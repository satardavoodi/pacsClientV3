# FAST Viewer Performance Optimization — v2.3.3-perf

**Date:** 2026-04-19  
**Phase:** B2+B3 (Instrumentation + Optimization)  
**Backend:** `pydicom_qt` (FAST mode only — Advanced/VTK is unaffected)

---

## Summary

Optimized the FAST viewer scroll hot-path from **12.7ms P50 frame time** to **1.8ms P50** during active scrolling — a **7× improvement**. Zero slow frames (>16ms) during scroll, up from 52/200.

---

## Baseline (pre-optimization, synthetic 512×512)

| Metric | Value |
|--------|-------|
| W/L P50 | 5.46ms |
| W/L P95 | 10.66ms |
| Filter P50 | 5.00ms |
| Frame P50 | 12.7ms |
| Frame P95 | 37.8ms |
| Slow frames (>16ms) | 52/200 |
| Slow frames (>33ms) | 14/200 |
| Scroll FPS | 61 |

---

## Optimizations Applied

### B3.1 — W/L LUT for int16 data

**File:** `PacsClient/pacs/patient_tab/utils/dicom_windowing.py`

- Added `window_to_uint8_fast()` with LUT-based path for int16/uint16 data
- 65536-entry uint8 LUT indexed by uint16 view of int16 data (two's complement aware)
- Uses numpy fancy indexing (`lut[arr.view(uint16)]`) — faster than `np.take` or `clip+cast`
- LUT cache with 16-entry max, keyed by (lower, upper, dtype)
- Float32 path uses non-mutating `_window_direct_fast()` — safe for pixel cache

**Also modified:** `modules/viewer/fast/lightweight_2d_pipeline.py` — `_decode_slice()` keeps data as int16 instead of converting to float32 when slope=1.0 and intercept is integer

### B3.2 — Filter skip during fast scroll

**File:** `modules/viewer/fast/lightweight_2d_pipeline.py`

- Added `_fast_interaction` state flag on `Lightweight2DPipeline`
- `get_rendered_frame()` skips OpenCV filter when `_fast_interaction=True`
- Falls back to filtered cache entry if available (filtered frame is always acceptable)
- `rerender_current_filtered()` re-applies filter on scroll-stop

### B3.3 — Annotation skip during fast scroll

**File:** `modules/viewer/fast/qt_viewer_bridge.py`

- `set_slice()` accepts `fast_interaction` parameter
- Skips `_update_annotations()` during fast scroll
- `end_fast_interaction()` re-renders with filter and updates annotations on scroll-stop

### B3.4 — WheelEvent wiring + scroll-stop timer

**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_scroll.py`

- Qt fast-path wheelEvent now passes `fast_interaction=True` to bridge
- Added `_qt_scroll_stop_timer` (200ms single-shot QTimer)
- Timer restarts on each wheel event; fires `_on_qt_scroll_stop()` which calls `end_fast_interaction()`
- Separate from VTK path's `_reenable_gc` mechanism

### B3.5 — Debug logging gated

**Files:** `_vw_scroll.py`, `lightweight_2d_pipeline.py`

- All `logger.debug()` calls in hot paths gated with `logger.isEnabledFor(logging.DEBUG)`
- Prevents string formatting overhead (~0.1-0.3ms per call) during scroll
- Filter diagnostic string construction moved inside the debug gate

### B3.6 — QImage.copy() elimination

**File:** `modules/viewer/fast/lightweight_2d_pipeline.py`

- `_numpy_to_qimage_gray()` and `_numpy_to_qimage_rgb()` no longer call `.copy()`
- Instead, store numpy buffer reference on QImage (`qimg._np_buffer = arr`) to prevent GC
- Saves ~0.2ms per frame for 512×512 images

---

## Post-Optimization Results

### Normal rendering (with filter)

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| W/L P50 | 5.46ms | 1.7ms | 3.2× |
| W/L P95 | 10.66ms | 2.7ms | 3.9× |
| Frame P50 | 12.7ms | 7.1ms | 1.8× |
| Frame P95 | 37.8ms | 9.6ms | 3.9× |
| Slow (>16ms) | 52/200 | 0/200 | eliminated |
| FPS | 61 | 135 | 2.2× |

### Fast-scroll mode (filter skipped, during active scrolling)

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| W/L P50 | 5.46ms | 1.7ms | 3.2× |
| Frame P50 | 12.7ms | 1.8ms | **7.1×** |
| Frame P95 | 37.8ms | 2.9ms | **13×** |
| Slow (>16ms) | 52/200 | 0/200 | eliminated |
| FPS | 61 | 518 | **8.5×** |

---

## Latency budget (updated)

During active scrolling, the per-frame hot-path is:

| Stage | Time | Notes |
|-------|------|-------|
| W/L LUT lookup | ~1.7ms | int16 → uint8 via LUT fancy indexing |
| QImage wrap | ~0.06ms | No copy, buffer reference kept |
| QPainter paint | ~0.1ms | Hardware-accelerated |
| **Total** | **~1.9ms** | Well under 16ms budget |

After scrolling stops (200ms debounce):

| Stage | Time | Notes |
|-------|------|-------|
| OpenCV filter | ~2ms | GaussianBlur + AddWeighted |
| Annotation update | ~0.5ms | Corner text, overlays |
| **Total** | **~2.5ms** | One-time cost on scroll-stop |

---

## Benchmark tool

`tests/performance/test_fast_scroll_perf.py`

```bash
# Synthetic benchmark (all stages)
python tests/performance/test_fast_scroll_perf.py --synthetic

# Fast-scroll simulation (filter skipped)
python tests/performance/test_fast_scroll_perf.py --fast-scroll

# Both + comparison
python tests/performance/test_fast_scroll_perf.py --all
```

---

## Test coverage

All optimizations verified against:
- 56 viewer pipeline tests (`test_fast_viewer_pipeline.py`)
- 34 Stage 1 migration tests (`test_stage1_migration_validation.py`)
- 15 Stage 2 hardening tests (`test_stage2_hardening_validation.py`)
- 24 import smoke tests (`test_import_smoke.py`)
- **Total: 129 tests, all passing**

---

## Critical rules added

- **W/L `window_to_uint8_fast` must NOT mutate its input array** — the pixel cache passes the same object on cache hits. The float32 path uses `_window_direct_fast()` which creates a new array. The int16 LUT path returns `lut[view]` which also creates a new array.
- **`_qt_scroll_stop_timer` is separate from `_reenable_gc`** — the Qt fast-path does not use VTK's GC suppression mechanism. The 200ms single-shot timer handles scroll-stop for the Qt path exclusively.
- **Filter skip is transparent to the viewer** — the bridge's `set_slice()` method handles `fast_interaction` internally. Callers just pass the flag.
- **LUT is built in uint16 index order for int16 data** — indices 0..32767 map to int16 values 0..32767; indices 32768..65535 map to int16 values -32768..-1 (two's complement). This allows direct `lut[arr.view(uint16)]` without offset arithmetic.
