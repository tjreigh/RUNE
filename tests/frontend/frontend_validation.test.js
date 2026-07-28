const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

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
  element("source-position");
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
    documentElement: new FakeElement(),
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
    localStorage: {
      getItem: (key) => storedValues.get(key) ?? null,
      setItem: (key, value) => storedValues.set(key, value),
    },
    setTimeout,
  });
  const appPath = path.join(
    __dirname,
    "..",
    "..",
    "src",
    "rune_web",
    "static",
    "app.js"
  );
  vm.runInContext(fs.readFileSync(appPath, "utf8"), context);
  return { context, elements, storedValues };
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
  const app = loadApp(async () => response({ ok: true, diagnostics: [] }));
  const markup = vm.runInContext(
    'highlightRune(\'# <note>\\n@chaos 5\\nfunction add(x)\\nreturn x + "<tag>"\\nend function\')',
    app.context,
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

  assert.equal(app.context.document.documentElement.dataset.pageTheme, "dark");
  assert.equal(frame.dataset.editorTheme, "classic-light");

  editorTheme.value = "cool-light";
  editorTheme.dispatch("change");

  assert.equal(app.context.document.documentElement.dataset.pageTheme, "dark");
  assert.equal(frame.dataset.editorTheme, "cool-light");
  assert.equal(app.storedValues.get("rune-editor-theme"), "cool-light");

  pageTheme.value = "light";
  pageTheme.dispatch("change");

  assert.equal(app.context.document.documentElement.dataset.pageTheme, "light");
  assert.equal(frame.dataset.editorTheme, "cool-light");
  assert.equal(app.storedValues.get("rune-page-theme"), "light");
});

test("page theme defaults to the live system preference", () => {
  const app = loadApp(async () => response({ ok: true, diagnostics: [] }));

  assert.equal(
    app.context.document.documentElement.dataset.pageTheme,
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
