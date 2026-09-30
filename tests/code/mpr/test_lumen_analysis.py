"""Physical geometry, cancellation and source-owned workflow contracts."""
from pathlib import Path
import sys
import threading

import numpy as np
import pytest
import vtk

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "modules/mpr/advanced_3d_slicer/slicer_modules"))
from aipacs_lumen.geometry import sample_path, path_frames, diameter_stenosis, segment_snapshot
from aipacs_lumen.backend import make_surface, cross_section_area, analyze
from aipacs_lumen.routing import validate, MODULES
from modules.mpr.advanced_3d_slicer.workflows import validate_workflow, WORKFLOW_MODULES


def test_seed_classes_preserve_paint_identity_and_do_not_duplicate_on_reopen():
    from aipacs_lumen.seed_presets import ensure_seed_segments, lumen_segment_id, PRESETS

    class Segment:
        def __init__(self, name):
            self.name, self.tags, self.paint = name, {}, object()
        def GetName(self):
            return self.name
        def GetTag(self, key, value):
            if key not in self.tags:
                return False
            value.set(self.tags[key])
            return True
        def SetTag(self, key, value):
            self.tags[key] = value

    class Segmentation:
        def __init__(self):
            self.items = {}
        def GetNumberOfSegments(self):
            return len(self.items)
        def GetNthSegmentID(self, index):
            return list(self.items)[index]
        def GetSegment(self, key):
            return self.items[key]
        def AddEmptySegment(self, identifier, name, color=None):
            identifier = str(len(self.items))
            self.items[identifier] = Segment(name)
            return identifier

    for mode, presets in PRESETS.items():
        segmentation = Segmentation()
        segmentation.AddEmptySegment("", "Unrelated anatomy")
        legacy = segmentation.AddEmptySegment("", presets[0][1])
        paint = segmentation.GetSegment(legacy).paint
        classes, created = ensure_seed_segments(segmentation, mode)
        assert classes["lumen"] == legacy and "lumen" not in created
        segmentation.GetSegment(legacy).name = "My reviewed target"
        again, created = ensure_seed_segments(segmentation, mode)
        assert again == classes and not created
        assert lumen_segment_id(segmentation, mode) == legacy
        assert segmentation.GetSegment(legacy).paint is paint
        assert sum(row[3] for row in presets) >= 2
        del segmentation.items[legacy]
        with pytest.raises(ValueError, match="missing"):
            lumen_segment_id(segmentation, mode)


def test_routes_agree_across_interpreters():
    assert MODULES == WORKFLOW_MODULES
    for value in [None, "", "vascular", "bronchoscopy"]:
        assert validate(value) == value
        assert validate_workflow(value) == (value or None)
    for function in (validate, validate_workflow):
        with pytest.raises(ValueError):
            function("arbitrary_module")


def test_shared_labelmap_snapshot_excludes_other_segment_and_preserves_crop():
    binary = np.array([[[0, 2, 3], [2, 0, 3]]], dtype=np.uint8)
    matrix = np.diag([.5, 2, 3, 1])
    matrix[:3, 3] = [10, 20, 30]
    mask, affine = segment_snapshot(binary, 2, matrix, [4, 6, 7, 8, 9, 9])
    assert mask.sum() == 2
    binary[:] = 0
    assert mask.sum() == 2
    np.testing.assert_allclose(affine[:3, 3], [12, 34, 57])
    np.testing.assert_allclose(matrix[:3, 3], [10, 20, 30])


def test_sampling_physical_length_endpoints_and_duplicate_points():
    points, distance = sample_path([[0, 0, 0], [0, 0, 0], [0, 0, 5], [0, 4, 5]], .5)
    assert distance[-1] == pytest.approx(9)
    np.testing.assert_allclose(points[[0, -1]], [[0, 0, 0], [0, 4, 5]])
    assert np.diff(distance).max() <= .5


@pytest.mark.parametrize("points", [[], [[0, 0, 0]], [[0, 0, 0]] * 2, [[0, 0, 0], [0, np.nan, 1]]])
def test_invalid_routes_are_rejected(points):
    with pytest.raises(ValueError):
        sample_path(points)


def test_camera_frames_do_not_flip_on_smooth_bend():
    theta = np.linspace(0, 1.9 * np.pi, 200)
    points = np.column_stack([10 * np.cos(theta), 10 * np.sin(theta), theta])
    tangent, up = path_frames(points)
    np.testing.assert_allclose(np.linalg.norm(up, axis=1), 1)
    np.testing.assert_allclose((tangent * up).sum(axis=1), 0, atol=1e-12)
    assert (up[1:] * up[:-1]).sum(axis=1).min() > .99


def test_perpendicular_area_ignores_separate_lumen():
    tube = vtk.vtkCylinderSource()
    tube.SetRadius(5)
    tube.SetHeight(30)
    tube.SetResolution(128)
    tube.Update()
    area = cross_section_area(tube.GetOutput(), [0, 0, 0], [0, 1, 0], [0, 0, 1])
    assert area == pytest.approx(np.pi * 25, rel=.001)
    assert np.isnan(cross_section_area(tube.GetOutput(), [30, 0, 0], [0, 1, 0], [0, 0, 1]))


def test_oblique_anisotropic_mask_uses_ras_and_cancellation():
    mask = np.zeros((20, 20, 20), dtype=np.uint8)
    mask[2:18, 7:13, 7:13] = 1
    affine = np.array([[0, -2, 0, 30], [1, 0, 0, -20], [0, 0, 3, 10], [0, 0, 0, 1]], dtype=float)
    points = (np.array([[10, 10, 4, 1], [10, 10, 16, 1]]) @ affine.T)[:, :3]
    result = analyze(mask, affine, None, points, threading.Event())
    assert result["distance"][-1] == pytest.approx(36)
    assert np.median(result["area"]) == pytest.approx(71, abs=.1)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        make_surface(mask, affine, cancel)


def test_stenosis_requires_explicit_positive_reference():
    assert diameter_stenosis(2, 4) == 50
    with pytest.raises(ValueError):
        diameter_stenosis(2, 0)


def test_manual_route_cannot_leave_lumen():
    mask = np.zeros((20, 20, 20), dtype=np.uint8)
    mask[2:18, 7:13, 7:13] = 1
    with pytest.raises(ValueError, match="leaves"):
        analyze(mask, np.eye(4), None, [[10, 10, 4], [15, 15, 10], [10, 10, 16]], threading.Event())


def test_isolated_worker_roundtrip_and_cancel():
    from aipacs_lumen.process import run_isolated
    mask = np.zeros((20, 20, 20), dtype=np.uint8)
    mask[2:18, 7:13, 7:13] = 1
    route = np.array([[10, 10, 4], [10, 10, 16]])
    result = run_isolated(sys.executable, mask, np.eye(4), route, route, threading.Event(), timeout=30)
    assert result["distance"][-1] == pytest.approx(12)
    stop = threading.Event()
    stop.set()
    with pytest.raises(InterruptedError):
        run_isolated(sys.executable, mask, np.eye(4), route, route, stop)
