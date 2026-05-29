"""
s04_early_teardown.py
=====================
H2 probe: widget destroyed while download/decode is still in progress.

Purpose
-------
Tests the teardown-decode race condition (H2: DestroyedWidget UAF crash).

Timeline simulated
------------------
1. Series starts loading (first progress signal received).
2. Widget teardown is triggered mid-download (before completion).
3. Remaining decode signals arrive AFTER teardown.
4. Framework must not crash or log a decode_failed storm.

Failure signatures probed
-------------------------
- FS-06: LOADER_RELEASED_EARLY (grow called after loader released)
- FS-14: LOADER_OUTLIVES_VIEWER (registry key outlives widget)
- FS-11: SLICE_READY_BEFORE_BIND (late decode arriving after teardown)
- FS-07: DECODE_FAILED_STORM (>10 failed decodes in rapid succession)

Expected outcomes
-----------------
- FS-06 or FS-14 present in findings (teardown race exists)
- C16_exceptions_swallowed == 0   (crashes swallowed silently = bad sign)
- HypothesisResult("H2").verdict in ("CONFIRMED", "LIKELY") when FS-14 fires
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from tests.diagnostics.harness import DiagnosticHarness, HarnessResult
from tests.diagnostics.event_log import (
    ET_LOADER_RELEASED,
    ET_WIDGET_DESTROYED,
    ET_DECODE_SLICE_READY,
)


SCENARIO_NAME = "s04_early_teardown"
MODALITY = "CT"
SLICE_COUNT = 120
SERIES_NUMBER = "1"


def run(
    harness: Optional[DiagnosticHarness] = None,
    output_dir: Optional[Path] = None,
) -> HarnessResult:
    """Run s04_early_teardown."""
    if harness is None:
        harness = DiagnosticHarness(
            scenario_name=SCENARIO_NAME,
            output_dir=output_dir,
            modality=MODALITY,
            slice_count=SLICE_COUNT,
            run_count=1,
        )

    with harness:
        harness.make_controller()

        # Phase 1: partial download (50%)
        harness.step("partial_download")
        harness.emit_progress(SERIES_NUMBER, 10, SLICE_COUNT)
        harness.emit_progress(SERIES_NUMBER, 40, SLICE_COUNT)
        harness.emit_progress(SERIES_NUMBER, 60, SLICE_COUNT)

        # Phase 2: simulate widget teardown — log directly into the event stream
        # Without a real widget we emit the event so the failure detector can
        # check the registry sequencing.
        harness.step("teardown")
        harness._log.append(
            ET_WIDGET_DESTROYED,
            series_number=SERIES_NUMBER,
            reason="tab_closed_by_user",
        )

        # Phase 3: loader released (correct teardown path)
        harness._log.append(
            ET_LOADER_RELEASED,
            series_number=SERIES_NUMBER,
        )

        # Phase 4: late decode signals arriving AFTER teardown (the race)
        harness.step("late_decode_signals")
        for slice_idx in range(61, 75):
            harness._log.append(
                ET_DECODE_SLICE_READY,
                series_number=SERIES_NUMBER,
                slice_index=slice_idx,
            )

        harness.snapshot_memory()
        return harness.finish()
