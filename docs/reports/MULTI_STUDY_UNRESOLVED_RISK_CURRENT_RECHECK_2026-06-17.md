# Multi-Study Pipeline Current Recheck and Unresolved Risk Review

Date: 2026-06-17  
Status: current-state report after the latest code changes.  
Supersedes: `docs/reports/MULTI_STUDY_UNIFIED_PIPELINE_FULL_RECHECK_2026-06-17.md` for current risk interpretation.  
Mode: documentation/evaluation only. No runtime code was changed while preparing this report.
Additional input incorporated: `C:\Users\Dr.Alizadeh\Desktop\Strategic Architecture Direction —.txt`.

## 1. Short Answer

The current code is in a better state than the previous full report described.

The most dangerous original failure class, a multi-study patient where a late DOC/DICOMized-document study becomes visible but is not downloaded, is now directly addressed by open-tab backfill plus late download enqueue.

Several earlier concerns are now fixed:

- Shared download payload now carries both `description` and `study_description`.
- Viewer canonical series identity now falls back to `series_instance_uid`.
- Open-tab backfill now tries every study UID in the patient study set, so it can find a tab keyed by a secondary/DOC study UID.
- Release parity tests now pass.

The remaining unresolved items can still cause trouble, but the type of trouble has changed:

- The remaining risks are mostly future edge-case, performance, queue-priority, and maintainability risks.
- The remaining risks are less likely to cause direct cross-patient mixing because owner guards and tests are now stronger.
- The system is still not a single optimized pipeline. It is a safer multi-path system with shared helper logic.

After incorporating the strategic architecture concern, the direct verdict is:

- The current code is improved enough to reduce the original critical multi-study/DOC failure.
- The current code does not yet satisfy the desired final architecture of one authoritative pipeline for sync, metadata, download, thumbnails, open, drag/drop, and viewport loading.
- The most important remaining weak point is architectural fragmentation: patient/study/series identity is safer, but it is still reconstructed in several places instead of being resolved once and passed through every workflow.
- The planned prior-study / National-ID / real-patient identity feature should not be added as a separate workflow. It should plug into the same unified identity/catalog/download/viewer pipeline.

## 2. Evidence From Current Recheck

Focused tests were run with `.venv`.

Passed:

- Patient study-set / resolver / backfill / series identity: 43 passed.
- Resync / storage manifest / orphan prune / content version: 62 passed.
- Download Manager identity / dedup / preempt / image-count tests: 29 passed.
- Builder release parity guards: 14 passed.
- Syntax compile passed for the reviewed pipeline modules.

Total focused validation: 148 tests passed.

Important current code points:

- `PacsClient/utils/patient_study_set.py`
  - `PatientStudySetService`
  - `merge_study_uids`
  - `resolve_study_uids`
  - `build_download_payload`

- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py`
  - `_PSS_MERGE_RESOLVE`
  - `_backfill_open_viewer_studyset`
  - `_enqueue_missing_series_for_open_study`
  - double-click open missing-only filtering

- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py`
  - single-click no-download behavior
  - resync-on-reopen
  - disk-aware resync decisions

- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`
  - canonical viewer-to-DM series identity
  - `series_uid` / `series_instance_uid` fallback

- `modules/storage/sync_manifest.py`
  - disk-first local-vs-server completeness decision

- `modules/download_manager`
  - duplicate task protection
  - stale completed-state handling
  - series membership validation
  - immutable progress totals

## 3. What Is Now Resolved Since the Previous Report

### 3.1 Download Payload Description Mismatch

Previous concern:

`build_download_payload` only emitted `description`, while Download Manager queue code reads `study_description`.

Current state:

Fixed. The payload now includes both:

```python
'description': info.get('study_description', ''),
'study_description': info.get('study_description', ''),
```

Risk now:

Low. This should no longer cause study description loss in Download Manager paths using the shared payload builder.

### 3.2 `series_instance_uid` Fallback in Viewer Canonical Identity

Previous concern:

`_vc_load.py` canonical identity resolver read only `series_uid`.

Current state:

Fixed. It now reads:

```python
entry.get('series_uid') or entry.get('series_instance_uid')
```

Risk now:

Low. UID-based handoff to Download Manager is stronger and less dependent on series-number-only fallback.

### 3.3 Backfill Tab Lookup by Only First Study UID

Previous concern:

Open-tab backfill looked up the viewer tab using only the first study UID in the discovered set.

Current state:

Improved. Backfill now tries every study UID in the patient set and has a focused test where the tab is keyed by a secondary/DOC UID.

Risk now:

Low to medium-low. There can still be unusual lifecycle cases where the widget is closed or stale, but the original primary-vs-secondary UID blind spot is covered.

### 3.4 Release Parity

Previous concern:

`test_release_gate_stage_config_parity_against_current_stage` failed because staged `patient_table_sort.json` differed from repo config.

Current state:

Fixed. Builder release parity guards now pass.

Risk now:

Low for this specific issue.

## 4. Current Architecture State

The code now has a partial shared architecture:

```text
Patient row / selected study / local cache / server row
        |
        v
_resolve_patient_study_uids / reconcile / resync / enumeration
        |
        v
shared merge + owner filter helpers
        |
        v
open viewer / right panel / backfill / download manager
```

The architecture is safer than before because shared functions now handle critical pieces:

- selected-first ordering;
- deduplication;
- cross-patient owner filtering;
- shared download payload shape;
- late viewer backfill;
- late open-intent download enqueue;
- disk-aware completeness checks.

But it is not yet the final ideal architecture:

```text
PatientStudySetService.resolve(intent, patient_id, selected_study_uid)
        |
        v
PatientStudySet
        |
        v
DownloadPlanBuilder.from_patient_study_set(...)
        |
        v
one download/preview/open/backfill path
```

That final form is not fully implemented yet.

## 5. Unresolved Steps and Whether They Can Cause Trouble

### 5.1 Unresolved Step: Full `PatientStudySetService.resolve()`

Current state:

`PatientStudySetService` exists, but it is still mostly a facade around pure helper functions. It does not yet own the full process of gathering study sources from:

- selected table row;
- row `study_uids`;
- row `studies`;
- latest study UID;
- right-panel fallback;
- local DB;
- cached patient-study map;
- server patient row;
- per-modality enumeration;
- fresh server study info.

Can this cause trouble?

Yes, but mostly as future or edge-case trouble, not as an immediate guaranteed bug.

Why:

When study-source gathering remains distributed, different workflows can still discover slightly different study sets:

- double-click open;
- single-click preview;
- background reconcile;
- manual refresh;
- already-open refresh;
- plus-button/manual download.

This can recreate divergence if a future change updates one path and not the others.

Likely symptoms if it happens:

- One path shows a study that another path does not.
- Right panel has more studies than the open viewer until backfill runs.
- A late DOC/new study is handled later than ideal.
- Logs show late growth/backfill instead of complete first-pass resolution.

Severity:

Medium now. Previously this was high. It is lower now because late backfill and late download enqueue provide a safety net.

Recommendation:

Still implement a real `PatientStudySetService.resolve()` as the single authority. This remains the most important architecture cleanup.

### 5.2 Unresolved Step: Shared `DownloadPlan`

Current state:

There is a shared `build_download_payload`, but there is not yet a true typed `DownloadPlan` that every workflow consumes.

Current paths differ:

- Main double-click open filters to missing/partial series before calling `start_priority_download_immediately`.
- Late backfill gates with `evaluate_sync`, then passes the server series payload to `add_downloads`.
- Resync/manual refresh also use shared payloads but rely on Download Manager skip/resume behavior.
- Viewer retry/priority paths use their own targeted series identity handling.

Can this cause trouble?

Yes, but the likely trouble is inefficiency, inconsistent priority, and harder debugging rather than direct wrong-patient data mixing.

Likely symptoms:

- Download Manager queue contains broader tasks than necessary.
- Complete series are skipped later by DM instead of never entering the plan.
- Progress/log messages may be noisier than needed.
- Late studies may be queued differently from main open studies.
- Future changes could fix missing-only logic in one caller but not another.

Severity:

Medium.

Recommendation:

Create a `DownloadPlan` with:

- patient ID;
- patient name;
- study UID;
- owner verification result;
- missing series list;
- partial series list;
- priority/open intent;
- source reason;
- full server metadata for display only.

Then make double-click open, backfill, manual refresh, resync, and manual download consume that same plan.

### 5.3 Unresolved Step: Late Backfill Uses `add_downloads`, Not Main Open Priority Path

Current state:

Main double-click open uses:

```python
start_priority_download_immediately(...)
```

Late backfill uses:

```python
dm.add_downloads(..., start_immediately=True)
```

Can this cause trouble?

Potentially yes under a busy queue or active competing downloads.

What kind of trouble:

- A late DOC/new study might download later than the originally opened imaging study.
- It may not get the exact same preemption/priority semantics as the explicit double-click open path.
- The user may see the DOC/new study in the viewer sidebar before its files arrive.

What it is unlikely to cause now:

- It is unlikely to cause cross-patient mixing because owner checks are applied before attach/enqueue.
- It is less likely to cause "never downloaded" because the late enqueue now exists and tests cover it.

Severity:

Medium. This is not a catastrophic correctness bug, but it can affect user experience and timing.

Recommendation:

Make late open-tab backfill downloads carry explicit open-intent priority, either by routing through the priority API or by making `DownloadPlan` carry priority semantics consumed by Download Manager.

### 5.4 Unresolved Step: Missing-Only Filtering Is Split Across Layers

Current state:

Main open filters series before queueing:

```text
server series -> evaluate_sync -> _download_series_list -> priority download
```

Backfill/resync often do:

```text
server series -> evaluate_sync gate -> full payload -> DM R20 skips complete series
```

Can this cause trouble?

Yes, but mostly performance/control-plane trouble.

Likely symptoms:

- More queue/task work than necessary.
- Extra validation logs.
- Extra progress state to reconcile.
- Harder to reason about exactly what should download.

Safety factors:

- Download Manager R20 checks complete series.
- Validation rules are disk-aware.
- Task dedupe and count guards reduce inflated progress issues.

Severity:

Low to medium. It is not likely to re-download complete data in a dangerous way, but it keeps the pipeline harder to reason about.

Recommendation:

Move missing/partial filtering into shared `DownloadPlan` creation so the payload itself says what will download.

### 5.5 Unresolved Step: Different Real Patients With Multiple Patient IDs

Current state:

The system correctly treats `PatientID` as the strict identity key. It does not automatically merge multiple Patient IDs that may belong to the same real person.

Can this cause trouble?

It depends on the expected workflow.

For clinical safety:

This is safer than implicit merging. Different Patient IDs should not be silently merged without explicit user-confirmed patient linking.

For user workflow:

Yes, this can cause trouble if imported data uses multiple Patient IDs for the same real-world patient. The user may see separate patient rows/tabs for data that should be associated.

What it should not do:

It should not mix those Patient IDs automatically. Automatic merge would be more dangerous.

Severity:

Medium workflow risk, low mixing risk.

Recommendation:

If needed, implement explicit patient alias/linking:

- link multiple Patient IDs to one real-patient group;
- keep original DICOM PatientID preserved;
- show clear UI that records are linked;
- require user confirmation/audit trail.

### 5.6 Unresolved Step: Open-Time Orphan Series Pruning

Current state:

The open path calls `prune_orphan_series_for_study` for opening studies. It is guarded and conservative.

Can this cause trouble?

Possibly, mainly through latency or surprise mutation.

Likely symptoms:

- Slower open for large/multi-study patients.
- DB rows removed during open rather than during maintenance.
- If a storage mount is unusual or delayed, orphan detection must stay conservative.

Safety factors:

- It skips whole file-less studies.
- It skips pending zero-instance series.
- It checks storage root availability.
- It is flag-gated.

Severity:

Low to medium.

Recommendation:

Keep it for now because it repairs real broken DB/disk states, but add/monitor telemetry:

- prune duration;
- number of rows removed;
- study UID;
- whether source root was reachable.

Longer term, move broad cleanup to a maintenance tool and keep open-path repair narrow.

### 5.7 Unresolved Step: Sync Manifest Documentation Stale

Current state:

`modules/storage/sync_manifest.py` still says:

```text
Nothing in the live open/render path depends on this yet
```

But the open/resync paths now do depend on `evaluate_sync`.

Can this cause trouble?

Not at runtime. This is a developer-risk issue.

Likely symptom:

A future developer may think the module is inactive and change it without realizing it affects live open/resync behavior.

Severity:

Low, but easy to fix.

Recommendation:

Update the comment to say the module is now live and used by open/resync disk-aware decisions.

### 5.8 Unresolved Step: Old Reports Are Now Partly Outdated

Current state:

Some older reports still describe risks that are now fixed.

Can this cause trouble?

Yes, for planning. A developer could waste time fixing an already-fixed item or misunderstand the current risk profile.

Severity:

Low to medium documentation risk.

Recommendation:

Treat this report as current. Older reports should be read as historical context unless they have an explicit current-state note.

The previous full report now has a superseded note pointing here.

## 6. Can the Remaining Unresolved Steps Recreate the Original Critical Bug?

Original critical bug class:

```text
multi-study patient
  -> double-click opens incomplete set
  -> later reconcile discovers DOC/extra study
  -> viewer/download/cache/db do not converge
```

Current likelihood:

Reduced significantly.

Why:

- Late study growth is detected.
- Open viewer backfill exists.
- Backfill now tries all study UIDs to find the open tab.
- Late study download enqueue exists.
- Cross-patient owner guards exist.
- Disk-aware sync prevents DB-only false completeness.
- Focused tests cover key backfill and no-open-tab behavior.

Remaining ways trouble could still happen:

1. Server metadata is incomplete or wrong.
   - If server omits owner patient ID or returns incomplete study lists, the client can only do best-effort.

2. Late backfill download is queued but does not get open priority.
   - This can delay download, especially under active queue pressure.

3. Download Manager rejects or skips due to an untested state transition.
   - Stale-completed handling is stronger now, but complex live queues can still expose edge cases.

4. A future code change updates one path and misses another.
   - This remains the main reason to finish `PatientStudySetService.resolve()` and `DownloadPlan`.

Conclusion:

The original bug is no longer the obvious expected behavior. The current unresolved steps are more likely to cause delayed/partial convergence or future regression, not immediate guaranteed failure.

## 7. Cross-Patient Mixing Risk

Current risk:

Low, assuming server and local DB owner metadata are accurate.

Why:

- Resolver drops positively foreign studies.
- Backfill skips positively foreign studies.
- Resync skips positively foreign studies.
- Download queue path guards against foreign extra studies.
- Unknown owner is kept by design to avoid blocking fresh server studies.

Remaining risk:

If a study has unknown owner locally and server metadata is missing or wrong, the client cannot prove it is foreign. That is a data-quality boundary, not a pure client logic issue.

Recommendation:

For high-risk workflows, log unknown-owner multi-study additions clearly and consider a stronger validation mode for production:

- allow known same-patient;
- allow selected study;
- require server owner for extra studies before attaching/downloading;
- or warn when owner is unknown.

## 8. Download / Cache / Disk Convergence Risk

Current risk:

Medium-low.

Why improved:

- Disk manifest is now used.
- Pixel-less stub detection exists.
- Stale completed-state reset exists.
- DM R20 skips complete series.
- Open path filters missing series before priority queue.
- Backfill now enqueues late studies.

Remaining risk:

Because missing-only filtering is not centralized, different paths still rely on different layers for the final "what downloads" decision.

Recommendation:

Centralize as `DownloadPlan`.

## 9. Patient ID Alias Risk

Current behavior:

Multiple Patient IDs are not automatically grouped as one real patient.

Can this cause trouble?

Yes, if the desired workflow is "same real person across imported IDs should appear together." But automatic grouping would be clinically risky.

Recommendation:

Do not auto-merge. Build explicit patient alias/linking if needed.

## 10. Current Risk Table

| Area | Current Status | Can It Cause Trouble? | Severity | Type of Trouble |
|---|---|---:|---:|---|
| Late DOC/new study not downloaded | Improved/fixed path exists | Possible only in edge states | Medium-low | Delay or queue issue |
| Cross-patient study mixing | Strongly guarded | Low | Low | Mostly bad metadata boundary |
| `study_description` payload | Fixed | Unlikely | Low | None expected |
| `series_instance_uid` fallback | Fixed | Unlikely | Low | None expected |
| Backfill tab lookup | Improved | Unlikely/common case covered | Low | Stale widget/lifecycle only |
| Full `PatientStudySetService.resolve()` | Not complete | Yes | Medium | Path divergence/future regression |
| Shared `DownloadPlan` | Not complete | Yes | Medium | Priority/missing-only inconsistency |
| Late backfill priority | Not unified | Yes | Medium | Late study downloads slower |
| Missing-only filtering | Split across layers | Yes | Low-medium | Extra queue/log/progress work |
| Patient ID aliases | Not solved | Yes | Medium workflow | Same real patient split across IDs |
| Orphan prune during open | Live/guarded | Possible | Low-medium | Open latency/surprise DB mutation |
| Sync manifest comment | Stale | Developer only | Low | Misleading maintenance context |

## 11. Recommended Next Steps

### Priority 1: Create real `PatientStudySetService.resolve()`

Goal:

One service returns the same study set for open, preview, resync, backfill, and manual download.

This is the most important remaining architectural cleanup.

### Priority 2: Create shared `DownloadPlan`

Goal:

Every workflow uses the same missing/partial filtering, priority, payload schema, and owner validation.

This removes the current split between:

- main open filtering before queue;
- backfill/resync relying on DM skip logic.

### Priority 3: Give late backfill open-priority semantics

Goal:

If a viewer tab is open and a late DOC/new study is discovered, treat its missing series as part of the open intent, not generic queue work.

### Priority 4: Update stale live-code comments

Goal:

Mark `sync_manifest.py` as live in open/resync disk-aware decisions.

### Priority 5: Decide explicit patient-alias policy

Goal:

If multiple Patient IDs can belong to the same real patient, support explicit linking, not automatic silent merging.

## 12. Strategic Direction From User Concern

The strategic concern is correct: the main remaining architectural risk is not
only "does the current 46630/DOC case work?" The larger risk is that the repo
still has many partially overlapping workflows for patient/study/series discovery
and preparation.

The user requirement is:

```text
Create one correct, unified, optimized pipeline for:
server sync -> local manifest/database -> download manager -> metadata/header
indexing -> thumbnails -> patient open -> drag/drop -> viewport loading.
```

This is the right direction. The current code has moved toward it, but has not
fully arrived.

The present state should be described as:

```text
safer multi-path architecture with shared helper contracts
```

not yet:

```text
single authoritative patient/study/series pipeline
```

This distinction matters because the next planned feature, prior studies linked
by reception/National ID/real-patient identity, will add another identity layer.
If it is added before the current paths are unified, it can multiply the same
class of bugs:

- studies visible in one workflow but missing in another;
- thumbnails not matching opened studies;
- drag/drop targeting the wrong study/series;
- download/cache/database disagreement;
- prior studies accidentally treated as current-study siblings without clear
  identity policy.

## 13. Current Workflow Path Map

This is the practical map of the major current paths and where they still differ.

### 13.1 Single-Click Thumbnail / Preview Path

Main code:

- `_load_and_display_series_info`
- `_reconcile_patient_studies_on_click`
- `_show_grouped_patient_studies`
- `show_patient_studies`

Current strength:

- Single-click is now clearly preview/select intent.
- It avoids automatic full download by default.
- It can discover late studies and trigger open-tab backfill if a viewer tab is open.

Weak point:

- It still performs its own patient/study reconciliation and server-row parsing.
- It can still discover a richer study set than the first open path, which means
  complete study-set resolution is not yet centralized.

Trouble potential:

Medium. Current backfill reduces the damage, but future edits can still make
single-click and double-click disagree.

### 13.2 Double-Click Open Path

Main code:

- `_on_patient_double_clicked_async`
- `_resolve_patient_study_uids_async`
- `_resolve_patient_study_uids`
- `start_priority_download_immediately`
- `set_server_series_info`

Current strength:

- This is currently the best base path.
- It has explicit open intent.
- It fetches fresh server series info.
- It applies cross-patient owner guards.
- It filters complete/missing/partial series using `evaluate_sync`.
- It sends full viewer metadata into the open tab.

Weak point:

- It still contains too much orchestration directly in the UI mixin.
- It builds download/task payload details locally instead of consuming a shared
  `DownloadPlan`.
- It is not yet only a caller of `PatientStudySetService.resolve()`.

Trouble potential:

Medium. It is strong today, but the logic is hard to reuse safely across other
workflows.

### 13.3 Download Path

Main code:

- `modules/download_manager/ui/widget/_dm_queue.py`
- `modules/download_manager/ui/widget/_dm_priority.py`
- `modules/download_manager/coordinator/series_intent_coordinator.py`
- `modules/download_manager/download/series_downloader.py`
- `modules/download_manager/rules/validation_rules.py`

Current strength:

- Task identity is study-centered.
- Duplicate series/task inflation is guarded.
- Stale completed state is disk-aware.
- Series membership validation protects against synthetic display keys.
- Progress denominator mutation is guarded.

Weak point:

- It still receives differently shaped requests from different upstream paths:
  main open, late backfill, resync/manual refresh, viewer retry, manual download.
- It acts as a downstream safety net for upstream inconsistency.

Trouble potential:

Medium. The current DM is robust, but relying on it to correct all upstream
payload differences keeps debugging harder than necessary.

### 13.4 Server Sync / Local Manifest Path

Main code:

- `modules/storage/sync_manifest.py`
- content version store
- `_resync_patient_studies_from_server`
- `evaluate_sync`

Current strength:

- Disk-first sync state is a good direction.
- Manifest compares local files against server series.
- Content version can avoid unnecessary rescans.

Weak point:

- The manifest is used by open/resync/backfill, but metadata indexing and viewer
  loading are not fully consolidated around one local model yet.
- The module comment still under-states that this code is live.

Trouble potential:

Low to medium. Runtime behavior is improving, but developer misunderstanding
and partial adoption are still risks.

### 13.5 Thumbnail Path

Main code areas:

- right-panel thumbnail display;
- grouped patient studies;
- `set_server_series_info`;
- thumbnail cache / server thumbnail helpers;
- local thumbnail load for downloaded studies.

Current strength:

- Multi-study grouping and late backfill are much better than before.
- DOC studies can be shown after late discovery.

Weak point:

- Thumbnail grouping is still not purely a view over one canonical
  `PatientStudySet`.
- Thumbnail visibility and viewer-open metadata can still be prepared by
  different paths.

Trouble potential:

Medium. This is exactly where users notice "it showed in the list but disappeared
after opening."

### 13.6 Drag-and-Drop / Viewport Loading Path

Main code:

- `_vc_load.py`
- viewer thumbnail handlers;
- `_trigger_download_if_needed`
- `_notify_dm_viewed_series`
- Download Manager priority handoff.

Current strength:

- Synthetic multi-study display keys are now resolved to canonical study/series
  identity before DM notification.
- `series_instance_uid` fallback is now present.

Weak point:

- Drag/drop still depends on the viewer having a correct `_server_series_info`
  map.
- That map is fed by open/backfill/grouped paths, not by one universal
  patient-study-series model.

Trouble potential:

Medium. The current fixes reduce wrong-target bugs, but the path should still
be unified with the same source model as open and thumbnails.

### 13.7 FAST / Advanced / MPR Viewer Paths

Current strength:

- The report does not identify a need to change clinically verified geometry.
- Viewer identity handoff is safer now.

Weak point:

- Data discovery and metadata preparation are not yet fully shared across FAST,
  Advanced, and MPR/VTK surfaces.
- There is a risk of fixing identity in one viewer path while another still uses
  older assumptions.

Trouble potential:

Medium if new multi-study/prior-study data is introduced before a shared model.
High only if unification touches geometry/slice ordering unsafely.

Rule:

Do not change clinically verified geometry, orientation, slice order, or MPR
behavior as part of pipeline unification unless a separate confirmed bug proves
those outputs wrong.

### 13.8 Import / DICOMized Document Path

Main code areas:

- import preview dialog;
- study save helpers;
- DICOMized document studies;
- local DB insert/update;
- disk storage under `SOURCE_PATH / StudyInstanceUID`.

Current strength:

- DICOMized DOC studies are treated as separate studies and can now be backfilled
  and downloaded under an open patient.

Weak point:

- Imported patients with different Patient IDs are not unified under a real
  patient identity model.
- Import metadata and live-server metadata can enter the system through different
  paths.

Trouble potential:

Medium. This becomes more serious when prior studies by National ID/reception
identity are introduced.

## 14. Repo / Code / Structure Weak Points

### 14.1 Weak Point: UI Mixins Still Own Too Much Workflow Logic

The home-panel mixins still contain heavy orchestration:

- study discovery;
- server fetch;
- cache behavior;
- download planning;
- viewer metadata push;
- resync decisions;
- late backfill decisions.

Why this is weak:

UI classes should mostly call services and render results. When the UI owns the
workflow, every new UI action risks creating another variant of the same pipeline.

Can this cause trouble?

Yes. This is one of the main reasons one fix can solve one path but not another.

Recommended direction:

Move workflow decisions into services:

- `PatientStudySetService`
- `StudySyncService`
- `DownloadPlanBuilder`
- `ThumbnailCatalogService`
- `ViewerLoadPlanService`

### 14.2 Weak Point: No Real Patient Identity Layer Yet

Current identity model is strong for DICOM safety:

- `PatientID`
- `StudyInstanceUID`
- `SeriesInstanceUID`
- `SOPInstanceUID`

But it does not yet model:

- real patient identity;
- National ID;
- reception identity;
- prior-study link identity;
- explicit patient aliases.

Why this is weak:

The next feature will link prior studies that may have different Patient IDs.
Without an explicit identity layer, developers may be tempted to overload
`PatientID`, patient name, or reception code.

Can this cause trouble?

Yes. This is the biggest future-feature risk.

Recommended direction:

Add an explicit, audited identity model:

```text
RealPatientIdentity
    -> one or more PatientID aliases
    -> one or more StudyInstanceUIDs
    -> optional reception/National-ID links
```

Do not silently merge Patient IDs. Link them explicitly and visibly.

### 14.3 Weak Point: No Single Local Metadata Catalog

Metadata currently exists in several places:

- server responses;
- `dicom.db`;
- download progress DB/state store;
- sync manifest;
- thumbnail cache;
- viewer `_server_series_info`;
- right-panel thumbnail payloads;
- disk DICOM headers.

Why this is weak:

Different paths can believe different metadata is authoritative.

Can this cause trouble?

Yes. This explains cases where thumbnails appear but opened studies differ, or
drag/drop sees a different series identity than the right panel.

Recommended direction:

Create a local metadata catalog/read model populated by sync/download/import:

```text
PatientStudyCatalog
    patient identities
    studies
    series
    instances
    thumbnails
    local availability
    server version/content version
    mode/source
```

Viewer setup should consume this catalog. Disk header reading should be fallback,
not repeated normal flow.

### 14.4 Weak Point: Download Planning Is Not a First-Class Object

There is no typed `DownloadPlan` yet.

Why this is weak:

Each caller still decides parts of:

- what series are missing;
- what priority applies;
- whether this is open intent;
- whether stale completed state should be reset;
- what payload fields are included.

Can this cause trouble?

Yes. It can cause queue priority differences, noisy progress, and future
regressions when new workflows are added.

Recommended direction:

Introduce:

```text
DownloadPlan
    patient_id
    real_patient_id optional
    study_uid
    series_to_download
    reason
    intent
    priority
    owner_verified
    local_state
    server_version
```

All download entrypoints should use it.

### 14.5 Weak Point: Thumbnail Model Is Not Fully Canonical

Thumbnails are user-visible evidence of the study model, but they can still be
prepared by separate preview/open/grouped paths.

Can this cause trouble?

Yes. This is a common source of user-facing inconsistency.

Recommended direction:

Make thumbnails a projection of the same `PatientStudyCatalog` / `PatientStudySet`,
not a separate grouping authority.

### 14.6 Weak Point: Viewer Loading Still Depends on Preloaded Side Maps

The viewer relies on metadata maps such as `_server_series_info` and
`_studies_series`.

Can this cause trouble?

Yes, if those maps are incomplete or built differently for single-click,
double-click, backfill, import, or prior-study flows.

Recommended direction:

Viewer loading should receive a normalized `ViewerLoadPlan` generated from the
same catalog. The viewer can still render with FAST/Advanced/MPR-specific logic,
but discovery and identity should be shared.

### 14.7 Weak Point: Mode Awareness Is Not Yet Front-and-Center in This Pipeline

The strategic text correctly separates:

- live server mode;
- local DB/cache mode;
- import mode;
- CD mode;
- offline cloud mode.

Can this cause trouble?

Yes. A unified path must not accidentally force live-server logic onto imported
or CD/offline studies.

Recommended direction:

Every pipeline request should carry a mode:

```text
WorkflowMode.LiveServer
WorkflowMode.LocalDatabase
WorkflowMode.Import
WorkflowMode.OfflineCloud
WorkflowMode.CDBurn
```

Then sync/download/cache decisions should be mode-policy driven.

### 14.8 Weak Point: Too Many Historical Reports Can Confuse Current Work

There are now many reports and some are historical.

Can this cause trouble?

Yes, but only in planning. People may chase already-fixed risks.

Recommended direction:

Keep one current "authoritative status" report per area and mark older reports as
historical/superseded.

## 15. Best Current Base Path

The best current path to use as the base for the unified pipeline is the
double-click open path, specifically the current combination of:

- fresh study resolution;
- owner-guarded study acceptance;
- `evaluate_sync` disk-aware local-vs-server check;
- missing/partial filtering;
- priority download;
- viewer `set_server_series_info`;
- open-tab backfill safety net.

Why this is the best base:

- It has explicit user intent: open/view patient.
- It already handles multi-study better than the other paths.
- It already avoids redundant re-download when complete.
- It already handles missing/partial studies.
- It already pushes viewer metadata.
- It has the strongest clinical isolation checks.

But it should not remain inside the UI mixin. It should be extracted into a
service-level pipeline:

```text
PatientOpenPipeline
    -> PatientStudySetService.resolve(...)
    -> StudySyncService.evaluate(...)
    -> DownloadPlanBuilder.build(...)
    -> ThumbnailCatalogService.prepare(...)
    -> ViewerLoadPlanService.build(...)
```

Then single-click, resync, drag/drop, import, and future prior-study work should
use the same model with different intents.

## 16. Target Architecture

### 16.1 Identity Model

Required identity separation:

```text
RealPatientIdentity / NationalID / ReceptionIdentity
PatientID
StudyInstanceUID
SeriesInstanceUID
SOPInstanceUID
AccessionNumber
Modality
Source mode
```

Rules:

- Do not use PatientID where StudyInstanceUID is required.
- Do not use series number without study UID.
- Do not merge Patient IDs without explicit alias/link state.
- Preserve original DICOM identity.

### 16.2 Catalog / Metadata Model

Create a canonical local read model:

```text
PatientStudyCatalog
    patients
    patient aliases
    studies
    series
    instances
    thumbnails
    documents
    local availability
    server freshness/content version
    source mode
```

Server/download/import update the catalog. UI/viewers read from it.

### 16.3 Sync Model

Live-server mode:

- server version/manifest is authoritative for freshness;
- disk remains source of truth for local availability;
- missing/partial series produce a `DownloadPlan`.

Local/import/CD/offline modes:

- local source is authoritative unless explicitly synced;
- live-server calls must be mode-policy controlled.

### 16.4 Download Model

All downloads should use:

```text
DownloadPlan -> DownloadManager
```

not ad-hoc dicts per caller.

### 16.5 Thumbnail Model

Thumbnails should be:

```text
PatientStudyCatalog projection -> thumbnail UI
```

The same study/series model should feed single-click thumbnails and opened viewer
sidebars.

### 16.6 Viewer Loading Model

Viewer loading should use:

```text
ViewerLoadPlan
    study_uid
    series_uid
    series_number
    instance list / local paths
    metadata
    local availability
```

FAST, Advanced, and MPR can render differently, but discovery/identity should be
shared.

Geometry, orientation, slice order, VTK/MPR behavior, and clinically verified
rendering must remain protected unless a separate confirmed clinical bug requires
change.

## 17. Updated Acceptance-Criteria Status

| Acceptance Criterion | Current Status | Risk |
|---|---|---|
| Complex patients handled reliably | Improved, not fully proven | Medium |
| All same-PatientID studies visible/preserved | Mostly improved by resolver/backfill | Medium-low |
| Thumbnails and opened studies use same model | Not fully unified | Medium |
| Drag/drop loads correct series | Improved identity handling, not fully catalog-backed | Medium |
| Download manager uses correct unique identity | Stronger now | Low-medium |
| No duplicate/conflicting paths | Not met | Medium |
| Prior-study future feature can use same pipeline | Not ready yet | Medium-high |
| Performance equal or better | Many improvements, but not globally proven | Medium |
| Stability/reliability improve | Yes for current bug class | Medium-low |
| Final build uses unified path | Not yet | Medium |

## 18. Strategic Recommendation

Do not add prior-study/National-ID complexity as a new separate workflow.

Before that feature, implement at least the foundation of:

1. `PatientStudySetService.resolve()` as the single study-set authority.
2. `DownloadPlan` as the single download decision object.
3. `PatientStudyCatalog` or equivalent local read model for metadata/thumbnails.
4. Mode policy attached to every pipeline request.
5. Viewer load plans generated from the same identity model.

This does not require a risky rewrite of rendering. It is mostly a data-path and
workflow-authority unification.

## 19. Final Assessment

The current code is much safer than the earlier architecture review state.

The following are now in good shape:

- late open-viewer backfill;
- late download enqueue;
- payload description parity;
- `series_instance_uid` fallback;
- secondary-study tab lookup;
- release parity;
- focused regression tests.

The remaining unresolved work can still cause trouble, but mostly in these forms:

- delayed late-study download under queue pressure;
- future divergence between open/reconcile/resync/manual paths;
- extra queue/progress work from non-centralized missing-only filtering;
- workflow confusion around same real patient with multiple Patient IDs;
- developer confusion from stale comments/reports.

The remaining items are worth fixing, but the immediate high-risk clinical mixing/download-loss situation is much better controlled than before.
