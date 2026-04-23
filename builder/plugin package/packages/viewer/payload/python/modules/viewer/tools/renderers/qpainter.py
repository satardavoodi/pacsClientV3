"""QPainter-based tool renderer for FAST mode.

Draws measurement annotations using QPainter in widget coordinates.
All visual constants are read from ``styles.py`` — nothing is hardcoded
here (single source of truth).

Qt imports are deferred to method bodies so the module can be imported
in headless test environments without crashing.
"""

from __future__ import annotations

from typing import Any, List, Tuple

from ..enums import ToolType
from ..models import AngleModel, ArrowModel, ROICircleModel, ROIRectModel, RulerModel, TextModel, ToolModel, TwoLineAngleModel
from .. import styles
from .base import AbstractToolRenderer, RenderContext


class QPainterToolRenderer(AbstractToolRenderer):
    """Render tool annotations via QPainter."""

    # ── public API ───────────────────────────────────────────────────

    def render_tool(
        self,
        ctx: RenderContext,
        painter: Any,
        model: ToolModel,
    ) -> None:
        if model.tool_type == ToolType.RULER:
            self._render_ruler(ctx, painter, model)
        elif model.tool_type == ToolType.ANGLE:
            self._render_angle(ctx, painter, model)
        elif model.tool_type == ToolType.TWO_LINE_ANGLE:
            self._render_two_line_angle(ctx, painter, model)
        elif model.tool_type == ToolType.ROI_RECT:
            self._render_roi_rect(ctx, painter, model)
        elif model.tool_type == ToolType.ROI_CIRCLE:
            self._render_roi_circle(ctx, painter, model)
        elif model.tool_type == ToolType.ARROW:
            self._render_arrow(ctx, painter, model)
        elif model.tool_type == ToolType.TEXT:
            self._render_text(ctx, painter, model)

    def render_preview(
        self,
        ctx: RenderContext,
        painter: Any,
        tool_type: ToolType,
        points_image: List[Tuple[float, float]],
        cursor_image: Tuple[float, float],
    ) -> None:
        if tool_type == ToolType.RULER:
            self._render_ruler_preview(ctx, painter, points_image, cursor_image)
        elif tool_type in (ToolType.ANGLE, ToolType.TWO_LINE_ANGLE):
            self._render_multipoint_preview(ctx, painter, tool_type, points_image, cursor_image)
        elif tool_type == ToolType.ROI_RECT:
            self._render_roi_rect_preview(ctx, painter, points_image, cursor_image)
        elif tool_type == ToolType.ROI_CIRCLE:
            self._render_roi_circle_preview(ctx, painter, points_image, cursor_image)
        elif tool_type == ToolType.ARROW:
            self._render_ruler_preview(ctx, painter, points_image, cursor_image)  # same preview as ruler

    # ── ruler ────────────────────────────────────────────────────────

    def _render_ruler(
        self,
        ctx: RenderContext,
        painter: Any,
        model: RulerModel,
    ) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QFont, QPen

        if len(model.points_image) < 2:
            return

        p1_img = model.points_image[0]
        p2_img = model.points_image[1]
        p1w = ctx.coord.image_to_widget(*p1_img)
        p2w = ctx.coord.image_to_widget(*p2_img)

        color = QColor(*styles.RULER_COLOR)
        selected_extra = styles.SELECTION_HIGHLIGHT_WIDTH if model.is_selected else 0
        line_w = styles.RULER_LINE_WIDTH + selected_extra

        # ---- line ----
        pen = QPen(color, line_w)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(color)
        painter.drawLine(QPointF(*p1w), QPointF(*p2w))

        # ---- endpoints (filled circles) ----
        r = styles.RULER_ENDPOINT_SIZE / 2.0
        painter.drawEllipse(QPointF(*p1w), r, r)
        painter.drawEllipse(QPointF(*p2w), r, r)

        # ---- label ----
        if model.distance_mm is not None:
            label = styles.LABEL_FORMAT_DISTANCE.format(model.distance_mm)
            font = QFont(
                styles.LABEL_FONT_FAMILY,
                styles.LABEL_FONT_SIZE,
            )
            font.setBold(styles.LABEL_FONT_BOLD)
            painter.setFont(font)
            # Position label near midpoint, offset slightly upward
            mx = (p1w[0] + p2w[0]) / 2.0
            my = (p1w[1] + p2w[1]) / 2.0 - 10
            painter.drawText(QPointF(mx, my), label)

    def _render_ruler_preview(
        self,
        ctx: RenderContext,
        painter: Any,
        points_image: List[Tuple[float, float]],
        cursor_image: Tuple[float, float],
    ) -> None:
        """Rubber-band dashed line from first point to cursor."""
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QColor, QPen

        if not points_image:
            return

        p1w = ctx.coord.image_to_widget(*points_image[0])
        cw = ctx.coord.image_to_widget(*cursor_image)

        color = QColor(*styles.RULER_COLOR)
        pen = QPen(color, styles.RULER_LINE_WIDTH, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(QPointF(*p1w), QPointF(*cw))

        # First endpoint dot
        painter.setBrush(color)
        r = styles.RULER_ENDPOINT_SIZE / 2.0
        painter.drawEllipse(QPointF(*p1w), r, r)

    # ── angle (3-point) ──────────────────────────────────────────

    def _render_angle(
        self,
        ctx: RenderContext,
        painter: Any,
        model: AngleModel,
    ) -> None:
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QColor, QFont, QPen
        import math

        if len(model.points_image) < 3:
            return

        pts_w = [ctx.coord.image_to_widget(*p) for p in model.points_image]
        p1w, vw, p3w = pts_w

        color = QColor(*styles.ANGLE_COLOR)
        selected_extra = styles.SELECTION_HIGHLIGHT_WIDTH if model.is_selected else 0
        line_w = styles.ANGLE_LINE_WIDTH + selected_extra

        pen = QPen(color, line_w)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(color)

        # Two lines: vertex→p1, vertex→p3
        painter.drawLine(QPointF(*vw), QPointF(*p1w))
        painter.drawLine(QPointF(*vw), QPointF(*p3w))

        # Endpoint dots
        r = styles.ANGLE_POINT_SIZE / 2.0
        for pw in pts_w:
            painter.drawEllipse(QPointF(*pw), r, r)

        # Arc at vertex
        arc_radius = 30.0
        ang1 = math.degrees(math.atan2(-(p1w[1] - vw[1]), p1w[0] - vw[0]))
        ang3 = math.degrees(math.atan2(-(p3w[1] - vw[1]), p3w[0] - vw[0]))
        span = ang3 - ang1
        # Normalize span to [-180, 180]
        while span > 180:
            span -= 360
        while span < -180:
            span += 360

        painter.setBrush(QColor(0, 0, 0, 0))  # no fill
        arc_rect = QRectF(
            vw[0] - arc_radius, vw[1] - arc_radius,
            arc_radius * 2, arc_radius * 2,
        )
        # QPainter.drawArc uses 1/16th of a degree
        painter.drawArc(arc_rect, int(ang1 * 16), int(span * 16))

        # Label
        label = styles.LABEL_FORMAT_ANGLE.format(model.angle_degrees)
        font = QFont(styles.LABEL_FONT_FAMILY, styles.LABEL_FONT_SIZE)
        font.setBold(styles.LABEL_FONT_BOLD)
        painter.setFont(font)
        # Position label along the bisector of the arc
        bisect_ang = math.radians(ang1 + span / 2.0)
        lx = vw[0] + (arc_radius + 15) * math.cos(bisect_ang)
        ly = vw[1] - (arc_radius + 15) * math.sin(bisect_ang)
        painter.drawText(QPointF(lx, ly), label)

    # ── two-line angle (4-point) ──────────────────────────────────

    def _render_two_line_angle(
        self,
        ctx: RenderContext,
        painter: Any,
        model: TwoLineAngleModel,
    ) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QFont, QPen

        if len(model.points_image) < 4:
            return

        pts_w = [ctx.coord.image_to_widget(*p) for p in model.points_image]
        a1w, a2w, b1w, b2w = pts_w

        color = QColor(*styles.TWO_LINE_ANGLE_COLOR)
        selected_extra = styles.SELECTION_HIGHLIGHT_WIDTH if model.is_selected else 0
        line_w = styles.TWO_LINE_ANGLE_LINE_WIDTH + selected_extra

        pen = QPen(color, line_w)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(color)

        # Two lines
        painter.drawLine(QPointF(*a1w), QPointF(*a2w))
        painter.drawLine(QPointF(*b1w), QPointF(*b2w))

        # Endpoint dots
        r = styles.ANGLE_POINT_SIZE / 2.0
        for pw in pts_w:
            painter.drawEllipse(QPointF(*pw), r, r)

        # Label at midpoint of the two lines' midpoints
        label = styles.LABEL_FORMAT_ANGLE.format(model.angle_degrees)
        font = QFont(styles.LABEL_FONT_FAMILY, styles.LABEL_FONT_SIZE)
        font.setBold(styles.LABEL_FONT_BOLD)
        painter.setFont(font)
        mid_a = ((a1w[0] + a2w[0]) / 2.0, (a1w[1] + a2w[1]) / 2.0)
        mid_b = ((b1w[0] + b2w[0]) / 2.0, (b1w[1] + b2w[1]) / 2.0)
        lx = (mid_a[0] + mid_b[0]) / 2.0
        ly = (mid_a[1] + mid_b[1]) / 2.0 - 10
        painter.drawText(QPointF(lx, ly), label)

    # ── multi-point preview (shared for angle tools) ────────────────

    def _render_multipoint_preview(
        self,
        ctx: RenderContext,
        painter: Any,
        tool_type: ToolType,
        points_image: List[Tuple[float, float]],
        cursor_image: Tuple[float, float],
    ) -> None:
        """Dashed lines between placed points + cursor."""
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QColor, QPen

        if not points_image:
            return

        if tool_type == ToolType.TWO_LINE_ANGLE:
            color = QColor(*styles.TWO_LINE_ANGLE_COLOR)
            line_w = styles.TWO_LINE_ANGLE_LINE_WIDTH
        else:
            color = QColor(*styles.ANGLE_COLOR)
            line_w = styles.ANGLE_LINE_WIDTH

        solid_pen = QPen(color, line_w)
        solid_pen.setCosmetic(True)
        dash_pen = QPen(color, line_w, Qt.PenStyle.DashLine)
        dash_pen.setCosmetic(True)

        pts_w = [ctx.coord.image_to_widget(*p) for p in points_image]
        cw = ctx.coord.image_to_widget(*cursor_image)

        # Draw solid lines between already-placed points
        for i in range(len(pts_w) - 1):
            painter.setPen(solid_pen)
            painter.drawLine(QPointF(*pts_w[i]), QPointF(*pts_w[i + 1]))

        # Dashed line from last placed point to cursor
        painter.setPen(dash_pen)
        painter.drawLine(QPointF(*pts_w[-1]), QPointF(*cw))

        # Dots on placed points
        painter.setBrush(color)
        r = styles.ANGLE_POINT_SIZE / 2.0
        for pw in pts_w:
            painter.drawEllipse(QPointF(*pw), r, r)

    # ── ROI Rect ─────────────────────────────────────────────────────

    def _render_roi_rect(
        self,
        ctx: RenderContext,
        painter: Any,
        model: ROIRectModel,
    ) -> None:
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QColor, QFont, QPen

        if len(model.points_image) < 2:
            return

        p1w = ctx.coord.image_to_widget(*model.points_image[0])
        p2w = ctx.coord.image_to_widget(*model.points_image[1])

        color = QColor(*styles.ROI_COLOR)
        selected_extra = styles.SELECTION_HIGHLIGHT_WIDTH if model.is_selected else 0
        hover_extra = 1 if (ctx.hovered_model is model) else 0
        line_w = styles.ROI_LINE_WIDTH + selected_extra + hover_extra

        pen = QPen(color, line_w)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(0, 0, 0, 0))  # no fill (wireframe)

        x1, y1 = p1w
        x2, y2 = p2w
        rect = QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
        painter.drawRect(rect)

        # Stats label — drawn below the ROI box, centred horizontally
        if model.stats is not None:
            lines = [
                f"Mean: {model.stats.mean:.1f}  SD: {model.stats.std:.1f}",
                f"Min: {model.stats.min_val:.0f}  Max: {model.stats.max_val:.0f}",
                f"Area: {model.stats.area_cm2:.2f} cm²",
            ]
        else:
            lines = ["ROI"]
        font = QFont(styles.LABEL_FONT_FAMILY, styles.LABEL_FONT_SIZE - 2)
        font.setBold(styles.LABEL_FONT_BOLD)
        painter.setFont(font)
        painter.setPen(color)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(font)
        line_h = fm.height() + 2
        base_x = (min(x1, x2) + max(x1, x2)) / 2.0
        base_y = max(y1, y2) + line_h
        for i, line in enumerate(lines):
            tw = fm.horizontalAdvance(line)
            painter.drawText(QPointF(base_x - tw / 2.0, base_y + i * line_h), line)

    def _render_roi_rect_preview(
        self,
        ctx: RenderContext,
        painter: Any,
        points_image: List[Tuple[float, float]],
        cursor_image: Tuple[float, float],
    ) -> None:
        from PySide6.QtCore import QPointF, QRectF, Qt
        from PySide6.QtGui import QColor, QPen

        if not points_image:
            return

        color = QColor(*styles.ROI_COLOR)
        pen = QPen(color, styles.ROI_LINE_WIDTH, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(0, 0, 0, 0))

        p1w = ctx.coord.image_to_widget(*points_image[0])
        cw = ctx.coord.image_to_widget(*cursor_image)
        x1, y1 = p1w
        x2, y2 = cw
        rect = QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
        painter.drawRect(rect)

    # ── ROI Circle ───────────────────────────────────────────────────

    def _render_roi_circle(
        self,
        ctx: RenderContext,
        painter: Any,
        model: ROICircleModel,
    ) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QFont, QPen

        if len(model.points_image) < 2:
            return

        cw = ctx.coord.image_to_widget(*model.points_image[0])  # center
        ew = ctx.coord.image_to_widget(*model.points_image[1])  # edge

        import math
        radius_w = math.sqrt((ew[0] - cw[0]) ** 2 + (ew[1] - cw[1]) ** 2)

        color = QColor(*styles.CIRCLE_ROI_COLOR)
        selected_extra = styles.SELECTION_HIGHLIGHT_WIDTH if model.is_selected else 0
        hover_extra = 1 if (ctx.hovered_model is model) else 0
        line_w = styles.CIRCLE_ROI_LINE_WIDTH + selected_extra + hover_extra

        pen = QPen(color, line_w)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(0, 0, 0, 0))  # no fill

        center_pt = QPointF(*cw)
        painter.drawEllipse(center_pt, radius_w, radius_w)

        # Handles at center and edge point
        painter.setBrush(color)
        hr = styles.CIRCLE_ROI_HANDLE_SIZE / 2.0
        painter.drawEllipse(center_pt, hr, hr)
        painter.drawEllipse(QPointF(*ew), hr, hr)

        # Stats label — drawn below the circle, centred horizontally
        if model.stats is not None:
            lines = [
                f"Mean: {model.stats.mean:.1f}  SD: {model.stats.std:.1f}",
                f"Min: {model.stats.min_val:.0f}  Max: {model.stats.max_val:.0f}",
                f"Area: {model.stats.area_cm2:.2f} cm²",
            ]
        else:
            lines = ["Circle ROI"]
        font = QFont(styles.LABEL_FONT_FAMILY, styles.LABEL_FONT_SIZE - 2)
        font.setBold(styles.LABEL_FONT_BOLD)
        painter.setFont(font)
        painter.setPen(color)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(font)
        line_h = fm.height() + 2
        base_x = cw[0]
        base_y = cw[1] + radius_w + line_h
        for i, line in enumerate(lines):
            tw = fm.horizontalAdvance(line)
            painter.drawText(QPointF(base_x - tw / 2.0, base_y + i * line_h), line)

    def _render_roi_circle_preview(
        self,
        ctx: RenderContext,
        painter: Any,
        points_image: List[Tuple[float, float]],
        cursor_image: Tuple[float, float],
    ) -> None:
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QColor, QPen

        if not points_image:
            return

        color = QColor(*styles.CIRCLE_ROI_COLOR)
        pen = QPen(color, styles.CIRCLE_ROI_LINE_WIDTH, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(0, 0, 0, 0))

        cw = ctx.coord.image_to_widget(*points_image[0])
        ew = ctx.coord.image_to_widget(*cursor_image)

        import math
        radius_w = math.sqrt((ew[0] - cw[0]) ** 2 + (ew[1] - cw[1]) ** 2)
        painter.drawEllipse(QPointF(*cw), radius_w, radius_w)

    # ── Arrow ────────────────────────────────────────────────────────

    def _render_arrow(
        self,
        ctx: RenderContext,
        painter: Any,
        model: ArrowModel,
    ) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QFont, QPen, QPolygonF
        import math

        if len(model.points_image) < 2:
            return

        tail_w = ctx.coord.image_to_widget(*model.points_image[0])
        head_w = ctx.coord.image_to_widget(*model.points_image[1])

        color = QColor(*styles.ARROW_COLOR)
        selected_extra = styles.SELECTION_HIGHLIGHT_WIDTH if model.is_selected else 0
        line_w = styles.ARROW_LINE_WIDTH + selected_extra

        pen = QPen(color, line_w)
        pen.setCosmetic(True)
        painter.setPen(pen)

        # Shaft
        painter.drawLine(QPointF(*tail_w), QPointF(*head_w))

        # Arrowhead triangle at head
        dx = head_w[0] - tail_w[0]
        dy = head_w[1] - tail_w[1]
        length = math.sqrt(dx * dx + dy * dy)
        if length < 1e-6:
            return

        # Unit direction
        ux, uy = dx / length, dy / length
        # Perpendicular
        px, py = -uy, ux

        h = styles.ARROW_HEAD_HEIGHT
        hw = h * styles.ARROW_HEAD_WIDTH_RATIO

        # Triangle points
        tip = QPointF(*head_w)
        left = QPointF(
            head_w[0] - ux * h + px * hw / 2,
            head_w[1] - uy * h + py * hw / 2,
        )
        right = QPointF(
            head_w[0] - ux * h - px * hw / 2,
            head_w[1] - uy * h - py * hw / 2,
        )

        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([tip, left, right]))

        # Optional text label
        if model.text:
            font = QFont(styles.LABEL_FONT_FAMILY, styles.LABEL_FONT_SIZE)
            font.setBold(styles.LABEL_FONT_BOLD)
            painter.setFont(font)
            painter.setPen(color)
            mid_x = (tail_w[0] + head_w[0]) / 2.0
            mid_y = (tail_w[1] + head_w[1]) / 2.0 - 10
            painter.drawText(QPointF(mid_x, mid_y), model.text)

    # ── Text annotation ──────────────────────────────────────────────

    def _render_text(
        self,
        ctx: RenderContext,
        painter: Any,
        model: TextModel,
    ) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QFont, QPen

        if not model.points_image:
            return

        pw = ctx.coord.image_to_widget(*model.points_image[0])
        color = QColor(*model.color)

        font = QFont(styles.LABEL_FONT_FAMILY, model.font_size)
        painter.setFont(font)
        painter.setPen(QPen(color))
        painter.drawText(QPointF(*pw), model.text)
