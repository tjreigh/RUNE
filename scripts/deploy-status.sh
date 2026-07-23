#!/bin/sh
set -eu

# Show service status and exercise the local deployment. Set PUBLIC_URL to
# smoke-test the Caddy/TLS endpoint too:
#   PUBLIC_URL=https://rune.tjreigh.mobi scripts/deploy-status.sh

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    echo "Usage: [PUBLIC_URL=https://rune.tjreigh.mobi] $0"
    echo "Optional: APP_DIR, SERVICE_NAME, LOCAL_URL, CURL_SOCKET, PYTHON_BIN"
    exit 0
fi

APP_DIR="${APP_DIR:-/srv/rune/current}"
SERVICE_NAME="${SERVICE_NAME:-rune}"
LOCAL_URL="${LOCAL_URL:-http://localhost}"
CURL_SOCKET="${CURL_SOCKET:-/run/$SERVICE_NAME/rune.sock}"
PUBLIC_URL="${PUBLIC_URL:-}"
# The status helper may inspect an untrusted target release. Never run its
# virtualenv interpreter with the caller's (possibly root) privileges.
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
SMOKE_SCRIPT="$APP_DIR/scripts/deploy-smoke-test.sh"

if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl is required; this helper is intended for the Linux VPS." >&2
    exit 1
fi

echo "Service: $SERVICE_NAME.service"
systemctl is-active "$SERVICE_NAME.service"
systemctl --no-pager --full status "$SERVICE_NAME.service" | sed -n '1,12p'

if [ ! -x "$SMOKE_SCRIPT" ]; then
    echo "Smoke-test script missing or not executable: $SMOKE_SCRIPT" >&2
    exit 1
fi

echo
BASE_URL="$LOCAL_URL" CURL_SOCKET="$CURL_SOCKET" \
    PYTHON_BIN="$PYTHON_BIN" "$SMOKE_SCRIPT"

if [ -n "$PUBLIC_URL" ]; then
    echo
    BASE_URL="$PUBLIC_URL" CURL_SOCKET= \
        PYTHON_BIN="$PYTHON_BIN" "$SMOKE_SCRIPT"
fi
