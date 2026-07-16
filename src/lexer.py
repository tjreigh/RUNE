from tokens import Token, TokenType

class Lexer:
    """
    Tokenizes RUNE source code
    Converts: '"cat" + "dog"' -> [STRING("cat"), PLUS, STRING("dog"), EOF]
    """
    
    def __init__(self, text):
        self.text = text
        self.pos = 0

    def peek(self):
        """Look at the next character without consuming it"""
        if self.pos + 1 < len(self.text):
            return self.text[self.pos + 1]
        return None

    def tokenize(self):
        """Main lexer loop - returns list of tokens"""
        tokens = []

        while self.pos < len(self.text):
            # Skip whitespace (but not newlines - they're statement separators)
            if self.text[self.pos] in ' \t\r':
                self.pos += 1
                continue

            # Newlines (statement separators)
            if self.text[self.pos] == '\n':
                tokens.append(Token(TokenType.NEWLINE, '\n'))
                self.pos += 1
                continue

            # String literals (enclosed in double quotes)
            if self.text[self.pos] == '"':
                string_val = self.read_string()
                tokens.append(Token(TokenType.STRING, string_val))

            # Numbers (one or more digits)
            elif self.text[self.pos].isdigit():
                num = self.read_number()
                tokens.append(Token(TokenType.NUMBER, num))

            # Identifiers and keywords (like 'chaos')
            elif self.text[self.pos].isalpha():
                ident = self.read_identifier()
                if ident == "chaos":
                    tokens.append(Token(TokenType.CHAOS, ident))
                elif ident == "if":
                    tokens.append(Token(TokenType.IF, ident))
                else:
                    print(f"Warning: Unknown identifier '{ident}' at position {self.pos}")

            # Pragma (@)
            elif self.text[self.pos] == '@':
                tokens.append(Token(TokenType.PRAGMA, '@'))
                self.pos += 1

            # Arithmetic operators
            elif self.text[self.pos] == '+':
                tokens.append(Token(TokenType.PLUS, '+'))
                self.pos += 1
            elif self.text[self.pos] == '-':
                tokens.append(Token(TokenType.MINUS, '-'))
                self.pos += 1
            elif self.text[self.pos] == '*':
                tokens.append(Token(TokenType.MULT, '*'))
                self.pos += 1

            # Comparison operators (with lookahead for multi-char)
            elif self.text[self.pos] == '<':
                if self.peek() == '=':
                    tokens.append(Token(TokenType.LTE, '<='))
                    self.pos += 2
                else:
                    tokens.append(Token(TokenType.LT, '<'))
                    self.pos += 1
            elif self.text[self.pos] == '>':
                if self.peek() == '=':
                    tokens.append(Token(TokenType.GTE, '>='))
                    self.pos += 2
                else:
                    tokens.append(Token(TokenType.GT, '>'))
                    self.pos += 1
            elif self.text[self.pos] == '=':
                if self.peek() == '=':
                    tokens.append(Token(TokenType.EQ, '=='))
                    self.pos += 2
                else:
                    print(f"Warning: Single '=' found at position {self.pos}, use '==' for equality")
                    self.pos += 1
            elif self.text[self.pos] == '!':
                if self.peek() == '=':
                    tokens.append(Token(TokenType.NEQ, '!='))
                    self.pos += 2
                else:
                    print(f"Warning: Unexpected '!' at position {self.pos}")
                    self.pos += 1

            # Logical operators
            elif self.text[self.pos] == "IF":
                tokens.append(Token(TokenType.IF, "IF"))
                self.pos += 2

            else:
                # Unknown character - skip it (or raise error)
                print(f"Warning: Unknown character '{self.text[self.pos]}' at position {self.pos}")
                self.pos += 1

        # Add EOF marker
        tokens.append(Token(TokenType.EOF, None))
        return tokens
    
    def read_string(self):
        """Read a string literal from current position"""
        self.pos += 1  # Skip opening quote
        start = self.pos
        
        # Read until closing quote or end of input
        while self.pos < len(self.text) and self.text[self.pos] != '"':
            self.pos += 1
        
        if self.pos >= len(self.text):
            raise Exception("Unterminated string literal")
        
        string_val = self.text[start:self.pos]
        self.pos += 1  # Skip closing quote
        return string_val
    
    def read_number(self):
        """Read a number from current position"""
        start = self.pos

        # Read all consecutive digits
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.pos += 1

        return int(self.text[start:self.pos])

    def read_identifier(self):
        """Read an identifier (keyword) from current position"""
        start = self.pos

        # Read all consecutive alphanumeric characters
        while self.pos < len(self.text) and self.text[self.pos].isalnum():
            self.pos += 1

        return self.text[start:self.pos]
