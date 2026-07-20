from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def test_service_caps_uvicorn_and_the_complete_process_tree():
    service = _read("deploy/rune.service")

    for option in (
        "--limit-concurrency 32",
        "--backlog 64",
        "--timeout-keep-alive 5",
        "MemoryMax=512M",
        "MemorySwapMax=0",
        "TasksMax=64",
        "CPUQuota=100%",
        "LimitNOFILE=1024",
        "CapabilityBoundingSet=",
        "NoNewPrivileges=true",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "IPAddressDeny=any",
        "IPAddressAllow=localhost",
        "ProtectProc=invisible",
        "ProcSubset=pid",
    ):
        assert option in service


def test_caddy_bounds_rune_requests_and_upstream_requests():
    site = _read("deploy/rune.caddy")

    for option in (
        "max_size 16KiB",
        "dial_timeout 2s",
        "response_header_timeout 5s",
        "read_timeout 5s",
        "write_timeout 5s",
    ):
        assert option in site


def test_deployment_update_reinstalls_site_policy_and_validates_caddyfile():
    updater = _read("scripts/deploy-update.sh")

    assert '"$APP_DIR/scripts/deploy-install-config.sh"' in updater
    assert 'awk -v site="$CADDY_SITE"' in updater
    assert "--config /etc/caddy/Caddyfile" in updater
    assert "systemctl restart" in updater
