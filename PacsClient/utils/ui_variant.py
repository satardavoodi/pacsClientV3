"""Parallel UI-variant flag for the AI-PACS design migration.

The ("v2") design language is now the **default** for new installs and new
builds — it ships as the active workstation appearance. The legacy ("v1")
design is preserved as an alternate / backup variant: it stays callable from
every `apply_*_v2()` wrapper (each one no-ops back to V1 when the flag is
``"v1"``), and can be re-activated by anyone who wants the old look.

Resolution order (first match wins):
  1. Environment variable ``AIPACS_UI_VARIANT`` (handy for testing).
  2. ``<USER_DATA_ROOT>/config/ui_variant.json`` (or ``config/ui_variant.json``).
  3. Default ``"v2"`` — the current shipping design.

The JSON file may also carry per-module overrides so a single area can be
forced to V1 while the rest stays V2 (or vice versa)::

    {"variant": "v2", "modules": {"home": "v1"}}

To roll the whole workstation back to V1, drop one of:

    # via env var (single session)
    set AIPACS_UI_VARIANT=v1

    # via config file (persistent)
    echo {"variant": "v1"} > <USER_DATA_ROOT>/config/ui_variant.json

This function never raises; on any error it returns ``"v2"`` so a missing
config file or corrupt JSON can never strand a user on the legacy UI. See
``docs/design/CLAUDE_DESIGN_WORKSTATION_V1_PLAN.md`` and
``docs/design/THEME_SYSTEM_REVIEW_2026-05-30.md``.

Default flipped from "v1" → "v2" on 2026-05-31 after the V2 design language
matured through the home + viewer + theme passes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_VALID = {"v1", "v2"}
MODULES = ("home", "viewer", "echomind", "eagle_eye", "education", "printing", "settings")

# Build-time default for the workstation design language. Flipping this one
# constant changes the default for every call site. To restore V1-as-default
# globally, set this back to "v1" — no other code change required.
_BUILD_DEFAULT_VARIANT = "v2"


def _config_path() -> Path:
    try:
        from PacsClient.utils.data_paths import USER_DATA_ROOT

        return Path(USER_DATA_ROOT) / "config" / "ui_variant.json"
    except Exception:
        return Path("config") / "ui_variant.json"


def _load() -> dict:
    data: dict = {}
    try:
        path = _config_path()
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
    except Exception:
        data = {}

    env = os.environ.get("AIPACS_UI_VARIANT")
    if env in _VALID:
        data["variant"] = env
    return data


def get_ui_variant(module: str | None = None) -> str:
    """Return ``"v2"`` (default) or ``"v1"`` (legacy backup).

    Pass ``module`` (one of :data:`MODULES`) to honour a per-module override.
    Never raises; any failure falls back to the build default (``"v2"``).
    """
    try:
        data = _load()
        variant = data.get("variant", _BUILD_DEFAULT_VARIANT)
        if module:
            modules = data.get("modules") or {}
            if isinstance(modules, dict):
                variant = modules.get(module, variant)
        return variant if variant in _VALID else _BUILD_DEFAULT_VARIANT
    except Exception:
        return _BUILD_DEFAULT_VARIANT
