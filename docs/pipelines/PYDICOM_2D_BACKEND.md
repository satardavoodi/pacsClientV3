# PyDicom 2D Backend (Phase 1)

> Related canonical docs: [Viewer Docs Hub](../viewer/README.md),
> [FAST Pipeline Detailed](../viewer/FAST_PIPELINE_DETAILED.md)

## Phase 1 Scope
- Lazy per-slice loading and decode.
- Backend toggle (`VTK / SimpleITK` vs `PyDicom 2D`).
- Non-blocking frame delivery path for scrolling.
- Tools remain on existing VTK overlay path in Phase 1.

Phase 1 does **not** move tools to backend-independent overlays yet.
That is Phase 2 scope.

If PyDicom 2D is used only as a lazy data source while VTK still renders:
- series read/decode pressure is reduced,
- but VTK render cost still exists.
This is expected and accepted for Phase 1.

## Backend Selection Guard
- `resolve_viewer_backend(metadata, settings)` is the single authoritative backend resolver.
- Viewer start/switch/reset bind through this resolver.
- If backend metadata is incomplete (`viewer_backend=pydicom_2d` without valid `lazy_loader_key`), immediate fallback to VTK is enforced.

## Runtime Decoder Requirements
Required:
- `pydicom`
- `numpy`

Recommended for compressed transfer syntaxes:
- `pylibjpeg`
- `pylibjpeg-libjpeg`
- `pylibjpeg-openjpeg`
- `pylibjpeg-rle`

Optional fallback:
- `python-gdcm`

## Dependency Installation
Runtime:
- `python -m pip install -r requirements-core.txt`

Dev/test:
- `python -m pip install -r requirements-dev.txt`

## Strict Fallback Policy
If PyDicom decode fails (missing handlers, unsupported compressed stream, or runtime decode error):
- log a clear decode-failure reason,
- mark series metadata for VTK fallback,
- force reload series through VTK backend.

## Settings
- Viewer backend selector is available in Viewer Configuration.
- Backend badge is shown per viewport (`PyDicom 2D` / `VTK / SimpleITK`).
- Setting `PyDK (PyDicom 2D Lazy Load)` applies lazy path for normal series open/switch flow.
- Setting `VTK / SimpleITK` keeps current VTK path.

## Tests and Dev Environment
- Install dev dependencies:
  - `python -m pip install -r requirements-dev.txt`
- Run tests:
  - `python -m pytest tests/viewer/test_pydicom_backend_geometry.py`
  - or via app entrypoint: `python main.py --run-tests`
  - PowerShell helper: `./run_test.ps1`

## Application-Level Verification (UI)
1. Launch app: `python main.py` (or `./run_app.ps1`).
2. Open `Settings -> Viewer`.
3. Select `PyDK (PyDicom 2D Lazy Load)` and save.
4. Open a study/series through normal workflow.
5. Verify:
   - image renders in viewer,
   - slice scrolling works,
   - WL drag works,
   - no freeze/crash,
   - thumbnail list remains visible/updated,
   - download flow remains functional.
6. Switch backend to `VTK / SimpleITK` and repeat a quick open/switch check.

## VTK Viewer Wiring — Critical Architecture Rule (v2.3.1 / 2026-04-10)

### The frozen image regression

For pydicom_2d, the viewer **MUST be wired directly to the raw lazy `vtkImageData`**
from `PyDicomLazyVolume`.  Wiring through `image_reslice.GetOutput()` (the normal
Advanced path) causes all scrolling to show a permanently frozen image:

```
WRONG (causes frozen image):
  image_reslice = ImageReslice(lazy_vtk_image_data, metadata)
  viewer.SetInputData(image_reslice.GetOutput())   ← trivial producer around reslice output

CORRECT (pydicom_2d path):
  viewer.SetInputData(lazy_vtk_image_data)         ← direct to raw numpy-backed source
```

### Why the reslice path breaks

`SetInputData(image_reslice.GetOutput())` stores the reslice output as a
**VTK trivial producer**.  `Render()` asks the trivial producer for data but
never calls `image_reslice.Update()`.  The lazy decoder fills `lazy_vtk_image_data`
(the numpy backing store), but `image_reslice.GetOutput()` is a separate
`vtkImageData` object still holding zeros.  Every scroll shows the frozen zeros.

Calling `image_reslice.Modified()` in the scroll path does NOT fix this — it
only sets the filter's own MTime, which the trivial producer never checks.

### Why direct wiring works

```
1. Lazy decoder fills numpy_array[N]  →  data present in lazy_vtk_image_data
2. mark_vtk_modified()  →  lazy_vtk_image_data.Modified()  →  MTime increases
3. Render()  →  trivial producer (wrapping lazy source) detects MTime change
              →  re-reads numpy scalars  →  correct image at SetSlice(N)
```

### What must be bypassed for pydicom_2d

| Step | Advanced path | pydicom_2d path | Reason |
|------|--------------|-----------------|--------|
| `_preprocess_vtk_image_data` | ✅ Run | ❌ **Skip** | Creates a NEW disconnected copy (via `vtkImageResample`); `mark_vtk_modified()` on original has no effect on the copy |
| `image_reslice.GetOutput()` as viewer input | ✅ Use | ❌ **Bypass** | Trivial producer never propagates upstream; decoder updates never reach viewer |
| `image_reslice.Modified()` in scroll path | ✅ Harmless | ❌ **Do not add** | Silently re-introduces freeze regression |
| `image_reslice.Update()` per slice | N/A | ❌ **Do not add** | Not needed; bypasses the whole point of lazy decoding |

### Implementation guard (viewer_2d.py)

```python
_is_pydicom_lazy = (
    getattr(getattr(self, 'vtk_widget', None), '_active_backend', None) == 'pydicom_2d'
)
if not _is_pydicom_lazy:
    self.vtk_image_data = self._preprocess_vtk_image_data(self.vtk_image_data)

_raw_lazy_vtk = self.vtk_image_data
self.image_reslice = ImageReslice(self.vtk_image_data, self.metadata)

if _is_pydicom_lazy:
    self.SetInputData(_raw_lazy_vtk)          # bypass reslice
    self.vtk_image_data = _raw_lazy_vtk
else:
    self.SetInputData(self.image_reslice.GetOutput())
    self.vtk_image_data = self.image_reslice.GetOutput()
```

The same `_is_pydicom_lazy` guard must be present in `reset_image_viewer` for both
the rebuild branch and the reconnect block — otherwise a series switch re-connects
through `image_reslice` and the freeze returns.

See [IMAGE_PIPELINE_REFERENCE.md Rule 11](IMAGE_PIPELINE_REFERENCE.md#rule-11-pydicom_2d-viewer-must-be-wired-directly-to-the-raw-lazy-vtkimagedata--not-through-image_reslice-v231--2026-04-10)
for the full technical explanation.

## Integration Notes
- Download warmup subprocess uses `allow_lazy_backend=False` to keep warmup deterministic.
- Thumbnail/study-series flow remains unchanged; lazy backend plugs into the existing `load_single_series_by_number` path.
- DB metadata structure is reused; lazy path requires valid geometry (`IOP`, `IPP`, `PixelSpacing`, `Rows/Cols`) and falls back to VTK if incomplete.

## TODO Before Phase 2
1. Non-blocking `ensure_slice_loaded` + stale-frame dropping via `generation_id`.
2. Guaranteed loader `close()/dispose` on series switch/reset.
3. Strict fallback policy validation (decode fail -> VTK reload) across all series entry paths.
4. Runtime dependency preflight checks with user-readable messages in UI/logs.
5. Metrics + throttled logging validation (`time_to_first_frame_ms`, `dicom_read_ms`, `decode_ms`, `wl_convert_ms`, `cache_hit_rate`, `dropped_frames_count`).
6. Configurable lazy cache size and prefetch window in settings (advanced/hidden is acceptable).
7. DB metadata validation hardening (incomplete geometry -> log + fallback).
8. CI test environment standardization (`pytest`, `numpy`) with one-line test command.

## Phase 2 Readiness
- Keep tool interactions independent from VTK APIs.
- Build tool overlay against shared geometry/transform contracts (`IViewer2DBackend`).
- Preserve backend-neutral sync/reference-line calculations using geometry only.

---

## FAST Viewer Stabilization History and Qt Boundary Reference

> Added: v2.2.9.3 (2026-04-10).  Updated when guards change.

### Crash History / Evolution

| Stage | Version | Symptom | Root Cause | Fix |
|-------|---------|---------|------------|-----|
| 1 | v2.2.5 | Scroll freezes permanently after progressive grow | `vtkImageReslice.SetInterpolationMode*()` called during scroll — collapsed slice range to 1. See `viewer-pipeline.md` §Scroll Guardrails. | Never call reslice methods during scroll. Fixed in v2.2.6. |
| 2 (Steps 0–3) | early v2.2.8.x | Qt crash during active download — `_flush_progressive_grow` unguarded | `QTimer.timeout` fired `_flush_progressive_grow` → `_grow_progressive_fast` → unguarded `_update_vtk_slice_range` / `exit_progressive_mode` calls threw → exception escaped Qt dispatch. | Outer guard on entire `_flush_progressive_grow` body; guards on `update_available_slice_count` and `exit_progressive_mode` calls. 22 tests. |
| 3 (Steps A–D) | v2.2.9.2 | Qt crash from signal slots | `on_series_images_progress`, `on_series_download_fully_complete`, and `_completion_sweep_tick` had no outer try/except around their Qt signal/timer dispatch bodies. | Outer guard + `_impl` split for all three. `_progressive_grow_timer.stop()` on cleanup. 28 tests. |
| 4 (Steps E–F) | v2.2.9.3 | Late-phase crash ~3s after download completion, under 83–94% CPU | `_on_lazy_slice_ready` outer scope (metrics updates, `int()` type conversions, drop path, final `_log_lazy_metrics_if_due()`) unguarded. Only the render step (lines ~400–455) had a try/except — the drop path above it did not. `_completion_verify_series` outer function also unguarded (called via `QTimer.singleShot`). | Outer guard + `_impl` split on both. 33 tests. |
| 5 (Step G) | v2.2.9.4 | Potential crash on large CT decode failure: `_on_lazy_decode_failed` had no outer guard despite being the second Qt signal slot connected to `PyDicomLazyVolume.decode_failed`. Any exception in `_update_backend_badge`, `_release_bound_lazy_loader`, or `_schedule_force_vtk_reload` would escape Qt dispatch. Also: bare `lambda: release_loader(_key)` in `_release_bound_lazy_loader` was unguarded (low-risk but inconsistent). | Outer guard + `_on_lazy_decode_failed_impl` split (`_vw_backend.py`). Named `_deferred_release` closure wrapping `release_loader`. 3 new tests (36 total). |

### Qt Boundary Map

All Qt dispatch boundaries in the FAST viewer path.  An **unguarded** boundary is a potential crash site if any exception escapes.

| Boundary type | File | Function | Status |
|---------------|------|----------|--------|
| `QTimer.timeout` signal | `_vc_progressive.py` | `_flush_progressive_grow` | ✅ Guarded (Stage 2, Step 0) |
| Qt signal slot (`seriesProgressUpdated`) | `_vc_progressive.py` | `on_series_images_progress` | ✅ Guarded (Stage 3, Step A) |
| Qt signal slot (`seriesDownloadCompleted`) | `_vc_progressive.py` | `on_series_download_fully_complete` | ✅ Guarded (Stage 3, Step B) |
| `QTimer.singleShot` callback | `_vc_progressive.py` | `_completion_sweep_tick` | ✅ Guarded (Stage 3, Step C) |
| `QTimer.singleShot` callback | `_vc_progressive.py` | `_completion_verify_series` | ✅ Guarded (Stage 4, Step F) |
| Qt signal slot (`slice_ready` from loader) | `_vw_backend.py` | `_on_lazy_slice_ready` | ✅ Guarded (Stage 4, Step E) |
| Qt signal slot (`decode_failed` from loader) | `_vw_backend.py` | `_on_lazy_decode_failed` | ✅ Guarded (Stage 5, Step G) |
| `QTimer.singleShot` (150ms stale-guard restart) | `_vc_progressive.py` | `_grow_progressive_fast` (timer reschedule) | ✅ Protected by outer `_flush_progressive_grow` guard |
| `QTimer.singleShot` (0ms completion) | `_vc_progressive.py` | `on_series_download_fully_complete` (layer callbacks) | ✅ Protected by outer `on_series_download_fully_complete` guard |

### Current Guard Coverage

Timeline of outer guards added, in order:

**Stage 2 (Steps 0–3):**
- `_flush_progressive_grow` → outer try/except wrapping entire body (`_vc_progressive.py`)
- `_update_vtk_slice_range` → guard on `update_available_slice_count` call (`_vc_cache.py`)
- `exit_progressive_mode()` bare calls in stale-exhausted and completion branches (`_vc_progressive.py`)

**Stage 3 (Steps A–D):**
- `on_series_images_progress` → split into outer guard + `_on_series_images_progress_impl` (`_vc_progressive.py`)
- `on_series_download_fully_complete` → split into outer guard + `_on_series_download_fully_complete_impl` (`_vc_progressive.py`)
- `_completion_sweep_tick` → split into outer guard + `_completion_sweep_tick_impl` (`_vc_progressive.py`)
- `_progressive_grow_timer.stop()` added to `clear_all_caches_for_close` and `exit_patient_widget`

**Stage 4 (Steps E–F):**
- `_on_lazy_slice_ready` → split into outer guard + `_on_lazy_slice_ready_impl` (`_vw_backend.py`)
  - Outer guard logs 10 context fields: viewer id, slice_index, decode_ms, cache_hit, current_slice (inner try), requested_slice, requested_gen, series_gen, backend, loader presence
  - This guard is also the **primary traceback-capture mechanism** for late-phase lazy callback crashes
- `_completion_verify_series` → split into outer guard + `_completion_verify_series_impl` (`_vc_progressive.py`)

**Stage 5 (Step G):**
- `_on_lazy_decode_failed` → split into outer guard + `_on_lazy_decode_failed_impl` (`_vw_backend.py`)
  - Outer guard logs 4 context fields: viewer id, reason, backend, loader presence
  - Missed in Stage 4 sweep — added in v2.2.9.4
- `release_loader` deferred call: bare `lambda: release_loader(_key)` replaced with named `_deferred_release` closure containing try/except

### FAST Viewer Late-Phase Lifecycle

The sequence after download completes for a series being actively viewed in FAST mode:

```
DM subprocess: last batch written to disk
    │
    ▼
home_download_service.on_series_completed
    │   emits series_images_progress(sn, total, total)  [Layer 2a pulse]
    ▼
ViewerController.on_series_images_progress  [GUARDED — Step A]
    │   downloaded >= total → _on_series_download_fully_complete
    ▼
ViewerController.on_series_download_fully_complete  [GUARDED — Step B]
    │   final loader.grow() + slider update on ALL viewers showing series
    │   exit_progressive_mode() on each viewer
    │   _progressive_series.pop(sn)
    │   schedules QTimer.singleShot(500, _completion_verify_series)  [Layer 3]
    │   registers sn into _completion_sweep_series_set  [Layer 4]
    ▼
ZetaBoost.invalidate_series(sn)  ← fires ~0ms post-completion
    │   promotes lazy volume to ZetaBoost L1 cache
    │   starts booster prefetch burst for slices 0..N-1
    │   CPU load: 83–94% typical during burst (heavy decode activity)
    ▼
PyDicomLazyVolume.slice_ready signal (per decoded slice, many rapid-fire)
    │   connected to VTKWidget._on_lazy_slice_ready  [GUARDED — Step E]
    │   under high CPU, any exception in type conversions / metrics / drop path
    │   is now captured instead of aborting the process
    ▼
QTimer fires at +500ms: _completion_verify_series  [GUARDED — Step F]
    │   disk count vs viewer count check; catch-up grow if needed
    │   up to 3 retries at 500ms intervals
    ▼
_completion_sweep_timer fires at 3s intervals  [GUARDED — Step C]
    │   final safety net; polls until viewer count matches disk
    ▼
STABLE — all slices visible, progressive mode exited, ZetaBoost caching active
```

**Critical timing note:** ZetaBoost fires immediately at completion (`invalidate_series` → booster starts). This saturates CPU with decode work at the exact moment the `_on_lazy_slice_ready` signal fires repeatedly. This is why late-phase crashes occurred under high CPU but not during early progressive grow (fewer concurrent callbacks).

### Regression Protection

The following behaviors must not break when modifying FAST viewer code:

| Behavior | Mechanism | What must not be broken |
|----------|-----------|------------------------|
| Scroll during download | `_flush_progressive_grow` → `_grow_progressive_fast` → `loader.grow()` | Exceptions in grow must not reset slider max or current_slice |
| Scroll after download | `_on_lazy_slice_ready` render path → `_call_image_viewer_set_slice` | Outer guard must not swallow normal render; `_on_lazy_slice_ready_impl` must execute on happy path |
| Progressive grow | `_progressive_grow_timer` (150ms) → `_flush_progressive_grow_impl` → `_grow_progressive_fast` | Info dict `pending_downloaded` preserved after exception so timer retries |
| pydicom_2d direct VTK wiring | `SetInputData(raw_lazy_vtk)` in `ImageViewer2D.__init__` and `reset_image_viewer` | Never wire through `image_reslice.GetOutput()` for pydicom_2d — causes frozen image. See Rule 11 in `IMAGE_PIPELINE_REFERENCE.md`. |
| ZetaBoost promote on completion | `on_series_download_fully_complete` → `zeta_boost.invalidate_series` | Must fire AFTER exit_progressive_mode; outer guard must not suppress this call |
| High-slice CT stability (99+ slices) | All of the above together under ZetaBoost burst | Test scenario B2: scroll aggressively immediately after 99-slice CT download completes |

### Investigation Notes — Stage 4 Hypothesis

#### Why `_on_lazy_slice_ready` is the prime suspect

Three converging indicators (not a confirmed traceback — this is the hypothesis that drove Stage 4):

1. **Last pre-crash log line**: `viewer-lazy frame_delivery action=render viewer=1 slice=87`. This line is emitted near the END of `_on_lazy_slice_ready_impl`, inside the render try/except. The Qt crash message followed immediately with no other log lines. This places the exception either (a) after the render try/except (in the final `_log_lazy_metrics_if_due()` call at line 457, which is unguarded) or (b) in a concurrent signal delivery where the outer scope metrics code throws.

2. **Code inspection**: The outer scope of `_on_lazy_slice_ready` (before the render try/except and in the drop path) contains multiple unguarded type conversions:
   - `self._lazy_metrics["decode_ms_total"] += decode_ms_f` — `KeyError` if `_lazy_metrics` cleared by `_release_bound_lazy_loader()` racing signal delivery
   - `int(self._lazy_requested_generation)` in `should_render_ready_slice()` args — `TypeError` if attribute is `None` during series switch race
   - `int(self._series_generation_id)` same — same risk
   - `self._lazy_drop_log_counter = int(self._lazy_drop_log_counter or 0) + 1` in drop path — `TypeError` if `_lazy_drop_log_counter` is in unexpected state
   - `self._log_lazy_metrics_if_due()` after the render try/except — `RuntimeError` if internal state torn down

3. **CPU/timing context**: ZetaBoost fires a prefetch burst for slices 0–98 immediately at completion. This saturates CPU at 83–94% and generates 99 rapid-fire `slice_ready` signals. Under this load, any attribute access on partially-modified state (series switch cleanup racing decode delivery) is more likely to throw than during normal single-signal delivery.

#### Why `_completion_verify_series` is a secondary candidate

The inner paths in `_completion_verify_series_impl` are mostly guarded individually (e.g., grow failure is caught at `logger.debug` level). However, `vtk_w.get_count_of_slices()` and the retry `QTimer.singleShot(...)` call are outside any inner try/except. A `RuntimeError` from `get_count_of_slices()` (e.g., C++ object partially deleted at tab teardown) would propagate. Less likely than `_on_lazy_slice_ready` because it fires only once at +500ms, not 99 times under burst load.

#### Why download/network is not the primary crash source

- Download subprocess runs in a separate process (separate GIL and signal space)
- ZetaBoost completed safely at `INVALIDATE → PROMOTE` before the crash (confirmed in Log 3 at 16:30:40.182)
- All DM→viewer signal slots (`on_series_images_progress`, `on_series_download_fully_complete`) were already guarded in Stage 3 (Steps A–B) and confirmed working in Log 3 (`_on_series_download_fully_complete_impl` logged, `EXIT series=203 available=99` logged)
- The crash occurred 3 seconds after the DM completed — during post-completion viewer interaction, not during the download itself
