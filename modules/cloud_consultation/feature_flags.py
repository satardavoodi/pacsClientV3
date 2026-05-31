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


def cloud_consultation_enabled() -> bool:
    raw = os.environ.get(_ENV_VAR)
    if raw is not None:
        val = raw.strip().lower()
        if val in _TRUE:
            return True
        if val in _FALSE:
            return False
    try:
        path = _flag_file_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "enabled" in data:
                return bool(data["enabled"])
    except Exception as exc:
        logger.debug("cloud_consultation flag read failed: %s", exc)
    return False
