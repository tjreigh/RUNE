import pytest

from spans import Position, SourceSpan


def test_zero_width_span():
    position = Position(4, 2)
    assert SourceSpan.at(position) == SourceSpan(position, position)


def test_multiline_span_serialization():
    span = SourceSpan(Position(2, 4), Position(3, 2))
    assert span.to_dict() == {
        "start": {"line": 2, "column": 4},
        "end": {"line": 3, "column": 2},
    }


def test_covering_uses_first_start_and_last_end():
    first = SourceSpan(Position(1, 2), Position(1, 4))
    last = SourceSpan(Position(2, 1), Position(2, 5))
    assert SourceSpan.covering(first, last) == SourceSpan(
        Position(1, 2), Position(2, 5)
    )


def test_span_end_cannot_precede_start():
    with pytest.raises(ValueError):
        SourceSpan(Position(2, 1), Position(1, 5))
