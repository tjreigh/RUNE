from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    """A 1-based line/column point in RUNE source."""
    line: int
    column: int

    def __repr__(self):
        return f"{self.line}:{self.column}"
