from dataclasses import dataclass
from typing import Any, Optional

from lexer import Lexer
from parser import Parser
from interpreter import Interpreter
from diagnostics import RuneError
from runtime_state import RuntimeState, RuntimeEvent

__all__ = [
    "RuntimeState",
    "RuntimeEvent",
    "CompiledProgram",
    "EvaluationResult",
    "compile_source",
    "execute",
    "evaluate",
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
    state: Optional[RuntimeState] = None,
) -> EvaluationResult:
    """Execute a compiled program against the given state (or a fresh
    default). Never mutates the caller's state; a failed execution returns
    the exact state it was given."""
    base_state = state if state is not None else RuntimeState()
    interpreter = Interpreter(state=base_state)
    try:
        raw = interpreter.interpret(program.ast)
    except RuneError as e:
        return EvaluationResult(
            values=[],
            diagnostics=[e.diagnostic],
            events=[],
            state=base_state,
        )
    return EvaluationResult(
        values=_normalize_values(raw),
        diagnostics=[],
        events=interpreter.events,
        state=interpreter.state,
    )


def evaluate(
    source: str,
    state: Optional[RuntimeState] = None,
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
        )
    return execute(program, state=base_state)
