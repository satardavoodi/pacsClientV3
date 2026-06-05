"""Film renderer for preview and print output."""

from __future__ import annotations

from typing import List, Dict, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from modules.printing.core.models import FilmLayout, FilmSize
from modules.printing.layout.grid import GridLayoutEngine
from modules.printing.render.dicom_renderer import RenderedImage, compute_scout_reference_lines


HEADER_HEIGHT_RATIO = 0.10
HEADER_PADDING_IN = 0.25


def film_size_to_pixels(film_size: FilmSize, dpi: int) -> tuple[int, int]:
    width_px = int(film_size.width_in * dpi)
    height_px = int(film_size.height_in * dpi)
    return width_px, height_px


def render_film(
    images: List[RenderedImage],
    film_size: FilmSize,
    layout: FilmLayout,
    dpi: int = 150,
    background: QColor | None = None,
    overlay_info: Optional[Dict[str, str]] = None,
    start_cell_index: int = 0,
    scout_info: Optional[Tuple[str, List[str]]] = None,
) -> QPixmap:
    """
    Render film sheet with images in strict grid layout.
    
    Features:
    - Tight grid alignment (no gaps between images except grid lines)
    - White grid lines between all cells
    - Images centered within cells (preserving aspect ratio)
    """
    width_px, height_px = film_size_to_pixels(film_size, dpi)
    image = QImage(width_px, height_px, QImage.Format_ARGB32)
    bg = background or QColor(0, 0, 0)
    image.fill(bg)

    painter = QPainter(image)

    overlay_info = overlay_info or {}
    patient_name = overlay_info.get("patient_name") or "Unknown Patient"
    patient_id = overlay_info.get("patient_id") or "Unknown ID"
    institution = overlay_info.get("institution") or "Unknown Institution"
    center_name = overlay_info.get("center_name") or institution
    right_line_1 = overlay_info.get("header_right_line_1") or ""
    right_line_2 = overlay_info.get("header_right_line_2") or ""
    font_sizes = {
        "font_patient_name": int(overlay_info.get("font_patient_name", 24) or 24),
        "font_patient_id": int(overlay_info.get("font_patient_id", 18) or 18),
        "font_center_name": int(overlay_info.get("font_center_name", 42) or 42),
        "font_right_block": int(overlay_info.get("font_right_block", 18) or 18),
    }
    sequence_start = int(overlay_info.get("sequence_start") or 1)

    header_height_in = film_size.height_in * HEADER_HEIGHT_RATIO
    film_area_height_in = max(0.1, film_size.height_in - header_height_in)
    film_area = FilmSize(name=film_size.name, width_in=film_size.width_in, height_in=film_area_height_in)

    grid = GridLayoutEngine()
    cells = grid.compute_cells(film_area, layout)

    # Render images into grid cells (optionally offset by start_cell_index)
    for cell_idx, cell in enumerate(cells):
        image_idx = cell_idx - start_cell_index
        if image_idx < 0:
            continue
        if image_idx >= len(images):
            break
        render = images[image_idx]
        x_in, y_in, w_in, h_in = grid.map_image_to_cell(cell, render.aspect)
        x_px = int(x_in * dpi)
        y_px = int((y_in + header_height_in) * dpi)
        w_px = int(w_in * dpi)
        h_px = int(h_in * dpi)
        # Smooth + aspect-preserving scaling — this is the export path that
        # produces the print pixmap, so jagged scaling here would print
        # visibly aliased. Cell sizes already factor in image aspect.
        scaled = render.pixmap.scaled(
            w_px, h_px, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        painter.drawPixmap(x_px, y_px, scaled)

        is_scout_image = scout_info is not None and image_idx == 0
        if not is_scout_image:
            sequence_no = sequence_start + (image_idx - 1 if scout_info is not None else image_idx)
            _draw_image_number_badge(painter, x_px, y_px, sequence_no, dpi)

    # Draw reference lines on scout (first cell)
    if scout_info and images:
        scout_path, slice_paths = scout_info
        rows_s, cols_s, lines = compute_scout_reference_lines(scout_path, slice_paths)
        if rows_s > 0 and cols_s > 0 and lines:
            scout_cell = cells[0] if cells else None
            if scout_cell is not None:
                scout_render = images[0]
                x_in, y_in, w_in, h_in = grid.map_image_to_cell(scout_cell, scout_render.aspect)
                scale_x = w_in / cols_s
                scale_y = h_in / rows_s
                x_offset_px = int(x_in * dpi)
                y_offset_px = int((y_in + header_height_in) * dpi)
                pen = painter.pen()
                pen.setColor(QColor(255, 217, 51))
                pen.setWidth(max(1, int(1 * dpi / 150)))
                painter.setPen(pen)
                # Reference line rules:
                # - Lines positioned by true physical slice position
                # - Displayed numbers = visible slot index (1-based sequential)
                # - Only odd-numbered visible slots are rendered (1, 3, 5, 7, ...)
                for idx, (x0, y0, x1, y1) in enumerate(lines):
                    visible_slot = idx + 1  # 1-based visible slot number
                    if visible_slot % 2 == 0:
                        continue  # Skip even-numbered slots

                    sx0 = x_offset_px + int(x0 * scale_x * dpi)
                    sy0 = y_offset_px + int(y0 * scale_y * dpi)
                    sx1 = x_offset_px + int(x1 * scale_x * dpi)
                    sy1 = y_offset_px + int(y1 * scale_y * dpi)
                    painter.drawLine(sx0, sy0, sx1, sy1)
                    # Place label at 1/3 along the line so it stays inside
                    lx = sx0 + (sx1 - sx0) // 3
                    ly = sy0 + (sy1 - sy0) // 3
                    _draw_scout_line_label(painter, lx, ly, str(visible_slot), dpi)

    # Draw white grid lines between cells
    _draw_grid_lines(painter, film_area, layout, dpi, y_offset_in=header_height_in)

    _draw_header(
        painter,
        film_size,
        patient_name=patient_name,
        patient_id=patient_id,
        center_name=center_name,
        right_line_1=right_line_1,
        right_line_2=right_line_2,
        dpi=dpi,
        header_height_in=header_height_in,
        font_sizes=font_sizes,
    )

    painter.end()
    return QPixmap.fromImage(image)


def _draw_grid_lines(
    painter: QPainter,
    film_size: FilmSize,
    layout: FilmLayout,
    dpi: int,
    y_offset_in: float = 0.0,
) -> None:
    """
    Draw white grid lines between all cells.
    
    Grid lines are drawn:
    - (rows + 1) horizontal lines (top/bottom + between rows)
    - (cols + 1) vertical lines (left/right + between cols)
    """
    grid = GridLayoutEngine()
    cells = grid.compute_cells(film_size, layout)

    grid_line_px = int(grid.GRID_LINE_WIDTH_IN * dpi)
    if grid_line_px < 1:
        grid_line_px = 1

    painter.setPen(QColor(255, 255, 255))
    painter.setBrush(QColor(255, 255, 255))

    width_px = int(film_size.width_in * dpi)
    height_px = int(film_size.height_in * dpi)
    y_offset_px = int(y_offset_in * dpi)

    cell_w = cells[0].width if cells else film_size.width_in
    cell_h = cells[0].height if cells else film_size.height_in
    line_in = grid.GRID_LINE_WIDTH_IN

    # Vertical grid lines (including left/right borders)
    x_positions_in = [0.0]
    for col in range(1, layout.cols):
        x_positions_in.append(col * cell_w + (col - 1) * line_in)
    x_positions_in.append(max(0.0, film_size.width_in - line_in))

    for x_in in x_positions_in:
        x_px = int(x_in * dpi)
        painter.fillRect(x_px, y_offset_px, grid_line_px, height_px, QColor(255, 255, 255))

    # Horizontal grid lines (including top/bottom borders)
    y_positions_in = [0.0]
    for row in range(1, layout.rows):
        y_positions_in.append(row * cell_h + (row - 1) * line_in)
    y_positions_in.append(max(0.0, film_size.height_in - line_in))

    for y_in in y_positions_in:
        y_px = int(y_in * dpi)
        painter.fillRect(0, y_offset_px + y_px, width_px, grid_line_px, QColor(255, 255, 255))


def _draw_header(
    painter: QPainter,
    film_size: FilmSize,
    *,
    patient_name: str,
    patient_id: str,
    center_name: str,
    right_line_1: str,
    right_line_2: str,
    dpi: int,
    header_height_in: float,
    font_sizes: dict | None = None,
) -> None:
    fs = font_sizes or {}
    fs_pname = int(fs.get("font_patient_name", 24))
    fs_pid = int(fs.get("font_patient_id", 18))
    fs_center = int(fs.get("font_center_name", 42))
    fs_right = int(fs.get("font_right_block", 18))

    # Scale user pt sizes for export DPI (user sees them at ~110 dpi preview)
    dpi_scale = dpi / 110.0

    painter.setPen(QColor(240, 240, 240))

    width_px = int(film_size.width_in * dpi)
    x_left = int(HEADER_PADDING_IN * dpi)
    x_right = width_px - int(HEADER_PADDING_IN * dpi)
    y_top = int(HEADER_PADDING_IN * dpi)
    row_gap = int(0.24 * dpi)

    # Left block: patient details (2 lines max)
    font = painter.font()
    font.setPointSize(max(8, int(fs_pname * dpi_scale)))
    font.setBold(True)
    painter.setFont(font)
    fm = painter.fontMetrics()
    painter.drawText(x_left, y_top + fm.ascent(), patient_name)
    name_height = fm.height()

    font.setPointSize(max(8, int(fs_pid * dpi_scale)))
    font.setBold(False)
    painter.setFont(font)
    fm = painter.fontMetrics()
    painter.drawText(x_left, y_top + name_height + fm.ascent(), f"ID: {patient_id}")

    # Center block: center/institute name (single centered line)
    font.setPointSize(max(10, int(fs_center * dpi_scale)))
    font.setBold(True)
    painter.setFont(font)
    center_rect_x = int(width_px * 0.28)
    center_rect_w = int(width_px * 0.44)
    center_rect_h = int(header_height_in * dpi) - int(HEADER_PADDING_IN * dpi)
    painter.drawText(center_rect_x, y_top, center_rect_w, center_rect_h, Qt.AlignHCenter | Qt.AlignVCenter, center_name)

    # Right block: address/contact (2 lines max)
    font.setPointSize(max(8, int(fs_right * dpi_scale)))
    font.setBold(False)
    painter.setFont(font)
    fm_r = painter.fontMetrics()
    right_row_h = fm_r.height()
    painter.drawText(0, y_top + fm_r.ascent(), x_right - int(0.04 * dpi), right_row_h, Qt.AlignRight | Qt.AlignVCenter, right_line_1)
    painter.drawText(0, y_top + right_row_h + fm_r.ascent(), x_right - int(0.04 * dpi), right_row_h, Qt.AlignRight | Qt.AlignVCenter, right_line_2)

    separator_y = int(header_height_in * dpi)
    painter.drawLine(0, separator_y, int(film_size.width_in * dpi), separator_y)


def _draw_image_number_badge(painter: QPainter, x_px: int, y_px: int, number: int, dpi: int) -> None:
    font = painter.font()
    font.setPointSize(max(18, int(22 * dpi / 150)))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(255, 240, 160))
    painter.drawText(x_px + int(0.05 * dpi), y_px + int(0.14 * dpi), str(number))


def _draw_scout_line_label(painter: QPainter, x: int, y: int, label: str, dpi: int) -> None:
    font = painter.font()
    font.setPointSize(max(8, int(10 * dpi / 150)))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(255, 217, 51))
    # Position label centred on the anchor point, slightly above the line
    fm = painter.fontMetrics()
    tw = fm.horizontalAdvance(label)
    th = fm.height()
    painter.drawText(x - tw // 2, y - th // 2, label)
