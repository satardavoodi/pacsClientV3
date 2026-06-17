# Multi-Study and Multi-Patient-ID Architecture Review

Date: 2026-06-16

Status: evaluation only. No application code changes are included in this report.

Scope: patient/study identity, multi-study grouping, download and restore logic,
cache/database/disk synchronization, import behavior, and DICOMized document
workflow.

## Executive Summary

The current architecture has a mostly sound study-level storage model: studies
are separated by `StudyInstanceUID`, DICOM files are stored under a study-UID
root, thumbnails are keyed by `(study_uid, series_number)`, and recent sync work
uses a disk-first manifest plus server `contentVersion` to avoid stale local
state. The double-click open path also contains important multi-study and
cross-patient guards.

The main weakness is not the basic study folder layout. The main weakness is
identity translation at boundaries. The system has several identifiers with
different scopes:

- `PatientID` is treated as the local patient key.
- `StudyInstanceUID` is the true study identity and disk root.
- `SeriesInstanceUID` is the true series identity.
- `SeriesNumber` is only study-local and can repeat in every study.
- The viewer creates synthetic multi-study display keys such as `1000003` to
  avoid UI collisions.

Most recurring multi-study bugs come from one of these values escaping its
proper scope. The most concrete current risk is the viewer-to-download-manager
handoff: multi-study viewer entries correctly preserve `study_uid`,
`_orig_series_number`, and `series_path`, but some post-open interaction paths
still notify the Download Manager using the tab's primary `study_uid` plus the
synthetic display key. The Download Manager currently accepts that pair without
membership validation and can write a critical-intent file for a series that does
not exist in that study. That is a high-risk source of impossible image counts,
wrong priority behavior, and repeated download confusion.

The second major weakness is patient identity. The database has
`patients.patient_id TEXT UNIQUE` but no issuer, assigning authority, master
patient, or alias table. That is enough for simple PACS data, but it cannot
correctly model either of these real clinical cases:

- The same real patient appears under multiple Patient IDs.
- Different real patients share the same Patient ID from different issuers or
  imported sources.

The system can keep studies separated by `StudyInstanceUID`, but it cannot
decide whether multiple Patient IDs represent one real person without a separate
patient-identity model and explicit merge/link policy.

## Sources Inspected

Documentation reviewed:

- `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`
- `docs/pipelines/download-pipeline.md`
- `docs/pipelines/thumbnail-pipeline.md`
- `docs/pipelines/SYNC_DOWNLOAD_OPEN_PIPELINE_AS_BUILT.md`
- `docs/architecture/database-architecture.md`
- `docs/architecture/SYNC_MODE_SEPARATION.md`
- `docs/reports/CROSS_PATIENT_STUDY_MIXING_44504_2026-06-02.md`
- `docs/reports/MULTI_STUDY_MULTIMODALITY_44534_2026-06-02.md`
- `docs/reports/DOC_ATTACHMENT_MISSING_45932_2026-06-11.md`
- `docs/reports/IMPORT_PIPELINE_COMPRESSED_DICOM_2026-06-06.md`
- `docs/reports/SYNC_DOWNLOAD_LIFECYCLE_REVIEW_2026-06-15.md`
- `docs/reports/SESSION_SUMMARY_SYNC_MULTISTUDY_2026-06-16.md`
- `docs/reports/stress_2026-06-16/*`

Key code areas inspected:

- `database/dicom_db.py`
- `database/download_progress_db.py`
- `PacsClient/utils/data_paths.py`
- `PacsClient/utils/config.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_search.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_modules.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_import.py`
- `PacsClient/pacs/workstation_ui/home_ui/import_preview_dialog.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_db_service.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_study_save.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_series.py`
- `modules/storage/sync_manifest.py`
- `modules/storage/content_version_store.py`
- `modules/storage/sync_mode_policy.py`
- `modules/storage/thumbnail_store.py`
- `modules/download_manager/core/models.py`
- `modules/download_manager/ui/widget/_dm_queue.py`
- `modules/download_manager/ui/widget/_dm_priority.py`
- `modules/download_manager/coordinator/series_intent_coordinator.py`
- `modules/download_manager/download/executor.py`
- `modules/download_manager/download/series_downloader.py`

Regression tests reviewed:

- `tests/code/ui_services/test_resolve_patient_study_uids_scope.py`
- `tests/code/ui_services/test_resync_on_reopen.py`
- `tests/code/storage/test_sync_manifest.py`
- `tests/code/storage/test_sync_mode_policy.py`
- `tests/code/storage/test_open_skip_download_when_complete.py`
- `tests/code/storage/test_import_prepare_all_studies.py`
- `tests/code/download_manager/test_download_task_dedup.py`
- `tests/code/download_manager/test_series_dedup_count_guard.py`
- `tests/code/download_manager/test_dm_preempt_on_drag.py`
- `tests/code/viewer/test_viewport_drop_replacement.py`
- `tests/code/viewer/test_plain_series_study_path.py`
- `tests/code/system/test_modality_summary_doc_merge.py`

## Current Identifier Model

### Patient identity

The local patient table is:

```text
patients(
  patient_pk INTEGER PRIMARY KEY,
  patient_id TEXT UNIQUE,
  patient_name TEXT,
  birth_date TEXT,
  sex TEXT,
  age TEXT,
  patient_weight TEXT
)
```

This means `PatientID` is the only durable local patient key. There is no
`IssuerOfPatientID`, no assigning authority, no source-system namespace, and no
master-patient/person record above `patients`.

This is acceptable for simple single-source data where Patient IDs are globally
unique. It is fragile for imports, CDs, multi-center data, and DICOMized
documents that may carry a slightly different Patient ID from the same real
patient.

### Study identity

The study table uses:

```text
studies(
  study_pk INTEGER PRIMARY KEY,
  study_uid TEXT UNIQUE,
  patient_fk INTEGER NOT NULL,
  ...
  study_path TEXT
)
```

`StudyInstanceUID` is the strongest identity in the current design. It is unique
in the database and is also the disk-storage root:

```text
SOURCE_PATH/<study_uid>/
```

This is the right unit for clinical data isolation. It means two studies under
one patient remain physically separated on disk.

### Series identity

The series table uses:

```text
series(
  series_pk INTEGER PRIMARY KEY,
  series_uid TEXT UNIQUE,
  study_fk INTEGER NOT NULL,
  series_number INTEGER,
  image_count INTEGER,
  thumbnail_path TEXT,
  series_path TEXT
)
```

`SeriesInstanceUID` is globally unique and should be the primary series identity
whenever it is available. `SeriesNumber` is not globally unique. It only has
meaning inside one study.

The project already recognizes this in `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`.
The viewer uses offset keys for multi-study display only:

- Primary study keeps real series numbers.
- Secondary studies use `study_slot * 1_000_000 + original_series_number`.
- Each rebuilt entry carries:
  - `study_uid`
  - `_orig_series_number`
  - `_study_slot`
  - absolute `series_path`

That design is correct. The remaining risk is that some downstream callers do
not consistently translate the display key back to canonical identity.

### Instance identity

Instances are keyed by `SOPInstanceUID`:

```text
instances(
  instance_pk INTEGER PRIMARY KEY,
  sop_uid TEXT UNIQUE,
  series_fk INTEGER NOT NULL,
  instance_path TEXT,
  instance_number INTEGER,
  geometry/window fields...
)
```

The viewer still primarily trusts files on disk for image loading. Instance rows
are an accelerator and metadata source. Stress-report findings show some
downloaded files can exist without matching `instances` rows, so DB instance
counts should not be the sole completion authority.

## Storage, Cache, and Truth Model

### Disk layout

The path registry centralizes user data under `user_data/`:

```text
user_data/
  patients/
    dicom/<study_uid>/<series_number>/*.dcm
    thumbnails/<study_uid>/<series_number>.png
    attachments/
  database/dicom.db
  content_versions.json
```

This layout is study-rooted, not patient-rooted. That is good because a study
remains isolated even if patient grouping is wrong. The weakness is the inverse:
if the database links a study to the wrong patient, the disk folder still looks
valid, because disk paths do not encode patient ownership.

### Database

The database is the durable local index. Its strengths are:

- Normalized DICOM hierarchy: Patient -> Study -> Series -> Instance.
- Unique constraints on study, series, and instance UIDs.
- Foreign-key indexes for common joins.
- Download progress mirrored by `study_uid`.

Its weak points are:

- `patient_id` is unique without issuer/source.
- `insert_study()` updates `patient_fk` on `study_uid` conflict.
- `insert_series()` updates `study_fk` on `series_uid` conflict.
- Existing series can be skipped in `save_complete_study_info()` rather than
  refreshed with new `image_count`, `series_path`, or description.

The conflict-update behavior is efficient for normal refreshes, but dangerous
if a caller passes a wrong patient or study. A mis-association can become
durable.

### Thumbnail cache

The thumbnail architecture is strong:

- Canonical disk path: `THUMBNAIL_PATH/<study_uid>/<series_number>.png`
- In-memory cache key: `(study_uid, series_number)`
- `series.thumbnail_path` is only a hint, not the authority.

Recent gate fixes are also correct:

- Patient-level aggregate `count_of_series` is not attributed to a single study
  when `total_studies > 1`.
- The server-refresh marker is keyed like `uid@server_series`, so growth can be
  detected after a previous refresh.

### Sync manifest and content version

`modules/storage/sync_manifest.py` is the best current model for local state. It
builds a disk-first read model, using DB as hints and the server series list
when available. It reports:

- missing series
- partial series
- missing thumbnails
- local state such as not downloaded, partial, downloaded, stale, or
  thumbnail-only

`content_version_store.py` stores the last server `contentVersion` that was
confirmed complete locally. This is correct because server-side growth can
include image instances and non-image content such as documents, attachments,
voice, and captures.

The remaining weakness is duplication. Older completeness functions and
download-state checks still coexist with `sync_manifest`, so different paths can
arrive at subtly different conclusions.

## Main Workflows

### Server search and patient rows

The server patient list supplies patient rows with fields such as:

- `patient_id`
- `patient_name`
- `latest_study_uid`
- `study_uids`
- `modalities`
- `total_studies`
- `count_of_series`

The default server response can return only the latest study UID even when
`total_studies > 1`. This was the root of the 44534 multi-modality bug. The
client now compensates by querying once per modality when the row reports
multiple modalities and not all studies are known.

That fix is conceptually correct. It preserves the common case because
single-modality rows add no extra query.

### Single-click selection

Single-click is meant to be selection and preview only:

- Local thumbnails are shown first if available.
- Server thumbnails are fetched if needed.
- Multi-study reconcile can run in the background.
- Full study download is not started by default.

This is correct. It avoids turning simple browsing into a download storm.

The remaining fragility is late discovery. If an additional study, especially a
DOC study, is discovered after the right panel or viewer sidebar has already
rendered, the UI may not refresh in the same session. The document report for
patient 46024 shows exactly this first-open behavior.

### Double-click open

The double-click path is the most important user workflow. Its current structure
is broadly correct:

1. Resolve all candidate study UIDs for the patient.
2. Add per-modality-discovered studies when needed.
3. Create the patient tab quickly.
4. For each study UID:
   - fetch fresh study/series info
   - check server `patient_id` ownership for extra studies
   - save study metadata
   - evaluate local sync state
   - queue only missing or partial series
5. Aggregate full series metadata into the viewer.
6. Render grouped thumbnails for multi-study patients.

This path has the important cross-patient guard that was missing in earlier
bugs: a non-clicked study is skipped if the server says its `patient_id` belongs
to another patient.

### Multi-study viewer grouping

The viewer's multi-study index rebuild is a good design:

```text
display_key = original_series_number + study_slot * 1_000_000
```

The rebuilt entry keeps:

```text
entry["series_number"] = display_key
entry["_orig_series_number"] = original_series_number
entry["_study_slot"] = slot
entry["study_uid"] = actual_study_uid
entry["series_path"] = SOURCE_PATH / actual_study_uid / original_series_number
```

This solves the UI problem that series numbers collide across studies. It also
contains the data needed to route disk/server/download calls correctly.

The problem is not this design. The problem is incomplete enforcement at call
sites.

### Download queue and task model

The Download Manager operates per study:

- one task per `study_uid`
- task state in memory
- progress mirrored to `download_progress`
- worker subprocess fetches authoritative metadata
- disk writes under `SOURCE_PATH/<study_uid>/<series_number>`
- instance rows are written after download

Recent de-duplication in `DownloadTask` is valuable. It collapses duplicate
series by `SeriesInstanceUID`, and when no UID exists, by series number. This
protects task creation from impossible totals caused by repeated drag payloads.

However, task-creation de-dup does not fully protect runtime priority intent.
The critical-series path can still accept a wrong study/series pair after the
task exists.

### Critical series and drag/drop priority

When the user drags or views a series, the viewer notifies the Download Manager
so that series can become critical. The intended identity should be:

```text
actual study_uid + original series_number + optional series_uid
```

For multi-study secondary entries, the current viewer metadata contains those
actual values. But inspected code shows interaction paths that still use:

```text
parent_widget.study_uid + synthetic display series_number
```

Examples:

- `_vc_load.py::_notify_dm_viewed_series()`
- `_vc_load.py::_trigger_download_if_needed()`
- `_pw_series.py::_on_retry_series_download()` receives what the caller passes
  and forwards to `request_critical_series_download()`.

The Download Manager side then:

- sets `viewed_series_number`
- may write `.critical_intent.json`
- does not verify that the requested series exists in the task's series list
- lets the downloader reorder based on the intent file

In `series_downloader.py`, when a series yields to a critical intent, the code
mutates `series_list` and later calculates totals from the mutated list. The
comment explicitly accepts temporary denominator inflation as cosmetic. That is
not safe enough for invalid or stale intent, especially with multi-study display
keys.

This is the highest-priority architectural concern found in this review.

### Import workflow

The import scanner reads DICOM headers, groups by `StudyInstanceUID` and
`SeriesInstanceUID`, and tracks patient identity warnings. The import destination
is:

```text
SOURCE_PATH/<study_uid>/<series_storage_name>/
```

Recent import work correctly prepares every imported study for fast open, not
only the primary one. That fixes a major multi-study import usability issue.

The remaining issue is policy. The scanner warns on multiple Patient IDs in a
folder, but the product has no master-patient model and no explicit merge/split
workflow. That means it can import multiple Patient IDs, but it cannot say
whether they are aliases for the same real person or distinct people.

### DICOMized documents

The product supports two document shapes:

1. A document series inside an imaging study, commonly `SeriesNumber #100000`
   and modality `DOC`.
2. A separate DOC study with its own `StudyInstanceUID`, often in the
   `1.2.826...` UID family.

The viewer can render document series, and the home summary merges DOC into the
parent modality instead of treating it as a separate clinical modality.

The fragile part is discovery. Separate DOC studies are only found if the server
patient aggregation reports the DOC modality/study or if per-modality
enumeration is triggered. If the server says the patient is single-modality MR
and hides the DOC study, the client does not currently discover it. Patient
45932 demonstrated a server-side linkage gap. Patient 46024 then demonstrated a
client-side first-open refresh gap after the server fix.

## What Is Correct

The following parts are architecturally correct and should be preserved:

- Study-rooted disk storage by `StudyInstanceUID`.
- Unique database keys for studies, series, and instances.
- Thumbnail identity by `(study_uid, series_number)`.
- Multi-study viewer offset keys as display-only collision avoiders.
- Preservation of `study_uid`, `_orig_series_number`, and `series_path` in
  multi-study viewer entries.
- Per-modality enumeration for server rows that hide non-latest studies.
- Cross-patient server-owner checks before queueing or persisting extra studies.
- Disk-first sync manifest with server comparison for missing/partial series.
- `contentVersion` as the cheap server-growth gate.
- Download-only-missing behavior on open and resync.
- One download task per study UID with duplicate enqueue prevention.
- Import grouping by DICOM study/series UIDs.
- Preparing all imported studies for fast open.
- Support for DOC series rendering and DOC-to-parent modality summary merging.

## Fragile or Incorrect Areas

### 1. Viewer display keys can leak into server/download identity

Severity: high.

The multi-study viewer correctly creates synthetic keys, but the Download
Manager should never receive those keys as real series numbers. It should
receive the entry's actual `study_uid` and `_orig_series_number`.

Current problematic shape:

```text
primary_tab_study_uid + "1000003"
```

Correct shape:

```text
secondary_study_uid + "3"
```

Likely symptoms:

- critical series request does nothing
- wrong study is marked critical
- intent file targets a non-existent series
- progress denominators inflate
- dragged not-yet-downloaded series does not download correctly
- multi-study patient appears to have impossible image counts

### 2. Download Manager critical intent lacks membership validation

Severity: high.

`request_critical_series()` checks that a study state exists, but it does not
verify that the requested series belongs to that study's task. The downloader
then treats the intent file as a valid ordering signal.

The Download Manager needs a defense-in-depth rule:

```text
Before setting viewed_series_number or writing critical intent:
  find the task for study_uid
  verify series_uid or series_number exists in task.series_list
  reject or normalize otherwise
```

### 3. Downloader progress depends on mutable runtime `series_list`

Severity: high.

The downloader reorders and can duplicate the current series after a yield. It
also computes final `total_series` and `total_images` from the same mutable
list. For valid intents this may only be cosmetic. For invalid intents it can
turn into impossible totals.

Progress should use an immutable manifest captured before runtime reordering.

### 4. Patient identity model cannot represent real-world aliases

Severity: high.

`patient_id TEXT UNIQUE` is not enough for:

- same real patient with multiple Patient IDs
- duplicate Patient IDs from different issuers
- imported folders from multiple institutions
- document studies with normalized or mismatched Patient IDs

The product needs a master-patient concept if it wants to group "same real
patient" across IDs safely.

### 5. Upserts can silently reassign ownership

Severity: high.

`insert_study()` updates `patient_fk` when `study_uid` already exists.
`insert_series()` updates `study_fk` when `series_uid` already exists.

This should not be silent. If an existing study is linked to patient A and a
caller tries to save it under patient B, that is either:

- a real correction requiring an explicit migration path, or
- a cross-patient bug that must be rejected/quarantined.

### 6. Study discovery still depends on fallbacks and caches

Severity: medium-high.

`_resolve_patient_study_uids()` merges data from:

- table row metadata
- right-panel thumbnails
- `_patient_study_uid_map`
- clicked fallback UID

There is now a local DB owner guard, and later server-owner checks protect
critical persist/download paths. That is much better than before. But studies
with unknown local owner are intentionally kept so fresh server opens work.

That means any caller that consumes resolved UIDs without server validation can
still be risky.

### 7. DICOMized document discovery depends on server aggregation

Severity: medium-high.

The workstation handles DOC rendering once it receives the DOC series/study.
The weak point is being told the DOC study exists. A separate DOC study can be
missed if:

- `GetPatientList` does not include DOC in modalities.
- `total_studies` or `study_uids` are incomplete.
- PatientID linkage differs between the document study and imaging study.
- A late async discovery/download happens after the first render and does not
  trigger a viewer/right-panel refresh.

### 8. Existing series metadata can become stale

Severity: medium.

`save_complete_study_info()` skips an existing series when `find_series_pk()`
returns a row. That means refreshed server metadata may not update:

- `image_count`
- `series_path`
- description/protocol/body part
- thumbnail hints

The downloader may update `series_path` later, but metadata freshness should not
depend on a full download.

### 9. Multiple completeness systems coexist

Severity: medium.

The sync manifest is the best current read model, but older checks still exist.
This creates risk that:

- table status
- open-skip logic
- resync logic
- DM resume logic
- right-panel gates

disagree about what "complete" means.

### 10. Import warns about multi-patient input but does not enforce policy

Severity: medium.

The import preview detects multiple Patient IDs and warns. That is useful, but
not enough for complex clinical data. The system needs a policy decision:

- import as separate patients
- group under a master patient
- require explicit user selection
- reject mixed-patient folders by default

### 11. Disk can be ahead of DB instance rows

Severity: medium.

The stress report found sampled studies where `.dcm` files exist on disk but
some `instances` rows are missing. This is safer than the opposite direction for
image viewing, because the viewer can read disk. But it can distort DB-based
counts, completion displays, and analytics.

### 12. Performance bottlenecks amplify multi-study problems

Severity: medium.

Known bottlenecks include:

- header rescans during first-series open
- multi-study grouped render with many studies/series
- socket report-status calls holding a shared client lock
- thumbnail base64 server fetches for large studies
- DB instance insert/update under download pressure
- a single active download slot interacting with critical preemption

These are not all correctness bugs, but they make users click repeatedly or
switch contexts while the app is still reconciling. That increases the chance of
identity/cache races.

### 13. Documentation and comments have minor drift

Severity: low-medium.

`sync_mode_policy.py` says LocalDatabase auto server sync defaults ON, and tests
pin that. Some nearby comments in home-panel code have historically implied the
opposite. This should be cleaned up because mode semantics affect data freshness
and user trust.

## Answers to the Specific Review Questions

| Question | Current behavior | Assessment |
|---|---|---|
| 1. How are patients identified? | By local `patients.patient_id`, unique in DB. | Simple and fast, but incomplete for multi-issuer and same-real-patient/multiple-ID cases. |
| 2. How are studies identified? | By unique `StudyInstanceUID`, also used as disk root. | Correct and strong. |
| 3. How are multiple studies under the same patient handled? | Resolved from table metadata, caches, and per-modality enumeration; rendered as grouped single tab with offset series keys. | Mostly correct after recent fixes, but fallback sources remain risky unless server ownership is rechecked. |
| 4. How are different Patient IDs handled? | As different patients. | Correct only if every Patient ID is globally unique. No alias/master-patient model exists. |
| 5. How are DICOMized documents inserted and represented? | As DOC series inside imaging studies or separate DOC studies. Viewer can render them. | Rendering is good. Discovery depends too heavily on server aggregation and has a first-open refresh gap. |
| 6. How are downloads queued and tracked? | One task per study UID; state in memory; progress mirrored to DB; open queues missing/partial series only. | Study-level queue is good. Critical-series runtime intent needs stronger validation. |
| 7. How are studies stored on disk? | `SOURCE_PATH/<study_uid>/<series_number>/*.dcm`; thumbnails under `THUMBNAIL_PATH/<study_uid>/<series_number>.png`. | Correct separation by study. |
| 8. How are studies restored from disk? | Viewer and sync code read disk folders, DB hints, and cached thumbnails. | Disk-first is correct. DB metadata drift still affects counts and speed. |
| 9. How do cache and DB records relate to studies? | DB indexes the hierarchy; thumbnail cache keys by study/series; content versions stored per study. | Good direction, but several caches and state stores still duplicate completeness decisions. |
| 10. Where are weak points or flaws? | Viewer->DM identity translation, PatientID model, silent ownership upserts, DOC discovery, duplicated completeness logic, disk/DB drift. | These are the main architectural risks. |

## Likely Root Causes of Recurring Bugs

### Multi-study patient works on first open but fails after interaction

Likely cause: initial open uses the stronger multi-study path, while later
drag/drop or retry uses a weaker path that does not resolve the display key back
to actual study/series identity.

### Patient shows another patient's study

Likely cause: a fallback study UID from right-panel/cache/search state leaked
into the current patient. Recent server-owner checks significantly reduce this,
but silent DB reassignment and unknown-owner fallbacks mean this class should
remain guarded.

### Patient with MR and DX shows only one study

Known cause: default server patient list returns only latest study UID. Current
per-modality enumeration is the right mitigation.

### Document appears only after reopen

Known cause: late discovery/download of an additional DOC study after first UI
render, without re-rendering the right panel or viewer series sidebar in the
same session.

### Impossible Download Manager counts

Known partial cause: duplicate series rows in task creation. A guard exists.
Remaining likely cause: invalid runtime critical intent plus mutable
`series_list` totals.

### Same real patient has multiple Patient IDs

Architectural cause: no master-patient/alias model. The application can only
show them as separate patients unless something upstream normalizes IDs.

## Recommended Roadmap

### P0: Stop identity leaks and impossible counts

1. Add a canonical viewer series resolver for all viewer-to-download calls.

   Input can be display key, series UID, or thumbnail entry. Output must be:

   ```text
   StudySeriesIdentity(
     study_uid,
     original_series_number,
     display_series_key,
     series_uid,
     series_path
   )
   ```

   All calls to `set_viewed_series()` and
   `request_critical_series_download()` should use this resolver.

2. Add Download Manager membership validation.

   Reject critical intent when the requested series is not in the task's series
   list for that study. Prefer matching by `series_uid`, then by original
   `series_number`.

3. Make downloader progress totals immutable.

   Capture `original_total_images` and `original_total_series` before runtime
   reordering. Runtime yield/requeue should never change progress denominators.

4. Add regression tests for the exact secondary-study case.

   Required tests:

   - secondary study series `3` with display key `1000003` sends
     `secondary_study_uid + 3`, not `primary_study_uid + 1000003`
   - invalid critical intent is rejected and does not write
     `.critical_intent.json`
   - downloader yield with invalid target does not mutate totals
   - patient 46912-style repeated drag cannot inflate runtime progress

### P1: Strengthen ownership and patient identity

5. Prevent silent study/series reassignment.

   `insert_study()` and `insert_series()` should not silently change ownership
   on unique conflict. They should validate expected owner and return a conflict
   result or log a quarantine event.

6. Introduce a clinical patient identity model.

   Recommended tables:

   ```text
   master_patients(master_patient_pk, display_name, created_at, ...)
   patient_aliases(alias_pk, master_patient_fk, patient_id, issuer, source, ...)
   patients(patient_pk, alias_fk or master_patient_fk, patient_id, ...)
   ```

   Grouping multiple Patient IDs should be explicit and auditable.

7. Make study ownership server-authoritative before persistence.

   Centralize "can this study be saved under this patient?" into one service
   used by open, reconcile, import, offline-cloud, and document attach paths.

### P2: Consolidate sync and refresh behavior

8. Make `sync_manifest.evaluate_sync()` the single completeness decision API.

   Migrate older disk/DB completeness checks to call it or a thin wrapper around
   it.

9. Refresh existing series metadata.

   When fresh server study-info arrives, update existing series rows instead of
   skipping them completely.

10. Add a study-count-growth refresh path.

   If async reconcile discovers a new study UID for the active patient, refresh:

   - home right-panel grouped thumbnails
   - viewer sidebar series info if a tab is open
   - download queue for missing series only

11. Add a safe DOC discovery policy.

   Primary fix remains server-side patient/study aggregation. Client mitigation
   can be a gated DOC probe for single-modality patients, but only with strict
   server-owner validation and metrics.

### P3: Import and local/offline robustness

12. Define import policy for multi-patient folders.

   Options should be explicit in the UI:

   - split into separate patients
   - import selected patient only
   - link aliases under one master patient
   - reject mixed folders

13. Add a local reconciliation job.

   A background or manual diagnostic should compare:

   - DB studies/series/instances
   - disk folders/files
   - thumbnails
   - contentVersion store
   - download_progress

   It should report disk>DB and DB>disk drift separately.

14. Make all import writes atomic where possible.

   Converted compressed files already use temp plus replace. Non-converted
   copies should use the same pattern to avoid partial visible files.

### P4: Performance and observability

15. Reduce first-open header rescans.

   Use downloader/import-written DB metadata where complete and validated,
   especially for large multi-study patients.

16. Keep report-status socket calls isolated.

   The stress report showed shared socket locks can amplify multi-study stalls.
   Keep circuit-breakers and avoid sharing a long-timeout client with GUI
   thumbnail/patient-list requests.

17. Add identity-focused structured logs.

   Log normalized tuples:

   ```text
   patient_id, study_uid, series_uid, orig_series_number, display_key, source
   ```

   This will make future multi-study bugs much easier to diagnose.

## Proposed Acceptance Criteria

Before major changes in this area are considered complete:

- A multi-study patient with repeated `SeriesNumber` values can open, drag,
  download, and reopen without display-key leakage.
- A secondary-study series request never writes intent under the primary study.
- A study cannot be silently reassigned to a different patient by a normal
  metadata refresh.
- A multi-modality patient shows all server-owned studies.
- A separate DOC study appears on first open once discovered.
- Clearing local files causes the study to read as stale/not-downloaded, not
  complete.
- DB instance-row drift does not affect clinical image availability or progress
  totals.
- Importing a folder with multiple studies prepares every study for fast open.
- Importing multiple Patient IDs follows an explicit user-visible policy.

## Final Assessment

The system is not fundamentally wrong. Its strongest architectural decision is
using `StudyInstanceUID` as the durable study boundary across DB, disk, cache,
and downloads. That should remain the backbone.

The weak parts are the identity edges around that backbone. `PatientID` is being
asked to represent real-person identity, but it cannot. `SeriesNumber` is being
used in some places as if it were study-global, but it is only study-local. The
viewer has a good display-key scheme, but the contract that those keys must
never reach server/disk/download APIs is not fully enforced.

The highest-value next work is therefore small and surgical: canonicalize
viewer-to-download series identity, reject invalid critical intent in the
Download Manager, and freeze progress totals against runtime list mutation.
After that, the bigger architectural project is a real patient-alias/master
patient model and stricter ownership persistence.
