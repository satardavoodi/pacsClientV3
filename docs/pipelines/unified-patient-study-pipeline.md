# Unified Patient-Study Pipeline — As-Built (2026-06-17)

Authoritative as-built record for the multi-study / 46630 unified-pipeline work
implemented 2026-06-17. Design background + evaluations:
`docs/reports/MULTI_STUDY_OPEN_VS_SELECT_DIVERGENCE_46630_2026-06-17.md`,
`docs/reports/UNIFIED_PIPELINE_EVALUATION_2026-06-17.md`,
`docs/reports/MULTI_STUDY_UNIFIED_PIPELINE_FULL_RECHECK_2026-06-17.md`,
`docs/reports/MULTI_STUDY_UNRESOLVED_RISK_CURRENT_RECHECK_2026-06-17.md`.

> Read this before editing the home-panel study-resolution / open / back-fill paths,
> `PacsClient/utils/patient_study_set.py`, or the viewer canonical series resolver.

## 1. What this fixes

The recurring multi-study failure: a patient with a second study (often a DICOMized
**DOC** study with its own `StudyInstanceUID`) — single-click showed it, but the
**double-click OPEN built a single-study tab and lost it**, returning only on reopen
(patient 46630). Root cause: the open path resolved the study set from a weaker/staler
source than single-click, and there was **no in-session path to push a late-discovered
study into the already-open viewer tab**, nor to download its files under open intent.

**Validated 2026-06-17 (live GUI, source build):** opening 46630 shows the grouped
viewer with **33 series** = Study 1 BREAST MR (32) + the DOC/secondary series
(100/101/102/103); the reception document renders. Trace
`patient_study_set_viewer_backfill new_studies=1` fires on open, non-blocking.

## 2. The shared authority (new, pure)

`PacsClient/utils/patient_study_set.py` — pure Python (stdlib only; **no Qt / VTK /
pydicom / numpy**). Keep it import-light so it stays the single shared authority and is
unit-testable in isolation.

- `PatientStudySetRequest` / `SeriesDescriptor` / `StudyDescriptor` / `PatientStudySet`
  — the immutable data contract (frozen dataclasses) + `Intent` / `Freshness` vocab.
- `merge_study_uids(sources, selected, owner_of, patient_id) -> (ordered, dropped)` —
  the canonical union + dedup + **selected-first** ordering + **cross-patient owner
  filter** (positively-foreign dropped, selected always kept, unknown-owner kept). This
  is the ONE place that logic lives.
- `diff_study_uids(previous, current)` — study UIDs in `current` not in `previous`
  (the study-set-growth detector).
- `resolve_study_uids(table_uids, rightpanel_uids, cache_uids, selected, owner_of,
  patient_id)` — the conditional-fallback gather + owner-filter (the
  `_resolve_patient_study_uids` logic extracted; fallbacks consulted only when the table
  source yields ≤1 study — legacy-equivalent).
- `build_download_payload(study_uid, patient_id, patient_name, study_info)` — the
  canonical Download Manager `add_downloads` dict (the **DownloadPlan seed**). Emits BOTH
  `description` and `study_description` (the DM queue reads `study_description`).
- `PatientStudySetService` — thin facade grouping the above as the named API to migrate
  callers to.

## 3. Implemented stages + flags (all default to the safe/correct behavior)

| Flag (env) | Default | Module | Effect |
|---|---|---|---|
| `AIPACS_PSS_MERGE_RESOLVE` | **on** | `_hp_patient_open.py` | `_resolve_patient_study_uids` routes its fallback-first ordering + cross-patient owner-guard **tail** through `merge_study_uids`. `=0` restores the byte-identical legacy tail (kill switch). The study-source **gather is unchanged**. |
| `AIPACS_OPEN_TAB_STUDYSET_BACKFILL` | **on** | `_hp_series.py` | When the deferred/single-click reconcile discovers the study set grew **and a viewer tab is open**, push the late study's series into the OPEN tab via the merge-aware `set_server_series_info`. `=0` disables. |
| `AIPACS_OPEN_TAB_LATE_DOWNLOAD` | **on** | `_hp_patient_open.py` | The back-fill also enqueues the late study's **missing/partial-only** series (disk-aware via `sync_manifest.evaluate_sync`) under open intent. `=0` disables (metadata still back-fills). |
| `AIPACS_PATIENT_STUDY_SET_SHADOW` | **off** | both home-panel | Observe-only diagnostic: logs `patient_study_set_open` (open resolve) and `patient_study_set_late_growth` (reconcile found more). Changes no behavior. |

Key methods:
- `_backfill_open_viewer_studyset` (`_hp_patient_open.py`) — finds the open tab by **any**
  study UID in the set (not just the primary), owner-validates each missing study, pushes
  metadata, then calls `_enqueue_missing_series_for_open_study`. Fire-and-forget
  (`_schedule_ui_coro`) so it never delays the grouped render.
- `_enqueue_missing_series_for_open_study` — open-intent, missing/partial-only download
  via `build_download_payload` + DM, with stale-terminal-state reset.
- `_vc_load.py::_resolve_canonical_series_identity` — now reads
  `entry.get('series_uid') or entry.get('series_instance_uid')`.
- Three enqueue sites (back-fill, resync, single-click reconcile) build their DM payload
  via `build_download_payload` (one schema).

## 4. Invariants that must NOT be broken (regression guards)

1. **`patient_study_set.py` stays pure** (stdlib only). It must remain importable and
   unit-testable without Qt — it is the shared authority and the wiring guard imports it.
2. **The pipeline terminates at `set_server_series_info`** (the merge-aware, metadata-only
   viewer sink, `_pw_thumbnails.py:86`). It must NEVER reach pixel loading, IPP/IOP
   geometry, slice ordering, orientation, VTK render windows, or MPR reslice — those are
   DOWNSTREAM and clinically protected. The back-fill's only viewer call is
   `set_server_series_info`.
3. **Legacy = kill switch, not deletion.** Every behavior change is gated by a default-on
   flag with the legacy path preserved (`AIPACS_PSS_MERGE_RESOLVE=0` restores the legacy
   owner-guard tail). Do not delete a legacy path until the new one is GUI-validated over
   time; flip the flag to revert instantly.
4. **Cross-patient isolation, centralized AND at the sinks.** `merge_study_uids` drops a
   positively-foreign study and keeps the selected + unknown-owner studies. The back-fill
   and the enqueue ALSO re-validate the server owner (defense-in-depth). Keep both — the
   central rule + the sink guards (`viewer_backfill_cross_patient_skip`,
   `reconcile_cross_patient_skip`, `resync_cross_patient_skip`).
5. **Open intent vs preview.** The back-fill/late-download run **only when a viewer tab is
   open** for the patient (open intent). A pure single-click preview with no tab must
   never download (preserved by the early return when no widget is found).
6. **Non-blocking.** The back-fill is fire-and-forget; it must not be `await`-ed before the
   grouped right-panel render (that re-introduces an open-latency stall).
7. **No unnecessary duplicate path.** Callers were *consolidated* onto the shared
   authority (`merge_study_uids` / `build_download_payload` / the existing
   `set_server_series_info` sink), not forked. The ONLY net-new code path is the open-tab
   back-fill, which fills a real gap (late study → open viewer) rather than duplicating an
   existing path. Do not add a parallel resolver/payload/enqueue variant — extend the
   shared authority instead.
8. **The resolver GATHER is unchanged.** Only the owner-filter tail was routed through the
   authority (scope-test byte-equivalent). Converting the gather (table/right-panel/cache
   reading) to `resolve_study_uids` is DEFERRED — it is not unit-coverable for the Qt-table
   path and needs a live multi-study GUI pass.

## 5. Guard tests

- `tests/code/ui_services/test_patient_study_set.py` — contract + `merge_study_uids` +
  `diff_study_uids` + `resolve_study_uids` + `build_download_payload` (incl. the
  `study_description` key + the 46630 late-growth scenario).
- `tests/code/ui_services/test_open_tab_studyset_backfill.py` — back-fill push, no-tab
  no-op, already-complete no-op, foreign-skip, **secondary-UID tab lookup**, late-download
  enqueue, **no-download-when-no-open-tab**.
- `tests/code/ui_services/test_resolve_patient_study_uids_scope.py` — pins the resolver
  tail's cross-patient contract (proves the `merge_study_uids` routing is equivalent).
- `tests/code/ui_services/test_unified_pipeline_wiring.py` — **source-wiring guard**:
  fails if the flags / functions / caller routing are removed (catches a stale build or an
  accidental revert).
- `tests/code/download_manager/test_multistudy_identity_guards.py` — the `_vc_load`
  canonical identity wiring.

Run: `python -m pytest tests/code/ui_services tests/code/download_manager -q -p no:debugging`.

## 6. Validation status (2026-06-17)

- Unit: download_manager 199, ui_services 97 (1 skipped GUI walkthrough), network
  attachment 6, viewer 23, builder release-parity **14/14** — all green.
- Plugin mirrors: **389/389** (home-panel + utils + viewer files here are NOT
  plugin-mirrored; nothing to sync for them).
- **Live GUI (source build, monitor A):** 46630 list row shows modality "MR, DOC";
  double-click opens grouped 33 series (Study 1 BREAST 32 + DOC/secondary 100–103); the
  reception document renders. Back-fill trace fired; download path inert because the DOC
  was already complete on disk (`study_resync_check result=current_cv`).

## 7. NOT done — staged tail (do before the prior-study / National-ID feature)

These are architectural consolidation, not active bugs (the 46630 case is live-validated).
Each must be flag-gated + GUI-validated + no-regression:

1. Full `PatientStudySetService.resolve()` owning the study-source **gather** (convert the
   resolver gather + reconcile union + per-modality enumeration + manual download).
2. A typed `DownloadPlan` (missing/partial filtered at construction; priority/open-intent;
   consumed by open / back-fill / resync / manual download).
3. Late back-fill download routed through the open-priority API
   (`start_priority_download_immediately`) rather than `add_downloads`.
4. A local `PatientStudyCatalog` read model + `ViewerLoadPlan` + per-request `WorkflowMode`.
5. Explicit real-patient identity / alias model (never auto-merge Patient IDs).
6. **Drag-drop as a first-class view-intent through this pipeline** (see §8) — converge the
   drop's prime + coalesced download + progressive feed onto the same `DownloadPlan` /
   `PatientStudySetService` the open / back-fill paths use, instead of its own mini-workflow.

**Clinical guardrail for all of the above:** unification is a data-path / workflow-authority
change. Do NOT change VTK/MPR geometry, slice order, orientation, or clinically verified
rendering unless a separate confirmed clinical bug proves them wrong.

## 8. Drag-drop = a "view series" intent through this pipeline (2026-06-17)

A viewer drag-drop is, conceptually, the same thing the open / back-fill paths do — *make
a study/series present and visible* — so it belongs **inside** this pipeline rather than as a
parallel priority/download path. The slow/unstable-link thrash (a user re-dragging because
nothing appears, churning the single download slot until nothing completes) is the symptom of
it living outside. Root cause + as-built: `docs/reports/DRAGDROP_SLOW_INTERNET_PRIORITY_THRASH_2026-06-17.md`
(§6); history [[dragdrop-slow-internet-thrash-2026-06-17]]. The target shape:

> **one drop → one "view series X" intent → { first-image prime, a coalesced
> `DownloadPlan` (open-intent + first-image priority), a progressive feed, a live download
> notification }** — drained against the single slot, last-write-wins.

### Implemented (flag-gated, default on, legacy kill switch each)
- **First-image prime** — `socket_client.py::_first_image_prime_size` (plugin-mirrored): a
  freshly-dropped series fetches its first batch as ONE image so the progressive feed paints a
  slice in one round-trip, then restores the full adaptive batch size (bulk speed unchanged;
  resume/force-single untouched). `AIPACS_FIRST_IMAGE_PRIME`.
- **Global view-intent coalescing** — `_vc_load.py::_coalesce_dm_view_intent` +
  `_merge_drag_view_intent` (last-write-wins) routing the drop's `_notify_dm_viewed_series` +
  `_trigger_download_if_needed` (`_vc_switch.py`): rapid drops of different series/studies
  collapse to the FINAL target, so the one slot is not preempted/torn-down per drop. The view
  switch is NOT debounced — only the DM intent. `AIPACS_DRAGDROP_DEBOUNCE`.
- **Rich download notification** — the waiting spinner shows series identity ("MR · Series 4
  · T2 FLAIR"), "Downloading N of M · P%", a progress bar, speed/ETA/elapsed, and an inferred
  connection state ("Connecting…" → "Waiting for server…" → "Slow connection — still trying…").
  `_vc_progressive.py` (`_update_download_spinner_text` + pure formatters + `_begin_download_wait`
  + the `_dl_watchdog_tick` staleness watchdog, fed by `on_series_images_progress`) →
  `ViewportSpinner.set_loading_details` (`loading_spinner.py`, mirrored) → the minimal
  `AiPacsLoadingOverlay` (identity line + `QProgressBar` + detail line + `set_loading_details`).
  Removes the "is it stuck?" blank wait that triggers the re-drag. Isolated in try/except so it
  can never disturb the progressive-display pipeline. `AIPACS_DOWNLOAD_PROGRESS_TEXT`. Guards:
  `tests/code/viewer/test_download_progress_text.py`. (Future: exact retry counts from the DM —
  needs a cross-layer state signal; the staleness inference covers the confidence case for now.)

### Staged (need live slow-link validation before building)
- **Settle-then-switch cross-study preemption** — coalescing already cuts the *frequency* of
  preempts; the remaining cross-study teardown should prefer a batch-boundary
  `.critical_intent.json` yield over a subprocess kill (deeper DM-coordinator change).
- **Converge onto the shared authority** — the drop should build its download via
  `build_download_payload` / a typed `DownloadPlan` and resolve its study/series via
  `PatientStudySetService` (items §7.1–§7.3), so drag-drop, open, and back-fill share ONE
  resolver + ONE plan + ONE single-flight slot. This is where the drag-drop fix and the
  patient-study-set unification meet — do it with §7.2's `DownloadPlan`.

**Clinical guardrail:** the drag-drop work is download / priority / perception only. It must
stay above the metadata sink (`set_server_series_info`) — no VTK/MPR geometry, slice order,
orientation, or render change — exactly like the rest of this pipeline.
