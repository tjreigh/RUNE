from dataclasses import dataclass
from enum import Enum
from typing import Optional

from spans import SourceSpan


class DiagnosticKind(Enum):
    """Which stage produced the diagnostic."""
    LEX = "lex"
    PARSE = "parse"
    RUNTIME = "runtime"
    INTERNAL = "internal"
    LIMIT = "limit"


@dataclass
class Diagnostic:
    message: str
    kind: DiagnosticKind
    span: Optional[SourceSpan] = None

    def format(self):
        if self.span is None:
            return self.message
        return (
            f"line {self.span.start.line}, col {self.span.start.column}: "
            f"{self.message}"
        )

    def to_dict(self):
        return {
            "kind": self.kind.value,
            "message": self.message,
            "span": self.span.to_dict() if self.span is not None else None,
        }


class RuneError(Exception):
    """Common base for all structured RUNE diagnostics."""
    def __init__(self, diagnostic: Diagnostic):
        self.diagnostic = diagnostic
        super().__init__(diagnostic.format())


class RuneLexError(RuneError):
    def __init__(self, message: str, span: Optional[SourceSpan] = None):
        super().__init__(Diagnostic(message, DiagnosticKind.LEX, span))


class RuneParseError(RuneError):
    def __init__(self, message: str, span: Optional[SourceSpan] = None):
        super().__init__(Diagnostic(message, DiagnosticKind.PARSE, span))


class RuneRuntimeError(RuneError):
    """Deliberately does not subclass the builtin RuntimeError."""
    def __init__(self, message: str, span: Optional[SourceSpan] = None):
        super().__init__(Diagnostic(message, DiagnosticKind.RUNTIME, span))


class RuneInternalError(RuneError):
    """Raised for interpreter invariant violations that should never occur
    on a valid AST (distinct from RuneRuntimeError, which is a user
    program error)."""
    def __init__(self, message: str, span: Optional[SourceSpan] = None):
        super().__init__(Diagnostic(message, DiagnosticKind.INTERNAL, span))


class RuneLimitError(RuneError):
    """Raised when an execution limit (step, recursion, or output budget)
    is exceeded. A user/runtime failure, not an internal interpreter bug."""
    def __init__(self, message: str, span: Optional[SourceSpan] = None):
        super().__init__(Diagnostic(message, DiagnosticKind.LIMIT, span))
