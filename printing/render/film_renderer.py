"""Film renderer for preview and print output."""

from __future__ import annotations

from typing import List, Dict, Optional, Tuple

from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from printing.core.models import FilmLayout, FilmSize
from printing.layout.grid import GridLayoutEngine
from printing.render.dicom_renderer import RenderedImage


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
        scaled = render.pixmap.scaled(w_px, h_px)
        painter.drawPixmap(x_px, y_px, scaled)

    # Draw white grid lines between cells
    _draw_grid_lines(painter, film_area, layout, dpi, y_offset_in=header_height_in)

    _draw_header(
        painter,
        film_size,
        patient_name=patient_name,
        patient_id=patient_id,
        institution=institution,
        dpi=dpi,
        header_height_in=header_height_in,
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
    institution: str,
    dpi: int,
    header_height_in: float,
) -> None:
    painter.setPen(QColor(240, 240, 240))

    x_px = int(HEADER_PADDING_IN * dpi)
    y_px = int(HEADER_PADDING_IN * dpi)

    font = painter.font()
    font.setPointSize(16)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(x_px, y_px + int(0.28 * dpi), patient_name)

    font.setPointSize(11)
    font.setBold(False)
    painter.setFont(font)
    painter.drawText(x_px, y_px + int(0.52 * dpi), f"Patient ID: {patient_id}")
    painter.drawText(x_px, y_px + int(0.72 * dpi), f"Institution: {institution}")

    separator_y = int(header_height_in * dpi)
    painter.drawLine(0, separator_y, int(film_size.width_in * dpi), separator_y)
