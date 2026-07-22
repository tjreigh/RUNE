import pytest

from lexer import Lexer
from parser import Parser
from interpreter import Interpreter, _BreakSignal, _ContinueSignal
from tokens import Token, TokenType
from ast_nodes import (
    BinaryOpNode,
    ComparisonNode,
    LogicalOpNode,
    LogicalNotNode,
    NumberNode,
    UnaryOpNode,
    IfNode,
    BreakNode,
    ContinueNode,
)
from diagnostics import RuneInternalError, RuneRuntimeError
from runtime_state import RuntimeState


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
    "source,expected",
    [
        ("7/3", 2),
        ("-7/3", -2),
        ("7/-3", -2),
        ("-7/-3", 2),
    ],
)
def test_integer_division_truncates_toward_zero(source, expected):
    assert _run(source) == expected


@pytest.mark.parametrize(
    "source,expected",
    [
        ("7%3", 1),
        ("-7%3", -1),
        ("7%-3", 1),
        ("-7%-3", -1),
    ],
)
def test_remainder_follows_dividend_sign(source, expected):
    assert _run(source) == expected


@pytest.mark.parametrize(
    "source,message",
    [("1/0", "Division by zero"), ("1%0", "Modulo by zero")],
)
def test_zero_divisor_is_runtime_error(source, message):
    with pytest.raises(RuneRuntimeError) as exc_info:
        _run(source)

    assert exc_info.value.diagnostic.message == message


@pytest.mark.parametrize(
    "source,expected",
    [
        ("2**10", 1024),
        ("2**3**2", 512),
        ("-2**2", -4),
        ("(-2)**2", 4),
        ("0**0", 1),
        ("0**5", 0),
        ("(-1)**999", -1),
    ],
)
def test_integer_power_semantics(source, expected):
    assert _run(source) == expected


def test_negative_exponent_is_runtime_error():
    with pytest.raises(RuneRuntimeError) as exc_info:
        _run("2**-1")

    assert exc_info.value.diagnostic.message == "Negative exponent"


def test_multiplicative_operators_are_left_associative():
    assert _run("20/3*2%5") == 2


@pytest.mark.parametrize(
    "source,expected",
    [
        ("0b1100 & 0b1010", 0b1000),
        ("0b1100 | 0b1010", 0b1110),
        ("0b1100 ^ 0b1010", 0b0110),
        ("-5 & 3", -5 & 3),
        ("-5 | 3", -5 | 3),
        ("-5 ^ 3", -5 ^ 3),
    ],
)
def test_bitwise_operators_use_infinite_twos_complement(source, expected):
    assert _run(source) == expected


@pytest.mark.parametrize(
    "source,expected",
    [
        ("3 << 4", 48),
        ("-3 << 2", -12),
        ("16 >> 2", 4),
        ("-9 >> 2", -3),
        ("5 >> 999999999999999999999999", 0),
        ("-5 >> 999999999999999999999999", -1),
        ("0 << 999999999999999999999999", 0),
    ],
)
def test_shift_semantics(source, expected):
    assert _run(source) == expected


@pytest.mark.parametrize("source", ["1 << -1", "1 >> -1"])
def test_negative_shift_count_is_runtime_error(source):
    with pytest.raises(RuneRuntimeError) as exc_info:
        _run(source)

    assert exc_info.value.diagnostic.message == "Negative shift count"


def test_bitwise_and_shift_precedence():
    assert _run("1 | 2 ^ 3 & 7 << 1 + 1") == 3


def test_parentheses_override_precedence():
    assert _run("(2+3)*4") == 20


def test_nested_parentheses_preserve_value():
    assert _run("(((42)))") == 42


def test_unary_negation():
    assert _run("-42") == -42


def test_bitwise_complement_uses_infinite_twos_complement_semantics():
    assert _run("~0b0101") == -6


@pytest.mark.parametrize(
    "source,expected",
    [("--5", 5), ("-~5", 6), ("~-5", 4), ("~~5", 5)],
)
def test_nested_unary_operators(source, expected):
    assert _run(source) == expected


def test_unary_operators_apply_after_string_collapse():
    assert _run('-"A"') == -65
    assert _run('~"A"') == -66


def test_assignment_stores_value_and_produces_no_output():
    assert _run("score = 40 + 2") is None


def test_assignment_lookup_and_reassignment():
    assert _run("score = 40\nscore = score + 2\nscore") == [42]


def test_assigned_string_collapses_immediately_to_a_number():
    assert _run('animal = "cat"\nanimal') == [sum(ord(c) for c in "cat")]


def test_assignment_in_executed_branch_updates_state():
    interpreter = Interpreter()
    ast = Parser(Lexer("if (1)\nanswer = 42\nend if").tokenize()).parse()
    assert interpreter.interpret(ast) == []
    assert interpreter.state.variables == {"answer": 42}


def test_assignment_in_skipped_branch_does_not_update_state():
    interpreter = Interpreter()
    ast = Parser(Lexer("if (0)\nanswer = 42\nend if").tokenize()).parse()
    assert interpreter.interpret(ast) == []
    assert interpreter.state.variables == {}


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


@pytest.mark.parametrize(
    "source,expected",
    [
        ("5 and 8", 1),
        ("0 and 8", 0),
        ("5 or 0", 1),
        ("0 or 8", 1),
        ("0 or 0", 0),
        ("not 0", 1),
        ("not 5", 0),
    ],
)
def test_logical_operators_normalize_to_one_or_zero(source, expected):
    assert _run(source) == expected


@pytest.mark.parametrize(
    "source,expected",
    [
        ("0 and missing", 0),
        ("5 or missing", 1),
        ("@chaos 10\n5 and missing", [0]),
        ("@chaos 10\n20 or missing", [1]),
    ],
)
def test_logical_operators_skip_unneeded_right_operand(source, expected):
    assert _run(source) == expected


def test_logical_operators_visit_needed_right_operand():
    with pytest.raises(RuneRuntimeError) as exc_info:
        _run("5 and missing")
    assert exc_info.value.diagnostic.message == "Undefined variable 'missing'"

    with pytest.raises(RuneRuntimeError) as exc_info:
        _run("0 or missing")
    assert exc_info.value.diagnostic.message == "Undefined variable 'missing'"


def test_higher_chaos_threshold_controls_logic_before_normalization():
    assert _run("@chaos 10\n5 or 20") == [1]
    assert _run("@chaos 10\nnot 5") == [1]
    assert _run("@chaos 10\nnot 20") == [0]


def test_normalized_logical_result_can_itself_be_chaos_falsy():
    assert _run("@chaos 10\nif (5 or 20)\n99\nelse\n0\nend if") == [0]


def test_chaos_truthy_boundaries():
    interp = Interpreter(state=RuntimeState(chaos_threshold=5))
    assert interp.is_chaos_truthy(5) is True
    assert interp.is_chaos_truthy(4) is False
    assert interp.is_chaos_truthy(0) is False
    assert interp.is_chaos_truthy(-3) is False


def test_if_only_first_truthy_branch_executes():
    result = _run("@chaos 1\nif (1)\n10\nelif (1)\n20\nend if")
    assert result == [10]


def test_if_else_all_falsy():
    result = _run("@chaos 1\nif (0)\n10\nelse\n20\nend if")
    assert result == [20]


def test_if_no_else_all_falsy_returns_empty_list():
    result = _run("@chaos 1\nif (0)\n10\nend if")
    assert result == []


def test_nested_if_flattens():
    result = _run("@chaos 1\nif (1)\nif (1)\n99\nend if\nend if")
    assert result == [99]


def test_while_uses_chaos_truthiness_and_reevaluates_its_condition():
    interpreter = Interpreter()
    ast = Parser(
        Lexer(
            "@chaos 3\ncount = 5\nwhile (count)\n"
            "count\ncount = count - 1\nend while"
        ).tokenize()
    ).parse()

    assert interpreter.interpret(ast) == [5, 4, 3]
    assert interpreter.state.variables == {"count": 2}
    assert interpreter.stats.loop_iterations == 3


def test_while_can_execute_zero_iterations():
    interpreter = Interpreter()
    ast = Parser(
        Lexer("count = 0\nwhile (count)\nmissing\nend while").tokenize()
    ).parse()

    assert interpreter.interpret(ast) == []
    assert interpreter.stats.loop_iterations == 0


def test_break_exits_nearest_loop_and_preserves_prior_output():
    source = (
        "outer = 2\n"
        "while (outer)\n"
        "inner = 2\n"
        "while (inner)\n"
        "inner\n"
        "if (1)\n42\nbreak\nend if\n"
        "99\n"
        "end while\n"
        "outer = outer - 1\n"
        "end while"
    )
    interpreter = Interpreter()
    ast = Parser(Lexer(source).tokenize()).parse()

    assert interpreter.interpret(ast) == [2, 42, 2, 42]
    assert interpreter.state.variables["outer"] == 0
    assert interpreter.stats.loop_iterations == 4


def test_continue_starts_next_iteration_and_preserves_prior_output():
    source = (
        "count = 2\n"
        "while (count)\n"
        "count\n"
        "count = count - 1\n"
        "continue\n"
        "99\n"
        "end while"
    )
    interpreter = Interpreter()
    ast = Parser(Lexer(source).tokenize()).parse()

    assert interpreter.interpret(ast) == [2, 1]
    assert interpreter.state.variables == {"count": 0}
    assert interpreter.stats.loop_iterations == 2


@pytest.mark.parametrize("node", [BreakNode(), ContinueNode()])
def test_loop_control_node_without_active_loop_is_internal_error(node):
    with pytest.raises(RuneInternalError):
        Interpreter().visit(node)


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


def test_unknown_unary_operator_raises_internal_error():
    bad_op = Token(TokenType.PLUS, "+")
    node = UnaryOpNode(bad_op, NumberNode(1))
    with pytest.raises(RuneInternalError):
        Interpreter().visit_unary(node)


def test_unknown_comparison_operator_raises_internal_error():
    bad_op = Token(TokenType.PLUS, "+")
    node = ComparisonNode(NumberNode(1), bad_op, NumberNode(2))
    with pytest.raises(RuneInternalError):
        Interpreter().visit_comparison(node)


def test_unknown_logical_operator_raises_internal_error():
    bad_op = Token(TokenType.PLUS, "+")
    node = LogicalOpNode(NumberNode(1), bad_op, NumberNode(2))
    with pytest.raises(RuneInternalError):
        Interpreter().visit_logical_op(node)


def test_unknown_logical_not_operator_raises_internal_error():
    bad_op = Token(TokenType.MINUS, "-")
    node = LogicalNotNode(bad_op, NumberNode(1))
    with pytest.raises(RuneInternalError):
        Interpreter().visit_logical_not(node)


@pytest.mark.parametrize("signal_type", [_BreakSignal, _ContinueSignal])
def test_loop_control_signal_preserves_output_from_nested_blocks(signal_type):
    marker = object()

    class SignalingInterpreter(Interpreter):
        def visit(self, node):
            if node is marker:
                raise signal_type()
            return super().visit(node)

    interpreter = SignalingInterpreter()
    nested_if = IfNode(NumberNode(1), [NumberNode(2), marker])

    with pytest.raises(signal_type) as exc_info:
        interpreter._exec_block([NumberNode(1), nested_if])

    assert exc_info.value.values == [1, 2]
    assert interpreter.stats.output_values == 2
