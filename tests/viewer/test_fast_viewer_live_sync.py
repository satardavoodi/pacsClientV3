"""tests/viewer/test_fast_viewer_live_sync.py
-------------------------------------------
FAST Viewer live download synchronisation tests.

These tests cover the live / progressive behaviour that is *unique* to the
FAST (PyDicom) Viewer path.

Background
----------
Advanced Viewer loads a series only AFTER it is fully downloaded, so there is
no live-sync concern there.  FAST Viewer must stay in lock-step with the
download state: each batch of ~10 new images that arrive from the DM must
immediately become navigable (slider + counter + actual rendered image).

The critical chain per batch:
  DM emits seriesProgressUpdated(sn, downloaded, total)
    → on_series_images_progress (100ms per-series debounce)
      └─ progressive viewer already showing sn?
           ├─ delta ≥ batch_size OR downloaded==total  →  grow timer fires
           │     └─ _flush_progressive_grow → _grow_progressive_fast(sn, pending, viewers)
           └─ delta < batch_size                       →  (skipped — not enough new images)

_grow_progressive_fast per viewer:
  1. loader.grow()               refresh backend, expand VTK memmap, update slice_count
  2. reslice extent update        fix ImageReslice.SetOutputExtent (prevents image stuck)
  3. update_available_slice_count  expose new slices to slider + counter
  4. slider.setMaximum             keep slider maximum in sync
  5. booster.update_paths          update ±20 prefetch window for new files
  6. _refresh_stored_metadata_instances  so re-drop sees full count
  7. exit_progressive_mode (only when new_count ≥ total)

Scenarios
---------
L1   loader.grow() called — NOT backend.refresh_file_list() — to preserve
     old-path snapshot for interleaved DICOM instance-number remap
L2   update_available_slice_count called with correct new_count each batch
L3   slider.setMaximum set to new_count - 1 each batch
L4   booster.update_paths called when booster is active for this series
L5   booster NOT updated when active_series differs (different series booster)
L6   exit_progressive_mode called exactly once when new_count == total
L7   exit_progressive_mode NOT called when new_count < total
L8   Two viewers in 2×2 layout both receive the grow update each batch
L9   Qt-bridge path (BACKEND_PYDICOM_QT): bridge.grow() used instead of
     loader.grow(); update_available_slice_count still called correctly
L10  Fallback: loader has no grow() — backend.refresh_file_list() + slice_count update
L11  Fallback: no loader at all — pending_count used; update_available_slice_count
     still fires
L12  Multi-batch lifecycle: 10 batches × 10 images → available counts are
     monotonically increasing and match expected values at every step
L13  Last batch: new_count == total → exit_progressive_mode fires; _progressive_series
     entry removed; viewer can no longer grow
L14  _refresh_stored_metadata_instances called at every grow (partial and final)
L15  KPI — 10 batch grows across 2 viewers stay under 5ms total wall-clock
L16  Routing: on_series_images_progress with progressive viewer and delta ≥ batch →
     grow timer starts; _start_progressive_display NOT called
L17  Routing: delta < batch_size → timer does NOT start (not enough new images)
L18  Routing: downloaded == total → timer starts even when delta < batch_size
     (completion signal always triggers final grow)
L19  Reslice extent re-applied at EVERY batch grow, not only the first
L20  Available counts emitted are never negative and always monotonically
     non-decreasing across 10 consecutive grows
L21  Stale grow (loader.grow returns fewer files than expected due to OS
     flush delay): _stale_retry_count incremented, pending_downloaded kept,
     timer restarted, exit_progressive_mode NOT called — no permanent stuck
L22  One-shot path stale grow: non-progressive viewer calls
     enter_progressive_mode so _find_progressive_viewers can locate it on the
     retry tick; timer is started; pending_downloaded preserved for retry
L23  _flush_progressive_grow safety-net: after all series are processed, if
     any series still has pending_downloaded > last_grow_count, the single-shot
     timer is restarted — independent protection from the stale-grow guard
L24  Done-guard completion one-shot: when sn is in _progressive_display_done
     and downloaded >= total, a non-progressive viewer stuck at fewer slices
     triggers _grow_progressive_fast (fixes Series 201 "scrolls only 30" bug)
L25  Stale exhaustion (max 5 retries): exit_progressive_mode called, series
     popped from tracking, slider updated to actual count, timer NOT restarted
     (prevents infinite safety-net loop, done-guard recovers on completion)
L26  _refresh_stored_metadata_instances updates series["image_count"] after
     grow so thumbnails show the correct downloaded count, not old server count

Run:
    .venv\\Scripts\\python.exe -m pytest tests/viewer/test_fast_viewer_live_sync.py -v
    .venv\\Scripts\\python.exe tests/viewer/test_fast_viewer_live_sync.py
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

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
    def __init__(self):
        self._records: List[Dict[str, Any]] = []

    def record(self, scenario, metric, value, unit="", passed=None):
        self._records.append(
            {"scenario": scenario, "metric": metric, "value": value,
             "unit": unit, "passed": passed}
        )

    def report(self) -> str:
        lines = ["", "=" * 100, "  FAST VIEWER LIVE SYNC — KPI REPORT", "=" * 100]
        by_scenario: Dict[str, list] = defaultdict(list)
        for r in self._records:
            by_scenario[r["scenario"]].append(r)

        total_pass = total_fail = total_info = 0
        for scenario, records in by_scenario.items():
            lines.append(f"\n  ┌─ {scenario}")
            lines.append(f"  │{'Metric':<45} {'Value':>15} {'Unit':<10} {'Status':>8}")
            lines.append(f"  │{'─' * 82}")
            for r in records:
                if r["passed"] is True:
                    status = "  ✅ PASS"; total_pass += 1
                elif r["passed"] is False:
                    status = "  ❌ FAIL"; total_fail += 1
                else:
                    status = "  ── info"; total_info += 1
                v = r["value"]
                vs = f"{v:>15.3f}" if isinstance(v, float) else f"{str(v):>15}"
                lines.append(f"  │ {r['metric']:<44} {vs} {r['unit']:<10}{status}")
            lines.append(f"  └{'─' * 82}")

        lines += [
            "", "=" * 100,
            f"  TOTALS:  ✅ {total_pass} passed   ❌ {total_fail} failed   "
            f"── {total_info} info",
            "=" * 100, "",
        ]
        return "\n".join(lines)


_kpi = KPICollector()


# ═══════════════════════════════════════════════════════════════════════════════
#  Shared mock factories
# ═══════════════════════════════════════════════════════════════════════════════

def _build_controller() -> controller_mod.ViewerController:
    """Minimal ViewerController — no Qt, no VTK."""
    c = controller_mod.ViewerController.__new__(controller_mod.ViewerController)
    c.logger = SimpleNamespace(
        info=lambda *a, **kw: None,
        debug=lambda *a, **kw: None,
        warning=lambda *a, **kw: None,
        error=lambda *a, **kw: None,
    )
    c.lst_nodes_viewer = []
    c._progressive_series = {}
    c._progressive_display_done = set()
    c._progressive_display_inflight = set()
    c._progressive_grow_batch_size = 10
    c._is_fast_viewer_mode = lambda: True
    c._find_progressive_viewers = lambda sn: []
    c._image_slice_booster = SimpleNamespace(
        active_series=None,
        update_paths=lambda sn, paths: None,
    )
    c._refresh_stored_metadata_instances = lambda sn, count: None
    c._invalidate_series_caches = lambda sn: None
    return c


def _make_mock_loader(
    *,
    initial_count: int = 10,
    grow_to: int = 20,
    vtk_image_data=None,
    file_paths: Optional[List[str]] = None,
):
    """Fake PyDicomLazyVolume with grow() that returns grow_to."""
    if vtk_image_data is None:
        vtk_image_data = object()  # sentinel

    grow_calls: List[int] = []

    loader = SimpleNamespace(
        vtk_image_data=vtk_image_data,
        slice_count=initial_count,
        _grow_calls=grow_calls,
        backend=SimpleNamespace(
            get_file_paths=lambda: (file_paths or [f"file_{i}.dcm" for i in range(grow_to)]),
            refresh_file_list=lambda: grow_to,
        ),
    )

    def _grow():
        grow_calls.append(grow_to)
        loader.slice_count = grow_to
        return grow_to

    loader.grow = _grow
    return loader


def _make_mock_reslice(vtk_image_data=None, same_as_loader=True):
    """Fake ImageReslice.  same_as_loader=True means same vtk_image_data reference."""
    loader_vtk = vtk_image_data or object()
    reslice_vtk = loader_vtk if same_as_loader else object()

    configure_calls: List[int] = []
    modified_calls: List[int] = []
    update_calls: List[int] = []
    set_input_calls: List[Any] = []

    reslice = SimpleNamespace(
        vtk_image_data=reslice_vtk,
        _configure_calls=configure_calls,
        _modified_calls=modified_calls,
        _update_calls=update_calls,
        _set_input_calls=set_input_calls,
        _configure_output_from_input=lambda: configure_calls.append(1),
        Modified=lambda: modified_calls.append(1),
        Update=lambda: update_calls.append(1),
        GetOutputExtent=lambda: [0, 511, 0, 511, 0, initial_ct - 1],
        SetInputData=lambda vd: (set_input_calls.append(vd), setattr(reslice, "vtk_image_data", vd)),
    )

    initial_ct = 10  # bound early for lambda — just for GetOutputExtent info
    return reslice, loader_vtk


def _make_vtk_widget(
    *,
    series_number: str = "5",
    progressive_mode: bool = True,
    initial_slices: int = 10,
    loader=None,
    reslice=None,
    qt_bridge_active: bool = False,
    slider=None,
):
    """Full mock vtk_widget for live-sync tests."""
    exit_pm_calls: List[int] = []
    avail_calls: List[int] = []
    enter_pm_calls: List[Any] = []

    if loader is not None:
        image_viewer = SimpleNamespace(
            metadata={"series": {"series_number": series_number}},
            get_count_of_slices=lambda: loader.slice_count,
            image_reslice=reslice,
        )
    else:
        image_viewer = SimpleNamespace(
            metadata={"series": {"series_number": series_number}},
            get_count_of_slices=lambda: initial_slices,
            image_reslice=reslice,
        )

    vtk_w = SimpleNamespace(
        _progressive_mode=progressive_mode,
        _progressive_series_number=series_number if progressive_mode else None,
        _lazy_loader=loader,
        _qt_bridge_active=qt_bridge_active,
        _active_backend="BACKEND_PYDICOM" if not qt_bridge_active else "BACKEND_PYDICOM_QT",
        image_viewer=image_viewer,
        _exit_pm_calls=exit_pm_calls,
        _avail_calls=avail_calls,
        _enter_pm_calls=enter_pm_calls,
        exit_progressive_mode=lambda: exit_pm_calls.append(1),
        update_available_slice_count=lambda n: avail_calls.append(n),
        enter_progressive_mode=lambda tot, sn: enter_pm_calls.append((tot, sn)),
        get_count_of_slices=lambda: loader.slice_count if loader else initial_slices,
    )

    # Attach slider if provided
    if slider is not None:
        vtk_w._slider = slider

    return vtk_w


def _make_slider():
    """Minimal slider mock tracking setMaximum calls."""
    set_max_calls: List[int] = []
    sl = SimpleNamespace(
        _set_max_calls=set_max_calls,
        blockSignals=lambda flag: None,
        setMaximum=lambda n: set_max_calls.append(n),
        value=lambda: 0,
    )
    return sl


def _make_node(vtk_w, slider=None):
    return SimpleNamespace(vtk_widget=vtk_w, slider=slider)


# ═══════════════════════════════════════════════════════════════════════════════
#  L1: loader.grow() is called — NOT backend.refresh_file_list() directly
# ═══════════════════════════════════════════════════════════════════════════════

def test_grow_refreshes_via_loader_grow_not_backend_directly():
    """
    L1: _grow_progressive_fast must call loader.grow() — which snapshots the
    old file-path order BEFORE refreshing — rather than pre-calling
    backend.refresh_file_list() separately.

    Calling refresh_file_list() before grow() can re-sort _slices by instance
    number, poisoning the old-index → new-index remap used by grow() to
    correctly place decoded pixels when instance numbers are interleaved.

    Asserts:
      - loader.grow() is called at least once
      - backend.refresh_file_list() is NOT called directly by the method
    """
    scenario = "L1: loader.grow() used (not bare refresh_file_list)"

    c = _build_controller()
    c._progressive_series = {"5": {"total": 20, "last_grow_count": 10, "last_signal_ms": 0}}

    loader = _make_mock_loader(initial_count=10, grow_to=20)

    # Track direct calls to backend.refresh_file_list
    refresh_direct_calls: List[int] = []
    _orig_refresh = loader.backend.refresh_file_list
    loader.backend.refresh_file_list = lambda: (refresh_direct_calls.append(1), _orig_refresh())[1]

    reslice, loader_vtk = _make_mock_reslice(vtk_image_data=loader.vtk_image_data)
    vtk_w = _make_vtk_widget(series_number="5", loader=loader, reslice=reslice)
    node = _make_node(vtk_w)

    c._grow_progressive_fast("5", 20, [(vtk_w, node)])

    grow_ok = len(loader._grow_calls) >= 1
    # The only allowed route to refresh_file_list is inside loader.grow() itself;
    # the method must NOT call it on the backend object via the outer try block.
    refresh_direct_ok = len(refresh_direct_calls) == 0

    _kpi.record(scenario, "loader.grow() called", len(loader._grow_calls), passed=grow_ok)
    _kpi.record(scenario, "backend.refresh_file_list() NOT called directly",
                len(refresh_direct_calls), passed=refresh_direct_ok)

    assert grow_ok, "loader.grow() must be called"
    assert refresh_direct_ok, (
        "backend.refresh_file_list() must NOT be called directly from "
        "_grow_progressive_fast — it poisons the old-path snapshot used by grow()"
    )
    print(f"✅ L1 passed  (grow_calls={loader._grow_calls}, direct_refresh={refresh_direct_calls})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L2: update_available_slice_count called with correct new_count each batch
# ═══════════════════════════════════════════════════════════════════════════════

def test_grow_updates_available_slice_count_each_batch():
    """
    L2: After each grow, vtk_w.update_available_slice_count(new_count) must be
    called so the slider and image counter display the correct value.

    Tests two grows: 10→20 (partial) and 20→30 (partial).
    """
    scenario = "L2: update_available_slice_count correct at each batch"

    c = _build_controller()

    loader = _make_mock_loader(initial_count=10, grow_to=20)
    reslice, _ = _make_mock_reslice(vtk_image_data=loader.vtk_image_data)
    vtk_w = _make_vtk_widget(series_number="6", loader=loader, reslice=reslice)
    node = _make_node(vtk_w)

    # Batch 1: 10→20
    c._progressive_series = {"6": {"total": 30, "last_grow_count": 10, "last_signal_ms": 0}}
    c._grow_progressive_fast("6", 20, [(vtk_w, node)])

    assert vtk_w._avail_calls[-1] == 20, (
        f"Batch 1: expected update_available_slice_count(20), got {vtk_w._avail_calls}"
    )

    # Batch 2: 20→30
    loader.slice_count = 20
    loader.grow = lambda: (loader._grow_calls.append(30), setattr(loader, "slice_count", 30), 30)[2]
    c._progressive_series["6"]["last_grow_count"] = 20
    c._grow_progressive_fast("6", 30, [(vtk_w, node)])

    assert vtk_w._avail_calls[-1] == 30, (
        f"Batch 2: expected update_available_slice_count(30), got {vtk_w._avail_calls}"
    )

    _kpi.record(scenario, "batch-1 available count", vtk_w._avail_calls[0],
                passed=(vtk_w._avail_calls[0] == 20))
    _kpi.record(scenario, "batch-2 available count", vtk_w._avail_calls[1] if len(vtk_w._avail_calls) > 1 else -1,
                passed=(len(vtk_w._avail_calls) > 1 and vtk_w._avail_calls[1] == 30))
    print(f"✅ L2 passed  (avail_calls={vtk_w._avail_calls})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L3: slider.setMaximum set to new_count - 1 each batch
# ═══════════════════════════════════════════════════════════════════════════════

def test_grow_updates_slider_max_each_batch():
    """
    L3: The slider maximum must be updated to match the newly available slice
    count after each batch so the user can navigate to the new slices.

    If slider.setMaximum is not updated, the slider clamps at the old limit
    even though the counter says more images are available — inconsistent UX.
    """
    scenario = "L3: slider.setMaximum = new_count - 1 each batch"

    c = _build_controller()
    c._progressive_series = {"7": {"total": 30, "last_grow_count": 10, "last_signal_ms": 0}}

    loader = _make_mock_loader(initial_count=10, grow_to=20)
    reslice, _ = _make_mock_reslice(vtk_image_data=loader.vtk_image_data)
    slider = _make_slider()
    vtk_w = _make_vtk_widget(series_number="7", loader=loader, reslice=reslice)
    node = _make_node(vtk_w, slider=slider)

    c._grow_progressive_fast("7", 20, [(vtk_w, node)])

    assert len(slider._set_max_calls) >= 1, "setMaximum must be called at least once"
    # The max must be new_count - 1 = 19
    assert slider._set_max_calls[-1] == 19, (
        f"Expected setMaximum(19), got {slider._set_max_calls}"
    )

    _kpi.record(scenario, "setMaximum calls", len(slider._set_max_calls),
                passed=(len(slider._set_max_calls) >= 1))
    _kpi.record(scenario, "setMaximum value", slider._set_max_calls[-1] if slider._set_max_calls else -1,
                passed=(bool(slider._set_max_calls) and slider._set_max_calls[-1] == 19))
    print(f"✅ L3 passed  (set_max_calls={slider._set_max_calls})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L4: booster.update_paths called when booster is active for this series
# ═══════════════════════════════════════════════════════════════════════════════

def test_grow_updates_booster_paths_when_active():
    """
    L4: When the ImageSliceBooster is active for the downloading series,
    _grow_progressive_fast must call booster.update_paths(sn, new_paths) so
    the ±20 prefetch window expands to cover newly downloaded slices.

    Without this call the booster would pre-fetch using the old file list,
    returning MISS for any slice index beyond the original batch count.
    """
    scenario = "L4: booster.update_paths called when active series matches"

    c = _build_controller()
    c._progressive_series = {"3": {"total": 20, "last_grow_count": 10, "last_signal_ms": 0}}

    new_paths = [f"dcm_{i:04d}.dcm" for i in range(20)]
    loader = _make_mock_loader(initial_count=10, grow_to=20, file_paths=new_paths)
    reslice, _ = _make_mock_reslice(vtk_image_data=loader.vtk_image_data)
    vtk_w = _make_vtk_widget(series_number="3", loader=loader, reslice=reslice)
    node = _make_node(vtk_w)

    booster_calls: List[Any] = []
    c._image_slice_booster = SimpleNamespace(
        active_series="3",  # active for THIS series
        update_paths=lambda sn, paths: booster_calls.append((sn, paths)),
    )

    c._grow_progressive_fast("3", 20, [(vtk_w, node)])

    booster_ok = (
        len(booster_calls) >= 1
        and booster_calls[0][0] == "3"
        and len(booster_calls[0][1]) == 20
    )

    _kpi.record(scenario, "booster.update_paths calls", len(booster_calls), passed=(len(booster_calls) >= 1))
    _kpi.record(scenario, "booster received correct sn",
                booster_calls[0][0] if booster_calls else "—",
                passed=(bool(booster_calls) and booster_calls[0][0] == "3"))
    _kpi.record(scenario, "booster received 20 paths",
                len(booster_calls[0][1]) if booster_calls else -1,
                passed=(bool(booster_calls) and len(booster_calls[0][1]) == 20))

    assert booster_ok, (
        f"booster.update_paths must be called once with sn='3' and 20 paths, got {booster_calls}"
    )
    print(f"✅ L4 passed  (booster_calls={len(booster_calls)}, paths={len(booster_calls[0][1])})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L5: booster NOT updated when active_series differs
# ═══════════════════════════════════════════════════════════════════════════════

def test_grow_skips_booster_update_when_different_series_active():
    """
    L5: If the booster is currently active for a *different* series (e.g. series 1
    while we are growing series 5), update_paths must NOT be called — otherwise
    the booster's window for series 1 would be overwritten with series 5 paths,
    corrupting the prefetch for the series the user is actually viewing.
    """
    scenario = "L5: booster NOT updated when active_series != downloading series"

    c = _build_controller()
    c._progressive_series = {"5": {"total": 20, "last_grow_count": 10, "last_signal_ms": 0}}

    loader = _make_mock_loader(initial_count=10, grow_to=20)
    reslice, _ = _make_mock_reslice(vtk_image_data=loader.vtk_image_data)
    vtk_w = _make_vtk_widget(series_number="5", loader=loader, reslice=reslice)
    node = _make_node(vtk_w)

    booster_calls: List[Any] = []
    c._image_slice_booster = SimpleNamespace(
        active_series="1",  # different series — must NOT be updated
        update_paths=lambda sn, paths: booster_calls.append((sn, paths)),
    )

    c._grow_progressive_fast("5", 20, [(vtk_w, node)])

    _kpi.record(scenario, "booster.update_paths calls (must be 0)",
                len(booster_calls), passed=(len(booster_calls) == 0))

    assert len(booster_calls) == 0, (
        f"booster.update_paths must NOT be called when active_series='1' "
        f"and growing series='5', got {booster_calls}"
    )
    print(f"✅ L5 passed  (booster_calls={booster_calls})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L6: exit_progressive_mode called exactly once on completion
# ═══════════════════════════════════════════════════════════════════════════════

def test_grow_calls_exit_progressive_mode_on_completion():
    """
    L6: When new_count == total the download is complete.
    vtk_w.exit_progressive_mode() must be called exactly once and the series
    must be removed from _progressive_series.

    The viewer should transition from progressive to normal (non-growing) mode.
    """
    scenario = "L6: exit_progressive_mode called and _progressive_series cleared on close"

    c = _build_controller()
    sn = "8"
    total = 20
    c._progressive_series = {sn: {"total": total, "last_grow_count": 10, "last_signal_ms": 0}}

    loader = _make_mock_loader(initial_count=10, grow_to=total)
    reslice, _ = _make_mock_reslice(vtk_image_data=loader.vtk_image_data)
    vtk_w = _make_vtk_widget(series_number=sn, loader=loader, reslice=reslice)
    node = _make_node(vtk_w)

    c._grow_progressive_fast(sn, total, [(vtk_w, node)])

    exit_ok = len(vtk_w._exit_pm_calls) == 1
    series_cleared = sn not in c._progressive_series

    _kpi.record(scenario, "exit_progressive_mode called once",
                len(vtk_w._exit_pm_calls), passed=exit_ok)
    _kpi.record(scenario, "_progressive_series cleared",
                str(series_cleared), passed=series_cleared)

    assert exit_ok, (
        f"exit_progressive_mode must be called exactly once on completion, "
        f"got {len(vtk_w._exit_pm_calls)} calls"
    )
    assert series_cleared, (
        f"_progressive_series must not contain '{sn}' after completion, "
        f"keys={list(c._progressive_series.keys())}"
    )
    print(f"✅ L6 passed  (exit={vtk_w._exit_pm_calls}, series_cleared={series_cleared})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L7: exit_progressive_mode NOT called on a partial grow
# ═══════════════════════════════════════════════════════════════════════════════

def test_grow_keeps_progressive_mode_when_incomplete():
    """
    L7: When new_count < total (still downloading), exit_progressive_mode must
    NOT be called — the viewer must stay in progressive (growing) mode.

    Premature exit would make subsequent batch grows invisible to the user
    because the viewer would have lost its progressive-mode flag.
    """
    scenario = "L7: exit_progressive_mode NOT called while still downloading"

    c = _build_controller()
    sn = "9"
    c._progressive_series = {sn: {"total": 50, "last_grow_count": 10, "last_signal_ms": 0}}

    loader = _make_mock_loader(initial_count=10, grow_to=20)  # 20 of 50
    reslice, _ = _make_mock_reslice(vtk_image_data=loader.vtk_image_data)
    vtk_w = _make_vtk_widget(series_number=sn, loader=loader, reslice=reslice)
    node = _make_node(vtk_w)

    c._grow_progressive_fast(sn, 20, [(vtk_w, node)])

    exit_ok = len(vtk_w._exit_pm_calls) == 0
    series_kept = sn in c._progressive_series

    _kpi.record(scenario, "exit_progressive_mode NOT called (partial)",
                len(vtk_w._exit_pm_calls), passed=exit_ok)
    _kpi.record(scenario, "_progressive_series still present",
                str(series_kept), passed=series_kept)

    assert exit_ok, (
        f"exit_progressive_mode must NOT be called at 20/50 downloaded, "
        f"got {len(vtk_w._exit_pm_calls)} calls"
    )
    assert series_kept, f"_progressive_series must still have '{sn}' at 20/50"
    print(f"✅ L7 passed  (exit={vtk_w._exit_pm_calls}, series_kept={series_kept})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L8: Two viewers in a 2×2 layout both receive every grow update
# ═══════════════════════════════════════════════════════════════════════════════

def test_grow_updates_both_viewers_in_2x2_layout():
    """
    L8: When two viewers are both showing the same series in progressive mode
    (2×2 layout, series duplicated in two panels), _grow_progressive_fast must
    update BOTH viewers — not just the first one.

    Asserts:
      - update_available_slice_count called once per viewer (2 total)
      - exit_progressive_mode NOT called (20/50 downloaded)
    """
    scenario = "L8: both viewers in 2×2 layout receive grow update"

    c = _build_controller()
    sn = "4"
    c._progressive_series = {sn: {"total": 50, "last_grow_count": 10, "last_signal_ms": 0}}

    loader1 = _make_mock_loader(initial_count=10, grow_to=20)
    loader2 = _make_mock_loader(initial_count=10, grow_to=20)
    reslice1, _ = _make_mock_reslice(vtk_image_data=loader1.vtk_image_data)
    reslice2, _ = _make_mock_reslice(vtk_image_data=loader2.vtk_image_data)

    vtk_w1 = _make_vtk_widget(series_number=sn, loader=loader1, reslice=reslice1)
    vtk_w2 = _make_vtk_widget(series_number=sn, loader=loader2, reslice=reslice2)
    node1 = _make_node(vtk_w1)
    node2 = _make_node(vtk_w2)

    c._grow_progressive_fast(sn, 20, [(vtk_w1, node1), (vtk_w2, node2)])

    avail1_ok = len(vtk_w1._avail_calls) >= 1 and vtk_w1._avail_calls[-1] == 20
    avail2_ok = len(vtk_w2._avail_calls) >= 1 and vtk_w2._avail_calls[-1] == 20
    exit1_ok = len(vtk_w1._exit_pm_calls) == 0
    exit2_ok = len(vtk_w2._exit_pm_calls) == 0

    _kpi.record(scenario, "viewer-1 avail updated to 20",
                vtk_w1._avail_calls[-1] if vtk_w1._avail_calls else -1, passed=avail1_ok)
    _kpi.record(scenario, "viewer-2 avail updated to 20",
                vtk_w2._avail_calls[-1] if vtk_w2._avail_calls else -1, passed=avail2_ok)
    _kpi.record(scenario, "viewer-1 NOT exited (20/50)", len(vtk_w1._exit_pm_calls), passed=exit1_ok)
    _kpi.record(scenario, "viewer-2 NOT exited (20/50)", len(vtk_w2._exit_pm_calls), passed=exit2_ok)

    assert avail1_ok, f"Viewer 1: expected available=20, got {vtk_w1._avail_calls}"
    assert avail2_ok, f"Viewer 2: expected available=20, got {vtk_w2._avail_calls}"
    assert exit1_ok, "Viewer 1 must not exit progressive mode at 20/50"
    assert exit2_ok, "Viewer 2 must not exit progressive mode at 20/50"
    print(f"✅ L8 passed  (avail1={vtk_w1._avail_calls}, avail2={vtk_w2._avail_calls})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L9: Qt-bridge path (BACKEND_PYDICOM_QT) uses bridge.grow()
# ═══════════════════════════════════════════════════════════════════════════════

def test_grow_uses_qt_bridge_when_qt_bridge_active():
    """
    L9: When _qt_bridge_active=True the viewer uses a Lightweight2DPipeline
    via QtViewerBridge.  _grow_progressive_fast must call bridge.grow() (which
    calls pipeline.refresh_file_list and updates _slice_count) instead of
    loader.grow().

    Without this the bridge's internal _slice_count would stay at the original
    batch count, causing set_slice(n) to clamp at the old limit.
    """
    scenario = "L9: Qt-bridge path calls bridge.grow() not loader.grow()"

    c = _build_controller()
    c._progressive_series = {"2": {"total": 30, "last_grow_count": 10, "last_signal_ms": 0}}

    bridge_grow_calls: List[int] = []

    mock_bridge = SimpleNamespace(
        grow=lambda: (bridge_grow_calls.append(20), 20)[1],
        metadata={"series": {"series_number": "2"}},
        get_count_of_slices=lambda: 20,
        image_reslice=None,
    )

    vtk_w = SimpleNamespace(
        _progressive_mode=True,
        _progressive_series_number="2",
        _lazy_loader=None,          # no lazy loader — Qt bridge path
        _qt_bridge_active=True,
        _active_backend="BACKEND_PYDICOM_QT",
        image_viewer=mock_bridge,
        _avail_calls=[],
        _exit_pm_calls=[],
        exit_progressive_mode=lambda: None,
        update_available_slice_count=lambda n: vtk_w._avail_calls.append(n),
        get_count_of_slices=lambda: 20,
    )
    node = _make_node(vtk_w)

    c._grow_progressive_fast("2", 20, [(vtk_w, node)])

    bridge_ok = len(bridge_grow_calls) >= 1
    avail_ok = len(vtk_w._avail_calls) >= 1

    _kpi.record(scenario, "bridge.grow() called", len(bridge_grow_calls), passed=bridge_ok)
    _kpi.record(scenario, "update_available_slice_count called",
                len(vtk_w._avail_calls), passed=avail_ok)

    assert bridge_ok, (
        f"bridge.grow() must be called on the Qt-bridge path, got {bridge_grow_calls}"
    )
    assert avail_ok, (
        f"update_available_slice_count must be called even on Qt-bridge path, "
        f"got {vtk_w._avail_calls}"
    )
    print(f"✅ L9 passed  (bridge_grow={bridge_grow_calls}, avail={vtk_w._avail_calls})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L10: Fallback: loader with no grow() → backend.refresh_file_list()
# ═══════════════════════════════════════════════════════════════════════════════

def test_grow_fallback_to_backend_refresh_when_loader_has_no_grow():
    """
    L10: If the loader exists but has no grow() method (e.g. a legacy or
    reduced backend variant), _grow_progressive_fast falls back to calling
    backend.refresh_file_list() and updating loader.slice_count manually.

    Asserts:
      - backend.refresh_file_list() is called
      - loader.slice_count is updated to the returned value
      - update_available_slice_count is called with the new count
    """
    scenario = "L10: fallback to backend.refresh_file_list when loader has no grow()"

    c = _build_controller()
    c._progressive_series = {"10": {"total": 30, "last_grow_count": 10, "last_signal_ms": 0}}

    refresh_calls: List[int] = []

    mock_loader = SimpleNamespace(
        slice_count=10,
        vtk_image_data=object(),
        backend=SimpleNamespace(
            refresh_file_list=lambda: (refresh_calls.append(20), 20)[1],
            get_file_paths=lambda: [],
        ),
        # NO grow attribute
    )

    reslice = SimpleNamespace(
        vtk_image_data=mock_loader.vtk_image_data,
        image_reslice=None,
    )

    vtk_w = SimpleNamespace(
        _progressive_mode=True,
        _progressive_series_number="10",
        _lazy_loader=mock_loader,
        _qt_bridge_active=False,
        _active_backend="BACKEND_PYDICOM",
        image_viewer=SimpleNamespace(
            metadata={"series": {"series_number": "10"}},
            get_count_of_slices=lambda: 20,
            image_reslice=None,
        ),
        _avail_calls=[],
        _exit_pm_calls=[],
        exit_progressive_mode=lambda: None,
        update_available_slice_count=lambda n: vtk_w._avail_calls.append(n),
        get_count_of_slices=lambda: mock_loader.slice_count,
    )
    node = _make_node(vtk_w)

    c._grow_progressive_fast("10", 20, [(vtk_w, node)])

    refresh_ok = len(refresh_calls) >= 1
    slice_count_ok = mock_loader.slice_count == 20
    avail_ok = len(vtk_w._avail_calls) >= 1

    _kpi.record(scenario, "backend.refresh_file_list() called",
                len(refresh_calls), passed=refresh_ok)
    _kpi.record(scenario, "loader.slice_count updated to 20",
                mock_loader.slice_count, passed=slice_count_ok)
    _kpi.record(scenario, "update_available_slice_count called",
                len(vtk_w._avail_calls), passed=avail_ok)

    assert refresh_ok, "backend.refresh_file_list() must be called as fallback"
    assert slice_count_ok, f"loader.slice_count must be 20, got {mock_loader.slice_count}"
    assert avail_ok, "update_available_slice_count must be called"
    print(f"✅ L10 passed  (refresh={refresh_calls}, slice_count={mock_loader.slice_count})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L11: No loader at all — pending_count used as fallback
# ═══════════════════════════════════════════════════════════════════════════════

def test_grow_uses_pending_count_when_no_loader():
    """
    L11: When _lazy_loader is None and _qt_bridge_active is False,
    _grow_progressive_fast falls through all branch conditions.  It must
    still call update_available_slice_count with the pending_count argument
    (the fallback initialised at the top of the per-viewer loop) so the viewer
    counter stays in sync even without a proper backend.
    """
    scenario = "L11: pending_count used when no loader exists"

    c = _build_controller()
    c._progressive_series = {"11": {"total": 20, "last_grow_count": 10, "last_signal_ms": 0}}

    vtk_w = SimpleNamespace(
        _progressive_mode=True,
        _progressive_series_number="11",
        _lazy_loader=None,
        _qt_bridge_active=False,
        _active_backend="BACKEND_PYDICOM",
        image_viewer=SimpleNamespace(
            metadata={"series": {"series_number": "11"}},
            get_count_of_slices=lambda: 20,
            image_reslice=None,
        ),
        _avail_calls=[],
        _exit_pm_calls=[],
        exit_progressive_mode=lambda: None,
        update_available_slice_count=lambda n: vtk_w._avail_calls.append(n),
        get_count_of_slices=lambda: 20,
    )
    node = _make_node(vtk_w)

    c._grow_progressive_fast("11", 20, [(vtk_w, node)])

    avail_ok = len(vtk_w._avail_calls) >= 1

    _kpi.record(scenario, "update_available_slice_count called",
                len(vtk_w._avail_calls), passed=avail_ok)

    assert avail_ok, (
        "update_available_slice_count must be called even with no loader, "
        f"got {vtk_w._avail_calls}"
    )
    print(f"✅ L11 passed  (avail_calls={vtk_w._avail_calls})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L12: Multi-batch lifecycle — 10 × 10 image batches
# ═══════════════════════════════════════════════════════════════════════════════

def test_multi_batch_lifecycle_10_batches():
    """
    L12: Simulate the full 10-batch lifecycle for a 100-image series.

    For each batch (10, 20, … 90 downloaded; total=100):
      - loader.grow() is called and returns the new slice count
      - update_available_slice_count receives the new count
      - exit_progressive_mode is NOT called (not complete)

    Final batch (100 downloaded, total=100):
      - exit_progressive_mode IS called exactly once
      - _progressive_series entry removed

    Asserts correctness of every intermediate and the final state.
    """
    scenario = "L12: 10-batch multi-batch lifecycle"

    BATCH = 10
    TOTAL = 100
    c = _build_controller()
    sn = "12"
    c._progressive_series = {sn: {"total": TOTAL, "last_grow_count": 0, "last_signal_ms": 0}}

    current_count = [0]  # mutable closure
    exit_pm_calls: List[int] = []
    avail_calls: List[int] = []

    def _fake_grow():
        current_count[0] += BATCH
        return current_count[0]

    loader = SimpleNamespace(
        slice_count=0,
        vtk_image_data=object(),
        grow=_fake_grow,
        backend=SimpleNamespace(
            get_file_paths=lambda: [f"f{i}.dcm" for i in range(current_count[0])],
        ),
    )

    reslice_vtkdata = loader.vtk_image_data
    reslice = SimpleNamespace(
        vtk_image_data=reslice_vtkdata,
        _configure_output_from_input=lambda: None,
        Modified=lambda: None,
        Update=lambda: None,
        GetOutputExtent=lambda: [0, 511, 0, 511, 0, 0],
        SetInputData=lambda vd: None,
    )

    vtk_w = SimpleNamespace(
        _progressive_mode=True,
        _progressive_series_number=sn,
        _lazy_loader=loader,
        _qt_bridge_active=False,
        _active_backend="BACKEND_PYDICOM",
        image_viewer=SimpleNamespace(
            metadata={"series": {"series_number": sn}},
            get_count_of_slices=lambda: current_count[0],
            image_reslice=reslice,
        ),
        _avail_calls=avail_calls,
        _exit_pm_calls=exit_pm_calls,
        exit_progressive_mode=lambda: exit_pm_calls.append(1),
        update_available_slice_count=lambda n: avail_calls.append(n),
        get_count_of_slices=lambda: current_count[0],
    )
    node = _make_node(vtk_w)

    # Simulate 9 partial batches
    for batch_n in range(1, 10):
        downloaded = batch_n * BATCH
        c._grow_progressive_fast(sn, downloaded, [(vtk_w, node)])
        c._progressive_series[sn]["last_grow_count"] = current_count[0]

        # Must NOT exit yet
        assert len(exit_pm_calls) == 0, (
            f"Batch {batch_n}: exit_progressive_mode must not fire until complete, "
            f"got {len(exit_pm_calls)} calls"
        )
        # Available count must match
        assert avail_calls[-1] == batch_n * BATCH, (
            f"Batch {batch_n}: expected avail={batch_n * BATCH}, got {avail_calls[-1]}"
        )

    # Final batch
    c._grow_progressive_fast(sn, TOTAL, [(vtk_w, node)])

    exit_ok = len(exit_pm_calls) == 1
    series_cleared = sn not in c._progressive_series
    avail_counts_ok = avail_calls == list(range(BATCH, TOTAL + 1, BATCH))

    _kpi.record(scenario, "avail counts match expected sequence",
                str(avail_counts_ok), passed=avail_counts_ok)
    _kpi.record(scenario, "exit_progressive_mode once at completion",
                len(exit_pm_calls), passed=exit_ok)
    _kpi.record(scenario, "_progressive_series cleared at completion",
                str(series_cleared), passed=series_cleared)

    assert avail_counts_ok, (
        f"Expected available counts = {list(range(BATCH, TOTAL + 1, BATCH))}, "
        f"got {avail_calls}"
    )
    assert exit_ok, f"exit_progressive_mode must fire exactly once, got {len(exit_pm_calls)}"
    assert series_cleared, f"_progressive_series must not have '{sn}' after completion"
    print(
        f"✅ L12 passed  (10 batches, avail={avail_calls}, "
        f"exit_pm={exit_pm_calls}, series_cleared={series_cleared})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  L13: Last batch — exit_progressive_mode fires; _progressive_series cleaned
# ═══════════════════════════════════════════════════════════════════════════════

def test_last_batch_clears_progressive_series():
    """
    L13: After the final batch, the series MUST be removed from
    _progressive_series so that stale state from a completed download cannot
    interfere with a future drag-drop of the same series.
    """
    scenario = "L13: _progressive_series cleared when final batch completes"

    c = _build_controller()
    sn = "13"
    total = 25
    c._progressive_series = {sn: {"total": total, "last_grow_count": 20, "last_signal_ms": 0}}

    loader = _make_mock_loader(initial_count=20, grow_to=25)
    reslice, _ = _make_mock_reslice(vtk_image_data=loader.vtk_image_data)
    vtk_w = _make_vtk_widget(series_number=sn, loader=loader, reslice=reslice)
    node = _make_node(vtk_w)

    # Ensure series is present before the final grow
    assert sn in c._progressive_series

    c._grow_progressive_fast(sn, total, [(vtk_w, node)])

    series_cleared = sn not in c._progressive_series
    exit_ok = len(vtk_w._exit_pm_calls) == 1

    _kpi.record(scenario, "_progressive_series cleared", str(series_cleared), passed=series_cleared)
    _kpi.record(scenario, "exit_progressive_mode called once", len(vtk_w._exit_pm_calls), passed=exit_ok)

    assert series_cleared, (
        f"_progressive_series must not contain '{sn}' after final batch; "
        f"keys={list(c._progressive_series.keys())}"
    )
    assert exit_ok, (
        f"exit_progressive_mode must be called exactly once, got {len(vtk_w._exit_pm_calls)}"
    )
    print(f"✅ L13 passed  (series_cleared={series_cleared}, exit_calls={vtk_w._exit_pm_calls})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L14: _refresh_stored_metadata_instances called at every grow (partial & final)
# ═══════════════════════════════════════════════════════════════════════════════

def test_refresh_stored_metadata_called_each_grow():
    """
    L14: _refresh_stored_metadata_instances must be called after every grow —
    partial and final — so that re-dropping the series into another viewer
    always reflects the actual downloaded file count rather than the stale
    pre-download metadata.

    Without this, a user who drag-drops Series 5 to a second viewer while 60/100
    images are downloaded would see only the first-display count (e.g. 10) even
    though 60 images are actually available.
    """
    scenario = "L14: _refresh_stored_metadata_instances called at partial and final grow"

    c = _build_controller()
    sn = "14"
    c._progressive_series = {sn: {"total": 30, "last_grow_count": 10, "last_signal_ms": 0}}

    refresh_calls: List[Any] = []
    c._refresh_stored_metadata_instances = lambda s, count: refresh_calls.append((s, count))

    loader = _make_mock_loader(initial_count=10, grow_to=20)
    reslice, _ = _make_mock_reslice(vtk_image_data=loader.vtk_image_data)
    vtk_w = _make_vtk_widget(series_number=sn, loader=loader, reslice=reslice)
    node = _make_node(vtk_w)

    # Partial grow (20/30)
    c._grow_progressive_fast(sn, 20, [(vtk_w, node)])
    partial_refresh_ok = len(refresh_calls) >= 1 and refresh_calls[0] == (sn, 20)

    # Final grow (30/30) — re-init loader grow to return 30
    c._progressive_series[sn]["last_grow_count"] = 20
    loader.grow = lambda: (loader._grow_calls.append(30), setattr(loader, "slice_count", 30), 30)[2]
    c._grow_progressive_fast(sn, 30, [(vtk_w, node)])
    final_refresh_ok = any(call == (sn, 30) for call in refresh_calls)

    _kpi.record(scenario, "refresh after partial grow (20)",
                str(partial_refresh_ok), passed=partial_refresh_ok)
    _kpi.record(scenario, "refresh after final grow (30)",
                str(final_refresh_ok), passed=final_refresh_ok)

    assert partial_refresh_ok, (
        f"_refresh_stored_metadata_instances must be called at partial grow, "
        f"got {refresh_calls}"
    )
    assert final_refresh_ok, (
        f"_refresh_stored_metadata_instances must be called at final grow, "
        f"got {refresh_calls}"
    )
    print(f"✅ L14 passed  (refresh_calls={refresh_calls})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L15: KPI — 10 batch grows across 2 viewers stay under 5ms total
# ═══════════════════════════════════════════════════════════════════════════════

def test_grow_dispatch_kpi_10_batches_fast():
    """
    L15: _grow_progressive_fast must be fast enough to run in the Qt event loop
    without causing visible stutter.

    Benchmark: 10 grows × 2 viewers must complete in < 5ms total wall-clock.

    The real pipeline timer fires every 150ms; individual grow calls should
    take < 0.5ms each to leave ample headroom for the rest of the event loop.
    """
    scenario = "L15: grow dispatch KPI — 10 batches × 2 viewers < 5ms"
    TARGET_TOTAL_MS = 5.0

    c = _build_controller()
    sn = "15"
    c._progressive_series = {sn: {"total": 100, "last_grow_count": 0, "last_signal_ms": 0}}

    current_count = [0]

    def _fast_grow():
        current_count[0] += 10
        return current_count[0]

    loader1 = SimpleNamespace(
        slice_count=0, vtk_image_data=object(), grow=_fast_grow,
        backend=SimpleNamespace(get_file_paths=lambda: []),
    )
    loader2 = SimpleNamespace(
        slice_count=0, vtk_image_data=object(), grow=_fast_grow,
        backend=SimpleNamespace(get_file_paths=lambda: []),
    )

    def _noop_reslice():
        return SimpleNamespace(
            vtk_image_data=loader1.vtk_image_data,
            _configure_output_from_input=lambda: None,
            Modified=lambda: None,
            Update=lambda: None,
            GetOutputExtent=lambda: [0, 0, 0, 0, 0, 0],
            SetInputData=lambda v: None,
        )

    def _make_fast_vtk_w(loader, reslice_vtkdata):
        return SimpleNamespace(
            _progressive_mode=True,
            _progressive_series_number=sn,
            _lazy_loader=loader,
            _qt_bridge_active=False,
            _active_backend="BACKEND_PYDICOM",
            image_viewer=SimpleNamespace(
                metadata={"series": {"series_number": sn}},
                get_count_of_slices=lambda: current_count[0],
                image_reslice=SimpleNamespace(
                    vtk_image_data=reslice_vtkdata,
                    _configure_output_from_input=lambda: None,
                    Modified=lambda: None,
                    Update=lambda: None,
                    GetOutputExtent=lambda: [0, 0, 0, 0, 0, 0],
                    SetInputData=lambda v: None,
                ),
            ),
            exit_progressive_mode=lambda: None,
            update_available_slice_count=lambda n: None,
            get_count_of_slices=lambda: current_count[0],
        )

    vtk_w1 = _make_fast_vtk_w(loader1, loader1.vtk_image_data)
    vtk_w2 = _make_fast_vtk_w(loader2, loader2.vtk_image_data)
    node1 = SimpleNamespace(slider=None)
    node2 = SimpleNamespace(slider=None)

    t0 = time.perf_counter()
    for batch_n in range(1, 11):
        downloaded = batch_n * 10
        c._grow_progressive_fast(sn, downloaded, [(vtk_w1, node1), (vtk_w2, node2)])
        if sn in c._progressive_series:
            c._progressive_series[sn]["last_grow_count"] = current_count[0]
    total_ms = (time.perf_counter() - t0) * 1000

    per_batch_ms = total_ms / 10

    _kpi.record(scenario, "total time (10 batches × 2 viewers)", total_ms, "ms",
                passed=(total_ms < TARGET_TOTAL_MS))
    _kpi.record(scenario, "per-batch avg time", per_batch_ms, "ms",
                passed=(per_batch_ms < TARGET_TOTAL_MS / 10))

    assert total_ms < TARGET_TOTAL_MS, (
        f"10 grows × 2 viewers took {total_ms:.2f}ms — must be < {TARGET_TOTAL_MS}ms"
    )
    print(
        f"✅ L15 passed  (total={total_ms:.3f}ms, per_batch={per_batch_ms:.3f}ms)"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  L16: Routing — progressive viewer present + delta ≥ batch → grow timer starts
# ═══════════════════════════════════════════════════════════════════════════════

def test_routing_progressive_viewer_found_starts_grow_timer():
    """
    L16: on_series_images_progress routing: when a viewer is already in
    progressive mode and downloaded - last_grow_count >= batch_size, the grow
    timer must be started and _start_progressive_display must NOT be called.
    """
    scenario = "L16: routing — progressive viewer + delta ≥ batch → timer starts"

    c = _build_controller()
    sn = "16"
    c._progressive_series = {sn: {"total": 100, "last_grow_count": 10, "last_signal_ms": 0}}

    timer_starts: List[int] = []
    mock_timer = SimpleNamespace(
        start=lambda: timer_starts.append(1),
        isActive=lambda: False,
    )
    c._progressive_grow_timer = mock_timer

    start_calls: List[Any] = []
    c._start_progressive_display = lambda *a, **kw: start_calls.append(a)

    node, vtk_w = SimpleNamespace(vtk_widget=None, slider=None), SimpleNamespace(
        _progressive_mode=True,
        _progressive_series_number=sn,
    )
    node.vtk_widget = vtk_w

    c._find_progressive_viewers = lambda s: [(vtk_w, node)] if s == sn else []
    c.lst_nodes_viewer = [node]

    # downloaded=20 → delta=10 ≥ batch_size=10 → should start timer
    c.on_series_images_progress(sn, 20, 100)

    timer_ok = len(timer_starts) >= 1
    no_start = len(start_calls) == 0

    _kpi.record(scenario, "grow timer started", len(timer_starts), passed=timer_ok)
    _kpi.record(scenario, "_start_progressive_display NOT called",
                len(start_calls), passed=no_start)

    assert timer_ok, (
        f"Grow timer must start when delta≥batch_size, got {timer_starts}"
    )
    assert no_start, (
        f"_start_progressive_display must NOT be called when viewer is in progressive mode, "
        f"got {len(start_calls)} calls"
    )
    print(f"✅ L16 passed  (timer_starts={timer_starts}, start_calls={start_calls})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L17: Routing — delta < batch_size → timer does NOT start
# ═══════════════════════════════════════════════════════════════════════════════

def test_routing_below_batch_delta_no_grow():
    """
    L17: When delta = downloaded - last_grow_count < batch_size AND
    downloaded < total, the grow timer must NOT start — there are not yet
    enough new images to justify a grow cycle.

    This prevents unnecessary refreshes when the DM emits progress at sub-batch
    granularity (e.g. file-by-file on very fast connections).
    """
    scenario = "L17: routing — delta < batch_size → timer skipped"

    c = _build_controller()
    sn = "17"
    c._progressive_series = {sn: {"total": 100, "last_grow_count": 10, "last_signal_ms": 0}}

    timer_starts: List[int] = []
    mock_timer = SimpleNamespace(
        start=lambda: timer_starts.append(1),
        isActive=lambda: False,
    )
    c._progressive_grow_timer = mock_timer

    vtk_w = SimpleNamespace(_progressive_mode=True, _progressive_series_number=sn)
    node = SimpleNamespace(vtk_widget=vtk_w, slider=None)
    c._find_progressive_viewers = lambda s: [(vtk_w, node)] if s == sn else []
    c.lst_nodes_viewer = [node]

    # downloaded=15 → delta=5 < batch_size=10 → should NOT start timer
    c.on_series_images_progress(sn, 15, 100)

    timer_ok = len(timer_starts) == 0

    _kpi.record(scenario, "grow timer NOT started (delta=5 < batch=10)",
                len(timer_starts), passed=timer_ok)

    assert timer_ok, (
        f"Grow timer must NOT start when delta(5) < batch_size(10), "
        f"got timer_starts={timer_starts}"
    )
    print(f"✅ L17 passed  (timer_starts={timer_starts})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L18: Routing — completion signal always triggers grow regardless of delta
# ═══════════════════════════════════════════════════════════════════════════════

def test_routing_completion_signal_always_triggers_grow():
    """
    L18: When downloaded == total (completion), the grow timer must ALWAYS start,
    even if delta < batch_size.

    Scenario: last_grow_count=90, downloaded=95=total (final 5 images arrived).
    delta=5 < batch_size=10 but downloaded==total → timer MUST start.

    Without this, the last sub-batch would never become visible to the user.
    """
    scenario = "L18: routing — completion signal (downloaded==total) always grows"

    c = _build_controller()
    sn = "18"
    c._progressive_series = {sn: {"total": 95, "last_grow_count": 90, "last_signal_ms": 0}}

    timer_starts: List[int] = []
    mock_timer = SimpleNamespace(
        start=lambda: timer_starts.append(1),
        isActive=lambda: False,
    )
    c._progressive_grow_timer = mock_timer

    vtk_w = SimpleNamespace(_progressive_mode=True, _progressive_series_number=sn)
    node = SimpleNamespace(vtk_widget=vtk_w, slider=None)
    c._find_progressive_viewers = lambda s: [(vtk_w, node)] if s == sn else []
    c.lst_nodes_viewer = [node]

    # delta=5 < batch_size=10 BUT downloaded==total → must still start
    c.on_series_images_progress(sn, 95, 95)

    timer_ok = len(timer_starts) >= 1

    _kpi.record(scenario, "grow timer started even with delta(5) < batch(10) on completion",
                len(timer_starts), passed=timer_ok)

    assert timer_ok, (
        "Completion signal (downloaded==total) must trigger grow timer even when "
        f"delta < batch_size, got timer_starts={timer_starts}"
    )
    print(f"✅ L18 passed  (timer_starts={timer_starts})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L19: Reslice extent re-applied at EVERY batch grow, not only the first
# ═══════════════════════════════════════════════════════════════════════════════

def test_reslice_extent_updated_every_batch():
    """
    L19: The ImageReslice output extent fix must fire on EVERY batch grow,
    not just the first one.

    Scenario: 3 consecutive grows (10→20, 20→30, 30→40).
    _configure_output_from_input(), Modified(), Update() must each be called
    exactly once per grow (3× total).

    If the reslice update is accidentally gated on "first grow only", the viewer
    would become stuck again at the boundary of the second grow batch.
    """
    scenario = "L19: reslice extent updated at every batch (not only first)"

    c = _build_controller()
    sn = "19"
    c._progressive_series = {sn: {"total": 40, "last_grow_count": 10, "last_signal_ms": 0}}

    current_count = [10]
    configure_calls: List[int] = []
    modified_calls: List[int] = []
    update_calls: List[int] = []

    def _make_grow():
        current_count[0] += 10
        return current_count[0]

    raw_vtkdata = object()

    loader = SimpleNamespace(
        slice_count=10,
        vtk_image_data=raw_vtkdata,
        grow=_make_grow,
        backend=SimpleNamespace(get_file_paths=lambda: []),
    )

    reslice = SimpleNamespace(
        vtk_image_data=raw_vtkdata,  # same object → no reconnect
        _configure_output_from_input=lambda: configure_calls.append(1),
        Modified=lambda: modified_calls.append(1),
        Update=lambda: update_calls.append(1),
        GetOutputExtent=lambda: [0, 511, 0, 511, 0, current_count[0] - 1],
        SetInputData=lambda v: None,
    )

    vtk_w = SimpleNamespace(
        _progressive_mode=True,
        _progressive_series_number=sn,
        _lazy_loader=loader,
        _qt_bridge_active=False,
        _active_backend="BACKEND_PYDICOM",
        image_viewer=SimpleNamespace(
            metadata={"series": {"series_number": sn}},
            get_count_of_slices=lambda: current_count[0],
            image_reslice=reslice,
        ),
        exit_progressive_mode=lambda: None,
        update_available_slice_count=lambda n: None,
        get_count_of_slices=lambda: current_count[0],
    )
    node = _make_node(vtk_w)

    # Three consecutive batch grows
    for batch in range(1, 4):
        downloaded = (batch + 1) * 10  # 20, 30, 40
        c._grow_progressive_fast(sn, downloaded, [(vtk_w, node)])
        if sn in c._progressive_series:
            c._progressive_series[sn]["last_grow_count"] = current_count[0]

    configure_ok = len(configure_calls) == 3
    modified_ok = len(modified_calls) == 3
    update_ok = len(update_calls) == 3

    _kpi.record(scenario, "_configure_output_from_input calls (must be 3)",
                len(configure_calls), passed=configure_ok)
    _kpi.record(scenario, "reslice.Modified() calls (must be 3)",
                len(modified_calls), passed=modified_ok)
    _kpi.record(scenario, "reslice.Update() calls (must be 3)",
                len(update_calls), passed=update_ok)

    assert configure_ok, (
        f"_configure_output_from_input must be called 3× (once per batch), "
        f"got {len(configure_calls)}"
    )
    assert modified_ok, f"Modified() must be called 3×, got {len(modified_calls)}"
    assert update_ok, f"Update() must be called 3×, got {len(update_calls)}"
    print(
        f"✅ L19 passed  (configure={len(configure_calls)}, modified={len(modified_calls)}, "
        f"update={len(update_calls)})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  L20: Available counts are monotonically non-decreasing across 10 grows
# ═══════════════════════════════════════════════════════════════════════════════

def test_available_counts_monotonically_non_decreasing():
    """
    L20: The sequence of available slice counts emitted by
    update_available_slice_count must be strictly non-decreasing across 10
    consecutive batch grows.

    A decreasing count would cause the slider to shrink backwards — the user
    would lose access to images they could already navigate to.

    Also verifies:
      - All emitted counts are ≥ 0
      - The final emitted count equals the series total (100)
    """
    scenario = "L20: available counts monotonically non-decreasing, final == total"

    c = _build_controller()
    sn = "20"
    total = 100
    c._progressive_series = {sn: {"total": total, "last_grow_count": 0, "last_signal_ms": 0}}

    current_count = [0]
    avail_calls: List[int] = []

    def _batch_grow():
        current_count[0] += 10
        return current_count[0]

    raw_vtkdata = object()

    loader = SimpleNamespace(
        slice_count=0,
        vtk_image_data=raw_vtkdata,
        grow=_batch_grow,
        backend=SimpleNamespace(get_file_paths=lambda: []),
    )

    reslice = SimpleNamespace(
        vtk_image_data=raw_vtkdata,
        _configure_output_from_input=lambda: None,
        Modified=lambda: None,
        Update=lambda: None,
        GetOutputExtent=lambda: [0, 0, 0, 0, 0, 0],
        SetInputData=lambda v: None,
    )

    vtk_w = SimpleNamespace(
        _progressive_mode=True,
        _progressive_series_number=sn,
        _lazy_loader=loader,
        _qt_bridge_active=False,
        _active_backend="BACKEND_PYDICOM",
        image_viewer=SimpleNamespace(
            metadata={"series": {"series_number": sn}},
            get_count_of_slices=lambda: current_count[0],
            image_reslice=reslice,
        ),
        exit_progressive_mode=lambda: None,
        update_available_slice_count=lambda n: avail_calls.append(n),
        get_count_of_slices=lambda: current_count[0],
    )
    node = _make_node(vtk_w)

    for batch_n in range(1, 11):
        downloaded = batch_n * 10
        c._grow_progressive_fast(sn, downloaded, [(vtk_w, node)])
        c._progressive_series[sn] = c._progressive_series.get(
            sn, {"total": total, "last_grow_count": 0, "last_signal_ms": 0}
        )
        c._progressive_series[sn]["last_grow_count"] = current_count[0]

    all_non_negative = all(v >= 0 for v in avail_calls)
    monotonic = all(avail_calls[i] <= avail_calls[i + 1] for i in range(len(avail_calls) - 1))
    final_ok = avail_calls[-1] == total if avail_calls else False

    _kpi.record(scenario, "all avail counts ≥ 0", str(all_non_negative), passed=all_non_negative)
    _kpi.record(scenario, "counts are non-decreasing", str(monotonic), passed=monotonic)
    _kpi.record(scenario, "final count == total (100)",
                avail_calls[-1] if avail_calls else -1, passed=final_ok)

    assert all_non_negative, f"Negative count found in {avail_calls}"
    assert monotonic, f"Counts not monotonic: {avail_calls}"
    assert final_ok, f"Final count must be {total}, got {avail_calls[-1] if avail_calls else 'empty'}"
    print(f"✅ L20 passed  (avail_calls={avail_calls})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L21: Stale grow — timer restarted and retry tracking activated
# ═══════════════════════════════════════════════════════════════════════════════

def test_stale_grow_restarts_timer_and_tracks_retry():
    """
    L21: When loader.grow() returns fewer slices than expected (OS file-flush
    delay), _grow_progressive_fast must:
      1. Increment _stale_retry_count to 1 (max 3 retries)
      2. Set pending_downloaded = pending_count so _flush_progressive_grow retries
      3. Call timer.start() so the single-shot timer fires again for the retry
      4. NOT call exit_progressive_mode (series is not complete yet)
      5. Log a STALE warning

    ROOT CAUSE of the "last N images stuck" bug: the single-shot timer fires
    once, loader.grow() returns a stale count (OS buffers not yet flushed to
    disk), last_grow_count is set to the stale value, and without this fix
    the timer never fires again — the viewer is stuck forever.
    """
    scenario = "L21: stale grow — timer restarted, retry tracked, exit NOT called"

    c = _build_controller()
    sn = "21"
    c._progressive_series = {sn: {"total": 25, "last_grow_count": 20, "last_signal_ms": 0}}

    # grow() returns 20 instead of the expected 25 (stale OS file list)
    stale_count = 20
    pending_count = 25
    loader = SimpleNamespace(
        slice_count=stale_count,
        vtk_image_data=object(),
        grow=lambda: stale_count,
        backend=SimpleNamespace(
            get_file_paths=lambda: [f"f{i}.dcm" for i in range(stale_count)],
        ),
    )
    reslice, _ = _make_mock_reslice(vtk_image_data=loader.vtk_image_data)
    vtk_w = _make_vtk_widget(series_number=sn, loader=loader, reslice=reslice,
                              progressive_mode=True)
    node = _make_node(vtk_w)

    timer_starts: List[int] = []
    mock_timer = SimpleNamespace(
        start=lambda: timer_starts.append(1),
        isActive=lambda: False,   # single-shot already fired — not active
        interval=lambda: 150,
    )
    c._progressive_grow_timer = mock_timer

    warning_logs: List[str] = []
    c.logger = SimpleNamespace(
        info=lambda *a, **kw: None,
        debug=lambda *a, **kw: None,
        warning=lambda fmt, *a, **kw: warning_logs.append(fmt % a if a else fmt),
        error=lambda *a, **kw: None,
    )

    c._grow_progressive_fast(sn, pending_count, [(vtk_w, node)])

    info = c._progressive_series.get(sn, {})
    retry_ok    = info.get("_stale_retry_count", 0) == 1
    pending_ok  = info.get("pending_downloaded", 0) == pending_count
    timer_ok    = len(timer_starts) >= 1
    no_exit     = len(vtk_w._exit_pm_calls) == 0
    warned      = any("STALE" in w for w in warning_logs)

    _kpi.record(scenario, "_stale_retry_count = 1",
                info.get("_stale_retry_count", -1), passed=retry_ok)
    _kpi.record(scenario, "pending_downloaded set to expected (25)",
                info.get("pending_downloaded", -1), passed=pending_ok)
    _kpi.record(scenario, "timer.start() called for retry",
                len(timer_starts), passed=timer_ok)
    _kpi.record(scenario, "exit_progressive_mode NOT called",
                len(vtk_w._exit_pm_calls), passed=no_exit)
    _kpi.record(scenario, "STALE warning logged", str(warned), passed=warned)

    assert retry_ok, f"_stale_retry_count must be 1, got {info.get('_stale_retry_count')}"
    assert pending_ok, (
        f"pending_downloaded must be {pending_count}, got {info.get('pending_downloaded')}"
    )
    assert timer_ok, f"timer.start() must be called, got {timer_starts}"
    assert no_exit, f"exit_progressive_mode must not fire on stale, got {vtk_w._exit_pm_calls}"
    assert warned, f"STALE warning must be logged, got {warning_logs}"
    print(
        f"✅ L21 passed  "
        f"(retry={info.get('_stale_retry_count')}, pending={info.get('pending_downloaded')}, "
        f"timer_starts={len(timer_starts)}, exit_pm={vtk_w._exit_pm_calls})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  L22: One-shot path stale grow — non-progressive viewer enters progressive mode
# ═══════════════════════════════════════════════════════════════════════════════

def test_one_shot_stale_grow_sets_up_retry_via_progressive_mode():
    """
    L22: The "one-shot path" fires when a non-progressive viewer shows the series
    and the download-completion signal (downloaded == total) arrives.
    _grow_progressive_fast is called *directly* — not via the timer — with a
    viewer that has _progressive_mode = False.

    If loader.grow() returns a stale count the viewer MUST:
      1. Call enter_progressive_mode() so _find_progressive_viewers() can locate
         it on the retry tick inside _flush_progressive_grow
      2. Start the single-shot timer so the retry fires in 150ms
      3. Set pending_downloaded = pending_count to satisfy the retry condition

    Without enter_progressive_mode(), _flush_progressive_grow calls
    _find_progressive_viewers() → returns [] → skips → last N images stuck.
    """
    scenario = "L22: one-shot stale grow — viewer enters prog mode for retry"

    c = _build_controller()
    sn = "22"
    c._progressive_series = {sn: {"total": 25, "last_grow_count": 0, "last_signal_ms": 0}}

    stale_count = 20
    pending_count = 25
    loader = SimpleNamespace(
        slice_count=stale_count,
        vtk_image_data=object(),
        grow=lambda: stale_count,   # stale: 5 files not yet visible to scandir
        backend=SimpleNamespace(
            get_file_paths=lambda: [f"f{i}.dcm" for i in range(stale_count)],
        ),
    )
    reslice, _ = _make_mock_reslice(vtk_image_data=loader.vtk_image_data)

    # *** Non-progressive viewer — this is the one-shot path ***
    vtk_w = _make_vtk_widget(
        series_number=sn,
        loader=loader,
        reslice=reslice,
        progressive_mode=False,   # NOT in progressive mode
    )
    node = _make_node(vtk_w)

    timer_starts: List[int] = []
    mock_timer = SimpleNamespace(
        start=lambda: timer_starts.append(1),
        isActive=lambda: False,
        interval=lambda: 150,
    )
    c._progressive_grow_timer = mock_timer
    c.logger = SimpleNamespace(
        info=lambda *a, **kw: None,
        debug=lambda *a, **kw: None,
        warning=lambda *a, **kw: None,
        error=lambda *a, **kw: None,
    )

    # Simulate the one-shot path (on_series_images_progress calls this directly)
    c._grow_progressive_fast(sn, pending_count, [(vtk_w, node)])

    info = c._progressive_series.get(sn, {})
    entered_pm    = len(vtk_w._enter_pm_calls) >= 1
    timer_started = len(timer_starts) >= 1
    pending_set   = info.get("pending_downloaded", 0) == pending_count
    retry_tracked = info.get("_stale_retry_count", 0) >= 1

    _kpi.record(scenario, "enter_progressive_mode called (enables retry lookup)",
                len(vtk_w._enter_pm_calls), passed=entered_pm)
    _kpi.record(scenario, "timer.start() called for retry",
                len(timer_starts), passed=timer_started)
    _kpi.record(scenario, "pending_downloaded set to 25",
                info.get("pending_downloaded", -1), passed=pending_set)
    _kpi.record(scenario, "_stale_retry_count ≥ 1",
                info.get("_stale_retry_count", 0), passed=retry_tracked)

    assert entered_pm, (
        f"enter_progressive_mode must be called on non-progressive viewer so "
        f"the retry tick can locate it; got {vtk_w._enter_pm_calls}"
    )
    assert timer_started, (
        f"timer.start() must be called so the retry fires; got {timer_starts}"
    )
    assert pending_set, (
        f"pending_downloaded must be {pending_count}; got {info.get('pending_downloaded')}"
    )
    assert retry_tracked, (
        f"_stale_retry_count must be ≥ 1; got {info.get('_stale_retry_count')}"
    )
    print(
        f"✅ L22 passed  "
        f"(entered_pm={vtk_w._enter_pm_calls}, timer_starts={len(timer_starts)}, "
        f"pending={info.get('pending_downloaded')}, retry={info.get('_stale_retry_count')})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  L23: _flush_progressive_grow safety-net restarts timer on stale grow
# ═══════════════════════════════════════════════════════════════════════════════

def test_flush_progressive_grow_safety_net_restarts_timer():
    """
    L23: _flush_progressive_grow has an independent safety-net that restarts the
    single-shot timer AFTER all series are processed, if any series still has
    pending_downloaded > last_grow_count.

    This is a second protection layer (in addition to the stale guard inside
    _grow_progressive_fast itself).  It ensures the timer restarts even if
    the stale guard fires in a path that doesn't start the timer redundantly.

    Setup: _grow_progressive_fast is mocked to simulate a stale grow — it sets
    last_grow_count = 20 but leaves pending_downloaded = 25 untouched.
    After the loop, the safety-net code must call timer.start().
    """
    scenario = "L23: _flush_progressive_grow safety-net restarts timer after stale"

    c = _build_controller()
    sn = "23"
    # pending_downloaded(25) > last_grow_count(20) → will try to grow
    c._progressive_series = {
        sn: {"total": 25, "last_grow_count": 20, "pending_downloaded": 25}
    }

    vtk_w = SimpleNamespace(_progressive_mode=True, _progressive_series_number=sn)
    node  = SimpleNamespace(vtk_widget=vtk_w, slider=None)
    c._find_progressive_viewers = lambda s: [(vtk_w, node)] if s == sn else []

    # Mock _grow_progressive_fast: stale — only sets last_grow_count to 20 (not 25)
    grow_calls: List[Any] = []
    def _mock_stale_grow(series_number, pending, viewers):
        grow_calls.append((series_number, pending))
        c._progressive_series[series_number]["last_grow_count"] = 20  # stale

    c._grow_progressive_fast = _mock_stale_grow

    timer_starts: List[int] = []
    mock_timer = SimpleNamespace(
        start=lambda: timer_starts.append(1),
        isActive=lambda: False,
        interval=lambda: 150,
    )
    c._progressive_grow_timer = mock_timer
    c.logger = SimpleNamespace(
        info=lambda *a, **kw: None,
        debug=lambda *a, **kw: None,
        warning=lambda *a, **kw: None,
        error=lambda *a, **kw: None,
    )

    c._flush_progressive_grow()

    # After processing: pending(25) > last_grow_count(20) → safety-net must restart timer
    timer_ok = len(timer_starts) >= 1

    _kpi.record(scenario, "safety-net timer.start() called after stale grow",
                len(timer_starts), passed=timer_ok)
    _kpi.record(scenario, "_grow_progressive_fast called for series",
                len(grow_calls), passed=(len(grow_calls) >= 1))

    assert len(grow_calls) >= 1, (
        f"_grow_progressive_fast must be called for '{sn}', got {grow_calls}"
    )
    assert timer_ok, (
        f"_flush_progressive_grow safety-net must restart timer when "
        f"pending(25) > last_grow_count(20), got timer_starts={timer_starts}"
    )
    print(
        f"✅ L23 passed  (timer_starts={len(timer_starts)}, grow_calls={len(grow_calls)})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  L24: Done-guard completion one-shot — fires grow on non-progressive viewer
# ═══════════════════════════════════════════════════════════════════════════════

def test_done_guard_completion_triggers_one_shot_grow():
    """
    L24: When *sn* is already in _progressive_display_done (series displayed once)
    AND downloaded >= total (completion signal) AND a non-progressive viewer shows
    that series with fewer slices than downloaded (e.g. stale-grow exhaustion left
    it stuck at 30 of 40), _grow_progressive_fast must be called so the missing
    images become navigable.

    Root cause of Series 201 "scrolls only 30" bug:
      - DM reports total=30 initially → progressive completes at 30
      - 10 more images arrive → DM sends (40, 40) completion signal
      - Old done-guard hit bare `return` → _grow_progressive_fast never called
      - Viewer stuck at 30 though 40 images are on disk
    """
    scenario = "L24: done-guard completion one-shot triggers _grow_progressive_fast"

    c = _build_controller()
    sn = "24"
    # Simulate series already displayed (in done set) but stuck at 30 of 40
    c._progressive_display_done = {sn}
    c._progressive_series = {
        sn: {"total": 40, "last_grow_count": 30, "last_signal_ms": 0}
    }

    timer_starts: List[int] = []
    c._progressive_grow_timer = SimpleNamespace(
        start=lambda: timer_starts.append(1),
        isActive=lambda: False,
        interval=lambda: 150,
    )
    c.logger = SimpleNamespace(
        info=lambda *a, **kw: None,
        debug=lambda *a, **kw: None,
        warning=lambda *a, **kw: None,
        error=lambda *a, **kw: None,
    )

    # Non-progressive viewer stuck at 30 slices (after stale-grow exhaustion exit)
    loader = SimpleNamespace(
        slice_count=30,
        vtk_image_data=object(),
        grow=lambda: 40,  # real count is 40 — OS has flushed by now
        backend=SimpleNamespace(
            get_file_paths=lambda: [f"f{i}.dcm" for i in range(40)],
        ),
    )
    reslice, _ = _make_mock_reslice(vtk_image_data=loader.vtk_image_data)
    vtk_w = _make_vtk_widget(
        series_number=sn, loader=loader, reslice=reslice, progressive_mode=False,
    )
    node = _make_node(vtk_w)
    c.lst_nodes_viewer = [node]

    # _find_progressive_viewers returns [] (viewer is non-progressive after exhaustion)
    c._find_progressive_viewers = lambda s: []

    # Mock _grow_progressive_fast to capture calls
    grow_calls: List[Any] = []
    c._grow_progressive_fast = lambda sn_, dl_, vwrs_: grow_calls.append((sn_, dl_))

    c.on_series_images_progress(sn, 40, 40)

    grow_fired = len(grow_calls) >= 1

    _kpi.record(scenario, "_grow_progressive_fast called for completion one-shot",
                len(grow_calls), passed=grow_fired)

    assert grow_fired, (
        f"_grow_progressive_fast must fire for done-guard completion one-shot "
        f"(sn={sn}, stuck at 30, completion signal 40/40); got grow_calls={grow_calls}"
    )
    print(f"✅ L24 passed  (grow_calls={grow_calls})")


# ═══════════════════════════════════════════════════════════════════════════════
#  L25: Stale exhaustion — progressive mode exited, safety-net stopped
# ═══════════════════════════════════════════════════════════════════════════════

def test_stale_grow_exhaustion_exits_progressive_mode():
    """
    L25: When _stale_retry_count has reached _STALE_RETRY_MAX (5) and
    loader.grow() still returns a stale count, _grow_progressive_fast must:
      1. Log STALE-EXHAUSTED error
      2. Pop the series from _progressive_series (stops safety-net loop)
      3. Call exit_progressive_mode() on each viewer
      4. Update slider to (stale_count - 1) so no empty positions are accessible
      5. NOT restart the timer (prevents infinite safety-net loop)
      6. Return early — step 6 (exit) does NOT run again

    Root cause of infinite loop bug: without exhaustion handling, the safety-net
    _flush_progressive_grow endlessly calls _grow_progressive_fast when
    pending_downloaded(40) > last_grow_count(30), even after max retries.
    """
    scenario = "L25: stale exhaustion exits progressive mode and stops safety-net"

    c = _build_controller()
    sn = "25"
    # Already at max retries
    c._progressive_series = {
        sn: {
            "total": 40,
            "last_grow_count": 30,
            "last_signal_ms": 0,
            "_stale_retry_count": 5,  # already exhausted
            "pending_downloaded": 40,
        }
    }

    stale_count = 30
    loader = SimpleNamespace(
        slice_count=stale_count,
        vtk_image_data=object(),
        grow=lambda: stale_count,  # still stale
        backend=SimpleNamespace(
            get_file_paths=lambda: [f"f{i}.dcm" for i in range(stale_count)],
        ),
    )
    reslice, _ = _make_mock_reslice(vtk_image_data=loader.vtk_image_data)
    vtk_w = _make_vtk_widget(
        series_number=sn, loader=loader, reslice=reslice, progressive_mode=True,
    )
    slider = _make_slider()
    node = _make_node(vtk_w, slider)

    timer_starts: List[int] = []
    c._progressive_grow_timer = SimpleNamespace(
        start=lambda: timer_starts.append(1),
        isActive=lambda: False,
        interval=lambda: 150,
    )
    error_logs: List[str] = []
    c.logger = SimpleNamespace(
        info=lambda *a, **kw: None,
        debug=lambda *a, **kw: None,
        warning=lambda *a, **kw: None,
        error=lambda fmt, *a, **kw: error_logs.append(fmt % a if a else fmt),
    )

    c._grow_progressive_fast(sn, 40, [(vtk_w, node)])

    popped         = sn not in c._progressive_series
    exited         = len(vtk_w._exit_pm_calls) >= 1
    slider_updated = slider._set_max_calls and slider._set_max_calls[-1] == stale_count - 1
    no_timer       = len(timer_starts) == 0
    errored        = any("STALE-EXHAUSTED" in e for e in error_logs)

    _kpi.record(scenario, "series popped from _progressive_series", popped, passed=popped)
    _kpi.record(scenario, "exit_progressive_mode called",
                len(vtk_w._exit_pm_calls), passed=exited)
    _kpi.record(scenario, "slider set to stale_count - 1",
                slider._set_max_calls[-1] if slider._set_max_calls else -1, passed=slider_updated)
    _kpi.record(scenario, "timer NOT restarted on exhaustion",
                len(timer_starts), passed=no_timer)
    _kpi.record(scenario, "STALE-EXHAUSTED error logged", str(errored), passed=errored)

    assert popped, f"series must be popped on exhaustion; _progressive_series={c._progressive_series}"
    assert exited, f"exit_progressive_mode must be called; exit_calls={vtk_w._exit_pm_calls}"
    assert slider_updated, (
        f"slider must be set to {stale_count - 1}; calls={slider._set_max_calls}"
    )
    assert no_timer, (
        f"timer must NOT restart on exhaustion (prevents safety-net loop); starts={timer_starts}"
    )
    assert errored, f"STALE-EXHAUSTED error must be logged; logs={error_logs}"
    print(
        f"✅ L25 passed  "
        f"(popped={popped}, exited={exited}, slider={slider._set_max_calls}, timer={timer_starts})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  L26: _refresh_stored_metadata_instances updates series["image_count"]
# ═══════════════════════════════════════════════════════════════════════════════

def test_refresh_metadata_updates_series_image_count(tmp_path):
    """
    L26: _refresh_stored_metadata_instances must update metadata["series"]["image_count"]
    to reflect the actual number of downloaded instances.

    Root cause of Series 201 thumbnail showing 20 instead of 40:
      - Server metadata reports image_count = 20
      - 40 files downloaded to disk
      - _refresh_stored_metadata_instances only updated metadata["instances"]
      - metadata["series"]["image_count"] stayed at 20
      - Thumbnail reads image_count → shows "20"

    After the fix: image_count is set to len(new_instances) after each grow.
    """
    import tempfile, os
    scenario = "L26: _refresh_stored_metadata_instances updates series image_count"

    sn = "201"

    # Create fake .dcm files (40 total, 30 already in metadata)
    series_dir = tmp_path / sn
    series_dir.mkdir()
    dcm_files = []
    for i in range(40):
        p = series_dir / f"Instance_{i + 1:04d}.dcm"
        p.write_bytes(b"DICM")  # minimal placeholder
        dcm_files.append(p)

    # Existing instances: only 30 (server-reported count = 20 in series meta)
    existing_instances = [
        {
            "instance_number": i,
            "instance_path": str(series_dir / f"Instance_{i + 1:04d}.dcm"),
            "window_width": 400,
            "window_center": 40,
        }
        for i in range(30)
    ]
    metadata = {
        "series": {
            "series_number": sn,
            "image_count": 20,  # old server-reported count
            "series_path": str(series_dir),
        },
        "instances": existing_instances,
    }

    c = controller_mod.ViewerController.__new__(controller_mod.ViewerController)
    c.logger = SimpleNamespace(
        info=lambda *a, **kw: None,
        debug=lambda *a, **kw: None,
        warning=lambda *a, **kw: None,
        error=lambda *a, **kw: None,
    )
    c._series_number_to_index = {sn: 0}
    c.parent_widget = SimpleNamespace(
        lst_thumbnails_data=[{"metadata": metadata}]
    )
    c._disk_count_cache = {}  # empty TTL cache
    c._series_cache = {}
    c._hot_series_cache = {}
    c._get_correct_study_path = lambda: str(tmp_path)

    # current_disk_count = 40 (DM reports 40 downloaded)
    c._refresh_stored_metadata_instances(sn, 40)

    instances_ok  = len(metadata["instances"]) == 40
    image_count_ok = metadata["series"]["image_count"] == 40

    _kpi.record(scenario, "metadata['instances'] length == 40",
                len(metadata["instances"]), passed=instances_ok)
    _kpi.record(scenario,
                "metadata['series']['image_count'] updated from 20 → 40",
                metadata["series"]["image_count"], passed=image_count_ok)

    assert instances_ok, (
        f"metadata['instances'] must have 40 entries; got {len(metadata['instances'])}"
    )
    assert image_count_ok, (
        f"metadata['series']['image_count'] must be 40 (was 20); "
        f"got {metadata['series']['image_count']}"
    )
    print(
        f"✅ L26 passed  "
        f"(instances={len(metadata['instances'])}, image_count={metadata['series']['image_count']})"
    )




if __name__ == "__main__":
    import traceback

    tests = [
        test_grow_refreshes_via_loader_grow_not_backend_directly,
        test_grow_updates_available_slice_count_each_batch,
        test_grow_updates_slider_max_each_batch,
        test_grow_updates_booster_paths_when_active,
        test_grow_skips_booster_update_when_different_series_active,
        test_grow_calls_exit_progressive_mode_on_completion,
        test_grow_keeps_progressive_mode_when_incomplete,
        test_grow_updates_both_viewers_in_2x2_layout,
        test_grow_uses_qt_bridge_when_qt_bridge_active,
        test_grow_fallback_to_backend_refresh_when_loader_has_no_grow,
        test_grow_uses_pending_count_when_no_loader,
        test_multi_batch_lifecycle_10_batches,
        test_last_batch_clears_progressive_series,
        test_refresh_stored_metadata_called_each_grow,
        test_grow_dispatch_kpi_10_batches_fast,
        test_routing_progressive_viewer_found_starts_grow_timer,
        test_routing_below_batch_delta_no_grow,
        test_routing_completion_signal_always_triggers_grow,
        test_reslice_extent_updated_every_batch,
        test_available_counts_monotonically_non_decreasing,
        test_stale_grow_restarts_timer_and_tracks_retry,
        test_one_shot_stale_grow_sets_up_retry_via_progressive_mode,
        test_flush_progressive_grow_safety_net_restarts_timer,
        test_done_guard_completion_triggers_one_shot_grow,
        test_stale_grow_exhaustion_exits_progressive_mode,
        # L26 uses tmp_path fixture (only via pytest), excluded from __main__
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
