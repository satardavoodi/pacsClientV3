"""Grid layout computation for film sheets."""

from __future__ import annotations

from dataclasses import dataclass
import math
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
        rows, cols = layout.rows, layout.cols
        count = rows * cols
        merged = layout.scout_scale > 1
        if merged:
            # The requested count is diagnostic images; the scout consumes four extra slots.
            candidates = []
            for candidate_cols in range(2, count + 5):
                candidate_rows = max(2, math.ceil((count + 4) / candidate_cols))
                excess = candidate_rows * candidate_cols - (count + 4)
                aspect = (film_size.width_in / candidate_cols) / (film_size.height_in / candidate_rows)
                candidates.append(((excess, abs(math.log(aspect))), candidate_rows, candidate_cols))
            _, rows, cols = min(candidates)
        gap = self.GRID_LINE_WIDTH_IN
        width = (film_size.width_in - gap * (cols - 1)) / cols
        height = (film_size.height_in - gap * (rows - 1)) / rows
        cells = []
        if merged:
            cells.append(GridCell(0, 0, 2 * width + gap, 2 * height + gap))
        for row in range(rows):
            for col in range(cols):
                if merged and row < 2 and col < 2:
                    continue
                cells.append(GridCell(col * (width + gap), row * (height + gap), width, height))
        return cells[:count + 1] if merged else cells

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
