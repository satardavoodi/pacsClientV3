# FAST pipeline complete review — 2026-04-20

## Purpose

This document records a full architecture review of the current FAST pipeline from:

- patient double-click / tab open
- Block A (data / thumbnails / download projection)
- Block B (first visible image / target viewer handoff)
- Block C (progressive grow / cache / scroll orchestration)
- `PipelineOrchestrator`
- database touchpoints and metadata authority

This is a **review document**, not a fix plan. It is intended to preserve the current understanding of what the code actually does today, where the ownership boundaries are strong, and where they are duplicated or fragile.

---

## Executive summary

The current FAST pipeline is **functionally layered but not strictly linear**.

The intended Block A → Block B → Block C story is directionally correct, but the runtime implementation is more like this:

1. **Open hot path** creates the tab immediately and starts study download wiring early.
2. **Block A work is partially front-loaded** (DM start, signal normalization, server-series bootstrap) and partially **deferred until first-series-visible**.
3. **Block B owns the first useful image** and acts as a practical admission barrier for some noncritical A-side network/UI tasks.
4. **Block C owns the live viewer lifecycle** after that point: progressive display, terminal idempotence, viewer-visible admission, completion repair, and cache warm dispatch.
5. `PipelineOrchestrator` is **not the global owner of the full FAST pipeline**. It is a **narrow study-level download phase state machine** that gates preview/warmup policy. It does not own the progressive lifecycle, target-viewer admission, or completion finalization.

That split is workable, but it means the current architecture depends on several pieces of synchronization glue:

- DM progress normalization in `home_download_service.py`
- series UID/number mapping in both home and patient-tab code
- metadata refresh + live-viewer sync in `_vc_cache.py`
- progressive lifecycle guards and one-shot finalization in `_vc_progressive.py`

The main structural risk is **authority fragmentation**, not a single broken algorithm.

---

## Reviewed files

Primary runtime files reviewed in this pass:

- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_cache.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py`
- `modules/viewer/pipeline/orchestrator.py`
- `database/manager.py`

Reference documents reviewed:

- `docs/plans/analysis/BLOCK_A_B_KPI_CLEARCANVAS_HANDOFF_2026-04-20.md`
- `docs/plans/performance/FAST_VIEW_PERFORMANCE_EXECUTION_PLAN.md`
- repo memories for FAST pipeline flow and system-load-controller accounting

---

## Actual end-to-end runtime flow

## 1) Double-click open hot path

In `_hp_patient_open.py`, `_on_patient_double_clicked_async(...)` does all of the following very early:

- blocks duplicate open requests for the same study
- focuses an existing tab if already open
- determines local/offline-cloud/server context
- resolves `output_dir` / study path
- creates the patient tab immediately via `add_new_tab_widget(...)`
- activates the tab immediately
- connects first-series-visible signal handling
- starts a **High priority whole-study download** for server-backed opens
- wires Download Manager signals to the widget

This is important architecturally:

> The user-visible open flow does **not** wait for thumbnails, right-panel population, attachments, or full metadata hydration.

That matches the FAST UX goal.

---

## 2) Block A is split into immediate and deferred lanes

Block A is not a single monolithic pre-B stage.

### Immediate A-side work

These happen before first image visibility:

- DM tab creation / retrieval
- building `dm_study_data`
- optional server series fetch if missing in `study_data`
- `widget.set_server_series_info(series_list)` pre-bootstrap
- `start_priority_download_immediately(...)`
- `connect_dm_to_widget(...)`

### Deferred A-side work

These are explicitly allowed to wait until first-series-visible when `ui_throttle.should_defer_noncritical_open_network(...)` says so:

- series info UI refresh
- right panel study refresh
- attachment download
- some server thumbnail loading retries

The replay barrier is `_on_first_series_loaded()` in `_hp_patient_open.py`, which calls `_run_deferred_patient_open_tasks(...)`.

### Review conclusion

The implementation already encodes a stronger truth than some docs imply:

> Block A is **partly speculative / front-loaded** and **partly post-B replayed**.

That should be documented explicitly anywhere the architecture is described as a clean A-then-B handoff.

---

## 3) HomeDownloadService is the real DM→viewer bridge

`home_download_service.py` is more than wiring glue. It is the runtime authority for **viewer-facing projection** of DM progress.

### What it owns well

- idempotent DM↔widget connection lifecycle
- per-series progress coalescing
- terminal progress normalization
- thumbnail projection start/complete behavior
- duplicate completion suppression
- UID→series-number resolution fallback chain

### Architectural significance

The `_SeriesProgressNormalizer` reserves terminal `current >= total` progress for the definitive completion path and drops provisional terminal progress.

This means:

> The authoritative viewer-facing “series complete” moment is **not raw DM progress**, and it is also **not owned by `PipelineOrchestrator`**. It is normalized here first.

That is a strong design choice, but it means any future refactor must preserve `HomeDownloadService` as the **single terminal projection authority**, or move that authority wholesale elsewhere.

---

## 4) PatientWidget thumbnail layer is also a metadata authority

`_pw_thumbnails.py::set_server_series_info(...)` is not a passive setter.

It:

- initializes `_server_series_info`
- initializes `_series_uid_to_number`
- merges subsequent calls instead of overwriting
- preserves authoritative values like gRPC-derived `image_count`
- schedules server thumbnail loading

This is necessary because `_hp_patient_open.py` can push series info twice:

- once on the main async path
- once again from background setup

### Review conclusion

This is deliberate and correct, but it confirms that:

> “series info” is not owned in only one place. The home layer, thumbnail layer, DM layer, and viewer layer all participate in keeping it stable.

That is manageable, but only if merge/idempotence behavior is preserved.

---

## 5) ViewerController creates the real Block B/C runtime shell

`patient_widget_viewer_controller.py` assembles the FAST runtime around:

- `PipelineOrchestrator`
- `LoadCoordinator`
- `PreviewEngine`
- ZetaBoost / warmup state
- progressive lifecycle timers and guard sets
- telemetry and load shedding hooks

The controller is the practical integration hub.

### Important review point

Although the orchestrator is constructed here, the controller also owns many mechanisms that are **not orchestrator-controlled**:

- `_progressive_series`
- `_progressive_display_done`
- `_progressive_display_inflight`
- `_series_download_completed`
- `_layer2b_complete_guard`
- `_progressive_terminal_complete_guard`
- `_progressive_finalized_series`

So the real runtime model is:

- orchestrator = coarse study download phase
- controller progressive state = fine-grained live-view lifecycle

This is the single most important architecture clarification from this review.

---

## Orchestrator: actual scope vs perceived scope

## What `PipelineOrchestrator` actually owns

`modules/viewer/pipeline/orchestrator.py` is a deterministic study-level state machine:

- `IDLE`
- `DOWNLOADING`
- `POST_DOWNLOAD`
- `READY`

It tracks:

- whether a download session exists
- active per-series download set
- completed-series set
- study-level completion
- preview active vs warmup allowed

### What it does well

- keeps warmup blocked during download
- allows preview only during download
- gives the controller a clean callback on phase transitions
- avoids regressing from `POST_DOWNLOAD` / `READY` back to `DOWNLOADING`

### What it explicitly does **not** own

It does **not** own:

- target-viewer selection
- first-display start decisions
- untargeted deferral policy
- progressive viewer admission cadence
- terminal completion one-shots
- completion repair / sweep logic
- DM terminal pulse normalization

### Review conclusion

The orchestrator is correctly named for a **coarse control-plane policy object**, but not for the entire visible FAST pipeline.

If anyone reads “Orchestrator” as “the single owner of A/B/C sequencing,” they will misunderstand the current system.

This mismatch between name/impression and actual scope is a documentation risk.

---

## Block B: actual role in the current system

Block B is more than “show first image.”

In the current system, it also acts as a practical release point for deferred work:

- `_on_first_series_loaded()` replays deferred open tasks
- untargeted progressive display is intentionally blocked until explicit viewer interest exists
- some thumbnail/network refreshes intentionally wait for first-series-visible

### Review conclusion

Block B is effectively both:

- the first-visual-success stage
- a coordination barrier for releasing noncritical A-side work

That is a good FAST design, but it means B is acting as both **presentation** and **admission control**.

---

## Block C: actual scope is broader than “cache and scroll”

`_vc_progressive.py` shows that Block C owns far more than cache warmup.

It owns:

- progressive lifecycle state map
- done/inflight guards
- untargeted defer guard
- terminal-complete guard
- finalization one-shot guard
- viewer-visible admission gating
- stale-grow retry / exhaustion handling
- Layer 2b / 3 / 4 completion repair
- post-completion cache warm dispatch

### Review conclusion

In practice, Block C is the **live-state correctness layer** for FAST viewer behavior, not just the performance layer.

That is powerful but dangerous: a lot of correctness policy now lives in performance-oriented code.

---

## Database and metadata touchpoints

## Where DB participates directly

### Open path

`_hp_patient_open.py` checks local study presence with `get_study_by_study_uid(study_uid)` and uses stored `study_path` when available.

### Download retry / study reconstruction

`database/manager.py::get_study_info_with_series(...)` reconstructs study + series info from DB, including `image_count`.

### Series metadata lookup

`database/manager.py::get_series_by_study_and_number(...)` resolves per-series DB info by `(study_uid, series_number)`.

### Runtime metadata correction

`database/manager.py::update_series_image_count_by_uid(...)` allows reliable counts to overwrite DB state when a better authority arrives.

---

## Where DB is **not** the sole runtime authority

The code intentionally does **not** trust DB alone for active download/view completeness.

Runtime code also uses:

- DM task `image_count`
- server/gRPC `image_count`
- `metadata['instances']` length
- disk `.dcm` count via `_count_series_files_on_disk(...)`
- viewer slice count

This is visible in:

- DM progress normalization
- progressive grow / completion verify
- thumbnail merge logic
- `_refresh_and_sync_metadata(...)`

### Review conclusion

This is not accidental duplication. It is partly a deliberate defense against stale DB state during active download.

But it has a cost:

> completeness and identity are decided in more than one place, so synchronization helpers are mandatory.

---

## Current strengths

## 1) The open hot path is correctly biased toward immediate UI ownership

The tab opens immediately and defers noncritical work. This is exactly the right shape for FAST behavior.

## 2) DM terminal progress is normalized before it hits viewer logic

`HomeDownloadService` prevents raw completion races from spraying duplicate terminal behavior downstream.

## 3) Progressive finalization is explicitly one-shot

`_finalize_progressive_series(...)` plus multiple guard sets significantly reduces duplicate terminal close/update churn.

## 4) Metadata drift is explicitly acknowledged and patched

`_refresh_and_sync_metadata(...)` is a strong sign that the code understands the difference between:

- stored thumbnail metadata
- live viewer metadata
- on-disk truth

## 5) Untargeted background work is now intentionally blocked from auto-placement

That matches the manual-only placement policy and protects responsiveness.

---

## Structural weaknesses and risks

## 1) Authority is fragmented across too many adjacent layers

### Evidence

- open path owns deferral/replay
- DM service owns terminal projection normalization
- thumbnail layer owns server-series merge stability
- orchestrator owns study download phase
- progressive mixin owns live correctness lifecycle
- cache mixin owns disk-count truth and metadata repair

### Risk

Any refactor that changes one layer “locally” can silently break assumptions in another.

### Assessment

This is the top structural risk.

---

## 2) The orchestrator’s name overstates its real ownership

### Evidence

`PipelineOrchestrator` does not control first-display, progressive start, completion repair, or viewer admission.

### Risk

Future work may incorrectly route more responsibilities into it or assume it already provides guarantees it does not provide.

### Assessment

This is mainly a documentation and mental-model risk, but those are the kinds that grow bugs later.

---

## 3) Series identity resolution is duplicated

### Evidence

- `_SeriesProgressNormalizer` path in `home_download_service.py` resolves UID→number using thumbnail maps, widget maps, and DM task lists
- `_pw_thumbnails.py` maintains `_series_uid_to_number`
- DB helpers resolve by `study_uid + series_number` or `series_uid`

### Risk

If one mapping source is missing or stale, progress can arrive under the wrong identity form at the wrong stage.

### Assessment

Currently mitigated by fallback logic, but still structurally duplicated.

---

## 4) Completeness is multi-sourced and therefore fragile without sync glue

### Evidence

Runtime compares or uses:

- server `image_count`
- DB `image_count`
- metadata instance count
- disk `.dcm` count
- viewer visible slice count

### Risk

Any path that forgets to sync one representation can create “complete but not visible” or “visible but stale metadata” problems.

### Assessment

This duplication is partly necessary, but it should be treated as a first-class architecture fact, not incidental behavior.

---

## 5) Block A/B/C are coordinated by gates in several places, not one place

### Evidence

- first-series-visible replays deferred A tasks
- `ui_throttle.should_defer_noncritical_open_network(...)`
- untargeted progressive defer in `_vc_progressive.py`
- orchestrator state transitions for warmup/preview

### Risk

The sequencing policy is real, but distributed.

### Assessment

Good runtime behavior, medium maintainability risk.

---

## 6) Background setup still intentionally duplicates some setup pushes

### Evidence

`_hp_patient_open.py` can push series info once on the main path and once again from a background setup thread.

### Risk

Without the merge behavior in `_pw_thumbnails.py`, this would clobber better metadata.

### Assessment

Currently safe because merge semantics exist. Still worth documenting as intentional duplication.

---

## 7) Block C mixes performance control with correctness control

### Evidence

`_vc_progressive.py` owns stale recovery, completion repair, finalization idempotence, viewer admission cadence, and cache-warm dispatch.

### Risk

Performance tuning in Block C can accidentally become correctness tuning.

### Assessment

This is probably the most subtle long-term risk after authority fragmentation.

---

## Recommended documentation clarifications

The following should be treated as current truth in future docs and reviews:

1. **Block A is split** into immediate and deferred lanes.
2. **First-series-visible is a real release barrier**, not just a cosmetic milestone.
3. **`PipelineOrchestrator` is a coarse study download phase machine**, not the sole owner of FAST sequencing.
4. **HomeDownloadService is the viewer-facing DM terminal authority.**
5. **Progressive lifecycle correctness is owned by `_vc_progressive.py`, not by the orchestrator.**
6. **DB metadata is important but not sufficient** for active-download completeness or final viewer truth.
7. **Manual-only untargeted layout insertion is already enforced in code** and should remain part of the contract.

---

## Suggested future fix themes

These are not implementation instructions yet, only likely improvement themes.

### Theme 1: clarify authority boundaries

Potential target:

- orchestrator = study download phase only
- DM service = download projection only
- progressive controller = viewer lifecycle only
- metadata service = identity/completeness resolution only

### Theme 2: centralize series identity resolution

There is a good case for one reusable resolver for:

- series UID
- series number
- DB row identity
- thumbnail identity

### Theme 3: centralize completeness truth composition

Instead of ad hoc comparisons, consider one helper or service that explains:

- expected count
- on-disk count
- viewer-admitted count
- viewer-actual count
- metadata count

### Theme 4: separate correctness policy from performance throttling where possible

Block C currently carries both.

---

## Bottom line

The current FAST architecture is **not broken**, but it is **more distributed than the high-level block diagrams suggest**.

The strongest factual takeaway from this review is:

> The visible FAST pipeline is not orchestrated by one object. It is coordinated by a set of cooperating authorities, each with a narrower role than the word “pipeline” might imply.

That design has produced good runtime behavior, but it also means future fixes must be very explicit about which layer owns:

- identity
- completeness
- terminal authority
- first-visible gating
- post-download warmup gating
- viewer-lifecycle finalization

If those ownership lines are clarified in future refactors, the FAST pipeline should become significantly easier to evolve without regressions.