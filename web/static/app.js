const EXAMPLES = {
  smoke: "2+2",
  chaos: `"dog" + "cat"

@chaos 1
if ("dog" > "cat")
1
else
0
end

@chaos 500
if ("dog" > "cat")
1
else
0
end
`,
  full: `2+2
"dog" + "cat"
@chaos 1
if ("dog" > "cat")
1
else
0
end
if (0)
0
elif (2)
2
else
0
end
@chaos 500
if ("dog" > "cat")
1
else
0
end
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

let heldState = null; // Last RuntimeState returned by the stateless server.
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

function updateChaosDisplay() {
  const threshold = heldState?.chaos_threshold ?? 1;
  chaosLevelEl.textContent = String(threshold);
}

resetBtn.addEventListener("click", () => {
  ++requestSeq;
  if (activeController !== null) {
    activeController.abort();
    activeController = null;
  }
  heldState = null;
  updateChaosDisplay();
  runBtn.disabled = false;
  renderOutput("");
});

runBtn.addEventListener("click", async () => {
  const mySeq = ++requestSeq;
  const controller = new AbortController();
  activeController = controller;
  runBtn.disabled = true;

  try {
    const payload = { source: sourceEl.value };
    if (heldState !== null) {
      payload.state = heldState;
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
        detail = body.detail || JSON.stringify(body);
      } catch (_) {
        // The status text is the best fallback for a non-JSON error body.
      }
      renderOutput(`Request rejected (${response.status}): ${detail}`, true);
      return;
    }

    const result = await response.json();
    heldState = result.state;
    updateChaosDisplay();
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
