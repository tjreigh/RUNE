import assert from "node:assert/strict";
import test from "node:test";

import {
  deferred,
  flushAsync,
  loadApp,
  response,
  waitForDebounce,
} from "./support/fake-browser.js";
import type { RecordedRequest } from "./support/fake-browser.js";

test("superseded validation is aborted and its late response is ignored", async () => {
  const requests: RecordedRequest[] = [];
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
  assert.equal(requests[0]!.options.signal.aborted, true);
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
  status.children[0]!.dispatch("click");
  assert.equal(source.selectionStart, 4);
  assert.equal(source.selectionEnd, 5);
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
