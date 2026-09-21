"""Shared drag-hover dwell policy for Fast and Advanced viewport cells.

The policy delays only the visual hover activation while the pointer is moving
across a layout.  A deliberate quick drop remains accepted by each viewer's own
drop handler; series dispatch and rendering stay in their separate domains.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer

from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (
    _DROP_DWELL_MOVE_TOLERANCE_PX,
    _DROP_HOVER_ARM_MS,
)
from PacsClient.utils.diagnostic_logging import now_ms


class _DropHoverDwellMixin:
    """One hover-activation contract shared by all production viewport cells."""

    def _init_drop_hover_dwell(self) -> None:
        self._drop_hover_started_ms = 0.0
        self._drop_hover_armed = False
        self._drop_hover_inside = False
        self._drop_hover_anchor_pos = None
        self._drop_hover_timer = QTimer(self)
        self._drop_hover_timer.setSingleShot(True)
        self._drop_hover_timer.timeout.connect(self._arm_drop_target)

    def _arm_drop_target(self) -> None:
        """QTimer timeout boundary; never let hover feedback break a drag."""
        try:
            if not self._drop_hover_inside:
                return
            self._drop_hover_timer.stop()
            self._drop_hover_armed = True
            self._show_drop_highlight(True)
        except Exception:
            # Hover feedback is optional. The owning drop handler remains the
            # authority for accepting and dispatching the actual drop.
            return

    @staticmethod
    def _drag_event_point(event):
        try:
            return event.position().toPoint()
        except Exception:
            return event.pos()

    def _restart_drop_dwell(self, anchor_point=None) -> None:
        self._drop_hover_started_ms = now_ms()
        self._drop_hover_armed = _DROP_HOVER_ARM_MS <= 0
        if anchor_point is not None:
            self._drop_hover_anchor_pos = anchor_point
        if self._drop_hover_armed:
            self._show_drop_highlight(True)
            self._drop_hover_timer.stop()
            return
        self._show_drop_highlight(False)
        self._drop_hover_timer.start(_DROP_HOVER_ARM_MS)

    def _begin_drop_hover(self, event) -> None:
        self._drop_hover_inside = True
        self._restart_drop_dwell(anchor_point=self._drag_event_point(event))

    def _update_drop_hover(self, event) -> None:
        self._drop_hover_inside = True
        point = self._drag_event_point(event)
        anchor = self._drop_hover_anchor_pos
        if anchor is None:
            self._restart_drop_dwell(anchor_point=point)
        elif (point - anchor).manhattanLength() > _DROP_DWELL_MOVE_TOLERANCE_PX:
            self._restart_drop_dwell(anchor_point=point)

        # A queued drag-move can arrive after the timer interval but before its
        # timeout is delivered. Arm synchronously in that narrow case.
        if not self._drop_hover_armed and _DROP_HOVER_ARM_MS > 0:
            elapsed_ms = now_ms() - float(self._drop_hover_started_ms or 0.0)
            if elapsed_ms >= _DROP_HOVER_ARM_MS:
                self._arm_drop_target()

    def _reset_drop_hover_state(self, hide_overlay: bool = True) -> None:
        self._drop_hover_inside = False
        self._drop_hover_armed = False
        self._drop_hover_started_ms = 0.0
        self._drop_hover_anchor_pos = None
        try:
            self._drop_hover_timer.stop()
        except (AttributeError, RuntimeError):
            pass
        if hide_overlay:
            self._show_drop_highlight(False)
