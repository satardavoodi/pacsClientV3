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
from PacsClient.utils.structured_logging import emit_viewer_event

logger = logging.getLogger(__name__)


def _fmt_vec3(values):
    try:
        return f"[{float(values[0]):.6f},{float(values[1]):.6f},{float(values[2]):.6f}]"
    except Exception:
        return "none"


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

            row_dir = [
                self.direction_matrix.GetElement(0, 0),
                self.direction_matrix.GetElement(0, 1),
                self.direction_matrix.GetElement(0, 2),
            ]
            col_dir = [
                self.direction_matrix.GetElement(1, 0),
                self.direction_matrix.GetElement(1, 1),
                self.direction_matrix.GetElement(1, 2),
            ]
            slice_dir = [
                self.direction_matrix.GetElement(2, 0),
                self.direction_matrix.GetElement(2, 1),
                self.direction_matrix.GetElement(2, 2),
            ]
            emit_viewer_event(
                logger,
                "ZETA_NPR_RESLICE_AXES_AUDIT",
                stage="capture_baseline_camera_state",
                view_name=view_name,
                row_dir=_fmt_vec3(row_dir),
                col_dir=_fmt_vec3(col_dir),
                slice_dir=_fmt_vec3(slice_dir),
                camera_position=_fmt_vec3(pos),
                camera_focal_point=_fmt_vec3(focal),
                camera_view_up=_fmt_vec3(up),
                camera_direction=_fmt_vec3(direction),
                camera_distance=dist,
                parallel_scale=float(camera.GetParallelScale()),
            )

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

    # ------------------------------------------------------------------
    # Interactive update throttle (smooth crosshair move/rotate on large stacks)
    # ------------------------------------------------------------------
    # VTK MouseMoveEvent fires far faster than the views can reslice + render. Running the full
    # update (crosshair endpoints + slice positions + oblique reslice + slice-info text) on EVERY
    # event saturates the main thread — laggy/choppy crosshair move & rotation, worst on
    # high-slice-count series — and produces uneven motion (jitter). Rendering was already batched
    # (`_request_render`, 5 ms); this coalesces the COMPUTE to the same frame cadence: run
    # immediately if a frame budget has elapsed, otherwise remember the latest request and fire a
    # single trailing timer so the final position always lands. The geometry/orientation logic is
    # unchanged — only how often it runs per drag. Disable with AIPACS_ZETA_MPR_INTERACT_MS=0.

    def _interaction_budget_ms(self):
        try:
            import os
            return max(0, int(os.environ.get("AIPACS_ZETA_MPR_INTERACT_MS", "16")))
        except Exception:
            return 16

    def _apply_interaction_update(self, kind):
        """Run the actual view updates for one interaction step (same calls/order as the legacy
        inline path). kind='move' → crosshairs + slice positions + oblique + slice-info text;
        kind='rotate' → crosshairs + oblique only."""
        try:
            self._update_all_crosshairs()
            if kind == 'move':
                self._update_slice_positions()
            self._synchronize_oblique_views()
            if kind == 'move':
                self._update_slice_info_texts()
        except Exception as exc:
            logger.debug("[ZETA_MPR] interaction update (%s) failed: %r", kind, exc)

    def _request_interaction_update(self, kind):
        """Frame-cadence throttle for interactive crosshair updates (see note above)."""
        budget = self._interaction_budget_ms()
        if budget <= 0:
            # Throttle disabled -> legacy immediate behaviour.
            self._apply_interaction_update(kind)
            return
        import time as _t
        prev = getattr(self, "_interaction_pending_kind", None)
        # 'move' supersedes 'rotate' (move does strictly more); within one gesture kind is constant.
        merged = 'move' if (kind == 'move' or prev == 'move') else 'rotate'
        self._interaction_pending_kind = merged
        self._interaction_active_kind = merged
        now = _t.monotonic() * 1000.0
        last = getattr(self, "_interaction_last_ms", 0.0)
        if (now - last) >= budget:
            self._interaction_last_ms = now
            self._interaction_pending_kind = None
            self._apply_interaction_update(merged)
            return
        timer = getattr(self, "_interaction_timer", None)
        if timer is None:
            from PySide6.QtCore import QTimer
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(self._flush_interaction_update)
            self._interaction_timer = timer
        if not timer.isActive():
            timer.start(max(1, int(budget - (now - last))))

    def _flush_interaction_update(self):
        """Trailing flush fired by the throttle timer — applies the most recent pending state."""
        kind = getattr(self, "_interaction_pending_kind", None)
        if kind is None:
            return
        import time as _t
        self._interaction_last_ms = _t.monotonic() * 1000.0
        self._interaction_pending_kind = None
        self._apply_interaction_update(kind)

    def _finalize_interaction_update(self):
        """Land the exact final state on mouse release (cancels any pending trailing flush)."""
        try:
            timer = getattr(self, "_interaction_timer", None)
            if timer is not None:
                timer.stop()
            kind = getattr(self, "_interaction_active_kind", None) or 'move'
            self._interaction_pending_kind = None
            self._apply_interaction_update(kind)
        except Exception as exc:
            logger.debug("[ZETA_MPR] finalize interaction failed: %r", exc)

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

    def _needs_radiological_correction(self):
        """Whether the proven radiological camera corrections (Roll/Azimuth) apply.

        True for CT (the legacy-calibrated path) OR for a canonicalized / axis-aligned
        volume flagged by the canonicalization pre-filter (``self._mpr_canonicalized``).
        For a legacy non-CT volume with the pre-filter OFF this returns False, so the
        legacy path is byte-identical. See ``_mpr_canonicalize.py`` and
        ``ZETA_MPR_GEOMETRY_MATH_INVESTIGATION_2026-06-02.md``.
        """
        try:
            # Anatomical-camera path (ZetaAnatA) orients each view directly from patient axes,
            # so the legacy coupled Roll(180)/Azimuth(180) must NOT run. Returning False here
            # disables them at every call site (_create_*_view, _reset_rendering,
            # _reload_with_series, _reset_all_to_orthogonal) with a single guard.
            if getattr(self, "_mpr_use_anatomical", False):
                return False
            if getattr(self, "detected_modality", None) == "CT":
                return True
            return bool(getattr(self, "_mpr_canonicalized", False))
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Anatomical-camera helpers (ZetaAnatA path — 2026-06-03)
    # ------------------------------------------------------------------
    # Each MPR pane targets a PATIENT plane (radiological canonical), in patient LPS
    # (X=Left, Y=Posterior, Z=Superior). Per pane: (plane_normal, screen_up, screen_right):
    #   axial    : normal=S/I, up=Anterior, right=Left
    #   sagittal : normal=L/R, up=Superior, right=Posterior  (face on viewer-left)
    #   coronal  : normal=A/P, up=Superior, right=Left
    # The camera for a pane is built along the VOLUME's own world grid axes (so the image is
    # grid-aligned / upright, no oblique tilt). The look-axis = the world axis whose patient
    # direction best matches plane_normal — this ROUTES the native plane to its correct pane
    # (a sagittal acquisition lands in the Sagittal pane, etc.) and keeps reconstructions in
    # canonical layout (no spurious 90° turn). For an axial acquisition this reduces to the
    # original look=Z(axial)/X(sag)/Y(cor) assignment, so axial cases are unchanged.
    _ANAT_PLANE_TARGETS = {
        'axial':    ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0), (1.0, 0.0, 0.0)),
        'sagittal': ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0),  (0.0, 1.0, 0.0)),
        'coronal':  ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0),  (1.0, 0.0, 0.0)),
    }

    @staticmethod
    def _lps_label(v):
        """Nearest anatomical letter (R/L/A/P/S/I) for a patient-LPS direction vector."""
        v = np.asarray(v, dtype=float)
        ax = int(np.argmax(np.abs(v)))
        positive = float(v[ax]) >= 0.0
        return (('L', 'R'), ('P', 'A'), ('S', 'I'))[ax][0 if positive else 1]

    def _anatomical_camera(self, view_name):
        """Camera (position, focal, view_up) in WORLD coords for ``view_name``.

        PLANE-AWARE + GRID-ALIGNED. The look-axis is the VOLUME world axis whose patient
        direction best matches this pane's patient plane-normal, so the NATIVE acquisition plane
        is ROUTED to its correct pane (axial acq -> Axial pane; sagittal acq -> Sagittal pane;
        coronal acq -> Coronal pane) and the reconstructions appear in canonical radiological
        layout with no spurious 90° rotation. view_up + view direction are VOLUME world axes, so
        the image is a clean upright rectangle (no oblique tilt). Only the SIGN of each axis is
        chosen — from ``A`` (= self._anat_A; columns are the patient-LPS directions of world
        +X/+Y/+Z) — so screen up/right are canonical. The chosen look-axis index is stored in
        self._anat_look_axis[view_name] (used by the slice-info text). Returns None on any
        problem so the caller falls back to legacy.
        """
        try:
            A = getattr(self, "_anat_A", None)
            if A is None or view_name not in self._ANAT_PLANE_TARGETS:
                return None
            # Per-view cache: A and self.center are fixed for the viewer's lifetime, so each
            # view's camera vectors are constant. Compute once and reuse — this avoids per-frame
            # numpy recompute and the 3 camera rebuilds _anatomical_labels triggers on every
            # label refresh. Keyed on id(A) so a new volume (new A) invalidates it.
            cache = getattr(self, "_anat_camera_cache", None)
            cache_key = id(A)
            if cache is None or getattr(self, "_anat_camera_cache_key", None) != cache_key:
                cache = {}
                self._anat_camera_cache = cache
                self._anat_camera_cache_key = cache_key
            cached = cache.get(view_name)
            if cached is not None:
                if getattr(self, "_anat_look_axis", None) is None:
                    self._anat_look_axis = {}
                if getattr(self, "_anat_up_axis", None) is None:
                    self._anat_up_axis = {}
                self._anat_look_axis[view_name] = cached[1]
                self._anat_up_axis[view_name] = cached[2]
                return cached[0]
            n_t, up_t, right_t = (np.asarray(v, dtype=float)
                                  for v in self._ANAT_PLANE_TARGETS[view_name])
            pat = [A[:, k] for k in range(3)]   # patient-LPS direction of each volume world axis
            eye = np.eye(3)
            # look-axis: the volume world axis most parallel to this pane's patient plane-normal
            # (routes the matching native/reconstructed plane to this pane).
            look_k = max(range(3), key=lambda k: abs(float(pat[k] @ n_t)))
            # up-axis: among the remaining two, the one most parallel to the canonical 'up'.
            others = [k for k in range(3) if k != look_k]
            up_k = max(others, key=lambda k: abs(float(pat[k] @ up_t)))
            look_axis = eye[look_k]
            up_axis = eye[up_k]
            # Signs (from A) so screen-up and screen-right hit the canonical patient targets.
            s_up = 1.0 if float(pat[up_k] @ up_t) >= 0.0 else -1.0
            view_up = s_up * up_axis
            sr_plus = np.cross(look_axis, view_up)
            s_look = 1.0 if float((A @ sr_plus) @ right_t) >= 0.0 else -1.0
            dir_w = s_look * look_axis
            center = np.asarray(self.center, dtype=float)
            pos = center - dir_w               # ResetCamera() (caller) sets the actual distance
            result = (pos.tolist(), center.tolist(), view_up.tolist())
            try:
                if getattr(self, "_anat_look_axis", None) is None:
                    self._anat_look_axis = {}
                if getattr(self, "_anat_up_axis", None) is None:
                    self._anat_up_axis = {}
                self._anat_look_axis[view_name] = int(look_k)
                self._anat_up_axis[view_name] = int(up_k)
            except Exception:
                pass
            cache[view_name] = (result, int(look_k), int(up_k))
            return result
        except Exception as exc:
            logger.warning("[ZETA_MPR_ANAT] camera build failed for %s: %r", view_name, exc)
            return None

    # Legacy axial-native interaction axes per pane: (look, h, v) = (through-plane,
    # screen-horizontal, screen-vertical) VOLUME-world axis indices. These reproduce the original
    # hardcoded crosshair geometry exactly (axial in-plane X,Y / through Z; sagittal Y,Z / X;
    # coronal X,Z / Y).
    _LEGACY_VIEW_AXES = {
        'axial':    (2, 0, 1),
        'sagittal': (0, 1, 2),
        'coronal':  (1, 0, 2),
    }

    def _view_axes(self, view_name):
        """Return (look_axis, h_axis, v_axis) VOLUME-world axis indices for a pane.

        This is the single source of truth for ALL crosshair-interaction geometry — slice
        following (`_update_slice_positions`), crosshair line endpoints, drag mapping, rotation,
        and oblique sample points — so the interaction matches the pane's ACTUAL camera.

        When the plane-aware anatomical cameras are active the axes come from the routing:
        ``look`` = `_anat_look_axis` (the volume axis the camera looks down = through-plane),
        ``v`` = `_anat_up_axis` (the volume axis aligned with screen-up), ``h`` = the remaining
        axis (screen-horizontal). This is what makes a NON-axial native series (e.g. sagittal,
        routed into the Sagittal pane) move/rotate/reslice correctly instead of driving the wrong
        axis (which slid the slice out of the volume → black image).

        Without anatomical routing — and, by construction, for an axial-native volume even WITH
        routing — this returns the legacy triples, so the original path is byte-identical (no
        regression). Falls back to legacy on any inconsistency.
        """
        legacy = self._LEGACY_VIEW_AXES.get(view_name, (2, 0, 1))
        if not getattr(self, "_mpr_use_anatomical", False):
            return legacy
        try:
            la = getattr(self, "_anat_look_axis", None)
            ua = getattr(self, "_anat_up_axis", None)
            if not (isinstance(la, dict) and isinstance(ua, dict)
                    and view_name in la and view_name in ua):
                # Cameras not built yet for this view → build (populates the dicts), then re-read.
                self._anatomical_camera(view_name)
                la = getattr(self, "_anat_look_axis", None)
                ua = getattr(self, "_anat_up_axis", None)
            look = int(la[view_name])
            v = int(ua[view_name])
            h = ({0, 1, 2} - {look, v}).pop()
            if look == v or look == h or v == h:
                return legacy
            return (look, h, v)
        except Exception:
            return legacy

    def _anatomical_labels(self):
        """Orientation labels computed from the actual anatomical cameras, so the markers always
        match the rendered image (never the reverse). Returns None on any problem (caller falls
        back to the legacy hardcoded labels)."""
        try:
            A = getattr(self, "_anat_A", None)
            if A is None:
                return None
            out = {}
            for view in ('axial', 'sagittal', 'coronal'):
                cam = self._anatomical_camera(view)
                if cam is None:
                    return None
                pos = np.asarray(cam[0], dtype=float)
                focal = np.asarray(cam[1], dtype=float)
                up_w = np.asarray(cam[2], dtype=float)
                dir_w = focal - pos
                dir_w = dir_w / (float(np.linalg.norm(dir_w)) or 1.0)
                right_w = np.cross(dir_w, up_w)          # screen-right (world)
                up_pat = A @ up_w
                right_pat = A @ right_w
                out[view] = {
                    'top':    self._lps_label(up_pat),
                    'bottom': self._lps_label(-up_pat),
                    'right':  self._lps_label(right_pat),
                    'left':   self._lps_label(-right_pat),
                }
            return out
        except Exception as exc:
            logger.warning("[ZETA_MPR_ANAT] label build failed: %r", exc)
            return None

    # ------------------------------------------------------------------
    # Camera vector computation  (CRITICAL — direction matrix handling)
    # ------------------------------------------------------------------

    def _get_camera_vectors_for_view(self, view_name):
        """
        Calculate camera position, focal point, and view-up vectors for a view
        using the DICOM direction matrix for proper orientation.
        """
        # Anatomical-camera path (ZetaAnatA present): orient each view directly from patient
        # axes so the reconstructed planes are canonical with NO Roll/Azimuth. See
        # _anatomical_camera + ZETA_MPR_SAGITTAL_AP_AND_WRIST_INVESTIGATION_2026-06-03.md.
        if getattr(self, "_mpr_use_anatomical", False) and getattr(self, "_anat_A", None) is not None:
            cam = self._anatomical_camera(view_name)
            if cam is not None:
                return cam

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
        """Log orientation information for debugging.

        This block does many synchronous ``print()`` + ``sys.stdout.flush()`` calls, which stall
        the main thread during MPR open. It is gated to debug only: skipped when there is no
        console (frozen build) OR when ``ZETA_MPR_DIAG`` is not ``1``. Enable with
        ``ZETA_MPR_DIAG=1`` to get the console dump.
        """
        import sys as _sys
        import os as _os
        if _sys.stdout is None or _os.environ.get("ZETA_MPR_DIAG", "0") != "1":
            # No console (frozen) OR diagnostics off: skip all print/flush debug output.
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
            legacy = [-slice_dir[0], -slice_dir[1], -slice_dir[2]]
        elif view_name == 'sagittal':
            legacy = [-row_dir[0], -row_dir[1], -row_dir[2]]
        elif view_name == 'coronal':
            legacy = [-col_dir[0], -col_dir[1], -col_dir[2]]
        else:
            legacy = [0, 0, -1]

        # Plane-aware scroll: when the anatomical cameras are active a pane's look-axis may have
        # been rerouted (e.g. a sagittal acquisition lands in the Sagittal pane). Snap the scroll
        # to that pane's ACTUAL look-axis so the wheel advances the displayed slice instead of
        # panning. The legacy sign is preserved when the legacy vector has a component along that
        # axis (so axial-acquired / CT cases are byte-identical to before); otherwise default +.
        if getattr(self, "_mpr_use_anatomical", False):
            la = getattr(self, "_anat_look_axis", None)
            if isinstance(la, dict) and view_name in la:
                k = int(la[view_name])
                if 0 <= k <= 2:
                    s = 1.0 if legacy[k] >= 0 else -1.0
                    out = [0.0, 0.0, 0.0]
                    out[k] = s
                    return out

        return legacy

    def _get_orientation_labels(self):
        """Get orientation labels for display based on direction matrix."""
        # Anatomical path: compute labels from the ACTUAL cameras so the letters always match
        # the rendered image (one correct layer). Falls back to the legacy hardcoded tables.
        if getattr(self, "_mpr_use_anatomical", False) and getattr(self, "_anat_A", None) is not None:
            lab = self._anatomical_labels()
            if lab is not None:
                return lab
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
