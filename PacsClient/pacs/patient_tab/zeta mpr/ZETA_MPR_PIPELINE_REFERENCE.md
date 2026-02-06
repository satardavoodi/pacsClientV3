# Z‑MPR (Zeta MPR) – Pipeline & Tools Reference

**Location**: `PacsClient/pacs/patient_tab/zeta mpr/`
**Scope**: Standard MPR (orthogonal), cross‑lines, tools/measurements, and input orientation handling
**Generated**: 2026‑02‑05

---

## 1) High‑level architecture (where Z‑MPR lives)

**Entry path (runtime)**
1. User opens study in main app.
2. Toolbar action toggles Z‑MPR:
   - `toolbar_integration.py::toggle_new_mpr_zeta()`
   - `toolbar_integration.py::replace_selected_viewport_with_new_mpr_zeta()`
3. Z‑MPR viewer instantiated:
   - `standard_mpr_viewer.py::StandardMPRViewer`

**Key files**
- `standard_mpr_viewer.py` – main MPR UI + crosshair interaction + reslice mapping
- `mpr_measurement_tools.py` – distance/angle/caption widgets
- `curved_mpr.py` – true curved MPR (path → frames → reslice)
- `advanced_rendering.py` – MIP/MinIP/Thick‑Slab utilities
- `segmentation_tools.py` – lung/airway/vessel/bone segmentation helpers
- `surface_reconstruction.py` – marching cubes / surface tools
- `preset_manager.py` – 3D volume presets (depends on `vtk_3d_presets`)

---

## 2) End‑to‑end input pipeline (from data → MPR views)

### 2.1 Data handoff into Z‑MPR
- `toolbar_integration.py` searches `patient_widget.lst_thumbnails_data` for the selected series.
- It extracts:
  - `vtk_image_data`
  - `series_path` (dicom directory)
  - optional window/level from instance metadata
- It replaces the selected viewport widget with `StandardMPRViewer`.

**Code references**
- `toolbar_integration.py::toggle_new_mpr_zeta()`
- `toolbar_integration.py::replace_selected_viewport_with_new_mpr_zeta()`

### 2.2 Z‑MPR viewer initialization
`standard_mpr_viewer.py::StandardMPRViewer.__init__()`
1. **Input flip (left‑right)**
   - Uses `vtkImageFlip` on axis 0 (X).
   - This is the foundational correction used across all views.
2. **Direction matrix extraction**
   - Reads field data array: `DirectionMatrix` (4x4) if present.
   - Adjusts the matrix for the X‑flip (negates first column).
3. **Core view creation**
   - Axial, Sagittal, Coronal via `vtkImageResliceMapper`.
   - 3D volume view via `vtkGPUVolumeRayCastMapper`.
4. **Crosshair setup + interactor**
   - Crosshair lines + handles + custom interactor style per view.
5. **Slice synchronization**
   - Wheel events update camera focal points and crosshair positions.

---

## 3) Cross‑lines (crosshair) system – current behavior

### 3.1 Crosshair data model
- `self.current_position`: current world center (x, y, z)
- `self.crosshair_angles`: per‑view rotation angle (radians)
- `self.crosshair_actors`: VTK actors for lines + handles per view

### 3.2 How cross‑lines drive planes
- Crosshair position updates call:
  - `_update_all_crosshairs()` → line endpoints updated
  - `_update_slice_positions()` → camera focal points updated
- This synchronizes axial/sagittal/coronal planes to the crosshair center.

### 3.3 Rotation: **visual only**
- Oblique reslicing is currently **disabled**.
- `_update_oblique_reslicing()` returns early and calls `_reset_all_to_orthogonal()`.
- **Result**: line rotation does **not** create true oblique slices.

### 3.4 Interaction rules (mouse)
Implemented in the custom VTK interactor style inside `_add_click_handler()`:
- **Rotation zones**: last 10% of line ends, 20px threshold
- **Handles**: 15px squares at endpoints
- **Center**: 20px radius (move crosshair center)
- **Line drag**: drag from any line point (with offset)
- **Wheel**: scroll slices (direction from `_get_scroll_direction()`)

### 3.5 Improving cross‑lines / cross‑plane logic
If true oblique reslicing is re‑enabled, revisit:
- `_update_oblique_reslicing()` and `_apply_oblique_transform()`
- Interaction feedback vs. actual reslice axis
- Coordinate space consistency after pre‑orientation transform (see section 7)

---

## 4) Measurements & tool system

### 4.1 What tools exist
Defined in `mpr_measurement_tools.py`:
- **Ruler** → `vtkDistanceWidget` + `vtkDistanceRepresentation2D`
- **Angle** → `vtkAngleWidget` + `vtkAngleRepresentation2D`
- **Caption** → `vtkCaptionWidget` + `vtkCaptionRepresentation`

### 4.2 Activation flow
- `activate_ruler_tool()` / `activate_angle_tool()` / `activate_caption_tool()`
- Creates widget, assigns interactor, calls `.CreateDefaultRepresentation()`
- Calls `.On()` and `.SetProcessEvents(1)` so widget is interactive

### 4.3 Current limitations
- `deactivate_tool()` only clears `current_tool` and does **not** disable widgets.
- Use `clear_measurements()` to actually turn widgets off.
- Debug prints exist in `_activate_ruler_on_view()`.

### 4.4 Input mappings (keyboard/mouse)
- **No keyboard shortcuts** defined in Z‑MPR files.
- Mouse behavior is defined by VTK widgets and the custom crosshair interactor.
- 3D view uses `vtkInteractorStyleTrackballCamera` (default mouse rotate/zoom/pan).

---

## 5) Curved MPR pipeline (true CPR)

**Core flow** in `curved_mpr.py`:
1. **Path3D** – Catmull‑Rom spline from control points
2. **PlaneGenerator** – parallel transport frames along the path
3. **ResliceEngine** – reslice volume perpendicular to path tangent
4. **Output** – straightened volume or panoramic projection

**Important details**
- Uses parallel transport frame to avoid twist/flipping.
- Panoramic uses a 2‑step method (build straightened volume → projection).
- Spacing is computed from actual path length (important for measurements).

---

## 6) 3D rendering + segmentation tools (support modules)

### 6.1 Volume rendering
- `advanced_rendering.py`: MIP / MinIP / Thick‑Slab utilities
- `StandardMPRViewer._apply_mip/_apply_minip/_apply_thick_slab()` wrappers

### 6.2 Segmentation
- `segmentation_tools.py`: Lung/Airway/Vessel/Bone helpers
- Results are stored in `StandardMPRViewer.segmentation_results`
- Some 3D overlay logic exists, but actor tracking is minimal

### 6.3 Surface reconstruction
- `surface_reconstruction.py`: marching cubes / smoothing / decimation

---

## 7) Oblique/Non‑canonical input handling (pre‑pipeline filter)

### 7.1 Problem statement
Some datasets have **oblique DICOM orientation**. When they enter the current pipeline:
- Output slices are not radiological‑canonical.
- Crosshair and camera assumptions become incorrect.

### 7.2 Current orientation logic (in Z‑MPR)
- `StandardMPRViewer` reads a `DirectionMatrix` from VTK field data.
- It also applies an **X‑axis flip** to enforce radiological left‑right.
- Camera vectors are derived by `_get_camera_vectors_for_view()`.

### 7.3 Recommended solution: pre‑canonicalize input volume
Do **not** modify the internal MPR pipeline first. Instead, insert a pre‑filter:

**Goal**: transform the volume into a standard, axis‑aligned 3D volume so that
Z‑MPR receives data that behaves like routine scans.

**Suggested approach**
1. Compute orientation from DICOM (ImageOrientationPatient / ImagePositionPatient).
2. Build a transform matrix to map source orientation → canonical patient axes.
3. Resample the source volume with `vtkImageReslice` into a new axis‑aligned volume.
4. Preserve origin/spacing correctly.
5. Pass this canonical volume to `StandardMPRViewer`.

### 7.4 Best insertion points
**Option A (preferred)** – **before** `StandardMPRViewer` is created:
- `toolbar_integration.py::replace_selected_viewport_with_new_mpr_zeta()`
  - Add a `canonicalize_volume(vtk_image_data)` call before constructing the viewer.

**Option B** – inside `StandardMPRViewer.__init__()`:
- Replace the current `vtkImageFlip` step with a canonicalization step that:
  - resamples to standard orientation
  - then applies the existing X‑flip if still needed

**Option C** – at the upstream series builder:
- Wherever `vtk_image_data` is constructed for thumbnails.
- Most global but requires broader code audit.

---

## 8) Suggested documentation targets for future changes

### Cross‑lines / cross‑planes
- Re‑enable oblique reslice in `_update_oblique_reslicing()`
- Define correct axis + rotation for each plane after pre‑canonicalization
- Ensure camera vectors remain consistent with canonical axes

### Measurements
- Decide tool lifecycle: single tool vs. multi‑tool
- Decide deactivation behavior (disable widgets vs. keep visible)
- Add consistent tool state UI in toolbar (if desired)

### Input pipeline
- Add a documented `canonicalize_volume()` helper
- Store original orientation matrix for traceability
- Update metadata so downstream modules can know the original orientation

---

## 9) Quick index (where things live)

**Crosshair logic**
- `StandardMPRViewer._add_click_handler()`
- `StandardMPRViewer._update_all_crosshairs()`
- `StandardMPRViewer._update_slice_positions()`
- `StandardMPRViewer._update_oblique_reslicing()` (currently disabled)

**Measurements**
- `MPRMeasurementTools.activate_ruler_tool()`
- `MPRMeasurementTools.activate_angle_tool()`
- `MPRMeasurementTools.activate_caption_tool()`
- `MPRMeasurementTools.clear_measurements()`

**Curved MPR**
- `CurvedMPRGenerator.set_centerline()`
- `CurvedMPRGenerator.generate_curved_mpr()`
- `ResliceEngine.reslice_along_path()`

---

## 10) Open questions for follow‑up
- Where is `vtk_image_data` produced upstream (thumbnail builder or loader)?
- Is `DirectionMatrix` always present in field data? If not, how is it constructed?
- Should the canonicalization filter preserve a separate “original orientation” matrix?

---

## 11) Summary (current state)
- Z‑MPR uses **orthogonal** reslicing only.
- Crosshair rotation is **visual** only (no oblique slicing).
- Measurements are widget‑based and interactive; deactivation is incomplete.
- Oblique input requires a **pre‑pipeline canonicalization** layer.

This document is the baseline reference for improvements and architectural changes.
