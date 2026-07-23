from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class BindingFrame:
    """One ephemeral lexical scope layered above persistent runtime state."""

    values: dict[str, int]
    captures_assignments: bool = False
    isolates_parent_bindings: bool = False


class BindingEnvironment:
    """Stack of ephemeral lexical bindings.

    Persistent session variables remain in ``RuntimeState`` and are supplied
    as the root mapping during lookup. Loop counters use non-capturing frames.
    Function frames capture otherwise-new assignments and isolate reads from
    caller frames, while still falling back to the persistent root.
    """

    def __init__(self):
        self._frames = []

    @property
    def depth(self):
        return len(self._frames)

    @property
    def binding_count(self):
        return sum(len(frame.values) for frame in self._frames)

    @contextmanager
    def frame(
        self,
        values=None,
        captures_assignments=False,
        isolates_parent_bindings=False,
    ):
        frame = BindingFrame(
            dict(values or {}),
            captures_assignments,
            isolates_parent_bindings,
        )
        self._frames.append(frame)
        try:
            yield frame
        finally:
            popped = self._frames.pop()
            if popped is not frame:
                raise RuntimeError("Lexical binding stack corrupted")

    def resolve(self, name, root):
        """Return the nearest binding, falling back to the persistent root."""
        for frame in reversed(self._frames):
            if name in frame.values:
                return frame.values[name]
            if frame.isolates_parent_bindings:
                break
        if name in root:
            return root[name]
        raise KeyError(name)

    def assignment_target(self, name):
        """Return the nearest frame that owns or captures this assignment."""
        for frame in reversed(self._frames):
            if name in frame.values or frame.captures_assignments:
                return frame
            if frame.isolates_parent_bindings:
                break
        return None
