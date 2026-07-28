"""Dynamic control context for one interpreter execution."""

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

from .spans import SourceSpan


class ExecutionFrameKind(Enum):
    FUNCTION = "function"
    WHILE = "while"
    FOR = "for"
    CHAOS = "chaos"


_LOOP_KINDS = frozenset({
    ExecutionFrameKind.WHILE,
    ExecutionFrameKind.FOR,
})


@dataclass
class ExecutionFrame:
    """One dynamically active language construct."""

    instance_id: int
    kind: ExecutionFrameKind
    span: SourceSpan | None = None
    name: str | None = None
    counter: str | None = None
    iteration: int = 0
    previous_chaos_threshold: int | None = None
    entered_chaos_threshold: int | None = None

    @property
    def is_loop(self):
        return self.kind in _LOOP_KINDS

    def to_dict(self):
        result = {
            "instance_id": self.instance_id,
            "kind": self.kind.value,
            "span": self.span.to_dict() if self.span is not None else None,
        }
        if self.name is not None:
            result["name"] = self.name
        if self.counter is not None:
            result["counter"] = self.counter
        if self.is_loop:
            result["iteration"] = self.iteration
        if self.kind is ExecutionFrameKind.CHAOS:
            result["previous_chaos_threshold"] = self.previous_chaos_threshold
            result["entered_chaos_threshold"] = self.entered_chaos_threshold
        return result


class ExecutionContext:
    """Stack of function, loop, and scoped-chaos frames.

    Unlike parser nesting, these frames represent actual dynamic invocations:
    recursive calls and repeated calls receive different instance IDs. Runtime
    control checks use this stack directly, and observers may consume detached
    snapshots without reconstructing Python's call stack.
    """

    def __init__(self):
        self._frames = []
        self._next_instance_id = 1

    @property
    def depth(self):
        return len(self._frames)

    @property
    def in_function(self):
        return self.active_function is not None

    @property
    def active_function(self):
        for frame in reversed(self._frames):
            if frame.kind is ExecutionFrameKind.FUNCTION:
                return frame
        return None

    @property
    def active_loop(self):
        """Nearest loop belonging to the current function invocation.

        A caller's loop is not a valid break/continue target for a called
        function, so the nearest function frame acts as a control barrier.
        """
        for frame in reversed(self._frames):
            if frame.is_loop:
                return frame
            if frame.kind is ExecutionFrameKind.FUNCTION:
                return None
        return None

    @property
    def active_chaos(self):
        for frame in reversed(self._frames):
            if frame.kind is ExecutionFrameKind.CHAOS:
                return frame
        return None

    def snapshot(self):
        """Return a detached, JSON-safe view in outermost-to-innermost order."""
        return [frame.to_dict() for frame in self._frames]

    def begin_loop_iteration(self, frame):
        if (
            not frame.is_loop
            or not any(active is frame for active in self._frames)
        ):
            raise RuntimeError("Cannot advance an inactive non-loop frame")
        frame.iteration += 1

    @contextmanager
    def frame(
        self,
        kind,
        *,
        span=None,
        name=None,
        counter=None,
        previous_chaos_threshold=None,
        entered_chaos_threshold=None,
    ):
        frame = ExecutionFrame(
            instance_id=self._next_instance_id,
            kind=kind,
            span=span,
            name=name,
            counter=counter,
            previous_chaos_threshold=previous_chaos_threshold,
            entered_chaos_threshold=entered_chaos_threshold,
        )
        self._next_instance_id += 1
        self._frames.append(frame)
        try:
            yield frame
        finally:
            popped = self._frames.pop()
            if popped is not frame:
                raise RuntimeError("Execution context stack corrupted")
