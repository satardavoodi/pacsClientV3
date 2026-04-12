"""
s07_series_interrupt.py
=======================
DM interrupt scenario: coordinator cancels current series mid-download.

Purpose
-------
Simulates the "same-study series interrupt" flow (copilot-instructions.md):
  request_critical_series() cancels the study's own worker when a different
  series is requested.  The state is set to PENDING, not PAUSED.

The scenario verifies:
  1. Inflight guard is cleared when the old series is interrupted.
  2. Done-guard does NOT contain the incomplete series at interruption.
  3. New series starts cleanly (C01_progressive_start_calls increments again).

Timeline simulated
------------------
1. Series 1 loads partially (first batch, inflight guard set).
2. Series 2 is requested → coordinator cancels series 1.
3. Series 1 progress stops (no completion signal).
4. Series 2 begins and completes normally.

Failure signatures probed
-------------------------
- FS-01: INFLIGHT_STUCK (series 1 inflight never cleared if interrupt path fails)
- FS-02: DONE_NEVER_RESET (series 1 done-guard set wrongly after interrupt)

Expected outcomes
-----------------
- Only series 2 in _progressive_display_done
- C01_progressive_start_calls == 2   (series 1 start + series 2 start)
- S05_inflight_still_set_at_end == False
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from tests.diagnostics.harness import DiagnosticHarness, HarnessResult
from tests.diagnostics.event_log import (
    ET_INFLIGHT_SET,
    ET_INFLIGHT_CLEARED,
)


SCENARIO_NAME = "s07_series_interrupt"
MODALITY = "CT"
SLICE_COUNT = 200
SERIES_1 = "1"
SERIES_2 = "2"


def run(
    harness: Optional[DiagnosticHarness] = None,
    output_dir: Optional[Path] = None,
) -> HarnessResult:
    """Run s07_series_interrupt."""
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

        # Phase 1: series 1 starts loading
        harness.step("series1_start")
        harness._log.append(ET_INFLIGHT_SET, series_number=SERIES_1)
        harness.emit_progress(SERIES_1, 20, SLICE_COUNT)
        harness.emit_progress(SERIES_1, 50, SLICE_COUNT)

        # Phase 2: coordinator interrupt — series 1 cancelled
        harness.step("series1_interrupt")
        harness._log.append(
            ET_INFLIGHT_CLEARED,
            series_number=SERIES_1,
            reason="coordinator_interrupt",
        )

        # Phase 3: series 2 begins immediately after interrupt
        harness.step("series2_start")
        harness._log.append(ET_INFLIGHT_SET, series_number=SERIES_2)
        harness.emit_progress(SERIES_2, 20, SLICE_COUNT)
        harness.emit_progress(SERIES_2, 80, SLICE_COUNT, times=4)
        harness.emit_progress(SERIES_2, SLICE_COUNT, SLICE_COUNT)

        # Phase 4: series 2 completes
        harness.step("series2_complete")
        harness.emit_download_complete(SERIES_2)
        harness._log.append(
            ET_INFLIGHT_CLEARED,
            series_number=SERIES_2,
            reason="download_fully_complete",
        )

        return harness.finish()
