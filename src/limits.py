from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionLimits:
    """Deterministic interpreter execution bounds checked during a single
    evaluation. Wall-clock termination is a separate, future concern."""
    max_steps: int = 10_000
    max_recursion_depth: int = 100
    max_output_values: int = 1_000
    max_variables: int = 256

    def __post_init__(self):
        if self.max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if self.max_recursion_depth < 1:
            raise ValueError("max_recursion_depth must be at least 1")
        if self.max_output_values < 1:
            raise ValueError("max_output_values must be at least 1")
        if self.max_variables < 1:
            raise ValueError("max_variables must be at least 1")


@dataclass(frozen=True)
class ExecutionStats:
    """Work performed by a single evaluation, recorded even when it fails
    a limit so callers can see how far execution got."""
    steps: int
    peak_recursion_depth: int
    output_values: int

    def to_dict(self):
        return {
            "steps": self.steps,
            "peak_recursion_depth": self.peak_recursion_depth,
            "output_values": self.output_values,
        }
