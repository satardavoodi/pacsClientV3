"""
s10_memory_pressure.py
======================
Memory stress scenario: 5 consecutive large CT opens.

Purpose
-------
Probes FS-17 (MEMORY_PRESSURE) and measures peak RSS growth.

Each open loads a 400-slice CT series, completes, and then simulates the
series being closed (no explicit GC triggered between opens — mimics real
app behaviour where the viewer retains the lazy volume until it is evicted).

The scenario captures:
- M01_rss_at_start_mb, M02_rss_peak_mb, M03_rss_at_end_mb
- M04_rss_delta_mb  (total growth over all 5 opens)
- M09_loader_registry_size  (should be 0 after all series are closed)

Failure signatures probed
-------------------------
- FS-17: MEMORY_PRESSURE (RSS > 3 GB during any progressive grow)
- FS-14: LOADER_OUTLIVES_VIEWER (registry not cleared between opens)

Thresholds
----------
- M04_rss_delta_mb < 1500 MB for 5 × 400-slice CT = acceptable
- M09_loader_registry_size == 0 at end = all loaders released
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from tests.diagnostics.harness import DiagnosticHarness, HarnessResult
from tests.diagnostics.event_log import (
    ET_WIDGET_DESTROYED,
    ET_LOADER_RELEASED,
    ET_TAB_CLOSED,
)


SCENARIO_NAME = "s10_memory_pressure"
MODALITY = "CT"
SLICE_COUNT = 400
REPEAT_COUNT = 5


def run(
    harness: Optional[DiagnosticHarness] = None,
    output_dir: Optional[Path] = None,
) -> HarnessResult:
    """Run s10_memory_pressure."""
    if harness is None:
        harness = DiagnosticHarness(
            scenario_name=SCENARIO_NAME,
            output_dir=output_dir,
            modality=MODALITY,
            slice_count=SLICE_COUNT,
            run_count=REPEAT_COUNT,
        )

    with harness:
        harness.make_controller()

        harness.snapshot_memory()  # M01 baseline

        for i in range(1, REPEAT_COUNT + 1):
            series_number = str(i)
            harness.step(f"open_{i}")

            # Progressive load — 8 batches of ~50 slices each
            BATCH_SIZE = SLICE_COUNT // 8
            for b in range(1, 9):
                harness.emit_progress(
                    series_number,
                    min(b * BATCH_SIZE, SLICE_COUNT),
                    SLICE_COUNT,
                )

            harness.emit_progress(series_number, SLICE_COUNT, SLICE_COUNT)
            harness.emit_download_complete(series_number)

            harness.snapshot_memory()  # capture intermediate RSS

            # Simulate series close (loader released, tab closed)
            harness.step(f"close_{i}")
            harness._log.append(ET_LOADER_RELEASED, series_number=series_number)
            harness._log.append(ET_WIDGET_DESTROYED, series_number=series_number)
            harness._log.append(ET_TAB_CLOSED, series_number=series_number)

        harness.snapshot_memory()  # M03 final RSS

        return harness.finish()
