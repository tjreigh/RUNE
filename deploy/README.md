# RUNE production deployment

Use the installed, root-owned `/usr/local/sbin/rune-deploy` helper for
application updates. Never run the repository copy with `sudo`.

## Routine task: deploy an application update

Deploy a reviewed full commit SHA:

```sh
COMMIT=0123456789abcdef0123456789abcdef01234567
sudo rune-deploy --check
sudo rune-deploy "$COMMIT"
sudo -u rune /srv/rune/current/scripts/deploy-status.sh
```

The helper fetches, builds, promotes, restarts, smoke-tests, and automatically
rolls back a failed release. It can be invoked
from any working directory. Leave `/srv/rune/source` as a clean detached
checkout; the helper exports the requested commit without checking it out.

Application updates do not reinstall systemd/Caddy policy or reload Caddy.

## Routine task: check deployment status

```sh
readlink -f /srv/rune/current
sudo systemctl --no-pager --full status rune.service
sudo journalctl -u rune.service -n 100 --no-pager
sudo -u rune /srv/rune/current/scripts/deploy-status.sh
sudo -u rune PUBLIC_URL=https://rune.example.com \
  /srv/rune/current/scripts/deploy-status.sh
```

## Recovery task: roll back manually

Startup and smoke-test failures roll back automatically. To select another
retained release manually:

```sh
sudo ls -1 /srv/rune/releases
PREVIOUS_COMMIT=0123456789abcdef0123456789abcdef01234567
sudo rm -f /srv/rune/current.next
sudo ln -s "/srv/rune/releases/$PREVIOUS_COMMIT" /srv/rune/current.next
sudo mv -Tf /srv/rune/current.next /srv/rune/current
sudo systemctl restart rune.service
sudo -u rune /srv/rune/current/scripts/deploy-status.sh
```

## Maintenance task: update the deployment control plane

The root-owned control plane is sourced from:

- `scripts/deploy-update.sh`
- `scripts/deploy-install-config.sh`
- `deploy/rune.service`
- `deploy/rune.caddy`

Update it only from an exact reviewed commit. First compare installed files:

```sh
sudo diff -u /usr/local/sbin/rune-deploy scripts/deploy-update.sh || true
sudo diff -u /usr/local/sbin/rune-install-policy \
  scripts/deploy-install-config.sh || true
sudo diff -u /usr/local/share/rune-deploy/rune.service \
  deploy/rune.service || true
sudo diff -u /usr/local/share/rune-deploy/rune.caddy \
  deploy/rune.caddy || true
```

Install reviewed copies:

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

If policy templates changed:

```sh
sudo DOMAIN=rune.example.com rune-install-policy
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemd-analyze verify /etc/systemd/system/rune.service
sudo systemctl restart rune.service
sudo systemctl reload caddy.service
```

If only the deploy helper changed, install it and run:

```sh
sudo rune-deploy --check
```

## Troubleshooting

Start here:

```sh
sudo rune-deploy --check
sudo journalctl -u rune.service -n 100 --no-pager
```

- `/root/.yarnrc` or another denied `/root` path means the installed deployer
  is stale. Reinstall the reviewed helper; do not loosen `/root` permissions.
- A dirty source checkout must be investigated:
  `sudo -H -u rune-deploy git -C /srv/rune/source status`.
- An existing release is immutable and cannot be overwritten. Confirm it with
  `sudo ls -ld /srv/rune/releases/COMMIT`.
- `ModuleNotFoundError: No module named 'app'` means the deployer or service
  policy predates the `rune_web` package. Update the control plane.
- Startup and smoke-test failures restore the prior release. Inspect the
  journal before retrying.

## First-time task: prepare a production host

### 1. Check requirements

- Debian or Ubuntu with systemd and cgroup v2
- Linux x86_64
- CPython 3.12–3.14
- Node.js 22 or newer
- Yarn 1.22.22
- Caddy 2.10 or newer

```sh
uname -m
/usr/bin/python3 --version
node --version
yarn --version
caddy version
stat -fc %T /sys/fs/cgroup
```

### 2. Create accounts and directories

```sh
getent group rune-proxy >/dev/null ||
  sudo groupadd --system rune-proxy
getent passwd rune >/dev/null ||
  sudo useradd --system --no-create-home --shell /usr/sbin/nologin rune
getent group rune-deploy >/dev/null ||
  sudo groupadd --system rune-deploy
getent passwd rune-deploy >/dev/null ||
  sudo useradd --system --create-home --home-dir /srv/rune/deploy-home \
    --gid rune-deploy --shell /usr/sbin/nologin rune-deploy

sudo usermod --append --groups rune-proxy rune
sudo usermod --append --groups rune-proxy caddy
sudo install -d -o root -g root -m 0755 /srv/rune
sudo install -d -o rune-deploy -g rune-deploy -m 0700 \
  /srv/rune/source /srv/rune/build /srv/rune/deploy-home
sudo install -d -o root -g root -m 0755 /srv/rune/releases
```

### 3. Clone and install the control plane

```sh
sudo -H -u rune-deploy git clone https://github.com/tjreigh/RUNE.git \
  /srv/rune/source
```

From an operator checkout at the reviewed commit, follow
[Maintenance task: update the deployment control plane](#maintenance-task-update-the-deployment-control-plane).

### 4. Move Caddy administration to a Unix socket

Merge this into the existing global block in `/etc/caddy/Caddyfile`:

```caddyfile
{
	admin unix//run/caddy/admin.sock
}
```

Add a Caddy systemd override with `sudo systemctl edit caddy.service`:

```ini
[Service]
RuntimeDirectory=caddy
RuntimeDirectoryMode=0700
Environment=CADDY_ADMIN=unix//run/caddy/admin.sock
```

Then validate and restart:

```sh
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl daemon-reload
sudo systemctl restart caddy
```

### 5. Install policy and make the first deployment

Ensure `/etc/caddy/Caddyfile` imports the generated site:

```caddyfile
import /etc/caddy/rune.caddy
```

Then:

```sh
sudo DOMAIN=rune.example.com rune-install-policy
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemd-analyze verify /etc/systemd/system/rune.service
sudo rune-deploy --check
sudo rune-deploy 0123456789abcdef0123456789abcdef01234567
sudo systemctl enable rune.service
sudo systemctl reload caddy.service
```

## Periodic verification

Run after initial setup and OS, systemd, Caddy, or policy upgrades:

```sh
sudo systemctl show rune.service \
  -p User -p Group -p PrivateNetwork -p RestrictAddressFamilies \
  -p NoNewPrivileges -p MemoryMax -p TasksMax
sudo ss -ltnp
sudo ss -lxnp | grep /run/rune/rune.sock
sudo namei -l /srv/rune/current
sudo -u rune test ! -w /srv/rune/current
sudo find -L /srv/rune/current -xdev -perm /022 -print
sudo systemd-analyze security rune.service
```

Nothing should listen on TCP port 8000. The final `find` should print nothing.

## Reference: security model

- `rune` runs the service and owns no releases or executables.
- `rune-deploy` owns only its home, source, and scratch build tree.
- `root` owns releases, installed helpers, and systemd/Caddy policy.
- `rune-proxy` grants Caddy and RUNE access to the private application socket.

Build and application code run only as `rune-deploy` or `rune`, never as root.
Application releases are immutable. Caddy reaches RUNE through
`/run/rune/rune.sock`; the service has no IP network namespace or credentials.
