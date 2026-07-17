from tokens import Token, TokenType
from spans import Position
from diagnostics import RuneLexError

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
                tokens.append(Token(TokenType.NEWLINE, '\n', start))
                self.advance()
                continue

            # String literals (enclosed in double quotes)
            if self.text[self.pos] == '"':
                string_val = self.read_string()
                tokens.append(Token(TokenType.STRING, string_val, start))

            # Numbers (one or more digits)
            elif self.text[self.pos].isdigit():
                num = self.read_number()
                tokens.append(Token(TokenType.NUMBER, num, start))

            # Identifiers and keywords (like 'chaos')
            elif self.text[self.pos].isalpha():
                ident = self.read_identifier()
                if ident == "chaos":
                    tokens.append(Token(TokenType.CHAOS, ident, start))
                elif ident == "if":
                    tokens.append(Token(TokenType.IF, ident, start))
                elif ident == "elif":
                    tokens.append(Token(TokenType.ELIF, ident, start))
                elif ident == "else":
                    tokens.append(Token(TokenType.ELSE, ident, start))
                elif ident == "end":
                    tokens.append(Token(TokenType.END, ident, start))
                else:
                    raise RuneLexError(f"Unknown identifier '{ident}'", start)

            # Pragma (@)
            elif self.text[self.pos] == '@':
                tokens.append(Token(TokenType.PRAGMA, '@', start))
                self.advance()

            # Parentheses used by conditional expressions
            elif self.text[self.pos] == '(':
                tokens.append(Token(TokenType.LPAREN, '(', start))
                self.advance()
            elif self.text[self.pos] == ')':
                tokens.append(Token(TokenType.RPAREN, ')', start))
                self.advance()

            # Arithmetic operators
            elif self.text[self.pos] == '+':
                tokens.append(Token(TokenType.PLUS, '+', start))
                self.advance()
            elif self.text[self.pos] == '-':
                tokens.append(Token(TokenType.MINUS, '-', start))
                self.advance()
            elif self.text[self.pos] == '*':
                tokens.append(Token(TokenType.MULT, '*', start))
                self.advance()

            # Comparison operators (with lookahead for multi-char)
            elif self.text[self.pos] == '<':
                if self.peek() == '=':
                    tokens.append(Token(TokenType.LTE, '<=', start))
                    self.advance()
                    self.advance()
                else:
                    tokens.append(Token(TokenType.LT, '<', start))
                    self.advance()
            elif self.text[self.pos] == '>':
                if self.peek() == '=':
                    tokens.append(Token(TokenType.GTE, '>=', start))
                    self.advance()
                    self.advance()
                else:
                    tokens.append(Token(TokenType.GT, '>', start))
                    self.advance()
            elif self.text[self.pos] == '=':
                if self.peek() == '=':
                    tokens.append(Token(TokenType.EQ, '==', start))
                    self.advance()
                    self.advance()
                else:
                    raise RuneLexError(
                        "Single '=' found; use '==' for equality", start
                    )
            elif self.text[self.pos] == '!':
                if self.peek() == '=':
                    tokens.append(Token(TokenType.NEQ, '!=', start))
                    self.advance()
                    self.advance()
                else:
                    raise RuneLexError("Unexpected '!'; use '!=' for inequality", start)

            else:
                raise RuneLexError(f"Unknown character {self.text[self.pos]!r}", start)

        # Add EOF marker
        tokens.append(Token(TokenType.EOF, None, self.current_position()))
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
            raise RuneLexError("Unterminated string literal", string_start)

        string_val = self.text[start:self.pos]
        self.advance()  # Skip closing quote
        return string_val

    def read_number(self):
        """Read a number from current position"""
        start = self.pos

        # Read all consecutive digits
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.advance()

        return int(self.text[start:self.pos])

    def read_identifier(self):
        """Read an identifier (keyword) from current position"""
        start = self.pos

        # Read all consecutive alphanumeric characters
        while self.pos < len(self.text) and self.text[self.pos].isalnum():
            self.advance()

        return self.text[start:self.pos]
