"""Advanced VTK orientation markers derived from final viewport orientation.

Option B path:  update_from_affine() uses SeriesGeometryIndex effective_display_ijk_to_lps.
Legacy path:    update_from_geometry() uses camera projection (still available as fallback).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, Optional, Tuple

import numpy as np
import vtk

if TYPE_CHECKING:
    from modules.viewer.advanced.series_geometry_index import SeriesGeometryIndex

logger = logging.getLogger(__name__)


class DicomOrientationMarkers:
    """Render per-viewport orientation labels from the displayed slice orientation."""

    _knee_validation_rows: Dict[str, Dict[str, str]] = {}

    def __init__(self, renderer: vtk.vtkRenderer):
        self.renderer = renderer
        self.markers = {}
        self._orientation_data = {}
        self._affine_source: bool = False   # True if last update came from affine path

    # ─────────────────────────────────────────────────────────────────────────
    # Option B: affine-based marker update
    # ─────────────────────────────────────────────────────────────────────────

    def update_from_affine(
        self,
        geometry: "SeriesGeometryIndex",
        viewport_id: str,
        slice_index: int,
        series_uid: str = "",
        series_number: str = "",
        plane: str = "",
        body_part: str = "",
    ) -> bool:
        """Update orientation labels from explicit SeriesGeometryIndex affine.

        This is the Option B path. VTK camera is NOT consulted.
        The effective_display_ijk_to_lps (accounts for Y-flip) is used to
        compute patient-LPS directions for each screen edge.

        Returns True if markers were updated successfully, False otherwise.
        """
        if geometry is None or not geometry.valid:
            return False

        try:
            screen_right = geometry.screen_right_lps()
            screen_up = geometry.screen_up_lps()
            if screen_right is None or screen_up is None:
                return False

            screen_left = -screen_right
            screen_bottom = -screen_up

            right_label = self._vector_to_lps_label(screen_right)
            left_label = self._vector_to_lps_label(screen_left)
            top_label = self._vector_to_lps_label(screen_up)
            bottom_label = self._vector_to_lps_label(screen_bottom)

            self._orientation_data = {
                "viewport_id": str(viewport_id or "unknown"),
                "series_uid": str(series_uid or geometry.series_uid or ""),
                "series_number": str(series_number or ""),
                "slice_index": int(slice_index),
                "plane": str(plane or ""),
                "body_part": str(body_part or ""),
                "row_cosines": tuple(geometry.row_cosines.tolist()),
                "col_cosines": tuple(geometry.col_cosines.tolist()),
                "screen_right": tuple(screen_right.tolist()),
                "screen_left": tuple(screen_left.tolist()),
                "screen_top": tuple(screen_up.tolist()),
                "screen_bottom": tuple(screen_bottom.tolist()),
                "right_label": right_label,
                "left_label": left_label,
                "top_label": top_label,
                "bottom_label": bottom_label,
            }
            self._affine_source = True

            self._render_markers(
                top=top_label,
                bottom=bottom_label,
                left=left_label,
                right=right_label,
            )
            self._emit_affine_marker_log(geometry)
            self._emit_geometry_contract_marker_log(source="effective_display_affine")
            self._emit_knee_validation_table_if_needed()
            return True
        except Exception as exc:
            logger.warning("Error in update_from_affine: %s", exc)
            return False

    def update_from_geometry_contract(
        self,
        *,
        viewport_id: str,
        screen_vectors: Dict[str, np.ndarray],
        series_uid: str = "",
        series_number: str = "",
        plane: str = "",
        body_part: str = "",
        slice_index: int = -1,
    ) -> bool:
        """Update markers from contract-derived screen-edge vectors.

        This is the preferred runtime path for Phase 2 migration. It uses vectors
        derived from effective display affine and does not consult camera basis.
        """
        try:
            right = np.asarray(screen_vectors.get("screen_right"), dtype=float)
            left = np.asarray(screen_vectors.get("screen_left"), dtype=float)
            top = np.asarray(screen_vectors.get("screen_up"), dtype=float)
            bottom = np.asarray(screen_vectors.get("screen_down"), dtype=float)

            if right.size != 3 or top.size != 3:
                return False

            right_label = self._vector_to_lps_label(right)
            left_label = self._vector_to_lps_label(left)
            top_label = self._vector_to_lps_label(top)
            bottom_label = self._vector_to_lps_label(bottom)

            self._orientation_data = {
                "viewport_id": str(viewport_id or "unknown"),
                "series_uid": str(series_uid or ""),
                "series_number": str(series_number or ""),
                "slice_index": int(slice_index),
                "plane": str(plane or ""),
                "body_part": str(body_part or ""),
                "screen_right": tuple(right.tolist()),
                "screen_left": tuple(left.tolist()),
                "screen_top": tuple(top.tolist()),
                "screen_bottom": tuple(bottom.tolist()),
                "right_label": right_label,
                "left_label": left_label,
                "top_label": top_label,
                "bottom_label": bottom_label,
            }
            self._affine_source = True

            self._render_markers(
                top=top_label,
                bottom=bottom_label,
                left=left_label,
                right=right_label,
            )
            self._emit_geometry_contract_marker_log(source="effective_display_affine")
            self._emit_knee_validation_table_if_needed()
            return True
        except Exception as exc:
            logger.warning("Error in update_from_geometry_contract: %s", exc)
            return False

    def _emit_affine_marker_log(self, geometry: "SeriesGeometryIndex") -> None:
        """Emit [ADVANCED_MARKERS_FROM_AFFINE] log."""
        data = self._orientation_data
        if not data:
            return

        def _fmt(vec) -> str:
            return f"({vec[0]:.4f},{vec[1]:.4f},{vec[2]:.4f})"

        log_msg = (
            "[ADVANCED_MARKERS_FROM_AFFINE] "
            f"viewport_id={data['viewport_id']} "
            f"series_uid={data['series_uid']} "
            f"series_number={data['series_number']} "
            f"slice_index={data['slice_index']} "
            f"ijk_to_lps_hash={geometry.ijk_to_lps_hash} "
            f"y_flip_detected={geometry.y_flip_detected} "
            f"screen_right_lps={_fmt(data['screen_right'])} "
            f"screen_up_lps={_fmt(data['screen_top'])} "
            f"right_label={data['right_label']} "
            f"left_label={data['left_label']} "
            f"top_label={data['top_label']} "
            f"bottom_label={data['bottom_label']} "
            f"confidence=high "
            f"source=SeriesGeometryIndexAffine"
        )
        logger.warning(log_msg, extra={"component": "viewer"})

    def _emit_geometry_contract_marker_log(self, source: str) -> None:
        """Emit Phase 2 contract marker log shape.

        Required runtime tag:
          [MARKERS_FROM_GEOMETRY_CONTRACT]
        """
        data = self._orientation_data
        if not data:
            return

        def _fmt(vec) -> str:
            return f"({vec[0]:.4f},{vec[1]:.4f},{vec[2]:.4f})"

        logger.warning(
            "[MARKERS_FROM_GEOMETRY_CONTRACT] "
            "viewport_id=%s "
            "top_lps_vector=%s bottom_lps_vector=%s "
            "left_lps_vector=%s right_lps_vector=%s "
            "top_label=%s bottom_label=%s left_label=%s right_label=%s "
            "source=%s",
            data.get("viewport_id", "unknown"),
            _fmt(data.get("screen_top", (0.0, 0.0, 0.0))),
            _fmt(data.get("screen_bottom", (0.0, 0.0, 0.0))),
            _fmt(data.get("screen_left", (0.0, 0.0, 0.0))),
            _fmt(data.get("screen_right", (0.0, 0.0, 0.0))),
            data.get("top_label", "?"),
            data.get("bottom_label", "?"),
            data.get("left_label", "?"),
            data.get("right_label", "?"),
            str(source or "effective_display_affine"),
            extra={"component": "viewer"},
        )

    def update_from_geometry(
        self,
        row_cosines: Tuple[float, float, float],
        col_cosines: Tuple[float, float, float],
        plane: str,
        viewport_id: str,
        series_uid: str = "",
        series_number: str = "",
        body_part: str = "",
        slice_index: int = -1,
    ):
        """
        Update labels from DICOM IOP and the current viewport camera orientation.

        The labels are computed from screen-edge vectors in patient LPS, so any
        VTK flip/rotation/transposition seen on screen is reflected in markers.
        """
        try:
            row = self._normalize(np.array(row_cosines, dtype=float))
            col = self._normalize(np.array(col_cosines, dtype=float))
            if row is None or col is None:
                return

            slice_normal = self._normalize(np.cross(row, col))
            if slice_normal is None:
                return

            cam_right, cam_up = self._camera_basis_vectors()
            if cam_right is None or cam_up is None:
                return

            # Project camera basis onto displayed slice plane. These vectors are the
            # patient-space directions of screen edges in the final viewport display.
            screen_right = self._project_to_plane(cam_right, slice_normal)
            screen_top = self._project_to_plane(cam_up, slice_normal)

            # Stable fallback: if projection degenerates, use row/col directly.
            if screen_right is None:
                screen_right = row
            if screen_top is None:
                screen_top = -col

            screen_left = -screen_right
            screen_bottom = -screen_top

            right_label = self._vector_to_lps_label(screen_right)
            left_label = self._vector_to_lps_label(screen_left)
            top_label = self._vector_to_lps_label(screen_top)
            bottom_label = self._vector_to_lps_label(screen_bottom)

            self._orientation_data = {
                "viewport_id": str(viewport_id or "unknown"),
                "series_uid": str(series_uid or ""),
                "series_number": str(series_number or ""),
                "slice_index": int(slice_index),
                "plane": str(plane or ""),
                "body_part": str(body_part or ""),
                "row_cosines": tuple(row.tolist()),
                "col_cosines": tuple(col.tolist()),
                "screen_right": tuple(screen_right.tolist()),
                "screen_left": tuple(screen_left.tolist()),
                "screen_top": tuple(screen_top.tolist()),
                "screen_bottom": tuple(screen_bottom.tolist()),
                "right_label": right_label,
                "left_label": left_label,
                "top_label": top_label,
                "bottom_label": bottom_label,
            }

            self._render_markers(
                top=top_label,
                bottom=bottom_label,
                left=left_label,
                right=right_label,
            )
            self._emit_diagnostic_log()
            self._emit_knee_validation_table_if_needed()
        except Exception as exc:
            logger.warning("Error updating orientation markers: %s", exc)

    def _camera_basis_vectors(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        if self.renderer is None:
            return None, None
        camera = self.renderer.GetActiveCamera()
        if camera is None:
            return None, None

        view_up = self._normalize(np.array(camera.GetViewUp(), dtype=float))
        dop = self._normalize(np.array(camera.GetDirectionOfProjection(), dtype=float))
        if view_up is None or dop is None:
            return None, None

        # Right-handed camera basis: right = dop x up
        view_right = self._normalize(np.cross(dop, view_up))
        return view_right, view_up

    def _project_to_plane(self, vec: np.ndarray, plane_normal: np.ndarray) -> Optional[np.ndarray]:
        projected = vec - np.dot(vec, plane_normal) * plane_normal
        return self._normalize(projected)

    def _normalize(self, vec: np.ndarray) -> Optional[np.ndarray]:
        norm = float(np.linalg.norm(vec))
        if norm <= 1e-8:
            return None
        return vec / norm

    def _vector_to_lps_label(self, direction: np.ndarray) -> str:
        # DICOM LPS mapping required by spec:
        # +X=Left, -X=Right, +Y=Posterior, -Y=Anterior, +Z=Superior, -Z=Inferior
        idx = int(np.argmax(np.abs(direction)))
        if idx == 0:
            return "L" if direction[0] >= 0.0 else "R"
        if idx == 1:
            return "P" if direction[1] >= 0.0 else "A"
        return "S" if direction[2] >= 0.0 else "I"

    def _render_markers(self, top: str, bottom: str, left: str, right: str):
        try:
            for marker in self.markers.values():
                if marker and self.renderer:
                    self.renderer.RemoveVolume(marker)
                    self.renderer.RemoveActor(marker)
            self.markers.clear()

            positions = {
                "top": (top, 0.5, 0.95),
                "bottom": (bottom, 0.5, 0.05),
                "left": (left, 0.05, 0.5),
                "right": (right, 0.95, 0.5),
            }

            for key, (text, x, y) in positions.items():
                actor = self._create_text_actor(text, x, y)
                if actor:
                    self.markers[key] = actor
                    self.renderer.AddViewProp(actor)
        except Exception as exc:
            logger.warning("Error rendering orientation markers: %s", exc)

    def _create_text_actor(self, text: str, norm_x: float, norm_y: float) -> Optional[vtk.vtkTextActor]:
        try:
            actor = vtk.vtkTextActor()
            actor.SetInput(text)

            prop = actor.GetTextProperty()
            prop.SetFontSize(20)
            prop.SetColor(1.0, 1.0, 1.0)
            prop.SetOpacity(0.8)
            prop.BoldOn()

            actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
            actor.GetPositionCoordinate().SetValue(norm_x, norm_y)
            return actor
        except Exception as exc:
            logger.warning("Error creating text actor: %s", exc)
            return None

    def _emit_diagnostic_log(self):
        data = self._orientation_data
        if not data:
            return

        def _fmt(vec) -> str:
            return f"({vec[0]:.4f},{vec[1]:.4f},{vec[2]:.4f})"

        log_msg = (
            "[ADVANCED_ORIENTATION_MARKERS] "
            f"viewport_id={data['viewport_id']} "
            f"series_uid={data['series_uid']} "
            f"series_number={data['series_number']} "
            f"slice_index={data['slice_index']} "
            f"plane={data['plane']} "
            f"row_cosines={_fmt(data['row_cosines'])} "
            f"col_cosines={_fmt(data['col_cosines'])} "
            f"screen_right_lps_vector={_fmt(data['screen_right'])} "
            f"screen_left_lps_vector={_fmt(data['screen_left'])} "
            f"screen_top_lps_vector={_fmt(data['screen_top'])} "
            f"screen_bottom_lps_vector={_fmt(data['screen_bottom'])} "
            f"right_label={data['right_label']} "
            f"left_label={data['left_label']} "
            f"top_label={data['top_label']} "
            f"bottom_label={data['bottom_label']}"
        )
        logger.warning(log_msg, extra={"component": "viewer"})

    def _emit_knee_validation_table_if_needed(self):
        data = self._orientation_data
        body_part = str(data.get("body_part", "")).upper()
        if "KNEE" not in body_part:
            return

        plane = str(data.get("plane", "")).upper()
        top = data.get("top_label", "?")
        bottom = data.get("bottom_label", "?")
        left = data.get("left_label", "?")
        right = data.get("right_label", "?")

        expected, passed = self._knee_expected_for_plane(plane, top, bottom, left, right)
        viewport = str(data.get("viewport_id", "unknown"))

        DicomOrientationMarkers._knee_validation_rows[viewport] = {
            "viewport": viewport,
            "plane": plane or "UNKNOWN",
            "top": top,
            "bottom": bottom,
            "left": left,
            "right": right,
            "expected": expected,
            "result": "PASS" if passed else "FAIL",
        }

        rows = []
        rows.append("[ADVANCED_ORIENTATION_MARKERS] knee_layout_validation_table")
        rows.append("| viewport | plane | top | bottom | left | right | expected | pass/fail |")
        rows.append("|---|---|---|---|---|---|---|---|")
        for key in sorted(DicomOrientationMarkers._knee_validation_rows.keys()):
            row = DicomOrientationMarkers._knee_validation_rows[key]
            rows.append(
                f"| {row['viewport']} | {row['plane']} | {row['top']} | {row['bottom']} | "
                f"{row['left']} | {row['right']} | {row['expected']} | {row['result']} |"
            )
        logger.warning("\n".join(rows), extra={"component": "viewer"})

    def _knee_expected_for_plane(
        self,
        plane: str,
        top: str,
        bottom: str,
        left: str,
        right: str,
    ) -> Tuple[str, bool]:
        top_bottom = {top, bottom}
        left_right = {left, right}

        if "AXIAL" in plane:
            expected = "AXIAL: top/bottom=A-P, left/right=L-R"
            return expected, (top_bottom == {"A", "P"} and left_right == {"L", "R"})

        if "CORONAL" in plane or "SAGITTAL" in plane:
            expected = "CORONAL/SAGITTAL: top/bottom=S-I"
            return expected, top_bottom == {"S", "I"}

        expected = "OBLIQUE/OTHER: manual review"
        return expected, True

    def clear(self):
        try:
            for marker in self.markers.values():
                if marker and self.renderer:
                    self.renderer.RemoveVolume(marker)
                    self.renderer.RemoveActor(marker)
            self.markers.clear()
            self._orientation_data.clear()
        except Exception:
            pass
