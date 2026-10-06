"""Synthetic region metrics distinguish coverage from particle counts."""
import importlib.util
from pathlib import Path


def module():
    path=Path(__file__).resolve().parents[3]/'tools/eagle_eye/compare_physician_calcification_regions.py'
    spec=importlib.util.spec_from_file_location('region_audit',path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def test_many_particles_cover_one_region_once():
    result=module().counts([[2,2,4,4],[5,5,7,7],[30,30,32,32]],[[0,0,20,20]])
    assert result['regions_with_proposal_center']==1
    assert result['proposal_centers_outside_all_regions']==1
    assert result['regions_with_iou_025']==0


def test_empty_review_and_half_open_boundary():
    m=module()
    assert not m.contains_center([0,0,10,10],[9,9,11,11])
    assert m.counts([[1,1,2,2]],[])['proposal_centers_outside_all_regions']==1
    assert m.overlap([0,0,10,10],[0,0,10,10])==1
