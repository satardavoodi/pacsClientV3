"""Runtime provenance marker for the Zeta MPR geometry pipeline.

Emits ONE log line (per process) that pins down *which* MPR geometry
implementation actually loaded and from where. This exists because the frozen
build uses ``module_collection_mode={"modules": "pyz+py"}`` — at runtime the
PYZ bytecode is imported, NOT the on-disk ``engine/modules/...py``. A stale or
mis-packaged build can therefore run old geometry while the on-disk files look
current. This marker makes that visible in ``app.log`` instead of silent; the
authoritative bytecode check is the build-time gate
(``builder/audit/scripts/verify_mpr_in_pyz.py``).

The fingerprint checks class-level symbols that the corrected geometry
introduced, so a "regressed" build (old geometry) reports ``geometry_ok=False``
right at the first MPR open.
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

_LOGGED = False

# Class-level attributes proving the corrected geometry/routing/projection are loaded.
_REQUIRED_CLASS_ATTRS = (
    "_view_axes",                       # per-pane (look,h,v) routing (sagittal-native fix)
    "_apply_native_plane_interpolation",  # native plane shows acquired slices
    "_anatomical_camera",               # matrix-driven canonical cameras
)


def _app_version() -> str:
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            v = app.applicationVersion()
            if v:
                return str(v)
    except Exception:
        pass
    return "unknown"


def log_mpr_geometry_provenance(viewer_cls) -> bool:
    """Log the MPR geometry provenance once. Returns the geometry_ok flag.

    ``viewer_cls`` is the StandardMPRViewer class (passed in to avoid an import
    cycle). Never raises — provenance logging must not break opening the viewer.
    """
    global _LOGGED
    try:
        # Resolve the orientation module that actually loaded (frozen or source).
        ori = sys.modules.get("modules.mpr.zeta_mpr.mpr_viewer._mpr_orientation")
        path = getattr(ori, "__file__", "<unknown>") if ori is not None else "<not-imported>"
        loader = type(getattr(ori, "__loader__", None)).__name__ if ori is not None else "<none>"
        frozen = bool(getattr(sys, "frozen", False))

        missing = [a for a in _REQUIRED_CLASS_ATTRS if not hasattr(viewer_cls, a)]
        try:
            import inspect

            has_projection = "layout_views" in inspect.signature(viewer_cls.__init__).parameters
        except Exception:
            has_projection = False

        # _force_crosshair_on_top lives on the crosshair-render mixin/module.
        has_crosshair_ontop = hasattr(viewer_cls, "_force_crosshair_on_top")
        if not has_crosshair_ontop:
            cr = sys.modules.get("modules.mpr.zeta_mpr.mpr_viewer._mpr_crosshair_render")
            has_crosshair_ontop = bool(cr is not None and hasattr(cr, "_force_crosshair_on_top"))

        geometry_ok = (not missing) and has_projection and has_crosshair_ontop

        if not _LOGGED:
            _LOGGED = True
            logger.info(
                "[MPR_GEOMETRY_PROVENANCE] impl=zeta_mpr geometry_ok=%s frozen=%s "
                "loader=%s version=%s path=%s",
                geometry_ok, frozen, loader, _app_version(), path,
            )
            logger.info(
                "[MPR_GEOMETRY_PROVENANCE] fingerprint: view_axes=%s native_interp=%s "
                "anatomical_camera=%s projection=%s crosshair_on_top=%s missing=%s",
                "_view_axes" not in missing,
                "_apply_native_plane_interpolation" not in missing,
                "_anatomical_camera" not in missing,
                has_projection, has_crosshair_ontop, missing or "none",
            )
            if not geometry_ok:
                logger.error(
                    "[MPR_GEOMETRY_PROVENANCE] STALE/REGRESSED geometry loaded — the "
                    "packaged MPR code is older than the corrected geometry. Rebuild with "
                    "--clean-build; the build-time PYZ gate should also have caught this."
                )
        return geometry_ok
    except Exception as exc:  # never break the viewer
        logger.debug("[MPR_GEOMETRY_PROVENANCE] provenance log failed: %r", exc)
        return True
