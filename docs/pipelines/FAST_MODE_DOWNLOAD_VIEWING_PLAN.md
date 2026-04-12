# Fast Mode — Download-Time Viewing Plan

> ⚠️ **Historical planning document (proposal-era).**
> This file captures design intent at the time it was written and may not match
> current implementation details.
>
> For current architecture/debugging truth, start with:
> - [Viewer Docs Hub](../viewer/README.md)
> - [FAST Pipeline Detailed](../viewer/FAST_PIPELINE_DETAILED.md)
> - [Viewer Backends Reference](VIEWER_BACKENDS_REFERENCE.md)

**Version:** v2.2.3.5.0 (Plan)  
**Status:** Proposed  
**Author:** AI Assistant  
**Date:** 2025-07-10  

---

## 1. Problem Statement

When the user is in **Fast mode** (PyDicom 2D / Qt 2D backend with local ±20 boost) and opens a study that is **still downloading**, the viewer must:

1. Show the series **immediately** as images arrive — no waiting for full download.
2. Set the **correct scrollbar range** from the start (e.g., 156 slices), not grow it as files arrive.
3. Cache **±20 slices** around the user's current scroll position using `ImageSliceBooster`.
4. **Detect new images** arriving during active viewing and integrate them seamlessly.
5. **Not lag** — the viewer must remain responsive at all times.

### Current Bug
> "Scrollbar became filled only when it reached the middle of the page"

**Root cause:** When a series enters the layout for the first time during download, the slider max is set from `get_count_of_slices()` which returns the number of files currently on disk, not the total expected. The `enter_progressive_mode(total)` call happens *after* the first display, but the slider was already set to the partial count.

---

## 2. Architecture Overview

### Current System (Advanced/VTK Mode)

```
Download Manager (10x/sec @ 100ms throttle)
    ↓
home_ui.py: on_series_progress()
    ↓
PatientWidget.series_images_progress.emit(sn, current, total)
    ↓
ViewerController.on_series_images_progress()
    ├─ First batch ≥ 10 → _start_progressive_display()
    │    └─ _async_load_and_display_series(sn, progressive_total=total)
    │        └─ _load_partial_series_from_disk() [allow_lazy_backend=False → VTK]
    │            └─ grow_vtk_inplace() + enter_progressive_mode()
    │
    └─ Subsequent batches → _progressive_grow_timer (500ms debounce)
         └─ _flush_progressive_grow()
             └─ _grow_progressive_viewer_async()
                 └─ _load_partial_series_from_disk() → grow_progressive_series()
```

**Problem in Fast mode:** The VTK-centric growth path (`grow_vtk_inplace`, `_load_partial_series_from_disk` with `allow_lazy_backend=False`) bypasses the PyDicom lazy backend entirely. Fast mode needs a **different progressive path** that:
- Uses PyDicom lazy loaders instead of VTK volume reconstruction
- Leverages `ImageSliceBooster` for ±20 window caching
- Only reads DICOM headers for metadata, pixel data on demand

### Proposed System (Fast Mode)

```
Download Manager (10x/sec @ 100ms throttle)
    ↓
home_ui.py: on_series_progress()
    ↓
PatientWidget.series_images_progress.emit(sn, current, total)
    ↓
ViewerController.on_series_images_progress()
    │
    ├─ [METADATA-FIRST] Before any viewer exists:
    │    Store total_expected in _progressive_series[sn]
    │
    ├─ First batch ≥ 10 in Fast mode:
    │    └─ _start_progressive_display_fast(sn, downloaded, total)
    │        ├─ 1. Read DICOM headers only (metadata: WL, dims, spacing)
    │        ├─ 2. Create PyDicom lazy backend with partial file list
    │        ├─ 3. Set slider max = total (from download task metadata)
    │        ├─ 4. Set _available_slice_count = downloaded
    │        ├─ 5. Activate ImageSliceBooster(sn, paths, center=0)
    │        └─ 6. Display first slice via lightweight 2D pipeline
    │
    └─ Subsequent batches in Fast mode:
         └─ _grow_progressive_fast(sn, downloaded, total)
             ├─ 1. Scan new DICOM files on disk
             ├─ 2. Update PyDicom backend's _slices list
             ├─ 3. Update _available_slice_count
             ├─ 4. If new files fall within ±20 window → update booster paths
             └─ 5. No VTK reconstruction needed!
```

---

## 3. Detailed Design

### 3.1 Metadata-First Scrollbar (Priority 1 — Fixes the scrollbar bug)

**Goal:** When a series enters the viewer layout, immediately set slider max = total expected, even if 0 files are on disk.

**Where:** `widget_viewer.py` lines 680-684 and `_activate_progressive_mode_on_viewers()`

**Current flow:**
```python
# widget_viewer.py line 682 — runs AFTER series data loaded
self.slider.setMaximum(max(0, self.get_count_of_slices() - 1))
```

`get_count_of_slices()` already handles progressive mode:
```python
if self._progressive_mode and self._total_expected_slices > 0:
    return self._total_expected_slices
```

**Bug:** The `enter_progressive_mode()` call happens AFTER `switch_series()`, which already set the slider. By the time progressive mode is active, the slider has the wrong max.

**Fix:**
1. In `on_series_images_progress()`: When the **first** progress signal arrives for a series, store `{total, last_grow_count: 0}` immediately (already done).
2. In `_start_progressive_display()` / `_async_load_and_display_series()`: Pass `progressive_total` to `switch_series()` so it can set the correct slider max **during** initial setup, not after.
3. In `switch_series()`: Accept optional `progressive_total` param. If > 0, call `enter_progressive_mode(total, sn)` BEFORE setting slider max.

**Changes required:**
- `widget_viewer.py`: `switch_series()` — add `progressive_total=0` parameter, call `enter_progressive_mode()` before slider setup if > 0.
- `patient_widget_viewer_controller.py`: Pass `progressive_total` through the display chain.

### 3.2 Fast Mode Progressive Display (Priority 2)

**Goal:** When in Fast mode, use PyDicom lazy backend for progressive loading instead of the VTK grow-in-place path.

**Key insight:** In Fast mode, the PyDicom backend loads slices on-demand from disk. We don't need to "grow" a VTK volume. We only need to:
1. Tell the backend about new files
2. Update the available slice count
3. Let the ±20 booster pre-decode nearby slices

#### 3.2.1 New method: `_start_progressive_display_fast()`

```python
def _start_progressive_display_fast(self, series_number, downloaded, total):
    """Fast mode: display partial series using PyDicom lazy backend."""
    # 1. Use existing _async_load_and_display_series with lazy backend
    #    (pass allow_lazy_backend=True, progressive_total=total)
    # 2. After display: activate ImageSliceBooster with current file list
    # 3. Set slider to full range immediately
```

#### 3.2.2 New method: `_grow_progressive_fast()`

```python
def _grow_progressive_fast(self, series_number, downloaded, total):
    """Fast mode: update backend with newly arrived files."""
    # 1. Refresh PyDicom backend's file list (_slices)
    # 2. Update _available_slice_count on widget
    # 3. Update ImageSliceBooster paths if total changed
    # 4. NO VTK grow needed — lazy backend handles it
```

#### 3.2.3 PyDicom backend: `refresh_file_list()` new method

Add to `pydicom_2d_backend.py`:
```python
def refresh_file_list(self, new_paths=None):
    """Re-scan series directory for new DICOM files.
    
    Called during progressive download to detect newly arrived files.
    Only adds new files — never removes existing ones.
    Returns the new total slice count.
    """
    # Scan for new .dcm files not in current _slices
    # Read headers only (stop_before_pixels=True)
    # Append to _slices list maintaining instance_number order
    # Return len(self._slices)
```

#### 3.2.4 ImageSliceBooster integration

When the user is viewing a partially downloaded series in Fast mode:

1. **On initial display**: `set_active(sn, available_paths, center=0)`
2. **On new files arriving** (within ±20 window): Update `_instance_paths` and restart worker for the extended range.
3. **On scroll**: Normal `on_slice_changed()` — slices outside the available range show the download overlay.

New method needed on `ImageSliceBooster`:
```python
def update_paths(self, series_number, instance_paths):
    """Update the file list for an active series (new files downloaded).
    
    Does NOT restart the worker unless new files fall within the 
    current ±WINDOW range and aren't cached yet.
    """
```

### 3.3 New-Slice Detection & Integration (Priority 3)

**Goal:** When images 51-60 arrive while viewing slice 45, seamlessly integrate them.

**Trigger:** `on_series_images_progress(sn, 60, 156)` fires.

**Fast mode flow:**
1. Timer debounce (500ms) fires `_flush_progressive_grow()`.
2. For Fast mode viewers: call `_grow_progressive_fast()` instead of `_grow_progressive_viewer_async()`.
3. `_grow_progressive_fast()`:
   - Calls `pydicom_backend.refresh_file_list()` on executor thread.
   - Returns new total on-disk count.
   - Updates `vtk_w.update_available_slice_count(new_count)`.
   - Calls `booster.update_paths(sn, updated_paths)` if booster is active for this series.
4. If current slice (45) is within available range (0-59) and within ±20 window: slice renders instantly from booster cache.
5. If current slice is beyond available range: download overlay shown.

### 3.4 Scroll Boundary Behavior

| Scenario | Behavior |
|----------|----------|
| User scrolls to slice 45, only 30 downloaded | Show download overlay "Downloading... 30/156 images" |
| User scrolls to slice 20, 50 downloaded | Normal display from ±20 booster cache |
| User scrolls to slice 155, 100 downloaded | Show download overlay, clamp effective display |
| User scrolls rapidly through mix of available/unavailable | Overlay shows/hides per slice, no lag |
| Download completes (156/156) | `exit_progressive_mode()`, hide overlay, full series |

---

## 4. Files to Modify

### 4.1 `widget_viewer.py`

| Change | Lines | Description |
|--------|-------|-------------|
| `switch_series()` | ~2000 | Add `progressive_total=0` param; if > 0, call `enter_progressive_mode()` before slider setup |
| `get_count_of_slices()` | ~2273 | Already handles progressive mode ✓ |
| Slider setup after render | ~682 | Already uses `get_count_of_slices()` which returns total_expected in progressive mode ✓ |

### 4.2 `patient_widget_viewer_controller.py`

| Change | Lines | Description |
|--------|-------|-------------|
| `on_series_images_progress()` | ~697 | Branch on `_is_fast_viewer_mode()` for fast-path growth |
| `_start_progressive_display()` | ~770 | Branch: Fast mode → `_start_progressive_display_fast()` |
| New: `_start_progressive_display_fast()` | — | PyDicom lazy + booster activation |
| New: `_grow_progressive_fast()` | — | Refresh backend file list + update available count |
| `_flush_progressive_grow()` | ~800 | Branch: Fast viewers → `_grow_progressive_fast()` |
| `_load_partial_series_from_disk()` | ~885 | Allow `allow_lazy_backend=True` when in Fast mode |
| `_activate_progressive_mode_on_viewers()` | ~922 | Pass progressive_total to `switch_series()` |

### 4.3 `pydicom_2d_backend.py`

| Change | Lines | Description |
|--------|-------|-------------|
| New: `refresh_file_list()` | — | Re-scan directory, append new DICOM headers, return new count |

### 4.4 `image_slice_booster.py`

| Change | Lines | Description |
|--------|-------|-------------|
| New: `update_paths()` | — | Update instance_paths for growing series without full reset |

---

## 5. Implementation Order

### Phase A: Scrollbar Fix (immediate, small change)
1. Modify `switch_series()` to accept `progressive_total` and call `enter_progressive_mode()` early.
2. Thread `progressive_total` through `_display_first_series_in_all_viewers()` → `switch_series()`.
3. **Result:** Scrollbar shows full range from the first display.

### Phase B: Fast Mode Progressive Path (core work)
1. Add `refresh_file_list()` to `pydicom_2d_backend.py`.
2. Add `update_paths()` to `image_slice_booster.py`.
3. Add `_start_progressive_display_fast()` to viewer controller.
4. Add `_grow_progressive_fast()` to viewer controller.
5. Wire branching in `on_series_images_progress()` and `_flush_progressive_grow()`.
6. **Result:** Fast mode viewers update incrementally without VTK overhead.

### Phase C: Booster Integration (polish)
1. Activate `ImageSliceBooster` when Fast mode viewer opens a downloading series.
2. Update booster paths as new files arrive.
3. Verify ±20 window covers newly downloaded slices near current position.
4. **Result:** Sub-5ms slice display even during active download.

---

## 6. Constraints & Safety Rules

1. **Do NOT re-sort by IPP.** File order = instance_number order = VTK Z-axis order.
2. **ImageSliceBooster worker = IDLE priority.** Do not bump.
3. **GC suppressed during scroll.** Do not call `gc.collect()` in any new per-frame code.
4. **500ms debounce on grow.** Do not reduce — prevents render stutter from rapid progress updates.
5. **Progressive batch size ≥ 5.** First display needs minimum viable slice set.
6. **`_in_wheel_scroll` guard.** Any new per-frame code in `set_slice()` must check this flag.
7. **Direction matrix Y-flip.** Do not use stored DirectionMatrix for DICOM normal without un-negating row 1.

---

## 7. Testing Scenarios

| Scenario | Expected Behavior |
|----------|-------------------|
| Open study with 0 downloaded, Fast mode | Loading dialog shows; first series displays at batch 10; slider shows full range |
| Scroll to undownloaded region | Download overlay appears; returns to normal once slice becomes available |
| Download completes while viewing | Progressive mode exits; overlay hides; full scroll range works |
| Switch series during download | New series enters progressive mode; old booster cleared; new booster starts |
| Rapid scroll during download | No lag; ±20 booster serves cached slices; overlay for uncached |
| Mode switch Fast → Advanced during download | Progressive mode continues with VTK path; no crash |
| Very large series (700+ images) | Booster ±20 window stays bounded (~25 MB); no memory explosion |

---

## 8. Metrics to Track

| Metric | Target | Current |
|--------|--------|---------|
| First-slice display latency | < 500ms from first batch | ~800ms (VTK path) |
| Slice switch during download | < 10ms (from booster) | ~15ms (VTK Render) |
| Memory overhead per series during download | < 30 MB (booster only) | ~200 MB (VTK full volume) |
| Scrollbar accuracy at first display | 100% (total from metadata) | Wrong until progressive_mode |
| Download overlay show/hide latency | < 1 frame (16ms) | N/A (not implemented for Fast) |

---

## 9. Signal Flow Diagram (Final)

```
                        ┌─────────────────────┐
                        │   Download Manager   │
                        │  (Zeta, 100ms rate)  │
                        └──────────┬──────────┘
                                   │ seriesProgressUpdated(uid, series_uid, current, total)
                                   ▼
                        ┌─────────────────────┐
                        │     home_ui.py       │
                        │ on_series_progress() │
                        └──────────┬──────────┘
                                   │ series_images_progress.emit(sn, current, total)
                                   ▼
            ┌──────────────────────────────────────────────┐
            │      ViewerController                        │
            │      on_series_images_progress()             │
            │                                              │
            │  ┌─ Is Fast mode? ──────────────────────┐    │
            │  │ YES                          NO      │    │
            │  ▼                              ▼       │    │
            │  _start_progressive_     _start_progressive_ │
            │  display_fast()          display() [VTK]     │
            │  │                       │                   │
            │  ├─ PyDicom lazy open    ├─ VTK load partial │
            │  ├─ Slider = total       ├─ grow_vtk_inplace │
            │  ├─ Booster.set_active   ├─ enter_progressive│
            │  └─ Render slice 0       └─ Render           │
            │                                              │
            │  On growth:              On growth:          │
            │  _grow_progressive_      _grow_progressive_  │
            │  fast()                  viewer_async()       │
            │  │                       │                   │
            │  ├─ backend.refresh()    ├─ load from disk   │
            │  ├─ update avail count   ├─ grow VTK Z       │
            │  └─ booster.update_paths └─ update avail cnt │
            └──────────────────────────────────────────────┘
```

---

## 10. Dependencies

- `PySide6`: QTimer, QLabel (overlay), Signal/Slot
- `pydicom`: Header-only reads (`stop_before_pixels=True`) for metadata
- `numpy`: Pixel array cache in ImageSliceBooster
- `natsort`: File ordering in series directory scan
- **No new external dependencies required.**
