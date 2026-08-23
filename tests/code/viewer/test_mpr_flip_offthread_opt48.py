"""Guard tests — OPT-48 Phase 2: MPR L/R flip moved OFF the GUI thread.

**GEOMETRY / RADIOLOGICAL-CANON SAFETY IS THE POINT OF THIS FILE.**

The MPR viewer physically flips the volume along X to produce the radiological
left-right convention every downstream consumer assumes (reslice mappers,
cameras, crosshairs, measurements). Phase 2 does NOT change that: it hoists the
identical `vtkImageFlip` onto the loader's worker thread. These tests prove the
result is byte-for-byte identical to the legacy inline flip — voxels, dims,
spacing, origin AND the DirectionMatrix / ZetaAnatA field data.

If any of these fail, the flip changed and MPR orientation is at risk. Do not
"fix" them by relaxing the comparison.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WIDGET_SRC = ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "widget.py"
TOOLBAR_SRC = (
    ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)


def _vtk():
    try:
        import vtkmodules.all as vtk
        return vtk
    except Exception:
        pytest.skip("VTK not importable in this environment")


def _flip_fn():
    try:
        from modules.mpr.zeta_mpr.mpr_viewer.widget import StandardMPRViewer
        return StandardMPRViewer.build_lr_flipped_volume
    except Exception:
        pytest.skip("StandardMPRViewer not importable (needs VTK + PySide6)")


def _make_volume(vtk, nx=6, ny=5, nz=4, with_field_data=True):
    """Small asymmetric volume: every voxel value encodes its (x,y,z)."""
    img = vtk.vtkImageData()
    img.SetDimensions(nx, ny, nz)
    img.SetSpacing(0.7, 0.8, 1.3)
    img.SetOrigin(-11.0, 22.0, -3.5)
    img.AllocateScalars(vtk.VTK_SHORT, 1)
    for z in range(nz):
        for y in range(ny):
            for x in range(nx):
                img.SetScalarComponentFromDouble(x, y, z, 0, x * 100 + y * 10 + z)
    if with_field_data:
        # Mimic the geometry contract carried in field data (DirectionMatrix /
        # ZetaAnatA) — these MUST survive the flip untouched.
        dm = vtk.vtkDoubleArray()
        dm.SetName("DirectionMatrix")
        dm.SetNumberOfComponents(1)
        for v in (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0):
            dm.InsertNextValue(v)
        img.GetFieldData().AddArray(dm)
        anat = vtk.vtkDoubleArray()
        anat.SetName("ZetaAnatA")
        anat.SetNumberOfComponents(1)
        for v in (-1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0):
            anat.InsertNextValue(v)
        img.GetFieldData().AddArray(anat)
    return img


def _legacy_inline_flip(vtk, src):
    """The EXACT pre-OPT-48 inline code (copied verbatim from widget.py history)."""
    image_flip = vtk.vtkImageFlip()
    image_flip.SetInputData(src)
    image_flip.SetFilteredAxis(0)
    image_flip.Update()
    out = image_flip.GetOutput()
    if src.GetFieldData():
        for i in range(src.GetFieldData().GetNumberOfArrays()):
            arr = src.GetFieldData().GetArray(i)
            if arr:
                out.GetFieldData().AddArray(arr)
    return out


def _voxels(img):
    nx, ny, nz = img.GetDimensions()
    return [
        img.GetScalarComponentAsDouble(x, y, z, 0)
        for z in range(nz) for y in range(ny) for x in range(nx)
    ]


# ---------------------------------------------------------------------------
# THE decisive test: helper == legacy inline flip, voxel for voxel
# ---------------------------------------------------------------------------

def test_helper_flip_is_byte_identical_to_legacy_inline_flip():
    vtk = _vtk()
    flip = _flip_fn()
    src_a = _make_volume(vtk)
    src_b = _make_volume(vtk)

    legacy = _legacy_inline_flip(vtk, src_a)
    helper = flip(src_b)

    assert tuple(helper.GetDimensions()) == tuple(legacy.GetDimensions())
    assert tuple(helper.GetSpacing()) == tuple(legacy.GetSpacing())
    assert tuple(helper.GetOrigin()) == tuple(legacy.GetOrigin())
    assert _voxels(helper) == _voxels(legacy), "flipped voxels differ from the legacy flip"


def test_helper_actually_flips_x_and_only_x():
    """Radiological L/R correction must still happen — and nothing else."""
    vtk = _vtk()
    flip = _flip_fn()
    src = _make_volume(vtk)
    nx, ny, nz = src.GetDimensions()
    out = flip(src)

    assert tuple(out.GetDimensions()) == (nx, ny, nz)
    for z in range(nz):
        for y in range(ny):
            for x in range(nx):
                expected = src.GetScalarComponentAsDouble(nx - 1 - x, y, z, 0)
                got = out.GetScalarComponentAsDouble(x, y, z, 0)
                assert got == expected, f"voxel ({x},{y},{z}) is not the X-mirror"


def test_geometry_contract_field_data_survives():
    """DirectionMatrix / ZetaAnatA must be carried onto the flipped volume."""
    vtk = _vtk()
    flip = _flip_fn()
    src = _make_volume(vtk)
    out = flip(src)

    fd = out.GetFieldData()
    names = {fd.GetArrayName(i) for i in range(fd.GetNumberOfArrays())}
    assert "DirectionMatrix" in names
    assert "ZetaAnatA" in names
    for name in ("DirectionMatrix", "ZetaAnatA"):
        src_arr = src.GetFieldData().GetArray(name)
        out_arr = fd.GetArray(name)
        assert out_arr.GetNumberOfTuples() == src_arr.GetNumberOfTuples()
        for i in range(src_arr.GetNumberOfTuples()):
            assert out_arr.GetTuple1(i) == src_arr.GetTuple1(i), f"{name}[{i}] changed"


def test_helper_handles_volume_without_field_data():
    vtk = _vtk()
    flip = _flip_fn()
    src = _make_volume(vtk, with_field_data=False)
    out = flip(src)
    assert tuple(out.GetDimensions()) == tuple(src.GetDimensions())


# ---------------------------------------------------------------------------
# Wiring: viewer accepts a pre-computed flip, rejects a mismatched one,
# and always falls back to the inline flip.
# ---------------------------------------------------------------------------

def test_widget_uses_precomputed_flip_and_validates_dims():
    src = WIDGET_SRC.read_text(encoding="utf-8", errors="replace")
    assert "def build_lr_flipped_volume(" in src
    assert "pre_flipped_image_data=None" in src
    block = src[src.index("self._flip_precomputed = False"): src.index("self.dims = self.image_data")]
    # accepted only when dims match the source (a flip cannot change dims)
    assert "GetDimensions()" in block
    assert "_pf_dims) == tuple(_src_dims)" in block
    assert "REJECTED" in block
    # ALWAYS falls back to the canonical inline flip
    assert "if not self._flip_precomputed:" in block
    assert "self.build_lr_flipped_volume(vtk_image_data)" in block


def test_widget_has_exactly_one_flip_implementation():
    """One implementation = the off-thread path cannot drift from the inline one."""
    src = WIDGET_SRC.read_text(encoding="utf-8", errors="replace")
    assert src.count("vtk.vtkImageFlip()") == 1, "the flip must exist in ONE place only"
    assert src.count("SetFilteredAxis(0)") == 1


def test_toolbar_offthread_helper_uses_the_same_implementation():
    src = TOOLBAR_SRC.read_text(encoding="utf-8", errors="replace")
    helper = src[src.index("def _prepare_mpr_flip_offthread"): src.index("def handle_buttons_checked")]
    # must call the viewer's canonical flip — never a private re-implementation
    assert "_SMV.build_lr_flipped_volume(vtk_image_data)" in helper
    # no re-implementation: the caller must never CONSTRUCT its own flip filter
    # (a mention in the explanatory docstring is fine).
    assert "vtkImageFlip()" not in helper, "the caller must NOT re-implement the flip"
    assert "SetFilteredAxis(0)\n" not in helper, "no second flip implementation"
    # gated, fallback-safe, and modal (no re-entrancy) like the volume loader
    assert 'AIPACS_MPR_FLIP_OFFTHREAD", "1"' in helper
    assert 'AIPACS_MPR_FLIP_OFFTHREAD_SLICES", "200"' in helper
    assert "return None" in helper           # every failure path → inline flip
    assert "WindowModality.ApplicationModal" in helper
    assert "setCancelButton(None)" in helper


def test_toolbar_passes_preflipped_to_the_viewer():
    """The open path must compute the flip off-thread and hand the result to the
    viewer.

    Re-pinned 2026-08-23 to assert the WIRING rather than one line's exact
    formatting. The previous version required the literal
    ``self._prepare_mpr_flip_offthread(vtk_image_data)`` and broke when the call
    gained an ``existing_dlg=`` argument (so the flip step reuses the caller's
    progress dialog instead of stacking a second modal on top of it) and wrapped
    onto two lines. The assertion was still true; only the spelling had moved.
    """
    src = TOOLBAR_SRC.read_text(encoding="utf-8", errors="replace")
    assert "_pre_flipped = self._prepare_mpr_flip_offthread(" in src
    assert "vtk_image_data" in src[src.index("_pre_flipped = self._prepare_mpr_flip_offthread("):][:400]
    assert "pre_flipped_image_data=_pre_flipped," in src


def test_other_mpr_call_sites_keep_the_inline_flip():
    """Dental/CurveMPR hosts must be untouched (default None → inline flip)."""
    src = TOOLBAR_SRC.read_text(encoding="utf-8", errors="replace")
    assert src.count("pre_flipped_image_data=") == 1, (
        "only the main toggle_zeta_mpr open should pass a pre-computed flip"
    )
