"""Shared enlarged-scout geometry, independent of clinical data."""
import pytest
from modules.printing.core.models import FilmLayout, FilmSize
from modules.printing.layout.grid import GridLayoutEngine


@pytest.mark.parametrize("rows,cols", [(2,2),(4,4),(5,4),(1,1),(1,4),(4,1)])
def test_enlarged_scout_fits_without_overlap(rows, cols):
    grid = GridLayoutEngine()
    film = FilmSize("A3", 11.69, 14.886)
    base = grid.compute_cells(film, FilmLayout(rows,cols))
    cells = grid.compute_cells(film, FilmLayout(rows,cols,scout_scale=1.5))
    assert len(cells) == len(base)
    if len(cells) > 1:
        for cell in cells[1:]:
            assert cell.width == pytest.approx(cells[1].width)
            assert cell.height == pytest.approx(cells[1].height)
    assert cells[0].width == pytest.approx(base[0].width * (1.5 if cols > 1 else 1))
    assert cells[0].height == pytest.approx(base[0].height * (1.5 if rows > 1 else 1))
    for i,a in enumerate(cells):
        assert a.width > 0 and a.height > 0
        assert a.x+a.width <= film.width_in+1e-9
        assert a.y+a.height <= film.height_in+1e-9
        for b in cells[i+1:]:
            assert min(a.x+a.width,b.x+b.width) <= max(a.x,b.x) or min(a.y+a.height,b.y+b.height) <= max(a.y,b.y)
