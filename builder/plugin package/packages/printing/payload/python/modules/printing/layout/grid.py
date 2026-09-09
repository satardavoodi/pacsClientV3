"""Grid layout computation for film sheets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from modules.printing.core.models import FilmLayout, FilmSize


@dataclass(frozen=True)
class GridCell:
    """A single cell in film coordinates (inches)."""

    x: float
    y: float
    width: float
    height: float


class GridLayoutEngine:
    """Compute film layout cells based on grid and film size."""
    
    # Grid line thickness in inches
    GRID_LINE_WIDTH_IN = 0.02  # ~1.4 pixels at 72 DPI, ~3 pixels at 150 DPI

    def compute_cells(self, film_size: FilmSize, layout: FilmLayout) -> List[GridCell]:
        """
        Compute grid cells with tight alignment.
        
        Layout formula:
        - Fill entire film (no margins)
        - Grid lines are between cells (thickness = GRID_LINE_WIDTH_IN)
        - Cell sizes calculated: (available_space - grid_lines) / num_cells
        """
        # Grid lines separate cells: (cols-1) vertical lines + (rows-1) horizontal lines
        total_gutter_w = self.GRID_LINE_WIDTH_IN * (layout.cols - 1)
        total_gutter_h = self.GRID_LINE_WIDTH_IN * (layout.rows - 1)

        # Available space: entire film minus grid lines
        available_width = film_size.width_in - total_gutter_w
        available_height = film_size.height_in - total_gutter_h

        # Each cell size
        cell_width = available_width / layout.cols
        cell_height = available_height / layout.rows

        scale = max(1.0, min(1.5, layout.scout_scale))
        scout_width = cell_width * scale if layout.cols > 1 else cell_width
        scout_height = cell_height * scale if layout.rows > 1 else cell_height
        diagnostic_width = ((available_width - scout_width) / (layout.cols - 1)
                            if layout.cols > 1 else cell_width)
        diagnostic_height = ((available_height - scout_height) / (layout.rows - 1)
                             if layout.rows > 1 else cell_height)
        gap = self.GRID_LINE_WIDTH_IN
        cells = [GridCell(0, 0, scout_width, scout_height)]
        # Independent diagnostic boxes: the scout never expands a shared row/column.
        for col in range(layout.cols - 1):
            cells.append(GridCell(scout_width + gap + col * (diagnostic_width + gap),
                                  0, diagnostic_width, diagnostic_height))
        for row in range(layout.rows - 1):
            for col in range(layout.cols):
                cells.append(GridCell(col * (diagnostic_width + gap),
                                      scout_height + gap + row * (diagnostic_height + gap),
                                      diagnostic_width, diagnostic_height))
        return cells

    def border_rectangles(self, film_size: FilmSize, layout: FilmLayout) -> List[GridCell]:
        """Return borders for actual boxes, never full-sheet row/column lines."""
        edges = []
        for cell in self.compute_cells(film_size, layout):
            t = min(self.GRID_LINE_WIDTH_IN, cell.width / 2, cell.height / 2)
            edges.extend((GridCell(cell.x, cell.y, cell.width, t),
                          GridCell(cell.x, cell.y + cell.height - t, cell.width, t),
                          GridCell(cell.x, cell.y, t, cell.height),
                          GridCell(cell.x + cell.width - t, cell.y, t, cell.height)))
        return edges

    def map_image_to_cell(
        self,
        cell: GridCell,
        image_aspect: float,
    ) -> Tuple[float, float, float, float]:
        """Return x, y, width, height fitted to cell while preserving aspect."""
        cell_aspect = cell.width / cell.height if cell.height else 1.0
        if image_aspect >= cell_aspect:
            width = cell.width
            height = width / image_aspect
        else:
            height = cell.height
            width = height * image_aspect
        x = cell.x + (cell.width - width) / 2
        y = cell.y + (cell.height - height) / 2
        return x, y, width, height
