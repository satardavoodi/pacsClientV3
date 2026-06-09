# AI-PACS — High-level architecture review: are the current data paths the best paths? (2026-06-08)

A read-only, structural overlook (no code changed) of the major data routes —
download, cache, database, disk I/O, viewer load, thumbnails, progressive
loading, UI↔backend, module interaction, resource ownership, threading. The
question is not "is each path tuned" (we've tuned many) but **"is the route
itself the right route, or is there a simpler one the original design missed."**

Bottom line: the pipelines are, with **one important exception**, structurally
reasonable and already well optimized. The one exception is a genuine
design-level detour with a large, *safe* upside — and it is exactly the kind the
user described: **the viewer reads metadata from disk that the database already
holds.**

---

## 0. The headline finding (the one that matters)

**Every DICOM header in a series is parsed twice — once by the downloader into
the database, once again by the viewer off the disk — because the viewer never
asks the database for it.**

The evidence, end to end:

1. **The downloader already extracts and persists per-instance geometry.**
   `SeriesDownloader._save_series_instances_to_db` (`series_downloader.py`
   ~965-1011) reads **every** downloaded DICOM header *in parallel* (8-worker
   `ThreadPoolExecutor`, line 1000-1005), pulls `ImageOrientationPatient`,
   `ImagePositionPatient`, `PixelSpacing`, rows, columns, WW/WC, direction, and
   writes them to the `instances` table via `batch_insert_instances`
   (`database_manager.py:383`, `dicom_db.py:631` `insert_instances_batch`).
2. **The `instances` table is built to hold exactly that** — columns
   `image_position_patient`, `image_orientation_patient`, `pixel_spacing`,
   `rows`, `columns`, `slice_thickness`, `rescale_slope/intercept`,
   `bits_allocated`, `pixel_representation` (`dicom_db.py:158-184`).
3. **The viewer has a fast DB path** — `load_single_series_by_number`'s FAST
   `pydicom_qt` branch (`image_io.py` ~2576) does
   `find_series_pk_by_number(series_number, study_pk)` →
   `get_instances_by_series_pk` → `_get_cached_metadata`. **But it is gated on
   `if study_pk:`.**
4. **`study_pk` is essentially never available at load time for server-opened
   studies.** It is only stamped into `parent_widget.metadata_fixed['study_pk']`
   *inside* `_apply_loaded_series_data` (`_vc_load.py:784-793`), which runs
   **after** a series has already loaded, and only behind a
   `if not metadata_fixed or len(metadata_fixed) < 3:` guard that is already
   satisfied (so the block is skipped) for a server-opened tab.
5. **So the DB path is skipped and the viewer falls back to
   `_build_metadata_headers_only`** — re-reading **all** N DICOM headers off disk.
   Measured live: `headers_only_build = 800 ms` (450 files) / `1424 ms` (428
   files) — the dominant cost of first-opening a series.

This is the textbook version of the user's own example: *"data is currently
being read from disk when it could be read more directly from the database."*
The database is the authoritative, indexed copy; the downloader filled it; the
viewer ignores it and re-derives the same numbers from 450 files.

**Why it survived:** the disk scan was historically the *only* path (pre-DB), and
when the DB path was added it was correctly gated on `study_pk` — but the one
wiring step that makes `study_pk` available *before* the first series load was
never added for the server-open flow. Each later optimization (parallel-ish
scan, `specific_tags`) tuned the **disk** route instead of taking the **DB**
route. We optimized the detour rather than removing it.

**The fix is conservative (see §5):** resolve `study_pk` from the already-known
`study_uid` at open time and put it in `metadata_fixed` *before* series loads.
The FAST load then reads metadata from one indexed query (tens of ms) and only
touches disk for instances whose geometry is genuinely missing
(`_reconcile_db_instances_with_disk` + `_backfill_instance_orientation` already
handle that). The disk scan **stays as the fallback** — nothing is removed, the
safety net is intact. Expected: first-series-open header cost ~800-1400 ms →
~tens of ms for the common (fully-downloaded) case. This is the single largest
structural win available and it does not touch the download or render contract.

---

## 1. Are the current paths structurally reasonable?

Mostly **yes**. The spine is sound:

- **Transport is single and correct.** Everything (patient list, thumbnails,
  DICOM image bytes) goes over the socket stack (`modules/network/socket_client.py`).
  gRPC is retired. There is no live dual-transport confusion at runtime.
- **Download writes are atomic and resumable** (`*.part` → `os.replace`, resume
  scan rejects partials), and the subprocess shares the live `dicom.db` with
  DB-lock retry/backoff. This is a correct, well-guarded design — do not disturb.
- **Progressive grow is incremental, off-thread, batch-buffered, interaction-
  deferred, render-coalesced.** No full-refresh per batch. Already audited clean.
- **The viewer is metadata-first / lazy-pixel** (decode slices on demand), which
  is the right shape for large series.

The exception is the metadata route in §0: a real structural detour, not just an
un-tuned path.

---

## 2. Is there a major shortcut / simpler path?

**Yes — the DB-metadata shortcut in §0.** It collapses two full header parses
(download + view) into one (download only), and turns the viewer's per-series
open from an O(N-file disk scan) into an O(1 indexed query). Everything needed
already exists (the columns, the writer, the reader, the backfill); the only
missing wire is `study_pk` propagation. This is the "simpler route the original
design did not use."

Smaller shortcuts exist too (§4) but none with this leverage.

---

## 3. Already well optimized — do NOT disturb

These are load-bearing and correct; touching them is pure downside:

- **Atomic download writes + resume + DB-lock backoff** (`series_downloader.py`,
  `database_manager.py`).
- **Progressive grow / additive cache** (`lightweight_2d_pipeline.refresh_file_list`,
  `qt_viewer_bridge.grow`) — ~0.5 ms/flush, off-thread, no forced repaint.
- **Render coalescing + the single-vs-double-click debounce + the cross-patient
  isolation guards + the batch-boundary yield** — all recently hardened, all
  guarded by tests.
- **Socket transport + the GetStudyInfo single-probe + TTL `server_capabilities`
  cache.**
- **Lazy pixel decode + prefetch band** in `PyDicomLazyVolume`.
- **Atomic single-instance lock / clean shutdown.**

Fix A from this session (sequential + `specific_tags` header scan) stays useful
as the **fallback** path's tuning even after §0 lands.

---

## 4. Hidden / structural inefficiencies (ranked)

| # | Inefficiency | Evidence | Impact |
|---|---|---|---|
| **H1** | **Duplicate header parse: viewer re-reads disk metadata the DB already has** (§0) | `series_downloader.py:965-1011` writes geometry to DB; `image_io._build_metadata_headers_only` re-reads it; `study_pk` never propagated (`_vc_load.py:793`) | **High** — 800-1424 ms per first series open |
| H2 | **Two redundant in-memory series caches** | `_series_cache` and `_hot_series_cache` hold the same `(vtk, metadata, idx)` tuples | Low (memory + bookkeeping), structural clutter |
| H3 | **ZetaBoost holds full 3D volumes in RAM, but the lazy loader still re-decodes slices from the disk pixel cache** instead of reading the in-RAM volume | viewer cache survey | Low-Med — RAM held without serving the read it could serve |
| H4 | **Two thumbnail caches; one is dead** | live `ThumbnailStore` (`modules/storage/thumbnail_store.py`) vs never-populated legacy `ThumbnailCache` (`modules/download_manager/storage/thumbnail_cache.py`) | Low — dead code + double decode (store insert + sidebar `ThumbnailImageSourceService`) |
| H5 | **Dead gRPC stack still in tree** | `modules/network/dicom_service_pb2*.py`, `grpc_client.py`, `multi.py`; `GrpcMetadataClient` is **socket-backed despite its name** | None at runtime — pure confusion / maintenance tax |
| H6 | **`disk_pixel_cache` (.apc) is a third copy of pixels** (DICOM on disk → decoded .apc on disk → RAM) | viewer cache survey | Med but **intentional** (avoids re-decode); keep, just be aware it's a 3rd materialization |

H1 dwarfs the rest. H2/H4/H5 are cleanup, not performance.

---

## 5. Safe, conservative changes (recommended, in order)

1. **(H1 — do this) Propagate `study_pk` before the first series load.** At
   patient open, resolve the local study row from the known `study_uid` (the
   study already exists — the downloader created it) and stamp
   `metadata_fixed['study_pk']` (and `patient_pk`) *before* any
   `load_single_series_by_number` call. Keep the disk header scan as the
   fallback for missing/partial DB rows. **Net: removes the duplicate parse for
   the common case; no change to download, render, or the fallback.** Risk:
   **low-moderate** — it's a read-path key-propagation, not a data-format or
   contract change; gated so a missing/NULL DB still falls back exactly as today.
   Must be verified live (confirm the DB path actually populates geometry for a
   server-opened study, and that `[FAST_LOAD_BREAKDOWN]` drops to a `db_lookup`/
   `cached_metadata` breakdown instead of `headers_only_build`).
2. **(H5) Delete the dead gRPC modules** (or move to `_recovery/`), and rename
   `GrpcMetadataClient` → `SocketMetadataClient`. Zero runtime risk, large
   clarity gain. Pure cleanup.
3. **(H4) Remove the never-populated legacy `ThumbnailCache`**; keep the single
   `ThumbnailStore`. Cleanup.
4. **(H2) Collapse `_hot_series_cache` into `_series_cache`** (or document why
   both exist). Small, test-guarded.

All four are "tidy the map" changes: none alters a clinical data format, the
download contract, or the render path.

---

## 6. Risky — do NOT do without deep testing

- **Rewriting the viewer cache layers** (H2/H3/H6 consolidation into one store).
  The layering is subtle (preview vs full vs progressive vs paired-viewer sync);
  a wrong move reintroduces stuck-slice / flicker / cross-series bugs we already
  fixed. Leave the layers; only de-dup the obviously identical pair (H2) with
  tests.
- **Making the DB the *sole* metadata source (removing the disk fallback).** The
  fallback is a real safety net during active download / partial DB. Keep it.
- **Changing the download→DB write shape** (e.g. to store full volumes or
  pre-sorted geometry). High blast radius on the clinical write path.
- **Throwaway-widget startup warm** (first-tab cold start). Already evaluated and
  declined this session — side-effect/leak risk for a sub-second, once-per-
  session cost.
- **Single-process (merge download subprocess into main).** The subprocess
  isolation is a stability feature (crash containment, CPU class). Do not merge.

---

## 7. The one obvious design-level issue with large upside

**H1 — the disk-vs-DB metadata detour (§0).** It is the only finding that is both
(a) clearly a wrong *route* rather than an un-tuned one, and (b) high-impact
(hundreds of ms to >1 s per first series open, on every server-opened study) and
(c) fixable *conservatively* (propagate one key; keep the disk fallback). It is
the direct answer to the user's question: yes, the software is currently
optimized along an existing route (disk header scan) when a simpler route (the
database the downloader already populated) exists right next to it.

Everything else is either already optimal (§3) or low-value cleanup (§4 H2/H4/H5).

---

## Suggested validation for H1 before any change (read-only first)

To *prove* the DB already has usable geometry for a server-opened study (so the
fix is just propagation, not a download change), run a read-only query against a
copy of `dicom.db`: for a recently fully-downloaded study, check that
`instances.image_orientation_patient` / `image_position_patient` are non-NULL for
its series. If they are populated → H1 is purely a propagation fix (low risk). If
they are NULL → the downloader's geometry write is the real gap and H1 moves to
"riskier" (a download-path change). The §0 evidence (`series_downloader.py:991-
993` writes them) says they should be populated, but confirm on real data first.
