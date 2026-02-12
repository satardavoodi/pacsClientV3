"""
Test script to visualize tight grid layout with grid lines.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from printing.core.models import FilmLayout, FilmSize
from printing.layout.grid import GridLayoutEngine


def test_grid_layout():
    """Test grid layout computation."""
    print("\n" + "="*80)
    print("🔬 PRINTING GRID LAYOUT TEST")
    print("="*80 + "\n")
    
    # Test cases
    test_cases = [
        ("2x2", FilmSize("14x17", 14.0, 17.0), FilmLayout(2, 2)),
        ("3x3", FilmSize("14x17", 14.0, 17.0), FilmLayout(3, 3)),
        ("4x4", FilmSize("14x17", 14.0, 17.0), FilmLayout(4, 4)),
        ("1x1", FilmSize("14x17", 14.0, 17.0), FilmLayout(1, 1)),
    ]
    
    for name, film_size, layout in test_cases:
        print(f"📐 Layout: {name}")
        print(f"   Film size: {film_size.width_in}\" x {film_size.height_in}\"")
        print(f"   Grid: {layout.rows} rows x {layout.cols} cols")
        
        grid = GridLayoutEngine()
        cells = grid.compute_cells(film_size, layout)
        
        print(f"   Grid line width: {grid.GRID_LINE_WIDTH_IN}\" ({grid.GRID_LINE_WIDTH_IN * 72:.1f} px @ 72 DPI)")
        print(f"   Cell size: {cells[0].width:.4f}\" x {cells[0].height:.4f}\"")
        print(f"   Total cells: {len(cells)}")
        
        # Verify no overlap/gaps
        for row in range(layout.rows):
            for col in range(layout.cols):
                idx = row * layout.cols + col
                cell = cells[idx]
                
                # Check bounds
                x_max = cell.x + cell.width
                y_max = cell.y + cell.height
                
                # Verify within film
                assert cell.x >= 0, f"Cell {idx} x < 0"
                assert cell.y >= 0, f"Cell {idx} y < 0"
                assert x_max <= film_size.width_in + 0.001, f"Cell {idx} x_max > film width"
                assert y_max <= film_size.height_in + 0.001, f"Cell {idx} y_max > film height"
                
                # Check adjacent cells
                if col < layout.cols - 1:
                    next_cell = cells[idx + 1]
                    expected_gap = grid.GRID_LINE_WIDTH_IN
                    actual_gap = next_cell.x - x_max
                    assert abs(actual_gap - expected_gap) < 0.0001, \
                        f"Cell {idx} to {idx+1} gap mismatch: {actual_gap:.4f}\" vs {expected_gap:.4f}\""
                
                if row < layout.rows - 1:
                    next_cell = cells[(row + 1) * layout.cols + col]
                    expected_gap = grid.GRID_LINE_WIDTH_IN
                    actual_gap = next_cell.y - y_max
                    assert abs(actual_gap - expected_gap) < 0.0001, \
                        f"Cell {idx} to row+1 gap mismatch: {actual_gap:.4f}\" vs {expected_gap:.4f}\""
        
        print(f"   ✅ Layout valid (no gaps, tight alignment)")
        print()
    
    print("="*80)
    print("✅ All grid layouts valid")
    print("="*80 + "\n")


if __name__ == "__main__":
    test_grid_layout()
