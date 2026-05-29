"""
s05_scroll_completion.py
========================
H6 probe: scroll during the final grow window.

Purpose
-------
Simulates the case where a user scrolls through the viewer while
the final batches of a large CT series are being applied (Layer 2b/3).
This probes FS-13 (COMPLETION_LAYER2_MISSED): does the viewer correctly
receive and apply the last grow after on_series_download_fully_complete?

Timeline simulated
------------------
1. CT series load begins (80% complete).
2. User starts scrolling (series_switch BEGIN/DONE events interleaved with
   grow events — simulates _set_slice overhead competing with grow).
3. Final batch arrives (downloaded == total).
4. on_series_download_fully_complete fires.
5. Check: S01_final_grow_count == SLICE_COUNT.

Failure signatures probed
-------------------------
- FS-13: COMPLETION_LAYER2_MISSED (final grow after fully_complete = 0)
- FS-01: INFLIGHT_STUCK (series switch blocked the inflight guard)
- FS-12: DOWNLOAD_START_LATENCY (first grow delayed by scroll overhead)

Expected on healthy system
--------------------------
- T04_download_complete_to_final_grow_ms < 300
- S01_final_grow_count == SLICE_COUNT
- No FS-13
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from tests.diagnostics.harness import DiagnosticHarness, HarnessResult
from tests.diagnostics.event_log import (
    ET_SERIES_SWITCH_BEGIN,
    ET_SERIES_SWITCH_DONE,
)


SCENARIO_NAME = "s05_scroll_completion"
MODALITY = "CT"
SLICE_COUNT = 400
SERIES_NUMBER = "1"


def run(
    harness: Optional[DiagnosticHarness] = None,
    output_dir: Optional[Path] = None,
) -> HarnessResult:
    """Run s05_scroll_completion."""
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

        # Phase 1: series opens and progresses normally to 80%
        harness.step("initial_load_80pct")
        harness.emit_progress(SERIES_NUMBER, 20, SLICE_COUNT)
        harness.emit_progress(SERIES_NUMBER, 80, SLICE_COUNT, times=4)
        harness.emit_progress(SERIES_NUMBER, 320, SLICE_COUNT)

        # Phase 2: user starts scrolling (interleaved series-switch events)
        harness.step("scroll_begin")
        for i in range(5):
            harness._log.append(
                ET_SERIES_SWITCH_BEGIN,
                series_number=SERIES_NUMBER,
                target_slice=i * 30,
            )
            harness._log.append(
                ET_SERIES_SWITCH_DONE,
                series_number=SERIES_NUMBER,
                target_slice=i * 30,
            )
            # Interleaved progress signal during scroll
            harness.emit_progress(
                SERIES_NUMBER,
                min(320 + (i + 1) * 16, SLICE_COUNT - 5),
                SLICE_COUNT,
            )

        # Phase 3: completion pulse arrives during or just after scroll
        harness.step("completion_during_scroll")
        harness.emit_progress(SERIES_NUMBER, SLICE_COUNT, SLICE_COUNT)

        # Phase 4: Layer 2b — on_series_download_fully_complete
        harness.step("download_complete")
        harness.emit_download_complete(SERIES_NUMBER)

        harness.snapshot_memory()
        return harness.finish()
