# ClearCanvas KPI Mapping

**Date:** 2026-04-15  
**Scope:** FAST mode only (`pydicom_qt`)  
**Ground truth input:** `docs/analysis/CLEARCANVAS_WORKSTATION_COMPARISON.md`

---

## Purpose

This document converts the architectural divergences between AI-PACS FAST and ClearCanvas into KPI consequences.

The goal is not to prove that ClearCanvas is “better” in the abstract. The goal is to identify which AI-PACS structural differences measurably affect:

- scroll smoothness
- mixed-load responsiveness
- UI event-loop stability
- wasted background work
- correctness recovery after progressive growth

---

## KPI set used here

The mapping below uses the current FAST performance vocabulary from `docs/plans/plan.md`, `docs/performance/PERFORMANCE_STATUS.md`, and `docs/performance/FAST_VIEWER_KPI_CATALOG.md`.

### Primary KPIs

| KPI | Meaning |
|---|---|
| `set_slice_present_p95_ms` | p95 time for interactive frame presentation to reach UI |
| `foreground_wait_p95_ms` | p95 time the user-visible path waits on foreground work |
| `ui_event_loop_lag_ms` | callback-gap estimate for UI responsiveness pressure |
| `cpu_scroll_plus_download_pct` | process CPU during interaction + download overlap |
| `stale_task_ratio` | stale background tasks / submitted tasks |
| `cache_hit_ratio` | frame/pixel cache hit efficiency near current position |
| `time_to_exact_after_stop_p95_ms` | time from interaction stop to exact final frame |
| `terminal_completion_duplicate_count` | duplicate terminal grow/cache-warm actions per series/epoch |
| `progressive_grow_latency_ms` | time from new downloaded images to visible slice-count extension |
| `thumbnail_update_burst_rate_hz` | effective UI update pressure from thumbnail/progress churn |

---

## Mapping by divergence

### 1) Ownership spread vs single rooted viewer graph

**AI-PACS loci**
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- `modules/viewer/fast/ui_throttle.py`
- `modules/viewer/pipeline/orchestrator.py`

**ClearCanvas contrast**
- `Workspace -> ImageViewerComponent -> PhysicalWorkspace/LogicalWorkspace -> ImageBox -> DisplaySet -> PresentationImage`

**KPI effect**
- Raises `ui_event_loop_lag_ms` because more independent code paths can schedule UI-visible follow-up work.
- Raises `foreground_wait_p95_ms` when multiple owners attempt “small but immediate” main-thread actions in the same interval.
- Raises `terminal_completion_duplicate_count` because terminal work is guarded in several places instead of one owner deciding once.

**Mechanism**
- The same series lifecycle is touched by bridge interaction logic, progressive lifecycle, shared throttle policy, and orchestrator download state.
- Even when each branch is individually cheap, overlap creates burstiness.

---

### 2) Progressive lifecycle with compatibility guards instead of one canonical progression

**AI-PACS loci**
- `_vc_progressive.py` state helpers, done/inflight/completed guards, Layer 2b/3/4 completion paths

**KPI effect**
- Directly increases `terminal_completion_duplicate_count`.
- Increases `progressive_grow_latency_ms` via rechecks, retries, and cross-layer reconciliation.
- Can spike `set_slice_present_p95_ms` and `ui_event_loop_lag_ms` even with `decode_ms=0`, because the cost is orchestration churn rather than decode.

**Mechanism**
- A terminal callback that arrives late can still attempt lifecycle re-entry unless rejected very early.
- Completion work is conceptually one-shot but operationally spread across several safety layers.

---

### 3) Multi-source load policy instead of one small policy authority

**AI-PACS loci**
- `system_load_controller.py`
- `ui_throttle.py`
- `qt_viewer_bridge.py`
- `lightweight_2d_pipeline.py`
- `_vc_progressive.py`

**KPI effect**
- Raises variance in `set_slice_present_p95_ms` because different call sites can still carry local timing behavior.
- Raises `ui_event_loop_lag_ms` when individual subsystems make locally-correct decisions that are globally simultaneous.
- Complicates improvements to `cpu_scroll_plus_download_pct` because policy is not enforced at one admission point.

**Mechanism**
- The load controller exists, which is good.
- But it still fronts decisions that are consumed in several places rather than admitting work through one scheduler-like authority.

---

### 4) UI flood path from download manager to viewer + thumbnails

**AI-PACS loci**
- `home_download_service.py`
- `thumbnail_manager.py`
- `_vc_progressive.py`

**KPI effect**
- Raises `thumbnail_update_burst_rate_hz`.
- Raises `ui_event_loop_lag_ms` during mixed load.
- Raises `cpu_scroll_plus_download_pct` due to repeated small UI updates and progress formatting.
- Indirectly raises `set_slice_present_p95_ms` when scroll competes with these updates.

**Mechanism**
- DM emits series progress.
- Home service forwards it to patient widget.
- Viewer progressive path and thumbnail path both consume it.
- Coalescing now exists, but the path still fan-outs at multiple layers.

---

### 5) Cache richness without fully singular cache authority

**AI-PACS loci**
- `lightweight_2d_pipeline.py`
- `disk_pixel_cache.py`
- `decode_service.py`
- historical FAST booster overlap noted in `docs/plans/plan.md`

**KPI effect**
- Positive effect on `cache_hit_ratio` and reopen latency.
- Negative effect on `cpu_scroll_plus_download_pct` when overlapping cache/prefetch helpers are alive together.
- Negative effect on `stale_task_ratio` if more than one layer prefetches or warms without shared ownership.

**Mechanism**
- L0/L1/L2 cache layering is justified.
- Trouble appears when additional helpers behave like partial caches or independent warmers.

**Takeaway**
- Not all layering is bad.
- The KPI problem is not “too many caches” in principle; it is “too many cache-like actors deciding to work.”

---

### 6) Fast renderer is efficient, but redraw/sync ordering is distributed

**AI-PACS loci**
- `qt_viewer_bridge.py`
- patient widget sync paths
- reference-line update paths referenced in project docs/instructions

**KPI effect**
- Raises `set_slice_present_p95_ms` tails under sync-enabled or multi-view scenarios.
- Raises `ui_event_loop_lag_ms` during interaction bursts.

**Mechanism**
- ClearCanvas uses a more explicit coordination mediator for synchronization tools.
- AI-PACS protects many expensive paths, but the ordering remains distributed across viewer/controller/sync callbacks.

---

### 7) Progressive metadata repair during live growth

**AI-PACS loci**
- `_vc_progressive.py`
- metadata sync helpers
- thumbnail count update path

**KPI effect**
- Raises `progressive_grow_latency_ms`.
- Raises `ui_event_loop_lag_ms` in download-heavy windows.
- Can indirectly affect `time_to_exact_after_stop_p95_ms` if progressive reconciliation lands near interaction stop.

**Mechanism**
- AI-PACS solves a harder problem than ClearCanvas: new slices can appear while viewer state is already live.
- The cost is real and justified, but it must be bounded behind one growth authority.

---

### 8) Decode is no longer the dominant mixed-load bottleneck

**AI-PACS loci**
- `[B3.8_SCROLL]` metrics from `qt_viewer_bridge.py`
- pipeline fast path in `lightweight_2d_pipeline.py`

**KPI effect**
- `decode_ms` is often `0`, yet `set_slice_present_p95_ms` still spikes during mixed load.
- This strongly points remaining lag toward orchestration and UI churn, not core pixel decode.

**Mechanism**
- Cache-hot frame generation is already in the ~2–5ms class.
- Therefore remaining 50–80ms-class spikes have to come from event pressure, lifecycle churn, redraw collisions, or progress-side work.

---

## Priority ranking by KPI damage

| Rank | Divergence | Primary KPI damage | Why it ranks here |
|---|---|---|---|
| 1 | Progressive lifecycle over-authority | `terminal_completion_duplicate_count`, `ui_event_loop_lag_ms`, `set_slice_present_p95_ms` | Produces repeated terminal work in the exact period where user-visible latency is most fragile |
| 2 | UI flood path from DM → viewer + thumbnails | `ui_event_loop_lag_ms`, `cpu_scroll_plus_download_pct`, `thumbnail_update_burst_rate_hz` | Small updates arrive often and collide with interaction |
| 3 | Distributed load policy | `set_slice_present_p95_ms`, `ui_event_loop_lag_ms` | Prevents consistent admission control for non-interactive work |
| 4 | Distributed redraw/sync ordering | `set_slice_present_p95_ms` tails | Mostly visible when sync, ref-lines, or multi-view coordination are active |
| 5 | Non-singular cache-like helpers | `stale_task_ratio`, `cpu_scroll_plus_download_pct` | More historical than current, but must stay closed to avoid regression |
| 6 | Live metadata repair during growth | `progressive_grow_latency_ms` | Necessary work, but still needs stronger bounding |

---

## KPI implications for engineering decisions

### What should not be optimized next

Do **not** prioritize another decode micro-optimization pass unless new evidence shows `decode_ms` has returned as the dominant term.

Reason:
- current evidence already shows cache-hot frames in the low-millisecond range
- mixed-load spikes still happen with `decode_ms=0`

### What should be optimized next

1. **Terminal lifecycle idempotence and single completion authority**
   - best target for reducing `terminal_completion_duplicate_count`
   - high leverage on `ui_event_loop_lag_ms`

2. **Single UI-facing admission policy for non-interactive work**
   - best target for stabilizing `set_slice_present_p95_ms`
   - strongest lever on mixed-load jitter

3. **Collapse DM progress fan-out into one viewer update contract**
   - best target for lowering `thumbnail_update_burst_rate_hz`
   - helps `cpu_scroll_plus_download_pct`

4. **Explicit redraw coordinator for sync/reference-line follow-up**
   - best target for multi-view tail latency

---

## Success criteria

The target architecture should produce measurable movement in these KPIs:

| KPI | Current qualitative state | Target direction |
|---|---|---|
| `set_slice_present_p95_ms` | cache-hot good, mixed-load tails still present | reduce tails materially under download overlap |
| `foreground_wait_p95_ms` | should fall once non-interactive bursts are gated | lower |
| `ui_event_loop_lag_ms` | still burst-sensitive | lower and more stable |
| `cpu_scroll_plus_download_pct` | still high under overlap | lower |
| `stale_task_ratio` | should remain bounded and not regress | stable or lower |
| `cache_hit_ratio` | maintain current gains | stable or higher |
| `time_to_exact_after_stop_p95_ms` | must not regress while simplifying | stable or lower |
| `terminal_completion_duplicate_count` | should approach zero per series/epoch | near-zero |

---

## Bottom line

The KPI story is now clear:

> AI-PACS FAST has mostly solved the raw frame pipeline, but it still pays a measurable tax for distributed orchestration, duplicated terminal completion logic, and UI-facing progress churn.

That means the next wins come from **authority reduction and event admission control**, not from making `_decode_slice()` 0.8ms faster and then wondering why the app still hiccups.
