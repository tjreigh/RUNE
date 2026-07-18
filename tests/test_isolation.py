import time

import pytest

from isolation import IsolationStatus, run_isolated, _atomic_write_json

# All targets must be module-level (picklable under the 'spawn' context).


def _fast_target(result_path):
    _atomic_write_json(result_path, {"hello": "world"})


def _slow_target(result_path):
    time.sleep(10)  # far longer than any timeout used below


def _no_write_target(result_path):
    raise SystemExit(1)  # exits non-zero, writes nothing


def _clean_exit_without_write_target(result_path):
    pass


def _oversized_result_target(result_path):
    _atomic_write_json(result_path, {"value": "x" * 1_000})


def _malformed_result_target(result_path):
    result_path.write_text("{not valid json")


def _write_then_hang_target(result_path):
    _atomic_write_json(result_path, {"hello": "world"})
    time.sleep(10)


def _partial_write_then_hang_target(result_path):
    tmp = result_path.with_suffix(result_path.suffix + ".tmp")
    tmp.write_text('{"incomplete": tr')  # never renamed to the final path
    time.sleep(10)


def _write_then_exit_nonzero_target(result_path):
    _atomic_write_json(result_path, {"hello": "world"})
    raise SystemExit(1)


def test_fast_target_returns_ok():
    result = run_isolated(_fast_target, timeout=2.0)
    assert result.status is IsolationStatus.OK
    assert result.value == {"hello": "world"}
    assert result.exitcode == 0


def test_slow_target_times_out():
    result = run_isolated(_slow_target, timeout=0.3, grace_period=0.2)
    assert result.status is IsolationStatus.TIMEOUT
    # exitcode is only ever set once multiprocessing has confirmed the
    # process actually terminated (via join()), so a populated exitcode
    # here -- rather than a bare elapsed-time check -- is the real proof
    # the process is gone, not just that a kill signal was sent.
    assert result.exitcode is not None


def test_no_write_target_is_crashed():
    result = run_isolated(_no_write_target, timeout=2.0)
    assert result.status is IsolationStatus.CRASHED
    assert result.exitcode == 1


def test_clean_exit_without_result_is_crashed():
    result = run_isolated(_clean_exit_without_write_target, timeout=2.0)
    assert result.status is IsolationStatus.CRASHED
    assert result.exitcode == 0


def test_oversized_result_file_is_crashed_without_loading_it():
    result = run_isolated(
        _oversized_result_target,
        timeout=2.0,
        max_result_bytes=100,
    )
    assert result.status is IsolationStatus.CRASHED
    assert result.exitcode == 0


def test_malformed_result_file_is_crashed():
    result = run_isolated(_malformed_result_target, timeout=2.0)
    assert result.status is IsolationStatus.CRASHED
    assert result.exitcode == 0


def test_write_then_hang_is_timeout_not_ok():
    """Deliberate behavior: a worker that successfully writes its result
    but then hangs afterward is TIMEOUT, not OK-with-the-value, because
    liveness is checked before the result file ever is."""
    result = run_isolated(_write_then_hang_target, timeout=0.3, grace_period=0.2)
    assert result.status is IsolationStatus.TIMEOUT
    assert result.exitcode is not None


def test_partial_write_then_hang_is_timeout():
    """The classic partial-message hazard a Pipe-based transport has --
    here it's a non-issue: a temp file that's never atomically renamed is
    simply never read, since the parent bails out on liveness first."""
    result = run_isolated(_partial_write_then_hang_target, timeout=0.3, grace_period=0.2)
    assert result.status is IsolationStatus.TIMEOUT


def test_write_then_exit_nonzero_is_crashed():
    """Exercises the exitcode == 0 gate specifically: a valid file exists,
    but the process itself didn't exit cleanly, so it's not trusted."""
    result = run_isolated(_write_then_exit_nonzero_target, timeout=2.0)
    assert result.status is IsolationStatus.CRASHED
    assert result.exitcode == 1


class _FakeProcess:
    def __init__(self):
        self.exitcode = None
        self.closed = False

    def start(self):
        raise OSError("fake process start failure")

    def is_alive(self):
        return False

    def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self, fake_proc):
        self._fake_proc = fake_proc

    def Process(self, target, args):
        return self._fake_proc


def test_isolation_infrastructure_failure_still_cleans_up():
    """If Process.start() itself raises, run_isolated must let the
    exception propagate (so evaluate_isolated's own except Exception can
    turn it into a generic 500) without a masking secondary exception from
    proc.close() -- and cleanup must still run."""
    fake_proc = _FakeProcess()
    with pytest.raises(OSError, match="fake process start failure"):
        run_isolated(_fast_target, mp_context=_FakeContext(fake_proc))
    assert fake_proc.closed
