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
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .portable_viewer.viewer_meta import VIEWER_DISPLAY_NAME, VIEWER_EXE_NAME

ENV_OVERRIDE = "AIPACS_LITE_VIEWER_PATH"
LITE_DIST_DIRNAME = "lightViewer_dist"
LITE_BUNDLE_DIRNAME = "AIPacsLiteViewer"
LEGACY_DIRNAME = "lightViewer"


def _module_root() -> Path:
    """``modules/cd_burner`` directory (works in source and frozen layouts)."""
    return Path(__file__).resolve().parent


def _candidate_roots() -> List[Path]:
    """All plausible ``modules/cd_burner`` locations, most-specific first.

    Covers source runs, the run_cd plugin payload, and frozen layouts
    (PyInstaller ``_MEIPASS``/``_internal``, Nuitka, installed exe dir) so
    the bundled viewer is found no matter which channel shipped it.
    """
    roots: List[Path] = []
    seen = set()

    def add(path: Optional[Path]):
        if path is None:
            return
        try:
            resolved = Path(path).resolve()
        except Exception:
            return
        key = str(resolved).lower()
        if key not in seen:
            seen.add(key)
            roots.append(resolved)

    add(_module_root())  # next to this file (source + most frozen layouts)

    rel = Path("modules") / "cd_burner"

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            add(Path(meipass) / rel)
        try:
            exe_dir = Path(sys.executable).resolve().parent
            add(exe_dir / rel)
            add(exe_dir / "_internal" / rel)
        except Exception:
            pass

    # Installed run_cd plugin payload — the authoritative copy in the
    # PyInstaller build, where cd_burner code loads from the payload (it is
    # excluded from the engine), not from engine datas. Best-effort.
    try:
        from aipacs_runtime import bundled_module_packages_search_roots

        for mp_root in bundled_module_packages_search_roots():
            add(Path(mp_root) / "run_cd" / "payload" / "python" / rel)
    except Exception:
        pass
    return roots


def _bundle_size_mb(path: Path) -> float:
    """Total size (MB) of what actually gets burned for this viewer.

    A PyInstaller onedir bundle (the exe sits next to an ``_internal`` folder)
    is copied to the disc as a TREE, so report the WHOLE bundle directory — not
    just the ~6 MB bootloader exe — so the UI honestly reflects everything that
    lands on the media (exe + ``_internal`` + Qt/codecs). A lone single-exe
    viewer (no ``_internal``) reports its own size, matching the exe-only copy.
    """
    try:
        bundle_dir = path.parent
        if (bundle_dir / "_internal").is_dir():
            total = 0
            for f in bundle_dir.rglob("*"):
                try:
                    if f.is_file():
                        total += f.stat().st_size
                except OSError:
                    continue
            return total / (1024 * 1024)
        if path.is_file():
            return path.stat().st_size / (1024 * 1024)
    except OSError:
        pass
    return 0.0


def _describe(path: Path, kind: str, display_name: str) -> Dict[str, Any]:
    return {
        "path": str(path),
        "kind": kind,                     # "lite" | "legacy" | "override"
        "display_name": display_name,
        "size_mb": round(_bundle_size_mb(path), 1),
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

    roots = _candidate_roots()

    # Prefer the built lite viewer in any candidate location.
    for root in roots:
        lite_exe = root / LITE_DIST_DIRNAME / LITE_BUNDLE_DIRNAME / VIEWER_EXE_NAME
        if lite_exe.is_file():
            return _describe(lite_exe, "lite", VIEWER_DISPLAY_NAME)

    # Legacy fallback (older installs that still carry lightViewer/*.exe).
    for root in roots:
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
