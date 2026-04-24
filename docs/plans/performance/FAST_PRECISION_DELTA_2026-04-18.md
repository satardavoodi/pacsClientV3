# FAST Precision Delta — 2026-04-18

## Purpose

This document records the **actual delta introduced during the current precision-preservation pass**.

It is intentionally narrow.

The goal of this pass was **not** to change runtime behavior yet.
The goal was to:

1. preserve documentation before further edits
2. verify the current structure with focused tests
3. write down the current structure clearly enough that later changes can be judged precisely

## Actual delta in this pass

### 1. Documentation baseline was frozen

A preserved snapshot of the current planning/status corpus was created at:

- `docs/archive/performance-history/2026-04-18_pre_precision_block_plan_baseline/`

Snapshot contents:

- `FAST_VIEW_PERFORMANCE_EXECUTION_PLAN.before_precision.md`
- `FAST_BLOCK_PERFORMANCE_ARCHITECTURE.before_precision.md`
- `PERFORMANCE_STATUS.before_precision.md`
- snapshot `README.md`

Why this matters:

- future edits can now be compared against a real frozen baseline
- current KPI/state language is preserved
- the next pass can document deltas instead of silently rewriting history

### 2. Current structure was explicitly documented

A current-state baseline document was added:

- `docs/plans/analysis/FAST_CURRENT_STRUCTURE_BASELINE_2026-04-18.md`

What it captures:

- current role of `SystemLoadController`
- current role of `ui_throttle`
- current role of `PipelineOrchestrator`
- current role of `block_telemetry`
- current Block 1 / Block 2 / Block 3 ownership
- explicit conclusion that the current repo already has a lightweight layered coordination shape

Why this matters:

- prevents unnecessary framework expansion
- makes later proposals answer to the current real structure
- keeps complexity growth honest

### 3. Focused structural validation was completed

Two focused validation slices were run.

#### Controller / projection / lifecycle-hygiene slice

Executed tests:

- `tests/viewer/test_system_load_controller.py`
- `tests/viewer/test_cp1_control_plane_governance.py`
- `tests/fast/test_fast_thumbnail_vs_download_separation.py`
- `tests/fast/test_thumbnail_progress_state_binding.py`
- `tests/ui_services/test_lifecycle_hygiene.py`

Result:

- **84 passed**
- **3 warnings**
- **58.92s**

#### Progressive lifecycle slice

Executed tests:

- `tests/viewer/test_fast_viewer_pipeline.py`
- `tests/viewer/test_b43_progressive_lifecycle_state.py`
- `tests/viewer/test_dragdrop_progressive.py`

Result:

- **150 passed**
- **3 warnings**
- **33.87s**

Combined result:

- **234 focused tests passed**

Why this matters:

- the current controller/facade/lifecycle structure is not just a theory
- the preserved baseline is test-backed
- future changes can now be evaluated against a validated starting point

## What did NOT change in this pass

This pass intentionally did **not** introduce:

- new runtime scheduling code
- new orchestrator layers
- new cache/prefetch logic
- new UI throttling logic
- new download-manager behavior
- new viewer hot-path behavior

In other words:

- **no runtime architecture expansion was performed here**
- this was a preservation + verification + documentation pass

## Interpretation of the delta

This pass confirms three important conclusions:

1. the current system already contains the needed lightweight coordination seam
2. the next work should refine that seam, not replace it
3. Block 3 remains the safest next implementation target, but only after respecting the preserved baseline

## Practical rule for the next pass

Any next implementation change should now state all of the following explicitly:

1. which block is changing
2. which current owner file is being tightened
3. which part of the baseline is intentionally unchanged
4. which KPI is expected to move
5. how added complexity is being avoided

## Current status after this delta

- documentation baseline preserved
- current structure baseline written
- focused structure/lifecycle tests green
- repo is ready for precise, minimal, KPI-justified follow-up work
