from enum import Enum

class TokenType(Enum):
    """All possible token types in RUNE"""
    STRING = "STRING"
    NUMBER = "NUMBER"
    # Arithmetic operators
    PLUS = "PLUS"
    MINUS = "MINUS"
    MULT = "MULT"
    # Comparison operators
    LT = "LT"          # <
    GT = "GT"          # >
    LTE = "LTE"        # <=
    GTE = "GTE"        # >=
    EQ = "EQ"          # ==
    NEQ = "NEQ"        # !=
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
    """A single token with a type and value"""
    def __init__(self, type, value):
        self.type = type
        self.value = value
    
    def __repr__(self):
        return f"Token({self.type}, {self.value})"
