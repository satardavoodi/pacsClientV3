# AIPacs Architecture Review — Step Back from KPI Patches

**Date:** 2026-04-30
**Author:** GitHub Copilot (architecture pass at user request)
**Scope:** Download Manager, Qt/PySide UI, Viewer Widget, Thumbnails, Drag-and-Drop, DB, Disk/RAM, UI/UX consistency
**Status:** Assessment & recommendation. **No code changes proposed in this document.**

---

## 1. Executive Summary

| Area | Original goal | Current state | Verdict |
|---|---|---|---|
| Download Manager *core* (state, rules, coordinator, observers) | Priority-aware, preemption-capable, observable queue | Sound architecture, well-tested (DM 27 + Stress 10 + Load 11 + KPI 25) | **Healthy. Keep.** |
| Download Manager *UI widget* | Simple list + controls | 9 mixins, 893 lines for `_dm_details.py` alone, recursion + ghost-signal class of bugs (R22) | **Partial redesign. Split UI from controller.** |
| Drag-drop priority chain | drop → CRITICAL → preempt → resume | Functionally correct, but path is 6+ hops with two latches and three timers | **Healthy semantics, but observability/instrumentation contract should be formalized.** |
| Patient double-click HIGH/CRITICAL elevation | Open → CRITICAL on viewed series, HIGH on other series of that study | Works. Drag-drop reliably elevates. | **Healthy.** |
| Viewer widget | Fast 2D rendering pipeline + Advanced VTK | FAST core is well-isolated (`Lightweight2DPipeline`, `QtViewerBridge`); legacy VTK widget is a 3609-line god class; controller-mixin layer is 2453 lines for one mixin | **Partial redesign. Decompose `_vc_progressive.py`, `_vc_load.py`, `qt_viewer_bridge.py`. Quarantine `_legacy_widget.py`.** |
| Thumbnails | Background thumbs + progressive overlay | Functional, idempotent emits added recently. Lives in `utils/thumbnail_manager.py`. | **Healthy. Document the projection contract once.** |
| Database | SQLite WAL + connection pool + observer-driven writes | Clean (R7-style commit rule, FK indexes, no read_uncommitted). Some scattered ad-hoc CRUD. | **Healthy. Consolidate CRUD into a thin DAO layer.** |
| Disk cache (decoded pixels) | L2 disk cache for re-open speed | Clean: `disk_pixel_cache.py` is small, isolated, documented. | **Healthy.** |
| RAM cache | Per-pipeline pixel cache + frame cache; ZetaBoost L1 RAM (Advanced); per-controller `_full_series_cache` | Multiple unrelated caches with overlapping responsibilities. Eviction policies are scattered. | **Partial redesign. Single CacheManager facade with named regions.** |
| Qt threading model | Qt event loop + qasync + executor threads + subprocesses | Mostly correct, but **597 `QTimer.singleShot` calls in `PacsClient/`**, **107 in DM**, **289 in viewer**. Marshaling has become a cross-cutting concern. | **Partial redesign. Centralize "post to UI thread" + "schedule once" idioms. Audit cooldowns/deferrals for ownership.** |
| Logging / observability | Async queue logger + per-component thresholds | Excellent design (R7) but 3 separate bugs (R13 SP, R22 DM_REBUILD, R19 INTENT_PRIORITY) caused by component-threshold filter silently dropping INFO. | **Healthy infra, broken contract. Lint rule needed.** |
| UI/UX consistency with backend | Fast feedback on every state change | Mostly aligned. Stale-on-drop and progressive grow have one-way information flow (download → view) but priority promotion has no visible UI confirmation pre-row-rebuild. | **Minor UI work, not redesign.** |

**Bottom line:** the architecture is **mostly sound at the module-system level**. The trouble is concentrated in **3 specific files** where complexity has escalated to the point that any KPI fix risks introducing a new defect. Three of the last four production bugs (`[SP]` silent drop, `[DM_REBUILD]` recursion, `[INTENT_PRIORITY]` silent drop) all share the same surface root cause: **a cross-cutting contract is implicit in the code**, so each new emit/timer/observer site has to re-discover it.

We do **not** need a full redesign. We need:

1. Fix the silent contract (component log thresholds) by lint, not by remembering.
2. Decompose the 3 god classes (`toolbar_manager.py`, `_legacy_widget.py`, `_vc_progressive.py`).
3. Consolidate cross-cutting facades (UI thread post; cache regions; admission gate).
4. Continue KPI work **after** items 1-3, with much higher confidence per change.

---

## 2. Original Goals vs Current Implementation

The architecture as documented in `.github/copilot-instructions.md` and the v2.x release notes was built around five clear goals:

| Original goal | Current state |
|---|---|
| **G1.** FAST viewer (PyDicom + Qt) is the default; Advanced (VTK) for MPR/3D. | ✅ Achieved. v2.3.3 made FAST default; the resolver alias (R-Stage1/Stage2) protects against drift. |
| **G2.** Each module (viewer, DM, thumbnails) is an independent loop; no cross-module main-thread blocking >16 ms. | ✅ At the *boundary*. ⚠️ Inside FAST viewer, multi-second drag bursts now meet the budget only because R1-R15 chain together. Removing any one breaks it. |
| **G3.** Priorities (LOW→NORMAL→HIGH→CRITICAL) drive who downloads first, with drag-drop = CRITICAL and patient open = HIGH. | ✅ Semantically correct. R19/R20 instrument it; live evidence shows recurring exhaust on series=202/203 but the *promotion mechanic* is sound. |
| **G4.** Progressive display: download progress should be visible incrementally, not after 100% complete. | ✅ With caveats. 4-layer completion protocol (Layer 1-4 in `_vc_progressive.py`) covers OS-flush races and drop-recovery; complexity is high but justified. |
| **G5.** Build/install is portable: clone → setup → build → installer. ProgramData for shared config, LocalAppData for user data, Program Files for binaries. | ✅ Achieved in v2.4.5+. Dual builders (PyInstaller + Nuitka) fully separated. |

**Mismatch between goals and implementation:** **none structurally.** The goals are intact. What has accumulated is **incidental complexity to keep them intact**:

- 4-layer completion protocol exists because Qt signal ordering across DM throttle, OS file-flush latency, and viewer state-machine were not designed as one contract.
- 15 numbered rules R1-R22 in `copilot-instructions.md` exist because each fix found a corner the abstraction did not cover.
- 6 mixin folders (DM=9, VC=7, PW=9, HP=10, VW=10, ZB=5) = **50 mixin files** exist because the original god classes were broken up *by extraction* without picking new responsibility boundaries.

This is the classic "mixin-flat-file refactor" — a working step out of god-class territory but **not yet a layered design**. Mixins share the same `self`; they cannot enforce invariants across each other.

---

## 3. Per-Module Assessment

### 3.1 Download Manager Core

**Files:** `modules/download_manager/{core,state,rules,coordinator,download,workers,network,storage}/**`

**What is correct:**
- `DownloadStateStore` is a pure in-memory DB with observer fan-out. State machine is explicit.
- 5 observers (UI, DB, Priority, Logging, Validation) are decoupled.
- `RuleEngine` (R17a/b/c, R19b, R20) has named, individually-testable rules.
- `SeriesIntentCoordinator` owns priority negotiation and series-interrupt; UI never mutates queue state directly.
- 27 + 10 + 11 + 25 + 7 = **80 tests** across DM/Stress/Load/KPI/Instrumentation. Coverage is real.

**What is not correct:**
- The **`DownloadManagerWidget` UI** has accumulated 9 mixins (`_dm_*.py`) and ~900 lines per mixin. It mixes:
  - Pure UI rendering (`_dm_ui_setup`, `_dm_theming`)
  - UI ↔ state observer wiring (`_dm_details`, `_dm_priority`)
  - Worker-pool callbacks (`_dm_workers`)
  - Business logic (`_dm_queue`, `_dm_retry`)
- Three of the last four bugs (`[DM_REBUILD]` recursion, `[DM_PRIORITY_TRANSITION]` ghost signal, `[SP]` silent drop) all surfaced **inside this widget** because UI-side state writes ↔ observer reentrancy was never modeled.
- **Verdict: partial redesign.** Split `DownloadManagerWidget` into:
  1. **`DownloadManagerView`** — pure widget, no state mutations (only `setText`, `setVisible`, `setCurrentText` with `blockSignals`).
  2. **`DownloadManagerPresenter`** — owns observer subscriptions, translates state events → view updates, owns the inspector-panel selection.
  3. **`DownloadManagerCommands`** — user-action handlers (pause/resume/cancel/retry/priority-change). These call `intent_coordinator` directly and never touch the view.

The `DownloadManagerWidget` shell remains as a thin composer. This eliminates the entire ghost-signal class because user-driven and observer-driven combo writes go through different paths with explicit `blockSignals` discipline (the R22 fix codified this — the redesign would make it impossible to violate).

### 3.2 Qt / PySide UI Architecture

**Files:** all of `PacsClient/pacs/`, viewer `widget_viewer.py` (3609 lines).

**What is correct:**
- `qasync.QEventLoop` is wired at startup; async UI work stays on the loop.
- Heavy work goes to executor threads / subprocesses with explicit marshaling.
- Lifecycle is centralized in `LifecycleManager` (good).
- Thread-safe `_UISafeInvoker` exists in `patient_widget_viewer_controller.py`.

**What is not correct:**
- **597 `QTimer.singleShot` calls in `PacsClient/`** alone. Many are 0-ms "post to UI thread" calls; many are 50–750 ms cooldowns, throttles, and grace windows. There is no single registry, no single place to ask "what timers are pending against this widget?", no unified cancellation on widget destruction.
- The legacy VTK widget `_legacy_widget.py` is **3609 lines**. It owns: render throttle, GC suppression, drag-drop hover, lazy backend wiring, qt-bridge wiring, scroll lag probe, sync interactor, reference-line throttle, tool widget management, drop overlay. That is 9+ responsibilities in one class.
- **Verdict: partial redesign**, in this order:
  1. **Single facade `ui_dispatch.py`** for "post once to UI thread" (`post(callback)`), "schedule with cancellation" (`schedule(ms, callback) -> handle`), and "keepalive latch" (`latch(name, grace_ms)`). All 597 callsites migrate to this. Deletion safety is enforced at the facade.
  2. **`_legacy_widget.py` quarantine.** It is named "legacy" already. Carve out:
     - drag/drop hover → `_vw_dragdrop.py` (already started in mixin folder, finish the migration)
     - scroll/wheel coalescing → `_vw_scroll.py` (already exists; migrate the rest)
     - lazy backend wiring → `_vw_backend.py` (exists)
     - The remainder shrinks to ~800 lines of pure VTK/Qt glue.

### 3.3 Viewer Widget (FAST core)

**Files:** `modules/viewer/fast/*` (small, well-named) + `_vc_*.py` mixins (large).

**What is correct:**
- `Lightweight2DPipeline`, `QtSliceViewer`, `QtViewerBridge`, `disk_pixel_cache`, `decode_service` are *small, focused, individually testable* (12 + 9 + 26 tests). Even at 2231 lines, `lightweight_2d_pipeline.py` is one coherent class.
- Backend resolution (`viewer_backend_config.py`) is a clean state machine.
- Stale-frame guard, surrogate frame, prefetch admission are all behind protocol-shaped seams.

**What is not correct:**
- **`_vc_progressive.py` is 2453 lines** — bigger than `lightweight_2d_pipeline.py`. It is a **single mixin** containing:
  - Layer 1-4 completion protocol
  - Stale OS-flush retry chain (5 retries)
  - Done-guard recovery
  - Untargeted-defer rules
  - Terminal-finalizer ownership
  - Thumbnail/corner refresh post-grow
- **`_vc_load.py` is 2195 lines** with similarly mixed concerns (validation, fast/slow path, threading, async marshal, warmup, capacity).
- **`qt_viewer_bridge.py` is 1442 lines** — a "bridge" should not be the second-largest file in the FAST stack. It accreted state because every behavior the legacy VTK widget had needed a Qt-side cousin.
- **Verdict: partial redesign**, in this order:
  1. **Extract a `ProgressiveDisplayController`** as a real class (not a mixin). It owns the 4-layer state machine. `_vc_progressive.py` shrinks to ~400 lines of viewer-controller bindings.
  2. **Extract a `SeriesLoadController`** out of `_vc_load.py`. Same shape: real class, owns `LoadCoordinator` + capacity-aware admission. Mixin shrinks to bindings.
  3. **`qt_viewer_bridge.py`**: split into `QtViewerBridge` (Qt-side adapter for VTK calls; ~500 lines), `QtViewerInteractionRouter` (drag/scroll/wheel; ~400 lines), `QtViewerCameraState` (~200 lines). Tests already exist; this is mechanical.

### 3.4 Drag-and-Drop & Priority Chain

**Path (current):**
```
drop on viewer
  → ViewerController.change_series_on_viewer
  → QTimer.singleShot(0, _notify_dm_viewed_series)        [defer]
  → 500 ms per-series cooldown                             [dedup]
  → DownloadManagerWidget.set_viewed_series
  → SeriesIntentCoordinator.request_critical_series
  → DownloadStateStore.update(priority=CRITICAL)
  → Observers fire (UI/DB/Priority/Logging)
  → UIObserver QTimer.singleShot(0, refresh_table_order)
  → _refresh_table_order rebuilds DM table
```

**Assessment:** *semantically correct*. Every hop has a documented reason (cooldown for drag-burst, defer for paint cost, observer for fan-out). But the chain has **no end-to-end timestamp** in production logs, so when "downloads stop" is reported we cannot prove which hop dropped or stalled.

**Verdict: keep, but instrument.** Add one structured log tag `[PRIORITY_CHAIN] event=<hop> study=<UID> series=<N> elapsed_ms=<F>` at each of the 7 hops, all at WARNING level (per R13/R19/R22 lesson), with a parser in the KPI harness. This is **observability work**, not redesign.

### 3.5 Patient Double-Click → CRITICAL/HIGH

**Current:** `_on_patient_double_clicked_async` → `download_manager.start_priority_download_immediately(priority="Critical")`. This is correct: the *first* viewed series is CRITICAL; **other series of that study become HIGH** automatically because the per-series priority defaults differ (rule in `_dm_priority`).

**Verdict: healthy.** The only friction is that the DM table rebuild (R22) was masking the priority transition with the QComboBox ghost signal. R22 fix has resolved this; verified clean in pid=32956.

### 3.6 Database

**What is correct:**
- WAL mode, connection pool, FK indexes, explicit `commit()` rule, no `read_uncommitted` leak.
- `database/manager.py` consolidated CRUD in v2.2.8.0.
- Stage-timing logger has min_ms threshold to avoid spam.

**What is not correct:**
- DM has its own `database/database_manager.py` (`storage/database_manager.py`) which duplicates patterns.
- Some queries still bypass `database/manager.py` (e.g. inline SELECT in retry handlers).
- Schema migrations exist but are not automatically applied — startup assumes schema is current.

**Verdict: healthy. One small cleanup.** Consolidate the 3-4 inline queries into `database/manager.py`; add a startup migration runner. **This is not redesign.**

### 3.7 Disk and RAM

**Disk:**
- `DiskPixelCache` (L2 decoded pixel cache) — clean, atomic writes, 2 GB LRU, isolated. ✅
- DICOM file cache (study folder) — owned by DM. ✅
- Thumbnail cache (`storage/thumbnail_cache.py`) — owned by DM. ✅
- No conflicts. Three caches, three owners, three policies. **Healthy.**

**RAM:**
- `Lightweight2DPipeline._pixel_cache` (FAST per-pipeline)
- `Lightweight2DPipeline._frame_cache` (rendered frames, FAST per-pipeline)
- `PyDicom2DBackend` OrderedDict (32-slice pixel cache)
- `ViewerController._full_series_cache` (per-tab; sized in bytes)
- `ZetaBoostEngine` L1 RAM (Advanced only; empty in FAST mode by design — see R FAST switch rules)
- `_metadata_flat_cache`, `_hot_series_cache` (controller caches)
- DiskPixelCache LRU index (in RAM)

**That is 7+ RAM caches** with overlapping concerns: 3 pixel-shaped caches (`_pixel_cache`, `PyDicom2DBackend.cache`, `ZetaBoost`), 2 frame-shaped, 2 metadata-shaped. Each has its own eviction policy and size budget. This is **the** structural smell that survives untouched from the v2.0 era.

**Verdict: partial redesign.** Introduce `CacheManager` with named regions (`pixels`, `rendered_frames`, `metadata`, `volume`) and a single global byte budget that respects QPixmap weight, drag-active throttling (R5/R6), and study-completion (`is_viewed_series_complete`). Each existing cache becomes an adapter that registers its region. Eviction is centralized; per-region weights are configurable.

### 3.8 Thumbnails

**Files:** `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py` (~600 lines).

**What is correct:**
- Idempotent property writes (R rule already in instructions).
- `start/total/complete` projection contract.
- gRPC fetch on background thread; main-thread paint via `QMetaObject.invokeMethod`.

**What is not correct:**
- Inflight guard `_thumbnail_load_inflight` is correct but the recovery path on Qt-thread failure is implicit.
- Border-state machine (pending/ready/error) is split between `apply_border_states_new` and per-event setters.

**Verdict: healthy.** Document the projection contract once in `docs/architecture/thumbnails.md` and call it done.

### 3.9 UI/UX vs Backend Consistency

**Symptom-level reports from logs:**
- "Downloads appear stuck" — root cause was either stale cache (fixed) or invisible priority handoff exhaust (now diagnosable after R19 fix).
- "Image frozen during scroll" — fixed by R1 surrogate-staleness break.
- "Two brains overlapping" — fixed by R17 preserve_dimensions.
- "Last 5 images stuck" — fixed by stale OS-flush guard.

**Pattern:** every UI/UX bug had a **backend root cause** (cache, threading, latch). The UI itself never lied — it showed exactly what the backend told it. **There is no UI/backend impedance mismatch.** This is good news.

**Verdict: no UI redesign needed.**

---

## 4. The Real Cross-Cutting Issue: Implicit Contracts

Three of the last four production bugs share **one root cause**: an implicit cross-cutting contract that each new code site has to re-discover.

| Bug (rule) | Symptom | Implicit contract violated |
|---|---|---|
| R13 (`[SP]`) | Subprocess priority logs missing | `extra={"component": "<X>"}` requires log level >= component threshold |
| R19 (`[INTENT_PRIORITY]`) | Priority chain logs missing | same |
| R22 (`[DM_REBUILD]` / `[DM_PRIORITY_TRANSITION]`) | DM table thrashing | combo writes from observer-driven code paths must `blockSignals` |

These are not coding errors. They are **architectural under-specifications**: nowhere in the code does the type system or a lint rule say "if you call `logger.info` with `component=download`, it will be silently dropped." The contract lives **only in `copilot-instructions.md` rules R13/R19/R22**.

**Verdict:** This is the single highest-leverage fix in the entire codebase.

**Recommendation:**
1. Replace `logger.info(..., extra={"component": X})` with **typed emit helpers** per component:
   - `emit_download_event(tag, **fields)` (always WARNING)
   - `emit_viewer_event(tag, **fields)` (INFO ok)
   - `emit_ipc_event(tag, **fields)` (always WARNING)
   - `emit_priority_chain_event(...)` (WARNING)
2. The `component` extra field is set inside the helper. Direct `logger.info`/`logger.warning` callsites with `component=...` are forbidden by a unit test that scans the source.
3. The same helpers compute `slot_timing` start/stop and admit/defer accounting — the helper is the contract.

---

## 5. Module Verdict Table (Decision Matrix)

| Module | Verdict | Rough effort | Why | Pre-conditions |
|---|---|---|---|---|
| DM core (state/rules/coordinator/observers) | **Keep** | — | Sound, well-tested. | — |
| DM widget (UI) | **Partial redesign** (View/Presenter/Commands split) | ~3 days | Recurring ghost-signal class of bugs. | None. |
| Drag-drop chain | **Instrument only** | ~0.5 day | Semantically correct. | None. |
| Patient open priority | **Keep** | — | Working. | R22 fix verified. |
| FAST viewer pipeline (`Lightweight2DPipeline` etc.) | **Keep** | — | Cleanly factored. | — |
| Viewer-controller mixins (`_vc_progressive`, `_vc_load`) | **Partial redesign** (extract real classes) | ~5 days | God-mixin. | None. |
| Legacy VTK widget (`_legacy_widget.py`) | **Partial redesign** (continue mixin extraction) | ~3 days | 3609 lines, 9+ responsibilities. | None. |
| `qt_viewer_bridge.py` | **Partial redesign** (split into 3) | ~2 days | 1442 lines, was supposed to be a thin adapter. | None. |
| Thumbnails | **Document & lock** | ~0.5 day | Healthy; needs spec only. | None. |
| Database | **Small cleanup** | ~1 day | Consolidate inline CRUD; auto-migrate. | None. |
| Disk caches | **Keep** | — | Three caches, three owners. | — |
| RAM caches | **Partial redesign** (CacheManager facade) | ~3 days | 7+ overlapping caches. | None. |
| Qt threading (timers/marshal) | **Partial redesign** (`ui_dispatch.py` facade) | ~2 days | 597 `QTimer.singleShot` cross-cutting. | Should land before legacy-widget extraction so migrations target the new facade. |
| Logging contract | **New typed helpers + lint** | ~1 day | Three identical bugs in 3 months. | **Highest leverage. Do first.** |
| UI/UX | **Keep** | — | No backend impedance mismatch. | — |
| Build system | **Keep** | — | v2.4.5+ is clean. | — |

**Total partial redesign budget: ~20 working days.** No item requires a full redesign.

---

## 6. Recommended Phased Sequence

This is a **proposal**, not a commitment. User decides whether to proceed.

### Phase 0 — Stop the bleeding (1 day)
- **P0.1** Typed emit helpers + lint test. Eliminates the R13/R19/R22 class of bugs at the source.
- **P0.2** Run R19's effect on the **next live log** to confirm the priority-handoff exhaust reason. *This was the original "stop and ask for live log" point.*

### Phase 1 — Cross-cutting facades (3 days)
- **P1.1** `ui_dispatch.py` facade (post / schedule / latch / cancel-on-destroy).
- **P1.2** `CacheManager` with named regions; existing caches become adapters.
- These are **prerequisites** that make later phases safe.

### Phase 2 — DM widget split (3 days)
- **P2.1** Extract `DownloadManagerView` (no state writes).
- **P2.2** Extract `DownloadManagerPresenter` (observer subscriptions).
- **P2.3** Extract `DownloadManagerCommands` (user actions).
- The R22 ghost-signal class becomes structurally impossible.

### Phase 3 — Viewer-controller decomposition (5 days)
- **P3.1** `ProgressiveDisplayController` real class.
- **P3.2** `SeriesLoadController` real class.
- **P3.3** `_vc_*.py` mixins shrink to ~300 lines each (bindings only).

### Phase 4 — Legacy VTK widget quarantine (3 days)
- **P4.1** Migrate drag/drop + scroll out of `_legacy_widget.py`.
- **P4.2** Migrate qt-bridge wiring to `_vw_backend.py`.
- **P4.3** Quarantine remainder; rename to `_legacy_widget_core.py`.

### Phase 5 — `qt_viewer_bridge.py` split (2 days)
- **P5.1** Split into bridge / interaction-router / camera-state.

### Phase 6 — Database & docs cleanup (1 day)
- **P6.1** Consolidate inline queries into `database/manager.py`.
- **P6.2** Auto-migration runner at startup.
- **P6.3** Document thumbnail projection contract.

### Phase 7 — Resume KPI work (open-ended)
- With **all cross-cutting contracts now explicit and structurally enforced**, the remaining KPI work (priority-handoff V2 default-on, prefetch tuning, cache-region tuning) becomes single-file changes with predictable blast radius.

---

## 7. Risks & Counterarguments

**"This will introduce regressions."** Yes — but each phase is independently revertible. We have 80+ tests across DM, viewer, KPI parsers, instrumentation. We have golden-frame regression for the FAST viewer overlap (F1.3). We have synthetic baselines in `generated-files/benchmarks/`. The infrastructure for safe refactoring is already in place — we built it for the KPI work.

**"This is a lot of work for no user-visible change."** Correct, in the short term. The user-visible payoff is:
- Each future KPI fix lands faster and with fewer rules to remember.
- The R13/R19/R22 class of bug becomes impossible.
- Onboarding a new contributor stops requiring memorization of 22 numbered rules in `copilot-instructions.md`.

**"We could just patch and ship."** That is what we have been doing for 3 months. The latest bug (R19 silent drop) hid for **at least 8 production sessions** and required external prompting to find. Two more in the same class will land if we do not fix the contract.

**"What if we just do Phase 0 and 1?"** That is a viable stopping point. Phase 0 alone resolves the silent-drop class. Phase 1 alone unblocks every later phase. Together they are 4 days. They give 70% of the architectural value.

---

## 8. Decision Asked of User

Three options:

**Option A — Continue current KPI work; do Phase 0 only this week.**
Cost: 1 day. Benefit: no more silent-drop class. Resumes KPI work from R20 V2 default-on after one fresh log.

**Option B — Pause KPI work; do Phase 0 + Phase 1 (4 days), then resume.**
Cost: 4 days no user-visible feature. Benefit: cross-cutting contracts enforced; KPI work afterward is materially safer.

**Option C — Full Phase 0-7 sequence (~20 days), then resume KPI.**
Cost: ~4 weeks no user-visible feature. Benefit: codebase enters a clean state where every future bug-fix is small and local.

My recommendation: **Option B**. The user's instinct in this thread — that we are patching past the architecture — is correct, and four days of Phase 0+1 makes every subsequent patch order-of-magnitude safer. Phases 2-6 can be sequenced opportunistically alongside KPI work afterward.

---

## 9. What I Will Not Do Without Your Decision

- I will **not** start any code change in this branch.
- I will **not** delete or rename existing files.
- I will **not** add a `CacheManager`, `ui_dispatch.py`, or typed emit helpers without your "go".

The next log you send will give us R19's diagnostic data **regardless** of which option you pick. So requesting the live log is still the right next step under all three options.

---

## 10. Implementation Status (live tracker)

**Phase 0 — Stop the silent-drop bug class. STATUS: COMPLETE (2026-04-30).**

- PacsClient/utils/structured_logging.py — typed emit helpers (`emit_download_event` defaults WARNING; `emit_ipc_event` / `emit_viewer_event` / `emit_zetaboost_event` / `emit_db_event` / `emit_ui_event` default INFO). Helper sets `extra['component']` internally and promotes the level to the component minimum so the queued listener never silently drops.
- `tests/utils/test_structured_logging.py` — 17 unit tests, all green.
- `tests/utils/test_structured_logging_lint.py` — 6 source-scan tests, all green; scans `PacsClient/` + `modules/` + `database/` for `logger.info(..., extra={'component': 'download'})` and similar silent-drop patterns. Allows `# noqa: structured-logging` on the same source line. DEBUG is always permitted (developers explicitly want DEBUG invisible). Excludes `builder/plugin package/`, `tests/`, and the structured_logging module's own docstring.
- Initial scan flagged **20 production violations** (16 in `modules/download_manager/network/socket_client.py`, 2 in `modules/download_manager/ui/widget/_dm_workers.py`, 1 in `modules/download_manager/workers/download_process_worker.py`, 1 in `PacsClient/utils/diagnostic_logging.py` — same root cause that hid R13/R19/R22).
- Fix policy: KPI/summary/retry events bumped INFO → WARNING (visible); routine chatter (init, recv byte counts, batch start/got) demoted INFO → DEBUG (silent on purpose, intent now explicit). All 4 download_manager files mirrored to `builder/plugin package/packages/download_manager/payload/python/...`. `diagnostic_logging.py` is PacsClient-tier and has no plugin-package mirror.
- Regression: DM 27 scenarios / 129 assertions all PASS; 7 pre-existing failures in `test_fast_viewer_pipeline.py` and `test_b32_adaptive_prefetch.py` confirmed unrelated (also fail on git-stash baseline).
- Budget: ~120 lines new helper + ~280 lines test = small, contained.
- Outcome: the silent-drop bug class is now caught by `pytest tests/utils/` in 36 s and cannot regress without an explicit `# noqa` opt-out.

**Phase 1 — Extract two facades. STATUS: NOT STARTED.**
- `PacsClient/utils/ui_dispatch.py` (post / schedule / latch / cancel-on-destroy)
- `modules/cache_manager.py` (named regions: pixels, rendered_frames, metadata, volume; single byte budget)

**Phase 2-7 — see Section 6.** Will be revisited after Phase 1 lands and the next live log is captured.


---

## 10. Implementation Status (live tracker)

**Phase 0 â€” Stop the silent-drop bug class. STATUS: COMPLETE (2026-04-30).**

- `PacsClient/utils/structured_logging.py` â€” typed emit helpers (`emit_download_event` defaults WARNING; `emit_ipc_event` / `emit_viewer_event` / `emit_zetaboost_event` / `emit_db_event` / `emit_ui_event` default INFO). Helper sets `extra['component']` internally and promotes the level to the component minimum so the queued listener never silently drops.
- `tests/utils/test_structured_logging.py` â€” 17 unit tests, all green.
- `tests/utils/test_structured_logging_lint.py` â€” 6 source-scan tests, all green; scans `PacsClient/` + `modules/` + `database/` for `logger.info(..., extra={'component': 'download'})` and similar silent-drop patterns. Allows `# noqa: structured-logging` on the same source line. DEBUG is always permitted (developers explicitly want DEBUG invisible). Excludes `builder/plugin package/`, `tests/`, and the structured_logging module's own docstring.
- Initial scan flagged **20 production violations** (16 in `modules/download_manager/network/socket_client.py`, 2 in `modules/download_manager/ui/widget/_dm_workers.py`, 1 in `modules/download_manager/workers/download_process_worker.py`, 1 in `PacsClient/utils/diagnostic_logging.py` â€” same root cause that hid R13/R19/R22).
- Fix policy: KPI/summary/retry events bumped INFO â†’ WARNING (visible); routine chatter (init, recv byte counts, batch start/got) demoted INFO â†’ DEBUG (silent on purpose, intent now explicit). All 4 download_manager files mirrored to `builder/plugin package/packages/download_manager/payload/python/...`. `diagnostic_logging.py` is PacsClient-tier and has no plugin-package mirror.
- Regression: DM 27 scenarios / 129 assertions all PASS; 7 pre-existing failures in `test_fast_viewer_pipeline.py` and `test_b32_adaptive_prefetch.py` confirmed unrelated (also fail on git-stash baseline).
- Outcome: the silent-drop bug class is now caught by `pytest tests/utils/` in 36 s and cannot regress without an explicit `# noqa` opt-out.

**Phase 1 â€” Extract two facades. STATUS: NOT STARTED.**
- `PacsClient/utils/ui_dispatch.py` (post / schedule / latch / cancel-on-destroy)
- `modules/cache_manager.py` (named regions: pixels, rendered_frames, metadata, volume; single byte budget)

**Phase 2-7 â€” see Section 6.** Will be revisited after Phase 1 lands and the next live log is captured.

