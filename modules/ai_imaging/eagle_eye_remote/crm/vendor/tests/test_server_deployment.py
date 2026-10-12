"""Deployment-layer tests: binding rules, config resolution, frozen paths.

These cover the failures found while packaging the service — each one is here
because it actually broke a real install, not hypothetically.
"""

from __future__ import annotations

import json

import pytest

from reception_crm import runtime
from reception_crm.adapters.http_api import create_http_api_server
from reception_crm.server.config import ServerConfig, load_server_config, write_default_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "RECEPTION_SESSION_SECRET",
        "RECEPTION_HTTP_API_TOKEN",
        "RECEPTION_SERVER_BIND",
        "RECEPTION_SERVER_PORT",
        "RECEPTION_CRM_DATA_ROOT",
        "RECEPTION_CRM_CONFIG_DIR",
        "RECEPTION_HTTP_API_CENTER",
    ):
        monkeypatch.delenv(name, raising=False)


# --- binding rules --------------------------------------------------------


def test_external_bind_refused_without_any_credential(monkeypatch):
    """An unauthenticated public port would expose patient data."""
    with pytest.raises(RuntimeError, match="no credential configured"):
        create_http_api_server("0.0.0.0", 8899)


def test_external_bind_allowed_with_session_secret(monkeypatch):
    """Per-user sessions are the preferred credential and must permit binding.

    Regression: the guard used to demand RECEPTION_HTTP_API_TOKEN specifically,
    so a correctly configured per-user deployment crashed on startup with
    "Refusing to bind to a LAN address".
    """
    monkeypatch.setenv("RECEPTION_SESSION_SECRET", "a" * 64)
    server = create_http_api_server("127.0.0.1", 8898)
    try:
        assert server.server_address[1] == 8898
    finally:
        server.server_close()


def test_external_bind_allowed_with_legacy_token(monkeypatch):
    monkeypatch.setenv("RECEPTION_HTTP_API_TOKEN", "legacy-token")
    server = create_http_api_server("127.0.0.1", 8897)
    try:
        assert server.server_address[1] == 8897
    finally:
        server.server_close()


def test_loopback_bind_needs_no_credential():
    server = create_http_api_server("127.0.0.1", 8896)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_shared_token_closes_the_localhost_shortcut(monkeypatch):
    """With no shared token, 127.0.0.1 is trusted without a credential.

    `legacy_principal` computes local_dev = (client is loopback) and (no token
    configured). On a clinic server that any staff member can sign into, that
    lets any local process read patient data. Configuring a shared token must
    switch the loopback path back to requiring a credential.
    """
    from reception_crm.adapters import http_api

    class FakeHandler:
        client_address = ("127.0.0.1", 5555)
        headers: dict[str, str] = {}

        legacy_principal = http_api.HttpApiHandler.legacy_principal

    handler = FakeHandler()

    # No shared token -> loopback is trusted outright.
    monkeypatch.delenv("RECEPTION_HTTP_API_TOKEN", raising=False)
    assert handler.legacy_principal(None) is not None

    # Shared token configured -> a wrong/absent credential is rejected.
    monkeypatch.setenv("RECEPTION_HTTP_API_TOKEN", "the-real-token")
    assert handler.legacy_principal(None) is None
    assert handler.legacy_principal("wrong-token") is None
    assert handler.legacy_principal("the-real-token") is not None


# --- configuration --------------------------------------------------------


def test_config_validation_blocks_exposed_port_without_credential():
    config = ServerConfig(bind="all", port=8770)
    problems = config.validate()
    assert any("session_secret" in problem for problem in problems)


def test_config_validation_passes_with_secret():
    config = ServerConfig(bind="all", port=8770, session_secret="x" * 64)
    assert config.validate() == []


def test_config_warns_about_plaintext_when_exposed():
    config = ServerConfig(bind="all", port=8770, session_secret="x" * 64)
    assert any("clear text" in note for note in config.warnings())


def test_config_warns_when_center_bootstrap_has_not_run(tmp_path, monkeypatch):
    monkeypatch.setenv("RECEPTION_CRM_CONFIG_DIR", str(tmp_path))
    config = ServerConfig(center="TEST", session_secret="x" * 64)
    assert any("bootstrap-center" in note for note in config.warnings())


def test_environment_overrides_file(tmp_path, monkeypatch):
    config_file = tmp_path / "server.json"
    config_file.write_text(json.dumps({"bind": "local", "port": 1234}), encoding="utf-8")

    monkeypatch.setenv("RECEPTION_SERVER_PORT", "9999")
    config = load_server_config(config_file)

    assert config.port == 9999, "environment must win over the file"
    assert config.bind == "local"


def test_write_default_config_never_overwrites(tmp_path):
    target = tmp_path / "server.json"
    target.write_text('{"port": 4242}', encoding="utf-8")

    write_default_config(target)

    assert json.loads(target.read_text(encoding="utf-8"))["port"] == 4242


def test_invalid_json_falls_back_to_defaults(tmp_path):
    """A corrupt config must not stop the service from starting."""
    config_file = tmp_path / "server.json"
    config_file.write_text("{ not valid json", encoding="utf-8")

    config = load_server_config(config_file)

    assert config.port == 8770


def test_explicit_server_config_keeps_sibling_center_artifacts_together(
    tmp_path, capsys
):
    from reception_crm.server.runner import main

    config_file = tmp_path / "custom" / "server.json"
    config_file.parent.mkdir()
    config_file.write_text(json.dumps({"center": "TEST"}), encoding="utf-8")

    assert main(["--describe", "--config", str(config_file)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["config_file"] == str(config_file.parent / "server.json")
    assert runtime.config_root() == config_file.parent


# --- frozen path resolution ----------------------------------------------


def test_data_root_never_resolves_into_the_pyinstaller_bundle(monkeypatch):
    """The original defect: frozen builds wrote clinical data to a temp dir.

    PyInstaller extracts to _MEIPASS and deletes it on exit, so any data root
    derived from __file__ silently vanished on every restart.
    """
    monkeypatch.setattr(runtime.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime.sys, "_MEIPASS", r"C:\Temp\_MEI123456", raising=False)

    resolved = str(runtime.data_root())

    assert "_MEI" not in resolved
    assert resolved == str(runtime.DEFAULT_DATA_ROOT)


def test_data_root_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("RECEPTION_CRM_DATA_ROOT", str(tmp_path))
    assert runtime.data_root() == tmp_path


def test_config_root_is_writable_location_when_frozen(monkeypatch):
    """Program Files is not writable by the service; ProgramData is."""
    monkeypatch.setattr(runtime.sys, "frozen", True, raising=False)
    monkeypatch.setenv("ProgramData", r"C:\ProgramData")

    assert "ProgramData" in str(runtime.config_root())


def test_roles_policy_found_via_config_root(monkeypatch, tmp_path):
    """A service runs from C:\\Windows\\System32, so relative paths never match."""
    monkeypatch.setenv("RECEPTION_CRM_CONFIG_DIR", str(tmp_path))
    (tmp_path / "roles.json").write_text(
        json.dumps({"schema_version": 1, "roles": {}, "users": {}}), encoding="utf-8"
    )

    from reception_crm.permissions import discover_roles_path

    assert discover_roles_path() == tmp_path / "roles.json"


def test_installer_bootstraps_center_before_starting_the_service():
    """No request may see another centre's bundled migration seed."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    installer = (root / "installer" / "ReceptionCrmServer.iss").read_text(
        encoding="utf-8", errors="replace"
    )
    post_install = installer[installer.index("procedure CurStepChanged"):]
    assert post_install.index("WriteServerConfig();") < post_install.index("BootstrapCenter();")
    assert post_install.index("BootstrapCenter();") < post_install.index("RegisterAndStartService();")
    assert "review-only" in installer.lower()


def test_frozen_build_contains_the_center_bootstrap_helper():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = (root / "scripts" / "ReceptionCrmServer.spec").read_text(encoding="utf-8")
    entry = (root / "scripts" / "reception_server_main.py").read_text(encoding="utf-8")
    assert '"reception_crm.center_bootstrap"' in spec
    assert '"bootstrap-center"' in entry
    assert '"approve-center-concepts"' in entry
