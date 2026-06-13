"""Feature flag for the cloud-consultation layer (default OFF).

Resolution: env ``AIPACS_CLOUD_CONSULTATION`` → ``config/cloud_consultation/cloud_consultation.json``
→ default OFF. Path resolution never creates directories (a disabled module has no
startup side effects). Independent from the Identity flag, but in practice cloud
consultation is only useful once a Google identity is connected.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_VAR = "AIPACS_CLOUD_CONSULTATION"
_TRUE = {"1", "true", "on", "yes", "enabled"}
_FALSE = {"0", "false", "off", "no", "disabled"}
_FLAG_FILE = "cloud_consultation.json"


def _config_root() -> Path:
    try:
        if getattr(sys, "frozen", False):
            from aipacs_runtime import roaming_config_root, seed_user_config_defaults

            seed_user_config_defaults()
            return Path(roaming_config_root())
        from _project_root import PROJECT_ROOT

        return Path(PROJECT_ROOT) / "config"
    except Exception:  # pragma: no cover
        return Path.home() / ".aipacs" / "config"


def _flag_file_path() -> Path:
    return _config_root() / "cloud_consultation" / _FLAG_FILE


def _flag_payload() -> dict:
    try:
        path = _flag_file_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.debug("cloud_consultation flag read failed: %s", exc)
    return {}


def cloud_consultation_enabled() -> bool:
    raw = os.environ.get(_ENV_VAR)
    if raw is not None:
        val = raw.strip().lower()
        if val in _TRUE:
            return True
        if val in _FALSE:
            return False
    data = _flag_payload()
    if "enabled" in data:
        return bool(data["enabled"])
    return False


# ── hub-account mode (R1 §4.4 option (a), owner-approved 2026-06-10) ──────────
# Both workstations connect the SAME shared Google account; all consultations
# live in one Drive, so cross-account detection works under drive.file. Routing
# between physicians then needs an app-level address (NOT the Drive account):
# each workstation declares its own "consultation address", and assignment /
# inbox matching use it instead of the Google handle.

_HUB_ENV = "AIPACS_CONSULTATION_HUB_MODE"
_ADDR_ENV = "AIPACS_CONSULTATION_ADDRESS"


def hub_mode_enabled() -> bool:
    """True when consultations run over a shared hub Drive account."""
    raw = os.environ.get(_HUB_ENV)
    if raw is not None:
        val = raw.strip().lower()
        if val in _TRUE:
            return True
        if val in _FALSE:
            return False
    return bool(_flag_payload().get("hub_mode"))


def consultation_address(default: str = "", aipacs_user: str | None = None) -> str:
    """The physician routing address for THIS workstation (hub mode).

    Resolution: env → ``consultation_address`` in the flag file →
    (ADR-0008) the linked aipacs_web identity's attested Gmail for
    ``aipacs_user`` (when given) → ``default`` (callers pass the Google handle
    so personal-account mode is unchanged). Never raises.
    """
    raw = os.environ.get(_ADDR_ENV)
    if raw and raw.strip():
        return raw.strip().lower()
    addr = str(_flag_payload().get("consultation_address") or "").strip().lower()
    if addr:
        return addr
    if aipacs_user:
        linked = linked_consultation_address(aipacs_user)
        if linked:
            return linked
    return (default or "").strip().lower()


_CENTER_ENV = "AIPACS_CONSULTATION_CENTER_ID"


def center_id(default: str = "") -> str:
    """The imaging-center id this workstation reports on new consultations.

    Assignment workflow v2 (2026-06-12): an OPTIONAL ``center_id`` key in
    ``config/cloud_consultation/cloud_consultation.json`` (env
    ``AIPACS_CONSULTATION_CENTER_ID`` wins). Creation-only metadata for the
    registry POST — absent/empty means the field is simply not sent. Never
    raises.
    """
    raw = os.environ.get(_CENTER_ENV)
    if raw and raw.strip():
        return raw.strip()
    try:
        cid = str(_flag_payload().get("center_id") or "").strip()
        if cid:
            return cid
    except Exception as exc:  # pragma: no cover - must never break callers
        logger.debug("center_id lookup failed: %s", exc)
    return (default or "").strip()


def linked_consultation_address(aipacs_user: str) -> str:
    """The attested Gmail (or handle) of the linked aipacs_web identity, or "".

    ADR-0008 identity bridge: once a physician has linked their Gmail via the
    transient attestation flow, that address routes their consultations — no
    env var / flag-file edit needed per workstation. Lazy Identity import (this
    module must stay import-cheap); never raises.
    """
    try:
        from modules.Identity.providers.aipacs_web import find_aipacs_web_identity

        ident = find_aipacs_web_identity(aipacs_user)
        if ident is None:
            return ""
        link = (ident.extra or {}).get("link") or {}
        addr = str(link.get("gmail_email") or ident.handle or "").strip().lower()
        return addr
    except Exception as exc:  # pragma: no cover - must never break callers
        logger.debug("linked consultation address lookup failed: %s", exc)
        return ""
