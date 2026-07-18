#!/bin/sh
set -eu

# Smoke-test a running RUNE web deployment without requiring jq.
#
# Examples:
#   scripts/deploy-smoke-test.sh
#   BASE_URL=https://rune.tjreigh.mobi scripts/deploy-smoke-test.sh

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
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

echo "Checking $BASE_URL/ ..."
# shellcheck disable=SC2086
curl $CURL_FLAGS "$BASE_URL/" > "$TMP_DIR/index.html"
grep -q '<title>RUNE Web REPL</title>' "$TMP_DIR/index.html"

echo "Checking static assets ..."
# shellcheck disable=SC2086
curl $CURL_FLAGS "$BASE_URL/static/style.css" > /dev/null
# shellcheck disable=SC2086
curl $CURL_FLAGS "$BASE_URL/static/app.js" > /dev/null

echo "Evaluating 2+2 ..."
# shellcheck disable=SC2086
curl $CURL_FLAGS \
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

echo "RUNE smoke test passed: $BASE_URL"
