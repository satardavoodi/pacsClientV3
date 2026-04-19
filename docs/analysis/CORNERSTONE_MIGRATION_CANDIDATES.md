# Cornerstone Migration Candidates

**Date:** 2026-04-15  
**Scope:** FAST viewer architecture candidates only  
**Goal:** rank the most valuable Cornerstone-inspired refactor targets for AI-PACS

---

## Ranking criteria

Candidates are ranked by expected benefit to:
- overlap responsiveness during active viewing + download
- stale-work reduction
- CPU reduction from unnecessary admitted work
- architecture simplification

They are **not** ranked by implementation ease.

---

## Ranked candidate list

### C1 — FAST central scheduler with request classes

**ROI:** Very high  
**Confidence:** High  
**Cornerstone inspiration:** `RequestPoolManager`, `RequestType`, `imageLoadPoolManager`, `imageRetrievalPoolManager`

#### What it is

Create a FAST-specific scheduler that becomes the single legal owner for non-interactive work admission.

Possible lanes:
- `interaction`
- `final_render`
- `progressive_visible`
- `progress_bookkeeping`
- `thumbnail`
- `prefetch`
- `cache_warm`
- `diagnostic`

#### Why it matters most

This closes the main architectural gap identified by the Cornerstone study:

> AI-PACS has request classes, but not request-class ownership.

Without this candidate, every later fix remains a local improvement rather than a systemic one.

#### Minimal first version

- in-memory priority queues per class
- fixed drain order
- per-class concurrency / in-flight caps
- identity fields: `viewer_id`, `series_number`, `epoch`, `work_class`
- stale predicate / drop reason recording
- metrics counters for enqueue, admit, defer, drop, complete

#### Risks

- can become over-engineered if it tries to replace all current code at once
- must not slow the immediate interaction path

#### Guardrail

Keep `interaction` and exact visible render on a zero-ceremony fast path while still registering them with the scheduler for accounting.

---

### C2 — Progressive lifecycle rewritten as staged work descriptors

**ROI:** Very high  
**Confidence:** High  
**Cornerstone inspiration:** `ProgressiveRetrieveImages`, `RetrieveStage`, `IRetrieveConfiguration`, staged priorities

#### What it is

Refactor `_vc_progressive.py` so progressive behavior is expressed as a bounded sequence of scheduler-managed stages instead of a runtime negotiation among:
- inflight guards
- done guards
- completion guard sets
- verify timers
- sweep recovery
- terminal one-shot protections

#### Example stage model for AI-PACS

1. `initial_visible`
2. `grow_visible`
3. `terminal_reconcile`
4. `post_terminal_warm`

Only one stage family should be active per series epoch.

#### Why it ranks this high

The current progressive path is correctness-hardened but still expensive to reason about. Cornerstone's big win is not that it has no progressive complexity; it is that progressive order is declared up front.

#### Risks

- regressions in rare recovery scenarios if existing safety nets are removed too quickly
- temptation to preserve every old callback path “just in case,” which would keep the complexity alive

#### Guardrail

Migrate by wrapping existing terminal/verify/sweep actions as scheduler stages before deleting old direct triggers.

---

### C3 — Queue filtering and stale-work cancellation by identity

**ROI:** High  
**Confidence:** High  
**Cornerstone inspiration:** `filterRequests(...)`, `cancelLoadImage(...)`, `cancelLoading()`

#### What it is

Introduce a generic stale-work drop system.

Every background work item should know:
- which viewer it belongs to
- which series it belongs to
- which download epoch or lifecycle epoch it belongs to
- whether it is still relevant

#### Why it matters

AI-PACS currently avoids some bad work through admission reduction and coalescing, but it still lacks a strong equivalent of:

> “remove everything queued for this logical asset, now.”

That is the cleanest direct import from Cornerstone.

#### Early win opportunities

- drop prefetch when viewed series changes
- drop thumbnail work older than latest admitted state
- drop progressive grow or warm tasks once terminal close is finalized
- drop queued DM-derived UI tasks for superseded epochs

#### Risks

- if identity is underspecified, valid work may be dropped accidentally

#### Guardrail

Start with additive logging: record what would have been dropped before making every drop destructive.

---

### C4 — Split FAST background lanes into retrieval / decode / UI-update classes

**ROI:** High  
**Confidence:** Medium  
**Cornerstone inspiration:** separate retrieval and load pools

#### What it is

Represent the background stack more explicitly:
- retrieval / availability work
- decode / transform work
- UI-side progress / thumbnail work

This does **not** require a literal copy of Cornerstone's browser/XHR separation. It means AI-PACS should stop treating all non-visible background work as one soft mass.

#### Why it matters

AI-PACS currently knows a lot about system pressure, but it does not yet express a firm lane model for overlap.

That keeps the system reliant on local helper rules.

#### Risks

- false precision: too many lanes too soon
- confusion between download-manager transport and viewer decode lanes

#### Guardrail

Start with three coarse non-interactive buckets only:
- `visible_support`
- `decode_prefetch`
- `ui_cosmetic`

If that helps, split further later.

---

### C5 — Single viewer-facing progress envelope

**ROI:** High  
**Confidence:** High  
**Cornerstone inspiration:** central request admission + data-defined staging

#### What it is

Normalize DM progress into one admitted series-update envelope that downstream consumers use after scheduling.

Potential contents:
- series id
- downloaded count / total
- current lifecycle epoch
- visibility state
- whether a visible grow is actually needed
- whether thumbnail state changed materially

#### Why it matters

Today one DM event can still trigger multiple UI-facing actions across:
- progressive viewer updates
- completion pulse behavior
- thumbnail overlays / borders
- download bookkeeping

The overlap problem improves when that becomes one admitted event stream, not many cousin streams.

#### Risks

- could become a god-object if it carries unrelated UI concerns

#### Guardrail

Keep the envelope schema narrow; let consumers read, not mutate.

---

### C6 — Scheduler-owned thumbnail lane

**ROI:** Medium-high  
**Confidence:** High  
**Cornerstone inspiration:** `thumbnail` request class

#### What it is

Move thumbnail progress/border/overlay work out of local independent timing control and into a scheduler-owned lane with explicit defer/drop rules.

#### Why it matters

Thumbnail work is currently better than before, but still structurally independent. Under overlap, that means it can remain “well throttled” and still be one source too many.

#### Suggested rank

In AI-PACS FAST, thumbnail work should probably sit **below viewer-visible progressive work** and often below final visible renders.

#### Risks

- user may perceive stale sidebar state if lane is too aggressively deferred

#### Guardrail

Preserve correctness updates immediately in model state, but defer paint-heavy work.

---

### C7 — Reorderable request descriptors for prefetch/grow/warm

**ROI:** Medium-high  
**Confidence:** Medium-high  
**Cornerstone inspiration:** `getImageLoadRequests()` and external reorder/interleave support

#### What it is

Represent work as descriptors that can be reordered before admission:
- exact slice render
- neighborhood prefetch
- grow to current known bound
- post-terminal warm
- thumbnail refresh

#### Why it matters

This is how AI-PACS can stop hardcoding order in callback topology.

#### Risks

- if descriptor creation remains spread across many files, this just renames the mess

#### Guardrail

Descriptor generation should be centralized in a very small number of components:
- pipeline
- progressive controller
- download progress bridge

---

### C8 — Explicit approximate-fill policy for non-terminal gaps

**ROI:** Medium  
**Confidence:** Medium  
**Cornerstone inspiration:** `nearbyFrames` replication, progressive low-quality-first strategies

#### What it is

Formalize when AI-PACS may show an approximation while exact data is pending.

This already exists informally via fast-interaction surrogate behavior. The candidate is to make that concept part of the scheduler/stage model rather than an isolated optimization.

#### Why it matters

Approximate-fill is useful only when:
- it improves perceived continuity
- it does not create a second ownership system

#### Risks

- can become visually confusing if both progressive fill and surrogate fill compete

#### Guardrail

One approximation authority only. If the active series epoch already has a progressive surrogate policy, do not layer another one on top.

---

### C9 — Stable create-then-fill session model for viewed series

**ROI:** Medium  
**Confidence:** Medium-high  
**Cornerstone inspiration:** streaming volume allocation before pixel fill

#### What it is

Make viewed-series ownership more explicitly session-based:
- viewer session created once for series epoch
- slice arrivals fill owned session
- completion actions close session once
- verification may observe but should not recreate controller state casually

#### Why it matters

This helps AI-PACS move away from the feeling that completion recovery is a second controller instead of a verifier.

#### Risks

- may touch several progressive assumptions at once

#### Guardrail

Apply only after C2 or in parallel with it.

---

### C10 — Transport-level progressive retrieve tricks

**ROI:** Low for current problem  
**Confidence:** Medium  
**Cornerstone inspiration:** byte-range, streaming HTJ2K, alternate low-resolution paths

#### What it is

Adopt more advanced partial transport or alternate low-resolution retrieval strategies.

#### Why it ranks low now

Interesting, but it does not attack the main diagnosed cause in AI-PACS FAST today.

Current FAST pain is still:
- stale work
- distributed admission
- progress fan-out
- progressive lifecycle over-authority

not “we need better remote transport semantics first.”

#### Recommendation

Keep as a later optimization track, not next-pass core work.

---

## Suggested migration phases

### Phase 1 — control-plane foundation

- C1 central scheduler
- C3 stale-work queue filtering
- instrumentation for enqueue/admit/drop/defer per class

### Phase 2 — progressive simplification

- C2 staged progressive descriptors
- C9 stable create-then-fill session handling
- C7 reorderable work descriptors

### Phase 3 — UI fan-out calming

- C5 single progress envelope
- C6 scheduler-owned thumbnail lane

### Phase 4 — deeper pipeline separation

- C4 coarse retrieval/decode/UI lane split
- C8 explicit approximate-fill policy if still needed

### Phase 5 — optional transport research

- C10 transport-level progressive retrieval enhancements

---

## Candidates explicitly not recommended as the next-pass center

### Rebuilding the FAST cache stack

Not recommended. The current evidence does not point to cache ownership as the main overlap failure.

### Adding more one-off throttles

Not recommended. They may help locally, but they prolong the distributed-authority model.

### Large rewrite of Advanced mode together with FAST

Not recommended. The evidence and user preference both point to FAST-first focus.

---

## Decision summary

| Candidate | Priority | Next pass? |
|---|---|---|
| C1 FAST central scheduler | 1 | **Yes** |
| C2 Progressive staged descriptors | 2 | **Yes** |
| C3 Queue filtering + stale cancel | 3 | **Yes** |
| C5 Single progress envelope | 4 | **Yes** |
| C6 Scheduler-owned thumbnail lane | 5 | **Likely yes** |
| C4 Background lane split | 6 | **Maybe, scoped** |
| C7 Reorderable request descriptors | 7 | **Likely yes** |
| C9 Stable create-then-fill session model | 8 | **Maybe, with C2** |
| C8 Explicit approximate-fill policy | 9 | **Only if needed** |
| C10 Transport-level progressive tricks | 10 | **No, not yet** |

---

## Final recommendation

If only one sentence survives this whole document, it should be this:

> The next FAST pass should copy Cornerstone's **request ownership model** before copying any more of its loading tricks.

That is the part most likely to reduce both lag and wasted CPU in AI-PACS's actual problem shape.