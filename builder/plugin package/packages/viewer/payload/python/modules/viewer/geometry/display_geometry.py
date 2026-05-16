"""DisplayGeometry — per-viewport display-index transform.

Every pixel rearrangement applied before display (Y-flip, X-flip,
90° rotations, transpose) must be expressed as a ``display_to_raw_ijk``
matrix so that the effective LPS transform remains authoritative.

Rule:
    NO naked pixel flip / rotate / transpose may exist in the codebase
    without a matching update to a DisplayGeometry instance.

The effective transform that maps displayed pixel (i_d, j_d, k) to
patient LPS is:

    A_display_to_LPS = source.raw_ijk_to_lps_4x4 @ display_to_raw_ijk_4x4

Convenience properties:
    effective_display_ijk_to_lps_4x4
    lps_to_effective_display_ijk_4x4
    screen_right_lps    — unit vector pointing screen-right in patient LPS
    screen_up_lps       — unit vector pointing screen-up in patient LPS

Supported operations (all compose onto display_to_raw_ijk):
    apply_y_flip(n_display_rows)
    apply_x_flip(n_display_cols)
    apply_rotate_cw_90(n_display_rows, n_display_cols)
    apply_rotate_ccw_90(n_display_rows, n_display_cols)
    apply_transpose()
    reset()                — back to identity (no display transform)

Log tags emitted (logger.warning, extra={"component": "viewer"}):
    [DISPLAY_GEOMETRY_CONTRACT]   — on every update
    [EFFECTIVE_DISPLAY_AFFINE]    — on every update
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from modules.viewer.geometry.source_geometry import SourceGeometry

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v.copy()


def _safe_inv(M: np.ndarray) -> Optional[np.ndarray]:
    try:
        det = np.linalg.det(M[:3, :3])
        if abs(det) < 1e-9:
            return None
        return np.linalg.inv(M)
    except np.linalg.LinAlgError:
        return None


def _mat4_identity() -> np.ndarray:
    return np.eye(4, dtype=float)


# ─────────────────────────────────────────────────────────────────────────────
# Primitive display-index transforms (all 4×4, homogeneous)
# ─────────────────────────────────────────────────────────────────────────────

def _y_flip_4x4(n_rows: int) -> np.ndarray:
    """j_display = (n_rows-1) - j_raw  →  raw_j = (n_rows-1) - disp_j."""
    M = _mat4_identity()
    M[1, 1] = -1.0
    M[1, 3] = float(n_rows - 1)
    return M


def _x_flip_4x4(n_cols: int) -> np.ndarray:
    """i_display = (n_cols-1) - i_raw  →  raw_i = (n_cols-1) - disp_i."""
    M = _mat4_identity()
    M[0, 0] = -1.0
    M[0, 3] = float(n_cols - 1)
    return M


def _rotate_cw_90_4x4(n_display_rows: int, n_display_cols: int) -> np.ndarray:
    """Clockwise 90° rotation of displayed raster.

    After rotation, displayed grid has n_display_cols rows × n_display_rows cols.
    Mapping:  i_new = (n_display_rows - 1) - j_old;  j_new = i_old.

    In matrix form (display_new → display_old):
        i_old = j_new
        j_old = (n_display_rows - 1) - i_new
    """
    M = np.zeros((4, 4), float)
    M[3, 3] = 1.0
    # i_old from j_new
    M[0, 1] = 1.0
    # j_old = (n_display_rows-1) - i_new
    M[1, 0] = -1.0
    M[1, 3] = float(n_display_rows - 1)
    # k unchanged
    M[2, 2] = 1.0
    return M


def _rotate_ccw_90_4x4(n_display_rows: int, n_display_cols: int) -> np.ndarray:
    """Counter-clockwise 90° rotation of displayed raster.

    Mapping (display_new → display_old):
        i_old = (n_display_cols - 1) - j_new
        j_old = i_new
    """
    M = np.zeros((4, 4), float)
    M[3, 3] = 1.0
    # i_old = (n_display_cols-1) - j_new
    M[0, 1] = -1.0
    M[0, 3] = float(n_display_cols - 1)
    # j_old = i_new
    M[1, 0] = 1.0
    # k unchanged
    M[2, 2] = 1.0
    return M


def _transpose_4x4() -> np.ndarray:
    """Swap i and j axes.

    Mapping:  i_old = j_new;  j_old = i_new.
    """
    M = np.zeros((4, 4), float)
    M[0, 1] = 1.0
    M[1, 0] = 1.0
    M[2, 2] = 1.0
    M[3, 3] = 1.0
    return M


def _k_flip_4x4(n_slices: int) -> np.ndarray:
    """K-axis flip (stack reordering) for display.

    k_display = (n_slices - 1) - k_raw  →  raw_k = (n_slices - 1) - disp_k.
    This reorders the stack without changing source geometry or physical affine.
    """
    M = _mat4_identity()
    M[2, 2] = -1.0
    M[2, 3] = float(n_slices - 1)
    return M


# ─────────────────────────────────────────────────────────────────────────────
# DisplayGeometry
# ─────────────────────────────────────────────────────────────────────────────

class DisplayGeometry:
    """Per-viewport accumulation of display-index transforms.

    Parameters
    ----------
    source:
        The :class:`~modules.viewer.geometry.source_geometry.SourceGeometry`
        this viewport is displaying.
    viewport_id:
        Unique string identifier for the viewport (e.g. ``"vp_0"``, ``"axial_1"``).
    """

    __slots__ = (
        "source",
        "viewport_id",
        "_display_to_raw_ijk",   # 4×4: display indices → raw source IJK
        "_raw_ijk_to_display",   # 4×4: raw source IJK → display indices
        "_effective_to_lps",     # 4×4: display indices → patient LPS
        "_lps_to_effective",     # 4×4: patient LPS → display indices
        "_operations",           # human-readable log of applied operations
        "_k_flip_applied",       # bool: True once K-flip has been applied (prevents double-application)
    )

    def __init__(
        self,
        source: "SourceGeometry",
        viewport_id: str = "vp_0",
    ) -> None:
        self.source = source
        self.viewport_id = viewport_id
        self._display_to_raw_ijk: np.ndarray = _mat4_identity()
        self._raw_ijk_to_display: Optional[np.ndarray] = _mat4_identity()
        self._operations: List[str] = []
        self._k_flip_applied: bool = False
        self._recompute()

    # ─────────────────────────────────────────────────────────────────────────
    # Public operations — each composes onto display_to_raw_ijk
    # ─────────────────────────────────────────────────────────────────────────

    def reset(self) -> "DisplayGeometry":
        """Remove all display transforms; display indices == raw source IJK."""
        self._display_to_raw_ijk = _mat4_identity()
        self._raw_ijk_to_display = _mat4_identity()
        self._operations = []
        self._k_flip_applied = False
        self._recompute()
        return self

    def apply_y_flip(self, n_display_rows: int) -> "DisplayGeometry":
        """Model a Y-flip of the displayed raster.

        Equivalent to ``arr[:, ::-1, :]`` applied before display.
        n_display_rows is the number of rows in the currently displayed grid.
        """
        T = _y_flip_4x4(n_display_rows)
        self._display_to_raw_ijk = self._display_to_raw_ijk @ T
        self._operations.append(f"y_flip(n_rows={n_display_rows})")
        self._recompute()
        return self

    def apply_x_flip(self, n_display_cols: int) -> "DisplayGeometry":
        """Model an X-flip of the displayed raster."""
        T = _x_flip_4x4(n_display_cols)
        self._display_to_raw_ijk = self._display_to_raw_ijk @ T
        self._operations.append(f"x_flip(n_cols={n_display_cols})")
        self._recompute()
        return self

    def apply_rotate_cw_90(self, n_display_rows: int, n_display_cols: int) -> "DisplayGeometry":
        """Rotate the displayed raster 90° clockwise."""
        T = _rotate_cw_90_4x4(n_display_rows, n_display_cols)
        self._display_to_raw_ijk = self._display_to_raw_ijk @ T
        self._operations.append(f"rotate_cw_90(rows={n_display_rows},cols={n_display_cols})")
        self._recompute()
        return self

    def apply_rotate_ccw_90(self, n_display_rows: int, n_display_cols: int) -> "DisplayGeometry":
        """Rotate the displayed raster 90° counter-clockwise."""
        T = _rotate_ccw_90_4x4(n_display_rows, n_display_cols)
        self._display_to_raw_ijk = self._display_to_raw_ijk @ T
        self._operations.append(f"rotate_ccw_90(rows={n_display_rows},cols={n_display_cols})")
        self._recompute()
        return self

    def apply_transpose(self) -> "DisplayGeometry":
        """Transpose the displayed raster (swap i and j axes)."""
        T = _transpose_4x4()
        self._display_to_raw_ijk = self._display_to_raw_ijk @ T
        self._operations.append("transpose")
        self._recompute()
        return self

    def apply_k_flip_for_stack_order(self, n_slices: int, reason: str = "") -> "DisplayGeometry":
        """Apply K-axis stack reordering for clinical display convention.

        This reverses the slice stack for display WITHOUT changing source geometry,
        DICOM affine, or any LPS mappings used by markers/sync/reference-lines.
        The effective_display_ijk_to_lps automatically remains correct.

        Parameters
        ----------
        n_slices:
            Total number of slices in the stack.
        reason:
            Human-readable reason for the flip (e.g. 'axial_superior_to_inferior').
        """
        # Guard: prevent double-application on reopen/rebind of the same viewport
        if self._k_flip_applied:
            logger.warning(
                "[DISPLAY_POLICY_DOUBLE_APPLICATION_BLOCKED] "
                "viewport_id=%s existing_n_slices=%s new_n_slices=%s reason=%s",
                self.viewport_id,
                int(round(self._display_to_raw_ijk[2, 3])) + 1,
                n_slices,
                reason,
                extra={"component": "viewer"},
            )
            return self

        self._k_flip_applied = True
        T = _k_flip_4x4(n_slices)
        self._display_to_raw_ijk = self._display_to_raw_ijk @ T
        ops_label = f"k_flip(n_slices={n_slices}"
        if reason:
            ops_label += f",reason={reason}"
        ops_label += ")"
        self._operations.append(ops_label)
        self._recompute()
        # Emit runtime bind summary for diagnostic logs
        display_0_raw = self.display_k_to_raw_k(0)
        display_last_raw = self.display_k_to_raw_k(n_slices - 1)
        logger.warning(
            "[DISPLAY_K_RUNTIME_BIND] "
            "viewport_id=%s n_slices=%s k_flip_active=True "
            "display_0_raw_k=%s display_last_raw_k=%s reason=%s",
            self.viewport_id, n_slices,
            display_0_raw, display_last_raw,
            reason,
            extra={"component": "viewer"},
        )
        return self

    # ─────────────────────────────────────────────────────────────────────────
    # Read-only properties
    # ─────────────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────
    # K-flip slice-index conversion helpers
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def is_k_flip_active(self) -> bool:
        """True when a K-flip has been applied (k-diagonal of display_to_raw is -1)."""
        return bool(self._display_to_raw_ijk[2, 2] < 0)

    @property
    def k_flip_n_slices(self) -> Optional[int]:
        """Number of slices used for K-flip, or None when K-flip is not active."""
        if not self.is_k_flip_active:
            return None
        return int(round(self._display_to_raw_ijk[2, 3])) + 1

    def display_k_to_raw_k(self, display_k: int) -> int:
        """Convert a display-space slice index to the raw VTK k index.

        When K-flip is active: raw_k = (N-1) - display_k.
        When inactive: raw_k = display_k (identity).
        """
        k22 = self._display_to_raw_ijk[2, 2]
        k23 = self._display_to_raw_ijk[2, 3]
        return int(round(k22 * float(display_k) + k23))

    def raw_k_to_display_k(self, raw_k: int) -> int:
        """Convert a raw VTK k index to display-space slice index.

        When K-flip is active: display_k = (N-1) - raw_k.
        When inactive: display_k = raw_k (identity).
        """
        if self._raw_ijk_to_display is None:
            return raw_k
        k22 = self._raw_ijk_to_display[2, 2]
        k23 = self._raw_ijk_to_display[2, 3]
        return int(round(k22 * float(raw_k) + k23))

    # ─────────────────────────────────────────────────────────────────────────
    # Read-only matrix properties
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def display_to_raw_ijk_4x4(self) -> np.ndarray:
        """4×4 matrix: display indices → raw source IJK."""
        return self._display_to_raw_ijk.copy()

    @property
    def raw_ijk_to_display_4x4(self) -> np.ndarray:
        """4×4 matrix: raw source IJK → display indices."""
        return self._raw_ijk_to_display.copy() if self._raw_ijk_to_display is not None else _mat4_identity()

    @property
    def effective_display_ijk_to_lps_4x4(self) -> np.ndarray:
        """4×4 matrix: display indices → patient LPS.

        This is the only transform needed by markers, sync, reference lines, etc.
        """
        return self._effective_to_lps.copy()

    @property
    def lps_to_effective_display_ijk_4x4(self) -> np.ndarray:
        """4×4 matrix: patient LPS → display indices."""
        return self._lps_to_effective.copy() if self._lps_to_effective is not None else _mat4_identity()

    def screen_right_lps(self) -> np.ndarray:
        """Unit vector in patient LPS pointing screen-right (+i display direction)."""
        col0 = self._effective_to_lps[:3, 0]
        return _unit(col0)

    def screen_up_lps(self) -> np.ndarray:
        """Unit vector in patient LPS pointing screen-up (+j display direction negated).

        Screen-up corresponds to decreasing j (rows go top → bottom on screen).
        """
        col1 = self._effective_to_lps[:3, 1]
        return _unit(-col1)

    def screen_into_screen_lps(self) -> np.ndarray:
        """Unit vector in patient LPS pointing into the screen (slice normal direction)."""
        col2 = self._effective_to_lps[:3, 2]
        return _unit(col2)

    # ─────────────────────────────────────────────────────────────────────────
    # Transform helpers
    # ─────────────────────────────────────────────────────────────────────────

    def display_index_to_lps(
        self, i_d: float, j_d: float, k_or_slice: float
    ) -> np.ndarray:
        """Convert displayed pixel (i_d, j_d, k_or_slice) → patient LPS (mm)."""
        v = self._effective_to_lps @ np.array([i_d, j_d, k_or_slice, 1.0])
        return v[:3]

    def lps_to_display_index(
        self, x: float, y: float, z: float
    ) -> np.ndarray:
        """Convert patient LPS (mm) → displayed index (i_d, j_d, k)."""
        if self._lps_to_effective is None:
            return np.zeros(3)
        v = self._lps_to_effective @ np.array([x, y, z, 1.0])
        return v[:3]

    def current_slice_plane_in_lps(self, k: float) -> tuple:
        """Return (origin_lps, screen_right_lps, screen_up_lps) for displayed slice k.

        The plane normal is -screen_into_screen_lps (facing viewer).
        """
        origin = self.display_index_to_lps(0.0, 0.0, k)
        return origin, self.screen_right_lps(), self.screen_up_lps()

    def audit_stack_order_convention(
        self, plane: str = "", body_part: str = ""
    ) -> tuple:
        """Audit and recommend stack-order transforms for clinical convention.

        Returns (convention_name, order_matches, recommended_transform, reason, direction_label).
        """
        sg = self.source
        if sg.n_slices < 2:
            return "UNKNOWN_SINGLE_SLICE", True, "NONE", "insufficient_slices", "?"

        # Get first and last slice IPP
        first_ipp = None
        last_ipp = None
        try:
            first_key = next(iter(sg.k_to_sop_uid.keys())) if sg.k_to_sop_uid else 0
            last_key = max(sg.k_to_sop_uid.keys()) if sg.k_to_sop_uid else sg.n_slices - 1
            # Get from per-frame if available
            if sg.per_frame_geometries and first_key in sg.per_frame_geometries:
                first_ipp = sg.per_frame_geometries[first_key].ipp
            if sg.per_frame_geometries and last_key in sg.per_frame_geometries:
                last_ipp = sg.per_frame_geometries[last_key].ipp
            # Fallback to origin + slice progression
            if first_ipp is None:
                first_ipp = sg.origin_ipp
            if last_ipp is None:
                last_ipp = sg.origin_ipp + float(sg.n_slices) * sg.slice_step * sg.slice_normal
        except Exception:
            return "ERROR_READING_GEOMETRY", False, "NONE", "geometry_read_error", "?"

        # Compute direction from first to last
        delta = last_ipp - first_ipp
        delta_norm = float(np.linalg.norm(delta))
        if delta_norm <= 1e-8:
            return "UNKNOWN_COPLANAR", True, "NONE", "first_equals_last", "?"

        delta_unit = delta / delta_norm

        # Determine which anatomical direction delta points along
        idx = int(np.argmax(np.abs(delta_unit)))
        if idx == 0:
            direction = "L" if delta_unit[0] >= 0.0 else "R"
        elif idx == 1:
            direction = "P" if delta_unit[1] >= 0.0 else "A"
        else:
            direction = "S" if delta_unit[2] >= 0.0 else "I"

        plane_upper = plane.upper()
        body_part_upper = body_part.upper()
        axial_like = (
            "AXIAL" in plane_upper or "AX" in plane_upper or
            "TRA" in plane_upper or "TRANS" in plane_upper
        )

        # Determine convention and whether order matches
        convention_name = "UNKNOWN"
        expected_direction = "?"
        order_matches = False
        reason = "no_matching_convention"

        if "SAGITTAL" in plane_upper or "SAG" in plane_upper:
            convention_name = "SAGITTAL_RIGHT_TO_LEFT"
            expected_direction = "R"  # Right → Left means ending at Left (R label on first)
            order_matches = (direction == "R")
            reason = "sagittal_policy" if order_matches else "sagittal_reversed"
        elif "CORONAL" in plane_upper or "COR" in plane_upper:
            convention_name = "CORONAL_ANTERIOR_TO_POSTERIOR"
            expected_direction = "A"  # Anterior → Posterior means starting at A
            order_matches = (direction == "A")
            reason = "coronal_policy" if order_matches else "coronal_reversed"
        elif axial_like:
            convention_name = "AXIAL_SUPERIOR_TO_INFERIOR"
            if "KNEE" in body_part_upper or "LEG" in body_part_upper or "EXTREMITY" in body_part_upper:
                convention_name = "AXIAL_LIKE_PROXIMAL_TO_DISTAL"
                expected_direction = "S"  # Proximal-to-distal typically maps to S-to-I
            else:
                expected_direction = "S"  # Superior → Inferior
            order_matches = (direction == "S")
            reason = ("axial_policy" if order_matches else "axial_reversed")

        recommended_transform = "NONE" if order_matches else "K_FLIP"

        return convention_name, order_matches, recommended_transform, reason, direction

    # ─────────────────────────────────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────────────────────────────────

    def _recompute(self) -> None:
        """Recompute effective affine and its inverse from current display_to_raw_ijk."""
        src_M = self.source.raw_ijk_to_lps_4x4
        # effective = source_raw_to_LPS @ display_to_raw
        self._effective_to_lps = src_M @ self._display_to_raw_ijk
        inv = _safe_inv(self._effective_to_lps)
        self._lps_to_effective = inv
        self._emit_log()

    def _emit_log(self) -> None:
        E = self._effective_to_lps
        sr = self.screen_right_lps()
        su = self.screen_up_lps()
        ops = ",".join(self._operations) if self._operations else "identity"
        logger.warning(
            "[DISPLAY_GEOMETRY_CONTRACT] "
            "viewport_id=%s series_uid=%s operations=%s "
            "display_to_raw=[%s] "
            "effective_col0=(%.4f,%.4f,%.4f) effective_col1=(%.4f,%.4f,%.4f) "
            "screen_right_lps=(%.4f,%.4f,%.4f) screen_up_lps=(%.4f,%.4f,%.4f) "
            "valid=%s hash=%s",
            self.viewport_id, self.source.series_uid, ops,
            " ".join(f"{v:.3f}" for v in self._display_to_raw_ijk.ravel()),
            E[0, 0], E[1, 0], E[2, 0],
            E[0, 1], E[1, 1], E[2, 1],
            sr[0], sr[1], sr[2],
            su[0], su[1], su[2],
            self.source.valid,
            self.source.ijk_to_lps_hash,
            extra={"component": "viewer"},
        )
        logger.warning(
            "[EFFECTIVE_DISPLAY_AFFINE] "
            "viewport_id=%s series_uid=%s "
            "effective_display_ijk_to_lps=["
            "[%.4f,%.4f,%.4f,%.4f],"
            "[%.4f,%.4f,%.4f,%.4f],"
            "[%.4f,%.4f,%.4f,%.4f],"
            "[%.4f,%.4f,%.4f,%.4f]]",
            self.viewport_id, self.source.series_uid,
            E[0,0],E[0,1],E[0,2],E[0,3],
            E[1,0],E[1,1],E[1,2],E[1,3],
            E[2,0],E[2,1],E[2,2],E[2,3],
            E[3,0],E[3,1],E[3,2],E[3,3],
            extra={"component": "viewer"},
        )
