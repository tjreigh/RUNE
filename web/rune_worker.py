"""RUNE-specific layer on top of web/isolation.py.

This is the only module in web/ that touches the core (src/). It inserts
src/ onto sys.path at import time so it can import runtime/limits/
diagnostics without needing PYTHONPATH set externally -- mirroring exactly
what pytest's `pythonpath` ini option already does for the test suite.
"""

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from diagnostics import DiagnosticKind  # noqa: E402
from limits import ExecutionLimits  # noqa: E402
from runtime import evaluate  # noqa: E402
from runtime_state import RuntimeState  # noqa: E402

from isolation import IsolationStatus, run_isolated  # noqa: E402

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES = 64 * 1024
MAX_WORKER_ADDRESS_SPACE_BYTES = 192 * 1024 * 1024


def _apply_worker_resource_limits() -> None:
    """Cap a production evaluator before it runs untrusted RUNE code.

    RLIMIT_AS is Unix-specific and its behavior varies outside Linux, so local
    development platforms retain the language-level and subprocess limits.
    The deployment's systemd cgroup remains the aggregate Linux backstop.
    """
    if not sys.platform.startswith("linux"):
        return

    import resource

    _, hard_limit = resource.getrlimit(resource.RLIMIT_AS)
    soft_limit = MAX_WORKER_ADDRESS_SPACE_BYTES
    if hard_limit != resource.RLIM_INFINITY:
        soft_limit = min(soft_limit, hard_limit)
    resource.setrlimit(resource.RLIMIT_AS, (soft_limit, hard_limit))


def _atomic_write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj))
    tmp.replace(path)


def _oversized_envelope(state_dict: dict, stats) -> dict:
    return {
        "ok": False,
        "values": [],
        "diagnostics": [{
            "kind": DiagnosticKind.LIMIT.value,
            "message": "Result too large to serialize",
            "span": None,
        }],
        "events": [],
        "state": state_dict,
        "stats": stats,
    }


def _memory_limit_envelope(state_dict: dict) -> dict:
    return {
        "ok": False,
        "values": [],
        "diagnostics": [{
            "kind": DiagnosticKind.LIMIT.value,
            "message": "Evaluation memory limit exceeded",
            "span": None,
        }],
        "events": [],
        "state": state_dict,
        "stats": None,
    }


def _bounded_dict(result_dict: dict, state_dict: dict) -> dict:
    """Keep serialization bounded even if a future core invariant regresses."""
    try:
        text = json.dumps(result_dict)
    except (ValueError, OverflowError):
        return _oversized_envelope(state_dict, result_dict.get("stats"))
    if len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
        return _oversized_envelope(state_dict, result_dict.get("stats"))
    return result_dict


def _worker_entrypoint(result_path, source, state_dict, evaluator=evaluate):
    """`evaluator` is injectable (defaults to runtime.evaluate) so tests can
    force a deterministic crash through the real spawn path -- a
    monkeypatch applied in the pytest parent process has no effect inside a
    freshly spawned 'spawn'-context child, which re-imports everything
    fresh."""
    try:
        _apply_worker_resource_limits()
        state = RuntimeState(
            chaos_threshold=state_dict.get("chaos_threshold", 1),
            variables=state_dict.get("variables", {}),
        )
        result = evaluator(source, state=state, limits=ExecutionLimits())
        bounded = _bounded_dict(result.to_dict(), state_dict)
        _atomic_write_json(result_path, bounded)
    except MemoryError:
        try:
            _atomic_write_json(result_path, _memory_limit_envelope(state_dict))
        except Exception:
            logger.exception("RUNE worker could not report its memory limit")
            raise SystemExit(1)
    except Exception:
        logger.exception("RUNE evaluation worker crashed")
        # No file written -- the parent sees "exited, no result" -> CRASHED.
        # Exit non-zero deliberately (SystemExit, not a re-raised
        # traceback) so the process's own exit status honestly reflects
        # the failure, matching run_isolated()'s exitcode == 0 gate.
        raise SystemExit(1)


@dataclass
class WorkerOutcome:
    status_code: int
    body: dict


def _timeout_envelope(state_dict: dict) -> dict:
    return {
        "ok": False,
        "values": [],
        "diagnostics": [{
            "kind": DiagnosticKind.LIMIT.value,
            "message": "Wall-clock timeout exceeded",
            "span": None,
        }],
        "events": [],
        "state": state_dict,
        "stats": None,
    }


def _crashed_envelope(state_dict: dict) -> dict:
    return {
        "ok": False,
        "values": [],
        "diagnostics": [{
            "kind": DiagnosticKind.INTERNAL.value,
            "message": "Evaluation process terminated unexpectedly",
            "span": None,
        }],
        "events": [],
        "state": state_dict,
        "stats": None,
    }


def evaluate_isolated(
    source: str,
    state_dict: dict,
    timeout: float = 2.0,
    worker_evaluator=evaluate,
) -> WorkerOutcome:
    """`worker_evaluator` is threaded through to _worker_entrypoint so a
    test can pass a real, module-level, picklable failing evaluator (e.g.
    a `_raising_evaluator`) all the way through the actual spawn ->
    exception -> SystemExit(1) -> CRASHED -> WorkerOutcome(500, ...) path,
    proving end-to-end that the exception's own text never reaches the
    returned envelope."""
    try:
        result = run_isolated(
            _worker_entrypoint,
            args=(source, state_dict, worker_evaluator),
            timeout=timeout,
        )
    except Exception:
        # The isolation machinery itself faulted (e.g. Process.start()
        # failing) -- never let a raw framework traceback reach a client.
        logger.exception("Isolation infrastructure failure")
        return WorkerOutcome(500, _crashed_envelope(state_dict))

    if result.status is IsolationStatus.OK:
        return WorkerOutcome(200, result.value)
    if result.status is IsolationStatus.TIMEOUT:
        return WorkerOutcome(200, _timeout_envelope(state_dict))  # rejected workload
    return WorkerOutcome(500, _crashed_envelope(state_dict))       # infra fault
