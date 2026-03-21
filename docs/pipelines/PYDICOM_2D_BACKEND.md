# PyDicom 2D Backend (Phase 1)

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
  - `python -m pytest tests/test_pydicom_backend_geometry.py`
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
