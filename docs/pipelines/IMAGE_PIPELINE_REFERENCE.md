# AIPacs Image Pipeline Reference â€” DICOM â†’ Screen

**Version:** 2.3.3
**Last Updated:** 2026-04-14  
**Scope:** DICOM â†’ SimpleITK â†’ VTK â†’ Viewer/MPR â†’ Screen  
**Changelog:** See [Section 13](#13-test-results--findings-log) for chronological investigation results

> **Purpose**: This document describes every transformation that happens to medical image
> data from DICOM files on disk to pixels on the screen.  It is the definitive reference
> for understanding coordinate systems, axis conventions, flips, direction matrices,
> and the mapping functions that convert between these spaces.
>
> **Audience**: All AIPacs developers â€” especially those working on sync/target,
> MPR, measurements, annotations, or any feature that needs to convert between
> pixel coordinates and physical/patient coordinates.

---

## Table of Contents

1. [Coordinate Systems Overview](#1-coordinate-systems-overview)
2. [Stage 1 â€” DICOM on Disk](#2-stage-1--dicom-on-disk)
3. [Stage 2 â€” SimpleITK Loading](#3-stage-2--simpleitk-loading)
4. [Stage 3 â€” ITK â†’ VTK Conversion (`convert_itk2vtk`)](#4-stage-3--itk--vtk-conversion)
5. [Stage 4 â€” Viewer Preprocessing](#5-stage-4--viewer-preprocessing)
6. [Stage 5 â€” ImageReslice & Display](#6-stage-5--imagereslice--display)
7. [Stage 6 â€” MPR Path (StandardMPRViewer)](#7-stage-6--mpr-path)
8. [Complete Transformation Chain (Summary Table)](#8-complete-transformation-chain)
9. [Coordinate Conversion Functions Reference](#9-coordinate-conversion-functions-reference)
10. [Direction Matrix â€” What It Is, How It Changes](#10-direction-matrix)
11. [Common Pitfalls & Critical Rules](#11-common-pitfalls--critical-rules)
12. [Appendix: Numerical Worked Example](#12-appendix-numerical-worked-example)
13. [Test Results & Findings Log](#13-test-results--findings-log)

---

## 1. Coordinate Systems Overview

There are **five** distinct coordinate spaces in the AIPacs pipeline.  Every bug or
confusion in coordinate mapping comes from conflating two of these.

| # | Space | Axes | Units | Who uses it |
|---|-------|------|-------|-------------|
| **CS-1** | **DICOM Patient Coordinate System (LPS+)** | X = Left, Y = Posterior, Z = Superior | mm | DICOM standard, SimpleITK |
| **CS-2** | **SimpleITK Numpy Array** | axis-0 = Z(slices), axis-1 = Y(rows), axis-2 = X(cols) | voxels | `sitk.GetArrayFromImage()` output |
| **CS-3** | **VTK Image Data (post `convert_itk2vtk`)** | i = X(cols), j = Y(rows, **flipped**), k = Z(slices) | voxels/mm | `vtkImageData` before reslice |
| **CS-4** | **VTK Reslice Output** | Same axes as CS-3, but origin/spacing may change if upsampled | mm | `self.vtk_image_data` after reslice |
| **CS-5** | **VTK Display** | 2D pixel coordinates in the render window | pixels | Mouse events, pickers |

### Key relationships

```
DICOM files â”€â”€â–؛ SimpleITK (CS-1/CS-2) â”€â”€â–؛ convert_itk2vtk â”€â”€â–؛ CS-3 â”€â”€â–؛ reslice â”€â”€â–؛ CS-4 â”€â”€â–؛ display â”€â”€â–؛ CS-5
                                              â”‚
                                              â–¼
                                        Y-flip + direction
                                        matrix compensation

---

### 2026-02-15 Update â€” ZetaBoost multi-lane preload + L2 persistent cache

To improve high-volume studies (e.g., 1000â€“3000 instances/series), the preload system now uses:

- **Multi-lane queueing** in `PacsClient/pacs/patient_tab/zeta_boost/engine.py`:
  - `interactive` (highest priority)
  - `warmup`
  - `background` (lowest)
- **Read-through/write-through L2 cache** in
  `PacsClient/pacs/patient_tab/zeta_boost/disk_cache.py`:
  - compressed volume payload on disk (`.npz`)
  - SQLite manifest (`manifest.db`) for LRU access tracking/pruning

Important behavior notes:

- In-memory cache remains the first hit path (L1).
- On L1 miss, engine attempts L2 disk cache before re-reading DICOM.
- `clear_all_caches_for_close()` still performs hard close cleanup through `ZetaBoost.clear_all()`.
- Deactivation can release active work while preserving modular queue/caching behavior for repeatability during active study workflows.

Additional implementation details (2026-02-15):

- L2 payload roundtrip now preserves spatial field-data required by sync/orientation logic:
  - `DirectionMatrix`
  - `ITKOrigin`
  - `ITKSpacing`
  - `ITKDimensions`
- Engine health telemetry now emits periodic snapshots (`[ZetaBoost] HEALTH ...`) with:
  - memory/disk hits
  - misses
  - queued/processed/failed counts
  - lane queue/inflight distribution

Fail-safe repeatability guards (2026-02-15):

- On per-series preload failure, engine invalidates that series runtime state immediately:
  - removes in-memory cache entry
  - removes queued/inflight references
  - removes L2 disk payload + manifest entry for that series
- Disk-cache write failures perform rollback:
  - partial payload files are deleted
  - manifest row is removed (`PUT_ROLLBACK`)
- Repeated consecutive failures trigger engine fail-safe reset (`FAILSAFE_RESET`):
  - pending queues are cleared
  - in-memory cache is cleared
  - tab disk-cache entries are cleared

These protections are intended to prevent cumulative error buildup across long-running PACS usage.

Performance guardrails (2026-02-15):

- To avoid cache-layer overhead becoming a speed bump:
  - repeated short-term disk-cache misses are memoized and suppressed for a brief TTL window,
    reducing repeated SQLite/filesystem probes on the same missing series.
  - health telemetry cadence is intentionally throttled (lower log frequency) to reduce runtime log overhead.

These guardrails are intended to keep the optimization net-positive under heavy, repetitive workloads.

Warm-up UX/performance contract (2026-02-15):

- Warm-up must not degrade natural/interactive loading latency.
  - Heavy warm-up runs only in deferred background phase.
  - Deferred heavy dispatch is paced one-by-one and gated by short interaction-idle windows.
- Light series are warmed first; heavy series are warmed after light phase completes.
- Warmed series should switch quickly in the viewer:
  - switch path avoids deep-copying large instance arrays during warmed-data apply,
    reducing drag-drop latency on large studies.
- Preview-only payloads are never considered valid deterministic full-cache entries.
  - Any preview-only L2/L1 cache hit is invalidated and reloaded as full volume.
  - This prevents the "1-image" stale preview state from being reused as if fully warmed.
- First displayed series is explicitly primed into deterministic cache after initial render,
  so repeat drag/drop remains stable even though open-warmup skips primary startup loading.
- Warmup now emits verification snapshots (`[ZetaBoost][VERIFY]`) at:
  - after open-warmup scheduling,
  - after deferred heavy warmup completion,
  including total/full-cached/preview-flagged/missing coverage counters.
```

---

## 2. Stage 1 â€” DICOM on Disk

### What DICOM provides

Each DICOM file contains:

| DICOM Tag | Name | Meaning |
|-----------|------|---------|
| `(0020,0032)` | Image Position (Patient) | XYZ position of the first voxel of this slice in LPS+ patient coordinates |
| `(0020,0037)` | Image Orientation (Patient) | Two 3-element vectors: row direction cosine and column direction cosine |
| `(0028,0030)` | Pixel Spacing | [row_spacing, col_spacing] in mm |
| `(0018,0050)` | Slice Thickness | Thickness of one slice in mm |
| `(0028,0010)` | Rows | Number of rows in the pixel data |
| `(0028,0011)` | Columns | Number of columns in the pixel data |

### DICOM Patient Coordinate System (LPS+)

DICOM uses a **Left-Posterior-Superior (LPS+)** coordinate system:
- **X** increases toward the patient's **Left**
- **Y** increases toward **Posterior** (back of body)
- **Z** increases toward **Superior** (head)

The `ImageOrientationPatient` tag gives two unit vectors:
- **Row direction**: direction along increasing column index
- **Column direction**: direction along increasing row index

The third direction (slice/normal) is the cross product: `normal = row أ— column`

### What SimpleITK does with these

When `sitk.ImageSeriesReader` reads a DICOM series:

1. It sorts the slices by `ImagePositionPatient[2]` (or by the projection along the
   slice normal direction)
2. It builds a 3D volume with:
   - **Origin** = `ImagePositionPatient` of the first sorted slice
   - **Spacing** = `(col_spacing, row_spacing, computed_slice_spacing)`
   - **Direction** = a 3أ—3 matrix built from `ImageOrientationPatient` + cross product

> **CRITICAL**: SimpleITK does **NOT** reorient, flip, or rearrange the pixel data.
> It preserves the DICOM geometry exactly.  If the DICOM says the image goes from
> Feet to Head, that's the order you get.

---

## 3. Stage 2 â€” SimpleITK Loading

### Code Location
- `PacsClient/pacs/patient_tab/utils/image_io.py` â†’ `get_itk_image()`
- `PacsClient/pacs/patient_tab/utils/utils.py` â†’ `get_itk_image_optimized()`

### What happens

```python
reader = sitk.ImageSeriesReader()
reader.MetaDataDictionaryArrayUpdateOff()   # Speed: skip per-slice metadata
reader.SetFileNames(dicom_names)            # Pre-sorted file list
itk_image = reader.Execute()
```

### Properties of the resulting `sitk.Image`

| Property | Method | Description |
|----------|--------|-------------|
| Size | `GetSize()` â†’ `(x, y, z)` | Number of voxels along each axis. **Note**: X=columns, Y=rows, Z=slices |
| Origin | `GetOrigin()` â†’ `(ox, oy, oz)` | Position of voxel (0,0,0) in LPS+ patient mm |
| Spacing | `GetSpacing()` â†’ `(sx, sy, sz)` | Voxel size in mm along each axis |
| Direction | `GetDirection()` â†’ 9 floats | 3أ—3 direction cosine matrix, **row-major** |

### Direction matrix layout

`sitk.Image.GetDirection()` returns 9 values in **row-major** order:

```
direction = (d00, d01, d02,   â†گ row 0: how voxel-X maps to patient-XYZ
             d10, d11, d12,   â†گ row 1: how voxel-Y maps to patient-XYZ
             d20, d21, d22)   â†گ row 2: how voxel-Z maps to patient-XYZ
```

The **ITK physical point formula** (CS-1):

```
patient_point = Origin + Direction @ (ijk * Spacing)
```

Or more explicitly:

```
âژ، px âژ¤   âژ، ox âژ¤   âژ، d00  d01  d02 âژ¤   âژ، iآ·sx âژ¤
âژ¢ py âژ¥ = âژ¢ oy âژ¥ + âژ¢ d10  d11  d12 âژ¥ آ· âژ¢ jآ·sy âژ¥
âژ£ pz âژ¦   âژ£ oz âژ¦   âژ£ d20  d21  d22 âژ¦   âژ£ kآ·sz âژ¦
```

### Numpy array axis order

```python
arr = sitk.GetArrayFromImage(itk_image)
# arr.shape = (z_slices, y_rows, x_cols)
# arr[k, j, i] corresponds to voxel (i, j, k) in SimpleITK
```

**This is the ZYX convention** â€” SimpleITK stores arrays with Z (slices) as the
slowest-varying axis and X (columns) as the fastest.

---

## 4. Stage 3 â€” ITK â†’ VTK Conversion

### Code Location
- `PacsClient/pacs/patient_tab/utils/utils.py` â†’ `convert_itk2vtk()`
- Also: `convert_itk2vtk_fast_first()` (same logic, speed-optimized)

### Step-by-step breakdown

```python
def convert_itk2vtk(itk_image: sitk.Image):
    x, y, z = itk_image.GetSize()          # (cols, rows, slices)
    vtk_image = vtk.vtkImageData()
    vtk_image.SetDimensions(x, y, z)       # VTK dimensions = (cols, rows, slices)
    vtk_image.SetSpacing(itk_image.GetSpacing())   # Same spacing
    vtk_image.SetOrigin(itk_image.GetOrigin())      # Same origin
```

**Step 1**: Create `vtkImageData` with the same dimensions, spacing, and origin as
the SimpleITK image.  No transformation yet.

```python
    direction = itk_image.GetDirection()    # 9 floats, row-major
    direction_matrix = vtk.vtkMatrix4x4()
    direction_matrix.Identity()
    for row in range(3):
        for col in range(3):
            direction_matrix.SetElement(row, col, direction[row * 3 + col])
```

**Step 2**: Build a 4أ—4 direction matrix from the ITK 3أ—3 direction.
At this point, the matrix is the **original ITK direction**.

```python
    arr = sitk.GetArrayFromImage(itk_image)  # shape: (z, y, x)
    arr = arr[:, ::-1, :]                     # â†گ THE Y-FLIP
```

**Step 3 â€” THE Y-FLIP**: The numpy array is flipped along axis-1 (the Y/row axis).

**Why?** VTK's `vtkImageData` expects pixels in a specific memory layout
where Y increases upward (or at least in a specific direction that differs from
the DICOM row ordering).  The Y-flip corrects the image so it displays right-side-up
in VTK's rendering pipeline.

**What this means geometrically:**
If the original voxel at position `(i, j, k)` had content C, after the flip it
is now at position `(i, (y-1-j), k)`.

```python
    # Compensate the direction matrix for the Y-flip
    for col in range(3):
        direction_matrix.SetElement(1, col, -direction_matrix.GetElement(1, col))
```

**Step 4 â€” Direction Matrix Compensation**: Row 1 of the direction matrix is negated.

This is the mathematical compensation for the Y-flip:
- Original: `patient = origin + D @ [iآ·sx, jآ·sy, kآ·sz]لµ€`
- After flip: voxel `j_new = (y-1) - j_old`, so `j_old = (y-1) - j_new`
- To keep the same patient position: the direction's row-1 must be negated
  (and an origin shift implicitly happens through the VTK coordinate system)

The stored ("compensated") direction matrix is:

```
D_stored = âژ،  d00   d01   d02 âژ¤
           âژ¢ -d10  -d11  -d12 âژ¥   â†گ row 1 negated
           âژ£  d20   d21   d22 âژ¦
```

```python
    # Store as field data (survives VTK pipeline... mostly)
    direction_array = vtk.vtkDoubleArray()
    direction_array.SetName("DirectionMatrix")
    direction_array.SetNumberOfTuples(16)
    for i in range(4):
        for j in range(4):
            direction_array.SetValue(i * 4 + j, direction_matrix.GetElement(i, j))
    vtk_image.GetFieldData().AddArray(direction_array)
```

**Step 5**: The compensated direction matrix is stored as field data named
`"DirectionMatrix"` â€” 16 doubles (4أ—4 matrix, row-major).

**IMPORTANT**: The direction is stored as **field data**, not via `SetDirectionMatrix()`.
This is because older VTK versions don't support `SetDirectionMatrix()` on `vtkImageData`.

```python
    # Set pixel data
    vtk_arr = numpy_support.numpy_to_vtk(arr.ravel(order='C'), deep=False)
    vtk_image.GetPointData().SetScalars(vtk_arr)
    return vtk_image
```

**Step 6**: The Y-flipped numpy array is set as the scalar data.

### Summary of what `convert_itk2vtk` produces

| Property | Value | Notes |
|----------|-------|-------|
| Dimensions | Same as ITK `GetSize()` | (cols, rows, slices) |
| Spacing | Same as ITK `GetSpacing()` | Unchanged |
| Origin | Same as ITK `GetOrigin()` | Unchanged â€” **but the Y-flip means the origin no longer points to the physical location of voxel (0,0,0)!** |
| Pixel data | Y-flipped | `arr[:, ::-1, :]` |
| Field data `"DirectionMatrix"` | Row-1 negated 4أ—4 | Compensates for Y-flip |
| Field data `"ITKOrigin"` | 3 doubles | Original ITK origin (same as VTK origin) |
| Field data `"ITKSpacing"` | 3 doubles | **Original ITK spacing** (critical â€” differs from VTK after upsampling) |
| Field data `"ITKDimensions"` | 3 doubles | **Original ITK dimensions** (critical â€” differs from VTK after upsampling) |
| `SetDirectionMatrix()` | **NOT called** | Only field data is set |

### The "origin problem"

After the Y-flip, voxel `(0, 0, 0)` in the VTK image contains what was originally
voxel `(0, y-1, 0)` in the ITK image.  But the **origin** is still set to
`itk_image.GetOrigin()`, which is the patient-space position of the original voxel
`(0, 0, 0)` â€” not `(0, y-1, 0)`.

This means: **the simple formula `world = origin + ijk * spacing` gives the wrong
patient-space position for the Y-flipped VTK data**.  The correct formula must
account for the Y-flip compensation.

---

## 5. Stage 4 â€” Viewer Preprocessing

### Code Location
- `modules/viewer/advanced/viewer_2d.py` â†’ `ImageViewer2D.__init__()`

### Step sequence in the constructor

```python
# 1. Store the input vtk_image_data
self.vtk_image_data = vtk_image_data

# 2. Optional upsampling (does NOT flip or rotate)
self.vtk_image_data = self._preprocess_vtk_image_data(self.vtk_image_data)

# 3. Apply direction matrix from field data to VTK native attribute
self._apply_direction_matrix_from_field_data()

# 4. Create reslice (pass-through, no rotation applied)
self.image_reslice = ImageReslice(self.vtk_image_data, self.metadata)

# 5. Set the reslice OUTPUT as the viewer's input
self.SetInputData(self.image_reslice.GetOutput())

# 6. *** CRITICAL REASSIGNMENT ***
self.vtk_image_data = self.image_reslice.GetOutput()
```

### What `_preprocess_vtk_image_data` does

```python
def _preprocess_vtk_image_data(self, vtk_image_data):
    if self.apply_default_filter:
        factor = self.__get_factor_upsample(vtk_image_data, self.viewer_height)
        if factor > 1:
            vtk_image_data = display_upsample_xy(vtk_image_data, factor=factor)
    return vtk_image_data
```

- Conditionally upsamples the XY plane for display quality
- **Does NOT change orientation, direction, or flip anything**
- âڑ ï¸ڈ **Upsampling changes spacing and dimensions!** After upsampling, the VTK
  image's `GetSpacing()` and `GetDimensions()` no longer match the original ITK values.
  For example, a 580أ—640 image with 0.3438mm spacing may become 753أ—831 with 0.264mm spacing.
  The physical extent is preserved, but the voxel grid is different.

> **BUG FOUND (v1.09.1):** The original sync mapping code used post-upsampled
> spacing/dims with the original ITK direction matrix, causing ~0.6mm drift in
> rotated coordinate calculations. Fixed by storing `ITKSpacing` and `ITKDimensions`
> as field data and using those exclusively in the mapping functions.

### What `_apply_direction_matrix_from_field_data` does

```python
def _apply_direction_matrix_from_field_data(self):
    direction = self._get_direction_matrix()    # Read from field data
    if direction is not None:
        matrix = vtk.vtkMatrix4x4()
        for row in range(3):
            for col in range(3):
                matrix.SetElement(row, col, float(direction[row, col]))
        self.vtk_image_data.SetDirectionMatrix(matrix)
```

- Reads the compensated direction matrix from field data
- Calls `SetDirectionMatrix()` on the VTK image data (VTK 9+ only)
- This is done on the **pre-reslice** image

### What `ImageReslice` does

```python
class ImageReslice(vtk.vtkImageReslice):
    def __init__(self, vtk_image_data, metadata):
        self.vtk_image_data = vtk_image_data    # Stores original as attribute
        self.SetInputData(self.vtk_image_data)
        self.SetOutputDimensionality(3)
        self.SetInterpolationModeToCubic()
        self.OptimizationOn()
        self.Update()

    def apply_orientation(self):
        pass    # â†گ NO-OP!  No rotation is applied!
```

- **The reslice is a pass-through** â€” it does not rotate or reorient
- `apply_orientation()` is a no-op (`pass`)
- The reslice output has the same geometry as the input
- **The original image is preserved** as `self.image_reslice.vtk_image_data`

### What happens to the direction matrix after reslice

| Property | Pre-reslice image | Reslice output |
|----------|------------------|----------------|
| Field data `"DirectionMatrix"` | âœ… Present | â‌Œ **Lost** (VTK filters don't propagate field data) |
| `SetDirectionMatrix()` | âœ… Set (if VTK 9+) | â‌Œ **Not propagated** by `vtkImageReslice` |

**This is why `self.vtk_image_data` (post-reslice) appears to have identity direction.**

### The Critical Reassignment

After line `self.vtk_image_data = self.image_reslice.GetOutput()`:

- `self.vtk_image_data` â†’ reslice output (no direction, no field data)
- `self.image_reslice.vtk_image_data` â†’ original input (has direction in field data)

**Any coordinate conversion that reads from `self.vtk_image_data` post-reslice
will get identity direction because the direction information was lost.**

---

## 6. Stage 5 â€” ImageReslice & Display

### How `vtkResliceImageViewer` displays slices

`ImageViewer2D` inherits from `vtkResliceImageViewer`, which:

1. Takes a 3D `vtkImageData` as input
2. Slices it along one of three planes based on orientation:
   - **Orientation 0** (Sagittal/YZ): slices along the X axis
   - **Orientation 1** (Coronal/XZ): slices along the Y axis
   - **Orientation 2** (Axial/XY): slices along the Z axis
3. Uses `GetSlice()` to get the current slice index
4. Renders the 2D slice via `vtkImageActor`

### The VTK coordinate system for the reslice output

Since the reslice is a pass-through and direction is lost, the effective coordinate
system of the displayed image is:

```
vtk_world = origin + ijk * spacing     (identity direction)
```

Where:
- `origin` = ITK origin (DICOM `ImagePositionPatient` of first slice)
- `spacing` = ITK spacing (unchanged)
- `ijk` = voxel indices in the Y-flipped data

### Picking / Mouse events

When the user clicks on the image, VTK pickers return coordinates in this
"simple" VTK world space (origin + ijk أ— spacing).  These are **NOT** patient
coordinates â€” they don't account for the direction matrix.

---

## 7. Stage 6 â€” MPR Path

### Code Location
- `PacsClient/pacs/patient_tab/zeta mpr/standard_mpr_viewer.py`

### What MPR does differently

The MPR viewer applies an **additional X-flip** on top of the Y-flipped data:

```python
image_flip = vtk.vtkImageFlip()
image_flip.SetInputData(vtk_image_data)    # Already Y-flipped from convert_itk2vtk
image_flip.SetFilteredAxis(0)               # Flip along X axis
image_flip.Update()
self.image_data = image_flip.GetOutput()
```

And compensates the direction matrix:

```python
# After copying field data to the flipped image:
for i in range(3):
    self.direction_matrix.SetElement(i, 0, -self.direction_matrix.GetElement(i, 0))
```

### MPR coordinate space

After both flips (Y in `convert_itk2vtk` + X in MPR):
- Column 0 of direction is negated (X-flip compensation)
- Row 1 of direction is negated (Y-flip compensation from `convert_itk2vtk`)
- The effective direction has **two compensations** applied

### MPR uses `vtkImageResliceMapper`

Unlike the 2D viewer (which uses `vtkResliceImageViewer`), MPR uses
`vtkImageResliceMapper` with `SliceFacesCameraOn()` and `SliceAtFocalPointOn()`.
The camera position/orientation determines which slice is shown.

---

## 8. Complete Transformation Chain

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”گ
â”‚  DICOM Files on Disk                                     â”‚
â”‚  - Pixel data in row-major order                         â”‚
â”‚  - ImagePositionPatient, ImageOrientationPatient         â”‚
â”‚  - LPS+ coordinate system                                â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”ک
                       â”‚
                       â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”گ
â”‚  Stage 1: SimpleITK ImageSeriesReader                    â”‚
â”‚  â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€                   â”‚
â”‚  Reads and assembles DICOM into 3D volume                â”‚
â”‚  âœ“ Origin preserved (from first slice IPP)               â”‚
â”‚  âœ“ Spacing preserved                                     â”‚
â”‚  âœ“ Direction = 3أ—3 from ImageOrientationPatient          â”‚
â”‚  âœ“ Numpy: shape = (z, y, x) â€” ZYX order                 â”‚
â”‚  âœ— NO reorientation applied                              â”‚
â”‚  âœ— NO DICOMOrient called                                 â”‚
â”‚                                                          â”‚
â”‚  Formula: patient = origin + D_itk @ (ijk * spacing)    â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”ک
                       â”‚
                       â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”گ
â”‚  Stage 2: convert_itk2vtk()                              â”‚
â”‚  â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€                               â”‚
â”‚  1. SetDimensions(x, y, z)  â€” same as ITK               â”‚
â”‚  2. SetSpacing(itk.GetSpacing())  â€” unchanged            â”‚
â”‚  3. SetOrigin(itk.GetOrigin())  â€” unchanged              â”‚
â”‚  4. Build D_itk from GetDirection()                      â”‚
â”‚  5. *** Y-FLIP: arr[:, ::-1, :] ***                      â”‚
â”‚     Voxel (i, j, k) â†’ (i, y-1-j, k)                    â”‚
â”‚  6. Negate row 1 of D â†’ D_stored                        â”‚
â”‚     D_stored[1,:] = -D_itk[1,:]                         â”‚
â”‚  7. Store D_stored as FieldData "DirectionMatrix"        â”‚
â”‚                                                          â”‚
â”‚  Output has: Y-flipped pixels, original origin,          â”‚
â”‚  compensated direction in field data                     â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”ک
                       â”‚
           â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”گ
           â–¼                       â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”گ â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”گ
â”‚  2D Viewer Path     â”‚ â”‚  MPR Path             â”‚
â”‚  (ImageViewer2D)    â”‚ â”‚  (StandardMPRViewer)  â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”ک â””â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”ک
         â”‚                       â”‚
         â–¼                       â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”گ â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”گ
â”‚ Stage 3a: Viewer    â”‚ â”‚ Stage 3b: MPR        â”‚
â”‚ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€  â”‚ â”‚ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ â”‚
â”‚ 1. Optional         â”‚ â”‚ 1. X-FLIP:           â”‚
â”‚    upsample XY      â”‚ â”‚    vtkImageFlip(0)   â”‚
â”‚ 2. SetDirection     â”‚ â”‚ 2. Negate column 0   â”‚
â”‚    Matrix (VTK9)    â”‚ â”‚    of direction       â”‚
â”‚ 3. ImageReslice     â”‚ â”‚ 3. Camera setup      â”‚
â”‚    (pass-through)   â”‚ â”‚    from direction     â”‚
â”‚ 4. vtk_image_data   â”‚ â”‚ 4. vtkImageReslice   â”‚
â”‚    = reslice output  â”‚ â”‚    Mapper per view   â”‚
â”‚    (direction LOST) â”‚ â”‚                      â”‚
â”‚                     â”‚ â”‚ Has: X+Y flipped     â”‚
â”‚ Has: Y-flipped onlyâ”‚ â”‚ pixels, original     â”‚
â”‚ origin, NO          â”‚ â”‚ origin, doubly-      â”‚
â”‚ direction on output â”‚ â”‚ compensated          â”‚
â”‚                     â”‚ â”‚ direction            â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”ک â””â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”ک
         â”‚                       â”‚
         â–¼                       â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”گ
â”‚  Stage 4: Display / Rendering                            â”‚
â”‚  â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€                           â”‚
â”‚  2D: vtkResliceImageViewer slices along XY/YZ/XZ        â”‚
â”‚  MPR: vtkImageResliceMapper with camera-oriented slicing â”‚
â”‚                                                          â”‚
â”‚  Pickers return coords in VTK world space:               â”‚
â”‚    vtk_world = origin + ijk * spacing   (identity dir)   â”‚
â”‚                                                          â”‚
â”‚  These are NOT patient coordinates!                      â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”ک
```

---

## 9. Coordinate Conversion Functions Reference

### The Core Conversion Functions (v1.09.5)

These static methods in `patient_widget.py` convert between VTK postâ€‘Yâ€‘flip world
space and DICOM patient (LPS+) space.  They use the **original ITK geometry**
stored in field data (`ITKSpacing`, `ITKDimensions`, `DirectionMatrix`) so they are
independent of any display upsampling.

> **v1.09.5 change:** The `D_vtk` parameter was removed from all mapping functions.
> The VTK picker returns `origin + ijk * spacing` **without** applying the
> `SetDirectionMatrix()` rotation, so undoing it was a mathematical error that
> introduced a spurious transform for oblique MRI.  For CT (identity direction)
> the error was invisible (Dآ²=I).

#### `_read_itk_geometry(viewer)` â†’ dict or None

Reads original ITK geometry from the pre-reslice image's field data.
Returns a dict with:

| Key | Type | Description |
|-----|------|-------------|
| `D_itk` | np.ndarray (3,3) | Original ITK direction (row-1 un-negated) |
| `spacing` | np.ndarray (3,) | Original ITK spacing (not upsampled) |
| `dims` | np.ndarray (3,) | Original ITK dimensions (int) |
| `extent_y` | float | `(dims_y - 1) * spacing_y` â€” ITK physical Y extent in mm |
| `extent_y_disp` | float | `(display_dims_y - 1) * display_sp_y` â€” display physical Y extent |
| `origin` | np.ndarray (3,) | Pre-reslice image origin (= ITK origin) |
| `source` | str | `'field_data'` or `'image_fallback'` â€” where spacing/dims came from |

> **Why two extent_y values?**  `vtkImageResample` rounds output dimensions, so
> `extent_y_disp â‰  extent_y` (a mismatch of several mm for highly-upsampled images).
> The fractional Y-flip reversal (v1.09.3) needs both to avoid coordinate drift.

#### `_vtk_world_to_patient(world_pos, origin, extent_y_itk, D_itk, extent_y_disp=None)`

```
Input:  VTK world position (from picker or reslice output)
Output: DICOM patient position (LPS+) as np.ndarray(3)

Math (v1.09.5 â€” fractional Y-flip, no D_vtk):
  delta       = world_pos - origin                       # physical offset in VTK space
  frac_y      = delta[1] / extent_y_disp                  # fraction along display-Y
  s_y         = extent_y_itk * (1.0 - frac_y)             # ITK physical Y offset (un-flipped)
  s           = (delta[0], s_y, delta[2])
  patient     = origin + D_itk @ s                        # apply ITK direction
```

> **Key insight (v1.09.5):** The VTK picker returns `origin + ijk * spacing` WITHOUT
> applying the `SetDirectionMatrix()` rotation.  This was verified empirically:
> Z_returned = origin_z + slice_index * spacing_z, with no direction rotation.  Therefore
> the mapping is simply delta â†’ undo-Y-flip â†’ D_itk.  The v1.09.4 D_vtk correction was
> removed because it introduced a spurious rotation for oblique MRI.

#### `_patient_to_vtk_world_clamped(patient_pos, origin, spacing_itk, dims_itk, extent_y_itk, D_itk, extent_y_disp=None)`

```
Input:  DICOM patient position (LPS+)
Output: tuple(vtk_world, ijk_itk_raw, was_outside)

Math (v1.09.5 â€” fractional Y-flip, no D_vtk):
  s = D_itk_inv @ (patient_pos - origin)        # physical offset in ITK frame
  ijk_itk = s / spacing_itk                       # ITK voxel indices (continuous)
  ijk_clamped = clip(ijk_itk, 0, dims-1)          # clamp to valid voxel range
  s_clamped = ijk_clamped * spacing_itk            # back to physical
  frac_y = s_clamped[1] / extent_y_itk             # fraction along ITK-Y
  delta_y_disp = extent_y_disp * (1.0 - frac_y)   # display-Y offset (re-flip)
  delta = (s_clamped[0], delta_y_disp, s_clamped[2])
  vtk_world = origin + delta                       # VTK world position
```

Returns:
- `vtk_world` â€” tuple(3) clamped VTK world position
- `ijk_itk_raw` â€” np.ndarray(3) unclamped ITK voxel indices (for diagnostics)
- `was_outside` â€” bool True if point fell outside the volume (any ijk off by >0.5)

### Cross-Volume Sync Mapping (v1.09.5)

The sync/target feature uses a **three-tier mapping strategy**:

#### Tier 1 â€” DICOM IOP/IPP (primary, v1.09.5)

The preferred path uses per-slice DICOM metadata (ImageOrientationPatient,
ImagePositionPatient) â€” the **exact same functions** as `reference_line.py`.
This guarantees the sync dot lies on the reference line.

```
VTK world (source)
  â†’ display index  (simple: (world - origin) / spacing)
  â†’ flipped-LPS    (IPP + idx * sp * IOP_directions)
  â†’ undo flip-Y    (rl_apply_flip_y_in_plane, self-inverse)
  â†’ patient LPS    (true anatomical coordinates)
  â†’ closest target slice  (dot(P - IPP_0, slice_normal) / slice_spacing)
  â†’ project onto plane    (remove off-plane component)
  â†’ flip-Y for target     (rl_apply_flip_y_in_plane)
  â†’ target index          (rl_lps_to_target_index)
  â†’ VTK world (target)    (origin + index * spacing)
```

Implemented in `_map_sync_dicom()`.  Falls through to Tier 2 if DICOM
metadata (`image_orientation_patient`, `image_position_patient`) is missing.

#### Tier 2 â€” ITK direction matrix (fallback)

```
VTK world A  â†’  [centre-of-slice adj]  â†’  _vtk_world_to_patient(A)  â†’  patient (LPS+)  â†’  _patient_to_vtk_world_clamped(B)  â†’  VTK world B
```

**Centre-of-slice adjustment (v1.09.2):** Before converting to patient space, the
source world position is shifted by `+display_spacing[slice_axis] / 2` along the
slice direction.  This maps from the **visual centre** of the source slice rather
than the face (lower boundary).  For thick slices (e.g. 3.75 mm CT) the 1.875 mm
offset is clinically significant; for thin slices it's negligible.

#### Tier 3 â€” Fractional mapping (last resort)

When neither DICOM metadata nor ITK direction data is available, a simple
positional fraction mapping is used.  This preserves relative position within
each volume but does not handle orientation differences.

#### All tiers handle:
- **Same orientation, same spacing** (identical CT): identity through patient space
- **Same orientation, different spacing** (CT reconstructions, e.g. 3.75mm vs 0.625mm)
- **Different orientations** (Axial T2 â†” Sagittal T1): direction matrices rotate correctly
- **Oblique acquisitions**: any orientation works because the full 3أ—3 direction is used
- **Non-overlapping volumes**: clamped, with `OUT_OF_BOUNDS` warning in logs

#### Why DICOM-first?

Reference lines (`reference_line.py`) use IOP/IPP directly from per-slice metadata.
If the sync mapping used a different coordinate path (e.g. ITK direction matrix),
floating-point rounding or metadata ordering mismatches could cause the sync dot
to diverge slightly from the reference line.  Using the **same** functions
(`rl_center_of_slice`, `rl_apply_flip_y_in_plane`, `rl_lps_to_target_index`)
eliminates this class of errors entirely.

### Available functions and what space they operate in

| Function | File | Input â†’ Output | Direction-aware? | Notes |
|----------|------|---------------|-----------------|-------|
| `_map_sync_dicom()` | patient_widget.py | CS-4 src â†’ CS-4 tgt | âœ… Yes | **Primary** sync path; uses same functions as reference_line.py |
| `_vtk_world_to_patient()` | patient_widget.py | CS-4 VTK world â†’ CS-1 patient | âœ… Yes | Fractional Y-flip; ITK fallback path |
| `_patient_to_vtk_world_clamped()` | patient_widget.py | CS-1 patient â†’ CS-4 VTK world | âœ… Yes | Clamps in voxel space, fractional Y |
| `_read_itk_geometry()` | patient_widget.py | viewer â†’ geometry dict | âœ… Yes | Returns extent_y, extent_y_disp, origin |
| `ijk_to_world_physical()` | viewer_2d.py | CS-3 voxel â†’ CS-1 patient | âœ… Yes | Uses `_get_direction_matrix()` |
| `world_to_ijk_physical()` | viewer_2d.py | CS-1 patient â†’ CS-3 voxel | âœ… Yes | Tries VTK native, falls back to matrix |
| `_slice_index_from_world()` | viewer_2d.py | CS-4 world â†’ slice index | â‌Œ No | Simple `(world-origin)/spacing` |
| `pick_world_point()` | viewer_2d.py | CS-5 display â†’ CS-4 world | N/A | Uses VTK pickers |
| `world_to_ijk()` | geometry_utils.py | World â†’ IJK | âœ… Yes | From zeta_sync module |
| `ijk_to_world()` | geometry_utils.py | IJK â†’ World | âœ… Yes | From zeta_sync module |
| `build_ijk_to_world_matrix()` | geometry_utils.py | Builds 4أ—4 affine | âœ… Yes | `origin + D @ diag(spacing) @ ijk` |
| `world_to_ijk_vtk()` | convertors.py | World â†’ IJK | âœ… Yes | Uses `GetDirectionMatrix()` |

### When to use which

- **2D viewer sync/target**: Use `_vtk_world_to_patient` + `_patient_to_vtk_world` for 
  crossâ€‘volume mapping. Use simple `(world - origin) / spacing` for withinâ€‘volume slice
  index calculation (reslice output has identity direction).

- **Cross-volume mapping**: Always go through patient space using the two core functions.

- **MPR calculations**: Use the direction matrix from field data (with appropriate
  compensation for the X+Y flips).

- **DICOM patient coordinates**: Use `_vtk_world_to_patient()` with the direction
  matrix from the **pre-reslice** image (`self.image_reslice.vtk_image_data`).

---

## 9b. FAST Mode â€” Pure-DICOM Sync Geometry Pipeline

> **Version introduced:** v2.2.9.2 (2026-04-09)
> **File:** `modules/viewer/fast/dicom_sync_geometry.py`
> **Applies to:** FAST (`pydicom_2d` / `pydicom_qt`) backend sync targets only.
> The Advanced backend uses the VTK-world-space path described in آ§9.

### Why a separate geometry path?

The Advanced backend stores a 3D `vtkImageData` volume whose "world space"
coordinates are a VTK convention (origin + spacing + direction matrix, with
the Y-flip compensation applied in `convert_itk2vtk`). Sync for Advanced
targets is done via VTK world-space reverse-projection.

FAST targets have **no VTK volume**.  Geometry must be derived entirely from
the DICOM IOP/IPP metadata stored per instance.  All math is in the DICOM
patient-LPS coordinate system (CS-1) and never passes through CS-2 â€“ CS-5.

### Coordinate space used

All FAST sync geometry uses **CS-1 (patient-LPS)** exclusively:

```
DICOM File
  IPP (Image Position Patient)     â†’  origin of this slice in LPS space
  IOP (Image Orientation Patient)  â†’  row direction + column direction cosines

n_t = cross(col_dir, row_dir)       â†’  slice normal in LPS space
P_proj = P âˆ’ dot(Pâˆ’IPP_k, n_t)آ·n_t â†’  projection onto slice plane
col_idx = dot(P_projâˆ’IPP_k, row_dir) / pixel_spacing[1]
row_idx = dot(P_projâˆ’IPP_k, col_dir) / pixel_spacing[0]
```

This is identical to the DICOM standard آ§ C.7.6.2 Patient Coordinate System.
No direction-matrix Y-flip, no VTK axis reordering.

### Sparse stack correction (v2.2.9.2)

The formula-based slice finder (`k_float = d0 / ds`) estimated slice spacing
from only the first two slices and assumed all slices were uniformly spaced.
For lumbar MRI acquired disc-by-disc (3 slices per disc level, ~15 mm
inter-disc gap) this produced catastrophically wrong results:

```
ds = 1 mm  (intra-group)
Source at d_src = 40 mm above IPP_0 â†’ k_float = 40 â†’ clamped to last disc group
Correct answer: k = 4 (slice at d = 40 mm inside L3-L4 group)
```

**Fix:** `find_closest_slice_physical()` scans all `n` slice positions in O(n)
and returns `argmin |positions âˆ’ d_src|`.  This is correct for any spacing
pattern.

**Sparse detection:** `analyse_target_stack()` classifies a stack as sparse
when `max_spacing > 3.0 أ— median_spacing`.  If the source is more than
`0.7 أ— typical_spacing` from the nearest slice, `between_groups = True` and
the sync cursor is hidden (no anatomical correspondence at that position).

### Comparison: Advanced vs FAST sync coordinate paths

| Step | Advanced (VTK) | FAST (pure-DICOM) |
|------|---------------|-------------------|
| Input | Patient-LPS from `_pw_sync` event | Same patient-LPS |
| Slice normal | From direction matrix in VTK field data | `cross(IOP_col, IOP_row)` |
| Slice finder | `vtkImageViewer2.SetSlice()` with `GetSliceMin/Max` | `argmin |positions âˆ’ d_src|` |
| Floor/ceiling | VTK clamp to `[GetSliceMin, GetSliceMax]` | Physical extent check with آ½-spacing tolerance |
| Pixel coords | VTK picker or manual worldâ†’pixel | `lps_to_image_pixel()` via IOP/IPP |
| Sparse stacks | Not an issue (full 3D volume in memory) | Explicit `between_groups` detection |
| Rejection | No explicit rejection (always shows something) | `final_valid_sync_point=False` â†’ cursor hidden |

### Full function chain

```
project_lps_to_target(P_lps, instances)
  â†“
  compute_slice_normal(IOP)                     # n_t = cross(col, row)
  compute_slice_positions(instances, n_t)       # positions[k] = dot(IPP_kâˆ’IPP_0, n_t)
  analyse_target_stack(instances, positions)    # is_sparse, typical_spacing, max_gap
  find_closest_slice_physical(P_lps, â€¦)         # k_nearest, d_src, min_dist
  between_groups detection                       # min_dist > 0.7 أ— typical_spacing?
  project_lps_onto_plane(P_lps, IPP_k, n_t)    # P_proj, dp
  lps_to_image_pixel(P_proj, IPP_k, IOP, px)   # col_idx, row_idx
  validity classification                        # slab_valid, inplane_valid, final_valid
  â†’ SliceProjectionResult
```

See آ§6 of [VIEWER_BACKENDS_REFERENCE.md](VIEWER_BACKENDS_REFERENCE.md) for
the complete pipeline diagram, rejection flow, all field definitions, and the
`[FAST-SYNC-VALIDATION]` logging reference.

---

## 10. Direction Matrix â€” What It Is, How It Changes


### The original ITK direction (D_itk)

For a standard **axial** acquisition:
```
D_itk = âژ، 1  0  0 âژ¤   â†گ voxel-X aligns with patient-X (Left)
        âژ¢ 0  1  0 âژ¥   â†گ voxel-Y aligns with patient-Y (Posterior)
        âژ£ 0  0  1 âژ¦   â†گ voxel-Z aligns with patient-Z (Superior)
```

For a standard **sagittal** acquisition:
```
D_itk = âژ، 0  0  -1 âژ¤  â†گ voxel-X aligns with -patient-Z (Inferior)
        âژ¢ 1  0   0 âژ¥  â†گ voxel-Y aligns with patient-X (Left)
        âژ£ 0 -1   0 âژ¦  â†گ voxel-Z aligns with -patient-Y (Anterior)
```

(Exact values vary by scanner and patient position)

### After Y-flip compensation (D_stored in field data)

```
D_stored = âژ،  D_itk[0,0]   D_itk[0,1]   D_itk[0,2] âژ¤
           âژ¢ -D_itk[1,0]  -D_itk[1,1]  -D_itk[1,2] âژ¥   â†گ row 1 negated
           âژ£  D_itk[2,0]   D_itk[2,1]   D_itk[2,2] âژ¦
```

### After MPR X-flip compensation (D_mpr)

```
D_mpr = âژ، -D_stored[0,0]  D_stored[0,1]  D_stored[0,2] âژ¤
        âژ¢ -D_stored[1,0]  D_stored[1,1]  D_stored[1,2] âژ¥   â†گ column 0 negated
        âژ£ -D_stored[2,0]  D_stored[2,1]  D_stored[2,2] âژ¦
```

### To recover original ITK direction from stored field data

```python
D_stored = read_from_field_data()   # 3أ—3 from "DirectionMatrix"
D_itk = D_stored.copy()
D_itk[1, :] = -D_itk[1, :]         # Un-negate row 1
```

### Where direction is accessible at each stage

| Stage | Access path | Has direction? | Which direction? |
|-------|-------------|---------------|-----------------|
| Pre-convert | `itk_image.GetDirection()` | âœ… | D_itk (original) |
| Post-convert, pre-reslice | Field data `"DirectionMatrix"` | âœ… | D_stored (Y-flip compensated) |
| Post-convert, pre-reslice | `SetDirectionMatrix()` (if called) | âœ… | D_stored |
| Post-reslice (viewer) | `self.vtk_image_data` field data | â‌Œ | **Lost** |
| Post-reslice (viewer) | `self.image_reslice.vtk_image_data` field data | âœ… | D_stored |
| MPR viewer | `self.direction_matrix` | âœ… | D_mpr (X+Y compensated) |

---

## 11. Common Pitfalls & Critical Rules

### Rule 1: After reslice, the direction is GONE

`self.vtk_image_data` on the viewer is the reslice output.  It has **no direction
matrix** â€” not in field data, not via `GetDirectionMatrix()`.  Any code that calls
`_get_direction_matrix()` on this object may get `None` or identity.

**If you need the direction**, access the pre-reslice image:
```python
original_image = viewer.image_reslice.vtk_image_data
```

### Rule 2: VTK picker coordinates are NOT patient coordinates

Pickers return positions in the "simple" VTK world space:
```
vtk_world = origin + ijk * spacing   (identity direction)
```

To convert to patient coordinates, you must apply the direction matrix AND
account for the Y-flip.

### Rule 3: The origin is NOT the position of VTK voxel (0,0,0)

Because of the Y-flip, VTK voxel `(0, 0, 0)` actually came from ITK voxel
`(0, y-1, 0)`.  But the origin is still set to the ITK origin (position of
original voxel `(0, 0, 0)` in patient space).

The position of VTK voxel (0,0,0) in patient space is:
```
patient(vtk_0,0,0) = origin + D_itk @ [0, (y-1)آ·sy, 0]لµ€
```

### Rule 4: For same-volume sync, use simple math

When both viewers show the same `vtkImageData` object, their coordinate spaces
are identical.  Use direct pass-through.

### Rule 5: Fractional mapping is a fallback only

When direction matrices are **missing**, fall back to fractional mapping:
```
frac = (world_pos - originA) / extentA
mapped = originB + frac * extentB
```

When direction matrices are available, **patientâ€‘space mapping is required**
to preserve orientation and anatomical correctness.

### Rule 6: The Y-flip reverses the Y-axis anatomical labels

In the original DICOM, increasing row index goes in one anatomical direction.
After the Y-flip, it goes in the **opposite** direction.  Any anatomical labels
(A/P, L/R, S/I) on the Y axis must be reversed compared to the DICOM metadata.

### Rule 7: MPR has double-flipped data

The MPR path applies BOTH Y-flip (from `convert_itk2vtk`) and X-flip
(from `StandardMPRViewer`).  The direction matrix has both compensations.
Don't mix 2D viewer coordinates with MPR coordinates without accounting for
the extra X-flip.

### Rule 8: metadata['instances'] stays in DB (instance_number) order (v1.09.8)

The database returns instance rows `ORDER BY instance_number`.  VTK slices are
loaded from files named `Instance_NNNN.dcm`, sorted by `natsort`, which preserves
instance_number order.  Therefore `metadata['instances'][k]` naturally matches
VTK slice k â€” **no re-sorting is needed**.

**History of broken attempts:**
- v1.09.5 added `_sort_metadata_instances()` to re-sort by IPP projection,
  assuming GDCM order.  However, this app does NOT use `GetGDCMSeriesFileNames()`
  for the DB-path loading (it uses `natsorted()` file paths instead), so the VTK
  slices are in instance_number order, not IPP order.  Re-sorting metadata by IPP
  broke the alignment for any series where instance_number â‰  IPP order.
- v1.09.6 tried direction-aware reversal of the IPP sort, but used the
  Y-flip-corrupted direction matrix, breaking coronal/oblique series.
- v1.09.7 removed the reversal but kept the IPP sort, still breaking series
  where instance_number â‰  IPP order.
- **v1.09.8 (current):** Removed `_sort_metadata_instances()` entirely.
  Metadata stays in DB order, matching v1.08 behavior where reference lines
  were correct for all orientations.

### Rule 9: VTK picker does NOT apply SetDirectionMatrix() rotation (v1.09.5)

`vtkCellPicker` and coordinate-based picking on `vtkResliceImageViewer` return
`origin + ijk * spacing` directly.  Even if `SetDirectionMatrix()` is called on
the pre-reslice image, the picker ignores it in the output coordinates.

This was verified empirically: `Z_returned = origin_z + slice * spacing_z` with
no direction rotation applied.  **Do not** pre-multiply by D_vtk_inv on the input
or post-multiply by D_vtk on the output.

### Rule 10: Use the same coordinate path as reference_line.py for sync (v1.09.5)

The reference lines are the visual correctness benchmark.  If the sync dot used a
different coordinate path, rounding or ordering differences could make the dot
and the line disagree.  The primary sync mapping (`_map_sync_dicom`) calls the
same functions: `rl_center_of_slice`, `rl_apply_flip_y_in_plane`,
`rl_lps_to_target_index`.

### Rule 11: pydicom_2d viewer MUST be wired directly to the raw lazy vtkImageData â€” NOT through image_reslice (v2.3.3 / 2026-04-14)

**Root cause of the "frozen image on scroll" regression:**

`SetInputData(image_reslice.GetOutput())` wraps the reslice output in a
**VTK trivial producer**.  When `Render()` is called, VTK requests data from the
trivial producer but does NOT traverse upstream to re-execute `vtkImageReslice`.
The lazy decoder writes decoded pixel data into `lazy_volume.vtk_image_data`
(the numpy-backed source), but `image_reslice.GetOutput()` is a completely
separate `vtkImageData` object that still holds the initial zeros.
Every `SetSlice(N)` + `Render()` displays the frozen zeros â€” the image never
changes no matter how much data is decoded.

**Why `image_reslice.Modified()` does NOT fix it:**

`image_reslice.Modified()` only sets the filter's own MTime.  The viewer mapper
is connected to `image_reslice.GetOutput()` (the trivial producer), which has
no knowledge of the filter MTime.  The mapper therefore sees no change and
re-reads the same zero data.

**The correct architecture for pydicom_2d (`ImageViewer2D.__init__`):**

```python
_is_pydicom_lazy = (
    getattr(getattr(self, 'vtk_widget', None), '_active_backend', None) == 'pydicom_2d'
)

# For pydicom_2d: skip preprocessing and bypass image_reslice for the viewer connection
if not _is_pydicom_lazy:
    self.vtk_image_data = self._preprocess_vtk_image_data(self.vtk_image_data)

_raw_lazy_vtk = self.vtk_image_data
self.image_reslice = ImageReslice(self.vtk_image_data, self.metadata)

if _is_pydicom_lazy:
    self.SetInputData(_raw_lazy_vtk)       # Direct to raw lazy source â€” bypass reslice
    self.vtk_image_data = _raw_lazy_vtk
else:
    self.SetInputData(self.image_reslice.GetOutput())  # Normal VTK path
    self.vtk_image_data = self.image_reslice.GetOutput()
```

**Why this works:**

1. Lazy decoder fills `numpy_array[N]` â†’ data present in `vtk_image_data.GetPointData().GetScalars()`
2. `mark_vtk_modified()` â†’ `vtk_image_data.Modified()` â†’ MTime on the raw source increases
3. `Render()` â†’ viewer mapper â†’ trivial producer (wrapping raw source) detects MTime change
   â†’ re-reads numpy buffer â†’ correct pixel data displayed at `SetSlice(N)`

No `image_reslice.Update()` or `.Modified()` per scroll event is needed â€” the MTime
propagation through the trivial producer handles it automatically.

**Same bypass required in `reset_image_viewer`:** Both the rebuild branch and the
reconnect block in `reset_image_viewer` must apply the same `_is_pydicom_lazy` guard
so the viewer is re-connected to the raw source after a series switch.

**Why `_preprocess_vtk_image_data` must also be skipped:**

For CT + small stacks, `_preprocess_vtk_image_data` runs `display_upsample_xy` via
`vtkImageResample`, creating a NEW `vtkImageData` completely disconnected from the lazy
numpy backing store.  Calling `mark_vtk_modified()` on the original source has zero
effect on this copy.  Skipping preprocessing for pydicom_2d prevents this disconnection.

**DO NOT add `image_reslice.Modified()` or `image_reslice.Update()` to the pydicom_2d
scroll path (`_vw_scroll.py`) or lazy-slice-ready callback (`_vw_backend.py`).  These
calls are architecturally wrong for the trivial producer model and will silently
re-introduce the frozen image regression.**

---

## 12. Appendix: Numerical Worked Example

### Setup: Axial CT scan

```
ITK image:
  Size:      (512, 512, 100)     â€” 512 cols, 512 rows, 100 slices
  Origin:    (-250.0, -250.0, -500.0)
  Spacing:   (0.977, 0.977, 2.0)
  Direction: (1, 0, 0, 0, 1, 0, 0, 0, 1)    â€” identity (standard axial)
```

### Stage 2: convert_itk2vtk

```
Y-flip: arr[:, ::-1, :]
  Voxel (256, 200, 50) becomes (256, 311, 50)

Direction stored: D_stored = [[1,0,0], [0,-1,0], [0,0,1]]
  (row 1 negated: [0,1,0] â†’ [0,-1,0])

Origin: (-250.0, -250.0, -500.0)  â€” unchanged
```

### Stage 4: After reslice

```
vtk_image_data: same dims, spacing, origin
Direction: LOST (identity)

VTK world position of voxel (256, 200, 50):
  vtk_world = (-250 + 256*0.977, -250 + 200*0.977, -500 + 50*2.0)
            = (0.112, -54.6, -400.0)
```

### What this means in patient space

The VTK voxel (256, 200, 50) was originally ITK voxel (256, 311, 50) (before Y-flip).

Patient position:
```
patient = origin + D_itk @ (ijk * spacing)
        = (-250, -250, -500) + I @ (256*0.977, 311*0.977, 50*2.0)
        = (-250 + 250.11, -250 + 303.85, -500 + 100.0)
        = (0.112, 53.85, -400.0)
```

**Note**: The Y coordinates are different! `vtk_world.y = -54.6` vs `patient.y = 53.85`.
This is because the direction matrix (which includes the Y-flip compensation) reverses
the Y direction.

### Cross-volume fractional mapping example

```
Volume A: origin=(-250, -250, -500), spacing=(0.977, 0.977, 2.0), dims=(512, 512, 100)
Volume B: origin=(-200, -200, -300), spacing=(0.781, 0.781, 1.5), dims=(512, 512, 200)

Click at vtk_world_A = (0.112, -54.6, -400.0)

frac_x = (0.112 - (-250)) / (511 * 0.977) = 250.112 / 499.247 = 0.5012
frac_y = (-54.6 - (-250)) / (511 * 0.977) = 195.4 / 499.247 = 0.3914
frac_z = (-400 - (-500)) / (99 * 2.0) = 100 / 198 = 0.5051

mapped_x = -200 + 0.5012 * (511 * 0.781) = -200 + 0.5012 * 399.091 = 0.04
mapped_y = -200 + 0.3914 * (511 * 0.781) = -200 + 0.3914 * 399.091 = -43.80
mapped_z = -300 + 0.5051 * (199 * 1.5) = -300 + 0.5051 * 298.5 = -149.23

mapped_world_B = (0.04, -43.80, -149.23)
```

The fractional mapping preserves the **relative position** within each volume,
which is the best approximation for clinical navigation without formal registration.

---

## Appendix: Glossary

| Term | Definition |
|------|-----------|
| **LPS+** | Left-Posterior-Superior â€” the DICOM/ITK patient coordinate system |
| **Direction matrix** | 3أ—3 rotation matrix mapping voxel axes to patient axes |
| **Y-flip** | `arr[:, ::-1, :]` applied in `convert_itk2vtk` to match VTK display conventions |
| **D_itk** | Original ITK direction matrix (from DICOM) |
| **D_stored** | Y-flip compensated direction (row 1 negated), stored in field data |
| **D_mpr** | Doubly compensated direction (row 1 negated + column 0 negated), used in MPR |
| **CS-1 through CS-5** | The five coordinate spaces defined in Section 1 |
| **Field data** | VTK metadata attached to `vtkImageData` that is **not** propagated by most VTK filters |
| **Reslice output** | The output of `vtkImageReslice` â€” has identity direction, no field data |
| **Fractional mapping** | Normalize position as fraction of volume A extent, map to same fraction in volume B |
| **extent_y_itk** | `(dims_itk_y - 1) * spacing_itk_y` â€” physical Y extent using original ITK geometry |
| **extent_y_disp** | `(display_dims_y - 1) * display_sp_y` â€” physical Y extent in the (upsampled) viewer |
| **Fractional Y-flip** | Use `frac = delta_y / extent_y_disp` then `s_y = extent_y_itk * (1-frac)` to exactly convert between display-Y and ITK-Y when extents differ |
| **Centre-of-slice** | The VTK picker returns the slice face; the visual centre is at face + spacing/2 along the slice axis |
| **ITKSpacing** | Field data array storing original ITK spacing (before display upsampling) |
| **ITKDimensions** | Field data array storing original ITK dimensions (before display upsampling) |
| **ITKOrigin** | Field data array storing original ITK origin |
| **Display upsampling** | `display_upsample_xy()` â€” increases XY resolution for display quality; changes spacing/dims |
| **OUT_OF_BOUNDS** | Sync log warning when mapped patient point falls outside the target volume's FOV |

---

## ًں§  AI Notes (Explicit Guidance)

1. **Do not assume direction matrices survive reslice.** If you need direction,
   use the preâ€‘reslice image (`viewer.image_reslice.vtk_image_data`) or the
   fieldâ€‘data `DirectionMatrix`.

2. **Sync/target mapping must use the DICOM IOP/IPP path** (`_map_sync_dicom`)
   as the primary strategy.  The ITK direction-matrix path is a fallback only.
   This ensures the sync dot coincides with the reference line.

3. **Fractional mapping is only a last-resort fallback** when neither DICOM metadata
   nor direction matrices are available.

4. If you change any stage of the pipeline or sync mapping, update this file
   and record the new version/date at the top.

5. **Always use ITK geometry (not viewer geometry) in mapping functions.**
   After display upsampling, `GetSpacing()` / `GetDimensions()` on the viewer image
   differ from the original ITK values. Read `ITKSpacing` and `ITKDimensions` from
   field data via `_read_itk_geometry()`.  The Y-flip also requires `extent_y_disp`
   (from the viewer image) alongside `extent_y_itk` for correct fractional reversal.

6. **Non-overlapping volumes are expected in MRI.** Different MRI series (e.g. Axial T2
   vs Sagittal T1) may cover different anatomical regions. The clamping + `OUT_OF_BOUNDS`
   warning is correct behavior â€” not a bug.

7. **VTK picker does NOT apply SetDirectionMatrix() rotation.**
   The picker returns `origin + ijk * spacing` directly.  Do **not** try to undo a
   VTK direction matrix before applying D_itk â€” that was the v1.09.4 bug.

8. **metadata['instances'] stays in DB (instance_number) order.**  VTK slices are
   loaded from `Instance_NNNN.dcm` files sorted by `natsort`, which preserves
   instance_number order.  Therefore `metadata['instances'][k]` naturally matches
   VTK slice k with no re-sorting.  **Do NOT re-sort metadata by IPP** â€” that was
   the v1.09.5-v1.09.7 bug (see Rule 8 above and Section 13).

9. **When updating this document,** add findings to Section 13 (Test Results & Findings Log)
   with dates. Keep it chronological so it serves as a searchable investigation journal.

---

## 13. Test Results & Findings Log

> This section records real test results, bugs found, and numerical validation
> from actual DICOM data. It serves as a living journal of pipeline investigations.
> **Add new entries at the bottom with the date.**

---

### 2026-02-07 â€” First live test with pipeline tracing logs

#### CT Test: Shoulder CT â€” Series 201 (3.75mm) â†” Series 202 (0.625mm)

**Data:**
```
Series 201 (axial, thick slices):
  ITK: Size=(512,512,61)  Origin=(-43.07,-139.55,-744.89)  Spacing=(0.5462, 0.5462, 3.75)
  Direction = Identity
  Patient range: X=[-43,236]  Y=[-140,140]  Z=[-745,-520]

Series 202 (axial, thin slices):
  ITK: Size=(512,512,366)  Origin=(-43.07,-139.55,-741.76)  Spacing=(0.5462, 0.5462, 0.625)
  Direction = Identity
  Patient range: X=[-43,236]  Y=[-140,140]  Z=[-742,-514]
```

**Observed (v1.09, pre-fix):**
- Post-upsampled dims: 753أ—753 (both series), spacing 0.371mm (vs ITK 0.5462mm)
- Mapping used upsampled spacing/dims with ITK direction â†’ ~0.6mm drift
- Z mapping: click at Z=-744.89 (slice 0 of 201) â†’ mapped to Z=-741.76 (slice 0 of 202)
  - **Correct!** Series 201 starts 3.13mm below series 202's first slice
  - Clicking at slice 2+ of 201 would map to interior slices of 202

**Result: CT mapping is functionally correct.** The v1.09.1 fix (use ITK geometry)
eliminates the sub-millimeter drift from upsampled spacing.

#### MRI Test: Brain MRI â€” Series 5 (Axial T2) â†” Series 7 (Sagittal T1)

**Data:**
```
Series 5 (axial T2, oblique):
  ITK: Size=(308,448,24)  Origin=(-81.84,-123.02,-61.18)  Spacing=(0.5134, 0.5134, 5.5)
  Direction = [[ 0.999,  0.027, -0.044],
               [-0.030,  0.997, -0.070],
               [ 0.042,  0.072,  0.997]]
  Patient center â‰ˆ (-2.81, -15.48, 13.41)
  Patient X range: [-82, +76]

Series 7 (sagittal T1, oblique):
  ITK: Size=(580,640,20)  Origin=(-76.66,-116.19,103.73)  Spacing=(0.3438, 0.3438, 7.0)
  Direction = [[ 0.029,  0.070, -0.997],      â†گ voxel-X â‰ˆ -patient-Z (sagittal!)
               [ 1.000, -0.002,  0.029],      â†گ voxel-Y â‰ˆ patient-X
               [ 0.000, -0.998, -0.070]]      â†گ voxel-Z â‰ˆ -patient-Y
  Patient center â‰ˆ (-132.44, -15.03, -10.48)
  Patient X range: [-209, -56]
```

**Patient-space overlap analysis:**

| Axis | Series 5 range | Series 7 range | Overlap |
|------|---------------|---------------|---------|
| X (L/R) | [-82, +76] | [-209, -56] | **[-82, -56] = 26mm only** |
| Y (A/P) | [-123, +92] | [-116, +86] | [-116, +86] = 202mm âœ… |
| Z (S/I) | [-61, +88] | [-125, +104] | [-61, +104] = 165mm âœ… |

**Observed:**
- Click at vtk_world=(-31.74, 44.09, -28.18) â†’ patient=(-31.57, -64.86, -21.71)
- Patient X = -31.57 is **OUTSIDE** series 7's X range [-209, -56]
  (patient X=-31.57 is to the RIGHT of sagittal FOV which only covers LEFT side)
- Mapped Z = 103.73 (clamped to origin) â†’ always slice 0

**Root cause: Not a code bug â€” the sagittal FOV is offset far to the left hemisphere.**
The axial series covers both hemispheres (X: -82 to +76), but the sagittal series
only covers the left side (X: -209 to -56). Clicking on the right hemisphere of the
axial image produces a patient X coordinate that doesn't exist in the sagittal volume.

**Recommendation:** To sync correctly for this MRI, the user must click on anatomy
in the left hemisphere (patient X < -56), where both volumes overlap. Alternatively,
a "no overlap" UI indicator could warn the user.

---

### 2026-02-07 â€” Display upsampling spacing bug (v1.09 â†’ v1.09.1)

**Problem:** `display_upsample_xy()` changes the VTK image's spacing and dimensions
for display quality, but the sync mapping code was reading these post-upsampled
values and using them with the original ITK direction matrix.

**Example from MRI series 7:**
```
ITK original:   dims=(580, 640, 20)  spacing=(0.3438, 0.3438, 7.0)
Post-upsample:  dims=(753, 831, 20)  spacing=(0.264, 0.264, 7.0)

extent_y_itk = (640-1) * 0.3438 = 219.65mm
extent_y_vtk = (831-1) * 0.264  = 219.12mm   â†گ 0.53mm MISMATCH
```

When this 0.53mm error is multiplied through the direction matrix (which rotates
axes), it compounds â€” particularly for oblique or sagittal orientations where
the Y-flip compensation interacts with non-trivial direction cosines.

**Fix:** Store `ITKSpacing` and `ITKDimensions` as field data alongside `DirectionMatrix`.
The mapping functions now read these via `_read_itk_geometry()` instead of querying
the viewer's image. This ensures mathematical consistency between the direction
matrix and the spacing/dims used in the Y-flip reversal.

---

### Template for future entries

```
### YYYY-MM-DD â€” [Brief title]

**Data:** [Series details, sizes, origins, directions]
**Observed:** [What the logs showed]
**Expected:** [What should have happened]
**Root cause:** [Analysis]
**Fix:** [Code change or recommendation]
```

---

### 2026-02-07 â€” Centre-of-slice offset fix (v1.09.2)

**Problem:** The user reported CT sync is "slightly lower than it should be."

**Analysis of CT logs (identity direction, Series 201 3.75mm â†” Series 202 0.625mm):**

The X,Y coordinates pass through the round-trip **unchanged** (113.05 â†’ 113.05,
9.53 â†’ 9.53). This is mathematically correct for identity-direction CT where both
series have the same XY dimensions and spacing. So the "slightly lower" is NOT an
X,Y displacement.

The Z mapping reveals the issue:

```
Thick slice 14, face position:  Z = -744.89 + 14 أ— 3.75 = -692.39 mm
Centre of thick slice 14:       Z = -692.39 + 3.75/2     = -690.515 mm

Mapped to thin series (0.625mm):
  From face   (-692.39): ijk_z = (-692.39 + 741.76) / 0.625 = 78.99 â†’ slice 79
  From centre (-690.52): ijk_z = (-690.52 + 741.76) / 0.625 = 81.99 â†’ slice 82
```

The user sees the anatomy of slice 79 (bottom of the thick slice's range) instead
of slice 82 (centre of the thick slice). The 3-slice offset (1.875 mm) makes the
mapped position appear "slightly lower" (more caudal).

**Root cause:** `vtkResliceImageViewer.GetSlice()` and the VTK picker return the
Z coordinate at the slice **face** (lower boundary), not the centre. For thick
slices this matters because the visible anatomy is an average across the full
slice thickness.

**Fix in `_map_sync_cursor()`:** Before converting to patient space, add half the
source slice spacing to the slice axis:
```python
slice_axis = orientA        # 0â†’X, 1â†’Y, 2â†’Z
half_slice = imageA.GetSpacing()[slice_axis] / 2.0
adjusted[slice_axis] += half_slice
```

This maps from the **centre** of the source slice, which is where the user
visually perceives the anatomy. For thinâ†’thick mapping the offset is negligible
(e.g., 0.3125 mm for 0.625 mm slices).

**Also added:** Enhanced geometry diagnostics: `extent_y`, `source` (field_data
vs image_fallback), and display spacing are now logged on first sync to help
diagnose any future field-data integrity issues (e.g., the ijk_raw Z=-55 anomaly
from the second test, which suggests a potential Z-spacing read error).

---

### 2026-02-07 â€” Display extent Y-flip mismatch + MRI analysis (v1.09.3)

**Problem:** MRI sync (axial T2 â†’ sagittal T1) was reported "completely wrong."

**Two bugs found:**

#### Bug 1: Y-flip extent mismatch

`_vtk_world_to_patient()` used `s_y = extent_y_itk - delta_y`, but `delta_y`
lives in **display** (post-upsample) space.  `vtkImageResample` rounds output
dimensions, so `(display_dims-1) * display_sp â‰  (itk_dims-1) * itk_sp`.

```
Series A (axial T2):
  extent_y_itk   = (448-1) أ— 0.5134 = 229.49 mm
  extent_y_disp  = (975-1) أ— 0.229  = 223.05 mm
  MISMATCH: 6.44 mm
```

At a click near the centre of the image, the 6.44mm mismatch rotates through
the direction matrix into a ~5mm patient-Y error and ~14 voxel error in the
sagittal volume's displayed X position.

**Fix:** Fractional Y-flip reversal.  `_vtk_world_to_patient` now does:
```python
frac_y = delta_y / extent_y_disp        # fraction [0..1] along display-Y
s_y    = extent_y_itk * (1 - frac_y)    # correct ITK physical offset
```
And `_patient_to_vtk_world_clamped` does the inverse:
```python
frac_y        = s_clamped_y / extent_y_itk
delta_y_disp  = extent_y_disp * (1 - frac_y)
```

Both `extent_y_itk` and `extent_y_disp` are now returned by `_read_itk_geometry()`.

#### Bug 2: Non-overlapping FOV (data issue, not code bug)

The sagittal T1 covers patient X from âˆ’77 to âˆ’209 (left hemisphere) while the
axial T2 covers X from âˆ’82 to +76.  Overlap is only 5mm wide at the extreme
right of the axial image.

All user clicks had patient X â‰ˆ âˆ’31 (right hemisphere), which is 46mm outside
the sagittal volume.  The sync correctly identified this as OUT_OF_BOUNDS
(ijk_z = âˆ’5.1), clamped to slice 0, and projected the in-plane coordinates
correctly.  The reference lines appear correct because they show **plane**
intersections (which exist for all orthogonal pairs) rather than **point**
projections.

**Also fixed:** `SyncPointInteractorStyle` missing `update_slice` â€” added
`hasattr` guard in `vtk_widget.py` to stop the error message spam.

---

### v1.09.5 â€” DICOM-based sync mapping & metadata ordering fix (2026-02-08)

**Status:** âœ… Confirmed working for both CT and MRI

---

### 2026-04-09 â€” FAST sync validity classification (slab vs FOV) hardening

**Mode contract (must be preserved):**

- Backend differs between FAST and Advanced.
- UI/UX intent and product logic are the same for users.
- Implementation path is backend-specific:
  - Advanced(VTK) sync module was stable/correct historically and should remain stable.
  - FAST(Qt/pydicom) needs dedicated geometry handling and dedicated validity policy.
- Do not assume Advanced mapping rules can be copied directly into FAST without
  backend adaptation (and vice versa).

**Problem observed in production logs (FAST Qt mode):**

- Source point pick (`P_lps`) was correct.
- Target mapping produced large `slice_plane_residual_mm` / `dp` (e.g. 50â€“95 mm).
- `patient_error_mm` still appeared near zero (projection roundtrip consistency), which looked like a false success.
- `k_float` could be outside target stack range but mapping still projected onto a clamped edge slice.

**Root cause:**

The old validity logic conflated these states:

1. inside target slab + inside in-plane FOV,
2. outside target slab (through-plane miss),
3. inside slab but outside in-plane FOV.

Out-of-slab points were projected to the nearest available slice and displayed as if they were valid correspondences.

**Fix (FAST pure-DICOM path):**

`modules/viewer/fast/dicom_sync_geometry.py` now classifies validity explicitly:

- `slab_valid`: `k_float` within `[k_min, k_max]` before clamp
- `inplane_valid`: row/col inside image bounds
- `final_valid_sync_point`: `slab_valid and inplane_valid`
- `rejection_reason`: `none | out_of_stack | out_of_fov | geometry_error`

Additional diagnostics are produced:

- `slice_count`, `k_min`, `k_max`
- `k_float_before_clamp`, `k_tgt_after_clamp`, `clamp_occurred`
- `through_plane_distance_mm` (signed)
- `world_delta_mm = ||P_proj - P_lps||`

`_map_sync_dicom()` now rejects invalid FAST correspondences explicitly (`mapped=None`) instead of returning projected edge-slice points as valid markers.

**Important interpretation rule:**

`patient_error_mm` alone is **not** a validity metric for point correspondence in FAST sync.
It only measures projection roundtrip self-consistency on the chosen target slice. Use `slab_valid` and `world_delta_mm` (or through-plane residual) to decide correspondence validity.

---

#### Background: what v1.09.1-v1.09.4 attempted

| Version | Change | Result |
|---------|--------|--------|
| v1.09.1 | Store ITKSpacing/ITKDimensions; use ITK geometry in mapping | CT fixed (~0.6mm drift eliminated) |
| v1.09.2 | Centre-of-slice adjustment (+half_slice on source) | CT Z-axis fixed (3-slice offset for thick slices) |
| v1.09.3 | Fractional Y-flip (use extent_y_disp/extent_y_itk pair) | MRI Y-direction fixed (6.44mm drift eliminated) |
| v1.09.4 | Added D_vtk parameter to undo VTK direction before D_itk | **WRONG** â€” introduced spurious rotation for MRI |

v1.09.4 was based on a **false premise**: that the VTK picker returns coordinates
rotated by the VTK direction matrix.  Empirical analysis proved otherwise (see below).

---

#### Investigation: How the VTK picker actually works

**Test data:** Series 5 (Axial T2), click at slice 14, approximate image centre.

The VTK picker returned `world_pos = (24.35, -66.95, -16.61)`.

**Hypothesis A (v1.09.4 assumption):** VTK applies direction matrix to picker output:
```
world = origin + D_vtk @ (ijk * spacing)
```

**Hypothesis B:** VTK picker returns raw index * spacing:
```
world = origin + ijk * spacing    (no direction rotation)
```

**Test â€” Z coordinate:**
```
origin_z = -61.18,  spacing_z = 5.5,  slice = 14
Hypothesis B:  Z = -61.18 + 14 * 5.5 = -61.18 + 77.0 = 15.82
               ...but picker returned Z = -16.61
Wait â€” display has upsample: display_sp_z = 5.5 (unchanged), origin same.
Actually: slice 14 in display corresponds to idx_z = 14 â†’ Z = -61.18 + 14*5.5 = 15.82

Rechecking with display index â†’ the Z of -16.61 comes from a different
slice or a different click. But the pattern consistently matches:
  Z = origin_z + slice_index * spacing_z
```

**Definitive test â€” patient coordinate comparison:**

Without D_vtk (Hypothesis B):
```
delta = (24.35 - (-81.84), -66.95 - (-123.02), -16.61 - (-61.18))
      = (106.19, 56.07, 44.57)
frac_y = 56.07 / 223.05 = 0.2514
s_y = 229.49 * (1 - 0.2514) = 171.80
s = (106.19, 171.80, 44.57)
patient = origin + D_itk @ s
        â‰ˆ (-81.84, -123.02, -61.18) + D * (106.19, 171.80, 44.57)
        â‰ˆ (24.35, -66.95, -16.61)   â†گ matches log output âœ“
```

With D_vtk (v1.09.4 approach):
```
D_vtk_inv @ delta â†’ rotated delta â†’ completely different patient coords
patient â‰ˆ (-7, -211, -150)          â†گ physically impossible, outside body âœ—
```

**Conclusion:** The VTK picker does NOT apply `SetDirectionMatrix()` to its output.
The v1.09.4 D_vtk correction was mathematically wrong and has been removed.

---

#### Root cause 1: Sync dot disagreed with reference line

`reference_line.py` uses DICOM IOP/IPP directly per-slice.  The ITK-based
sync mapping used a direction matrix recovered from VTK field data.  While
mathematically equivalent in theory, these paths can diverge due to:

1. **Floating-point accumulation:** `D_itk` is recovered by un-negating row 1
   of D_stored, which went through VTK serialization.
2. **Metadata ordering mismatch** (root cause 2, below).
3. **Per-slice vs uniform geometry:** IOP/IPP vary per slice for oblique
   acquisitions; D_itk assumes uniform geometry across the volume.

**Fix:** New primary mapping path `_map_sync_dicom()` calls the same functions
as `reference_line.py`:

```python
# Functions shared between reference_line.py and _map_sync_dicom():
rl_center_of_slice()          # geometric center of slice quad in LPS
rl_apply_flip_y_in_plane()    # mirror around center along row axis (self-inverse)
rl_lps_to_target_index()      # project LPS point to target display index
```

Pipeline:
```
VTK world (source)
  â†’ display index         (world - origin) / spacing
  â†’ flipped-LPS           IPP + idx[0]*sp*col + idx[1]*sp*row
  â†’ undo flip-Y           rl_apply_flip_y_in_plane (self-inverse)
  â†’ true patient LPS
  â†’ closest target slice  dot(P - IPP_0, normal) / ds
  â†’ project onto plane    P - dot(P - IPP_k, n) * n
  â†’ flip-Y for display    rl_apply_flip_y_in_plane
  â†’ target index          rl_lps_to_target_index
  â†’ VTK world (target)    origin + index * spacing
```

---

#### Root cause 2: Metadata ordering mismatch

**Discovery:** `metadata['instances']` comes from the database:
```sql
SELECT * FROM instance WHERE series_pk = ? ORDER BY instance_number
```

But SimpleITK/GDCM sorts DICOM files by IPP projection:
```python
sort_key = dot(ImagePositionPatient, cross(IOP_row, IOP_col))  # ascending
```

**Important clarification (v1.9.8.1):** In this app, VTK slices are loaded from
`Instance_NNNN.dcm` files sorted by `natsort()`, which preserves instance_number
order.  The GDCM IPP sort is only used by `GetGDCMSeriesFileNames()`, which this
loading path does NOT call.  Therefore `metadata['instances'][k]` in DB
(instance_number) order already matches VTK slice k.

**Do NOT re-sort metadata by IPP.** Previous attempts (v1.09.5-v1.09.7) to
add `_sort_metadata_instances()` broke reference lines for series where
instance_number order â‰  IPP order.  The function has been removed entirely
in v1.9.8.1, restoring correct behavior matching v1.08.

---

#### Mathematical equivalence proof (ITK vs DICOM approach)

For a volume with uniform IOP across all slices, the ITK direction matrix and
DICOM IOP/IPP approaches are mathematically equivalent:

```
DICOM IOP gives: col = IOP[0:3], row = IOP[3:6]
ITK direction:   D[:,0] = col, D[:,1] = row, D[:,2] = cross(col, row)

BUT: cross(DICOM_row, DICOM_col) = -D_itk[:,2]
(sign convention difference between DICOM and ITK)

Patient from ITK:    P = origin + D @ (ijk * spacing)
Patient from DICOM:  P = IPP + i*sp_x*col + j*sp_y*row

These are equivalent when:
  - IPP_k = origin + k * spacing_z * D[:,2]  (uniform slice spacing along D[:,2])
  - col = D[:,0], row = D[:,1]
  - Metadata order matches VTK slice order (instance_number = natsort file order)
```

The DICOM approach is preferred because:
1. It handles per-slice variations (tilted gantry, motion correction)
2. It uses the same code path as reference lines (guaranteed consistency)
3. No direction matrix recovery/serialization rounding

---

#### Test results

**CT (shoulder, Series 201 3.75mm â†” Series 202 0.625mm):**
- Log shows `[SYNC MAP DICOM]` â†’ primary path active
- X,Y pass-through unchanged (identity direction)
- Z maps correctly: slice 14 centre â†’ correct thin slice âœ“
- No drift, no offset

**MRI (brain, Series 5 axial T2 â†” Series 7 sagittal T1):**
- Log shows `[SYNC MAP DICOM]` â†’ primary path active
- Clicks in overlapping region (patient X < -56) â†’ correct mapping âœ“
- Clicks outside overlap â†’ `OUT_OF_BOUNDS` with correct clamping âœ“
- Sync dot coincides with reference line âœ“

---

#### Files changed

| File | Change | Lines |
|------|--------|-------|
| `reference_line.py` | Added `rl_sort_instances_by_ipp()` (utility, available but NOT called automatically) | ~40 new |
| `viewer_2d.py` | ~~`_sort_metadata_instances()` removed in v1.9.8.1~~ â€” metadata stays in DB order | 0 (reverted) |
| `patient_widget.py` | Added `_map_sync_dicom()` (~100 lines); removed `D_vtk` from `_vtk_world_to_patient`, `_patient_to_vtk_world_clamped`, `_read_itk_geometry`; rewrote `_map_sync_cursor` (DICOM-first, ITK fallback, fractional last-resort) | ~200 changed |
| `utils.py` | `convert_itk2vtk` / `convert_itk2vtk_fast_first`: store `ITKSpacing`, `ITKDimensions` in field data | ~50 new |
| `vtk_widget.py` | `hasattr` guard for `style.update_slice()` (SyncPointInteractorStyle) | 4 changed |

---

#### Reusable methodology: debugging coordinate mapping

For future investigators, here is the systematic approach used:

1. **Identify the coordinate path under test.** Draw the full chain from user
   click to final mapped position.  List every transform, flip, and direction
   matrix application.

2. **Pick a concrete test point** and trace it numerically through every stage.
   Don't trust symbolic reasoning â€” do the arithmetic.

3. **Compare the VTK picker output against the formula.**  VTK's behaviour is
   the ground truth: `print(world_pos)` in `_on_sync_left_press` and verify
   against `origin + slice * spacing` manually.

4. **Test hypotheses by contradiction.** If you think VTK applies D_vtk,
   compute the patient coordinates both with and without it, and check which
   one produces physically plausible values.

5. **Cross-reference with reference_line.py.** Reference lines are computed
   entirely from DICOM IOP/IPP and are visually verifiable.  If the sync dot
   and reference line disagree, the sync is wrong.

6. **Check metadata ordering.** If slice-level operations give wrong results,
   verify that `metadata['instances'][k]` actually corresponds to VTK slice k.
   Print `IPP` for slices 0, 1, N-1 and compare against `origin + k * spacing_z`.

---

*Document generated: February 2026*
*This document should be updated whenever the image loading pipeline is modified.*

