"""Agent Gateway settings persistence (roaming user config).

Mirrors the EchoMind ``settings_store`` idiom: a ``_defaults()`` dict merged over
the on-disk JSON, atomic ``tmp``+``os.replace`` writes, and typed accessors. The
file lives at ``<roaming config root>/agent_gateway/agent_gateway.json`` so a
user's choices persist across restarts and updates.

Pure stdlib. Never raises into a caller — a missing / unparseable file returns
defaults so the gateway (and the Settings tab) always have a usable config.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

# Canonical config filename (also the CONFIG_FAMILY_VERSIONS family key tail).
CONFIG_SUBDIR = "agent_gateway"
CONFIG_FILENAME = "agent_gateway.json"

# Device permission modes offered to a paired device. Mapped to the CommandBus
# permission-gate ``agent_mode`` in :mod:`modules.agent_gateway.core`.
DEVICE_MODE_FULL = "full"          # every action, no confirmation (audited)
DEVICE_MODE_ASSISTANT = "assistant"  # reads free; server-write/destructive confirm
DEVICE_MODE_READ_ONLY = "read_only"  # queries/reads only
DEVICE_MODES = (DEVICE_MODE_FULL, DEVICE_MODE_ASSISTANT, DEVICE_MODE_READ_ONLY)

TRANSPORT_LAN = "lan"
TRANSPORT_RELAY = "relay"
TRANSPORTS = (TRANSPORT_LAN, TRANSPORT_RELAY)

DEFAULT_PORT = 8760


def _roaming_config_dir() -> Path:
    """Resolve the roaming config dir; fall back to a home dir if runtime import
    is unavailable (keeps pure tests + odd environments working)."""
    try:
        from aipacs_runtime import roaming_config_root

        return Path(roaming_config_root())
    except Exception:
        return Path.home() / ".aipacs" / "config"


def config_path() -> Path:
    cfg_dir = _roaming_config_dir() / CONFIG_SUBDIR
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return cfg_dir / CONFIG_FILENAME


def gateway_data_dir() -> Path:
    """Directory for runtime gateway state (TLS material, device tokens).

    Kept beside the config file, under the roaming profile — NEVER inside the
    shipped repo ``config/`` tree, so nothing secret is ever packaged.
    """
    d = _roaming_config_dir() / CONFIG_SUBDIR
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _defaults() -> Dict[str, Any]:
    return {
        # Master switch. The gateway server binds ONLY when this is true (and
        # the env flag does not force it off). Default OFF.
        "enabled": False,
        # Reachability: "lan" (same network) or "relay" (outbound tunnel).
        "transport": TRANSPORT_LAN,
        # LAN bind scope: "lan" -> all interfaces (0.0.0.0) so the phone can
        # reach it; "loopback" -> 127.0.0.1 (dev only). Resolved in core.
        "bind_scope": "lan",
        "port": DEFAULT_PORT,
        # Self-signed TLS + cert-pinning (fingerprint travels in the QR).
        "tls_enabled": True,
        # MCP endpoint (Streamable-HTTP JSON-RPC over POST).
        "mcp_enabled": True,
        "mcp_path": "/mcp",
        # Default permission mode assigned to a newly paired device. The owner
        # selected FULL; every device's mode is individually changeable in the
        # Agent tab afterwards, and the permission gate stays enforced.
        "default_device_mode": DEVICE_MODE_FULL,
        # Pairing code lifetime + device-token lifetime (0 days = non-expiring).
        "pairing_ttl_seconds": 300,
        "device_token_ttl_days": 0,
        # Human-friendly name shown to the phone during pairing.
        "workstation_name": "",
        # Address the pairing QR advertises FIRST. Empty = auto (default-route
        # address first, then every other detected address). Pin this when the
        # workstation is multi-homed — e.g. a PACS box with one IP per modality
        # subnet plus a WireGuard tunnel: set it to the address the PHONES can
        # actually reach (the VPN/tunnel address for remote access), otherwise
        # the client may give up before trying the right one. May also be a
        # hostname (DDNS / public name), not just an IP.
        "advertise_host": "",
        # ── Relay transport (only used when transport == "relay") ────────────
        # The rendezvous server you host. Blank by default; blanked by the
        # build sanitizer so a dev's relay never ships.
        "relay_base_url": "",
        "relay_auth_token": "",       # this workstation's relay credential
        "relay_workstation_id": "",   # stable id for this PC on the relay
        "relay_poll_timeout_seconds": 25,
        # ── P2/P3: persistent outbound WebSocket rendezvous (preferred) ──────
        # e.g. "wss://relay.aipacs.example/agent/ws". When set, the workstation
        # holds ONE outbound connection to the AIPACS relay and is reachable from
        # anywhere — no static IP, no port forwarding. The relay routes by
        # relay_workstation_id, never by address.
        "relay_ws_url": "",
        # Credential issued by the relay at registration (never ships).
        "relay_workstation_secret": "",
        # ── P4: end-to-end encryption ───────────────────────────────────────
        # Seal every frame so the relay only ever forwards opaque ciphertext.
        # Keep this ON for anything crossing a network you do not control.
        "e2e_encryption": True,
    }


def load_settings() -> Dict[str, Any]:
    out = _defaults()
    fp = config_path()
    try:
        if fp.exists():
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            if isinstance(data, dict):
                out.update(data)
    except Exception:
        pass
    return out


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    cur = load_settings()
    cur.update(patch or {})
    fp = config_path()
    tmp = fp.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2, ensure_ascii=False)
    os.replace(tmp, fp)
    return cur


def normalize_transport(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in TRANSPORTS else TRANSPORT_LAN


def normalize_device_mode(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in DEVICE_MODES else DEVICE_MODE_FULL


def get_port(settings: Dict[str, Any] | None = None) -> int:
    s = settings or load_settings()
    try:
        p = int(s.get("port") or DEFAULT_PORT)
    except Exception:
        p = DEFAULT_PORT
    return p if 1 <= p <= 65535 else DEFAULT_PORT
