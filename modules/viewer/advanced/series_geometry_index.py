"""SeriesGeometryIndex — Option B explicit affine contract for Advanced VTK viewer.

Architecture:
    Advanced VTK rendering may remain in voxel/index space, but all
    geometry-sensitive logic (orientation markers, reference lines, sync,
    pickers) must use this explicit affine contract instead of relying on
    vtkImageData.GetDirectionMatrix() as the authoritative source of truth.

    vtkImageData direction matrix is IDENTITY in the active rendering
    context (confirmed by audit v2026-05-14 — see ADVANCED_VTK_ORIENTATION_DEEP_AUDIT.md).
    That is ACCEPTABLE under Option B: geometry ownership is external to VTK.

DICOM index convention:
    i = column index   (grows along IOP row_cosines direction)
    j = row index      (grows along IOP col_cosines direction)
    k = slice index    (grows along slice_normal direction)

    DICOM PixelSpacing = [row_spacing, column_spacing]
        row_spacing    = mm per row step     (j-axis physical scale)
        column_spacing = mm per column step  (i-axis physical scale)

    P_lps(i, j, k) =  IPP_first
                    + i * column_spacing * row_cosines
                    + j * row_spacing    * col_cosines
                    + k * slice_spacing  * slice_normal

    IJK_to_LPS columns:
        col 0 = row_cosines  * column_spacing   (i-axis → LPS)
        col 1 = col_cosines  * row_spacing      (j-axis → LPS)
        col 2 = slice_normal * slice_spacing    (k-axis → LPS)
        col 3 = IPP_first                       (origin, homogeneous)

Hard Y-flip compensation (convert_itk2vtk applies arr[:, ::-1, :]):
    After the flip:  j_display = (N_rows - 1) - j_original

    The effective display affine for VTK index (i, j_display, k):
        col 0 = row_cosines  * column_spacing                          (unchanged)
        col 1 = -col_cosines * row_spacing                             (sign flipped)
        col 2 = slice_normal * slice_spacing                           (unchanged)
        col 3 = IPP_first + (N_rows - 1) * row_spacing * col_cosines  (origin shifted)

    Screen-edge directions from effective affine:
        screen_right_lps = normalize(effective_col0) = row_cosines
        screen_up_lps    = normalize(effective_col1) = -col_cosines
    (i.e. increasing j_display = going toward -col_cosines in patient LPS)

Validation conditions (build-time):
    - Non-empty instances list
    - All instances share same IOP (max normal deviation < 2°)
    - IPP projections onto slice_normal are monotonic / regular
    - ijk_to_lps_4x4 determinant > 1e-6 (invertible)
    - orthonormal_error < 0.01 (rotation part is near-orthonormal)

Log tags emitted:
    [ADVANCED_GEOMETRY_AFFINE_CONTRACT]   — per series, after build
    [ADVANCED_EFFECTIVE_DISPLAY_AFFINE]   — per series, after y-flip model
"""

from __future__ import annotations

import hashlib
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_IOP_CONSISTENCY_TOL_DEG: float = 2.0   # max allowed normal deviation across slices
_IPP_REGULARITY_TOL_MM: float = 1.0     # max allowed inter-slice spacing jitter (mm)
_ORTHO_ERROR_WARN: float = 0.02         # warn if orthonormal_error exceeds this
_DET_MIN: float = 1e-6                  # affine is non-invertible below this


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _unit(v: np.ndarray) -> Optional[np.ndarray]:
    """Return normalized vector or None if degenerate."""
    n = float(np.linalg.norm(v))
    if n <= 1e-12:
        return None
    return v / n


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    """Angle in degrees between two non-zero vectors."""
    au = _unit(a)
    bu = _unit(b)
    if au is None or bu is None:
        return float("nan")
    return float(np.degrees(np.arccos(np.clip(np.dot(au, bu), -1.0, 1.0))))


def _mat4_str(m: np.ndarray) -> str:
    """Compact one-line representation of a 4×4 matrix for logging."""
    rows = []
    for r in range(4):
        row = ",".join(f"{m[r, c]:.6f}" for c in range(4))
        rows.append(f"[{row}]")
    return "[" + "|".join(rows) + "]"


def _hash6(data: str) -> str:
    """Return 6-char hex hash of a string (for compact log identifiers)."""
    return hashlib.md5(data.encode()).hexdigest()[:6]


# ─────────────────────────────────────────────────────────────────────────────
# SeriesGeometryIndex
# ─────────────────────────────────────────────────────────────────────────────

class SeriesGeometryIndex:
    """Explicit DICOM-sourced affine contract for the Advanced VTK viewer.

    Build once per series load via ``build_from_instances()``.  Immutable
    after construction — do not mutate fields after build.
    """

    __slots__ = (
        # Raw DICOM geometry
        "row_cosines",
        "col_cosines",
        "slice_normal",
        "pixel_spacing_row",
        "pixel_spacing_col",
        "slice_spacing",
        "origin_ipp",
        "n_rows",
        "n_cols",
        "n_slices",
        # Affines (raw DICOM space)
        "ijk_to_lps_4x4",
        "lps_to_ijk_4x4",
        # Voxel axes (unit vectors)
        "voxel_axis_i_lps",
        "voxel_axis_j_lps",
        "voxel_axis_k_lps",
        # Y-flip model
        "y_flip_detected",
        "origin_adjusted",
        "vtk_pixel_array_transform_ijk",
        "effective_display_ijk_to_lps",
        # Lookup maps
        "index_to_sop_uid",
        "sop_uid_to_display_index",
        "display_index_to_ijk_k",
        # Validation
        "valid",
        "validation_errors",
        "determinant",
        "orthonormal_error",
        "spacing_error",
        # Metadata
        "series_uid",
        "n_instances",
        "ijk_to_lps_hash",
    )

    def __init__(self) -> None:
        self.row_cosines: Optional[np.ndarray] = None
        self.col_cosines: Optional[np.ndarray] = None
        self.slice_normal: Optional[np.ndarray] = None
        self.pixel_spacing_row: float = 1.0
        self.pixel_spacing_col: float = 1.0
        self.slice_spacing: float = 1.0
        self.origin_ipp: Optional[np.ndarray] = None
        self.n_rows: int = 0
        self.n_cols: int = 0
        self.n_slices: int = 0
        self.ijk_to_lps_4x4: Optional[np.ndarray] = None
        self.lps_to_ijk_4x4: Optional[np.ndarray] = None
        self.voxel_axis_i_lps: Optional[np.ndarray] = None
        self.voxel_axis_j_lps: Optional[np.ndarray] = None
        self.voxel_axis_k_lps: Optional[np.ndarray] = None
        self.y_flip_detected: bool = False
        self.origin_adjusted: bool = False
        self.vtk_pixel_array_transform_ijk: Optional[str] = None
        self.effective_display_ijk_to_lps: Optional[np.ndarray] = None
        self.index_to_sop_uid: Dict[int, str] = {}
        self.sop_uid_to_display_index: Dict[str, int] = {}
        self.display_index_to_ijk_k: Dict[int, int] = {}
        self.valid: bool = False
        self.validation_errors: List[str] = []
        self.determinant: float = 0.0
        self.orthonormal_error: float = 0.0
        self.spacing_error: float = 0.0
        self.series_uid: str = ""
        self.n_instances: int = 0
        self.ijk_to_lps_hash: str = ""

    # ─────────────────────────────────────────────────────────────────────────
    # Factory
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def build_from_instances(
        cls,
        instances: List[Dict[str, Any]],
        series_uid: str = "",
        vtk_n_rows: int = 0,
        vtk_n_cols: int = 0,
        vtk_n_slices: int = 0,
        apply_y_flip: bool = True,
    ) -> "SeriesGeometryIndex":
        """Build index from DICOM metadata instance list.

        Parameters
        ----------
        instances:
            List of per-slice DICOM metadata dicts (from ``metadata['instances']``).
            Each dict must contain at minimum:
              - ImageOrientationPatient or image_orientation_patient (6 floats)
              - ImagePositionPatient or image_position_patient (3 floats)
              - PixelSpacing or pixel_spacing (2 floats: [row_spacing, col_spacing])
        series_uid:
            SeriesInstanceUID string for logging.
        vtk_n_rows, vtk_n_cols, vtk_n_slices:
            VTK image data dimensions.  Used to compute effective display affine
            for Y-flip compensation.  If zero, Rows/Columns from first instance
            are used instead.
        apply_y_flip:
            Whether to model the hard Y-flip applied by convert_itk2vtk.
            Should always be True for the Advanced VTK path.
        """
        idx = cls()
        idx.series_uid = series_uid
        idx.n_instances = len(instances)

        errors: List[str] = []

        if not instances:
            errors.append("empty_instances_list")
            idx.validation_errors = errors
            idx.valid = False
            return idx

        # ── 1. Extract IOP from first instance ─────────────────────────────
        first = instances[0]
        iop_raw = (
            first.get("ImageOrientationPatient")
            or first.get("image_orientation_patient")
        )
        if iop_raw is None or len(iop_raw) < 6:
            errors.append("missing_ImageOrientationPatient")
            idx.validation_errors = errors
            idx.valid = False
            return idx

        iop = [float(v) for v in iop_raw[:6]]
        row_cos = _unit(np.array(iop[0:3], dtype=float))
        col_cos = _unit(np.array(iop[3:6], dtype=float))
        if row_cos is None or col_cos is None:
            errors.append("degenerate_IOP_vectors")
            idx.validation_errors = errors
            idx.valid = False
            return idx

        slice_normal = _unit(np.cross(row_cos, col_cos))
        if slice_normal is None:
            errors.append("degenerate_slice_normal_from_IOP")
            idx.validation_errors = errors
            idx.valid = False
            return idx

        idx.row_cosines = row_cos
        idx.col_cosines = col_cos
        idx.slice_normal = slice_normal
        idx.voxel_axis_i_lps = row_cos.copy()
        idx.voxel_axis_j_lps = col_cos.copy()
        idx.voxel_axis_k_lps = slice_normal.copy()

        # ── 2. Check IOP consistency across all slices ──────────────────────
        for k, inst in enumerate(instances):
            iop_k_raw = inst.get("ImageOrientationPatient") or inst.get("image_orientation_patient")
            if iop_k_raw is None or len(iop_k_raw) < 6:
                errors.append(f"missing_IOP_slice_{k}")
                continue
            iop_k = [float(v) for v in iop_k_raw[:6]]
            rc_k = _unit(np.array(iop_k[0:3], dtype=float))
            cc_k = _unit(np.array(iop_k[3:6], dtype=float))
            if rc_k is None or cc_k is None:
                errors.append(f"degenerate_IOP_slice_{k}")
                continue
            n_k = _unit(np.cross(rc_k, cc_k))
            if n_k is not None:
                dev = _angle_deg(slice_normal, n_k)
                if dev > _IOP_CONSISTENCY_TOL_DEG:
                    errors.append(
                        f"inconsistent_IOP_normal_slice_{k}_dev_{dev:.2f}deg"
                    )

        # ── 3. Extract PixelSpacing from first instance ─────────────────────
        ps_raw = first.get("PixelSpacing") or first.get("pixel_spacing")
        if ps_raw is None or len(ps_raw) < 1:
            errors.append("missing_PixelSpacing")
            row_spacing = 1.0
            col_spacing = 1.0
        else:
            ps = [float(v) for v in ps_raw]
            row_spacing = float(ps[0])
            col_spacing = float(ps[1]) if len(ps) > 1 else row_spacing

        idx.pixel_spacing_row = row_spacing
        idx.pixel_spacing_col = col_spacing

        # ── 4. Extract IPP from first instance ─────────────────────────────
        ipp_raw = first.get("ImagePositionPatient") or first.get("image_position_patient")
        if ipp_raw is None or len(ipp_raw) < 3:
            errors.append("missing_ImagePositionPatient")
            idx.validation_errors = errors
            idx.valid = False
            return idx

        origin_ipp = np.array([float(v) for v in ipp_raw[:3]], dtype=float)
        idx.origin_ipp = origin_ipp

        # ── 5. Compute slice spacing from IPP projections ───────────────────
        ipp_list: List[Optional[np.ndarray]] = []
        for inst in instances:
            ipp_k_raw = inst.get("ImagePositionPatient") or inst.get("image_position_patient")
            if ipp_k_raw is not None and len(ipp_k_raw) >= 3:
                ipp_list.append(np.array([float(v) for v in ipp_k_raw[:3]], dtype=float))
            else:
                ipp_list.append(None)

        positions = [
            float(np.dot(ipp_k - origin_ipp, slice_normal)) if ipp_k is not None else None
            for ipp_k in ipp_list
        ]
        valid_positions = [p for p in positions if p is not None]

        if len(valid_positions) < 2:
            errors.append("insufficient_IPP_for_slice_spacing")
            slice_spacing = 1.0
        else:
            diffs = [
                abs(valid_positions[i + 1] - valid_positions[i])
                for i in range(len(valid_positions) - 1)
            ]
            median_diff = float(np.median(diffs))
            slice_spacing = median_diff if median_diff > 1e-6 else 1.0

            # Regularity check
            if diffs:
                max_jitter = max(abs(d - median_diff) for d in diffs)
                idx.spacing_error = float(max_jitter)
                if max_jitter > _IPP_REGULARITY_TOL_MM and len(diffs) > 2:
                    errors.append(
                        f"irregular_IPP_spacing_max_jitter_{max_jitter:.3f}mm"
                    )

        idx.slice_spacing = slice_spacing

        # ── 6. Extract n_rows, n_cols, n_slices ─────────────────────────────
        if vtk_n_rows > 0:
            n_rows = vtk_n_rows
        else:
            n_rows = int(first.get("Rows") or first.get("rows") or 0)
        if vtk_n_cols > 0:
            n_cols = vtk_n_cols
        else:
            n_cols = int(first.get("Columns") or first.get("columns") or 0)
        n_slices = vtk_n_slices if vtk_n_slices > 0 else len(instances)

        idx.n_rows = n_rows
        idx.n_cols = n_cols
        idx.n_slices = n_slices

        # ── 7. Build raw DICOM IJK→LPS affine ──────────────────────────────
        # col 0 = row_cosines * column_spacing
        # col 1 = col_cosines * row_spacing
        # col 2 = slice_normal * slice_spacing
        # col 3 = origin_ipp   (homogeneous)
        M = np.eye(4, dtype=float)
        M[0:3, 0] = row_cos * col_spacing
        M[0:3, 1] = col_cos * row_spacing
        M[0:3, 2] = slice_normal * slice_spacing
        M[0:3, 3] = origin_ipp
        idx.ijk_to_lps_4x4 = M

        # Compute inverse
        det = float(np.linalg.det(M[0:3, 0:3]))
        idx.determinant = det
        if abs(det) < _DET_MIN:
            errors.append(f"non_invertible_affine_det_{det:.6f}")
            idx.valid = False
        else:
            try:
                M_inv = np.eye(4, dtype=float)
                M_inv[0:3, 0:3] = np.linalg.inv(M[0:3, 0:3])
                M_inv[0:3, 3] = -M_inv[0:3, 0:3] @ origin_ipp
                idx.lps_to_ijk_4x4 = M_inv
            except np.linalg.LinAlgError:
                errors.append("linalg_inv_failed")

        # Orthonormality check on rotation part (cols 0-2 normalized)
        R = np.column_stack([
            row_cos,
            col_cos,
            slice_normal,
        ])
        RtR = R.T @ R
        ortho_err = float(np.linalg.norm(RtR - np.eye(3)))
        idx.orthonormal_error = ortho_err
        if ortho_err > _ORTHO_ERROR_WARN:
            errors.append(f"non_orthonormal_rotation_err_{ortho_err:.6f}")

        # Hash for compact identification in logs
        idx.ijk_to_lps_hash = _hash6(_mat4_str(M))

        # ── 8. Build lookup maps ─────────────────────────────────────────────
        for display_idx, inst in enumerate(instances):
            sop = str(inst.get("SOPInstanceUID") or inst.get("sop_uid") or inst.get("sop_instance_uid") or "")
            if sop:
                idx.index_to_sop_uid[display_idx] = sop
                idx.sop_uid_to_display_index[sop] = display_idx
            idx.display_index_to_ijk_k[display_idx] = display_idx  # 1:1 mapping

        # ── 9. Model the Y-flip (always active in Advanced VTK path) ────────
        idx.y_flip_detected = apply_y_flip
        if apply_y_flip and n_rows > 0:
            idx.vtk_pixel_array_transform_ijk = "flip_j"
            # Effective display affine for VTK index (i, j_display, k):
            #   col 0 = row_cosines * col_spacing              (i-axis, unchanged)
            #   col 1 = -col_cosines * row_spacing             (j_display-axis, sign flipped)
            #   col 2 = slice_normal * slice_spacing           (k-axis, unchanged)
            #   col 3 = origin_ipp + (N_rows-1)*row_spacing*col_cosines
            E = np.eye(4, dtype=float)
            E[0:3, 0] = row_cos * col_spacing
            E[0:3, 1] = -col_cos * row_spacing            # sign flipped
            E[0:3, 2] = slice_normal * slice_spacing
            E[0:3, 3] = origin_ipp + (n_rows - 1) * row_spacing * col_cos
            idx.effective_display_ijk_to_lps = E
            idx.origin_adjusted = True
        elif apply_y_flip and n_rows == 0:
            # Y-flip active but N_rows unknown — use raw affine as best effort,
            # log a warning so callers know the origin is not compensated.
            errors.append("y_flip_active_but_n_rows_unknown_origin_uncompensated")
            idx.vtk_pixel_array_transform_ijk = "flip_j_uncompensated"
            idx.effective_display_ijk_to_lps = M.copy()
            idx.origin_adjusted = False
        else:
            idx.vtk_pixel_array_transform_ijk = "identity"
            idx.effective_display_ijk_to_lps = M.copy()
            idx.origin_adjusted = False

        # ── 10. Set validity ─────────────────────────────────────────────────
        fatal = {"empty_instances_list", "missing_ImageOrientationPatient",
                 "degenerate_IOP_vectors", "degenerate_slice_normal_from_IOP",
                 "missing_ImagePositionPatient", "linalg_inv_failed"}
        is_fatal = any(any(f in e for f in fatal) for e in errors)
        idx.valid = (not is_fatal) and abs(det) >= _DET_MIN
        idx.validation_errors = errors

        # ── 11. Emit diagnostic logs ─────────────────────────────────────────
        idx._emit_affine_contract_log()
        idx._emit_effective_display_affine_log()

        return idx

    # ─────────────────────────────────────────────────────────────────────────
    # Screen-edge direction API
    # ─────────────────────────────────────────────────────────────────────────

    def screen_right_lps(self) -> Optional[np.ndarray]:
        """Patient-LPS unit vector corresponding to screen-right.

        Uses the effective display affine (accounts for Y-flip) column 0,
        normalized.  Returns row_cosines when Y-flip is active.
        """
        if self.effective_display_ijk_to_lps is None:
            return self.row_cosines
        return _unit(self.effective_display_ijk_to_lps[0:3, 0])

    def screen_up_lps(self) -> Optional[np.ndarray]:
        """Patient-LPS unit vector corresponding to screen-up (increasing j_display).

        Uses the effective display affine column 1, normalized.
        When Y-flip is active, returns -col_cosines.
        """
        if self.effective_display_ijk_to_lps is None:
            return _unit(-self.col_cosines) if self.col_cosines is not None else None
        return _unit(self.effective_display_ijk_to_lps[0:3, 1])

    # ─────────────────────────────────────────────────────────────────────────
    # Diagnostic log emitters
    # ─────────────────────────────────────────────────────────────────────────

    def _emit_affine_contract_log(self) -> None:
        """Emit [ADVANCED_GEOMETRY_AFFINE_CONTRACT] at WARNING level."""
        try:
            def _v3(v):
                if v is None:
                    return "None"
                return f"({v[0]:.6f},{v[1]:.6f},{v[2]:.6f})"

            M_str = "None"
            Mi_str = "None"
            if self.ijk_to_lps_4x4 is not None:
                M_str = _mat4_str(self.ijk_to_lps_4x4)
            if self.lps_to_ijk_4x4 is not None:
                Mi_str = _mat4_str(self.lps_to_ijk_4x4)

            ps = f"[{self.pixel_spacing_row:.4f},{self.pixel_spacing_col:.4f}]"

            errors_str = ";".join(self.validation_errors) if self.validation_errors else "none"

            logger.warning(
                "[ADVANCED_GEOMETRY_AFFINE_CONTRACT] "
                "series_uid=%s n_instances=%d "
                "row_cosines=%s col_cosines=%s slice_normal=%s "
                "pixel_spacing=%s slice_spacing=%.4f origin_ipp=%s "
                "n_rows=%d n_cols=%d n_slices=%d "
                "ijk_to_lps_4x4=%s lps_to_ijk_4x4=%s "
                "determinant=%.6f orthonormal_error=%.6f spacing_error=%.3f "
                "valid=%s validation_errors=%s ijk_to_lps_hash=%s",
                self.series_uid,
                self.n_instances,
                _v3(self.row_cosines),
                _v3(self.col_cosines),
                _v3(self.slice_normal),
                ps,
                self.slice_spacing,
                _v3(self.origin_ipp),
                self.n_rows,
                self.n_cols,
                self.n_slices,
                M_str,
                Mi_str,
                self.determinant,
                self.orthonormal_error,
                self.spacing_error,
                self.valid,
                errors_str,
                self.ijk_to_lps_hash,
                extra={"component": "viewer"},
            )
        except Exception as exc:
            logger.debug("Error emitting ADVANCED_GEOMETRY_AFFINE_CONTRACT: %s", exc)

    def _emit_effective_display_affine_log(self) -> None:
        """Emit [ADVANCED_EFFECTIVE_DISPLAY_AFFINE] at WARNING level."""
        try:
            def _v3(v):
                if v is None:
                    return "None"
                return f"({v[0]:.6f},{v[1]:.6f},{v[2]:.6f})"

            orig_str = "None"
            eff_str = "None"
            if self.ijk_to_lps_4x4 is not None:
                orig_str = _mat4_str(self.ijk_to_lps_4x4)
            if self.effective_display_ijk_to_lps is not None:
                eff_str = _mat4_str(self.effective_display_ijk_to_lps)

            sr = self.screen_right_lps()
            su = self.screen_up_lps()

            logger.warning(
                "[ADVANCED_EFFECTIVE_DISPLAY_AFFINE] "
                "series_uid=%s "
                "y_flip_detected=%s origin_adjusted=%s "
                "vtk_pixel_array_transform_ijk=%s n_rows=%d "
                "original_ijk_to_lps=%s "
                "effective_display_ijk_to_lps=%s "
                "screen_right_lps=%s screen_up_lps=%s "
                "ijk_to_lps_hash=%s",
                self.series_uid,
                self.y_flip_detected,
                self.origin_adjusted,
                str(self.vtk_pixel_array_transform_ijk),
                self.n_rows,
                orig_str,
                eff_str,
                _v3(sr),
                _v3(su),
                self.ijk_to_lps_hash,
                extra={"component": "viewer"},
            )
        except Exception as exc:
            logger.debug("Error emitting ADVANCED_EFFECTIVE_DISPLAY_AFFINE: %s", exc)
