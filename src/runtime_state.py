from dataclasses import dataclass
from typing import Optional

from spans import Position


@dataclass(frozen=True)
class RuntimeState:
    """Serializable interpreter state, threaded between evaluations."""
    chaos_threshold: int = 1

    def to_dict(self):
        return {"chaos_threshold": self.chaos_threshold}


@dataclass(frozen=True)
class RuntimeEvent:
    """A structured record of an interpreter side effect (e.g. a pragma),
    so callers can format it (--verbose) without the interpreter printing."""
    kind: str
    data: dict
    position: Optional[Position] = None

    def to_dict(self):
        return {
            "kind": self.kind,
            "data": self.data,
            "position": self.position.to_dict() if self.position is not None else None,
        }
