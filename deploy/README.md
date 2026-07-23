# Hardened RUNE deployment

RUNE is intentionally treated as an untrusted-code service. Caddy reaches one
Uvicorn process through `/run/rune/rune.sock`; the service has no IP network
namespace, no writable application files, and no credentials. Each evaluation
still runs in its own resource-limited disposable process.

The repository's privileged helpers deliberately refuse to run from a mutable
Git checkout. Review them, install root-owned copies, and use only those copies
on the VPS.

## Supported production target

The checked-in production lock supports:

- Debian or Ubuntu with systemd and cgroup v2
- CPython 3.12
- Linux x86_64
- Caddy 2.10 or newer

Check before migrating:

```sh
uname -m
/usr/bin/python3 --version
caddy version
systemd --version
stat -fc %T /sys/fs/cgroup
```

`uname -m` must report `x86_64`, Python must be 3.12, and the cgroup filesystem
should report `cgroup2fs`. Regenerate and review
`requirements/production.txt` before using another architecture or Python
minor version.

## Security model

The accounts have deliberately separate authority:

- `rune` runs the public service and owns no releases or executables.
- `rune-deploy` owns only the source checkout and scratch build directory.
- `root` owns promoted releases, systemd policy, Caddy policy, and the fixed
  deployment commands.
- `rune-proxy` grants only Caddy and RUNE access to the application socket.

Repository and dependency code may execute as `rune-deploy` while building and
as `rune` after promotion. Neither path executes as root. Application updates
never install systemd or Caddy configuration.

For the strongest host boundary, run RUNE on a dedicated VPS or VM with no
unrelated credentials or workloads. The controls below reduce host exposure
but cannot make a shared Linux kernel equivalent to a VM boundary.

## Back up the existing deployment

Before migration, record the current revision and configuration:

```sh
sudo -u rune git -C /srv/rune/app rev-parse HEAD
sudo cp -a /etc/systemd/system/rune.service /root/rune.service.before-hardening
sudo cp -a /etc/caddy/Caddyfile /root/Caddyfile.before-rune-hardening
sudo cp -a /etc/caddy/rune.caddy /root/rune.caddy.before-hardening
```

Keep an SSH session open throughout the migration.

## Create the trust boundaries

Create accounts and directories once:

```sh
getent group rune-proxy >/dev/null ||
  sudo groupadd --system rune-proxy
getent passwd rune >/dev/null ||
  sudo useradd --system --no-create-home --shell /usr/sbin/nologin rune
sudo install -d -o root -g root -m 0755 /srv/rune
getent passwd rune-deploy >/dev/null ||
  sudo useradd --system --create-home --home-dir /srv/rune/deploy-home \
    --shell /usr/sbin/nologin rune-deploy
sudo usermod --append --groups rune-proxy rune
sudo usermod --append --groups rune-proxy caddy

sudo install -d -o rune-deploy -g rune-deploy -m 0700 \
  /srv/rune/source /srv/rune/build /srv/rune/deploy-home
sudo install -d -o root -g root -m 0755 /srv/rune/releases
```

If an account or group already exists, inspect it rather than recreating it:

```sh
getent passwd rune
getent passwd rune-deploy
getent group rune-proxy
```

Clone the source as the deployment account:

```sh
sudo -u rune-deploy git clone https://github.com/tjreigh/RUNE.git \
  /srv/rune/source
```

## Install the reviewed control plane

From a checkout at the exact reviewed commit, inspect the helpers and policy:

```sh
git diff HEAD -- scripts/deploy-update.sh scripts/deploy-install-config.sh \
  deploy/rune.service deploy/rune.caddy
```

Then install root-owned copies:

```sh
sudo install -o root -g root -m 0755 \
  scripts/deploy-update.sh /usr/local/sbin/rune-deploy
sudo install -o root -g root -m 0755 \
  scripts/deploy-install-config.sh /usr/local/sbin/rune-install-policy
sudo install -d -o root -g root -m 0755 /usr/local/share/rune-deploy
sudo install -o root -g root -m 0644 \
  deploy/rune.service /usr/local/share/rune-deploy/rune.service
sudo install -o root -g root -m 0644 \
  deploy/rune.caddy /usr/local/share/rune-deploy/rune.caddy
```

This is the only step where repository deployment policy crosses into the
root-owned control plane. Repeat it only after reviewing an intentional policy
change; ordinary application updates do not repeat it.

## Protect Caddy administration

Caddy's default admin API listens without authentication on localhost TCP.
Merge this line into the existing global options block at the beginning of
`/etc/caddy/Caddyfile`:

```caddyfile
{
	admin unix//run/caddy/admin.sock

	# Keep any existing global options here.
}
```

Do not add a second global block. Ensure Caddy's systemd reload command knows
the non-default endpoint:

```sh
sudo systemctl edit caddy.service
```

Add:

```ini
[Service]
Environment=CADDY_ADMIN=unix//run/caddy/admin.sock
```

Validate the file, then restart Caddy once to move the endpoint atomically:

```sh
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl daemon-reload
sudo systemctl restart caddy
```

Confirm TCP administration is gone and the root operator can reach the socket:

```sh
! curl --fail --max-time 2 http://127.0.0.1:2019/config/
sudo curl --fail --unix-socket /run/caddy/admin.sock http://localhost/config/ \
  >/dev/null
```

The second command must succeed; the first must fail.

## Install RUNE policy

Render the reviewed templates:

```sh
sudo DOMAIN=rune.example.com rune-install-policy
```

Ensure the operator-owned `/etc/caddy/Caddyfile` contains:

```caddyfile
import /etc/caddy/rune.caddy
```

Then validate the complete configuration:

```sh
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemd-analyze verify /etc/systemd/system/rune.service
```

## Deploy an exact application revision

Deploy a full reviewed commit SHA, not a moving branch:

```sh
sudo rune-deploy 0123456789abcdef0123456789abcdef01234567
sudo systemctl enable rune.service
sudo systemctl reload caddy.service
```

The deployment command:

1. fetches and exports the commit as `rune-deploy`;
2. installs only hash-locked binary dependencies;
3. builds and imports the application as `rune-deploy`;
4. rejects symlinks and special filesystem objects;
5. promotes a root-owned, read-only release;
6. restarts the systemd service;
7. runs target-provided smoke code only as `rune`; and
8. restores the previous release automatically if startup or smoke testing
   fails.

The command never executes repository scripts, Python, package hooks, or Caddy
configuration as root.

## Required verification

Run these after the first hardened deployment and after OS/systemd upgrades.

Service and socket:

```sh
sudo systemctl --no-pager --full status rune.service
sudo systemctl show rune.service \
  -p User -p Group -p PrivateNetwork -p RestrictAddressFamilies \
  -p NoNewPrivileges -p MemoryMax -p MemoryHigh -p TasksMax
sudo ss -ltnp
sudo ss -lxnp | grep /run/rune/rune.sock
```

Nothing should listen on TCP port 8000. Public listeners should be limited to
the services the VPS intentionally exposes, normally SSH plus Caddy on 80/443.

Ownership and write denial:

```sh
sudo namei -l /srv/rune/current
sudo -u rune test ! -w /srv/rune/current
sudo -u rune test ! -w "$(readlink -f /srv/rune/current)"
sudo find -L /srv/rune/current -xdev -perm /022 -print
```

The two write tests must succeed (meaning the paths are not writable), and the
final `find` should print nothing.

Cross-service isolation:

```sh
sudo -u rune curl --fail --max-time 2 http://127.0.0.1:2019/config/ && exit 1 || true
sudo -u rune curl --fail --max-time 2 \
  --unix-socket /run/caddy/admin.sock http://localhost/config/ && exit 1 || true
sudo -u caddy curl --fail --max-time 2 \
  --unix-socket /run/rune/rune.sock http://localhost/ >/dev/null
```

Both RUNE-to-Caddy-admin checks must fail. Caddy-to-RUNE must succeed.

Systemd hardening:

```sh
sudo systemd-analyze security rune.service
sudo journalctl -u rune.service -n 100 --no-pager
```

Review every item reported by `systemd-analyze`; do not chase the numeric score
by enabling incompatible controls blindly. In particular, confirm evaluator
process creation still works under the syscall filter.

Functional smoke tests:

```sh
sudo -u rune /srv/rune/current/scripts/deploy-status.sh
sudo -u rune PUBLIC_URL=https://rune.example.com \
  /srv/rune/current/scripts/deploy-status.sh
```

Finally, exercise one infinite loop and confirm it returns a bounded diagnostic
without leaving an evaluator child:

```sh
curl --fail --silent --show-error \
  -H 'content-type: application/json' \
  -d '{"source":"while (1)\nend while"}' \
  https://rune.example.com/evaluate
pgrep -a -u rune
```

Only the Uvicorn parent should remain after the request.

## Updating application code

Review and deploy an exact commit:

```sh
sudo -u rune-deploy git -C /srv/rune/source fetch origin
sudo -u rune-deploy git -C /srv/rune/source show \
  --stat 0123456789abcdef0123456789abcdef01234567
sudo rune-deploy 0123456789abcdef0123456789abcdef01234567
```

Updating systemd/Caddy policy is a separate, explicit review and reinstall of
the root-owned control-plane files.

## Manual rollback

List immutable releases and repoint the atomic symlink:

```sh
sudo ls -1 /srv/rune/releases
sudo ln -s /srv/rune/releases/PREVIOUS_COMMIT /srv/rune/current.next
sudo mv -Tf /srv/rune/current.next /srv/rune/current
sudo systemctl restart rune.service
sudo -u rune /srv/rune/current/scripts/deploy-status.sh
```

Promoted releases are deliberately retained for rollback. Remove an old
release only after confirming it is not the current target and is no longer
needed.

## Host-level controls

- Permit inbound traffic only to SSH, HTTP, and HTTPS.
- Keep the kernel, Python, systemd, Caddy, and dependencies patched.
- Do not store application secrets in the RUNE service environment.
- Keep unrelated databases and control planes off this VPS where practical.
- Back up operator-owned Caddy and systemd configuration before policy changes.
- Run a dependency advisory scanner in CI and before each dependency-lock
  update.
