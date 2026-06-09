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
    # the expensive prop pick must still exist (behavior preserved), just rate-limited
    assert "prop_picker.Pick" in hover


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
