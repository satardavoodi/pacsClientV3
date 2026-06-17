# Unified Patient-Study Pipeline Recheck After Code Changes

Date: 2026-06-17

Status: evaluation only. This report documents the current code state after the
latest changes. No application code is changed by this report.

Related documents:

- `docs/reports/UNIFIED_PATIENT_STUDY_PIPELINE_REVIEW_2026-06-17.md`
- `docs/reports/UNIFIED_PIPELINE_EVALUATION_2026-06-17.md`
- `docs/reports/MULTI_STUDY_OPEN_VS_SELECT_DIVERGENCE_46630_2026-06-17.md`
- `docs/reports/MULTI_STUDY_CODE_CHANGE_REVIEW_2026-06-16.md`
- `docs/reports/MULTI_STUDY_MULTI_PATIENT_ID_ARCHITECTURE_REVIEW_2026-06-16.md`

## 1. Executive Summary

The latest changes move the project in the right direction. The code now contains:

- a pure, immutable `PatientStudySet` data contract;
- canonical study UID merge/diff helpers;
- optional shadow tracing for open-vs-late study-set divergence;
- a concrete open-viewer backfill path for late-discovered studies;
- stronger single-click no-download separation;
- an orphan-series DB self-heal;
- additional tests around the new patient-study-set and backfill logic.

This is a meaningful improvement over the previous state. In particular, the
46630 class of bug is now partly addressed: when a second study, such as a
DICOMized DOC study, is discovered after a viewer tab was already created, the
new backfill path can push that late study's series metadata into the open
viewer without closing and reopening the tab.

However, the current code is **not yet the final unified pipeline**. It is a
foundation plus targeted wiring.

The most important remaining gap is:

> Late-discovered studies can now be pushed into the open viewer as metadata,
> but they do not yet reliably produce an open-intent missing-only download plan.

For patient 46630-like cases, this means the DOC study may become visible in the
viewer sidebar, but its missing DICOM files can still remain unqueued because the
late discovery path still travels through single-click/deferred-reconcile logic
that intentionally skips downloads.

The second major remaining gap is architectural:

> The code has a `PatientStudySet` contract and helper functions, but not yet a
> full `PatientStudySetService` consumed by all workflows.

So the project is safer and closer, but still not "one optimized path" end to
end.

## 2. What Changed

### 2.1 New patient-study-set contract

New file:

```text
PacsClient/utils/patient_study_set.py
```

Key contents:

- `Intent`
- `Freshness`
- `PatientStudySetRequest`
- `SeriesDescriptor`
- `StudyDescriptor`
- `PatientStudySet`
- `merge_study_uids`
- `diff_study_uids`

Assessment:

- Good direction.
- Pure Python, no Qt/VTK/pydicom/numpy dependency.
- Safe as a foundation.
- Unit-tested.
- Still not a service and not yet the single authority used by all callers.

### 2.2 Open-time study-set shadow recording

Changed file:

```text
PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py
```

New behavior:

- `AIPACS_PATIENT_STUDY_SET_SHADOW`
- `_pss_record_open_studyset`
- `patient_study_set_open` trace

Assessment:

- Good diagnostic layer.
- Default off.
- Helps quantify when open resolves fewer studies than later reconcile.
- Does not itself fix the path.

### 2.3 Late open-viewer study-set backfill

Changed files:

```text
PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py
PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py
```

New behavior:

- `AIPACS_OPEN_TAB_STUDYSET_BACKFILL` default on.
- `_backfill_open_viewer_studyset`
- `_load_and_display_series_info` invokes backfill when reconcile returns a
  multi-study set and a viewer tab is open.
- Backfill fetches missing studies' series metadata.
- Backfill calls the viewer's merge-aware `set_server_series_info`.

Assessment:

- This directly addresses the viewer-metadata half of the 46630 issue.
- It is metadata-only and respects the rendering boundary.
- It is cross-patient guarded.
- It avoids duplicate pushes when the tab already has all studies.
- It has useful tests.
- It still does not enqueue missing files for late studies in open context.

### 2.4 Single-click download separation

Changed file:

```text
PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py
```

New behavior:

- `AIPACS_SINGLE_CLICK_DOWNLOAD` defaults off.
- Single-click reconcile and auto-resync refresh metadata/display but skip full
  image download.
- Manual forced refresh can still enqueue.
- Double-click open remains the path that should enqueue missing series.

Assessment:

- Correct product behavior.
- Prevents accidental download storms from selection/preview.
- Creates a subtle problem for late studies found while an open viewer exists:
  the code needs to know whether the late discovery belongs to an open-intent
  patient, not just a single-click preview.

### 2.5 Orphan-series self-heal

Changed file:

```text
database/dicom_db.py
```

New behavior:

- `prune_orphan_series_for_study`
- `find_orphan_series`
- open path calls `prune_orphan_series_for_study` for studies being opened.

Assessment:

- Useful for repairing DB rows that point to vanished series folders.
- Safety gates are strong:
  - no file deletion;
  - root must be reachable;
  - series must have instance rows;
  - series must have zero `.dcm` files;
  - whole-study file-less cases are treated as cache-evicted/not-local and not
    pruned.
- Tests are good.
- It is still a DB-mutating operation on open, so it has latency and release
  safety implications.

### 2.6 Lightweight FAST overlay/color rendering

Changed file:

```text
modules/viewer/fast/lightweight_2d_pipeline.py
```

New behavior:

- `AIPACS_FAST_DICOM_EXTRAS` default on.
- Lightweight FAST pipeline detects DICOM overlay planes and palette/embedded
  color cases.
- Overlay/color data are cached.
- Ordinary grayscale remains on the grayscale path.

Assessment:

- This is adjacent to the 46630 work but separate from the patient-study-set
  pipeline.
- Tests passed.
- It touches rendering, unlike the patient-study-set backfill.
- The implementation is gated and targeted, but it should be treated as its own
  viewer-path change with separate clinical validation.

## 3. Current Coverage After Changes

| Area | Current state | Evaluation |
|---|---|---|
| Study UID identity | Still strong | `StudyInstanceUID` remains the storage/display grouping key. |
| Series identity | Improved | DM guards and viewer canonical identity remain important. |
| Patient-study-set contract | New foundation | Good, but not fully wired. |
| Single-click preview | Improved | Safer no-download behavior. |
| Double-click open | Improved | Open path still owns download; not fully unified. |
| Late-discovered study in open viewer | Improved | Backfill can push metadata into the open tab. |
| Late-discovered study download | Incomplete | Missing/partial files are not reliably queued from backfill. |
| Already-known study with newly grown series | Partially covered | Existing resync and refocus paths help; new backfill focuses on missing study UIDs, not grown series inside known study UIDs. |
| DICOMized DOC study | Improved | Can be backfilled into viewer; download policy still incomplete. |
| Cross-patient isolation | Improved | Backfill and existing paths guard owner mismatch. |
| Local/server sync | Improved but fragmented | Sync decisions still spread across open, resync, manual download, cache gates. |
| DB/disk cleanup | Improved | Orphan-series prune is guarded but default-on DB mutation. |
| Unified optimized path | Not complete | Still no single `PatientStudySetService` or `DownloadPlan`. |

## 4. What Is Now Correct

### 4.1 A late DOC study can be added to an already-open viewer

Before:

```text
open path creates viewer with one study
later reconcile discovers DOC study
right panel refreshes
viewer tab remains unaware
```

Now:

```text
open path creates viewer with one study
later reconcile discovers DOC study
_backfill_open_viewer_studyset fetches DOC series metadata
set_server_series_info merges DOC into viewer
```

This is the most important improvement.

### 4.2 The backfill respects the rendering boundary

The backfill only calls:

```text
widget.set_server_series_info(...)
```

It does not touch:

- pixel loading;
- IPP/IOP geometry;
- slice ordering;
- VTK windows;
- MPR reslice;
- image orientation.

That makes it much safer than a viewer-internal change.

### 4.3 Single-click no longer acts like download

This is important. A user selecting a patient should not start a full image
download unless explicitly configured.

The code now clearly logs:

- `PatientSelectedSingleClick`
- `ThumbnailPreviewRequested`
- `reconcile_enqueue_skipped_single_click`
- `resync_enqueue_skipped_single_click`

That is good observability and correct default behavior.

### 4.4 The patient-study-set helper is the right foundation

`merge_study_uids` centralizes:

- deduplication;
- selected-first ordering;
- empty-value filtering;
- optional owner filtering;
- unknown-owner keep behavior.

This helper can be the seed of the later service.

## 5. Remaining Functional Gaps

### 5.1 Late-discovered open studies are not downloaded

This is the top remaining issue.

Current late path:

```text
_load_and_display_series_info
    -> _reconcile_patient_studies_on_click
    -> _backfill_open_viewer_studyset
    -> set_server_series_info
```

But download behavior still follows single-click policy:

```text
reconcile_enqueue_skipped_single_click
resync_enqueue_skipped_single_click
```

For patient 46630-like cases, this means:

- DOC study metadata can be shown in the viewer;
- DOC series may still be missing on disk;
- dragging/opening the DOC series may rely on later on-demand retry rather than
  being queued as part of the original open intent.

Recommended fix:

```text
If a patient has an open viewer tab and backfill discovers missing studies,
build an open-intent missing-only download plan for those late studies.
```

This should not re-enable downloads for ordinary single-click preview. The
condition should be explicit:

```text
open viewer tab exists for this patient
AND late study is part of that open patient study set
AND sync manifest says missing/partial
THEN enqueue missing/partial only
```

### 5.2 Backfill only handles missing study UIDs, not grown existing studies

`_backfill_open_viewer_studyset` computes:

```text
missing_studies = discovered_uids - existing_widget_study_uids
```

So if the viewer already knows a study UID, but that study gains new series, this
backfill does not push the grown series.

Some same-study growth is covered elsewhere:

- double-click open force-fetches series info;
- already-open refocus path refreshes current study series;
- resync can detect growth.

But the current backfill itself is not a universal "study set changed" sink. It
is specifically a "study UID set grew" sink.

Recommended future behavior:

```text
apply PatientStudySet to open viewer
    -> add missing study UIDs
    -> merge grown series inside existing study UIDs
    -> preserve existing image counts when authoritative
```

### 5.3 There is still no `PatientStudySetService`

The new `PatientStudySet` file is a contract, not a service.

Current major callers still independently resolve or enrich study/series data:

- `_resolve_patient_study_uids`
- `_resolve_patient_study_uids_async`
- `_reconcile_patient_studies_on_click`
- `_resync_patient_studies_from_server`
- `_show_grouped_patient_studies`
- `show_patient_studies`
- `_on_download_requested`
- double-click open STEP 3.5

Until these consume a shared service, fixes can still land in one path without
covering the others.

### 5.4 Download planning remains fragmented

Open, resync, and manual download still build payloads independently.

The desired target is:

```text
PatientStudySet
    -> DownloadPlan
        -> missing/partial only
        -> canonical study_uid
        -> canonical series_uid
        -> original series_number
        -> patient ownership already validated
```

Current state:

- open builds one payload;
- resync builds another;
- manual download prefetches and mutates selected dicts;
- backfill builds no download payload.

### 5.5 Tab ownership is still study-primary rather than patient-study-set primary

The open viewer tab is still found mostly by a primary `study_uid`.

That works for:

- selected primary imaging study;
- backfill where `study_uids[0]` is the open study.

Potential future issue:

- If the user later opens/selects a secondary DOC study directly, the system may
  not always know that an existing patient-level multi-study tab already owns
  that study set.

Recommended direction:

```text
tab ownership should include patient_id + study_uid set
```

or at minimum:

```text
dict study_uid -> owning patient tab
```

for every study in the open study set, not only the primary study.

### 5.6 Selected study is always kept even if owner appears foreign

`merge_study_uids` intentionally keeps the explicitly selected study even when
`owner_of` reports a different patient.

This matches existing behavior and avoids breaking fresh-server cases, but it is
a residual safety edge. If a table row is stale or carries the wrong patient ID
for a selected study, the selected study can still be kept under the wrong
patient context.

Recommended future handling:

- keep selected study to avoid data loss;
- emit a high-severity trace when selected owner does not match requested
  patient;
- consider correcting the patient context from authoritative study owner;
- never silently attach selected foreign study under the wrong patient in a
  final unified service.

## 6. Potential Risks

### 6.1 Backfill waits before grouped right-panel render

Current order in `_load_and_display_series_info`:

```text
reconcile study_uids
await _backfill_open_viewer_studyset(...)
then _show_grouped_patient_studies(...)
```

Backfill may fetch missing studies using:

```text
await asyncio.wait_for(asyncio.to_thread(...), timeout=45.0)
```

For multiple missing studies or a slow server, this can delay the right-panel
grouped render. It should not freeze the Qt UI thread directly because the fetch
is in `to_thread`, but the coroutine's own workflow is delayed.

Recommendation:

- make backfill fire-and-forget after reconciliation; or
- fetch missing studies concurrently with a shorter timeout; or
- render the right panel first, then backfill the viewer.

### 6.2 Backfill is default-on and can add network work

`AIPACS_OPEN_TAB_STUDYSET_BACKFILL` defaults on.

This is reasonable for the 46630 fix, but operationally it means a single-click
or deferred refresh while a tab is open can trigger fresh `_get_or_fetch_series_info`
calls for missing studies.

Recommendation:

- keep the flag;
- monitor trace counts;
- add latency metrics:
  - `patient_study_set_viewer_backfill duration_ms`;
  - missing study count;
  - series count;
  - skipped foreign count.

### 6.3 Orphan-series prune mutates DB during open

The orphan-series prune is well-guarded, but it runs in the open path.

Potential risks:

- extra DB and disk listing latency before first paint;
- false orphan if a valid storage layout uses DICOM files without `.dcm`
  extension;
- stale thumbnails may remain even after DB rows are pruned;
- release support complexity if users see series disappear because rows were
  repaired automatically.

Recommendations:

- measure open latency with and without `AIPACS_PRUNE_ORPHAN_SERIES`;
- consider running prune after first paint or throttling per study;
- clear or invalidate thumbnails for pruned series;
- consider dry-run/observe mode before default-on in production builds;
- document the behavior in release notes.

### 6.4 Existing background setup still has thread-boundary risk

There are still code paths where background setup can call viewer methods after
worker-thread work. The new backfill itself is called from the async/UI flow, but
the broader codebase still has old patterns that should be normalized.

Recommendation:

- final `ViewerStudySetBridge.apply(...)` should always marshal to the UI thread;
- no background thread should directly mutate Qt widgets.

### 6.5 Lightweight overlay/color path is a separate rendering change

The new DICOM extras support in `lightweight_2d_pipeline.py` is valuable for
derived/secondary-capture frames, but it is not part of the patient-study-set
unification.

Potential bottleneck:

- overlay/color series read DICOM datasets again per slice to extract overlays
  or palette data;
- ordinary grayscale is gated and cached, so normal studies should be minimally
  affected;
- overlay-heavy series should be validated for latency.

Recommendation:

- keep separate clinical validation for overlay/color rendering;
- keep `AIPACS_FAST_DICOM_EXTRAS` as rollback;
- collect timing on real 46630 overlay series.

### 6.6 Build/release parity failure

The release parity test failed because staged config differs from repo config:

```text
patient_table_sort.json
```

This is not a runtime patient-study-set bug, but it is a release blocker until
the stage is rebuilt or the config change is intentionally handled.

## 7. Bottleneck Analysis

### 7.1 Study-set resolution

Current bottleneck:

- resolution is still repeated across several paths;
- fresh server patient-row calls are not centralized;
- per-study `_get_or_fetch_series_info` can be sequential.

Risk:

- duplicated server calls;
- inconsistent freshness;
- slow multi-study patients with many studies.

Target:

```text
PatientStudySetService.resolve(...)
    -> one freshness policy
    -> one cache/throttle policy
    -> concurrent per-study metadata fetch when needed
```

### 7.2 Backfill

Current bottleneck:

- missing studies are fetched sequentially;
- each has up to 45 seconds timeout;
- backfill currently awaits before grouped right-panel render.

Target:

- fire-and-forget or concurrent fetch;
- short per-study timeout for UI update;
- render local/cached content first;
- apply late metadata when ready.

### 7.3 Download planning

Current bottleneck:

- open/resync/manual download calculate payloads separately;
- backfill calculates no download payload.

Risk:

- late studies are visible but not downloaded;
- duplicated missing/partial logic;
- inconsistent stale-completed reset behavior.

Target:

```text
DownloadPlanBuilder.from_patient_study_set(...)
```

### 7.4 Orphan prune

Current bottleneck:

- DB queries plus disk folder checks during open;
- potentially expensive for large multi-study patients.

Target:

- throttle per study;
- run after first paint;
- clear stale thumbnails;
- expose maintenance script for manual repair.

### 7.5 DB-first metadata auto mode

Existing risk from previous review remains:

- `_db_geom_trust_cache` is keyed by `study_pk`;
- if study grows or is reindexed, trust invalidation may lag.

Target:

- invalidate trust when sync manifest detects growth;
- include indexed count/content version in cache key.

## 8. Test Results From Recheck

The following focused tests were run after the changes.

Passed:

```text
tests/code/ui_services/test_patient_study_set.py
tests/code/ui_services/test_open_tab_studyset_backfill.py
22 passed
```

Passed:

```text
tests/code/ui_services/test_resync_on_reopen.py
tests/code/storage/test_orphan_series_prune.py
24 passed
```

Passed:

```text
tests/code/download_manager/test_multistudy_identity_guards.py
tests/code/download_manager/test_series_dedup_count_guard.py
tests/code/download_manager/test_dm_preempt_on_drag.py
17 passed
```

Passed:

```text
tests/code/storage/test_open_skip_download_when_complete.py
tests/code/viewer/test_plain_series_study_path.py
tests/code/storage/test_db_first_metadata_index.py
tests/code/viewer/test_h1_study_pk_propagation.py
28 passed
```

Passed:

```text
tests/code/network/test_attachment_local_first_persistence.py
tests/code/network/test_report_status_circuit_breaker.py
10 passed
```

Passed:

```text
tests/code/viewer/test_lightweight_pipeline_overlay.py
tests/code/download_manager/test_fast_object_cache_adapter.py
tests/code/download_manager/test_dm_rebuild_recursion.py
25 passed
```

Passed:

```text
tests/code/system/test_voice_study_uid_resolution.py
tests/code/download_manager/test_batch_growth.py
tests/code/download_manager/test_image_count_normalization.py
16 passed
```

Passed:

```text
py_compile:
PacsClient/utils/patient_study_set.py
PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py
PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py
database/dicom_db.py
modules/viewer/fast/lightweight_2d_pipeline.py
```

Failed:

```text
tests/code/builder/test_release_parity_guards.py
```

Failure reason:

```text
stage_config_parity failed because staged patient_table_sort.json differs from
repo config/patient_table_sort.json.
```

Assessment:

- Runtime logic tests are strong.
- Release parity must be handled before packaging.
- A dedicated test is still needed for "late-discovered open study also queues
  missing-only download."

## 9. Remaining Required Tests

### 9.1 Late open-study download plan

Shape:

```text
viewer opened with PRIMARY
later reconcile discovers DOC
DOC is missing on disk
open tab exists
```

Expected:

```text
set_server_series_info receives DOC
Download Manager receives DOC missing series only
single-click without open tab still does not download
```

### 9.2 Existing study grows while tab open

Shape:

```text
viewer already has study UID A
server adds new series under study UID A
resync detects growth
```

Expected:

```text
open viewer receives new series metadata
download plan queues only new/partial series
```

### 9.3 Backfill latency does not block right-panel render

Shape:

```text
backfill server fetch stalls
```

Expected:

```text
right panel grouped render still happens quickly
backfill times out/logs separately
```

### 9.4 Orphan prune clears stale thumbnail metadata

Shape:

```text
series DB rows are pruned
thumbnail for that series remains on disk
```

Expected:

```text
stale thumbnail is not shown as a valid local series
```

### 9.5 Selected-study owner mismatch

Shape:

```text
selected study UID owner differs from selected patient ID
```

Expected:

```text
high-severity trace
no silent attach under wrong patient
policy-defined correction or refusal
```

## 10. Recommended Roadmap

### P0: Add open-intent download plan for late backfilled studies

This is the most important remaining functional gap.

Implementation direction:

1. In `_backfill_open_viewer_studyset`, after collecting owner-validated
   aggregated series for missing studies, evaluate sync manifest for those
   studies.
2. Build missing/partial-only download payloads.
3. Enqueue only when an open viewer tab exists for the patient.
4. Do not enqueue for ordinary single-click with no open tab.
5. Log:
   - `patient_study_set_viewer_backfill`
   - `patient_study_set_late_download_enqueued`
   - skipped reason if complete/no server/no DM.

### P0: Make backfill non-blocking for right-panel render

Current awaited backfill can delay the grouped render.

Safer behavior:

```text
render right panel
schedule viewer backfill
apply metadata/download when ready
```

### P1: Convert resolver callers to `merge_study_uids`

Start replacing duplicated union/dedup/owner filtering logic in:

- `_resolve_patient_study_uids`;
- `_reconcile_patient_studies_on_click`;
- plus-button path;
- manual download target normalization.

Do this behind tracing or narrow tests first.

### P1: Build `PatientStudySetService`

The contract exists. The service should own:

- source collection;
- owner validation;
- per-study series metadata;
- sync status;
- viewer payload;
- thumbnail payload;
- download plan.

### P1: Centralize `DownloadPlan`

Use one builder for:

- double-click open;
- late backfill;
- resync/manual refresh;
- manual download.

### P2: Normalize tab ownership

Map every study UID in an open patient study set to the owning tab.

This prevents:

- duplicate tabs for secondary DOC study;
- failure to focus an existing multi-study patient tab;
- incomplete backfill when the selected UID is not the primary UID.

### P2: Revisit orphan prune rollout

Decide whether production default should be:

- default on;
- observe first;
- after-first-paint;
- manual maintenance only.

Also add thumbnail invalidation.

### P3: Patient identity model

Still separate from this change:

- issuer of Patient ID;
- assigning authority;
- patient alias/master-patient table;
- explicit merge/link policy.

## 11. Final Evaluation

Current state after changes:

```text
Foundation: good
Viewer backfill: good and important
Late-study download: incomplete
Unified service: not yet implemented
Risk profile: improved but still fragmented
Release readiness: blocked by staged config parity until handled
```

The latest code is not a final unified path, but it is no longer just a report.
It now contains the first real pieces of the unified model:

- a canonical data contract;
- a canonical study UID merge helper;
- a concrete late-study viewer backfill;
- focused tests.

The next step should be precise, not broad:

> When a late study is discovered for a patient that already has an open viewer
> tab, update the viewer and enqueue only missing/partial series for that late
> study under open intent.

After that, the project can move from targeted backfill toward the full
`PatientStudySetService` and shared `DownloadPlan`.

