const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

class FakeElement {
  constructor(value = "") {
    this.value = value;
    this.textContent = "";
    this.className = "";
    this.listeners = new Map();
    this.children = [];
    this.selectionStart = 0;
    this.selectionEnd = 0;
    this.disabled = false;
  }

  addEventListener(kind, listener) {
    this.listeners.set(kind, listener);
  }

  dispatch(kind) {
    return this.listeners.get(kind)?.({});
  }

  replaceChildren(...children) {
    this.children = children;
    this.textContent = "";
  }

  append(child) {
    this.children.push(child);
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
  };
}

function loadApp(fetchImpl) {
  const elements = new Map();
  const element = (id, value = "") => {
    const created = new FakeElement(value);
    elements.set(id, created);
    return created;
  };
  element("source", "1");
  element("validation-status");
  element("output");
  element("run");
  element("reset");
  element("examples");
  element("chaos-level");
  element("inspector-state");
  element("inspector-events");
  element("inspector-stats");

  const document = {
    getElementById: (id) => elements.get(id),
    querySelectorAll: () => [],
    createElement: () => new FakeElement(),
  };
  const context = vm.createContext({
    AbortController,
    clearTimeout,
    console,
    document,
    fetch: fetchImpl,
    setTimeout,
  });
  const appPath = path.join(__dirname, "..", "web", "static", "app.js");
  vm.runInContext(fs.readFileSync(appPath, "utf8"), context);
  return { elements };
}

const waitForDebounce = () => new Promise((resolve) => setTimeout(resolve, 325));
const flushAsync = () => new Promise((resolve) => setImmediate(resolve));

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
      message: "Unknown character '#'",
      span: {
        start: { line: 1, column: 4 },
        end: { line: 1, column: 5 },
      },
    }],
  }));
  const source = app.elements.get("source");
  const status = app.elements.get("validation-status");

  source.value = '"😀"#';
  source.dispatch("input");
  await waitForDebounce();
  await flushAsync();

  assert.equal(status.children.length, 1);
  status.children[0].dispatch("click");
  assert.equal(source.selectionStart, 4);
  assert.equal(source.selectionEnd, 5);
});
