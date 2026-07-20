#!/bin/sh
set -eu

# Render and install RUNE's systemd service and Caddy site snippet.
# This intentionally does not modify /etc/caddy/Caddyfile or start services
# unless ACTIVATE=1 is explicitly supplied.
#
# Required:
#   sudo DOMAIN=rune.tjreigh.mobi scripts/deploy-install-config.sh
#
# Optional:
#   APP_DIR=/srv/rune/app
#   SERVICE_USER=rune
#   SERVICE_NAME=rune
#   ACTIVATE=1

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this script as root, normally with sudo." >&2
    exit 1
fi

DOMAIN="${DOMAIN:-}"
APP_DIR="${APP_DIR:-/srv/rune/app}"
SERVICE_USER="${SERVICE_USER:-rune}"
SERVICE_NAME="${SERVICE_NAME:-rune}"
ACTIVATE="${ACTIVATE:-0}"

case "$DOMAIN" in
    ""|*[!A-Za-z0-9.-]*)
        echo "DOMAIN must be a plain DNS name, for example rune.tjreigh.mobi." >&2
        exit 1
        ;;
esac

case "$APP_DIR" in
    ""|*[!A-Za-z0-9_./-]*)
        echo "APP_DIR contains unsupported characters: $APP_DIR" >&2
        exit 1
        ;;
esac

case "$SERVICE_USER:$SERVICE_NAME" in
    *[!A-Za-z0-9_.:-]*)
        echo "SERVICE_USER or SERVICE_NAME contains unsupported characters." >&2
        exit 1
        ;;
esac

for command in awk caddy install sed systemctl systemd-analyze; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Required command not found: $command" >&2
        exit 1
    fi
done

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    echo "Service user does not exist: $SERVICE_USER" >&2
    exit 1
fi

if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
    echo "Deployment virtual environment not found: $APP_DIR/.venv" >&2
    exit 1
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
SERVICE_TEMPLATE="$REPO_ROOT/deploy/rune.service"
CADDY_TEMPLATE="$REPO_ROOT/deploy/rune.caddy"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
CADDY_SITE="/etc/caddy/$SERVICE_NAME.caddy"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

sed \
    -e "s|@@APP_DIR@@|$APP_DIR|g" \
    -e "s|@@SERVICE_USER@@|$SERVICE_USER|g" \
    "$SERVICE_TEMPLATE" > "$TMP_DIR/$SERVICE_NAME.service"

sed \
    -e "s|@@DOMAIN@@|$DOMAIN|g" \
    "$CADDY_TEMPLATE" > "$TMP_DIR/$SERVICE_NAME.caddy"

caddy fmt --overwrite "$TMP_DIR/$SERVICE_NAME.caddy"
systemd-analyze verify "$TMP_DIR/$SERVICE_NAME.service"
caddy validate --config "$TMP_DIR/$SERVICE_NAME.caddy" --adapter caddyfile

install -o root -g root -m 0644 \
    "$TMP_DIR/$SERVICE_NAME.service" "$SERVICE_FILE"
install -o root -g root -m 0644 \
    "$TMP_DIR/$SERVICE_NAME.caddy" "$CADDY_SITE"
systemctl daemon-reload

echo "Installed:"
echo "  $SERVICE_FILE"
echo "  $CADDY_SITE"
echo
echo "Ensure /etc/caddy/Caddyfile contains this line:"
echo "  import $CADDY_SITE"

if [ "$ACTIVATE" != "1" ]; then
    echo
    echo "Nothing was started. After adding the import, validate and activate:"
    echo "  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile"
    echo "  systemctl enable --now $SERVICE_NAME.service"
    echo "  systemctl reload caddy"
    exit 0
fi

if ! awk -v site="$CADDY_SITE" \
    '$1 == "import" && $2 == site && NF == 2 { found = 1 }
     END { exit !found }' \
    /etc/caddy/Caddyfile; then
    echo "ACTIVATE=1 requested, but /etc/caddy/Caddyfile does not import:" >&2
    echo "  $CADDY_SITE" >&2
    exit 1
fi

caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl enable --now "$SERVICE_NAME.service"
systemctl reload caddy

BASE_URL=http://127.0.0.1:8000 \
PYTHON_BIN="$APP_DIR/.venv/bin/python" \
    "$APP_DIR/scripts/deploy-smoke-test.sh"

echo "Deployment configuration installed and activated for $DOMAIN."
