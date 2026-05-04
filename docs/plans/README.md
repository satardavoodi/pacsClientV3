# Plans Index

This folder is the canonical home for active planning documents, recovery plans, migration plans, and roadmaps.

## Rule

- Put new plan documents under `docs/plans/`
- Prefer a topical subfolder when it helps avoid name collisions or keeps context clear
- Keep architecture/source-of-truth docs in their normal folders; only planning-oriented documents belong here

## Current layout

- `plan.md` - master planning ledger
- `analysis/` - evaluation notes, block reviews, baselines, and ClearCanvas handoff planning
- `performance/FAST_STORM_AND_PERFORMANCE_PLAN_vNEXT.md` - canonical next-step FAST storm/performance plan
- `performance/FAST_2D_CELL_SEPARATION_PLAN.md` - **✅ COMPLETED (Step 1 of performance surgery)** VTK-free FAST mode viewer cells
- `performance/` - performance roadmaps, KPI playbooks, and execution plans
- `VIEWER_CELL_SEPARATION_SAFETY_PLAN.md` - multi-phase surgery safety plan (P1 done, P2–P7 pending)
- `development/` - development/refactoring plans
- `implementation/` - implementation/refactor plans
- `pipelines/` - pipeline planning docs
- `stability/` - recovery and stabilization plans
- `viewer/` - viewer-specific migration plans

Build-specific planning no longer lives in `docs/plans/`; use `builder/docs/NUITKA_BUILD_PLAN.md` for the staged Nuitka pipeline.

## Notes

- Some non-plan architecture/reference docs intentionally remain outside this folder.
- When moving or adding plans, update any docs that link to the old path so `docs/plans/` stays canonical.

## Recommended starting points

- Read `plan.md` for the broader planning ledger and historical context.
- Read `performance/FAST_VIEW_PERFORMANCE_EXECUTION_PLAN.md` for the current detailed execution sequence and KPI contract.
- Read `performance/FAST_STORM_AND_PERFORMANCE_PLAN_vNEXT.md` for the current canonical next-step performance/orchestration plan.
