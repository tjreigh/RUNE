import pytest

from spans import Position, SourceSpan
from diagnostics import (
    Diagnostic,
    DiagnosticKind,
    RuneError,
    RuneLexError,
    RuneParseError,
    RuneRuntimeError,
    RuneInternalError,
    RuneLimitError,
)


def test_format_with_span_uses_its_start():
    diag = Diagnostic(
        "bad thing",
        DiagnosticKind.LEX,
        SourceSpan(Position(3, 5), Position(3, 8)),
    )
    assert diag.format() == "line 3, col 5: bad thing"


def test_format_without_span():
    diag = Diagnostic("bad thing", DiagnosticKind.LEX, None)
    assert diag.format() == "bad thing"


@pytest.mark.parametrize(
    "error_cls,kind",
    [
        (RuneLexError, DiagnosticKind.LEX),
        (RuneParseError, DiagnosticKind.PARSE),
        (RuneRuntimeError, DiagnosticKind.RUNTIME),
        (RuneInternalError, DiagnosticKind.INTERNAL),
        (RuneLimitError, DiagnosticKind.LIMIT),
    ],
)
def test_exception_hierarchy_and_kind(error_cls, kind):
    span = SourceSpan(Position(1, 1), Position(1, 2))
    err = error_cls("oops", span)
    assert isinstance(err, RuneError)
    assert err.diagnostic.kind == kind
    assert err.diagnostic.span == span


def test_rune_runtime_error_does_not_subclass_builtin_runtime_error():
    assert not issubclass(RuneRuntimeError, RuntimeError)


def test_str_matches_diagnostic_format():
    err = RuneLexError(
        "bad thing", SourceSpan(Position(2, 4), Position(2, 5))
    )
    assert str(err) == err.diagnostic.format()


def test_diagnostic_serializes_full_span_without_legacy_position():
    diag = Diagnostic(
        "bad thing",
        DiagnosticKind.PARSE,
        SourceSpan(Position(2, 4), Position(3, 2)),
    )
    assert diag.to_dict() == {
        "kind": "parse",
        "message": "bad thing",
        "span": {
            "start": {"line": 2, "column": 4},
            "end": {"line": 3, "column": 2},
        },
    }
