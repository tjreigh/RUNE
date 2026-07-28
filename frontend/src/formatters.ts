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
  if (event.kind === "chaos_scope_entered") {
    return [
      "Entered chaos scope:",
      `${event.data.previous_threshold} → ${event.data.threshold}`,
    ].join(" ");
  }
  if (event.kind === "chaos_scope_restored") {
    return [
      "Restored chaos scope:",
      `${event.data.previous_threshold} → ${event.data.threshold}`,
    ].join(" ");
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

function formatVariables(variables: Record<string, number>): string[] {
  const entries = Object.entries(variables)
    .sort(([left], [right]) => left.localeCompare(right));
  return entries.length === 0
    ? ["Variables: (none)"]
    : ["Variables:", ...entries.map(([name, value]) => `  ${name} = ${value}`)];
}

export function formatTraceState(snapshot: TracePlaybackSnapshot): string {
  const localLines = snapshot.locals.length === 0
    ? ["Locals: (none)"]
    : [
      "Locals:",
      ...snapshot.locals.flatMap((scope) => {
        const label = scope.label === null ? "" : ` ${scope.label}`;
        const kind = scope.kind ?? "scope";
        const scopeId = scope.scopeId === null ? "" : ` #${scope.scopeId}`;
        const bindings = Object.entries(scope.values)
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([name, value]) => `    ${name} = ${value}`);
        return [`  ${kind}${label}${scopeId}:`, ...bindings];
      }),
    ];
  return [
    `Chaos threshold: ${snapshot.chaosThreshold}`,
    ...formatVariables(snapshot.variables),
    ...localLines,
  ].join("\n");
}

function formatExecutionFrame(frame: TraceExecutionFrame): string {
  if (frame.kind === "function") {
    return `${frame.name ?? "(anonymous)"} #${frame.instance_id}`;
  }
  if (frame.kind === "for") {
    const iteration = frame.iteration ?? 0;
    return `for ${frame.counter ?? "?"} #${frame.instance_id}, iteration ${iteration}`;
  }
  if (frame.kind === "while") {
    return `while #${frame.instance_id}, iteration ${frame.iteration ?? 0}`;
  }
  return [
    `chaos #${frame.instance_id}`,
    `${frame.previous_chaos_threshold ?? "?"}`,
    "→",
    `${frame.entered_chaos_threshold ?? "?"}`,
  ].join(" ");
}

export function formatTraceContext(
  snapshot: TracePlaybackSnapshot,
): string {
  const { frame } = snapshot;
  const activeLine = frame.active === null
    ? "Next statement: (none)"
    : [
      `Next statement: ${frame.active.node_kind}`,
      `at line ${frame.active.span.start.line}`,
    ].join(" ");
  const callStack = frame.context.call_stack.length === 0
    ? ["Call stack: (top level)"]
    : [
      "Call stack:",
      ...frame.context.call_stack.map(
        (entry, index) => `  ${index + 1}. ${formatExecutionFrame(entry)}`,
      ),
    ];
  if (frame.context.call_stack_truncated > 0) {
    callStack.splice(
      1,
      0,
      `  … ${frame.context.call_stack_truncated} frame(s) omitted`,
    );
  }
  const loops = frame.context.loops.length === 0
    ? ["Loops: (none)"]
    : [
      "Loops:",
      ...frame.context.loops.map((entry) => `  ${formatExecutionFrame(entry)}`),
    ];
  const controlFlow = frame.control_flow === undefined
    ? []
    : [
      `Control flow: ${frame.control_flow.kind} → frame ${
        frame.control_flow.destination_frame + 1
      }`,
    ];
  return [
    `Frame: ${snapshot.frameIndex + 1} of ${snapshot.frameCount}`,
    `Status: ${frame.status}${frame.truncated === true ? " (truncated)" : ""}`,
    activeLine,
    `Function: ${frame.context.function ?? "(top level)"}`,
    `Call depth: ${frame.context.call_depth}`,
    ...callStack,
    ...loops,
    ...controlFlow,
  ].join("\n");
}

function formatRemaining(label: string, value: number | null): string {
  return `${label}: ${value === null ? "unbounded" : value}`;
}

export function formatTraceStats(frame: TraceFrame): string {
  if (frame.truncated === true) {
    return [
      formatStats(frame.stats, true),
      "",
      "Remaining budgets: unavailable (trace was truncated).",
    ].join("\n");
  }
  return [
    formatStats(frame.stats, true),
    "",
    "Remaining budgets:",
    formatRemaining("  Steps", frame.budgets.steps),
    formatRemaining("  Output values", frame.budgets.output_values),
    formatRemaining("  Runtime events", frame.budgets.runtime_events),
    formatRemaining("  Trace frames", frame.budgets.trace_frames),
    formatRemaining("  Trace bytes", frame.budgets.trace_bytes),
  ].join("\n");
}
import type {
  TraceExecutionFrame,
  TraceFrame,
  TracePlaybackSnapshot,
} from "./trace-player.js";
