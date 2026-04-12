"""
s03_large_ct.py
===============
PRIMARY crash scenario: 400-slice CT series with rapid progress signals.

Purpose
-------
This is the primary probe for H1 (Metadata scan stalls main thread).

In production the crash/freeze occurs when:
  1. DM sends a rapid burst of seriesProgressUpdated signals (100ms throttle).
  2. Each signal calls on_series_images_progress → _grow_progressive_fast.
  3. _grow_progressive_fast calls _refresh_stored_metadata_instances which
     scans the DICOM directory with Path.iterdir() for all 400 files.
  4. On some systems the scan blocks the Qt event loop for 200–500 ms per call.
  5. The viewer freezes and the _progressive_grow_timer starves.

Failure signatures probed
-------------------------
- FS-04: METADATA_STALL (primary H1 indicator; _refresh > 200 ms)
- FS-08: SIGNAL_QUEUE_OVERFLOW (>50 progress signals before first grow)
- FS-20: TIMER_NEVER_FIRES (progressive timer active but no grow)
- FS-09: PROGRESSIVE_NEVER_STARTED (inflight stuck but no start)

Expected outcomes when H1 present
----------------------------------
- T05_metadata_refresh_max_ms > 200
- C04_metadata_refresh_calls >= 5
- HypothesisResult(H1).verdict in ("CONFIRMED", "LIKELY")

Expected outcomes on healthy system
-------------------------------------
- T05_metadata_refresh_max_ms < 100
- HypothesisResult(H1).verdict == "POSSIBLE" or below threshold
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from tests.diagnostics.harness import DiagnosticHarness, HarnessResult


SCENARIO_NAME = "s03_large_ct"
MODALITY = "CT"
SLICE_COUNT = 400
SERIES_NUMBER = "1"

# Number of rapid progress bursts to simulate DM's 100ms throttle firing
# repeatedly during a large CT download.
BURST_COUNT = 12


def run(
    harness: Optional[DiagnosticHarness] = None,
    output_dir: Optional[Path] = None,
    run_count: int = 1,
) -> HarnessResult:
    """Run s03_large_ct.

    Parameters
    ----------
    harness : DiagnosticHarness | None
        If None, a new harness is created.
    output_dir : Path | None
        Artifact directory (only used when harness is None).
    run_count : int
        Which run this is in a multi-run sequence (H1 scoring uses ≥ 3 runs).
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
        harness.make_controller()

        # Phase 1: first small batch (triggers _start_progressive_display)
        harness.step("first_batch")
        harness.emit_progress(SERIES_NUMBER, 20, SLICE_COUNT)

        # Phase 2: rapid-fire burst (each call → _grow_progressive_fast →
        #   _refresh_stored_metadata_instances on all 400 files).
        harness.step("rapid_burst_start")
        batch_size = SLICE_COUNT // BURST_COUNT
        for i in range(1, BURST_COUNT):
            downloaded = min((i + 1) * batch_size, SLICE_COUNT)
            harness.emit_progress(SERIES_NUMBER, downloaded, SLICE_COUNT)

        harness.step("rapid_burst_end")
        harness.snapshot_memory()

        # Phase 3: near-complete
        harness.step("near_complete")
        harness.emit_progress(SERIES_NUMBER, SLICE_COUNT - 5, SLICE_COUNT)

        # Phase 4: completion pulse (Layer 2a — downloaded == total)
        harness.step("completion_pulse")
        harness.emit_progress(SERIES_NUMBER, SLICE_COUNT, SLICE_COUNT)

        # Phase 5: Layer 2b — on_series_download_fully_complete
        harness.step("download_complete")
        harness.emit_download_complete(SERIES_NUMBER)

        harness.snapshot_memory()

        return harness.finish()
