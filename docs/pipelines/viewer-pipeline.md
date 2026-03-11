# Viewer Pipeline

> **Version:** v2.2.3.4.0 | **Updated:** 2026-03-10

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
| `tools/_base_vtk.py` | VTK widget base, scroll handling, GC management |
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
