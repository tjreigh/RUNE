const KIND_LABELS = {
  lex: "Lex error",
  parse: "Parse error",
  runtime: "Runtime error",
  internal: "Internal error",
  limit: "Execution limit",
};

const RUNE_KEYWORDS = new Set([
  "if",
  "elif",
  "else",
  "while",
  "for",
  "from",
  "to",
  "step",
  "break",
  "continue",
  "function",
  "return",
  "end",
  "and",
  "or",
  "not",
]);

const MULTI_CHARACTER_OPERATORS = [
  "**",
  "<<",
  ">>",
  "<=",
  ">=",
  "==",
  "!=",
];

const EDITOR_THEMES = new Set([
  "classic-dark",
  "ultraviolet",
  "classic-light",
  "cool-light",
]);

const LEGACY_EDITOR_THEMES = {
  dark: "classic-dark",
  light: "classic-light",
  "violet-dark": "ultraviolet",
};

const PAGE_THEMES = new Set(["system", "light", "dark"]);

const sourceEl = document.getElementById("source");
const editorFrameEl = document.getElementById("editor-frame");
const editorThemeEl = document.getElementById("editor-theme");
const pageThemeEl = document.getElementById("page-theme");
const highlightingEl = document.getElementById("highlighting");
const highlightingContentEl = document.getElementById("highlighting-content");
const sourcePositionEl = document.getElementById("source-position");
const validationStatusEl = document.getElementById("validation-status");
const outputEl = document.getElementById("output");
const runBtn = document.getElementById("run");
const resetBtn = document.getElementById("reset");
const examplesEl = document.getElementById("examples");
const chaosLevelEl = document.getElementById("chaos-level");
const inspectorStateEl = document.getElementById("inspector-state");
const inspectorEventsEl = document.getElementById("inspector-events");
const inspectorStatsEl = document.getElementById("inspector-stats");
const inspectorTabs = Array.from(document.querySelectorAll(".inspector-tab"));

let sessionId = null; // Opaque capability for server-side session state.
let heldState = null; // Last state returned, used only for the status display.
let heldEvents = [];
let heldStats = null;
let hasEvaluation = false;
let requestSeq = 0; // Prevent stale responses from overwriting newer state.
let activeController = null;
let validationRequestSeq = 0;
let validationController = null;
let validationTimer = null;
let exampleRequestSeq = 0;
let exampleController = null;

function applyEditorTheme(theme) {
  const migratedTheme = LEGACY_EDITOR_THEMES[theme] ?? theme;
  const selectedTheme = EDITOR_THEMES.has(migratedTheme)
    ? migratedTheme
    : "classic-dark";
  editorFrameEl.dataset.editorTheme = selectedTheme;
  editorThemeEl.value = selectedTheme;

  try {
    localStorage.setItem("rune-editor-theme", selectedTheme);
  } catch (_) {
    // A private or restricted browser may not expose local storage.
  }
}

function applyPageTheme(theme) {
  const selectedTheme = PAGE_THEMES.has(theme) ? theme : "system";
  document.documentElement.dataset.pageTheme = selectedTheme;
  pageThemeEl.value = selectedTheme;

  try {
    localStorage.setItem("rune-page-theme", selectedTheme);
  } catch (_) {
    // A private or restricted browser may not expose local storage.
  }
}

function initialEditorTheme() {
  try {
    return localStorage.getItem("rune-editor-theme") ?? "classic-dark";
  } catch (_) {
    return "classic-dark";
  }
}

function initialPageTheme() {
  try {
    return localStorage.getItem("rune-page-theme") ?? "system";
  } catch (_) {
    return "system";
  }
}

editorThemeEl.addEventListener("change", () => {
  applyEditorTheme(editorThemeEl.value);
});

pageThemeEl.addEventListener("change", () => {
  applyPageTheme(pageThemeEl.value);
});

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function highlightedToken(kind, text) {
  return `<span class="tok-${kind}">${escapeHtml(text)}</span>`;
}

function matchAt(source, offset, pattern) {
  return source.slice(offset).match(pattern)?.[0] ?? null;
}

function highlightRune(source) {
  let offset = 0;
  let markup = "";
  let expectsFunctionName = false;

  while (offset < source.length) {
    const rest = source.slice(offset);
    const character = rest[0];

    const whitespace = matchAt(source, offset, /^[\s]+/u);
    if (whitespace !== null) {
      markup += escapeHtml(whitespace);
      offset += whitespace.length;
      continue;
    }

    if (character === "#") {
      const newline = source.indexOf("\n", offset);
      const end = newline === -1 ? source.length : newline;
      markup += highlightedToken("comment", source.slice(offset, end));
      offset = end;
      expectsFunctionName = false;
      continue;
    }

    if (character === '"') {
      const closingQuote = source.indexOf('"', offset + 1);
      const end = closingQuote === -1 ? source.length : closingQuote + 1;
      const literal = source.slice(offset, end);
      markup += highlightedToken("string", literal);
      offset = end;
      expectsFunctionName = false;
      continue;
    }

    const prefixedNumber = matchAt(
      source,
      offset,
      /^0[bBoOxX][\p{L}\p{N}_]*/u,
    );
    if (prefixedNumber !== null) {
      markup += highlightedToken("number", prefixedNumber);
      offset += prefixedNumber.length;
      expectsFunctionName = false;
      continue;
    }

    const decimalNumber = matchAt(source, offset, /^\p{Nd}+/u);
    if (decimalNumber !== null) {
      markup += highlightedToken("number", decimalNumber);
      offset += decimalNumber.length;
      expectsFunctionName = false;
      continue;
    }

    const identifier = matchAt(
      source,
      offset,
      /^[\p{L}_][\p{L}\p{N}_]*/u,
    );
    if (identifier !== null) {
      let kind = "identifier";
      if (identifier === "chaos") {
        kind = "directive";
      } else if (RUNE_KEYWORDS.has(identifier)) {
        kind = "keyword";
      } else {
        const followingSource = source.slice(offset + identifier.length);
        if (expectsFunctionName || /^\s*\(/u.test(followingSource)) {
          kind = "function";
        }
      }
      markup += highlightedToken(kind, identifier);
      offset += identifier.length;
      expectsFunctionName = identifier === "function";
      continue;
    }

    if (character === "@") {
      markup += highlightedToken("directive", character);
      ++offset;
      expectsFunctionName = false;
      continue;
    }

    const operator = MULTI_CHARACTER_OPERATORS.find(
      (candidate) => rest.startsWith(candidate),
    ) ?? (/[+\-*/%~&|^<>=!]/u.test(character) ? character : null);
    if (operator !== null) {
      markup += highlightedToken("operator", operator);
      offset += operator.length;
      expectsFunctionName = false;
      continue;
    }

    if (/[(),]/u.test(character)) {
      markup += highlightedToken("punctuation", character);
      ++offset;
      continue;
    }

    const codePoint = String.fromCodePoint(source.codePointAt(offset));
    markup += escapeHtml(codePoint);
    offset += codePoint.length;
    expectsFunctionName = false;
  }

  // A trailing newline otherwise collapses in the backdrop and makes the
  // textarea and highlighted layer disagree about their scroll height.
  return source.endsWith("\n") ? `${markup} ` : markup;
}

function updateEditorHighlighting() {
  highlightingContentEl.innerHTML = highlightRune(sourceEl.value);
}

function syncEditorScroll() {
  highlightingEl.scrollTop = sourceEl.scrollTop;
  highlightingEl.scrollLeft = sourceEl.scrollLeft;
}

function updateSourcePosition() {
  const beforeCursor = sourceEl.value.slice(0, sourceEl.selectionStart);
  const lines = beforeCursor.split("\n");
  const line = lines.length;
  const column = Array.from(lines.at(-1)).length + 1;
  sourcePositionEl.textContent = `Ln ${line}, Col ${column}`;
}

examplesEl.addEventListener("change", async () => {
  const key = examplesEl.value;
  const mySeq = ++exampleRequestSeq;

  if (exampleController !== null) {
    exampleController.abort();
    exampleController = null;
  }
  if (!key) {
    return;
  }

  const controller = new AbortController();
  exampleController = controller;
  renderValidationStatus("neutral", "Loading example…");

  try {
    const response = await fetch(
      `/examples/${encodeURIComponent(key)}.rune`,
      { signal: controller.signal },
    );
    if (mySeq !== exampleRequestSeq) {
      return;
    }
    if (!response.ok) {
      renderValidationStatus(
        "unavailable",
        `Could not load example (${response.status}).`,
      );
      return;
    }

    sourceEl.value = await response.text();
    if (mySeq !== exampleRequestSeq) {
      return;
    }
    updateEditorHighlighting();
    syncEditorScroll();
    updateSourcePosition();
    scheduleValidation();
  } catch (networkError) {
    if (
      networkError.name !== "AbortError"
      && mySeq === exampleRequestSeq
    ) {
      renderValidationStatus("unavailable", "Could not load example.");
    }
  } finally {
    if (
      mySeq === exampleRequestSeq
      && exampleController === controller
    ) {
      exampleController = null;
    }
  }
});

function formatDiagnostic(diagnostic) {
  const label = KIND_LABELS[diagnostic.kind] || diagnostic.kind;
  if (diagnostic.span) {
    const { line, column } = diagnostic.span.start;
    return `${label}: line ${line}, col ${column}: ${diagnostic.message}`;
  }
  return `${label}: ${diagnostic.message}`;
}

function renderOutput(text, isError = false) {
  outputEl.textContent = text;
  outputEl.classList.toggle("error", isError);
}

function sourceOffsetAtPosition(source, position) {
  let line = 1;
  let column = 1;
  let offset = 0;

  for (const character of source) {
    if (line === position.line && column === position.column) {
      return offset;
    }
    offset += character.length; // JavaScript selection offsets use UTF-16.
    if (character === "\n") {
      ++line;
      column = 1;
    } else {
      ++column;
    }
  }
  return offset;
}

function selectDiagnosticSpan(span) {
  const source = sourceEl.value;
  const start = sourceOffsetAtPosition(source, span.start);
  const end = sourceOffsetAtPosition(source, span.end);
  sourceEl.focus();
  sourceEl.setSelectionRange(start, end);
  updateSourcePosition();
}

function renderValidationStatus(kind, text, span = null) {
  validationStatusEl.className = `validation-status ${kind}`;
  validationStatusEl.replaceChildren();

  if (span === null) {
    validationStatusEl.textContent = text;
    return;
  }

  const errorButton = document.createElement("button");
  errorButton.type = "button";
  errorButton.className = "validation-error";
  errorButton.textContent = text;
  errorButton.title = "Select this error in the editor";
  errorButton.addEventListener("click", () => selectDiagnosticSpan(span));
  validationStatusEl.append(errorButton);
}

async function validateSource(source, mySeq) {
  const controller = new AbortController();
  validationController = controller;

  try {
    let response;
    try {
      response = await fetch("/validate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ source }),
        signal: controller.signal,
      });
    } catch (networkError) {
      if (
        networkError.name !== "AbortError"
        && mySeq === validationRequestSeq
      ) {
        renderValidationStatus("unavailable", "Validation unavailable.");
      }
      return;
    }

    if (mySeq !== validationRequestSeq) {
      return;
    }

    if (!response.ok) {
      renderValidationStatus(
        "unavailable",
        `Validation unavailable (${response.status}).`,
      );
      return;
    }

    const result = await response.json();
    if (mySeq !== validationRequestSeq) {
      return;
    }

    if (result.ok) {
      renderValidationStatus("valid", "Syntax looks good.");
      return;
    }

    const diagnostic = result.diagnostics[0];
    renderValidationStatus(
      "invalid",
      formatDiagnostic(diagnostic),
      diagnostic.span,
    );
  } finally {
    if (
      mySeq === validationRequestSeq
      && validationController === controller
    ) {
      validationController = null;
    }
  }
}

function scheduleValidation() {
  const source = sourceEl.value;
  const mySeq = ++validationRequestSeq;

  if (validationTimer !== null) {
    clearTimeout(validationTimer);
    validationTimer = null;
  }
  if (validationController !== null) {
    validationController.abort();
    validationController = null;
  }

  if (source.length === 0) {
    renderValidationStatus("neutral", "Nothing to validate.");
    return;
  }

  renderValidationStatus("neutral", "Checking syntax…");
  validationTimer = setTimeout(() => {
    validationTimer = null;
    validateSource(source, mySeq);
  }, 300);
}

sourceEl.addEventListener("input", () => {
  ++exampleRequestSeq;
  if (exampleController !== null) {
    exampleController.abort();
    exampleController = null;
  }
  examplesEl.value = "";
  updateEditorHighlighting();
  updateSourcePosition();
  scheduleValidation();
});
sourceEl.addEventListener("scroll", syncEditorScroll);
sourceEl.addEventListener("click", updateSourcePosition);
sourceEl.addEventListener("keyup", updateSourcePosition);
sourceEl.addEventListener("select", updateSourcePosition);
sourceEl.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    runBtn.click();
  }
});

function formatRequestDetail(detail) {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map((issue) => {
      const location = Array.isArray(issue.loc)
        ? issue.loc.filter((part) => part !== "body").join(".")
        : "";
      const message = issue.msg ?? JSON.stringify(issue);
      return location ? `${location}: ${message}` : message;
    }).join("; ");
  }
  return JSON.stringify(detail);
}

function updateChaosDisplay() {
  const threshold = heldState?.chaos_threshold ?? 1;
  chaosLevelEl.textContent = String(threshold);
}

function formatState(state) {
  const threshold = state?.chaos_threshold ?? 1;
  const variables = Object.entries(state?.variables ?? {})
    .sort(([left], [right]) => left.localeCompare(right));
  const variableLines = variables.length === 0
    ? ["Variables: (none)"]
    : ["Variables:", ...variables.map(([name, value]) => `  ${name} = ${value}`)];
  return [`Chaos threshold: ${threshold}`, ...variableLines].join("\n");
}

function formatEvent(event) {
  if (event.kind === "variable_assigned") {
    return `${event.data.name} = ${event.data.value}`;
  }
  if (event.kind === "chaos_threshold_changed") {
    return `Chaos threshold = ${event.data.threshold}`;
  }
  return `${event.kind}: ${JSON.stringify(event.data)}`;
}

function formatStats(stats, evaluated) {
  if (stats === null) {
    return evaluated
      ? "Not available (evaluation did not begin)."
      : "No evaluation yet.";
  }
  return [
    `Steps: ${stats.steps}`,
    `Peak recursion depth: ${stats.peak_recursion_depth}`,
    `Output values: ${stats.output_values}`,
    `Runtime events: ${stats.runtime_events}`,
    `Loop iterations: ${stats.loop_iterations}`,
  ].join("\n");
}

function renderInspector() {
  inspectorStateEl.textContent = formatState(heldState);
  inspectorEventsEl.textContent = heldEvents.length === 0
    ? "No runtime events."
    : heldEvents.map(formatEvent).join("\n");
  inspectorStatsEl.textContent = formatStats(heldStats, hasEvaluation);
}

function activateInspectorTab(selectedTab, moveFocus = true) {
  for (const tab of inspectorTabs) {
    const selected = tab === selectedTab;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    document.getElementById(tab.getAttribute("aria-controls")).hidden = !selected;
  }
  if (moveFocus) {
    selectedTab.focus();
  }
}

for (const [index, tab] of inspectorTabs.entries()) {
  tab.addEventListener("click", () => activateInspectorTab(tab, false));
  tab.addEventListener("keydown", (event) => {
    let nextIndex = null;
    if (event.key === "ArrowRight") {
      nextIndex = (index + 1) % inspectorTabs.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (index - 1 + inspectorTabs.length) % inspectorTabs.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = inspectorTabs.length - 1;
    }
    if (nextIndex !== null) {
      event.preventDefault();
      activateInspectorTab(inspectorTabs[nextIndex]);
    }
  });
}

resetBtn.addEventListener("click", async () => {
  ++requestSeq;
  if (activeController !== null) {
    activeController.abort();
    activeController = null;
  }
  const resetSessionId = sessionId;
  sessionId = null;
  heldState = null;
  heldEvents = [];
  heldStats = null;
  hasEvaluation = false;
  updateChaosDisplay();
  renderInspector();
  runBtn.disabled = false;
  renderOutput("");

  if (resetSessionId !== null) {
    try {
      await fetch("/reset", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ session_id: resetSessionId }),
      });
    } catch (_) {
      // The token is forgotten locally regardless. An unreachable server
      // will expire the now-unreachable session by TTL.
    }
  }
});

runBtn.addEventListener("click", async () => {
  const mySeq = ++requestSeq;
  const controller = new AbortController();
  activeController = controller;
  runBtn.disabled = true;

  try {
    const payload = { source: sourceEl.value };
    if (sessionId !== null) {
      payload.session_id = sessionId;
    }

    let response;
    try {
      response = await fetch("/evaluate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
    } catch (networkError) {
      if (networkError.name !== "AbortError" && mySeq === requestSeq) {
        renderOutput(`Network error: ${networkError}`, true);
      }
      return;
    }

    if (mySeq !== requestSeq) {
      return;
    }

    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = await response.json();
        detail = formatRequestDetail(body.detail ?? body);
      } catch (_) {
        // The status text is the best fallback for a non-JSON error body.
      }
      if (response.status === 404) {
        sessionId = null;
        heldState = null;
        heldEvents = [];
        heldStats = null;
        hasEvaluation = false;
        updateChaosDisplay();
        renderInspector();
      }
      renderOutput(`Request rejected (${response.status}): ${detail}`, true);
      return;
    }

    const result = await response.json();
    sessionId = result.session_id;
    heldState = result.state;
    heldEvents = result.events ?? [];
    heldStats = result.stats ?? null;
    hasEvaluation = true;
    updateChaosDisplay();
    renderInspector();
    if (result.ok) {
      renderOutput(result.values.map(String).join("\n"));
    } else {
      renderOutput(result.diagnostics.map(formatDiagnostic).join("\n"), true);
    }
  } finally {
    if (mySeq === requestSeq) {
      activeController = null;
      runBtn.disabled = false;
    }
  }
});

updateEditorHighlighting();
updateSourcePosition();
applyEditorTheme(initialEditorTheme());
applyPageTheme(initialPageTheme());

scheduleValidation();
