# AI-PACS — Software Optimization, Stability & Reliability Master Plan

## 2026-09-26: OPT-51 Eagle Eye 2D worker reliability

The explicit 2D lesion worker retains required model/runtime hashing while avoiding unrelated 3D model/header verification. Short scratch execution and extended-path artifact publication address a reproduced Windows service failure. This does not alter PACS acquisition, download U0-U5, viewer domains or 3D inference. Actual source GUI remained interactive during a 150 s analysis; isolated Razi completion was 152.29 s. These are one-case end-to-end timings, not controlled speedup or accuracy claims. See [method and acceptance](modules/eagle-eye-server-development/docs/LESIONS_2D_2026-09-26.md).


## 2026-09-26: OPT-58 / OPT-60 canonical thumbnail order and row ownership

**State: code-verified; fresh-source GUI and artifact acceptance pending.** A large
Patient-Tab sidebar could receive two producer generations with different order. The
new generation reused an existing card by key but did not move it to its planned row,
so it could overlap another card and make an exact history document appear missing.
The same history priority was implemented independently at several producer seams.

One pure `series_identity` authority now orders series within each study by original
SeriesNumber, with exact 100000 history priority and offset-insensitive identity. Home,
cached files, server/local entries and grouped rows consume it. Study group order,
slot/offset allocation and storage paths are unchanged. The bounded scheduler owns
replacement geometry and exact planned-card totals; headers retain per-study counts
and never enter the total.

Two direct guards failed before and pass after. The affected/adjacent suite is 230
passed; release-candidate packaging inputs are 42 passed; compilation and diff checks
pass. These core sources have no plugin payload mirrors. The repository-wide mirror
gate remains independently red for an unrelated existing Download Manager source/
payload drift; this fix did not edit or synchronize it. Applicable source path is
shared by Standard Client, ARM64-emulated Client and Eagle Eye Server under both
packagers; no candidate build or artifact acceptance was performed. Required live
gate: fresh source launch/login, large single- and multi-study open/reopen, exact
history visibility, unique card rows, stable headers, correct per-study/total counts,
and unchanged thumbnail action/download behavior. This is a bounded U0 presentation
correction and does not advance download U1-U5 or viewer-domain work.

## 2026-09-25: OPT-51 co-located source storage implementation

Owner-authorized paired PACS/Eagle Eye change implements atomic PACS DICOM
publication and attested, read-protected same-volume source hardlinks. Three
synthetic 16 MiB inputs now add zero duplicated DICOM payload instead of 48 MiB.
Legacy, cross-volume and unsupported storage retain copies. Existing model/viewer
domains and Download Manager are unchanged. 125 workstation plus 6 PACS tests
pass (exit 0); 472 mirrors match. Source GUI unavailable; no deployment/artifact
acceptance. See the [owning Eagle Eye receipt](plans/architecture/EAGLE_EYE_SERVER_CLIENT_PLAN_2026-09-21.md#2026-09-25-co-located-pacs-source-sharing-opt-51)
for source contract, rollback, limitations and next-build matrix. This does not
advance or bypass the separate U0-U5 download queue.

## 2026-09-25: OPT-04 / OPT-51 PACS client/server contract review

OPT-60 Advanced frame follow-up: validated per-frame planes now support reference
lines and synchronous navigation without opening MPR volume admission. The VTK
owner receipt records fail-before evidence, 123 passing checks, 606 structurally
valid real-input planes, 472 matching mirrors and pending fresh GUI/clinical
acceptance. No advancement of the independent shared-pipeline workstream.

OPT-60 Local DX thumbnail follow-up: user-authorized maintenance extends the
existing thumbnail worker adapter to one identity-checked DX Presentation object.
The synthetic PNG guard fails before the change; 116 affected/adjacent/builder
checks pass afterward and 472 mirror pairs match. No viewer runtime or U0-U5
progression changes. The UI-stall owner receipt records limits and scoped rollback.
Fresh source GUI acceptance remains blocked by the absent test endpoint and needs
a human fresh source launch/login; existing full-build/artifact gates remain open.

Related OPT-60 viewer-owned maintenance: Enhanced MR 2D presentation is now
code-verified (47 related tests) and prepares all 606 affected frames read-only.
The VTK owner receipt documents frame identity, nonspatial limits, rollback,
Client/Server applicability and pending fresh GUI/artifact acceptance. This is
not spatial reconstruction or advancement of the independent Unify workstream.

Source/offline evidence is recorded in the [existing shared-pipeline report](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-25-cross-repository-pacs-transfer-review-opt-04--opt-51).
The workstation uses Socket JSON/Base64 batches; Eagle Eye Server uses REST
location resolution plus accessible storage staging, without automatic Socket
acquisition on a cache miss. Confirmed fragmented-prefix handling, offset overlap,
and advisory Socket authentication require coordinated server/client correction.
U1/OPT-04 retains ownership of SOP manifests and authoritative completion before
throughput tuning; OPT-51 retains source preparation/reuse. Existing U0-U5 gates
and ownership order are unchanged. No runtime fix or speedup is claimed.
Focused baseline: 87 passed, 8 stale structural failures, 5 skipped absent-helper
tests; exit 1. Live throughput/GUI acceptance was not performed for this review.

## 2026-09-24: OPT-60 Local multiframe thumbnails and Advanced empty hint

Related OPT-23 follow-up: native drag-hover exposed Home before mouse release.
The VTK owner recurrence receipt records live pre-fix reproduction, opaque hover
backing correction, fail-before/pass-after guard and 32 passing focused tests.
Fresh post-fix source GUI and artifact acceptance remain pending; no U0-U5 advance.

The existing UI-stall and VTK owner reports record the two explicitly requested
maintenance fixes: Enhanced MR PNG repair independent of spatial preview admission,
and fully opaque painting of the empty native-viewer hint. Both have fail-before /
pass-after guards; three read-only real-input thumbnail decode probes pass. Source
GUI acceptance and every produced-artifact gate remain pending. This does not
advance U0-U5 or claim a performance/KPI improvement. Rollback and per-edition
build handoff are in those owner records. MCP connection diagnosis is recorded in
the agent control guide; no launch defaults or production gateway settings changed.

## 2026-09-20: OPT-60 first-viewer graphics-profile I/O

**State: fixed and code-verified; fresh-source KPI acceptance pending.** The latest
source session contained a 413.6 ms GUI-thread stall in
`resolve_gpu_boost_plan -> resolve_graphics_profile -> load_runtime_profile ->
Path.read_text` during viewer construction. This was duplicate work: `main.py` had
already read the profile, probed graphics support and persisted the result before Qt/VTK
startup. Every later viewer independently repeated that process.

The bootstrap graphics result is now primed into one process-owned snapshot in
`modules.viewer.gpu_boost`. Fast and Advanced consume the same immutable policy without
another runtime JSON read or graphics probe on the Qt thread. Repeated viewer creation
reuses the snapshot. Saving the GPU preference invalidates both cached views immediately;
the existing restart-required policy remains unchanged. No backend choice, decode,
render, download, thumbnail, DICOM or packaging contract changed.

The reuse and invalidation guards failed before implementation (2 failed / 6 passed).
The final GPU-boost file passes 9 tests; the graphics/runtime/build/WoA boundary passes
28 tests with one unrelated deselection, direct exit 0. Python compilation passes and
all 468 source/payload mirror pairs match. Required live gate: fresh source launch,
open the first and subsequent patient viewers in Fast and Advanced, verify identical
backend/GPU status and require no GUI-thread runtime-profile read below
`resolve_gpu_boost_plan`. This slice does not close the separate Advanced presentation
first-image metric, GUI-thread DICOM header reads or native COM event.

## 2026-09-20: OPT-60 shared viewport drag-hover activation

**State: fixed and code-verified; fresh-source native drag acceptance pending.**
Thumbnail drag traversal had two different input policies. The Advanced mixin already
had a 120 ms / 8 px dwell state machine, but its internal series MIME bypassed that
state and highlighted every viewport immediately. `QtFastContainer` had no dwell state
at all. Crossing pane 1 on the way to pane 2 could therefore flash pane 1 as active.

One UI-input-only `_DropHoverDwellMixin` now owns hover timing for both production
viewport containers. Movement beyond the existing tolerance restarts the dwell; leave,
drop and malformed payloads stop it. A deliberate quick drop is still accepted before
the highlight arms, and each backend keeps its own drop dispatch, decode, cache and
render path. The required `QTimer.singleShot(0, ...)` series-switch handoff remains
unchanged, so no OLE/COM work was moved into the native drop callback. The quarantined
legacy A/B viewer keeps behavior parity without becoming a new production authority.

Two behavioral guards failed before the correction: Fast had no hover state and
Advanced armed internal thumbnail MIME immediately. Final focused replacement/hover
suite: **22 passed**. Adjacent progressive, coalescing, multi-series, no-abandon,
stacking and split-viewer selection: **199 passed, 15 GUI-tier skipped, 1 quarantined
xfail, 1 unrelated deselected**, exit 0. Python compilation passes. The broader run's
one unrelated failure is the existing split-test spinner double lacking the newer
`hide_loading_after` API; it is not counted as a hover pass or fixed here.

Live gate: in a two-or-more-pane layout, drag a thumbnail across pane 1 into pane 2 at
normal and slow speeds. Traversed panes must not flash active; pausing on the intended
pane must show one stable highlight; a quick release must still load exactly the dropped
series in that pane. Repeat in Fast and Advanced and check session-scoped logs for one
drop apply, no duplicate switch, no transient top-level window and no stall/crash.
This bounded correction does not advance the `U0`-`U5` execution ledger.

## 2026-09-18: canonical Unify continuation queue and evidence baseline

The current single execution order is the `U0`-`U5` ledger in
[`UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md`](plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md#current-execution-ledger---2026-09-18).
It supersedes any older text that appears to authorize parallel shared-pipeline work.
The active slice is **U0: accept or reject the already-landed ordered Local catalog
owner and completed-load handoff**. Do not begin another thumbnail optimization,
download-state cutover, invalidation implementation or branch retirement until U0 has
a fresh source-GUI receipt. A failure is fixed inside the same owner; it is not bypassed
with another producer, cache, callback or fallback.

After U0, the mandatory order is: **U1 authoritative download completion -> U2 primary
per-series state authority -> U3 one invalidation bus -> U4 shared chokepoint/path
retirement -> U5 installed/restart/stress closure**. Fast, Advanced and every VTK tool
retain private decode/cache/render/lifecycle implementations throughout this sequence.

### Evidence-based progress statement

- Validated UI-stall events above 100 ms fell from 711 to 218, a 69.3% reduction in
  event count. The p95 rose from 562.1 to 706.4 ms because fewer small stalls left a
  distribution dominated by the remaining large events; this is not uniform latency
  improvement.
- The named exercised GUI-blocking stacks disappeared from their tested workflows.
  Fast Viewer handler time was already healthy (about 32 ms median / 70 ms p95) and is
  not credited to Unify. Cold Local catalog completion remains open even when card apply
  and the Qt event loop are responsive.
- Cross-PC ERROR totals are classification evidence, not a before/after rate: 3,017 of
  3,243 ERROR lines in the archived client window and 92 of 179 in the current developer
  window belong to the socket-request family. The windows, workload and duration differ.
  This shows that a large operational-error family is at the network/download boundary;
  it does not prove server fault or Unify regression.
- Recent developer native evidence contains 12 access-violation records correlated with
  application shutdown and 27 non-terminal COM `0x8001010d` records, with no Fatal Python
  marker. The exact native owner is still unproved. Treat shutdown/lifetime as a separate
  stop condition, not as evidence that shared identity/catalog/download routing failed.

The defensible conclusion is **substantial but incomplete improvement**: Unify removed
many duplicate-authority, stale-callback and GUI-thread-I/O failures, but the remaining
risk is distributed across cold first-touch I/O, download/network convergence, and
native Qt/VTK/QObject teardown. There is no evidence for one unidentified global defect,
and there is no basis for declaring the remaining ten percent closed. Each U0-U5 slice
must retain separate states for code-verified, live-verified and installed/release-ready.

## 2026-09-19: hidden Home work at patient-tab handoff (OPT-58 / OPT-60)

**State: fixed and code-verified; fresh-source GUI/KPI pending.** The latest run
contained two different delays. Historical Local studies with no producer index still
performed their expected first verification. Separately, a fully indexed two-study
case resolved 24 and 15 series in tens of milliseconds but its patient sidebar needed
18.822 seconds. Its maximum GUI card apply was only 21.17 ms. During that interval the
now-hidden Home right panel logged preparation of all 39 images over 15.030 seconds and
consumed approximately one CPU core. The remaining warm delay was therefore lifecycle
contention, not another catalog/index failure.

The existing Home render generation now pauses when its panel is hidden: no new image
read is admitted, the owned progressive timer stops, and a return to Home resumes the
same generation. One in-flight worker read is allowed to complete because Python cannot
safely cancel native file/decode work already running. Existing cards, exact action
identity, ordering, render signature and prepared QImage data survive the suspension.
This is a lifecycle correction inside the current owner, not a new cache, producer,
fallback, executor or viewer path. Both immediate and progressive fail-before guards
now pass; the four adjacent Home render/manager suites pass 68 cases and the broader
Home/thumbnail/sidebar selection passes 163. Compilation and scoped diff checks pass.
U0 remains open
until a restarted source run proves that a large Home preview stops competing after
patient-tab activation and that returning Home resumes cleanly without overlap, jump,
wrong counts, error/native fault or lost double-click action.

## 2026-09-19: legacy Local backfill live evidence (OPT-58 / OPT-60)

Two cold Local batches in the latest normal-source session scanned all 18 and 13
series in 9.175 s and 6.333 s. A read-only post-run audit found every row persisted as
schema-1 `Verified`, with valid count relationships and exact current managed-directory
revision (18/18 and 13/13). The same session's already indexed 24- and 15-series cases
resolved in 39.70 ms and 23.74 ms. Therefore the remaining delay is the intentional
one-time verification of historical/restored data, not a repeated-backfill defect.

Do not add a startup/library-wide scanner or another catalog/cache path. Import and
Download own new-generation publication; the existing Local worker owns legacy
self-heal. A real close/reopen construction remains the only open gate for these two
cases because the live control inventory has no tab-close action and the accepted
open command only activated the existing tab. Require `indexed=<all> scanned=0`, exact
identity/counts/pixels and clean scoped logs. See the canonical UI-stall receipt for
the evidence and limitations.

## 2026-09-19: U0 patient-open identity and pre-construction admission (OPT-35 / OPT-60)

**State: fixed and code-verified; fresh-source GUI pending.** A Local patient row with
an empty primary Study UID still resolved to an owner-filtered study set, but the open
path continued with the empty primary. The cached-thumbnail helper consequently formed
the thumbnail root itself, enumerated 2,635 unrelated study directories and returned no
cards after 13.825 seconds. The correction is at the existing patient-study authority:
one pure finalizer promotes the first resolved UID, preserves selected-first order and
fails closed for absent or owner-inconsistent identity. The filesystem helper rejects an
empty UID as defense in depth. This does not add a source, fallback, index or cache.

A separate fifth-tab trace showed another admission-order defect. Home constructed a
real `PatientWidget` and launched its pipeline before the tab manager rejected the
four-tab capacity. The modal warning then created a nested Qt event loop while qasync
tasks from the orphan widget were runnable, producing task re-entry errors and a
22.823-second failed open. `HomeTabService` now owns a bounded reservation set, counts
active tabs plus outstanding reservations, and admits before construction. Successful
registration commits; all failure exits abort. The tab manager retains the final check
as a defensive invariant rather than an alternate admission path. Capacity UI is posted
only after the active coroutine returns.

Eleven guards failed before the implementation (26 passed, exit 1). Final focused
identity/admission verification passes 41 tests. Two adjacent selections pass 159 with
one documented GUI-tier skip and 142 with one Windows symlink skip; compilation passes.
No viewer decoder/render/cache, DICOM grouping, thumbnail producer, download transport,
database schema or packaged mirror changed. Roll back this slice by reverting the
finalizer/admission methods and their call sites together; no feature flag is added
because keeping the invalid root lookup or orphan widget construction as a parallel path
would preserve the defect. U0 remains open until a restarted source run verifies blank-
primary Local open, cached and multi-study order/counts, four accepted tabs plus prompt
fifth-tab rejection, no widget/pipeline creation on rejection, no qasync re-entry and a
normal session exit.

## 2026-09-18: U0 post-catalog orphan maintenance (OPT-58 / OPT-60)

The fresh U0 source run remained responsive but failed thumbnail latency. Three Local
opens recorded five worker-owned orphan reconciliations: 6,953/3,822 ms, 3,142/297 ms
and 6,285 ms. In the 31-series single-study case, the authoritative producer-index
inventory itself completed in 899 ms and GUI card application was normally 18-25 ms
(52.67 ms maximum), but the first card arrived 6,318 ms after stream start because
orphan maintenance still preceded the catalog. Two grouped catalogs similarly spent
4,386 ms for 39 cards and 5,811 ms for 66 cards after admission. No main-thread stall,
ERROR, CRITICAL, Shiboken failure or access violation occurred; the startup-only
`0x8001010d` record was non-terminal. Whole-patient file warming overlapped these opens
(376-596 MB over 9.8-24.5 s) and remains a measured I/O-pressure candidate, not the
proven admission gate.

The correction changes ordering, not authority. Exact pixel inventory remains the
only catalog admission gate and already excludes missing/non-pixel series. Single-study
Local publishes its bounded ordered cards and persists UID-scoped counts before the
same worker runs destructive orphan self-heal. Grouped Local and Server publish their
complete metadata before the existing background worker reconciles in `finally`, so
failure paths retain maintenance without blocking successful publication. No new
thread, producer, cache, timer, state authority, Viewer/VTK/decode behavior, download
contract or database rule is introduced. The existing orphan function still owns all
partial-study, stale-sample, pending, whole-study-eviction and offline-root safeguards.
New aggregate `LOCAL_ORPHAN_RECONCILE` markers distinguish post-catalog maintenance.

Behavioral guards failed before with first-publish seeing prune already complete and
grouped publication seeing `prune -> push`. The corrected direct boundary passes 61;
adjacent Local/catalog/offline/sidebar/metadata/file-warm/index tests pass 151.
Compilation and diff checks pass. **U0 remains open** pending a restarted source run:
require first-card before the post-catalog reconcile marker, exact single/multi-study
identity/order/object/frame counts, no overlap/jump, no new GUI stall/error/native fault,
and a normal process exit. Do not start U1 from code results alone.

## 2026-09-17: OPT-58 / OPT-60 ordered Local inventory ownership

Fresh source evidence separated the remaining delay from Qt and rendering. Two
previously unopened Local patients required 2.717 s for 5 series / 280 files and
15.158 s for 11 series / 1,172 files. The latter spent 11.525 s in cold pixel
inventory while the independent file warmer simultaneously read the same 1,172
files (307.2 MB in 14.637 s); grouped card application itself took 434.14 ms and
the session recorded no GUI stall or error.

The 22:12 live follow-up proved the intermediate fact-primer insufficient: three
unverified catalogs still completed in 6.950-13.707 s because an independent primer
and the sequential consumer interleaved through the single-flight. The corrected
default therefore gives exact Local inventory one owner. Home and patient projections
both consume `resolve_series_pixel_inventories`: series remain strictly ordered, while
only files inside the current unverified series use one reusable bounded worker pool.
The result is yielded only after the complete exact series inventory, preserving
non-pixel exclusion, object/cine-frame separation, collision aliases, multi-study
order, revision checks and batch DB backfill. No provisional or stale card is admitted.

The patient-open warmer now skips known unverified Local series entirely, eliminating
both duplicate enumeration and competing reads. Producer-indexed Local series and all
Server/unknown fallback paths retain raw warming. `AIPACS_LOCAL_ORDERED_INVENTORY=0`
restores the prior fact-primer path; `AIPACS_LOCAL_PIXEL_FACT_WARM=0` remains its
narrow secondary rollback. Work stays off Qt. Viewer/VTK/decode, download, thumbnail
layout, storage identity and GUI cadence are unchanged.

New fail-before: 4 failed / 44 passed (missing ordered resolver and warm delegation).
Final direct boundary: 50 passed. The Home/patient/offline/owner boundary passes 129.
The wider UI/storage selection passes 1,295 with two skips and three quarantined
xfails; two unrelated pre-existing assertions remain red in login-identity source
spelling and status-sort source spelling. Compilation and diff checks pass. Fresh
source GUI/KPI is **OPEN**: compare first-card and full-catalog time for previously
unopened single- and multi-study patients, then reopen them to exercise producer-index
admission. Require exact card order/counts, no overlap/jump, no GUI stall/error/native
fault, `delegated_series>0`, and PHI-free `LOCAL_PIXEL_INVENTORY_BATCH` markers. Do not
claim latency closure from code tests alone.

## 2026-09-17: OPT-58 / OPT-60 Local open orphan-reconcile stall

The first post-index source run did not validate Local latency. A two-study Local
open needed 23.280 s to publish 33 series because its 2,264-file legacy catalog was
still unverified. That scan completed the intended migration: a read-only post-run
check found 1/1 and 32/32 series pixel summaries Verified. Card layout was not the
dominant wait (23.13 ms reservation; 985.81 ms grouped delivery; 19.22 ms maximum
card apply).

The same run exposed a separate **6.925 s GUI freeze**. Repeated sampled stacks pin
the UI coroutine in `prune_orphan_series_for_study -> _series_has_disk_files ->
os.listdir`. The self-heal remains required, but it now runs only in existing workers:
the patient inventory worker for single-study Local, and the existing patient-open
background worker for grouped Local and Server. Healthy series first validate one
known DB instance path; full directory enumeration remains the conservative fallback
for a missing/stale sample, preserving partial-study orphan detection and whole-study
eviction safety. No viewer, decode, geometry, download or card-layout behavior changed.

Fail-before: 2/2 focused guards failed (GUI ownership and healthy-folder enumeration).
After the fix: 67 directly affected tests pass; expanded Local/storage/multi-study
selection passes 337 with one explicit Windows symlink skip. Compilation passes.
Fresh source same-patient reopen/restart is OPEN: require per-study aggregate
`source=producer_index owner=home_local` totals summing to 33 series, no
`prune_orphan_series_for_study` GUI stack, exact 33-card
identity/counts, and no new error/native fault. The legacy cold scan is not claimed
eliminated before its one-time verified backfill.

## 2026-09-17: OPT-58 / OPT-60 producer-verified Local catalog facts

Deep review confirmed the previous worker/QImage correction but rejected further
per-file cache tuning as the primary architecture. Cold Local admission remained
O(total DICOM files): sampled 1,998-file single-study inventory took 17.974 s and
2,142-file grouped inventory took 37.305 s, while GUI card application stayed
bounded (29.72 ms median / 49.24 ms max in the sampled single-study stream).

The existing series index record now carries an independent producer-verified pixel summary:
pixel-bearing object count, display-frame count, schema and exact managed series-
directory revision. Import publishes it only after the same generation copied and
indexed every destination; Download Manager publishes it only after all headers and
pixel probes succeeded in its subprocess. Home and patient Local projections accept
the summary only for a complete pixel inventory under the managed two-level DICOM
tree with an unchanged directory revision. A completed legacy scan backfills the
summary in one DB transaction without claiming geometry-index completeness.
Restored/external/partial/changed rows keep the existing worker header scan. Object,
cine-frame and download-completeness truth
remain separate; exact Series UID, raw number, `folder_key` and display-key allocation
are unchanged. This extends the existing DB-first index; it is not a second catalog,
renderer, downloader or viewer cache.

Fail-before selection: 3 failed / 1 passed, exit 1 (missing schema/round-trip and
Local fast-path behavior). Final exact contract selection: 76 passed. Expanded
catalog/Local/storage/multi-study boundary: 319 passed / 1 explicit Windows symlink
skip, exit 0. Import/download adjacent selection: 104 passed, exit 0. Compilation
passes and 467 plugin mirror pairs match. A compare-and-persist revision guard also
rejects a directory changed between legacy scan and DB commit. Fresh source cold/warm/restart GUI and
installed acceptance remain OPEN; existing datasets backfill through the legacy
scan rather than being silently trusted. See the canonical UI-stall receipt,
thumbnail pipeline and regression catalog for rollback and acceptance scope.
Release parity code checks pass 13/13; the excluded live-stage check remains the
pre-existing stale five-template build-output blocker and was not rebuilt here.

## 2026-09-17: OPT-58 / OPT-60 Local patient-stream image preparation

The 10:49 normal-source run proved that Home image preparation was active but
isolated the remaining Local patient-sidebar GUI read: a 413.0 ms sampled stack
opened thumbnail bytes inside the 10 ms drain callback. The existing Local worker
now prepares an immutable QImage with the exact study/folder storage identity;
the bounded mailbox carries it to the GUI, which alone constructs QPixmap/cards.
Ordering, stable aliases, grouped takeover, object/frame counts, persistence,
download state, placeholder behavior and cancellation are unchanged. No Viewer,
download, DB, cache-policy, protocol or packaging path changed.

Fail-before worker-preparation guard: exit 1; final Local stream file: **37 passed**.
Expanded Local/Home/sidebar/source selection: **212 passed, 1 explicit Windows
symlink-privilege skip**, exit 0. Broader 29-file UI-services boundary: **456
passed with the same 1 skip**, exit 0; 467 mirrors match. Fresh normal-source
Local GUI and matched KPI remain OPEN; the expected gate is removal of the Local
`read_bytes` GUI stack, not a synthetic wall-time threshold or a blanket crash claim. See the
[canonical implementation, risks and rollback](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-local-patient-stream-image-preparation-opt-58--opt-60).

## 2026-09-17: OPT-35 / OPT-60 completed-load tab handoff

The 8/104 incident is reproduced across two owned boundaries: hiding during decode
discarded successful delivery and leaked load ownership; Advanced metadata could grow
without matching decoded pixels. Shared delivery now preserves the normalized pair,
defers only rendering and resumes the original cancellation/token-bound completion in
manual and automatic boost modes. Advanced cache integrity was corrected by its owner,
not folded into a shared decoder. No server retry/cache flush workaround or geometry edit.
Twenty-five new shared guards pass; initial corrected baseline was ten failures / one
pass against clean HEAD methods. Source GUI remains pending on a fresh process.
The final combined focused selection has 214 passes / six existing quarantined xfails;
467 mirrors match. A separate release gate still fails on stale staged configuration
(41 other checks pass, one deselected); do not call the release lane green.
See [canonical evidence, regression matrix and rollback](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-completed-load-tab-handoff-opt-35--opt-60)
and the paired Advanced-owner receipt linked there. Thumbnail cold-start latency,
MPR setup latency, native stress and installed acceptance remain separate open gates.

## 2026-09-17: OPT-58 / OPT-60 Local inventory persistence

Latest source receipt (September 16, 23:40:15 main PID 739276): two Local
two-study cases take 6.570 / 27.004 seconds to publish their complete metadata;
2398 / 2412 files are reprobed with zero memory hits. Bounded card application
maxima are 35.38 / 20.33 ms. PNG enumeration and stripe-lock wait do not explain
the delay. This is partial evidence for the prior builder, not whole-GUI acceptance.

Authorized next slice adds version-checked, positive-only persisted facts to
the existing `dicom_displayability` worker service. Managed source files remain
unchanged; artifacts live in bounded central cache storage, **not** thumbnail
folders (an intermediate-placement regression guard caught a false presence hint).
No DB-count shortcut, decoder/viewer/UI/download change or new config/module.
First cold scan still required; full grouped catalog-first delivery is not closed.
Final direct focused pytest: **425 passed, 1 deselected**, six existing SWIG warnings,
exit 0 (44.32 s); **467 mirror pairs match**. No full-suite or installed claim.
Code/limits/rollback and exact source metrics:
[canonical receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-local-inventory-persistence-opt-58--opt-60).
Fresh-source cold/reopen/restart GUI/KPI gate remains OPEN: responsive old PID
739276 cannot accept a later edit. Existing native-crash and installed gates remain.

## 2026-09-16: OPT-58 / OPT-60 bounded cached-sidebar application

Measured 141-card cached and 142-card grouped synchronous bursts are now routed
through the existing thumbnail batch/source services: detached worker I/O/QImage,
GUI-only QPixmap/cards, complete fixed-size/header reservation, one card per
yield, exact startup inventory count and generation/identity rejection. Preserve
download-state replay and object-versus-frame counts. No Viewer branch change.
Two real-Qt/qasync guards failed before implementation; a third then reproduced
server-entry/cached-build overlap. Server entries now use the same scheduler after
their existing count merge/persistence. Final direct focused suite: **304 passed,
1 deselected**, exit 0; new guard file **21 cases**. Six existing SWIG warnings.
467 plugin mirror pairs match (no mirrored
runtime source was edited). New code is in existing core modules; no build/profile
entry, dependency or new feature flag is required.

Controlled 141-card offscreen comparison: legacy entry 1002.54 ms, bounded entry
0.88 ms, reservation 25.21 ms, max card apply 11.12 ms, total bounded elapsed
1905.42 ms. Do not present this as faster total loading or live improvement.
Old source PID 1197880 answers MCP but predates the patch; fresh source GUI and
same-workload KPI acceptance remain OPEN. Local admission/stream and explicit
compatibility paths remain follow-ups; this does not close OPT-58/60 or native crashes.
Rollback: existing `AIPACS_SIDEBAR_BUILD_CHUNKED=0` on process start restores the
prior synchronous paths. Details, affected files/contracts and live matrix:
[implementation receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-bounded-cached-sidebar-build-opt-58--opt-60).

## 2026-09-16 22:47 source receipt: OPT-04 positive; OPT-58/60 latency still open

Fresh PID 1197880 executes the retired-hard-suspension correction. The exact
previously blocked study now reaches Completed 2262/2262 (32 series); its secondary
task completes 2/2. Five tasks complete, 150 exact file-count checks pass. Read-only
control remains responsive. This is positive user-workflow/log evidence, not the
full visual/identity/pause/close/installed matrix or clinical completeness proof.

Shared thumbnail bottlenecks persist: 3.908-second synchronous 141-card load and
2.566-second 142-card grouped rebuild; Local grouped metadata remains late. Whole
window has 111 threshold-selected F8 stalls, p95 1017 ms; no matched workload
speedup claim. Existing OPT-58/60 next slice must preserve stable geometry while
removing GUI store reads and bounding card application through the same owner.
MPR/Advanced findings and one non-terminal COM event go to their respective owner
records. See [the live receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-2247-fresh-source-download-and-kpi-receipt).
No runtime change was made during this review.

## 2026-09-16: OPT-04 / OPT-35 remote-download liveness diagnosis

**Subsequent authorized correction:** shared download native suspension hooks are
now compatibility no-ops in current/legacy routes; retain shutdown bookkeeping and
the existing child OS-priority request. No rendering, decoding, scroll algorithm,
queue/progress or transport edits. Sixteen new synthetic guards: 14 failures before,
all pass afterward. Focused download/system: **142 pass**; package guards **9 pass**;
**467 mirrors match**. Expanded Viewer selection: **288 pass / 1 pre-existing
spinner-test-double failure**, reproduced with original download hooks in an
isolated baseline process. No full-suite green claim. Details and rollback:
[implementation receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-opt-04-download-liveness-independent-of-viewport-settling).
Fresh-source actual download/scroll-overlap/close/priority GUI and KPI gates remain
open; removal of hard suspension needs a matched contention check. The earlier
diagnostic receipt below is historical, not the current implementation status.

Fresh source session 21:27:14, main PID 1215900: remote thumbnails and two series
drop intents succeed, but the adopted prewarmed download child remains Windows
`Suspended` before job receipt. Live task stays `Downloading` with zero progress;
secondary study is `Pending`. This is a local worker-execution blocker, not a
demonstrated server-response failure or sidebar/header regression. Exact missed
suspension release is not proven. No runtime change or forced recovery performed.

Shared worker liveness/shutdown-vs-throttle ownership remains OPT-04; Advanced
scroll/series-switch release belongs to its Viewer owner under OPT-35. Full
evidence and the bounded joint verification request are in
[Viewer handoff 02](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#unify-handoff-2026-09-16-02-suspended-download-process-after-advanced-interaction),
with a backlink in the existing UI-stall owner report. This diagnostic handoff
does not close download, live performance or prior crash acceptance.

## 2026-09-16: OPT-58 / OPT-60 live follow-up and grouped-header reservation

20:51:54 source run: user confirms materially smoother card loading/replacement;
remaining first-Local grouped delay and header jump reviewed. First 39-card Local
metadata arrives at +8.086 s, grouped render at +8.897 s; PNG enumeration is only
7.99 ms. Warm-up alone is not established. A late-discovered study changes 11 primary
cards into 12 grouped cards and remains a separate topology-handoff gate.

Corrected hidden-header admission and width-dependent height reservation in the shared
sidebar after fail-before real-Qt guards. **432 focused passes / 467 matching mirrors**;
the running process predates this latest correction, so fresh GUI is pending. No
Viewer/decode/filter/download change. Whole-session selected F8 max is 4.813 s;
patient-work max 1.824 s, so full KPI/crash closure is not accepted. 23/23 file-count
checks pass but are not clinical completeness. Next performance work targets measured
Local grouped metadata preparation, not speculative extra warm-up. See
[evidence, tests, limits and rollback](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-2051-source-review-and-study-header-geometry-correction).

## 2026-09-16: shared Unify versus Viewer workstream ownership

User reaffirmed one common coordination trunk feeding independent Fast and Advanced
viewer backends; VTK modules retain independent execution domains. Unify owns common
identity, catalog/thumbnail presentation, download/file/state coordination and cache
invalidation contracts, not backend decode/filter/render or decoded-cache internals.
Use the [canonical boundary and bidirectional handoff](plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md#02-workstream-ownership-and-two-way-handoff-user-decision-2026-09-16).
Advanced/VTK findings go to the [VTK owner report](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#inbound-handoff-from-unify-2026-09-16);
shared findings return to the [Unify owner report](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-workstream-ownership-and-outgoing-viewer-handoff).
The earlier Advanced mirror drift was handed off, not repaired by Unify. The owner's
later receipt plus a fresh read-only check now show 467 matching pairs, exit 0.
This is documentation-only scope coordination, with no changed runtime/defaults or
new GUI acceptance. Existing OPT statuses and outstanding validation gates remain.

## 2026-09-16: OPT-23 / OPT-35 preview-count clarity and audit accuracy

Advanced now displays known total and ready count during preview (`1 / 80 | 8 ready`)
without widening VTK/slider bounds. Geometry changes are restricted to the contradictory
camera-audit normal calculation and diagnostic labeling; actual render geometry and all
filters remain unchanged. Filter-chain maxima in sampled logs reach 10.3 s, so no latency
improvement is claimed from this UI change. Sixteen new cases; expanded 257 passed /
5 existing xfailed, exit 0; 467 mirrors match. Fresh source GUI and clinical geometry
acceptance remain open. See the
[receipt](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#preview-count-presentation-and-diagnostic-correction-opt-23--opt-35-2026-09-16).

## 2026-09-16: OPT-58 / OPT-60 sidebar presentation correction

The 17:58:46 source session reproduces redundant 141-card single-study rendering
before a 142-card grouped rebuild. Real-Qt guards also reproduce pre-layout painting,
header-inclusive totals, terminal reordering and native-parent detachment. Corrected
the shared card insertion boundary and Local/queued/grouped ownership in `_pw_panels.py`
and `_pw_thumbnails.py`; retain explicit primary fallback on grouped failure. Mixed
Local catalogs now publish an ordered prefix, not an out-of-order subset. No viewer,
decode, download protocol or feature-default change. **428 focused tests pass, exit 0.**
Initial 466-pair parity passed; final recheck found one unrelated Advanced Viewer
source/payload drift (exit 1), left to its owner. Guards, tradeoffs and narrow rollback are recorded in the
[receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-sidebar-presentation-boundary-correction-opt-58--opt-60).

Status: code-verified; fresh source GUI requested, not accepted. The running process
predates the patch. The transient central-window cause is unconfirmed. Grouped GUI
PNG/readiness I/O and synchronous card construction remain, as does Local inventory
contention. Keep visual stability and exact identity/counts as gates before optimizing
those costs; no crash/KPI/release closure from offscreen passes.

## 2026-09-16: OPT-23 / OPT-35 user acceptance and remaining VTK gates

User confirms Advanced drag/drop background exposure is fixed and previously confirmed
US color. In the 17:58:46 source session, complete binds match 30/30/88/80 frames and
live readback reports 80 non-preview slices. Seven complete hot-cache reads match the
same-series bind order/count; the separate shared-volume cache flags remain off.
No application/viewer/download ERROR/CRITICAL in the inspected window. Remaining gates
include the internally inconsistent orientation-audit handedness test, mixed-orientation
and preview admission, and separate Eagle Eye/MPR/Advanced Analysis image-path passes.
Long Qt/thumbnail gaps and recurring unclassified COM evidence were handed to owner
documents. This is bounded acceptance, not closure of all VTK work. See the
[consolidated receipt](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#consolidated-acceptance-review-175846-source-session-2026-09-16).

## 2026-09-16: OPT-58 / OPT-60 fresh-source evidence and stable-sidebar gate

The 17:14:46 source launch supersedes the bootstrap blocker for the large-number
follow-up. Two Local streams terminate with 31/20 cards and no prior-key rejection;
this is partial log evidence, not exact-series/visual acceptance. Remaining evidence:
18.55-second Local inter-card wait aligned with pixel inventory, and a distinct
4.90-second grouped-sidebar GUI freeze during 39-card construction/cache reads.
No new runtime change is made in this review.

User-required acceptance now explicitly includes no overlap, visible reorder/flicker,
or stale title/count oscillation; preserve history/study order, progress/selection,
scroll and callback retirement. Add behavioral guards before the next bounded grouped
cutover; timer-only scheduling is insufficient while callbacks retain disk I/O.
Local completion-time repositioning and header-inclusive interim totals also need
coverage before claiming stable incremental presentation. See the
[evidence and ordered gate](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-fresh-session-review-and-sidebar-stability-gate)
and [presentation contract](pipelines/thumbnail-pipeline.md#presentation-acceptance-contract-user-decision-2026-09-16).
Crash closure, matched cold/warm KPI acceptance and packaged verification remain open.

## 2026-09-16: OPT-23 Advanced drag/drop loading continuity

Reproduced transparent native loading cover, missing repaint on branded-cover reuse,
and stale completion dismissing the next load. Corrected with a native-only opaque
backdrop, synchronous repaint and generation-scoped completion. No geometry or decode
changes. Eight new cases including 3/30-image complete-stack checks; expanded **106
passed, 15 opt-in GUI skipped, 1 existing xfailed**, exit 0; **466** mirrors match.
User confirmed US RGB appearance. Fresh source native drag/drop/scroll acceptance
remains open; control ping was unavailable. See the
[receipt and rollback](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#advanced-dragdrop-loading-cover-and-full-stack-checks-opt-23-2026-09-16).

## 2026-09-16: OPT-58 / OPT-60 large-number follow-up

The 16:51 source run exposed a remaining identity failure: initial allocation allowed
raw numbers >=1,000,000, while incremental validation correctly rejected those as local
handles. The shared allocator now aliases these numbers without changing original DICOM
number, UID or disk location. Mixed Local catalogs can publish their stable ordinary
subset early; alias-requiring members still wait for full inventory. Owner-local startup
deduplication prevents a second load after an early metadata-started load completes.

Six fail-before cases plus a separate mixed-catalog latency failure; **344 final passes,
exit 0**, including 76 cases in the three directly affected guard files. **466 mirrors
match.** Code PASS, fresh-source live BLOCKED: ping/83-action discovery work, but the
16:51 process predates this correction. Do not claim total I/O reduction, crash closure,
packaged acceptance or live speedup. Scope, rollback, tests and next GUI/KPI matrix:
[follow-up receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-large-number-identity-correction-and-startup-deduplication).

## 2026-09-16: OPT-58 / OPT-60 Local incremental card delivery

The confirmed Local whole-list barrier is corrected at the single-study startup and
delivery boundary, not by skipping pixel checks. Unique canonical series deliver one
verified card at a time through a bounded worker/GUI queue. Collision/legacy catalogs
retain full-inventory key allocation; grouped Server/multi-study ownership, decoding,
download semantics and the dormant Fast preparation primitive are unchanged.

Code gate: four initial contract failures plus a separately reproduced Local startup
branch failure before their corrections. Final focused selection: 212 passed, exit 0
(26 stream guards plus 21 startup guards and adjacent identity/lifecycle/cine suites);
466 mirror pairs match. Live remains BLOCKED pending human fresh source launch/sign-in
(documented ping failed; no source main process at preflight). No measured production
speedup or full crash/Unify closure is claimed. Details, affected files, test guards,
rollback and the same-workload KPI matrix are in the
[implementation receipt](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-local-incremental-card-delivery-opt-58--opt-60).

## 2026-09-16: OPT-35 Advanced nonspatial US compatibility

The missing-US viewport defect is code-corrected with a separate display-only ordering
plan, retaining strict spatial CT/MR geometry. Related reproduced stale-affine and RGB
mapper-reuse defects are corrected; nonspatial US cannot enter the shared MPR route.
17 synthetic guards; 245 expanded passes, 5 existing xfails, exit 0; 466 mirror pairs
match. No measured speedup is claimed. Live acceptance remains pending: the reachable
15:42:20 source process predates these edits. Scope, rollback and next workflow are in
the [US correction receipt](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#us-correction-opt-35-code-verified-live-pending).

## 2026-09-16: OPT-23 Advanced VTK first-render measurement prerequisite

The fresh source sample showed a 6102.8 ms GUI gap through Advanced construction and
initial rendering. Phase timing is now added only to the completed `ImageViewer2D`
constructor, one identity-free summary per build, with unchanged render/fit ordering
and executable viewer behavior. Four guards, 257 expanded passes, 6 existing xfails,
exit 0; 466 mirror pairs match. This is **instrumentation, not a latency fix**; a fresh
source-GUI test is pending. See the [next-test receipt](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md).
Generic KPI/Home/native findings remain with their owning documents per the user's scope.

## 2026-09-16: VTK domain review under OPT-35 / OPT-48 / OPT-49 / OPT-56

**Authorized cache prerequisite follow-up:** generation-scoped build invalidation and
post-build VTK byte accounting are implemented. Four behavioral guards failed before;
eight new cases pass afterward. Expanded selection: 398 passed, 5 xfailed, 1 xpassed,
exit 0; 465 mirrors match. No flags or geometry changed. Existing source-app ping/actions
work, but its 11:52:59 launch predates the patch: live acceptance remains BLOCKED pending
fresh human source bootstrap. See the implementation receipt in the report below.

The [VTK geometry and performance review](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md)
covers Advanced Viewer, Eagle Eye, Standard/Zeta MPR and external Advanced Analysis.
It records two synthetic cache reproductions (in-flight invalidation republishing stale
results and zero byte accounting through the volume wrapper), existing optimizations,
geometry constraints and ordered implementation slices. Cache primitives are prerequisites
before activation; the service remains default-off. Preserve the real MPR X flip and
explicit oblique planes; older OPT-48 proposals must not override the later geometry contract.
Initial review verification: 418 passed, 6 existing xfailed, exit 0. The initial review
had no runtime change; the follow-up above records the subsequent implementation.
No live GUI/performance acceptance is claimed.

## 2026-09-16: OPT-60 / OPT-35 catalog-first prerequisite

**Fast preparation prerequisite implemented (OPT-58 / OPT-60):** worker-only
data preparation, single-consumer identity/revision/config-checked adoption and
optional prepared bridge initialization now have 37 synthetic guards. The follow-up
prepares immutable image-tag snapshots through the same reader, validates incoming
Study/Series/source at the bridge, and scopes their use to one synchronous initial
presentation. Real annotations pass without GUI header/stat work in that scope;
later mtime-aware demographic refresh remains intact. No runtime caller activates
this path yet: bounded request scheduling and completed-switch semantics are still
gates, not lag closure. Final focused runs: 335 passed, one existing xfailed and
three missing-fixture skips, exit 0; 466 mirrors match. Source live acceptance of
the new path is pending activation, not PASS. An explicitly requested restart is
only baseline/bootstrap verification until that integration exists.
See the [implementation receipt and next gates](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-fast-initial-display-preparation-primitive-opt-58--opt-60).

**Fast lag pre-change review (OPT-58 / OPT-60):** confirmed synchronous switch
consumers depend on an already-created bridge/count; a fire-and-forget conversion
would break slider, progressive and loading semantics. Selected prepare/validate/
GUI-commit direction, with worker-owned data, generation/revision/lifetime checks,
bounded memory/work and preserved cine/WL behavior. Native drag is user-accepted;
do not conflate it with startup decode latency. **186 baseline tests passed,
1 existing quarantined xfailed**, both direct pytest runs exited 0. No runtime
fix or new live/KPI acceptance. Full dependency matrix, rejected approaches and
implementation gates: [Fast impact review](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-fast-initial-display-change-impact-review-opt-58--opt-60).

**11:52:59 fresh-source sample:** existing MCP Local open/switch/scroll passed
for distinct-UID same-number still/cine (25 images, two cine objects / 424 frames,
independently header-verified) and two linked studies / five series. Exact Study/
Series UIDs and handles remained stable; cine last-frame captures were nonblank.
Native mouse drag, close/reopen, Server, late-arrival and heavy cold gates remain
open. Performance is NOT accepted: 35 session stalls, max 4673.3 ms, with repeated
Fast GUI `dcmread` stacks during cine startup; retain as a separate Fast-domain
investigation. No scoped ERROR/CRITICAL or main access-violation mention; one
non-terminal COM mention. See the fresh-source receipt in the report below.

Architecture review selected cached, identity-keyed previews plus background
verification, not a new viewer/downloader or blind DB/PNG rendering. Do not feed
partial lists to the old sink: five fail-before cases proved alias theft, missing
series and wrong-card metadata. The existing allocator/sink now reserves admitted
study-local handles across subsets and late collisions, retains exact prior UID
paths, and prevents foreign-study metadata fills. Fifteen final guards; 181 focused
plus 107 adjacent passes, exit 0; 465 mirrors match. Count-authority policy, decode,
Download Manager and rendering cadence are unchanged. This is a correctness
prerequisite, **not a measured lag fix or incremental-display activation**.
The initial 10:32 source process predated this patch; the later sampled receipt
above provides partial GUI acceptance. Next: GUI-owned generation-scoped card upsert, then trusted
catalog-first delivery and validated-summary reuse. Evidence, research, boundaries
and narrow rollback: [catalog-first review](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-catalog-first-review-and-stable-handle-prerequisite-opt-60--opt-35).

## 2026-09-16: OPT-60 / OPT-58 Local metadata gate

**Second slice: shared pixel facts, GUI pending.** The fresh source test still
took 31.8 seconds to hand off Local metadata despite finding PNGs around 0.7 s;
the first routing correction was insufficient. The existing Local inventory now
coalesces positive per-file probes with version-checked, bounded 30-second reuse
and requests only needed header values. No projection/classification bypass.
Six fail-before cases; 24 final new guards, 181 focused passes / three unavailable
clinical-fixture skips, exit 0; 465 mirrors match, compilation/diff checks pass.
Warm off-app repeat passes fell from ~1.9-2.0 s
to ~0.16 s with all per-series counts unchanged; first uncached passes ~1.85 s.
This is not measured GUI improvement. New aggregate instrumentation will separate
probe work/wait from delivery on the next source run. Scope, bounded-cache limits,
rollback and live gate: [inventory follow-up](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-local-pixel-inventory-reuse-follow-up-opt-60--opt-58).

Removed the redundant manifest scan before selecting the existing Local DB metadata
route in `_hp_series.py`; only the two `or` operands changed order. Server growth,
download-completeness authority, offline routing and UID/count contracts are unchanged.
The pre-fix source session recorded a 7,022 ms GUI gap with this manifest traversal
on its stack; two larger Local metadata handoffs took about 25/36 seconds, not all
attributable to this one gate. Five fail-before cases; 18 new guards and **77 focused
passes**, exit 0; **465 mirror pairs match**. Fresh-source GUI and matched-workload
timings remain OPEN. No measured post-fix latency or crash-prevention claim.
Evidence, adjacent remaining scans, command and narrow rollback:
[Local follow-up](reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-local-metadata-route-follow-up-opt-60--opt-58).

## 2026-09-15: crash closure -> Unify acceptance -> KPI acceptance

**Fourth evidence slice (OPT-60 / OPT-21):** fixed reproduced nested/concurrent
shutdown admission in the existing lifecycle manager. Added callback-versus-owner
observations and a nonblocking consultation probe including retired owners; no drain
barrier, Qt/VTK/GC reorder or download change. Corrected the finalization claim before
log shutdown. Twelve fail-before cases; 105 focused passes, four build deselections,
exit 0; 465 mirror pairs match. Fresh-source application exit remains pending,
including the previous native-header hardening. Original crash prevention remains
OPEN. Evidence, scope, rollback and live gate are in the fourth
[closure-audit follow-up](reports/CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md).

**Third evidence slice (OPT-60 / OPT-21):** process-exclusive native capture and
coordinated reader cutover implemented. New files include PID plus a unique session
token; legacy evidence remains readable/unattributed. External probes, filter,
dashboard and native GUI guards discover both; the retired raw GUI counter explicitly
redirects instead of reading files or returning false zero. Six initial failures plus
three subsequent guards; 19 new isolation cases, **120 passes / 4 opt-in build deselections**,
exit 0, and 465 mirror pairs match. User-authorized 22:05:08 source launch: Home/menu
smoke, 77-action bridge and mixed-format health probes passed. Final header-publication
ordering was hardened after this launch and still needs the next fresh-source gate.
One startup COM record
was non-terminal; no exit/crash-prevention claim. Actual shutdown owner completion is
next, not a reason to alter Qt/VTK teardown speculatively. Full scope/rollback:
[third closure-audit follow-up](reports/CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md).

**Second evidence slice (OPT-60 / OPT-21):** fixed the external MCP scenario's
no-op `assert_health` and removed its native-log reads from the GUI command bus.
Use a bounded cumulative byte window, verify capture-start/current process identity,
and fail closed on unavailable or rewritten evidence. A retrospective health
snapshot is explicitly inconclusive, not a guessed last-N-minutes crash count.
7 initial failures; 32 new guards, 93 focused passes, exit 0. A read-only live
two-assertion smoke plus final check passed over approximately 0.45 seconds; no
patient GUI or runtime crash closure is claimed. The legacy raw adapter, coordinated
sink migration, shutdown owner completion and ignored download-wait test result
remain open. See the second follow-up in the
[closure audit](reports/CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md).

**First corrective evidence slice (OPT-60 / OPT-21):** fixed the offline native
filter's reversed header/stack association and input/output alias overwrite hazard.
12 fail-before cases; 20 final new guards and 42 adjacent passes, exit 0. Existing
native text round-trips exactly in memory; no clinical log export or runtime change.
Per-process capture must migrate its readers together, then verify owner completion;
do not confuse this diagnostic repair with crash prevention. See the first follow-up
in the [closure audit](reports/CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md).

**19:12-19:20 source follow-up:** 149 focused code passes; three patient tabs and
downloads exercised. Independently validated 251 MR DICOM files (65/114/72) across
21 series, unique SOPs and correct study/selected-series identities; three separate
document tasks completed in the queue. Native thumbnail input, wheel, surviving-tab
close/reopen and second-viewport/last-slice output passed. No fresh recorded crash;
application exit was not tested. Keep Preview identity/status convergence, stale DM
summary/details, and a 458 ms GUI metadata read OPEN. This is sampled acceptance,
not completion of Unify or the shutdown gate. The [closure audit](reports/CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md)
records exact counts, tool fidelity, KPI limitations and remaining scenarios.

User-confirmed patient-tab native drag works; the earlier unfinished automation is
not an application bug. Rechecked **124 focused crash/ownership guards**, all pass;
465 payload pairs match. No new Windows crash event was found after the 16:51 source
launch, but the process was absent after the 17:40 log tail without a shutdown
completion receipt. Exit intent is unconfirmed; native exit faults are not closed.
The shared native log also requires process attribution, not last-header guessing.

Continue existing OPT-60/OPT-35/OPT-04 in order: attributable shutdown/owner completion;
UID/revision and durable download-completion convergence with the remaining live
matrix; then matched KPI optimization. Latest 42 threshold-selected stalls include
a 416.6 ms GUI DICOM cache miss; no broad performance acceptance or Unify completion
is claimed. See [the evidence and ordered acceptance gates](reports/CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md).

## 2026-09-15: OPT-04 file-count gate and retry destination ownership

**Fresh-source sampled live update:** user-requested 16:51:38 launch and human
sign-in; ping/action discovery, native Home-card double-click and wheel passed.
Five MR series / 117 files matched independent disk counts and both terminal
Overall Progress displays; count checks 0.97-2.55 ms including a separate document.
Second viewport rendered the exact series through MCP. Native drag remained
unfinished and was cancelled: not passed. Explicit pause/retry, in-flight progress,
collision recovery and durable SOP-manifest proof stay open. Main process survived
one startup non-terminal COM event; no crash closure. New 416.6 ms GUI DICOM-read
trace belongs to the separate viewer cache-miss workstream. Full receipt below.

Known-count socket series no longer report success below the existing resume-file
count threshold; duplicate filenames no longer inflate progress. One final scan
runs off the event loop. Consumer review also reproduced same-number series retry
entering a sibling folder: reuse the first UID-scoped destination instead.
12 initial socket failures and 2 coordinator failures before their corrections;
23 new guards, **217 expanded passes including builder guards, exit 0**, 465 mirrors
match. No UI redesign, encoding, scheduling or test-driven live DB mutation in the
code phase. Source GUI is now partial as above; durable SOP/manifest completion remains OPEN, as do
historical encoding/payload debt and GUI DICOM-read latency. See
[scope, limits, verification and rollback](reports/DOWNLOAD_FILE_COUNT_GATE_2026-09-15.md).

## 2026-09-15: OPT-04 bounded socket-response reliability slice

Reproduced the ten-broadcast false failure, fragmented response-prefix parsing,
and request/connect self-deadlock. Correct only the existing DM client and payload:
exact prefix accumulation, elapsed broadcast wait budget with restored body timeout,
invalid-stream retirement and an owner-reentrant serialization lock. UI/progress,
priority, batch indexing, encoding, files and worker scheduling remain unchanged.
This correctness slice is not download optimization or the lifecycle cutover.

31 fail-before cases; 38 final wire cases including real local socket exchange.
Expanded boundary: **189 passed**, builder: **5 passed**, exit 0; 465 mirrors match.
Known baseline remains red: removed payload-key helper prevents collection; four
tolerant-decode guards and an old count-limit guard fail before this slice. Git
attributes the removals to July 25, not the current Unify changes. No test debt is
hidden. Fresh source GUI, durable disk/manifest completion and final IPC/convergence
remain open. See [scope, provenance, tests, live gate and rollback](reports/DOWNLOAD_SOCKET_RESPONSE_REVIEW_2026-09-15.md).

## 2026-09-15: OPT-22 user-initiated browser opening feedback

September 26 UI follow-up: replace the top-edge, full-width notice with a compact
centered child card. Three geometry guards fail before/pass after; 92 browser,
adjacent and builder checks pass; 472 mirrors match. Synthetic visual preview
inspected. No startup scheduling/input-return contract change. Fresh source GUI
and artifact acceptance remain open; see `reports/WEBENGINE_OPEN_WAIT_STATUS_2026-09-15.md`
for evidence, native stacking caveat and scoped rollback.

The latest first browser open produced a 35,375.9 ms GUI stall and a temporally
correlated Windows AppHangTransient event; the process recovered. The bounded
correction adds a pre-import header status strip, indeterminate bar and temporary
application-local input gate while preserving synchronous Widget-or-None callers.
No nested event pumping, worker-side Qt construction or warmup re-enablement.
This is wait feedback/reentry protection, **not removal of the native GUI block**.

Four initial guard failures; 12 final real-Qt guards; 160 focused passes plus one
mirror-parity pass, all exit 0. New helper added to the existing browser payload;
465 mirrors match. Fresh-source native GUI acceptance remains pending because the
running app predates this change. See [implementation, exact evidence, live gate
and scoped rollback](reports/WEBENGINE_OPEN_WAIT_STATUS_2026-09-15.md).

## 2026-09-15: OPT-60 consultation producer retirement

Fixed a reproduced stop-contract gap: delayed startup survived stop, late results
could still persist/notify, and completed or identity-replaced QThread owners were
retained. Own/cancel both timers, invalidate scan generations, cooperatively stop
between network stages, and release workers only after finished on the owner thread.
The existing MainWindow lifecycle registry now requests Poller stop before DB cleanup;
aboutToQuit is a fallback and autostart refuses new work during application close.

Code: **367 passed, 3 warnings, exit 0**, including 15 new real-Qt lifecycle guards.
Nine initial failures, three integration failures and one later batch-reentrancy
failure were reproduced before their respective corrections. Two payloads synced;
464 mirror pairs match. Source GUI remains blocked on the documented test-server
connection. Native exit faults, complete worker drain, GC and global KPI acceptance
remain open. No viewer/decode/download behavior change. Existing lifecycle-manager
timeout wording corrected: it is post-return reporting, not an enforced deadline.
See [scope, remaining architecture work, verification and rollback](reports/QT_POLLER_LIFECYCLE_2026-09-15.md).

Next structural step: instrument/extend the existing lifecycle manager with explicit
stop-request/completion phases and an event-driven drain gate; first prove it with
blocked workers and close/reentry tests. Do not change hard exit or global GC in the
same slice. Preserve Fast, Advanced and VTK ownership domains and qasync's distinct
executor shutdown semantics.

## 2026-09-15: OPT-60 signature import race; exit faults remain separate

Two synthetic guards reproduced the installed PySide6 6.10.2 `Reloader.update`
KeyError seen at 12:08:10. A version/binding-gated core snapshot adapter now preserves
the existing mapper owner and parser entry point without changing credential
selection or hiding exceptions. Native access violations at 10:57/11:04 followed
normal application shutdown; they are not proven fixed by this adapter.
Preparation traces now separate queue, scan and GUI delivery; no scheduling or
download behavior change. See the [evidence, scope and rollback receipt](reports/QT_SIGNATURE_IMPORT_RACE_2026-09-15.md).

Code: 72 focused passes, exit 0; 463 mirror pairs match. Expanded builder selection:
85 passes / one staged-config parity failure (two unchanged staged templates).
Fresh GUI is pending: existing 12:25 source predates this patch, and documented
MCP client ping is unavailable. Do not advance native-crash/performance closure.

## 2026-09-14: OPT-60 startup thumbnail enumeration preparation

The observed 4.1-second `pipeline_manager -> show_exist_thumbnails -> iterdir` seam now prepares
its listing with the existing asyncio/qasync executor, not on GUI. The exact immutable tuple is
passed to the original startup count/render decision: pending preparation is not an empty cache
and never initiates a fabricated cache-miss download/import. Layout is created once on GUI before
the await, so an arriving first-series signal has a viewport; delivery never reconstructs it.
Grouped Server startup keeps its original early-render skip and introduces no extra primary scan.
Local/Import still uses its existing authoritative identity/frame-count projection, not PNG stems.

One tracked task per owner coalesces duplicate starts. Study/path, terminal-close and native-owner
checks reject obsolete preparation before layout and after await. Exit cancels preparation before
viewer cleanup. The worker only owns immutable inputs and directory data; cancellation does not
forcibly stop an in-flight filesystem read. Existing log trace records exclusive `scan_ms` and
`prepare_wait_ms` (executor/scheduling plus read) separately. No dependencies/modules/flags added.

Five startup guards failed before implementation; an additional adversarial test caught a viewport
not ready during the await and led to the prepare-once layout correction. The final 18 new guards
include real offscreen Qt/qasync heartbeat during a 150 ms synthetic scan, native owner deletion,
close/cancel/identity invalidation, exact hit/miss routing, coalescing and teardown ordering.
See the [audit and implementation receipt](reports/UNIFY_PATH_COST_AND_STALL_AUDIT_2026-09-14.md).

An additional shutdown guard proved that cancellation on an already-closed event loop must not
abort viewer cleanup; that RuntimeError is logged and terminal cleanup continues. The expanded
selection includes the prior import/layout and overlay-reentrancy guards. The three changed
mixins are core-only (no plugin mirrors); read-only parity verification: 462 pairs match.

**Final code receipt:** 170 passed, 6 existing SWIG deprecation warnings, 21.09 s, exit 0,
direct pytest with `-p no:debugging --reruns 0`. Includes all 18 new preparation cases and the
affected Local/collision/multistudy/progress/lifecycle/import/overlay selections. Expanded
verification first exposed a pre-existing progress fake missing `_disposed`; only that fake
was initialized to the existing live-manager contract. No production progress change. Source
syntax and scoped diff checks pass. This is not the full repository fast lane or a live pass.

**Not whole-pipeline closure:** grouped availability `stat`, pixel loading/decoding, progressive
refresh/Education/direct no-loop compatibility scans, row-status DB and GUI batch/deletion costs
remain staged. No source KPI improvement, native-crash closure or installed acceptance is claimed.
**Fresh sampled GUI receipt (recorded September 15):** human source launch September 14 23:16:05,
PID 1123404, includes the final edits. Native Home double-click/visible pixels/wheel/normal close
passed for a grouped eight-image series and Local non-first 25-image series; Local reopen preserved
the count and selected series. MCP client was unavailable this launch, so exact UID inspection
and the extended acceptance matrix remain open. Local scans: 3.90/2.26 ms; preparation waits:
358.88/319.21 ms. The gap includes scheduling/delivery and is not yet exclusively attributed.
Fixed window through 23:25:50: 64 F8 stalls, median 163.2 ms, p95 581.8 ms, max 1799.1 ms;
remaining stacks include startup, backend filesystem/config reads and deferred close GC.
No sampled GUI enumeration stack or new app ERROR through 23:25:47; no native access violation.
This is a sampled correctness pass, not a matched speedup or no-lag claim. See the linked audit
for evidence, native COM qualification and remaining cold/cine/close/Advanced/download gates.
Do not reuse the older launch receipt as evidence for this slice. Roll back only its changes in the three core
mixins if the fresh gate fails, preserving earlier lifecycle/identity and unrelated dirty work.

## 2026-09-14: OPT-60 performance acceptance audit — not yet green

Before further consolidation, see the [current cost/stall audit](reports/UNIFY_PATH_COST_AND_STALL_AUDIT_2026-09-14.md).
No runtime changes in this audit. Re-reading all relevant rotations with live-writer sharing,
exact PID and the existing 21:04:04–21:17:55 window finds **81 stalls, maximum 4116.3 ms**;
four successive F11 samples remain in `show_exist_thumbnails -> get_image_files -> iterdir`.
Grouped availability, preview metadata checks and row-status DB work also reach GUI I/O.
The old scan is not a demonstrated regression from the new card-effect timers; it remains
reachable around the unified path. The earlier sampled GUI pass below is a correctness receipt,
not a latency pass. Absence of ERROR records never established absence of stalls.

Five-repetition synthetic A/B: 200-card build medians 586.112/642.690 ms (HEAD classes/current),
with variability on repeat; 200-card native deletion max 102.753 ms in the first run. Home's
existing progressive renderer means this is not a measured synchronous Home freeze. Coalescing
10,000 submissions into 200 latest entries is cheap but excludes paint/download work. Fresh
focused lifetime suite: 31 passed, 6 SWIG warnings, exit 0. No new live acceptance lap.

Next gate: instrument and guard the observed synchronous preparation/availability seams, use
the existing worker projection and identity-scoped delivery, then budget GUI application and
measure first/all-card latency plus event-loop delay. Keep status DB work separate. Establish
authoritative completion before download optimization; require matched viewer-only/overlap,
Fast/Advanced, cold/warm and close/retry resource/stress receipts before calling Unify optimized.

## 2026-09-14: OPT-60 sampled source GUI receipt (21:04 launch)

The user explicitly requested source launch; main PID 925068 started 21:04:04, after the
20:57:47 card-effect edit. Human sign-in was completed before this lap. Existing local test
client ping and action discovery passed; no installed build, hot reload, authentication
automation or new control path was used. This removes the fresh-launch blocker below.

**Sampled GUI PASS:** a server-linked two-study candidate showed 13 Home cards. Native Home
card double-click opened the requested series with 8 slices; requested/rendered Series UID
matched and rendered Study UID belonged to the exact candidate's distinct member set. Native
wheel changed visible slice 5/8 to 6/8, preserving both identities. Native close returned the
tab count from 5 to 4; an empty-result search cleared the table and Home cards to zero. Exact
reselection restored 13 cards; native double-click reopened the same Study/Series with 8 slices
and tab count 5. A surviving original tab still rendered its own first series (5 slices,
Series UID matched) on native card click. No name-based patient joins or clinical fixtures.

Two computer-control interruptions were not product defects: an expired screenshot handle
required reobservation, and an unrelated foreground window intercepted one input. Fresh
observation/activation and one retry succeeded. The failed/no-viewport command was not counted
as a render pass. No native OLE drag was performed or inferred from downstream commands.

**Logs, 21:04:04 through 21:17:55:** app has 2 ERROR records for one attachment worker failure
at 21:06:26 (`GetStudyAttachments` non-success -> RuntimeError); viewer has 0 ERROR; download
has 7 ERROR records at 21:08:47–21:09:03 for repeated `Response too large` failures and final
series failure. These precede the agent lap; they are not an authentication failure, blanket
server-cause diagnosis, or evidence of thumbnail timer regression. From 21:10 through the
cutoff there are no new ERROR/CRITICAL records in the reviewed app/viewer/download logs.
No deleted-Qt/QThread-destruction markers were found. Native log: 0 access violations, one
startup non-terminal COM event; Windows Application 1000/1001/1002 review found no matching
Python/AI-PACS crash/hang events. Do not infer absence of stalls from missing parsed metrics.

**Still open:** real progress -> retry/Ready -> close, concurrent completion with a surviving
tab, Advanced-panel independence, genuine changed-payload same-identity refresh and large
progressive replacement, native drag, offline/cine/heavy-import/stress/installed acceptance.
The 441-pass code receipt remains separate; no source code changed in this live-verification
turn. The attachment and response-size incidents need separate bounded diagnosis under the
existing network/download backlog; do not increase protocol size caps blindly or optimize
downloads before establishing authoritative completion. Direct map-clear/worker-generation
Unify work remains staged. This sample does not close all OPT-60 or historical crash gates.

## 2026-09-14: OPT-60 card-owned effect retirement

**Default-on; source GUI pending a fresh launch.** The next bounded slice preserves the
purpose of card-local effects: 400 ms progress interpolation, 450 ms delayed presentation of
Ready and its 2500 ms label interval. These are UI effects, not download-completion authority.
Seven corrected baseline guards failed / one passed (exit 1): old Ready overwrote newer
progress, an old hide concealed new progress, cleanup left animation running, terminal updates
were accepted, manager reset/dispose did not retire card effects, and the animation lacked a
native parent. The first test draft used an invalid instance enum; it was corrected and the
baseline rerun before production changes. No native crash was reproduced by these guards.

`CircularProgressborder` now owns two reusable single-shot timers and its progress animation.
New state/progress cancels superseded effects; terminal cleanup rejects late effect setters,
stops both timers and all direct-child property animations (including overlapping priority
flashes), and leaves children/visible pixels parented until normal owner deletion. Manager
reset/dispose calls this before dropping its map. Normal progressive rendering is not disposal.
An adversarial transition check caught a stuck Ready label after timer cancellation; two
additional fail-before guards now require pending/retry to remove that obsolete label.

**Historical correction:** the constructor does have `theme_manager`; the old cleanup accessed
the nonexistent card `_on_theme_changed`. Its outer catch therefore skipped animation cleanup.
The prior claim that an absent guarded attribute prevented that abort was incorrect. No owner
call to this cleanup was found in the audited paths, so this is a demonstrated method defect,
not evidence that it caused the earlier clinical crash. The manager owns/disconnects its theme
subscription; a card must not impersonate that receiver.

Changed runtime: `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py` only. Guard:
`tests/code/ui_services/test_thumbnail_card_effect_lifetime.py` (14 real-Qt synthetic cases),
including native parent deletion, independent live sibling, snapshot preservation and bounded
timer count. Final code receipt is recorded in section 15. Core-only source; no dependency,
mirror source, worker, filesystem/network/DB operation, decode/geometry/count/key/route change.
Final expanded gate: **441 passed / 1 existing opt-in GUI KPI skip**, 6 existing SWIG warnings,
31.14 s, direct pytest exit 0; **462 mirror pairs match**. Includes the 17 import/overlay-crash
guards and adjacent Home, manager, multi-study identity, active/count and priority boundaries.
No speedup, full-build, lint, installed-runtime or all-crashes-fixed claim.

The documented client passed ping then action discovery. The running source main process
started at 20:41:10, before this change: do not count it as live acceptance or hot reload it.
After human source relaunch/sign-in, exercise real progress/Ready transitions, Home replacement
and clear, native exact-series open, close/reopen with another tab alive, and the independent
Advanced panel; verify rendered identity/counts and session-scoped logs. No fabricated download
completion events. Code and GUI remain separate gates.

Previous-slice log receipt (20:41 run, reviewed before this edit): no app/viewer ERROR, three
normal closes, no access violation or deleted-Qt markers in the scoped review. Four download
ERROR records comprise a broadcast-response-limit event (three records) and a cancellation;
they are not an authentication failure or proof of a server-side cause. No definitive completion
marker occurred. Startup stalls remain; these observations do not close GUI/stress acceptance.

Next: audit direct legacy map clears and worker-image generation identity before changing those
boundaries; retain Home drag/priority migration and authoritative completion as separate
OPT-35/OPT-04 work. Rollback only this card effect/manager-hook slice and its guards together,
preserving prior manager timers, signal relay, identity and paint-atomic swap changes.

## 2026-09-14: OPT-60 manager-owned callback retirement

**Default-on, code PASS; fresh-source GUI BLOCKED.** The next bounded lifecycle slice
reproduced old pending progress being delivered after `reset_all_states()` and a retained old
card selecting the same numeric key after reset/replacement. The original seven guards failed
(exit 1): the two behavioral defects, missing terminal-disposal contract and missing patient-exit
wiring. Two additional Home-owner guards failed before Home integration (2 failed / 10 passed).

`ThumbnailManager` now owns its six delayed-work scheduling sites through parented single-shot
timers and a generation-scoped callback registry. Reset cancels those timers and clears pending
progress/throttling state before reusing the manager. Terminal `dispose()` is idempotent: it
retires deferred work, disconnects its own theme/image receivers, releases the bound viewer
callback and clears series/button maps. Late update/action entry points reject terminal owners;
card click/retry/selection callbacks require their creation generation and current card mapping.
Normal keys, count semantics, coalescing intervals and rendering policy remain unchanged.

Patient exit retires the main and Advanced-panel managers independently before viewer teardown.
Home uses a weak registry for both render schedules and disposes retired managers on clear,
including keep-widgets clears. It does not delete/reparent native cards: existing deferred
deletion and the paint-atomic replacement still own that work. Normal progressive completion
does not dispose a live manager. No new worker, dependency, feature flag, disk/network/DB work,
forced GC or cross-viewer mutable state was introduced.

Files: `thumbnail_manager.py`, `_pw_lifecycle.py`, `right_panel_widget.py`; new guard
`tests/code/ui_services/test_thumbnail_manager_retirement.py` (17 synthetic real-Qt tests).
A final adversarial guard exposed disposal after native timer/manager destruction; validity
checks now skip already-destroyed Qt resources while still releasing Python-owned state.
Final adjacent selection: **424 passed / 1 existing GUI KPI skip**, 6 SWIG warnings, exit 0,
including the existing 17 import/overlay-crash guards. Compile and scoped diff checks pass;
**462 mirror pairs match** (all three runtime files are core-only, no mirror update required).
No full-build, lint, installed-runtime or performance-improvement claim.

The documented client ping failed at this handoff and the prior main PID was absent. No
automatic launch/recovery/login was attempted; the human was asked for a fresh source launch
with `AIPACS_TEST_SERVER=1`. The earlier 20:03 live receipt predates this patch. Acceptance:
small/large Home replacement and empty clear, same-identity refresh, native exact-series open,
progress followed by close/reopen, a remaining live tab and independent Advanced panel, then
session-scoped log/resource review. Do not fabricate completion events or use clinical DB tests.

Remaining lifecycle boundaries are explicit: `CircularProgressborder` owns separate ready-label
timers/animations, including a historical misplaced cleanup disconnect; these were not changed.
Already-running card animations, delete-without-explicit-owner-close reachability, direct legacy
map-clearing callers and worker-image identity across a reusable reset require their own evidence.
This is manager deferred-work/owner retirement, not closure of every widget resource or a proven
fix for the earlier native crashes. Home drag/priority migration, completion convergence and
UID-cache migration remain separate OPT-35/OPT-04 work. Rollback only this slice's manager,
patient-exit and weak Home-registry hunks together; preserve previous relay/action/swap changes.

## 2026-09-14: OPT-60 fresh-source sampled GUI acceptance (20:03 session)

The user explicitly requested source launch; one source launch (main PID 1113400,
20:03:33) contains the latest 19:17:26 runtime edit. Home was observed after human sign-in;
no authentication was automated. The documented local client passed `ping` then `list_actions`.
This supersedes the connectivity/old-process blocker below, not the remaining acceptance gates.

**Sampled GUI PASS:** a server-linked two-study case displayed 13 Home series; an empty-result
query cleared both table and preview to zero; restoring the exact current row restored 13 cards.
Native Home-card double-click displayed the first series with 8 slices. Rendered Series UID
matched the first series entry, and rendered Study UID belonged to the verified case membership.
Native wheel input changed visible slice 5/8 to 6/8 with both identities preserved. Native tab
close, reselect and native double-click reopened the same Study/Series with 8 slices; tab counts
were 3 -> 2 -> 3. Pixels were observed, not inferred from command acknowledgements.

**Still unverified live:** a genuine changed semantic payload for the same ordered identities
through the small non-progressive swap; large/progressive -> immediate owner replacement;
real priority/completion after close; extended identity/offline/cine and native-drag matrices.
Reselection/opening alone does not prove no blank frame or wrapper collection. No completion
event was fabricated. Previous code evidence remains 390 passes / 1 existing skip plus 17
separate import/overlay guards; those suites were not rerun during this GUI-only lap.

Session-scoped log review through 20:12:47 found no ERROR/CRITICAL, deleted-object/traceback
markers or access violation in the reviewed app/viewer/download/DB/native logs. There were
38 main-thread stalls, maximum 1909.1 ms, and one non-terminal startup COM `0x8001010d`
in the main PID. Close exit was 34.7 ms; deferred GC was 154.5 ms. Zero real completion
emission markers occurred. These are sampled observations, not a performance comparison,
Windows-event-log audit, heavy-import crash closure or installed-build acceptance.

**Control-tool fidelity finding:** `get_thumbnails_data` returned one row while native Home
and patient sidebar showed 13 and `get_series_info` returned 13. Do not use that adapter's
count as the displayed-card oracle. Its current implementation reads `lst_thumbnails_data`;
the reason for the incomplete projection needs a separate guarded adapter investigation.
Clinical responses stayed transient; no identifiers/images or raw payloads were added to docs.
No runtime code changed in this lap.

## 2026-09-14: OPT-60 bounded same-identity Home refresh swap

**Implemented by default; code PASS, live BLOCKED.** The next independent scheduling seam fixes
the documented clear-before-deferred-build gap. Three real-Qt guards failed before correction
(3 failed / 8 passed, exit 1). This is a paint-continuity fix, not a native-crash diagnosis.

`right_panel_widget.py` retains old cards only for a non-progressive request at or below the
existing immediate threshold whose ordered immutable action identities exactly match the old
signature and are all known. It retires callbacks/timers immediately, then removes old cards and
builds replacements within the existing paint-disabled render turn, activating layout before
re-enabling paint. The input-synchronous deferral and generation checks remain. Changed/unknown
identity, changed membership/order, explicit clear, large sets and explicit progressive requests
keep immediate clearing; no old patient preview is deliberately preserved across identity changes.
Full signature coalescing remains. A preparation-failure guard caught retained stale cards in the
first implementation; failure now clears the current pending replacement and allows a retry.

Final `test_home_small_refresh_swap.py`: **16 guards**, including supersession, input retries,
grouped repeated numbers/unnamed series, old-action rejection, preparation failure and unchanged
large-set delegation. Expanded gate **390 passed / 1 existing GUI KPI skip**, 6 SWIG warnings,
exit 0. Separate existing import-registration/overlay-crash guards: **17 passed**, exit 0.
Compile/diff checks pass; **462 mirror pairs match**. One core-only runtime file changed; no
new flag, dependency, decoder, downloader, database, native viewer or package definition.

The existing MCP tool is not exposed; its documented local client `ping` failed. Observed
Python `main.py` processes started at 18:29:49, before the latest edit at 19:17:26. Do not count
that process or the older 17:57 live lap as acceptance. No relaunch/login/recovery was attempted.
After human source restart/sign-in with the test server enabled, verify same-case metadata
refresh without blanking, changed-patient/empty search clearing, repeated replacement, exact
Home double-click output and session-scoped logs. This is paint-atomic replacement, not a
transactional all-or-nothing guarantee for individual card-build failures or a benchmark.
Rollback only this keep-widgets/removal-helper/swap/error-retirement slice and its guard.

### Implementation and previous-crash status

| Area | Evidence-backed status | Still required |
|---|---|---|
| Large local import / partial-layout Qt re-entry | September 5 worker-registration and no-nested-event-loop fixes remain in source; 17 import/overlay guards pass again | Fresh heavy-import/open/close replay and native/Windows log evidence; no blanket crash-closure claim |
| Thumbnail heap corruption during stylesheet repolish | September 1 scoped early root-style correction exists; thumbnail guards remain in the expanded passing selection | Relevant source/installed stress acceptance; not re-diagnosed by this UI patch |
| Home identity, search and queued render retirement | Code guarded; earlier sampled Server/Local and exact-series open live PASS | Extended offline/pins/cine/multi-study matrix |
| Patient-tab outward signal lifetime | Code guarded; sampled close/reopen live PASS | Real priority/completion events with a closed tab |
| Home owner retention and small refresh swap | Code guarded and default-on | Fresh-source live acceptance |
| Generic manager timer/state disposal, native drag/stalls, priority migration, definitive download completion and later UID-cache work | Not closed by the completed slices | Independent guarded changes/measurement; OPT-04 before download-path optimization |

## 2026-09-14: OPT-60 Home render owner retirement

**Default behavior confirmed (user request, 2026-09-14):** the recent Home action/metadata,
search/render retirement and patient-tab signal-lifetime corrections are unconditional normal
runtime paths, not opt-in patches. No activation environment variable, configuration edit or
new feature flag is required. Inspection found no default flip needed; no unrelated experimental
flags were enabled or safety switches removed. The focused default-path recheck passed 90 tests,
6 SWIG warnings, exit 0. This confirmation does not close pending fresh-source/live or installed
acceptance gates, and does not change the running process until source restart.

**Fixed and code-verified; fresh-source live gate pending.** A completed progressive Home render
left `_progressive_manager` attached after `clear_content()`, retaining deleted card wrappers
and the old action map even through a later immediate render. The Home action closure also
strongly retained the panel; invoking it after native panel deletion raised a deleted-object
RuntimeError while trying to schedule work. These are deterministic ownership findings, not
attribution of a clinical crash or evidence that the theme signal itself leaks a manager.

`right_panel_widget.py` now drops only the retired progressive-manager reference after stopping
its timer. Card callbacks retain their manager until the existing deferred card destruction;
there is no eager native deletion, state reset, forced collection or new disposal API. The shared
Home action factory uses a weak panel reference and checks native validity plus the render token
both before queueing and at delivery. It retains Qt-context zero-delay dispatch. A normal timer
finish is NOT retirement: current cards, counts, identity and double-click remain usable.

Guard `tests/code/ui_services/test_home_render_owner_lifetime.py`: **4 failed / 3 passed before**,
exit 1; final **10 guards**. Expanded Home/search/thumbnail/multistudy/close/download boundary
selection: **374 passed, 1 existing opt-in GUI KPI skip**, 6 SWIG warnings, exit 0. An initial
expanded command used two incorrect close-test paths and collected no tests; the corrected run
above is the acceptance evidence. Compile and diff checks pass; **462 mirror pairs match**.
The sole runtime file is core-only. No change to generic ThumbnailManager or patient-viewer
states, study/series keys, object/frame counts, render cadence, input-dispatch guards, download,
decode, Fast/Advanced separation, dependencies or packaging.

Existing source MCP `ping` responds, but main PID 1114928 started at 17:57:23, before this edit
at 18:22:12. Do not reuse the earlier lap as acceptance. After human source restart/sign-in,
exercise large/progressive selection -> empty search -> small/immediate selection, repeated
replacement and exact-series double-click. The code guards prove wrapper reachability; live
observation must not claim memory collection from disappearing cards alone. No restart/hot reload
was attempted. Roll back only the reference-release and weak-action hunks with their guard.
Full generic timer/state disposal, atomic small-set replacement, Home drag/priority migration,
pixel-revision/cache phases and prior real completion/priority live gates remain open.

## 2026-09-14: OPT-60 patient-tab external signal lifetime

**Fixed and code-verified; sampled open/close/reopen live PASS; completion/priority live gate pending.** Continue the independent lifecycle
work without claiming full ThumbnailManager disposal or changing priority/download routing.
Creation in `_hp_modules.py` connected priority and app-lifetime download completion through
closures capturing the patient widget (and Home for priority). Deterministic Qt tests prove
delivery after close/deletion and retention of the deleted patient's Python wrapper.

`HomeTabService.bind_patient_signals` now installs one patient-parented QObject relay, with weak
Home/patient references and typed slots. It forwards the same raw series key and supplied Study
UID to the existing priority handler; completion retains the existing primary Study UID filter.
Priority binding still precedes lazy Download Manager lookup. Exit disposes only these connection
handles before existing viewer teardown; repeated disposal is harmless. QObject destruction
also disconnects for delete-without-close/rejected-tab paths, and queued deliveries check the
retired/closing state. Rebinding retires the old receiver without disconnecting other subscribers.
No new downloader, retry, cache policy, thread pool, timer, I/O, event pump or forced collection.
The existing VTK/GC teardown and Fast/Advanced separation are unchanged. Worker-signal delivery
is tested on the GUI thread; the old implementation is not claimed to have failed that guard.

Guard `tests/code/ui_services/test_patient_tab_signal_lifetime.py` executes the production wiring
block with synthetic Qt owners/publishers, avoiding the clinical DB/viewer construction graph.
Before correction: **6 failed / 2 passed**, exit 1 (after correcting a test teardown double-delete).
Final **16 guards** cover routing/filter/key preservation, close/delete, wrapper collection,
worker/queued-close, explicit exit, rebind, sibling subscriptions, publisher/Home destruction,
optional managers and creation order. Expanded Home/search/thumbnail/multistudy/close/download
boundary gate: **364 passed, 1 existing GUI-only skip**, 6 SWIG warnings, exit 0. The skip is the
pre-existing opt-in KPI walkthrough, not live acceptance. **462 mirror pairs match**, exit 0;
all three changed runtime files are core-only, no mirror or package definition changed.

**Fresh-source live receipt, 17:57:23-18:01:10:** main PID 1114928 (venv redirector 1110568),
human sign-in; all three runtime edits predate launch. Bounded MCP selection of a two-study
case showed 13 Home cards. Actual Home thumbnail double-click displayed the matching Series UID
and case-member Study UID, 8 slices and visible pixels. Native patient-tab close removed that
tab; Home cards remained and the bridge responded. Reselecting and double-clicking reopened
the same Study/Series with visible pixels, 8 slices, and no duplicate tab (tab counts 3 -> 2 -> 3,
including Home and Download Manager). The app was left open. Identities remained transient.

Scoped logs: app 354, viewer 201, download 229, DB 181 records; zero ERROR/CRITICAL, traceback
or deleted-object error markers. `exit_patient_widget` completed in 42.5 ms and deferred close
GC in 195.9 ms. One startup main-process `0x8001010d` was non-terminal; no access violation
record in this interval. 38 timer stalls, max 1773.8 ms, in mixed startup/automation/idle work:
not a matched performance comparison or no-lag claim. Zero worker-completion/emission markers;
real completion/priority behavior and absence of closed-tab refresh under those events remain
unverified live. GUI close is not proof of wrapper collection (that has deterministic Qt evidence).
No runtime changes, full build, release or clinical data edits during this live lap. The older
16:35 process predates this patch and is not its acceptance evidence.
Rollback only the relay/binding/exit-disposal hunks and guards; preserve earlier Home work.
Remaining: full ThumbnailManager state/timer disposal, render-owned Home managers, atomic
small-set replacement, Home drag/priority intent migration and later UID-cache phases.
OPT-04 definitive completion remains prerequisite to download-path optimization.

## 2026-09-14: OPT-60 search-owned Home preview retirement

**Fixed and code-verified; sampled Server/Local live gate PASS, extended matrix pending.** This follow-up closes the caller
gap observed in the 15:39 source lap below, not the full Unify plan. Search cleared rows without
retiring selection/preview producers. An empty selection was also treated as permissive initial
state by late-response guards. The service was unchanged against HEAD before this correction;
do not classify the symptom as a regression introduced by queued-render retirement.

**Fresh-source receipt, 16:35:43-16:41:32:** source main PID 1111380 (venv redirector 1111452),
human sign-in; both changed runtime files predate launch. Bounded MCP Server query and unique
current-row selection produced 13 Home cards for a two-study case. Empty query produced an empty
table, no old cards and `0 series`; old-row selection was rejected. Valid reselection restored
13 cards. Actual Home thumbnail double-click opened the patient tab and rendered the matching
Series UID / case-member Study UID with 8 slices. A later double-click reused that tab without
duplication or identity change. Local selection showed 6 cards for its selected study; another
empty Local query cleared table/cards/count. Switching source alone was not used as proof.

Logs scoped to that interval: app 405, viewer 142, download 243 and DB 158 records; zero
ERROR/CRITICAL or thumbnail-cleanup errors. No access violation; one startup main-process
`0x8001010d` at 16:35:43 was non-terminal. 41 timer stalls, maximum 2236.1 ms: mixed startup,
automation and idle workload, not a matched performance comparison or a no-lag claim.
Pins/row-shift timing, advanced-search overlap and Offline Cloud were not exercised live;
their deterministic guards remain separate evidence. No runtime edits or extra app instance
in this live lap. The launch-pending paragraph below records the earlier implementation handoff.

`HomeSearchService._clear_search_results` is now the shared boundary for all five existing
service clear sites: Local, Offline Cloud, normal Socket (empty/nonempty), and advanced Socket.
It rejects cancelled/superseded clears; retires row-number debounce and orphaned selection,
fetch ownership, render markers and panel generation; and displays `0 series`. An explicitly
retired selection rejects late responses until a real selection is marked. A selected pinned
row survives only when its Patient/Study identity matches before/after clear and the active
preview. Its fetch is retained, with a pending thumbnail debounce rebound to the new row.
The table remains the pin-retention authority; no change to its native-safe teardown.

The same guard prevents advanced Socket's formerly unguarded pre-insert clear from erasing a
newer search. Thumbnail task cleanup now treats cancellation normally and releases only its
own current handle, never a newer task. Existing Local/Offline early-clear timing, Socket
wait-before-clear, filters, ordering, grouped UID/count contracts and download paths remain.
No added I/O, nested event pump, blocking wait, dependency or flag; only current row metadata
is read in addition to existing clear work. This is not a performance measurement or a complete
request-epoch/manager-disposal migration.

Guard `tests/code/ui_services/test_home_search_preview_retirement.py`: **7 failed / 4 passed**
before the main fix (after correcting one fake-import setup omission), exit 1. Two subsequent
task-cleanup guards failed before their fix. Final **18 new guards**, including pin row movement,
Local/Offline, nonempty replacement and stale queued render. Focused/adjacent **302 passed**,
6 existing SWIG warnings, exit 0. **462 mirror pairs match**, exit 0; both runtime files are
core-only, so no mirror payload changed. Two existing source guards now follow the shared clear
boundary and additionally assert its generation ordering/no event pumping.

Next live gate: human relaunch/sign-in once, then bounded MCP selection and native Home checks
for empty search -> zero cards/count; subsequent selection and exact-series open; retained pins
including row movement; Local/Offline where available. The running 15:39 process predates this
patch and cannot validate it. No restart, build, release, patient-data deletion or installed test
was performed in this slice. Rollback only this helper/call-site, explicit-retirement and
task-cleanup hunks plus their guards; preserve prior render/identity and other dirty work.
Full manager disposal, atomic small-set replacement, drag/priority routing and later UID-cache
phases remain open. OPT-04 completion verification still precedes download optimization.

## 2026-09-14: OPT-60 queued Home-render retirement

**Historical live receipt; empty-search gap is now code-fixed above, live still pending.** At the user's request, continue independent
Unify work while leaving native-drag and stall investigation open. This bounded lifecycle slice
does not change Home drag/priority routing or bypass OPT-04 completion verification.

`RightPanelWidget.clear_content()` stopped an existing timer but did not retire queued render
starts/retries. A delayed callback could rebuild old cards or restart progression after a clear;
context-free single shots also invoked callbacks after the Qt panel had been destroyed.
The clear operation now owns generation invalidation. New requests capture that generation;
direct renderer calls bind an omitted generation before deferring. All four render/retry single
shots use the panel's Qt context, and the progressive timer is parented to the panel. Clears
release pending row payloads and reset only the retired generation's input-deferral budget.

Evidence: 9 failed / 4 passed before correction, exit 1. Sixteen final lifecycle guards include
real Qt destruction, input retries, replacement/coalescing, re-request and timer ownership.
Focused/adjacent Home, thumbnail, multistudy and control selection: **197 passed**, six existing
SWIG warnings, exit 0. **462 mirror pairs match**, exit 0; changed runtime file is core-only.
No new dependency, flag, module, I/O, nested event pump, forced collection or decoder change.
Immediate/progressive cadence, large-set threshold, input-sync guard, UID/count contracts and
download behavior are unchanged. No measured live-performance improvement is claimed.

The user requested a new source launch at 15:39:22 and completed sign-in (main PID 1106292).
Fresh-source sampling passed: 13-card and 17-card patients, five alternating selections at
0.65-second client intervals, final 13-card selection and exact Series/Study UID open with
8 slices. No selection alone opened a tab. This does not prove every timer interleaving or
application-destruction case live; those remain covered by deterministic Qt guards only.

**New observed integration gap, not a proven regression:** an empty server search clears the
table but leaves the prior 13-card preview visible. Its double-click correctly opens no tab
without a current row. `home_search_service.py::search_server` clears only the table in its
empty branch; that service has no diff against HEAD. The earlier assertion that this branch
already clears the right panel was wrong. Guard the current-search/selection retirement seam
before changing it, including cancellation, pinned rows and late results; do not weaken the
Home action identity guard. This gap is not evidence that generation invalidation failed.

Review through 15:52:00: no ERROR/CRITICAL or new access violation; one non-terminal startup
main-process COM event, 50 timer stalls (max 2222.2 ms). No matched performance claim or stall
investigation; see the detailed provenance receipt. No runtime changes were made in the live lap.
Full manager disposal/outward priority callback disconnection, atomic small-set replacement,
Home drag/priority convergence and later UID-cache phases remain open. Rollback only the render
retirement/context/timer-parent hunks and associated guards; preserve prior Home identity work.

## 2026-09-14 next prerequisite: OPT-35 / OPT-60 current-row MCP selection

**Fixed, code-verified and source-live verified for the sampled selection workflow.** The previous GUI lap exposed a test
adapter gap: `select_patient` bypassed the Qt row selection and the command wrapper filled
missing identity from accumulated server-search history. Home correctly refused the resulting
incomplete selection. Fix this prerequisite without relaxing the production identity guard.

`HomeWidgetAdapter.select_patient` now resolves exactly one visible current table result by
Patient ID and optional member Study UID, selects that real row, revalidates after synchronous
selection signals and queues the existing single-click timer. Grouped selection returns the
canonical row Study UID; caller names cannot override current row data. Missing/ambiguous/hidden
results, incomplete study identity, active searches and non-GUI calls are rejected. The command
wrapper delegates resolution and reports `selection_state=queued`, not rendered completion.
There is no new I/O, event pumping, timer, downloader, module, dependency or feature flag.

Evidence: the initial 15 behavioral guards all failed before the fix (after correcting two
test-harness setup errors); all pass afterward. Three additional guards cover missing canonical
UID, synchronous result replacement, and no I/O/nested event pump. Final focused/adjacent Home
selection: **99 passed**, six existing SWIG warnings, exit 0. Command/bus/permission/viewer/build
boundary selection: **89 passed, 1 failed**, exit 1. That failure is the existing-stage config
parity check: staged `echomind_settings.json` and `printing_config.json` differ from sanitized
expectations. The test, release-gate source and canonical two configs have no diff against HEAD;
this patch does not touch them or rebuild generated output. Do not call that lane green.

Both changed runtime adapter files were synced to EchoMind payload mirrors; **462 pairs match**.
The MCP wrapper docstring, control guide, test indexes and regression catalog were updated.
Rollback is the two adapters and their mirrors plus associated contract/guard changes only;
leave all previous Home identity and renderer work intact. No build/release was performed.

The fresh 15:15:21 source launch (main PID 1106228, human sign-in) contains the correction.
Live PASS: MCP selection without a compensating row click, native Home double-click creating
a tab, then reuse for the same-number series from another study. Both rendered Series UIDs
matched the destination metadata; Study UIDs were distinct, and each stack had 8 slices.
Grouped-member reselection returned the canonical row; a nonexistent ID was rejected with
`HOME_SELECT_FAILED` without adding a tab. Native wheel moved index 4 -> 5 with UID preserved.
The same 99-test focused lane passed again, exit 0. No runtime code changed in this receipt.

Session review through 15:26:01 found no ERROR/CRITICAL in the four regular logs, 37 timer
stalls (maximum 2263.1 ms), no convergence-miss markers, one startup main-process
`0x8001010d` and no new access violation. This is not a matched performance benchmark.
Native sidebar drag remained INCONCLUSIVE: its drag image stayed active; Escape canceled it,
the empty destination remained empty, and the bridge stayed responsive. Native Home drag,
targeted same-path refresh, cine/offline/unnamed cases and installed acceptance remain open.
See the [detailed receipt](plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md).
Do not advance download/cache changes under cover of this prerequisite or claim Unify complete.

## 2026-09-14 fresh-source GUI receipt: OPT-35 / OPT-60

Source restarted at 13:22:08 at the user's explicit request; human sign-in completed before
tests. `ping`/`list_actions` and the final ping passed. The final header and semantic-refresh
code was present. No product code changed during this verification lap.

- **PASS, sampled Home workflow:** native row selection followed by native Home thumbnail
  double-click reused the existing tab and displayed the selected second-study series (11 slices,
  exact Series UID match). Closing only that test tab, then double-clicking the first-study card
  created a new tab and displayed its exact series (8 slices). Group headers stayed `Study 1/2`.
- **PASS, sampled adjacent boundary:** two repeated-number series from distinct studies loaded
  into separate viewports via the application bridge, with exact UID matches and 9/11 slices.
  Native wheel changed left index 4 -> 5; bridge navigation set right index to 0; UIDs stayed fixed.
  Normal patient open before placement left both viewports empty as required.
- **Observed count refresh:** Home's 13 cards acquired counts after normal data preparation,
  including 8/1/1/9/9/25 and 8/1/1/11/11/18/1. This is a real integration observation, not an
  isolated same-path semantic-only mutation, cine acceptance or proof of complete downloads.
- **INCONCLUSIVE:** one native sidebar drag did not produce a verified destination change.
  A successful `change_series` command is not native drag acceptance. Home drag remains unmigrated.
- **Test-adapter gap, not established product regression:** `select_patient` only calls the
  downstream Home selection handler. It does not select `results_table.currentRow()`, which the
  Home action checks. Initial thumbnail attempts with that incomplete precondition were correctly
  rejected; the same route worked after real row selection. Do not weaken the production guard.

Session health through 13:53:03: no ERROR/CRITICAL in the four reviewed regular logs; 51 timer
stall records (max 1776.5 ms), seven convergence-miss markers, one non-terminal main-process
`0x8001010d`, no new access violation. This interval includes startup, human idle time and test
automation; it is not a matched performance benchmark or a claim of no lag. Source stayed alive.
New-tab request at 13:52:31.439799 -> first-visible marker at 13:52:32.766740 (~1.327 s).

The sampled source-live open/header boundary is now verified; targeted same-path-only refresh,
cine/offline/unnamed cases, native drag and installed gates remain explicit. Unify is not complete.
Follow the existing remaining sequence below. The control guide records the deterministic GUI
preconditions so later laps do not repeat the adapter-only false failure.

## 2026-09-14 follow-up: OPT-35 / OPT-60 live receipt and semantic refresh

**Home double-click: user-confirmed and log-corroborated for the exercised workflow.**
The 12:49:16 source session recorded a two-study open, seven-series metadata publication,
explicit placement and a first visible image with no identity mismatch. This is not acceptance
of every series, native Home drag, offline/cine cases or installed builds. That process predates
the final header-presentation correction and the metadata-refresh change below.

**Next bounded slice: code PASS; new source-live gate PENDING.** Same-path metadata changes
could be coalesced away even when the card count/description changed. Comparison and rendering
now share `extract_series_info_from_thumbnail`; the signature includes normalized visual fields
and the existing immutable action identity. No filesystem reads, hashes, decode, network,
download policy or scheduling changes were added. Pixel-content revision remains separate.

Evidence: new guards **9 failed / 2 passed before**, then **68 focused passed** and
**931 expanded passed / 1 skipped / 3 deselected / 3 existing xfails**, both exit 0.
The same two independently proven HEAD failures listed in the earlier receipt remain explicitly
excluded; no quarantine changes. **462 mirror pairs match**, exit 0. A warmed synthetic
500-row signature-only probe (50 runs) measured median 1.894 ms, p95 2.051 ms; this is not a
matched live-performance comparison or proof of absence of UI stalls.

Remaining ordered work stays under OPT-35/OPT-60 and OPT-04, not a competing plan:

| Gate / slice | Next action and boundary |
|---|---|
| Current live gate | After human source restart/login, verify count/description refresh and repeat exact-series double-click; retain repeated/unnamed multi-study and cine cases in the acceptance matrix. |
| Home action convergence | Migrate Home drag and priority adapters to UID-scoped intent and the existing coordinator; never revive direct downloader helpers. Delete obsolete helpers only after caller/behavior guards. |
| Lifecycle and render scheduling | Explicit idempotent callback disposal; separately guard deferred small-set atomic replacement. Preserve progressive rendering and Windows input deferral. |
| OPT-35 P3 | Audit consumers before internal UID-keyed cache migration; preserve numeric public keys used by existing warmup/viewer consumers. Define producer-driven same-path pixel revision/invalidation. |
| OPT-04 / OPT-35 P4 | Establish definitive download completion/convergence evidence before download optimization; then migrate remaining Download Manager/growing-thumbnail identity keys. |
| Retirement and acceptance | Keep legacy guards until classified authority comparisons and the documented full-matrix/observation window justify retirement. Source live, mirror and installed acceptance remain separate gates. |

Current-session caveats: 16 timer-reported UI stalls over 100 ms (maximum 2058.3 ms during
startup, before the click), 10 convergence-miss markers, and one non-terminal main-process COM
exception remain investigation items. No ERROR/CRITICAL or new access violation was found in
the scoped records. Two legacy PK-guard messages started from `None`; they are not proof of
wrong-study contamination. Details, rollback and timestamp boundaries are in the
[provenance receipt](plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md).
**The overall Unify master plan is not complete.** Fast, Advanced and VTK execution domains
remain separate; only immutable identity/data contracts are shared.

## 2026-09-14: OPT-35 / OPT-60 explicit Home thumbnail open

**Latest user decision:** double-click a Home thumbnail to open/reuse the normal patient
tab and place that exact series in the selected viewport. Single click remains preview-only.
This supersedes the earlier existing-tab-only single-click scope below; it does not change
the empty-layout policy when a patient is opened by name without an explicit series intent.

**Historical implementation receipt; latest live scope is recorded above.** The cache-hit identity loss is
guarded and corrected. Cached single-study, grouped, downloaded-preview and Offline Cloud
producers share `_build_cached_thumbnail_payload` on workers, retaining UID/path/frame fields
and rejecting ambiguous numeric-cache identity. Socket/placeholder payloads carry request-scoped
study identity. No decode, encoding, transport or download-policy change is included.

HomeTabService reuses the standard async open flow, shares in-flight opens and consumes the
last UID-scoped intent only after destination metadata/layout readiness. QObject-parented,
queued callbacks expire after 30 seconds without polling; close/tab changes or a subsequent
placement cancel the intent. Destination-owned keys are resolved afresh, never copied from Home.

Evidence: first requirement run **6 failed / 21 passed**, plus the downloaded-preview worker
guard failed independently before convergence. Two additional failing presentation guards
prevented UID preservation from adding a raw-UID header to single-study Home previews;
explicit group labels are retained and unlabeled multi-study headers use `Study N`.
Latest focused run **57 passed**, exit 0.
Final broad run **920 passed / 1 skipped / 3 deselected / 3 existing xfails**, exit 0; two explicit
exclusions are proven unchanged HEAD failures (`test_login_carries_the_user_identity_ids`,
`test_status_flags_are_stashed_on_the_widget_to_avoid_recompute`), not new quarantines.
Stateful identity **1 passed** (150 examples); **462 plugin mirrors match**. See the current
[provenance receipt](plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md).

Remaining extended acceptance: human restart/login with the final patch, actual Home double-click on unopened and existing
patients, multi-study repeated/unnamed series, cine frame count and UID-matched rendered pixels.
The 12:49 source session exercises the core route, but predates the final header correction.
Installed acceptance remains separate.

## 2026-09-14 historical receipt: first live click check FAILED

**Current status supersedes the earlier connectivity/login blockers below.** After human login,
`ping` and `list_actions` succeeded through the existing local client. In the fresh 12:10 source
session, a bounded MR search found a single-study case with 18 series. A real Home Series 2 card
click selected the card but did not activate the already-open patient tab; the probe returned
`NO_ACTIVE_TAB`, and no `[HOME-SERIES-ACTION]` outcome was logged. The case-specific log confirms
the Home cache-hit route. Source review and execution of the actual cached-payload method with
synthetic I/O confirmed `_build_cached_thumbnail_payload` discards BOTH study and series UIDs
even when the synthetic DB row contains them. The new action boundary correctly refuses that
incomplete identity. Existing card tests start from complete metadata and missed this producer
boundary. Do not weaken the UID gate or guess from the selected patient/card ordinal.

Control comparison passed: MCP series 2 -> viewport 0 and series 3 -> viewport 1 rendered 11
images each with matching study/series UIDs. MCP slice navigation 6 -> 1 and actual mouse wheel
1 -> 2 were visible and state-confirmed. Native drag attempts did not prove a completed drop;
one remained in the OLE drag loop and was canceled with Escape. Mark native drag INCONCLUSIVE,
not a confirmed application regression. This sample does not cover multi-study/cine/offline.

No runtime fix was made during this verification. Next bounded correction: guard the full
cached-payload -> card -> action chain, preserve UID provenance at each producer, and audit
number-collision handling before further cutover. Repeat the actual Home-click live scenario
afterward. Detailed evidence and limits are in the September 14 provenance live-receipt section.

## 2026-09-14: mandatory two-gate verification for existing Unify / OPT slices

**12:10 follow-up:** the user explicitly authorized a normal source-app close/restart. The old
source processes exited and one fresh source launch now includes the click patch and the
process-scoped test flag; the production Agent Gateway is disabled for this run. The app is at
login, which remains human-operated. Pre-login `ping` is unavailable: the live gate is still
BLOCKED, not failed or passed. Focused automated recheck: **61 passed, exit 0**, reruns disabled.
The control guide's authorized-restart receipt records process/source details; no runtime fix
or persistent configuration change was made during this verification attempt.

**User-required operating policy, not another implementation plan:** each runtime slice requires
automated code tests and an affected-workflow live source-GUI pass. The durable procedure is
[`AGENT_CONTROL_AND_TESTING_GUIDE.md`, section 0](for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md),
also indexed in `AGENTS.md`, `CLAUDE.md`, the subsystem index and guard index. Discover the existing
`aipacs-control` MCP first; its existing CLI uses the same local Test Control Server when tools
are unavailable. Preserve human bootstrap, one source instance and no clinical/production gateway.

**OPT-35 / OPT-60 live gate remains BLOCKED:** on this check the MCP was not exposed and CLI
`ping` failed with local socket unavailable (exit 1); no named test pipe was found. The source
app still dated from 10:57, before the click patch. No patient workflow, relaunch, external
reception query or configuration change occurred. This is not evidence of a viewer failure.
After human restart with `AIPACS_TEST_SERVER=1`, verify `ping`/`list_actions`, choose a bounded
verified multi-study case, and exercise actual Home-card click plus destination/render checks.
MCP `drag_series` alone bypasses this changed boundary; Home drag/retry remain separate work.
Code verification already recorded below does not close this live gate.
Documentation/control discovery verification: the existing test-server, adapter-contract and
MCP-inventory suites passed **11 tests, exit 0**, reruns disabled; these are not live GUI tests.
This policy update changed documentation only, not runtime control/clinical behavior.

## 2026-09-14: OPT-35 / OPT-60 Home click identity cutover

**Status: implemented and automated-verified for existing open tabs; live pending.**
Both Home render schedules now use one card factory and a render-scoped immutable
`SeriesActionIdentity` map. Posted clicks reject cleared/replaced renders. Home's
handler delegates to `HomeTabService`, resolves a unique destination by both UIDs,
rechecks after activation, and calls the normal viewer entry with that tab's key.
The old direct-download click body was removed; generic numeric drag keys stay
unchanged. No new downloader, I/O probe, decode path or cross-backend state exists.

Four behavioral failures exposed the old ordinal/dead-handler boundary; seven
additional tests described the absent destination API. Four later fail-before
guards required advancing the identity-only render-signature prerequisite: compare
the same immutable action to prevent same-PNG stale clicks. Full visual signature,
pre-deferred-clear scheduling, Home drag/retry, coordinator migration, lifecycle
and completion correctness remain separate. Missing/ambiguous/closed destinations
fail closed; automatic new-tab creation is not introduced.

Final focused suite **238 passed, exit 0**; stateful projection **1 passed, exit 0**;
**462 mirrors match, exit 0**. Two brittle Windows guard tests now execute the
actual deferral behavior; one obsolete quarantine entry was removed after XPASS.
No new module/dependency/flag/schema; all five runtime files are core/unmirrored.
Rollback the five cutover hunks together, preserving prior metadata/projection fixes.
The separate 10:57 source run had ten matching render identities/zero SKIPs, but
predates this click patch and does not verify its live acceptance. Full evidence,
scope and restart matrix: the final September 14 provenance implementation record.

## 2026-09-14: OPT-60 right-panel card metadata prerequisite

**Status: fixed and automated-verified; source-live acceptance pending.** The shared
`RightPanelWidget.extract_series_info_from_thumbnail` now preserves supplied study/series
UIDs, original/display/storage identities, exact series path and separate frame/object
counts. A fixed metadata allowlist repairs the existing projection; no parallel helper,
new I/O, decoder, timing policy or action route was added. A real synthetic Qt card
showed 2 images before and 420 after, without changing its two-object count.

`test_right_panel_metadata_contract.py`: **4 failed / 4 passed before**, all eight
pass after. Both real-method render schedules and legacy defaults/types are covered.
Focused adjacent verification: **205 passed, exit 0**, reruns disabled; **462 mirrors
match, exit 0**. The Home source has no plugin mirror. Rollback removes only the
metadata-copy block/docstring change. The running process predates this patch;
fresh source and installed acceptance remain pending. The immutable action envelope,
ordinal/signal migration, semantic signature, scheduling and lifecycle remain separate
steps. Details and retained risks are in the provenance implementation record.

## 2026-09-14: source-run evidence after the Unify prerequisites

**Status: partial live evidence, not full acceptance or permission to retire guards.**
The user-started source session was inspected through 10:26 local time. There were 15
`UX_FIRST_IMAGE_VISIBLE` records, including secondary-study offset keys, and no logged
multi-study rebuild failures. Two UID-mismatched render attempts were rejected; each
was followed by a matching render and visible image in less than 0.5 s. Consequently
the OPT-35 zero-`SKIP` acceptance oracle is NOT satisfied. Keep the identity gates on;
do not interpret successful recovery as proof that the stale-result path is fixed.

The sampled viewer log contained 99 main-thread timer gaps (median 158.3 ms,
p95 480.6 ms using sorted index floor((N-1)*0.95), maximum 3730.7 ms). The two
gaps above 1 s were startup/UI construction, 3730.7 and 1931.2 ms; sampled stacks
included `window.show()` and theme application. These are local UI observations,
not proof of server delay, and are not a matched before/after performance comparison.
One non-terminal `0x8001010d` record occurred; the same main process remained alive
afterward. No access violation was present in this session's native-log portion.

Separate pending findings: 25 `DM-CONVERGE-MISS` events (OPT-04, missing UI rows,
not proof of re-download), one visit-status persistence-false warning (OPT-58), and
one download ERROR classified as priority preemption, not server failure. Download
completeness, offline/cine/unnamed-series coverage and installed-runtime acceptance
are not proven by this run. The detailed evidence and next bounded metadata prerequisite
are in the September 14 sections of the thumbnail/priority provenance document.

## 2026-09-14: OPT-35 shared multi-study projection, compatibility preserved

**Status: extraction implemented and automated-verified; source-live acceptance pending.**
`series_identity.build_multistudy_series_projection` now owns the stable study-slot,
offset-key and per-entry path projection formerly embedded in
`_PWThumbnailsMixin._rebuild_multistudy_series_index`. The controller calls it once and
retains its single-study gate and history/numeric ordering policy. The original inline
implementation was removed. Ingestion normalization, same-study display-key allocation
and immutable `SeriesRef` consumption retain their separate documented responsibilities.

Before changing runtime code, 14 production-method compatibility cases passed for missing
or identical labels, missing-number spellings, reserved-band avoidance, duplicate-number
still/cine series, external exact paths, leading-zero raw labels, later study merges,
repeat rebuilds, history ordering and single-study bypass. They still pass afterward;
an additional pure-input ownership check brings the new file to 15 tests. The final
focused suite is **171 passed, exit 0**. The existing stateful identity test now calls
the production projection instead of its copied implementation; its independent identity
and stable-key assertions pass (150 configured examples, up to 40 steps; **1 passed,
exit 0**). A location-specific source guard was migrated to behavior at the shared seam.
This is a contract-preserving refactor, not a newly reproduced defect or measured speedup.

All **462 mirrors match**; neither changed runtime file has a plugin mirror. No new module,
dependency, configuration, schema, DICOM byte transformation or installed-path requirement.
Rollback restores the controller/helper extraction hunks together. Right-panel action
envelopes, Download Manager routing, render signature and lifecycle remain pending under
OPT-60. Details and source-live matrix:
`docs/plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md`.

## 2026-09-13: OPT-60 Qt thumbnail ownership and patient-close GC pressure

**Status: queued Home-render retirement is code-verified (September 14 receipt above);
full manager lifecycle/disposal remains diagnosed with its guards and fixes pending.
The separate Local identity prerequisite is automated-verified as of 2026-09-14.** Current
source defines no manager-level `cleanup()` or `dispose()`. Real-PySide6 probes corrected the
initial retention hypothesis: a standalone `ThumbnailManager` was collectible while still
connected to `ThemeManager.themeChanged`, and an immediate right-panel manager was collectible
after its cards received `deleteLater()`. Parentlessness and the theme connection therefore do
not prove a deterministic permanent leak. The confirmed strong-retention boundary is the
patient-tab priority callback in `_hp_modules.py`: an outward signal connection targets a lambda
that closes over the patient widget/home owner. A matching Qt probe kept both owner and manager
alive after deferred deletion and collection until that connection was disconnected. Static
delayed callbacks remain a separate bounded-retention/stale-result risk.

Correction (2026-09-14): the misplaced May P1 disconnect in `CircularProgressborder.cleanup()`
accessed a missing callback on a card whose `theme_manager` exists; its outer catch aborted the
remaining cleanup. The card-effect receipt above corrects the earlier absent-attribute claim.
Eleven measured GUI-thread full collections took 149.1–1501.1 ms (median 234.1 ms; latest
306.4 ms). They are deferred by 150 ms, not moved off the GUI thread; moving global collection to
a worker would risk running Qt/VTK finalizers on the wrong thread. The next lifecycle slice must
start with fail-before guards, disconnect the confirmed outward callback, add one idempotent
owner-driven disposal contract, clear back-references/state, and cancel or generation-gate late
callbacks. Re-measure multi-cycle memory, threads, handles, GC, theme switching, and close/reopen.

Separate correctness defects were reproduced and must not be bundled with lifecycle work: the
right panel substitutes its card ordinal for series identity (`Series 4` emitted `0` for drag,
selection, and priority); its legacy click handler depends on an attribute never assigned and a
retired direct-downloader API; the newer priority handler contains an undefined variable after
Download Manager dispatch; and its render signature omits semantic identity/count fields. The
future route is an immutable series action identity into the existing Download Manager/intent
coordinator, while preserving Local hard-offline behavior and the patient-viewer `display_key`
contract. No current crash is attributed to OPT-60 without a matching runtime trace.

The Git-history rationale and guarded migration sequence are recorded in
`docs/plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md`. Preserve the
complementary local/server and immediate/progressive paths; treat the direct-download/right-panel
handler cluster as an incomplete Zeta migration rather than a supported second downloader.

**2026-09-14 implementation, first prerequisite:** corrected
`_HPSearchMixin._build_local_series_thumbnail_payload` so the existing pure
`allocate_series_display_keys` runs for both successful and partial nonempty payloads.
Previously it ran only in the exception handler; failures before the import also raised
`UnboundLocalError`. Empty results now return without referencing an unbound allocator.
No new I/O, thread, decoder, storage rule, schema, flag or dependency was introduced.
`test_home_local_thumbnail_projection.py` executes the real method with isolated synthetic
I/O: three failures before the fix (missing keys twice, unbound allocator once), two existing
behaviors passing; all five pass afterward. The focused Local, patient-study-set, collision,
SeriesRef and thumbnail suite is **120 passed, exit 0**; all **462 mirrors match, exit 0**.
The changed Home mixin has no plugin mirror. No performance speedup is claimed.
Rollback consists of the three added lines in that method; no data migration is needed.
Source live and installed-build validation remain pending. Right-panel ordinal/action
routing, semantic refresh, download completion and lifecycle work remain separate pending
slices; study-local display keys must never be promoted to patient-global identity.

## 2026-09-12: OPT-59 Viewer Configuration storage cleanup

**Status: fixed and automated-verified; source live gate pending.** The storage panel's
recursive size walk, destructive cleanup, preview, consistency operation, drive probing,
and Qt worker lifecycle were treated as one ownership boundary. Single-pass `os.scandir`
reduced the same full managed-storage scan from more than 90 seconds to 2.915 seconds
(warm cache 0.006 ms). Deletion now fails closed on path escape or file-removal failure,
uses Imported On as the primary retention date, preserves undatable patients, and refuses
to race active imports, downloads, or viewer tabs. Worker results are marshalled to the GUI
thread and process-owned jobs survive transient panel destruction; shutdown waits for a
consistent boundary. The focused storage/GUI suite passes 59 tests and adjacent settings /
download-state suites pass 18, all with exit code 0. Rollback is the complete OPT-59 slice;
do not reconnect the dormant legacy patient cleanup manager. Full evidence and live checklist:
`docs/reports/STORAGE_CLEANUP_SAFETY_AND_PERFORMANCE_2026-09-12.md`.

## 2026-09-08: OPT-55 spatial diagnosis input experiment

Implemented the independent spatial-packet benchmark utility with complete native
groups, physical slice order/spacing, crop-adjusted LPS geometry and bidirectional
plane locators. Seven synthetic guards pass. The private matched evaluation uses
the existing authorized Gemini company route, all five target levels and repeated
requests; the report distinguishes input correctness from diagnostic agreement.
The latest ordinary source run completed transport but did not resolve critical
diagnostic disagreement. It therefore clears the earlier transport verification
pending item, not the clinical validation item. No default runtime adoption or
installed-build change is claimed. Continue under OPT-55; see
`docs/reports/EAGLE_EYE_SPATIAL_PACKET_EXPERIMENT_2026-09-08.md`.


## 2026-09-08: OPT-55 Gemini company profile follow-up

Pipeline 8.6.0 / atomic 2.7.0 uses the live-listed, synthetically tested
`gemini-3.1-pro-preview` company endpoint throughout lumbar analysis. Atomic
factories inherit temperature 1.0 instead of forcing zero; global model pins
resolve at call time. Five fail-before guards pass; the affected boundary
passes 146 tests. Multi-image probes succeed while the tested strict-schema
path fails, so local JSON validation remains authoritative. All 462 mirrors
match. Source/transport verification is complete; restarted source-run and
clinical validation remain pending. This extends OPT-55 rather than introducing
a new optimization plan. Details and scoped rollback:
`docs/reports/EAGLE_EYE_GEMINI_COMPANY_ROUTE_2026-09-08.md`.


**Status:** CANONICAL — this is the single source of truth for optimization, stability, reliability,
and performance work. Every future optimization task extends this document rather than starting a new
disconnected plan.
**Created:** 2026-07-03 (consolidates ~1 month of fragmented optimization work)
**Owner discipline:** code is the source of truth for *implementation status*; docs describe *intent*;
logs/KPIs show *runtime behavior*. All three are reconciled here.

> **UPDATE 2026-08-31 — OPT-56 resident Advanced Analysis implemented and synthetically verified.**
> A background startup coordinator now warms the optional custom Slicer viewer while
> keeping it hidden. User launch reuses the same process; a separate headless Slicer
> handles immutable AI snapshots and the existing offline model. Real readiness,
> authenticated local commands, exact-series selection and session-owned Windows jobs
> replace import-only warmup and process-name cleanup. The full synthetic probe measured
> 4.385 s cold / 0.471 s warm show, exact threshold output, and a 55.600 s headless CPU
> model run. This is not a full-workstation or clinical speed/accuracy acceptance.
> Source integration and focused guards are complete; the user subsequently confirmed
> source launch and responsiveness. Customer hardware/offline and release gates remain open. See
> [the runtime guide](modules/ADVANCED_ANALYSIS_RESIDENT_RUNTIME.md) for evidence and limits.

> **OPT-56 live follow-up, 2026-08-31:** source-session logs confirmed hidden viewer
> readiness (26.608 s), but a deleted sidebar `QPushButton` in `ButtonSafeguard`
> aborted the explicit Advanced MPR click before dispatch and left the operation
> flag set. The core safeguard now prunes stale wrappers and checks Qt validity
> during registration/start/completion. Five behavioral cases failed before the
> fix; the focused lifecycle/resident/builder gate now passes 52 tests (exit 0),
> and 462 mirror pairs match. Slicer/AI visibility policy is unchanged. Normal
> source retesting subsequently confirmed window launch; see the runtime guide's
> live-launch follow-up and separate modal repair for the final functional status.

> **OPT-56 second live follow-up, 2026-08-31:** the visible viewer opened, but a
> hidden owned window blocked input. The warmup guard suppressed every top-level
> widget while promotion restored only the main window. Restore only guard-owned
> offscreen attributes across live widgets, map active dialogs without dismissing
> them, and remove the viewer event filter. Three real-Qt guards failed before
> repair; the combined launch/lifecycle/builder gate passes 70 tests (exit 0),
> with 462 synchronized mirror pairs. Separate headless analysis is unchanged.
> The user subsequently confirmed that the source viewer works. This closes the
> reported UI defects for that run; model accuracy, broader extension/hardware
> qualification and release gates remain open. See the runtime guide for evidence.

> **OPT-56 model-readiness follow-up, 2026-08-31:** during the assistant-directed
> local MR trial, the portable worker remained in full bundle verification for
> more than seven minutes before creating its engine-state marker; process read
> counters continued advancing. This is a preparation delay, not measured model
> inference time. The earlier synthetic timings do not predict this run's latency.
> Viewer warmup does not warm or retain the portable model. Preserve the integrity
> gate; separately measure verification, imports, weight loading and computation
> before choosing a model-readiness optimization. See the offline lumbar guide for
> the trial route and outcome; customer performance acceptance remains open.

> **UPDATE 2026-07-05 — optimization release SHIPPED (deploy gate PASSED).** The #1 performance target
> — main-thread blocking *during use* — is **RESOLVED and live-verified**: during-use main-thread stalls
> went from the 725 ms baseline (48 s worst-case on the reporting PC) to **0 this release run**, and the
> disk-walk / status-refresh functions are **absent from every stall trace**. Shipped + verified:
> **OPT-01** (status disk-walk TTL cache + refresh-trim, off the GUI thread), **OPT-12** (startup
> single-instance sweep — psutil name-reuse; `:446` stall gone), **OPT-09** (download telemetry log
> hygiene), plus the **multi-study wrong-series clinical fix** (viewport study-identity gate +
> per-series `study_uid`/`series_uid` stamp + primary poison-guard; live-verified on 2 PCs, gate ran with
> 0 wrong-study stomps). **OPT-11:** 7 validated flags collapsed to unconditional (4 non-clinical + 3
> clinical wrong-series). Deploy gate PASSED with owner clinical sign-off — record
> `docs/reports/deploy-record-workstation-2026-07-05.md`. **Still default-OFF pending a live-validation run** (do NOT
> assume active): `AIPACS_FAST_INSTANCE_SWEEP` (safety-critical startup ppid snapshot),
> `AIPACS_STATUS_EXPENSIVE_TTL`, and `AIPACS_LOG_TELEMETRY_DOWNGRADE` effect unconfirmed. **Remaining for
> a future phase:** OPT-04 lifecycle cutover; promote the two default-off flags after validation.
> Per-fix evidence in §15; backlog states in §9.

> **UPDATE 2026-07-06 — OPT-20 "previous-exam series won't display" RESOLVED + shipped default-on; more
> items verified.** The long-running "a previous-exam X-ray/document doesn't render" bug (patients 48456,
> 45289, and the 48912/multi-study family) is **fixed and live-verified**. TRUE root cause: an
> async-apply **render-gate type mismatch** — `_apply_loaded_series_data` (`_vc_load.py`) gated the render
> on `current_idx == series_idx`, comparing a **series NUMBER** (`last_series_show`) to a **list INDEX**
> (`replace_series_data` return). Offset-key previous-exam series (e.g. `2000001`) can never match a small
> index, so the render was always skipped and `_start_qt_viewer` never ran (metadata was fine —
> `[FAST-YIELD-TRACE] will_yield=True`). Fix (`AIPACS_APPLY_RENDER_TARGET_VIEWER`, promoted **default-on**
> after 45289: `[apply-path] target_fix_render=29` renders that the buggy gate would have skipped;
> previous-exam DX/documents now display). Instrumentation kept behind `AIPACS_APPLY_TRACE` (default-off).
> **Honesty note:** this took THREE wrong root-cause calls (contention/OPT-04, then a stale-token "race" +
> a render-convergence retry, then even the right file/wrong line) before per-hop apply instrumentation
> made it undeniable — the "66 display-misses" metric was ALSO false (benign spinner clears). Contention
> (OPT-04) is NOT behind the previous-exam display bug. Also this window: **OPT-09/12/18 VERIFIED-COMPLETE**
> (live), **OPT-06** grow-lane study-scoped bind shipped (mechanism-verified-safe, default-off),
> **OPT-17** cache study-identity shipped. Remaining OPT-20 residuals (rare, P2): a lost worker→UI apply
> post, and a rare empty metadata build. Evidence in §15; backlog in §9.

> **UPDATE 2026-07-07 — OPT-20 slot-3 residual ROOT-CAUSED + fixed default-on (multi-study display-miss).**
> The 49317 residual where distinct SECONDARY-study series (`3000001`/`3000002`) never displayed while
> slot-2 (`2000001`) did is now a **deterministic, static-analysis root cause** (not the token race — ruled
> out: `[APPLY-STALE-EARLY]=0` and same-UI-thread ⇒ token current at both gates). Cause:
> `add_new_data_to_lst_thumbnails_data` (`_pw_metadata.py`) had a **study-blind name+count dedup** — a series
> sharing a `series_name` **and** instance count with an already-present series hit `return False` and was
> **never appended**, even when its `series_number` was DIFFERENT. For a multi-study / previous-exam patient
> two studies routinely share a name (scout/localizer/DX/same-protocol repeat), so the distinct secondary
> series was dropped → `replace_series_data` returned **-1** → the async apply render loop was gated off
> (`series_idx < 0`, no `[APPLY-GATE]`) → the series never displayed. Fix (`AIPACS_SERIES_APPEND_STUDY_DISTINCT`,
> **default on**; `=0` = byte-identical legacy): only skip as a TRUE duplicate when the incoming
> `series_number` is already present; a distinct, not-yet-present number is appended (same end-append the
> different-count pairing path already used — no ordering change for any working case). **Isolation
> untouched** — each series keeps its own offset number + stamped `study_uid`/`series_uid`, and the
> viewport identity gate (fail-closed on `series_uid`) still blocks any cross-exam paint. Verified against
> the REAL method (8/8 headless checks incl. `replace_series_data` now returns ≥0). Residual `1100000`
> (DICOMized document, `[APPLY-ENTER]=0`) is a distinct path = **OPT-07** document handling, not this gate.
> Evidence in §15; backlog in §9. **NEEDS live source-build verify on 49317** (drag every series of both
> studies → all display; 0 `[IDENTITY-GATE] SKIP`).

> **Reading order for a new agent:** §1 (how to use) → §4 (current architecture) → §6 (reconciliation
> matrix) → §9 (backlog) → §10 (next safe phase). Then, only if you touch a pipeline, the linked
> subsystem doc.

---

> **UPDATE 2026-07-14 — REASSESSMENT. Both of the plan's founding diagnoses are now known to be
> WRONG or incomplete, and the real defect classes have names.** This supersedes §2's TL;DR.
>
> **(1) The #1 reliability defect is NOT "completion-by-notification-not-convergence" (OPT-04).**
> That was the 07-02 hypothesis and it was never confirmed. Every "series won't display" bug since
> has been **deterministic and structural**, not a dropped notification: OPT-20 (an async-apply gate
> comparing a series NUMBER to a list INDEX), OPT-20/slot-3 (a study-blind name+count dedup that
> never appended the series), OPT-26/49836 (a secondary load repointing the TAB's `import_folder_path`),
> 50238 (a primary load inheriting the SECONDARY study's `study_pk` from mutable tab state).
> **The real class: series identity was RE-DERIVED at four stages from MUTABLE TAB STATE**, so any
> multi-study patient whose studies share series NUMBERS found a stage where the derivations
> disagreed — and each time we added a guard, until **nine flags were answering one question**.
> **OPT-35** is the structural answer (resolve an immutable `SeriesRef` ONCE, thread it, retire the
> guards). P0/P1/P2 shipped default-on 2026-07-14; the shadow oracle came back **clean on two live
> patients** (0 mismatches), which is the green light for P3–P5. OPT-04 is **not dead but
> DOWNGRADED**: its remaining real scope is DM completion convergence (the 216× `not in
> download_rows` re-download loop), not the display family.
> **2026-08-30 imported-series follow-up:** the same identity rule now protects
> Local import count persistence: duplicate raw `SeriesNumber` rows are updated
> by `SeriesInstanceUID`, while a header-boundary pixel gate prevents SR/vendor
> metadata objects from entering the image viewer. Local folder inspection runs
> on the existing worker path and stops at the pixel tag, so no cine decode or
> large Pixel Data read was added to patient open.
>
> **(2) The #1 performance defect ("main-thread blocking") was correctly identified but is a
> RECURRING CLASS, not a fixed list of hotspots.** The 07-03 hotspots (OPT-01/09/12) are resolved and
> live-verified — and then **three NEW multi-second GUI-thread freezes appeared from unrelated
> subsystems**: OPT-22 (web-browser Chromium prewarm, **21 s**), OPT-23 (EchoMind inline dispatch),
> OPT-27 (Eagle Eye training-settings scan walking 53 k DICOM files, **55 s → 1.4 s**). None came from
> the pipeline this plan was written about. ⇒ **"No blocking I/O, folder walk, DICOM read, network
> call, or engine construction on the GUI thread" is now a STANDING RULE for every new feature**
> (§12.3), not a backlog item to be closed.
>
> **(3) The most useful new diagnostic heuristic — "the mechanism exists but a coarse guard is
> suppressing it."** THREE of this session's four defects were NOT missing machinery; the machinery
> existed, was correct, and was **suppressed**: OPT-36 (the awaiting/loading-spinner machinery worked;
> the resume watchdog's settle condition declared a viewport "settled" that had never shown the
> awaited series, and hid the spinner with a FAKE `ViewportLoadSucceeded`); OPT-37 (thumbnail refresh
> worked — a detected change already re-renders with `force_server_merge=True`; a flat **5-minute**
> per-study TTL throttled the *change detector* for exactly the window in which a study grows);
> OPT-35 (the canonical identity resolver existed — its result was simply discarded). **Before adding
> a mechanism, check whether the existing one is being gated off.** Corollary, from OPT-36: **a "stop
> the loop" signal must never double as "the operation succeeded."**
>
> **(4) Flag debt is now a first-class risk.** Nine flags for one question (OPT-35) was the symptom
> that forced this reassessment. §10/N-4 makes flag retirement a scheduled workstream with an
> evidence gate, not a someday.
>
> **Shipped this window (all default-on, all with kill switches, all NEEDING live verify):** OPT-24
> (DM outage re-arm), OPT-25 (missing `SeriesNumber` killed a whole study), OPT-26, OPT-27, OPT-28
> (stale pooled socket — the connectivity root cause), OPT-29 (patient-table `clear_table` native
> crash), OPT-30 (Sync Status reporting a false success), OPT-31, OPT-33, OPT-35 P0/P1/P2, OPT-36,
> OPT-37. Evidence per item in §15; states in §9; the next phase is **§10, rewritten**.

## 1. Purpose & the one non-negotiable rule

Over the last month the same three themes — **reliability, stability, performance** — were worked
repeatedly across many documents, code changes, and partially-finished implementation phases. The
knowledge fragmented. This document reconciles all of it into one backlog with one status per problem.

**The critical rule going forward:** do **not** create another independent optimization plan. When a
new optimization idea appears, first locate it in the backlog (§9). If it is already tracked, update
that item. If it is genuinely new, add a new backlog ID here. Never fork a parallel plan.

**Architecture guardrails that outrank every optimization** (from `CLAUDE.md`; unchanged, every phase):

- FAST viewer never instantiates VTK render windows.
- Never remove viewer features: overlays, metadata, measurements, sync, reference lines, sidebars,
  patient/thumbnail workflows.
- Keep the three execution domains separated: **Fast** (`pydicom_qt`), **Advanced** (`vtk_simpleitk`),
  **VTK modules** (MPR / Dental / Analysis). Unify only through the read-only trunk.
- Preserve cross-patient isolation and single-study-vs-multi-study gating.
- Never write the live `dicom.db`; atomic `.part` → `os.replace`; resume rejects partials.
- Minimal safe edits, flag-gated with a kill switch, verify-lane test + fresh-log review after each phase.

---

## 2. TL;DR — where we were on 2026-07-03 *(HISTORICAL — superseded by the 2026-07-14 reassessment above)*

> ⚠️ **Read the 2026-07-14 UPDATE block first.** Point 2 below ("the reliability failures are ONE
> architectural defect: completion-by-notification") is the founding hypothesis of this plan and it
> did **not** survive contact with the evidence — every display failure since has been a distinct,
> deterministic, structural bug (see OPT-20/26/35/36). Point 1 (main-thread blocking) was right about
> the *hotspots* but wrong about the *shape*: it is a recurring class that new features keep
> re-introducing, not a finite list. Kept verbatim below as the historical record of what we believed
> and why — deleting it would hide the two most instructive wrong calls in this project.

1. **The performance bottleneck was mis-identified for months and is now correctly known.** Decode and
   render are **healthy** (decode p50 ≈ 4.5 ms, TTFI p50 ≈ 19 ms). The real #1 issue is **main-thread
   blocking** on the download-status refresh + filesystem manifest scan path, which starves every
   async fetch and grow event.

2. **The reliability failures (blank thumbnails, previous-exam won't grow, 80/20 flakiness) are ONE
   architectural defect, not three bugs:** completion is defined by *notification arrival*, not *state
   convergence*. Dropped notifications leave a study partial until a manual reopen.

3. **A canonical fix has been designed and partially shipped.** The pure lifecycle core
   (`patient_load_lifecycle.py`, 15 tests green) + shadow telemetry + **Seam A/B cutovers** shipped
   **default-on** in the 2026-07-03 build with kill switches. They are **safe-by-construction and
   unit-tested but NOT yet live-verified on the reporting workstation** — that verification is the
   explicit purpose of that build.

4. **Phase-1 main-thread fixes shipped** (async thumbnail save, chunked status refresh, chunked sidebar
   build). The *broad* off-GUI-thread move (the amplifier) and the full lifecycle cutover remain the
   two biggest open items.

**The single most valuable next action:** live-verify the shipped Seam A/B cutovers and the P1 fixes on
the reporting PC with fresh logs, *before* writing any more code. If they hold, collapse their flags and
proceed to the off-thread convergence sweep (Stage 2). See §10.

---

## 3. Historical work summary & document inventory (Deliverable 1)

Roughly 240 markdown files touch performance/stability/reliability across `docs/`. They cluster into
generations. The table lists the **canonical** documents a consolidation must build on; the many
per-fix reports are folded into the backlog (§9) and remain as historical evidence.

### 3.1 The anchor documents (read these; they supersede the rest)

| Doc | Date | Role | Status of its content |
|---|---|---|---|
| `docs/reports/PATIENT_LOADING_PIPELINE_RELIABILITY_REVIEW_2026-07-02.md` | 07-02 | **Root-cause bible.** Proves the single "completion ≠ convergence" defect; designs the Study Load Lifecycle. | Phase-1 core built + green; Seams A/B shipped 07-03 (unverified). **Supersedes all prior thumbnail/grow patch docs as the explanation.** |
| `docs/plans/UNIFIED_STABILIZATION_OPTIMIZATION_PLAN_2026-07-01.md` | 07-01 | **Phased execution plan** across stability/perf/maintainability. | Phase 0 + P1.1–P1.3 DONE; P1.4 assessed; Phases 2–4 open. |
| `docs/reports/KPI_SESSION_REVIEW_2026-07-01.md` | 07-01 | **KPI baseline + bottleneck proof** (Conference-Loop, live logs). | Read-only finding. Establishes decode/render healthy, main-thread blocking = #1. Authoritative baseline. |
| `docs/reports/deploy-record-workstation-2026-07-03.md` | 07-03 | **As-shipped record** of the lifecycle build. | Gate PASSED with informed override; live-verify pending. |
| `docs/reference/AIPACS_FLAG_REGISTRY_2026-07-01.md` | 07-01 | **Flag audit** (62 `AIPACS_*` flags; doc-vs-code divergences). | Seed for the Phase-4 central registry. |
| `docs/plans/VIEWER_GEOMETRY_HARDENING_MASTER_PLAN_2026-06-14.md` | 06-14 | Geometry correctness/latency (T1/T2/T3). | T1 shipped; T2/T3 staged (golden-compare gate). |

### 3.2 Supporting / superseded generations (historical evidence, folded into §9)

- **FAST viewer stabilization (2026-05-08 → 05-13):** `FAST_VIEWER_STABILIZATION`, `FAST_VIEWER_REGRESSION_GUARDS`, `FAST_GROW_BATCHING_HARDENING`, `FAST_RENDER_CLOCK_PRODUCTION_HARDENING`. Mostly **shipped**; their guards live in `tests/code/viewer/`.
- **Responsive-UI generation (2026-05-26):** `RESPONSIVE_UI_ROOT_CAUSE`, `_SCALING_PLAN(+REVIEW)`, `_STRUCTURAL_PATTERN`, `_TEST_CRITERIA`. Partly shipped; the main-thread findings are **superseded** by the sharper 07-01 KPI review.
- **ClearCanvas KPI benchmark set (2026-04-20 → 05):** `docs/plans/clear-canvas/*`, `docs/analysis/CLEARCANVAS_KPI_MAPPING`. Origin of the KPI catalog; **superseded** by `FAST_VIEWER_KPI_CATALOG.md` + `CURRENT_KPIS_v2.3.6.md`.
- **MPR open-freeze (2026-06-27):** `docs/plans/performance/MPR_OPEN_FREEZE_OPTIMIZATION_PLAN_2026-06-27.md`. L1 deferred-3D shipped default-on; L2 progressive-2D + off-thread volume build **staged**.
- **Zeta Download Manager review (2026-05-24):** `docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN`. Most fixes shipped; residual steps test-gated.
- **Per-fix reliability reports (2026-06):** drag-drop thrash, viewport loading lifecycle, canonical-disk-complete, resume-settle, grow-displayed-to-disk, multi-study identity/grouping review. All **shipped default-on**; their behaviors are the ones the lifecycle refactor will *absorb into one authority*.
- **Standards:** `docs/performance/FAST_VIEWER_KPI_CATALOG.md`, `docs/plans/performance/CURRENT_KPIS_v2.3.6.md` — the KPI source of truth (§13).
- **Tooling:** `tools/performance/kpi_session_report.py` + `kpi_targets.py` (read-only session analyzer, Phase 0), `stall_correlation_report.py`.

---

## 4. Current architecture map (Deliverable 3)

### 4.1 Patient-load pipeline, as actually built

```
                    ┌─────────────────────────────────────────────┐
   user click ──▶   │ HOME PANEL  (_hp_search / _hp_series /       │
                    │             _hp_patient_open / _hp_modules)  │
                    │  • debounced single vs double click          │
                    │  • right-panel thumbnail fetch (asyncio)     │  ← Seam A wired here
                    │  • study-set resolution + download enqueue   │    (lifecycle shadow + cutover)
                    └───────┬─────────────────────┬────────────────┘
                            │ (Qt signals)        │ (add_downloads)
                            ▼                     ▼
        ┌───────────────────────────┐   ┌──────────────────────────────┐
        │ DOWNLOAD MANAGER (zeta)   │   │ PATIENT TAB / VIEWER          │
        │  • subprocess + sockets   │   │  • thumbnail sidebar          │
        │  • per-series progress    │   │  • progressive grow           │
        │  • writes .dcm to disk    │   │  • viewport population        │
        └───────────┬───────────────┘   └───────────────┬──────────────┘
                    │  on_series_progress/completed      │  awaiting/grow
                    └────────► home_download_service ◄────┘  ← Seam B wired here
                              (DM → widget BRIDGE, keyed to ONE study_uid)   ← Seam C tap in _vc_progressive
```

**The structural defect visible in the diagram:** the DM→viewer bridge is keyed to one primary
`study_uid`; the home-panel fetch is a cancellable fire-and-forget task; neither owns a durable "this
study reached displayed-complete" contract. Every subsystem *hopes* its signal lands. There is **no
stage that asserts the study is displayed-complete** — the pipeline runs out of events.

### 4.2 The eight stages and where each can silently stop

| # | Stage | Owner today | Completion signal | Silent-stop risk |
|---|---|---|---|---|
| 1 | Click disambiguation | `patient_table_widget`, `_hp_series` | timer fires | debounce dropped under load |
| 2 | Study-set resolution | `_hp_patient_open`, `patient_study_set` | function returns | mostly deterministic |
| 3 | Right-panel thumbnail fetch | `show_patient_studies` (`_hp_search`) | `right_panel_display_done` | **≥9 early returns; 3 silent drops** |
| 4 | Series discovery / metadata | `_get_or_fetch_series_info` | dict returned | stale-token discard |
| 5 | Download (per series) | Zeta DM subprocess | `on_series_completed` | subprocess spawn crash; response desync |
| 6 | DM→viewer progress bridge | `home_download_service` | `series_images_progress.emit` | **secondary-study key → `sn=None` → dropped** |
| 7 | Progressive grow / populate | `_vc_progressive` | `DISPLAYED_COMPLETE` (implicit) | grow event never arrives → timer backstop |
| 8 | Backstop reconcile | `_dl_watchdog_tick` (GUI-thread QTimer) | resume/grow | starved by GUI stalls; self-stops if `awaiting` cleared early |

### 4.3 The three execution domains (must stay separate)

Fast (`pydicom_qt`, 2D, no VTK render windows) · Advanced (`vtk_simpleitk`) · VTK modules (MPR, Dental
Curve MPR, Advanced Analysis, Orthogonal MPR). Each owns its own decode/cache/render/lifecycle/state.
The lifecycle controller (§5, when built) lives in the **read-only trunk** and only *calls* each
domain — it never couples them.

---

## 5. Per-pipeline current state (Deliverable 3, A–H)

### A. Application startup
**State:** the two largest one-time freezes are `add_AIPacs_tab` building the whole
`ControlPanelInterface` (AIPacs + EchoMind) synchronously (~1.4 s) plus theme `apply_modern_style`
(~2.5 s). **Assessed, not optimized** (P1.4). Lower during-use value (one-time at launch, not during
reading), higher risk (tab presence, `control_panel` deps, EchoMind init). Recommendation: defer
EchoMind CommandBus registration specifically, not the whole tab. → backlog **OPT-12**.

### B. Patient opening
**State:** works ~80% of the time; ~20% leaves a study partial until reopen — the machine-dependent
flakiness. Fully mapped in §4. The pure lifecycle model exists; Seam A (thumbnail token-stale render)
shipped default-on but unverified. The full deterministic cutover is **not** done. → **OPT-02, OPT-04**.

### C. Thumbnail pipeline
**State below the socket = reliable** (`socket_done = display_input = display_done`, 72=72=72). The loss
is entirely upstream: a fetch is cancelled (`CancelledError` bypasses `except Exception` → 29
unaccounted starts) or discarded on a stale token (18). "Only the first thumbnail" = a *partial* cache
set renders first, and the full-set fetch that would replace it is the one dropped, with **no
reconciliation back to the full set**. Canonical disk path + memory-first store are sound
(`docs/pipelines/thumbnail-pipeline.md`). → **OPT-02** (Seam A) and **OPT-04** (render-from-model).

### D. Current exam vs Previous Exam loading
**State:** they use **different event paths** — this is the core "works here / fails there." A previous
exam is a *different* `study_uid`; the DM→viewer bridge is keyed to the primary `study_uid`, so
secondary-study progress arrives with `uid != study_uid` and is dropped (`sn=None`, 200
`GROW-LANE-TRACE resolved=None`). The first image shows; the rest download to disk unseen; a **second
drag** re-registers awaiting after files are on disk and reads the complete set. Seam B (watchdog
keep-alive) shipped default-on but unverified; the real fix is re-keying the bridge by canonical
identity. → **OPT-03** (Seam B verify), **OPT-04/OPT-06** (canonical-identity DM adapter).

### E. Drag and drop
**State:** folded into the unified view-intent pipeline (first-image prime, view-intent coalescing,
complete-on-disk skip, disk-ready resume). Multiple historically-competing paths were consolidated onto
`_coalesce_dm_view_intent` + the shared authority. Remaining risk is the same secondary-study grow gap
(D) and the GUI-thread amplifier widening the drop→grow race. Drag KPIs still FAIL at the tail (§13). →
**OPT-01, OPT-04**.

### F. Cache architecture
**State:** disk is the single source of truth (canonical `SOURCE_PATH/<study_uid>/<orig_series>` +
`THUMBNAIL_PATH/<study_uid>/<series>.png`), atomic writes, resume rejects partials. The competing
*state* is not on disk but in **notifications vs memory flags** (`_thumbnail_fetch_token`,
`_awaiting_series_number`, primary-bound bridge) that can disagree with disk. The lifecycle model makes
disk authoritative for existence and reduces the in-memory gates to one identity-keyed model. Server
`expected` count (never disk-derived) stays the completeness authority. → **OPT-04**.

### G. Decode and rendering
**State: HEALTHY — do not optimize.** decode p50 ≈ 4.5 ms, TTFI p50 ≈ 19 ms, frame ≈ 16 ms, scroll fast.
Multi-frame/cine decode implemented (needs live verify, **OPT-13**). The pipeline below the socket and
the DICOM/decode/geometry layers are proven sound and must not be touched by reliability work.

### H. UI thread and responsiveness
**State: the #1 problem.** Synchronous disk I/O (manifest `Path.iterdir()` walk) + per-study DB status
checks run **on the GUI thread** during DM/patient-table refresh. 63 stalls >100 ms in 20 min (07-01
local); 10,105 stalls, max 48 s, on the reporting PC. P1.1–P1.3 removed the thumbnail-save, status-
refresh, and sidebar-build stalls; the manifest scan, DM table rebuild, GC pauses, and subprocess spawn
remain. → **OPT-01** (the amplifier).

---

## 6. Document ↔ code reconciliation matrix (Deliverable 2)

Each row is a distinct optimization/reliability concern, classified by the required states. **Code is
authoritative for status.**

| Concern | Planned in | Code reality (2026-07-03) | Class |
|---|---|---|---|
| Async thumbnail disk save off GUI thread | UNIFIED P1.1 | `AIPACS_THUMB_SAVE_ASYNC` default-on, in code, live-verified | **COMPLETED** |
| Chunked DM status refresh | UNIFIED P1.2 | `AIPACS_STATUS_REFRESH_CHUNKED` default-on, in code, offscreen-verified | **COMPLETED** |
| Chunked single-study sidebar build | UNIFIED P1.3 | `AIPACS_SIDEBAR_BUILD_CHUNKED` default-on, in code, visual-verified | **COMPLETED** |
| KPI session analyzer + flag registry | UNIFIED P0 | `tools/performance/kpi_session_report.py` + `kpi_targets.py` + registry doc exist | **COMPLETED** |
| Lifecycle pure core (identity model + reconcile) | RELIABILITY §6, §10 | `PacsClient/utils/patient_load_lifecycle.py`, 15 tests green, additive | **COMPLETED (core only)** |
| Lifecycle shadow telemetry | RELIABILITY §7.1 | `lifecycle_shadow.py`, `AIPACS_LIFECYCLE_THUMBS` default-on | **COMPLETED (telemetry)** |
| Seam A: thumbnail token-stale render from model | deploy 07-03 | `_hp_search.py`, `AIPACS_LIFECYCLE_THUMBS_ACTIVE` default-on | **IMPLEMENTED — UNVERIFIED (live)** |
| Seam B: previous-exam grow watchdog keep-alive | deploy 07-03 | `home_download_service.py`, `AIPACS_LIFECYCLE_GROW_ACTIVE` default-on | **IMPLEMENTED — UNVERIFIED (live)** |
| Retry-exhausted → FAILED terminal tap | deploy 07-03 | `series_intent_coordinator.py` (+mirror) | **IMPLEMENTED — UNVERIFIED (live)** |
| Main-thread blocking — manifest scan / DM rebuild / GC off thread | KPI review §3; RELIABILITY §7.3 | NOT started (beyond P1.1–P1.3) | **PARTIAL / NOT STARTED** |
| Full Stage-1 cutover (render-from-model; DM re-key; convergence sweep off-GUI replaces watchdog) | RELIABILITY §7.2 | Shadow only; cutover not done | **DEFERRED (staged, high-risk)** |
| Startup `add_AIPacs_tab` / EchoMind init defer | UNIFIED P1.4 | Assessed only | **DEFERRED** |
| Multi-study A2 live secondary progress bridge | MULTISTUDY 06-30 | Watchdog-grow shipped; live bridge not | **PARTIAL (subsumed by OPT-04)** |
| Multi-study B1 Series 100000 (DICOMized doc) offset-key | MULTISTUDY 06-30 | Not resolved | **NOT STARTED** |
| Dental VTK-MPR geometry parity default | UNIFIED 1b; registry | Code default **OFF**; `CLAUDE.md` says ON | **REGRESSED / DOC-DIVERGENCE** |
| Geometry hardening T1 (IPP-spacing invariant) | GEOMETRY 06-14 | Shipped + guard test | **COMPLETED** |
| Geometry T2/T3 (persist spacing/photometric; DB metadata path ~1424 ms) | GEOMETRY 06-14 | Staged; needs golden-compare | **DEFERRED (high-risk)** |
| MPR open-freeze L1 deferred-3D | MPR 06-27 | Shipped default-on | **COMPLETED** |
| MPR open-freeze L2 progressive-2D / off-thread volume | MPR 06-27 | Design-only | **DEFERRED** |
| Cine / multi-frame decode + playback | DICOM_COMPLEX 07-01 | Implemented default-on | **IMPLEMENTED — UNVERIFIED (live)** |
| Download subprocess spawn access violation | RELIABILITY §7.4 | Tracked; not fixed | **REGRESSION / NOT STARTED** |
| Log hygiene (WARNING telemetry; 13 MB record; mismatch spam) | UNIFIED P3.2; KPI §4 | Not done | **NOT STARTED (low-risk)** |
| Flag collapse (verified default-on kill switches) | UNIFIED P4.1 | `AIPACS_DISK_COUNT_CANONICAL` collapsed (template); rest pending | **PARTIAL** |
| CLAUDE.md reconciliation (retired flags) | UNIFIED P4.3 | Not done | **NOT STARTED (low-risk)** |
| CPU/GPU runtime sampling | KPI §4 | Instrumentation gap | **NEEDS INSTRUMENTATION** |
| EchoMind prompt safety | UNIFIED P4.2 | Audit, unfixed | **NOT STARTED (out of core perf scope)** |

**Duplicated concerns merged:** "previous-exam won't grow," "canonical-disk-complete," "resume-settle,"
"grow-displayed-to-disk," and "A2 live bridge" are **one problem** (secondary-study completion by
convergence). They are consolidated into **OPT-04**; the individual shipped fixes are the *interim
compensations* the lifecycle authority will absorb and let us delete.

---

## 7. Completed & verified optimizations (Deliverable 4) — do not re-touch

- **Main-thread P1.1/P1.2/P1.3** — async thumbnail save, chunked status refresh, chunked sidebar build
  (all default-on, verified). `save_thumbnail`, `refresh_download_statuses`, `build_local_manifest`,
  `_pw_thumbnails`, `_pw_panels` all absent from stall traces after the fix.
- **KPI Phase 0** — read-only session analyzer + thresholds table + flag registry.
- **Multi-study Stage A1** — canonical on-disk count for offset display keys (flag collapsed to
  unconditional) + A1 watchdog `force_reload=True`. Live-verified on patient 48695.
- **Geometry hardening T1** — IPP-spacing invariant guard.
- **DM dedup** (phantom count inflation) — user-confirmed.
- **FAST viewer stabilization + grow batching + render-clock hardening** (May) — guards in place.
- **MPR open-freeze L1** deferred-3D; **Curved/Dental MPR safety** (teardown/UAF, deleted-object swallow,
  2D-mouse, WL inherit, robust WL, panoramic quality, FAST→VTK pick, in-place result).
- **MPR annotation** slice-binding + viewport-scoped targeting + click-to-activate.
- **Single-instance takeover, attachment local-first, voice keep-on-close, import-opens-FAST,
  drag-drop view-intent coalescing / first-image prime / complete-on-disk skip** — shipped.

---

## 8. Partially completed / implemented-but-unverified (Deliverable 5)

| Item | What's done | What's missing |
|---|---|---|
| **Lifecycle refactor** | Pure core + shadow + Seam A/B cutovers + failure tap, all default-on | Live source-build verification; full cutover (render-from-model, DM re-key, off-GUI convergence sweep) |
| **Main-thread de-blocking** | P1.1–P1.3 (three stall sources removed) | Manifest scan, DM table rebuild, GC pause, subprocess spawn still on GUI thread; startup (P1.4) |
| **Multi-study secondary completion** | A1 (post-settle grow), watchdog keep-alive | Grow *during* download (live secondary bridge, A2); B1 Series-100000 doc |
| **Geometry** | T1 invariant | T2 (persist spacing/photometric), T3 (DB metadata path for ~1424 ms) — golden-compare gated |
| **Cine / multi-frame** | Decode + playback default-on | Live verify with real cine/US/XA data |
| **Flag collapse** | 1 flag collapsed (template) | ~40+ verified default-on kill switches remain |

---

## 9. Canonical optimization backlog (Deliverables 6 + 7)

**OPT-56 Total Spine local-model follow-up (2026-09-18):** the new SAM correction
workflow reuses Alignment's sealed portable runtime without changing that runtime
or another viewer domain. `eagle_eye_total_spine/runtime_seal.py` holds a
window-owned verification snapshot: full hashes on first use or changed metadata,
then per-file identity/size/write/change-time checks on subsequent prompts, all in
the existing background executor. No patient data or interpreter is cached here.
The first independent cold full-service synthetic run took 284.92 s. A subsequent
two-prompt session with already-warm filesystem caches took 36.85 s for first
verification/inference and 17.38 s for the next prompt. The cold-vs-warm numbers are
not a controlled claim about model acceleration. Both produced masks and proposals;
runtime mutation/cancellation/failure guards passed. Source GUI and clinical
acceptance remain pending; OPT-56 is not closed by this feature.

**OPT-58 / OPT-60 Home image-I/O follow-up (2026-09-17):** the measured Home
QPixmap file read now runs as QImage preparation in the existing shared worker
service, with bounded progressive buffering and generation/native-lifetime checks.
Existing Home action/grouped/atomic/cadence contracts remain. Two fail-before
renderer guards; 23 new cases, 214 adjacent plus 24 panel/effect passes; 467 mirrors.
Fresh normal-source GUI remains pending; do not close cold Local header admission,
cache read/validation, pruning, Viewer or crash work. See the Home image preparation
receipt in `reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md` for rollback and gates.

**OPT-58 / OPT-60 enumeration correction, 2026-09-17:** shared Local inventory
retains directory-entry type information, eliminating one redundant Path.stat per
candidate while retaining independent fresh version checks. Two fail-before cost
guards; 334 expanded passes / 1 unavailable-symlink skip. Cache-path/read timing
split for the next source run. Grouped admission, cold/warm wall-time and GUI
acceptance remain OPEN; see the UI-stall report's enumeration receipt. Advanced
first-render freeze is assigned to its existing owner, not patched in Unify.

**OPT-58 / OPT-60 source evidence, 2026-09-17 09:13 run:** grouped Local (2 studies,
39 series) still waits 24.096 s for metadata; 2398 persisted hits / zero probes,
21.361 s inventory dominated by enumeration and cache reads. This is not a test
of the single-Local ownership branch. Concurrent first Advanced Render causes a
13.785 s GUI gap, with MathText imports and 13.209 s first-render timing; routed
to the Advanced owner as UNIFY-HANDOFF-2026-09-17-03. Read-only receipt in the
UI-stall report; grouped latency, Home GUI PNG I/O and open-time pruning remain
OPEN. No runtime fix or performance acceptance is claimed by this log review.

**OPT-58 / OPT-60 ownership follow-up, 2026-09-17:** remove Home setup's duplicate
inventory/snapshot push for exactly-one-study Local opens; the existing patient
stream owns delivery. Grouped Local aggregation and Server routes are unchanged.
Four pre-fix failures; 10 new guards / 321 expanded passes. Fresh-source GUI and
matched KPIs are OPEN; cold per-series classification and grouped catalog-first
admission are not fixed by this slice. See the single-study ownership receipt in
`reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md` and section 15.

**OPT-58 / OPT-60 status update, 2026-09-17:** Local repeated header admission
has a guarded persisted-fact optimization; cold unverified admission, source-GUI
acceptance and complete Unify/KPI closure remain open. See the dated receipt above
and section 15; this extends the existing items, not a separate plan.

**OPT-60 current slice status (2026-09-14):** manager retirement now also cancels card-local
Ready/hide timers and running property animations. See the newest receipt and section 15 for
the code gate. Source GUI requires a fresh launch; the 20:41 run predates card-effect changes.
Direct legacy map clears, worker-image identity, real completion/priority and the remaining
Unify phases stay open; no blanket native-crash or performance closure.
Detailed scope/rollback are in the current receipts above; validation is recorded in section 15.

One unified, risk-ranked backlog. Priority score ≈ **(Benefit × Confidence) ÷ (Risk × Complexity)**.
States: VERIFIED-COMPLETE · COMPLETE-MONITOR · PARTIAL · READY-SAFE · IMPL-UNVERIFIED · NEEDS-INSTRUMENTATION
· HIGH-RISK-DEFERRED · REGRESSION · OBSOLETE.

| ID | Problem | Pipeline | Evidence | Code status | Benefit | Risk | Cmplx | State | Priority |
|---|---|---|---|---|---|---|---|---|---|
| **OPT-56** | Advanced Analysis pays cold Slicer startup on user click; import-only prewarm was reported as ready | Workstation startup / external Advanced Analysis / offline AI | Three failing-before readiness/ownership guards; isolated synthetic probe verifies hidden startup, same-process promotion, exact series, independent threshold/model execution and parent Qt heartbeat | Default-on optional viewer warmup off the workstation GUI thread; authenticated role-specific local bridge; lazy separate headless runtime; owned-job shutdown; package mirrors synchronized | Faster warm opening; AI does not manipulate the user's viewer | Idle RAM and graphics qualification; Slicer's own DICOM load remains synchronous; no clinical accuracy claim | Medium | **PARTIAL: source/synthetic verification and user-confirmed launch/responsiveness complete; customer and clinical acceptance pending** | User-requested launch latency; preserves OPT-12 startup ownership discipline without repurposing it |
| **OPT-55** | Bounded focus coverage and report identity: axial underfill, sagittal ambiguity, screening sampling loss, pixel pressure, silent level shifts, diagnostic anchoring, cross-level evidence fusion, mixed-structure cognitive load, and omitted same-level consequences | Eagle Eye atomic structure analysis | Synthetic guards and saved-evidence comparisons verify geometry, focus identity, anatomy-only mapping, diagnosis-free handoff, task-specific image selection, independent card dispatch, strict response identity, exact endplate surface binding, objective posterior thresholds, deterministic merge, and immutable group transport without a model call. Byte-identical live atlases also exposed model-owned axial role instability, false semantic certainty from geometry, disc/canal task competition, color-dependent grouping, and representative-slice handoffs that hid complete membership | Pipeline 8.4.0 / atomic contract 2.5.0 / anatomy-card schema 1.9.0 / screening-atlas schema 1.6.0 / screening schema 3.3.0 / diagnosis schema 1.2.0. The official MRI architecture is raw DICOM → geometry-derived neutral series and persistent sagittal/axial groups → LLM sequence and anatomy labels → screening cards → diagnostic cards → classification. The workstation owns DICOM LPS order, patient side, physical correspondence, and group membership. It supplies semantic sequence labels only when operator-confirmed or high confidence; otherwise the atlas uses neutral identifiers. Gemini assigns unresolved sequence, sagittal regional role, and axial group-to-level semantics. Gate 1-to-2 screening cards now carry every original member of each included geometry group. Gate 2-to-3 diagnostic cards may select a task-specific subset only while retaining the parent group ID, complete original membership, and selected membership; mismatches fail with `geometry_group_integrity_error`. The canal-only screen additionally records a per-level caliber/CSF audit and uses at most two identity-checked MR-myelography overview images; a minor impression with preserved caliber cannot create a central positive. Five independent screens, one-structure Sol diagnosis, stage order, and semantic ownership remain unchanged | The official cross-MRI architecture, confidence rule, immutable grouping contract, card families, layout hierarchy, stage contracts, failure policy, and body-part extension boundary are documented in `docs/pipelines/eagle-eye-mri.md`. Guards prevent positional group-to-level mapping, low-confidence sequence relabeling, physical-order semantic relabeling, group-ID loss, incomplete screening-group transport, out-of-parent diagnostic selection, color-only grouping, group-splitting pagination, and combined foraminal/posterior screening | Clinical benefit and total cost remain unproven; anatomical level and low-confidence sequence naming remain model-assisted, a level missed by every screen still receives no diagnostic card, the atlas has no sagittal STIR, and near-identical-card Sol morphology variance remains unresolved | Medium | **IMPLEMENTED default-on in source; live verification pending.** Two group-handoff guards failed before implementation and now pass; one additional fail-closed subset guard passes. Complete AI Imaging passes 930 with 8 expected xfails and 3 existing SWIG warnings. Python compilation and mirror parity are verified separately | Restart the source build and inspect the saved Gate 1 atlas pages, all five complete-group Gate 1-to-2 cards, and every diagnostic card JSON. Confirm `group_integrity.status=validated`, unchanged parent IDs, complete original membership, and bounded selected membership. Also verify the canal observation audit and overview-only MR-myelography context against the radiologist reference. Then freeze 8.3.0 and run repeated multi-case experiments for recall, level/side/morphology/grading, false positives, failures, latency, and token cost. |
| **OPT-02** | Seam A: verify thumbnail token-stale render-from-model (kills "only first thumbnail") | C | 18 stale + 29 unaccounted; shipped 07-03 | `_hp_search.py` default-on | High reliab | Med (default-on, unverified) | Low | **IMPL-UNVERIFIED** | **P0** |
| **OPT-03** | Seam B: previous-exam grow keep-alive (kills "second drag needed") | D | 200 `resolved=None`; shipped 07-03 | `home_download_service.py` default-on | High reliab | Med | Low | **VERIFY FAILED 2026-07-05** (sess-11818cd24bf6): grow-lane `resolved=None` for prev-exam series 202 but seam_b nudge fired 0x — the nudge sits DOWNSTREAM of the primary-`study_uid` filter that drops SECONDARY-study progress, so it only ever covers the primary study. Series 202 crawled 40->58/256 via the disk-readiness resume fallback = "needs a 2nd nudge". PROPER FIX SHIPPED as **OPT-06** (study-scoped `(study_uid, series_number)` grow-lane fallback, `AIPACS_GROW_LANE_STUDY_NUMBER_BIND` default-OFF, 9/9 guard-test green) — OPT-03's seam becomes redundant once OPT-06 verifies. Same multi-study offset-key family as **OPT-20** (but OPT-20 is the initial `change_series` LOAD path, a different resolution — OPT-06 does not automatically close it) | **P1 (→ OPT-06)** |
| **OPT-01** | Move manifest scan / DM rebuild / GC off the GUI thread (the amplifier) Printing follow-up 2026-09-09: bounded background DICOM submission with captured study identity; see section 15 and the printing maintenance note. | H | 10,105 stalls, max 48 s; `build_local_manifest` iterdir on GUI thread | P1.1–1.3 + status-refresh dicom-only (`AIPACS_STATUS_REFRESH_DICOM_ONLY`, live-validated) + startup theme dedup (`AIPACS_THEME_APPLY_DEDUP`: patient-search + mainwindow + control-panel `AIPacs_ui`) + license defer (`AIPACS_DEFER_LICENSE_INFO`) done; tab-construction/EchoMind init (P1.4) / DM rebuild not | Very high (fixes 20% + drag) | Med | Med | **VERIFIED-COMPLETE** (during-use; startup OPT-12) | **DONE 07-05** |
| **OPT-09** | Log hygiene: download telemetry off WARNING; 13 MB single-record cap; throttle geometry-mismatch | — | 17 k WARNING/run bury 13 real errors | Shipped default-on 07-05 (`AIPACS_LOG_TELEMETRY_DOWNGRADE`) | Med (observability) | **Low** | Low | **VERIFIED-COMPLETE 2026-07-05** (live run sess-…416036: **+753 INFO / +295 WARNING / +9 ERROR** this run — telemetry relabelled to INFO, down from ~36,663 WARNING/run; real WARNING/ERROR now grep-able) | **DONE** |
| **OPT-14** | Reconcile `CLAUDE.md` with code (retired flags, `AIPACS_DENTAL_VTK_MPR` note) | — | registry §21 divergences | Not done | Med (maintainability) | **Low** | Low | **READY-SAFE** | **P1** |
| **OPT-05** | Download subprocess spawn access violation (pickle into child) | E | `native_fault.log` `download_process_worker.py:148` | Tracked | High (session stability) | Med | Med | **REGRESSION** | **P1** |
| **OPT-13** | Live-verify cine / multi-frame decode + playback | G | implemented; no cine data exercised | default-on | Low-Med | Low | Low | **IMPL-UNVERIFIED** | **P2** |
| **OPT-08** | Resolve Dental VTK-MPR default (doc ON vs code OFF) + geometry parity | D/geom | registry 🔴 row | code default-OFF | Med (dental correctness) | **High (geometry, clinical)** | Med | **REGRESSION/DIVERGENCE** | **P2** |
| **OPT-04** | Full Stage-1 lifecycle cutover: sidebar renders from model; DM re-key by canonical identity; off-GUI convergence sweep replaces `_dl_watchdog_tick`+resume+grow | B/C/D/F | the whole §4 defect | shadow only | **Very high (determinism)** | **High** | High | **HIGH-RISK-DEFERRED** (decompose) | **P2 (staged)** |
| **OPT-06** | Multi-study grow-lane bind for a PREVIOUS-EXAM/secondary series whose offset-key stored `series_uid` is stale/degenerate — the grow lane (`_grow_lane_display_key`→`display_key_for_active_series_uid`) matched DM download events by `series_uid` ONLY, so a prev-exam series was dropped (`resolved=None`) or mis-resolved to a bare number and never grew. This is the ROOT of OPT-03's failure and the recurring "series N shows in current AND previous exam / needs a 2nd drag" report | D | sess-11818cd24bf6 2026-07-05: `resolved=None`/wrong-number for prev-exam series 202; seam_b 0× | **study-scoped `(study_uid, series_number)` fallback SHIPPED default-OFF** (`AIPACS_GROW_LANE_STUDY_NUMBER_BIND`): binds ONLY after the `series_uid` match fails AND only when BOTH the resolved study_uid AND series_number equal the DM event's OWN (never cross-study; never overrides a series_uid match; default-off byte-identical). `home_download_service.py` `_dm_event_series_number` + identity threading; `_vc_progressive.py` fallback loop + `[GROW-LANE-STUDYNUM-BIND]` success marker; widened `[GROW-LANE-TRACE]` (full uids + `ev_num`). Guard `tests/code/viewer/test_grow_lane_study_number_bind.py` 9/9 green | High reliab (kills "2nd drag" + prev-exam no-grow) | **Low** (additive; study-scoped; default-off byte-identical) | Low | **MECHANISM-VERIFIED-SAFE, target not yet reproduced** (live run sess-…416036 with flag on: `ev_num` correctly computed = 10 / 100000; **0 false binds** under a 3-study + document session; the awaited prev-exam series 3000201/3000202 had VALID stored series_uids and loaded fine — this patient never hit the stale-uid case. The 77 unmatched `[GROW-LANE-TRACE]` were the DM downloading *other* series (10, doc 100000) no viewport awaited = correctly unbound. **KEY LEARNING: `resolved=None` is NOT inherently the defect** — it is the normal signal for a background series no viewport awaits; the bug is only when the DM `series_uid` MATCHES an awaiting entry's uid yet still resolves None. Keep default-OFF until a run shows a `[GROW-LANE-TRACE]` whose DM `series_uid` equals an `awaiting` uid with `resolved=None`) | **P2 (staged; safe)** |
| **OPT-07** | Multi-study B1 Series 100000 (DICOMized document) offset-key resolution | D | STAGED in MULTISTUDY 06-30 | not started | Low-Med | Med | Med | **NOT STARTED** | **P3** |
| **OPT-12** | Startup main-thread stall — ROOT-CAUSED 07-05 to the single-instance takeover sweep (NOT EchoMind/add_AIPacs_tab as first assumed): psutil `proc.name()`/`.exe()` + `ppid_map()` rebuilds | A | STALL_TRACE `single_instance_lock.py:446`/`:387` | name-reuse + fast ppid-snapshot (`AIPACS_FAST_INSTANCE_SWEEP`) BOTH now **default-on** | Med (one-time) | Med | Med | **VERIFIED-COMPLETE 2026-07-05** (live run sess-…416036 with the flag on: `single_instance_lock.py:387` sweep stall **0 traces**, `:446` already gone, **0 crashes**, nothing wrongly closed. During-use **0 stalls / max 0 ms**) | **DONE** |
| **OPT-10** | Geometry T2/T3: persist spacing/photometric; DB metadata path (~1424 ms H1) | G/geom | GEOMETRY 06-14 | staged | Med (latency) | **High (every render)** | High | **HIGH-RISK-DEFERRED** | **P3 (golden-compare gate)** |
| **OPT-11** | Collapse verified default-on kill switches (one at a time, post-verify) | — | ~40+ flags; `CLAUDE.md` directive | 8 collapsed (07-05: license-defer, theme-dedup, status-trim, dl-cache, + 3 clinical wrong-series flags) | Med (maintainability) | Med (per-flag) | Med | **PARTIAL** (continue as items soak) | **P3 (continuous)** |
| **OPT-16** | Add CPU/GPU runtime sampling to live logs | — | KPI §4 gap | none | Low (visibility) | Low | Low | **NEEDS-INSTRUMENTATION** | **P3** |
| **OPT-15** | EchoMind prompt safety (legacy "exaggeration", correction schema, modality match, temp/max_tokens) | — | UNIFIED P4.2 | audit | Med (output quality) | Med | Med | **NOT STARTED** | **P3 (separate track)** |
| **OPT-17** | Viewer-cache STUDY-IDENTITY hardening: make study_uid an intrinsic, positively-checked property of every in-memory viewer/ZetaBoost cache entry (tiers 1-3 had NO study check; tier-4 failed open on missing study_uid) | C/D (isolation) | audit `CLINICAL_SERIES_IDENTITY_TARGET_AUDIT_2026-07-05` finding #1; 48952 | `_vc_backend.py` + `_vc_cache.py` default-on (`AIPACS_CACHE_STUDY_IDENTITY`); 11/11 guard-test green | High (clinical isolation) | **Low** (additive; multi-study-gated; fail-open; single-study byte-identical) | Low | **IMPL-UNVERIFIED** (shipped in the 07-05 release; live-verify in N-1) | **P1** |
| **OPT-18** | DB series-owner enforcement: default `AIPACS_DB_ENFORCE_OWNER=1` for clinical builds so a non-conformant DUPLICATE SeriesInstanceUID across studies cannot silently repoint a series' `study_fk` (blocks + metadata-only refresh; already logged as `[CrossStudyReassignment]`) | C/D (isolation) | audit `CLINICAL_SERIES_IDENTITY_TARGET_AUDIT_2026-07-05` finding #2 | guard EXISTS in `database/dicom_db.py` but default `"0"` = OBSERVE-ONLY (logs, does not block); enforcement path already coded behind `=1` | High (clinical isolation; cheap) | **Low** (config-default flip; enforce path exists + `test_multistudy_identity_guards`) | Low | **VERIFIED-COMPLETE 2026-07-05** (default `"1"`; live run sess-…416036: **0 CrossStudy/CrossPatient reassignment events** on a multi-study + previous-exam + document session = enforce-on causes no false blocks on conformant data) | **DONE** |
| **OPT-19** | Series-identity robustness cluster (defence-in-depth; NOT a misread hazard): (a) self-describing drag payload — carry study_uid+series_uid, not only the offset display key [#3]; (b) DM `series_uid` degrade-to-bare-number defensive guard/log [#4]; (c) study-completeness probe use the collision-safe canonical folder resolver, not the bare series_number [#5 — partly covered by `_DM_CANON_IDENTITY` default-on] | D (multi-study) | audit findings #3/#4/#5 | not started (all Low; no active leak observed) | Low-Med (robustness) | Low | Med | **NOT STARTED** | **P3** |
| **OPT-20** | Multi-study SECONDARY-study series (higher-slot offset key, e.g. `3000002` = slot 3 / series 2) **fails to resolve → load → display** when its original number collides with another study's series — a viewport display MISS (blank/stuck), NOT wrong pixels | D (multi-study) | **live sess-34560eed25d3 2026-07-05**: `change_series(3000002)` → `_load_single_series_on_demand` runs but **no `[MULTI-STUDY LOAD]` resolution, no `open_series`** → `ViewportLoadingStateCleared series=None`; sibling keys (`3000004`, `2000005`, primary `2`) `hot_hit`+render. 59 display-misses this run. Gate held (0 wrong-study skips) | **RESOLVED (metric) + NARROWED to a self-recovering edge case 2026-07-05.** Deep trace of sess-…416036: **(1) the "66 display-misses" metric was FALSE.** `ViewportLoadingStateCleared series=None` is emitted by `_hide_spinner_for_widget` logging `_awaiting_series_number`, which is **None AFTER a successful load** (awaiting reset). Every one of the 66 followed a successful `open_series` + `first_image_visible`; `ViewportLoadFailed=0`; non-None clears=0. So there were **ZERO real display failures**, and every actively-viewed series — INCLUDING previous exams (slots 2 & 3: `2000002-6`, `3000201/2`) — rendered. Verify script metric corrected to count `ViewportLoadFailed` + non-None clears (not benign `series=None`). **(2) ONE series genuinely did not render: `1000001`** (a 13.5 MB single-frame **DX**, slot-1 previous exam, study `…20260607092105.0.28`), dragged at 20:09 **DURING its own 13.5 MB download**. Study/disk/DB/metadata ALL resolved CORRECTLY (`[MULTI-STUDY LOAD] entry-authority slot=1`, `study_pk=1793`, `disk_series=1`, `[H7-P4] disk_file_count=1`, `[FAST_LOAD_BREAKDOWN] headers_only_build=4ms`) — but the render aborted AFTER header-build (never reached `_start_qt_viewer`: no `IDENTITY-GATE eval`, no `first_image_visible`). `itk_pipeline files=2` disagrees with the fresh `[H7-P4] disk_file_count=1` at the SAME retry → a **stale mid-download metadata/instance cache** (`_get_cached_metadata` / `_reconcile_db_instances_with_disk` reconcile=0 ms did not refresh) that `force_reload` + `ZetaBoost INVALIDATE` did NOT clear, so the 3 retries reused it. NOT a multi-study resolution bug (resolution correct) and NOT wrong-pixels (blank, re-openable). Fix target = FAST metadata-cache invalidation on `force_reload`. LIVE TEST: re-drop `1000001` after an app restart (clears in-mem cache) — renders ⇒ confirms stale-mid-download-cache **(3) SECOND, HIGHER-SEVERITY RESIDUAL - previous-exam INTERMITTENT render miss under contention (sess-9721c090163f, the "second patient" symptom).** Per-series tally: previous-exam offset keys render only SOMETIMES - `1000004` 1/5, `1000006` 1/3, `1000003` 4/5 - while primary series 1-6 render 1:1. Decisive compare: `1000003` (21:48:46) load completes (`load_single_series_total 155ms`) then `first_image_visible render_ms=40`; `1000004` (21:48:56) load completes IDENTICALLY (`143ms`) then NO `first_image`, immediately a `MAIN_THREAD_STALL 224ms` with `active_series_number=1000003` (viewport stayed on the PRIOR series). This run had **65 main-thread stalls, max 5.7s** (vs 0 in run 1) because the second patient has many previous-exam studies downloading at once. Under GUI-thread contention the FAST **render-apply for a rapidly-switched previous-exam series is DROPPED** (metadata load finishes, repaint never lands) with NO convergence to re-render. Amplified by `[DB_METADATA_GATE] geometry holes -> disk header path` (a still-downloading study's DB metadata is incomplete). NOT the identity gate (0 skips, never reached), NOT resolution, NOT the false metric = the OPT-04 no-convergence x OPT-01 main-thread intersection, reproduced. `verify_opt20.ps1` verdict corrected to flag intermittent offset-key renders + correlate stalls | Med-High (real intermittent previous-exam display miss) | Med (contained: FAST disk-header metadata path for DX) | High | **METRIC FIXED. (4) CORRECTED ROOT CAUSE 2026-07-06 (48456, sess pid454684, 0 stalls) — NOT contention/OPT-04 (that theory disproved: 0 main-thread stalls this run, study download COMPLETE).** The RENDER-DROP detector caught all 3 misses; ALL THREE (`1000001`, `2000001`, `2000002`) are **large single-frame DX images** (~13 MB, SOP `1.2.840.10008.5.1.4.1.1.1.1`) loaded as PREVIOUS-EXAM series. DX images have NO ImageOrientationPatient (2D projection), so their DB metadata is flagged "geometry holes" -> `[DB_METADATA_GATE] -> disk header path`. The SAME DX render fine as PRIMARY series AND via the DB-metadata path (slot-1 `1000002-5` all rendered 2/2); they fail ONLY via the FAST **disk-header** metadata path (slot-2 study `…20260615200149.0.42`): metadata builds (`[FAST_LOAD_BREAKDOWN] headers_only_build`) but the render never reaches `_start_qt_viewer` (identity-gate evals=0, no first_image) -> empty apply. So the real bug = **the FAST disk-header metadata/apply path does not render DX / no-geometry single-frame images**, while the DB-metadata path does. Deterministic (not timing/contention). Fix target = reconcile the disk-header DX metadata/apply with the working DB path (narrow, contained). Detector: `AIPACS_RENDER_DROP_DETECT` default-on. **(5) DEFINITIVE ROOT CAUSE + FIX 2026-07-06 (48456, run pid via FAST-YIELD-TRACE): NOT a metadata bug — ALL 51 `[FAST-YIELD-TRACE]` = `will_yield=True` (metadata always builds). It is a DROPPED UI APPLY.** On a rapidly re-switched LARGE single-frame previous-exam image (DX up to 13613x4424 = 60 MP, and DICOMized documents series 100000), the worker-thread load finishes (`stage-timing ~179ms`, `[MULTI-STUDY LOAD]`, `[H7-P4]` all present) and queues the UI apply FIRE-AND-FORGET (`_apply_loaded_series_data_threadsafe` -> `_queue_on_ui_thread`), but `_apply_loaded_series_data`'s stale-request guard (`_vc_load.py:1204`, `_is_request_current` False -> `[APPLY STALE]` return) DROPS the repaint, and nothing re-renders it -> `_start_qt_viewer` never runs (IDENTITY-GATE evals=0 for the miss, skips=0). Intermittent (same series renders on the switches whose apply wins the token), 0 stalls, no supersession by a new `change_series` (detector gen-confirmed). The manual re-click renders (the user's 4/7). **FIX = render-convergence:** the `[RENDER-DROP]` detector, on a confirmed drop (gen-match, not-rendered, not-awaiting), re-issues the SAME series ONCE (`change_series_on_viewer`) = the auto version of the successful re-click. Bounded 1 retry/series/episode (reset on next render) so it cannot loop; only fires when NOT superseded/awaiting. `_vc_switch.py`, flag `AIPACS_RENDER_DROP_RECONVERGE` DEFAULT OFF pending live validation (`run_dx_trace.ps1` sets it =1); marker `[RENDER-DROP-RECONVERGE]`. **(6) TRUE ROOT CAUSE + FIX 2026-07-06 (48456) — a TYPE-MISMATCH gate, deterministic (my (3) contention + (5) stale-token/reconverge theories were BOTH WRONG; the reconverge fired but the miss persisted + fails even fully-cached => not a race).** The async worker-load apply path `_apply_loaded_series_data` (`_vc_load.py:1259`) gated the render (`_perform_series_switch_optimized` -> `_start_qt_viewer`) on `current_idx == series_idx`, where `current_idx = vtk_w.last_series_show`. But `last_series_show` holds the **series NUMBER** (`_pw_viewers.py:684` sets it = `metadata['series']['series_number']`) while `series_idx` is the **list INDEX** returned by `replace_series_data` (`-> int`). For an offset-key previous-exam series (`2000001`, `1100000`, …) a series number can NEVER equal a small list index -> the gate is ALWAYS False -> the render block is skipped -> `_start_qt_viewer` never runs (IDENTITY-GATE evals=0, `[FAST-YIELD-TRACE] will_yield=True` = metadata was fine). Small primary numbers matched the index only by coincidence and/or rendered via the SYNC path, so only large/offset async loads failed. **FIX (`_vc_load.py`, flag `AIPACS_APPLY_RENDER_TARGET_VIEWER` DEFAULT OFF pending live verify): also render for the explicitly-targeted, non-stale viewer** (already past the `target_viewer_id` filter + the `_is_request_current` stale check, so THIS is the viewer that requested THIS series) regardless of the broken index compare. Additive (legacy index match preserved; no-target broadcast unchanged). Confirmation log `[APPLY-GATE] last_series_show=… series_idx=… legacy_match=… target_fix_render=…` proves both the mismatch and the fix. **LIVE-VERIFIED + PROMOTED DEFAULT-ON 2026-07-06 (45289).** With `AIPACS_APPLY_TRACE=1` the `[apply-path]` breakdown proved it: `APPLY-ENTER=34`, `APPLY-STALE-EARLY=0` (the stale-token theory is dead), `APPLY-GATE legacy_match=False=28` (the type-mismatch would have skipped 28 renders), **`target_fix_render=29`** (the fix rendered them). The `[APPLY-GATE]` lines show it exactly: `series=1000002 last_series_show=4 series_idx=5 legacy_match=False target_fix_render=True` (series NUMBER 4 vs list INDEX 5) + `first_image_visible` follows each. Previous-exam DX/document series that were 0/N now render (1000001 4/4, 1000004 3/3, …). Flag `AIPACS_APPLY_RENDER_TARGET_VIEWER` flipped default `"0"`->`"1"` (kill switch `=0`); the `[APPLY-ENTER]`/`[APPLY-GATE]` telemetry gated behind `AIPACS_APPLY_TRACE` (default OFF, no clinical-log spam). **TWO RARE RESIDUALS (small follow-ups, not the main bug):** (a) an occasional miss where `_apply_loaded_series_data` was NEVER entered (no `[APPLY-ENTER]`) = the worker->UI fire-and-forget post (`_queue_on_ui_thread`) was lost for that one switch (1000002 1-of-5, recovered on the user's next click); (b) 1 `[FAST-YIELD-TRACE] will_yield=False` = a rare metadata-build returning no instances. Both intermittent + rare. **(7) SLOT-3 RESIDUAL ROOT-CAUSED + FIXED default-on 2026-07-07 (`AIPACS_SERIES_APPEND_STUDY_DISTINCT`).** The 49317 case where distinct secondary-study series `3000001`/`3000002` reached `[APPLY-ENTER]` but never `[APPLY-GATE]` was NOT the token gate (`[APPLY-STALE-EARLY]=0`, same UI thread) — it was `series_idx<0`: `add_new_data_to_lst_thumbnails_data` (`_pw_metadata.py`) had a **study-blind name+count dedup** that `return False`'d a distinct series sharing a `series_name`+count with an already-present series (common across a multi-study patient's studies), so it was never appended → `replace_series_data` returned -1 → render loop gated off. Fix: skip as a true duplicate ONLY when the incoming `series_number` is already present; a distinct not-present number appends. Isolation untouched (identity gate still fail-closed on `series_uid`). 8/8 headless checks vs the real method; guard `test_series_append_study_distinct.py`. NEEDS live verify on 49317 | **DONE (index-gate + slot-3 append-skip fixes shipped default-on); residuals (a) lost UI-post + (b) rare empty metadata + `1100000` document = OPT-07 = P2 follow-ups** |
| **OPT-21** | End-user PC whole-app NATIVE crash opening Standard MPR: a machine whose display driver cannot provide OpenGL 3.2 dies with an access violation inside the FIRST `QVTKRenderWindowInteractor` (`_mpr_views._create_axial_view`, between construction and `Initialize()`) — no Python traceback, every log stops mid-line. FAST 2D is VTK-free so the machine looks healthy until the MPR click (PC2 "baba", 2026-07-07 14:48, MR 144-slice; deferred-3D never reached) | MPR | PC2 logs (`app.log`/`viewer_diagnostics.log`/`zeta_mpr_canon_probe.log` all end 14:48:02.63-.64 at `create_view axial`) | **SHIPPED default-on 2026-07-07**: (1) `modules/mpr/opengl_preflight.py` — PERSISTED once-per-INSTALL check (`<config>/hardware_check.json`; user directive: never re-probe per session/click): persisted PASS = zero probing on MPR open; persisted FAIL/missing = graceful Qt probe now + persist (self-heals after a driver update); called in `toggle_zeta_mpr` BEFORE volume load/VTK construction → friendly QMessageBox + tool-state reset instead of process death (`AIPACS_MPR_OPENGL_PREFLIGHT`, `=0` legacy); (2) **Settings → Viewer Configuration → "Hardware Requirements Check"** (`settings_ui/hardware_check_panel.py`) — on-demand full check (OpenGL/GPU, CPU, RAM, disk via pure `evaluate_hardware`; only OpenGL gates MPR) with persisted display; (3) production faulthandler → `user_data/logs/native_fault.log` (`PacsClient/utils/native_fault_log.py`, wired early in `main.py`, `AIPACS_NATIVE_FAULT_LOG`, `=0` off) so any future native fault leaves all-thread Python stacks even frozen. `hardware_check.json` = machine state, never seeded | High (whole-app crash → contained failure + diagnosability) | **Low** (additive; probe cached; flag-gated; blocked path only on probe failure) | Low | **IMPL-VERIFIED offscreen** (15/15 new guard tests; viewer suite 60 fails = byte-identical to stashed baseline, 0 new). NEEDS: machine-level confirm on PC2 (Event Viewer faulting module / driver update) + live source-build sanity (MPR still opens on a good GPU) | **P1** |

| **OPT-22** | STARTUP freeze: in-app web-browser Chromium prewarm constructs `QWebEngineView` on the GUI thread → up to **21 s** main-thread stall (`interaction_active=False`, t_since_start ~39 s) while the user is on the main page / patient list | Startup | 07-07 sess-d2bd9ea75f3f: `[MAIN_THREAD_STALL] stall_duration_ms=21054.2` ends exactly at `web_browser.prewarm._construct_warm_view` "Chromium engine warmed" (14:57:54.67 vs 54.74). Also 20074/8546/7357 ms startup stalls | **PRE-EXISTING** (prewarm module + call site landed v3.3.9 2026-06-27; NOT changed v3.4.6; NOT unified-pipeline). Marker-gated (only warms if browser used before) + kill switch `AIPACS_BROWSER_PREWARM=0` already exists. QWebEngineView is GUI-thread-only (can't off-thread) → fix = defer-to-idle / open-on-intent, not off-threading | High (multi-s startup freeze) | Low (opt only; kill switch exists) | Low | **FIXED default-on 2026-07-08** (`AIPACS_BROWSER_PREWARM_IDLE_ONLY`): the GUI-thread warm now waits for a genuine idle gap (no discrete input for `idle_ms`, default 5 s) after a longer initial delay (default 20 s), rechecking on a poll timer, and SKIPS the warm entirely if the user stays busy past a cap (default 10 min) — so the 21 s block lands only when the user isn't interacting, or not at all. Marker-gate + `AIPACS_BROWSER_PREWARM=0` preserved; `IDLE_ONLY=0` = byte-identical legacy fixed-delay. `modules/web_browser/prewarm.py`. Guard `tests/code/system/test_browser_prewarm_idle_gate.py` (+ algorithm validated standalone; py_compile blocked in-sandbox by the FUSE mount-staleness on that one file — Read-tool confirms the file is complete/well-formed). NEEDS live verify. Report `docs/reports/REGRESSION_REVIEW_STARTUP_AND_ECHOMIND_FREEZE_2026-07-08.md` | **DONE (needs live verify)** |
| **OPT-24** | Download queue does not auto-resume after the internet drops for several minutes then returns; manual resume/global-vs-individual controls unreliable. TWO defects: **(A)** the temporary/network retry budget is COUNT-based (`MAX_RETRIES_TEMPORARY=10`, backoff `min(30s,3s·(n+1))` ≈ 2.75 min) so an outage > ~3 min drains it *while still offline*, then `retry_count>=cap` excludes the study from BOTH `_check_auto_retry` and the 5 s `_pipeline_health_check` sweep, and there is NO connectivity monitor to re-arm it → stranded `FAILED`; **(B)** completion never converges to `download_rows` (216× `not in download_rows` + 24× `no workers` re-spawn in 07-07 logs) → a finished study is re-downloaded in a loop (= the OPT-04 defect) | E / DM | audit `docs/reports/DOWNLOAD_MANAGER_RESUME_RETRY_RELIABILITY_AUDIT_2026-07-08.md`; `download_diagnostics.log` 07-07 | **Defect A SHIPPED default-ON 2026-07-08** (decomposed, additive, each kill-switched `=0`): **A1** `modules/download_manager/network/net_monitor.py` — pure-stdlib off-GUI-thread TCP reachability probe reporting offline→online EDGES (`AIPACS_DM_NET_MONITOR`); **A3** `_dm_workers._rearm_network_failed_studies` resets `retry_count`+flips FAILED→PENDING for TEMPORARY failures only (permanent left untouched), the SINGLE re-arm the monitor + any future "resume all" both call (`AIPACS_DM_NET_RESUME`); **A4** `_effective_retry_cap` returns `MAX_RETRIES_TEMPORARY_UNSTABLE=100000` under the same flag so a long outage keeps retrying; **I1** `_on_start_selected` delegates to the canonical `_on_per_patient_resume` (`AIPACS_DM_UNIFY_RESUME`) killing the drifted duplicate (was missing COMPLETED branch); **L1–L4** `[DM-STATE]`/`[DM-NET]`/`[DM-RETRY-EXHAUSTED]`/`[DM-CONVERGE-MISS]` structured logs. **Defect B (convergence) = OPT-04, NOT attempted here** (only the L3 diagnostic marker added) | High reliab (kills "won't resume after outage") | **Low** (all additive; each piece has a `=0` kill switch → legacy byte-identical; permanent failures untouched; no hot path change) | Med | **IMPL-VERIFIED on host venv** (full pytest 11/11 green incl. the PySide6 `_dm_workers` import path; py_compile host OK on all 6 files + payload; **plugin mirror synced + verified 412/412, `net_monitor.py` added**). G1 global-Start-All unification NOT done (cancelled-restart semantics differ; deferred). NEEDS live source-build verify: >5 min outage → studies re-arm on reconnect | **P1 (Defect A shipped default-on; Defect B → OPT-04)** |
| **OPT-23** | Secretary EchoMind viewport import FREEZE: dispatch runs **inline on the UI thread** (`QTimer.singleShot(0)`→`bus.execute`→`change_series_on_viewer`); Advanced/VTK switch builds `ImageViewer2D()`+`Render()` sync (~2.4 s); AI-seg `on_contour_closed`→`requests.post` sync network on UI thread (→6.5 s) | D / EchoMind | 07-07 stall stacks: `_perform_series_switch_optimized→switch_series→ImageViewer2D.__init__→Render()` (2439 ms); `on_contour_closed→download_file→requests.post→socket.recv_into` (411→6498 ms) | **UNDERLYING PRE-EXISTING** (sync `change_series_on_viewer` = 06-06 bridge; Advanced VTK render older); **v3.4.6 "EchoMind unified MCP" (`aipacs_control_mcp/server.py`) is the NEW TRIGGER** that first drives it programmatically. Bus BUILD is cheap (registration only) — not the freeze | High (import freeze) | Med-low (parity with proven drop path) | Med | **FIXED default-on 2026-07-08** (`AIPACS_ECHOMIND_DEFER_SWITCH`): `viewer_write_adapter.change_series` now defers the `method_change_series_on_viewer(...)` call to `QTimer.singleShot(0, ...)` — matching the REAL drop handler (`_vw_dragdrop.dropEvent → singleShot(0, _do_series_switch)`, which the file's own fidelity note already claimed). The loading spinner (shown above the call) now PAINTS before the switch and the command-bus/IPC drain returns immediately, so the import shows "loading" instead of a dead freeze. `=0` = legacy inline. Guard `tests/code/echomind/test_echomind_defer_switch.py` (3 green in-sandbox vs the REAL adapter: defers-by-default / inline-when-off / spinner-first). **STILL PENDING (follow-ups, in the report):** the Advanced/VTK `ImageViewer2D`+`Render()` is GUI-thread-inherent (spinner only); the AI-seg `on_contour_closed→requests.post` sync network POST should move off-thread. `viewer_write_adapter.py`. Report as above | **DONE (import; VTK-render + AI-seg upload = follow-ups)** |

| **OPT-28** | **Stale pooled socket handed out as healthy — the connectivity root cause.** `PatientListSocketClient.is_connected()` is a FLAG (`self.connected and self.socket is not None`), never validated. On a public-internet path (remote server / NAT / firewall) an idle pooled connection is closed by the peer; the flag still says "connected", so `SocketConnectionPool.get_connection()` hands out the corpse, `send_request` skips its reconnect branch, `sendall` succeeds into the dead socket and the read hits **EOF** → `Invalid response length header` → **`return None` with NO retry**. `return_connection()` then re-pooled it, so a single blip kept failing after the network recovered. Only the **UI-facing** client is affected — the DM client (`download_manager/network/socket_client.py`) already has `REQUEST_MAX_RETRIES`/`connect_with_retry` and rode out the same fault | Network (patient list / report status / previous exams) | **Field logs 2026-07-13 (laptop, server `81.16.117.196` over the internet):** EVERY socket error in the session is `Invalid response length header` — **zero timeouts** — across `GetPatientList` (×7), `UpdateReportStatus` (×2), `GetPatientReceptionHistory` (×3), plus one `[WinError 10053]`. Surfaced as `❌ Search returned None` / `Update failed - no response from server` | **SHIPPED default-on 2026-07-13** (`modules/network/socket_client.py`): (1) `is_socket_alive()` — real liveness probe (`select` → readable-with-0-bytes = EOF = dead; readable-with-bytes = stream desync = dead; not-readable = alive, the cheap common path); (2) `is_reusable(max_idle)` — healthy + not idle past `AIPACS_SOCKET_POOL_IDLE_S` (default 30 s, below any common NAT idle timeout) + alive; (3) pool `get_connection()` gates on `is_reusable`, `return_connection()` REFUSES to re-pool a client whose last request failed (`healthy=False`) or that is disconnected; (4) `send_request()` = pre-flight recycle + **one reconnect-and-resend when the failure happened BEFORE any response byte** (`_last_error_zero_byte`) — a half-open socket means the server never saw the request, so this is side-effect-safe even for `UpdateReportStatus`; a **mid-response** failure is never resent (the request may have been applied), and a live-connection timeout is never resent. Kill switch `AIPACS_SOCKET_RECONNECT_RETRY=0` = byte-identical legacy | **Very high** (kills the whole network-loss failure family + its non-recovery) | **Low** (additive; narrow retry classification; kill-switched; DM path untouched) | Low | **IMPL-VERIFIED offscreen** (16/16 new guard tests `tests/code/network/test_socket_pool_health.py`; full `tests/code/network` + `ui_services` + `system` + `download_manager` + `storage` = **1219 passed, 0 new failures vs the stashed baseline**) | **P0 — NEEDS live verify on the laptop (pull the network, search, restore, search again → recovers silently)** |
| **OPT-29** | **Patient-table Shiboken native ACCESS VIOLATION during row construction and clear.** The July guard stopped cell-widget teardown/re-entrant producers, but the table still replaced the hidden `order` `SortableItem` twice per row and bulk-invalidated all remaining `QTableWidgetItem` wrappers from inside `setRowCount(0)`. Local search also called `QApplication.processEvents()` synchronously between clear and its normal coroutine yield | A / home UI | **Native-symbol confirmation 2026-08-28:** all four v3.6.3 Windows Application Error events (2026-08-24 10:53; 2026-08-28 11:05, 11:20, 22:18) fault in `shiboken6.abi3.dll`, exception `0xc0000005`, offset `0x26f20`; PE exports place that address at `Shiboken::BindingManager::releaseWrapper + 0x90`. Faulthandler stacks split exactly between `add_patient_data` at the duplicate `setItem` and `clear_table` at `setRowCount(0)`. The paired Windows System/Application logs contain no GPU reset, OOM, disk, or network precursor at the crash windows | **SHIPPED source fix 2026-08-28**, preserving the existing `AIPACS_SAFE_CLEAR_TABLE` rollback path: (1) create the hidden `order` item once; (2) transfer every row item out of Qt ownership with `takeItem` before `removeRow`/`setRowCount(0)`, retain strong Python references through the model mutation, then release them afterward; (3) apply the same rule to provisional-pin row removal and row-count shrink; (4) retain deferred cell-widget destruction; (5) remove Local Server's redundant nested `QApplication.processEvents()` call and use the existing `await asyncio.sleep(0)` yield | **Very high** (whole-app crash) | **Low-Med** (ownership/lifetime only; no clinical, network, database, or visible table behavior change; legacy kill switch retained) | Low | **ROOT CAUSE CONFIRMED + IMPL-VERIFIED offscreen**: four new guards failed on the pre-fix source; fixed suite **16/16 passed**, including a real Qt/Shiboken test proving taken subclassed items remain valid across `setRowCount(0)`; direct `py_compile` and diff checks green. Upgrade-only is not accepted because Shiboken 6.10.3 retains the same release path and has no matching release-note fix | **P0 — NEEDS live source-build soak on the affected PC: repeatedly open Local Server / local list, alternate searches, and exercise 45+ rows with active status/download updates; then ship only after zero new native faults** |
| **OPT-30** | **"Sync Status" reports SUCCESS when the server never received it — clinical state divergence.** `PatientSyncService._sync_worker` emitted `sync_completed` unconditionally (`sync_failed` only on an exception); a failed attachment upload or a failed `update_report_status` merely appended to `result['errors']`. `toolbar_manager.on_sync_completed` never inspected `errors` / `status_updated`, so it set the study to **`physician_approved`**, painted the home row green ("synced") and **CLOSED the patient tab** — while the server had received nothing. The queued `statusError` from the report-status service then popped a modal on the home table AFTER the tab was gone (the symptom the user reported) | Reporting / sync | **Field logs 2026-07-13, twice:** `13:26:52 ERROR Update failed - no response from server` → `13:26:54 [VOICE-DELETE-GUARD] … non-user teardown` (the tab closing). Same pair at 11:58:30 → 11:58:35. Both are OPT-28's dead-socket EOF on `UpdateReportStatus` | **SHIPPED default-on 2026-07-13**: (1) pure `_sync_result_failed(result)` — success requires no recorded errors AND `status_updated` True AND `attachments_failed == 0`; `_sync_worker` routes anything else to **`sync_failed`** (keeps the tab open, offers Retry; local files were never at risk — the local-first/non-destructive-reconcile guards are untouched). Kill switch `AIPACS_SYNC_STRICT_RESULT=0`; (2) `on_sync_completed` RE-VALIDATES with the same pure predicate before it closes the tab / writes `physician_approved` (defence in depth — it is the site that asserts the server state); (3) `sync_in_progress()` (+ grace window for the queued cross-thread signals) suppresses the duplicate `statusError` popup while the sync owns that error | **Very high** (the workstation asserted a clinical state the server never had) | **Low** (additive predicate; kill-switched; no change to the successful path) | Low | **IMPL-VERIFIED offscreen** (14/14 new guard tests `tests/code/ui_services/test_sync_status_strict_result.py`; 0 regressions) | **P0 — NEEDS live verify (sync with the network down → tab stays open + Retry; sync with the network up → unchanged success + close)** |
| **OPT-31** | **Modal dialogs on a network-failure path spin a NESTED Qt event loop on the GUI thread** — the app "freezes", and timers/coroutines keep firing behind the dialog (the search coroutine, the status-refresh chain, the pin-overlay timer), which is exactly the re-entrancy OPT-29 lives in. On a flaky link they arrive in bursts | A / home UI | Same 2026-07-13 session: repeated `Search returned None` → repeated `QMessageBox.critical` | **SHIPPED default-on 2026-07-13**: `_show_conn_failed` (`home_search_service.py`) and `_on_report_status_error` (`patient_table_widget.py`) now use a NON-modal `QMessageBox.show()` (no nested loop), at most one box per burst, with the persistent connection indicator carrying the state. Kill switches `AIPACS_MODAL_CONN_FAILED=1` / `AIPACS_MODAL_STATUS_ERROR=1` restore the modals | Med-High (perceived freeze + re-entrancy) | **Low** | Low | **IMPL-VERIFIED offscreen** (pinned by the OPT-29/30 guard tests) | **P1 — NEEDS live verify** |
| **OPT-32** | Patient-list search ~0.5 s = **server-side date+modality SCAN**, confirmed by the built-in one-shot A/B probe (`with_study_count_ms=489 vs without=434, delta=55 → "SCAN is the cost (not enrichment) → needs a SERVER-side index; no client fix helps"`). Client waste on top: the pre-flight `test_connection()` is a FULL extra `GetPatientList` round-trip, and `[SEED_CONFIG]` re-scans 7-10× per search. The *perceived* multi-second slowness was OPT-28 (dead socket → empty result → re-probe → another round-trip) | Network / server | `[SEARCH-PERF] search_ms=489/504/538 rows=45`, `[SEARCH-ENRICH-PROBE]` verdict, 2026-07-13 | Not started. Same index fix already applied at the other centre (see OPT-24 history) | Med (perceived latency) | Low (server-side) | Low | **NOT STARTED** — server-side index is the only real fix; the client-side probe can be dropped once OPT-28 makes a stale socket self-heal | **P2** |

| **OPT-33** | **EchoMind AI calls have NO timeout → the AI panel hangs forever when the link dies mid-request.** All ten `requests.post(...)` calls in `modules/EchoMind/viewer_chat/openai_reporter.py` (to the external `api.gapgpt.app` endpoint) were issued without `timeout=`, i.e. requests waits indefinitely. **Not a crash** — each runs on an `ApiWorker` QThread wrapped in try/except, so the app survives and shows "check your internet connection" on a *clean* error. But on a **half-open** connection (a link that dies mid-request — exactly what the field laptop's network does, see OPT-28) the worker never returns: the "typing…" bubble spins forever, the Send button stays locked (`lock_btn`), and the QThread leaks — one more per retry | EchoMind | Connectivity audit 2026-07-13 (the "does EchoMind hang/attenuate on net loss?" recheck). **EchoMind made ZERO network calls in the crash session** (adapter registration only) — it is NOT implicated in the crash; this is a forward-looking hang risk | **SHIPPED default-on 2026-07-13**: `_request_timeout()` → `(connect=10 s, read=180 s)` on all 10 calls — a connect must fail fast, a long LLM completion needs a generous read budget. A timeout turns an infinite hang into the EXISTING error path (the user gets the "Connection error" bubble and can retry). Tunable via `AIPACS_ECHOMIND_HTTP_TIMEOUT=<read_seconds>`; `=0` restores the legacy wait-forever. **`openai_reporter.py` IS plugin-mirrored** — synced on the Windows host (413/413 match) | Med-High (AI panel unusable + thread leak after any mid-request drop) | **Low** (one kwarg per call; kill switch; error path already existed) | Low | **IMPL-VERIFIED offscreen** (5/5 new guard tests `tests/code/echomind/test_echomind_http_timeout.py`, incl. an AST sweep that FAILS if any `requests.*` call in the module ever loses its `timeout=`, plus a mirror-parity pin. Reporter suites green: mri 41, ultrasound 41, prompt-preservation 13) | **P1 — NEEDS live verify (start an AI report, pull the network mid-call → a clean error bubble within ~3 min, not an endless spinner)** |
| **OPT-34** | Reception REST hydration (reporting-physician names) gets **HTTP 404** from `http://81.16.117.196:8080` — the endpoint is not deployed / mis-configured on this server. Handled gracefully (`[reporter-hydration] phase=rest_error … 404 Client Error`, no crash, no freeze), but the REPORT column's physician name silently never hydrates against this centre | Reception API | Field logs 2026-07-13, ×4 | Not started — this is a **server/config** issue, not a client bug. `reception_api_config.json` base URL / endpoint path needs checking against what that server actually exposes | Low-Med (missing column data) | **Low** | Low | **NOT STARTED (config)** | **P3** |

| **OPT-35** | **STRUCTURAL: series identity is DERIVED 4× from mutable tab state instead of DECIDED once — the root of the whole multi-study bug family.** To show one series, the code independently re-answers *"which study does this display key belong to, and where do its bytes/rows live?"* at four stages (disk path, DB `study_pk`, cache key, render gate), each reading **tab-level** state (`import_folder_path` ~35 refs, `metadata_fixed['study_pk']` ~10 refs) as if it were **per-series** identity. Every multi-study patient with **colliding series numbers** finds a stage where the derivations disagree, and each time we added a guard: 48912 (disk path) → poison guard; 49836 (tab repoint) → `TAB-PATH-GUARD`; 50238 (**DB pk**) → `STUDY-PK-GUARD`; plus 48952/48296/48476/48101 → 5 more. **Nine flags now answer one question.** Guard #10 is predictable. The authority already exists (`_resolve_canonical_series_identity`, 20 refs) but is **incomplete** (no `study_pk`, no `series_path`) and its result is **discarded** rather than threaded | D (multi-study) / perf | The three live cases 48912 / 49836 / 50238 (§15); the 9-flag inventory; user directive 2026-07-14: *"the pipeline should be straightforward for showing the series and optimizing performance and speed"* + the standing rule *"route decisions through the ONE authority, not bespoke checks + flags"* | **PLANNED — `docs/plans/architecture/SERIES_IDENTITY_PIPELINE_UNIFICATION_2026-07-14.md`.** Resolve an immutable **`SeriesRef`** (`display_key, study_uid, study_pk, series_uid, series_number, series_path`) **ONCE** at `change_series`, built where series-info already lands (`_rebuild_multistudy_series_index`) so resolution is a **dict lookup, not a computation**; thread it through load → DB → cache → apply → render. Then no stage *computes* a study ⇒ the three bugs become **structurally impossible**, not guarded-against, and cache collisions on a shared series *number* vanish (key = the globally-unique `series_uid`). **Phase 0 = build + SHADOW-COMPARE only (additive, default-OFF, zero risk)** — it logs `[SERIESREF-SHADOW] mismatch` whenever the table disagrees with what the live pipeline actually used, i.e. it proves the design against production data **before** any consumer changes. Phases 1–4 migrate one stage at a time (each its own flag); Phase 5 retires a guard only after it has logged **zero firings** | High (kills the recurring class; also removes `exists()` probes + a DB round-trip + guard scans from the click→first-image path) | **Med** (most-guarded path in the app) — mitigated: every existing guard STAYS ON during migration and becomes the **free production regression detector** (a guard that fires after a phase ships = that phase is wrong); the fail-closed identity gate stays as the oracle (`SKIP` must remain 0); single-study must be **byte-identical**; per-phase kill switches | Med | **P0 + P1 + P2 SHIPPED default-on 2026-07-14.** NEW pure `PacsClient/utils/series_ref.py` (frozen `SeriesRef` + `build_series_ref_table` + `resolve_series_ref` + `shadow_compare`; stdlib only — no Qt/VTK/pydicom/**DB**). Wired into `_vc_load._load_single_series_on_demand`: **P0** `AIPACS_SERIESREF_SHADOW` builds the table (cached on the identity of `_server_series_info` ⇒ per-load resolution is an **O(1) dict lookup**, not a re-computation with `exists()` probes) and logs `[SERIESREF-SHADOW] mismatch` whenever the LEGACY derivation disagrees — the regression oracle, and a permanent production record of how often the old path *would have been* wrong; **P1** `AIPACS_SERIESREF_DISK` takes `study_path`/series number from the ref, but **only when the ref is AUTHORITATIVE** (`source` ∈ {entry, slot_fallback}) — a `derived` ref merely INFERS `SOURCE_PATH/<primary>/<key>`, which is WRONG for an externally-IMPORTED study outside SOURCE_PATH, so it is never acted on and **single-study tabs stay byte-identical**; **P2** `AIPACS_SERIESREF_DB` applies THE RULE — **`study_pk = pk_of(ref.study_uid)`** — which alone satisfies BOTH polarities that needed two opposing guards (a PLAIN key's entry carries `study_uid == primary` ⇒ 50238 fixed; an OFFSET key's carries its own study ⇒ 48101 preserved) and **never reads `metadata_fixed['study_pk']`, so it cannot be poisoned**. Identity traces now go through `_identity_log` → the **viewer channel** (app.log did not reliably capture viewer-module INFO — that is why the 49836 trace was invisible). The 9 legacy guards **stay ON as DETECTORS**: if the authority is right they are no-ops, and a guard/`[SERIESREF-*]` firing after this ships means the authority is wrong. Traps honoured: ZetaBoost digit key (C10 — `display_key` stays a digit string; the ref is NOT a composite cache key, so Phase 3 remains separate), C1 (`parse_series_number`, never `int()` a server field), C2 (synthetic 900001–999999 stays a PLAIN key), C3 (`"02"` stays `"02"`), C8 (both pk polarities), C11 (offset-key scheme unchanged) | **P1 — P0/P1/P2 shipped; P3 (cache re-key) + P4 (DM) + P5 (guard retirement) gated on live shadow output** |

| **OPT-42** | **Imported Enhanced-MR multi-frame series showed a scrambled/wrong frame — STALE L2 pixel cache from a pre-multiframe-fix build.** A single DICOM file with `NumberOfFrames>1` (Charles Walker MRI 2023, 14 series, 20–140 frames, SOP `…1.1.4.1`, per-frame WW/WL+RescaleSlope) shares ONE SOPInstanceUID across all N frames. A build BEFORE the `::f{frame_index}` cache-key suffix (added 2026-07-01, OPT-13/`fast-multiframe`) keyed the L2 disk pixel cache by the bare per-file key, so all N frames collided → frame 0 (an edge/ear slice) was stored and returned at EVERY scroll position, and it SURVIVED the code upgrade (the poisoned entries stayed on disk). Same "one authority, keyed by the globally-unique identity" principle as OPT-35 — here the decode-cache key must carry per-FRAME identity, not just per-file | G (decode/render) | user 2026-07-23: imported study "couldn't show the series correctly"; a noisy ear slice at position 12/26. Contact sheet proves the DATA is perfect (sagittal T1: ear→brain→ear); every cache layer (in-mem by slice `idx`, disk by `{path}\|decode-vN::f{k}`) is frame-aware in current code; `get_rendered_frame(k)` returns 26 distinct correct frames | **SHIPPED default-on 2026-07-23** (`lightweight_2d_pipeline.py`, plugin-mirrored, synced 417/417): bump `_FAST_DISK_CACHE_POLICY_TAG` `"decode-v4"`→`"decode-v5"`. The tag is part of every disk-cache key (`_disk_cache_decode_key` → `{path}\|{tag}`), so a v5 launch cannot READ any v4-poisoned entry → one-time re-decode → correct frames. Exactly the tag's purpose (WW/WL/MG-polarity bumps used it before). No behaviour change for single-frame series (byte-identical) | Med (clinical: wrong frame shown) | **Low** (tag bump = pure cache invalidation; re-decode is cheap; no decode/render/geometry logic touched) | Low | **VERIFIED offscreen + on the REAL study; NEEDS live re-open verify.** Proved on the real 320×320 series 1101: cold decode of all 14 series = 0 mismatches vs pydicom; write→read-back = 0 mismatches; `get_rendered_frame` = 26 distinct frames; live `viewer_diagnostics.log` shows correct `multiframe-expand slices=26`. Both disk caches physically cleared (`pixel_cache`, `zeta_boost`). The user's post-restart "still wrong" = their tab held stale in-memory state OR the restart predated the effective v5 — a CLEAN patient re-open (fresh per-tab pipeline reads the clean cache) is the remaining live gate. Guard `tests/code/viewer/test_fast_multiframe.py` +2 (v5 pin + behavioural no-cross-frame-cache-collision), 10 green. **PART 2 (2026-07-23, the "still missing frames while stacking/scrolling" follow-up): the BACKGROUND PREFETCH subprocess decoder is NOT frame-aware.** `_decode_into_cache` warms the cache via `decode_service.decode(file_path=…)` (subprocess, GIL isolation) which does `arr = arr[0]` for ANY `NumberOfFrames>1` file (no `frame_index` param), then caches that frame-0 under THIS frame's key — poisoning BOTH the in-memory `_pixel_cache[idx]` AND the L2 disk key (`::f{k}`), re-poisoning the disk cache the v5 tag just cleaned. So slow foreground scroll (in-process `_decode_slice`, frame-aware) is correct while fast scroll (surrogate + background subprocess warm) shows frame 0 / stale frames. **PROVEN**: with the subprocess available (as live), driving the real prefetch path over series 1101 poisoned **25 of 26 frames** (all→frame 0); guard on → **0**. FIX (`AIPACS_FAST_MULTIFRAME_SUBPROC_GUARD`, default-on): a multi-frame slice (`frame_index is not None`) forces the frame-aware in-process decode (~6 ms/frame uncompressed — cheap), mirroring the existing empty-photometric/MG subprocess bypasses. `=0` = legacy subprocess path. Guard test +2 (flag/source pin + behavioural: a stubbed frame-unaware service must NOT poison the cache) — 12 green. Mirror re-synced 417/417. **PART 3 (2026-07-24, comprehensive review): multi-frame GEOMETRY.** Enhanced files (all 14 *Charles Walker* series) leave top-level IPP/IOP/PixelSpacing EMPTY — geometry is in the Shared+Per-Frame Functional Groups — so the expansion gave every frame IPP=(0,0,0)/spacing=(1,1): measurements/overlay/reference-lines had no real geometry; MPR built a degenerate 1-slice volume. FIX (`AIPACS_FAST_MULTIFRAME_GEOMETRY` + `AIPACS_MPR_MULTIFRAME_GATE`, default-on): NEW pure `multiframe_geometry.py` reads per-frame IPP/IOP/spacing + classifies (spatial_volume/multi_dimensional/multi_stack/temporal/unknown); expansion stamps each frame's own geometry (single-frame + multi-file series byte-identical); MPR gate blocks a single multi-frame file with a classified message (standard series never gated). All 14 real series classified correctly; per-frame geometry matches pydicom (0.75/0.47/1.95 mm vs buggy 1.0). +9 pure geometry tests + FAST wiring/gate/RLE tests; viewer geometry/sync/drag suite 455 pass 0 new fails; mirror 418/418. STAGED: multi-frame→VTK volume BUILDER for real spatial-multi-frame MPR (VTK-domain, live-validate). Review `docs/reports/MULTIFRAME_DICOM_HANDLING_REVIEW_2026-07-24.md` | **P2 (parts 1–3 shipped default-on; needs live source-build verify; VTK volume builder staged)** |
| **OPT-38** | **Automatic incremental update system** — every release previously required building the full installer, transferring it to each center, and reinstalling by hand; the app had NO update detection, notification, delta download, restart, or rollback (the pre-existing update seam — `update_sources.json` + `update_feed.json` + `summarize_available_updates` + Settings UI — was manual-only and core update = download-the-full-installer) | Release / deployment infra | user request 2026-07-16 (decisions: host-agnostic static structure for up to 2 mirror sites; incremental + installer fallback; startup off-thread + manual check; notify → user starts) | **SHIPPED default-on 2026-07-16** — extends the existing seam, no fork: BUILD `generate_update_manifest.py` (file-level SHA-256 manifest of `stage/core` == `{app}`; content-addressed gzip store `files/<h2>/<sha>.gz` — only NEW hashes ever published; `engine/version.json` stamped into the payload) wired guarded into `publish_update_bundle` (`AIPACS_UPDATE_DELTA_PUBLISH`); feed core entry gains additive `delta{manifest_path,manifest_sha256,files_base,compression}` + `size/required/min_version/release_notes*`; PUBLISH `publish_update.py` syncs to N site roots (mirror merge); WEBSITE `website_update_service/` static skeleton (.htaccess/web.config; feed = availability API); CLIENT `modules/auto_update/` (pure `manifest`/`client`/`apply` + Qt `service`/`ui`): startup check delayed+off-thread (`AIPACS_AUTO_UPDATE_CHECK` — frozen-only default, dev quiet; delay `AIPACS_UPDATE_CHECK_DELAY_S`=20), multi-source failover (active first), notify dialog → user-consented download (per-file sha256 verify, resume, progress, retries), staged mirror tree, PowerShell helper apply (waits-never-kills exit 2 on timeout; backup→copy-with-retry; ANY failure = automatic restore + relaunch old exe exit 3; best-effort ProgramData version stamp; relaunch), boot reconcile (`engine/version.json`→runtime_profile) + health marker + staging/backup prune (keep 2), `rollback_update.ps1` kept per backup; Settings core Apply routes to delta flow (installer fallback preserved) + startup-check checkbox; logs `user_data/logs/auto_update.log` + helper apply logs | High (deployment reliability: centers get fixes without manual reinstall; delta ≪ full package) | **Low-Med** (additive: no `delta` in feed ⇒ byte-identical legacy installer path; helper writes ONLY manifest-listed `engine/**`+top-level-file paths — path guard at generator+client+helper ⇒ `User Data`/`%APPDATA%` config/center settings untouchable BY CONSTRUCTION; consent-gated; kill switches per layer) | Med | **IMPL-VERIFIED offscreen** (56/56 new guard tests `tests/code/auto_update/` incl. an offline end-to-end delta cycle + tamper/corruption aborts + helper-script safety pins; builder/runtime/module_system suites: 100 passed, 6 pre-existing `test_nuitka_arm64_parity` fails = committed-state drift, untouched by this work — confirmed via `git status`). Tests caught+fixed a real Windows CRLF hash-mismatch bug (`dump_manifest` → exact bytes). NEEDS live verify: real vN→vN+1 cycle on an installed build (design doc §10 checklist) | **P1 (needs live verify + first published release)** |

| **OPT-48** | **Standard MPR open is SLOW at high slice counts** (not a crash — pure latency). Measured 2026-08-01 on patient 52827 series 202, **512×512×672** CT (352 MB): open = **~21 s wall / `[MPR-OPEN-KPI] standard_mpr_construct_ms=17944`**, main thread blocked **19.3 s + 10.8 s**. ~8 serial GUI-thread costs that each scale with slice count | MPR | `[MPR-STEP]` per-step split + F11 stall stacks (see `docs/reports/MPR_SLOW_HIGH_SLICE_COUNT_52827_2026-08-01.md`) | **Analysed, not yet fixed.** Split: `vtkImageFlip.Update()` **3.3 s** (`widget.py:134` — a full SECOND 352 MB volume copy just to mirror X), `GetScalarRange()` **1.5 s** (`widget.py:149`, full-volume scan), `QVTKRenderWindowInteractor()`+`winId()` **4.5 s**, `vtkRenderer`/`AddRenderer` 2.4 s, `Initialize()` **2.7 s** (first GL + 352 MB upload), crosshairs/text 1.2 s, then the deferred 3D VRT **~9 s** (mapper + `Render()`×3 — `AIPACS_MPR_DEFER_3D` moved it after the 2D panes but it still blocks the GUI). Volume LOAD itself is 2.2 s and already off-thread ✅. OPT-47's `_heavy` path engaged correctly (no crash) | High (30 s frozen window on a routine large CT) | Fix-dependent: #2/#4/#5 Low, #1 Med (geometry — needs L/R golden compare) | Med | **ANALYSED — ranked fix list ready** (1: fold the X-flip into the direction matrix/camera instead of `vtkImageFlip` = −3.3 s and −352 MB peak; 2: compute scalar range off-thread/from tags = −1.5 s; 3: lazy sag/cor panes; 4: build the 3D VRT on demand = −9 s off the open path; 5: progress feedback; 6: down-sample VRT input >400 slices) | **P1** |

| **OPT-49** | **MPR/VTK LIFECYCLE — no re-entrancy guard, deferred callbacks reachable during teardown, and teardown left the object graph alive.** Requested review of initialization / threading / memory / shutdown for high-slice-count studies, with two must-be-stable scenarios: (A) large study → MPR → close → use another viewer, (B) MPR open/close ×2 → another patient → another reconstruction | MPR | Full audit vs the requested 10-step teardown contract (`docs/reports/MPR_VTK_LIFECYCLE_REVIEW_2026-08-01.md`) | **SHIPPED default-on 2026-08-01.** THREE defects. **(1) `toggle_zeta_mpr` had NO re-entrancy guard** (grep for `_mpr_opening|_mpr_busy|_mpr_in_progress|reentr|already_opening` = 0 matches). Reachable despite the modal dialogs because they PUMP the event loop and because the open is called programmatically by the EchoMind command bus / agent-control surface — a second entry built a SECOND complete pipeline (2 volumes, 2 worker pairs, 2 render windows) on top of the first. FIX `_mpr_open_in_progress`, placed AFTER the close branch (close must never be blockable) and released in a `finally` (a stuck flag would kill the button for the session). **(2) Deferred callbacks could reach VTK DURING teardown**: `_request_render`/`_execute_pending_renders`/`_render_immediately`/`_apply_interaction_update` were guarded only by `view_name in self.viewers`, which starts protecting only after `viewers.clear()` at the END of cleanup — in between, a queued callback finds live entries + a render window whose graphics resources are already released. The `try/except` around `_apply_interaction_update` catches NOTHING there: the fault is native inside VTK. FIX `_mpr_closed = True` as the FIRST statement of `cleanup()` + `_mpr_is_closed()` early-return in all five entry points. **(3) Teardown left the object graph alive**: OPT-47 cleared only `self.viewers` — `text_actors`, `crosshair_actors`, `_view_containers` (a QWidget pins its whole parent chain), `_vtk_widget_to_view`, `_toolbar_styles`, `_render_pending`, `_diag` and `_viewport_activate_cb` (a closure over the ToolbarManager + host cell) were never cleared, and `_interaction_timer` was never stopped (its slot walks `self.viewers` and renders ⇒ stale callback into a finalized window). FIX new step 7 in `cleanup()` inside the existing `AIPACS_MPR_FULL_TEARDOWN` switch: clear all 6 containers, drop both cross-module refs, stop **+ disconnect + null** all 3 timers (stopping alone is not enough — `_request_render` can restart a stopped timer) | High (scenario B was monotonic memory growth; scenario A was a live use-after-free window) | **Low** (teardown + guards only; no geometry/camera/render-path change — 2 tests mechanically forbid every geometry setter and `ResetCamera` in the added code) | Low | **IMPL-VERIFIED offscreen**: new `tests/code/viewer/test_mpr_lifecycle_guard.py` (34) + `tests/code/viewer` & `tests/code/system` **2331 passed, 0 new failures** (4 remaining `test_local_search_progressive` fails proven PRE-EXISTING by stashing all 4 edits and re-running on clean HEAD); mirrors 420/420 (none of the 4 files is mirrored). Two pre-existing tests REPAIRED not weakened (`test_mpr_interaction_perf` stub gained `_mpr_is_closed`; `test_cleanup_clears_pending_flag`'s 600-char source window widened to 3000 + now also pins ordering). NEEDS live verify: scenarios A/B with RSS watched across cycles, rapid double-click on the MPR button (must log `[MPR-LIFECYCLE] open ignored`), and close-during-load / close-tab-with-MPR-open | **P1 (needs live verify)** |

| **OPT-50** | **LOCAL PATIENT LIST IS O(N²) ON THE GUI THREAD — fine at 200 studies, unusable past ~2000.** OPT-43 (2026-07-24) made the list *paint* early (first 20 rows) but did not remove any per-row cost, so the background streamer still pays the whole quadratic bill while the user is trying to work. FOUR independent costs, measured, not guessed: **(1)** `add_patient_data`'s per-study dedup scanned EVERY existing row for EVERY insert → **1 999 000** `item()`+`.text()` calls at 2000 rows; **(2)** TWO SQLite connections **per row** — `check_patient_visited`→`find_patient_pk` and `_resolve_imported_on`→`get_imported_at_map([one_uid])` (a fresh study is always a memo miss) = **4000** connections; **(3)** `_finalize_bulk_insert_ui` runs after EVERY 40-row batch (~50×) and each time does a FULL-table `apply_anti_aliasing_to_table` (N×C `setFont`, each emitting `dataChanged` → **832 000** cells), a full `_programmatic_sort` whose restore pass calls `_extract_row_data` (~30 `item()` lookups) on every row, and an O(N) `_update_results_count`; **(4)** the Assign/Report columns re-read TWO JSON stores **three times per row** (`ino_assignment_server_state._load` **6.7 s / 2400 calls** at 800 rows = half the whole render) and `report_status_for_reception` scans the entire table once per row. Plus `render_one` did 1–3 blocking `stat`/`opendir` calls per row on the GUI thread. **BONUS BUG**: the per-batch sort ran only when NO user sort was active, so with a saved sort (the user's config has `active_sort_col=15`) every background-streamed row was appended **UNSORTED at the bottom** — "sort by Imported Date" silently covered only the first 20 rows | Home / patient list | user 2026-08-03: "Local patient list still too slow >2000 studies — loading, filters, search, sort by Imported Date, re-render; UI freezes"; profiled with `tests/bench/bench_local_patient_list.py` (new) | **SHIPPED default-on 2026-08-03**, six independent kill switches. **(1)** `AIPACS_LIST_UID_INDEX` — a study_uid presence SET; the row scan runs only for a genuine duplicate. Safe by asymmetry: a False is authoritative (never inserted ⇒ the scan would have found nothing), a True only means "go scan", so a stale set can never create a duplicate. Rebuilt (not emptied) in both `clear_table` paths because a clear KEEPS pinned rows. **(2)** `AIPACS_LIST_DB_PREFETCH` — new `dicom_db.get_existing_patient_ids()` (chunked at 500) + the existing `get_imported_at_map`, both run ONCE on the worker in `search_local`, then `prime_visited_patient_ids` / `prime_imported_on_cache` seed the widget; misses are primed as `""` so a study with no stamp does not re-query. Un-primed callers keep the legacy per-row DB lookup. **(3)** `AIPACS_LIST_BATCH_FINALIZE` — while a stream is in flight, anti-alias only the NEW row range (new `font_manager.apply_anti_aliasing_to_rows`; a non-growing refresh still gets the full pass), skip the count (the progressive label replaces it anyway), and debounce the sort into ONE `_on_stream_settled` pass 140 ms after the last batch — which sorts by the **ACTIVE** column, fixing the bonus bug. **(4)** `AIPACS_INO_STORE_CACHE` — mtime+size-guarded read caches in `ino_assignment_server_state._load`, `ino_assignment_history.read_all` and `ino_assignment._config`; explicit invalidation on write, copies handed out so no caller can poison them. Also fewer open handles on `server_state.json`, which is exactly what its `os.replace` fights with on Windows. **(5)** `AIPACS_LIST_REPORT_MEMO` — `report_status_for_reception` answered from a memo armed for the render pass only (`load_progressive` → `_on_stream_settled`/`clear_table`); reproduces the scan exactly (`setdefault` keeps the first row; an empty scan is never cached; a miss still scans). **(6)** `AIPACS_LIST_PATHS_OFFTHREAD` — the disk resolution lifted verbatim into module-level `_resolve_renderable_study_path`, run on the worker for the first page before paint and for the tail in the background; `render_one` falls back to resolving inline for any row the worker has not reached, so the optimisation is never a precondition. Plus five new SQLite indexes (`studies.patient_fk` — the LEFT JOIN key — `study_date`, `imported_at`, `modality`, `patients.patient_name`), and `_programmatic_sort` now reads one field per row via the new `_row_study_uid` instead of building a ~30-lookup dict | High (the list is the app's front door; this is the difference between "usable" and "unusable" on a real clinic database) | **Low** — every change is either a memo/cache with an exact invalidation, a scan the code can still fall back to, or an index. No column, row, widget, overlay, sidebar or clinical field is added or removed; the FAST/Advanced/VTK domains are untouched; six independent kill switches restore the old path piece by piece | Low | **IMPL-VERIFIED offscreen.** New `tests/code/ui_services/test_local_list_render_opt50.py` (46) + `tests/bench/bench_local_patient_list.py`. Directly-affected `tests/code/ui_services` = **662 tests, 2 failures, BOTH proven pre-existing** (`test_status_flags_are_stashed_on_the_widget_to_avoid_recompute` and `test_login_carries_the_user_identity_ids` — the first was proven by extracting the same source window from `git show HEAD` and getting the identical offset 2272 > its 1500-char window, i.e. a stale guard, not a regression). Three progressive tests were REPAIRED not weakened (the test double gained the real `_begin_report_status_memo`, borrowed from the class so it cannot drift). **Bench @2000 studies: full load 42.7 s → 13.9 s (3.1×), worst GUI block 1139 ms → 271 ms (4.2×), first paint 285 ms → 114 ms, db_calls 4000 → 1, dedup-scan rows 1 999 000 → 0, anti-alias cells 832 000 → 32 000** | **P1 — NEEDS live verify on the real >2000-study database** |

| **OPT-52** | **CLINICAL-CORRECTNESS: Eagle Eye combined MLO with CC — `str(None)` is the truthy literal `'None'`, so every MG series of a NULL-named study shared ONE pairing bucket.** The `series` table stores `series_name` as NULL for studies whose rows were written without a folder-derived name; `image_io.load_series_preview` loads series metadata DB-first (`get_series_by_series_pk`, image_io.py:3573), so `metadata['series']['series_name']` is `None` **with the key present**. Six call sites read it as `str(series_info.get('series_name', ''))` — and `str(None) == 'None'`, which is **truthy**, so `_rebuild_series_index`'s `if series_name:` guard **passed** and produced `_paired_series_map == {'None': ['2','4','6','8']}` for PID 52795's four MG series (R-CC / L-CC / R-MLO / L-MLO, one image each, distinct Series+SOP UIDs). `_vc_switch.py:1446` then hit that key, took **the first other number in the bucket**, and attached it as `vtk_image_data_2`; the MG-modality gate could not help because all four ARE MG. `_vw_series.py:1199` therefore built `CustomCombineImageViewers`, whose `get_count_of_slices()` returns `Z1+Z2 = 2` (the bogus **"1 / 2"** counter) and whose `set_slice(1)` calls `change_local_series('series_2')` — **scrolling the MLO viewport displayed the CC image.** Three further sites (`_vc_layout.py:757`, `_pw_viewers.py:397`, `_pw_series.py:150,692`) had the same defect via a bare `==`, where `None == None` and `'None' == 'None'` are both True. **The DICOM data was never at fault** — series grouping, view-position metadata and Series/SOP-UID grouping are all correct | Eagle Eye / viewer pairing | user 2026-08-04 (screenshot + patient code); traced end-to-end against the live DB and the user's own `viewer_diagnostics.log` (`bind_source=switch_series_combined`, `Combined: True`, partner fetch of series 2 into the series-4 viewport) | **SHIPPED default-on 2026-08-04**, one kill switch. New shared `PacsClient/utils/series_pairing.py`: `normalize_series_name()` collapses `None`/`'None'`/`''`/whitespace/`'null'`/`'nan'`/`'unknown'`/`'n/a'`/`'-'` to `''` ("no pairing key"); `can_pair_series_names(a,b)` is True only when both carry the **same non-empty real** name, replacing the bare `==`. Applied at six sites: `_vc_backend` (pairing key normalised — the flat metadata cache deliberately keeps the RAW value, and `_series_number_to_index` is untouched), `_vc_switch` + `_vc_warmup` (`series_pair_key` for the map lookup, raw name kept for logging), `_vc_layout`, `_pw_viewers`, `_pw_series` ×2. Studies with a genuine shared `series_name` still pair and still open the combined viewer unchanged | **High** — a mammography viewport was showing a *different view's* image on scroll, and reporting a 2-slice stack where the DICOM has one image | **Low** — pure predicate tightening at the pairing key; no viewer, overlay, camera, geometry, metadata, sidebar or clinical field touched; the MG gate, `allow_paired`, flat cache and fast index all unchanged; single kill switch restores byte-equivalent legacy behaviour | Low | **IMPL-VERIFIED.** New `tests/code/viewer/test_mg_series_pairing_guard.py` (**33 passed**). **End-to-end against the LIVE database** (`_recovery/probe_pair_map_52795.py`): guard ON → `_paired_series_map = {}`; guard OFF → `{'None': ['2','4','6','8']}` — the legacy run **reproduces the defect exactly**, proving both the diagnosis and that the kill switch is a real revert path. `_series_number_to_index` identical in both runs. Regression: **`tests/code/viewer` 2099 passed**, 28 skipped, 51 xfailed, 0 new failures; `tests/code/ui_services` 707 passed / 2 failed, both the known PRE-EXISTING stale positional guards | **P1 — NEEDS live verify: PID 52795 MLO must read `1 / 1`, scrolling must never show CC, and a study that legitimately uses paired MG series must still combine** |

| **OPT-53** | **RELIABILITY: module installation was checkbox-deep — "installed" meant "files copied", not "verified runnable", and a freshly installed module still refused to open.** Field bug 2026-08-22: AiPacs Chat icon + Settings visible (they ship in the core engine) but opening it said "not installed or not enabled" — one string for THREE distinct causes (package absent from the workstation profile, module disabled in the registry, module's own flag OFF — the shipped template is force-OFF by `config_sanitizer.py`, and nothing turned it on after an install). Older installs (pre-8/19 installer or delta-updated engines) additionally lack `aipacs_chat` in `installation_profile.json` entirely → `is_module_enabled` = False with no recovery hint | Module install/update pipeline (`aipacs_runtime.py`, installer, Settings ▸ Installation) | user 2026-08-22 comprehensive module-architecture review request; live inspection of `C:\ProgramData\AIPacs\config\installation_profile.json` (no `aipacs_chat` key) + the tri-condition gate `aipacs_chat_available()` | **SHIPPED 2026-08-22.** ONE pipeline for every channel (installer bootstrap / Settings package/folder/URL / update feed) via `install_module_package()`: sha256 enforcement (feed hash now checked), zip-slip guard, POST-INSTALL VERIFICATION (`validate_module_installation` = catalog `requires` dependencies with NAMED "cannot start because…" messages + healthcheck) — failure ⇒ `install_incomplete` + warning + module disabled, never "success"; catalog `feature_flag` spec auto-enables the module's own toggle after a VERIFIED install (aipacs_chat opted in; identity declares its flag read-only for dependency checks); `_package_record` preserves failure statuses; Settings table gained a Status column + warning tooltips; `aipacs_chat_unavailable_reason()` names the exact failing condition in the open-dialog; dedicated `<User Data>/logs/module_install.log` | High (every optional-module install; the "icon works, module doesn't" class) | **Low** — additive verification/logging around the existing pipeline; no loader rearchitecture; bundled_unlock engine-code model unchanged | Low | New `tests/code/runtime/test_module_install_verification.py` (7) + `tests/code/aipacs_chat/test_unavailable_reason.py` (8); targeted suites 51 + builder/aipacs_chat/settings_ui 295 passed, 0 new failures (6 pre-existing Nuitka-parity reds, empty `git diff` on their targets) | **P1 — STAGED, deliberately NOT done: physical code separation for `bundled_unlock` modules (code ships in the core PYZ and is only registry-locked when unselected; true separation = per-module PYZ exclusion + payload-only import, needs dedicated live-build testing)** |

| **OPT-54** | **LOCAL MODE WAS NOT OFFLINE:** Local single-click/open crossed into live PACS reconciliation, grouped thumbnail fetch, viewer cache-miss fetch, existing-tab forced refresh, and previous-exam socket calls. Advanced Search also discarded multi-ID/body-part/age/physician criteria. | Home Local search/preview/open + patient viewer + SQLite | User 2026-08-29: disconnecting the network made Local thumbnails/search/open unreliable; code-path audit reproduced five independent remote leaks and lossy advanced mapping. | **SHIPPED default-offline 2026-08-29.** `AIPACS_LOCALDB_AUTO_SERVER_SYNC` now defaults `0` (`=1` explicitly restores background growth sync); all Local preview/open cache misses resolve through SQLite + canonical disk thumbnails with metadata placeholders; viewer cache miss returns before socket import; local multi-study preview no longer requires a selected server; normal Server mode and manual Refresh/Sync retain remote behavior. SQLite adds `studies.reporting_physician` via idempotent migration, persists validated online physician hydration for later offline reuse, and supports bounded multi-ID, normalized acquisition/import date, multi-valued modality, body-part, DICOM-age, and physician combinations. | High reliability/availability | **Low-Med** — mode gates and read fallbacks; one additive nullable column; no DICOM pixel, geometry, or viewer-domain changes | Med | **11 guards failed pre-fix; 26 focused tests passed after implementation/review; 309 broader related database/storage/UI/viewer/thumbnail tests passed; py_compile green.** | **P1 — source-build cable-disconnect live verify required** |

**Audit reconciliation — `CLINICAL_SERIES_IDENTITY_TARGET_AUDIT_2026-07-05.md` (7 findings mapped, no separate plan):**
- **#1** (bare-number viewer caches) → **RESOLVED** = **OPT-17** (`AIPACS_CACHE_STUDY_IDENTITY`, shipped 07-05). Live-verify in **N-1**.
- **#2** (duplicate SeriesInstanceUID repoints study_fk) → **OPEN, highest value** = **OPT-18**. Cheap config-default flip; do in **N-2** (low-risk hygiene/config), guard-tested, per-flag.
- **#3/#4/#5** (drag payload, DM bare-number degrade, completeness-probe resolver) → **OPEN, Low** = **OPT-19**, **P3** robustness; fold each into the file it lives in when that area is next touched (drop path / DM adapter / view-intent). #5 is partly done (`_DM_CANON_IDENTITY`).
- **#6** (reception `study_uid` ≠ on-disk StudyInstanceUID, case 48101) → **Info, already instrumented** (`[PREV-EXAM-UID]`); worst case = previous exam *fails to render*, never wrong images. Track under **OPT-07** (previous-exam / DICOMized-document identity), not a new item.
- **#7** (identity gate + poison guard NEEDS-LIVE-VERIFY) → **largely DISCHARGED 2026-07-05**: both live-ran green in the pre-publish gate (gate 26+ evals / 0 wrong-study stomps; poison-guard tests green; app clean) and their flags were retired to unconditional. Any *formal multi-scenario* pass folds into **N-1**.

**Net:** one new **P1** action (**OPT-18**, a config default), one **P3** robustness cluster (**OPT-19**); everything else is resolved or verification debt folded into N-1. No new plan — all seven findings live inside this backlog + the existing N-1/N-2 staging.

---

## 10. Next safe optimization phase (Deliverable 9)

**Principle:** do not start with the largest/most invasive item (OPT-04). Start with high-value, safe,
easily-validated work that cannot damage working systems. The next phase is **verification + low-risk
hygiene**, which also *earns the evidence* required to safely attempt OPT-04.

---

### ▶ PHASE N+1 (2026-07-14) — THE CURRENT PLAN. *(The "Phase N" block below is the 07-03 plan, kept
### for history; N-1's Seam A/B verification is folded into V-1 here.)*

**The situation has changed shape.** A large amount of code shipped default-on in the last ten days
and **almost none of it is live-verified**. The single biggest risk to this project is no longer an
unfixed bug — it is **an unverified fix pile**. Writing more code before draining it is how a
regression gets buried.

**V — VERIFICATION DEBT (do this FIRST; no new code).** Every item below is shipped, default-on,
guard-tested, and unproven on a real build. Each has an exact acceptance signal.

| # | Item | Live acceptance signal |
|---|---|---|
| **V-1** | **OPT-35** SeriesRef authority (P0/P1/P2) | Open **50238**, **49836**, **48912** + a **single-study** patient. Require: `[SERIESREF-SHADOW] mismatch` = **0**, `[IDENTITY-GATE] SKIP` = **0**, every guard firing = 0, single-study shows **zero** `[SERIESREF]` redirects. *(Partially done: two live patients already returned a clean oracle.)* |
| **V-2** | **OPT-36** drop-never-abandoned | Drag a previous-exam series the instant its study starts downloading → the loading GIF **persists**, images appear **without a re-drag**, no intermediate revert to the previous image. And the 47084 livelock must still settle once the series IS displayed. |
| **V-3** | **OPT-37** thumbnail refresh | Click **50264**'s study while it is still receiving images → within ~10 s the resync re-checks (`study_resync_check result=grew`) and the thumbnails refresh **without changing the search filter**. |
| **V-4** | **OPT-28/29/30/31** (the laptop/field cluster) | Pull the network → search → restore → recovers silently. 45+ rows + active download + two back-to-back searches → **no crash**. Sync with the network down → tab **stays open** with Retry and the study is **NOT** marked approved. |
| **V-5** | **OPT-25** (Roshana) / **OPT-21** (PC2 WoA) / **OPT-24** (DM outage re-arm) | Roshana: the radiography study downloads + displays. PC2: MPR opens (hardware D3D12, not llvmpipe). DM: >5 min outage → studies re-arm on reconnect. |

**Rule: no new optimization work starts until V-1…V-4 have run at least once.** A clean V-1 is
*also* the gate that unlocks OPT-35 P3–P5.

> **⚠ The V-lane is currently a MANUAL checklist, and that is itself the problem.** See the companion
> **`docs/plans/QUALITY_AND_VALIDATION_ROADMAP_2026-07-14.md`** — it measures the test suite (566 files,
> but the full run **does not complete**, ~68 permanently-red tests, **zero** GUI tests, **no coverage
> tooling**) and shows that **none of the last 10 user-facing bugs was catchable by any existing test**.
> Its Phase Q1 turns V-1…V-5 into **automated scenario scripts** driven by the control MCP and asserted
> against the log-oracle set — which pays off this verification debt *and* creates the permanent
> live-regression lane. **Do the roadmap's Q0 (repair the instrument) before trusting any regression
> result, including mine.**

**S — STRUCTURAL (only after V).** In priority order:
- **S-1 · OPT-35 P3 — cache/switch re-key by `series_uid`.** This is **no longer theoretical**: the
  50264 live run showed 3 × `[IDENTITY-GATE] SKIP`, and the trace pins them on the **switch path's
  bare-series-number metadata lookup** (a secondary series' metadata carries its RAW number, so `"3"`
  can return the sibling study's entry; the incoming study_uid is empty, so OPT-17's cache check
  **fails open** and only the fail-closed `series_uid` gate catches it). The gate is currently the
  ONLY thing standing between that and a wrong image. ⚠ **ZetaBoost warmup hard-requires a digit key**
  (`isdigit()`/`int(sn)`) ⇒ `display_key` stays the public handle; `series_uid` is the *internal* key.
- **S-2 · OPT-35 P4/P5** — DM/grow-lane onto the ref, then **retire the 9 identity flags → 1**, one at
  a time, each only after logging zero firings. This is the flag-debt payment.
- **S-3 · OPT-37 residual** — the GROUPED (multi-study) render path still has **no independent
  staleness check**; it depends entirely on the resync firing `force_server_merge=True`. **Extend the
  resync — do NOT fork a second refresh mechanism.**
- **S-4 · OPT-04, re-scoped** — DM **completion convergence** only (216× `not in download_rows` →
  re-download loop). It is *not* the display-bug cause; that theory is retired.
- **S-5 · OPT-07** — DICOMized-document handling (`1100000`, `[APPLY-ENTER]=0` — the apply never runs).

**G — STANDING GUARDS (not tasks; enforce on every new feature).**
- **No blocking work on the GUI thread** — no folder walk, DICOM read, network call, or engine
  construction. This class has now produced OPT-22 (21 s), OPT-23, OPT-27 (55 s) *after* the plan
  declared main-thread blocking "resolved". Known remaining offenders: the Advanced/VTK
  `ImageViewer2D`+`Render()` per switch (GUI-thread-inherent → spinner only), the AI-seg
  `on_contour_closed → requests.post` sync POST (**should move off-thread**), and Eagle Eye's eager
  `ModelTrainingTab` construction (**lazy-build it**).
- **A stop-condition must never double as a success signal** (OPT-36).
- **Throttle what is settled; re-check what is not** (OPT-37).
- **Route decisions through the ONE authority, not bespoke checks + flags** (OPT-35).

**External / not ours:** OPT-32 (server-side `(study_date)` index; the client A/B probe already proved
the cost is a server scan), OPT-34 (reception REST 404 = server config), and the `limit: 100` patient-
list truncation.

---

### Phase N (2026-07-03, HISTORICAL) — three parallel, low-blast-radius workstreams

**N-1 — Live-verify what already shipped (OPT-02, OPT-03, OPT-13).** No new code.
- *Exact problem:* Seam A/B cutovers and cine are default-on but unverified on a live source build.
- *Code path:* `_hp_search.py` (Seam A), `home_download_service.py` (Seam B), the FAST cine engine.
- *Why unresolved:* shipped 07-03 as a test build; the reporting PC run is the acceptance step.
- *Method:* on the reporting workstation, with fresh logs, follow the deploy record's post-deploy plan —
  open multi-study / previous-exam patients on a poor link; confirm `[LIFECYCLE] …->thumbs_ready`,
  `[LIFECYCLE-CUTOVER] rendered token-stale ACTIVE` (rapid A→B→A), `seam_b watchdog kept alive`, rising
  `watchdog_grow`, and previous-exam series finishing **without a second drag**.
- *Must not change:* nothing — verification only.
- *Instrumentation:* the shipped `[LIFECYCLE*]` markers + the KPI analyzer.
- *Acceptance:* invariants 1–4 (§12.3) hold across ≥100 patients incl. several previous-exam cases;
  zero reopens, zero second-drags; no wrong-study display; stalls not worse than the 07-03 baseline.
- *Rollback:* `AIPACS_LIFECYCLE_THUMBS_ACTIVE=0` / `AIPACS_LIFECYCLE_GROW_ACTIVE=0` → byte-identical
  legacy; keep the prior installer available.

**N-2 — Low-risk config + hygiene + doc reconciliation (OPT-18, OPT-14; OPT-09 shipped 07-05).** Near-zero clinical risk.
- **OPT-18 (audit #2) — DB owner enforcement (highest-value remaining):** flip `AIPACS_DB_ENFORCE_OWNER`
  default `"0"`→`"1"` for clinical builds in `database/dicom_db.py` so a duplicate SeriesInstanceUID across
  studies is BLOCKED (metadata-only refresh) instead of silently repointing `study_fk`. The enforce path
  + `[CrossStudyReassignment]` logging already exist; this is a one-line default change. *Method:* flip the
  default, run `tests/code/download_manager/test_multistudy_identity_guards.py`, then a live pass watching
  for `[CrossStudyReassignment]` (should be rare/absent on conformant data). *Rollback:*
  `AIPACS_DB_ENFORCE_OWNER=0` restores observe-only. Do this FIRST in N-2 (cheap, isolation-critical).
- *Exact problem (OPT-09, now shipped):* `download_diagnostics.log` is ~99% WARNING (17 k lines) burying 13 real socket
  errors; a single 13 MB log record is a main-thread write hazard; `CLAUDE.md` cites retired flags and a
  wrong `AIPACS_DENTAL_VTK_MPR` default.
- *Code path:* the log formatter / `log_stage_timing` channel; `diagnostic_logging.py`; `CLAUDE.md`.
- *Why unresolved:* never scheduled; low urgency vs reliability.
- *Proposed correction:* move download stage-timing/progress telemetry from WARNING to an INFO/diag
  channel; add a byte-length cap in the formatter (truncate + flag oversized records); throttle repeat
  `FAST_GEOMETRY_ORDER_MISMATCH` to once/series; correct the `CLAUDE.md` flag notes.
- *Why safe:* changes log routing/formatting only; preserves every useful marker (stall probe, stage
  timing, `[KPI]`, `VIEWPORT_LIFECYCLE`).
- *Must not change:* the diagnostic markers themselves, or `dicom.db`.
- *Acceptance:* no log file ≥90% WARNING; no single record > ~256 KB; the 13 real errors visible; guard
  test on a fixture log.
- *Rollback:* revert the formatter/routing change; docs are text-only.

**N-3 — Subprocess spawn hardening (OPT-05).** Contained stability fix.
- *Exact problem:* `access violation` while pickling args to spawn the download subprocess
  (`download_process_worker.py:148` → `popen_spawn_win32 → reduction.dump`).
- *Why unresolved:* intermittent; surfaced only in the 07-02 review's `native_fault.log`.
- *Proposed correction:* audit exactly what is pickled into the child; ensure only picklable, fully-
  constructed data crosses; guard the spawn against racing teardown; confirm the pre-warm note does not
  spawn during teardown.
- *Why safe:* touches only the spawn arg construction/guard, not the download protocol or disk writes.
- *Acceptance:* no `native_fault.log` access violation across a stress session of repeated
  open/download/close; download throughput unchanged.
- *Rollback:* revert the guard; behavior returns to prior spawn.

**Only after N-1 passes** do we attempt **OPT-01** (broaden off-thread work — the amplifier) and then the
decomposed **OPT-04** cutover. OPT-01 is sequenced first because §3.4/§6.7 of the reliability review make
clear that even a perfect state machine "feels broken behind a 48 s freeze" — removing the amplifier is a
prerequisite for the cutover to show its value.

### OPT-04 decomposition (when reached — never one change)

1. Thumbnail sidebar renders from the model (kills Problem #1; smallest blast radius) — shadow-agreement
   gate first, then cut over.
2. DM adapter re-keyed to canonical `(study_uid, orig_series, series_uid)` (previous-exam first-class;
   delete the `sn is None` drop + sibling lane) — this *is* OPT-06.
3. Convergence sweep on a worker replaces `_dl_watchdog_tick` + resume + grow-to-disk; delete the flag
   quartet. Each sub-step independently live-verifiable and reversible.

---

## 11. Risk classification (Deliverable 5 support)

- **LOW** (do freely, guard-tested): OPT-09 log hygiene, OPT-14 doc reconciliation, OPT-16 CPU/GPU
  sampling, most single-flag collapses (OPT-11), the N-1 verification (no code).
- **MEDIUM** (staged, kill switch, fresh-log review): OPT-01 off-thread moves (touch guarded thumbnail/
  multistudy/patient-table paths — honor canonical-path/memory-first/offset-key/gating invariants),
  OPT-05 subprocess spawn, OPT-12 startup defer, OPT-03/OPT-02 already-shipped verification.
- **HIGH** (decompose into observable, reversible sub-phases; never one change): OPT-04 lifecycle
  cutover, OPT-08 dental geometry default flip (clinical-lane golden compare), OPT-10 geometry T2/T3 (DB
  metadata feeds every render — golden-compare before any flip). High-risk items **must not** ship as a
  single large change.

---

## 12. Current bottleneck assessment (Deliverable 8)

1. **Main-thread blocking (H) is the #1 bottleneck and the amplifier of every reliability race.**
   Synchronous manifest disk-walk + per-study DB status on the GUI thread; stalls to 48 s on the loaded
   machine. Everything else (drag lag, dropped fetches, missed grows) is downstream of it. → OPT-01.
2. **Notification-not-convergence completion (B/C/D)** is the #1 *reliability* defect. → OPT-02/03/04.
3. **Not bottlenecks (leave alone):** decode, render/frame, scroll, layout-switch, memory (RSS ~930 MB
   stable). Spending effort here is wasted — the months of decode/render work targeted the wrong path.
4. **Secondary stability risks:** subprocess spawn AV (OPT-05); log bloat obscuring faults (OPT-09);
   dental geometry divergence from the default-OFF VTK-MPR flag (OPT-08).

### 12.3 Determinism invariants (the acceptance bar for reliability, not "usually works")

From the lifecycle log, any run must satisfy:
1. `count(SELECTED) == count(DISPLAYED_COMPLETE) + count(THUMBS_READY[preview]) + count(FAILED[explicit])` — no study vanishes.
2. Every `right_panel_socket_start` has a terminal (`done|error|empty`) — **zero silent drops**.
3. Every `SERIES_LOADING` reaches `FIRST_IMAGE` then `DISPLAYED_COMPLETE` — **zero permanent `awaiting`**.
4. `DISPLAYED_COMPLETE` viewport slice count == canonical on-disk count — **no partial grow**.
5. No state entered twice for one identity — no duplicate execution.

**Added 2026-07-14 — the invariants the last ten days actually broke.** These are *standing rules for
every new feature*, not backlog items; each is written from a defect that shipped past the five above.

6. **No blocking work on the GUI thread.** No folder walk, DICOM read, network call, or engine
   construction. Violations *after* main-thread blocking was declared "resolved": OPT-22 (Chromium
   prewarm, **21 s**), OPT-23 (EchoMind inline dispatch), OPT-27 (Eagle Eye scanning 53 k DICOM,
   **55 s**). None came from the pipeline this plan was written about — the class travels with new
   features.
7. **A stop-condition must never double as a success signal.** OPT-36: the resume watchdog's
   "settled" test cleared the awaiting flag, hid the spinner and emitted `ViewportLoadSucceeded` for
   a viewport that had **never displayed the awaited series** — silently abandoning the user's drop
   back to the previous image. A viewport may be declared settled **only when it is actually showing
   the awaited series**.
8. **Throttle what is settled; re-check what is not.** OPT-37: a flat 5-minute TTL on the *change
   detector* was applied to a study the previous check had just found INCOMPLETE — exactly the study
   that will change, throttled for exactly the window in which it changes.
9. **Identity is resolved ONCE and threaded, never re-derived from mutable state.** OPT-35: it was
   re-derived at four stages from `import_folder_path` / `metadata_fixed['study_pk']`, producing
   48912 / 49836 / 50238 and **nine flags answering one question**.
10. **Before adding a mechanism, check whether the existing one is being suppressed.** Three of the
    four defects fixed on 2026-07-14 were correct machinery gated off by a too-coarse guard.

---

## 13. Permanent KPI framework & current baseline (Deliverable 10)

**Source of truth:** `docs/performance/FAST_VIEWER_KPI_CATALOG.md` + `CURRENT_KPIS_v2.3.6.md`.
**Analyzer:** `tools/performance/kpi_session_report.py` (run after every phase, from fresh logs).
Reliability KPIs rank **equal to** speed KPIs — the target is *deterministic behavior across repeated
runs*, never "usually works."

### 13.1 Performance KPIs (baseline = 2026-07-01 authoritative session)

| KPI | Marker | Baseline p50 / p95 / max | Target | Verdict |
|---|---|---|---|---|
| DICOM decode | `[KPI] decode_ms` | 4.5 / 9.4 / 12.0 ms | low | ✅ |
| Time to first image | `[KPI] TTFI total_ms` | 18.8 / 93.2 / 114.4 ms | < 80 ms | ✅ p50 |
| Render frame | `FAST_SET_SLICE_STAGE frame_ms` | 16.1 / 28.7 / 39.2 ms | ~1 frame | ✅ |
| Layout switch → 1st image | `VIEWER_SWITCH total_ms` | 18.8 / 93.2 / 114.4 ms | < 80 ms | ✅ |
| **Drag event interval** | `FAST_DRAG_KPI event_p95_ms` | 157.7 / 454.8 / 725.2 ms | **< 120 ms** | ❌ |
| **Drag UI lag** | `FAST_DRAG_KPI ui_lag_max_ms` | 216.3 / 943.2 / 1054.6 ms | **< 200 ms** | ❌ |
| **Main-thread stalls** | `MAIN_THREAD_STALL stall_duration_ms` | 175.5 / 548.5 / 1421.2 ms; 63 > 100 ms / 20 min | **0 during interaction** | ❌ |
| Process RSS | `rss_mb` | ~930 MB stable | bounded | ✅ |
| CPU / GPU | — | not sampled | — | ⛔ gap (OPT-16) |

**Reporting-PC reference (worst observed, 2026-07-02):** main-thread stalls **10,105** ≥100 ms, p99
1,243 ms, **max 48,387 ms**, 23 ≥5 s. Local control same-code: 741 stalls, max 9,684 ms. The gap between
these two on identical code *is* the 80/20.

**Current-run spot check (2026-07-03 `viewer_diagnostics.log`):** drag `event_p95` sample p50 ≈ 95 ms,
max ≈ 840 ms (n=346) — tail still elevated (OPT-01 open). `MAIN_THREAD_STALL` count 0 in the current
`app.log`/`viewer_diagnostics.log`, but the stall-trace flags (`AIPACS_MAIN_THREAD_TRACE`) are default-OFF
and the probe may not have emitted this run → **treat as "not measured," not "improved."** Re-run the
analyzer with the probe enabled to refresh this baseline (fresh-log discipline, §14).

### 13.2 Reliability KPIs (the equal-weight half)

| Reliability KPI | Marker / source | Target |
|---|---|---|
| Thumbnail completion success rate | socket_start → terminal; full-set render | **100%**, zero silent drops |
| Viewport grow-up success rate | `SERIES_LOADING → DISPLAYED_COMPLETE` | **100%** on first drag |
| Patient-open success rate | `SELECTED → DISPLAYED_COMPLETE/THUMBS_READY` | **100%**, zero manual reopen |
| Silent-drop count | 29 unaccounted (07-02) | **0** |
| Lost grow notifications | 200 `GROW-LANE-TRACE resolved=None` | **0** |
| Duplicate execution | double-spelled traces; re-entered pipeline | **0** |
| Determinism under injected stall | §12.3 invariants with vs without stalls | identical (latency may rise) |

---

## 14. Fresh-log discipline (Deliverable 9 / Phase 9)

Historical logs explain *past* failures; **current** decisions use fresh logs from the current build.
Do not let resolved problems dominate the plan. After each implementation phase:

1. Rotate/clear the relevant dev logs (`user_data/logs/`).
2. Run a defined scenario (source build; multi-study + previous-exam patients; the `aipacs-control` MCP
   harness where possible for repeatability).
3. Run `tools/performance/kpi_session_report.py` on the fresh logs.
4. Compare the KPI panel + reliability invariants to the §13 baseline.
5. Confirm no regression (viewer/geometry/isolation guard suites green).
6. **Update this document** (§9 states, §13 baseline, §15 history).

Two testing lanes (see `docs/for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md`): the **verify lane**
(offscreen pytest in the sandbox — pure/Qt-offscreen, pre-merge gate) and the **clinical lane** (Windows
source build — the only lane that proves GUI/render/clinical behavior; human-assisted bootstrap default).

---

## 15. Validation & regression history (living log)

**2026-09-18, OPT-56 / Total Spine SAM:** verified immutable-runtime reuse,
changed-file revalidation, cancellation and no cache after failed/changing seals
in `test_total_spine_assist.py`. Real SAM weights executed through the owned
subprocess; synthetic repeated-prompt times were 36.85 s then 17.38 s (warm disk),
separate from the earlier 284.92 s cold full-service run. No source application
was launched or restarted; test-control ping was unavailable. See
[`EAGLE_EYE_TOTAL_SPINE_ALIGNMENT.md`](modules/EAGLE_EYE_TOTAL_SPINE_ALIGNMENT.md)
for feature tests, model provenance and remaining acceptance.

| Date | Change | KPI/reliability before | After | Regression check | Result |
|---|---|---|---|---|---|
| 2026-09-19 | OPT-58 / OPT-60 inactive patient-tab thumbnail ownership | Cold 23-series Local verification ran 18.475 s while the next indexed 66-series grouped sidebar took 9.169 s and kept applying hidden-tab cards after a third patient opened; one synchronous card trace write sampled at 428.3 ms under overlap | Existing Local worker and qasync sidebar now share the authoritative patient-tab active lifecycle: pause at bounded worker/UI boundaries, retain generation/order/identity and resume in place; close/supersession cancellation unchanged. Intermediate INFO progress is card 1/every tenth plus exact terminal summary; paused native lifetime is rechecked every 50 ms | Four fail-before guards; Local/sidebar 66 passed; adjacent inactive-result/signal/lifecycle 64 passed, direct exit 0 | Code verified; fresh normal-source rapid A -> B -> C single/multi-study KPI and visual acceptance OPEN. Rollback `AIPACS_PATIENT_THUMBNAIL_VISIBILITY_GATE=0`; no Viewer/VTK/decode/download protocol/cache format change |
| 2026-09-19 | OPT-58 / OPT-60 indexed-Local read amplification | Warm indexed cases still launched a whole-patient raw warm: 2,398 files / 596.2 MB / 9.843 s and 508 files / 133.2 MB / 5.397 s, overlapping catalog and first-image work | Known Local paths are catalog-owned and excluded from the patient-open raw warmer; no empty Local warm thread starts and a failed Local catalog lookup remains fail-closed. Server/unknown behavior is unchanged. The authoritative durable layer remains the revision-bound DB summary written by Import/Download; the bounded per-file disk cache remains only a cold-scan accelerator | Three behavioral guards failed before and pass after; 24 warmer tests; combined producer/index/Local/download/open boundary 150 passed / 1 unavailable-symlink skip | Code verified, fresh normal-source single/multi-study KPI and visual acceptance OPEN. Narrow rollback `AIPACS_LOCAL_INDEXED_FILE_WARM=1`; no Viewer/VTK/decode or download transport change |
| 2026-09-17 | OPT-58 / OPT-60 10:49 normal-source log review | Home GUI QPixmap read previously stalled 1274 ms | Four Home preparation markers, no sampled Home read stack; patient tabs deliver 27/65 and grouped 39 cards; max patient-work gap 684.3 ms | Read-only scoped logs; prior code tests separate. Largest remaining sample is patient Local stream get_bytes/read_bytes, not Home | Positive Home execution evidence, not full visual/stress closure. Six-series zero-file paths require availability/mapping verification; cold header admission and Local image preparation remain open |
| 2026-09-17 | OPT-58 / OPT-60 Home image preparation | 1274 ms GUI gap in Home QPixmap file read | Detached worker QImage preparation, same GUI scheduler/actions, two ready progressive images and cancelled stale generations | Two fail-before renderer guards; 23 new cases; 214 adjacent + 24 panel/effect passes; 467 mirror pairs match | Code verified; fresh normal-source GUI/KPI pending. No cold DICOM, cache-policy or Viewer change |
| 2026-09-17 | OPT-58 / OPT-60 10:03 source acceptance review | Warm grouped 39-series metadata formerly 24.096 s; first Advanced Render formerly 13.209 s | Same primary-study/39-series workload metadata 2.011 s; first Advanced Render 40.747 ms. Cold 43-series admission still 22.336 s to stream completion; 66-series grouped 12.834 s to all cards | 125 direct focused passes; synthetic 141-card entry 0.76 ms, maximum apply 11.41 ms. Human workflow plus scoped logs; no new runtime changes | Sampled improvement, not complete closure. Cold header scans, cache read/validation and Home GUI QPixmap I/O remain; detailed 10:03 receipt in UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md |
| 2026-09-17 | OPT-58 / OPT-60 Local enumeration cost | 13.439 s enumeration despite 2398 persisted hits / zero probes | Retain directory-entry type facts; preserve fresh version validation and sorted membership; split cache path/read timings | Two cost guards fail before; 192 redundant classification stats become zero; 334 expanded passes / 1 unavailable-symlink skip, exit 0 | Code verified; fresh-source grouped/single GUI and wall-time KPI OPEN. No complete catalog-first or crash closure |
| 2026-09-17 | OPT-58 / OPT-60 single-study Local inventory owner | 54/66/130 inventory calls for 27/33/65 series; overlapping worker wait, not twice actual header reads | Remove redundant Home setup aggregation and stale snapshot push only for single-study Local; preserve existing stream, grouped and Server contracts | 4 fail-before / 6 pass-before; 10 new guards, 113 focused and 321 expanded passes, exit 0 | Code verified; fresh-source GUI and matched latency OPEN. Cold classification and grouped full-catalog barrier remain |
| 2026-09-17 | OPT-58 / OPT-60 Local pixel-fact persistence | Two Local grouped metadata pushes take 6.570 / 27.004 s, all 2398 / 2412 files reprobed | Same inventory authority reuses positive, version/age-checked facts across restart; bounded central cache, fresh enumeration, no thumbnail-presence side effect | Four original behavioral failures plus one intermediate-placement failure; 32 new synthetic cases; 425 focused passes / 1 deselection / exit 0; 467 mirrors match | Code verified; fresh-source GUI and matched cold/warm KPI OPEN. First uncached scan still required; no crash, download or installed closure |
| 2026-09-17 | OPT-58 / OPT-60 ordered Local inventory owner | Intermediate fact-primer preserved 6.950-13.707 s cold catalog times because producer and consumer interleaved | One ordered Home/patient resolver; bounded file parallelism and bounded pending queue only inside current exact series; warmer delegates known unverified Local directories. The September 19 follow-up also delegates producer-indexed Local rows; Server/unknown fallback remains raw-warm | New fail-before 4 failed / 44 passed; 50 direct and 129 projection-boundary passes; wider selection 1,295 passed / 2 skips / 3 quarantined xfails, with two unrelated baseline assertions red | Code verified; fresh single/multi-study first-card/full-catalog, exact-card, no-jump, Server and native-crash GUI gates OPEN. Rollback `AIPACS_LOCAL_ORDERED_INVENTORY=0`; indexed-Local rollback documented in the September 19 row |
| 2026-09-14 | OPT-60 card-owned effect retirement | Old Ready/hide callbacks overwrite newer state; cleanup skips animation stop; manager retirement leaves effects running | Two reusable native-owned timers, parented progress animation, terminal effect cleanup invoked before manager map release; preserve native snapshot and stop priority animations | 7 corrected baseline failures / 1 pass; 2 additional transition failures corrected; 14 final Qt guards; 441 adjacent passes / 1 existing skip, exit 0; 462 mirrors match | Default-on, code PASS. Source GUI pending fresh launch; 20:41 run predates this edit. No native-crash, completion or performance closure |
| 2026-09-14 | OPT-60 manager-owned callback retirement | Pending progress survived reset; old same-key cards dispatched after replacement; no terminal manager disposal before owner teardown | Parented cancellable generation-scoped timers; reset clears pending work; idempotent dispose releases owner/state; patient and weak Home registry call it without deleting native cards | 7 initial failures; 2 additional Home integration failures; final native-deletion guard exposed and corrected invalid-resource teardown; 17 final guards; 424 adjacent passes / 1 existing skip, exit 0; 462 mirrors match | Code PASS, default-on; fresh source GUI blocked on bootstrap. Card-owned animations, native-crash causation, performance and installed acceptance remain separate |
| 2026-09-14 | OPT-60 same-identity small refresh swap | Deferred immediate refresh first emptied the panel | Retire actions immediately; preserve only identical known action sets, replace during paint suppression; failure allows retry | 3 baseline failures; additional preparation-failure guard caught a first-implementation gap; 16 final guards; 390 expanded passes / 1 existing skip; 17 separate import/overlay passes; 462 mirrors match | Default-on, live blocked; not full Unify or native-crash closure |
| 2026-09-14 | OPT-60 Home render owner retirement | Clear retained progressive manager/card wrappers; action closure retained or addressed a deleted panel | Release retired render reference; weak panel action with validity/token guards before queue and delivery | 4 failures before; 10 final guards; 374 adjacent passes / 1 existing GUI skip, exit 0; 462 mirrors match | Fresh-source live pending; no generic disposal or crash/performance claim |
| 2026-09-14 | OPT-60 patient-tab external signal lifetime | Capturing priority/completion closures retained deleted wrappers and delivered into closed tabs | Patient-owned weak-reference QObject relay; exact routing/filter preserved; idempotent per-connection disposal before teardown | 6 failures before; 16 final guards; 364 adjacent passes / 1 existing GUI skip, exit 0; 462 mirrors match | Sampled 17:57 open/close/reopen live PASS; real completion/priority pending; not full manager disposal or a crash/performance claim |
| 2026-09-14 | OPT-60 search-owned preview retirement | Search removed rows but retained old preview/selection producers; advanced stale clear and old task cleanup could affect newer owners | Shared guarded search clear; identity-preserving pins and pending row remap; explicit retirement; ownership-safe cancellation cleanup | 7 main fail-before cases and 2 cleanup failures; 18 final new guards; 302 adjacent passes, exit 0; 462 mirrors match | Sampled Server/Local live PASS; extended matrix pending. No decoder/download/installed/full-Unify claim |
| 2026-09-14 | OPT-60 queued Home-render retirement | Clear allowed deferred starts/retries or late ticks to rebuild retired content; context-free callbacks outlived the Qt panel | Clear-owned generation invalidation, explicit retry generation, Qt-context single shots and parented progressive timer | 9 failed / 4 passed before; 16 final lifecycle guards; 197 adjacent passes, exit 0; 462 mirrors match | Code-verified; sampled 15:39 replacement/open passed. Empty-search caller follow-up recorded above; no full disposal or installed-acceptance claim |
| 2026-09-14 | OPT-35/OPT-60 existing-tab Home click cutover | Cards emitted ordinal strings; dead handler did not reach a viewer; same-PNG coalescing could retain another action identity | Frozen UID action, render-token rejection, unique destination-owned key resolution and normal viewer handoff; old direct click body removed | 4 behavioral failures + 7 absent-API failures before; 4 identity-signature failures before prerequisite; final 238 passed plus 1 stateful test, exit 0; 462 mirrors match | Automated only; Home drag/retry, full signature/scheduling, completion, live and installed gates remain open |
| 2026-09-14 | OPT-60 Home card metadata prerequisite | Both render schedules discarded supplied UID/path/UI-key/frame facts; synthetic Qt cine card displayed 2 instead of 420 | Existing projection preserves only supplied identity/count fields; object count remains 2, visible count is 420 | 4 failures and 4 passes before; all 8 new guards pass after; focused suite 205 passed, exit 0; 462 mirrors match | Automated-verified only; no action-routing, semantic-refresh, performance or installed-runtime acceptance claim |
| 2026-08-31 | OPT-55 Eagle Eye bounded same-slab focus-window backfill | Two focuses retained only 4 of 5 available slices; 20 new guard failures | Both now retain 5 slices, true four-slice slab stays at 4; 5 total images; 8,046,336 pixels and 4,546,578 bytes within unchanged caps; anchors, sagittal sampling, overview bytes, and 57 original files unchanged | V2/V3 63 passed; AI Imaging 643 passed, 8 existing xfailed; core-build inclusion 3 passed; 458 mirror pairs matched; private offline replay 3.03 s with outbound connections denied | Code/offline verified; no paid model call, build, or deployment. Live diagnostic benefit remains unverified. Details: V3 research plan section 16 and Eagle Eye LLM stage-2 document section 29 |
| 2026-08-31 | OPT-55 additive bilateral sagittal experiment; adjacent scoped scorer correction | Three-slice focus row omits lateral planes available in overview; root contact suppressed by negated deviation | Opt-in supplement mode preserves all 4 base images/captions and adds 2 sheets, 7 planes each, approximately +/-14.4 mm; 6 images / 9,361,152 pixels / 4,897,937 bytes, within unchanged caps. Saved root contact scores under, not miss; 57 original files unchanged | Parasagittal 18 passed; scorer 25 passed; complete AI Imaging 675 passed, 8 existing xfailed; core inclusion 3 passed; 458 mirror pairs matched. Network-disabled replay: 2.551 s experimental, 2.852 s baseline (single observations, not speed comparison) | No model call, build, default promotion, or accuracy claim. New mode manifest 1.4.0; ordinary V3 stays 1.3.0. Full benchmark repair/reference adjudication and controlled clinical trials remain pending. Details: Eagle Eye stage-2 section 30 and V3 research section 16 |
| 2026-08-31 | OPT-55 level identity, padding-only headroom, coverage visibility; scorer 1.2.0 | A uniform one-level shift passed monotonicity; padding used 99.92% of pixel cap; scorer missed participles and misattributed recess grades | Review-required audit preserves raw report without relabeling. All 5 base images and 21 supplemental anatomical tile contents retained; 60 originals unchanged. Pixels 11,990,784 to 11,253,504; bytes 5,890,397 to 5,881,762. Image cap remains 8/8; coverage exclusions become visible | Initial 22 failed/43 passed; self-review reproduced 5 map-parser and 2 subarticular-location failures before correction. Final focused 19 + 26 + 35; AI Imaging/core inclusion 732 passed, 8 existing xfailed; 462 mirror pairs matched. Network-disabled replay 3.735 s (one observation) | No model call, app launch, build, default promotion, or clinical claim. Supplement manifest 1.5.0; base V3 unchanged. Full Phase 0, frozen-input E1/E2, and clinical acceptance remain pending. See Eagle Eye stage-2 section 31 |
| 2026-09-01 | OPT-55 explicit sagittal/axial plane identity | A multi-level sagittal crop had a single focus title but no visible link to paired AX frames, enabling a neighboring disc to be read under the title; contribution to the observed clinical error was not assumed | Manifest 1.6.0 places a DICOM-derived locator duplicate only in the existing spare cell. Shared Frame of Reference and every-source-plane affine validation fail closed; seven clean tiles and 8-image/11,253,504-pixel package stay unchanged. Offline bytes 5,880,276 to 6,055,847; no UID serialized | Initial availability guard failed with exit 1. New locator suite 32 passed. Full AI Imaging/default-build 810 passed, 8 existing xfailed, exit 0; 462 mirror pairs matched. Offline selected-input reconstruction 4.2 s, three locators included, all non-locator pixels byte/pixel identical | No app/model call, installer build, benchmark or accuracy claim. Ordinary V3/layout bypass unchanged. Clinical and repeated frozen-input evaluation pending. Details: Eagle Eye stage-2 section 35 |
| 2026-08-29 | OPT-54 Local hard-offline boundary + complete Local advanced filters | Local cache misses and patient open could enter socket timeouts; advanced Local silently ignored 4 filter families | Local DB/disk authority, placeholder series cards, no automatic PACS access; all advanced criteria preserved | 11 failures on pre-fix code → 26 focused passes after review; 309 broader related passes; isolated temp DB; py_compile green | ✅ offscreen; live cable-disconnect validation pending |
| 2026-08-29 | OPT-43 Imported Date reversed-range hardening | Custom `From > To` silently returned zero rows | Dialog + repository order the bounds; Local query uses a half-open next-day upper bound while preserving immutable first-import semantics | 2 failures pre-fix → 2 passes; broader Imported Date/Imported On/Advanced/Local-list/DB gate 94 passed | ✅ offscreen; live Advanced Search date-picker verification pending |
| 2026-08-29 | OPT-54 follow-up: Local multi-study patient-tab handoff | Home cache hits were healthy, but a two-study Local open never requested patient-viewer thumbnails because the grouped renderer received no series map | The background Local handoff now aggregates every resolved study from SQLite/disk and initializes the grouped patient-tab sidebar; Server behavior is unchanged | New guard failed before implementation; Local offline contract 7 passed | ✅ offscreen; source-build re-open of the reported Local multi-study patient pending |
| 2026-08-30 | OPT-35/OPT-42/OPT-54 follow-up: imported duplicate-SeriesNumber mixed still/cine display | Import grouped by UID but Local used a suffixed storage folder as a drag handle; viewport rejected nonnumeric keys. Incomplete DB metadata also classified six colour stills as grayscale multi-frame arrays (`Rows x Columns x 3` → `Columns x 3`) and reduced two cine objects / 424 frames to two slices | Added deterministic digit-only `display_key` aliases while retaining raw SeriesNumber, exact `folder_key`/`series_path`, and a separate `SeriesRef.storage_key`; Local card inventory distinguishes objects from frames; FAST refreshes colour facts from the dataset and expands every object of a legacy-metadata cine after a first-object probe; header stubs now preserve the missing facts | Four behavioral guards failed before implementation and pass after; affected source data: 25/25 still shapes correct, 2 objects expand to 424/424 frames, edge cine frames decode correctly; plugin mirror synced/verified | ✅ live-verified in the source build on 2026-08-30 for the reported Local still/cine display workflow; explicit cable-disconnect, re-import, packaged-runtime, and broader comparison gates remain separate |
| 2026-08-30 | OPT-35 follow-up: Local cached-card identity leak after duplicate-series fix | The synchronous cache pass ran before the authoritative Local projection and used canonical PNG stems as display handles. `1_2` escaped from storage identity and Python converted it to Series 12 during FAST drop; the early Series 1 card also won deduplication and hid the projected 25-object count | In Local workflow, preserve cached-thumbnail control flow by counting the inventory but create no card until SQLite/disk projection supplies `display_key`, `folder_key`, counts, and path together. Harden FAST custom-MIME parsing with decimal-digit validation before `int()` | Two focused behavioral guards were red before implementation (`show_exist_thumbnails` called once; `1_2` parsed as 12) and green afterward. Remote/server startup behavior is unchanged; no persisted cache naming or DICOM data changes | ✅ live-verified in the source build on 2026-08-30: the prior still series again reports/displays 25 images and the duplicate-number cine series also displays correctly |
| 2026-07-01 | KPI Phase 0 analyzer + flag registry | fragmented scratch scripts | one report generator + thresholds | guard test on fixture | ✅ read-only |
| 2026-07-01 | P1.1 async thumbnail save | `save_thumbnail` in stall traces | absent from traces (pid 193028) | offscreen + live | ✅ |
| 2026-07-01 | P1.2 chunked status refresh | `refresh_download_statuses` stalls | cooperative chunk, no threads | offscreen | ✅ |
| 2026-07-01 | P1.3 chunked sidebar build | single-study build stall | progressive build | source-build visual | ✅ |
| 2026-07-02 | Lifecycle pure core (additive) | n/a | 15 invariant tests green | offscreen | ✅ additive, no runtime change |
| 2026-07-03 | Shadow + Seam A/B cutovers + failure tap (default-on) | 80/20 flakiness | model holds parked data; seams active | 359 pass/1 skip (3 pre-existing unrelated); live sanam max stall 4.8 s | ✅ gate PASSED; **live cutover verify pending** |
| 2026-07-03 | OPT-01 status-refresh dicom-only trim (`AIPACS_STATUS_REFRESH_DICOM_ONLY`, default-on) | per-row `os.walk`(attachments)+2 DB queries on GUI thread each refresh | only `dicom` flag re-read; attachment/DB flags kept cached | py_compile OK; 13 offscreen tests green (`test_status_refresh_dicom_only` + sibling P1.2); no test pins old behavior | ✅ offscreen; **live-verify pending** (fresh probe run). Report: `docs/reports/OPT-01_STATUS_REFRESH_DICOM_ONLY_2026-07-03.md` |
| 2026-07-03 | OPT-01 **live-verified** via probe run (`AIPACS_MAIN_THREAD_TRACE=1`, session `sess-4e53e3d33995`, pid 38204) | 07-01 baseline: 63 stalls/20 min, status-refresh + `build_local_manifest` in stall stacks | run: **35 stalls, p50 200 / p95 1023 / max ~3140 ms**; status-refresh / `_compute_local_status_flags` / attachment-`os.walk` / manifest = **ABSENT from all traces** (0 lines) — `TABLE_REFRESH` correlation now coincidental (stacks prove it) | 0 errors from the changed functions; lifecycle shadow active (`grow_lane_drop`=116, `watchdog_grow`=24) | ✅ **OPT-01 status path validated.** New top freezes shifted to STARTUP: `apply_theme`/`_apply_field_styling` (~2.3 s), `add_AIPacs_tab`/`_wrap_home_tripane_in_splitter` (~1.3 s), thumbnail-widget build (~0.3 s) → OPT-12/P1.4 |
| 2026-07-03 | OPT-01 startup theme dedup (`AIPACS_THEME_APPLY_DEDUP`, default-on) | `PatientSearchWidget.apply_theme` re-styled 11 fields × ~15 `setStyleSheet` several times/launch (~2.3 s startup stall) | idempotent skip of identical-theme re-apply | py_compile OK; 20 offscreen tests green (`test_theme_apply_dedup` + OPT-01 + P1.2) | ✅ offscreen; **live-verify pending** (re-run probe → `apply_theme` should drop from startup traces). Report: `docs/reports/OPT-01_THEME_APPLY_DEDUP_2026-07-03.md` |
| 2026-07-04 | **Reliability/clinical: wrong-study load fix** (`AIPACS_PRIMARY_SERIES_POISON_GUARD`, default-on) | patient 48912: loading previous-exam 29694 series 4 then current series 4 re-displayed the PREVIOUS study's series 4 (log: `rebind_to_series=1000004`, `open_series path=<previous>/4`) | plain (<1M) key now re-resolves to its own primary `study_uid` folder when a poisoned tab path (previous-exam study) collides on the same series number | py_compile OK; 7 offscreen tests green (`test_primary_series_poison_guard`); pre-existing PySide6-missing errors in sibling tests unrelated | ✅ **LIVE-VERIFIED on 48912 (2026-07-04, user-confirmed)** — current series 4 now loads from the current study. HIGH severity (cross-study display). Kill switch RETAINED (clinical fix; collapse deferred until more clinical mileage). Deeper audit: the guard is the primary key's counterpart to the existing offset-key fallback (`_vc_load.py:476`); resolver now symmetric. Report: `docs/reports/WRONG_STUDY_PRIMARY_SERIES_AFTER_PREVIOUS_EXAM_2026-07-04.md` |
| 2026-07-04 | OPT-01 control-panel theme dedup (`AIPacs_ui.apply_theme`, shared flag `AIPACS_THEME_APPLY_DEDUP`) | `AIPacs_ui.apply_theme` ~1.4 s startup stall (3rd theme layer; restyles shell + cascades to child widgets) | idempotent skip of identical-theme re-apply (children self-dedup) | py_compile OK; 23 startup/theme/OPT-01 tests + 4 startup-subtiming tests green; `test_apply_theme_call_preserved` still passes | ✅ offscreen; **live-verify pending** (next probe run → `AIPacs_ui.apply_theme` should drop from startup traces) |
| 2026-07-04 | OPT-01 startup fixes **LIVE-VERIFIED** (fresh run `sess-71efc2d063b8`, pid 318112, 84-min session) | apply_modern_styling ~2.3 s, _update_license_info ~1.7 s, _apply_field_styling ~2.3 s, _compute_local_status_flags in startup traces | **ALL FOUR = 0 occurrences** in stall traces (gone). Render healthy: frame p50 17.9/p95 31 ms, TTFI p50 22.8 ms. **Decode cache 100% hit (5560/0).** | no regression | ✅ **startup theme + license + status-refresh fixes confirmed eliminated.** Remaining: stack-drag ui_lag p50 255/p95 849 ms (main-thread contention, not render); NEW targets: `AIPacs_ui.apply_theme` ~1.4 s (another theme layer — same dedup), a 5.9 s + 2.4 s generic `main.py:notify` stall (GC/subprocess-spawn? needs deeper trace; note a 1.4 s `linecache/tokenize` is the trace mechanism itself, not a real app stall) |
| 2026-07-03 | OPT-01 during-use **re-validated** on a later fresh run (`sess-edc3b36c2070`, pid 306988, 23:51–23:53, terminal capture) | — | only **4 main-thread stalls in ~2 min, max 355 ms, 0 ≥1 s**; series 6/16/17/18/19/20 grew 96/96 smoothly | GetReportStatus timeout (report column only, non-blocking) | ✅ during-use rock-solid. NOTE: startup-trace confirmation of increment-3 (mainwindow theme + license defer) still pending a clean-log capture — the sandbox FUSE mount served a STALE cached copy of the big log (showed 22:48 while the app ran at 23:53); use a cleared/backed-up log or read the terminal capture, not the mounted file |
| 2026-07-03 | OPT-01 startup **live-verified (increment 2)** + increment 3 shipped (probe `sess-2f9be9ca545a`, pid 315304) | patient-search `_apply_field_styling` = 2264 ms freeze | `_apply_field_styling` **ABSENT from traces** (theme dedup worked); during-use KPIs healthy (decode p50<1 ms, TTFI p50 43 ms, **drag p95 266 ms** vs 725 baseline). New top startup freezes: `apply_modern_styling` ~2.3 s, `_update_license_info` ~1.7 s, `setupUi` ~1.3 s | — | ✅ increment-2 validated; increments 3 = mainwindow theme dedup (`AIPACS_THEME_APPLY_DEDUP`) + license defer (`AIPACS_DEFER_LICENSE_INFO`), 27 offscreen tests green, **live-verify pending**. Report: `docs/reports/OPT-01_STARTUP_FREEZES_2026-07-03.md` |
| 2026-07-04 | **Reliability/clinical: viewport study-identity gate** (`AIPACS_VIEWPORT_STUDY_IDENTITY_GATE` + `AIPACS_STAMP_SERIES_STUDY_UID`, default-on) | 48912/48952: requesting a CURRENT series rendered the same-numbered PREVIOUS exam (`change_series(4)` → `first_image_visible 1000004`); the previous series is stored in the DB under the CURRENT study_uid so study signals falsely matched | each viewport is stamped with its intended series identity (`_vc_switch`); the FAST render choke point `qt_fast_container._start_qt_viewer` skips a render whose **series_uid** (DB-corruption-proof) ≠ the intended one; metadata now also carries server-canonical study_uid/series_uid | 3 files AST-OK; 13 offscreen tests green (`test_viewport_study_identity_gate`) | ✅ **LIVE-VERIFIED on a 2nd PC (2026-07-04, user-confirmed)** — all series show and switch without the previous-exam stomp. Deeper: DB has previous-exam rows under the wrong study_uid = separate data-integrity cleanup (deferred). Report: `docs/reports/MULTISTUDY_CURRENT_SERIES_DISPLAY_MISS_48952_2026-07-04.md` |
| 2026-07-04 | OPT-01 **`_is_study_downloaded` TTL cache + scandir** (`AIPACS_STUDY_DL_CHECK_CACHE`, TTL `AIPACS_STUDY_DL_CHECK_TTL_MS`=1500, default-on) | the manifest disk-walk amplifier (§5.H): `_is_study_downloaded` ran 1+N `iterdir()` per study per row on EVERY DM-progress status refresh → re-walked every study's folder many ×/s on the GUI thread (48 s stalls on reporting PC) | short-TTL cache collapses the repeated walks; invalidated the moment a study's status changes (`update_study_download_status`→`_invalidate_study_downloaded_cache`) so completion still flips promptly; check itself is a single `os.scandir` early-exit pass (behavior preserved) | full-file AST-OK; 12 offscreen tests green (`test_study_downloaded_cache`: TTL collapse, expiry re-walk, invalidation flip, kill-switch, + real-tree scandir semantics) | ✅ offscreen; **live-verify pending** (probe run on the reporting PC → status-refresh disk-walk stalls should drop). §5.H manifest-scan amplifier addressed |
| 2026-07-04 | OPT-01 **status expensive-flag TTL reuse** (`AIPACS_STATUS_EXPENSIVE_TTL`, TTL `_S`=30, **default OFF/opt-in**) | `_compute_local_status_flags` re-runs the attachment `os.walk` + case-of-day + printed DB queries per row whenever the 5 s `_local_status_cache` TTL expires on a status-widget rebuild | between the 5 s short TTL and a 30 s expensive TTL, refresh ONLY the cheap (now-cached) dicom flag and REUSE the expensive attachment/DB flags; those change only via viewer actions that return through a cache-clearing refresh | edit region verified well-formed (Read tool); **offscreen tests + full-file AST could NOT run** — sandbox FUSE mount served STALE/truncated copies this session (source capped at 301829 B / line 6429; test file showed pre-edit 12 tests) | ⏸️ **DEFAULT-OFF pending validation** — chosen because the freshness change (5 s→30 s for docs/voice/ai/case/printed chips during continuous list viewing) is unverified in-sandbox. Flip `=1` after confirming chips still update promptly on the viewer→list transition. Mechanism shipped; guard tests written (`test_study_downloaded_cache` expensive-TTL mirror). |
| 2026-07-04 | **OPT-01 LIVE-VERIFIED (during-use)** on fresh user run (23:46, sessions incl. `sess-9f940906f3a6`) | 07-01/reporting-PC amplifier: status-refresh disk-walk in stall stacks, 48 s max stall | **during-use max stall ≈247 ms (32 total, none >250 ms)**; `_is_study_downloaded`/`_compute_local_status_flags`/`iterdir` **absent from every stall trace**; decode 7.9 ms, TTFI 30.4 ms healthy. Remaining large stalls are ALL **startup** (t_since_start 2–13 s, interaction_active=False) | 0 regressions | ✅ **disk-walk amplifier resolved.** Next perf frontier = startup init (OPT-12/P1.4) + the generic `main.py:notify` multi-second startup stalls |
| 2026-07-04 | **OPT-09 log hygiene: download telemetry off WARNING** (`AIPACS_LOG_TELEMETRY_DOWNGRADE`, default-on) | download_diagnostics.log 2026-07-04: **36,663 WARNING vs 294 ERROR** — telemetry (`[BATCH_TRACE]`/`download-summary`/`series-summary`/`stage-timing`/`[NET_TIMING]`/`[KPI] TTFC`/`[SERIES_COMPLETE]`) emitted at WARNING to pass the download component threshold, burying real errors 125:1 | `TelemetryLevelDowngradeFilter` on the download handler AFTER the threshold gate relabels known-telemetry WARNING records → INFO (telemetry still captured; handler is DEBUG); genuine WARNING/ERROR untouched → `grep WARNING/ERROR` now surfaces only real problems | module imports clean; **7 offscreen tests green** (`test_telemetry_level_downgrade`: each telemetry prefix downgraded, real WARNING/ERROR untouched, kill-switch, mid-message non-match, source-pin filter ordering) | ✅ offscreen; contained to `diagnostic_logging.py` (no socket_client touch). **live-verify pending** (next run → download_diagnostics WARNING count should collapse to real warnings only). No 13 MB single-record hazard this run (longest line 3 KB) |
| 2026-07-05 | **OPT-12 startup: single-instance sweep cheap-name reuse** | STALL_TRACE (07-04) proved the startup freezes are NOT UI construction but `main.py:1189 try_acquire → _force_close_other_instances`: psutil `me.parents()` (277 ms sample) + `proc.name()`→`.exe()`/OpenProcess in the kill loop (**1320 ms sample** on a half-dead orphan) — the latter called ONLY to build a log-description string | store the cheap Toolhelp `(proc, name)` with each candidate; the kill loop reuses `cand_name` for the description instead of re-deriving via the slow `proc.name()`/`.exe()` path. Protect-set + kill/terminate logic byte-identical (dict still keyed by pid; `proc.ppid() in candidates` intact) | AST-OK; 4 offscreen source-pin tests green (`test_instance_sweep_cheap_name`); takeover behaviour still covered by `test_single_instance_takeover` | ✅ offscreen; **live-verify pending** (STALL_TRACE at `single_instance_lock.py:446` should vanish). **DEFERRED (medium-risk, next):** replace the repeated Windows `ppid_map()` rebuilds in `me.parents()`/`me.children(recursive=True)`/`proc.ppid()` with ONE ppid snapshot — touches the safety-critical protected-set (mis-computation could kill the launching terminal), so it needs a flag + live Windows validation, not a blind sandbox edit |
| 2026-07-05 | **OPT-12 LIVE-VERIFIED** (fresh trace run `sess-3d375cab2ef4`, 00:18) | `single_instance_lock.py:446` name()→exe() stall (1320 ms) | **`:446` GONE from all traces** (0 occurrences); remaining single-instance frames = `:387` (`me.parents()`) + `:449` (kill loop). During-use **max stall 173 ms (2 total)**, decode 7.1 ms, TTFI 36.8 ms — best yet. **No crash** (0 AV/faulthandler; OPT-05 did not reproduce) | 0 regressions | ✅ name-reuse confirmed. Remaining ~2.3 s **startup** stall (one-time, interaction_active=False) is the psutil `ppid_map()` rebuild in `me.parents()`/kill-loop → the deferred ppid-snapshot (safety-critical, flag-gated + Windows-validated). OPT-09 telemetry not exercised (no downloads this run) |
| 2026-07-05 | **OPT-12 fast instance sweep — ppid snapshot** (`AIPACS_FAST_INSTANCE_SWEEP`, **default OFF pending Windows validation**) | the residual ~2.3 s startup stall: `me.parents()` + `me.children(recursive=True)` + per-candidate `proc.ppid()` each rebuild the whole Windows parent map | the Toolhelp `PROCESSENTRY32W` already carries `th32ParentProcessID`, so ONE snapshot now yields (pid, name, ppid); pure `_protected_pids_from_snapshot(pid2ppid, self_pid)` computes self+ancestors+descendants via dict walks; the kill-loop top-level check reads the snapshot ppid. Legacy psutil path byte-identical when the flag is off; snapshot can only ever OVER-protect (skip a kill), never mis-protect a real target | AST/edit verified via Read tool; **pure protected-set logic exhaustively unit-tested** (ancestors, descendants, siblings excluded, cycle + ppid-0 guards, deep trees) — 8 tests green (`test_fast_instance_sweep`) | ⏸️ **DEFAULT-OFF, ship-ready.** SAFETY-CRITICAL (protected set = "never kill our own launcher/tree"), so it needs a live Windows run with `AIPACS_FAST_INSTANCE_SWEEP=1`: confirm startup `:387`/`:449` stall drops AND nothing unexpected closes (VS Code/terminal). Then flip default. Kill switch = unset/`0` |
| 2026-07-05 | **OPT-11 flag collapse — 4 validated NON-clinical flags retired** (promoted to unconditional default) | live-verified optimizations still carrying a kill switch; user directive to close out small validated items (keep clinical kill switches) | retired `AIPACS_DEFER_LICENSE_INFO` (app_handler), `AIPACS_THEME_APPLY_DEDUP` (mainwindow_ui + AIPacs_ui + patient_search_widget), `AIPACS_STATUS_REFRESH_DICOM_ONLY` + `AIPACS_STUDY_DL_CHECK_CACHE` (patient_table_widget) → defer/dedup/trim/cache now unconditional; legacy branches deleted; `AIPACS_STUDY_DL_CHECK_TTL_MS` kept as a numeric tunable | 4 guard tests updated (flag-retired pins + kill-switch mirror tests removed); the 4 smaller source files AST-OK in sandbox; patient_table_widget verified via file tool (sandbox mount truncates it) | ✅ code complete; **CLINICAL kill switches deliberately RETAINED** (identity gate / poison-guard / study_uid stamp — recent, safety-sensitive). **Verify via VS Code pytest** (sandbox mount corrupting reads this session). Default-off flags (`AIPACS_FAST_INSTANCE_SWEEP`, `AIPACS_STATUS_EXPENSIVE_TTL`) + OPT-09 telemetry still await their live validation run before promotion |

| 2026-07-05 | **OPT-17 Reliability/clinical: viewer-cache STUDY-IDENTITY hardening** (`AIPACS_CACHE_STUDY_IDENTITY`, default-on) | audit finding #1: in-memory viewer caches keyed by BARE series_number — tiers 1-3 of `_get_series_by_number_fast` (`_hot_series_cache`/`_series_cache`/`_series_number_to_index`) validated ONLY series_number + object identity (NO study check); tier-4 `_cache_entry_study_matches` failed OPEN on a cached entry lacking `study_uid`. Isolation depended on the offset-key scheme + stable slots, not on the key itself | study identity made an INTRINSIC, positively-checked property of every entry: (1) `_full_cache_put` STAMPS the entry's own `study_uid` at write time (gap-fill only, via `_resolve_canonical_series_identity`) so the read guard can never fail-open on our entries; (2) `_entry_is_valid` (tiers 1-3) REJECTS a cached tuple whose stored `study_uid` ≠ the study the display key resolves to → miss → clean reload; (3) tier-4 fail-open branch now logged. Multi-study-gated + positive-mismatch-only ⇒ single-study byte-identical; the viewport `series_uid` identity-gate remains the final backstop. **Deliberately did NOT reformat the ZetaBoost store key** — the warmup callback `_zeta_boost_load_series` hard-requires a digit key (`isdigit()`/`int(sn)`), so a composite key would silently break warmup; that full store re-key stays a larger staged item needing warmup-callback rework + live validation | edits verified via Read tool + isolated-block AST-OK; **11/11 offscreen guard tests green** (`test_cache_study_identity`: truth-table single-study byte-identical / multi-study reject-on-positive-mismatch / fail-open-on-unknown / stamp gap-fill + 5 source-pins). Full-file AST via sandbox blocked by the known FUSE tail-truncation (verified the real files terminate cleanly via Read) | ⏳ offscreen-verified; **NEEDS-LIVE-VERIFY** on the source build (multi-study + previous-exam tab: every current & previous series shows/switches correctly; watch for `[CACHE-STUDY-IDENTITY] tier reject` — a reject should be followed by a correct reload, never a blank/stuck viewport). Files: `_vc_backend.py`, `_vc_cache.py` (neither plugin-mirrored). Report: `docs/reports/CLINICAL_SERIES_IDENTITY_TARGET_AUDIT_2026-07-05.md` §5 |

| 2026-07-05 | **OPT-06 Reliability/clinical: study-scoped grow-lane fallback bind** (`AIPACS_GROW_LANE_STUDY_NUMBER_BIND`, **default OFF pending live verify**) | OPT-03 verify FAILED (sess-11818cd24bf6): the download→viewer grow lane (`_grow_lane_display_key`→`display_key_for_active_series_uid`) re-keys a DM event to the awaiting viewport by matching the DM event's globally-unique `series_uid` against the `series_uid` stored in this patient's `_server_series_info[offset_key]`. For a PREVIOUS-EXAM/secondary series whose offset-key entry carries a stale/degenerate `series_uid`, that match failed → `resolved=None` (10×) or mis-resolved to a wrong bare number (201/9001) → the awaiting prev-exam series (202) never grew; it only crawled up via the disk-readiness resume fallback (`GROW-DISPLAYED 40→58/256`). Seam B (OPT-03) fired 0× because most drops were mis-resolved (non-None), not None. This is the root of the recurring "series N shows in current AND previous exam / needs a 2nd drag" report | when the `series_uid` match finds nothing, bind by the CANONICAL `(study_uid, series_number)` instead: `home_download_service._dm_event_series_number` reads the DM event's authoritative number from ITS OWN study's DM task `series_list` (independent of the stale uid→number map) and threads `(event_study_uid=uid, event_series_number)` into `display_key_for_active_series_uid`, which matches an awaiting/progressive key ONLY when BOTH its resolved study_uid AND series_number equal the event's own. STRICTLY study-scoped (never number-only) so it can never cross-study collide; never overrides a `series_uid` match; default-off = byte-identical legacy. `[GROW-LANE-STUDYNUM-BIND]` success marker + widened `[GROW-LANE-TRACE]` (full uids + `ev_num`) for the verify | both edited blocks AST-OK as isolated snippets + **9/9 offscreen guard tests green** (`test_grow_lane_study_number_bind`: legacy-miss-on-stale-uid, fallback-binds-prev-exam, never-cross-study, number-mismatch-no-bind, series_uid-precedence, no-kwargs-byte-identical + 3 source-pins). Full-file AST blocked by the known FUSE tail-truncation (both files verified to terminate cleanly via Read) | ⏳ offscreen-verified; **DEFAULT-OFF, NEEDS-LIVE-VERIFY** on the source build (48912 / a prev-exam patient) with `AIPACS_GROW_LANE_STUDY_NUMBER_BIND=1`: the previous-exam series should grow on the FIRST drag; watch for `[GROW-LANE-STUDYNUM-BIND] bound display_key=…` and a drop in `[GROW-LANE-TRACE]` unmatched lines → then flip default-on and OPT-03's seam becomes redundant. OPT-20 (initial `change_series` LOAD miss) is a DIFFERENT resolution path — not closed by this. Files: `home_download_service.py`, `_vc_progressive.py` (neither plugin-mirrored) |

| 2026-07-05 | **VERIFY RUN sess-…416036 — closes OPT-09/12/18; OPT-06 mechanism-safe; OPT-20 narrowed** (verify_release.ps1, all validation flags on) | pre-run: OPT-09/12/18 shipped-unconfirmed; OPT-06 impl-unverified; OPT-20 open | **0 crashes; during-use 0 stalls / max 0 ms; TTFI 27.8 ms.** OPT-18 = **0** owner-reassignments (enforce-on, no false blocks). OPT-12 = `single_instance_lock.py:387` **0** stall traces (fast-sweep default-on), nothing wrongly closed. OPT-09 = **+753 INFO / +295 WARNING / +9 ERROR** (telemetry relabelled INFO, was ~36,663 WARNING). OPT-06 = `ev_num` computed (10/100000), **0 false binds** under a 3-study+document session (target stale-uid case not hit — prev-exam 3000201/3000202 had valid uids + loaded fine). OPT-20 = the 66 `series=None` misses are a DOCUMENT/secondary-capture study (`…045`, series 10 + doc 100000, empty series_uid), NOT the prev-exam path (which worked) | 0 regressions; identity-gate 24 evals / **0** wrong-study skips | ✅ **OPT-09, OPT-12, OPT-18 → VERIFIED-COMPLETE.** OPT-06 → mechanism-verified-safe, kept default-OFF (needs a real stale-uid repro; learned `resolved=None` is normal for background series). OPT-20 → narrowed to a document/secondary-capture study (overlaps OPT-07) = the next P1. OPT-02 (Seam A) not exercised (no rapid A→B→A); OPT-01 expensive-TTL still default-off pending a chip-freshness visual confirm |

| 2026-07-06 | **OPT-20 Reliability/clinical: async-apply render-gate type-mismatch — previous-exam DX/document "won't display" FIXED + PROMOTED DEFAULT-ON** (`AIPACS_APPLY_RENDER_TARGET_VIEWER`, default `"0"`→`"1"`) | patients 48456/45289: large single-frame previous-exam series (DX X-rays up to 60 MP, DICOMized documents) intermittently/never rendered. Ruled out (in order, all WRONG first): contention/OPT-04 (0 stalls), a stale-token race + render-convergence retry (reconverge fired but miss persisted; fails even fully-cached ⇒ deterministic), and the disk-header metadata path (renders primary DX fine). `[FAST-YIELD-TRACE] will_yield=True` proved metadata always builds — the drop is in the APPLY/RENDER half | `_apply_loaded_series_data` (`_vc_load.py:1259`) gated the render (`_perform_series_switch_optimized`→`_start_qt_viewer`) on `current_idx == series_idx`, but `current_idx = last_series_show` is the **series NUMBER** (`_pw_viewers.py:684`) while `series_idx` is the **list INDEX** (`replace_series_data -> int`). Offset-key series (e.g. `2000001`) never equal a small index ⇒ render ALWAYS skipped. Fix: also render for the explicitly-targeted, non-stale viewer (already past the `target_viewer_id` filter + `_is_request_current`), regardless of the broken index compare; additive, legacy match preserved | **LIVE-VERIFIED 45289** via the per-hop apply instrumentation (`AIPACS_APPLY_TRACE`): `[apply-path] APPLY-ENTER=34 APPLY-STALE-EARLY=0 APPLY-GATE(legacy_match=False)=28 target_fix_render=29`; `[APPLY-GATE] series=1000002 last_series_show=4 series_idx=5 legacy_match=False target_fix_render=True` + `first_image_visible` after each; previous-exam series now render (1000001 4/4, 1000004 3/3, …). AST-verified through the edit region (full-file blocked past the edits by the FUSE truncation cap) | ✅ **DONE — shipped default-on**, kill switch `AIPACS_APPLY_RENDER_TARGET_VIEWER=0`; telemetry `[APPLY-ENTER]`/`[APPLY-GATE]`/`[FAST-YIELD-TRACE]`/`[RENDER-DROP]` all behind flags default-off (no clinical-log spam). **Two rare P2 residuals** (each 1× this run, recover on re-click): (a) apply NEVER entered (no `[APPLY-ENTER]`) = worker→UI fire-and-forget post lost (`_queue_on_ui_thread`); (b) 1 `will_yield=False` = rare empty metadata build. The earlier `[RENDER-DROP-RECONVERGE]` retry stays as a default-off safety net. Locator: `tools/dev/run_dx_trace.ps1`. Files: `_vc_load.py` (not plugin-mirrored) |

| 2026-07-07 | **CLOSE-OUT RUN 49317** (`verify_all_opts.ps1`, all validation flags on) — closes 4 OPTs, refines OPT-20 residuals | pre-run: OPT-09/12/17/18 shipped; OPT-20 main fix shipped; residuals uncharacterized | **0 crashes; during-use 0 stalls / max 0 ms; ViewportLoadFailed=0; cleared-while-awaiting=0.** OPT-20 `[APPLY-GATE] target_fix_render=31` (fix carrying most previous-exam renders). OPT-17 = 48 gate evals / **0** skips. OPT-18 = **0** reassignments. OPT-12 = **0** `:387` stalls. OPT-09 = +1135 INFO (telemetry at INFO). **3 offset-key series still never rendered — now characterized:** `1100000` = a DICOMized DOCUMENT (series 100000, `APPLY-ENTER=0`, apply never ran) = OPT-07 document handling, not the display-gate bug; `3000001`/`3000002` = slot-3 DX (`APPLY-ENTER=4/2` but `APPLY-GATE=0`) = the apply enters then bails BEFORE the render loop (series_idx<0 OR the per-viewer stale check at `_vc_load.py:1276`, coincident with a mid-load 401 credential refresh). Residuals: 5 empty-metadata builds, 9 render-drops | 0 regressions | ✅ **CLOSE: guard-tests, safety, OPT-09, OPT-12, OPT-17, OPT-18, OPT-20 MAIN fix** (index-gate type-mismatch, default-on, target_fix_render=31). **HOLD: OPT-06** (not exercised — no stale-uid grow this run — keep default-off); **OPT-01** expensive-TTL (0 stalls, needs chip-freshness visual confirm to flip); **OPT-20 residuals (P2)** = `[APPLY-LOOP]` + `[APPLY-STALE-VIEWER]` diagnostics added (`AIPACS_APPLY_TRACE`) to pin the slot-3 per-viewer-stale vs series_idx<0 sub-case next run; `1100000` document = OPT-07 |

| 2026-07-07 | **OPT-21 Stability: MPR OpenGL pre-flight + production faulthandler** (`AIPACS_MPR_OPENGL_PREFLIGHT` + `AIPACS_NATIVE_FAULT_LOG`, both default-on) | end-user PC2: Standard MPR killed the whole frozen app with a NATIVE crash creating the FIRST VTK OpenGL render window (`_create_axial_view`; all logs stop 14:48:02.63-.64, no traceback — production build had NO faulthandler, so zero trace) | `toggle_zeta_mpr` now probes OpenGL once per session via plain Qt (graceful failure) BEFORE any volume load / VTK window; on failure shows an "update your GPU driver" dialog + resets tool state and returns — the 2D viewer keeps working. `main.py` enables faulthandler → `user_data/logs/native_fault.log` (all threads, session markers, handle kept alive, never breaks startup) | py_compile OK (toolbar_manager, main, both new modules); **15/15 new guard tests green** (`tests/code/viewer/test_mpr_opengl_preflight.py` 11 + `tests/code/system/test_native_faulthandler.py` 4) on the real venv; full `tests/code/viewer` run vs stashed baseline: **60 failed / identical set both runs, 0 new failures** (pre-existing local-env failures; `test_b43_progressive_lifecycle_state` collection error also pre-existing, verified via stash). New viewer tests +11 = 1819 passed vs 1808 baseline | ✅ shipped default-on with kill switches. NEXT: (a) PC2 machine confirm — Event Viewer faulting module + GPU driver update (the actual cure); (b) live source-build sanity on a good GPU (MPR opens unchanged; probe logs `[MPR OPENGL_PREFLIGHT] ok=True`); (c) staged follow-up — reuse the same probe for the other VTK hosts (Advanced viewer, dental VTK-MPR, curved-MPR picking host). Files: `modules/mpr/opengl_preflight.py` (new), `PacsClient/utils/native_fault_log.py` (new), `toolbar_manager.py`, `main.py` (none plugin-mirrored) |

| 2026-07-08 | **OPT-21 ROOT CAUSE FOUND + FIXED via the shipped faulthandler — WoA MPR crash = bundled SOFTWARE OpenGL (llvmpipe) illegal-instruction under emulation, NOT OpenGLOn12** | live Snapdragon `native_fault.log`: `0xc000001d ILLEGAL INSTRUCTION` at `_mpr_views.py:498 vtk_widget.Initialize()`; `[HW_CHECK] renderer=llvmpipe (LLVM 3.6) OpenGL 3.3` = app was on the BUNDLED SOFTWARE renderer (`cpu_safe` default), not the hardware D3D12/Adreno GL 4.6 GLview saw. llvmpipe's x64 SIMD JIT hits an instruction Prism can't emulate. The pre-flight probe passed (same software GL, didn't hit that instruction) = the documented "probe passes, VTK crashes deeper" caveat | **the safe/dangerous graphics choice is INVERTED on WoA** — software crashes, hardware works. Fix (`aipacs_runtime.build_windows_graphics_environment` WoA branch, default-on): on emulated WoA the software profile uses SYSTEM/desktop hardware OpenGL (`QT_OPENGL=desktop`, `VTK_USE_HARDWARE=1`, no Mesa DLLs on PATH, ANGLE d3d11) instead of forcing llvmpipe; escape hatch `AIPACS_WOA_FORCE_SOFTWARE_GL=1`. Emulation detection hardened (`is_windows_on_arm_emulated` — IsWow64Process2 returned blank on the live box, so env `PROCESSOR_ARCHITECTURE` mismatch + CPU-identifier/`platform.machine()` fallback); `[RUNTIME_ARCH] emulated` now resolves True; `[WOA-PROFILE]` reports `graphics=hardware_desktop_gl`; `[MPR-STEP]` bisector confirmed the crash window | py_compile OK; **38 green** (`test_woa_graphics.py` 9 new + runtime-arch/woa-profile/arm64-packaging updated) | ⏳ **NEEDS live re-test on the Snapdragon box** (open MPR → should render via D3D12/Adreno; `[MPR-GL-CAPS]` shows the real renderer + `emulated=True`; no `0xc000001d`). Separate OpenGLOn12 pack regression may still bite OTHER machines — pack/driver update stays in the checklist. Does not need a rebuild flag flip; ships in the next build |

| 2026-07-07 | **ARM64 STRATEGY PIVOT: emulation-first WoA SKU SHIPPED** (user decision — x64-under-emulation is the supported ARM64 path for now; native ARM64 = later phase) | ARM64 machines could only install the classic x64 package silently (no ARM64-aware install, no emulation profile, no WoA diagnostics) | **"AIPacs (ARM64 emulated)" SKU**: `AIPacs_Setup_woa.iss` (ARM64-hosts-ONLY installer of the SAME x64 stage; informative first page; stamps `install_package=x64_on_arm64` into installation_profile.json; same AppId = clean upgrade of a prior x64 install; plain-x64 machines can't install it) + `build_release.py --with-woa-installer` (compiled from the normal x64 pipeline, best-effort, primary artifact never at risk) + classic x64 installer's ARM64 warning now points at the WoA package + `InstallPackageKind` stamped for all three SKUs (x64 / x64_on_arm64 / arm64). **WoA runtime profile** `PacsClient/utils/woa_profile.py` wired in main.py after `[RUNTIME_ARCH]`: on emulated hosts logs `[WOA-PROFILE]` (arch, package kind, VTK/MPR=emulated-x64-via-OpenGLOn12, tuned vars) and applies user-overridable env defaults (`AIPACS_BROWSER_PREWARM=0` — Chromium prewarm is a heavy JIT cost under emulation); pure `decide_woa_tuning`; kill switch `AIPACS_WOA_PROFILE=0`; native machines byte-identical no-op. **Diagnostics completed**: `[MPR-OPEN-KPI] standard_mpr_construct_ms` (toolbar_manager) + `[MPR-GL-CAPS] emulated=/host=` fields | guard tests `test_arm64_packaging.py` **19 green** (incl. WoA iss pins) + NEW `tests/code/system/test_woa_profile.py` **8 green**; parity gate green after `sync_plugin_mirrors.py` (drift = the OPT-22/23 files `prewarm.py`/`viewer_write_adapter.py`, which ARE plugin-mirrored — their "not mirrored" notes were WRONG, corrected in CLAUDE.md + memory) | ✅ x64 machines byte-identical. NEXT: compile all three .iss variants on the next release build (ISCC syntax check); ship the WoA SKU to PC2 + run plan §6 validation (startup, patient/viewport loading, MPR via emulation, `[MPR-OPEN-KPI]`/`[WOA-PROFILE]`/`[MPR-GL-CAPS]` captured) after the pack/driver fix; publish per-arch URLs via `location_by_arch`. Native ARM64 (lite build + VTK wheel) deferred until the emulation path is stable |

| 2026-07-07 | **ARM64 platform foundation SHIPPED (x64-side half of `docs/plans/architecture/ARM64_WINDOWS_PLATFORM_PLAN_2026-07-07.md` §7)** | no ARM64 packaging path existed; the x64 installer silently installs on WoA via `x64compatible` (how PC2 got the emulated build) | `requirements-arm64.txt` (PySide6>=6.11.1, grpcio dropped, vtk/SimpleITK excluded pending Phase-2/3 source wheels, `#OPTIONAL` best-effort section) + `tools/build/setup_arm64_env.ps1`; `build_release.py --arch {x64,arm64}` (default x64 byte-identical: names, script, behavior; arm64 = cross-build guard + `AIPacs_Setup_arm64.iss` + " arm64"-suffixed artifacts); post-stage **binary PE-architecture scan** (`release_gate.check_stage_binary_architecture`, enforced arm64 / warn-only x64, `AIPACS_ENFORCE_ARCH_SCAN=1`); Inno single-source arch conditionals + x64-on-ARM InitializeSetup warning (SuppressibleMsgBox); `aipacs_runtime`: `resolve_source_location` per-arch update URLs (`location_by_arch`, host-arch keyed, legacy passthrough) + `build_profile()`/`vtk_features_available()` arm64-lite foundation | **13/13 new guard tests** (`test_arm64_packaging.py`) + builder/runtime/module_system parity suites **76 green** (1 pre-existing plugin-mirror drift — user's uncommitted `polygon_interactorstyle.py` et al — fixed via the documented `sync_plugin_mirrors.py`, 411 pairs match) | ✅ x64 pipeline byte-identical (arch suffix "" default). NEXT: ISCC-compile both .iss variants on the next release build; procure the ARM64 builder → Phase 1 arm64-lite build + live validation checklist (plan §6); Phase 2 VTK win_arm64 source wheel |

| 2026-07-07 | **OPT-21 iteration 3 — PC2 is Windows-on-ARM (Snapdragon X Elite): "weak GPU" hypothesis WITHDRAWN; WoA instrumentation shipped** | PC2 identified as ASUS Vivobook S, Snapdragon X Elite, Adreno X1-85 (driver 31.0.137.0), Windows 11 ARM64. GLview proves OpenGL 3.0–4.5 render tests PASS at high FPS on `D3D12 (Adreno X1-85)` / GL 4.6 Mesa — capability is NOT missing. Our x64 frozen build runs under Prism emulation; OpenGL is served by the Microsoft compatibility pack (Mesa GLon12 / `OpenGLOn12.dll`). STRONG external corroboration for the crash class: microsoft/OpenCLOn12#68 (systematic `0xc0000005` in OpenGLOn12.dll on ARM64 incl. Snapdragon X Elite, kills Blender/Godot at GL init/extension discovery; downgrade to pack v1.2403.9.0 fixes Blender), godot#106853, Blender#142859 (Adreno driver). Slow startup = Prism JIT translation (CPU pinned ~100% through the 9.1 s UI-construction window) + known startup stages | SHIPPED default-on: `[RUNTIME_ARCH]` banner + emulation detection (`PacsClient/utils/runtime_arch_log.py` via IsWow64Process2, wired in `main.py`); `[MPR-STEP]` native-call bisector bracketing QVTK ctor→Initialize→Start + `[MPR-GL-CAPS]` VTK ReportCapabilities log (`_mpr_views.py`, `AIPACS_MPR_STEP_TRACE`); "Process architecture" row in the Settings hardware check (`evaluate_hardware` arch item — WARNS on emulation); read-only PC2 evidence collector `tools/diagnostics/collect_pc_crash_evidence.ps1` (Event-Viewer faulting module, WER, D3DMappingLayers version, GPU driver, exe PE arch, `-EnableDumps`) | py_compile OK; **34/34 guard tests green** (preflight 20 + faulthandler 4 + runtime-arch 4 + defer-3d 6) | ⏳ **Next distinguishing steps (in order): (1)** run the collector on PC2 → faulting module (predicts OpenGLOn12.dll); **(2)** compatibility-pack version swap (newest, else known-good v1.2403.9.0) → retry MPR; **(3)** Adreno driver update; **(4)** next build's `[MPR-STEP]`/`[MPR-GL-CAPS]`/native_fault.log land. Full report: `docs/reports/WOA_ARM64_MPR_CRASH_INVESTIGATION_2026-07-07.md`. NOTE: the Qt pre-flight may PASS on this machine while VTK still crashes (GLon12 dies at extension discovery/texture ops, not context creation) — the probe guards the missing-GL class, the step trace + dump pin this one. Long-term mitigation ladder (only after evidence): pack pin on WoA → optional software-GL for MPR → native ARM64 build |

| 2026-07-08 | **OPT-24 Reliability: DM network auto-resume + control unification (Defect A)** — audit `docs/reports/DOWNLOAD_MANAGER_RESUME_RETRY_RELIABILITY_AUDIT_2026-07-08.md`; **shipped default-ON (each `=0` kill switch)** | queue does not auto-resume after a >3 min outage: temporary retry budget (10, ~2.75 min) drains while offline → `retry_count>=cap` → excluded from `_check_auto_retry` + the 5 s sweep; no connectivity monitor to re-arm → stranded FAILED. Right-side Start was a drifted duplicate of the row Resume (missing COMPLETED branch) | **A1** `network/net_monitor.py` (pure-stdlib off-thread TCP reachability probe, offline→online edges, `AIPACS_DM_NET_MONITOR`); **A3** `_dm_workers._rearm_network_failed_studies` resets retry_count + FAILED→PENDING for TEMPORARY only, polled from the GUI-thread health check on the edge (`AIPACS_DM_NET_RESUME`); **A4** `_effective_retry_cap`→`MAX_RETRIES_TEMPORARY_UNSTABLE=100000` under the same flag; **I1** `_on_start_selected`→`_on_per_patient_resume` (`AIPACS_DM_UNIFY_RESUME`); **L1–L4** `[DM-STATE]`/`[DM-NET]`/`[DM-RETRY-EXHAUSTED]`/`[DM-CONVERGE-MISS]` | **host venv full pytest 11/11 GREEN** (`tests/code/download_manager/test_dm_net_monitor.py` 4, `test_dm_net_resume.py` 5, `test_dm_resume_unification.py` 2 — real PySide6 `_dm_workers` import path, not just offscreen); host `py_compile` clean on all 6 edited files + the payload copy. NOTE: this session's Linux sandbox FUSE mount served TRUNCATED reads of the large `_dm_*`/`constants.py` (false end-of-file SyntaxErrors) — so compile + tests were run on the HOST via PowerShell; Read-tool + host confirm the files are complete | ✅ **Defect A shipped default-ON** (each `=0` kill switch → legacy byte-identical). **Plugin mirror SYNCED + verified on host** (`sync_plugin_mirrors.py --add …net_monitor.py` → `verify_plugin_mirrors.py` = 412/412 match, 0 drift) so the change is in the build payload. Defect B (completion-convergence re-download storm) = **OPT-04, NOT attempted** (only L3 marker). **G1 global Start-All unification deferred** (cancelled-restart semantics differ). NEEDS live source-build verify: multi-patient queue → >5 min outage → studies re-arm on reconnect (watch `[DM-NET] offline->online edge` → `[DM-STATE] … new=PENDING reason=net_up`) |

| 2026-07-07 | **OPT-21 iteration 2 — once-per-INSTALL persistence + Settings "Hardware Requirements Check"** (user directive: don't check OpenGL every time; put the test in Settings → Viewer Configuration) | iteration 1 probed once per SESSION on the first MPR click | probe result now PERSISTS to `<config>/hardware_check.json`: persisted PASS = ZERO probing on MPR open (healthy machine probes exactly once ever); persisted FAIL/missing = graceful re-probe + persist (self-heals after a driver update). New `HardwareCheckPanelWidget` (`settings_ui/hardware_check_panel.py`) in `viewerconfigsetting.py`'s right column: persisted result display (OpenGL/GPU, CPU, RAM, free disk — pure `evaluate_hardware`, ok/warning/fail; only OpenGL gates MPR) + "Run Hardware Check" button (`run_hardware_check(persist=True)`, also refreshes the MPR gate). Blocked-MPR dialog now points at the Settings check | py_compile OK (4 files); **22/22 guard tests green** (persistence semantics pinned: persisted-PASS-zero-probe, fail-reprobe-self-heal, run-persists-refreshes-gate, settings wiring) + settings-related suite 15 passed; offscreen import of `viewerconfigsetting`+panel OK | ✅ shipped default-on. `hardware_check.json` is machine-generated state — NEVER seed it as a config template. NEEDS live sanity: open Settings → Viewer Configuration (panel renders; Run updates statuses), MPR unchanged on a good GPU |

| 2026-07-07 | **OPT-20 slot-3 residual: multi-study display-miss — study-blind append dedup FIXED default-on** (`AIPACS_SERIES_APPEND_STUDY_DISTINCT`, default-on) | 49317: distinct SECONDARY-study series `3000001`/`3000002` never displayed while primary/slot-2 did (`[APPLY-ENTER]` present, `refresh=True`, but `[APPLY-GATE]` ABSENT ⇒ render loop gated off by `series_idx<0`). Ruled OUT the token race by static analysis: `[APPLY-STALE-EARLY]=0` + both token gates run on the SAME UI thread with no yield ⇒ token current at 1290 too; and the offset-key stamping aligns (`series_key==str(series_number)==metadata series_number`) ⇒ NOT a key mismatch | ROOT (deterministic): `add_new_data_to_lst_thumbnails_data` (`_pw_metadata.py:203-211`) had a **study-blind** dedup — a series sharing a `series_name` AND instance count with an already-present series hit `return False` and was NEVER appended, even with a DIFFERENT `series_number`. Multi-study/previous-exam patients routinely share a name across studies (scout/localizer/DX/repeat) → the distinct secondary series was dropped → `replace_series_data` returned **-1** → `series_idx<0` gated off the render loop → never displayed. Fix: only skip as a TRUE duplicate when the incoming `series_number` is already present; a distinct, not-yet-present number falls through to the existing end-append (no ordering change for any working case). Isolation untouched (own offset number + stamped `study_uid`/`series_uid`; identity gate still fail-closed on `series_uid`) | **8/8 headless checks vs the REAL method** (distinct same-name+count appends; `replace_series_data` returns ≥0 not -1; 3 studies same-name all present; true-duplicate still deduped; diff-count pairing unchanged; flag-off legacy drop + `replace`→-1). `import os` added to `_pw_metadata.py`; py_compile OK. Guard test `tests/code/viewer/test_series_append_study_distinct.py` | ⏳ offscreen-verified; **NEEDS-LIVE-VERIFY on 49317** (drag every series of BOTH studies → all display; `[SERIES-APPEND-DISTINCT] append distinct series=3000001…` in app.log; 0 `[IDENTITY-GATE] SKIP`; slot-3 now reaches `[APPLY-GATE]`+`first_image_visible`). Then collapse the flag. `1100000` document (`[APPLY-ENTER]=0`) remains OPT-07. File `_pw_metadata.py` (not plugin-mirrored) |

| 2026-07-08 | **OPT-22 startup freeze FIX: idle-gate the web-browser Chromium prewarm** (`AIPACS_BROWSER_PREWARM_IDLE_ONLY`, default-on) | 07-07 v3.4.6: `web_browser.prewarm._construct_warm_view` constructed `QWebEngineView` on the GUI thread ~4 s after home load → **21 s** `interaction_active=False` startup stall (ends exactly at "Chromium engine warmed") | `QWebEngineView` is GUI-thread-only (can't off-thread), so the fix is TIMING: warm only after a genuine idle gap (no click/key/wheel for `idle_ms`, default 5 s) past a longer initial delay (default 20 s), poll-recheck, and SKIP the warm if the user stays busy past `max_wait_ms` (default 10 min). Minimal app event filter (discrete events only, removed after warm/skip). Marker-gate + `AIPACS_BROWSER_PREWARM=0` preserved; `IDLE_ONLY=0` = byte-identical legacy | idle/poll/skip decision + both flag defaults validated standalone; EchoMind sibling test green; **py_compile of `prewarm.py` blocked in-sandbox by the FUSE mount caching the old file size (6306 B) — Read-tool confirms the real 314-line file is complete + well-formed**; guard `test_browser_prewarm_idle_gate.py` (host lane) | ⏳ **shipped default-on; NEEDS live verify** (probe on, browser marker armed → no `_construct_warm_view` stall in the first ~60 s; browser still opens; `AIPACS_BROWSER_PREWARM=0` clean). Report `docs/reports/REGRESSION_REVIEW_STARTUP_AND_ECHOMIND_FREEZE_2026-07-08.md` |
| 2026-07-08 | **OPT-23 EchoMind import freeze FIX: defer change_series switch to singleShot(0)** (`AIPACS_ECHOMIND_DEFER_SWITCH`, default-on) | 07-07 v3.4.6: EchoMind dispatch inline on UI thread → `change_series_on_viewer` synchronous; spinner shown but never painted (same event-loop turn); Advanced/VTK `ImageViewer2D`+`Render()` ~2.4 s | `viewer_write_adapter.change_series` now schedules `method_change_series_on_viewer(...)` via `QTimer.singleShot(0, ...)` — matching the real drop (`_vw_dragdrop.dropEvent`), so the spinner paints first and the command-bus/IPC drain returns immediately; the switch itself is unchanged (async for cache-miss). Result semantics unchanged ("async load dispatched") | **3/3 guard tests green in-sandbox vs the REAL adapter** (`test_echomind_defer_switch`: defers-by-default, inline-when-`=0`, spinner-first); `viewer_write_adapter.py` py_compile OK | ⏳ **shipped default-on; NEEDS live verify** (EchoMind `drag_series` → spinner shows, no dead freeze). Follow-ups (report): Advanced/VTK render is GUI-thread-inherent (spinner only); AI-seg `on_contour_closed→requests.post` sync network POST → move off-thread |

| 2026-07-11 | **OPT-24 patient-list slowness: SERVER-side root cause proven + client-side waste removed** (4 flags, all default-on) | User report "getting the patient list is too slow". 07-11 logs: `[NET_TIMING] endpoint=GetPatientList` **`server_wait_ms=5016..5941 transfer_ms=0-1 parse_ms=0`** on date+modality searches vs **139 ms** for a `patient_id` lookup on the SAME socket. 215 calls: median 130 ms, max 5941 ms, 36 > 3 s. Result count does NOT drive it (3 patients = 5.02 s, 16 = 5.48 s ⇒ ~4.9 s FIXED cost) | **The 5 s is 100% `server_wait_ms` — the client cannot remove it** (transfer+parse ≈ 0; runs on worker threads, NOT the GUI thread — max main-thread stall during searches was 768 ms, so it is a LATENCY problem, not a freeze). Client-side waste that WAS removed: (a) **OPT-24b** `test_connection()` pre-flight before EVERY search is a FULL extra GetPatientList round-trip (~125 ms) — **~140 of the 215 calls were just probes**; now skipped while connectivity is fresh (TTL 300 s), still probed on the first search and to disambiguate an empty result (`search_patients_sync` returns `[]` for BOTH "no patients" and "connection dead"). (b) **OPT-24c** `socket_service.cleanup()` after each search called `connection_pool.close_all()`, closing all 5 pooled connections so the pool never pooled (95 rebuilds/session); now kept warm — SAFE because `SocketConnectionPool.get_connection()` already validates + replaces stale clients. (c) **OPT-24a** `update_server_settings()` rewrote the config FILE on every search (111 writes, host/port never changed); now skipped when unchanged. (d) **OPT-24d** `[SEARCH-PERF]` log + a one-shot background **enrich A/B probe** that re-issues the same query with `include_study_count=False` and logs `[SEARCH-ENRICH-PROBE] with_study_count_ms=… without_study_count_ms=… delta_ms=… -> verdict`, to settle whether the 5 s is the per-patient ENRICHMENT or the date+modality SCAN | **11/11 guard tests green** (`tests/code/ui_services/test_patient_search_client_opt.py`: real `update_server_settings` save-skip + change-still-persists + kill switch; probe-skip decision; connectivity TTL expiry + failure-forces-reprobe; empty-result-must-verify; all 4 flags default-on w/ kill switches). `socket_config.py` full-file AST-OK; `home_search_service.py` AST-OK through all edits (tail truncated by the known FUSE mount bug; edited regions isolate-verified). Plugin mirrors verified (412 pairs, 0 drift) | ⏳ **shipped default-on; NEEDS live verify on a routine run.** Expected: `GetPatientList` calls ≈ 215 → ~75 (−65% server load), config writes 111 → ~1, pool rebuilds 95 → ~1, `patient_id` search ~2× faster; **the 5 s date+modality wait is UNCHANGED — that needs a SERVER-side index.** The `[SEARCH-ENRICH-PROBE]` line in the next run decides whether a client lazy-enrich + background backfill is worth building. Flags: `AIPACS_SEARCH_SKIP_PROBE`, `AIPACS_SEARCH_KEEP_POOL`, `AIPACS_SEARCH_ENRICH_PROBE`, `AIPACS_SOCKET_CFG_SKIP_UNCHANGED_SAVE` |

| 2026-07-11 | **OPT-24 LIVE RESULT — SERVER-side index fix = ~12× on the patient list; client A/B probe settles the enrichment question** | Pre-fix `[SEARCH-PERF]`: date+modality 5279–5655 ms (patient_id 125 ms). The 5 s was `server_wait_ms` (transfer/parse ≈ 0) | **SERVER fix (by the user) landed between 15:54 and 16:26.** The IDENTICAL query (`date=20260709, modality=MR, 30 rows`) went **5387 ms → 455 ms → 448 ms ≈ 12× faster**. **`[SEARCH-ENRICH-PROBE] with_study_count_ms=455 without_study_count_ms=429 delta_ms=26 rows=30 -> SCAN is the cost (not enrichment)`** — enrichment (`include_study_count`) costs only **26 ms**, so it was NEVER the bottleneck. This **vindicates NOT default-on'ing the lazy-enrich change**: it would have risked regressing the documented right-panel "grew" gate (`count_of_series`, the 44113/44534 fix) for a 26 ms gain. The client A/B probe did exactly its job — it told us the client had no lever, and the server index was the right fix | Client OPT-24 verified live: **config disk writes 111 → 0** ✅; **probe-skip working** (4 of 8 searches `probed=False`; probes only on the first search and after the 300 s TTL — correct by design). **Pool rebuilds still 22** ❌ → root-caused: `get_socket_patient_service()` called `reload_connection()` **unconditionally on every call**, constructing a BRAND-NEW `SocketConnectionPool` and discarding the warm one — so removing the per-search `cleanup()` could not help. FIXED: new `reload_if_server_changed()` rebuilds only on a real host/port change (kill switch `AIPACS_SOCKET_POOL_REUSE=0`). 15/15 guard tests green; `socket_patient_service.py` py_compile OK | ✅ **Patient-list slowness RESOLVED (server-side).** Client waste removed. Remaining: one more restart to confirm pool rebuilds 22 → ~1. `include_study_count` stays as-is (26 ms — not worth touching). Files: `socket_patient_service.py`, `socket_config.py`, `home_search_service.py` |

| 2026-07-12 | **OPT-25 FIELD DEFECT (new center "Roshana"): radiography study never displays — a missing `SeriesNumber` killed the WHOLE study's metadata fetch. FIXED default-on** (`AIPACS_SERIES_NUMBER_NORMALIZE`) | User report: "some radiography images cannot be displayed" at a newly installed center. Logs (`logs roshana/`): `❌ Metadata fetch via socket failed (attempt 1..3/3): invalid literal for int() with base 10: 'None'` → `❌ [ERROR] Worker error … Failed to fetch metadata` → the download **never starts** → nothing to display. Same `ValueError` in `db_diagnostics.log` from `home_db_service.get_series_info_from_database:146`. **NOT** a network/decode/cache/render problem: the socket answered in **38 ms** (`[NET_TIMING] endpoint=GetStudyThumbnails server_wait_ms=38 transfer_ms=1 parse_ms=0`); there is not a single decode/pixel/render error in any log | **ROOT CAUSE (ours, one cast).** `SeriesNumber` (0020,0011) is **optional/type-2 in DICOM** — the center's DX/CR device omitted it, and the server serialized the absent value as the **literal string `"None"`**. `grpc_client._build_metadata_from_socket:147` (socket-backed despite the legacy filename — gRPC is retired) did `series_number=int(str(series.get("series_number") or 0))`. `"None"` is a **truthy non-empty string** ⇒ the `or 0` guard never fires ⇒ `int("None")` raises ⇒ the exception escapes the per-series loop and aborts the **entire study's** metadata build (3 retries, then permanent failure + an infinite DM health-check respawn loop: 7 subprocesses in 2 min). **FIX = normalize ONCE at the single socket ingestion boundary**, so no consumer can ever see a non-numeric series number: NEW pure-stdlib `modules/network/series_identity.py` (`parse_series_number` — the one tolerant predicate; `normalize_series_entries` — deterministic repair) wired into `modules/network/socket_client.py` `get_study_thumbnails` + `query_series_thumbnails` (the choke point ALL consumers share: DM, home panel, patient-tab thumbnails, previous-exams, DB writer). Missing numbers get a **deterministic, non-colliding synthetic** from the reserved band **900001–999999** — above any real SeriesNumber, strictly **below the 1_000_000 multi-study offset-key threshold**, excluding numbers already taken by the study, assigned in `series_uid` order so the UI and the download subprocess independently agree (on-disk folder / thumbnail / DB row stay consistent). Safe because **images are fetched by `series_uid`** (`GetSeriesImages`), not by series number — the number is only local naming/ordering. Defense-in-depth: the DM per-series loop is now try/except'd (one malformed series can never abort a study) and `home_db_service` uses the tolerant parse | **`tests/code/network/test_series_number_normalization.py` 15/15 green** (pins the original `int("None")` crash; healthy payload **byte-identical incl. type** — `"02"` stays `"02"`; no collision; below 1e6; deterministic regardless of server list order; kill switch). **Regression proof:** ui_services+viewer+builder+system run **with** the fix vs the SAME suites with the edits `git stash`ed → **identical failure sets (65 = 65, `Compare-Object` = IDENTICAL)** ⇒ **zero new failures**; those 65 are pre-existing/env. download_manager+network+storage **499 passed** (1 pre-existing `test_ino_report_workflow::test_classify_error[400]` — fails on baseline too). Mirrors **412/412 match** | ✅ **shipped default-on** (`AIPACS_SERIES_NUMBER_NORMALIZE=0` = byte-identical legacy). **Healthy centers are untouched by construction** — a series whose number already parses is not rewritten at all. ⚠️ **HOST-ONLY builds:** the sandbox FUSE mount served a **truncated** `grpc_client.py` (8344 of 9985 B) and `sync_plugin_mirrors.py` run *in the sandbox* wrote that truncated copy into the plugin payload — re-synced + verified on the Windows host. **Never run the mirror sync from the sandbox.** NEEDS live verify at Roshana (open patient MOHAMMAD ALI / study `1.2.246.512.1000.959000462…`: expect `[SERIES_NUMBER_NORMALIZE] … repaired=N` once, then a normal download + display). Follow-ups (NOT done): DM auto-retries a *deterministic* parse failure forever (should be non-retryable); server should emit JSON `null` (or synthesize a number) instead of the string `"None"`; rename `grpc_client.py` → `socket_metadata_client.py`. Report: `docs/reports/RADIOGRAPHY_NOT_DISPLAYING_MISSING_SERIES_NUMBER_ROSHANA_2026-07-12.md` |

| 2026-07-12 | **OPT-26 Reliability/clinical: TAB STUDY-PATH POISONING — a secondary study's series repointed the tab path, so a PRIMARY series with a COLLIDING series_number loaded the WRONG study and never displayed** (`AIPACS_TAB_PATH_PRIMARY_ONLY`, default-on) | Patient **49836** (2026-07-12 16:35): 3 studies; study A (primary `…068`) and study B (`…059`) BOTH contain series numbered **2/3/4**. Series **3 never displayed** — repeatedly: `[IDENTITY-GATE] viewer=0 SKIP render: incoming series=3 uid=…5932803366 != intended uid=…3657708721`. DICOM on disk proves the identities: `A/3` → SeriesUID `…43657708721`, `B/3` → `…35932803366`. Data was COMPLETE on disk (A=5, B=3, C=1 series); NOT a download bug | ROOT: `_apply_loaded_series_data` (`_vc_load.py`) adopted `metadata['series']['series_path'].parent` as the **TAB's** `import_folder_path` for **ANY** loaded series — including a SECONDARY study's. Loading study B's series (offset key `1000004`) repointed the tab path to study B; the next PRIMARY (plain-key) load then resolved `study_path/3` → **study B's folder 3** and handed B's series 3 to a viewport intending A's → the viewport identity gate (fail-closed on `series_uid`) correctly REFUSED to paint → series 3 blank forever. **The gate did its job** (it prevented showing study B's images labelled as A's series 3 — a wrong-image-on-screen event); the blank was the symptom, not the defect. FIX: only adopt the path when it belongs to the tab's **primary** study (`correct_path.name == parent_widget.study_uid`); a secondary series loads from its OWN entry `series_path` (the multi-study disk authority) and must NEVER redirect the tab. Refusals log `[TAB-PATH-GUARD]`. Single-study tabs byte-identical (their only study IS the primary); unknown primary → legacy. `_resolve_plain_series_study_path` poison guard retained as the 2nd layer | Edited block AST-OK + truth table (secondary refused / primary adopted / single-study identical / unknown-primary legacy / kill switch / non-existent path); **9/9 guard tests green** (`tests/code/viewer/test_tab_path_primary_only.py`, incl. the concrete 49836 sequence) | ✅ **LIVE-VERIFIED on 49836 (2026-07-12, user-confirmed: "now it works correctly")** — series 3 displays study A's series 3. HIGH severity (multi-study patients whose studies share series numbers: a primary series silently never displays after viewing the sibling study). Kill switch RETAINED (clinical). `_vc_load.py` not plugin-mirrored. **Diagnostic gap found:** `[MULTI-STUDY LOAD]` is `logger.info` and app.log did not capture viewer-module INFO this session — the resolution trace was invisible; consider raising its level / routing |

| 2026-07-12 | **OPT-27 Performance: EAGLE EYE OPEN FROZE THE APP ~55 s — the AI-module training-settings widget walked the whole DICOM store on the GUI thread. FIXED default-on + LIVE-VERIFIED** (`AIPACS_AI_TRAINING_SCAN_ASYNC`) | User report: "I run Eagle Eye on patient 49874 and it doesn't open the patient and the app freezes." `viewer_diagnostics.log`: ONE contiguous **`[MAIN_THREAD_STALL] stall_duration_ms=54799.3`**; every F11 sample on the same stack: `open_ai_module → switch_right_panel('ai_module') → add_new_tab_widget → AIMainWindow.__init__ → ModelTrainingTab → TrainingDataSettingsTab → MammographySettingsWidget.__init__ → _load_defaults → _auto_detect_and_apply_img_size → _detect_mg_dicom_image_size → pydicom.dcmread`. `app.log`: sustained **8–30 MB/s disk read at 25–55 % CPU for ~55 s**. NOT patient-specific; unrelated to the same-day AI-server 502 | ROOT: the Eagle Eye tab constructor eagerly builds the *Model Training settings* widget, which auto-detected the MG image size by `os.walk` + `pydicom.dcmread` over `user_data/patients` (**53,250 DICOM / 31.7 GB** on this machine) **synchronously on the GUI thread** — and its `max_scan_files=300` cap counted only **MG hits** (a non-MG file `continue`d BEFORE `scanned += 1`), so on a CT/MR/DX-heavy store the cap never tripped and the walk read every DICOM on disk. FIX (`modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py`, not plugin-mirrored): (1) **BOUNDED** — `_detect_mg_dicom_image_size` gains `max_examined_files` (files actually OPENED, default 2000) + `deadline_s` (default 3.0 s); (2) **OFF the GUI thread** — `_run_scan_off_thread` runs the scan on a daemon thread and applies the result via the module's existing thread-safe `_run_on_ui` dispatcher (deleted-widget safe); also covers BOTH `_update_file_count` `os.walk`s (BoneAge + Mammography). Non-clinical by construction (seeds a training spinbox default only) | **8/8 new guard tests** (`tests/code/ai_imaging/test_eagle_eye_training_scan_bounded.py`: examined-cap, deadline, MG still detected, off-thread by default, kill-switch inline, source pins) — full `tests/code/ai_imaging` **18 green** on the host venv; py_compile clean | ✅ **LIVE-VERIFIED on 49874 (2026-07-12 18:31): worst stall on Eagle Eye open 54,799 ms → 1,444 ms**, zero stall stacks in this file, `[TrainingUI] background mg-size-detect done in 3002 ms`; the same scan against the real store ~55 s → **1.88 s** (off-thread). Residual sub-1.5 s stalls = the AI module's Advanced/VTK viewer (`ImageViewer2D.__init__` 932 ms, `draw_boxes_ijk` 422 ms, `create_overlay_box` 450 ms) — GUI-thread-inherent, separate item. Trade-off: no MG in the first 2000 files ⇒ label says "no MG DICOM found (keeping current value)" (Browse path still scanned first). STAGED: lazy-build `ModelTrainingTab`; surface the AI server's error `detail` (`MamoWorker.raise_for_status()` discards the body — the 502 dialog hid "PACS request failed: 127.0.0.1:8000 … actively refused", i.e. the AI server's own PACS HTTP API was down). Report: `docs/reports/EAGLE_EYE_OPEN_FREEZE_TRAINING_SCAN_2026-07-12.md` |

| 2026-07-13 | **OPT-28 / OPT-29 / OPT-30 / OPT-31 — laptop field session: crash + "everything fails when the internet drops" + Sync Status reporting a false success. THREE independent root causes, all FIXED default-on** | User report: "the software froze, crashed several times and closed unexpectedly; when the Internet was lost it stopped responding. Sync Status closes the tab and THEN says the upload failed. Patient search is sometimes slow." Logs: `C:\Users\…\log on other pc\laptop khodam\` (app.log 7 990 lines / download_diagnostics 2 063 / viewer_diagnostics 10 252 / **native_fault.log 166**). Machine = plain x64 (`[RUNTIME_ARCH] emulated=False`), frozen build, server **`81.16.117.196:50052` over the public internet** (dev talks to a LAN server — the decisive environmental difference) | **(1) OPT-28 — the connectivity root cause.** EVERY socket error in the session is `Invalid response length header`; **not one timeout**. That is EOF on a half-open pooled socket: `is_connected()` is a flag, the pool handed out a connection the peer had closed, and `send_request` had **no retry** → `Search returned None` / `Update failed - no response from server`, and it did not self-heal because `return_connection()` re-pooled the corpse. Note the asymmetry it exposed: the DM client already had `REQUEST_MAX_RETRIES`/`connect_with_retry` and rode out the same fault — only the UI-facing client was unprotected. **(2) OPT-29 — the crash.** `native_fault.log`: access violation on the Qt main thread in `clear_table` → `setRowCount(0)`, called from `search_server`; last log line ms earlier = `[SEARCH-PERF] search_ms=208 rows=5` (45 rows on screen, a download live). Four event-loop producers mutate the table with no interlock, and ~180 cell widgets are destroyed synchronously inside the model reset. **(3) OPT-30 — the false success.** `_sync_worker` emitted `sync_completed` even when `update_report_status` failed; the toolbar then wrote `physician_approved`, painted the row green and closed the tab — **asserting a server state the server never had** — and the queued `statusError` popped after the tab was gone. **(4) Search "slowness" is server-side**, already proven by the in-app A/B probe (`SCAN is the cost … needs a SERVER-side index`) → OPT-32 | **39 new guard tests** across `tests/code/network/test_socket_pool_health.py` (16), `tests/code/ui_services/test_sync_status_strict_result.py` (14 incl. the ordering pin that the bail precedes the approve+close), `tests/code/ui_services/test_clear_table_crash_guard.py` (14). **Regression proof:** `tests/code/{network,ui_services,system,download_manager,storage}` = **1219 passed**; the 7 remaining failures were compared against the same suites with the edits `git stash`ed → **identical** (ino ×2, pin_overlay ×2, vtk_volume, mpr_tool_autoexit = pre-existing; echo_popup mirror drift = the user's own uncommitted EchoMind work). **Zero new failures.** Two existing guards had to be repaired, not weakened: `test_pin_overlay::test_stable_pinned_section_wired` and `test_study_downloaded_cache::test_invalidation_wired_into_status_update` pinned `clear_table` / `update_study_download_status` with a **fixed byte-window** (1400/1600 chars) — documenting those functions pushed the asserted code past the window. Both now extract the real function body via `ast` (same assertions, exact scope, no longer fragile). Mirror check: **none of the 4 edited source files is plugin-mirrored** (verified 413 files) | ✅ **All four shipped default-on, each with a kill switch** (`AIPACS_SOCKET_RECONNECT_RETRY`, `AIPACS_SOCKET_POOL_IDLE_S`, `AIPACS_SAFE_CLEAR_TABLE`, `AIPACS_SYNC_STRICT_RESULT`, `AIPACS_MODAL_CONN_FAILED`, `AIPACS_MODAL_STATUS_ERROR`). Files: `modules/network/socket_client.py`, `PacsClient/pacs/patient_tab/utils/patient_sync_service.py`, `…/patient_toolbar/toolbar_manager.py`, `…/home_ui/patient_table_widget.py`, `…/home_ui/home_search_service.py`. **ALL NEED LIVE VERIFY on the laptop** — (a) pull the network → search → restore → search recovers silently, no error storm; (b) 45+ rows + active download + two back-to-back searches with different result counts → no crash; (c) Sync Status with the network down → tab STAYS OPEN with Retry (and the study is NOT marked approved); with the network up → unchanged success + close. Report: `docs/reports/STABILITY_FREEZE_CONNECTIVITY_INVESTIGATION_2026-07-13.md` |

| 2026-07-14 | **STUDY-PK POISONING — the DB-dimension twin of OPT-26. A primary series read the SECONDARY study's DB rows, so series 2/3/4 of study 1 never displayed. FIXED default-on** (`AIPACS_PRIMARY_STUDY_PK_GUARD`) — and this is the **third** instance of one structural defect, which is now planned out as **OPT-35** | Patient **50238**: study 1 and study 2 BOTH have series **2/3/4** (study 1 series 3 = 90 images, SeriesUID …3882107555; study 2 series 3 = 30 images, SeriesUID …0005302607). On FIRST open, study 1's series 2/3 were blank; a **reopen** showed them (which is why it looked intermittent — the reopen merely rebuilt the poisoned tab state). Decisive log: `[MULTI-STUDY LOAD] key=3 -> study_path=<study1>/3 (slot=0)` (**disk path CORRECT**) but `FAST:meta_cache key=series_15208_n30` (**30 images = study 2**) → `[IDENTITY-GATE] SKIP render: incoming series=3 uid=…0005302607 != intended uid=…3882107555` | ROOT: `_effective_study_pk` (`_vc_load._load_single_series_on_demand`) defaults to `parent_widget.metadata_fixed['study_pk']` — **mutable TAB state**. A secondary-study load legitimately sets it to study 2's pk and **leaves the tab carrying it**; a later PRIMARY (plain-key) load then asks the DB for "series 3 of study 2" and, because the studies share series NUMBERS, gets back the wrong study's same-numbered series. The disk path was right (OPT-26 fixed that dimension) — the **DB** path was not. **The identity gate again did its job**: it refused to paint study 2's 30-image series as study 1's series 3 (a wrong-image-on-screen event); the blank viewport was the symptom. FIX: a plain (< 1 000 000) key ALWAYS belongs to the tab's PRIMARY study ⇒ pin its `study_pk` to the primary `study_uid`'s own pk (`find_study_pk_with_study_uid`, cached). Multi-study **and** plain-key gated + fail-open ⇒ single-study tabs and every secondary (offset-key) load are byte-identical (the 48101 per-series-pk fix is untouched). Logs `[STUDY-PK-GUARD]` | **21/21 viewer guard tests green** (`tests/code/viewer/test_primary_study_pk_guard.py` — the concrete 50238 sequence, offset keys keep their own pk, single-study byte-identical, fail-open ×2, kill switch — plus the 9 OPT-26 tests still green) | ⚠️ **shipped default-on; NEEDS live verify on 50238** (fresh open → load a study-2 series → then study 1's series 2/3/4 must show study 1's images; expect `[IDENTITY-GATE] SKIP` = **0**). **STRUCTURAL FINDING → OPT-35:** 48912 (disk path), 49836 (tab path), 50238 (DB pk) are **the same defect in three dimensions** — series identity is **re-derived at 4 stages from mutable tab state** instead of decided once, and we now carry **9 flags that all answer one question**. Per the user directive *"the pipeline should be straightforward for showing the series"*, the guard-stacking stops here: plan `docs/plans/architecture/SERIES_IDENTITY_PIPELINE_UNIFICATION_2026-07-14.md` (resolve an immutable `SeriesRef` ONCE at `change_series`, thread it through load/DB/cache/apply/render; retire the guards behind their own kill switches once they prove they never fire). This fix stays as the interim stop-gap |

| 2026-07-14 | **OPT-35 P0+P1+P2 — SERIES IDENTITY IS NOW RESOLVED ONCE AND THREADED, not re-derived 4× from mutable tab state. SHIPPED default-on** (`AIPACS_SERIESREF_SHADOW` / `_DISK` / `_DB`) | Not a new bug report — the STRUCTURAL root of the whole recurring class. 48912 (disk path), 49836 (tab repoint), 50238 (DB pk) are **one defect in three dimensions**: to show a series the code independently re-answered *"which study does this display key belong to?"* at four stages, each reading **tab-level** state (`import_folder_path` ~35 refs, `metadata_fixed['study_pk']` ~10 refs) as if it were **per-series** identity. Any multi-study patient whose studies share series NUMBERS found a stage where the derivations disagreed ⇒ **9 flags answering ONE question**, with guard #10 already predictable. User directive: *"the pipeline should be straightforward for showing the series and optimizing performance and speed."* | NEW pure `PacsClient/utils/series_ref.py` — frozen `SeriesRef(display_key, study_uid, study_pk, series_uid, series_number, series_path, study_slot, source)` + `build_series_ref_table` + `resolve_series_ref` (table → live entry → offset-key **slot fallback** → `derived`) + `shadow_compare`. Stdlib ONLY (no Qt/VTK/pydicom/**DB**) ⇒ fully unit-testable offscreen; `study_pk` is left None by the builder and filled by the consumer via the one rule. Consumed in `_vc_load._load_single_series_on_demand`: the disk location comes from the ref (**authoritative refs only** — a `derived` ref infers `SOURCE_PATH/<primary>/<key>` and would BREAK an externally-imported study, so it is never acted on), and **`study_pk = pk_of(ref.study_uid)`** replaces both opposing pk guards at once. The ref reads NO tab state, so it cannot be poisoned by a sibling load. Table cached on the identity of `_server_series_info` ⇒ **O(1) lookup per load** instead of `exists()` probes + a DB round-trip + guard scans (the "speed" half). Traces routed via `_identity_log` to the **viewer channel** — app.log did not reliably capture viewer INFO, which is precisely why the 49836 resolution trace was invisible and the bug had to be proven by reading SeriesInstanceUIDs off the DICOM | **40/40 new guard tests** (`tests/code/viewer/test_series_ref_authority.py`) — the three live bugs (50238 plain-key→primary + offset-key→own study, 49836 same-number-never-shares-a-folder, 48912 plain-key-never-into-a-previous-exam), the 50238 SEQUENCE (a secondary load cannot poison the next primary), **and a pin for every prior correction**: C1 (`parse_series_number` never raises on the literal `"None"`; an AST sweep FAILS if a bare `int()` on a series field reappears — the OPT-25/Roshana killer), C2 (synthetic 900001–999999 stays a PLAIN key; 999_999/1_000_000 boundary), C3 (`"02"` stays `"02"`), C8 (both pk polarities), C10 (display key is always a DIGIT string — ZetaBoost warmup), C11 (offset scheme intact), single-study `derived` refs are NOT authoritative, slot-fallback resolves a dropped entry, an out-of-range slot **refuses to guess** (never falls back to the primary), frozen-dataclass immutability, and the shadow oracle. **Regression proof:** `tests/code/{viewer,network,ui_services}` = **65 failed / 2493 passed** vs the SAME command with `_vc_load.py` `git stash`ed = **65 failed / 2453 passed** → `Compare-Object` on the FAILED sets = **IDENTICAL (65 = 65) ⇒ ZERO new failures**; the +40 are exactly the new tests. py_compile green on the Windows host; plugin mirrors **414/414** (neither edited file is mirrored) | ⚠️ **shipped default-on, each with a kill switch** (`=0` → the byte-identical legacy derivation). The **9 legacy guards stay ON as DETECTORS** — if the authority is right they are no-ops; **a guard or `[SERIESREF-SHADOW]`/`[SERIESREF-DB]` firing after this ships means the AUTHORITY is wrong and the phase must be reverted.** NEEDS LIVE VERIFY: open **50238** (fresh → load a study-2 series → then study 1's series 2/3/4 must show study 1's images), **49836**, **48912**, a **single-study** patient (must be byte-identical: zero `[SERIESREF]` redirects, zero shadow mismatches), and a **previous-exam** patient. Success signals: `[IDENTITY-GATE] SKIP` = **0**, `[SERIESREF-SHADOW] mismatch` = **0**, every guard firing = **0**, every dragged series renders. STAGED (gated on that output): P3 cache re-key by `series_uid` (⚠ ZetaBoost hard-requires a digit key), P4 DM/grow-lane, P5 retire the guards one at a time → **9 flags → 1**. Plan: `docs/plans/architecture/SERIES_IDENTITY_PIPELINE_UNIFICATION_2026-07-14.md` |

| 2026-07-14 | **OPT-36 — DRAG-AND-DROP DURING DOWNLOAD: the drop was silently ABANDONED back to the previous image. FIXED default-on** (`AIPACS_SETTLE_REQUIRES_DISPLAYED`, `AIPACS_RESUME_BUDGET_ON_PROGRESS`) | User report: *"the viewer wins the race, so the drag-and-drop is not completed and the viewer displays the previous image; dragging the same series again later works because the files are on disk by then — poor reliability."* Live trace (50336, previous-exam series **1000002** dragged mid-download): `14:35:03.083 [LOAD] Error … WinError 3` (study folder not created yet) → `14:35:03.129 "not resident yet — awaiting download"` + `RemoteSeriesDownloadAttached` (**the awaiting/spinner machinery worked correctly**) → **`14:35:05.126 disk-ready resume: series=1000002 settled (visible=1 disk=1 settled_visible=False exhausted=False authority=True) — cleared`** → `ViewportLoadingStateCleared` + a **FAKE `ViewportLoadSucceeded`**. Only a manual re-drag recovered it | **NOT the exception path** (that was correct) — the **resume watchdog** abandoned the drop, via TWO compounding bugs. **(A) `_disk_ready_complete` never saw `.part`.** The call site already computed `_has_part` and passed it to the sibling `_disk_series_settled`, but **not** to `_disk_ready_complete`. A previous exam is not in the DB yet ⇒ **no server `expected` count** ⇒ the weak stable-count fallback ran ⇒ a download that had written its FIRST file and not yet landed the second was *"stable at 1"* across two ticks ⇒ **a 1-of-N series was declared COMPLETE**. FIX: pass `has_part`; it gates ONLY the unknown-expected fallback (a stray `.part` must not block a known-and-met count). `has_part=False` default ⇒ legacy 3-arg call byte-identical. **(B) the settle stop-condition bypassed `_shows_awaited`.** `_settled_visible` honoured it (the 48101 fix) but `_authority_settled` / `_exhausted` were **OR'd in** and did not — so the state authority (a monotonic high-water mark of *displayed slices*, which says nothing about WHICH series is displayed) **overrode the live check that had CORRECTLY decided the viewport was not showing the awaited series**, cleared `_awaiting_series_number`, hid the spinner and faked success. FIX = **THE RULE: a viewport may only be declared SETTLED when it is ACTUALLY SHOWING THE AWAITED SERIES.** The 47084/47801 livelock this brake exists for has `_shows_awaited=True`, so gating on it **preserves that fix exactly** while closing the abandonment hole. **(C) the retry budget was consumed while the download was healthy** → now **refunded whenever the on-disk count GROWS**, so the cap trips only on a genuinely stuck download; on true exhaustion with the series still undisplayed the viewport shows an explicit "still loading" state and KEEPS the awaiting flag — never a silent revert. Also: a not-yet-created study folder (`WinError 3`) is an EXPECTED transient, now logged INFO instead of a false ERROR | **19/19 new guard tests** (`tests/code/viewer/test_drop_never_abandoned_to_previous_image.py`): the exact 50336 case (disk=1, expected unknown, `.part` in flight, `shows_awaited=False` → must NOT settle), `.part` gates ONLY the unknown-expected fallback, legacy 3-arg byte-identity, **the 47084 livelock stop is PRESERVED**, exhaustion cannot silently abandon, progress refunds the budget, kill switches, + wiring pins. **Regression proof:** `tests/code/viewer` with the fix and my 2 new files EXCLUDED = **60 failed / 1868 passed** vs the SAME command with both edited files `git stash`ed = **60 failed / 1868 passed** → newly-failing = **(none)**, newly-passing = (none) ⇒ **ZERO regressions**; the 59 new tests all pass. py_compile green on the host; plugin mirrors **414/414** (neither file is mirrored) | ⚠️ **shipped default-on with kill switches.** Delivers the requested contract: if the files are not on disk yet the viewport **STAYS in the loading state until the image is available**, or until the user drops another series (the replacement clear in `_vc_switch` is unchanged); it **NEVER** falls back to the previous image, and never reports a fake success. NEEDS LIVE VERIFY: drag a previous-exam series the instant its study starts downloading → the loading GIF persists, no intermediate revert, the images appear on their own **without a re-drag**; and confirm no resume livelock returns (`disk-ready resume … settled` must still fire once the series IS displayed). Files: `_vc_progressive.py`, `_vc_load.py` |

| 2026-07-14 | **OPT-37 — THUMBNAILS NEVER REFRESH WHEN THE SERVER GAINS IMAGES: the change detector is throttled for 5 minutes, which is exactly the window in which the study grows. FIXED default-on** (`AIPACS_RESYNC_TTL_INCOMPLETE`) | Patient **50264**: clicked the study when 3 series were on the server; ~5 min later the rest arrived (24 series / **1148 images**) and the count updated — but the thumbnails were **never re-requested**. Clicking again (patient-code filter) did nothing; clearing the code and switching the filter to **Yesterday** refreshed them instantly. Live trace: `17:21:21 [CT-072] study_resync_check result=grew server_series=2 new_series=2` (**detected**) → then EVERY click 17:22:43 → 17:25:52 logged `resync_start → resync_complete changed=0` **in 0.2 ms with NO `study_resync_check` at all** (no server query) | **The refresh machinery was NEVER broken.** The auto-resync (`_resync_patient_studies_from_server`, runs on every single-click) already detects growth and re-renders with **`_show_grouped_patient_studies(..., force_server_merge=True)`** — which refetches the thumbnails. **ROOT CAUSE = `_RESYNC_TTL_S = 300.0`**, a FLAT per-study throttle on the DETECTOR, applied to every study **including one the previous check had just found INCOMPLETE** (`result=grew`) — precisely the study that WILL change, and 5 minutes is precisely the window. So the first click detected `server_series=2`, marked the study checked, and every click for the next 5 min was throttled out before any server query. FIX: the TTL is now **per-study and completeness-aware** — full 300 s once CONFIRMED complete (preserves the 44113 "not every click hits the network" contract), **short TTL (10 s, still absorbs click-spam) while still growing**. Completeness = `content_version_store.get_synced_version(uid) is not None`, reliable **because `set_synced_version` is stamped ONLY on the not-needs-sync / disk-confirmed-complete branch**. **WHY THE FILTER CHANGE "FIXED" IT — a different CODE PATH, not a cache invalidation:** a patient-code search returns the patient's 2 studies as ONE aggregated row (`study_uids_count=2`) → `_hp_modules.py:579` routes to `_show_grouped_patient_studies`, which at `:687` contacts the server ONLY when `(not study_thumbs) or force_server_merge` — with 2 thumbnails on disk it renders **local-only, forever**. The "Yesterday" list produced a **single-study row** (`study_uids_count=1`) → `show_patient_studies` → the single-study **cache gate**, which DOES check the server (`grew=1 local_thumbs=2 server_series=24` → fetched 24). Two list filters, two render paths, only one with staleness detection | **19/19 new guard tests** (`tests/code/ui_services/test_resync_ttl_incomplete_study.py`): the 7 real click times from the 50264 trace must all re-check; a pin of the OLD flat-TTL behaviour showing it skipped every one of them; a CONFIRMED-COMPLETE study still honours the full 300 s TTL (44113 contract); a growing study is still throttled against click-spam (<10 s); never-checked/force/feature-off/kill-switch invariants; wiring pins incl. "the existing `force_server_merge=True` refresh path must not be forked". **Regression proof:** `tests/code/ui_services` = **3 failed / 468 passed** vs baseline **3 failed / 449 passed** → the SAME 3 pre-existing failures (`test_pin_overlay` ×2, `test_vtk_volume_service`); **zero regressions**, +19 new. Two `test_resync_on_reopen.py` throttle stubs were **REPAIRED, not weakened** (they bind only a subset of the mixin's methods via `SimpleNamespace`; the new per-study TTL needs `_resync_ttl_for` + `_study_confirmed_complete` bound — assertions unchanged) | ⚠️ **shipped default-on with kill switch** (`AIPACS_RESYNC_TTL_INCOMPLETE=0` → the flat 300 s TTL). NEEDS LIVE VERIFY on **50264**: click the study while it is still receiving images; within ~10 s of each click the resync must re-check (`study_resync_check result=grew`) and the thumbnails must refresh **without changing the search filter**. **KNOWN RESIDUAL (staged):** the GROUPED (multi-study) render path still has NO independent staleness check — it depends entirely on the resync firing `force_server_merge=True`. That is now restored, but a multi-study patient's grouped preview has no gate of its own; unifying it with the single-study cache gate is the follow-up (do NOT fork a second refresh mechanism — extend the resync). File: `_hp_series.py` (not plugin-mirrored) |

| 2026-07-16 | **OPT-38 — Automatic incremental update system SHIPPED default-on** (build manifest/store generation + static website structure + client check/notify/delta-download/apply/rollback; design `docs/plans/architecture/AUTO_UPDATE_SYSTEM_2026-07-16.md`) | no update mechanism at all: full installer hand-carried to every center per release; the existing update seam was manual-only, core = full installer, blocking urllib, no progress/rollback/restart | startup off-thread check (frozen-only default; consent-gated) → only CHANGED files download (content-addressed store; per-file SHA-256 verify; resume) → helper applies after clean exit with backup + automatic rollback on any failure → relaunch; installer path preserved as fallback; center config/User Data untouchable by construction (path allowlist at generator+client+helper) | **56/56 new guard tests** (`tests/code/auto_update/`: offline end-to-end delta cycle, tamper/corruption aborts, helper-script safety pins, flag policy, feed passthrough); builder+runtime+module_system = 100 passed / 6 pre-existing `test_nuitka_arm64_parity` fails (committed-state drift, confirmed unrelated via `git status`); tests CAUGHT a real bug pre-ship (Windows CRLF `write_text` broke `manifest_sha256` → `dump_manifest` now writes exact bytes). `.gitignore` fix: `build/` was silently untracking ALL of `tools/build/` (incl. `build_lite_viewer.py`) → negation added | ⚠️ **shipped default-on, NEEDS LIVE VERIFY** (design doc §10): real vN→vN+1 delta cycle on an installed build — notify ≤~30 s post-login, only changed bytes downloaded, restart lands new version with ALL center settings + DB intact, mid-apply failure rolls back to vN, installer fallback works. Files: `modules/auto_update/*` (new, not mirrored), `tools/build/generate_update_manifest.py` + `publish_update.py` (new), `website_update_service/` (new), edits: `build_release.py`, `aipacs_runtime.py` (additive feed keys), `main.py` (guarded service start), `installation_module_settings.py` |

| 2026-07-17 | **OPT-38 phase 2 — first REAL local publish + INCREMENTAL remote publishing shipped** | website side built by the site agent in `D:\laragon-www` (static tree + Laravel `updates-api` with WP-credential login + installer upload UI; its fake v100.0.0 test feed was live); publishing to a remote host would have re-uploaded the whole ~2.5 GB every release | (1) v3.5.3 delta generated from the EXISTING staged tree (no rebuild): 7,968 blobs / 525 MB store vs 626 MB installer; published 2.52 GB to the local Laragon site; ALL contract checks green over HTTP (headers, byte-exact `manifest_sha256` through Apache, %20 installer name) and the REAL client code (`summarize_available_updates` + `fetch_core_manifest`, fake 3.5.2 profile) returns `update_available` with a verified 8,877-file manifest. Two reality-driven fixes: payload allowlist gained the third staged root **`Qss/`** (`_ALLOWED_TOP_DIRS`, case-insensitive) and the client now **percent-encodes URLs** (spaces in installer names 400 on real servers). (2) `tools/build/remote_publish.py`: incremental upload — remote store listing is the truth; only the current manifest's missing/size-mismatched blobs transfer; blobs→core→modules→**feed LAST**+read-back byte-verify; installer opt-in; transports folder + FTPS (stdlib); credentials in gitignored `builder/publish_targets.json` (template committed); auto-publish from `build_release.py` for `"auto": true` targets, guarded (`AIPACS_UPDATE_REMOTE_PUBLISH=0`), upload failure never fails the build | **69/69 `tests/code/auto_update/`** incl. the core pin: release N+1 uploads ONLY changed blobs (hash-set equality), drift repair re-uploads a deleted blob, dry-run uploads nothing, feed-verify failure aborts without state, password never in logs, credentials file gitignore pin | ⚠️ NEEDS: first real FTPS publish against Hostinger (ai-pacs.com) + the installed-build vN→vN+1 apply/rollback cycle (still the last unverified piece). Files: `tools/build/remote_publish.py` (new), `publish_update.py` + `build_release.py` (extended), `builder/publish_targets.template.json` (new), `.gitignore` |
| 2026-07-20 | **OPT-39 — PREVIOUS-EXAM series won't grow after a mid-download drop until a LAYOUT SWITCH: the A1 grow watchdog can self-stop before the rest of the series arrives. FIXED default-on** (`AIPACS_PROGRESSIVE_ARMS_WATCHDOG`) | Patients **51234 / 51249** (other-PC `laptop khodam` logs, 2026-07-20): a cross-PatientID previous exam (3-image series, offset key `2000001`/`1000001`) dragged mid-download painted `open_series slices=1`; the download completed to **disk=3** but the series stuck at 1 until the user changed viewport LAYOUT (which re-loads it fresh from the now-complete disk → `slices=3`). The laptop build **predates OPT-35** (no `[SERIESREF-SHADOW]` anywhere in the session; the legacy `completion-verify` EXHAUSTED and nothing rescued it) — but a same-shaped edge exists in CURRENT source too | Verified the current-source A1 grow (`_maybe_grow_displayed_to_disk`) IS offset-key-correct: `_viewport_displayed_series_number` returns the STRING offset key `'2000001'`, `_server_series_info` is STRING-keyed (`_rebuild_multistudy_series_index:602 key=str(orig+offset)`) so `_resolve_canonical_series_identity` HITS → the previous exam's OWN `study_uid`+orig series, and A1 scandirs THAT folder + smooth-grows via `bridge.grow` (this is why 48695 live-verified A1 growing prev-exam keys). **The real residual: A1 runs ONLY inside `_dl_watchdog`, armed ONLY from the awaiting/spinner path (`_begin_download_wait`/`_update_download_spinner_text`) and self-stops when nothing is awaiting AND nothing is behind.** A drop that awaited, showed its first image (`_apply_progressive_to_target_viewer` CLEARS `_awaiting_series_number`), then hit a stop-check tick where `disk==displayed` and no `.part` was momentarily present → the watchdog stopped; the later images never triggered A1 → stuck until a layout switch. FIX: both progressive-activation paths (`_apply_progressive_to_target_viewer`, `_activate_progressive_mode_on_viewers`) now (re)arm the self-stopping watchdog when the series is known-incomplete (`total > avail`), so A1 is guaranteed to sweep a progressively-loaded-but-behind viewport regardless of await timing | **guard `tests/code/viewer/test_grow_previous_exam_offset_key.py`**: BEHAVIORAL — drives the REAL `_maybe_grow_displayed_to_disk` with a prev-exam offset key + a temp disk folder, proving it resolves the offset key to the previous exam's OWN folder (never `<primary>/2000001`), does NOT grow before the folder settles (2 ticks) or while a `.part` is present, and smooth-grows to 3 via `bridge.grow`; + WIRING pins that BOTH progressive paths arm the watchdog gated on the flag + `total>avail`. (The existing `test_grow_displayed_to_disk` was source-pin ONLY.) **py_compile + tests DEFERRED to the Windows/offscreen lane** — the Linux sandbox failed to start this whole session; edits + indentation verified via the Read tool | ⚠️ **shipped default-on** (`AIPACS_PROGRESSIVE_ARMS_WATCHDOG=0` → awaiting-only arming = byte-identical legacy). **The laptop must be updated to a build carrying OPT-35/36/39** — its installed build predates them (that is why these patients stuck). NEEDS LIVE VERIFY on 51234/51249: drag a previous-exam series the instant its study starts downloading → it grows to all images on its own with **NO layout switch** (watch `[GROW-DISPLAYED] … displayed` climbing). Files: `_vc_progressive.py` (not plugin-mirrored) |
| 2026-07-23 | **OPT-40 — Manual DOWNLOAD skipped a multi-study patient's newest study (often the scanned-document study); it only arrived later via the OPEN path's reconcile/back-fill. FIXED default-on** (`AIPACS_MANUAL_DL_PATIENT_DISCOVERY`) | Field report 2026-07-23: checkbox-select patient → Download → latest study missing; opening the patient later started the "missing" download. ROOT (three facts, one defect): (a) `GetPatientList` returns only the LATEST study UID per patient and grouped rows carry a `study_uids` list that BOTH download handlers (`_hp_modules._on_zeta_download_requested` — the live button — and `_hp_download._on_download_requested` — CD-burn/CommandBus) **ignored**, enqueueing only each row's single `study_uid` snapshot with NO server discovery; (b) the open/single-click paths DO full discovery (`_reconcile_patient_studies_on_click` → per-modality enumeration → `merge_study_uids`) — two pipelines for one intent (the 46630 late-growth signature, `patient_study_set_late_growth`); (c) `add_downloads` rejects ANY existing DM state incl. stale COMPLETED, and unlike the open back-fill/resync the manual path never reset it, so a grown previously-downloaded study was silently skipped too. FIX: new authority-routed coroutine in `_hp_download.py` (`_manual_download_with_patient_discovery`): expand each checked row to the patient's FULL study set via `_reconcile_patient_studies_on_click` (fallback `_resolve_patient_study_uids`, canonical owner-filtered union via `merge_study_uids`), reset stale COMPLETED/CANCELLED (mirror of FIX-010/46640), enrich fresh per study (`_get_or_fetch_series_info` force_refresh, bounded `asyncio.to_thread` ×8, cross-patient guard), payload via `build_download_payload`, ONE `add_downloads`. Both entry points gated through `_start_manual_download_with_discovery`; DM resume scan keeps it missing-only. This completes the `patient_study_set.py` migration roadmap item "manual download" (Intent.MANUAL_DOWNLOAD). | **guard `tests/code/ui_services/test_manual_download_patient_discovery.py` (13 tests)**: newest-server-study discovered + enqueued once; ignored row `study_uids` tail now used; resolver fallback; owner-filter drops foreign study (expansion AND enrich stages); stale COMPLETED reset / DOWNLOADING untouched; one add_downloads with all studies enriched; click never lost (expansion failure → raw selection, socket failure → un-enriched enqueue); kill switch + no-loop → legacy False. Regression sweep GREEN: ui_services + download_manager + 2026-05-27 guards + resync-grow + release-parity = **926 passed** (`-n 4`); mirrors 417/417 clean (PacsClient not mirrored). | ✅ **shipped default-on** (`AIPACS_MANUAL_DL_PATIENT_DISCOVERY=0` → byte-identical legacy row-only path). NEEDS LIVE VERIFY: multi-study patient (imaging + scanned-doc) → checkbox Download → DM queue shows ALL studies (`[MANUAL-DL] discovery: N row(s) → M study(ies)`, `manual_download_expanded` traces); then open → NO surprise late download. Files: `_hp_download.py`, `_hp_modules.py` (not plugin-mirrored). |
| 2026-07-23 | **OPT-41 — Small lag/FREEZE when clicking a patient on the home page right after startup: the OPT-22 browser-prewarm idle gate fired BEFORE the user's first interaction. FIXED default-on** (first-interaction requirement + `AIPACS_BROWSER_PREWARM_UNTOUCHED_MS` grace) | Live 13:51 session 2026-07-23 (pid 36612): F11 stall sampler caught **gap_ms=17031 / 11164** inside `modules/web_browser/prewarm.py::_construct_warm_view → view.setUrl("about:blank")` — the synchronous GUI-thread Chromium boot — landing ~45 s after launch, exactly as the user began clicking patients (queued clicks processed only after the boot; the click pipeline itself is HEALTHY — right-panel thumbnails in 255–278 ms, single-click resync non-blocking with enqueue correctly skipped). ROOT: OPT-22's gate measured idle as *no input since the watch started*; right after startup the user hasn't clicked YET, so the pre-input quiet (waiting for the home page to paint) satisfied the 5 s gap — the warm was guaranteed to fire at the worst possible moment (initial delay 20 s ≈ startup end). | FIX in `prewarm.py` (mirrored → re-synced 417/417): the idle gap qualifies ONLY after the first discrete input (`_seen_input`) — idle = a pause BETWEEN interactions, never "the user hasn't started yet"; a truly-away user (zero input) is covered by a 120 s untouched grace (`AIPACS_BROWSER_PREWARM_UNTOUCHED_MS`, 0 = legacy pre-input warm); busy-cap give-up unchanged. **guard `tests/code/web_browser/test_prewarm_idle_gate.py` (7 tests)**: pre-input quiet never warms; post-interaction idle warms (OPT-22 preserved); busy no-warm; untouched-grace warms; `=0` legacy restore; cap give-up; event filter marks first input. web_browser suite 24 passed. | ✅ **shipped default-on**. NEEDS LIVE VERIFY: restart app → click patients immediately — NO multi-second freeze in the first minute; later, after clicking around and pausing >5 s, log shows `browser prewarm: idle … after first interaction -> warming now` (the one-time warm cost lands in a real pause). Startup-phase stalls (window.show ~5.9 s, tab construction) remain OPT-01 territory, unchanged. |
| 2026-07-23 | **OPT-41b — "Optimize Chromium itself" EVALUATED with a real benchmark; flags are NOT the lever — shipped the measured fix instead: off-thread FILE WARM + release-on-ready** (`AIPACS_BROWSER_PREWARM_FILE_WARM`, default on) | User asked to make Chromium/browser boot faster. Built `tools/dev/bench_webengine_boot.py` (per-variant FRESH-process cold/warm boot phases) and ran on the workstation: **WARM boot ≈ 1.0 s total** (construct+setUrl ~0.6 s) and **NO flag set changes it beyond noise** (baseline 962–980 ms; --disable-gpu 940; slim 979; slim+no-sandbox 989). The 11–17 s live freezes = **COLD first boot**: warmup run 15.0 s (construct 1.1 s, ready 14.7 s) — ~200 MB WebEngine DLLs/resources read from disk + AV scan (MsMpEng) + Proxifier hooking QtWebEngineProcess spawns (both confirmed running). Conclusion: do NOT ship Chromium flags (measured no-op; GPU-off would only hurt real browsing). | Shipped in `prewarm.py` (mirrored, re-synced 417/417): (1) `_warm_webengine_files()` — daemon-thread sequential pre-read of QtWebEngineProcess.exe / icudtl.dat / *.pak / v8_context_snapshot.bin (600 MB cap) inside `_bg_import`, so the cold disk+AV cost is paid OFF the GUI thread and the GUI-thread construct hits warm cache (~0.6 s); (2) warm view now released on **loadFinished** (+1.5 s settle, 60 s failsafe) — the old fixed 2.5 s release destroyed the view MID-BOOT on cold starts (15 s to ready), wasting the warm. | **guards in `test_prewarm_idle_gate.py` (+4 → 11)**: file-warm reads exactly the engine-init files and skips unrelated ones; kill switch `=0` reads nothing; missing root never raises; source pins for daemon-thread wiring + release-on-loadFinished. web_browser suite 28 passed. | ✅ shipped default-on. Ops levers if still slow at a center: AV exclusion for the PySide6 dir / QtWebEngineProcess.exe, Proxifier rule excluding QtWebEngineProcess.exe. Out-of-process browser embed remains the only way to make even the warm ~0.6 s construct zero — not justified at current numbers. Bench artifacts: `user_data/test_reports/2026-07-23/webengine_bench.json`. |
| 2026-07-23 | **Threading & subprocess ARCHITECTURE REVIEW (no code change) — model confirmed correct; residuals ranked** | Full audit: codebase concurrency inventory + live psutil measurement + F8/F11 stall data. Model: GUI thread (qasync orchestration) → bounded thread pools for I/O + GIL-releasing C work → separate processes for GIL-bound CPU (decode B3.11 w/ restart+fallback, per-study download worker w/ DM-H4 orphan guard, ZetaBoost warmup w/ download throttle) → separate apps (Slicer MPR, Chromium). DB = per-thread pooled WAL connections w/ dead-thread pruning. Live idle: 68+21 threads ALL parked (0% CPU), 531+291 MB RSS, ZERO orphans. | Ranked residuals (all already tracked, none need redesign): (1) startup GUI-thread construction ~5.9 s window.show + ~1.3 s tab build → OPT-01 P1.4/OPT-12 deferral; (2) stack-drag contention p95 849 ms → §9 open item; (3) generic GC stalls → OPT-05; (4) per-widget seg executors — observation only; (5) decode pool=1 adequate per KPIs (do-not-touch). | Report: `docs/reports/THREADING_SUBPROCESS_ARCHITECTURE_REVIEW_2026-07-23.md`; artifacts: `concurrency_inventory.txt`, `live_process_snapshot.json` (user_data/test_reports/2026-07-23). | ✅ review complete; next perf work should take residual #1 (startup deferral, OPT-01 P1.4). |
| 2026-07-23 | **OPT-01 P1.4 / OPT-12 residual — startup construction INVESTIGATED: landing-page deferral NOT warranted; re-classified INHERENT + instrumentation added** | Followed the architecture-review "residual #1" recommendation and traced the real startup path. main.py:1311 `window.show()` paints only the LIGHTWEIGHT LOGIN window; the ~1.3 s `add_AIPacs_tab` + first paint happen AFTER login via the fade-anim `finished` → `_open_main_window` → `MainWindowWidget` → `add_AIPacs_tab` → `ControlPanelInterface.setupUi` → `home_widget`. So the "window.show ~5.9 s at main.py:1311" F11 attribution is a MIS-READ — that line is the login form; the real one-time cost is the post-login `MainWindowWidget.showMaximized()` first paint of the landing tri-pane. | **No behaviour change / no deferral shipped — deliberately.** Confirmed every SAFE deferral is already harvested: settings heavy tabs lazy-on-first-view, data-analysis on-demand placeholder, web-browser runtime-module placeholder, `apply_anti_aliasing` singleShot(0), `apply_theme` self-dedup (`_applied_theme_sig`), instance sweep (OPT-12 DONE), browser prewarm (OPT-22/41). The only eager build left is `home_widget` (the visible landing tri-pane `setup_left/center/right_panel`) — cannot be deferred without blanking the landing page (the exact "higher risk, tab/EchoMind/control_panel deps" the master plan §5A flagged when it chose NOT to optimize P1.4). The EchoMind CommandBus the plan floated as the deferral target is confirmed CHEAP (OPT-23: "registration only, not the freeze"). Instead added pure-logging `[STARTUP_STAGE] stage=mainwindow_construct` + `stage=mainwindow_show` timers in `_open_main_window` so the next restart pins post-login construct-vs-first-paint precisely (setupUi already times home_widget/settings/theme). | py_compile OK on `app_handler.py` (host). Pure-logging, ASCII-only, no control-flow change; `app_handler.py` not plugin-mirrored (verified). | ✅ investigation complete; **residual #1 re-classified INHERENT one-time post-login first paint — no risky landing-page deferral to be forced against the §5A decision + the stability mandate.** NEEDS (data-gate, not code): one restart → read `[STARTUP_STAGE] stage=mainwindow_construct / mainwindow_show` + the existing setupUi stages in app.log to confirm the construct-vs-paint split before any further action. Files: `app_handler.py`. |

| 2026-07-23 | **OPT-42 clinical: imported multi-frame Enhanced-MR showed the wrong frame — stale L2 pixel cache invalidated** (`_FAST_DISK_CACHE_POLICY_TAG` v4→v5, default-on) | Charles Walker MRI 2023 (14 multi-frame series, 20–140 frames each): a build before the `::f{frame_index}` cache-key fix (2026-07-01) cached the WRONG frame — all N frames of one file share ONE SOPInstanceUID, so the pre-fix bare key collided → frame-0 (ear) returned at every scroll position, surviving the upgrade on disk | bump the disk-cache policy tag (part of every key via `_disk_cache_decode_key`) so a v5 launch cannot read any v4 entry → one-time correct re-decode; single-frame series byte-identical | **exhaustively verified on the REAL study**: cold decode of all 14 series = 0 mismatches vs pydicom; write→read-back on 320×320 series 1101 = 0 mismatches; `get_rendered_frame` (the actual display method) = 26 distinct correct frames; live `viewer_diagnostics.log` shows `multiframe-expand slices=26`. Both disk caches (`pixel_cache`, `zeta_boost`) physically cleared. Guard `test_fast_multiframe.py` +2 (v5 pin + no-cross-frame-collision), 10 green | ⏳ **shipped default-on; NEEDS clean-reopen live verify** — code+data proven correct, remaining variable is the running tab's stale in-memory decode; user must close+reopen the patient (fresh per-tab pipeline reads the clean cache) → a middle frame (~13/26) must show a deep mid-brain sagittal slice. `lightweight_2d_pipeline.py` (plugin-mirrored, synced 417/417). Memory: `multiframe_stale_pixel_cache_2026-07-21.md` |

| 2026-07-24 | **OPT-42 part 3: multi-frame GEOMETRY — Enhanced files store geometry in functional groups, not top-level tags** (`AIPACS_FAST_MULTIFRAME_GEOMETRY` + `AIPACS_MPR_MULTIFRAME_GATE`, default-on) | comprehensive review request (angio/enhanced/ophthalmic/cine). Ground truth: the 14 *Charles Walker* Enhanced-MR series have ALL top-level IPP/IOP/PixelSpacing = None; geometry is entirely in Shared+Per-Frame Functional Groups. The FAST expansion copied the (absent → default) top-level geometry onto every frame → every frame IPP=(0,0,0)/IOP=identity/spacing=(1,1): frames display but measurements, slice-location overlay and reference lines have NO real geometry, and MPR builds a degenerate 1-slice volume (image_io documents "must not pass multi-frame files") | NEW pure `modules/viewer/fast/multiframe_geometry.py` (stdlib+pydicom): `read_frame_geometries` merges Shared+Per-Frame groups (PlanePosition/PlaneOrientation/PixelMeasures/FrameContent) → per-frame IPP/IOP/spacing; `classify_frames` → spatial_volume / multi_dimensional / multi_stack / temporal / unknown with `volume_frame_indices`. Wired into `_expand_multiframe_slices` (stamps each frame's SliceMeta with its OWN geometry; single-frame + multi-file series byte-identical). MPR gate at `_load_vtk_paths_responsive` blocks a single multi-frame file with a classified message (standard multi-file series never gated) | **all 14 real series classified correctly** (12 spatial_volume, 801 DWI=multi_dimensional 140→28, 101 SURVEY=multi_stack); per-frame IPP+spacing match pydicom exactly (0.75/0.47/1.95 mm vs the buggy 1.0); single-frame series unchanged (top-level IPP, frame_index None, no classification). Guard tests: `test_multiframe_geometry.py` (9) + `test_fast_multiframe.py` additions (per-frame stamping, single-frame-unchanged, MPR-gate helper, RLE-compressed decode). Geometry/sync/drag/identity viewer suite **455 passed, 0 new failures**. Mirror 418/418 (new file added) | ⏳ **shipped default-on; NEEDS live source-build verify** (spatial series: overlay slice-loc + ruler now correct; reference lines land on the right level next to a standard series; MPR on multi-frame shows the "not available" message not a 1-slice viewer; standard series fully unchanged). STAGED: the multi-frame→VTK volume BUILDER that would let a spatial multi-frame series open real MPR (VTK-domain, needs live validation; classifier already yields the frame list). Review: `docs/reports/MULTIFRAME_DICOM_HANDLING_REVIEW_2026-07-24.md`. Memory: `multiframe_dicom_handling_2026-07-24.md` |
| 2026-07-23 | **OPT-42 part 2: multi-frame "still missing frames while stacking/scrolling" — the background PREFETCH subprocess decoder is not frame-aware** (`AIPACS_FAST_MULTIFRAME_SUBPROC_GUARD`, default-on) | after part 1 (v5 tag) frames were correct on slow scroll but wrong/blank on FAST stack-scroll: `_decode_into_cache` warms via `decode_service.decode` (subprocess) which returns `arr[0]` for a multi-frame file (no frame_index), caching frame 0 under every frame's mem+disk key → re-poisoning the cache during interaction | for a multi-frame slice (`frame_index is not None`) force the frame-aware in-process decode instead of the subprocess (mirrors the existing empty-photometric / MG bypasses); ~6 ms/frame uncompressed | **PROVEN on the real series 1101 driving the actual `_decode_into_cache` prefetch path with the subprocess available: legacy = 25/26 frames wrong (all frame 0); guard on = 0 wrong.** Guard `test_fast_multiframe.py` +2 (flag/source pin + behavioural stub-service poison test), 12 green; mirror re-synced 417/417 | ⏳ **shipped default-on; NEEDS live stack-scroll verify** — reopen the patient and drag/wheel fast through a multi-frame series: every frame must appear (no frozen/blank frames). `lightweight_2d_pipeline.py` (plugin-mirrored) + `decode_service.py` note. Memory: `multiframe_stale_pixel_cache_2026-07-21.md` |

| 2026-07-24 | **OPT-42 part 3 follow-up: reference lines/geometry STILL broken — the consumer reads `metadata['instances']`, not the pipeline SliceMeta** (`AIPACS_MULTIFRAME_SYNC_INSTANCES`, default-on) | user: "still, the reference line and geometry are not working" after part 3. Stamping per-frame geometry into `SliceMeta` was necessary but not sufficient: `_pw_sync._geometry_instances_for_viewer` + the slice-location overlay read per-slice geometry from `viewer.metadata['instances']` (DB-built), and a single-file multi-frame series has ONE DB instance row → `len(instances)<=1` → consumers saw one geometry-less slice while the viewport scrolled N frames | pipeline `export_frame_instances()` emits one per-frame instance dict (own IPP/IOP/spacing/frame_index); FAST bridge factory `_vw_globals._create_qt_viewer_bridge` hands the bridge a SHALLOW-COPIED metadata whose `instances` is the per-frame list (shared thumbnail/DB metadata untouched → download-completeness keeps 1 instance). Only replaces when DB list shorter; many-file series export [] → byte-identical | end-to-end via the app's metadata path: 1 DB instance → 26 per-frame instances, 26 distinct positions, correct 0.75 mm spacing; sync instance-sort preserves frame order; +3 guard tests (export per-frame geometry, factory wiring pin, empty-for-single-frame); `_pw_sync`/geometry/reference suite 226 passed 0 new fails; mirror 418/418 | ⏳ **shipped default-on; NEEDS live verify** — reference lines land on the correct level with the multi-frame series next to a standard series; the slice-location overlay reads the current frame's position. `lightweight_2d_pipeline.py` (mirrored) + `_vw_globals.py` (not mirrored). Review §6 updated |

| 2026-07-24 | **OPT-43: Local patient-list incremental loading + Advanced-Search import-date filter** (`AIPACS_PROGRESSIVE_LOCAL_BG` default-on) | user: a very large Local Service list loads all-at-once → slow/lag/temporary freeze; and Advanced Patient Search has no import-date filter | **(A) Incremental loading:** `patient_table_widget.load_progressive` now renders a SMALL first batch (`_PROGRESSIVE_INITIAL_BATCH=20`) immediately, then streams the rest in the BACKGROUND on an idle `QTimer` (`_PROGRESSIVE_BG_BATCH=40`, 50 ms) — not only on scroll — with a generation guard so a new load invalidates stale timers; `search_local` engages progressive at `total>20` (was >100) and drops the forced 100-batch. **(B) Import-date filter:** `AdvancedSearchDialog` gains an Import-date group (Any / Imported Today / Yesterday / Two Days Ago / Custom Date / Date Range) → `get_query()` emits ordered `import_date_from`/`import_date_to` (yyyy-MM-dd); `database.search_patients_local` filters immutable `studies.imported_at` (local first-import time, NOT study_date) with an ordered range and half-open next-day upper bound; the dispatch `_on_advanced_search_requested` routes an import-date query to the LOCAL DB search (`search_local(extra_criteria=…)`) since import date is local-only, server path preserved | 13 guards (`test_local_incremental_and_import_date.py`; the two reversed-range guards failed before the 2026-08-29 hardening and pass afterward); broader Imported Date/Imported On/Advanced/Local-list/DB gate 94 passed; none of the touched files are plugin-mirrored (mirror verification retained) | ⏳ **shipped default-on; NEEDS live verify** — open Local with a large list → first ~20 appear instantly and the rest fill in while scrolling/interacting, no freeze; Advanced Search → Import date → Imported Today/Range (including reversed picker order) returns studies by first local import date. Files: `patient_table_widget.py`, `home_search_service.py`, `advanced_search_dialog.py`, `_hp_search.py`, `database/dicom_db.py`. Memory: `local_incremental_and_import_date_2026-07-24.md` |

| 2026-07-24 | **OPT-44: centralised OS light/dark-mode immunity — recurring "popup unreadable when the theme changes"** (`AIPACS_FORCE_APP_THEME` default-on) | recurring defect fixed one-popup-at-a-time; latest = Eagle Eye 3D Cursor windows. ROOT: `main.py` sets a global QSS but keeps the NATIVE Windows style + NO fixed `QPalette`, and the QSS only targets built-in dialog classes (QMessageBox/QInputDialog/QFileDialog/QToolTip) — there is no broad QDialog/QWidget/QLabel rule. So a CUSTOM dialog without a complete stylesheet falls back to the QApplication palette, which FOLLOWED the OS light/dark theme → broke. The 3D Cursor dialog sets light-on-dark label colours but NO background, so on a light OS palette its text vanished | `theme_manager.apply_global_app_theme(app, theme)` (called in `_apply_application_theme` BEFORE the stylesheet, and on every themeChange) installs **Fusion** (palette-driven, ignores the OS theme) + a fixed dark `QPalette` from the active theme (`build_application_palette`). The global QSS overrides both for every already-styled widget, so ONLY the broken un-styled popups change (OS-coloured → dark). Residual helper `apply_dialog_theme(widget)` + a token-based "consistent method" for any dialog that hard-codes a light colour | 6 guard tests (`test_app_theme_enforcement.py`: palette-is-dark-readable, installs-Fusion+palette, kill-switch, **un-styled QDialog+QLabel now dark-bg/light-text = the 3D-cursor class**, helper, main-wiring pin); theme regression (v2_style + ui_variant + dm_theme_retint) 68 passed 0 new fails; theme_manager/main.py NOT plugin-mirrored (418/418) | ⏳ **shipped default-on; NEEDS live verify** — open the 3D Cursor windows (and other custom popups) with Windows in LIGHT mode → dark background, readable text; toggle OS light/dark → app appearance unchanged; confirm no regression to already-styled main windows. Doc: `docs/design/THEMING_DIALOGS.md`. Memory: `app_theme_os_immunity_2026-07-24.md`. Files: `main.py`, `PacsClient/utils/theme_manager.py` |

| 2026-07-28 | **OPT-45 — up-to-2-MINUTE UI freeze under heavy download: the shared `dicom.db` had a flat 120 s busy_timeout on EVERY connection incl. the GUI thread. FIXED default-on (main GUI process → 5 s; download subprocess unchanged 120 s)** (`AIPACS_DB_SHORT_MAIN_TIMEOUT` / `AIPACS_DB_MAIN_BUSY_TIMEOUT_MS`) | Center "sanam" PC (x64, build 3.5.6): Windows Event Log (`.evtx`) recorded an **Application Hang `AppHangB1` / EventID 1002 `Cross-thread`** (pid 5644) at 2026-07-28 09:51:41 **while downloading a 600+150-image study**; the app recovered. (History on OLDER builds: hard `Qt6Core.dll` crashes `c0000005`/`c0000409` on 3.4.7/3.5.2 — a Qt object-lifetime/cross-thread family the 3.5.4+ stability work tamed; 3.5.6 showed only this hang.) The 13:19 app.log end was a CLEAN close, not a crash | **Audit (2 subagents + verified):** the download→UI progress bridge is already fully deferred/throttled (`home_download_service.on_series_progress` is GUI-thread + QTimer-coalesced; the DM's own hot path holds no long GUI lock; **all DM DB writes run in the download SUBPROCESS**) — NOT the block. ROOT = shared `dicom.db` **WAL write-lock** contention: `database/_pool.py` opened every connection with `timeout=300.0` + **`PRAGMA busy_timeout = 120000` (120 s)**. In WAL a reader never blocks on a writer, so only a **GUI-thread WRITE** (or read→write upgrade) freezes — up to **120 s** while the subprocess holds the write lock (`batch_insert_instances`). All main-process writes funnel through `database.get_db_connection()` with **no per-site SQLITE_BUSY retry** (verified: `manager.py` has zero retry loops) — so they rely entirely on that ceiling. FIX: `_resolve_db_timeouts()` makes the ceiling **role-aware** — the download subprocess (spawned mp child, `current_process().name != "MainProcess"`, plus an explicit `AIPACS_DB_ROLE=download-subprocess` marker set in `download_process_entry`) keeps the full **120 s** (never drops an instance row; DM-H5 retry intact), while the **main GUI process** uses **5 s** so a contended write fails fast + defers instead of freezing. SAFE: real WAL write-lock holds during a download are sub-second (per-batch commit), so 5 s ≫ any legitimate contention (writes virtually never raise); and a raised main-process write is recoverable (disk is the authority, the DB is a derived index reconcile/resync rewrites). **Does NOT create a new failure mode** — a contended write already raised at the old 120 s ceiling; 5 s only surfaces it sooner | py_compile OK (both files); **7/7 guard tests green** in-sandbox (`tests/code/system/test_db_main_busy_timeout.py`: main-default 5 s, kill-switch→120 s, tunable+clamped, subprocess-marker keeps 120 s + ignores tuning, spawned-child-name-alone keeps 120 s, + 2 source pins). `_resolve_db_timeouts` exercised across all branches (main/subprocess/kill/tune/clamp/bad) | ⚠️ **shipped default-ON**, kill switch `AIPACS_DB_SHORT_MAIN_TIMEOUT=0` = byte-identical flat 120 s; value tunable via `AIPACS_DB_MAIN_BUSY_TIMEOUT_MS` (clamped [1000, 120000]). **NEEDS LIVE VERIFY** on a heavy multi-series download: the UI stays responsive (no multi-second freeze / no `AppHangB1`), AND grep the run for main-process `"database is locked"` ERROR lines — if any appear, raise the value or move that specific write off-thread. `database/_pool.py` NOT plugin-mirrored (ships automatically); `download_process_entry.py` **IS** plugin-mirrored — the identical edit was applied host-side to the download_manager payload copy. Files: `database/_pool.py`, `modules/download_manager/workers/download_process_entry.py` |

| 2026-07-28 | **OPT-46 — CRASH-DURABLE DOWNLOAD QUEUE: interrupted downloads now auto-resume after a restart (disk task-specs). SHIPPED default-OFF** (`AIPACS_DM_QUEUE_PERSIST=1`) | Owner directive after OPT-45: the DM must behave like a REAL download manager (queue/priority/retry/**persist across crash**), not a sequential downloader. Capability review (2 subagents) confirmed 11/12 present; the ONE gap = the queue (PENDING/FAILED/priority/`retry_count`) lived **in-memory only** — `get_incomplete_downloads()`/the `download_progress` restore path is BUILT but UNWIRED (`DatabaseObserver` at `state_store.py:38` is a docstring example; live DM registers only `UIObserver`, `widget.py:232`). So a crash lost the pending QUEUE (DATA was already safe: disk + atomic `.part`→`os.replace` + resume scan) and the user had to re-open the patient | **Chose DISK task-specs over the DB path** (safer): new pure-stdlib `modules/download_manager/state/queue_persistence.py` writes each ENQUEUED study's SANITISED re-enqueue dict (identity + series list w/ image counts; **never** pixel/thumbnail bytes) to `<SOURCE_PATH>/<study_uid>/.dm_task.json` (atomic `.part`→`os.replace`). Wired: `add_downloads` persists on enqueue (`_dm_queue.py`); the DM widget defers `_restore_persisted_queue` 9 s post-init (`widget.py`) → `scan_incomplete_task_specs` re-feeds the still-incomplete specs to the SAME `add_downloads(..., start_immediately=False)` path (dedup/validation/priority/concurrency all reused). **Deliberately NOT the DatabaseObserver** — it persists on EVERY progress tick, which would reintroduce the exact main-thread `dicom.db` load OPT-45 removed; the disk spec adds **no DB write** (zero interaction with OPT-45) and is **self-cleaning** (the scan deletes the spec of any study already COMPLETE on disk and skips it) and **dedup-safe** (partial studies re-enqueue and the resume scan skips completed images — never a re-fetch; UNKNOWN expected count is never marked complete). `clear_task_spec` for explicit removal | **8/8 guard tests green** in-sandbox (`tests/code/download_manager/test_queue_persistence.py`: flag-default-off no-op, sanitise-drops-bytes, persist↔scan round-trip, complete→delete+skip, partial→re-enqueue+keep, requires-a-series, unknown-count-never-complete, wiring pins) + py_compile clean; all 3 files compile. **Plugin mirror synced host-side + byte-verified** (`_dm_queue.py`/`widget.py` mirrored; NEW `queue_persistence.py` added to the download_manager payload; `diff` = MATCH ×3, mirror compiles) | ⚠️ **shipped default-OFF** (changes startup behaviour = auto-resume of interrupted downloads → validate before default-on). Enable `AIPACS_DM_QUEUE_PERSIST=1`, then **NEEDS LIVE VERIFY**: start a multi-study download → kill the app mid-download → relaunch → within ~9 s the interrupted studies re-appear in the queue and RESUME from where they stopped (`[DM-QUEUE-RESTORE] re-enqueueing N …`), no re-fetch of completed images, no double-download, a fully-complete study is cleaned + skipped. Then flip default-on. Files: `modules/download_manager/state/queue_persistence.py` (new), `…/ui/widget/_dm_queue.py`, `…/ui/widget/widget.py` (all plugin-mirrored). **OPT-45 verified orthogonal + net-positive for the DM** (§ CLAUDE.md); remaining pre-existing DM notes (dead `DatabaseObserver`; concurrency hard-capped at 1) are unrelated/by-design |

| 2026-07-29 | **EVALUATION (no code change): series-thumbnail sidebar + download-status + drag-drop at start/load — HEALTHY; first-image latency on a FRESH SERVER open root-caused** | user asked to evaluate whether the patient-window series sidebar, the download function, and thumbnail drag-drop are optimized/correct at start+load. Evaluated against a LIVE session (patient 52583/NARGES NAJAFI, server open 00:27:49) + code | **Subsystem is well-optimized + correct** (live proof): open hot-path **4 ms**, right-panel thumbnails **57 ms** (cache-hit); sidebar renders chunked (token-cancelled, per-chunk `setUpdatesEnabled`+`activate` → no overlap, no freeze); download status on cards works (`[FAST-THUMB-STATE] downloading→blue → completed→green`, per-series progress bar O(1)); drag-drop smooth (`source=memory_cache cache_hit=True`, frame ~2 ms, 0 disk reads). **Root-caused the 9.4 s "first_series_visible"**: it is the double-click loading-screen duration until the DEFAULT series (201) is DISPLAYED — **download-bound on a fresh server study**. Timeline: series 201 (the display series, 38 img) finished downloading at **52 s** but the viewport didn't fire `change_series(201)` until **55 s**, first image **57.27 s** — a **~3–5 s window where the ready series is not yet shown** while the big series 202 (228 img) downloads concurrently (main-thread progress/DB traffic; 2 stalls 117 ms/197 ms during viewport construct). `_display_first_series_in_viewer` shows `lst_thumbnails_data[0]`, triggered by home_ui on the first series' download-complete | ⏳ **evaluation only — nothing shipped.** The sidebar/status/drag subsystem needs NO change. STAGED optimization candidate (needs live source-build validation, flag-gated per viewer rules): trigger the initial auto-display on the display series' FIRST IMAGE (progressive) rather than whole-series download-complete, and/or de-contend the concurrent large-series download from the initial paint — target the ~3–5 s ready-but-not-shown window. A LOCAL (already-downloaded) open has no download so is near-instant. Memory: `sidebar_download_drag_evaluation_2026-07-29.md` |

| 2026-07-29 | **Thumbnail-panel: 3 UI fixes (overlap-on-load residual, progress-bar z-order, active-series contrast)** (`AIPACS_SIDEBAR_ACTIVATE_ON_RENDER` / `AIPACS_THUMB_BAR_ABOVE_GLASS` / `AIPACS_ACTIVE_THUMB_STRONG`, all default-on) | user reported 3 issues in the series sidebar | **(1) Overlap-on-load** still recurred (multi-study / downloading opens): the 2026-07-19 fix bracketed only the chunked path; `_render_multistudy_grouped` + `show_exist_thumbnails` used `updateGeometry()` (posts a DEFERRED LayoutRequest) not `activate()`, so a repaint from `setUpdatesEnabled(True)` could land before layout → stacked-at-(0,0)-then-snap. FIX: both now `thumb_grid.activate()` synchronously while paint is off, before re-enable (the proven bracket). The CLAUDE.md "both other paths were already safe" claim was WRONG (corrected). **(2) Progress bar behind glass:** the per-series `dl_progress_bar` lived in `content_layout` (BELOW the full-card `glass_overlay`), so the ~78%-opaque glass dimmed it. FIX: bar is now a DIRECT child of the card `widget`, absolute bottom-strip geometry, `raise_()`d above the glass at creation + on every runtime glass re-raise (`_raise_dl_bar_above_glass`); the % text was already a glass child (crisp). **(3) Active-series contrast:** selected card was a faint 2px/alpha-30 accent → now 3.5px stroke + alpha-64 fill (accent theme token, light+dark), glow unchanged | real-widget verified (card 190×215; bar child-of-card, z-order glass(0)<bar(1) = bar on top; geometry (8,204,174,4); selected wires). Guards `test_thumbnail_panel_ui_fixes.py` (7) + updated `test_thumbnail_download_progress_bar.py`; thumbnail/sidebar/overlay/status suite **113 passed, 0 regressions**; mirror 420/420 (files not mirrored) | ⏳ **shipped default-on; NEEDS live verify** — open a >4-series AND a multi-study patient (no overlap/snap); download a series (progress bar crisp above the frosted glass); confirm the active series card is clearly distinct in light+dark. Files: `_pw_thumbnails.py`, `thumbnail_manager.py`. Memory: `thumbnail_panel_ui_fixes_2026-07-29.md` |

| 2026-07-29 | **OPT-47 — FIRST-OPEN MPR CRASH on large (700-800 slice) studies: GPU budget below the volume + a host-memory triple copy + a teardown that released nothing. FIXED default-on** (`AIPACS_MPR_VRT_GPU_BUDGET`, `AIPACS_ITK2VTK_SINGLE_COPY`, `AIPACS_MPR_FULL_TEARDOWN`) | Owner report: MPR on a ~700-800 slice study **crashes and closes the app on the FIRST attempt**; after relaunching, the SAME study opens fine. Today's dev logs: `[MPR-OPEN-KPI] standard_mpr_construct_ms=4568.4` on a 388-slice study (4 of the day's 5 stalls ≥1 s are MPR); app RSS max 2581 MB. Two independent read-only audits converged | **THREE compounding causes, all verified in source.** (1) **GPU budget**: `_mpr_views._create_3d_view` set a FIXED `SetMaxMemoryInBytes(512 MB)`; VTK applies its own MaxMemoryFraction (0.75) ⇒ **~384 MB effective** = `384MiB/(512·512·2B)` = **768 slices** — exactly the reported range. Past it the mapper partitions into several 3D textures while ALSO holding a gradient-opacity texture (`SetDisableGradientOpacity(0)`) + 4× MSAA, and it is `vtkGPUVolumeRayCastMapper` **not** `vtkSmartVolumeMapper` ⇒ **no CPU fallback**, so a failed GPU alloc is a driver-level access violation = silent process death (no Python traceback — consistent with the field report). (2) **Host triple copy**: `convert_itk2vtk` did `GetArrayFromImage` (copy#1) → `arr[:, ::-1, :]` (negative-stride view) → `if not C_CONTIGUOUS: arr.copy()` (copy#2, **always** fired) while the CALLER still held the ITK buffer ⇒ **~1.26 GB transient** at 800 slices (the in-function `del itk_image` freed nothing — it dropped only the local name). (3) **Teardown**: `_mpr_layout.cleanup()` was `Finalize()` ONLY — no `ReleaseGraphicsResources`, so **VRAM accumulated across a session**; that is precisely why a RELAUNCH (fresh VRAM) succeeded. FIXES: (1) size the cap from the real volume (`max(512MB, bytes×1.6)`) + drop the gradient texture ≥320 MB + drop MSAA ≥512 MB (graceful degradation; normal studies byte-identical); (2) `GetArrayViewFromImage` (zero-copy) + a single `np.ascontiguousarray` ⇒ **one** copy instead of two (−400 MB peak), ITK image deliberately NOT dropped before the copy (the view aliases its buffer); (3) full teardown — stop the unparented `_render_timer`, deactivate measurement tools, per-view `SetInputData(None)` → `RemoveAllViewProps` → `RemoveAllObservers` → `Disable` → **`ReleaseGraphicsResources` BEFORE `Finalize()`** (context must still be valid) → `RemoveRenderer`, then `viewers.clear()` (breaks the VRTInteractorStyle→self reference CYCLE) + `image_data = None`. Every step individually guarded; idempotent | **10/10 guard tests green** (`tests/code/viewer/test_mpr_large_volume_safety.py`) — incl. the decisive **byte-identity** test (single-copy result == legacy result, C-contiguous, and INDEPENDENT of the ITK buffer = no use-after-free), Y-flip preserved, the 768-slice arithmetic pinned as the documented defect, normal studies byte-identical, kill switches, + wiring pins (GL release ordered before Finalize). py_compile clean on all 3 files. NOTE: the broader `tests/code/viewer` suite could NOT run in-sandbox this session — the sandbox was reset and `PySide6` is absent (`sandbox_setup.sh` not re-run); those collection errors are environmental, not from these edits | ⚠️ **shipped default-on**, three independent kill switches. **None of the 3 files is plugin-mirrored** (ship automatically). **PRESERVES reconstruction quality**: no change to spacing/origin/direction matrix/slice order/Y-flip/X-flip/reslice interpolation; the only rendering change is on LARGE volumes (gradient-opacity modulation off, MSAA off) which today simply crash. **NEEDS LIVE VERIFY on a 700-800 slice study**: first open no longer crashes; `[MPR-VRT-BUDGET] large volume: …` appears; MPR open/close ×10 shows no monotonic private-bytes growth. **STAGED (not done, from the audits):** off-thread the `vtkImageFlip` (`widget.py:131-137`, a 4th full copy + ~1.3 s GUI stall) — `AIPACS_MPR_FLIP_OFFTHREAD`; extend the OpenGL pre-flight to the **6 unguarded VTK hosts** (only `toggle_zeta_mpr` calls it); `CurveMPR` leaks **3 GL contexts per open** (zero teardown); `viewer_3d.py` + `orthogonal/core/volume_loader.py` (triple-resident volume, no release); `vtk_widget/` render windows never `Finalize()`d (`cleanup_widget()` has no production caller); enable `AIPACS_VTK_VOLUME_CACHE` for the mpr domain only AFTER the teardown fix; delete dead `standard_mpr_viewer_original.py` (225 KB, 0 importers). Files: `_mpr_views.py`, `_mpr_layout.py`, `PacsClient/pacs/patient_tab/utils/utils.py` |

| 2026-08-01 | **OPT-48 Phase 1 SHIPPED — MPR open LATENCY at high slice counts** (#2 scalar range off-thread + #4 3D VRT on demand + #5 build progress; all default-on) | patient 52827, 512×512×672 CT: open **~21 s**, `standard_mpr_construct_ms=17944`, main thread blocked **19.3 s + 10.8 s** (~30 s frozen). `[MPR-STEP]` split: `vtkImageFlip.Update()` 3.3 s, `GetScalarRange()` 1.5 s, QVTK ctor/`winId()` 4.5 s, `vtkRenderer`/`AddRenderer` 2.4 s, `Initialize()` 2.7 s, crosshairs/text 1.2 s, **deferred 3D VRT ~9 s AFTER the KPI**. Volume LOAD (2.2 s) already off-thread ✅. OPT-47's `_heavy` path engaged — no crash; this is latency, not stability | **#2** the loader's existing worker warms `GetScalarRange()` (`_VtkLoadWorker`) and `StandardMPRViewer.__init__` reads the range from the **PRE-FLIP** volume — `vtkImageFlip` only PERMUTES voxels along X so the value set (and min/max) is identical; falls back to the flipped output on any error (`AIPACS_MPR_WARM_SCALAR_RANGE`, `AIPACS_MPR_SCALAR_RANGE_FROM_SOURCE`). **#4** volumes ≥200 slices no longer auto-build the VRT — the deferred-3D placeholder becomes a clickable "3D view (click to render)" cell; pure `should_defer_vrt_to_demand()` (garbage/unknown → legacy); below the threshold L1 auto-build is byte-identical; `[MPR-VRT-ON-DEMAND]` marker (`AIPACS_MPR_VRT_ON_DEMAND`, `..._SLICES`). **#5** modal busy dialog painted BEFORE the blocking construction, closed in a `finally`, only ≥200 slices (`AIPACS_MPR_BUILD_PROGRESS`, `..._SLICES`). `[MPR-OPEN-KPI]` extended with `slices=`/`vrt_on_demand=`/`warm_scalar_range=` | py_compile OK; **45 green** (new `test_mpr_open_latency_opt48.py` 11 + L1 defer-3D + OPT-47 large-volume + preflight); **full `tests/code/viewer` = 1938 passed / 0 failed** (28 skipped, 54 quarantine-xfail, 2 xpass). `test_decode_service::test_benchmark_subprocess_vs_inprocess` now trips the 120 s timeout — it scans the REAL patient store, which has grown; data-dependent + pre-existing, excluded from the run | ✅ geometry / slice order / orientation / the 3 diagnostic 2D planes / OPT-47 safety ALL untouched. **Expected: construct ≈17.9 → ≈16.4 s and the ~9 s post-open VRT freeze GONE** (paid only if the user opens 3D). NEEDS live re-measure on 52827 (compare `[MPR-OPEN-KPI]`). **Phase 2** = remove `vtkImageFlip` (−3.3 s, −352 MB peak; the OPT-47 "STAGED" item) — needs an L/R golden-image compare first. Report: `docs/reports/MPR_SLOW_HIGH_SLICE_COUNT_52827_2026-08-01.md`. Files: `_mpr_views.py`, `widget.py`, `toolbar_manager.py` (none plugin-mirrored) |

| 2026-08-01 | **OPT-48 Phase 2 SHIPPED — the MPR L/R (X) flip moved OFF the GUI thread, GEOMETRY-IDENTICAL** (`AIPACS_MPR_FLIP_OFFTHREAD`, default-on ≥200 slices) | `vtkImageFlip.Update()` = **3.3 s** of GUI-thread time on the 672-slice CT (a full second 352 MB volume copy) — the OPT-47 "STAGED" item | **The geometry-safe route was chosen deliberately.** The originally-proposed "fold the flip into the direction matrix/camera" WOULD change the radiological convention contract — every downstream consumer (reslice mappers, cameras, crosshairs, measurements, the on-screen L/R) assumes the volume is PHYSICALLY flipped — so it was **NOT** done. Instead: `StandardMPRViewer.build_lr_flipped_volume()` is now the SINGLE canonical flip (`vtkImageFlip`+`SetFilteredAxis(0)`+the field-data copy carrying `DirectionMatrix`/`ZetaAnatA`), and `toolbar_manager._prepare_mpr_flip_offthread()` runs THAT SAME function on a QThread behind the existing modal-progress pattern, handing the result in as `pre_flipped_image_data=`. The viewer VALIDATES it (dims must equal the source — a flip cannot change dims) and falls back to the inline flip on any mismatch/failure/flag-off. The other two `StandardMPRViewer(...)` call sites (dental host, CurveMPR) don't pass it → byte-identical | **10 new guard tests with REAL VTK** on a synthetic asymmetric volume (each voxel encodes its own x,y,z): (1) helper output **voxel-for-voxel identical** to the verbatim legacy inline flip + identical dims/spacing/origin; (2) output IS the X-mirror (`out[x]==src[nx-1-x]`) — the L/R correction still happens and nothing else moved; (3) `DirectionMatrix`+`ZetaAnatA` survive value-for-value; (4) ONE-flip-implementation pin (`widget.py` constructs `vtkImageFlip()` exactly once, so the paths cannot drift), dims-validation/fallback + call-site pins. `tests/code/viewer -k "mpr or orientation or geometry or canon"` = **404 passed**; **full `tests/code/viewer` = 1947 passed / 0 failed** | ✅ **no geometry or radiological-canon change — proven by byte-identity, not asserted.** Expected ~3.3 s more off the GUI thread (Phase 1+2 ≈ **−13.8 s** blocking on the 672-slice case). Peak memory unchanged (still 2 volumes): releasing the source after the flip is NOT safe (caller may reuse it — cache/other viewers) → separate later item. NEEDS live re-measure on 52827 (`[MPR-OPEN-KPI]` + `[MPR-FLIP] off-thread L/R flip done`) **and a visual L/R sanity check on a known-laterality study** |

| 2026-08-01 | **MPR reconstructed pane SHAKES while scrolling in the enlarged (double-click) view — FIXED default-on** (`AIPACS_MPR_STABLE_SCROLL=0` reverts) | owner report: after double-click-enlarging a reconstructed coronal/sagittal pane, scrolling the stack shows a slight shake; requirement = scrolling changes ONLY slice position | **Audit first:** the scroll path contains **no** `ResetCamera`/`ResetCameraClippingRange` (they live only in `zoom_to_fit`/`apply_view_transform`/view-creation/3D), never touches `SetParallelScale`/pan, and the double-click `_toggle_expand_view` moves no camera at all (it only re-parents the container + locks widget size) — enlarging MAGNIFIES an existing sub-pixel instability rather than causing it. **TWO real causes.** (1) the wheel handlers advanced `focal` and `pos` INDEPENDENTLY by a raw, possibly non-unit `scroll_dir` → any off-axis component slid the image sideways and the focal↔position distance crept (a guard test reproduced the creep over 200 notches). FIX: pure `stable_scroll_camera_step()` — normalise the direction, move the FOCAL by exactly `step×unit(dir)`, then carry the camera RIGIDLY (`pos = focal + pre-move offset`); caller pins `SetParallelScale` + `SetViewUp`. Oblique-safe (follows the pane's own direction, never a world axis); zero/invalid direction = no movement. (2) **the shimmer**: `_apply_native_plane_interpolation` gave the RECONSTRUCTED panes `SetResampleToScreenPixels(True)` — VTK re-derives that grid *"every time the camera changes"*, and the slice IS selected by moving the camera (`SliceAtFocalPointOn`), so every notch re-sampled onto a slightly different grid. The NATIVE pane already used `False` — **which is exactly why only the reconstructed panes shook**. FIX: reconstructed panes also use `False` (data-derived, camera-independent grid) while KEEPING `SetInterpolationTypeToLinear()` so smoothness is retained | **10 new guard tests** (`test_mpr_scroll_stability.py`): only the through-plane coord changes; direction AND distance invariant; oblique direction followed not axis-snapped; exact step length for an unnormalised direction; zero-direction no-move; 200 notches leave in-plane bit-identical; both handlers pin zoom+view-up; **no `ResetCamera` in the scroll path**; native-plane rule untouched. **Full `tests/code/viewer` = 1957 passed / 0 failed** | ✅ **no geometry/radiological-canon change**: slice plane, position, spacing, origin, bounds, direction matrix and `ZetaAnatA` untouched — cause 2 changes only the sampling grid the mapper renders ONTO, not what is sampled or where; cause 1 makes the camera motion strictly MORE constrained. **NEEDS LIVE CONFIRM**: double-click coronal + sagittal, scroll the full stack → no shake, zoom/centre fixed, smoothness still acceptable. If smoothness at high zoom is judged worse, cause 2 can be reverted independently. Report: `docs/reports/MPR_ENLARGED_SCROLL_JITTER_2026-08-01.md` |

| 2026-08-01 | **OPT-49 — MPR/VTK LIFECYCLE review + stabilization SHIPPED default-on** (re-entrancy guard, closed-viewer guard, teardown completion) | owner brief: review the whole MPR/VTK lifecycle (init / threading / memory / 10-step shutdown) for high-slice-count studies; scenarios (A) large study → MPR → close → another viewer, (B) MPR open/close ×2 → another patient → another reconstruction | **Audit first — most of the checklist was already satisfied and is now recorded so nobody re-audits it:** both MPR workers are created AND joined inside the function that makes them (`_load_vtk_paths_responsive`, `_prepare_mpr_flip_offthread`), neither is stored on `self` ⇒ **no worker can outlive the open**; the worker touches only the data object, never a widget/render window; OPT-47's release-GPU-before-`Finalize()` ordering is intact. **THREE real defects fixed.** **(1) NO re-entrancy guard on `toggle_zeta_mpr`** — reachable despite the modal dialogs (they pump the event loop) and directly callable by the EchoMind command bus / agent-control surface; a second entry built a SECOND complete pipeline. FIX `_mpr_open_in_progress`, placed AFTER the close branch and released in a `finally`. **(2) Deferred callbacks could reach VTK DURING teardown** — `view_name in self.viewers` only protects after `viewers.clear()` at the END of cleanup; the `try/except` in `_apply_interaction_update` catches nothing because the fault is native. FIX `_mpr_closed = True` as cleanup's FIRST statement + `_mpr_is_closed()` early-return in all 5 deferred entry points. **(3) Teardown left the object graph alive** — 6 containers never cleared (incl. `_view_containers`: a QWidget pins its whole parent chain) + `_viewport_activate_cb` (a closure over the ToolbarManager + host cell) + `_diag`, and `_interaction_timer` never stopped. FIX new step 7 inside `AIPACS_MPR_FULL_TEARDOWN`: clear all 6, drop both cross-module refs, stop **+ disconnect + null** all 3 timers | **34 new guard tests** (`test_mpr_lifecycle_guard.py`) incl. a BEHAVIOURAL one that execs the real `_apply_interaction_update` against a recorder (closed ⇒ zero calls; open ⇒ normal call set), the "guard must not block closing" pin, the "released in a finally" pin, teardown ordering + completeness, the OPT-47 regression pins, and the worker-join pin. **`tests/code/viewer` + `tests/code/system` = 2331 passed, 0 new failures.** The 4 remaining `test_local_search_progressive` fails were proven PRE-EXISTING by stashing all 4 source edits and re-running on clean HEAD. Mirrors 420/420 (none of the 4 files is mirrored). Two pre-existing tests REPAIRED not weakened | ✅ **no geometry / radiological-canon change — enforced mechanically**: `test_lifecycle_work_changed_no_geometry_api` + `test_closed_guards_added_no_geometry_calls` forbid `SetSpacing`/`SetOrigin`/`SetDirectionMatrix`/`SetFilteredAxis`/`SetResampleToScreenPixels`/`SetParallelScale`/`SetViewUp`/`SetFocalPoint`/`SetPosition`/`ResetCamera` in every line added. **DELIBERATELY NOT DONE**: the 2nd full volume copy (releasing the source after the flip is unsafe — the caller may reuse it; folding the flip into the direction matrix is a geometry change, see OPT-48 Phase 2), and worker cancellation (`setCancelButton(None)` is intentional — a half-loaded volume is not a valid MPR input). **NEEDS live verify**: scenarios A/B with RSS watched across cycles; rapid double-click must log `[MPR-LIFECYCLE] open ignored`; close-during-load + close-tab-with-MPR-open must produce no `already deleted` RuntimeError and no VTK-framed access violation. Report: `docs/reports/MPR_VTK_LIFECYCLE_REVIEW_2026-08-01.md` |

| 2026-08-03 | **OPT-50 — LOCAL PATIENT LIST: three quadratic terms + 4000 per-row SQLite connections removed. SHIPPED default-on** (`AIPACS_LIST_UID_INDEX`, `AIPACS_LIST_DB_PREFETCH`, `AIPACS_LIST_BATCH_FINALIZE`, `AIPACS_LIST_REPORT_MEMO`, `AIPACS_LIST_PATHS_OFFTHREAD`, `AIPACS_INO_STORE_CACHE`) | user 2026-08-03: the Local list is still too slow past ~2000 studies — loading, filters, search, sort by Imported Date, re-render; the UI freezes. Asked for a first-50-fast / incremental redesign | **Measured before designing** (new `tests/bench/bench_local_patient_list.py` + cProfile). OPT-43 fixed *first paint*, not *cost*: the background streamer still paid an O(N²) bill. **(1)** the per-study dedup scanned every row per insert (1 999 000 lookups @2000) → a study_uid presence SET, scan only on a real duplicate; **(2)** `check_patient_visited` and `_resolve_imported_on` each opened a SQLite connection PER ROW (4000) → two batched worker queries (new `get_existing_patient_ids`) priming the widget before the render; **(3)** `_finalize_bulk_insert_ui` ran a full-table anti-alias + sort + count after every 40-row batch (~50×) → incremental anti-alias over the new rows only (new `apply_anti_aliasing_to_rows`), count skipped while streaming, sort debounced into ONE settle pass; **(4)** profiling showed the Assign/Report columns were **half the total** — `ino_assignment_server_state._load` alone 6.7 s / 2400 calls @800 rows, because two JSON stores were re-opened and re-parsed three times per row → mtime+size-guarded read caches in `_load`, `read_all` and `_config`, with explicit write invalidation and copy-out. Plus `render_one`'s per-row `stat`/`opendir` moved to the worker (head-of-list resolved before paint, tail in the background, inline fallback), `report_status_for_reception` memoised for the render pass, `_programmatic_sort` reading one field per row instead of ~30, and five missing SQLite indexes | **46 new guard tests** (`test_local_list_render_opt50.py`) covering: batched-lookup correctness incl. >999-var chunking, index presence, idempotent `init_database`, presence-set semantics + rebuild-from-pinned-rows, prime-hits-no-DB / un-primed-falls-back / misses-primed-as-empty, settle sort honours the ACTIVE column + waits while streaming, anti-alias range isolation, memo never caches an empty scan + setdefault-keeps-first-row + live-again-when-disarmed, store caches read-once-until-changed + copy-out + kill switch, off-thread path stamping + never-raises, and every kill switch defaulting ON. **`tests/code/network` + `database` + `storage` = 300 passed / 0 failed.** `tests/code/ui_services` = 662, **2 failures BOTH PROVEN PRE-EXISTING** (`test_status_flags_are_stashed_on_the_widget_to_avoid_recompute`: the same 1500-char source window extracted from `git show HEAD` puts `container.status_rank` at offset **2272 in BOTH** — a stale guard whose window never grew when the 2026-08-02 async-status docstring did; `test_login_carries_the_user_identity_ids`: untouched area, my diff's earliest hunk is 800 lines below it). Three progressive tests REPAIRED not weakened — the test double gained the real `_begin_report_status_memo` borrowed from the class, so it cannot drift | ⚠️ **shipped default-on; six independent kill switches; NEEDS LIVE VERIFY on the real >2000-study database.** Bench @2000: **full load 42.7 s → 13.9 s, worst GUI block 1139 ms → 271 ms, first paint 285 ms → 114 ms, db_calls 4000 → 1, dedup-scan rows 1 999 000 → 0, anti-alias cells 832 000 → 32 000.** Live checks: (a) switch to Local on the big DB — first rows instantly, typing/scrolling/tab-switch stay responsive while it fills; (b) **sort by Imported Date and let it finish — every row must be in order, not just the first 20** (that was silently broken before); (c) the Assign and Report columns must still show the same icons/colours as before (the store caches are the highest-value change and the one to revert first via `AIPACS_INO_STORE_CACHE=0` if anything looks stale); (d) change an assignment, then re-search — the new state must appear. **NOTE the remaining cost is now linear widget construction (~6 ms/row: 4 `setCellWidget` + ~16 items + per-row `setStyleSheet`); going materially below ~14 s for 2000 rows needs DB-side paging (`ORDER BY … LIMIT`) — deliberately NOT done here, see the Stage-2 note.** Files: `patient_table_widget.py`, `home_search_service.py`, `database/dicom_db.py`, `PacsClient/utils/font_manager.py`, `modules/network/ino_assignment{,_history,_server_state}.py` (none plugin-mirrored). Report: `docs/reports/LOCAL_PATIENT_LIST_RENDER_OPT50_2026-08-03.md`. Memory: `local_list_render_opt50_2026-08-03.md` |

| 2026-08-03 | **OPT-51 Reliability/CLINICAL-CRASH: Eagle Eye MG/DX server request could ABORT the Python process (running QThread GC'd/overwritten). FIXED default-on** (`AIPACS_EAGLE_WORKER_LIFECYCLE`) | User report: "the Python process involved in Eagle Eye appears to crash while the request is being executed"; also review duplicate uploads / stuck requests / uncontrolled retries. Scope clarified first: the CLIENT does **not** prepare/decode/upload pixels — it POSTs `{study_id,…}` to `/api/v1/run_full_analysis` and the AI SERVER pulls DICOM from its own PACS; so image-prep / multi-view upload / native decode are **not on the client** (no `pixel_array`/`cv2`/`Image.open` in the path). The crash is worker-lifecycle, not networking/imaging | ROOT: `AIChatInteractorStyle._current_worker = worker` was the ONLY strong ref to the running `MamoWorker`/`BoneAgeWorker` QThread — never cleared, never `deleteLater`-d, NO re-entrancy guard ⇒ `QThread: Destroyed while thread is still running` (Qt abort): (1) a 2nd run OVERWROTE the ref to the first still-running thread → GC of a live QThread (the overlay auto-hid at 120 s while the request ran to 240 s → UI looked idle → user re-clicked); (2) tab/patient close mid-request dropped the only ref. FIX (`modules/viewer/interactor_styles/ai_chat_interactorstyle.py`, plugin-mirrored): module-level `_LIVE_AI_WORKERS` set holds each worker until `finished`/`error` (then `deleteLater`); `_register_ai_worker` wires exactly-once GUI-thread cleanup (clears `_current_worker` only if unchanged); `_ai_worker_busy()` re-entrancy guard on BOTH `start_mg_process`+`start_dx_process` (kills duplicate server jobs + the overwrite crash; dead-C++→not-busy). Plus fail-fast `(10,240)`/`(10,360)` connect/read timeouts (a scalar applied to BOTH phases → dead host hung the thread = "stuck request") and overlay safety 120 s→260 s (>read budget) so it can't vanish mid-request and invite the re-click. Same idiom as EchoMind `_ORPHANED_WORKERS`. `run()` try/except boundary + non-OK-body-before-raise (502 detail) + atomic streamed download (`with requests.get(stream=True)`+`with open()` → handles always closed) already correct, unchanged | **11/11 guard tests** (`tests/code/ai_imaging/test_eagle_worker_lifecycle.py`: flag+kill-switch; running worker strongly-ref'd+busy; finished/error clear+free; deleted-C++ not-busy; 2nd worker doesn't evict 1st; source-pins for guards/registration/timeout-tuples/260 s). ai_imaging **236 passed, 8 xfailed**. Mirror synced+verified **422/422** (host-side) | ✅ shipped default-on (`=0` = byte-identical legacy single-ref). HIGH severity (a clinical AI path could abort the process). Report: `docs/reports/EAGLE_EYE_MG_WORKER_CRASH_OPT51_2026-08-03.md`. NEEDS live source-build verify: re-click during a run → "already running", no 2nd job, no crash; dead host → controlled error ~10 s; close tab mid-request → no `QThread: Destroyed while…` abort |

| 2026-08-04 | **OPT-52 Clinical-correctness: Eagle Eye showed the CC image when scrolling the MLO viewport. FIXED default-on** (`AIPACS_DISABLE_SERIES_NAME_PAIRING_GUARD` = kill switch) | user 2026-08-04 with a screenshot and the patient code: "the MLO layout appears to contain two images/slices… when scrolling inside the MLO layout, it also starts showing the CC image". Asked to check series grouping, view-position metadata, MLO-vs-CC DICOM tags, Series/SOP-UID grouping, stack building and viewer navigation, and to trace the exact study | **Traced end-to-end on PID 52795 / study_pk 2253.** The data is clean: four MG series (R-CC, L-CC, R-MLO, L-MLO), **one image each**, distinct Series and SOP UIDs — so grouping, view-position metadata and UID handling were all correct and the fault was downstream in *paired-series* selection. ROOT: `series_name` is **NULL** in the DB for these rows, and `load_series_preview` loads series metadata DB-first (`get_series_by_series_pk`), so the key is present with value `None`. Six call sites did `str(series_info.get('series_name',''))` — **`str(None)` is the truthy literal `'None'`** — so `_rebuild_series_index`'s `if series_name:` guard passed and built `_paired_series_map = {'None': ['2','4','6','8']}`. `_vc_switch.py:1446` hit that key, took the first other number in the bucket and attached it as `vtk_image_data_2` (the MG gate was useless — all four are MG), so `_vw_series.py:1199` built `CustomCombineImageViewers`: `get_count_of_slices()` = `Z1+Z2` = 2 (the bogus "1 / 2") and `set_slice(1)` → `change_local_series('series_2')` = **the CC image on scroll**. Confirmed in the user's own `viewer_diagnostics.log` (`bind_source=switch_series_combined`, `Combined: True`, series 2 fetched as the partner of series 4). Three more sites had the same bug via a bare `==` (`None == None` is True). FIX: new `PacsClient/utils/series_pairing.py` — `normalize_series_name()` collapses `None`/`'None'`/`''`/whitespace/`'null'`/`'nan'`/`'unknown'`/`'n/a'`/`'-'` to `''`, `can_pair_series_names()` requires the **same non-empty real** name — applied at `_vc_backend`, `_vc_switch`, `_vc_warmup`, `_vc_layout`, `_pw_viewers`, `_pw_series` ×2. The flat metadata cache keeps the RAW value and `_series_number_to_index` is untouched; genuine shared-name MG studies still pair exactly as before | **33 new guard tests** (`tests/code/viewer/test_mg_series_pairing_guard.py`) covering the placeholder set, the `str(None)` regression itself, genuine names still pairing, distinct names staying separate, the untouched flat cache + fast index, and the kill switch reproducing the original bad bucket. **End-to-end against the LIVE database** (`_recovery/probe_pair_map_52795.py`): guard ON → `{}`, guard OFF → `{'None': ['2','4','6','8']}` — the legacy run reproduces the defect exactly. **`tests/code/viewer` 2099 passed / 0 new failures**; `tests/code/ui_services` 707 passed / 2 failed (both the known pre-existing stale positional guards) | ✅ shipped default-on; `=1` restores byte-equivalent legacy behaviour. **NEEDS live verify:** PID 52795 MLO must read `1 / 1`; scrolling MLO must never show CC; the log must show `Combined: False` / `bind_source=switch_series` for series 4 and 6; and a study that legitimately uses paired MG series must still open the combined viewer. Report: `docs/reports/EAGLE_EYE_MLO_CC_MIXING_MG_PAIR_1_2026-08-04.md`. **Issue 1 of the same report (duplicate `Advanced` / `Show / Hide Box` controls) is NOT yet root-caused** — duplicate widget creation, repeated signal connections, a lesion-count-triggered toolbar, a second overlay set from the combined viewer, and stacked `AIVTKWidget`s in the captured log were each ruled out; the one remaining hypothesis is layout reinitialisation orphaning a previous widget. Re-check it after this fix is live, since the combined viewer is what made this study render abnormally |

| 2026-08-04 | **TS-1 Build/CLINICAL-CORRECTNESS: compressed-DICOM codec plugins were bundled by ACCIDENT, not by declaration. FIXED + GATED** | user 2026-08-04: the server team is adding compressed transfer syntaxes to save bandwidth; a first test showed the viewport not displaying the image. Asked for a full review of both viewers, the pydicom decoder configuration, bundling, and a shared decoder | **Review first, measured not assumed** (`docs/reports/COMPRESSED_TRANSFER_SYNTAX_REVIEW_2026-08-04.md`). The app's design is **decompress-at-import** (`import_preview_dialog._decompress_file_to_destination`, one caller, module-private), so both viewers assume uncompressed on disk. **(A)** the download manager does NOT normalize transfer syntax — its `is_compressed` is a **gzip transport envelope** (`socket_client.py:1359-1361`) — so server-side compression lands compressed in storage, bypassing the only normalization the app has; every network route shares this, and `multi.py:141` additionally stamps `ExplicitVRLittleEndian` on data it never decompressed (latent corruption). **(B)** `builder/spec/appA_workstation.spec` — the spec `build_release.py:44` feeds PyInstaller — declared **neither** the codec hidden-imports **nor** `copy_metadata`, while the Nuitka spec, the legacy `AIPacs.spec` and the Lite Viewer all did. **(C)** `_detect_decoder_capabilities` probes by IMPORT while `_missing_decoder_packages` probes by METADATA — they disagree in a frozen build — and `_is_transfer_syntax_supported` gates JPEG-LS on `pyjpegls`/GDCM (neither installed) even though JPEG-LS decodes fine here via pylibjpeg-libjpeg. **Decode matrix measured on pydicom's reference corpus + a synthetic corpus, both substrates:** RLE 9/9, JPEG Baseline 13/13, JPEG Lossless 1/1, JPEG-LS 1/1, J2K lossless 3/3 on both; **one real divergence — 12-bit JPEG Extended (`…4.51`) FAILS in pydicom (Fast) and PASSES in SimpleITK (Advanced)** (`libjpeg -1038`; Pillow "Unsupported JPEG data precision 12"), which matters for CR/DX/MG. Also GDCM inverts MONOCHROME1→MONOCHROME2 while pydicom does not (pre-existing, not compression-specific) | **SCOPE THIS PASS (user-chosen): build fix + gates + read-only detection only.** New `spec_utils.CODEC_PACKAGES` single source of truth + `codec_hiddenimports()` + `codec_metadata_datas(copy_metadata)`; `appA_workstation.spec` now declares BOTH halves (metadata added to `datas` before the dedup line); `release_gate` gains `check_codec_plugins_available()` (pre-build: a decoder registered for all 7 required syntaxes) and `check_stage_codec_metadata()` (post-stage: dist-info **and** `entry_points.txt` staged), both wired in. New read-only `tools/diagnostics/scan_compressed_studies.py`. **18/18 new tests** (`tests/code/builder/test_codec_bundling.py`) incl. reproducing the zero-decoder failure by stripping entry points, and gate-fails-when-dist-info-absent **and** when present-without-entry_points. **Diff is 214 insertions / 1 deletion.** `tests/code/builder` 84 passed / 7 failed — all 7 PRE-EXISTING (6 ARM64-parity regressions, see the untracked `builder/docs/ARM64_RESTORE_nuitka_2026-08-02.patch`; 1 stale-stage config parity calling a function this pass never touched). `tests/code/system` 322 passed / 4 failed = the documented pre-existing `test_local_search_progressive` set | ✅ shipped. **IMPORTANT CORRECTION recorded in the report §4.1:** an initial STATIC reading concluded the shipped installer was already failing on JPEG 2000. **Inspecting the real staged artifact disproved that** — all 4 codec dist-info dirs (with `entry_points.txt`) and `_libjpeg`/`_openjpeg`/`rle` .pyd are present, so the current build decodes correctly. The metadata was arriving **incidentally** via PyInstaller 6.20's own hook set (no local hook, no contrib pylibjpeg hook, and `hook-pydicom.py` copies no metadata). So B's severity is **"a clinical decode capability depended on undeclared, version-specific build-tool behaviour with no gate"** — not "currently broken". **On-disk scan of real storage: 6714 instances / 499 studies → 5 affected** (4× JPEG Lossless SV1, 1× RLE, **0 JPEG 2000** — the rollout has not reached local storage). **STILL OPEN, deliberately not done:** ingest normalization (§3), the shared runtime decoder (§6), the 12-bit JPEG Extended Fast-viewer gap, and defect C. Report: `docs/reports/COMPRESSED_TRANSFER_SYNTAX_REVIEW_2026-08-04.md` |

| 2026-08-05 | **DM-R1 Reliability/BANDWIDTH: a series retry WIPED the series folder and re-downloaded everything — 5 consecutive full re-transfers of one series on a live/growing study. FIXED default-on** (`AIPACS_DM_RETRY_KEEP_FILES=0` = legacy wipe) | user 2026-08-05: "check the log for patient 53346 it start download with delay and also redownload the serries 203 multiple of times" | **Log-first diagnosis** (`docs/reports/DM_53346_DELAY_AND_SERIES_203_REDOWNLOAD_2026-08-05.md`, all claims with `dl:` line refs). The study was a LIVE acquisition — series 203 grew 71→191→260 during the session, new series appeared mid-way. **Re-download ROOT:** `_dm_retry._bg_series_retry` deleted the whole series folder whenever `existing_count >= expected_count`, with `expected_count` from the STALE in-memory task — for a growing study the retry fires precisely BECAUSE the server count grew past that snapshot, so disk(71)>=stale(71) → `shutil.rmtree` → full re-download `skipped=0`. Measured: **8 download rounds for series 203, rounds 1–5 each wiped + re-transferred all 71 instances (~230 MB total where ~40 MB + increments sufficed)**, each round in a fresh subprocess. Trigger loop: the viewer's missing-slice poll (`request_object` → `request_critical_series`, one per 250 ms — a growing or just-wiped series always has missing slices; intent tokens 2→19+ in seconds). The wipe also RACED the viewer holding the displayed instance open → `PermissionError WinError 32` mid-rmtree (dl:11604-11617) → partial deletes; round 6's failed wipe left 38 files which the downloader correctly SKIPPED — accidental proof that file-level resume works whenever the delete doesn't happen (rounds 7-8 with refreshed counts skipped 194). **Delay ROOT (documented, NOT yet fixed):** double-click enqueues BOTH studies of the patient; their mutual pause/preempt negotiation parked both (Downloading→Paused→Pending in 400 ms) while the pool sat IDLE (`pool_busy=False capacity=1/1`), and nothing kicks `_start_next_pending` — a lost wakeup recovered only by the intent coordinator's 90×~200 ms watchdog = **18.33 s** (dl:11222 `tag=recover attempt=90/90 elapsed_ms=18330`); total double-click → first pixel 27.5 s where the transfer itself took 2.2 s. Plus 64 s of user-perceived delay was the single-click design (`single_click_auto_no_download`) | **FIX (surgical, one file):** every `_on_series_retry` caller is a "fetch this series" intent (viewer critical path, FAST-OBJECT slice poll, thumbnail retry — the DM panel retry_btn is per-PATIENT), none means "wipe corrupt files". New module flag `_DM_RETRY_KEEP_FILES` (default ON): the `existing>=expected` branch now KEEPS the files and lets file-level resume fetch only the tail; deletion requires the new explicit `force_clean=True` parameter, which no production caller passes (guard-tested). `=0` restores the legacy wipe byte-for-byte. **10/10 new guard tests** (`tests/code/download_manager/test_dm_retry_keep_files.py`) — BEHAVIOURAL harness drives the REAL `_on_series_retry` with the bg job inline + tmp storage root: complete-looking series kept (the exact regression), disk>expected kept, incremental branch unchanged, `force_clean=True` still wipes, kill switch reproduces legacy, worker still restarts after keeping files; plus source pins (guard before rmtree, signature default False, no force_clean=True caller repo-wide) | High (bandwidth on slow clinic links + a delete racing the live viewer) | **Low** — one decision branch in one function; the two legacy branches are byte-identical; single kill switch | Low | `tests/code/download_manager` = **260 passed / 29 failed — ALL 29 PRE-EXISTING**: they are source-pin tests for `socket_client.py` features not in the working tree (`_POOR_NET_KPIS` etc.); git shows `modules/download_manager` modified ONLY in `_dm_retry.py` and `socket_client.py` untouched since v3.5.5, so they fail identically on clean HEAD (committed pins for unlanded work, same pattern as the ARM64 set). The `test_instance_payload_key_variants.py` collection error remains the known blocker for the unfiltered run. **STILL OPEN:** the 18.3 s lost-wakeup scheduler stall (D1) and the 250 ms `request_object` intent storm — both documented in the report; D1 is the next candidate fix (kick `_start_next_pending` on Pending-with-idle-pool) | **P1 — NEEDS live verify: open a growing study, watch `download_diagnostics.log` — retries must log "DM-R1 no-wipe" and `skipped>0`, never repeated `skipped=0` rounds; no WinError 32** |

| 2026-08-05 | **DM-D1 Reliability/LATENCY: a paused worker's un-booted subprocess held the ONLY download slot for 26.8 s — the freshly opened study's critical series waited ~21 s behind a zombie. FIXED default-on** (`AIPACS_DM_CANCEL_ESCALATE_S`, default 8; `<=0` = legacy wait-forever) | Follow-up to DM-R1's open item D1 ("download starts with delay", patient 53346), user: "ok go on" | **The DM-R1 row's hypothesis for D1 was WRONG and is corrected here.** It guessed a lost wakeup ("kick `_start_next_pending` on Pending-with-idle-pool"). The timer math disproved it: 90 ticks × 200 ms from the intent chain's `begin` at 11:30:30.80 lands at 11:30:48.8 — `recover` fired at 11:30:49.13, so **the chain ran exactly on schedule and every tick found the pool genuinely FULL**. The true holder: the previous-exam study's worker (started 11:30:25.09) whose download **subprocess took 26.8 s to boot** (child pid 146640's first log 11:30:51.85; `[SPAWN-TIMING] Imports OK (0.001s)` proves the child was fast once up — the cost was process creation/interpreter boot under the multi-study open load). The pause at 11:30:30.8 (`_pause_all_active_downloads` → `request_cancel()`) only sets a `multiprocessing.Event` **the child checks** — a child stuck in boot never sees it, and the parent bridge (`DownloadProcessWorker.run` poll loop) had NO escalation: it waits while `is_alive()` is True, indefinitely. When the child finally booted it exited in 45 ms, the slot freed, `on_worker_removed → _start_next_pending` started the viewed study at 11:30:51.97 — before the recovery chain's first tick (54.1) — i.e. the entire recovery machinery never actually started anything; the boot completing did | **FIX (one file, worker bridge — not the scheduler):** new `DownloadProcessWorker._maybe_escalate_cancel()`, called from the poll loop's queue-timeout branch BEFORE the liveness check: arms a timer on first observing the cancel event set; after the grace (default 8 s) with no terminal message, terminates the subprocess exactly once (latched; same TerminateProcess ladder philosophy as DM-H4 `ensure_subprocess_dead`). The exit is reaped by the existing dead-process handling as a **deliberate preemption**: state is already PAUSED+`is_auto_paused` (set by the pause), so the completion handler's classic-preemption path applies — `completed(False)` emitted, **no `error` signal** (a new escalated-exit branch suppresses the scary "exited unexpectedly" error), and the coordinator's `expected_preemption_window` (which keys on `is_auto_paused`) stays satisfied. Slot frees via the NORMAL removal path. Escalated terminate is safe for data: instance writes are atomic (DM-H2 `.part`+`os.replace`) and retries keep files (DM-R1) — at most in-flight network work is lost. Healthy cancels untouched (booted children ack within ms, far under 8 s). Worst case on the 53346 timeline drops ~21 s → ~8.5 s; typical preemptions unaffected | High (every double-click open of a multi-study patient could pay an invisible, unbounded first-pixel delay) | **Low** — one method + one call site + one exit-branch in one file; escalation only acts when a cancel is ALREADY pending and ignored; single tunable kill switch | Low | **16/16 new guard tests** (`tests/code/download_manager/test_dm_cancel_escalation.py`): threshold parsing (default 8 / env / invalid / disabled), behavioural harness on the real `_maybe_escalate_cancel` (arm-without-terminate, within-grace no-op, fire-once + latch, disabled/negative/no-process/dead-process safety), a **replay of the measured 53346 timeline** (fires at the first tick past 8 s, terminate exactly once), and wiring pins (escalation before the liveness check inside `run()`; escalated exit emits `completed(False)` with no `error.emit`). Combined with DM-R1: `tests/code/download_manager` = **276 passed / 29 failed — the identical pre-existing socket_client pin set as before this change (0 new)**. Neither `download_process_worker.py` nor `_dm_retry.py` is plugin-mirrored | **P1 — NEEDS live verify: double-click a multi-study patient; viewed study's series must start ≤ ~10 s; if escalation fires the log shows `DM-D1 cancel unacknowledged … terminating` then `reaped after cancel escalation`, and NO error toast for the paused study. STILL OPEN (lower priority): the 250 ms `request_object` intent storm (mitigated by DM-R1), and the underlying 26.8 s subprocess boot cost under open-load (prewarm pool exists but is default-OFF — `AIPACS_DM_PREWARM`)** |

| 2026-08-05 | **IMP-1 + IMP-2 + GW-1 Latency/UI-FREEZE: local DICOM import froze the GUI ~50 s and app startup froze ~11.5 s — three independent main-thread blockers. ALL FIXED default-on** (kill switches: `AIPACS_BROWSER_PREWARM_BUSY_VETO=0`, `AIPACS_IMPORT_HEADER_ONLY_READS=0`, `AIPACS_GW_FAST_BIND=0`) | user 2026-08-05 (MRI GA T, 384 files / 66 MB / 8 MR series, all Explicit VR LE — compression NOT involved): "The import process is slow, and after opening, the patient seems to make the app slow. Checking the log, it seems to be still the problem of the patient list loading in local mode" | **Log-first, F11-stack-sampled** (`docs/reports/IMPORT_MRI_GAT_STARTUP_AND_POSTOPEN_2026-08-05.md`). Timeline 20:35:08 app start → 20:38:50: **(GW-1)** startup `mainwindow_construct ms=18043` / `home_widget ms=14203`, of which **~11.5 s inside `gethostbyaddr`** (samples 20:35:45→56) — stdlib `HTTPServer.server_bind` does `socket.getfqdn("0.0.0.0")` (reverse-DNS that hangs on the clinic network) and `agent_gateway.service.start()` constructs the server ON THE GUI THREAD during home-widget construction. This — not the OPT-50 list path — is what reads as "patient list won't load": **OPT-50 flags are all ON and working** (`search_patients_local` 3.0 s ran on a worker). **(IMP-1)** the OPT-22 prewarm idle gate counts only clicks/keys, so the user WAITING on the import scan/preview modals looked idle (native-folder-picker clicks are invisible to the Qt event filter); warm kicked 20:36:17 mid-import, `_warm_webengine_files` read 152 MB against the copy's I/O, and `_construct_warm_view` (QWebEngineView+setUrl) landed on the GUI thread at 20:36:23 = **ONE contiguous 39.7 s MAIN_THREAD_STALL** spanning the whole 40.9 s copy (66 MB at ~1.6 MB/s from the same contention; prewarm.py's own 2026-07-23 comment records a 17 s version). **(IMP-2)** post-copy, `save_complete_study_info` ran on the GUI thread re-reading ALL 384 files with FULL `dcmread` (pixels included) for six header tags → **10.6 s stall** (samples in pydicom `fp = open(fp,'rb')` ~8 s straight; plus `insert_patient` 988 ms) | **Three surgical fixes:** (IMP-1) `modules/web_browser/prewarm.py` — `_app_is_busy()` (modal/popup open) refreshes last-input in `_check_idle` (and gates the `waited`-keyed away-branch — zero-input CD auto-import would otherwise still trip), and `_on_construct` DEFERS in 2 s steps while busy (10 min deadline → skip); (IMP-2) `_hp_study_save.py` — per-file read factored into `_read_instance_record_for_import()` using `stop_before_pixels=True` + `specific_tags` (all six tags are header-group; extraction semantics byte-identical, equivalence-tested); (GW-1) `modules/agent_gateway/http_gateway.py` — `_FastBindThreadingHTTPServer.server_bind` = stdlib minus `getfqdn` (server_name never used by our handler); `start()` selects by flag | High (every local import froze the workstation ~50 s; every startup ate ~11.5 s on the GUI thread) | **Low** — three local changes, no threading rearchitecture, each independently flag-gated | Low | **52/52 new guard tests**: `tests/code/agent_gateway/test_gw_fast_bind.py` (fast bind never calls getfqdn, stdlib-does reproduction pin, live HTTP roundtrip, subclass overrides ONLY server_bind), `tests/code/web_browser/test_prewarm_busy_veto.py` (REAL `_check_idle`/`_on_construct` offscreen harness: busy never warms even on a perfect idle gap, away-branch veto, kill switch reproduces warm-under-modal, construct defers/skips/runs, real modal-dialog `_app_is_busy`), `tests/code/dicom_media/test_import_header_only_reads.py` (header-only record == legacy full-read on synthetic files incl. multi-value WW/WC + missing-tag defaults, stop_before_pixels/specific_tags kwargs pin, kill switch = plain call). Regression: `tests/code/agent_gateway` + `web_browser` + `dicom_media` = **165 passed / 0 failed** | **P1 — NEEDS live verify:** (a) restart app on the clinic network → `home_widget` stage should drop ~11.5 s and no `gethostbyaddr` samples; (b) re-import a folder → no `[MAIN_THREAD_STALL]` ≳ 2 s during `[IMPORT_COPY]`, copy ≈ disk speed, "browser prewarm" never logs "warming now" while a dialog is up; (c) registration stall after copy < 1.5 s. **POST-OPEN ROOT-CAUSED, fixes PROPOSED not applied (report §7):** **VS-1** — every series drop runs THREE switches / builds THREE bridges: placeholder, then `_apply_loaded_series_data` AND `change_series_on_viewer`'s async fallback (`finish_action=fallback_switch`) each run a full `_perform_series_switch_optimized` ~6 ms apart; the later one destroys the other's fresh bridge and rebuilds identically (proven on BOTH drops: series 6 bridges b3f110→b3c7d0, series 2 b3f890→b97250→b3cb90; +3.8 s first open, ~+250 ms every drop) → proposed in-flight/just-completed switch dedupe registry. **VS-2** — first-frame `filter=2852 ms` is `import cv2` (lazy, `opencv_filter_pipeline.py:45`) on the GUI thread at first render; `widget_creation_ms=5423` is the same first-use shape (later widgets 278→6 ms) → proposed patient-open off-thread prewarm. **Still unattributed:** the `os.stat` main-thread runs + `setCellWidget` list-population bursts (candidates bracketed by H7 `on_tab_activated`/ZetaBoost toggles); `search_patients_local` 3.0 s; `insert_patient` 988 ms |

| 2026-08-22 | **OPT-53 Reliability: module installation made VERIFIED and self-diagnosing — the AiPacs Chat "icon visible, module 'not installed correctly'" bug fixed at the pipeline level** (kill surface: behavior is additive; no flag needed — verification failure falls back to an honest `install_incomplete` state) | user 2026-08-22: comprehensive module-installation architecture review; the newest build showed the Chat icon + Settings but opening reported "not installed correctly" | **Root causes, live-inspected:** (1) this machine's `installation_profile.json` (and any profile written by a pre-8/19 installer, or an engine brought forward by DELTA updates, which never rewrite the profile or ship packages) has **no `aipacs_chat` key** → `configured_module_map` falls back to catalog `default_enabled: False` → the registry leg of the tri-gate fails; (2) even a CORRECT fresh install left the module's own flag OFF (shipped template force-disabled by `config_sanitizer.py`; nothing flipped it on install) → same dialog; (3) the dialog was ONE generic string for three causes; (4) `install_module_package` reported success with zero verification (no hash check, no healthcheck, no dependency check) and `_package_record` flattened recorded `install_failed` states back to `not_installed`. **Fixes:** unified verified pipeline (hash → zip-slip guard → manifest → payload → register → profile → activate → VERIFY → feature-flag enable) in `install_module_package`; catalog `requires` + `feature_flag` metadata (chat + identity); named dependency diagnostics; `aipacs_chat_unavailable_reason()` + precise dialog in `_hp_modules.open_aipacs_chat`; Status column + warning tooltips + honest verification-failure dialog in Settings ▸ Installation; feed sha256 enforced in `install_component_update`; `module_install.log`. `.iss` was already chat-complete (aipacs_chat component, [Files], both profile writers — landed 8/19-8/20); v3.6.1 (built 2026-08-22 21:04) was the first COMPLETE chat installer, and v3.6.2 adds the verified pipeline | 15 new guard tests green (7 install-pipeline + 8 unavailable-reason); `tests/code/runtime` + `aipacs_chat` + `builder` + `settings_ui` = 295+51 passed, 0 new failures (6 pre-existing Nuitka-parity reds — `git diff` empty on their target files) | ⚠️ shipped; **NEEDS live verify on a real install:** fresh v3.6.2 install with AiPacs Chat ticked → module opens with NO settings visit; unticked → Settings shows `not_installed` and the icon dialog names the fix path; Settings ▸ Install From URL/Package → "installed and verified" only after healthcheck; `module_install.log` written. **Recovery path for delta-updated clinics:** Settings ▸ Installation ▸ Apply Selected Update (feed carries the chat package + sha256) — no reinstall needed. **STAGED:** physical code separation for bundled_unlock modules (per-module PYZ exclusion + payload-only import) — engine code is currently present-but-locked when unselected |

**IMP-2 amendment — 2026-09-05:** A 2,890-object/20-series import proved that
header-only reads alone do not make registration GUI-safe. The unchanged
per-object registration loop produced a 37.6-second UI stall, followed by a
`Qt6Core.dll` `0xc0000005` after `apply_multi_viewer()` called
`processEvents()` with a partial viewport tree. Registration now runs
sequentially through the existing managed import worker, and layout creation is
atomic. The correction changes no DICOM bytes, transfer syntax,
decode/count/identity/storage rule, SQLite policy, or packaging surface. The
four fail-before guards and the 206-test import/viewer boundary are green;
restarted source-build live verification remains pending. See
`docs/reports/LARGE_IMPORT_QT_REENTRANCY_CRASH_2026-09-05.md`.

**Known pre-existing (unrelated) test failures:** `test_pin_overlay` (×2), `test_vtk_volume_service`,
`test_ino_assignment`, `test_ino_report_workflow`, `test_mpr_tool_autoexit` — confirmed pre-existing
via `git stash`/`git status` comparison; not caused by this work. **RESOLVED 2026-08-01:**
`test_nuitka_arm64_parity` (×6) — the missing `_compile_nuitka_woa_installer` + `--arch`/
`--with-woa-installer` plumbing was implemented in `builder nuitka/build_nuitka_release.py` (with the
three arch-aware Nuitka `.iss` variants), so those 6 now pass.

---

| 2026-09-01 | OPT-55 source-grounded correlated screening and lesion-centred verification | Model locations were bound to full UI screenshots, cross-plane links were proposals only, and focused sagittal sampling used the axial slice centre rather than the observed focus | Pipeline 5.2.0 / screening 2.1.0 / verification 4.2.0. A bounded raw-DICOM atlas exposes every represented sagittal T2/T1 and axial T2 slice with immutable tile identity. Tile-content boxes resolve locally to LPS, correspondence is checked by Frame of Reference and spatial separation, and the verified medoid is used for axial/sagittal focus selection. Exact LPS is removed from the diagnostic context. Independent layout fallbacks remain | Initial guard failed during import; geometry and anchor assertions then failed until implemented. Correlated 4 passed, including fail-closed missing Frame of Reference; full AI Imaging gate 811 passed, 8 existing xfailed, 3 dependency warnings; mirrors 462/462 | Source-build default changed to `focused-v4-correlated`; no live app, model call, clinical benchmark, installer build, or accuracy claim in this validation. Human-supervised case 56339 trial and locked benchmark comparison remain required |
| 2026-09-01 | OPT-55 canonical screening-to-diagnosis handoff | Repeated or contradictory Gemini rows could reach GPT as competing attention tasks, and internal normal counts/parser warnings enlarged the diagnostic context | Pipeline 5.3.0 / screening 2.2.0 / verification 4.3.0. Local normalization emits one focus per supported anatomical site, unions cross-plane evidence, resolves abnormal/normal and side duplication deterministically, splits patient-space-distant lesions, and serializes a compact material-quality handoff while preserving the raw audit | Six fail-before assertions across duplicate, contradiction, laterality, public-context, prompt and spatial-split behavior; self-review also caught an unavailable-to-verified geometry promotion. Focused 35 and orchestration 134 passed; full AI Imaging 817 passed, 8 existing xfailed; default-build 3 passed; mirrors 462/462 | No app/model call or clinical improvement claim. Source run and locked benchmark required; targeted evidence-card and prompt-length experiments remain open |
| 2026-09-01 | OPT-55 canonical V4 runtime and legacy retirement | The V4 constant was the default, but a stale legacy environment value still selected layout/V1/V2/V3 in an ordinary app or build run | Ordinary resolution now always selects `focused-v4-correlated`; retired composers require a separate explicit engineering gate and remain only for benchmark reproduction or bounded incident rollback. The benchmark scopes that exception to its own process. No UI or packaged profile enables it | Four policy assertions failed before implementation; mode/focus/identity passed 120, full AI Imaging passed 819 with 8 existing xfails, default-build inclusion passed 3, and mirrors matched 462/462. Initial human source acceptance completed all three GapGPT stages and preserved the principal morphology/side, while residual severity and quiet-finding misses remain | Locked multi-case clinical benchmark remains required before any accuracy or deployment claim; no installer build or deployment performed |
| 2026-09-01 | OPT-55 submillimetric sagittal screening atlas | Canonical V4 packed a 150 x 260 mm sagittal crop into a fixed 256 x 256 tile, yielding approximately 1.01 mm/px versus 0.4065 axial, 0.5208 verification overview and 0.3906 verification focus sampling. Its manifest did not compute effective sampling or validate a separate screening request budget | Pipeline 5.4.0 keeps axial pages unchanged; sagittal T2/T1 use 320 x 555 tiles and six slices per page, reaching 0.4688 mm/px on a representative 0.390625-mm synthetic source. Manifest 1.1.0 records per-tile and summarized sampling plus actual 8-image/12-MP/12-MiB capacity. Result metadata carries only the compact summary. Render, quality or budget failure uses layout fallback | Eight fail-before guards; focused screening/orchestration 135 passed; full AI Imaging 825 passed with 8 existing xfails and 3 dependency warnings; default-build inclusion 3 passed; mirrors 462/462 | Human-controlled source rerun required. A missed bone-marrow classification had already entered screening and remains a separate diagnostic-reader issue; severity evidence and locked benchmark remain open |
| 2026-09-01 | OPT-55 salience-aware screening and dominant-focus retention | Identical screening pixels produced materially different candidate counts; in the later run Gemini localized the principal caudal focus, but the four-focus planner broke equal confidence/family ties by cranial level order and omitted it from dedicated diagnostic evidence | Pipeline 5.5.0 / screening 2.3.0 / evidence-plan 1.2.0. The atlas-specific prompt emits diagnosis-free visual salience, within-study priority, persistence and allowlisted observable features. The local normalizer rejects unknown keys and exposes incomplete routing data. Marked/dominant foci outrank level order; over-capacity marked/dominant demand creates explicit report-review warnings; selected-focus manifests retain the routing values | Six fail-before guards. Changed boundary 235 passed; full AI Imaging 830 passed with 8 existing xfails and 3 existing SWIG warnings, exit 0 | Temperature remains 1.0 pending a frozen-atlas n>=5 comparison at 1.0/0.2/0.0. No app/model call or clinical-accuracy claim; source rerun and locked radiologist-adjudicated benchmark remain required |
| 2026-09-01 | OPT-55 self-contained diagnostic level cards | Focused V4 exposed the same adjacent-level sagittal anatomy in multiple wide sheets and sent redundant overviews/supplements. Global upload image identity was not explicit in every transport caption, and verification could cite axial frames outside its named focus. A level-specific diagnosis from the parallel MRI-overview context created an additional anchoring path | Pipeline 5.6.0 / verification 4.4.0 / manifest 2.0.0 makes `focused-v5-level-cards` canonical. Each selected level becomes one bound card with targeted sagittal T2, matched sagittal T1 when available, and at most four contiguous axial T2 frames confined to the measured slab. Header/manifest/caption bind image, focus, attention IDs, level and allowed frames. MRI-only context is diagnosis-neutral. Integrity guard 1.1.0 marks cross-card citations review-required without automatic relabeling | Four principal fail-before boundaries plus prompt/handoff guards; focused gate 173 passed; complete AI Imaging 837 passed with 8 pre-existing xfails and 3 pre-existing SWIG warnings; default-build inclusion plus mirror parity 4 passed; 462 plugin mirrors match after EchoMind transport synchronization | No app/model call or clinical-accuracy claim. Human-controlled source rerun and locked benchmark remain required; frozen-atlas Gemini temperature comparison remains separate |
| 2026-09-01 | OPT-55 fixed anatomical diagnostic-card template | The first V5 card isolated levels but retained a variable visual reading order and had no bounded Gemini-to-renderer contract for assigning exact source tiles to diagnostic roles | Pipeline 5.7.0 / screening 2.4.0 / verification 4.5.0 / evidence plan 1.3.0 / manifest 2.1.0. Gemini proposes source-atlas identities for a fixed 3 x 3 card: right/midline/left sagittal T2, the same sagittal T1 sampling roles, and disc-level/maximum-abnormality/caudal-extent axial T2. Local normalization rejects role and patient-LPS order mismatch, rendering enforces measured-slab axial membership, public handoff exposes rejected-slot degradation, and every fallback is audited. The diagnostic prompt reads a fixed order and separates axial zones from craniocaudal levels | Six fail-before guards; changed boundary 166 passed; complete AI Imaging 842 passed with 8 pre-existing xfails and 3 pre-existing SWIG warnings; build/parity 17 passed; mirrors 462/462 | No app/model call or clinical-accuracy claim. The sampling-plane labels do not prove anatomical midline or finding laterality. Human-controlled source rerun and locked benchmark remain required |
| 2026-09-01 | OPT-55 geometry-owned card assembly and compact card metadata | Offline reconstruction showed that an incomplete screening template could repeat one slab-edge axial frame in all three semantic axial slots. T1/T2 plane synchronization, per-tile routing strength, outside-level abnormal attention and non-obscuring reference marks also lacked one authoritative contract | Pipeline 5.8.0 / screening 2.5.0 / verification 4.6.0 / evidence plan 1.4.0 / card template 1.1.0 / manifest 2.2.0. Patient geometry owns sagittal order and T1-to-T2 plane projection; incomplete axial proposals become distinct same-slab context frames; Gemini supplies bounded 0-3 conspicuity plus level-bound attention IDs; context cannot create a card; one additional-findings card retains source-bound unclear foci; short edge ticks replace full locator lines; compact card JSON reaches Sol while full coordinates remain local | Six fail-before behavioral boundaries; changed screening/card boundary 67 passed; full AI Imaging 848 passed with 8 pre-existing xfails and 3 pre-existing SWIG warnings; builder inclusion/parity 7 passed with 4 deselected; mirrors 462/462. Offline saved-source reconstruction confirmed distinct axial frames and edge-only locators | Fresh human-controlled source run required for real per-tile Gemini scores and clinical assessment. No installer build, deployment or accuracy claim |
| 2026-09-01 | OPT-55 same-plane sagittal-pair diagnostic cards | Geometry synchronized T1 and T2 but separate sequence rows forced a distant row/column association; square sagittal cells also spent canvas pixels on letterboxing around a 100 x 60 mm crop | Pipeline 5.9.0 / verification 4.7.0 / card template 1.2.0 / manifest 2.3.0. Three patient-space columns place T2 directly above matched T1; a neutral divider isolates the left-to-right axial sequence. Sequence-specific borders are explicitly non-diagnostic. Sagittal cells are 384 x 256 and axial cells remain 384 x 384; card pixels fall 11.9 percent without changing source crops or axial detail. Caption/header/prompt/JSON share one pairwise reading contract | Card size/layout/order and prompt/pipeline version guards failed before correction. Changed boundary 172 passed; full AI Imaging 848 passed with 8 pre-existing xfails and 3 pre-existing SWIG warnings; builder package checks 4 passed with 4 deselected; mirrors 462/462. Offline saved-source reconstruction confirmed the visual pairs without a model call | Fresh human-controlled source run and locked benchmark required. The layout is an evidence-presentation optimization, not a clinical-accuracy claim; no installer build or deployment performed |
| 2026-09-01 | OPT-55 five-plane sagittal diagnostic-card coverage | The paired V5 selector computed five local sagittal planes but discarded both paracentral planes, leaving only right foraminal, midline and left foraminal evidence for diagnosis | Pipeline 6.0.0 / screening 2.6.0 / verification 4.8.0 / evidence plan 1.5.0 / card template 1.3.0 / manifest 2.4.0. The fixed card carries five DICOM-LPS-ordered sagittal T2 planes from right foraminal through both paracentral planes and midline to left foraminal, each immediately above geometry-matched T1, plus three level-bound axial T2 frames. The 1600 x 1050 layout uses 320 x 224 sagittal cells and 384 x 384 axial cells; six cards total 10.08 MP under the 12 MP ceiling | Card size, five-plane fallback and schema guards failed before correction. Changed boundary 173 passed; full AI Imaging 849 passed with 8 pre-existing xfails and 3 pre-existing SWIG warnings; builder checks 4 passed with 4 deselected; Python compilation passed; mirrors 462/462. Saved-source reconstruction produced two visually reviewed cards at 3.36 MP without a model call | Fresh human-controlled source run and locked benchmark required. This proves coverage, ordering and capacity only; no clinical-accuracy, installer-build or deployment claim |
| 2026-09-01 | OPT-55 anatomy-first spaced sagittal sampling | Five consecutive source slices were centred on the screening focus's lateral coordinate, so a lateral lesion could shift nominal midline and adjacent columns did not represent central, paracentral and foraminal zones | Pipeline 6.1.0 / screening 2.7.0 / verification 4.9.0 / evidence plan 1.6.0 / card template 1.4.0 / manifest 2.5.0. Gemini selects anatomical midline; local validation rejects consecutive or misordered proposals. Fallback uses -4/-2/0/+2/+4 source offsets around bounded stack centre and ignores lesion laterality. Geometry still synchronizes T1. `VOL` labels distinguish source-volume order from possibly reversed DICOM instance order | Six fail-before requirements; changed boundary 174 passed; full AI Imaging 850 passed with 8 pre-existing xfails and 3 pre-existing SWIG warnings; builder checks 4 passed with 4 deselected; Python compilation passed; mirrors 462/462. Saved-source reconstruction showed spaced 10/8/6/4/2 volume indexes and three distinct axial frames at unchanged 3.36 MP | Fresh human-controlled Gemini/Sol run and locked benchmark required. The outer foraminal proposal may move one source interval inward when anatomy supports it. No clinical-accuracy, installer-build or deployment claim |
| 2026-09-01 | OPT-55 explicit per-card JSON and Sol binding | Card metadata was embedded in a free-form caption and nested in one aggregate manifest, so no independent artifact or exact saved-request binding proved which JSON accompanied which PNG | Pipeline 6.2.0 / verification 5.0.0 / manifest 2.6.0. Each level or additional-findings PNG receives one sibling `.card.json`; the manifest, saved request and shared GapGPT content builder preserve the same image index, filename and card metadata. Exactly one JSON block immediately precedes each diagnostic image; global sanitized context remains separate and cannot create a card | Four fail-before requirements; changed boundary 126 passed; full AI Imaging 852 passed with 8 pre-existing xfails and 3 pre-existing SWIG warnings; builder checks 4 passed with 4 deselected; Python compilation passed; mirrors 462/462. Latest saved-source reconstruction verified 2 cards, 2 sidecars, 2 bindings and 2 model-facing payloads with exact decoded equality | Fresh human-controlled Gemini/Sol run and locked benchmark required. This is transport/audit correctness, not diagnostic-accuracy evidence; no installer build or deployment claim |
| 2026-09-01 | OPT-55 card-first Sol diagnostic prompt | The transport had become one JSON-bound V5 card per level, but the verifier still mixed that contract with legacy screenshot sweeps, whole-study recount/safety instructions, context-only additions and a hard-coded L4-L5 extrusion example | Pipeline 6.3.0 / verification 5.1.0. Sol binds each PNG to its immediately preceding JSON, records exact card identity, decides every attention independently, restricts context and safety findings to supplied cards, preserves bound card-level scope, fails identity conflict as INDETERMINATE and uses a neutral output schema. Legacy layout rules are conditional only | Four fail-before contract boundaries; prompt gate 145 passed; complete AI Imaging 855 passed with 8 pre-existing xfails and 3 pre-existing SWIG warnings | Fresh human-controlled source run and locked benchmark required. This is prompt/transport consistency, not diagnostic-accuracy evidence; no model call, installer build or deployment performed |
| 2026-09-02 | OPT-55 atomic anatomy screening and structure-card diagnosis | One Gemini request still screened every lumbar compartment, and one Sol request still received every selected level/structure card. A favorable answer could therefore reflect prompt competition, cross-structure anchoring or stochastic sampling rather than stable morphology recognition | Pipeline 7.0.0 / atomic contract 1.0.0 / card template 2.0.0 / manifest 3.0.0. Five bounded Gemini domains run concurrently against role-filtered, renumbered atlas pages. Local planning splits by `(level, structure_group)`. Disc, endplate/marrow, canal/neural, foraminal and posterior-element cards retain only their decision-relevant planes. Each one-image Sol request receives its own JSON plus the sanitized clinical prior. Local identity validation converts wrong card/level/structure/attention output to INDETERMINATE before deterministic merge. Three-way diagnostic concurrency, partial-failure review and one default-on kill switch are explicit | Atomic/render/orchestration gate 134 passed; complete AI Imaging 866 passed with 8 pre-existing xfails and 3 existing SWIG warnings | No live model call, installer build, deployment or clinical-accuracy claim. Freeze this version and compare it against 5.3.0 and 4.6.1 on a radiologist-adjudicated multi-case cohort. Details: current-state decision record and atomic structure pipeline document |
| 2026-09-02 | OPT-55 grouped screening output-budget correction | Live pipeline 7.0.0 produced a safe but diagnostically empty report: disc, endplate/marrow, canal/neural and posterior-element Gemini calls each reached 5996/6000 completion tokens and returned truncated JSON. Only the empty foraminal reply parsed, so no cards were created and the monolithic fallback did not run | Pipeline 7.0.1 / atomic contract 1.1.0 / atomic screening schema 2.8.0. Three requests replace five: disc plus canal/neural, endplate/marrow, and foraminal plus posterior elements. Each uses temperature 0.2, a 3000-token ceiling, one compact JSON object, an in-object level map, and at most five locations per finding. The five diagnostic card domains remain separate after local validation. Truncated or unstructured grouped output is a request failure; any failed group invokes the complete bounded screening fallback. Successful and discarded atomic usage remains counted | The new compact-request guard failed before `SCREENING_REQUESTS` existed. A 2996/3000 synthetic truncation guard proves fail-closed parsing and a headless integration guard proves full fallback rather than an empty handoff. Focused prompt/orchestration boundary 190 passed; complete AI Imaging 869 passed with 8 pre-existing xfails and 3 existing SWIG warnings; Python compilation passed | Live 7.0.1 rerun required. Confirm all three grouped JSON objects parse, no fallback warning appears, cards are produced for the dominant abnormality, and total tokens/latency improve before any clinical-accuracy interpretation |
| 2026-09-02 | OPT-55 grouped screening ceiling restoration | Pipeline 7.0.1 correctly narrowed five screening tasks into three groups, but also lowered each request's output ceiling from 6000 to 3000 without an owner requirement or a measured safe bound. Expected token savings had been confused with a hard maximum | Pipeline 7.0.2 / atomic contract 1.1.1 restores 6000 per grouped request. Temperature 0.2, JSON-only output, five-location limit, fail-closed truncation handling, complete fallback, usage accounting and the three-group/five-card-domain separation remain unchanged | `test_atomic_screening_dispatch_is_three_focused_low_variance_requests` failed before the correction with 3000 versus required 6000. Truncation guards now exercise the restored 5996/6000 boundary. Focused boundary: 190 passed. Complete AI Imaging: 869 passed, 8 pre-existing xfails, 3 existing SWIG warnings, exit 0 | Live 7.0.2 rerun must measure actual per-request input/image/output tokens and latency. The higher ceiling prevents forced truncation but does not itself increase billed output; repeated image input across three calls may still cost more than one monolithic call |
| 2026-09-02 | OPT-55 task-specific Gemini screening evidence | The three grouped screening calls still repeated identical sagittal T2, sagittal T1, and axial T2 atlas inputs despite different anatomical questions. Irrelevant evidence increased visual competition and input duplication; the metadata-degraded filter path could also fall back to every image | Pipeline 7.1.0 / atomic contract 1.2.0 introduces explicit evidence allowlists. Disc/canal/neural receives sagittal T2 plus axial T2; endplate/marrow receives sagittal T1 plus sagittal T2; foraminal/posterior retains all three because its grouped anatomy needs both parasagittal fat assessment and axial posterior-element assessment. Each prompt declares its supplied roles and treats exclusions as intentional. The fallback filters by session role and never restores unrelated images. Temperature, `detail="high"`, three-way parallel dispatch, JSON contract, fallback policy, and 6000-token ceiling are unchanged | Two existing role assertions failed before correction; a new degraded-metadata guard pins the no-all-image fallback. Changed atomic 13 passed; focused boundary 138 passed; complete AI Imaging 870 passed with 8 pre-existing xfails and 3 existing SWIG warnings; compilation, 7 builder guards, and 462 mirror pairs passed | Live 7.1.0 rerun must measure per-request image/input-token reduction and verify that abnormality recall does not regress. This is a transport optimization, not evidence of improved diagnostic accuracy |
| 2026-09-02 | OPT-55 anatomy-only Gate 1 and intermediate screening cards | Three pathology-screening calls still received raw atlas pages and each inferred anatomical level identity inside the same task that assessed abnormality. No saved card existed between anatomical mapping and pathology screening, so the intended three-gate architecture was not implemented | Pipeline 7.3.0 / atomic contract 1.4.0 / anatomy map 1.0.0 / screening schema 3.0.0. One temperature-0 Gemini map call sees the complete atlas but cannot assess normality. Local validation binds exact sagittal roles and measured axial slabs using DICOM geometry, then saves three task-specific PNG/JSON anatomy cards. Each screen receives exactly one card and treats Gate 1 level/plane labels as immutable. Wrong role/order/pair/slab mappings fail closed to monolithic screening with usage retained. The audit gallery separately exposes mapping inputs, intermediate cards, and screening inputs | New guard failed at collection before `anatomy_cards.py` existed. Changed boundary 185 passed; complete AI Imaging 877 passed with 8 pre-existing xfails and 3 existing SWIG warnings; default-build inclusion 3 passed; Python compilation and 462 mirror pairs pass | Restart the source build, run one study, and verify four Stage 1 request artifacts, three anatomy cards/sidecars, exactly one image per pathology screen, no anatomy fallback warning, and stable level identity before interpreting diagnostic accuracy |
| 2026-09-02 | OPT-55 geometry-owned sagittal identity and mandatory three-gate route | The first live 7.3.0 anatomy response copied concrete prompt example IDs. Their DICOM LPS X coordinates proved the proposed patient-right-to-left order was reversed, so Gate 1 rejected the map and automatically ran the old monolithic pipeline, reproducing the L4-L5/L5-S1 exchange instead of testing the requested architecture | Pipeline 7.4.0 / atomic contract 1.5.0 / anatomy card schema 1.1.0 removes concrete source IDs from the anatomy prompt. Gemini selects five distinct sagittal candidates; local DICOM LPS X sorts and assigns patient-right through patient-left roles and records proposed/canonical bindings. Parseable Gate 2 responses must also match schema, request, structure, and assessment contracts. Default V5 now stops on correlated-atlas, anatomy-map, anatomy-card, grouped-screening, diagnostic-card, or all-diagnostic-card failure. It never automatically invokes the monolithic screen or verifier | Seeded-ID, reversed-order, invalid-map-fallback, truncated/invalid-screen-fallback, and all-card diagnostic-fallback guards fail against 7.3.0. Changed anatomy/screening/audit/orchestration boundary: 77 passed. Complete AI Imaging: 880 passed, 8 pre-existing xfails, 3 existing SWIG warnings; compilation and 462 mirror pairs pass | Restart the source build and verify Gate 1 produces three anatomy cards, Gate 2 receives exactly one matching card per request, Gate 3 receives only positive structure cards, and any gate error is shown as a failed analysis rather than a legacy report |
| 2026-09-02 | OPT-55 diagnosis-free structure screening and one-structure Sol diagnosis | Pipeline 7.5 added disc zone and neural-effect interpretation to Gate 2, a companion checklist to every disc row, and five extra canal/recess/root decisions to every disc diagnostic request. A live run used unchanged source slots but returned contradictory screening semantics and changed disc morphology, so the regression was task competition rather than missing evidence | Pipeline 7.6.0 / atomic contract 1.7.0 / screening schema 3.2.0 / diagnosis schema 1.2.0 preserves all pixels, cards, model settings, ceilings and concurrency. Gate 2 outputs only abnormal structure, immutable level, confidence, visual magnitude, persistence, paired-structure laterality and evidence locations. Local validation rejects morphology, zone, grade, space-effacement, neural-effect and companion fields. Compact Sol metadata removes screening laterality, interpreted features, priority and companion questions. Gate 3 receives one exact structure task and independently classifies diagnosis, morphology, zone, side, severity and effects | Four semantic-boundary guards failed against 7.5. The corrected screening/card pair passes 39 tests; the adjacent selection passes 153; complete AI Imaging passes 889 with 8 pre-existing xfails and 3 existing SWIG warnings. Python compilation passes, builder package checks pass 4 with 4 deselected, and all 462 plugin mirror pairs match | Restart the source build and inspect the exact three Gate 2 JSON files plus every Gate 3 card JSON. Confirm no screening diagnostic descriptor is present, separate canal/recess/root abnormalities create their own cards, and Sol independently classifies each bound structure. This is a semantic-boundary fix, not an accuracy claim |

| 2026-09-01 | OPT-21 native-crash tracing + Windows spawn IPC recovery + FAST embedded-widget ownership | A multi-study patient open terminated with `0xc0000374`; the final main-thread stack ended at the late unscoped thumbnail-card stylesheet. The attempted source-window hardening then selected the venv `pythonw.exe` redirector. Live inspection proved that it did not remove the FAST flash, and download logs later showed a new client failure: the child reached a healthy server thumbnail response but could not read its shared cancellation Event (`PermissionError`, WinError 5). Separately, fresh viewer logs showed a valid Preview -> Complete promotion while both FAST install paths detached the old visible child with `setParent(None)`, temporarily creating a top-level Windows widget | Scope/apply the thumbnail root style before its native subtree; preserve Python's default spawn executable for supported venv source runs so shared IPC handles survive; leave frozen/installed execution untouched; and retire embedded FAST viewers by hide + retained parent + `deleteLater()`. Preserve Preview -> Complete promotion, DICOM decoding, series identity, server protocol, download policy, and the Advanced/VTK domain | Spawn-policy and real shared-Event guards failed before the IPC correction and pass afterward: 7 passed. Focused Download Manager/startup/shutdown/package selection: 59 passed, 4 deselected; materialization/startup-timing/runtime-architecture: 3/4/4 passed. FAST ownership focused guard: 18 passed; broader FAST/drop/progressive/lifecycle selection: 264 passed, 15 skipped, 6 existing xfailed, 1 existing xpassed. PHI-safe report: `docs/reports/THUMBNAIL_HEAP_CRASH_AND_WINDOWS_SPAWN_FLASH_2026-09-01.md` | Human-controlled source restart remains required. Acceptance: a download begins series transfer without WinError 5/retry churn; an uncached FAST drop promotes Preview -> Complete without a separate window; reopening the multi-study patient does not terminate. No installed executable or release build was launched. Full Download Manager collection and a separate ARM64 parity guard remain blocked by pre-existing dirty-worktree mismatches |

| 2026-09-01 | **OPT-57 Download Manager monotonic study-level Overall Progress** | The queue-row and details bars could reset to the current series because their aggregate depended on a separate main-process `completed_series` update arriving before the next heartbeat. The deterministic replay produced `1/300` instead of `101/300`. The first live verification still failed: logs showed the worker had the full multi-series study, which exposed a second seam where the UI denominator came from a potentially unknown/stale queue payload while the subprocess used freshly fetched authoritative metadata | Added an O(1), integer-only per-study ledger keyed by `SeriesInstanceUID`; passed UID through the existing socket/process/Qt envelope; retained bounded-reliable terminal delivery and aggregate-only complete-on-disk accounting. The subprocess now emits one bounded-reliable aggregate-only `study_manifest` event before series transfer; its total is the frozen server manifest used by the actual download and can replace a series-local fallback without losing the accumulated numerator. Existing 10 Hz bridge plus 100–200 ms UI throttle remains unchanged. No GUI-thread I/O, new network request, DB write, decode, VTK work, or per-image signal | Original seven guards passed; follow-up fail-before raised on the missing authoritative-total path and now nine guards pass. Worker/IPC/protected-interaction boundary: 47 passed. Python compilation and mirror parity: 462/462. Builder parity: 13 passed, one unrelated pre-existing stale-stage failure for `patient_table_sort.json`; the heavyweight staged build was not regenerated on the dirty worktree. The earlier 500-series/100,000-event measurement remained 2.10 microseconds/event. Rollback is the Download Manager source/mirror hunks plus guard/docs; no schema/config migration | **Source-build live verification passed on 2026-09-01.** Human observation confirmed that both Overall Progress surfaces were cumulative. PHI-safe logs recorded the authoritative manifest correcting an unknown queue total from `0` to `319` images across `6` series; the six terminal series totals summed exactly to `319`, and the verification window contained no timestamped application/download/viewer/database `ERROR` or `CRITICAL` event. OPT-57 is complete for the source build. Installed-package and release-stage verification remain separate; the unrelated stale staged-config parity failure is still open. |
| 2026-09-02 | OPT-55 geometry-owned axial role order and separate disc/canal screening | Byte-identical atlases and the same temperature-0 anatomy request produced a cyclic reassignment of the same axial tiles, while the combined disc/canal/neural screen returned discs but no canal, recess, or root focus | Pipeline 7.7.0 / atomic contract 1.8.0 uses DICOM LPS Z to canonicalize each selected axial triplet from superior to inferior and records proposed/canonical bindings. Gate 1 now renders four cards; disc and canal/neural run as separate one-card Gemini screens. Diagnostic crops and the Sol prompt are deliberately unchanged | Fail-before: 6 failed / 20 passed. After correction: 27 focused passed; 136 adjacent passed; complete AI Imaging 900 passed with 8 expected xfails and 3 existing SWIG warnings; default-build inclusion 3 passed; 462 mirrors match; exit 0 | Source-build live verification remains required. This correction addresses deterministic anatomy and screening-recall boundaries only; the near-identical-card Sol morphology variance requires a separate frozen-card repeated experiment. |
| 2026-09-03 | OPT-55 canonical MRI architecture and central card registry | Eagle Eye had the intended geometry/anatomy/screen/diagnosis gates, but its authoritative design was scattered across version-specific lumbar plans and runtime data duplicated card semantics. The screening domain model was five-part while transport still combined neural foramen with facets/posterior elements, allowing future body parts to invent another incompatible package | Pipeline 7.8.0 / atomic contract 1.9.0 / anatomy-card schema 1.3.0 establishes `docs/pipelines/eagle-eye-mri.md` as the official MRI architecture and adds an immutable, UI-free registry at `modules/ai_imaging/eagle_eye/card_templates.py`. Lumbar now projects five independent screening cards and five diagnosis profiles from the same registry. Historical plans remain available but are explicitly superseded for architecture | The new registry guard failed at import before implementation. Registry/anatomy/atomic boundary passes 33 tests; affected orchestration/card/audit boundary passes 162; complete AI Imaging passes 910 with 8 expected xfails and 3 existing SWIG warnings. Python compilation, default-build inclusion (3), documentation guards, and 462/462 plugin mirror parity pass | This standardizes ownership and prevents architecture drift; it is not a diagnostic-accuracy claim. Live source transport and radiologist-adjudicated multi-case validation remain required. |
| 2026-09-03 | OPT-55 geometry-first neutral grouping and model-owned anatomy semantics | The workstation correctly measured axial slab boundaries but the Gate 1 contract still forced positional level order, exposed low-confidence T1/T2 slot names as fact, and rewrote the model's axial anatomical roles from Z order. Geometry was therefore being promoted into unsupported semantic anatomy | Pipeline 7.9.0 / atomic 2.0.0 / anatomy schema 1.4.0 / atlas schema 1.3.0 persists classifier confidence, emits neutral `sagittal-series-*` and `axial-group-*` identities, visually separates axial groups, lets Gemini assign sequence and group-to-level semantics, validates exact membership, and records axial physical order without semantic relabeling. High-confidence or operator-confirmed sequence labels remain explicit metadata priors | Three focused guards failed before the correction. Neutral-series/group, arbitrary group-to-level, provenance-confidence, anatomy/card, and correlated-atlas guards pass; complete AI Imaging passes 915 with 8 expected xfails and 3 existing SWIG warnings. Python compilation, 3 default-build inclusion guards, and 462/462 plugin mirror pairs pass | This corrects ownership and repeatability, not diagnostic accuracy. The prior 7.7 Z-based role canonicalization is superseded. A restarted source run must confirm the model returns schema 1.4.0 and that saved cards/JSON preserve the same group identities end to end. |
| 2026-09-03 | OPT-55 persistent sagittal and axial group identity across all three gates | The neutral geometry contract grouped axial slabs but left sagittal planes as one undifferentiated stack. Anatomy mapping could therefore assign slice roles without an immutable regional group, and screening/diagnosis cards discarded the geometry-group identity after selection | Pipeline 8.0.0 / atomic 2.1.0 / anatomy schema 1.5.0 / atlas schema 1.4.0 derives three persistent neutral sagittal regions from DICOM slice-normal projection, retains physical-gap axial groups, requires the anatomy mapper to bind all neutral sagittal groups to regional roles and all axial groups to levels, validates exact membership, and carries the same group IDs into screening slots, evidence plans, diagnostic labels, manifests, and card JSON | Four focused guards failed before implementation on missing sagittal groups, missing mapping contract, missing normalized assignments, and reversed inter-series source order. The affected anatomy/correlated/focused/audit/LLM boundary passes 158 tests; complete AI Imaging passes 917 with 8 expected xfails and 3 existing SWIG warnings; Python compilation, 3 default-build guards, and all 462 plugin mirror pairs pass | This removes an identity discontinuity and prevents physical order from silently rewriting model semantics. It does not prove anatomical or diagnostic accuracy. A restarted source run must inspect the neutral atlas, anatomy JSON, screening slots, and diagnostic card sidecars for unchanged group IDs. |
| 2026-09-03 | OPT-55 physically separated Gate 1 and Gate 1-to-2 geometry groups | Atlas and intermediate cards retained immutable group IDs but could present adjacent groups as a continuous colored grid. A vision model could therefore infer membership from color rather than layout or merge neighboring axial/sagittal groups when color was weak | Pipeline 8.1.0 / atomic 2.2.0 / anatomy schema 1.6.0 / atlas schema 1.5.0 paginates only at geometry-group boundaries and renders groups as separate rows or blocks with 32-pixel whitespace. Disc and Canal separate every axial group. Foramen creates separate right/left three-slice blocks for T2 and T1. Posterior Elements creates right-lateral, central, and left-lateral blocks for T2 and T1. Endplate retains its paired grid. Sidecars record layout strategy, block boxes, tile IDs, group IDs and the spacing/header/color cue hierarchy | Two fail-before guards reproduced the missing block contract and continuous layout. The affected boundary passes 167 tests; complete AI Imaging passes 919 with 8 expected xfails and 3 existing SWIG warnings. Python compilation passes, 3 default-build guards pass, and all 462 plugin mirror pairs match | No screening prompt semantics, diagnosis evidence, model settings, or clinical rules changed. Restart the source build and visually inspect saved Gate 1 and Gate 1-to-2 PNG/JSON artifacts before running or interpreting the downstream screening stage. |
| 2026-09-02 | **OPT-58 measured UI-stall closure** (extends OPT-01, OPT-27 and OPT-45) | 711 gaps exceeded 100 ms (median 169.2, p95 562.1, 11 above 1 s). Exact stacks attributed material stalls to visit-status commit, retired gRPC import, root repolish, Agent Gateway adapter discovery, activation-time completeness scan, Zeta schema first touch, WAV flush, and Eagle Eye tab/probe construction. Fast Viewer remained healthy at 32 ms median / 70 ms p95 and was deliberately unchanged | Startup owns the visit schema and one ordered worker persists status; package compatibility exports are lazy; the window background uses a palette; Agent Gateway discovery/bind, content-aware completeness, Zeta schema, WAV publication, and DICOM probing run outside the GUI thread; only Imaging Tools is eager. Pixel-less-stub correctness, Qt dispatcher ownership, same-key Zeta safety, queue drain, atomic WAV publication with post-replace cancellation, and immutable Eagle Eye worker inputs are preserved. Details and rollbacks: `docs/reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md` | Eleven fail-before boundaries reproduced the original defects. After implementation and adversarial hardening, 13 dedicated guards pass; current adjacent selection passes 340; earlier broad affected selections pass 130, 176 and 14; changed modules compile; 462/462 plugin mirrors match. Builder-focused checks pass 17 with one unrelated pre-existing stale-stage `patient_table_sort.json` failure. No Fast Viewer, Download Manager, DICOM decode, server protocol, or clinical geometry code was changed by OPT-58 | **Partially live-verified; installed-build verification pending.** The source run reduced >100 ms events from 711 to 218, while p95 rose from 562.1 to 706.4 because the remaining distribution is dominated by fewer large stalls; do not claim uniform percentile improvement. Targeted stacks disappeared from exercised paths, voice publication and off-thread visit writing succeeded, and no terminal main-process native crash occurred. Eagle Eye was not exercised. R1 is now code/offscreen verified: initial Server Search row construction no longer calls the unused per-row disk probe; explicit Local/Import state remains unchanged; its behavioral guard failed before correction, the 29-test disk-path file and 142-test adjacent boundary pass, and live verification remains pending. Remaining separate follow-ups are: (2) server-only visit persistence has always failed when no derived `studies` row exists, is not an OPT-58 regression, and needs an independent no-FK `study_visit_status` table rather than a stub study; (3) an authoritative download-completion marker must land before further download optimization; and (4) MPR remains a separate instrument-first VTK workstream. Do not claim release parity until normal builder gates run on a clean release candidate. |

| 2026-09-03 | OPT-55 central-canal specificity and bounded MR-myelography context | Live pipeline 8.2.0 retained correct immutable group membership but produced an L4-L5 central-canal false positive alongside a recess positive. Its raw schema exposed locations without the caliber/CSF feature that caused the decision, and the canal card omitted two available MR-myelography overview series | Pipeline 8.3.0 / atomic 2.4.0 / anatomy 1.8.0 / screening 3.3.0 adds a canal-only per-level observation contract and fail-closed consistency validation. Preserved caliber or minor impression cannot create a central positive; recess/root remain independent; preserved CSF alone does not veto genuine caliber loss. At most two explicitly identified, same-study, bounded MR-myelography images are decoded off the GUI thread and added as non-localizing overview context. Other screening and diagnosis paths are unchanged | Six dedicated guards failed before correction and all 9 pass afterward. Adjacent boundary 159 passed; complete AI Imaging 930 passed with 8 expected xfails and 3 existing SWIG warnings. The two available live-study context series decoded to 512x512 with no warning. Direct exit codes 0 | Restart the source build and run the same study. Acceptance: raw canal JSON contains six group-bound observations; L4-L5 records preserved caliber/minor impression without a central positive; L5-S1 recess/root remain independent; the card sidecar records two overview-only myelographic images; no geometry or other-card regression. Clinical accuracy remains unproven pending radiologist review. |

### OPT-53 build-boundary follow-up — 2026-09-04

Recovery of the first 3.6.5 attempt adds a pre-staging 240-character compiler
path budget and short unique compiler input trees, serial low-memory Nuitka
compilation, fatal-memory detection, owned-process termination and watchdog
timeouts. A synthetic Inno probe proved a 261-character source path fails while
the same bytes at 37 characters compile. Three guards failed before correction.
Python core reuse requires matching source hashes and repeat stage/MPR gates;
no prior installer is renamed or promoted. See the release record below for
the failed attempt, recovery workspace and remaining output/installation gates.

The 3.6.5 local candidate extends the existing verified-module-installation item,
not a separate runtime optimization. Staged Nuitka now uses the canonical
Standard/Eagle Eye/ARM-emulated installer contract, preserves codec discovery
metadata, excludes work caches from its core and does not automatically launch
the workstation. Source-aware checkpoints and isolated snapshot hashes reject
stale inputs; the coherence gate compares stages to the source version. The
owner accepted the current Developer Run for local building, not production.
Fail-before/pass-after evidence and remaining baseline failures are recorded in
`releases/VERSION_3.6.5_BUILD.md` and guarded by
`tests/code/builder/test_release_candidate_packaging.py`. Rollback: discard only
the new isolated candidate; preserve the working source and previous installers.
Installed-module, clean-machine, upgrade and ARM-host validation remain pending.

The final-output boundary was corrected after the recovery build exposed an
unapproved `output/distributions/<run>` delivery tree. Isolated source and short
Inno stages remain safety mechanisms, but final files now land only in the two
pre-existing backend folders: `builder/output/installer` and
`builder nuitka/output/installer`. Each receives the three exact versioned
edition names plus refreshed manifest, installation notes and SHA-256 files.
The folder-contract guard failed before the fix and the focused boundary passes
31 tests afterward. The stopped recovery candidate is retained as failed
diagnostic evidence and cannot be promoted.

The final recovery completed on 2026-09-05. A healthy but silent Stage 6 compile
first exceeded the old 90-minute idle watchdog; a later retry exposed MSVC C1002
in the generated SimpleITK translation unit under `/Ox`. The build supervisor now
allows four hours of compiler silence, Stage 6 appends `/Od` through `_CL_`, and
resume begins at the recorded failed release stage while preserving only the exact
timeout object boundary. The focused distribution/candidate/ARM suite passes 41
tests. PyInstaller and Nuitka each produced Eagle Eye, Standard and ARM64-emulated
3.6.5 installers in their pre-existing backend installer folders, and all six
sizes and SHA-256 hashes match their manifests. Cross-backend stage coherence
passes. This closes local build generation only; installed, clinical, upgrade,
rollback and real ARM-host acceptance remain open. Exact artifact evidence is in
`releases/VERSION_3.6.5_BUILD.md`.

Post-build review found that the initial compact-edition interpretation violated
the 3.6.3 functionality baseline: Standard and ARM had dropped the full 813 MB
Slicer runtime, explaining Python Standard's 628,247,370-to-442,928,735-byte
reduction. OPT-53 now treats Slicer runtime inclusion and Eagle Eye offline-model
inclusion as independent boundaries. Standard/ARM retain and install Slicer but
prune the offline model; Eagle Eye retains both. The same correction makes the
Information edition lines runtime-version-driven and gives the Inno Wizard an
explicit macro-driven version title. Five fail-before guards and the 21-test
Information/distribution selection pass; the real compiler-only Inno matrix also
passes. The first 3.6.5 installer set is superseded and requires a fresh rebuild.

The 2026-09-05 final-readiness audit extends OPT-53 again. The prior six-artifact
candidate contains the cardiac MRI Flow VM-normalization fix but predates later
source changes and cannot represent HEAD. The proprietary dependency set also
carried GPL-3.0 `pylibjpeg-libjpeg`; requirements and both frozen backends now use
Apache-2.0 GDCM plus MIT pyjpegls for JPEG/JPEG-LS, retain MIT OpenJPEG/RLE, and
install an EULA plus third-party notice. Real compressed reference samples,
80 focused guards, 68 installer/ARM guards, three Inno profiles, and 462 mirrors
pass. A final rebuild remains blocked on the explicit legacy-license reactivation
decision, then clean-machine, cvi42, Qt-license, signing, and ARM-host gates.

The 2026-09-06 r15 measurement establishes the current build-time baseline and a
single operational route. The complete isolated matrix took about 2 h 54 min:
PyInstaller about 62 min, Nuitka about 112 min, Nuitka Stage 6 about 49 min, and
the six Inno compression passes about 96 min in aggregate. Compression and the
serial low-memory native compile are the measured bottlenecks. `BUILD.md` is now
the authoritative human/AI entry point and defines three lanes: source validation
for normal changes, disposable one-edition/synthetic packaging validation, and one
full six-installer candidate after source freeze. Existing backend documents link
to it and are explicitly subordinate. The release default remains sequential;
Nuitka `--jobs=1`, low-memory mode, no LTO, disabled compiler cache, and `/Od` are
not relaxed because they close observed MSVC heap failures. Future speed work is
limited to guarded experiments: content-addressed Nuitka core reuse, a non-promotable
fast-compression internal profile, and measured bounded Inno parallelism. The
documentation contract is pinned by
`tests/code/builder/test_canonical_build_runbook.py`.

The 2026-09-10 orchestration correction removes the manual multi-command internal
packaging path. One `build_local_candidate.py --internal` invocation now derives
the source version, immutable asset location and a new short workspace, then builds
one Standard PyInstaller candidate by default; backend and edition overrides stay
explicit and non-promotable. Standard/ARM focused builds no longer stage Eagle Eye
models that their profiles remove. Official and internal Eagle Eye requests resolve
one external Brain source deliberately, and the official lane rejects missing or
stale redistribution evidence before source snapshotting or any expensive compile.
This improves failure latency and operator repeatability without relaxing the
six-artifact, serial Nuitka, source identity, legal, or install-acceptance gates.

The completed 2026-09-10 version 3.6.6 matrix sharpens the OPT-53 performance
decision with a second real measurement. Exact-input PyInstaller repackaging took
about 49 minutes. Nuitka took about 3 hours 15 minutes; Stage 6 took about 54
minutes, while Stage 10 took about 63 minutes and its three standalone Inno
compression passes accounted for about 60 minutes. Both backends already compile
one core and derive three edition views, so the six outputs do not represent six
application compiles. Immutable runtime assets are already cached. The remaining
safe reuse boundaries are fail-closed PyInstaller core reuse and same-candidate
Nuitka recovery. Inno has no incremental block cache for a monolithic standalone
EXE, so unchanged DLLs alone cannot authorize installer reuse. The next measured
experiment remains content-addressed cross-candidate Nuitka Stage 6 reuse; a fast
compression profile is limited to non-promotable diagnostics, and parallel Inno
compilation remains disabled pending dedicated-machine RAM/disk evidence. Root
`BUILD.md` now makes an unqualified build request an immutable six-file contract,
and the coordinator CLI no longer exposes a final-output redirect. The same
coordinator now owns interrupted-candidate recovery through `--resume-workspace`:
it retains a completed backend, refuses an active recorded child, constrains Nuitka
resume to release stages 0/6/7/8/9/10, and reruns coherence. This closes the manual
recovery gap encountered by the 3.6.6 build without authorizing cross-candidate
cache reuse.

### OPT-01 Printing follow-up - 2026-09-09

DICOM network submission now runs in a bounded pool job holding captured settings, pixels and study identity. Association timeout is 10 s; DIMSE/network timeouts are 30 s; no automatic print retries. Before: synchronous network on the GUI thread. After: a held synthetic transport proves off-GUI execution, immediate return, and completion owned by the original study. No live latency percentile improvement is claimed.

The same maintenance slice corrects study/page state, stale exports, settings, Qt buffer packing, physical page format and Scout line coordinates. Before-fix evidence: 22 behavioral failures across staged runs, each exit 1. After: 28 printing tests passed, exit 0; all 462 plugin mirror pairs match. See `docs/modules/PRINTING_WORKFLOW_MAINTENANCE_2026-09-09.md`. Source-build/printer checks remain pending. Filesystem scans, DICOM decoding and page composition still need an independently measured worker/render design. Existing unrelated plan work is preserved.

Printing reliability follow-up (2026-09-09): selected-tile drag now retains the selected group across mouse tools, while Shift/Ctrl selection gestures do not edit pixels. Six pre-fix failures and ten synthetic Qt mouse cases document the boundary in the existing printing maintenance note. No performance improvement or live-source verification is claimed.

## 16. Permanent update rule

From now on, **every optimization task updates this document** instead of creating a disconnected plan.
After each change record, in §9 and §15: what changed, why, files/modules affected, KPI before/after,
reliability result, regression result, remaining work, new priority order. Per-fix detail lives in the
linked report; the *status* lives here. Fragmented docs remain as historical evidence but this file is
the current source of truth.

---

## 17. Final decision — the safest highest-value remaining work *(rewritten 2026-07-14)*

**Historical decision, not current completion status.** Follow the September 15
closure audit at the top for current ordering. Its measured GUI DICOM cache miss
qualifies the older blanket "decode/render healthy" statement below; it does not
authorize rewriting the decoder. Preserve the historical evidence and existing
default-on identity implementation while reconciling remaining acceptance gates.

> **The highest-value work right now is not writing code. It is DRAINING THE VERIFICATION DEBT.**
>
> Between 2026-07-08 and 2026-07-14, thirteen fixes shipped **default-on** — including three that
> touch the most clinically sensitive path in the app (series identity) and three that were only
> discovered because a *previous* fix's logging made them visible. Almost none is live-verified. The
> dominant risk has flipped: it is no longer an unfixed bug, it is **a regression hiding inside an
> unverified pile**. Every additional fix layered on top makes attribution harder.
>
> **In order:**
>
> 1. **Run V-1 … V-4 (§10).** Zero new code. Each has an exact acceptance signal and a kill switch if
>    it fails. A clean **V-1** (`[SERIESREF-SHADOW] mismatch = 0`) is *also* the evidence gate that
>    unlocks the rest of OPT-35 — it is the cheapest high-leverage action available.
> 2. **OPT-35 P3 (S-1)** — re-key the cache/switch path by `series_uid`. This is the last stage still
>    deriving identity from a bare series number, it is **evidence-backed** (3 live `IDENTITY-GATE
>    SKIP`s trace to it), and the fail-closed gate is currently the only thing preventing a wrong
>    image there. Mind the ZetaBoost digit-key constraint.
> 3. **OPT-35 P4/P5 — pay the flag debt.** Nine identity flags → one. Retire one at a time, each only
>    after it logs zero firings. Flag debt is now a named risk, not housekeeping.
> 4. **The three known GUI-thread offenders (G)** — AI-seg sync POST off-thread, Eagle Eye lazy
>    `ModelTrainingTab`, Advanced/VTK spinner. Cheap, contained, and they close the class that has
>    produced three multi-second freezes *since* main-thread blocking was declared "resolved".
> 5. **Only then OPT-04, re-scoped to DM completion convergence** — high value, high risk, and no
>    longer urgent, because it is *not* the cause of the display-failure family (that theory is
>    retired; see the 07-14 reassessment).
>
> Deliberately **not** next: decode/render optimization (healthy — wasted effort), geometry T2/T3 and
> the dental VTK-MPR flip (high-risk, clinical-lane golden-compare gated), and any large single-shot
> rewrite.
>
> **The discipline that actually produced results this month:** read the logs before theorising
> (three wrong root-cause calls on OPT-20 were only settled by per-hop instrumentation); prefer
> *removing a suppressor* over *adding a mechanism* (OPT-35/36/37 were all existing machinery being
> gated off); and never let a fix ship without an acceptance signal you can grep for.
>
> The goal is not continuous refactoring. It is measurable, monotonic progress toward a **faster, more
> deterministic, more maintainable** application — verified by fresh logs against the §13 baseline after
> every phase.

---

## 18. Linked evidence (historical documents this consolidates)

### 2026-09-05 — OPT-55 extended anatomy coverage

Pipeline 8.4.0 / atomic 2.5.0 / anatomy schema 1.9.0 separates a complete anatomical
map from the bounded lumbar diagnostic target. Seven acquired groups no longer have
to fit six unique diagnostic labels. Extra recognized levels retain their source-tile
membership as context, are explicitly not assessed, and cannot shift lumbar labels
or enter lumbar diagnoses. Unknown and duplicate assignments still fail. The final
numbering audit excludes only explicitly recorded context ranges and preserves the
coverage-review notice.

The initial guard failed 3 tests and passed 5. Twelve focused guards now pass; exact
saved-response replay generated all five screening cards with unchanged lumbar frame
ranges and no model call. Full AI Imaging: 1,012 passed, 8 existing xfails, exit 0.
Source verified; operator-controlled restart and live re-analysis remain pending.
Details and rollback: `docs/reports/EAGLE_EYE_EXTENDED_COVERAGE_2026-09-05.md`.

### 2026-09-05 — OPT-55 physical side and neural coverage

2026-09-07 diagnosis-input investigation: proposed MedGemma 1.5 multi-image packets
retain immutable parent groups while independently validating anatomical eligibility.
Source review found that the current sagittal outer-three partition does not itself
prove foraminal coverage. The proposed experiment separates montage effects,
complete-group coverage and spatial-prompt effects. No runtime, server, provider
or clinical data change was made. Input contracts, task prompts, resource policy
and acceptance guards are documented in
`docs/reports/MEDGEMMA_GROUPED_DIAGNOSIS_DESIGN_2026-09-07.md`.

Related side/coverage correction: pipeline 8.5.0 / atomic 2.6.0 / anatomy 1.10.0 /
screening 3.4.0 makes axial patient-side display explicit, corrects sagittal side
semantics from DICOM while preserving midline/source membership, and requires
central canal plus bilateral recess/root/foramen observations at every diagnostic
level. Abnormal observations require matching candidates; unassessable compartments
require review. Actual-card headers replace obsolete capture-layout instructions.
Initial guard: 11 failed / 1 passed. Final full AI Imaging: 1,063 passed, 8 optional
skips, 8 existing xfails, exit 0; 3 builder guards and 462 mirror pairs pass.
Saved-anatomy replay preserves six levels and all selected source sets while fixing
both sagittal series' side labels. Source verified; restarted live inference and
clinical adjudication remain pending. Details and scoped rollback:
`docs/reports/EAGLE_EYE_NEURAL_COVERAGE_2026-09-05.md`.

### 2026-09-05 — OPT-55 provider/model boundary follow-up

**2026-09-20 saved candidate follow-up:** the owner requested durable build defaults
for the best available model experiments. Pipeline provenance 8.7.0 now persists
Astra company screening and standard diagnosis with independent Gemini anatomy
and context. The reporter preserves the tested Astra original-detail, medium
reasoning and completion-token profile; explicit provider/model overrides remain.
Fail-before: 5 failed / 1 passed. Final affected/provider/builder selection:
164 passed, exit 0. All 468 plugin mirror pairs match. A synthetic-only real
company transport call passed. Current source control ping/actions are reachable,
but that process predates the edits: fresh-source GUI and installer acceptance
remain pending. No clinical accuracy claim, installer, endpoint or key change.
Neural grading, subtle findings and the existing eight-card coverage limit remain
open. See [saved model profile](modules/EAGLE_EYE_LUMBAR_SAVED_MODEL_PROFILE_2026-09-20.md).

The installed Eagle Eye failure exposed an old explicit direct-provider selection
combined with hardcoded endpoint/model fallbacks. Company/GapGPT remains the default;
direct mode now needs the user's saved selection, key and Base URL. Direct Eagle Eye
models require explicit Settings entries, with a retryable preflight error rather than
a company-model fallback. The UI exposes both model fields and no longer prefills a
direct endpoint. No clinical pipeline stage or company credential was changed.

Fail-before: 14 failures / 4 passes, exit 1. Final affected selection: 205 passed /
1 existing xfail, exit 0; 21 focused provider/UI/runner guards. Three EchoMind payload
mirrors were synchronized. Release parity remains blocked by unrelated `run_cd`
mirror drift and stale staged templates; installed code/settings remain untouched.
Status: source/offscreen verified, live and installed-build verification pending.
Rollback: scoped source/payload reversal in a future build; no implicit-routing bypass.
Details: `docs/reports/ECHOMIND_EXPLICIT_PROVIDER_SELECTION_2026-09-05.md`.

Root-cause/plan: `docs/reports/PATIENT_LOADING_PIPELINE_RELIABILITY_REVIEW_2026-07-02.md` ·
`docs/plans/UNIFIED_STABILIZATION_OPTIMIZATION_PLAN_2026-07-01.md` ·
`docs/reports/KPI_SESSION_REVIEW_2026-07-01.md` · `docs/reports/deploy-record-workstation-2026-07-03.md`.
Reference/tooling: `docs/reference/AIPACS_FLAG_REGISTRY_2026-07-01.md` ·
`docs/performance/FAST_VIEWER_KPI_CATALOG.md` · `docs/plans/performance/CURRENT_KPIS_v2.3.6.md` ·
`tools/performance/kpi_session_report.py`. Subsystem as-built: `docs/pipelines/thumbnail-pipeline.md` ·
`docs/pipelines/unified-patient-study-pipeline.md` · `docs/plans/VIEWER_GEOMETRY_HARDENING_MASTER_PLAN_2026-06-14.md`
· `docs/plans/performance/MPR_OPEN_FREEZE_OPTIMIZATION_PLAN_2026-06-27.md` ·
`docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`. P1 reports:
`docs/reports/P1_1..P1_4_*_2026-07-01.md`. Control/testing:
`docs/for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md`. Code authorities:
`PacsClient/utils/patient_load_lifecycle.py`, `PacsClient/utils/lifecycle_shadow.py`,
`PacsClient/utils/patient_study_set.py`, `series_display_state.decide_display_action`, `series_completeness`.

### 2026-09-08: OPT-55 paired locator readability correction

Review of the spatial pilot found crowded guide overlays and separated axial-to-
line correspondence. The benchmark now renders one physical-plane pair per card:
single-line mini-locator, clean enlarged sagittal slab context, clean matching
axial. Complete original groups still accompany the cards. Nine geometry/layout
guards pass (two new fail-before). Private real-panel pixel checks pass for all
22 cards. Five company-route layout-only requests completed; exact source IDs,
order and overlay placement were read correctly for all 22 pairs, with four pair
tags including their total-count suffix. This validates presentation, not a new
diagnostic result or production rollout. See the existing spatial experiment report.

### OPT-01 Printing reliability follow-up - 2026-09-09

The print audit correction adds truthful Windows submission completion, DICOM operation/status reporting and pre-association validation; fixes shared image window/color fidelity. 89 focused tests pass, 462 mirror pairs match. This is correctness/reliability work, with no latency improvement claim or new GUI-thread offload. Remaining preparation latency and live device checks are recorded in `docs/modules/PRINT_TRANSPORT_AUDIT_2026-09-09.md`. Rollback is limited to the follow-up hunks and matching mirrors, preserving prior staged changes.


### 2026-09-11: OPT-51 workspace-owned Eagle Eye jobs; OPT-58 follow-up boundary

The workspace-first UI correction makes function selection explicit after navigation.
The new entry guards reproduce and prevent pre-entry execution and Lumbar auto-capture.
Parent destruction now invokes existing teardown before child QThreads are deleted,
because the workstation removes tabs with deleteLater without closeEvent. A duplicate
Lumbar request cannot replace an active analysis. This extends OPT-51 lifecycle ownership;
it does not claim to close OPT-58 latency work. Existing MG/DX modal overlays, synchronous
Lumbar preflight and viewer/dataset preparation remain for the requested later blocking
pass. Validation: 1165 passed, 8 existing xfails in the broad selection; 99 related tests
passed after final popup layout adjustments. See
`docs/modules/EAGLE_EYE_WORKSPACE_ENTRY_2026-09-11.md` for files, pre-fix evidence,
scoped rollback and the remaining human-launched live gate. No latency KPI was measured.

### 2026-09-14: OPT-51 / OPT-58 Eagle Eye background interaction

Four fail-before guards reproduced cancellation on dismissal in Brain, lesions and Alignment, and application-modal MG/DX progress. `background_analysis.py` now supplies owner-bound nonmodal windows with Continue working in PACS; hiding a computing job preserves its Future, while explicit Cancel and workspace destruction keep cancellation. Pending input scans still cancel to avoid delayed selectors over other patients. Reopening a completed Brain/lesion job preserves its result instead of starting another series scan. MG/DX use compact dismissible progress instead of a full-window cover; existing worker reentrancy guards remain. Alignment only cancels pending scan/load on hide. Lumbar results were already nonmodal; no capture/preflight latency claim is made.

Verification: six new guards, 93 focused/adjacent passes, 3 build-inclusion passes, exit 0; 462 mirrored pairs match. The existing source process predates this patch. While its real lesion worker remained active, native minimize, PACS Home, opening a series and slice navigation succeeded. This proves current background worker coexistence only, not the new close/reopen behavior. Full new UI acceptance, reporting interaction and installed-client gates remain pending until a fresh source launch after the current job finishes. No model accuracy or CPU speedup claim. Rollback only these dialog, workspace, Alignment-hide and interactor-progress hunks plus viewer mirror; preserve earlier workspace and Brain changes.
# 2026-09-15: OPT-56 Advanced Analysis UI/UX audit

Header follow-up: scene-independent Python presentation now replaces module-action
icons, styles the header/menu, removes case identifiers from the OS title and
clamps resident launch geometry to the destination monitor. Two compact-title
fail-before cases and six new presentation cases; 40 final adjacent passes,
463 matching mirrors. PythonQt startup attribute failure corrected; 41 adjacent
tests and the embedded synthetic resident probe pass. Fresh source-workstation
launch renders MPR; custom module icons and Models dispatch verified. Native
About metadata and complete extension responsiveness remain open. Details and
rollback are in the linked Advanced Analysis audit.

Dropdown follow-up: native inspection reproduced the empty template Home panel
and hidden menu bar. The real MPR action is now Home / MPR; a flat installed-tool
list replaces general module discovery, preserving manual segmentation and Eagle
Eye programmatic entries. One new fail-before guard; 42 focused passes and 463
matching mirrors. Subsequent native close/reopen exposed disconnected action
routing; fixed by keeping native actions attached. Final gate: 44 focused passes,
463 mirrors, second fresh launch opens all eight menu panels and Home returns to
MPR with the menu bar intact. No editing/inference operation was validated.

Panel follow-up: all eight curated modules now have scoped navy/cyan controls,
AI-PACS headings and concise purpose captions; Measurements creation icons are
custom. Two fail-before guards preserve control values/callbacks and intact grid
layout ownership. Final code gate: 46 focused passes, four deselected, exit 0;
463 mirrors match. Fresh native close/reopen verifies all eight styled panels and
return to populated Home on the primary monitor. Remaining: deep internal icons,
native version notice/rebuild and final panel-theme acceptance on monitor B.

Default-size/numeric-control follow-up: native constructor and resident geometry
now target 70% of available screen dimensions; legacy standby no longer maximizes.
Four geometry cases failed before the fix. Shared immutable numeric styling and
SVG chevrons replace missing arrows in base theme/Settings and Advanced panels,
with explicit integrations for filtering, storage, printing and report controls.
Code: 60 launch/theme/package passes and 150 adjacent UI passes (overlapping
selections), direct exit 0; 464 Python mirrors plus four SVG parity guards.
Native resident GUI: default 1344x722, Maximize/Restore, visible arrows and
Sharpness 1.0 -> 1.1 -> 1.0 verified. C++ rebuild and fresh main-app Settings
acceptance remain pending. Monitor B deferred by the user. Details/rollback in
the same Advanced Analysis audit; no measured startup-speed claim.

Live follow-up: source-launched external viewer rendered a local MR series;
native menu, cross-line and wheel input worked, and PACS wheel input remained
independent. On the 1280x1024 secondary monitor, normal geometry was partly
offscreen; maximized 1280x976 fit, with overly wide module panels and low-contrast
controls. About still displays Slicer text. Version/title sources now match 3.6.6:
seven fail-before guards, 34 final adjacent passes (exit 0), 462 mirror pairs match.
The running native binary is still 0.1: rebuild and fresh GUI acceptance pending.
These sampled UI checks do not establish inference/startup performance acceptance.

Initial source/document/asset review found inconsistent resident/native geometry,
manual-review launch-option drift, unenforced custom-only executable overrides,
and remaining native branding/icon acceptance gaps. No runtime change or measured
speedup. Existing focused guards pass 23 cases (exit 0) when QApplication tests
precede QCoreApplication tests; the reverse order terminated without a summary.
The existing live control client could not connect; GUI acceptance remains open.
See [the audit](reports/ADVANCED_ANALYSIS_UI_UX_AUDIT_2026-09-15.md) for evidence,
priorities and implementation slices under the existing OPT-56 item.

# 2026-09-15: OPT-51 / OPT-58 manual review follow-up

Added worker-submitted isolated Slicer review preparation and lesion revision
recalculation. Existing nonmodal progress and Continue working in PACS remain
the execution boundary. Sixty-seven focused tests passed, including existing
background dismissal/input guards. No measured inference speedup is claimed.
Whole-brain edits produce a binary-volume addendum, preserving posterior
inference. Live synthetic Slicer Erase/Save removed nine voxels and regenerated
a matching binary addendum. PACS result-button acceptance awaits human login. See
EAGLE_EYE_BRAIN_UI_AND_MAINTENANCE.md for supported scope and rollback.

### OPT-56 startup welcome text follow-up

The presentation adapter corrects the stale native welcome version to the product
title while preserving the clinical disclaimer and acknowledgement controls.
Known-message-only handling covers existing dialogs and Show events. Fail-before
guard; 51 focused passes, exit 0; 465 mirrors match. Live acceptance pending because
no source PACS/Advanced window was present. Native rebuild remains separate.


## OPT-35 preview metadata follow-up (2026-09-16, post-20:51 session)

Closed the reproduced metadata/pixel count and order mismatch in bounded Advanced
previews via header reads for the exact selected decode files. No geometry transform,
filter or renderer changes; unsupported mappings defer to full loading. Three
fail-before cases, six final guards; load suite 280 passes / 4 xfails / 1 xpass,
additional geometry/MPR suite 129 passes / 5 xfails; 467 mirrors match. Suites overlap
on six preview guards. Ping/actions work, but fresh-source GUI acceptance is pending.
Native COM/shared stalls remain routed to existing owner reports; first-render/filter
latency is measured but not fixed. Details, rollback and live gate:
[VTK review](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#opt-35-preview-frame-metadata-alignment-2026-09-16-post-2051-session).


## OPT-23 page-switch overlay follow-up (2026-09-16)

Reproduced background loading re-showing an opaque native cover after viewport Hide.
A show-time anchor/lifetime/intent check now preserves hidden-page scoping. Two
fail-before cases plus hidden-completion guard; 46 focused passes, 467 mirrors match.
Ping/actions work; fresh-source page-switch GUI remains pending. Remote-drop wait
belongs to the Download Manager handoff, not a proven VTK decoder failure. Evidence,
rollback and acceptance are in the [VTK report](reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#opt-23-native-cover-after-page-switch-2026-09-16).

## OPT-23 individual filter timing prerequisite (2026-09-16)

Added PHI-free per-stage filter timing without changing image processing. Four guards, 30 focused passes, source GUI blocked on control ConnectionError. Synthetic timings do not reproduce the 11-second live workload; optimization remains pending stage evidence. Shared font backend unchanged; exception cleanup ownership requires separate guarded work. See the VTK review filter-stage measurement section for evidence and rollback.


## OPT-35 / OPT-48 MPR admission stability (2026-09-16)

Reproduced and blocked reuse of explicit Advanced previews or volumes with fewer
pixel slices than instance records. No geometry/filter changes or synchronous full
rebuild added. Nine failing-before guards, ten final cases, 192 focused MPR/US/route
passes and 467 matching mirrors. Ping/actions succeed on the pre-edit app; fresh
GUI preview-rejection -> completed-MPR gate remains. Upstream tab/cache promotion
and open-time latency are separate. Details and rollback are in the VTK review's
Guarded MPR admission section.

## OPT-35 Advanced cache integrity with tab-delivery owner (2026-09-17)

Closed independently reproduced decoded metadata/pixel mismatch admission and metadata-only growth in four owned cache methods. Five fail-before cases, eleven final cases; 391 expanded passes, four existing xfails, one quarantined xpass; 467 mirrors match. Shared delivery/activation remains Unify-owned. Fresh combined native drop/tab-switch acceptance pending; see VTK report for contract, limits and rollback.


## OPT-48 deferred MPR teardown follow-up (2026-09-17)

`_mpr_views.py::_build_deferred_3d_view` now stops after progress-event processing if
MPR cleanup has begun, while still dismissing the busy dialog. Two fail-before cases;
four final cases and 121 combined MPR/admission passes (exit 0). No geometry, rendering
quality or performance claim. Mirror dry-run: zero drift. Fresh-source GUI close during
3D progress and reopen gate pending; ping/actions available on the older running source.
Evidence, remaining scope and narrow rollback are in the VTK domains report's
"OPT-48 MPR deferred 3D teardown reentrancy" section.


## OPT-35 cold preview text-render correction (2026-09-17)

UNIFY-HANDOFF-2026-09-17-03 is implemented/code-verified, pending coordinated fresh-source GUI. `slice_progress.py` changes generated pipe separators to parentheses: VTK interprets pipes as MathText columns. Three fail-before guards include a real cold text-actor render; 49 combined passes and one builder mirror guard pass, 467 mirrors match. Matched synthetic first-render samples: old 441-515 ms with Matplotlib import; fixed 64-81 ms without it (three cold Python processes each, OS caches uncontrolled). No claim of full-app live latency closure. Camera, geometry and literal metadata untouched. Full files, rollback and live gate: VTK report top handoff receipt.


## OPT-35 mixed MR/SC display compatibility (2026-09-17)

Advanced presentation-frame route implemented/code-verified for single-frame MR/SC,
MONOCHROME2/byte RGB, per-frame VOI and separate overlay graphics. Complete local-case
preparation: 45 frames, nine RGB and 45 overlays; native synthetic render/scroll/reset
checks pass. 153 focused passes, 468 source/mirror pairs match. No geometry reconstruction
or full-volume cache for this sequence; no GUI-thread decode. Test-control unavailable,
fresh source/clinical acceptance pending. VTK owner report records exact files, fail-before
proof, bounded memory/layout limitations and rollback. Stale loader identity and generic
failure-to-download mapping handed to the existing Unify UI-stall report, not patched here.


## OPT-35 large DX admission correction (2026-09-18)

Code-verified: Advanced now admits DX for-presentation images without IPP/IOP through its
native independent-frame worker path. Original resolution/window retained; existing filters
remain dispatched. Detector spacing is explicit and the ruler identifies its plane. Synthetic
31.1 MP worker/native render passes; eight local affected DX images prepare successfully.
132 focused passes plus one builder parity pass; 468 mirror pairs match. Existing source test
server responds but predates edits: real drag/drop and packaged acceptance remain pending.
See the VTK domains report's matching correction section for scope, evidence and rollback.


## OPT-35 DOC/SC admission correction (2026-09-20)

Advanced's series-100000 display defect is reproduced as excluded SC/DOC admission, not a
numeric limit. Exact SC/DOC now uses native independent pages without image enhancement or
fabricated spatial geometry. Two worker fail-before cases; 19 presentation cases; 137 focused
and mirror passes, exit 0. Thirty local document samples prepare correctly. Test-control
ping/actions available; fresh-source real drop still pending. See matching VTK domains report
section. Historical OPT-07 shared offset-key work stays separate and is not closed by this fix.


## OPT-35 DOC whole-series budget correction (2026-09-20)

Repeat live failure exposed a second blocker after DOC classification: seven byte-RGB pages
were charged as float64 components, exceeding the 512 MiB preparation cap. Fixed only DOC
RGB accounting: native retained buffers plus largest-page workspace/overlay allowance; cap
unchanged. Fail-before seven-page guard and pre-decode over-budget rejection pass. Full local
seven-page worker delivery/native offscreen switching pass; 138 focused/parity tests pass.
Fresh-source real drop remains pending. See VTK report DOC whole-series memory follow-up.

## 2026-09-20: OPT-51 / OPT-58 Eagle Eye activity presentation

Extend the existing background interaction slice: worker-backed preparation
popups now expose stage text plus indeterminate activity; Lumbar owns one reusable
nonmodal popup through capture/analysis and disposes it at terminal status/teardown.
No worker ownership, GUI-thread decode, network protocol or performance budget was
changed. This is activity visibility, not a latency improvement claim.
Selected-series handoff and review ownership are documented in
`docs/modules/EAGLE_EYE_WORKSPACE_ENTRY_2026-09-11.md`.
Validation: 197 focused/adjacent/builder passes, exit 0; common-popup/Lumbar guards
failed before and passed after; 468 mirror pairs match. Live bridge is reachable,
but the source process predates the changes, so fresh-source native acceptance
remains pending. Rollback only the activity/session hunks and their guard.


## OPT-35 large CT stack interaction and preview continuity (2026-09-20)

Code-verified: geometry-authoritative preview prefix, reuse of valid worker-read window
headers during scroll, and proportional large-stack Advanced drag targets with endpoint
clamping. Seven fail-before assertions; 208 broad passes plus one native transition pass;
four existing display-geometry quarantines remain open. Both local 392-frame CT preview
prefixes match source pixels/order. Cold preview measured about 1.05-1.10 s, so no cold-load
speedup claim. Native filters unchanged; all 468 mirrors match. Real GUI speed/handoff/cache
acceptance pending; no test flag or process changed. VTK report owns full evidence; existing
Unify report owns the idle cache-admission/resume observation request.


OPT-35 large-CT final verification update: older cached payloads also memoize a successful
window-header fallback per viewer instance; additional fail-before guard proves one read
across repeated visits. Final combined suite 210 passed / 4 existing quarantined xfailed,
exit 0, superseding intermediate counts above. No live/FPS equivalence claim.


## OPT-35 redundant spatial render correction (2026-09-20)

Latest sampled slow updates remain render-bound after header reuse. Native fail-before
proved two draws per changed slice. Advanced now prepares visuals at one native render's
StartEvent, with observer cleanup on failure; other contexts retain their existing route.
Pixel-equivalence, camera/order and recovery guards pass. Final 253 passed / 4 existing
geometry xfailed, exit 0; all 468 mirrors match. Synthetic 392-slice rounds reduced draws
60 to 30 per 30 updates; median 14-16 to 11-14 ms, tails variable. No live speed/FPS claim.
VTK report owns details and remaining normal-source GUI gate; no launch flags changed.


## OPT-58 / OPT-60 late-study sidebar generation correction (2026-09-20)

The latest multi-study source trace proved that open admission started with two studies,
the shared back-fill correctly delivered a third, and the patient tab still completed its
older two-study/15-series sidebar snapshot. The third study's DICOM and canonical PNG were
already present; server response and download were not the fault. The grouped render guard
treated an accepted in-flight build as final, while an active prefetch discarded a newer
target topology.

The existing bounded Sidebar owner now keys accepted generations by the immutable ordered
Study/Series identity signature. A changed topology supersedes the old task through its
existing token/cancellation path; a change during prefetch queues exactly one follow-up
worker. The replacement uses the existing off-GUI image/readiness preparation and card
manager, including disk-authoritative ready-border hydration. Same-signature metadata is a
no-op. No alternate loader/downloader, GUI-thread scan, Viewer decode/cache/render change,
flag default or package mirror was introduced.

Two behavioral guards failed before and pass after. Final focused Study-set/sidebar/state
selection: 125 passed; expanded Local/Server/sidebar/identity/lifecycle selection:
259 passed; exits 0. The synthetic 141-card receipt remains bounded (entry below
1 ms in the final run; total application is scheduling/machine dependent and not a product
latency claim). Rollback is limited to the signature/pending-generation methods and two
guards. Fresh-source verification must reopen the affected multi-study pattern and require
the late study/header/card, correct total, blue disk-ready border, stable geometry and the
new PHI-free supersession trace before this item is live-verified.

### OPT-09: isolated Eagle Eye failure evidence (2026-09-22)

The Breast/Bone engine service previously discarded child output and deleted failed work, obscuring a shared exit-103 interpreter-launch failure. It now retains only the final 64 KiB in a private server diagnostic log; completed artifacts never include logs. The failing-before retention guard and adjacent execution guards pass in the 58-test focused selection. This exposed a Codex MSIX-virtualized interpreter home that the desktop-launched app could not resolve; bundle preparation now seals the physical base path. Both actual hosted jobs completed after preparation. No latency improvement or other OPT-09 completion claim is made. Rollback is confined to engine diagnostic capture and the preparation helper; do not restore an inaccessible runtime alias. See the phase-1 execution receipt for UI and classifier limitations.

### 2026-09-22 OPT-56 application chrome and Save branding

Hide native menubar; lock main-window toolbar customization while preserving
Module Selection and internal module controls. Brand native Save dialog without
altering persistence. Fail-before guards, 45 focused passes, final 19 presentation
passes, and 470 mirror matches. Live acceptance remains pending due to concurrent
user input during authorized restart. See the 2026-09-22 section in
`reports/ADVANCED_ANALYSIS_UI_UX_AUDIT_2026-09-15.md`.

### 2026-09-22 OPT-56 installed warm-up resource correction

An installed ARM64-emulated and x64 report showed an automatically visible,
older Slicer interface. On this PC the installed `presentation.py` matches the
earlier installer snapshot, not the newer Developer Run source; the native
viewer executable matches the development/cache copy. Separately, frozen
resident startup resolved its Slicer module guard and presentation script from
the frozen core's module location rather than the installed Advanced MPR runtime.
The frozen-path behavioral guard failed before correction; resident startup now
uses the installed runtime and fails before process creation when guard or
presentation resources are missing. Source mode retains its former paths.
Rollback is limited to this resource resolver; the prior path is unsafe for
installed warm-up. Automated guards and mirror parity are recorded separately
from pending fresh-installer and GUI acceptance. No warm-up timing benefit is
claimed.

### 2026-09-22 OPT-56 native Slicer build provenance

The installer coordinator previously compared only assembled Developer Run
runtime files with the distribution cache, so identical January 2026 native
binaries passed even though C++/CMake/UI source changed in September. A
fail-before guard reproduced that false pass. Assembly now refuses an inner
executable older than native source and writes a source/executable hash record;
cache preparation and both coordinator parity checks require that record.
Current 3.6.7 assets fail closed because they predate the native source and lack
provenance. The pinned Slicer SuperBuild and Qt 5.15.2 SDK were absent at the
documented paths; a deeper search found CMake 3.31.6 and MSVC 14.44 in Visual
Studio 2022 Build Tools outside the default PATH. Native compilation,
fresh immutable cache, role-selected installers, and source/installed GUI
acceptance are pending. This is release correctness, not a runtime speed claim.

### 2026-09-22: OPT-51 / OPT-56 Eagle Eye execution boundary corrections

The actual-model audit reproduced source filtering, PDF completion, Windows child cwd and Slicer DICOM-reference failures. Guarded corrections preserve job ownership, identity checks, cancellation and viewer-domain separation. The Lumbar bridge resolves identity on a read-only worker connection; lesion and nested MS/SVD anatomy scratch are cleaned on all exit paths. Actual full lesion mask/PDF transport and both downstream assessments on that mask completed successfully. The previous local GUI success for spine is not counted as post-fix acceptance. Current verification, actual Standard/Robust PDF and selected-radiograph server receipts, Standard native-runtime residual, lesion repeatability caveat, inaccessible Lumbar menu handoff and pending GUI gates are tracked in [the execution report](reports/EAGLE_EYE_EXECUTION_FIXES_2026-09-22.md). No throughput optimization or release readiness is claimed.

### OPT-51 Brain repeatability follow-up (2026-09-22)

Actual repeated Greedy registration differed with two threads, including a fixed-seed experiment. Fixed seed plus one registration thread produced identical T1/FLAIR matrices in two repeats. The source runner correction has a fail-before guard; 36 affected tests and three payload tests pass. Full post-change lesion inference, native review and Standard native-abort closure remain open. Scope and rollback evidence are in [the existing execution report](reports/EAGLE_EYE_EXECUTION_FIXES_2026-09-22.md). This is repeatability work, not a throughput improvement or release qualification.

### OPT-51 server admission and administration follow-up (2026-09-22)

The Eagle Eye settings tab now exposes the unified client endpoint, owner-filtered
job inventory and next-start server source/resource settings. Worker-owned I/O,
revision-checked atomic writes, FIFO compute reservations, per-client/global bounds
and exclusive durable-directory ownership have focused guards. Actual loopback
Alignment and Bone jobs from two independent client identities completed with
overlapping running states in 277.5 seconds. This establishes execution concurrency,
not a measured throughput gain, GPU scheduling or OS-enforced RAM limits.
119 combined runtime/configuration tests and 40 builder tests pass; all 470 mirror
pairs match. Native GUI acceptance and automatic uncached PACS acquisition remain
open; the latter has an explicit Unify handoff. Brain private numeric diagnostics
now distinguish sampled physical memory from native allocation failure; the
Standard abort remains under investigation. See the implementation ledger in
[the existing server/client plan](plans/architecture/EAGLE_EYE_SERVER_CLIENT_PLAN_2026-09-21.md#11-implementation-ledger-settings-and-bounded-scheduling-2026-09-22)
for files, limits, rollback and remaining gates.

### OPT-51 Brain CPU commit pressure correction (2026-09-22)

Two native-abort dumps identify `std::bad_alloc`. A monitored successful Standard
baseline used 69.6 GB peak private allocation and nearly exhausted Windows system
commit despite free physical RAM. Explicit oneDNN CPU execution completed two
same-input comparisons in 216.7/208.6 seconds versus 402.7 seconds; first comparison
peak private allocation was 26.5 GB. Masks and eight QC values were exactly equal;
probabilistic volume differences are quantified in the execution report. The
SynthSeg-only process environment and result backend metadata now select this
measured path by default. Four fail-before cases and 129 affected passing tests
guard the change. Fresh integrated Robust and Standard passed in 251.6/210.6 seconds
with exact baseline masks, equal QC and complete 29-page derived PDF retrieval;
probabilistic-volume differences are reported separately. Native GUI and broader
clinical qualification remain open. Process evidence now distinguishes private/commit from physical RAM.
Rollback restores the prior high-allocation backend; it is not a safer default.

### OPT-51 SVD anatomical geometry correction (2026-09-22)

SVD previously checked only anatomy/source array size before applying a physical
registration transform. It now rejects differences in spacing, origin or direction
using the existing MS tolerance. Three synthetic SVD cases failed at the registration
boundary before the correction; the corresponding MS cases already passed. The
affected execution, MS, lesion-context, manual-review and lesion selection passed
79 tests, direct exit 0, retries disabled. Rollback removes this isolated additional
check and restores acceptance of geometrically inconsistent labels. Native display
and clinical acceptance remain separate gates; Breast optimization is deferred by
the owner's explicit instruction.

OPT-51 report transport follow-up: lesion HTML used server-only file URIs, so its
previews were unavailable after retrieval by a client. The report now embeds the
same generated PNG bytes, matching the other Brain reports. The transfer guard
failed before the change; 103 affected report/transport/assessment tests pass.
Actual MS/SVD packets contain complete 15/12-page PDFs and six portable previews
each, with masks and without source volumes. Native display remains pending.
Rollback is isolated to `lesion_report.py` and restores server-local image links.

OPT-51 TLS listener isolation: an accepted TCP peer that sent no TLS handshake
blocked the listener before it could dispatch other clients. The extended local
TLS guard reproduced a second authenticated client's handshake timeout. The
listener now defers TLS handshaking to each connection handler, where the existing
30-second socket timeout applies. Certificate and hostname checks remain enabled.
All 45 transport/scheduling/roles/settings tests pass, direct exit 0, retries
disabled. This does not add a connection-count/rate limiter or certify a deployed
network. Rollback of `do_handshake_on_connect=False` restores the reproduced stall.

OPT-51 full LST repetition completed: the two post-registration-fix runs passed in
3484.8 / 3897.8 seconds. Input and model-manifest hashes match; final binary masks
have zero differing voxels and published measurements are exactly equal. Both
native-geometry checks and eight-page PDF retrievals pass, with no DICOM transfer.
NIfTI-roundtrip measurement tolerance and portable HTML verification are detailed
in the execution report. This closes the selected-case two-run engineering gate,
not universal determinism, native display or clinical qualification.

### OPT-51 Windows service lifecycle design review (2026-09-22)

The existing [server/client plan, section 12](plans/architecture/EAGLE_EYE_SERVER_CLIENT_PLAN_2026-09-21.md#12-windows-service-architecture-review-2026-09-22)
now records the verified gaps between the current console/desktop host and an
independent Windows service. Ordered follow-up covers SCM/Session 0 qualification,
explicit role/storage boundaries, transactional recovery, bounded stop versus
maintenance drain, client reconnect, the existing Unify PACS handoff, measured
resource admission, production listener capacity and both frozen installer paths.
Proposed 24/72-hour installed-service soak gates are not completed evidence.
Breast optimization remains deferred. Documentation only: no runtime speed,
service installation, native GUI acceptance or release-readiness claim is made.

### OPT-51 independent service entry and client reconciliation (2026-09-22)

Implementation now adds early SCM/owned-child dispatch in `main.py` and
`eagle_eye_remote/bootstrap.py`, with `service_host.py` supervising listener startup,
pending status and cooperative/forced descendant shutdown. The client now persists
a handle before submission, reconciles uncertain acknowledgement and detaches on
transport failure/observation timeout instead of canceling server work. Two dispatch
and two transport guards failed before correction. Focused verification: 59 tests;
subsequent service/build boundary selection: 41 tests, overlapping, direct exit 0
with retries disabled. All 470 mirror pairs match. No throughput claim is made.

Exact build-task handoff, scoped rollback and remaining work are in
[the existing plan's implementation ledger](plans/architecture/EAGLE_EYE_SERVER_CLIENT_PLAN_2026-09-21.md#13-service-entry-and-reconnect-implementation-ledger-2026-09-22).
Control ping/actions succeeded, but installed SCM/Session 0 tests require an
Administrator context absent in this session; native recovery UI remains open.
No production service, workstation process or release gate changed.

### 2026-09-23: OPT-51 unattended Eagle Eye service and PACS renewal

Status: code verified; isolated Razi SCM lifecycle verified; production promotion
and GUI/real-account/reboot/model acceptance remain open. Source: eagle_eye_remote
pacs_credentials/source/service_admin/service_host/process_owner/launch plus shared
Eagle Eye settings UI and source settings/SCM entries. Five expiry/restart guards,
the missing preset, duplicate listener and viewer import failed before correction.
Focused verification: 66 passed, direct exit 0, retries disabled; 470 mirror pairs pass.

Before: manual-only task; token expiry had no renewal; service import failed on Razi.
After: independent LocalService candidate on 8043, delayed automatic startup, bounded
SCM recovery, encrypted endpoint-bound account renewal, worker-backed administration.
Actual empty stop/start released the listener; injected candidate failure recovered.
Original 8042 task remains because approval review blocked replacement. No clinical
PACS/Breast/CRM processes changed. Rollback: stop/disable only the candidate service.
Evidence and remaining gates: docs/modules/eagle-eye-server-development/docs/SERVICE_AUTH.md.


### 2026-09-23: OPT-51 full Razi workstation transfer; GUI gate failed

The full runtime/UI source and isolated offline environment are installed in the
Razi development workspace; source hashes and post-install pip check pass. Human
sign-in succeeded. Read-only header verification found 128 MR DICOMs, 128 unique
SOPs, one study and five series in this source instance's local cache. This does
not establish source-inventory completeness, selection identity or rendered output.
The owner reported Home freezing; a separate 6050.9 ms Reception-breaker sample
and a session-scoped native Advanced SetInputData access violation were recorded.
GUI acceptance FAILED. No GUI restart, Viewer code repair or feature-flag workaround
was applied. Destination-owner handoffs are in the existing UI-stall and VTK-domain
reports; the build task retains this as a release blocker. Model deployment and
runtime import probes are not clinical inference qualification. The independent
8043 service still responds; its full-source worker alignment remains open.
Details: [deployment ledger section 19](plans/architecture/EAGLE_EYE_SERVER_CLIENT_PLAN_2026-09-21.md#19-full-workstation-deployment-and-failed-gui-acceptance-2026-09-23).


### OPT-21 / OPT-56 follow-up: native graphics admission, 2026-09-23

Razi drag/drop native crash diagnosed at GetDepthBufferSize (execute at zero).
DLL presence was not proof of functional VTK Win32 OpenGL. Shared Standard/Server
startup now probes in an isolated bounded child; failed admission stays on
VTK-free Fast, including empty cells and controller overrides, and blocks MPR.
Before: 10 regression failures. After: 71 focused + 15 parity/service guards,
471 matching mirrors. Local actual native probe passes; Razi interactive probe
correctly rejects unsupported graphics. Seven files deployed to the development
source with baseline verification/backups. Native driver capability remains
unresolved; Advanced/MPR there stay unavailable. Human drag/drop acceptance is
pending. Evidence and rollback: existing VTK domains report, September 23 native
graphics diagnosis section. This extends OPT-21/56, not a new workstream.

### 2026-09-23: OPT-48 Standard MPR residual interaction jitter investigation

Extends the August 1 reconstructed-pane scroll-stability receipt: the owner
reports residual sagittal/coronal CT image shaking and explicitly freezes
geometry. Standard Zeta MPR only. No runtime or mirror edits. Existing focused
geometry/interaction suites pass 51 tests (exit 0); a real-VTK synthetic state
probe passes 3,672 camera/plane checks across acquisition routings, anisotropic
spacing, oblique angles and repeated position changes. These are not rendered
image or live acceptance. Current default sampling excludes automatic VTK
screen-grid quality switching as an established cause. Scheduling, the existing
near-zero rotation reset and sampling appearance remain hypotheses. Local
control-client ping is unavailable; human source test-session bootstrap and an
affected CT are needed for reproduction. No measured before/after improvement
and no bug-fix/closure claim. Evidence and bounded next gate are in the existing
VTK domains report, section "2026-09-23 Standard MPR residual image jitter:
investigation only". Existing geometry and rollback behavior remain unchanged.

September 24 diagnostic update: the owner confirms the 372-frame series jumps
through both viewer routes while the 380-frame series stays stable. A new
standalone synthetic render probe reproduces that distinction using full-precision
local numeric geometry: the 372 setup changes 13,902 screen pixels and its raw
output shifts exactly one row; the 380 setup stays pixel-identical. Disabling
only VTK reslice Optimization in the probe removes the displayed jump without
changing geometry. Native-grid optimized reslicing is the isolated vulnerable
boundary; the internal rounding branch and live attribution require confirmation.
Unquoted PowerShell numeric arguments lose digits and invalidate this comparison.
Runtime/mirrors untouched. Test-control endpoint unavailable; GUI gate unpassed.
Evidence: VTK domains report, "OPT-48 rendered stationarity failure isolated to
VTK optimization". This is diagnostic evidence, not a shipped correction.

September 24 authorized correction: reconstructed reslicers now use general
linear execution (OptimizationOff); native policy and all geometry unchanged.
Four initial guards fail before; 85 focused tests pass after, including a new
enlarged-view rendered guard. Both 372/380 synthetic geometry controls are stable.
Matched warm Render median: 7.03 -> 7.21 ms, local synthetic only. Mirror tool
reports 471 matching pairs, no mirror for the changed source. Rollback: remove
the OptimizationOff block and restart source. Developer-run human visual gate
is pending; documented test-control endpoint remains unavailable. Full receipt
and known-case checklist are in the VTK domains report's developer-run candidate
section. No live or release closure claim.

September 24 fresh-session follow-up: owner reports preliminary success. Source
process launch is after the correction; canonicalization logs show both 372/380
volumes opened at 01:32/01:34, with no MPR-tagged ERROR/CRITICAL in the inspected
interval. This supports the human observation, not independent pixel verification
or full workflow acceptance; test-control endpoint remains unavailable. Details
in the VTK report's fresh source-session observation. No further runtime changes.

### OPT-35 / OPT-60: first-double-click observation, 2026-09-23
Local and Razi first-open complaint remains under diagnosis. One native local double-click opened immediately; no reproducible root cause yet. Viewport mouse and handler outcome observation added (no patient content/no input behavior change), 1 fail-before guard and 47 focused passes. Fresh source reproduction pending. Evidence and rollback: UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md, first-double-click investigation section.


### OPT-21 / OPT-35 / OPT-51 acceptance update, 2026-09-23
Razi source patient open and actual viewport display passed in normal operation with human confirmation and first-image/native/Windows log evidence. Download logs report 12 series / 111 files, matching authoritative count; no new native crash. Remaining: first Fast import 1251.1 ms GUI stall and Download Manager missing-row/convergence warnings. This does not close model/client/concurrency or frozen acceptance. Full evidence: server-development/docs/FULL_WORKSTATION.md, patient-open / viewport receipt.


#### OPT-51 update — role-specific server settings, 2026-09-23

Server settings now separate local AI hosting from outbound client connections.
Legacy AI endpoint controls are hidden without deleting stored values. Installed
edition detection is cached before Qt; settings I/O remains worker-owned. Focused
verification: 33 tests passed; 471 mirrors match. Razi development source updated
with backup and hash verification; fresh-launch live Settings gate pending.

#### OPT-51 update — local Reception and listener UI, 2026-09-24

Validated worker-owned listener settings and service-managed TLS desktop startup
implemented; local Reception configured in Razi development source. 41 focused
tests pass, including synthetic TLS artifact transport; mirrors match. Source
files/config backed up and verified. No 8002 cutover: client-facing address/TLS,
SCM revision alignment and live acceptance remain pending. See FULL_WORKSTATION.

#### OPT-51 update — actual SCM alignment, 2026-09-24

SCM now runs the complete workstation source/venv. Empty-queue restart and
authenticated Client transport over temporary SSH passed; PACS roots configured
from authoritative installed storage settings. Bone Age synthetic model probe
passed; Breast full smoke fails known deferred classifier schema. PACS service
account, real source staging/inference, GUI and public 8002 remain pending.
FULL_WORKSTATION and SERVICE_AUTH record rollback and mandatory future source/SCM
update-restart-verify discipline requested by the owner.

#### OPT-51 update — paired8002 transport, 2026-09-24

Actual SCM now owns TLS8002 with two independent client pairings; legacy Mammography
is stopped, other clinical listener owners unchanged. Positive and negative live
transport tests pass on LAN and public-IP route from this PC. 36 focused tests and
471 mirrors pass. Initial certificate AKI issue corrected without weakening TLS.
Clinical inference, source GUI and outside-network acceptance remain open; see
FULL_WORKSTATION for exact receipts, renewal and rollback.

#### OPT-51 update — SCM native readiness and PACS identity, 2026-09-24

The real Alignment request exposed a first native import/thread-start stall.
`service_host.py` now initializes pydicom on the child main thread before opening
the listener or starting control threads. The live retry remained responsive
(capabilities 0.02–0.04 seconds), exposing an independent metadata rejection:
`source.py` compared administrative Study ID to the requested Study Instance UID.
It now requires the canonical `study_instance_uid`, retaining per-file DICOM checks.
Five new regression cases failed before the corresponding changes. Focused
selections: 25 service tests and 40 identity/source/session tests passed; these
selections overlap. All 471 plugin mirror pairs match.
Only these two source files were transferred in separate baseline-verified updates;
only AIPacsEagleEye was restarted. Rollback copies are in the Razi development
backups service-import-fix-20260924 and pacs-identity-fix-20260924. Live request
now reaches model execution; full result/UI gate is recorded in FULL_WORKSTATION.md.
PACS metadata returned HTTP200 without service credentials for this endpoint;
missing credential_file was not the immediate blocker. Unattended authenticated
PACS renewal remains a separate configuration/acceptance concern.

Live Alignment acceptance: the final retry reached succeeded on Razi and the
existing standard client displayed returned landmarks, overlays and measurement
rows on the selected image. The application also reported its generated PDF ready.
No calibration/review checkbox was attested by the operator or agent. This is a
transport/execution/UI pass, not clinical validation of model measurements.

#### OPT-51 live Bone Age/Breast follow-up, 2026-09-24

Both authorized cases completed through the real paired HTTPS8002 client code:
Razi retrieved PACS sources, ran models and returned verified artifacts. Bone Age
returned one-image real inference with low-confidence/input-coverage flags; its
separate native UI run displayed completion and populated the Bone Age tab, left
pending_review. Breast returned four-image detections in about 73 seconds; lesion
classification remains unavailable (deferred weights mismatch). No runtime edits
or service restart were required in this lap. The native Breast UI repetition and
final acceptance are recorded in the existing FULL_WORKSTATION development runbook.
This establishes execution/transport, not clinical model accuracy.

OPT-51 Breast UI follow-up: native submission, server execution and result
notification passed; classification remains explicitly unavailable. A detection-only
manifest was then discarded by the viewport's optional-classification gate. Four
startup/switch + manifest/fallback regression cases failed before the four-condition
correction. Focused suite: 16 passed; mirror guard: 1 passed; 471 pairs match.
Scoped UI source deployed to Razi with backup mg-detection-only-20260924. No
service restart or unrelated VTK geometry/decoding changes. Final overlay display
remains pending a human-launched fresh source client, not a claimed GUI pass.

#### OPT-51 Alignment result navigation, 2026-09-24

A successful server Alignment job had no persistent workspace review tab. The
controller now embeds the existing measurement widget under Lower Limb Alignment
and reuses the correct series session when revisited. No model, geometry,
calibration or review behavior changed. A real-Qt regression failed before the
fix; workspace/alignment selection passed 51 tests and the extended series-session
guard passed. Scoped source deployed to Razi with backup alignment-tab-20260924.
The original popup/absent-tab behavior was visible in the user's screenshot;
updated GUI acceptance remains pending a normal human source-client restart.

#### OPT-51 remote radiograph semantic binding, 2026-09-24

A real Total Spine server job completed but client review rejected its equivalent
DICOM encoding because whole-file hashes differed. The image loader now computes
a versioned fingerprint of decoded raw pixels, preprocessing output, valid mask,
spacing/calibration and orientation. The server adapter returns that evidence;
the remote bridge requires exact Study/Series/SOP identity, then either exact file
bytes or matching semantic evidence. Total Spine's review binding is translated
only after its source hash, projection and shape are verified; server provenance
remains unchanged. Tests: `test_remote_radiograph_binding.py` demonstrated two
red-before cases; focused runtime and payload suites passed. Razi scoped four-file
update backed up to `backups/radiograph-binding-fix-20260924`; only AIPacsEagleEye
restarted. Real paired round trip: 17 candidates, 35.48 seconds, local binding
matched. This is technical transfer verification, not anatomical acceptance.
Rollback: restore those four files using the deployment manifest (remove only the
new helper if baseline is null), restart inference service. Fresh human-launched
client GUI review remains pending; no hot reload or installed executable used.

#### OPT-51 PACS absence fallback, 2026-09-24

`source.py` now distinguishes explicit HTTP 404 from transport/authentication and
server errors. `PacsWithCacheSource` tries the existing read-only server database
only after StudyNotFound. No source path is accepted from clients. Cache bounds,
completeness and identity/hash checks are reused; incomplete sources fail closed.
Eleven dedicated guards (one red before correction) plus 38 existing PACS/remote
guards passed. Development service updated with baseline verification and source/
config backups under `backups/cache-fallback-20260924`; service cache points to
the actual workstation database and allows its patients/cache roots. Real Brain
request reached fallback but found no matching study in the five-study local DB.
Benchmark NIfTI files are not a DICOM database import. No clinical DB writes or
PACS uploads occurred. Successful Brain inference and GUI verification remain
pending DICOM import. Rollback: restore source.py and server-service.json from
that backup and restart only AIPacsEagleEye.

#### OPT-51 remote human review design, 2026-09-25

Code inspection confirms Alignment/Total Spine editing and Brain manual correction
are local workflows; remote transport lacks revision/upload APIs and the complete
Brain editing reference bundle. Extend the existing server/client plan (remote
manual review section) with immutable server revisions, expected-base conflicts,
reconnect/idempotency, bounded geometry-verified mask uploads and headless server
recalculation. Sequence: Alignment vertical slice, Total Spine, Brain, cross-client
and role/build acceptance. Status: design only; no runtime or service changes,
no GUI/inference acceptance claimed.

#### OPT-51 Alignment remote correction implementation, 2026-09-25

First remote manual-review slice implemented in source and Razi development service.
See the existing Eagle Eye server/client plan implementation section for the contract,
eight-file rollback, 50 automated passes, 471 mirror matches and real 8.01-second
paired correction/PDF receipt. Fresh-source GUI gate pending; no installer acceptance.
Total Spine, Brain upload/edit round trips, revision browsing and cross-process UI
reattachment remain open. Device ownership is verified, not clinician signature.

### OPT-51 follow-up: direct Eagle Eye MCP (2026-09-25)
Shared CommandBus study/series/function control, worker-state observation, explicit Brain input selection and Spine ROI reuse now have focused guards and stdio inventory evidence. See the owning Eagle Eye server/client plan. App attachment/live acceptance and Razi UI delivery remain pending; no mouse automation substitutes for those gates.


### OPT-04 / OPT-51 follow-up, 2026-09-25: exact batch reduction and PatientID contract

Client batch reduction now preserves the server page offset, including odd sizes and resume. Five pre-fix behavioral failures; 16 paging cases now pass. Focused suites: 133 then 85 passed (overlapping); 472 mirrors match. PatientID PATCH exists on Razi, but source semantics lack DICOM rewrite, existing-target reassignment and rollback; client push remains disabled. See the shared-pipeline report section "client paging correction and PatientID contract". Source GUI and artifacts remain pending; no separate PACS changes in this follow-up.

### OPT-51 follow-up: remote Brain, lesions and Total Spine editing (2026-09-25)

Source now extends existing authenticated revision jobs for client mask/endplate
editing, bounded label uploads, server measurement/report generation and SAM box
segmentation. Old masks/results remain immutable; stale lesion success on failed
correction is guarded. See the owning Eagle Eye server/client plan for protocol,
files, tests and rollout boundaries. Fresh source MCP/native Slicer and Razi paired
acceptance are pending; do not deploy the separate in-progress source-sharing
changes incidentally with these shared server files. No release artifact claimed.

OPT-51 remote review final source receipt: 438 affected/adjacent/builder tests pass
(exit 0), 472 mirror pairs match. Brain and lesion consecutive revisions, spine
angle changes/SAM routing and empty-mask first-lesion editing are guarded. Live
MCP/Slicer, coordinated Razi deployment and installed acceptance remain pending.


### OPT-04: September 26 morning download inventory

Read-only installed-Razi versus local audit: 23 studies / 16 patients, 20,095
files, all SOP identities and per-study series counts matched. Requested large
study: 6,218 files / 198 series, including one document. No present data deficit
was reproduced; reported smaller UI count remains unconfirmed. Source GUI control
unavailable; no runtime/deployment changes. See the shared-pipeline report section
"2026-09-26: read-only morning download inventory" for scope and limitations.


### OPT-04: September 26 speed clarification and measured bottleneck boundary

Owner concern is speed/load. Actual LAN body receive reaches about 107 MiB/s;
small installed-PACS requests yield about 24-30 MiB/s useful payload, versus
3.67 MiB/s historical full-workflow average. Twenty slow series account for
144.65 s of 256.19 s cumulative series time; disk write/decode totals are only
12.62/2.53 s. Current measurements do not isolate those stalls. See the shared
pipeline report "LAN throughput and load follow-up" for bounded probe evidence,
resource limits and the next timing boundary. No runtime/server change was made.


### OPT-04: diagnosis before tuning; Poor Connectivity wiring regression

September 26 deeper audit confirms poor-mode configuration is disconnected from
Download Manager batch selection: actual forced-ON replay still requests ten;
explicit diagnostic cap one yields one. Focused legacy guards: 11 pass / 5 fail.
No runtime patch or tuning applied during diagnosis. Historical small-series
20.77 s replayed in 1.633 s; long stalls not reproduced. DB/index stage separately
accounts for 35.041 s. See shared-pipeline "deeper timing / Poor Connectivity
diagnosis" for confounders, required actual-host regression contract and missing
authenticated per-request timing. Preserve poor-link single-image semantics.


### OPT-04: dual transfer modes code-verified, September 26

Owner-authorized Poor Connectivity restoration and normal-mode aligned byte/time-bounded growth are implemented. Single-image poor mode is tied to the actual endpoint and stable per study; normal starts at 10 and can grow to 40 within an estimated 8 MiB / 0.75 s response target. New-loop baseline: 9 fail / 3 pass; final affected/distribution suite: 175 pass. Mirrors: 472 match. Bounded 80-image real-PACS sample used 4 instead of 8 requests and about 30% less wall time; poor mode used 80 one-image requests. Historical stalls, fresh source GUI and built artifacts remain unverified. See shared-pipeline report "dual transfer modes implemented" for full evidence and rollback. No separate PACS changes or U0-U5 state-contract advancement.


### OPT-58 / OPT-60: patient-tab representative thumbnail authority, September 26

The Patient-tab title image had six effective producers across cached startup,
patient pipelines and viewer loading. Selection depended on callback timing and one
cached path incorrectly required an asyncio loop; the deferred write also targeted
the currently selected tab. The shared sidebar card-admission boundary is now the
only producer. It excludes original SeriesNumber 100000, preserves multi-study
offset identity, and targets the registered PatientWidget. This is a U0 presentation
ownership correction, not a new cache, loader or viewer route.

Four guards failed before the change. The affected/adjacent selection passes 238;
packaging-input checks pass 42; compilation and diff checks pass. Selection performs
no scan, DICOM read, DB/network call, decode or VTK construction. Fresh-source GUI is
still required for cold/cached, history, multi-study and rapid-tab-switch acceptance;
installed PyInstaller/Nuitka artifacts remain pending under the normal build workflow.
