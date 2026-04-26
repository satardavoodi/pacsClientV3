"""
Orientation, camera vectors, and rendering helpers for StandardMPRViewer.

Contains DICOM direction-matrix interpretation, camera-vector computation,
scroll-direction logic, orientation labels, baseline camera state, and
render batching.

CRITICAL: ``_get_camera_vectors_for_view`` uses the direction matrix that
has already been adjusted for the input X-flip (column 0 negated). Do NOT
re-negate inside this mixin.
"""

import logging
import sys

import numpy as np
from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)


class _MprOrientationMixin:
    """Mixin providing orientation, camera, and rendering utilities."""

    # ------------------------------------------------------------------
    # Baseline camera state
    # ------------------------------------------------------------------

    def _capture_baseline_camera_state(self):
        """Snapshot every 2-D view camera AFTER creation + CT corrections.

        This is the single source of truth for oblique computations.
        Must be called once at end of _setup_ui and again after a full
        reset (_reset_rendering) so that the oblique code always has a
        clean reference.
        """
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name not in self.viewers:
                continue
            renderer = self.viewers[view_name]['renderer']
            camera   = renderer.GetActiveCamera()

            pos   = np.array(camera.GetPosition(),  dtype=float)
            focal = np.array(camera.GetFocalPoint(), dtype=float)
            up    = np.array(camera.GetViewUp(),     dtype=float)

            direction = focal - pos
            dist = float(np.linalg.norm(direction))
            if dist < 1e-6:
                dist = 500.0
                direction = np.array([0.0, 0.0, -1.0])
            else:
                direction = direction / dist

            self._baseline_camera_state[view_name] = {
                'position':       pos.tolist(),
                'focal':          focal.tolist(),
                'view_up':        up.tolist(),
                'direction':      direction.tolist(),
                'distance':       dist,
                'parallel_scale': camera.GetParallelScale(),
            }

        logger.info("Baseline camera state captured for %s",
                    list(self._baseline_camera_state.keys()))

    # ------------------------------------------------------------------
    # Window / Level
    # ------------------------------------------------------------------

    def _apply_window_level(self, window, level):
        """Apply window/level to all 2D MPR views (axial/sagittal/coronal)."""
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name in self.viewers:
                actor = self.viewers[view_name]['actor']
                actor.GetProperty().SetColorWindow(window)
                actor.GetProperty().SetColorLevel(level)
                self._request_render(view_name)

    # ------------------------------------------------------------------
    # Render batching
    # ------------------------------------------------------------------

    def _request_render(self, view_name):
        """Request a render for a specific view (batched for performance)"""
        self._render_pending.add(view_name)

        if self._render_timer is None:
            self._render_timer = QTimer()
            self._render_timer.setSingleShot(True)
            self._render_timer.timeout.connect(self._execute_pending_renders)

        if not self._render_timer.isActive():
            self._render_timer.start(5)

    def _execute_pending_renders(self):
        """Execute all pending render requests in batch"""
        for view_name in self._render_pending:
            if view_name in self.viewers:
                self.viewers[view_name]['renderer'].GetRenderWindow().Render()
        self._render_pending.clear()

    def _render_immediately(self, view_name):
        """Force immediate render (use sparingly)"""
        if view_name in self.viewers:
            self.viewers[view_name]['renderer'].GetRenderWindow().Render()

    def _clamp_current_position(self):
        """Clamp crosshair position to volume bounds."""
        bounds = self.image_data.GetBounds()
        self.current_position[0] = min(max(self.current_position[0], bounds[0]), bounds[1])
        self.current_position[1] = min(max(self.current_position[1], bounds[2]), bounds[3])
        self.current_position[2] = min(max(self.current_position[2], bounds[4]), bounds[5])

    # ------------------------------------------------------------------
    # Series type detection
    # ------------------------------------------------------------------

    def _detect_series_type(self):
        """Detect modality (CT/MR) and anatomy from image data"""
        scalar_min = self.scalar_range[0]
        scalar_max = self.scalar_range[1]

        if scalar_min < -500 and scalar_max > 1000:
            modality = "CT"
            mean_hu = (scalar_min + scalar_max) / 2
            if scalar_min > -200 and scalar_max < 200 and abs(mean_hu) < 50:
                anatomy = "Brain"
            elif scalar_min < -800 and scalar_max > 500:
                anatomy = "Chest"
            elif scalar_min > -200 and scalar_max < 500:
                anatomy = "Abdomen"
            elif scalar_min > 0 and scalar_max > 800:
                anatomy = "Bone"
            else:
                anatomy = "General"
        else:
            modality = "MR"
            if scalar_max < 500:
                anatomy = "Brain"
            else:
                anatomy = "General"

        return modality, anatomy

    # ------------------------------------------------------------------
    # Camera vector computation  (CRITICAL — direction matrix handling)
    # ------------------------------------------------------------------

    def _get_camera_vectors_for_view(self, view_name):
        """
        Calculate camera position, focal point, and view-up vectors for a view
        using the DICOM direction matrix for proper orientation.
        """
        row_dir = [
            self.direction_matrix.GetElement(0, 0),
            self.direction_matrix.GetElement(0, 1),
            self.direction_matrix.GetElement(0, 2)
        ]
        col_dir = [
            self.direction_matrix.GetElement(1, 0),
            self.direction_matrix.GetElement(1, 1),
            self.direction_matrix.GetElement(1, 2)
        ]
        slice_dir = [
            self.direction_matrix.GetElement(2, 0),
            self.direction_matrix.GetElement(2, 1),
            self.direction_matrix.GetElement(2, 2)
        ]

        is_identity = self._is_identity_direction()

        if is_identity:
            return self._get_standard_camera_vectors(view_name)

        if view_name == 'axial':
            camera_pos = [
                self.center[0],
                self.center[1],
                self.center[2] - 1
            ]
            view_up = [0, 1, 0]
        elif view_name == 'sagittal':
            camera_pos = [
                self.center[0] + 1,
                self.center[1],
                self.center[2]
            ]
            view_up = [0, 0, 1]
        elif view_name == 'coronal':
            camera_pos = [
                self.center[0],
                self.center[1] + 1,
                self.center[2]
            ]
            view_up = [0, 0, 1]
        else:
            return self._get_standard_camera_vectors(view_name)

        logger.debug(f"{view_name} camera: pos={camera_pos}, up={view_up}")
        return camera_pos, self.center, view_up

    def _is_identity_direction(self):
        """Check if direction matrix is identity (standard RAS orientation)"""
        tolerance = 0.01
        for i in range(3):
            for j in range(3):
                expected = 1.0 if i == j else 0.0
                actual = self.direction_matrix.GetElement(i, j)
                if abs(actual - expected) > tolerance:
                    return False
        return True

    def _log_orientation_info(self):
        """Log orientation information for debugging"""
        import sys as _sys
        if _sys.stdout is None:
            # No console in frozen/windowed mode — skip all print/flush debug output
            return
        try:
            print("=" * 80)
            print("DEBUG: ORIENTATION INFORMATION")
            print("=" * 80)
            sys.stdout.flush()

            print("Full Direction Matrix (4x4):")
            for i in range(4):
                row = [self.direction_matrix.GetElement(i, j) for j in range(4)]
                print(f"  Row {i}: [{row[0]:8.4f}, {row[1]:8.4f}, {row[2]:8.4f}, {row[3]:8.4f}]")
            sys.stdout.flush()

            row_dir = [
                self.direction_matrix.GetElement(0, 0),
                self.direction_matrix.GetElement(0, 1),
                self.direction_matrix.GetElement(0, 2)
            ]
            col_dir = [
                self.direction_matrix.GetElement(1, 0),
                self.direction_matrix.GetElement(1, 1),
                self.direction_matrix.GetElement(1, 2)
            ]
            slice_dir = [
                self.direction_matrix.GetElement(2, 0),
                self.direction_matrix.GetElement(2, 1),
                self.direction_matrix.GetElement(2, 2)
            ]

            print(f"\nExtracted Direction Vectors:")
            print(f"  Row direction (Image X axis): [{row_dir[0]:.4f}, {row_dir[1]:.4f}, {row_dir[2]:.4f}]")
            print(f"  Col direction (Image Y axis): [{col_dir[0]:.4f}, {col_dir[1]:.4f}, {col_dir[2]:.4f}]")
            print(f"  Slice direction (Image Z axis): [{slice_dir[0]:.4f}, {slice_dir[1]:.4f}, {slice_dir[2]:.4f}]")
            sys.stdout.flush()

            print(f"\nImage Properties:")
            print(f"  Dimensions: {self.dims}")
            print(f"  Spacing: {self.spacing}")
            print(f"  Origin: {self.origin}")
            print(f"  Center: {self.center}")
            print(f"  Scalar Range: {self.scalar_range}")
            sys.stdout.flush()

            abs_slice = [abs(slice_dir[0]), abs(slice_dir[1]), abs(slice_dir[2])]
            dominant_axis = abs_slice.index(max(abs_slice))

            print(f"\nOrientation Analysis:")
            print(f"  Slice dominant axis: {['X', 'Y', 'Z'][dominant_axis]}")

            if dominant_axis == 2:
                if slice_dir[2] > 0:
                    print("  Detected: HEAD-FIRST acquisition (slices go toward head)")
                else:
                    print("  Detected: FEET-FIRST acquisition (slices go toward feet)")
            elif dominant_axis == 1:
                print("  Detected: Non-standard slice orientation (Y dominant - possibly coronal acquisition)")
            else:
                print("  Detected: Non-standard slice orientation (X dominant - possibly sagittal acquisition)")

            is_identity = self._is_identity_direction()
            print(f"  Is standard (identity) orientation: {is_identity}")
            sys.stdout.flush()

            print(f"\nComputed Camera Vectors:")
            for vn in ['axial', 'sagittal', 'coronal']:
                try:
                    camera_pos, focal, view_up = self._get_camera_vectors_for_view(vn)
                    print(f"  {vn.upper()}:")
                    print(f"    Camera Position: [{camera_pos[0]:.2f}, {camera_pos[1]:.2f}, {camera_pos[2]:.2f}]")
                    print(f"    Focal Point: [{focal[0]:.2f}, {focal[1]:.2f}, {focal[2]:.2f}]")
                    print(f"    View Up: [{view_up[0]:.2f}, {view_up[1]:.2f}, {view_up[2]:.2f}]")
                except Exception as cam_err:
                    print(f"  {vn.upper()}: ERROR - {cam_err}")
            sys.stdout.flush()

            print(f"\nScroll Directions:")
            for vn in ['axial', 'sagittal', 'coronal']:
                try:
                    scroll_dir = self._get_scroll_direction(vn)
                    print(f"  {vn}: [{scroll_dir[0]:.2f}, {scroll_dir[1]:.2f}, {scroll_dir[2]:.2f}]")
                except Exception as scroll_err:
                    print(f"  {vn}: ERROR - {scroll_err}")

            print("=" * 80)
            sys.stdout.flush()

            logger.info("Orientation info logged to console - check terminal output")

        except Exception as e:
            print(f"ERROR in _log_orientation_info: {e}")
            import traceback
            traceback.print_exc()
            sys.stdout.flush()

    def _get_standard_camera_vectors(self, view_name):
        """Get standard camera vectors for identity direction matrix."""
        if view_name == 'axial':
            camera_pos = [self.center[0], self.center[1], self.center[2] - 1]
            view_up = [0, 1, 0]
        elif view_name == 'sagittal':
            camera_pos = [self.center[0] + 1, self.center[1], self.center[2]]
            view_up = [0, 0, 1]
        elif view_name == 'coronal':
            camera_pos = [self.center[0], self.center[1] + 1, self.center[2]]
            view_up = [0, 0, 1]
        else:
            camera_pos = [self.center[0], self.center[1], self.center[2] - 1]
            view_up = [0, 1, 0]

        return camera_pos, self.center, view_up

    def _get_scroll_direction(self, view_name):
        """Get the scroll direction vector for a view based on image orientation."""
        slice_dir = [
            self.direction_matrix.GetElement(2, 0),
            self.direction_matrix.GetElement(2, 1),
            self.direction_matrix.GetElement(2, 2)
        ]
        row_dir = [
            self.direction_matrix.GetElement(0, 0),
            self.direction_matrix.GetElement(0, 1),
            self.direction_matrix.GetElement(0, 2)
        ]
        col_dir = [
            self.direction_matrix.GetElement(1, 0),
            self.direction_matrix.GetElement(1, 1),
            self.direction_matrix.GetElement(1, 2)
        ]

        if view_name == 'axial':
            return [-slice_dir[0], -slice_dir[1], -slice_dir[2]]
        elif view_name == 'sagittal':
            return [-row_dir[0], -row_dir[1], -row_dir[2]]
        elif view_name == 'coronal':
            return [-col_dir[0], -col_dir[1], -col_dir[2]]

        return [0, 0, -1]

    def _get_orientation_labels(self):
        """Get orientation labels for display based on direction matrix."""
        labels = {}
        labels['axial'] = {
            'left': 'R', 'right': 'L', 'top': 'A', 'bottom': 'P'
        }
        labels['sagittal'] = {
            'left': 'A', 'right': 'P', 'top': 'H', 'bottom': 'F'
        }
        labels['coronal'] = {
            'left': 'R', 'right': 'L', 'top': 'H', 'bottom': 'F'
        }
        return labels

    # ------------------------------------------------------------------
    # 3D preset & W/L helpers
    # ------------------------------------------------------------------

    def _get_best_3d_preset(self):
        """Get the best 3D preset based on detected series type"""
        preset_map = {
            ("CT", "Brain"): "CT-Soft-Tissue",
            ("CT", "Bone"): "CT-Bone",
            ("CT", "Chest"): "CT-Lung",
            ("CT", "Abdomen"): "CT-Soft-Tissue",
            ("MR", "Brain"): "MRI-Brain-T1",
            ("MR", "General"): "MRI-Brain-T1",
        }
        key = (self.detected_modality, self.detected_anatomy)
        preset = preset_map.get(key, "CT-Bone")
        logger.info(f"Selected best 3D preset: {preset} for {key}")
        return preset

    def _get_default_window_level(self):
        """Get default window/level based on data range"""
        if self.scalar_range[0] < -500 and self.scalar_range[1] > 1000:
            return 400, 40
        else:
            window = self.scalar_range[1] - self.scalar_range[0]
            level = (self.scalar_range[0] + self.scalar_range[1]) / 2
            return window, level

    def _get_initial_window_level(self):
        """Get initial window/level from source image (fallback to defaults)."""
        if self._initial_window_level is not None:
            return self._initial_window_level
        return self._get_default_window_level()
