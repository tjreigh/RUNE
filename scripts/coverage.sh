#!/bin/sh
set -e

# Runs the full test suite with line and branch coverage. Any arguments are
# passed through to pytest, so a focused report can use -k or a test path.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -x .venv/bin/python ]; then
    echo ".venv not found. Run scripts/setup.sh first." >&2
    exit 1
fi

if [ ! -x node_modules/.bin/tsc ]; then
    echo "Frontend dependencies not found. Run scripts/setup.sh first." >&2
    exit 1
fi

yarn typecheck
yarn build

if [ -d /opt/homebrew/opt/expat/lib ]; then
    export DYLD_LIBRARY_PATH="/opt/homebrew/opt/expat/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
fi

if ! .venv/bin/python -c 'import pytest_cov' >/dev/null 2>&1; then
    echo "pytest-cov not found. Run scripts/setup.sh to install dev dependencies." >&2
    exit 1
fi

exec .venv/bin/python -m pytest \
    --cov=src \
    --cov-branch \
    --cov-report=term-missing \
    --cov-report=html \
    "$@"
