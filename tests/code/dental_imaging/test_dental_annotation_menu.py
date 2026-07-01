# -*- coding: utf-8 -*-
"""Guard: Dental Imaging annotation right-click menu + visibility (2026-06-24).

Right-clicking an annotation (distance/angle/density/text/marker) or the arch/nerve line
opens a context menu: Rename/label, Pin (all slices), Unpin (this slice = default), Hide,
Delete. Visibility is per-layout and DEFAULTS to the creation slice only (slice_based) —
it must not appear on every slice unless explicitly pinned.
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


def test_right_click_menu_wired():
    s = _read(WORKSPACE)
    # right-click is routed to the overlay context-menu resolver in the event filter
    assert "event.button() == Qt.RightButton" in s
    assert "self._maybe_show_overlay_context_menu(" in s
    for sym in ("def _annotation_hit_test", "def _overlay_line_hit_test",
                "def _show_annotation_context_menu", "def _rename_annotation",
                "def _delete_annotation", "def _set_annotation_vis",
                "def _show_line_context_menu", "def _annotation_display_label"):
        assert sym in s, f"missing {sym}"


def test_menu_actions_present():
    s = _read(WORKSPACE)
    assert '"Rename / label...' in s
    assert '"Pin - visible on all slices"' in s
    assert '"Unpin - this slice only"' in s
    assert '"Hide"' in s
    assert '"Delete"' in s
    assert "QMenu(self)" in s and "QInputDialog.getText" in s


def test_default_visibility_is_slice_based_per_layout():
    s = _read(WORKSPACE)
    # new annotations default to the slice they were created on (not pinned/all slices)
    assert 'self._annotation_visibility_mode = "slice_based"' in s
    assert '"visibility_mode": self._annotation_visibility_mode' in s
    # visibility is judged per layout + per slice unless pinned
    assert 'item.get("layout_id") != layout_id' in s
    assert 'mode == "pinned"' in s and 'mode == "hidden"' in s
    # the three set_annotation_visibility modes exist
    assert 'def set_annotation_visibility' in s


def test_arch_and_labels_wired():
    s = _read(WORKSPACE)
    # arch curve can be hidden via right-click
    assert "self._arch_show" in s and "def _set_arch_show" in s
    assert "if self._arch_show:" in s               # arch draw is gated
    # custom label combined with measured value in the draw
    assert "label = self._annotation_display_label(item)" in s
