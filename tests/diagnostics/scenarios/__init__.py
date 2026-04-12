"""
tests/diagnostics/scenarios/
==============================
Synthetic diagnostic scenarios for the FAST viewer.

Each scenario is a function ``run(harness, **kwargs) -> HarnessResult``
that drives a DiagnosticHarness through a specific sequence of events.

Scenario index
--------------
s01_small_mri      — 25-slice MRI baseline (MR KPI baseline for comparison)
s02_medium_ct      — 120-slice CT intermediate
s03_large_ct       — 400-slice CT primary crash scenario (H1 probe)
s04_early_teardown — Widget destroyed while download in progress (H2 probe)
s05_scroll_completion — Scroll during final grow window (H6 layer-miss probe)
s06_tab_switch     — Series switched mid-download (H3 generation mismatch)
s07_series_interrupt — DM interrupt during progressive grow
s08_repeated_open  — Same series opened/closed 3× (H4 done-guard collision)
s09_mri_vs_ct      — Runs s01 + s03 and emits comparison.json
s10_memory_pressure — Five consecutive large-CT opens (M02 peak RSS)
s11_post_fix_repeated_open — H4 post-fix health check (real methods; expects C01==3, no FS-18/FS-02)
"""

__all__ = [
    "s01_small_mri",
    "s02_medium_ct",
    "s03_large_ct",
    "s04_early_teardown",
    "s05_scroll_completion",
    "s06_tab_switch",
    "s07_series_interrupt",
    "s08_repeated_open",
    "s09_mri_vs_ct",
    "s10_memory_pressure",
    "s11_post_fix_repeated_open",
]
