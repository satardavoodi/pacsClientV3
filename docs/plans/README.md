# Plans Index

This folder is the canonical home for active planning documents, recovery plans, migration plans, and roadmaps.

## Rule

- Put new plan documents under `docs/plans/`
- Prefer a topical subfolder when it helps avoid name collisions or keeps context clear
- Keep architecture/source-of-truth docs in their normal folders; only planning-oriented documents belong here

## Current layout

- `plan.md` - master planning ledger
- `FAST_VIEW_PERFORMANCE_EXECUTION_PLAN.md` - precise execution plan for the next FAST-view performance pass, based on live overlap evidence and ClearCanvas-guided ownership discipline
- `performance/FAST_STORM_AND_PERFORMANCE_PLAN_vNEXT.md` - canonical next-step FAST storm/performance plan
- `analysis/` - plan documents tied to analysis work
- `clear-canvas/` - gathered ClearCanvas plan copies
- `development/` - development/refactoring plans
- `implementation/` - implementation/refactor plans
- `performance/` - performance roadmaps and plan docs
- `pipelines/` - pipeline planning docs
- `stability/` - recovery and stabilization plans
- `viewer/` - viewer-specific migration plans

## Notes

- Some non-plan architecture/reference docs intentionally remain outside this folder.
- When moving or adding plans, update any docs that link to the old path so `docs/plans/` stays canonical.

## Recommended starting points

- Read `plan.md` for the broader planning ledger and historical context.
- Read `FAST_VIEW_PERFORMANCE_EXECUTION_PLAN.md` for the current detailed execution sequence and KPI contract.
- Read `performance/FAST_STORM_AND_PERFORMANCE_PLAN_vNEXT.md` for the current canonical next-step performance/orchestration plan.
