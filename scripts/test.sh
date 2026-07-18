#!/bin/sh
set -e

# Runs the test suite. Any arguments are passed through to pytest, e.g.:
#   scripts/test.sh -k isolation
#   scripts/test.sh -v tests/test_web_app.py

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -x .venv/bin/python ]; then
    echo ".venv not found. Run scripts/setup.sh first." >&2
    exit 1
fi

export DYLD_LIBRARY_PATH="/opt/homebrew/opt/expat/lib"
exec .venv/bin/python -m pytest "$@"
