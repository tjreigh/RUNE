import time

import rune_worker
from rune_worker import _bounded_dict, evaluate_isolated


def _hanging_evaluator(source, state=None, limits=None):
    time.sleep(10)  # far longer than any timeout used in these tests


def _normal_result_dict():
    return {
        "ok": True, "values": [4], "diagnostics": [], "events": [],
        "state": {"chaos_threshold": 1},
        "stats": {"steps": 3, "peak_recursion_depth": 2, "output_values": 1},
    }


def test_bounded_dict_passes_through_normal_result():
    result = _normal_result_dict()
    bounded = _bounded_dict(result, {"chaos_threshold": 1})
    assert bounded == result


def test_bounded_dict_flags_over_byte_limit_result():
    oversized = {
        "ok": True, "values": ["x" * 100_000], "diagnostics": [], "events": [],
        "state": {"chaos_threshold": 1}, "stats": None,
    }
    bounded = _bounded_dict(oversized, {"chaos_threshold": 1})
    assert bounded["ok"] is False
    assert bounded["diagnostics"][0]["kind"] == "limit"
    assert bounded["diagnostics"][0]["message"] == "Result too large to serialize"
    assert bounded["state"] == {"chaos_threshold": 1}


def test_bounded_dict_flags_huge_integer_that_trips_json_conversion_limit():
    # Python 3.11+ caps int-to-str conversion at 4300 digits by default;
    # RUNE's `*` can produce an integer this large in very few steps.
    huge_int_result = {
        "ok": True, "values": [10 ** 5000], "diagnostics": [], "events": [],
        "state": {"chaos_threshold": 1},
        "stats": {"steps": 5, "peak_recursion_depth": 2, "output_values": 1},
    }
    bounded = _bounded_dict(huge_int_result, {"chaos_threshold": 1})
    assert bounded["ok"] is False
    assert bounded["diagnostics"][0]["kind"] == "limit"
    assert bounded["diagnostics"][0]["message"] == "Result too large to serialize"
    # stats are preserved from the original (oversized) result, not dropped
    assert bounded["stats"] == huge_int_result["stats"]


def test_evaluate_isolated_ok_translation():
    outcome = evaluate_isolated("2+2", {"chaos_threshold": 1})
    assert outcome.status_code == 200
    assert outcome.body["ok"] is True
    assert outcome.body["values"] == [4]


def test_evaluate_isolated_restores_variable_state_in_worker():
    outcome = evaluate_isolated(
        "answer + 1",
        {"chaos_threshold": 1, "variables": {"answer": 41}},
    )
    assert outcome.status_code == 200
    assert outcome.body["ok"] is True
    assert outcome.body["values"] == [42]


def test_evaluate_isolated_timeout_translation():
    outcome = evaluate_isolated(
        "2+2", {"chaos_threshold": 1}, timeout=0.3, worker_evaluator=_hanging_evaluator
    )
    assert outcome.status_code == 200
    assert outcome.body["ok"] is False
    assert outcome.body["diagnostics"][0]["kind"] == "limit"
    assert outcome.body["diagnostics"][0]["message"] == "Wall-clock timeout exceeded"
    assert outcome.body["state"] == {"chaos_threshold": 1}


def _raising_evaluator(source, state=None, limits=None):
    raise RuntimeError("boom")


def test_evaluate_isolated_crash_translation_end_to_end():
    """The complete chain: real spawn -> real exception in a genuine
    subprocess -> SystemExit(1) -> CRASHED classification ->
    WorkerOutcome(500, ...). Proves the exception's own text never
    reaches the returned envelope -- not a fabricated IsolationResult."""
    outcome = evaluate_isolated(
        "2+2", {"chaos_threshold": 7}, worker_evaluator=_raising_evaluator
    )
    assert outcome.status_code == 500
    assert outcome.body["ok"] is False
    assert outcome.body["diagnostics"][0]["kind"] == "internal"
    assert outcome.body["diagnostics"][0]["message"] == (
        "Evaluation process terminated unexpectedly"
    )
    assert "boom" not in str(outcome.body)
    # original state echoed back untouched
    assert outcome.body["state"] == {"chaos_threshold": 7}


def test_evaluate_isolated_isolation_layer_failure_returns_generic_500():
    def _fake_run_isolated(*args, **kwargs):
        raise OSError("infra exploded")

    original = rune_worker.run_isolated
    rune_worker.run_isolated = _fake_run_isolated
    try:
        outcome = evaluate_isolated("2+2", {"chaos_threshold": 1})
    finally:
        rune_worker.run_isolated = original

    assert outcome.status_code == 500
    assert "infra exploded" not in str(outcome.body)
    assert outcome.body["diagnostics"][0]["kind"] == "internal"
