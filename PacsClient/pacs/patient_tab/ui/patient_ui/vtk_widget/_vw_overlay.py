"""
VTK overlay mixin for VTKWidget.
overlay, clear_overlay, _update_overlay_extent.
"""
from __future__ import annotations
import logging
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap, QColor
from PySide6.QtWidgets import QLabel
import vtkmodules.all as vtk

logger = logging.getLogger(__name__)


class _VWOverlayMixin:
    """VTK image overlay: add, clear, update extent."""

    _EMPTY_DROP_HINT_HTML = (
        "<div style='text-align:center;'>"
        "<span style='font-size:15px; font-weight:600;'>Drop a series here</span><br/>"
        "<span style='font-size:11px; color:rgba(226,232,240,0.88);'>"
        "or select one from the thumbnail panel"
        "</span>"
        "</div>"
    )

    def _ensure_empty_drop_hint_label(self):
        label = getattr(self, '_empty_drop_hint_label', None)
        if label is not None:
            return label

        label = QLabel(self)
        label.setObjectName("emptyDropHint")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        label.setText(self._EMPTY_DROP_HINT_HTML)
        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        label.setStyleSheet(
            "QLabel#emptyDropHint {"
            "background-color: rgba(15, 23, 42, 145);"
            "color: #f8fafc;"
            "border: 1px dashed rgba(148, 163, 184, 170);"
            "border-radius: 12px;"
            "padding: 14px 18px;"
            "}"
        )
        label.hide()
        self._empty_drop_hint_label = label
        return label

    def _layout_empty_drop_hint_label(self):
        label = self._ensure_empty_drop_hint_label()
        available_width = max(180, int(self.width()) - 48)
        target_width = max(180, min(available_width, 340))
        label.setFixedWidth(target_width)
        label.adjustSize()

        x = max(12, (self.width() - label.width()) // 2)
        y = max(48, (self.height() - label.height()) // 2)
        label.move(x, y)

    def _should_show_empty_drop_hint(self) -> bool:
        if getattr(self, 'last_series_show', None) is not None:
            return False

        drop_overlay = getattr(self, '_drop_overlay', None)
        try:
            if drop_overlay is not None and drop_overlay.isVisible():
                return False
        except Exception:
            pass

        spinner = getattr(self, 'viewport_spinner', None)
        if spinner is not None:
            try:
                overlay = getattr(spinner, 'overlay', None)
                if overlay is not None and overlay.isVisible():
                    return False
            except Exception:
                pass
            try:
                fallback_spinner = getattr(spinner, 'spinner', None)
                if fallback_spinner is not None and fallback_spinner.isVisible():
                    return False
            except Exception:
                pass

        return True

    def _update_empty_drop_hint_visibility(self):
        try:
            label = self._ensure_empty_drop_hint_label()
            if self._should_show_empty_drop_hint():
                self._layout_empty_drop_hint_label()
                label.show()
                label.raise_()
            else:
                label.hide()
        except RuntimeError:
            pass
        except Exception:
            logger.debug("Failed to update empty drop hint visibility", exc_info=True)

    def overlay(self, vtk_image_data: vtk.vtkImageData, color=(1.0, 0.0, 0.0), opacity=0.4, is_label=True):
        """
        Overlays an image on the current image_viewer.
        - vtk_image_data: vtk.vtkImageData
        - color: (r,g,b) in [0..1]
        - opacity: overlay opacity (for non-zero pixels)
        - is_label: if True, zero becomes transparent and non-zero is colored.
        """
        if not hasattr(self, "image_viewer") or self.image_viewer is None:
            return

        self.clear_overlay()
        self._overlay = {}

        # 1) Reslice overlay to match base image
        ov_reslice = vtk.vtkImageReslice()
        ov_reslice.SetInputData(vtk_image_data)

        # # Same reslice axes matrix as the base image
        # axes = self.image_viewer.image_reslice.GetResliceAxes()
        # if axes is not None:
        #     ov_reslice.SetResliceAxes(axes)

        # Get geometry from current image (origin/spacing/extent)
        # ov_reslice.SetInformationInput(self.image_viewer.vtk_image_data)
        # ov_reslice.SetOutputOrigin(self.image_viewer.vtk_image_data.GetOrigin())

        # # Interpolation: nearest for masks, linear for normal images
        # if is_label:
        #     ov_reslice.SetInterpolationModeToNearestNeighbor()
        # else:
        #     ov_reslice.SetInterpolationModeToLinear()

        # ov_reslice.SetInterpolationModeToNearestNeighbor()
        # ov_reslice.SetInterpolationModeToLinear()

        ov_reslice.Update()
        self._overlay["reslice"] = ov_reslice

        # 2) Color/alpha mapping
        #   a) Label mask: LUT with 0 transparent, others colored/opacity
        #   b) Normal image: WL/WW could be applied; using simple LUT for now
        rng = ov_reslice.GetOutput().GetScalarRange()
        lut = vtk.vtkLookupTable()
        # Set a reasonable LUT size

        table_size = max(256, int(rng[1] - rng[0] + 1))
        lut.SetNumberOfTableValues(table_size)
        lut.Build()

        if is_label:
            # Index 0 fully transparent
            lut.SetTableValue(0, 0.0, 0.0, 0.0, 0.0)
            # Other indices with color/opacity
            for i in range(1, table_size):
                lut.SetTableValue(i, float(color[0]), float(color[1]), float(color[2]), float(opacity))
        else:
            # All values with mild opacity; WL/WW can be customized if needed
            for i in range(table_size):
                lut.SetTableValue(i, float(color[0]), float(color[1]), float(color[2]), float(opacity))

        map_colors = vtk.vtkImageMapToColors()
        map_colors.SetLookupTable(lut)
        map_colors.SetInputConnection(ov_reslice.GetOutputPort())
        map_colors.Update()
        self._overlay["map"] = map_colors

        # 3) Overlay image actor
        actor = vtk.vtkImageActor()
        actor.GetMapper().SetInputConnection(map_colors.GetOutputPort())
        actor.SetPickable(False)
        self.image_viewer.GetRenderer().AddActor(actor)
        self._overlay["actor"] = actor

        # 4) Sync extent with current slice and orientation
        self._update_overlay_extent()

        # 5) Render
        self._schedule_render(1)

    def clear_overlay(self):
        """Remove overlay from renderer and release references."""
        if hasattr(self, "_overlay") and self._overlay:
            try:
                actor = self._overlay.get("actor")
                if actor:
                    self.image_viewer.GetRenderer().RemoveActor(actor)
            except Exception:
                pass
        self._overlay = {}

    def _update_overlay_extent(self):
        """Set overlay DisplayExtent based on current slice and orientation."""
        if self._qt_bridge_active:
            return  # No VTK overlay in Qt mode
        if not hasattr(self, "_overlay") or not self._overlay:
            return
        actor = self._overlay.get("actor")
        ov_img = self._overlay.get("reslice").GetOutput()
        base_img = self.image_viewer.vtk_image_data
        if not actor or not ov_img or not base_img:
            return

        # Get dimensions and current slice from the main viewer
        slice_idx = self.image_viewer.GetSlice()
        dims = base_img.GetDimensions()
        # slice_idx = dims[2] - (slice_idx + 2)

        extent = (0, dims[0] - 1, 0, dims[1] - 1, slice_idx, slice_idx)
        # extent = (0, dims[0], 0, dims[1], slice_idx, slice_idx)

        actor.SetDisplayExtent(*extent)
