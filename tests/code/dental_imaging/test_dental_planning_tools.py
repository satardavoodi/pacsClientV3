# -*- coding: utf-8 -*-
"""Guard: Dental Imaging "Planning / Objects" panel tools are wired (2026-06-24).

Every panel button used to connect to a dead ``_tool_placeholder``. Now:
 * Measurements -> real tools: Distance/Angle reuse the existing annotation tools, and a
   NEW Density / HU probe samples the volume voxel and shows "N HU" — all via the existing
   per-view click routing (axial/coronal/sagittal/panoramic/cross-section).
 * View Sync -> real toggles (panoramic reference line, cross-section position, linked WL).
 * Implant Planning / Nerve Canal (no backend yet) -> honest "not yet available" feedback,
   not a silent placeholder.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
WORKSPACE = REPO / "modules" / "dental_imaging" / "workspace.py"


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated mirror of {p.name}; run on Windows")
    return b.decode("utf-8", "replace").replace("\r\n", "\n")


def test_planning_panel_no_longer_uses_placeholder():
    s = _read(WORKSPACE)
    # the panel builds a real action map and pins each button (Distance/Angle/Density...)
    assert "planning_actions = {" in s
    assert '"Distance": lambda: self._set_annotation_tool("distance")' in s
    assert '"Angle": lambda: self._set_annotation_tool("angle")' in s
    assert '"Density probe": lambda: self._set_annotation_tool("density")' in s
    # the panel loop must NOT wire buttons to the dead placeholder anymore
    assert "btn.clicked.connect(self._tool_placeholder)" not in s


def test_density_probe_tool_is_registered_end_to_end():
    s = _read(WORKSPACE)
    assert 'annotation_type == "density"' in s                 # measurement text
    assert "def _density_value_at" in s and "def _annotation_index_for_point" in s
    assert '"density": 1' in s                                  # needed points = 1
    assert '"density": "Density / HU probe"' in s               # tool label
    assert 'annotation_type in ("text", "marker", "density")' in s   # draws a marker
    assert '("Density / HU probe", "density")' in s             # in the measure menu
    assert "HU" in s


def test_view_sync_toggles_and_gating():
    s = _read(WORKSPACE)
    assert "def _toggle_sync_overlay" in s and "def _relink_window_level" in s
    assert "self._show_pano_reference" in s and "self._show_cross_position" in s
    # overlays are actually gated by the flags (not just stored)
    assert "or not self._show_cross_position" in s
    assert "and self._show_pano_reference" in s


def test_unimplemented_features_give_honest_feedback():
    s = _read(WORKSPACE)
    assert "def _planning_feature_pending" in s
    assert "self._planning_feature_pending(name)" in s
    assert "not yet available" in s


def test_mouse_function_selector_stack_pan_zoom_wl():
    s = _read(WORKSPACE)
    # panel exposes a Mouse function selector with all four modes
    assert '"Mouse function"' in s
    assert "def _set_mouse_mode" in s and "self._mouse_mode" in s
    for label, mode in (("Stack", "stack"), ("Pan", "pan"), ("Zoom", "zoom"), ("WW/WL", "wl")):
        assert f'("{label}", "{mode}")' in s
    assert "self._set_mouse_mode(m)" in s
    # the LEFT-drag actually dispatches on the selected mode
    assert "def _apply_stack_drag" in s
    assert 'mode = getattr(self, "_mouse_mode"' in s
    assert 'if mode == "pan":' in s and 'elif mode == "zoom":' in s and 'elif mode == "stack":' in s
    # stack drag reuses the existing per-view scroll (no separate geometry)
    assert "self._scroll_view(plane, step)" in s
    assert "_STACK_DRAG_PX" in s
