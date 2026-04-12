"""
s09_mri_vs_ct.py
================
Comparative scenario: run s01_small_mri + s03_large_ct, emit comparison.json.

Purpose
-------
Identifies CT-specific regressions by diffing KPIs between the MR baseline
(25 slices, healthy) and the large CT scenario (400 slices, H1 probe).

Significant differences (ratio > 2.0 or delta > 100 ms) are marked in the
comparison output and used as evidence for H1 hypothesis scoring.

Key comparison KPIs
-------------------
- T05_metadata_refresh_max_ms   (H1 primary indicator; MR baseline vs CT)
- T07_grow_max_ms               (grow stall under large slice count)
- M04_rss_delta_mb              (memory growth per series)
- C04_metadata_refresh_calls    (how often refresh was triggered)

Artifacts written
-----------------
- ``<run_dir>/comparison.json``    — KpiDiffRow[] with ratios and deltas
- ``<run_dir>/mri_kpis.json``      — MR run KPIs snapshot
- ``<run_dir>/ct_kpis.json``       — CT run KPIs snapshot
- ``<run_dir>/summary.txt``        — Human-readable diff table

Usage
-----
    python tests/diagnostics/run_diagnostic.py --scenario s09_mri_vs_ct
    cat tests/diagnostics/runs/s09_mri_vs_ct/comparison.json
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Optional

from tests.diagnostics.harness import DiagnosticHarness, HarnessResult
from tests.diagnostics.comparison import compare_runs, format_diff
from tests.diagnostics.scenarios import s01_small_mri, s03_large_ct


SCENARIO_NAME = "s09_mri_vs_ct"


def run(
    harness: Optional[DiagnosticHarness] = None,
    output_dir: Optional[Path] = None,
) -> HarnessResult:
    """Run s09_mri_vs_ct comparison.

    Runs s01 and s03 as sub-scenarios, then writes comparison artifacts to
    the top-level output_dir.  The returned HarnessResult is from the CT run
    (the higher-risk scenario); MR KPIs are stored as an extra artifact.
    """
    # Determine output directory
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="diag_s09_mri_vs_ct_"))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Run s01 (MR baseline) ──────────────────────────────────────────────
    mr_run_dir = output_dir / "mr_run"
    mr_run_dir.mkdir(exist_ok=True)
    mr_harness = DiagnosticHarness(
        scenario_name="s01_small_mri",
        output_dir=mr_run_dir,
        modality="MR",
        slice_count=25,
        run_count=1,
    )
    mr_result = s01_small_mri.run(harness=mr_harness)

    # ── Run s03 (CT primary) ──────────────────────────────────────────────
    ct_run_dir = output_dir / "ct_run"
    ct_run_dir.mkdir(exist_ok=True)
    ct_harness = DiagnosticHarness(
        scenario_name="s03_large_ct",
        output_dir=ct_run_dir,
        modality="CT",
        slice_count=400,
        run_count=1,
    )
    ct_result = s03_large_ct.run(harness=ct_harness)

    # ── Compare KPIs ─────────────────────────────────────────────────────
    comparison = compare_runs(
        mr_kpis=mr_result.kpis,
        ct_kpis=ct_result.kpis,
    )

    # Write comparison artifacts
    comparison.write_json(output_dir / "comparison.json")

    (output_dir / "mri_kpis.json").write_text(
        json.dumps(mr_result.kpis, indent=2, default=str)
    )
    (output_dir / "ct_kpis.json").write_text(
        json.dumps(ct_result.kpis, indent=2, default=str)
    )

    diff_text = format_diff(comparison)
    (output_dir / "summary.txt").write_text(diff_text, encoding="utf-8")

    print(diff_text)

    # Return the CT result (higher risk scenario) as the primary result
    return ct_result
