"""Deterministic execution budgets and statistics."""

from dataclasses import dataclass


DEFAULT_MAX_INTEGER_BITS = 14_285


@dataclass(frozen=True)
class ExecutionLimits:
    """Deterministic interpreter execution bounds checked during a single
    evaluation. ``None`` disables one interpreter-level ceiling; wall-clock,
    parser, and process-memory containment are separate."""
    max_steps: int | None = 10_000
    max_recursion_depth: int | None = 100
    max_output_values: int | None = 1_000
    max_variables: int | None = 256
    max_integer_bits: int | None = DEFAULT_MAX_INTEGER_BITS
    max_events: int | None = 1_000

    def __post_init__(self):
        for name in (
            "max_steps",
            "max_recursion_depth",
            "max_output_values",
            "max_events",
            "max_variables",
            "max_integer_bits",
        ):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(f"{name} must be at least 1 or None")

    @classmethod
    def unbounded(cls):
        """Disable every interpreter budget for explicit trusted execution."""
        return cls(
            max_steps=None,
            max_recursion_depth=None,
            max_output_values=None,
            max_variables=None,
            max_integer_bits=None,
            max_events=None,
        )

    @property
    def is_unbounded(self):
        """Whether every interpreter budget is disabled."""
        return all(
            value is None
            for value in (
                self.max_steps,
                self.max_recursion_depth,
                self.max_output_values,
                self.max_variables,
                self.max_integer_bits,
                self.max_events,
            )
        )


@dataclass(frozen=True)
class ExecutionStats:
    """Work performed by a single evaluation, recorded even when it fails
    a limit so callers can see how far execution got."""
    steps: int
    peak_recursion_depth: int
    output_values: int
    runtime_events: int = 0
    loop_iterations: int = 0

    def to_dict(self):
        return {
            "steps": self.steps,
            "peak_recursion_depth": self.peak_recursion_depth,
            "output_values": self.output_values,
            "runtime_events": self.runtime_events,
            "loop_iterations": self.loop_iterations,
        }
