import type {
  Diagnostic,
  ExecutionStats,
  RuntimeEvent,
  RuntimeState,
  SourceSpan,
} from "./formatters.js";

export type TraceFrameStatus = "paused" | "completed" | "error";
export type TraceControlFlowKind = "break" | "continue" | "return";

export interface TraceActive {
  site_id: number | null;
  node_kind: string;
  span: SourceSpan;
  loop_instance_id: number | null;
}

export interface TraceBindingChange {
  name: string;
  before_exists: boolean;
  before: number | null;
  after_exists: boolean;
  after: number | null;
  scope_id?: number | null;
  kind?: string;
  label?: string | null;
}

export interface TraceChanges {
  chaos_threshold: {
    before: number;
    after: number;
  } | null;
  variables: TraceBindingChange[];
  locals: TraceBindingChange[];
  output_values: number[];
  events: RuntimeEvent[];
}

export interface TraceExecutionFrame {
  instance_id: number;
  kind: "function" | "while" | "for" | "chaos";
  span: SourceSpan | null;
  name?: string;
  counter?: string;
  iteration?: number;
  previous_chaos_threshold?: number;
  entered_chaos_threshold?: number;
}

export interface TraceContext {
  function: string | null;
  call_depth: number;
  call_stack: TraceExecutionFrame[];
  call_stack_truncated: number;
  loops: TraceExecutionFrame[];
}

export interface TraceBudgets {
  steps: number | null;
  output_values: number | null;
  runtime_events: number | null;
  trace_frames: number;
  trace_bytes: number;
}

export interface TraceControlFlow {
  kind: TraceControlFlowKind;
  destination_frame: number;
}

export interface TraceFrame {
  number: number;
  status: TraceFrameStatus;
  active: TraceActive | null;
  changes: TraceChanges;
  context: TraceContext;
  stats: ExecutionStats;
  budgets: TraceBudgets;
  diagnostic_index?: number;
  truncated?: boolean;
  control_flow?: TraceControlFlow;
}

export interface TraceResult {
  ok: boolean;
  artifact_available: boolean;
  session_id: string;
  diagnostics: Diagnostic[];
  base_state: RuntimeState | null;
  frames: TraceFrame[];
}

export interface TraceLocalScope {
  scopeId: number | null;
  kind: string | null;
  label: string | null;
  values: Record<string, number>;
}

export interface TracePlaybackSnapshot {
  frameIndex: number;
  frameCount: number;
  frame: TraceFrame;
  chaosThreshold: number;
  variables: Record<string, number>;
  locals: TraceLocalScope[];
  outputValues: number[];
  events: RuntimeEvent[];
}

interface MutableLocalScope {
  scopeId: number | null;
  kind: string | null;
  label: string | null;
  values: Record<string, number>;
}

function requiredChangeValue(
  change: TraceBindingChange,
  direction: "before" | "after",
): number {
  const value = change[direction];
  if (value === null) {
    throw new Error(
      `Trace ${direction} value is missing for ${change.name}`,
    );
  }
  return value;
}

function localScopeKey(change: TraceBindingChange): string {
  return change.scope_id === undefined || change.scope_id === null
    ? "unknown"
    : String(change.scope_id);
}

/**
 * Replays bounded trace deltas without mutating the trace artifact.
 *
 * A selected frame describes state before its active statement. Moving to the
 * next frame applies that next frame's changes; moving back reverses the frame
 * being left. This is the same pre-execution checkpoint convention used by the
 * recorder.
 */
export class TracePlayback {
  readonly result: TraceResult;

  private frameIndex = -1;
  private chaosThreshold: number;
  private readonly variables: Record<string, number>;
  private readonly locals = new Map<string, MutableLocalScope>();
  private readonly outputValues: number[] = [];
  private readonly events: RuntimeEvent[] = [];

  constructor(result: TraceResult) {
    if (!result.artifact_available || result.base_state === null) {
      throw new Error("Trace artifact is unavailable");
    }
    result.frames.forEach((frame, index) => {
      if (frame.number !== index) {
        throw new Error("Trace frame numbers must be contiguous");
      }
    });

    this.result = result;
    this.chaosThreshold = result.base_state.chaos_threshold;
    this.variables = { ...(result.base_state.variables ?? {}) };
    this.stepForward();
  }

  get length(): number {
    return this.result.frames.length;
  }

  get index(): number {
    return this.frameIndex;
  }

  get canStepBack(): boolean {
    return this.frameIndex > 0;
  }

  get canStepForward(): boolean {
    return this.frameIndex + 1 < this.result.frames.length;
  }

  get canStepOut(): boolean {
    const currentFrame = this.result.frames[this.frameIndex];
    return (
      this.canStepForward
      && (currentFrame?.context.call_depth ?? 0) > 0
    );
  }

  get current(): TracePlaybackSnapshot | null {
    const frame = this.result.frames[this.frameIndex];
    if (frame === undefined) {
      return null;
    }
    return {
      frameIndex: this.frameIndex,
      frameCount: this.result.frames.length,
      frame,
      chaosThreshold: this.chaosThreshold,
      variables: { ...this.variables },
      locals: Array.from(this.locals.values(), (scope) => ({
        scopeId: scope.scopeId,
        kind: scope.kind,
        label: scope.label,
        values: { ...scope.values },
      })),
      outputValues: [...this.outputValues],
      events: [...this.events],
    };
  }

  stepForward(): boolean {
    const nextFrame = this.result.frames[this.frameIndex + 1];
    if (nextFrame === undefined) {
      return false;
    }
    this.applyChanges(nextFrame.changes, "forward");
    ++this.frameIndex;
    return true;
  }

  /**
   * Advances over the current loop or nested function calls.
   *
   * Inside a loop, this retains the loop-aware behavior of advancing to the
   * first frame outside the innermost enclosing loop. Otherwise it advances at
   * least once, then skips frames at a deeper call depth.
   */
  stepOver(): boolean {
    const currentFrame = this.result.frames[this.frameIndex];
    const loop = currentFrame?.context.loops.at(-1);
    if (loop === undefined) {
      const callDepth = currentFrame?.context.call_depth ?? 0;
      if (!this.stepForward()) {
        return false;
      }
      while (
        this.canStepForward
        && (
          this.result.frames[this.frameIndex]?.context.call_depth
            ?? callDepth
        ) > callDepth
      ) {
        this.stepForward();
      }
      return true;
    }

    let advanced = false;
    while (this.stepForward()) {
      advanced = true;
      const nextFrame = this.result.frames[this.frameIndex];
      const stillInsideLoop = nextFrame?.context.loops.some(
        (candidate) => candidate.instance_id === loop.instance_id,
      ) ?? false;
      if (!stillInsideLoop) {
        break;
      }
    }
    return advanced;
  }

  /** Advances until execution returns from the current function invocation. */
  stepOut(): boolean {
    const callDepth = this.result.frames[this.frameIndex]?.context.call_depth
      ?? 0;
    if (callDepth === 0) {
      return false;
    }

    let advanced = false;
    while (this.stepForward()) {
      advanced = true;
      const nextCallDepth = this.result.frames[this.frameIndex]?.context.call_depth
        ?? 0;
      if (nextCallDepth < callDepth) {
        break;
      }
    }
    return advanced;
  }

  stepBack(): boolean {
    const currentFrame = this.result.frames[this.frameIndex];
    if (currentFrame === undefined || this.frameIndex === 0) {
      return false;
    }
    this.applyChanges(currentFrame.changes, "backward");
    --this.frameIndex;
    return true;
  }

  /** Rewinds the recorded execution to its first frame. */
  restart(): boolean {
    let rewound = false;
    while (this.stepBack()) {
      rewound = true;
    }
    return rewound;
  }

  diagnosticForCurrentFrame(): Diagnostic | null {
    const diagnosticIndex = this.current?.frame.diagnostic_index;
    if (diagnosticIndex === undefined) {
      return null;
    }
    return this.result.diagnostics[diagnosticIndex] ?? null;
  }

  private applyChanges(
    changes: TraceChanges,
    direction: "forward" | "backward",
  ): void {
    if (changes.chaos_threshold !== null) {
      this.chaosThreshold = changes.chaos_threshold[
        direction === "forward" ? "after" : "before"
      ];
    }

    for (const change of changes.variables) {
      this.applyBindingChange(this.variables, change, direction);
    }
    for (const change of changes.locals) {
      this.applyLocalChange(change, direction);
    }

    if (direction === "forward") {
      this.outputValues.push(...changes.output_values);
      this.events.push(...changes.events);
    } else {
      this.outputValues.splice(
        Math.max(0, this.outputValues.length - changes.output_values.length),
      );
      this.events.splice(
        Math.max(0, this.events.length - changes.events.length),
      );
    }
  }

  private applyBindingChange(
    target: Record<string, number>,
    change: TraceBindingChange,
    direction: "forward" | "backward",
  ): void {
    const exists = direction === "forward"
      ? change.after_exists
      : change.before_exists;
    if (!exists) {
      delete target[change.name];
      return;
    }
    target[change.name] = requiredChangeValue(
      change,
      direction === "forward" ? "after" : "before",
    );
  }

  private applyLocalChange(
    change: TraceBindingChange,
    direction: "forward" | "backward",
  ): void {
    const key = localScopeKey(change);
    const exists = direction === "forward"
      ? change.after_exists
      : change.before_exists;
    let scope = this.locals.get(key);

    if (exists) {
      if (scope === undefined) {
        scope = {
          scopeId: change.scope_id ?? null,
          kind: change.kind ?? null,
          label: change.label ?? null,
          values: {},
        };
        this.locals.set(key, scope);
      }
      scope.values[change.name] = requiredChangeValue(
        change,
        direction === "forward" ? "after" : "before",
      );
      return;
    }

    if (scope === undefined) {
      return;
    }
    delete scope.values[change.name];
    if (Object.keys(scope.values).length === 0) {
      this.locals.delete(key);
    }
  }
}
