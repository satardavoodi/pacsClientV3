"""Locate the viewer executable to bundle on patient CD/DVD media.

Resolution order for the DEFAULT AI-PACS viewer:

1. ``AIPACS_LITE_VIEWER_PATH`` environment override (file, or a directory
   that contains the lite viewer exe) — used by tests and power users.
2. The built lite viewer bundle:
   ``modules/cd_burner/lightViewer_dist/AIPacsLiteViewer/AIPacsLiteViewer.exe``
   (produced by ``tools/build/build_lite_viewer.py``).
3. Legacy fallback: any ``*.exe`` in ``modules/cd_burner/lightViewer/``
   (prefers ``AiPacs.exe``) so existing installations keep working until
   the lite viewer is built.

The CUSTOM viewer (user-selected ``.exe`` in Settings) is resolved by the
settings widget, not here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from .portable_viewer.viewer_meta import VIEWER_DISPLAY_NAME, VIEWER_EXE_NAME

ENV_OVERRIDE = "AIPACS_LITE_VIEWER_PATH"
LITE_DIST_DIRNAME = "lightViewer_dist"
LITE_BUNDLE_DIRNAME = "AIPacsLiteViewer"
LEGACY_DIRNAME = "lightViewer"


def _module_root() -> Path:
    """``modules/cd_burner`` directory (works in source and frozen layouts)."""
    return Path(__file__).resolve().parent


def _describe(path: Path, kind: str, display_name: str) -> Dict[str, Any]:
    size_mb = 0.0
    try:
        if path.is_file():
            size_mb = path.stat().st_size / (1024 * 1024)
    except OSError:
        pass
    return {
        "path": str(path),
        "kind": kind,                     # "lite" | "legacy" | "override"
        "display_name": display_name,
        "size_mb": round(size_mb, 1),
    }


def _resolve_env_override() -> Optional[Dict[str, Any]]:
    raw = os.environ.get(ENV_OVERRIDE, "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_dir():
        exe = candidate / VIEWER_EXE_NAME
        if not exe.is_file():
            exes = sorted(candidate.glob("*.exe"))
            exe = exes[0] if exes else None
        candidate = exe
    if candidate and candidate.is_file() and candidate.suffix.lower() == ".exe":
        return _describe(candidate, "override", VIEWER_DISPLAY_NAME)
    return None


def resolve_default_viewer() -> Optional[Dict[str, Any]]:
    """Return info about the default AI-PACS viewer bundle, or None."""
    override = _resolve_env_override()
    if override:
        return override

    root = _module_root()

    lite_exe = root / LITE_DIST_DIRNAME / LITE_BUNDLE_DIRNAME / VIEWER_EXE_NAME
    if lite_exe.is_file():
        return _describe(lite_exe, "lite", VIEWER_DISPLAY_NAME)

    legacy_dir = root / LEGACY_DIRNAME
    if legacy_dir.is_dir():
        legacy_exes = sorted(p for p in legacy_dir.glob("*.exe") if p.is_file())
        if legacy_exes:
            preferred = next(
                (p for p in legacy_exes if p.name.lower() == "aipacs.exe"),
                legacy_exes[0],
            )
            return _describe(preferred, "legacy", f"AI-PACS Viewer ({preferred.stem})")

    return None


def default_viewer_hint() -> str:
    """One-line, user-facing hint about default viewer availability."""
    info = resolve_default_viewer()
    if info is None:
        return (
            "Default AI-PACS portable viewer not found. Build it with "
            "tools\\build\\build_lite_viewer.bat (or configure a custom viewer)."
        )
    if info["kind"] == "legacy":
        return (
            f"Using legacy bundled viewer: {Path(info['path']).name} "
            f"({info['size_mb']} MB). Build the Lite Viewer for a smaller, "
            "faster disc viewer."
        )
    return f"{info['display_name']} ready ({info['size_mb']} MB)."
