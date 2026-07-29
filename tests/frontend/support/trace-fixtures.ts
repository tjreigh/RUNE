import type {
  TraceChanges,
  TraceFrame,
} from "../../../frontend/src/trace-player.js";

export function traceFrame(
  number: number,
  changes: Partial<TraceChanges> = {},
  overrides: Partial<TraceFrame> = {},
): TraceFrame {
  return {
    active: {
      site_id: number + 1,
      node_kind: "AssignmentNode",
      span: {
        start: { line: number + 1, column: 1 },
        end: { line: number + 1, column: 2 },
      },
      loop_instance_id: null,
    },
    budgets: {
      steps: 100 - number,
      output_values: 100,
      runtime_events: 100,
      trace_frames: 100 - number,
      trace_bytes: 10_000,
    },
    changes: {
      chaos_threshold: { before: 1, after: 1 },
      variables: [],
      locals: [],
      output_values: [],
      events: [],
      ...changes,
    },
    context: {
      function: null,
      call_depth: 0,
      call_stack: [],
      call_stack_truncated: 0,
      loops: [],
    },
    number,
    stats: {
      steps: number + 1,
      peak_recursion_depth: 1,
      output_values: 0,
      runtime_events: 0,
      loop_iterations: 0,
    },
    status: "paused",
    ...overrides,
  };
}
