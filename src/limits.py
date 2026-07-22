from dataclasses import dataclass


DEFAULT_MAX_INTEGER_BITS = 14_285


@dataclass(frozen=True)
class ExecutionLimits:
    """Deterministic interpreter execution bounds checked during a single
    evaluation. Wall-clock and process-memory containment are separate."""
    max_steps: int = 10_000
    max_recursion_depth: int = 100
    max_output_values: int = 1_000
    max_variables: int = 256
    max_integer_bits: int = DEFAULT_MAX_INTEGER_BITS
    max_events: int = 1_000

    def __post_init__(self):
        if self.max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if self.max_recursion_depth < 1:
            raise ValueError("max_recursion_depth must be at least 1")
        if self.max_output_values < 1:
            raise ValueError("max_output_values must be at least 1")
        if self.max_events < 1:
            raise ValueError("max_events must be at least 1")
        if self.max_variables < 1:
            raise ValueError("max_variables must be at least 1")
        if self.max_integer_bits < 1:
            raise ValueError("max_integer_bits must be at least 1")


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
