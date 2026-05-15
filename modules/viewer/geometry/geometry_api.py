"""GeometryAPI — canonical stateless functions and viewport registry.

All LPS-space geometry operations for multi-viewport sync, reference lines,
and screen-edge vector queries are centralised here.  Every consumer
(markers, sync, MPR/NPR, reference lines, rotate-left/right) must route
geometry work through these functions rather than querying VTK world-space
or camera conventions.

Thread-safety: all public functions are stateless (pure functions).
ViewportGeometryRegistry is NOT thread-safe; access from the UI thread only.

Log tags emitted (logger.warning, extra={"component": "viewer"}):
    [SYNC_LPS_MAPPING]             — on cross-viewport LPS mapping
    [REFERENCE_LINE_LPS_INTERSECTION] — when a reference line is computed
"""

from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from modules.viewer.geometry.display_geometry import DisplayGeometry
from modules.viewer.geometry.source_geometry import SourceGeometry

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v.copy()


def _norm(v: np.ndarray) -> float:
    return float(np.linalg.norm(v))


def _cross3(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.cross(a, b)


def _frames_of_reference_match(dg_a: DisplayGeometry, dg_b: DisplayGeometry) -> bool:
    """Return True when both viewports share a frame of reference.

    Viewports without a populated FrameOfReferenceUID are assumed compatible
    (they may share a study even when the tag is absent).
    """
    uid_a = dg_a.source.frame_of_reference_uid
    uid_b = dg_b.source.frame_of_reference_uid
    if not uid_a or not uid_b:
        return True   # unknown → assume compatible
    return uid_a == uid_b


# ─────────────────────────────────────────────────────────────────────────────
# Stateless API
# ─────────────────────────────────────────────────────────────────────────────

class GeometryAPI:
    """Namespace for canonical LPS-space geometry operations.

    All methods are static/class-method; the class is a namespace only.
    """

    # ── Index ↔ LPS ──────────────────────────────────────────────────────────

    @staticmethod
    def displayed_index_to_lps(
        dg: DisplayGeometry, i_d: float, j_d: float, k: float
    ) -> np.ndarray:
        """Convert displayed pixel (i_d, j_d, k) → patient LPS (mm).

        Parameters
        ----------
        dg:
            The viewport's :class:`DisplayGeometry`.
        i_d, j_d:
            Displayed column and row indices.
        k:
            Slice index (real-valued; can be fractional for sub-slice queries).
        """
        return dg.display_index_to_lps(i_d, j_d, k)

    @staticmethod
    def lps_to_displayed_index(
        dg: DisplayGeometry, x: float, y: float, z: float
    ) -> Tuple[float, float, float]:
        """Convert patient LPS (mm) → displayed index (i_d, j_d, k).

        Returns a 3-tuple of floats; callers must round to nearest integer
        for pixel access.
        """
        v = dg.lps_to_display_index(x, y, z)
        return float(v[0]), float(v[1]), float(v[2])

    # ── Screen-edge vectors ───────────────────────────────────────────────────

    @staticmethod
    def screen_edge_vectors_in_lps(
        dg: DisplayGeometry,
    ) -> Dict[str, np.ndarray]:
        """Return all six anatomical screen-edge vectors for a viewport.

        Returns a dict with keys:
          ``screen_right``, ``screen_left``, ``screen_up``, ``screen_down``,
          ``screen_into``, ``screen_out_of``.
        All are unit vectors in patient LPS space.
        """
        r = dg.screen_right_lps()
        u = dg.screen_up_lps()
        n = dg.screen_into_screen_lps()
        return {
            "screen_right":     r,
            "screen_left":     -r,
            "screen_up":        u,
            "screen_down":     -u,
            "screen_into":      n,
            "screen_out_of":   -n,
        }

    # ── Cross-viewport LPS sync ───────────────────────────────────────────────

    @staticmethod
    def map_lps_between_viewports(
        dg_src: DisplayGeometry,
        dg_dst: DisplayGeometry,
        i_src: float,
        j_src: float,
        k_src: float,
        *,
        log: bool = False,
    ) -> Optional[Tuple[float, float, float]]:
        """Map displayed pixel in viewport A to the corresponding index in viewport B.

        Uses patient LPS as the common space.  Returns ``None`` when the
        viewports do not share a frame of reference.

        Parameters
        ----------
        dg_src, dg_dst:
            Source and destination :class:`DisplayGeometry` objects.
        i_src, j_src, k_src:
            Displayed pixel coordinates in the source viewport.
        log:
            When True, emit ``[SYNC_LPS_MAPPING]`` log line.
        """
        if not _frames_of_reference_match(dg_src, dg_dst):
            if log:
                logger.warning(
                    "[SYNC_LPS_MAPPING] "
                    "source_viewport=%s target_viewport=%s "
                    "source_display_index=(%.2f,%.2f,%.2f) "
                    "mapped_lps=(nan,nan,nan) "
                    "target_display_index=(nan,nan,nan) "
                    "same_frame_of_reference=False "
                    "registration_used=False "
                    "roundtrip_error_px=nan "
                    "sync_blocked_reason=different_frame_of_reference_no_registration "
                    "src_for=%s dst_for=%s",
                    dg_src.viewport_id, dg_dst.viewport_id,
                    i_src, j_src, k_src,
                    dg_src.source.frame_of_reference_uid,
                    dg_dst.source.frame_of_reference_uid,
                    extra={"component": "viewer"},
                )
            return None

        lps = GeometryAPI.displayed_index_to_lps(dg_src, i_src, j_src, k_src)
        dst = GeometryAPI.lps_to_displayed_index(dg_dst, *lps.tolist())
        # Roundtrip (source -> LPS -> target -> LPS -> source) error in source px.
        lps_rt = GeometryAPI.displayed_index_to_lps(dg_dst, dst[0], dst[1], dst[2])
        src_rt = GeometryAPI.lps_to_displayed_index(dg_src, *lps_rt.tolist())
        rt_err = math.sqrt(
            (float(src_rt[0]) - float(i_src)) ** 2 +
            (float(src_rt[1]) - float(j_src)) ** 2 +
            (float(src_rt[2]) - float(k_src)) ** 2
        )

        if log:
            logger.warning(
                "[SYNC_LPS_MAPPING] "
                "source_viewport=%s target_viewport=%s "
                "source_display_index=(%.2f,%.2f,%.2f) "
                "mapped_lps=(%.3f,%.3f,%.3f) "
                "target_display_index=(%.2f,%.2f,%.2f) "
                "same_frame_of_reference=True "
                "registration_used=False "
                "roundtrip_error_px=%.6f",
                dg_src.viewport_id, dg_dst.viewport_id,
                i_src, j_src, k_src,
                lps[0], lps[1], lps[2],
                dst[0], dst[1], dst[2],
                rt_err,
                extra={"component": "viewer"},
            )
        return (float(dst[0]), float(dst[1]), float(dst[2]))

    # ── Current slice plane in LPS ────────────────────────────────────────────

    @staticmethod
    def current_slice_plane_in_lps(
        dg: DisplayGeometry, slice_k: float
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return the displayed slice plane in patient LPS.

        Returns ``(origin_lps, screen_right_lps, screen_up_lps, normal_lps)``
        where ``normal_lps`` points toward the viewer (anti-parallel to into-screen).
        """
        origin, sr, su = dg.current_slice_plane_in_lps(slice_k)
        normal = -dg.screen_into_screen_lps()
        return origin, sr, su, normal

    # ── Reference line computation ─────────────────────────────────────────────

    @staticmethod
    def reference_line_in_viewport(
        dg_reference: DisplayGeometry,
        dg_target: DisplayGeometry,
        slice_k_reference: float,
        *,
        log: bool = False,
    ) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """Compute where the reference viewport's current slice plane intersects
        the target viewport's displayed plane, returning a 2-D line segment in
        the *target* viewport's display coordinates.

        Returns ``None`` when:
        - The viewports do not share a frame of reference.
        - The planes are nearly parallel (no meaningful intersection line).
        - The intersection line falls entirely outside the target's image bounds.

        Parameters
        ----------
        dg_reference:
            The viewport whose current slice defines the reference plane.
        dg_target:
            The viewport in which to draw the reference line.
        slice_k_reference:
            Current slice index in the reference viewport.

        Returns
        -------
        Optional tuple of two 2-D display-coordinate points ``(p1, p2)``
        (each as ``(col_float, row_float)``).
        """
        if not _frames_of_reference_match(dg_reference, dg_target):
            if log:
                logger.warning(
                    "[REFERENCE_LINE_LPS_INTERSECTION] "
                    "source_viewport=%s target_viewport=%s "
                    "plane_a_origin_lps=(nan,nan,nan) plane_a_normal_lps=(nan,nan,nan) "
                    "plane_b_origin_lps=(nan,nan,nan) plane_b_normal_lps=(nan,nan,nan) "
                    "intersection_status=blocked_frame_of_reference_mismatch "
                    "line_lps_p0=(nan,nan,nan) line_lps_p1=(nan,nan,nan) "
                    "target_display_p0=(nan,nan) target_display_p1=(nan,nan)",
                    dg_reference.viewport_id, dg_target.viewport_id,
                    extra={"component": "viewer"},
                )
            return None

        # ── Reference plane in LPS ────────────────────────────────────────────
        origin_ref, sr_ref, su_ref, normal_ref = GeometryAPI.current_slice_plane_in_lps(
            dg_reference, slice_k_reference
        )

        # ── Target plane in LPS ───────────────────────────────────────────────
        origin_tgt, sr_tgt, su_tgt, normal_tgt = GeometryAPI.current_slice_plane_in_lps(
            dg_target, 0.0  # target plane: we embed the reference line, k doesn't matter
        )

        # ── Plane-plane intersection ───────────────────────────────────────────
        # direction = cross of the two normals
        line_dir = _cross3(normal_ref, normal_tgt)
        line_dir_norm = _norm(line_dir)
        if line_dir_norm < 1e-6:
            # planes are (nearly) parallel → no intersection line
            if log:
                logger.warning(
                    "[REFERENCE_LINE_LPS_INTERSECTION] "
                    "source_viewport=%s target_viewport=%s "
                    "plane_a_origin_lps=(%.3f,%.3f,%.3f) "
                    "plane_a_normal_lps=(%.4f,%.4f,%.4f) "
                    "plane_b_origin_lps=(%.3f,%.3f,%.3f) "
                    "plane_b_normal_lps=(%.4f,%.4f,%.4f) "
                    "intersection_status=parallel_planes "
                    "line_lps_p0=(nan,nan,nan) line_lps_p1=(nan,nan,nan) "
                    "target_display_p0=(nan,nan) target_display_p1=(nan,nan)",
                    dg_reference.viewport_id, dg_target.viewport_id,
                    origin_ref[0], origin_ref[1], origin_ref[2],
                    normal_ref[0], normal_ref[1], normal_ref[2],
                    origin_tgt[0], origin_tgt[1], origin_tgt[2],
                    normal_tgt[0], normal_tgt[1], normal_tgt[2],
                    extra={"component": "viewer"},
                )
            return None

        line_dir = line_dir / line_dir_norm

        # Find a point on the intersection line by solving the two plane equations
        # using the "three-plane" method with a plane through the origin perpendicular
        # to both normals.
        n3 = _unit(line_dir)
        A = np.column_stack([normal_ref, normal_tgt, n3])
        d = np.array([
            float(np.dot(normal_ref, origin_ref)),
            float(np.dot(normal_tgt, origin_tgt)),
            0.0,
        ])
        try:
            det = np.linalg.det(A)
            if abs(det) < 1e-9:
                return None
            line_point = np.linalg.solve(A, d)
        except np.linalg.LinAlgError:
            return None

        # ── Project line into target display coordinates ──────────────────────
        # We need two 2-D points in target display space.
        # Parameterise: P(t) = line_point + t * line_dir
        # Project both ends (±large t) into target display, then clip to image bounds.
        n_rows = max(dg_target.source.n_rows, 1)
        n_cols = max(dg_target.source.n_cols, 1)
        diag = math.sqrt(n_rows ** 2 + n_cols ** 2) * max(
            dg_target.source.row_spacing, dg_target.source.col_spacing, 1.0
        )
        t_max = diag * 2.0

        p3d_1 = line_point + line_dir * t_max
        p3d_2 = line_point - line_dir * t_max

        i1, j1, _ = GeometryAPI.lps_to_displayed_index(dg_target, *p3d_1.tolist())
        i2, j2, _ = GeometryAPI.lps_to_displayed_index(dg_target, *p3d_2.tolist())

        # Cohen-Sutherland-style bounds check: at least one endpoint in image
        margin = max(n_rows, n_cols) * 2
        if (i1 < -margin and i2 < -margin) or (i1 > n_cols + margin and i2 > n_cols + margin):
            return None
        if (j1 < -margin and j2 < -margin) or (j1 > n_rows + margin and j2 > n_rows + margin):
            return None

        if log:
            logger.warning(
                "[REFERENCE_LINE_LPS_INTERSECTION] "
                "source_viewport=%s target_viewport=%s "
                "plane_a_origin_lps=(%.3f,%.3f,%.3f) "
                "plane_a_normal_lps=(%.4f,%.4f,%.4f) "
                "plane_b_origin_lps=(%.3f,%.3f,%.3f) "
                "plane_b_normal_lps=(%.4f,%.4f,%.4f) "
                "intersection_status=ok "
                "line_lps_p0=(%.3f,%.3f,%.3f) line_lps_p1=(%.3f,%.3f,%.3f) "
                "target_display_p0=(%.2f,%.2f) target_display_p1=(%.2f,%.2f)",
                dg_reference.viewport_id, dg_target.viewport_id,
                origin_ref[0], origin_ref[1], origin_ref[2],
                normal_ref[0], normal_ref[1], normal_ref[2],
                origin_tgt[0], origin_tgt[1], origin_tgt[2],
                normal_tgt[0], normal_tgt[1], normal_tgt[2],
                p3d_1[0], p3d_1[1], p3d_1[2],
                p3d_2[0], p3d_2[1], p3d_2[2],
                i1, j1, i2, j2,
                extra={"component": "viewer"},
            )

        return ((float(i1), float(j1)), (float(i2), float(j2)))

    # ── Slice distance in LPS ─────────────────────────────────────────────────

    @staticmethod
    def lps_to_slice_k_approx(
        dg: DisplayGeometry, x: float, y: float, z: float
    ) -> float:
        """Return the approximate slice k for the LPS point in this viewport.

        This is the third component of :meth:`lps_to_displayed_index`.
        """
        _, _, k = GeometryAPI.lps_to_displayed_index(dg, x, y, z)
        return k


# ─────────────────────────────────────────────────────────────────────────────
# ViewportGeometryRegistry
# ─────────────────────────────────────────────────────────────────────────────

class ViewportGeometryRegistry:
    """Thread-unsafe registry mapping viewport IDs to :class:`DisplayGeometry` objects.

    Provides convenience wrappers over :class:`GeometryAPI` for multi-viewport
    operations.

    Access from the Qt main / UI thread only.
    """

    def __init__(self) -> None:
        self._registry: Dict[str, DisplayGeometry] = {}

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self, viewport_id: str, dg: DisplayGeometry) -> None:
        """Register or replace the :class:`DisplayGeometry` for a viewport."""
        self._registry[viewport_id] = dg

    def unregister(self, viewport_id: str) -> None:
        """Remove a viewport from the registry."""
        self._registry.pop(viewport_id, None)

    def get(self, viewport_id: str) -> Optional[DisplayGeometry]:
        """Return the :class:`DisplayGeometry` for *viewport_id*, or ``None``."""
        return self._registry.get(viewport_id)

    def all_viewport_ids(self) -> List[str]:
        """Return all registered viewport IDs."""
        return list(self._registry.keys())

    def clear(self) -> None:
        """Remove all registrations."""
        self._registry.clear()

    # ── Convenience wrappers ──────────────────────────────────────────────────

    def get_screen_edge_vectors(self, viewport_id: str) -> Optional[Dict[str, np.ndarray]]:
        """Return screen-edge vectors for a viewport, or ``None`` if not registered."""
        dg = self.get(viewport_id)
        if dg is None:
            return None
        return GeometryAPI.screen_edge_vectors_in_lps(dg)

    def map_lps_to_viewport(
        self,
        src_viewport_id: str,
        dst_viewport_id: str,
        i: float, j: float, k: float,
        *,
        log: bool = False,
    ) -> Optional[Tuple[float, float, float]]:
        """Map a display index from one viewport to another via LPS.

        Returns ``None`` if either viewport is unregistered or they do not share
        a frame of reference.
        """
        dg_src = self.get(src_viewport_id)
        dg_dst = self.get(dst_viewport_id)
        if dg_src is None or dg_dst is None:
            return None
        return GeometryAPI.map_lps_between_viewports(dg_src, dg_dst, i, j, k, log=log)

    def compute_reference_line(
        self,
        reference_viewport_id: str,
        target_viewport_id: str,
        slice_k_reference: float,
        *,
        log: bool = False,
    ) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """Compute the reference line from one viewport in another.

        See :meth:`GeometryAPI.reference_line_in_viewport`.
        """
        dg_ref = self.get(reference_viewport_id)
        dg_tgt = self.get(target_viewport_id)
        if dg_ref is None or dg_tgt is None:
            return None
        return GeometryAPI.reference_line_in_viewport(
            dg_ref, dg_tgt, slice_k_reference, log=log
        )

    def compute_all_reference_lines(
        self,
        reference_viewport_id: str,
        slice_k_reference: float,
        *,
        log: bool = False,
    ) -> Dict[str, Optional[Tuple[Tuple[float, float], Tuple[float, float]]]]:
        """Compute reference lines from one reference viewport in all other viewports.

        Returns a dict keyed by target viewport ID.
        """
        results: Dict[str, Optional[Tuple[Tuple[float, float], Tuple[float, float]]]] = {}
        for vid, dg in self._registry.items():
            if vid == reference_viewport_id:
                continue
            dg_ref = self.get(reference_viewport_id)
            if dg_ref is None:
                results[vid] = None
            else:
                results[vid] = GeometryAPI.reference_line_in_viewport(
                    dg_ref, dg, slice_k_reference, log=log
                )
        return results
