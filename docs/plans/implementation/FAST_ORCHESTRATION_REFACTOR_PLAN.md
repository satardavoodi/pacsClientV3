# FAST Orchestration Refactor Plan

**Date:** 2026-04-15  
**Scope:** FAST mode only (`pydicom_qt`)  
**Ground truth inputs:**
- `docs/analysis/CLEARCANVAS_WORKSTATION_COMPARISON.md`
- `docs/analysis/CLEARCANVAS_DIVERGENCE_MATRIX.md`
- `docs/analysis/CLEARCANVAS_KPI_MAPPING.md`
- `docs/analysis/ORCHESTRATION_ROOT_CAUSES.md`
- `docs/architecture/FAST_ORCHESTRATION_TARGET.md`

---

## Purpose

This is the execution plan for simplifying FAST orchestration without rewriting the renderer.

The plan is intentionally incremental. The current FAST pipeline already has real performance wins. The risk now is destabilizing correctness while trying to “clean everything at once.”

---

## Refactor strategy

### Guiding principles

1. **Interaction path stays sacred**
   - `QtViewerBridge.set_slice()` remains direct and synchronous.
2. **Collapse authority before adding machinery**
   - simplify existing ownership first.
3. **Keep FAST cache/render truth where it is**
   - `Lightweight2DPipeline` remains the 2D cache/render owner.
4. **Replace fan-out with normalization**
   - one canonical event stream before UI projections.
5. **Every step must move a KPI or reduce a known authority split**

---

## Execution sequence

### Step 1 — Canonicalize progressive terminal ownership

**Goal**
- make terminal completion one-shot per `(series, epoch)`

**Primary files**
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`

**Change type**
- refactor existing state transitions and completion close paths
- no user-facing feature change

**Implementation**
- introduce one internal terminal-close function that is the only path allowed to:
  - mark terminal complete for the epoch
  - dispatch final visible grow
  - schedule post-completion cache warm request
  - transition to `DONE`
- verification/sweep layers may call into it only in explicit recovery mode, never as parallel peers

**Expected KPI impact**
- lower `terminal_completion_duplicate_count`
- lower `ui_event_loop_lag_ms`
- reduce mixed-load tails in `set_slice_present_p95_ms`

**Risk**
- medium (progressive correctness)

**Validation**
- extend progressive lifecycle tests around duplicate terminal callbacks and restart-after-DONE
- rerun existing FAST viewer lifecycle/progressive suites

---

### Step 2 — Extract `FastEventNormalizer` from raw DM → viewer wiring

**Goal**
- stop downstream fan-out from starting at the raw signal layer

**Primary files**
- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`

**Change type**
- additive extraction + wiring simplification

**Implementation**
- normalize once:
  - canonical series key
  - current/total
  - terminal pulse
  - epoch marker if available
- emit one viewer-facing progress stream
- make thumbnails and progressive lifecycle consume the normalized stream, not raw DM signal semantics

**Expected KPI impact**
- lower `thumbnail_update_burst_rate_hz`
- lower `cpu_scroll_plus_download_pct`
- lower `ui_event_loop_lag_ms`

**Risk**
- medium (wiring regressions)

**Validation**
- DM/viewer integration tests
- thumbnail progress tests
- manual runtime check: first completion pulse still visible and final grow still occurs once

---

### Step 3 — Introduce `FastAdmissionController` as non-interactive gate

**Goal**
- enforce one admission point for non-interactive FAST work

**Primary files**
- `modules/viewer/fast/system_load_controller.py`
- `modules/viewer/fast/ui_throttle.py`
- new controller file under `modules/viewer/fast/`
- `_vc_progressive.py`
- `thumbnail_manager.py`

**Change type**
- additive component, then route existing decisions through it

**Implementation**
- `SystemLoadController` keeps producing policy
- `FastAdmissionController` becomes the executor-facing gate for:
  - progressive signals
  - grow work
  - thumbnail projection updates
  - cache-warm requests
  - redraw follow-up
- existing direct defer checks become thin adapters or are removed

**Expected KPI impact**
- lower `ui_event_loop_lag_ms`
- lower `foreground_wait_p95_ms`
- more stable `set_slice_present_p95_ms`

**Risk**
- medium

**Validation**
- controller unit tests for each work class
- regression run of interaction-policy tests
- runtime capture under scroll + download

---

### Step 4 — Convert `thumbnail_manager.py` into a projection consumer, not a lifecycle peer

**Goal**
- make thumbnails reflect state instead of influencing orchestration timing

**Primary files**
- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`

**Change type**
- role simplification

**Implementation**
- move any remaining lifecycle-like decisions out
- keep only:
  - displayed ready/downloading state
  - selected state
  - coalesced progress text/border rendering
- consume normalized/admitted updates only

**Expected KPI impact**
- lower `thumbnail_update_burst_rate_hz`
- lower `cpu_scroll_plus_download_pct`

**Risk**
- low to medium

**Validation**
- thumbnail UI tests
- drag/drop priority behavior check
- runtime check during heavy download + scroll

---

### Step 5 — Extract `FastRedrawCoordinator` for sync/reference-line follow-up

**Goal**
- make non-primary redraw ordering explicit

**Primary files**
- likely `modules/viewer/fast/` + patient sync/reference-line call sites

**Change type**
- additive coordinator + routing cleanup

**Implementation**
- queue/dedup redraw intents for:
  - lock sync follow-up
  - reference-line refresh
  - secondary viewer updates
- prioritize after direct interaction render and exact settle work

**Expected KPI impact**
- lower tail `set_slice_present_p95_ms`
- lower `ui_event_loop_lag_ms` in multi-view flows

**Risk**
- medium (sync correctness)

**Validation**
- sync/reference-line targeted tests
- manual multi-view scroll scenario

---

### Step 6 — Retire compatibility guard reads/writes that are now shadowed

**Goal**
- reduce cognitive complexity and eliminate ghost authority

**Primary files**
- `_vc_progressive.py`

**Change type**
- cleanup/removal

**Implementation**
- once the single progressive owner is proven stable:
  - retire direct reads of raw compatibility sets
  - remove redundant write-side maintenance
  - keep only migration-safe shims required by any remaining callers

**Expected KPI impact**
- small direct KPI gain
- large maintainability gain
- lowers future regression risk

**Risk**
- medium if done too early

**Validation**
- only after previous steps are green
- rerun progressive suite and targeted mixed-load runtime capture

---

### Step 7 — Re-baseline mixed-load KPIs and stop if goals are met

**Goal**
- prove that orchestration simplification changed user-visible behavior

**Primary files**
- docs + test harness / runtime capture outputs

**Required KPI comparison**
- `set_slice_present_p95_ms`
- `foreground_wait_p95_ms`
- `ui_event_loop_lag_ms`
- `cpu_scroll_plus_download_pct`
- `stale_task_ratio`
- `cache_hit_ratio`
- `time_to_exact_after_stop_p95_ms`
- `terminal_completion_duplicate_count`

**Stop condition**
- if KPI goals are met, do not continue “cleaning” for aesthetic reasons alone

---

## Suggested implementation order by risk-adjusted value

| Order | Step | Value | Risk | Recommendation |
|---|---|---|---|---|
| 1 | Canonicalize terminal ownership | Very high | Medium | Do first |
| 2 | Normalize DM → viewer events | High | Medium | Do second |
| 3 | Add admission controller | Very high | Medium | Do third |
| 4 | Simplify thumbnail role | Medium | Low/Medium | Do fourth |
| 5 | Add redraw coordinator | Medium/High | Medium | Do fifth |
| 6 | Remove compatibility leftovers | Medium | Medium | Do sixth |
| 7 | Re-baseline and stop | Critical | Low | Always |

---

## KPI expectations by step

| Step | Main KPI expected to move |
|---|---|
| 1 | `terminal_completion_duplicate_count`, `ui_event_loop_lag_ms` |
| 2 | `thumbnail_update_burst_rate_hz`, `cpu_scroll_plus_download_pct` |
| 3 | `foreground_wait_p95_ms`, `set_slice_present_p95_ms` |
| 4 | `cpu_scroll_plus_download_pct` |
| 5 | `set_slice_present_p95_ms` tails in sync/multi-view use |
| 6 | maintenance risk more than runtime KPI |
| 7 | validates all above |

---

## What not to do in this refactor

- Do not merge FAST and Advanced pathways.
- Do not rewrite `Lightweight2DPipeline` first.
- Do not add another cache or booster-style FAST helper.
- Do not introduce a large generalized scheduler before the small admission controller proves sufficient.
- Do not remove correctness recovery layers before the new single-owner path is validated.

---

## Minimal test package per step

### Automated
- `tests/viewer/test_fast_viewer_pipeline.py`
- progressive lifecycle focused tests
- interaction policy tests
- DM integration tests where progress/completion behavior is touched
- thumbnail tests where projection/update cadence is touched

### Runtime validation
- active download + wheel precision scroll
- active download + stack drag
- progressive first display + later terminal completion
- same-series reopen/restart-after-DONE
- multi-view sync/reference-line follow-up scenario

---

## Definition of done

The orchestration refactor is done when:
- one series/epoch produces one terminal completion path
- all non-interactive FAST work routes through one admission controller
- thumbnails no longer behave as lifecycle peers
- redraw/sync follow-up has an explicit coordinator
- current FAST core performance is preserved
- mixed-load KPI tails materially improve

---

## Bottom line

This plan deliberately avoids the classic trap of performance work:

> adding a new system to manage the complexity created by the previous system.

The right move here is smaller and sharper: **collapse authority, normalize events, gate non-interactive work once, and keep the FAST renderer itself mostly alone.**