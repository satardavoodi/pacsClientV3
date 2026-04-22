# Block Priority & Connection Review vs ClearCanvas

**Date:** 2026-04-19
**Scope:** Initial architecture review of AIPacs Block A/B/C ordering and connection topology, compared with the available ClearCanvas source snapshot.

## Goal

Desired runtime order for the FAST path:

1. **Block A** — thumbnails appear first
2. **Block B** — image appears next
3. **Block C** — scrolling / caching / prefetch / interaction optimization comes after first visible image

This review checks:
- whether the current structure follows that ordering,
- whether block connections are clean and correct,
- whether there are likely bug-prone couplings,
- and what ClearCanvas suggests about priority ownership.

## Evidence Base

### AIPacs files reviewed
- `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/thumbnail_panel.py`
- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py`
- Architecture note: `docs/architecture/home-ui-services.md`
- Repo memory: FAST pipeline flow and PacsClient structure

### ClearCanvas files reviewed
- `ClearCanvas-master_extracted/ClearCanvas-master/Desktop/Desktop.sln`
- `.../Desktop/Application.cs`
- `.../Desktop/Explorer/ExplorerTool.cs`
- `.../Common/PluginManager.cs`
- `.../Common/Caching/*`
- `.../Desktop/View/WinForms/*`

## Important limitation on the ClearCanvas comparison

The provided ClearCanvas archive is **not a full RIS/PACS workstation tree**. It contains the **desktop framework / explorer / plugin / caching shell**, but no obvious imaging-specific projects such as a full DICOM image-viewer module, thumbnail browser for studies/series, or PACS/network client implementation.

So the comparison is valid at the **priority architecture level** (shell, plugin loading, workspace/explorer startup, deferred loading, background assembly loading), but **not** as a one-to-one comparison of full thumbnail/image/scroll rendering code.

---

## AIPacs block review

## Block A — thumbnails first

### Intended role
Block A should establish study/series visibility quickly and cheaply:
- create the thumbnail panel,
- render or replay thumbnail widgets,
- show series identity and readiness,
- avoid blocking on full image load.

### What currently exists

#### Good structure
- `ThumbnailPanel.display_thumbnails_immediately()` and `display_thumbnails_progressively()` explicitly treat thumbnails as an early visual stage.
- `ThumbnailPanel.display_next_thumbnail_patient()` batches thumbnails (`batch_size = 3`) for quick progressive visibility.
- `ThumbnailManager.create_thumbnail_widget()` supports placeholder/partial state before full readiness.
- `ThumbnailManager.start_series_download()` / `complete_series_download()` and `HomeDownloadService.connect_dm_to_widget()` create a dedicated progress projection path into thumbnails.
- Recent fixes ensure a completed series can replay ready state even if the widget is created late.

#### Structural concerns
- `thumbnail_panel.py` still mixes UI, cache lookup, direct DB metadata lookup, disk file checks, progressive timers, and debug-print-heavy orchestration in one class.
- Block A has **multiple sources of truth** for series state:
  - `ThumbnailPanel.lst_thumbnails_data`
  - `ThumbnailManager.series_widgets`
  - `ThumbnailManager.ready_series`
  - `_series_projection_state`
  - widget-level and parent-level UID→number maps
  - DM task state via `HomeDownloadService`
- This makes Block A functional but **architecturally noisy**.

### Ordering assessment
**Status: mostly correct, but not isolated enough.**

Block A usually appears first, which matches the desired UX. But the block is not cleanly isolated from Block B and DM state, so late or duplicated completion pulses can still disturb it.

### KPI assessment
- Good for perceived startup when thumbnails come from cache or server bytes.
- Risk factors:
  - main-thread DB queries in `thumbnail_panel.py`
  - disk existence checks and pixmap fallback reads on the UI thread
  - timer-based batching without a stricter ownership boundary
- Practical KPI target for Block A should be:
  - **first visible thumbnail**: sub-150ms after series data available
  - **all initial thumbnails for a study**: progressive, non-blocking, with no UI-thread storms

### Verdict
**Block A should remain first priority.**
But it needs a stronger service boundary so it is a projection layer, not a mini-orchestrator.

---

## Block B — first image visible

### Intended role
Block B should:
- switch to a selected series,
- bind the correct backend,
- show the first image quickly,
- avoid waiting on full cache warmup / prefetch / secondary work.

### What currently exists

#### Good structure
- `_vc_switch.py::change_series_on_viewer()` has a clear split between:
  - fast cache-hit switch,
  - async load-and-switch on cache miss,
  - stale-cache show-then-refresh,
  - deferred DM notify.
- FAST mode already has a metadata-first path and avoids the ITK full-volume cost.
- Spinner + stale guard are designed to preserve responsiveness.

#### Structural concerns
- `change_series_on_viewer()` still owns too much:
  - interaction signaling,
  - stale detection,
  - backend rebuild policy,
  - cache lookup,
  - request token lifecycle,
  - spinner policy,
  - load scheduling,
  - DM notification,
  - first-use boost activation,
  - paired-series logic,
  - post-switch UI refresh.
- That means Block B is the **heaviest control-plane node** in the pipeline.
- It also directly touches several neighboring concerns that should ideally stay below it:
  - cache warmup / booster activation,
  - progressive follow-up,
  - paired-series MG logic,
  - sync/reference-line updates.

### Ordering assessment
**Status: correct in intent, but Block B still sometimes overreaches into Block C work.**

The first image is generally prioritized correctly. However, Block B still carries responsibilities that belong to “after first visible image” work.

### KPI assessment
Current design is aligned with the FAST goal of low first-image latency, but Block B must protect this invariant:
- **first image visible** should not wait on:
  - prefetch,
  - cache warming,
  - secondary metadata refresh,
  - nonessential paired-series work,
  - sidebar decoration work.

This is where regressions can hide: the image still appears, but extra responsibilities inside Block B raise tail latency and destabilize layout timing.

### Verdict
**Block B should stay second, but it needs a stricter “first frame authority” boundary.**

---

## Block C — scrolling, cache, prefetch, and interaction optimization

### Intended role
Block C should start only after Block B has produced a stable first image.
Its job is throughput and smoothness, not first visibility.

### What currently exists

#### Good structure
- FAST viewer architecture already distinguishes first display from continuous interaction.
- Scrolling/caching/prefetch live largely under the FAST viewer stack and related orchestration.
- Existing repo rules strongly protect fast interaction from heavy work.

#### Structural concerns
- Some Block C concerns still influence Block B too early:
  - booster activation in `_perform_series_switch_optimized()`
  - warmup triggers immediately after successful switch
  - metadata/count sync and grow logic can interact with viewer state very early
- The remaining “backward then return” symptom likely lives here: a drag/settle/cache/surrogate interaction bug family, not a thumbnail-first issue.

### Ordering assessment
**Status: mostly third, but some prefetch/warmup responsibilities bleed into Block B.**

### KPI assessment
Block C should optimize:
- p95/p99 scroll frame time,
- perceived stability during drag,
- surrogate-frame correctness,
- cache fill efficiency.

It should **not** be allowed to degrade:
- first thumbnail time,
- first image time,
- layout stabilization after switch.

### Verdict
**Block C is conceptually in the right place, but some of its setup work still starts too eagerly.**

---

## Connection review by dependency type

## 1) Qt / UI thread connection

### AIPacs
- Strong signal/slot usage between DM and widgets.
- `HomeDownloadService` uses `QTimer` coalescing for progress fan-out.
- `change_series_on_viewer()` and thumbnail code still perform some UI-thread work that is broader than pure presentation.

### Assessment
- **Correct directionally**
- **Risk:** Block A and B have too many UI-thread responsibilities mixed with orchestration and fallback logic.

### Engineering recommendation
- Keep Qt as the **projection boundary**, not the source of truth.
- One block = one UI owner:
  - A owns thumbnail projection
  - B owns first-image projection
  - C owns post-display interaction cadence

## 2) Database connection

### AIPacs
- Home services follow the proper service-layer pattern.
- But `thumbnail_panel.py` still performs metadata lookup directly from UI code for cached thumbnails.

### Assessment
- **Not clean enough** for Block A.
- DB metadata access for thumbnails should come from a thin service/cache provider, not the panel widget.

### KPI concern
DB queries during thumbnail construction can lengthen thumbnail flush batches and create uneven first-paint timing.

## 3) Disk / filesystem connection

### AIPacs
- Thumbnail fallback still reads pixmaps from disk on the UI thread when memory cache misses.
- Series stale checks intentionally touch disk, but with TTL protections.
- FAST image loading relies on disk presence correctly for progressive grow.

### Assessment
- Mixed.
- Disk use in Block B/C is generally purposeful and guarded.
- Disk use in Block A is more fragile because it is still partly synchronous in UI code.

## 4) Reading / loading pipeline connection

### AIPacs
- Block B is tied directly to `load_single_series_by_number()` and backend binding.
- This is correct, but the switch layer still also triggers follow-up responsibilities.

### Assessment
- Core loading path is correct.
- Ownership boundary is too wide inside `_vc_switch.py`.

## 5) Server / network connection

### AIPacs
- `HomeDownloadService` is the main bridge from Download Manager progress to thumbnails/viewer.
- This is the right architectural center for server-driven progress projection.

### Assessment
- Better than the thumbnail panel’s own DB/disk coupling.
- Recent normalization logic is a good direction: a single terminal authority for completion.
- Remaining risk is fan-out complexity and duplicate progress/completion semantics.

## 6) Module / subsystem connection

### AIPacs
- Strong modular decomposition exists overall:
  - Home UI services
  - Download Manager
  - FAST viewer stack
  - thumbnail manager
  - storage thumbnail store
- But the live block boundaries are still not perfectly aligned with those module boundaries.

### Assessment
- Macro architecture: good
- Runtime coupling: still too entangled at the A/B seam and B/C seam

---

## Comparison with ClearCanvas

## What ClearCanvas shows clearly

### 1) Shell-first architecture
- `Desktop/Application.cs` establishes the application, root window, UI toolkit, and session first.
- `ExplorerTool.cs` launches the Explorer as a shelf/workspace from a startup action.
- This means **navigation/browsing shell is a first-class stage**, separate from later specialist functionality.

### 2) Plugin-oriented responsibility boundaries
- `Common/PluginManager.cs` loads plugin metadata first and defers remaining assembly loading in the background.
- This is a strong example of **early availability, deferred depth**.
- The platform prefers a responsive shell + background capability resolution.

### 3) UI toolkit abstraction
- ClearCanvas abstracts the GUI layer via `IGuiToolkit` and associated views.
- It is **not Qt** in this snapshot; it is clearly a desktop/WinForms-oriented abstraction.
- That architectural separation reduces framework leakage into domain components.

### 4) Background loading as second-order work
- The plugin manager explicitly enables background assembly loading only after initialization is complete.
- That matches your desired principle very well:
  - get the shell visible first,
  - defer deeper loading second.

## What ClearCanvas suggests for AIPacs priority design

Even though the imaging-specific modules are not present in this archive, its architecture strongly reinforces these principles:

1. **A visible shell/browsing layer should come first**
   - In AIPacs terms: Block A should be the earliest user-trust surface.
2. **Background depth should be deferred**
   - In AIPacs terms: Block C should never compete with first thumbnail or first image.
3. **Plugin/module ownership should be explicit**
   - In AIPacs terms: thumbnail panel should not own DB fallback logic; switch controller should not own too much post-display optimization.
4. **Startup and interaction should not fully resolve all capabilities upfront**
   - In AIPacs terms: prefetch/warmup/caching should be admitted only after the first visual milestone is complete.

---

## Are the causes shared across A/B/C?

## Answer
**Partly shared, partly separate.**

### Shared architectural issue family
There is a shared architectural issue around **priority leakage between blocks**:
- Block A still carries too much orchestration and metadata fallback logic.
- Block B still carries too much post-switch and optimization ownership.
- Some Block C work starts too early and can affect Block B timing.

### Probably separate issue family
The exact “scroll jumps backward then returns” symptom still looks like a **Block C interaction/cache/settle problem**, not the same root cause as thumbnail lateness.

So the overall answer is:
- **A and B are structurally coupled more than they should be**
- **B and C are also coupled more than they should be**
- **but the remaining drag-jump symptom is likely a Block C-specific defect**

---

## Initial judgment on correctness

## Correct / healthy
- Service layer on Home UI
- DM→viewer signal wiring centralized in `HomeDownloadService`
- FAST metadata-first image load philosophy
- Progressive/stale guards and deferred UI updates
- Explicit attempt to keep first image fast

## Needs structural cleanup
- `thumbnail_panel.py` still does too much local orchestration
- `thumbnail_manager.py` still holds both visual state and some lifecycle policy
- `_vc_switch.py` is overloaded as a control-plane hub
- Block boundaries are present conceptually, but not yet strict in runtime ownership

## KPI risk areas
- UI-thread DB/disk work in thumbnail path
- duplicated/late progress/completion fan-out at the A/B seam
- first-image path carrying post-switch side effects
- early Block C work interfering with Block B stabilization

---

## Recommended priority model going forward

## Target runtime contract

### Block A contract
**Goal:** series browser confidence
- show thumbnail widgets first
- show title / modality / count / ready/downloading state
- no full-image dependency
- no direct DB/disk fallback logic in panel class

### Block B contract
**Goal:** first diagnostic image visible
- switch series
- bind backend
- display first frame
- set stable layout / slider state
- no eager warmup/prefetch pressure before first frame is visible

### Block C contract
**Goal:** smooth ongoing interaction
- scroll
- surrogate/exact frame selection
- prefetch
- cache warmup
- post-completion optimization
- never block or delay Block A/B milestones

---

## Recommended next fixes at architecture level

1. **Extract Block A data supply from `thumbnail_panel.py`**
   - move DB/cache fallback metadata lookup behind a thumbnail data service or provider
2. **Narrow Block B authority in `_vc_switch.py`**

---

## 2026-04-20 hardening update

### What was hardened

- `modules/viewer/fast/lightweight_2d_pipeline.py::shutdown()` now shuts down the actual FAST background pools (`_decode_executor`, `_frame_executor`) instead of referencing a non-existent `_executor` field.
- The matching builder payload copy under `builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/lightweight_2d_pipeline.py` was updated in the same way so packaged builds do not drift behind the workspace runtime behavior.
- `_vc_switch.py::_perform_series_switch_optimized()` now keeps the actual series switch, spinner hide, and Qt refit immediate, while deferring lower-priority follow-up work (corner refresh, reference-line recompute, protected-series refresh) to the next Qt tick.

### Why this is a Block B improvement

This is deliberately a **beside-the-current-function** optimization, not a redesign:

- no change to the first-image-visible path,
- no change to the current FAST badge / loader-GIF / viewport-fit behavior,
- no change to the manual-switch refit path that fixed the quarter-size layout zoom regression,
- no change to the terminal/background skip policy for untargeted FAST series.

Instead, it removes a latent cleanup fault in the FAST render core so shutdown/teardown does not fail on a stale attribute lookup.
It also trims a small amount of non-essential work off the immediate Block B switch path without changing current presentation semantics.

### Regression guardrails preserved

The current hardening pass must remain compatible with the following already-fixed user-visible behaviors:

1. **Badge behavior** remains presentation-only; cleanup hardening must not reintroduce state churn that changes backend badge timing.
2. **Loader/GIF behavior** remains unchanged; successful manual switch still owns spinner hide/awaiting cleanup.
3. **Layout zoom / quarter-size regression** remains protected by the Qt post-switch refit path in `_vc_switch.py`; cleanup work must stay separate from viewport presentation repair.
4. **Post-switch first-frame priority** is now explicit: spinner hide and Qt refit remain inline, while safe follow-up UI work runs one Qt tick later so performance improves beside the current behavior instead of replacing it.

### Architectural meaning

This update reinforces the current conclusion of this review:

- the FAST decode/render core is qualified,
- the next improvements should be narrow hardening and ownership cleanup,
- and performance work should stay adjacent to the current behavior instead of broad rewrites that risk regressions in Block A/B presentation.
   - first-image path should stop after a stable visible frame + essential slider/layout state
3. **Move all nonessential warmup behind Block B completion**
   - treat warmup/prefetch as admitted Block C work only
4. **Keep `HomeDownloadService` as the single terminal-progress authority**
   - continue reducing duplicate completion semantics across thumbnails + progressive display
5. **Add explicit milestone metrics**
   - A1: first thumbnail visible
   - A2: all initial thumbnail widgets projected
   - B1: first image visible
   - B2: viewer stabilized (slider/layout ready)
   - C1: first smooth scroll frame
   - C2: warmup admitted

---

## Final conclusion

The current AIPacs architecture is **close to the desired A → B → C priority model**, but it is not strict enough yet:

- **Block A** is correctly first in UX intent, but too entangled with fallback logic.
- **Block B** is correctly second in UX intent, but overloaded with adjacent control-plane responsibilities.
- **Block C** is mostly third, but some of its preparation begins too early.

The available ClearCanvas snapshot supports a strong architectural lesson:

> **show the shell first, defer deeper loading second, and keep module ownership explicit.**

That principle matches your requested ordering very well and should be the basis for the next round of block-by-block fixes.

---

## 2026-04-20 continuation update

The current continuation summary now lives in:

- `docs/plans/BLOCK_A_B_KPI_CLEARCANVAS_HANDOFF_2026-04-20.md`

### What this review predicted correctly

Two of the next real fixes aligned directly with this review:

1. **Block B first-visible authority was tightened further**
  - non-essential post-switch work now runs via `_schedule_post_switch_followups(...)`
  - first-frame display, spinner hide, and Qt presentation repair remain immediate

2. **Runtime-log-driven layout stabilization mattered more than deeper renderer changes**
  - a fresh-start Qt refit was added in `_vw_series.py`
  - this fixed the “last inserted series has wrong zoom / under-fit layout” symptom without broad redesign

### KPI interpretation update

Recent manual log review showed:

- first image visible in the low tens of milliseconds,
- cache-hot drag frames in the sub-millisecond to low-millisecond class,
- `decode_ms=0.0` on sampled drag frames,
- but CPU still elevated during overlap.

That strengthens the main thesis of this review:

> the remaining optimization center is control-plane/background pressure, not another first-pass decode optimization.

### ClearCanvas update

The ClearCanvas work remains valid as an architecture and KPI reference, but the real runtime benchmark is still only **prepared/partially simulated**, not fully executed on this machine. The AI-PACS `run_001` / `run_002` captures remain the practical comparison baseline until ClearCanvas becomes buildable.
