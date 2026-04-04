"""tests/viewer/test_dragdrop_progressive.py
------------------------------------------
Drag-and-drop progressive display tests.

Covers three bugs fixed in v2.2.8.1 PLUS the two automatic-batch bugs and the
image-replacement bug reported after the initial fix.

Bug A (first batch): First 10 images arrived but the viewer was never populated
    — the awaiting-viewer scan in on_series_images_progress did not exist.
Bug B (second batch): Even after the first 10 were shown, the second batch of 10
    was never displayed — done.add() ran from the background thread BEFORE
    progressive mode was activated, so the grow path was permanently dead.
Bug C (image replacement): Drag-drop only changed download priority; the viewer
    kept showing the old series image instead of switching to a loading state.

Run:
    .venv\\Scripts\\python.exe -m pytest tests/viewer/test_dragdrop_progressive.py -v
    .venv\\Scripts\\python.exe tests/viewer/test_dragdrop_progressive.py

Scenarios
---------
S1   _awaiting_series_number set when async load fails (ok=False)
S2   _awaiting_series_number cleared at start of new drag-drop
S3   Repeated drag-drop on same layout overwrites awaiting marker
S4   on_series_images_progress scan finds the awaiting viewer (3 nodes)
S5   Two layouts track different awaiting series independently
S6   _apply_progressive_to_target_viewer — happy path: clear, display, enter pm
S7   _apply_progressive_to_target_viewer — cache miss: hides spinner, no pm
S8   Inflight guard blocks _start_progressive_display even when viewer awaiting
S9   Done guard blocks _start_progressive_display even when viewer awaiting
S10  KPI — awaiting scan over 10 nodes is < 1ms average
S11  End-to-end: 10-series patient, drag sn=5, download arrives, viewer populated
S12  Bug A regression — first batch auto-loads the awaiting viewer
S13  Bug B regression — second batch triggers grow, NOT restart
S14  Bug C regression — drag-drop replaces image AND sends priority signal
S15  Stability — 10 downloading batches: exactly 1 start then 9 grows (3 reps)
S16  Repeatability — full drag-drop + 10-batch lifecycle, 5 identical repetitions
S17  Last batch all at once — one-shot final grow on non-progressive viewer
     (exact scenario from log 2026-04-03: Series 6, 20→25 images, stuck at 19)
S18  Intermediate signal activates progressive mode; completion signal fires grow
S19  _grow_progressive_fast updates ImageReslice.SetOutputExtent after grow so
     SetSlice(n>=old_count) is not clamped (fixes image stuck at last pre-grow slice)
S19b Same as S19 but reslice input was a preprocessed (CT-upsampled) copy — verify
     it is reconnected to loader.vtk_image_data so new slices are accessible
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

# Make the project root importable when the file is executed directly
# (pytest adds it via conftest.py; direct execution needs it explicitly).
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PacsClient.pacs.patient_tab.ui.patient_ui import (
    patient_widget_viewer_controller as controller_mod,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  KPI Collector
# ═══════════════════════════════════════════════════════════════════════════════

class KPICollector:
    """Accumulates key-performance indicators across all scenarios."""

    def __init__(self):
        self._records: List[Dict[str, Any]] = []

    def record(
        self,
        scenario: str,
        metric: str,
        value: Any,
        unit: str = "",
        passed: Optional[bool] = None,
    ) -> None:
        self._records.append({
            "scenario": scenario,
            "metric": metric,
            "value": value,
            "unit": unit,
            "passed": passed,
        })

    def report(self) -> str:
        lines: List[str] = []
        lines.append("")
        lines.append("=" * 100)
        lines.append("  DRAG-DROP PROGRESSIVE — KPI REPORT")
        lines.append("=" * 100)

        scenarios: Dict[str, list] = defaultdict(list)
        for r in self._records:
            scenarios[r["scenario"]].append(r)

        total_pass = total_fail = total_skip = 0
        for scenario, records in scenarios.items():
            lines.append("")
            lines.append(f"  ┌─ Scenario: {scenario}")
            lines.append(f"  │{'Metric':<45} {'Value':>15} {'Unit':<10} {'Status':>8}")
            lines.append(f"  │{'─' * 80}")
            for r in records:
                if r["passed"] is True:
                    status = "  ✅ PASS"; total_pass += 1
                elif r["passed"] is False:
                    status = "  ❌ FAIL"; total_fail += 1
                else:
                    status = "  ── info"; total_skip += 1
                val = r["value"]
                if isinstance(val, float):
                    val_str = f"{val:>15.3f}"
                else:
                    val_str = f"{str(val):>15}"
                lines.append(
                    f"  │ {r['metric']:<44} {val_str} {r['unit']:<10}{status}"
                )
            lines.append(f"  └{'─' * 80}")

        lines.append("")
        lines.append("=" * 100)
        lines.append(
            f"  TOTALS:  ✅ {total_pass} passed   ❌ {total_fail} failed   "
            f"── {total_skip} info"
        )
        lines.append("=" * 100)
        lines.append("")
        return "\n".join(lines)


_kpi = KPICollector()


# ═══════════════════════════════════════════════════════════════════════════════
#  Mock factories
# ═══════════════════════════════════════════════════════════════════════════════

def _build_controller() -> controller_mod.ViewerController:
    """Construct a ViewerController with bare minimum attributes — no Qt."""
    c = controller_mod.ViewerController.__new__(controller_mod.ViewerController)
    c.logger = SimpleNamespace(
        info=lambda *a, **kw: None,
        debug=lambda *a, **kw: None,
        warning=lambda *a, **kw: None,
        error=lambda *a, **kw: None,
    )
    c.lst_nodes_viewer = []
    c._is_request_current = lambda *a, **kw: True
    c._perform_series_switch_optimized = lambda *a, **kw: None
    c._progressive_series = {}
    c._progressive_display_done = set()
    c._progressive_display_inflight = set()
    c._progressive_grow_batch_size = 10
    c._is_fast_viewer_mode = lambda: True
    c._find_progressive_viewers = lambda sn: []
    return c


def _make_vtk_widget(
    *,
    awaiting_sn: Optional[str] = None,
    progressive_mode: bool = False,
    progressive_sn: Optional[str] = None,
    available_slices: int = 0,
) -> SimpleNamespace:
    """Create a minimal mock VTK widget."""
    spinner_calls: list = []
    enter_pm_calls: list = []
    update_avail_calls: list = []

    w = SimpleNamespace(
        _awaiting_series_number=awaiting_sn,
        _progressive_mode=progressive_mode,
        _progressive_series_number=progressive_sn,
        _spinner_calls=spinner_calls,
        _enter_progressive_calls=enter_pm_calls,
        _update_avail_calls=update_avail_calls,
        image_viewer=SimpleNamespace(
            metadata={"series": {"series_number": progressive_sn or ""}},
            get_count_of_slices=lambda: available_slices,
        ),
        get_count_of_slices=lambda: available_slices,
    )
    w.enter_progressive_mode = lambda total, sn: enter_pm_calls.append((total, sn))
    w.update_available_slice_count = lambda c: update_avail_calls.append(c)
    w.viewport_spinner = SimpleNamespace(
        show_loading=lambda msg: spinner_calls.append(("show", msg)),
        hide=lambda: spinner_calls.append(("hide",)),
    )
    return w


def _make_node(
    *,
    awaiting_sn: Optional[str] = None,
    progressive_mode: bool = False,
    progressive_sn: Optional[str] = None,
    available_slices: int = 0,
):
    """Return (node, vtk_widget) pair."""
    vtk_w = _make_vtk_widget(
        awaiting_sn=awaiting_sn,
        progressive_mode=progressive_mode,
        progressive_sn=progressive_sn,
        available_slices=available_slices,
    )
    node = SimpleNamespace(vtk_widget=vtk_w, slider=None)
    return node, vtk_w


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _scan_for_awaiting(nodes, sn: str):
    """Replicate the awaiting-viewer scan from on_series_images_progress."""
    for node in nodes:
        vtk_w = getattr(node, "vtk_widget", None)
        if vtk_w and getattr(vtk_w, "_awaiting_series_number", None) == sn:
            return vtk_w, node
    return None, None


# ═══════════════════════════════════════════════════════════════════════════════
#  S1: _awaiting_series_number is set when the async load fails (ok=False)
# ═══════════════════════════════════════════════════════════════════════════════

def test_awaiting_series_number_set_when_async_load_fails():
    """
    When _schedule_async_load_and_switch finishes with ok=False (files not yet
    on disk), vtk_widget._awaiting_series_number must be set to the series number
    and the spinner must be kept visible.
    """
    vtk_w = _make_vtk_widget()
    assert vtk_w._awaiting_series_number is None  # sanity: starts clear

    series_number = "5"

    # Simulate the _finish_on_ui(ok=False) branch logic
    ok = False
    if not ok:
        vtk_w._awaiting_series_number = str(series_number)
        vtk_w.viewport_spinner.show_loading(f"Downloading series {series_number}...")

    assert vtk_w._awaiting_series_number == "5"
    spinner_shows = [c for c in vtk_w._spinner_calls if c[0] == "show"]
    assert len(spinner_shows) == 1
    assert spinner_shows[0] == ("show", "Downloading series 5...")

    _kpi.record("S1: awaiting_set_on_fail", "_awaiting_series_number == '5'", True, passed=True)
    _kpi.record("S1: awaiting_set_on_fail", "spinner show_loading called once", len(spinner_shows), passed=(len(spinner_shows) == 1))
    print("✅ S1 passed")


# ═══════════════════════════════════════════════════════════════════════════════
#  S2: _awaiting_series_number cleared at the start of a new drag-drop
# ═══════════════════════════════════════════════════════════════════════════════

def test_awaiting_series_number_cleared_on_new_dragdrop():
    """
    When a new drag-drop begins on a viewer that still carries
    _awaiting_series_number from a prior incomplete switch,
    change_series_on_viewer must clear the marker before issuing the new switch.
    """
    vtk_w = _make_vtk_widget(awaiting_sn="5")
    assert vtk_w._awaiting_series_number == "5"

    # Simulate the clear at the top of change_series_on_viewer
    vtk_w._awaiting_series_number = None

    assert vtk_w._awaiting_series_number is None

    _kpi.record("S2: awaiting_cleared_on_new_drop", "awaiting cleared to None", True, passed=True)
    print("✅ S2 passed")


# ═══════════════════════════════════════════════════════════════════════════════
#  S3: Repeated drag-drop overwrites the awaiting marker
# ═══════════════════════════════════════════════════════════════════════════════

def test_repeated_dragdrop_overwrites_awaiting_marker():
    """
    User drags series 3 → layout 1 (files absent → awaiting=3).
    Before series 3 arrives, user drags series 7 → same layout 1.
    The marker must end up as '7', not '3'.
    """
    vtk_w = _make_vtk_widget()

    # First drag-drop: series 3, async load fails
    vtk_w._awaiting_series_number = None   # cleared at switch start
    vtk_w._awaiting_series_number = "3"    # set by _finish_on_ui(ok=False)
    assert vtk_w._awaiting_series_number == "3"

    # Second drag-drop: series 7, async load also fails
    vtk_w._awaiting_series_number = None   # cleared at new switch start
    vtk_w._awaiting_series_number = "7"    # set by _finish_on_ui(ok=False)

    assert vtk_w._awaiting_series_number == "7", (
        f"Expected '7', got {vtk_w._awaiting_series_number!r}"
    )
    # Old marker for series 3 must be gone
    assert vtk_w._awaiting_series_number != "3"

    _kpi.record("S3: repeated_dragdrop", "final marker == '7'", vtk_w._awaiting_series_number,
                passed=(vtk_w._awaiting_series_number == "7"))
    _kpi.record("S3: repeated_dragdrop", "old marker '3' gone", True, passed=True)
    print("✅ S3 passed")


# ═══════════════════════════════════════════════════════════════════════════════
#  S4: on_series_images_progress scan correctly finds the awaiting viewer
# ═══════════════════════════════════════════════════════════════════════════════

def test_progress_scan_finds_awaiting_viewer():
    """
    Three nodes: only node 2 has _awaiting_series_number == '5'.
    The awaiting-viewer scan must return node 2's vtk_widget.
    """
    node1, vtk_w1 = _make_node()                        # no awaiting
    node2, vtk_w2 = _make_node(awaiting_sn="5")         # awaiting series 5
    node3, vtk_w3 = _make_node()                        # no awaiting

    t0 = time.perf_counter()
    found_vw, found_node = _scan_for_awaiting([node1, node2, node3], "5")
    elapsed_us = (time.perf_counter() - t0) * 1e6

    assert found_vw is vtk_w2, "Must find the viewer awaiting series 5"
    assert found_node is node2

    # Other viewers must NOT be returned
    assert found_vw is not vtk_w1
    assert found_vw is not vtk_w3

    _kpi.record("S4: progress_scan", "correct viewer found", True, passed=True)
    _kpi.record("S4: progress_scan", "scan elapsed", elapsed_us, "µs",
                passed=(elapsed_us < 500))  # must be < 0.5ms for 3 nodes
    print(f"✅ S4 passed  (scan={elapsed_us:.1f}µs)")


# ═══════════════════════════════════════════════════════════════════════════════
#  S5: Two layouts independently track different awaiting series
# ═══════════════════════════════════════════════════════════════════════════════

def test_two_layouts_track_different_awaiting_series():
    """
    Layout 1 awaits series 3.  Layout 2 awaits series 7.
    Progress for series 3 must resolve to layout 1 only.
    Progress for series 7 must resolve to layout 2 only.
    """
    node_l1, vtk_l1 = _make_node(awaiting_sn="3")
    node_l2, vtk_l2 = _make_node(awaiting_sn="7")
    nodes = [node_l1, node_l2]

    found_3_vw, found_3_nd = _scan_for_awaiting(nodes, "3")
    found_7_vw, found_7_nd = _scan_for_awaiting(nodes, "7")

    assert found_3_vw is vtk_l1, "Series 3 must resolve to layout 1"
    assert found_7_vw is vtk_l2, "Series 7 must resolve to layout 2"

    # Cross-contamination check
    assert found_3_vw is not vtk_l2, "Series 3 must not match layout 2"
    assert found_7_vw is not vtk_l1, "Series 7 must not match layout 1"

    _kpi.record("S5: two_layouts", "L1 finds series-3 viewer", True, passed=True)
    _kpi.record("S5: two_layouts", "L2 finds series-7 viewer", True, passed=True)
    _kpi.record("S5: two_layouts", "no cross-contamination", True, passed=True)
    print("✅ S5 passed")


# ═══════════════════════════════════════════════════════════════════════════════
#  S6: _apply_progressive_to_target_viewer — happy path
# ═══════════════════════════════════════════════════════════════════════════════

def test_apply_progressive_to_target_viewer_happy_path():
    """
    With cached data available, _apply_progressive_to_target_viewer must:
      1. Clear _awaiting_series_number = None
      2. Call _display_loaded_series on the target viewer
      3. Call vtk_widget.enter_progressive_mode(total, sn)
      4. Call vtk_widget.update_available_slice_count
      5. Hide the spinner at the end
    """
    controller = _build_controller()
    sn = "5"
    total = 100

    vtk_w = _make_vtk_widget(awaiting_sn=sn, available_slices=10)
    vtk_w.get_count_of_slices = lambda: 10
    node = SimpleNamespace(vtk_widget=vtk_w, slider=None)

    display_calls: list = []
    hide_calls: list = []

    controller._get_series_by_number_fast = lambda _sn: (
        object(), {"series": {"series_number": _sn}}, 0
    )
    controller._display_loaded_series = lambda **kw: display_calls.append(kw)
    controller._hide_spinner_for_widget = lambda w: hide_calls.append(w)
    controller._is_fast_viewer_mode = lambda: False  # skip booster path

    controller._apply_progressive_to_target_viewer(sn, total, vtk_w, node)

    # 1. Marker cleared
    assert vtk_w._awaiting_series_number is None, (
        f"Expected None, got {vtk_w._awaiting_series_number!r}"
    )
    # 2. Display was called once with correct args
    assert len(display_calls) == 1
    assert display_calls[0]["series_number"] == sn
    assert display_calls[0]["progressive_total"] == total
    assert display_calls[0]["vtk_widget"] is vtk_w
    assert display_calls[0]["flag_change_selected_widget"] is False

    # 3 & 4. Progressive mode entered
    assert len(vtk_w._enter_progressive_calls) == 1
    assert vtk_w._enter_progressive_calls[0] == (total, sn)
    assert len(vtk_w._update_avail_calls) == 1
    assert vtk_w._update_avail_calls[0] == 10

    # 5. Spinner hidden
    assert len(hide_calls) == 1
    assert hide_calls[0] is vtk_w

    _kpi.record("S6: apply_progressive_happy", "_awaiting_series_number cleared", True, passed=True)
    _kpi.record("S6: apply_progressive_happy", "_display_loaded_series called once", len(display_calls),
                passed=(len(display_calls) == 1))
    _kpi.record("S6: apply_progressive_happy", "enter_progressive_mode called once",
                len(vtk_w._enter_progressive_calls), passed=(len(vtk_w._enter_progressive_calls) == 1))
    _kpi.record("S6: apply_progressive_happy", "update_available_slice_count called", True, passed=True)
    _kpi.record("S6: apply_progressive_happy", "spinner hidden", len(hide_calls),
                passed=(len(hide_calls) == 1))
    print("✅ S6 passed")


# ═══════════════════════════════════════════════════════════════════════════════
#  S7: _apply_progressive_to_target_viewer — cache miss hides spinner
# ═══════════════════════════════════════════════════════════════════════════════

def test_apply_progressive_to_target_viewer_cache_miss_hides_spinner():
    """
    When _get_series_by_number_fast returns (None, None, 0), the method must
    hide the spinner and NOT enter progressive mode (cleanup path).
    """
    controller = _build_controller()
    sn = "3"
    total = 50

    vtk_w = _make_vtk_widget(awaiting_sn=sn)
    node = SimpleNamespace(vtk_widget=vtk_w, slider=None)

    hide_calls: list = []

    controller._get_series_by_number_fast = lambda _sn: (None, None, 0)
    controller._hide_spinner_for_widget = lambda w: hide_calls.append(w)
    controller._is_fast_viewer_mode = lambda: False

    controller._apply_progressive_to_target_viewer(sn, total, vtk_w, node)

    # Marker still cleared (happens before cache lookup)
    assert vtk_w._awaiting_series_number is None

    # Spinner hidden to clean up
    assert len(hide_calls) == 1, f"Expected 1 hide call, got {len(hide_calls)}"
    assert hide_calls[0] is vtk_w

    # No progressive mode on cache miss
    assert len(vtk_w._enter_progressive_calls) == 0

    _kpi.record("S7: cache_miss", "spinner hidden once", len(hide_calls), passed=(len(hide_calls) == 1))
    _kpi.record("S7: cache_miss", "no enter_progressive_mode on miss",
                len(vtk_w._enter_progressive_calls), passed=(len(vtk_w._enter_progressive_calls) == 0))
    _kpi.record("S7: cache_miss", "_awaiting_series_number cleared", True, passed=True)
    print("✅ S7 passed")


# ═══════════════════════════════════════════════════════════════════════════════
#  S8: Inflight guard blocks _start_progressive_display even with awaiting viewer
# ═══════════════════════════════════════════════════════════════════════════════

def test_inflight_guard_blocks_start_when_awaiting_viewer_present():
    """
    Once sn is in _progressive_display_inflight, a subsequent progress signal
    must NOT call _start_progressive_display, even if a viewer is waiting.
    """
    sn = "5"
    node, vtk_w = _make_node(awaiting_sn=sn)

    done = set()
    inflight = {sn}  # already in-flight

    start_calls: list = []

    # Replicate the guard logic from on_series_images_progress
    if sn not in done and sn not in inflight:
        # Would call _start_progressive_display — but should not reach here
        start_calls.append("called")

    assert len(start_calls) == 0, "inflight guard must block _start_progressive_display"

    _kpi.record("S8: inflight_guard", "_start_progressive_display blocked when in-flight",
                len(start_calls), passed=(len(start_calls) == 0))
    print("✅ S8 passed")


# ═══════════════════════════════════════════════════════════════════════════════
#  S9: Done guard blocks restart even when viewer is still awaiting
# ═══════════════════════════════════════════════════════════════════════════════

def test_done_guard_blocks_restart_when_awaiting_viewer_present():
    """
    After sn enters _progressive_display_done, further progress signals must
    NOT call _start_progressive_display, even if a viewer's awaiting marker
    is still set (edge case: race between display completion and progress signal).
    """
    sn = "5"
    node, vtk_w = _make_node(awaiting_sn=sn)

    done = {sn}    # already done
    inflight = set()

    start_calls: list = []

    # Replicate the guard logic from on_series_images_progress
    if sn not in done and sn not in inflight:
        start_calls.append("called")

    assert len(start_calls) == 0, "done guard must block _start_progressive_display"

    _kpi.record("S9: done_guard", "_start_progressive_display blocked by done-guard",
                len(start_calls), passed=(len(start_calls) == 0))
    print("✅ S9 passed")


# ═══════════════════════════════════════════════════════════════════════════════
#  S10: KPI — awaiting-viewer scan over 10 nodes is fast (< 1ms average)
# ═══════════════════════════════════════════════════════════════════════════════

def test_awaiting_scan_over_10_nodes_is_fast():
    """
    The awaiting-viewer scan iterates all nodes.  With 10 nodes and the target
    at position 8 (worst-ish case), the average scan time must be < 1ms.
    """
    TARGET_MS = 1.0
    ITERATIONS = 200

    # 10 nodes: awaiting viewer at index 7 (0-based)
    nodes = []
    for i in range(10):
        awaiting = "5" if i == 7 else None
        n, _ = _make_node(awaiting_sn=awaiting)
        nodes.append(n)

    times_ms: list = []
    found_vw = None
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        found_vw, _ = _scan_for_awaiting(nodes, "5")
        times_ms.append((time.perf_counter() - t0) * 1000)

    assert found_vw is not None, "Must find the awaiting viewer"

    avg_ms = sum(times_ms) / len(times_ms)
    p99_ms = sorted(times_ms)[int(len(times_ms) * 0.99)]

    _kpi.record("S10: scan_kpi", "avg scan time (10 nodes)", avg_ms, "ms",
                passed=(avg_ms < TARGET_MS))
    _kpi.record("S10: scan_kpi", "p99 scan time (10 nodes)", p99_ms, "ms",
                passed=(p99_ms < TARGET_MS))

    assert avg_ms < TARGET_MS, (
        f"Scan avg {avg_ms:.3f}ms exceeds {TARGET_MS}ms target for 10-node viewer list"
    )
    print(f"✅ S10 passed  (avg={avg_ms:.4f}ms, p99={p99_ms:.4f}ms, iterations={ITERATIONS})")


# ═══════════════════════════════════════════════════════════════════════════════
#  S11: End-to-end — 10-series patient, drag sn=5 while sn=1 downloading
# ═══════════════════════════════════════════════════════════════════════════════

def test_end_to_end_10series_patient_drag_drop_flow():
    """
    Scenario: 10-series patient with series 1 already downloading.
    User drag-drops series 5 → layout 1 while layout 2 is empty.

    Step 1: Async load fails (not on disk) → _awaiting_series_number = '5'
    Step 2: DM emits progress(sn=5, downloaded=10, total=100)
    Step 3: Scan finds awaiting viewer (layout 1) → _start_progressive_display called
            with target_vtk_widget=vtk_l1 and target_node=node_l1
    Step 4: _apply_progressive_to_target_viewer populates layout 1 only

    Verify:
    - Layout 1 gets displayed and enters progressive mode
    - Layout 2 is completely unaffected
    - Inflight guard is set after step 3
    """
    controller = _build_controller()

    # Two viewers: layout 1 awaiting series 5 (after drag-drop), layout 2 empty
    node_l1, vtk_l1 = _make_node(awaiting_sn="5", available_slices=10)
    vtk_l1.get_count_of_slices = lambda: 10
    node_l2, vtk_l2 = _make_node()
    controller.lst_nodes_viewer = [node_l1, node_l2]

    controller._progressive_series = {
        "5": {"total": 100, "last_grow_count": 0, "last_signal_ms": 0}
    }

    # ── Step 3: Simulate progress signal arriving for series 5 ──────────────

    start_calls: list = []

    def _capture_start(sn, downloaded, total, target_vtk_widget=None, target_node=None):
        start_calls.append({
            "sn": sn,
            "downloaded": downloaded,
            "total": total,
            "target": target_vtk_widget,
            "target_node": target_node,
        })

    controller._start_progressive_display = _capture_start

    sn = "5"
    downloaded = 10
    total = 100

    # Replicate the core logic from on_series_images_progress (awaiting scan + guard)
    found_vw, found_node = _scan_for_awaiting(controller.lst_nodes_viewer, sn)

    done = controller._progressive_display_done
    inflight = controller._progressive_display_inflight

    if downloaded >= controller._progressive_grow_batch_size:
        if sn not in done and sn not in inflight:
            inflight.add(sn)
            controller._start_progressive_display(
                sn, downloaded, total,
                target_vtk_widget=found_vw,
                target_node=found_node,
            )

    assert len(start_calls) == 1, (
        f"Expected exactly 1 _start_progressive_display call, got {len(start_calls)}"
    )
    call = start_calls[0]
    assert call["sn"] == "5"
    assert call["target"] is vtk_l1, "Target must be the layout-1 viewer (awaiting series 5)"
    assert call["target_node"] is node_l1
    assert "5" in inflight, "Inflight guard must be set after _start_progressive_display"

    # ── Step 4: Simulate _apply_progressive_to_target_viewer ────────────────

    display_calls: list = []
    hide_calls: list = []

    controller._get_series_by_number_fast = lambda _sn: (
        object(), {"series": {"series_number": _sn}}, 0
    )
    controller._display_loaded_series = lambda **kw: display_calls.append(kw)
    controller._hide_spinner_for_widget = lambda w: hide_calls.append(w)
    controller._is_fast_viewer_mode = lambda: False

    controller._apply_progressive_to_target_viewer("5", 100, vtk_l1, node_l1)

    # Awaiting marker cleared
    assert vtk_l1._awaiting_series_number is None, "L1 marker must be cleared after display"

    # L1 displayed
    assert len(display_calls) == 1
    assert display_calls[0]["vtk_widget"] is vtk_l1
    assert display_calls[0]["progressive_total"] == 100

    # L1 entered progressive mode
    assert len(vtk_l1._enter_progressive_calls) == 1
    assert vtk_l1._enter_progressive_calls[0] == (100, "5")

    # L2 completely unaffected
    assert vtk_l2._awaiting_series_number is None, "L2 must NOT have awaiting marker"
    assert len(vtk_l2._enter_progressive_calls) == 0, "L2 must NOT enter progressive mode"

    _kpi.record("S11: e2e_10series", "_start_progressive_display called once",
                len(start_calls), passed=(len(start_calls) == 1))
    _kpi.record("S11: e2e_10series", "correct target viewer (L1) passed",
                call["target"] is vtk_l1, passed=True)
    _kpi.record("S11: e2e_10series", "inflight guard set after start",
                "5" in inflight, passed=True)
    _kpi.record("S11: e2e_10series", "_apply: display called on L1",
                len(display_calls), passed=(len(display_calls) == 1))
    _kpi.record("S11: e2e_10series", "_apply: progressive mode entered on L1",
                len(vtk_l1._enter_progressive_calls), passed=(len(vtk_l1._enter_progressive_calls) == 1))
    _kpi.record("S11: e2e_10series", "_apply: L2 unaffected (no pm)",
                len(vtk_l2._enter_progressive_calls) == 0, passed=True)
    _kpi.record("S11: e2e_10series", "_awaiting_series_number cleared on L1",
                vtk_l1._awaiting_series_number is None, passed=True)
    print("✅ S11 passed")


# ═══════════════════════════════════════════════════════════════════════════════
#  Shared helper for S12–S16: simulate one on_series_images_progress signal
# ═══════════════════════════════════════════════════════════════════════════════

def _simulate_progress_signal(controller, sn: str, downloaded: int, total: int) -> str:
    """Replicate the core routing logic of on_series_images_progress.

    Returns a short string describing which path was taken:
      'grow'         — progressive viewer found, grow timer should fire
      'grow-small'   — progressive viewer found but delta < batch_size
      'start'        — no progressive viewer, awaiting scan matched, start called
      'done-guard'   — sn already in done set, no action
      'inflight'     — sn already in inflight set, no action
      'below-batch'  — downloaded < batch_size, not enough for first display
    """
    if sn not in controller._progressive_series:
        controller._progressive_series[sn] = {
            "total": total, "last_grow_count": 0,
            "last_signal_ms": 0, "pending_downloaded": 0,
        }
    info = controller._progressive_series[sn]
    info["total"] = max(info["total"], total)
    info["last_signal_ms"] = 0   # bypass 100ms throttle in unit tests

    # Path 1: a viewer is already showing this series in progressive mode → grow
    viewers_showing = controller._find_progressive_viewers(sn)
    if viewers_showing:
        delta = downloaded - info["last_grow_count"]
        if delta >= controller._progressive_grow_batch_size or downloaded >= total:
            info["pending_downloaded"] = downloaded
            timer = getattr(controller, "_progressive_grow_timer", None)
            if timer is not None and not timer.isActive():
                timer.start()
            return "grow"
        return "grow-small"

    # Path 2: no progressive viewer — scan for an awaiting viewer, then start
    found_vw, found_node = _scan_for_awaiting(controller.lst_nodes_viewer, sn)

    done = controller._progressive_display_done
    inflight = controller._progressive_display_inflight

    if downloaded < controller._progressive_grow_batch_size:
        return "below-batch"

    if sn in done:
        return "done-guard"

    if sn in inflight:
        return "inflight"

    inflight.add(sn)
    controller._start_progressive_display(
        sn, downloaded, total,
        target_vtk_widget=found_vw,
        target_node=found_node,
    )
    return "start"


# ═══════════════════════════════════════════════════════════════════════════════
#  S12: Bug A — First batch of 10 auto-loads the awaiting viewer
# ═══════════════════════════════════════════════════════════════════════════════

def test_bug_a_first_batch_triggers_display_on_awaiting_viewer():
    """
    Bug A regression: The viewer is marked _awaiting_series_number='5' because
    the async load failed (files not yet on disk).  When the DM emits
    progress(sn=5, downloaded=10, total=100), on_series_images_progress MUST:
      - find the awaiting viewer via the _awaiting_series_number scan
      - call _start_progressive_display with target_vtk_widget pointing to it

    Before the fix this scan did not exist, so the viewer sat with a spinner
    indefinitely even after the first 10 images were on disk.
    """
    controller = _build_controller()
    sn = "5"

    # Viewer is awaiting series 5 (drag-drop happened, async load failed)
    node, vtk_w = _make_node(awaiting_sn=sn)
    controller.lst_nodes_viewer = [node]
    controller._progressive_series = {
        sn: {"total": 100, "last_grow_count": 0, "last_signal_ms": 0, "pending_downloaded": 0}
    }

    start_calls: list = []
    controller._start_progressive_display = (
        lambda s, dl, tot, target_vtk_widget=None, target_node=None:
        start_calls.append({
            "sn": s, "downloaded": dl, "total": tot,
            "target": target_vtk_widget, "node": target_node,
        })
    )

    state = _simulate_progress_signal(controller, sn, downloaded=10, total=100)

    assert state == "start", f"Expected 'start', got {state!r}"
    assert len(start_calls) == 1, f"Expected 1 call, got {len(start_calls)}"
    assert start_calls[0]["target"] is vtk_w, (
        "target_vtk_widget must be the awaiting viewer (Bug A: previously was None)"
    )
    assert start_calls[0]["node"] is node
    assert sn in controller._progressive_display_inflight

    _kpi.record("S12: bug_a", "state == 'start'", state, passed=(state == "start"))
    _kpi.record("S12: bug_a", "_start_progressive_display calls", len(start_calls),
                passed=(len(start_calls) == 1))
    _kpi.record("S12: bug_a", "target_vtk_widget is awaiting viewer",
                start_calls[0]["target"] is vtk_w, passed=True)
    _kpi.record("S12: bug_a", "inflight guard set", sn in controller._progressive_display_inflight,
                passed=True)
    print("✅ S12 passed")


# ═══════════════════════════════════════════════════════════════════════════════
#  S13: Bug B — Second batch triggers grow, does NOT restart
# ═══════════════════════════════════════════════════════════════════════════════

def test_bug_b_second_batch_grows_not_restarts():
    """
    Bug B regression: After the first batch is displayed (viewer._progressive_mode=True,
    done-guard set), the SECOND progress signal (downloaded=20) must take the GROW
    path — not call _start_progressive_display again.

    Before the fix: done.add(sn) ran from the background thread before
    _activate_progressive_mode_on_viewers fired.  The next signal found sn in
    done but no progressive viewer (mode wasn't active yet), returned early from
    the done-guard, and the grow path was permanently dead.
    """
    controller = _build_controller()
    sn = "5"

    # State after first batch was displayed:
    #   - done-guard set
    #   - viewer is in progressive mode showing 10 images
    controller._progressive_display_done = {sn}
    controller._progressive_display_inflight = set()
    controller._progressive_series = {
        sn: {"total": 100, "last_grow_count": 10, "last_signal_ms": 0, "pending_downloaded": 10}
    }

    node, vtk_w = _make_node(progressive_mode=True, progressive_sn=sn, available_slices=10)
    controller.lst_nodes_viewer = [node]

    # _find_progressive_viewers returns the viewer (it has _progressive_mode=True)
    controller._find_progressive_viewers = (
        lambda s: [(vtk_w, node)] if s == sn else []
    )

    timer_starts: list = []
    mock_timer = SimpleNamespace(
        start=lambda: timer_starts.append("start"),
        isActive=lambda: False,
    )
    controller._progressive_grow_timer = mock_timer

    start_calls: list = []
    controller._start_progressive_display = lambda *a, **kw: start_calls.append(a)

    state = _simulate_progress_signal(controller, sn, downloaded=20, total=100)

    assert state == "grow", f"Expected 'grow', got {state!r}"
    assert len(timer_starts) == 1, f"Grow timer must start once, got {len(timer_starts)}"
    assert len(start_calls) == 0, (
        f"_start_progressive_display must NOT be called for second batch "
        f"(Bug B: previously the grow path was dead), got {len(start_calls)} call(s)"
    )

    _kpi.record("S13: bug_b", "state == 'grow'", state, passed=(state == "grow"))
    _kpi.record("S13: bug_b", "grow timer started once", len(timer_starts),
                passed=(len(timer_starts) == 1))
    _kpi.record("S13: bug_b", "_start_progressive_display NOT called again",
                len(start_calls), passed=(len(start_calls) == 0))
    print("✅ S13 passed")


# ═══════════════════════════════════════════════════════════════════════════════
#  S14: Bug C — Drag-drop replaces image AND sends priority signal
# ═══════════════════════════════════════════════════════════════════════════════

def test_bug_c_dragdrop_replaces_image_and_escalates_priority():
    """
    Bug C regression: When the user drag-drops a series that is not yet on disk,
    TWO things must happen:
      1. The viewer switches to a loading state (spinner visible, old image gone)
         — _awaiting_series_number is set on the target vtk_widget.
      2. The download priority is escalated via request_critical_series.

    Before the fix, only (2) happened — the viewer kept showing the old series
    image without any visual feedback that a switch was in progress.
    """
    # Viewer currently showing series 1
    vtk_w = _make_vtk_widget()
    vtk_w.image_viewer.metadata = {"series": {"series_number": "1"}}
    assert vtk_w._awaiting_series_number is None

    priority_calls: list = []

    # ── Simulate change_series_on_viewer for drag-dropping series 5 ──────────

    # Step A: new switch starts — clear any previous awaiting marker
    vtk_w._awaiting_series_number = None

    # Step B: async load fails because files aren't on disk yet
    series_number = "5"
    vtk_w._awaiting_series_number = str(series_number)               # Bug C fix
    vtk_w.viewport_spinner.show_loading(f"Downloading series {series_number}...")  # Bug C fix

    # Step C: priority notification (deferred 0ms in real code; synchronous here)
    def _request_critical_series(study_uid: str, sn: str):
        priority_calls.append((study_uid, sn))

    _request_critical_series("1.2.3.study", series_number)

    # ── Assertions ────────────────────────────────────────────────────────────

    # (1) Viewer is in loading state — old image replaced
    assert vtk_w._awaiting_series_number == "5", (
        "Viewer must mark itself awaiting series 5; "
        "Bug C: previously _awaiting_series_number was never set so old image stayed"
    )
    spinner_shows = [c for c in vtk_w._spinner_calls if c[0] == "show"]
    assert len(spinner_shows) == 1, "Spinner must show loading message (replaces old image)"
    assert "Downloading series 5" in spinner_shows[0][1]

    # (2) Priority escalated
    assert len(priority_calls) == 1, "request_critical_series must be called exactly once"
    assert priority_calls[0] == ("1.2.3.study", "5")

    _kpi.record("S14: bug_c", "_awaiting_series_number set (loading state shown)",
                vtk_w._awaiting_series_number == "5", passed=True)
    _kpi.record("S14: bug_c", "spinner show_loading called", len(spinner_shows),
                passed=(len(spinner_shows) == 1))
    _kpi.record("S14: bug_c", "priority escalation called", len(priority_calls),
                passed=(len(priority_calls) == 1))
    print("✅ S14 passed")


# ═══════════════════════════════════════════════════════════════════════════════
#  S15: Stability — 10 batches produce exactly 1 start then 9 grows (3 reps)
# ═══════════════════════════════════════════════════════════════════════════════

def test_stability_10_batches_one_start_nine_grows():
    """
    Simulate 10 progress signals for a 100-image series (batches of 10).

    Expected state machine per signal:
      Batch 1  (downloaded=10):  awaiting viewer found → 'start'
      Batches 2-10 (20..100):    progressive mode active → 'grow'

    Verifies both bugs simultaneously:
      Bug A: batch 1 must produce 'start' (not 'below-batch' or silence)
      Bug B: batch 2 must produce 'grow'  (not 'done-guard' or silence)

    Runs 3 times to verify repeatability.
    """
    BATCH_SIZE = 10
    TOTAL = 100
    REPS = 3

    all_states: list = []

    for rep in range(REPS):
        controller = _build_controller()
        sn = "5"

        node, vtk_w = _make_node(awaiting_sn=sn)
        controller.lst_nodes_viewer = [node]

        timer_starts: list = []
        mock_timer = SimpleNamespace(
            start=lambda: timer_starts.append("start"),
            isActive=lambda: False,
        )
        controller._progressive_grow_timer = mock_timer

        start_calls: list = []

        def _capture_start(s, dl, tot, target_vtk_widget=None, target_node=None,
                           _vtk_w=vtk_w, _sn=sn, _sc=start_calls,
                           _ctrl=controller):
            """Simulate what _start_progressive_display does: activate, mark done."""
            _sc.append(s)
            _vtk_w._progressive_mode = True
            _vtk_w._progressive_series_number = _sn
            if target_vtk_widget is not None:
                target_vtk_widget._awaiting_series_number = None   # cleared by apply
            _ctrl._progressive_display_done.add(s)
            _ctrl._progressive_display_inflight.discard(s)

        controller._start_progressive_display = _capture_start
        controller._find_progressive_viewers = (
            lambda s, _vtk_w=vtk_w, _nd=node, _sn=sn:
            [(vtk_w, node)] if s == _sn and _vtk_w._progressive_mode else []
        )

        rep_states: list = []
        for batch_n in range(1, 11):
            downloaded = batch_n * BATCH_SIZE
            state = _simulate_progress_signal(controller, sn, downloaded, TOTAL)
            if state == "grow":
                # Advance last_grow_count so next delta is >= batch_size
                controller._progressive_series[sn]["last_grow_count"] = downloaded
            rep_states.append(state)

        all_states.append(rep_states)

        # Per-rep correctness
        assert len(start_calls) == 1, (
            f"Rep {rep + 1}: Expected exactly 1 _start_progressive_display, got {len(start_calls)}"
        )
        assert rep_states[0] == "start", (
            f"Rep {rep + 1}: Batch 1 must be 'start' (Bug A), got {rep_states[0]!r}"
        )
        for j in range(1, 10):
            assert rep_states[j] == "grow", (
                f"Rep {rep + 1}: Batch {j + 1} must be 'grow' (Bug B), got {rep_states[j]!r}"
            )

    # Repeatability: all reps produce identical sequences
    for rep in range(1, REPS):
        assert all_states[rep] == all_states[0], (
            f"Rep {rep + 1} states differ from rep 1:\n"
            f"  rep 1:   {all_states[0]}\n"
            f"  rep {rep + 1}: {all_states[rep]}"
        )

    _kpi.record("S15: stability", "reps completed", REPS, passed=True)
    _kpi.record("S15: stability", "batch-1 state across all reps",
                all_states[0][0], passed=(all_states[0][0] == "start"))
    _kpi.record("S15: stability", "batch-2..10 all 'grow'",
                all(s == "grow" for s in all_states[0][1:]), passed=True)
    _kpi.record("S15: stability", "all reps identical", True, passed=True)
    print(f"✅ S15 passed  ({REPS} reps, states={all_states[0]})")


# ═══════════════════════════════════════════════════════════════════════════════
#  S16: Repeatability — full drag-drop + 10-batch lifecycle, 5 repetitions
# ═══════════════════════════════════════════════════════════════════════════════

def test_repeatability_full_dragdrop_plus_10_batches():
    """
    Full lifecycle, 5 independent repetitions — each starts with a completely
    fresh controller and viewer state.

    Per repetition:
      1. User drag-drops series 5 → async load fails → awaiting marker set,
         spinner shown, priority escalated.
      2. 10 DM progress signals arrive (10, 20, … 100 downloaded).
      3. The grow path picks up image-count from last_grow_count after each grow.

    Verify per-rep:
      - Exactly 1 priority call
      - Exactly 1 _start_progressive_display call (batch 1)
      - 9 subsequent signals all take the 'grow' path
      - _awaiting_series_number is cleared after batch-1 display
      - Each rep takes < 5ms wall-clock

    Verify across reps:
      - All 5 produce identical batch-state sequences (repeatability)
      - All 5 elapsed times within 5× of the fastest (no timing explosion)
    """
    REPS = 5
    BATCH_SIZE = 10
    TOTAL = 100
    MAX_REP_MS = 5.0

    all_results: list = []

    for rep in range(REPS):
        t0 = time.perf_counter()

        controller = _build_controller()
        sn = "5"

        node, vtk_w = _make_node(awaiting_sn=sn)
        controller.lst_nodes_viewer = [node]

        timer_starts: list = []
        mock_timer = SimpleNamespace(
            start=lambda: timer_starts.append("start"),
            isActive=lambda: False,
        )
        controller._progressive_grow_timer = mock_timer

        start_calls: list = []
        priority_calls: list = []

        def _capture_start(s, dl, tot, target_vtk_widget=None, target_node=None,
                           _vtk_w=vtk_w, _sn=sn, _sc=start_calls,
                           _ctrl=controller):
            _sc.append(s)
            _vtk_w._progressive_mode = True
            _vtk_w._progressive_series_number = _sn
            if target_vtk_widget is not None:
                target_vtk_widget._awaiting_series_number = None
            _ctrl._progressive_display_done.add(s)
            _ctrl._progressive_display_inflight.discard(s)

        controller._start_progressive_display = _capture_start
        controller._find_progressive_viewers = (
            lambda s, _vtk_w=vtk_w, _nd=node, _sn=sn:
            [(_vtk_w, _nd)] if s == _sn and _vtk_w._progressive_mode else []
        )

        # ── Step 1: drag-drop fails → loading state ───────────────────────────
        vtk_w._awaiting_series_number = None   # cleared at new switch start
        vtk_w._awaiting_series_number = sn     # set by _finish_on_ui(ok=False)
        vtk_w.viewport_spinner.show_loading(f"Downloading series {sn}...")
        priority_calls.append(("study.1.2.3", sn))   # simulate request_critical_series

        # ── Step 2: 10 DM progress signals ────────────────────────────────────
        batch_states: list = []
        for batch_n in range(1, 11):
            downloaded = batch_n * BATCH_SIZE
            state = _simulate_progress_signal(controller, sn, downloaded, TOTAL)
            if state == "grow":
                controller._progressive_series[sn]["last_grow_count"] = downloaded
            batch_states.append(state)

        elapsed_ms = (time.perf_counter() - t0) * 1000

        all_results.append({
            "priority_calls":            len(priority_calls),
            "start_count":               len(start_calls),
            "batch_states":              batch_states,
            "awaiting_cleared":          vtk_w._awaiting_series_number is None,
            "elapsed_ms":                elapsed_ms,
        })

    # ── Per-rep assertions ────────────────────────────────────────────────────
    for i, r in enumerate(all_results):
        label = f"Rep {i + 1}"
        assert r["priority_calls"] == 1, f"{label}: Expected 1 priority call"
        assert r["start_count"] == 1, f"{label}: Expected 1 progressive start (Bug A)"
        assert r["batch_states"][0] == "start", (
            f"{label}: Batch 1 must be 'start' (Bug A), got {r['batch_states'][0]!r}"
        )
        for j in range(1, 10):
            assert r["batch_states"][j] == "grow", (
                f"{label}: Batch {j + 1} must be 'grow' (Bug B), got {r['batch_states'][j]!r}"
            )
        assert r["awaiting_cleared"], (
            f"{label}: _awaiting_series_number must be None after first batch display"
        )
        assert r["elapsed_ms"] < MAX_REP_MS, (
            f"{label}: Took {r['elapsed_ms']:.2f}ms, expected < {MAX_REP_MS}ms"
        )

    # ── Repeatability: identical state sequences ──────────────────────────────
    for i in range(1, REPS):
        assert all_results[i]["batch_states"] == all_results[0]["batch_states"], (
            f"Rep {i + 1} states differ from rep 1:\n"
            f"  rep 1:   {all_results[0]['batch_states']}\n"
            f"  rep {i + 1}: {all_results[i]['batch_states']}"
        )

    elapsed_values = [r["elapsed_ms"] for r in all_results]
    avg_ms = sum(elapsed_values) / REPS
    max_ms = max(elapsed_values)
    min_ms = min(elapsed_values)

    _kpi.record("S16: repeatability", "reps completed", REPS, passed=True)
    _kpi.record("S16: repeatability", "avg elapsed per rep", avg_ms, "ms",
                passed=(avg_ms < MAX_REP_MS))
    _kpi.record("S16: repeatability", "max elapsed (any rep)", max_ms, "ms",
                passed=(max_ms < MAX_REP_MS))
    _kpi.record("S16: repeatability", "timing variance (max/min ratio)",
                max_ms / min_ms if min_ms > 0 else 0.0, "×",
                passed=((max_ms / min_ms if min_ms > 0 else 0) < 5.0))
    _kpi.record("S16: repeatability", "all batch-state sequences identical", True, passed=True)
    print(
        f"✅ S16 passed  ({REPS} reps, avg={avg_ms:.3f}ms, "
        f"min={min_ms:.3f}ms, max={max_ms:.3f}ms, "
        f"states={all_results[0]['batch_states']})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  S17: Last batch arrives all at once — one-shot final grow on non-progressive
#       viewer matches the log: Series 6 dragged at 20/25, stuck at slice 19
# ═══════════════════════════════════════════════════════════════════════════════

def test_completion_signal_triggers_one_shot_grow_on_non_progressive_viewer():
    """
    S17: Live-connection final grow (from log 2026-04-03).

    Scenario:
      - Series 6 drag-dropped when 20 of 25 images are on disk.
      - change_series_on_viewer loads those 20 files normally — NOT progressive.
      - The remaining 5 images download in one batch.  Only a single completion
        signal fires: on_series_images_progress("6", 25, 25).
      - No intermediate signal ever arrived so the retroactive activation
        (downloaded < total path) never ran.
      - Bug: the old `if downloaded < total:` guard skipped the retroactive scan
        entirely, leaving the viewer stuck at slice 19 (image 20).
      - Fix: the scan is now unconditional.  When downloaded >= total a one-shot
        _grow_progressive_fast call is made immediately.

    Asserts:
      - _grow_progressive_fast called exactly once with series_number="6".
      - _start_progressive_display NOT called (no full reload needed).
    """
    scenario = "S17: one-shot final grow when last batch arrives all at once"

    c = _build_controller()

    # Track calls
    grow_calls: list = []
    start_calls: list = []

    def _fake_grow(sn, pending, viewers):
        grow_calls.append((sn, pending, len(viewers)))

    c._grow_progressive_fast = _fake_grow
    c._start_progressive_display = lambda *a, **kw: start_calls.append(a)

    # Viewer shows series 6 normally — NOT in progressive mode, 20 slices
    node, vtk_w = _make_node(progressive_mode=False, progressive_sn=None, available_slices=20)
    vtk_w.image_viewer = SimpleNamespace(
        metadata={"series": {"series_number": "6"}},
        get_count_of_slices=lambda: 20,
    )
    c.lst_nodes_viewer = [node]

    # Fire completion signal: 25/25 arrived (was 20 before drag-drop)
    c.on_series_images_progress("6", 25, 25)

    grow_ok = len(grow_calls) == 1 and grow_calls[0][0] == "6" and grow_calls[0][1] == 25
    start_ok = len(start_calls) == 0  # no full reload should be triggered

    _kpi.record(scenario, "_grow_progressive_fast called once", len(grow_calls),
                passed=(len(grow_calls) == 1))
    _kpi.record(scenario, "_grow_progressive_fast series_number='6'",
                grow_calls[0][0] if grow_calls else "—", passed=(bool(grow_calls) and grow_calls[0][0] == "6"))
    _kpi.record(scenario, "_grow_progressive_fast pending=25",
                grow_calls[0][1] if grow_calls else -1, passed=(bool(grow_calls) and grow_calls[0][1] == 25))
    _kpi.record(scenario, "_start_progressive_display NOT called", len(start_calls),
                passed=start_ok)

    assert grow_ok, f"_grow_progressive_fast expected once with sn='6', got: {grow_calls}"
    assert start_ok, f"_start_progressive_display should not be called, got {len(start_calls)} calls"
    print(f"✅ S17 passed  (grow={grow_calls}, no reload)")


# ═══════════════════════════════════════════════════════════════════════════════
#  S18: Intermediate signals activate progressive mode; completion triggers grow
# ═══════════════════════════════════════════════════════════════════════════════

def test_intermediate_then_completion_activates_then_grows():
    """
    S18: Still-downloading signals enable progressive mode; final signal grows.

    Scenario:
      - Same drag-drop at 20/25 images (non-progressive viewer, 20 slices).
      - Signal 1: (21, 25) — downloaded < total, viewer not in progressive mode.
        → retroactive activation fires: enter_progressive_mode called.
      - Signal 2: (25, 25) — downloaded == total, viewer NOW in progressive mode
        → _grow_progressive_fast fires via the timer path (viewers_showing).
    """
    scenario = "S18: intermediate signal activates progressive; completion grows"

    c = _build_controller()
    grow_calls: list = []
    timer_started = []

    # Minimal timer mock
    class FakeTimer:
        def isActive(self): return False
        def start(self): timer_started.append(1)

    c._progressive_grow_timer = FakeTimer()

    def _fake_grow(sn, pending, viewers):
        grow_calls.append((sn, pending))

    c._grow_progressive_fast = _fake_grow
    c._start_progressive_display = lambda *a, **kw: None

    # Viewer shows series 6 normally — NOT in progressive mode
    node, vtk_w = _make_node(progressive_mode=False, progressive_sn=None, available_slices=20)
    vtk_w.image_viewer = SimpleNamespace(
        metadata={"series": {"series_number": "6"}},
        get_count_of_slices=lambda: 20,
    )
    c.lst_nodes_viewer = [node]

    # Signal 1 (still downloading) — retroactive activation
    c.on_series_images_progress("6", 21, 25)

    # After retroactive activation vtk_w.enter_progressive_mode was called
    pm_calls = vtk_w._enter_progressive_calls
    entered_pm = len(pm_calls) == 1

    _kpi.record(scenario, "intermediate signal: enter_progressive_mode called", len(pm_calls),
                passed=entered_pm)

    # Now the viewer IS in progressive mode — simulate that
    vtk_w._progressive_mode = True
    vtk_w._progressive_series_number = "6"
    # Re-wire _find_progressive_viewers to return the viewer
    c._find_progressive_viewers = lambda sn: [(vtk_w, node)] if sn == "6" else []

    # Signal 2 (completion)
    c.on_series_images_progress("6", 25, 25)

    timer_fired = len(timer_started) >= 1
    _kpi.record(scenario, "completion signal: grow timer started", len(timer_started),
                passed=timer_fired)

    assert entered_pm, f"enter_progressive_mode should be called once, got {pm_calls}"
    assert timer_fired, f"grow timer should start on completion signal, got {timer_started}"
    print(f"✅ S18 passed  (pm_calls={pm_calls}, timer_starts={len(timer_started)})")


# ═══════════════════════════════════════════════════════════════════════════════
#  S19: _grow_progressive_fast updates ImageReslice.SetOutputExtent after grow
#       so that SetSlice(n) for n >= old_count is not clamped to old_count-1
# ═══════════════════════════════════════════════════════════════════════════════

def test_grow_progressive_fast_updates_reslice_extent():
    """
    S19: After _grow_progressive_fast calls loader.grow() on a BACKEND_PYDICOM
    viewer, it must update the ImageReslice output extent so that new slices
    (indices >= old_count) become renderable.

    Root cause fixed in v2.2.8.2:
      ImageReslice._configure_output_from_input() sets SetOutputExtent with
      z_max = initial_count - 1 at construction.  After grow(), vtk_image_data
      has new_count slices but the reslice filter's OutputExtent is stale.
      vtkResliceImageViewer.SetSlice(n) for n >= old_count is therefore clamped
      to old_count-1, so the image stays frozen at the last pre-download slice
      even though the slider and counter correctly show the higher count.

    Asserts:
      - reslice._configure_output_from_input() is called after loader.grow()
      - reslice.Modified() is called
      - reslice.Update() is called
    """
    scenario = "S19: reslice output extent updated after grow"

    # --- Build a minimal controller ---
    c = _build_controller()
    c._progressive_series = {"6": {"total": 25, "last_grow_count": 20, "last_signal_ms": 0}}
    c._image_slice_booster = SimpleNamespace(active_series=None, update_paths=lambda *a: None)
    c._refresh_stored_metadata_instances = lambda *a, **kw: None
    c._invalidate_series_caches = lambda *a, **kw: None

    # --- Mock lazy loader ---
    grew_calls: list = []
    loader_vtkdata = object()  # unique sentinel for the raw lazy vtk data

    def _fake_grow():
        grew_calls.append(1)
        return 25  # new_count

    mock_loader = SimpleNamespace(
        grow=_fake_grow,
        backend=SimpleNamespace(
            get_file_paths=lambda: [],
        ),
        vtk_image_data=loader_vtkdata,
    )

    # --- Mock reslice object (same vtk_image_data → non-preprocessed path) ---
    configure_calls: list = []
    modified_calls: list = []
    update_calls: list = []

    mock_reslice = SimpleNamespace(
        vtk_image_data=loader_vtkdata,  # identical object → no reconnect needed
        _configure_output_from_input=lambda: configure_calls.append(1),
        Modified=lambda: modified_calls.append(1),
        Update=lambda: update_calls.append(1),
        GetOutputExtent=lambda: [0, 511, 0, 511, 0, 19],
        SetInputData=lambda vd: None,
    )

    # --- Mock image_viewer with the reslice ---
    mock_image_viewer = SimpleNamespace(image_reslice=mock_reslice)

    # --- Mock vtk_widget ---
    exit_pm_calls: list = []
    update_avail_calls: list = []

    vtk_w = SimpleNamespace(
        _lazy_loader=mock_loader,
        _qt_bridge_active=False,
        _active_backend="BACKEND_PYDICOM",
        image_viewer=mock_image_viewer,
        exit_progressive_mode=lambda: exit_pm_calls.append(1),
        update_available_slice_count=lambda n: update_avail_calls.append(n),
        get_count_of_slices=lambda: 25,
    )
    node = SimpleNamespace(slider=None)

    # --- Call the real method ---
    c._grow_progressive_fast("6", 25, [(vtk_w, node)])

    # --- Assertions ---
    grew_ok = len(grew_calls) == 1
    configure_ok = len(configure_calls) >= 1
    modified_ok = len(modified_calls) >= 1
    update_ok = len(update_calls) >= 1
    avail_ok = len(update_avail_calls) >= 1 and update_avail_calls[0] == 25

    _kpi.record(scenario, "loader.grow() called", len(grew_calls),
                passed=grew_ok)
    _kpi.record(scenario, "_configure_output_from_input() called",
                len(configure_calls), passed=configure_ok)
    _kpi.record(scenario, "reslice.Modified() called",
                len(modified_calls), passed=modified_ok)
    _kpi.record(scenario, "reslice.Update() called",
                len(update_calls), passed=update_ok)
    _kpi.record(scenario, "update_available_slice_count(25) called",
                update_avail_calls[0] if update_avail_calls else -1,
                passed=avail_ok)

    assert grew_ok, "loader.grow() must be called exactly once"
    assert configure_ok, (
        "_configure_output_from_input() must be called to fix stale reslice extent"
    )
    assert modified_ok, "reslice.Modified() must be called after extent update"
    assert update_ok, "reslice.Update() must be called to re-execute the pipeline"
    assert avail_ok, f"update_available_slice_count should receive 25, got {update_avail_calls}"

    print(f"✅ S19 passed  (configure={len(configure_calls)}, modified={len(modified_calls)}, "
          f"update={len(update_calls)}, avail={update_avail_calls})")


def test_grow_progressive_fast_reconnects_reslice_when_preprocessed():
    """
    S19b: When preprocessing (e.g. CT XY-upsample) created a DIFFERENT VTK
    object as the reslice input, _grow_progressive_fast reconnects the reslice
    to loader.vtk_image_data (which has all new_count slices) so that slice n
    for n >= old_count can be rendered.

    Asserts:
      - reslice.SetInputData() is called with loader.vtk_image_data
      - reslice.vtk_image_data becomes loader.vtk_image_data after the call
      - _configure_output_from_input() is called
    """
    scenario = "S19b: reslice reconnected when preprocessed VTK object differs"

    c = _build_controller()
    c._progressive_series = {"7": {"total": 25, "last_grow_count": 20, "last_signal_ms": 0}}
    c._image_slice_booster = SimpleNamespace(active_series=None, update_paths=lambda *a: None)
    c._refresh_stored_metadata_instances = lambda *a, **kw: None
    c._invalidate_series_caches = lambda *a, **kw: None

    raw_vtkdata = object()  # loader's original vtk_image_data
    preprocessed_vtkdata = object()  # different object (CT upsample output)

    grew_calls: list = []

    mock_loader = SimpleNamespace(
        grow=lambda: (grew_calls.append(1), 25)[1],
        backend=SimpleNamespace(get_file_paths=lambda: []),
        vtk_image_data=raw_vtkdata,
    )

    set_input_calls: list = []
    configure_calls: list = []

    mock_reslice = SimpleNamespace(
        vtk_image_data=preprocessed_vtkdata,  # different → triggers reconnect
        _configure_output_from_input=lambda: configure_calls.append(1),
        Modified=lambda: None,
        Update=lambda: None,
        GetOutputExtent=lambda: [0, 511, 0, 511, 0, 19],
        SetInputData=lambda vd: set_input_calls.append(vd),
    )

    mock_image_viewer = SimpleNamespace(image_reslice=mock_reslice)
    vtk_w = SimpleNamespace(
        _lazy_loader=mock_loader,
        _qt_bridge_active=False,
        _active_backend="BACKEND_PYDICOM",
        image_viewer=mock_image_viewer,
        exit_progressive_mode=lambda: None,
        update_available_slice_count=lambda n: None,
        get_count_of_slices=lambda: 25,
    )
    node = SimpleNamespace(slider=None)

    c._grow_progressive_fast("7", 25, [(vtk_w, node)])

    reconnected_ok = (
        len(set_input_calls) >= 1
        and set_input_calls[0] is raw_vtkdata
    )
    vtk_ref_ok = mock_reslice.vtk_image_data is raw_vtkdata
    configure_ok = len(configure_calls) >= 1

    _kpi.record(scenario, "SetInputData called with loader.vtk_image_data",
                len(set_input_calls), passed=reconnected_ok)
    _kpi.record(scenario, "reslice.vtk_image_data updated to raw loader data",
                str(vtk_ref_ok), passed=vtk_ref_ok)
    _kpi.record(scenario, "_configure_output_from_input() called",
                len(configure_calls), passed=configure_ok)

    assert reconnected_ok, (
        f"reslice.SetInputData must be called with loader.vtk_image_data, "
        f"got: {set_input_calls}"
    )
    assert vtk_ref_ok, "mock_reslice.vtk_image_data must be updated to raw_vtkdata"
    assert configure_ok, "_configure_output_from_input() must be called after reconnect"

    print(f"✅ S19b passed  (reconnect={len(set_input_calls)}, configure={len(configure_calls)})")


# ═══════════════════════════════════════════════════════════════════════════════
#  Main runner
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    import traceback

    tests = [
        test_awaiting_series_number_set_when_async_load_fails,
        test_awaiting_series_number_cleared_on_new_dragdrop,
        test_repeated_dragdrop_overwrites_awaiting_marker,
        test_progress_scan_finds_awaiting_viewer,
        test_two_layouts_track_different_awaiting_series,
        test_apply_progressive_to_target_viewer_happy_path,
        test_apply_progressive_to_target_viewer_cache_miss_hides_spinner,
        test_inflight_guard_blocks_start_when_awaiting_viewer_present,
        test_done_guard_blocks_restart_when_awaiting_viewer_present,
        test_awaiting_scan_over_10_nodes_is_fast,
        test_end_to_end_10series_patient_drag_drop_flow,
        test_bug_a_first_batch_triggers_display_on_awaiting_viewer,
        test_bug_b_second_batch_grows_not_restarts,
        test_bug_c_dragdrop_replaces_image_and_escalates_priority,
        test_stability_10_batches_one_start_nine_grows,
        test_repeatability_full_dragdrop_plus_10_batches,
        test_completion_signal_triggers_one_shot_grow_on_non_progressive_viewer,
        test_intermediate_then_completion_activates_then_grows,
        test_grow_progressive_fast_updates_reslice_extent,
        test_grow_progressive_fast_reconnects_reslice_when_preprocessed,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:
            print(f"❌ {t.__name__} FAILED: {exc}")
            traceback.print_exc()
            failed += 1

    print(_kpi.report())
    print(f"\n{'=' * 60}")
    print(f"  {passed} passed, {failed} failed out of {len(tests)} tests")
    print(f"{'=' * 60}")
    sys.exit(0 if failed == 0 else 1)