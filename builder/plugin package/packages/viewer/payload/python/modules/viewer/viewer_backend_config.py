"""Viewer backend settings persistence.

Stores the preferred 2D backend for patient-tab viewers.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from PacsClient.utils.config import SOCKET_CONFIG_PATH
from aipacs_runtime import SAFE_VIEWER_BACKEND_DEFAULT, SAFE_VIEWER_BACKEND_ENV

logger = logging.getLogger(__name__)


BACKEND_VTK = "vtk_simpleitk"
BACKEND_PYDICOM = "pydicom_2d"
BACKEND_PYDICOM_QT = "pydicom_qt"   # VTK-free 2D via PyDicom + OpenCV + QPainter
# v2.3.3+: FAST (pydicom_qt) is the default.  Advanced (vtk_simpleitk) must be
# explicitly requested via viewer_backend_settings.json or force_vtk metadata.
DEFAULT_BACKEND = BACKEND_PYDICOM_QT


def _config_path() -> Path:
    cfg_dir = Path(SOCKET_CONFIG_PATH)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir / "viewer_backend_settings.json"


def load_viewer_backend(default: str = DEFAULT_BACKEND) -> str:
    path = _config_path()
    try:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        value = str(data.get("viewer_2d_backend", default)).strip().lower()
        if value not in {BACKEND_VTK, BACKEND_PYDICOM, BACKEND_PYDICOM_QT}:
            return default
        return value
    except Exception:
        return default


def _normalize_backend(value: str, default: str = DEFAULT_BACKEND) -> str:
    backend = str(value or "").strip().lower()
    if backend in {BACKEND_VTK, BACKEND_PYDICOM, BACKEND_PYDICOM_QT}:
        return backend
    fallback = str(default or "").strip().lower()
    if fallback in {BACKEND_VTK, BACKEND_PYDICOM, BACKEND_PYDICOM_QT}:
        return fallback
    return "" if default == "" else DEFAULT_BACKEND


def resolve_viewer_backend(metadata=None, settings=None) -> dict:
    """Single authoritative backend decision function.

    Returns a dict:
    - backend: selected backend after guards/fallback
    - requested_backend: backend requested from settings/policy
    - metadata_backend: backend annotation found in metadata (if any)
    - lazy_loader_key: lazy loader key from metadata (if any)
    - metadata_complete: bool for metadata validity under selected backend
    - force_vtk_fallback: bool
    """
    settings_backend = None
    if isinstance(settings, dict):
        settings_backend = settings.get("viewer_2d_backend")
    elif settings is not None:
        settings_backend = settings
    configured_backend = _normalize_backend(settings_backend or load_viewer_backend(default=DEFAULT_BACKEND))
    forced_backend = _normalize_backend(
        os.environ.get(SAFE_VIEWER_BACKEND_ENV, "").strip().lower(),
        default="",
    )
    safe_backend_forced = bool(
        forced_backend in {BACKEND_PYDICOM, BACKEND_PYDICOM_QT}
        and configured_backend in {BACKEND_VTK, BACKEND_PYDICOM}
    )
    requested_backend = forced_backend if safe_backend_forced else configured_backend

    # v2.3.3 Stage 2: Emergency escape hatch — revert FAST to the old VTK
    # lazy-hybrid backend without a code change.  Set the env var to "1"
    # and restart the application.
    _force_legacy = os.environ.get("AIPACS_FORCE_PYDICOM_2D", "").strip() == "1"
    if _force_legacy and requested_backend in {BACKEND_PYDICOM_QT, BACKEND_PYDICOM}:
        logger.warning(
            "[BACKEND_SWITCH_V2.3.3] AIPACS_FORCE_PYDICOM_2D=1 — "
            "overriding %s -> %s (emergency escape hatch)",
            requested_backend, BACKEND_PYDICOM,
        )
        requested_backend = BACKEND_PYDICOM

    # v2.3.3: PYDICOM (pydicom_2d) is deprecated for FAST mode.
    # Remap to PYDICOM_QT unconditionally — the VTK lazy hybrid is no longer
    # the default path.  This safety net ensures even stale config files
    # or manual overrides resolve to the Qt-native path.
    # Note: force_vtk_fallback from metadata is applied downstream and will
    # override to BACKEND_VTK if set, so the alias is always safe here.
    # Note: The escape hatch above intentionally bypasses this remap.
    if requested_backend == BACKEND_PYDICOM and not _force_legacy:
        logger.info(
            "[BACKEND_SWITCH_V2.3.3] Remapping deprecated BACKEND_PYDICOM "
            "(%s) -> BACKEND_PYDICOM_QT (%s) for FAST mode",
            BACKEND_PYDICOM, BACKEND_PYDICOM_QT,
        )
        requested_backend = BACKEND_PYDICOM_QT

    series_meta = {}
    instances = []
    if isinstance(metadata, dict):
        raw_series_meta = metadata.get("series")
        if isinstance(raw_series_meta, dict):
            series_meta = raw_series_meta
        instances = metadata.get("instances", []) or []

    metadata_backend_raw = series_meta.get("viewer_backend")
    metadata_backend = _normalize_backend(metadata_backend_raw, default=requested_backend) if metadata_backend_raw else ""
    lazy_loader_key = str(series_meta.get("lazy_loader_key", "") or "").strip()
    force_vtk_fallback = bool(series_meta.get("force_vtk_fallback", False))
    requested_is_advanced = requested_backend == BACKEND_VTK

    backend = requested_backend
    metadata_complete = True

    # Keep FAST and Advanced pipelines independent: metadata-level VTK fallback
    # is honored only when Advanced is explicitly requested.
    if force_vtk_fallback and requested_is_advanced:
        backend = BACKEND_VTK

    # When metadata says PyDicom but no loader key survived start/switch/reset,
    # enforce immediate deterministic fallback.
    if backend == BACKEND_PYDICOM and metadata_backend == BACKEND_PYDICOM and not lazy_loader_key:
        backend = BACKEND_VTK
        metadata_complete = False

    # BACKEND_PYDICOM_QT does not need lazy_loader_key — it manages its own
    # Lightweight2DPipeline from metadata instances directly.
    # No fallback needed if metadata has instances.
    if backend == BACKEND_PYDICOM_QT:
        if not instances:
            backend = BACKEND_VTK
            metadata_complete = False

    if safe_backend_forced and backend in {BACKEND_VTK, BACKEND_PYDICOM} and instances:
        backend = BACKEND_PYDICOM_QT
        metadata_complete = True

    # NOTE: pydicom_2d renders through VTK.  When Mesa software-rendering
    # DLLs are present the VTK pipeline works correctly.  When they are
    # missing, build_windows_graphics_environment() sets
    # AIPACS_FORCE_SAFE_VIEWER_BACKEND=pydicom_qt and the guard above
    # promotes pydicom_2d → pydicom_qt automatically (same as vtk_simpleitk).

    return {
        "backend": backend,
        "configured_backend": configured_backend,
        "requested_backend": requested_backend,
        "metadata_backend": metadata_backend,
        "lazy_loader_key": lazy_loader_key,
        "metadata_complete": metadata_complete,
        "force_vtk_fallback": force_vtk_fallback,
        "safe_backend_forced": safe_backend_forced,
        "safe_backend_reason": (
            "Software OpenGL runtime is unavailable, so the workstation is forcing "
            f"{requested_backend or SAFE_VIEWER_BACKEND_DEFAULT} as the safe CPU viewer backend."
            if safe_backend_forced
            else ""
        ),
    }


def save_viewer_backend(backend: str) -> bool:
    value = str(backend or "").strip().lower()
    if value not in {BACKEND_VTK, BACKEND_PYDICOM, BACKEND_PYDICOM_QT}:
        value = DEFAULT_BACKEND
    payload = {"viewer_2d_backend": value}
    path = _config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False
