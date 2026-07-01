# -*- coding: utf-8 -*-
"""Guard: Dental Imaging ortho geometry + stack navigation (P2, 2026-06-23).

Pins the fix for mis-oriented ortho views (axial flipped, L/R wrong, head/nose
inverted) + the new stack navigation:
 * `core/ortho_orientation.py` derives, from the volume's OWN DirectionMatrix (the
   standard-MPR geometry contract), the per-view through/h/v axis + flips + L/R/A/P/H/F
   labels in the radiological convention — REUSED, never recomputed. Pure (stdlib),
   unit-tested against the real CBCT matrix + flipped variants.
 * the workspace renders oriented slices and adds a per-view slider + mouse-wheel +
   slice index (synchronized), no VTK render window.
"""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
ORIENT = REPO / "modules" / "dental_imaging" / "core" / "ortho_orientation.py"
WORKSPACE = REPO / "modules" / "dental_imaging" / "workspace.py"


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated mirror of {p.name}; run on Windows")
    return b.decode("utf-8", "replace").replace("\r\n", "\n")


def _load():
    spec = importlib.util.spec_from_file_location("dental_ortho_orientation", ORIENT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# real CBCT series 202 DirectionMatrix (diag(1,-1,1)): x->L, y->A(-P), z->S
_M_202 = [1, 0, 0, 0,  0, -1, 0, 0,  0, 0, 1, 0,  0, 0, 0, 1]
_M_IDENT = [1, 0, 0, 0,  0, 1, 0, 0,  0, 0, 1, 0,  0, 0, 0, 1]
_M_ZINF = [1, 0, 0, 0,  0, -1, 0, 0,  0, 0, -1, 0,  0, 0, 0, 1]


def test_radiological_labels_match_standard_mpr_convention():
    o = _load()
    ax = o.plan_view(_M_202, "axial")["labels"]
    assert ax == {"top": "A", "bottom": "P", "left": "R", "right": "L"}     # A-top, R-left
    sag = o.plan_view(_M_202, "sagittal")["labels"]
    assert sag == {"top": "S", "bottom": "I", "left": "A", "right": "P"}    # S-top, A-left (face left)
    cor = o.plan_view(_M_202, "coronal")["labels"]
    assert cor == {"top": "S", "bottom": "I", "left": "R", "right": "L"}    # S-top, R-left


def test_labels_anatomically_stable_across_matrices():
    o = _load()
    # identity and Z-inferior must still produce anatomically-correct letters
    for m in (_M_IDENT, _M_ZINF):
        assert o.plan_view(m, "axial")["labels"]["top"] == "A"
        assert o.plan_view(m, "axial")["labels"]["left"] == "R"
        assert o.plan_view(m, "sagittal")["labels"]["top"] == "S"
        assert o.plan_view(m, "coronal")["labels"]["top"] == "S"


def test_plan_axes_are_a_valid_permutation():
    o = _load()
    for view in ("axial", "coronal", "sagittal"):
        p = o.plan_view(_M_202, view)
        assert sorted([p["through"], p["h"], p["v"]]) == [0, 1, 2]
        assert isinstance(p["flip_h"], bool) and isinstance(p["flip_v"], bool)


def test_axial_through_is_S_axis_for_axial_acq():
    o = _load()
    # axial-acquired: through-plane axis is the volume axis pointing Superior (z, vtk 2)
    assert o.plan_view(_M_202, "axial")["through"] == 2
    assert o.plan_view(_M_202, "sagittal")["through"] == 0   # L/R axis
    assert o.plan_view(_M_202, "coronal")["through"] == 1    # A/P axis


def test_axis_patient_dirs_reads_columns():
    o = _load()
    dirs = o.axis_patient_dirs(_M_202)
    assert dirs[0] == (1.0, 0.0, 0.0)    # x -> +L
    assert dirs[1] == (0.0, -1.0, 0.0)   # y -> +A (-P)
    assert dirs[2] == (0.0, 0.0, 1.0)    # z -> +S
    # None / short -> identity
    assert o.axis_patient_dirs(None)[0] == (1.0, 0.0, 0.0)


# --- workspace wiring: orientation + navigation source-pins ----------------
def test_workspace_uses_orientation_and_nav():
    s = _read(WORKSPACE)
    assert "from .core.ortho_orientation import plan_view" in s
    assert "AIPACS_DENTAL_ORTHO_ORIENT" in s and "AIPACS_DENTAL_STACK_NAV" in s
    for sym in ("def _ortho_cell", "def _extract_oriented", "def _render_view",
                "def _on_slider", "def _scroll_view", "def _compose_view",
                "def _update_nav_widgets",
                "def _apply_standard_mpr_static_camera_correction"):
        assert sym in s, f"missing {sym}"
    assert 'view in ("coronal", "sagittal")' in s
    assert "QSlider" in s                  # sidebar/slider navigation
    assert "angleDelta()" in s             # mouse-wheel scroll
    assert "/ {count}" in s or "/ {" in s   # slice index display
    # still static QImage — no VTK render window introduced
    assert "QVTKRenderWindowInteractor" not in s and "vtkImageViewer2" not in s
