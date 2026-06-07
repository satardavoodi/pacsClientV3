"""Imaging-center identity for burned media (name / address / phone).

Per-system configuration stored alongside the other CD settings in
``<roaming config>/lightviewer_settings.json``. Entered once in the Write
CD dialog, reloaded automatically on every later burn, and stamped into
the media manifest so the portable viewer can display who created the disc.
"""

from __future__ import annotations

import json
import logging
from typing import Dict

logger = logging.getLogger(__name__)

_FIELDS = ("center_name", "center_address", "center_phone")


def _config_file():
    from aipacs_runtime import roaming_config_root

    root = roaming_config_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "lightviewer_settings.json"


def load_center_identity() -> Dict[str, str]:
    """Saved identity (empty strings when not configured). Never raises."""
    identity = {field: "" for field in _FIELDS}
    try:
        path = _config_file()
        if path.exists():
            settings = json.loads(path.read_text(encoding="utf-8"))
            for field in _FIELDS:
                identity[field] = str(settings.get(field, "") or "").strip()
    except Exception as exc:
        logger.warning("Could not load center identity: %s", exc)
    return identity


def save_center_identity(name: str, address: str, phone: str) -> bool:
    """Persist the identity, preserving all other keys in the file."""
    try:
        path = _config_file()
        settings = {}
        if path.exists():
            try:
                settings = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                settings = {}
        settings["center_name"] = (name or "").strip()
        settings["center_address"] = (address or "").strip()
        settings["center_phone"] = (phone or "").strip()
        path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as exc:
        logger.warning("Could not save center identity: %s", exc)
        return False


def identity_to_media_dict(name: str, address: str, phone: str) -> Dict[str, str]:
    """Normalized dict for the media manifest (only meaningful when any set)."""
    return {
        "name": (name or "").strip(),
        "address": (address or "").strip(),
        "phone": (phone or "").strip(),
    }
