# Orchestration Root Causes

**Date:** 2026-04-15  
**Scope:** FAST mode only (`pydicom_qt`)  
**Ground truth input:** `docs/analysis/CLEARCANVAS_WORKSTATION_COMPARISON.md`

---

## Purpose

This document identifies the main causes of remaining FAST mixed-load lag after the B3.x render/data-path work.

This is intentionally **not** a re-analysis of decode performance. The current code and logs already show that the FAST renderer is often healthy when cache-hot. The remaining issue is orchestration pressure.

---

## Root cause summary

### RC1 — Progressive lifecycle has too many terminal authorities

**Primary loci**
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`

**Symptoms**
- repeated `COMPLETE` handling on the same series/epoch
- repeated cache-warm dispatch on the same series/epoch
- lifecycle bounce such as `COMPLETING -> AWAITING -> PROGRESSIVE -> COMPLETING`
- mixed-load spikes with `decode_ms=0`

**Why it happens**
- the progressive path still combines:
  - explicit lifecycle state map
  - compatibility guard sets (`done`, `inflight`, completed-series, Layer 2b guard, terminal-complete guard)
  - Layer 2b final completion
  - Layer 3 verification
  - Layer 4 sweep/recovery
- each layer exists for a real reason, but the write/close authority is still spread too widely

**User-visible effect**
- UI time is spent reconciling terminal state instead of preserving scroll priority
- background work can re-enter exactly when the series should be stabilizing

**Severity**
- **Highest**

---

### RC2 — Download progress fan-out creates multiple UI-side consumers of the same event

**Primary loci**
- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`
- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`
- `_vc_progressive.py`

**Symptoms**
- progress signals touch viewer growth, thumbnail overlays, progress labels, completion pulses, and series-complete wiring
- UI pressure grows during download even when visible rendering is cache-hot

**Why it happens**
- one DM event becomes several UI-facing actions:
  - progressive viewer update
  - thumbnail state update
  - completion pulse
  - series-downloaded signal
- coalescing exists, but fan-out still occurs downstream

**User-visible effect**
- scroll competes with many small UI updates rather than one admitted update stream
- increases burst sensitivity and callback-gap lag

**Severity**
- **High**

---

### RC3 — Load policy exists, but work admission is still not singular

**Primary loci**
- `modules/viewer/fast/system_load_controller.py`
- `modules/viewer/fast/ui_throttle.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `_vc_progressive.py`

**Symptoms**
- protected-mode behavior improves things, but mixed-load tails remain
- several call sites still decide locally whether to defer, coalesce, or proceed

**Why it happens**
- the project now has a good policy shell, but not yet a single UI-admission owner for non-interactive FAST work
- interaction, progressive grow, cache warm, thumbnail work, and logging are policy-aware, but they are still initiated from several places

**User-visible effect**
- globally, the app can still admit too many “cheap” tasks in the same protected interval

**Severity**
- **High**

---

### RC4 — Redraw and synchronization follow-up are still distributed

**Primary loci**
- `modules/viewer/fast/qt_viewer_bridge.py`
- sync/reference-line paths described in `copilot-instructions.md` and performance docs

**Symptoms**
- scroll may remain smooth in simple cases but tail latency rises in coordinated/multi-view flows
- redraw ordering is harder to predict than in ClearCanvas-style mediator systems

**Why it happens**
- AI-PACS has defensive throttles and guards, but not one small redraw coordinator for sync/reference-line follow-up
- multiple subsystems can still request near-term UI work after an interaction change

**User-visible effect**
- long-tail jank, especially when interaction overlaps with linked updates

**Severity**
- **Medium**

---

### RC5 — Live metadata repair is necessary, but it still lives too close to the hot path

**Primary loci**
- `_vc_progressive.py`
- thumbnail count and metadata sync helpers

**Symptoms**
- progressive display has to repair viewer-visible metadata as slices arrive
- growth correctness depends on metadata freshness and consistency

**Why it happens**
- AI-PACS supports a live-growing series while the viewer is already active
- this is inherently more turbulent than ClearCanvas’s steadier loaded-study model
- the work is justified, but it still competes for the same narrow UI timing windows

**User-visible effect**
- growth cadence and interaction cadence can interfere unless one owner schedules the repair work deliberately

**Severity**
- **Medium**

---

## Why decode is not the top root cause anymore

### Evidence

From current docs and instrumentation:
- cache-hot `[B3.8_SCROLL]` frames are commonly in the ~2–5ms class
- mixed-load spikes can still happen with `decode_ms=0`
- disk cache, prefetch, and surrogate policies already removed the old “always decode on scroll” problem

### Conclusion

The dominant remaining failures are now:
- duplicate terminal actions
- UI progress churn
- distributed non-interactive work admission
- redraw/lifecycle ordering collisions

Not:
- the raw pixel decode path by itself

---

## Cause chain under the current architecture

$$
Download\ progress \rightarrow fan\text{-}out\ to\ viewer\ and\ thumbnails \rightarrow
progressive\ lifecycle\ checks \rightarrow
completion\ safety\ layers \rightarrow
follow\text{-}up\ cache\ warm/grow/sync\ work \rightarrow
UI\ callback\ congestion \rightarrow
scroll\ tail\ latency
$$

The important point is that the problem is **structural fan-out**, not just “too much CPU” in a generic sense.

---

## Top 5 causes ranked by contribution to perceived lag

| Rank | Root cause | Why it contributes most |
|---|---|---|
| 1 | Progressive terminal over-authority | Repeats work exactly when the series should be quiescing |
| 2 | DM progress fan-out to multiple UI consumers | Creates sustained small-burst pressure under active download |
| 3 | Non-singular work admission despite shared policy shell | Allows several subsystems to decide to run in the same interval |
| 4 | Distributed redraw/sync ordering | Produces tail latency and harder-to-predict UI contention |
| 5 | Live metadata repair close to the UI path | Necessary cost, but still not bounded under one growth owner |

---

## Root-cause-guided principles for the next refactor

1. **Single terminal authority**
   - One component decides when a progressive cycle becomes terminal.
   - Recovery layers may verify, but they must not recreate live terminal work by default.

2. **Single non-interactive admission authority**
   - Interaction stays immediate.
   - Everything else asks one FAST scheduler/admission gate whether it may run now.

3. **One viewer-facing progress contract**
   - DM updates should be normalized once, then routed to thumbnails/progressive growth from a single admitted stream.

4. **One redraw follow-up coordinator**
   - Sync, ref-lines, and secondary repaint triggers should queue behind a small explicit coordinator.

5. **Cache ownership must stay singular**
   - `Lightweight2DPipeline` remains the authoritative 2D frame/pixel cache owner.
   - No new side caches or hidden warmers in FAST mode.

---

## What success looks like

The mixed-load session is healthier when:
- duplicate terminal `COMPLETE` / cache-warm activity disappears per series/epoch
- scroll remains in the target frame class while downloads continue
- `ui_event_loop_lag_ms` falls because fewer non-interactive tasks are admitted during protected intervals
- the progressive lifecycle becomes understandable from one small state machine rather than a reconciliation story across several sets and callbacks

---

## Bottom line

> The remaining FAST problem is not “the renderer is still too slow.” It is that too many legitimate subsystems are still allowed to behave like local authorities during a mixed-load session.

The refactor target should therefore be **authority collapse**, not another round of isolated micro-optimizations.