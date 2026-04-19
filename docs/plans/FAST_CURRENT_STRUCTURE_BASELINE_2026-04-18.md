# FAST Current Structure Baseline — 2026-04-18

## Purpose

This document records the **current verified FAST structure** before any further precision changes.

It exists to support four rules:

1. preserve the current good structure
2. preserve the current KPI gains
3. avoid adding architectural complexity without measurable value
4. document future changes as explicit deltas against a known baseline

This is a **baseline document**, not a proposal.

## Verified current shape

The current FAST control path is already a **lightweight layered structure**, not a large scheduler framework.

### Current roles

- `modules/viewer/fast/system_load_controller.py`
  - current **policy brain**
  - classifies work
  - computes protected-mode policy
  - tracks admission/defer/drop counters
  - exposes per-block debug/accounting snapshots

- `modules/viewer/fast/ui_throttle.py`
  - current **shared FAST facade**
  - bridges load policy, heavy-download state, active orchestrator, and telemetry
  - exposes cadence/admission decisions to the rest of the system
  - acts as the practical cross-block coordination seam

- `modules/viewer/pipeline/orchestrator.py`
  - current **lifecycle/event spine**
  - holds structured state and event history for viewer-side orchestration

- `modules/viewer/fast/block_telemetry.py`
  - current **block-observability layer**
  - merges orchestrator signals, controller accounting, and live KPI snapshots

- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`
  - current **Block 1 normalization and wiring owner**
  - centralizes DM → widget signal wiring
  - normalizes progress/completion flow
  - already calmer than the older fan-out model

## Current block ownership

### Block 1 — data services

Current practical owners:

- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`
- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`
- `modules/download_manager/**`
- `database/**`
- `modules/network/**`

Current role:

- produce download/progress/persistence state
- normalize and project state to viewer-facing consumers
- avoid unnecessary UI churn

Current assessment:

- mostly healthy as a producer plane
- should stay stable unless logs prove it is disturbing the visible path

### Block 2 — viewer hot path

Current practical owners:

- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- `modules/viewer/fast/qt_slice_viewer.py`
- `modules/viewer/fast/decode_service.py`

Current role:

- decode, filter, render, and present the visible image
- keep interaction path direct and protected

Current assessment:

- still expensive when exact foreground decode is exposed
- should be optimized only after avoidable Block 3 pressure is reduced

### Block 3 — cache / scroll / orchestration

Current practical owners:

- `modules/viewer/fast/system_load_controller.py`
- `modules/viewer/fast/ui_throttle.py`
- `modules/viewer/fast/lightweight_2d_pipeline.py` (`set_slice_index`, prefetch path)
- viewer controller progressive/load/warmup mixins

Current role:

- decide what non-interactive work is allowed to run
- protect the visible path from unnecessary work
- manage cache/prefetch/progressive coordination behavior

Current assessment:

- primary remaining bottleneck under heavy overlap
- already has the correct lightweight ownership direction
- should be tightened, not broadly redesigned

## Architectural conclusion

The current repo **already partially realizes** the intended hierarchy:

- block-local owners exist
- a higher-level policy/facade seam already exists
- telemetry/observability already exists
- the current gap is mainly **policy refinement and measured tightening**, not missing architecture

So the safest interpretation is:

- do **not** introduce a new heavyweight orchestrator layer yet
- do **not** rewrite current owners into a new framework yet
- continue using the current controller + facade + orchestrator + telemetry shape
- refine only where KPIs justify it

## What is intentionally unchanged in this baseline

This baseline preserves these rules:

- `QtViewerBridge.set_slice()` remains direct and protected
- FAST and Advanced paths remain separate
- Block 1 remains a calm producer plane, not a broad rewrite target
- Block 3 remains the first optimization plane for the next heavy-stack pass
- future extraction into new files/modules must happen only after a seam is behaviorally proven

## Current KPI truth supporting this baseline

Latest overlap artifact interpretation:

- `first_image_visible_ms = 196.76`
- `set_slice_present_p95_ms = 155.48`
- `decode_p95_ms = 208.4`
- `frame_render_p95_ms = 187.49`
- `cache_hit_ratio_pct = 52.6`
- `cpu_p95_pct = 139.18`

Meaning:

- startup is no longer the dominant current problem
- heavy-stack overlap remains the active bottleneck
- Block 3 remains the safest next place to work

## Validation performed on this baseline

Focused structure-preservation tests run on 2026-04-18:

### Structure/controller/projection slice

- `tests/viewer/test_system_load_controller.py`
- `tests/viewer/test_cp1_control_plane_governance.py`
- `tests/fast/test_fast_thumbnail_vs_download_separation.py`
- `tests/fast/test_thumbnail_progress_state_binding.py`
- `tests/ui_services/test_lifecycle_hygiene.py`

Result:

- **84 passed**
- **3 warnings**
- runtime: **58.92s**

### Progressive/lifecycle slice

- `tests/viewer/test_fast_viewer_pipeline.py`
- `tests/viewer/test_b43_progressive_lifecycle_state.py`
- `tests/viewer/test_dragdrop_progressive.py`

Result:

- **150 passed**
- **3 warnings**
- runtime: **33.87s**

### Combined baseline proof

- **234 focused tests passed**
- no structure regression found in the validated FAST control/lifecycle slice

## Baseline preservation location

Frozen pre-change documentation snapshot:

- `docs/archive/performance-history/2026-04-18_pre_precision_block_plan_baseline/`

This snapshot is the reference point for any future delta documentation.
