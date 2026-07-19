import pytest

from lexer import Lexer
from parser import Parser, MAX_EXPRESSION_NESTING
from tokens import TokenType
from ast_nodes import (
    NumberNode,
    StringNode,
    BinaryOpNode,
    ComparisonNode,
    ChaosPragmaNode,
    VariableNode,
    AssignmentNode,
    GroupNode,
    UnaryOpNode,
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


def test_variable_lookup():
    node = _parse("score")
    assert isinstance(node, VariableNode)
    assert node.name == "score"


def test_assignment_parses_expression_rhs_and_full_span():
    node = _parse("score = 2 + 3 * 4")
    assert isinstance(node, AssignmentNode)
    assert node.name == "score"
    assert isinstance(node.value, BinaryOpNode)
    assert node.span == SourceSpan(Position(1, 1), Position(1, 18))


def test_assignment_requires_a_value():
    with pytest.raises(RuneParseError):
        _parse("score =")


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


def test_parentheses_override_arithmetic_precedence():
    node = _parse("(2+3)*4")

    assert isinstance(node, BinaryOpNode)
    assert node.op.type == TokenType.MULT
    assert isinstance(node.left, GroupNode)
    assert isinstance(node.left.expression, BinaryOpNode)
    assert node.left.expression.op.type == TokenType.PLUS
    assert node.left.span == SourceSpan(Position(1, 1), Position(1, 6))
    assert node.left.expression.span == SourceSpan(
        Position(1, 2), Position(1, 5)
    )


def test_nested_parentheses_preserve_each_group_span():
    node = _parse("((42))")

    assert isinstance(node, GroupNode)
    assert isinstance(node.expression, GroupNode)
    assert node.span == SourceSpan(Position(1, 1), Position(1, 7))
    assert node.expression.span == SourceSpan(Position(1, 2), Position(1, 6))
    assert node.expression.expression.span == SourceSpan(
        Position(1, 3), Position(1, 5)
    )


@pytest.mark.parametrize(
    "source,operator",
    [("-42", TokenType.MINUS), ("~42", TokenType.BIT_NOT)],
)
def test_unary_operator_node_and_span(source, operator):
    node = _parse(source)

    assert isinstance(node, UnaryOpNode)
    assert node.op.type == operator
    assert isinstance(node.operand, NumberNode)
    assert node.span == SourceSpan(Position(1, 1), Position(1, 4))


def test_unary_operators_nest_from_right_to_left():
    node = _parse("-~5")

    assert isinstance(node, UnaryOpNode)
    assert node.op.type == TokenType.MINUS
    assert isinstance(node.operand, UnaryOpNode)
    assert node.operand.op.type == TokenType.BIT_NOT


def test_unary_binds_more_tightly_than_multiplication():
    node = _parse("-2*3")

    assert isinstance(node, BinaryOpNode)
    assert node.op.type == TokenType.MULT
    assert isinstance(node.left, UnaryOpNode)


def test_parenthesized_expression_can_be_assignment_value():
    node = _parse("answer = (40 + 2)")

    assert isinstance(node, AssignmentNode)
    assert isinstance(node.value, GroupNode)
    assert node.span == SourceSpan(Position(1, 1), Position(1, 18))


def test_missing_closing_parenthesis_reports_eof_span():
    with pytest.raises(RuneParseError) as exc_info:
        _parse("(2 + 3")

    assert exc_info.value.diagnostic.message == "Expected RPAREN, got EOF"
    assert exc_info.value.diagnostic.span == SourceSpan.at(Position(1, 7))


@pytest.mark.parametrize("wrapper", [("(", ")"), ("-", "")])
def test_expression_nesting_at_limit_is_accepted(wrapper):
    prefix, suffix = wrapper
    source = (prefix * MAX_EXPRESSION_NESTING) + "1" + (
        suffix * MAX_EXPRESSION_NESTING
    )

    assert _parse(source) is not None


@pytest.mark.parametrize("wrapper", [("(", ")"), ("-", "")])
def test_expression_nesting_over_limit_is_structured_parse_error(wrapper):
    prefix, suffix = wrapper
    source = (prefix * (MAX_EXPRESSION_NESTING + 1)) + "1" + (
        suffix * (MAX_EXPRESSION_NESTING + 1)
    )

    with pytest.raises(RuneParseError) as exc_info:
        _parse(source)

    assert exc_info.value.diagnostic.message == (
        f"Expression nesting exceeds the {MAX_EXPRESSION_NESTING}-level limit"
    )


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


def test_unexpected_token_in_primary_raises_parse_error():
    with pytest.raises(RuneParseError) as exc_info:
        _parse(")")
    assert exc_info.value.diagnostic.span == SourceSpan(
        Position(1, 1), Position(1, 2)
    )


def test_binop_span_covers_both_operands():
    node = _parse("2+3")
    assert node.span == SourceSpan(Position(1, 1), Position(1, 4))
