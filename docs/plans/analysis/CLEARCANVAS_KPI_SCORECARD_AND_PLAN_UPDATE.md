# ClearCanvas KPI Scorecard And Plan Update

**Date:** 2026-04-15  
**Scope:** ClearCanvas local reference vs AI-PACS FAST plan, KPI path, and correction priorities  
**Reference ClearCanvas checkout:** `C:\AI-Pacs codes\ClearCanvas-master\ClearCanvas-master`

---

## Purpose

This document turns the ClearCanvas review into an execution scorecard.

The goal is not to copy ClearCanvas code or force AI-PACS into a foreign runtime model. The goal is to use ClearCanvas as a disciplined reference for:

- ownership
- admission control
- redraw ordering
- cache authority
- KPI expectations

---

## Executive Verdict

The strongest conclusion after reviewing the current plan, performance docs, and both source trees is this:

> AI-PACS is not losing mainly because the FAST renderer is weak. It is losing because too many non-render tasks are still allowed to compete at the same time.

ClearCanvas feels calmer because it keeps the runtime graph smaller:

- one shell owner
- one viewer root
- one clearer study-loading model
- one clearer sync coordinator
- one clearer cache owner for MPR

AI-PACS has a stronger mixed-download data path than ClearCanvas, but the control plane around it is still too busy.

---

## Where Our Current Way Is Strong

These are not mistakes and should stay:

1. FAST and Advanced are correctly separated.
2. The FAST 2D pipeline is real engineering, not cosmetic optimization.
3. Disk pixel cache is a good decision.
4. Decode isolation is a reasonable Python-specific response.
5. Download-aware throttling is justified for the product we are building.

This means the next phase should **not** be a renderer rewrite.

---

## Where Our Current Way Is Wrong

These are the main deficiencies relative to ClearCanvas.

| Area | ClearCanvas pattern | AI-PACS current behavior | KPI damage |
|---|---|---|---|
| Ownership | Rooted shell/workspace/viewer graph | Authority spread across bridge, controller mixins, pipeline, throttle, orchestrator, progressive code | tail latency, cleanup ambiguity, more thread pressure |
| Study loading | Header and pixel retrieval are clearly separated | progressive metadata repair and live viewer growth are still entangled | extra UI churn, more lifecycle edge work |
| Admission control | Calmer, fewer actors deciding to work | policy exists but admission is still not singular | CPU spikes, stale work, jank during overlap |
| Sync ordering | explicit `SynchronizationToolCoordinator` mediator | redraw intent is distributed | redraw tails, harder maintenance |
| Cache ownership | singular cache lifetime in MPR path | FAST core cache is fine, but overlap helpers historically act like cache-adjacent owners | avoidable background work |
| Terminal lifecycle | calmer terminal ownership | duplicate terminal and post-completion paths still need guarding | duplicate work, completion storms |

---

## What We Are Probably Doing Unnecessarily

These are the best candidates for removal, demotion, or tighter gating.

### Probably unnecessary

- duplicate terminal completion on the same series epoch
- duplicate post-completion cache warm dispatch
- progress-driven UI churn during protected interaction windows
- any helper that behaves like a second FAST cache authority

### Necessary but currently too eager

- metadata repair
- progressive grow follow-up
- thumbnail overlay refresh
- diagnostic logging during overlap

These should exist, but they should not be allowed to compete directly with `set_slice()` during protected UI intervals.

---

## KPI Scorecard

The comparison must be split into two classes.

### A. Common KPIs we can compare on both apps

These can be measured with the same dataset and the same step script.

| KPI | ClearCanvas | AI-PACS | Why it matters |
|---|---|---|---|
| `first_image_visible_ms` | yes | yes | open-to-first-frame user experience |
| `set_slice_present_p95_ms` | yes, by scripted observation/process-timed step | yes, directly from headless/logged run | browsing smoothness |
| `cpu_p95_pct` | yes | yes | control-plane overhead signal |
| `rss_peak_mb` | yes | yes | cache and retention discipline |
| `thread_count_p95` | yes | yes | actor count and ownership spread |
| `read_mb_delta` | yes | yes | retrieval/caching behavior |
| `write_mb_delta` | yes | yes | cache persistence and extra churn |

### B. AI-PACS-only KPIs

These measure the extra runtime class that ClearCanvas does not carry in the same way.

| KPI | Why AI-PACS-only |
|---|---|
| `terminal_completion_duplicate_count` | ClearCanvas does not expose the same progressive terminal lifecycle |
| `cache_warm_duplicate_count` | ClearCanvas does not run the same post-completion warm path |
| `stale_task_ratio` | internal FAST prefetch/decode relevance metric |
| `cache_hit_ratio_pct` | internal FAST cache efficiency metric |
| `decode_p95_ms` | internal FAST decode metric |
| `frame_render_p95_ms` | internal FAST render metric |
| `longest_ui_gap_ms` | current AI-PACS event-loop lag instrumentation |

### Interpretation rule

If AI-PACS is worse on the common KPIs **and** also shows high AI-PACS-only storm KPIs, the diagnosis is not "our renderer is slow." The diagnosis is "our overlap model is too noisy."

---

## 2026-04-17 First Executed Benchmark Status

This section records the first real AI-PACS benchmark execution performed from the prepared harness.

### Run status

- **AI-PACS common local benchmark:** executed
- **AI-PACS overlap benchmark:** executed
- **ClearCanvas runtime benchmark:** not executed yet

### Dataset and artifact paths

- Dataset used:
  - `user_data/patients/dicom/1.2.840.1.99.1.47.1.1772527236103.85188/202`
  - local 342-slice series
- Output folder:
  - `generated-files/benchmarks/run_001/`
- Produced artifacts:
  - `aipacs_common.json`
  - `aipacs_overlap.json`
  - `aipacs_overlap_vs_common.md`

### ClearCanvas runtime feasibility status

What was verified locally:
- ClearCanvas source checkout exists at `C:\AI-Pacs codes\ClearCanvas-master\ClearCanvas-master`
- `Desktop\Desktop.sln` exists

What is still missing for runtime comparison here:
- no built ClearCanvas desktop executable was found
- `ReferencedAssemblies` folders were not present

So the honest status is:

> ClearCanvas runtime benchmarking is **prepared structurally but still blocked operationally** in this environment.

### Measured AI-PACS results

| KPI | AI-PACS common local | AI-PACS overlap | Reading |
|---|---:|---:|---|
| `first_image_visible_ms` | 327.72 | 1382.48 | overlap startup becomes 4.2× worse |
| `set_slice_present_p50_ms` | 0.05 | 14.41 | overlap loses cache-hot browsing calm |
| `set_slice_present_p95_ms` | 24.85 | 30.04 | both runs still miss the 16ms target |
| `set_slice_present_max_ms` | 191.09 | 60.04 | baseline has rarer severe outliers; overlap is more consistently slow |
| `decode_p95_ms` | 62.34 | 27.45 | overlap regression is not caused by slower decode |
| `frame_render_p95_ms` | 46.82 | 29.93 | render path is not the main overlap bottleneck |
| `cache_hit_ratio_pct` | 56.2 | 48.0 | overlap harms locality/effectiveness |
| `slow_frame_count_16ms` | 63 / 296 | 124 / 248 | overlap roughly doubles missed frames |
| `stale_task_ratio` | 0.9537 | 0.99 | both runs are overwhelmed by stale background work |
| `cpu_p95_pct` | 132.2 | 166.08 | overlap adds major control-plane CPU overhead |
| `thread_count_p95` | 31 | 33 | overlap keeps more concurrent actors alive |

### 2026-04-15 stabilization-pass recapture (`run_002`)

After the bounded stabilization pass requested for this repo, the same harness was rerun on the same dataset.

Artifacts:
- `generated-files/benchmarks/run_002/aipacs_common.json`
- `generated-files/benchmarks/run_002/aipacs_overlap.json`
- `generated-files/benchmarks/run_002/aipacs_overlap_vs_common.md`

Measured AI-PACS results (`run_002`):

| KPI | AI-PACS common local | AI-PACS overlap | Reading |
|---|---:|---:|---|
| `first_image_visible_ms` | 227.61 | 1103.79 | still overlap-heavy, but improved vs `run_001` |
| `set_slice_present_p50_ms` | 0.03 | 2.99 | overlap browsing is still slower than local, but no longer persistently 14ms-class |
| `set_slice_present_p95_ms` | 23.33 | 6.45 | overlap tail improved sharply in the headless harness |
| `decode_p95_ms` | 23.12 | 4.52 | overlap remains cheaper on pure decode cost |
| `frame_render_p95_ms` | 23.94 | 6.30 | overlap render tail also improved materially |
| `cache_hit_ratio_pct` | 56.2 | 48.2 | locality is still worse under overlap |
| `slow_frame_count_16ms` | 109 / 296 | 0 / 248 | overlap no longer misses the 16ms threshold in this headless run |
| `stale_task_ratio` | 0.9538 | 0.9899 | stale-work KPI did not improve in any meaningful way |
| `cpu_p95_pct` | 85.0 | 189.4 | overlap CPU got worse despite lower frame latency |
| `thread_count_p95` | 29 | 33 | overlap still keeps more concurrent actors alive |

### What `run_002` changes in the scorecard

It strengthens and narrows the diagnosis:

- The shared admission tightening can improve frame-path latency substantially.
- But the main KPI gate for the bounded pass is still **not passed** because:
  - `stale_task_ratio` remains essentially pinned near `1.0`
  - overlap `cpu_p95_pct` is worse than before

So the honest scorecard update is:

> We improved the headless frame path, but we did **not** yet prove that overlap orchestration is calm enough overall.

That means the next capture must be a live app/runtime-log run, not another documentation-only inference cycle.

### What the first real run means

This run strengthens the earlier architectural conclusion:

> The remaining performance problem is not mainly decode speed. It is authority spread, event fan-out, and over-admission of non-interactive work.

Why that conclusion is justified:
- overlap `decode_p95_ms` got **better** (`62.34 → 27.45`) while user-visible KPIs got worse
- overlap `cpu_p95_pct` rose strongly (`132.2 → 166.08`)
- `stale_task_ratio` remained extremely high (`0.9537 → 0.99`)
- overlap `set_slice_present_p50_ms` jumped from effectively free (`0.05`) to a persistently slow `14.41`

That combination does **not** point to a decode-path emergency. It points to a control-plane/admission emergency.

---

## Lag Classification For The Current Evidence

Use the following A/B/C/D/E categories for the current benchmark evidence.

| Class | Meaning | Status | Why |
|---|---|---|---|
| **A** | Decode-bound lag | **Secondary** | decode is still non-trivial, but it does not explain the overlap regression |
| **B** | Main-thread blocked / UI-path work | **Present** | first-image latency explodes under overlap, and `_vc_progressive.py` still owns multi-layer UI-adjacent work |
| **C** | Event storm / fan-out | **Strong** | one DM progress event still drives viewer growth + thumbnail progress + completion pulse + downloaded signal |
| **D** | Scheduling / admission conflict | **Strongest** | stale-task ratios near 1.0 show the app is admitting huge amounts of now-irrelevant work |
| **E** | Redraw / follow-up duplication | **Moderate** | scroll path still triggers slider/sync/reference-line/thumbnail follow-up work from several places |

### Important nuance

The current run is **headless**, so:
- it is strong for admission/CPU/stale-work evidence
- it is weaker for live Qt callback-gap evidence
- it does not prove whether duplicate terminal log markers are fully gone in the real app

So the right statement is:

> A, B, C, and especially D are already evidenced by execution. E is strongly suggested by code-path mapping and should be validated with the next live app runtime capture.

---

## Code-Path Mapping Back To The Benchmarks

### 1. Event fan-out from download manager into viewer + thumbnails

Primary path:
- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`

Observed fan-out:
- `seriesProgressUpdated -> on_series_progress`
- `w.series_images_progress.emit(...)`
- `w.thumbnail_manager.update_series_progress(...)`
- completion path also emits:
  - `_emit_final_progress(...)`
  - `w.series_downloaded.emit(...)`

Implication:
- one DM progress event still becomes multiple UI-facing actions immediately

### 2. Progressive lifecycle over-authority

Primary path:
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`

Observed complexity:
- lifecycle state map
- done/inflight/completed compatibility sets
- Layer 2b final completion
- Layer 3 verify
- Layer 4 sweep
- deferred grow and deferred cache warm

Implication:
- the code is much better defended than before, but the terminal authority surface is still large

### 3. Admission conflict in prefetch / background work

Primary path:
- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/ui_throttle.py`
- `modules/viewer/fast/system_load_controller.py`

Observed benchmark symptom:
- `stale_task_ratio=0.9537` in common local
- `stale_task_ratio=0.99` in overlap

Implication:
- the policy shell exists, but actual submission pressure is still far too high for the viewed work

### 4. User-facing scroll bridge remains synchronous, as it should

Primary path:
- `modules/viewer/fast/qt_viewer_bridge.py`

Good news:
- `set_slice()` still keeps user interaction first-class

Remaining risk:
- after `set_slice()`, follow-up work still fans into thumbnail, sync, slider, and progressive consumers nearby in time

---

## Code-Level Fix Design After The First Execution

These are the best next changes supported by the run.

### Fix 1 — One viewer-facing progress stream

Goal:
- collapse `HomeDownloadService` progress fan-out into one coalesced per-series stream

Change direction:
- create a small admitted progress event object per series/cadence
- progressive display and thumbnails consume that same admitted event instead of each receiving direct DM progress callbacks

Expected KPI effect:
- lower `cpu_p95_pct`
- better `set_slice_present_p95_ms`
- fewer burst callbacks during overlap

**2026-04-15 status:** implemented in `HomeDownloadService` as a coalesced per-series progress gateway with dedup and admitted cadence. Live runtime validation still pending.

### Fix 2 — One terminal closer, recovery layers verify only

Goal:
- keep Layer 2b as the only normal terminal closer for a series epoch

Change direction:
- Layer 3 and Layer 4 should verify and repair only
- they must not recreate active terminal work or re-open the normal completion path by default

Expected KPI effect:
- lower duplicate-work probability
- calmer post-completion interval

**2026-04-15 status:** implemented via `_finalize_progressive_series(...)` + `_progressive_finalized_series` one-shot guarding. Verified by progressive regression suites; live duplicate-log recapture still pending.

### Fix 3 — Admission hardening under heavy download + fast interaction

Goal:
- make `SystemLoadController` the real authority for non-interactive FAST work

Change direction:
- reduce or skip low-value prefetch submission during protected overlap windows
- favor relevance near current slice over generic ahead/behind submission
- ensure admitted work volume matches what interaction can realistically use

Expected KPI effect:
- `stale_task_ratio` should drop sharply
- `cpu_p95_pct` should drop
- overlap `set_slice_present_p95_ms` should improve materially

**2026-04-15 status:** partially implemented. `SystemLoadController.should_admit(...)` now gates `PROGRESS_UPDATE` and `PREFETCH`, and `Lightweight2DPipeline` routes prefetch bursts through it. Headless overlap latency improved, but `stale_task_ratio` and overlap CPU did not yet meet target.

### Fix 4 — Small redraw mediator

Goal:
- queue sync/ref-line/secondary redraw follow-up behind one mediator

Expected KPI effect:
- lower tail jank, especially in multi-view / linked-view scenarios

---

## Estimated KPI Targets For The Next Pass

These are estimates, not achieved results.

| KPI | Current run_001 | Estimated next target |
|---|---:|---:|
| `set_slice_present_p95_ms` (common local) | 24.85 | 16-20 |
| `set_slice_present_p95_ms` (overlap) | 30.04 | 18-24 |
| `cpu_p95_pct` (overlap) | 166.08 | 110-135 |
| `stale_task_ratio` | 0.99 | <0.35 |
| `first_image_visible_ms` (overlap) | 1382.48 | 500-800 |
| `slow_frame_count_16ms` (overlap) | 124 / 248 | <60 / 248 |

These targets are reasonable only if the next pass really removes fan-out and over-admission, not if it just micro-optimizes decode again.

---

## Step-By-Step Benchmark Process

Use the same DICOM set for both applications.

### Scenario 1: common local viewing

Scenario file:
- `tests/performance/clearcanvas_aipacs_scenarios.json`

Steps:
1. Launch the viewer.
2. Open the same local series.
3. Measure first-image-visible.
4. Scroll forward steadily.
5. Run a rapid burst.
6. Reverse direction repeatedly.
7. Stop and settle.
8. Reopen the same series.
9. Collect process KPIs and output JSON.

### Scenario 2: AI-PACS live overlap

This is AI-PACS-only.

Steps:
1. Start download.
2. Open while download is active.
3. Burst-scroll under overlap.
4. Reverse direction under overlap.
5. Let terminal completion and cache warm happen.
6. Parse logs and collect duplicate-work KPIs.

---

## Test Files And Measurement Files

These files now define the benchmark path:

- `tools/performance/clearcanvas_aipacs_kpi_harness.py`
- `tests/performance/clearcanvas_aipacs_scenarios.json`
- `tests/performance/test_clearcanvas_aipacs_kpi_harness.py`

### How to run AI-PACS headless

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py run-aipacs-headless `
  --dataset C:\path\to\dicom-series `
  --scenario common_local_viewing `
  --output generated-files\benchmarks\aipacs_common.json
```

### How to monitor ClearCanvas with the same scripted duration

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py monitor-process `
  --scenario common_local_viewing `
  --process-name ClearCanvas.ImageViewer.exe `
  --output generated-files\benchmarks\clearcanvas_common.json
```

### How to parse AI-PACS logs for overlap-only KPIs

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py parse-aipacs-log `
  --log C:\path\to\aipacs.log `
  --output generated-files\benchmarks\aipacs_overlap_log.json
```

### How to compare result files

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py compare `
  --left generated-files\benchmarks\aipacs_common.json `
  --right generated-files\benchmarks\clearcanvas_common.json `
  --output generated-files\benchmarks\common_comparison.md
```

---

## Plan Correction: What We Should Do Next

The ClearCanvas lesson is not "be simpler everywhere." It is "make ownership and admission obvious."

### Priority 1: Collapse authority

1. Make progressive terminal completion one-shot per series epoch.
2. Collapse viewer-facing progress into one contract.
3. Make `SystemLoadController` the single admission point for non-interactive FAST work.

### Priority 2: Clarify redraw ownership

4. Add a small FAST sync/redraw coordinator inspired by `SynchronizationToolCoordinator`.
5. Ensure sync, ref-lines, and follow-up redraws do not self-schedule from multiple places.

### Priority 3: Protect cache authority

6. Keep `Lightweight2DPipeline` as the only authoritative FAST 2D cache/prefetch owner.
7. Treat cache warm as low-priority admitted work, not as a direct side effect from multiple paths.

### Priority 4: Untangle loading model

8. Push progressive metadata repair farther away from the hot UI path.
9. Make header-state arrival and pixel retrieval conceptually cleaner, more like ClearCanvas's separation.

---

## Optimized Plan Direction

The corrected plan should aim for these outcomes:

| Target | Needed change |
|---|---|
| Reach ClearCanvas-like calm on local viewing | reduce actor count and admission spread |
| Keep AI-PACS advantage on live download | preserve throttling, but route it through one gate |
| Improve user comfort under overlap | drop duplicate work, coalesce low-value updates |
| Improve KPI credibility | benchmark common KPIs and overlap-only KPIs separately |

---

## Bottom Line

ClearCanvas is not proof that AI-PACS should become simpler by removing needed features.

It is proof that:

- fewer authorities win
- clearer ownership wins
- calmer redraw ordering wins
- singular cache ownership wins

So the real correction is:

> keep the FAST engine, keep the mixed-download capability, and remove the extra choreography that does not improve the user's actual work.
