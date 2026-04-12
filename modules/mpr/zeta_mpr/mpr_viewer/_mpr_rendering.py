"""
MPR Rendering Mixin — MIP, MinIP, thick slab, reset rendering.

Extracted from standard_mpr_viewer.py (Phase 5A refactoring).
"""
import logging

import vtkmodules.all as vtk

logger = logging.getLogger(__name__)


class _MprRenderingMixin:
    """Slab projections (MIP/MinIP/thick slab) and full rendering reset."""

    def _apply_mip(self):
        """Apply Maximum Intensity Projection to 2D MPR views"""
        try:
            logger.info("=" * 60)
            logger.info("APPLYING MIP (2D MPR views)")
            logger.info("=" * 60)

            from PySide6.QtWidgets import QInputDialog
            thickness_mm, ok = QInputDialog.getDouble(
                self,
                "MIP Thickness",
                "Enter slab thickness (mm):",
                float(self._mpr_slab_thickness_mm),
                0.1,
                200.0,
                1
            )
            if not ok:
                return

            self._apply_slab_projection(mode='max', thickness_mm=thickness_mm)

            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "MIP Applied", "Maximum Intensity Projection applied to Axial/Sagittal/Coronal views")

        except Exception as e:
            logger.error(f"ERROR in MIP: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Error applying MIP: {str(e)}")

    def _apply_minip(self):
        """Apply Minimum Intensity Projection to 2D MPR views"""
        try:
            logger.info("=" * 60)
            logger.info("APPLYING MinIP (2D MPR views)")
            logger.info("=" * 60)

            from PySide6.QtWidgets import QInputDialog
            thickness_mm, ok = QInputDialog.getDouble(
                self,
                "MinIP Thickness",
                "Enter slab thickness (mm):",
                float(self._mpr_slab_thickness_mm),
                0.1,
                200.0,
                1
            )
            if not ok:
                return

            self._apply_slab_projection(mode='min', thickness_mm=thickness_mm)

            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "MinIP Applied", "Minimum Intensity Projection applied to Axial/Sagittal/Coronal views")

        except Exception as e:
            logger.error(f"ERROR in MinIP: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Error applying MinIP: {str(e)}")

    def _apply_thick_slab(self, thickness_mm=None):
        """Apply Thick Slab MPR"""
        try:
            if thickness_mm is None:
                if hasattr(self, 'slab_thickness_spin'):
                    thickness_mm = self.slab_thickness_spin.value()
                else:
                    from PySide6.QtWidgets import QInputDialog
                    thickness_mm, ok = QInputDialog.getDouble(
                        self,
                        "Thick Slab Thickness",
                        "Enter slab thickness (mm):",
                        10.0,
                        0.1,
                        200.0,
                        1
                    )
                    if not ok:
                        return
            elif hasattr(self, 'slab_thickness_spin'):
                self.slab_thickness_spin.setValue(thickness_mm)

            thickness = thickness_mm
            logger.info("=" * 60)
            logger.info(f"APPLYING THICK SLAB MPR - Thickness: {thickness} mm")
            logger.info("=" * 60)

            self._apply_slab_projection(mode='max', thickness_mm=thickness)

            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                "Thick Slab Applied",
                f"Thick Slab MPR ({thickness} mm) applied to Axial/Sagittal/Coronal views"
            )

        except Exception as e:
            logger.error(f"ERROR in Thick Slab: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Error applying Thick Slab: {str(e)}")

    def _apply_slab_projection(self, mode, thickness_mm):
        """Apply slab projection to 2D MPR views using vtkImageResliceMapper slab settings."""
        self._mpr_slab_thickness_mm = thickness_mm
        self._mpr_slab_mode = mode

        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name not in self.viewers:
                continue

            mapper = self.viewers[view_name]['mapper']

            if not hasattr(mapper, 'SetSlabThickness'):
                logger.warning(f"Slab projection not supported on mapper for view: {view_name}")
                continue

            mapper.SetSlabThickness(thickness_mm)

            if mode == 'max' and hasattr(mapper, 'SetSlabTypeToMax'):
                mapper.SetSlabTypeToMax()
            elif mode == 'min' and hasattr(mapper, 'SetSlabTypeToMin'):
                mapper.SetSlabTypeToMin()
            elif mode == 'mean' and hasattr(mapper, 'SetSlabTypeToMean'):
                mapper.SetSlabTypeToMean()
            else:
                logger.warning(f"Unsupported slab mode '{mode}' for view: {view_name}")

            self._request_render(view_name)

    def _reset_rendering(self):
        """Reset to normal rendering"""
        try:
            logger.info("=" * 60)
            logger.info("RESETTING TO NORMAL RENDERING")
            logger.info("=" * 60)

            views_reset = 0

            # Reset 3D view to composite rendering
            if '3d' in self.viewers:
                try:
                    renderer = self.viewers['3d']['renderer']
                    mapper = self.viewers['3d']['mapper']
                    volume_property = self.viewers['3d']['property']

                    # Set blend mode to composite
                    mapper.SetBlendModeToComposite()
                    logger.info("3D view blend mode reset to Composite")

                    # Re-enable shading
                    volume_property.ShadeOn()
                    logger.info("Shading re-enabled")

                    # Reapply current preset
                    self._apply_volume_preset(volume_property, self.current_3d_preset)
                    logger.info(f"Preset {self.current_3d_preset} reapplied")

                    # Reset camera to standard radiological orientation
                    camera = renderer.GetActiveCamera()

                    # Reset camera to fit volume
                    renderer.ResetCamera()

                    # Set ViewUp
                    camera.SetViewUp(0, 0, 1)  # Z is up (superior direction)

                    # Calculate distance for good view
                    bounds = self.image_data.GetBounds()
                    distance = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]) * 2.0

                    # Anterior-oblique view
                    # After Y-flip: +Y = Anterior (Front)
                    camera.SetPosition(
                        self.center[0] + distance * 0.7,   # Right side
                        self.center[1] + distance * 1.2,   # Front (Anterior)
                        self.center[2] + distance * 0.4    # Elevated
                    )
                    camera.SetFocalPoint(self.center[0], self.center[1], self.center[2])
                    camera.Zoom(1.2)

                    logger.info("3D camera orientation reset to standard view")

                    # Render
                    renderer.GetRenderWindow().Render()
                    views_reset += 1
                    logger.info("3D view reset successfully")
                except Exception as e3d:
                    logger.error(f"Error resetting 3D view: {e3d}")

            # Reset 2D views - recreate them with original mappers
            reset_window, reset_level = self._get_initial_window_level()
            for view_name in ['axial', 'sagittal', 'coronal']:
                if view_name not in self.viewers:
                    continue

                try:
                    logger.info(f"Resetting {view_name} view...")
                    renderer = self.viewers[view_name]['renderer']

                    # Create new slice mapper
                    slice_mapper = vtk.vtkImageResliceMapper()
                    slice_mapper.SetInputData(self.image_data)
                    slice_mapper.SliceFacesCameraOn()
                    slice_mapper.SliceAtFocalPointOn()

                    # Create new image slice
                    image_slice = vtk.vtkImageSlice()
                    image_slice.SetMapper(slice_mapper)

                    # Set window/level to initial source-derived defaults
                    image_slice.GetProperty().SetColorWindow(reset_window)
                    image_slice.GetProperty().SetColorLevel(reset_level)

                    # Remove old actors and add new one
                    renderer.RemoveAllViewProps()
                    renderer.AddViewProp(image_slice)

                    # Reset camera to original position (v1.01 correct state)
                    camera = renderer.GetActiveCamera()
                    camera.ParallelProjectionOn()

                    # Use DICOM orientation for proper camera setup
                    camera_pos, focal_point, view_up = self._get_camera_vectors_for_view(view_name)
                    camera.SetPosition(camera_pos)
                    camera.SetFocalPoint(focal_point)
                    camera.SetViewUp(view_up)

                    # Apply CT-specific transformations (v1.01 baseline)
                    if self.detected_modality == "CT":
                        if view_name == 'sagittal':
                            camera.Roll(180)
                        elif view_name == 'coronal':
                            camera.Azimuth(180)
                            camera.Roll(180)

                    renderer.ResetCamera()
                    camera.Zoom(1.2)

                    # Recreate crosshairs for this view
                    if view_name in self.crosshair_actors:
                        # Remove old crosshairs
                        old_actors = self.crosshair_actors[view_name]
                        if 'h_line_actor' in old_actors:
                            renderer.RemoveActor(old_actors['h_line_actor'])
                        if 'v_line_actor' in old_actors:
                            renderer.RemoveActor(old_actors['v_line_actor'])
                        for handle in old_actors.get('handles', []):
                            renderer.RemoveActor(handle['actor'])

                    # Create fresh crosshairs
                    self._create_crosshairs(renderer, view_name)

                    # Recreate text annotation
                    if view_name in self.text_actors:
                        # Use RemoveViewProp instead of deprecated RemoveActor2D (VTK 9.5.0+)
                        renderer.RemoveViewProp(self.text_actors[view_name])
                    self._create_slice_info_text(renderer, view_name)

                    # Update viewer storage
                    self.viewers[view_name]['actor'] = image_slice
                    self.viewers[view_name]['mapper'] = slice_mapper

                    renderer.GetRenderWindow().Render()

                    views_reset += 1
                    logger.info(f"{view_name} view reset successfully")

                except Exception as view_error:
                    logger.error(f"Error resetting {view_name} view: {view_error}", exc_info=True)

            # Reset crosshair rotation to 0
            for view_name in self.crosshair_angles.keys():
                self.crosshair_angles[view_name] = 0.0

            # Reset to orthogonal slicing (remove any oblique transforms)
            self._reset_all_to_orthogonal()

            # Re-capture baseline after full view reset
            self._capture_baseline_camera_state()

            # Update all crosshairs to current position
            self._update_all_crosshairs()
            self._update_slice_positions()
            self._update_slice_info_texts()

            logger.info(f"Reset complete - {views_reset} views reset")
            logger.info("Crosshair rotation reset to 0°")
            logger.info("=" * 60)

            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                "Reset Complete",
                f"Rendering reset to normal for {views_reset} views"
            )

        except Exception as e:
            logger.error(f"ERROR in reset: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Error resetting rendering: {str(e)}")
