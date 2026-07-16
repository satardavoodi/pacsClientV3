# EagleEye MG viewport — multi-image import, view/laterality, annotation binding (2026-07-14)

Investigation + first-stage fixes for three reported EagleEye Mammography viewport
bugs, requested as prerequisites to continuing the 3D Cursor lesion-matching work.

**Files touched (all AI-module-scoped — NOT the shared FAST loader):**
- `modules/ai_imaging/ai_module_ui/overrides/vtk_widget.py` — diagnostics + guard
- `modules/ai_imaging/ai_module_ui/overrides/patient_widget.py` — view/laterality resolver
- Guard test: `tests/code/ai_imaging/test_eagleeye_viewport_fixes.py`

Nothing in `PacsClient/.../image_io.py`, `viewer_2d.py`, the DB, or the FAST viewer
was modified. The architecture separation rule (Fast / Advanced / VTK domains stay
independent) is preserved.

---

## Bug #1 — two images in a single-image MG viewport

### What was ruled OUT (with evidence)

The intuitive theory — duplicate DICOM instances in the DB, or two files on disk —
is **wrong for the reported study (50016)**. Ground truth, read directly from disk
and a copy of the live `dicom.db`:

| series | view | files on disk | DB instance rows | `image_count` |
|---|---|---|---|---|
| 2 | R-CC | **1** | **1** | 1 |
| 4 | L-CC | **1** | **1** | 1 |
| 6 | R-MLO | **1** | **1** | 1 |
| 8 | L-MLO | **1** | **1** | 1 |
| 100000 | (DICOMized doc) | 1 | 1 | 1 |

The data is clean: one file, one instance, `image_count=1` per series. That is
**why the patient tab (FAST, disk-scan) correctly shows one image.**

The reslice reset (`ImageViewer2D.reset_image_viewer`) was also read in full: for a
different series it rebinds `SetInputData(new_volume)` and forces a slice-range
reconnect (`_reslice_data_updated=True`). It is correct for a single-slice volume.

### What that leaves

EagleEye is the **VTK/Advanced** path (it forces `BACKEND_VTK`), and it **reuses**
one `vtkResliceImageViewer` across series switches, unlike the patient-tab FAST
viewer which rebuilds. A viewport can only offer two scrollable images if it was
handed a **Z=2 volume** or a **metadata instance list of length 2** — neither of
which is visible in static analysis when the on-disk/DB data is 1:1. Candidate
runtime sources (any of which produces the symptom): a stale cached
**geometry-index** entry stacking two files, a `db_incomplete` filesystem-fallback
that size-groups two same-dimension views, or a metadata/slider slice-count
mismatch on the reused viewer.

The user's own phrasing — *"the previously loaded image may also be imported into
the new viewport"* — matches the reused-viewer / stale-stack family exactly.

### Why this was not blind-fixed

The exact source is a **runtime condition** that cannot be reproduced from static
analysis with clean data, and every candidate lives in **shared clinical VTK code**
(`image_io.py`, `viewer_2d.py`) whose blast radius is every viewer for every
patient. Editing it on a theory, with no ability to GUI-test, risks a silent
clinical regression. So stage 1 is **instrumentation + a safe, opt-in guard**.

### What shipped

**1. Diagnostics — `_diagnose_mg_volume` (default ON, `AIPACS_MG_VOLUME_DIAG`).**
Logged at both viewport entry points (`start_process_series`, `switch_series`)
through `logging.getLogger(__name__)` — which reaches `user_data/logs/app.log`
(the feature's old `print()`s never did; that is why the first failure had to be
diagnosed by hand). For every MG load it records the incoming volume Z, the
metadata instance count, and the distinct SOP/file counts, flagging the exact bug
signature:

```
[MG][VTK-DIAG] switch_series series=4 L-CC uid=...10012.11 vol_z=2 meta_instances=2
    distinct_sops=2 distinct_files=2  <-- SUSPECT: single-image MG series carrying >1 image
[MG][VTK-DIAG] switch_series files=['Instance_68306.dcm', 'Instance_68304.dcm'] sops=[...]
```

The next real run pins the mechanism precisely — including *which* extra image is
being stacked — turning the remaining fix into a one-line, correctly-targeted edit.

**2. Corrective guard — `enforce_single_image_metadata` (default OFF,
`AIPACS_MG_ENFORCE_SINGLE_IMAGE`).** Enforces the confirmed product invariant *"an
MG series is a single image"* at the viewport boundary: it trims the metadata
instance list to the first image **only when** all of these hold —
modality == MG, the flag is on, and the list has >1 entry **with distinct SOP
UIDs** (genuinely different images stacked together). It is **safe by
construction**: a multi-frame MG series (one file, one SOP, many frames) has a
single distinct SOP and is never touched, and the original metadata dict is not
mutated in place. Default OFF until the diagnostic confirms the mechanism on a live
run — a blind volume/metadata edit could otherwise mishandle a genuine multi-frame
series (tomo/cine), so it is opt-in, not default-on.

---

## Bug #2 — reliable CC/MLO and L/R identification

The identification itself works today (the screenshot shows correct L-MLO / L-CC
labels, read from DICOM at load time). The gap was **robustness**: the CC/MLO
**auto-pair** (`_schedule_mg_mirror`) read laterality/view **only** from series
metadata, so if a center's DICOM populated the tags but the metadata parse left
them blank, auto-pairing silently failed.

`resolve_thumb_lat_view(thumb)` now resolves identity from the most reliable source
in order: **series metadata → the DICOM tags on the first instance**
(`ImageLaterality`/`Laterality`, `ViewPosition`). It never infers from series order
or viewer position, and returns `('', '')` when undeterminable so the caller
**declines to pair** rather than pairing the wrong views. Wired into both the
dropped-series and candidate-scan sides of the auto-pair.

---

## Bug #3 / #4 — annotations appear on all images

**These are downstream of bug #1.** The advanced-2D annotation store
(`abstract_interactorstyle.add_object_to_store_widgets` / `update_slice`) already
keys annotations by the integer `GetSlice()` index and hides them on non-matching
slices — but a **correct single-image MG viewport has exactly one slice (index 0)**,
so there is no other image for an annotation to bleed onto. The cross-image bleed
manifests **only because bug #1 wrongly places two images in one viewport.** Fixing
#1 removes the bleed for the normal single-image case.

Two deeper, separable hardening items are **staged, not done** (they touch shared
render code and need live validation):

- **Annotation identity should be the SOP Instance UID, not the volatile slice
  ordinal.** The correct reference implementation is
  `modules/mpr/zeta_mpr/mpr_measurement_tools.py`, which binds each annotation to a
  stable coordinate captured at creation (`_annotation_slice_coord` +
  `refresh_slice_visibility`). The advanced-2D viewer binds to `GetSlice()`.
- **AI detection boxes / nipple / pectoral / region overlays have no slice binding
  at all** (`viewer_2d.draw_boxes_ijk` adds actors straight to the renderer; the AI
  widget toggles them only globally). For a genuine single-image MG series this is
  correct; it would matter only for a multi-image viewport.

---

## Testing

Guard test `tests/code/ai_imaging/test_eagleeye_viewport_fixes.py` (pure; runs in
the offscreen sandbox lane) — 11 checks against the **real** function source:

- corrective trims 2 distinct-SOP images → 1; **preserves** multi-frame (same SOP);
  leaves single-image / non-MG untouched; does not mutate the original dict;
  flag-off (default) is a no-op.
- resolver returns metadata identity; truncates `LEFT`→`L`; returns `('','')` when
  undeterminable (never a guess); metadata takes priority over a DICOM read.

All 11 behaviours verified green against the real sources.

### NEEDS LIVE VERIFICATION (source build)

1. **Re-open EagleEye on study 50016 and read the new `[MG][VTK-DIAG]` lines in
   `app.log`.** They will state whether the extra image is a Z=2 volume or a
   length-2 metadata list, and name the stacked file — the decisive evidence for
   the final #1 fix.
2. If the signature is confirmed, set `AIPACS_MG_ENFORCE_SINGLE_IMAGE=1` to verify
   the viewport then shows the single intended image, and confirm the annotation
   bleed is gone as a consequence.
3. Confirm CC/MLO auto-pair still works (and now also works when series metadata
   laterality/view is blank but the DICOM tags are present).

---

## Flags

| Flag | Default | Effect |
|---|---|---|
| `AIPACS_MG_VOLUME_DIAG` | **on** | Log incoming MG volume geometry vs instance list |
| `AIPACS_MG_ENFORCE_SINGLE_IMAGE` | **off** | Trim a stacked-image MG series to its one intended image |

Neither file is plugin-mirrored.
