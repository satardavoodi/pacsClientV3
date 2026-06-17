# Unified Patient-Study Pipeline Review

Date: 2026-06-17

Status: architecture evaluation and recommendation. This report changes
documentation only. No application code is changed by this report.

Related reports:

- `docs/reports/MULTI_STUDY_MULTI_PATIENT_ID_ARCHITECTURE_REVIEW_2026-06-16.md`
- `docs/reports/MULTI_STUDY_CODE_CHANGE_REVIEW_2026-06-16.md`
- `docs/reports/MULTI_STUDY_OPEN_VS_SELECT_DIVERGENCE_46630_2026-06-17.md`
- `docs/reports/PIPELINE_REVIEW_OPEN_THUMB_DOWNLOAD_DRAGDROP_2026-06-14.md`
- `docs/reports/RESYNC_ON_REOPEN_45611_2026-06-14.md`
- `docs/reports/SYNC_DOWNLOAD_LIFECYCLE_REVIEW_2026-06-15.md`
- `docs/architecture/SYNC_MODE_SEPARATION.md`

## 1. Executive Summary

The requested architecture goal is:

> All patient/study workflows should use one best, optimized, clinically safe
> path that covers single-study, multi-study, multi-modality, multiple Patient
> IDs, DICOMized documents, local/server sync, downloads, cache, database, and
> disk state.

The current codebase does **not** fully satisfy that goal yet.

The current state is materially better than the earlier multi-study failure
state. Several important guards now exist:

- `StudyInstanceUID` remains the correct disk and database study identity.
- Viewer-to-Download-Manager series identity is safer than before.
- Critical download intent now has membership validation.
- Cross-patient study guards exist in multiple paths.
- Resync is disk-aware, mode-aware, and throttled.
- Double-click open increasingly downloads only missing or partial series.
- Multi-study grouped thumbnails can render studies with colliding series
  numbers.

However, the system still does not have a single canonical authority for:

```text
patient -> current complete study set -> per-study series set -> local/server
sync status -> render payload -> download payload
```

Instead, the code contains several independently implemented paths that answer
"which studies belong to this patient?" and "which series should be shown or
downloaded?" from different sources, at different freshness levels, and with
different side effects.

This means the current architecture is **improved but not unified**. It is a set
of increasingly well-guarded paths, not one optimized path.

The most visible consequence is the 46630 class of bug: a single-click path can
discover and render the full patient study set, including a DICOMized DOC study,
while the first double-click open can build the viewer from a smaller study-set
snapshot and never push the late-discovered study into the already-open viewer.

The recommended direction is to introduce a canonical `PatientStudySetService`
and a single immutable `PatientStudySet` result object. All workflows should call
that service, then apply only an action-specific intent:

- preview only
- open viewer and download missing
- refresh already-open viewer
- manual refresh/sync
- manual download
- local-only restore
- offline-cloud preview/open
- import/CD local workflow

The path can still be optimized and mode-aware. "One path" does not mean every
click does an expensive server refresh. It means every workflow uses the same
resolution contract, ownership checks, identity normalization, sync evaluation,
and payload builders.

## 2. Short Answer to the Current Question

Question:

> Does the current situation cover the goal that all pipelines use one best and
> optimized path?

Answer:

**No.**

The current code covers many important safety aspects, but it does not yet route
all patient/study workflows through one canonical path.

The current implementation has multiple authorities:

- table-row study UID metadata
- `_patient_study_uid_map`
- `_server_patient_meta_by_pid`
- right-panel thumbnails
- `_resolve_patient_study_uids`
- `_resolve_patient_study_uids_async`
- `_reconcile_patient_studies_on_click`
- `_resync_patient_studies_from_server`
- `_show_grouped_patient_studies`
- `show_patient_studies`
- double-click open step 3.5 download assembly
- manual download prefetch
- viewer `set_server_series_info`

Some of these share helpers, but they do not consume one canonical
patient-study-set object.

## 3. What "One Optimized Path" Should Mean

A correct unified design should not be a single giant function. It should be one
canonical data contract plus a small number of policy-controlled stages.

The canonical pipeline should be:

```text
User action or system event
    -> resolve patient context
    -> resolve complete study set
    -> validate study ownership
    -> fetch or merge per-study series metadata
    -> evaluate DB/cache/disk/server sync state
    -> build viewer payload
    -> build right-panel thumbnail payload
    -> build download payload
    -> apply action intent
```

The critical rule is that all user-facing workflows consume the same resolved
object:

```text
PatientStudySet
```

Then each workflow decides what to do with that object:

- single-click displays thumbnails but does not download full images;
- double-click opens the viewer and downloads only missing/partial data;
- already-open refresh pushes the same full study set into the existing viewer;
- manual refresh bypasses throttles and can enqueue missing data;
- local DB mode uses local-only policy unless explicit server sync is requested;
- offline cloud uses package/local sync policy;
- import/CD uses local-only ownership and disk authority.

## 4. Current Pipeline Map

### 4.1 Single-click preview path

Primary functions:

- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py`
  - `_load_and_display_series_info`
  - `_reconcile_patient_studies_on_click`
  - `_resync_patient_studies_from_server`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_search.py`
  - `show_patient_studies`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_modules.py`
  - `_show_grouped_patient_studies`

Behavior:

1. Marks the event as preview/select.
2. Calls `_reconcile_patient_studies_on_click`.
3. Uses a fresh `search_patients_sync` call when not throttled.
4. Reads `study_uids`, `studies`, `study_list`, and `latest_study_uid` when present.
5. May run per-modality enumeration.
6. Saves newly discovered study metadata.
7. Does not start full image download by default.
8. Renders right-panel thumbnails via single-study or grouped path.
9. Starts background resync for already-local/grown studies.

Strength:

- This path is often the strongest at discovering hidden studies because it does
  a fresh patient-row search.

Weakness:

- It owns study-set discovery logic that double-click open does not fully share.
- Its late discoveries mainly update the home/right panel, not necessarily an
  already-open viewer tab.

### 4.2 Double-click open path

Primary function:

- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py`
  - `_on_patient_double_clicked_async`
  - `_resolve_patient_study_uids`
  - `_resolve_patient_study_uids_async`
  - `_enumerate_studies_for_row`

Behavior:

1. Resolves `all_study_uids` before opening.
2. Opens the viewer tab immediately.
3. Sets multi-study hint when `len(all_study_uids) > 1`.
4. Fetches per-study series info for each resolved study.
5. Pushes aggregated series into `widget.set_server_series_info`.
6. Evaluates disk sync and queues only missing/partial series when possible.
7. Starts Download Manager critical/high priority path.
8. Schedules right-panel and series-info background tasks.

Strength:

- This is the best current path when `all_study_uids` is correct before the tab
  is created.
- It has cross-patient owner guards for extra studies.
- It pushes a patient-level series map into the viewer.
- It tries to avoid re-downloading complete studies.

Weakness:

- It can resolve the study set from stale or incomplete cached metadata.
- It does not always use the fresh study-set logic from single-click reconcile.
- If a missing study is discovered after the tab is created, the initial viewer
  may remain built as a single-study tab.

### 4.3 Already-open tab refresh path

Primary function:

- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py`
  - existing-widget branch inside `_on_patient_double_clicked_async`

Behavior:

1. Focuses the existing tab.
2. Optionally schedules forced resync.
3. Fetches series info for the current `study_uid`.
4. Calls `existing_widget.set_server_series_info`.

Strength:

- Fixes same-study server growth better than older behavior.
- Avoids the old "focus only and return" problem.

Weakness:

- It refreshes mainly the current study's series list, not necessarily the full
  patient study set.
- It is not the same sink used by late first-open discovery.
- It does not provide a guaranteed "patient study set grew, update open viewer"
  path for separate-study DOC cases.

### 4.4 Resync path

Primary function:

- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py`
  - `_resync_patient_studies_from_server`

Behavior:

1. Runs mode-aware remote sync policy.
2. Is throttled unless forced.
3. Fetches fresh series info per study.
4. Validates server-reported patient owner.
5. Uses content version fast gate when present.
6. Compares server series counts and local series counts.
7. Uses disk-aware manifest for missing/partial series.
8. Saves refreshed metadata.
9. Enqueues downloads only on forced/manual action or legacy env flag.
10. Re-renders the home/right panel when the active selection still matches.

Strength:

- This is one of the better guarded pieces.
- It correctly separates auto preview from manual download/sync.
- It is cross-patient guarded and off the UI thread for server work.

Weakness:

- It is primarily a right-panel reveal path.
- It does not own a unified update contract for an already-open viewer tab.
- Its growth logic is separate from double-click open's sync logic.

### 4.5 Plus-button preview path

Primary function:

- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_modules.py`
  - `on_plus_button_clicked`
  - `_show_grouped_patient_studies`

Behavior:

1. Reads patient data from the table row.
2. Uses `patient_data["study_uids"]` if present.
3. Falls back to the single `study_uid`.
4. Shows grouped or single-study thumbnails.

Strength:

- Simple and fast.

Weakness:

- It trusts the row payload instead of calling a canonical resolver.
- It can diverge from single-click and double-click if table metadata is stale.

### 4.6 Manual download path

Primary function:

- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_download.py`
  - `_on_download_requested`

Behavior:

1. Receives selected studies.
2. Prefetches missing series info in parallel.
3. Mutates selected study dicts with fetched series.
4. Calls `zeta_manager.add_downloads`.

Strength:

- Optimized by parallel prefetch.
- Avoids blocking the UI as badly as older sequential calls.

Weakness:

- It is another independent study/series enrichment path.
- It does not consume a canonical `PatientStudySet` or canonical download payload.

### 4.7 Viewer series metadata path

Primary functions:

- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py`
  - `set_server_series_info`
  - `_rebuild_multistudy_series_index`
  - `_schedule_multistudy_thumbnail_prefetch`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`
  - `_resolve_canonical_series_identity`
  - `_notify_dm_viewed_series`
  - `_trigger_download_if_needed`

Behavior:

1. Receives a series list.
2. Builds `_server_series_info`.
3. Builds `_studies_series`.
4. Handles multi-study display keys.
5. Supplies identity resolution for viewer-to-DM interaction.

Strength:

- Can represent multi-study series once it gets a correct full series list.
- Recent DM identity fixes make this much safer.

Weakness:

- It is a consumer, not an authority.
- If upstream gives it a partial study set, it cannot infer missing studies.
- It has historically been used as an implicit metadata authority.

## 5. Current Coverage Matrix

| Requirement | Current coverage | Assessment |
|---|---|---|
| Single-study patient open | Strong | Works in normal downloaded/opened cases. |
| Multi-study patient grouping | Partial to strong | Works when the correct full study set is known before render/open. |
| Multiple modalities | Partial | Per-modality enumeration exists, but not as one shared authority. |
| Separate-UID DICOMized DOC study | Partial | Can render in single-click/grouped path; first-open viewer can still miss it. |
| Multiple Patient IDs for same real patient | Weak | No master-patient or alias model. |
| Same Patient ID from different issuers | Weak | No issuer/assigning authority in local patient identity. |
| Cross-patient study leakage | Improved | Multiple guards exist, but they are repeated in several paths. |
| Download only missing/partial data | Improved | Stronger in open/resync, but not represented as one canonical payload builder. |
| Study restore from disk | Strong for study UID | Disk path is study-UID based and generally sound. |
| DB/cache/disk sync | Improved | Sync manifest and content version are good, but decisions are duplicated. |
| Already-open viewer update | Partial | Same-study refresh improved; late new-study insertion remains weak. |
| Local vs server data policy | Improved | Sync-mode policy exists, but not all paths consume one resolver. |
| Import/CD local workflows | Partial | Study UID separation is good; patient identity remains weak. |
| Unified optimized path | Not covered | This is the main architectural gap. |

## 6. Key Architectural Finding

The main weakness is **authority fragmentation**.

The recurring bugs are not caused by one bad helper. They come from several
helpers each being partly right:

- one path has fresher server patient data;
- one path opens the viewer quickly;
- one path knows how to group thumbnails;
- one path knows how to resync grown studies;
- one path knows how to enqueue missing series;
- one path knows how to refresh an already-open tab;
- one path knows how to protect Download Manager critical intent.

Because these are not composed through a single canonical result object, a fix in
one path does not automatically protect the others.

## 7. Why the Current State Still Allows 46630-Class Bugs

The 46630 report shows this exact failure class:

```text
single-click: fresh reconcile discovers imaging study + DOC study
double-click: open path resolves one study at tab creation
late reconcile/resync: discovers two studies after the viewer exists
result: home right panel updates, but open viewer remains incomplete
```

The failure is not that the system never finds the DOC study. It does find it.
The failure is that late study discovery does not have one canonical sink that
updates all interested consumers:

- home right panel;
- open viewer tab;
- Download Manager queue;
- DB/cache state;
- patient table study UID map.

This is the clearest evidence that current architecture is not yet one path.

## 8. Best Target Architecture

### 8.1 Introduce `PatientStudySetService`

Recommended module location:

```text
PacsClient/pacs/workstation_ui/home_ui/patient_study_set_service.py
```

or, if it should be shared outside Home UI:

```text
PacsClient/utils/patient_study_set_service.py
```

The service should own all study-set resolution and produce a single data
contract.

### 8.2 Canonical data objects

Suggested core objects:

```python
@dataclass(frozen=True)
class PatientStudySetRequest:
    patient_id: str
    patient_name: str
    selected_study_uid: str
    source_mode: str
    intent: str
    force_refresh: bool = False
    allow_remote: bool = True


@dataclass(frozen=True)
class SeriesDescriptor:
    study_uid: str
    series_uid: str
    series_number: str
    modality: str = ""
    description: str = ""
    image_count: int = 0
    thumbnail_path: str = ""
    is_document: bool = False


@dataclass(frozen=True)
class StudyDescriptor:
    study_uid: str
    patient_id: str
    patient_name: str
    modality: str = ""
    study_date: str = ""
    description: str = ""
    series: tuple[SeriesDescriptor, ...] = ()
    owner_verified: bool = False
    local_status: str = "unknown"
    server_status: str = "unknown"
    missing_series_numbers: tuple[str, ...] = ()
    partial_series_numbers: tuple[str, ...] = ()
    content_version: int | None = None


@dataclass(frozen=True)
class PatientStudySet:
    patient_id: str
    patient_name: str
    selected_study_uid: str
    studies: tuple[StudyDescriptor, ...]
    source_mode: str
    freshness: str
    warnings: tuple[str, ...] = ()
```

The exact class names can change, but the design principle should not: every
workflow receives the same resolved patient/study/series object.

### 8.3 Service stages

The service should perform these stages in this order:

1. Normalize input patient/study identifiers.
2. Read local table row, cached patient-study map, and DB study ownership.
3. Decide remote policy using sync-mode policy.
4. If allowed and needed, fetch fresh server patient row.
5. Parse all study UID sources:
   - selected `StudyInstanceUID`;
   - row `study_uids`;
   - row `studies`;
   - row `study_list`;
   - `latest_study_uid`;
   - DB studies for patient;
   - already-known `_patient_study_uid_map`;
   - optional per-modality enumeration.
6. Validate study ownership:
   - local DB owner check when present;
   - server `study_info.patient_id` check when fetched;
   - never attach a positively foreign study.
7. Fetch or merge per-study series metadata.
8. Normalize every series identity:
   - `StudyInstanceUID`;
   - `SeriesInstanceUID`;
   - original study-local `SeriesNumber`;
   - document/DOC marker when known.
9. Evaluate local DB/disk/server completeness:
   - sync manifest;
   - content version;
   - missing series;
   - partial series;
   - local-only status.
10. Build canonical payloads:
   - viewer series payload;
   - right-panel thumbnail payload;
   - download payload for missing/partial only;
   - table/cache update payload.

### 8.4 Action intents

The path should be shared, but side effects should depend on intent:

| Intent | Remote freshness | Render | Viewer update | Download |
|---|---|---|---|---|
| `preview_only` | fast/fresh if allowed | yes | no, unless tab already open and caller asks | no |
| `open_viewer` | fresh enough for selected patient | yes | yes, full study set | missing/partial only |
| `refresh_open_viewer` | forced fresh | yes | yes, full study set | missing/partial only if policy says yes |
| `manual_refresh` | forced fresh | yes | yes if open | missing/partial only |
| `manual_download` | forced or cached series metadata | optional | optional | yes |
| `local_restore` | local only | yes | yes | no |
| `offline_cloud_preview` | package/local | yes | no or yes by caller | package sync only |
| `import_cd` | local only | yes | yes after import | no server |

This is how the path stays optimized. The service contract is shared, but
expensive remote work is policy-driven.

## 9. What Should Become Consumers Only

The following code should eventually stop resolving patient study sets on its
own and consume `PatientStudySet` instead:

- `_load_and_display_series_info`
- `_reconcile_patient_studies_on_click`
- `_on_patient_double_clicked_async`
- existing-tab focus/refresh branch
- `_resync_patient_studies_from_server`
- `on_plus_button_clicked`
- `_show_grouped_patient_studies`
- `show_patient_studies`
- `_on_download_requested`

They should keep UI responsibilities, not authority responsibilities.

For example:

```text
single-click handler
    -> PatientStudySetService.resolve(intent="preview_only")
    -> RightPanelRenderer.render(study_set)
    -> maybe schedule background resync through same service
```

```text
double-click handler
    -> PatientStudySetService.resolve(intent="open_viewer", force_refresh=True)
    -> open tab immediately
    -> ViewerStudySetBridge.apply(widget, study_set)
    -> DownloadPlanner.enqueue_missing(study_set)
```

```text
already-open focus
    -> PatientStudySetService.resolve(intent="refresh_open_viewer", force_refresh=True)
    -> ViewerStudySetBridge.apply(existing_widget, study_set)
    -> DownloadPlanner.enqueue_missing(study_set)
```

## 10. Optimized Path Details

### 10.1 Fast first paint

The unified path must preserve the current good UX:

- open tab immediately;
- do not block first image on noncritical network calls;
- local disk/DB first where appropriate;
- background refresh after first paint;
- throttle remote checks.

The service can support this with freshness levels:

```text
local_fast
cached_server
fresh_patient_row
fresh_study_series
forced_fresh
```

Double-click can open with `local_fast` quickly, but it must still attach a
pending `PatientStudySet` update that will update the already-open viewer if the
study set grows.

### 10.2 Server calls should be intentional

One path does not mean "always call the server."

Recommended policy:

- Single-study, complete local DB, recent content version: no server call unless
  refresh requested.
- Server source, unknown completeness: lightweight patient-row refresh.
- Double-click open from server search: force per-study series info for selected
  patient, but only enqueue missing/partial.
- Local DB source: no live server call by default.
- Import/CD source: never auto-contact server.
- Offline cloud: use package/cloud-local policy.

### 10.3 Canonical identity rules

The unified path must enforce:

- `StudyInstanceUID` is the study key.
- `SeriesInstanceUID` is the series key when available.
- `SeriesNumber` is study-local only.
- Synthetic viewer display keys never leave the viewer boundary.
- `PatientID` alone is not enough for real-world patient identity.
- A positively foreign study must never be rendered or downloaded under the
  selected patient.

### 10.4 DICOMized document rules

DICOMized documents should be treated as first-class studies/series, not as an
afterthought:

- A DOC study with its own `StudyInstanceUID` belongs in the patient study set.
- DOC series may have reused or synthetic-looking series numbers such as
  `100000`; this must not collide with another study's series number.
- DOC visibility must not depend on whether it was discovered before or after
  viewer tab creation.
- DOC download behavior should follow the same missing/partial policy.
- DOC thumbnails and viewer entries must carry their true `study_uid`.

## 11. Current Strong Points to Preserve

Do not discard the recent fixes. The unified path should absorb them.

Preserve:

- Download Manager membership validation in
  `modules/download_manager/coordinator/series_intent_coordinator.py`.
- Canonical viewer-to-DM identity resolution in
  `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`.
- Immutable download progress totals in
  `modules/download_manager/download/series_downloader.py`.
- Disk-aware sync manifest in `modules/storage/sync_manifest.py`.
- Sync-mode policy in `modules/storage/sync_mode_policy.py`.
- Content-version fast gate where available.
- Cross-patient guards from open/reconcile/resync/grouped thumbnail paths.
- Grouped multi-study thumbnail rendering and synthetic display-key handling.
- Missing-only download planning from double-click open/resync.

The target is not a rewrite for its own sake. It is an authority collapse.

## 12. Current Gaps and Risks

### 12.1 No single study-set authority

The same question is answered by different functions:

```text
_resolve_patient_study_uids
_resolve_patient_study_uids_async
_reconcile_patient_studies_on_click
_resync_patient_studies_from_server
on_plus_button_clicked
manual download prefetch
```

This is the primary architectural flaw.

### 12.2 Late discovery has no universal sink

When a new study is discovered after first render/open, the current code may
update only one consumer.

Expected behavior:

```text
new study discovered
    -> update patient-study map
    -> update home right panel if active
    -> update open viewer tab if present
    -> update download plan if intent allows
    -> update DB/cache
```

Current behavior:

```text
new study discovered
    -> often updates home/right panel
    -> may not update already-open viewer tab
```

### 12.3 Open path and select path still differ

Single-click uses fresher patient-row data. Double-click uses a more compact
pre-open resolution path. This causes the open-vs-select divergence.

### 12.4 Cross-patient guards are repeated

Repeated guards are good defense in depth, but also evidence that ownership
validation is not centralized. The target service should centralize validation
and keep local defense-in-depth checks at sinks.

### 12.5 Patient identity model is still weak

The database still treats `patient_id` as unique local identity. That does not
model:

- issuer of Patient ID;
- assigning authority;
- multiple Patient IDs for one real person;
- same Patient ID from different sources;
- explicit patient merge/link decisions.

This is not required to unify the study pipeline, but it remains a future
architecture limitation.

### 12.6 Download planning is not one payload builder

Open, resync, and manual download build download payloads differently. They
should all consume a `DownloadPlan` derived from the same `PatientStudySet`.

### 12.7 DB/cache/disk decisions are duplicated

The sync manifest is strong, but its decision is not the only completeness
authority in the app. There are still local thumbnail gates, DB series counts,
content version checks, and per-path completeness decisions.

## 13. Recommended Migration Plan

### Phase 0: Freeze invariants

Add a short architecture contract before refactoring:

```text
PatientStudySet is the only authority for patient -> studies -> series
resolution in Home UI workflows.
```

Define invariants:

- All studies are keyed by `StudyInstanceUID`.
- All series carry both `SeriesInstanceUID` and original `SeriesNumber` when
  available.
- A series number is never globally unique.
- A synthetic viewer key is never accepted by storage/download/server APIs.
- Every extra study must pass owner validation if owner data is available.
- Every viewer update receives the full current study set, not only the selected
  study.

### Phase 1: Build read-only `PatientStudySetService`

Create the service without changing behavior first.

Initial implementation can internally call existing helpers:

- `_resolve_patient_study_uids`
- `_reconcile_patient_studies_on_click`
- `_get_or_fetch_series_info`
- `_local_series_counts`
- `sync_manifest.evaluate_sync`
- local DB owner lookups

The first milestone is producing a diagnostic object and logs:

```text
[PATIENT_STUDY_SET] patient=46630 selected=... studies=2 source=fresh_patient_row intent=open_viewer
```

No UI behavior should change in this phase.

### Phase 2: Use the service for double-click open

Double-click is the highest priority because it owns the viewer tab.

Change the open path so:

1. It requests `PatientStudySet` with intent `open_viewer`.
2. It opens the tab immediately.
3. It applies the full study set to the viewer.
4. It queues only missing/partial series from the service-generated download
   plan.
5. If the study set grows after tab creation, it applies the new full set to
   the existing viewer.

This phase directly addresses 46630.

### Phase 3: Use the service for single-click preview

Replace the study-discovery responsibility in `_reconcile_patient_studies_on_click`
with the service.

Single-click should become:

```text
study_set = resolve(intent="preview_only")
render right panel from study_set
do not enqueue full image download
```

This preserves the current select-vs-open behavior while removing duplicate
study-set logic.

### Phase 4: Use the service for already-open refresh

The existing tab focus branch should call:

```text
resolve(intent="refresh_open_viewer", force_refresh=True)
ViewerStudySetBridge.apply(existing_widget, study_set)
DownloadPlanner.enqueue_missing(study_set)
```

It should not fetch only the current study's series.

### Phase 5: Use the service for resync/manual refresh

Resync should stop being a separate authority and become a caller of the service.

It can keep:

- throttling;
- content version gate;
- mode policy;
- disk-aware sync;
- forced/manual override.

But the output should be a new `PatientStudySet`, not just a right-panel refresh.

### Phase 6: Use the service for plus-button and manual download

Plus-button should render from `PatientStudySet`.

Manual download should use a generated `DownloadPlan` rather than mutating
selected table dicts independently.

### Phase 7: Patient identity model enhancement

After study-set unification, improve patient identity:

- add `issuer_of_patient_id` where available;
- add source namespace;
- add optional `patient_identity_pk` or master-person table;
- add patient alias/link table;
- never auto-merge Patient IDs without explicit policy.

This is larger and should not block the pipeline unification.

## 14. Required Regression Tests

### 14.1 46630 first-open test

Shape:

```text
server row initially compact/incomplete
fresh patient-row lookup reveals imaging study + DOC study
double-click first open must create viewer with both studies
```

Assertions:

- open trace has either `all_studies=2` or `studyset_backfilled study_count=2`;
- `widget.set_server_series_info` receives both study UIDs;
- DOC series appears with its own `study_uid`;
- download plan includes DOC only when missing and intent allows.

### 14.2 Late study discovery updates open viewer

Shape:

```text
viewer opened with one study
background resolve discovers second study
```

Assertions:

- open viewer receives full updated `PatientStudySet`;
- `_is_multistudy_hint` becomes true;
- `_studies_series` has both study UIDs;
- grouped sidebar can render the new study without closing/reopening.

### 14.3 Single-click does not download

Shape:

```text
single-click multi-study patient with missing DOC study
```

Assertions:

- right panel shows DOC;
- no `DownloadEnqueued` unless legacy env flag is set;
- DB metadata may be saved.

### 14.4 Double-click downloads missing only

Shape:

```text
multi-study patient where primary is complete and DOC is missing
```

Assertions:

- primary study is not re-downloaded;
- DOC missing series is queued;
- completed DM state is reset only for stale terminal state.

### 14.5 Cross-patient stale fallback guard

Shape:

```text
right panel/table cache contains a study UID from another patient
```

Assertions:

- service excludes positively foreign study;
- no render;
- no download;
- warning trace emitted.

### 14.6 Series number collision test

Shape:

```text
two studies both have SeriesNumber=1
```

Assertions:

- viewer payload contains two distinct series by `(study_uid, series_uid)`;
- synthetic display keys stay inside viewer;
- DM receives original study UID and original series number.

### 14.7 Multi-Patient-ID future test

Shape:

```text
same real patient appears under different Patient IDs
```

Assertions for current architecture:

- no automatic merge;
- studies stay separated;
- optional alias/link policy is the only merge mechanism.

## 15. Suggested Service API

Example:

```python
class PatientStudySetService:
    async def resolve(self, request: PatientStudySetRequest) -> PatientStudySet:
        ...

    def build_viewer_payload(self, study_set: PatientStudySet) -> list[dict]:
        ...

    def build_thumbnail_payload(self, study_set: PatientStudySet) -> list[dict]:
        ...

    def build_download_plan(self, study_set: PatientStudySet) -> list[dict]:
        ...
```

Alternative split:

```text
PatientStudySetResolver
PatientStudySetValidator
StudySeriesMetadataResolver
StudySyncEvaluator
ViewerStudySetBridge
DownloadPlanBuilder
```

The important part is that all workflows use the same output object.

## 16. Suggested Event/Trace Tags

Add low-volume traces:

```text
PatientStudySetResolveStart
PatientStudySetResolveDone
PatientStudySetOwnerDrop
PatientStudySetLateGrowth
PatientStudySetViewerApplied
PatientStudySetDownloadPlan
```

Useful fields:

```text
patient_id
selected_study_uid
intent
source_mode
study_count
series_count
owner_drops
missing_series_count
partial_series_count
freshness
duration_ms
```

This will make future bugs easier to diagnose than reading six independent
trace streams.

## 17. Practical Implementation Notes

### 17.1 Do not big-bang rewrite

Use the service first as a facade over existing logic. Then migrate callers one
by one.

### 17.2 Keep UI work on the UI thread

The service can fetch network and DB data off-thread, but UI sinks must receive
the final object on the UI/event loop.

### 17.3 Do not block first paint

For open:

1. create viewer tab quickly;
2. display local selected study if available;
3. resolve full study set in background when needed;
4. apply full study set to viewer when ready.

The key improvement is that step 4 must be universal.

### 17.4 Preserve source-mode policy

The service must respect:

- Live server;
- offline cloud;
- local database;
- import/CD;
- manual force refresh.

### 17.5 Keep defense-in-depth checks at sinks

Even after central validation, keep cheap guards at:

- Download Manager critical intent;
- viewer-to-DM handoff;
- DB owner reassignment;
- grouped thumbnail render;
- download enqueue.

Centralization reduces normal mistakes; sink guards protect against future
callers and stale data.

## 18. Decision

The current architecture should not be considered complete for the "one
optimized path" requirement.

It is safe enough to say the project has many of the right building blocks, but
they are not yet assembled into a single authority. The next architectural move
should be to collapse patient/study/series resolution into one canonical service
and make every workflow a consumer of that service.

## 19. Priority Roadmap

### P0: Unify study-set resolution for double-click open

Goal:

- first open of patient 46630-like cases shows all studies, including DOC.

Deliverables:

- `PatientStudySetService.resolve(intent="open_viewer")`;
- viewer receives full study set;
- late study-set growth updates existing viewer;
- regression test for first-open DOC study.

### P1: Make single-click and already-open refresh consume the same study set

Goal:

- select/open/focus use the same answer for "which studies does this patient
  have?"

Deliverables:

- single-click preview uses service;
- existing tab refresh uses full study set;
- no download on preview;
- missing-only download on open/refresh.

### P2: Centralize download planning

Goal:

- open, resync, and manual download use one `DownloadPlan`.

Deliverables:

- `DownloadPlanBuilder`;
- missing/partial only;
- stale terminal-state reset rule in one place;
- test primary complete + DOC missing.

### P3: Centralize cache/DB/disk sync status

Goal:

- one per-study sync state used by UI, download, and resync.

Deliverables:

- service wraps `sync_manifest.evaluate_sync`;
- content version used consistently;
- DB-first metadata trust invalidation considered when study grows.

### P4: Improve patient identity model

Goal:

- support imported/multi-source patient identity safely.

Deliverables:

- issuer/source namespace;
- optional alias/master patient table;
- explicit merge/link policy;
- no automatic merge based on name alone.

## 20. Final Assessment

Current state:

```text
partially covered, significantly improved, not unified
```

Target state:

```text
one canonical PatientStudySet path
many action intents
one viewer payload
one download payload
one sync evaluation
many lightweight UI consumers
```

The best next work is not another local fix around a specific patient. The best
next work is the authority-collapse pass: make patient-study-set resolution a
first-class service and route all pipelines through it.

