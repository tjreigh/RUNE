import json

import pytest

from rune import (
    ExecutionLimits,
    RuntimeState,
    TraceLimits,
    evaluate,
    trace_evaluate,
)
from rune.diagnostics import DiagnosticKind
from rune.interpreter import Interpreter
from rune.runtime import compile_source


def active_kinds(result):
    return [
        frame.active["node_kind"]
        for frame in result.frames
        if frame.active is not None
    ]


def test_interpreter_delivers_side_effects_incrementally_to_trace_recorder():
    class ProbeRecorder:
        def __init__(self):
            self.snapshots = []
            self.output_values = []
            self.events = []

        def capture(self, interpreter, **_checkpoint):
            self.snapshots.append(interpreter.trace_snapshot())

        def record_output(self, value, _span):
            self.output_values.append(value)

        def record_event(self, event):
            self.events.append(event.to_dict())

    recorder = ProbeRecorder()
    interpreter = Interpreter(trace_recorder=recorder)
    interpreter.interpret(compile_source("answer = 42\nanswer").ast)

    assert recorder.output_values == [42]
    assert [event["kind"] for event in recorder.events] == [
        "variable_assigned"
    ]
    assert all("output_values" not in item for item in recorder.snapshots)
    assert all("events" not in item for item in recorder.snapshots)


def test_straight_line_trace_is_a_sequence_of_pre_execution_checkpoints():
    result = trace_evaluate("answer = 40\nanswer = answer + 2\nanswer")

    assert result.ok
    assert result.base_state == RuntimeState()
    assert active_kinds(result) == [
        "AssignmentNode",
        "AssignmentNode",
        "VariableNode",
    ]
    assert result.frames[-1].status == "completed"
    assert result.frames[-1].active is None
    assert result.frames[1].changes["variables"] == [
        {
            "name": "answer",
            "before_exists": False,
            "before": None,
            "after_exists": True,
            "after": 40,
        }
    ]
    assert result.frames[-1].changes["output_values"] == [42]


def test_statement_checkpoints_consistently_include_the_active_node_charge():
    result = trace_evaluate("1\nif (1)\n2\nend if")
    active = [frame for frame in result.frames if frame.active is not None]

    assert [frame.active["node_kind"] for frame in active] == [
        "NumberNode",
        "IfCondition",
        "NumberNode",
    ]
    assert [frame.stats["steps"] for frame in active[:2]] == [2, 3]
    assert [frame.stats["peak_recursion_depth"] for frame in active[:2]] == [
        2,
        2,
    ]


def test_trace_is_non_committing_even_when_execution_succeeds():
    state = RuntimeState(chaos_threshold=7, variables={"kept": 1})
    result = trace_evaluate("@chaos 99\nkept = 2\nnew = 3", state=state)

    assert result.ok
    assert result.base_state is state
    assert state.to_dict() == {
        "chaos_threshold": 7,
        "variables": {"kept": 1},
    }


def test_function_calls_step_into_bodies_and_expose_local_lifetime():
    result = trace_evaluate(
        "function add_one(value)\n"
        "  local = value + 1\n"
        "  return local\n"
        "end function\n"
        "answer = add_one(41)\n"
        "answer"
    )

    assert active_kinds(result) == [
        "AssignmentNode",
        "AssignmentNode",
        "ReturnNode",
        "VariableNode",
    ]
    function_frame = result.frames[1]
    assert function_frame.context["function"] == "add_one"
    assert function_frame.context["call_depth"] == 1
    assert {
        change["name"] for change in function_frame.changes["locals"]
    } == {"value"}
    call_id = function_frame.context["call_stack"][-1]["instance_id"]
    assert {
        change["scope_id"] for change in function_frame.changes["locals"]
    } == {call_id}
    caller_frame = result.frames[3]
    assert caller_frame.context["call_depth"] == 0
    removed = [
        change
        for change in caller_frame.changes["locals"]
        if not change["after_exists"]
    ]
    assert {change["name"] for change in removed} == {"value", "local"}


def test_for_trace_revisits_header_and_identifies_one_dynamic_loop():
    result = trace_evaluate("for i from 1 to 2\ni\nend for")
    headers = [
        frame for frame in result.frames
        if frame.active is not None
        and frame.active["node_kind"] == "ForCondition"
    ]

    assert len(headers) == 3
    loop_ids = {frame.active["loop_instance_id"] for frame in headers}
    assert len(loop_ids) == 1
    assert [frame.context["loops"][-1]["iteration"] for frame in headers] == [
        0,
        1,
        2,
    ]
    loop_id = headers[0].context["loops"][-1]["instance_id"]
    body_frame = next(
        frame
        for frame in result.frames
        if frame.active is not None
        and frame.active["node_kind"] == "VariableNode"
    )
    assert body_frame.changes["locals"][0]["scope_id"] == loop_id
    assert result.frames[-1].changes["locals"][0]["after_exists"] is False


def test_while_trace_includes_final_false_condition_checkpoint():
    result = trace_evaluate("x = 2\nwhile (x)\nx = x - 1\nend while")

    assert active_kinds(result).count("WhileCondition") == 3
    assert result.frames[-1].status == "completed"


@pytest.mark.parametrize(
    "source,node_kind,flow_kind,destination_kind",
    [
        (
            "while (1)\nbreak\nend while\n99",
            "BreakNode",
            "break",
            "NumberNode",
        ),
        (
            "for i from 1 to 1\ncontinue\nend for\n99",
            "ContinueNode",
            "continue",
            "ForCondition",
        ),
        (
            "function value()\n"
            "return 42\n"
            "end function\n"
            "answer = value()\n"
            "answer",
            "ReturnNode",
            "return",
            "VariableNode",
        ),
    ],
)
def test_non_local_control_flow_links_to_observed_destination(
    source,
    node_kind,
    flow_kind,
    destination_kind,
):
    result = trace_evaluate(source)
    transfer = next(
        frame
        for frame in result.frames
        if frame.active is not None
        and frame.active["node_kind"] == node_kind
    )
    destination = result.frames[
        transfer.control_flow["destination_frame"]
    ]

    assert transfer.control_flow["kind"] == flow_kind
    assert destination.active["node_kind"] == destination_kind
    assert destination.number > transfer.number


def test_return_to_program_completion_has_explicit_terminal_destination():
    result = trace_evaluate(
        "function value()\n"
        "return 42\n"
        "end function\n"
        "value()"
    )
    transfer = next(
        frame
        for frame in result.frames
        if frame.active is not None
        and frame.active["node_kind"] == "ReturnNode"
    )
    destination = result.frames[
        transfer.control_flow["destination_frame"]
    ]

    assert destination.status == "completed"
    assert destination.active is None


def test_nested_recursive_returns_can_share_the_next_observed_destination():
    result = trace_evaluate(
        "function factorial(n)\n"
        "if (n <= 1)\n"
        "return 1\n"
        "end if\n"
        "return n * factorial(n - 1)\n"
        "end function\n"
        "factorial(5)"
    )
    returns = [
        frame
        for frame in result.frames
        if frame.active is not None
        and frame.active["node_kind"] == "ReturnNode"
    ]

    assert result.ok
    assert result.frames[-1].changes["output_values"] == [120]
    assert len(returns) == 5
    assert all(frame.control_flow is not None for frame in returns)
    assert all(
        frame.control_flow["destination_frame"] > frame.number
        for frame in returns
    )


@pytest.mark.parametrize(
    "source,node_kind,destination_kind",
    [
        (
            "while (1)\n"
            "chaos 1\n"
            "break\n"
            "end chaos\n"
            "end while\n"
            "99",
            "BreakNode",
            "NumberNode",
        ),
        (
            "for i from 1 to 1\n"
            "chaos 1\n"
            "continue\n"
            "end chaos\n"
            "end for\n"
            "99",
            "ContinueNode",
            "ForCondition",
        ),
        (
            "function value()\n"
            "chaos 1\n"
            "return 42\n"
            "end chaos\n"
            "end function\n"
            "answer = value()\n"
            "answer",
            "ReturnNode",
            "VariableNode",
        ),
    ],
)
def test_control_flow_destination_skips_required_scope_cleanup(
    source,
    node_kind,
    destination_kind,
):
    result = trace_evaluate(source)
    transfer = next(
        frame
        for frame in result.frames
        if frame.active is not None
        and frame.active["node_kind"] == node_kind
    )
    cleanup = result.frames[transfer.number + 1]
    destination = result.frames[
        transfer.control_flow["destination_frame"]
    ]

    assert cleanup.active["node_kind"] == "ChaosScopeExit"
    assert destination.active["node_kind"] == destination_kind
    assert destination.number > cleanup.number


def test_failed_return_expression_is_not_reported_as_control_transfer():
    result = trace_evaluate(
        "function value()\n"
        "return 1 / 0\n"
        "end function\n"
        "value()"
    )
    return_frame = next(
        frame
        for frame in result.frames
        if frame.active is not None
        and frame.active["node_kind"] == "ReturnNode"
    )

    assert return_frame.control_flow is None
    assert result.frames[-1].status == "error"
    assert result.frames[-1].diagnostic_index == 0


def test_runtime_failure_retains_partial_trace_and_original_base_state():
    state = RuntimeState(variables={"original": 7})
    result = trace_evaluate("temporary = 9\n1 / 0", state=state)

    assert not result.ok
    assert result.diagnostics[0].message == "Division by zero"
    assert result.base_state is state
    assert result.frames[-1].status == "error"
    assert result.frames[-1].active["span"] == (
        result.diagnostics[0].span.to_dict()
    )
    assert result.frames[1].changes["variables"][0]["name"] == "temporary"


def test_failure_inside_chaos_scope_restores_threshold_in_error_frame():
    result = trace_evaluate("chaos 99\n1 / 0\nend chaos")

    error = result.frames[-1]
    assert error.status == "error"
    assert error.changes["chaos_threshold"] == {"before": 99, "after": 1}
    assert error.changes["events"][-1]["kind"] == "chaos_scope_restored"


def test_compile_failure_has_no_execution_frames():
    result = trace_evaluate("if (1)\n1")

    assert not result.ok
    assert result.diagnostics[0].kind is DiagnosticKind.PARSE
    assert result.frames == []
    assert result.artifact_available
    assert json.loads(result.artifact_json_bytes()) == result.to_dict()


def test_runtime_diagnostic_is_stored_once_and_referenced_by_error_frame():
    result = trace_evaluate("1 / 0")
    payload = result.artifact_json_bytes()
    decoded = json.loads(payload)

    assert payload.count(b"Division by zero") == 1
    assert len(decoded["diagnostics"]) == 1
    assert decoded["frames"][-1]["diagnostic_index"] == 0
    assert "diagnostic" not in decoded["frames"][-1]


@pytest.mark.parametrize(
    "trace_limits,source,message",
    [
        (
            TraceLimits(max_frames=1),
            "1\n2",
            "Trace frame budget exceeded",
        ),
        (
            TraceLimits(max_binding_changes=1),
            "x = 1\ny = 2\n0",
            "Trace binding-change budget exceeded",
        ),
        (
            TraceLimits(max_output_values=1),
            "1\n2\n3",
            "Trace output budget exceeded",
        ),
        (
            TraceLimits(max_events=1),
            "x = 1\ny = 2\n0",
            "Trace event budget exceeded",
        ),
    ],
)
def test_trace_budgets_return_playable_limit_failures(
    trace_limits,
    source,
    message,
):
    result = trace_evaluate(source, trace_limits=trace_limits)

    assert not result.ok
    assert result.diagnostics[0].kind is DiagnosticKind.LIMIT
    assert result.diagnostics[0].message == message
    assert result.frames[-1].status == "error"
    assert result.frames[-1].truncated
    assert len(result.frames) <= trace_limits.max_frames
    assert (
        len(result.artifact_json_bytes())
        <= trace_limits.max_serialized_bytes
    )
    json.dumps(result.to_dict())


@pytest.mark.parametrize(
    "trace_limits,source,message",
    [
        (
            TraceLimits(max_binding_changes=1),
            "x = 1\ny = 2",
            "Trace binding-change budget exceeded",
        ),
        (
            TraceLimits(max_output_values=1),
            "1\n2",
            "Trace output budget exceeded",
        ),
        (
            TraceLimits(max_events=1),
            "x = 1\ny = 2",
            "Trace event budget exceeded",
        ),
    ],
)
def test_completed_terminal_cannot_bypass_change_budgets(
    trace_limits,
    source,
    message,
):
    result = trace_evaluate(source, trace_limits=trace_limits)

    assert not result.ok
    assert result.diagnostics[0].message == message
    assert result.frames[-1].status == "error"
    assert result.frames[-1].truncated


def test_serialization_budget_exactly_bounds_canonical_playback_payload():
    limits = TraceLimits(max_serialized_bytes=2_000)
    result = trace_evaluate(
        "answer = 40\nanswer = answer + 2\nanswer",
        trace_limits=limits,
    )

    payload = result.artifact_json_bytes()
    assert payload is not None
    assert len(payload) <= limits.max_serialized_bytes
    assert json.loads(payload) == result.to_dict()


def test_oversized_completed_terminal_becomes_bounded_truncation_marker():
    limits = TraceLimits(max_serialized_bytes=1_000)
    result = trace_evaluate("1", trace_limits=limits)

    assert not result.ok
    assert result.diagnostics[0].message == (
        "Trace serialization budget exceeded"
    )
    assert [(frame.status, frame.truncated) for frame in result.frames] == [
        ("error", True)
    ]
    assert len(result.artifact_json_bytes()) <= limits.max_serialized_bytes


def test_oversized_runtime_error_terminal_becomes_truncation_marker():
    limits = TraceLimits(max_serialized_bytes=810)
    result = trace_evaluate("1 / 0", trace_limits=limits)

    assert not result.ok
    assert result.diagnostics[0].message == "Division by zero"
    assert [(frame.status, frame.truncated) for frame in result.frames] == [
        ("error", True)
    ]
    assert len(result.artifact_json_bytes()) <= limits.max_serialized_bytes


def test_error_artifact_can_omit_terminal_when_only_diagnostic_fits():
    limits = TraceLimits(max_serialized_bytes=800)
    result = trace_evaluate("1 / 0", trace_limits=limits)

    assert not result.ok
    assert result.artifact_available
    assert result.frames == []
    assert len(result.artifact_json_bytes()) <= limits.max_serialized_bytes


def test_serialization_budget_can_reject_before_trace_creation():
    result = trace_evaluate(
        "1",
        trace_limits=TraceLimits(max_serialized_bytes=1),
    )

    assert not result.ok
    assert result.diagnostics[0].message == (
        "Trace serialization budget exceeded"
    )
    assert result.base_state is None
    assert result.frames == []
    assert not result.artifact_available
    assert result.artifact_json_bytes() is None


def test_serialization_budget_can_reject_compile_failure_artifact():
    result = trace_evaluate(
        "if (1)\n1",
        trace_limits=TraceLimits(max_serialized_bytes=1),
    )

    assert not result.ok
    assert result.diagnostics[0].kind is DiagnosticKind.PARSE
    assert result.base_state is None
    assert result.frames == []
    assert not result.artifact_available
    assert result.artifact_json_bytes() is None


def test_execution_limits_still_apply_during_tracing():
    result = trace_evaluate("1 + 2", limits=ExecutionLimits(max_steps=1))

    assert not result.ok
    assert result.diagnostics[0].message == "Step budget exceeded"


def test_normal_evaluation_result_is_unchanged_by_trace_infrastructure():
    source = (
        "function twice(value)\n"
        "  return value * 2\n"
        "end function\n"
        "for i from 1 to 3\n"
        "  answer = twice(i)\n"
        "  answer\n"
        "end for"
    )

    normal = evaluate(source)
    traced = trace_evaluate(source)

    assert normal.ok and traced.ok
    assert normal.values == [2, 4, 6]
    assert normal.state.variables == {"answer": 6}
