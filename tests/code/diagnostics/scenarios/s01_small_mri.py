"""
s01_small_mri.py
================
Baseline scenario: 25-slice MRI series loaded without errors.

Purpose
-------
- Establish per-KPI baseline values for MR modality.
- Used as the MR reference in s09_mri_vs_ct comparison.
- Should produce zero CRITICAL findings under normal conditions.

Expected outcomes
-----------------
- C01_progressive_start_calls >= 1
- T01_first_progress_to_first_grow_ms < 2000   (< 2 s)
- No FS-04 (metadata stall)
- No FS-17 (memory pressure)
- Hypotheses H1, H4 NOT CONFIRMED (MR is the healthy baseline)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from tests.diagnostics.harness import DiagnosticHarness, HarnessResult


SCENARIO_NAME = "s01_small_mri"
MODALITY = "MR"
SLICE_COUNT = 25
SERIES_NUMBER = "1"


def run(
    harness: Optional[DiagnosticHarness] = None,
    output_dir: Optional[Path] = None,
) -> HarnessResult:
    """Run s01_small_mri.

    Parameters
    ----------
    harness : DiagnosticHarness | None
        Pre-built harness (e.g. from conftest).  If None, one is created.
    output_dir : Path | None
        Where to write artifacts (only used when harness is None).

    Returns
    -------
    HarnessResult
    """
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

        # --- Phase 1: early progress (first 5 slices) -------------------------
        harness.step("early_progress_batch")
        harness.emit_progress(SERIES_NUMBER, 5, SLICE_COUNT)

        # --- Phase 2: mid-download progress (batches) -------------------------
        harness.step("mid_progress_batches")
        harness.emit_progress(SERIES_NUMBER, 15, SLICE_COUNT, times=3)

        # --- Phase 3: near-complete ------------------------------------------
        harness.step("near_complete_progress")
        harness.emit_progress(SERIES_NUMBER, 23, SLICE_COUNT)

        # --- Phase 4: download complete signal --------------------------------
        harness.step("download_complete")
        harness.emit_progress(SERIES_NUMBER, SLICE_COUNT, SLICE_COUNT)
        harness.emit_download_complete(SERIES_NUMBER)

        return harness.finish()
