import assert from "node:assert/strict";
import test from "node:test";

import { TracePlayback } from "../../frontend/src/trace-player.js";
import type {
  TraceContext,
  TraceExecutionFrame,
} from "../../frontend/src/trace-player.js";
import { traceFrame } from "./support/trace-fixtures.js";

test("trace playback applies each checkpoint delta before presenting it", () => {
  const assigned = {
    name: "answer",
    before_exists: false,
    before: null,
    after_exists: true,
    after: 42,
  };
  const local = {
    name: "value",
    scope_id: 7,
    kind: "function",
    label: "solve",
    before_exists: false,
    before: null,
    after_exists: true,
    after: 9,
  };
  const playback = new TracePlayback({
    ok: true,
    artifact_available: true,
    session_id: "session",
    diagnostics: [],
    base_state: { chaos_threshold: 1, variables: { kept: 3 } },
    frames: [
      traceFrame(0),
      traceFrame(1, {
        chaos_threshold: { before: 1, after: 500 },
        variables: [assigned],
        locals: [local],
        output_values: [42],
        events: [{
          kind: "variable_assigned",
          data: { name: "answer", value: 42 },
          span: null,
        }],
      }),
    ],
  });

  assert.equal(playback.index, 0);
  assert.deepEqual(playback.current!.variables, { kept: 3 });
  assert.equal(playback.current!.frame.active!.span.start.line, 1);

  assert.equal(playback.stepForward(), true);
  assert.equal(playback.current!.chaosThreshold, 500);
  assert.deepEqual(playback.current!.variables, { kept: 3, answer: 42 });
  assert.deepEqual(playback.current!.locals, [{
    scopeId: 7,
    kind: "function",
    label: "solve",
    values: { value: 9 },
  }]);
  assert.deepEqual(playback.current!.outputValues, [42]);
  assert.equal(playback.current!.events.length, 1);
  assert.equal(playback.current!.frame.active!.span.start.line, 2);
});

test("trace playback reverses state, locals, output, and events", () => {
  const playback = new TracePlayback({
    ok: true,
    artifact_available: true,
    session_id: "session",
    diagnostics: [],
    base_state: { chaos_threshold: 2 },
    frames: [
      traceFrame(0, {
        chaos_threshold: { before: 2, after: 2 },
      }),
      traceFrame(1, {
        chaos_threshold: { before: 2, after: 7 },
        variables: [{
          name: "x",
          before_exists: false,
          before: null,
          after_exists: true,
          after: 1,
        }],
        locals: [{
          name: "i",
          scope_id: 4,
          kind: "for",
          label: "i",
          before_exists: false,
          before: null,
          after_exists: true,
          after: 1,
        }],
        output_values: [1],
        events: [{ kind: "chaos_changed", data: {}, span: null }],
      }),
    ],
  });

  playback.stepForward();
  assert.equal(playback.stepBack(), true);
  assert.equal(playback.current!.chaosThreshold, 2);
  assert.deepEqual(playback.current!.variables, {});
  assert.deepEqual(playback.current!.locals, []);
  assert.deepEqual(playback.current!.outputValues, []);
  assert.deepEqual(playback.current!.events, []);
  assert.equal(playback.stepBack(), false);
});

test("step over exits the innermost enclosing loop", () => {
  const outerLoop: TraceExecutionFrame = {
    instance_id: 10,
    kind: "while",
    span: null,
    iteration: 1,
  };
  const innerLoop: TraceExecutionFrame = {
    instance_id: 20,
    kind: "for",
    span: null,
    iteration: 1,
  };
  const context = (loops: TraceExecutionFrame[]): TraceContext => ({
    function: null,
    call_depth: 0,
    call_stack: [],
    call_stack_truncated: 0,
    loops,
  });
  const frames = [
    traceFrame(0),
    traceFrame(1, { output_values: [1] }, {
      context: context([outerLoop]),
    }),
    traceFrame(2, { output_values: [2] }, {
      context: context([outerLoop]),
    }),
    traceFrame(3, { output_values: [3] }, {
      context: context([outerLoop, innerLoop]),
    }),
    traceFrame(4, { output_values: [4] }, {
      context: context([outerLoop]),
    }),
    traceFrame(5, { output_values: [5] }),
  ];
  const result = {
    ok: true,
    artifact_available: true,
    session_id: "session",
    diagnostics: [],
    base_state: { chaos_threshold: 1 },
    frames,
  };

  const outerPlayback = new TracePlayback(result);
  assert.equal(outerPlayback.stepOver(), true);
  assert.equal(outerPlayback.index, 1);
  assert.equal(outerPlayback.stepOver(), true);
  assert.equal(outerPlayback.index, 5);
  assert.deepEqual(outerPlayback.current!.outputValues, [1, 2, 3, 4, 5]);

  const innerPlayback = new TracePlayback(result);
  innerPlayback.stepForward();
  innerPlayback.stepForward();
  innerPlayback.stepForward();
  assert.equal(innerPlayback.index, 3);
  assert.equal(innerPlayback.stepOver(), true);
  assert.equal(innerPlayback.index, 4);
});

test("step over skips recursive calls until the current call depth resumes", () => {
  const context = (callDepth: number): TraceContext => ({
    function: callDepth === 0 ? null : `factorial-${callDepth}`,
    call_depth: callDepth,
    call_stack: [],
    call_stack_truncated: 0,
    loops: [],
  });
  const frames = [
    traceFrame(0, {}, {
      active: {
        site_id: 1,
        node_kind: "FunctionCallNode",
        span: {
          start: { line: 1, column: 1 },
          end: { line: 1, column: 13 },
        },
        loop_instance_id: null,
      },
      context: context(0),
    }),
    traceFrame(1, { output_values: [1] }, { context: context(1) }),
    traceFrame(2, { output_values: [2] }, { context: context(2) }),
    traceFrame(3, { output_values: [3] }, { context: context(1) }),
    traceFrame(4, { output_values: [4] }, { context: context(0) }),
  ];
  const result = {
    ok: true,
    artifact_available: true,
    session_id: "session",
    diagnostics: [],
    base_state: { chaos_threshold: 1 },
    frames,
  };

  const topLevelPlayback = new TracePlayback(result);
  assert.equal(topLevelPlayback.stepOver(), true);
  assert.equal(topLevelPlayback.index, 4);
  assert.deepEqual(topLevelPlayback.current!.outputValues, [1, 2, 3, 4]);

  const recursivePlayback = new TracePlayback(result);
  recursivePlayback.stepForward();
  assert.equal(recursivePlayback.index, 1);
  assert.equal(recursivePlayback.stepOver(), true);
  assert.equal(recursivePlayback.index, 3);

  const stepOutPlayback = new TracePlayback(result);
  assert.equal(stepOutPlayback.canStepOut, false);
  assert.equal(stepOutPlayback.stepOut(), false);
  stepOutPlayback.stepForward();
  assert.equal(stepOutPlayback.canStepOut, true);
  assert.equal(stepOutPlayback.stepOut(), true);
  assert.equal(stepOutPlayback.index, 4);
});

test("trace playback validates artifact availability and frame numbering", () => {
  assert.throws(
    () => new TracePlayback({
      ok: false,
      artifact_available: false,
      session_id: "session",
      diagnostics: [],
      base_state: null,
      frames: [],
    }),
    /unavailable/,
  );
  assert.throws(
    () => new TracePlayback({
      ok: true,
      artifact_available: true,
      session_id: "session",
      diagnostics: [],
      base_state: { chaos_threshold: 1 },
      frames: [traceFrame(3)],
    }),
    /contiguous/,
  );
});
