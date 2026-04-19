# Analysis Docs Index

Start here when the task involves ClearCanvas comparison, KPI benchmarking, or FAST workstation architecture review.

---

## ClearCanvas Benchmark Path

### 1. Execution and runbook

- `CLEARCANVAS_BENCHMARK_EXECUTION.md`
  - build/run status for ClearCanvas
  - benchmark phases
  - step mapping
  - result folder layout
  - how to extract ClearCanvas KPIs from test files
  - exact next run procedure

### 2. Benchmark scorecard and plan correction

- `../plans/analysis/CLEARCANVAS_KPI_SCORECARD_AND_PLAN_UPDATE.md`
  - what is structurally wrong in AI-PACS
  - which KPIs are common vs AI-PACS-only
  - ClearCanvas-inspired plan correction priorities

### 3. Full review and benchmark rationale

- `../plans/analysis/CLEARCANVAS_FULL_REVIEW_AND_KPI_BENCHMARK_PLAN.md`
  - broader synthesis of docs, code, and benchmark strategy

---

## ClearCanvas Architecture Review Path

- `CLEARCANVAS_WORKSTATION_COMPARISON.md`
- `CLEARCANVAS_DIVERGENCE_MATRIX.md`
- `CLEARCANVAS_KPI_MAPPING.md`
- `FAST_TASK_CONCURRENCY_AND_CLEARCANVAS_COMPARISON.md`
- `ORCHESTRATION_ROOT_CAUSES.md`

---

## Benchmark Files Outside `docs/analysis/`

### Harness and runners

- `tools/performance/clearcanvas_aipacs_kpi_harness.py`
- `tools/performance/run_clearcanvas_manual_benchmark.ps1`

### Scenario and step model

- `tests/performance/clearcanvas_aipacs_scenarios.json`
- `tests/performance/clearcanvas_aipacs_benchmark_model.json`

### Harness tests

- `tests/performance/test_clearcanvas_aipacs_kpi_harness.py`

---

## Fast Start For Another AI Agent

If the task is "run or continue the ClearCanvas benchmark work", use this order:

1. Read `CLEARCANVAS_BENCHMARK_EXECUTION.md`.
2. Check whether ClearCanvas is buildable in the current environment.
3. Use `emit-execution-pack` from the KPI harness.
4. Produce:
   - `aipacs_common.json`
   - `clearcanvas_process_metrics.json`
   - `manual_step_results.csv`
   - `clearcanvas_common.json` via `summarize-manual-results`
   - `comparison.md`
5. Only after those files exist should you claim a real side-by-side run happened.

---

## Truthfulness Rule

Do not say "ClearCanvas comparison completed" unless a real ClearCanvas runtime run has happened and produced result files. Preparing the workflow is not the same thing as completing the benchmark.
