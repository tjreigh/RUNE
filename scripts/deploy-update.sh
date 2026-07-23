#!/bin/sh
set -eu

# Root-owned RUNE release promoter.
#
# SECURITY: do not execute this copy from a Git checkout with sudo. Review it,
# then install it root-owned:
#   sudo install -o root -g root -m 0755 \
#     scripts/deploy-update.sh /usr/local/sbin/rune-deploy
#
# The installed command performs network/build operations as RUNE_DEPLOY_USER,
# promotes an immutable root-owned release, and runs target-provided smoke code
# only as RUNE_SERVICE_USER. It never executes repository or virtualenv code as
# root and never updates systemd/Caddy policy automatically.

PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

INSTALL_PATH="${RUNE_DEPLOY_INSTALL_PATH:-/usr/local/sbin/rune-deploy}"
SOURCE_DIR="${RUNE_SOURCE_DIR:-/srv/rune/source}"
BUILD_DIR="${RUNE_BUILD_DIR:-/srv/rune/build}"
RELEASES_DIR="${RUNE_RELEASES_DIR:-/srv/rune/releases}"
CURRENT_LINK="${RUNE_CURRENT_LINK:-/srv/rune/current}"
DEPLOY_USER="${RUNE_DEPLOY_USER:-rune-deploy}"
SERVICE_USER="${RUNE_SERVICE_USER:-rune}"
SERVICE_NAME="${RUNE_SERVICE_NAME:-rune}"
PYTHON_BIN="${RUNE_PYTHON_BIN:-/usr/bin/python3}"
REMOTE="${RUNE_REMOTE:-origin}"
DEPLOY_REF="${1:-}"
STAGING_DIR=""
STAGING_ROOTED=0
PREVIOUS_RELEASE=""
TARGET_RELEASE=""

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
fi

fail() {
    echo "rune-deploy: $*" >&2
    exit 1
}

if [ "$(id -u)" -ne 0 ]; then
    fail "run the installed command as root, normally with sudo"
fi

case "$DEPLOY_USER:$SERVICE_USER:$SERVICE_NAME:$REMOTE" in
    *[!A-Za-z0-9_.:-]*)
        fail "account, service, or remote name contains unsupported characters"
        ;;
esac
for path in "$SOURCE_DIR" "$BUILD_DIR" "$RELEASES_DIR" "$CURRENT_LINK" "$PYTHON_BIN"; do
    case "$path" in
        /*) ;;
        *) fail "deployment paths must be absolute" ;;
    esac
done
if [ "${#DEPLOY_REF}" -ne 40 ]; then
    fail "pass one full 40-character reviewed commit SHA"
fi
case "$DEPLOY_REF" in
    *[!0-9A-Fa-f]*) fail "deployment revision must be a full commit SHA" ;;
esac

SCRIPT_PATH="$(readlink -f "$0")"
if [ "$SCRIPT_PATH" != "$INSTALL_PATH" ]; then
    fail "refusing to run a mutable checkout script as root; install it at $INSTALL_PATH"
fi
if [ "$(stat -c '%u:%a' "$SCRIPT_PATH")" != "0:755" ]; then
    fail "$INSTALL_PATH must be owned by root with mode 0755"
fi

for command in git runuser systemctl find readlink stat mktemp mv ln chown chmod \
    dirname pgrep pkill; do
    command -v "$command" >/dev/null 2>&1 ||
        fail "required command not found: $command"
done
for account in "$DEPLOY_USER" "$SERVICE_USER"; do
    id "$account" >/dev/null 2>&1 || fail "account does not exist: $account"
done
[ -x "$PYTHON_BIN" ] || fail "Python executable not found: $PYTHON_BIN"
[ -d "$SOURCE_DIR/.git" ] || fail "deployment checkout not found: $SOURCE_DIR"
[ -d "$BUILD_DIR" ] || fail "build directory not found: $BUILD_DIR"
[ -d "$RELEASES_DIR" ] || fail "release directory not found: $RELEASES_DIR"

DEPLOY_UID="$(id -u "$DEPLOY_USER")"
for path in "$SOURCE_DIR" "$BUILD_DIR" "$RELEASES_DIR"; do
    [ "$(readlink -f "$path")" = "$path" ] ||
        fail "deployment directory must be canonical and not a symlink: $path"
done
[ "$(stat -c '%u:%a' "$SOURCE_DIR")" = "$DEPLOY_UID:700" ] ||
    fail "$SOURCE_DIR must be owned by $DEPLOY_USER with mode 0700"
[ "$(stat -c '%u:%a' "$BUILD_DIR")" = "$DEPLOY_UID:700" ] ||
    fail "$BUILD_DIR must be owned by $DEPLOY_USER with mode 0700"
[ "$(stat -c '%u:%a' "$RELEASES_DIR")" = "0:755" ] ||
    fail "$RELEASES_DIR must be owned by root with mode 0755"
CURRENT_PARENT="$(dirname "$CURRENT_LINK")"
[ "$(readlink -f "$CURRENT_PARENT")" = "$CURRENT_PARENT" ] ||
    fail "current-link parent must be canonical: $CURRENT_PARENT"
[ "$(stat -c '%u:%a' "$CURRENT_PARENT")" = "0:755" ] ||
    fail "$CURRENT_PARENT must be owned by root with mode 0755"

run_as_deploy() {
    runuser -u "$DEPLOY_USER" -- "$@"
}

run_as_service() {
    runuser -u "$SERVICE_USER" -- "$@"
}

cleanup() {
    if [ -n "$STAGING_DIR" ] && [ -d "$STAGING_DIR" ]; then
        case "$STAGING_DIR" in
            "$BUILD_DIR"/release.*)
                if [ "$STAGING_ROOTED" = "1" ]; then
                    rm -rf -- "$STAGING_DIR"
                else
                    run_as_deploy rm -rf -- "$STAGING_DIR" || true
                fi
                ;;
        esac
    fi
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

if [ -n "$(run_as_deploy git -C "$SOURCE_DIR" status --porcelain)" ]; then
    fail "refusing to deploy from a dirty checkout: $SOURCE_DIR"
fi

echo "Fetching $REMOTE as $DEPLOY_USER ..."
run_as_deploy git -C "$SOURCE_DIR" fetch --prune "$REMOTE"
TARGET_COMMIT="$(
    run_as_deploy git -C "$SOURCE_DIR" rev-parse \
        --verify --end-of-options "$DEPLOY_REF^{commit}"
)" || fail "unable to resolve deployment ref: $DEPLOY_REF"

TARGET_RELEASE="$RELEASES_DIR/$TARGET_COMMIT"
[ ! -e "$TARGET_RELEASE" ] || fail "release already exists: $TARGET_RELEASE"

if [ -L "$CURRENT_LINK" ]; then
    PREVIOUS_RELEASE="$(readlink -f "$CURRENT_LINK")"
    case "$PREVIOUS_RELEASE" in
        "$RELEASES_DIR"/*) ;;
        *) fail "current link does not point into $RELEASES_DIR" ;;
    esac
fi

STAGING_DIR="$(
    run_as_deploy mktemp -d "$BUILD_DIR/release.XXXXXXXX"
)"
STAGING_RELEASE="$STAGING_DIR/root"
ARCHIVE="$STAGING_DIR/source.tar"
run_as_deploy mkdir -p "$STAGING_RELEASE"

echo "Exporting reviewed commit $TARGET_COMMIT ..."
run_as_deploy git -C "$SOURCE_DIR" archive \
    --format=tar --output="$ARCHIVE" "$TARGET_COMMIT"
run_as_deploy tar -xf "$ARCHIVE" -C "$STAGING_RELEASE"
run_as_deploy rm -f "$ARCHIVE"

echo "Building an isolated release as $DEPLOY_USER ..."
run_as_deploy "$PYTHON_BIN" -m venv --copies "$STAGING_RELEASE/.venv"
# CPython may add lib64 -> lib even with --copies; it is unnecessary here and
# immutable releases intentionally contain no symlinks.
run_as_deploy rm -f "$STAGING_RELEASE/.venv/lib64"
run_as_deploy "$STAGING_RELEASE/.venv/bin/python" -m pip install \
    --disable-pip-version-check \
    --require-hashes \
    --only-binary=:all: \
    -r "$STAGING_RELEASE/requirements/production.txt"
run_as_deploy "$STAGING_RELEASE/.venv/bin/python" -m pip install \
    --disable-pip-version-check \
    --no-deps \
    --no-build-isolation \
    "$STAGING_RELEASE"
run_as_deploy env PYTHONPATH="$STAGING_RELEASE/web" \
    "$STAGING_RELEASE/.venv/bin/python" -c 'import app'

# A malicious build hook must not retain an open directory descriptor and
# race the ownership transition. This account is dedicated to deployments,
# so no long-running process under it is legitimate.
pkill -KILL -u "$DEPLOY_USER" 2>/dev/null || true
attempt=0
while pgrep -u "$DEPLOY_USER" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 20 ] || fail "$DEPLOY_USER still has running processes"
    sleep 0.1
done

# Take the top-level directory first. With no surviving process and no open
# directory descriptor, the deployment user can no longer alter the tree.
chown root:root "$STAGING_RELEASE"
chmod 0700 "$STAGING_RELEASE"
STAGING_ROOTED=1

# Root never interprets target-controlled content. Reject filesystem object
# types that could make recursive ownership/permission changes surprising.
if find -P "$STAGING_RELEASE" -type l -print -quit | grep -q .; then
    fail "release contains a symbolic link"
fi
if find -P "$STAGING_RELEASE" ! -type f ! -type d -print -quit | grep -q .; then
    fail "release contains a non-regular filesystem object"
fi

echo "Promoting immutable release $TARGET_RELEASE ..."
chown -R root:root "$STAGING_RELEASE"
chmod -R a-w,go+rX,u+rX "$STAGING_RELEASE"
mv "$STAGING_RELEASE" "$TARGET_RELEASE"
run_as_deploy rmdir "$STAGING_DIR"
STAGING_DIR=""
STAGING_ROOTED=0

NEXT_LINK="$CURRENT_LINK.next"
rm -f "$NEXT_LINK"
ln -s "$TARGET_RELEASE" "$NEXT_LINK"
mv -Tf "$NEXT_LINK" "$CURRENT_LINK"

rollback() {
    echo "Deployment failed; restoring the previous release ..." >&2
    if [ -n "$PREVIOUS_RELEASE" ] && [ -d "$PREVIOUS_RELEASE" ]; then
        rm -f "$NEXT_LINK"
        ln -s "$PREVIOUS_RELEASE" "$NEXT_LINK"
        mv -Tf "$NEXT_LINK" "$CURRENT_LINK"
        systemctl restart "$SERVICE_NAME.service" || true
    else
        systemctl stop "$SERVICE_NAME.service" || true
    fi
}

echo "Restarting $SERVICE_NAME.service ..."
if ! systemctl restart "$SERVICE_NAME.service" ||
   ! systemctl is-active --quiet "$SERVICE_NAME.service"; then
    rollback
    exit 1
fi

echo "Smoke-testing through the private Unix socket as $SERVICE_USER ..."
if ! run_as_service env \
    BASE_URL=http://localhost \
    CURL_SOCKET="/run/$SERVICE_NAME/rune.sock" \
    PYTHON_BIN="$PYTHON_BIN" \
    "$TARGET_RELEASE/scripts/deploy-smoke-test.sh"; then
    rollback
    exit 1
fi

echo "Deployment succeeded: $TARGET_COMMIT"
