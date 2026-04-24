# FAST Task Concurrency And ClearCanvas Comparison

**Date:** 2026-04-17  
**Scope:** AI-PACS FAST viewer live overlap behavior vs local ClearCanvas workstation task-ownership model  
**AI-PACS workspace:** `C:\AI-Pacs codes\aipacs-pydicom2d`  
**AI-PACS live log reviewed:** `C:\Users\vahid\OneDrive\Desktop\log 56 .txt`  
**ClearCanvas reference checkout:** `C:\AI-Pacs codes\ClearCanvas-master\ClearCanvas-master`

---

## Purpose

This document answers a very specific architecture question:

- if decode, download, and cache each look acceptable on their own, why does the viewer still lag under overlap?
- how many things are actually running at the same time during download and viewing?
- which parts are truly isolated in other processes, and which parts still collapse back into one main pressure point?
- how does that compare to the way ClearCanvas organizes the same kind of workstation work?

The intent is not to score individual components in isolation. The intent is to understand team behavior: who is on the field, who is competing for the ball, and which work should not be allowed to behave like a peer of visible interaction.

---

## Truthfulness Boundaries

- **AI-PACS findings below include live runtime evidence** from `log 56 .txt`.
- **ClearCanvas findings below are based on static source inspection only** in the local ClearCanvas checkout.
- This document **does not claim** that a real ClearCanvas runtime benchmark was executed in this pass.
- Where this document compares ClearCanvas behavior, it compares **task ownership and concurrency structure**, not an invented runtime number.

---

## Sources Reviewed

### AI-PACS docs and plans

- `docs/plans/performance/FAST_VIEW_PERFORMANCE_EXECUTION_PLAN.md`
- `docs/plans/performance/FAST_STORM_AND_PERFORMANCE_PLAN_vNEXT.md`
- `docs/performance/PERFORMANCE_STATUS.md`
- `docs/performance/WORKLOAD_MODEL.md`
- `docs/analysis/ORCHESTRATION_ROOT_CAUSES.md`
- `docs/analysis/CLEARCANVAS_WORKSTATION_COMPARISON.md`
- `docs/analysis/CLEARCANVAS_KPI_MAPPING.md`
- `docs/analysis/CLEARCANVAS_DIVERGENCE_MATRIX.md`

### AI-PACS runtime and code

- `C:\Users\vahid\OneDrive\Desktop\log 56 .txt`
- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/decode_service.py`
- `modules/download_manager/workers/download_process_worker.py`
- `modules/download_manager/workers/download_process_entry.py`
- `modules/download_manager/storage/database_manager.py`
- `PacsClient/utils/diagnostic_logging.py`

### ClearCanvas source

- `ImageViewer/StudyManagement/StudyLoader.cs`
- `ImageViewer/StudyManagement/WeightedWindowPrefetchingStrategy.cs`
- `ImageViewer/Thumbnails/ThumbnailLoader.cs`
- `ImageViewer/Tools/Synchronization/SynchronizationToolCoordinator.cs`
- `ImageViewer/Volumes/VolumeCache.cs`

---

## Executive Conclusion

AI-PACS is not losing mainly because "too many subprocesses" are running. In the reviewed overlap session, only **two OS processes** were clearly active:

1. the **main application process**
2. one **download subprocess**

The real problem is that too many logically separate jobs still collapse back into the **main process coordination surface**:

- visible `set_slice()` work
- cache miss decode and window/level finish work
- progressive event handling
- prefetch scheduling and cache follow-up
- UI state updates
- some DB access and queue handling

So the architecture looks parallel from far away, but under load it still behaves like:

- **one heavy foreground process cluster**
- **one helper download process**
- several minor side threads feeding work back into the same UI/event-loop domain

That is why individual subsystems can look "good" on their own while the combined experience still feels unstable.

ClearCanvas solves this more calmly, not because every part is faster in isolation, but because it gives each class of work a narrower role:

- study loading is separated from pixel loading
- prefetch uses owned background pools with deliberately lower priorities
- thumbnails are queue/projection work, not lifecycle peers
- redraw follow-up is mediated by one coordinator instead of many direct drawers

The practical conclusion is:

- **AI-PACS needs less peer behavior and more controlled admission**
- **subprocesses alone are not the cure**
- the next wins will come from **ownership collapse, stale-work filtering, and foreground/background separation**

Reviewed against `docs/plans/performance/FAST_VIEW_PERFORMANCE_EXECUTION_PLAN.md`, the current repo state is aligned with **entering Phase 4**, not with treating Phase 3 as still absent. The controller shell for non-interactive admission already exists in-place through `SystemLoadController` + `ui_throttle`; the remaining gap is hardening and measurement proof, which should be handled **after Phase 4**, not before it.

---

## AI-PACS Runtime Findings From `log 56`

### Observed OS processes

The log explicitly showed only these process IDs:

- `pid=22612` -> main application process
- `pid=33464` -> download subprocess

No separate warmup subprocess was active in this session, and no independently active decode subprocess was visible in the log. The decode service exists in the codebase, but in this capture it did not appear as a separately logged active worker process.

### Observed thread IDs

The log showed at least these thread IDs:

- `tid=4468`
- `tid=19244`
- `tid=25016`
- `tid=25936`
- `tid=28852`

This means the session was concurrent, but the concurrency was still concentrated around a very small number of OS execution domains.

### Logical tasks happening during overlap

Even though only two OS processes were clearly visible, the workload included several logical tasks:

1. **Main process visible interaction**
   - `QtViewerBridge.set_slice()`
   - slice preparation
   - display handoff
   - window/level finish work
   - visible presentation timing

2. **Main process orchestration and event-loop work**
   - progressive callbacks
   - stack-drag settle behavior
   - UI signaling
   - admitted work handoff and callback delivery

3. **Main process background helper work**
   - prefetch scheduling
   - cache follow-up
   - frame/decode futures
   - bridge-side support work

4. **Download subprocess work**
   - network request
   - response handling
   - file write
   - database update
   - progress/completion messages back to the parent

5. **Minor side work**
   - DB touches in the main process
   - resource monitor samples
   - thumbnail/progressive state notifications

So the user-visible session was not "many equally independent subprocesses." It was mostly **one crowded main process plus one active helper process**.

### Measured runtime signals

#### Foreground `set_slice` behavior

- `set_slice_count = 22`
- `avg_total_ms = 34.7`
- `avg_decode_ms = 23.7`
- `avg_wl_ms = 6.0`
- `max_total_ms = 55.3`

Representative slow slices in the log:

- `idx=60 total=35.0 decode=0.0 wl=0.0 prepare_ms=32.6 ui_lag_ms=318.5`
- `idx=78 total=45.2 decode=34.7 wl=6.2`
- `idx=86 total=41.2 decode=32.1 wl=5.7`
- `idx=91 total=46.1 decode=35.5 wl=6.5`
- `idx=103 total=55.3 decode=44.8 wl=7.1`

Interpretation:

- some hitches are still decode-driven
- at least one hitch was **not decode-driven** and was instead dominated by prepare/UI lag
- this matches the storm thesis: not all bad frames come from raw decode

#### FAST stage timing

- `stage_count = 22`
- `avg_prepare_ms = 2.0`
- `avg_frame_ms = 30.1`
- `avg_display_ms = 2.5`
- `avg_ui_lag_ms = 85.1`
- `max_ui_lag_ms = 318.5`

Interpretation:

- raw stage pieces are not individually catastrophic
- the event-loop side still suffers large lag spikes
- the UI-lag spikes are too large to explain as "decode only"

#### Download subprocess timing

- `request_total_count = 4`
- `avg_request_total_ms = 1466.4`
- `max_request_total_ms = 1981.3`
- `response_parse_count = 4`
- `avg_response_parse_ms = 20.5`
- `max_response_parse_ms = 30.6`
- `header_recv_count = 4`
- `avg_header_recv_ms = 115.3`
- `max_header_recv_ms = 150.0`

Interpretation:

- the download subprocess is doing real work and holding system resources for long enough to matter
- but its own parse/header work is not the main lag source
- its influence is mostly indirect: CPU, disk, DB, and queue pressure that feed back into the main process

#### Resource monitor samples

From the log:

- `resource_count = 12`
- `avg_cpu_pct = 73.7`
- `max_cpu_pct = 150.2`
- `min_cpu_pct = 15.3`
- high CPU samples count `= 5`
- average of high CPU samples `= 123.3`

Observed main-process sample sequence:

- `38.5`
- `60.6`
- `139.4`
- `150.2`
- `121.3`
- `40.0`
- `15.3`
- `20.9`
- `84.2`
- `121.5`
- `52.3`
- `40.4`

Important limitation:

- the current resource summary comes from `psutil.Process()` in `PacsClient/utils/diagnostic_logging.py`
- that means the sampled CPU is primarily the **current process**
- it does **not** give a reliable whole-system breakdown across child processes

So the log proves that the main process gets hot, but it does not yet give a full per-process CPU budget for every child.

### Log-side responsibility estimate for user-visible lag

This estimate is based on the live log and should be treated as a practical attribution model, not a mathematically exact profiler result.

| Area | Approximate responsibility |
| --- | ---: |
| Main-process visible slice work | 45% |
| Main-process orchestration and event-loop lag | 25% |
| Main-process prefetch and cache follow-up | 15% |
| Download subprocess shared-resource pressure | 10% |
| Progressive, thumbnail, and DB side work | 5% |

Key point:

- roughly **85%** of the user-visible pain still lands in or very near the **main process coordination surface**

That is why adding isolated workers does not automatically remove interference.

---

## Why The Existing Subprocess Split Does Not Fully Protect The Viewer

Subprocesses help with some categories of contention, but they do **not** isolate:

- CPU core contention
- memory bandwidth contention
- disk I/O contention
- SQLite and file-path coordination pressure
- Qt signal/event-queue pressure
- parent-process callback and repaint pressure

In AI-PACS specifically:

- the download worker is separate, but its progress/completion still comes back through queue polling and signals into the parent
- foreground cache misses can still lead to in-process decode or finish work near the visible path
- prefetch helpers and cache follow-up still run close enough to the main pipeline to compete with it
- DB activity still exists on both sides of the process boundary

So "running in different subprocesses" is only a partial separation. The visible viewer still pays for shared resources and for callback traffic that re-enters the main process.

---

## ClearCanvas Concurrency Model From Source

## Important Boundary

The ClearCanvas findings below come from source inspection, not from a real ClearCanvas runtime capture in this pass.

### 1. Study loading is separated from pixel loading

In `ImageViewer/StudyManagement/StudyLoader.cs`, the loader contract explicitly avoids pushing pixel loading into the basic SOP enumeration path.

The important design idea is:

- identify the next SOP/data source
- create/own loading state
- do not let that path become a hidden pixel-data hot path

That makes the "what should be shown next?" decision calmer than a design where every next-step decision can accidentally expand into heavy pixel work.

### 2. Prefetch has explicit ownership and lower-priority pools

In `ImageViewer/StudyManagement/WeightedWindowPrefetchingStrategy.cs`, ClearCanvas creates explicit pools for background retrieval and decompression:

- retrieval concurrency: `5`
- decompression concurrency: `1`
- retrieval thread priority: `BelowNormal`
- decompression thread priority: `Lowest`

This matters a lot.

The ClearCanvas model is not simply "run more workers." It is:

- define prefetch as owned background work
- keep it below foreground importance
- cap decompression more tightly than retrieval
- use a weighted window around the viewer instead of treating all pending work as equal

That is much closer to a workstation discipline model than a free-form helper model.

### 3. Thumbnails are queue work, not lifecycle peers

In `ImageViewer/Thumbnails/ThumbnailLoader.cs`:

- thumbnail requests go into one pending list
- one loading loop drains that list
- cancellation removes pending requests
- the loader does not behave like a peer authority to visible image lifecycle

This is an important contrast to AI-PACS storm behavior.

In the calmer model:

- thumbnails are a projection of state
- they are not a repeated source of urgency
- they do not keep asking the rest of the system to re-prove progress

### 4. Redraw follow-up is centrally mediated

In `ImageViewer/Tools/Synchronization/SynchronizationToolCoordinator.cs`, ClearCanvas explicitly centralizes synchronization-driven redraw behavior.

The key point from that code is simple:

- spatial locator
- stacking synchronization
- reference lines

should not each directly force repeated draw behavior independently.

Instead, one coordinator decides what should actually redraw.

This directly matches the main AI-PACS pain point where several "helpful" callbacks still behave like peers and create duplicate follow-up work.

### 5. Cache ownership is explicit

In `ImageViewer/Volumes/VolumeCache.cs`, ClearCanvas uses a reference-managed cache model with explicit ownership and release discipline.

The important lesson is not the exact class shape. The lesson is:

- one cache owner
- explicit lifetime
- no casual peer authority over cache identity

That same ownership discipline is what AI-PACS still needs in its progressive/admission/redraw paths.

---

## Side-By-Side Comparison

| Area | AI-PACS current behavior | ClearCanvas reference behavior | Why it matters |
| --- | --- | --- | --- |
| Process shape | One hot main process plus one active download subprocess in the reviewed run | Mostly one workstation process with deliberately owned background pools | AI-PACS looks distributed but still collapses into one hot coordination zone |
| Foreground ownership | Visible interaction shares space with helper callbacks and follow-up work | Visible study/view ownership is calmer and less peer-driven | Foreground path stays easier to protect |
| Loading contract | Some work classes still blend "what is next?" with "do more work now" | `StudyLoader` separates source progression from heavy pixel work | Fewer surprise expansions of visible-path work |
| Prefetch strategy | Helper work exists, but admission remains more fragmented | One weighted prefetch strategy with explicit lower-priority pools | Background work is less likely to fight the viewer |
| Decompression policy | Decode/prefetch helper behavior can still compete with foreground timing | Retrieval and decompression have separate owned pools and tighter decompression concurrency | Background decompression is less able to stampede |
| Thumbnail behavior | Historically more coupled to progress churn and peer signaling | Queue/projection loader with cancellation | Thumbnail work stays cheap and secondary |
| Redraw/sync behavior | Multiple subsystems can still trigger follow-up redraw pressure | One synchronization coordinator arbitrates redraw work | Duplicate redraw pressure drops |
| Cache ownership | FAST render/cache authority is strong, but control-plane ownership still fragments around it | Cache lifetime and ownership are explicit | Less duplicate post-processing and less re-entry churn |
| Live progressive download | Harder problem; AI-PACS must support it | ClearCanvas has calmer workstation assumptions | AI-PACS cannot copy the runtime model directly, but it can copy the ownership discipline |

---

## What This Means For The "Football Team" Analogy

The current AI-PACS problem is exactly what the football-team analogy describes.

The issue is not:

- every player is weak

The issue is:

- too many players still think they are allowed to attack the same ball
- too many support players are entering the play as if they were strikers
- there is not yet one coach making the final admission call for non-interactive work

In programming terms that means:

- too many background functions still behave like peers of visible interaction
- too many follow-up callbacks still act with local urgency
- not enough work is dropped or deferred when it has already become stale
- the main process still carries too much of the team conversation

ClearCanvas is calmer because:

- fewer players are allowed to improvise
- support roles stay support roles
- redraw and prefetch have clearer coaches

---

## Priority Fixes Suggested By This Comparison

### Priority 1: Execute Phase 4 — series-load decomposition and first-image fast path

Why first:

- the Phase 3 controller shell is already present in the repo
- one of the biggest remaining user-visible costs is still the heavy series-load path itself
- metadata-first / preview-first seams already exist, so the next value is to deepen that separation instead of re-arguing whether admission control exists at all

Must do:

- split the series-load path more explicitly into source enumeration, first-visible-image preparation, and deferred full-series work
- keep first image visible sooner than full grouping / full preparation
- prevent active viewing from sharing the same worst pressure window as a large on-demand series load

### Priority 2: Post-Phase-4 hardening of the admission owner

Why second:

- the controller shell exists, but its proof surface is still incomplete
- the remaining work is now measurement and closure, not invention

Must do:

- track `admitted`, `deferred`, `dropped`, and `stale-dropped` by work class
- close any remaining non-interactive paths that still self-admit outside the shared shell
- validate `stale_task_ratio` and `foreground_wait_p95_ms` against fresh overlap captures after Phase 4

### Priority 3: Add one redraw follow-up coordinator

Why third:

- multiple small redraws can still steal event-loop stability even when decode is acceptable
- ClearCanvas explicitly treats this as coordination work, not peer behavior

Must do:

- centralize sync/reference-line/secondary follow-up redraws
- deduplicate redraw requests
- run them only after visible interaction work is satisfied

### Priority 4: Download preemption without destructive cancellation

Why fourth:

- the logs still show unnecessary preemption churn and callback noise
- this remains important, but it no longer needs to block Phase 4 now that the admission shell exists

Must do:

- avoid reprioritization turning into synthetic failure noise
- reduce mid-receive cancellation where simple reordering is sufficient
- keep viewer-side progress/completion semantics calmer during overlap

### Priority 5: Narrow foreground-visible decode pressure

Why fifth:

- the log still shows real decode cost in several slow slices
- but decode is not the first architectural bottleneck anymore

Must do:

- keep the direct visible path sacred
- avoid letting helper policy make the current visible slice colder than necessary
- focus prewarm/current-window policy on reducing foreground misses instead of broad study-wide helpfulness

### Priority 6: Add per-process resource accounting

Why fifth:

- the current CPU story is still incomplete
- we know the main process gets hot, but not the exact child-process distribution

Must do:

- capture CPU per PID for:
  - main process
  - download subprocess
  - decode subprocess if active
  - warmup subprocess if active
- capture queue depth and callback-rate metrics
- record per-class work admission counts

Without this, future tuning risks optimizing the wrong side of the process boundary.

## Process-model clarification for the current question

### Can we have "multiple main processes"?

Yes and no:

- **Yes**, in the OS sense, you can run multiple peer processes, and each process has its own primary thread, memory space, and Python GIL.
- **No**, in the normal desktop-app architecture sense, you generally do **not** want multiple GUI "main app" processes all acting as equal owners of the same Qt workstation UI.

For this repo, the healthy model is:

- **one UI/main application process**
- **multiple narrowly-owned worker processes only where isolation really helps**

That means the better question is not "how many main processes?" but:

- which work classes deserve their own process?
- which work classes should stay in the main process but be admitted less often?

### Do subprocesses use multiple CPU cores, or do they still end up on one core?

By default, subprocesses are **not pinned to one core**.

On modern Windows systems:

- each runnable process or thread can be scheduled on **any available core** unless CPU affinity is explicitly restricted
- the OS may even move a process/thread between cores over time
- a separate Python process gives you a **separate GIL**, so Python bytecode can truly run concurrently on multiple cores across processes

So the answer is:

- **multi-core execution is absolutely possible through subprocesses**
- **subprocesses do not automatically collapse onto one core**
- but they still compete for **shared resources** such as memory bandwidth, disk I/O, SQLite/file locks, and callback traffic back into the parent process

That last point is the trap: subprocesses can spread CPU work across cores, yet the **user-visible bottleneck can still remain in the main process** if too many callbacks, redraws, or orchestration decisions return there.

### Does multi-core happen only through subprocesses?

Not only through subprocesses.

There are three common ways work can use multiple cores:

1. **Multiple processes**
   - best for isolating Python/GIL-heavy work
   - strongest separation

2. **Native-library threads inside one process**
   - libraries such as SimpleITK, NumPy, OpenCV, BLAS, and some decoders may use multiple cores internally
   - this can happen even when Python code itself is single-threaded

3. **Python threads**
   - useful for I/O overlap and coordination
   - but for pure Python CPU work they still share one GIL per process, so they are weaker than multiprocessing for true parallel CPU execution

### What this means specifically for AI-PACS

The current repo already uses the right general shape:

- download worker in its own process
- optional decode subprocess service for background decode isolation
- main process for UI and visible interaction

So the next improvement is **not** "create many equal main processes."

The next improvement is:

- keep one UI/main process
- add worker processes only for narrowly-owned heavy work that truly benefits from GIL/resource isolation
- keep reducing the amount of non-visible work that flows back into the main process during overlap

In short: **multiple cores are already usable, subprocesses can run on different cores, but the architectural win comes only when process isolation is paired with good admission control.**

---

## Concrete Next Instrumentation Needed

To answer the user's process-architecture question more precisely in future runs, the next log format should include:

1. **Per-PID CPU samples**
   - main PID
   - download PID
   - decode PID if active
   - warmup PID if active

2. **Per-class queue depth**
   - interaction
   - thumbnail
   - prefetch
   - compute/background

3. **Per-class work outcomes**
   - admitted
   - deferred
   - dropped
   - stale-dropped

4. **Foreground miss accounting**
   - cache hit
   - in-process decode
   - out-of-process help available or not

5. **Callback pressure counters**
   - progress updates delivered
   - thumbnail state updates delivered
   - redraw follow-up requests delivered
   - deduplicated redraw count

That instrumentation will make the next comparison much stronger than a flat "CPU high" statement.

---

## Bottom Line

From the reviewed overlap session, AI-PACS is not suffering because too many truly separate processes are active. It is suffering because:

- one helper subprocess exists,
- but most important coordination still lands back in the main process,
- and too many background or follow-up functions still behave like peers of visible work.

ClearCanvas is a useful standard here because it shows a calmer shape:

- separate study progression from heavy pixel work
- give prefetch explicit ownership and lower priority
- keep thumbnails as projections
- centralize redraw follow-up

So the next performance gains should come less from adding more workers and more from deciding:

- who owns each work class
- who is allowed to run during protected interaction
- which requests are already stale and should never run
- which UI updates should be projections instead of participants

That is the path most likely to reduce lag, lower CPU pressure, and move AI-PACS toward the same effective workstation discipline as ClearCanvas.
