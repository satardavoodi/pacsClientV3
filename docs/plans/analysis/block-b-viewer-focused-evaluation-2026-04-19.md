# Block B Viewer Focused Evaluation

**Date:** 2026-04-19  
**Scope:** Focused evaluation of **Block B (Viewer)** for the FAST path, with a ClearCanvas comparison centered on **prioritization, optimization, rendering stability, and duplicate work**.  
**Intent:** Evaluate first. Optimize safely second. No broad redesign proposed here.

---

## What Block B is responsible for

For this review, **Block B** is the viewer path between upstream image availability and user-visible image presentation:

1. receive image/metadata input,
2. decode DICOM pixel data,
3. apply filters and window/level,
4. render the frame,
5. display a stable image in the viewer/layout.

This review is intentionally scoped to the **FAST viewer path** first, because that is the active performance-sensitive path and the user requested optimization rather than Advanced-viewer redesign.

---

## Evidence reviewed

### Primary AIPacs files
- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- `modules/viewer/fast/pydicom_2d_backend.py`
- `modules/viewer/fast/ui_throttle.py`
- `modules/viewer/fast/system_load_controller.py`
- `PacsClient/pacs/patient_tab/utils/image_io.py`
- `PacsClient/pacs/patient_tab/utils/opencv_filter_pipeline.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_cache.py`

### Existing comparison / architecture references
- `docs/analysis/CLEARCANVAS_WORKSTATION_COMPARISON.md`
- `docs/analysis/FAST_TASK_CONCURRENCY_AND_CLEARCANVAS_COMPARISON.md`
- `/memories/repo/fast-viewer-complete-pipeline-flow.md`
- `/memories/repo/viewer-widget-architecture-comprehensive.md`

---

## Executive judgment

**Block B is fundamentally sound, but not yet structurally optimal.**

The good news:
- the **FAST path already avoids the old ITK/VTK waste** for `pydicom_qt`,
- decode/filter/render/display are connected correctly,
- filter consistency is intentionally preserved outside fast interaction,
- rendering stability is reasonably protected,
- and the repo already contains a real admission-control shell (`ui_throttle` + `SystemLoadController`).

The main optimization problem is **not that Block B is incorrect**.  
It is that **Block B still carries too much coordination gravity** around the hot path:
- split ownership of viewer state,
- repeated metadata/header work during progressive growth,
- multiple cache layers with overlapping policy,
- and extra control-plane work around growth/prefetch/render follow-up.

So the current structure is:
- **clinically workable**,
- **performance-aware**,
- but **still heavier than it should be** when download overlap, progressive growth, and user interaction happen together.

---

## Current Block B fast-path structure

### 1) Receive image data / metadata

The FAST load path is structurally correct:
- `image_io.load_single_series_by_number()` has a **`BACKEND_PYDICOM_QT` early exit**.
- For FAST mode, it builds metadata and yields a **minimal VTK stub** instead of running `apply_filters()` + `convert_itk2vtk()`.
- This is exactly the right architectural decision for FAST.

### 2) Decode

The runtime decode authority is effectively:
- `Lightweight2DPipeline._decode_slice()` for foreground decode,
- optional decode-service assistance for **background prefetch only**,
- disk pixel cache before pydicom decode,
- memory pixel cache after decode.

This is a real optimization stack, not accidental layering.

### 3) Filter + W/L

`Lightweight2DPipeline.get_rendered_frame()` owns:
- W/L resolution,
- optional OpenCV filter application,
- drag-specific filter suppression,
- rendered frame caching,
- surrogate/cached-frame selection during drag.

This is the correct place conceptually, but some state that influences it is still duplicated outside the pipeline.

### 4) Render + display

`QtViewerBridge.set_slice()` is the display orchestrator:
- sets interaction mode,
- updates slice index,
- gets a rendered frame,
- pushes image into `QtSliceViewer`,
- updates W/L text and annotations.

This is a clean display seam compared with the older VTK-heavy path.

---

## What is already good and should be preserved

### FAST-mode early load staging is correct

The `pydicom_qt` metadata-only early exit in `image_io.py` is a major architectural win.
It prevents expensive pre-render work from running before the FAST viewer even needs pixels.

### Filter behavior is already sensibly prioritized

The current rule is strong:
- **precision wheel** keeps exact filtered appearance,
- **fast drag** can skip filter temporarily,
- final exact render is restored on interaction settle.

That is a reasonable tradeoff between speed and consistency.

### Qt rendering path is stable enough for optimization

The bridge already gives Block B a clear visible-image boundary:
- `pipeline.get_rendered_frame()` produces image data,
- `qt_viewer.set_image()` displays it.

That separation is usable and should not be replaced casually.

### Tool and sync connections are technically correct

The tool layer is wired directly to the pipeline for:
- pixel access,
- pixel spacing,
- patient-space conversion.

This is good engineering because it prevents tool code from re-decoding or inventing its own geometry path.

### Admission control exists

`ui_throttle.py` and `system_load_controller.py` already form a shared policy front door.
That means the codebase is **not missing the right architecture idea** — it mainly still needs tighter execution under that shell.

---

## Focused optimization findings inside Block B

## 1) Header / metadata work is still duplicated during progressive growth

### Evidence
- `Lightweight2DPipeline.refresh_file_list()` scans the series folder and reads DICOM headers for new files.
- `PyDicom2DBackend.refresh_file_list()` performs essentially the same kind of header scan.
- `_vc_cache._refresh_stored_metadata_instances()` separately scans the same series directory and appends metadata stubs.
- `_schedule_background_header_fill()` then backfills geometry for those new stubs.

### Why this matters
This is one of the clearest remaining inefficiencies:
- the same new files can trigger multiple directory walks,
- multiple `dcmread(stop_before_pixels=True)` calls,
- multiple metadata rebuild/merge actions,
- and repeated sync into viewer metadata.

### Judgment
**This is the strongest candidate for safe optimization** without redesign.

---

## 2) Block B still has split ownership of window/level state

### Evidence
- `QtViewerBridge` stores `_window` / `_level`.
- `Lightweight2DPipeline` stores `_window` / `_level`.
- `QtSliceViewer` also receives W/L values for UI display.
- `set_window_level()` and `_on_qt_wl_changed()` update both bridge and pipeline paths.

### Why this matters
This is not necessarily a visible bug today, but it is structural drag:
- multiple writes per W/L change,
- extra invalidation logic,
- extra reasoning burden when a rapid scroll/WL/filter interaction goes wrong.

### Judgment
Block B would be cleaner if the **pipeline were the single W/L authority**, with the bridge acting as presenter only.

---

## 3) The hot render path still does extra cache-neighborhood work during drag

### Evidence
In `Lightweight2DPipeline.get_rendered_frame()` drag mode may do:
1. exact filtered frame cache search,
2. exact current cache check,
3. nearest cached frame scan,
4. nearest cached pixel scan,
5. uncached frame render on surrogate,
6. then prefetch scheduling.

### Why this matters
The logic is clever and clinically useful, but still a little over-layered.
It reduces foreground decode, but the decision tree itself is more complex than ideal.

### Judgment
This is not a redesign issue. It is a **micro-optimization and simplification opportunity**.

---

## 4) Prefetch scheduling is correct in intent but still slightly over-invoked

### Evidence
- `QtViewerBridge.set_slice()` calls `pipeline.set_slice_index(idx)`, which triggers `_prefetch_around(...)`.
- `pipeline.get_rendered_frame(...)` also ends by calling `_prefetch_around(idx)`.
- Dedup via `_last_prefetch_center` prevents full duplication, but the second call still occurs.

### Why this matters
This is not a large bug, but it is evidence that Block B still does some avoidable coordination work even when behavior remains correct.

### Judgment
Low-risk cleanup candidate.

---

## 5) Progressive grow still pushes Block B work into neighboring responsibilities

### Evidence
`_grow_progressive_fast()` does more than just update visible slice availability. It also:
- grows backend or bridge file lists,
- updates VTK slice range / slider range,
- updates booster paths,
- refreshes stored metadata,
- syncs live viewer metadata,
- updates thumbnails,
- may finalize lifecycle state.

### Why this matters
This function is functioning as a **mixed control-plane node**, not just a viewer grow step.
That increases the chance that optimization work in Block B gets tangled with Block C or sidebar behavior.

### Judgment
The logic is justified for correctness, but **too much post-display policy is coupled to the same growth step**.

---

## 6) Memory/caching is powerful, but ownership is still spread out

### Evidence
Block B relies on multiple cache layers:
- pixel cache,
- rendered frame cache,
- disk pixel cache,
- plus progressive metadata state and prefetch pending state.

### Why this matters
These caches are individually reasonable, but they are not governed by one simple ownership model.
ClearCanvas is calmer here because it uses clearer single-resource ownership.

### Judgment
This is not evidence that the caches are wrong.  
It is evidence that **cache policy and state authority are still somewhat diffuse**.

---

## 7) `image_io.py` still contains noisy non-structured terminal output in the load path

### Evidence
`image_io.load_single_series_by_number()` still contains direct `print(...)` calls around:
- path resolution,
- FAST metadata-only path messages,
- DB-path diagnostics,
- warning/fallback messages.

### Why this matters
This is not the biggest CPU problem, but it is still Block B-adjacent:
- it adds synchronous terminal/log output in an important load path,
- it makes viewer-load observability noisier,
- and it creates more work in the same stage that is supposed to stay lean.

### Judgment
This is a **small but clean optimization/hygiene candidate**.

---

## Connection review for Block B

## Qt / UI rendering / layout

### Status
**Mostly correct.**

### Good
- `QtViewerBridge` is the central visible-image presenter.
- Annotation updates are skipped during fast interaction.
- Interaction settle consolidates the final quality render.
- The layout/display boundary is clearer than the legacy VTK path.

### Risk
- bridge + pipeline still share too much state authority,
- progressive grow still reaches into slider/layout-visible behavior from outside the immediate display seam.

### Verdict
Qt connection is correct, but Block B would benefit from **stricter presentation-only responsibility at the bridge boundary**.

---

## Upstream data source connection

### Status
**Correct and significantly improved.**

### Good
- `image_io.load_single_series_by_number()` correctly stages FAST vs VTK behavior.
- metadata-first loading for FAST is exactly what Block B should do.
- upstream pipeline does not force full ITK work in FAST mode anymore.

### Risk
- metadata completeness repair still spans DB metadata, disk reconciliation, background header fill, and live viewer sync.

### Verdict
The upstream connection is conceptually right. The remaining issue is **metadata repair duplication**, not the load contract itself.

---

## Disk connection

### Status
**Correct, but duplicated in the growth path.**

### Good
- pixel decode only reads full data when needed,
- disk pixel cache is a strong reopen optimization,
- header-only reads are used where appropriate.

### Risk
- progressive growth causes repeated directory scans and header reads in multiple layers,
- some disk checks still happen in adjacent orchestration layers rather than one shared helper.

### Verdict
Disk access strategy is good; **disk metadata scanning strategy is not yet minimal**.

---

## Memory buffer connection

### Status
**Powerful but layered.**

### Good
- pixel cache + frame cache + disk cache form a sensible latency ladder,
- QImage lifetime protection via numpy buffer retention is correct,
- foreground vs background decode separation is deliberate.

### Risk
- too many related state holders raise coherence complexity,
- growth path and cache path are still partly independent.

### Verdict
Memory strategy is effective, but **simplification of ownership would reduce bug surface**.

---

## Other module connections: sync, tools, filters

### Status
**Functionally correct, structurally a bit fragile.**

### Good
- tools use pipeline pixel access directly,
- geometry transforms are pipeline-backed,
- filters run from one main render path,
- sync/reference-line machinery has explicit geometry repair rules.

### Risk
- sync correctness still depends on metadata backfill and viewer metadata syncing after growth,
- this means Block B correctness is partly dependent on side-channel metadata repair.

### Verdict
Connections are correct, but **the dependency on post-growth metadata synchronization is still a hidden complexity hotspot**.

---

## Comparison with ClearCanvas

## What ClearCanvas appears to prioritize better

### 1) Single ownership per visible-image object

ClearCanvas is structurally calmer:
- loader ownership is explicit,
- frame/presentation ownership is explicit,
- viewer composition is easier to reason about.

AI-PACS Block B currently spreads responsibility across:
- controller mixins,
- load path,
- bridge,
- pipeline,
- progressive grow helpers,
- throttling shell.

**ClearCanvas advantage:** fewer authority points per visible frame.

---

### 2) Cleaner separation between initial availability and background depth

ClearCanvas consistently models:
- study loading,
- frame/presentation ownership,
- prefetch,
- synchronization
as separate owned concerns.

AI-PACS often still lets post-display work remain close to the same call paths that create the first visible image.

**ClearCanvas advantage:** calmer prioritization tree.

---

### 3) Lower control-plane noise around rendering

From the comparison docs, ClearCanvas wins more on **ownership clarity** than on raw decode cleverness.
It avoids some of the control churn that AI-PACS accepts because AI-PACS is solving:
- active downloads,
- progressive growth,
- mixed-load viewer interaction.

So the lesson is **not** “copy ClearCanvas behavior.”
The lesson is:
- keep Block B narrow,
- keep Block C from impersonating Block B,
- keep one authority for viewer-visible image state.

---

## What AI-PACS already does better than ClearCanvas in this area

To stay fair: AI-PACS is solving a harder runtime problem.

### AI-PACS strengths
- progressive display during live download,
- disk pixel cache,
- interaction-aware surrogate/cached frame behavior,
- filter skip during drag with exact settle rerender,
- explicit mixed-load throttling.

So the conclusion is **not** that Block B is behind ClearCanvas overall.
It is that **Block B is doing advanced things, but still paying a complexity tax for them**.

---

## Focused KPI interpretation

For Block B specifically, the most important KPI truth is:

### The dominant problem is no longer pure decode alone
The reviewed docs and live analysis already show that overlap pain also comes from:
- UI lag,
- control-plane work,
- progressive/grow fan-out,
- cache/prefetch follow-up,
- metadata synchronization overhead.

### That means optimization priority should be:
1. protect first visible image,
2. reduce duplicate metadata/grow work,
3. simplify state authority,
4. reduce non-essential hot-path coordination,
5. only then chase deeper micro-optimizations.

---

## Small and safe optimization candidates

These are intentionally conservative.

## Priority 1 — best safe wins

### A) Extract one shared “new slice header scan” helper
Use one shared helper for:
- `Lightweight2DPipeline.refresh_file_list()`
- `PyDicom2DBackend.refresh_file_list()`
- metadata-growth reconciliation where possible

**Why:** removes the clearest duplicate work without changing behavior.

### B) Make the pipeline the single W/L authority
Let the bridge query pipeline W/L instead of maintaining parallel ownership.

**Why:** reduces state duplication and makes render consistency easier to reason about.

### C) Remove duplicate prefetch triggering at slice-set time
Keep one canonical prefetch trigger per slice transition.

**Why:** small win, very low risk, reduces coordination noise.

---

## Priority 2 — still safe, slightly more careful

### D) Collapse nearest-cache lookup into one pass
Unify the drag-surrogate search so it does not walk the cache neighborhood multiple times.

### E) Strip remaining `print(...)` output from `image_io.py` viewer load path
Replace with structured logger calls only.

### F) Isolate Block B completion/grow outputs from thumbnail-side follow-up where possible
Do not change semantics yet; just narrow what the grow step must directly own.

---

## What should **not** be changed casually

To avoid optimization regressions, these should remain intact unless benchmarked carefully:
- `BACKEND_PYDICOM_QT` metadata-only early exit,
- drag-time filter suppression + settle rerender,
- surrogate frame behavior during fast drag,
- progressive terminal visibility guarantees,
- disk pixel cache,
- protected admission shell via `ui_throttle` / `SystemLoadController`.

These are not accidental complexity; they are mostly purposeful responses to real FAST viewer constraints.

---

## Final focused verdict

If the question is:

> is Block B structurally correct?

**Yes — mostly.**

If the question is:

> is Block B already optimally structured for performance and priority?

**No — not yet.**

### The biggest remaining optimization issues are:
1. duplicate header/metadata work during progressive growth,
2. split state ownership (especially W/L and some viewer-visible state),
3. hot-path coordination that still does more work than strictly necessary,
4. growth/completion logic that makes Block B carry neighboring responsibilities.

### The right next step is not redesign.
The right next step is:
- keep Block B behavior,
- trim duplicate work,
- tighten ownership,
- and verify with KPI measurements after each small change.

That is the safest path to making Block B more like the *good parts* of ClearCanvas:
- calmer ownership,
- clearer priority,
- and less extra work around the visible image path.
