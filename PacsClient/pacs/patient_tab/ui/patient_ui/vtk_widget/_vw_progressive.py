"""
Progressive display mixin for VTKWidget.

Manages progressive mode lifecycle (enter/exit), slice availability
tracking, in-place VTK image growth, and download overlay display.

Note: Progressive display is currently only active in FAST (PyDicom)
mode. The VTK (Advanced) mode methods (`grow_progressive_series`,
`grow_current_series_inplace`) are retained for future use but are
not called in the current production flow.
"""
from __future__ import annotations
import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

logger = logging.getLogger(__name__)


class _VWProgressiveMixin:
    """Progressive display state and growth for VTKWidget."""

    # ---- lifecycle ---------------------------------------------------

    def enter_progressive_mode(self, total_expected_slices: int, series_number: str):
        self._progressive_mode = True
        self._total_expected_slices = max(1, int(total_expected_slices))
        self._progressive_series_number = str(series_number)
        logger.info(
            "progressive: ENTER series=%s total_expected=%d available=%d",
            series_number, self._total_expected_slices, self._available_slice_count,
        )

    def exit_progressive_mode(self):
        if self._progressive_mode:
            logger.info(
                "progressive: EXIT series=%s available=%d",
                self._progressive_series_number, self._available_slice_count,
            )
        self._progressive_mode = False
        self._total_expected_slices = 0
        self._available_slice_count = 0
        self._progressive_series_number = None
        self._progressive_grow_pending = False
        self._hide_download_overlay()

    # ---- slice tracking ----------------------------------------------

    def update_available_slice_count(self, count: int):
        self._available_slice_count = max(0, int(count))
        if self._progressive_mode and self.image_viewer is not None:
            try:
                current = int(self.image_viewer.GetSlice())
                if current < self._available_slice_count:
                    self._hide_download_overlay()
            except Exception:
                pass

    def _is_slice_available(self, slice_index: int) -> bool:
        if not self._progressive_mode:
            return True
        return int(slice_index) < self._available_slice_count

    # ---- VTK-mode growth (retained for future use) -------------------

    def grow_progressive_series(self, new_vtk_image_data, new_metadata):
        """Grow the VTK image data in-place during progressive download.

        Called from ``_grow_progressive_viewer_async`` (VTK/Advanced mode).
        Currently unreachable because progressive display is disabled for
        Advanced mode, but kept correct for potential future enablement.
        """
        if self.image_viewer is None:
            return False
        try:
            grew = self.image_viewer.grow_input_image_inplace(new_vtk_image_data, new_metadata)
            if grew:
                new_dims = new_vtk_image_data.GetDimensions()
                new_z = int(new_dims[2]) if new_dims and len(new_dims) > 2 else 0
                self._available_slice_count = new_z
                logger.info(
                    "progressive: GROW series=%s available=%d/%d",
                    self._progressive_series_number, new_z, self._total_expected_slices,
                )
                if new_z >= self._total_expected_slices:
                    self.exit_progressive_mode()
                try:
                    current = int(self.image_viewer.GetSlice())
                    if current < self._available_slice_count:
                        self._hide_download_overlay()
                        self.image_viewer.Render()
                except Exception:
                    pass
                return True
        except Exception as e:
            logger.warning("progressive: grow_progressive_series failed: %s", e)
        return False

    def grow_current_series_inplace(self, new_vtk_image_data, new_metadata=None):
        """Soft-increase slice count for the current series without reset/switch.

        After a successful grow, updates the slider maximum so the user
        can scroll to newly arrived slices.  Clamps the slider value if
        it exceeds the new maximum (e.g. slices were removed or reordered).
        """
        if self.image_viewer is None:
            return False

        grown = False
        try:
            grown = self.image_viewer.grow_input_image_inplace(new_vtk_image_data, new_metadata)
            if grown:
                self._schedule_render(1)
                # Update slider maximum so user can scroll to new slices
                slider = getattr(self, "slider", None)
                if slider is not None:
                    max_slice = self.get_count_of_slices() - 1
                    if slider.maximum() != max_slice:
                        try:
                            slider.blockSignals(True)
                            slider.setMaximum(max_slice)
                        finally:
                            slider.blockSignals(False)
                        # Clamp value if it exceeds new maximum
                        if slider.value() > max_slice:
                            slider.setValue(max_slice)
        except Exception as e:
            logger.error("grow_current_series_inplace failed: %s", e)
        return grown

    # ---- download overlay --------------------------------------------

    def _show_download_overlay(self):
        if self._download_overlay_label is None:
            self._download_overlay_label = QLabel(self)
            self._download_overlay_label.setAlignment(Qt.AlignCenter)
            self._download_overlay_label.setStyleSheet(
                "QLabel {"
                "background-color: rgba(0, 0, 0, 180);"
                "color: #e5e7eb;"
                "border: 1px solid rgba(100, 100, 255, 140);"
                "border-radius: 8px;"
                "padding: 12px 24px;"
                "font-size: 13px;"
                "font-weight: 600;"
                "}"
            )
            self._download_overlay_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        avail = self._available_slice_count
        total = self._total_expected_slices
        self._download_overlay_label.setText(f"Downloading... {avail}/{total} images\nPlease wait")
        self._download_overlay_label.adjustSize()
        w = self.width()
        h = self.height()
        lw = self._download_overlay_label.sizeHint().width()
        lh = self._download_overlay_label.sizeHint().height()
        self._download_overlay_label.move((w - lw) // 2, (h - lh) // 2)
        self._download_overlay_label.raise_()
        self._download_overlay_label.show()

    def _hide_download_overlay(self):
        if self._download_overlay_label is not None:
            self._download_overlay_label.hide()
