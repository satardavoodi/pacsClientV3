"""Feature flag for the Agent Gateway (default OFF).

Resolution (identical shape to ``modules/cloud_consultation/feature_flags.py``):

    env ``AIPACS_AGENT_GATEWAY``  →  ``config/agent_gateway/agent_gateway.json``
    (``"enabled"``)  →  default **OFF**.

Import-cheap and never raises: a disabled gateway has no startup side effects.
The env var is the operator kill switch / force switch; the config ``enabled``
flag is what the Settings ▸ Agent tab toggles.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

_ENV_VAR = "AIPACS_AGENT_GATEWAY"
_TRUE = {"1", "true", "on", "yes", "enabled"}
_FALSE = {"0", "false", "off", "no", "disabled"}


def _env_override() -> bool | None:
    raw = os.environ.get(_ENV_VAR)
    if raw is None:
        return None
    val = raw.strip().lower()
    if val in _TRUE:
        return True
    if val in _FALSE:
        return False
    return None


def agent_gateway_enabled() -> bool:
    """True when the gateway should run. env wins, else config, else OFF."""
    override = _env_override()
    if override is not None:
        return override
    try:
        from .config_store import load_settings

        return bool(load_settings().get("enabled"))
    except Exception as exc:  # pragma: no cover - must never break startup
        logger.debug("agent_gateway flag read failed: %s", exc)
        return False


def gateway_config_summary() -> Dict[str, Any]:
    """A non-secret snapshot for the Settings tab / diagnostics.

    Never includes tokens or key material — only booleans, the transport, the
    port, and the configured (but not resolved) relay URL presence.
    """
    try:
        from .config_store import load_settings, normalize_transport, get_port

        s = load_settings()
        return {
            "enabled": bool(s.get("enabled")),
            "env_override": _env_override(),
            "transport": normalize_transport(s.get("transport")),
            "port": get_port(s),
            "tls_enabled": bool(s.get("tls_enabled", True)),
            "mcp_enabled": bool(s.get("mcp_enabled", True)),
            "mcp_path": str(s.get("mcp_path") or "/mcp"),
            "default_device_mode": str(s.get("default_device_mode") or "full"),
            "relay_configured": bool(str(s.get("relay_base_url") or "").strip()),
        }
    except Exception:
        return {"enabled": False, "transport": "lan", "port": 8760}
