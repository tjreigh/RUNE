# Deploying RUNE

RUNE runs as one Uvicorn worker on `127.0.0.1:8000`, behind Caddy. These instructions assume an Ubuntu or Debian VPS with Python 3.12 or newer, Git, curl, Caddy, and systemd.

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

Add the import printed by the installer to `/etc/caddy/Caddyfile`, then activate the service:

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

The checked-in Caddy configuration uses `request_body`, which requires Caddy 2.10 or newer. On an older version, remove that block; the application still enforces its own request-size limit.

## Update

Deploy the latest `origin/main`:

```sh
sudo /srv/rune/app/scripts/deploy-update.sh
```

Pass a tag or commit SHA to deploy a specific revision. Failed deployments automatically roll back to the previous commit.

## Check the deployment

```sh
sudo PUBLIC_URL=https://rune.tjreigh.mobi \
  /srv/rune/app/scripts/deploy-status.sh

sudo journalctl -u rune.service -n 100 --no-pager
sudo journalctl -u caddy.service -n 100 --no-pager
```

The scripts default to `/srv/rune/app`, the `rune` user and service, and `origin/main`. Run any script with `--help` to see its available overrides.
