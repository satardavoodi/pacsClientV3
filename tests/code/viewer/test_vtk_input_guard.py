"""Guards for the Eagle-Eye/MG native-crash fix (2026-06-05).

Production frozen-build evidence (other-PC logs): 4× access violations at
``Viewer2D.__init__`` → ``SetInputData(self.image_reslice.GetOutput())`` during
Eagle-Eye mammography series switches — an allocation-failed (empty) reslice
output fed straight into the native call. Contract pinned here:

  1. ``_vtk_image_scalars_valid`` correctly distinguishes empty / scalar-less
     images from real ones (pure CPU vtkImageData — no rendering needed).
  2. ``Viewer2D.__init__`` validates the reslice output BEFORE the native
     SetInputData, falls back to the raw input, and raises a normal Python
     RuntimeError (never the native call) when both are invalid.
  3. ``loading_overlay.hide_overlay``'s fade checks widget liveness before
     touching the (possibly deleted) overlay.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

vtk = pytest.importorskip("vtkmodules.all")

from modules.viewer.advanced.viewer_2d import _vtk_image_scalars_valid  # noqa: E402


def _make_image(with_scalars: bool, dims=(4, 4, 2)):
    img = vtk.vtkImageData()
    img.SetDimensions(*dims)
    if with_scalars:
        img.AllocateScalars(vtk.VTK_SHORT, 1)
    return img


def test_none_is_invalid():
    assert _vtk_image_scalars_valid(None) is False


def test_empty_image_is_invalid():
    # Fresh vtkImageData: dims default to 0 — exactly what a failed
    # reslice Update() leaves behind.
    assert _vtk_image_scalars_valid(vtk.vtkImageData()) is False


def test_dims_without_scalars_is_invalid():
    assert _vtk_image_scalars_valid(_make_image(with_scalars=False)) is False


def test_allocated_image_is_valid():
    assert _vtk_image_scalars_valid(_make_image(with_scalars=True)) is True


def test_non_vtk_object_is_invalid():
    assert _vtk_image_scalars_valid(object()) is False


def test_viewer_init_guard_source_contract():
    src = (_REPO_ROOT / "modules/viewer/advanced/viewer_2d.py").read_text(encoding="utf-8")
    # validation precedes the native call in the non-lazy branch
    i_guard = src.index("_reslice_out = self.image_reslice.GetOutput()")
    i_valid = src.index("_vtk_image_scalars_valid(_reslice_out)")
    i_set = src.index("self.SetInputData(_reslice_out)")
    assert i_guard < i_valid < i_set
    # fallback + clean failure exist
    assert "falling" in src and "back to direct input wiring" in src
    assert "refusing native SetInputData" in src


def test_overlay_fade_liveness_guard_source_contract():
    src = (_REPO_ROOT / "PacsClient/components/loading_overlay.py").read_text(encoding="utf-8")
    i_valid = src.index("shiboken6.isValid(overlay)")
    i_anim = src.index('QPropertyAnimation(overlay, b"windowOpacity")')
    assert i_valid < i_anim
