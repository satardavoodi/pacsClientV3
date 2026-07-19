"""Wiring / integration guards for the Agent Gateway.

Source-pins (no Qt import) that fail if a future refactor drops the Settings-tab
registration, the boot start hook, the shutdown stop hook, or the build-system
config entries — the "works in source, missing in the build" class the release
parity guards protect against, applied to this feature specifically.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8", errors="replace")


# ── Settings tab registration ────────────────────────────────────────────────
def test_settings_registers_agent_tab():
    src = _read("PacsClient/pacs/workstation_ui/settings_ui/settings_ui.py")
    assert "_add_lazy_tab('Agent', self._create_agent_settings)" in src
    assert "def _create_agent_settings" in src
    assert "from .agent_settings import AgentSettingsWidget" in src


def test_agent_settings_widget_module_exists():
    assert (REPO / "PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py").exists()


# ── boot start hook (home panel) ─────────────────────────────────────────────
def test_home_panel_installs_and_starts_gateway():
    src = _read("PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py")
    assert "from modules.agent_gateway.service import install_service" in src
    assert "start_if_enabled()" in src
    assert "_agent_gateway_service" in src


# ── shutdown stop hook (main.py, before the hard-exit failsafe) ──────────────
def test_main_stops_gateway_before_hard_exit():
    src = _read("main.py")
    assert "_agent_gateway_service" in src
    stop_idx = src.index("_agent_gateway_service")
    exit_idx = src.index("os._exit(0)")
    assert stop_idx < exit_idx, "gateway must be stopped before the hard-exit failsafe"


# ── build-system config wiring ───────────────────────────────────────────────
def test_config_template_present_and_has_no_secrets():
    """The template must exist and carry no centre-specific secrets.

    NOTE: we deliberately do NOT assert the on-disk ``enabled`` flag here. On a
    SOURCE build the roaming config root IS this repo's config/ dir, so merely
    enabling the gateway in the app rewrites this file. The ship-OFF guarantee is
    enforced by the BUILD (see test_build_forces_gateway_disabled) and by the
    code default (see test_code_default_is_disabled) — not by the dev's tree.
    """
    tmpl = REPO / "config/agent_gateway/agent_gateway.json"
    assert tmpl.exists()
    import json

    data = json.loads(tmpl.read_text(encoding="utf-8"))
    assert data["relay_auth_token"] == ""         # no baked-in secret
    assert data["relay_base_url"] == ""


def test_code_default_is_disabled():
    """The shipping contract: the feature defaults OFF in code."""
    from modules.agent_gateway.config_store import _defaults

    assert _defaults()["enabled"] is False


def test_build_forces_gateway_disabled_and_strips_advertise_host():
    """Packaging must neutralise a dev tree that left the gateway enabled."""
    import json
    import sys

    sys.path.insert(0, str(REPO))
    from builder.config_sanitizer import sanitize_bytes

    dirty = json.dumps({
        "enabled": True,
        "relay_base_url": "https://relay.example.com",
        "relay_auth_token": "super-secret",
        "relay_workstation_id": "clinic-3",
        "advertise_host": "192.168.24.41",
        "port": 8760,
    }).encode("utf-8")
    clean = json.loads(sanitize_bytes("agent_gateway/agent_gateway.json", dirty))
    assert clean["enabled"] is False              # forced OFF at build time
    assert clean["relay_auth_token"] == ""
    assert clean["relay_base_url"] == ""
    assert clean["advertise_host"] == ""          # centre-specific, stripped
    assert clean["port"] == 8760                  # product defaults preserved


def test_config_family_and_feature_flag_registered():
    import re

    runtime = _read("aipacs_runtime.py")
    # version-agnostic: the family must be registered at SOME version
    assert re.search(r'"agent_gateway/agent_gateway\.json":\s*\d+', runtime)
    guards = _read("tests/code/builder/test_release_parity_guards.py")
    assert '"agent_gateway/agent_gateway.json"' in guards


def test_sanitizer_blanks_relay_secrets():
    src = _read("builder/config_sanitizer.py")
    assert "agent_gateway/agent_gateway.json" in src
    assert "relay_auth_token" in src


def test_sanitizer_excludes_gateway_runtime_artifacts():
    # A source build writes the paired-device registry + a TLS cert/private key
    # under config/agent_gateway/; the build must NEVER package them.
    src = _read("builder/config_sanitizer.py")
    for name in ("devices.json", "gateway_cert.pem", "gateway_key.pem"):
        assert name in src, f"{name} must be in config_sanitizer EXCLUDE_NAMES"


def test_requirements_declares_segno():
    assert "segno" in _read("requirements.txt")


# ── remote stack (outbound rendezvous + E2E) ────────────────────────────────
def test_remote_stack_modules_present():
    for rel in (
        "modules/agent_gateway/secure_channel.py",   # P4 E2E
        "modules/agent_gateway/relay_ws.py",         # P3 outbound WSS client
        "tools/agent_relay/aipacs_relay.py",         # P1+P2 registry + rendezvous
        "tools/agent_relay/requirements.txt",
        "tools/agent_relay/integration_check.py",
    ):
        assert (REPO / rel).exists(), f"missing {rel}"


def test_relay_registry_stores_no_ip_addresses():
    """The whole point of the design: identity is a stable id, never an address.

    If an ip/endpoint/port column ever appears in the relay schema, the
    architecture has regressed to endpoint tracking.
    """
    src = _read("tools/agent_relay/aipacs_relay.py")
    block = src[src.index("SCHEMA = "):src.index("def _hash")]
    # Only inspect the SQL itself — prose/comments legitimately mention these words.
    sql = "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("#")
    ).lower()
    for banned in ("ip_address", "endpoint", "ip text", "port integer", "port text"):
        assert banned not in sql, f"relay schema must not store {banned!r}"


def test_websocket_client_is_a_soft_dependency():
    """A build without websocket-client must still run (long-poll fallback)."""
    src = _read("modules/agent_gateway/relay_ws.py")
    assert "def websocket_available" in src
    assert "falling back to the long-poll" in src


def test_service_prefers_ws_then_falls_back():
    src = _read("modules/agent_gateway/service.py")
    assert "relay_ws_url" in src and "WebSocketRelayClient" in src
    assert src.index("WebSocketRelayClient") < src.index("from .relay_transport import RelayClient")


def test_sanitizer_blanks_rendezvous_identity():
    src = _read("builder/config_sanitizer.py")
    for key in ("relay_ws_url", "relay_workstation_secret"):
        assert key in src, f"{key} must be blanked by the build"


# ── docs resources (curated + synthesized) ───────────────────────────────────
def test_docs_provider_lists_functions_and_reads_catalog():
    from modules.agent_gateway.docs_resources import DocsResourceProvider

    provider = DocsResourceProvider(list_actions=lambda: ["list_patients", "open_patient"])
    uris = {r["uri"] for r in provider.list_resources()}
    assert "aipacs-agent://functions" in uris

    catalog = provider.read_resource("aipacs-agent://functions")
    import json

    data = json.loads(catalog["text"])
    assert data["action_count"] == 2
    assert set(data["actions"]) == {"list_patients", "open_patient"}
    assert "how_to_call" in data


def test_docs_provider_unknown_resource_returns_none():
    from modules.agent_gateway.docs_resources import DocsResourceProvider

    assert DocsResourceProvider().read_resource("aipacs-agent://docs/nope") is None


def test_pairing_protocol_doc_present():
    assert (REPO / "docs/for-future-agents/AGENT_MOBILE_PAIRING_PROTOCOL.md").exists()
    assert (REPO / "docs/pipelines/agent-gateway.md").exists()
