import pytest

from lexer import Lexer
from parser import Parser
from interpreter import Interpreter
from tokens import Token, TokenType
from ast_nodes import BinaryOpNode, ComparisonNode, NumberNode
from diagnostics import RuneInternalError


def _run(src):
    tokens = Lexer(src).tokenize()
    ast = Parser(tokens).parse()
    return Interpreter().interpret(ast)


def test_number_literal_value():
    assert _run("42") == 42


def test_string_collapses_to_codepoint_sum():
    assert _run('"cat"') == sum(ord(c) for c in "cat")


def test_addition():
    assert _run("2+3") == 5


def test_subtraction():
    assert _run("5-3") == 2


def test_multiplication():
    assert _run("4*3") == 12


@pytest.mark.parametrize(
    "src,expected",
    [
        ("1 < 2", 1),
        ("2 < 1", 0),
        ("2 > 1", 1),
        ("1 > 2", 0),
        ("1 <= 1", 1),
        ("2 <= 1", 0),
        ("1 >= 1", 1),
        ("1 >= 2", 0),
        ("1 == 1", 1),
        ("1 == 2", 0),
        ("1 != 2", 1),
        ("1 != 1", 0),
    ],
)
def test_comparisons_return_one_or_zero(src, expected):
    assert _run(src) == expected


def test_chaos_truthy_boundaries():
    interp = Interpreter()
    interp.chaos_threshold = 5
    assert interp.is_chaos_truthy(5) is True
    assert interp.is_chaos_truthy(4) is False
    assert interp.is_chaos_truthy(0) is False
    assert interp.is_chaos_truthy(-3) is False


def test_if_only_first_truthy_branch_executes():
    result = _run("@chaos 1\nif (1)\n10\nelif (1)\n20\nend")
    assert result == [10]


def test_if_else_all_falsy():
    result = _run("@chaos 1\nif (0)\n10\nelse\n20\nend")
    assert result == [20]


def test_if_no_else_all_falsy_returns_empty_list():
    result = _run("@chaos 1\nif (0)\n10\nend")
    assert result == []


def test_nested_if_flattens():
    result = _run("@chaos 1\nif (1)\nif (1)\n99\nend\nend")
    assert result == [99]


def test_multi_statement_program_excludes_pragma_results():
    result = _run("@chaos 1\n1\n2")
    assert result == [1, 2]


def test_unknown_node_type_raises_internal_error():
    class FakeNode:
        pass

    with pytest.raises(RuneInternalError):
        Interpreter().visit(FakeNode())


def test_unknown_binop_operator_raises_internal_error():
    bad_op = Token(TokenType.LT, "<")
    node = BinaryOpNode(NumberNode(1), bad_op, NumberNode(2))
    with pytest.raises(RuneInternalError):
        Interpreter().visit_binop(node)


def test_unknown_comparison_operator_raises_internal_error():
    bad_op = Token(TokenType.PLUS, "+")
    node = ComparisonNode(NumberNode(1), bad_op, NumberNode(2))
    with pytest.raises(RuneInternalError):
        Interpreter().visit_comparison(node)
