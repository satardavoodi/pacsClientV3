"""Settings → Viewer Configuration → Hardware Requirements Check (OPT-21).

Shows whether this computer meets the requirements for the viewer and 3D/MPR
rendering (OpenGL/GPU driver, CPU, RAM, free disk) and lets the user run the
check on demand. The result is PERSISTED (``hardware_check.json``) and reused
by the MPR OpenGL pre-flight gate, so the check runs once per install — never
on every MPR click (user directive 2026-07-07).

Backed by ``modules/mpr/opengl_preflight.py`` (``run_hardware_check`` /
``load_persisted_check``). Purely additive UI — no existing settings behavior
is touched. Guard pins live in tests/code/viewer/test_mpr_opengl_preflight.py.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

_STATUS_ICON = {"ok": "✅", "warning": "⚠️", "fail": "❌"}
_STATUS_COLOR = {"ok": "#34d399", "warning": "#fbbf24", "fail": "#f87171"}
_OVERALL_TEXT = {
    "ok": "This computer meets the requirements.",
    "warning": "This computer works, but is below the recommended specification.",
    "fail": "This computer does NOT meet a requirement — 3D/MPR may be unavailable.",
}


class HardwareCheckPanelWidget(QWidget):
    """'Hardware Requirements Check' section for the Viewer Configuration page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(10)

        title = QLabel("Hardware Requirements Check")
        title.setStyleSheet("font-weight: 600; font-size: 14px; color: #f9fafb;")
        root.addWidget(title)

        desc = QLabel(
            "Evaluates whether this computer can run the viewer and 3D/MPR rendering "
            "(GPU driver / OpenGL 3.2+, CPU, RAM, free disk). The result is saved and "
            "checked once per installation — it is not re-tested on every MPR open. "
            "Re-run after a graphics-driver update or hardware change."
        )
        desc.setWordWrap(True)
        desc.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        desc.setStyleSheet(
            "color: #d1d5db; font-size: 13px; padding: 9px; "
            "background-color: #1f2937; border-radius: 4px; line-height: 1.5;"
        )
        root.addWidget(desc)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "font-size: 13px; font-weight: 600; padding: 2px 2px; color: #d1d5db;"
        )
        root.addWidget(self.summary_label)

        self.items_frame = QFrame()
        self.items_layout = QVBoxLayout(self.items_frame)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(6)
        root.addWidget(self.items_frame)

        self.run_button = QPushButton("🔍  Run Hardware Check")
        self.run_button.setMinimumHeight(34)
        self.run_button.setMinimumWidth(180)
        self.run_button.setCursor(Qt.PointingHandCursor)
        self.run_button.setToolTip(
            "Runs the full hardware check now and saves the result.\n"
            "Use this after updating the graphics (GPU) driver."
        )
        self.run_button.clicked.connect(self._on_run_clicked)
        root.addWidget(self.run_button, alignment=Qt.AlignLeft)

        self._show_persisted()

    # ------------------------------------------------------------------
    def _on_run_clicked(self):
        """Run the full check now (persists + refreshes the MPR gate)."""
        try:
            from modules.mpr.opengl_preflight import run_hardware_check

            self.run_button.setEnabled(False)
            self.run_button.setText("Checking…")
            try:
                result = run_hardware_check(persist=True)
            finally:
                self.run_button.setEnabled(True)
                self.run_button.setText("🔍  Run Hardware Check")
            self._render_result(result)
        except Exception as exc:  # UI must never crash on a diagnostics action
            logger.warning("[HW_CHECK_PANEL] run failed: %r", exc)
            self.summary_label.setText(f"⚠️ Hardware check failed to run: {exc}")

    def _show_persisted(self):
        try:
            from modules.mpr.opengl_preflight import load_persisted_check

            persisted = load_persisted_check()
        except Exception:
            persisted = None
        if persisted:
            self._render_result(persisted)
        else:
            self.summary_label.setText(
                "Not checked yet on this computer — click \"Run Hardware Check\"."
            )

    # ------------------------------------------------------------------
    def _render_result(self, result: dict):
        while self.items_layout.count():
            item = self.items_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        overall = str(result.get("overall") or "warning")
        checked_at = str(result.get("checked_at") or "")
        icon = _STATUS_ICON.get(overall, "⚠️")
        color = _STATUS_COLOR.get(overall, "#fbbf24")
        summary = _OVERALL_TEXT.get(overall, "")
        when = f"   (last checked: {checked_at.replace('T', ' ')})" if checked_at else ""
        self.summary_label.setText(f"{icon} {summary}{when}")
        self.summary_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; padding: 2px 2px; color: {color};"
        )

        for it in result.get("items") or []:
            status = str(it.get("status") or "warning")
            row = QLabel(
                f"{_STATUS_ICON.get(status, '⚠️')}  {it.get('label', '?')}  —  {it.get('detail', '')}"
            )
            row.setWordWrap(True)
            row.setStyleSheet(
                "color: #e5e7eb; font-size: 13px; padding: 7px 9px; "
                "background-color: #1f2937; border-radius: 4px; "
                f"border-left: 3px solid {_STATUS_COLOR.get(status, '#fbbf24')};"
            )
            self.items_layout.addWidget(row)
