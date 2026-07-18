import asyncio
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx2")

from fastapi.testclient import TestClient

import app as app_module
from app import FixedWindowRateLimiter, MaxBodySizeMiddleware, create_app
from rune_worker import WorkerOutcome
from sessions import SessionStore


def test_normal_evaluation():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={"source": "2+2"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["values"] == [4]
    assert body["state"] == {"chaos_threshold": 1}
    assert len(body["session_id"]) >= 32


def test_lex_error_returns_200_with_diagnostic():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={"source": "#"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["diagnostics"][0]["kind"] == "lex"


def test_parse_error_returns_200_with_diagnostic():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={"source": "if (1)\n1\n"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["diagnostics"][0]["kind"] == "parse"


def test_state_persists_by_opaque_session_id():
    client = TestClient(create_app())
    first = client.post("/evaluate", json={"source": "@chaos 500"})
    assert first.json()["state"] == {"chaos_threshold": 500}
    session_id = first.json()["session_id"]

    second = client.post("/evaluate", json={
        "source": 'if ("dog" > "cat")\n1\nelse\n0\nend',
        "session_id": session_id,
    })
    assert second.json()["values"] == [0]
    assert second.json()["session_id"] == session_id


def test_client_supplied_runtime_state_is_rejected():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={
        "source": "1", "state": {"chaos_threshold": -1},
    })
    assert response.status_code == 422


def test_client_cannot_inject_state_using_an_old_state_shape():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={
        "source": "1", "state": {"chaos_threshold": "500"},
    })
    assert response.status_code == 422

    float_response = client.post("/evaluate", json={
        "source": "1", "state": {"chaos_threshold": 500.0},
    })
    assert float_response.status_code == 422


def test_unknown_fields_are_rejected():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={
        "source": "1", "state": {"chaos_threshold": 1, "extra": "nope"},
    })
    assert response.status_code == 422


def test_client_supplied_limits_field_is_rejected():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={
        "source": "1", "limits": {"max_steps": 999_999_999},
    })
    assert response.status_code == 422


def test_oversized_source_returns_413():
    client = TestClient(create_app(max_source_length=10))
    response = client.post("/evaluate", json={"source": "1" * 1000})
    assert response.status_code == 413


def test_streaming_body_over_limit_without_honest_content_length():
    """Proves the real byte-counting middleware, not just the
    Content-Length fast pre-check: the body is sent via a generator so
    httpx uses chunked transfer with no Content-Length header at all."""
    app = create_app(max_request_bytes=100)
    client = TestClient(app)
    payload = json.dumps({"source": "x" * 1000}).encode()

    def gen():
        yield payload

    response = client.post(
        "/evaluate", content=gen(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 413


def test_content_length_fast_precheck_and_exact_body_boundary():
    client = TestClient(create_app(max_request_bytes=20))

    rejected = client.post(
        "/evaluate",
        content=b'{}',
        headers={"content-type": "application/json", "content-length": "21"},
    )
    assert rejected.status_code == 413

    exact_body = b'{"source":"1234567"}'
    assert len(exact_body) == 20
    accepted = client.post(
        "/evaluate",
        content=exact_body,
        headers={"content-type": "application/json"},
    )
    assert accepted.status_code == 200


def test_malformed_content_length_falls_back_to_actual_body_size():
    client = TestClient(create_app(max_request_bytes=100))
    response = client.post(
        "/evaluate",
        content=b'{"source":"2+2"}',
        headers={"content-type": "application/json", "content-length": "nope"},
    )
    assert response.status_code == 200


def test_chunk_count_cap_rejects_pathological_stream(monkeypatch):
    monkeypatch.setattr(app_module, "MAX_CHUNKS", 1)

    async def exercise():
        messages = iter([
            {"type": "http.request", "body": b'{"source":"', "more_body": True},
            {"type": "http.request", "body": b'2+2"}', "more_body": False},
        ])
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        async def downstream(scope, receive, send):
            raise AssertionError("oversized chunk stream reached downstream app")

        middleware = MaxBodySizeMiddleware(downstream, max_bytes=100)
        await middleware(
            {"type": "http", "path": "/evaluate", "headers": []},
            receive,
            send,
        )
        return sent

    sent = asyncio.run(exercise())
    assert sent[0]["status"] == 413


def test_concurrency_cap_returns_503_then_recovers():
    app = create_app(max_concurrency=1)
    client = TestClient(app)

    acquired = app.state.concurrency_semaphore.acquire(blocking=False)
    assert acquired
    try:
        response = client.post("/evaluate", json={"source": "2+2"})
        assert response.status_code == 503
    finally:
        app.state.concurrency_semaphore.release()

    recovered = client.post("/evaluate", json={"source": "2+2"})
    assert recovered.status_code == 200


def test_rate_limit_returns_429_on_second_request():
    app = create_app(rate_limit_max=1, rate_limit_window=60.0)
    client = TestClient(app)

    first = client.post("/evaluate", json={"source": "2+2"})
    assert first.status_code == 200

    second = client.post("/evaluate", json={"source": "2+2"})
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"


def test_rate_limiter_hard_caps_unique_client_buckets():
    limiter = FixedWindowRateLimiter(
        max_requests=1,
        window_seconds=60.0,
        max_buckets=1,
    )

    assert limiter.allow("client-a")
    assert not limiter.allow("client-b")


def test_invalid_request_counts_toward_rate_limit():
    client = TestClient(create_app(rate_limit_max=1, rate_limit_window=60.0))

    invalid = client.post("/evaluate", json={"source": "1", "limits": {}})
    assert invalid.status_code == 422

    valid = client.post("/evaluate", json={"source": "2+2"})
    assert valid.status_code == 429


def test_malformed_json_counts_toward_rate_limit():
    client = TestClient(create_app(rate_limit_max=1, rate_limit_window=60.0))

    malformed = client.post(
        "/evaluate",
        content=b"{",
        headers={"content-type": "application/json"},
    )
    assert malformed.status_code == 422

    valid = client.post("/evaluate", json={"source": "2+2"})
    assert valid.status_code == 429


def test_oversized_request_counts_toward_rate_limit():
    client = TestClient(create_app(
        rate_limit_max=1,
        rate_limit_window=60.0,
        max_request_bytes=100,
    ))

    oversized = client.post("/evaluate", json={"source": "x" * 1_000})
    assert oversized.status_code == 413

    valid = client.post("/evaluate", json={"source": "2+2"})
    assert valid.status_code == 429


def _fake_timeout_evaluator(source, state_dict, timeout=2.0):
    return WorkerOutcome(200, {
        "ok": False, "values": [],
        "diagnostics": [{"kind": "limit", "message": "Wall-clock timeout exceeded", "span": None}],
        "events": [], "state": state_dict, "stats": None,
    })


def _fake_crash_evaluator(source, state_dict, timeout=2.0):
    return WorkerOutcome(500, {
        "ok": False, "values": [],
        "diagnostics": [{"kind": "internal", "message": "Evaluation process terminated unexpectedly", "span": None}],
        "events": [], "state": state_dict, "stats": None,
    })


def test_endpoint_maps_timeout_outcome_to_200():
    client = TestClient(create_app(evaluator=_fake_timeout_evaluator))
    response = client.post("/evaluate", json={"source": "2+2"})
    assert response.status_code == 200
    assert response.json()["diagnostics"][0]["kind"] == "limit"
    assert "session_id" in response.json()


def test_endpoint_maps_crash_outcome_to_500():
    client = TestClient(create_app(evaluator=_fake_crash_evaluator))
    response = client.post("/evaluate", json={"source": "2+2"})
    assert response.status_code == 500
    assert response.json()["diagnostics"][0]["kind"] == "internal"
    assert "session_id" in response.json()


def test_huge_integer_source_returns_limit_diagnostic_not_500():
    client = TestClient(create_app())
    # Three ~2200-digit literals multiplied together produce a ~6600-digit
    # result in only 2 multiplications (5 steps, recursion depth 3) --
    # comfortably within every ExecutionLimits default, while still
    # exceeding Python 3.11+'s 4300-digit int-to-str conversion limit at
    # serialization time. Exercises the real evaluate_isolated() path (not
    # a fake evaluator), through the actual worker's _bounded_dict.
    base = "9" * 2200
    source = f"{base}*{base}*{base}"
    response = client.post("/evaluate", json={"source": source})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["diagnostics"][0]["message"] == "Result too large to serialize"


def test_oversized_integer_literal_returns_lex_diagnostic_not_500():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={"source": "9" * 4_301})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["diagnostics"][0]["kind"] == "lex"
    assert "4300-digit limit" in body["diagnostics"][0]["message"]


def test_root_route_serves_html():
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="chaos-level">1<' in response.text
    assert 'href="/static/style.css"' in response.text
    assert 'src="/static/app.js"' in response.text


def test_static_css_and_javascript_are_served_separately():
    client = TestClient(create_app())

    css = client.get("/static/style.css")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]

    javascript = client.get("/static/app.js")
    assert javascript.status_code == 200
    assert "javascript" in javascript.headers["content-type"]
    assert "payload.session_id = sessionId" in javascript.text
    assert 'fetch("/reset"' in javascript.text
    assert "payload.state" not in javascript.text


def test_default_state_behavior():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={"source": "2+2"})
    assert response.json()["state"] == {"chaos_threshold": 1}


def test_variables_persist_across_web_evaluations():
    client = TestClient(create_app())
    assigned = client.post("/evaluate", json={"source": "answer = 40"}).json()
    session_id = assigned["session_id"]

    updated = client.post("/evaluate", json={
        "source": "answer = answer + 2",
        "session_id": session_id,
    })
    assert updated.status_code == 200
    assert updated.json()["state"]["variables"] == {"answer": 42}

    looked_up = client.post("/evaluate", json={
        "source": "answer",
        "session_id": session_id,
    })
    assert looked_up.json()["values"] == [42]


def test_sessions_cannot_read_or_mutate_each_other():
    client = TestClient(create_app())
    first = client.post("/evaluate", json={"source": "value = 1"}).json()
    second = client.post("/evaluate", json={"source": "value = 2"}).json()
    assert first["session_id"] != second["session_id"]

    first_value = client.post("/evaluate", json={
        "source": "value",
        "session_id": first["session_id"],
    })
    second_value = client.post("/evaluate", json={
        "source": "value",
        "session_id": second["session_id"],
    })
    assert first_value.json()["values"] == [1]
    assert second_value.json()["values"] == [2]


def test_failed_evaluation_does_not_commit_partial_variable_state():
    client = TestClient(create_app())
    first = client.post("/evaluate", json={"source": "value = 1"}).json()
    session_id = first["session_id"]

    failed = client.post("/evaluate", json={
        "source": "value = 2\nmissing",
        "session_id": session_id,
    })
    assert failed.json()["ok"] is False
    assert failed.json()["state"]["variables"] == {"value": 1}

    unchanged = client.post("/evaluate", json={
        "source": "value",
        "session_id": session_id,
    })
    assert unchanged.json()["values"] == [1]


def test_unknown_or_expired_session_id_is_not_accepted():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={
        "source": "1",
        "session_id": "x" * 43,
    })
    assert response.status_code == 404
    assert response.json()["detail"] == "session not found or expired"


def test_reset_deletes_server_side_session_state():
    client = TestClient(create_app())
    created = client.post("/evaluate", json={"source": "answer = 42"}).json()

    reset = client.post("/reset", json={"session_id": created["session_id"]})
    assert reset.status_code == 204

    missing = client.post("/evaluate", json={
        "source": "answer",
        "session_id": created["session_id"],
    })
    assert missing.status_code == 404


def test_session_capacity_is_bounded_and_reset_releases_capacity():
    store = SessionStore(max_sessions=1)
    client = TestClient(create_app(session_store=store))
    first = client.post("/evaluate", json={"source": "1"}).json()

    full = client.post("/evaluate", json={"source": "1"})
    assert full.status_code == 503
    assert full.json()["detail"] == "session capacity reached"

    client.post("/reset", json={"session_id": first["session_id"]})
    recovered = client.post("/evaluate", json={"source": "1"})
    assert recovered.status_code == 200


def _oversized_state_evaluator(source, state_dict, timeout=2.0):
    return WorkerOutcome(200, {
        "ok": True,
        "values": [],
        "diagnostics": [],
        "events": [],
        "state": {"chaos_threshold": 1, "variables": {"huge": 10 ** 200}},
        "stats": None,
    })


def test_oversized_session_state_is_rejected_without_committing():
    store = SessionStore(max_state_bytes=100)
    client = TestClient(create_app(
        session_store=store,
        evaluator=_oversized_state_evaluator,
    ))
    response = client.post("/evaluate", json={"source": "anything"})
    body = response.json()

    assert response.status_code == 200
    assert body["ok"] is False
    assert body["diagnostics"][0]["kind"] == "limit"
    assert body["diagnostics"][0]["message"] == "Session state is too large"
    session = store.resolve(body["session_id"])
    assert store.snapshot(session) == {"chaos_threshold": 1}


def _invalid_state_evaluator(source, state_dict, timeout=2.0):
    return WorkerOutcome(200, {
        "ok": True,
        "values": [],
        "diagnostics": [],
        "events": [],
        "state": {"not_runtime_state": True},
        "stats": None,
    })


def test_invalid_evaluator_state_is_a_generic_500_and_is_not_committed():
    client = TestClient(create_app(evaluator=_invalid_state_evaluator))
    response = client.post("/evaluate", json={"source": "anything"})

    assert response.status_code == 500
    assert response.json()["diagnostics"][0]["message"] == (
        "Evaluation process returned invalid state"
    )
