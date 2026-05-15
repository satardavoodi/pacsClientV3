"""VTK Orientation Bridge — mirror SourceGeometry into VTK image data.

VTK (vtkmodules) stores orientation in several fields:
  - vtkImageData.GetDirectionMatrix() / SetDirectionMatrix()
    (available in VTK ≥ 9.0; not present in older vtkmodules bundles)
  - vtkImageData.SetOrigin(), SetSpacing()
  - ApplyIndexToPhysicalMatrix-style API

This module provides best-effort bridging: it tries the VTK 9 API first and
falls back gracefully.  The absence of a VTK direction matrix does NOT make
the geometry contract invalid — SourceGeometry/DisplayGeometry remain the
sole authority.  VTK orientation is a mirror only.

Log tags emitted (logger.warning, extra={"component": "viewer"}):
    [VTK_ORIENTATION_BRIDGE_STATUS]  — once after every apply attempt
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:
    from modules.viewer.geometry.source_geometry import SourceGeometry
    from modules.viewer.geometry.display_geometry import DisplayGeometry

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# VTK import (optional — VTK may not be present in headless / test envs)
# ─────────────────────────────────────────────────────────────────────────────

try:
    import vtkmodules.vtkCommonDataModel as _vtkdm   # type: ignore
    _VTK_AVAILABLE = True
except ImportError:
    try:
        import vtk as _vtkdm  # type: ignore
        _VTK_AVAILABLE = True
    except ImportError:
        _VTK_AVAILABLE = False
        _vtkdm = None  # type: ignore


def _has_direction_matrix_api(vtk_image_data: object) -> bool:
    """Return True when vtkImageData exposes GetDirectionMatrix / SetDirectionMatrix."""
    return (
        _VTK_AVAILABLE
        and vtk_image_data is not None
        and hasattr(vtk_image_data, "GetDirectionMatrix")
        and hasattr(vtk_image_data, "SetDirectionMatrix")
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def apply_source_geometry_to_vtk(
    vtk_image_data: object,
    sg: "SourceGeometry",
    dg: Optional["DisplayGeometry"] = None,
) -> bool:
    """Mirror the geometry contract into *vtk_image_data*.

    When *dg* is provided, the *effective display* affine (dg.effective_display_ijk_to_lps_4x4)
    is used as the mapping so VTK orientation matches what the user sees.
    When *dg* is ``None``, the raw source affine (sg.raw_ijk_to_lps_4x4) is used.

    Returns ``True`` when the direction matrix was successfully applied,
    ``False`` otherwise (e.g. unsupported VTK version, invalid geometry).
    """
    if vtk_image_data is None:
        _log_status("no_vtk_object", sg, dg, success=False)
        return False

    if not sg.valid:
        _log_status("invalid_source_geometry", sg, dg, success=False)
        return False

    M = dg.effective_display_ijk_to_lps_4x4 if dg is not None else sg.raw_ijk_to_lps_4x4

    # ── Origin: translation column of the affine ──────────────────────────────
    try:
        origin = M[:3, 3].tolist()
        vtk_image_data.SetOrigin(origin[0], origin[1], origin[2])
    except Exception as exc:
        _log_status(f"SetOrigin_failed:{exc}", sg, dg, success=False)
        return False

    # ── Spacing: column norms of the upper-left 3×3 ───────────────────────────
    try:
        spacing = [float(np.linalg.norm(M[:3, c])) for c in range(3)]
        spacing = [s if s > 1e-9 else 1.0 for s in spacing]
        vtk_image_data.SetSpacing(spacing[0], spacing[1], spacing[2])
    except Exception as exc:
        _log_status(f"SetSpacing_failed:{exc}", sg, dg, success=False)
        return False

    # ── Direction matrix (VTK ≥ 9.0) ─────────────────────────────────────────
    if _has_direction_matrix_api(vtk_image_data):
        try:
            # Normalise upper-left 3×3 to pure rotation
            R = M[:3, :3].copy()
            for c in range(3):
                col_n = np.linalg.norm(R[:, c])
                if col_n > 1e-9:
                    R[:, c] /= col_n
            # VTK expects column-major 3×3 (row-major stored)
            vtk_mat = vtk_image_data.GetDirectionMatrix()
            for row in range(3):
                for col in range(3):
                    vtk_mat.SetElement(row, col, float(R[row, col]))
            vtk_image_data.SetDirectionMatrix(vtk_mat)
            _log_status("direction_matrix_applied", sg, dg, success=True, vtk_api="SetDirectionMatrix")
            return True
        except Exception as exc:
            _log_status(f"SetDirectionMatrix_failed:{exc}", sg, dg, success=False, vtk_api="SetDirectionMatrix")
            # Fall through to origin+spacing only
            return False
    else:
        # Origin + Spacing applied; direction unavailable in this VTK build.
        _log_status("origin_spacing_only_no_direction_api", sg, dg, success=True, vtk_api="none")
        return True


def log_vtk_orientation_bridge_status(
    vtk_image_data: object,
    sg: "SourceGeometry",
    dg: Optional["DisplayGeometry"] = None,
) -> None:
    """Emit a status log comparing VTK's stored orientation against the contract.

    Useful for diagnostic assertions and CI geometry-contract tests.
    """
    if vtk_image_data is None or not sg.valid:
        _log_status("query_skipped_invalid_or_no_vtk", sg, dg, success=False)
        return

    try:
        vtk_origin = vtk_image_data.GetOrigin()
        vtk_spacing = vtk_image_data.GetSpacing()
    except Exception:
        _log_status("GetOrigin_GetSpacing_failed", sg, dg, success=False)
        return

    M = dg.effective_display_ijk_to_lps_4x4 if dg is not None else sg.raw_ijk_to_lps_4x4
    expected_origin = M[:3, 3]
    origin_err = float(np.linalg.norm(np.array(vtk_origin[:3], float) - expected_origin))

    has_dm = _has_direction_matrix_api(vtk_image_data)
    dir_err = float("nan")
    if has_dm:
        try:
            vtk_mat = vtk_image_data.GetDirectionMatrix()
            R_vtk = np.array(
                [[vtk_mat.GetElement(r, c) for c in range(3)] for r in range(3)], float
            )
            R_contract = M[:3, :3].copy()
            for c in range(3):
                n = np.linalg.norm(R_contract[:, c])
                if n > 1e-9:
                    R_contract[:, c] /= n
            dir_err = float(np.max(np.abs(R_vtk - R_contract)))
        except Exception:
            pass

    logger.warning(
        "[VTK_ORIENTATION_BRIDGE_STATUS] "
        "viewport=%s series_uid=%s "
        "vtk_origin=(%.3f,%.3f,%.3f) contract_origin=(%.3f,%.3f,%.3f) origin_err_mm=%.4f "
        "vtk_spacing=(%.4f,%.4f,%.4f) "
        "has_direction_matrix=%s direction_err=%s "
        "source_valid=%s",
        dg.viewport_id if dg is not None else "n/a", sg.series_uid,
        vtk_origin[0], vtk_origin[1], vtk_origin[2],
        expected_origin[0], expected_origin[1], expected_origin[2],
        origin_err,
        vtk_spacing[0], vtk_spacing[1], vtk_spacing[2],
        has_dm,
        f"{dir_err:.6f}" if not np.isnan(dir_err) else "n/a",
        sg.valid,
        extra={"component": "viewer"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Internal
# ─────────────────────────────────────────────────────────────────────────────

def _log_status(
    status: str,
    sg: "SourceGeometry",
    dg: Optional["DisplayGeometry"],
    *,
    success: bool,
    vtk_api: str = "unknown",
) -> None:
    logger.warning(
        "[VTK_ORIENTATION_BRIDGE_STATUS] "
        "status=%s vtk_api=%s "
        "viewport=%s series_uid=%s source_valid=%s "
        "success=%s vtk_available=%s",
        status, vtk_api,
        dg.viewport_id if dg is not None else "n/a",
        sg.series_uid if sg is not None else "n/a",
        sg.valid if sg is not None else "n/a",
        success, _VTK_AVAILABLE,
        extra={"component": "viewer"},
    )
