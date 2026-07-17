from dataclasses import dataclass
from enum import Enum
from typing import Optional

from spans import Position


class DiagnosticKind(Enum):
    """Which stage produced the diagnostic."""
    LEX = "lex"
    PARSE = "parse"
    RUNTIME = "runtime"
    INTERNAL = "internal"


@dataclass
class Diagnostic:
    message: str
    kind: DiagnosticKind
    position: Optional[Position] = None

    def format(self):
        if self.position is None:
            return self.message
        return f"line {self.position.line}, col {self.position.column}: {self.message}"

    def to_dict(self):
        return {
            "kind": self.kind.value,
            "message": self.message,
            "position": self.position.to_dict() if self.position is not None else None,
        }


class RuneError(Exception):
    """Common base for all structured RUNE diagnostics."""
    def __init__(self, diagnostic: Diagnostic):
        self.diagnostic = diagnostic
        super().__init__(diagnostic.format())


class RuneLexError(RuneError):
    def __init__(self, message: str, position: Optional[Position] = None):
        super().__init__(Diagnostic(message, DiagnosticKind.LEX, position))


class RuneParseError(RuneError):
    def __init__(self, message: str, position: Optional[Position] = None):
        super().__init__(Diagnostic(message, DiagnosticKind.PARSE, position))


class RuneRuntimeError(RuneError):
    """Deliberately does not subclass the builtin RuntimeError."""
    def __init__(self, message: str, position: Optional[Position] = None):
        super().__init__(Diagnostic(message, DiagnosticKind.RUNTIME, position))


class RuneInternalError(RuneError):
    """Raised for interpreter invariant violations that should never occur
    on a valid AST (distinct from RuneRuntimeError, which is a user
    program error)."""
    def __init__(self, message: str, position: Optional[Position] = None):
        super().__init__(Diagnostic(message, DiagnosticKind.INTERNAL, position))
