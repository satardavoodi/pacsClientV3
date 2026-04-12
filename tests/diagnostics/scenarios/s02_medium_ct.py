"""
s02_medium_ct.py
================
Intermediate scenario: 120-slice CT series loaded without induced errors.

Purpose
-------
- Bridge between MR baseline (25 slices) and the large CT scenario (400 slices).
- Confirms that moderate CT series load without framework failures.
- T05_metadata_refresh_max_ms expected < 100 ms on well-resourced hardware.

Expected outcomes
-----------------
- C01_progressive_start_calls >= 1
- T01_first_progress_to_first_grow_ms < 2000
- No FS-04 (metadata stall) at this slice count
- RSS delta < 500 MB
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from tests.diagnostics.harness import DiagnosticHarness, HarnessResult


SCENARIO_NAME = "s02_medium_ct"
MODALITY = "CT"
SLICE_COUNT = 120
SERIES_NUMBER = "1"


def run(
    harness: Optional[DiagnosticHarness] = None,
    output_dir: Optional[Path] = None,
) -> HarnessResult:
    """Run s02_medium_ct."""
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

        # Phase 1: first small batch
        harness.step("first_batch")
        harness.emit_progress(SERIES_NUMBER, 10, SLICE_COUNT)

        # Phase 2: burst of batches (simulate DM 100ms throttle intervals)
        harness.step("burst_batches")
        harness.emit_progress(SERIES_NUMBER, 60, SLICE_COUNT, times=5)

        # Phase 3: final batch
        harness.step("final_batch")
        harness.emit_progress(SERIES_NUMBER, 110, SLICE_COUNT)
        harness.emit_progress(SERIES_NUMBER, SLICE_COUNT, SLICE_COUNT)

        harness.snapshot_memory()

        # Phase 4: completion
        harness.step("download_complete")
        harness.emit_download_complete(SERIES_NUMBER)

        return harness.finish()
