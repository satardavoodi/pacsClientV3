"""Guards for the MPR mouse-interaction responsiveness fix (2026-06-09).

Symptom: noticeable lag/stutter using the mouse inside MPR — hovering, drawing a
ruler, mouse-wheel scrolling. Two UNTHROTTLED per-event hot paths were the cause:

1. CrosshairInteractorStyle.check_handle_hover ran a vtkPropPicker.Pick() plus 4
   fresh vtkCoordinate allocations on EVERY MouseMoveEvent (>100 Hz) — and also
   while an annotation tool was drawing (no crosshair drag active). It only sets
   the cursor SHAPE, so it is now coalesced to frame cadence and reuses one cached
   vtkCoordinate.
2. on_mouse_wheel_forward/backward ran the FULL cross-pane compute (crosshairs +
   oblique reslice + slice-info across all panes) inline per notch. That sync is
   now routed through the existing frame-cadence throttle (new kind='scroll'),
   while the scrolled pane's own camera move + render stay immediate.

Crosshair drag was already throttled (kind='move'/'rotate'); renders are batched.
All of this is gated by AIPACS_ZETA_MPR_INTERACT_MS (0 = legacy inline behaviour),
and AIPACS_ZETA_MPR_PERF=1 logs per-op interaction latency for KPI capture.
"""
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_CROSSHAIR = (_ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer"
              / "_mpr_crosshair_interact.py")
_ORIENT = (_ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer"
           / "_mpr_orientation.py")


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _method_slice(src: str, name: str) -> str:
    start = src.index(f"def {name}")
    nxt = src.index("\n    def ", start + 1)
    return src[start:nxt]


def _load_apply_interaction_update():
    """Exec just _apply_interaction_update against a stub holder (pure Python)."""
    src = _ORIENT.read_text(encoding="utf-8", errors="ignore")
    block = _method_slice(src, "_apply_interaction_update")
    fn_src = "    " + block.rstrip() + "\n"
    ns = {"logger": logging.getLogger("test")}
    exec("class _H:\n" + fn_src, ns)  # noqa: S102 — test-local exec of repo source
    return ns["_H"]


class _Recorder:
    def __init__(self):
        self.calls = []

    def _update_all_crosshairs(self):
        self.calls.append("crosshairs")

    def _update_slice_positions(self):
        self.calls.append("slice_positions")

    def _synchronize_oblique_views(self):
        self.calls.append("oblique")

    def _update_slice_info_texts(self):
        self.calls.append("text")

    def _mpr_perf_note(self, op, ms):
        pass


def test_scroll_kind_matches_wheel_sync_and_skips_slice_positions():
    """kind='scroll' must do exactly the wheel's old inline cross-pane sync:
    crosshairs + oblique + slice-info text — and must NOT move the slice cameras
    (the wheel never called _update_slice_positions)."""
    H = _load_apply_interaction_update()
    rec = _Recorder()
    H._apply_interaction_update(rec, "scroll")
    assert rec.calls == ["crosshairs", "oblique", "text"]


def test_move_and_rotate_kinds_unchanged():
    H = _load_apply_interaction_update()
    rec = _Recorder()
    H._apply_interaction_update(rec, "move")
    assert rec.calls == ["crosshairs", "slice_positions", "oblique", "text"]
    rec.calls.clear()
    H._apply_interaction_update(rec, "rotate")
    assert rec.calls == ["crosshairs", "oblique"]


def test_wheel_handlers_route_through_throttle():
    code = _strip_comments(_CROSSHAIR.read_text(encoding="utf-8", errors="ignore"))
    # both wheel directions coalesce the cross-pane sync via the throttle
    assert code.count("_request_interaction_update('scroll')") == 2
    # legacy inline path retained behind the budget kill-switch
    assert "_interaction_budget_ms() > 0" in code


def test_hover_is_coalesced_to_frame_cadence():
    src = _CROSSHAIR.read_text(encoding="utf-8", errors="ignore")
    hover = _method_slice(src, "check_handle_hover")
    assert "_last_hover_ms" in hover
    assert "_interaction_budget_ms" in hover
    # handle detection is now geometric (no GPU prop pick) AND rate-limited
    assert "_handle_at(click_pos)" in hover
    assert "prop_picker.Pick" not in hover


def test_world_to_display_reuses_cached_coordinate():
    src = _CROSSHAIR.read_text(encoding="utf-8", errors="ignore")
    w2d = _method_slice(src, "_world_to_display")
    assert "_coord_converter" in w2d
    # exactly ONE allocation (lazy init), not one-per-call
    assert w2d.count("vtk.vtkCoordinate()") == 1


def test_orientation_has_scroll_kind_rank_merge_and_kpi_logger():
    code = _ORIENT.read_text(encoding="utf-8", errors="ignore")
    assert "kind in ('move', 'scroll')" in code          # scroll runs slice-info text
    assert "'scroll': 1" in code                          # rank-based coalescing merge
    assert "def _mpr_perf_note" in code                   # gated KPI logger
    assert "AIPACS_ZETA_MPR_PERF" in code


# ── gesture-START hiccup: GPU prop pick replaced by geometric handle hit-test ──

def _load_method(name):
    src = _CROSSHAIR.read_text(encoding="utf-8", errors="ignore")
    block = _method_slice(src, name)
    fn_src = "    " + block.rstrip() + "\n"
    ns = {"logger": logging.getLogger("test")}
    exec("class _H:\n" + fn_src, ns)  # noqa: S102 — test-local exec of repo source
    return ns["_H"]


def test_prop_pick_removed_from_mouse_hot_paths():
    """The vtkPropPicker.Pick() (a GPU colour-buffer readback) must no longer run
    on press or hover — it was the start-of-interaction hiccup. Both now use the
    geometric _handle_at hit-test instead."""
    src = _CROSSHAIR.read_text(encoding="utf-8", errors="ignore")
    for m in ("check_handle_hover", "on_left_button_press"):
        body = _method_slice(src, m)
        assert "prop_picker.Pick" not in body, f"{m} must not GPU-pick on the mouse hot path"
        assert "_handle_at(click_pos)" in body, f"{m} must use the geometric handle hit-test"


def test_handle_at_is_pure_geometry_hit_and_miss():
    """_handle_at must detect a handle by display-distance only (no GPU pick)."""
    H = _load_method("_handle_at")

    class _Parent:
        def __init__(self, handles):
            self.crosshair_actors = {"axial": {"handles": handles}}

    class _Stub:
        view_name = "axial"

        def __init__(self, parent, display_pt):
            self.parent = parent
            self._display_pt = display_pt

        def _world_to_display(self, pos):
            # handle's known world position projects to this fixed display point
            return self._display_pt

    handles = [{"id": "h1", "position": (1.0, 2.0, 3.0)}]
    parent = _Parent(handles)
    stub = _Stub(parent, (100.0, 100.0))

    # cursor within the 14px radius of the handle's display position → hit
    assert H._handle_at(stub, (105, 103)) is handles[0]
    # cursor far away → miss
    assert H._handle_at(stub, (200, 200)) is None
    # no handles tracked → miss, never raises
    assert H._handle_at(_Stub(_Parent([]), (100.0, 100.0)), (100, 100)) is None
