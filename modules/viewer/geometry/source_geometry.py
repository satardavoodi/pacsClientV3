"""SourceGeometry — authoritative DICOM-derived IJK→LPS affine for a series.

This is the ground-truth geometry object that every feature in the viewer
(markers, sync, reference lines, MPR/NPR, 3D outputs) must use.  VTK may
optionally mirror this geometry, but SourceGeometry is the sole authority.

DICOM conventions enforced here (DICOM PS3.3 C.7.6.2.1.1):
  PixelSpacing[0]  = row spacing    (mm between adjacent rows    → j-axis scale)
  PixelSpacing[1]  = column spacing (mm between adjacent columns → i-axis scale)

  i  = column index (grows along row_cosines)
  j  = row    index (grows along col_cosines)
  k  = slice  index (grows along slice_normal = row_cosines × col_cosines)

  P_lps(i,j,k) = IPP_first
               + i * column_spacing * row_cosines
               + j * row_spacing    * col_cosines
               + k * slice_step     * slice_normal

  raw_ijk_to_lps columns:
      col 0 = row_cosines  * column_spacing
      col 1 = col_cosines  * row_spacing
      col 2 = slice_normal * slice_step
      col 3 = IPP_first

Slice step is derived from ordered IPP projections (more robust than tags).
Multi-frame per-frame geometry is supported when IOP/IPP vary across slices.

Log tags emitted (all at logger.warning, extra={"component": "viewer"}):
  [GEOMETRY_SOURCE_CONTRACT]   — once per series after build
"""

from __future__ import annotations

import hashlib
import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
_IOP_TOL_DEG: float = 2.0        # max IOP normal deviation across slices before per-frame
_IPP_JITTER_TOL_MM: float = 1.0  # max IPP regularity jitter (mm)
_DET_MIN: float = 1e-6           # affine is non-invertible below this
_ORTHO_WARN: float = 0.02        # orthonormal_error threshold for warning


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v.copy()


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    dot = float(np.clip(np.dot(_unit(a), _unit(b)), -1.0, 1.0))
    return math.degrees(math.acos(abs(dot)))


def _hash6(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:6]


def _parse_float_list(v: Any, n: int) -> Optional[List[float]]:
    if v is None:
        return None
    try:
        lst = [float(x) for x in v]
        return lst if len(lst) >= n else None
    except (TypeError, ValueError):
        return None


def _safe_inv(m: np.ndarray) -> Optional[np.ndarray]:
    try:
        det = np.linalg.det(m[:3, :3])
        if abs(det) < _DET_MIN:
            return None
        return np.linalg.inv(m)
    except np.linalg.LinAlgError:
        return None


def _mat4_identity() -> np.ndarray:
    return np.eye(4, dtype=float)


def _build_raw_ijk_to_lps(
    row_cos: np.ndarray,
    col_cos: np.ndarray,
    slice_normal: np.ndarray,
    row_spacing: float,
    col_spacing: float,
    slice_step: float,
    origin: np.ndarray,
) -> np.ndarray:
    M = np.eye(4, dtype=float)
    M[0:3, 0] = row_cos * col_spacing     # i-axis in LPS
    M[0:3, 1] = col_cos * row_spacing     # j-axis in LPS
    M[0:3, 2] = slice_normal * slice_step # k-axis in LPS
    M[0:3, 3] = origin
    return M


# ─────────────────────────────────────────────────────────────────────────────
# Per-frame geometry (when IOP/IPP varies per frame)
# ─────────────────────────────────────────────────────────────────────────────

class FrameGeometry:
    """Affine contract for a single frame in a per-frame geometry series."""

    __slots__ = (
        "k_index",
        "sop_uid",
        "ipp",
        "row_cosines",
        "col_cosines",
        "slice_normal",
        "row_spacing",
        "col_spacing",
        "frame_to_lps",     # 3×3 rotation+scale only (no translation for inter-slice)
        "ijk_to_lps_4x4",   # 4×4 including IPP origin
        "lps_to_ijk_4x4",
    )

    def __init__(
        self,
        k_index: int,
        sop_uid: str,
        ipp: np.ndarray,
        row_cosines: np.ndarray,
        col_cosines: np.ndarray,
        row_spacing: float,
        col_spacing: float,
        slice_step: float,
    ) -> None:
        self.k_index = k_index
        self.sop_uid = sop_uid
        self.ipp = ipp.copy()
        self.row_cosines = _unit(row_cosines)
        self.col_cosines = _unit(col_cosines)
        self.slice_normal = _unit(np.cross(self.row_cosines, self.col_cosines))
        self.row_spacing = row_spacing
        self.col_spacing = col_spacing
        M = _build_raw_ijk_to_lps(
            self.row_cosines, self.col_cosines, self.slice_normal,
            row_spacing, col_spacing, slice_step, ipp,
        )
        self.ijk_to_lps_4x4 = M
        inv = _safe_inv(M)
        self.lps_to_ijk_4x4 = inv if inv is not None else np.linalg.pinv(M)


# ─────────────────────────────────────────────────────────────────────────────
# SourceGeometry
# ─────────────────────────────────────────────────────────────────────────────

class SourceGeometry:
    """Authoritative DICOM-derived geometry for a series or frame stack.

    All geometry-sensitive features must consume this object rather than
    querying VTK world-space or camera conventions.

    Use :meth:`build_from_instances` to construct; do not call ``__init__``
    directly unless you are building a stub for tests.
    """

    __slots__ = (
        # Identity
        "series_uid",
        "frame_of_reference_uid",
        "n_instances",
        # Raw affine (source of truth)
        "raw_ijk_to_lps_4x4",
        "lps_to_raw_ijk_4x4",
        # Decomposed geometry
        "row_cosines",
        "col_cosines",
        "slice_normal",
        "row_spacing",
        "col_spacing",
        "slice_step",
        "origin_ipp",
        # Volume dimensions (VTK-reported preferred, fallback metadata)
        "n_rows",
        "n_cols",
        "n_slices",
        # Lookup maps
        "sop_uid_to_k",
        "k_to_sop_uid",
        # Per-frame geometry (None when single global affine is valid)
        "per_frame_geometries",   # Dict[int, FrameGeometry] keyed by k_index, or None
        "is_per_frame",
        # Validation
        "valid",
        "validation_errors",
        "determinant",
        "orthonormal_error",
        "spacing_error",
        # Diagnostics
        "ijk_to_lps_hash",
    )

    def __init__(self) -> None:
        self.series_uid: str = ""
        self.frame_of_reference_uid: str = ""
        self.n_instances: int = 0
        self.raw_ijk_to_lps_4x4: np.ndarray = _mat4_identity()
        self.lps_to_raw_ijk_4x4: np.ndarray = _mat4_identity()
        self.row_cosines: np.ndarray = np.array([1.0, 0.0, 0.0])
        self.col_cosines: np.ndarray = np.array([0.0, 1.0, 0.0])
        self.slice_normal: np.ndarray = np.array([0.0, 0.0, 1.0])
        self.row_spacing: float = 1.0
        self.col_spacing: float = 1.0
        self.slice_step: float = 1.0
        self.origin_ipp: np.ndarray = np.zeros(3)
        self.n_rows: int = 0
        self.n_cols: int = 0
        self.n_slices: int = 0
        self.sop_uid_to_k: Dict[str, int] = {}
        self.k_to_sop_uid: Dict[int, str] = {}
        self.per_frame_geometries: Optional[Dict[int, FrameGeometry]] = None
        self.is_per_frame: bool = False
        self.valid: bool = False
        self.validation_errors: List[str] = []
        self.determinant: float = 0.0
        self.orthonormal_error: float = 0.0
        self.spacing_error: float = 0.0
        self.ijk_to_lps_hash: str = ""

    # ─────────────────────────────────────────────────────────────────────────
    # Factory
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def build_from_instances(
        cls,
        instances: List[Dict[str, Any]],
        *,
        series_uid: str = "",
        frame_of_reference_uid: str = "",
        vtk_n_rows: int = 0,
        vtk_n_cols: int = 0,
        vtk_n_slices: int = 0,
    ) -> "SourceGeometry":
        """Build a :class:`SourceGeometry` from a list of DICOM instance metadata dicts.

        Each dict should contain the keys:
          - ``ImageOrientationPatient``  — 6-element list/array
          - ``ImagePositionPatient``     — 3-element list/array
          - ``PixelSpacing``             — [row_spacing, col_spacing]
          - ``Rows``                     — int (optional, used for n_rows)
          - ``Columns``                  — int (optional, used for n_cols)
          - ``SOPInstanceUID``           — str
          - ``FrameOfReferenceUID``      — str (optional)
        """
        sg = cls()
        sg.series_uid = series_uid
        errors: List[str] = []

        # ── 0. Guard: empty list
        if not instances:
            errors.append("empty_instances_list")
            sg.validation_errors = errors
            sg._emit_contract_log()
            return sg

        sg.n_instances = len(instances)

        # ── 1. Frame of Reference
        if frame_of_reference_uid:
            sg.frame_of_reference_uid = frame_of_reference_uid
        else:
            sg.frame_of_reference_uid = str(
                instances[0].get("FrameOfReferenceUID", "") or ""
            )

        # ── 2. Parse IOP from first instance
        iop_raw = _parse_float_list(instances[0].get("ImageOrientationPatient"), 6)
        if iop_raw is None:
            errors.append("missing_ImageOrientationPatient")
            sg.validation_errors = errors
            sg._emit_contract_log()
            return sg

        row_cos_raw = np.array(iop_raw[0:3], float)
        col_cos_raw = np.array(iop_raw[3:6], float)
        if np.linalg.norm(row_cos_raw) < 1e-6 or np.linalg.norm(col_cos_raw) < 1e-6:
            errors.append("degenerate_ImageOrientationPatient_zero_vector")
            sg.validation_errors = errors
            sg._emit_contract_log()
            return sg

        row_cos = _unit(row_cos_raw)
        col_cos = _unit(col_cos_raw)
        slice_normal = _unit(np.cross(row_cos, col_cos))
        if np.linalg.norm(slice_normal) < 1e-6:
            errors.append("degenerate_IOP_parallel_vectors")
            sg.validation_errors = errors
            sg._emit_contract_log()
            return sg

        # ── 3. Parse IPP from first instance
        ipp0_raw = _parse_float_list(instances[0].get("ImagePositionPatient"), 3)
        if ipp0_raw is None:
            errors.append("missing_ImagePositionPatient")
            sg.validation_errors = errors
            sg._emit_contract_log()
            return sg
        ipp0 = np.array(ipp0_raw, float)

        # ── 4. PixelSpacing
        ps_raw = _parse_float_list(instances[0].get("PixelSpacing"), 2)
        if ps_raw is None or len(ps_raw) < 2:
            errors.append("missing_PixelSpacing")
            # Use 1.0 fallback so we can still build geometry
            ps_raw = [1.0, 1.0]
        row_spacing = float(ps_raw[0]) if float(ps_raw[0]) > 1e-9 else 1.0
        col_spacing = float(ps_raw[1]) if float(ps_raw[1]) > 1e-9 else 1.0

        # ── 5. Sort instances by IPP projection onto slice_normal
        def _ipp_proj(inst: Dict[str, Any]) -> float:
            ipp = _parse_float_list(inst.get("ImagePositionPatient"), 3)
            if ipp is None:
                return 0.0
            return float(np.dot(np.array(ipp, float), slice_normal))

        try:
            sorted_instances = sorted(instances, key=_ipp_proj)
        except Exception:
            sorted_instances = instances

        # ── 6. Build lookup maps
        sop_uid_to_k: Dict[str, int] = {}
        k_to_sop_uid: Dict[int, str] = {}
        for k, inst in enumerate(sorted_instances):
            uid = str(inst.get("SOPInstanceUID", "") or "")
            sop_uid_to_k[uid] = k
            k_to_sop_uid[k] = uid
        sg.sop_uid_to_k = sop_uid_to_k
        sg.k_to_sop_uid = k_to_sop_uid

        # ── 7. Check IOP consistency across slices; detect per-frame geometry
        iop_deviations: List[float] = []
        for inst in sorted_instances[1:]:
            iop_i = _parse_float_list(inst.get("ImageOrientationPatient"), 6)
            if iop_i is None:
                continue
            n_i = _unit(np.cross(_unit(np.array(iop_i[0:3], float)),
                                  _unit(np.array(iop_i[3:6], float))))
            if np.linalg.norm(n_i) < 1e-6:
                continue
            dev = _angle_deg(slice_normal, n_i)
            iop_deviations.append(dev)
            if dev > _IOP_TOL_DEG:
                errors.append(
                    f"inconsistent_IOP_normal dev_deg={dev:.2f} "
                    f"instance={inst.get('SOPInstanceUID','?')}"
                )

        is_per_frame = any(d > _IOP_TOL_DEG for d in iop_deviations)

        # ── 8. Compute slice step from IPP projections
        slice_step = 1.0
        spacing_error = 0.0
        if len(sorted_instances) >= 2:
            projs = []
            for inst in sorted_instances:
                ipp_i = _parse_float_list(inst.get("ImagePositionPatient"), 3)
                if ipp_i is not None:
                    projs.append(float(np.dot(np.array(ipp_i, float), slice_normal)))
            if len(projs) >= 2:
                gaps = [projs[i + 1] - projs[i] for i in range(len(projs) - 1)]
                valid_gaps = [g for g in gaps if abs(g) > 1e-6]
                if valid_gaps:
                    slice_step = float(np.mean([abs(g) for g in valid_gaps]))
                    # Ensure consistent sign with normal direction
                    if gaps[0] < 0:
                        slice_step = -slice_step
                    jitter = float(np.std([abs(g) for g in valid_gaps]))
                    spacing_error = jitter
                    if jitter > _IPP_JITTER_TOL_MM:
                        errors.append(f"IPP_spacing_jitter_mm={jitter:.3f}")
        else:
            errors.append("insufficient_IPP_for_slice_step_single_slice")

        # ── 9. Dimensions
        n_rows_meta = int(sorted_instances[0].get("Rows", 0) or 0)
        n_cols_meta = int(sorted_instances[0].get("Columns", 0) or 0)
        sg.n_rows = vtk_n_rows if vtk_n_rows > 0 else n_rows_meta
        sg.n_cols = vtk_n_cols if vtk_n_cols > 0 else n_cols_meta
        sg.n_slices = vtk_n_slices if vtk_n_slices > 0 else len(sorted_instances)

        # ── 10. Build raw affine
        M = _build_raw_ijk_to_lps(
            row_cos, col_cos, slice_normal,
            row_spacing, col_spacing, abs(slice_step), ipp0,
        )

        # ── 11. Validate
        det = float(np.linalg.det(M[:3, :3]))
        R = M[:3, :3].copy()
        col_norms = np.linalg.norm(R, axis=0)
        R_normed = R / np.where(col_norms > 1e-9, col_norms, 1.0)
        ortho_err = float(np.max(np.abs(R_normed.T @ R_normed - np.eye(3))))

        if abs(det) < _DET_MIN:
            errors.append(f"non_invertible_affine det={det:.3e}")

        sg.raw_ijk_to_lps_4x4 = M
        inv_M = _safe_inv(M)
        sg.lps_to_raw_ijk_4x4 = inv_M if inv_M is not None else np.linalg.pinv(M)

        sg.row_cosines = row_cos
        sg.col_cosines = col_cos
        sg.slice_normal = slice_normal
        sg.row_spacing = row_spacing
        sg.col_spacing = col_spacing
        sg.slice_step = abs(slice_step)
        sg.origin_ipp = ipp0
        sg.determinant = det
        sg.orthonormal_error = ortho_err
        sg.spacing_error = spacing_error
        sg.is_per_frame = is_per_frame

        if ortho_err > _ORTHO_WARN:
            errors.append(f"orthonormal_error={ortho_err:.4f}")

        # ── 12. Per-frame geometries (when IOP varies significantly)
        if is_per_frame:
            pfg: Dict[int, FrameGeometry] = {}
            for k, inst in enumerate(sorted_instances):
                iop_k = _parse_float_list(inst.get("ImageOrientationPatient"), 6)
                ipp_k = _parse_float_list(inst.get("ImagePositionPatient"), 3)
                ps_k = _parse_float_list(inst.get("PixelSpacing"), 2)
                if iop_k and ipp_k:
                    rc_k = _unit(np.array(iop_k[0:3], float))
                    cc_k = _unit(np.array(iop_k[3:6], float))
                    rs_k = float(ps_k[0]) if ps_k else row_spacing
                    cs_k = float(ps_k[1]) if ps_k else col_spacing
                    uid_k = str(inst.get("SOPInstanceUID", "") or "")
                    pfg[k] = FrameGeometry(
                        k_index=k,
                        sop_uid=uid_k,
                        ipp=np.array(ipp_k, float),
                        row_cosines=rc_k,
                        col_cosines=cc_k,
                        row_spacing=rs_k,
                        col_spacing=cs_k,
                        slice_step=abs(slice_step),
                    )
            sg.per_frame_geometries = pfg if pfg else None

        # ── 13. Hash
        sg.ijk_to_lps_hash = _hash6(M.tobytes())

        # ── 14. Validity
        fatal_tags = {
            "empty_instances_list",
            "missing_ImageOrientationPatient",
            "missing_ImagePositionPatient",
            "degenerate_ImageOrientationPatient_zero_vector",
            "degenerate_IOP_parallel_vectors",
        }
        is_fatal = any(any(ft in e for ft in fatal_tags) for e in errors)
        non_invertible = any("non_invertible_affine" in e for e in errors)
        sg.valid = not is_fatal and not non_invertible
        sg.validation_errors = errors

        sg._emit_contract_log()
        return sg

    # ─────────────────────────────────────────────────────────────────────────
    # Transform helpers
    # ─────────────────────────────────────────────────────────────────────────

    def ijk_to_lps(self, i: float, j: float, k: float) -> np.ndarray:
        """Convert raw source IJK index → patient LPS point (mm).

        Uses per-frame geometry when available for the given slice k.
        """
        k_int = int(round(k))
        if self.is_per_frame and self.per_frame_geometries is not None:
            fg = self.per_frame_geometries.get(k_int)
            if fg is not None:
                v = fg.ijk_to_lps_4x4 @ np.array([i, j, 0.0, 1.0])
                return v[:3]
        v = self.raw_ijk_to_lps_4x4 @ np.array([i, j, k, 1.0])
        return v[:3]

    def lps_to_ijk(self, x: float, y: float, z: float) -> np.ndarray:
        """Convert patient LPS point → raw source IJK index.

        Uses the global inverse affine (per-frame inverse not implemented here;
        use :meth:`lps_to_ijk_for_k` for per-frame series).
        """
        v = self.lps_to_raw_ijk_4x4 @ np.array([x, y, z, 1.0])
        return v[:3]

    def lps_to_ijk_for_k(self, x: float, y: float, z: float, k: int) -> np.ndarray:
        """Convert patient LPS → IJK using the per-frame affine for slice k.

        Falls back to global inverse when per-frame geometry is unavailable.
        """
        if self.is_per_frame and self.per_frame_geometries is not None:
            fg = self.per_frame_geometries.get(k)
            if fg is not None:
                v = fg.lps_to_ijk_4x4 @ np.array([x, y, z, 1.0])
                return v[:3]
        return self.lps_to_ijk(x, y, z)

    def slice_plane_in_lps(self, k: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return the plane of slice k as (origin_lps, row_cosines, col_cosines).

        The normal of the plane is ``slice_normal``.
        """
        if self.is_per_frame and self.per_frame_geometries is not None:
            fg = self.per_frame_geometries.get(k)
            if fg is not None:
                return fg.ipp.copy(), fg.row_cosines.copy(), fg.col_cosines.copy()
        origin = self.raw_ijk_to_lps_4x4 @ np.array([0.0, 0.0, float(k), 1.0])
        return origin[:3], self.row_cosines.copy(), self.col_cosines.copy()

    def find_closest_k_for_lps(self, x: float, y: float, z: float) -> int:
        """Return the k index of the slice closest to patient LPS point (x,y,z)."""
        ijk = self.lps_to_ijk(x, y, z)
        k = int(round(float(ijk[2])))
        return max(0, min(k, self.n_slices - 1))

    # ─────────────────────────────────────────────────────────────────────────
    # Logging
    # ─────────────────────────────────────────────────────────────────────────

    def _emit_contract_log(self) -> None:
        M = self.raw_ijk_to_lps_4x4
        cols = " | ".join(
            f"[{M[0,c]:.3f},{M[1,c]:.3f},{M[2,c]:.3f}]" for c in range(4)
        )
        logger.warning(
            "[GEOMETRY_SOURCE_CONTRACT] "
            "series_uid=%s frame_of_reference=%s n_instances=%d "
            "row_cos=(%.4f,%.4f,%.4f) col_cos=(%.4f,%.4f,%.4f) "
            "slice_normal=(%.4f,%.4f,%.4f) "
            "row_spacing=%.4f col_spacing=%.4f slice_step=%.4f "
            "origin=(%.3f,%.3f,%.3f) "
            "n_rows=%d n_cols=%d n_slices=%d "
            "ijk_to_lps=%s "
            "det=%.6f ortho_err=%.6f spacing_err=%.4f "
            "valid=%s is_per_frame=%s validation_errors=%s "
            "hash=%s",
            self.series_uid, self.frame_of_reference_uid, self.n_instances,
            self.row_cosines[0], self.row_cosines[1], self.row_cosines[2],
            self.col_cosines[0], self.col_cosines[1], self.col_cosines[2],
            self.slice_normal[0], self.slice_normal[1], self.slice_normal[2],
            self.row_spacing, self.col_spacing, self.slice_step,
            self.origin_ipp[0], self.origin_ipp[1], self.origin_ipp[2],
            self.n_rows, self.n_cols, self.n_slices,
            cols,
            self.determinant, self.orthonormal_error, self.spacing_error,
            self.valid, self.is_per_frame,
            self.validation_errors or "none",
            self.ijk_to_lps_hash,
            extra={"component": "viewer"},
        )
