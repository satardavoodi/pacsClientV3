## Plan: FAST Storm vNext

This plan consolidates the current AI-PACS FAST performance truth, the existing repo plans/docs, the current runtime code, the benchmark evidence, and the ClearCanvas/Cornerstone workstation-oriented lessons already gathered in this workspace. The core conclusion is that the remaining bottleneck is no longer raw decode/render speed; it is a control-plane storm caused by distributed non-interactive work admission, multi-authority progressive lifecycle handling, progress fan-out, and duplicated follow-up work during overlap. The recommended direction is to preserve the current FAST renderer/cache wins, but move toward a calmer workstation pattern: central request ownership, staged/background admission before work starts, one progressive lifecycle owner, one viewer-facing progress contract, and one redraw follow-up coordinator.

**Steps**
1. Consolidate the current truth into one vNext plan that supersedes stale decode-first assumptions and names the remaining storm sources precisely. Completed.
2. Use the new plan as the execution baseline for the next implementation pass, with phases ordered by ROI and validation gates. Completed as part of the plan below.

**Relevant files**
- `c:\AI-Pacs codes\aipacs-pydicom2d\docs\plans\plan.md` — current master plan; still valid for completed FAST data-path work, but its next-step emphasis now needs a control-plane-first correction.
- `c:\AI-Pacs codes\aipacs-pydicom2d\docs\performance\PERFORMANCE_STATUS.md` — most important source for current measured truth, including `run_001` and `run_002` headless evidence.
- `c:\AI-Pacs codes\aipacs-pydicom2d\docs\plans\performance\FAST_VIEWER_PERFORMANCE_ROADMAP.md` — still useful for planning discipline, but too generic for the next storm-focused pass.
- `c:\AI-Pacs codes\aipacs-pydicom2d\docs\performance\CONCURRENCY_ANALYSIS_v2.3.3.md` — helpful background, but parts of its decode/GIL-first emphasis are now secondary to control-plane evidence.
- `c:\AI-Pacs codes\aipacs-pydicom2d\docs\analysis\CLEARCANVAS_WORKSTATION_COMPARISON.md` — local workstation-reference lesson: simplify ownership and mediator patterns, not rendering mechanics.
- `c:\AI-Pacs codes\aipacs-pydicom2d\docs\analysis\CLEARCANVAS_DIVERGENCE_MATRIX.md` — explicit statement that AI-PACS needs ClearCanvas-like ownership discipline while preserving harder live-download behavior.
- `c:\AI-Pacs codes\aipacs-pydicom2d\docs\analysis\CLEARCANVAS_KPI_MAPPING.md` — maps structural differences to user-facing KPI damage.
- `c:\AI-Pacs codes\aipacs-pydicom2d\docs\analysis\ORCHESTRATION_ROOT_CAUSES.md` — strongest current statement of the remaining problem: progressive over-authority, UI fan-out, distributed admission, redraw spread.
- `c:\AI-Pacs codes\aipacs-pydicom2d\docs\architecture\FAST_ORCHESTRATION_TARGET.md` — already defines the right target shape: one admission gate, one progressive owner, one redraw coordinator.
- `c:\AI-Pacs codes\aipacs-pydicom2d\docs\plans\implementation\FAST_ORCHESTRATION_REFACTOR_PLAN.md` — still the best incremental sequence skeleton, but should now be reframed as the central next plan rather than one sub-plan among many.
- `c:\AI-Pacs codes\aipacs-pydicom2d\docs\plans\analysis\CLEARCANVAS_KPI_SCORECARD_AND_PLAN_UPDATE.md` — current repo truth that overlap loss is control-plane churn, not bad FAST rendering.
- `c:\AI-Pacs codes\aipacs-pydicom2d\docs\analysis\CORNERSTONE_ADMISSION_AND_ORCHESTRATION_REPORT.md` — strongest evidence for central request ownership and queue-class admission.
- `c:\AI-Pacs codes\aipacs-pydicom2d\docs\analysis\CORNERSTONE_TO_AIPACS_ACTION_MATRIX.md` — adopt/adapt/reject mapping for next-pass changes.
- `c:\AI-Pacs codes\aipacs-pydicom2d\docs\analysis\CORNERSTONE_MIGRATION_CANDIDATES.md` — ranked ROI list for the next architecture moves.
- `c:\AI-Pacs codes\aipacs-pydicom2d\modules\viewer\fast\lightweight_2d_pipeline.py` — current FAST render/cache owner; should remain cache/render authority, but should stop directly acting as a global admission authority for background work.
- `c:\AI-Pacs codes\aipacs-pydicom2d\modules\viewer\fast\qt_viewer_bridge.py` — direct interaction path; should remain sacred/immediate.
- `c:\AI-Pacs codes\aipacs-pydicom2d\modules\viewer\fast\ui_throttle.py` — current policy facade; should remain facade, but point to one real admission owner.
- `c:\AI-Pacs codes\aipacs-pydicom2d\modules\viewer\fast\system_load_controller.py` — current policy brain; should become the policy source behind a central admission controller/scheduler.
- `c:\AI-Pacs codes\aipacs-pydicom2d\modules\viewer\pipeline\orchestrator.py` — correct study/series state source; should stay a state oracle, not become another UI authority.
- `c:\AI-Pacs codes\aipacs-pydicom2d\PacsClient\pacs\patient_tab\ui\patient_ui\_vc_progressive.py` — current highest-value simplification target; too much lifecycle authority still lives here.
- `c:\AI-Pacs codes\aipacs-pydicom2d\PacsClient\pacs\patient_tab\ui\patient_ui\_vc_warmup.py` — helper/background warmup behaviors; must stay subordinate to protected UI policy.
- `c:\AI-Pacs codes\aipacs-pydicom2d\PacsClient\pacs\workstation_ui\home_ui\home_download_service.py` — current progress gateway; should become a true event normalizer rather than a multi-consumer fan-out source.
- `c:\AI-Pacs codes\aipacs-pydicom2d\PacsClient\pacs\workstation_ui\home_ui\home_db_service.py` — not the storm bottleneck; keep DB work out of the viewer hot path and avoid giving it new runtime authority.
- `c:\AI-Pacs codes\aipacs-pydicom2d\PacsClient\pacs\patient_tab\utils\thumbnail_manager.py` — should become projection-only, not a lifecycle peer.
- `c:\AI-Pacs codes\aipacs-pydicom2d\PacsClient\pacs\patient_tab\ui\patient_ui\patient_widget_viewer_controller.py` — integration point for orchestrator, progressive display, and viewer-facing behaviors.
- `c:\AI-Pacs codes\aipacs-pydicom2d\tests\viewer\test_fast_viewer_pipeline.py` — core progressive/lifecycle/FAST integration coverage.
- `c:\AI-Pacs codes\aipacs-pydicom2d\tests\viewer\test_b43_progressive_lifecycle_state.py` — lifecycle state-map coverage.
- `c:\AI-Pacs codes\aipacs-pydicom2d\tests\viewer\test_cp1_control_plane_governance.py` — current orchestration governance coverage.
- `c:\AI-Pacs codes\aipacs-pydicom2d\tests\viewer\test_system_load_controller.py` — admission policy behavior tests.
- `c:\AI-Pacs codes\aipacs-pydicom2d\tests\viewer\test_dragdrop_progressive.py` — live progressive display/series switch coverage.
- `c:\AI-Pacs codes\aipacs-pydicom2d\tests\viewer\test_fast_download_scroll_cpu_repro.py` — important storm/regression evidence harness.
- `c:\AI-Pacs codes\aipacs-pydicom2d\tests\performance\test_b25_scenarios.py` — baseline scenario harness.
- `c:\AI-Pacs codes\aipacs-pydicom2d\tests\performance\test_clearcanvas_aipacs_kpi_harness.py` and `c:\AI-Pacs codes\aipacs-pydicom2d\tools\performance\clearcanvas_aipacs_kpi_harness.py` — KPI comparison and headless recapture tools.
- `c:\AI-Pacs codes\aipacs-pydicom2d\generated-files\benchmarks\run_001\*` and `...\run_002\*` — latest measured benchmark truth.

## Plan: FAST Storm and Performance Plan vNext

### A. Current truth

The current repo truth is now clear:
- The FAST data path is no longer the primary problem. Cache-hot interaction is commonly in the ~2–5ms class, and multiple recent optimizations already landed: disk pixel cache, decode-service isolation, cache-first fast scroll, exact-vs-surrogate wheel/drag split, protected UI throttles, and completion/lifecycle hardening.
- The remaining problem is a **storm/control-plane problem**, not a raw decode or render problem. The strongest evidence is that under overlap the user-facing KPIs still regress even when `decode_ms` improves or is zero.
- `run_001` and `run_002` headless captures show the same pattern:
  - `first_image_visible_ms` remains far worse under overlap than local baseline.
  - `stale_task_ratio` remains pinned around ~0.95–0.99, which means too much background work is still admitted relative to what the user needs.
  - overlap `cpu_p95_pct` is still too high and even worsened in `run_002`, despite latency improvements in the harness.
- Therefore the real remaining bottleneck is:
  - **control-plane fragmentation** causing
  - **over-admission of non-interactive work** causing
  - **progress fan-out and progressive lifecycle churn** causing
  - **duplicated or mistimed background work** during user interaction and download overlap.
- Decode and render are now **secondary contributors**, not the main next-pass target.
- The current code truth also shows that some older documentation assumptions are stale: progressive layer descriptions in docs still imply explicit Layer 2b/3/4 authority methods, while current code has already partly collapsed those behaviors into more helper/state-driven paths. The new plan should explicitly treat the repo as partway through an authority-collapse refactor, not at the older “many equal completion layers” stage.

### B. Valid carried-forward decisions

The following prior decisions remain correct and should stay:
- **FAST / Advanced separation** remains mandatory. FAST optimization must not bleed VTK/Advanced behavior back into the pydicom-Qt path.
- **Keep `Lightweight2DPipeline` as the FAST cache/render authority.** The pipeline, its pixel/frame cache, disk cache, and decode-service helper stack are still the correct home for 2D render truth.
- **Disk pixel cache remains high ROI and correct.** It is not the storm source and should not be revisited as a primary optimization target.
- **Decode isolation remains correct.** The decode service, although not the final architecture story, is still a valid helper and not the main overlap regression source.
- **Wheel exact vs stack-drag surrogate policy remains correct.** Precision browsing must stay exact; navigation may approximate transiently. This is aligned with stable workstation behavior.
- **Shared policy shell remains correct.** `SystemLoadController` + `ui_throttle` were the right direction; they should be strengthened via central enforcement rather than discarded.
- **Series-level readiness / viewed-series relief remains correct.** Current-series work should be favored over unrelated study-wide pressure.
- **Post-download helper work must remain subordinate to interaction.** Warmup/prefetch/cache-warm work should exist, but only as admitted, deferrable helpers.
- **Live progressive download support remains a required AI-PACS divergence.** We should become calmer like ClearCanvas/Cornerstone in ownership, but not regress to a simpler non-live model they had the luxury of solving.

### C. What should be simplified or reduced

The next pass should explicitly reduce the following complexity areas:
- **Progressive lifecycle over-authority** in `_vc_progressive.py`. Too many compatibility guards, transition helpers, and recovery paths still behave like peers instead of one owner plus recovery observers.
- **Viewer-facing progress fan-out** from `home_download_service.py` into progressive display, thumbnails, completion pulses, and related UI consumers. One raw DM event still does too much downstream work.
- **Distributed admission decisions** spread across `ui_throttle`, the bridge, the pipeline, progressive handlers, and thumbnail/progress consumers. The project has a policy vocabulary but not yet a single owner enforcing it.
- **Scattered redraw follow-up** for sync/reference-line/secondary UI work. Multiple small “helpful” callbacks still compete with interaction-critical rendering.
- **Independent local calming logic** across subsystems. Several parts of the code coalesce or defer correctly, but they do so as separate authorities rather than one coordinated system.
- **Documentation divergence** between `docs/plans/plan.md`, `docs/analysis/*`, and the current code. The old plan still over-emphasizes decode/concurrency-first next steps, while current evidence says the next pass must be orchestration-first.
- **Duplicate doc trees** under `docs\analysis` and `docs\clear canvas` should be treated as a consistency risk; the vNext plan should name one canonical path and note the duplicate tree as a maintenance concern.

### D. Cornerstone-Windows-inspired guidance

The practical lesson from the local Cornerstone study is not “copy the web stack.” The relevant stable pattern is:
- **central request ownership**
- **request-class separation**
- **admission-before-work**
- **queue/filter stale work by identity**
- **stage-driven progressive behavior instead of callback-driven improvisation**
- **one owner for visible lifecycle state**
- **background UI consumers as projections, not peers**
- **separation of create/own/fill**, so work order can change without changing state authority.

For AI-PACS, apply directly:
- one central admission owner for non-interactive FAST work;
- one progressive lifecycle owner;
- one viewer-facing progress contract;
- request classes that distinguish visible correctness from cosmetics and best-effort helpers;
- identity-based stale-work filtering.

Adapt for Python/Qt:
- do not literally copy browser/XHR retrieval pools;
- keep the direct synchronous `set_slice()` interaction path;
- use Qt-friendly coalescing/marshaling, but make admission central before those callbacks fire;
- keep live progressive download semantics, because AI-PACS solves a harder problem than the reference apps.

Do **not** apply directly:
- Cornerstone’s browser transport assumptions;
- exact cache topology;
- any queue ranking that places thumbnail work above user-visible viewed-series correctness without evidence;
- any assumption that AI-PACS can simplify down to a non-progressive workstation model.

The combined workstation lesson from ClearCanvas + Cornerstone is:
- **ClearCanvas** contributes calm ownership and mediator discipline.
- **Cornerstone** contributes explicit request ownership and request-class admission.
- AI-PACS should borrow both concepts while keeping its stronger live-download data path.

### E. New target architecture

The target architecture for the next pass should be:
- **Direct interaction path remains untouched in principle**:
  - `QtViewerBridge.set_slice()` → `Lightweight2DPipeline` stays direct, synchronous, and top priority.
- **One non-interactive admission owner**:
  - a FAST admission controller or lightweight scheduler becomes the only legal gate for non-interactive work.
  - `SystemLoadController` remains the policy brain feeding it.
- **One progressive lifecycle owner**:
  - progressive state for a `(series, epoch)` is owned by a single component, not reconstructed by several guard layers.
  - terminal close becomes truly one-shot.
  - verification/sweep may confirm or recover, but not behave like parallel terminal authorities.
- **One viewer-facing progress stream**:
  - `home_download_service.py` should normalize raw DM progress/completion events into one canonical per-series stream.
  - progressive display and thumbnails consume that stream after admission, not before.
- **Thumbnail manager becomes projection-only**:
  - it reflects admitted state; it does not influence lifecycle urgency.
- **One redraw follow-up coordinator**:
  - sync/reference-line/secondary repaint work is queued and deduplicated explicitly after direct visible interaction work.
- **Current-series vs global-study pressure must be explicit**:
  - viewed/current series can receive a higher budget for visible correctness, grow, and local prefetch.
  - unrelated study-wide work stays throttled harder.
- **Warmup/cache-warm/helper work remains outside the critical owner**:
  - helpers may request work, but only as best-effort, deferrable tasks admitted by the same central gate.

Conceptually, the new direction is:
- `Download Manager` → `FAST Event Normalizer` → `FAST Admission Owner`
- then to:
  - `FAST Progressive Lifecycle Owner`
  - `Thumbnail Projection`
  - `Redraw Coordinator`
  - `Cache Warm Requestor`
- while `set_slice()` remains a sacred direct path.

### F. KPI model

The KPI model should now distinguish leading indicators from lagging indicators.

**Leading indicators**: these tell us early whether the storm is being reduced.
- `terminal_completion_duplicate_count` per `(series, epoch)` — target `0`
- `cache_warm_duplicate_count` per `(series, epoch)` — target `0`
- `stale_task_ratio` under overlap — move from ~0.99 toward `<0.50` first, then toward `<0.35`
- `ui_event_loop_lag_ms` (callback-gap estimate) — target `<20ms` P95 during active interaction
- `foreground_wait_p95_ms` — target `<5ms`
- viewer-facing progress update cadence / burst rate — should reduce materially and become bounded under overlap
- scheduler/admission metrics per work class: admitted, deferred, dropped, stale-dropped counts

**Lagging indicators**: these are the user-visible outcomes.
- `set_slice_present_p95_ms` under overlap — target `<16ms` for interaction class; acceptable settle tails `<25ms`
- `first_image_visible_ms` under overlap — target meaningful improvement from current ~1100–1400ms class toward `<500–800ms`
- `cpu_p95_pct` under overlap — move from current ~166–189% toward `<120–135%` on the current benchmark class
- `slow_frame_count_16ms` under overlap — trend sharply downward and remain stable in repeated runs
- `cache_hit_ratio_pct` near current/viewed series — improve or at minimum stop degrading during overlap

**Interpretation rule**
- Headless improvements alone are not enough. A phase only counts as successful when headless metrics and live runtime/log evidence agree that duplicate terminal churn and interaction-visible lag both improved.

### Reality update — non-terminal viewer admission gate (2026-04-16)

Part of this plan has now shipped as a targeted viewer-side admission layer.

What changed:
- non-terminal progressive growth is no longer allowed to expose the full `pending_downloaded` count to the viewer in one jump
- `_flush_progressive_grow_impl()` advances viewer-visible slices in bounded batches via `_progressive_admit_batch_size`
- terminal completion is still uncapped so the final full series appears immediately once `downloaded >= total`

Why this matters:
- it attacks the remaining internal-network burst problem directly at the viewer admission point
- it does **not** slow the downloader itself
- it gives us a simpler observable metric: burst shock at the viewer edge

Validation added with this change:
- `tests/viewer/test_progressive_admission_storm.py` compares ungated vs gated burst shock
- the same file verifies bounded extra grow ticks and a CPU-pressure storm harness so the test is hot, not merely callback-dense

### Stack path, gating, and other solutions

This plan should continue to separate work classes instead of applying one rule everywhere:

- **stack / wheel / drag**: keep direct and immediate
- **progressive viewer admission**: gate in bounded steps
- **prefetch / cache warm / fan-out / refresh follow-up work**: defer, coalesce, or drop under protected UI windows

That split is deliberate. The user interaction path should stay sacred; the burst-prone background path is where gating belongs.

### G. Implementation phases

#### Phase P1 — Truth alignment and event normalization foundation

**Objective**
- Freeze the next-pass scope around the real problem: control-plane storm, not decoder heroics.
- Normalize the raw DM-to-viewer progress contract so later refactors do not keep fanning out at the source.

**Target files**
- `home_download_service.py`
- `patient_widget_viewer_controller.py`
- `_vc_progressive.py`
- `thumbnail_manager.py`
- new event-normalizer helper under FAST/patient UI ownership
- documentation files named in this plan

**Expected KPI movement**
- leading: lower viewer progress burst rate, lower duplicate downstream update triggers
- lagging: modest CPU improvement; little direct frame-latency gain yet

**Risk**
- medium — signal wiring regressions and missing terminal progress semantics

**Validation requirements**
- keep final completion pulse semantics intact
- rerun progressive lifecycle and drag-drop suites
- verify one admitted viewer-facing progress stream per series

**Rollback condition**
- if final grow no longer happens exactly once or if thumbnails/progressive display miss completion state, revert the event-normalization wiring.

#### Phase P2 — Single progressive terminal authority

**Objective**
- make terminal completion one-shot per `(series, epoch)` and demote verification/sweep to recovery roles only.

**Target files**
- `_vc_progressive.py`
- `patient_widget_viewer_controller.py`
- any helper/state wrappers already introduced around lifecycle state

**Expected KPI movement**
- leading: `terminal_completion_duplicate_count` → 0; `cache_warm_duplicate_count` → 0
- lagging: lower overlap CPU, lower live callback-gap spikes, lower latency tails during terminal periods

**Risk**
- medium-high — correctness-sensitive, especially restart-after-DONE and partial-cycle recovery

**Validation requirements**
- rerun `test_fast_viewer_pipeline.py`
- rerun `test_b43_progressive_lifecycle_state.py`
- rerun `test_dragdrop_progressive.py`
- rerun repeated-open / restart-after-DONE diagnostics
- capture live runtime log to verify duplicate COMPLETE/cache-warm markers vanish

**Rollback condition**
- any regression in progressive recovery, restart-after-DONE, or missing last slices under completion pressure.

#### Phase P3 — Central non-interactive admission controller / scheduler shell

**Objective**
- make one owner responsible for admitting non-interactive FAST work using request classes and protected-mode policy.

**Target files**
- `system_load_controller.py`
- `ui_throttle.py`
- new FAST admission controller or scheduler shell under `modules\viewer\fast\`
- `lightweight_2d_pipeline.py`
- `_vc_progressive.py`
- `thumbnail_manager.py`
- `_vc_warmup.py`

**Expected KPI movement**
- leading: lower `stale_task_ratio`, lower `foreground_wait_p95_ms`, explicit admit/defer/drop counters per class
- lagging: improved `set_slice_present_p95_ms` under overlap, lower CPU

**Risk**
- medium — if too broad, it can become a rewrite instead of a bounded admission shell

**Validation requirements**
- keep direct interaction immediate
- rerun `test_system_load_controller.py`
- rerun `test_cp1_control_plane_governance.py`
- rerun `test_fast_download_scroll_cpu_repro.py`
- rerun benchmark harness `run-aipacs-headless` common + overlap
- compare against `run_001` and `run_002`

**Rollback condition**
- if interaction path latency regresses or if the admission shell introduces starvation of visible grow/terminal work.

#### Phase P4 — Redraw follow-up coordination and thumbnail demotion

**Objective**
- remove remaining scattered redraw/cosmetic urgency from the interaction-critical path.

**Target files**
- `thumbnail_manager.py`
- likely sync/reference-line related viewer/controller files
- new redraw coordinator helper/component
- `qt_viewer_bridge.py` integration points if needed for scheduling after exact visible work

**Expected KPI movement**
- leading: fewer redraw bursts, fewer cosmetic updates admitted during protected UI, lower `ui_event_loop_lag_ms`
- lagging: lower tail latency in multi-view/sync-enabled scenarios

**Risk**
- medium — sync correctness and perceived thumbnail freshness

**Validation requirements**
- rerun sync/reference-line relevant viewer tests
- rerun `test_fast_viewer_live_sync.py`
- manual/runtime multi-view scroll during overlap
- verify thumbnail state remains correct though not urgent

**Rollback condition**
- if sync/reference lines fall behind correctness requirements or if thumbnail state becomes misleading.

#### Phase P5 — Current-series priority refinement and helper work shedding

**Objective**
- refine current-series vs global-study pressure handling and make helper work best-effort only.

**Target files**
- `orchestrator.py`
- `ui_throttle.py`
- `system_load_controller.py`
- `_vc_warmup.py`
- `lightweight_2d_pipeline.py`

**Expected KPI movement**
- leading: lower stale helper work, improved local cache usefulness near current series, better class-level drop/defer ratios
- lagging: improved overlap responsiveness without hurting viewed-series continuity

**Risk**
- medium-low if done after admission ownership is stable

**Validation requirements**
- benchmark current viewed series while unrelated series download
- verify completed viewed series can still recover full local prefetch budget appropriately
- verify helper work never outranks visible correctness

**Rollback condition**
- if current viewed series becomes starved by study-wide pressure or if helper deferral causes visible incompleteness.

### H. Test / benchmark requirements

The new plan should require both existing suites and new targeted coverage.

**Existing suites that must be updated or rerun after each relevant phase**
- `tests\viewer\test_fast_viewer_pipeline.py`
- `tests\viewer\test_b43_progressive_lifecycle_state.py`
- `tests\viewer\test_cp1_control_plane_governance.py`
- `tests\viewer\test_system_load_controller.py`
- `tests\viewer\test_dragdrop_progressive.py`
- `tests\viewer\test_fast_download_scroll_cpu_repro.py`
- `tests\viewer\test_fast_viewer_live_sync.py`
- `tests\performance\test_b25_scenarios.py`
- `tests\performance\test_clearcanvas_aipacs_kpi_harness.py`
- `tests\download_manager\run_dm_test.py` for DM-side regressions around progress/completion contracts
- `tests\load\run_load_test.py` for multi-patient/mixed-load regression coverage

**New tests required**
- event normalizer tests:
  - one raw DM progress burst in, one canonical admitted update stream out
  - canonical terminal pulse behavior
- admission-owner tests:
  - per work class admit/defer/drop behavior
  - identity-based stale queue filtering by `(viewer, series, epoch, class)`
- progressive one-shot terminal tests:
  - duplicate late callbacks do not recreate active lifecycle state
  - restart-after-DONE still works for verified new partial cycles
- redraw coordinator tests:
  - dedup sync/reference-line follow-up under bursty interaction
- thumbnail projection tests:
  - thumbnail updates reflect state but never act as lifecycle peers

**Benchmark / runtime requirements by phase**
- Re-run `run-aipacs-headless` common + overlap after P2 and P3 at minimum.
- Compare against `generated-files\benchmarks\run_001\*` and `run_002\*`.
- Continue to use ClearCanvas/Cornerstone local benchmark assets already in repo as the comparison framework, but do not claim any new external comparison unless a real runtime run occurs.
- Add a required live runtime/log capture after P2 and after P3, because headless-only evidence is insufficient for the storm problem.
- Keep benchmark artifacts timestamped and comparable across phases.

### I. Plan consistency notes

This vNext plan keeps, replaces, and supersedes the earlier planning corpus as follows:
- It **keeps** the completed FAST data-path wins and their rationale:
  - cache improvements
  - disk cache
  - decode service
  - exact vs surrogate interaction policy
  - protected UI throttles
  - series-level readiness handling
- It **keeps** the planning discipline from `FAST_VIEWER_PERFORMANCE_ROADMAP.md` — bounded phases, KPI gates, stop/go checkpoints.
- It **keeps** the target shape from `FAST_ORCHESTRATION_TARGET.md` and the incremental spirit of `FAST_ORCHESTRATION_REFACTOR_PLAN.md`.
- It **supersedes** any remaining implication that the next pass should primarily be decoder/GIL/worker-budget tuning. Those are now secondary unless new evidence says otherwise.
- It **supersedes** older multi-layer progressive descriptions where Layer 2/3/4 are treated like equal peers. The new plan treats them as a one-owner lifecycle with recovery observers.
- It **demotes** broad concurrency-tuning ideas from `CONCURRENCY_ANALYSIS_v2.3.3.md` to later-phase refinements. That document remains useful background, but the next pass should not begin with worker-count tuning or a decode-pool rewrite.
- It **replaces** the repo’s fragmented “performance next step” narrative with one simpler statement:
  - the next pass is about reducing the overlap storm by collapsing authority and normalizing work admission.

**Decisions**
- Included scope: FAST-only control-plane/performance architecture, progressive lifecycle, progress/event normalization, admission ownership, redraw follow-up, benchmark/test requirements.
- Excluded scope: Advanced/VTK changes, new decoder backends as the primary next step, browser-only transport patterns, broad rewrite of `Lightweight2DPipeline`, claiming the problem is solved based on headless evidence alone.
- Canonical reference interpretation: use the local ClearCanvas and Cornerstone materials already in this repo as the practical reference base; borrow ownership/admission discipline, not foreign runtime mechanics.

**Verification**
1. Confirm that this plan’s priorities align with current measured truth: overlap CPU and stale-task ratio remain the key unsolved KPIs despite render/decode gains.
2. Confirm that every proposed phase maps to concrete files and existing tests already present in the workspace.
3. Confirm that the plan does not regress FAST/Advanced separation or re-open a decode-first optimization loop without new evidence.
4. Confirm that the plan explicitly requires live runtime validation in addition to headless benchmark recapture.
5. Save this content under `c:\AI-Pacs codes\aipacs-pydicom2d\docs\plans\performance\FAST_STORM_AND_PERFORMANCE_PLAN_vNEXT.md` and update stale cross-references as needed so it remains the canonical next-step plan.
