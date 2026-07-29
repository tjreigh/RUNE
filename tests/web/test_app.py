import asyncio
import json
from pathlib import Path
import threading

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx2")

from fastapi.testclient import TestClient

from rune_web import app as app_module
from rune_web.app import FixedWindowRateLimiter, MaxBodySizeMiddleware, create_app
from rune_web.worker import WorkerOutcome
from rune_web.sessions import SessionStore


def test_validation_accepts_valid_source_without_evaluation_fields():
    client = TestClient(create_app())
    response = client.post("/validate", json={"source": "missing_variable"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "diagnostics": []}


def test_validation_and_evaluation_use_the_function_grammar():
    client = TestClient(create_app())
    source = (
        "function add(a, b)\nreturn a + b\nend function\nadd(20, 22)"
    )

    validated = client.post("/validate", json={"source": source})
    evaluated = client.post("/evaluate", json={"source": source})

    assert validated.status_code == 200
    assert validated.json() == {"ok": True, "diagnostics": []}
    assert evaluated.status_code == 200
    assert evaluated.json()["values"] == [42]


def test_web_sessions_do_not_persist_function_declarations():
    client = TestClient(create_app())
    declared = client.post(
        "/evaluate",
        json={
            "source": (
                "function answer()\nreturn 42\nend function\nanswer()"
            )
        },
    ).json()

    later = client.post(
        "/evaluate",
        json={
            "source": "answer()",
            "session_id": declared["session_id"],
        },
    )

    assert declared["values"] == [42]
    assert later.status_code == 200
    assert later.json()["ok"] is False
    assert later.json()["diagnostics"][0]["message"] == (
        "Undefined function 'answer'"
    )


@pytest.mark.parametrize("source", ["", " \t\r\n"])
def test_validation_keeps_empty_source_neutral(source):
    client = TestClient(create_app())
    response = client.post("/validate", json={"source": source})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "diagnostics": []}


@pytest.mark.parametrize(
    ("source", "kind", "line", "column"),
    [
        ("$", "lex", 1, 1),
        ("\N{NO-BREAK SPACE}", "lex", 1, 1),
        ("if (1)\n1\n", "parse", 3, 1),
    ],
)
def test_validation_diagnostics_exactly_match_evaluation(
    source, kind, line, column
):
    app = create_app()
    client = TestClient(app)

    validated = client.post("/validate", json={"source": source})
    evaluated = client.post("/evaluate", json={"source": source})

    assert validated.status_code == 200
    assert validated.json()["ok"] is False
    assert validated.json()["diagnostics"] == evaluated.json()["diagnostics"]
    diagnostic = validated.json()["diagnostics"][0]
    assert diagnostic["kind"] == kind
    assert diagnostic["span"]["start"] == {"line": line, "column": column}


def test_validation_accepts_only_source_field():
    client = TestClient(create_app())

    with_session = client.post(
        "/validate",
        json={"source": "1", "session_id": "x" * 43},
    )
    with_state = client.post(
        "/validate",
        json={"source": "1", "state": {"chaos_threshold": 500}},
    )

    assert with_session.status_code == 422
    assert with_state.status_code == 422


def test_validation_never_creates_or_mutates_sessions():
    store = SessionStore()
    client = TestClient(create_app(session_store=store))

    assert client.post(
        "/validate", json={"source": "answer = 99"}
    ).status_code == 200
    assert store.session_count == 0

    evaluated = client.post(
        "/evaluate", json={"source": "answer = 42"}
    ).json()
    session = store.resolve(evaluated["session_id"])
    before = store.snapshot(session)

    client.post("/validate", json={"source": "answer = 99"})

    assert store.session_count == 1
    assert store.snapshot(session) == before


def test_validation_source_and_streaming_body_limits():
    client = TestClient(create_app(max_source_length=10, max_request_bytes=100))

    oversized_source = client.post(
        "/validate", json={"source": "1" * 11}
    )

    def oversized_chunks():
        yield json.dumps({"source": "1" * 1_000}).encode()

    oversized_body = client.post(
        "/validate",
        content=oversized_chunks(),
        headers={"content-type": "application/json"},
    )

    assert oversized_source.status_code == 413
    assert oversized_body.status_code == 413


def test_validation_hostile_literal_and_nesting_are_structured():
    client = TestClient(create_app())

    literal = client.post("/validate", json={"source": "9" * 4_301})
    nested = client.post(
        "/validate",
        json={"source": "(" * 101 + "1" + ")" * 101},
    )

    assert literal.status_code == 200
    assert literal.json()["diagnostics"][0]["kind"] == "lex"
    assert "4300-digit limit" in literal.json()["diagnostics"][0]["message"]
    assert nested.status_code == 200
    assert nested.json()["diagnostics"][0]["kind"] == "parse"
    assert "nesting exceeds" in nested.json()["diagnostics"][0]["message"]


def test_validation_concurrency_cap_is_separate_and_recovers():
    app = create_app(max_concurrency=1, validation_max_concurrency=1)
    client = TestClient(app)

    assert app.state.validation_concurrency_semaphore.acquire(blocking=False)
    try:
        busy = client.post("/validate", json={"source": "2+2"})
        evaluation = client.post("/evaluate", json={"source": "2+2"})
    finally:
        app.state.validation_concurrency_semaphore.release()

    recovered = client.post("/validate", json={"source": "2+2"})
    assert busy.status_code == 503
    assert evaluation.status_code == 200
    assert recovered.status_code == 200


def test_default_validation_concurrency_is_bounded_to_four():
    app = create_app()
    semaphore = app.state.validation_concurrency_semaphore

    for _ in range(4):
        assert semaphore.acquire(blocking=False)
    assert not semaphore.acquire(blocking=False)
    for _ in range(4):
        semaphore.release()


def test_validation_has_separate_client_rate_limit():
    client = TestClient(create_app(
        rate_limit_max=1,
        validation_rate_limit_max=1,
        rate_limit_window=60.0,
    ))

    assert client.post("/validate", json={"source": "1"}).status_code == 200
    limited = client.post("/validate", json={"source": "2"})
    evaluation = client.post("/evaluate", json={"source": "2"})

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert evaluation.status_code == 200


def test_invalid_validation_request_counts_toward_its_rate_limit():
    client = TestClient(create_app(
        validation_rate_limit_max=1,
        rate_limit_window=60.0,
    ))

    invalid = client.post(
        "/validate", json={"source": "1", "unexpected": True}
    )
    limited = client.post("/validate", json={"source": "1"})

    assert invalid.status_code == 422
    assert limited.status_code == 429


def test_global_validation_rate_limit_bounds_all_clients():
    app = create_app(
        validation_rate_limit_max=10,
        validation_global_rate_limit_max=1,
        rate_limit_window=60.0,
    )
    first_client = TestClient(app, client=("client-a", 50_000))
    second_client = TestClient(app, client=("client-b", 50_001))

    assert first_client.post(
        "/validate", json={"source": "1"}
    ).status_code == 200
    limited = second_client.post("/validate", json={"source": "2"})

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"


def test_missing_frontend_build_fails_clearly(monkeypatch, tmp_path):
    monkeypatch.setattr(
        app_module,
        "FRONTEND_ENTRYPOINT",
        tmp_path / "missing-app.js",
    )

    with pytest.raises(RuntimeError, match="yarn install.*yarn build"):
        create_app()


def test_normal_evaluation():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={"source": "2+2"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["values"] == [4]
    assert body["state"] == {"chaos_threshold": 1}
    assert len(body["session_id"]) >= 32


def test_debug_creates_a_session_but_never_commits_traced_state():
    store = SessionStore()
    client = TestClient(create_app(session_store=store))

    traced = client.post(
        "/debug",
        json={"source": "answer = 42\nanswer"},
    )

    assert traced.status_code == 200
    body = traced.json()
    assert body["ok"] is True
    assert body["artifact_available"] is True
    assert body["base_state"] == {"chaos_threshold": 1}
    assert body["frames"][-1]["status"] == "completed"
    session = store.resolve(body["session_id"])
    assert store.snapshot(session) == {"chaos_threshold": 1}

    later = client.post(
        "/evaluate",
        json={"source": "answer", "session_id": body["session_id"]},
    )
    assert later.json()["ok"] is False
    assert later.json()["diagnostics"][0]["message"] == (
        "Undefined variable 'answer'"
    )


def test_debug_uses_existing_committed_session_state_without_replacing_it():
    store = SessionStore()
    client = TestClient(create_app(session_store=store))
    created = client.post(
        "/evaluate",
        json={"source": "answer = 41"},
    ).json()

    traced = client.post(
        "/debug",
        json={
            "source": "answer = 42\nanswer",
            "session_id": created["session_id"],
        },
    ).json()

    assert traced["base_state"]["variables"] == {"answer": 41}
    session = store.resolve(created["session_id"])
    assert store.snapshot(session)["variables"] == {"answer": 41}


def test_debug_rejects_a_result_if_reset_superseded_its_session():
    store = SessionStore()
    session_id, _session = store.create()

    def resetting_debugger(source, state_dict, timeout=2.0):
        store.reset(session_id)
        return WorkerOutcome(200, {
            "ok": True,
            "artifact_available": True,
            "diagnostics": [],
            "base_state": state_dict,
            "frames": [],
        })

    client = TestClient(create_app(
        session_store=store,
        debugger=resetting_debugger,
    ))
    response = client.post(
        "/debug",
        json={"source": "1", "session_id": session_id},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "session was reset during debugging"


def test_debug_and_evaluation_serialize_on_the_same_session_lock():
    store = SessionStore()
    session_id, session = store.create()
    store.commit(
        session_id,
        session,
        {"chaos_threshold": 1, "variables": {"answer": 1}},
    )
    debug_started = threading.Event()
    release_debug = threading.Event()
    evaluation_started = threading.Event()

    def blocking_debugger(source, state_dict, timeout=2.0):
        debug_started.set()
        assert release_debug.wait(2)
        return WorkerOutcome(200, {
            "ok": True,
            "artifact_available": True,
            "diagnostics": [],
            "base_state": state_dict,
            "frames": [],
        })

    def recording_evaluator(source, state_dict, timeout=2.0):
        evaluation_started.set()
        return WorkerOutcome(200, {
            "ok": True,
            "values": [],
            "diagnostics": [],
            "events": [],
            "state": {
                "chaos_threshold": 1,
                "variables": {"answer": 2},
            },
            "stats": None,
        })

    app = create_app(
        session_store=store,
        debugger=blocking_debugger,
        evaluator=recording_evaluator,
    )
    debug_client = TestClient(app)
    evaluation_client = TestClient(app)
    responses = {}

    debug_thread = threading.Thread(
        target=lambda: responses.setdefault(
            "debug",
            debug_client.post(
                "/debug",
                json={"source": "answer", "session_id": session_id},
            ),
        )
    )
    debug_thread.start()
    assert debug_started.wait(2)

    evaluation_thread = threading.Thread(
        target=lambda: responses.setdefault(
            "evaluate",
            evaluation_client.post(
                "/evaluate",
                json={"source": "answer = 2", "session_id": session_id},
            ),
        )
    )
    evaluation_thread.start()
    assert not evaluation_started.wait(0.1)

    release_debug.set()
    debug_thread.join(2)
    evaluation_thread.join(2)

    assert not debug_thread.is_alive()
    assert not evaluation_thread.is_alive()
    assert responses["debug"].status_code == 200
    assert responses["evaluate"].status_code == 200
    assert store.snapshot(session)["variables"] == {"answer": 2}


def test_lex_error_returns_200_with_diagnostic():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={"source": "$"})
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
        "source": 'if ("dog" > "cat")\n1\nelse\n0\nend if',
        "session_id": session_id,
    })
    assert second.json()["values"] == [0]
    assert second.json()["session_id"] == session_id


def test_stale_client_reusing_returned_state_is_told_to_reload():
    store = SessionStore()
    client = TestClient(create_app(session_store=store))
    first = client.post("/evaluate", json={"source": "@chaos 500"})
    assert first.status_code == 200

    response = client.post("/evaluate", json={
        "source": "2+2",
        "state": first.json()["state"],
    })
    assert response.status_code == 409
    assert response.json() == {
        "detail": "This RUNE page is out of date. Reload the page before running again."
    }
    assert response.headers["cache-control"] == "no-store"
    assert store.session_count == 1


def test_stale_client_response_does_not_depend_on_injected_state_shape():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={
        "source": "1", "state": {"chaos_threshold": "500"},
    })
    assert response.status_code == 409

    float_response = client.post("/evaluate", json={
        "source": "1", "state": {"chaos_threshold": 500.0},
    })
    assert float_response.status_code == 409


def test_unknown_fields_are_rejected():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={
        "source": "1", "unexpected": "nope",
    })
    assert response.status_code == 422


def test_client_supplied_limits_field_is_rejected():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={
        "source": "1", "limits": {"max_steps": 999_999_999},
    })
    assert response.status_code == 422


def test_debug_accepts_only_source_and_optional_session_id():
    client = TestClient(create_app())

    limits = client.post(
        "/debug",
        json={"source": "1", "limits": {"max_frames": 1}},
    )
    state = client.post(
        "/debug",
        json={"source": "1", "state": {"chaos_threshold": 1}},
    )

    assert limits.status_code == 422
    assert state.status_code == 409


def test_oversized_source_returns_413():
    client = TestClient(create_app(max_source_length=10))
    response = client.post("/evaluate", json={"source": "1" * 1000})
    assert response.status_code == 413


def test_oversized_debug_source_returns_413():
    client = TestClient(create_app(max_source_length=10))
    response = client.post("/debug", json={"source": "1" * 1000})
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
        debug = client.post("/debug", json={"source": "2+2"})
        assert response.status_code == 503
        assert debug.status_code == 503
    finally:
        app.state.concurrency_semaphore.release()

    recovered = client.post("/evaluate", json={"source": "2+2"})
    assert recovered.status_code == 200


def test_default_concurrency_is_bounded_to_two_evaluations():
    app = create_app()
    semaphore = app.state.concurrency_semaphore
    assert semaphore.acquire(blocking=False)
    assert semaphore.acquire(blocking=False)
    assert not semaphore.acquire(blocking=False)
    semaphore.release()
    semaphore.release()


def test_rate_limit_returns_429_on_second_request():
    app = create_app(rate_limit_max=1, rate_limit_window=60.0)
    client = TestClient(app)

    first = client.post("/evaluate", json={"source": "2+2"})
    assert first.status_code == 200

    second = client.post("/evaluate", json={"source": "2+2"})
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"


def test_debug_and_evaluate_share_execution_rate_limit():
    client = TestClient(create_app(
        rate_limit_max=1,
        rate_limit_window=60.0,
    ))

    first = client.post("/debug", json={"source": "1"})
    second = client.post("/evaluate", json={"source": "1"})

    assert first.status_code == 200
    assert second.status_code == 429


def test_global_evaluation_rate_limit_bounds_all_clients():
    app = create_app(
        rate_limit_max=10,
        global_rate_limit_max=1,
        rate_limit_window=60.0,
    )
    first_client = TestClient(app, client=("client-a", 50_000))
    second_client = TestClient(app, client=("client-b", 50_001))

    first = first_client.post("/evaluate", json={"source": "2+2"})
    assert first.status_code == 200

    second = second_client.post("/evaluate", json={"source": "2+2"})
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"


def test_new_session_rate_limit_does_not_block_existing_session():
    store = SessionStore()
    client = TestClient(create_app(
        session_store=store,
        rate_limit_max=10,
        global_rate_limit_max=10,
        new_session_rate_limit_max=1,
    ))

    created = client.post("/evaluate", json={"source": "answer = 42"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    rejected = client.post("/evaluate", json={"source": "1"})
    assert rejected.status_code == 429
    assert rejected.json()["detail"] == "new session rate limit exceeded"
    assert rejected.headers["retry-after"] == "60"
    assert store.session_count == 1

    debug_rejected = client.post("/debug", json={"source": "answer"})
    assert debug_rejected.status_code == 429

    existing = client.post(
        "/debug",
        json={"source": "answer", "session_id": session_id},
    )
    assert existing.status_code == 200
    assert existing.json()["base_state"]["variables"] == {"answer": 42}


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


def _fake_timeout_debugger(source, state_dict, timeout=2.0):
    return WorkerOutcome(200, {
        "ok": False,
        "artifact_available": False,
        "diagnostics": [{
            "kind": "limit",
            "message": "Tracing wall-clock timeout exceeded",
            "span": None,
        }],
        "base_state": None,
        "frames": [],
    })


def _fake_crash_debugger(source, state_dict, timeout=2.0):
    return WorkerOutcome(500, {
        "ok": False,
        "artifact_available": False,
        "diagnostics": [{
            "kind": "internal",
            "message": "Tracing process terminated unexpectedly",
            "span": None,
        }],
        "base_state": None,
        "frames": [],
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


def test_debug_endpoint_preserves_timeout_and_crash_outcome_statuses():
    timeout_client = TestClient(create_app(debugger=_fake_timeout_debugger))
    crash_client = TestClient(create_app(debugger=_fake_crash_debugger))

    timed_out = timeout_client.post("/debug", json={"source": "1"})
    crashed = crash_client.post("/debug", json={"source": "1"})

    assert timed_out.status_code == 200
    assert timed_out.json()["artifact_available"] is False
    assert "session_id" in timed_out.json()
    assert crashed.status_code == 500
    assert crashed.json()["artifact_available"] is False
    assert "session_id" in crashed.json()


def test_huge_integer_source_returns_limit_diagnostic_not_500():
    client = TestClient(create_app())
    # Three ~2200-digit literals multiplied together produce a ~6600-digit
    # mathematical result in only 2 multiplications. Core preflight must reject
    # it before allocation while the real isolated-worker path remains healthy.
    base = "9" * 2200
    source = f"{base}*{base}*{base}"
    response = client.post("/evaluate", json={"source": source})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["diagnostics"][0]["kind"] == "limit"
    assert "Integer magnitude exceeds" in body["diagnostics"][0]["message"]


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
    assert response.headers["cache-control"] == "no-store"
    assert 'id="chaos-level">1<' in response.text
    assert '<option value="variables">Variables</option>' in response.text
    assert '<option value="expressions">Expressions</option>' in response.text
    assert '<option value="logic">Chaos-aware logic</option>' in response.text
    assert '<option value="loops">Loops</option>' in response.text
    assert '<option value="functions">Functions and recursion</option>' in response.text
    assert "answer = answer + 2" in response.text
    assert '<details id="inspector" class="inspector">' in response.text
    assert 'role="tablist" aria-label="Runtime internals"' in response.text
    assert response.text.count('role="tabpanel"') == 4
    assert 'id="inspector-state">Chaos threshold: 1' in response.text
    assert 'id="validation-status"' in response.text
    assert 'role="status"' in response.text
    assert 'id="highlighting-content"' in response.text
    assert 'id="trace-highlighting-content"' in response.text
    assert 'id="debug"' in response.text
    assert 'id="restart"' in response.text
    assert 'id="step-back"' in response.text
    assert 'id="step-over"' in response.text
    assert 'id="step-out"' in response.text
    assert 'id="play"' in response.text
    assert 'id="playback-speed-control"' in response.text
    assert 'id="playback-speed"' in response.text
    assert 'id="playback-speed-value"' in response.text
    assert 'id="runtime-state"' in response.text
    assert 'id="inspector-context"' in response.text
    assert 'id="source-position"' in response.text
    assert 'id="editor-theme"' in response.text
    assert 'id="page-theme"' in response.text
    assert '<option value="system">System</option>' in response.text
    assert '<option value="classic-dark">Classic Dark</option>' in response.text
    assert '<option value="ultraviolet">Ultraviolet</option>' in response.text
    assert '<option value="classic-light">Classic Light</option>' in response.text
    assert '<option value="cool-light">Cool Light</option>' in response.text
    assert 'data-page-theme="system"' in response.text
    assert 'data-editor-theme="classic-dark"' in response.text
    header = response.text.split('<header class="site-header">', 1)[1].split(
        "</header>", 1
    )[0]
    assert 'id="page-theme"' in header
    assert 'id="guide-heading">How RUNE works<' in response.text
    assert "<p>version 0.9</p>" in response.text
    assert "Truth has a lifetime" in response.text
    assert "<dt>Temporary chaos</dt>" in response.text
    assert "<code>end chaos</code>" in response.text
    assert "Strings collapse to the sum of their Unicode code points" in response.text
    assert 'href="/static/style.css?v=0.9.0"' in response.text
    assert 'src="/static/build/app.js?v=0.9.0" type="module"' in response.text


def test_static_css_and_javascript_are_served_separately():
    client = TestClient(create_app())

    css = client.get("/static/style.css")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert css.headers["cache-control"] == "no-cache"
    assert "@media (prefers-color-scheme: dark)" in css.text
    assert '[data-page-theme="system"]' in css.text
    assert '[data-editor-theme="ultraviolet"]' in css.text
    assert '[data-editor-theme="cool-light"]' in css.text

    javascript = client.get("/static/build/app.js")
    editor = client.get("/static/build/editor.js")
    formatters = client.get("/static/build/formatters.js")
    repl = client.get("/static/build/repl.js")
    trace_player = client.get("/static/build/trace-player.js")
    assert javascript.status_code == 200
    assert editor.status_code == 200
    assert formatters.status_code == 200
    assert repl.status_code == 200
    assert trace_player.status_code == 200
    assert "javascript" in javascript.headers["content-type"]
    assert "javascript" in editor.headers["content-type"]
    assert "javascript" in formatters.headers["content-type"]
    assert "javascript" in repl.headers["content-type"]
    assert "javascript" in trace_player.headers["content-type"]
    assert javascript.headers["cache-control"] == "no-cache"
    assert editor.headers["cache-control"] == "no-cache"
    assert formatters.headers["cache-control"] == "no-cache"
    assert repl.headers["cache-control"] == "no-cache"
    assert trace_player.headers["cache-control"] == "no-cache"
    assert 'import { startRuneRepl } from "./repl.js"' in javascript.text
    assert "payload.session_id = sessionId" in repl.text
    assert "`/examples/${encodeURIComponent(key)}.rune`" in repl.text
    assert "0 and missing" not in repl.text
    assert "function factorial(n)" not in repl.text
    assert 'fetch("/reset"' in repl.text
    assert 'fetch("/validate"' in repl.text
    assert 'fetch("/debug"' in repl.text
    assert "validationController.abort()" in repl.text
    assert "mySeq !== validationRequestSeq" in repl.text
    assert "}, 300);" in repl.text
    assert "setSelectionRange(start, end)" in repl.text
    assert "function highlightRune(source)" in editor.text
    assert "updateEditorHighlighting()" in repl.text
    assert "syncEditorScroll" in repl.text
    assert "class TracePlayback" in trace_player.text
    assert 'localStorage.setItem("rune-editor-theme"' in repl.text
    assert 'localStorage.setItem("rune-page-theme"' in repl.text
    assert "payload.state" not in repl.text
    assert "inspectorStateEl.textContent = formatState(heldState)" in repl.text
    assert "heldEvents = result.events ?? []" in repl.text
    assert "heldStats = result.stats ?? null" in repl.text
    assert "Runtime events: ${stats.runtime_events}" in formatters.text
    assert "Loop iterations: ${stats.loop_iterations}" in formatters.text
    assert "formatRequestDetail(body.detail ?? body)" in repl.text
    assert "[object Object]" not in repl.text
    assert "sessionId" not in formatters.text


@pytest.mark.parametrize(
    "name",
    [
        "smoke",
        "variables",
        "expressions",
        "logic",
        "chaos",
        "loops",
        "functions",
        "full",
    ],
)
def test_example_gallery_serves_canonical_valid_source(name):
    client = TestClient(create_app())
    example_path = (
        Path(__file__).resolve().parents[2] / "examples" / f"{name}.rune"
    )

    response = client.get(f"/examples/{name}.rune")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.text == example_path.read_text()
    assert client.post("/validate", json={"source": response.text}).json() == {
        "ok": True,
        "diagnostics": [],
    }


def test_default_state_behavior():
    client = TestClient(create_app())
    response = client.post("/evaluate", json={"source": "2+2"})
    assert response.json()["state"] == {"chaos_threshold": 1}


def test_variables_persist_across_web_evaluations():
    client = TestClient(create_app())
    assigned = client.post("/evaluate", json={"source": "answer = 40"}).json()
    session_id = assigned["session_id"]
    assert assigned["events"][0]["kind"] == "variable_assigned"
    assert assigned["stats"]["steps"] > 0

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
    assert failed.json()["events"] == []
    assert failed.json()["stats"]["steps"] > 0

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

    debug = client.post("/debug", json={
        "source": "1",
        "session_id": "x" * 43,
    })
    assert debug.status_code == 404
    assert debug.json()["detail"] == "session not found or expired"


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
