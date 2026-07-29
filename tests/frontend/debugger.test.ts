import assert from "node:assert/strict";
import test from "node:test";

import { formatTraceStats } from "../../frontend/src/formatters.js";
import type {
  TraceContext,
  TraceExecutionFrame,
} from "../../frontend/src/trace-player.js";
import {
  deferred,
  flushAsync,
  loadApp,
  response,
} from "./support/fake-browser.js";
import type { RecordedRequest } from "./support/fake-browser.js";
import { traceFrame } from "./support/trace-fixtures.js";

test("truncated terminal frames do not present placeholder budgets as exhausted", () => {
  const formatted = formatTraceStats(traceFrame(3, {}, {
    status: "error",
    truncated: true,
  }));

  assert.match(formatted, /Steps: 4/);
  assert.match(formatted, /Remaining budgets: unavailable/);
  assert.doesNotMatch(formatted, /Remaining budgets:\n\s+Steps: 0/);
});

test("debug trace controls replay state without replacing committed state", async () => {
  const requests: RecordedRequest[] = [];
  const loop: TraceExecutionFrame = {
    instance_id: 7,
    kind: "while",
    span: null,
    iteration: 1,
  };
  const loopContext: TraceContext = {
    function: null,
    call_depth: 0,
    call_stack: [],
    call_stack_truncated: 0,
    loops: [loop],
  };
  const callContext = (callDepth: number): TraceContext => ({
    function: callDepth === 0 ? null : "factorial",
    call_depth: callDepth,
    call_stack: [],
    call_stack_truncated: 0,
    loops: [],
  });
  const trace = {
    ok: true,
    artifact_available: true,
    session_id: "trace-session",
    diagnostics: [],
    base_state: { chaos_threshold: 1 },
    frames: [
      traceFrame(0, {}, { context: loopContext }),
      traceFrame(1, {
        variables: [{
          name: "answer",
          before_exists: false,
          before: null,
          after_exists: true,
          after: 42,
        }],
        output_values: [42],
        events: [{
          kind: "variable_assigned",
          data: { name: "answer", value: 42 },
          span: null,
        }],
      }, { context: loopContext }),
      traceFrame(2, {}, {
        active: {
          site_id: 3,
          node_kind: "FunctionCallNode",
          span: {
            start: { line: 3, column: 1 },
            end: { line: 3, column: 13 },
          },
          loop_instance_id: null,
        },
      }),
      traceFrame(3, {}, { context: callContext(1) }),
      traceFrame(4, {}, { context: callContext(2) }),
      traceFrame(5, {}, { context: callContext(1) }),
      traceFrame(6, {}, { active: null, status: "completed" }),
    ],
  };
  const app = loadApp(async (url, options) => {
    requests.push({ url, options });
    if (url === "/debug") {
      return response(trace);
    }
    if (url === "/evaluate") {
      return response({
        ok: true,
        session_id: "trace-session",
        state: { chaos_threshold: 1 },
        events: [],
        stats: null,
        values: [7],
        diagnostics: [],
      });
    }
    return response({ ok: true, diagnostics: [] });
  });
  const debug = app.elements.get("debug");
  const stepBack = app.elements.get("step-back");
  const step = app.elements.get("step");
  const stepOver = app.elements.get("step-over");
  const stepOut = app.elements.get("step-out");
  const stop = app.elements.get("stop");
  const status = app.elements.get("debug-status");
  const traceLayer = app.elements.get("trace-highlighting-content");

  await debug.dispatch("click");
  assert.equal(requests[0]!.url, "/debug");
  assert.deepEqual(JSON.parse(requests[0]!.options.body!), { source: "1" });
  assert.equal(status.dataset.state, "paused");
  assert.match(status.textContent, /line 1, frame 1 of 7/);
  assert.match(traceLayer.innerHTML, /trace-active-source/);
  assert.equal(stepBack.disabled, true);
  assert.equal(step.disabled, false);
  assert.equal(stepOut.disabled, true);

  app.elements.get("source").selectionStart = 1;
  app.elements.get("source").selectionEnd = 1;
  step.dispatch("click");
  assert.equal(app.elements.get("source").selectionStart, 1);
  assert.equal(app.elements.get("source").selectionEnd, 1);
  assert.equal(app.elements.get("chaos-level").textContent, "1");
  assert.match(app.elements.get("inspector-state").textContent, /answer = 42/);
  assert.match(app.elements.get("inspector-events").textContent, /Last event/);
  assert.equal(app.elements.get("output").textContent, "42");
  assert.equal(stepBack.disabled, false);

  stepBack.dispatch("click");
  assert.doesNotMatch(
    app.elements.get("inspector-state").textContent,
    /answer = 42/,
  );
  assert.equal(app.elements.get("output").textContent, "");

  stepOver.dispatch("click");
  assert.equal(status.dataset.state, "paused");
  assert.match(status.textContent, /frame 3 of 7/);
  assert.equal(app.elements.get("output").textContent, "42");
  assert.equal(stepOut.disabled, true);

  step.dispatch("click");
  assert.equal(status.dataset.state, "paused");
  assert.equal(stepOut.disabled, false);
  stepOut.dispatch("click");
  assert.equal(status.dataset.state, "finished");
  assert.match(status.textContent, /frame 7 of 7/);
  assert.equal(step.disabled, true);
  assert.equal(stop.disabled, false);

  stop.dispatch("click");
  assert.equal(status.dataset.state, "idle");
  assert.equal(app.elements.get("inspector-state").textContent, [
    "Chaos threshold: 1",
    "Variables: (none)",
  ].join("\n"));
  assert.equal(app.elements.get("output").textContent, "");
  assert.doesNotMatch(traceLayer.innerHTML, /trace-active-source/);

  await app.elements.get("run").dispatch("click");
  const evaluation = requests.find((request) => request.url === "/evaluate");
  assert.notEqual(evaluation, undefined);
  assert.equal(
    JSON.parse(evaluation!.options.body!).session_id,
    "trace-session",
  );
});

test("editing source aborts and supersedes a pending debug request", async () => {
  const pendingDebug = deferred();
  let debugSignal: AbortSignal | undefined;
  const app = loadApp((url, options) => {
    if (url === "/debug") {
      debugSignal = options.signal;
      return pendingDebug.promise;
    }
    return Promise.resolve(response({ ok: true, diagnostics: [] }));
  });
  const debugPromise = app.elements.get("debug").dispatch("click");
  await flushAsync();
  assert.equal(app.elements.get("debug-status").dataset.state, "loading");

  const source = app.elements.get("source");
  source.value = "2";
  source.dispatch("input");
  assert.notEqual(debugSignal, undefined);
  assert.equal(debugSignal!.aborted, true);
  assert.equal(app.elements.get("debug-status").dataset.state, "idle");
  assert.match(
    app.elements.get("debug-status").textContent,
    /source changed/,
  );

  pendingDebug.resolve(response({
    ok: true,
    artifact_available: true,
    session_id: "late",
    diagnostics: [],
    base_state: { chaos_threshold: 1 },
    frames: [traceFrame(0)],
  }));
  await debugPromise;
  assert.equal(app.elements.get("debug-status").dataset.state, "idle");
  assert.equal(app.elements.get("debug").disabled, false);
});

test("a terminal trace error preserves prior output and resolves its diagnostic", async () => {
  const diagnostic = {
    kind: "runtime",
    message: "Division by zero",
    span: {
      start: { line: 2, column: 1 },
      end: { line: 2, column: 6 },
    },
  };
  const app = loadApp(async (url) => response(
    url === "/debug"
      ? {
        ok: false,
        artifact_available: true,
        session_id: "session",
        diagnostics: [diagnostic],
        base_state: { chaos_threshold: 1 },
        frames: [
          traceFrame(0),
          traceFrame(1, {
            output_values: [7],
          }, {
            active: {
              site_id: null,
              node_kind: "error",
              span: diagnostic.span,
              loop_instance_id: null,
            },
            diagnostic_index: 0,
            status: "error",
          }),
        ],
      }
      : { ok: true, diagnostics: [] },
  ));

  await app.elements.get("debug").dispatch("click");
  assert.doesNotMatch(app.elements.get("output").textContent, /Division/);

  app.elements.get("step").dispatch("click");
  assert.equal(app.elements.get("debug-status").dataset.state, "error");
  assert.match(app.elements.get("output").textContent, /^7\n\nRuntime error:/);
  assert.equal(app.elements.get("output").classes.has("error"), true);

  app.elements.get("step-back").dispatch("click");
  assert.equal(app.elements.get("debug-status").dataset.state, "paused");
  assert.equal(app.elements.get("output").textContent, "");
  assert.equal(app.elements.get("output").classes.has("error"), false);
});

test("an unavailable trace has an explicit error state and remains stoppable", async () => {
  const app = loadApp(async (url) => response(
    url === "/debug"
      ? {
        ok: false,
        artifact_available: false,
        session_id: "session",
        diagnostics: [{
          kind: "limit",
          message: "Trace serialization budget exceeded",
          span: null,
        }],
        base_state: null,
        frames: [],
      }
      : { ok: true, diagnostics: [] },
  ));

  await app.elements.get("debug").dispatch("click");
  assert.equal(app.elements.get("debug-status").dataset.state, "error");
  assert.equal(app.elements.get("stop").disabled, false);
  assert.match(app.elements.get("output").textContent, /Trace serialization/);

  app.elements.get("stop").dispatch("click");
  assert.equal(app.elements.get("debug-status").dataset.state, "idle");
  assert.equal(app.elements.get("stop").disabled, true);
});
