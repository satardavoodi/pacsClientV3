"""
MPR Oblique Reslicing Mixin — 9-point dual-tier oblique slicing.

Extracted from standard_mpr_viewer.py (Phase 5A refactoring).
"""
import logging
import math

import numpy as np
import vtkmodules.all as vtk

logger = logging.getLogger(__name__)


class _MprObliqueMixin:
    """Oblique reslicing: 9-point sampling, camera-stable plane setting, reset."""

    # ── 9-Point Oblique MPR (v1.07) ─────────────────────────────────

    def _update_oblique_reslicing(self):
        """
        9-Point Oblique MPR (v1.07) — dual-tier sampling.

        Uses the center point + 8 sample points (two tiers per crosshair
        line) to define oblique slice planes for perpendicular views via
        camera repositioning.

        When crosshairs rotate in a source view, the two crosshair lines
        trace the intersection of two perpendicular oblique planes with
        the source view's slice plane.  For each crosshair line:

            oblique_plane_normal = line_direction × source_slice_normal

        Two tiers of sample points per line provide robustness:
          • Outer tier (quarter) — at 25% of shortest axis span from
            center.  Larger baseline → higher directional precision.
          • Inner tier  (sixth)  — at 1/6 of shortest axis span from
            center.  Closer to centre → always inside the FOV even
            when the crosshair centre is near the volume edge.

        If either outer-tier point falls outside the image FOV, the
        inner-tier pair is used as a fallback for direction computation.

        Each reconstruction plane therefore has **5 sample points**:
          C        = crosshair intersection  (self.current_position)
          outer_p1 = outer tier, positive direction
          outer_p2 = outer tier, negative direction
          inner_p1 = inner tier, positive direction
          inner_p2 = inner tier, negative direction

        9 points per source view  (C + 4 per line × 2 lines).
        5 points per target reconstruction plane (C + 4 on the
        relevant line).
        """
        if not bool(getattr(self, "_guard_logged_mpr_oblique_update", False)):
            logger.warning(
                "[GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH] feature=zeta_mpr_oblique_update "
                "reason=local_oblique_plane_update_without_advanced_contract_adapter "
                "fallback_behavior=continue_legacy_mpr_oblique_path action=warn_only"
            )
            try:
                setattr(self, "_guard_logged_mpr_oblique_update", True)
            except Exception:
                pass
        if not self.oblique_enabled:
            logger.debug("Oblique reslicing disabled - crosshair rotation is visual only")
            if self._oblique_cameras_active:
                self._reset_all_to_orthogonal()
            return

        # Check if any view has rotation
        has_rotation = any(abs(angle) > 0.01 for angle in self.crosshair_angles.values())

        if not has_rotation:
            if self._oblique_cameras_active:
                self._reset_all_to_orthogonal()
            return

        bounds = self.image_data.GetBounds()

        # Track which target views have been updated (last write wins)
        for source_view, angle in self.crosshair_angles.items():
            if abs(angle) < 0.01:
                continue

            # ── 9 points: dual-tier sampling (quarter + sixth) ──────
            # Two tiers of sample points per crosshair line:
            #   Outer tier (quarter): 25 % of shortest axis span
            #   Inner tier (sixth):   1/6 of shortest axis span
            # Outer pair has larger baseline → better precision.
            # Inner pair is a robust fallback when the crosshair
            # centre is near the volume edge and outer points
            # leave the FOV.
            # → 5 points per reconstruction plane:
            #     C + 2 outer + 2 inner.

            cx, cy, cz = self.current_position
            angle = self.crosshair_angles.get(source_view, 0.0)

            axis_spans = [
                bounds[1] - bounds[0],
                bounds[3] - bounds[2],
                bounds[5] - bounds[4],
            ]
            shortest = min(s for s in axis_spans if s > 0)
            dist_quarter = shortest * 0.25       # outer tier
            dist_sixth   = shortest / 6.0        # inner tier (fallback)

            cos_a  = math.cos(angle)
            sin_a  = math.sin(angle)
            cos_a2 = math.cos(angle + math.pi / 2)
            sin_a2 = math.sin(angle + math.pi / 2)

            if source_view == 'axial':
                # Horizontal line — outer (quarter)
                h_q1 = [cx + dist_quarter * cos_a,  cy + dist_quarter * sin_a,  cz]
                h_q2 = [cx - dist_quarter * cos_a,  cy - dist_quarter * sin_a,  cz]
                # Horizontal line — inner (sixth)
                h_s1 = [cx + dist_sixth * cos_a,    cy + dist_sixth * sin_a,    cz]
                h_s2 = [cx - dist_sixth * cos_a,    cy - dist_sixth * sin_a,    cz]
                # Vertical line — outer (quarter)
                v_q1 = [cx + dist_quarter * cos_a2, cy + dist_quarter * sin_a2, cz]
                v_q2 = [cx - dist_quarter * cos_a2, cy - dist_quarter * sin_a2, cz]
                # Vertical line — inner (sixth)
                v_s1 = [cx + dist_sixth * cos_a2,   cy + dist_sixth * sin_a2,   cz]
                v_s2 = [cx - dist_sixth * cos_a2,   cy - dist_sixth * sin_a2,   cz]

            elif source_view == 'sagittal':
                h_q1 = [cx, cy + dist_quarter * cos_a,  cz + dist_quarter * sin_a]
                h_q2 = [cx, cy - dist_quarter * cos_a,  cz - dist_quarter * sin_a]
                h_s1 = [cx, cy + dist_sixth * cos_a,    cz + dist_sixth * sin_a]
                h_s2 = [cx, cy - dist_sixth * cos_a,    cz - dist_sixth * sin_a]
                v_q1 = [cx, cy + dist_quarter * cos_a2, cz + dist_quarter * sin_a2]
                v_q2 = [cx, cy - dist_quarter * cos_a2, cz - dist_quarter * sin_a2]
                v_s1 = [cx, cy + dist_sixth * cos_a2,   cz + dist_sixth * sin_a2]
                v_s2 = [cx, cy - dist_sixth * cos_a2,   cz - dist_sixth * sin_a2]

            elif source_view == 'coronal':
                h_q1 = [cx + dist_quarter * cos_a,  cy, cz + dist_quarter * sin_a]
                h_q2 = [cx - dist_quarter * cos_a,  cy, cz - dist_quarter * sin_a]
                h_s1 = [cx + dist_sixth * cos_a,    cy, cz + dist_sixth * sin_a]
                h_s2 = [cx - dist_sixth * cos_a,    cy, cz - dist_sixth * sin_a]
                v_q1 = [cx + dist_quarter * cos_a2, cy, cz + dist_quarter * sin_a2]
                v_q2 = [cx - dist_quarter * cos_a2, cy, cz - dist_quarter * sin_a2]
                v_s1 = [cx + dist_sixth * cos_a2,   cy, cz + dist_sixth * sin_a2]
                v_s2 = [cx - dist_sixth * cos_a2,   cy, cz - dist_sixth * sin_a2]

            # Best direction from outermost valid pair (fallback to inner)
            h_dir = self._best_line_direction(h_q1, h_q2, h_s1, h_s2, bounds)
            v_dir = self._best_line_direction(v_q1, v_q2, v_s1, v_s2, bounds)

            # ── source slice normal & target mapping ──────────────────
            # v1.09: Use the baseline camera direction as the slice
            # normal instead of hardcoded axis vectors.  This is correct
            # for non-identity direction matrices and after CT camera
            # corrections.  Falls back to axis-aligned defaults when
            # baseline state is unavailable.
            #
            # In each source view the horizontal crosshair line is the
            # trace of one target plane and the vertical line is the
            # trace of the other.
            baseline = self._baseline_camera_state.get(source_view)
            if baseline is not None:
                # baseline['direction'] is unit vector: focal − pos
                # The slice normal is the viewing direction (camera looks
                # perpendicular to the slice plane).
                slice_normal = np.array(baseline['direction'], dtype=float)
            else:
                # Fallback to axis-aligned defaults
                if source_view == 'axial':
                    slice_normal = np.array([0.0, 0.0, 1.0])
                elif source_view == 'sagittal':
                    slice_normal = np.array([1.0, 0.0, 0.0])
                elif source_view == 'coronal':
                    slice_normal = np.array([0.0, 1.0, 0.0])
                else:
                    continue

            if source_view == 'axial':
                targets = [
                    ('sagittal', v_dir),   # vertical line → sagittal trace
                    ('coronal',  h_dir),   # horizontal line → coronal trace
                ]
            elif source_view == 'sagittal':
                targets = [
                    ('axial',   h_dir),
                    ('coronal', v_dir),
                ]
            elif source_view == 'coronal':
                targets = [
                    ('axial',    h_dir),
                    ('sagittal', v_dir),
                ]
            else:
                continue

            for target_view, line_dir in targets:
                # Oblique plane normal = line_direction × source_slice_normal
                oblique_normal = np.cross(line_dir, slice_normal)
                norm_mag = np.linalg.norm(oblique_normal)
                if norm_mag < 1e-8:
                    continue  # degenerate – line parallel to slice normal
                oblique_normal /= norm_mag

                self._set_oblique_camera(target_view, oblique_normal)

        logger.debug(
            "9-pt oblique: ax=%.1f° sag=%.1f° cor=%.1f°",
            math.degrees(self.crosshair_angles.get('axial', 0.0)),
            math.degrees(self.crosshair_angles.get('sagittal', 0.0)),
            math.degrees(self.crosshair_angles.get('coronal', 0.0)),
        )

    # ─── helpers for 9-point oblique ────────────────────────────────────

    def _best_line_direction(self, p1_outer, p2_outer, p1_inner, p2_inner, bounds):
        """
        Return the normalised direction vector for a crosshair line.

        Prefers the outer (quarter) pair — larger baseline gives higher
        directional precision.  Falls back to the inner (sixth) pair if
        either outer point is outside the image FOV.
        """
        if (self._point_inside_bounds(p1_outer, bounds)
                and self._point_inside_bounds(p2_outer, bounds)):
            d = np.array(p1_outer, dtype=float) - np.array(p2_outer, dtype=float)
        else:
            d = np.array(p1_inner, dtype=float) - np.array(p2_inner, dtype=float)

        mag = np.linalg.norm(d)
        if mag > 1e-8:
            d /= mag
        return d

    @staticmethod
    def _point_inside_bounds(pt, bounds):
        """True if *pt* lies within the 6-component VTK image bounds."""
        return (bounds[0] <= pt[0] <= bounds[1]
                and bounds[2] <= pt[1] <= bounds[3]
                and bounds[4] <= pt[2] <= bounds[5])

    def _set_oblique_camera(self, target_view, oblique_normal):
        """
        Set an oblique slice plane on *target_view*'s mapper.

        v1.09.Fix-E — camera-stable oblique slicing:

        Instead of repositioning the camera (which shifts the viewport
        centre and makes the displayed image appear to move), we switch
        the vtkImageResliceMapper from camera-driven slicing to an
        explicit vtkPlane.  The camera stays in its original orthogonal
        position, so the viewport is perfectly stable.

        The explicit plane:
            origin = self.current_position   (crosshair centre)
            normal = oblique_normal          (sign-corrected)

        When the crosshair centre moves later (_update_slice_positions),
        only the plane origin is updated — the camera still only tracks
        the through-plane axis, identical to orthogonal behaviour.
        """
        if target_view not in self.viewers:
            return

        viewer   = self.viewers[target_view]
        mapper   = viewer['mapper']
        renderer = viewer['renderer']

        # --- baseline reference (for sign consistency) --------------------
        baseline = self._baseline_camera_state.get(target_view)
        if baseline is not None:
            baseline_dir = np.array(baseline['direction'], dtype=float)
        else:
            # Axis-aligned fallback
            _defaults = {
                'axial':    np.array([0., 0., -1.]),
                'sagittal': np.array([-1., 0., 0.]),
                'coronal':  np.array([0., -1., 0.]),
            }
            baseline_dir = _defaults.get(target_view, np.array([0., 0., -1.]))

        oblique_normal = np.array(oblique_normal, dtype=float)

        # Sign consistency: keep normal in the same hemisphere as the
        # baseline camera→focal direction so back-face orientation matches.
        if float(np.dot(oblique_normal, -baseline_dir)) < 0:
            oblique_normal = -oblique_normal

        # --- Switch mapper to explicit-plane mode -------------------------
        mapper.SliceFacesCameraOff()
        mapper.SliceAtFocalPointOff()

        # Get-or-create the vtkPlane attached to this mapper
        plane = mapper.GetSlicePlane()
        if plane is None:
            plane = vtk.vtkPlane()

        plane.SetOrigin(self.current_position)
        plane.SetNormal(oblique_normal.tolist())
        mapper.SetSlicePlane(plane)
        mapper.Modified()

        # Camera stays UNTOUCHED — no viewport shift.
        # Just fix clipping in case the oblique plane extends differently.
        renderer.ResetCameraClippingRange()

        self._oblique_cameras_active = True
        self._request_render(target_view)

        # --- diagnostic validation ----------------------------------------
        if hasattr(self, '_diag'):
            self._diag.validate_after_oblique(target_view, oblique_normal)

    def _clamp_to_fov(self, center, endpoint, bounds):
        """
        If *endpoint* lies outside the image FOV (bounds), compute a
        replacement point on the same ray center→endpoint that sits at
        the volume boundary edge.  Direction is preserved; only the
        distance from center shrinks.

        Parameters
        ----------
        center   : list[float]  –  crosshair intersection (assumed inside)
        endpoint : list[float]  –  peripheral crosshair endpoint
        bounds   : tuple        –  (xmin, xmax, ymin, ymax, zmin, zmax)

        Returns
        -------
        list[float]  –  original endpoint if inside, or clamped point
        """
        c = np.array(center, dtype=float)
        p = np.array(endpoint, dtype=float)
        d = p - c

        # Find the largest t ∈ (0, 1] such that  c + t·d  is inside bounds.
        # For each axis the ray exits at t = (boundary − c_i) / d_i.
        t_max = 1.0
        for i in range(3):
            if abs(d[i]) < 1e-10:
                continue
            if d[i] > 0:
                t_i = (bounds[2 * i + 1] - c[i]) / d[i]
            else:
                t_i = (bounds[2 * i] - c[i]) / d[i]
            if t_i < t_max:
                t_max = max(t_i, 0.0)

        if t_max < 1.0 - 1e-8:
            # Pull 2 % inward so the point sits safely inside bounds
            t_safe = t_max * 0.98
            return (c + t_safe * d).tolist()
        return list(endpoint)

    def _reset_all_to_orthogonal(self):
        """
        Reset all views to standard orthogonal camera positions.
        Preserves zoom (ParallelScale) and restores original mappers
        if the old reslice approach left swapped mappers behind.
        Called only when transitioning from oblique back to orthogonal.
        """

        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name not in self.viewers:
                continue

            renderer = self.viewers[view_name]['renderer']
            camera   = renderer.GetActiveCamera()

            # Preserve zoom
            parallel_scale = camera.GetParallelScale()

            # ── v1.09.Fix-E: restore mapper to camera-driven slicing ──
            mapper = self.viewers[view_name].get('mapper')
            if mapper is not None:
                mapper.SliceFacesCameraOn()
                mapper.SliceAtFocalPointOn()
                mapper.Modified()

            # Standard camera vectors from direction matrix
            position, focal, view_up = self._get_camera_vectors_for_view(view_name)

            camera.SetPosition(position)
            camera.SetFocalPoint(focal)
            camera.SetViewUp(view_up)

            # CT-specific display corrections
            if self.detected_modality == "CT":
                if view_name == 'sagittal':
                    camera.Roll(180)
                elif view_name == 'coronal':
                    camera.Azimuth(180)
                    camera.Roll(180)

            # Reset camera distance (preserves direction, fixes clipping)
            renderer.ResetCamera()
            camera.SetParallelScale(parallel_scale)

            # Restore original mapper if swapped by legacy reslice approach
            if 'original_mapper' in self.viewers[view_name]:
                original_mapper = self.viewers[view_name]['original_mapper']
                self.viewers[view_name]['actor'].SetMapper(original_mapper)
                self.viewers[view_name]['mapper'] = original_mapper
                del self.viewers[view_name]['original_mapper']

                window, level = self._get_default_window_level()
                self.viewers[view_name]['actor'].GetProperty().SetColorWindow(window)
                self.viewers[view_name]['actor'].GetProperty().SetColorLevel(level)

            self._request_render(view_name)
            logger.debug(f"Reset {view_name} to orthogonal")

        # ── v1.09.Fix-C: switch to orthogonal BEFORE repositioning ──
        # Must clear flag first so _update_slice_positions uses the
        # orthogonal code path (moves both position + focal together,
        # preserving camera direction).  Previously the flag was cleared
        # AFTER, causing the oblique path (focal-only) to leave the
        # camera direction slightly off after reset.
        self._oblique_cameras_active = False

        # Reposition cameras to current crosshair position
        self._update_slice_positions()

        # ── v1.09.Fix-D: re-capture baseline after reset ──
        # ResetCamera() may have shifted pos/focal slightly from the
        # original setup.  Refresh baseline so subsequent oblique
        # computations reference the actual clean state.
        self._capture_baseline_camera_state()

        # Diagnostic: verify reset returned to clean state
        if hasattr(self, '_diag'):
            self._diag.capture_baseline()  # sync diag baselines too
            self._diag.validate_after_reset()
