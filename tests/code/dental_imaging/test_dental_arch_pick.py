# -*- coding: utf-8 -*-
"""Guard: Dental Imaging arch picking (M2a, 2026-06-23).

Two parts:
 * PURE geometry (`core/arch_geometry.py`) — display→slice→world mapping, fully
   headless (no Qt/VTK/numpy). The letterbox math + index→world via the volume's
   DirectionMatrix are the only genuinely new, error-prone logic, so they are
   unit-tested directly.
 * Workspace WIRING source-pin — the Axial cell captures clicks behind the
   default-off flag, draws markers, exposes world points, and adds NO VTK render
   window (the module's static-QImage rule).
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
WORKSPACE = REPO / "modules" / "dental_imaging" / "workspace.py"
GEOM = REPO / "modules" / "dental_imaging" / "core" / "arch_geometry.py"


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated mirror of {p.name}; run on Windows")
    return b.decode("utf-8", "replace")


# --- pure geometry: import the real module ---------------------------------
import importlib.util  # noqa: E402


def _load_geom():
    spec = importlib.util.spec_from_file_location("dental_arch_geometry", GEOM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fit_scale_offset_letterbox():
    g = _load_geom()
    # wide label, square content -> horizontal letterbox
    scale, ox, oy, dw, dh = g.fit_scale_offset(200, 100, 100, 100)
    assert scale == 1.0 and ox == 50.0 and oy == 0.0 and dw == 100.0 and dh == 100.0
    # tall label -> vertical letterbox
    scale, ox, oy, dw, dh = g.fit_scale_offset(100, 200, 100, 100)
    assert scale == 1.0 and ox == 0.0 and oy == 50.0
    # degenerate
    assert g.fit_scale_offset(0, 100, 100, 100)[0] == 0.0


def test_display_click_to_slice_inside_and_margin():
    g = _load_geom()
    # label 200x100, slice 100x100 -> scale 1, off_x 50
    assert g.display_click_to_slice(60, 10, 200, 100, 100, 100) == (10, 10)
    # click on the left letterbox margin -> None
    assert g.display_click_to_slice(40, 10, 200, 100, 100, 100) is None
    # click past the right edge of the image -> None
    assert g.display_click_to_slice(155, 10, 200, 100, 100, 100) is None
    # scaled 2x: label 200x200, slice 100x100 -> click centre maps to (50,50)
    assert g.display_click_to_slice(100, 100, 200, 200, 100, 100) == (50, 50)


def test_slice_index_to_world_identity_and_rotation():
    g = _load_geom()
    # identity direction: world = origin + index*spacing
    w = g.slice_index_to_world(10, 20, 5, (1.0, 2.0, 3.0), (0.5, 0.5, 1.0), None)
    assert w == (6.0, 12.0, 8.0)
    # x/y swap rotation (row-major 4x4) must rotate the offset, not the origin
    d = [0, 1, 0, 0,  1, 0, 0, 0,  0, 0, 1, 0,  0, 0, 0, 1]
    w = g.slice_index_to_world(10, 20, 5, (1.0, 2.0, 3.0), (0.5, 0.5, 1.0), d)
    # vx=5, vy=10, vz=5 -> rx=10, ry=5, rz=5
    assert w == (11.0, 7.0, 8.0)


def test_slice_display_roundtrip():
    g = _load_geom()
    col, row = 30, 40
    dx, dy = g.slice_to_display(col, row, 200, 200, 100, 100)
    back = g.display_click_to_slice(dx, dy, 200, 200, 100, 100)
    assert back == (col, row)


# --- workspace wiring: source-pin ------------------------------------------
def test_workspace_arch_flag_default_on_for_professional_workflow():
    s = _read(WORKSPACE)
    assert 'os.environ.get("AIPACS_DENTAL_ARCH_PICK", "1")' in s
    # controls + capture are still kill-switch gated
    assert "if self._arch_enabled:" in s
    assert "self._arch_enabled and self._arch_pick_mode" in s


def test_workspace_arch_pick_wiring():
    s = _read(WORKSPACE)
    for sym in (
        "def _build_arch_controls",
        "def _toggle_arch_pick",
        "def _undo_arch",
        "def _clear_arch",
        "def _on_axial_click",
        "def _display_to_volume_index",
        "def _volume_index_to_vtk_world",
        "def _volume_index_to_patient_world",
        "def _arch_world_points",
        "def _composite_axial",
        "def eventFilter",
        "def get_arch_world_points",
    ):
        assert sym in s, f"missing {sym}"
    # reuses the pure mapping (never recomputes geometry)
    assert "from .core.arch_geometry import display_click_to_slice, slice_index_to_world" in s
    # click capture installed on the ortho cells (incl. axial) via the event filter
    assert "installEventFilter(self)" in s


def test_workspace_does_not_show_seeded_arch_by_default():
    s = _read(WORKSPACE)
    assert "return self._arch_points if self._arch_points else self._default_arch_points" not in s
    assert "def _arch_items" in s
    assert "return self._arch_points" in s
    assert "self._seed_default_arch()" not in s.replace("def _seed_default_arch(self) -> None:", "")


def test_workspace_has_professional_dental_reconstruction_surface():
    s = _read(WORKSPACE)
    for text in (
        "Panoramic Reconstruction",
        "Axial - Arch Curve",
        "Cross Sections",
        "Implant Planning",
        "Nerve Canal",
        "CBCT Panoramic / Cross Sections / Planning",
    ):
        assert text in s
    for sym in (
        "def _render_panoramic_preview",
        "def _render_cross_sections_preview",
        "def _vtk_xy_plane_to_qt_display",
        "def _build_cross_section_montage",
        "def _change_cross_page",
        "def _on_cross_section_click",
        "def _select_cross_section_at",
        "def _cross_section_hit",
        "def _set_cross_tool",
        "def _on_panoramic_click",
        "def _set_sync_index",
        "def _draw_panoramic_overlays",
        "def _draw_cross_section_overlays",
        "def _seed_default_arch",
        "def _regenerate_dental_recon",
        "build_curved_reconstruction",
        "AIPACS_DENTAL_AUTO_RECON",
        "AIPACS_DENTAL_XSECTION_COUNT",
        "AIPACS_DENTAL_XSECTION_PAGE_SIZE",
    ):
        assert sym in s
    assert '"patient_world"' in s
    assert "roll_180=False" in s
    assert "roll_180=True" in s
    recon = (REPO / "modules" / "dental_imaging" / "core" / "curved_reconstruction.py").read_text(encoding="utf-8")
    assert "AIPACS_DENTAL_PANO_DENSITY" in recon
    assert "AIPACS_DENTAL_XSECTION_MAX" in recon
    assert "reslice_along_path" in recon
    assert "_generate_panoramic_uncropped" in recon
    assert "generate_curved_mpr(" not in recon
    assert "generate_panoramic_view(" not in recon
    assert "auto_crop_image" not in recon
    assert "_frame_for_section" in s
    assert "def _section_path_fraction" in s
    assert "def _pano_display_y_to_source_fraction" in s
    assert "def _pano_source_fraction_to_display_y" in s
    assert "def _panoramic_world_index" in s
    assert "def _apply_panoramic_selection" in s
    assert "self._pano_display_y_to_source_fraction(float(py), float(pix.height()))" in s
    assert "self._pano_source_fraction_to_display_y(ly, pano.height())" in s
    assert "patch = self._vol[:, y0:y1, x0:x1]" not in s
    assert "strip[:, oi] = self._vol[:, yi, xi]" not in s


def test_workspace_no_vtk_render_window_added():
    s = _read(WORKSPACE)
    assert "QVTKRenderWindowInteractor" not in s
    assert "vtkImageViewer2" not in s
    assert "vtkRenderWindow(" not in s
