# Stitching Module

**Landmark-based 2D radiograph stitching** for compositing long-bone survey
radiographs (Pelvis → Femur → Knee → Tibia …) into a single image for
limb-length and alignment measurement.

## Architecture

```
stitching/
├── __init__.py                  Public API exports
├── landmark_store.py            Physical-coord landmark pair-set manager (QObject + Signal)
├── stitch_engine.py             SimpleITK registration (Rigid / Similarity / Affine) + residuals
├── blend_engine.py              Histogram-match + multi-band (Laplacian) blend; float32
├── stitch_worker.py             QThread background worker for the full N-series pipeline
├── stitching_widget.py          Main PySide6 + VTK window (sidebar + two viewers)
├── landmark_interactor_style.py VTK interactor for click-to-place landmarks
└── README.md                    ← you are here
```

## Workflow (multi-series chain)

1. User opens **Advanced Analysis → Stitching** in the patient tab.
2. The available series are listed; the user **checks ≥ 2 series** and clicks
   **Load Selected Series** (sorted by series number into a chain).
3. For each adjacent pair (Series k ↔ Series k+1), the user picks the **Active
   Pair**, toggles **Place Landmark Pair**, and alternately clicks corresponding
   anatomical points on the left and right images (A/A', B/B', …).
   **≥ 4 complete pairs per boundary** are required before Compute enables.
4. **Compute Stitching** runs the pipeline on a background `QThread`:
   per-pair `LandmarkBasedTransformInitializerFilter` → per-landmark residuals →
   (pause for confirmation if any residual > 4 mm) → chain-composed transforms →
   union canvas at finest spacing → resample each series → histogram-match +
   multi-band blend.
5. **Preview Result** displays the stitched composite in the right viewer.
6. **Export as DICOM** saves a Secondary Capture (`AI-Stitch-<timestamp>.dcm`)
   with spatial metadata (PixelSpacing / ImagePositionPatient / orientation).
7. **Use Result for Next Stitch** adds the result back to the series list (kept
   in memory at full precision) for multi-stage stitching: A+B → R₁, R₁+C → R₂…

## Key Design Decisions

* **Physical coordinates only** — landmarks are stored and processed in mm
  (DICOM physical space), never in pixel or screen coordinates.
* **SimpleITK** — `LandmarkBasedTransformInitializerFilter` for the transforms,
  `SignedMaurerDistanceMap` for blend weight ramps, recursive Gaussian for the
  pyramid.
* **Multi-band (Laplacian-pyramid) blend** after overlap histogram matching —
  removes seam/ghosting artefacts; runs in **float32** for memory and speed.
* **Accuracy gate** — the worker pauses and reports per-landmark residuals; the
  UI offers Re-adjust / Add more pairs / Continue anyway when any exceed 4 mm
  (the limb-length measurement tolerance).
* **Singleton window** — `get_stitching_widget()` returns a shared instance.
* **QThread worker** — heavy compute is off the GUI thread; progress and the
  residual report are relayed via Qt signals.

## Tests

`tests/code/stitching/` — headless engine + blend coverage (run with
`QT_QPA_PLATFORM=offscreen`, `-p no:debugging`). Golden blend statistics guard
the float32 pipeline; extend these before any change to the blend math (e.g. the
planned Phase 2 pyramid decimation). See
`docs/reports/STITCHING_MODULE_REVIEW_2026-06-08.md` for the optimization plan.

## Dependencies

| Package    | Version |
|------------|---------|
| SimpleITK  | 2.5.3   |
| VTK        | latest  |
| PySide6    | 6.10.2  |
| pydicom    | ≥ 2.4.0 |
| numpy      | latest  |
