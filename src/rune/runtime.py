from dataclasses import dataclass
from typing import Any

from .lexer import Lexer
from .parser import Parser
from .interpreter import Interpreter
from .diagnostics import RuneError
from .runtime_state import RuntimeState, RuntimeEvent
from .limits import ExecutionLimits, ExecutionStats, TraceLimits
from .tracing import TraceRecorder, TraceFrame, TraceResult

__all__ = [
    "RuntimeState",
    "RuntimeEvent",
    "ExecutionLimits",
    "ExecutionStats",
    "TraceLimits",
    "TraceFrame",
    "TraceResult",
    "CompiledProgram",
    "EvaluationResult",
    "compile_source",
    "execute",
    "evaluate",
    "trace_execute",
    "trace_evaluate",
]


@dataclass
class CompiledProgram:
    """Lexed tokens and parsed AST for a source string. Not serialized."""
    tokens: list
    ast: Any


@dataclass
class EvaluationResult:
    values: list
    diagnostics: list
    events: list
    state: RuntimeState
    stats: ExecutionStats | None = None

    @property
    def ok(self):
        return not self.diagnostics

    def to_dict(self):
        return {
            "ok": self.ok,
            "values": self.values,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "events": [e.to_dict() for e in self.events],
            "state": self.state.to_dict(),
            "stats": self.stats.to_dict() if self.stats is not None else None,
        }


def compile_source(source: str) -> CompiledProgram:
    """Lex and parse source. Raises RuneError subclasses on failure."""
    tokens = Lexer(source).tokenize()
    ast = Parser(tokens).parse()
    return CompiledProgram(tokens=tokens, ast=ast)


def _normalize_values(raw) -> list:
    if isinstance(raw, list):
        return raw
    if raw is None:
        return []
    return [raw]


def execute(
    program: CompiledProgram,
    state: RuntimeState | None = None,
    limits: ExecutionLimits | None = None,
) -> EvaluationResult:
    """Execute a compiled program against the given state (or a fresh
    default). Never mutates the caller's state; a failed execution
    (including one that exceeds an execution limit) returns the exact
    state it was given, no partial values, and the stats recorded before
    termination."""
    base_state = state if state is not None else RuntimeState()
    interpreter = Interpreter(state=base_state, limits=limits)
    try:
        raw = interpreter.interpret(program.ast)
    except RuneError as e:
        return EvaluationResult(
            values=[],
            diagnostics=[e.diagnostic],
            events=[],
            state=base_state,
            stats=interpreter.stats,
        )
    return EvaluationResult(
        values=_normalize_values(raw),
        diagnostics=[],
        events=interpreter.events,
        state=interpreter.state,
        stats=interpreter.stats,
    )


def evaluate(
    source: str,
    state: RuntimeState | None = None,
    limits: ExecutionLimits | None = None,
) -> EvaluationResult:
    """Convenience wrapper around compile_source() + execute(). Converts
    known RuneError failures (including compilation failures) into result
    diagnostics; unexpected Python exceptions still propagate so interpreter
    bugs are not disguised as user errors."""
    base_state = state if state is not None else RuntimeState()
    try:
        program = compile_source(source)
    except RuneError as e:
        return EvaluationResult(
            values=[],
            diagnostics=[e.diagnostic],
            events=[],
            state=base_state,
            stats=None,
        )
    return execute(program, state=base_state, limits=limits)


def trace_execute(
    program: CompiledProgram,
    state: RuntimeState | None = None,
    limits: ExecutionLimits | None = None,
    trace_limits: TraceLimits | None = None,
) -> TraceResult:
    """Execute once while recording bounded, non-committing checkpoints."""
    base_state = state if state is not None else RuntimeState()
    try:
        recorder = TraceRecorder(base_state, limits=trace_limits)
    except RuneError as exc:
        return TraceResult(
            diagnostics=[exc.diagnostic],
            base_state=None,
            frames=[],
            artifact_available=False,
        )
    interpreter = Interpreter(
        state=base_state,
        limits=limits,
        trace_recorder=recorder,
    )
    try:
        interpreter.interpret(program.ast)
        # Closing the trace can exceed a recorder budget even after the
        # program completes; deliberately report that through this error path.
        recorder.finish_success(interpreter)
    except RuneError as exc:
        recorder.finish_error(interpreter, exc)
        return TraceResult(
            diagnostics=recorder.diagnostics,
            base_state=(
                base_state if recorder.artifact_available else None
            ),
            frames=recorder.frames if recorder.artifact_available else [],
            artifact_available=recorder.artifact_available,
        )
    return TraceResult(
        diagnostics=[],
        base_state=base_state,
        frames=recorder.frames,
        artifact_available=recorder.artifact_available,
    )


def trace_evaluate(
    source: str,
    state: RuntimeState | None = None,
    limits: ExecutionLimits | None = None,
    trace_limits: TraceLimits | None = None,
) -> TraceResult:
    """Compile and record one bounded execution trace."""
    base_state = state if state is not None else RuntimeState()
    try:
        program = compile_source(source)
    except RuneError as exc:
        result = TraceResult(
            diagnostics=[exc.diagnostic],
            base_state=base_state,
            frames=[],
            artifact_available=True,
        )
        active_limits = (
            trace_limits if trace_limits is not None else TraceLimits()
        )
        if (
            len(result.artifact_json_bytes())
            > active_limits.max_serialized_bytes
        ):
            result.base_state = None
            result.artifact_available = False
        return result
    return trace_execute(
        program,
        state=base_state,
        limits=limits,
        trace_limits=trace_limits,
    )
