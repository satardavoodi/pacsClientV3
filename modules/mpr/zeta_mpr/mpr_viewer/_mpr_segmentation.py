"""
MPR Segmentation Mixin — lung, airway, vessel, bone segmentation + measurement viewport.

Extracted from standard_mpr_viewer.py (Phase 5A refactoring).
"""
import logging

import vtkmodules.all as vtk

logger = logging.getLogger(__name__)


class _MprSegmentationMixin:
    """Segmentation menu and all organ-specific segmentation methods."""

    def _show_segment_menu(self):
        """Show segmentation menu"""
        from PySide6.QtWidgets import QMenu, QMessageBox
        from PySide6.QtCore import Qt

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #2a2a2a;
                color: white;
                border: 1px solid #555;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
            }
            QMenu::item:selected {
                background: #3b82f6;
            }
        """)

        # Add segmentation options
        lung_action = menu.addAction("🫁 Segment Lungs")
        airway_action = menu.addAction("🌳 Segment Airways")
        vessel_action = menu.addAction("🩸 Segment Vessels")
        bone_action = menu.addAction("🦴 Segment Bone")
        menu.addSeparator()
        clear_action = menu.addAction("🗑️ Clear All")

        # Show menu at button position
        action = menu.exec_(self.segment_btn.mapToGlobal(self.segment_btn.rect().bottomLeft()))

        # Handle action
        if action == lung_action:
            self._segment_lungs()
        elif action == airway_action:
            self._segment_airways()
        elif action == vessel_action:
            self._segment_vessels()
        elif action == bone_action:
            self._segment_bone()
        elif action == clear_action:
            self._clear_segmentation()

    def _segment_lungs(self):
        """Segment lungs"""
        try:
            logger.info("Starting lung segmentation...")

            from ..segmentation_tools import LungSegmenter

            # Create lung segmenter
            segmenter = LungSegmenter(self.image_data)

            # Segment lungs (auto-find seeds)
            lung_mask = segmenter.segment_lungs(auto_find_seeds=True)

            if lung_mask:
                # Store result
                self.segmentation_results['lungs'] = lung_mask

                # Create surface mesh
                surface = segmenter.create_surface_mesh(lung_mask, smooth=True)

                # Add to 3D view
                if '3d' in self.viewers and surface:
                    renderer = self.viewers['3d']['renderer']

                    # Create mapper and actor
                    mapper = vtk.vtkPolyDataMapper()
                    mapper.SetInputData(surface)

                    actor = vtk.vtkActor()
                    actor.SetMapper(mapper)
                    actor.GetProperty().SetColor(0.8, 0.3, 0.3)  # Red-ish
                    actor.GetProperty().SetOpacity(0.5)

                    renderer.AddActor(actor)
                    renderer.GetRenderWindow().Render()

                    logger.info("Lung segmentation completed")
            else:
                logger.warning("Lung segmentation failed")

        except Exception as e:
            logger.error(f"Error in lung segmentation: {e}")

    def _segment_airways(self):
        """Segment airways"""
        try:
            logger.info("Starting airway segmentation...")

            from ..segmentation_tools import AirwaySegmenter

            segmenter = AirwaySegmenter(self.image_data)
            airway_mask = segmenter.segment_airways(auto_find_seed=True)

            if airway_mask:
                self.segmentation_results['airways'] = airway_mask
                logger.info("Airway segmentation completed")

        except Exception as e:
            logger.error(f"Error in airway segmentation: {e}")

    def _segment_vessels(self):
        """Segment vessels"""
        try:
            logger.info("Starting vessel segmentation...")

            from ..segmentation_tools import VesselSegmenter

            segmenter = VesselSegmenter(self.image_data)
            vessel_mask = segmenter.segment_vessels(
                lower_threshold=100,
                upper_threshold=500
            )

            if vessel_mask:
                self.segmentation_results['vessels'] = vessel_mask
                logger.info("Vessel segmentation completed")

        except Exception as e:
            logger.error(f"Error in vessel segmentation: {e}")

    def _segment_bone(self):
        """Segment bone"""
        try:
            logger.info("Starting bone segmentation...")

            from ..segmentation_tools import BoneSegmenter

            segmenter = BoneSegmenter(self.image_data)
            bone_mask = segmenter.segment_bone(threshold=250)

            if bone_mask:
                self.segmentation_results['bone'] = bone_mask

                # Create 3D model
                bone_surface = segmenter.create_3d_model(bone_mask, smooth=True)

                # Add to 3D view
                if '3d' in self.viewers and bone_surface:
                    renderer = self.viewers['3d']['renderer']

                    mapper = vtk.vtkPolyDataMapper()
                    mapper.SetInputData(bone_surface)

                    actor = vtk.vtkActor()
                    actor.SetMapper(mapper)
                    actor.GetProperty().SetColor(0.9, 0.9, 0.8)  # Bone color

                    renderer.AddActor(actor)
                    renderer.GetRenderWindow().Render()

                    logger.info("Bone segmentation completed")

        except Exception as e:
            logger.error(f"Error in bone segmentation: {e}")

    def _clear_segmentation(self):
        """Clear all segmentation results"""
        try:
            self.segmentation_results.clear()

            # Remove segmentation actors from 3D view
            if '3d' in self.viewers:
                renderer = self.viewers['3d']['renderer']
                # This would need more sophisticated actor management
                # For now, just log
                logger.info("Segmentation cleared")

        except Exception as e:
            logger.error(f"Error clearing segmentation: {e}")

    def get_active_viewport_for_measurements(self):
        """
        Get the active viewport widget for measurement tools.
        Returns the VTK widget of the active measurement viewport.
        This is used when Crosshairs are OFF and user wants to use measurement tools.
        """
        if self.active_measurement_viewport in self.viewers:
            return self.viewers[self.active_measurement_viewport]['widget']
        # Default to axial if active viewport not found
        if 'axial' in self.viewers:
            self.active_measurement_viewport = 'axial'
            return self.viewers['axial']['widget']
        return None

    def set_active_measurement_viewport(self, view_name):
        """
        Set which viewport should be active for measurement tools.
        Args:
            view_name: 'axial', 'sagittal', or 'coronal'
        """
        if view_name in self.viewers and view_name in ['axial', 'sagittal', 'coronal']:
            self.active_measurement_viewport = view_name
            logger.info(f"Active measurement viewport set to: {view_name}")
        else:
            logger.warning(f"Invalid viewport name: {view_name}")
