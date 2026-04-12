"""
s08_repeated_open.py
====================
H4 probe: same series opened and closed 3× (done-guard collision).

Purpose
-------
H4 hypothesis: "Done-guard collision on re-open — progressive display never
activates on the second open".

When a series is opened, downloaded, and the viewer closes/re-opens the same
series, the _progressive_display_done set should NOT contain the series key
from the previous open.  If it does, the done-guard blocks progressive mode
from starting, and the viewer shows a frozen image forever.

This scenario runs the full open/close cycle 3× (minimum evidence for H4
requires FS-18 in s08 ≥ 2/3 runs) to gather statistical evidence.

Timeline per cycle
------------------
1. Progress signals received → progressive start.
2. Download completes → done-guard set.
3. Series "closed" (ET_TAB_CLOSED) — done-guard should be cleared.
4. SAME series re-opened → progress signals received again.
5. Check: _start_progressive_display IS called again (C01 increments).

Failure signatures probed
-------------------------
- FS-18: DONE_GUARD_FALSE_POSITIVE (done-guard set but no progressive viewer)
- FS-02: DONE_NEVER_RESET (done-guard key survives series close)
- FS-09: PROGRESSIVE_NEVER_STARTED (second open blocked by stale done-guard)

Expected outcomes when H4 present
-----------------------------------
- FS-18 found in ≥ 2 of 3 cycles
- HypothesisResult("H4").verdict in ("CONFIRMED", "LIKELY")
- C01_progressive_start_calls < 3  (cycles 2 and/or 3 never got a start)

Expected on healthy system
--------------------------
- C01_progressive_start_calls == 3
- No FS-18
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from tests.diagnostics.harness import DiagnosticHarness, HarnessResult
from tests.diagnostics.event_log import (
    ET_DONE_GUARD_SET,
    ET_TAB_CLOSED,
    ET_TAB_OPENED,
)


SCENARIO_NAME = "s08_repeated_open"
MODALITY = "CT"
SLICE_COUNT = 120
SERIES_NUMBER = "1"
REPEAT_COUNT = 3


def run(
    harness: Optional[DiagnosticHarness] = None,
    output_dir: Optional[Path] = None,
    run_count: int = 1,
) -> HarnessResult:
    """Run s08_repeated_open.

    Parameters
    ----------
    run_count : int
        Which of the N repetitions this is.  HypothesisEngine uses run_count
        to enforce "≥ 2/3 runs must show FS-18" for H4 confirmation.
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

            # Done-guard set by framework after completion
            harness._log.append(
                ET_DONE_GUARD_SET,
                series_number=SERIES_NUMBER,
                cycle=cycle,
            )

            # Close
            harness.step(f"{label}_close")
            harness._log.append(
                ET_TAB_CLOSED,
                series_number=SERIES_NUMBER,
                cycle=cycle,
            )
            # Note: a HEALTHY framework clears the done-guard here.
            # If the done-guard is NOT cleared, the next cycle's emit_progress
            # will hit the block path and C01 will not increment.

        return harness.finish()
