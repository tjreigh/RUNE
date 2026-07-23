# Deploying RUNE

RUNE runs as one Uvicorn worker on `127.0.0.1:8000`, behind Caddy. The single
worker is required while sessions use process-local memory; adding workers
requires a shared session store first. These instructions assume an Ubuntu or
Debian VPS with Python 3.12 or newer, Git, curl, Caddy, and systemd.

Before starting, point the domain at the VPS and allow inbound traffic on ports 80 and 443. Port 8000 should remain private.

## First install

Create a service user, clone the repository, and install the web dependencies:

```sh
sudo useradd --system --create-home --home-dir /srv/rune \
  --shell /usr/sbin/nologin rune
sudo -u rune git clone https://github.com/tjreigh/RUNE.git /srv/rune/app
sudo -u rune python3 -m venv /srv/rune/app/.venv
sudo -u rune /srv/rune/app/.venv/bin/python -m pip install \
  -e "/srv/rune/app[web]"
```

Install the systemd unit and Caddy site configuration:

```sh
sudo DOMAIN=rune.tjreigh.mobi \
  /srv/rune/app/scripts/deploy-install-config.sh
```

Add the import printed by the installer to `/etc/caddy/Caddyfile`:

```caddyfile
import /etc/caddy/rune.caddy
```

Then activate the service:

```sh
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl enable --now rune.service
sudo systemctl reload caddy
```

Alternatively, after adding the import, let the installer activate everything:

```sh
sudo DOMAIN=rune.tjreigh.mobi ACTIVATE=1 \
  /srv/rune/app/scripts/deploy-install-config.sh
```

The checked-in Caddy configuration uses `request_body`, which requires Caddy
2.10 or newer. On an older version, remove that block; the application still
enforces its own request-size limit.

## Caddy limits

Client-facing header, body, write, idle, and maximum-header limits are Caddy
server options, not site options. They can affect every application sharing a
listener, so RUNE deliberately does not install or overwrite them. Configure
them in the single global block at the beginning of `/etc/caddy/Caddyfile`
according to the slowest legitimate application on the server.

For a Caddy instance dedicated to RUNE, this is a reasonable starting point:

```caddyfile
{
    servers {
        timeouts {
            read_body 10s
            read_header 5s
            write 30s
            idle 2m
        }
        max_header_size 16KiB
    }
}
```

## Resource limits

Each evaluation runs in a disposable process with a two-second deadline and
irreversible Linux limits of 192 MiB of address space, three CPU seconds,
1,000,000 bytes of file output, and no core dumps. The application admits at
most two evaluations concurrently, at most 120 evaluations and 20 new sessions
per minute across all clients. Compile-only validation is admitted separately
at four concurrent requests, 120 requests per client per minute, and 480 per
minute across all clients. Uvicorn caps accepted tasks and its socket backlog.
The systemd unit additionally caps the complete service process tree at 512
MiB, one CPU, 64 tasks, and 1,024 file descriptors, with swap disabled, so a
failed inner limit remains contained to the service instead of exhausting the
VPS. Tune the service limits only while preserving enough memory and CPU for
the OS, Caddy, and SSH.

## Update

Deploy the latest `origin/main`:

```sh
sudo /srv/rune/app/scripts/deploy-update.sh
```

Pass a tag or commit SHA to deploy a specific revision. Updates reinstall and
validate the checked-in systemd and Caddy policy as well as application code.
They validate the complete Caddyfile before restarting RUNE,
and failed deployments automatically roll back to the previous commit.

## Check the deployment

```sh
sudo PUBLIC_URL=https://rune.tjreigh.mobi \
  /srv/rune/app/scripts/deploy-status.sh

sudo journalctl -u rune.service -n 100 --no-pager
sudo journalctl -u caddy.service -n 100 --no-pager
```

The scripts default to `/srv/rune/app`, the `rune` user and service, and `origin/main`. Run any script with `--help` to see its available overrides.
