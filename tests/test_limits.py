import json
from pathlib import Path

import pytest

import rune
from runtime import compile_source, execute, evaluate, RuntimeState
from limits import ExecutionLimits
from interpreter import Interpreter
from diagnostics import DiagnosticKind, RuneLimitError
from spans import Position, SourceSpan

REPO_ROOT = Path(__file__).resolve().parent.parent

# "1\n2\n3" costs exactly 4 steps: 1 for the ProgramNode plus 1 per NumberNode.
THREE_STATEMENTS = "1\n2\n3"

# Peak recursion depth 3: outer if -> inner if's condition/body visit() calls.
NESTED_IF = 'if (1)\nif (1)\n99\nend\nend'


def test_execution_limits_rejects_invalid_values():
    with pytest.raises(ValueError):
        ExecutionLimits(max_steps=0)
    with pytest.raises(ValueError):
        ExecutionLimits(max_recursion_depth=0)
    with pytest.raises(ValueError):
        ExecutionLimits(max_output_values=0)
    with pytest.raises(ValueError):
        ExecutionLimits(max_variables=0)
    with pytest.raises(ValueError):
        ExecutionLimits(max_integer_bits=0)


def test_integer_at_exact_bit_limit_succeeds():
    result = evaluate("15 * 17", limits=ExecutionLimits(max_integer_bits=8))

    assert result.ok
    assert result.values == [255]


def test_multiplication_over_integer_limit_is_rejected_at_operator():
    result = evaluate("16 * 16", limits=ExecutionLimits(max_integer_bits=8))

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT
    assert result.diagnostics[0].message == (
        "Integer magnitude exceeds the 8-bit limit"
    )
    assert result.diagnostics[0].span == SourceSpan(
        Position(1, 4), Position(1, 5)
    )


def test_definitely_oversized_multiplication_is_not_attempted():
    class ExplodingInt(int):
        def __mul__(self, other):
            raise AssertionError("oversized product was allocated")

    interpreter = Interpreter(limits=ExecutionLimits(max_integer_bits=8))
    with pytest.raises(RuneLimitError):
        interpreter._checked_multiply(ExplodingInt(256), ExplodingInt(256), None)


def test_power_at_exact_bit_limit_succeeds():
    result = evaluate("2 ** 7", limits=ExecutionLimits(max_integer_bits=8))

    assert result.ok
    assert result.values == [128]


def test_oversized_power_is_rejected_at_operator():
    result = evaluate("2 ** 8", limits=ExecutionLimits(max_integer_bits=8))

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT
    assert result.diagnostics[0].message == (
        "Integer magnitude exceeds the 8-bit limit"
    )
    assert result.diagnostics[0].span == SourceSpan(
        Position(1, 3), Position(1, 5)
    )


def test_power_exact_check_rejects_inconclusive_preflight_boundary():
    result = evaluate("3 ** 2", limits=ExecutionLimits(max_integer_bits=3))

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT


def test_definitely_oversized_power_is_not_attempted():
    class ExplodingInt(int):
        def __pow__(self, exponent):
            raise AssertionError("oversized power was allocated")

    interpreter = Interpreter(limits=ExecutionLimits(max_integer_bits=8))
    with pytest.raises(RuneLimitError):
        interpreter._checked_power(ExplodingInt(256), 2, None)


def test_astronomical_exponent_is_rejected_before_power():
    result = evaluate("2 ** 999999999999999999999999999999999999")

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT


def test_addition_over_integer_limit_is_rejected():
    result = evaluate("255 + 1", limits=ExecutionLimits(max_integer_bits=8))

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT


def test_collapsed_string_over_integer_limit_is_rejected():
    result = evaluate('"AA"', limits=ExecutionLimits(max_integer_bits=7))

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT


def test_state_from_looser_limit_is_rejected_before_execution():
    state = RuntimeState(chaos_threshold=1, variables={"large": 256})
    result = evaluate("1", state, limits=ExecutionLimits(max_integer_bits=8))

    assert not result.ok
    assert result.state is state
    assert result.stats.steps == 0


def test_state_from_higher_variable_limit_is_rejected_before_execution():
    state = RuntimeState(variables={"a": 1, "b": 2})
    result = evaluate("1", state, limits=ExecutionLimits(max_variables=1))

    assert not result.ok
    assert result.diagnostics[0].message == "Variable budget exceeded"
    assert result.state is state
    assert result.stats.steps == 0


def test_repetitive_squaring_is_rejected_transactionally():
    state = RuntimeState(variables={"kept": 7})
    squarings = "\n".join(["x = x * x"] * 14)
    result = evaluate(
        f"x = 2\n{squarings}\nx",
        state,
    )

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT
    assert "14285-bit limit" in result.diagnostics[0].message
    assert result.state is state
    assert result.state.variables == {"kept": 7}
    assert result.events == []
    assert result.values == []


def test_step_budget_exact_limit_succeeds():
    program = compile_source(THREE_STATEMENTS)
    result = execute(program, limits=ExecutionLimits(max_steps=4))
    assert result.ok
    assert result.values == [1, 2, 3]
    assert result.stats.steps == 4


def test_step_budget_one_over_fails():
    program = compile_source(THREE_STATEMENTS)
    result = execute(program, limits=ExecutionLimits(max_steps=3))
    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT
    assert "Step budget exceeded" in result.diagnostics[0].message
    assert result.diagnostics[0].span == SourceSpan(
        Position(3, 1), Position(3, 2)
    )


def test_recursion_depth_exact_limit_succeeds():
    program = compile_source(NESTED_IF)
    result = execute(program, limits=ExecutionLimits(max_recursion_depth=3))
    assert result.ok
    assert result.values == [99]
    assert result.stats.peak_recursion_depth == 3


def test_deeply_nested_conditionals_exceed_recursion_depth():
    program = compile_source(NESTED_IF)
    result = execute(program, limits=ExecutionLimits(max_recursion_depth=2))
    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT
    assert "Recursion depth exceeded" in result.diagnostics[0].message
    assert result.diagnostics[0].span == SourceSpan(
        Position(2, 5), Position(2, 6)
    )


def test_depth_counter_recovers_after_failure():
    program = compile_source(NESTED_IF)
    interpreter = Interpreter(limits=ExecutionLimits(max_recursion_depth=2))
    with pytest.raises(RuneLimitError):
        interpreter.interpret(program.ast)
    assert interpreter._depth == 0


def test_output_budget_exact_limit_succeeds():
    program = compile_source(THREE_STATEMENTS)
    result = execute(program, limits=ExecutionLimits(max_output_values=3))
    assert result.ok
    assert result.values == [1, 2, 3]
    assert result.stats.output_values == 3


def test_output_budget_one_over_fails():
    program = compile_source(THREE_STATEMENTS)
    result = execute(program, limits=ExecutionLimits(max_output_values=2))
    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT
    assert "Output budget exceeded" in result.diagnostics[0].message


def test_nested_conditional_results_count_once():
    program = compile_source('if (1)\nif (1)\n1\n2\nend\nend')
    result = execute(program, limits=ExecutionLimits(max_output_values=2))
    assert result.ok
    assert result.values == [1, 2]
    assert result.stats.output_values == 2


def test_pragmas_do_not_consume_output_budget():
    program = compile_source("@chaos 1\n@chaos 2\n@chaos 3")
    result = execute(program, limits=ExecutionLimits(max_output_values=1))
    assert result.ok
    assert result.values == []
    assert result.stats.output_values == 0


def test_variable_budget_rejects_new_name_and_rolls_back():
    state = RuntimeState(variables={"first": 1})
    result = evaluate(
        "second = 2",
        state,
        limits=ExecutionLimits(max_variables=1),
    )
    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT
    assert result.diagnostics[0].message == "Variable budget exceeded"
    assert result.state is state
    assert result.state.variables == {"first": 1}


def test_variable_budget_allows_reassignment_at_limit():
    state = RuntimeState(variables={"answer": 1})
    result = evaluate(
        "answer = 42",
        state,
        limits=ExecutionLimits(max_variables=1),
    )
    assert result.ok
    assert result.state.variables == {"answer": 42}


def test_output_limit_diagnostic_includes_source_span():
    program = compile_source(THREE_STATEMENTS)
    result = execute(program, limits=ExecutionLimits(max_output_values=2))
    assert result.diagnostics[0].span == SourceSpan(
        Position(3, 1), Position(3, 2)
    )


def test_limit_result_serializes_to_json():
    program = compile_source(THREE_STATEMENTS)
    result = execute(program, limits=ExecutionLimits(max_output_values=2))
    assert json.dumps(result.to_dict())


def test_failed_limited_execution_rolls_back_state():
    state = RuntimeState(chaos_threshold=1)
    result = evaluate(
        "@chaos 500\n1\n2\n3", state, limits=ExecutionLimits(max_output_values=2)
    )
    assert not result.ok
    # The chaos pragma ran before the limit tripped, but the failure must
    # discard that working state and return exactly what was supplied.
    assert result.state is state
    assert state.chaos_threshold == 1


def test_failed_limited_execution_discards_runtime_events():
    result = evaluate(
        "@chaos 500\n1\n2", limits=ExecutionLimits(max_output_values=1)
    )
    assert not result.ok
    assert result.events == []


def test_failed_limited_execution_returns_no_partial_values():
    result = evaluate("1\n2\n3", limits=ExecutionLimits(max_output_values=2))
    assert not result.ok
    assert result.values == []


def test_failed_limited_execution_reports_stats_before_termination():
    result = evaluate("1\n2\n3", limits=ExecutionLimits(max_output_values=2))
    assert result.stats is not None
    assert result.stats.output_values == 2


def test_default_limits_execute_test_rune():
    source = (REPO_ROOT / "test.rune").read_text()
    result = evaluate(source)
    assert result.ok
    assert result.values == [42, 4, 626, 1, 2, 0]


def test_cli_exits_with_status_1_for_a_limit_error(capsys):
    # 1001 simple statements exceeds the default max_output_values (1000)
    # without coming close to the default step or recursion budgets.
    source = "\n".join(["1"] * 1001)
    rc = rune.run_code(source)

    assert rc == 1
    err = capsys.readouterr().err
    assert "Execution limit" in err


def test_repl_remains_usable_after_a_limited_evaluation_fails(monkeypatch, capsys):
    overflowing_line = "\n".join(["1"] * 1001)
    inputs = iter([overflowing_line, "2+2"])

    def fake_input(prompt=""):
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    rune.repl()

    out = capsys.readouterr().out
    assert "Execution limit" in out
    assert "=> 4" in out
    assert "Goodbye!" in out
