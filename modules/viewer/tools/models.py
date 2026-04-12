"""Pure-data models for measurement and annotation tools.

All models store geometry in **image-pixel coordinates** (row, column).
Patient-space measurements (mm, degrees) are derived once at tool completion
and cached as read-only fields.

No Qt / VTK imports — these are plain dataclasses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .enums import ToolType


# ── ROI statistics ──────────────────────────────────────────────────────

@dataclass
class ROIStatistics:
    """Statistics computed over a region of interest."""

    mean: float
    std: float
    min_val: float
    max_val: float
    pixel_count: int
    area_cm2: float


# ── Base model ──────────────────────────────────────────────────────────

@dataclass
class ToolModel:
    """Base annotation model.

    ``points_image`` stores image-pixel coordinates  ``(col, row)`` — i.e.
    ``(x, y)`` in the image frame.  Widget/screen coordinates are derived
    per-frame by ``CoordinateResolver.image_to_widget()``.
    """

    tool_type: ToolType = ToolType.RULER  # overridden by subclass __post_init__
    slice_index: int = 0
    points_image: List[Tuple[float, float]] = field(default_factory=list)
    is_complete: bool = False
    is_selected: bool = False
    label_text: str = ""
    created_at: float = field(default_factory=time.time)


# ── Concrete models ─────────────────────────────────────────────────────

@dataclass
class RulerModel(ToolModel):
    """Two-point distance ruler."""

    distance_mm: float = 0.0

    def __post_init__(self):
        self.tool_type = ToolType.RULER


@dataclass
class AngleModel(ToolModel):
    """Three-point angle measurement."""

    angle_degrees: float = 0.0

    def __post_init__(self):
        self.tool_type = ToolType.ANGLE


@dataclass
class TwoLineAngleModel(ToolModel):
    """Four-point (two-line) angle measurement."""

    angle_degrees: float = 0.0

    def __post_init__(self):
        self.tool_type = ToolType.TWO_LINE_ANGLE


@dataclass
class ROIRectModel(ToolModel):
    """Rectangular region of interest (two corners)."""

    stats: Optional[ROIStatistics] = None

    def __post_init__(self):
        self.tool_type = ToolType.ROI_RECT


@dataclass
class ROICircleModel(ToolModel):
    """Circular region of interest (center + radius)."""

    radius_image_px: float = 0.0
    stats: Optional[ROIStatistics] = None

    def __post_init__(self):
        self.tool_type = ToolType.ROI_CIRCLE


@dataclass
class ArrowModel(ToolModel):
    """Arrow annotation (tail → head) with optional text."""

    text: str = ""
    head_size_px: float = 42.0

    def __post_init__(self):
        self.tool_type = ToolType.ARROW


@dataclass
class TextModel(ToolModel):
    """Free-text annotation at a point."""

    text: str = ""
    font_size: int = 16
    color: Tuple[int, int, int] = (178, 77, 77)

    def __post_init__(self):
        self.tool_type = ToolType.TEXT


@dataclass
class ROIPolygonModel(ToolModel):
    """Polygon region of interest (N vertices)."""

    stats: Optional[ROIStatistics] = None

    def __post_init__(self):
        self.tool_type = ToolType.ROI_POLYGON
