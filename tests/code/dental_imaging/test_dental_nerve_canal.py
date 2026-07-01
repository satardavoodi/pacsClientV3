# -*- coding: utf-8 -*-
"""Guard: Dental Imaging mandibular (inferior alveolar) canal tracing (2026-06-24).

Structured-report use (AAOMR/ACR): trace the IAN canal as an editable control-point
curve, review on slices, report length + proximity. Two parts:
 * PURE `core/nerve_canal.py` — bilateral control points + report geometry (length,
   proximity, resample, nearest-control, move/undo/clear). Unit-tested headless.
 * WORKSPACE wiring — trace/edit/show tools, L/R side, per-view click→world, canal
   overlay, all routed through the existing geometry helpers (no VTK render window).
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


def _load():
    spec = importlib.util.spec_from_file_location("dental_nerve_canal", CANAL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# --- pure canal core --------------------------------------------------------
def test_canal_length_and_proximity():
    n = _load()
    st = n.NerveCanalStore()
    for x in (0, 10, 20, 30):
        st.add_point("left", {"world": (float(x), 10.0, 5.0), "index": (x, 10, 5)})
    assert st.count("left") == 4
    assert abs(st.length_mm("left") - 30.0) < 1e-6          # traced length
    # proximity: a point 4 mm off the mid-canal (implant/third-molar clearance)
    assert abs(st.nearest_distance_mm("left", (15.0, 14.0, 5.0)) - 4.0) < 0.2


def test_canal_edit_operations():
    n = _load()
    st = n.NerveCanalStore()
    for x in (0, 10, 20):
        st.add_point("right", {"world": (float(x), 0.0, 0.0), "index": (x, 0, 0)})
    # nearest control for editing
    assert st.nearest_control("right", (9.0, 0.0, 0.0), max_dist=6.0) == 1
    assert st.nearest_control("right", (100.0, 0.0, 0.0), max_dist=6.0) is None
    assert st.move_control("right", 1, {"world": (11.0, 1.0, 0.0), "index": (11, 1, 0)})
    assert st.undo("right") and st.count("right") == 2
    st.clear("right")
    assert st.count("right") == 0
    # sides are independent
    st.add_point("left", {"world": (0.0, 0.0, 0.0)})
    st.clear_all()
    assert st.count("left") == 0


def test_resample_count_and_empty_safety():
    n = _load()
    st = n.NerveCanalStore()
    assert st.nearest_distance_mm("left", (0, 0, 0)) is None   # <2 pts
    for x in range(5):
        st.add_point("left", {"world": (float(x), 0.0, 0.0)})
    assert len(st.resampled_world("left", 32)) == 32


# --- workspace wiring -------------------------------------------------------
def test_workspace_nerve_wiring():
    s = _read(WORKSPACE)
    assert "from .core.nerve_canal import NerveCanalStore" in s
    for sym in ("def _toggle_nerve_trace", "def _toggle_nerve_edit", "def _toggle_nerve_show",
                "def _handle_nerve_press", "def _handle_nerve_move", "def _draw_nerve_overlay",
                "def _set_nerve_side", "def _nerve_undo", "def _nerve_clear",
                "def _build_nerve_controls"):
        assert sym in s, f"missing {sym}"
    # the Planning "Nerve Canal" rows are wired (no placeholder)
    assert '"Trace mandibular canal": self._toggle_nerve_trace' in s
    assert '"Edit control points": self._toggle_nerve_edit' in s
    assert '"Show on slices": self._toggle_nerve_show' in s
    # canal drawn on the ortho views + reset on new series
    assert "self._draw_nerve_overlay(painter, view, w, h)" in s
    assert "self._nerve_store.clear_all()" in s
    # editing routes through the event filter (press/drag)
    assert "self._handle_nerve_press(" in s and "self._handle_nerve_move(obj, event)" in s
    assert "QVTKRenderWindowInteractor" not in s and "vtkImageViewer2" not in s
