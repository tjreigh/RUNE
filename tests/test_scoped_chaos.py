import pytest

from rune.diagnostics import DiagnosticKind, RuneRuntimeError
from rune.interpreter import Interpreter
from rune.limits import ExecutionLimits
from rune.parser import Parser
from rune.lexer import Lexer
from rune.runtime import RuntimeState, evaluate


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def test_scoped_chaos_restores_threshold_and_emits_ordered_events():
    result = evaluate(
        "@chaos 2\n"
        "chaos 10\n"
        "  @chaos 20\n"
        "end chaos\n"
        "1"
    )

    assert result.ok
    assert result.state.chaos_threshold == 2
    assert [event.kind for event in result.events] == [
        "chaos_threshold_changed",
        "chaos_scope_entered",
        "chaos_threshold_changed",
        "chaos_scope_restored",
    ]
    assert result.events[-1].data == {
        "previous_threshold": 20,
        "threshold": 2,
    }


def test_nested_scopes_restore_in_stack_order():
    result = evaluate(
        "chaos 10\n"
        "  chaos 20\n"
        "    @chaos 30\n"
        "  end chaos\n"
        "end chaos"
    )

    assert result.ok
    assert result.state.chaos_threshold == 1
    restored = [
        event.data["threshold"]
        for event in result.events
        if event.kind == "chaos_scope_restored"
    ]
    assert restored == [10, 1]


def test_function_called_inside_scope_observes_temporary_threshold():
    result = evaluate(
        "function classify(value)\n"
        "  if (value)\n"
        "    return 1\n"
        "  end if\n"
        "  return 0\n"
        "end function\n"
        "chaos 50\n"
        "  classify(25)\n"
        "end chaos\n"
        "classify(25)"
    )

    assert result.ok
    assert result.values == [0, 1]


@pytest.mark.parametrize(
    "source,expected",
    [
        (
            "function answer()\n"
            "  chaos 100\n"
            "    return 42\n"
            "  end chaos\n"
            "end function\n"
            "answer()",
            [42],
        ),
        (
            "for i from 1 to 2\n"
            "  chaos 100\n"
            "    break\n"
            "  end chaos\n"
            "end for\n"
            "1",
            [1],
        ),
        (
            "for i from 1 to 2\n"
            "  chaos 100\n"
            "    continue\n"
            "  end chaos\n"
            "end for\n"
            "1",
            [1],
        ),
    ],
)
def test_scope_restores_across_non_local_control_flow(source, expected):
    result = evaluate(source)

    assert result.ok
    assert result.values == expected
    assert result.state.chaos_threshold == 1


def test_negative_scoped_threshold_is_a_runtime_diagnostic():
    result = evaluate("chaos -1\n1\nend chaos")

    assert not result.ok
    assert result.diagnostics[0].kind is DiagnosticKind.RUNTIME
    assert result.diagnostics[0].message == (
        "Chaos threshold must be a non-negative integer"
    )


def test_runtime_failure_restores_interpreter_working_threshold():
    interpreter = Interpreter(state=RuntimeState(chaos_threshold=7))

    with pytest.raises(RuneRuntimeError, match="Division by zero"):
        interpreter.interpret(parse("chaos 99\n1 / 0\nend chaos"))

    assert interpreter.state.chaos_threshold == 7


def test_existing_failure_is_not_masked_when_restoration_event_hits_budget():
    result = evaluate(
        "chaos 99\n1 / 0\nend chaos",
        limits=ExecutionLimits(max_events=1),
    )

    assert not result.ok
    assert result.diagnostics[0].message == "Division by zero"


def test_successful_restoration_still_obeys_event_budget():
    result = evaluate(
        "chaos 99\n1\nend chaos",
        limits=ExecutionLimits(max_events=1),
    )

    assert not result.ok
    assert result.diagnostics[0].kind is DiagnosticKind.LIMIT
    assert result.diagnostics[0].message == "Event budget exceeded"
