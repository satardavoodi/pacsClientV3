"""Source-pin guard for the Dental Curve MPR FAST fix: VTK-hosted point picking
(2026-06-22; auto-on-FAST routing 2026-06-23).

Pure source-string checks (no PySide6/VTK import — VTK isn't available in the
offscreen sandbox). Runtime behaviour MUST be validated on the Windows source build.

Pins that Dental Curve MPR can pick on a real VTK host (standard-MPR layout) instead
of the stubbed FAST viewer:
* DentalCurvePicker exposes the panel-compatible interface;
* the toolbar launch reuses the proven volume route and the picker reslices the
  host's OWN (flipped) volume so points + volume share a frame;
* picking is AUTO-routed to the VTK host when the active viewer is FAST (the default,
  whose enable_curved_mpr_mode is a no-op) — the reported "points don't register" bug
  — while a real VTK viewer keeps the unchanged legacy in-place picking.

See docs/plans/architecture/UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md.
"""

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PICKER = _REPO_ROOT / "modules" / "mpr" / "curved_mpr" / "dental_curve_vtk_host.py"
_TOOLBAR = (
    _REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)


def _read(path: Path) -> str:
    assert path.is_file(), f"expected source file missing: {path}"
    data = path.read_bytes()
    if b"\x00" in data:  # flaky Linux mount sometimes serves NUL-truncated copies
        pytest.skip(f"NUL-truncated mirror of {path.name}; run on Windows")
    return data.decode("utf-8", "replace")


def _toolbar() -> str:
    """Read toolbar_manager.py, skipping if the (large) mirror is truncated before
    the dental-curve region this guard inspects."""
    src = _read(_TOOLBAR)
    if "def is_mpr_viewer" not in src:  # anchor sits just past the helper we assert
        pytest.skip("toolbar_manager.py mirror truncated; run on Windows")
    return src


def _read_complete(path: Path, anchor: str) -> str:
    """Read `path`, skipping if the mirror is truncated before `anchor`."""
    src = _read(path)
    if anchor not in src:
        pytest.skip(f"{path.name} mirror truncated (anchor missing); run on Windows")
    return src


# --- DentalCurvePicker exposes the panel-compatible interface ---------------

def test_picker_exposes_panel_interface():
    src = _read(_PICKER)
    assert "class DentalCurvePicker" in src
    for member in (
        "def enable_curved_mpr_mode(self, enable",
        "def _add_curved_mpr_point(self, point_3d",
        "def get_curved_mpr_points(self)",
        "def _clear_curved_mpr_visuals(self)",
        "self.vtk_image_data = vtk_image_data",
        "self.curved_mpr_points",
        "def add_point(self, world_pos)",  # CurveMPRInteractorStyle-compatible alias
    ):
        assert member in src, f"DentalCurvePicker missing: {member}"


def test_picker_uses_world_point_picker_nonconsuming():
    src = _read(_PICKER)
    assert "vtkWorldPointPicker" in src
    # high-priority, non-consuming observer (mirrors CurveMPRInteractorStyle)
    assert 'AddObserver(' in src and 'LeftButtonPressEvent' in src
    assert "RemoveObserver(" in src, "must be able to disarm picking"


# --- toolbar wiring: reuses the proven route + host frame --------------------

def test_toolbar_force_flag_default_off_auto_on():
    src = _toolbar()
    # The explicit FORCE flag stays default-off...
    assert '"AIPACS_CURVED_MPR_VTK_PICK", "0"' in src
    # ...but auto-routing to the VTK host (for FAST) is default-ON.
    assert '"AIPACS_CURVED_MPR_VTK_PICK_AUTO", "1"' in src


def test_toolbar_launch_reuses_volume_route_and_host_frame():
    src = _toolbar()
    assert "def _launch_dental_curve_vtk_host(self, selected_widget):" in src
    # reuses the same real-volume route standard MPR uses (works on FAST)
    assert "_resolve_mpr_volume_for_route(" in src
    assert "StandardMPRViewer(" in src
    # picker reslices the host's OWN flipped volume → points + volume share one frame
    assert "DentalCurvePicker(host, getattr(host, 'image_data'" in src
    # in-place placement + cross-link (restore via _restore_selected_viewer)
    assert "selected_widget._curved_mpr_widget = host" in src
    assert "host._original_widget = selected_widget" in src


def test_panel_uses_resolved_curved_viewer():
    src = _toolbar()
    assert "curved_viewer = self._launch_dental_curve_vtk_host(selected_widget)" in src
    assert "self._curved_mpr_viewer = curved_viewer" in src


# --- FAST auto-routing (2026-06-23): fixes "points don't register on FAST" ----

def test_toolbar_auto_routes_fast_viewer_to_vtk_host():
    src = _toolbar()
    assert "AIPACS_CURVED_MPR_VTK_PICK_AUTO" in src
    # the gate routes to the VTK host when the active viewer can't pick natively
    assert "_viewer_supports_native_curve_picking(selected_widget)" in src


def test_native_pick_detection_helper_present():
    src = _toolbar()
    assert "def _viewer_supports_native_curve_picking(self, selected_widget)" in src
    assert "QtFastContainer" in src
    assert "isinstance(selected_widget, QtFastContainer)" in src
    assert "return False" in src  # FAST → routed to VTK host
    assert "return True" in src   # real VTK viewer → legacy path


# --- pure detection contract (no import) -------------------------------------

def _supports_native(selected_widget, fast_types):
    """Re-implements _viewer_supports_native_curve_picking's contract."""
    if isinstance(selected_widget, fast_types):
        return False
    iv = getattr(selected_widget, "image_viewer", None)
    if iv is None:
        return False
    cls = type(iv).__name__.lower()
    if "fast" in cls or "bridge" in cls:
        return False
    return True


def test_native_pick_detection_contract():
    class _QtFastContainer:
        pass

    class _RealVTKWidget:
        def __init__(self):
            self.image_viewer = object()  # a real ImageViewer2D stand-in

    class _FastBridge:
        pass

    class _ContainerWithFastIV:
        def __init__(self):
            self.image_viewer = _FastBridge()

    # FAST container → routed to host
    assert _supports_native(_QtFastContainer(), (_QtFastContainer,)) is False
    # real VTK viewer → legacy path
    assert _supports_native(_RealVTKWidget(), (_QtFastContainer,)) is True
    # a FAST-bridge image_viewer (by class name) → routed to host
    assert _supports_native(_ContainerWithFastIV(), (_QtFastContainer,)) is False
    # no image_viewer → cannot pick natively
    assert _supports_native(_RealVTKWidget.__new__(_RealVTKWidget), (_QtFastContainer,)) is False


# --- closing the panel restores the default view (2026-06-23) ----------------

def test_panel_close_routes_window_x_to_cleanup():
    src = _toolbar()
    # the window X / Escape (finished signal) must run the same teardown as Close
    assert "self._curved_mpr_panel.finished.connect(self._cleanup_curved_mpr_panel)" in src
    assert "AIPACS_CURVED_MPR_CLOSE_RESTORE" in src
    assert "def _cleanup_curved_mpr_panel(self" in src
    # idempotent guard so Close-button + finished-signal don't double-run
    assert "_curved_mpr_panel_cleaned" in src


def test_cleanup_disables_picking_and_restores_original_viewport():
    src = _toolbar()
    assert "enable_curved_mpr_mode(False)" in src        # stop point-picking
    assert "_restore_selected_viewer(" in src            # bring back the original cell
    assert "self._dental_curve_host = None" in src       # clear the consumed host
    # the Close button now delegates to the shared teardown
    assert "self._cleanup_curved_mpr_panel()" in src


# --- generated result resets to default on close (2026-06-23) ----------------

def test_curved_result_is_inplace_by_default():
    src = _toolbar()
    # in-place placement (restorable) is now the default; legacy destructive 1x1 opt-in
    assert '"AIPACS_CURVED_MPR_INPLACE_VIEWPORT", "1"' in src
    # the result's source cell is tracked so close can restore it
    assert "self._dental_curve_result_source = source" in src
    # the FAST picking host is handed off (removed) during in-place placement
    assert "host handoff cleanup skipped" in src


def test_close_restores_inplace_result_to_default():
    src = _toolbar()
    assert "result_source = getattr(self, '_dental_curve_result_source', None)" in src
    assert "self._restore_selected_viewer(result_source)" in src


def test_restore_selected_viewer_skips_stale_none_attrs():
    # late in the file — anchor on the method's last line so a truncated mirror skips
    src = _read_complete(_TOOLBAR, "original_widget.setEnabled(True)")
    assert "getattr(selected_widget, '_curved_mpr_widget', None) is not None" in src
    assert "getattr(selected_widget, '_zeta_mpr_widget', None) is not None" in src
    assert "getattr(selected_widget, '_mpr_widget', None) is not None" in src
