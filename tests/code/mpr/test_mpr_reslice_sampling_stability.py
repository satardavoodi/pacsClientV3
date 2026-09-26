"""Synthetic rendered regression for optimized reslice row jumps (OPT-48)."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import vtkmodules.all as vtk

from modules.mpr.zeta_mpr.mpr_viewer._mpr_views import _MprViewsMixin

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("size, zoom", [((320, 240), 1.2), ((960, 720), 2.4)])
def test_reconstructed_scroll_preserves_rendered_stationary_phantom(size, zoom):
    # Isolate the native graphics context so a driver failure cannot kill pytest.
    # Entirely invented geometry; no clinical data or application/database access.
    code = '''
import json
from types import SimpleNamespace
from tools.testing.probe_mpr_render_stationarity import run
from modules.mpr.zeta_mpr.mpr_viewer._mpr_views import _MprViewsMixin
def configure(actor, mapper):
    host = SimpleNamespace(viewers={'coronal': {'actor': actor, 'mapper': mapper}},
                           _view_axes=lambda view: (1, 0, 2))
    _MprViewsMixin._apply_native_plane_interpolation(host)
result = run(64, (-123.45, -67.89, -98.76), (.73, .73, 1.3),
             (320, 240), 1.2, frames=21, configure=configure)
print(json.dumps(result))
'''
    code = code.replace("(320, 240), 1.2", f"{size!r}, {zoom!r}")
    env = dict(os.environ, AIPACS_MPR_STABLE_SCROLL="1")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout.strip().splitlines()[-1])
    assert receipt["changed_pixels_max"] == 0, receipt
    assert receipt["resliced_max_difference"] <= 1, receipt


@pytest.mark.parametrize("native_view", ["axial", "sagittal", "coronal"])
def test_sampling_policy_preserves_geometry_and_native_plane(native_view, monkeypatch):
    monkeypatch.setenv("AIPACS_MPR_STABLE_SCROLL", "1")
    volume = vtk.vtkImageData()
    volume.SetDimensions(8, 9, 10)
    volume.SetOrigin(-12.3, 4.5, 6.7)
    volume.SetSpacing(.7, .9, 1.3)
    viewers = {}
    planes = {}
    for view in ("axial", "sagittal", "coronal"):
        mapper = vtk.vtkImageResliceMapper()
        mapper.SetInputData(volume)
        plane = vtk.vtkPlane()
        plane.SetNormal(.2, .3, .9)
        plane.SetOrigin(1, 2, 3)
        mapper.SetSlicePlane(plane)
        actor = vtk.vtkImageSlice()
        actor.SetMapper(mapper)
        viewers[view] = {"mapper": mapper, "actor": actor}
        planes[view] = plane
    before = (volume.GetOrigin(), volume.GetSpacing(), volume.GetDimensions())
    host = SimpleNamespace(viewers=viewers,
                           _view_axes=lambda view: (2 if view == native_view else 1, 0, 1))
    _MprViewsMixin._apply_native_plane_interpolation(host)
    assert before == (volume.GetOrigin(), volume.GetSpacing(), volume.GetDimensions())
    for view, info in viewers.items():
        mapper = info["mapper"]
        assert mapper.GetSlicePlane() is planes[view]
        assert planes[view].GetNormal() == (.2, .3, .9)
        assert planes[view].GetOrigin() == (1, 2, 3)
        assert mapper.GetResampleToScreenPixels() == 0
        native = view == native_view
        assert info["actor"].GetProperty().GetInterpolationType() == (0 if native else 1)
        assert mapper.GetImageReslice().GetOptimization() == int(native)
