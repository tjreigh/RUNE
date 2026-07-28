import { highlightRune, sourceOffsetAtPosition } from "./editor.js";
import {
  formatDiagnostic,
  formatEvent,
  formatRequestDetail,
  formatState,
  formatStats,
} from "./formatters.js";
import type {
  Diagnostic,
  ExecutionStats,
  RuntimeEvent,
  RuntimeState,
  SourceSpan,
} from "./formatters.js";

interface ValidationResult {
  ok: boolean;
  diagnostics: Diagnostic[];
}

interface EvaluationResult {
  ok: boolean;
  session_id: string;
  state: RuntimeState;
  events?: RuntimeEvent[];
  stats?: ExecutionStats | null;
  values: number[];
  diagnostics: Diagnostic[];
}

interface EvaluateRequest {
  source: string;
  session_id?: string;
}

interface RuneReplDependencies {
  document: Document;
  fetch: typeof globalThis.fetch;
  localStorage: Storage;
  AbortController: typeof globalThis.AbortController;
  setTimeout: typeof globalThis.setTimeout;
  clearTimeout: typeof globalThis.clearTimeout;
}

const EDITOR_THEMES = new Set([
  "classic-dark",
  "ultraviolet",
  "classic-light",
  "cool-light",
]);

const LEGACY_EDITOR_THEMES: Record<string, string> = {
  dark: "classic-dark",
  light: "classic-light",
  "violet-dark": "ultraviolet",
};

const PAGE_THEMES = new Set(["system", "light", "dark"]);

function requiredElement(document: Document, id: string): HTMLElement {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error(`RUNE page is missing #${id}`);
  }
  return element;
}

function isAbortError(error: unknown): boolean {
  return (
    error !== null
    && typeof error === "object"
    && "name" in error
    && error.name === "AbortError"
  );
}

/**
 * Bind one RUNE REPL document to its browser services.
 *
 * Keeping construction explicit lets tests create isolated applications
 * without executing the browser entry module or replacing process globals.
 */
export function startRuneRepl({
  document,
  fetch,
  localStorage,
  AbortController,
  setTimeout,
  clearTimeout,
}: RuneReplDependencies): void {
  const sourceEl = requiredElement(document, "source") as HTMLTextAreaElement;
  const editorFrameEl = requiredElement(document, "editor-frame");
  const editorThemeEl = requiredElement(
    document,
    "editor-theme",
  ) as HTMLSelectElement;
  const pageThemeEl = requiredElement(
    document,
    "page-theme",
  ) as HTMLSelectElement;
  const highlightingEl = requiredElement(document, "highlighting");
  const highlightingContentEl = requiredElement(
    document,
    "highlighting-content",
  );
  const sourcePositionEl = requiredElement(document, "source-position");
  const validationStatusEl = requiredElement(document, "validation-status");
  const outputEl = requiredElement(document, "output");
  const runBtn = requiredElement(document, "run") as HTMLButtonElement;
  const resetBtn = requiredElement(document, "reset") as HTMLButtonElement;
  const examplesEl = requiredElement(
    document,
    "examples",
  ) as HTMLSelectElement;
  const chaosLevelEl = requiredElement(document, "chaos-level");
  const inspectorStateEl = requiredElement(document, "inspector-state");
  const inspectorEventsEl = requiredElement(document, "inspector-events");
  const inspectorStatsEl = requiredElement(document, "inspector-stats");
  const inspectorTabs = (
    Array.from(document.querySelectorAll(".inspector-tab"))
  ) as HTMLButtonElement[];

  let sessionId: string | null = null; // Opaque server-side session capability.
  let heldState: RuntimeState | null = null;
  let heldEvents: RuntimeEvent[] = [];
  let heldStats: ExecutionStats | null = null;
  let hasEvaluation = false;
  let requestSeq = 0; // Prevent stale responses from overwriting newer state.
  let activeController: AbortController | null = null;
  let validationRequestSeq = 0;
  let validationController: AbortController | null = null;
  let validationTimer: ReturnType<typeof setTimeout> | null = null;
  let exampleRequestSeq = 0;
  let exampleController: AbortController | null = null;

  function applyEditorTheme(theme: string): void {
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

  function applyPageTheme(theme: string): void {
    const selectedTheme = PAGE_THEMES.has(theme) ? theme : "system";
    document.documentElement.dataset.pageTheme = selectedTheme;
    pageThemeEl.value = selectedTheme;

    try {
      localStorage.setItem("rune-page-theme", selectedTheme);
    } catch (_) {
      // A private or restricted browser may not expose local storage.
    }
  }

  function initialEditorTheme(): string {
    try {
      return localStorage.getItem("rune-editor-theme") ?? "classic-dark";
    } catch (_) {
      return "classic-dark";
    }
  }

  function initialPageTheme(): string {
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

  function updateEditorHighlighting(): void {
    highlightingContentEl.innerHTML = highlightRune(sourceEl.value);
  }

  function syncEditorScroll(): void {
    highlightingEl.scrollTop = sourceEl.scrollTop;
    highlightingEl.scrollLeft = sourceEl.scrollLeft;
  }

  function updateSourcePosition(): void {
    const beforeCursor = sourceEl.value.slice(0, sourceEl.selectionStart);
    const lines = beforeCursor.split("\n");
    const line = lines.length;
    const column = Array.from(lines.at(-1) ?? "").length + 1;
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
        !isAbortError(networkError)
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

  function renderOutput(text: string, isError = false): void {
    outputEl.textContent = text;
    outputEl.classList.toggle("error", isError);
  }

  function selectDiagnosticSpan(span: SourceSpan): void {
    const source = sourceEl.value;
    const start = sourceOffsetAtPosition(source, span.start);
    const end = sourceOffsetAtPosition(source, span.end);
    sourceEl.focus();
    sourceEl.setSelectionRange(start, end);
    updateSourcePosition();
  }

  function renderValidationStatus(
    kind: string,
    text: string,
    span: SourceSpan | null = null,
  ): void {
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

  async function validateSource(source: string, mySeq: number): Promise<void> {
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
          !isAbortError(networkError)
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

      const result = await response.json() as ValidationResult;
      if (mySeq !== validationRequestSeq) {
        return;
      }

      if (result.ok) {
        renderValidationStatus("valid", "Syntax looks good.");
        return;
      }

      const diagnostic = result.diagnostics[0];
      if (diagnostic === undefined) {
        renderValidationStatus("unavailable", "Validation response was invalid.");
        return;
      }
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

  function scheduleValidation(): void {
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

  function updateChaosDisplay(): void {
    const threshold = heldState?.chaos_threshold ?? 1;
    chaosLevelEl.textContent = String(threshold);
  }

  function renderInspector(): void {
    inspectorStateEl.textContent = formatState(heldState);
    inspectorEventsEl.textContent = heldEvents.length === 0
      ? "No runtime events."
      : heldEvents.map(formatEvent).join("\n");
    inspectorStatsEl.textContent = formatStats(heldStats, hasEvaluation);
  }

  function activateInspectorTab(
    selectedTab: HTMLButtonElement,
    moveFocus = true,
  ): void {
    for (const tab of inspectorTabs) {
      const selected = tab === selectedTab;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      const panelId = tab.getAttribute("aria-controls");
      if (panelId === null) {
        throw new Error("Inspector tab is missing aria-controls");
      }
      requiredElement(document, panelId).hidden = !selected;
    }
    if (moveFocus) {
      selectedTab.focus();
    }
  }

  for (const [index, tab] of inspectorTabs.entries()) {
    tab.addEventListener("click", () => activateInspectorTab(tab, false));
    tab.addEventListener("keydown", (event) => {
      let nextIndex: number | null = null;
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
        const nextTab = inspectorTabs[nextIndex];
        if (nextTab !== undefined) {
          activateInspectorTab(nextTab);
        }
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
      const payload: EvaluateRequest = { source: sourceEl.value };
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
        if (!isAbortError(networkError) && mySeq === requestSeq) {
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
          const body = await response.json() as { detail?: unknown };
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

      const result = await response.json() as EvaluationResult;
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
}
