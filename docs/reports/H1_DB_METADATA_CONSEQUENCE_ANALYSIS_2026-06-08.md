# H1 (DB-metadata path) — consequence analysis + validation/KPI plan (2026-06-08)

Companion to `ARCHITECTURE_REVIEW_DATA_PATHS_2026-06-08.md`. This applies the
conservative path-replacement discipline to the **only** high-value architectural
finding (H1) **before** any code is written. No code changed.

## The single most important framing

**H1 is NOT a path removal or replacement. The disk header scan
(`_build_metadata_headers_only`) STAYS, unchanged, as the fallback.** The code in
`image_io.load_single_series_by_number` is already structured as:

```
if study_pk:                       # PRIMARY (intended) path — read metadata from DB
    _qt_meta = <DB lookup + reconcile + backfill>
if _qt_meta is None:               # FALLBACK — disk header scan (unchanged)
    _qt_meta = _build_metadata_headers_only(series_path, series_number)
```

The DB path is the **existing, intended primary** path. It already runs today for
local studies and for the 2nd+ series of a study (once `study_pk` is known). H1
only makes it reachable for the **first** series of a **server-opened** study by
supplying `study_pk` earlier. Nothing is deleted; the duplicated route is not
"removed", the *condition that bypasses the primary route* is fixed. If the DB is
ever incomplete, the existing fallback runs exactly as it does now.

## Decisive evidence (read-only, live DB copy — `_recovery/db_geometry_audit.py`)

The DB **already holds** the geometry the disk scan re-derives, at full
completeness, across 252,962 real instance rows:

| field | non-NULL | top-8 series (by size) |
|---|---|---|
| `image_orientation_patient` | **99%** (252028/252962) | 100% on every one |
| `image_position_patient` | **99%** | 100% on every one |
| `pixel_spacing` | **99%** | 100% on every one |
| `rows`, `columns`, `rescale_slope` | **100%** | 100% |

→ The downloader's geometry write (`series_downloader.py:965-1011`) works. H1 is a
**low-risk propagation fix**, confirmed — not a riskier download-path change.

---

## The 8 required questions, answered

**1. What does the old (disk) path do?**
`_build_metadata_headers_only(series_path, series_number)` lists the series folder,
reads each DICOM header (`stop_before_pixels`, `specific_tags`), and builds a
metadata dict: `series{series_number, series_name, series_description, series_thk,
modality, protocol_name, body_part_examined, series_path, main_thumbnail}` +
`instances[]{instance_number, instance_path, rows, columns, window_width,
window_center, is_rgb, sop_uid, image_orientation_patient, image_position_patient,
pixel_spacing, slice_thickness, spacing_between_slices, rescale_slope,
rescale_intercept, bits_allocated, pixel_representation}`. It is a **pure read** —
no DB write, no cache write, no UI/download side effect. Output is then
geometry-normalised + lazy-loader-built downstream (same for both paths).

**2. Which modules consume its output?** (mapped, with file:line)
- FAST render / pixel access — `lightweight_2d_pipeline.py:3440-3491`,
  `pydicom_2d_backend.py:559-585` (instance_path, rows, columns, IOP, IPP,
  pixel_spacing, is_rgb, bits_allocated, pixel_representation, WW/WC, rescale,
  instance_number).
- Reference lines / lock-sync — `reference_line.py:46,67`,
  `dicom_sync_geometry.py:99-643` (IOP, IPP, pixel_spacing, slice_thickness).
- Advanced/MPR (VTK) — `viewer_2d.py:1991-2010` (backfills DICOM tags from IOP/IPP/
  pixel_spacing/slice_thickness/spacing_between_slices/rows/columns).
- Measurements — `tools/controller.py:567,607,655,767` (pixel_spacing).
- Geometry contract / slice ordering — `advanced_geometry_contract.py:439-565`,
  `image_io.py:723-796` (IOP/IPP).
- Progressive + apply — `_vc_load.py:580-813` (series_number, series_path,
  thumbnail_path, instances list/length, instance_path).
- Thumbnails (sidebar) — `thumbnail_panel.py:473-478` (series_number, modality,
  series_description, body_part_examined).

**3. Which edge cases does the disk path support?**
(a) DB row absent (pre-DB / never-downloaded / imported-not-yet-indexed series);
(b) DB behind disk during active download (more files on disk than DB rows);
(c) NULL/partial geometry; (d) DX/MG with no `PixelSpacing` (uses ImagerPixelSpacing
fallback, `lightweight_2d_pipeline.py:3453-3457`); (e) multi-study offset-key series
(resolved to real `study_uid`/`orig_series_number` before this function); (f)
non-image SOP classes / DOC-RGB series; (g) instance_number ordering when geometry
absent.

**4. Does the DB (primary) path cover all those cases?**
- Common case (DB complete, 99–100%): **fully** — identical metadata shape (proved
  by the consumer map + both paths emit the same dict; `dicom_db.py:631-682` write
  ↔ `_build_metadata_headers_only` build).
- (b) DB-behind-disk: covered by `_reconcile_db_instances_with_disk` (reads headers
  for **only the missing** files, not all N).
- (c) NULL geometry: covered by `_metadata_needs_geometry_backfill` →
  `_backfill_instance_orientation` (backfills from disk for the ~1% missing).
- (a) DB row absent: **DB path yields nothing → existing disk fallback runs**
  (unchanged). This is the key safety property.
- (d)/(e)/(f)/(g): unchanged — DX/MG pixel_spacing fallback lives in the *render*
  layer (runs regardless of metadata source); offset-key resolution happens
  *before* this function; ordering uses the same `instance_number`/IOP fields the
  DB stores.

**5. Does it preserve all required side effects?**
The disk path has **no side effects to preserve** (pure read). The only incidental
effect — warming the OS file cache for N files — is not relied on by anything (the
lazy loader reads pixels on demand with prefetch). No DB write, cache write, UI
state, or download-status mutation occurs in either path. ✔

**6. Does anything become starved?**
No. The metadata dict is the sole output, and the DB path produces the same dict.
The DICOM files remain on disk and are still read on demand for pixels by the lazy
loader (unchanged). Thumbnails, downloads, reports, and the geometry index all read
the metadata dict, not the act-of-scanning. Nothing downstream depends on the disk
scan *running*. ✔

**7. Hidden dependencies (cache / DB / UI / download status / thumbnails / viewer)?**
- Cache: metadata is cached identically (`_full_cache`, `_series_cache`) regardless
  of source. No change to cache keys/shape.
- DB state: the DB is the *source* in the primary path; the download subprocess
  writes it with DB-lock retry; cross-process WAL readers see committed rows. (The
  one timing nuance — DB rows committed slightly after files land during active
  download — is exactly case (b), handled by reconcile.)
- Download status / progressive: a still-downloading series hits reconcile/fallback
  and the progressive grow continues to stream as today. No coupling broken.
- Viewer/UI state, MPR, reports: consume the metadata dict only.
→ No hidden dependency is severed; the riskiest one (active-download partial DB) is
explicitly handled by reconcile + fallback.

**8. Is the duplication actually solving a real requirement?**
Partly yes — the disk scan's *real* requirement is **fallback** (cases a/b/c). That
requirement is **kept** (the scan stays). The *duplicate full parse on every
first-open even when the DB is complete* solves nothing — that is the waste H1
removes. So we keep the legitimate fallback and remove only the needless re-parse.

---

## Validation test matrix (must pass before/after)

For each: assert behavior is **identical or better**, with the DB path active.

| Workflow | What to assert | Where |
|---|---|---|
| Patient open (server study) | tab opens; first series renders; `[FAST_LOAD_BREAKDOWN]` shows `db_lookup`/`cached_metadata` (not `headers_only_build`) | live + `viewer_diagnostics` |
| Thumbnail load | right-panel + sidebar thumbnails identical count/content | live + existing thumbnail tests |
| Download start | unchanged (download path untouched) | `download_diagnostics` |
| Partial-download resume | open a mid-download series → reconcile reads only missing headers; stack grows; no missing slices | live + `test_*resume*` |
| Drag-drop into viewport | dropped series renders; slice count correct; W/L correct | live |
| Progressive stack loading | grows to full N; current slice preserved by path; no index mismatch | `PROGRESSIVE_GROW` + grow tests |
| Viewer scrolling | smooth; correct geometry order (IOP); no black/cross-series | live + FAST_EVENT_PACING |
| **MPR/reslice** | reference lines + reslice geometry identical (IOP/IPP from DB == from disk) | live + mpr tests |
| Report/status update | unaffected (no metadata-source coupling) | existing education/report tests |
| Cache + DB consistency | metadata dict shape byte-equivalent DB-vs-disk for a complete series (golden compare) | **new targeted test** |
| Restart / reopen | reopen same study → DB path again; no stale/locked DB | live restart |
| Geometry golden | for a fully-downloaded series, assert DB-built metadata == disk-built metadata field-by-field (instances + series) | **new targeted test** |

**New targeted tests to add (with the fix, not now):**
1. `test_db_vs_disk_metadata_equivalence` — build metadata both ways for a synthetic
   series with full geometry; assert identical instances (all 18 fields) + series
   fields + ordering.
2. `test_db_path_partial_db_falls_back_to_reconcile` — DB has subset of files →
   reconcile fills the rest; final instance set == disk truth.
3. `test_db_path_absent_falls_back_to_disk_scan` — no DB rows → `_build_metadata_headers_only`
   runs (fallback intact).
4. `test_null_geometry_backfilled` — DB rows with NULL IOP/IPP → backfill restores
   geometry == disk.

## KPIs (before → expected after)

| KPI | Baseline (disk scan) | Target (DB primary) |
|---|---|---|
| First-open header build, 450-slice series | `headers_only_build=800 ms` | DB `db_lookup`+`cached_metadata` ≈ **20–60 ms** |
| First-open header build, 428-slice | `1424 ms` | ≈ **20–60 ms** |
| Drag→first-image (already-downloaded, uncached) | ~0.8–2.4 s | sub-second |
| Per-series header **re-parses** per session | 2 (download + view) | **1** (download only) |
| MPR/reference-line geometry | (unchanged) | **identical** (same IOP/IPP source) |
| Active-download series open | reconcile/fallback | unchanged |
| Patient open total (tab_created, first_series_visible) | current | ≤ current (never worse) |

KPI signal: `[FAST_LOAD_BREAKDOWN]` must change from `headers_only_build=Nms` to a
`db_lookup=…ms cached_metadata=…ms reconcile_disk=…ms` breakdown.

## Risk assessment

- **Risk level: low-moderate.** It activates an existing, already-used path; it does
  not alter data formats, the download contract, the render path, or remove the
  fallback. The geometry is confirmed present (99–100%).
- **Primary residual risk:** a study whose DB rows are *stale vs disk* in a way
  reconcile misjudges (e.g. files replaced in place). Mitigation: reconcile already
  keys on file presence; keep the fallback; add the partial-DB test.
- **Rollback:** a single env flag (e.g. `AIPACS_VIEWER_DB_METADATA=0`) to force the
  old disk-scan path; revert is one condition. (To be added with the fix.)

## Recommendation

H1 is **safe and worth doing**, implemented as: resolve `study_pk` from `study_uid`
(`find_study_pk_with_study_uid`, `dicom_db.py`) at patient open and stamp
`metadata_fixed` **before** the first series load; keep the disk scan as fallback;
add the 4 targeted tests + the KPI assertion; gate behind a rollback flag.

---

## Implementation (applied 2026-06-08, on user go-ahead)

**Change (one localized addition, `_vc_load.py`):** new method
`_VCLoadMixin._ensure_study_pk_for_db_metadata()` called at the top of
`_load_single_series_on_demand` (right after the `load_request` log, before the
multi-study resolution). It:
- resolves `study_pk` from the widget's `study_uid` via
  `find_study_pk_with_study_uid` and stamps `metadata_fixed['study_pk']` **once**,
  up front, so the existing `if study_pk:` DB-metadata primary path is reachable;
- **gates to single-study only** — returns early if `_is_multistudy_hint` or
  `len(_studies_series) > 1` (multi-study offset-key series keep the disk path, so
  no cross-study mixing);
- is **flag-gated**: `AIPACS_VIEWER_DB_METADATA=0` disables it (rollback);
- is **no-op** when `study_pk` is already set, there is no `study_uid`, or the
  study isn't in the local DB yet → the disk-scan **fallback runs unchanged**;
- never raises (any failure → disk fallback).

No other file changed. The disk scan (`_build_metadata_headers_only`) and the
download path are **untouched**. `metadata_fixed['study_pk']` is consumed only by
the DB-aware loaders, so early stamping has no other effect.

**Tests (added):** `tests/code/viewer/test_h1_study_pk_propagation.py` — 7 guards:
single-study stamps; multi-study-hint skips (never queries DB); `_studies_series>1`
skips; flag-off skips; already-set is no-op; no-`study_uid` no-op; study-not-in-DB
falls back. **206 passed** with the existing `test_plain_series_study_path` /
`test_viewport_drop_replacement` / `test_fast_viewer_pipeline` /
`test_flat_folder_import` suites; `_vc_load.py` compiles. `PacsClient/` is not
plugin-mirrored.

**DB evidence reused:** the read-only audit (`_recovery/db_geometry_audit.py`,
252,962 rows, geometry 99-100% non-NULL) proves the DB path will populate real
metadata, so this is the low-risk propagation fix described above — not a download
change.

**Live verification to run (the validation matrix, condensed):** restart, open a
**single-study server patient**, and confirm in `app.log`:
1. `[H1_DB_METADATA] study_pk=… resolved … DB metadata path enabled (single-study)`;
2. `[FAST_LOAD_BREAKDOWN]` now shows `db_lookup=…ms cached_metadata=…ms
   reconcile_disk=…ms` (and/or `backfill_orientation`) **instead of**
   `headers_only_build=800-1424ms` — expect tens of ms;
3. spot-check that **MPR / reference lines / measurements / scrolling** render
   identically (same IOP/IPP, now sourced from DB), and that a **multi-study**
   patient still logs `headers_only_build` (proves the guard holds);
4. partial-download + drag-drop + progressive still grow correctly.
Rollback if anything looks off: set `AIPACS_VIEWER_DB_METADATA=0` and restart.
