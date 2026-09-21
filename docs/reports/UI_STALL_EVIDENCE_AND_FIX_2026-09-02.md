# UI Stall Evidence and Guarded Fixes — 2026-09-02

## 2026-09-20 first-viewer graphics snapshot reuse (OPT-60)

**Fixed and code-verified; fresh-source timing pending.** The current session sampled a
413.6 ms GUI-thread stop while viewer construction re-entered the runtime graphics
resolver and read `runtime_profile.json`. Startup had already completed the same profile
read and hardware/software graphics probe, so the viewer was repeating stable process
configuration rather than obtaining a new clinical or display fact.

`main.py` now hands its completed graphics result to the existing GPU policy module.
That module owns one lock-protected process snapshot shared by Fast and Advanced viewer
construction. Repeated policy resolution performs no filesystem read or graphics probe.
The user-facing GPU save path clears the snapshot, so a changed preference cannot be
served from stale memory; the setting still applies after restart as before. This is
one policy owner, not another fallback or viewer path.

Two behavioral guards were red before the correction. Final focused file: 9 passed.
Adjacent runtime graphics, build profile and Windows-on-ARM policy: 28 passed with one
unrelated deselection; compilation and 468 mirror pairs pass. A fresh source GUI run
must still prove the sampled stack is gone and that first/subsequent viewer backend and
GPU status are unchanged. Advanced render visibility telemetry and remaining pydicom
header reads are separate owner follow-ups.

## 2026-09-20 shared viewport drag-hover dwell (OPT-60)

**Fixed and code-verified; native source GUI pending.** The reported symptom was not
decode, layout construction or download delay. It was an input-policy split: Advanced
had a dwell controller but bypassed it for the exact MIME used by thumbnail drags, while
Fast painted its drop overlay immediately. Both paths accepted every crossing event, so
the visual active state followed the cursor through intermediate panes.

The shared correction delays only hover feedback until the pointer remains within the
existing 8 px tolerance for 120 ms. Continuous traversal restarts that interval. Drop
acceptance is intentionally independent: releasing quickly on the target still schedules
the same backend-owned switch, with the existing zero-delay Qt handoff outside the OLE
callback. No series identity, thumbnail mapping, download intent, decoder, cache, pixel,
geometry, filter or renderer behavior changed.

Fail-before: Fast lacked `_drop_hover_armed`; Advanced set it true at internal drag-enter.
Pass-after: 22 focused cases. Adjacent selection passes 199 with 15 opt-in native skips,
one known quarantine and one unrelated spinner-double case deselected. Required live
receipt is cross-pane traversal plus pause and quick-drop in both backends, exact target
series, one switch/apply, no flash/window, stall or crash. This is an input-boundary fix,
not evidence that U0, Advanced rendering or historical native-crash closure is complete.

## 2026-09-19 inactive patient-tab thumbnail lifecycle (OPT-58 / OPT-60)

**Fixed and code-verified; fresh-source GUI/KPI acceptance pending.** The post-Home-fix
session proved that hidden Home work no longer continued after patient activation, but
patient tabs themselves had no equivalent lifecycle boundary. A cold 23-series Local
owner used the exact verifier for 18,475.34 ms. During that work a second, already-indexed
multi-study owner resolved 65 series in 143.12 ms yet needed 9,169.17 ms to finish its
grouped sidebar. It continued applying cards after a third patient was selected. That
third indexed 31-series owner completed its Local stream in 1,749.58 ms. The discriminating
evidence is therefore concurrent inactive-owner work, not Home, socket latency, decode or
per-card layout cost (the grouped run's maximum apply was 44.46 ms).

The patient widget already received authoritative `on_tab_activated` /
`on_tab_deactivated` callbacks, but those callbacks only informed the viewer controller.
The Local stream timer/worker and qasync prepared-card generation remained active until
tab close or generation supersession. The correction adds one presentation lifecycle
gate shared by those two existing paths. On deactivation, the Local Qt timer stops and
the worker pauses at the next series boundary; one read already in progress may finish,
but it cannot publish or advance to another series. The qasync sidebar can similarly
finish one detached preparation but waits before touching Qt. Activation wakes the same
generation and preserves its identity, reserved rows, card order, cine/object counts,
download projection and completed inventory work. Close and supersession continue to
cancel/retire through their prior paths. The rollback is
`AIPACS_PATIENT_THUMBNAIL_VISIBILITY_GATE=0`.

The same session sampled a 428.3 ms GUI stall inside the Local card trace's synchronous
logging write under overlapping load. Intermediate INFO markers are therefore bounded
to card 1 and every tenth card; the terminal marker still records exact delivered total
and elapsed time. This changes observability volume only, not card cadence or state.
The paused qasync wait also re-checks native owner validity every 50 ms, because direct
native destruction does not wake an `asyncio.Event`; it then exits without preparing or
publishing a stale card.

Fail-before: both lifecycle guards raised because no patient-thumbnail presentation
lifecycle hook existed; the logging guard saw all 25 card markers instead of 1/10/20.
The native-destruction guard timed out before the bounded owner re-check. Pass-after:
Local/sidebar suites 66 passed; adjacent inactive-load,
patient-signal and lifecycle suites 64 passed, all direct exit 0. No live database,
network or clinical fixture was used. Required live gate: restart the normal source app,
rapidly open a cold Local patient, an indexed high-series multi-study patient and a third
patient; require exact cards/order/counts, no overlap/jump, no hidden-owner card markers,
no new stall/crash and normal return to each partially prepared tab.

## 2026-09-19 hidden Home thumbnail work after patient-tab activation (OPT-58 / OPT-60)

**Live defect proved; guarded code correction verified; fresh-source rerun pending.**
The latest normal-source session separated catalog latency from renderer lifecycle.
One grouped Local patient had 24- and 15-series inventories entirely satisfied by the
producer index in 32.56 ms and 21.28 ms. Nevertheless its patient-tab sidebar reported
39 applied cards after 18,822.17 ms, while maximum GUI application for any card was only
21.17 ms. Resource samples during the interval showed approximately one full CPU core.

The correlated owner marker identified the competing work: after the patient tab was
already active, the hidden Home right-panel generation continued preparing all 39
thumbnail images and completed after 15,029.59 ms (`progressive=True`). Hiding a Qt page
stopped paint, but the qasync producer and its progressive timer had no visibility
lifecycle boundary. This explains the indexed case without weakening the separate
finding that the final two historical Local studies still required their one-time
worker verification.

The correction stays inside the existing Home owner. `RightPanelWidget.hideEvent`
suspends its current generation, clears a generation-local async visibility gate and
stops (without deleting) its parented timer. `showEvent` wakes the same generation and
restarts the timer. `prepare_home_thumbnails` checks the gate before admitting each
read and before atomic publication. An already-running native read may complete; no
later read begins while hidden. No card, action token, signature, order, prepared image,
index state, download state or viewer domain is cleared or transferred.

The behavioral guard failed before because all five synthetic reads continued after
hide. Both immediate and progressive forms now prove exactly one admitted read, zero
hidden publication, ordered resume and one final card per series. Four focused Home
image/render/manager suites pass 68 tests; ten broader Home/thumbnail/sidebar suites
pass 163 tests. Both changed runtime modules and the new guard compile, and the scoped
diff check is clean. Live acceptance requires a restarted source process, a large Home
preview followed immediately by patient open, clean patient
first-card/full-sidebar timing, return-to-Home continuation without overlap/jump or
lost double-click identity, and no new ERROR/native fault. The running application
predates this edit and is not evidence of the correction.

## 2026-09-19 legacy Local backfill verification (OPT-58 / OPT-60)

The latest normal-source session separates a recurring persistence defect from the
expected one-time migration cost. Two previously unverified Local studies completed
exact worker scans for 18 and 13 series in 9,174.76 ms and 6,332.91 ms respectively.
Both batches reported `indexed=0`, `scanned=<all>` and `cancelled=False`; this is the
legacy path, not a failure of the producer-index fast path.

A subsequent read-only database/filesystem comparison found all 31 rows in
`Verified` schema 1 state, with valid object/pixel/frame relationships, canonical
two-level managed paths and exact current directory-revision matches (18/18 and
13/13). There was no pixel-inventory writer error or lock failure in the scoped app
or database logs. The unchanged next construction is therefore eligible for the
O(series) index route. Earlier in the same session, producer-indexed studies resolved
24 series in 39.70 ms and 15 series in 23.74 ms without a scan.

This evidence falsifies the hypothesis that completed cold scans were not persisted.
No new pre-indexer, cache, timer, fallback or GUI-thread work was added: a background
whole-library migration would duplicate the canonical catalog owner and could create
unbounded disk contention. New Import/Download generations already publish the same
revision-bound facts at their existing completion seam; old data self-heals once on
the existing worker. The first trustworthy scan of historical/restored data remains
an explicit migration cost and is not called a warm-latency pass.

The local test-control server can activate/open an existing patient tab but exposes no
close action, and native desktop control was unavailable in this session. Its accepted
`open_patient` command therefore did not reconstruct the widget and is not counted as
a reopen pass. Fresh close/reopen of these same unchanged studies remains the narrow
live gate: require `indexed=<all> scanned=0`, exact cards/counts/pixels, no new error or
native fault, and no directory-revision change. This receipt changes no runtime code
or Regression Catalog entry; it records validation of the guarded September 17 fix.

## 2026-09-18 current shared-path decision

This report is the dated evidence ledger for shared UI/catalog work, not a second
roadmap. The only active Unify step is **U0** from the
[canonical execution ledger](../plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md#current-execution-ledger---2026-09-18):
fresh source acceptance of the already-landed ordered Local catalog owner plus the
completed-load tab handoff. No additional thumbnail producer, provisional-card route,
cache layer, timer or downloader fallback is authorized while this gate is open.

The U0 live matrix is one previously unopened single-study Local patient, one previously
unopened multi-study Local patient, warm reopen of both, one Server control, and one
hidden-tab completion/replay. Record first-card and complete-catalog time separately;
verify exact card order, object/frame counts, collision-folder identity, selected pixels,
no overlap/jump, no GUI-thread file I/O and no new ERROR/native fault. End with a normal
application exit and correlate the process-exclusive native sink. A failure extends the
existing OPT-58/OPT-60 owner and guard; it does not create another path.

Only after U0 passes may the shared work move to U1 authoritative download completion,
then U2 state authority, U3 invalidation, U4 path retirement and U5 installed/stress
acceptance. Viewer-specific decode, filters, geometry, rendering and decoded-cache work
remain in their owner documents.

## 2026-09-18 post-catalog orphan-maintenance correction (OPT-58 / OPT-60, U0)

**Fresh-source failure diagnosed; guarded code correction verified; rerun pending.**
The 16:23 process opened three Local cases without an ERROR, CRITICAL, traceback,
Shiboken failure or sampled main-thread stall. The process remained responsive. Its
session-exclusive native sink contained one non-terminal startup `0x8001010d` record
and no access violation.

The first two opens were grouped: 39 cards took 4,385.54 ms after reservation and
66 cards took 5,810.88 ms. Their orphan workers ran for 6,953/3,822 ms and
3,142/297 ms before metadata publication. The third open was a producer-indexed
31-series single study. First Viewer pixels arrived in 1,160 ms, but the first sidebar
card arrived 6,318 ms after stream start and completion took 7,930 ms. The inventory
resolved all 31 indexed series / 1,998 files in 899.33 ms; card application was mostly
18-25 ms with a 52.67 ms maximum. `db_diagnostics.log` attributes the missing 6,285 ms
to `prune_orphan_series_for_study` on its worker. Therefore the prior change removed
the Qt freeze but retained the same maintenance operation as a user-visible admission
barrier. Concurrent file warming read 376-596 MB over 9.8-24.5 s; it may amplify disk
pressure, but this run does not isolate it as the admission cause.

The correction preserves one path and all safety rules. `_build_local_thumbnail_entries`
is now a read/projection owner only. The single-study stream publishes its existing
ordered bounded mailbox and persists counts before its worker performs orphan cleanup.
Grouped Local and Server publish their existing complete metadata before the same Home
background owner reconciles in `finally`; a failed catalog attempt still reaches the
self-heal. The exact pixel inventory remains the pre-publication authority, so absent
or non-pixel rows cannot become visible merely because cleanup moved later. No new
thread, cache, timer, provisional card, download decision, Viewer/VTK or DB deletion
rule was added. PHI-free `LOCAL_ORPHAN_RECONCILE` markers record owner, phase, duration
and counts.

The single-stream behavioral guard failed before because first publish observed prune
already complete. The grouped guard failed with `prune -> push`. Final direct stream,
open and orphan boundary: 61 passed. Adjacent Local catalog, offline, sidebar, metadata,
file-warm and DB-index boundary: 151 passed. Both commands exit 0; source compilation
and diff checks pass. U0 remains open until a restarted source run proves first-card
delivery before reconciliation, exact single/multi-study card identity/order/counts,
no overlap/jump, no new error/native fault and a normal exit.

## 2026-09-17 cold Local inventory/file-warm unification (OPT-58 / OPT-60)

**Live defect reproduced; guarded code fix verified; post-fix live gate partial.**
In the 17:19 source session, producer-indexed 39- and 66-series Local patients
published grouped metadata in 660.6 and 1,494.4 ms. Two previously unopened cases
instead completed at 2,717.0 ms (5 series / 280 cold probes) and 15,157.7 ms
(11 series / 1,172 cold probes). The larger case accumulated 11,525.39 ms of
inventory work while the independent warmer read the same 1,172 files / 307.2 MB
in 14,637 ms. The three slowest series cost 5,338.07, 3,655.92 and 1,228.56 ms.
Grouped card delivery after metadata cost only 434.14 ms. No main-thread stall,
ERROR or CRITICAL event accompanied the delay.

The correction keeps the existing warm pool, budgets and cancellation-independent
daemon ownership. Home supplies detached Local series metadata from its background
setup owner. Only rows that fail the strict producer-index/revision check enter fact
mode. Their DICOMs are parsed by the shared positive pixel-fact single-flight rather
than raw-read in parallel with the later inventory. Inventory still stats each file,
rejects changed versions, re-probes failed/non-pixel outcomes, persists its optional
derived cache and publishes the same revision-checked summary. Indexed Local and all
Server work keep raw warming; catalog-routing failure fails back to raw warming.
`AIPACS_LOCAL_PIXEL_FACT_WARM=0` is the narrow rollback.

Seven targeted assertions failed before implementation while two preserved routes
passed. The final direct boundary passes 55; the expanded Local/storage/sidebar/
multi-study selection passes 358 with one unavailable Windows symlink skip; adjacent
warm/cache/viewer selection passes 76. All commands exit 0 and compilation passes.
No plugin mirror changed.

The restarted 22:12 source session proves the new ownership is active but does not
close the latency defect. Three cold Local opens routed 1,976/721/765 files through
fact mode. The inventory reused 1,888/718/734 facts and issued only 88/3/31 probes;
there was no competing raw-byte warm. First visible content arrived in
1.195-1.330 s. Complete catalog delivery still required 13.707 s for 28 series,
6.950 s for 11 series, and 7.261 s metadata plus 0.595 s grouped application for
22 series. Accumulated single-flight wait was 2.864/3.611/2.027 s, showing that the
independent warmer and sequential per-series consumer still interleave even though
they no longer reread successful headers. The already indexed two-study control
published all 39 series in 669.2 ms; its remaining 5.929 s progressive card rendering
is a separate presentation KPI, not cold classification.

No main-thread stall, ERROR, CRITICAL or current-process native fault was recorded.
The live verdict is therefore: responsiveness guard PASS, duplicate-positive-read
guard PASS, complete cold-catalog latency FAIL/OPEN. The next change must establish
one ordered producer-to-consumer handoff without moving I/O to Qt, weakening exact
pixel/cine facts or changing multi-study identity. Exact visual card/count, reopen
producer-index and installed-build gates remain required.

## 2026-09-17 Local open orphan reconciliation (OPT-58 / OPT-60)

**Live failure diagnosed; guarded code fix verified; post-fix live gate pending.**
The 16:15 source session opened one two-study Local patient. Grouped metadata reached
the tab at 23,279.5 ms after scanning 33 legacy series; several cold header groups
individually took 1.8-2.6 s. The same workload warmed 2,264 files in 14.355 s. This
was the expected first trustworthy scan, not use of the new fast path: no
`source=producer_index` marker appeared. A read-only DB check after completion found
both studies fully backfilled (1/1 and 32/32 Verified), so the next unchanged open is
eligible for O(series) revision checks. Grouped reservation/delivery measured 23.13 /
985.81 ms, with 19.22 ms maximum card application; card painting was not the 23 s cause.

Separately, the main-thread probe recorded a 6,925 ms freeze. Consecutive stacks from
432.6 through 6,547.2 ms stayed in `_on_patient_double_clicked_async ->
prune_orphan_series_for_study -> _series_has_disk_files -> os.listdir`. This closes
the previously open attribution gap: filesystem reconciliation, not server response,
blocked Qt in this interval.

The correction preserves the June orphan safety contract while changing ownership and
cost. No pruning runs in the GUI portion of patient open. Single-study Local executes
it in the existing patient inventory worker; grouped Local and Server execute it in
the existing background setup worker before metadata publication. A series with DB
instance rows first checks one exact `instance_path`; only a missing/stale sample falls
back to directory enumeration. Therefore a deleted sampled file with another surviving
DICOM is still retained, partial-study orphans are still removed, pending zero-row
series remain, and an entirely evicted/offline study still fails safe.

Two focused guards failed before the change. Final direct boundary: 67 passed. Expanded
Local/storage/sidebar/multi-study selection: 337 passed, one unavailable Windows symlink
skip, exit 0. Source compilation passes. Post-fix live acceptance requires a restarted
source process, closing/reopening the same patient, exact card/series counts, an aggregate
`source=producer_index owner=home_local` marker for each study (totals must sum to the
visible catalog), and absence of the orphan-prune GUI stack. No installed,
crash-closure or release claim is made.

## 2026-09-17 Alignment/Stitching artifact contract handoff

ELA source review requests an owner-approved immutable derived-artifact descriptor
through the existing trunk: original study ownership, new derived Series/SOP,
source lineage, content hash, result revision and invalidation. No new catalog or
coordinator is implemented. Stitching currently exports an unrelated study with
no source references; its exporter/geometry findings are routed to the VTK owner.
See [scoped review](../modules/EAGLE_EYE_ALIGNMENT_STITCHING_HANDOFF.md).
Status: shared contract proposal awaiting owner alignment; no Unify runtime edits,
live acceptance or catalog registration claimed.

## 2026-09-17 producer-verified Local catalog facts (OPT-58 / OPT-60)

**Code verified; fresh source cold/warm/restart KPI remains pending.** Review of
the post-QImage run showed the GUI seam was corrected but cold admission was still
coupled to complete pixel verification. A 31-series Local case spent 17.974 s
inspecting 1,998 files; a 29-series grouped case spent 37.305 s over 2,142 files.
The GUI card apply median/max remained 29.72/49.24 ms, and no `read_bytes`,
`_load_from_store` or `load_pixmap` GUI stack appeared. The residual delay therefore
belongs to repeated cold producer facts, not card painting or Viewer decode.

The selected seam extends the existing `series` metadata-index status rather than
introducing another cache or coordinator. Schema 1 stores pixel-object count,
display-frame count and the exact managed series-directory `st_mtime_ns`. Import
propagates scan facts through copy and stamps them only after every destination is
owned by that generation and every instance is indexed. A pre-existing destination
fails closed to Unknown. Download Manager obtains the same facts in its existing
subprocess header executor; unreadable payload probes invalidate summary publication.

`resolve_series_pixel_inventory()` accepts the summary only when all of these hold:
Verified pixel-inventory schema 1, a positive independently recorded object count,
valid object/pixel/frame relationships, canonical two-level containment under the
active DICOM root, and an exact current directory revision. Geometry-index status
is deliberately separate. Otherwise it calls the unchanged
`inspect_series_pixel_inventory()` fallback. Verified non-pixel series remain
excluded; cine object/frame counts remain distinct. PNG presence is not completion,
and download state, Fast/Advanced decode stores and VTK domains are untouched.

After a successful fallback scan, the patient Local owner backfills all scanned
series summaries in one SQLite transaction; the Home Local projection uses that
same batch writer on its existing `asyncio.to_thread` path. This does not mark
geometry metadata Indexed, does not run on GUI, and makes later opens/restarts
eligible for the strict O(series) revision check. The scan revision is carried to
the writer and compared again before commit, so a concurrent directory change is
rejected rather than paired with stale counts. Cancellation skips sidebar backfill.

Regression evidence: the requirement run failed 3/4 cases (exit 1) before the
implementation. The exact contract selection passes 76. Final expanded
Local/catalog/storage/multi-study selection passes 319 with one explicit Windows
symlink-privilege skip; adjacent import/download selection passes 104. All commands
exit 0; compilation
passes and 467 mirrored pairs match. Roll back the six additive series columns,
producer stamp arguments and resolver calls together; retain the earlier Local
stream/QImage, identity allocator and legacy scan. Existing rows require no eager
migration; the first successful fallback scan backfills them safely.
Release parity code checks pass 13/13. The separate current-stage check still fails
on five stale sanitized templates; this slice did not edit generated build output
or run a release build.

Live gate: restart the source build after schema migration; compare one newly
imported and one newly downloaded cine/still study cold, warm and after restart;
verify `source=producer_index`, exact series/card/frame counts, duplicate-number
folders, non-pixel exclusion, offline open and no per-file inventory burst. Then
modify/add/remove a synthetic managed file and prove revision mismatch returns to
the scan. No crash-closure or installed-build claim is made yet.

## 2026-09-17 Local patient-stream image preparation (OPT-58 / OPT-60)

**Code verified; fresh normal-source GUI/KPI acceptance pending.** The 10:49
source receipt isolated a 413.0 ms sampled GUI stack in
`_drain_local_thumbnail_stream -> add_thumbnail_to_thumbnail_layout ->
load_pixmap -> ThumbnailStore.get_bytes -> Path.read_bytes`. Local pixel inventory
already ran on its bounded worker, but its mailbox published only metadata and a
PNG path. The 10 ms GUI drain therefore reopened/decompressed the image before
constructing each card. This was a separate patient-sidebar seam, not a regression
in the corrected Home preparation path or a Viewer decode/render problem.

The existing Local producer now prepares an owned `QImage` through the shared
store-first `ThumbnailImageSourceService.prepare_image` before publishing the
same entry. The two-message mailbox, one-card-per-tick GUI drain, ordered-prefix
allocation, exact Study/Series identity, object/cine counts, count persistence,
grouped takeover, cancellation and terminal outcome are unchanged. Storage reads
use the exact `folder_key` (`1`, `1_2`, and similar collision suffixes), never the
display alias. The GUI converts the immutable image to `QPixmap`, uses the existing
Local placeholder on an empty/failed image, and passes the prepared pixmap to the
same card renderer. No file/network/DB read, QPixmap creation or widget access was
moved to a worker; no new thread, signal, flag, cache, dependency or render path was
added. An in-progress single file read remains non-interruptible, while retirement
continues to reject its delivery and prevents subsequent work.

Regression evidence:

- `test_local_stream_prepares_image_off_gui_and_only_publishes_pixmap` failed on
  the pre-fix behavior with no worker preparation (exit 1), then passed after the
  change. Additional guards pin collision storage keys and placeholder completion
  after a worker read failure.
- `test_local_thumbnail_stream.py`: **37 passed**, exit 0, including identity,
  multi-study takeover, two-message backpressure, native destruction, cine counts,
  refresh, failure and persistence boundaries.
- Nine adjacent Local/Home/sidebar/source suites: **212 passed, 1 skipped**, exit 0.
  The skip is the explicit Windows synthetic-symlink privilege case, not a pass.
  A broader 29-file Local/thumbnail/sidebar/right-panel/pipeline selection passes
  **456 tests with the same 1 skip**, exit 0. Existing SWIG deprecation warnings
  only. Compile, targeted diff check and all **467 mirror pairs** pass.

This changes one existing non-mirrored runtime module and two existing guard files;
no package payload synchronization is required. Roll back only the prepared-image
mailbox field, GUI conversion and `prepared_pixmaps` renderer input to restore the
previous behavior. Do not roll back the earlier Local stream, stable aliases,
pixel-fact cache, Home preparation or bounded grouped builder.

Live gate: restart the source build normally (no test-server flag), open warm and
cold single-study Local cases including duplicate SeriesNumber/folder suffixes,
observe progressive cards and exact image/count identity, then compare session
stalls. Acceptance requires disappearance of this Local `read_bytes` GUI stack;
code passes alone do not establish the latency improvement or native-crash closure.

## 2026-09-17 10:49 normal-source receipt: Home preparation active

Read-only review of fresh source PID 1172172 (10:49:35 launch), fixed log window
10:49:35-11:08:09 across 11 rotated app/viewer/download files, live-writer/delete
sharing. Timestamped records only; do not misclassify untimed historical traceback
continuations as current events. Source files were last edited 10:36-10:37 and
four `[HOME_IMAGE_PREPARE]` records prove execution of the new preparation path.
No test-server marker; the user's normal-launch preference remains unchanged.
No runtime changes, restart, patient manipulation or automated GUI test this turn.

### Observed opens (anonymous aliases, not portable patient identifiers)

| Case | Patient-tab result | Inventory evidence |
|---|---|---|
| A: single Local, 27 series | Open 10:50:29.017; first card 10:50:30.551; 27 cards delivered, stream done 10:50:33.852 (4.835 s after open) | 2424 files, all persisted hits, zero probes; inventory 2571.55 ms, enumeration 60.57 ms, cache load/validation 2317.43 ms |
| B: single Local, 65 series | Open 10:50:59.325; first card 10:51:00.678; 65 cards delivered, stream done 10:51:03.396 (4.071 s after open) | 2074 files, all persisted hits, zero probes; inventory 482.26 ms, enumeration 101.58 ms, cache load/validation 62.40 ms |
| C: six catalog series | Open 10:51:28.570; Local stream ends with zero delivered at 10:51:29.601; Home prepares six images | Six inventory calls find zero direct `.dcm` candidates, zero probes and six no-pixel skips. This does not prove a decode failure or that data is absent everywhere; verify persisted folder mapping and actual download availability before treating it as correct or a regression |
| D: grouped Local, 39 series / 2 studies | Open 10:59:23.941; metadata at 10:59:25.481 (1.540 s); all 39 cards at 10:59:28.757 (4.816 s after open); reserve 36.81 ms, max apply 22.10 ms | 2398 files, all persisted hits, zero probes; inventory 1069.99 ms, enumeration 217.54 ms, cache load/validation 136.93 ms |

All inventory records have zero stat failures. Warm and cold workloads must remain
separate: this run does not exercise the prior 2252 uncached-file header-scan delay.
Repeated `open_request` markers in two logging formats are one event, not extra
opens; repeated `first_series_visible` markers are not independent TTFF samples.

### Home correction and residual shared bottleneck

Home prepares 27 / 65 / 6 / 39 images in 5204.63 / 8348.74 / 180.56 / 4789.94 ms.
Only the six-image case is immediate; others retain progressive scheduling.
**These elapsed values include bounded-buffer backpressure against the unchanged
120-ms UI timer; they are not pure disk latency or all-card paint completion.**
No Home preparation failure, `_build_pixmap_from_thumb` stall stack, deleted-Qt
marker, traceback or MathText/Matplotlib import stack appears in timestamped
main-process records. This is positive sampled execution evidence, not visual
certification of all source/fallback/rapid-replacement/atomic-refresh cases.

The largest patient-work F8 gap is **684.3 ms**, ending 10:50:32.342. Its F11 sample
(413.0 ms) is `_drain_local_thumbnail_stream -> _render_thumbnails_from_entries ->
add_thumbnail_to_thumbnail_layout -> load_pixmap -> _load_from_store -> get_bytes ->
read_bytes -> open`. This is the separate **patient Local stream**, not the corrected
Home adapter. The `local_verified=True` admission intentionally bypasses the cached/
Server batch runner but still uses the unprepared image loader. Next guarded image
slice should pass worker-prepared QImage through that existing stream, preserving
single-owner delivery, object/frame counts, alias order, readiness and cancellation.
Do not change Viewer rendering or add another inventory producer for this fix.

### Stability / Viewer boundaries

54 unique threshold-selected F8 stalls: median 169.75 ms, nearest-rank p95 640.5 ms,
maximum 1908.6 ms (startup/theme), one over 1 s. From first patient open onward:
48 stalls, maximum 684.3 ms; no patient-work gap over 1 s in this sampled window.
Do not compare counts/percentiles to a different-duration workload as a normalized
performance benchmark. Zero ERROR/CRITICAL across all PIDs in the fixed window.
Source remains alive/responding. Current main native sink: zero access violations,
one COM record; observed current child sink: zero faults. No all-crash/exit closure.

Advanced first renders are 56.114 / 53.005 ms; constructor totals 95.360 / 107.834 ms.
The prior long MathText stall is absent. Window-level file reading and placeholder
construction still appear in short sampled GUI stacks; recorded separately in the
Viewer owner report. No Viewer code changed. No new pytest run is claimed for this
log-only review; the previous 214 + 24 code passes remain separate evidence.

## 2026-09-17 Home thumbnail image preparation off GUI (OPT-58 / OPT-60)

**Code verified; fresh normal-source GUI/KPI acceptance pending.** User authorized
remaining corrections after the 10:03 receipt. This slice fixes only the confirmed
Home image-I/O seam (`display_next_thumbnail -> _build_pixmap_from_thumb`, 1274 ms
GUI gap). Cold DICOM admission, cache-read validation and open-time pruning remain
separate; no Viewer rendering/decoding/filter, download, clinical DB or cache-policy
change is bundled here. The 10:29 normal source process was launched without
`AIPACS_TEST_SERVER` as requested; its available traces cover startup and shutdown,
not an affected patient-workflow acceptance of this later edit. No restart performed.

Implementation in three existing core modules (no new flag, module or dependency):

- `thumbnail_image_source_service.py::prepare_home_image` returns an owned QImage
  from explicit path first, then the same six embedded-data aliases, data URL,
  base64/URL-safe padding and raw-byte fallbacks. Home's resolved projection is
  deliberately not reinterpreted as a patient-sidebar ThumbnailStore ordinal.
  Patient-side store-first policy is unchanged. Placeholder painting stays on GUI.
- `thumbnail_batch_runner.py::prepare_home_thumbnails` uses the existing qasync
  executor with detached source dictionaries, one outstanding read per generation
  and at most two ready progressive images. The normal immediate path prepares
  only its existing small batch (default maximum 16) before atomic replacement.
  No per-card thread/signal is created. File reads in progress are not forcibly
  interruptible; cancellation rejects their results and schedules no further reads.
- `right_panel_widget.py` keeps existing generation, signature, identity/action,
  input-synchronous dispatch, small same-identity atomic swap, grouped row, count,
  manager and 120-ms progressive timer contracts. A not-yet-prepared row yields
  instead of reading on GUI; GUI converts QImage to QPixmap and releases the ready
  slot. Source-less progressive rows preserve their previous skip behavior without
  occupying an unconsumable buffer slot. Clear/native destruction retire the task;
  a done callback disconnects destruction hooks even if cancelled before first run.

No-qasync callers explicitly retain synchronous compatibility using the same image
source policy. Normal source/packaged applications run qasync. This fix does not
claim the compatibility route is I/O-free, that an intentionally disabled legacy
batch limit is bounded, or that the existing progressive cadence is optimized.
Repeated rapid replacement can leave old executor reads finishing, but none can
publish or enqueue the remainder of a retired generation.

Verification:

- New `test_home_thumbnail_image_preparation.py`: **23 cases**. Two actual renderer
  guards failed before production changes (exit 1): 3 and 19 QPixmap file reads on
  GUI. The corrected path passes both without changing pixels or source metadata.
- Slow-provider tests exercise real qasync/Qt: main loop remains available; clear,
  native deletion and replacement reject stale identity. Two-image backpressure,
  a 141-entry/three-study repeated-number projection, source-less rows, worker
  failures, image-source priority/formats and small atomic refresh are exercised.
  The scale test accelerates only its test timer, uses lightweight synthetic cards
  and is not a clinical wall-time benchmark or a new production cadence.
- Cancellation-before-start initially exposed a test-baseline issue: PySide installs
  one internal destroyed observer on first Python connection (plain QWidget probe:
  0 -> 2 connected -> 1 disconnected -> 1 after repeat). The guard establishes that
  equivalent baseline, then verifies ten cancelled generations do not grow hooks.
  It does not suppress a callback leak or change production behavior to fit a count.
- Direct pytest, reruns disabled: **214 passed, exit 0** across new Home image,
  Home lifecycle/metadata/actions/open/local projection/input dispatch, patient
  sidebar/Local stream and thumbnail progress boundaries. Additional native card
  effects/panel layout/height/width guards: **24 passed, exit 0**. Existing SWIG
  warnings only. Targeted diff check passes; **467 mirror pairs match**, no sync
  needed for these non-mirrored core modules. No full build or release-lane claim.

Live gate: fresh source launch and human sign-in, preserving the user's normal
no-test-server launch preference. Verify small and large Home previews, rapid
patient replacement, same-identity metadata refresh, grouped headers, empty clear,
exact-series double-click and normal patient-tab/downloading behavior. Compare the
former Home PNG-read stack and new PHI-free `[HOME_IMAGE_PREPARE]` counts/timing;
the latter is preparation completion, not proof of all cards painted or downloads
complete. No agent-operated GUI pass is claimed while the bridge is disabled.

Rollback only this Home preparation helper, image-source adapter and panel wiring,
preserving earlier card lifecycle, Local inventory and Advanced changes. No data
migration, cleanup, new environment flag or persisted setting is involved.

## 2026-09-17 10:03 source receipt: warm grouped improvement, cold admission remains

Read-only review of the user-operated fresh source process (PID 913840, launched
10:03:27). Fixed evidence window 10:03:27-10:16:39, 11 rotated app/viewer/download
files read with live-writer/delete sharing. No runtime changes, new patient opens,
downloads, cache warming/cleanup or process restart in this review. The user reports
the first multistudy case opened well and subsequent loading was slower. Three
opens are present, not just two; anonymous aliases below are local to this receipt.

| Observed case | Inventory and cache | Admission/delivery evidence |
|---|---|---|
| A: Local, 2 studies, 39 series | 2398 files, 2398 disk hits, zero probes; inventory 1472.79 ms; enumeration 269.59 ms; cache path/load 310.28 / 106.85 ms | Open 10:13:25.476; full metadata 10:13:27.487 (2.011 s); 39 cards completed 10:13:31.531 (6.055 s after open); reservation 34.12 ms, builder elapsed 3928.66 ms, maximum card apply 23.84 ms |
| B: Local, 1 study, 43 series | 2252 files, zero hits, 2252 header probes; inventory 20342.88 ms, probes 18995.47 ms, enumeration 53.86 ms, cache path/load 98.18 / 3.78 ms | Open 10:14:15.926; stream starts 10:14:17.693; first card 10:14:18.189 (2.263 s after open); all 43 delivered by 10:14:38.246 and stream finishes 10:14:38.262 (22.336 s after open); maximum card apply 62.92 ms |
| C: Local grouped, 2 studies, 66 series | 2076 files, 2074 hits, 2 probes; inventory 7591.54 ms; enumeration 70.59 ms; cache path/load 65.63 / 6124.85 ms; probes 248.65 ms | Open 10:14:43.497; full metadata 10:14:51.704 (8.207 s); all 66 cards completed 10:14:56.331 (12.834 s after open); reservation 96.57 ms, builder elapsed 4616.53 ms, maximum card apply 19.69 ms |

All three inventory groups have zero stat failures and negligible striped-lock
wait (3.53 / 2.95 / 2.27 ms). Do not compare cold B against warm A as a pure
card-count benchmark. A's primary Study UID matches the previous 09:15 open in
memory; no identifier is recorded here. Its 39-series/2398-file workload matches
the prior receipt: metadata wait 24.096 -> 2.011 s and enumeration 13439.15 ->
269.59 ms. This is observed improvement, not isolation of the code change from OS
cache, disk/AV or scheduling conditions. Initial thumbnail listing is only
7.64 / 5.17 / 10.48 ms; scheduling/delivery wait is a different metric.

### Remaining bottlenecks and causal limits

- **Cold per-series admission is the dominant B delay, not PNG size or the
  two-entry delivery queue.** A 27-file series spends 3852.57 ms in probes; the
  next 90-file series spends 10352.32 ms there. The third/fourth card arrivals
  are 10:14:22.072 / 10:14:32.586. Together those two probes account for about
  14.205 s. The parser reads headers to detect pixel presence/NumberOfFrames,
  not pixel decoding. Missing/expired/version-rejected persisted facts are not
  differentiated by current markers; zero hits alone does not prove which one.
  OS storage/AV versus parser traversal cost is also not isolated.
- **C's remaining cache cost is in read/JSON/digest/record validation, not path
  resolution or enumeration.** The new split timings localize 6.125 s there,
  but do not yet separate open/read latency, CPU validation and scheduling.
  Small 14/32-file entries take 621.45 / 463.50 ms in this phase. Do not remove
  the checksum, TTL, containment or fresh file-version checks to hide this delay.
- **Home still performs synchronous image I/O.** A 1274.0 ms F8 gap ending
  10:14:53.471 overlaps F11 `display_next_thumbnail -> _build_pixmap_from_thumb`
  (sample gap 1258.2 ms); source `right_panel_widget.py` constructs `QPixmap(path)`.
  This overlaps C's sidebar building, so the whole builder elapsed value cannot
  be assigned to card construction. Route image reading through the existing
  shared preparation service in a future guarded slice; preserve Home generation,
  atomic replacement, file/base64 fallback and actions/identity contracts.
- B's 1081.7 ms open-time gap includes a sample in
  `prune_orphan_series_for_study -> _series_has_disk_files`; other samples include
  tab/placeholder creation and graphics-runtime path resolution. Pruning remains
  a separate GUI-thread I/O seam, not permission to remove orphan safety checks.

The single-Local ownership marker appears for B and exactly 43 inventory records
serve 43 delivered cards; the previous duplicate setup producer is not observed
for that open. The shared service remains serial within each inventory. Stream
backpressure is bounded (one producer, queue capacity 2, one card per timer tick),
but a slow early series still holds later ordered delivery. Cancellation is checked
between series; an in-flight header scan is not interruptible by those checks.
Grouped admission still waits for its full catalog. These are real scaling limits,
not proof that increasing worker counts or dropping identity guards is safe.

### Viewer handoff, stability and scale checks

- Four Advanced constructors report first renders 40.747 / 42.059 / 49.160 /
  44.269 ms; constructor totals 98.341 / 141.129 / 83.002 / 76.219 ms. No sampled
  MathText/Matplotlib import stall appears. The former 13.785 s first-render gap
  is absent in this run; this is sampled acceptance of the counter correction,
  not full Advanced geometry/zoom/overlay or all-native-crash acceptance.
- Threshold-selected F8 distribution: 77 unique stalls, median 144.5 ms,
  nearest-rank p95 988.7 ms, maximum 1870.5 ms, 3 above 1 s. The maximum overlaps
  Home startup/theme work. Not a frame-time distribution or normalized comparison
  to the earlier shorter session. Zero ERROR/CRITICAL across all PIDs in the fixed
  window. Current source remains alive. Current-session main native sink has zero
  access violations and one COM exception record; observed child sink has zero
  faults. This is not blanket native-crash closure or proof about later exits.
- Existing client ping and action discovery succeed. No agent-operated patient
  GUI acceptance is claimed beyond the user's reported workflow and scoped logs.
- Direct offscreen pytest, reruns disabled: **125 passed, exit 0**, covering
  bounded/sidebar presentation/overlap, Local stream and persisted inventory.
  The synthetic 141-card case completes all cards: entry handler 0.76 ms,
  reservation 20.28 ms, maximum apply 11.41 ms, elapsed 2234.88 ms. The existing
  suite also checks grouped headers, immutable positions, cancellation/stale
  owners and cache safety. This synthetic prepared-image test is not a 141-series
  cold clinical I/O, high-cardinality multistudy, or native GUI stress pass.

Next order: guard Home image preparation off GUI; distinguish cold fact misses
and read/validation cost before changing cache behavior; then stage catalog-first
presentation independently of verified image admission using stable UID-keyed
slots. Preserve frame/object counts, same-number/different-UID series, grouped
headers and completion authority. Do not change Viewer decode/filter internals.
Full cold/warm, larger multistudy, close/reopen-during-scan and exact-image/count
acceptance remains open. No additional runtime fix is claimed by this review.

## 2026-09-17 Local enumeration cost correction (OPT-58 / OPT-60)

**Code verified; fresh-source GUI/KPI acceptance OPEN.** This follow-up targets
the measured 13.439 s enumeration phase in the 09:13 source receipt below, without
weakening Local image admission or changing grouped UI topology. It does not
claim to eliminate all 24.096 s of grouped metadata wait.

`dicom_displayability.inspect_series_pixel_inventory` used `Path.glob` then
`Path.is_file` for every candidate, discarding the directory entry's available
type information. `_inventory_pixel_facts` subsequently did another fresh stat
for version validation. New helper `_inventory_dicom_paths` retains the existing
enumeration's directory entries, closes the iterator before type filtering, and
returns the same sorted Path list. Platform case matching, direct `.dcm` selection,
file-link following, directory exclusion and glob-style enumeration-error handling
are preserved. Per-entry type lookup failures still propagate as before.

Crucially, **DirEntry.stat is not used for cache version validation**. The existing
fresh Path.stat inside the striped lock and post-probe mutation check remain.
Windows cached entry identity fields may be zero/stale; see the
[Python 3.13 DirEntry contract](https://docs.python.org/3.13/library/os.html#os.DirEntry.stat).
No inventory/UID/count/Ready schema, clinical DB, source files, thumbnail cache
location, threads, dependencies, flags or Viewer implementation changed. Both
Home grouped Local and the patient stream consume this same inventory service.

The existing aggregate marker now separately includes `cache_path_ms` (containment
and path resolution) and `cache_load_ms` (read/JSON validation). Their sum retains
the old `cache_read_ms` meaning. The previous 7.438 s cache phase cannot yet be
attributed exclusively to JSON/disk versus path resolution; do not optimize those
boundaries by guessing or remove containment checks.

Verification:

- New `tests/code/ui_services/test_local_inventory_enumeration.py` has 14 cases.
  The two cost guards fail before the change: cold candidate has 3 rather than
  2 Path.stat calls, warm candidate 2 rather than 1. Three initial scanner-seam
  guards also fail before that seam exists; those are not three additional live
  defects. An intermediate context-manager test mismatch was corrected without
  relaxing the assertions.
- Final new guard: 13 passes / 1 skip (this Windows environment cannot create
  the synthetic symlinks). A 192-file comparison eliminates 192 classification
  Path.stat calls while preserving exact membership/order. This is an operation
  count, not a clinical wall-time benchmark or elimination of version checks.
- Freshness tests replace/delete a file after enumeration; cache admission still
  uses the new version, or rejects the deleted file. Handles close before probes;
  no cached DirEntry.stat is consumed. Selection, failures, counts and PHI-free
  numeric timing fields are guarded.
- Final adversarial review compared the supported Python 3.13 glob implementation:
  an interrupted scan discards the entire listing, not just its unread suffix.
  The corrected guard first failed against the intermediate helper (exit 1).
  The final helper preserves that behavior by collecting directory entries inside
  the enumeration error boundary and keeping type inspection outside it. This
  prevents accidental admission of a partial failed listing; the full expanded
  suite was rerun after this correction with the same 334 passes / 1 skip.
- Expanded startup/stream/offline/cache/real-Qt-sidebar/identity/multistudy/download
  boundary selection: **334 passed / 1 skipped, exit 0**, direct pytest with
  reruns disabled. Only existing SWIG warnings. Source GUI remains a separate gate.
- Final targeted diff check exits 0; read-only mirror verification reports
  **467 matching pairs, zero plugin-only files, exit 0**. This shared utility
  requires no plugin mirror synchronization. The existing test-control client's
  `ping` and `list_actions` both succeed; connection availability is not GUI
  acceptance of an edit absent from the running process.

The source app launched at 09:13:10 predates this patch; no hot reload or live
acceptance is claimed. Repeat the same grouped Local case after coordinated fresh
restart, verify exact Study/Series identity, counts and stable headers/cards, then
compare enumeration/cache/first-card/all-card metrics. Cold classification,
whole-catalog admission, Home GUI PNG I/O and open-time pruning remain follow-up
seams, not silently closed. Advanced first-render work is assigned to the existing
Vtk task under UNIFY-HANDOFF-2026-09-17-03; do not mix its changes with this service.

**Subsequent owner receipt:** Vtk has implemented the independently guarded
Advanced counter correction: generated `|` status separators selected MathText;
parentheses preserve count semantics without that dependency activation. The
[owner receipt](VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#unify-handoff-2026-09-17-03-first-advanced-render-freezes-gui)
records three fail-before guards, 49 focused passes and one builder pass. Unify's
independent rerun of the counter-backend and slice-progress guards reports
10 passed, exit 0, with reruns disabled. Read-only
mirror verification after the handoff still reports 467 matching pairs. This is
not a full live-stall closure: coordinate a fresh-source run for both the Local
multistudy inventory and the first Advanced preview/complete-count workflow.

Rollback only this helper/call-site/timing addition and its guard, preserving the
previous persisted-fact and single-owner changes. No data migration or cleanup.

## 2026-09-17 09:13 source verification: Local multistudy and first render

**Read-only diagnosis; no runtime change or new automated/GUI test execution.**
Human-reported workflow reviewed in source PID 1238252, start 09:13:10, fixed log
window 09:13:10-09:18:00 across 11 app/viewer/download files with live-writer sharing.
The source contains the single-study setup-owner change below. This run instead
opens a **two-study Local case** and a **single-study Server case**. It has zero
Local stream/owner markers: the new single-Local branch was not exercised and is
neither live-accepted nor disproved by this grouped-case result.

### Confirmed Local admission bottleneck

- Local open 09:15:29.162; complete grouped metadata 09:15:53.258: **24.096 s**
  until admission of 39 series. Initial PNG listing is only 4.4 ms; GUI delivery
  of that listing waits 378.91 ms. The early `first_series_visible` marker is not
  an actual-thumbnail first-paint oracle.
- Exactly 39 inventory records visit 2398 files, **zero header probes**, 2398
  persisted hits, zero stat failures. Sequential inventory total **21.361 s**:
  enumeration **13.439 s**, cache-read phase **7.438 s**, cache writes **0.15 ms**,
  striped-lock wait **2.39 ms**. Thus this window falsifies repeated header decode
  and duplicate inventory contention as the dominant grouped delay.
- One 192-file inventory takes 5.112 s, including 4.708 s enumeration. Enumeration
  includes `root.is_dir`, glob, per-entry `is_file` and sorting; cache-read includes
  path resolution, reading and validation. Wall-time logs do not prove a disk,
  antivirus, network-drive or scheduling root cause inside those phases.
- Grouped slots reserve in 33.46 ms at 09:15:53.299; completion is
  09:16:16.164, builder elapsed **22.904 s**, maximum individual card apply
  **28.45 ms**. This interval overlaps the first Advanced render freeze below;
  it cannot all be attributed to PNG work or fixed by shortening the card timer.

### Confirmed first-series GUI freeze and adjacent UI work

One F8 gap is **13.785 s** at 09:16:15.032. Advanced constructor timing attributes
13.209 s to first render (13.402 s total). Repeated samples during this same gap
show native Render entering `matplotlib/mathtext` and importing its dependencies.
Later first-render timings are about 48 ms. Owner evidence and review request are
in [UNIFY-HANDOFF-2026-09-17-03](VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#unify-handoff-2026-09-17-03-first-advanced-render-freezes-gui).
Unify did not edit rendering, decoding, geometry, filters or native text handling.

Other shared UI blockers: the 2.768 s gap ending 09:15:31.929 has consecutive
samples in `_on_patient_double_clicked_async -> prune_orphan_series_for_study`
(`database/dicom_db.py:1427/1431` query/fetch), followed by tab header creation.
Do not assign the entire gap exclusively to pruning. Home's
`right_panel_widget.py:735 _build_pixmap_from_thumb` (`QPixmap(path)`) is sampled
at 09:15:37.869 / 39.099 during gaps of 520.4 / 402.3 ms. These are genuine GUI
I/O seams, separate from the worker inventory and Advanced first render.

Server case: 16 thumbnails arrive in approximately 132 ms at the patient socket
boundary; first bounded build completes about 2.961 s after open. Sixteen file
count checks pass with exact counts in the window (all-process metric, not a
durable SOP completeness certificate). There are zero ERROR/CRITICAL lines, but
83 threshold-selected UI gaps, four over one second, max 13.785 s. Startup gaps
are included; no whole-session responsiveness or crash-closure claim.

Next seams: Advanced owner investigates first-render MathText dependency loading;
Unify separates grouped thumbnail catalog admission from whole-tree validation,
preserving identity/count/Ready authority, then removes Home GUI image I/O and
reviews open-time pruning placement without bypassing its orphan safety purpose.
Do not turn cached PNG presence into proof of pixels/completion or delete study
grouping. Fresh single-Local acceptance and cold/warm grouped KPI gates stay OPEN.

## 2026-09-17 Single-study Local inventory ownership (OPT-58 / OPT-60)

**Status: code verified; fresh-source live/KPI gate OPEN.** The user's request to
remove the bottleneck does not remove study grouping. This is the first bounded
ownership correction, not completion of catalog-first delivery or all latency work.

The preceding source window (00:57:16-01:01:34, main PID 1228520) distinguished
three single-study Local opens. First actual stream cards arrived after
1.376 / 1.629 / 1.320 seconds; all cards after 14.111 / 3.014 / 16.627 seconds.
The 27 / 33 / 65-series cases performed 54 / 66 / 130 inventory calls. Cold
cases probed 2424 / 2074 files once and revisited them through the other consumer;
the warm case had zero header probes and 2411 persisted hits. Per-file locking
prevented duplicate header reads, but did not remove repeated enumeration and
waiting. Overlapping worker durations are NOT additive wall time. Neither this
window nor progressive single-study delivery establishes multistudy acceptance.

### Guarded correction

`_hp_patient_open.py::_background_setup_thread` now returns before Home's series
aggregation and snapshot delivery for exactly one Local study. Patient startup
already starts `_start_local_thumbnail_stream` independently of Home metadata;
that existing bounded, cancelable worker remains the sole inventory/presentation
owner for this open. It retains pixel exclusion, alias allocation, cine/object
counts, exact storage paths, UID-scoped count persistence and GUI delivery.
Home's possibly stale right-panel metadata cannot race it from this setup worker.
The marker is `background_series_info_owned_by_local_stream`.

The worker still kicks the existing file warmer: that is a separate viewer
capability, not the removed metadata authority. Grouped Local retains the complete
catalog aggregation because it suppresses primary-only startup and needs all
study headers/offset identities. Server attachment/metadata routes are unchanged.
Home preview on selection, explicit refresh and compatibility paths remain; this
does not claim globally one scan across every independent UI action. No new worker,
cache, flag, dependency, schema, runtime module or viewer-domain change was added.

### Verification and remaining work

- New behavioral guard `tests/code/ui_services/test_local_open_inventory_owner.py`
  runs the actual nested worker with synthetic I/O: **4 failed / 6 passed before**,
  all **10 passed after**. It checks empty/stale/foreign snapshots, Local failure
  isolation, 2/4-study duplicate-number/unnamed/cine records, partial group coverage,
  grouped error visibility, and unchanged single/multi-study Server routing.
- Focused startup/stream/offline/identity suite: **113 passed, exit 0**. Expanded
  cache, real-Qt sidebar, multistudy projection, exact SeriesRef, file warmer,
  per-study DB selection and download/progress boundaries: **321 passed, exit 0**,
  direct pytest with reruns disabled. Only existing SWIG deprecation warnings.
- Mirror verifier: **467 pairs match, exit 0**. The changed Home core file has
  no plugin payload mirror; no synchronization of another owner's work was needed.
  Targeted diff whitespace checks pass. No build, installed run or release gate.
- Existing test-control client `ping` and `list_actions` succeeded, but PID 1228520
  (00:57:16 startup) predates this patch. Human fresh source restart/sign-in was
  requested. No hot reload, second instance or old-process acceptance.
- After restart: compare the same Local case cold/reopen, verify first/all-card
  timing and one setup-owner marker without a duplicate Home metadata push. Test
  a confirmed multistudy case with matching UIDs, stable headers/card positions,
  repeated/missing descriptions, separate object/cine counts, switching/scrolling
  and close/reopen. GUI input and rendered output remain separate from code tests.

The cold per-series classification barrier and grouped full-catalog admission
remain OPEN. Removing redundant work does not prove those waits disappeared.
Do not bypass pixel validation or infer completeness from a cached PNG to meet a
latency target. The existing revision-scoped catalog/upsert prerequisite still
governs the next cutover. Home GUI image I/O and viewer-specific stalls remain
separate seams. No native-crash, full Unify, download or installed-release closure.

Rollback: remove only the new single-Local early-return branch and its guard;
preserve prior dirty changes. No persisted data or configuration rollback is needed.

## 2026-09-17 Local inventory persistence (OPT-58 / OPT-60)

**Status: code verified; fresh-source GUI/KPI acceptance OPEN.** This is a
conservative reuse slice, not completion of cold catalog-first delivery or of
Unify. It changes only the shared `PacsClient/utils/dicom_displayability.py`
inventory service. No viewer, decoder, filter, widget, download, clinical DB,
source DICOM, feature-default or package-payload change.

### Last source receipt: 2026-09-16 23:40:15-23:42:28

Main PID 739276 includes the bounded sidebar builder, not this persistence patch.
The user opened two Local cases, each with two known studies. Deduplicated
app/viewer/download logs and existing test-control reads give:

| Metric | Local case A | Local case B |
|---|---:|---:|
| Series / inspected files | 39 / 2398 | 34 / 2412 |
| Open to complete metadata push | 6.570 s | 27.004 s |
| Summed pixel inventory duration | 6.095 s | 26.492 s |
| Memory cache hits / probes | 0 / 2398 | 0 / 2412 |
| Summed striped-lock wait | 3.12 ms | 3.46 ms |
| PNG listing duration | 5.75 ms | 4.10 ms |
| Sidebar reservation | 30.36 ms | 31.40 ms |
| Maximum single-card apply | 35.38 ms | 20.33 ms |
| Bounded sidebar elapsed | 2555.43 ms | 1228.98 ms |
| Open to complete grouped cards | 9.177 s | 28.235 s |

Case B includes 27-file and 90-file inventory calls taking 5093.14 and
15057.41 ms. These old records do not distinguish header-parser time from I/O;
disk hardware, antivirus and unusual DICOM structure are **not proven causes**.
The Local branch has no server fetch. `_background_setup_thread` waits for every
`_build_local_series_thumbnail_payload` before the grouped map is published;
that helper classifies every file through the shared inventory authority.
Thus the full Local admission barrier, not PNG listing or lock contention,
dominates this sample. A first-visible marker is not proof of sidebar paint.

Whole window: 48 threshold-selected F8 events, median 164.15 ms, p95 753.1 ms,
max 1893.9 ms (startup). Patient-work window: 43, max 837.6 ms, none above 1 s.
Card-application intervals contain one 104.0-ms event for A and zero for B;
B's inventory wait contains 19 events, max 532.3 ms. No ERROR/CRITICAL in the
scoped logs; current main sink has no access-violation/fatal-Python marker and
one non-terminal COM event. No downloads were exercised. Advanced geometry
and matplotlib stacks remain separate owner findings, not this fix's target.
No controlled same-case old/new A/B was available; do not claim global speedup,
native-crash closure or download acceptance from these numbers.

### Chosen seam and safety contract

The 30-second, 4096-file process LRU remains. Add optional, positive-only,
version-checked metadata reuse across process restart, still inside the same
inventory authority. Do not substitute DB counts, accept PNGs as evidence of
pixels, infer completion, or introduce a second UI catalog writer. Streaming an
unverified grouped catalog was deferred because it would change alias allocation,
non-pixel exclusion, object/frame labels and reserved geometry together.

- Managed `DICOM_IMAGES_DIR/<study>/<series>` only; external/direct media stays
  read-only and on the old probe path. Cache lives under the existing
  `data_paths.CACHE_DIR/local_pixel_facts`, never the DICOM or thumbnail folders.
  An initial adjacent-thumbnail design was rejected: a behavioral guard proved
  it falsely created the legacy folder-existence thumbnail hint.
- Persist path hashes, five stat-version fields, frame count and original
  verification timestamp only. No raw path, UID, patient attribute or pixels in
  the JSON. Profile/root changes cannot match another source. Enumeration stays
  fresh; each file is stat-checked before reuse; new/modified/replaced files are
  probed. Publication requires the unchanged post-probe version.
- Keep only successful positive results. Non-pixel and failed reads retry.
  Schema, root hash, record types, age and checksum must pass. The checksum
  detects accidental corruption, not malicious alteration/authenticity.
- Max verification age 24 hours, not refreshed by a cache hit. Existing memory
  reuse can add up to its 30-second lifetime. Preserved-all-stat-fields external
  rewrites are not detectable until expiry; these hints are not a completion or
  permission certificate. Public import/viewer single-file probes stay uncached.
- At most 8192 records / 1 MiB per artifact; published JSONs bounded to 256 entries
  and 16 MiB, oldest-written eviction in this dedicated cache only. Worker scan
  is capped; unexpected directory contents disable a write, not clinical loading.
  Atomic same-directory replacement; a contended write lock skips persistence
  rather than waiting. Normal temporary files are cleaned in `finally`; process
  death can leave a temporary file, which is not accepted as a cache entry.
  Bounds above describe published JSONs, not arbitrary external files.
- Missing/corrupt/expired/read-only/evicted cache falls back to the existing
  pixel classifier. Deleting source data yields no inventory even if disposable
  metadata remains. No background sweeper, new executor, DB schema or dependency.
- KPI now separates disk hits, enumeration, cache read/write, actual probe sum/max
  and stat failures; all fields are aggregates. Parsing and filesystem time inside
  a single header probe are still combined.

### Verification, rollout and remaining work

`test_local_pixel_inventory_persistence.py`: 32 synthetic cases. Four behavioral
failures preceded the implementation; the thumbnail-presence guard additionally
failed on the intermediate placement and passed after correction. Covers a real
fresh Python process, identity/profile isolation, cine counts, add/remove/replace,
concurrent writers, busy-writer nonblocking behavior, mutation during probe,
stat/read/write/replace failures, non-pixel recovery, corruption, expiry without
renewal, bounded eviction and external-media/public-probe isolation.

Final direct selected pytest: **425 passed, 1 deselected, exit 0**, 44.32 seconds.
This includes the 32 new guards, the original 24 inventory guards and neighboring
sidebar, Local/offline, identity, import/cine, completeness and cleanup boundaries.
Six existing SWIG deprecation warnings remain. 467 mirror pairs
match; this core module has no packaged mirror and requires no new module entry.
No installer build or installed acceptance was run.

Controlled synthetic 64-file test, with artificial per-file latency: cold
1079.73 ms, reuse after clearing memory 17.40 ms, 64 probes -> zero. This is a
helper mechanism check, **not a clinical or GUI speedup claim**. One initial scan
is still required for old data without a valid artifact; the full cold grouped
admission barrier and Local single-study GUI image I/O remain open follow-ups.

The existing control client answers ping/actions, but PID 739276 started before
the patch. Do not hot reload or claim a live pass. After human fresh source
bootstrap/sign-in, open the same two Local cases cold and again after close/reopen;
repeat after a process restart within validity. Require matching identities,
series/object/frame counts, stable headers/cards, working drag/scroll and
`disk_hits` with reduced probes, plus matched F8/F11 and metadata-push timings.
Keep Server workflow and public viewer probes independent. Rollback is scoped
removal of the persistence admission (`cache_path = None`) in this helper,
retaining previous memory reuse/probing; cached JSONs are disposable, not data
migrations. Do not revert the whole dirty file or alter durability settings.

## 2026-09-16 bounded cached-sidebar build (OPT-58 / OPT-60)

**Scope:** correct the measured synchronous cached single-study and grouped
card-construction stalls from the 22:47 source session. No Viewer decode, filter,
VTK/render/cache-domain or download scheduling/protocol changes.

Adversarial follow-up: a server-entry response could otherwise become a second GUI
writer while the cache build awaited preparation. A third pre-fix workflow guard
reproduced that direct GUI image read. Normal qasync server entries now use the
same scheduler after the existing metadata/count merge; background UID-keyed count
persistence is retained. The verified Local stream remains its existing owner.

The previous loop constructs every card before yielding; each insertion also
recomputes the growing layout and can read PNG/store bytes and directory readiness
on GUI. Two real-Qt/qasync workflow guards failed before the correction because
all 20/40 cards existed before the entry handler returned (exit 1).

The existing `thumbnail_batch_runner.py` now owns the cached/grouped preparation
and application cadence. Existing `ThumbnailImageSourceService.prepare_image`
reads/decompresses thumbnail bytes into worker-owned QImage; QPixmap and all card
widgets remain GUI-owned. It uses the actual study UID and persisted PNG stem,
never a secondary-study viewer offset as a storage key. The same disk predicates
are rebound to a detached plain-data snapshot, not a live QObject. Exact expected
DICOM-object counts are captured through `resolve_series_expected_count`; no
viewer/native payload travels into the worker. Root resolution, cache enumeration,
legacy missing-metadata lookup and readiness scans execute in the existing qasync
executor. One card is prepared/applied at a time; no new thread pool or dependency.

GUI first reserves every known header and a lightweight parented 190x215 slot.
It then replaces those slots through the existing card manager, with painting
suppressed and layout activated before paint. Empty QSpacerItems were rejected
during testing: Qt excludes them from inter-widget spacing and they caused visible
one-pixel shifts. Wrapped production headers and real cards now keep their positions.
The series total excludes headings and stays at the admitted plan size. Per-card
layout-height rescans are avoided while the complete reservation is active.

Startup returns the exact cached inventory count immediately; pending cards are
not a cache miss and do not trigger a second import/download route. Grouped True
now means accepted for scheduling; its existing rendered marker is emitted only
after application completes. Close, native destruction, study/path change,
grouped takeover and a newer build reject old delivery. Close cancels the task
without joining the executor. Superseded blank slots are retired under paint
suppression. Current metadata may enrich unknown UIDs for the same study/storage
file but cannot replace a known identity. A changed count/path invalidates old
readiness; current download/completed state is replayed rather than reset by card
construction. Missing grouped caches retain the explicit primary fallback.

**Verification:** final direct focused pytest: **304 passed, 1 deselected**, six
existing SWIG deprecation warnings, process exit 0 (30.44 seconds). New guard file
has **21 cases**; two initial workflow failures and one later server-entry writer
failure were observed before their corresponding corrections. **467 mirror pairs
match**, no payload synchronization needed. Selected-file diff checks pass. No live
DB, clinical file, generated payload, new package module/dependency or config edit.
`test_sidebar_bounded_build.py` covers responsive entry, 141
cards, real header geometry, no overlap/jump/native popup, stable cine counts,
close/delete/supersession, detached worker predicates, current download-state
replay, late metadata, corrupt-store/exact-file fallback, and duplicate-number
multi-study storage keys. The existing presentation guards continue to test the
explicit no-loop compatibility path. The repository-wide suite was not claimed.

**Controlled cost receipt (offscreen, synthetic 141 cards, no disk/network delay):**
legacy whole entry 1002.54 ms; bounded entry 0.88 ms; initial reservation 25.21 ms;
slowest card application 11.12 ms. Bounded total elapsed 1905.42 ms. This is a
responsiveness trade-off, **not a total-throughput speedup or a live KPI claim**;
the GUI gets turns between cards. Repeat the same real heavy workflow after restart.

**Live pending:** the documented bridge answers ping/list_actions, but main PID
1197880 (22:47 launch) predates these edits. Human source restart/sign-in requested;
no hot reload, duplicate instance or fabricated live pass. Verify cold/warm Local
and Server, long multi-study headers, a heavy catalog, native drag/download,
progress, scroll and close/reopen. Inspect `patient_tab_thumb_reserved` reserve_ms
and `patient_tab_thumb_bounded_rendered` / grouped elapsed_ms/max_apply_ms together
with F8/F11. These are sidebar application metrics, not viewport TTFF.

**Remaining:** Local grouped full-inventory admission delay, Local single-study
stream's image read, and explicit no-loop/rollback
compatibility I/O remain separate gates. A finite reservation pass and an individual
card are not hard real-time guarantees. Advanced/MPR stalls stay with their owner.
No crash closure or installed acceptance claim. Existing
`AIPACS_SIDEBAR_BUILD_CHUNKED=0` is the process-start rollback to prior synchronous
cached/grouped behavior (including its known stalls); no new persisted flag/module.

## 2026-09-16 22:47 fresh-source download and KPI receipt

Read-only review of user-exercised source PID 1197880, launched 22:47:00.
Log window 22:47:00-23:04:47, ten app/viewer/download files including rotations.
Existing test-control ping/actions succeed; no runtime edits or extra downloads.

**Suspension fix: sampled positive evidence.** Locally compared authoritative
Study UID with the earlier 21:31 blocked open without exposing the identifier:
the same study opens at 23:01:39, its prewarmed child enters actual download code
at 23:01:41.300, and both real drops at 23:01:45.695 / 47.381 reach the application.
Current state shows its 32-series task completed, 2262/2262 images; its associated
one-series task is 2/2. All five queue tasks are Completed/100%: 354/354, 4647/4647,
3/3, 2262/2262, 2/2. These are accounted totals, not a claim every file was newly
transferred this session. Across subprocesses, 150 file-count checks pass with
present==expected, zero cancelled, maximum check time 11.24 ms. This is not full
SOP/content or clinical validation. The remaining idle spare has UserRequest waits,
not Suspended. Exact rendered-pixel/native-input observation by the agent and the
full pause/close/overlap matrix are still open; logs do not replace visual acceptance.

| Measurement | Result and interpretation |
|---|---|
| Threshold-selected F8 stalls, whole window | 111; median 160.0 ms; nearest-rank p95 1017.0 ms; max 3908.4 ms; seven >1 s. Not percentiles of all UI events. |
| Patient-work window from 22:59:18 | 102; median 163.4 ms; p95 1012.1 ms; six >1 s; same maximum. |
| Cached Local, 39 cards / 2 studies | PNG scan 8.55 ms; queue 0.27 ms, delivery 344.59 ms; full metadata +6.505 s, grouped completion +7.413 s. Metadata barrier remains; warm-up-only attribution unsupported. |
| Heavy 141-series open | Scan 13.61 ms, delivery 165.46 ms. F8 gap 3908.4 ms; repeated F11 samples inside synchronous show_exist_thumbnails/card creation/layout and load_pixmap -> store.get_bytes -> read_bytes. Main-thread work, not waiting for thumbnail network response. |
| Heavy late-study grouping | 141 -> 142 cards / two studies; F8 gap 2566.3 ms with repeated _render_multistudy_grouped/card insertion samples. Stable geometry does not make bulk construction nonblocking. |
| Sampled network-client timing | 43 NET_TIMING requests: total median 67 ms, p95 424 ms, max 823 ms; server wait median 45 ms, p95 399 ms; transfer max 55 ms, parse max 10 ms. This is the instrumented client sample, not all bulk DICOM requests. |
| Initial visibility markers | First marker per open: 1.810 / 1.074 / 4.842 / 1.681 s. Later rerender markers excluded; these are application markers, not independently observed first-pixel latency. |

No ERROR/CRITICAL severity in the scoped app/viewer/download logs (all PIDs).
Session-native sink contains one non-terminal COM marker; same main process remains
responsive. See the crash/KPI owner record. MPR/Advanced stack findings are handed
off to the VTK owner report rather than patched here.

**Next shared slice:** remove GUI-thread store reads and long bulk card creation
from the existing thumbnail admission path, retaining fixed card/header slots,
ordered identity, grouped takeover tokens and stale-callback retirement. Do not
reintroduce progressive geometry jumps or another renderer. Measure preparation,
card application and scheduling separately. Different case counts/workloads prevent
a numerical before/after speedup or no-contention-regression claim for the download
policy. The fix's observed liveness success does not close Unify performance.

## 2026-09-16 OPT-04: download liveness independent of viewport settling

**Status: minimal runtime correction and focused code verification complete;
fresh-source GUI/performance verification pending.** User authorized fixing the
preceding suspended-download incident, then rerunning the source app. The existing
21:27:14 process is not acceptance for this correction and was not hot-reloaded,
resumed, killed or restarted during implementation.

### Decision and scope

Retire native whole-process suspension/resumption of download children from the
interaction boundary. `_nt_suspend_download_subprocesses` and its resume partner
remain callable compatibility no-ops in `_vw_globals.py` and `_legacy_widget.py`.
Registration remains intact for lifecycle/shutdown ownership; current-path normal
termination, forced termination and idempotence are guarded. No new scheduler,
background timer, GUI I/O, feature flag, dependency or package module was added.

This intentionally removes the failure condition rather than trying to resume a
potentially IPC/DB-lock-owning child on every possible viewer lifetime edge.
Balancing one timer/early return would leave other overlapping-viewer, series-switch
and close paths capable of stalling the shared downloader. A periodic forced-resume
watchdog would also interfere with suspension ownership and add a second recovery
path. No such watchdog is introduced.

The existing child `BELOW_NORMAL` priority request is retained, not newly certified
as successfully applied on every Windows host. Download Manager user Pause/Resume,
cancel escalation, priority/preemption, queue identity, protocol, file writes and
Overall Progress are unchanged. No decode, filter, rendering, scroll algorithm or
cache-store implementation was changed. The shared helpers happen to reside in the
VTK compatibility modules; this slice does not edit the other workstream's active
`_vw_series.py`, `_vw_scroll.py` or viewer implementation. The worker registration
comment and its packaged mirror now describe shutdown ownership accurately.

### Reproduction and verification

`tests/code/download_manager/test_download_process_interaction_liveness.py`
executes actual process-control functions with a synthetic Windows API, and actual
prewarm pool handoff/child-entry functions with in-memory IPC. No native suspension,
clinical files, sockets, live database or real child process is used. The scenarios
cover an unsettled interaction, overlapping callers, repeated release, actual
prewarm job admission, registration retirement and shutdown/kill escalation.
They do **not** establish which particular viewer callback was lost in the live run.

- Before production edits: **14 failed / 2 passed, exit 1**. Both routes suspend
  registered workers; both actual prewarm handoff scenarios fail to execute the job.
- After correction: all **16 new guards pass**; with prewarm/registration guards,
  **26 pass, exit 0**.
- Fourteen focused download/system files: **142 pass, exit 0**. Includes cancel,
  cleanup, preemption, resume, deduplicated priority retries, aggregate progress,
  multi-study identity and file-completion guards. Six existing SWIG warnings.
- Expanded selection including `test_vtk_widget_split.py`: **288 pass / 1 fail,
  exit 1**. The failure is an existing `_Spinner` test double missing
  `hide_loading_after`, not download control. Repeated that exact test with both
  original HEAD download-control functions restored only inside an isolated pytest
  process: same exception, exit 1. No source files were reverted or tests weakened.
  Owner handoff is in the Viewer report.
- Package registry/materialization plus prewarm mirror guards: **9 pass, exit 0**.
  Sync changed only the worker-comment mirror; **467 mirror pairs match, exit 0**.
  The two VTK compatibility files are core source, not plugin-mirrored. No installer
  or release build was run; these checks are not installed-client acceptance.

### Fresh-source acceptance and remaining risk

After saving work, close the old source app normally and start one new source app
with the documented test server enabled; human sign-in. Discover/ping the existing
test-control endpoint, then exercise cached Advanced scrolling followed by a remote
multi-series open and two real drops. Require child download entry, increasing real
file/progress counts, exact-series pixels, queued secondary-study completion and
continued responsiveness. Test scroll/series-switch/tab-close overlap and user
Pause/Resume without duplicate workers. Compare scroll/frame and F8/F11 timing on
the same workload: removing hard suspension can increase concurrent CPU/I/O load;
no improved-performance or no-regression claim is made before this check.

This fixes the identified suspension mechanism, not every alive-but-stuck worker
failure; generic job-acceptance/progress watchdogs remain separate OPT-04 work.
Do not hot-reload or force-resume the already suspended live child. There is no new
runtime toggle; any rollback must restore this small change as a reviewed slice
on a fresh process, acknowledging that it reintroduces the known liveness hazard.

Cross-owner receipt: [Viewer handoff 02](VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#unify-handoff-2026-09-16-02-suspended-download-process-after-advanced-interaction).

## 2026-09-16 21:27 session: remote download start blocked

**Diagnostic-only; no runtime change, recovery, restart or fix acceptance.**
The current source run includes the preceding header correction. The user reports
two cached cases around a remote case whose thumbnails arrived but dropped series
never downloaded. The remote task was admitted, both drops reached priority
coordination, and live state remained `Downloading` with zero progress. Repeated
read-only Windows inspection found the adopted prewarmed download child entirely
`Suspended`; Python stacks place it before job receipt, not awaiting the server.
The bridge treats an alive child as ongoing execution and holds the download slot.

This crosses shared download/process coordination and Advanced scroll lifetime.
Evidence, structural release gaps, uncertainties and the requested owner checks
are recorded once in [Viewer handoff 02](VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#unify-handoff-2026-09-16-02-suspended-download-process-after-advanced-interaction).
The exact interaction that left suspension outstanding is not established; no
thumbnail/header regression or server failure is inferred. Keep OPT-04 download
start/liveness open alongside the Viewer-owned release adapter. No runtime tests
were needed or claimed for this read-only diagnosis and documentation handoff.

## 2026-09-16 20:51 source review and study-header geometry correction

**Status:** user reports substantially smoother card loading/replacement on the
20:51:54 source launch (main PID 1207756), with first-open delay and multi-study header
jump remaining. This is partial user-observed acceptance of the preceding sidebar
patch, not exact-identity/full-matrix certification. The header correction below was
made after this launch and still needs fresh-source GUI acceptance.

### Scoped KPI evidence

Window: 20:51:54-20:58:29 local, ten app/viewer/download files including rotations.
Read-only `tools/analysis/oneoff/unify_open_kpi_2026_09_16.ps1` deduplicates trace
timestamp/body copies and emits anonymous ordinals only. Extract identity **after**
`[FAST-OPEN-TRACE]`, not the generic logger's earlier `study=-` context. The existing
stall-summary tool supplies threshold-selected F8 statistics.

| Workflow | Measured evidence and limits |
|---|---|
| First Local open, two known studies / 39 cards | PNG enumeration 7.99 ms; queue 0.36 ms, GUI delivery 391.73 ms. Full metadata pushed at +8.086 s; grouped render done at +8.897 s, 811 ms after the push. Main latency precedes full grouped admission, not PNG enumeration alone. |
| Next Local open, one study / 31 cards | First streamed card at +1.982 s from open / 132.63 ms after stream start; terminal stream duration 7150.8 ms. Apply median 36.55 ms, p95 70.88 ms, max 76.8 ms, sum 1203.51 ms. Remaining elapsed time includes preparation/scheduling/other work; it is not all GUI or all disk time. |
| Server, initially one study | 11 thumbnails fetched in 97 ms. Another study discovered at +2.241 s; grouped list has 12 cards at +2.905 s. Primary rendering before discovery was legitimate, not stale delivery after known grouped ownership. Late topology promotion remains separate. |
| Another Server open | Request deferred once, then canonical cache reused; file rendering starts at +1.449 s. This exercises cache handoff, not every failure/retry case. |
| Download file-count checks | 23 unique checks, all pass with present equal expected, zero cancelled, max check 10.31 ms. Existing file-count gate only, not a SOP-content/clinical completeness certificate. |
| Errors/native evidence | Zero actual ERROR/CRITICAL severity in inspected app/viewer/download window, all PIDs. Main-session native sink has one COM `0x8001010d`, no access-violation/fatal-Python marker; same process answers ping/actions. See crash/KPI owner record; no crash-closure claim. |

Four opens have earliest `first_series_visible` markers at approximately 2.006,
1.871, 1.042 and 0.907 seconds. Exclude the later 8.281-second rerender marker. These
are application markers, not newly observed native first-pixel measurements.

Whole-session selected F8 gaps: **82**, median **163.45 ms**, p95 **949.4 ms**, maximum
**4812.5 ms**, four above one second. Patient-work window from 20:54:09: **73**, median
**165.2 ms**, p95 **913.4 ms**, maximum **1823.8 ms**, two above one second. The two
largest session gaps (4.813 / 2.814 s) are startup/login/Home construction; later >1 s
events align with Home table transition (1.140 s) and import machinery (1.824 s).
Grouped-card stack samples still occur near 419 / 425 ms. Workloads differ from the
earlier 142-card run: no matched cold/warm comparison, percentage speedup, uniformly
improved percentile or all-green KPI claim is justified.

### First-open delay: not established as warm-up alone

Local multi-study startup waits for complete aggregated metadata. `_background_setup_thread`
builds each study's Local payload; `_build_local_series_thumbnail_payload` inspects
pixel inventory. It also kicks budgeted file warming. Tiny PNG scan plus late metadata
identify the grouped metadata barrier, but current timing cannot apportion DB, inventory,
warm-up contention and scheduler costs. Local here is disk/DB-only; the sampled Server
thumbnail fetch is fast. Do not blame the server or add more warm-up work on this evidence.
Next bounded performance slice: measure those worker stages, reuse verified identity-keyed
inventory/catalog preparation, and admit known grouped slots without inventing readiness
or creating another renderer. Do not change decode/filter/Viewer internals here.

### Header defect, correction and verification

Two real-Qt short/long-header cases failed before correction: cards had layout geometry,
but new study labels remained implicitly hidden at `(0,0,640,480)` until the next event
turn. Showing them then shifted cards. Four-study expansion exposed a second gap:
generic minimum height and spare viewport width underestimated wrapped headings;
scrollbar admission resized the container (1247 -> 1280 px in one synthetic case),
moving later cards again.

`_pw_thumbnails.py` now shows headers after parenting while grouped painting is
suppressed, constrained to the existing 190-pixel card column. Height remains
content-derived; dates, previous-exam ID/tag and body-part text are retained.
`_pw_panels.py` reserves the maximum of minimum height and total height-for-width at
the layout's minimum column width before activation/paint. No event pumping, GUI I/O,
worker wait, new source path, decode/filter/Viewer or download change was added.

Four new behavioral cases cover 2/4 studies, short/long/previous-exam headings,
scrollbar admission, no post-paint shift, non-overlap and header-excluded totals.
Initial two cases failed before correction; expanded four-study cases failed before
height-for-width correction. Final 23-file suite: **432 passed**, six existing SWIG
warnings, exit 0. Mirror verification: **467 pairs match**, exit 0. Existing Local,
UID/collision/history/cine, retirement, selection/strip and progress-binding guards pass.

Fresh GUI gate: documented ping/actions work on the old process. Human fresh source
restart/sign-in requested; no hot reload or restart performed here. Observe 2+ study
groups, wrapped previous-exam headings, many-card scroll, stable counts/selection and
exact series opening. A genuinely late-discovered study still triggers the existing
grouped clear/rebuild: this fixes deferred geometry, **not all late topology changes**.
Do not silently hide a new study or retire legitimate fallback routes without parity.
Rollback only this slice's header width/show and height-for-width additions, retaining
the preceding ownership patch and unrelated Viewer work.

## 2026-09-16 Workstream ownership and outgoing Viewer handoff

User decision: this Unify workstream owns common identity/catalog/thumbnail presentation,
download/file/state coordination, cache keys/revision/invalidation contracts and shared
responsiveness/lifecycle boundaries. It does **not** own backend-specific decoding,
filters, rendered geometry, Fast/Advanced rendering or their decoded-cache internals.
The [authoritative boundary and handoff protocol](../plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md#02-workstream-ownership-and-two-way-handoff-user-decision-2026-09-16)
keeps one common coordination path and separate execution domains; it is not a claim
that every historical migration is complete.

The point-in-time Advanced source/payload mismatch is handed to
[the Viewer owner's record](VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#inbound-handoff-from-unify-2026-09-16),
`UNIFY-HANDOFF-2026-09-16-01`. No Viewer code or payload was changed by this handoff.
That owner's later receipt and a fresh read-only verifier now show **467 matching
pairs, exit 0**; this supersedes the earlier observed drift, not the live acceptance
gates. Shared findings from that owner return here with evidence and a backlink;
avoid competing fixes to the same boundary. The central-window cause stays unclassified.

Documentation-only coordination update: no runtime modification or new test/GUI pass.
The preceding sidebar patch still requires its fresh-source live acceptance.

## 2026-09-16 Sidebar presentation boundary correction (OPT-58 / OPT-60)

**Code-verified, fresh-source GUI pending.** User reports overlapping/jumping cards,
changing heights and a transient central window during large-study loading. This
slice corrects reproduced sidebar presentation/ownership defects; it does not certify
the reported popup's cause or close the remaining grouped-render performance work.

### Current-run evidence and diagnosis

The 17:58:46 source session (main PID 1209848) predates this patch. Scoped logs through
18:03:21 show 155 selected F8 gaps above 100 ms, median 141.8 ms, p95 490.8 ms and
maximum 11577.1 ms; three exceed one second. These are session observations, not a
matched before/after performance comparison. A Local stream delivers 31 cards in
6881.92 ms after worker preparation (scan 5.77 ms, wait 418.31 ms, delivery 412.16 ms).
A later Server open fetches 141 primary thumbnails, then an additional study's one
thumbnail. The queued single-study entries render at 18:00:00.479, before grouped
render completion at 18:00:05.771 reports 142 cards across two studies. Sampled UI
stacks include PNG reads and card construction in both paths: redundant primary
construction followed by grouped clear/rebuild is established. Later samples have
less-specific event-loop/progress frames; do not attribute the entire 11.58-second
gap to one method or sum cumulative samples.

Native observation after loading showed the large sidebar and a viewport loading
cover, not a proven separate top-level popup. A transient during-load native window
remains an independent live gate. The VTK task's loading-cover changes are separate.

### Bounded correction and preserved contracts

- `_pw_panels.py::add_thumbnail_to_thumbnail_layout` now suppresses painting during
  card construction/placement, shows the card only after grid parenting, grows the
  scroll container and activates layout before restoring the prior paint state.
  Previously the newly inserted card retained `(0,0)` geometry until a later layout
  event. Nested paint suppression and exception restoration have real-Qt guards.
  The total comes from registered cards, not row indexes that include study headers.
- `_pw_thumbnails.py` rejects queued single-study files/entries and file chunks once
  grouped ownership takes over, and rejects retired/disposed owners. Grouped failure
  explicitly permits the existing primary-study fallback; a new grouped attempt
  reclaims ownership and invalidates old file chunks. Adversarial review caught and
  guarded the over-broad rejection of that fallback before delivery.
- Grouped replacement retires the manager's existing deferred callbacks/effects,
  then hides and schedules deletion of cards **without detaching their native parent**.
  This is a guarded lifecycle correction, not proof of the reported popup/crash cause.
- Local worker delivery publishes only a verified, deterministically ordered prefix.
  An unresolved pixel-bearing alias holds later ordinary cards until full allocation;
  excluded non-pixel records do not become cards. Completion no longer repositions
  already-visible widgets. Existing visible cards retain position during refresh;
  genuinely new refresh entries append instead of reshuffling them. The deliberate
  tradeoff is later appearance of cards after an earlier unresolved alias, not an
  identity shortcut or fake completion marker.

The existing image-source service, ThumbnailManager, allocator, study offsets,
UID/path mapping, history priority, and object-versus-frame counts remain authoritative.
No viewer, decode/encoding, download protocol, schema, credential, dependency or
feature-default change is part of this patch. These two mixins have no plugin payload
mirror. There is no new parallel thumbnail pipeline.

### Verification and outstanding work

Initial guards failed **10 cases** before correction (late delivery, terminal moves,
unpositioned card, parent detachment and mixed-catalog order). Two further retired-owner
guards failed before gating. Three candidate-fix fallback guards failed during
self-review and then passed after preserving explicit fallback. These last three are
review-caught risks, not three additional user-observed production regressions.

Direct pytest (`-p no:debugging --reruns 0`, offscreen) across 23 focused files:
**428 passed, six existing SWIG deprecation warnings, exit 0**. Includes 29 new
`test_sidebar_presentation_boundary.py` cases, Local worker delivery, prepared startup,
pixel inventory/offline/Home projection, metadata identity, multi-study/history/SeriesRef,
normalization/collision, tab/card/manager retirement, Home entry, panel/chunk construction,
active-state/progress-strip and Fast progress binding guards. All inputs are synthetic;
no clinical database is used. Initial mirror verification: **466 pairs match, exit 0**.
The 18:20 final recheck subsequently reports **one drift among 466 pairs, exit 1**.
Its evidence and later passing recheck belong to [the Viewer handoff](VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#inbound-handoff-from-unify-2026-09-16),
not this workstream's implementation queue. Do not overwrite concurrent VTK work.
The edited sidebar mixins themselves have no payload mirrors. Whole-worktree package
parity was not accepted by this original receipt; see the later handoff recheck above.

Documented control-client ping and action discovery succeed. The running source still
predates the edits; human fresh source bootstrap/sign-in was requested. No hot reload,
duplicate source instance or installed-build test was performed. Required native gate:
observe intermediate loading on small/large Local and grouped Server cases; verify
card geometry, stable titles/counts, scroll/selection/progress, exact study/series and
rendered images, then close/reopen with another tab surviving. Capture the transient
window if it recurs. Offscreen geometry is not native GUI acceptance.

Remaining cost: grouped card creation and PNG/readiness work are still synchronous;
Local whole-inventory/warm-up contention and GUI PNG reads remain. Measure these on
the fresh run before the next bounded worker-preparation/grouped-scheduling slice.
No claim of lag elimination, crash closure, download completeness or packaged acceptance.
Rollback only this dated slice's changes in the two mixins; retain its guards and
evidence, and preserve unrelated dirty-worktree/VTK work. Do not reset whole files.

## VTK acceptance handoff: 17:58:46 source session (2026-09-16)

Viewer log sampled a gap rising to 4843.8 ms around 18:00:01-18:00:05. At 18:00:02
the UI stack includes `_render_thumbnails_from_entries` -> `add_thumbnail_to_thumbnail_layout`
-> `thumbnail_image_source_service._load_from_store` -> `thumbnail_store.get_bytes`
-> `Path.read_bytes/open`; later samples include `_render_multistudy_grouped` and
`create_thumbnail_widget`. The next cumulative gap rises to 10642.5 ms at 18:00:16,
but those samples contain only the Qt event loop / main.notify, so their deeper cause
is not established. Do not sum these samples or call them a VTK-render stall. Source
remains reachable; no generic UI code was modified by the VTK task. Full Advanced binds
match 30/30/88/80 source metadata counts, and the user confirms the backdrop fix.

## 2026-09-16 Fresh-session review and sidebar stability gate

**Read-only runtime review plus documentation; no new runtime fix or GUI pass.**
The user-authorized source launch at 17:14:46 (main PID 1206296) contains the
large-number follow-up below. Existing control-client ping and action discovery
succeeded. This supersedes the old-process bootstrap blocker, not full acceptance.

### Bounded log evidence

Application/viewer/download logs across rotations, scoped to this PID through
17:23:40, show zero ERROR records, prior-key rejections or deleted-Qt/fatal markers.
Two Local starts each have one stream start and terminal `outcome=done`:

| Local sample | First card after open | Stream first card | Stream terminal | Open to terminal | Cards delivered |
|---|---:|---:|---:|---:|---:|
| A | 1663 ms | 151 ms | 5019 ms | 6531 ms | 31 |
| B | 1756 ms | 587 ms | 27134 ms | 28303 ms | 20 |

These are card-delivery measurements, not viewport first-pixel times or proof of
pixel/identity/count correctness. Neither sample establishes matched cold/warm
improvement or acceptance of the earlier 19-series large-number case.

Sample B has an 18,551 ms gap between cards 4 and 5. Two 192-file pixel-inventory
records each span about 18,562 ms; one reports 18,156 ms of lock wait. Concurrent
file warming reports 2065 files / 415.3 MB / 24,306 ms. The waiting boundary is local
inventory/I/O, not a PACS-response wait. The logs do not establish whether storage,
security scanning, first-touch cost or contention dominates; disabling warm-up or
loosening validation is not justified by these measurements alone. The paired
inventories are separate consumers, not proof of repeated stream startup.

There are 94 threshold-selected F8 gaps: median 140.3 ms, nearest-rank p95 628.6 ms,
maximum 4897.6 ms, two above 1000 ms. The maximum is a real grouped-sidebar GUI
stall near 17:15:37–17:15:41. Successive sampled stacks show
`_render_multistudy_grouped` -> card construction and
`load_pixmap` -> `_load_from_store` -> `get_bytes` -> `read_bytes`.
The grouped terminal marker reports two studies / 39 series. The other >1-second
F8 gap is startup (1853.6 ms), with an `apply_theme` sample. These are not five
independent freezes merely because the sampler captured five stacks during one gap.

The source process remained responsive at the final process check. A later shared-read
native-file check found one non-terminal main-process `0x8001010d` event, zero access
violations and zero fatal-Python markers in the inspected fresh-session sinks. The
main sink grew after its earlier zero-byte observation; do not preserve a false
"no native events" verdict or equate this COM diagnostic with a terminal crash.

### User requirement and code-review findings

The user requires smooth, reliable sidebar loading without overlap, card jumping,
flicker or oscillating titles/counts. These requirements are now explicit in the
[thumbnail presentation contract](../pipelines/thumbnail-pipeline.md#presentation-acceptance-contract-user-decision-2026-09-16).

The current code confirms several boundaries to guard before the next cutover:

1. `_render_multistudy_grouped` clears widgets and manager collections, performs
   filesystem/readiness work and builds all cards in a single GUI call. Preserve
   study grouping and history order, but do not treat this synchronous loop as the
   desired final unified presentation authority.
2. Its clear path uses `setParent(None)` / `deleteLater()` and direct collection
   assignment rather than the manager's callback/effect retirement boundary.
   This is a lifetime risk to cover, not a newly proven native-crash cause.
3. `_drain_local_thumbnail_stream` repositions surviving cards at terminal completion.
   Widget reuse avoids recreation, but does not prove no visible movement; the new
   per-entry call also needs a behavioral geometry-before-paint guard.
4. `add_thumbnail_to_thumbnail_layout` writes the global label from `thumb_index + 1`.
   Grouped indexes include header rows and the grouped terminal call later corrects
   the count. A progressive conversion must not expose those intermediate totals.
5. Keep the older scoped-style heap-crash fix, strip z-order fix, history/offset
   identity contracts and owner-scoped progress effects intact. Small PNGs do not
   make widget construction, stylesheet work or filesystem operations free.

### Ordered next slice and acceptance

First write failing real-Qt guards for stable geometry, no unchanged-card recreation,
header-excluded counts, label/state/scroll retention and close/late-callback safety.
Then separate immutable exact-identity preparation from bounded GUI presentation
through the existing image-source/projection/card authorities. Preserve legitimate
metadata updates without letting late snapshots overwrite newer values. Do not
implement a timer-only rewrite or a second independent cache/identity pipeline.

Keep total Local inventory/warm-up contention as a separate measured slice after
the grouped GUI freeze; neither bypass pixel validation nor alter decode/download
semantics for thumbnail speed. Fresh-source native GUI checks must observe every
intermediate state, not just the final list. Full crash, Unify, heavy-workload and
installed-runtime acceptance remain open. This entry adds no runtime changes,
test-pass claims, regression-catalog fix row or release claim.

## 2026-09-16 Large-number identity correction and startup deduplication

**OPT-58 / OPT-60 follow-up: code PASS; fresh-source GUI/KPI pending.** This supersedes
the launch-blocked status of the initial streaming slice below. The 16:51:12 source
session did exercise that slice, but its large-case acceptance FAILED; do not retain
the earlier 212-test code receipt as a claim of successful production delivery.

### Diagnosis and pre-fix evidence

- A Local case had 19 series, including six raw series numbers at/above 1,000,000.
  Bounded read-only SQLite inspection confirmed this without retaining identifiers.
  The allocator emitted those raw numbers as UI handles, but its own incremental
  validation rejected prior handles outside `[0, 1_000_000)`. This is not evidence
  of corrupt DICOM or a server timeout, and should not be repaired by weakening validation.
- At 16:53:01 the new Local delivery hit this rejection; at 16:53:22 background Home
  metadata hit the same allocator check. Full metadata for the large case arrived
  about 16,091 ms after open. This was not a continuous 16-second GUI freeze.
- One small Local case completed an inventory before prepared startup called the loader,
  causing a second inventory: the inflight flag alone cannot deduplicate completed work.
- Six new behavioral failures reproduced large-key range/refresh failure, primary versus
  secondary offset isolation, worker-to-GUI delivery rejection and repeated startup
  (64 adjacent passes, exit 1). A separate mixed-catalog test then reproduced the remaining
  all-list delay: first safe card delivery occurred only after inspecting its large sibling.

### Narrow correction

1. `patient_study_set.allocate_series_display_keys` routes raw numbers at/above
   1,000,000 through the existing reserved alias allocator. It still reserves real
   numbers occupying the alias band and rejects already-offset/corrupt prior mappings.
   Original number, UID, folder, exact path and object/frame counts are not rewritten.
   Home, Local and metadata merges use this same shared allocator; no DB migration occurs.
2. `_pw_thumbnails._build_local_thumbnail_entries` can now publish the provably stable
   canonical subset of a mixed catalog. Only unique canonical raw handles below the alias
   band that remain their own key may be published early. Alias-requiring members wait
   for the complete pixel inventory; excluded non-pixel siblings cannot reserve phantom
   aliases. A history-first group requiring full resolution holds early delivery back.
   The GUI still uses the existing bounded mailbox, metadata sink and renderer.
3. Successful Local worker launch records owner-local startup state. `_pw_pipeline`
   does not launch the same startup inventory again after it has finished. Explicit
   refreshes and later metadata-driven additions remain available; a failed thread launch
   does not set that state. This is lifecycle state, not a new feature/configuration flag.

No decoder, download transport, geometry, VTK runtime, clinical file or schema changed.
Existing invalid handles in an already-running process are deliberately NOT remapped
under live cards; a fresh source process is required.

### Verification and acceptance

Direct pytest with `QT_QPA_PLATFORM=offscreen`, `PYTHONPATH=.`, `-p no:debugging`,
`--reruns 0`: **344 passed, exit 0**, six existing SWIG warnings. Selection includes
the stream/startup/incremental-identity guards plus patient-study-set, Local/Home
projection/offline, grouped projection, history order, SeriesRef authority, network
number normalization, download collisions, card/manager/relay lifetime and Home actions.
The three directly affected guard files contain 76 cases. Synthetic guards cover
large-number boundaries, repeat refreshes, storage/frame preservation, interleaved
Home metadata, excluded non-pixel aliases, history order, explicit refresh and thread
start failure. Test workers finish before fake repositories are removed.
Mirror verification: **466 matching pairs, exit 0**; no separate payload copy of these
three canonical files, no new modules/dependencies/flags and no installer build.

Documented MCP fallback `ping` and `list_actions` succeed (83 actions), but source PID
1209712 started at 16:51:12 before this follow-up. No old-process replay, hot reload,
automated login, restart or installed-runtime acceptance was claimed. Human fresh source
launch/sign-in was requested. Then verify the same Local large-number case: early ordinary
cards, all expected final cards, large-series exact UID/path/pixels, counts, close/reopen,
and a confirmed multi-study case sharing small raw numbers. Also verify one startup
inventory per owner without suppressing later refreshes and inspect session-native faults.

Total disk inventory/file-warming cost is still open, and alias-only sets still wait for
full inventory. No matched cold/warm speedup is claimed before fresh live measurement.
Rollback only this follow-up's allocator range predicate, mixed-catalog early-subset
policy and startup deduplication state/gate; preserve the pre-existing dirty worktree.

## VTK-scope handoff: 16:51:12 session on 2026-09-16

At 16:53:01, `_drain_local_thumbnail_stream` -> `set_server_series_info` ->
`allocate_series_display_keys` raises `ValueError: Prior series display keys must be
study-local numeric handles`. At 16:53:22 the same exception occurs through
`_background_setup_thread` -> `set_server_series_info`. This repeats the earlier
handoff and can interrupt series/thumbnail delivery independently of VTK rendering.
No identity/UI fix was made in the VTK task. Source process remains responsive at
the final probe. Keep diagnosis and correction with the identity/Home owner.
The identity-owner code correction is now recorded in the follow-up above; its new
source-GUI acceptance remains pending, separate from VTK acceptance.

## 2026-09-16 Local incremental card delivery (OPT-58 / OPT-60)

**Code correction active at the Local single-study call site; fresh-source GUI/KPI
acceptance remains pending.** This is separate from the dormant Fast initial-display
preparation primitive below. It does not activate that primitive or change decoding.

### Evidence and selected boundary

The 15:42 source session's Local 23-series sample delivered its whole metadata set
about 10,846 ms after open. PNG listing/preparation took about 238 ms; the later wait
included pixel inventories and concurrent file warming. A pair of 52-file inventories
took about 4.4 seconds, with measured cache-lock waits around 1.8–2.1 seconds. This is
evidence of an all-series delivery barrier, not a 10.8-second continuous GUI freeze,
not a server-response wait, and not proof that all time belongs to one consumer.
Repeated `first_series_visible` records must not be treated as actual first-pixel TTFF.

Two gates mattered: Local startup only started its own inventory for Import, waiting
for Home's complete metadata push otherwise; the Local entry builder returned only
after every series was inspected. Existing cached PNGs alone cannot safely supply
clinical identity, collision aliases, pixel eligibility or multiframe display counts.

### Implementation and preserved contracts

- `_pw_pipeline.py` starts the existing Local projection at single-study startup,
  including Local (not only Import), without waiting for Home's whole-study metadata.
  Grouped/multi-study ownership is unchanged.
- `_pw_thumbnails.py` extends the existing Local builder with optional delivery and
  cancellation. Unique canonical numeric series below the reserved alias range may
  publish after each series' complete pixel inventory. Duplicate/legacy/noncanonical
  catalogs still use complete-inventory allocation before delivery. This deliberately
  retains the old collision winner/non-pixel exclusion rule, not a speculative fast path.
- The same builder, display-key allocator, metadata sink and thumbnail renderer are
  reused. Full-catalog reservations and current owner handles must agree; conflicts
  reject delivery rather than retargeting an existing card. No row is admitted merely
  because it appears in the reservation catalog. Study/Series UID, persisted folder,
  original number, 25-instance still and 2-instance/420-frame cine counts stay distinct.
- One worker and a two-message bounded mailbox feed one GUI-parented timer, at most
  one verified card per tick. Backpressure waits only on the worker. No GUI joins,
  `processEvents`, per-card DB threads, network access or VTK construction are added.
  The verified Local renderer does not rescan directories for each Ready check;
  Ready remains local availability, not a server/download completion certificate.
  Existing small PNG reads/QPixmap creation remain on GUI; this is not a zero-I/O claim.
- Close, native QObject destruction, owner change, disposal and transfer to grouped
  rendering stop/reject pending delivery. Inventory failures are not reported as a
  completed inventory. Normal finish repositions surviving cards without recreation;
  UID-matched repeated delivery updates the cine label without duplicate widgets.
  UID-scoped count persistence stays on the inventory worker, separate from GUI work.
- Aggregate traces `local_thumb_stream_start/card/finished` distinguish delivery,
  terminal outcome and GUI `apply_ms`. `elapsed_ms` starts at stream creation, NOT
  at patient double-click and NOT at first viewport pixels. Use session-scoped evidence.

### Verification and remaining gate

Initial optional-delivery/render contracts: four failures before implementation.
The actual startup branch guard separately failed with zero Local inventory launches
where one was required (one failed / 20 passed, exit 1). New Qt/worker tests cover early
delivery while the next inventory is blocked, bounded queue/native destruction,
cancellation, collisions, non-pixel siblings, owner identity rejection, cine counts,
history-first ordering, existing-widget reuse and failure retirement. Tests use synthetic
repositories and pixel facts; the live database and clinical files are not opened.

Final direct pytest selection: **212 passed, exit 0**, reruns disabled (26 stream and
21 startup guards plus adjacent Local/Home/identity/history/collision/Qt lifetime suites;
six existing SWIG deprecation warnings). Fake repositories remain installed until all
test workers terminate; application GUI retirement never joins a worker.
Source mirror verification matches 466 pairs, with no drift; the three modified `PacsClient` mixins have no separate
plugin payload mirror. No new module, dependency, flag, schema or installer entry was added.
No packaged build or installed-client acceptance was performed.

At preflight, the documented local-control `ping` failed and no `main.py` source process
was observed. No restart/login/recovery was improvised. Fresh human source launch with
`AIPACS_TEST_SERVER=1` and sign-in is needed, followed by ping/action discovery and:

1. The same Local large single-study case, cold and warm: first verified card before
   final inventory; correct eventual card count and no late blanking/duplicate widgets.
2. Exact-series selection/drag and visible pixels; still/cine object-versus-frame counts;
   confirmed multi-study and Server cases as negative boundaries.
3. Close during preparation/reopen with a surviving tab: no stale delivery or native
   faults. Match stream timings, F8/F11 and first-pixel markers to this source session.

The whole-study Home inventory and file warming still exist; this patch neither removes
their work nor proves lower total I/O. Duplicate/legacy catalogs intentionally retain their
inventory barrier. The separate study-local/offset-key handoff below remains open.
Rollback only this slice's streaming methods/optional arguments, startup Local gate and
exit-retirement call; preserve earlier dirty-worktree changes and the shared pixel cache.

## Identity handoff from US/VTK investigation, 2026-09-16 15:33

Separate background-setup failure: at 15:33:35 `_background_setup_thread` called
`set_server_series_info` -> `allocate_series_display_keys(existing_records=...)`, which
raised `ValueError: Prior series display keys must be study-local numeric handles`.
Read-only study identity matching links this error to a CT-containing study; it is not
the independently reproduced US missing-IPP/IOP rejection. Review the study-local versus
multi-study offset-key boundary in the incremental metadata workstream. No code fix or
acceptance claim is made here. Coordinate with existing changes; do not remove identity
validation to silence the exception. [VTK diagnostic receipt](VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md).

## Handoff from VTK review: Home startup timing, 2026-09-16

The user requests that general UI defects be handled in their existing workstream,
not in the VTK conversation. The source launch at 15:01:03 produced these subsequent
login/Home metrics: `mainwindow_construct=1855.0 ms`, `home_widget=1139.9 ms`,
`setupUi_apply_theme=428.7 ms`, and an associated event-loop gap of 2058.8 ms.
Sampler stacks traversed Home search-field construction and theme application.
These are observations, not proof that an individual constructor caused the whole gap;
stage timings overlap and must not be added blindly. Investigate under OPT-58/OPT-60.

A later 2177.5 ms gap included VTK placeholder construction and loading-overlay work.
VTK placeholder construction stays with the VTK workstream; generic overlay/theme
overhead belongs here. Coordinate at that boundary to avoid overlapping edits.
The later Advanced constructor/first-render 6102.8 ms gap remains owned by VTK.
No generic UI fix was made as part of this handoff and no other conversation's receipt
or completion is implied. [Source evidence and limits](VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md).

## 2026-09-16 Fast initial-display preparation primitive (OPT-58 / OPT-60)

**Implemented prerequisite, NOT activated in application scheduling.** No factory,
container, controller, download or thumbnail call site invokes the new preparation
API yet. The observed live lag therefore remains OPEN. This slice makes the
worker-to-GUI data handoff testable before changing synchronous switch completion.

### Follow-up: prepared image-identity commit scope (2026-09-16)

The annotation prerequisite found below is now covered for **initial commit**,
not for all later paint/scroll operations. The earlier 29-case / 278-pass receipt
below is historical; this follow-up has 37 preparation cases and 335 focused passes.

- Preparation reads descriptive image tags using the unchanged shared
  `overlay_identity_source.read_identity_tags` on the worker. Frozen facts contain
  string/tuple snapshots for the original metadata first path and, when relevant,
  the sorted multiframe first path used by the existing geometry projection.
  Input metadata is copied once for the whole preparation. Object/frame counts,
  sorting, geometry, pixel transforms and image-over-DB precedence are unchanged.
- Bridge construction rejects mismatched StudyUID, SeriesUID or first-source
  path before consuming adopted facts. `prepared_initial_presentation()` is an
  explicit, single-use synchronous scope for set-slice plus initial W/L. It
  validates identity again at entry and annotation use, does no header/stat I/O
  there, and always releases the snapshot on scope exit or exception. No nested
  event pumping or asynchronous work is permitted inside this commit scope.
- The snapshot is **not** a lifetime cache. Subsequent ordinary refresh uses the
  existing mtime-aware reader; a demographic edit is therefore visible rather
  than pinned until tab close. Failed header reads keep the existing DB-fallback
  semantics without retrying on GUI inside the commit. Shared reader and Advanced
  Viewer behavior were not modified. Later refresh still has its prior stat/read
  cost; removing that requires a separate invalidation/freshness design.
- The complete prepared first-image bridge test no longer stubs annotations.
  Tool persistence and neighbour prefetch remain isolated in that guard; passing
  it does not prove all surrounding controller/tool work is off-thread.

Fail-before: **5 failed / 28 passed, exit 1**. Two failures were missing scoped
API checks; three were actual acceptance of changed study, series or source by
the existing prepared bridge. Eight added cases then cover identity precedence,
no GUI stat/read, post-edit refresh, sorted multi-object cine projection, source
mutation during commit, exception cleanup and failed-read fallback.

Final direct pytest, offscreen, reruns disabled:

- Preparation, overlay identity, demographic editor, earlier Fast/cine/WL/
  geometry/lifecycle/identity selection: **272 passed, 1 existing MG-placeholder
  xfailed**, exit 0.
- Builder registry/materialization and render/cache/color/derived-geometry:
  **63 passed, 3 unavailable clinical-fixture skips**, exit 0.
- Total **335 passed**, one xfailed, three skips. Six SWIG warnings and the
  existing synthetic YBR warning remain. No lint or installed-build pass claimed.
- Mirror dry-run found exactly the two changed Fast files; sync completed and
  verifier reported **466 matching pairs**, exit 0. The additional pair belongs
  to concurrent VTK work, not this slice. No new module/dependency/flag was added.

**Still not activated:** no factory/controller invokes preparation or the new
commit scope. Bounded request-owned scheduling, stale/file revision validation
and preservation of completed-switch semantics are mandatory before activation.
Do not count this as reduction of the observed 4.67-second live gap. Source-GUI
acceptance of that new workflow and matched cold/warm KPI measurements remain open.

Rollback: remove only the follow-up snapshot/context/validation/test hunks and
resync the two Fast mirrors. Preserve the preceding preparation primitive and
unrelated concurrent VTK/cache/controller changes; never revert whole files.

The user explicitly requested one normal close/restart for testing. The old
source main/redirector (1200512/1204772, 15:01:03 launch) exited after native
Alt-F4; no force termination was used. One source launch started at **15:28:41**,
main PID **1191764**, redirector **1197980**, with process-local test-server/socket
flags and the LAN Agent Gateway disabled. This is baseline/bootstrap validation,
not acceptance of an uncalled preparation API; login/patient testing is separate.
Native accessibility observed the disk-space notice and Sign In. The attempted
OK action returned an expired/missing accessibility-element error; acknowledgement
is not claimed. Human OK/sign-in was requested. Pre-login test-server ping was
unavailable (exit 1). GUI acceptance is BLOCKED on bootstrap, not failed rendering.

### Implementation and ownership

- `Lightweight2DPipeline.prepare_initial_display` rejects GUI-thread execution.
  An unpublished worker-owned pipeline uses the existing open/header, pixel,
  W/L, color and filtering implementation. It prepares the first scalar range
  and middle image without launching neighbour prefetch or grow work. This may
  still decode a whole multiframe object internally; it is not a frame-indexed
  codec rewrite or a hard byte budget.
- `PreparedInitialDisplay` transfers only an explicit data-state allowlist.
  Small ownership containers are shallow-copied before producer shutdown;
  decoded arrays/datasets are not deep-copied. QObject affinity, signals, locks,
  executors, futures and interaction ownership are never transferred. The old
  producer is shut down on its worker before returning the result.
- Adoption requires an unused pipeline on its owner thread, matching
  `(viewer-owner, StudyUID, SeriesUID, revision)` key and matching config. It is
  single-consumer; discard is idempotent and cannot clear an adopted consumer's
  caches. Opened/closed/shutdown targets cannot be repopulated by this API.
  Future scheduling must supply the existing stable viewer handle and a revision
  covering request/metadata changes, validate lifetime/files and bound admission;
  equality checking inside the primitive does not replace those responsibilities.
- A keyword-only `initial_display_facts` input on `QtViewerBridge` accepts only
  the facts adopted by that pipeline and the current per-instance W/L policy.
  Initial construction can retain the prepared QImage rather than clearing it
  with redundant frame-zero W/L initialization. Existing callers with no facts
  retain their previous behavior. Reset/grow continue through their old path.
- The existing substantial-window-difference function was moved verbatim to the
  pipeline module and the bridge delegates to it; preparation and presentation
  must not grow separate W/L policies. Missing-pixel preparation is an explicit
  failure, not a successful black placeholder. Cancellation is cooperative
  between operations, not forced interruption of a native codec.

### Initial prerequisite receipt (before the overlay follow-up above)

`tests/code/viewer/test_fast_initial_display_preparation.py` has **29 final
synthetic cases**. The first ten failed before implementation because the new
handoff API was absent (exit 1); this is missing-contract evidence, not a claim
that ten independent live defects were reproduced. The bridge-input guard also
failed before that interface existed. Adversarial tests then reproduced two
first-implementation defects: adopting into an already-shutdown target and
accepting a changed per-instance W/L policy. Both were corrected before delivery.

Guards cover request owner/UID/revision mismatch, config mismatch, single-use and
discard, cancellation before reads and after open, worker shutdown, GUI/owner
thread enforcement, no prefetch, non-mutation of input metadata and pixel failure.
Real offscreen Qt bridge comparisons produce identical QImages for MONOCHROME2,
MONOCHROME1 and RGB, with filtering off/on, and for mildly/substantially different
middle-instance windows with per-instance policy off/on. Synthetic multi-object
cine retains two objects / 20 frames and the same decoded array objects after
handoff. A delayed-read test demonstrates continuing Qt timer callbacks while
the worker waits; it is not a real-workload latency benchmark.

**Important uncovered I/O:** the first full bridge test reached
`_update_annotations -> _build_annotation_metadata ->
overlay_identity_source.read_series_identity_from_instances -> read_identity_tags
-> pydicom.dcmread` on GUI. Even a hit in this provider checks `getmtime`.
The prepared-pixel guard therefore explicitly isolates annotations and tool
persistence: its pass is NOT an all-bridge-no-I/O claim. Before activation,
prepare the displayed image's authoritative identity tags through the existing
trunk, with revision/invalidation semantics for demographic edits. Do not replace
these tags with the tab's DB demographics merely to avoid the read. This remains
an explicit gate, not a silently ignored failure.

### Verification and next slice

Direct `.venv` pytest, `QT_QPA_PLATFORM=offscreen`, `PYTHONPATH=.`,
`-p no:debugging -q --reruns 0 --tb=short`:

- 29 new cases plus the preceding review's 186-case Fast/identity/lifecycle
  selection: **215 passed, 1 existing MG-placeholder quarantined xfailed**, exit 0.
- Plugin registry/materialization, render clock, stack/cache identity, DICOM
  color and derived multiframe geometry: **63 passed, 3 unavailable clinical
  fixture skips**, exit 0.
- Total **278 passed**, one xfailed and three skips across these non-overlapping
  final runs. Intermediate/subset runs are not added again. SWIG warnings and the
  existing synthetic YBR warning remain. No lint pass is claimed.
- `sync_plugin_mirrors.py` updated exactly the two Fast payload files;
  `verify_plugin_mirrors.py`: **465 pairs match**, exit 0. No new module,
  dependency, configuration flag, generated build output or installer was added.

Live GUI: **NOT RUN for the new path, pending activation and fresh-source
bootstrap**. Existing live-session evidence cannot certify this code. Do not
restart the app merely to claim acceptance of an API no runtime caller uses.
No existing user session, clinical files or database were changed by this slice.

Next after the overlay follow-up: bounded request-owned scheduling, file/metadata
freshness validation and factory adoption covering cached/uncached, first
population, reset and progressive delivery. Preserve synchronous completed-switch
meaning for consumers, and separate preparation timings from first actual paint.
The comparative live/KPI matrix in the impact review below remains required.
No global cache, general predecode, or cross-domain VTK handoff is introduced.

Rollback is limited to the new preparation/adoption API, optional bridge facts
and equivalent helper extraction plus their two mirrors. Preserve unrelated dirty
worktree changes; do not revert whole files. No runtime switch currently activates
this path, so rollback is not necessary to retain the current application flow.

## 2026-09-16 Fast initial-display change impact review (OPT-58 / OPT-60)

**Status: pre-implementation review, not a runtime fix.** The user requested a
deeper dependency/regression review before changing this stable workflow. Native
patient-tab drag is user-accepted; do not reopen that input investigation merely
because the earlier MCP lap did not synthesize OLE drag. This acceptance does not
close the independently observed initial-display latency.

### Confirmed boundary and newly identified dependencies

The preceding source-session receipt records repeated GUI DICOM reads during the
4,673.3 ms cine-switch gap. Code inspection confirms three potentially blocking
steps: `_vw_globals._create_qt_viewer_bridge` calls `pipeline.open_series` (header
hydration and multiframe expansion); `QtViewerBridge._build_mock_vtk_data` requests
the actual scalar range and default W/L for frame zero; `QtFastContainer._start_qt_viewer`
then renders the middle frame and applies its default W/L. Header-only reads can
also block. Do not attribute the whole gap to codec CPU time, or promise a speedup
from offloading alone: direct stage timing and a matched workload are still needed.

| Boundary inspected | Existing contract / regression risk | Required protection |
|---|---|---|
| `_vc_switch._perform_series_switch_optimized` | A truthy synchronous `switch_series` result immediately resets the slider, clears awaiting state, updates tools/progressive mode, starts the booster and hides loading | Do not redefine `True` as merely queued; separate preparation from the existing completed GUI commit, or migrate every completion consumer together |
| `_pw_series`, `_pw_lifecycle`, `_pw_pipeline`, `_vc_load`, `_vc_warmup` | Additional switch callers and first-population routes exist | Cover each Fast entry route; fixing only one mouse or cache-miss branch leaves cold GUI reads reachable |
| `QtFastContainer.switch_series/reset_image/cleanup` | Same-series skip, force reload, volume-behind rebuild, reentrancy and parent-retained widget retirement already have distinct purposes | Preserve them; invalidate pending preparation on replacement, reset, layout retirement and close; no nested `processEvents` |
| `Lightweight2DPipeline(QObject)` | Mutable slice/WL/pixel/frame state, signals and three executors; `close_series` clears state before non-waiting executor shutdown | Do not hand the live pipeline to another worker; cancellation is not proof that a running decoder stopped; define exclusive preparation ownership and disposal before offloading |
| `QtViewerBridge` initialization/reset/grow | `_build_mock_vtk_data` is not constructor-only; W/L can be resolved per instance | Preserve exact W/L, scalar range, current-slice/reset policy and geometry; no guessed range or blanket frame-zero-only optimization |
| Multiframe dataset cache and W/L memo | Locked dataset LRU and series-scoped W/L memo avoid repeated full-file work; cache limit is object-count based, not a hard byte budget | Preserve reuse and frame indexing; measure decoded bytes/RSS and bound active preparation, not just queued futures |
| Factory per-frame metadata projection | Expanded bridge geometry is a shallow copy, not a rewrite of shared DB instance metadata | Keep object/download counts separate from displayed frame counts; protect source metadata against mutation |

`_ensure_qt_bridge` is another factory-capable method, but repository search found
its definition only. This is not evidence that it caused the live lag and is not
permission to delete it. `_vw_series` and legacy factories also exist: route
provenance and compatibility must be established before changing/removing them.
Advanced/VTK/MPR behavior is outside this Fast-domain correction.

### Selected direction and rejected shortcuts

Use **prepare -> validate -> GUI commit**, within the existing request/identity
flow. Prefer preparing before the existing synchronous completed-switch boundary
so its consumers retain their meaning. Reuse stable viewer handles, request
tokens and cancellation registry rather than inventing another numeric-key
identity scheme. Cache-hit metadata is not proof that pixel/WL/header caches are
warm; both cached and uncached entry routes must reach preparation when needed.

The worker input must be an owned snapshot of the selected series and presentation
policy, without QWidget/VTK references. Its result must include enough prepared
metadata/pixels/display facts to prevent a second cold read during GUI adoption.
Study UID, Series UID, viewer lifetime, request generation and file/metadata
revision must still match at delivery. A same-UID reset or progressive append can
make an old result stale. Results are immutable at the boundary, or have an
explicit exclusive-ownership transfer; never share mutable pipeline/cache state
concurrently. Avoid copying whole decoded cine datasets just to enforce this
boundary. The exact cache-adoption API and worker ownership remain to be proven
with synthetic guards before production edits.

Rejected: timer-only deferral; extra `processEvents`; moving a QWidget or the live
QObject pipeline wholesale into an executor; general all-patient predecode;
unbounded per-click threads; a second decoder/global cache; the existing prefetch
helper as a foreground-completion API (it reads mutable current state and swallows
errors); and converting `switch_series` to fire-and-forget while leaving callers
unchanged. A preparation failure must be visible and must not trigger a hidden
synchronous GUI decode fallback. Superseded completion must not hide a newer
request's spinner or publish old pixels/annotations under new identity.

### Required implementation and acceptance order

1. Add fail-before synthetic guards for cold startup work on GUI, middle-frame
   equivalence, and exact display metadata. Inject controlled slow reads; no
   clinical fixtures, live DB, OS cache flush or antivirus changes.
2. Implement the smallest Fast-only preparation/adoption seam, with bounded
   admission and latest-request cancellation. Prove close/reopen, A->B->A,
   two-viewports, same-UID newer revision, error/retry and shutdown ownership.
   Cancellation discards publication; it must not forcibly stop native decode.
3. Run still/cine/mixed non-pixel, color/YBR/MONOCHROME1, per-instance W/L,
   enhanced geometry, same-number multi-study, progressive grow and tool-isolation
   guards. Preserve the middle initial frame and 2-object versus N-frame semantics.
4. Sync affected Fast plugin mirrors, verify parity and builder guards. No new
   dependencies, modules or flags without the repository packaging checklist.
   Use a narrowly scoped rollback of this slice, never a whole-file revert over
   the dirty worktree; any diagnostic legacy fallback is not a performance pass.
5. Fresh-source GUI: same local still/cine case, rapid switches, close during
   preparation, reopen, two viewports and progressive Server arrival. Verify
   actual rendered identity/count/pixels and session-scoped native logs.

KPI receipt must separate admission/queue wait, metadata preparation, pixel decode,
W/L resolution, GUI commit and first actual paint. Use the same study/series,
viewport layout, first-frame policy and comparable download/background load;
label process-cold, OS-cache state unknown, and warm runs honestly. Report sample
counts, stage p50/p95/max, UI heartbeat gaps, reads/decoded bytes, peak RSS and
active/pending work. Hard correctness gates: zero stale/wrong-identity publication,
zero GUI cold I/O/decode in the changed startup seam, and no unbounded queue growth.
Offloading may improve responsiveness without reducing total TTFF; warm TTFF and
memory must not regress unnoticed. Whole-session threshold-selected stall p95 is
not a substitute for this matched comparison. Numeric latency/memory budgets
must be set from that baseline, not invented from a different workload.

### Baseline verification for this review

Direct `.venv` pytest (`-p no:debugging -q --reruns 0`, Qt offscreen):

- Fast multiframe, dataset cache, cine, shutdown, study gate, MG placeholder,
  YBR, per-instance W/L, W/L memo, multiframe geometry and canonical sort:
  **136 passed, 1 existing quarantined xfailed, 7 warnings, exit 0**.
- Stale-load ownership, backend geometry boundaries, prefetch cancellation,
  overlay reentrancy, MPR-preserving switches and incremental series identity:
  **50 passed, 6 warnings, exit 0**.

Total: **186 passed, 1 xfailed**, not a new-fix fail-before/pass-after receipt.
The MG placeholder xfail remains a coverage gap, not a clean pass. Warnings were
SWIG deprecations and a synthetic YBR inconsistency warning. No runtime source,
live application state, patient files, decoder, Download Manager or configuration
was changed for this review; no new GUI lap, mirror synchronization or release
build was needed. The Local catalog delivery delay remains a separate OPT-60
slice; removing Fast initial-display blocking will not by itself remove that
whole-set metadata barrier.

## 2026-09-16 Catalog-first review and stable-handle prerequisite (OPT-60 / OPT-35)

### Fresh-source sampled acceptance: 11:52:59 launch

Explicit user-requested source launch, main PID 1188460, human sign-in. The
existing local test bridge responded to ping and action discovery. No runtime
code was changed during this lap. Clinical identifiers stayed in transient local
memory; independent SQL reads used SQLite `mode=ro`, not the application pool.

- `LOCAL-COLLISION-A`: initial candidate had four DB series but only one
  pixel-bearing projection (three objects); it was not used to claim a live
  multi-image-series collision pass.
- `LOCAL-CINE-B`: Local search/current-row selection and normal open produced two
  distinct Series UIDs with keys 1 and 900001. Existing MCP downstream switches
  rendered 25 still images in viewport 0 and 424 cine frames in viewport 1;
  Study/Series UIDs matched the selected metadata and the mapping stayed stable.
  Header-only independent disk validation counted two cine DICOM objects whose
  NumberOfFrames values totalled 424. The synthetic guard's 420-frame fixture is
  not a claim about this live case.
- Last-frame navigation reached indices 24 and 423 with the original UIDs retained.
  Local viewport captures succeeded; central-region pixel standard deviations
  were 35.82 and 33.55 (not blank). Captures remained local, uncommitted and were
  not uploaded. This is rendered-pixel evidence, not a clinical image-quality
  verdict. Both viewport indices were restored afterward.
- `LOCAL-MULTI-C`: two locally linked studies (same patient FK, not a name join)
  appeared with five series and the expected member Study UIDs. Primary and
  secondary-study series displayed in separate viewports, with exact Study and
  Series UIDs verified against read-only DB linkage. Counts were two and one;
  the tab's handle mapping remained unchanged.

**Scope:** sampled Local downstream GUI acceptance, not full native-input or
Unify acceptance. The MCP switches bypass mouse/OLE input. No native drag,
close/reopen, Server retrieval, injected late-series admission, network disconnect
or heavy cold-workload benchmark was performed. Late/subset collision behavior
still has the fail-before automated evidence, not a fabricated live event.

**Performance is NOT accepted:** session logs through 12:01:55 contain 35 unique
threshold-selected main-thread gaps, median 136.6 ms, nearest-rank p95 1773.5 ms,
maximum 4673.3 ms; two exceed one second. These include startup and MCP search
overhead (the existing adapter pumps events while waiting), so they are not a
matched before/after latency distribution. The long cine-switch interval at
11:58:26-30 has repeated GUI stacks in Fast Viewer bridge construction/scalar-range
and initial frame rendering -> `_decode_slice -> pydicom.dcmread/read_partial`.
This is a local GUI DICOM-read path, not evidence of server-response delay or
the display-key allocator blocking. Keep its investigation in the Fast execution
domain; do not change decoding or introduce a shared VTK cache as a shortcut.

No ERROR/CRITICAL entries were found in the four scoped application/DB/viewer/
download logs. The main session native file contained zero access-violation
mentions and one COM `0x8001010d` mention; the process continued responding.
This does not close historical native-crash, shutdown or installed-build gates.

### Evidence and decision

The 10:32 source session still spent about 25.36 seconds handing off the Local
series map for a 43-series / 2,486-file case. Two inventory consumers collectively
performed 2,486 probes and 2,486 cache hits: duplicate probe suppression worked,
but the initial whole-set readiness barrier remained. A separate file warmer read
637.5 MB in about 21.5 seconds concurrently. I/O contention is a hypothesis, not a
measured causal attribution. This workload differs from the earlier 31-series
sample; do not claim a matched improvement from 31.8 to 25.36 seconds.

Public-source review supports separating lightweight identity/preview metadata
from pixel retrieval, with targeted updates and bounded background preparation:

- [Orthanc metadata cache](https://orthanc.uclouvain.be/book/plugins/dicomweb.html):
  reusable metadata avoids reparsing all instances; DB-only subsets can omit
  display-critical facts. Old studies need explicit cache population.
- [OHIF DisplaySetService](https://docs.ohif.org/platform/services/data/DisplaySetService):
  identified display sets and targeted change/invalidation events; a display set
  is not universally equivalent to one DICOM series.
- [Weasis retrieval workflow](https://weasis.org/en/tutorials/index.print.html):
  series work can start before all discovery finishes; selection influences
  priority. Thumbnail availability must not become a global download barrier.
- [Cornerstone request pools](https://www.cornerstonejs.org/docs/concepts/cornerstone-core/requestpoolmanager/):
  separate retrieval/processing and interaction/thumbnail/prefetch priorities.

These are design references, not proof of commercial PACS internals or measured
AI-PACS performance. Do not import their frameworks, protocols or concurrency
defaults. Retain the current Download Manager/coordinator, thumbnail store,
SeriesRef authority and independent Fast/Advanced/VTK execution domains.

Selected direction: prepare the lightweight identity set, show trustworthy cached
previews without waiting for full pixel inventory, then apply identity/revision
scoped updates. Unknown counts must remain unknown, not zero or inferred cine
frame totals. Local stays network-independent. Preview availability is not
download completion or proof that pixels are renderable.

### Implemented prerequisite only: owner-stable display handles

The existing metadata sink allocated aliases independently for each incoming
subset. A later same-number series could receive an occupied alias, disappear in
single-study mode, or replace an earlier series during multi-study projection.
A subset without its persisted folder hint could fill another card's metadata.
Five actual-sink behavioral guards failed before production changes (exit 1).

`patient_study_set.allocate_series_display_keys` now accepts optional prior
study-local records. Existing UID pairs retain their owner-local handles; new
series cannot reuse an occupied handle, even when their raw SeriesNumber equals
an existing synthetic alias. Initial full-snapshot allocation remains unchanged.
The patient sink supplies its existing study buckets and reuses exact prior
folder/path hints only for a matching Study/Series UID pair. It refuses to merge
fields across different identities before grouped projection. The existing
primary-study fallback and multi-study offset projection remain authoritative.

Legacy UID-less repetition is deduplicated only for the same study-local handle
and exact folder/path; it never establishes a match to a known UID. A follow-up
guard caught duplicate legacy handles in the first implementation and passed
after correction. Prior conflicting handles fail before metadata maps mutate.
No disk access, new workers, Qt objects, timers, modules, dependencies or flags
were introduced. No decode, geometry, download scheduling, count precedence or
Ready/completion behavior changed. Source files are core files, not plugin mirrors.

### Verification and remaining rollout

- New guard: `tests/code/ui_services/test_series_metadata_incremental_identity.py`.
  Executes the production sink, allocator, projection and SeriesRef resolver with
  synthetic records and substituted scheduling/configuration only; no live DB.
- Initial eight cases: five failures / three passes before the correction.
- Expanded guard: 15 cases, including subsets, late collisions, reverse order,
  primary fallback, foreign-study isolation, owner isolation, legacy UID absence,
  cine object/frame counts, exact paths, idempotence and corrupt prior mappings.
- Focused suite: 181 passed; additional identity/progress/thumbnail suite: 107
  passed, both exit 0. Existing SWIG deprecation warnings remain.
- Existing `test_series_ref_stateful.py` property lane: one passed in 23.69 s,
  exit 0. Compilation and targeted `git diff --check` also passed. These checks
  do not establish a cold/warm GUI latency improvement or a repository-wide pass.
- Plugin mirror verifier: 465 pairs match, exit 0; neither changed core file has
  a mirrored payload to synchronize. No build/release or installed-app run.
- At the original code handoff, live bridge ping and action discovery succeeded. Running main PID 1183728,
  started at 10:32:21, predated this patch. Fresh-source GUI acceptance was PENDING;
  human restart/sign-in requested. Do not hot reload or count old-process actions
  as validation. Test Local and Server single/multi-study open, exact UID/path,
  counts, sidebar selection/drag, scroll and close/reopen with a surviving tab.
  The newer 11:52:59 receipt above supersedes this bootstrap blocker only; its
  explicitly untested workflows remain open.

This prerequisite is **not** the catalog-first cutover and does not claim reduced
Local latency. Before enabling incremental delivery, finish a GUI-owned,
generation-scoped receive/upsert contract: update the same card without rebuilding
its effects or stealing focus; reconcile explicitly verified count revisions
without replacing socket expectations with partial local counts. Then remove the
whole-inventory first-paint barrier, reuse validated summaries at existing
import/download-finalization seams, and backfill old data off-thread with explicit
invalidation. Preserve small atomic refresh versus large bounded card batches.
Compare matched cold/warm first-card, first-image, all-card and GUI-stall metrics;
measure file-warmer contention independently. Existing shutdown/crash gates stay open.

Rollback: revert only this dated allocator/sink change and its guards; preserve
all earlier dirty-worktree Unify/projection/inventory work. Do not reset the files
to HEAD. No schema, stored identity, DICOM or configuration rollback is needed.

## 2026-09-16 Local pixel inventory reuse follow-up (OPT-60 / OPT-58)

### Fresh-source result: previous routing fix was insufficient

The 09:53:57 source session was responsive to the documented test bridge. A Local
open created its tab in 535.5 ms, found 31 cached PNGs around 690 ms and completed
the initial cache listing in 49.71 ms (3.24 ms scan). The authoritative background
series map arrived at 31,802.7 ms, with the patient card-render entry immediately
afterward. The earlier completeness traversal was not observed in sampled stacks;
absence of a sample alone is not exhaustive proof. The earlier operand-order guard
still passes, but the reported end-to-end Local delay is **not closed**.

The two Local projections both call `inspect_series_pixel_inventory`, which opened
and read every DICOM header independently. Their historical purpose is valid:
preserve duplicate-number series and real cine frame counts, and exclude non-pixel
objects without deleting them. Home builds the study-aware series map; the patient
projection also handles missing PNG repair. Neither can safely be replaced with
the first cached PNG or an unverified DB count. A separate file-warmer also ran in
this session; its contention contribution is not measured and it is unchanged.

Read-only off-app profiling of the same 31-series inventory found 1,998 files and
1,998 frames. A profiled baseline pass took 4,820.6 ms: 4,446.1 ms was cumulative
`read_partial` time. This is a warm, profiler-influenced measurement, not attribution
of all 31.8 seconds in the live run. The two corresponding DB lookups were 6.12
and 2.31 ms in the log. Separately observed series switches rendered successfully
with 348.8/49.2 ms total handler times; no decoder change is justified by this delay.

### Correction and safety review

Only runtime file changed in this slice: `PacsClient/utils/dicom_displayability.py`.

- Keep the existing pixel-tag callback and NumberOfFrames semantics; request just
  that value through pydicom `specific_tags`, skipping unrelated defined-length
  values. Keep pydicom's undefined-length sequence and transfer-syntax handling.
- Share positive `(has_pixels, frames)` facts only inside Local inventory, using
  an absolute path plus per-file version check. Recheck before publication;
  fresh folder enumeration handles membership changes. Bounded 4,096-entry LRU,
  absolute 30-second TTL and 64 single-flight lock stripes. Global cache lock
  never covers I/O; callers remain on existing workers. No new executor or module.
- Do not cache negative/error results, which the legacy probe cannot distinguish.
  The public single-file Import/Fast probe remains uncached. Blank persisted paths
  no longer inspect the working directory. No patient lookup, UID/display alias,
  object-versus-frame count, download verdict, storage write or teardown change.
- Log aggregate inventory work and timing without paths/identifiers. Original
  per-card scans, worker delivery lifetime and other pending Unify gates are not
  claimed fixed. Same-version filesystem rewrites are bounded by the TTL, not
  detected cryptographically; this cache is never download-completion authority.

The new synthetic guard initially failed **6 cases / 13 passed**, exit 1, for
duplicate sequential/concurrent probes, excessive recounting, absent bounded
reuse, blank-path fallback and unnecessary header values. The final 24 guards
also cover version/add/delete/replace changes, mutation during a read, expiry,
access failure/recovery, path isolation, five transfer syntaxes, all three pixel
tag kinds, non-pixel objects, undefined-length sequences, log privacy and both
actual UI projection methods with isolated DB/PNG I/O, missing frame-count fallback,
nested-only pixel exclusion and independent-file progress during a blocked read.
No clinical DB was opened by these guards. A synthetic nested-pixel fixture initially
lacked an explicit VR; its setup was corrected before the final passing run.

Direct focused pytest (`QT_QPA_PLATFORM=offscreen`, `PYTHONPATH=.`,
`-p no:debugging --reruns 0 -q --tb=short`): **181 passed, 3 skipped**, exit 0.
Skipped cases require an unavailable clinical color fixture, not acceptance passes.
Suites: `test_local_pixel_inventory_reuse`, `test_local_offline_contract`,
`test_home_local_thumbnail_projection`, `test_fast_multiframe`,
`test_dicom_import_preview`, `test_series_number_collision`,
`test_patient_study_set`, `test_series_ref_authority`, `test_cine_playback`,
`test_dicom_color_decode` (paths indexed in `tests/INDEX_BY_GUARD.md`).

### Measured helper comparison, not GUI acceptance

The original helper was loaded from its unchanged-before-this-slice Git HEAD into
memory, not restored over the worktree. In one off-app process, two alternating
laps over the same files produced these unprofiled timings:

| Lap | Original | New, empty fact cache | New, reused facts |
|---|---:|---:|---:|
| 1 | 2,004.5 ms | 1,851.2 ms | 161.7 ms |
| 2 | 1,905.7 ms | 1,867.0 ms | 159.1 ms |

All 31 per-series object/pixel/frame count tuples matched on every pass. File/OS
caches were already warm and order was not randomized. This supports reduced
repeat work, not a cold-open speedup claim or a predicted GUI time. No pixel values
were decoded, exported or rewritten. Mirror verification: **465 pairs match**,
exit 0; the changed core helper has no payload mirror. Python compilation and
targeted `git diff --check` passed. No build/release acceptance is implied.

**Live gate remains OPEN:** the running source app predates this helper change.
After normal close and fresh source launch/sign-in, repeat the same Local open,
check `[LOCAL_PIXEL_INVENTORY]` work/wait counts and metadata-to-card timings, then
verify exact series identity, counts and selected pixels for ordinary, cine,
duplicate-number and multi-study cases. Check normal Server behavior separately.
Do not hot-reload, start a second instance or disconnect the clinical network.
Rollback is limited to this helper's fact reuse/selective-read changes; keep prior
UID, offline and metadata-route fixes. Retain the new explicit blank-path safety
check during rollback; do not reintroduce CWD traversal.

## 2026-09-16 Local metadata route follow-up (OPT-60 / OPT-58)

The sections below this follow-up are historical September 2 evidence, not current
acceptance status. In particular, current empty/manual-first viewer policy means
metadata handoff or render-entry markers do not prove first image paint.

### Observed boundary and cause

The September 16 source session, 01:48:25 to 01:59:00, eventually displayed Local
thumbnails; the symptom is delay, not permanent failure. Two larger Local opens
reached metadata handoff at approximately 24,856 and 35,908 ms. These are not final
thumbnail paint measurements or a workload-matched comparison with Server opens.
The session contained 117 threshold-selected F8 gaps, nearest-rank p95 1,242 ms,
maximum 7,022 ms. Repeated F11 samples within that largest continuous block showed:

`_load_and_display_series_info -> check_study_complete -> evaluate_sync ->
build_local_manifest -> _disk_series/_count_disk_instances/_pixelless_stub_count
-> pathlib.stat/is_file` on the GUI thread.

The route condition evaluated completeness before testing Local mode. Local
already selected the DB route regardless of that verdict, so this read-only
manifest traversal was unnecessary at this boundary. `evaluate_sync` does not
persist or download data; its incidental cache population is not the route contract.
This is a demonstrated local code/I/O stall, not a server-response explanation.
It does not account for all measured preparation latency.

### Minimal correction and regression boundaries

In `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py`, test
`SourceOfPatientLoad.DB` before `check_study_complete(study_uid)` in the existing
`or`. Keep `_server_grew` and every downstream branch unchanged. The metadata route
decision is preserved; no Study is newly declared downloaded/complete. Other
completeness callers, partial/unknown state, Server fetch/error behavior, Local
missing-row handling, UID identity, cine/frame counts, decode and download paths
are untouched. No new feature flag, cache, dependency, worker or callback is needed.
Changing the central manifest or adding another async route would have a wider
blast radius than removing this unnecessary call.

The new guard executes the actual AST condition using synthetic probes, rather
than pinning its spelling. It covers 16 source/completeness/growth combinations
plus inaccessible Local storage and unchanged Server error propagation. It is
deliberately a branch/evaluation-order test, not a full Home integration test.
Before correction: **5 failed / 13 passed**, exit 1. After correction, run directly
with `QT_QPA_PLATFORM=offscreen`, `PYTHONPATH=.`:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:debugging --reruns 0 tests/code/ui_services/test_local_series_info_gate.py tests/code/ui_services/test_local_offline_contract.py tests/code/ui_services/test_home_local_thumbnail_projection.py tests/code/ui_services/test_pipeline_thumbnail_preparation.py tests/code/ui_services/test_series_completeness.py tests/code/storage/test_sync_manifest.py -q --tb=short
```

**77 passed**, six SWIG deprecation warnings, exit 0. No clinical fixtures were
introduced. `tools/dev/verify_plugin_mirrors.py`: **465 pairs match**, exit 0;
this Home core file has no plugin payload edit. No build/release or full-suite claim.

### Remaining gate and rollback

The currently observed source process predates this edit. Fresh-source GUI
verification is **pending**: human launch/sign-in, documented control ping/actions,
repeat the same Local cases and a Server case, verify eventual thumbnail identity,
counts and selected-series pixels. Check absent gate traversal stacks and compare
cold/warm handoff and paint timings separately. Local source must not initiate a
remote fetch. Do not disconnect the clinical network for this test.

Per-card `_is_series_downloaded`, patient-open orphan pruning/audio listing and
background pixel-inventory preparation remain separate measured candidates; other
`check_study_complete` call sites remain unchanged. Do not claim all Local I/O is
off-GUI or the 25/36-second delay is eliminated. Original crash/exit gates also
remain open. Rollback is only restoration of the original operand order in this
condition; it restores the unwanted scan and requires reevaluating its guard.

## 2026-09-17 ordered Local inventory owner (OPT-58 / OPT-60)

### Why the previous correction was not sufficient

The 22:12 fresh-source run confirmed that shared pixel facts removed duplicate
positive header probes and kept Qt responsive, but did not remove the cold catalog
wait. Three unverified Local opens completed in 13.707, 6.950 and approximately
7.856 seconds. The independent file primer and sequential per-series consumer still
interleaved through the same single-flight locks. This was a producer/consumer
ownership defect, not card rendering, Server response or Viewer decoding.

The rejected alternatives were provisional cards from cached PNG presence and
parallel scan-ahead across series. The first can expose stale/non-pixel cards or
incorrect cine counts; the second can change progressive order and aliases or spend
I/O on a later series before the next visible card. Neither is acceptable in the
stable product phase.

### Correction and preserved contracts

`dicom_displayability.resolve_series_pixel_inventories` is now the one shared Local
catalog owner for Home and patient projections. It retains deterministic catalog
order and yields only a complete exact series result. For an unverified row, files
inside only the current series use one reusable bounded worker pool and a pending
window capped at twice the worker count, so a very large series is not eagerly queued.
Each worker owns its mutable timing/persistence accumulator; the catalog owner merges
results, writes
the optional cache and preserves directory-revision validation. Producer-indexed
rows continue to bypass header reads.

The patient-open warmer delegates known unverified Local directories to that owner
without enumerating or opening their files. Indexed Local rows and Server/unknown
fallback retain raw warming. `AIPACS_LOCAL_ORDERED_INVENTORY=0` restores the prior
fact-primer path; `AIPACS_LOCAL_PIXEL_FACT_WARM=0` remains its secondary rollback.
No provisional card, GUI cadence, Study/Series/folder identity, alias allocation,
multi-study grouping, non-pixel exclusion, object/cine count, download completeness,
thumbnail-byte cache, Fast/Advanced Viewer or VTK behavior changed. All file work
remains under existing non-GUI owners.

PHI-free acceptance markers are now explicit:

- `LOCAL_PIXEL_INVENTORY_BATCH`: requested/completed/indexed/scanned counts, bounded
  worker count, cancellation and total duration;
- `SERIES_FILE_WARM`: touched files/bytes/facts plus delegated series count.

### Verification and open live gate

The new regression guards failed before implementation with **4 failed / 44 passed**:
the ordered resolver and delegation plan did not exist. Final focused boundary:
**50 passed**. The real Home/patient/offline/owner projection boundary passes
**129**. The broader UI/storage selection records **1,295 passed, two skips and
three quarantined xfails**. Two unrelated existing source-spelling assertions remain
red (`test_login_carries_the_user_identity_ids` and
`test_status_flags_are_stashed_on_the_widget_to_avoid_recompute`); neither source nor
test is touched by this slice. Changed modules compile and `git diff --check` passes.

Fresh-source acceptance remains **OPEN**. Use previously unopened single- and
multi-study Local cases, then reopen the same cases. Verify exact final card identity,
order, object/frame counts, selected-series pixels, no overlap/jump, and no GUI
stall/error/native fault. Compare first-card and complete-catalog time against the
22:12 baseline and confirm the new batch/delegation markers. Include a Server open to
confirm its raw warm and download behavior are unchanged. Code gates alone do not
establish latency or crash closure.

Rollback only the plural catalog resolver consumption, its bounded file context and
the warmer delegation plan, or set `AIPACS_LOCAL_ORDERED_INVENTORY=0` for diagnosis.
Preserve the producer index, positive fact cache, orphan correction, Local stream,
identity allocator and unrelated dirty-worktree changes.

## Scope

This report reconciles the 2026-09-02 source-build performance logs, recovered Cloud
decision history, current code, focused tests, and the subsequent source-build live run. It
contains no patient identifiers or clinical payloads. It does not claim installed-build,
release, or clinical-workflow verification.

## Corrected evidence baseline

- 711 measured UI gaps exceeded 100 ms; median 169.2 ms, p95 562.1 ms, 11 above 1 s.
- Only four traces occurred during a drag interval and none recorded `drag_active=True`.
- Fast Viewer handler time remained healthy: median `total_ms` 32 ms, p95 70 ms. No Fast
  decode/render change was justified.
- `first_series_visible` is emitted again during rerender. Across 16 open requests there were
  31 markers; using every marker produced a false multi-second median. The first marker per
  session is the valid TTFF sample, approximately 528 ms median in the corrected analysis.
- The program connection explicitly uses `PRAGMA synchronous=NORMAL`. A raw diagnostic
  connection reported `2/FULL`; it did not represent application behavior.
- Today's four access violations belonged to AI-PACS-owned subprocess PIDs absent from the
  main `app.log` session list. Six `0x8001010d` events belonged to main sessions and were
  non-terminal. Whole-file historical totals are not current-day crash counts.

## Rev 3 live verification

The source-build run reduced the count of recorded gaps above 100 ms from 711 to 218. The
p95 moved from 562.1 ms to 706.4 ms, so the result must not be described as a uniform
percentile improvement: removing many small stalls changes the remaining distribution. The
defensible improvement is the lower event count and the absence, in the exercised paths, of
the eight named pre-fix stacks. Eagle Eye was not exercised, so absence of its probe stack is
not independent live proof.

Confirmed in the observed run:

- root theme application completed in 3.4 ms;
- the retired gRPC import, adapter discovery, synchronous voice write, patient-tab
  pixel-less-stub scan, and Zeta WAL first-touch stacks did not recur;
- three approved voice recordings were published successfully;
- the visit-status worker completed its observed write in 24.75 ms without blocking the Qt
  thread;
- six patient opens produced one valid first-visible marker per open, with median TTFF
  642.8 ms, p95 1089.1 ms, and maximum 1144.2 ms;
- Fast Viewer and drag-handler timings remained healthy enough to exclude them as the cause
  of the remaining multi-second stalls;
- no terminal main-process native crash or Windows hang was observed. One caught,
  non-terminal `0x8001010d` marker remained.

The status is **partially live-verified**, not complete.

## Root causes and corrections

### 1. Visit-status SQLite write

Evidence showed 2332.9 ms inside `set_visit_status` from the Qt main thread, accounting for
about 83% of the corresponding 2818 ms open interval. OPT-45 already gives the main process a
5000 ms busy timeout and download subprocesses 120000 ms. The delay was a WAL write-lock wait
inside that bounded ceiling, not a durability setting.

Correction:

- `visit_status` is created/migrated by `init_database`;
- the per-open writer no longer performs a nested schema check;
- the table colour updates immediately;
- persistence runs through one ordered worker, preserving `opened -> synced` order without
  multiplying SQLite writers.

The live run also exposed a separate, pre-existing persistence defect. `set_visit_status`
has always used `UPDATE studies ... WHERE study_uid = ?` and still returns
`cur.rowcount > 0`. A server-only study with no derived local `studies` row therefore returns
false. Before OPT-58 the UI still became orange and this failed persistence was silently lost
at restart; the asynchronous writer made that old failure observable. It is **not an OPT-58
regression**. `ensure_visit_status_column()` is confirmed absent from this hot path.

Do not repair this by fabricating a stub row in `studies`: that table is a derived disk index
that reconcile/resync may rewrite or remove. The future persistence boundary should be an
independent table such as
`study_visit_status(study_uid TEXT PRIMARY KEY, status TEXT, updated_at)`, with no foreign key
to `studies`, while preserving the rule that a stale `opened` write cannot overwrite `synced`.

Rollback: `AIPACS_VISIT_STATUS_ASYNC=0` restores synchronous persistence for diagnosis only.

### 2. Startup native gRPC import

Importing any `PacsClient.components.*` submodule executed package-level compatibility exports,
which loaded the retired gRPC downloader. One trace spent 3493.9 ms importing
`grpc._cython.cygrpc` on the UI thread.

Correction: compatibility exports use lazy module attributes. Public names remain available,
but importing a loading overlay no longer imports gRPC, Download Manager, Zeta, or the module
system.

### 3. Startup root stylesheet repolish

The completed control-panel tree received a root `QMainWindow` stylesheet after construction.
Measured sessions spent approximately 1.45-2.49 s in this repolish family.

Correction: the redundant post-build root stylesheet was removed. The same window background is
set with `QPalette`; child theme styles and theme-change behavior remain explicit and unchanged.

### 4. Enabled Agent Gateway address/TLS preparation

An enabled source configuration called `psutil.net_if_addrs()` while constructing the home panel;
one trace blocked the GUI for about 1443 ms.

Correction: the Qt command dispatcher is prepared on the UI thread, then adapter discovery, TLS
identity work, and transport binding run on a daemon startup thread. Default-off and shutdown
ownership are unchanged.

### 5. Patient-tab activation manifest scan

`on_tab_activated` synchronously called the authoritative completeness manifest. On a cache miss,
pixel-less-stub verification walked the series filesystem; a measured trace spent about 443 ms.

Correction: the complete, content-aware manifest decision runs on a worker. A generation token and
active-tab check discard late results. Pixel-less-stub detection, DB/disk authority, pipeline state,
and warmup gating remain unchanged.

### 6. Zeta manifest SQLite first touch

Every Zeta manifest connection executed `PRAGMA journal_mode=WAL`; construction and close traces
showed roughly 0.4-2.5 s in `_conn()` on the GUI thread.

Correction:

- schema/WAL first touch runs on a daemon worker;
- WAL is configured once rather than on every connection;
- reads before readiness degrade to an ordinary cache miss;
- background writes wait for bounded readiness;
- close does not queue a late clear, avoiding same-key close/reopen deletion races;
- slow schema initialization emits a PHI-safe timing marker.

### 7. Voice WAV flush

Stopping an inline recording called `sf.write` on the GUI thread. Native `sf_write_sync` produced a
410.4 ms trace.

Correction: queue draining still happens synchronously before stop completes, but WAV serialization
uses a daemon worker and a sibling temporary file followed by atomic replace. Explicit delete cancels
publication; non-user teardown does not delete an approved recording; Sync waits for publication.

### 8. Eagle Eye eager secondary tabs and series probe

`AiMainWindow` eagerly constructed Imaging Tools, Data Set, Model Training, and Reception Data.
Series probing also enumerated each folder twice and performed `pydicom.dcmread` on the GUI thread;
one measured probe gap was about 430 ms.

Correction:

- Imaging Tools remains the only eager active tab;
- the other three tabs retain stable positions but import/construct only when selected;
- DICOM candidate probing runs on a worker and uses a generation guard at teardown;
- the GUI thread supplies only an immutable identity/geometry snapshot; the worker never
  dereferences the live patient widget or receives VTK/private metadata;
- each series folder and its file list are enumerated once.

## Guard evidence

The new focused selection failed before production changes with 11 failures. It demonstrated the
blocking visit write, missing startup migration, eager gRPC import, root stylesheet, synchronous
gateway start, inline manifest scan, synchronous Zeta schema work, inline WAV write, eager Eagle Eye
tabs, inline Eagle Eye probe, and double series enumeration.

After the corrections and the final thread-boundary hardening:

- dedicated new guards: 13 passed (the original fail-before set contained 11 boundaries);
- voice/DB/theme/gateway/Eagle Eye adjacent boundary: 130 passed;
- Eagle Eye probe/training/dataset boundary: 176 passed;
- database plus visit-status boundary: 14 passed;
- current adjacent startup/gateway/database/Eagle Eye selection: 340 passed;
- all 462 packaged plugin mirror pairs match after syncing the Zeta payload;
- builder-focused checks: 17 passed, with one unrelated pre-existing failure because the
  existing staged `patient_table_sort.json` is stale;
- Python compilation of every changed runtime module: exit 0.

## Remaining gates

The live run found four remaining workstreams:

1. **Server-search row construction — fixed/offscreen verified, live pending:** after the server returned 51 rows, synchronous
   `count_subfolders_with_dicom` traversal on the GUI thread produced the largest remaining
   confirmed freeze. This is the third occurrence of the same design error already seen in
   `_pixelless_stub_count` and the Eagle Eye probe: answering a UI question by synchronously
   walking the filesystem. The 2026-08-22 work already replaced the expensive `rglob` scanner
   and moved later status refreshes behind `downloadStatusReady`; it did not cover the initial
   server-search row-construction call. Code review then proved its synthesized
   `download_status`/`is_downloaded` fields were unused: `add_patient_data` already paints an
   empty Status cell and resolves the authoritative disk flags through `statusFlagsReady`.
   Removing the redundant call was safer than adding another batch, cache, or invalidation path.
   Explicit Local/Import state is forwarded unchanged. The fail-before guard observed one probe;
   the corrected 51-row controlled replay observed zero. Live acceptance is a fresh Server Search
   with no `get_study_download_status/count_subfolders_with_dicom` UI stack and correct eventual
   DICOM chips.
2. **Server-only visit-status persistence:** use the independent table described above, not a
   fabricated `studies` row. This requires a fail-before guard and migration/reconcile tests.
3. **Definitive download completion:** the observed run included genuine no-response failures
   and preemption cancellations, but no authoritative completion marker. Download integrity
   therefore cannot be asserted from the log. Add the explicit completion marker before any
   further download-path optimization; it becomes the pass/fail probe for future soak runs.
4. **MPR/VTK:** retain this as a separate execution-domain workstream. Instrument construction
   and volume-build stages first, then optimize from measured evidence.

Additional live gates remain for Eagle Eye lazy-tab/probe behavior, direct Zeta
`_conn()`/`clear_tab` instrumentation, and startup `window.show`, icon, and font first-touch.
The revised order is: live-verify the Server Search fix, server-only visit persistence, download
completion marker, Eagle Eye live pass, MPR instrumentation, Zeta instrumentation, then remaining startup
first-touch work. Every behavioral change requires its own fail-before guard.

The installed executable and heavyweight release builder were not launched. The existing staged
build remains non-authoritative until its unrelated stale configuration is rebuilt from a clean
release candidate. OPT-58 did not change Download Manager, Fast Viewer, DICOM decode, server
protocol, or clinical geometry behavior. The download completion-marker requirement above is an
open follow-up, not an implemented change.


## 2026-09-16 tab-switch preview stuck at 8/104: investigation

User screenshot shows 8 ready out of 104 after dropping a second series and rapidly
switching between the patient tab and Download Manager. No patient identifiers or
screenshot are copied into repository artifacts.

Confirmed log sequence: 23:01:59.856-23:02:00.060 binds an eight-frame preview;
23:02:00.472 records 104 aligned source-file/metadata entries; 23:02:03.416 completes
filtering with slices=104 (one requested thread); 23:02:03.445 attaches download-wait
state. At 23:02:05.457 hot_cache returns n_instances=104 with dims=(320,210,8), and
23:02:05.480 post-bind still has eight pixel slices with 104 metadata records.
Thus full filtering completed, but the resumed display used an inconsistent cached
payload. This is not explained by filter duration or the count label alone.

Source mechanisms requiring a guarded reproduction: `_vc_load` returns False after
caching an item when `_tab_active` is false; `_vc_switch` treats False as not-resident
and enters download-wait. `_vc_cache._refresh_stored_metadata_instances` can extend
non-indexed preview metadata in place and republish it with unchanged vtk_image_data;
`_sync_viewer_metadata_instances` can also extend non-indexed viewer metadata. The
hot-cache validator checks current object identity, not pixel/metadata depth. These
paths explain how an eight-slice preview can survive with a larger metadata list,
but the exact mutator call and race ordering need a synthetic reproduction before
assigning the complete root cause or changing runtime behavior.

Ownership: shared tab activation/result handoff and metadata/invalidation contract
belong to Unify; decoded VTK payload integrity belongs to Advanced. Coordinate a
single reproduction with full result arriving while hidden, activation before/after
completion, cache promotion, replacement/cancellation, and completed download without
another signal. Preserve geometry ordering and per-frame pixel/SOP alignment. This
investigation made documentation-only changes; no runtime fix or live-pass claim.

Paired owner record: [VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md](VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md).

## 2026-09-17 completed-load tab handoff (OPT-35 / OPT-60)

**Status: code-verified; fresh-source GUI pending.** This supersedes the
investigation-only status above, not the separate cold-thumbnail or MPR latency gates.
The current source process (September 16, 23:40:15, main PID 739276) predates this fix;
documented control-client ping and action discovery succeed, but cannot accept it.

### Evidence and diagnosis

Independent PHI-safe extraction of the September 16 23:02 window confirmed:
104 metadata entries at 00.469, filtering finished with 104 slices at 03.416,
download wait at 03.445, then hot-cache 104 entries / dimensions (320,210,8) at
05.457. Full decode/filtering had finished, so this is not explained by missing
source files or server latency alone. The exact historical metadata mutator is
not uniquely identified by the logs; the defective transitions are reproduced below.
The separate screenshot's 8/224 position indicator alone is not proof of incompleteness.

Two cooperating defects were reproduced with synthetic data:

- Shared delivery returned False if a tab became hidden after decoding, bypassing
  normal identity normalization, GUI publication and load-event release. The caller
  interpreted False as not resident and attached download wait. A stale request after
  decode also leaked ownership. A separate same-series/positive-count no-op treated
  a visible preview as a completed load.
- Advanced decoded cache admitted inconsistent pixel/metadata pairs and permitted
  non-indexed preview metadata growth without replacement pixels. Its owner corrected
  this separately; see the [Advanced receipt](VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#opt-35-advanced-decoded-cache-integrity-2026-09-17-coordinated-fix).

### Shared correction and unchanged contracts

`_vc_load` now completes identity normalization and queues the complete pair even
when the tab is hidden. Existing full-candidate admission owns the no-op decision;
the redundant positive-visible-count shortcut is removed. Owned load events are
released on every post-decode exit without releasing another worker's event.
The GUI publishes the pair but does not render into a hidden tab. Missing targets,
stale tokens and a closed controller reject publication.

`_vc_switch` retains the original completion and cancellation token, at most one
per viewport, until activation. `_vc_cache.on_tab_activated` replays explicit
completions independently of automatic boost preference. Replay rechecks cancellation,
stable request identity and wrapper liveness; a hide before the queued tick preserves
the pending completion. Close clears callbacks and prevents new or late delivery.
New PHI-free `[VIEWER-HANDOFF]` markers distinguish defer and activation replay.

This is not a second loader, download retry, cache flush, or hidden rendering path.
No file, database, server protocol, decoder, filter, geometry or pixel ordering changes
were made by the shared slice. Fast progressive metadata growth is retained by the
Advanced owner's backend-specific admission; genuinely absent files still use the
existing download-wait path. Multi-study display keys retain their own canonical
study/series identity. Background-only hidden load admission remains unchanged.

### Verification and remaining gate

`test_inactive_load_result_handoff.py` executes actual method bodies with deterministic
worker/UI scheduling and synthetic payloads; it does not replicate the decision logic.
The first fixture attempt had missing mock state/BOM handling and is not reproduction
evidence. After correcting the harness, the initial 11 cases against the verified
clean pre-edit HEAD methods produced **10 failures / 1 pass, exit 1**, for the expected
behavioral reasons, without reverting or overwriting any worktree file. After the fix,
the final **25 cases pass, exit 0**, including composed worker -> GUI publication ->
activation for both backends, secondary-study identity, manual/automatic activation,
stale/cancelled/deleted targets, close, re-hide, missing files and resident no-decode reuse.
Adversarial cross-owner review found one additional case: a deferred replacement could
be mistaken for an already-present old full view of the same series. Its behavioral
guard failed before the follow-up; deferred completion now bypasses that duplicate-
presentation shortcut without changing the active-tab duplicate-suppression path.

Final combined adjacent selection: **214 passed / 6 existing quarantined xfailed,
exit 0** (six existing SWIG warnings). Release-parity plus additional identity guards:
**41 passed / 1 failed / 1 deselected, exit 1**. The failing stage-config parity guard
finds stale existing staged configuration; no build/config output was changed here.
This is an explicit release blocker, not a pass. All **467 plugin mirror pairs match**;
these shared controller sources have no payload mirrors. No unrelated payload sync.

Required fresh-source GUI lap: real drop of a large series, leave for Download Manager
during preview/full loading, return before and after completion, confirm full first/last
frame access, matching metadata/pixel depth and exact study/series without another drop
or download. Repeat in manual/automatic boost, a secondary study, Fast progressive mode,
superseding request, and close/reopen. Check session-scoped handoff, cache and native
logs. Until then do not claim live incident closure, performance improvement, clinical
geometry validation, full Unify completion or installed-build readiness.

Rollback only the September 17 shared hunks in `_vc_load`, `_vc_switch` and activation
in `_vc_cache`; retain other owners' changes. Reverting shared delivery can reintroduce
lost results; reverting Advanced integrity independently can reintroduce mismatched
cache acceptance. Treat the two receipts as a coordinated acceptance boundary.


## VTK-to-Unify handoff: mixed-series loading identity (2026-09-17)

Status: shared-owner correction required; no shared identity/download fix by VTK.
The user's screenshot shows a previously rendered series name while another series is
requested. A synthetic call to `_VCProgressiveMixin._resolve_series_identity` with current
viewer series A and requested series B (with B present in `_server_series_info`) returns
A's modality/number/description. The method at `_vc_progressive.py` reads current-viewer
metadata unconditionally and overwrites the requested number; populated old description
also prevents fallback to requested catalog info. This proves stale label selection, not
proof that the renderer actually rolled back its image.

Related seam: `_vc_switch.py::_finish_on_ui`, `if not ok`, coalesces download intent and
sets Connecting even when a resident series failed Advanced geometry/decode. Typed
resident-decode failure versus unavailable-source outcomes should be handled by the
existing shared load owner, with current request/token validation and truthful error UI.
Do not add a second coordinator or let stale callbacks hide/overwrite a newer request.

VTK now prepares the reported heterogeneous presentation series independently (45 frames,
nine RGB, 45 overlay graphics layers); it must remain outside the shared spatial-volume
cache. See VTK owner report's OPT-35 mixed MR/SC implementation. No clinical identifiers
or raw logs copied. Suggested shared guards: A visible + B requested label uses B;
B request overwritten by C ignores B failure; resident decode failure does not become
Connecting/download restart; missing-source load still follows existing download flow.
Source test-control endpoint unavailable at this check; live acceptance remains open.

## 2026-09-19 indexed-Local patient-open read amplification (OPT-58 / OPT-60)

**Code verified; fresh-source GUI/KPI acceptance pending.** The latest normal-source
session proved that the durable catalog path itself was fast for producer-indexed rows,
but the older patient-open warmer still read every file concurrently. One 39-series
two-study open read 2,398 files / 596.2 MB over 9.843 s; a four-series indexed open read
508 files / 133.2 MB over 5.397 s. Those reads were not required for catalog correctness
and overlapped first-card, thumbnail and first-image work.

Import and Download Manager already publish the correct reusable fact after complete
indexing: one revision-bound database summary per series with DICOM-object count,
pixel-object count and display-frame count. A bounded per-file disk fact cache remains
an accelerator for legacy cold scans, never the authoritative catalog. Unknown,
partial, restored or changed directories continue through the exact verifier and fail
closed. No second index or viewer cache was introduced.

Known Local series directories are now excluded from the patient-open raw warmer.
Unverified Local rows remain owned by the ordered inventory; producer-indexed rows reuse
the database summary. A failed Local catalog lookup remains Local and skips warming;
it cannot fall through to the Server/unknown raw route. Server/unknown opens retain the prior raw warm. The narrow field
rollback is `AIPACS_LOCAL_INDEXED_FILE_WARM=1`. No decoder, renderer, VTK, download
transport, card scheduling, identity, object/frame count or cache format changed.

The indexed-Local ownership, no-empty-thread and fail-closed Local-routing guards failed
before their corrections and pass after. The full warmer file passes 24 tests. The combined
Import/Download/database/Local projection/open selection passes 150 tests with one explicit
Windows symlink-privilege skip. Required
fresh-source acceptance: previously unopened and warm single/multi-study Local cases,
one Server control, exact cards/counts/order, no overlap or jump, no Local whole-series
warm bytes, first-card/full-catalog/first-image timing, and a normal session exit.

## 2026-09-19 patient-open identity and tab admission (OPT-35 / OPT-60)

**Fixed and code-verified; fresh-source acceptance pending.** A blank primary Study UID
was allowed past the plural owner-filtered resolver. The cached-thumbnail lookup then
treated the thumbnail root as the selected study, enumerated 2,635 unrelated study
directories and returned zero cards after 13.825 seconds. The canonical study-set module
now finalizes one non-empty `OpenStudyIdentity`, promoting the first resolved study for
blank Local rows and rejecting absent or owner-inconsistent results. The disk helper
independently rejects an empty UID. No new source, fallback, cache or index exists.

The same run exposed a separate Qt lifecycle defect at the four-tab limit: Home built a
patient widget and started asynchronous setup before the tab manager rejected it. A
modal warning then entered a nested event loop with orphan qasync work ready, causing
task re-entry errors and a 22.823-second failure. The existing `HomeTabService` now owns
capacity reservations before construction; registration commits and every failure aborts.
The final tab-manager check remains defensive. The warning is scheduled only after the
active coroutine returns.

Fail-before: 11 failed / 26 passed. Final focused: 41 passed. Adjacent boundaries: 159
passed / one documented GUI-tier skip and 142 passed / one Windows symlink skip. No
viewer decode/render/cache, download protocol, database schema, DICOM grouping, thumbnail
producer or package mirror changed. Live gate: restart the source application; open a
blank-primary Local case plus cached and multi-study controls, then fill four patient tabs
and attempt a fifth. Require exact identity/order/counts, prompt rejection with no new
widget/pipeline, no qasync re-entry, and normal exit.


## VTK-to-Unify follow-up: DOC memory rejection state (2026-09-20)

Latest source DOC attempt resolved the secondary series but hit Advanced preparation memory
rejection. Advanced owner corrected byte-RGB budget accounting (VTK domains report OPT-35
DOC whole-series follow-up). Separate shared-state observation: exhausted retry completion
logged LoadSucceeded with visible=0, and preparation error was described as awaiting download.
These events do not certify rendered output. Preserve this as a Unify failure-state follow-up;
Advanced changed no shared retry, hover, identity, download or controller code. No identifiers
or patient payloads retained here. Source real-drop acceptance remains pending after restart.


## VTK-to-Unify: idle neighboring-series cache observation request (2026-09-20)

Source: user request during large Advanced CT stack review, normal source session. No new
shared-cache defect is proven. Existing `_enqueue_lookahead_warmup` schedules two neighbors;
`_start_open_tab_warmup` and `_start_deferred_heavy_warmup` defer on interaction/interactive
loads and apply resource/admission limits. User asks whether unseen series can prepare while
idle. Requested owner check: trace candidate eligibility, cached/failed/oversize skips, retry
exhaustion and subsequent idle resumption, source revision and eviction on a large CT case.
Use current coordination services and immutable domain-specific results; no second timer or
prefetch coordinator, uncontrolled whole-study warmup, or flag change. Status: observation
request, not a diagnosed coordination bug. Viewer owner changed only geometry/header reuse
and large-stack drag; see VTK domains report OPT-35 large CT follow-up. Real UI/cache hit-rate
acceptance pending; test server unavailable, and normal launch policy preserved.


## 2026-09-20 late-study sidebar generation correction (OPT-58 / OPT-60)

### Evidence and diagnosis

The source session opened a multi-study tab from a stale two-study admission snapshot.
Fresh reconciliation found three studies and the existing open-tab back-fill delivered the
additional study and its one series about 1.6 seconds later. Nevertheless the bounded
sidebar finished with the original 15-series/two-study plan. The late study's DICOM file,
canonical thumbnail and complete disk count were already present, and its server metadata
request completed normally. This falsifies server, download, thumbnail-generation and
decode failure.

`set_server_series_info` rebuilt the current three-study projection, but
`_multistudy_thumbs_rendered` had been set when the earlier bounded task was merely accepted.
The grouped render therefore returned without superseding its immutable two-study snapshot.
An earlier arrival could also be lost at `_multistudy_prefetch_inflight`, because that guard
returned without remembering the newer target set. Download-complete decisions occurred
before Download Manager callback wiring, making per-generation disk readiness replay the
required source for the blue available border.

### Correction

- Compute one immutable ordered identity signature from study UID, stable display key,
  Series UID and storage key for every grouped generation.
- Return early only when the accepted/rendered signature equals the current signature.
  A changed topology reuses `start_sidebar_build`, whose existing token cancels stale
  delivery and reserves final geometry before paint.
- While one thumbnail-prefetch worker is active, retain only the newest different
  signature. Its GUI-thread completion schedules exactly one follow-up prefetch, then
  renders the newest complete projection.
- Keep unchanged metadata a no-op. Keep file/image/readiness preparation off GUI and let
  the existing disk-completeness snapshot rehydrate card-ready state after replacement.
- Emit only PHI-free study counts for queued-prefetch and generation-supersession traces.

No DICOM, download protocol, database, Viewer decoding/rendering, card implementation,
cache store, feature flag or packaged mirror changed.

### Guard and verification

`test_late_study_growth_supersedes_active_grouped_generation_and_rehydrates_ready` failed
before because the old and replacement tasks were identical. It now requires all three
study groups/cards, the exact total and ready state after supersession.
`test_late_study_growth_queues_one_followup_prefetch` failed before because completion of
the old worker scheduled no newer worker; it now proves one queued follow-up and one fetch
for the added study. Final focused selection across bounded/presentation sidebar,
open-tab back-fill, patient Study-set, multi-study projection and progress-state binding:
**125 passed, exit 0**. The expanded Local/Server thumbnail, identity, patient admission
and card-lifecycle boundary passed **259 tests, exit 0**. Source GUI verification remains
pending and must not be reported as passed until the affected multi-study workflow is
reopened successfully.
