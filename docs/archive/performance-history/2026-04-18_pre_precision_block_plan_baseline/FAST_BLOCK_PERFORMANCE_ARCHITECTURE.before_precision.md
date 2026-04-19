# FAST Block Performance Architecture

## Purpose

This document turns the FAST performance work into a 3-block execution model so the code, workers, scheduling, and KPIs can be reasoned about as stable functional units.

It does **not** replace `docs/plans/FAST_VIEW_PERFORMANCE_EXECUTION_PLAN.md`.
It sits on top of it and answers a different question:

- not only **what phase comes next**
- but also **which block owns the problem, which worker should run it, and which KPI proves it**

## The 3 blocks

### Block 1 — Data services

This block owns everything upstream of the visible FAST image.

It includes:

- download manager and download workers
- right-side panel / thumbnail projection contract
- thumbnail update behavior and state transitions
- download-to-database connection
- DICOM persistence on disk
- DICOM header extraction and persistence
- database records derived from DICOM content
- deferred reception / external metadata / low-priority auxiliary information

### Block 2 — Viewer hot path

This block owns the visible FAST viewer pipeline.

It includes:

- DICOM decode
- filter application
- render-frame preparation
- final image presentation to the viewer

In FAST mode, this is the critical latency path.

### Block 3 — Cache, scroll, and orchestration

This block owns the logic between Block 1 and Block 2.

It includes:

- scroll policy
- cache policy
- prefetch direction and radius selection
- progressive lifecycle ownership
- redraw ordering
- admission/defer/drop decisions for non-interactive work
- work scheduling under the orchestrator

This block is the control plane.

## Required relationship between blocks

The runtime contract should be:

- Block 1 produces data, events, manifests, and persistence state.
- Block 2 consumes the currently needed visible image data.
- Block 3 decides **when** Block 1 may disturb Block 2 and **how much** Block 2 may ask Block 1/its caches for ahead-of-time work.

In short:

$$
\text{Block 1} \xrightarrow{data/events} \text{Block 3} \xrightarrow{scheduling/admission} \text{Block 2}
$$

and for cache/prefetch/scroll feedback:

$$
\text{Block 2} \xrightarrow{view state / slice demand} \text{Block 3} \xrightarrow{prefetch/storage requests} \text{Block 1}
$$

## Current code mapping

### Block 1 current owners

Primary files:

- `modules/download_manager/**`
- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`
- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`
- `database/core.py`
- `database/manager.py`
- `modules/network/**`
- `modules/zeta_boost/**`

Current worker/process model:

- download subprocesses / worker wrappers
- DB + storage work in background threads where already implemented
- thumbnail state mostly on main thread
- warmup subprocess for post-download preparation

### Block 2 current owners

Primary files:

- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- `modules/viewer/fast/pydicom_2d_backend.py`
- `modules/viewer/fast/decode_service.py`
- `modules/viewer/fast/qt_slice_viewer.py`

Current worker/process model:

- direct interaction path on main/UI thread
- background prefetch threads
- decode subprocess for selected background work
- disk pixel cache as persistent L2

### Block 3 current owners

Primary files:

- `modules/viewer/fast/system_load_controller.py`
- `modules/viewer/fast/ui_throttle.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_warmup.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py`
- redraw/sync follow-up inside patient/viewer controller files

Current worker/process model:

- mostly main-thread coordination with timers
- policy probes in shared controller helpers
- no single admitted work queue yet

## Orchestrator contract

The orchestrator must become the owner of scheduling decisions across all 3 blocks.

### Current implementation step (2026-04-17)

The current FAST control-plane now has an explicit lightweight classification seam:

- `modules/viewer/fast/system_load_controller.py`
   - `BlockId`
   - `classify_work_class(...)`
   - per-block admission counters
   - `debug_snapshot(...)`
- `modules/viewer/fast/ui_throttle.py`
   - `classify_work(...)`
   - `get_load_debug_snapshot()`
   - `get_live_block_telemetry_snapshot()`
   - `emit_live_block_telemetry()`
- `modules/viewer/pipeline/orchestrator.py`
   - structured `snapshot()` output
   - recent event journal with block ownership on every transition
   - compact event summaries: `transition_seq`, `most_recent_event`, `event_counts_by_block`, `event_counts_by_name`
- `modules/viewer/fast/block_telemetry.py`
   - merged live per-block snapshot across orchestrator + admissions + perf metrics
   - recent-delta accounting per block
   - overlap-state history for real workstation exams
   - compact `[BLOCK_DIAG]` heartbeat payloads for live logs

This is intentionally **not** a heavy queue manager yet.  It gives us:

- one stable block label per admitted work class
- reproducible per-block counters for tests/KPIs
- a compact orchestrator event history for debugging patient-open and overlap runs
- low-cost summary fields that let tooling compare block/event churn without reparsing the full event journal
- one live-runtime heartbeat that shows which blocks are active together, which block just changed, and which KPI cluster is currently hot
- a safe path to move responsibilities between blocks without guessing which file currently owns them

### Live exam telemetry contract (2026-04-17)

For real workstation runs we now want a single merged snapshot instead of three partial debug views.

The live contract is:

- `PipelineOrchestrator.snapshot()` supplies lifecycle state + event ownership
- `SystemLoadController.debug_snapshot()` supplies admission/defer/drop accounting + UI protection probes
- `PerfMetrics.snapshot()` supplies interaction/render KPIs
- `LiveBlockTelemetry.snapshot()` merges those into:
   - `blocks[]` with per-block `live_kpis`
   - `overlap.active_blocks`
   - `overlap.overlap_state`
   - per-block recent deltas (`recent_event_count`, `recent_admission_delta`)
   - rolling history counts for overlap states during a live exam

The runtime heartbeat format is:

- log prefix: `[BLOCK_DIAG]`
- cadence: controlled by `AIPACS_BLOCK_DIAG_INTERVAL_MS` (default 2000ms)
- enabled by `AIPACS_BLOCK_DIAG_ENABLED=1`

This heartbeat is intentionally compact.  It is for production-style live exams where we need to answer:

- which blocks are overlapping right now
- which block is generating fresh churn right now
- whether the visible pain is mainly Block 2 cost, Block 1 pressure, or Block 3 control-plane churn

### What it must decide

- which block gets to run now
- which work is deferred
- which work is stale and must be dropped
- which work deserves a different worker/process boundary
- which work is allowed during protected interaction

### What it must not do

- it must not become a giant "do everything" runtime object
- it must not replace the direct present path in `QtViewerBridge.set_slice()`
- it must not force every task into a new subprocess just because CPU is high

### Operational rule

Before adding a new worker/process boundary, answer:

1. What contention is being removed?
2. Why is admission/defer/coalesce/drop not enough?
3. What coordination cost will the new worker add?

If those answers are weak, keep the work in the same process and improve scheduling instead.

## Worker/process guidance by block

### Block 1

Preferred model:

- keep network receive / long-running download work out of the UI thread
- keep persistence and heavier storage work backgrounded
- keep thumbnail rendering/projection lightweight and main-thread safe
- do **not** let thumbnail UI become an equal-priority worker peer to download correctness

### Block 2

Preferred model:

- direct visible present stays synchronous and top priority
- background decode isolation is allowed when it truly avoids GIL contention
- any non-visible decode/filter work must be subordinate to interaction
- Block 2 should receive the lightest possible inputs from Block 1

### Block 3

Preferred model:

- mostly control-plane logic and queues/timers
- minimal heavy compute of its own
- one admission front door for non-interactive work
- one lifecycle owner for terminal completion
- one redraw owner for post-present follow-up

## Folder strategy

This should be implemented incrementally, not as a giant move.

### Target logical structure

- `modules/viewer/fast/core/`
  - `event_normalizer.py`
  - `admission_controller.py`
  - `progressive_lifecycle.py`
  - `redraw_coordinator.py`
  - `cache_warm_scheduler.py`
- `modules/viewer/fast/render/`
  - viewer hot-path files
- `modules/viewer/fast/helpers/`
  - policy helpers, caches, decode helpers, stale guards

### Important rule

Logical ownership comes first.
Physical extraction into new files should only happen after the ownership seam is already proven in behavior and tests.

## KPI model by block

The new canonical machine-readable model is:

- `tests/performance/block_kpi_model.json`

The first anti-orphan job inventory for the two highest-risk user flows lives in:

- `docs/plans/FAST_PIPELINE_JOB_BLOCK_INVENTORY.md`
- `tests/performance/pipeline_job_block_model.json`

This gives every block:

- role and position
- preferred worker model
- KPI list
- goal per KPI
- whether the KPI is already instrumented or still planned

## Test redesign

The performance suite should no longer be only scenario-centric.
It should support three simultaneous views:

1. **scenario view** — what happened in the run?
2. **block view** — which block consumed the budget?
3. **ownership view** — which worker/scheduler path likely caused the issue?

### Anti-orphan requirement

For the first two critical flows:

- open new patient
- stack / scroll image

every listed job must resolve to exactly one primary block owner.

That contract is now enforced by:

- `tests/performance/test_pipeline_job_block_model.py`

### Required test lanes

#### Block 1 lane

Focus:

- download progress normalization
- thumbnail projection contract
- DB/storage persistence budgets
- download/preemption churn

#### Block 2 lane

Focus:

- first image visible
- decode/filter/render/present timing
- stable image presentation
- exact vs surrogate frame behavior

#### Block 3 lane

Focus:

- stale-drop rate
- terminal duplicate suppression
- cache-warm duplication
- scroll/redraw hitch attribution
- admission behavior under overlap
- orchestrator event-journal correctness
- block-ownership correctness for admitted work

#### Integration lane

Focus:

- Block 1 → Block 3 fan-in normalization
- Block 3 → Block 2 protection of interaction
- terminal completion one-shot per epoch
- overlap control-plane calmness

## Delivery order

Recommended order on top of the existing FAST execution plan:

1. **Measurement lock with block grouping**
   - make every scenario summarizable by block
2. **Block 1 normalization**
   - one canonical progress stream
   - thumbnail projection stays projection-only
3. **Block 3 ownership collapse**
   - one lifecycle owner
   - one admission front door
   - one redraw owner
4. **Block 2 hot-path reduction**
   - series-load decomposition
   - first-image fast path
   - image stability hardening
5. **Cross-block KPI closure**
   - prove which block improved
   - prove which block still fails on overlap

## Definition of success

This block model is successful when the team can answer all of these for any regression run:

- which block regressed
- which KPI inside that block regressed
- which worker/process path was involved
- which orchestrator decision allowed the regression to happen
- which file group owns the fix

If a run is faster but we still cannot answer those questions clearly, the architecture is still too blurred.
