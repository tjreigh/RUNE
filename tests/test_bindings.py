import pytest

from bindings import BindingEnvironment
from diagnostics import RuneLimitError, RuneRuntimeError
from interpreter import Interpreter
from lexer import Lexer
from limits import ExecutionLimits
from parser import Parser
from runtime_state import RuntimeState


def _parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def test_nearest_frame_shadows_root_and_outer_frames():
    bindings = BindingEnvironment()
    root = {"value": 1}

    with bindings.frame({"value": 2}):
        assert bindings.resolve("value", root) == 2
        with bindings.frame({"value": 3}):
            assert bindings.resolve("value", root) == 3
        assert bindings.resolve("value", root) == 2

    assert bindings.resolve("value", root) == 1


def test_non_capturing_frame_only_owns_declared_bindings():
    bindings = BindingEnvironment()

    with bindings.frame({"counter": 1}):
        assert bindings.assignment_target("counter") is not None
        assert bindings.assignment_target("other") is None


def test_capturing_frame_accepts_new_assignments():
    bindings = BindingEnvironment()

    with bindings.frame(captures_assignments=True) as frame:
        assert bindings.assignment_target("local") is frame


def test_interpreter_assigns_to_nearest_local_and_restores_global():
    interpreter = Interpreter(state=RuntimeState(variables={"counter": 99}))

    with interpreter._binding_scope({"counter": 1}):
        interpreter.visit(_parse("counter = 2"))
        assert interpreter.visit(_parse("counter")) == 2
        assert interpreter.state.variables == {"counter": 99}

    assert interpreter.visit(_parse("counter")) == 99


def test_capturing_scope_keeps_new_assignment_ephemeral():
    interpreter = Interpreter()

    with interpreter._binding_scope(captures_assignments=True):
        interpreter.visit(_parse("local = 42"))
        assert interpreter.visit(_parse("local")) == 42

    with pytest.raises(RuneRuntimeError) as exc_info:
        interpreter.visit(_parse("local"))
    assert "Undefined variable 'local'" in str(exc_info.value)


def test_ephemeral_bindings_count_against_variable_budget():
    interpreter = Interpreter(
        state=RuntimeState(variables={"global": 1}),
        limits=ExecutionLimits(max_variables=1),
    )

    with pytest.raises(RuneLimitError, match="Variable budget exceeded"):
        with interpreter._binding_scope({"counter": 1}):
            pass


def test_binding_frame_is_removed_when_execution_raises():
    interpreter = Interpreter()

    with pytest.raises(RuntimeError):
        with interpreter._binding_scope({"counter": 1}):
            raise RuntimeError("boom")

    assert interpreter._bindings.depth == 0
