export interface SourcePosition {
  line: number;
  column: number;
}

export interface SourceSpan {
  start: SourcePosition;
  end: SourcePosition;
}

export interface Diagnostic {
  kind: string;
  message: string;
  span: SourceSpan | null;
}

export interface RuntimeState {
  chaos_threshold: number;
  variables?: Record<string, number>;
}

export interface RuntimeEvent {
  kind: string;
  data: Record<string, unknown>;
  span: SourceSpan | null;
}

export interface ExecutionStats {
  steps: number;
  peak_recursion_depth: number;
  output_values: number;
  runtime_events: number;
  loop_iterations: number;
}

const KIND_LABELS: Record<string, string> = {
  lex: "Lex error",
  parse: "Parse error",
  runtime: "Runtime error",
  internal: "Internal error",
  limit: "Execution limit",
};

export function formatDiagnostic(diagnostic: Diagnostic): string {
  const label = KIND_LABELS[diagnostic.kind] || diagnostic.kind;
  if (diagnostic.span) {
    const { line, column } = diagnostic.span.start;
    return `${label}: line ${line}, col ${column}: ${diagnostic.message}`;
  }
  return `${label}: ${diagnostic.message}`;
}

export function formatRequestDetail(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map((issue) => {
      if (issue === null || typeof issue !== "object") {
        return String(issue);
      }
      const locationValue = "loc" in issue ? issue.loc : null;
      const location = Array.isArray(locationValue)
        ? locationValue.filter((part) => part !== "body").join(".")
        : "";
      const message = "msg" in issue
        ? String(issue.msg)
        : (JSON.stringify(issue) ?? String(issue));
      return location ? `${location}: ${message}` : message;
    }).join("; ");
  }
  return JSON.stringify(detail) ?? String(detail);
}

export function formatState(state: RuntimeState | null): string {
  const threshold = state?.chaos_threshold ?? 1;
  const variables = Object.entries(state?.variables ?? {})
    .sort(([left], [right]) => left.localeCompare(right));
  const variableLines = variables.length === 0
    ? ["Variables: (none)"]
    : ["Variables:", ...variables.map(([name, value]) => `  ${name} = ${value}`)];
  return [`Chaos threshold: ${threshold}`, ...variableLines].join("\n");
}

export function formatEvent(event: RuntimeEvent): string {
  if (event.kind === "variable_assigned") {
    return `${event.data.name} = ${event.data.value}`;
  }
  if (event.kind === "chaos_threshold_changed") {
    return `Chaos threshold = ${event.data.threshold}`;
  }
  return `${event.kind}: ${JSON.stringify(event.data)}`;
}

export function formatStats(
  stats: ExecutionStats | null,
  evaluated: boolean,
): string {
  if (stats === null) {
    return evaluated
      ? "Not available (evaluation did not begin)."
      : "No evaluation yet.";
  }
  return [
    `Steps: ${stats.steps}`,
    `Peak recursion depth: ${stats.peak_recursion_depth}`,
    `Output values: ${stats.output_values}`,
    `Runtime events: ${stats.runtime_events}`,
    `Loop iterations: ${stats.loop_iterations}`,
  ].join("\n");
}
