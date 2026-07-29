import assert from "node:assert/strict";
import test from "node:test";

import { loadApp, response } from "./support/fake-browser.js";

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
