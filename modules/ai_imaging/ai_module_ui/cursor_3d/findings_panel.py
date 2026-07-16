"""
Findings overlay panel — a small, click-to-select list shown IN A CORNER of the
destination viewport when the 3D Cursor finds more than one corresponding lesion.

WHY (2026-07-15): with two or three findings the viewport became unreadable — every
box, label and heatmap drawn at once, so large parts of the breast were highlighted.
This panel shows HOW MANY findings there are and each score, and lets the radiologist
review them ONE AT A TIME: clicking a row selects that finding, and the controller
redraws it at full intensity (box + region + heatmap) while the others drop back to
small numbered markers.

Qt only (no VTK). It is a child QWidget raised over the viewport; clicks are handled
by Qt and never reach the VTK interactor underneath. Every use in the controller is
wrapped in try/except so, if anything about the Qt-over-VTK overlay misbehaves on a
given machine, the workflow still works from the markers + the sidebar text.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


_PANEL_QSS = """
#cursor3dFindingsPanel {
    background-color: rgba(12, 18, 26, 210);
    border: 1px solid rgba(120, 190, 235, 160);
    border-radius: 8px;
}
#cursor3dFindingsTitle { color: #cfe6f5; font-weight: 600; }
"""

_ROW_BASE = (
    "padding:3px 8px; border-radius:5px; color:#d7e6f0; "
    "background-color: rgba(255,255,255,10);"
)
_ROW_SELECTED = (
    "padding:3px 8px; border-radius:5px; color:#04121c; font-weight:700; "
    "background-color: rgba(30, 220, 255, 235);"
)


class _Row(QLabel):
    """A single clickable finding row. Emits its index on left-click."""

    clicked = Signal(int)

    def __init__(self, index: int, text: str, parent=None):
        super().__init__(text, parent)
        self._index = index
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(_ROW_BASE)

    def mousePressEvent(self, ev):  # noqa: N802 (Qt signature)
        try:
            if ev.button() == Qt.LeftButton:
                self.clicked.emit(self._index)
        except Exception:
            pass
        super().mousePressEvent(ev)


class FindingsOverlayPanel(QFrame):
    """
    Corner overlay listing the findings. `selected(index)` fires on a row click.

    Usage:
        panel = FindingsOverlayPanel(viewport_widget)
        panel.selected.connect(on_select)
        panel.set_findings([(1, 0.48, "R MLO->CC"), (2, 0.46, "R MLO->CC")], selected=0)
        panel.show_in_corner()
    """

    selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cursor3dFindingsPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_PANEL_QSS)
        self._selected_idx = 0
        self._rows: List[_Row] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(4)
        self._title = QLabel("Findings")
        self._title.setObjectName("cursor3dFindingsTitle")
        lay.addWidget(self._title)
        self._layout = lay

        if parent is not None:
            try:
                parent.installEventFilter(self)
            except Exception:
                pass

    # ── content ──────────────────────────────────────────────────────────────
    def set_findings(self, items: List[Tuple[int, int, Optional[float], str]], selected: int = 0) -> None:
        """items = [(global_index, number, score, subtitle), ...], top first.

        `global_index` is the finding's index in the controller's ordered list — it
        is what a click emits and what `set_selected` matches on, so the panel stays
        correct even if findings target more than one viewport."""
        for r in self._rows:
            try:
                r.setParent(None)
                r.deleteLater()
            except Exception:
                pass
        self._rows = []

        n = len(items)
        self._title.setText(f"{n} finding{'s' if n != 1 else ''} — click to review")
        for (global_index, number, score, subtitle) in items:
            score_txt = "" if score is None else f"   {score:.2f}"
            sub = f"   ·  {subtitle}" if subtitle else ""
            row = _Row(global_index, f"#{number}{score_txt}{sub}", self)
            row.clicked.connect(self._on_row_clicked)
            self._layout.addWidget(row)
            self._rows.append(row)

        self.set_selected(selected)
        self.adjustSize()
        self.show_in_corner()

    def set_selected(self, idx: int) -> None:
        self._selected_idx = idx
        for row in self._rows:
            row.setStyleSheet(_ROW_SELECTED if row._index == idx else _ROW_BASE)

    def _on_row_clicked(self, idx: int) -> None:
        self.set_selected(idx)
        try:
            self.selected.emit(idx)
        except Exception:
            pass

    # ── placement ────────────────────────────────────────────────────────────
    def show_in_corner(self, margin: int = 12) -> None:
        """Pin to the TOP-LEFT of the parent viewport (clear of the top-right
        'advance / Hide Boxes' buttons and the date stamp)."""
        p = self.parentWidget()
        if p is None:
            self.show()
            return
        try:
            self.adjustSize()
            self.move(margin, margin + 30)  # below the top toolbar row
            self.raise_()
            self.show()
        except Exception:
            self.show()

    def eventFilter(self, obj, ev):  # noqa: N802
        # Re-pin on parent resize so the panel stays in the corner.
        try:
            from PySide6.QtCore import QEvent
            if obj is self.parentWidget() and ev.type() == QEvent.Resize:
                self.show_in_corner()
        except Exception:
            pass
        return False
