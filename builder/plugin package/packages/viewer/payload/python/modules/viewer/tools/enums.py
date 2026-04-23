"""Tool type and state enumerations for the renderer-agnostic tool layer."""

from enum import Enum, auto


class ToolType(Enum):
    """Active measurement / annotation tool."""

    RULER = auto()
    ANGLE = auto()
    TWO_LINE_ANGLE = auto()
    ROI_RECT = auto()
    ROI_CIRCLE = auto()
    ARROW = auto()
    TEXT = auto()
    ERASER = auto()
    ROI_POLYGON = auto()


class ToolState(Enum):
    """Placement state machine state."""

    IDLE = auto()
    PLACING = auto()
    COMPLETE = auto()
    HOVERING = auto()
    DRAGGING = auto()
