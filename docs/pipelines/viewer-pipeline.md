# Viewer Pipeline

> **Version:** v2.2.8.1 | **Updated:** 2026-04-02
>
> See also: [VIEWER_BACKENDS_REFERENCE.md](VIEWER_BACKENDS_REFERENCE.md) for the
> complete Advanced vs Fast backend pipeline documentation.
>
> Canonical architecture map: [docs/viewer/README.md](../viewer/README.md)

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
| **VTK/SimpleITK** (`vtk_simpleitk`) | Full 3D volume, ITK filters, VTK render | Rich viewing, measurements, MPR |
| **PyDicom Qt** (`pydicom_qt`) | Per-slice decode + Qt/QPainter render | Lightweight browsing, fallback-safe mode |
| **PyDicom 2D lazy** (`pydicom_2d`) | Per-slice lazy decode + VTK render path | Download-time progressive viewing, low-latency lazy decode |

Backend selection: `resolve_viewer_backend(metadata, settings)` — single authority.

## Key Files

| File | Responsibility |
|------|----------------|
| `PacsClient/pacs/patient_tab/utils/image_io.py` | Series loading, backend-aware I/O path |
| `PacsClient/pacs/patient_tab/utils/image_filters.py` | ITK filter pipeline (advanced path) |
| `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/` | VTKWidget mixins (scroll, backend binding, lazy callbacks) |
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` | Per-viewer orchestration, progressive lifecycle |
| `modules/viewer/advanced/viewer_2d.py` | Advanced viewer render pipeline |
| `modules/viewer/fast/qt_viewer_bridge.py` | FAST Qt bridge adapter |
| `modules/viewer/fast/qt_slice_viewer.py` | FAST Qt render surface |
| `modules/viewer/fast/pydicom_lazy_volume.py` | FAST lazy data source (`pydicom_2d`) |

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
  │       ├─ defer if no target viewer requested it and all viewers are already occupied
  │       ├─ _load_single_series_on_demand(sn)
  │       ├─ _display_series_after_load(sn)
  │       ├─ _activate_progressive_mode_on_viewers(sn)
  │       └─ _progressive_display_done.add(sn)  [MUST be AFTER activation]
  │
  └─ Subsequent batches (sn in _progressive_display_done):
      └─ _grow_progressive_fast(sn)
          └─ _progressive_grow_timer fires at 150ms intervals
```

    ### Admission Gate (2026-04-16)

    Progressive display now distinguishes between:

    - **actual downloaded count** — how many slices the backend/loader already knows are on disk
    - **visible/admitted count** — how many of those slices the viewer exposes right now

    For non-terminal progressive growth, `_flush_progressive_grow_impl()` caps each grow tick to:

    $$
    \min(\text{pending\_downloaded},\ \text{last\_grow\_count} + \text{admit\_batch})
    $$

    where `admit_batch` comes from `ViewerController._progressive_admit_batch_size`
    (configurable via `AIPACS_PROGRESSIVE_ADMIT_BATCH`, default **8** as of 2026-04-16; kept independent from `_progressive_grow_batch_size`).

    This keeps the downloader fast while preventing a large LAN-speed burst from being
    admitted into the viewer as one huge UI jump. Terminal completion remains **uncapped**
    so the user still sees the final full series immediately once `downloaded >= total`.

    ### Why stack/scroll stays direct

    The admission gate applies only to **non-interactive progressive growth**. It must
    not be applied to the direct stack/wheel path:

    - wheel/stack drag are user-driven and must stay low-latency
    - progressive gating is background/load-shedding logic
    - mixing them would trade overlap pressure for delayed interaction

    So the workstation pattern is:

    - **stack/wheel/drag**: direct priority path
    - **progressive growth / cache warm / other non-interactive work**: admitted in bounded steps

### Guard States

| Guard | Type | Purpose |
|-------|------|---------|
| `_progressive_display_inflight` | `set` | Prevents duplicate concurrent load tasks for same series |
| `_progressive_display_done` | `set` | Lifecycle guard — routes subsequent signals to grow path |
| Done-guard recovery | scan | If `sn` in done but no progressive viewer found, re-enters progressive mode |

### Critical Rules

- `done.add(sn)` MUST run AFTER `_activate_progressive_mode_on_viewers()` completes on the main thread
- Background threads MUST NOT add to `_progressive_display_done` directly — marshal via `QTimer.singleShot(0, callback)`
- FAST mode only — the progressive path returns early for Advanced/VTK backends
- Untargeted progressive first-display must stay deferred once a first series is already visible and there is no empty viewer. A background series may keep accumulating progress, but it must not trigger a surprise first-load/rebind on the active layout unless a viewer explicitly awaited it.
- `load_series_on_demand()` must treat `on_series_download_fully_complete()` as the authoritative completion grow. If a viewer already shows the completed disk-count after Layer 2b, only mark the thumbnail ready; do not invalidate/reload the same series again.

### Untargeted First-Display Deferral (2026-04-16)

The completeness gate protects `_start_progressive_display()` during heavy overlap, but it is not sufficient by itself. Once the workstation already has visible content, a newly downloading background series can still reach the first-batch threshold and trigger an unnecessary 1s+ metadata/load/apply cycle.

The current rule is:

- allow `_start_progressive_display()` when a viewer is explicitly awaiting the series
- allow it when an empty viewer still needs content
- otherwise, keep tracking progress and defer first-display until the user actually asks for that series

Hardening note: once that untargeted defer fires, later background progress pulses must not keep re-invoking `_start_progressive_display()` while the same “no awaiting/empty viewer” condition still holds. The controller now keeps a per-series untargeted-defer guard and only retries when layout eligibility changes.

This preserves progressive readiness without causing layout churn while the user is actively reviewing another series.

### Sync / Sidebar Idempotence (2026-04-16)

Progressive admission is already gated in batches, but the post-gate sync path must also stay cheap:

- `_update_vtk_slice_range()` should skip `update_available_slice_count()` when the visible count is unchanged
- `_sync_viewer_metadata_instances()` should append-only extend viewer metadata lists when possible instead of replacing the whole list every tick
- thumbnail progress/count/ready updates should skip `setVisible`, `setText`, and border state setters when the value is already current

The rule is simple: once the same state is already visible, do not re-write it just because another progress signal arrived.

### Post-Completion Reload Suppression (2026-04-16)

`load_series_on_demand()` still runs on the completion signal path, but after it calls `on_series_download_fully_complete(series_number)` it must check whether any viewer already shows that series at the current disk count.

If the final Layer 2b grow already exposed the full series:

- mark the thumbnail ready
- skip cache invalidation / full reload

Without this guard, the workstation can rebind or partially reload the same series immediately after completion, producing the visible “finished, then shuffled itself again” lag reported in the April 16 overlap logs.

### Done-Guard Lifecycle Rule (v2.2.9.2 — H4 fix)

**`_progressive_display_done` is a lifecycle guard, NOT a permanent cache.**

When a download lifecycle completes (all expected files visible in the viewer), the
series key MUST be discarded from `_progressive_display_done` so that a future re-open
of the same series can start a fresh progressive display.

**Why three discard sites are required:**  Download completion can be observed at three
independent points depending on OS disk-flush latency.  All three must discard the key:

| Layer | Method | When it fires |
|-------|--------|---------------|
| Layer 2b | `_on_series_download_fully_complete_impl` | Immediately on `seriesDownloadCompleted` signal |
| Layer 3 | `_completion_verify_series` | 500ms deferred (OS-flush catch-up, up to 3 retries) |
| Layer 4 | `_completion_sweep_tick_impl` | 3s periodic safety-net (handles any remaining stragglers) |

**Invariant:** Every code path that calls `self._progressive_series.pop(sn, None)` as a
lifecycle-close MUST also call `done.discard(sn)` immediately after.

```python
# Required pattern at each of the three pop sites:
self._progressive_series.pop(sn, None)
done = getattr(self, '_progressive_display_done', None)
if done is not None:
    done.discard(sn)   # idempotent — safe if Layer 2b already discarded
```

**Race safety:** `set.discard()` is idempotent.  If Layer 2b fires first and discards the
key, Layers 3 and 4 calling `discard()` again is a silent no-op.  No locking required.

**Failure mode if missing (H4):** After Cycle 1 completes, `sn` stays in `done`.  On
Cycle 2 re-open, `sn in done` is True, the recovery scan finds no viewer (none loaded yet),
and `_start_progressive_display` is silently skipped — viewer frozen forever.

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

Viewer pipeline tests: `tests/viewer/test_fast_viewer_pipeline.py` (13 tests)

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
| `test_done_guard_cleared_on_series_complete` | **H4 fix** — Layer 2b discards `done` key after completion |
| `test_done_guard_allows_restart_after_completion` | **H4 fix** — cleared guard allows `_start_progressive_display` restart on re-open |

Diagnostic scenarios:

| Scenario | Role |
|----------|------|
| `s08_repeated_open` | Detection canary — H4 CONFIRMED **always expected** (tests detector logic, not production code) |
| `s11_post_fix_repeated_open` | Post-fix health check — H4 NO_EVIDENCE **always expected** (tests real bound production methods) |

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
