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
