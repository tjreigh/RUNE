const EXAMPLES = {
  smoke: "2+2",
  variables: `animal = "cat"
score = animal + 1
score
`,
  expressions: `0b101010
(2 + 3) ** 2
-17 / 5
-17 % 5
(0b1010 << 2 | 0b0011) ^ 1
`,
  logic: `@chaos 1
0 and missing
5 or missing
not 0

@chaos 10
5 or 20
if (5 or 20)
99
else
0
end if
`,
  chaos: `"dog" + "cat"

@chaos 1
if ("dog" > "cat")
1
else
0
end if

@chaos 500
if ("dog" > "cat")
1
else
0
end if
`,
  full: `answer = 40
answer = answer + 2
answer
0b101010
(2 + 3) ** 2
-17 / 5
-17 % 5
(0b1010 << 2 | 0b0011) ^ 1
"dog" + "cat"
@chaos 1
0 and missing
5 or missing
not 0
if ("dog" > "cat")
1
else
0
end if
if (0)
0
elif (2)
2
else
0
end if
@chaos 10
5 or 20
if (5 or 20)
99
else
0
end if
`,
};

const KIND_LABELS = {
  lex: "Lex error",
  parse: "Parse error",
  runtime: "Runtime error",
  internal: "Internal error",
  limit: "Execution limit",
};

const sourceEl = document.getElementById("source");
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

examplesEl.addEventListener("change", () => {
  const key = examplesEl.value;
  if (key && EXAMPLES[key] !== undefined) {
    sourceEl.value = EXAMPLES[key];
  }
  examplesEl.value = "";
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
