# Viewer Pipeline

> **Version:** v2.2.8.1 | **Updated:** 2026-04-02
>
> See also: [VIEWER_BACKENDS_REFERENCE.md](VIEWER_BACKENDS_REFERENCE.md) for the
> complete Advanced vs Fast backend pipeline documentation.

## Overview

The viewer pipeline loads DICOM images from local storage and renders them via VTK. It must be fast enough for real-time scrolling (60 Hz target) while handling large volumetric datasets.

## Pipeline Stages

```
User opens series (click or auto-load)
  │
  ▼
┌─────────────────────────────────────────┐
│ 1. METADATA LOAD                         │
│    ├─ DB query: series instances          │
│    ├─ Build file path list               │
│    └─ Parse DICOM geometry (cached)      │
│    Timing: 5-15ms (DB), variable (cache) │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ 2. IMAGE I/O                             │
│    image_io.load_single_series_by_number │
│    ├─ Read DICOM files from disk         │
│    ├─ SimpleITK ReadImage (3D volume)    │
│    └─ Parse window/level defaults        │
│    Timing: 27-384ms                      │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ 3. ITK FILTERS (apply_filters)           │
│    ├─ Noise reduction (Gaussian)         │
│    ├─ Contrast enhancement               │
│    ├─ Sharpening (modality-dependent)    │
│    └─ Adaptive thread count              │
│    Timing: 150ms-3s (modality dependent) │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ 4. ITK→VTK CONVERSION (convert_itk2vtk) │
│    ├─ Array data copy (ITK→numpy→VTK)   │
│    ├─ Y-flip compensation                │
│    ├─ Direction matrix stored in field   │
│    │   data (row 1 negated!)             │
│    └─ Spacing/origin preserved           │
│    Timing: 2-45ms                        │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ 5. VTK DISPLAY                           │
│    ├─ vtkImageReslice (pass-through)     │
│    ├─ Window/Level mapping               │
│    ├─ Camera setup                       │
│    └─ Render to screen                   │
│    Timing: 5-15ms per frame              │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ 6. INTERACTIVE VIEWING                   │
│    ├─ Scroll (wheelEvent → set_slice)    │
│    ├─ Zoom / Pan                         │
│    ├─ Window/Level adjustment            │
│    ├─ Measurements / Annotations         │
│    └─ Reference line sync                │
│    Timing: <16ms target (60 Hz)          │
└─────────────────────────────────────────┘
```

## Coordinate Systems

Five coordinate systems are involved (see `IMAGE_PIPELINE_REFERENCE.md` for details):

1. **DICOM Patient (LPS+)** — Physical patient space
2. **SimpleITK** — ZYX array with LPS directions
3. **VTK Pre-Reslice** — Y-flipped from ITK conversion
4. **VTK Post-Reslice** — After ImageReslice pass-through
5. **Display** — Screen pixels

### Critical Rule
> **Do NOT re-sort metadata['instances'] by IPP.** VTK slices are in instance_number order (files are `Instance_NNNN.dcm` loaded via natsort). Re-sorting by IPP broke reference lines in v1.09.5-v1.09.7.

### Direction Matrix
> The stored DirectionMatrix in field data has **row 1 negated** (Y-flip compensation from `convert_itk2vtk`). Do not use it directly for DICOM normal comparisons without un-negating row 1 first.

## Scroll Performance Architecture

```
wheelEvent (user scrolls)
  ├─ gc.disable()         ← Suppress GC during burst
  ├─ _in_wheel_scroll = True
  ├─ Coalesce timer (adaptive throttle)
  │   └─ set_slice(new_index)
  │       ├─ Skip camera zoom save/restore (fast path)
  │       ├─ Skip interactor style update
  │       ├─ Throttle Lock Sync to 100ms
  │       └─ VTK render
  ├─ Reference line update (round-robin, 1 target/tick)
  └─ GC re-enable timer (2000ms after last render)
```

### Scroll Guardrails
- `_in_wheel_scroll` flag: skips expensive per-frame operations
- Adaptive throttle: 25% of frame time
- GC suppression: prevents collection pauses during scroll
- Round-robin reference lines: 1 target per tick (not all)
- Lock Sync: throttled to 100ms during scroll

### ⚠ Critical Rule: Never Modify Reslice During Scroll

> **Do NOT** call `reslice.SetInterpolationMode*()` or `reslice.Modified()`
> during interactive scroll. The reslice carries a non-identity direction-matrix
> transform (Y-flip from `convert_itk2vtk`). Dirtying it causes VTK to recompute
> the output extent, which can collapse the slice range to a single slice,
> freezing the image permanently. This was the root cause of the v2.2.5 scroll
> freeze bug. Fixed in v2.2.6 — see [VIEWER_BACKENDS_REFERENCE.md §4](VIEWER_BACKENDS_REFERENCE.md#4-known-bug-history--reslice-nn-interpolation-corruption).

## Backends

| Backend | Technology | Use Case |
|---------|-----------|----------|
| **VTK/SimpleITK** (default) | Full 3D volume, ITK filters, VTK render | Rich viewing, measurements, MPR |
| **PyDicom 2D** (Phase 1) | Per-slice lazy decode, Qt 2D render | Lightweight browsing, download-time viewing |

Backend selection: `resolve_viewer_backend(metadata, settings)` — single authority.

## Key Files

| File | Responsibility |
|------|----------------|
| `PacsClient/pacs/patient_tab/utils/image_io.py` | Series loading, file I/O |
| `PacsClient/pacs/patient_tab/utils/image_filters.py` | ITK filter pipeline |
| `tools/vtk/_base_vtk.py` | VTK widget base, scroll handling, GC management |
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget.py` | Viewer container, series management |
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` | Per-viewer logic |

## ZetaBoost Preload

After initial display, ZetaBoost prefetches adjacent series:

```
Active viewing: Series N
  │
  ├─ Interactive lane: immediate (user-triggered)
  ├─ Warmup lane: Series N±1, N±2 (2 workers, IDLE priority)
  └─ Background lane: remaining series (2 workers, IDLE priority)
```

Cache hierarchy:
- **L1 (memory)**: Most recently used series, LRU eviction
- **L2 (disk)**: Processed volumes on disk with SQLite manifest

## Stability Considerations

1. **Thread safety**: `asyncio.to_thread()` for loading, Qt signals for UI updates
2. **Memory pressure**: L1 cache with LRU eviction prevents unbounded growth
3. **GC management**: Suppressed during scroll, re-enabled after 2s idle
4. **Error recovery**: Fallback UI states on load failure
5. **Warmup isolation**: IDLE priority threads, max_itk_threads=1 during DL_WARMUP

## Progressive Display (v2.2.8.1)

Progressive display shows images incrementally as they download, instead of waiting
for the entire series to complete.

### Lifecycle

```
DM seriesProgressUpdated(sn, downloaded, total)
  │
  ▼
on_series_images_progress()  [100ms per-series debounce]
  │
  ├─ First batch (sn not in _progressive_display_done):
  │   └─ _start_progressive_display(sn)
  │       ├─ _ensure_import_folder_path()  [resolve study_uid → disk path]
  │       ├─ _load_single_series_on_demand(sn)
  │       ├─ _display_series_after_load(sn)
  │       ├─ _activate_progressive_mode_on_viewers(sn)
  │       └─ _progressive_display_done.add(sn)  [MUST be AFTER activation]
  │
  └─ Subsequent batches (sn in _progressive_display_done):
      └─ _grow_progressive_fast(sn)
          └─ _progressive_grow_timer fires at 150ms intervals
```

### Guard States

| Guard | Type | Purpose |
|-------|------|---------|
| `_progressive_display_inflight` | `set` | Prevents duplicate concurrent load tasks for same series |
| `_progressive_display_done` | `set` | Marks series that completed initial display — routes to grow path |
| Done-guard recovery | scan | If `sn` in done but no progressive viewer found, re-enters progressive mode |

### Critical Rules

- `done.add(sn)` MUST run AFTER `_activate_progressive_mode_on_viewers()` completes on the main thread
- Background threads MUST NOT add to `_progressive_display_done` directly — marshal via `QTimer.singleShot(0, callback)`
- FAST mode only — the progressive path returns early for Advanced/VTK backends

### Stale OS-Flush Guard (v2.2.8.3)

**Problem**: `_progressive_grow_timer` is single-shot (`setSingleShot(True)`).  When it fires
and `loader.grow()` returns a count lower than expected because the OS has not yet flushed all
downloaded files to disk (`os.scandir` misses the last N files), `last_grow_count` is set to
the stale value.  No more DM signals arrive (download complete).  The timer will not fire again.
**Result: viewer stuck forever on the last N images.**

This same deadlock applies to the *one-shot path* (non-progressive viewer + completion signal):
`_grow_progressive_fast` is called directly without the timer, so there is no retry at all.

**Fix in `_grow_progressive_fast`** — stale-grow guard (max 3 retries = 450 ms):
```python
if new_count < pending_count and info.get("_stale_retry_count", 0) < 3:
    info["_stale_retry_count"] += 1
    info["pending_downloaded"] = pending_count   # keep retry condition true
    for vtk_w2, _ in viewers:
        if not vtk_w2._progressive_mode:          # one-shot path: enter progressive
            vtk_w2.enter_progressive_mode(total, series_number)
            vtk_w2.update_available_slice_count(new_count)
    if not self._progressive_grow_timer.isActive():
        self._progressive_grow_timer.start()      # restart the single-shot timer
    [log STALE warning]
```

**Fix in `_flush_progressive_grow`** — safety-net (independent second layer):
```python
# After the for loop:
if any(info.get("pending_downloaded", 0) > info.get("last_grow_count", 0)
       for info in self._progressive_series.values()):
    if not self._progressive_grow_timer.isActive():
        self._progressive_grow_timer.start()
```

| Scenario | Protection |
|----------|------------|
| Timer path: stale grow | Stale guard (layer 1) + safety-net (layer 2) |
| One-shot path: stale grow | Stale guard enters progressive mode → timer starts → safety-net retries |
| Third (or later) stale grow | Max 3 retries; after 450 ms any remaining files guaranteed flushed |

### Stale Cache Guard (v2.2.8.1)

When cache has fewer slices than disk (`cached_instances < disk_files`):
1. Display stale cache IMMEDIATELY (no user-visible delay)
2. Background refresh fires after 150ms via `QTimer.singleShot(150, ...)`
3. Uses `os.scandir()` + 1s TTL cache (`_disk_count_cache`) for disk file count

### DM Notify on Drag-Drop (v2.2.8.1)

```
change_series_on_viewer(series_number)
  └─ QTimer.singleShot(0, _notify_dm_viewed_series)  [non-blocking, 500ms cooldown]
      ├─ Scan existing tabs for DM widget (avoids 100+ms widget creation)
      └─ dm.set_viewed_series(series_number)
          └─ coordinator.request_critical_series(...)
```

### Loading Spinner (v2.2.8.1)

When drag-drop targets a series not in cache:
- `viewport_spinner.show_loading("Downloading series N...")` on target viewer
- Old image must NOT remain visible (users interpret it as stall/crash)

### Viewer Metadata Sync (v2.2.8.7)

**Problem:** `ImageViewer2D.metadata` is a `copy.deepcopy()` from creation time.  When
progressive grow adds slices to the VTK volume and updates `lst_thumbnails_data`, the live
viewer's metadata copy is stale.  Any method indexing `metadata['instances'][slice_index]`
crashes with `IndexError` for slices beyond the initial count — producing white/missing images.

**Metadata ownership chain:**

```
lst_thumbnails_data[i]["metadata"]          ◄── SOURCE (mutated by _refresh_stored_metadata_instances)
    │
    │  copy.deepcopy() in create_new_vtk_widget
    ▼
ImageViewer2D.metadata                     ◄── STALE COPY (frozen at widget creation)
    │
    │  Consumed by:
    ├─ apply_default_window_level(idx)     → per-slice W/L
    ├─ set_window_level(ww, wc)            → is_rgb check
    ├─ update_corners_actors()             → rows/columns
    └─ load_bottom_left_actors()           → rows/columns
```

**Fix — `_sync_viewer_metadata_instances(series_number)`:**

After every `_refresh_stored_metadata_instances()` call, `_sync_viewer_metadata_instances`
patches all live `ImageViewer2D.metadata['instances']` from the source dict.  Called from
5 grow paths:

```
_grow_progressive_fast          ─┐
on_series_download_fully_complete│
change_series_on_viewer (grow)   ├─► _refresh_stored_metadata_instances(sn)
_completion_verify_series        │       then
_completion_sweep_tick          ─┘   _sync_viewer_metadata_instances(sn)
```

**Defensive fallback (viewer_2d.py):**

All `metadata['instances'][idx]` accesses are bounds-checked.  When `idx >= len(instances)`,
fallback behavior avoids crash:

| Method | Fallback |
|--------|----------|
| `apply_default_window_level` | `GetScalarRange()` auto-calc W/L |
| `set_window_level` | Default `is_rgb=False` |
| `update_corners_actors` | VTK `GetDimensions()` for rows/columns |
| `load_bottom_left_actors` | VTK `GetDimensions()` for rows/columns |

## Test Coverage

Viewer pipeline tests: `tests/viewer/test_fast_viewer_pipeline.py` (11 tests)

| Test | What it validates |
|------|-------------------|
| `test_apply_loaded_series_data_rehydrates_parent_cache_without_refresh` | Cache rehydration on series load |
| `test_get_series_by_number_fast_rehydrates_from_full_cache` | Fast-path cache hit |
| `test_progressive_display_done_set` | Done-guard prevents duplicate initial loads |
| `test_progressive_display_inflight_guard` | Inflight guard deduplication |
| `test_ensure_import_folder_path` | Study path resolution during download |
| `test_disk_count_cache_ttl` | `os.scandir` cache expiry at 1s |
| `test_dm_notify_cooldown` | 500ms per-series cooldown enforcement |
| `test_done_guard_recovery` | Recovery path re-activates progressive mode |
| `test_threaded_done_add_ordering` | Background thread cannot race done.add |
| + 2 additional | Edge cases and boundary conditions |

FAST Viewer live-sync tests: `tests/viewer/test_fast_viewer_live_sync.py` (23 tests, L1–L23)

| Tests | What they validate |
|-------|--------------------|
| L1–L11 | Individual grow mechanics (loader.grow, slider, booster, reslice, fallbacks) |
| L12–L14 | Multi-batch lifecycle: monotonic counts, completion, metadata refresh |
| L15 | KPI: 10 batches × 2 viewers < 5ms |
| L16–L18 | Routing: timer-start conditions, delta threshold, completion bypass |
| L19–L20 | Reslice every batch; counts monotonically non-decreasing |
| **L21** | **Stale grow: timer restarted, retry tracked, exit NOT called** |
| **L22** | **One-shot stale grow: viewer enters progressive mode so retry finds it** |
| **L23** | **_flush_progressive_grow safety-net: restarts timer after stale grow** |
