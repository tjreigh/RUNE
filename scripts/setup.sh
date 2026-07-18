#!/bin/sh
set -e

# One-time local dev environment setup for RUNE (macOS + Homebrew).
#
# Homebrew's python@3.12 bottle on this machine links pyexpat against a
# newer libexpat than macOS provides, so venv creation (and every later
# invocation of that venv's Python) needs Homebrew's expat on the dynamic
# linker's search path -- see README.md's "Homebrew troubleshooting"
# section for the underlying issue. This script handles it for you.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v python3.12 >/dev/null 2>&1; then
    echo "python3.12 not found. Install it first: brew install python@3.12" >&2
    exit 1
fi

if ! brew list expat >/dev/null 2>&1; then
    echo "Homebrew's expat not found. Install it first: brew install expat" >&2
    exit 1
fi

export DYLD_LIBRARY_PATH="/opt/homebrew/opt/expat/lib"

if [ ! -d .venv ]; then
    echo "Creating .venv..."
    python3.12 -m venv .venv
else
    echo ".venv already exists, skipping creation."
fi

echo "Installing dev + web dependencies..."
.venv/bin/python -m pip install -e ".[dev,web]"

echo
echo "Done. Try:"
echo "  scripts/test.sh       # run the test suite"
echo "  scripts/run-web.sh    # start the local web REPL"
