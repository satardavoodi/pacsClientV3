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
        self._recompute()

    # ─────────────────────────────────────────────────────────────────────────
    # Public operations — each composes onto display_to_raw_ijk
    # ─────────────────────────────────────────────────────────────────────────

    def reset(self) -> "DisplayGeometry":
        """Remove all display transforms; display indices == raw source IJK."""
        self._display_to_raw_ijk = _mat4_identity()
        self._raw_ijk_to_display = _mat4_identity()
        self._operations = []
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

    # ─────────────────────────────────────────────────────────────────────────
    # Read-only properties
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
