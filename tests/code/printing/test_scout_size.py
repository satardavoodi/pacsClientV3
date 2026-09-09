"""Diagnostic capacity excludes the scout."""
import pytest
from modules.printing.core.models import FilmLayout, FilmSize
from modules.printing.layout.grid import GridLayoutEngine

@pytest.mark.parametrize("count", [1,4,16,20,40,200])
def test_scout_does_not_consume_diagnostic_capacity(count):
    grid=GridLayoutEngine(); film=FilmSize("14x17",14,15.3)
    cells=grid.compute_cells(film,FilmLayout(1,count,scout_scale=2))
    assert len(cells)==count+1
    assert cells[0].width==pytest.approx(2*cells[1].width+grid.GRID_LINE_WIDTH_IN)
    assert cells[0].height==pytest.approx(2*cells[1].height+grid.GRID_LINE_WIDTH_IN)
    for i,a in enumerate(cells):
        if i:
            assert a.width==pytest.approx(cells[1].width)
            assert a.height==pytest.approx(cells[1].height)
        assert a.x+a.width<=film.width_in+1e-9
        assert a.y+a.height<=film.height_in+1e-9
        for b in cells[i+1:]:
            assert min(a.x+a.width,b.x+b.width)<=max(a.x,b.x) or min(a.y+a.height,b.y+b.height)<=max(a.y,b.y)

def test_reference_labels_keep_endpoints_midpoint_and_source_numbers():
    from modules.printing.render.dicom_renderer import labeled_reference_lines
    for count,step in [(9,2),(20,5),(49,5),(200,10)]:
        lines=[(0,0,1,1)]*count
        labels=[number for number,line in labeled_reference_lines(lines,21)]
        assert {21,21+(count-1)//2,20+count}.issubset(labels)
        assert 20+step in labels
    lines=[(0,0,1,1),None,(0,0,1,1)]
    assert [n for n,line in labeled_reference_lines(lines,21)]==[21,23]
