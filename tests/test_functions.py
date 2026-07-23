import pytest

from rune.ast_nodes import (
    BinaryOpNode,
    FunctionCallNode,
    FunctionDefinitionNode,
    ReturnNode,
)
from rune.diagnostics import RuneInternalError, RuneParseError, RuneRuntimeError
from rune.interpreter import Interpreter
from rune.lexer import Lexer
from rune.limits import ExecutionLimits
from rune.parser import MAX_EXPRESSION_NESTING, Parser
from rune.runtime import RuntimeState, evaluate
from rune.spans import Position, SourceSpan


def _parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def test_function_definition_and_call_ast_retain_structure_and_spans():
    ast = _parse(
        "function add(left, right)\n"
        "return left + right\n"
        "end function\n"
        "add(20, 22)"
    )

    definition, call = ast.statements
    assert isinstance(definition, FunctionDefinitionNode)
    assert definition.name == "add"
    assert definition.parameters == ["left", "right"]
    assert isinstance(definition.body[0], ReturnNode)
    assert isinstance(definition.body[0].value, BinaryOpNode)
    assert definition.name_span == SourceSpan(
        Position(1, 10), Position(1, 13)
    )
    assert definition.span == SourceSpan(
        Position(1, 1), Position(3, 13)
    )

    assert isinstance(call, FunctionCallNode)
    assert call.name == "add"
    assert [argument.value for argument in call.arguments] == [20, 22]
    assert call.span == SourceSpan(Position(4, 1), Position(4, 12))


def test_zero_argument_function_and_call_parse():
    ast = _parse("function answer()\nreturn 42\nend function\nanswer()")
    definition, call = ast.statements

    assert definition.parameters == []
    assert call.arguments == []


def test_function_call_is_a_primary_expression():
    ast = _parse("double(20) + 2")

    assert isinstance(ast, BinaryOpNode)
    assert isinstance(ast.left, FunctionCallNode)
    assert ast.left.arguments[0].value == 20


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("return 1", "'return' is only valid inside a function"),
        (
            "if (1)\nfunction nested()\nreturn 1\nend function\nend if",
            "Function declarations are only valid at the top level",
        ),
        (
            "function duplicate(a, a)\nreturn a\nend function",
            "Duplicate parameter 'a'",
        ),
        (
            "function same()\nreturn 1\nend function\n"
            "function same()\nreturn 2\nend function",
            "Function 'same' is already defined",
        ),
        (
            "function invalid()\nbreak\nreturn 1\nend function",
            "'break' is only valid inside a loop",
        ),
    ],
)
def test_invalid_function_structure_is_a_parse_error(source, message):
    with pytest.raises(RuneParseError) as exc_info:
        _parse(source)

    assert exc_info.value.diagnostic.message == message


def test_function_requires_matching_typed_terminator():
    with pytest.raises(RuneParseError) as exc_info:
        _parse("function answer()\nreturn 42\nend if")

    assert exc_info.value.diagnostic.message == (
        "Expected 'function' after 'end'"
    )


def test_nested_calls_respect_expression_nesting_limit():
    accepted = "identity(" * MAX_EXPRESSION_NESTING + "1" + (
        ")" * MAX_EXPRESSION_NESTING
    )
    assert _parse(accepted) is not None

    rejected = "identity(" * (MAX_EXPRESSION_NESTING + 1) + "1" + (
        ")" * (MAX_EXPRESSION_NESTING + 1)
    )
    with pytest.raises(RuneParseError) as exc_info:
        _parse(rejected)

    assert "Expression nesting exceeds" in exc_info.value.diagnostic.message


def test_function_call_returns_one_value_without_leaking_body_expressions():
    result = evaluate(
        "function answer()\n"
        "1\n"
        "2\n"
        "return 42\n"
        "missing\n"
        "end function\n"
        "answer()"
    )

    assert result.ok
    assert result.values == [42]
    assert result.stats.output_values == 1


def test_arguments_evaluate_left_to_right_and_strings_collapse_normally():
    result = evaluate(
        "function add(left, right)\n"
        "return left + right\n"
        "end function\n"
        'add("cat", 1)'
    )

    assert result.values == [sum(ord(char) for char in "cat") + 1]


def test_argument_calls_evaluate_from_left_to_right():
    result = evaluate(
        "function raise_chaos()\n"
        "@chaos 10\n"
        "return 1\n"
        "end function\n"
        "function observe_chaos()\n"
        "if (5)\n"
        "return 0\n"
        "else\n"
        "return 1\n"
        "end if\n"
        "end function\n"
        "function second(left, right)\n"
        "return right\n"
        "end function\n"
        "second(raise_chaos(), observe_chaos())"
    )

    assert result.ok
    assert result.values == [1]
    assert result.state.chaos_threshold == 10


def test_parameters_and_assignments_are_local_while_globals_are_readable():
    result = evaluate(
        "offset = 2\n"
        "value = 100\n"
        "function calculate(value)\n"
        "temporary = value + offset\n"
        "value = temporary * 2\n"
        "return value\n"
        "end function\n"
        "calculate(20)\n"
        "value"
    )

    assert result.ok
    assert result.values == [44, 100]
    assert result.state.variables == {"offset": 2, "value": 100}
    assert "temporary" not in result.state.variables


def test_callees_cannot_read_their_callers_local_bindings():
    result = evaluate(
        "value = 7\n"
        "function read_global()\n"
        "return value\n"
        "end function\n"
        "function caller(value)\n"
        "temporary = 99\n"
        "return read_global()\n"
        "end function\n"
        "caller(42)"
    )

    assert result.ok
    assert result.values == [7]


def test_callee_cannot_resolve_a_caller_only_local():
    result = evaluate(
        "function read_local()\n"
        "return temporary\n"
        "end function\n"
        "function caller()\n"
        "temporary = 99\n"
        "return read_local()\n"
        "end function\n"
        "caller()"
    )

    assert not result.ok
    assert result.diagnostics[0].message == "Undefined variable 'temporary'"


def test_return_escapes_nested_conditionals_and_loops():
    result = evaluate(
        "function find()\n"
        "for i from 1 to 5\n"
        "if (i == 3)\n"
        "return i\n"
        "end if\n"
        "end for\n"
        "return 0\n"
        "end function\n"
        "find()"
    )

    assert result.values == [3]
    assert result.stats.loop_iterations == 3


def test_function_call_restores_the_callers_active_loop():
    result = evaluate(
        "function one()\nreturn 1\nend function\n"
        "for i from 1 to 3\n"
        "one()\n"
        "break\n"
        "end for"
    )

    assert result.ok
    assert result.values == [1]
    assert result.stats.loop_iterations == 1


def test_declarations_are_hoisted_for_forward_calls_and_mutual_recursion():
    result = evaluate(
        "even(6)\n"
        "function even(n)\n"
        "if (n == 0)\n"
        "return 1\n"
        "end if\n"
        "return odd(n - 1)\n"
        "end function\n"
        "function odd(n)\n"
        "if (n == 0)\n"
        "return 0\n"
        "end if\n"
        "return even(n - 1)\n"
        "end function"
    )

    assert result.ok
    assert result.values == [1]


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("missing(1)", "Undefined function 'missing'"),
        (
            "function one(value)\nreturn value\nend function\none()",
            "Function 'one' expects 1 argument, got 0",
        ),
        (
            "function two(a, b)\nreturn a + b\nend function\ntwo(1)",
            "Function 'two' expects 2 arguments, got 1",
        ),
        (
            "function none()\n1\nend function\nnone()",
            "Function 'none' returned no value",
        ),
    ],
)
def test_function_runtime_errors_are_structured(source, message):
    result = evaluate(source)

    assert not result.ok
    assert result.diagnostics[0].kind.value == "runtime"
    assert result.diagnostics[0].message == message
    assert result.diagnostics[0].span is not None


def test_recursive_calls_are_bounded_by_runtime_recursion_limit():
    result = evaluate(
        "function recurse(n)\nreturn recurse(n + 1)\nend function\nrecurse(0)",
        limits=ExecutionLimits(max_recursion_depth=20),
    )

    assert not result.ok
    assert result.diagnostics[0].kind.value == "limit"
    assert result.diagnostics[0].message == "Recursion depth exceeded"


def test_function_parameter_frames_share_the_variable_budget():
    result = evaluate(
        "function pair(a, b)\nreturn a + b\nend function\npair(1, 2)",
        limits=ExecutionLimits(max_variables=1),
    )

    assert not result.ok
    assert result.diagnostics[0].message == "Variable budget exceeded"


def test_failed_function_call_is_transactional():
    state = RuntimeState(variables={"persistent": 7})
    result = evaluate(
        "function fail()\n"
        "@chaos 500\n"
        "local = 42\n"
        "end function\n"
        "fail()",
        state=state,
    )

    assert not result.ok
    assert result.state is state
    assert result.state.to_dict() == {
        "chaos_threshold": 1,
        "variables": {"persistent": 7},
    }
    assert result.events == []


def test_function_declarations_are_source_local_not_session_state():
    declared = evaluate(
        "function answer()\nreturn 42\nend function\nanswer()"
    )
    later = evaluate("answer()", state=declared.state)

    assert declared.values == [42]
    assert not later.ok
    assert later.diagnostics[0].message == "Undefined function 'answer'"


def test_reused_interpreter_does_not_retain_function_declarations():
    interpreter = Interpreter()
    interpreter.interpret(
        _parse("function answer()\nreturn 42\nend function\nanswer()")
    )

    with pytest.raises(RuneRuntimeError) as exc_info:
        interpreter.interpret(_parse("answer()"))

    assert exc_info.value.diagnostic.message == "Undefined function 'answer'"


def test_failed_function_call_always_unwinds_local_runtime_context():
    interpreter = Interpreter()
    ast = _parse("function none(value)\nlocal = value\nend function\nnone(1)")

    with pytest.raises(RuneRuntimeError):
        interpreter.interpret(ast)

    assert interpreter._bindings.depth == 0
    assert interpreter._active_function_depth == 0
    assert interpreter._active_loop_depth == 0


def test_manual_return_outside_function_is_an_internal_error():
    node = ReturnNode(_parse("1"), span=SourceSpan.at(Position(1, 1)))

    with pytest.raises(RuneInternalError) as exc_info:
        Interpreter().visit_return(node)

    assert exc_info.value.diagnostic.message == "Return outside active function"
