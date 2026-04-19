# ClearCanvas Divergence Matrix

**Date:** 2026-04-15  
**Scope:** FAST mode only (`pydicom_qt`)  
**Ground truth input:** `docs/analysis/CLEARCANVAS_WORKSTATION_COMPARISON.md`

---

## Purpose

This matrix converts the completed ClearCanvas comparison into a precise list of architectural divergences that matter for FAST workstation stabilization.

The focus is not generic “design taste.” The focus is:

- which structures are different
- why those differences matter under live download + viewing overlap
- which differences are necessary for AI-PACS’s problem domain
- which differences are accidental or harmful and should be reduced

---

## Classification legend

| Label | Meaning |
|---|---|
| **REQUIRED** | AI-PACS needs this difference because it solves a genuinely harder runtime problem than ClearCanvas |
| **ACCIDENTAL** | the difference emerged from implementation history, not from a necessary product requirement |
| **HARMFUL** | the difference materially raises complexity, latency risk, or lifecycle ambiguity and should be reduced |

---

## Divergence matrix

### 1) Viewer ownership and hierarchy

| Aspect | AI-PACS FAST | ClearCanvas | Structural difference | Why it matters under load | Classification |
|---|---|---|---|---|---|
| Root ownership | `PatientWidget` + controller mixins + bridge + pipeline + services | `Workspace -> ImageViewerComponent -> Logical/PhysicalWorkspace -> ImageBox -> DisplaySet -> PresentationImage` | AI-PACS viewer authority is spread across more runtime layers | More places can schedule UI-visible work or retain lifecycle state during mixed load | **HARMFUL** |

**Evidence loci**
- `modules/viewer/fast/qt_viewer_bridge.py`
- `modules/viewer/pipeline/orchestrator.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`

**Conclusion**
- AI-PACS should not copy ClearCanvas literally.
- But it should copy the **single-rooted ownership principle**.

---

### 2) Progressive lifecycle / series growth

| Aspect | AI-PACS FAST | ClearCanvas | Structural difference | Why it matters under load | Classification |
|---|---|---|---|---|---|
| Progressive growth model | Viewer can display a series that is still downloading and growing | Mostly stable loaded-study model with lazy frame access, not live-growing viewer state in the same sense | AI-PACS must reconcile visible state while the dataset changes underneath it | This justifies some extra lifecycle logic, but current guard layering and completion overlap still create orchestration pressure | **REQUIRED** for live growth, **HARMFUL** in current over-layered form |

**Evidence loci**
- `_vc_progressive.py` lifecycle state helpers, grow logic, Layer 2b/3/4 completion paths
- `home_download_service.py` progress/completion forwarding

**Conclusion**
- Live growth is required.
- The current number of lifecycle authorities is not.

---

### 3) Prefetch and cache layering

| Aspect | AI-PACS FAST | ClearCanvas | Structural difference | Why it matters under load | Classification |
|---|---|---|---|---|---|
| Cache/prefetch model | `frame_cache` + `pixel_cache` + `disk_pixel_cache` + decode service + load-aware prefetch | calmer prefetch strategy around frame/view context with cleaner ownership | AI-PACS has richer 2D caching and Python-specific mitigation | Good for reopen speed and mixed-load resilience, but any extra overlapping cache-like helper increases stale work and reasoning cost | **REQUIRED** for Python FAST path, but overlap beyond core layers is **HARMFUL** |

**Evidence loci**
- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/disk_pixel_cache.py`
- `modules/viewer/fast/decode_service.py`
- `docs/plans/plan.md` B4.2 notes about retiring booster overlap in FAST mode

**Conclusion**
- The main pipeline cache stack is justified.
- A second independent FAST cache authority is not.

---

### 4) Decode pipeline

| Aspect | AI-PACS FAST | ClearCanvas | Structural difference | Why it matters under load | Classification |
|---|---|---|---|---|---|
| Decode path | per-slice pydicom decode, optional subprocess prefetch decode, persistent disk pixel cache | frame-oriented lazy data access with less Python/GIL pressure by platform/runtime | AI-PACS uses more aggressive decode mitigation because Python needs it | This is one of the places where AI-PACS is actually stronger for its environment | **REQUIRED** |

**Evidence loci**
- `lightweight_2d_pipeline.py` `_decode_slice`, `_decode_into_cache`, prefetch logic
- `qt_viewer_bridge.py` interaction-aware presentation path

**Conclusion**
- Do not rewrite the FAST decode path in this refactor.
- It is not the main remaining architectural problem.

---

### 5) Synchronization and redraw ordering

| Aspect | AI-PACS FAST | ClearCanvas | Structural difference | Why it matters under load | Classification |
|---|---|---|---|---|---|
| Sync/redraw coordination | distributed across viewer/controller/sync callbacks with guards and throttles | explicit synchronization mediator/tool coordination | AI-PACS behavior exists, but its ordering is less explicit | Tail-latency and redraw contention are harder to predict and harder to simplify | **HARMFUL** |

**Evidence loci**
- `qt_viewer_bridge.py` interaction and follow-up paths
- project sync/reference-line architecture notes in repository instructions and docs

**Conclusion**
- AI-PACS should introduce a small explicit redraw coordinator rather than keep scattering redraw intent.

---

### 6) UI update flow

| Aspect | AI-PACS FAST | ClearCanvas | Structural difference | Why it matters under load | Classification |
|---|---|---|---|---|---|
| Download progress to UI | DM progress fans out into viewer progressive updates, thumbnail overlays, completion pulses, and series-downloaded events | cleaner viewer/workspace ownership with less live download-driven UI fan-out | AI-PACS produces more UI-visible update streams from one source event | In mixed load, small repeated updates compete with interaction even when each one looks cheap alone | **HARMFUL** |

**Evidence loci**
- `home_download_service.py`
- `thumbnail_manager.py`
- `_vc_progressive.py`

**Conclusion**
- AI-PACS needs a single normalized viewer-facing progress contract.

---

### 7) Control plane

| Aspect | AI-PACS FAST | ClearCanvas | Structural difference | Why it matters under load | Classification |
|---|---|---|---|---|---|
| Work policy/control plane | `SystemLoadController` + `ui_throttle` + bridge + pipeline + progressive lifecycle each hold part of the policy story | calmer ownership with less runtime policy scattering | AI-PACS has a good emerging policy shell, but enforcement is still distributed | This makes protected-mode behavior harder to reason about and keeps admission control non-singular | **ACCIDENTAL** moving toward **HARMFUL** if not consolidated |

**Evidence loci**
- `modules/viewer/fast/system_load_controller.py`
- `modules/viewer/fast/ui_throttle.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- `_vc_progressive.py`

**Conclusion**
- Keep `SystemLoadController`.
- Add one admission/enforcement point for non-interactive work.

---

### 8) Session / tab lifecycle cleanup

| Aspect | AI-PACS FAST | ClearCanvas | Structural difference | Why it matters under load | Classification |
|---|---|---|---|---|---|
| Cleanup model | explicit service teardown, defensive disconnection, widget-alive checks | cleaner workspace-rooted disposal tree | AI-PACS has improved a lot recently, but still uses more defensive cleanup because ownership is less rooted | Good defensive work, but also a sign the ownership tree is still not crisp enough | **ACCIDENTAL** |

**Evidence loci**
- `home_download_service.py` `_ConnectionRecord`, `disconnect_widget()`, `cleanup()`
- recent B4.x hygiene notes in `docs/plans/plan.md`

**Conclusion**
- Keep the hygiene fixes.
- Long term, reduce the need for them by simplifying ownership boundaries.

---

### 9) Load-state management

| Aspect | AI-PACS FAST | ClearCanvas | Structural difference | Why it matters under load | Classification |
|---|---|---|---|---|---|
| Load state model | explicit heavy-download detection, UI lag probe, protected-mode cadence, per-series download queries | simpler lazy-loading worldview, less live overlap control | AI-PACS genuinely needs richer runtime state signals because download/view overlap is real | The signals are required; the remaining issue is too many consumers and too little centralized admission | **REQUIRED** for signals, **ACCIDENTAL/HARMFUL** for current distribution |

**Evidence loci**
- `system_load_controller.py`
- `ui_throttle.py`
- `modules/viewer/pipeline/orchestrator.py`
- `lightweight_2d_pipeline.py`

**Conclusion**
- Keep the probes.
- Collapse their consumption behind one FAST admission controller.

---

## What is genuinely necessary vs what should be removed

### Keep

- FAST/Advanced separation
- `Lightweight2DPipeline` as the core 2D render/cache owner
- disk pixel cache
- decode-service support for background isolation
- heavy-download awareness
- progressive display as a capability

### Reduce or collapse

- progressive completion authority spread
- raw DM progress fan-out into several UI consumers
- distributed redraw follow-up ordering
- policy decisions initiated from multiple call sites
- any remaining cache-like FAST helper outside the core pipeline

---

## Divergence summary by actionability

| Category | Status |
|---|---|
| Necessary divergence to preserve | FAST/Advanced split, richer FAST decode/cache path, live download-aware load probes |
| Necessary divergence to simplify | progressive growth capability itself |
| Accidental divergence to clean up | distributed lifecycle/cleanup/policy ownership |
| Harmful divergence to actively remove | duplicated terminal completion authority, UI progress fan-out, distributed redraw coordination |

---

## Bottom line

The most important result from this matrix is:

> AI-PACS does **not** need to become more like ClearCanvas in rendering mechanics. It needs to become more like ClearCanvas in **ownership discipline** while preserving the richer live-download FAST behaviors that ClearCanvas never had to carry.

That means the next architecture move is not a renderer rewrite. It is an **authority rewrite**.
