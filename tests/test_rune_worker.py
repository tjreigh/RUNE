import sys
import time
from types import SimpleNamespace

import pytest

import rune_worker
from isolation import IsolationStatus
from rune_worker import _bounded_dict, evaluate_isolated


def _hanging_evaluator(source, state=None, limits=None):
    time.sleep(10)  # far longer than any timeout used in these tests


def _memory_error_evaluator(source, state=None, limits=None):
    raise MemoryError


def _unbounded_rune_evaluator(source, state=None, limits=None):
    """Test-only evaluator proving the process deadline is independent of
    interpreter budgets."""
    from limits import ExecutionLimits
    from runtime import evaluate

    return evaluate(source, state=state, limits=ExecutionLimits.unbounded())


def _normal_result_dict():
    return {
        "ok": True, "values": [4], "diagnostics": [], "events": [],
        "state": {"chaos_threshold": 1},
        "stats": {"steps": 3, "peak_recursion_depth": 2, "output_values": 1},
    }


def _resource_limit_probe(result_path):
    import resource

    rune_worker._apply_worker_resource_limits()
    rune_worker._atomic_write_json(
        result_path,
        {
            "address_space": resource.getrlimit(resource.RLIMIT_AS),
            "cpu": resource.getrlimit(resource.RLIMIT_CPU),
            "file_size": resource.getrlimit(resource.RLIMIT_FSIZE),
            "core_dump": resource.getrlimit(resource.RLIMIT_CORE),
        },
    )


def test_linux_worker_resource_limits_are_made_irreversible(monkeypatch):
    calls = []
    limits = {
        1: (-1, -1),
        2: (-1, -1),
        3: (-1, -1),
        4: (-1, -1),
    }
    fake_resource = SimpleNamespace(
        RLIMIT_CORE=1,
        RLIMIT_FSIZE=2,
        RLIMIT_CPU=3,
        RLIMIT_AS=4,
        RLIM_INFINITY=-1,
        getrlimit=lambda kind: limits[kind],
        setrlimit=lambda kind, limits: calls.append((kind, limits)),
    )
    monkeypatch.setattr(rune_worker.sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "resource", fake_resource)

    rune_worker._apply_worker_resource_limits()

    assert calls == [
        (fake_resource.RLIMIT_CORE, (0, 0)),
        (
            fake_resource.RLIMIT_FSIZE,
            (rune_worker.MAX_WORKER_FILE_BYTES, rune_worker.MAX_WORKER_FILE_BYTES),
        ),
        (
            fake_resource.RLIMIT_CPU,
            (rune_worker.MAX_WORKER_CPU_SECONDS, rune_worker.MAX_WORKER_CPU_SECONDS),
        ),
        (
            fake_resource.RLIMIT_AS,
            (
                rune_worker.MAX_WORKER_ADDRESS_SPACE_BYTES,
                rune_worker.MAX_WORKER_ADDRESS_SPACE_BYTES,
            ),
        ),
    ]


def test_resource_limit_respects_lower_inherited_hard_limit():
    calls = []
    fake_resource = SimpleNamespace(
        RLIM_INFINITY=-1,
        getrlimit=lambda kind: (50, 100),
        setrlimit=lambda kind, limits: calls.append((kind, limits)),
    )

    rune_worker._lower_hard_resource_limit(fake_resource, 7, 200)

    assert calls == [(7, (100, 100))]


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="production rlimits are Linux-specific",
)
def test_spawned_linux_child_reports_effective_hard_resource_limits():
    result = rune_worker.run_isolated(_resource_limit_probe)

    assert result.status is IsolationStatus.OK
    expected_maximums = {
        "address_space": rune_worker.MAX_WORKER_ADDRESS_SPACE_BYTES,
        "cpu": rune_worker.MAX_WORKER_CPU_SECONDS,
        "file_size": rune_worker.MAX_WORKER_FILE_BYTES,
        "core_dump": 0,
    }
    for name, maximum in expected_maximums.items():
        soft, hard = result.value[name]
        assert soft == hard
        assert hard <= maximum


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


def test_worker_always_supplies_finite_interpreter_limits(monkeypatch, tmp_path):
    observed = {}

    def evaluator(source, state=None, limits=None):
        observed["limits"] = limits
        return SimpleNamespace(to_dict=_normal_result_dict)

    monkeypatch.setattr(rune_worker, "_apply_worker_resource_limits", lambda: None)
    result_path = tmp_path / "result.json"

    rune_worker._worker_entrypoint(
        result_path,
        "2 + 2",
        {"chaos_threshold": 1},
        evaluator=evaluator,
    )

    assert result_path.exists()
    assert observed["limits"].is_unbounded is False
    assert all(
        value is not None
        for value in (
            observed["limits"].max_steps,
            observed["limits"].max_recursion_depth,
            observed["limits"].max_output_values,
            observed["limits"].max_variables,
            observed["limits"].max_integer_bits,
            observed["limits"].max_events,
        )
    )


def test_real_infinite_loop_hits_finite_worker_step_budget_transactionally():
    initial_state = {
        "chaos_threshold": 1,
        "variables": {"kept": 7},
    }
    outcome = evaluate_isolated(
        "temporary = 9\nwhile (1)\nend while",
        initial_state,
    )

    assert outcome.status_code == 200
    assert outcome.body["ok"] is False
    assert outcome.body["diagnostics"][0]["kind"] == "limit"
    assert outcome.body["diagnostics"][0]["message"] == "Step budget exceeded"
    assert outcome.body["state"] == initial_state
    assert outcome.body["values"] == []
    assert outcome.body["events"] == []
    assert outcome.body["stats"]["loop_iterations"] > 0


def test_evaluate_isolated_timeout_translation():
    outcome = evaluate_isolated(
        "2+2", {"chaos_threshold": 1}, timeout=0.3, worker_evaluator=_hanging_evaluator
    )
    assert outcome.status_code == 200
    assert outcome.body["ok"] is False
    assert outcome.body["diagnostics"][0]["kind"] == "limit"
    assert outcome.body["diagnostics"][0]["message"] == "Wall-clock timeout exceeded"
    assert outcome.body["state"] == {"chaos_threshold": 1}


def test_unbounded_rune_loop_is_killed_by_worker_wall_clock_timeout():
    initial_state = {
        "chaos_threshold": 1,
        "variables": {"kept": 7},
    }
    outcome = evaluate_isolated(
        "temporary = 9\nwhile (1)\nend while",
        initial_state,
        timeout=0.5,
        worker_evaluator=_unbounded_rune_evaluator,
    )

    assert outcome.status_code == 200
    assert outcome.body["ok"] is False
    assert outcome.body["diagnostics"][0]["kind"] == "limit"
    assert outcome.body["diagnostics"][0]["message"] == (
        "Wall-clock timeout exceeded"
    )
    assert outcome.body["state"] == initial_state
    assert outcome.body["values"] == []
    assert outcome.body["events"] == []


def test_evaluate_isolated_memory_error_becomes_limit_outcome():
    outcome = evaluate_isolated(
        "2+2",
        {"chaos_threshold": 7},
        worker_evaluator=_memory_error_evaluator,
    )

    assert outcome.status_code == 200
    assert outcome.body["ok"] is False
    assert outcome.body["diagnostics"][0]["kind"] == "limit"
    assert outcome.body["diagnostics"][0]["message"] == (
        "Evaluation memory limit exceeded"
    )
    assert outcome.body["state"] == {"chaos_threshold": 7}


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
