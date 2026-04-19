# ClearCanvas Full Review And KPI Benchmark Plan

**Date:** 2026-04-15  
**Scope:** ClearCanvas workstation source vs AI-PACS FAST workstation/runtime  
**Reference checkout:** `C:\AI-Pacs codes\ClearCanvas-master\ClearCanvas-master`

---

## What Was Reviewed

This review was grounded in the current project documentation and the inspected source trees, not in product folklore.

### AI-PACS documentation reviewed

- `docs/plans/plan.md`
- `docs/README.md`
- `docs/architecture/overview.md`
- `docs/architecture/workstation-lifecycle.md`
- `docs/performance/PERFORMANCE_STATUS.md`
- `docs/plans/performance/FAST_VIEWER_PERFORMANCE_ROADMAP.md`
- `docs/performance/FAST_VIEWER_KPI_CATALOG.md`
- `docs/performance/FAST_VIEWER_TEST_SCENARIOS.md`
- `docs/performance/CONCURRENCY_ANALYSIS_v2.3.3.md`
- `docs/performance/WORKLOAD_MODEL.md`
- `docs/viewer/FAST_PIPELINE_DETAILED.md`
- `docs/analysis/CLEARCANVAS_WORKSTATION_COMPARISON.md`
- `docs/analysis/CLEARCANVAS_DIVERGENCE_MATRIX.md`
- `docs/analysis/CLEARCANVAS_KPI_MAPPING.md`
- `docs/analysis/ORCHESTRATION_ROOT_CAUSES.md`

### AI-PACS code reviewed

- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- `modules/viewer/fast/perf_metrics.py`
- `modules/viewer/fast/system_load_controller.py`
- `modules/viewer/fast/ui_throttle.py`
- `modules/viewer/pipeline/orchestrator.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- `tests/performance/test_b25_scenarios.py`
- `tests/performance/perf_helpers.py`

### ClearCanvas code reviewed

- `Desktop/Workspace.cs`
- `ImageViewer/ImageViewerComponent.cs`
- `ImageViewer/StudyManagement/StudyLoader.cs`
- `ImageViewer/StudyLoaders/Streaming/StreamingStudyLoader.cs`
- `ImageViewer/StudyManagement/Frame.cs`
- `ImageViewer/StudyManagement/WeightedWindowPrefetchingStrategy.cs`
- `ImageViewer/Tools/Synchronization/SynchronizationToolCoordinator.cs`
- `ImageViewer/Volumes/VolumeCache.cs`
- `ImageViewer/Thumbnails/ThumbnailLoader.cs`

---

## Final Verdict

AI-PACS does **not** mainly lose to ClearCanvas because its raw FAST renderer is bad. It loses because the workstation still admits too much overlapping control-plane work during mixed load.

The cleanest short statement is:

> AI-PACS has a credible FAST engine, but its shell, progressive lifecycle, and UI fan-out still behave like several partial authorities instead of one calm owner.

ClearCanvas validates the direction of:

- single rooted viewer ownership
- clear shell/workspace/viewer separation
- lazy header/pixel access
- explicit sync coordination
- single-authority cache lifetime management

ClearCanvas does **not** invalidate:

- FAST vs Advanced separation
- disk pixel cache
- subprocess decode isolation
- load-aware throttling
- progressive viewing as a product capability

Those are justified by AI-PACS's harder runtime problem.

---

## Deficiencies In AI-PACS

### 1. Ownership is still spread across too many layers

The FAST viewer path is split across:

- `PatientWidget` / controller mixins
- `QtViewerBridge`
- `Lightweight2DPipeline`
- `SystemLoadController`
- `ui_throttle`
- `PipelineOrchestrator`
- progressive helpers in `_vc_progressive.py`

This makes local fixes possible, but it makes global timing behavior difficult to predict.

### 2. Progressive lifecycle still has too many terminal authorities

The current state machine is better than before, but terminal completion still carries legacy compatibility sets and multiple verification layers. That means the exact moment that should become quiet can still become noisy.

This is the biggest structural defect still visible in runtime evidence.

### 3. Download progress still fans out into too many UI-side actions

One download event can still drive:

- progressive viewer updates
- thumbnail overlay updates
- completion pulses
- series-downloaded signaling
- post-completion warm behavior

Even after coalescing, this is still too much surface area for one event source.

### 4. Load policy exists, but admission is still not singular

`SystemLoadController` is the right move, but it is still acting more like a shared rulebook than a real admission gate.

That means several callers can still decide that their work is cheap enough to run now.

### 5. Sync/redraw follow-up is still too distributed

ClearCanvas has a small synchronization mediator. AI-PACS has equivalent protections, but the redraw intent is still scattered across viewer, controller, and follow-up callbacks.

That creates tail latency and maintenance ambiguity.

### 6. Some cache-adjacent behavior still risks reintroducing overlap

The core FAST cache stack is justified:

- frame cache
- pixel cache
- disk pixel cache
- optional decode service

The problem is not the existence of these layers. The problem is any extra helper that starts behaving like an independent prefetcher, warmer, or cache owner.

---

## Bottlenecks

### Primary bottlenecks

1. Progressive terminal duplicate handling and post-completion churn
2. Download-manager progress fan-out into viewer plus thumbnails
3. Non-singular work admission for protected UI intervals
4. Distributed redraw/sync ordering

### Secondary bottlenecks

5. Metadata repair too close to live viewer update windows
6. Residual background work competing during interaction even when the frame path is already cache-hot

### Not the primary bottleneck anymore

- raw `_decode_slice()` speed by itself
- QImage conversion by itself
- simple cache-hit rendering

Current evidence already shows many cache-hot FAST frames in the low-millisecond class.

---

## Unnecessary Or Low-Value Work

These are the strongest candidates for removal, demotion, or tighter gating.

### Remove or collapse

- duplicate terminal completion handling on the same series epoch
- duplicate post-completion cache-warm dispatch
- repeated progress-side UI churn during active interaction
- any remaining FAST helper that acts like a second cache authority

### Keep but demote behind one gate

- metadata repair
- progressive grow follow-up
- thumbnail overlay updates
- diagnostic logging during protected UI windows

### Keep as-is

- FAST/Advanced separation
- main FAST pipeline and disk cache
- load probes
- exact wheel rendering policy

---

## What Must Be Fixed First

### Priority 1

1. Make terminal completion genuinely one-shot per series epoch
2. Collapse download-progress fan-out into one viewer-facing contract
3. Put all non-interactive FAST work behind one admission point

### Priority 2

4. Add a small redraw coordinator for sync/reference-line follow-up
5. Continue reducing lifecycle compatibility sets in `_vc_progressive.py`

### Priority 3

6. Trim any remaining low-value log/UI updates during overlap
7. Keep FAST booster-style overlap retired in FAST mode

---

## Benchmark Strategy

The benchmark must be split into two tracks.

### Track A: Common local-viewing benchmark

Use the **same fully local DICOM series** in both ClearCanvas and AI-PACS.

This is the fair apples-to-apples comparison.

Measure:

- first image visible
- browse/scroll tail latency
- process CPU
- peak RSS
- thread pressure
- warm reopen behavior

### Track B: AI-PACS-only live-overlap benchmark

This is **not** comparable to ClearCanvas one-to-one, because ClearCanvas is not carrying the same progressive live-growth burden.

Use it to measure the extra tax AI-PACS pays for:

- active download plus viewing overlap
- progressive grow churn
- duplicate terminal completion
- post-completion cache warm storms

Measure:

- scroll tail under overlap
- terminal completion duplicates
- cache-warm duplicates
- CPU under overlap
- stale work ratio

---

## Test Files Added

The following files were added for repeatable KPI comparison:

- `tests/performance/clearcanvas_aipacs_scenarios.json`
- `tools/performance/clearcanvas_aipacs_kpi_harness.py`
- `tests/performance/test_clearcanvas_aipacs_kpi_harness.py`

The scenario file defines the step-by-step protocol. The tool can:

- run a headless AI-PACS FAST pipeline benchmark
- monitor an external process such as ClearCanvas during the same scripted steps
- parse AI-PACS logs for orchestration-specific KPI signals
- compare two result JSON files into one Markdown report

---

## Step-By-Step Simulation

### 1. Common local-viewing comparison

Use scenario `common_local_viewing`.

Run AI-PACS headless core benchmark:

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py `
  run-aipacs-headless `
  --dataset "C:\path\to\dicom_series" `
  --scenario common_local_viewing
```

Run ClearCanvas with the same dataset, then monitor its process during the same steps:

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py `
  monitor-process `
  --scenario common_local_viewing `
  --process-name ClearCanvas.ImageViewer `
  --label ClearCanvas
```

Then compare:

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py `
  compare `
  --left generated-files\benchmarks\aipacs_headless_*.json `
  --right generated-files\benchmarks\external_viewer_monitor_*.json
```

### 2. AI-PACS live-download overlap

Use scenario `aipacs_live_download_overlap`.

Headless core stress:

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py `
  run-aipacs-headless `
  --dataset "C:\path\to\dicom_series" `
  --scenario aipacs_live_download_overlap
```

Real runtime orchestration parse:

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py `
  parse-aipacs-log `
  --log "C:\path\to\aipacs.log"
```

This second track is where duplicate terminal completion and cache-warm churn should be judged.

---

## How To Read The KPI Output

### If AI-PACS loses on Track A

That means the problem is in the core workstation path even without live download. The likely culprits are:

- ownership spread
- redraw ordering
- too many always-on helpers

### If AI-PACS is close on Track A but loses badly on Track B

That means the FAST engine is fundamentally acceptable and the problem is exactly what the current documentation already points to:

- mixed-load orchestration
- duplicate terminal actions
- UI event fan-out

That is the most likely result.

---

## Bottom Line

The important conclusion is not that ClearCanvas should be copied line-for-line.

The important conclusion is:

> AI-PACS should preserve its stronger FAST data path, but it must become much stricter about who is allowed to act as an authority during a mixed-load session.

That means the next major improvement should be an **authority simplification pass**, not another decode micro-optimization sprint.
