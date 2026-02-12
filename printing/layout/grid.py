"""Grid layout computation for film sheets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from printing.core.models import FilmLayout, FilmSize


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

        cells: List[GridCell] = []
        for row in range(layout.rows):
            for col in range(layout.cols):
                # Position: no margin, cells are adjacent with grid lines between
                x = col * (cell_width + self.GRID_LINE_WIDTH_IN)
                y = row * (cell_height + self.GRID_LINE_WIDTH_IN)
                cells.append(GridCell(x=x, y=y, width=cell_width, height=cell_height))
        return cells

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
