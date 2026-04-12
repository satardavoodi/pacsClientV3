"""
s11_post_fix_repeated_open.py
==============================
H4 post-fix validation: same series opened and closed 3× using REAL production
method logic (bound via types.MethodType) instead of no-op mocks.

Purpose
-------
s08_repeated_open is a DETECTION baseline — it uses synthetic no-op mocks and
is expected to produce H4 CONFIRMED both before and after the fix (it validates
the detector, not production code).

s11 is the POST-FIX HEALTH CHECK.  It binds the real
``_on_series_download_fully_complete_impl`` and ``_on_series_images_progress_impl``
so that the done-guard discard in Layer 2b (Hunk A) actually fires between cycles.

Expected outcomes (healthy, post-fix)
--------------------------------------
- C01_progressive_start_calls == REPEAT_COUNT (3) — each cycle starts fresh
- No FS-18 (done-guard set before any grow event)
- No FS-02 (done-guard key set multiple times without clearing)
- H4 verdict: NO_EVIDENCE or UNLIKELY

Expected outcomes (pre-fix / regression)
-----------------------------------------
- C01_progressive_start_calls < REPEAT_COUNT
- FS-18, FS-02 present
- H4 verdict: CONFIRMED or LIKELY

Run command
-----------
    python tests/diagnostics/run_diagnostic.py --scenario s11_post_fix_repeated_open
"""
from __future__ import annotations

import types
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from tests.diagnostics.harness import DiagnosticHarness, HarnessResult
from tests.diagnostics.event_log import (
    ET_DONE_GUARD_SET,
    ET_TAB_CLOSED,
    ET_TAB_OPENED,
)

SCENARIO_NAME = "s11_post_fix_repeated_open"
MODALITY = "CT"
SLICE_COUNT = 120
SERIES_NUMBER = "1"
REPEAT_COUNT = 3


def _build_real_controller():
    """Build a minimal controller with REAL _VCProgressiveMixin methods bound.

    Unlike the harness mock controller (which uses no-ops for all methods),
    this controller binds the production completion and progress-impl methods
    so that done.discard() actually fires.  All other helpers are stubs that
    return safe defaults.
    """
    from PacsClient.pacs.patient_tab.ui.patient_ui import _vc_progressive as _prog_mod

    def _noop(*a, **kw):
        return None

    ctrl = SimpleNamespace()
    ctrl.logger = SimpleNamespace(
        info=_noop, debug=_noop, warning=_noop, error=_noop,
    )
    ctrl.lst_nodes_viewer = []
    ctrl._progressive_series = {}
    ctrl._progressive_display_done = set()
    ctrl._progressive_display_inflight = set()
    ctrl._progressive_grow_batch_size = 10
    ctrl._progressive_grow_timer = SimpleNamespace(
        isActive=lambda: False, start=_noop, stop=_noop,
    )
    ctrl._completion_sweep_series_set = set()
    ctrl._completion_sweep_timer = SimpleNamespace(
        isActive=lambda: False, start=_noop, stop=_noop,
    )
    ctrl._disk_count_cache = {}
    ctrl._is_fast_viewer_mode = lambda: True
    # Stub all helpers called by completion impl
    ctrl._refresh_and_sync_metadata = _noop
    ctrl._invalidate_series_caches = _noop
    ctrl._update_vtk_slice_range = _noop
    ctrl._refresh_corner_text = _noop
    ctrl._update_thumbnail_count = _noop
    ctrl._full_cache_put = _noop
    ctrl._count_series_files_on_disk = lambda sn: 0
    ctrl._completion_verify_series = _noop
    ctrl._completion_sweep_register = _noop
    ctrl._find_progressive_viewers = types.MethodType(
        _prog_mod._VCProgressiveMixin._find_progressive_viewers, ctrl
    )
    ctrl.parent_widget = SimpleNamespace(
        lst_thumbnails_data=[],
        thumbnail_manager=SimpleNamespace(update_series_image_count=_noop),
    )

    # _start_progressive_display is a lightweight stub (no async machinery needed)
    # but NOT a no-op — it adds the done-guard just like the real method does,
    # so inflight cleanup fires and subsequent progress signals see a clean state.
    def _stub_start_progressive_display(sn, downloaded, total, **kw):
        # Simulate the done-guard being set after first display
        done = getattr(ctrl, '_progressive_display_done', None)
        if done is not None:
            done.add(str(sn))
        inflight = getattr(ctrl, '_progressive_display_inflight', None)
        if inflight is not None:
            inflight.discard(str(sn))

    ctrl._start_progressive_display = _stub_start_progressive_display

    # Bind the REAL production methods (includes done.discard in completion path)
    ctrl.on_series_download_fully_complete = types.MethodType(
        _prog_mod._VCProgressiveMixin.on_series_download_fully_complete, ctrl
    )
    ctrl._on_series_download_fully_complete_impl = types.MethodType(
        _prog_mod._VCProgressiveMixin._on_series_download_fully_complete_impl, ctrl
    )
    ctrl._on_series_images_progress_impl = types.MethodType(
        _prog_mod._VCProgressiveMixin._on_series_images_progress_impl, ctrl
    )
    # Outer guard delegates to impl — bind real outer guard too
    ctrl.on_series_images_progress = types.MethodType(
        _prog_mod._VCProgressiveMixin.on_series_images_progress, ctrl
    )
    return ctrl


def run(
    harness: Optional[DiagnosticHarness] = None,
    output_dir: Optional[Path] = None,
    run_count: int = 1,
) -> HarnessResult:
    """Run s11_post_fix_repeated_open.

    Unlike s08, this scenario uses a controller with REAL production methods so
    that the H4 fix (done.discard in Layer 2b) fires between cycles.

    Parameters
    ----------
    run_count : int
        Which of the N repetitions this is.
    """
    if harness is None:
        harness = DiagnosticHarness(
            scenario_name=SCENARIO_NAME,
            output_dir=output_dir,
            modality=MODALITY,
            slice_count=SLICE_COUNT,
            run_count=run_count,
        )

    with harness:
        # Override the harness mock controller with one that runs real production code
        real_ctrl = _build_real_controller()
        harness._kpi.attach_controller(real_ctrl)
        harness._controller = real_ctrl

        for cycle in range(1, REPEAT_COUNT + 1):
            label = f"cycle_{cycle}"

            # Open
            harness.step(f"{label}_open")
            harness._log.append(
                ET_TAB_OPENED,
                series_number=SERIES_NUMBER,
                cycle=cycle,
            )

            # Download and progressive display
            harness.emit_progress(SERIES_NUMBER, 20, SLICE_COUNT)
            harness.emit_progress(SERIES_NUMBER, 80, SLICE_COUNT, times=3)
            harness.emit_progress(SERIES_NUMBER, SLICE_COUNT, SLICE_COUNT)
            harness.emit_download_complete(SERIES_NUMBER)

            # Done-guard set by framework after completion (mirrors s08 structure)
            harness._log.append(
                ET_DONE_GUARD_SET,
                series_number=SERIES_NUMBER,
                cycle=cycle,
            )

            # Close — in the real system the done-guard is now cleared by the
            # H4 fix in on_series_download_fully_complete.  The ET_TAB_CLOSED
            # event tells the detector to check for stale keys.
            harness.step(f"{label}_close")
            harness._log.append(
                ET_TAB_CLOSED,
                series_number=SERIES_NUMBER,
                cycle=cycle,
            )

        return harness.finish()
