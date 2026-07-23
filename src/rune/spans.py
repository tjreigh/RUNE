"""Source positions and half-open spans."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    """A 1-based line/column point in RUNE source."""
    line: int
    column: int

    def __repr__(self):
        return f"{self.line}:{self.column}"

    def to_dict(self):
        return {"line": self.line, "column": self.column}


@dataclass(frozen=True)
class SourceSpan:
    """An inclusive start and exclusive end range in RUNE source."""
    start: Position
    end: Position

    def __post_init__(self):
        if (self.end.line, self.end.column) < (self.start.line, self.start.column):
            raise ValueError("source span end must not precede its start")

    @classmethod
    def at(cls, position: Position):
        """Create a zero-width span at a position."""
        return cls(position, position)

    @classmethod
    def covering(cls, first, last):
        """Create a span from the start of one span through the end of another."""
        return cls(first.start, last.end)

    def __repr__(self):
        return f"{self.start!r}-{self.end!r}"

    def to_dict(self):
        return {"start": self.start.to_dict(), "end": self.end.to_dict()}
