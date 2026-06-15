"""Feature flag for the Identity module.

Resolution order (mirrors :mod:`PacsClient.utils.ui_variant`):
  1. Environment variable ``AIPACS_IDENTITY_MODULE`` (1/true/on/yes vs 0/false/off/no)
  2. Config file ``config/identity/identity.json`` -> ``{"enabled": true}``
  3. Default: **OFF**

When OFF, the Identity module is never imported in the hot path and the account
area / login behave byte-identically to today.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_ENV_VAR = "AIPACS_IDENTITY_MODULE"
_TRUE = {"1", "true", "on", "yes", "enabled"}
_FALSE = {"0", "false", "off", "no", "disabled"}


def identity_module_enabled() -> bool:
    """Return True only if explicitly enabled via env or config. Never raises."""
    # 1) Environment override
    raw = os.environ.get(_ENV_VAR)
    if raw is not None:
        val = raw.strip().lower()
        if val in _TRUE:
            return True
        if val in _FALSE:
            return False

    # 2) Config file (no directory is created here — a disabled module must have
    #    zero filesystem side effects at startup).
    try:
        from modules.Identity.config import identity_flag_file_path

        path = identity_flag_file_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "enabled" in data:
                return bool(data["enabled"])
    except Exception as exc:
        logger.debug("identity flag config read failed: %s", exc)

    # 3) Default OFF
    return False
