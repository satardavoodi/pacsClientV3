"""
Nipple Picker — Manual nipple point selection by user for 3D Cursor.

Instead of auto-detecting the nipple (unreliable in MLO), this module lets the
user click the nipple position on each view (CC and MLO). A small dialog shows
instructions and collects the two clicks before running the correlation.

Usage:
    picker = NipplePickerController(imaging_tab)
    picker.start()  # begins the interactive picking flow
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Callable

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMessageBox, QWidget,
)


@dataclass
class PickedNipple:
    """A user-selected nipple position in pixel coordinates."""
    x_px: float
    y_px: float
    view_key: str  # e.g. "R_CC" or "L_MLO"
    vtk_widget: object = None


class NipplePickerController(QObject):
    """
    Orchestrates the two-click nipple selection on CC and MLO viewers.

    Flow:
        1. User clicks "3D Cursor" button
        2. A floating instruction panel appears asking to click nipple on view 1
        3. User clicks on viewer → position captured
        4. Instruction updates asking to click nipple on view 2
        5. User clicks on viewer → position captured
        6. Callback fires with both positions → correlation runs
    """

    # Emitted when both nipple points are selected
    nipples_selected = Signal(object, object)  # (PickedNipple_cc, PickedNipple_mlo)

    def __init__(self, imaging_tab, parent=None):
        super().__init__(parent)
        self._imaging_tab = imaging_tab
        self._patient_widget = getattr(imaging_tab, 'patient_widget', None)
        self._picked_points: list = []
        self._active_pick_index = 0  # 0=first view, 1=second view
        self._instruction_dialog: Optional[QDialog] = None
        self._callback: Optional[Callable] = None
        self._view_labels = ["", ""]  # Will be filled with actual view info
        self._viewers = []
        self._manual_nipple_actors = {}

    def start(self, callback: Callable = None):
        """
        Begin the nipple picking workflow.

        Args:
            callback: Called with (PickedNipple_1, PickedNipple_2) when both picks are done.
        """
        self._callback = callback
        self._picked_points = []
        self._active_pick_index = 0

        # Detect what views are loaded on the viewers
        viewers = self._get_viewer_widgets()
        if len(viewers) < 2:
            QMessageBox.warning(
                self._get_parent_widget(),
                "3D Cursor",
                "برای استفاده از 3D Cursor باید هر دو ویو CC و MLO بارگذاری شده باشند.\n"
                "لطفاً CC و MLO یک طرف (R یا L) را روی دو ویویر بارگذاری کنید."
            )
            return

        # Determine view labels
        v1_info = self._get_view_info(viewers[0])
        v2_info = self._get_view_info(viewers[1])
        self._view_labels = [v1_info, v2_info]
        self._viewers = viewers

        # Show instruction dialog
        self._show_instruction_dialog()

        # Install click interceptors on both viewers
        self._install_click_handlers()

    def _get_parent_widget(self) -> QWidget:
        pw = self._patient_widget
        if pw and hasattr(pw, 'window'):
            try:
                return pw.window()
            except Exception:
                pass
        tab = self._imaging_tab
        if tab and isinstance(tab, QWidget):
            return tab
        return None

    def _get_viewer_widgets(self) -> list:
        """Get the VTK widgets from the viewer nodes."""
        widgets = []
        pw = self._patient_widget
        if not pw:
            return widgets

        nodes = getattr(pw, 'lst_nodes_viewer', None) or []
        for node in nodes[:2]:
            w = getattr(node, 'vtk_widget', None)
            if w is not None:
                widgets.append(w)
        return widgets

    def _get_view_info(self, vtk_widget) -> str:
        """Get a display string like 'R-CC' for a viewer widget."""
        try:
            iv = getattr(vtk_widget, 'image_viewer', None)
            if iv:
                meta = getattr(iv, 'metadata', {}) or {}
                series_meta = meta.get('series', {})
                lat = str(series_meta.get('laterality', '') or '').upper()
                vp = str(series_meta.get('view_position', '') or '').upper()
                if lat and vp:
                    return f"{lat}-{vp}"
        except Exception:
            pass
        return "View"

    def _show_instruction_dialog(self):
        """Show the floating instruction panel."""
        parent = self._get_parent_widget()
        dlg = QDialog(parent, Qt.Tool | Qt.WindowStaysOnTopHint)
        dlg.setWindowTitle("3D Cursor - Select Nipple Points")
        dlg.setMinimumWidth(380)

        layout = QVBoxLayout(dlg)

        # Title
        title = QLabel("<b>Step 1 of 2</b>")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 14px; margin-bottom: 8px;")
        layout.addWidget(title)
        self._title_label = title

        # Instruction
        instr = QLabel(
            f"<p style='font-size:12px;'>"
            f"Please click the <b>Nipple</b> point in viewer <b>{self._view_labels[0]}</b>."
            f"</p>"
        )
        instr.setWordWrap(True)
        instr.setAlignment(Qt.AlignCenter)
        layout.addWidget(instr)
        self._instruction_label = instr

        # Status
        status = QLabel("⏳ Waiting for the first point...")
        status.setAlignment(Qt.AlignCenter)
        status.setStyleSheet("color: #FFA500; font-size: 11px; margin-top: 8px;")
        layout.addWidget(status)
        self._status_label = status

        # Cancel button
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self._cancel)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        dlg.setLayout(layout)
        dlg.show()
        self._instruction_dialog = dlg

    def _install_click_handlers(self):
        """Install mouse press event interceptors on viewer widgets."""
        for w in self._viewers:
            # Use eventFilter instead of overriding mousePressEvent
            w.installEventFilter(self)

    def eventFilter(self, obj, event):
        """Intercept mouse clicks on viewer widgets."""
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                # Check if this is one of our tracked viewers
                if obj in self._viewers:
                    expected = self._viewers[self._active_pick_index] if self._active_pick_index < len(self._viewers) else None
                    if expected is not None and obj is not expected:
                        expected_info = self._get_view_info(expected)
                        self._status_label.setText(f"⚠️ Please click viewer {expected_info} in this step.")
                        self._status_label.setStyleSheet("color: #FF5A5A; font-size: 11px; margin-top: 8px;")
                        return True
                    self._on_viewer_clicked(obj, event)
                    return True  # consume the event

        return super().eventFilter(obj, event)

    def _on_viewer_clicked(self, vtk_widget, event):
        """Handle a click on a viewer widget — record nipple position."""
        # Get click position in widget coordinates
        pos = event.position() if hasattr(event, 'position') else event.pos()
        x_px = pos.x()
        y_px = pos.y()

        # Convert widget coordinates to image pixel coordinates
        img_x, img_y = self._widget_to_image_coords(vtk_widget, x_px, y_px)

        view_info = self._get_view_info(vtk_widget)
        picked = PickedNipple(
            x_px=img_x,
            y_px=img_y,
            view_key=view_info,
            vtk_widget=vtk_widget,
        )

        self._picked_points.append(picked)
        self._active_pick_index += 1

        # Draw immediate red marker so user can verify the selected origin point.
        self._draw_manual_nipple_marker(vtk_widget, img_x, img_y)

        print(f"[3D-Cursor][NIPPLE-PICK] User picked nipple on {view_info}: "
              f"widget=({x_px:.0f}, {y_px:.0f}) -> image=({img_x:.1f}, {img_y:.1f})")

        if self._active_pick_index == 1:
            # First pick done, ask for second
            self._title_label.setText("<b>Step 2 of 2</b>")
            self._instruction_label.setText(
                f"<p style='font-size:12px;'>"
                f"✅ First point saved ({view_info})<br><br>"
                f"Now click the <b>Nipple</b> point in viewer <b>{self._view_labels[1]}</b>."
                f"</p>"
            )
            self._status_label.setText("⏳ First point saved. Waiting for the second point...")
            self._status_label.setStyleSheet("color: #00BFFF; font-size: 11px; margin-top: 8px;")
        elif self._active_pick_index >= 2:
            # Both picks done
            self._finish()

    def _widget_to_image_coords(self, vtk_widget, wx, wy) -> tuple:
        """
        Convert widget (screen) coordinates to DICOM image pixel coordinates.

        For VTK viewers, uses the renderer coordinate system.
        Falls back to proportional mapping if VTK conversion fails.
        """
        try:
            import vtk as _vtk

            iv = getattr(vtk_widget, 'image_viewer', None)
            if iv is None:
                raise ValueError("No image_viewer")

            renderer = getattr(iv, 'renderer', None)
            world_to_ijk = getattr(iv, 'world_to_ijk', None)
            if renderer is not None and callable(world_to_ijk):
                widget_h = float(max(1, vtk_widget.height()))

                # Reliable VTK picking path used by other tools: display -> world -> ijk.
                picker = _vtk.vtkWorldPointPicker()
                ok = picker.Pick(float(wx), float(widget_h - wy), 0.0, renderer)
                if ok:
                    w_pt = picker.GetPickPosition()
                    i, j, _k = world_to_ijk(
                        xw=w_pt[0],
                        yw=w_pt[1],
                        zw=w_pt[2],
                        y_flip=True,
                    )

                    meta = getattr(iv, 'metadata', {}) or {}
                    instances = meta.get('instances', [])
                    inst = instances[0] if isinstance(instances, list) and instances else {}
                    rows = int(inst.get('rows', 0) or 0)
                    cols = int(inst.get('columns', 0) or 0)

                    img_x = float(i)
                    img_y = float(j)
                    if cols > 0 and rows > 0:
                        img_x = max(0.0, min(img_x, float(cols - 1)))
                        img_y = max(0.0, min(img_y, float(rows - 1)))

                    return (img_x, img_y)
        except Exception as e:
            print(f"[3D-Cursor][NIPPLE-PICK] VTK coord conversion failed: {e}")

        # Fallback: proportional mapping
        try:
            iv = getattr(vtk_widget, 'image_viewer', None)
            meta = getattr(iv, 'metadata', {}) or {}
            instances = meta.get('instances', [])
            inst = instances[0] if instances else {}
            img_w = inst.get('columns', 0) or 0
            img_h = inst.get('rows', 0) or 0

            if img_w > 0 and img_h > 0:
                widget_w = vtk_widget.width()
                widget_h = vtk_widget.height()
                img_x = (wx / widget_w) * img_w
                img_y = (wy / widget_h) * img_h
                return (img_x, img_y)
        except Exception:
            pass

        # Last resort: raw widget coords
        return (float(wx), float(wy))

    def _draw_manual_nipple_marker(self, vtk_widget, img_x: float, img_y: float):
        """Draw a red marker at the user-selected nipple point."""
        try:
            import vtk as _vtk
        except Exception:
            return

        try:
            image_viewer = getattr(vtk_widget, 'image_viewer', None)
            if image_viewer is None:
                return
            renderer = getattr(image_viewer, 'renderer', None)
            ijk_to_world = getattr(image_viewer, 'ijk_to_world', None)
            if renderer is None or not callable(ijk_to_world):
                return

            # Clear previous marker for this viewer
            old_actor = self._manual_nipple_actors.get(id(vtk_widget))
            if old_actor is not None:
                try:
                    renderer.RemoveActor(old_actor)
                except Exception:
                    pass

            p_world = ijk_to_world(float(img_x), float(img_y), None, y_flip=True)

            marker = _vtk.vtkSphereSource()
            marker.SetCenter(p_world)
            marker.SetRadius(3.0)
            marker.SetPhiResolution(14)
            marker.SetThetaResolution(14)
            marker.Update()

            mapper = _vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(marker.GetOutputPort())

            actor = _vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(1.0, 0.0, 0.0)  # red
            actor.GetProperty().SetOpacity(0.95)
            renderer.AddActor(actor)

            self._manual_nipple_actors[id(vtk_widget)] = actor

            rw = getattr(image_viewer, 'image_render_window', None) or \
                 getattr(image_viewer, 'GetRenderWindow', lambda: None)()
            if rw is not None:
                rw.Render()
        except Exception as e:
            print(f"[3D-Cursor][NIPPLE-PICK] marker draw failed: {e}")

    def _finish(self):
        """Both nipple points selected — clean up and fire callback."""
        self._remove_click_handlers()

        if self._instruction_dialog:
            self._instruction_dialog.close()
            self._instruction_dialog = None

        if self._callback and len(self._picked_points) >= 2:
            self._callback(self._picked_points[0], self._picked_points[1])

        self.nipples_selected.emit(
            self._picked_points[0] if len(self._picked_points) > 0 else None,
            self._picked_points[1] if len(self._picked_points) > 1 else None,
        )

    def _cancel(self):
        """User cancelled the picking."""
        self._remove_click_handlers()

        if self._instruction_dialog:
            self._instruction_dialog.close()
            self._instruction_dialog = None

        self._clear_manual_markers()
        self._picked_points = []

    def _remove_click_handlers(self):
        """Remove event filters from viewer widgets."""
        for w in getattr(self, '_viewers', []):
            try:
                w.removeEventFilter(self)
            except Exception:
                pass

    def _clear_manual_markers(self):
        """Remove manual nipple markers from all viewers."""
        for w in getattr(self, '_viewers', []):
            try:
                iv = getattr(w, 'image_viewer', None)
                renderer = getattr(iv, 'renderer', None) if iv is not None else None
                actor = self._manual_nipple_actors.get(id(w))
                if renderer is not None and actor is not None:
                    renderer.RemoveActor(actor)
                    rw = getattr(iv, 'image_render_window', None) or \
                         getattr(iv, 'GetRenderWindow', lambda: None)()
                    if rw is not None:
                        rw.Render()
            except Exception:
                pass
        self._manual_nipple_actors = {}
