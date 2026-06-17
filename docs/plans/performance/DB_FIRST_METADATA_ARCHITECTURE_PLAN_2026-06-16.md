# DB-First DICOM Metadata — Architecture Review & Implementation Plan

Date: 2026-06-16
Status: review + plan (no clinical-path code changed by this document).
Safety contract: **do not change clinically verified geometry, slice order,
orientation, or rendering output.** Metadata is only *stored and reused* — never
recomputed differently.

## TL;DR / verdict

The direction is correct, and most of it is **already built**:

- The downloader (`series_downloader._save_series_instances_to_db`) already reads
  each downloaded file's header in an 8-worker pool and writes per-instance
  metadata to `dicom.db` (`batch_insert_instances`): `instance_path`,
  `instance_number`, `rows`, `columns`, `window_width/center`,
  `image_orientation_patient` (IOP), `image_position_patient` (IPP),
  `pixel_spacing`, `direction`. Import populates instance rows too (POKORA: 401
  rows present).
- A DB-first read path already exists in
  `image_io.load_single_series_by_number` (`find_series_pk_by_number` →
  `get_instances_by_series_pk` → `read_series_instances_metadata` /
  `_get_cached_metadata` → reconcile-with-disk → backfill NULL geometry →
  normalize). The disk header rescan (`_build_metadata_headers_only`, ~12 ms/slice
  → 5 s for a 401-slice series) is only the **fallback when that path yields
  nothing**.

**The geometry the FAST viewer needs is already in the DB**:
`_normalize_instances_geometry_order` derives `direction` from **IOP**, and
ordering is **IPP**-based (`canonical_sort_instances`) — *not* from
`slice_thickness`/`spacing` tags. So IOP+IPP+pixel_spacing+rows+cols (all written)
are sufficient for an identical setup map.

**So the bottleneck is not "metadata isn't indexed."** It is:

1. The DB-first read path is **gated OFF by default** (`AIPACS_VIEWER_DB_METADATA=0`,
   `_vc_load._ensure_study_pk_for_db_metadata:256`) — so the stored metadata is
   ignored and the viewer rescans disk on drag. The same headers are read **twice**
   (downloader → DB, then viewer ← disk).
2. There is **no per-series "indexed & complete" signal**, which is exactly why the
   gate was left off (the team couldn't trust DB completeness — "DB row found but no
   retrievable instances").

The high-leverage work is therefore (a) a reliable index-status signal and (b)
turning on the consumer behind a golden-compare verify gate — **not** a new
service that re-reads every series from disk (that would double I/O during batch
downloads).

## 1. Metadata consumer audit

| Consumer | Key fields used | Reads from today | Repeated read? | DB-safe to serve? |
|---|---|---|---|---|
| **FAST viewer** (setup map) | series row; per-instance IOP, IPP, pixel_spacing, rows, columns, instance_number, window, instance_path | DB path if `study_pk` set **(gated off → disk rescan)** | **Yes — twice** (downloader→DB, then disk on drag) | **Yes, already** — geometry from IOP/IPP which are stored |
| **FAST viewer** (pixels) | PixelData, RescaleSlope/Intercept, BitsAllocated, PixelRepresentation, Photometric | disk (lazy, per-slice) | No (lazy, cached) | No — pixels must come from disk; decode params read with pixels |
| **ADVANCED / VTK** | volume + geometry | disk via VTK/ITK | per open | Partial — bundled with pixel load; lower ROI |
| **MPR** (`orthogonal`, `zeta_mpr`) | volume + spacing/orientation | **disk via SimpleITK** (`volume_loader`, `sitk_helpers`), IPP-sorted files | per MPR init | No today — ITK reads files directly; would need a separate adapter |
| **Thumbnails** | precomputed PNG | `ThumbnailStore` / PNG cache | No | N/A — already cached, no header read |
| **Drag-and-drop load** | = FAST viewer setup map | same as FAST | same | same |
| **Patient/study/series tree** | patient/study/series rows | DB | No | Already DB |
| **Download manager** | series list, counts | DB + server | No | Already DB |
| **Import** | full headers (grouping + DB write) | disk once at import | No (once) | Writes DB |
| **Cache/manifest builder** | disk file presence; `content_versions.json` (per-study version only) | disk listing + DB | No | N/A |

**Takeaways**
- The only consumer that *re-reads geometry headers from disk on a hot path* is the
  **FAST viewer setup map**, and its required fields are already in the DB. This is
  where DB-first pays off (5 s → ~tens of ms on POKORA-class series).
- **MPR and ADVANCED read pixels via ITK/VTK from disk** — the header read there is
  bundled with the unavoidable pixel read, so DB-first saves little and is **not**
  recommended in phase 1 (and touching ITK/VTK geometry is the highest clinical
  risk).
- Thumbnails, tree, DM, import are already DB/cache-backed — no change needed.

## 2. Database schema review

Existing tables (already present):

- `patients(patient_pk, patient_id, patient_name, birth_date, sex, age, patient_weight)`
- `studies(study_pk, study_uid, patient_fk, study_date, study_time, study_description,
  institution_name, modality, body_part, number_of_series, number_of_instances,
  study_path, reportStatus…)`
- `series(series_pk, series_uid, series_name, study_fk, series_number, series_thk,
  series_description, orientation, modality, image_count, protocol_name,
  body_part_examined, manufacturer, institution_name, thumbnail_path, series_path)`
- `instances(instance_pk, sop_uid, series_fk, instance_path, instance_number, rows,
  columns, window_width, window_center, is_rgb, group_id, image_position_patient,
  image_orientation_patient, pixel_spacing, direction, slice_thickness,
  spacing_between_slices, rescale_slope, rescale_intercept, bits_allocated,
  pixel_representation)`

**The instances table already has columns for nearly the entire requested
instance-level list.** The gap is not the schema — it is that the downloader's
write dict omits some columns (they stay NULL):

- Omitted by downloader write: `slice_thickness`, `spacing_between_slices`,
  `rescale_slope`, `rescale_intercept`, `bits_allocated`, `pixel_representation`,
  `is_rgb`. (Geometry does **not** need slice_thickness/spacing — IPP deltas drive
  z-spacing — so these are cosmetic for the setup map; rescale/bits are read with
  pixels at decode time.)

**Genuinely missing / worth adding (small, targeted — avoid gold-plating):**

- Series-level (the high-value additions): `metadata_index_status`
  (`NotIndexed|Indexing|Indexed|FailedIndexing|NeedsReindex`),
  `indexed_instance_count`, `expected_instance_count`, `last_indexed_at`,
  optional `metadata_version`. **These are what make the read gate safe.**
- Study-level (optional): `accession_number` (if a consumer needs it; not used by
  the viewer setup today).
- Instance-level (optional, only if a consumer reads it): `transfer_syntax_uid`
  (decode hint), `number_of_frames` (multi-frame), `slice_location`.

**Do NOT** add the full proposed field list (national_id, high_bit, planar_config,
file hash, slice-normal vectors, etc.) unless a named consumer reads it — they are
not consumed by the current viewer/MPR setup and would be dead columns + migration
risk. Store what the code actually reads.

Migration: additive `ALTER TABLE … ADD COLUMN` (nullable) only — no destructive
change, back-compat with existing rows. Gate behind the existing schema-migration
path (`ensure_*_schema`).

## 3. Phased implementation plan (flag-gated, reversible)

### Phase 0 — index-status + complete the write (safe; no read-path change)
- Add the series-level status columns (additive migration).
- At download completion (`series_downloader._save_series_instances_to_db`) and
  import completion: after the existing instance write, stamp
  `metadata_index_status=Indexed`, `indexed_instance_count=N`,
  `expected_instance_count=server/expected`, `last_indexed_at=now` — **only when
  `indexed == expected`**; else `NotIndexed`/`FailedIndexing`. No extra disk read
  (reuse the headers already parsed at write time). Add the 2 geometry-cosmetic
  fields to the write dict while we're there (cheap, completeness).
- A **backfill/reindex** job (low-priority, throttled, cancellable, yields to the
  DB lock) that scans only series whose rows are missing/incomplete (legacy/partial
  /0-row), reads only those, stamps status. NOT a blanket re-read of every series.
- Pure write-side + status → cannot change any displayed output. Default-on safe.

### Phase 1 — DB-first read for the FAST viewer setup map (behind verify gate)
- Replace the global `AIPACS_VIEWER_DB_METADATA` off-switch with a **data-driven
  gate**: use the DB path when `metadata_index_status=Indexed` AND every instance
  has non-NULL IOP/IPP; else disk fallback (unchanged).
- **Verify mode first** (`AIPACS_VIEWER_DB_METADATA=verify`): build BOTH the DB
  setup map and the disk setup map for the first series of a study, compare the
  geometry signature (per-instance IPP order + IOP + pixel_spacing + the final
  sorted SOP order), and LOG match/mismatch — **display stays disk-driven**. Run on
  POKORA + a downloaded multi-study patient + a multi-modality patient. Only after
  it logs clean across the regression set do we flip the gate to active.
- The DB path already calls the SAME normalizer (`_normalize_metadata_instances`)
  and `canonical_sort_instances` as the disk path, so a clean verify result proves
  identical geometry/order.

### Phase 2 — (optional, later) MPR/ADVANCED
- Only if measurement shows header-read (not pixel-read) is a material cost there.
  Higher clinical risk (ITK/VTK geometry) → separate plan + golden 3-plane compare.
  Not recommended until Phase 1 is proven in the field.

## 4. Safety & validation

- **Geometry source is unchanged**: IOP→direction, IPP→sort. Both are stored and
  fed through the existing normalizer. The verify-mode golden compare is the proof
  gate before any switch-on.
- **Multi-study / multi-Patient-ID**: keys are `series_pk` (unique per
  SeriesInstanceUID) and `study_pk`; the existing H1 multi-study guard already
  refuses to feed a primary `study_pk` to an offset-key series. PatientID is never
  a load/cache key. Keep all of this.
- **Consistency**: DB says instance exists but file missing → series marked
  stale/incomplete (sync manifest already does disk-vs-DB). File exists but DB row
  missing → backfill/reindex. Provide the reindex/repair operation (Phase 0).
- **Fallback always available**: any DB miss/incompleteness/verify-fail → disk
  header read, exactly as today. The app never depends solely on the DB.

## 5. Metrics (instrumentation already present; capture before/after)

Grep `user_data/logs/app.log`:
- header reads / disk rescans: `[FAST_LOAD_BREAKDOWN] … headers_only_build=` with
  `disk_file_count>0` (each = one full disk scan). DB-first → these → 0.
- setup-map build vs reuse: `FAST:meta_cache source=miss|hit`.
- DB lookup time: `_qt_substage_ms['db_lookup']`; DB path active:
  `[H1_DB_METADATA] study_pk=… resolved`.
- drag → first image: `[VIEWER_SWITCH] … first_image_visible_ms` / `psso_total`.
- parallel fallback scan: `[FAST_LOAD_BREAKDOWN] header_scan_parallel files=… workers=…`.
- patient open: `[FAST-OPEN-TRACE] … first_series_visible` (subtract idle).
- MPR init + memory: MPR stage logs + `aipacs.resource resource-summary rss=`.

Targets: first drag of an already-downloaded large series 5 s → < 0.5 s; repeated
header reads per open → ~0 for indexed studies; no download/UI regression.

## 6. Build inclusion

All touched files are in collected packages (frozen into the PYZ): `image_io.py`
(PacsClient), `series_downloader.py` (modules/download_manager — not plugin-
mirrored), `dicom_db.py` / schema (database), `_vc_load.py` (PacsClient). The
schema migration runs at startup via `init_database` / `ensure_*_schema`. Verify in
the built app: `engine/.../instances` has the new columns and
`[H1_DB_METADATA]` / `FAST:meta_cache source=hit` appear in the log on a downloaded
study open.

## Recommendation

Implement **Phase 0** (index-status + write completion + reindex; pure write-side,
safe) and the **Phase 1 verify harness** (observe-only golden compare) now. Capture
the verify results on POKORA + a downloaded multi-study patient. Flip the DB-first
read gate to active only after verify logs clean. Defer MPR/ADVANCED (Phase 2). Do
not expand the instance schema beyond the fields a consumer actually reads.
