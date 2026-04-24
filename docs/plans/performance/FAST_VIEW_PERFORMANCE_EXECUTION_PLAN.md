# FAST View Performance Execution Plan

## Purpose

This is the precise execution plan for the next FAST-view performance pass.

It is based on:
- the current repo plans and architecture notes
- the benchmark harness and existing benchmark artifacts
- the latest live overlap evidence from `C:\Users\vahid\OneDrive\Desktop\evaluation .txt`
- the latest live scroll/download session from `C:\Users\vahid\OneDrive\Desktop\log 53 .txt`
- the current FAST viewer code and tests
- the local ClearCanvas source tree in `C:\AI-Pacs codes\ClearCanvas-master`

This document does not replace the background performance corpus. It turns the findings into one execution contract with priorities, file ownership, KPI gates, validation rules, and stop/go criteria.

## Execution Status — 2026-04-18

## Block-First Optimization Rule — 2026-04-18

The execution plan is now explicitly optimized around **block logic first**, not phase labels first.

That means every next package must start by answering:

1. **Which block is paying the user-visible cost?**
2. **Which block is allowed to change for this package?**
3. **Which blocks must stay behaviorally stable?**
4. **Which KPI or stage timing proves the block choice was correct?**

### Default block priority under overlap

For the current workspace state, the default order is:

1. **Block 3 — Cache/scroll/orchestration**
2. **Block 2 — Viewer hot path**
3. **Block 1 — Data services**

This order is deliberate.

- **Block 3** is the first place to optimize because it decides whether Block 2 ever has to pay foreground cost.
- **Block 2** should only be optimized after Block 3 has already stopped avoidable misses, stalls, and UI-thread scheduling churn.
- **Block 1** should remain as stable as possible unless a proven producer-side behavior is disturbing the visible path.

### Current working rule by block

#### Block 1 — Data services

Treat Block 1 as a **stable producer plane** for this pass.

Allowed changes:

- instrumentation completion
- non-destructive preemption / calmer download state transitions
- thumbnail projection simplification already completed

Avoid for now:

- broad download-manager rewrites
- new persistence behavior that touches active-viewer semantics
- producer-side churn that does not directly reduce overlap pressure

#### Block 2 — Viewer hot path

Treat Block 2 as the **protected visible path**.

Allowed changes:

- exact-slice readiness improvements
- local cache-hit retention improvements
- measured reductions to decode/filter/render cost when logs clearly show `frame_ms` or `decode_ms` dominating

Avoid for now:

- changing wheel precision semantics
- broad visual-path rewrites before Block 3 pressure is reduced
- moving more visible work off-thread unless contention is proven and correctness remains clear

#### Block 3 — Cache/scroll/orchestration

Treat Block 3 as the **default first-fix plane** for overlap lag.

Allowed changes:

- admission tightening
- prefetch policy simplification
- UI-thread scheduling reduction
- heavy-stack-only policy refinement
- redraw/follow-up de-duplication when `decode=0` hitches are proven

This is where the next packages should start unless the log evidence clearly contradicts it.

### Package admission rule

No package should change more than one of these at once unless the affected code is inseparable:

- **Block 3 policy**
- **Block 2 exact hot path**
- **Block 1 producer behavior**

If a proposed package touches all three, it is too large and must be split.

### Cross-block harmony rule — mandatory

The three blocks must not be optimized as if they are independent machines.

They are one runtime team sharing the same:

- CPU budget
- UI-thread time budget
- memory/cache budget
- background worker attention
- cancellation/retry bandwidth
- user-visible latency budget

That means **harmony, relation, and co-work between blocks are mandatory**.

#### Required coordination model

- **Block 1** must behave like a calm producer and must not flood Block 3 or Block 2 with avoidable state churn.
- **Block 3** must behave like the traffic controller and must protect Block 2 from unnecessary work rather than trying to do more work itself.
- **Block 2** must behave like the protected visible path and must spend cost only on work that survived Block 3 admission for a real user-visible reason.

#### Global performance rule

No block-local win counts as success if it steals too much shared budget from the other blocks.

Examples:

- a Block 1 progress refinement is not a win if it creates more UI wakeups and makes Block 3 noisier
- a Block 3 prefetch expansion is not a win if it raises contention and makes Block 2 exact presentation less stable
- a Block 2 exact-quality improvement is not a win if it ignores global scheduling pressure and makes overlap responsiveness worse

#### Shared-resource rule

Every package must explicitly respect shared resources and answer:

1. what shared resource budget is being consumed more or less?
2. which block is being protected by this change?
3. which block might be disturbed by this change?
4. what evidence proves the global result improved, not just the local metric?

#### Job-control rule

All major work classes must be treated as coordinated jobs competing for the same runtime window.

The plan therefore requires:

- clear admission priority for user-visible work over helper work
- bounded background work during protected interaction
- stale-drop before execution whenever identity proves the job is no longer valuable
- coalescing instead of duplicate execution when multiple blocks request near-equivalent work
- reordering/defer-before-cancel whenever that produces lower global disturbance

#### Non-negotiable interpretation

From this point forward, the target is **best global performance**, not isolated per-block hero numbers.

So every optimization must preserve the relationship between blocks:

- Block 1 should feed the system calmly
- Block 3 should coordinate the system cheaply
- Block 2 should spend the protected budget only where the user actually sees the value

If a change improves one block while making the overall system feel busier, less stable, or less predictable, that change does not satisfy this plan.

## Block-Oriented Execution Overlay — 2026-04-17

This plan is now paired with a block-oriented execution companion:

- `docs/plans/performance/FAST_BLOCK_PERFORMANCE_ARCHITECTURE.md`

That companion reframes the FAST work into three functional performance blocks:

1. **Block 1 — Data services**
   - download manager, thumbnail/right-panel projection, DICOM/header persistence, DB/storage writes, and deferred reception/external metadata
2. **Block 2 — Viewer hot path**
   - decode, filter, render, and present in FAST mode
3. **Block 3 — Cache/scroll/orchestration**
   - cache policy, scroll policy, prefetch direction, progressive lifecycle, redraw ordering, and admission/scheduling between Block 1 and Block 2

### Why this overlay matters

The repo already has several phase-local wins, but the next meaningful step is no longer just "another phase". The next step is to make every performance change answer four questions explicitly:

- which block owns it
- which worker/process owns it
- which orchestrator gate schedules it
- which KPI proves it helped

### Phase-to-block mapping

The existing phases remain valid, but they now map to the block model like this:

- **Block 1**
  - Phase 1 thumbnail simplification/progress normalization
  - Phase 5 download preemption without destructive cancellation
  - storage/DB/header persistence instrumentation added in the new block KPI model
- **Block 2**
  - Phase 4B series-load decomposition and first-image fast path
  - Phase 7 clinical image stability during interaction
- **Block 3**
  - Phase 2 single progressive lifecycle owner
  - Phase 3 central non-interactive admission controller shell
  - Phase 4A heavy-stack cache/scroll stabilization
  - Phase 6 redraw coordination and stack-drag stabilization

### Performance suite rule going forward

The performance section must no longer report only viewer-centric or scenario-centric KPIs. Every benchmark capture should also be groupable into:

- Block 1 KPIs
- Block 2 KPIs
- Block 3 KPIs

The block KPI contract for that redesign now lives in:

- `tests/performance/block_kpi_model.json`
- `tools/performance/clearcanvas_aipacs_kpi_harness.py summarize-blocks`

This means the performance suite can answer not only "was the run faster?" but also:

- which block consumed the budget
- which block is missing instrumentation
- which block should move to a different worker/process model
- which block is the most likely fault owner when a scenario regresses

## Current Reality Check — 2026-04-18

### Current KPI extract — 2026-04-18

Latest artifacts reviewed:

- `generated-files/benchmarks/aipacs_live_overlap_fresh.json`
- `generated-files/benchmarks/aipacs_live_overlap_blocks_fresh.json`

Current measured overlap KPIs:

- `first_image_visible_ms = 196.76`
- `set_slice_present_p95_ms = 155.48`
- `set_slice_present_max_ms = 385.82`
- `decode_p95_ms = 208.4`
- `frame_render_p95_ms = 187.49`
- `cache_hit_ratio_pct = 52.6`
- `slow_frame_count_16ms = 114`
- `stale_task_ratio = 0.0`
- `cpu_p95_pct = 139.18`
- `rss_peak_mb = 221.42`
- `thread_count_p95 = 36.0`

Block-summary interpretation from the paired block KPI artifact:

- **Block 1 coverage:** `57.14%`
- **Block 2 coverage:** `85.71%`
- **Block 3 coverage:** `42.86%`

Immediate reading of those KPIs:

- startup/first-image latency is no longer the dominant remaining problem
- control-plane stale-work pressure is materially improved versus older benchmark captures
- sustained heavy-stack interaction is still far outside target, especially in the visible slice-present and decode/render tails
- cache-hit ratio is not yet strong enough to keep the active heavy series on the cheap path consistently under overlap

### Are we near the goals of this plan?

**Partially, yes — but only for the architectural control goals, not yet for the final heavy-stack performance goals.**

What is meaningfully closer to target now:

- the FAST viewer control plane is calmer than before for low and medium studies
- the thumbnail/progressive/controller-shell work is already materially closer to the intended ownership model
- the current live evidence shows that studies under roughly `200` images can now be viewed well and without the broad lag pattern that motivated this plan
- per-frame instrumentation and block KPI plumbing are now real enough to guide smaller, safer changes

What is **not** yet near closure:

- large actively viewed stacks still regress under overlap or long drag travel
- the heavy-series problem is no longer a general FAST collapse; it is now a **large-stack-specific bottleneck**
- final KPI closure for overlap CPU, heavy-series open/load, and stack-drag hitch suppression is still incomplete
- current measured overlap interaction tails (`set_slice_present_p95_ms=155.48`, `decode_p95_ms=208.4`) are still far outside the intended target band even though first-image startup is now much better

### Current block diagnosis from live logs

Based on the latest multi-patient `viewer_diagnostics.log` review:

- **Block 1 — Data services:** generally healthy; not the primary bottleneck in the reviewed sessions
- **Block 2 — Viewer hot path:** secondary contributor when Block 3 misses force foreground decode or when large-series load/open work expands too much
- **Block 3 — Cache/scroll/orchestration:** current primary bottleneck for the remaining heavy-series lag

In other words:

- the plan's control-plane direction was correct
- the remaining problem is now more specific than this document originally assumed
- the next step should be **more conservative**, not broader

### Block logic for the next implementation wave

The verified live-log pattern now gives us a more exact block contract:

- if `prepare_ms` is large while `decode_ms=0`, the package belongs to **Block 3**
- if `frame_ms` is large and `decode_ms` dominates, the package belongs to **Block 2**
- if overlap pressure is caused by cancellation/retry/producer churn before the viewer even asks for work, the package belongs to **Block 1**

That means the next optimization sequence should not be phrased as "speed up FAST generally".
It should be phrased as:

1. stop Block 3 from making the UI pay for unnecessary work
2. then reduce the remaining exact-cost work in Block 2
3. only then calm any remaining Block 1 pressure that still leaks into the visible path

### Focused bottleneck inventory by block

To stay focused, the next analysis and implementation passes should go **block by block** rather than mixing symptoms from different owners.

#### Block 1 — Data services

**Current status:** secondary bottleneck, not the main current source of visible lag.

**Primary owner files:**

- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`
- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`
- download-manager/network/storage files feeding those UI projections

**Current bottleneck inside Block 1:**

- progress/event **fan-out and UI projection churn**
- thumbnail state and border work are much better than before, but Block 1 still has the most risk of reintroducing overlap noise through repeated progress-to-UI transitions
- KPI coverage is still weak here (`57.14%`), so Block 1 can still hide waste that is not yet measured precisely enough

**Evidence pattern to watch:**

- repeated `seriesProgressUpdated` → thumbnail/progress/UI transitions without a corresponding user-visible gain
- residual border/count-label/progress projection work surviving even after projection-only simplification
- producer-side reprioritization/cancellation churn that leaks downstream as false work for Block 3 and Block 2

**Current safest reading:**

- Block 1 is mostly healthy as a producer plane
- its remaining bottleneck is **not raw download throughput first**; it is **how often producer events still wake UI-side consumers**

**Safest next package for Block 1:**

- do not broaden Block 1 work yet
- keep it to:
  - missing KPI/instrumentation completion
  - non-destructive preemption cleanup
  - any residual thumbnail projection idempotence fixes only if logs prove they still matter

#### Block 2 — Viewer hot path

**Current status:** secondary bottleneck, but the primary source of pain whenever the exact path is exposed.

**Primary owner files:**

- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/qt_viewer_bridge.py`

**Current bottleneck inside Block 2:**

- **exact foreground decode on wheel / exact-view requests**
- some non-fast or settled frames can also spike from filter/render work, but the main current problem is still exact misses falling through to decode on the visible path

**Evidence pattern to watch:**

- `frame_ms` dominates `total_ms`
- `decode_ms` dominates `frame_ms`
- live lines such as `decode_ms=40–130ms` during wheel interaction or large-stack navigation
- KPI confirmation in the current artifact:
  - `set_slice_present_p95_ms = 155.48`
  - `decode_p95_ms = 208.4`
  - `frame_render_p95_ms = 187.49`

**Current safest reading:**

- Block 2 is not the first thing to broaden or rewrite
- it should be optimized only after Block 3 has already reduced avoidable misses and UI-thread scheduling cost
- wheel precision semantics should remain protected

**Safest next package for Block 2:**

- strengthen exact nearby-slice readiness and retention
- reduce exact visible-path cost only where logs prove `frame_ms/decode_ms` are still dominant after Block 3 tightening
- leave visual/clinical-path semantics stable while doing so

#### Block 3 — Cache, scroll, orchestration

**Current status:** primary bottleneck.

**Primary owner files:**

- `modules/viewer/fast/lightweight_2d_pipeline.py`
  - `set_slice_index()`
  - `_prefetch_around()`
  - `_submit_prefetch()`
  - `_submit_frame_prefetch()`
- `modules/viewer/fast/system_load_controller.py`
- `modules/viewer/fast/ui_throttle.py`

**Current bottleneck inside Block 3:**

- **UI-thread prefetch/admission/scheduling cost**
- large active stacks still pay too much in the control plane before the frame is even shown
- this is the current home of the `decode=0` hitch class and the `prepare_ms` spike class

**Evidence pattern to watch:**

- `prepare_ms` dominates while `decode_ms=0`
- `set_slice_ms` dominates `_on_qt_scroll()` total even when slider/reference work stays tiny
- cache-hit ratio remains too weak for large active stacks (`cache_hit_ratio_pct = 52.6`)
- the control plane is improved, but still not strong enough to keep the active viewed series on the cheap path consistently under overlap

**Current safest reading:**

- Block 3 is where the next focused optimization should begin
- the biggest remaining gain is not from more workers; it is from making the current admission/prefetch path cheaper and calmer on the UI thread
- this is the correct place for the first heavy-stack-only package

**Safest next package for Block 3:**

- reduce synchronous work inside `set_slice_index()` / `_prefetch_around()`
- simplify or defer admission/probe work during protected interaction
- improve heavy-stack-only local warm coverage without changing small/medium global behavior
- use existing `[FAST_SET_SLICE_STAGE]` / `[FAST_QT_SCROLL_STAGE]` lines to verify that `prepare_ms` and `decode=0` hitch counts move down

### Practical focus rule

For the next implementation pass, treat the three blocks like this:

- **Block 3:** first block to change
- **Block 2:** first block to re-measure after Block 3 changes
- **Block 1:** only change if it still shows up as a real disturbance after the Block 3 → Block 2 pass

This keeps the work focused and prevents one package from mixing producer churn, visible decode cost, and orchestration overhead into the same change set.

### Conservative execution rule from this point forward

For the next pass, the plan should prefer:

1. preserving the current good behavior for `<200`-image studies
2. changing the active heavy-stack path before changing shared global policy
3. fixing one bottleneck at a time, with measurement after each package
4. delaying new module extraction until the behavioral seam is already proven inside the current files

The following work packages from this execution plan are now completed in the current workspace.

### Completed packages

- **Phase 0 / partial measurement lock — materially progressed enough for conservative phase work**
  - block KPI grouping artifacts exist in the repo
  - `QtViewerBridge.set_slice()` now emits sub-stage timing via `[FAST_SET_SLICE_STAGE]`
  - the KPI harness parses first-image and non-decode hitch evidence strongly enough to guide targeted work packages
  - remaining Phase 0 work is now mostly about keeping the measurement pack fresh, not inventing the measurement contract from scratch

- **Phase 1 / Package 1.1 + 1.2 — thumbnail simplification and progress normalization**
  - `HomeDownloadService` remains the canonical viewer-facing per-series progress stream.
  - `ThumbnailManager` now keeps stable per-series projection state and stable total-count memory.
  - repeated start/complete transitions are idempotent and skip redundant overlay/border/count-label writes.
  - `_hp_priority.py` no longer injects direct thumbnail per-progress churn during priority-download flow; the thumbnail contract is now projection-style `start → stable total → complete`.
  - active count projection stays stable as `N images` during download and finalizes as `N/N` on completion.
  - focused validation passed: **61 passed** across the Phase 1 thumbnail/lifecycle suites.

- **Phase 2 / Package 2.1 + 2.2 — single progressive lifecycle owner**
  - terminal progressive close is now routed through the shared `_finalize_progressive_series(...)` authority.
  - Layer 2b, Layer 3, and Layer 4 no longer perform duplicate post-finalize close/follow-up work around that shared finalizer.
  - verify/sweep remain repair helpers and observers rather than peer terminal owners.
  - focused regressions now prove that Layer 2b delegates terminal close through the shared finalizer and Layer 3 does not duplicate finalize follow-up.
  - focused validation passed: **128 passed** across the progressive lifecycle suites.

- **Phase 3 / controller-shell implementation — central non-interactive admission policy is in place enough to proceed**
  - the repo does **not** currently use a dedicated `fast_admission_controller.py` file, but the Phase 3 controller shell now exists in-place through `modules/viewer/fast/system_load_controller.py` plus `modules/viewer/fast/ui_throttle.py`.
  - non-interactive FAST work classes now have a shared admission front door and shared policy vocabulary (`interaction`, `progressive`, `thumbnail`, `prefetch`, `cache_warm`, diagnostics).
  - key call sites already route through the shell, including prefetch policy in `Lightweight2DPipeline`, thumbnail/UI throttling, warmup admission, and protected-UI progressive behavior.
  - preview-first and metadata-first paths also already exist in the series-load stack (`load_series_preview`, `pydicom_qt` metadata-only path), which means the repo is no longer blocked on inventing the controller before starting Phase 4.
  - **important correction:** Phase 3 should now be treated as **functionally progressed / sufficient to enter Phase 4**, not as a still-missing prerequisite.
  - remaining Phase 3 work is now a **post-Phase-4 hardening checkpoint**:
    - add explicit admitted/deferred/dropped/stale-dropped accounting by work class *(controller-side admitted/deferred/dropped accounting has now landed in `SystemLoadController`; stale-dropped remains primarily pipeline/perf-metric territory)*
    - close any remaining direct self-admission call sites that still bypass the shared shell
    - validate stale-drop and foreground-wait acceptance targets against fresh overlap captures

### Current recommended next step

With the current Phase 0 instrumentation, Phase 1, Phase 2, and the in-place Phase 3 controller shell in place, the next execution target is now:

- **Phase 4A — heavy-stack cache/scroll stabilization (Block 3 first)**

This is the correct next phase **before** broader series-load refactoring because the latest live evidence now shows a more specific remaining problem:

- low and medium studies already behave much better and should not be destabilized
- the reviewed heavy-series lag appears first in the active cache/scroll/orchestration path
- the visible slowdown is usually created when large-stack navigation outruns local cache coverage and falls back into foreground decode or cached-frame/UI follow-up hitches
- some heavy-series hitches still occur with `decode=0`, which means the remaining issue is not only raw decode cost

The immediate job is therefore:

- keep the current good small/medium behavior intact
- strengthen the heavy active-series path only where the logs prove it still loses
- postpone broader load-path restructuring until after the heavy-stack interaction path is calmer

The former Phase 4 series-load decomposition work remains necessary, but it should now follow the heavy-stack stabilization checkpoint instead of being the very next broad step.

The central finding is simple:

- the FAST viewer is no longer losing mainly because raw decode or render is slow
- it is losing because multiple subsystems still compete for authority during overlap
- in other words, the individual players are often fast enough, but the team is still colliding with itself

This plan therefore uses two explicit control levers:

1. **partition work across executors only where real isolation helps**
2. **schedule, admit, and defer work over time everywhere else**

The implementation bias for this pass is:

- do **not** create new subprocesses or worker pools just because CPU is high
- first reduce how much work is admitted concurrently
- only split work into another executor when that split removes a real source of contention such as GIL holds, blocking network receive, or heavyweight background preparation

## Evidence Reviewed

### Repo plans and analysis

- `docs/plans/plan.md`
- `docs/plans/performance/FAST_STORM_AND_PERFORMANCE_PLAN_vNEXT.md`
- `docs/plans/implementation/FAST_ORCHESTRATION_REFACTOR_PLAN.md`
- `docs/performance/PERFORMANCE_STATUS.md`
- `docs/analysis/ORCHESTRATION_ROOT_CAUSES.md`
- `docs/analysis/CLEARCANVAS_WORKSTATION_COMPARISON.md`
- `docs/analysis/CLEARCANVAS_DIVERGENCE_MATRIX.md`
- `docs/analysis/CLEARCANVAS_KPI_MAPPING.md`
- `docs/plans/analysis/CLEARCANVAS_KPI_SCORECARD_AND_PLAN_UPDATE.md`
- `docs/analysis/CORNERSTONE_ADMISSION_AND_ORCHESTRATION_REPORT.md`
- `docs/architecture/FAST_ORCHESTRATION_TARGET.md`

### Tests and harnesses

- `tests/performance/test_clearcanvas_aipacs_kpi_harness.py`
- `tools/performance/clearcanvas_aipacs_kpi_harness.py`
- `tests/viewer/test_fast_download_scroll_cpu_repro.py`
- `tests/viewer/test_cp1_control_plane_governance.py`
- `tests/viewer/test_system_load_controller.py`
- `tests/viewer/test_fast_viewer_pipeline.py`
- `tests/viewer/test_b43_progressive_lifecycle_state.py`
- `tests/viewer/test_dragdrop_progressive.py`
- `tests/viewer/test_fast_viewer_live_sync.py`
- `tests/ui_services/test_lifecycle_hygiene.py`
- `tests/fast/test_thumbnail_progress_state_binding.py`
- `tests/fast/test_fast_thumbnail_vs_download_separation.py`

### AI-PACS code paths

- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- `modules/viewer/fast/system_load_controller.py`
- `modules/viewer/fast/ui_throttle.py`
- `modules/viewer/pipeline/orchestrator.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`
- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_warmup.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`
- `PacsClient/pacs/patient_tab/utils/image_io.py`
- `modules/download_manager/network/socket_client.py`

### ClearCanvas reference code

- `ImageViewer/StudyManagement/StudyLoader.cs`
- `ImageViewer/StudyManagement/WeightedWindowPrefetchingStrategy.cs`
- `ImageViewer/Tools/Synchronization/SynchronizationToolCoordinator.cs`
- `ImageViewer/Thumbnails/ThumbnailLoader.cs`
- `ImageViewer/Volumes/VolumeCache.cs`

## Executive Diagnosis

### What is already good enough

- FAST cache-hot presentation is often in the low-millisecond class.
- The direct `QtViewerBridge.set_slice()` path can already be fast when background pressure is calm.
- Disk cache, decode isolation, and cache-first interaction were high-value improvements and should remain.
- Thumbnail behavior has already started moving in the right direction: it is no longer necessary to make thumbnails full lifecycle peers.

### What is still wrong

The current bottleneck is a control-plane storm under overlap:

1. Non-interactive work still enters from too many places.
2. Progressive lifecycle still has too much authority in too many branches.
3. Series load is too heavy and too close to the viewer hot path.
4. Stack-drag behavior is less controlled than wheel behavior.
5. Redraw/sync follow-up is still too distributed.
6. Download preemption is still destructive and creates failure churn.
7. Thumbnail/download UI still needs stricter projection-only semantics.

Another way to say it:

- the system currently asks too many workers to do too many things at the same time
- some of that work should run on different executors
- but a larger portion of the problem is that too much work is admitted at once instead of being ordered by importance

So the solution is **not** "just add more workers".
The solution is:

- keep truly isolated heavy work on separate executors/processes
- keep visible interaction on the direct path
- schedule, batch, coalesce, defer, or drop non-visible work before it burns CPU

### Evidence from the latest live session

From `log 53 .txt`:

- overlap CPU repeatedly reached roughly `136%`, `143%`, `156%`, `169%`, `180%`, and over `200%`
- a single on-demand series load took about `11.3s`
- stack drag produced decode hitches such as about `24.7ms` and `39.8ms`
- one visible hitch was about `68.4ms` with `decode=0`, `filter=0`, and `wl=0`, which means the hitch was orchestration/redraw/UI side, not raw image math
- several download/network request batches still took about `4s` to `6s`
- the log also showed `Download cancelled during receive (preemption)` followed by an invalid `Paused -> Failed` path, which means priority changes are still wasting work instead of merely reordering work

This matches the repo benchmark story:

- `run_001` and `run_002` improved rendering behavior
- but overlap `cpu_p95_pct` and `stale_task_ratio` remained far outside the target range
- therefore decode/render wins alone will not finish this problem

## Non-Negotiable Rules

These rules govern the whole implementation sequence:

1. Keep FAST and Advanced separated.
2. Keep `QtViewerBridge.set_slice()` direct, synchronous, and top priority.
3. Keep `Lightweight2DPipeline` as the FAST render/cache authority.
4. Move ownership out of peer callbacks and into named owners.
5. Let thumbnails reflect state, not drive state.
6. Do not reintroduce repeated DB/server checks just to paint thumbnail state.
7. Do not accept clinical image instability as a hidden cost of performance work.
8. Do not treat a headless-only win as success if live overlap still feels laggy.

## Executor Partitioning vs Scheduling Discipline

This plan explicitly distinguishes **where work runs** from **when work is allowed to run**.

### Current repo reality

The repo already has meaningful executor separation:

- download runs in a dedicated subprocess via `DownloadProcessWorker`
- background decode isolation already exists via `modules/viewer/fast/decode_service.py`
- FAST prefetch and frame preparation already use thread pools in `Lightweight2DPipeline`
- the visible present path still runs through direct `QtViewerBridge.set_slice()` on the UI-driven path

Therefore, the next pass should assume:

- some partitioning is already present
- adding even more workers or subprocesses is **not** the default answer
- poor admission, poor timing, and poor ownership are currently more dangerous than lack of raw worker count

### When work should be split across executors

Executor/process separation is justified only when at least one of these is true:

- the task holds the Python GIL for meaningful time
- the task blocks on network receive or heavy file I/O
- the task can run with low coordination chatter and low cancellation cost
- the task can be safely deprioritized without affecting the active image

Examples in this repo:

- download receive / batch processing
- background decode service
- heavy non-visible preparation work

### When work should stay on the same executor but be scheduled over time

Scheduling, not executor multiplication, is the right answer when:

- the work is lightweight but too frequent
- the work is user-interface adjacent
- the work is cosmetic or secondary
- the work becomes harmful only because too many copies run together

Examples in this repo:

- progressive viewer-facing updates
- thumbnail state projection
- redraw follow-up
- sync/reference-line follow-up
- non-critical helper refresh

### Operational rule for this plan

Before introducing any new executor, thread pool, or subprocess, the phase owner must answer:

1. What exact contention does the new executor remove?
2. Why can the same win not be achieved by admission, batching, or deferral?
3. What coordination or cancellation cost does the new executor add?

If those answers are weak, prefer scheduling discipline over more executors.

## ClearCanvas Lessons We Should Copy

The goal is not to copy the ClearCanvas runtime or transport. The goal is to copy its ownership discipline.

### Patterns to adopt

- central request ownership
- admission before work starts
- simple pending queues for background UI work
- single cache ownership and lifetime discipline
- one redraw/synchronization coordinator
- separation of source enumeration from pixel loading
- explicit prefetch windows and lower-priority background work

### Patterns not to copy literally

- browser-specific or foreign transport assumptions
- exact ClearCanvas cache topology
- any approach that would remove AI-PACS live progressive download support

## Success Contract

This plan has four levels of targets.

### Level 1 - immediate correction

- overlap `stale_task_ratio < 0.50`
- `terminal_completion_duplicate_count = 0`
- `cache_warm_duplicate_count = 0`
- `ui_event_loop_lag_ms p95 < 20`
- `foreground_wait_p95_ms < 5`
- thumbnails only expose `start`, `total`, and `complete` state

### Level 2 - strong improvement

- overlap `cpu_p95_pct < 80`
- overlap `first_image_visible_ms < 800`
- on-demand series-load time cut by at least half from the current `11.3s` evidence
- stack-drag hitch rate falls materially and non-decode hitches trend toward zero

### Level 3 - primary closure target

- overlap `cpu_p95_pct < 80` remains true in both headless and live overlap validation
- benchmark timings on the named target KPIs are reduced by at least half versus the locked baseline package for this plan
- user-visible lag becomes rare rather than common
- active scroll image looks clinically stable and visually consistent with the settled image

### Level 4 - stretch target

- overlap `cpu_p95_pct < 50` on the current benchmark class and host profile

The `< 50%` CPU target remains the aspirational endpoint, but plan execution should not ignore major validated wins merely because the final stretch target has not yet been fully reached.

## Work Class Model

All non-interactive FAST work should be admitted through explicit work classes.

### Work classes

1. `interaction`
- direct visible slice presentation
- never queued behind background work

2. `visible_progressive`
- progress-driven viewer updates for the currently visible series
- can be batched, coalesced, and stale-dropped by identity

3. `thumbnail`
- thumbnail start/finish state and total-count projection
- no independent urgency above visible correctness

4. `prefetch`
- nearby exact slice preparation and cache fill
- only around the active viewing window

5. `compute_background`
- cache warm, helper scans, diagnostics, non-visible refresh, optional boosters

### Identity model

Every non-interactive request should be keyed at least by:

- `viewer_id`
- `series_number`
- `epoch`
- `work_class`

If useful, slice or range identity may be added as a secondary discriminator.

Anything stale should be dropped before execution, not after wasting CPU.

## Target Architecture

The next-pass architecture should be understood first as **logical ownership roles**, not automatically as a requirement to create a brand-new file for every label.

The logical target is:

`Download Manager`
-> `FastDownloadEventNormalizer`
-> `FastAdmissionController`
-> `FastProgressiveLifecycleOwner`
-> `ThumbnailProjection`
-> `FastRedrawCoordinator`
-> `CacheWarmRequestor`

At the same time:

`User Interaction`
-> `QtViewerBridge.set_slice()`
-> `Lightweight2DPipeline`
-> exact visible present
-> post-present redraw follow-up only if admitted

### Ownership boundaries

- `SystemLoadController` remains the policy brain.
- `ui_throttle` remains a facade.
- `FastAdmissionController` becomes the only legal gate for non-interactive FAST work.
- `FastProgressiveLifecycleOwner` becomes the only terminal authority for `(series, epoch)`.
- `thumbnail_manager.py` becomes projection-only.
- redraw/sync work moves behind one coordinator.

Implementation note:

- these roles may begin as in-place ownership collapse inside existing files
- extract a new module only when the seam is proven and actually reduces complexity
- do not add architectural layers whose coordination cost is greater than the contention they remove

## Detailed Execution Plan

## Optimized Block Execution Sequence — 2026-04-18

The phase list below remains valid, but the **execution logic** is now optimized into three waves.

### Wave A — Block 3 first

Goal:

- reduce visible lag without changing viewer semantics
- reduce `prepare_ms` spikes
- reduce `decode=0` hitches
- protect the good small/medium-study behavior already achieved

Packages in this wave:

- Phase 3 hardening that directly reduces distributed admission work
- Phase 4A heavy-stack cache/scroll stabilization
- the first measured part of Phase 6 where redraw/follow-up duplication is proven to be Block 3 work

### Wave B — Block 2 second

Goal:

- reduce the remaining exact wheel/settled-frame cost after Block 3 has been tightened
- reduce visible `frame_ms` / `decode_ms` tails without weakening correctness

Packages in this wave:

- Phase 4B first-image / series-load decomposition where the viewer hot path is still being burdened
- targeted Block 2 work inside `Lightweight2DPipeline` and `QtViewerBridge`
- Phase 7 clinical image stability only after the interaction/control path is calmer

### Wave C — Block 1 third

Goal:

- calm remaining producer-side disturbance only if it still affects overlap after Waves A and B

Packages in this wave:

- Phase 5 download preemption without destructive cancellation
- any residual thumbnail/progress producer cleanup that still shows up in post-Wave-B logs

### Why this optimized sequence is safer

Because it matches the actual bottleneck ownership:

- **Block 3** decides whether Block 2 is allowed to become expensive
- **Block 2** is where the unavoidable exact cost appears
- **Block 1** should be changed last unless it is directly proven to be disturbing the visible path

This keeps us from "fixing" a producer or decode detail when the real regression is still admission pressure or cache-orchestration churn.

### Phase 0 - Lock the measurement contract

#### Objective

Freeze the exact scenarios, KPI names, and artifact paths so each later phase can be judged against the same contract.

#### Why this phase is first

The repo already has benchmarks, but the live log evidence shows that some important failures still appear outside headless-only views. We need one stable measurement pack before changing more code.

#### Files

- `tests/performance/test_clearcanvas_aipacs_kpi_harness.py`
- `tools/performance/clearcanvas_aipacs_kpi_harness.py`
- `docs/performance/PERFORMANCE_STATUS.md`
- this plan

#### Work

- Lock the main overlap scenario as: view current series while downloading and while opening or loading another patient/series.
- Keep the same KPI vocabulary across AI-PACS and ClearCanvas-style comparisons.
- Extend the parser if needed so it records:
  - `series_load_single_ms`
  - `download_preemption_fail_count`
  - `stack_drag_decode_hitch_count`
  - `stack_drag_nondecode_hitch_count`
  - `thumbnail_start_count`
  - `thumbnail_complete_count`
- Add sub-stage timing inside `QtViewerBridge.set_slice()` so non-decode hitches can be attributed to:
  - frame retrieval
  - `set_image`
  - annotation update
  - slider update
  - sync/reference-line follow-up
  - any measurable post-present gap
- Ensure live log capture remains mandatory after major phases, not optional.

#### Acceptance

- One benchmark and log package can be used before/after every phase.
- The team can prove whether a phase reduced storm behavior, not just average latency.
- The team can distinguish decode hitches from non-decode UI/redraw hitches before doing later structural changes.

### Phase 1 - Thumbnail simplification and one viewer-facing progress stream

**Status (2026-04-16):** current workspace package completed.

#### Objective

Reduce thumbnail and progress-side fan-out so the UI stops doing repeated low-value work.

#### Why this matters

The user only needs three thumbnail facts:

- the series started downloading
- the total image count
- the series finished downloading

The current design should be simplified until thumbnail updates do not keep re-checking state or acting like lifecycle peers.

#### Files

- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`
- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py`
- `tests/ui_services/test_lifecycle_hygiene.py`
- `tests/fast/test_thumbnail_progress_state_binding.py`
- `tests/fast/test_fast_thumbnail_vs_download_separation.py`

#### Work

- Normalize download-manager events into one canonical series stream.
- Resolve `total_images` once and keep it stable for the series lifecycle.
- Emit thumbnail state only on:
  - start
  - total-count availability if not already known
  - complete
- Keep the thumbnail visual contract simple:
  - gray/glassy while active
  - count shown as `145 images` when download is underway
  - final count shown as `145/145` when complete
- Ensure thumbnails do not continuously poll, query, or request DB/server checks just to refresh cosmetic state.
- Keep viewer progress separate from thumbnail projection.

#### Acceptance

- Each series produces at most one thumbnail start transition and one thumbnail complete transition.
- Active and completed series remain visually distinguishable.
- No new repeated DB poll loop exists for thumbnail state.
- Completion still emits one final viewer-facing completion pulse where needed.

#### Completed in this workspace

- thumbnail start/complete lifecycle is projection-only and idempotent
- stable per-series total-count memory preserves the first valid total instead of allowing later churn to rewrite the active label
- `_hp_priority.py` no longer pushes direct thumbnail per-progress updates during priority flow
- focused validation passed:
  - `tests/fast/test_fast_thumbnail_vs_download_separation.py`
  - `tests/fast/test_thumbnail_progress_state_binding.py`
  - `tests/fast/test_series_completion_state_transition.py`
  - `tests/fast/test_series_download_order_top_to_bottom.py`
  - `tests/ui_services/test_lifecycle_hygiene.py`
  - **61 passed** total in the focused Phase 1 run

#### Expected KPI movement

- modest CPU reduction
- lower UI burst rate
- lower thumbnail churn

### Phase 2 - Single progressive lifecycle owner

**Status (2026-04-16):** current workspace package completed.

#### Objective

Make terminal completion one-shot and stop lifecycle re-entry from peer branches.

#### Files

- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py`
- supporting helper/state code introduced in this phase
- `tests/viewer/test_fast_viewer_pipeline.py`
- `tests/viewer/test_b43_progressive_lifecycle_state.py`
- `tests/viewer/test_dragdrop_progressive.py`

#### Work

- Collapse terminal authority into one owner for each `(series, epoch)`.
- Demote verify/sweep/recovery paths to observers and repair helpers only.
- Ignore late terminal callbacks after terminal closure unless a real new epoch begins.
- Ensure background-complete/no-viewer cases do not recreate full viewer lifecycle work.
- Keep cache warm subordinate to lifecycle closure, not equal to it.

#### Acceptance

- `terminal_completion_duplicate_count = 0`
- `cache_warm_duplicate_count = 0`
- restart-after-DONE still works for a valid new cycle
- no late callback can recreate a second viewer-facing 100 percent completion path

#### Completed in this workspace

- Layer 2b final close now passes matched viewers into the shared `_finalize_progressive_series(...)` path
- Layer 2b no longer performs duplicate exit/corner/thumbnail follow-up outside the shared finalizer for already-finalized cycles
- Layer 3 and Layer 4 no longer append duplicate post-finalize corner/thumbnail work after calling the shared finalizer
- focused regressions were added for shared-finalizer ownership and duplicate-follow-up suppression
- focused validation passed:
  - `tests/viewer/test_fast_viewer_pipeline.py`
  - `tests/viewer/test_b43_progressive_lifecycle_state.py`
  - `tests/viewer/test_dragdrop_progressive.py`
  - **128 passed** total in the focused Phase 2 run

#### Expected KPI movement

- lower CPU tails near completion
- lower callback-gap spikes
- fewer duplicate close/grow/warm actions

### Phase 3 - Central non-interactive admission controller

#### Objective

Stop distributed self-admission and put non-interactive work behind one gate.

This phase is primarily about **when work runs**, not about creating additional executors.

#### Files

- `modules/viewer/fast/system_load_controller.py`
- `modules/viewer/fast/ui_throttle.py`
- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_warmup.py`
- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`
- `tests/viewer/test_system_load_controller.py`
- `tests/viewer/test_cp1_control_plane_governance.py`
- `tests/viewer/test_fast_download_scroll_cpu_repro.py`

#### Work

- Introduce a single gate that admits, defers, coalesces, or drops all non-interactive FAST work.
- Keep `interaction` work outside the queue and immediate.
- Re-route `visible_progressive`, `thumbnail`, `prefetch`, and `compute_background` through the controller.
- Enforce stale-drop by identity before work runs.
- Keep policy centralized even if execution stays local; a single policy brain does **not** require one giant runtime queue for every work class.
- Under protected interaction:
  - cap visible progressive admission in bounded batches
  - allow only current-series prefetch in a narrow window
  - defer or drop helper work
  - defer cosmetic/UI-only work
- Keep accounting for admitted, deferred, dropped, and stale-dropped work per class.

#### Acceptance

- no component self-admits background work around the controller
- `stale_task_ratio < 0.50` first, then `< 0.35`
- `foreground_wait_p95_ms < 5`
- interaction path does not regress

#### Expected KPI movement

- this should be the biggest CPU win
- it should also reduce lag amplification during overlap

### Phase 4A - Heavy-stack cache/scroll stabilization

#### Objective

Reduce the remaining lag for large actively viewed series without retuning the whole FAST system.

#### Why this phase is next

The latest live multi-patient evidence changed the immediate priority:

- smaller studies in the same session are already performing well enough that broad shared-policy churn is now risky
- the heavy-series slowdown appears mainly when the viewed stack becomes large enough to outrun the current cache/prefetch window
- some visible hitches still show `decode=0`, which means cached-path display/follow-up cost still needs measurement and containment

That means the safest next move is **not** a broad architectural rewrite. It is a focused, heavy-stack-only stabilization pass on the active viewing path.

#### Files

- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- `modules/viewer/fast/system_load_controller.py`
- `modules/viewer/fast/ui_throttle.py`
- `tools/performance/clearcanvas_aipacs_kpi_harness.py`
- targeted viewer/performance tests touching heavy-stack scroll behavior

#### Work

- Introduce a **large-series-only** policy override for the actively viewed series rather than changing the global FAST defaults.
- Start with the smallest possible package:
  - adjust heavy-stack cache/prefetch behavior only when the active viewed stack crosses a clear threshold
  - preserve the current small/medium-series behavior unchanged
- Improve the heavy active-series hot path conservatively:
  - strengthen local warm coverage around the current slice for large stacks
  - keep directional drag prefetch conservative and measurable
  - do not widen work admission globally for all studies
- Use the existing `[FAST_SET_SLICE_STAGE]` breakdown to isolate `decode=0` hitches before adding any new redraw architecture.
- Prefer in-file tightening inside `qt_viewer_bridge.py` and `lightweight_2d_pipeline.py` before extracting any new coordinator module.

#### Acceptance

- heavy active-series stack-drag shows materially fewer visible hitches
- `stack_drag_decode_hitch_count` and `stack_drag_nondecode_hitch_count` both trend down on the target scenario
- lower-count studies keep their current good behavior
- the change can be explained as a heavy-stack-only policy refinement, not a global runtime rewrite

#### Expected KPI movement

- better heavy-stack interaction stability
- lower chance of cache miss falling back to foreground decode
- lower incidence of `decode=0` but high-total-ms hitches in drag sessions

### Phase 4B - Series-load decomposition and first-image fast path

#### Objective

Reduce the `11.3s` series-load burden and separate first visible image from full series preparation.

#### Why this phase is necessary

The latest live log showed that one on-demand series load took about `11.3s`. Even if some of that work is outside the visible slice path, keeping such heavy work near the same process and timing window damages the viewing experience.

ClearCanvas gets this right by separating source enumeration and load planning from pixel retrieval.

#### Files

- `PacsClient/pacs/patient_tab/utils/image_io.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py`
- `modules/viewer/pipeline/orchestrator.py`
- related tests around on-demand series load and flat-folder import

#### Work

- Split the series-load path into:
  - metadata/source enumeration
  - first-visible-image preparation
  - deferred full-series grouping or background preparation
- Make first visible image the priority, not full-series completeness.
- Avoid expensive viewer-side grouping or transformation work before the first visible slice is ready.
- If needed, precompute or cache lightweight series manifests that let the viewer know count/order without pulling the whole payload through the hot path.
- Ensure new-patient load does not outrank current interaction-critical viewing.
- Prefer decomposition and manifesting before adding any new worker or subprocess for series load; first prove what can be removed, deferred, or made incremental.

#### Acceptance

- `series_load_single_ms` is cut by at least half from the latest live evidence
- `first_image_visible_ms` under overlap materially improves
- opening a new patient no longer drags the active viewer into the same pressure pattern

#### Expected KPI movement

- large improvement to "open while viewing" feel
- better first-image timing under overlap

### Phase 5 - Download preemption without destructive cancellation

#### Objective

Preserve priority control without turning reprioritization into canceled work and error churn.

#### Files

- `modules/download_manager/network/socket_client.py`
- related download-manager service code and tests
- `tests/download_manager/run_dm_test.py`

#### Work

- Change preemption policy so queued work is reprioritized before in-flight receive is canceled.
- Avoid mid-receive cancellation unless there is a stronger reason than simple priority inversion.
- Prevent `Paused -> Failed` transitions that are artifacts of internal reprioritization rather than real network failure.
- Keep download state transitions consistent so UI and progressive handlers do not respond to artificial failure noise.

#### Acceptance

- no invalid preemption-driven pause/fail transition in the overlap scenario
- fewer wasted retries and fewer failure-side callbacks during active viewing
- priority changes still work, but with calmer state transitions

#### Expected KPI movement

- lower CPU waste
- lower retry and error churn
- less downstream event noise

### Phase 6 - Redraw coordination and stack-drag stabilization

#### Objective

Remove non-decode hitches and bring stack drag under the same discipline that wheel scrolling already benefits from.

#### Why this phase matters

The latest evidence says wheel behavior is currently better than stack behavior. That means stack drag is still admitting or triggering extra work that wheel interaction is avoiding.

The `68.4ms` hitch with zero decode/filter/window-level cost strongly suggests redraw or coordination work is still escaping the intended order.

#### Files

- `modules/viewer/fast/qt_viewer_bridge.py`
- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`
- sync/reference-line related viewer/controller code
- `tests/viewer/test_fast_viewer_live_sync.py`
- any redraw-specific tests added in this phase

#### Work

- First collapse redraw ownership inside the current files; extract a redraw coordinator only if the seam becomes stable and clearly valuable.
- Deduplicate redraw requests after exact visible present.
- Prevent multiple helper callbacks from independently scheduling redraw work during interaction.
- Audit stack-drag path against wheel path and remove extra timer, settle, cosmetic, or follow-up work that stack still triggers.
- Keep only a narrow exact-slice neighborhood active during stack drag.

#### Acceptance

- `stack_drag_nondecode_hitch_count` trends to zero
- sync/reference-line work remains correct but does not interfere with frame presentation
- wheel and stack interaction behavior become structurally consistent

#### Expected KPI movement

- fewer long hitches
- smoother active navigation
- lower event-loop disturbance

### Phase 7 - Clinical image stability during interaction

#### Objective

Make the scrolling image visually stable so the user does not see a darker or different-looking image during interaction.

#### Why this phase is not first

The current evidence says the bigger user pain is still storm behavior. The system must first stop fighting itself. After that, image-quality differences during active interaction can be isolated and fixed more cleanly.

#### Files

- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- any filter/window-level/compression path involved in interaction-vs-settled presentation
- comparison harnesses or targeted diagnostics added in this phase

#### Work

- Identify exactly which interaction path changes the visible image:
  - surrogate frame choice
  - filter timing
  - window-level timing
  - compressed-vs-final pixel path
- Compare wheel and stack rendering paths to locate where image appearance diverges.
- Enforce a rule that active interaction must preserve the same clinical appearance as the settled image, even if resolution strategy differs internally.
- If a temporary lower-fidelity path remains necessary, it must remain visually equivalent enough that the user does not perceive a confidence-breaking brightness or contrast shift.

#### Acceptance

- no obvious darkening or visible tonal shift during active scroll
- wheel and stack remain visually stable
- performance win is kept without clinical instability

### Phase 8 - Benchmark closure and plan re-baseline

#### Objective

Close the loop with measured proof and then update the canonical plans.

#### Files

- `generated-files/benchmarks/*`
- `docs/performance/PERFORMANCE_STATUS.md`
- `docs/plans/plan.md`
- `docs/plans/performance/FAST_STORM_AND_PERFORMANCE_PLAN_vNEXT.md`

#### Work

- rerun headless common and overlap benchmarks after Phase 2, Phase 3, Phase 4, and final closure
- capture live overlap logs after the same phases
- compare against existing `run_001` and `run_002`
- validate on the current developer machine and on at least one second machine using the repo's cross-PC workflow
- update the master plan and performance status with the new measured truth

#### Acceptance

- benchmarks show at least a two-times improvement on the targeted timings
- live overlap confirms the user-visible lag reduction
- overlap CPU on the benchmark host is materially reduced, with `< 80%` as the primary closure target and `< 50%` retained as the stretch target

## Detailed Priority Order

This is the exact solution order recommended by the findings:

1. `Phase 0` measurement lock and non-decode hitch instrumentation
2. `Phase 1` thumbnail simplification and progress normalization
3. `Phase 2` single progressive owner
4. `Phase 3` central admission controller shell
5. `Wave A / Block 3 first:` `Phase 4A` heavy-stack cache/scroll stabilization
6. `Wave A / Block 3 follow-up:` measured `Phase 6` redraw/scheduling cleanup only where logs show `decode=0` hitch ownership
7. `Wave B / Block 2 second:` `Phase 4B` series-load decomposition and exact visible-path relief
8. `Post-Wave-B checkpoint` — Phase 3 hardening (per-class accounting, stale-drop proof, residual routing cleanup)
9. `Wave C / Block 1 third:` `Phase 5` download preemption fix
10. `Phase 7` clinical image stability
11. `Phase 8` benchmark closure and cross-PC validation

If raw latency improves but ownership still remains fragmented, the phase is only partially successful and the next pass must continue collapsing authority instead of pivoting early to visual polish.

**Progress update (2026-04-18):** Steps 1 through 4 are materially progressed enough to support conservative next packages. The current execution stop is now **Wave A / Block 3 first**, beginning with Step 5 (`Phase 4A` heavy-stack cache/scroll stabilization) and then only the measured Block-3-owned portion of Step 6 (`Phase 6` redraw/scheduling cleanup). Only after that should execution move into **Wave B / Block 2 second** (`Phase 4B` series-load decomposition and exact visible-path relief). The explicit goal is to fix the controller/cache/orchestration plane before touching broader viewer or producer behavior.

## Implementation Mode

This section exists to make the plan easier to execute.

The implementation style for this plan is:

- prefer **small, measurable work packages**
- change as few files as possible per package
- prove each package with one focused test group and one live/log check
- avoid large framework extraction before the behavioral seam is already working

### Default work package template

For each package, do only the following:

1. identify one concrete behavior to change
2. identify one owner file or one tightly-related file group
3. implement the smallest change that enforces the new rule
4. add or update focused tests
5. capture one benchmark/log comparison against the locked baseline

If a package cannot be described that simply, it is too large and should be split.

### Build this first, not that first

When a phase proposes a new owner such as:

- `FastAdmissionController`
- `FastProgressiveLifecycleOwner`
- `FastRedrawCoordinator`

the first implementation step should usually be one of these, in order:

1. collapse scattered logic into one existing file
2. introduce one helper function or helper class in the existing area
3. only then extract a new module if the seam is stable

This keeps the repo debuggable while the behavior is still changing.

### Do not build yet

Until the relevant behavior is proven, do **not** start by building:

- a generic queue framework for every work class
- a new global scheduler that owns too many responsibilities at once
- extra subprocesses just because CPU is high
- broad abstraction layers that do not immediately reduce overlap work

The plan should produce calmer runtime behavior first, cleaner architecture second.

### Per-phase ship criteria

Each phase should ship only when it has all four of these:

1. **code change** — the runtime behavior actually changed
2. **focused test proof** — the targeted test set passes
3. **measurement proof** — at least one KPI/log indicator moved in the right direction
4. **rollback clarity** — the changed ownership boundary is simple enough to revert if needed

### Phase packaging guidance

#### Phase 0 packaging

- Package 0.1: add missing metrics/parsing only
- Package 0.2: add `QtViewerBridge.set_slice()` sub-stage timing only
- Do not combine parser changes and bridge behavior changes in one patch set

#### Phase 1 packaging

- Package 1.1: canonicalize download-to-thumbnail event normalization
- Package 1.2: reduce thumbnail visual state writes to projection-only transitions
- Do not mix thumbnail projection cleanup with progressive lifecycle cleanup

#### Phase 2 packaging

- Package 2.1: centralize terminal close path
- Package 2.2: demote verify/sweep/recovery to observer/repair role
- Do not extract a new lifecycle module until duplicate terminal work is already gone

#### Phase 3 packaging

- Package 3.1: centralize admission decisions for one work class at a time
- Package 3.2: add stale-drop accounting and proof
- Package 3.3: extend to the next work class only after the first one is stable
- Do not migrate `prefetch`, `thumbnail`, `progressive`, and helper work all at once

#### Phase 4 packaging

- Package 4A.1: heavy-stack-only cache/prefetch threshold policy for the active viewed series
- Package 4A.2: isolate and reduce the worst `decode=0` hitch stage using existing set-slice stage timing
- Package 4A.3: validate that `<200`-image studies remain unchanged
- Package 4B.1: separate first-visible-image path from the heavier series-load path
- Package 4B.2: defer non-essential grouping/background preparation
- Do not introduce a new loader architecture before first-image timing clearly improves

#### Phase 5 packaging

- Package 5.1: stop invalid preemption-driven pause/fail transitions
- Package 5.2: reduce destructive mid-receive cancellation
- Do not rewrite the whole download manager to fix this phase

#### Phase 6 packaging

- Package 6.1: use Phase 0 timing to identify the worst non-decode follow-up stage
- Package 6.2: deduplicate one redraw/sync follow-up source at a time
- Package 6.3: align stack-drag follow-up rules with wheel behavior
- Do not create a broad redraw framework before the worst offender is measured

#### Phase 7 packaging

- Package 7.1: identify exactly which interaction path changes appearance
- Package 7.2: remove one proven source of visible appearance divergence
- Do not start with broad image-processing changes before the divergence is localized

### Implementation checkpoint after every package

After each package, answer these four questions in the commit notes or working log:

1. What work was removed, deferred, or isolated?
2. Which executor still owns the work now?
3. What higher-priority work is now protected better than before?
4. What metric or log line proves that this package helped?

## What To Remove, Demote, Or Contain

### Remove or collapse

- repeated thumbnail-state checks that do not change user value
- peer terminal authorities in progressive lifecycle
- destructive preemption that converts reprioritization into failure churn

### Keep, but behind one gate

- cache warm
- helper/background refresh
- non-visible prefetch
- redraw follow-up
- optional boosters or warmup helpers

### Keep as-is

- direct `set_slice()` interaction
- FAST render/cache authority in `Lightweight2DPipeline`
- FAST/Advanced split
- disk cache and decode isolation

## Test Matrix By Phase

### Phase 1

- `tests/ui_services/test_lifecycle_hygiene.py`
- `tests/fast/test_thumbnail_progress_state_binding.py`
- `tests/fast/test_fast_thumbnail_vs_download_separation.py`
- `tests/fast/test_cpu_only_download_ui_responsiveness.py`

### Phase 2

- `tests/viewer/test_fast_viewer_pipeline.py`
- `tests/viewer/test_b43_progressive_lifecycle_state.py`
- `tests/viewer/test_dragdrop_progressive.py`

### Phase 3

- `tests/viewer/test_system_load_controller.py`
- `tests/viewer/test_cp1_control_plane_governance.py`
- `tests/viewer/test_fast_download_scroll_cpu_repro.py`

### Phase 4

- on-demand series-load tests in `tests/viewer/test_fast_viewer_pipeline.py`
- flat-folder and load-path tests touching `image_io.load_single_series_by_number`

### Phase 5

- `tests/download_manager/run_dm_test.py`
- overlap live-log replay if available

### Phase 6

- `tests/viewer/test_fast_viewer_live_sync.py`
- new redraw coordinator tests
- live wheel-vs-stack overlap run

### Phase 7

- targeted interaction-vs-settled image-comparison diagnostics
- live clinical-review capture for wheel and stack

### Phase 8

- `tests/performance/test_b25_scenarios.py`
- `tests/performance/test_clearcanvas_aipacs_kpi_harness.py`
- headless benchmark recapture
- live overlap log capture

## Stop/Go Rules

### Stop and rollback a phase if

- active interaction regresses
- completion semantics become incorrect
- thumbnail state becomes misleading
- first visible image becomes less reliable
- the visible image becomes less clinically stable without an explicit temporary exception and rollback plan

### Continue to the next phase only if

- the phase-specific KPI gates improved
- live runtime and headless evidence agree
- no protected direct interaction regression is observed

## Definition Of Done

This plan is complete only when all of the following are true:

1. benchmark timings are at least halved versus the locked measured baseline package
2. lag is controlled in live overlap, not only in headless runs
3. stack drag feels as disciplined as wheel interaction
4. thumbnails are cheap, simple, and unambiguous
5. on-demand new-patient or new-series load no longer destabilizes the active viewer
6. the scrolling image remains visually stable and clinically trustworthy
7. overlap CPU stays below `< 80%` on the current benchmark class and host profile as the primary closure target, with `< 50%` retained as the stretch target
8. the result is validated through the repo's cross-PC workflow, not just on one machine

## Relationship To Existing Plans

- `docs/plans/performance/FAST_STORM_AND_PERFORMANCE_PLAN_vNEXT.md` remains the best broad performance/orchestration background plan.
- `docs/plans/implementation/FAST_ORCHESTRATION_REFACTOR_PLAN.md` remains the best refactor skeleton for ownership collapse.
- This document becomes the precise execution plan that combines those documents with the latest live evidence, the latest log findings, the thumbnail simplification requirement, the stack-drag concern, and the final KPI contract.

## Bottom Line

The next pass should not chase one more isolated speed win inside a single component.

It also should not assume that every overlap problem means we need more executors.

The default order should be:

- first reduce simultaneous admitted work in **Block 3**
- then remove the remaining exact visible cost in **Block 2**
- then calm any still-relevant producer disturbance in **Block 1**
- finally prove the result in live overlap on more than one machine

It should make the FAST viewer behave like a coached team:

- one admission owner
- one lifecycle owner
- one redraw owner
- one thumbnail projection contract
- one calmer path for overlap

And from this point on, every package should be explainable in one sentence using the block model:

- **which block changed**
- **which block was protected**
- **which KPI moved**

That is the shortest path to lower CPU, less lag, and a clinically more trustworthy user experience.
