from enum import Enum

from spans import SourceSpan

class TokenType(Enum):
    """All possible token types in RUNE"""
    STRING = "STRING"
    NUMBER = "NUMBER"
    IDENTIFIER = "IDENTIFIER"
    # Arithmetic operators
    PLUS = "PLUS"
    MINUS = "MINUS"
    MULT = "MULT"
    BIT_NOT = "BIT_NOT"  # ~
    # Comparison operators
    LT = "LT"          # <
    GT = "GT"          # >
    LTE = "LTE"        # <=
    GTE = "GTE"        # >=
    EQ = "EQ"          # ==
    NEQ = "NEQ"        # !=
    ASSIGN = "ASSIGN"  # =
    # Logical operators
    IF = "IF"
    ELIF = "ELIF"
    ELSE = "ELSE"
    AND = "AND"
    OR = "OR"
    # Pragma tokens
    PRAGMA = "PRAGMA"  # @
    CHAOS = "CHAOS"    # chaos keyword
    # Structural
    LPAREN = "LPAREN"  # (
    RPAREN = "RPAREN"  # )
    END = "END"
    NEWLINE = "NEWLINE"  # \n (statement separator)
    EOF = "EOF"


class Token:
    """A single token with a type, value, and source span."""
    def __init__(self, type, value, span: SourceSpan | None = None):
        self.type = type
        self.value = value
        self.span = span

    def __repr__(self):
        return f"Token({self.type}, {self.value}, {self.span})"
