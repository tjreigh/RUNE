import assert from "node:assert/strict";
import test from "node:test";

import {
  highlightActiveTraceSpan,
  highlightRune,
  scrollTopToRevealLine,
} from "../../frontend/src/editor.js";
import { loadApp, response } from "./support/fake-browser.js";

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
