# Multi-Study Unified Pipeline Full Recheck

Date: 2026-06-17  
Scope: latest working-tree code review after the recent multi-study, multi-patient-ID, study backfill, resync, and Download Manager changes.  
Mode: evaluation only. No runtime code was changed while preparing this report.

> Superseded note, 2026-06-17 later recheck: this report is preserved for
> history, but several risks listed here have since been fixed in code
> (`study_description` payload parity, `series_instance_uid` fallback in
> `_vc_load.py`, and multi-study backfill lookup by secondary study UID).
> Use `docs/reports/MULTI_STUDY_UNRESOLVED_RISK_CURRENT_RECHECK_2026-06-17.md`
> as the current authoritative risk review.

## 1. Executive Conclusion

The current code is significantly better than the previous state. The most important previous failure mode was:

1. Double-click open created a viewer tab with an incomplete study set.
2. A later single-click or background reconcile discovered an additional same-patient study, often a DOC/DICOMized-document study.
3. The late study could appear in metadata/right-panel paths, but its images were not reliably downloaded under the original open intent.

The new code now addresses this class more directly:

- `PatientStudySet` and `PatientStudySetService` exist as a shared contract/facade.
- `_resolve_patient_study_uids` now routes final merge/order/owner filtering through shared logic.
- Open-tab backfill now pushes late-discovered studies into the open viewer.
- Open-tab backfill also enqueues late studies for download.
- Single-click preview paths still avoid automatic full downloads.
- Disk-aware manifest checks now reduce unnecessary re-downloads and detect missing/partial local studies.
- Download Manager has stronger guards for duplicate studies, stale completed state, progress count inflation, and multi-study series identity.

However, the system is not yet a fully unified, optimized, single-path architecture. It is now a safer incremental architecture with several important shared helpers, but core orchestration is still split across home-panel open, single-click reconcile, resync, manual refresh, Download Manager queue creation, and viewer retry paths.

The remaining risk is not one obvious crash. The remaining risk is fragmentation: different flows still build similar but not identical study sets and download payloads. That fragmentation can cause small inconsistencies in priority, metadata fields, tab lookup, and missing-only download behavior.

## 2. Reviewed Areas

This review focused on the areas that determine whether complex patient structures remain separated and synchronized:

- Patient identity and patient grouping.
- Study identity and multi-study ordering.
- Same-patient multi-study handling.
- Different Patient ID handling and cross-patient isolation.
- DICOMized document representation.
- Double-click open pipeline.
- Single-click preview/reconcile pipeline.
- Open-tab late backfill pipeline.
- Resync-on-reopen and manual refresh pipeline.
- Disk completeness and sync manifest logic.
- Download Manager task creation, duplicate detection, priority, and resume behavior.
- Viewer series identity and retry handoff.
- Local DB/disk/cache relationship.
- Release/build parity guard.

Primary files reviewed:

- `PacsClient/utils/patient_study_set.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_priority.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_tab_service.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`
- `database/dicom_db.py`
- `modules/storage/sync_manifest.py`
- `modules/download_manager/core/models.py`
- `modules/download_manager/rules/validation_rules.py`
- `modules/download_manager/download/series_downloader.py`
- `modules/download_manager/ui/widget/_dm_queue.py`
- `modules/download_manager/ui/widget/_dm_priority.py`
- `modules/download_manager/coordinator/series_intent_coordinator.py`
- Relevant focused tests under `tests/code/ui_services`, `tests/code/storage`, `tests/code/download_manager`, `tests/code/system`, and `tests/code/viewer`.

## 3. Current Architecture Summary

### 3.1 Patient Identity

The application still primarily treats `PatientID` as the grouping key for a patient row and patient study set. This is appropriate for strict DICOM identity separation, but it is not the same as "real-world patient identity" when imported data contains multiple Patient IDs for the same real person.

Current behavior:

- A patient tab is opened from a selected `patient_id`.
- Study ownership checks compare the discovered study's server/local owner `patient_id` to the requested `patient_id`.
- Cross-patient studies are dropped or skipped when the owner is positively known to be different.
- Unknown owner studies are kept so fresh server studies not yet in the local DB are not incorrectly blocked.

This is clinically conservative. It avoids accidental mixing of different patients. It does not solve real-patient aliasing across multiple Patient IDs. That should remain a separate explicit patient-linking/merge feature, not implicit grouping.

### 3.2 Study Identity

Study identity is still centered on `StudyInstanceUID`, called `study_uid` in most of the Python code.

This is the correct disk/DB/download identity:

- Disk path: `SOURCE_PATH / study_uid`
- Series folder: `SOURCE_PATH / study_uid / series_number`
- Local DB study row: keyed by `study_uid`
- Download task identity: `study_uid`
- Viewer tab primary identity: `study_uid`

The current system correctly treats `series_number` as study-local, not global. Recent Download Manager changes also reduce the chance that the same series number from different studies collides.

### 3.3 Series Identity

Series identity remains a mixed model:

- Display often uses `series_number`.
- Server/download identity prefers `series_uid` or `SeriesInstanceUID`.
- Multi-study viewer display may use synthetic display keys for secondary studies.
- Download Manager task membership validates by `series_uid` first, then by original `series_number`.

The recent changes are much safer than before. The main remaining gap is in `_vc_load.py`, where `_resolve_canonical_series_identity` still reads only `series_uid` from the viewer metadata entry and does not also fallback to `series_instance_uid`. Other helpers already know how to handle `series_instance_uid`, so this should be aligned.

## 4. Current Workflow Behavior

### 4.1 Double-Click Open

Entry point:

- `_on_patient_double_clicked_async`
- File: `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py`

Current flow:

1. Resolve all study UIDs for the patient via `_resolve_patient_study_uids_async`.
2. Mark the event as explicit open intent using `PatientOpenDoubleClick`.
3. Optionally prune orphan series rows for opening studies.
4. Open or focus a viewer tab.
5. Fetch fresh server series info per study.
6. Apply cross-patient owner guard.
7. Build aggregated viewer series metadata for all accepted studies.
8. Use disk-aware manifest logic to skip complete studies or download only missing/partial series.
9. Queue download with `start_priority_download_immediately`.
10. Push full series metadata into the viewer.
11. Schedule right-panel/series-info background tasks.

This is now much closer to the desired behavior. The main double-click path is the strongest and most complete path in the system.

Strengths:

- Explicit open intent is traceable.
- It uses fresh server metadata.
- It avoids redundant re-downloads when the disk is complete.
- It filters missing/partial series before priority queueing.
- It resets stale terminal Download Manager state before enqueue when needed.
- It guards against foreign studies before queueing/downloading/surfacing.

Weaknesses:

- It still contains orchestration logic directly inside the UI mixin.
- It manually builds `dm_study_data` instead of using one shared `DownloadPlan`.
- It uses `start_priority_download_immediately`, while other related paths use `add_downloads`.
- Study gathering remains inside `_resolve_patient_study_uids`; only merge/owner filtering is shared.

### 4.2 Single-Click Preview/Reconcile

Entry point:

- `_load_and_display_series_info`
- `_reconcile_patient_studies_on_click`
- File: `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py`

Current flow:

1. Mark event as `PatientSelectedSingleClick`.
2. Reconcile local and server study UIDs for the patient.
3. Save refreshed metadata for missing/grown studies.
4. Do not start full downloads by default.
5. Log `reconcile_enqueue_skipped_single_click` or `resync_enqueue_skipped_single_click`.
6. If an open viewer tab exists and the study set grew, schedule open-tab backfill.

This is correct conceptually. Single-click should preview/select. It should not silently start large downloads. The recent code preserves that separation.

Strengths:

- Clear intent separation between preview and open.
- Download behavior is reversible via `AIPACS_SINGLE_CLICK_DOWNLOAD`.
- Late discovery can now trigger open-tab backfill only when a viewer tab exists.

Weaknesses:

- The single-click reconcile still has its own server row parsing and study UID merge logic.
- It can discover studies after the main open path, which proves resolution is still not centralized.
- It depends on side effects from open-tab detection to decide whether late downloads are open intent.

### 4.3 Open-Tab Late Backfill

Entry point:

- `_backfill_open_viewer_studyset`
- `_enqueue_missing_series_for_open_study`
- File: `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py`

Current behavior:

When single-click/reconcile discovers that the patient study set has grown and a viewer tab already exists:

1. Find the open widget for the primary study UID.
2. Determine which studies are already represented in the open viewer.
3. Fetch server series info for missing studies.
4. Validate owner `patient_id`.
5. Push missing study series metadata into `set_server_series_info`.
6. If `AIPACS_OPEN_TAB_LATE_DOWNLOAD` is enabled, enqueue the missing/partial study for download.

This is the most important improvement in the latest code.

Positive effect:

- The previous "late DOC study visible but not downloaded" problem is now directly addressed.
- The operation is guarded by open viewer presence, so pure single-click preview still does not download.
- Cross-patient studies are skipped before metadata attach or download enqueue.

Remaining concern:

The late download uses `dm.add_downloads(..., start_immediately=True)`, not the same `start_priority_download_immediately` path used by double-click open. This means a late DOC/new study under an already-open patient may be queued as immediate but not necessarily with the same open-priority/preemption semantics as the main open path.

Also, `_enqueue_missing_series_for_open_study` uses the sync manifest as a gate, but then passes the full server series list through `build_download_payload`. The Download Manager should skip complete series later, but the "only missing" contract is enforced one layer later rather than at payload construction.

### 4.4 Resync-on-Reopen and Manual Refresh

Entry points:

- `_resync_patient_studies_from_server`
- `_on_resync_from_server_requested`
- File: `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py`

Current behavior:

- Auto resync can detect server growth or disk-missing studies.
- Manual refresh with `force=True` can enqueue downloads.
- Auto single-click resync saves/reveals metadata but does not download by default.
- Content version can skip expensive checks when server and local synced version match.
- Disk-aware sync catches cases where DB rows exist but DICOM files are missing.

This is good and solves several previous stale-completed and stale-local cases.

Remaining concern:

Manual resync uses the shared payload builder, but still sends a full series payload to `add_downloads`, relying on Download Manager skip/resume. That is less optimized than the main open path, which filters to missing/partial before queueing.

### 4.5 Download Manager

Relevant files:

- `modules/download_manager/core/models.py`
- `modules/download_manager/rules/validation_rules.py`
- `modules/download_manager/download/series_downloader.py`
- `modules/download_manager/coordinator/series_intent_coordinator.py`
- `modules/download_manager/ui/widget/_dm_queue.py`
- `modules/download_manager/ui/widget/_dm_priority.py`

Current improvements:

- Duplicate series in a task are deduplicated.
- Implausible count inflation is logged as `CriticalCountMismatch`.
- Completed state is disk-aware, so stale completed states can be resumed if files are missing.
- Series download progress denominators are frozen to avoid mutation/reorder count inflation.
- Series-level skip checks still prevent re-downloading complete series.
- Critical intent validation rejects series that do not belong to the task.
- UID-based normalization can correct wrong display series numbers when the UID is supplied.

This is a strong safety net. The Download Manager is now more robust against bad inputs from the UI.

Remaining concern:

The Download Manager is still acting as a safety net for upstream fragmentation. Ideally, upstream should pass a clean `DownloadPlan` that is already:

- patient-owner verified;
- study-scoped;
- missing/partial filtered;
- priority annotated;
- schema-normalized.

Today, those responsibilities are distributed across UI code, sync manifest code, queue validation, task model dedupe, and downloader skip logic.

## 5. Database, Disk, Cache, and Manifest Review

### 5.1 Disk Structure

The current disk structure remains:

```text
SOURCE_PATH/
  <StudyInstanceUID>/
    <SeriesNumber>/
      *.dcm
```

This is good because it separates studies even when the same patient has many studies and even when two studies contain the same `SeriesNumber`.

Risk:

Series folder names still depend on `series_number`, not `series_uid`. This is workable because series numbers are study-local, but it means every path must always carry the correct `study_uid`. Any loss of study context can misroute a series.

### 5.2 Sync Manifest

File:

- `modules/storage/sync_manifest.py`

The sync manifest is a major improvement. It gives the app one disk-first read model for:

- Not downloaded
- Thumbnail only
- Partially downloaded
- Downloaded
- Stale
- Missing series vs server
- Partial series vs server
- Missing thumbnails

It is read-only and therefore a good source of truth for decisions.

Positive:

- Disk is treated as truth, DB as hint.
- Manifest cache reduces repeated disk scans.
- Pixel-less stub detection is included.
- Content version integration reduces unnecessary resync work.

Weakness:

The module header still contains stale documentation saying nothing in live open/render path depends on it. That is no longer true. The open and resync paths now depend on `evaluate_sync`.

### 5.3 Orphan Series Prune

File:

- `database/dicom_db.py`

Open path now calls `prune_orphan_series_for_study` for opening studies.

Positive:

- This repairs a real DB/disk inconsistency class where DB series rows point to missing disk folders.
- It avoids pruning whole evicted studies.
- It avoids pruning pending zero-instance series.
- It is gated by `AIPACS_PRUNE_ORPHAN_SERIES`.

Risks:

- It mutates DB during open.
- It adds disk/DB work to the open path.
- It only counts `.dcm` files.
- It may not clear all related thumbnails/cache artifacts.

Recommendation:

Keep this as a guarded self-heal, but eventually move heavier cleanup to a maintenance/repair job or make open-path pruning bounded and telemetry-driven.

## 6. DICOMized Document Workflow

DICOMized documents are represented as DICOM series/studies, often with modality-like document metadata and high/synthetic series numbers such as `100000`.

Current handling is better because:

- Late DOC study discovery can backfill the open viewer.
- Late DOC study discovery can now enqueue download.
- Cross-patient owner validation prevents attaching another patient's DOC study.
- The grouped multi-study viewer can show DOC and imaging studies together under one patient when ownership matches.

Remaining risks:

- DOC studies often arrive as separate StudyInstanceUIDs, so patient-level tab lookup must reliably find the open patient tab even when the newly discovered study UID is not the tab's primary `study_uid`.
- If server rows omit study lists and only expose latest study, DOC discovery can still occur late, after the open tab is built. The current backfill handles this, but the ideal architecture would resolve the complete set before first open/download planning.
- Document series with unusual `series_number` values should always use `study_uid + series_uid` for identity-sensitive operations.

## 7. What Is Correct Now

The following parts are conceptually correct and well aligned with the desired architecture:

1. Study identity is based on `StudyInstanceUID`.
2. Disk storage is study-scoped.
3. Series number is treated as study-local.
4. Explicit open intent is separated from single-click preview intent.
5. Single-click no longer silently starts full downloads by default.
6. Cross-patient studies are dropped/skipped when owner mismatch is known.
7. Unknown-owner fresh studies are kept, preventing false blocking.
8. Open path uses fresh server metadata.
9. Open path skips complete studies and queues missing/partial series.
10. Late open-tab backfill now updates viewer metadata and starts downloads.
11. Download Manager has stronger dedupe, stale-completed, and count guards.
12. Sync manifest provides a good disk-first read model.
13. Focused regression coverage is much stronger than before.

## 8. Main Fragile Areas

### 8.1 Not Yet One Service Boundary

`PatientStudySetService` exists, but the application does not yet use it as the one orchestration authority. It currently centralizes helper logic, not the whole flow.

Still duplicated:

- Study UID source gathering.
- Patient row parsing.
- Server row enumeration.
- Download payload construction variants.
- Missing-only filtering variants.
- Priority semantics.
- Open-tab lookup.

Risk:

A future fix may update one path and miss another path, recreating open/select divergence.

### 8.2 Late Backfill Uses Different Download Path

Main open:

- `start_priority_download_immediately`
- Priority/preemption aware.
- Missing-only filtered before queue.

Late backfill:

- `add_downloads(..., start_immediately=True)`
- Manifest gate before queue.
- Full series payload passed to DM.

Risk:

Late DOC/new study downloads may not behave exactly like open-intent downloads under worker pressure or competing downloads.

### 8.3 Payload Schema Mismatch

`build_download_payload` returns:

```python
'description': info.get('study_description', '')
```

But `_dm_queue.py` reads:

```python
data.get('study_description', '')
```

Effect:

Downloads may still work, but study description can be lost in Download Manager state/UI/database for paths using the shared builder.

Risk:

Not a clinical mixing bug, but a quality and traceability bug.

### 8.4 Tab Lookup Is Study-Centric

Open-tab backfill starts by finding a widget from `study_uids[0]`. The tab service lookup is keyed by the widget's primary `study_uid`.

Risk:

For true patient-level multi-study tabs, every study UID in the patient set should resolve to the same widget. If `study_uids[0]` is not the primary tab study UID, backfill can miss the open tab.

Current code likely works in common selected-first cases, but the architecture should be stronger.

### 8.5 Series UID Fallback Gap

`PacsClient/utils/series_identity.py` already handles both:

- `series_uid`
- `series_instance_uid`

But `_vc_load.py` canonical resolver still reads only:

```python
entry.get('series_uid')
```

Risk:

Priority/retry handoff may lose UID-based validation and fall back to series-number-only matching. This is lower risk now because study UID and original series number are also corrected, but it should be aligned.

### 8.6 DB Mutation During Open

Orphan pruning during open is practical, but still a mutation in a latency-sensitive path.

Risk:

Large multi-study patients may pay extra open latency. Unexpected DB pruning during open also deserves careful telemetry.

### 8.7 Stale Documentation

Several comments now contradict actual code usage:

- `patient_study_set.py` says nothing imports it yet.
- `sync_manifest.py` says live open/render path does not depend on it yet.

Risk:

Future developers may misunderstand which code is live and which code is experimental.

## 9. Bottleneck Analysis

### 9.1 Open-Time Server Fetches

The double-click open path fetches fresh series info per study. This is necessary for correctness, but multi-study patients can require several server calls.

Risk:

Patients with many studies/modalities may experience open latency or delayed full sidebar population.

Mitigation:

The code already pushes tab creation early and schedules some UI tasks asynchronously. Long term, `PatientStudySetService.resolve()` should support staged freshness:

- local fast first;
- cached server next;
- fresh server reconcile in background;
- deterministic backfill/download plan when fresh data arrives.

### 9.2 Disk Manifest Scans

`evaluate_sync` scans disk/DB state. The cache helps, but opening many studies can still create disk I/O.

Risk:

Large studies or slow disks can still affect open responsiveness.

Mitigation:

Keep manifest caching, invalidate on download/delete, and monitor scan latency.

### 9.3 Download Manager as Downstream Dedupe Layer

Several upstream paths still pass broad payloads and depend on DM skip/resume logic.

Risk:

Even when files are skipped, broad tasks can increase queue overhead, logs, progress state complexity, and UI churn.

Mitigation:

Move missing-only filtering into a shared `DownloadPlan`.

### 9.4 Open-Path Orphan Pruning

Pruning scans DB rows and disk files at open time.

Risk:

May add latency for multi-study opens and create surprise DB mutation.

Mitigation:

Keep flag, add telemetry, consider moving heavy cleanup to maintenance.

## 10. Test Results From Current Recheck

The following tests were run against the current working tree using `.venv`, because the system Python did not have `PySide6`.

Passed:

- `tests/code/ui_services/test_patient_study_set.py`
- `tests/code/ui_services/test_resolve_patient_study_uids_scope.py`
- `tests/code/ui_services/test_open_tab_studyset_backfill.py`
- Result: 37 passed.

Passed:

- `tests/code/ui_services/test_resync_on_reopen.py`
- `tests/code/storage/test_open_skip_download_when_complete.py`
- `tests/code/storage/test_sync_manifest.py`
- `tests/code/storage/test_orphan_series_prune.py`
- Result: 42 passed.

Passed:

- `tests/code/download_manager/test_multistudy_identity_guards.py`
- `tests/code/download_manager/test_series_dedup_count_guard.py`
- `tests/code/download_manager/test_dm_preempt_on_drag.py`
- `tests/code/download_manager/test_batch_growth.py`
- `tests/code/download_manager/test_image_count_normalization.py`
- Result: 29 passed.

Passed:

- `tests/code/storage/test_resync_content_version_gate.py`
- `tests/code/storage/test_content_version_store.py`
- Result: 20 passed.

Passed:

- `tests/code/ui_services/test_series_identity.py`
- `tests/code/viewer/test_h1_study_pk_propagation.py`
- `tests/code/system/test_voice_study_uid_resolution.py`
- Result: 18 passed.

Syntax check passed:

- `PacsClient/utils/patient_study_set.py`
- `_hp_patient_open.py`
- `_hp_series.py`
- `_vc_load.py`
- `database/dicom_db.py`
- `modules/storage/sync_manifest.py`
- Download Manager queue/priority/downloader/validation modules.

Failed:

- `tests/code/builder/test_release_parity_guards.py`
- Result: 13 passed, 1 failed.
- Failure: staged build config differs from repo config for `patient_table_sort.json`.

Interpretation:

The focused runtime logic for multi-study, late backfill, sync manifest, and DM identity is currently green. The remaining failed test is a release/build parity issue, not a direct multi-study runtime failure. It should still block release packaging until fixed.

## 11. Risk Ranking

### P0 - Release Blocker

Release stage config parity is failing:

- `patient_table_sort.json` staged bytes differ from repo config.

This does not invalidate the multi-study logic, but it means packaged/staged output may not match source. Rebuild or refresh the stage before release.

### P1 - Architecture Risk

The pipeline is not fully unified yet.

Current state:

- Shared contract exists.
- Shared merge/owner logic is used in some places.
- But full resolution, download planning, tab mapping, and payload shape are not centralized.

Impact:

Future multi-study bugs are still possible if one path evolves differently from another.

### P1 - Open Intent Priority Inconsistency

Late backfill download uses `add_downloads` rather than the exact main open priority path.

Impact:

Late DOC/new study downloads may not preempt/priority-match the original double-click open.

### P1 - Missing-Only Contract Is Split

Main open filters missing series before queueing. Backfill/resync gate on manifest but pass full server list to DM.

Impact:

Download is likely safe due to downstream skip logic, but less optimized and harder to reason about.

### P2 - Payload Schema Drift

`description` vs `study_description` mismatch.

Impact:

Metadata quality loss in Download Manager UI/state.

### P2 - Study-Centric Tab Lookup

Patient-level multi-study tabs should be findable by any study UID in the patient set, not only the primary tab UID.

Impact:

Potential blind spot for late backfill in uncommon ordering cases.

### P2 - Series UID Alias Gap

`_vc_load.py` should fallback from `series_uid` to `series_instance_uid`.

Impact:

Priority/retry matching can become weaker when metadata uses alternate UID key.

### P2 - Open-Time DB Mutation

Orphan pruning during open is useful but should be monitored.

Impact:

Possible latency and maintenance surprise.

### P3 - Stale Comments

Some comments say new modules are not live, but they are now live.

Impact:

Developer confusion.

## 12. Recommended Roadmap

### Step 1 - Fix Release Parity

Rebuild or refresh staged config so `test_release_gate_stage_config_parity_against_current_stage` passes.

Reason:

No release should ship with known source/stage mismatch.

### Step 2 - Standardize Download Payload Schema

Update the shared payload builder to include both:

```python
'study_description': ...
'description': ...
```

Or update Download Manager to accept both consistently.

Reason:

This is small, low risk, and removes immediate metadata drift.

### Step 3 - Make Late Backfill Use Open-Priority Semantics

For `_enqueue_missing_series_for_open_study`, either:

- route through the same priority API used by double-click open; or
- add explicit priority/open-intent metadata to the shared plan and let DM apply the same behavior.

Reason:

A late DOC/new study under an open patient is still part of the open intent.

### Step 4 - Build a Real `DownloadPlan`

Create one shared planner:

```text
PatientStudySet
  -> owner-verified StudyDescriptors
  -> disk manifest comparison
  -> missing/partial SeriesDescriptors
  -> DownloadPlan
```

Every caller should consume the same plan:

- double-click open;
- open-tab backfill;
- manual refresh;
- resync;
- plus-button/manual download;
- viewer retry.

Reason:

This removes full-vs-missing payload inconsistencies.

### Step 5 - Promote `PatientStudySetService.resolve()` to True Authority

Move study source gathering into the service:

- selected study;
- table row;
- row `study_uids`;
- row `studies`;
- local DB;
- cached patient map;
- right-panel fallback;
- server patient row;
- modality enumeration.

Return a typed `PatientStudySet` with:

- selected study first;
- same-patient studies only;
- owner validation status;
- freshness;
- warnings.

Reason:

This is the actual "one optimized path."

### Step 6 - Add Patient-Level Open Tab Mapping

When a patient tab contains multiple studies, map all study UIDs in the set to the same widget, or add patient-ID lookup to backfill.

Reason:

Backfill should find an open patient tab regardless of which study UID becomes first in the discovered list.

### Step 7 - Complete Series UID Alias Handling

In `_vc_load.py`, update canonical identity resolution to read:

```python
entry.get('series_uid') or entry.get('series_instance_uid')
```

Add a focused regression test.

Reason:

This aligns viewer identity with the rest of the codebase.

### Step 8 - Move Heavy Repair Out of Hot Open Path Where Possible

Keep orphan prune available, but track:

- prune duration;
- number of rows touched;
- study size;
- whether it ran during first open.

If expensive, move full scan/repair to maintenance and keep open-path repair narrow.

## 13. Final Assessment

The latest changes are good quality overall. They are careful, guarded by flags, covered by focused tests, and aimed at the real failure modes observed in multi-study patients.

The most important bug class, late-discovered same-patient DOC/new study not downloading, is now much better handled. Cross-patient isolation is also stronger than before.

The remaining work is architectural consolidation. The system should now move from "several guarded fixes in several paths" to "one resolved patient study set and one download plan consumed everywhere." Until that happens, the code is safer but still not as simple or deterministic as it should be for complex multi-study and multi-patient-ID workflows.

In short:

- Runtime safety: improved.
- Cross-patient isolation: improved.
- Late DOC/new study handling: improved.
- Test coverage: improved.
- Release readiness: blocked by stage config parity.
- Architectural unification: partial, not complete.
