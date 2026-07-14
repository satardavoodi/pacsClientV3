"""
Anchor Interaction — User interaction controller for nipple anchor placement.

Handles:
    - Click to place nipple anchor
    - Drag to reposition anchor
    - Delete/replace anchor
    - Undo/redo stack
    - Live update of arc and distance on drag

The controller is a QObject that installs an event filter on the target
viewer widget. It intercepts mouse events and translates them into anchor
operations.

Architecture:
    This controller does NOT draw anything — it only manages state and emits
    signals. The rendering is handled by the arc_renderer module, called from
    the viewer's paintEvent overlay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal
from PySide6.QtWidgets import QWidget

from .anchor_nipple import (
    AnchorPair,
    AnchorState,
    BreastSide,
    DicomImageInfo,
    MammogramView,
    NippleAnchor,
)
from .distance_computation import (
    ArcParameters,
    DistanceResult,
    compute_anchor_distance,
    compute_arc_parameters,
)


# ─── Undo/Redo ───────────────────────────────────────────────────────────────

@dataclass
class AnchorAction:
    """A single undoable anchor operation."""
    action_type: str  # 'place', 'move', 'delete'
    view: MammogramView
    old_anchor: Optional[NippleAnchor]
    new_anchor: Optional[NippleAnchor]


@dataclass
class UndoStack:
    """Simple undo/redo stack for anchor operations."""
    _undo: List[AnchorAction] = field(default_factory=list)
    _redo: List[AnchorAction] = field(default_factory=list)
    max_size: int = 50

    def push(self, action: AnchorAction) -> None:
        """Push an action onto the undo stack, clearing redo."""
        self._undo.append(action)
        if len(self._undo) > self.max_size:
            self._undo.pop(0)
        self._redo.clear()

    def can_undo(self) -> bool:
        return len(self._undo) > 0

    def can_redo(self) -> bool:
        return len(self._redo) > 0

    def undo(self) -> Optional[AnchorAction]:
        if not self._undo:
            return None
        action = self._undo.pop()
        self._redo.append(action)
        return action

    def redo(self) -> Optional[AnchorAction]:
        if not self._redo:
            return None
        action = self._redo.pop()
        self._undo.append(action)
        return action

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()


# ─── Interaction States ──────────────────────────────────────────────────────

class InteractionMode:
    """Enumeration of interaction modes."""
    IDLE = "idle"          # Not interacting
    PLACING = "placing"    # Waiting for click to place anchor
    DRAGGING = "dragging"  # Currently dragging an anchor
    HOVERING = "hovering"  # Mouse near an anchor (highlight)


# ─── Anchor Interaction Controller ───────────────────────────────────────────

class AnchorInteractionController(QObject):
    """
    Manages nipple anchor user interactions on a mammography viewer.

    Signals:
        anchor_placed: Emitted when a new anchor is placed.
        anchor_moved: Emitted when an anchor is dragged to a new position.
        anchor_deleted: Emitted when an anchor is removed.
        anchor_updated: Emitted on any change (for triggering redraw).
        distance_updated: Emitted with new distance measurement.
        error_occurred: Emitted with error message string.

    Usage:
        controller = AnchorInteractionController(viewer_widget)
        controller.set_image_info(dicom_info)
        controller.start_placement()
        # User clicks → anchor_placed signal fires
        # controller.current_anchor holds the anchor
    """

    # ── Signals ──
    anchor_placed = Signal(object)    # NippleAnchor
    anchor_moved = Signal(object)     # NippleAnchor
    anchor_deleted = Signal(object)   # MammogramView
    anchor_updated = Signal()         # Generic update (triggers repaint)
    distance_updated = Signal(object) # DistanceResult
    error_occurred = Signal(str)      # Error message

    # Drag detection threshold in pixels
    DRAG_THRESHOLD_PX = 5.0
    # Hit-test radius for selecting an anchor (pixels)
    HIT_RADIUS_PX = 15.0

    def __init__(self, viewer_widget: QWidget, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._viewer = viewer_widget
        self._image_info: Optional[DicomImageInfo] = None
        self._anchor: Optional[NippleAnchor] = None
        self._mode = InteractionMode.IDLE
        self._undo_stack = UndoStack()
        self._drag_start_px: Optional[Tuple[float, float]] = None
        self._is_selected = False
        self._coord_converter: Optional[Callable] = None

        # Install event filter
        self._viewer.installEventFilter(self)

    # ── Public API ──

    def set_image_info(self, info: DicomImageInfo) -> None:
        """Set the DICOM image metadata for coordinate conversion."""
        self._image_info = info

    def set_coord_converter(self, converter: Callable) -> None:
        """
        Set a function that converts widget (screen) coords to image pixel coords.

        Signature: converter(widget_x: float, widget_y: float) -> (img_x: float, img_y: float)

        If not set, raw widget coordinates are used (only correct for 1:1 zoom).
        """
        self._coord_converter = converter

    @property
    def current_anchor(self) -> Optional[NippleAnchor]:
        """The currently placed anchor, or None."""
        return self._anchor

    @property
    def is_active(self) -> bool:
        """True if in placement mode (waiting for a click)."""
        return self._mode == InteractionMode.PLACING

    @property
    def is_dragging(self) -> bool:
        return self._mode == InteractionMode.DRAGGING

    @property
    def is_selected(self) -> bool:
        return self._is_selected

    def start_placement(self) -> None:
        """Enter placement mode — next click places the anchor."""
        if self._image_info is None:
            self.error_occurred.emit(
                "Cannot place anchor: no DICOM image info set. "
                "Ensure PixelSpacing is available."
            )
            return
        self._mode = InteractionMode.PLACING
        self._viewer.setCursor(Qt.CrossCursor)

    def stop_placement(self) -> None:
        """Exit placement mode without placing."""
        self._mode = InteractionMode.IDLE
        self._viewer.unsetCursor()

    def place_anchor(self, x_px: float, y_px: float) -> Optional[NippleAnchor]:
        """
        Programmatically place an anchor at image pixel coordinates.

        Args:
            x_px: Image x-coordinate in pixels.
            y_px: Image y-coordinate in pixels.

        Returns:
            The created NippleAnchor, or None if creation failed.
        """
        if self._image_info is None:
            self.error_occurred.emit("Cannot place anchor: missing image info.")
            return None

        try:
            new_anchor = NippleAnchor.create(x_px, y_px, self._image_info)
        except ValueError as e:
            self.error_occurred.emit(f"Invalid anchor position: {e}")
            return None

        # Record undo action
        action = AnchorAction(
            action_type='place',
            view=self._image_info.view,
            old_anchor=self._anchor,
            new_anchor=new_anchor,
        )
        self._undo_stack.push(action)

        self._anchor = new_anchor
        self._mode = InteractionMode.IDLE
        self._viewer.unsetCursor()

        self.anchor_placed.emit(new_anchor)
        self.anchor_updated.emit()
        return new_anchor

    def delete_anchor(self) -> None:
        """Remove the current anchor."""
        if self._anchor is None:
            return

        action = AnchorAction(
            action_type='delete',
            view=self._anchor.view,
            old_anchor=self._anchor,
            new_anchor=None,
        )
        self._undo_stack.push(action)

        view = self._anchor.view
        self._anchor = None
        self._is_selected = False

        self.anchor_deleted.emit(view)
        self.anchor_updated.emit()

    def undo(self) -> None:
        """Undo the last anchor operation."""
        action = self._undo_stack.undo()
        if action is None:
            return
        self._anchor = action.old_anchor
        self._is_selected = False
        self.anchor_updated.emit()

    def redo(self) -> None:
        """Redo the last undone operation."""
        action = self._undo_stack.redo()
        if action is None:
            return
        self._anchor = action.new_anchor
        self._is_selected = action.new_anchor is not None
        self.anchor_updated.emit()

    def cleanup(self) -> None:
        """Remove the event filter and release resources."""
        try:
            self._viewer.removeEventFilter(self)
        except RuntimeError:
            pass
        self._undo_stack.clear()

    # ── Event Filter ──

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Intercept mouse events on the viewer widget."""
        if obj is not self._viewer:
            return False

        event_type = event.type()

        if event_type == QEvent.MouseButtonPress:
            return self._on_mouse_press(event)
        elif event_type == QEvent.MouseMove:
            return self._on_mouse_move(event)
        elif event_type == QEvent.MouseButtonRelease:
            return self._on_mouse_release(event)

        return False

    # ── Mouse Handlers ──

    def _on_mouse_press(self, event) -> bool:
        """Handle mouse press."""
        if event.button() != Qt.LeftButton:
            return False

        pos = self._get_image_pos(event)
        if pos is None:
            return False

        x_px, y_px = pos

        # In placement mode — place the anchor
        if self._mode == InteractionMode.PLACING:
            self.place_anchor(x_px, y_px)
            return True  # Consume event

        # If clicking near existing anchor — start drag
        if self._anchor is not None and self._anchor.is_valid:
            dist = self._anchor.distance_to_px(x_px, y_px)
            if dist <= self.HIT_RADIUS_PX:
                self._mode = InteractionMode.DRAGGING
                self._drag_start_px = (x_px, y_px)
                self._is_selected = True
                self.anchor_updated.emit()
                return True  # Consume

        return False  # Pass through to viewer

    def _on_mouse_move(self, event) -> bool:
        """Handle mouse move (drag)."""
        if self._mode != InteractionMode.DRAGGING:
            return False

        pos = self._get_image_pos(event)
        if pos is None:
            return False

        x_px, y_px = pos

        # Move the anchor
        if self._image_info is not None:
            try:
                new_anchor = NippleAnchor.create(x_px, y_px, self._image_info)
                self._anchor = new_anchor
                self.anchor_moved.emit(new_anchor)
                self.anchor_updated.emit()
            except ValueError:
                pass

        return True  # Consume during drag

    def _on_mouse_release(self, event) -> bool:
        """Handle mouse release (end drag)."""
        if self._mode != InteractionMode.DRAGGING:
            return False

        if event.button() != Qt.LeftButton:
            return False

        # Finalize drag — record undo
        if self._drag_start_px is not None and self._anchor is not None:
            action = AnchorAction(
                action_type='move',
                view=self._anchor.view,
                old_anchor=NippleAnchor.create(
                    self._drag_start_px[0],
                    self._drag_start_px[1],
                    self._image_info,
                ) if self._image_info else None,
                new_anchor=self._anchor,
            )
            self._undo_stack.push(action)

        self._mode = InteractionMode.IDLE
        self._drag_start_px = None
        self.anchor_updated.emit()
        return True

    # ── Coordinate Conversion ──

    def _get_image_pos(self, event) -> Optional[Tuple[float, float]]:
        """Convert a mouse event position to image pixel coordinates."""
        pos = event.position() if hasattr(event, 'position') else event.pos()
        wx, wy = pos.x(), pos.y()

        if self._coord_converter is not None:
            try:
                return self._coord_converter(wx, wy)
            except Exception:
                return (wx, wy)

        return (wx, wy)
