# FAST Mammography Regression Playbook (May 19, 2026)

Purpose
- Provide a single recovery guide for FAST mammography display regressions.
- Capture what was fixed, why it broke, and how to validate quickly.

Scope
- FAST path only (pydicom_qt): QtSliceViewer + QtViewerBridge + Lightweight2DPipeline.
- Advanced VTK behavior is used as visual reference but is not modified by this playbook.

## User-visible failures this playbook addresses

1. FAST series switch/import appears broken or blank due to viewer startup error.
2. Mammography appears white or washed out on some series while others look correct.
3. Window width and center look locked at 32768/32768 with inconsistent visual outcomes.
4. Negative display behavior unexpectedly changes across sessions.

## Root causes found and fixed

### A. FAST startup/switch path blocked by Qt viewer syntax failure
- Symptom: FAST drag/drop or series switch fails before first render.
- Fix: Remove malformed code block in Qt slice paint path.
- File:
  - modules/viewer/fast/qt_slice_viewer.py

### B. MONOCHROME1 inversion depended on scene extrema
- Symptom: Some MG series looked correct while others were washed out even with same tag WW/WL.
- Root issue: Inversion based on per-image extrema can shift contrast when tissue occupancy differs by series.
- Fix: Use storage-domain inversion bounds (BitsStored + PixelRepresentation + slope/intercept) to make inversion stable across MG series.
- File:
  - modules/viewer/fast/lightweight_2d_pipeline.py

### C. MG WW/WL source handling around 32768/32768
- Symptom: WW/WL displayed as 32768/32768 but output differed by series.
- Fix direction: Preserve DICOM-tag source values where intended and avoid accidental fallback churn.
- Files:
  - modules/viewer/fast/lightweight_2d_pipeline.py
  - PacsClient/pacs/patient_tab/utils/dicom_windowing.py

### D. Negative mode requirement for FAST filter chain
- User request: Keep negative display active.
- Implemented by config: Pooyan filter invert is enabled in shipped config.
- File:
  - config/pooyan_opencv_filter.json (invert = true)

### E. Zoomed-out radiography interpolation + subtle manual W/L drag
- User request: improve zoomed-out visual quality and avoid aggressive W/L jumps.
- Implemented in FAST Qt viewer interaction path only (default W/L resolution unchanged).
- Changes:
  - Enable smooth pixmap transform for zoomed-out radiography modalities (MG/DX/CR/XR).
  - Reduce manual W/L drag sensitivity for MG/DX/CR/XR to keep changes gradual.
- File:
  - modules/viewer/fast/qt_slice_viewer.py

## Load-bearing invariants (do not regress)

1. FAST and ADVANCED remain separated by render owner.
- FAST (pydicom_qt) renders in Qt path.
- Advanced (vtk_simpleitk) renders in VTK path.

2. MONOCHROME1 inversion must stay storage-domain based in FAST MG path.
- Do not switch back to per-image min/max inversion.

3. FAST MG filter path must keep preserve_dimensions true.
- Prevents dimension/stride mismatch artifacts and wrapped images.

4. FAST negative display setting is config-driven and must flow into pipeline config.
- config/pooyan_opencv_filter.json invert value must be honored.

5. Canonical and plugin payload copies must stay aligned for viewer FAST files used in release packaging.

6. Manual W/L interaction for MG/DX/CR/XR must remain subtle.
- Do not restore aggressive drag multipliers for radiography modalities.

7. Zoomed-out radiography rendering must keep smooth downscale enabled.
- Applies when modality is MG/DX/CR/XR and zoom < 1.0.

## Regression diagnostics (what to inspect first)

Check viewer log for these tags around a failing switch:
- [MG_WL_RESOLVE]
- [MG_DIAG]
- [MG_DIAG_FILTER]
- FAST:first_renderable_frame

Interpretation hints:
- If [MG_WL_RESOLVE] shows source drift (unexpected src), inspect WW/WL resolution path.
- If [MG_DIAG] arr_mean/disp_mean are inconsistent with expected contrast for one series only, verify inversion branch.
- If [MG_DIAG_FILTER] changes are tiny but image still white, issue is before filter (decode/window/inversion), not filter tuning.

## Fast recovery checklist

1. Confirm runtime backend route is FAST pydicom_qt for the failing viewer event.
2. Reproduce on a known pair (one good, one bad series in same study if possible).
3. Inspect [MG_WL_RESOLVE] and [MG_DIAG] lines for both series.
4. Verify pooyan invert setting loaded from config (invert should be true if negative mode is required).
5. Verify no syntax/runtime errors in FAST Qt viewer startup path.
6. Verify canonical/plugin parity for FAST files before packaging.

## Validation commands used in this area

Run focused filter regression suite:
- .venv\Scripts\python.exe tests/viewer/test_pooyan_opencv_filter.py

Expected:
- Config Loader Negative Mode passes.
- Inversion Parity passes.

Optional compile sanity:
- .venv\Scripts\python.exe -m py_compile modules/viewer/fast/lightweight_2d_pipeline.py
- .venv\Scripts\python.exe -m py_compile modules/viewer/fast/qt_viewer_bridge.py
- .venv\Scripts\python.exe -m py_compile modules/viewer/fast/qt_slice_viewer.py

Focused interaction safeguards:
- .venv\Scripts\python.exe -m pytest tests/viewer/test_qt_slice_viewer_stack_drag.py -k "radiography or downscale_smoothing" -q

## Files most likely to fix if regression returns

Primary:
- modules/viewer/fast/lightweight_2d_pipeline.py
- modules/viewer/fast/qt_viewer_bridge.py
- modules/viewer/fast/qt_slice_viewer.py
- PacsClient/pacs/patient_tab/utils/dicom_windowing.py
- config/pooyan_opencv_filter.json

Packaging mirror when required:
- builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/lightweight_2d_pipeline.py
- builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/qt_viewer_bridge.py
- builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/qt_slice_viewer.py

## Known good intent snapshot (May 19, 2026)

- FAST mammography renders correctly after restart with the patched FAST path.
- Negative mode is active through Pooyan config invert.
- Focused Pooyan regression suite passes completely.

If a future change breaks MG again, start with this document, collect the log tags above, and compare behavior series-by-series (not only by DICOM tags) because occupancy distribution can expose inversion/windowing instability.
