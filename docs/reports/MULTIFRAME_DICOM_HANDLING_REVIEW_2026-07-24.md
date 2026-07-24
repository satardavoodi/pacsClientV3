# Multi-frame DICOM handling — comprehensive review + implementation (2026-07-24)

Scope: how AI-PACS reads, decodes, indexes, and geometrically interprets **multi-frame**
DICOM (a whole series inside ONE file with N internal frames — Enhanced MR/CT, XA/angio,
ophthalmic, cine), while **preserving the standard multi-file series path** used by ~90% of
studies. Ground-truthed against the imported *Charles Walker MRI 2023* study (patient E1026485,
14 Enhanced-MR series) and validated with synthetic spatial / temporal / multi-stack /
multi-dimensional / compressed fixtures.

This extends **OPT-42** in `docs/OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md` (parts 1–2
were the pixel-cache correctness fixes; this is part 3 — geometry). Prior context:
`multiframe_stale_pixel_cache_2026-07-21` memory and CLAUDE.md "FAST multi-frame / cine".

---

## 1. Executive summary

The two structures are already distinguished correctly and must stay that way:

- **Standard series** = many single-frame files, one image per file. Geometry is in each file's
  TOP-LEVEL tags (`ImagePositionPatient`/`...Orientation`/`PixelSpacing`). `entry_from_dataset`
  reads them; the whole geometry stack works. **Unchanged.**
- **Multi-frame series** = ONE file, `NumberOfFrames > 1`. The FAST pipeline already **expands**
  it into N scrollable frames (`_expand_multiframe_slices`) and decodes each frame's own pixels
  (frame-aware decode + cache, fixed in OPT-42 parts 1–2).

**The gap this review found and fixed:** an Enhanced multi-frame file stores its geometry
**entirely in the functional groups and leaves the top-level tags EMPTY**. The expansion copied
the single (absent → default) top-level geometry onto every frame, so all frames got
`IPP=(0,0,0)`, `IOP=identity`, `PixelSpacing=(1,1)`. Frames displayed fine, but **measurements,
the slice-location overlay, and reference lines had no real geometry**, and **MPR would build a
degenerate 1-slice volume**.

**What shipped (default-on, standard series byte-identical):**
1. A pure `multiframe_geometry.py` that reads **per-frame** geometry from the Shared + Per-Frame
   Functional Groups and **classifies** the series (spatial volume / multi-dimensional /
   multi-stack / temporal / unknown).
2. The FAST expansion now **stamps each frame's SliceMeta with its OWN geometry** → measurements,
   overlay, and reference lines become correct for spatial multi-frame; feeds the existing robust
   sync/reference-line engine unchanged.
3. An **MPR eligibility gate**: a single-file multi-frame series can't produce a valid VTK volume
   through the current builder (which documents it must not be handed multi-frame files), so MPR
   is blocked with a clear, classified message instead of generating a degenerate/incorrect MPR.

**Staged (needs live VTK validation):** the actual multi-frame → VTK volume BUILDER that would
let a *spatial* multi-frame series open real MPR.

---

## 2. Ground truth — what the real files actually contain

All 14 *Charles Walker* series are Enhanced MR (`SOPClassUID 1.2.840.10008.5.1.4.1.1.4.1`),
uncompressed (`1.2.840.10008.1.2.1`), each **one file**, with BOTH
`SharedFunctionalGroupsSequence` and `PerFrameFunctionalGroupsSequence`, and **all top-level
`ImagePositionPatient` / `ImageOrientationPatient` / `PixelSpacing` / `SliceThickness` = None**.

| Series | Frames | Structure (from per-frame functional groups) | Classification |
|---|---|---|---|
| 201/301/401/501/601/701/802/803/804/901/1001/1101 | 24–35 | one stack, monotonic per-frame IPP, constant IOP, one StackID | **spatial_volume** (MPR-eligible) |
| 801 (DWI) | 140 | 28 spatial positions × 5 (b-values/directions); frames repeat positions, distinguished by `DimensionIndexValues` | **multi_dimensional** (MPR on one 28-slice sub-stack) |
| 101 (SURVEY) | 20 | 3 stacks with **different IOP per stack** (`StackID` 1/2/3) — a 3-plane localizer | **multi_stack** (not one volume) |

Pixel spacing recovered per series: 0.75 / 0.469 / 0.682 / 0.833 / 0.898 / 1.953 mm — vs the
**1.0 mm default the code used before** (a silent measurement error).

This single study exercises every hard case the request named (spatial volume, cine-like temporal
would be the same file shape with all-equal IPP, multi-stack localizer, multi-dimensional
parametric), so the classifier was designed and tested against all of them.

---

## 3. How multi-frame files are read, decoded, and indexed (current, correct)

- **Detection** (`dicom_header_scan._safe_number_of_frames` / `_expand_multiframe_slices`): a file
  with `NumberOfFrames > 1` is multi-frame. The metadata path only *probes* the single-file case,
  so an ordinary many-file series pays zero extra reads. **A single-frame file and a multi-file
  series are never treated as multi-frame.**
- **Frame indexing**: each frame becomes a `SliceMeta` sharing the file `path` with a distinct
  `frame_index` (0..N-1). Scroll position k ⇒ frame k.
- **Decoding** (`_decode_slice`): `pydicom.dcmread(...).pixel_array` returns `(N,R,C)`; the frame
  is selected as `arr[frame_index]` (NOT `arr[0]`). Works for compressed transfer syntaxes because
  `pixel_array` decompresses all frames (pylibjpeg/RLE), then the frame is indexed.
- **Caching**: in-memory cache is keyed by slice index; the L2 disk cache key carries a
  `::f{frame_index}` suffix + a decode policy tag, so frames never collide and a stale build's
  cache is invalidated (OPT-42 parts 1–2). Background/subprocess prefetch is frame-guarded so it
  can't cache frame 0 under another frame's key (OPT-42 part 2).

Compressed multi-frame is covered by a new RLE test (`test_compressed_multiframe_decodes_each_frame`).

---

## 4. Geometry extraction — the fix

New pure module **`modules/viewer/fast/multiframe_geometry.py`** (stdlib + pydicom only — no
Qt/VTK/DB, fully unit-testable, reusable by both the FAST and VTK domains without coupling them).

- `read_frame_geometries(ds)` merges **Shared** + **Per-Frame** Functional Groups (per-frame wins):
  - `PlanePositionSequence.ImagePositionPatient` → per-frame **IPP**
  - `PlaneOrientationSequence.ImageOrientationPatient` → **IOP** (usually shared)
  - `PixelMeasuresSequence.PixelSpacing / SliceThickness / SpacingBetweenSlices` → **spacing**
  - `FrameContentSequence.StackID / InStackPositionNumber / DimensionIndexValues /
    TemporalPositionIndex` → **stack + dimension** organisation
  - Missing groups yield `None` fields → the caller falls back to legacy/top-level values, so a
    geometry-less US cine never regresses.

**Wiring** (`_expand_multiframe_slices`, flag `AIPACS_FAST_MULTIFRAME_GEOMETRY` default-on): each
frame's `SliceMeta` is stamped with its OWN `ipp/iop/pixel_spacing/slice_thickness/
spacing_between_slices` when present. A frame lacking per-frame geometry keeps the base slice's
value. **Single-frame series and standard multi-file series never enter this path — byte-identical.**
The classification is reset per `open_series` so it can't leak into the next series.

Verified on real data: series 1101 frames now carry distinct IPPs (99.25 → 21.84 → −49.61 mm)
and spacing 0.75 mm; the synthetic single-frame series still reads IPP from top-level with
`frame_index=None` and no classification.

---

## 5. Spatial relationships + classification

`classify_frames(...)` → one of:

- **`spatial_volume`** — one orientation/stack, distinct positions along the normal, consistent
  IOP, ~uniform spacing. MPR-eligible; `volume_frame_indices` = all frames in order.
- **`multi_dimensional`** — distinct positions but many frames share each position (DWI b-values,
  multi-echo, dynamic). MPR-eligible on ONE representative sub-stack (one frame per position,
  chosen deterministically by lowest `DimensionIndexValues`/temporal index).
- **`multi_stack`** — more than one orientation / `StackID` (3-plane localizer). Not a single
  volume; the largest coherent sub-stack is exposed for possible MPR.
- **`temporal`** — every frame at the same location within `position_epsilon_mm` (cine / angio /
  echo loop). Never volumetric → MPR disabled.
- **`unknown`** — multi-frame with no usable per-frame geometry (e.g. a geometry-less US cine).

Validity primitives (all pure): `slice_normal` (None on degenerate IOP), distinct-position
detection, per-group orientation consistency (|dot(normal_i, normal_0)| > 0.999), and uniform-
spacing check (gap deviation < 35 % of the median). `per_frame_geometry_valid` marks whether every
frame carries real geometry (the signal reference lines can trust).

Classifier validated on all 14 real series (table in §2) — every one classified as expected.

---

## 6. Reference lines — the real consumer is `metadata['instances']`, not `SliceMeta`

The FAST sync / reference-line engine (`dicom_sync_geometry.py`) is **already robust**: it computes
the slice normal from IOP (None on degenerate orientation), projects positions along the normal, and
validates slab / in-plane / through-plane before drawing.

**CORRECTION (2026-07-24, "still not working" follow-up):** stamping per-frame geometry into the
pipeline's `SliceMeta` was necessary but **NOT sufficient**. The reference-line / cross-series sync /
slice-location overlay code does **not** read the pipeline `SliceMeta` — it reads per-slice geometry
from **`viewer.metadata['instances']`** (`_pw_sync._geometry_instances_for_viewer`, the overlay
identity/slice reader). That list is built from the **DB**, and a single-file multi-frame Enhanced
series has **one** DB instance row (no per-frame geometry). So the consumers saw ONE geometry-less
"slice" (`len(instances) <= 1` → returned as-is) while the viewport scrolled N frames — reference
lines and the slice-location overlay had nothing usable. The two representations (pipeline slices =
N, metadata instances = 1) had diverged.

**Fix (`AIPACS_MULTIFRAME_SYNC_INSTANCES`, default-on):** the pipeline exports one per-frame instance
dict per frame (`export_frame_instances()` — each with its own `image_position_patient` /
`image_orientation_patient` / `pixel_spacing` / `slice_thickness` / `frame_index`), and the FAST
bridge factory (`_vw_globals._create_qt_viewer_bridge`, right after `open_series`) hands the bridge a
**shallow-copied** metadata whose `instances` is that per-frame list. So every geometry consumer
(reference lines, sync, overlay slice-location) now sees N frames with real per-frame geometry, while
the **shared thumbnail/DB metadata is untouched** (it must keep one instance for download-
completeness — hence the copy, not an in-place mutation). Only replaces when the DB list is shorter
than the true frame count; a standard many-file series exports `[]` → the bridge keeps the original
metadata → **byte-identical**. Frame order is preserved through the sync's stable InstanceNumber sort
(all frames share the file's InstanceNumber).

- **Spatial multi-frame:** correct reference lines + cross-series sync (the robust engine now receives
  real per-frame IPP/IOP).
- **Geometry-less multi-frame** (temporal / unknown): `export_frame_instances` still returns per-frame
  entries, but with the legacy fallback geometry — behaviour is as before (benign single location).

Verified end-to-end on the real study via the app's metadata path (1 DB instance in → 26 per-frame
instances out, 26 distinct positions, correct spacing) and that the sync's instance sort preserves
frame order. `_pw_sync` / geometry / reference tests: 226 passed, 0 new failures.

---

## 7. MPR / reconstruction

**Finding:** the VTK volume builder `image_io.load_vtk_from_dicom_paths` explicitly documents
*"Multi-frame DICOM (single file, N frames): treated as a single instance; caller must not pass
multi-frame files to this function."* So today, opening MPR on a multi-frame series builds a
**1-slice degenerate volume** — an incorrect MPR.

**Gate shipped** (`AIPACS_MPR_MULTIFRAME_GATE` default-on) at the single MPR volume-load funnel
(`_load_vtk_paths_responsive`): if the resolved series is a single multi-frame file,
`multiframe_geometry.classify_series_files` classifies it and MPR aborts cleanly with a specific,
classified message (`_mpr_route_block_message`), instead of constructing a degenerate volume. A
**standard multi-file series (or a single-frame file) is never gated** → ordinary MPR is
byte-identical. This directly satisfies "do not incorrectly generate MPR" and "enable MPR only
where valid geometry exists".

**Staged (not shipped — needs live VTK validation):** a multi-frame-aware VTK volume BUILDER that,
for a `spatial_volume` (or a chosen sub-stack of a `multi_dimensional`) series, expands the N
frames with their per-frame geometry into a real `vtkImageData` so spatial multi-frame MPR renders.
The classifier + `volume_frame_indices` already provide exactly the frame list and ordering this
builder needs; the remaining work is VTK-domain (per the Fast/Advanced/VTK separation rule, it must
be validated on the live source build, default-off until proven).

---

## 8. Orientation / position / spacing / dimensions interpretation

- **Orientation (IOP)**: from `PlaneOrientationSequence` (shared for a single-orientation stack;
  per-frame for a localizer). Drives the slice normal and the pixel↔patient transforms.
- **Position (IPP)**: from per-frame `PlanePositionSequence` — the authoritative per-frame location.
- **Spacing**: in-plane from `PixelMeasuresSequence.PixelSpacing`; through-plane from
  `SpacingBetweenSlices` when present, else derived from the gap between consecutive frame positions
  along the normal.
- **Dimensions**: `FrameContentSequence` (`StackID`, `InStackPositionNumber`, `DimensionIndexValues`,
  `TemporalPositionIndex`) is used to separate stacks and to reduce a multi-dimensional acquisition
  to a single spatial sub-stack. `FrameIncrementPointer` (classic NM/XA multi-frame) is not required
  for the Enhanced files here; it remains a future input for legacy multi-frame that lacks functional
  groups.

---

## 9. Testing

**Standard series (must remain unchanged) — verified:**
- `test_single_frame_series_geometry_is_top_level_and_unchanged`: single-frame file reads top-level
  IPP/spacing, `frame_index=None`, no classification.
- The MPR gate returns None for any multi-FILE list → standard-series MPR path untouched.
- Full geometry/sync/drag/identity viewer suite: **455 passed, 0 new failures**.

**Multi-frame series — verified:**
- Pure module (`test_multiframe_geometry.py`, 9): single/spatial/temporal/multi-stack/
  multi-dimensional/read-merge/no-groups/non-uniform/degenerate-IOP.
- FAST wiring (`test_fast_multiframe.py`): per-frame geometry stamping, classification, frame-aware
  decode, no cross-frame cache collision, subprocess guard, MPR-gate helper, and a **compressed
  (RLE) multi-frame** decode-each-frame test.
- Real-data validation (offscreen scripts): all 14 series classified correctly; per-frame IPP +
  spacing match the pydicom functional groups exactly.

**Modality coverage:** Enhanced MR (real, 14 series) + synthetic spatial volume, temporal cine
(all-equal IPP), 3-plane localizer (multi_stack), DWI-style multi_dimensional, and RLE-compressed
multi-frame. Angiography / ophthalmology follow the same single-file-N-frames shape and are covered
by the temporal/spatial classification (angio cine → `temporal` → MPR disabled; a spatial angio
rotational run would classify `spatial_volume`).

---

## 10. Flags (all default-on; kill switch reverts to byte-identical legacy)

| Flag | Effect when off (`=0`) |
|---|---|
| `AIPACS_FAST_MULTIFRAME` | disable multi-frame expansion entirely (legacy frame-0) |
| `AIPACS_FAST_MULTIFRAME_SUBPROC_GUARD` | prefetch may use the frame-blind subprocess (OPT-42 pt 2) |
| `AIPACS_FAST_MULTIFRAME_GEOMETRY` | frames inherit top-level (absent) geometry — legacy |
| `AIPACS_MPR_MULTIFRAME_GATE` | pass multi-frame to the VTK builder — may build a degenerate volume |

---

## 11. Files

- **New**: `modules/viewer/fast/multiframe_geometry.py` (pure; plugin-mirrored — 418/418).
- **Changed**: `modules/viewer/fast/lightweight_2d_pipeline.py` (expansion stamps per-frame
  geometry; plugin-mirrored — synced); `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/
  toolbar_manager.py` (MPR gate + message; not plugin-mirrored).
- **Tests**: `tests/code/viewer/test_multiframe_geometry.py` (9), additions to
  `tests/code/viewer/test_fast_multiframe.py`.

## 12. Live source-build verification still needed

1. Open the *Charles Walker* study; on a spatial series confirm the slice-location overlay and a
   ruler measurement are now correct (0.75 mm px, not 1.0).
2. With the multi-frame series next to an orthogonal standard series, confirm reference lines fall
   on the correct level.
3. Click MPR on a multi-frame series → the new "MPR not available (multi-frame)" message appears
   (no crash, no 1-slice viewer); click MPR on a standard series → unchanged.
4. Standard multi-file series: scrolling, overlay, reference lines, and MPR all unchanged.
