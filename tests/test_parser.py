import pytest

from lexer import Lexer
from parser import Parser
from tokens import TokenType
from ast_nodes import (
    NumberNode,
    StringNode,
    BinaryOpNode,
    ComparisonNode,
    ChaosPragmaNode,
    IfNode,
    ProgramNode,
)
from diagnostics import RuneParseError
from spans import Position, SourceSpan


def _parse(src):
    tokens = Lexer(src).tokenize()
    return Parser(tokens).parse()


def test_number_literal():
    node = _parse("42")
    assert isinstance(node, NumberNode)
    assert node.value == 42
    assert node.span == SourceSpan(Position(1, 1), Position(1, 3))


def test_string_literal():
    node = _parse('"cat"')
    assert isinstance(node, StringNode)
    assert node.value == "cat"


def test_arithmetic_precedence():
    node = _parse("2+3*4")
    assert isinstance(node, BinaryOpNode)
    assert node.op.type == TokenType.PLUS
    assert isinstance(node.left, NumberNode) and node.left.value == 2
    assert isinstance(node.right, BinaryOpNode)
    assert node.right.op.type == TokenType.MULT
    assert node.right.left.value == 3
    assert node.right.right.value == 4
    assert node.span == SourceSpan(Position(1, 1), Position(1, 6))
    assert node.right.span == SourceSpan(Position(1, 3), Position(1, 6))


@pytest.mark.parametrize(
    "op_src,op_type",
    [
        ("<", TokenType.LT),
        (">", TokenType.GT),
        ("<=", TokenType.LTE),
        (">=", TokenType.GTE),
        ("==", TokenType.EQ),
        ("!=", TokenType.NEQ),
    ],
)
def test_all_comparison_operators(op_src, op_type):
    node = _parse(f"1 {op_src} 2")
    assert isinstance(node, ComparisonNode)
    assert node.op.type == op_type


def test_chaos_pragma():
    node = _parse("@chaos 500")
    assert isinstance(node, ChaosPragmaNode)
    assert node.threshold == 500
    assert node.span == SourceSpan(Position(1, 1), Position(1, 11))


def test_if_then_only():
    node = _parse("if (1)\n2\nend")
    assert isinstance(node, IfNode)
    assert node.else_block is None
    assert node.elif_clauses == []
    assert len(node.then_block) == 1
    assert node.span == SourceSpan(Position(1, 1), Position(3, 4))


def test_if_then_else():
    node = _parse("if (1)\n2\nelse\n3\nend")
    assert node.else_block is not None
    assert len(node.else_block) == 1


def test_if_then_multiple_elif():
    node = _parse("if (0)\n1\nelif (0)\n2\nelif (1)\n3\nend")
    assert len(node.elif_clauses) == 2
    assert node.else_block is None


def test_if_then_elif_else():
    node = _parse("if (0)\n1\nelif (0)\n2\nelse\n3\nend")
    assert len(node.elif_clauses) == 1
    assert node.else_block is not None


def test_nested_if():
    node = _parse("if (1)\nif (1)\n2\nend\nend")
    assert isinstance(node, IfNode)
    assert isinstance(node.then_block[0], IfNode)


def test_multi_statement_program_wraps_in_program_node():
    node = _parse("1\n2\n3")
    assert isinstance(node, ProgramNode)
    assert len(node.statements) == 3
    assert node.span == SourceSpan(Position(1, 1), Position(3, 2))


def test_single_statement_does_not_wrap():
    node = _parse("1")
    assert isinstance(node, NumberNode)


def test_empty_program_raises_parse_error():
    tokens = Lexer("\n\n").tokenize()
    with pytest.raises(RuneParseError):
        Parser(tokens).parse()


def test_missing_end_raises_parse_error():
    with pytest.raises(RuneParseError) as exc_info:
        _parse("if (1)\n1\n")
    assert exc_info.value.diagnostic.span == SourceSpan.at(Position(3, 1))


def test_unexpected_token_in_factor_raises_parse_error():
    with pytest.raises(RuneParseError) as exc_info:
        _parse(")")
    assert exc_info.value.diagnostic.span == SourceSpan(
        Position(1, 1), Position(1, 2)
    )


def test_binop_span_covers_both_operands():
    node = _parse("2+3")
    assert node.span == SourceSpan(Position(1, 1), Position(1, 4))
