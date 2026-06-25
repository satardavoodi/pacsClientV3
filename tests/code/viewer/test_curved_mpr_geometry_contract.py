"""Guard for unified-pipeline STEP A0: Dental Curve MPR reslices the SAME
radiologically-prepared volume as standard MPR (2026-06-22).

Two layers:
* pure-math tests of the point mirror (loaded via importlib straight from the file —
  the helper's top-level imports are stdlib only, so no PySide6/VTK is needed);
* source-pin checks that the helper replicates standard MPR's flip and that the
  toolbar wiring is flag-gated default-off.

See docs/plans/architecture/UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md and
docs/reports/DENTAL_CURVE_MPR_VS_STANDARD_MPR_ALIGNMENT_2026-06-22.md.
"""

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HELPER = _REPO_ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_volume_prep.py"
_TOOLBAR = (
    _REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)


def _read(path: Path) -> str:
    assert path.is_file(), f"expected source file missing: {path}"
    return path.read_text(encoding="utf-8")


def _load_helper():
    """Exec the helper module straight from its file (no package import, no VTK)."""
    spec = importlib.util.spec_from_file_location("mpr_volume_prep_under_test", _HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- pure-math: the point mirror (the part that must be exactly right) -------

def test_mirror_point_x_basic():
    m = _load_helper()
    assert m.mirror_point_x((10.0, 5.0, 3.0), 20.0) == (30.0, 5.0, 3.0)


def test_mirror_point_x_is_self_inverse():
    import math
    m = _load_helper()
    p, cx = (12.3, -4.0, 7.0), 50.0
    round_trip = m.mirror_point_x(m.mirror_point_x(p, cx), cx)
    assert all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(round_trip, p))


def test_mirror_point_x_keeps_y_and_z():
    m = _load_helper()
    out = m.mirror_point_x((1.0, 2.0, 3.0), 0.0)
    assert out[1] == 2.0 and out[2] == 3.0


def test_point_on_center_is_fixed():
    m = _load_helper()
    assert m.mirror_point_x((20.0, 1.0, 1.0), 20.0) == (20.0, 1.0, 1.0)


# --- helper replicates standard MPR's flip, VTK imported lazily -------------

def test_helper_replicates_standard_flip():
    src = _read(_HELPER)
    assert "vtkImageFlip" in src and "SetFilteredAxis(0)" in src
    assert "GetFieldData" in src and "AddArray" in src
    # VTK must be imported lazily (inside prepare_radiological_volume, not at top)
    top = src.split("def prepare_radiological_volume")[0]
    assert "import vtkmodules" not in top and "\nimport vtk" not in top, (
        "VTK must be imported lazily so importing this module never pulls VTK"
    )


# --- toolbar wiring is flag-gated default-off (run on Windows / fresh sandbox) ---

def test_toolbar_geometry_contract_gated_default_off():
    src = _read(_TOOLBAR)
    assert "AIPACS_CURVED_MPR_GEOMETRY_CONTRACT" in src
    assert '"AIPACS_CURVED_MPR_GEOMETRY_CONTRACT", "0"' in src  # default OFF
    assert "prepare_radiological_volume(image_data)" in src
    assert "mirror_point_x(p, _center_x)" in src
