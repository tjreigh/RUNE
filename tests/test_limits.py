import json
from pathlib import Path

import pytest

from rune import cli
from rune.runtime import compile_source, execute, evaluate, RuntimeState
from rune.limits import ExecutionLimits, ExecutionStats
from rune.interpreter import Interpreter
from rune.ast_nodes import GroupNode, NumberNode
from rune.diagnostics import DiagnosticKind, RuneLimitError
from rune.spans import Position, SourceSpan

rune = cli

REPO_ROOT = Path(__file__).resolve().parent.parent

# "1\n2\n3" costs exactly 4 steps: 1 for the ProgramNode plus 1 per NumberNode.
THREE_STATEMENTS = "1\n2\n3"

# Peak recursion depth 3: outer if -> inner if's condition/body visit() calls.
NESTED_IF = 'if (1)\nif (1)\n99\nend if\nend if'


def test_execution_limits_rejects_invalid_values():
    with pytest.raises(ValueError):
        ExecutionLimits(max_steps=0)
    with pytest.raises(ValueError):
        ExecutionLimits(max_recursion_depth=0)
    with pytest.raises(ValueError):
        ExecutionLimits(max_output_values=0)
    with pytest.raises(ValueError):
        ExecutionLimits(max_events=0)
    with pytest.raises(ValueError):
        ExecutionLimits(max_variables=0)
    with pytest.raises(ValueError):
        ExecutionLimits(max_integer_bits=0)


def test_unbounded_policy_disables_every_interpreter_budget():
    limits = ExecutionLimits.unbounded()

    assert limits.is_unbounded
    assert limits.max_steps is None
    assert limits.max_recursion_depth is None
    assert limits.max_output_values is None
    assert limits.max_events is None
    assert limits.max_variables is None
    assert limits.max_integer_bits is None
    assert not ExecutionLimits().is_unbounded


def test_unbounded_policy_removes_all_interpreter_ceilings():
    limits = ExecutionLimits.unbounded()

    many_iterations = evaluate(
        "for i from 1 to 10001\nend for",
        limits=limits,
    )
    assert many_iterations.ok
    assert many_iterations.stats.loop_iterations == 10_001

    many_outputs = evaluate("\n".join(["1"] * 1_001), limits=limits)
    assert many_outputs.ok
    assert len(many_outputs.values) == 1_001

    many_events = evaluate("\n".join(["@chaos 1"] * 1_001), limits=limits)
    assert many_events.ok
    assert len(many_events.events) == 1_001

    many_variables = evaluate(
        "\n".join(f"value_{index} = {index}" for index in range(257)),
        limits=limits,
    )
    assert many_variables.ok
    assert len(many_variables.state.variables) == 257

    large_integer = evaluate("large = 2 ** 14285", limits=limits)
    assert large_integer.ok
    assert large_integer.state.variables["large"].bit_length() == 14_286

    deeply_nested = NumberNode(1)
    for _ in range(101):
        deeply_nested = GroupNode(deeply_nested)
    interpreter = Interpreter(limits=limits)
    assert interpreter.interpret(deeply_nested) == 1
    assert interpreter.stats.peak_recursion_depth == 102


def test_new_stats_fields_default_to_zero_for_existing_callers():
    stats = ExecutionStats(steps=1, peak_recursion_depth=2, output_values=3)

    assert stats.runtime_events == 0
    assert stats.loop_iterations == 0


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


def test_left_shift_at_exact_bit_limit_succeeds():
    result = evaluate("1 << 7", limits=ExecutionLimits(max_integer_bits=8))

    assert result.ok
    assert result.values == [128]


def test_oversized_left_shift_is_rejected_at_operator():
    result = evaluate("1 << 8", limits=ExecutionLimits(max_integer_bits=8))

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT
    assert result.diagnostics[0].span == SourceSpan(
        Position(1, 3), Position(1, 5)
    )


def test_definitely_oversized_left_shift_is_not_attempted():
    class ExplodingInt(int):
        def __lshift__(self, count):
            raise AssertionError("oversized left shift was allocated")

    interpreter = Interpreter(limits=ExecutionLimits(max_integer_bits=8))
    with pytest.raises(RuneLimitError):
        interpreter._checked_left_shift(ExplodingInt(1), 8, None)


def test_bitwise_result_still_obeys_integer_limit():
    result = evaluate("255 ^ -1", limits=ExecutionLimits(max_integer_bits=8))

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT


def test_zero_left_shift_by_astronomical_count_stays_zero():
    result = evaluate("0 << 999999999999999999999999999999999999")

    assert result.ok
    assert result.values == [0]


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


def test_nested_loop_iterations_do_not_accumulate_recursion_depth():
    result = evaluate(
        "for outer from 1 to 20\n"
        "for inner from 1 to 20\n"
        "end for\n"
        "end for",
        limits=ExecutionLimits(max_recursion_depth=3),
    )

    assert result.ok
    assert result.values == []
    assert result.stats.loop_iterations == 420
    assert result.stats.peak_recursion_depth == 3


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
    program = compile_source('if (1)\nif (1)\n1\n2\nend if\nend if')
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


def test_event_budget_exact_limit_succeeds():
    result = evaluate(
        "@chaos 1\n@chaos 2",
        limits=ExecutionLimits(max_events=2),
    )

    assert result.ok
    assert len(result.events) == 2
    assert result.stats.runtime_events == 2


def test_event_budget_one_over_fails_transactionally():
    state = RuntimeState(chaos_threshold=7)
    result = evaluate(
        "@chaos 1\n@chaos 2",
        state,
        limits=ExecutionLimits(max_events=1),
    )

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT
    assert result.diagnostics[0].message == "Event budget exceeded"
    assert result.diagnostics[0].span == SourceSpan(
        Position(2, 1), Position(2, 9)
    )
    assert result.state is state
    assert result.events == []
    assert result.stats.runtime_events == 1


def test_loop_generated_events_hit_budget_transactionally():
    state = RuntimeState(variables={"kept": 7})
    result = evaluate(
        "for i from 1 to 1001\nvalue = i\nend for",
        state,
    )

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT
    assert result.diagnostics[0].message == "Event budget exceeded"
    assert result.state is state
    assert result.state.variables == {"kept": 7}
    assert result.values == []
    assert result.events == []
    assert result.stats.runtime_events == 1_000
    assert result.stats.loop_iterations == 1_001


def test_loop_iteration_accounting_charges_steps_before_entry():
    interpreter = Interpreter(limits=ExecutionLimits(max_steps=1))

    interpreter._begin_loop_iteration(None)

    assert interpreter.stats.steps == 1
    assert interpreter.stats.loop_iterations == 1
    with pytest.raises(RuneLimitError, match="Step budget exceeded"):
        interpreter._begin_loop_iteration(None)
    assert interpreter.stats.loop_iterations == 1


def test_infinite_empty_while_exhausts_general_step_budget():
    result = evaluate(
        "while (1)\nend while",
        limits=ExecutionLimits(max_steps=5),
    )

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT
    assert result.diagnostics[0].message == "Step budget exceeded"
    assert result.diagnostics[0].span == SourceSpan(
        Position(1, 8), Position(1, 9)
    )
    assert result.values == []
    assert result.stats.loop_iterations == 2


def test_loop_limit_failure_is_transactional_and_recovers_active_depth():
    state = RuntimeState(variables={"kept": 7})
    program = compile_source(
        "count = 2\nwhile (count)\ncount\ncount = count - 1\nend while"
    )
    interpreter = Interpreter(
        state=state,
        limits=ExecutionLimits(max_output_values=1),
    )

    with pytest.raises(RuneLimitError):
        interpreter.interpret(program.ast)

    assert interpreter._active_loop_depth == 0

    result = execute(
        program,
        state=state,
        limits=ExecutionLimits(max_output_values=1),
    )
    assert not result.ok
    assert result.state is state
    assert result.state.variables == {"kept": 7}
    assert result.events == []
    assert result.values == []


def test_large_for_loop_exhausts_general_step_budget():
    result = evaluate(
        "for i from 1 to 100\nend for",
        limits=ExecutionLimits(max_steps=5),
    )

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT
    assert result.diagnostics[0].message == "Step budget exceeded"
    assert result.diagnostics[0].span == SourceSpan(
        Position(1, 5), Position(1, 6)
    )
    assert result.stats.loop_iterations == 2


def test_loop_integer_growth_hits_budget_transactionally():
    state = RuntimeState(variables={"kept": 7})
    result = evaluate(
        "value = 2\n"
        "for i from 1 to 14\n"
        "value = value * value\n"
        "end for",
        state,
    )

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LIMIT
    assert "14285-bit limit" in result.diagnostics[0].message
    assert result.state is state
    assert result.state.variables == {"kept": 7}
    assert result.values == []
    assert result.events == []
    assert result.stats.loop_iterations == 14


def test_for_counter_obeys_variable_budget_and_scope_recovers():
    state = RuntimeState(variables={"kept": 7})
    program = compile_source("for i from 1 to 0\nend for")
    interpreter = Interpreter(
        state=state,
        limits=ExecutionLimits(max_variables=1),
    )

    with pytest.raises(RuneLimitError, match="Variable budget exceeded"):
        interpreter.interpret(program.ast)

    assert interpreter._bindings.depth == 0

    result = execute(
        program,
        state=state,
        limits=ExecutionLimits(max_variables=1),
    )
    assert not result.ok
    assert result.state is state
    assert result.state.variables == {"kept": 7}


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
    assert result.values == [
        42, 42, 25, -3, -2, 42, 626, 0, 1, 1, 1, 2, 1, 0,
        5, 4, 3, 1, 3, 5, 1, 3, 4, 120,
    ]


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
