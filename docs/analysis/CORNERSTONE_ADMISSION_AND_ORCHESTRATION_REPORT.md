# Cornerstone Admission and Orchestration Report

**Date:** 2026-04-15  
**Scope:** Architecture study only; FAST mode as the AI-PACS comparison target  
**Primary reference:** Cornerstone3D official docs + `cornerstonejs/cornerstone3D` source  
**AI-PACS comparison scope:** `modules/viewer/fast/**`, `_vc_progressive.py`, `home_download_service.py`, `thumbnail_manager.py`

---

## Purpose

This report answers one narrow question:

> How does Cornerstone / Cornerstone3D avoid lag and CPU waste during concurrent loading plus active viewing, and which parts of that design are relevant to AI-PACS FAST?

This is **not** a generic viewer comparison and **not** an implementation proposal by itself. It is a code-backed architecture reading intended to reduce guesswork for the next FAST pass.

---

## Executive take

Cornerstone's biggest architectural advantage is **not** a magical decoder. It is that request admission is treated as a **first-class system** instead of a set of polite local decisions.

The most important patterns are:

1. **Central queue ownership by request class**
   - `interaction`, `thumbnail`, `prefetch`, `compute`
   - explicit per-class concurrency caps
   - fixed class dispatch order

2. **Retrieval and load/decode are split into different pools**
   - network retrieval can keep flowing while decode is busy
   - this reduces self-inflicted idle gaps

3. **Progressive loading is stage-driven, not callback-driven**
   - stages define *what* loads, *in what order*, *with which queue class*, and *at what quality*
   - later requests for the same image are chained behind earlier ones

4. **Cancellation is queue-level first, in-flight second**
   - remove stale queued work immediately
   - then cancel the load object if one exists

5. **Creation/allocation is separated from data loading**
   - volume metadata/allocation is prepared before pixel loading
   - actual pixel requests can then be reordered without reallocating the world

AI-PACS FAST already has pieces of this vocabulary (`WorkClass`, coalescing, protected mode, interaction-aware prefetch), but it still behaves more like:

- a **distributed admission shell**
- layered progressive lifecycle guards
- multiple downstream consumers of the same progress event
- direct executor submission from several call sites

That is the main divergence.

---

## Sources reviewed

### Cornerstone docs

- RequestPool Manager  
  `https://www.cornerstonejs.org/docs/concepts/cornerstone-core/requestpoolmanager/`
- Image Loaders  
  `https://www.cornerstonejs.org/docs/concepts/cornerstone-core/imageloader/`
- Cache  
  `https://www.cornerstonejs.org/docs/concepts/cornerstone-core/cache/`
- Streaming Image Volume  
  `https://www.cornerstonejs.org/docs/concepts/streaming-image-volume/`
- Streaming of Volume Data  
  `https://www.cornerstonejs.org/docs/concepts/streaming-image-volume/streaming/`
- Re-ordering Image Requests  
  `https://www.cornerstonejs.org/docs/concepts/streaming-image-volume/re-order/`
- Progressive Loading  
  `https://www.cornerstonejs.org/docs/concepts/progressive-loading/`
- Retrieve Configuration  
  `https://www.cornerstonejs.org/docs/concepts/progressive-loading/retrieve-configuration/`
- Advance Options  
  `https://www.cornerstonejs.org/docs/concepts/progressive-loading/advance-retrieve-config/`
- Usage  
  `https://www.cornerstonejs.org/docs/concepts/progressive-loading/usage/`
- Progressive Loading for non-HTJ2K data  
  `https://www.cornerstonejs.org/docs/concepts/progressive-loading/non-htj2k-progressive/`

### Cornerstone source

- `packages/core/src/requestPool/requestPoolManager.ts`
- `packages/core/src/requestPool/imageLoadPoolManager.ts`
- `packages/core/src/requestPool/imageRetrievalPoolManager.ts`
- `packages/core/src/enums/RequestType.ts`
- `packages/core/src/loaders/imageLoader.ts`
- `packages/core/src/loaders/ProgressiveRetrieveImages.ts`
- `packages/core/src/cache/classes/BaseStreamingImageVolume.ts`
- `packages/core/src/cache/classes/StreamingImageVolume.ts`
- `packages/core/src/loaders/cornerstoneStreamingImageVolumeLoader.ts`
- `packages/core/src/types/IRetrieveConfiguration.ts`
- `packages/core/src/loaders/configuration/interleavedRetrieve.ts`
- `packages/tools/src/utilities/stackPrefetch/stackPrefetch.ts`
- `packages/tools/src/utilities/stackPrefetch/stackContextPrefetch.ts`
- `packages/tools/src/utilities/stackPrefetch/stackPrefetchUtils.ts`

### AI-PACS files compared

- `modules/viewer/fast/system_load_controller.py`
- `modules/viewer/fast/ui_throttle.py`
- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- `modules/viewer/pipeline/orchestrator.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`
- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`

---

## 1. Request classes and priority

### What Cornerstone does

Cornerstone makes request class a core scheduling primitive.

- `RequestType` defines:
  - `interaction`
  - `thumbnail`
  - `prefetch`
  - `compute`
- `RequestPoolManager` stores a separate queue per request class and then priority buckets within each class.
- Lower numeric priority wins within a class.
- Dispatch order across classes is fixed in `startGrabbing()`:
  1. `Interaction`
  2. `Thumbnail`
  3. `Prefetch`
  4. `Compute`

Key evidence:
- `packages/core/src/enums/RequestType.ts`
- `packages/core/src/requestPool/requestPoolManager.ts`
  - `addRequest(...)`
  - `getNextRequest(...)`
  - `startGrabbing()`
  - `getSortedPriorityGroups(...)`

Important detail: Cornerstone does **not** merely tag requests with a class for logging. The class decides:
- which queue the request lives in
- how many simultaneous requests of that class may run
- which class gets drained first

### Why this helps responsiveness

This prevents background work from competing on equal footing with visible work.

In practice, the queue order means:

$$
Interaction > Thumbnail > Prefetch > Compute
$$

That is a very strong contract. It avoids the common failure mode where “lightweight” background work accumulates until the UI is technically busy even though nothing user-visible is improving.

### How AI-PACS differs

AI-PACS FAST has a similar vocabulary but weaker authority.

- `SystemLoadController.WorkClass` already distinguishes classes such as interaction, final render, progress update, progressive grow, prefetch, cache warm, and diagnostic work.
- `ui_throttle` centralizes helper queries.
- But admission is still decided **at the caller**.

Examples:
- `Lightweight2DPipeline._prefetch_around()` asks policy whether prefetch should be admitted, then directly submits work.
- `QtViewerBridge` interaction render path is immediate and correct, but it does not run against a central queue object that also owns non-interactive tasks.
- progressive, thumbnail, and DM progress work are still initiated from their own flows.

### AI-PACS takeaway

The next gain is not “invent more classes.” It is:

> move from **class-aware local decisions** to **class-owned central admission**.

---

## 2. Retrieval vs decode/load split

### What Cornerstone does

Cornerstone explicitly split the old single loading queue into two queues:

- `imageRetrievalPoolManager`
- `imageLoadPoolManager`

Docs state the reason clearly: previously, new retrievals waited behind decode work, which wasted available network concurrency.

Key evidence:
- RequestPool Manager docs
- `packages/core/src/requestPool/imageLoadPoolManager.ts`
- `packages/core/src/requestPool/imageRetrievalPoolManager.ts`
- `packages/dicomImageLoader/src/imageLoader/wadors/loadImage.ts`

The source pattern is:
- higher-level callers enqueue work into `imageLoadPoolManager`
- WADO-RS loading internally enqueues actual XHR/range retrieval into `imageRetrievalPoolManager`

That means retrieval and decode are not serialized by accident.

### Why this helps responsiveness

This matters during overlap because the system avoids a false bottleneck:

$$
Old:\ retrieval \rightarrow decode \rightarrow next\ retrieval
$$

vs.

$$
New:\ retrieval\ queue \parallel decode/load\ queue
$$

So even when decoding is expensive, retrieval slots can continue filling buffers and keeping the pipeline fed.

### How AI-PACS differs

AI-PACS FAST does have meaningful separation of work internally:
- direct render path
- background prefetch workers
- disk pixel cache
- subprocess decode service

But it does **not** currently expose a single authoritative split like “retrieval lane” vs “decode/load lane” to the full FAST scheduler.

The current architecture is closer to:
- caller decides whether to submit prefetch
- executor/worker handles actual decode work
- separate systems infer pressure using protected mode and lag probes

This is helpful, but it is still a policy shell rather than a hard separation of pipeline stages.

### AI-PACS takeaway

A central FAST scheduler should eventually distinguish at least:
- **visible render work**
- **download/retrieval work**
- **decode/prefetch work**
- **UI progress/thumbnail work**

Not all of these need separate thread pools immediately, but they should become separate admitted lanes.

---

## 3. Cancellation and stale-work prevention

### What Cornerstone does well

Cornerstone's first stale-work defense is simple and strong:

1. **filter queued requests out of the pool**
2. **cancel the corresponding load object if possible**

Examples:
- `imageLoader.cancelLoadImage(imageId)`
  - `imageLoadPoolManager.filterRequests(...)`
  - then `cache.getImageLoadObject(imageId)` and `cancelFn()`
- `BaseStreamingImageVolume.cancelLoading()`
  - marks loading false / cancelled true
  - clears callbacks
  - filters queued requests by `volumeId`

This is the correct priority order:
- stop future stale work first
- then attempt to stop in-flight work

### What Cornerstone does even better in progressive mode

`ProgressiveRetrieveImages` does not treat repeated quality loads as totally independent requests.

It builds per-image stage chains using `next`, so later requests for the same image are queued behind earlier ones. That means:
- a lower-quality stage can land first
- a better stage can replace it later
- later work is not blindly fired without regard to current image state
- if a better quality already exists, lower-value updates are discarded

Key evidence:
- `ProgressiveRetrieveImages.createStageRequests()`
- `ProgressiveRetrieveImages.sendRequest()`
- docs for advanced retrieve stages and nearby frames

### What Cornerstone does *not* fully solve

Cornerstone is not perfect here, and this is important.

`cancelLoadImage()` contains a `TODO` comment to cancel decoding/retrieval more completely. So its stale-work prevention is strong at the queue/load-object level, but not a universal “kill every descendant task now” mechanism.

That nuance matters because the right lesson is:

> adopt Cornerstone's **queue filtering + owned load object** model,
> not the fantasy that it has total preemption everywhere.

### How AI-PACS differs

AI-PACS FAST reduces stale work mainly through:
- protected-mode admission reduction
- coalescing intervals
- surrogate rendering during active interaction
- progressive lifecycle guards
- terminal one-shot guards

These are useful, but they are more defensive than authoritative.

The remaining issue is that stale work can still be *admitted from multiple loci*:
- progressive grow
- completion verify/sweep
- thumbnail updates
- cache warm follow-up
- prefetch submissions

### AI-PACS takeaway

The next step is a **single cancellation/invalidity contract** for non-interactive FAST work.

Each admitted work item should carry:
- series/viewer/epoch identity
- work class
- stale predicate
- cancel/drop handler

That would give AI-PACS a direct equivalent of Cornerstone's “filter queued work by identity” behavior.

---

## 4. Cache and load ownership

### What Cornerstone does

Cornerstone keeps cache/load ownership centralized.

Important concepts:
- image loaders return an **Image Load Object** with a promise and cancellation surface
- cache tracks image/volume load objects
- volume creation is separated from pixel loading
- progressive configuration is attached via metadata provider, not scattered through view code

Docs also emphasize a strong move toward **single-source-of-truth image-oriented caching** in 2.x.

At the same time, the streaming volume source still shows direct volume insertion paths and compatibility behavior. The implementation details are nuanced, but the architectural lesson is consistent:

> cache/load state has a clear owner and explicit lifecycle.

### Why this helps responsiveness

Central ownership reduces three expensive failure modes:

1. duplicate requests for the same logical asset
2. per-caller ad hoc cache policy
3. reallocation/reconstruction whenever progressive updates arrive

The streaming volume design is especially relevant:
- metadata is prefetched first
- a volume is allocated/cached before pixel data fully arrives
- actual image request order can then be changed without changing ownership

### How AI-PACS differs

AI-PACS FAST is already strong on cache specialization:
- `Lightweight2DPipeline` owns `pixel_cache` / `frame_cache`
- disk pixel cache provides L2 persistence
- foreground vs background decode split exists

That part is good.

The weaker part is **lifecycle ownership above the cache**.

The visible series state is influenced by several systems:
- pipeline cache state
- progressive lifecycle state in `_vc_progressive.py`
- orchestrator study/series download state
- download fan-out timing in `HomeDownloadService`
- thumbnail progress/UI state

So cache ownership is relatively clean, but **work ownership is not singular enough**.

### AI-PACS takeaway

Do **not** replace FAST cache ownership. `Lightweight2DPipeline` should remain the 2D cache owner.

Copy instead:
- explicit load object / request identity ownership above it
- central scheduling of cache warm / prefetch / progressive grow requests
- creation/allocation separate from progressive fill wherever practical

---

## 5. Event storm prevention

### What Cornerstone does

Cornerstone prevents storminess mostly through architecture, not just timers.

Key mechanisms:

1. **Central pool admission**
   - requests are not launched ad hoc from everywhere

2. **Queue class ordering + per-class limits**
   - reduces background crowding without every caller needing its own timer math

3. **`grabDelay` batching in request pool manager**
   - avoids pathological repeated scheduling when many requests are added quickly

4. **Stage configuration instead of per-callback improvisation**
   - progressive ordering is defined up front

5. **Pool filtering utilities**
   - prefetch helpers can clear or preserve existing pools intentionally
   - `stackPrefetch` and `stackContextPrefetch` explicitly control whether old prefetch work should survive

6. **Reordering supported as data, not as scattered logic**
   - `getImageLoadRequests()` returns request descriptors that may be interleaved or reordered externally

### Subtle but important point

Cornerstone examples sometimes render on every image-loaded or stage event. So Cornerstone is **not** “storm-proof because it never emits often.”

Its strength is that:
- the heavy work is admitted centrally
- progressive order is declarative
- stale queue entries can be filtered cheaply

That is why its event rate is less damaging than a design where several UI subsystems independently decide to do a little work “just this once.”

### How AI-PACS differs

AI-PACS currently prevents storms mostly with **distributed throttles**:
- `SystemLoadController` coalescing intervals
- `ui_throttle` helpers
- `HomeDownloadService` progress timers
- `ThumbnailManager` progress/border throttles
- `_vc_progressive.py` grow timers, terminal guards, completion verify, sweep

This has helped, but the cost is structural:
- several subsystems still own their own calming strategy
- one DM event still wakes multiple downstream consumers
- the system stays sensitive to overlap because the calm is local, not systemic

### AI-PACS takeaway

Cornerstone suggests the next move should be:

> fewer throttles as independent authorities, more throttles as one scheduler policy.

---

## 6. What to copy vs what not to copy

### Copy directly

#### A. Central request queue by class

AI-PACS should copy the principle almost directly.

Needed properties:
- one FAST scheduler object
- separate lanes for at least interaction / progress-visible / prefetch / thumbnail / background compute
- fixed draining order
- per-class concurrency caps
- per-item identity for cancellation

#### B. Queue filtering by identity

Copy the `filterRequests` idea.

AI-PACS needs a way to drop queued work by:
- viewer id
- series number
- download epoch
- work class

#### C. Stage-defined progressive order

Cornerstone's progressive stages are a big win conceptually.

AI-PACS does not need the exact same API, but it should adopt the idea that progressive fill order is:
- configured explicitly
- ranked explicitly
- not spread across timer callbacks and recovery layers

#### D. Separation of allocation from fill

Cornerstone's streaming volume design separates create/cache from load ordering.

AI-PACS FAST can reuse the concept at smaller scale:
- keep viewer ownership stable
- treat incoming slice availability as fill into an already-owned session
- avoid letting completion recovery act like a second controller

### Copy partially / adapt carefully

#### E. Retrieval vs load pool split

This is valuable, but AI-PACS should adapt it to its own pipeline.

Why partial:
- FAST is not a browser-based XHR/web-worker stack
- AI-PACS already has disk cache + subprocess decode + local filesystem semantics

So the direct port is wrong, but the architectural split is right.

#### F. Nearby-frame replication

AI-PACS already has surrogate rendering during fast interaction. Cornerstone's `nearbyFrames` is the volume-progressive cousin of that idea.

Copy only the principle:
- show stable approximations when exact data is not ready
- keep exact replacement authoritative and one-shot

Do **not** copy a new replication layer blindly if it duplicates current surrogate behavior.

### Do not copy directly

#### G. Cornerstone's exact cache topology

Cornerstone's web/runtime model is different enough that its exact cache/storage details should not be cloned mechanically.

AI-PACS already has a strong FAST cache stack:
- hot pixel/frame cache
- disk pixel cache
- optional subprocess decode service

The problem is not lack of cache types.

#### H. Browser-specific progressive transport assumptions

Features like byte-range progressive HTJ2K, JPIP-style alternate paths, and streaming decoders are useful references, but they are not the core answer to AI-PACS's present overlap issue.

The present FAST issue is mostly orchestration pressure, not missing transport tricks.

#### I. Thumbnail-above-interaction policy

Cornerstone puts `thumbnail` above `prefetch`, but AI-PACS should not automatically copy that exact rank without measurement. In FAST overlap, thumbnail work may deserve to sit *below* viewer-visible growth if it still creates jank.

---

## Direct answers to the required question groups

### Q1. How does Cornerstone classify and prioritize requests?

By explicit request class (`interaction`, `thumbnail`, `prefetch`, `compute`) plus numeric priority within class, both enforced by `RequestPoolManager` and its per-class simultaneous request caps.

### Q2. How does it split retrieval from decode/load?

By maintaining distinct `imageRetrievalPoolManager` and `imageLoadPoolManager` queues. WADO image loading uses the retrieval pool internally so network fetch can proceed independently of decode/load occupancy.

### Q3. How does it cancel or prevent stale work?

Primarily by filtering queued requests from the pool using request identity (`imageId`, `volumeId`) and then cancelling the owned load object if present. Progressive loading also chains repeated requests per image so lower-value follow-up work is not fired blindly.

### Q4. How does it keep cache/load ownership clear?

Through image load objects, central cache tracking, metadata-provider-based retrieval configuration, and volume creation separated from pixel loading. The exact cache internals are nuanced, but ownership is centralized.

### Q5. How does it reduce event storms?

By making admission central, ordering declarative, class limits explicit, and queue draining batched via `grabDelay`. It still emits progress/image events, but those events are less harmful because heavy work was already normalized before dispatch.

### Q6. What should AI-PACS copy vs avoid?

Copy:
- central request-class scheduler
- queue filtering by identity
- declarative progressive stage ordering
- stable ownership with fill-in-place semantics

Avoid copying directly:
- exact cache topology
- browser-specific transport assumptions
- any queue ranking that demotes user-visible FAST work in favor of thumbnails without measurement

---

## Comparison summary

| Topic | Cornerstone | AI-PACS FAST now | Main gap |
|---|---|---|---|
| Request classes | central queue primitive | policy vocabulary | no single queue owner |
| Priority | enforced by class + numeric bucket | helper-based admission | still caller-owned |
| Retrieval vs decode | explicit split pools | partial implicit split | not scheduler-owned |
| Cancellation | queue filter + load object cancel | guards + defers + coalescing | stale work not centrally removable |
| Progressive ordering | stage-defined, declarative | lifecycle/recovery driven | too many runtime authorities |
| Event pressure | centralized admission | distributed throttles | downstream fan-out remains |
| Reordering | supported as request descriptors | mixed local logic | no single order contract |

---

## Most important conclusion for AI-PACS

Cornerstone's lesson is not “use more progressive loading.” AI-PACS already does progressive work.

The real lesson is:

> Progressive work must be **scheduled as data** by one owner, not continuously renegotiated by several well-meaning subsystems.

That is the cleanest explanation for why Cornerstone's overlap model stays calmer.

---

## Recommended interpretation for the next FAST pass

If AI-PACS wants the highest ROI next pass, it should treat Cornerstone as evidence for this refactor order:

1. central FAST request scheduler
2. queue identity + cancellation/drop model
3. collapse progressive terminal/grow authority behind the scheduler
4. move DM progress and thumbnail updates behind one viewer-facing admitted stream
5. only then tune lane limits and radius/cadence numbers

In short:

> Stop tuning the traffic lights one intersection at a time. Build the roundabout.
