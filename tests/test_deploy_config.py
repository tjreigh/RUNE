from pathlib import Path
import re
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def test_service_uses_only_a_private_unix_socket():
    service = _read("deploy/rune.service")

    assert "--uds /run/@@SERVICE_NAME@@/rune.sock" in service
    assert "--forwarded-allow-ips=*" in service
    assert "--host " not in service
    assert "--port " not in service
    assert "PrivateNetwork=true" in service
    assert "RestrictAddressFamilies=AF_UNIX\n" in service
    assert "AF_INET" not in service
    assert "IPAddressAllow" not in service


def test_service_caps_and_sandboxes_the_complete_process_tree():
    service = _read("deploy/rune.service")

    for option in (
        "--limit-concurrency 32",
        "--backlog 64",
        "--timeout-keep-alive 5",
        "MemoryHigh=448M",
        "MemoryMax=512M",
        "MemorySwapMax=0",
        "TasksMax=64",
        "CPUQuota=100%",
        "LimitNOFILE=256",
        "CapabilityBoundingSet=",
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ProtectProc=invisible",
        "ProcSubset=pid",
        "RestrictNamespaces=true",
        "SystemCallFilter=@system-service",
        "SystemCallErrorNumber=EPERM",
        "MemoryDenyWriteExecute=true",
        "TemporaryFileSystem=/tmp:rw,nosuid,nodev,noexec,size=32M,mode=1777",
        "LogRateLimitBurst=200",
    ):
        assert option in service


def test_caddy_uses_the_unix_socket_and_bounds_requests():
    site = _read("deploy/rune.caddy")

    assert "reverse_proxy unix//run/@@SERVICE_NAME@@/rune.sock" in site
    assert "127.0.0.1:8000" not in site
    for option in (
        "max_size 16KiB",
        "dial_timeout 2s",
        "response_header_timeout 5s",
        "read_timeout 5s",
        "write_timeout 5s",
    ):
        assert option in site


def test_caddy_admin_example_removes_the_loopback_control_plane():
    options = _read("deploy/caddy-global-options.example")

    assert "admin unix//run/caddy/admin.sock" in options
    assert "localhost:2019" not in options


def test_deployer_refuses_checkout_execution_and_never_installs_policy():
    updater = _read("scripts/deploy-update.sh")

    assert 'INSTALL_PATH="${RUNE_DEPLOY_INSTALL_PATH:-/usr/local/sbin/rune-deploy}"' in updater
    assert 'SCRIPT_PATH="$(readlink -f "$0")"' in updater
    assert '"$SCRIPT_PATH" != "$INSTALL_PATH"' in updater
    assert "deploy-install-config.sh" not in updater
    assert "systemctl reload caddy" not in updater
    assert '-e "$APP_DIR' not in updater
    assert "pass one full 40-character reviewed commit SHA" in updater
    assert "--verify --end-of-options" in updater


def test_deployer_builds_locked_and_promotes_immutable_releases():
    updater = _read("scripts/deploy-update.sh")

    for required in (
        "--require-hashes",
        "--only-binary=:all:",
        "--no-deps",
        "--no-build-isolation",
        "chown root:root \"$STAGING_RELEASE\"",
        "chmod -R a-w,go+rX,u+rX \"$STAGING_RELEASE\"",
        "run_as_service env",
        "CURL_SOCKET=\"/run/$SERVICE_NAME/rune.sock\"",
    ):
        assert required in updater
    assert 'pkill -KILL -u "$DEPLOY_USER"' in updater
    assert 'find -P "$STAGING_RELEASE" -type l' in updater


def test_policy_installer_requires_root_owned_installed_inputs():
    installer = _read("scripts/deploy-install-config.sh")

    assert "/usr/local/sbin/rune-install-policy" in installer
    assert "/usr/local/share/rune-deploy" in installer
    assert '"0:755"' in installer
    assert '"0:644"' in installer
    assert "@@PROXY_GROUP@@" in _read("deploy/rune.service")


def test_production_lock_is_complete_and_hash_only():
    lock = _read("requirements/production.txt")
    requirement_lines = [
        line for line in lock.splitlines()
        if line and not line.startswith(("#", " ", "\t"))
    ]

    assert "httpx2" not in lock
    assert any(line.startswith("fastapi==") for line in requirement_lines)
    assert any(line.startswith("uvicorn==") for line in requirement_lines)
    assert any(line.startswith("setuptools==") for line in requirement_lines)
    hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})", lock)
    assert len(hashes) >= len(requirement_lines)
    assert lock.count("pydantic_core") == 0
    assert lock.count("--hash=sha256:") == len(requirement_lines) + 2


def test_http_test_client_dependency_is_not_in_production_extra():
    with (ROOT / "pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)

    assert any("httpx2" in dep for dep in project["project"]["optional-dependencies"]["dev"])
    assert all(
        "httpx2" not in dep
        for dep in project["project"]["optional-dependencies"]["web"]
    )


def test_deployment_smoke_supports_unix_socket_and_checks_functions():
    smoke_test = _read("scripts/deploy-smoke-test.sh")

    assert 'curl $CURL_FLAGS --unix-socket "$CURL_SOCKET"' in smoke_test
    assert '"$BASE_URL/validate"' in smoke_test
    assert 'diagnostics[0].get("kind") != "parse"' in smoke_test
    assert "function factorial(n)" in smoke_test
    assert 'response.get("values") != [120]' in smoke_test


def test_status_never_defaults_to_the_target_virtualenv():
    status = _read("scripts/deploy-status.sh")

    assert 'PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"' in status
    assert ".venv/bin/python" not in status
