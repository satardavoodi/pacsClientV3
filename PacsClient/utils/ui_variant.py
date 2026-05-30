"""Parallel UI-variant flag for the AI-PACS design migration.

The new ("v2") design language is rolled out ALONGSIDE the current UI ("v1")
without modifying it. The default is always ``"v1"`` so the live clinical
workstation is unchanged unless someone explicitly opts in.

Resolution order (first match wins):
  1. Environment variable ``AIPACS_UI_VARIANT`` (handy for testing).
  2. ``<USER_DATA_ROOT>/config/ui_variant.json`` (or ``config/ui_variant.json``).
  3. Default ``"v1"``.

The JSON file may also carry per-module overrides so a single area can be
flipped to v2 while the rest stays v1::

    {"variant": "v1", "modules": {"home": "v2"}}

This function never raises; on any error it returns ``"v1"`` so the parallel
layer can never break the live UI. See
``docs/design/CLAUDE_DESIGN_WORKSTATION_V1_PLAN.md``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_VALID = {"v1", "v2"}
MODULES = ("home", "viewer", "echomind", "eagle_eye", "education", "printing", "settings")


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
    """Return ``"v1"`` (default) or ``"v2"``.

    Pass ``module`` (one of :data:`MODULES`) to honour a per-module override.
    Never raises; any failure falls back to ``"v1"``.
    """
    try:
        data = _load()
        variant = data.get("variant", "v1")
        if module:
            modules = data.get("modules") or {}
            if isinstance(modules, dict):
                variant = modules.get(module, variant)
        return variant if variant in _VALID else "v1"
    except Exception:
        return "v1"
