import json

import pytest

from runtime import (
    RuntimeState,
    RuntimeEvent,
    CompiledProgram,
    compile_source,
    evaluate,
)
from diagnostics import DiagnosticKind
from ast_nodes import BinaryOpNode
from spans import Position, SourceSpan


def test_single_output_normalization():
    result = evaluate("2+2")
    assert result.ok
    assert result.values == [4]


def test_multiple_outputs():
    result = evaluate("1\n2\n3")
    assert result.ok
    assert result.values == [1, 2, 3]


def test_prefixed_integer_literals_are_ordinary_runtime_integers():
    result = evaluate("mask = 0b11110000\nmask + 0o10 + 0x10")

    assert result.ok
    assert result.values == [264]
    assert result.state.variables == {"mask": 240}


def test_malformed_prefixed_integer_becomes_lex_diagnostic():
    result = evaluate("0b102")

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LEX
    assert result.diagnostics[0].message == (
        "Invalid digit '2' in binary integer literal"
    )


def test_grouping_and_unary_operations_work_in_assignment_and_condition():
    result = evaluate(
        "answer = -(40 + 2)\n"
        "if ((~answer))\n"
        "answer\n"
        "else\n"
        "0\n"
        "end"
    )

    assert result.ok
    assert result.values == [-42]
    assert result.state.variables == {"answer": -42}


def test_grouping_preserves_inner_undefined_variable_span():
    result = evaluate("(missing)")

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.RUNTIME
    assert result.diagnostics[0].span == SourceSpan(
        Position(1, 2), Position(1, 9)
    )


def test_pragma_only_produces_no_output():
    result = evaluate("@chaos 500")
    assert result.ok
    assert result.values == []


def test_successful_chaos_state_update():
    result = evaluate("@chaos 500")
    assert result.state.chaos_threshold == 500


def test_variables_persist_across_evaluations():
    assigned = evaluate('animal = "cat"')
    assert assigned.ok
    assert assigned.values == []
    assert assigned.state.variables == {"animal": 312}

    looked_up = evaluate("animal + 1", assigned.state)
    assert looked_up.ok
    assert looked_up.values == [313]


def test_undefined_variable_is_a_runtime_diagnostic_at_its_name():
    result = evaluate("missing + 1")
    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.RUNTIME
    assert result.diagnostics[0].message == "Undefined variable 'missing'"
    assert result.diagnostics[0].span == SourceSpan(
        Position(1, 1), Position(1, 8)
    )


def test_chaos_changes_preserve_variables():
    result = evaluate("answer = 42\n@chaos 500")
    assert result.ok
    assert result.state.chaos_threshold == 500
    assert result.state.variables == {"answer": 42}


def test_failed_execution_rolls_back_variable_assignments():
    state = RuntimeState(variables={"kept": 7})
    result = evaluate("temporary = 9\nmissing", state)
    assert not result.ok
    assert result.state is state
    assert result.state.variables == {"kept": 7}


def test_runtime_state_detaches_input_and_returned_variable_mappings():
    source_variables = {"answer": 42}
    state = RuntimeState(variables=source_variables)
    source_variables["answer"] = 0
    detached = state.variables
    detached["answer"] = -1
    assert state.variables == {"answer": 42}


def test_runtime_state_rejects_invalid_numeric_types():
    for threshold in (True, -1, "1"):
        with pytest.raises(ValueError):
            RuntimeState(chaos_threshold=threshold)

    for value in (True, "42"):
        with pytest.raises(ValueError):
            RuntimeState(variables={"answer": value})


def test_supplied_state_affects_later_conditionals():
    state = RuntimeState(chaos_threshold=500)
    result = evaluate('if ("dog" > "cat")\n1\nelse\n0\nend', state)
    assert result.values == [0]


def test_lex_failure_becomes_diagnostic():
    result = evaluate("#")
    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LEX


def test_oversized_integer_literal_becomes_lex_diagnostic():
    result = evaluate("9" * 4_301)

    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LEX
    assert "4300-digit limit" in result.diagnostics[0].message


def test_parse_failure_becomes_diagnostic():
    result = evaluate("if (1)\n1\n")
    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.PARSE


def test_failed_evaluation_preserves_input_state():
    state = RuntimeState(chaos_threshold=42)
    result = evaluate("#", state)
    assert result.state is state


def test_input_state_is_never_mutated():
    state = RuntimeState(chaos_threshold=7)
    evaluate("@chaos 999", state)
    assert state.chaos_threshold == 7


def test_runtime_events_are_structured():
    result = evaluate("@chaos 500")
    assert len(result.events) == 1
    event = result.events[0]
    assert isinstance(event, RuntimeEvent)
    assert event.kind == "chaos_threshold_changed"
    assert event.data == {"threshold": 500}
    assert event.span == SourceSpan(Position(1, 1), Position(1, 11))


def test_assignment_event_is_structured():
    result = evaluate("answer = 42")
    assert result.events[0].kind == "variable_assigned"
    assert result.events[0].data == {"name": "answer", "value": 42}


def test_core_evaluation_produces_no_terminal_output(capsys):
    evaluate("@chaos 500\n1")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_successful_result_serializes_to_json():
    result = evaluate("2+2")
    assert json.dumps(result.to_dict())


def test_variable_state_serializes_to_json():
    result = evaluate("answer = 42")
    assert result.to_dict()["state"] == {
        "chaos_threshold": 1,
        "variables": {"answer": 42},
    }
    assert json.dumps(result.to_dict())


def test_diagnostic_result_serializes_to_json():
    result = evaluate("#")
    assert json.dumps(result.to_dict())


def test_compile_source_retains_tokens_and_ast():
    program = compile_source("2+2")
    assert isinstance(program, CompiledProgram)
    assert len(program.tokens) > 0
    assert isinstance(program.ast, BinaryOpNode)


def test_spec_acceptance_example():
    state = RuntimeState()

    first = evaluate("@chaos 500", state)
    assert first.ok
    assert first.values == []
    assert first.state.chaos_threshold == 500
    assert state.chaos_threshold == 1

    second = evaluate(
        'if ("dog" > "cat")\n1\nelse\n0\nend',
        first.state,
    )
    assert second.values == [0]
