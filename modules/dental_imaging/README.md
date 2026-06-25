# Dental Imaging module

Professional dental CBCT workspace, opened from the Patient Viewer's **Advanced
Analysis** area (beside *Advanced MPR* and *Stitching*). This is the **advanced**
level of a deliberate **two-level** dental architecture.

> Status: **Milestone 1 — foundation.** The skeleton pop-up plus the active
> series's **shared volume is bound** — the module reuses the active viewer's
> already-built `vtk_image_data` (single source of truth) and shows its geometry
> (dims / spacing / origin / direction). No volume is rebuilt and no geometry is
> recomputed. The 4-view VTK render + synchronized cursor is the next step and
> needs the live Windows source build to validate.

## Two levels — do not mix them

| Level | Where | Scope |
|---|---|---|
| **Simple viewer** | Patient-Tab **Dental Curve MPR** (MPR dropdown), `modules/mpr/zeta_mpr/curved_mpr.py` + `modules/mpr/curved_mpr/` | Lightweight: simple panoramic-style view + simple ruler. **Stays simple.** |
| **Professional** | **this module** (`modules/dental_imaging/`) | Full dedicated workspace: panoramic / curved MPR / cross-sections / arch-curve editing / nerve tracing / measurements / segmentation / AI / case planning. |

The simple viewer and this module **share lower-level infrastructure** but have
**different UI/workflow layers**. This package must **never** be imported into the
simple Dental Curve MPR viewer, and must not bloat it.

## Shared core — reuse, never duplicate

This module must reuse the existing safe infrastructure and must **not** fork a
second volume/geometry pipeline (per
`docs/plans/architecture/UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md`):

- **Volume preparation** → `modules/viewer/fast/pydicom_lazy_volume.py::PyDicomLazyVolume`
- **Geometry contract** (LPS triad, IPP/IOP) → standard (Zeta) MPR foundation
- **VTK / MPR reslice pipeline** → standard MPR
- **Curved reconstruction engine** → `modules/mpr/zeta_mpr/curved_mpr.py`
- **Measurement primitives** → shared measurement utilities

The active series arrives as a pure `DentalSeriesContext` handle (`context.py`,
stdlib only — a DICOM directory + identifiers + window/level, exactly what the
Advanced MPR / Stitching launchers already pass). Later milestones turn
`dicom_dir` into a volume via the shared `PyDicomLazyVolume` + geometry contract.

## Files

| File | Role | Imports |
|---|---|---|
| `context.py` | `DentalSeriesContext` data-source handle | stdlib only |
| `__init__.py` | flag (`dental_imaging_enabled`) + lazy `open_dental_imaging_workspace` | stdlib + context |
| `workspace.py` | `DentalImagingWorkspace` shell window | PySide6 (lazy) |
| `launcher.py` | singleton `open/get_dental_imaging_workspace` | PySide6 (lazy) |
| `core/volume.py` | `DentalVolume` — read-only geometry over the shared volume | stdlib only |
| `core/volume_binder.py` | `bind_active_viewer_volume` — reuse the active viewer's volume | stdlib only |

Import-light: importing the package pulls only stdlib + the pure context. Qt is
imported only when the workspace is actually opened.

## Feature flag

`AIPACS_DENTAL_IMAGING` — default **on**. Set to `0` to hide the Advanced-Analysis
entry and disable the launcher. Purely additive: disabling leaves every existing
flow byte-identical.

## Entry point

`PacsClient/.../patient_widget_core/_pw_advanced.py` adds a flag-gated **Dental
Imaging** button to the Advanced Models section; its handler
`_on_dental_imaging_clicked` resolves the active series (same way Advanced MPR /
Stitching do) into a `DentalSeriesContext` and calls
`modules.dental_imaging.open_dental_imaging_workspace(parent, context)`.

## Roadmap (after the skeleton)

1. ✅ **Bind the shared volume + geometry contract** (`core/`): reuse the active
   viewer's `vtk_image_data` (Milestone 1 foundation, done). A
   `PyDicomLazyVolume.from_series` fallback for a *non-active* series is staged.
2. 4-view synchronized layout (axial / panoramic / cross-section / 3D) on the
   shared MPR cursor bus.
3. Editable arch curve → panoramic reconstruction (reuse curved engine).
4. Perpendicular cross-sections with adjustable spacing/thickness/count.
5. mm-accurate measurements (world coordinates) + annotation management.
6. Manual mandibular-nerve tracing + crest/apex→canal distance.

Each step ships flag-gated with guard tests (voxel-spacing accuracy,
perpendicularity, coordinate consistency, ruler z-order, synced cursor).
