import pytest

from rune.execution_context import ExecutionContext, ExecutionFrameKind


def test_dynamic_frames_receive_monotonic_ids_and_unwind():
    context = ExecutionContext()

    with context.frame(
        ExecutionFrameKind.FUNCTION,
        name="outer",
    ) as outer:
        with context.frame(ExecutionFrameKind.WHILE) as loop:
            assert outer.instance_id == 1
            assert loop.instance_id == 2
            assert context.depth == 2
            assert context.active_function is outer
            assert context.active_loop is loop

    assert context.depth == 0
    assert context.active_function is None
    assert context.active_loop is None

    with context.frame(ExecutionFrameKind.CHAOS) as later:
        assert later.instance_id == 3


def test_function_frame_is_a_barrier_for_caller_loop_control():
    context = ExecutionContext()

    with context.frame(ExecutionFrameKind.WHILE) as caller_loop:
        assert context.active_loop is caller_loop
        with context.frame(
            ExecutionFrameKind.FUNCTION,
            name="called",
        ) as function:
            assert context.active_function is function
            assert context.active_loop is None
            with context.frame(ExecutionFrameKind.CHAOS):
                assert context.active_loop is None
                with context.frame(ExecutionFrameKind.FOR) as local_loop:
                    assert context.active_loop is local_loop
        assert context.active_loop is caller_loop


def test_loop_iteration_is_owned_by_active_execution_frame():
    context = ExecutionContext()

    with context.frame(ExecutionFrameKind.FOR, counter="i") as loop:
        context.begin_loop_iteration(loop)
        context.begin_loop_iteration(loop)
        assert loop.iteration == 2
        assert context.snapshot() == [
            {
                "instance_id": 1,
                "kind": "for",
                "span": None,
                "counter": "i",
                "iteration": 2,
            }
        ]

    with pytest.raises(RuntimeError, match="inactive non-loop"):
        context.begin_loop_iteration(loop)


def test_chaos_frame_owns_restoration_metadata():
    context = ExecutionContext()

    with context.frame(
        ExecutionFrameKind.CHAOS,
        previous_chaos_threshold=7,
        entered_chaos_threshold=99,
    ) as chaos:
        assert context.active_chaos is chaos
        assert context.snapshot()[0] == {
            "instance_id": 1,
            "kind": "chaos",
            "span": None,
            "previous_chaos_threshold": 7,
            "entered_chaos_threshold": 99,
        }

    assert context.active_chaos is None
