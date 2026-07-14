"""
Arc Renderer — Anti-aliased arc visualization with ±10% uncertainty band.

This module renders the correspondence arc on a Qt/VTK mammography viewer.
It draws three concentric arcs representing:
    - Inner arc: lower bound (distance × 0.90)
    - Nominal arc: best estimate (solid)
    - Outer arc: upper bound (distance × 1.10)

Plus:
    - A shaded uncertainty band between inner and outer arcs.
    - A nipple marker (crosshair).
    - A distance label with tolerance information.

All rendering is performed in Qt coordinates using QPainter for smooth,
scalable, anti-aliased output that works at any zoom level.

Performance:
    - Arcs are computed once and cached until the anchor moves.
    - QPainterPath is used for efficient GPU-accelerated rendering.
    - No per-frame allocations during pan/zoom (only transform updates).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)


from .anchor_nipple import AnchorState, NippleAnchor
from .distance_computation import ArcParameters, DistanceResult


# ─── Visual Constants ────────────────────────────────────────────────────────

# Nipple marker
NIPPLE_MARKER_RADIUS_PX = 6.0
NIPPLE_CROSSHAIR_SIZE_PX = 12.0
NIPPLE_COLOR = QColor(255, 80, 80, 220)  # Red
NIPPLE_SELECTED_COLOR = QColor(255, 200, 50, 255)  # Gold when selected

# Arc colors
ARC_NOMINAL_COLOR = QColor(0, 180, 255, 200)  # Cyan
ARC_INNER_COLOR = QColor(0, 180, 255, 100)    # Cyan, semi-transparent
ARC_OUTER_COLOR = QColor(0, 180, 255, 100)    # Cyan, semi-transparent
ARC_BAND_COLOR = QColor(0, 180, 255, 40)      # Very light cyan fill

# Distance label
LABEL_BG_COLOR = QColor(0, 0, 0, 180)  # Semi-transparent black
LABEL_TEXT_COLOR = QColor(255, 255, 255, 240)  # White
LABEL_FONT_SIZE = 11

# Line widths (in pixels, scale-independent)
NOMINAL_ARC_WIDTH = 2.5
BOUND_ARC_WIDTH = 1.2
NIPPLE_LINE_WIDTH = 2.0

# Minimum arc radius in pixels to render (avoid visual noise)
MIN_ARC_RADIUS_PX = 5.0


# ─── Render State ────────────────────────────────────────────────────────────

@dataclass
class ArcRenderState:
    """
    Cached render state for the arc visualization.

    Recalculated only when the anchor moves or zoom changes.
    """
    # Arc geometry (in image pixel coordinates)
    center_px: Tuple[float, float]
    nominal_radius_px: float
    inner_radius_px: float
    outer_radius_px: float
    start_angle_deg: float  # Qt uses degrees for arc drawing
    span_angle_deg: float
    # Distance info for label
    distance_mm: float
    lower_bound_mm: float
    upper_bound_mm: float
    tolerance_pct: float
    # Whether arc is partially outside image
    clipped: bool = False
    # Error state
    error_message: str = ""

    @classmethod
    def from_arc_params(cls, params: ArcParameters) -> "ArcRenderState":
        """Create render state from computed arc parameters."""
        # Convert radians to degrees for Qt (Qt measures counter-clockwise from 3 o'clock)
        # In image coords (y-down), angles are inverted from math convention.
        start_deg = -math.degrees(params.start_angle_rad)
        end_deg = -math.degrees(params.end_angle_rad)
        span_deg = end_deg - start_deg

        # Normalize span to be positive (Qt draws CCW for positive span)
        if span_deg > 0:
            span_deg = -(360.0 - span_deg)

        return cls(
            center_px=params.center_px,
            nominal_radius_px=params.nominal_radius_px,
            inner_radius_px=params.inner_radius_px,
            outer_radius_px=params.outer_radius_px,
            start_angle_deg=start_deg,
            span_angle_deg=span_deg,
            distance_mm=params.nominal_radius_mm,
            lower_bound_mm=params.inner_radius_mm,
            upper_bound_mm=params.outer_radius_mm,
            tolerance_pct=10.0,
            error_message=params.error_message,
        )

    @classmethod
    def from_distance(
        cls,
        anchor: NippleAnchor,
        distance: DistanceResult,
        angular_extent_deg: float = 120.0,
    ) -> "ArcRenderState":
        """
        Create render state from a single anchor + distance result.

        Used when drawing the arc on the SAME view as the anchor
        (visualizing the localization region around the nipple).
        """
        if not distance.is_valid or distance.distance_mm <= 0:
            return cls(
                center_px=anchor.position_px,
                nominal_radius_px=0.0,
                inner_radius_px=0.0,
                outer_radius_px=0.0,
                start_angle_deg=0.0,
                span_angle_deg=0.0,
                distance_mm=0.0,
                lower_bound_mm=0.0,
                upper_bound_mm=0.0,
                tolerance_pct=10.0,
                error_message=distance.error_message or "Invalid distance",
            )

        # Convert mm radii to pixels using geometric mean of spacing
        info = anchor.image_info
        avg_spacing = math.sqrt(info.pixel_spacing_x_mm * info.pixel_spacing_y_mm)

        nominal_px = distance.distance_mm / avg_spacing
        inner_px = distance.lower_bound_mm / avg_spacing
        outer_px = distance.upper_bound_mm / avg_spacing

        # Full circle arc (360°) for same-view visualization
        start_deg = 0.0
        span_deg = -360.0  # Full circle

        return cls(
            center_px=anchor.position_px,
            nominal_radius_px=nominal_px,
            inner_radius_px=inner_px,
            outer_radius_px=outer_px,
            start_angle_deg=start_deg,
            span_angle_deg=span_deg,
            distance_mm=distance.distance_mm,
            lower_bound_mm=distance.lower_bound_mm,
            upper_bound_mm=distance.upper_bound_mm,
            tolerance_pct=distance.tolerance_fraction * 100.0,
        )


# ─── Rendering Functions ─────────────────────────────────────────────────────

def render_nipple_marker(
    painter: QPainter,
    anchor: NippleAnchor,
    selected: bool = False,
    zoom_factor: float = 1.0,
) -> None:
    """
    Draw the nipple anchor marker (crosshair + circle).

    The marker remains the same screen size regardless of zoom
    (it's drawn in widget coordinates after the view transform).

    Args:
        painter: Active QPainter (already configured with transform).
        anchor: The nipple anchor to draw.
        selected: If True, draw in highlight color.
        zoom_factor: Current zoom level (for size normalization).
    """
    if anchor.state == AnchorState.EMPTY:
        return

    cx, cy = anchor.x_px, anchor.y_px
    color = NIPPLE_SELECTED_COLOR if selected else NIPPLE_COLOR

    # Scale marker size inversely with zoom so it stays readable
    inv_zoom = 1.0 / max(0.1, zoom_factor)
    marker_r = NIPPLE_MARKER_RADIUS_PX * inv_zoom
    cross_size = NIPPLE_CROSSHAIR_SIZE_PX * inv_zoom
    line_w = NIPPLE_LINE_WIDTH * inv_zoom

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)

    # Draw filled circle
    pen = QPen(color, line_w)
    pen.setCosmetic(True)  # Constant screen width regardless of transform
    painter.setPen(pen)
    fill_color = QColor(color)
    fill_color.setAlpha(80)
    painter.setBrush(QBrush(fill_color))
    painter.drawEllipse(QPointF(cx, cy), marker_r, marker_r)

    # Draw crosshair lines
    painter.setPen(QPen(color, line_w * 0.7))
    painter.drawLine(
        QPointF(cx - cross_size, cy),
        QPointF(cx + cross_size, cy),
    )
    painter.drawLine(
        QPointF(cx, cy - cross_size),
        QPointF(cx, cy + cross_size),
    )

    # Draw "out of image" warning indicator
    if anchor.state == AnchorState.OUT_OF_IMAGE:
        warn_color = QColor(255, 50, 50, 200)
        painter.setPen(QPen(warn_color, line_w * 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), marker_r * 2, marker_r * 2)

    painter.restore()


def render_arc_with_uncertainty(
    painter: QPainter,
    state: ArcRenderState,
    zoom_factor: float = 1.0,
) -> None:
    """
    Draw the correspondence arc with ±10% uncertainty band.

    Renders three elements:
    1. Shaded uncertainty band (between inner and outer arcs).
    2. Inner bound arc (dashed).
    3. Outer bound arc (dashed).
    4. Nominal arc (solid, thicker).

    Args:
        painter: Active QPainter.
        state: Pre-computed arc render state.
        zoom_factor: Current zoom level.
    """
    if state.nominal_radius_px < MIN_ARC_RADIUS_PX:
        return
    if state.error_message:
        return

    cx, cy = state.center_px
    inv_zoom = 1.0 / max(0.1, zoom_factor)

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)

    # ── 1. Shaded uncertainty band ──
    _draw_uncertainty_band(painter, state)

    # ── 2. Inner bound arc (dashed) ──
    inner_pen = QPen(ARC_INNER_COLOR, BOUND_ARC_WIDTH * inv_zoom)
    inner_pen.setStyle(Qt.DashLine)
    inner_pen.setCosmetic(True)
    painter.setPen(inner_pen)
    painter.setBrush(Qt.NoBrush)
    _draw_arc(painter, cx, cy, state.inner_radius_px,
              state.start_angle_deg, state.span_angle_deg)

    # ── 3. Outer bound arc (dashed) ──
    outer_pen = QPen(ARC_OUTER_COLOR, BOUND_ARC_WIDTH * inv_zoom)
    outer_pen.setStyle(Qt.DashLine)
    outer_pen.setCosmetic(True)
    painter.setPen(outer_pen)
    _draw_arc(painter, cx, cy, state.outer_radius_px,
              state.start_angle_deg, state.span_angle_deg)

    # ── 4. Nominal arc (solid, prominent) ──
    nominal_pen = QPen(ARC_NOMINAL_COLOR, NOMINAL_ARC_WIDTH * inv_zoom)
    nominal_pen.setCosmetic(True)
    painter.setPen(nominal_pen)
    _draw_arc(painter, cx, cy, state.nominal_radius_px,
              state.start_angle_deg, state.span_angle_deg)

    painter.restore()


def render_distance_label(
    painter: QPainter,
    state: ArcRenderState,
    position_px: Optional[Tuple[float, float]] = None,
    zoom_factor: float = 1.0,
) -> None:
    """
    Draw the distance label with measurement information.

    Displays:
        Distance: 64.3 mm
        Tolerance: ±10%
        Range: 57.9–70.7 mm

    Args:
        painter: Active QPainter.
        state: Arc render state with distance info.
        position_px: Label position in image pixels. If None, auto-positions
                     above the arc center.
        zoom_factor: Current zoom level.
    """
    if state.distance_mm <= 0:
        return

    inv_zoom = 1.0 / max(0.1, zoom_factor)

    # Auto-position: above the nipple, offset by nominal radius
    if position_px is None:
        cx, cy = state.center_px
        # Place label above the arc (negative y direction)
        label_x = cx
        label_y = cy - state.nominal_radius_px - 30 * inv_zoom
    else:
        label_x, label_y = position_px

    # Build label text
    if state.error_message and "خارج" in state.error_message:
        # Out-of-image: show Farsi warning prominently first
        lines = [
            f"⚠ خارج از ناحیه تصویر",
            f"Distance: {state.distance_mm:.1f} mm",
            f"Range (±{state.tolerance_pct:.0f}%): {state.lower_bound_mm:.1f}–{state.upper_bound_mm:.1f} mm",
        ]
    else:
        lines = [
            f"Distance: {state.distance_mm:.1f} mm",
            f"Arc (±{state.tolerance_pct:.0f}%): {state.lower_bound_mm:.1f}–{state.upper_bound_mm:.1f} mm",
        ]
        if state.error_message:
            lines.append(f"⚠ {state.error_message}")

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)

    # Font setup (scale-independent)
    font = QFont("Segoe UI", int(LABEL_FONT_SIZE * inv_zoom))
    font.setWeight(QFont.Medium)
    painter.setFont(font)

    # Compute text bounding rect
    line_height = painter.fontMetrics().height()
    max_width = max(painter.fontMetrics().horizontalAdvance(line) for line in lines)
    padding = 6 * inv_zoom
    total_height = line_height * len(lines) + padding * 2
    total_width = max_width + padding * 2

    # Background rectangle
    bg_rect = QRectF(
        label_x - total_width / 2,
        label_y - total_height,
        total_width,
        total_height,
    )

    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(LABEL_BG_COLOR))
    painter.drawRoundedRect(bg_rect, 4 * inv_zoom, 4 * inv_zoom)

    # Draw text lines
    painter.setPen(QPen(LABEL_TEXT_COLOR))
    for i, line in enumerate(lines):
        text_y = bg_rect.top() + padding + (i + 1) * line_height
        painter.drawText(
            QPointF(bg_rect.left() + padding, text_y),
            line,
        )

    painter.restore()


def render_anchor_system(
    painter: QPainter,
    anchor: NippleAnchor,
    arc_state: Optional[ArcRenderState] = None,
    selected: bool = False,
    zoom_factor: float = 1.0,
    show_label: bool = True,
) -> None:
    """
    Render the complete anchor visualization system.

    This is the main entry point for drawing the nipple anchor with its
    arc and distance label.

    Args:
        painter: Active QPainter (must be begin()'d).
        anchor: The nipple anchor to visualize.
        arc_state: Pre-computed arc state (if distance has been measured).
        selected: Whether this anchor is currently selected/active.
        zoom_factor: Current zoom factor for scale-independent rendering.
        show_label: Whether to show the distance label.
    """
    # 1. Draw the arc with uncertainty band (behind the marker)
    if arc_state is not None:
        render_arc_with_uncertainty(painter, arc_state, zoom_factor)

    # 2. Draw the nipple marker (on top)
    render_nipple_marker(painter, anchor, selected, zoom_factor)

    # 3. Draw the distance label
    if show_label and arc_state is not None and arc_state.distance_mm > 0:
        render_distance_label(painter, arc_state, zoom_factor=zoom_factor)


# ─── Internal Drawing Helpers ────────────────────────────────────────────────

def _draw_arc(
    painter: QPainter,
    cx: float,
    cy: float,
    radius: float,
    start_angle_deg: float,
    span_angle_deg: float,
) -> None:
    """
    Draw an arc using QPainter.drawArc.

    Qt's drawArc uses 1/16th degree units and a bounding rectangle.

    Args:
        cx, cy: Arc center in image pixel coordinates.
        radius: Arc radius in pixels.
        start_angle_deg: Start angle in degrees (0=3 o'clock, CCW positive).
        span_angle_deg: Angular span in degrees (negative = CW).
    """
    rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
    # Qt uses 1/16th degree units
    start_16 = int(start_angle_deg * 16)
    span_16 = int(span_angle_deg * 16)
    painter.drawArc(rect, start_16, span_16)


def _draw_uncertainty_band(painter: QPainter, state: ArcRenderState) -> None:
    """
    Draw the shaded uncertainty band between inner and outer arcs.

    Uses a QPainterPath to fill the annular region.
    """
    cx, cy = state.center_px
    inner_r = state.inner_radius_px
    outer_r = state.outer_radius_px

    if outer_r - inner_r < 1.0:
        return  # Band too thin to render

    # Build an annular path
    path = QPainterPath()

    # Outer arc (forward)
    outer_rect = QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2)
    inner_rect = QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)

    start = state.start_angle_deg
    span = state.span_angle_deg

    # For full circles, simplify to two ellipses
    if abs(span) >= 359.0:
        path.addEllipse(outer_rect)
        # Subtract inner
        inner_path = QPainterPath()
        inner_path.addEllipse(inner_rect)
        path = path.subtracted(inner_path)
    else:
        # Partial arc: build the band as a closed shape
        # This is an approximation using line segments
        num_segments = max(32, int(abs(span) / 2))
        angle_step = span / num_segments

        # Outer arc points
        outer_points: List[QPointF] = []
        for i in range(num_segments + 1):
            angle_deg = start + i * angle_step
            angle_rad = math.radians(-angle_deg)  # Qt angles are inverted
            px = cx + outer_r * math.cos(angle_rad)
            py = cy + outer_r * math.sin(angle_rad)
            outer_points.append(QPointF(px, py))

        # Inner arc points (reverse order to close the path)
        inner_points: List[QPointF] = []
        for i in range(num_segments, -1, -1):
            angle_deg = start + i * angle_step
            angle_rad = math.radians(-angle_deg)
            px = cx + inner_r * math.cos(angle_rad)
            py = cy + inner_r * math.sin(angle_rad)
            inner_points.append(QPointF(px, py))

        # Build path
        if outer_points:
            path.moveTo(outer_points[0])
            for pt in outer_points[1:]:
                path.lineTo(pt)
            for pt in inner_points:
                path.lineTo(pt)
            path.closeSubpath()

    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(ARC_BAND_COLOR))
    painter.drawPath(path)
