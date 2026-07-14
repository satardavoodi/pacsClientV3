"""
Pectoral Line Interaction — User interaction for manual pectoral line placement.

The user draws the pectoral line by placing two points on the MLO image.
This replaces automatic detection and the fixed 45° assumption.

Workflow:
    1. User activates Pectoral Line Tool.
    2. First click places the start point.
    3. Second click places the end point → line is finalized.
    4. User can drag either endpoint to adjust.
    5. Delete to remove and re-draw.

All operations support undo/redo via the shared UndoStack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal
from PySide6.QtWidgets import QWidget

from .anchor_nipple import BreastSide, DicomImageInfo, MammogramView
from .pectoral_line_anchor import PectoralLineAnchor


# ─── Undo/Redo ───────────────────────────────────────────────────────────────


@dataclass
class PectoralLineAction:
    """A single undoable pectoral line operation."""
    action_type: str  # 'place', 'move_start', 'move_end', 'delete'
    old_line: Optional[PectoralLineAnchor]
    new_line: Optional[PectoralLineAnchor]


@dataclass
class PectoralUndoStack:
    """Undo/redo stack for pectoral line operations."""
    _undo: List[PectoralLineAction] = field(default_factory=list)
    _redo: List[PectoralLineAction] = field(default_factory=list)
    max_size: int = 50

    def push(self, action: PectoralLineAction) -> None:
        self._undo.append(action)
        if len(self._undo) > self.max_size:
            self._undo.pop(0)
        self._redo.clear()

    def can_undo(self) -> bool:
        return len(self._undo) > 0

    def can_redo(self) -> bool:
        return len(self._redo) > 0

    def undo(self) -> Optional[PectoralLineAction]:
        if not self._undo:
            return None
        action = self._undo.pop()
        self._redo.append(action)
        return action

    def redo(self) -> Optional[PectoralLineAction]:
        if not self._redo:
            return None
        action = self._redo.pop()
        self._undo.append(action)
        return action

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()


# ─── Interaction Modes ───────────────────────────────────────────────────────


class PectoralInteractionMode:
    IDLE = "idle"
    PLACING_START = "placing_start"
    PLACING_END = "placing_end"
    DRAGGING_START = "dragging_start"
    DRAGGING_END = "dragging_end"


# ─── Controller ──────────────────────────────────────────────────────────────


class PectoralLineInteractionController(QObject):
    """
    Manages pectoral line user interactions on a mammography viewer.

    Signals:
        line_placed: Emitted when a complete pectoral line is placed.
        line_moved: Emitted when an endpoint is dragged.
        line_deleted: Emitted when the line is removed.
        line_updated: Generic update signal (triggers repaint).
        error_occurred: Emitted with error message string.
    """

    line_placed = Signal(object)    # PectoralLineAnchor
    line_moved = Signal(object)     # PectoralLineAnchor
    line_deleted = Signal()
    line_updated = Signal()
    error_occurred = Signal(str)

    # Hit-test radius for endpoint selection (pixels)
    HIT_RADIUS_PX = 12.0

    def __init__(self, viewer_widget: QWidget, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._viewer = viewer_widget
        self._image_info: Optional[DicomImageInfo] = None
        self._side: Optional[BreastSide] = None
        self._view: Optional[MammogramView] = None
        self._line: Optional[PectoralLineAnchor] = None
        self._mode = PectoralInteractionMode.IDLE
        self._undo_stack = PectoralUndoStack()
        self._pending_start_px: Optional[Tuple[float, float]] = None
        self._coord_converter: Optional[Callable] = None

        self._viewer.installEventFilter(self)

    # ── Public API ──

    def set_image_info(
        self,
        info: DicomImageInfo,
        side: BreastSide,
        view: MammogramView,
    ) -> None:
        """Set DICOM metadata and laterality/view for line construction."""
        self._image_info = info
        self._side = side
        self._view = view

    def set_coord_converter(self, converter: Callable) -> None:
        """
        Set converter: (widget_x, widget_y) -> (image_x_px, image_y_px).
        """
        self._coord_converter = converter

    @property
    def current_line(self) -> Optional[PectoralLineAnchor]:
        return self._line

    @property
    def is_active(self) -> bool:
        return self._mode in (
            PectoralInteractionMode.PLACING_START,
            PectoralInteractionMode.PLACING_END,
        )

    @property
    def angle_deg(self) -> Optional[float]:
        """Return the pectoral angle from vertical, or None if no line."""
        if self._line is None:
            return None
        return self._line.angle_from_vertical_deg

    def start_placement(self) -> None:
        """Enter placement mode — next two clicks define the line."""
        if self._image_info is None:
            self.error_occurred.emit(
                "Cannot place pectoral line: no DICOM image info set."
            )
            return
        self._mode = PectoralInteractionMode.PLACING_START
        self._pending_start_px = None
        self._viewer.setCursor(Qt.CrossCursor)

    def stop_placement(self) -> None:
        """Cancel placement without placing."""
        self._mode = PectoralInteractionMode.IDLE
        self._pending_start_px = None
        self._viewer.unsetCursor()

    def delete_line(self) -> None:
        """Remove the current pectoral line."""
        if self._line is None:
            return
        old_line = self._line
        self._line = None
        self._undo_stack.push(PectoralLineAction(
            action_type='delete', old_line=old_line, new_line=None
        ))
        self.line_deleted.emit()
        self.line_updated.emit()

    def undo(self) -> None:
        """Undo the last pectoral line action."""
        action = self._undo_stack.undo()
        if action is None:
            return
        self._line = action.old_line
        self.line_updated.emit()

    def redo(self) -> None:
        """Redo the last undone action."""
        action = self._undo_stack.redo()
        if action is None:
            return
        self._line = action.new_line
        self.line_updated.emit()

    # ── Event Filter ──

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is not self._viewer:
            return False

        if event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                return self._handle_left_press(event)

        elif event.type() == QEvent.MouseMove:
            if self._mode in (
                PectoralInteractionMode.DRAGGING_START,
                PectoralInteractionMode.DRAGGING_END,
            ):
                return self._handle_drag_move(event)

        elif event.type() == QEvent.MouseButtonRelease:
            if event.button() == Qt.LeftButton:
                return self._handle_left_release(event)

        return False

    # ── Private Handlers ──

    def _to_image_px(self, event) -> Tuple[float, float]:
        """Convert a mouse event to image pixel coordinates."""
        pos = event.position() if hasattr(event, 'position') else event.pos()
        wx, wy = pos.x(), pos.y()
        if self._coord_converter:
            return self._coord_converter(wx, wy)
        return (wx, wy)

    def _handle_left_press(self, event) -> bool:
        img_x, img_y = self._to_image_px(event)

        if self._mode == PectoralInteractionMode.PLACING_START:
            self._pending_start_px = (img_x, img_y)
            self._mode = PectoralInteractionMode.PLACING_END
            return True

        elif self._mode == PectoralInteractionMode.PLACING_END:
            if self._pending_start_px is None:
                self._mode = PectoralInteractionMode.IDLE
                return False
            self._finalize_placement(img_x, img_y)
            return True

        elif self._mode == PectoralInteractionMode.IDLE and self._line is not None:
            # Check if clicking near an endpoint to start dragging
            endpoint = self._hit_test_endpoint(img_x, img_y)
            if endpoint == 'start':
                self._mode = PectoralInteractionMode.DRAGGING_START
                return True
            elif endpoint == 'end':
                self._mode = PectoralInteractionMode.DRAGGING_END
                return True

        return False

    def _handle_drag_move(self, event) -> bool:
        img_x, img_y = self._to_image_px(event)

        if self._line is None or self._image_info is None:
            self._mode = PectoralInteractionMode.IDLE
            return False

        try:
            if self._mode == PectoralInteractionMode.DRAGGING_START:
                new_line = PectoralLineAnchor.from_pixels(
                    x1_px=img_x, y1_px=img_y,
                    x2_px=self._line.x2_px, y2_px=self._line.y2_px,
                    side=self._side, view=self._view,
                    image_info=self._image_info,
                )
            else:
                new_line = PectoralLineAnchor.from_pixels(
                    x1_px=self._line.x1_px, y1_px=self._line.y1_px,
                    x2_px=img_x, y2_px=img_y,
                    side=self._side, view=self._view,
                    image_info=self._image_info,
                )
            self._line = new_line
            self.line_updated.emit()
        except ValueError:
            pass  # Degenerate line during drag — ignore

        return True

    def _handle_left_release(self, event) -> bool:
        if self._mode in (
            PectoralInteractionMode.DRAGGING_START,
            PectoralInteractionMode.DRAGGING_END,
        ):
            old_line = self._line  # Already updated in drag_move
            self._undo_stack.push(PectoralLineAction(
                action_type='move_start' if self._mode == PectoralInteractionMode.DRAGGING_START else 'move_end',
                old_line=old_line,
                new_line=self._line,
            ))
            self._mode = PectoralInteractionMode.IDLE
            self.line_moved.emit(self._line)
            return True
        return False

    def _finalize_placement(self, end_x: float, end_y: float) -> None:
        """Create the pectoral line from pending start + new end point."""
        start_x, start_y = self._pending_start_px
        self._pending_start_px = None
        self._mode = PectoralInteractionMode.IDLE
        self._viewer.unsetCursor()

        try:
            new_line = PectoralLineAnchor.from_pixels(
                x1_px=start_x, y1_px=start_y,
                x2_px=end_x, y2_px=end_y,
                side=self._side, view=self._view,
                image_info=self._image_info,
            )
        except ValueError as e:
            self.error_occurred.emit(str(e))
            return

        old_line = self._line
        self._line = new_line
        self._undo_stack.push(PectoralLineAction(
            action_type='place', old_line=old_line, new_line=new_line
        ))
        self.line_placed.emit(new_line)
        self.line_updated.emit()

    def _hit_test_endpoint(self, x_px: float, y_px: float) -> Optional[str]:
        """Check if (x_px, y_px) is near a line endpoint."""
        if self._line is None:
            return None
        r = self.HIT_RADIUS_PX
        d1 = math.sqrt(
            (x_px - self._line.x1_px) ** 2 + (y_px - self._line.y1_px) ** 2
        )
        d2 = math.sqrt(
            (x_px - self._line.x2_px) ** 2 + (y_px - self._line.y2_px) ** 2
        )
        if d1 <= r and d1 <= d2:
            return 'start'
        if d2 <= r:
            return 'end'
        return None


import math
