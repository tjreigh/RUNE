#!/bin/sh
set -eu

# Install reviewed RUNE systemd/Caddy policy from a root-owned template copy.
#
# SECURITY: never run this file directly from the deployment checkout. Review
# and install this helper and its templates first; see deploy/README.md.

PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

INSTALL_PATH="${RUNE_POLICY_INSTALL_PATH:-/usr/local/sbin/rune-install-policy}"
TEMPLATE_DIR="${RUNE_POLICY_TEMPLATE_DIR:-/usr/local/share/rune-deploy}"
DOMAIN="${DOMAIN:-}"
APP_DIR="${APP_DIR:-/srv/rune/current}"
SERVICE_USER="${SERVICE_USER:-rune}"
SERVICE_NAME="${SERVICE_NAME:-rune}"
PROXY_GROUP="${PROXY_GROUP:-rune-proxy}"
ACTIVATE="${ACTIVATE:-0}"

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    sed -n '3,7p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
fi

fail() {
    echo "rune-install-policy: $*" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || fail "run the installed helper as root"
SCRIPT_PATH="$(readlink -f "$0")"
[ "$SCRIPT_PATH" = "$INSTALL_PATH" ] ||
    fail "install this helper at $INSTALL_PATH before running it as root"
[ "$(stat -c '%u:%a' "$SCRIPT_PATH")" = "0:755" ] ||
    fail "$INSTALL_PATH must be owned by root with mode 0755"

case "$DOMAIN" in
    ""|*[!A-Za-z0-9.-]*)
        fail "DOMAIN must be a plain DNS name, for example rune.example.com"
        ;;
esac
case "$APP_DIR" in
    /*) ;;
    *) fail "APP_DIR must be an absolute path" ;;
esac
case "$APP_DIR" in
    *[!A-Za-z0-9_./-]*) fail "APP_DIR contains unsupported characters" ;;
esac
case "$SERVICE_USER:$SERVICE_NAME:$PROXY_GROUP" in
    *[!A-Za-z0-9_.:-]*)
        fail "service user, service name, or proxy group is invalid"
        ;;
esac

for command in caddy getent install systemctl systemd-analyze sed mktemp \
    readlink stat; do
    command -v "$command" >/dev/null 2>&1 ||
        fail "required command not found: $command"
done
id "$SERVICE_USER" >/dev/null 2>&1 ||
    fail "service account does not exist: $SERVICE_USER"
getent group "$PROXY_GROUP" >/dev/null 2>&1 ||
    fail "proxy group does not exist: $PROXY_GROUP"

SERVICE_TEMPLATE="$TEMPLATE_DIR/rune.service"
CADDY_TEMPLATE="$TEMPLATE_DIR/rune.caddy"
[ "$(readlink -f "$TEMPLATE_DIR")" = "$TEMPLATE_DIR" ] ||
    fail "template directory must be canonical and not a symlink"
[ "$(stat -c '%u:%a' "$TEMPLATE_DIR")" = "0:755" ] ||
    fail "$TEMPLATE_DIR must be owned by root with mode 0755"
for template in "$SERVICE_TEMPLATE" "$CADDY_TEMPLATE"; do
    [ -f "$template" ] || fail "reviewed template missing: $template"
    [ "$(stat -c '%u:%a' "$template")" = "0:644" ] ||
        fail "$template must be owned by root with mode 0644"
done

SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
CADDY_SITE="/etc/caddy/$SERVICE_NAME.caddy"
TMP_DIR="$(mktemp -d)"
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

sed \
    -e "s|@@APP_DIR@@|$APP_DIR|g" \
    -e "s|@@SERVICE_USER@@|$SERVICE_USER|g" \
    -e "s|@@SERVICE_NAME@@|$SERVICE_NAME|g" \
    -e "s|@@PROXY_GROUP@@|$PROXY_GROUP|g" \
    "$SERVICE_TEMPLATE" > "$TMP_DIR/$SERVICE_NAME.service"
sed \
    -e "s|@@DOMAIN@@|$DOMAIN|g" \
    -e "s|@@SERVICE_NAME@@|$SERVICE_NAME|g" \
    "$CADDY_TEMPLATE" > "$TMP_DIR/$SERVICE_NAME.caddy"

caddy fmt --overwrite "$TMP_DIR/$SERVICE_NAME.caddy"
systemd-analyze verify "$TMP_DIR/$SERVICE_NAME.service"
caddy validate --config "$TMP_DIR/$SERVICE_NAME.caddy" --adapter caddyfile

install -o root -g root -m 0644 \
    "$TMP_DIR/$SERVICE_NAME.service" "$SERVICE_FILE"
install -o root -g root -m 0644 \
    "$TMP_DIR/$SERVICE_NAME.caddy" "$CADDY_SITE"
systemctl daemon-reload

echo "Installed reviewed policy:"
echo "  $SERVICE_FILE"
echo "  $CADDY_SITE"
echo "Ensure /etc/caddy/Caddyfile imports $CADDY_SITE."

if [ "$ACTIVATE" = "1" ]; then
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
    systemctl restart "$SERVICE_NAME.service"
    systemctl reload caddy.service
fi
