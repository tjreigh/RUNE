from dataclasses import dataclass
from collections.abc import Mapping

from spans import SourceSpan


@dataclass(frozen=True, init=False)
class RuntimeState:
    """Immutable, serializable interpreter state threaded between runs.

    Variables are normalized to a sorted tuple internally so a caller cannot
    mutate committed state through a retained dictionary reference.
    """
    chaos_threshold: int
    _variables: tuple[tuple[str, int], ...]

    def __init__(self, chaos_threshold: int = 1, variables=None):
        if variables is None:
            items = ()
        elif isinstance(variables, Mapping):
            items = variables.items()
        else:
            items = variables
        normalized = tuple(sorted(items))
        if len({name for name, _ in normalized}) != len(normalized):
            raise ValueError("variable names must be unique")
        for name, value in normalized:
            if not isinstance(name, str) or not name:
                raise ValueError("variable names must be non-empty strings")
            if not isinstance(value, int):
                raise ValueError("variable values must be integers")
        object.__setattr__(self, "chaos_threshold", chaos_threshold)
        object.__setattr__(self, "_variables", normalized)

    @property
    def variables(self):
        """Return a detached mapping of variable names to numeric values."""
        return dict(self._variables)

    def with_chaos_threshold(self, threshold: int):
        return RuntimeState(threshold, self._variables)

    def with_variable(self, name: str, value: int):
        variables = self.variables
        variables[name] = value
        return RuntimeState(self.chaos_threshold, variables)

    def to_dict(self):
        result = {"chaos_threshold": self.chaos_threshold}
        if self._variables:
            result["variables"] = self.variables
        return result


@dataclass(frozen=True)
class RuntimeEvent:
    """A structured record of an interpreter side effect (e.g. a pragma),
    so callers can format it (--verbose) without the interpreter printing."""
    kind: str
    data: dict
    span: SourceSpan | None = None

    def to_dict(self):
        return {
            "kind": self.kind,
            "data": self.data,
            "span": self.span.to_dict() if self.span is not None else None,
        }
