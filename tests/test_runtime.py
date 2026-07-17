import json

from runtime import (
    RuntimeState,
    RuntimeEvent,
    CompiledProgram,
    compile_source,
    evaluate,
)
from diagnostics import DiagnosticKind
from ast_nodes import BinaryOpNode


def test_single_output_normalization():
    result = evaluate("2+2")
    assert result.ok
    assert result.values == [4]


def test_multiple_outputs():
    result = evaluate("1\n2\n3")
    assert result.ok
    assert result.values == [1, 2, 3]


def test_pragma_only_produces_no_output():
    result = evaluate("@chaos 500")
    assert result.ok
    assert result.values == []


def test_successful_chaos_state_update():
    result = evaluate("@chaos 500")
    assert result.state.chaos_threshold == 500


def test_supplied_state_affects_later_conditionals():
    state = RuntimeState(chaos_threshold=500)
    result = evaluate('if ("dog" > "cat")\n1\nelse\n0\nend', state)
    assert result.values == [0]


def test_lex_failure_becomes_diagnostic():
    result = evaluate("#")
    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.LEX


def test_parse_failure_becomes_diagnostic():
    result = evaluate("if (1)\n1\n")
    assert not result.ok
    assert result.diagnostics[0].kind == DiagnosticKind.PARSE


def test_failed_evaluation_preserves_input_state():
    state = RuntimeState(chaos_threshold=42)
    result = evaluate("#", state)
    assert result.state.chaos_threshold == 42


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


def test_successful_result_serializes_to_json():
    result = evaluate("2+2")
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
