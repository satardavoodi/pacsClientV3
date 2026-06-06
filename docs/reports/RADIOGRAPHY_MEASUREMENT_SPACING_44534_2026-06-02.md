# Radiography Measurement Error — Root Cause & Fix

**Patient:** 44534 · **Study 738:** DX HAND (projection radiography) · **Date:** 2026-06-02
**Reported by:** vahid · **Symptom:** ruler reads ~10× too large on radiography; correct on CT/MRI.
**Status:** ✅ Fix applied · tests passing (14/14, incl. real 44534) · live-verified in the running app · **build payload mirrored** — 2026-06-02. Build-ready.

---

## TL;DR

The viewer derives physical distance from **`PixelSpacing` (0028,0030) only**, and falls back to a
default of **1.0 mm/px** when that tag is absent. Projection radiography (CR/DX) images, by DICOM
design, **do not carry `PixelSpacing`** — they carry **`ImagerPixelSpacing` (0018,1164)** instead.
Patient 44534's DX hand image has `ImagerPixelSpacing = [0.1, 0.1]` (0.1 mm/px) and no `PixelSpacing`,
so the ruler uses 1.0 mm/px instead of 0.1 mm/px → **exactly 10× over-measurement**.

```
A line the app labels "103 mm"  = 103 px × 1.0 mm/px   (current, wrong)
                                 = 103 px × 0.1 mm/px = 10.3 mm  (corrected)  ✓ ≈ 1 cm
```

CT/MRI are correct because those modalities always carry `PixelSpacing`. The fix is to read pixel
spacing with the **DICOM-standard precedence** `PixelSpacing → ImagerPixelSpacing →
NominalScannedPixelSpacing`. This leaves CT/MRI byte-identical and corrects CR/DX/MG/XA.

---

## 1. Evidence — patient 44534 DICOM headers

Tags dumped directly from the stored instances
(`user_data/patients/dicom/<study_uid>/<series>/Instance_0001.dcm`):

| Tag | DX hand (study 738) | MR (study 762) |
|---|---|---|
| Modality (0008,0060) | `DX` | `MR` |
| Rows × Columns | 2833 × 2035 | 168 × 256 |
| **PixelSpacing (0028,0030)** | **`<ABSENT>`** | `[0.46484, 0.46484]` |
| **ImagerPixelSpacing (0018,1164)** | **`[0.1, 0.1]`** | `<ABSENT>` |
| NominalScannedPixelSpacing (0018,2010) | `<ABSENT>` | `<ABSENT>` |
| DetectorElementSpacing (0018,7022) | `<ABSENT>` | `<ABSENT>` |
| PixelSpacingCalibrationType (0028,0A02) | `<ABSENT>` | `<ABSENT>` |
| DistanceSourceToDetector / SID (0018,1110) | `1050` | `<ABSENT>` |
| DistanceSourceToPatient / SOD (0018,1111) | `<ABSENT>` | `<ABSENT>` |

Empirical before/after with the proposed resolver (run against these exact files):

```
DX HAND : CURRENT spacing (1.0, 1.0)  →  FIXED (0.1, 0.1) from ImagerPixelSpacing  →  103 mm becomes 10.30 mm
MR      : CURRENT spacing (0.46484…)  →  FIXED (0.46484…) from PixelSpacing        →  103 mm stays 103.00 mm
```

---

## 2. Root-cause analysis

1. The FAST viewer's slice metadata (`SliceMeta.pixel_spacing`) is populated **exclusively** from
   `PixelSpacing` (0028,0030). When the tag is missing, every producer substitutes the geometry
   default `(1, 1)`.
2. For CR/DX (and MG/XA/XRF) the DICOM standard deliberately omits `PixelSpacing` — the diverging
   X-ray beam means there is no single "in-patient" spacing — and instead defines
   **`ImagerPixelSpacing` (0018,1164)** as the detector-plane pixel pitch. It is a **Type 1
   (required)** attribute in the DX-family IODs.
3. The codebase **never reads `ImagerPixelSpacing`** (verified: `grep -ri ImagerPixelSpacing` →
   **0 matches** across the whole repo, including `NominalScannedPixelSpacing`,
   `DetectorElementSpacing`, `PixelSpacingCalibrationType`).
4. Result: DX spacing collapses to 1.0 mm/px. Since this detector's true pitch is 0.1 mm,
   every length is inflated by **1.0 / 0.1 = 10×**. The ratio is incidental to this detector — a
   0.143 mm CR plate would show ~7×, a 0.2 mm plate ~5×, etc. The defect is "uncalibrated → 1 mm/px,"
   and the magnitude is `1.0 / ImagerPixelSpacing`.

CT/MRI never hit this path because `PixelSpacing` is always present, so the default is never used.

---

## 3. Relevant DICOM tags & the standard rule

| Tag | Keyword | Modalities that use it | Meaning |
|---|---|---|---|
| (0028,0030) | PixelSpacing | CT, MR, PET, NM, US (cross-sectional) | Spacing **in the patient** (Image Plane module). Type 1C in DX. |
| (0018,1164) | **ImagerPixelSpacing** | **CR, DX, MG, XA, XRF (projection)** | Physical pitch at the **detector front plane**. Type 1 in DX-family IODs. |
| (0018,2010) | NominalScannedPixelSpacing | Scanned film / some SC | Nominal spacing of a digitized/scanned image. |
| (0028,0A02) | PixelSpacingCalibrationType | DX/MG when calibrated | How `PixelSpacing` was corrected (GEOMETRY / FIDUCIAL). |
| (0028,0A04) | PixelSpacingCalibrationDescription | DX/MG when calibrated | Free-text description of the calibration. |
| (0018,1110) | DistanceSourceToDetector (SID) | projection | Source→detector distance (mm). |
| (0018,1111) | DistanceSourceToPatient (SOD) | projection | Source→object distance (mm); needed for magnification. |

**Standard precedence (DICOM CP-586 / Basic Pixel Spacing Calibration Macro, PS3.3 §10.7):**

> Display/measurement software looks for **Pixel Spacing (0028,0030)** first; if it does not exist,
> it uses **Imager Pixel Spacing (0018,1164)**. If neither exists, the measurement is **uncalibrated**.

So the correct measurement-spacing chain is:

```
PixelSpacing (0028,0030)
  └─ else ImagerPixelSpacing (0018,1164)        ← the missing branch that causes this bug
        └─ else NominalScannedPixelSpacing (0018,2010)
              └─ else uncalibrated  (report "px", do not invent mm)
```

### Geometric magnification (honesty about the limit)

`ImagerPixelSpacing` is measured **at the detector**, not in the patient. Because the beam diverges,
an object some distance in front of the detector projects **larger** than its true size by
`M = SID / SOD`. For this study SID = 1050 mm is present but **SOD is absent**, so `M` cannot be
computed. The corrected value (10.3 mm) is therefore a **detector-plane** length that slightly
**over-estimates** true anatomy — typically by ~5–20 % for an extremity resting near the detector.
This residual is **standard, accepted PACS behavior** for uncalibrated projection radiography (the
same as RadiAnt, Intelerad InteleViewer, etc.) and is not the bug. The bug is the 10× error; the
fix removes it and brings the reading to the best value the data supports.

---

## 4. Current code-path analysis

Both measurement paths bottom out at the same `pixel_spacing`:

**A. New ruler placement** (`modules/viewer/tools/controller.py::_ruler_press`, ~L334)
→ `CoordinateResolver.distance_mm` (`coord_resolver.py:116`)
→ `pipeline.image_xy_to_patient_xyz` (`lightweight_2d_pipeline.py:1375`)
→ slice basis `sx, sy` derived from `SliceMeta.pixel_spacing` (`~L1321-1322`).

**B. Live drag / ROI area** (`controller.py::_compute_ruler_distance_mm` L750,
`_get_pixel_spacing_mm` L557, ROI `area_cm2` L600/648)
→ `_pixel_spacing_fn` (`qt_viewer_bridge.py:746`)
→ `pipeline.get_slice_meta(idx).pixel_spacing`.

`SliceMeta.pixel_spacing` is produced in two places, **both `PixelSpacing`-only with a `(1,1)` default**:

- `modules/viewer/fast/dicom_header_scan.py::entry_from_dataset` (L63):
  `ps = _as_float_tuple(getattr(ds,"PixelSpacing",None), 2, (1,1))`
- `modules/viewer/fast/lightweight_2d_pipeline.py::_from_metadata_instances` (L3443):
  `ps = _as_float_tuple(inst.get("pixel_spacing"), 2, (1,1))`

The upstream `inst["pixel_spacing"]` is also `PixelSpacing`-only and `None` when absent, at every
extraction site:

- `PacsClient/pacs/patient_tab/utils/image_io.py` L818/825, L1551/1564, L1792-1795, L2298/2321, L3240/3252
- `database/dicom_db.py` (L663, L1055, L1110) and `database/manager.py` (L554) — store/replay `pixel_spacing` JSON; never `ImagerPixelSpacing`.
- `modules/viewer/geometry/source_geometry.py` L319-322 emits `missing_PixelSpacing` and proceeds with the default.

The advanced (VTK) viewer `modules/viewer/advanced/viewer_2d.py` reads `PixelSpacing` only as well, so
it shares the defect if used for DX — but the FAST viewer is the default measurement surface and the
one in the report.

### Possible-cause checklist (each item from the request)

| Candidate | Verdict |
|---|---|
| **PixelSpacing** | **Root cause** — absent on DX, code defaults to 1 mm/px. |
| **ImagerPixelSpacing** | The correct source (0.1 mm/px). **Never read anywhere.** |
| DetectorElementSpacing | Absent here; not required for the fix. |
| NominalScannedPixelSpacing | Absent here; include as 3rd-tier fallback for scanned/SC. |
| Magnification factor / SID / SOD | SID present (1050), SOD absent → small residual over-estimate, **not** the 10×. Not correctable without SOD. |
| Missing calibration | True for projection; detector-plane spacing is the best available, standard fallback. |
| Wrong unit conversion | No — mm math is correct once spacing is right. |
| Image resize / display scale | No — measurement uses image-pixel coordinates; zoom/`_display_scale` cancel in `widget↔image`. |
| Projection vs CT/MR handling | **Yes — the crux.** Projection needs the `ImagerPixelSpacing` branch CT/MR don't. |

---

## 5. Fix applied (minimal, safe)

One pure helper implementing the DICOM precedence, called at the two FAST-viewer producers.
No DB schema, network, or VTK changes; CT/MR path unchanged. **Files changed (2026-06-02):**

- `modules/viewer/fast/dicom_header_scan.py` — added `resolve_measurement_pixel_spacing()`;
  `entry_from_dataset()` now resolves spacing through it (header-scan producer).
- `modules/viewer/fast/lightweight_2d_pipeline.py` — import the helper; in
  `_from_metadata_instances()`, when DB/socket metadata lacks `pixel_spacing`, recover it from the
  header via the helper (metadata producer).
- `tests/code/fast_viewer/test_pixel_spacing_resolution.py` — new unit + real-data regression tests.
- **Build payload (mirrored for packaging, 2026-06-02):**
  `builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/dicom_header_scan.py`
  and `…/lightweight_2d_pipeline.py` — identical helper + call-site edits, so a packaged build ships
  the fix. (`builder/output/{dist,stage}` regenerate from source on build; the dated `builder/backups/…`
  copy is intentionally left untouched.)

**5.1 Helper** — in `modules/viewer/fast/dicom_header_scan.py`:

```python
def resolve_measurement_pixel_spacing(ds) -> tuple[float, float] | None:
    """DICOM-correct (row_mm, col_mm) for measurement, or None if uncalibrated.

    Precedence per DICOM CP-586 / PS3.3 §10.7 (Basic Pixel Spacing Calibration):
      PixelSpacing (0028,0030)  →  ImagerPixelSpacing (0018,1164)
                                →  NominalScannedPixelSpacing (0018,2010)
    CT/MR always carry PixelSpacing, so they are unaffected. CR/DX/MG/XA fall
    through to ImagerPixelSpacing, which is the detector-plane pitch.
    """
    for tag in (0x00280030, 0x00181164, 0x00182010):
        el = ds.get(tag)
        val = el.value if el is not None else None
        try:
            if val is None:
                continue
            seq = list(val)
            if len(seq) >= 2:
                r, c = float(seq[0]), float(seq[1])
                if r > 0.0 and c > 0.0:
                    return (r, c)
        except Exception:
            continue
    return None
```

**5.2 Use it in `entry_from_dataset`** (replaces the `PixelSpacing`-only read at L63):

```python
ps = resolve_measurement_pixel_spacing(ds)
ps = ps if ps is not None else _as_float_tuple(getattr(ds, "PixelSpacing", None), 2, (1, 1))
```

**5.3 Backfill the metadata-dict path** — in
`lightweight_2d_pipeline.py::_from_metadata_instances`, the loop at ~L3480 already re-reads the
header to fill missing `rows/cols`. Extend it so that **when `inst.get("pixel_spacing")` is missing**,
the spacing is resolved from the header via the helper instead of silently keeping `(1,1)`.

**5.4 (Optional, deferred) Provenance + UI honesty.** Carry an `imager_pixel_spacing` / spacing-source
field through `image_io.py` + the DB so the value persists without a header re-read, and label
projection-radiography measurements as *detector-plane (uncalibrated for magnification)* in the
overlay. Not required to kill the 10× error; recommended for clinical clarity.

Modalities fixed by 5.1–5.3: **CR, DX, MG, XA, XRF**. Modalities untouched: **CT, MR, PET, NM, US**.

---

## 6. Risks & regressions

- **CT/MR unchanged** — they carry `PixelSpacing`, which wins at tier 1 (proven: MR stays 0.46484).
  Low risk.
- **DX with a real `PixelSpacing` + `PixelSpacingCalibrationType`** (vendor-calibrated) — precedence
  still prefers `PixelSpacing`, which is correct. Low risk.
- **Garbage/zero spacing** — the `r > 0 and c > 0` guard rejects it and falls through; never divides by
  a bad value.
- **Uncalibrated images (neither tag)** — still fall back to `(1,1)`; behavior matches today. Consider
  surfacing a "px / uncalibrated" badge rather than implying mm (optional 5.4).
- **Out of scope on purpose:** DB schema, socket/download protocol, VTK render path, multi-study and
  cross-patient guards. No edits there.
- **Advanced VTK viewer is NOT on the projection-measurement path — confirmed, no edit needed.**
  `source_geometry.py` returns early when `ImagePositionPatient` is absent, and DX/CR/MG carry no
  IPP / IOP / FrameOfReferenceUID (verified on 44534's DX), so projection images never build advanced
  geometry — they are measured only by the FAST viewer (now fixed). The `PixelSpacing`-only reads in
  `viewer_2d.py` / `source_geometry.py` apply to CT/MR volumes, which always carry `PixelSpacing`, so
  they are not a measurement exposure. Left unchanged to avoid needless VTK-geometry risk before a build.
- **Optional (not required for correctness):** persist `ImagerPixelSpacing` / spacing-source through
  `image_io.py` + DB (avoids the per-image header re-read on the metadata path) and badge projection
  measurements as *detector-plane* (see §5.4).
- **Anisotropic spacing** (row ≠ col) is preserved as a pair throughout — no regression for it.

---

## 7. Validation tests

**Result (2026-06-02): 14/14 passing**, including the real-data regression (DX 44534 → `0.1` mm via
ImagerPixelSpacing; MR 44534 → `0.46484375` mm via PixelSpacing). Verified with an isolated harness
because the just-edited files were mid-sync on the dev mount; run the committed test file under the
Windows venv (`run_test.ps1` / pytest) to confirm in-tree.

**GUI live-verified (2026-06-02):** measurements on the 44534 DX hand study now read correctly in the
running source build — the ~10× over-measurement is gone (confirmed by vahid). CT/MRI measurements
unchanged.

**Unit (new)** — `tests/code/fast_viewer/test_pixel_spacing_resolution.py`:
- only `ImagerPixelSpacing=[0.1,0.1]` present → resolver returns `(0.1,0.1)`.
- both present (`PixelSpacing=[0.3,0.3]`, `ImagerPixelSpacing=[0.1,0.1]`) → returns `(0.3,0.3)` (PS wins).
- only `NominalScannedPixelSpacing` → returns it.
- neither → returns `None`.
- zero/negative spacing → rejected, falls through.

**Regression (real data)** — assert resolver on 44534: DX study 738 → `(0.1,0.1)`; MR study 762 →
`(0.46484375,0.46484375)`. (Use a copy of the DICOM, not the live DB.)

**Existing suites to re-run** (must stay green):
`tests/code/fast_viewer/test_tools_ruler.py`, `test_tools_roi.py`, `test_tools_angle.py`,
`tests/code/viewer/test_fast_viewer_pipeline.py`, `test_display_geometry.py`,
`test_pydicom_backend_geometry.py`.

**GUI check** (human-assisted): open 44534 → DX Hand PA → ruler across a metacarpal width →
expect ~9–12 mm (was ~100 mm); open the MR series → ruler unchanged. ROI `area_cm²` on DX should drop
by ~100× (10× per axis).

---

## 8. Sources

- DICOM CP-586, *Pixel spacing and calibration in projection radiography* — https://dicom.nema.org/dicom/CP/CPack-34_PDF/cp586_lb.pdf
- DICOM PS3.3 §10.7, *Basic Pixel Spacing Calibration Macro* — https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_10.7.html
- Imager Pixel Spacing (0018,1164), DICOM Standard Browser — https://dicom.innolitics.com/ciods/cr-image/cr-image/00181164
- Pixel Spacing (0028,0030), DX Detector module — https://dicom.innolitics.com/ciods/digital-mammography-x-ray-image/dx-detector/00280030
- InteleViewer, *Measurement Calibration for Projection Radiographic Images* — https://inteleviewer.documentation.intelerad.com/iv-help/PACS-5-1-1-P171/en/Content/Topics/IV_Measurement_Calibration.html
- RadiAnt forum, *Pixels to mm and (0018,1164)* — https://www.radiantviewer.com/dicom-viewer-forum/pixels-to-mm-conversion-and-0018-1164-dicom-tag/1575/
