"""
Pectoral Line Picker — Manual pectoral line selection by user for 3D Cursor.

The user draws a line (2 clicks) on each view (CC and MLO) to define the
pectoral muscle boundary. The angle of this line is then used in the
correspondence arc computation instead of auto-detection.

Usage:
    picker = PectoralLinePickerController(imaging_tab)
    picker.start(callback=on_lines_picked)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Callable, List, Tuple

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMessageBox, QWidget,
)


@dataclass
class PickedPectoralLine:
    """A user-drawn pectoral line defined by two points in image pixel coordinates."""
    p1_x_px: float
    p1_y_px: float
    p2_x_px: float
    p2_y_px: float
    view_key: str  # e.g. "R_CC" or "L_MLO"
    vtk_widget: object = None

    @property
    def angle_deg(self) -> float:
        """Compute the angle of the pectoral line from vertical (degrees)."""
        dx = self.p2_x_px - self.p1_x_px
        dy = self.p2_y_px - self.p1_y_px
        # Angle from vertical (y-axis): atan2(dx, dy) in degrees
        angle = math.degrees(math.atan2(abs(dx), abs(dy)))
        return angle

    @property
    def midpoint(self) -> Tuple[float, float]:
        return ((self.p1_x_px + self.p2_x_px) / 2.0, (self.p1_y_px + self.p2_y_px) / 2.0)


class PectoralLinePickerController(QObject):
    """
    Orchestrates the pectoral line selection on CC and MLO viewers.

    Flow:
        1. User activates the pectoral line tool.
        2. Instruction panel asks user to draw line on view 1 (2 clicks).
        3. Instruction updates asking to draw line on view 2 (2 clicks).
        4. Callback fires with both pectoral lines.

    Total: 4 clicks (2 per view).
    """

    # Emitted when both pectoral lines are selected
    pectoral_lines_selected = Signal(object, object)  # (PickedPectoralLine_1, PickedPectoralLine_2)

    def __init__(self, imaging_tab, parent=None):
        super().__init__(parent)
        self._imaging_tab = imaging_tab
        self._patient_widget = getattr(imaging_tab, 'patient_widget', None)
        self._click_points: list = []  # Accumulates all clicks
        self._current_view_index = 0   # 0=first view, 1=second view
        self._click_in_view = 0        # 0=first point, 1=second point
        self._instruction_dialog: Optional[QDialog] = None
        self._callback: Optional[Callable] = None
        self._view_labels = ["", ""]
        self._viewers: list = []
        self._pectoral_line_actors = {}  # vtk_widget id -> list of actors
        self._picked_lines: List[Optional[PickedPectoralLine]] = [None, None]
        self._temp_first_point: Optional[Tuple[float, float]] = None

    def start(self, callback: Callable = None):
        """
        Begin the pectoral line picking workflow.

        Args:
            callback: Called with (PickedPectoralLine_1, PickedPectoralLine_2) when done.
        """
        self._callback = callback
        self._click_points = []
        self._current_view_index = 0
        self._click_in_view = 0
        self._picked_lines = [None, None]
        self._temp_first_point = None

        # Detect what views are loaded on the viewers
        viewers = self._get_viewer_widgets()
        if len(viewers) < 2:
            QMessageBox.warning(
                self._get_parent_widget(),
                "Pectoral Line",
                "To draw pectoral lines, both CC and MLO views must be loaded.\n"
                "Please load the CC and MLO views for the same breast."
            )
            return

        v1_info = self._get_view_info(viewers[0])
        v2_info = self._get_view_info(viewers[1])
        self._view_labels = [v1_info, v2_info]
        self._viewers = viewers

        self._show_instruction_dialog()
        self._install_click_handlers()

    def _get_parent_widget(self) -> Optional[QWidget]:
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
        dlg.setWindowTitle("Pectoral Line Selection")
        dlg.setMinimumWidth(420)

        layout = QVBoxLayout(dlg)

        # Title
        title = QLabel("<b>Pectoral Line — Step 1 of 2</b>")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 14px; margin-bottom: 8px;")
        layout.addWidget(title)
        self._title_label = title

        # Instruction
        instr = QLabel(
            f"<p style='font-size:12px;'>"
            f"Draw the <b>Pectoral Line</b> on viewer <b>{self._view_labels[0]}</b>.<br>"
            f"<b>Click the top point</b> of the pectoral muscle line, "
            f"then <b>click the bottom point</b>."
            f"</p>"
        )
        instr.setWordWrap(True)
        instr.setAlignment(Qt.AlignCenter)
        layout.addWidget(instr)
        self._instruction_label = instr

        # Status
        status = QLabel("⏳ Waiting for the first click (top of pectoral line)...")
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
            w.installEventFilter(self)

    def eventFilter(self, obj, event):
        """Intercept mouse clicks on viewer widgets."""
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                if obj in self._viewers:
                    expected = self._viewers[self._current_view_index] if self._current_view_index < len(self._viewers) else None
                    if expected is not None and obj is not expected:
                        expected_info = self._get_view_info(expected)
                        self._status_label.setText(f"⚠️ Please click on viewer {expected_info}.")
                        self._status_label.setStyleSheet("color: #FF5A5A; font-size: 11px; margin-top: 8px;")
                        return True
                    self._on_viewer_clicked(obj, event)
                    return True

        return super().eventFilter(obj, event)

    def _on_viewer_clicked(self, vtk_widget, event):
        """Handle a click — two clicks per view define the pectoral line."""
        pos = event.position() if hasattr(event, 'position') else event.pos()
        x_px = pos.x()
        y_px = pos.y()

        img_x, img_y = self._widget_to_image_coords(vtk_widget, x_px, y_px)
        view_info = self._get_view_info(vtk_widget)

        if self._click_in_view == 0:
            # First point of the line
            self._temp_first_point = (img_x, img_y)
            self._draw_point_marker(vtk_widget, img_x, img_y)
            self._click_in_view = 1
            self._status_label.setText(
                f"✅ Top point set on {view_info}.\n"
                f"Now click the <b>bottom point</b> of the pectoral line."
            )
            self._status_label.setStyleSheet("color: #00BFFF; font-size: 11px; margin-top: 8px;")
            print(f"[3D-Cursor][PECTORAL-PICK] First point on {view_info}: ({img_x:.1f}, {img_y:.1f})")

        elif self._click_in_view == 1:
            # Second point — line complete for this view
            p1 = self._temp_first_point
            picked = PickedPectoralLine(
                p1_x_px=p1[0], p1_y_px=p1[1],
                p2_x_px=img_x, p2_y_px=img_y,
                view_key=view_info,
                vtk_widget=vtk_widget,
            )
            self._picked_lines[self._current_view_index] = picked

            # Draw the full line on the viewer
            self._draw_pectoral_line(vtk_widget, p1[0], p1[1], img_x, img_y)

            print(f"[3D-Cursor][PECTORAL-PICK] Line on {view_info}: "
                  f"({p1[0]:.1f},{p1[1]:.1f})->({img_x:.1f},{img_y:.1f}) "
                  f"angle={picked.angle_deg:.1f}°")

            # Move to next view or finish
            self._current_view_index += 1
            self._click_in_view = 0
            self._temp_first_point = None

            if self._current_view_index == 1:
                # First view done, ask for second
                self._title_label.setText("<b>Pectoral Line — Step 2 of 2</b>")
                self._instruction_label.setText(
                    f"<p style='font-size:12px;'>"
                    f"✅ Pectoral line set on {view_info} (angle: {picked.angle_deg:.1f}°)<br><br>"
                    f"Now draw the <b>Pectoral Line</b> on viewer <b>{self._view_labels[1]}</b>.<br>"
                    f"<b>Click the top point</b>, then <b>click the bottom point</b>."
                    f"</p>"
                )
                self._status_label.setText("⏳ Waiting for first click on second view...")
                self._status_label.setStyleSheet("color: #FFA500; font-size: 11px; margin-top: 8px;")
            elif self._current_view_index >= 2:
                # Both done
                self._finish()

    def _widget_to_image_coords(self, vtk_widget, wx, wy) -> tuple:
        """Convert widget coords to image pixel coords (shared high-accuracy utility)."""
        from .coord_utils import widget_to_image_coords
        return widget_to_image_coords(vtk_widget, wx, wy)

    def _draw_point_marker(self, vtk_widget, img_x: float, img_y: float):
        """Draw a green marker at a pectoral line endpoint."""
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

            p_world = ijk_to_world(float(img_x), float(img_y), None, y_flip=True)

            marker = _vtk.vtkSphereSource()
            marker.SetCenter(p_world)
            marker.SetRadius(2.5)
            marker.SetPhiResolution(12)
            marker.SetThetaResolution(12)
            marker.Update()

            mapper = _vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(marker.GetOutputPort())

            actor = _vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(0.3, 1.0, 0.3)  # green
            actor.GetProperty().SetOpacity(0.9)
            renderer.AddActor(actor)

            wid = id(vtk_widget)
            if wid not in self._pectoral_line_actors:
                self._pectoral_line_actors[wid] = []
            self._pectoral_line_actors[wid].append(actor)

            # Also store on widget for cleanup on series switch
            if not hasattr(vtk_widget, '_pectoral_line_actors'):
                vtk_widget._pectoral_line_actors = []
            vtk_widget._pectoral_line_actors.append(actor)

            rw = getattr(image_viewer, 'image_render_window', None) or \
                 getattr(image_viewer, 'GetRenderWindow', lambda: None)()
            if rw:
                rw.Render()
        except Exception as e:
            print(f"[3D-Cursor][PECTORAL-PICK] marker draw failed: {e}")

    def _draw_pectoral_line(self, vtk_widget, x1: float, y1: float, x2: float, y2: float):
        """Draw the pectoral line (green dashed) on the viewer."""
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

            p1_world = ijk_to_world(float(x1), float(y1), None, y_flip=True)
            p2_world = ijk_to_world(float(x2), float(y2), None, y_flip=True)

            line_source = _vtk.vtkLineSource()
            line_source.SetPoint1(p1_world)
            line_source.SetPoint2(p2_world)
            line_source.SetResolution(20)
            line_source.Update()

            mapper = _vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(line_source.GetOutputPort())

            actor = _vtk.vtkActor()
            actor.SetMapper(mapper)
            prop = actor.GetProperty()
            prop.SetColor(0.3, 1.0, 0.5)  # green
            prop.SetLineWidth(2.5)
            prop.SetLineStipplePattern(0xF0F0)
            prop.SetLineStippleRepeatFactor(1)
            prop.SetOpacity(0.9)
            renderer.AddActor(actor)

            # Endpoint markers
            for p_world in [p1_world, p2_world]:
                sphere = _vtk.vtkSphereSource()
                sphere.SetCenter(p_world)
                sphere.SetRadius(2.5)
                sphere.SetPhiResolution(12)
                sphere.SetThetaResolution(12)
                sphere.Update()

                sm = _vtk.vtkPolyDataMapper()
                sm.SetInputConnection(sphere.GetOutputPort())

                sa = _vtk.vtkActor()
                sa.SetMapper(sm)
                sa.GetProperty().SetColor(0.3, 1.0, 0.5)
                sa.GetProperty().SetOpacity(0.9)
                renderer.AddActor(sa)

                wid = id(vtk_widget)
                if wid not in self._pectoral_line_actors:
                    self._pectoral_line_actors[wid] = []
                self._pectoral_line_actors[wid].append(sa)

                if not hasattr(vtk_widget, '_pectoral_line_actors'):
                    vtk_widget._pectoral_line_actors = []
                vtk_widget._pectoral_line_actors.append(sa)

            wid = id(vtk_widget)
            if wid not in self._pectoral_line_actors:
                self._pectoral_line_actors[wid] = []
            self._pectoral_line_actors[wid].append(actor)

            if not hasattr(vtk_widget, '_pectoral_line_actors'):
                vtk_widget._pectoral_line_actors = []
            vtk_widget._pectoral_line_actors.append(actor)

            rw = getattr(image_viewer, 'image_render_window', None) or \
                 getattr(image_viewer, 'GetRenderWindow', lambda: None)()
            if rw:
                rw.Render()
        except Exception as e:
            print(f"[3D-Cursor][PECTORAL-PICK] line draw failed: {e}")

    def _finish(self):
        """Both pectoral lines drawn — clean up and fire callback."""
        self._remove_click_handlers()

        if self._instruction_dialog:
            self._instruction_dialog.close()
            self._instruction_dialog = None

        line1 = self._picked_lines[0]
        line2 = self._picked_lines[1]

        if self._callback and line1 and line2:
            self._callback(line1, line2)

        self.pectoral_lines_selected.emit(line1, line2)

    def _cancel(self):
        """User cancelled the picking."""
        self._remove_click_handlers()

        if self._instruction_dialog:
            self._instruction_dialog.close()
            self._instruction_dialog = None

        self._clear_line_markers()
        self._picked_lines = [None, None]

    def _remove_click_handlers(self):
        """Remove event filters from viewer widgets."""
        for w in getattr(self, '_viewers', []):
            try:
                w.removeEventFilter(self)
            except Exception:
                pass

    def _clear_line_markers(self):
        """Remove pectoral line markers from all viewers."""
        for w in getattr(self, '_viewers', []):
            try:
                iv = getattr(w, 'image_viewer', None)
                renderer = getattr(iv, 'renderer', None) if iv else None
                actors = self._pectoral_line_actors.get(id(w), [])
                if renderer:
                    for a in actors:
                        try:
                            renderer.RemoveActor(a)
                        except Exception:
                            pass
                    rw = getattr(iv, 'image_render_window', None) or \
                         getattr(iv, 'GetRenderWindow', lambda: None)()
                    if rw:
                        rw.Render()
            except Exception:
                pass
        self._pectoral_line_actors = {}
