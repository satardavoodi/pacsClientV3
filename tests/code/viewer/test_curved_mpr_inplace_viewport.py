"""Source-pin guard for unified-pipeline STEP 1: Dental Curve MPR opens in-place
like standard MPR (2026-06-22).

Pure source-string checks — imports NO PySide6 / VTK, so it runs in the offscreen
sandbox or on Windows without a display. It pins the first step of aligning Dental
Curve MPR with the standard (Zeta) MPR pipeline:

  * the result is placed via an in-place single-cell swap (mirroring
    toggle_zeta_mpr) when AIPACS_CURVED_MPR_INPLACE_VIEWPORT is enabled, instead
    of the destructive cleanup_all_viewers() grid wipe;
  * the legacy 1x1-wipe path is preserved as the default kill switch;
  * _restore_selected_viewer recognizes the curved-MPR cross-link;
  * CurvedMPRPanoramicView exposes a cleanup() lifecycle hook (like
    StandardMPRViewer.cleanup()).

See docs/plans/architecture/UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md and
docs/reports/DENTAL_CURVE_MPR_VS_STANDARD_MPR_ALIGNMENT_2026-06-22.md.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

_TOOLBAR = (
    _REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)
_PANORAMIC = (
    _REPO_ROOT / "modules" / "mpr" / "curved_mpr" / "curved_mpr_panoramic_view.py"
)


def _read(path: Path) -> str:
    assert path.is_file(), f"expected source file missing: {path}"
    return path.read_text(encoding="utf-8")


# --- Flag + in-place placement --------------------------------------------

def test_inplace_flag_declared_default_off():
    src = _read(_TOOLBAR)
    assert 'AIPACS_CURVED_MPR_INPLACE_VIEWPORT' in src, "in-place flag missing"
    # default OFF: env.get(..., "0") != "0"
    assert '"AIPACS_CURVED_MPR_INPLACE_VIEWPORT", "0"' in src, "flag must default OFF"


def test_inplace_method_present_and_gated():
    src = _read(_TOOLBAR)
    assert "def _place_curved_mpr_inplace(self, viewer_widget):" in src
    # the flag check must call the in-place method (gated)
    assert "placed_inplace = self._place_curved_mpr_inplace(viewer_widget)" in src


def test_inplace_mirrors_standard_mpr_pattern():
    src = _read(_TOOLBAR)
    # saves the source cell + cross-links like toggle_zeta_mpr / _zeta_mpr_widget
    assert "source._mpr_grid_position = grid_position" in src
    assert "source._curved_mpr_widget = viewer_widget" in src
    assert "viewer_widget._original_widget = source" in src
    assert "getItemPosition(i)" in src


def test_legacy_wipe_preserved_as_kill_switch():
    src = _read(_TOOLBAR)
    # the legacy destructive path must still exist (runs when the flag is off /
    # in-place can't resolve the source cell)
    assert "self.patient_widget.cleanup_all_viewers()" in src
    assert "if not placed_inplace:" in src


def test_inplace_method_does_not_wipe_grid():
    """The in-place method body itself must NOT call cleanup_all_viewers()."""
    src = _read(_TOOLBAR)
    start = src.index("def _place_curved_mpr_inplace(self, viewer_widget):")
    end = src.index("def _show_curved_mpr_result_simple", start)
    body = src[start:end]
    assert "cleanup_all_viewers" not in body, (
        "the in-place placement must preserve other viewports — no grid wipe"
    )
    assert "lst_nodes_viewer.clear()" not in body, (
        "the in-place placement must not clear the NodeViewer list"
    )


# --- Restore + lifecycle ----------------------------------------------------

def test_restore_recognizes_curved_cross_link():
    src = _read(_TOOLBAR)
    assert "elif hasattr(selected_widget, '_curved_mpr_widget'):" in src, (
        "_restore_selected_viewer must recognize the curved-MPR cross-link"
    )
    assert "delattr(original_widget, '_curved_mpr_widget')" in src


def test_curved_view_has_cleanup_lifecycle_hook():
    src = _read(_PANORAMIC)
    assert "def cleanup(self):" in src, (
        "CurvedMPRPanoramicView needs a cleanup() hook so the shared restore path "
        "can tear it down like StandardMPRViewer"
    )
