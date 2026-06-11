"""MPR geometry regression guards (headless).

Two layers, both numpy/stdlib only (no VTK, no Qt):

1. Named-case plane routing — the cases that historically regressed must land in
   the correct reconstructed pane: axial input -> axial box, sagittal -> sagittal,
   coronal -> coronal, including oblique shoulder MR (Z/Y/X dominant) and brain MR.

2. Source-marker guard — the corrected-geometry symbols must still be present in
   the geometry source files. This mirrors the build-time PYZ gate
   (builder/audit/scripts/verify_mpr_in_pyz.py) so a source deletion is caught in
   CI, while the PYZ gate catches a stale *packaged* build. Together they close the
   3.2.x "source correct but installed build regressed" gap.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from modules.mpr.zeta_mpr._mpr_canonicalize import classify_acquisition_plane

# ---------------------------------------------------------------------------
# 1. Named-case plane routing
# ---------------------------------------------------------------------------
# Canonical orthogonal acquisitions.
IOP_CT_AXIAL = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
IOP_BRAIN_AXIAL = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
IOP_BRAIN_SAGITTAL = [0.0, 1.0, 0.0, 0.0, 0.0, -1.0]
IOP_BRAIN_CORONAL = [1.0, 0.0, 0.0, 0.0, 0.0, -1.0]
IOP_PURE_SAGITTAL = [0.0, 1.0, 0.0, 0.0, 0.0, -1.0]
# Oblique shoulder MR (44534, measured on disk) — dominant axis still resolves.
IOP_SHOULDER_OBLIQUE_AXIAL = [0.883, -0.014, -0.469, 0.0, 0.9995, -0.031]
IOP_SHOULDER_OBLIQUE_COR = [0.884, -0.092, -0.459, -0.464, -0.050, -0.884]
IOP_SHOULDER_OBLIQUE_SAG = [-0.018, 0.999, -0.045, -0.461, -0.048, -0.886]


@pytest.mark.parametrize("name,iop,expected", [
    ("ct_axial", IOP_CT_AXIAL, "axial"),
    ("brain_axial", IOP_BRAIN_AXIAL, "axial"),
    ("brain_sagittal", IOP_BRAIN_SAGITTAL, "sagittal"),
    ("brain_coronal", IOP_BRAIN_CORONAL, "coronal"),
    ("pure_sagittal", IOP_PURE_SAGITTAL, "sagittal"),
    ("shoulder_oblique_axial", IOP_SHOULDER_OBLIQUE_AXIAL, "axial"),
    ("shoulder_oblique_coronal", IOP_SHOULDER_OBLIQUE_COR, "coronal"),
    ("shoulder_oblique_sagittal", IOP_SHOULDER_OBLIQUE_SAG, "sagittal"),
])
def test_named_case_plane_routing(name, iop, expected):
    plane, axis, dominance = classify_acquisition_plane(iop)
    assert plane == expected, f"{name}: classified {plane}, expected {expected}"
    assert 0 <= axis <= 2
    assert 0.0 <= dominance <= 1.0


# ---------------------------------------------------------------------------
# 2. Source-marker guard (mirrors the build-time PYZ gate)
# ---------------------------------------------------------------------------
_MPR_VIEWER = (
    Path(__file__).resolve().parents[3]
    / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer"
)

# Keep in lockstep with build_release.MPR_GEOMETRY_PYZ_MARKERS.
SOURCE_MARKERS = {
    "_mpr_orientation.py": ("_view_axes", "_anat_look_axis", "_anatomical_camera"),
    "_mpr_crosshair_render.py": ("_force_crosshair_on_top",),
    "_mpr_views.py": ("_apply_native_plane_interpolation",),
    "widget.py": ("layout_views", "slab_mode"),
}


@pytest.mark.parametrize("filename,markers", list(SOURCE_MARKERS.items()))
def test_geometry_source_markers_present(filename, markers):
    path = _MPR_VIEWER / filename
    assert path.exists(), f"missing geometry source file: {path}"
    text = path.read_text(encoding="utf-8", errors="replace")
    missing = [m for m in markers if m not in text]
    assert not missing, f"{filename}: corrected-geometry markers removed: {missing}"


def test_build_gate_and_source_markers_in_lockstep():
    """The build-time PYZ gate and this source guard must check the same symbols
    so a future edit can't silently drop coverage on one side."""
    build_release = (
        Path(__file__).resolve().parents[3] / "builder" / "build_release.py"
    )
    if not build_release.exists():
        pytest.skip("build_release.py not present in this checkout")
    text = build_release.read_text(encoding="utf-8", errors="replace")
    assert "MPR_GEOMETRY_PYZ_MARKERS" in text
    assert "verify_frozen_mpr_geometry" in text
    for markers in SOURCE_MARKERS.values():
        for m in markers:
            assert m in text, f"build gate missing marker '{m}'"
