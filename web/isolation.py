"""Generic, RUNE-agnostic subprocess isolation helper.

Runs a module-level target function in a fresh, disposable
multiprocessing.Process (spawn context) and reaps it within a hard
wall-clock deadline. Deliberately not a Pipe-based design: Connection.poll()
returning true only means *some* bytes are readable, not that a complete
pickled message is available, so a subsequent blocking recv() on a partial
message could hang past the deadline -- undermining the entire isolation
guarantee. Process.join(timeout) has no such ambiguity: it is a real,
atomic, OS-level wait with a genuine timeout. The target instead writes its
result to a private temp file (atomically renamed on success); the parent
only ever inspects that file after confirming (via join) that the process
has actually exited within the deadline.

Also not concurrent.futures.ProcessPoolExecutor: Future.result(timeout=N)
timing out does not terminate the underlying pooled worker -- a hung task
keeps running in that process, exactly the failure mode this module exists
to prevent.
"""

import json
import multiprocessing as mp
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class IsolationStatus(Enum):
    OK = "ok"
    TIMEOUT = "timeout"
    CRASHED = "crashed"


@dataclass
class IsolationResult:
    status: IsolationStatus
    value: Any = None
    exitcode: int | None = None


def _atomic_write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj))
    tmp.replace(path)  # atomic on POSIX -- readers never see a partial file


def _shutdown(proc: mp.process.BaseProcess, grace_period: float) -> None:
    """Idempotent: safe to call on an unstarted, already-exited, or live
    process. The only place terminate()/kill() are ever invoked."""
    if not proc.is_alive():
        return
    proc.terminate()
    proc.join(grace_period)
    if proc.is_alive():
        proc.kill()
        proc.join()


def run_isolated(
    target,
    args=(),
    timeout: float = 2.0,
    grace_period: float = 0.5,
    mp_context=None,
    max_result_bytes: int = 1_000_000,
) -> IsolationResult:
    """target(result_path, *args) must be module-level (picklable under
    'spawn') and write its result via _atomic_write_json(result_path, ...)
    on success, or exit non-zero (writing nothing) on failure.

    A result is trusted as OK only when the process exited with code 0 AND
    wrote a valid, bounded-size file -- checked in that order, so a
    crashed process's stale/partial file (if any) is never read, and a
    faulty target can't force the parent to load an arbitrarily large file.

    Deliberate behavior: a worker that successfully writes its result file
    but then hangs afterward is classified TIMEOUT, not OK with the value,
    because liveness is checked before the file ever is. Safer (no
    ambiguity about whether a "wrote-then-hung" child is truly done) at the
    cost of discarding an already-computed value in that specific edge
    case.
    """
    ctx = mp_context or mp.get_context("spawn")
    with tempfile.TemporaryDirectory() as tmp_dir:  # private dir: safer
        result_path = Path(tmp_dir) / "result.json"  # perms, no shared-tmp
        proc = None                                   # collisions/symlinks
        try:
            proc = ctx.Process(target=target, args=(result_path, *args))
            proc.start()
            proc.join(timeout)

            timed_out = proc.is_alive()
            _shutdown(proc, grace_period)  # ensures stopped either way
            exitcode = proc.exitcode

            if timed_out:
                return IsolationResult(IsolationStatus.TIMEOUT, exitcode=exitcode)
            if exitcode != 0:
                return IsolationResult(IsolationStatus.CRASHED, exitcode=exitcode)
            if not result_path.exists():
                return IsolationResult(IsolationStatus.CRASHED, exitcode=exitcode)
            try:
                if result_path.stat().st_size > max_result_bytes:
                    return IsolationResult(IsolationStatus.CRASHED, exitcode=exitcode)
                value = json.loads(result_path.read_text())
            except (json.JSONDecodeError, OSError, UnicodeError):
                return IsolationResult(IsolationStatus.CRASHED, exitcode=exitcode)
            return IsolationResult(IsolationStatus.OK, value=value, exitcode=exitcode)
        finally:
            if proc is not None:
                _shutdown(proc, grace_period)  # safety net (e.g. proc.start() raised)
                proc.close()                    # only after confirmed stopped
