# Cornerstone to AI-PACS Action Matrix

**Date:** 2026-04-15  
**Scope:** FAST viewer only  
**Intent:** translate Cornerstone findings into concrete next-pass choices

---

## How to read this matrix

- **Adopt** = worth implementing as a near-term FAST refactor target
- **Adapt** = the principle is useful, but the exact Cornerstone mechanism should not be copied literally
- **Reject** = not a good direct fit for current FAST needs

ROI ranking here is about likely reduction in overlap lag and stale CPU, not implementation ease.

---

## Matrix

| Rank | Cornerstone pattern | Evidence | AI-PACS current locus | Recommendation | Why |
|---|---|---|---|---|---|
| 1 | Central request-pool by class | `requestPoolManager.ts`, `RequestType.ts` | `system_load_controller.py`, `ui_throttle.py`, caller-side admissions | **Adopt** | Biggest gap: AI-PACS has class vocabulary but no singular admission owner |
| 2 | Queue filtering by identity before in-flight cancel | `filterRequests`, `cancelLoadImage`, `cancelLoading` | `_vc_progressive.py`, `lightweight_2d_pipeline.py`, follow-up timers | **Adopt** | Best direct way to kill stale queued work before it burns CPU |
| 3 | Declarative progressive stage ordering | `ProgressiveRetrieveImages.ts`, `IRetrieveConfiguration.ts`, advanced retrieve docs | `_vc_progressive.py` layered runtime control | **Adopt** | Replaces runtime negotiation with explicit ordered work plan |
| 4 | Split retrieval pool from load/decode pool | request-pool docs, `imageRetrievalPoolManager.ts`, WADO loadImage | pipeline/decode service/orchestrator separation is partial and implicit | **Adapt** | Strong architectural lesson, but exact browser/XHR structure should not be ported literally |
| 5 | Stable allocation first, fill later | streaming volume docs, `BaseStreamingImageVolume.ts` | viewer session + progressive series lifecycle | **Adapt** | Good model for keeping ownership calm while slices arrive |
| 6 | Reorderable request descriptors | `getImageLoadRequests`, re-order docs, volumePriorityLoading example | `_grow_progressive_fast` + progress fan-out + local order decisions | **Adopt** | Lets AI-PACS represent “what should happen next” as a queue, not callback folklore |
| 7 | Nearby-frame replication for early completeness | `nearbyFrames`, `interleavedRetrieve.ts` | FAST surrogate rendering during interaction | **Adapt** | Principle matches current surrogate strategy, but direct duplication risks overlap/confusion |
| 8 | Preserve or selectively clear prefetch pool | `stackPrefetch.ts`, `stackContextPrefetch.ts` | current prefetch radius/admission logic | **Adopt** | AI-PACS needs finer stale-prefetch cleanup than simple admit-or-don't-admit |
| 9 | Metadata-provider-based retrieval config | progressive usage docs | progressive order is encoded in runtime logic and timers | **Adapt** | Useful idea: config-like progression definition, even if not via metadata provider |
| 10 | Browser transport-specific progressive retrieve options | byte-range / streaming / JPIP / alternate paths | local DICOM files, FAST disk cache, subprocess decode | **Reject** for current pass | Not the bottleneck class we are trying to fix |
| 11 | Exact Cornerstone cache topology | cache docs + streaming internals | `Lightweight2DPipeline` + disk pixel cache + decode service | **Reject** | FAST cache ownership is already competent; orchestration is weaker than cache design |
| 12 | Thumbnail above prefetch as a universal ranking | `RequestType` class order | thumbnail fan-out currently still causes pressure in FAST overlap | **Adapt cautiously** | AI-PACS may need viewer-visible grow to outrank thumbnail cosmetics |

---

## Best matches by AI-PACS subsystem

### `modules/viewer/fast/system_load_controller.py`

**Current strength**
- already defines useful work classes and coalescing ideas

**Gap**
- policy is advisory; it does not own the queue

**Cornerstone lesson**
- move from `should_admit(...)` as a helper to `submit(...)` as the only legal path for non-interactive work

**Recommendation**
- turn the load controller into the policy brain behind a new FAST scheduler rather than the final integration point itself

---

### `modules/viewer/fast/lightweight_2d_pipeline.py`

**Current strength**
- good cache ownership
- strong fast-interaction behavior
- prefetch already class-aware

**Gap**
- prefetch and some background work are still submitted directly from the pipeline

**Cornerstone lesson**
- pipeline should describe desired work, not own global admission order

**Recommendation**
- pipeline emits request descriptors like:
  - `exact-final-render`
  - `prefetch-slice`
  - `warm-neighborhood`
  - `drop-stale-if(epoch mismatch)`

---

### `modules/viewer/fast/qt_viewer_bridge.py`

**Current strength**
- immediate interaction path is mostly correct
- lag probe and fast-interaction boundaries already exist

**Gap**
- no hard barrier between interaction work and accumulated secondary work

**Cornerstone lesson**
- user-driven work should sit in the top queue class with minimal dependence on background cleanup

**Recommendation**
- keep exact visible render immediate/highest, but ensure all non-essential follow-up work is scheduler-routed and cancelable

---

### `_vc_progressive.py`

**Current strength**
- correctness hardening is substantial
- terminal one-shot protections already exist

**Gap**
- progressive lifecycle still behaves like a multi-authority runtime negotiation

**Cornerstone lesson**
- progressive order should be expressed as stages/requests, not re-derived from multiple late callbacks

**Recommendation**
- replace free-form grow/finalize/verify/sweep authority with scheduler-managed progressive tickets:
  - `initial-display`
  - `incremental-grow`
  - `terminal-reconcile`
  - `post-terminal-warm`

Only one of those should be live per series epoch at a time.

---

### `home_download_service.py`

**Current strength**
- progress coalescing already exists
- widget disconnect/cleanup hygiene exists

**Gap**
- one download event still fans out to multiple UI consumers downstream

**Cornerstone lesson**
- normalize work once, then route admitted work to consumers

**Recommendation**
- convert DM progress into a single scheduler-fed “series update envelope” that downstream consumers subscribe to after admission, not before it

---

### `thumbnail_manager.py`

**Current strength**
- local coalescing/throttling already present

**Gap**
- thumbnail behavior remains an independent UI authority

**Cornerstone lesson**
- thumbnails belong to a lower class lane, not an independent timing system

**Recommendation**
- thumbnail repaint/progress should become lane work owned by the FAST scheduler with clear drop/defer rules

---

## What AI-PACS should do next, in order

### 1. Introduce a FAST scheduler

**Adopt from Cornerstone:** request-pool ownership  
**Why first:** without this, every other improvement stays local

Minimum responsibilities:
- accept work item descriptors
- own class ordering
- own concurrency caps
- drop stale queued work by identity
- expose metrics per class and per drop reason

---

### 2. Convert progressive flow into stage-like tickets

**Adopt from Cornerstone:** progressive stages and chained requests  
**Why second:** progressive lifecycle is the highest structural pressure source in FAST overlap

AI-PACS equivalent stages might be:
- `initial-visible`
- `grow-visible`
- `terminal-close`
- `background-warm`

---

### 3. Separate visible progress from cosmetic progress

**Adopt from Cornerstone:** request-class distinction  
**Why third:** viewer-visible updates and thumbnail cosmetics should not share the same authority level

Suggested first ranking for AI-PACS:

$$
interaction > final\ render > progressive\ visible > progress\ bookkeeping > thumbnail > prefetch > cache\ warm > diagnostic
$$

This is intentionally *not* a literal copy of Cornerstone's thumbnail rank.

---

### 4. Add queue filtering by series/viewer/epoch

**Adopt from Cornerstone:** `filterRequests(...)`  
**Why fourth:** it gives an immediate stale-work control surface before deeper refactors land

Examples of droppable work:
- prefetch for series no longer viewed
- progressive grow for superseded epoch
- thumbnail border/progress jobs older than latest admitted state
- post-terminal warm for an already closed cycle

---

### 5. Only then retune caps and cadences

**Adopt from Cornerstone:** per-class concurrency control  
**Why last:** tuning is only meaningful once ownership is centralized

Do not spend the next pass mostly changing:
- prefetch radius numbers
- timer intervals
- debounce constants

unless they are governed by the new owner.

---

## What not to let the next pass become

### Not this

- another spread of special-case timers in `_vc_progressive.py`
- another branch in `ui_throttle` for a new overlap corner case
- another local “if heavy download active then maybe skip X” rule added at the call site
- another cache layer introduced to mask stale admission

### Do this instead

- one request owner
- one progressive plan owner
- one stale-work drop mechanism
- fewer local negotiations

---

## Quick decision table

| Candidate move | Do it? | Reason |
|---|---|---|
| Add a FAST scheduler object | **Yes** | highest ROI, matches primary Cornerstone advantage |
| Rebuild `Lightweight2DPipeline` cache stack | **No** | cache is not the main gap |
| Add more local defer rules to progress/thumbnail code | **No** | treats symptoms, not authority fragmentation |
| Add request identity and drop filters | **Yes** | direct stale-work reduction |
| Represent progressive work as staged descriptors | **Yes** | cleaner than layered callbacks |
| Copy Cornerstone's browser transport tricks | **Not now** | wrong problem class for current FAST bottleneck |
| Put thumbnails ahead of everything except interaction | **Probably no** | FAST overlap needs viewer-visible work prioritized more carefully |

---

## Bottom line

If the next FAST pass is limited, the most faithful Cornerstone-inspired move is:

> Build the scheduler first, then migrate progressive, thumbnails, and prefetch behind it.

That is the shortest path from today's distributed admission model to a calmer overlap architecture.