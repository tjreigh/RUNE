from enum import Enum

from .spans import SourceSpan

class TokenType(Enum):
    """All possible token types in RUNE"""
    STRING = "STRING"
    NUMBER = "NUMBER"
    IDENTIFIER = "IDENTIFIER"
    # Arithmetic operators
    PLUS = "PLUS"
    MINUS = "MINUS"
    MULT = "MULT"
    DIV = "DIV"
    MOD = "MOD"
    POWER = "POWER"
    BIT_NOT = "BIT_NOT"  # ~
    BIT_AND = "BIT_AND"  # &
    BIT_OR = "BIT_OR"    # |
    BIT_XOR = "BIT_XOR"  # ^
    SHIFT_LEFT = "SHIFT_LEFT"    # <<
    SHIFT_RIGHT = "SHIFT_RIGHT"  # >>
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
    WHILE = "WHILE"
    FOR = "FOR"
    FROM = "FROM"
    TO = "TO"
    STEP = "STEP"
    BREAK = "BREAK"
    CONTINUE = "CONTINUE"
    FUNCTION = "FUNCTION"
    RETURN = "RETURN"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    # Pragma tokens
    PRAGMA = "PRAGMA"  # @
    CHAOS = "CHAOS"    # chaos keyword
    # Structural
    LPAREN = "LPAREN"  # (
    RPAREN = "RPAREN"  # )
    COMMA = "COMMA"    # ,
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
