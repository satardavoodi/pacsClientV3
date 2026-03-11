# Cross-PC Improvement Workflow (Standard)

Last updated: 2026-02-25

## Machine roles
- **PC A**: Developer machine (all code changes originate here).
- **PC B (and others)**: Validation machines (pull from GitHub and evaluate impact).

## Required cycle
1. Implement the change on **PC A**.
2. Run targeted local validation on **PC A** (same feature path, same log signals).
3. Push the updated code from **PC A** to GitHub.
4. Pull the exact commit on **PC B**.
5. Re-run the same scenario on **PC B**.
6. Compare results/logs between **PC A** and **PC B**.
7. If issue remains, iterate from step 1.

## Validation checklist per cycle
- Confirm commit hash is identical on PC A and PC B.
- Confirm runtime mode under test (source run and/or build run).
- Capture logs for the same study/workflow window on both PCs.
- Compare:
  - viewer timings (e.g., `set_slice_total`, `slice_apply`)
  - load timings (e.g., `itk_filter_chain`, `load_single_series_total`)
  - download/DB contention (e.g., `request_total`, batch DB stages)
  - pipeline mode markers (Plan A/Plan B state transitions)

## Notes
- Do not conclude from one machine only.
- Treat this process as mandatory for performance and stability improvements.