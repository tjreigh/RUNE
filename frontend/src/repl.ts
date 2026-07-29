import {
  highlightActiveTraceSpan,
  highlightRune,
  scrollTopToRevealLine,
  sourceOffsetAtPosition,
} from "./editor.js";
import {
  formatDiagnostic,
  formatEvent,
  formatRequestDetail,
  formatState,
  formatStats,
  formatTraceContext,
  formatTraceState,
  formatTraceStats,
} from "./formatters.js";
import type {
  Diagnostic,
  ExecutionStats,
  RuntimeEvent,
  RuntimeState,
  SourceSpan,
} from "./formatters.js";
import { TracePlayback } from "./trace-player.js";
import type {
  TracePlaybackSnapshot,
  TraceResult,
} from "./trace-player.js";

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

type DebuggerState = (
  "idle" | "loading" | "paused" | "playing" | "finished" | "error"
);
type RequestKind = "evaluate" | "debug";

const PLAYBACK_FRAME_DELAY_MS = 140;

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
  const traceHighlightingEl = requiredElement(document, "trace-highlighting");
  const traceHighlightingContentEl = requiredElement(
    document,
    "trace-highlighting-content",
  );
  const sourcePositionEl = requiredElement(document, "source-position");
  const validationStatusEl = requiredElement(document, "validation-status");
  const outputEl = requiredElement(document, "output");
  const runBtn = requiredElement(document, "run") as HTMLButtonElement;
  const debugBtn = requiredElement(document, "debug") as HTMLButtonElement;
  const resetBtn = requiredElement(document, "reset") as HTMLButtonElement;
  const restartBtn = requiredElement(document, "restart") as HTMLButtonElement;
  const stepBackBtn = requiredElement(
    document,
    "step-back",
  ) as HTMLButtonElement;
  const stepBtn = requiredElement(document, "step") as HTMLButtonElement;
  const stepOverBtn = requiredElement(
    document,
    "step-over",
  ) as HTMLButtonElement;
  const stepOutBtn = requiredElement(
    document,
    "step-out",
  ) as HTMLButtonElement;
  const playBtn = requiredElement(document, "play") as HTMLButtonElement;
  const playIconEl = requiredElement(document, "play-icon");
  const playLabelEl = requiredElement(document, "play-label");
  const playbackSpeedEl = requiredElement(
    document,
    "playback-speed",
  ) as HTMLInputElement;
  const playbackSpeedValueEl = requiredElement(
    document,
    "playback-speed-value",
  );
  const playbackSpeedControlEl = requiredElement(
    document,
    "playback-speed-control",
  );
  const stopBtn = requiredElement(document, "stop") as HTMLButtonElement;
  const debugStatusEl = requiredElement(document, "debug-status");
  const examplesEl = requiredElement(
    document,
    "examples",
  ) as HTMLSelectElement;
  const runtimeStateEl = requiredElement(document, "runtime-state");
  const chaosLevelEl = requiredElement(document, "chaos-level");
  const inspectorStateEl = requiredElement(document, "inspector-state");
  const inspectorEventsEl = requiredElement(document, "inspector-events");
  const inspectorStatsEl = requiredElement(document, "inspector-stats");
  const inspectorContextEl = requiredElement(document, "inspector-context");
  const inspectorTabs = (
    Array.from(document.querySelectorAll(".inspector-tab"))
  ) as HTMLButtonElement[];

  let sessionId: string | null = null; // Opaque server-side session capability.
  let heldState: RuntimeState | null = null;
  let heldEvents: RuntimeEvent[] = [];
  let heldStats: ExecutionStats | null = null;
  let heldOutputText = "";
  let heldOutputIsError = false;
  let hasEvaluation = false;
  let debuggerState: DebuggerState = "idle";
  let tracePlayback: TracePlayback | null = null;
  let requestSeq = 0; // Prevent stale responses from overwriting newer state.
  let activeController: AbortController | null = null;
  let requestInFlight = false;
  let activeRequestKind: RequestKind | null = null;
  const initialPlaybackSpeed = Number.parseFloat(playbackSpeedEl.value);
  let playbackSpeed = (
    Number.isFinite(initialPlaybackSpeed) && initialPlaybackSpeed > 0
  )
    ? initialPlaybackSpeed
    : 1;
  playbackSpeedValueEl.textContent = `${playbackSpeed}×`;
  let playbackTimer: ReturnType<typeof setTimeout> | null = null;
  let chaosHighlightTimer: ReturnType<typeof setTimeout> | null = null;
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
    if (tracePlayback === null) {
      traceHighlightingContentEl.innerHTML = highlightActiveTraceSpan(
        sourceEl.value,
        null,
      );
    }
  }

  function syncEditorScroll(): void {
    highlightingEl.scrollTop = sourceEl.scrollTop;
    highlightingEl.scrollLeft = sourceEl.scrollLeft;
    traceHighlightingEl.scrollTop = sourceEl.scrollTop;
    traceHighlightingEl.scrollLeft = sourceEl.scrollLeft;
  }

  function revealTraceLine(span: SourceSpan | null): void {
    if (span === null) {
      return;
    }
    const computedStyle = document.defaultView?.getComputedStyle(sourceEl);
    if (computedStyle === undefined) {
      return;
    }
    const lineHeight = Number.parseFloat(computedStyle.lineHeight);
    const paddingTop = Number.parseFloat(computedStyle.paddingTop);
    if (!Number.isFinite(lineHeight) || !Number.isFinite(paddingTop)) {
      return;
    }
    sourceEl.scrollTop = scrollTopToRevealLine({
      line: span.start.line,
      scrollTop: sourceEl.scrollTop,
      viewportHeight: sourceEl.clientHeight,
      lineHeight,
      paddingTop,
    });
    syncEditorScroll();
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

      const exampleSource = await response.text();
      if (mySeq !== exampleRequestSeq) {
        return;
      }
      supersedeDebugWork("Trace stopped because the source changed.");
      sourceEl.value = exampleSource;
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
    supersedeDebugWork("Trace stopped because the source changed.");
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

  function updateChaosDisplay(
    threshold = heldState?.chaos_threshold ?? 1,
  ): void {
    const nextValue = String(threshold);
    if (chaosLevelEl.textContent === nextValue) {
      return;
    }

    chaosLevelEl.textContent = nextValue;
    if (chaosHighlightTimer !== null) {
      clearTimeout(chaosHighlightTimer);
    }
    runtimeStateEl.classList.toggle("chaos-changed", true);
    chaosHighlightTimer = setTimeout(() => {
      chaosHighlightTimer = null;
      runtimeStateEl.classList.toggle("chaos-changed", false);
    }, 500);
  }

  function renderInspector(): void {
    inspectorStateEl.textContent = formatState(heldState);
    inspectorEventsEl.textContent = heldEvents.length === 0
      ? "No runtime events."
      : heldEvents.map(formatEvent).join("\n");
    inspectorStatsEl.textContent = formatStats(heldStats, hasEvaluation);
    inspectorContextEl.textContent = "No trace loaded.";
  }

  function updateControlAvailability(): void {
    const playing = debuggerState === "playing";
    const playbackActive = playing || debuggerState === "paused";
    runBtn.disabled = requestInFlight;
    debugBtn.disabled = requestInFlight;
    restartBtn.disabled = (
      tracePlayback === null
      || (!playing && !tracePlayback.canStepBack)
    );
    stepBackBtn.disabled = (
      playing || tracePlayback === null || !tracePlayback.canStepBack
    );
    stepBtn.disabled = (
      playing || tracePlayback === null || !tracePlayback.canStepForward
    );
    stepOverBtn.disabled = playing || stepBtn.disabled;
    stepOutBtn.disabled = (
      playing || tracePlayback === null || !tracePlayback.canStepOut
    );
    playBtn.disabled = (
      tracePlayback === null
      || (!playing && !tracePlayback.canStepForward)
    );
    playIconEl.textContent = playing ? "⏸️" : "▶️";
    playLabelEl.textContent = playing ? "Pause" : "Play";
    playbackSpeedControlEl.hidden = !playbackActive;
    playbackSpeedEl.disabled = !playbackActive;
    stopBtn.disabled = debuggerState === "idle";
  }

  function setDebuggerStatus(state: DebuggerState, text: string): void {
    debuggerState = state;
    const liveMode = state === "playing" ? "off" : "polite";
    outputEl.setAttribute("aria-live", liveMode);
    runtimeStateEl.setAttribute("aria-live", liveMode);
    debugStatusEl.dataset.state = state;
    debugStatusEl.textContent = text;
    updateControlAvailability();
  }

  function restoreCommittedPresentation(message = "Debugger idle."): void {
    stopPlaybackTimer();
    tracePlayback = null;
    traceHighlightingContentEl.innerHTML = highlightActiveTraceSpan(
      sourceEl.value,
      null,
    );
    updateChaosDisplay();
    renderInspector();
    renderOutput(heldOutputText, heldOutputIsError);
    setDebuggerStatus("idle", message);
  }

  function traceStateForFrame(
    snapshot: TracePlaybackSnapshot,
  ): DebuggerState {
    if (snapshot.frame.status === "completed") {
      return "finished";
    }
    if (snapshot.frame.status === "error") {
      return "error";
    }
    return "paused";
  }

  function traceStatusText(snapshot: TracePlaybackSnapshot): string {
    const framePosition = `frame ${snapshot.frameIndex + 1} of ${
      snapshot.frameCount
    }`;
    if (snapshot.frame.status === "completed") {
      return `Trace finished at ${framePosition}.`;
    }
    if (snapshot.frame.status === "error") {
      return `Trace stopped with an error at ${framePosition}.`;
    }
    const line = snapshot.frame.active?.span.start.line;
    return line === undefined
      ? `Paused at ${framePosition}.`
      : `Paused at line ${line}, ${framePosition}.`;
  }

  function renderTraceSnapshot(updateStatus = true): void {
    const snapshot = tracePlayback?.current;
    if (snapshot === null || snapshot === undefined) {
      return;
    }

    traceHighlightingContentEl.innerHTML = highlightActiveTraceSpan(
      sourceEl.value,
      snapshot.frame.active?.span ?? null,
    );
    revealTraceLine(snapshot.frame.active?.span ?? null);
    updateChaosDisplay(snapshot.chaosThreshold);
    inspectorStateEl.textContent = formatTraceState(snapshot);
    if (snapshot.events.length === 0) {
      inspectorEventsEl.textContent = "No runtime events through this frame.";
    } else {
      const renderedEvents = snapshot.events.map(formatEvent);
      inspectorEventsEl.textContent = [
        "Events through this frame:",
        ...renderedEvents.map((event) => `  ${event}`),
        "",
        `Last event: ${renderedEvents.at(-1)}`,
      ].join("\n");
    }
    inspectorStatsEl.textContent = formatTraceStats(snapshot.frame);
    inspectorContextEl.textContent = formatTraceContext(snapshot);

    const diagnostic = tracePlayback?.diagnosticForCurrentFrame() ?? null;
    const outputLines = snapshot.outputValues.map(String);
    if (diagnostic !== null) {
      outputLines.push("", formatDiagnostic(diagnostic));
    }
    renderOutput(outputLines.join("\n"), diagnostic !== null);
    if (updateStatus) {
      setDebuggerStatus(
        traceStateForFrame(snapshot),
        traceStatusText(snapshot),
      );
    }
  }

  function stopPlaybackTimer(): void {
    if (playbackTimer !== null) {
      clearTimeout(playbackTimer);
      playbackTimer = null;
    }
  }

  function schedulePlaybackFrame(): void {
    stopPlaybackTimer();
    playbackTimer = setTimeout(() => {
      playbackTimer = null;
      if (debuggerState !== "playing" || tracePlayback === null) {
        return;
      }
      if (!tracePlayback.stepForward()) {
        renderTraceSnapshot();
        return;
      }

      const snapshot = tracePlayback.current;
      if (
        snapshot === null
        || snapshot.frame.status !== "paused"
        || !tracePlayback.canStepForward
      ) {
        renderTraceSnapshot();
        return;
      }
      renderTraceSnapshot(false);
      schedulePlaybackFrame();
    }, Math.round(PLAYBACK_FRAME_DELAY_MS / playbackSpeed));
  }

  function renderUnavailableTrace(result: TraceResult): void {
    tracePlayback = null;
    traceHighlightingContentEl.innerHTML = highlightActiveTraceSpan(
      sourceEl.value,
      null,
    );
    updateChaosDisplay();
    renderInspector();
    const message = result.diagnostics.length === 0
      ? "Trace artifact is unavailable."
      : result.diagnostics.map(formatDiagnostic).join("\n");
    renderOutput(message, true);
    setDebuggerStatus("error", "Trace artifact is unavailable.");
  }

  function forgetCommittedSession(): void {
    sessionId = null;
    heldState = null;
    heldEvents = [];
    heldStats = null;
    heldOutputText = "";
    heldOutputIsError = false;
    hasEvaluation = false;
    updateChaosDisplay();
    renderInspector();
  }

  function renderEmptyTrace(result: TraceResult): void {
    tracePlayback = null;
    traceHighlightingContentEl.innerHTML = highlightActiveTraceSpan(
      sourceEl.value,
      null,
    );
    updateChaosDisplay();
    renderInspector();
    const message = result.diagnostics.length === 0
      ? "Trace contains no execution frames."
      : result.diagnostics.map(formatDiagnostic).join("\n");
    renderOutput(message, true);
    setDebuggerStatus("error", "Trace could not begin.");
  }

  function supersedeDebugWork(debugMessage: string): void {
    if (activeRequestKind === "debug" && activeController !== null) {
      ++requestSeq;
      activeController.abort();
      activeController = null;
      activeRequestKind = null;
      requestInFlight = false;
    }
    if (debuggerState !== "idle" || tracePlayback !== null) {
      restoreCommittedPresentation(debugMessage);
    } else {
      updateControlAvailability();
    }
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

  restartBtn.addEventListener("click", () => {
    if (tracePlayback === null) {
      return;
    }
    stopPlaybackTimer();
    tracePlayback.restart();
    renderTraceSnapshot();
  });

  stepBackBtn.addEventListener("click", () => {
    if (
      debuggerState !== "playing"
      && tracePlayback?.stepBack() === true
    ) {
      renderTraceSnapshot();
    }
  });

  stepBtn.addEventListener("click", () => {
    if (
      debuggerState !== "playing"
      && tracePlayback?.stepForward() === true
    ) {
      renderTraceSnapshot();
    }
  });

  stepOverBtn.addEventListener("click", () => {
    if (
      debuggerState !== "playing"
      && tracePlayback?.stepOver() === true
    ) {
      renderTraceSnapshot();
    }
  });

  stepOutBtn.addEventListener("click", () => {
    if (
      debuggerState !== "playing"
      && tracePlayback?.stepOut() === true
    ) {
      renderTraceSnapshot();
    }
  });

  playBtn.addEventListener("click", () => {
    if (debuggerState === "playing") {
      stopPlaybackTimer();
      renderTraceSnapshot();
      return;
    }
    if (tracePlayback === null || !tracePlayback.canStepForward) {
      return;
    }
    setDebuggerStatus("playing", "Playing trace…");
    schedulePlaybackFrame();
  });

  playbackSpeedEl.addEventListener("input", () => {
    const selectedSpeed = Number.parseFloat(playbackSpeedEl.value);
    if (!Number.isFinite(selectedSpeed) || selectedSpeed <= 0) {
      return;
    }
    playbackSpeed = selectedSpeed;
    playbackSpeedValueEl.textContent = `${selectedSpeed}×`;
    if (debuggerState === "playing") {
      schedulePlaybackFrame();
    }
  });

  stopBtn.addEventListener("click", () => {
    supersedeDebugWork("Trace stopped.");
  });

  resetBtn.addEventListener("click", async () => {
    ++requestSeq;
    if (activeController !== null) {
      activeController.abort();
      activeController = null;
    }
    activeRequestKind = null;
    requestInFlight = false;
    const resetSessionId = sessionId;
    sessionId = null;
    heldState = null;
    heldEvents = [];
    heldStats = null;
    heldOutputText = "";
    heldOutputIsError = false;
    hasEvaluation = false;
    restoreCommittedPresentation();

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
    if (debuggerState !== "idle" || tracePlayback !== null) {
      restoreCommittedPresentation();
    }
    const mySeq = ++requestSeq;
    const controller = new AbortController();
    activeController = controller;
    activeRequestKind = "evaluate";
    requestInFlight = true;
    updateControlAvailability();

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
        if (response.status === 404 || response.status === 409) {
          forgetCommittedSession();
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
        heldOutputText = result.values.map(String).join("\n");
        heldOutputIsError = false;
      } else {
        heldOutputText = result.diagnostics.map(formatDiagnostic).join("\n");
        heldOutputIsError = true;
      }
      renderOutput(heldOutputText, heldOutputIsError);
    } finally {
      if (mySeq === requestSeq) {
        activeController = null;
        activeRequestKind = null;
        requestInFlight = false;
        updateControlAvailability();
      }
    }
  });

  debugBtn.addEventListener("click", async () => {
    if (debuggerState !== "idle" || tracePlayback !== null) {
      restoreCommittedPresentation();
    }
    const mySeq = ++requestSeq;
    const controller = new AbortController();
    activeController = controller;
    activeRequestKind = "debug";
    requestInFlight = true;
    setDebuggerStatus("loading", "Recording bounded trace…");

    try {
      const payload: EvaluateRequest = { source: sourceEl.value };
      if (sessionId !== null) {
        payload.session_id = sessionId;
      }

      let response;
      try {
        response = await fetch("/debug", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
      } catch (networkError) {
        if (!isAbortError(networkError) && mySeq === requestSeq) {
          renderOutput(`Network error: ${networkError}`, true);
          setDebuggerStatus("error", "Debug request failed.");
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
        if (response.status === 404 || response.status === 409) {
          forgetCommittedSession();
        }
        renderOutput(`Request rejected (${response.status}): ${detail}`, true);
        setDebuggerStatus("error", `Debug request rejected (${response.status}).`);
        return;
      }

      const result = await response.json() as TraceResult;
      if (mySeq !== requestSeq) {
        return;
      }
      sessionId = result.session_id;
      if (!result.artifact_available || result.base_state === null) {
        renderUnavailableTrace(result);
        return;
      }
      if (result.frames.length === 0) {
        renderEmptyTrace(result);
        return;
      }

      try {
        tracePlayback = new TracePlayback(result);
      } catch (_) {
        renderOutput("The server returned an invalid trace artifact.", true);
        setDebuggerStatus("error", "Trace artifact is invalid.");
        return;
      }
      renderTraceSnapshot();
    } finally {
      if (mySeq === requestSeq) {
        activeController = null;
        activeRequestKind = null;
        requestInFlight = false;
        updateControlAvailability();
      }
    }
  });

  updateEditorHighlighting();
  updateSourcePosition();
  applyEditorTheme(initialEditorTheme());
  applyPageTheme(initialPageTheme());

  scheduleValidation();
  setDebuggerStatus("idle", "Debugger idle.");
}
