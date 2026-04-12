"""
s06_tab_switch.py
=================
H3 probe: series switched mid-download (generation mismatch).

Purpose
-------
Simulates a user opening series A, then immediately dragging series B onto
the same viewer while series A is still being downloaded.  The critical risk
is that lazy-decode signals for series A (old generation) arrive AFTER series
B has been bound (new generation), causing wrong-series pixels to be displayed
silently.

Timeline simulated
------------------
1. Series A begins loading (first batch).
2. Mid-way user switches to series B (SERIES_SWITCH_BEGIN for B).
3. Backend binds series B (BACKEND_BIND, generation incremented).
4. Late DECODE_SLICE_READY signals arrive for series A (old generation).
5. These should be ignored; FS-15 fires if generation is NOT checked.

Failure signatures probed
-------------------------
- FS-15: GENERATION_MISMATCH (old-generation decode arrived after bind)
- FS-03: (indirectly) stale retry after series B bound unexpected context
- FS-01: INFLIGHT_STUCK (inflight guard not cleared on switch)

Expected outcomes
-----------------
- FS-15 is raised (generation mismatch exists — known architecture risk)
- H3 hypothesis verdict in ("CONFIRMED", "LIKELY") if generation not guarded
- C07_series_switch_calls == 1
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from tests.diagnostics.harness import DiagnosticHarness, HarnessResult
from tests.diagnostics.event_log import (
    ET_SERIES_SWITCH_BEGIN,
    ET_SERIES_SWITCH_DONE,
    ET_BACKEND_BIND,
    ET_GENERATION_INCR,
    ET_DECODE_SLICE_READY,
)


SCENARIO_NAME = "s06_tab_switch"
MODALITY = "CT"
SLICE_COUNT_A = 120
SLICE_COUNT_B = 80
SERIES_A = "1"
SERIES_B = "2"


def run(
    harness: Optional[DiagnosticHarness] = None,
    output_dir: Optional[Path] = None,
) -> HarnessResult:
    """Run s06_tab_switch."""
    if harness is None:
        harness = DiagnosticHarness(
            scenario_name=SCENARIO_NAME,
            output_dir=output_dir,
            modality=MODALITY,
            slice_count=SLICE_COUNT_A,
            run_count=1,
        )

    with harness:
        harness.make_controller()

        # Phase 1: series A first batch
        harness.step("series_A_start")
        harness.emit_progress(SERIES_A, 10, SLICE_COUNT_A)
        harness.emit_progress(SERIES_A, 40, SLICE_COUNT_A)

        # Phase 2: user switches to series B mid-download
        harness.step("switch_to_series_B")
        harness._log.append(
            ET_SERIES_SWITCH_BEGIN,
            from_series=SERIES_A,
            to_series=SERIES_B,
        )
        # Series B binds its backend — generation incremented
        harness._log.append(
            ET_GENERATION_INCR,
            series_number=SERIES_B,
            new_generation=2,
        )
        harness._log.append(
            ET_BACKEND_BIND,
            series_number=SERIES_B,
            generation=2,
        )
        harness._log.append(
            ET_SERIES_SWITCH_DONE,
            from_series=SERIES_A,
            to_series=SERIES_B,
        )

        # Phase 3: series B progress (new active series)
        harness.step("series_B_progress")
        harness.emit_progress(SERIES_B, 20, SLICE_COUNT_B)
        harness.emit_progress(SERIES_B, 60, SLICE_COUNT_B)

        # Phase 4: late decode signals for SERIES_A (old generation=1)
        # These should be ignored; the generation mismatch detector looks for
        # DECODE_SLICE_READY with a generation that no longer matches the bound
        # backend.
        harness.step("late_series_A_decodes")
        for slice_idx in range(41, 55):
            harness._log.append(
                ET_DECODE_SLICE_READY,
                series_number=SERIES_A,
                slice_index=slice_idx,
                generation=1,          # old generation
            )

        # Phase 5: series B completes normally
        harness.step("series_B_complete")
        harness.emit_progress(SERIES_B, SLICE_COUNT_B, SLICE_COUNT_B)
        harness.emit_download_complete(SERIES_B)

        return harness.finish()
