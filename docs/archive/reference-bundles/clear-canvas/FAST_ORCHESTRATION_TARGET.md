# FAST Orchestration Target

**Date:** 2026-04-15  
**Scope:** FAST mode only (`pydicom_qt`)  
**Non-goals:** no Advanced/VTK changes, no rewrite of the FAST pixel pipeline, no ClearCanvas code import

---

## Purpose

This document defines the target orchestration architecture for FAST mode after the ClearCanvas comparison and current mixed-load findings.

The design goal is simple:

> keep the current FAST renderer and caches, but remove distributed authority around progressive growth, UI-side progress churn, and redraw follow-up.

---

## Design objectives

1. **Single authority for viewer lifecycle-visible progressive state**
2. **Single admission point for non-interactive FAST work**
3. **Explicit prioritization: interaction first, growth second, cosmetics last**
4. **Singular cache ownership for 2D FAST rendering**
5. **Predictable redraw ordering for sync/reference-line follow-up**
6. **Preserve current correctness protections for live-growing series**

---

## Target model at a glance

$$
DM\ progress \rightarrow FAST\ Event\ Normalizer \rightarrow FAST\ Admission\ Controller \rightarrow
\begin{cases}
Progressive\ Lifecycle\ Owner \\
Thumbnail\ Projection \\
Redraw/Sync\ Coordinator \\
Cache\ Warm\ Requestor
\end{cases}
$$

With interaction remaining direct:

$$
User\ interaction \rightarrow QtViewerBridge.set\_slice() \rightarrow Lightweight2DPipeline
$$

Nothing non-interactive is allowed to compete with `set_slice()` without first going through the admission controller.

---

## Target components

### 1) `FastAdmissionController` — the one admission gate for non-interactive work

**Responsibility**
- decides whether non-interactive work may run now
- consumes load/policy signals from `SystemLoadController`
- normalizes priorities across work classes

**Work classes admitted through this gate**
- progressive signal handling
- progressive grow work
- thumbnail/progress UI projection
- post-completion cache warm
- sync/reference-line follow-up redraws
- diagnostic/log-heavy optional work

**Not gated here**
- direct interactive slice presentation (`set_slice()`)
- minimal settle path needed to restore exact final image

**Why**
- `SystemLoadController` should become policy brains
- `FastAdmissionController` becomes policy enforcement at the entry point

---

### 2) `FastProgressiveLifecycle` — the single progressive state owner

**Responsibility**
- owns the canonical progressive state machine per series
- owns terminal completion decision per series/epoch
- owns grow eligibility and recovery intent

**Canonical states**
- `IDLE`
- `AWAITING_FIRST_VIEW`
- `PROGRESSIVE_ACTIVE`
- `TERMINAL_PENDING_VERIFY`
- `DONE`

**Key rule**
- Layer 3/Layer 4 verification may confirm or reconcile a terminal state, but must not recreate active lifecycle state unless a **new partial cycle** is positively verified.

**Target simplification**
- legacy guard sets become compatibility shims only until removed
- all write-side state transitions flow through this owner

---

### 3) `FastEventNormalizer` — one viewer-facing download/progress contract

**Responsibility**
- receives raw DM progress/completion events
- resolves canonical series identifiers once
- coalesces/update-shapes events before they reach viewer subsystems

**Outputs**
- `progress_update(series, downloaded, total, epoch)`
- `terminal_progress(series, total, epoch)`
- `series_started(series, epoch)`

**Why**
- today one DM event fans out into several direct UI consumers
- the target is one normalized event stream, then secondary projections are derived from it

---

### 4) `ThumbnailProjection` — projection only, not lifecycle authority

**Responsibility**
- displays thumbnail state derived from normalized viewer/download state
- never decides progressive lifecycle behavior
- never emits parallel authority signals that can race the progressive owner

**Rule**
- thumbnails are a projection of state, not a state machine peer

---

### 5) `FastRedrawCoordinator` — explicit ordering for non-primary redraw work

**Responsibility**
- queues sync/reference-line/secondary repaint follow-up
- runs them after interaction-critical rendering windows
- deduplicates repeated redraw intent for the same viewer/series tick

**Why**
- this is the closest conceptual adaptation of the ClearCanvas synchronization mediator idea
- it should reduce distributed redraw pressure without touching core rendering

---

### 6) `Lightweight2DPipeline` remains the sole 2D cache/render authority

**Responsibility preserved**
- pixel decode
- frame generation
- L0/L1/L2 cache ownership
- interaction-aware prefetch
- exact/surrogate frame policy already validated for FAST mode

**Rule**
- no new FAST side-cache or cache-like helper may own 2D frame/pixel truth
- no separate booster-style cache path should participate in FAST rendering decisions

---

## Event priority model

### Priority tiers

| Tier | Work | Policy |
|---|---|---|
| P0 | direct interaction (`set_slice`, exact settle) | always immediate |
| P1 | progressive lifecycle state transitions needed for visible correctness | admitted first among non-interactive work |
| P2 | progressive grow application / visible slice-count extension | admitted when protected-mode allows |
| P3 | sync/reference-line follow-up redraw | deduped and deferred behind interaction |
| P4 | thumbnail/progress cosmetics | aggressively coalesced |
| P5 | cache warm / diagnostics | best-effort only |

### Admission rules

1. P0 never waits on P1–P5.
2. P1 may proceed during protected mode only if it is required to preserve visible correctness.
3. P2–P5 are deferrable.
4. P5 is droppable/retryable without user-visible regression.

---

## Simplified progressive completion model

### Current problem

Completion is spread across multiple safety layers plus compatibility guards.

### Target behavior

1. Progressive owner observes `downloaded >= total`.
2. Progressive owner marks `TERMINAL_PENDING_VERIFY` once for `(series, epoch)`.
3. One admitted terminal action executes:
   - final visible grow if needed
   - final metadata sync if needed
   - optional post-completion cache-warm request submission
4. Verification/sweep layers only confirm or recover if the terminal action truly failed to make the viewer consistent.
5. On success, state becomes `DONE`.

### Critical invariant

For a given `(series, epoch)`, terminal progressive actions are **one-shot**.

---

## UI update policy

### Primary rule

The viewer is the product. Everything else is a guest.

### Practical rules

- Thumbnail updates are projected at bounded cadence only.
- Completion pulses are normalized once.
- Progress text, border, and count updates do not each get independent urgency.
- Any non-interactive UI update that cannot improve visible correctness right now must wait.

---

## Cache ownership rules

### Keep
- `frame_cache`
- `pixel_cache`
- `disk_pixel_cache`
- subprocess decode service as background decode helper

### Do not add
- a second FAST-mode frame/pixel truth cache
- a second background warming authority with its own cache semantics
- ad hoc per-widget caches that drive render decisions

### Reason

ClearCanvas’s strongest lifetime lesson is not “fewer caches at all costs.” It is **single cache authority per responsibility**.

---

## Target file/ownership shape

This is a conceptual target, not a required immediate file split.

| Target component | Likely home |
|---|---|
| `FastAdmissionController` | `modules/viewer/fast/` |
| `FastEventNormalizer` | `PacsClient/.../patient_ui/` or `modules/viewer/fast/` depending ownership choice |
| `FastProgressiveLifecycle` | extracted from `_vc_progressive.py` |
| `FastRedrawCoordinator` | `modules/viewer/fast/` or patient viewer sync area |
| `ThumbnailProjection` | existing `thumbnail_manager.py` slimmed to projection role |

---

## Migration constraints

1. Preserve current progressive correctness under active download.
2. Preserve restart-after-DONE for verified new partial cycles.
3. Preserve wheel precision behavior and drag-navigation surrogate policy.
4. Preserve FAST/Advanced separation.
5. Do not rewrite `Lightweight2DPipeline` unless KPI evidence requires it.

---

## Acceptance criteria

The target architecture is achieved when:
- terminal progressive actions are emitted once per `(series, epoch)`
- all non-interactive FAST work enters through one admission controller
- thumbnail state becomes a projection, not a competing lifecycle participant
- sync/reference-line follow-up runs through an explicit redraw coordinator
- FAST cache/render truth remains centered in `Lightweight2DPipeline`
- mixed-load KPI tails improve without regressing correctness

---

## Bottom line

The target is **not** “make AI-PACS look like ClearCanvas.”

The target is:

> keep AI-PACS’s stronger live-download FAST pipeline, but give it a calmer workstation control plane: one lifecycle owner, one admission gate, one redraw coordinator, and one 2D cache authority.
