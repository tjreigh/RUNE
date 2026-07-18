#!/bin/sh
set -e

# One-time local development environment setup. Set PYTHON_BIN to choose a
# specific interpreter; otherwise the first Python 3.12+ candidate is used.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ -d /opt/homebrew/opt/expat/lib ]; then
    export DYLD_LIBRARY_PATH="/opt/homebrew/opt/expat/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
fi

if [ -n "${PYTHON_BIN:-}" ]; then
    PYTHON_CANDIDATES="$PYTHON_BIN"
else
    PYTHON_CANDIDATES="python3 python3.14 python3.13 python3.12"
fi

PYTHON_BIN=""
for candidate in $PYTHON_CANDIDATES; do
    if command -v "$candidate" >/dev/null 2>&1 && \
        "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))'; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "Python 3.12 or newer was not found. Set PYTHON_BIN to its executable." >&2
    exit 1
fi

if [ ! -d .venv ]; then
    echo "Creating .venv..."
    "$PYTHON_BIN" -m venv .venv
else
    echo ".venv already exists, skipping creation."
fi

echo "Installing dev + web dependencies..."
.venv/bin/python -m pip install -e ".[dev,web]"

echo
echo "Done. Try:"
echo "  scripts/test.sh       # run the test suite"
echo "  scripts/run-web.sh    # start the local web REPL"
