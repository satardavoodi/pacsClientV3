"""
3D Cursor — guided picker (Qt shell over the pure `Cursor3DFlow` state machine).

ONE panel drives the whole workflow. At any moment it shows:
    • the current step ("Step 2 of 3") and a progress bar
    • the checklist of ALL steps with state (✓ done · ▶ current · ○ pending)
    • which VIEW must be clicked (e.g. "R-MLO — left viewer")
    • which TOOL is active ("Nipple marker · 1 click")
    • what to do next, and why the value is needed
    • Back (undo the last action) / Cancel

Clicking the wrong viewer does not corrupt the flow — it is rejected with an
inline warning naming the view the user must click.

The picked results are returned as the SAME dataclasses the legacy pickers
produce (`PickedNipple`, `PickedPectoralLine`), so the downstream correlation
path is unchanged.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QObject, QEvent, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QProgressBar, QMessageBox, QWidget,
)

from .guided_workflow import Cursor3DFlow, Cursor3DStep, ViewSlot, plan_cursor3d_steps
from .nipple_picker import PickedNipple
from .pectoral_picker import PickedPectoralLine
from . import overlay_draw


class Cursor3DWizardPanel(QDialog):
    """Always-on-top instruction panel: step, view, tool, checklist, next action."""

    back_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, steps: List[Cursor3DStep], parent=None):
        super().__init__(parent, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("3D Cursor — Guided Setup")
        self.setMinimumWidth(430)

        root = QVBoxLayout(self)
        root.setSpacing(8)

        self._header = QLabel()
        self._header.setAlignment(Qt.AlignCenter)
        self._header.setStyleSheet("font-size: 15px; font-weight: bold; color: #89b4fa;")
        root.addWidget(self._header)

        self._progress = QProgressBar()
        self._progress.setMaximum(max(1, len(steps)))
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        root.addWidget(self._progress)

        # ---- checklist (all steps, with state) ----
        self._checklist_labels: List[QLabel] = []
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(4)
        box_layout.setContentsMargins(10, 8, 10, 8)
        for _ in steps:
            lbl = QLabel()
            lbl.setWordWrap(True)
            box_layout.addWidget(lbl)
            self._checklist_labels.append(lbl)
        root.addWidget(box)

        # ---- current action ----
        self._view_label = QLabel()
        self._view_label.setWordWrap(True)
        self._view_label.setStyleSheet("font-size: 12px; color: #f9e2af;")
        root.addWidget(self._view_label)

        self._tool_label = QLabel()
        self._tool_label.setWordWrap(True)
        self._tool_label.setStyleSheet("font-size: 12px; color: #a6e3a1;")
        root.addWidget(self._tool_label)

        self._instruction = QLabel()
        self._instruction.setWordWrap(True)
        self._instruction.setStyleSheet("font-size: 13px; margin-top: 4px;")
        root.addWidget(self._instruction)

        self._why = QLabel()
        self._why.setWordWrap(True)
        self._why.setStyleSheet("font-size: 10px; color: #9399b2; font-style: italic;")
        root.addWidget(self._why)

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("font-size: 11px; color: #FFA500; margin-top: 6px;")
        root.addWidget(self._status)

        # ---- buttons ----
        btns = QHBoxLayout()
        self._back_btn = QPushButton("↩ Back")
        self._back_btn.clicked.connect(self.back_requested.emit)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.cancel_requested.emit)
        btns.addWidget(self._back_btn)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        root.addLayout(btns)

    # -- rendering -----------------------------------------------------------
    def render_flow(self, flow: Cursor3DFlow, status: str = "", warn: bool = False) -> None:
        self._header.setText(flow.progress_text())
        self._progress.setValue(flow.current_index)

        for i, step in enumerate(flow.steps):
            state = flow.step_state(i)
            if state == "done":
                self._checklist_labels[i].setText(
                    f"<span style='color:#a6e3a1;'>✓ {step.title}</span>"
                )
            elif state == "current":
                self._checklist_labels[i].setText(
                    f"<b style='color:#f9e2af;'>▶ {step.title}</b>"
                )
            else:
                self._checklist_labels[i].setText(
                    f"<span style='color:#6c7086;'>○ {step.title}</span>"
                )

        step = flow.current_step
        if step is None:
            self._view_label.setText("")
            self._tool_label.setText("")
            self._instruction.setText("<b>All steps complete — running the correlation…</b>")
            self._why.setText("")
            self._status.setText("")
            self._back_btn.setEnabled(False)
            return

        side = "left" if step.viewer_index == 0 else "right"
        self._view_label.setText(f"👁 View to click: <b>{step.view_label}</b> ({side} viewer)")
        self._tool_label.setText(f"🛠 Active tool: <b>{step.tool}</b>")
        self._instruction.setText(step.instruction)
        self._why.setText(step.why)
        self._back_btn.setEnabled(flow.current_index > 0 or bool(flow.points_for(step.key)))

        if status:
            self._status.setText(status)
            self._status.setStyleSheet(
                "font-size: 11px; color: %s; margin-top: 6px;" % ("#FF5A5A" if warn else "#89dceb")
            )
        else:
            remaining = flow.clicks_remaining()
            self._status.setText(
                f"⏳ Waiting for {remaining} click{'s' if remaining != 1 else ''}…"
            )
            self._status.setStyleSheet("font-size: 11px; color: #FFA500; margin-top: 6px;")


class Cursor3DGuidedPicker(QObject):
    """Drives the whole 3D-Cursor setup: nipple (MLO) → nipple (CC) → pectoral (MLO)."""

    finished = Signal(object, object, object, object)  # (nipple_mlo, nipple_cc, pectoral_mlo, pectoral_cc)

    def __init__(self, imaging_tab, parent=None):
        super().__init__(parent)
        self._imaging_tab = imaging_tab
        self._patient_widget = getattr(imaging_tab, 'patient_widget', None)
        self._viewers: List[object] = []
        self._flow: Optional[Cursor3DFlow] = None
        self._panel: Optional[Cursor3DWizardPanel] = None
        self._callback: Optional[Callable] = None
        self._actors_by_step: Dict[str, list] = {}

    # -- public --------------------------------------------------------------
    def can_start(self) -> bool:
        """True when the two loaded views can be identified as CC + MLO."""
        return plan_cursor3d_steps(self._build_slots()) is not None

    def start(self, callback: Callable = None) -> bool:
        self._callback = callback
        viewers = self._get_viewer_widgets()
        if len(viewers) < 2:
            QMessageBox.warning(
                self._parent_widget(), "3D Cursor",
                "To use the 3D Cursor, both CC and MLO views must be loaded.\n"
                "Please load the CC and the MLO view of the same breast into the two viewers."
            )
            return False

        self._viewers = viewers
        slots = self._build_slots()
        steps = plan_cursor3d_steps(slots)
        if steps is None:
            # Do not guess which view is which — a nipple clicked in the wrong view
            # silently corrupts the correlation. Log WHY, then fall back to legacy.
            detail = ", ".join(
                f"viewer{s.viewer_index + 1}={s.laterality or '?'}-{s.view_position or '?'}"
                for s in slots
            )
            print(f"[3D-Cursor][GUIDED] cannot identify CC/MLO ({detail}) — falling back to legacy flow")
            return False

        self._flow = Cursor3DFlow(steps=steps)
        self._actors_by_step = {}

        self._panel = Cursor3DWizardPanel(steps, parent=self._parent_widget())
        self._panel.back_requested.connect(self._on_back)
        self._panel.cancel_requested.connect(self.cancel)
        self._panel.render_flow(self._flow)
        self._panel.show()

        for w in self._viewers:
            w.installEventFilter(self)

        print(f"[3D-Cursor][GUIDED] flow started: {[s.key for s in steps]}")
        return True

    def cancel(self) -> None:
        self._teardown(clear_overlays=True)

    # -- flow ----------------------------------------------------------------
    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if obj in self._viewers and self._flow is not None:
                self._handle_click(obj, event)
                return True  # consume — the viewer must not pan/window-level here
        return super().eventFilter(obj, event)

    def _handle_click(self, vtk_widget, event) -> None:
        flow = self._flow
        if flow is None or flow.is_complete:
            return

        viewer_index = self._viewers.index(vtk_widget)
        pos = event.position() if hasattr(event, 'position') else event.pos()
        img_x, img_y = self._widget_to_image_coords(vtk_widget, pos.x(), pos.y())

        evt = flow.click(viewer_index, img_x, img_y)
        status = evt.get("status")

        if status == "wrong_view":
            self._panel.render_flow(
                flow,
                status=f"⚠️ Wrong viewer — click the <b>{evt['expected_view']}</b> view for this step.",
                warn=True,
            )
            return

        step: Cursor3DStep = evt["step"]
        print(f"[3D-Cursor][GUIDED] {step.key}: click -> ({img_x:.1f}, {img_y:.1f}) [{status}]")

        if status == "need_more_clicks":
            # first point of the pectoral line — mark it while we wait for the 2nd
            actor = overlay_draw.draw_point_marker(
                vtk_widget, img_x, img_y, color=overlay_draw.COLOR_PENDING, radius=2.5)
            self._actors_by_step.setdefault(step.key, []).append(actor)
            self._panel.render_flow(
                flow,
                status="✅ Upper point set — now click the <b>lower (inferior)</b> end.",
            )
            return

        # step complete → draw its final overlay
        pts = evt["points"]
        if step.kind == "point":
            actor = overlay_draw.draw_point_marker(
                vtk_widget, pts[0][0], pts[0][1], color=overlay_draw.COLOR_NIPPLE)
            self._actors_by_step.setdefault(step.key, []).append(actor)
        else:
            actors = overlay_draw.draw_line(
                vtk_widget, pts[0], pts[1], color=overlay_draw.COLOR_PECTORAL)
            self._actors_by_step.setdefault(step.key, []).extend(actors)

        if status == "flow_done":
            self._finish()
        else:
            self._panel.render_flow(flow, status=f"✅ {step.title} — done.")

    def _on_back(self) -> None:
        flow = self._flow
        if flow is None:
            return
        step = flow.back()
        if step is None:
            return
        self._erase_step_overlay(step)
        self._panel.render_flow(flow, status=f"↩ Undone: {step.title}")
        print(f"[3D-Cursor][GUIDED] back -> {step.key}")

    def _erase_step_overlay(self, step: Cursor3DStep) -> None:
        actors = self._actors_by_step.pop(step.key, [])
        actors = [a for a in actors if a is not None]
        if not actors:
            return
        vtk_widget = self._viewers[step.viewer_index] if step.viewer_index < len(self._viewers) else None
        if vtk_widget is not None:
            overlay_draw.remove_actors(vtk_widget, actors)

    def _finish(self) -> None:
        flow = self._flow
        steps_by_key = {s.key: s for s in flow.steps}

        def _picked_nipple(key: str) -> Optional[PickedNipple]:
            step = steps_by_key.get(key)
            pts = flow.points_for(key)
            if step is None or not pts:
                return None
            return PickedNipple(
                x_px=pts[0][0], y_px=pts[0][1],
                view_key=step.view_label,
                vtk_widget=self._viewers[step.viewer_index],
            )

        def _picked_line(key: str) -> Optional[PickedPectoralLine]:
            step = steps_by_key.get(key)
            pts = flow.points_for(key)
            if step is None or len(pts) < 2:
                return None
            return PickedPectoralLine(
                p1_x_px=pts[0][0], p1_y_px=pts[0][1],
                p2_x_px=pts[1][0], p2_y_px=pts[1][1],
                view_key=step.view_label,
                vtk_widget=self._viewers[step.viewer_index],
            )

        nipple_mlo = _picked_nipple("nipple_mlo")
        nipple_cc = _picked_nipple("nipple_cc")
        pectoral_mlo = _picked_line("pectoral_mlo")
        pectoral_cc = _picked_line("pectoral_cc")

        self._panel.render_flow(flow)
        self._teardown(clear_overlays=False)

        if pectoral_mlo is not None:
            print(f"[3D-Cursor][GUIDED] complete — MLO pectoral angle = {pectoral_mlo.angle_deg:.1f}°"
                  + (f", CC chest-wall line drawn" if pectoral_cc is not None else ", CC line MISSING"))

        if self._callback:
            self._callback(nipple_mlo, nipple_cc, pectoral_mlo, pectoral_cc)
        self.finished.emit(nipple_mlo, nipple_cc, pectoral_mlo, pectoral_cc)

    # -- helpers -------------------------------------------------------------
    def _teardown(self, *, clear_overlays: bool) -> None:
        for w in self._viewers:
            try:
                w.removeEventFilter(self)
            except Exception:
                pass
        if clear_overlays and self._flow is not None:
            for step in self._flow.steps:
                self._erase_step_overlay(step)
        if self._panel is not None:
            try:
                self._panel.close()
            except RuntimeError:
                pass
            self._panel = None

    def _parent_widget(self) -> Optional[QWidget]:
        pw = self._patient_widget
        if pw is not None and hasattr(pw, 'window'):
            try:
                return pw.window()
            except Exception:
                pass
        tab = self._imaging_tab
        return tab if isinstance(tab, QWidget) else None

    def _get_viewer_widgets(self) -> list:
        widgets = []
        pw = self._patient_widget
        if not pw:
            return widgets
        for node in (getattr(pw, 'lst_nodes_viewer', None) or [])[:2]:
            w = getattr(node, 'vtk_widget', None)
            if w is not None:
                widgets.append(w)
        return widgets

    def _build_slots(self) -> List[ViewSlot]:
        """Identify each loaded viewer via the SHARED resolver.

        Reading only `metadata['series']['view_position']` is not enough — on real
        studies those keys are empty and the view lives in the DICOM header (this is
        why the legacy dialog said "viewer View" and the guided flow fell back).
        `resolve_view_identity` walks metadata → DICOM header → description.
        """
        from .view_identity import resolve_view_identity

        viewers = self._viewers or self._get_viewer_widgets()
        slots: List[ViewSlot] = []
        for i, w in enumerate(viewers):
            lat, vp = resolve_view_identity(w)
            slots.append(ViewSlot(viewer_index=i, laterality=lat, view_position=vp))
        return slots

    def _widget_to_image_coords(self, vtk_widget, wx, wy) -> tuple:
        from .coord_utils import widget_to_image_coords
        return widget_to_image_coords(vtk_widget, wx, wy)
