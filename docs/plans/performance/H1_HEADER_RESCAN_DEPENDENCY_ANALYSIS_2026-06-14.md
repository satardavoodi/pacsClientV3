# H1 — FAST viewer header re-scan: deep dependency analysis (2026-06-14)

**Status:** investigation only (no code changed). Goes deeper than the 2026-06-08
architecture review (`ARCHITECTURE_REVIEW_DATA_PATHS_2026-06-08.md`, H1). Conclusion:
H1 is **not a single switch** — it is **two independent header-scan subsystems** that
both depend on the **same unmet foundation**: the DB must completely and correctly mirror
the per-instance header fields each scan needs. Today it does not. So H1 is a **staged
program with a DB-foundation phase first**, each phase flag-gated with a disk fallback.

---

## 1. The two tracks (the viewer reads DICOM headers TWICE per open)

**Track 1 — per-instance metadata build**
`PacsClient/pacs/patient_tab/utils/image_io.py::_build_metadata_headers_only` (~:1656).
This is the ~800–1424 ms `headers_only_build` cost in the arch review. A **DB-backed
alternative already exists**: `read_series_instances_metadata` (image_io.py:1976) →
`database/manager.py::get_instances_by_series_pk` (returns 21 columns incl. all the
header-stub fields). It is **gated OFF** by `AIPACS_VIEWER_DB_METADATA=0`
(`_vc_load.py:244`); the upfront `study_pk` resolver is drafted
(`_vc_load.py::_ensure_study_pk_for_db_metadata`, ~:212) but disabled.

**Track 2 — FAST pixel-pipeline geometry scan**
`modules/viewer/fast/dicom_header_scan.py::scan_series_header_entries` (:135), called by
`modules/viewer/fast/lightweight_2d_pipeline.py` (:3509, :3800) and
`modules/viewer/fast/pydicom_2d_backend.py` (:617, :639). Builds `DicomHeaderEntry`
(incl. `PhotometricInterpretation`, `SamplesPerPixel`). **No DB read at all.**

So on a FAST open the same files are header-read twice (metadata + pixel geometry).
Capturing the full win requires DB-serving **both**; they have different blockers.

---

## 2. Empirical DB completeness (live `dicom.db`, 304,779 instances)

| instance column | NULL/empty | note |
|---|---|---|
| instance_path, rows, columns, rescale_slope/intercept, bits_allocated, pixel_representation, is_rgb, instance_number, sop_uid | **0.0%** | ✓ reliable |
| window_width / window_center | 0.1% | ✓ |
| image_orientation_patient (IOP) | 0.6% | ✓ |
| image_position_patient (IPP) | 0.6% | ✓ |
| pixel_spacing | 0.6% | ✓ |
| direction | 0.7% | ✓ |
| **slice_thickness** | **99.1% NULL** | ✗ write gap (see D1) |
| **spacing_between_slices** | **99.5% NULL** | ✗ write gap (see D1) |
| **photometric_interpretation** | **column absent** | ✗ (Track 2 needs it) |
| **samples_per_pixel** | **column absent** | ✗ (Track 2 needs it) |

- IOP+IPP+pixel_spacing all present on **99.4%** of instances → core geometry is solid.
- **1,075 / 8,673 series (12.4%) have ZERO instance rows** — the import / offline-cloud
  path writes series/study rows but not per-instance rows.

**D1 proven a write gap, not source-absent:** a 40-instance spot-check of rows that are
NULL-in-DB found the **source files HAVE** `SliceThickness` in **40/40** and
`SpacingBetweenSlices` in **38/40** (e.g. ST=8, SBS=12/32). The downloader reads these
tags but does not persist them. So switching Track 1 to the DB *today* would silently
**lose** slice spacing for ~99% of series versus the header scan — degrading reference
lines, MPR spacing, and slice geometry. This is the headline dependency.

---

## 3. Dependencies / blockers

> **CORRECTION (2026-06-14, geometry deep-dive — see
> `docs/reports/GEOMETRY_EVAL_VTK_MPR_2026-06-14.md`):** D1 below was first called the
> *headline* geometry blocker. That is **downgraded**. Every viewer derives inter-slice
> z-spacing from **IPP deltas** (VTK `source_geometry.py:370`, FAST
> `pydicom_2d_backend._attach_spacing_between_slices:521`, MPR via SimpleITK), NOT from the
> `slice_thickness`/`spacing_between_slices` tags. Since the DB carries per-instance **IPP**
> (99.4%), a DB-served metadata dict feeds the same IPP derivation and geometry stays
> correct with those tags NULL. So **D1 is defense-in-depth / display-accuracy, not a
> geometry-correctness gate.** The real geometry gate is: preserve the IPP derivation in any
> DB-served path, keep the completeness check + disk fallback, resolve study_pk up front
> (D4), and golden-compare before flipping the flag. MPR is NOT in H1's blast radius (it
> loads via SimpleITK-from-files, not the FAST metadata dict).

- **D1 (shared, foundation):** downloader reads but does not persist `slice_thickness` /
  `spacing_between_slices` → fix the write in
  `series_downloader.py::_save_series_instances_to_db` / `database/dicom_db.py` insert,
  then **backfill ~302k existing rows**. Until done, the DB path loses this geometry.
- **D2 (shared):** 12.4% of series have no instance rows (import/offline-cloud) → DB path
  must fall back to disk for them; ideally the import path also writes instances.
- **D3 (Track 1):** 0.6% IOP/IPP/pixel_spacing NULL → per-instance disk fallback required.
- **D4 (Track 1):** `study_pk` is resolved too late for server-opened studies, so the DB
  path is skipped on the first series (drafted fix exists, gated off).
- **D5 (Track 2):** DB has **no** `photometric_interpretation` / `samples_per_pixel`
  columns → schema migration + downloader write + backfill before the pixel pipeline can
  read geometry from the DB.

The common root: **both tracks need the DB to be a complete, correct mirror of the
per-instance header.** That is the foundation phase.

---

## 4. Staged plan (each phase independently shippable, flag-gated, disk fallback)

**Phase 0 — DB foundation (prerequisite for both tracks)**
1. Persist `slice_thickness` + `spacing_between_slices` in the downloader (fix D1).
2. Add columns `photometric_interpretation` + `samples_per_pixel`; write them (enables D5).
3. One-time **backfill** of existing rows (off-thread / lazy; never block the UI).
4. Make import/offline-cloud populate instances, or accept disk fallback for them (D2).
5. Add a per-series **completeness self-check** (DB row count == on-disk file count AND
   required fields non-NULL) that decides DB-vs-disk at load time — the safety gate.

**Phase 1 — Track 1 DB metadata (captures the ~1424 ms `headers_only_build`)**
- Land `_ensure_study_pk_for_db_metadata` (D4) and flip `AIPACS_VIEWER_DB_METADATA` on,
  **only after** Phase 0 + golden validation. Disk fallback whenever the completeness
  check fails. Est. 800–1424 ms → ~20–60 ms (DB read + cache).

**Phase 2 — Track 2 pixel-pipeline geometry from DB (captures the second scan)**
- Build `DicomHeaderEntry` from DB rows (requires Phase 0 columns); disk fallback otherwise.

---

## 5. Risk & validation (clinical)

Geometry drives reference lines, MPR, and measurements, so any DB-served value **must
equal** the header value. Guardrails: Phase 0 backfill + the per-series completeness
self-check + disk fallback. Before flipping each flag, run a **golden compare** —
DB-built vs header-built metadata over a sample of studies (CT/MR/multi-frame/RGB/doc) —
and require an exact match on IOP/IPP/pixel_spacing/slice_thickness/spacing/rows/cols/
WL/rescale/photometric/samples. Each phase is reversible via its flag.

---

## 6. Recommended next step

Phase 0 item 1 (the `slice_thickness`/`spacing_between_slices` write gap) is **also a
standalone correctness bug** — the DB should already carry this geometry. Doing it first
(pin the exact drop point in the downloader insert, fix the write, add a guarded lazy
backfill, test-gated) is the safe, high-value foundation and unblocks Phase 1. The
schema additions (D5) and the Track-1 flag flip follow once the DB is complete and the
golden compare passes. No phase should ship without the completeness self-check + disk
fallback in place.
