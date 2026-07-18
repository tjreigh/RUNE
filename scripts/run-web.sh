#!/bin/sh
set -e

# Runs the local RUNE web REPL prototype (v0.3 -- see ROADMAP.md/
# ARCHITECTURE.md). Open http://127.0.0.1:8000/ once uvicorn prints
# "Application startup complete."
#
# Set PORT to use a different port, e.g. PORT=8080 scripts/run-web.sh

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -x .venv/bin/python ]; then
    echo ".venv not found. Run scripts/setup.sh first." >&2
    exit 1
fi

export DYLD_LIBRARY_PATH="/opt/homebrew/opt/expat/lib"
exec .venv/bin/python -m uvicorn app:app --app-dir web --port "${PORT:-8000}"
