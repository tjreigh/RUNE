#!/bin/sh
set -u

# Update an existing Linux/systemd RUNE deployment to a Git ref.
#
# The deployment checkout must be clean. The script deploys the requested
# commit, reinstalls the web extra, validates the environment, restarts the
# service, and runs a smoke test. If any step fails, it restores and verifies
# the previous commit before exiting non-zero.
#
# Usage:
#   sudo scripts/deploy-update.sh                    # deploy origin/main
#   sudo scripts/deploy-update.sh v0.4.0             # deploy a tag
#   sudo scripts/deploy-update.sh 0123456789abcdef    # deploy an exact SHA
#
# Configuration is available through environment variables:
#   APP_DIR=/srv/rune/app
#   SERVICE_USER=rune
#   SERVICE_NAME=rune
#   DOMAIN=rune.tjreigh.mobi
#   REMOTE=origin
#   LOCAL_URL=http://127.0.0.1:8000

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    sed -n '3,22p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
fi

APP_DIR="${APP_DIR:-/srv/rune/app}"
SERVICE_USER="${SERVICE_USER:-rune}"
SERVICE_NAME="${SERVICE_NAME:-rune}"
DOMAIN="${DOMAIN:-}"
REMOTE="${REMOTE:-origin}"
LOCAL_URL="${LOCAL_URL:-http://127.0.0.1:8000}"
DEPLOY_REF="${1:-$REMOTE/main}"
PYTHON_BIN="$APP_DIR/.venv/bin/python"
SMOKE_SCRIPT="$APP_DIR/scripts/deploy-smoke-test.sh"
CADDY_SITE="/etc/caddy/$SERVICE_NAME.caddy"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this script as root, normally with sudo." >&2
    exit 1
fi

for command in git sudo systemctl; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Required command not found: $command" >&2
        exit 1
    fi
done

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    echo "Service user does not exist: $SERVICE_USER" >&2
    exit 1
fi

if [ ! -d "$APP_DIR/.git" ]; then
    echo "Deployment checkout not found: $APP_DIR" >&2
    exit 1
fi

if [ ! -x "$PYTHON_BIN" ]; then
    echo "Deployment virtual environment not found: $PYTHON_BIN" >&2
    exit 1
fi

if [ ! -x "$SMOKE_SCRIPT" ]; then
    echo "Smoke-test script missing or not executable: $SMOKE_SCRIPT" >&2
    exit 1
fi

# Reuse the domain from the installed, rendered site when the operator does
# not supply DOMAIN explicitly. This lets normal updates reinstall changed
# service and proxy templates instead of silently leaving deployment policy
# stale.
if [ -z "$DOMAIN" ] && [ -r "$CADDY_SITE" ]; then
    DOMAIN="$(
        sed -n 's/^\([A-Za-z0-9][A-Za-z0-9.-]*\) {$/\1/p' "$CADDY_SITE" |
            sed -n '1p'
    )"
fi

case "$DOMAIN" in
    ""|*[!A-Za-z0-9.-]*)
        echo "Unable to determine the deployment domain." >&2
        echo "Set DOMAIN explicitly, for example DOMAIN=rune.example.com." >&2
        exit 1
        ;;
esac

# Keep a private copy outside the checkout so rollback verification still
# works even when the target or previous commit predates these helper scripts.
SMOKE_RUNNER="$(mktemp)" || exit 1
trap 'rm -f "$SMOKE_RUNNER"' EXIT HUP INT TERM
cp "$SMOKE_SCRIPT" "$SMOKE_RUNNER" || exit 1
chmod 700 "$SMOKE_RUNNER" || exit 1

run_as_service() {
    sudo -u "$SERVICE_USER" "$@"
}

if [ -n "$(run_as_service git -C "$APP_DIR" status --porcelain)" ]; then
    echo "Refusing to deploy over a dirty checkout: $APP_DIR" >&2
    run_as_service git -C "$APP_DIR" status --short >&2
    exit 1
fi

PREVIOUS_COMMIT="$(run_as_service git -C "$APP_DIR" rev-parse HEAD)" || exit 1

echo "Fetching $REMOTE ..."
if ! run_as_service git -C "$APP_DIR" fetch --prune "$REMOTE"; then
    echo "Git fetch failed; the running deployment was not changed." >&2
    exit 1
fi

TARGET_COMMIT="$(run_as_service git -C "$APP_DIR" rev-parse --verify "$DEPLOY_REF^{commit}")" || {
    echo "Unable to resolve deployment ref: $DEPLOY_REF" >&2
    exit 1
}

deploy_commit() {
    commit="$1"

    echo "Checking out $commit ..."
    run_as_service git -C "$APP_DIR" checkout --detach "$commit" || return 1

    echo "Installing RUNE web dependencies ..."
    run_as_service "$PYTHON_BIN" -m pip install \
        --disable-pip-version-check \
        -e "$APP_DIR[web]" || return 1

    echo "Validating installed dependencies and application imports ..."
    run_as_service "$PYTHON_BIN" -m pip check || return 1
    run_as_service env PYTHONPATH="$APP_DIR/web" \
        "$PYTHON_BIN" -c 'import app' || return 1

    echo "Installing and validating deployment configuration ..."
    DOMAIN="$DOMAIN" \
    APP_DIR="$APP_DIR" \
    SERVICE_USER="$SERVICE_USER" \
    SERVICE_NAME="$SERVICE_NAME" \
    ACTIVATE=0 \
        "$APP_DIR/scripts/deploy-install-config.sh" || return 1

    if ! awk -v site="$CADDY_SITE" \
        '$1 == "import" && $2 == site && NF == 2 { found = 1 }
         END { exit !found }' \
        /etc/caddy/Caddyfile; then
        echo "The operator-owned Caddyfile does not import $CADDY_SITE." >&2
        return 1
    fi

    echo "Validating the complete operator-owned Caddy configuration ..."
    caddy validate \
        --config /etc/caddy/Caddyfile \
        --adapter caddyfile || return 1

    echo "Restarting $SERVICE_NAME.service ..."
    systemctl restart "$SERVICE_NAME.service" || return 1
    systemctl is-active --quiet "$SERVICE_NAME.service" || return 1
    systemctl reload caddy.service || return 1

    BASE_URL="$LOCAL_URL" PYTHON_BIN="$PYTHON_BIN" "$SMOKE_RUNNER"
}

echo "Deploying $DEPLOY_REF ($TARGET_COMMIT); previous commit: $PREVIOUS_COMMIT"
if deploy_commit "$TARGET_COMMIT"; then
    echo "Deployment succeeded: $TARGET_COMMIT"
    exit 0
fi

echo "Deployment failed; rolling back to $PREVIOUS_COMMIT ..." >&2
if deploy_commit "$PREVIOUS_COMMIT"; then
    echo "Rollback succeeded; $SERVICE_NAME.service is running the previous release." >&2
    exit 1
fi

echo "ROLLBACK FAILED. Inspect the service immediately:" >&2
echo "  systemctl status $SERVICE_NAME.service" >&2
echo "  journalctl -u $SERVICE_NAME.service -n 100 --no-pager" >&2
exit 2
