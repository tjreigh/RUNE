import pytest

from lexer import Lexer
from tokens import TokenType
from spans import Position, SourceSpan
from diagnostics import RuneLexError


def _tokenize(src):
    return Lexer(src).tokenize()


def test_number_token():
    tokens = _tokenize("42")
    assert tokens[0].type == TokenType.NUMBER
    assert tokens[0].value == 42
    assert tokens[0].span == SourceSpan(Position(1, 1), Position(1, 3))
    assert tokens[-1].type == TokenType.EOF


def test_string_token():
    tokens = _tokenize('"cat"')
    assert tokens[0].type == TokenType.STRING
    assert tokens[0].value == "cat"
    assert tokens[0].span == SourceSpan(Position(1, 1), Position(1, 6))


def test_keyword_tokens():
    tokens = _tokenize("chaos if elif else end")
    types = [t.type for t in tokens[:-1]]
    assert types == [
        TokenType.CHAOS,
        TokenType.IF,
        TokenType.ELIF,
        TokenType.ELSE,
        TokenType.END,
    ]


def test_operator_and_structural_tokens():
    tokens = _tokenize("+-*()@")
    types = [t.type for t in tokens[:-1]]
    assert types == [
        TokenType.PLUS,
        TokenType.MINUS,
        TokenType.MULT,
        TokenType.LPAREN,
        TokenType.RPAREN,
        TokenType.PRAGMA,
    ]


@pytest.mark.parametrize(
    "src,expected_type",
    [
        ("<", TokenType.LT),
        (">", TokenType.GT),
        ("<=", TokenType.LTE),
        (">=", TokenType.GTE),
        ("==", TokenType.EQ),
        ("!=", TokenType.NEQ),
    ],
)
def test_comparison_operators(src, expected_type):
    tokens = _tokenize(src)
    assert tokens[0].type == expected_type
    assert tokens[1].type == TokenType.EOF


def test_multi_char_operators_do_not_over_consume():
    tokens = _tokenize("<= 5")
    assert tokens[0].type == TokenType.LTE
    assert tokens[0].span == SourceSpan(Position(1, 1), Position(1, 3))
    assert tokens[1].type == TokenType.NUMBER
    assert tokens[1].value == 5
    assert tokens[1].span == SourceSpan(Position(1, 4), Position(1, 5))


def test_span_tracking_multiline():
    tokens = _tokenize("1\n  22\n")
    assert tokens[0].type == TokenType.NUMBER
    assert tokens[0].span == SourceSpan(Position(1, 1), Position(1, 2))
    assert tokens[1].type == TokenType.NEWLINE
    assert tokens[1].span == SourceSpan(Position(1, 2), Position(2, 1))
    assert tokens[2].type == TokenType.NUMBER
    assert tokens[2].value == 22
    assert tokens[2].span == SourceSpan(Position(2, 3), Position(2, 5))
    assert tokens[3].type == TokenType.NEWLINE
    assert tokens[3].span == SourceSpan(Position(2, 5), Position(3, 1))
    assert tokens[4].type == TokenType.EOF
    assert tokens[4].span == SourceSpan.at(Position(3, 1))


def test_multiline_string_span_includes_quotes_and_newline():
    token = _tokenize('"a\nb"')[0]
    assert token.span == SourceSpan(Position(1, 1), Position(2, 3))


def test_unknown_identifier_raises_lex_error():
    with pytest.raises(RuneLexError) as exc_info:
        _tokenize("foo")
    assert exc_info.value.diagnostic.span == SourceSpan(
        Position(1, 1), Position(1, 4)
    )


def test_lone_equals_raises_lex_error():
    with pytest.raises(RuneLexError) as exc_info:
        _tokenize("1 = 2")
    assert exc_info.value.diagnostic.span == SourceSpan(
        Position(1, 3), Position(1, 4)
    )


def test_lone_bang_raises_lex_error():
    with pytest.raises(RuneLexError):
        _tokenize("1 ! 2")


def test_unknown_character_raises_lex_error():
    with pytest.raises(RuneLexError) as exc_info:
        _tokenize("#")
    assert exc_info.value.diagnostic.span == SourceSpan(
        Position(1, 1), Position(1, 2)
    )


def test_unterminated_string_raises_lex_error_at_opening_quote():
    with pytest.raises(RuneLexError) as exc_info:
        _tokenize('"unterminated')
    assert exc_info.value.diagnostic.span == SourceSpan(
        Position(1, 1), Position(1, 14)
    )
