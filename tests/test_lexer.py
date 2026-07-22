import pytest

from lexer import (
    Lexer,
    MAX_INTEGER_LITERAL_BITS,
    MAX_INTEGER_LITERAL_DIGITS,
    MAX_PREFIXED_INTEGER_LITERAL_DIGITS,
)
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


def test_integer_literal_over_digit_limit_raises_structured_lex_error():
    source = "9" * (MAX_INTEGER_LITERAL_DIGITS + 1)

    with pytest.raises(RuneLexError) as exc_info:
        _tokenize(source)

    diagnostic = exc_info.value.diagnostic
    assert diagnostic.message == (
        f"Integer literal exceeds the {MAX_INTEGER_LITERAL_DIGITS}-digit limit"
    )
    assert diagnostic.span == SourceSpan(
        Position(1, 1), Position(1, MAX_INTEGER_LITERAL_DIGITS + 2)
    )


def test_integer_literal_at_digit_limit_is_accepted():
    token = _tokenize("9" * MAX_INTEGER_LITERAL_DIGITS)[0]

    assert token.type == TokenType.NUMBER
    assert isinstance(token.value, int)


@pytest.mark.parametrize(
    "source,expected",
    [
        ("0b101101", 45),
        ("0B101101", 45),
        ("0o755", 493),
        ("0O755", 493),
        ("0xCAFE", 51_966),
        ("0Xcafe", 51_966),
    ],
)
def test_prefixed_integer_literals_become_number_tokens(source, expected):
    token = _tokenize(source)[0]

    assert token.type == TokenType.NUMBER
    assert token.value == expected
    assert token.span == SourceSpan(Position(1, 1), Position(1, len(source) + 1))


def test_prefixed_integer_does_not_consume_following_operator():
    tokens = _tokenize("0x10+0b1")

    assert [token.type for token in tokens[:-1]] == [
        TokenType.NUMBER,
        TokenType.PLUS,
        TokenType.NUMBER,
    ]
    assert [token.value for token in tokens[:-1]] == [16, "+", 1]


@pytest.mark.parametrize("source", ["0b", "0B", "0o", "0O", "0x", "0X"])
def test_prefixed_integer_literal_requires_digits(source):
    with pytest.raises(RuneLexError) as exc_info:
        _tokenize(source)

    assert exc_info.value.diagnostic.message == f"Expected digits after '{source}'"
    assert exc_info.value.diagnostic.span == SourceSpan(
        Position(1, 1), Position(1, 3)
    )


@pytest.mark.parametrize(
    "source,label,invalid",
    [
        ("0b102", "binary", "2"),
        ("0o789", "octal", "8"),
        ("0xCAFEG", "hexadecimal", "G"),
        ("0b10_01", "binary", "_"),
    ],
)
def test_invalid_prefixed_integer_digit_has_one_precise_diagnostic(
    source, label, invalid
):
    with pytest.raises(RuneLexError) as exc_info:
        _tokenize(source)

    assert exc_info.value.diagnostic.message == (
        f"Invalid digit {invalid!r} in {label} integer literal"
    )
    assert exc_info.value.diagnostic.span == SourceSpan(
        Position(1, 1), Position(1, len(source) + 1)
    )


@pytest.mark.parametrize(
    "prefix,base,leading_digit",
    [("0b", 2, "1"), ("0o", 8, "1"), ("0x", 16, "1")],
)
def test_prefixed_integer_at_text_and_magnitude_limit_is_accepted(
    prefix, base, leading_digit
):
    digit_count = MAX_PREFIXED_INTEGER_LITERAL_DIGITS[base]
    token = _tokenize(prefix + leading_digit + ("0" * (digit_count - 1)))[0]

    assert token.type == TokenType.NUMBER
    assert token.value.bit_length() <= MAX_INTEGER_LITERAL_BITS


@pytest.mark.parametrize(
    "prefix,base",
    [("0b", 2), ("0o", 8), ("0x", 16)],
)
def test_prefixed_integer_over_text_limit_is_rejected(prefix, base):
    digit_count = MAX_PREFIXED_INTEGER_LITERAL_DIGITS[base] + 1

    with pytest.raises(RuneLexError) as exc_info:
        _tokenize(prefix + ("1" * digit_count))

    assert exc_info.value.diagnostic.message.endswith(
        f"exceeds the {MAX_PREFIXED_INTEGER_LITERAL_DIGITS[base]}-digit limit"
    )


def test_hexadecimal_literal_over_magnitude_limit_is_rejected():
    digit_count = MAX_PREFIXED_INTEGER_LITERAL_DIGITS[16]

    with pytest.raises(RuneLexError) as exc_info:
        _tokenize("0x" + ("F" * digit_count))

    assert exc_info.value.diagnostic.message == (
        f"Integer literal exceeds the {MAX_INTEGER_LITERAL_BITS}-bit limit"
    )


def test_string_token():
    tokens = _tokenize('"cat"')
    assert tokens[0].type == TokenType.STRING
    assert tokens[0].value == "cat"
    assert tokens[0].span == SourceSpan(Position(1, 1), Position(1, 6))


def test_keyword_tokens():
    tokens = _tokenize(
        "chaos if elif else while for from to step break continue end and or not"
    )
    types = [t.type for t in tokens[:-1]]
    assert types == [
        TokenType.CHAOS,
        TokenType.IF,
        TokenType.ELIF,
        TokenType.ELSE,
        TokenType.WHILE,
        TokenType.FOR,
        TokenType.FROM,
        TokenType.TO,
        TokenType.STEP,
        TokenType.BREAK,
        TokenType.CONTINUE,
        TokenType.END,
        TokenType.AND,
        TokenType.OR,
        TokenType.NOT,
    ]


def test_operator_and_structural_tokens():
    tokens = _tokenize("+-*/%**~&|^<<>>()@")
    types = [t.type for t in tokens[:-1]]
    assert types == [
        TokenType.PLUS,
        TokenType.MINUS,
        TokenType.MULT,
        TokenType.DIV,
        TokenType.MOD,
        TokenType.POWER,
        TokenType.BIT_NOT,
        TokenType.BIT_AND,
        TokenType.BIT_OR,
        TokenType.BIT_XOR,
        TokenType.SHIFT_LEFT,
        TokenType.SHIFT_RIGHT,
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


def test_power_and_multiplication_use_longest_match():
    tokens = _tokenize("2***3")

    assert [token.type for token in tokens] == [
        TokenType.NUMBER,
        TokenType.POWER,
        TokenType.MULT,
        TokenType.NUMBER,
        TokenType.EOF,
    ]
    assert tokens[1].span == SourceSpan(Position(1, 2), Position(1, 4))
    assert tokens[2].span == SourceSpan(Position(1, 4), Position(1, 5))


def test_shift_and_comparison_operators_use_longest_match():
    tokens = _tokenize("<< <= < >> >= >")

    assert [token.type for token in tokens[:-1]] == [
        TokenType.SHIFT_LEFT,
        TokenType.LTE,
        TokenType.LT,
        TokenType.SHIFT_RIGHT,
        TokenType.GTE,
        TokenType.GT,
    ]


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


def test_identifiers_support_letters_digits_and_underscores():
    tokens = _tokenize("foo _bar rune2")
    assert [token.type for token in tokens[:-1]] == [
        TokenType.IDENTIFIER,
        TokenType.IDENTIFIER,
        TokenType.IDENTIFIER,
    ]
    assert [token.value for token in tokens[:-1]] == ["foo", "_bar", "rune2"]
    assert tokens[0].span == SourceSpan(Position(1, 1), Position(1, 4))


def test_single_equals_is_assignment_token():
    token = _tokenize("=")[0]
    assert token.type == TokenType.ASSIGN
    assert token.span == SourceSpan(Position(1, 1), Position(1, 2))


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
