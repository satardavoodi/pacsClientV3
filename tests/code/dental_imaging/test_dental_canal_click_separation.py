# -*- coding: utf-8 -*-
"""Guard: Dental Imaging canal / arch / multi-point-annotation click separation
(2026-07-01).

Right-click must NEVER add a point while drawing a canal, arch, or multi-point
annotation. Only LEFT-click adds the next point; right-click only opens the context
menu (annotation/line menu on a hit, else the drawing-mode Delete/Clear/Show menu),
and in plain sync mode still falls through to the Window/Level right-drag.

 * PURE `core/nerve_canal.py` gains `remove_control(side, idx)` for the right-click
   "delete point under cursor" action (unit-tested headless).
 * WORKSPACE `eventFilter` gates arch pick, canal press, and annotation clicks on
   `Qt.LeftButton`, and routes every right-click through a single interceptor.
"""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CANAL = REPO / "modules" / "dental_imaging" / "core" / "nerve_canal.py"
WORKSPACE = REPO / "modules" / "dental_imaging" / "workspace.py"


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated mirror of {p.name}; run on Windows")
    return b.decode("utf-8", "replace").replace("\r\n", "\n")


def _load_canal():
    spec = importlib.util.spec_from_file_location("dental_nerve_canal_click", CANAL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# --- pure core: single control-point deletion -------------------------------
def test_remove_control_deletes_one_point():
    n = _load_canal()
    st = n.NerveCanalStore()
    for x in (0, 10, 20, 30):
        st.add_point("left", {"world": (float(x), 0.0, 0.0), "index": (x, 0, 0)})
    assert st.count("left") == 4
    # delete the 2nd control point -> 3 remain, order preserved
    assert st.remove_control("left", 1) is True
    assert st.count("left") == 3
    xs = [p["world"][0] for p in st.points("left")]
    assert xs == [0.0, 20.0, 30.0]
    # out-of-range / empty side are safe no-ops
    assert st.remove_control("left", 99) is False
    assert st.remove_control("right", 0) is False


# --- workspace wiring: left-only point creation -----------------------------
def test_point_creation_is_left_button_only():
    s = _read(WORKSPACE)
    # arch pick, canal press, and annotation add are all gated on LeftButton
    assert s.count("event.button() == Qt.LeftButton") >= 3
    assert "is_left = event.button() == Qt.LeftButton" in s
    # the left guard sits on the arch + nerve press blocks
    assert 'and self._nerve_mode != "off"' in s


def test_right_click_routes_to_menu_only():
    s = _read(WORKSPACE)
    # single top-level right-click interceptor -> context menu / drawing menu
    assert "event.button() == Qt.RightButton" in s
    assert "self._in_drawing_mode()" in s
    for sym in ("def _in_drawing_mode", "def _show_drawing_context_menu",
                "def _nerve_delete_nearest", "def _cancel_pending_annotation"):
        assert sym in s, f"missing {sym}"
    # drawing menu offers the requested actions
    assert '"Delete point under cursor"' in s
    assert '"Delete last point"' in s
    assert '"Clear this canal"' in s or '"Clear arch"' in s


def test_drawing_menu_covers_all_three_tools():
    s = _read(WORKSPACE)
    # nerve, arch, and annotation branches are all present in the drawing menu
    assert 'nerve canal"' in s
    assert '"Dental arch curve"' in s
    assert "measurement" in s
    assert "def remove_control" in _read(CANAL)
