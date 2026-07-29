#!/bin/sh
set -eu

# Smoke-test a running RUNE web deployment without requiring jq.
#
# Examples:
#   scripts/deploy-smoke-test.sh
#   BASE_URL=https://rune.tjreigh.mobi scripts/deploy-smoke-test.sh
#   BASE_URL=http://localhost CURL_SOCKET=/run/rune/rune.sock \
#     scripts/deploy-smoke-test.sh

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
CURL_SOCKET="${CURL_SOCKET:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BASE_URL="${BASE_URL%/}"

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    echo "Usage: [BASE_URL=https://rune.tjreigh.mobi] [PYTHON_BIN=python3] $0"
    exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required for the deployment smoke test." >&2
    exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 && [ ! -x "$PYTHON_BIN" ]; then
    echo "Python executable not found: $PYTHON_BIN" >&2
    exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

CURL_FLAGS="--fail --silent --show-error --connect-timeout 3 --max-time 10 --retry 10 --retry-delay 1 --retry-connrefused"

if [ -n "$CURL_SOCKET" ]; then
    attempt=0
    while [ ! -S "$CURL_SOCKET" ]; do
        attempt=$((attempt + 1))
        if [ "$attempt" -ge 30 ]; then
            echo "Unix socket did not become ready: $CURL_SOCKET" >&2
            exit 1
        fi
        sleep 1
    done
fi

run_curl() {
    if [ -n "$CURL_SOCKET" ]; then
        # shellcheck disable=SC2086
        curl $CURL_FLAGS --unix-socket "$CURL_SOCKET" "$@"
    else
        # shellcheck disable=SC2086
        curl $CURL_FLAGS "$@"
    fi
}

echo "Checking $BASE_URL/ ..."
run_curl "$BASE_URL/" > /dev/null

echo "Checking static assets ..."
run_curl "$BASE_URL/static/style.css" > /dev/null
run_curl "$BASE_URL/static/build/app.js" > /dev/null

echo "Checking compile-only validation ..."
run_curl \
    -H 'content-type: application/json' \
    -d '{"source":"function answer()\nreturn 42\nend function\nanswer()"}' \
    "$BASE_URL/validate" > "$TMP_DIR/valid.json"
run_curl \
    -H 'content-type: application/json' \
    -d '{"source":"return 1"}' \
    "$BASE_URL/validate" > "$TMP_DIR/invalid.json"

"$PYTHON_BIN" - "$TMP_DIR/valid.json" "$TMP_DIR/invalid.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as response_file:
    valid = json.load(response_file)
with open(sys.argv[2], encoding="utf-8") as response_file:
    invalid = json.load(response_file)

if valid != {"ok": True, "diagnostics": []}:
    raise SystemExit(f"valid source failed validation: {valid}")
if invalid.get("ok") is not False:
    raise SystemExit(f"invalid source passed validation: {invalid}")
diagnostics = invalid.get("diagnostics", [])
if not diagnostics or diagnostics[0].get("kind") != "parse":
    raise SystemExit(f"expected a parse diagnostic: {invalid}")
PY

echo "Evaluating 2+2 ..."
run_curl \
    -H 'content-type: application/json' \
    -d '{"source":"2+2"}' \
    "$BASE_URL/evaluate" > "$TMP_DIR/evaluation.json"

"$PYTHON_BIN" - "$TMP_DIR/evaluation.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as response_file:
    response = json.load(response_file)

if response.get("ok") is not True:
    raise SystemExit(f"evaluation failed: {response}")
if response.get("values") != [4]:
    raise SystemExit(f"expected values [4], received: {response.get('values')}")
if response.get("state") != {"chaos_threshold": 1}:
    raise SystemExit(f"unexpected default state: {response.get('state')}")
PY

echo "Evaluating a recursive function ..."
run_curl \
    -H 'content-type: application/json' \
    -d '{"source":"function factorial(n)\nif (n <= 1)\nreturn 1\nend if\nreturn n * factorial(n - 1)\nend function\nfactorial(5)"}' \
    "$BASE_URL/evaluate" > "$TMP_DIR/function.json"

"$PYTHON_BIN" - "$TMP_DIR/function.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as response_file:
    response = json.load(response_file)

if response.get("ok") is not True or response.get("values") != [120]:
    raise SystemExit(f"recursive function evaluation failed: {response}")
PY

echo "Evaluating scoped chaos ..."
run_curl \
    -H 'content-type: application/json' \
    -d '{"source":"@chaos 2\nchaos 500\nnot 2\nend chaos\nnot 2"}' \
    "$BASE_URL/evaluate" > "$TMP_DIR/scoped-chaos.json"

"$PYTHON_BIN" - \
    "$TMP_DIR/scoped-chaos.json" \
    "$TMP_DIR/debug-request.json" \
    "$TMP_DIR/session-probe-request.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as response_file:
    response = json.load(response_file)

if response.get("ok") is not True or response.get("values") != [1, 0]:
    raise SystemExit(f"scoped chaos evaluation failed: {response}")
if response.get("state") != {"chaos_threshold": 2}:
    raise SystemExit(f"scoped chaos did not restore state: {response}")
session_id = response.get("session_id")
if not isinstance(session_id, str) or not session_id:
    raise SystemExit(f"scoped chaos response has no session ID: {response}")

with open(sys.argv[2], "w", encoding="utf-8") as request_file:
    json.dump(
        {
            "source": (
                "chaos 500\n"
                "preview = 9\n"
                "not 2\n"
                "end chaos\n"
                "not 2"
            ),
            "session_id": session_id,
        },
        request_file,
    )
with open(sys.argv[3], "w", encoding="utf-8") as request_file:
    json.dump({"source": "not 2", "session_id": session_id}, request_file)
PY

echo "Recording a non-committing debug trace ..."
run_curl \
    -H 'content-type: application/json' \
    --data-binary "@$TMP_DIR/debug-request.json" \
    "$BASE_URL/debug" > "$TMP_DIR/debug.json"

"$PYTHON_BIN" - "$TMP_DIR/scoped-chaos.json" "$TMP_DIR/debug.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as response_file:
    evaluation = json.load(response_file)
with open(sys.argv[2], encoding="utf-8") as response_file:
    debug = json.load(response_file)

if debug.get("ok") is not True or debug.get("artifact_available") is not True:
    raise SystemExit(f"debug trace failed: {debug}")
if debug.get("diagnostics") != []:
    raise SystemExit(f"debug trace returned diagnostics: {debug}")
if debug.get("session_id") != evaluation.get("session_id"):
    raise SystemExit(f"debug trace changed sessions: {debug}")
if debug.get("base_state") != {"chaos_threshold": 2}:
    raise SystemExit(f"debug trace used the wrong base state: {debug}")
frames = debug.get("frames")
if not isinstance(frames, list) or not frames:
    raise SystemExit(f"debug trace has no frames: {debug}")
if frames[-1].get("status") != "completed":
    raise SystemExit(f"debug trace did not complete: {debug}")
thresholds = {
    change["after"]
    for frame in frames
    if isinstance(frame.get("changes"), dict)
    if isinstance(
        change := frame["changes"].get("chaos_threshold"),
        dict,
    )
}
if not {2, 500}.issubset(thresholds):
    raise SystemExit(f"debug trace omitted chaos transitions: {debug}")
PY

echo "Confirming debug did not commit session state ..."
run_curl \
    -H 'content-type: application/json' \
    --data-binary "@$TMP_DIR/session-probe-request.json" \
    "$BASE_URL/evaluate" > "$TMP_DIR/session-probe.json"

"$PYTHON_BIN" - "$TMP_DIR/scoped-chaos.json" "$TMP_DIR/session-probe.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as response_file:
    evaluation = json.load(response_file)
with open(sys.argv[2], encoding="utf-8") as response_file:
    probe = json.load(response_file)

if probe.get("ok") is not True or probe.get("values") != [0]:
    raise SystemExit(f"post-debug session probe failed: {probe}")
if probe.get("session_id") != evaluation.get("session_id"):
    raise SystemExit(f"post-debug session probe changed sessions: {probe}")
if probe.get("state") != {"chaos_threshold": 2}:
    raise SystemExit(f"debug committed working state: {probe}")
PY

echo "RUNE smoke test passed: $BASE_URL"
