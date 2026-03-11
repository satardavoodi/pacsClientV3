# Stitching Module

**Landmark-based 2D radiograph stitching** for compositing long-bone survey
radiographs (Pelvis → Femur → Knee → Tibia …).

## Architecture

```
stitching/
├── __init__.py                  Public API exports
├── landmark_store.py            Physical-coord landmark pair manager (QObject + Signal)
├── stitch_engine.py             SimpleITK registration (Rigid / Similarity / Affine)
├── canvas_builder.py            Union bounding-box + image paste onto shared canvas
├── blend_engine.py              Feather / alpha blending for the overlap seam
├── stitch_worker.py             QThread background worker for the full pipeline
├── stitch_controller.py         Orchestrator / state-machine for pick mode
├── stitching_widget.py          Main PySide6 + VTK window (3-column layout)
├── landmark_interactor_style.py VTK interactor for click-to-place landmarks
└── README.md                    ← you are here
```

## Workflow

1. User opens **Advanced Analysis → Stitching** in the patient tab.
2. The fixed (reference) series is loaded automatically from the active viewer.
3. User clicks **Load Moving Series** to select the second radiograph folder.
4. User toggles **Place Landmark Pair** and alternately clicks corresponding
   anatomical points on the fixed and moving images (≥ 2 pairs for rigid /
   similarity, ≥ 3 for affine).
5. **Compute Alignment** runs the SimpleITK `LandmarkBasedTransformInitializerFilter`
   pipeline on a background thread with progress feedback.
6. **Preview Stitch** displays the feather-blended composite in the right viewer.
7. **Export as DICOM** saves the result as a DICOM Secondary Capture
   (`AI-Stitch-<timestamp>.dcm`).

## Key Design Decisions

* **Physical coordinates only** — landmarks are stored and processed in mm
  (DICOM physical space), never in pixel or screen coordinates.
* **SimpleITK** (not native ITK) — already a project dependency (`SimpleITK==2.5.3`).
* **Feather blending** — `SignedMaurerDistanceMap` distance ramp for seamless overlap.
* **Singleton window** — `get_stitching_widget()` returns a shared instance,
  matching the `get_slicer_launcher()` pattern used by the Advanced MPR module.
* **QThread worker** — heavy compute is off the GUI thread; progress is relayed
  via Qt signals.

## Dependencies

All already present in `requirements.txt`:

| Package    | Version |
|------------|---------|
| SimpleITK  | 2.5.3   |
| VTK        | latest  |
| PySide6    | 6.10.2  |
| pydicom    | ≥ 2.4.0 |
| numpy      | latest  |
