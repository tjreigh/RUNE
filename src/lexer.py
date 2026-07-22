from tokens import Token, TokenType
from spans import Position, SourceSpan
from diagnostics import RuneLexError
from limits import DEFAULT_MAX_INTEGER_BITS

MAX_INTEGER_LITERAL_DIGITS = 4_300
MAX_INTEGER_LITERAL_BITS = DEFAULT_MAX_INTEGER_BITS

_PREFIXED_INTEGER_SPECS = {
    "b": (2, "binary", frozenset("01")),
    "o": (8, "octal", frozenset("01234567")),
    "x": (16, "hexadecimal", frozenset("0123456789abcdefABCDEF")),
}

# Bound both numeric magnitude and source scanning. The per-base text limits
# are the number of digits needed to represent at most the same magnitude as a
# 4,300-digit decimal integer; a final bit-length check handles the partially
# filled leading digit in octal and hexadecimal forms.
MAX_PREFIXED_INTEGER_LITERAL_DIGITS = {
    2: MAX_INTEGER_LITERAL_BITS,
    8: (MAX_INTEGER_LITERAL_BITS + 2) // 3,
    16: (MAX_INTEGER_LITERAL_BITS + 3) // 4,
}


class Lexer:
    """
    Tokenizes RUNE source code
    Converts: '"cat" + "dog"' -> [STRING("cat"), PLUS, STRING("dog"), EOF]
    """

    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.line = 1
        self.column = 1

    def peek(self):
        """Look at the next character without consuming it"""
        if self.pos + 1 < len(self.text):
            return self.text[self.pos + 1]
        return None

    def current_position(self):
        """Position of the character currently at self.pos"""
        return Position(self.line, self.column)

    def advance(self):
        """Consume one character, keeping line/column in sync with pos"""
        if self.pos < len(self.text) and self.text[self.pos] == '\n':
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        self.pos += 1

    def span_from(self, start):
        """Build a span from a saved start through the current position."""
        return SourceSpan(start, self.current_position())

    def tokenize(self):
        """Main lexer loop - returns list of tokens"""
        tokens = []

        while self.pos < len(self.text):
            start = self.current_position()

            # Skip whitespace (but not newlines - they're statement separators)
            if self.text[self.pos] in ' \t\r':
                self.advance()
                continue

            # Newlines (statement separators)
            if self.text[self.pos] == '\n':
                self.advance()
                tokens.append(Token(TokenType.NEWLINE, '\n', self.span_from(start)))
                continue

            # String literals (enclosed in double quotes)
            if self.text[self.pos] == '"':
                string_val = self.read_string()
                tokens.append(Token(TokenType.STRING, string_val, self.span_from(start)))

            # Numbers (one or more digits)
            elif self.text[self.pos].isdigit():
                num = self.read_number(start)
                tokens.append(Token(TokenType.NUMBER, num, self.span_from(start)))

            # Identifiers and keywords. Underscores are allowed after or at
            # the start of a name; keywords remain reserved.
            elif self.text[self.pos].isalpha() or self.text[self.pos] == '_':
                ident = self.read_identifier()
                if ident == "chaos":
                    tokens.append(Token(TokenType.CHAOS, ident, self.span_from(start)))
                elif ident == "if":
                    tokens.append(Token(TokenType.IF, ident, self.span_from(start)))
                elif ident == "elif":
                    tokens.append(Token(TokenType.ELIF, ident, self.span_from(start)))
                elif ident == "else":
                    tokens.append(Token(TokenType.ELSE, ident, self.span_from(start)))
                elif ident == "end":
                    tokens.append(Token(TokenType.END, ident, self.span_from(start)))
                elif ident == "and":
                    tokens.append(Token(TokenType.AND, ident, self.span_from(start)))
                elif ident == "or":
                    tokens.append(Token(TokenType.OR, ident, self.span_from(start)))
                elif ident == "not":
                    tokens.append(Token(TokenType.NOT, ident, self.span_from(start)))
                else:
                    tokens.append(
                        Token(TokenType.IDENTIFIER, ident, self.span_from(start))
                    )

            # Pragma (@)
            elif self.text[self.pos] == '@':
                self.advance()
                tokens.append(Token(TokenType.PRAGMA, '@', self.span_from(start)))

            # Parentheses used by conditional expressions
            elif self.text[self.pos] == '(':
                self.advance()
                tokens.append(Token(TokenType.LPAREN, '(', self.span_from(start)))
            elif self.text[self.pos] == ')':
                self.advance()
                tokens.append(Token(TokenType.RPAREN, ')', self.span_from(start)))

            # Arithmetic operators
            elif self.text[self.pos] == '+':
                self.advance()
                tokens.append(Token(TokenType.PLUS, '+', self.span_from(start)))
            elif self.text[self.pos] == '-':
                self.advance()
                tokens.append(Token(TokenType.MINUS, '-', self.span_from(start)))
            elif self.text[self.pos] == '*':
                if self.peek() == '*':
                    self.advance()
                    self.advance()
                    tokens.append(
                        Token(TokenType.POWER, '**', self.span_from(start))
                    )
                else:
                    self.advance()
                    tokens.append(Token(TokenType.MULT, '*', self.span_from(start)))
            elif self.text[self.pos] == '/':
                self.advance()
                tokens.append(Token(TokenType.DIV, '/', self.span_from(start)))
            elif self.text[self.pos] == '%':
                self.advance()
                tokens.append(Token(TokenType.MOD, '%', self.span_from(start)))
            elif self.text[self.pos] == '~':
                self.advance()
                tokens.append(Token(TokenType.BIT_NOT, '~', self.span_from(start)))
            elif self.text[self.pos] == '&':
                self.advance()
                tokens.append(Token(TokenType.BIT_AND, '&', self.span_from(start)))
            elif self.text[self.pos] == '|':
                self.advance()
                tokens.append(Token(TokenType.BIT_OR, '|', self.span_from(start)))
            elif self.text[self.pos] == '^':
                self.advance()
                tokens.append(Token(TokenType.BIT_XOR, '^', self.span_from(start)))

            # Comparison operators (with lookahead for multi-char)
            elif self.text[self.pos] == '<':
                if self.peek() == '<':
                    self.advance()
                    self.advance()
                    tokens.append(
                        Token(TokenType.SHIFT_LEFT, '<<', self.span_from(start))
                    )
                elif self.peek() == '=':
                    self.advance()
                    self.advance()
                    tokens.append(Token(TokenType.LTE, '<=', self.span_from(start)))
                else:
                    self.advance()
                    tokens.append(Token(TokenType.LT, '<', self.span_from(start)))
            elif self.text[self.pos] == '>':
                if self.peek() == '>':
                    self.advance()
                    self.advance()
                    tokens.append(
                        Token(TokenType.SHIFT_RIGHT, '>>', self.span_from(start))
                    )
                elif self.peek() == '=':
                    self.advance()
                    self.advance()
                    tokens.append(Token(TokenType.GTE, '>=', self.span_from(start)))
                else:
                    self.advance()
                    tokens.append(Token(TokenType.GT, '>', self.span_from(start)))
            elif self.text[self.pos] == '=':
                if self.peek() == '=':
                    self.advance()
                    self.advance()
                    tokens.append(Token(TokenType.EQ, '==', self.span_from(start)))
                else:
                    self.advance()
                    tokens.append(Token(TokenType.ASSIGN, '=', self.span_from(start)))
            elif self.text[self.pos] == '!':
                if self.peek() == '=':
                    self.advance()
                    self.advance()
                    tokens.append(Token(TokenType.NEQ, '!=', self.span_from(start)))
                else:
                    self.advance()
                    raise RuneLexError(
                        "Unexpected '!'; use '!=' for inequality",
                        self.span_from(start),
                    )

            else:
                unknown = self.text[self.pos]
                self.advance()
                raise RuneLexError(
                    f"Unknown character {unknown!r}", self.span_from(start)
                )

        # Add EOF marker
        eof = self.current_position()
        tokens.append(Token(TokenType.EOF, None, SourceSpan.at(eof)))
        return tokens

    def read_string(self):
        """Read a string literal from current position"""
        string_start = self.current_position()
        self.advance()  # Skip opening quote
        start = self.pos

        # Read until closing quote or end of input
        while self.pos < len(self.text) and self.text[self.pos] != '"':
            self.advance()

        if self.pos >= len(self.text):
            raise RuneLexError(
                "Unterminated string literal", self.span_from(string_start)
            )

        string_val = self.text[start:self.pos]
        self.advance()  # Skip closing quote
        return string_val

    def read_number(self, source_start=None):
        """Read a number from current position"""
        start = self.pos
        source_start = source_start or self.current_position()

        if (
            self.text[self.pos] == "0"
            and self.peek() is not None
            and self.peek().lower() in _PREFIXED_INTEGER_SPECS
        ):
            return self.read_prefixed_number(source_start)

        # Read all consecutive digits
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.advance()

        literal = self.text[start:self.pos]
        if len(literal) > MAX_INTEGER_LITERAL_DIGITS:
            raise RuneLexError(
                f"Integer literal exceeds the {MAX_INTEGER_LITERAL_DIGITS}-digit limit",
                self.span_from(source_start),
            )
        try:
            return int(literal)
        except ValueError as exc:
            raise RuneLexError(
                "Invalid or unsupported integer literal",
                self.span_from(source_start),
            ) from exc

    def read_prefixed_number(self, source_start):
        """Read a 0b, 0o, or 0x integer and validate its complete form."""
        prefix = self.peek()
        base, label, valid_digits = _PREFIXED_INTEGER_SPECS[prefix.lower()]
        self.advance()  # 0
        self.advance()  # base prefix
        digits_start = self.pos

        # Consume the whole contiguous candidate so an invalid digit produces
        # one precise lex diagnostic instead of misleading adjacent tokens.
        while (
            self.pos < len(self.text)
            and (self.text[self.pos].isalnum() or self.text[self.pos] == "_")
        ):
            self.advance()

        digits = self.text[digits_start:self.pos]
        literal_prefix = f"0{prefix}"
        if not digits:
            raise RuneLexError(
                f"Expected digits after '{literal_prefix}'",
                self.span_from(source_start),
            )

        invalid = next((char for char in digits if char not in valid_digits), None)
        if invalid is not None:
            raise RuneLexError(
                f"Invalid digit {invalid!r} in {label} integer literal",
                self.span_from(source_start),
            )

        max_digits = MAX_PREFIXED_INTEGER_LITERAL_DIGITS[base]
        if len(digits) > max_digits:
            raise RuneLexError(
                f"{label.title()} integer literal exceeds the "
                f"{max_digits}-digit limit",
                self.span_from(source_start),
            )

        try:
            value = int(digits, base)
        except ValueError as exc:
            raise RuneLexError(
                "Invalid or unsupported integer literal",
                self.span_from(source_start),
            ) from exc

        if value.bit_length() > MAX_INTEGER_LITERAL_BITS:
            raise RuneLexError(
                f"Integer literal exceeds the {MAX_INTEGER_LITERAL_BITS}-bit limit",
                self.span_from(source_start),
            )
        return value

    def read_identifier(self):
        """Read an identifier (keyword) from current position"""
        start = self.pos

        # Read all name characters after the already-validated first one.
        while (
            self.pos < len(self.text)
            and (self.text[self.pos].isalnum() or self.text[self.pos] == '_')
        ):
            self.advance()

        return self.text[start:self.pos]
