from dataclasses import dataclass
from typing import Optional

from spans import SourceSpan


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
    span: Optional[SourceSpan] = None

    def to_dict(self):
        return {
            "kind": self.kind,
            "data": self.data,
            "span": self.span.to_dict() if self.span is not None else None,
        }
