import pytest

from spans import Position
from diagnostics import (
    Diagnostic,
    DiagnosticKind,
    RuneError,
    RuneLexError,
    RuneParseError,
    RuneRuntimeError,
    RuneInternalError,
)


def test_format_with_position():
    diag = Diagnostic("bad thing", DiagnosticKind.LEX, Position(3, 5))
    assert diag.format() == "line 3, col 5: bad thing"


def test_format_without_position():
    diag = Diagnostic("bad thing", DiagnosticKind.LEX, None)
    assert diag.format() == "bad thing"


@pytest.mark.parametrize(
    "error_cls,kind",
    [
        (RuneLexError, DiagnosticKind.LEX),
        (RuneParseError, DiagnosticKind.PARSE),
        (RuneRuntimeError, DiagnosticKind.RUNTIME),
        (RuneInternalError, DiagnosticKind.INTERNAL),
    ],
)
def test_exception_hierarchy_and_kind(error_cls, kind):
    err = error_cls("oops", Position(1, 1))
    assert isinstance(err, RuneError)
    assert err.diagnostic.kind == kind
    assert err.diagnostic.position == Position(1, 1)


def test_rune_runtime_error_does_not_subclass_builtin_runtime_error():
    assert not issubclass(RuneRuntimeError, RuntimeError)


def test_str_matches_diagnostic_format():
    err = RuneLexError("bad thing", Position(2, 4))
    assert str(err) == err.diagnostic.format()
