# Block A connection review

**Date:** 2026-04-19  
**Scope:** Thumbnail/sidebar pipeline only (Block A), with its runtime relations to Qt/PySide, database, disk/cache, and Blocks B/C.

## Executive summary

Block A is now much clearer than before, but it is still not an isolated island — it is a **Qt-facing projection layer** that depends on:

- **Qt/PySide** for widgets, timers, signals, drag/click events, and theme updates
- **database services** for normalized series metadata
- **disk/cache** for thumbnail bytes and fallback files
- **Block B** for series switching and first-image-visible handoff
- **Block C** for progress cadence, compact UI policy, and overlap protection during heavy interaction/download

The current direction is good: service extraction has reduced duplication and improved maintainability. The main remaining architectural concern is that Block A still owns some stateful UI policy that is influenced by Block B/C runtime conditions.

---

## Current Block A runtime pipeline

1. **`SeriesMetadataService`**  
   File: `PacsClient/utils/series_metadata_service.py`
   - resolves `study_uid` from `PatientWidget`
   - reads normalized series metadata from DB helpers

2. **`ThumbnailImageSourceService`**  
   File: `PacsClient/pacs/patient_tab/utils/thumbnail_image_source_service.py`
   - loads thumbnail pixels from `ThumbnailStore`
   - falls back to explicit PNG file path on disk

3. **`ThumbnailProjectionService`**  
   File: `PacsClient/pacs/patient_tab/utils/thumbnail_projection_service.py`
   - converts loaded/cached metadata into sidebar projection payloads
   - creates standardized metadata for immediate/cached rendering

4. **`ThumbnailBatchRunner`**  
   File: `PacsClient/pacs/patient_tab/utils/thumbnail_batch_runner.py`
   - owns Qt timer cadence and batch iteration for sidebar scheduling

5. **`ThumbnailPanel`**  
   File: `PacsClient/pacs/patient_tab/ui/patient_ui/thumbnail_panel.py`
   - owns Qt layout and per-item thumbnail processing
   - now also keeps O(1) duplicate-detection indexes for better performance

6. **`ThumbnailManager`**  
   File: `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`
   - owns widget creation
   - owns border/progress/selection visual state
   - receives progress/completion updates and applies coalesced UI changes

---

## Connection to Qt / PySide

### Main Qt objects

- `ThumbnailPanel(QWidget)`
- `ThumbnailManager(QObject)`
- thumbnail widgets created by `ThumbnailManager.create_thumbnail_widget(...)`
- `QTimer` in `ThumbnailPanel` for progressive/cached batch display
- `QTimer` in `ThumbnailManager` for coalesced progress/border updates
- Qt signals on `PatientWidget`:
  - `series_images_progress`
  - `series_downloaded`

### Important Qt relations

#### User click → Block B switch

`ThumbnailPanel.change_series_on_viewer(...)` calls the parent widget’s `change_series_on_viewer(...)`.

Relevant files:

- `thumbnail_panel.py`
- `patient_widget_core/widget.py`
- `_vc_switch.py`

This is the main **Block A → Block B** handoff.

#### Download progress → Block A and Block B simultaneously

`HomeDownloadService.connect_dm_to_widget(...)` emits:

- `widget.series_images_progress.emit(sn, current, total)`
- `widget.series_downloaded.emit(sn)`

Those signals feed:

- **Block B** progressive/image-visible path through `ViewerController.on_series_images_progress(...)`
- **Block A** progress visuals through `ThumbnailManager.start_series_download`, `update_series_progress`, and `complete_series_download`

Relevant files:

- `home_download_service.py`
- `patient_widget_core/widget.py`
- `_vc_progressive.py`
- `thumbnail_manager.py`

### Qt quality assessment

**Good:**

- timers are used for coalescing instead of fully synchronous UI churn
- Block A updates are partially guarded against overlap conditions
- many widget updates in `ThumbnailManager` are already idempotent

**Still risky / noteworthy:**

- `ThumbnailManager` still contains a lot of widget lifecycle guarding because thumbnail widgets can disappear while async callbacks still arrive
- theme changes iterate across all thumbnail widgets, which is okay but still O(n)
- Block A remains directly aware of viewer interaction pressure via compact/throttled UI policy

---

## Connection to database

### DB path

Block A no longer queries DB directly in the panel. The path is now:

`ThumbnailPanel` → `ThumbnailProjectionService` → `ThumbnailMetadataService` → `SeriesMetadataService` → `db_manager`

Relevant functions:

- `SeriesMetadataService.get_series_metadata(...)`
- `SeriesMetadataService.get_series_list(...)`
- `get_series_by_study_and_number(...)`
- `get_series_by_study_uid(...)`

### DB quality assessment

**Good:**

- Block A DB access is now routed through a shared service
- series metadata normalization is centralized
- fallback behavior is explicit and consistent

**Still noteworthy:**

- DB lookups still happen in Block A runtime paths when metadata is not already projected
- metadata duplication can still happen across UI state, DB state, and download-progress state

### Conclusion on DB relation

The connection is **much better than before**. Block A is no longer acting like a DB layer.  
The remaining goal should be to make Block A consume even more pre-batched / pre-normalized metadata where practical.

---

## Connection to disk and cache

### Disk/cache path

Block A thumbnail image loading now goes through:

`ThumbnailPanel` → `ThumbnailImageSourceService.load_pixmap(...)`

Inside that service:

1. try `ThumbnailStore.instance().get_bytes(study_uid, series_number)`
2. if not available, fall back to `QPixmap(file_path_thumbnail)`

Relevant file:

- `modules/storage/thumbnail_store.py`

### Disk/cache quality assessment

**Good:**

- clear source priority now exists
- in-memory/disk-backed thumbnail reuse is centralized
- the panel no longer decides memory-vs-disk inline

**Still noteworthy:**

- `QPixmap(file_path_thumbnail)` is still a synchronous fallback on the UI thread
- that is acceptable as fallback, but should stay rare if cache/store hit rate is good

### Conclusion on disk relation

Block A now has a **clean disk/cache boundary**. That is a strong improvement.

---

## Relation to Block B

Block B = first image visible / series switch / initial viewer binding.

### Main Block A → Block B relations

1. **Thumbnail click / drag intent**
   - user clicks a thumbnail
   - Block A forwards series selection to `PatientWidget.change_series_on_viewer(...)`
   - Block B takes over from `_vc_switch.py`

2. **Series identity continuity**
   - Block A uses series number / UID mapping through `ThumbnailManager`
   - Block B uses the same series number for viewer targeting and switch orchestration

3. **Progressive download visibility**
   - Block A reacts visually to series progress/completion
   - Block B reacts functionally to `series_images_progress` and `series_downloaded`

### Assessment of Block A ↔ Block B relation

**Good:**

- handoff is explicit through signals/method calls
- Block A now behaves more like projection, not like a switch orchestrator

**Still noteworthy:**

- Block A still knows enough runtime state to adapt UI policy based on focus/interaction conditions
- this is understandable, but it means it is not yet a pure passive projection layer

---

## Relation to Block C

Block C = scrolling, cache, progressive grow, overlap protection, and ongoing optimization.

### Main Block A ↔ Block C relations

1. **Progress throttling / cadence**
   - `ThumbnailManager` adjusts progress cadence when scroll is active
   - compact UI is enabled for background series during heavy interaction/download overlap

2. **Viewer-awareness for UI compaction**
   - `_is_focus_series(...)` looks at current viewers / progressive markers
   - this means Block A uses some Block B/C state to decide how expensive its own UI updates should be

3. **Download overlap protection**
   - Block A progress visuals are coalesced to reduce Qt event-loop pressure during heavy download + fast interaction

### Assessment of Block A ↔ Block C relation

**Good:**

- Block A is not blindly repainting during heavy overlap
- coalescing/throttling is aligned with overall responsiveness goals

**Still noteworthy:**

- Block A remains coupled to overlap policy logic
- the more compact/throttle rules live in Block A code, the less “pure” the projection boundary becomes

### Conclusion on Block C relation

The relation is justified for performance, but architecturally it should ideally be mediated by a thinner shared policy front door, not spread further inside Block A.

---

## Current strengths

1. **Service extraction is working**
   - DB normalization is no longer hidden in the sidebar widget
   - image source selection is no longer hidden in the sidebar widget
   - projection shaping is no longer hidden in the sidebar widget

2. **Qt hot-path discipline is improving**
   - duplicated scans were replaced with O(1) sets/maps in `ThumbnailPanel`
   - this improves growth behavior as series count increases

3. **Cross-block handoff is explicit**
   - Block A does not directly load viewer images
   - it hands off into Block B through clear series-switch and progress/completion pathways

---

## Remaining risks / gaps

1. **Widget lifecycle complexity remains in `ThumbnailManager`**
   - many guards exist because async callbacks can arrive after widget changes/deletion

2. **Block A still has some policy logic influenced by B/C runtime state**
   - this is not wrong, but it means the boundary is not fully passive

3. **Synchronous fallback disk pixmap loading still exists**
   - okay as fallback, but should stay minimized

4. **Legacy debug `print()` calls were still present in Block A hot path**
   - this was a performance smell on Windows because stdout I/O can block the UI thread
   - the current pass redirects them to logger-backed debug output in `thumbnail_panel.py`

---

## Final judgment

### Qt / PySide relation
**Healthy but stateful.**  
Block A is properly implemented as a Qt-driven sidebar pipeline, but it still carries nontrivial widget lifecycle and throttling logic.

### Database relation
**Good and much cleaner than before.**  
Block A now uses shared metadata services instead of direct DB shaping in widgets.

### Disk/cache relation
**Good and explicit.**  
The source stage is now isolated, with memory/disk-backed store first and file fallback second.

### Relation to Block B
**Clear and appropriate.**  
Block A hands off series selection and receives download/series completion signals that Block B also consumes.

### Relation to Block C
**Functionally justified, architecturally still somewhat coupled.**  
Block A depends on overlap/interaction policy to avoid hurting responsiveness.

---

## Recommended next step

If we continue refining Block A, the best next slice is:

### Extract the batch/timer runner from `ThumbnailPanel`

That would make the pipeline even clearer:

1. metadata service
2. image source service
3. projection service
4. **batch runner / scheduler**
5. thumbnail panel layout host
6. thumbnail manager widget renderer

That would further separate:

- policy/scheduling
- UI hosting
- widget rendering

and make future performance work easier.