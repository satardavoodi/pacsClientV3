"""
MPR Series Mixin — series scroller, switch, highlight, reload.

Extracted from standard_mpr_viewer.py (Phase 5A refactoring).
"""
import logging

import vtkmodules.all as vtk
from PySide6.QtWidgets import QWidget, QLabel, QPushButton
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)


class _MprSeriesMixin:
    """Series scroller sidebar, series switching, highlight, and reload."""

    def _create_series_scroller(self):
        """Create series scroller sidebar like 2D viewer"""
        from PySide6.QtWidgets import QScrollArea, QVBoxLayout
        from PySide6.QtCore import Qt

        # Main scroller widget
        scroller_widget = QWidget()
        scroller_widget.setFixedWidth(120)
        scroller_widget.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border-right: 1px solid #3a3a3a;
            }
        """)

        scroller_layout = QVBoxLayout(scroller_widget)
        scroller_layout.setContentsMargins(4, 8, 4, 8)
        scroller_layout.setSpacing(6)

        # Title label
        title_label = QLabel("Series")
        title_label.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 11px;
                font-weight: bold;
                padding: 4px;
            }
        """)
        title_label.setAlignment(Qt.AlignCenter)
        scroller_layout.addWidget(title_label)

        # Scroll area for series thumbnails
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                border: 1px solid #4b5563;
                background: #1f2937;
                width: 8px;
                margin: 0px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #374151;
                min-height: 30px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4b5563;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
                width: 0px;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

        # Container for series items
        series_container = QWidget()
        series_items_layout = QVBoxLayout(series_container)
        series_items_layout.setContentsMargins(0, 0, 0, 0)
        series_items_layout.setSpacing(6)

        # Try to get series list from parent
        try:
            # Navigate up to find patient_widget
            parent = self.parent()
            thumbnails_data = []

            while parent is not None:
                if hasattr(parent, 'lst_thumbnails_data'):
                    thumbnails_data = parent.lst_thumbnails_data
                    logger.info(f"Found {len(thumbnails_data)} series for scroller")
                    break
                parent = parent.parent()

            # Create series items
            self.series_buttons = []
            for i, thumb_data in enumerate(thumbnails_data):
                try:
                    metadata = thumb_data.get('metadata', {})
                    series_metadata = metadata.get('series', {})
                    series_number = series_metadata.get('series_number', f'{i+1}')
                    series_desc = series_metadata.get('series_description', 'Series')

                    # Trim description if too long
                    if len(str(series_desc)) > 15:
                        series_desc = str(series_desc)[:12] + '...'

                    # Series button
                    btn = QPushButton(f"{series_number}\n{series_desc}")
                    btn.setFixedSize(100, 70)
                    btn.setCursor(Qt.PointingHandCursor)
                    btn.setStyleSheet("""
                        QPushButton {
                            background: #252525;
                            color: #aaa;
                            border: 1px solid #444;
                            border-radius: 4px;
                            padding: 4px;
                            font-size: 10px;
                            text-align: center;
                        }
                        QPushButton:hover {
                            background: #333;
                            border-color: #0066cc;
                            color: #fff;
                        }
                        QPushButton:checked {
                            background: #0066cc;
                            color: #fff;
                            border-color: #0077ee;
                        }
                    """)

                    # Store series data
                    btn.setProperty('series_index', series_number)
                    btn.setProperty('vtk_data', thumb_data.get('vtk_image_data'))
                    btn.setProperty('dicom_dir', series_metadata.get('series_path'))

                    # Connect to switch series
                    btn.clicked.connect(lambda checked, b=btn: self._switch_series(b))

                    self.series_buttons.append(btn)
                    series_items_layout.addWidget(btn)

                except Exception as e:
                    logger.error(f"Error creating series button {i}: {e}")
                    continue

            # Add stretch at bottom
            series_items_layout.addStretch()

        except Exception as e:
            logger.error(f"Error creating series scroller: {e}")
            # Add placeholder if error
            placeholder = QLabel("Series\nUnavailable")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color: #666; font-size: 10px;")
            series_items_layout.addWidget(placeholder)
            series_items_layout.addStretch()

        scroll_area.setWidget(series_container)
        scroller_layout.addWidget(scroll_area)

        return scroller_widget

    def _switch_series(self, button):
        """Switch to a different series in MPR"""
        try:
            series_index = button.property('series_index')
            vtk_data = button.property('vtk_data')
            dicom_dir = button.property('dicom_dir')

            if vtk_data is None:
                logger.warning(f"No VTK data for series {series_index}")
                return

            logger.info(f"Switching MPR to series {series_index}")

            # Update all series buttons to unchecked
            for btn in self.series_buttons:
                btn.setChecked(False)

            # Check the clicked button
            button.setChecked(True)

            # Reload MPR with new series
            self._reload_with_series(vtk_data, dicom_dir)

        except Exception as e:
            logger.error(f"Error switching series: {e}", exc_info=True)

    def _highlight_current_series(self):
        """Highlight the currently displayed series in the scroller"""
        try:
            # Try to get the original series index from parent
            parent = self.parent()
            current_series = None

            while parent is not None:
                if hasattr(parent, 'selected_widget') and hasattr(parent.selected_widget, 'last_series_show'):
                    current_series = parent.selected_widget.last_series_show
                    logger.info(f"Found current series: {current_series}")
                    break
                parent = parent.parent()

            if current_series is None:
                logger.warning("Could not find current series index")
                return

            # Check the matching series button
            for btn in self.series_buttons:
                series_idx = btn.property('series_index')
                if str(series_idx) == str(current_series):
                    btn.setChecked(True)
                    logger.info(f"✓ Highlighted series {series_idx} in scroller")
                    break

        except Exception as e:
            logger.error(f"Error highlighting current series: {e}")

    def _reload_with_series(self, vtk_image_data, dicom_directory=None):
        """Reload MPR with a different series"""
        try:
            logger.info("Reloading MPR with new series...")

            # Apply input-level flip first
            image_flip = vtk.vtkImageFlip()
            image_flip.SetInputData(vtk_image_data)
            image_flip.SetFilteredAxis(0)  # Flip along X axis (left-right)
            image_flip.Update()

            # Store flipped data
            self.image_data = image_flip.GetOutput()

            # Copy field data from original to flipped image
            field_data = vtk_image_data.GetFieldData()
            if field_data:
                self.image_data.GetFieldData().ShallowCopy(field_data)

            # Reinitialize key attributes
            self.dims = self.image_data.GetDimensions()
            self.origin = self.image_data.GetOrigin()
            self.spacing = self.image_data.GetSpacing()
            self.scalar_range = self.image_data.GetScalarRange()

            # Reset crosshair position to center
            self.current_position = [
                self.origin[0] + (self.dims[0] - 1) * self.spacing[0] / 2.0,
                self.origin[1] + (self.dims[1] - 1) * self.spacing[1] / 2.0,
                self.origin[2] + (self.dims[2] - 1) * self.spacing[2] / 2.0
            ]

            # Update each view with new data
            for view_name in ['axial', 'sagittal', 'coronal']:
                if view_name not in self.viewers:
                    continue

                viewer_dict = self.viewers[view_name]

                # Update mapper input
                if 'mapper' in viewer_dict:
                    viewer_dict['mapper'].SetInputData(self.image_data)

                # Reset camera to new volume
                renderer = viewer_dict['renderer']
                camera = renderer.GetActiveCamera()

                # Recalculate camera for new volume
                position, focal, view_up = self._get_camera_vectors_for_view(view_name)
                camera.SetPosition(position)
                camera.SetFocalPoint(focal)
                camera.SetViewUp(view_up)
                renderer.ResetCamera()

                # Apply CT-specific camera adjustments if needed
                if self.detected_modality == "CT":
                    if view_name == 'sagittal':
                        camera.Roll(180)
                    elif view_name == 'coronal':
                        camera.Azimuth(180)
                        camera.Roll(180)

                self._request_render(view_name)

            # Capture fresh baseline after camera recreation
            self._capture_baseline_camera_state()
            # Update crosshairs
            self._update_all_crosshairs()
            self._update_slice_positions()
            self._synchronize_oblique_views()
            self._update_slice_info_texts()

            logger.info("✓ MPR reloaded with new series")

        except Exception as e:
            logger.error(f"Error reloading MPR: {e}", exc_info=True)
