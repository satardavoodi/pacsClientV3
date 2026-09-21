# AI-PACS Test Inventory — Index by Guard

## First-viewer graphics snapshot reuse (2026-09-20)

`code/viewer/test_viewer_gpu_boost.py` guards the shared Fast/Advanced graphics-policy
boundary. Repeated plan resolution may read/probe once per process, startup priming must
make even the first viewer independent of runtime-profile I/O, and saving a changed GPU
preference must invalidate the snapshot immediately. Two cases failed before the fix.
The final file passes 9 tests; adjacent runtime graphics, build-profile and WoA policy
selection passes 28 tests with one unrelated deselection. Fresh-source first/subsequent
viewer timing and backend parity remain the live gate.

## Shared viewport drag-hover activation (2026-09-20)

`code/viewer/test_viewport_drop_replacement.py` exercises the real Fast handler and
the real Advanced drag/drop mixin with internal series MIME. It requires traversal to
remain visually inactive until the existing stable-hover dwell arms, while proving
that a quick release still dispatches exactly one forced series replacement. A source
guard requires both production containers to consume `_DropHoverDwellMixin` and keeps
the quarantined legacy A/B route free of the immediate-internal bypass. The two core
behavior cases failed before the correction. Final file: 22 passed. Adjacent drag,
progressive, coalescing, multi-series, no-abandon, stacking and split-viewer selection:
199 passed, 15 GUI-tier skipped, 1 quarantined xfail and 1 unrelated deselected.
Fresh native Fast/Advanced mouse/OLE traversal remains the acceptance gate.

## Saved lumbar company model profile (2026-09-20)

`code/ai_imaging/test_eagle_eye_saved_model_profile.py` protects shipped Astra
screening/diagnosis defaults, separate Gemini anatomy/context, explicit model
overrides and direct user settings. It exercises the company reporter with a
synthetic image and intercepted transport to require original detail, medium
reasoning and completion-token budgeting only for the exact Astra aliases, while
retaining the company credential/endpoint authority and other model behavior.
`test_eagle_eye_llm_analysis.py` also exercises both company and direct atomic
dispatch, including recorded anatomy model identity. Final affected selection:
164 passed. Fresh-source GUI and installer acceptance remain pending.

## Patient-open identity and pre-construction admission (2026-09-19)

`code/ui_services/test_patient_study_set.py` and
`code/ui_services/test_patient_open_admission.py` protect the final shared boundary
between a Home selection and patient-widget construction. They require blank-primary
Local rows to promote the first owner-filtered resolved Study UID, reject stale/foreign
selection and no-study inputs, and prevent an empty UID from enumerating the thumbnail
root. Admission guards count active tabs plus reservations, reject duplicate opens,
clean up commit/abort paths and prove that capacity rejection never invokes the real
patient-widget factory. Eleven cases failed before the fix. Final focused selection:
41 passed; adjacent Home/Local/sidebar/lifecycle/storage selections: 298 passed with
two documented skips. Fresh-source GUI acceptance remains separate.

## Indexed-Local patient-open I/O ownership (2026-09-19)

`code/viewer/test_series_file_warm.py` proves that a producer-indexed Local row does
not cause the patient-open warmer to read the entire series again. The new behavioral
guard failed before the fix and passes after; a second fail-before guard requires that
no empty Local warm thread starts. `AIPACS_LOCAL_INDEXED_FILE_WARM=1` explicitly
restores the former behavior. `test_local_open_inventory_owner.py` additionally
requires a failed Local catalog lookup to remain Local instead of falling into the
Server raw-warm route. The same 24-test file preserves raw warming
for Server/unknown opens, global budgets and duplicate-run suppression. Paired producer
and database guards prove that Import and Download publish the durable summary only
after complete exact indexing, keep DICOM-object and cine-frame counts separate, and
fail closed on partial/pre-existing/changed directories. Combined Local/download/index
selection: 150 passed / 1 unavailable Windows symlink skip. Fresh source KPI remains a
separate acceptance gate.

## Ordered cold Local inventory ownership (2026-09-17)

`code/viewer/test_series_file_warm.py` keeps all previous budget, active-key, global
switch and raw Server guards, and now proves that every known Local directory is
delegated without any file touch. The independent
`AIPACS_LOCAL_ORDERED_INVENTORY=0` rollback restores the prior fact-primer route;
its older `AIPACS_LOCAL_PIXEL_FACT_WARM=0` switch then restores raw warm for
unverified rows. Indexed rows have the separate rollback documented above.

`code/ui_services/test_local_pixel_inventory_reuse.py` proves one ordered owner uses
bounded file concurrency without scanning the next series ahead of delivery. It pins
exact non-pixel exclusion, cine frames, result order and sequential rollback. Home and
patient projections consume the plural resolver while retaining their identity,
backfill and partial-result contracts. New fail-before: 4 failed / 44 passed; direct
final boundary 50 passed; Home/patient/offline/owner boundary 129 passed. Wider
UI/storage selection: 1,295 passed, two skips and three quarantined xfails; two
unrelated pre-existing source-spelling assertions remain red. Fresh-source cold and
warm single/multi-study KPI and visual stability remain pending.

## Local open orphan-reconcile ownership (2026-09-17)

`code/storage/test_orphan_series_prune.py` now guards both clinical safety and cost:
healthy series use a known DB instance path without enumerating the directory, while a
missing/stale path retains the full scan fallback. Partial-study orphan removal, pending
zero-row preservation, whole-study eviction, unreachable-root fail-safe and the kill
switch remain covered. A structural thread-ownership guard rejects synchronous pruning
in the GUI portion of patient open and requires the existing Local/background workers.
`test_local_open_inventory_owner.py` pins single-study, grouped and Server routing.
Fail-before: 2 failed. Direct boundary: 67 passed. Expanded selection: 337 passed /
1 unavailable Windows symlink skip. Post-fix source GUI remains pending.

**2026-09-18 post-catalog ordering:** `test_local_thumbnail_stream.py` now requires
first verified publication before orphan maintenance and retains the same single-study
worker self-heal. `test_local_open_inventory_owner.py` requires grouped Local and Server
metadata publication before their existing background owner prunes. These behavioral
guards failed before (`prune` was already complete at first publish and grouped order
was `prune -> push`). Direct stream/open/prune boundary: 61 passed; adjacent Local,
catalog, offline, sidebar, metadata, file-warm and DB-index boundary: 151 passed.
Fresh-source first-card/full-catalog/native acceptance remains open.

## Local patient-stream image ownership (2026-09-17)

`code/ui_services/test_local_catalog_producer.py` and the producer-index extensions
in `code/storage/test_db_first_metadata_index.py` plus
`code/ui_services/test_local_thumbnail_stream.py` protect the September 17
catalog-first acceleration. Import/download facts are published only after complete
indexing; cine object/frame totals stay distinct; pre-existing destinations fail
closed; only an unchanged managed directory revision bypasses per-file probing.
Unknown/legacy/changed rows retain the original verifier. Requirement run: 3 failed / 1
passed; exact contract selection 76 passed. Home and patient worker projections share
one batch backfill, and a changed scan revision is rejected at persistence. Expanded
boundary: 319 passed / 1 Windows symlink skip; adjacent import/download: 104 passed.

`code/ui_services/test_local_thumbnail_stream.py`: 40 synthetic/real-Qt cases;
`test_home_local_thumbnail_projection.py`: 7 projection cases, including one
PHI-free aggregate fast-path marker per study.
The new fail-before guard requires worker-only QImage preparation and GUI-only
QPixmap/card publication. Adjacent cases pin exact collision `folder_key` storage
identity and placeholder completion after read failure while retaining the prior
ordered-prefix, two-message backpressure, native destruction, grouped takeover,
cine count, persistence and refresh contracts. Original QImage slice: 37 passed;
the current file has 40 cases after the producer-index/backfill additions. Nine-suite
selection: 212 passed / 1 explicit Windows symlink-privilege skip; broader 29-file
Local/thumbnail/sidebar/right-panel/pipeline selection: 456 passed / same skip,
exit 0. Fresh normal-source GUI/KPI remains a separate gate in the shared UI-stall report.

## Home image preparation ownership (2026-09-17)

`code/ui_services/test_home_thumbnail_image_preparation.py`: 23 synthetic cases.
Two real Home renderer guards fail before with GUI QPixmap file reads. Covers
worker-only image preparation, GUI-only card application, source priority/embedded
formats, bounded ready images, 141-entry three-study order, skipped source-less
rows, stale/cleared/deleted owners, atomic refresh and repeated early cancellation.
214 adjacent passes plus 24 panel/effect guards; source GUI is a separate pending
gate. See the Home image preparation receipt in the shared UI-stall report.

## Local enumeration cost and freshness (2026-09-17)

`code/ui_services/test_local_inventory_enumeration.py`: 14 synthetic cases for
the shared inventory's directory-entry filtering. Two fail-before cost guards,
192-candidate comparison, platform selection/order, non-recursion, fresh version
after replacement/deletion, iterator closure before probing, error compatibility
and separate PHI-free cache timing fields. Real symlink case skips when Windows
creation privilege is unavailable (not a pass). Keep alongside memory/persisted
inventory guards and grouped/offline projection suites. See OPT-58/60 receipt.

## Single-study Local inventory owner (2026-09-17)

`code/ui_services/test_local_open_inventory_owner.py`: 10 behavioral cases execute
Home's actual setup worker with synthetic dependencies. No duplicate Local scan
or stale/foreign Home snapshot push; grouped 2/4-study catalogs preserve UID,
duplicate numbers, unnamed descriptions, object/cine counts and partial-coverage
handling. Server metadata/attachments and separate file warming remain intact.
Four pre-fix failures; pair with `test_pipeline_thumbnail_preparation.py` and
`test_local_thumbnail_stream.py` for independent startup and cancellation. See
the OPT-58/60 ownership receipt; code passes do not certify cold or multistudy GUI.

## Completed-load tab handoff (2026-09-17)

`code/viewer/test_inactive_load_result_handoff.py`: 25 behavioral cases executing
unchanged controller method bodies against synthetic worker/UI scheduling. Hidden
completion remains successful, owned events release after stale decode, previews do
not satisfy full-load admission, hidden publication does not render, activation is
token/cancellation-bound in manual and auto boost, close/re-hide/supersession are safe,
missing files still wait for download, secondary-study identity and complete resident
reuse remain intact. Deferred replacement cannot skip a new payload merely because
an old complete view has the same series number. Baseline mode reads only selected HEAD methods without reverting
the worktree. Pair with `test_advanced_cache_integrity.py`; both code and native GUI
gates are required by the OPT-35/60 receipt.

## Local persisted pixel facts (2026-09-17)

`code/ui_services/test_local_pixel_inventory_persistence.py`: 32 synthetic cases
for the same shared inventory service across memory retirement and a real fresh
process. Verify positive-only facts, exact source/profile isolation, cine/object
counts, add/remove/same-size replacement, mutation during read, access/cache I/O
failure, corrupt schema/checksum/records, expiry without renewal, atomic/concurrent
writes, nonblocking writer admission, bounded eviction, external-media/public-probe
isolation and no thumbnail-presence side effect. Four initial failures plus one
intermediate-placement failure; no live DB or clinical fixture. Source GUI and
matched cold/warm KPI remain separate gates in the OPT-58/60 receipt.

## Bounded cached/grouped sidebar build (2026-09-16)

`code/ui_services/test_sidebar_bounded_build.py`: 25 synthetic real-Qt/qasync cases.
Exact startup count without synchronous bulk construction; production card/header
geometry, identity/count separation, 141-card receipt, detached worker preparation,
no QPixmap on workers, late metadata/state replay, native deletion/close and generation
supersession; server entries must supersede the cache build, not become a second
GUI writer. An inactive patient tab may finish one detached preparation but cannot
apply it until the same generation is active again; direct native destruction releases
the paused coroutine without activation. The September 20 guards additionally require
late Study-set growth to supersede an active grouped snapshot, rehydrate disk-ready
borders and queue exactly one newer prefetch when the old worker is still active.
Seven pre-fix behavioral failures;
automated results do not replace live
GUI/KPI acceptance. Existing `test_sidebar_presentation_boundary.py` additionally
exercises the explicit no-loop compatibility route.

## Download-process interaction liveness (2026-09-16)

`code/download_manager/test_download_process_interaction_liveness.py`: 16 synthetic
cases execute current/legacy process-control functions, real prewarm handoff/entry
and shutdown logic behind fake native/process/IPC boundaries. Registered download
children must remain runnable regardless of viewport settling; no foreign native
resume, duplicate registration or loss of shutdown cleanup. 14 fail before / all
16 pass after retirement of hard suspension. Focused download/system suite 142
passes; packaging 9 passes. Expanded Viewer suite has one separately reproduced
existing spinner-double failure. See the
[implementation receipt](../docs/reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-opt-04-download-liveness-independent-of-viewport-settling).
No real process suspension or clinical data access; live GUI/KPI gate remains open.

## Advanced preview counts and orientation diagnostics (2026-09-16)

`code/viewer/test_advanced_slice_progress.py`: seven cases for known total versus ready
images, unknown/invalid totals, stale-total removal and real text actor refresh.
`code/viewer/test_advanced_orientation_audit_basis.py`: eight axial/sagittal/coronal/oblique
camera-basis cases preserving camera/image state, plus diagnostic-report truthfulness.
These are not clinical geometry acceptance; see the Advanced geometry contract and VTK report.

## Stable sidebar presentation boundary (2026-09-16)

20:51 live follow-up adds four real-Qt header cases: 2/4 studies, short/long text,
previous-exam labels and scrollbar admission. Headers and cards retain the geometry
they had before paint resumed. Expanded selection: 432 passes / 467 mirrors; fresh
source GUI pending. See the dated header-geometry receipt in the UI-stall report.

`code/ui_services/test_sidebar_presentation_boundary.py`: 33 synthetic behavioral
cases executing production methods with real Qt/card-manager geometry where relevant.
Covers grouped/retired ownership, explicit primary fallback and cancelled chunks,
parent retention, geometry before paint, nested paint/failure restoration, correct
header-excluded total and 32-card stable positions/labels/scroll/cine counts. Local
stream guards add ordered-prefix collision delivery and no terminal/refresh reorder.
Expanded 23-file selection: 428 passes, exit 0. Initial 466-pair mirror pass was
followed by one unrelated Advanced Viewer drift on final recheck. Native source GUI remains
pending; see the dated sidebar receipt in `UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md`.

## Advanced loading cover and full series (2026-09-16)

`code/viewer/test_advanced_loading_cover.py`: native-cover pixel opacity, unchanged
Fast child appearance, synchronous reused-overlay paint, overlapping completion and
cleanup generations, plus VTK call-site wiring. `code/viewer/test_advanced_complete_stack.py`:
synthetic 3/30-image MR files through the actual loader, aligned metadata/pixels, VTK
count and reachable first/last frame. See the VTK-domain report for live-test limits.

## Local incremental thumbnail delivery (2026-09-16)

Large-number follow-up: `test_series_metadata_incremental_identity.py` covers local
handle range, stable repeat admission, original path/cine counts and primary versus
secondary offset isolation. `test_local_thumbnail_stream.py` adds mixed-catalog early
delivery, large-number handoff, non-pixel alias exclusion, history-first fallback,
interleaved Home metadata and explicit-refresh retention. The startup file below also
guards completed-load deduplication. Together these three files have 76 cases; the
expanded follow-up selection has 344 passes, exit 0. Live source acceptance is pending.

`code/ui_services/test_local_thumbnail_stream.py` exercises the real builder, metadata
sink and renderer with synthetic repositories, Qt owners/timers and bounded workers:
early delivery, cancellation/native deletion, two-message backpressure, stale/grouped
owner rejection, collision fallback, cine counts, history order, existing-card reuse
and failure cleanup. The inactive-owner guard proves the worker pauses without retiring
or rescanning its generation and resumes in exact order. Additional guards pin the
legacy kill switch and sampled card-1/every-tenth INFO progress with an exact terminal
summary. `test_pipeline_thumbnail_preparation.py` additionally guards the
Local startup launch before Home metadata and grouped ownership. No clinical database
or DICOM data is accessed; these are code guards, not live GUI/pixel acceptance.
See the [receipt](../docs/reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-local-incremental-card-delivery-opt-58--opt-60).

## Advanced nonspatial US (2026-09-16)

`code/viewer/test_advanced_nonspatial_us.py`: 17 synthetic cases cover US loading
through DB-metadata/filesystem/grouped routes, stable frame/RGB correspondence,
preambleless input, rejection of mixed identities and unsupported geometry,
retirement of old viewport affines, scroll order, RGB mapper reuse, and MPR admission.
Database-facing routes use test-only paths and stubbed repositories. See the
[implementation receipt](../docs/reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#us-correction-opt-35-code-verified-live-pending).

## Advanced VTK startup phase timing (2026-09-16)

`code/viewer/test_advanced_startup_timing.py`: four guards for native input/first-render/
fit phase boundaries, deterministic disjoint elapsed durations, one completion record,
failed log-sink isolation and no completion claim for unfinished construction. The
boundary guard fails before wiring. This is instrumentation coverage, not a speed test;
see the [VTK next-test receipt](../docs/reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md).

## Fast initial-display preparation prerequisite (2026-09-16)

`code/viewer/test_fast_initial_display_preparation.py`: 37 synthetic cases for
worker-only initial preparation, single-consumer data adoption, owner/UID/revision/
config/policy rejection, cancellation/shutdown, thread affinity, retained cine
arrays and no neighbour fan-out. Real offscreen bridge pixel comparisons cover
grayscale/MONOCHROME1/RGB, filters and heterogeneous W/L; a delayed-read heartbeat
case checks GUI responsiveness. The initial-presentation case now includes real
annotations, plus no-stat image authority, changed metadata rejection, sorted
multiframe projection, read-failure fallback, bounded scope and post-edit refresh.
Tool persistence remains isolated; this is not an all-controller-I/O certification.
Ten absent-API failures preceded preparation; the overlay follow-up reproduced five
failures (two absent-context, three accepted wrong metadata). Final focused
335 passed / one existing xfail / three fixture skips; source-GUI acceptance
awaits scheduling activation. See the
[receipt](../docs/reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-fast-initial-display-preparation-primitive-opt-58--opt-60).

## VTK volume cache generation and budget (2026-09-16)

`code/ui_services/test_volume_cache_generation.py`: eight behavioral cases protect
key/study/all in-flight invalidation, fresh-generation retention, waiter cancellation,
failure and oversized-result delivery, integrated VTK byte budgeting, consumer pixel
lifetime after eviction, and module-domain isolation. Four original cases fail before
the fix. Synthetic data only; live source-GUI acceptance is tracked separately in the
[VTK review receipt](../docs/reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md).

## Incremental patient metadata identity (2026-09-16)

`code/ui_services/test_series_metadata_incremental_identity.py`: 15 synthetic
behavioral cases execute the actual metadata sink, allocator, grouped projection
and SeriesRef resolver without Qt/DB/network side effects. Five initial failures
prove late-series alias theft and subset wrong-card updates. Covers exact paths,
raw-number/alias collisions, implicit primary, other studies, reverse arrival,
separate tab owners, cine file/frame counts, repeated UID-less records and corrupt
prior maps. 181 focused plus 107 adjacent passes, exit 0. GUI acceptance pending;
not proof of catalog-first latency or a generic revision-aware card-upsert contract.

## Local metadata route / unnecessary manifest scan (2026-09-16)

`code/ui_services/test_local_pixel_inventory_reuse.py`: 24 synthetic cases cover
shared sequential/concurrent pixel-fact probes, changed/added/deleted/replaced
files, mutation during parsing, errors, expiry/eviction, exact-path separation,
blank-path safety, selective header values, pixel tag kinds, five transfer syntaxes,
undefined-length sequences, aggregate log privacy and both actual Home/patient
projection methods with isolated DB/PNG boundaries. Six initial failures; expanded
offline/import/multiframe/cine/color/UID suite: 181 passed, three unavailable
clinical-fixture skips, exit 0. No pixel decoding or packaged/GUI acceptance claim.

`code/ui_services/test_local_series_info_gate.py`: 18 cases execute the actual
metadata-route condition without importing Home/Qt or accessing the clinical DB.
Cover Local short-circuit, unchanged other-mode/growth/completeness verdicts and
storage-error semantics. Five pre-fix failures; 77 focused/adjacent passes, exit 0.
This is branch evaluation-order coverage, not whole-viewer GUI acceptance; the
fresh-source Local/Server workflow and matched latency check remain pending.

## Shutdown admission and completion observations (2026-09-15)

`code/system/test_lifecycle_shutdown_observation.py`: 12 synthetic cases for nested
and concurrent shutdown, guard restoration, LIFO/error/reuse compatibility, strict
completion semantics, probe failure/duration separation and no retained owner closure.
`code/cloud_consultation/test_poller_lifecycle.py`: queued finished delivery, retired
app-owned producer aggregation and main registry wiring. `test_shutdown_startup_cleanup.py`
pins intent logging before listener stop, without a fabricated drain claim. Twelve
fail-before cases across these files; 105 focused passes / four opt-in build
deselections, exit 0; 465 mirrors match. Fresh-source exit and native-crash gates OPEN.

## Process-exclusive native capture / consumer cutover (2026-09-15)

`code/system/test_native_fault_isolation.py`: 19 synthetic boundary cases, including
two real hidden Python child tracebacks (not deliberate crashes), PID reuse, exclusive
creation/collision refusal, frozen-flag/failed-enable handling, legacy/new-child
discovery, publication retry, loss of previously observed data, header identity and
filter/dashboard/native-GUI helper compatibility and enable-before-ready publication.
Six initial failures and three subsequent fail-before guards. 120 focused/adjacent passes,
four build-marked cases deselected; 465 mirror pairs match. The final publication-order
change postdates the source smoke and needs the next fresh run. The smoke is separate from
still-open shutdown and original crash-prevention acceptance.

## MCP native-health evidence and assertion integrity (2026-09-15)

`code/system/test_control_native_health.py` (15 cases) and
`code/system/test_native_fault_probe.py` (17 cases) cover actual health assertion
failure, cumulative limits, missing/replaced/partial/oversized source, exact
capture-start PID and same-process liveness, watchdog/Python/Windows record counts,
off-app log reads and non-certification of retrospective time windows. Seven initial
scenario failures; 93 focused/adjacent passes afterward. Synthetic files only.
The external read-only live smoke is not a patient GUI or crash-prevention pass.

## Native diagnostic record integrity (2026-09-15)

`code/system/test_native_fault_filter.py`: 20 synthetic guards for header-before-
stack association, COM exclusion without losing other fault/watchdog stacks,
session context without PID inference, unknown/truncated/CRLF preservation and
source/output alias protection. 12 initial failures; 42 adjacent passes afterward.
Offline diagnostic utility only; no clinical log fixtures or deliberate crashes.

## Download file-count and retry-folder boundary (2026-09-15)

`code/download_manager/test_series_file_completion.py`: 23 synthetic cases;
known-count incomplete responses fail, duplicate progress is unique, plain/gzip
bytes and resumable files survive, one final scan is off-loop, cancellation wins,
and real coordinator retries keep the first UID-scoped collision-aware folder.
12 socket failures and 2 coordinator failures before their respective fixes;
217 focused/builder passes afterward. Not full SOP-manifest verification or GUI
acceptance. See `docs/reports/DOWNLOAD_FILE_COUNT_GATE_2026-09-15.md`.

## Download socket response boundary (2026-09-15)

`code/download_manager/test_socket_response_framing.py`: 38 synthetic cases for
exact partial-prefix reads, valid broadcast bursts, consecutive persistent-socket
replies, elapsed flood/header budget, unchanged slow-body/UTF-8 payload handling,
cancel/error stream retirement and request/connect lock ownership. Includes a real
local socketpair exchange. Initial 31 failures; 189 expanded passes plus 5 builder
passes after correction. Old missing encoding/payload helper tests remain baseline
debt; the obsolete configurable-count assertion is not this new elapsed policy.
See `docs/reports/DOWNLOAD_SOCKET_RESPONSE_REVIEW_2026-09-15.md` for the live gate.

## Browser opening notice and input gate (2026-09-15)

`code/web_browser/test_browser_launch_notice.py`: 12 synthetic real-Qt guards for
pre-import paint, synchronous widget return, recursive/queued input, normal/error
recovery, existing/disabled modules, parent deletion and preserved control state.
Four initial failures preceded correction. 160 adjacent passes and one mirror
parity pass do not replace first-open native GUI acceptance. See
`docs/reports/WEBENGINE_OPEN_WAIT_STATUS_2026-09-15.md` (OPT-22).

## Consultation poller lifecycle (2026-09-15)

`code/cloud_consultation/test_poller_lifecycle.py`: 15 real-Qt synthetic-data guards
for delayed start cancellation, stop/restart and queued generations, nonblocking
cooperative cancellation, owner-thread delivery and finished-worker deletion,
identity retirement, notification reentrancy and existing LIFO shutdown integration.
See `docs/reports/QT_POLLER_LIFECYCLE_2026-09-15.md`; code proof is not source GUI
acceptance or proof that all application workers have drained.

## Qt signature import race (2026-09-15)

`code/system/test_pyside_signature_guard.py` reproduces transient module removal
against installed PySide6 code and guards snapshot validation, cached mapper/parser
binding, initializer/error semantics, version gate and real Qt isolated smoke.
`code/ui_services/test_pipeline_thumbnail_preparation.py` also checks exact queue,
scan and GUI-delivery timing decomposition. See the Qt signature report in docs/reports.

## Eagle Eye Alignment View (2026-09-14)

`code/ai_imaging/test_eagle_eye_alignment_relative_length.py` checks the explicit
longer-limb percentage denominator, common-scale invariance, pixel aspect without
millimeter calibration, mirrored laterality and widget/PDF recalculation.

`code/ai_imaging/test_eagle_eye_alignment_references.py` checks reference coverage,
source-tagged ranges versus classification bands, pediatric/unknown-age context,
uncalibrated MAD comparability, isolated reference manifests, and UI consistency.

`code/ai_imaging/test_eagle_eye_alignment_pdf.py` verifies explicit primary-series
identity, stale-result invalidation, automatic draft PDF, three-page image evidence,
shared Brain page furniture, calibration and atomic report publication.

`code/ai_imaging/test_eagle_eye_alignment.py` covers signed bilateral geometry,
obtuse angles, calibration/units, DICOM identity and photometry, review
invalidation, cancellation, disposal and private exports.
`code/builder/test_eagle_eye_alignment_payload.py` covers sealed assets,
allowlisted staging, local-use versus distribution acceptance and edition ownership.
See [implementation evidence](../docs/modules/EAGLE_EYE_ALIGNMENT_VIEW.md).

## Eagle Eye white-matter lesion workflow (2026-09-14)

`code/ai_imaging/test_eagle_eye_lesions.py` covers physical voxel-volume counting,
26-connected components, invalid mask/geometry rejection, study identity before
model access, mandatory paired input and quoted Windows registration paths.
`code/builder/test_eagle_eye_lesion_payload.py` covers hash/acceptance gates,
manifest-only staging and Standard edition never copying lesion bytes. Adjacent
workflow and edition tests cover the enabled function and separate payload.
Source live GUI and clinical qualification are separate from these code guards.

## Thumbnail card-local effect lifetime (2026-09-14)

Related startup preparation guard: `code/ui_services/test_pipeline_thumbnail_preparation.py`
has 18 synthetic cases for off-thread listing, exact cache-hit/miss routing, snapshot reuse,
duplicate start coalescing, prepared layout before first-series arrival, close/identity/cancel
rejection, failure handling, grouped skip and exit-before-cleanup. Real Qt/qasync tests verify
timer responsiveness during slow I/O and discard delivery after native owner deletion. No live
DB/clinical files. Five original fail-before cases and one adversarial layout failure; source GUI
and runtime KPI recapture remain independent gates. See canonical OPT-60.

`code/ui_services/test_thumbnail_card_effect_lifetime.py`: 14 synthetic real-Qt guards for
superseded Ready/hide callbacks, animation parenting/stopping, terminal late setters, manager
reset/dispose and live-sibling independence, native deletion, retained-label snapshot, normal
timing, bounded timers, running priority flash and pending/retry label transitions. Seven
corrected baseline failures / one pass; two adversarial stuck-label failures corrected during
implementation. Expanded gate: 441 passed / 1 existing opt-in GUI KPI skip, exit 0; 462 mirrors
match. Source GUI requires a launch newer than the card-effect patch; not a crash reproduction.

## Thumbnail manager callback retirement (2026-09-14)

`code/ui_services/test_thumbnail_manager_retirement.py`: 17 synthetic real-Qt guards for reset
discarding queued progress/border work, latest-value coalescing, old same-key card rejection,
idempotent terminal disposal, independent theme receivers, bound-owner release, queued-image
rejection, deleted native manager, callback reentrancy, delayed-payload release, patient-exit
ordering and weak Home-owner integration with/without retained native cards. Seven initial
failures; two additional Home guards failed before wiring. A final native-destruction guard
exposed invalid-resource disposal, now corrected. Final expanded gate: 424 passed /
1 existing GUI skip, exit 0 (includes 17 import/overlay guards). Live requires a new source run.

## Same-identity Home small refresh swap (2026-09-14)

`code/ui_services/test_home_small_refresh_swap.py`: 16 synthetic real-Qt guards for paint-gap
avoidance, same ordered known action identities, input deferral, supersession, explicit clear,
unknown/changed identities, member/order changes, large/progressive policy, coalescing, old-action
rejection, preparation-failure retry and grouped duplicate-number/unnamed series. Three baseline
failures; one additional error-path failure caught during implementation. Expanded: 390 passed /
1 existing GUI skip, exit 0. Separate import/overlay status recheck: 17 existing guards pass.
Live blocked on fresh source/test bridge; offscreen evidence is not GUI acceptance.

## Home render owner retirement (2026-09-14)

`code/ui_services/test_home_render_owner_lifetime.py`: 10 real-Qt guards, synthetic metadata
and in-memory pixmaps only. Clear and progressive-to-immediate release old manager/card wrappers;
retained callbacks do not own/address deleted panels; current exact identity/deferred delivery,
queued retirement, sibling panels, normal timer finish, 420-frame label and repeated cleanup
remain correct. Test-only weakref/GC probes, no production forced collection. Before: 4 failed /
3 passed, exit 1. Expanded: 374 passed / 1 existing opt-in GUI skip, exit 0. Fresh-source live pending.

## Patient-tab external signal lifetime (2026-09-14)

`code/ui_services/test_patient_tab_signal_lifetime.py`: 16 guards exercise the production
creation-time wiring and explicit-exit wrapper with real Qt publishers/receivers, without the
clinical DB/viewer graph. Covers raw-key routing, primary completion filter, close/delete,
wrapper collection, GUI-thread delivery, queued close/rebind, independent subscribers/tabs,
publisher/Home destruction, optional managers, and priority-before-lazy-DM order. Before: 6
failed / 2 passed, exit 1. Expanded gate: 364 passed / 1 pre-existing GUI-only KPI skip, exit 0.
No forced collection in production; test-only collection observes wrapper reachability.
17:57 fresh-source native open/close/reopen passed for one two-study sample with exact identity
and visible pixels; real completion/priority live checks remain pending. No test changes in that
lap; wrapper collection and queued-event rejection retain synthetic QObject evidence only.

## Home search preview retirement (2026-09-14)

Separate live receipt: 16:35 source session passes sampled Server/Local empty-preview retirement,
Server reselection and native new/reused exact-series open. Extended pins/advanced overlap/Offline
Cloud remain code-only. Automated gate remains 302 passes; no tests changed during the live lap.

`code/ui_services/test_home_search_preview_retirement.py`: 18 synthetic guards execute the real
search service with isolated network/local providers and real Qt table/panel/timers, plus extracted
production selection predicates and task cleanup (no full Home/clinical DB graph). Cover normal
and advanced empty search; cancellation/supersession; matching/nonmatching pins; pending pin row
movement; explicit-retirement late-response rejection and reselection; old cancelled/failed task
ownership; Local/Offline/nonempty clear; queued old render. Main fail-before: 7 failed / 4 passed;
two cleanup guards separately failed before correction. Final adjacent gate: 302 passed, exit 0.
`test_clear_table_crash_guard.py` follows the shared helper while retaining pre-clear generation
and no-nested-event assertions. Fresh-source live verification remains separate and pending.

## Home queued-render retirement (2026-09-14)

`code/ui_services/test_right_panel_render_lifecycle.py`: 16 synthetic Qt guards for clear before
initial render, explicit/implicit-generation input retries, late progressive ticks, same-payload
re-request, replacement/coalescing, panel destruction and child-timer destruction. Controlled
scheduling exercises real renderer methods; teardown cases use real Qt events/timers. No clinical
DB/network/pixel access. Before: 9 failed / 4 passed. Final adjacent gate: 197 passed, exit 0.
`code/test_right_panel_input_sync_guard.py` retains its input-gate/defer-bound/stale assertions
with a scheduler fake that accepts Qt's receiver-context overload. Source-live is a separate gate.

## Home command selection fidelity (2026-09-14)

`code/echomind/test_home_selection_fidelity.py`: 18 synthetic Qt guards for current-row selection,
current metadata authority, missing/foreign/hidden/ambiguous results, grouped study membership,
sorted rows, debounced supersession, active-search and GUI-thread checks, stale-cache rejection,
synchronous result replacement and no I/O/nested event pumping. Uses production debounce methods
without constructing the full clinical table or opening the live DB. Initial 15 cases failed
before correction. `test_adapter_contracts.py` pins delegation and unchanged argument shapes.

## Home thumbnail explicit series open (2026-09-14)

`code/ui_services/test_home_thumbnail_open.py` and `test_home_series_action.py` cover cache
identity/frame preservation, ambiguous/suffixed keys, worker projection, real Qt double-click
versus single click, normal async open/reuse, last-intent-wins, metadata/layout readiness,
GUI-thread consumption and supersession. The cache-to-card-to-service integration is synthetic;
it does not replace live rendered UID checks after a source restart. Existing Local projection,
metadata, Windows input-dispatch and stateful multi-study guards remain mandatory neighbors.

`test_home_series_action.py` also guards semantic render coalescing: changed same-path counts,
description, modality, protocol, anatomy and group label refresh the real panel; a real card
updates from 2 to 420 display images without changing its object count. Alias-equivalent
projections still coalesce; signature construction performs no file I/O or pixel retention.
Rendering and comparison share the normalizer covered by `test_right_panel_metadata_contract.py`.
Eleven new cases: 9 failed / 2 passed before; all pass afterward. Full five-file focused gate:
68 passed. Source-live acceptance of this new slice remains separate.

## Eagle Eye dataset templates and case forms (2026-09-13)

`code/ai_imaging/test_dataset_workspace_repository.py` and
`code/ai_imaging/test_dataset_workspace_ui.py`: 18 synthetic guards for template
editing/version retention, independent case answers, duplicate enrollment, identity
and modality binding, stale writes, required/type validation, save history, native
create/save/reopen, legacy CSV compatibility and destroyed-worker receivers. All
catalogs and study resolvers are test-owned; no live PACS database is used.

## Eagle Eye workspace entry (2026-09-11)

`code/ai_imaging/test_eagle_eye_workspace_entry.py`: 29 synthetic guards for
navigation without analysis, in-workspace function selection/cancellation,
common Brain viewer with reusable popup, study identity, duplicate-run rejection,
native result refresh, popup sizing and destruction-time worker teardown.
The 2026-09-12 UI extension covers prominent function-button sizing in all four
modes, duplicate Imaging section titles, and hidden Patient navigation with
retained callback targets and visible thumbnails.
See `docs/modules/EAGLE_EYE_WORKSPACE_ENTRY_2026-09-11.md` for pre-fix evidence.

## Printing workflow and transport (2026-09-09)

- `code/printing/test_printing_workflow.py`: study isolation, empty selection, multi-page deletion, persistent adjustments, fresh exports, pending-timer teardown, zero window level, fail-closed preview, read-only saved-page viewing, persisted header controls, composed DICOM pixels, immediate selection, background submission identity, landscape, 1x1 Scout, missing-printer status, and a synthetic Scout reference-line pixel check.
- `code/printing/test_printer_transport.py`: Calling AE, Meta SOP dispatch, returned Image Box identities, malformed-status handling, and physical OS page size. Transport and printer device are fakes; no network or print job is issued.
- `code/printing/conftest.py`: temporary DICOM/attachment/database paths plus a connection assertion preventing live SQLite access.
- Existing `code/printing/test_printing_series_repository.py` remains in the focused suite.


## Eagle Eye spatial packet geometry (2026-09-08)

`code/ai_imaging/test_eagle_eye_spatial_packet.py`: seven synthetic guards for
physical order, complete membership, shared frames, separate groups, finite-field
plane intersections, pixel preservation, irregular sampling, and oblique/cropped
anisotropic geometry. All seven pass. Scope: independent benchmark utility.


## Eagle Eye Gemini company route (2026-09-08)

`code/ai_imaging/test_eagle_eye_gemini_route.py`: five fail-before guards for
Gemini at every base/atomic dispatch, sampling inheritance and call-time global
model pins with stage-specific precedence. All five pass after correction.


## Canonical Git release route (2026-09-07)

`code/git/test_release_manager.py` protects the fixed three-repository/two-branch
target matrix, clean reviewed release commits, version and release-record parity,
fast-forward-only publication, path-only secret reporting, annotated tag identity,
explicit full-SHA execution confirmation, and complete synchronization receipts.
`code/builder/test_release_candidate_packaging.py::test_canonical_candidate_cli_requires_git_sync_receipt`
prevents a full installer matrix from starting before the exact clean commit is
published and read back. `code/builder/test_canonical_build_runbook.py` keeps
`RELEASE.md` and `BUILD.md` as the only human/agent entry points. The focused
release/build boundary passes 38 tests.

## Canonical build route (2026-09-06)

`code/builder/test_canonical_build_runbook.py` keeps `BUILD.md` as the single
human/AI entry point for the six-installer matrix. It requires every prominent
agent and backend build document to route there, pins the two canonical output
folders and six edition filenames, distinguishes source/internal/full lanes, and
rejects the known unsafe speed shortcuts: parallel full-core builds, removing
Slicer to reduce size, stale artifact reuse/renaming, and automatic executable launch.
The documented pre-build selection passes 114 tests. Its narrower canonical
runbook/profile/candidate/legal boundary passes 46 tests. The combined builder
plus Git release directory passes 159 tests with one known generated-stage parity failure:
the development checkout's `builder/output/stage` predates current sanitized
`echomind_settings.json` and `patient_table_sort.json`. Do not edit that generated
stage as source; a fresh isolated candidate must regenerate it.

The 2026-09-10 follow-up fixes the meaning and recovery of that same route.
`test_coordinator_cli_cannot_redirect_final_installer_outputs` removes the public
final-folder redirect. `test_nuitka_release_resume_never_enters_diagnostic_stages`
keeps full-candidate resume inside stages 0/6/7/8/9/10, and
`test_candidate_resume_skips_completed_python_and_resumes_nuitka` proves the root
coordinator retains a complete PyInstaller backend, recovers Nuitka, and reruns
coherence. The canonical runbook/candidate/profile selection passes 60 tests.

## Release candidate staging capacity (2026-09-06)

`code/builder/test_distribution_profiles.py::test_compact_stage_never_copies_excluded_offline_model_bytes`
ensures Standard and ARM64-emulated staging omit the Eagle Eye offline lumbar
model before filesystem copying begins. `code/builder/test_release_candidate_packaging.py::test_candidate_stops_before_nuitka_when_required_python_backend_fails`
also records and verifies that local candidate packaging uses the candidate
workspace drive rather than the smaller canonical installer-output drive.

## Eagle Eye physical side and neural coverage (2026-09-05)

`code/ai_imaging/test_eagle_eye_neural_contract.py`: 16 guards for canonical axial
display, immutable sagittal source membership/midline during side correction,
complete bilateral recess/root/foramen observations, finding consistency, same-level
and same-side evidence, not-assessable review, and actual-card header authority.
The atomic dispatch integration guard also verifies persisted seven-compartment
coverage and the separate recess diagnostic handoff. Full AI Imaging: 1,063 passed,
8 optional skips and 8 existing xfails; direct exit code 0, reruns disabled.

## Eagle Eye Brain foundation (2026-09-05)

DICOM report organization: `code/ai_imaging/test_eagle_eye_brain_patient_report.py`
covers age-at-exam and DICOM precedence, consistent/mixed series identity, institution
and patient fields, and repeated brand/ID/page count/review footer on every PDF page.

Medial temporal report follow-up: 65 tests pass across the three Brain test files.
`code/ai_imaging/test_eagle_eye_brain_medial_temporal.py` verifies missing-side
semantics, asymmetry sign, absence of inferred MTA/diagnosis and immutable local
hippocampal image evidence selected by label names.

Age/sex reference and report follow-up: 63 guards pass across the original file
and `code/ai_imaging/test_eagle_eye_brain_reference.py`. Protects unspecified or
invalid demographics, unavailable candidate scores, asymmetry sign/units/zero
denominator, local PNG/oblique geometry and immutable completed-job report export.

Protocol follow-up: 42 guards pass. Explicit T2/FLAIR-as-T1 and T1-as-FLAIR
metadata contradictions are rejected; correctly identified FLAIR remains accepted.
The two T1 mismatch guards failed on the preceding implementation. Missing metadata
does not establish sequence identity and still requires operator review.

Follow-up: 38 guards pass, including Qt table unit-header repetition and long
parcel-name layout. The installed SynthSeg 2 standard-profile synthetic service
probe passed through headless Slicer; this is execution evidence, not clinical QC.

`code/ai_imaging/test_eagle_eye_brain.py`: 37 synthetic guards for bounded model
settings, independent geometry/units, malformed model CSV, unavailable normative
scores, metadata removal, cancellation, atomic completion, lazy UI and real PDF
rendering/text. `tools/dev/run_brain_volumetry_probe.py` separately verified the
dedicated Slicer adapter with known oblique masks. See
[`Eagle Eye Brain status`](../docs/modules/EAGLE_EYE_BRAIN_VOLUMETRY.md) for model
provisioning, clinical and release limitations.

Every guard test in `tests/code/system/` is paired with one row of `docs/plans/architecture/REGRESSION_CATALOG.md`. This index tells you, for each test file: **what it protects, what bug it would re-introduce if removed, and where to read the audit report**.

For an alphabetical layout map (where tests live), see [`README.md`](README.md). For the 5-minute onboarding, see [`QUICKSTART.md`](QUICKSTART.md).

---

## How to use this index

Release candidates: `code/builder/test_release_candidate_packaging.py` protects
curated resources, mandatory backend edition parity, no automatic workstation
launch, current-source version coherence, codec entry points, and isolated source
snapshots. See `../docs/releases/VERSION_3.6.5_BUILD.md`.

`code/builder/test_distribution_profiles.py` requires Standard and ARM to retain
the complete standard Advanced MPR/Slicer runtime while physically excluding only
the Eagle Eye offline-lumbar model and its Slicer module. It also pins independent
Inno runtime/model availability macros and a version-bearing setup title.
`code/test_home_info_panel.py` requires every Information edition version line to
follow the running Qt application version and the fallback to match
`pyproject.toml`; the former stale-version quarantine entry was removed.
`code/cd_burner/test_lite_viewer_autobuild.py` and
`code/builder/test_windows_qt_icu_hygiene.py` keep foreign app-local ICU DLLs
out of both PyInstaller runtimes so they cannot shadow Windows ICU and break
`PySide6.QtCore`; Qt WebEngine's separate `icudtl.dat` remains present.
The distribution-profile guards also require an isolated candidate to receive
an explicit backend-specific canonical installer destination; a lookalike path
with the same folder suffix is rejected.
`code/builder/test_eagle_eye_brain_payload.py` and the internal Eagle Eye case in
`test_distribution_profiles.py` require portable packaging to omit TensorFlow
compile-only headers and allow local install-QA staging without falsely requiring
or copying a redistribution receipt. Release-mode receipt validation remains
fail-closed.
The asset-cache guard keeps SHA-256 verification deterministic for the 4 GiB
release cache when Windows rejects `hashlib.file_digest()` for a large file;
it uses bounded reads without weakening the manifest size or digest checks.

Recovery guards in the same file cover Inno path-budget staging, bounded Nuitka
memory settings, fatal compiler output, owned-child timeouts, and source-identity
validation before reusing an already compiled core. They also require the
four-hour heavyweight-build idle boundary, Stage 6 MSVC `/Od` override, exact
timeout cache boundary, partial-distribution cleanup, and resume from the recorded
failed release stage. The local candidate is fail-fast across required backends:
a Python failure marks Nuitka skipped instead of starting a multi-hour compile.
See the 2026-09-05 OPT-53 recovery rows in the regression catalog.

The same candidate guard file also parses the patient-sidebar coroutine and rejects
comprehensions inside async `finally` cleanup. Nuitka 4.1.3 on Python 3.13 otherwise
terminates Stage 6 with its internal `listcomp_1__.0_clone` assertion. The guard
failed four times before the cleanup was expressed as an equivalent explicit loop.

`code/builder/test_codec_bundling.py` protects the non-GPL compressed-DICOM
decoder contract: GDCM and pyjpegls replace pylibjpeg-libjpeg, OpenJPEG/RLE
entry-point metadata remains present, GDCM XML/native resources are declared,
and the release gate covers every required transfer syntax. The real compressed
round-trip boundary is in `code/test_import_pipeline_dicom.py`.
`code/builder/test_installer_legal_notices.py` requires both the EULA and the
3.6.5 third-party inventory to be installed under `Legal`. See
`../docs/reports/V3.6.5_FINAL_RELEASE_READINESS_2026-09-05.md`.

When you touch a subsystem:

1. Look up the subsystem in [`../docs/INDEX_BY_SUBSYSTEM.md`](../docs/INDEX_BY_SUBSYSTEM.md).
2. Identify which guard tests cover it.
3. Run them BEFORE your change so you have a green baseline.
4. Run them AFTER your change so any regression is loud.

When you ship a fix:

1. Add a row to `docs/plans/architecture/REGRESSION_CATALOG.md`.
2. Add a guard test to `tests/code/system/test_<scope>_guard.py`.
3. Add a row to this index.
4. Update the cumulative count in `docs/AUDIT_2026-05-28_OVERVIEW.md`.

---

## System-level structural guards (`tests/code/system/`)

| Test file | Guards | What it protects |
|---|---|---|
| `test_2026_05_27_regression_guards.py` | **15** | GetStudyInfo 6.8 s stall (4 probe guards), Eagle Eye COM 0x8001010d (3 mg-mirror QTimer guards), bulk-download UI freeze (5 ThreadPool prefetch guards), compile gates (3) |
| `test_kpi_schema.py` | KPI registry integrity | Each KPI key registered + threshold ordering correct |
| `test_diagnostic_logging_catchall.py` | **7** | `app.log` catch-all handler (download/viewer/db component routing + 4th catch-all for everything else); without this, UI/home events vanish |
| `test_hp_search_logging_guard.py` | **5** | Error paths in `_hp_search.py` use `_logger.error`, not `print()` |
| `test_hp_patient_open_logging_guard.py` | **4** | Error paths in `_hp_patient_open.py` bypass the `print → _logger.debug` rebind; success traces stay at debug |
| `test_responsive_layout_qscrollarea_guard.py` | **4** | `wrap_in_horizontal_scroll` uses `setSingleStep` not the bogus `setHorizontalScrollMode`; `QAbstractScrollArea` not re-imported |
| `test_titlebar_userinfo_clamp_guard.py` | **7** | TitleBar QFrame + user_info_container both have `setMaximumHeight` + Fixed vertical size policy; 84 / 70 px floors preserved |
| `test_thumbnail_card_height_guard.py` | **6** | Right-panel card height 215 px so server-desc + image-count labels coexist; progress overlay y-center recomputed for new height |
| `test_ui_polish_2026_05_29_guard.py` | **4** | Title bar maxHeight 110, right-panel grid vert spacing 14 + right margin 22, patient table `setShowGrid(False)` |
| `test_patient_tab_strip_width_guard.py` | **6** | tab_area carries stretch=1 (claims ~2/3 title bar); chip strip max_height ≥ 80 (10 px buffer); no outer trailing addStretch; **inner title_bar_tabs_layout has trailing addStretch(1) so chips left-pack inside QScrollArea (round-4)**; `_add_title_bar_tab_widget` uses `count()-1` to insert before the stretch |
| `test_max_patient_tabs_message_guard.py` | **3** | "Maximum Patient Tabs Reached" message in `_hp_modules.py` interpolates `MAX_PATIENT_TABS` (no hardcoded digit); constant is imported; `add_patient_tab` docstring doesn't pin a stale numeric literal |
| `test_right_panel_reserved_height_guard.py` | **2** | `RightPanelWidget.THUMBNAIL_BOX_HEIGHT` is coupled to `ThumbnailManager.create_thumbnail_widget`'s real card height (215) by source-parse; constant has a comment pointing at thumbnail_manager.py as source-of-truth |
| `test_patient_click_double_click_guard.py` | **4** | `_on_patient_clicked` does NOT call the redundant `highlight_selected_row(row)` that broke double-click detection; `itemClicked` + `itemDoubleClicked` signals stay wired to their handlers; table keeps `SelectRows` behaviour so Qt's native selection still fires |
| `test_ui_stall_boundaries_2026_09_02.py` | **8** | Measured UI-stall boundaries: no eager retired gRPC import, no completed-tree root stylesheet, asynchronous Agent Gateway startup, off-thread patient completeness and Zeta schema work, asynchronous WAV flush, lazy Eagle Eye secondary tabs, and off-thread DICOM probing. |
| `test_import_registration_layout_crash_guard.py` | **4** | Large Local import registration stays on the managed worker boundary, preserves per-study results and exact DICOM bytes while writing only an isolated local index, never accesses the server, and viewport layout construction cannot pump a nested Qt event loop. |
| `test_right_panel_min_width_guard.py` | **2** | `RightPanelWidget.setMinimumWidth(N)` is large enough that at the floor there's ≥22 px gap between the 190 px card right edge and the AlwaysOn 12 px vertical scrollbar (so the dotted border can't visually clip into the scrollbar); constant has a geometry comment so future agents don't lower it |
| `test_system_stress.py` | (env-gated) | Multi-process stress patterns (skips in sandbox) |

**Subtotal: 81 system-level guards across 15 active files.**

---

## EchoMind / Command Layer (`tests/code/echomind/`)

Adjacent Eagle Eye coverage guard (2026-09-05):
`tests/code/ai_imaging/test_eagle_eye_extended_coverage.py` protects seven-group
mapping, complete context membership, unchanged lumbar numbering, context-only
diagnostic exclusion and explicit review notices (12 guards).

`test_explicit_provider_selection.py` (2026-09-05): 21 synthetic guards for default
company routing, explicit direct opt-in, no invented endpoint, no key-override route
switch, explicit Eagle Eye models, retryable preflight failure, and Settings form/save
behavior. Full affected selection: 205 passed, 1 existing xfail.

| Test file | What it protects |
|---|---|
| `test_command_envelope.py` | Pydantic `CommandRequest` / `CommandPlan` / `CommandResult` round-trip with the legacy TypedDict |
| `test_adapter_registry.py` | `AdapterRegistry` dispatch, action mapping, scalar-payload normalization |
| `test_command_bus_unit.py` | `CommandBus.parse / execute / dispatch / dispatch_async` |
| `test_system_adapter.py` | `SystemAdapter` psutil probes (resources, process count, native faults, idle CPU) |
| `test_download_adapter.py` | `DownloadAdapter` pause / cancel / list / statistics |
| `test_module_adapter.py` | `ModuleAdapter` open_module / convenience aliases / launcher-failure handling |
| `test_viewer_adapter.py` | **Structural read-only enforcement** — no write-verb actions exist; multi-study flag propagation; offset-key preservation |
| `test_bus_factory.py` | `build_command_bus()` wires adapters correctly given different launcher dicts |
| `test_kpi_auto_record.py` | `hook_bus(bus)` auto-records `<action>.elapsed_ms` to the sink |
| `test_module_catalog_coverage.py` | Catalog vs CommandBus drift reporter; INFRASTRUCTURE_ACTIONS ⊥ catalog actions invariant |
| `test_credential_obfuscation.py` | EchoMind center access codes and provider credentials never ship as plaintext; access-code-derived AES-GCM envelopes open only the selected center; the protected owner-approved demo is available by default; tampering and missing Company Server 3 entitlement fail closed |
| `test_entitlement.py` | TEST is an end-user demo, authenticates by default, and reaches the same company-backend authorization chokepoint; explicit opt-out removes only the demo; legacy deployment flags remain compatible; direct-user backends remain independent |

The 2026-09-10 demo-center selection initially produced three targeted failures
(default registry, validation, and entitlement). The corrected focused and adjacent
selection passes 197 tests with 15 live/optional cases deselected; the protected
registry and plugin mirror contain no plaintext demo fixture.

**Subtotal: 14 unit-test files.**

---

## GUI tests (`tests/gui/`)

**Acceptance rule (2026-09-14):** each runtime fix/Unify slice needs both direct automated tests
and a live source-GUI pass. See
[`AGENT_CONTROL_AND_TESTING_GUIDE.md`, section 0](../docs/for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md)
for discovery of `aipacs-control` / its existing CLI, safe case selection and the receipt.
Tests in this folder may use fakes/offscreen Qt or skip without a live app: location/name is
not proof of live execution. MCP series switching bypasses Home-card click and OLE input;
run the actual affected input boundary plus render/identity checks. Report BLOCKED separately.

### `pywinauto/` — Windows UI Automation

| Test file | What it protects |
|---|---|
| `test_eagle_eye_dragdrop.py` | **The canonical 0x8001010d COM crash test** — only test that fires real Win32 OLE drag-drop messages. Requires source build + `_verify_source_build()`. |
| `test_close_no_zombie.py` | App fully exits — no orphan process in Task Manager after close |
| `test_open_close_cycles.py` | N-launch restart-to-ready KPI + zombie process leak (env-gated `AIPACS_CYCLE_LAUNCH_CMD`) |
| `test_thumbnail_pixel_isolation.py` | Pixel-diff: cross-patient thumbnail leak at the rendered-output level |

**Subtotal: 4 pywinauto tests.**

### `echomind_driven/` — CommandBus-driven scenarios

| Test file | What it protects |
|---|---|
| `test_command_bus_smoke.py` | Bus fixture works end-to-end with a `FakeHomeAdapter` |
| `test_scenario_1_patient_open.py` | Click-to-thumbnail latency KPI (`patient_open.elapsed_ms`) |
| `test_scenario_3_bulk_download.py` | 20+ patient enqueue speed |
| `test_idle_resource_budget.py` | `proc.idle_cpu_pct` + `crash.native_fault_count` budgets |
| `test_dm_status_workflow.py` | Status → list → cancel via `bus.execute` |
| `test_cross_patient_thumbnail_isolation.py` | Typed regression: patient A's thumbnails must not appear on B |
| `test_long_session_workload.py` | RSS-growth + leak KPI across hours (env-gated) |

**Subtotal: 7 bus-driven scenarios.**

### `live_walkthroughs/` — one-off agentic scripts

- `_verify_source_build.py` — pre-flight: refuses to run against the frozen exe
- `extract_2026_05_27_kpis.py` — log → PASS / CHECK extractor

---

## KPI machinery (`tests/_kpi/`)

| File | Purpose |
|---|---|
| `schema.py` | 42 registered KPI keys across 13 workflows |
| `collector.py` | `KpiCollector` + `kpi` pytest fixture + `hook_bus(bus)` auto-recording |
| `reporter.py` | CLI: `last` / `trend` / `diff` / `summary` over `user_data/test_kpis/<run>.jsonl` |
| `baseline.json` | Last-known-good values per key |
| [`README.md`](_kpi/README.md) | How to add a new KPI |

**Tools that consume this sink:**
- `tools/kpi_dashboard.py` — framework health snapshot
- `tools/kpi_html_report.py` — self-contained trend report
- `tools/kpi_build_compare.py` — cross-build divergence detector

---

## Domain-specific code tests (`tests/code/<domain>/`)

The `tests/code/` directory has 26 domain folders; **183 files total**. Highlights:

| Domain | What it covers |
|---|---|
| `architecture/` | Module boundary contracts (DM widget responsibilities, etc.) |
| `database/` | Connection pool, schema migration, test isolation |
| `download_manager/` | DM widget init contract, network paths, queue ordering |
| `fast/` | FAST viewer mode primitives (pydicom backend) |
| `fast_viewer/` | FAST viewer integration |
| `viewer/` | Standard viewer pipeline, multi-study state |
| `network/` | Socket / gRPC client behavior |
| `ui_services/` | Patient table, search-sort, sidebar rendering |
| `runtime/` | Runtime profile (FAST vs Advanced), GPU detection |
| `startup/` | Boot ordering, env-var contracts |
| `utils/` | Path resolvers, structured logging helpers |
| `system/` | **Cross-cutting structural guards listed above** |
| `echomind/` | **Command Layer unit tests listed above** |

For each domain, the matching docs live under `docs/` — start at [`../docs/INDEX_BY_SUBSYSTEM.md`](../docs/INDEX_BY_SUBSYSTEM.md).

---

## 2026-08 additions — startup, warm-up and thumbnail guards

These live outside `tests/code/system/`, so they are easy to miss from the
system table above. Each pairs with a 2026-08 row in the regression catalog.

| Test file | Guards | What it protects |
|---|---|---|
| `code/web_browser/test_prewarm_recency_veto.py` | **13** | The input filter SURVIVES the warm (`_finish_watch(warm=True)` must not remove it) and `_on_construct` re-checks input recency before blocking the GUI thread. Removing these re-introduces the 19 s double-click freeze. |
| `code/system/test_browser_prewarm_idle_gate.py` | +3 | The pre-warm is **opt-in**: only a literal `AIPACS_BROWSER_PREWARM="1"` enables it, and the adaptive used-marker still gates on top. Removing these re-introduces the 72 s freeze. |
| `code/web_browser/test_prewarm_idle_gate.py` | +4 | Warm the **default profile**, never a throwaway `QWebEngineView` + `setUrl`; the DLL file warm stays **name-scoped** and budget-capped. |
| `code/viewer/test_series_file_warm.py` | **18** | The patient-open warm stays read-only, daemon-threaded, budget-capped, kill-switchable, and refuses blank/duplicate work. Server and indexed Local series retain raw head warming; unverified Local series may prime shared positive pixel facts, while the inventory consumer remains authoritative for version/revision, counts, persistence and failure/non-pixel re-probe. |
| `code/viewer/test_disk_pixel_cache_async_init.py` | **10** | `initialize()` stays synchronous for direct callers; only the singleton goes background. Includes a threaded writer-vs-scan race and the LRU-order-after-merge invariant (the index's ORDER is the eviction order). |
| `code/viewer/test_viewer_import_warm.py` | **8** | The import warm creates **no Qt object** (it runs off the GUI thread) and fails loudly if the windowing path stops using the numpy calls it warms. |
| `code/viewer/test_dicom_import_preview.py` | **5** | Import groups by immutable study/series UID, assigns duplicate raw numbers through the shared collision resolver, and distinguishes copied DICOM object count from pixel-bearing image count. Metadata-only SR/vendor objects remain importable but must report zero displayable images. |
| `code/dicom_media/test_dicom_vm_normalization.py` | **5** | Restores only standard textual VM>1 elements collapsed into Python-list strings; preserves clean/unreadable payload bytes, private and VM=1 text, transfer syntax, pixels and all identity UIDs; proves socket normalization precedes the atomic write and DICOMDIR export repairs only its copy. Same-study flow validation is recorded in `FLOW_CVI42_SAME_STUDY_VM_COLLAPSE_2026-09-01.md`. |
| `code/viewer/test_disk_pixel_cache_persistence.py` | **20** | The L2 cache SURVIVES shutdown (before this it was `rmtree`'d every exit and had never served a cross-session hit). Pins: persistence is the default; `AIPACS_PIXEL_CACHE_CLEAR_ON_EXIT=1` really restores the wipe; **`clear()` itself stays unconditional** so an explicit user clear always clears; the shutdown path calls `clear_on_exit()` not `clear()` (AST pin — a comment naming `.clear()` cannot fool it); and eviction still bounds a *persisted* cache, with LRU order surviving a restart. |
| `code/ui_services/test_thumbnail_active_state_and_strip.py` | **20** | **Behavioural, on real Qt widgets.** The download bar is not buried by the re-parenting `addWidget`; the red active line is stacked above it; A→B→A returns a series to the active state. A source-string pin cannot see a z-order bug — that is exactly how the buried bar survived `test_thumbnail_panel_ui_fixes.py`. |
| `code/ui_services/test_thumbnail_panel_ui_fixes.py::test_thumbnail_card_root_style_is_scoped_and_applied_before_child_tree` | **1** | The thumbnail card root style stays object-scoped and is applied before Qt children, graphics effects, and event filters exist. This guards the exact main-thread site of the 2026-09-01 Windows heap-corruption termination. |
| `code/system/test_windows_multiprocessing_visibility.py` | **7** | The bootstrap remains before `freeze_support`; direct Python may select a direct `pythonw` sibling, but supported virtual-environment source runs never select the `pythonw` redirector. A real Windows spawn child must read a shared cancellation Event without WinError 5. Frozen/non-Windows/missing-interpreter and installed-application executables remain untouched. |
| `code/viewer/test_viewport_drop_replacement.py::test_retired_fast_viewer_child_never_becomes_a_top_level_window` + `test_fast_viewer_replacement_never_detaches_layout_children` | **2** | A retired FAST preview/full-series child is hidden but remains parented until deferred deletion, and both bridge-install paths use the shared retirement authority. Prevents `setParent(None)` from turning a visible embedded viewer into a millisecond Windows top-level window during Preview -> Complete promotion. |
| `code/ui_services/test_main_footer_bar_removed.py` | **6** | The empty main-page footer stays hidden and its widgets stay alive (so `apply_theme` keeps working); fails if anyone starts writing to its labels or introduces a real `QSizeGrip`. |
| `code/ui_services/test_clear_table_crash_guard.py` | **16** | Patient-table item and widget teardown stays outside Qt model mutation: each order cell is created once, safe row/full clears use `takeItem` before `removeRow`/`setRowCount(0)`, producers respect the rebuild guard, and Local Server search does not pump a nested event loop. Includes a real offscreen Qt/Shiboken ownership check. |
| `code/ui_services/test_local_offline_contract.py` | **21** | LocalDatabase defaults to no remote resync; single-click reconcile, right-panel cache miss, grouped preview, viewer thumbnail cache miss, existing-tab focus, and local patient open return through DB/disk paths before any PACS socket access. Multi-study Local open must aggregate every study's SQLite/disk series metadata. Duplicate-SeriesNumber imports preserve exact `series_path`/`folder_key` but use a digit-only UI handle; missing PNGs rebuild from the exact folder off the GUI thread; metadata-only DICOM groups are excluded; cine cards show total frames without changing file-completeness counts; and count persistence targets `SeriesInstanceUID`. Local startup must not render collision storage stems as drag handles before authoritative projection; a new single-study Import must start that projection even when cached PNGs already exist; and the FAST parser must reject storage stems rather than reinterpret underscores as numeric separators. |
| `code/ui_services/test_visit_status_write_off_ui.py` | **2** | Patient-open colour remains immediate while the ordered SQLite write runs off the GUI thread; the `visit_status` column is owned by startup schema migration rather than an ALTER/commit inside the open handler. |
| `code/ai_imaging/test_eagle_eye_probe_enumeration.py` | **3** | Each series folder is enumerated once; the worker receives a small immutable snapshot with no patient widget, VTK object, or private metadata; live Qt state is never dereferenced by the DICOM probe worker. |
| `code/ai_imaging/test_mammography_intelligent_analysis.py` | **12** | Mammography Intelligent AI Analyze accepts only explicitly identified same-study MG objects, uniquely rebinds stale remote CSV paths through an immutable local-viewer snapshot, preserves the original detection/classification association after rebinding, rejects ambiguous identity, excludes Qt/VTK objects from worker input, confines result discovery to the attachments root, rejects unsafe source dimensions before decode, masks corrupt decoder details, builds a bounded de-identified self-cleaning evidence package, performs decode/package/network work outside the GUI thread, delegates UI behavior to a dedicated controller, and routes MG directly without changing the MRI-only Legion Consult branch. |
| `code/system/test_voice_queue_drain_on_stop.py` | **5** | Stop drains every queued audio frame before asynchronous publication; empty takes are visible; explicit delete wins even if cancellation arrives in the narrow interval during atomic replace, so a cancelled WAV cannot reappear. |
| `code/download_manager/test_overall_progress_accumulator.py` | **9** | The queue row and right-side Overall Progress remain monotonic across series, retries, delayed terminal state, and complete-on-disk resume. SeriesInstanceUID distinguishes duplicate SeriesNumber values; the authoritative downloader manifest replaces an unknown/stale queue denominator without resetting the numerator; reset starts a new generation; manifest/terminal IPC is bounded/reliable off the GUI thread; aggregate-only events do not fan out per-series viewer updates. |
| `code/ui_services/test_patient_study_set.py` | **27** | Pure patient/study/series authority, including deterministic digit-only display aliases for duplicate raw SeriesNumber values while preserving the raw number and collision folder. |
| `code/viewer/test_dicom_color_decode.py` | **12** | DICOM colour conversion plus the FAST metadata-recovery regression: an RGB/YBR single frame remains `Rows x Columns x 3` when DB metadata omits colour facts. |
| `code/viewer/test_fast_multiframe.py` | **22** | Multi-frame decode, cache, geometry and metadata expansion, including several cine objects whose DB rows omit NumberOfFrames and Enhanced MR series mixed with Raw Data Storage in either metadata order. Metadata-only objects stay preserved but never become image slices. |
| `code/viewer/test_series_ref_authority.py` | **29** | Immutable display/study/series authority; a numeric collision alias retains the original DICOM number but loads the exact suffixed storage folder. |
| `code/ui_services/test_advanced_search_routing.py` + `code/database/test_local_advanced_search.py` | **8 + 3** | Advanced Search follows the active source and preserves bounded multi-ID, normalized acquisition/import date, multi-valued modality, body part, DICOM age, and persisted physician filters in Local SQLite. Valid online physician hydration is persisted for later offline reuse; the database tests use an isolated patched `DATABASE_FILE` and cleared pool. |
| `code/ui_services/test_local_incremental_and_import_date.py` | **13** | Imported Date means the immutable first entry into this computer's Local SQLite, never acquisition date or last refresh. Single-day/preset/range queries use full-day boundaries, NULL legacy timestamps do not match, import-date queries stay Local, and reversed custom ranges are normalized in both the dialog and repository. Also retains the incremental Local-list guards. |
| `code/viewer/test_reference_line_active_viewport.py` | **17** | The ACTIVE viewport carries no reference line — it is the source and stays clean; the line goes only on the series being cross-referenced. Load-bearing pin: the source overlay is **cleared**, not merely skipped, so a line drawn while a viewport was inactive vanishes the instant it becomes active. Also pins that `AIPACS_REFERENCE_LINES_ALL_PAIRS=1` restores bidirectional lines end-to-end. |
| `code/viewer/test_text_annotation_input.py` | **25** | The Text tool ASKS what to write. Before this it stamped the literal word "Text" — the whole chain was wired except the input step. Pins: the typed string is what reaches the `TextModel`; cancel / whitespace / a raising prompt all place **nothing** and return `False`, so the tool stays armed; a bare `ToolController` still places the legacy `"Text"` (every headless tool test and the EchoMind adapter build one that way); only the TEXT tool may prompt; `controller.py` stays **Qt-free**; the Qt bridge really wires `_text_prompt_fn` (AST pin — the controller change is inert without it); the dialog is re-entrancy-guarded and releases its flag even when it raises; and both backends word the prompt identically. |
| `code/reporting/test_report_image_insert.py` | **68** | Captured viewer images can be inserted into the Medical Report Editor and survive the whole trip. Also pins study RESOLUTION: a report opened from the Reception Data tab carries a reception record with no `studyUID`, so the study is found by joining `patients.patient_id -> patient_pk -> studies.patient_fk` — `patient_fk` is a FK to `patient_pk`, NOT the DICOM PatientID, and a direct comparison returns zero rows silently. Identifiers are tried in order and the FIRST match wins; `test_resolution_stops_at_the_first_identifier_that_matches` exists because unioning them could mix another patient's key images into the report. Load-bearing: **`test_the_upload_normaliser_keeps_the_image`** — the normaliser already strips `<style>`/`<script>`/chrome, and adding `img` to `_DIR_BLOCK_TAGS` would lose the key image for the referring doctor while the author's copy still shows it, the worst failure mode there is. Also pins: the picker's file list matches the viewer's "Captured Images" dropdown exactly; the encoder refuses rather than embedding over the byte ceiling (a report that will not upload is worse than a refused insert); and the resize actually changes the stored width — **behavioural, because the AST guards did not catch a reversed-cursor-selection bug where every button was wired, every handler ran, and nothing moved**. `test_a_document_can_render_a_data_uri` pins behaviour, not mechanism, so it holds on any Qt. |
| `code/mpr/test_mpr_lifecycle_release.py` | **28** | MPR teardown runs on EVERY destruction path, not just the toolbar toggle. Before this: 14 MPR opens vs 6 `cleanup()` completions across the logged sessions. **The load-bearing pair is `test_layout_teardown_releases_before_orphaning` + `test_patient_close_releases_the_mpr_child`** — they pin the two paths that actually leaked *and their ordering*, because a `closeEvent` hook alone does NOT fix this (Qt never calls `closeEvent` when a parent is destroyed or a widget is re-parented away). Anyone who "simplifies" the fix down to the closeEvent comes back green on the closeEvent tests and is caught here. Also pins: release must happen BEFORE `setParent(None)` or the GL context is gone and the VRAM cannot be freed; the 3D mapper is really re-pointed on an in-MPR series switch (behavioural, on real VTK); and teardown survives an already-deleted C++ object. |
| `code/viewer/test_mpr_step_instrumentation.py` | **20** | Every MPR view creator emits `[MPR-STEP]` under its OWN view name. Before this all 17 call sites passed `'axial'`, so sagittal/coronal/3D cost was invisible and an 8.7 s activation freeze could not be attributed. AST-based, so a renamed-but-still-hardcoded creator fails. |
| `code/network/test_ino_state_batch_write.py` | **28** | The assignment snapshot is written ONCE per refresh batch, not once per reception. Each write rewrites the whole file under a lock the GUI thread takes per patient-list row — the per-row version froze the UI for 10.79 s. Pins: one `_save` + one lock acquisition per batch; `set_state`/`set_many` cannot drift (shared `_entry`); `_load` happens inside the save's lock so a concurrent single write is not rolled back; the fsync is opt-in; and the refresh contracts that must NOT change (per-row `on_row`, summary shape, a failed fetch never wipes, an interrupted refresh still persists). |

Run them all with:

```
.venv\Scripts\python.exe -m pytest tests/code/web_browser tests/code/viewer/test_series_file_warm.py tests/code/viewer/test_disk_pixel_cache_async_init.py tests/code/viewer/test_disk_pixel_cache_persistence.py tests/code/viewer/test_viewer_import_warm.py tests/code/ui_services/test_thumbnail_active_state_and_strip.py tests/code/ui_services/test_main_footer_bar_removed.py tests/code/network/test_ino_state_batch_write.py tests/code/network/test_ino_server_state_concurrency.py tests/code/system/test_browser_prewarm_idle_gate.py -q
```

Last verified green: **2026-08-16, 196 passed**. The wider viewer regression
run was green again on **2026-08-18**:

```
pytest tests/code/viewer      -> 2265 passed, 28 skipped, 37 deselected,
                                 54 xfailed, 2 xpassed
pytest tests/code/fast        ->  176 passed
pytest tests/code/fast_viewer ->  416 passed, 12 skipped   (needs -p no:debugging)
pytest tests/code/reporting
       tests/code/ai_imaging  ->  297 passed, 8 xfailed
```

**2026-08-19** — `tests/code/mpr + viewer + ui_services` → **3091 passed**,
29 skipped, 54 xfailed, 5 xpassed. The 2 failures in that run
(`test_login_carries_the_user_identity_ids`,
`test_status_flags_are_stashed_on_the_widget_to_avoid_recompute`) are
pre-existing source-string pins on the login/JWT path and the patient-list
status renderer; confirmed unrelated by running them in isolation.

**2026-08-21** — `tests/code/viewer + fast_viewer + ui_services + system +
dicom_media` → **3814 passed**, 41 skipped, 38 deselected, 55 xfailed,
5 xpassed. **6 failures, all pre-existing and all proved to fail at HEAD:**
`test_login_carries_the_user_identity_ids` and
`test_status_flags_are_stashed_on_the_widget_to_avoid_recompute` (carried over
from 2026-08-19), plus four in
`tests/code/system/test_local_search_progressive.py` — three assert first-batch
sizes of 100/40 that a June change to `_PROGRESSIVE_INITIAL_BATCH` (now 20) made
stale, and one pins a renamed constant (`_LOCAL_SEARCH_BATCH` →
`_LOCAL_PROGRESSIVE_MIN`). Proved with
`tools/analysis/oneoff/prove_progressive_test_prefails_2026_08_21.py`, which runs
that file's own exec-the-source harness against a `git show HEAD:` copy and gets
20 rows either way. Left alone as unrelated to the 2026-08-21 fixes.

New this day: `tests/code/viewer/test_ybr_color_decode.py` (23 guards, 19 fail at
HEAD) and `tests/code/ui_services/test_list_stream_backpressure.py` (17 guards,
15 fail at HEAD). Both pre-fix checks swap `git show HEAD:` copies into the tree
and restore them in a `finally`.

**2026-08-22** — same five folders, same order → **3841 passed**, 41 skipped,
38 deselected, 55 xfailed, 5 xpassed, **6 failed — the same six as 2026-08-21 and
nothing new**. New guard file:
`tests/code/ui_services/test_gui_thread_disk_paths.py` (29 guards: the original
27 retain **19 fail at HEAD** via
`tools/analysis/oneoff/verify_gui_disk_guard_fails_prefix_2026_08_22.py`; the
2026-09-02 initial-row probe guard independently failed before its correction,
while the explicit-state parity guard already passed).

**2026-09-02 R1 follow-up** — initial Server Search row construction still
called `get_study_download_status` synchronously after the 2026-08-22 scanner
optimization. The result was not consumed by the row renderer, whose Status
cell already uses `statusFlagsReady`. The new behavioral guards execute the real
forwarder, forbid the probe, preserve all row metadata, and preserve explicit
Local/Import download state without reinterpretation. Full guard file: 29
passed. Adjacent search/status/clear/storage selection: 142 passed. A broader
search/table selection passed 95 with two registered xfails and one known
pre-existing fixed-window assertion from 2026-08-21; the changed production
file is outside that failure.

**2026-08-23** — `tests/code/system + runtime + utils + builder` → **580 passed**,
5 deselected, 1 xfailed, **11 failed, 0 of them ours**. New guard files:
`tests/code/system/test_close_path_hang_visibility.py` (14) and
`tests/code/runtime/test_seed_config_once.py` (12) — **all 26 fail pre-fix.**

> **The pre-fix check could not use `git show HEAD:` this time, and that is the
> point.** This working tree carries **389 lines of unrelated uncommitted work in
> `aipacs_runtime.py`** and 17 in `_pw_lifecycle.py` (3.6.1/3.6.2 were built from
> the working tree, not from a commit). Restoring those files from HEAD would
> have reverted far more than the A0 change, and the guards would have "failed"
> for the wrong reason — a green result that proves nothing. So
> `tools/analysis/oneoff/verify_close_path_guard_fails_prefix_2026_08_23.py`
> removes **exactly** the A0 additions instead: anchor-based, every anchor
> asserted present before anything is written, restored in a `finally`. Check
> this before reaching for `git show HEAD:` in any future pre-fix script.

The 11 failures were **measured**, not argued, by
`tools/analysis/oneoff/check_a0_regression_delta_2026_08_23.py`, which runs the
same file set with and without the A0 additions and diffs the failure sets:
identical both ways, **caused by A0: 0**. They are

* 6 × `tests/code/builder/test_nuitka_arm64_parity.py`
* 4 × `tests/code/system/test_local_search_progressive.py` — the same four
  carried since 2026-08-21 (stale batch-size pins)
* 1 × `tests/code/builder/test_release_parity_guards.py::test_plugin_mirrors_are_fresh`

The arm64 six and the plugin-mirror one are **new to this index and unexplained**
— they were not in the 08-21/08-22 folder set, so this is the first run that
covered `tests/code/builder`. Worth their own look; they are not A0.

**2026-08-23 (second run, MPR surface)** — `tests/code/mpr + viewer + system +
architecture + fast` → **2 919 passed**, 28 skipped, 37 deselected, 56 xfailed,
2 xpassed, **4 failed — the four `test_local_search_progressive.py` pins carried
since 2026-08-21, nothing new**. This is the **baseline for the MPR geometry
surface**: it is currently fully green apart from those four, so any red in
`tests/code/mpr` or `tests/code/viewer` after a geometry change is a regression.

Run because A1 (oblique MPR) was about to be changed. **It was not changed** —
reading the prior documentation showed the proposed fix would have reverted
v1.09.Fix-E. See `docs/plans/architecture/MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md`.
Only docs and one stale docstring were edited, hence the clean sweep.

> **Before editing any MPR source file, read the fixed-character-window table in
> that brief.** Eleven MPR-adjacent guard tests still slice their source at a
> fixed character count from a `def`; the 600-char window at
> `_capture_baseline_camera_state` and the 2200/2600-char windows at the two
> wheel handlers are the ones that will bite an oblique-camera change. The
> 2600-char ones hold **negative** assertions, so growth silently *weakens* them
> instead of failing — a worse failure mode than a red test.

> **Folder order changes the result — watch for it.** Running the same folders as
> `ui_services → system → viewer → fast_viewer` instead adds four
> `test_fast_viewer_pipeline.py::test_b41_*` failures. They are **run-order
> pollution, not a regression**: the file passes in isolation (`170 passed`), and
> `tools/analysis/oneoff/check_b41_order_pollution_2026_08_22.py` runs that order
> twice — once with the working tree, once with the three changed files swapped
> for their HEAD copies — and gets the **same four failures both times**.
> Whatever leaks between those folders predates this work and is still unfixed.

> **The fixed-window trap bit again — third file, fourth time.**
> `test_status_refresh_dicom_only.py::test_storage_clear_still_full_recomputes`
> searched a FIXED 1,800-character window from
> `def refresh_download_statuses_local_only`. Moving that method off the GUI
> thread added an explanatory paragraph, which pushed
> `self._local_status_cache.clear()` out of the window — the assertion was still
> TRUE in the code. Re-bounded at the next `def`, assertion untouched, exactly as
> `test_mpr_defer_3d_view.py` was on 2026-08-18 and 2026-08-19. **If you are
> writing a source-pin guard, bound it at the next `def` — never at a character
> count.**

(`tests/code/fast` and `tests/code/fast_viewer` are two different folders —
15 and 17 files. Running only one of them is a common way to miss a break.)

The xfail/xpass set is the pre-existing quarantine, unchanged.

> **`tests/code/fast_viewer` needs `-p no:debugging`.** Without it pytest dies
> with an INTERNALERROR before collection: `_pytest.debugging.pytest_configure`
> does `import pdb`, `pdb` does `import code`, and once `tests/` is on
> `sys.path` that resolves to this repo's `tests/code` package —
> `AttributeError: module 'code' has no attribute 'InteractiveConsole'`.
> `tests/code/viewer` is unaffected because it has no `__init__.py`.
> Pre-existing; the real fix is renaming `tests/code` or putting
> `-p no:debugging` in the pytest config, both wider than any one bug fix.

---

**2026-08-23 (third run, CPU budget)** — `tests/code/system + runtime + utils +
builder` → **593 passed**, 5 deselected, 1 xfailed, **11 failed — the same 11 as
the A0 run above, byte for byte**. 580 + the 13 new guards = 593, so **0
regressions**. New guard file:
`tests/code/system/test_cpu_budget_priority_boost.py` (13) — **5 fail pre-fix**
(`tools/analysis/oneoff/verify_cpu_budget_guard_fails_prefix_2026_08_23.py`).

> **This pre-fix script DOES use `git show HEAD:` — and proves it is allowed
> to.** The A0 note above says not to reach for it blindly; the discriminator is
> `git diff --numstat -- <file>`. For `main.py` that is exactly `18  0  main.py`
> — the fix hunk and nothing else — so HEAD really is the pre-fix state. The
> script asserts this and **refuses to run** if it stops being true. Check the
> numstat before deciding which technique a pre-fix script needs.

Only 5 of the 13 fail pre-fix, and that is correct rather than weak: the other 8
are either preservation guards (the block, the log lines, the `AIPACS_PRIORITY`
kill switch — they must pass on BOTH sides, that is their job) or the two
behavioural Win32 probes, which test Windows' pseudo-handle semantics rather
than our source and therefore pass on both sides by construction. The five that
flip are the three ctypes declarations and the two ORDERING pins.

---

**2026-08-23 (fourth run, HIGH on deployed workstations)** — `tests/code/system +
runtime + utils` → **519 passed**, 1 xfailed, **4 failed — the same four
`test_local_search_progressive` pins carried since 2026-08-21**. 0 regressions.
`test_cpu_budget_priority_boost.py` grew 13 → **23 guards**, of which **16 fail
pre-fix**.

> **`tests/code/builder` was NOT in this run, and that is a measurement gap, not
> a pass.** `test_release_parity_guards.py` calls
> `builder/release_gate.check_source_freshness()`, which shells out to
> `git fetch` with a 90 s timeout — the fetch hung on this network and took the
> whole pytest process with it. Environmental, not ours: the same folder ran 90
> minutes earlier in this session. **Re-run `tests/code/builder` with network
> access before a release build.**

Two new techniques in this file worth copying:

> **Behavioural guards over inline `__main__` code.** The priority resolution
> lives inside `if __name__ == "__main__":` and cannot be imported. Rather than
> settle for source pins, `_resolution_source()` lifts the resolution lines out
> of `main.py` **by anchor** and `exec`s them against a stubbed `_pri_frozen`
> and a stubbed `os.environ`. The guards then assert what the shipped code
> actually DECIDES, not merely that certain characters are present. Extract from
> the **start of the anchor's line**, or `textwrap.dedent` finds no common
> prefix and the exec raises `IndentationError`.

> **A pre-fix script can EARN the right to use `git show HEAD:`.** The A0 note
> above says not to reach for it blindly. The discriminator is whether the
> working diff touches anything outside the block being fixed.
> `verify_cpu_budget_guard_fails_prefix_2026_08_23.py` now parses
> `git diff -U0` hunk headers and requires every hunk to fall inside the CPU
> BUDGET block's line range at HEAD — and **refuses to run** otherwise. That is
> strictly better than the literal numstat check it replaced, which broke the
> moment the fix grew a second landing.

Two guards were **re-pinned, not deleted**, and both record why in the file:
`test_normal_escape_hatch_preserved` (spelling moved) and
`test_high_priority_class_is_not_the_default` →
`test_high_is_the_default_only_for_installed_builds` (**the policy changed by
owner request** — the guard now pins the new rule so a later edit that quietly
makes HIGH the default for source runs too is still caught).

---

**2026-08-24 (completion pass)** — the measurement gap left open on 08-23 is now
closed and one piece of tooling was repaired.

`tests/code/builder` finally ran: **85 passed, 6 failed** — the six
`test_nuitka_arm64_parity` pins, unchanged and unrelated. The seventh failure
carried since 08-23, `test_release_parity_guards::test_plugin_mirrors_are_fresh`,
now **passes** (the v3.6.3 release re-synced the plugin mirrors), and the
`git fetch` inside `check_source_freshness()` no longer hangs. Full picture for
the CPU-budget work: `system+runtime+utils` 519 passed / 4 failed +
`builder` 85 passed / 6 failed = **604 passed, 10 failed, none of them ours**.

> **A pre-fix verification script dies the moment its fix is committed — fix that
> when you write it, not after.** `verify_cpu_budget_guard_fails_prefix_2026_08_23.py`
> asserted `HEAD:main.py` lacks the fix. The fix shipped in
> `5deb8ee7 release(v3.6.3)`, so from that commit onward the script aborted with
> "HEAD already has fix" and the guard's pre-fix proof was **un-runnable**. It now
> resolves a base ref: HEAD when HEAD still lacks the fix, otherwise it walks
> `git log` for the newest commit whose `main.py` lacks it (here `c2f79e63`,
> v3.6.0) and prints which ref it chose; `--base <ref>` overrides. Re-run
> confirmed: **16 fail at `c2f79e63`, 23 pass after restore, `main.py` clean.**

---

**2026-08-26 (overlay re-entrancy crash)** — `tests/code/{viewer,system,ui_services,
fast_viewer}` + `test_loading_overlay_liveness_guard.py` → **3,862 passed**, 41
skipped, 55 xfailed, 5 xpassed, **6 failed — 0 of them ours**. New guard file:
`tests/code/system/test_overlay_reentrancy_crash.py` (13 guards, **11 fail pre-fix**).

Four of the six are the `test_local_search_progressive` pins carried since 08-21.
The other two are in `tests/code/ui_services`, a folder new to this index, and were
**measured rather than argued**: `check_overlay_fix_delta_2026_08_26.py` runs them
with and without the two changed files and gets the identical failure set.

> **A source pin over a file with several same-named methods must carry a CLASS
> scope.** `loading_overlay.py` defines three `__init__`s; a bare `ast.walk()`
> returns `_LogoSpinner.__init__` first, so the first draft of
> `test_overlay_init_refuses_a_destroyed_anchor` was reading the wrong function
> and would have guarded nothing. `_func_src(path, name, cls=...)` now takes the
> class. This is the AST-shaped cousin of the fixed-character-window trap above
> — same failure mode, different mechanism: the guard is bound to the wrong text
> and still goes green.

> **Binding a real method to a stub beats constructing the real object.**
> `QtFastContainer` is a QWidget subclass, so `object.__new__` is refused and a
> real instance needs a QApplication and a live viewport — neither of which the
> re-entrancy guard is about. `QtFastContainer.switch_series.__get__(stub, Stub)`
> runs the SHIPPED method against a plain object, which is how
> `test_a_nested_switch_is_refused` reproduces a native crash with no Qt at all.

---

**2026-08-26 (Eagle Eye lumbar — wrong series in the panes)** — `tests/code/ai_imaging`
→ **385 passed**, 8 pre-existing xfail; `tests/code/viewer` green;
`verify_plugin_mirrors.py` 456/456. Three guards added to
`test_eagle_eye_protocol_resolution.py`:
`test_the_tab_does_not_pre_wait_on_the_thumbnail_list`,
`test_the_controller_asks_by_series_key_never_by_list_position`,
`test_the_controller_still_refuses_when_the_series_never_arrive`.
The 10 `tests/code/ui_services` failures seen in the same run were **measured**
pre-existing: stashing this work reproduces the identical set (a qtawesome
font-directory `TypeError` plus two stale source pins).

> **A parameter name is not a contract — read the first line of the callee.**
> `change_series_on_viewer(series_index, …)` opens with
> `series_number = str(series_index)`: the argument is a series KEY, not a
> position. Passing a `lst_thumbnails_data` index loaded whichever series was
> *numbered* "1" and "2" (the localizer and a coronal myelogram) while every
> log line upstream said the mapping was correct — the defect was invisible
> from the resolver's side and only the viewport's own metadata revealed it.

> **Waiting for a precondition that your own call would satisfy is a deadlock
> with a timeout.** The tab polled `lst_thumbnails_data` (LOADED series only)
> before assigning, but assignment is what triggers the decode. For a study
> whose other series had never been requested the entries never appeared, so a
> correct mapping still burned the full 90 s budget. Readiness moved to the
> layer that can observe the real end state: the viewport.

---

**2026-08-26 (Eagle Eye v1.1.0 — protocol-driven engine + reference-line policy)** —
`tests/code/ai_imaging` → **426 passed**, `tests/code/viewer` → **2,288 passed**
(2,714 together), `verify_plugin_mirrors.py` 456/456. Eighteen guards added in two
new sections of `test_eagle_eye_lumbar_pipeline.py`: §8b the reference-line policy
(real behaviour against fake viewers) and §8c the protocol architecture.

> **A guard that says "the engine must not know about X" belongs on the AST, not
> the text.** `test_the_engine_names_no_body_part` first failed on the module
> docstring — which deliberately explains the lumbar history — and on the
> back-compat class alias. Parsing instead, and excluding docstring constants,
> makes it test the values the engine COMPUTES with rather than what it SAYS.
> The text version would have forced the comments to be worse.

> **Write the guard for the requirement, not for the code you just wrote.** Two
> of these failed on the first run and were right to: `restore()` on the
> reference-line policy was never wired into `_finish`/`_fail`, and the engine
> still carried `"lumbar_mri"` string defaults. Both were real gaps found by
> guards written from the requirement rather than from the implementation.

> **Derive a rule instead of declaring it where you can.**
> `hide_reference_lines_on` defaults to `primary + synced` and `sync_groups` is
> computed from the sessions. Declared copies of a rule drift from the code that
> enforces it; derived ones cannot. Both still allow an explicit override, so
> the default is a default rather than a law.

---

**2026-08-27 (Eagle Eye LLM pipeline 3.3.0 — explicit stenosis grades and
provider-specific stage sampling)** — `tests/code/ai_imaging` → **499 passed**,
8 pre-existing xfail. Five guards were added to
`test_eagle_eye_llm_analysis.py`; all five failed before the implementation and
passed afterward. They protect the immutable/versioned central-canal, neural-
foraminal and lateral-recess grading catalog; identical grading semantics in
both passes; ordinal grading fields in the screening contract; temperature in
stored provenance; and actual forwarding of each stage's temperature across
the Eagle Eye → EchoMind boundary.

> **Two readers may have opposite dispositions without having different
> dictionaries.** Screening remains inclusive and verification remains
> conservative, but both now use one catalog for the meaning of mild, moderate
> and severe. The transport also no longer applies its shared 0.2 default to
> Gemini 3 screening: screening requests 1.0, while GPT verification remains
> at 0.2. This slice deliberately does not change image selection, candidate
> routing, or final-report rendering, so its effect can be evaluated separately.

---

**2026-08-27 (Eagle Eye — patient-free GapGPT capability matrix)** —
`tests/code/ai_imaging` → **504 passed**, 8 pre-existing xfail;
Eagle Eye/GapGPT/EchoMind cross-boundary selection → **94 passed**;
`verify_plugin_mirrors.py` → **456/456**. New guard file:
`tests/code/ai_imaging/test_eagle_eye_gapgpt_capability.py` (5 guards; all five
failed before the pure contract and adapter existed).

The probe sends only deterministic in-memory PNG tiles through the existing
GapGPT URL, key and HTTP authorities. It pins the two production model ids and
their stage temperatures; text, high-detail vision, multi-image ordering,
strict-schema and Responses scenarios; semantic schema evaluation; credential
redaction; and the absence of any direct OpenAI endpoint or key path.

> **HTTP 200 is not capability success.** Gemini returned an empty JSON object
> for a strict schema and therefore failed semantically; GPT-5.6 Sol returned
> the exact required object. Also, `google/<model>` and `openai/<model>` are
> GapGPT canonical names, not model substitution. The first evaluator used raw
> string inequality, incorrectly marked every live response as substituted,
> and the namespace guard failed before that defect was fixed.

---

**2026-08-28 (Eagle Eye workflow/UI boundary)** — New guard file:
`tests/code/ai_imaging/test_eagle_eye_ui_boundary.py` (4 guards). The architecture
guard failed before implementation because the coordinator did not exist and all
capture, analysis, result, and teardown methods were still members of
`ImagingToolsTab`. The extracted
`modules/ai_imaging/eagle_eye_lumbar/workflow_coordinator.py` now owns those
lifecycles. Two behavioral guards protect the validated series-identity handoff and
close-while-running abort/detach sequence. Focused boundary/resolution gate:
**56 passed**; capture/resolution/LLM gate: **267 passed**; complete AI Imaging
gate: **518 passed, 8 pre-existing xfailed**.

> **A UI callback is not the feature boundary.** Moving only the button callback
> would leave state, error handling, worker ownership, and teardown coupled to the
> oversized tab. The coordinator owns the entire lifecycle; the tab constructs it,
> schedules it, displays status, and tears it down.

---

**2026-08-28 (Eagle Eye pipeline 4.0.0 — parallel clinical context)** —
`tests/code/ai_imaging/test_eagle_eye_llm_analysis.py` now contains 77 guards,
including four new guards that all failed before implementation. They protect:
the versioned Gemini clinical-context stage and GPT fusion input; bounded,
supported, path-redacted attachment packaging; concurrent Gemini MRI screening
and document extraction before GPT verification; and graceful continuation when
the document branch is absent or fails. Complete AI Imaging gate: **522 passed,
8 pre-existing xfailed**.

> Clinical context is an untrusted prior, never current-MRI evidence. The final
> adapter allowlists the extraction schema, and GPT verification must re-check
> every historical claim against the MRI. No document means no extra Gemini
> request; context failure does not discard a successful MRI read.

---

**2026-08-28 (Eagle Eye pipeline 4.1.0 — multi-source context)** — The parallel
Gemini context branch now reads allowlisted reception facts and prior reports,
a sanitized full-or-limited PACS series catalogue, DICOMized clinical history
series `100000`, supported attachment documents, and a bounded MRI overview.
New guards prove that collection itself overlaps MRI screening; the capture
boundary snapshots the full catalogue without UIDs; DICOM clinical pages are
rendered to derived PNGs; and `locally_available_series_only` can never create a
missing-sequence, absent-postcontrast, or protocol-limitation claim. Focused LLM
file: **83 passed**; LLM plus lumbar pipeline: **222 passed**; complete AI
Imaging gate: **529 passed, 8 pre-existing xfailed**; EchoMind scoping plus the
patient-free GapGPT capability gate: **21 passed**.

> Only `pacs_series_catalog` may support an absence claim. Reception history is
> a prior, series inventory is protocol metadata, and MRI overview is incomplete
> context; the final GPT must still establish findings from the full MRI package.

---

**2026-08-29 (Eagle Eye original-tab context handoff repair)** — Three new
guards failed before the fix and protect the live-discovered loss of patient ID
and complete series inventory between the original patient tab and the reduced
Eagle Eye widget. `test_preflight_handoff_snapshots_patient_id_and_the_complete_catalog`
pins the bounded, UID/path-free snapshot at the source;
`test_capture_context_uses_complete_handoff_when_the_ai_widget_is_reduced`
pins patient-ID recovery and six-series full-catalogue authority at capture;
and `test_original_patient_context_crosses_the_existing_one_shot_handoff`
pins coordinator threading without returning feature logic to the oversized UI
tab. Focused lumbar/UI gate: **146 passed**; complete AI Imaging gate:
**546 passed, 8 pre-existing xfailed**; plugin mirrors: **456 matched**.

> The handoff is application context, not model input. Identity enables the
> existing reception/prior-report authorities locally and is removed before the
> model package; the series snapshot contains descriptive protocol metadata but
> no series UID or path. Live source-build confirmation remains pending.

The same repair is now pinned into every default build path by
`tests/code/builder/test_eagle_eye_default_build_inclusion.py` (3 guards). The
Nuitka inclusion guard failed before the builder change; both monolithic and
staged full-core Nuitka now force-include `modules.ai_imaging`, while
PyInstaller's existing non-optional `modules` collection remains the third
path. The guards also inspect the generated staged command, prove there is no
feature-flag gate, and require the canonical Viewer file to match its package
payload exactly. Focused builder guard: **3 passed**; module/plugin readiness
and cross-build coherence: **passed**;
plugin mirrors: **456 matched**. The broader builder baseline remains red for
six unrelated ARM64 parity guards, one stale staged-config guard, and one
network source-freshness timeout; no full-build pass is claimed.

**2026-08-30 (Eagle Eye pipeline 4.2.0 — disc hydration specificity and
provider-neutral popup)** — Two behavioral guards failed before the fix and
pass afterward. The LLM guard requires both image-reading stages to treat
preserved central nucleus-pulposus T2 hyperintensity on adjacent mid-sagittal
slices as evidence against desiccation, and forbids axial-only or dark-annulus
calls. The UI guard renders a synthetic stored record and proves that the popup
shows `AI-PACS AI Lumbar Analysis` without Gemini/GPT/provider identifiers,
while preserving prompt version, pass/image counts, date, and token metadata.
Raw model provenance remains stored for audit. Focused proof: **2 passed**;
changed-boundary files: **90 passed**; complete AI Imaging gate: **559 passed,
8 pre-existing xfailed**; default-build inclusion guard: **3 passed**. Live
radiologist validation of pipeline 4.2.0 remains pending.

**2026-08-30 (Eagle Eye pipeline 4.3.0 — pathology-focus differential
adjudication)** — Four new prompt-contract guards failed before the fix. They
pin screening as a sensitivity-oriented attention map, a shared multi-plane
disc-displacement nomenclature, separate authorities for screening/context/MRI,
and mandatory differential reclassification at every positive focus. A wrong
screening label with a supported alternative pathology must be
`RECLASSIFIED`, not `REJECTED`; normal and non-pathological variants remain
valid rejection outcomes. Two older guards were intentionally re-pinned from
the former deletion-filter/axial-veto policy to the clarified owner contract.
Focused LLM file: **88 passed**. Live radiologist validation of pipeline 4.3.0
remains pending. Complete AI Imaging gate: **563 passed, 8 pre-existing
xfailed**; default-build inclusion guard: **3 passed**.

**2026-08-30 (Eagle Eye pipeline 4.4.0 — paired sagittal context and focal
attention)** — Four behavioral guards failed before the fix. They require the
context branch to select paired sagittal T2/T1 captures nearest the measured
midline instead of sagittal/axial sweep endpoints; extract bounded general,
regional, and level-specific `context_attention_foci`; preserve only allowlisted
fields and evidence sources when forwarding context; and retain safe
session-local sagittal context when an invalid study UID disables external
lookups. The final verifier must audit every non-global context focus against
the complete MRI and may add, reject, or mark it indeterminate. Focused LLM
file: **92 passed**; complete AI Imaging gate: **567 passed, 8 pre-existing
xfailed**; default-build inclusion guard: **3 passed**; combined gate:
**570 passed**. Live radiologist validation remains pending.

**2026-08-30 (Eagle Eye pipeline 4.5.0 — patient laterality and same-lesion
multiplanar morphology)** — Two prompt-contract guards failed before the fix.
They require both image readers to derive patient side from visible `R/L`
markers or trusted DICOM patient coordinates, never screen position, and to
return indeterminate laterality when orientation evidence is unavailable or
conflicting. They also require sagittal and axial observations to be correlated
to the same level and displaced component before morphology is fused. A
sagittal extrusion-defining neck/base-to-dome relationship cannot be outvoted
by a partial axial slice that looks protrusion-like. Focused LLM file: **94
passed**; complete AI Imaging gate: **569 passed, 8 pre-existing xfailed**;
default-build inclusion guard: **3 passed**; combined gate: **572 passed**.
Live radiologist validation remains pending.

**2026-08-31 (OPT-55 — level integrity, padding headroom, scorer 1.2.0)** —
`test_eagle_eye_level_identity.py` passes **19** cases for uniform shift despite
monotonicity, stable frame identity, invalid/missing/duplicate/overlapping maps,
measured slab mismatch, malformed/truncated input, review-required persistence
and panel presentation, and benchmark diagnostics without relabeling claims.
`test_eagle_eye_parasagittal.py` passes **26** cases including exact pixel retention
across seven aspect ratios and visible coverage failures. Scorer guards pass
**35** cases, adding participles, structure-local grades, lower-thoracic rows,
and subarticular-location versus recess-consequence separation. Initial suite:
22 failed/43 passed; self-review reproduced five map-parser and two location-
masking failures before correction. Final combined AI Imaging/core inclusion:
**732 passed, 8 existing xfailed** (729 + 3); **462 mirror pairs** matched.
Private offline replay preserved 60 originals, 5 base images, and 21 supplemental
tile contents; pixels fell to 11,253,504 but image capacity remains 8/8.
No model request, default promotion, or clinical accuracy claim. See Eagle Eye
stage-two document section 31; full Phase 0 and controlled E1/E2 remain pending.

**2026-08-31 (OPT-55 — opt-in bilateral sagittal supplements; root scorer 1.1.0)** —
`test_eagle_eye_parasagittal.py`: **18 passed**, covering LPS sampling under
reversed/oblique geometry, short/invalid coverage, exact V3 image/caption
preservation, screening-side independence, image/pixel/byte caps, optional
failure retention, no-focus overviews, and verification-only mocked dispatch.
Initial feature guards failed in **11 cases** before implementation. Root
negation guards reproduced **6 failures / 7 passes** before the scorer repair;
`test_eagle_eye_bench_scoring.py` now passes **25 tests**. Contact with negated
deviation is `under` against compression, not a total miss. Complete AI Imaging:
**675 passed, 8 existing xfailed**; core-build inclusion **3 passed**; **458
mirror pairs** matched. Offline replay preserved 57 original files and all four
baseline images/captions, then added two supplements within unchanged caps.
No model call, default promotion, or diagnostic improvement claim. Remaining
Phase 0 scorer/reference defects are documented, not silently declared fixed.

**2026-08-31 (OPT-55 — focused V2/V3 bounded axial-window coverage)** —
`tests/code/ai_imaging/test_eagle_eye_focused_v2.py` adds **41 synthetic cases**
covering short/long slabs, every anchor, both boundaries, interior windows,
gap/orientation isolation, reversed source ordinals, unchanged shared sagittal
selection, preserved projection anchors, original capture bytes, and audited
manifest/budget behavior in both render modes. Before the fix: **20 failed,
21 passed**, exit code 1. Afterward: focused V2/V3 **63 passed**; complete AI
Imaging **643 passed, 8 existing xfailed**; default-build inclusion **3 passed**;
**458 plugin mirror pairs** matched, all with exit code 0. A fresh private
offline replay restored available five-slice focus coverage without changing
original artifacts or sagittal sampling. No model call or clinical accuracy
claim. Manifest schema 1.3.0 records policy `same-slab-backfill-v1`; live
source-build/radiologist validation remains pending.

**2026-08-30 (Eagle Eye pipeline 4.6.0 — candidate-directed focused-v2 DICOM
evidence)** — `tests/code/ai_imaging/test_eagle_eye_focused_v2.py` adds seven
behavioral guards. They pin the versioned allowlisted focus plan; decisive-frame
sanitization and level-map fallback; patient-LPS mapping from stored capture
geometry into the immutable axial volume; DICOM-derived patient orientation;
five-slice axial and three-slice
sagittal sequence sheets; no-upscale rendering, uniform-image rejection, and
image/pixel/byte caps; local-only series-path provenance; layout evidence for
parallel Gemini screening; focused evidence only for GPT verification; and
deterministic fallback to the original stored layout when DICOM provenance or
composition is unavailable. The shared headless volume primitives now serve
both Legion Consult and Eagle Eye. Focused changed-boundary gate: **262 passed**;
complete AI Imaging gate: **576 passed, 8 pre-existing xfailed**. `layout`
remains the runtime default pending paired radiologist validation.

**2026-08-30 (Eagle Eye pipeline 4.6.1 — focused-v2 capture-frame
authority)** — Four additional behavioral guards cover the live reversed-level
map defect. They require raw inferior-to-superior DICOM order to remain distinct
from original superior-to-inferior capture-frame identity, prevent adjacent
focus ribbons from crossing independently angled slab boundaries, calculate the
cross-plane point from the physical image center rather than Image Position
Patient alone, and require verification to use only `AX frame n/N` labels for
the final level map. The numbering guard failed pre-fix with no
`axial_capture_frames` authority. The focused file now contains **11 guards**.
The changed-boundary set passed **134 tests**, complete AI Imaging passed **580
tests with 8 pre-existing xfails**, default-build inclusion passed **3 tests**,
and **458 plugin mirror pairs** matched. Live source-build model and radiologist
validation remain pending.

**2026-08-28 (Eagle Eye — Legion Consult foundation)** — New guard files:
`tests/code/ai_imaging/test_legion_consult_foundation.py` and
`tests/code/ai_imaging/test_legion_consult_ui_contract.py` (**14 focused guards**).
They protect the native/Legion function picker, MRI-only availability, mandatory
source/T1/T2 roles, role de-duplication, optional/select-all cost control,
non-diagnostic-series exclusion, deterministic four-corner LPS mapping, atomic
local-only request persistence, source identity matching, and toolbar routing.
The UI gate also proves that disarming an unfinished ROI returns the coordinator
to idle. No capture, provider dispatch, or model-analysis behavior is claimed
by this foundation gate.

**2026-08-29 (Eagle Eye — Legion Consult post-ROI completion)** —
`tests/code/ai_imaging/test_legion_consult_analysis.py` adds 10 focused guards,
with one additional retry-lifecycle guard in
`tests/code/ai_imaging/test_legion_consult_ui_contract.py`.
They pin the exact user-supplied Step 1 prompt fingerprint; Gemini screening and
GPT-5.6 Sol verification routing; clipped ±5 focus slices; exact complete-stack
overview coverage; LPS-to-series projection; 3D-volume validation; anonymous,
UID/path-free derived evidence and retry reconstruction; sequential transfer
of the Step 1 answer into Step 2; the workflow transition from a persisted ROI
request into analysis; and retention of source candidates when evidence
preparation fails before its manifest exists. The post-ROI transition guard
failed before the fix. The foundation persistence guard also verifies atomic
request-state advancement without changing the saved ROI geometry.

---

## Eagle Eye grading identity and frozen input (2026-08-31)

`code/ai_imaging/test_eagle_eye_grading_contract.py` and updated assertions in
`test_eagle_eye_llm_analysis.py` separate Bartynski recess compression criteria
from root contact/deviation/compression observations. Six guards failed before
the catalog/version correction; both files now pass 97 tests. Pipeline 4.7.0,
grading catalog 2.0.0, root observations 1.0.0; context stays unchanged.

`code/ai_imaging/test_eagle_eye_frozen_input.py` has 18 synthetic offline guards:
historical prompt/settings and ordered image bytes, source preservation, path/link
rejection, counts/limits, canonical-JSON size expansion, digest/order changes,
partial writes and CLI failures without patient-bearing output. Initial 15 failed
before implementation; the expansion guard failed during self-review before fix.
The feature freezes/checks saved inputs only, not verification replay or clinical
landmarks. Full AI Imaging/default-build gate: 753 passed, 8 existing xfailed;
462 plugin mirror pairs match. See Eagle Eye stage-two document section 32.

## Eagle Eye localization-only screening (2026-08-31)

Related follow-up: `code/ai_imaging/test_eagle_eye_axial_locator.py` (2026-09-01)
adds 32 synthetic guards for explicit plane identity in the spare supplement
cell. The first availability guard failed before implementation. Shared-frame
and every-source-plane affine checks prevent fabricated links; finite FOV,
oblique/reversed/anisotropic cases, synthetic DICOM loading and pixel comparison
protect correctness without changing the seven clean images or image/pixel
budgets. Full AI Imaging/default-build gate: 810 passed, 8 existing xfailed,
exit 0; 462 mirrors match. Stage-two section 35 records the offline check and
the still-pending clinical model test.

`code/ai_imaging/test_eagle_eye_screening_attention.py` has 18 synthetic guards
for diagnostic-rubric/label exclusion, anatomy-only legacy adaptation, raw-text
fallback removal, normal-focus exclusion, original-image frame/pane/box identity,
cross-plane correspondence, non-layout box rejection, malformed numbers/rows,
and retention of uncertain or unassessable anatomy. Seven initial guards failed
before implementation. The injected parallel integration test in
`test_eagle_eye_llm_analysis.py` verifies the planner and diagnostic reader receive
the same sanitized attention while raw stage output is preserved. Adjacent
Legion handoff remains unchanged. Pipeline 5.0.0; screening 2.0.0; verification
4.0.0; context 2.1.0. Full AI Imaging/default-build gate: 772 passed, 8 existing
xfailed; 462 mirror pairs match. See Eagle Eye stage-two document section 33.

The anatomy-first refinement adds three fail-before prompt/example guards and
one passing-before/after behavioral check for distinct disc/endplate/facet
identities at the same level (22 cases in the localization file). The injected
parallel handoff is now tested with each of those three structures. Pipeline
5.1.0, screening 2.0.1, diagnostic 4.1.0; context and normalization schema
unchanged. Full gate: 778 passed, 8 existing xfailed. Diagnostic output separates
the supplied anatomical compartment from the one actually reviewed. This does
not validate clinical conclusions or DICOM correspondence. See section 34.

## Offline lumbar bundle and installer guards (2026-08-31)

`code/mpr/test_slicer_window_promotion.py` covers the OPT-56 invisible-modal freeze:
dialogs polished during warmup must display when opened later; an active suppressed
modal must become visible without being dismissed; unused/deleted dialogs and
foreign offscreen attributes remain safe. Three real-Qt cases failed before repair;
the combined launch/lifecycle/builder gate passes 70 tests afterward. The user later confirmed live source-viewer responsiveness; this is distinct from
the offscreen checks and does not establish clinical segmentation accuracy.

`code/mpr/test_advanced_launch_safeguard.py` covers the live OPT-56 button failure:
immediate/deferred deletion of registered Qt controls, stale registration batches,
deletion during an operation and safe retry, disabled-state/duplicate protection,
and the real Advanced MPR handler reaching deferred launch with synthetic identity.
All five cases failed before the fix; the combined lifecycle/resident/builder gate
passed 52 tests afterward. The user later confirmed that the source viewer opens and responds.

`code/builder/test_distribution_profiles.py` verifies physical compact-payload
exclusion and feed isolation, mandatory Eagle Eye assets, no stale-installer
substitution, compact size failure, three-output/default selection, ARM emulation
identity, required Slicer resource retention, cached-asset tamper detection, and
the established per-backend `output/installer` contract. It asserts the exact
three versioned filenames, release manifest, install notes and checksums and
rejects the invented `output/distributions` delivery tree.
`code/builder/test_release_candidate_packaging.py` also restricts isolated-build
delivery to `builder/output/installer` and `builder nuitka/output/installer` in
the selected repository while allowing short external compiler staging only.
`tools/build/verify_distribution_installer.py` performs real compiler-only checks
on synthetic files for all three variants, including missing-model rejection.

`code/mpr/test_slicer_resident.py` covers OPT-56 actual readiness instead of import
readiness, alive-without-ready timeout failure, no image-name process cleanup,
coalesced background startup, role isolation, shutdown races, read-only input
budgets, scene preservation after rejected/uncertain commands, true launcher
lifetime, optional profile/prewarm switches and low-memory deferral. The source-only
`tools/dev/run_slicer_resident_probe.py --inference` additionally checks hidden
same-process promotion, exact DICOM selection, authentication, separate headless
threshold/model execution and parent Qt responsiveness with synthetic data.
See `docs/modules/ADVANCED_ANALYSIS_RESIDENT_RUNTIME.md` for evidence and limits.

`code/ai_imaging/test_offline_lumbar.py` checks bundle integrity, unsafe paths,
fixed task/device policy, missing weights, denied DNS, owned-process cancellation,
and input cleanup including process-start failure. That last guard failed before
the cleanup correction. `code/builder/test_offline_lumbar_payload.py` checks
fail-closed staging, canonical adapter refresh, retention of dependency resources,
and combined Slicer/model materialization. The dedicated Slicer synthetic probe
also checks GUI, cropped/rotated geometry, changed-source rejection and optional
real model inference; it is not a patient or accuracy test. See
`docs/modules/ADVANCED_ANALYSIS_OFFLINE_LUMBAR.md` for commands and limits.

## Cumulative count (2026-08-18)

Counted directly by `tools/analysis/oneoff/count_test_files_2026_08_18.py`,
not from the dashboard:

- **Test files under `tests/code/`: 691** (`test_*.py`, recursive) across
  **41** domain folders, plus 16 sitting directly under `tests/code/`
- **Regression catalog rows: 59**

Note: the 08-16 block below recorded *688 files / 44 folders*. The file delta
is the three guards added on 08-18 (`test_mpr_step_instrumentation.py`,
`test_text_annotation_input.py`, `test_report_image_insert.py`); the folder
count differs because this script counts only folders that actually contain a
`test_*.py`, so it is the number to trust going forward. Re-run
`tools/analysis/oneoff/count_test_files_2026_08_18.py` to refresh both numbers.

---

## Cumulative count (2026-08-16)

Counted directly, not from the dashboard:

- **Test files under `tests/code/`: 688** across **44** domain folders
- **Regression catalog rows: 56**

---

## Cumulative count (post-audit 2026-05-29)

- **Total test files: 194** (code = 183, bus-driven = 7, pywinauto = 4)
- **Sandbox-runnable code tests: 121 / 0 / 0**
- **Structural system guards: 46 across 7 files**
- **Regression catalog rows: 37**
- **KPI registered keys: 42 across 13 workflows**

These numbers come from `python tools/kpi_dashboard.py` and `pytest tests/code/echomind tests/code/system`. They are the long-term measurement surface — every PR that lands a fix should make the catalog and test counts grow together.

## Eagle Eye source-grounded correlated screening (2026-09-01)

`code/ai_imaging/test_eagle_eye_correlated_screening.py` protects the focused V4
contract: bounded DICOM atlas identity, no path/UID leakage in its manifest,
tile-content box conversion to patient LPS, deterministic multiplanar
validation, rejection of foreign tile identities, propagation of attention IDs
and the lesion anchor, and focus cropping around that anchor instead of the
axial slice centre. The file failed at import before implementation and passes
four synthetic cases afterward, including fail-closed missing Frame of
Reference. These guards validate software geometry, not
clinical localization or diagnosis.

## Eagle Eye canonical screening handoff (2026-09-01)

`code/ai_imaging/test_eagle_eye_screening_attention.py` and
`code/ai_imaging/test_eagle_eye_correlated_screening.py` now protect pipeline
5.3.0's diagnosis-free canonical handoff. The guards require same-site repeated
rows to merge with their cross-plane locations, normal/abnormal contradictions
to resolve once with reduced confidence, left/right duplicates to become one
bilateral focus, and spatially distant patient-space anchors to remain separate
foci. The public GPT context excludes normal counters and internal parser noise
while retaining bounded material quality issues. Six assertions failed before
their corresponding corrections; self-review also caught and guarded an
intermediate false promotion from unavailable geometry to verified single-plane
geometry. Final focused screening/correlation/version
gate: 35 passed; full AI Imaging gate: 817 passed, 8 existing xfailed; default
build inclusion: 3 passed; plugin mirrors: 462/462. These are software-contract
guards, not clinical sensitivity or specificity validation.

## Eagle Eye canonical evidence and rollback policy (2026-09-01)

Mode-policy guards in `code/ai_imaging/test_eagle_eye_evidence_bundle.py`,
`test_eagle_eye_focused_v3.py`, and `test_eagle_eye_parasagittal.py` require
the canonical evidence mode for an ordinary source or packaged run even when a
stale legacy evidence variable remains in the environment. That mode was V4 in
pipeline 5.4 and is V5 level cards in pipeline 5.6. Retired layout/V1/V2/V3/V4
composers are reachable only when the separate engineering gate is explicitly
enabled; unsupported values still fail clearly. Four assertions failed before
the original gate existed, and the current default assertion is pinned to V5.
Historical composers remain testable for rollback and benchmark reproduction;
they are not exposed as normal application versions.

## Eagle Eye sagittal screening sampling and capacity (2026-09-01)

`code/ai_imaging/test_eagle_eye_correlated_screening.py` protects pipeline
5.4.0's role-specific screening renderer. Synthetic 11-slice sagittal T2/T1
series must retain every source identity across 6+5 pages, use `320 x 555`
diagnostic tiles at no worse than `0.47 mm/px` for the representative source,
and leave axial `256 x 256` rendering unchanged. Manifest 1.1.0 must record
per-tile fitted content, effective sampling, summarized ranges and the actual
request budget; the session result retains only the compact summary. Explicit
budget, quality and render failures must raise the typed fallback contract.
Pipeline provenance is pinned to 5.4.0. Eight guards failed before the relevant
changes. Focused screening/orchestration passed 135; full AI Imaging passed 825
with 8 existing xfails and 3 dependency warnings; default-build inclusion passed
3 and all 462 plugin mirror pairs matched. These guards establish evidence
sampling and boundedness, not improved clinical detection.

## Eagle Eye salience-aware screening retention (2026-09-01)

`code/ai_imaging/test_eagle_eye_screening_attention.py` protects pipeline 5.5.0,
screening contract 2.3.0 and evidence-plan schema 1.2.0. The first reader must
remain diagnosis-free while emitting bounded visual salience, within-study
priority, adjacent-slice persistence and allowlisted observable features. The
normalizer must remove untrusted keys and expose an incomplete 2.3.0 routing
contract as degraded. The planner must retain a marked/dominant caudal focus
ahead of subtle cranial foci and must emit specific capacity warnings rather
than silently truncating marked/dominant evidence demand. Selected-focus
manifests must also retain the routing values. Six guards failed before
implementation. The changed boundary passed 235 tests; complete AI
Imaging passed 830 with 8 existing xfails and 3 existing SWIG warnings, exit 0.
These guards prove deterministic handoff retention, not clinical detection or
diagnostic accuracy. See Eagle Eye stage-two document section 40.

## Eagle Eye self-contained diagnostic level cards (2026-09-01)

`code/ai_imaging/test_eagle_eye_focused_v3.py`,
`test_eagle_eye_llm_analysis.py`, `test_eagle_eye_screening_attention.py`, and
the mode-policy tests protect pipeline 5.6.0 and canonical
`focused-v5-level-cards`. Each selected anatomical level must produce one image
containing one targeted sagittal T2 tile, one matched sagittal T1 tile when
available, and at most four contiguous axial T2 frames confined to the measured
slab. The card manifest and request header must bind its global image number,
focus, attention IDs, subject level and allowed axial frames; the shared
EchoMind/GapGPT content builder must expose the same `IMAGE n OF N` identity.
The diagnostic prompt may use only the bound card, MRI-overview context cannot
inject a level-specific diagnosis, and missing screening tile identity remains
material degradation. A structured verification citation outside the bound
axial frame set must make the report review-required without automatic
relabelling. The primary guards failed before implementation and the focused
boundary passes 173 tests afterward. Complete AI Imaging passes 837 with 8
pre-existing xfails and 3 pre-existing SWIG warnings; default-build inclusion
plus mirror parity passes 4 tests, and 462 mirror pairs match. These tests prove
package identity and scope enforcement, not anatomical-numbering truth or
diagnostic accuracy. See Eagle Eye stage-two document section 41.

## Eagle Eye fixed anatomical level-card template (2026-09-01)

`code/ai_imaging/test_eagle_eye_correlated_screening.py`,
`test_eagle_eye_focused_v3.py`, and `test_eagle_eye_llm_analysis.py` protect
pipeline 5.7.0, screening contract 2.4.0, evidence-plan schema 1.3.0,
verification prompt 4.5.0 and V5 manifest 2.1.0. Gemini may propose only exact
source-atlas identities for nine predefined slots. The local normalizer rejects
a tile from the wrong sequence, the renderer constrains axial selections to the
subject slab, and every card uses the same three sagittal T2, three sagittal T1
and three axial T2 positions. The prompt distinguishes axial anatomical zones
from craniocaudal migration levels. Six principal guards failed before the
production boundary existed, including patient-LPS sagittal order and public
degradation propagation. The changed boundary passes 166 tests and complete
AI Imaging passes 842 with 8 pre-existing xfails and 3 pre-existing SWIG
warnings. These tests prove bounded source identity and deterministic layout,
not clinical accuracy or a validated anatomical midline. See Eagle Eye
stage-two document section 42.

## Eagle Eye geometry-owned card assembly and metadata (2026-09-01)

`code/ai_imaging/test_eagle_eye_correlated_screening.py`,
`test_eagle_eye_screening_attention.py`, and
`test_eagle_eye_focused_v3.py` protect pipeline 5.8.0, screening contract 2.5.0,
verification prompt 4.6.0, evidence-plan schema 1.4.0, card-template schema 1.1.0
and V5 manifest 2.2.0. The guards require bounded per-tile conspicuity and
same-level attention bindings, prevent context-only cards, preserve unclear but
source-bound abnormal attention in one additional-findings card, synchronize T1
to the selected T2 patient planes, prevent one axial frame from occupying three
semantic slots, keep model-facing card JSON compact, and permit only edge ticks
rather than an anatomy-crossing locator line. Six primary assertions failed on
the preceding implementation. The changed boundary passes 67 tests and the full
AI Imaging suite passes 848 with 8 pre-existing xfails and 3 pre-existing SWIG
warnings. These are evidence identity, boundedness and transport guards; they do
not validate clinical detection, morphology classification or severity. See
Eagle Eye stage-two document section 43.

## Eagle Eye same-plane sagittal-pair card layout (2026-09-01)

`code/ai_imaging/test_eagle_eye_focused_v3.py`,
`test_eagle_eye_grading_contract.py`, and `test_eagle_eye_llm_analysis.py`
protect pipeline 5.9.0, verification prompt 4.7.0, card-template schema 1.2.0
and V5 manifest 2.3.0. Each patient-right, midline and patient-left sagittal
column must place T2 directly above the geometry-matched T1 plane and must be
read top to bottom before moving to the next column. The level-bound axial T2
sequence remains three tiles below a neutral divider and reads left to right.
The manifest must expose exact visual groups, pairwise slot order, 384 x 256
sagittal cells, 384 x 384 axial cells and a sequence-border legend whose
`diagnostic_meaning` is false. The request header, image caption and prompt must
state the same order and must not imply that color encodes abnormality,
laterality, severity or confidence. The card/layout assertion and two version
guards failed before implementation. The changed boundary passes 172 tests and
the full AI Imaging suite passes 848 with 8 pre-existing xfails and 3
pre-existing SWIG warnings. These tests establish deterministic visual
correlation and bounded image size, not diagnostic accuracy. See Eagle Eye
stage-two document section 44.

## Eagle Eye five-plane sagittal diagnostic cards (2026-09-01)

`code/ai_imaging/test_eagle_eye_focused_v3.py`,
`test_eagle_eye_correlated_screening.py`, `test_eagle_eye_llm_analysis.py`, and
`test_eagle_eye_grading_contract.py` protect pipeline 6.0.0, screening contract
2.6.0, evidence-plan schema 1.5.0, verification prompt 4.8.0, card-template
schema 1.3.0 and V5 manifest 2.4.0. Every named card must contain five distinct
patient-space sagittal T2 planes in right-foraminal, right-paracentral,
midline, left-paracentral and left-foraminal order, with a geometry-matched T1
tile immediately below each plane. Three distinct level-bound axial T2 tiles
remain below the divider. The card must be 1600 x 1050 with 320 x 224 sagittal
cells and 384 x 384 axial cells, keeping six cards at 10,080,000 pixels under
the twelve-megapixel request ceiling. Representative card-size, five-plane
fallback and screening-schema guards failed before implementation. The changed
boundary passes 173 tests and complete AI Imaging passes 849 with 8 pre-existing
xfails and 3 pre-existing SWIG warnings. These tests establish coverage,
patient-space ordering, cross-sequence pairing and bounded transport, not
clinical accuracy. See Eagle Eye stage-two document section 45.

## Eagle Eye anatomy-first spaced sagittal sampling (2026-09-01)

`code/ai_imaging/test_eagle_eye_focused_v3.py`,
`test_eagle_eye_correlated_screening.py`, `test_eagle_eye_llm_analysis.py`, and
`test_eagle_eye_grading_contract.py` protect pipeline 6.1.0, screening contract
2.7.0, evidence-plan schema 1.6.0, verification prompt 4.9.0, card-template
schema 1.4.0 and V5 manifest 2.5.0. The sagittal fallback must ignore a lesion's
lateral coordinate, use a bounded anatomical/acquisition midline, and ordinarily
select source offsets -4, -2, 0, +2 and +4 before patient-LPS ordering. A full
Gemini proposal may be asymmetric only when it remains ordered, distinct and
keeps the paracentral planes at least two source intervals from midline; five
consecutive planes are rejected. T1 remains geometry-matched to T2, and `VOL`
labels must be identified as source-volume indexes rather than DICOM instance
numbers. Six requirements failed before correction. The changed boundary passes
174 tests and complete AI Imaging passes 850 with 8 pre-existing xfails and 3
pre-existing SWIG warnings. These tests establish deterministic sampling and
identity, not anatomical ground truth or diagnostic accuracy. See Eagle Eye
stage-two document section 46.

## Eagle Eye explicit per-card JSON transport (2026-09-01)

`code/ai_imaging/test_eagle_eye_focused_v3.py` and
`test_eagle_eye_llm_analysis.py` protect pipeline 6.2.0, verification prompt
5.0.0 and V5 manifest 2.6.0. Every named-level or additional-findings card must
write one sibling `.card.json` file whose image index, filename and card
metadata match the PNG, focus record and manifest binding. The saved request
must preserve the same ordered payload once per card, and the shared
EchoMind/GapGPT content builder must place exactly one compact JSON block
immediately before that image. Ordinary screenshots remain payload-free. The
four principal assertions failed before implementation. Offline reconstruction
of the latest saved source session produced two cards, two sidecars, two
bindings and two model-facing payloads with exact decoded equality. These are
identity and audit guards; they do not establish diagnostic accuracy. The
changed boundary passes 126 tests, complete AI Imaging passes 852 with 8
pre-existing xfails and 3 pre-existing SWIG warnings, builder package checks
pass 4 tests with 4 intentionally deselected, and all 462 plugin mirror pairs
match. See Eagle Eye stage-two document section 47.

## Eagle Eye card-first diagnostic prompt (2026-09-01)

`code/ai_imaging/test_eagle_eye_screening_attention.py`,
`test_eagle_eye_llm_analysis.py`, and `test_eagle_eye_grading_contract.py`
protect pipeline 6.3.0 and verification prompt 5.1.0. The default diagnostic
reader must bind every PNG to the immediately preceding `CARD_METADATA_JSON`,
record card identity in every audit row, resolve each bound attention exactly
once, prevent unmatched context or a whole-package safety sweep from creating
unbound findings, preserve the named card as task scope, and use a neutral
output template without a seeded level-specific diagnosis. Identity conflict
must be `INDETERMINATE`, not a silent transfer to an adjacent card. The four
principal assertions failed before implementation. The prompt-focused gate
passes 145 tests and complete AI Imaging passes 855 with 8 pre-existing xfails
and 3 pre-existing SWIG warnings. These guards establish prompt/transport
consistency, not diagnostic accuracy. See Eagle Eye stage-two document section
48.

## Eagle Eye atomic anatomy pipeline (2026-09-02)

`code/ai_imaging/test_eagle_eye_atomic_structure_pipeline.py`,
`test_eagle_eye_focused_v3.py`, `test_eagle_eye_llm_analysis.py`, and
`test_eagle_eye_anatomy_gate.py` protect pipeline 8.2.0 and atomic contract
2.3.0. `test_eagle_eye_card_template_registry.py` additionally protects the
official cross-MRI card registry and its lumbar runtime projection. A separate
temperature-0 Gemini gate must map anatomy without assessing
normality or pathology. Before that call, the workstation assigns only neutral
series plus sagittal- and axial-group identities from DICOM geometry. Sequence confidence is
persisted; a semantic T1/T2 label is exposed only when operator-confirmed or
high confidence. Gemini maps unresolved series to sequence roles, every neutral
sagittal group to a regional role, and every neutral axial group to a lumbar
level. Local validation rejects unknown or duplicate series, levels, groups and
tiles. DICOM LPS X and Z record physical order for audit but must not rewrite
sagittal regional roles or axial disc-level/subarticular/infrapedicular
semantics. The validator also rejects distant T1/T2 pairs, changed group bounds,
cross-group tiles, and out-of-group samples. The same immutable group IDs must
survive screening slots, evidence planning, and diagnostic card JSON.
Exactly five saved anatomy cards and JSON sidecars must bridge Gate 1 to Gate 2.
Disc, canal/neural, neural-foramen, endplate/marrow, and facet/posterior-element
screening must each receive exactly one matching card rather than raw atlas
pages. Neural-foramen and posterior-element screening may not collapse back
into one combined transport.
Gate 1 atlas pages must render immutable sagittal and axial geometry groups as
separate blocks and paginate only at group boundaries. Gate 1-to-2 cards retain
every original member of each included group: Disc and Canal give every complete
axial group its own row; Foramen gives complete right/left T2 and T1 lateral
groups separate blocks; Posterior Elements gives complete right-lateral,
central, and left-lateral groups separate blocks for both T2 and T1; Endplate
uses complete central T1/T2 groups. The layout contract records block boxes and
a minimum 32-pixel gap. Physical spacing is the primary cue, headers are
secondary, and color is tertiary. Gate 2-to-3 cards may select task-specific
members, but every selected slot records its persistent parent group ID and the
complete original membership. `test_screening_cards_preserve_complete_geometry_group_membership`
pins the complete screening handoff;
`test_disc_card_uses_three_t2_sagittal_planes_and_three_axials` pins focused
subset provenance; and
`test_diagnostic_subset_rejects_a_member_outside_its_parent_group` pins the
fail-closed boundary. Historical artifacts without the contract are explicitly
`legacy_unavailable`, never silently validated.
Each grouped request is JSON-only, temperature 0, and has a bounded
24000-token response allowance after live 7.1.0 exhausted 5996/6000 in all three
branches before complete JSON was emitted. Each one-card diagnostic request has
a 12000-token allowance. The narrower tasks are still expected to use compact
outputs; the ceilings provide reasoning and serialization headroom.
Truncated or unstructured output must fail the active gate rather than becoming
an empty handoff. Neither anatomy failure nor grouped-screening failure may
invoke the historical monolithic screen. Diagnostic-card construction failure
and an all-card diagnostic failure likewise may not invoke the old verifier.
Positive findings at one level
must split into independent structure cards with anatomy-specific sagittal and
axial evidence. Every Sol request must contain exactly one card. Card ID, level,
structure group, attention ID and status are validated before deterministic
merge; conflicting or omitted decisions become `INDETERMINATE`. Atomic request
and response artifacts must not overwrite sibling calls. The authoritative
axial level map must remain machine-readable in the aggregate stage-one JSON so
the audit gallery can display the anatomical gate without parsing report prose.
The gallery must separately expose the anatomy-mapping atlas, all five
intermediate anatomy cards, and the exact one-card input of each screen.
Gate 2 must emit only abnormal structure, immutable level, confidence, visual
abnormality magnitude, persistence, paired-structure laterality, and exact
evidence locations. It may not emit morphology, zone, stenosis, grade, space
effacement, neural contact/displacement/compression, or a companion checklist.
Disc, canal, recess, root, foramen, facet, endplate, and marrow abnormalities
must remain separate findings. Compact card metadata must not forward screening
interpretations or companion questions. Each Sol request classifies exactly the
structure bound to its card. Endplate rows require exact vertebral-surface
identity, and ligamentum flavum confirmation requires adjacent-slice
reproducibility plus objective thickness or direct stenotic effect. Both
screening and diagnosis temperatures are pinned to 0.
The new regression file failed before the module and structure grouping existed;
the compact-group guard failed before the original three-request contract
existed. The axial-order and four-request guards fail against 7.6.0. The
registry guard fails at import before the shared package exists, and its runtime
assertions fail while foramen/posterior screening remains combined. The
geometry-order, seeded-ID, and no-legacy-fallback guards fail against 7.3.0.
The historical 7.7 fail-before run produced 6 failures and 20 passes across the
anatomy and atomic files; after correction those files passed 27. The 7.9.0
neutral-geometry guards failed three focused boundaries before implementation
and now cover confidence provenance, neutral series/group rendering, arbitrary
group-to-level assignment, and physical-order audit without semantic relabeling. The 7.8.0
registry/anatomy/atomic boundary passes 33. Pipeline 8.0.0 added three
fail-before sagittal-group boundaries and an end-to-end diagnosis-card identity
guard. Pipeline 8.1.0 added two fail-before physical-layout boundaries. Pipeline
8.2.0 adds complete-group screening transport and parent-bound diagnostic
subsets. Complete AI Imaging passes 921 tests with 8 expected xfails and 3
existing SWIG warnings. Python compilation and mirror parity are verified
separately; live source validation remains separate.
These guards establish execution, identity, evidence selection and audit
behavior, not diagnostic accuracy.

`code/ai_imaging/test_eagle_eye_stage_audit.py` and
`test_eagle_eye_ui_boundary.py` protect the read-only `View stage images`
workflow. Only session-contained files may be presented. The gallery exposes
the stored anatomy/slot map, exact images for each screening branch, parse and
truncation state, session-local context images, every gated diagnostic card,
and the image set recorded for diagnosis. Opening it never recaptures a viewer
or follows an external attachment or source-DICOM path.

## Eagle Eye central-canal specificity and MR-myelography context (2026-09-03)

`code/ai_imaging/test_eagle_eye_canal_screening.py` protects pipeline 8.3.0,
atomic contract 2.4.0, anatomy-card schema 1.8.0 and screening schema 3.3.0.
It requires an auditable central-canal decision for every mapped axial group,
same-group axial citations, preserved-caliber/minor-impression rejection, and
independence from lateral-recess positives. Optional MR myelography is bounded
to two explicitly identified and identity-validated MR series, excluded for a
wrong study or burned-in annotation, and marked overview-only rather than an
anatomy-localization source. Six guards failed before implementation. Nine now
pass; the adjacent boundary passes 159 and complete AI Imaging passes 930 with
8 expected xfails and 3 existing SWIG warnings.

- Brain anatomical report grouping: `tests/code/ai_imaging/test_eagle_eye_brain_patient_report.py` verifies disjoint coverage of 34 cortical and 14 other paired labels, basal ganglia membership, unchanged measurement objects, regional PDF headings, future atlas label retention and repeated patient/page furniture.

- Brain native FreeSurfer research scoring: `tests/code/ai_imaging/test_eagle_eye_brain_centilebrain.py` covers demographic bounds, exact Aseg/eTIV features, changed reference model rejection, source image mismatch, local WSL paths, version pinning and research report separation. `AIPACS_TEST_REFERENCE_RUNTIME=1` enables actual pinned R model acceptance with synthetic data.

- Adjacent Brain reference ranges: `test_eagle_eye_brain_centilebrain.py` checks the requested 90% band formula, mm3-to-cm3 conversion and missing/nonphysical limits; `test_eagle_eye_brain_patient_report.py` verifies normal-range availability columns across anatomical report pages and retains DICOM scanner covariates.
- Potvin adult regional reference: `test_eagle_eye_brain_potvin.py` checks supported ages/scanners, incompatible estimator rejection, candidate-only UI status, and (with `AIPACS_TEST_REFERENCE_RUNTIME=1`) all 26 published models, P5/P95 inversion, log-volume intervals, source Z_OP/T arithmetic and adjacent report values.

- Brain study workflow: test_eagle_eye_brain_study_workflow.py verifies MRI routing, patient/study storage isolation, source identity rejection, explicit Qt sequence selection, disabled lesion analysis, and complete atomic PDF export without accessing the live clinical database.

- Brain launcher: the same file executes the real toolbar handler with synthetic active-viewer metadata; brain bypasses the lumbar picker, other MR retains its picker/cancel path, and MG/DX continue directly. The brain case failed before the 2026-09-05 live-test fix.

- Brain published interval integrity, side-specific ranges, age domain and stale-score rejection: `tests/code/ai_imaging/test_eagle_eye_brain_volbrain.py`.

- Brain cortical group summary: `tests/code/ai_imaging/test_eagle_eye_brain_lobar_summary.py` checks native parcel sums without parent double counting, incomplete coverage and explicit unmeasured lobar WM/thickness; PDF integration remains covered by `test_eagle_eye_brain_patient_report.py`.


EchoMind STT quality (2026-09-07): `code/echomind/test_transcribe_retry.py` guards clear default, manual noisy selection for microphone/file requests, invalid selection fallback, and preservation of retry mode.

## Paired locator clean-panel guards (2026-09-08)

`code/ai_imaging/test_eagle_eye_spatial_packet.py` now has nine passing guards.
The two paired-card additions verify complete physical order, measured spacing,
one locator line per card, exact clean-panel crop/resize pixels and rejection of
incomplete groups before writing. No real patient fixture is committed.

Printing background extension (2026-09-09): `test_printing_workflow.py` covers dark/white/transparent gaps, unchanged image pixels, persisted background selection and DICOM alpha compositing without black margins.

Printing mouse extension (2026-09-09): ten synthetic Qt event cases in `test_printing_workflow.py` cover ten-image Shift group preservation across tools/drags, Ctrl selection-only gestures, empty selection, right/middle buttons, selection replacement and overlay hit testing.

Printing Ctrl/Shift extension (2026-09-09): `test_printing_workflow.py` verifies Ctrl selection of only images 1/3/5, no edits to intervening images, single-item deselection, and repeated Shift extension/contraction from the original anchor. Three cases, two fail-before.

- Printing sheet removal: `tests/code/printing/test_printing_workflow.py::test_delete_current_page_removes_only_that_sheet` and `test_clear_or_delete_last_sheet_stays_empty_until_regenerated` cover page scope, navigation, clear-all, and explicit regeneration.

Printing fidelity and transport: `tests/code/printing/test_print_fidelity.py` covers absolute gray, uniform values, crop, YBR color and width-one threshold. `test_printer_transport.py` covers default transfer syntax, warning detail, invalid settings/payload and Windows end/error/abort results.

Printing enlarged scout: `tests/code/printing/test_scout_size.py` covers shared geometry; scout default, persistence/reopen, export and separator guards live in `test_printing_workflow.py`.

Scout uniformity: `test_scout_size.py::test_enlarged_scout_fits_without_overlap` also requires identical non-scout dimensions, protecting against enlargement leaking into the first row/column.

Fixed 2x2 scout: geometry tests verify exact unmerged grid positions; `test_two_by_two_scout_repages_without_losing_images` verifies capacity, navigation, deletion and clearing.

Diagnostic count excludes Scout: `test_scout_size.py` verifies exact capacity and adaptive landmarks. `test_reference_labels_match_preview_export_and_page_image_numbers` checks visible label lifetime and export/page numbering parity.

Printing grid/background: `test_grid_stays_visible_in_preview_and_export_for_all_backgrounds` covers opaque contrasting borders and independent transparent page fill.

## Viewer Configuration storage cleanup (OPT-59, 2026-09-12)

- `code/storage/test_storage_cleanup_filtered.py` protects Imported On retention,
  unknown-date preservation, managed-root containment, DB preservation after a locked-file
  failure, filtered selection, and explicit cascade-independent Clear ALL deletion.
- `code/storage/test_storage_cleanup_consistency.py` protects link-safe single-pass sizing,
  DB/disk consistency repair, thumbnail-cache invalidation, and fail-closed full cleanup.
- `code/storage/test_storage_cleanup_panel_async.py` protects GUI-thread affinity, transient
  panel/thread lifetime, asynchronous drive/preview/consistency work, request coalescing,
  and the fail-closed import/download/viewer activity probe.

## EchoMind report font hierarchy (2026-09-13)

`code/reporting/test_echomind_font_hierarchy.py` verifies actual character sizes
across display and normalized Reception export, four-level hierarchy, 10-40px
scaling, reversible resizing, unchanged saved HTML, historical headings, edited
point sizes, list items and plain text. Five guards failed before the fix.
Together with reporting, GUI export and mirror checks: 119 passed (exit 0).
See `../docs/echomind/REPORT_TYPOGRAPHY_2026-09-13.md` for the pending live gate.

## EchoMind pathology organization (2026-09-13)

`code/reporting/test_echomind_pathology_layout.py` guards numbered findings,
organ groups, sentence breaks within findings, item margins, unchanged decimals,
abbreviations and punctuation, and identical Qt/Reception output at two font
scales. Eight failures before repair; reporting/GUI export 126 passed and mirror
guard one passed. See `../docs/echomind/REPORT_TYPOGRAPHY_2026-09-13.md`.

## EchoMind all-modality and edition coverage (2026-09-13)

`code/reporting/test_echomind_modality_layout.py` reads all six current modality
schemas, checks shared heading/body sizes and Reception parity at two scales,
and guards six report entry points. Four specialty-heading failures preceded
repair. `code/builder/test_distribution_profiles.py` checks byte preservation of
both EchoMind renderers in all three editions. Combined focused selection:
164 passed, exit 0. See `../docs/echomind/REPORT_TYPOGRAPHY_2026-09-13.md`.

## Shared multi-study projection (OPT-35, 2026-09-14)

`code/viewer/test_unify_multistudy_projection.py` exercises the actual controller with
synthetic inputs and real normalization/allocation/ref authorities. Fourteen cases passed
before and after extraction; 15 final cases cover same/empty labels, missing-number spellings,
same-study collisions, still/cine counts, exact external paths, leading zeros, later study
admission, idempotence, history ordering, single-study bypass and input ownership.
`test_series_ref_stateful.py` now consumes the production helper instead of a test-local
replica. `test_primary_bucket_fallback.py` verifies path/slot output at the new seam.
Focused selection: 171 passed; separate property selection: 1 passed (150 configured examples,
up to 40 steps), all exit 0. See the OPT-35 September 14 master-plan entry and provenance record.

## Home Local thumbnail identity prerequisite (2026-09-14)

`code/ui_services/test_home_local_thumbnail_projection.py` executes the production
projection with isolated synthetic I/O and the real display-key allocator. It verifies
successful collision allocation, leading-zero labels, exact storage paths, instance/frame
counts, non-pixel exclusion, partial failures, empty queries and early dependency failure.
Three guards failed before repair; all five pass afterward. The focused Local, identity,
collision and thumbnail selection is 120 passed, exit 0 (`--reruns 0`). This does not verify
the still-pending right-panel action route. Details: the implementation record in
`../docs/plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md`.

## Home card metadata preservation (OPT-60, 2026-09-14)

`code/ui_services/test_right_panel_metadata_contract.py` executes the production
extraction and both card render schedules with synthetic inputs. It checks exact
study/series identity, display/storage separation, leading-zero raw numbers,
same-study and cross-study duplicates, object versus frame counts, unchanged aliases
and defaults, and detached metadata without patient/pixel payloads. A real offscreen
Qt card verifies the visible 420-frame count while object count stays 2 and the
generic opaque-key contract is unchanged. Four fail-before cases, four preserved
baseline cases; all eight pass after. Focused adjacent selection: 205 passed, exit 0.
No live database/socket calls. Home ordinal/action routing remains a separate defect.

## Home existing-tab click identity (OPT-35/OPT-60, 2026-09-14)

`code/ui_services/test_home_series_action.py` has 22 guards: real Qt immediate/
progressive card clicks carry frozen study/series UIDs rather than ordinals;
cleared/superseded renders cannot dispatch stale clicks; the Home handler delegates
to its tab service; destination-owned keys preserve duplicate/leading-zero/external
path cases; foreign, incomplete, ambiguous, nonnumeric and closed targets fail
closed; activation is followed by identity revalidation. Four signature guards
prevent same-PNG coalescing of different action identities, while equivalent input
still coalesces. A source wiring guard pins the typed Home signal.

Initial pre-fix result: four existing-behavior failures and seven missing-API
failures. The four signature cases separately failed before that prerequisite.
`code/test_right_panel_input_sync_guard.py` now executes both real renderer guards
instead of relying on constructor text in a 1600-character source window; its
obsolete immediate-render quarantine entry was removed after XPASS. The metadata
harness follows the extracted factory without dropping assertions. Focused total:
238 passed, exit 0; property projection: 1 passed, exit 0. This does not verify
Home drag/retry, complete offline downstream behavior, or live/installed rendering.

## Eagle Eye Brain activity feedback (2026-09-14)

`code/ai_imaging/test_eagle_eye_brain_progress.py` protects pending-stage display, indeterminate rather than fabricated percentage progress, cancellation feedback and animation teardown on success/failure.

`code/ai_imaging/test_eagle_eye_brain_multi_t1.py` protects signed volume differences, ICV normalization, preflight identity, primary preservation, partial failure records and DICOM field reset/population.

## Eagle Eye background PACS interaction (2026-09-14)

`tests/code/ai_imaging/test_eagle_eye_background.py` verifies nonmodal Brain/lesion/Alignment popups, close/reopen preservation of the same active Future, explicit owner teardown, cancellation of pending selectors, compact MG/DX progress and unrelated PACS button input. Four guards failed before the correction; all six pass afterward.

- Lesion clinical context and MS comparison: `code/ai_imaging/test_lesion_clinical_context.py` covers required clinician indication, SVD unassessed fields, identity/date guards, conservative spatial candidate categories, native-volume arithmetic, report revision preservation and real synthetic rigid registration. Live acceptance remains separate.

- SVD spatial review: `test_lesion_clinical_context.py` also protects clinician-only Fazekas, invalid grade rejection, native-volume conservation and retention of candidates outside cerebral WM.

- MS contact/topography: `code/ai_imaging/test_ms_topography.py` protects face-only contact, intervening WM, missing-mask uncertainty, one-component double counting, small-candidate retention, conditional conclusions and PDF scope. `test_eagle_eye_lesions.py` verifies MS-only pipeline routing.

## WMH reference readiness (2026-09-15)

`code/ai_imaging/test_wmh_reference.py` guards normalization scale/zero/invalid inputs, reference-age boundaries, missing-model behavior, stale percentile rejection and SVD-only report explanation. This does not validate a fitted normative model.

## Eagle Eye selection refresh (2026-09-15)

`code/ai_imaging/test_eagle_eye_workspace_entry.py` covers initially empty workspace followed by a loaded brain T1, and rejects another study before opening the picker. Both guards fail before the fix.
# WMH graphical reference guard (2026-09-15)

`tests/code/ai_imaging/test_wmh_graphical_reference.py` checks ordered traced
quantiles, age bounds, log interpolation, uncertainty at boundaries, zero burden,
stale cached fractions and explicit non-diagnostic PDF source attribution.
# Manual segmentation revision guards

Advanced Analysis presentation: `code/mpr/test_analysis_presentation.py` checks
distinct small icons, nested action identity/dispatch and disabled state, screen
containment, idempotence and hidden-window preservation.
The curated-dropdown guards verify real MPR Home dispatch, required tool promotion,
hidden template/pipeline entries, finder removal and late menu refresh.
Panel guards verify scoped styling, one branded heading on repeated selection,
preserved callbacks/disabled states/numeric values, custom measurement icons and
intact grid positions, spans and stretch when adding the header.
The default-geometry cases require 70% of available screen dimensions, independent
of supplied viewport size. `code/system/test_numeric_control_style.py` checks
arrow contrast/click targets, stepping/limits/disabled state, fractional steps,
NoButtons preservation and shared SVG asset validity and Advanced payload parity.
Compact title guards in `test_advanced_analysis_brand_version.py` reject patient/study text in OS titles.

Advanced Analysis display version: `code/mpr/test_advanced_analysis_brand_version.py`
executes synthetic title composition and checks Python/native version declarations
against pyproject. Seven fail-before guards; 34 adjacent launch/package passes.
Native rebuild and fresh GUI version acceptance remain pending. See the
September 15 Advanced Analysis UI/UX audit under docs/reports.

`tests/code/ai_imaging/test_manual_brain_review.py`: geometry, label identities,
empty corrected masks and unsaved correction refusal. Background interactions
remain covered by `test_eagle_eye_background.py`.

Startup welcome text: `code/mpr/test_analysis_presentation.py::test_startup_notice_uses_product_version_without_changing_warning_or_consent` verifies product-version alignment without changing clinical disclaimer, buttons, checkbox state or unrelated error text.


## Advanced preview file/pixel metadata (2026-09-16)

`code/viewer/test_advanced_preview_metadata.py`: six synthetic guards for filesystem
count/order, shuffled DB order, SOP/IPP/pixel agreement, actual single-slice number,
unreadable headers, multiframe and decoded-depth mismatch deferral. Three original
behavioral failures reproduced before the fix. DB path isolated and pools cleared.


## Native loading cover after hidden-page callbacks (2026-09-16)

`code/viewer/test_advanced_loading_cover.py` now includes new/reused background load
requests while the viewport is hidden, return-to-page restoration and completion
while hidden. Two failing-before cases; overlay/liveness/reentrancy/lifecycle suite
46 passes. This is not a native GUI acceptance receipt.

## Advanced filter timing (2026-09-16)

`code/viewer/test_advanced_filter_timing.py`: four guards covering pre-instrumentation synthetic MR/CT pixel hashes and geometry, one privacy-safe stage record, and no completion claim for skipped/failed pipelines.


## MPR partial-volume admission (2026-09-16)

`code/viewer/test_mpr_partial_volume_admission.py`: ten cases cover four route names
with explicit preview or 8/104 metadata mismatch, complete volume reuse, unchanged
VTK MTime/metadata, and recovery messages. Nine failures before the fix; 192 combined
MPR/launch/US passes. No patient data or database access.

## Advanced decoded cache integrity (2026-09-17)

`code/viewer/test_advanced_cache_integrity.py`: eleven synthetic cases cover mismatched cache admission, no Advanced metadata-only disk/live growth, Fast growth preservation, preview/full distinction, multiframe forms and full-cache fallback after invalid hot/main/index entries. Five original failures reproduced. No patient data or DB access.


## MPR deferred-build teardown reentrancy (2026-09-17)

`code/mpr/test_mpr_deferred_build_reentrancy.py`: synthetic event-pump closure must
prevent layout/VTK access and dismiss the dialog; normal and failed builds restore
updates and dismiss the dialog. Four cases; two fail before correction. No DB or PHI.


## Advanced preview plain-text rendering (2026-09-17)

`code/viewer/test_advanced_counter_text_backend.py`: real VTK backend selection for known/unknown total and a cold native offscreen render that must not import Matplotlib. Three fail-before guards; no PHI/DB. Paired with `test_advanced_slice_progress.py` for count/scroll semantics.


## Advanced heterogeneous presentation frames (2026-09-17)

`code/viewer/test_advanced_presentation_sequence.py`: 10 synthetic cases cover worker
routing, native-size/RGB retention, per-frame/custom W/L, offscreen VTK scroll and return
to spatial series, order/identity, MPR/full-cache rejection, immutable metadata snapshots,
preview/budget limits, overlay origin/alpha and same-series tuple refresh. DB isolated.
Loader and refresh fail-before proof recorded in VTK report. Live GUI still pending.


## Advanced DX native-size admission and calibration labels (2026-09-18)

`code/viewer/test_advanced_presentation_sequence.py` now has 15 cases. Added DX missing-
IPP/IOP admission, exact pixels/VOI and anisotropic detector spacing, three ruler calibration
labels, and a full 4528 x 6869 synthetic worker-to-native-render check. No clinical fixtures;
DB isolation retained. Admission and two label cases have fail-before proof. Focused suite
132 passes plus one builder mirror pass; fresh-source drag/drop acceptance remains open.


## Total Spine direct reader correction (2026-09-19)

`code/ai_imaging/test_total_spine_editing.py` covers atomic line translation,
endpoint rotation through Qt mouse input, clickable anchor numbering, reference
remapping, undo, pedicle grade invalidation, source bounds and physical perpendicular
angle construction including obtuse angles. Four feature guards failed before
implementation. Focused Total Spine plus builder selection: 84 passed; native source
entry is blocked and is not substituted by offscreen input.


## Total Spine classic construction and embedded UI (2026-09-19)

`code/ai_imaging/test_total_spine_workspace.py` verifies source-connected endplate
extensions with physical perpendiculars, native tab creation/reuse before viewer
readiness, real header button dispatch and all unnumbered candidate visibility.
Two guards failed before the fix. Focused Total Spine/workspace/background/builder
selection: 126 passed. Offscreen visualization is separate from pending live source
acceptance after human launch/sign-in.


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


## Advanced DOC/SC admission guards (2026-09-20)

`code/viewer/test_advanced_presentation_sequence.py`: 19 cases including worker admission
at 100000 and 7 (both failed before), exact RGB preservation without enhancement, native DOC
scroll/reset, and rejection of encapsulated-PDF classification as raster presentation. Synthetic
fixtures and isolated DB only. 137 focused/adjacent/parity passes; real source drop gate pending.


Advanced DOC budget guard (2026-09-20): presentation suite now 20 cases. New seven-page
budget test fails before correction; verifies full-page delivery at the calculated limit and
rejection before decode below it. Full focused/adjacent/parity result: 138 passed, exit 0.

### Eagle Eye active-series handoff and activity (2026-09-20)

`tests/code/ai_imaging/test_eagle_eye_selected_series.py` covers exact viewport UID,
2D entry fallback, cross-study rejection, projection prompts, no alternate-series
fallback, per-series review retention, unreviewed auto-proposals, Brain input
continuation, lesion-role preselection and background activity lifecycle.
See `docs/modules/EAGLE_EYE_WORKSPACE_ENTRY_2026-09-11.md` for boundaries and live gate.

### Eagle Eye preparation versus result tabs (2026-09-20)

`code/ai_imaging/test_eagle_eye_result_tabs.py` covers an analysis-free preparation
sidebar, module result tabs, single-viewer ownership/activation, nonactivating
cached results, persistent reader corrections, and Bone Age result application
without GUI-thread reads. Six guards pass; two failed before. Native rendering
and feedback acceptance remain pending; see the workspace entry guide.

### Total Spine action discovery (2026-09-20)

`code/ai_imaging/test_total_spine_analysis_actions.py` verifies visible ROI/AI/angle
controls, valid-input/busy gating, no automatic clinical-review flag, and the
explicitly named Hide action. Two guards failed before; 78 related tests pass.


`code/ai_imaging/test_spine_progress_numbering.py` covers completed-stage percentage
rendering, worker progress milestones, cancellation without false completion,
assigned-anchor propagation, anatomical exceptions and single-step undo. Synthetic
inputs only; 81 related tests pass with the test endpoint disabled.


## Advanced CT preview/order/window/drag guards (2026-09-20)

`code/viewer/test_advanced_preview_metadata.py` now has 12 cases: exact source/display
prefix and first-frame selection, header/decode deferral, worker-sourced WW/WC without a
scroll-time reopen, large Advanced drag distance/endpoints, unchanged other-backend drag,
and actual offscreen ImageViewer2D preview-to-full displayed SOP continuity. Seven failing
assertions demonstrated before changes. Broad adjacent result 208 pass/4 existing geometry
xfail; extra native transition 1 pass. Synthetic fixtures and redirected DB only.


Large-CT final guard update: 13 cases in `test_advanced_preview_metadata.py`, including
older cached-header memoization (three calls before, one after). Final combined suite:
210 passed, four existing quarantined display-geometry xfails, exit 0.


Advanced single-render extension (2026-09-20): native preview/full guard in
`test_advanced_preview_metadata.py` now counts draw events, compares framebuffer pixels
against legacy, preserves camera/SOP order, exercises fast drawing and preparation-error
cleanup. Failed before with 2 draws, passes with 1. Adjacent US/conservative fake states bind
the extracted visual helper without weakening assertions. Final 253 pass / 4 existing
quarantined geometry xfail, exit 0. Real large-stack source interaction remains pending.


`code/ai_imaging/test_spine_guided_review.py` covers per-measurement prerequisites,
selected S1 placement and contextual controls, preservation of unrelated angle
approval, and dependency-specific guided confirmation invalidation. Synthetic
inputs only. 82 focused/adjacent guards pass; native application gate pending.


## EchoMind Reception normal templates (2026-09-20)

`code/echomind/test_reception_templates.py` covers modality resolution, provenance,
non-overwriting imports, pagination, cancellation, identity ranking and prompt precedence.
`gui/test_reception_template_ui.py` covers off-thread fetch/save, current modality, review
gating, stale connection rejection and closing during download.
`live/test_reception_template_reporting.py` is a synthetic-only, opt-in company-provider
check for all six report modalities; it is separate from native source-GUI acceptance.

`code/echomind/test_turbo_supplied_normal_template.py` covers the default enabled
regional V2 route: supplied templates survive for all six modalities and untemplated
MRI retains its existing V2 generation structure. Five cases failed before the fix.

`code/echomind/test_template_organization.py` covers source-ID completeness, unchanged
source storage, draft/published separation, cancellation, stale identity/edit rejection,
resume without overwriting edits, failed-item isolation, and HTML table/entity fidelity.
`gui/test_reception_template_ui.py` also covers sequential organization and final text
publication off the GUI thread, plus cancellation after a Reception refresh.

### EchoMind named pathology codes (2026-09-21)

Template organization retains source-referenced code labels, complete macro sentences and fillable fields. See `docs/echomind/RECEPTION_NORMAL_TEMPLATES_2026-09-20.md`; guards: `tests/code/echomind/test_template_organization.py` and `tests/code/echomind/test_normal_template_prompt.py`. Template-only activation rules leave no-template routine reporting unchanged.

### Template measurements and mammography choices (2026-09-21)

See `docs/echomind/TEMPLATE_MERGE_VALIDATION_2026-09-21.md`. `tests/code/echomind/test_template_organization.py` guards conditional choice banks; `tests/code/echomind/test_normal_template_prompt.py` guards template-only fidelity instructions; `tests/live/test_template_measurement_merge.py` supplies eight opt-in synthetic provider checks. Real-case and native GUI acceptance remain separate.

### EchoMind bilingual wording and review (2026-09-21)

`tests/code/echomind/test_bilingual_templates.py` covers paired persistence, stale/ambiguous references, exact phrase reuse, changed unit/slot rejection, mixed-language source detection and Correction inheritance. `tests/gui/test_reception_template_ui.py` covers preparation without publication and explicit Save & Use. See `docs/echomind/BILINGUAL_TEMPLATE_VALIDATION_2026-09-21.md`.

## Breast and Bone Age local engine boundaries (2026-09-21)

`tests/code/ai_imaging/test_eagle_eye_local_engines.py` covers wrong-study/modality,
multiframe, duplicated inputs, verified sex, source hashes, bundle corruption,
cancellation, strict weight loading, API/training isolation and MG/DX local routing.
See `docs/modules/EAGLE_EYE_BREAST_BONE_LOCAL_2026-09-21.md` for execution evidence.
