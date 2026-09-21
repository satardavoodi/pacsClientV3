# AI-PACS Documentation ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ Index by Subsystem

## Canonical shared Unify route (2026-09-18)

**2026-09-20 first-viewer graphics-policy correction:** startup now primes the one
process graphics result consumed by both Fast and Advanced, preventing viewer creation
from rereading the runtime profile or reprobeing graphics on the Qt thread. Preference
save invalidates the snapshot and restart semantics remain unchanged. See the latest
OPT-60 sections in the master plan and UI-stall report; guard:
`test_viewer_gpu_boost.py`. Code/mirror gates pass; fresh-source KPI acceptance remains
open. This shared policy correction does not alter viewer-private decode/render logic.

**Eagle Eye lumbar saved model profile (2026-09-20):**
[Astra screening/diagnosis with independent Gemini anatomy/context](modules/EAGLE_EYE_LUMBAR_SAVED_MODEL_PROFILE_2026-09-20.md)
records company wire settings, override rules, packaging parity and acceptance
limits under OPT-55. This is a persisted candidate, not clinical validation.

For identity/catalog/thumbnail presentation, download/file/state coordination,
cancellation, shared invalidation and KPI work, start with the
[current U0-U5 execution ledger](plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md#current-execution-ledger---2026-09-18),
then the [optimization master plan](OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md#2026-09-18-canonical-unify-continuation-queue-and-evidence-baseline).
There is one active shared-trunk slice at a time. The UI-stall report stores dated
shared-path evidence, the crash audit stores native/shutdown evidence, and viewer-private
work stays in its viewer-owner report. Do not implement from an older staged plan or
create another roadmap when one of these records already owns the concern.

Current active gate: **U0 fresh source acceptance** of the ordered Local catalog owner
and completed-load handoff, including a normal-exit native check. Next allowed sequence:
U1 completion fact, U2 state authority, U3 invalidation bus, U4 path retirement, U5
installed/restart/stress closure.

**2026-09-19 patient-open admission correction:** before any thumbnail/catalog/viewer
work, `finalize_open_study_identity` now requires a non-empty owner-consistent Study UID;
blank Local primaries promote the first resolved study. `HomeTabService` reserves one of
the four patient-tab slots before constructing `PatientWidget`, so a rejected fifth tab
cannot start an orphan pipeline or trigger qasync re-entry under a modal warning. Start
with `pipelines/unified-patient-study-pipeline.md`, then
`pipelines/thumbnail-pipeline.md`; guards are `test_patient_study_set.py` and
`test_patient_open_admission.py`. Code gates pass; fresh-source acceptance is pending.

## Local thumbnail latency / metadata routing (2026-09-16)

**2026-09-17 ordered cold-reader ownership:** the intermediate fact-primer removed
duplicate positive probes but live catalogs still took 6.950-13.707 seconds. Home and
patient Local projections now use one ordered catalog resolver: series order is fixed,
only the current series' files use bounded worker I/O, and the warmer skips known
unverified directories. Indexed Local and Server fallback remain raw-warm. Start with
the newest OPT-58/60 section in the UI-stall report, then `thumbnail-pipeline.md`,
`test_series_file_warm.py`, `test_local_pixel_inventory_reuse.py` and
`test_local_open_inventory_owner.py`. Code gates pass; fresh-source KPI and visual
acceptance are pending. `AIPACS_LOCAL_ORDERED_INVENTORY=0` is the narrow rollback.

**2026-09-17 orphan-reconcile correction:** a live two-study Local open proved a
6.925 s Qt freeze in synchronous per-series `os.listdir`. Orphan safety remains, but
its filesystem/DB work is now owned by the existing patient/background workers;
healthy series use one known instance path and fall back to enumeration only on stale
evidence. Start with the latest OPT-58/60 section in the UI-stall report, then
`test_orphan_series_prune.py` and `test_local_open_inventory_owner.py`. Post-fix live
acceptance is pending; the Home worker now emits one PHI-free aggregate
`source=producer_index owner=home_local` marker per study for that gate.

**2026-09-17 producer-index extension:** new imports/downloads publish verified
pixel-object and display-frame totals into the existing metadata index after complete
destination/index success. Local Home/sidebar consumers use the summary only with
exact managed-directory revision and otherwise retain the full worker scan. Both worker
projections use one batch backfill; the scan revision is compared at commit to reject
concurrent directory changes. Geometry-index status remains independent. Start at
`pipelines/thumbnail-pipeline.md`, then the latest OPT-58/60 section in
`reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md`. Guards:
`test_local_catalog_producer.py`, `test_db_first_metadata_index.py`,
`test_local_thumbnail_stream.py`, and `test_local_offline_contract.py`.

**September 17 Local image-I/O correction:** the existing single-study Local
worker now prepares QImage with exact Study UID + storage folder key and carries it
through its bounded mailbox. GUI retains QPixmap/card ownership and placeholder,
identity, order, counts, grouped takeover and cancellation contracts. This removes
the confirmed per-card ThumbnailStore/disk read from the GUI drain without adding
a second renderer or crossing Viewer domains. Fail-before guard; 37 Local-stream
and 212 adjacent passes / 1 privilege skip; broader 29-file boundary passes 456
with the same skip. Fresh normal-source GUI/KPI is pending.
[Implementation and rollback](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-local-patient-stream-image-preparation-opt-58--opt-60).

**September 17 measured enumeration follow-up:** the same inventory service now
retains directory-entry type information instead of issuing a second classification
stat for every candidate; independent fresh version validation remains. Grouped
and single-study consumers retain their admission/identity contracts. 334 passes /
1 unavailable-symlink skip; fresh-source GUI pending. See the
[enumeration receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-local-enumeration-cost-correction-opt-58--opt-60)
and `test_local_inventory_enumeration.py`. Cache path/read timing is now separated;
the full grouped barrier and other GUI I/O are not claimed closed.

**September 17 ownership correction:** single-study Local opens no longer run a
second full inventory in Home setup or push its stale right-panel snapshot into
the patient stream. Grouped Local and Server routes are preserved. Four baseline
failures, ten new guards and 321 expanded passes; cold classification and grouped
catalog-first work are not closed. Fresh-source GUI is pending. See the
[OPT-58/60 receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-single-study-local-inventory-ownership-opt-58--opt-60)
and `tests/code/ui_services/test_local_open_inventory_owner.py`.

**Separate completed-load delivery defect (September 17):** hidden-tab full results
now publish as paired, identity-normalized data and replay only their original viewer
request on activation. This is not thumbnail PNG persistence or a download protocol
change. Advanced decoded-cache integrity is owned separately. See the
[coordinated OPT-35/60 receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-completed-load-tab-handoff-opt-35--opt-60)
and `test_inactive_load_result_handoff.py` (25 cases). Fresh source GUI remains pending;
do not use the old running process or quarantined tests as acceptance.

**September 17 follow-up:** source run 23:40:15 exposes Local full-inventory waits
of 6.570 / 27.004 seconds before grouped metadata. The same classifier now supports
positive-only, version-checked persisted facts under bounded central cache storage;
no source/DB/thumbnail-presence or viewer-domain change. First uncached scan still
required. 32 new guards, including fresh-process reuse; fresh-source GUI remains
open. [Evidence, safety contract and rollback](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-local-inventory-persistence-opt-58--opt-60).

**Bounded cached/grouped build:** fixed-size card/header reservations and detached
image/readiness preparation now feed the same card manager one card per GUI turn.
Exact startup count, identity and download state are preserved. See
[OPT-58/60 implementation](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-bounded-cached-sidebar-build-opt-58--opt-60)
and `test_sidebar_bounded_build.py`. Server-entry delivery shares this owner after
the existing count merge/persistence. Fresh source GUI is pending; Local full-inventory
admission, its verified stream and explicit compatibility paths remain separate.

**September 20 late-study follow-up:** the same bounded owner now supersedes an active
grouped generation when the ordered Study/Series topology grows and queues one follow-up
prefetch if the prior worker is still active. This prevents a successfully back-filled
study from being omitted by the earlier sidebar snapshot and reapplies disk-authoritative
ready borders during replacement. No parallel renderer or downloader was introduced.
Code gates: 125 focused Study-set/sidebar/state tests and 259 expanded
Local/Server/sidebar/identity/lifecycle tests passed; fresh-source GUI remains open.

**Download liveness, separate from thumbnail presentation:** registered prewarmed
download child remained suspended before receiving its job. Shared native
suspend/resume hooks are retired without changing Viewer scroll/render/decode or
DM pause/priority. See the [OPT-04 implementation receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-opt-04-download-liveness-independent-of-viewport-settling)
and `tests/code/download_manager/test_download_process_interaction_liveness.py`.
Code verified; fresh-source download/scroll-contention GUI is pending. Cross-owner
evidence and the independent spinner-test baseline failure are in the VTK report.

**20:51 live follow-up and header fix:** user confirms smoother loading; remaining
first Local grouped delay aligns with late complete metadata, not a proven warm-up-only
cause. Hidden/wrapped study headers now participate in pre-paint height reservation.
432 tests / 467 mirrors; fresh-source header GUI and late-study topology gates remain.
[KPI evidence and scope](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-2051-source-review-and-study-header-geometry-correction).

**Workstream routing:** see the [Unify/Viewer ownership and handoff contract](plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md#02-workstream-ownership-and-two-way-handoff-user-decision-2026-09-16).
Advanced/VTK evidence is recorded in its owner report; shared coordination and sidebar
evidence stays in the UI-stall report. The earlier mirror drift mentioned below is a
historical observation: [the handoff recheck](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#inbound-handoff-from-unify-2026-09-16)
now confirms 467 matching pairs. No Viewer fix was performed by Unify.

**Presentation follow-up:** shared card insertion commits layout before paint, totals
exclude headers, queued primary results cannot rebuild a grouped/retired sidebar,
explicit grouped-failure fallback remains, and Local terminal updates no longer move
cards. Mixed catalogs publish an ordered prefix. 428 focused passes; initial 466-pair
mirror pass, then one unrelated Advanced Viewer drift on final recheck;
fresh-source GUI and transient-window diagnosis remain open, alongside synchronous
grouped PNG/readiness cost. [Receipt and rollback](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-sidebar-presentation-boundary-correction-opt-58--opt-60).

**Large-number follow-up:** shared allocation now aliases raw numbers >=1,000,000;
mixed Local catalogs deliver safe canonical members early, and prepared startup does
not repeat a completed metadata-started inventory. 344 code passes / 466 mirrors;
fresh-source GUI pending. [Evidence and rollback](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-large-number-identity-correction-and-startup-deduplication).

**Local card delivery is now wired at single-study startup:** verified unique canonical
series can reach the existing card renderer before the whole inventory finishes, with
bounded worker/Qt delivery and retirement. Collision/legacy allocation and grouped
ownership remain conservative. Fresh-source live/KPI acceptance is pending; the earlier
Fast preparation primitive below remains dormant. See the
[Local delivery receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-local-incremental-card-delivery-opt-58--opt-60).

**Fast preparation primitive implemented, not activated:** worker-owned data
handoff plus optional prepared bridge input and scoped image-owned overlay snapshot;
37 synthetic guards, 335 focused passes, one existing xfail, three missing-fixture
skips and 466 matching mirrors. The initial presentation guard now includes real
annotations; ordinary refresh still uses the mtime-aware reader. Bounded request
scheduling and fresh-source KPI/live acceptance remain gates. See the
[implementation receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-fast-initial-display-preparation-primitive-opt-58--opt-60).

Fast startup lag is a separate boundary from catalog delivery. The
[pre-change dependency review](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-fast-initial-display-change-impact-review-opt-58--opt-60)
maps synchronous switch consumers, QObject/cache lifetime, cine/WL/geometry
contracts and matched KPI gates. Review-only: 186 baseline passes / one existing
quarantined xfail, no runtime change or new live acceptance.

Related VTK-domain work: [Advanced / Eagle Eye / Standard MPR / Advanced Analysis geometry
and performance review](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md).
Latest OPT-23/35 slice separates the preview's ready count from its known total and
corrects only orientation-diagnostic handedness/claims. Sixteen new guards; 257 expanded
passes / five existing xfails, 467 mirrors. Actual geometry and filter quality unchanged;
fresh source GUI and transform-aware geometry validation remain open.
OPT-23 loading-cover follow-up fixes native backdrop opacity, branded-overlay repaint
and stale hide callbacks; eight new cover/full-stack cases, 106 expanded passes,
15 opt-in GUI skips and one existing xfail. User confirms US color; real Advanced
drag/drop continuity and full-range scrolling remain the next live gate.
OPT-35 US compatibility correction adds a nonspatial Advanced display path, stale-affine
retirement, RGB mapper reset and MPR admission guards: 17 new cases, 245 expanded passes,
5 existing xfails and 466 matching mirrors. Live source acceptance remains pending; see
the [US correction receipt](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#us-correction-opt-35-code-verified-live-pending).
OPT-23 next-test preparation now adds one per-constructor Advanced phase-timing record;
257 expanded tests pass, 6 existing xfails, 466 mirrors match. Render/fit and geometry
behavior are preserved; fresh source-GUI timing is pending.
Source map, cache reproductions, geometry authority, existing optimizations and ordered
OPT-35/48/49/56 follow-ups. The authorized cache prerequisite fix now has eight new guards
and 398 expanded passes; source-GUI acceptance awaits a fresh launch. Geometry and feature
flags are unchanged. Automated results remain separate from live acceptance.

**Catalog-first prerequisite (OPT-60 / OPT-35):** stable patient-tab handles now
survive metadata subsets/late same-number series; foreign-study metadata never
fills a primary card before grouped projection. Fifteen new behavioral guards,
181 focused + 107 adjacent passes. Incremental rendering/count revision and live
acceptance remain pending. See the [architecture decision and dated receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-catalog-first-review-and-stable-handle-prerequisite-opt-60--opt-35)
and `tests/code/ui_services/test_series_metadata_incremental_identity.py`.

**Pixel-inventory follow-up:** fresh source still showed 31.8-second Local metadata
handoff. Keep the historical cine/non-pixel/UID classification and the two distinct
UI projections; share immutable per-file positive facts with bounded, version-checked
worker reuse and selective pydicom reads. 181 code passes / three missing clinical
fixture skips; matched warm helper counts agree, but new GUI timing is pending.
See `pipelines/thumbnail-pipeline.md`, `test_local_pixel_inventory_reuse.py` in the
test index and the [inventory follow-up](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-local-pixel-inventory-reuse-follow-up-opt-60--opt-58).

OPT-60 / OPT-58: `_hp_series.py` now selects Local DB metadata before invoking
the unnecessary completeness scan. This is not a completeness bypass for downloads.
77 focused passes and 465 matching mirrors; fresh-source GUI/timing gate OPEN.
Remaining preparation, per-card and patient-open scans are separate workstreams.
See the [Local follow-up](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-local-metadata-route-follow-up-opt-60--opt-58)
and `tests/code/ui_services/test_local_series_info_gate.py`.

## Current crash, Unify and KPI acceptance (2026-09-15)

**Shutdown admission/evidence slice implemented:** nested/concurrent shutdown no
longer reopens registration during the outer callback. Callback return and owner
activity completion are separate observations; consultation includes retired owners.
Finalization intent is logged before listener shutdown, not labelled complete.
105 focused passes / four build deselections, 465 mirrors match. Fresh-source exit
acceptance remains OPEN; no Qt/VTK reorder or original crash-cure claim. See the
fourth closure-audit follow-up and `architecture/workstation-lifecycle.md`.

**Native sink/reader migration implemented:** exclusive PID/session log files,
legacy coexistence, bounded multi-source diagnostic readers, and explicit redirection
of the unsafe raw GUI counter. 120 passes / four opt-in build deselections, 465 mirrors
match; fresh 22:05:08 source Home/capture smoke passed before the final header-order
hardening, which needs next-source verification. Shutdown owner completion and
crash prevention remain open. See the third closure-audit follow-up; older pending
consumer status below is historical, not the current contract.

**MCP health prerequisite corrected:** `assert_health` now checks a real cumulative
native-byte baseline and live process identity instead of discarding its result.
The external reader is bounded and fails closed; retrospective snapshot windows
remain explicitly inconclusive. 32 new guards / 93 adjacent passes and a short
read-only live diagnostic smoke. The raw in-app native reader and sink migration
remain open; no runtime crash closure. See the second follow-up in the closure audit.

**Diagnostic prerequisite corrected:** the offline native filter now associates
fault headers with following stacks and protects its source from output aliases.
20 new synthetic guards / 42 adjacent passes; no application runtime change.
The closure audit records the fail-before evidence and the pending coordinated
native-sink/consumer migration. Old filtered reports are not attribution authority.

[Closure audit](reports/CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md): 124 focused
passes, user-confirmed patient drag, unresolved exit completion/native attribution,
remaining identity/download acceptance, and the latest session-scoped stall costs.
This qualifies older pending-GUI and historical completion language below.

## Qt lifecycle / cloud consultation retirement (2026-09-15)

[Poller lifecycle receipt](reports/QT_POLLER_LIFECYCLE_2026-09-15.md) records the
bounded OPT-60 stop/callback/worker-ownership fix, 15 new Qt guards, 367 adjacent
passes and pending source GUI. It separates stop requests from application-wide
drain, documents the advisory-only lifecycle timeout, and retains native exit
faults, GUI DB work and cross-domain shutdown as explicit follow-ups.

## Home thumbnail explicit open (2026-09-14)

**September 17 Home image-I/O correction:** qasync image preparation now uses the
existing thumbnail source/batch services while preserving Home ordering, action
identity and atomic refresh. [Implementation, code tests and pending live gate](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-home-thumbnail-image-preparation-off-gui-opt-58--opt-60).

**September 15 follow-up:** [Qt signature import-race correction](reports/QT_SIGNATURE_IMPORT_RACE_2026-09-15.md)
records the version-gated startup adapter, separate exit-time native faults, split
thumbnail preparation timing, 72 focused passes and pending fresh-source GUI gate.

Latest bounded OPT-60 implementation: startup cache enumeration runs in the existing executor;
the exact prepared tuple feeds the same routing/render path, and GUI layout exists before the
await. Guard: `test_pipeline_thumbnail_preparation.py` (18 cases, including real Qt/qasync and
native deletion). Fresh source GUI and KPI recapture pending; other GUI I/O is not fixed by this.

**Current performance gate:** [Unify path cost/stall audit](reports/UNIFY_PATH_COST_AND_STALL_AUDIT_2026-09-14.md)
separates guarded lifecycle correctness from performance acceptance: the current source session
still has GUI thumbnail enumeration/availability I/O and status DB stalls. Read before the next
OPT-60 slice; includes reproducible synthetic cost and PID-scoped log probes. No runtime fix.

Latest OPT-60 card-effect slice: parented reusable Ready/hide timers and progress animation;
manager reset/dispose stops card effects without native reparenting/deletion. Guard:
`test_thumbnail_card_effect_lifetime.py` (14); 441 expanded passes / 1 existing skip, 462 mirror
pairs match. Live requires a fresh source launch; the 20:41 process predates this change.
The master plan and thumbnail pipeline correct the old cleanup's absent-attribute explanation.
Identity, counts, decoder and download authority/routing remain unchanged.

Current OPT-60 lifecycle slice: manager-owned generation-scoped timers cancel on reset/dispose;
terminal disposal releases bound callbacks/maps and rejects stale cards/updates. Patient exit
retires main/Advanced-panel managers independently; Home weakly tracks both render schedules.
Native widget deletion and paint-atomic replacement stay unchanged. Guard:
`test_thumbnail_manager_retirement.py` (17); 424 adjacent passes / 1 existing skip, 462 mirrors
match. Fresh-source GUI blocked on bootstrap. Card-owned animations and full crash/stress
acceptance remain separate; see master-plan/provenance receipt for exact scope and rollback.

Current OPT-60 scheduling slice: bounded same-identity small refresh retains cards until the
paint-disabled replacement, while immediately retiring actions and preserving cross-identity/
large/progressive clearing. `test_home_small_refresh_swap.py` (16); 390 expanded passes / 1 existing
skip, 462 mirrors match. Default-on; source-live blocked. Master plan includes separate previous
import/native-crash status (17 import/overlay guards rechecked), not a blanket crash-closure claim.

Latest OPT-60 slice: Home clear releases the retired progressive-manager reference; action
callbacks weakly reference the panel and reject native-deleted/retired owners before queueing
and delivery. Guard `test_home_render_owner_lifetime.py` (10); 374 expanded passes / 1 existing
skip; fresh-source live pending. This is not full generic manager disposal. See master/provenance.

Newest OPT-60 slice: patient-owned QObject relay replaces capturing priority/download-completion
closures; disposal precedes explicit teardown and native deletion disconnects the receiver.
Routing/filter/key semantics are unchanged. Guard: `test_patient_tab_signal_lifetime.py` (16);
364 expanded passes / 1 existing GUI skip; 17:57 fresh-source native open/close/reopen PASS.
Real completion/priority live acceptance remains pending. Full manager disposal and
priority intent migration remain open. See master plan/provenance for scope and rollback.

Latest source receipt: 16:35 launch contains the search-retirement patch. Sampled empty Server
and Local results retire old previews; reselection and native new/reused exact-series open PASS.
Pins/advanced overlap/Offline Cloud remain live-unverified. See OPT-60 and provenance for scoped
logs and remaining work; older blanket launch-pending wording below is historical.

Latest follow-up: `HomeSearchService._clear_search_results` retires orphaned Home selection and
preview at all service clear sites, protects selected pins/pending row remapping, and rejects
stale advanced-search clears. Cancellation-safe thumbnail cleanup respects task ownership.
18 new guards (`test_home_search_preview_retirement.py`); 302 adjacent passes; 462 mirrors match.
Code-fixed only: a fresh source launch/live matrix remains required. This supersedes the open
caller-gap implementation status in the historical receipt below, not its live evidence.

Latest independent OPT-60 slice: clear-owned queued-render retirement and Qt-context callback
lifetime. Sixteen new guards; 197 adjacent passes. The 15:39 source sample passes replacement
and exact-series open; empty server search still retains the old preview (action guard holds).
That caller-side gap, full manager disposal and native drag remain open. See the receipt below.

Current MCP selection prerequisite: the two Home adapters now select a unique current Qt result
and share the normal debounce path instead of resolving stale cache metadata and bypassing row
selection. Code-verified and source-live verified in the 15:15 session for a two-study sample:
new/reused tab, exact-series output, invalid-ID rejection and wheel navigation. Native drag and
the extended matrix remain open. Guards: `test_home_selection_fidelity.py`.

See the current
[thumbnail/priority provenance receipt](plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md)
and [thumbnail pipeline](pipelines/thumbnail-pipeline.md). Double-click, shared cache identity,
standard async patient open and GUI-owned placement lifetime; the exercised two-study server
sample is user-confirmed and log-corroborated. Shared-normalizer semantic coalescing now guards
same-path count/description refresh without I/O. Final header/refresh and extended source-live
acceptance remain pending; Home drag/priority, disposal and later UID-cache phases remain open.

## Eagle Eye dataset templates and cases (2026-09-13)

[Native collection creation, editable templates and per-study forms](modules/EAGLE_EYE_DATASET_TEMPLATES_AND_CASES_2026-09-13.md):
modality/anatomy catalog, lumbar preset, optional/required custom fields, stable
template versions, duplicate-safe enrollment, searchable case lists and transactional
history. Form completion remains separate from image-reference training approval.

## Viewer Configuration storage cleanup (2026-09-12)

[Safety, Qt ownership, retention semantics and measured sizing performance](reports/STORAGE_CLEANUP_SAFETY_AND_PERFORMANCE_2026-09-12.md):
canonical manager/UI boundary, fail-closed deletion, Imported On retention, activity
coordination, worker lifecycle, regression guards, benchmark, rollback and source live gate.

## Eagle Eye workspace-first entry (2026-09-11)

[Workspace entry, explicit functions and Brain popup](modules/EAGLE_EYE_WORKSPACE_ENTRY_2026-09-11.md):
toolbar/sidebar navigation, named function selection, preserved native workers,
independent imaging, source-owned Legion ROI, lifecycle guards and deferred blocking work.
The 2026-09-12 presentation amendment covers the primary function action,
nonduplicated Imaging toolbar titles and removal of Patient navigation from this workspace.

## EchoMind restart and native MONAI input staging (2026-09-11)

[Restart receipt and complete Linux input validation](echomind/ECHOMIND_RESTART_AND_INPUT_STAGING_2026-09-11.md):
47-second restoration, 291 staged cases, 1,885 loaded inputs and 49,001 native planes.
Clinical training remains pending image-reference labels.

## Lumbar reference workbench (2026-09-11)

[Report-assisted form population](reports/LUMBAR_REPORT_PREFILL_2026-09-11.md):
722 proposed fields for 261 cases, source excerpts, unresolved report details,
preserved human edits and selective confirmation. All 291 case records verified.

[Local paired-image annotation and reviewed MONAI export](reports/LUMBAR_REFERENCE_WORKBENCH_2026-09-11.md):
loopback review for 291 cases, native evidence provenance, frozen patient partitions,
and a tested export path. Clinical image-reference review remains pending.

## EchoMind runtime and isolated training environment (2026-09-11)

[Verified endpoint repair, isolated environment and stop/test/restore](echomind/ECHOMIND_RUNTIME_AND_TRAINING_ENV_2026-09-11.md):
health/status ok, chat closure repaired, training dependencies isolated and synthetic
full-backbone optimizer/checkpoint checks passed. Reviewed patient labels remain pending.

## Lumbar regional input preparation (2026-09-11)

[Candidate packets and review-to-training export](reports/LUMBAR_REGIONAL_INPUT_PREPARATION_2026-09-11.md):
291 cases, 1,885 native candidate packets, 5,859 verified volumes and the remaining
anatomical/reference review requirements. No clinical training started.

## Lumbar training dataset readiness (2026-09-10)

[Current audit and preparation blockers](reports/LUMBAR_TRAINING_READINESS_2026-09-10.md):
292 packages passed declared-file integrity checks; regional packets and reviewed
targets remain incomplete. Includes the 12-case annotation queue and actual GPU
worker preflight rejection. No diagnostic training was started.

## EchoMind A100 maintenance / MONAI capacity (2026-09-10)

[Verified stop, test and restoration runbook](echomind/ECHOMIND_GPU_MAINTENANCE_2026-09-10.md):
Linux GPU ownership, local controls, restart recovery, preserved baseline health,
and full-backbone synthetic training-memory measurements. EchoMind was restored;
this is not diagnostic training or MON-AI dashboard integration.

## Printing / Filming maintenance (2026-09-09)

Runtime: `modules/printing`; launcher: `home_panel/_hp_modules.py::open_printing_module`.
Contract: [`modules/PRINTING_WORKFLOW_MAINTENANCE_2026-09-09.md`](modules/PRINTING_WORKFLOW_MAINTENANCE_2026-09-09.md).
Guards: `tests/code/printing/test_printing_workflow.py` and `test_printer_transport.py`.
Each preview belongs to one study; both printers consume the composed current page. DICOM network work runs outside the GUI thread. Physical output and complete-document printing are separate contracts.


## Eagle Eye spatial input pilot (2026-09-08)

[Spatial packet experiment](reports/EAGLE_EYE_SPATIAL_PACKET_EXPERIMENT_2026-09-08.md):
complete native groups, physical spacing, bidirectional plane locators and a
matched Gemini evaluation. Independent benchmark; not a live runtime default.


## Eagle Eye Gemini company route (2026-09-08)

[Current Gemini profile](reports/EAGLE_EYE_GEMINI_COMPANY_ROUTE_2026-09-08.md):
live GapGPT availability, synthetic capability limits, all-stage Pro defaults,
inherited sampling, runtime overrides and validation boundaries.


When you're about to touch a subsystem, this index tells you which docs to read first. Most subsystems have an "as-built" plan that codifies invariants; the catalog row tells you which guard test enforces them at runtime.

---

## Master indexes

- **[Eagle Eye Brain UI and maintenance](modules/EAGLE_EYE_BRAIN_UI_AND_MAINTENANCE.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ result card, anatomical PDF, background export and client acceptance boundaries.

- **[Eagle Eye development contract](modules/EAGLE_EYE_DEVELOPMENT_CONTRACT.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ common ownership and installer rules for Brain, Lumbar and future anatomy features.

- **[Eagle Eye Brain delivery](modules/EAGLE_EYE_BRAIN_CUSTOMER_DELIVERY.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ Brain/Lumbar ownership, portable assets, edition packaging and customer acceptance.
- **[Eagle Eye Brain active reference](modules/EAGLE_EYE_BRAIN_REFERENCE_SETUP.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ volBrain-only policy, scientific source, interval calculation and retired adapters.

- **[Release and build documentation hub](release-and-build/README.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ route to Git publication, the six-installer coordinator, backend details, output ownership, and release evidence.
- **[Canonical build and installer runbook](../BUILD.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ single human/AI entry point, safe fast lanes, official six-file isolated command, exact output folders, expected sizes, content checks, recovery constraints, and release blockers.
- **[3.6.6 build record](releases/VERSION_3.6.6_BUILD.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ current synchronized-source Python/Nuitka candidate, Standard/Eagle Eye/ARM-emulated editions, artifact identity and remaining installation gates.
- **[3.6.5 local build matrix](releases/VERSION_3.6.5_BUILD.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ previous measured Python/Nuitka baseline and historical recovery evidence.
- **[Pre-development system map (2026-08-27)](architecture/PRE_DEVELOPMENT_SYSTEM_MAP_2026-08-27.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ verified startup, subsystem connections, data/network boundaries, packaging flow, skills, MCPs, and the pre-code gate
- **[Codex repository readiness (2026-08-27)](reports/CODEX_REPOSITORY_READINESS_2026-08-27.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ verified environment, test baseline, security blockers, and development order
- **[Audit overview (2026-05-28)](AUDIT_2026-05-28_OVERVIEW.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ every stage report linked
- **[Regression catalog](plans/architecture/REGRESSION_CATALOG.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ every fix + its guard test (56 rows)
- **[Test inventory](../tests/INDEX_BY_GUARD.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ every guard test and what it protects
- **[For future agents](for-future-agents/README.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ onboarding for AI agents working in this repo
- **[Cloud decision ledger](for-future-agents/CLOUD_DECISION_LEDGER.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ PHI-safe, reconciled Cloud/recovery rationale with current-code status and superseded-material rules
- **[UI stall evidence and guarded fixes (2026-09-02)](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ corrected log interpretation, guarded fixes, Rev 3 partial live verification, unresolved server-row scan and visit-persistence defects, download-completion evidence gate, and separate MPR workstream
- **[Open findings (2026-08-16)](reports/OPEN_FINDINGS_2026-08-16.md)** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ diagnosed but deliberately NOT fixed. ط·آ¢ط¢آ§1 (pixel cache) has since been resolved; **ط·آ¢ط¢آ§2, the ~4-5.5 s MPR activation stall, is still open** and is the app's largest remaining freeze. Read it before touching MPR activation.

---

## Subsystems

MedGemma diagnosis input investigation (no runtime change):
[`MEDGEMMA_GROUPED_DIAGNOSIS_DESIGN_2026-09-07.md`](reports/MEDGEMMA_GROUPED_DIAGNOSIS_DESIGN_2026-09-07.md).
Separate-image transport, immutable parent groups versus anatomical eligibility,
task-specific axial/sagittal packets, compact prompts and controlled evaluation.

Eagle Eye side and neural-coverage contract:
[`EAGLE_EYE_NEURAL_COVERAGE_2026-09-05.md`](reports/EAGLE_EYE_NEURAL_COVERAGE_2026-09-05.md).
Canonical axial patient-side instructions, DICOM sagittal side correction, mandatory
seven-compartment per-level audit, abnormal-to-diagnosis handoff, and actual-card headers.

### EchoMind (reporting prompts, region gating, chat metadata)

Eagle Eye extended-coverage fix:
[`EAGLE_EYE_EXTENDED_COVERAGE_2026-09-05.md`](reports/EAGLE_EYE_EXTENDED_COVERAGE_2026-09-05.md).
Anatomy mapping can retain extra levels as explicit context without shifting lumbar
labels or extending lumbar diagnostic claims; canonical MRI architecture is updated.

Provider-routing incident and current contract:
[`ECHOMIND_EXPLICIT_PROVIDER_SELECTION_2026-09-05.md`](reports/ECHOMIND_EXPLICIT_PROVIDER_SELECTION_2026-09-05.md).
Company is the default; direct mode requires an explicit saved choice, key, endpoint,
and explicit Eagle Eye model choices. Guard: `test_explicit_provider_selection.py`.

Demo-center activation incident and current contract:
[`ECHOMIND_DEMO_CENTER_ACTIVATION_2026-09-10.md`](reports/ECHOMIND_DEMO_CENTER_ACTIVATION_2026-09-10.md).
The protected TEST record is the owner-approved end-user demo and is available by
default; restricted deployments have an explicit opt-out. No credential is stored in
the report or guard fixtures.

| Doc | What's in it |
|---|---|
| **[`echomind/README.md`](echomind/README.md)** | **Start here.** Index, the one-page mental model, and the six invariants. |
| [`echomind/01-architecture.md`](echomind/01-architecture.md) | Module map, the three backends, and what every workflow calls. |
| [`echomind/02-prompt-architecture.md`](echomind/02-prompt-architecture.md) | The nine prompt slots, what is shared vs gated, the load-bearing rules. |
| [`echomind/03-region-gating.md`](echomind/03-region-gating.md) | What a gate is, what selects it, multi-region selection. |
| [`echomind/04-chat-metadata.md`](echomind/04-chat-metadata.md) | Where every field comes from, the three layers, storage, edits. |
| [`echomind/05-mobile-parity.md`](echomind/05-mobile-parity.md) | What Android and iOS must reproduce byte-for-byte. |
| [`echomind/06-extending.md`](echomind/06-extending.md) | Adding a modality, region, subtype, lexicon or rule. |
| [`pipelines/echomind-reporting-prompts.md`](pipelines/echomind-reporting-prompts.md) | Per-modality prompt bodies and the preservation rule. Partly superseded - see `echomind/README.md`. |

**Guard tests:**
- `tests/code/echomind/test_turbo_template.py` - 103 guards on the template, the region packages and the gate
- `tests/code/echomind/test_turbo_prompt_seam.py` - the Turbo/Send seam
- `tests/code/echomind/test_credential_obfuscation.py` - packaged center/provider credential confidentiality, protected demo availability, and fail-closed Company Server 3 authorization
- `tests/code/echomind/test_entitlement.py` - demo default/opt-out behavior, paying-center isolation, legacy-flag compatibility, and backend entitlement chokepoints
- `tests/code/echomind/test_metadata_detection.py`, `test_metadata_card.py`, `test_reception_prefetch.py`

### Medical Report Editor (Reception Data tab)

| Doc | What's in it |
|---|---|
| **[`reports/REPORT_IMAGE_INSERT_2026-08-18.md`](reports/REPORT_IMAGE_INSERT_2026-08-18.md)** | **Read before touching report content or the upload path.** How a captured viewer image gets into the report and survives `toHtml` -> normaliser -> `setHtml` -> render/print; why images are embedded and downscaled rather than linked; the measured payload numbers; and the reversed-cursor-selection bug that every AST guard missed. |
| [`reports/REPORT_SYNC_ECHOMIND_EDITOR_RECEPTION_AUDIT_2026-07-15.md`](reports/REPORT_SYNC_ECHOMIND_EDITOR_RECEPTION_AUDIT_2026-07-15.md) | How the editor, EchoMind and the reception server stay in sync, and what the server-side HTML actually keeps. |

**Invariants:**

- The editing surface is a **Qt rich-text `QTextEdit`**, not a web view. Only the HTML-4 subset Qt understands round-trips; anything that needs real CSS will be silently lost.
- **Styling must be inline.** `prepare_report_html_for_server()` strips `<style>`, `<script>` and document chrome on upload, so a class or a stylesheet rule does not reach the server. Image sizing therefore lives on the `QTextImageFormat` (Qt emits `<img width= height=>` attributes), never in CSS.
- **`<img>` must stay out of `_DIR_BLOCK_TAGS`.** If it is ever added, an embedded key image silently disappears from the copy the referring doctor opens while the author's copy still shows it.
- **Report images travel as bytes, not paths.** The report is uploaded as one JSON field; a `file:///` src renders only on the machine that wrote it.
- **Per-image size is capped** (~1000 px / JPEG q88, 1.5 MB hard ceiling). There is no per-report cap ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ a report with many images can still grow past what the endpoint likes.

**Guard tests:**
- `tests/code/reporting/test_report_image_insert.py` (47) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ insert, resize, and the full save/upload/reopen round-trip
- `tests/code/reporting/test_server_report_html.py` (19) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ the upload normaliser itself (RTL/LTR per block, inline-style preservation, idempotency)

### Viewer (multi-study, sidebar, drag-drop)

**2026-09-14 Home click cutover:** `SeriesActionIdentity` in the existing pure
identity module, the common right-panel card factory, and `HomeTabService` route
clicks to uniquely matching already-open tabs by both UIDs. The destination retains
its own key/path authority. A token cancels stale render callbacks; the signature
includes that same action identity. Guards: `test_home_series_action.py` (22),
upgraded behavioral Windows input-dispatch tests, metadata/collision/Local/SeriesRef
neighbors (238 passed) and one stateful test. Full Home drag/retry, auto-open,
visual semantic refresh, lifecycle and live/installed acceptance remain separate.

**2026-09-14 Home card metadata prerequisite:** the existing common extraction now
retains supplied UID/path/display identity and frame counts for both render schedules.
`tests/code/ui_services/test_right_panel_metadata_contract.py` includes real-method
and real-Qt fail-before guards; focused selection: 205 passed. The provenance record
also qualifies today's partial source-run evidence, remaining UID rejection events,
download-row misses and the current pre-deferred-clear discrepancy. Action routing,
semantic refresh and full live/installed acceptance are not complete.

**2026-09-14 OPT-35 projection extraction:** patient-tab slot/key/path construction delegates
to `PacsClient/utils/series_identity.py::build_multistudy_series_projection`. The same 14
historical compatibility cases pass before and after extraction; final focused selection is
171 passed plus one stateful property test against the production helper. See
`MULTI_STUDY_SINGLE_TAB_PLAN.md` and the provenance record below. Full action routing and
live/installed acceptance remain pending.

**2026-09-14 OPT-60 prerequisite:** Home Local display-key allocation is repaired and
behaviorally guarded by `tests/code/ui_services/test_home_local_thumbnail_projection.py`.
The focused selection passes 120 tests. The provenance document below records the exact
scope; right-panel action routing, lifecycle and source-live validation remain pending.

| Doc | What's in it |
|---|---|
| **[`MULTI_STUDY_SINGLE_TAB_PLAN.md`](MULTI_STUDY_SINGLE_TAB_PLAN.md)** | **Required reading before editing the viewer.** Offset-key invariants, `_render_multistudy_grouped` behavior, server-info dict shape. |
| [`AUDIT_STAGE_5_2026-05-28.md`](plans/architecture/AUDIT_STAGE_5_2026-05-28.md) | Read-only `ViewerAdapter` live verification. |
| [`AUDIT_STAGE_6_2026-05-28.md`](plans/architecture/AUDIT_STAGE_6_2026-05-28.md) | Multi-study live workflow audit (239 series across 5+ studies). |
| [`pipelines/thumbnail-pipeline.md`](pipelines/thumbnail-pipeline.md) | THUMBNAIL_PATH conventions, memory-first vs disk fallback. |
| [`architecture/workstation-lifecycle.md`](architecture/workstation-lifecycle.md) | Current Qt/qasync ownership, Fast/Advanced/MPR separation, teardown order, and the diagnosed OPT-60 thumbnail-manager lifecycle gap. |
| **[`plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md`](plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md)** | **Read before consolidating thumbnail or priority paths.** Explains which local/server and immediate/progressive paths are intentional, how series identity evolved, why the direct-download cluster survived the Zeta migration, and the guarded retirement sequence. |
| [`reports/THUMBNAIL_HEAP_CRASH_AND_WINDOWS_SPAWN_FLASH_2026-09-01.md`](reports/THUMBNAIL_HEAP_CRASH_AND_WINDOWS_SPAWN_FLASH_2026-09-01.md) | Thumbnail-card native crash hardening, the Windows venv spawn/WinError-5 download correction, installed-build no-override policy, and the separate FAST Preview -> Complete ownership rule: never detach a visible embedded viewer before deferred deletion. |
| **[`reports/IMPORT_DUPLICATE_SERIES_NUMBER_IDENTITY_2026-08-30.md`](reports/IMPORT_DUPLICATE_SERIES_NUMBER_IDENTITY_2026-08-30.md)** | **Read before changing Import/Local series naming or displayability.** `SeriesInstanceUID` identity, raw `SeriesNumber`, collision-aware `folder_key`, digit-only `display_key`, exact `SeriesRef.storage_key`, pixel-object vs frame counts, mixed colour metadata recovery, multi-object cine expansion, and live validation. |
| **[`reports/LARGE_IMPORT_QT_REENTRANCY_CRASH_2026-09-05.md`](reports/LARGE_IMPORT_QT_REENTRANCY_CRASH_2026-09-05.md)** | Large Local import native-crash evidence and guarded fix: keep per-file DICOM/SQLite registration on the managed worker boundary, keep viewport-tree construction atomic, and preserve DICOM bytes, codec/counting rules, identity, storage paths, and installed-build parity. |
| **[`viewer/DICOM_FORMAT_COMPATIBILITY_OPERATING_GUIDE_2026-08-30.md`](viewer/DICOM_FORMAT_COMPATIBILITY_OPERATING_GUIDE_2026-08-30.md)** | **Read before diagnosing a new DICOM/IOD/codec/multiframe/waveform/ophthalmic compatibility case.** Separates preservation, classification, decoding, rendering, package parity, interoperability, and clinical verification. |
| **[`reports/ENHANCED_MR_RAW_DATA_MULTIFRAME_2026-09-01.md`](reports/ENHANCED_MR_RAW_DATA_MULTIFRAME_2026-09-01.md)** | Enhanced MR series mixed with same-Series-UID Raw Data objects: order-independent pixel-payload classification, full frame expansion, and truthful exclusion of metadata-only objects from the Fast viewport while preserving them on disk. |
| **[`reports/REFERENCE_LINE_ACTIVE_VIEWPORT_2026-08-16.md`](reports/REFERENCE_LINE_ACTIVE_VIEWPORT_2026-08-16.md)** | **Read before touching reference lines.** Two modes ship: single-source (default ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ the ACTIVE viewport is the source and stays clean) and bidirectional all-pairs (`AIPACS_REFERENCE_LINES_ALL_PAIRS=1`). Explains why the source overlay must be *cleared*, not skipped. |
| **[`reports/TEXT_ANNOTATION_INPUT_2026-08-18.md`](reports/TEXT_ANNOTATION_INPUT_2026-08-18.md)** | **Read before touching the annotation tools.** Why `ToolController` is Qt-free and how the Qt layer injects behaviour into it (`_pixel_data_fn`, `_pixel_spacing_fn`, `_text_prompt_fn`); why a tool press returning `False` is the "place nothing, stay armed" contract; why text annotations are single-line. |

**MPR lifecycle invariant (2026-08-19):** `_MprLayoutMixin.cleanup()` is the
only thing that releases an MPR viewer's volume, render windows and GPU
texture ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ and **a `closeEvent` hook cannot be relied on to reach it.** Qt does
not call `closeEvent` when a parent is destroyed or a widget is re-parented
away, which is how patient-tab close and layout rebuilds leaked (14 opens vs
6 teardowns across the logged sessions). Any code that drops, orphans or
replaces a widget which may host an MPR must call
`modules.mpr.zeta_mpr.mpr_viewer._mpr_lifecycle.release_mpr_children(widget,
reason=...)` **before** `setParent(None)` / `deleteLater()` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ after that the
GL context is gone and `ReleaseGraphicsResources()` cannot free the VRAM.
See [`reports/MPR_LIFECYCLE_RELEASE_2026-08-19.md`](reports/MPR_LIFECYCLE_RELEASE_2026-08-19.md).

**Oblique-MPR camera invariant (2026-08-23):** *in oblique mode the camera does
not select the displayed plane ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ an explicit `vtkPlane` on the mapper does.*
`_set_oblique_camera` runs `SliceFacesCameraOff()` + `SliceAtFocalPointOff()` and
sets `plane.SetOrigin(self.current_position)` (the crosshair centre) +
`plane.SetNormal(oblique_normal)`, **leaving the camera untouched** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ this is
**v1.09.Fix-E**, and repositioning the camera is what it deliberately reverted,
because it made the image pan under the cursor during rotation. **Do NOT "fix"
the camera focal point onto the crosshair.** The displayed oblique plane passes
through the crosshair by construction. Two corollaries that read like bugs and
are not: `_update_slice_positions` moves the camera along the **look axis only**
in *both* modes; and `mpr_diagnostic_validator.py` (header `Version: 2026-02-17`)
still measures the *camera's* plane, so its `focal_at_crosshair`,
`plane_containment` and `parallel_scale` checks fire on every oblique update
without anything being wrong. Until 2026-08-23 Fix-E was recorded only in a
source docstring, and a stability review recommended reverting it. See
[`plans/architecture/MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md`](plans/architecture/MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md)
and `pipelines/mpr-geometry-pipeline.md` ط·آ¢ط¢آ§10.9, ط·آ¢ط¢آ§10g, ط·آ¢ط¢آ§10h.

**Colour-decode invariant (2026-08-21):** any code path that reaches
`ds.pixel_array` for display must call
`modules.viewer.fast.dicom_color.normalize_ybr_subsampling(ds)` **before** the
decode and `ybr_samples_to_rgb(ds, arr)` **after** it. Order is the mechanism,
not a style choice: pydicom caches the decoded array, and for an uncompressed
dataset that claims `YBR_FULL_422` while shipping full-rate samples it truncates
the frame to two thirds and then resamples it, producing coloured static ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ this
cannot be repaired after the fact. Equally, multi-sample YBR data painted
straight into `Format_RGB888` renders with a heavy cyan cast. Both corrections
are needed; either alone leaves the image unreadable. See
[`plans/architecture/IMPORT_FREEZE_AND_YBR_COLOR_2026-08-21.md`](plans/architecture/IMPORT_FREEZE_AND_YBR_COLOR_2026-08-21.md).

**GUI-thread disk invariant (2026-08-22):** nothing on the patient-list or
settings path may walk the filesystem on the GUI thread. Three separate scanners
were found doing it the day after the streaming fix, and the pattern behind all
three is worth recognising: *chunking a blocking call does not make it
non-blocking*. The download-badge refresh was already split into 2-study chunks
and still froze the UI for 13.1 s per chunk, because the per-study cost was
seconds. Verdicts are now computed on a worker
(`patient_table_widget._compute_study_download_status`, dispatched via
`downloadStatusReady`) and applied on the GUI thread; `_peek_download_status`
reads the cache and **never computes**. Storage cleanup runs on a `QThread`
behind a busy dialog (`storage_cleanup_panel._CleanupWorker`). And
`count_subfolders_with_dicom` uses an early-exit `os.scandir` walk instead of
`Path.rglob('*')` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ measured **682.5 ms ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ 1.45 ms per study** cold, same verdict.
The 2026-09-02 live follow-up found the initial Server Search row path still
calling that faster scanner synchronously. Its derived status fields were unused,
so the residual call was removed; the existing generation-guarded Status worker
remains the sole initial-row disk-state owner. Explicit Local/Import state is
forwarded unchanged.
Prefer the two worker patterns already in `patient_table_widget`
(`statusFlagsReady`) and `storage_cleanup_panel` (`_FolderUsageWorker`) over a
new mechanism. See
[`plans/architecture/GUI_THREAD_DISK_PATHS_2026-08-22.md`](plans/architecture/GUI_THREAD_DISK_PATHS_2026-08-22.md).

**Hang-visibility invariant (2026-08-23):** *our stall probes cannot see a hang.
Do not read their silence as health.* Both are blind, for different reasons.
**F8 `[MAIN_THREAD_STALL]`** is a `QTimer` on the main thread ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ it measures the
gap when it *next fires*, so it only ever reports a stall that **ended**; a block
that runs until the process is killed leaves no record at all. **F11
`[MAIN_THREAD_STALL_TRACE]`** samples an in-progress block, but it is a **Python**
thread and needs the GIL for a single bytecode, so it cannot run while the main
thread sits inside a long C call ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ `gc.collect()`, a VTK destructor, a driver
call. On 2026-08-23 a workstation hung for 17 s during a patient close
(Windows `Application Hang 1002`) and the worst stall either probe recorded for
that session was 1 188 ms. Therefore: **any GUI-thread section that can block in
native code must be wrapped in
`PacsClient.utils.native_fault_log.hang_watchdog(label)`** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ it arms
`faulthandler.dump_traceback_later`, whose timer runs on a **native** thread and
fires while the GIL is held ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ **and must log a breadcrumb BEFORE it runs**, not
only after, so a step the process dies inside is identifiable by having a start
and no done (`_pw_lifecycle._close_step`). The watchdog keeps exactly one timer
process-wide and is deliberately non-reentrant; arm it at the outermost point
that matters. Related: the deferred patient-close `gc.collect()` was made
*later* in 2026-06-27, not *shorter* ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ it still runs on the GUI thread by design.
See
[`plans/architecture/CLOSE_PATH_HANG_VISIBILITY_2026-08-23.md`](plans/architecture/CLOSE_PATH_HANG_VISIBILITY_2026-08-23.md).

**Patient-list streaming invariant (2026-08-21):** the progressive patient-table
streamer must never resolve a row's on-disk path on the GUI thread. Rows are
resolved on a worker (`_resolve_display_paths`), and
`load_progressive(..., ready=)` makes the streamer *wait* for that worker rather
than fall back to an inline `stat`/`opendir`. The previous "the worker
comfortably outruns the streamer" assumption held warm (4,500ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ“6,000 rows/s vs
800) and failed catastrophically during an import (~325 ms/row ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ a 13.0 s
freeze). Anything that adds per-row work to the render path must be
`ready`-gated or budgeted the same way.

**Annotation-tool invariant:** `modules/viewer/tools/controller.py` must stay
**Qt-free** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ it holds the tool state machine and is imported by every headless
tool test. Anything needing a widget (a dialog, a colour picker, a font) is
INJECTED by `qt_viewer_bridge._init_tool_controller`, never imported here. A
press handler returns `True` only when it actually placed or changed something;
`False` means the caller must not repaint or deactivate the tool.

**Reference-line invariant:** the active viewport draws **no** line, and its overlay is explicitly cleared when it becomes active ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ skipping it silently leaves a stale line and looks like the fix never landed.

**Guard tests:**
- `tests/code/viewer/test_ybr_color_decode.py` (23) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ a mislabelled `YBR_FULL_422` frame is corrected before decode and converted to RGB after it; genuinely subsampled, compressed, 16-bit, RGB and monochrome data are all left byte-identical
- `tests/code/ui_services/test_list_stream_backpressure.py` (17) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ the list streamer waits for the path resolver instead of touching the disk, loses no rows, respects a per-batch time budget, and still makes progress if the resolver dies
- `tests/code/ui_services/test_gui_thread_disk_paths.py` (29) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ initial search rows never probe disk before paint, explicit caller state survives unchanged, download-badge refresh dispatches instead of walking, the DICOM scan never calls `rglob` yet returns the same verdict, and storage cleanup runs on a QThread
- `tests/code/viewer/test_text_annotation_input.py` (25) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ the Text tool asks what to write, cancel places nothing and leaves the tool armed, a bare controller keeps the legacy placeholder, and `controller.py` stays Qt-free
- `tests/code/viewer/test_reference_line_active_viewport.py` (17) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ the active viewport stays clean, the clean one follows the selection, and the env flag restores bidirectional
- `tests/code/viewer/test_reference_lines_all_pairs.py` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ the all-pairs engine itself (still fully covered; the flag default is pinned in both directions)
- `tests/code/echomind/test_viewer_adapter.py` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ 11 read-only adapter contract guards
- `tests/code/system/test_2026_05_27_regression_guards.py::test_change_series_signature_matches_base`

---

### Viewer cold-start cost (series load, pixel cache, import warm)

**The recurring lesson in this area: the cost is almost never parsing or thread count ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ it is FIRST TOUCH.** This machine runs two real-time AV engines, and cold/warm ratios of 7-100ط·آ£أ¢â‚¬â€‌ on the *same bytes* have been measured repeatedly. Benchmark warm vs cold before attributing a slow load to the code.

| Doc | What's in it |
|---|---|
| **[`reports/SERIES_HEADER_SCAN_COLD_LOAD_2026-08-08.md`](reports/SERIES_HEADER_SCAN_COLD_LOAD_2026-08-08.md)** | Patient 53417, ~15.7 s to get series 202 on screen. The switch-time probe was already header-only (`stop_before_pixels` + `specific_tags`): 40.5 ms/file cold vs 0.88 ms/file warm, and more threads cap at ~2.3ط·آ£أ¢â‚¬â€‌. Fix = a budgeted read-only pre-read at patient open (WU-1). Full per-file verification is unchanged. |
| [`reports/WEBENGINE_WARMUP_EVALUATION_2026-08-16.md`](reports/WEBENGINE_WARMUP_EVALUATION_2026-08-16.md) | ط·آ¢ط¢آ§8 documents the async pixel-cache init and the `viewer-import-warm` thread running off the GUI thread in a live run, plus the 7.6ط·آ£أ¢â‚¬â€‌ cold/warm read on identical bytes. |
| **[`reports/PIXEL_CACHE_PERSISTENCE_2026-08-16.md`](reports/PIXEL_CACHE_PERSISTENCE_2026-08-16.md)** | The L2 pixel cache now **survives shutdown** (it never did before: 18 wipes / `0 entries` indexed, measured). `clear_on_exit()` vs `clear()`, why persistence is bounded, the 2 GB / PHI-at-rest trade, and the one residual risk (a reused SOP UID with different pixels). |
| **[`reports/OPEN_FINDINGS_2026-08-16.md`](reports/OPEN_FINDINGS_2026-08-16.md)** | ط·آ¢ط¢آ§1 **resolved** (see above) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ kept as the record of how the decision was reached. ط·آ¢ط¢آ§2 still **OPEN**: MPR activation blocks the GUI thread ~4-5.5 s and the non-axial views are uninstrumented. |

**Invariants:**
- `DiskPixelCache.initialize()` stays **synchronous** for every direct caller; only `get_disk_pixel_cache()` passes `background=True`. An unindexed lookup is simply a cache miss, which is why this is safe.
- The index's **order is the LRU order** (`_evict_if_needed` pops the front). A background scan must re-sort by access time on merge, or the newest slices become the first evicted. This is also what makes persistence safe ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ without it the slice viewed last before closing would be first evicted next session.
- The shutdown path calls **`clear_on_exit()`, never `clear()`**. `clear()` must stay unconditional so an explicit user-initiated "clear cache" always clears; only the shutdown *policy* is configurable (`AIPACS_PIXEL_CACHE_CLEAR_ON_EXIT=1`).
- The import warm creates **no Qt objects** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ it is pure imports on a daemon thread.
- FAST viewer mode must **never** instantiate VTK render windows. Anything added to warm or cache the MPR path must not be reachable from FAST.

**Guard tests:**
- `tests/code/viewer/test_series_file_warm.py` (18) — budget caps, global and Local-fact kill switches, blank-path refusal, no duplicate concurrent warm, indexed/legacy selection and shared positive-fact reuse
- `tests/code/viewer/test_disk_pixel_cache_async_init.py` (10) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ incl. a threaded writer-vs-scan race and LRU order after merge
- `tests/code/viewer/test_viewer_import_warm.py` (8) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ fails if the warm ever touches a Qt object, or if the windowing path stops using `np.percentile`
- `tests/code/viewer/test_disk_pixel_cache_persistence.py` (20) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ the cache survives shutdown, the kill switch really wipes, `clear()` stays unconditional, and eviction still bounds a persisted cache

---

### CPU contention & process priority (Windows)

**The recurring lesson in this area: before optimising a path, check whether the main thread was RUNNING.** A stall sample that bottoms out in `run_forever` with nothing below it means the thread was inside the Qt event loop waiting to be scheduled ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ no amount of work removed from our handler changes that number.

| Doc | What's in it |
|---|---|
| **[`reports/STACKING_LAG_55387_2026-08-23.md`](reports/STACKING_LAG_55387_2026-08-23.md)** | Patient 55387 stacking lag (pid 90364). The stacking path is exonerated by its own instrumentation ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ `frame_total_ms` median **1.6 ms**, disk/decode/cache waits **0.0 at median and p90** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ while `ui_lag_max_ms` is 300 ms per drag. The decisive pair is **`event_p95_ms` 84.5 ms vs `handler_p95_ms` 9.0 ms**, and **45 of 66** sampled stall stacks bottom out in `run_forever`. Root cause on our side: the `[CPU_BUDGET]` priority boost had **never applied** (ctypes pseudo-handle truncation ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ `ERROR_INVALID_HANDLE`, 19 launches / 19 failures). |

**Invariants:**
- `GetCurrentProcess()` returns the pseudo-handle `(HANDLE)-1` == `0xFFFFFFFFFFFFFFFF`. **Any ctypes call that passes a Win32 HANDLE must declare `restype`/`argtypes` as `c_void_p`**, and must declare them **BEFORE** the handle is taken ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ a `restype` set after the call is a no-op. The default `c_int` silently truncates and the API fails with err 6. **There is a second, still-unfixed instance of this exact defect** at `modules/download_manager/workers/download_process_entry.py:149` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ see the open item below.
- **The default priority class is build-type dependent** (2026-08-23, by owner request): frozen/installed build ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ **HIGH** (deployed clinical workstation), source run ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ **ABOVE_NORMAL** (developer box also running an IDE/VM/compiler). Detected with `aipacs_runtime.is_frozen()`, never a bare `sys.frozen` check ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ that would report False on every Nuitka build, i.e. on exactly the machines the rule is for. `AIPACS_PRIORITY=normal|above_normal|high` overrides; `normal` is the kill switch.
- An unrecognised `AIPACS_PRIORITY` must fall back to **the machine's own default**, never a hard-coded class ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ otherwise a typo silently demotes a clinical workstation.
- A failing `is_frozen()` probe degrades to the **source** default. Never promote a machine to HIGH because a probe raised.

**Open item ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ the DM subprocess demotion has never applied.** `download_process_entry.py:149` calls `SetPriorityClass(GetCurrentProcess(), BELOW_NORMAL)` with no `restype`/`argtypes` **and does not check the return**, so it has always silently failed. That demotion is the codebase's stated mitigation for "HIGH starves disk I/O", and the same file's v2.3.7 comment reasons from the premise "the viewer (ABOVE_NORMAL) blocks waiting on a lock held by an IDLE-scheduled thread" ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ a premise that was false, because the viewer was at Normal too. **The intended priority separation has never existed at runtime.** Not fixed yet: the repo has MEASURED harm from widening this gap (`ui_lag_max` 412 ms vs 229 ms), and HIGH-vs-BELOW_NORMAL is wider still, so it needs its own measurement. Until then `high` is untested against heavy concurrent downloading.
- **Never delete the `[CPU_BUDGET] SetPriorityClass failed (err=%d)` warning.** That line, ignored for months, is the only reason the defect was ever found.
- The stall probe writes to **`viewer_diagnostics.log`, not `app.log`.** Searching only `app.log` returns ~2 lines per session and the wrong conclusion.
- Logging is **not** a GUI-thread cost: `diagnostic_logging.py` routes every file handler behind a `QueueHandler`/`QueueListener`. Rule it out by reading that file, not by assuming.

**Guard tests:**
- `tests/code/system/test_cpu_budget_priority_boost.py` (13) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ the three ctypes declarations, both ORDERING pins, the preserved diagnostics and kill switch, plus two behavioural Win32 probes that reproduce the truncation read-only via `GetPriorityClass`

**Analysis scripts:** `tools/analysis/oneoff/stack_lag_55387{,_detail}_2026_08_23.py`, `stall_trace_frames_90364_2026_08_23.py`

---

### Cardiac phase-contrast (flow) export ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ cvi42 compatibility

**The recurring lesson here: check what the OTHER tool actually does before blaming our side.** The leading hypothesis in this investigation was refuted by reading one DCMTK-produced DICOMDIR that cvi42 had already ingested.

| Doc | What's in it |
|---|---|
| **[`reports/FLOW_CVI42_55241_2026-08-24.md`](reports/FLOW_CVI42_55241_2026-08-24.md)** | Patient 55241 (SIEMENS Amira, syngo MR E11), flow series **45ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ“56** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ not 44ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ“49. cvi42 will not quantify flow on our export. **Cause NOT found.** Everything measurable is correct: CSA blocks intact with `FlowVenc=150`, `ImageType` P/MAG markers, phase pixels 0ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ“4094 rescaling to ط·آ¢ط¢آ±4092, MAG/P sharing geometry and trigger times, 1,570 files with 1,570 distinct SOP UIDs, DICOMDIR fully resolving. Includes a **retraction** of the DICOMDIR hypothesis. |
| **[`reports/FLOW_CVI42_SAME_STUDY_VM_COLLAPSE_2026-09-01.md`](reports/FLOW_CVI42_SAME_STUDY_VM_COLLAPSE_2026-09-01.md)** | **Same-study paired proof and guarded fix.** Server-served `ImageType` was a Python-list string with VM=1 in all 1,700 instances; 360/360 flow pixels and Siemens CSA blocks were intact. A single standard-VM normalization authority now protects socket ingestion and DICOMDIR/media export while preserving source files, UIDs, pixels, private elements, and transfer syntax. cvi42 live re-import remains pending. |

**Invariants and facts established:**
- Our CD export with anonymisation OFF and format "Original" is **pure passthrough** (`DicomPreparer.needs_processing` is False) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ exported files are byte-identical to stored ones. Do not look for export-stage damage in that configuration.
- `modules/dicom_media/dicomdir.py` builds with `pydicom.fileset.FileSet`, so SERIES records carry `Modality, SeriesInstanceUID, SeriesNumber`. **A real DCMTK `dcmmkdir` DICOMDIR carries exactly the same three** (verified against `OFFIS_DCMTK_363` output in cvi42's own store) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ our DICOMDIR is NOT deficient, and `SeriesDescription` is not expected in a SERIES record.
- Of 34 cvi42 study folders, **33 have no DICOMDIR and 1 does**. cvi42 ingests both shapes.
- Files leaving our server are stamped `PACS_SERVER_1.0` / `1.2.826.0.1.3680043.8.498.1` (the pydicom UID root): **the server re-encodes rather than storing scanner bytes verbatim.** The only VR casualty found is `(0051,1014)` ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ `UN`, 12 bytes, in all 240 flow files.
- Siemens E11 emits a **three-series** flow triplet (M / MAG / P) with the VENC encoded in `SequenceName` as `*fl2d1_v150in`; XA20 emits a different private layout (`(0021,xxxx)` SDS/SDI/SDR) and `MFSPLIT` in ImageType. **Do not diff an E11 study against an XA20 study and read the delta as loss.**

**Open ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ needed to close this:** the other PACS's export of **patient 55241 specifically**. A different patient on a different scanner generation cannot serve as a control.

---

### Loading overlay / viewport spinner ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ teardown races

**The recurring lesson: `QApplication.processEvents()` is not ط£آ¢أ¢â€ڑآ¬ط¥â€œpaint nowط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’, it is ط£آ¢أ¢â€ڑآ¬ط¥â€œrun arbitrary queued work nowط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’.** The crashes in this area came from calling it inside a series switch or a partially constructed viewport layout.

| Doc | What's in it |
|---|---|
| **[`reports/OVERLAY_REENTRANCY_CRASH_2026-08-26.md`](reports/OVERLAY_REENTRANCY_CRASH_2026-08-26.md)** | pid 217556 died at 13:40:25 with a native access violation, no `[SHUTDOWN-INITIATOR]`, no OS-level event. `show_overlay`'s double `processEvents()` re-entered the event loop mid-switch and started a **second series switch on top of the first**; the nested overlay was built against a viewport the outer switch was tearing down. app.log shows three `switch_start` for series 7 in one second and one `phase_summary`. Trigger: stack-scrolling during a switch. |
| **[`reports/LARGE_IMPORT_QT_REENTRANCY_CRASH_2026-09-05.md`](reports/LARGE_IMPORT_QT_REENTRANCY_CRASH_2026-09-05.md)** | A 2,890-object Local import blocked the GUI for 37.6 seconds during registration, then `apply_multi_viewer()` pumped queued work while its viewport tree was partial; Windows recorded a matching `Qt6Core.dll` `0xc0000005`. Registration now uses the existing worker boundary and layout construction is atomic. |

**Invariants:**
- **Never call `processEvents()` to force a paint.** `widget.repaint()` paints synchronously without running the event loop. Kill switch `AIPACS_OVERLAY_SYNC_PAINT=0` keeps the old path for comparison only.
- **Never call `processEvents()` between viewport creations.** QWidget/VTK construction stays on the GUI thread, but the layout mutation must remain atomic; optimize expensive preparation before construction.
- **`switch_series` must never run re-entrantly** on one container. The flag clears in a `finally` that covers the early `return False` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ a stuck flag turns a crash into a permanently dead pane. `AIPACS_SWITCH_REENTRANCY_GUARD=0`.
- The same-series no-op **cannot** be relied on to catch a duplicate switch: the first switch of the 08-26 crash carried an **empty `series_uid`**, so the identity comparison did not match.
- **Anything that touches an anchor/overlay across a teardown must check liveness first**, and `shiboken6` being unimportable must degrade to **alive**, never to dead. Guards exist at three sites now: `hide_overlay._start_fade` (2026-06-05), `_hp_layout._hide/_show_loading_overlay` (2026-06-15), `AiPacsLoadingOverlay.__init__` (2026-08-26). **Fixing one site does not fix the race** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ that is the whole history of this file.
- Diagnostic gap: faulthandler dumps in `native_fault.log` carry **no pid**, so attribution is by stack content. Worth stamping.

**Guard tests:**
- `tests/code/system/test_overlay_reentrancy_crash.py` (13) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ the cause, both defence-in-depth guards, and the prior-art anchor
- `tests/code/system/test_import_registration_layout_crash_guard.py` (4) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ off-thread import registration, preserved index/bytes/identity, and atomic layout construction
- `tests/code/test_loading_overlay_liveness_guard.py` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ the 2026-06-05/06-15 fade guards

---

### Download Manager (Zeta) + bulk download

**September 15 file-count/retry follow-up:**
[File-count gate and retry ownership](reports/DOWNLOAD_FILE_COUNT_GATE_2026-09-15.md)
records false success after incomplete batches, duplicate accounting and the
same-number retry-folder defect. 23 new guards; 217 focused/builder passes;
fresh GUI and full durable manifest proof remain pending.

**September 15 bounded transport follow-up:**
[Response framing/broadcast review](reports/DOWNLOAD_SOCKET_RESPONSE_REVIEW_2026-09-15.md)
records the client-side ten-notification failure, partial-prefix defect, reconnect
self-deadlock, Git provenance and narrowly scoped correction. 38 new wire guards,
189 adjacent passes and 5 builder passes; known encoding/payload baseline debt and
fresh-source GUI/completion-proof gates remain open. UI and scheduling unchanged.

| Doc | What's in it |
|---|---|
| **[`pipelines/download-pipeline.md`](pipelines/download-pipeline.md)** | **Current transport authority.** Socket worker/process flow, immutable study/series identity, Overall Progress, resume/completion evidence, and Windows spawn ownership. |
| **[`plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`](plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md)** | As-built review and fix plan; ط·آ¢ط¢آ§13 = applied vs outstanding; ط·آ¢ط¢آ§14 = patient-open stall; ط·آ¢ط¢آ§15 = socket/gRPC path map. |
| [`AUDIT_STAGE_4_2026-05-28.md`](plans/architecture/AUDIT_STAGE_4_2026-05-28.md) | Live bulk-download audit (35 patients in 8 s). |
| [`AUDIT_STAGE_4b_2026-05-28.md`](plans/architecture/AUDIT_STAGE_4b_2026-05-28.md) | DM controls (Pause / Cancel / Retry / Reset / priority dropdown). |

**Guard tests (in `tests/code/system/test_2026_05_27_regression_guards.py`):**
- `test_probe_uses_raw_send_request_not_helper` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ GetStudyInfo 6.8 s stall guard
- `test_probe_lock_is_module_level`, `test_probe_lock_is_used_in_get_series_info_from_server`
- `test_prefetch_uses_threadpool_executor`, `test_prefetch_has_no_sequential_loop`, `test_parallel_prefetch_is_faster_than_sequential`
- `tests/code/download_manager/test_overall_progress_accumulator.py` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ study-level Overall Progress stays monotonic across series/IPC delay, uses SeriesInstanceUID for duplicate numbers, accepts the downloader's authoritative one-time study total when the queue payload count is unknown/stale, and accounts complete-on-disk series without GUI-thread I/O or viewer fan-out.

---

### Internal assignment (INO) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ server-state snapshot

**The snapshot file is written under a process-global lock that the GUI thread also takes.** `get_state` is called per patient-list row while painting; anything that holds `_LOCK` for long freezes the worklist. Never add a per-row write to this store.

| Doc | What's in it |
|---|---|
| **[`reports/ASSIGNMENT_SNAPSHOT_BATCH_WRITE_2026-08-16.md`](reports/ASSIGNMENT_SNAPSHOT_BATCH_WRITE_2026-08-16.md)** | **Read before touching `ino_assignment_server_state` or `ino_assignment_refresh`.** The 10.79 s freeze: one full-file rewrite per reception, serialised against the GUI thread's per-row read. Measured write costs, why the fsync is now opt-in, and the four contracts that deliberately did NOT change. |
| [`reports/INTERNAL_ASSIGN_FALSE_ASSIGNED_REGRESSION_2026-07-15.md`](reports/INTERNAL_ASSIGN_FALSE_ASSIGNED_REGRESSION_2026-07-15.md) | Earlier assignment-state regression. |

**Invariants:**
- Writes are **batched**: `set_many()` for anything loop-shaped, `set_state()` only for a single user action. The write is O(all receptions), so a per-row write is O(Nط·آ¢ط¢آ²) over a refresh.
- `_merge_and_save` must `_load` **inside the same lock acquisition** as the save, or a concurrent single write is silently rolled back.
- `_load` must stay **lock-free** ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ the writer already holds `_LOCK`, and `threading.Lock` is not reentrant.
- `get_state` must **keep** taking `_LOCK` (the 2026-07-31 WinError-5 fix); the answer to contention is fewer writes, not an unlocked read.
- A failed fetch must never wipe a known assignment.

**Guard tests:**
- `tests/code/network/test_ino_state_batch_write.py` (28) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ one write per batch, the two write paths cannot drift, the fsync gate, and the refresh contracts that must not change
- `tests/code/network/test_ino_server_state_concurrency.py` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ the reader/writer `os.replace` failure and the per-writer temp name

---

### Web browser module + startup / engine warm-up

**September 15 user-initiated opening update (OPT-22):**
[Opening wait-status receipt](reports/WEBENGINE_OPEN_WAIT_STATUS_2026-09-15.md)
documents the observed 35.4-second first-open stall and a bounded header notice /
input guard. Preserve synchronous Home/OAuth/CommandBus returns, lazy import and
default-OFF warmup. `tests/code/web_browser/test_browser_launch_notice.py` has 12
real-Qt guards; 160 adjacent passes plus a mirror guard are code evidence only.
Native source GUI acceptance is pending; this does not eliminate the Qt block.

**Read this before touching `modules/web_browser/prewarm.py`.** Four live freezes came out of this one file (~17 s 2026-07-23, 39.7 s 2026-08-05, 19 s 2026-08-07, **72 s 2026-08-16**) and the lesson took all four to learn: *when* the Chromium construct runs was never the problem ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ its **cost is unbounded and cannot be capped**, because Qt requires it on the GUI thread and the call is atomic. Do not "improve the scheduling" here again.

| Doc | What's in it |
|---|---|
| **[`reports/FREEZE_72S_BROWSER_PREWARM_2026-08-16.md`](reports/FREEZE_72S_BROWSER_PREWARM_2026-08-16.md)** | **Start here.** The 72 s incident, why every scheduling guard behaved correctly, and why the answer was to make the pre-warm opt-in (IMP-4). |
| [`reports/PREWARM_DBLCLICK_FREEZE_2026-08-07.md`](reports/PREWARM_DBLCLICK_FREEZE_2026-08-07.md) | The 19 s double-click freeze ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ the input-recency veto (IMP-3). Explains why `_finish_watch` must keep the input filter installed. |
| [`reports/WEBENGINE_WARMUP_EVALUATION_2026-08-16.md`](reports/WEBENGINE_WARMUP_EVALUATION_2026-08-16.md) | Phase-by-phase cost of the engine boot (IMP-5): `defaultProfile()` is the 918 ms global init, `QWebEngineView()` is 0 ms. ط·آ¢ط¢آ§8 is the confirmed live run ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ 208 ms GUI block, 884 ms total. Chromium flags are measured and are NOT a lever. |
| [`reports/WEB_BROWSER_MODULE_FIXES_2026-06-27.md`](reports/WEB_BROWSER_MODULE_FIXES_2026-06-27.md) | Earlier module fixes. |

**Invariants:**
- The pre-warm is **opt-in**: `AIPACS_BROWSER_PREWARM=1` (a literal `"1"`), *and* the adaptive used-marker still gates on top.
- Warm the **default profile**, never a throwaway `QWebEngineView` + `setUrl` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ same benefit, ~24 % less GUI block, no render process held to be discarded.
- The off-thread file warm is **name-scoped** (`_WARM_DLL_HINTS`), not a blanket DLL sweep, and stays budget-capped.

**Guard tests:**
- `tests/code/web_browser/test_prewarm_recency_veto.py` (13) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ input filter survives the warm; construct re-checks recency
- `tests/code/web_browser/test_prewarm_idle_gate.py` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ default-profile warm + the DLL-name-scoped file warm
- `tests/code/system/test_browser_prewarm_idle_gate.py` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ opt-in default, marker gate on top, only a literal `"1"` enables it
- `tests/code/web_browser/test_prewarm_busy_veto.py`

---

### UI / Design system (V2, flag-gated) + viewer interaction

| Doc | What's in it |
|---|---|
| **[`design/V2_DESIGN_SYSTEM_AS_BUILT.md`](design/V2_DESIGN_SYSTEM_AS_BUILT.md)** | **Required reading before editing `v2_style.py`, `ui_variant.py`, toolbar/home styling.** Flag gating, apply-at-source rule, where each V2 style is applied, design-language invariants, how to extend. |
| [`design/DROPDOWN_SUBMENU_REVIEW.md`](design/DROPDOWN_SUBMENU_REVIEW.md) | Original dropdown/submenu review (rollout now complete). |
| [`design/VIEWER_TOOLBAR_INTERACTION_REVIEW.md`](design/VIEWER_TOOLBAR_INTERACTION_REVIEW.md) | Toolbar hover / dropdown attach / menu layout review. |
| **[`plans/performance/FAST_STACK_DRAG_PRESSURE_FIX_2026-05-30.md`](plans/performance/FAST_STACK_DRAG_PRESSURE_FIX_2026-05-30.md)** | Stack-drag main-thread stall fix: drag-pressure psutil sampler gated off by default (`AIPACS_FAST_STACK_PRESSURE`). Don't call psutil on the drag hot path. |
| **[`reports/THUMBNAIL_STRIP_AND_ACTIVE_STATE_2026-08-09.md`](reports/THUMBNAIL_STRIP_AND_ACTIVE_STATE_2026-08-09.md)** | **Required reading before touching the series thumbnail card.** The download bar / red active line share one bottom strip; `QLayout.addWidget()` RE-PARENTS and moves a widget to the TOP of the sibling stack, which is what buried the bar. Also the Aط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢Bط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢A active-state bug and `set_active_series()` as the single entry point. |
| [`reports/MAIN_FOOTER_BAR_REMOVAL_2026-08-10.md`](reports/MAIN_FOOTER_BAR_REMOVAL_2026-08-10.md) | The stray bar at the bottom of the main page ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ an empty Designer footer whose only visible output was its own chrome. Hidden, not deleted (`apply_theme` still styles it). Restore with `AIPACS_MAIN_FOOTER=1`. |

**Guard tests:**
- `tests/code/test_v2_style_scaffold.py` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ pure-function QSS builder + gate guards
- `tests/code/test_ui_variant_scaffold.py` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ flag resolution never raises
- `tests/code/ui_services/test_thumbnail_active_state_and_strip.py` (20) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ **behavioural**, on real Qt widgets. A source-string pin cannot see a z-order bug; that is exactly how the buried download bar survived `test_thumbnail_panel_ui_fixes.py`.
- `tests/code/ui_services/test_main_footer_bar_removed.py` (6) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ footer stays hidden, its widgets stay alive, and it fails loudly if anyone starts writing to its labels

---

### Patient search + patient list

| Doc | What's in it |
|---|---|
| [`AUDIT_STAGE_2_2026-05-28.md`](plans/architecture/AUDIT_STAGE_2_2026-05-28.md) | Search workflow audit, `_hp_search.py` print-to-logger fixes. |

**Guard tests:**
- `tests/code/system/test_hp_search_logging_guard.py` (5 guards)
- `tests/code/ui_services/test_clear_table_crash_guard.py` (16 guards) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ patient-table Qt/Shiboken ownership-safe clear/removal, producer interlock, and Local Server no-nested-event-loop contract

---

### Patient open + tab management

| Doc | What's in it |
|---|---|
| [`AUDIT_STAGE_3_2026-05-28.md`](plans/architecture/AUDIT_STAGE_3_2026-05-28.md) | Click-to-open audit, cross-patient isolation verification. |
| [`AUDIT_STAGE_10_2026-05-28.md`](plans/architecture/AUDIT_STAGE_10_2026-05-28.md) | Print-rebind ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ debug-silencing fix (13 error paths now visible in `app.log`). |

**Guard test:** `tests/code/system/test_hp_patient_open_logging_guard.py` (4 guards)

---

### Database (`dicom.db`) + test isolation

| Doc | What's in it |
|---|---|
| **`COPILOT_REPORT_db_cleanup.md`** (top-level) | 2026-05-24 pollution cleanup record. Patch `PacsClient.utils.data_paths.DATABASE_FILE` for tests, NOT `database.core._DB_PATH`. |

**Guard test:** `tests/code/database/conftest.py` (PRAGMA `database_list` invariant ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ loud-fail if a test connects to the live DB).

---

### Eagle Eye / AI module

Brain volumetry: [implementation and qualification status](modules/EAGLE_EYE_BRAIN_VOLUMETRY.md)
documents the 3D T1w/FLAIR tool, local SynthSeg/Slicer adapter, separate volume
estimators, synthetic verification and remaining model/normative/clinical gates.

Build variants and cached AI assets:
[`builder/docs/DISTRIBUTION_EDITIONS_AND_OFFLINE_ASSETS.md`](../builder/docs/DISTRIBUTION_EDITIONS_AND_OFFLINE_ASSETS.md)
defines Eagle Eye, compact Standard and ARM compatibility outputs, offline wheels,
mandatory weights, measured size baseline and remaining release gates.

| Doc | What's in it |
|---|---|
| [`pipelines/eagle-eye-mri.md`](pipelines/eagle-eye-mri.md) | **Official primary Eagle Eye MRI architecture:** geometry ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ anatomical localization ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ task-specific normal/abnormal screening cards ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ diagnostic cards ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ pathology classification; stable cross-stage contracts, fail-closed policy, central card registry, five lumbar screening templates, five lumbar diagnosis templates, and the Gate 1/Gate 1-to-2 rule that physical spacing is the primary grouping cue, labels secondary, and color tertiary. Start here for all MRI Eagle Eye work. |
| [`modules/ADVANCED_ANALYSIS_RESIDENT_RUNTIME.md`](modules/ADVANCED_ANALYSIS_RESIDENT_RUNTIME.md) | OPT-56 hidden concurrent Slicer startup, same-process viewer reuse, isolated headless threshold/offline model jobs, authenticated API, lifecycle and artifact policies, synthetic timings, deleted-button launch and invisible-modal repairs, and remaining acceptance. |
| [`modules/ADVANCED_ANALYSIS_OFFLINE_LUMBAR.md`](modules/ADVANCED_ANALYSIS_OFFLINE_LUMBAR.md) | Implemented offline TotalSegmentator MR vertebral adapter, separate portable CPU environment, combined Advanced MPR installer staging, Python control surface, synthetic verification and release/clinical limitations. |
| [`reports/OFFLINE_LUMBAR_IMPLEMENTATION_VERIFICATION_2026-08-31.md`](reports/OFFLINE_LUMBAR_IMPLEMENTATION_VERIFICATION_2026-08-31.md) | Real portable model and Slicer smoke test, empty synthetic-model output versus nonempty geometry fixture, installer guards, failed attempts, and outstanding customer/clinical acceptance. |
| [`AUDIT_STAGE_7_2026-05-28.md`](plans/architecture/AUDIT_STAGE_7_2026-05-28.md) | Three-layer defense map (structural + canonical pywinauto + modality gate). |
| [`plans/EAGLE_EYE_LUMBAR_STAGE1_2026-08-26.md`](plans/EAGLE_EYE_LUMBAR_STAGE1_2026-08-26.md) | Lumbar series resolution, capture protocol, geometry, and reference-line invariants. |
| [`reports/EAGLE_EYE_SLICER_TOOL_AUGMENTATION_FEASIBILITY_2026-08-31.md`](reports/EAGLE_EYE_SLICER_TOOL_AUGMENTATION_FEASIBILITY_2026-08-31.md) | Research assessment of Slicer/MCP augmentation: current integration limits, MRI anatomy models versus lesion diagnosis, bounded tool architecture, and fixed-versus-adaptive evidence experiments. No runtime implementation or clinical validation. |
| [`reports/SLICER_RUNTIME_CONTROL_AUDIT_2026-08-31.md`](reports/SLICER_RUNTIME_CONTROL_AUDIT_2026-08-31.md) | Executed control audit of the existing custom Slicer runtime: external loopback commands, synthetic DICOM/NRRD loading, threshold changes, segmentation/NIfTI save/reload, measurement, inventory, Mask Volume setup failure, and proposed LLM function boundary. |
| [`modules/ADVANCED_ANALYSIS_SLICER_CONTROL_RUNBOOK.md`](modules/ADVANCED_ANALYSIS_SLICER_CONTROL_RUNBOOK.md) | Practical control reference: runtime identity, repeatable synthetic probe, load/segment/read/save APIs, geometry, safe named tools, and tested versus proposed MCP behavior. |
| [`modules/SLICER_EXTENSIONS_INSTALL_AND_CONTROL_GUIDE.md`](modules/SLICER_EXTENSIONS_INSTALL_AND_CONTROL_GUIDE.md) | Extension download/install/control guide: pinned source audit, executed third-party measurements, separate GUI failure, TotalSegmentator/MONAI/MedSAM/Raidionics APIs, model download evidence, dependencies, and qualification sequence. |
| [`plans/EAGLE_EYE_LUMBAR_CURRENT_STATE_2026-09-02.md`](plans/EAGLE_EYE_LUMBAR_CURRENT_STATE_2026-09-02.md) | **Historical 7.7.0 snapshot:** pre-registry anatomy gate, four screening cards, diagnostic-card implementation, measured conclusions, and pending experiment. Superseded for architecture by `pipelines/eagle-eye-mri.md`. |
| [`plans/EAGLE_EYE_MAMMOGRAPHY_INTELLIGENT_ANALYSIS_MERGE_2026-09-02.md`](plans/EAGLE_EYE_MAMMOGRAPHY_INTELLIGENT_ANALYSIS_MERGE_2026-09-02.md) | Selective review and 3.6.4 port of the collaborator mammography workflow: bounded de-identified evidence, unique stale-path rebinding through an immutable viewer snapshot, worker-thread package/request execution, shared EchoMind/GapGPT authority, physician review, explicit exclusions, safety limits, and release gates. |
| [`plans/EAGLE_EYE_ATOMIC_STRUCTURE_PIPELINE_2026-09-02.md`](plans/EAGLE_EYE_ATOMIC_STRUCTURE_PIPELINE_2026-09-02.md) | Historical pipeline 7.7.0 implementation record. Its anatomy-gate, strict identity, fail-closed, and atomic-diagnosis evidence remains valid, but its four-card screening transport is superseded by the canonical five-template registry. |
| [`plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md`](plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md) | Historical implementation log for pipelines 1.x-7.0, retained for audit and benchmark archaeology. Do not use it as the concise current-state description. |
| [`plans/EAGLE_EYE_LLM_PROMPT_DRAFT_2026-08-26.md`](plans/EAGLE_EYE_LLM_PROMPT_DRAFT_2026-08-26.md) | Prompt-design history and the sequence/plane evidence rules. |
| [`plans/EAGLE_EYE_FOCUSED_V3_MORPHOLOGY_RESEARCH_PLAN_2026-08-31.md`](plans/EAGLE_EYE_FOCUSED_V3_MORPHOLOGY_RESEARCH_PLAN_2026-08-31.md) | Research and phased proposal: V3 limitations, localization-first screening, independent multiplanar diagnosis through GapGPT, neutral attention, and benchmark repair. Section 16 records OPT-55 axial backfill, bilateral sagittal coverage, level-conflict review, padding-only headroom, scorer 1.2.0, and offline verification. Full Phase 0 and controlled model experiments remain pending. |
| [`plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#36-source-grounded-correlated-screening-and-focused-v4-2026-09-01`](plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#36-source-grounded-correlated-screening-and-focused-v4-2026-09-01) | Focused V4 implementation: diagnosis-free raw-DICOM screening atlas, immutable tile identities, local LPS correlation, lesion-centred GPT evidence, independent fallbacks, and validation limits. |
| [`plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#38-historical-v4-runtime-and-legacy-retirement-2026-09-01`](plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#38-historical-v4-runtime-and-legacy-retirement-2026-09-01) | Historical pipeline 5.4 evidence policy: how V4 became canonical and how older composers were confined to an explicit engineering rollback gate. Section 41 records the current V5 default. |
| [`plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#39-submillimetric-sagittal-screening-pages-and-sampling-audit-2026-09-01`](plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#39-submillimetric-sagittal-screening-pages-and-sampling-audit-2026-09-01) | Pipeline 5.4.0 screening evidence: larger bounded sagittal tiles, role-specific paging, exact effective sampling and request-budget audit, fallback behavior, and clinical validation limits. |
| [`plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#40-salience-aware-screening-and-dominant-focus-retention-2026-09-01`](plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#40-salience-aware-screening-and-dominant-focus-retention-2026-09-01) | Pipeline 5.5.0 screening contract: atlas-specific instructions, diagnosis-free visual salience and within-study priority, deterministic marked/dominant focus retention, explicit capacity review, and the pending frozen-atlas temperature experiment. |
| [`plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#41-self-contained-diagnostic-level-cards-2026-09-01`](plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#41-self-contained-diagnostic-level-cards-2026-09-01) | Pipeline 5.6.0 / focused V5: one card per selected level with targeted sagittal T2, matched sagittal T1 and up to four same-slab axial T2 frames; global upload identity, authoritative attention/card bindings, cross-card citation review, and diagnosis-neutral MRI context. |
| [`plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#42-fixed-anatomical-reading-template-for-each-diagnostic-level-card-2026-09-01`](plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#42-fixed-anatomical-reading-template-for-each-diagnostic-level-card-2026-09-01) | Pipeline 5.7.0: Gemini proposes inventory-bound tiles for a fixed sagittal T2/T1 plus axial T2 3 x 3 level card; local role/slab validation, explicit fallbacks, shared diagnostic reading order, and separate axial-zone versus craniocaudal nomenclature. |
| [`plans/LEGION_CONSULT_FOUNDATION_2026-08-28.md`](plans/LEGION_CONSULT_FOUNDATION_2026-08-28.md) | MRI-only function picker, mandatory source/T1/T2 selection, optional/all-series cost control, Fast ROI geometry, local request schema, and the capture/model boundary. |

**Guard tests:**
- `tests/code/ai_imaging/test_eagle_eye_anatomy_gate.py` (diagnosis-free anatomy mapper, seeded-ID exclusion, immutable neutral sagittal/axial groups, model-owned semantic assignments, physical-order audit without semantic relabelling, exact five-card output, task-specific physically separated Gate 1-to-2 blocks, saved manifest, and one-card screening boundary)
- `tests/code/ai_imaging/test_eagle_eye_canal_screening.py` (central-canal caliber/CSF decision audit, same-group evidence, minor-impression and lateral-recess separation, bounded same-study MR-myelography overview context, and identity/resource rejection)
- `tests/code/ai_imaging/test_eagle_eye_card_template_registry.py` (immutable cross-MRI template identity, five lumbar screening and five diagnosis cards, task/sequence boundaries, fail-closed lookup, and runtime registry projection)
- `tests/code/ai_imaging/test_eagle_eye_atomic_structure_pipeline.py` (five task-specific screening requests, independent disc/canal/foramen/marrow/posterior boundaries, compact JSON, bounded 24000/12000 response allowances, truncation rejection, filtered-atlas identity, registry-derived diagnosis profiles, no retired Gemini template requirement, one-card diagnostic contract, strict response identity, and deterministic merge)
- `tests/code/ai_imaging/test_eagle_eye_stage_audit.py` (session-contained path enforcement, anatomical-map summary, exact grouped-screening image inventory, truncation visibility, diagnostic-card identity, frame metadata, and diagnostic-request image inventory)
- `tests/code/ai_imaging/test_eagle_eye_llm_analysis.py` (package, model routing, parallel multi-source context fusion, paired sagittal T2/T1 context selection, focal-attention normalization/forwarding, patient-laterality and same-lesion multiplanar morphology contracts, inventory-scope guards, DICOM document rendering, grading and disc-hydration contracts, stage sampling, persistence, and transport parity)
- `tests/code/ai_imaging/test_eagle_eye_grading_contract.py` (catalog 2.0.0 Bartynski criteria, separately versioned root effects, diagnostic-only rubric in pipeline 5.1.0; stage-two document sections 32-34)
- `tests/code/ai_imaging/test_eagle_eye_screening_attention.py` (localization-only screening, diagnosis-free canonical handoff, salience-aware dominant-focus retention, capacity-review warnings, duplicate and contradiction resolution, normal exclusion, compact public context, source-bound cross-plane frame/box validation, malformed input, legacy-anatomy adaptation, separate same-level compartment identities and anatomy-first diagnostic contract; stage-two document sections 33-34, 37 and 40)
- `tests/code/ai_imaging/test_eagle_eye_frozen_input.py` (offline saved-input identity, byte/order/prompt preservation, path/size limits, incomplete writes and tamper detection; snapshot preparation, not model replay)
- `tests/code/ai_imaging/test_eagle_eye_gapgpt_capability.py` (synthetic capability matrix, strict-schema evaluation, redaction, and GapGPT authority reuse)
- `tests/code/ai_imaging/test_eagle_eye_focused_v2.py` (bounded focus planning, per-slice multi-slab geometry, capture-frame authority under reversed source order, same-slab boundary backfill without moving sagittal anchors in V2/V3, manifest coverage, quality/budget gates, private provenance, verification-only dispatch, and immutable-layout fallback)
- `tests/code/ai_imaging/test_eagle_eye_focused_v3.py` (physical crop geometry, retained source resolution, render-profile separation, sampling provenance, unchanged slice selection between V2/V3, and deliberate opt-in mode)
- `tests/code/ai_imaging/test_eagle_eye_parasagittal.py` (opt-in bilateral LPS supplements, exact V3 baseline retention, explicit source numbering/offsets, partial coverage, all budget caps, and verification-only dispatch/failure)
- `tests/code/ai_imaging/test_eagle_eye_axial_locator.py` (spare-cell axial-plane locators, shared DICOM reference and source-affine validation, oblique/reversed/anisotropic geometry, finite FOV clipping, missing/partial links and exact clean-pixel retention; stage-two section 35)
- `tests/code/ai_imaging/test_eagle_eye_level_identity.py` (stable capture-range comparison, uniform shifts despite monotonicity, measured-slab conflicts, invalid/incomplete maps, persisted review-required reports/UI, and score diagnostics without automatic relabeling)
- `tests/code/ai_imaging/test_eagle_eye_bench_scoring.py` (prose parsing, attribute-scoped root negation, contact-versus-compression scoring, and scorer version provenance; full Phase 0 repair remains pending)
- `tests/code/ai_imaging/test_eagle_eye_lumbar_pipeline.py` (protocol and capture behavior)
- `tests/code/ai_imaging/test_eagle_eye_protocol_resolution.py` (series identity and readiness)
- `tests/code/ai_imaging/test_eagle_eye_ui_boundary.py` (feature coordinator ownership, mapping handoff, provider-neutral result metadata, reusable stage-image gallery entry, and teardown)
- `tests/code/ai_imaging/test_legion_consult_foundation.py` (pure series policy, ROI geometry, and local persistence contract)
- `tests/code/ai_imaging/test_legion_consult_ui_contract.py` (function picker, selection dialog, source identity, and toolbar routing)
- `tests/code/ai_imaging/test_mammography_intelligent_analysis.py` (MG/study-bound de-identified package, unique stale-path rebinding, ambiguous-identity rejection, immutable viewer snapshot, bounded CSV/images/findings, temporary cleanup, worker-thread execution, dedicated-controller boundary, and direct MG toolbar routing)
- `tests/code/system/test_2026_05_27_regression_guards.py::test_mg_mirror_is_deferred_via_qtimer` (structural)
- `tests/gui/pywinauto/test_eagle_eye_dragdrop.py` (canonical Win32 OLE drag-drop)

---

### Module launchers (Eagle Eye / MPR / Printing / Education / Advanced Analysis)

| Doc | What's in it |
|---|---|
| [`AUDIT_STAGE_8_2026-05-28.md`](plans/architecture/AUDIT_STAGE_8_2026-05-28.md) | **Adapter-readiness map per module.** Lists where each launcher lives and what refactor it needs before CommandBus integration. |

**Guard tests:**
- `tests/code/echomind/test_module_adapter.py`
- `tests/code/echomind/test_module_catalog_coverage.py` (drift reporter ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ currently 4 / 15 wired = 27 %)
- `tests/code/echomind/test_bus_factory.py`

---

### Unified Command Layer (EchoMind / CommandBus / Adapters)

| Doc | What's in it |
|---|---|
| **[`plans/architecture/UNIFIED_COMMAND_LAYER_2026-05-27.md`](plans/architecture/UNIFIED_COMMAND_LAYER_2026-05-27.md)** | Architecture design. |
| [`plans/architecture/IMPLEMENTATION_PLAN_2026-05-27.md`](plans/architecture/IMPLEMENTATION_PLAN_2026-05-27.md) | Phase-by-phase spec. |

**Guard tests:** every file under `tests/code/echomind/` (12 files).

---

### Agent control and MCP gateways

**Mandatory verification memory (2026-09-14):**
[Agent control guide, section 0](for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md)
owns the two independent code/live GUI gates, MCP discovery and same-pipe CLI fallback,
bounded reception/PACS multi-study case selection, input/visual fidelity and PHI-safe receipts.
The current Home-click cutover needs real card input; a downstream `change_series` is not coverage.

| Doc | What's in it |
|---|---|
| **[`architecture/PRE_DEVELOPMENT_SYSTEM_MAP_2026-08-27.md`](architecture/PRE_DEVELOPMENT_SYSTEM_MAP_2026-08-27.md)** | **Start here.** Separates the production paired-device Agent Gateway from the source-only developer test MCP and records their trust boundaries. |
| [`for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md`](for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md) | CommandBus testing workflow and tool-selection guidance. |
| [`../tools/testing/aipacs_control_mcp/README.md`](../tools/testing/aipacs_control_mcp/README.md) | `aipacs-control` setup, tool catalog, safety rules, and fidelity tiers. |

**Guard tests:**
- `tests/code/agent_gateway/` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ pairing, auth, TLS, relay, MCP, permission, lifecycle, and wiring
- `tests/code/echomind/test_test_server.py` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ source-only QLocalServer gate and transport
- `tests/code/echomind/test_command_bus_unit.py` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ shared command execution seam

---

### Layout & responsive UI

| Doc | What's in it |
|---|---|
| **[`conventions/RESPONSIVE_UI_CONVENTION.md`](conventions/RESPONSIVE_UI_CONVENTION.md)** | The seven archetypes (horizontal scroll wrap, wrapping label, elided label, splitter, min-height form fields, table column policy, empty-state). |
| [`plans/RESPONSIVE_UI_STRUCTURAL_PATTERN_2026-05-26.md`](plans/RESPONSIVE_UI_STRUCTURAL_PATTERN_2026-05-26.md) | Background + decision tree. |
| [`AUDIT_STAGE_9_2026-05-28.md`](plans/architecture/AUDIT_STAGE_9_2026-05-28.md) | `QScrollArea.setHorizontalScrollMode` regression fix. |

**Guard tests:**
- `tests/code/system/test_responsive_layout_qscrollarea_guard.py` (4 guards)
- `tests/code/system/test_titlebar_userinfo_clamp_guard.py` (7 guards)

---

### Logging & observability

| Doc | What's in it |
|---|---|
| [`AUDIT_STAGE_10_2026-05-28.md`](plans/architecture/AUDIT_STAGE_10_2026-05-28.md) | `app.log` catch-all handler + `_hp_patient_open` print-rebind fix. |

**Guard tests:**
- `tests/code/system/test_diagnostic_logging_catchall.py` (7 structural guards)
- `tests/code/system/test_hp_patient_open_logging_guard.py` (4 guards)
- `tests/code/system/test_hp_search_logging_guard.py` (5 guards)

---

### KPI machinery

| Doc | What's in it |
|---|---|
| **[`tests/_kpi/README.md`](../tests/_kpi/README.md)** | How to add a new KPI, how the collector hooks the bus, how the reporter CLI works. |
| [`plans/architecture/SCENARIO_KPIS_2026-05-28.md`](plans/architecture/SCENARIO_KPIS_2026-05-28.md) | KPI taxonomy ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ 42 keys across 13 workflows. |

**Guard test:** `tests/code/system/test_kpi_schema.py` (registered-keys integrity).

**Tools:**
- `tools/kpi_dashboard.py` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ framework health snapshot (exit 0 / 1 / 2)
- `tools/kpi_html_report.py` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ trend report from the JSONL sink
- `tools/kpi_build_compare.py` ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ cross-build divergence detector

---

### Release publication and build operations

- [Canonical versioned Git release workflow](../RELEASE.md)
- [Canonical six-installer build workflow](../BUILD.md)
- [Version 3.6.6 release gate and current blockers](releases/VERSION_3.6.6_RELEASE.md)
- [Version 3.6.6 build evidence](releases/VERSION_3.6.6_BUILD.md)
- [Version 3.6.5 release record](releases/VERSION_3.6.5_RELEASE.md)
- [Version 3.6.5 build evidence](releases/VERSION_3.6.5_BUILD.md)
- [Release notes](releases/VERSION_3.6.4_RELEASE.md)
- [2026-08-31 source follow-up, verification, and exclusions](releases/VERSION_3.6.4_FOLLOWUP_2026-08-31.md)
- [2026-08-31 source-publication safety record](../deploy-record-workstation-2026-08-31.md)

### Testing architecture

| Doc | What's in it |
|---|---|
| **[`plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md`](plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md)** | The full design ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ goals, taxonomy, test discipline, regression-catalog rules. |
| [`tests/QUICKSTART.md`](../tests/QUICKSTART.md) | 5-minute onboarding ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ how to run, where to add tests, the hard rules. |
| [`AUDIT_2026-05-28_OVERVIEW.md`](AUDIT_2026-05-28_OVERVIEW.md) | What the audit produced and the cumulative numbers. |

- Brain published volBrain offline interval default and source rights: `docs/modules/EAGLE_EYE_BRAIN_REFERENCE_SETUP.md`.


EchoMind STT quality selection (2026-09-07): see `reports/ECHOMIND_STT_SECURITY_REVIEW_2026-09-07.md` and `tests/code/echomind/test_transcribe_retry.py`.

## Eagle Eye paired spatial cards (2026-09-08)

The [spatial experiment report](reports/EAGLE_EYE_SPATIAL_PACKET_EXPERIMENT_2026-09-08.md)
now includes the visual handoff correction: one-line mini-locator next to clean,
pre-enlarged sagittal and matching axial panels, with complete native groups and
separate layout-only validation. The earlier diagnostic trial used the old layout.

Printing transport audit (2026-09-09): [DICOM and Windows print fidelity, protocol, settings, and device verification gaps](modules/PRINT_TRANSPORT_AUDIT_2026-09-09.md). Read-only runtime audit with synthetic probes; no production fixes in this pass.

Printing audit correction: `docs/modules/PRINT_TRANSPORT_AUDIT_2026-09-09.md` includes the authorized fidelity/transport follow-up, 89-test validation, and remaining device/profile limitations.

Printing scout/layout review: [proportional 150% scout implementation, shared geometry, paper-aware design, MR brain/lumbar preset scope and reference-line identity gaps](modules/SCOUT_LAYOUT_REVIEW_2026-09-09.md). The first proportional-scout stage is implemented; center-owned presets remain pending.

## EchoMind report typography (2026-09-13)

[Display and Reception font parity](echomind/REPORT_TYPOGRAPHY_2026-09-13.md):
shared proportional character/block scaling, explicit title/section/organ/body
sizes, legacy HTML behavior, fail-before evidence, 119 passing focused checks,
source/payload parity and pending source Reception/print acceptance.


EchoMind pathology organization: the amendment in
[Report typography](echomind/REPORT_TYPOGRAPHY_2026-09-13.md) documents ordered
finding groups, intra-item sentence breaks, preserved punctuation, spacing and
Qt/Reception parity guards. Saved historical reports are not rewritten.


EchoMind all-modality coverage: [Report typography](echomind/REPORT_TYPOGRAPHY_2026-09-13.md)
now covers all six current modality schemas, specialty section headings, shared
report entry points and renderer preservation in all three edition stages.
164 focused checks pass; next-candidate compilation and live acceptance remain separate.

- [Brain MS lesion candidate evaluation](modules/EAGLE_EYE_BRAIN_MS_LESION_DESIGN.md): separate T1/FLAIR lesion pipeline, LST-AI evidence and activation gates; not enabled.

Eagle Eye background interaction: `modules/ai_imaging/background_analysis.py`, `tests/code/ai_imaging/test_eagle_eye_background.py`, and the background amendment in [workspace entry](modules/EAGLE_EYE_WORKSPACE_ENTRY_2026-09-11.md). Lifecycle/responsiveness tracking remains in OPT-51 / OPT-58.

## Eagle Eye empty-entry function selection (2026-09-15)

See `modules/EAGLE_EYE_BRAIN_UI_AND_MAINTENANCE.md`: click-time same-study mode refresh; automated guards pass, fresh live acceptance tracked separately.

WMH normative completion status: [Percentile readiness](modules/EAGLE_EYE_WMH_PERCENTILE_READINESS_2026-09-15.md)
records missing fitted-model inputs, the de Kort alternative normalization contract,
and the unsent author request. Patient percentiles are not implemented.
# Eagle Eye manual segmentation review

Advanced Analysis UI/UX: [September 15 live audit](reports/ADVANCED_ANALYSIS_UI_UX_AUDIT_2026-09-15.md)
records small-monitor fitting, menus, remaining Slicer text, sampled independent
PACS interaction and guarded 3.6.6 source version alignment. Native rebuild pending.

See [Brain maintenance](modules/EAGLE_EYE_BRAIN_UI_AND_MAINTENANCE.md) for isolated
Slicer edits, lesion recalculation and binary brain addenda. Runtime:
`manual_review.py`, `manual_slicer.py`; guard: `test_manual_brain_review.py`.


## Advanced preview metadata alignment (2026-09-16)

`image_io.load_series_preview` aligns bounded header metadata to decoded files, not
DB prefix order. Six synthetic guards and the remaining source-GUI gate are recorded
in the [VTK review](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#opt-35-preview-frame-metadata-alignment-2026-09-16-post-2051-session).


## Advanced loading cover across page switches (2026-09-16)

[VTK report](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#opt-23-native-cover-after-page-switch-2026-09-16): scoped top-level overlay show guard, three new behavioral tests,
46 focused passes and pending live page-switch acceptance. Separate remote-drop
waiting evidence is handed off to the Download Pipeline owner document.

## Advanced filter performance measurement (2026-09-16)

The VTK review records per-stage ADVANCED-FILTER-KPI instrumentation, synthetic MR/CT pixel invariance guards and the remaining real-workload/first-font-render investigation. No filter quality or geometry changes.


## MPR partial-volume admission (2026-09-16)

The toolbar now rejects explicit Advanced previews and metadata/pixel-depth shortfalls
before MPR reuse. See the [VTK review](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#opt-35--opt-48-guarded-mpr-admission-2026-09-16)
and `tests/code/viewer/test_mpr_partial_volume_admission.py`. Geometry is unchanged;
fresh-source GUI acceptance and upstream preview promotion remain open.

## Advanced decoded cache pairing (2026-09-17)

`advanced_payload_integrity.py` validates Advanced pixel/metadata coverage; four controller cache methods prevent metadata-only growth and inconsistent cache reuse. See VTK report and `test_advanced_cache_integrity.py`. Unify owns the coordinated tab-delivery correction.


## MPR deferred 3D lifecycle guard (2026-09-17)

`modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py` checks teardown after progress-event
processing. Guard: `tests/code/mpr/test_mpr_deferred_build_reentrancy.py`; evidence and
fresh-source GUI gate in the VTK domains report, OPT-48 deferred 3D reentrancy section.


## Advanced cold preview counter render (2026-09-17)

`modules/viewer/advanced/slice_progress.py` uses parenthesized loading/ready status to avoid VTK MathText column detection. Guard: `tests/code/viewer/test_advanced_counter_text_backend.py`. See the first handoff receipt in the VTK domains report for measurements and fresh-source GUI gate.


## Advanced mixed MR/SC presentation (2026-09-17)

Worker: `PacsClient/pacs/patient_tab/utils/advanced_presentation.py`; native renderer helper:
`modules/viewer/advanced/presentation_frames.py`. Independent frame/graphic data are explicitly
nonspatial and excluded from MPR/full-volume cache. Guard: `tests/code/viewer/test_advanced_presentation_sequence.py`.
See VTK report OPT-35 mixed MR/SC implementation; stale loading title is a separate Unify handoff.


## Advanced large DX presentation (2026-09-18)

`PacsClient/pacs/patient_tab/utils/advanced_presentation.py` admits exact DX for-presentation
objects without spatial-stack geometry, retaining native frames/VOI and explicit image-plane
or detector spacing. `modules/viewer/interactor_styles/ruler_interactorstyle.py` labels detector
and uncalibrated presentation measurements. Guard: `tests/code/viewer/test_advanced_presentation_sequence.py`.
Evidence and open GUI/build acceptance: VTK domains report, OPT-35 large DX correction.


## Eagle Eye Total Spine reader correction (2026-09-19)

See [Total Spine module guide](modules/EAGLE_EYE_TOTAL_SPINE_ALIGNMENT.md) for editable
endplate lines, body-label anchor numbering, pedicle evidence and translated
perpendicular angle overlays. The [report specification](modules/EAGLE_EYE_TOTAL_SPINE_REPORT_SPEC.md)
retains outstanding clinical reference/protocol limitations. The guide separates
synthetic verification from the blocked native source entry workflow.


### Total Spine embedded editor and classic Cobb construction

The [module guide](modules/EAGLE_EYE_TOTAL_SPINE_ALIGNMENT.md) now documents the direct
Eagle Eye header button, study-owned native tab, headless model execution, source
endplate extensions and connected perpendicular construction. No external Slicer UI
is required. Existing Advanced rendering findings remain with their viewer owner.


### Total Spine results-first function flow (2026-09-19)

The direct header button is superseded by Choose Function. See
`tests/code/ai_imaging/test_total_spine_workspace.py` for delayed last-tab insertion,
automatic inference after required ROI input, unnumbered physical-angle proposals,
empty/canceled-result handling, background modality resolution and compact sections.
The module guide records remaining manual inputs and the pending fresh-source GUI gate.


### Total Spine direct mouse correction and naming (2026-09-19)

`tests/code/ai_imaging/test_total_spine_editing.py` covers unnumbered candidate
selection, body/line/endpoint dragging, ROI resizing, rejection and Undo.
`test_total_spine_workspace.py` also covers the result reparent fit and expanded
calibration width. Left naming and right review panels are documented in
`docs/modules/EAGLE_EYE_TOTAL_SPINE_ALIGNMENT.md`. Native verification of this
interaction revision remains pending; 137 focused tests passed.


## Advanced DOC/SC document pages (2026-09-20)

`PacsClient/pacs/patient_tab/utils/advanced_presentation.py` now routes exact DOC Secondary
Capture pages by SOP/modality, independently of series number. Native frames remain nonspatial;
no image filters apply. This does not route encapsulated PDFs or alter shared multi-study keys.
Guard and evidence: presentation sequence tests and VTK domains report OPT-35 DOC/SC section.


Advanced DOC budget follow-up (2026-09-20): `advanced_presentation.py` distinguishes
native byte-RGB retained storage from largest-page scratch/overlay costs. The 512 MiB cap
remains unchanged. See VTK domains report DOC whole-series memory follow-up.

### Eagle Eye selected series and common progress (2026-09-20)

See [workspace entry](modules/EAGLE_EYE_WORKSPACE_ENTRY_2026-09-11.md#active-series-and-background-activity-2026-09-20)
and `tests/code/ai_imaging/test_eagle_eye_selected_series.py` for active viewport
handoff, per-series review ownership, projection-only prompts and activity UI.

### Eagle Eye preparation/result presentation (2026-09-20)

`modules/ai_imaging/eagle_eye_result_tabs.py` owns Bone Age/Mammography result tabs
and same-viewer presentation. See [workspace entry](modules/EAGLE_EYE_WORKSPACE_ENTRY_2026-09-11.md#preparation-and-result-tabs-2026-09-20)
and `tests/code/ai_imaging/test_eagle_eye_result_tabs.py` for preserved feedback and
pending native rendering acceptance.

### Total Spine action discovery and Segment feasibility (2026-09-20)

See `docs/modules/EAGLE_EYE_TOTAL_SPINE_ALIGNMENT.md` for implemented action controls
and `docs/modules/EAGLE_EYE_WORKSPACE_ENTRY_2026-09-11.md` for the local seed+ROI
segmentation investigation. The latter is a proposal, not an installed tool.


## Advanced large-stack interaction and preview prefix (2026-09-20)

Ordering adapter: `advanced_geometry_contract.preview_geometry_prefix`, consumed by
`image_io.load_series_preview`. Worker window provenance: `_apply_geometry_index_metadata`
to Advanced `viewer_2d` resolver. Large drag target: Advanced-scoped branch in
`abstract_interactorstyle.change_quickly_slices`. Guard: `test_advanced_preview_metadata.py`.
Evidence and live/cache limitations: VTK domains report OPT-35 large CT follow-up.


Advanced single-render spatial updates (2026-09-20): `viewer_2d._set_slice_impl` and
`_prepare_slice_visuals` avoid the second draw in the vtk_simpleitk domain while retaining
source geometry and visual state. Native render/pixel/camera/order/error-cleanup guard lives
in `test_advanced_preview_metadata.py`. Evidence: VTK domains report OPT-35 single native render.


## EchoMind Reception normal templates (2026-09-20)

[Reception template workflow and verification](echomind/RECEPTION_NORMAL_TEMPLATES_2026-09-20.md):
shared Settings/Manage browser, current modality and verified account priority, personnel
filters, reviewed local snapshots and template-only normals. Runtime adapter:
`modules/EchoMind/reception_templates.py`; Qt browser: `viewer_chat/reception_template_dialog.py`.

The same service owns sequential LLM organization and the separate persistent draft
store. Settings/Manage expose source-versus-organization review and editable final text;
Save & Use publishes into the normal library. Guards: `test_template_organization.py`
and `tests/gui/test_reception_template_ui.py`. See the workflow document for cancellation,
source preservation, retry behavior and the pending native GUI gate.

### EchoMind named pathology codes (2026-09-21)

Template organization retains source-referenced code labels, complete macro sentences and fillable fields. See `docs/echomind/RECEPTION_NORMAL_TEMPLATES_2026-09-20.md`; guards: `tests/code/echomind/test_template_organization.py` and `tests/code/echomind/test_normal_template_prompt.py`. Template-only activation rules leave no-template routine reporting unchanged.

### Template measurements and mammography choices (2026-09-21)

See `docs/echomind/TEMPLATE_MERGE_VALIDATION_2026-09-21.md`. `tests/code/echomind/test_template_organization.py` guards conditional choice banks; `tests/code/echomind/test_normal_template_prompt.py` guards template-only fidelity instructions; `tests/live/test_template_measurement_merge.py` supplies eight opt-in synthetic provider checks. Real-case and native GUI acceptance remain separate.

### EchoMind bilingual templates

See `docs/echomind/BILINGUAL_TEMPLATE_VALIDATION_2026-09-21.md` for paired storage, review-before-use, translation references, and remaining acceptance gates.

## Eagle Eye Server and Standard Client (2026-09-21)

[Server/client migration plan](plans/architecture/EAGLE_EYE_SERVER_CLIENT_PLAN_2026-09-21.md)
records the owner-directed server edition, model-free interactive Standard client,
Breast/Bone Age source inventory, isolated workers, durable jobs, geometry-aware edit
revisions, segmentation/Slicer boundary, packaging migration and staged acceptance.
This is a proposal; no runtime migration or deployment is claimed.

## Breast and Bone Age local engine integration (2026-09-21)

[Engine integration and execution gates](modules/EAGLE_EYE_BREAST_BONE_LOCAL_2026-09-21.md)
tracks owner-supplied model provenance, isolated CPU workers, MG/DX UI routing,
synthetic execution, and the separate GUI/packaging/server acceptance boundaries.
