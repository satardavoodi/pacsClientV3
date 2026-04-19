# Tools Folder

This directory is organized by purpose:

- `diagnostics/` — one-off DB, printing, and patient/series investigation scripts plus their saved outputs/notebooks.
- `slicer/` — Advanced 3D Slicer runtime assembly, download, verification, and direct-load test helpers.
- `performance/` — performance instrumentation, monitoring, test runners, and log analysis.
- `vtk/` — VTK scratch/merge/reference files and comparison patches.
- `dev/` — temporary developer utilities and repo-maintenance helpers.
- `git/` — GitHub push/connectivity scripts and local network config templates.

Notable current tool:

- `tools/performance/clearcanvas_aipacs_kpi_harness.py` — shared KPI harness for AI-PACS vs ClearCanvas comparisons, including headless FAST runs, external-process monitoring, log parsing, and report generation.
- `tools/performance/clearcanvas_aipacs_kpi_harness.py summarize-blocks` — groups any KPI payload into Block 1 / Block 2 / Block 3 ownership using `tests/performance/block_kpi_model.json`.

- `tools/performance/run_clearcanvas_manual_benchmark.ps1` â€” helper wrapper for ClearCanvas manual benchmark runs, process capture, and execution-pack output.

Benchmark doc entrypoint:

- `docs/analysis/CLEARCANVAS_BENCHMARK_EXECUTION.md`

If you add a new script, place it in the closest matching subfolder instead of the `tools/` root.

For full governance rules, lifecycle expectations, and the future improvement roadmap, see:

- `docs/development/tools-governance-and-roadmap.md`
