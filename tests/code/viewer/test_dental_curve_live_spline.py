"""Source-pin guard for the Dental Curve MPR professional curve-drawing (2026-06-22):
live arch spline + numbered markers + undo.

Pure source-string checks (no PySide6/VTK; VTK isn't in the offscreen sandbox). Runtime
behaviour is validated on the Windows source build.

See docs/plans/architecture/UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PICKER = _REPO_ROOT / "modules" / "mpr" / "curved_mpr" / "dental_curve_vtk_host.py"
_TOOLBAR = (
    _REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)


def _read(path: Path) -> str:
    assert path.is_file(), f"expected source file missing: {path}"
    return path.read_text(encoding="utf-8")


# --- picker: live arch spline (gated), numbered markers, undo ---------------

def test_live_spline_flag_default_on():
    src = _read(_PICKER)
    assert "AIPACS_CURVED_MPR_LIVE_SPLINE" in src
    assert '"AIPACS_CURVED_MPR_LIVE_SPLINE", "1"' in src  # default ON


def test_picker_draws_arch_spline():
    src = _read(_PICKER)
    assert "def _rebuild_spline(self, renderer):" in src
    assert "vtkParametricSpline" in src
    assert "vtkParametricFunctionSource" in src
    assert "vtkTubeFilter" in src
    # spline is gated + only with >= 2 points
    assert "if not _LIVE_SPLINE or len(self.curved_mpr_points) < 2:" in src


def test_picker_numbered_markers_and_undo():
    src = _read(_PICKER)
    assert "def remove_last_point(self)" in src
    assert "self._sphere_actors.pop()" in src
    assert "self._label_actors" in src  # numbered labels
    assert "vtkBillboardTextActor3D" in src
    # clear removes spline + labels too
    assert "self._spline_actor = None" in src


# --- panel: Undo Last button + handler --------------------------------------

def test_panel_has_undo_button_and_handler():
    src = _read(_TOOLBAR)
    assert 'undo_btn = QPushButton("Undo Last")' in src
    assert "def _undo_last_curved_mpr_point(self):" in src
    assert "viewer.remove_last_point()" in src
