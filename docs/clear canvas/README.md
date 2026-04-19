# ClearCanvas Document Bundle

**Date gathered:** 2026-04-15  
**Source workspace:** `c:\AI-Pacs codes\aipacs-pydicom2d`

This folder gathers the ClearCanvas-related architecture, benchmark, and convergence documents into one place.

## Included documents

1. `CLEARCANVAS_WORKSTATION_COMPARISON.md`  
   Ground-truth comparison between AI-PACS FAST and the external ClearCanvas reference checkout.

2. `CLEARCANVAS_DIVERGENCE_MATRIX.md`  
   Precise divergence map with REQUIRED / ACCIDENTAL / HARMFUL classification.

3. `CLEARCANVAS_KPI_MAPPING.md`  
   Maps the architecture differences to measurable FAST KPIs.

4. `ORCHESTRATION_ROOT_CAUSES.md`  
   Identifies the primary mixed-load orchestration bottlenecks.

5. `FAST_ORCHESTRATION_TARGET.md`  
   Defines the desired simplified FAST orchestration architecture.

6. `../plans/clear-canvas/FAST_ORCHESTRATION_REFACTOR_PLAN.md`  
   Step-by-step implementation/refactor sequence.

7. `CLEARCANVAS_BENCHMARK_EXECUTION.md`  
   Execution runbook, result folder contract, file outputs, and manual-result normalization flow.

8. `../plans/clear-canvas/CLEARCANVAS_KPI_SCORECARD_AND_PLAN_UPDATE.md`  
   Scorecard-oriented summary of KPI comparison logic and plan-correction priorities.

9. `../plans/clear-canvas/CLEARCANVAS_FULL_REVIEW_AND_KPI_BENCHMARK_PLAN.md`  
   Broader synthesis of the review plus benchmark strategy and interpretation rules.

## Original source locations

- `docs/analysis/CLEARCANVAS_WORKSTATION_COMPARISON.md`
- `docs/analysis/CLEARCANVAS_DIVERGENCE_MATRIX.md`
- `docs/analysis/CLEARCANVAS_KPI_MAPPING.md`
- `docs/analysis/ORCHESTRATION_ROOT_CAUSES.md`
- `docs/architecture/FAST_ORCHESTRATION_TARGET.md`
- `docs/plans/implementation/FAST_ORCHESTRATION_REFACTOR_PLAN.md`
- `docs/analysis/CLEARCANVAS_BENCHMARK_EXECUTION.md`
- `docs/plans/analysis/CLEARCANVAS_KPI_SCORECARD_AND_PLAN_UPDATE.md`
- `docs/plans/analysis/CLEARCANVAS_FULL_REVIEW_AND_KPI_BENCHMARK_PLAN.md`

## Note

This folder remains a gathered reference bundle. The planning-oriented documents listed above now live canonically under `docs/plans/`, while the non-plan architecture/reference docs remain in their source folders.

## Suggested reading order

If the task is benchmark execution or continuation:

1. `CLEARCANVAS_BENCHMARK_EXECUTION.md`
2. `../plans/clear-canvas/CLEARCANVAS_KPI_SCORECARD_AND_PLAN_UPDATE.md`
3. `../plans/clear-canvas/CLEARCANVAS_FULL_REVIEW_AND_KPI_BENCHMARK_PLAN.md`
4. `CLEARCANVAS_WORKSTATION_COMPARISON.md`

If the task is architecture simplification/refactor planning:

1. `CLEARCANVAS_WORKSTATION_COMPARISON.md`
2. `CLEARCANVAS_DIVERGENCE_MATRIX.md`
3. `CLEARCANVAS_KPI_MAPPING.md`
4. `ORCHESTRATION_ROOT_CAUSES.md`
5. `FAST_ORCHESTRATION_TARGET.md`
6. `../plans/clear-canvas/FAST_ORCHESTRATION_REFACTOR_PLAN.md`
