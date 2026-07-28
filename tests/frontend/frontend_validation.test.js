import assert from "node:assert/strict";
import test from "node:test";

import {
  highlightActiveTraceSpan,
  highlightRune,
  scrollTopToRevealLine,
} from "../../src/rune_web/static/build/editor.js";
import {
  formatTraceStats,
} from "../../src/rune_web/static/build/formatters.js";
import { startRuneRepl } from "../../src/rune_web/static/build/repl.js";
import { TracePlayback } from "../../src/rune_web/static/build/trace-player.js";

class FakeElement {
  constructor(value = "") {
    this.value = value;
    this.textContent = "";
    this.innerHTML = "";
    this.className = "";
    this.listeners = new Map();
    this.children = [];
    this.selectionStart = 0;
    this.selectionEnd = 0;
    this.scrollTop = 0;
    this.scrollLeft = 0;
    this.dataset = {};
    this.disabled = false;
    this.hidden = false;
    this.tabIndex = 0;
    this.attributes = new Map();
    this.classes = new Set();
    this.classList = {
      toggle: (name, force) => {
        if (force) {
          this.classes.add(name);
        } else {
          this.classes.delete(name);
        }
      },
    };
  }

  addEventListener(kind, listener) {
    this.listeners.set(kind, listener);
  }

  dispatch(kind, event = {}) {
    return this.listeners.get(kind)?.(event);
  }

  replaceChildren(...children) {
    this.children = children;
    this.textContent = "";
  }

  append(child) {
    this.children.push(child);
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  setSelectionRange(start, end) {
    this.selectionStart = start;
    this.selectionEnd = end;
  }

  focus() {}
}

function deferred() {
  let resolve;
  const promise = new Promise((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => (
      typeof body === "string" ? body : JSON.stringify(body)
    ),
  };
}

function loadApp(fetchImpl, initialStoredValues = []) {
  const elements = new Map();
  const storedValues = new Map(initialStoredValues);
  const element = (id, value = "") => {
    const created = new FakeElement(value);
    elements.set(id, created);
    return created;
  };
  element("source", "1");
  element("editor-frame");
  element("editor-theme", "classic-dark");
  element("page-theme", "system");
  element("highlighting");
  element("highlighting-content");
  element("trace-highlighting");
  element("trace-highlighting-content");
  element("source-position");
  element("validation-status");
  element("output");
  element("run");
  element("debug");
  element("reset");
  element("step-back");
  element("step");
  element("step-over");
  element("step-out");
  element("stop");
  element("debug-status");
  element("examples");
  element("chaos-level");
  element("inspector-state");
  element("inspector-events");
  element("inspector-stats");
  element("inspector-context");

  const document = {
    documentElement: new FakeElement(),
    getElementById: (id) => elements.get(id),
    querySelectorAll: () => [],
    createElement: () => new FakeElement(),
  };
  startRuneRepl({
    AbortController,
    clearTimeout,
    document,
    fetch: fetchImpl,
    localStorage: {
      getItem: (key) => storedValues.get(key) ?? null,
      setItem: (key, value) => storedValues.set(key, value),
    },
    setTimeout,
  });
  return { document, elements, storedValues };
}

const waitForDebounce = () => new Promise((resolve) => setTimeout(resolve, 325));
const flushAsync = () => new Promise((resolve) => setImmediate(resolve));

function traceFrame(number, changes, overrides = {}) {
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
  assert.deepEqual(playback.current.variables, { kept: 3 });
  assert.equal(playback.current.frame.active.span.start.line, 1);

  assert.equal(playback.stepForward(), true);
  assert.equal(playback.current.chaosThreshold, 500);
  assert.deepEqual(playback.current.variables, { kept: 3, answer: 42 });
  assert.deepEqual(playback.current.locals, [{
    scopeId: 7,
    kind: "function",
    label: "solve",
    values: { value: 9 },
  }]);
  assert.deepEqual(playback.current.outputValues, [42]);
  assert.equal(playback.current.events.length, 1);
  assert.equal(playback.current.frame.active.span.start.line, 2);
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
  assert.equal(playback.current.chaosThreshold, 2);
  assert.deepEqual(playback.current.variables, {});
  assert.deepEqual(playback.current.locals, []);
  assert.deepEqual(playback.current.outputValues, []);
  assert.deepEqual(playback.current.events, []);
  assert.equal(playback.stepBack(), false);
});

test("step over exits the innermost enclosing loop", () => {
  const outerLoop = {
    instance_id: 10,
    kind: "while",
    span: null,
    iteration: 1,
  };
  const innerLoop = {
    instance_id: 20,
    kind: "for",
    span: null,
    iteration: 1,
  };
  const context = (loops) => ({
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
  assert.deepEqual(outerPlayback.current.outputValues, [1, 2, 3, 4, 5]);

  const innerPlayback = new TracePlayback(result);
  innerPlayback.stepForward();
  innerPlayback.stepForward();
  innerPlayback.stepForward();
  assert.equal(innerPlayback.index, 3);
  assert.equal(innerPlayback.stepOver(), true);
  assert.equal(innerPlayback.index, 4);
});

test("step over skips recursive calls until the current call depth resumes", () => {
  const context = (callDepth) => ({
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
  assert.deepEqual(topLevelPlayback.current.outputValues, [1, 2, 3, 4]);

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

test("the trace highlight is a separate Unicode-aware source layer", () => {
  const markup = highlightActiveTraceSpan(
    'face = "😀"\nface',
    {
      start: { line: 1, column: 9 },
      end: { line: 1, column: 10 },
    },
  );

  assert.match(
    markup,
    /face = "<span class="trace-active-source">😀<\/span>"/,
  );
  assert.doesNotMatch(markup, /tok-/);
});

test("trace line scrolling keeps context without moving already-visible lines", () => {
  assert.equal(scrollTopToRevealLine({
    line: 5,
    scrollTop: 40,
    viewportHeight: 200,
    lineHeight: 20,
    paddingTop: 16,
  }), 40);
  assert.equal(scrollTopToRevealLine({
    line: 20,
    scrollTop: 0,
    viewportHeight: 200,
    lineHeight: 20,
    paddingTop: 16,
  }), 256);
  assert.equal(scrollTopToRevealLine({
    line: 2,
    scrollTop: 200,
    viewportHeight: 200,
    lineHeight: 20,
    paddingTop: 16,
  }), 0);
});

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
  const requests = [];
  const loop = {
    instance_id: 7,
    kind: "while",
    span: null,
    iteration: 1,
  };
  const loopContext = {
    function: null,
    call_depth: 0,
    call_stack: [],
    call_stack_truncated: 0,
    loops: [loop],
  };
  const callContext = (callDepth) => ({
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
  assert.equal(requests[0].url, "/debug");
  assert.deepEqual(JSON.parse(requests[0].options.body), { source: "1" });
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
  assert.equal(
    JSON.parse(evaluation.options.body).session_id,
    "trace-session",
  );
});

test("editing source aborts and supersedes a pending debug request", async () => {
  const pendingDebug = deferred();
  let debugSignal;
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
  assert.equal(debugSignal.aborted, true);
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

test("superseded validation is aborted and its late response is ignored", async () => {
  const requests = [];
  const first = deferred();
  const second = deferred();
  const app = loadApp((url, options) => {
    requests.push({ url, options });
    return requests.length === 1 ? first.promise : second.promise;
  });
  const source = app.elements.get("source");
  const status = app.elements.get("validation-status");
  const run = app.elements.get("run");

  source.value = "if (1)";
  source.dispatch("input");
  await waitForDebounce();
  assert.equal(requests.length, 1);
  assert.equal(run.disabled, false);

  source.value = "2+2";
  source.dispatch("input");
  assert.equal(requests[0].options.signal.aborted, true);
  await waitForDebounce();
  assert.equal(requests.length, 2);

  second.resolve(response({ ok: true, diagnostics: [] }));
  await flushAsync();
  assert.equal(status.textContent, "Syntax looks good.");

  first.resolve(response({
    ok: false,
    diagnostics: [{
      kind: "parse",
      message: "late error",
      span: {
        start: { line: 1, column: 1 },
        end: { line: 1, column: 3 },
      },
    }],
  }));
  await flushAsync();
  assert.equal(status.textContent, "Syntax looks good.");
  assert.equal(status.children.length, 0);
  assert.equal(run.disabled, false);
});

test("clicking a Unicode diagnostic selects its source span", async () => {
  const app = loadApp(async () => response({
    ok: false,
    diagnostics: [{
      kind: "lex",
      message: "Unknown character '$'",
      span: {
        start: { line: 1, column: 4 },
        end: { line: 1, column: 5 },
      },
    }],
  }));
  const source = app.elements.get("source");
  const status = app.elements.get("validation-status");

  source.value = '"😀"$';
  source.dispatch("input");
  await waitForDebounce();
  await flushAsync();

  assert.equal(status.children.length, 1);
  status.children[0].dispatch("click");
  assert.equal(source.selectionStart, 4);
  assert.equal(source.selectionEnd, 5);
});

test("RUNE highlighting recognizes language tokens and escapes source", () => {
  loadApp(async () => response({ ok: true, diagnostics: [] }));
  const markup = highlightRune(
    '# <note>\n@chaos 5\nfunction add(x)\nreturn x + "<tag>"\nend function',
  );

  assert.match(markup, /class="tok-comment"># &lt;note&gt;<\/span>/);
  assert.match(markup, /class="tok-directive">@<\/span>/);
  assert.match(markup, /class="tok-directive">chaos<\/span>/);
  assert.match(markup, /class="tok-number">5<\/span>/);
  assert.match(markup, /class="tok-keyword">function<\/span>/);
  assert.match(markup, /class="tok-function">add<\/span>/);
  assert.match(markup, /class="tok-keyword">return<\/span>/);
  assert.match(markup, /class="tok-string">"&lt;tag&gt;"<\/span>/);
  assert.doesNotMatch(markup, /<tag>/);
});

test("the highlighted layer and cursor position follow editor changes", () => {
  const app = loadApp(async () => response({ ok: true, diagnostics: [] }));
  const source = app.elements.get("source");
  const highlighting = app.elements.get("highlighting");
  const traceHighlighting = app.elements.get("trace-highlighting");
  const highlightedContent = app.elements.get("highlighting-content");
  const position = app.elements.get("source-position");

  source.value = 'face = "😀"\nface';
  source.selectionStart = source.value.length;
  source.dispatch("input");
  assert.match(highlightedContent.innerHTML, /class="tok-string">"😀"<\/span>/);
  assert.equal(position.textContent, "Ln 2, Col 5");

  source.scrollTop = 24;
  source.scrollLeft = 8;
  source.dispatch("scroll");
  assert.equal(highlighting.scrollTop, 24);
  assert.equal(highlighting.scrollLeft, 8);
  assert.equal(traceHighlighting.scrollTop, 24);
  assert.equal(traceHighlighting.scrollLeft, 8);
});

test("editor theme changes are applied and remembered", () => {
  const app = loadApp(async () => response({ ok: true, diagnostics: [] }));
  const frame = app.elements.get("editor-frame");
  const theme = app.elements.get("editor-theme");

  assert.equal(frame.dataset.editorTheme, "classic-dark");
  theme.value = "ultraviolet";
  theme.dispatch("change");

  assert.equal(frame.dataset.editorTheme, "ultraviolet");
  assert.equal(app.storedValues.get("rune-editor-theme"), "ultraviolet");
});

test("legacy editor theme preferences migrate to classic variants", () => {
  const app = loadApp(
    async () => response({ ok: true, diagnostics: [] }),
    [["rune-editor-theme", "light"]],
  );

  assert.equal(
    app.elements.get("editor-frame").dataset.editorTheme,
    "classic-light",
  );
  assert.equal(app.storedValues.get("rune-editor-theme"), "classic-light");
});

test("the provisional violet theme name migrates to ultraviolet", () => {
  const app = loadApp(
    async () => response({ ok: true, diagnostics: [] }),
    [["rune-editor-theme", "violet-dark"]],
  );

  assert.equal(
    app.elements.get("editor-frame").dataset.editorTheme,
    "ultraviolet",
  );
  assert.equal(app.storedValues.get("rune-editor-theme"), "ultraviolet");
});

test("page and editor themes are independent and remembered", () => {
  const app = loadApp(
    async () => response({ ok: true, diagnostics: [] }),
    [
      ["rune-editor-theme", "classic-light"],
      ["rune-page-theme", "dark"],
    ],
  );
  const frame = app.elements.get("editor-frame");
  const editorTheme = app.elements.get("editor-theme");
  const pageTheme = app.elements.get("page-theme");

  assert.equal(app.document.documentElement.dataset.pageTheme, "dark");
  assert.equal(frame.dataset.editorTheme, "classic-light");

  editorTheme.value = "cool-light";
  editorTheme.dispatch("change");

  assert.equal(app.document.documentElement.dataset.pageTheme, "dark");
  assert.equal(frame.dataset.editorTheme, "cool-light");
  assert.equal(app.storedValues.get("rune-editor-theme"), "cool-light");

  pageTheme.value = "light";
  pageTheme.dispatch("change");

  assert.equal(app.document.documentElement.dataset.pageTheme, "light");
  assert.equal(frame.dataset.editorTheme, "cool-light");
  assert.equal(app.storedValues.get("rune-page-theme"), "light");
});

test("page theme defaults to the live system preference", () => {
  const app = loadApp(async () => response({ ok: true, diagnostics: [] }));

  assert.equal(
    app.document.documentElement.dataset.pageTheme,
    "system",
  );
  assert.equal(app.elements.get("page-theme").value, "system");
});

test("the selected example stays visible until its source is edited", async () => {
  const loops = `while (count)
  count
  count = count - 1
end while
`;
  const app = loadApp(async (url) => (
    url === "/examples/loops.rune"
      ? response(loops)
      : response({ ok: true, diagnostics: [] })
  ));
  const examples = app.elements.get("examples");
  const source = app.elements.get("source");

  examples.value = "loops";
  await examples.dispatch("change");
  assert.equal(examples.value, "loops");
  assert.match(source.value, /\n  count\n  count = count - 1\n/);

  source.value += "\n";
  source.dispatch("input");
  assert.equal(examples.value, "");
});
