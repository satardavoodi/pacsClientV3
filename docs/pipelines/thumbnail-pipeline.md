# Thumbnail Pipeline — As-Built Reference

## September 19 legacy-data acceptance clarification

The first exact scan of an old/restored series is a migration operation, not a second
steady-state thumbnail route. In the latest source session, two cold catalogs scanned
18 and 13 series and then persisted all 31 rows as revision-matched schema-1 verified
facts. Already indexed 24- and 15-series catalogs in that session resolved in tens of
milliseconds. Consumers must therefore keep this ownership model:

1. Import/Download publish exact facts for a newly owned complete generation.
2. Local Home/patient workers verify legacy data once and batch-backfill the same row.
3. A subsequent unchanged construction consumes only that revision-bound row.

Do not hide the first legacy scan with thumbnail presence, inferred database counts,
a startup whole-library scan or a parallel cache. A directory revision mismatch must
still fail closed to verification. Close/reopen of the two latest cases remains a live
gate because the available control surface could activate but not close/reconstruct a
patient tab; no GUI pass is inferred from that activation.

**Status:** Audited and corrected (2026-05-24; collision/cine contract updated 2026-08-30;
lifecycle correction recorded 2026-09-13).
**Scope:** Every place a series thumbnail is produced, cached, or rendered.

> This is a permanent reference + regression-guard. If you touch any thumbnail
> producer or consumer, read the **Regression guardrails** section first.
> Related: `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md` (multi-study viewer sidebar).

> **Execution order (2026-09-18):** this is an as-built pipeline reference, not a
> second roadmap. Shared thumbnail/catalog work follows the
> [U0-U5 ledger](../plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md#current-execution-ledger---2026-09-18).
> U0 live acceptance is currently open; do not add another producer, cache, provisional
> card path or timer while that gate is unresolved.

## Patient-open identity and admission boundary — 2026-09-19

Thumbnail/catalog work begins only after the existing patient-study resolver produces a
non-empty, owner-consistent `OpenStudyIdentity`. If the clicked row has no primary Study
UID, the first resolved study is promoted; an empty or inconsistent result is rejected
before path construction. `get_all_series_thumbnail_from_study_folder` also returns an
empty result immediately for an empty UID, so the thumbnail root can never be interpreted
as a study folder.

Tab capacity is reserved in `HomeTabService` before `PatientWidget` is constructed.
A rejected fifth tab therefore starts no thumbnail catalog, download or viewer work and
cannot leave callbacks behind a modal warning. This is an upstream identity/lifecycle
correction only: the producer-verified Local index, persistent pixel facts, ordered cold
scanner, worker-prepared QImage, bounded GUI card application, cache keys, series order
and Fast/Advanced execution-domain split below are unchanged.

## Producer-verified Local catalog facts — 2026-09-17

**Cold first-open reader ownership:** the 22:12 source run rejected the intermediate
fact-primer as the final design: full catalogs still took 6.950-13.707 seconds while
the primer and consumer interleaved. Exact Local inventory is now the single owner.
Both Local projections call the same ordered catalog resolver. It never scans a later
series before yielding the current series; only files inside that current unverified
series are inspected concurrently by one bounded reusable pool with at most twice the
worker count pending, rather than eagerly queuing the whole series. Producer-indexed rows
remain O(1). Exact membership, per-file versions, non-pixel exclusion, DICOM-object
count, cine-frame count, optional fact persistence and revision-checked DB backfill
remain unchanged.

The patient-open warmer skips all known Local directories instead of enumerating or
reading them. Unverified rows belong to the ordered inventory; producer-indexed rows
already have a revision-bound catalog summary and must not trigger a second whole-series
read. Server/unknown fallback retains raw warming.
`AIPACS_LOCAL_ORDERED_INVENTORY=0` restores the prior fact-primer behavior and
`AIPACS_LOCAL_PIXEL_FACT_WARM=0` can then restore raw warming for unverified rows.
`AIPACS_LOCAL_INDEXED_FILE_WARM=1` restores the former indexed-Local raw warm as a
field rollback. This is a worker-only
coordination change: no GUI scheduler, provisional card, identity allocator, thumbnail
byte cache, viewer decode/render or download-completeness contract changed. Code gates
pass; fresh normal-source single/multi-study latency and visual acceptance remain open.

**September 18 ordering correction:** Local study-open orphan reconciliation is
post-catalog maintenance, not catalog admission or thumbnail rendering. It no longer
runs on Qt and no longer gates the first card or grouped metadata publication.
Single-study Local first publishes through the patient inventory worker, then the same
worker reconciles. Grouped Local and Server first publish complete metadata, then their
existing patient-open background worker reconciles in `finally`. Exact pixel inventory
already rejects missing/non-pixel rows before publication. Healthy series validate one
known DB instance path, while stale/missing evidence retains full enumeration before
any destructive decision. Partial-study orphan removal, pending rows, whole-study
eviction and offline-root safety are unchanged. `LOCAL_ORPHAN_RECONCILE` reports only
owner, post-catalog phase, duration and counts for fresh-source acceptance.
Home emits one aggregate `source=producer_index owner=home_local` marker per study;
it contains only counts and makes the warm/restart acceptance gate measurable without
logging patient, study, series or filesystem identity.

Local presentation now has a strict catalog-first acceleration without weakening
the pixel verifier. Import and Download Manager already inspect the exact files they
publish; after complete instance indexing they stamp the existing series metadata
index with pixel-object count, display-frame count and the managed directory revision.
A completed legacy scan in either Local projection can backfill the independent
pixel summary through one shared batch writer without marking geometry metadata
Indexed. The scan directory revision is compared again at persistence time; a
concurrent add/remove/rename fails closed. Home and patient-sidebar projections accept
those immutable facts only for a complete, schema-matched, unchanged series under the
canonical study/folder tree. Card identity
still comes from Study UID, Series UID and exact `folder_key`; `display_key` remains
owner-local allocator output and is never persisted as storage identity.

Unknown, pre-existing, restored, external, partial or revision-mismatched data uses
the existing worker `inspect_series_pixel_inventory` path. A cached PNG or DB image
count alone is never sufficient. Non-pixel series remain preserved on disk but absent
from image cards; `image_count` remains pixel-bearing DICOM objects while
`display_image_count` includes cine frames. This is an extension of the DB-first
metadata index, not a replacement for download completeness, a new manifest, or a
shared Fast/Advanced decoded cache.

## Local incremental delivery — 2026-09-16

**September 17 Local image-preparation boundary:** the existing Local inventory
producer prepares store-first QImage using Study UID plus the persisted `folder_key`
before publishing through its two-message mailbox. The GUI drain creates QPixmap
and the existing card/placeholder only; it no longer reopens thumbnail bytes.
Identity, collision aliases, ordered-prefix delivery, object/frame counts, grouped
takeover, persistence, readiness and cancellation remain unchanged. This is the
same Local stream, not another renderer or a Viewer cache. Fresh source GUI/KPI is
pending; see the dated OPT-58/60 receipt in the UI-stall report.

**September 17 Home preparation boundary:** normal qasync Home renders prepare
QImage off GUI through `ThumbnailImageSourceService.prepare_home_image` and
`thumbnail_batch_runner.prepare_home_thumbnails`; explicit path then embedded-data
fallback remains distinct from the patient sidebar's store-first source policy.
Only GUI constructs QPixmap/cards. The existing generation and input guards own
publication; two ready images bound progressive preparation, and the existing
small immediate batch retains atomic same-identity refresh. Normal timer cadence,
study headers, counts and actions remain unchanged. No-qasync compatibility is
explicitly synchronous. See the dated Home image-preparation receipt in the
UI-stall report; code passes do not replace fresh-source GUI acceptance.

**September 19 hidden-owner correction:** visibility is now an admission boundary for
that same Home generation. When the main page is hidden by a patient or utility tab,
the right panel clears its generation-local visibility gate and stops its parented
progressive timer. The worker may finish the one read already admitted but starts no
next image read and publishes no hidden atomic batch. Returning Home sets the gate and
restarts the same timer/generation, retaining completed cards, exact action identity,
order, render signature and prepared QImage data. Replacement/clear/destruction still
cancel through the existing generation rules. Do not replace this with page-change
clearing, polling, a second executor or a second cache; those would lose Home state or
reintroduce parallel ownership.

**September 17 enumeration follow-up:** both Local projections keep the same
pixel-inventory service, now using directory-entry type filtering before Path
conversion. Fresh file-version checks, positive-only persistence and exact object/
frame counts stay unchanged. `cache_path_ms` and `cache_load_ms` split the prior
combined `cache_read_ms`. This reduces redundant per-candidate I/O; it does not
activate catalog-first rendering or bypass full grouped admission. See the
[code/live receipt](../reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-local-enumeration-cost-correction-opt-58--opt-60).

**September 17 ownership correction:** exactly-one-study Local opens now leave
inventory and metadata delivery to the existing patient stream. Home setup no
longer performs another full inventory or pushes its prior right-panel snapshot.
This supersedes the statement below that Home inventory always runs separately.
Grouped Local still uses full catalog aggregation; Home preview/explicit refresh
and separate viewer file warming remain. No identity, layout, pixel validation or
completion contract changed. Cold per-series admission is still a bottleneck;
the change is not the full catalog-first cutover. See the
[guarded ownership receipt](../reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-single-study-local-inventory-ownership-opt-58--opt-60).

**September 17 Local fact reuse:** the shared inventory service now keeps optional
positive facts across source-process restart in `data_paths.CACHE_DIR/local_pixel_facts`.
Never put these artifacts in thumbnail folders: legacy folder-presence consumers
could treat metadata as a PNG cache. Only managed study/series directories qualify;
no writes to external/import source media. Fresh enumeration and per-file stat
versions remain mandatory; only unchanged successful probes are persisted. Public
import/viewer probes remain uncached, and no layout, allocation or download authority
changes. See [the implementation and live gate](../reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-local-inventory-persistence-opt-58--opt-60).
The 23:40 source receipt verified bounded card application but found 6.570 / 27.004 s
Local metadata barriers. First uncached scans still require classification; this is
not full cold catalog-first acceptance.

**Later bounded-build correction:** normal qasync cached single-study and grouped
rendering now uses the existing batch/source services to prepare QImage/readiness
off GUI and apply one existing card per yield into fully reserved card/header rows.
Storage lookup uses study UID + persisted PNG stem, not an offset UI key. The
entry handler still returns the exact cached count. Current download state wins
over stale preparation; close/change/retirement rejects delivery. Explicit no-loop
and `AIPACS_SIDEBAR_BUILD_CHUNKED=0` retain prior behavior. This supersedes older
statements below that the normal grouped loop is entirely synchronous. Server
entries join the same owner after existing count merge/persistence; Local stream
and explicit compatibility image-I/O follow-ups remain. Code receipt and pending
fresh-source GUI: [bounded build](../reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-bounded-cached-sidebar-build-opt-58--opt-60).

**20:51 source follow-up:** user reports smoother card replacement. Four real-Qt
guards reproduce the remaining grouped-header jump: labels must be shown after
parenting while painting is suppressed, and the container must reserve wrapped height
at the fixed card-column width, not only generic minimum height or spare viewport width.
This correction has 432 focused passes / 467 mirrors; fresh source GUI is pending.
Late discovery of an additional study still uses grouped replacement and is a separate
topology gate. First Local grouped delay aligns with full metadata admission, not a
proven warm-up-only problem. [Current receipt](../reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-2051-source-review-and-study-header-geometry-correction).

**September 20 late-study generation correction:** grouped replacement now compares
the ordered Study/Series identity signature of the active sidebar generation. A late
study cannot disappear behind `_multistudy_thumbs_rendered`; a changed signature
supersedes the active bounded build through its existing cancellation token. If the
study set grows while thumbnail prefetch is active, one follow-up prefetch is queued
and only the newest complete snapshot is rendered. The replacement rebuilds each
card's ready state from the existing off-GUI disk-completeness snapshot, so a completed
series does not depend on an earlier Download Manager callback to regain its blue
available border. Unchanged metadata does not rebuild the sidebar. No new loader,
download path, GUI-thread file scan or viewer-domain coupling was added. Two new
fail-before real-Qt guards are part of `test_sidebar_bounded_build.py`; fresh-source
GUI verification remains required.

### Presentation acceptance contract (user decision, 2026-09-16)

Responsiveness is not accepted at the expense of stable presentation. This contract
applies to the next OPT-58/OPT-60 sidebar slice in both Local and grouped workflows:

- A card must have its final layout geometry before it becomes paintable. Preserve
  the existing paint-suppression / synchronous layout-activation ordering; do not
  replace it with `updateGeometry()` alone or `processEvents()` reentrancy.
- Already-visible cards must not overlap, jump, disappear or be rebuilt on an
  unchanged refresh. Preserve scroll position, selected/viewed state, progress-strip
  stacking, and the scoped root style applied before native children are created.
- Display order is deterministic and study-aware, including exact clinical-history
  priority, repeated/missing labels, collision aliases and previous-exam headers.
  An early subset followed by a final reorder is not yet a no-jump guarantee.
- Study headers are not series. The displayed series total must not temporarily
  count header/layout rows. Titles, descriptions and counts must not oscillate as
  competing producers deliver stale or less-authoritative metadata. Legitimate
  current-identity updates remain allowed; do not freeze incorrect information.
- Use exact Study/Series identity and existing stable handles. Keep DICOM-object
  completeness counts separate from cine frame counts. Cached PNG presence is
  neither clinical-data completeness nor permission to skip identity validation.
- File/cache reads and readiness preparation belong off GUI; card/QPixmap ownership
  remains GUI-local. A timer alone does not remove blocking I/O inside its callback.
  Reuse the existing projection, image-source service and card manager rather than
  adding a parallel sidebar implementation or crossing viewer execution domains.
- Cancellation, owner retirement, refresh supersession and close/reopen must reject
  stale delivery before touching Qt objects or a surviving tab. Retire callbacks and
  effects before releasing cards; never detach a visible card into a native window.

Require real-Qt guards for geometry at presentation, stable widget identity and
labels, header-excluded counts, state/scroll retention, stale delivery and native
destruction. Then require fresh-source native GUI observation during progressive
loading and close/reopen, alongside scoped logs. Code passes, terminal `done`, and
absence of exceptions do not certify visual stability or crash closure.

The September 16 presentation correction now commits card geometry before restoring
paint, excludes study headers from totals, rejects late single-study delivery after
grouped takeover, and preserves parent ownership during card retirement. Explicit
grouped failure retains the existing primary-study fallback; closing always rejects
delivery. Local completion no longer repositions cards. The grouped loop still
builds synchronously and GUI PNG/readiness I/O remains: these requirements are not
fully accepted. See the [correction and remaining gate](../reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-sidebar-presentation-boundary-correction-opt-58--opt-60).

**Large-number follow-up:** raw numbers >=1,000,000 must receive a study-local alias;
that range is reserved for grouped offset handles. The shared allocator preserves raw
numbers/paths and rejects invalid prior keys. Mixed catalogs publish only their stable
ordered ordinary prefix early; an earlier unresolved pixel-bearing alias holds later
cards back until complete-inventory allocation, avoiding a visible terminal reorder.
History-first groups needing that allocation hold early presentation back. Successful
startup is recorded beyond the inflight window, without disabling explicit refresh.
[Correction and live gate](../reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-large-number-identity-correction-and-startup-deduplication).

Single-study Local/Import startup now starts the existing Local inventory without
waiting for Home's whole-series metadata push. The worker may deliver each fully
pixel-verified unique canonical series; the existing GUI renderer admits at most one
card per timer tick from a two-message mailbox. Collision/legacy entries still finish
their catalog inventory before display-key allocation. Do not stream independently allocated
prefix aliases or turn catalog reservations into renderable/complete series.

Metadata reservations must agree with current owner keys. Close/destruction, changed
study, manager retirement or grouped takeover cancels delivery without a GUI join.
Verified Local rendering avoids a duplicate GUI directory/completeness scan; Server
and grouped rendering retain their existing contracts. Disk remains authoritative;
object/frame counts remain separate. This does not prove server download completion.
Existing PNG reads remain on GUI, and the full Home inventory still runs separately.

Guards: `test_sidebar_presentation_boundary.py`, `test_local_thumbnail_stream.py` and the Local startup branch in
`test_pipeline_thumbnail_preparation.py`. Code verification is not fresh-source live
acceptance. Traces distinguish stream elapsed time, per-card GUI apply time and terminal
outcome; none is a viewport TTFF metric. See the
[OPT-58/60 receipt](../reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-local-incremental-card-delivery-opt-58--opt-60).

## Lifecycle correction — 2026-09-13

**2026-09-16 stable-handle prerequisite:** metadata subsets must not allocate
viewer aliases independently of previously admitted series. The patient sink
passes its study-local buckets to `allocate_series_display_keys(existing_records=...)`.
Known Study/Series UID pairs retain owner-local keys and exact prior storage hints;
new arrivals cannot steal an alias. Do not pass offset projections or another
tab's handles. The unchanged grouped projection applies study offsets afterward.
Unknown UIDs do not match known UIDs. No pixel/count/readiness semantics changed.
This does NOT yet enable catalog-first/incremental rendering; card upsert, GUI
generation ownership and verified count revisions are the next prerequisites.
The 11:52:59 source run passed sampled MCP Local still/cine and two-study switches
with exact UIDs/counts, stable handles and nonblank cine last-frame capture. Actual
mouse drag, Server and late-admission live gates remain open. A 4.67-second Fast
GUI DICOM-read stall means performance acceptance is still open independently.
See the [dated evidence and rollout](../reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-catalog-first-review-and-stable-handle-prerequisite-opt-60--opt-35).

**2026-09-14 startup preparation:** normal qasync `_run_pipeline_safely` uses the existing executor
to prepare the canonical cache-file tuple, then supplies that tuple to the same startup routing
and early renderer. Count is exact, not temporarily zero; grouped Server's skip is preserved.
GUI layout is created once before waiting, never replaced by a late scan. Owned task tracking,
study/path validation, native validity and terminal retirement prevent late delivery. Fresh source
23:16 launch sampled grouped/Local open, pixels, scroll and Local close/reopen successfully;
scan times were 3.90/2.26 ms but delivery waits remained 358.88/319.21 ms. See the cost/stall audit
for the September 15 receipt and unverified cold/cine/identity/stress gates. The optional prepared argument leaves
direct refresh/Education/no-loop compatibility unchanged; their I/O remains a later explicit gate.

**2026-09-14 performance qualification:** the fresh sampled GUI receipt does not establish a
non-blocking pipeline. The [cost/stall audit](../reports/UNIFY_PATH_COST_AND_STALL_AUDIT_2026-09-14.md)
finds repeated GUI `show_exist_thumbnails -> get_image_files -> iterdir` samples during a
4.1-second stall, plus grouped availability `stat` and preview metadata I/O. Owned timers and
latest-value coalescing remain correct safety mechanisms, not background execution or proof of
bounded per-turn work. Existing single-study early display and progressive rendering have valid
purposes; move preparation through existing worker ownership before retiring their old seams.

**2026-09-14 card-effect follow-up:** the card's two reusable parented single-shot timers
preserve 450/2500 ms presentation intervals; its 400 ms progress animation is native-parented.
State transitions cancel superseded effects. Terminal cleanup stops timers/all direct-child
property animations, rejects late setters, and preserves native children/visible pixels until
owner deletion. Manager reset/dispose retires the card effects before clearing its map. Pending
or retry must remove an obsolete Ready label. No source-of-truth download, identity/count,
decoder or cross-viewer contract changes. Fourteen synthetic Qt guards; code/live results and
rollback are in the latest canonical OPT-60 receipt. The 20:41 source process predates this edit.

**2026-09-14 manager callback retirement:** `ThumbnailManager` owns delayed progress, border,
scroll-tail, priority-flash scheduling and overlay/auto-progress hides through parented
generation-scoped timers. `reset_all_states()` cancels pending work before reuse; `dispose()`
is terminal/idempotent and releases bound viewer callbacks, owned theme/image connections and
series/button state. Retained cards cannot dispatch after reset, mapping replacement or disposal.
Main/Advanced-panel managers retire independently before patient teardown. Home clear disposes
its weakly tracked render managers, including keep-widgets refresh, but leaves native card
deletion/paint replacement to the existing owner. Normal progressive completion retains ownership.
17 guards, including disposal after native destruction; 424 adjacent passes / 1 existing skip,
exit 0; 462 mirrors match. Fresh live blocked.
At that handoff card-owned effects were still open; the follow-up above addresses them.
Native-crash stress gates remain open. Read the older no-disposal review below as historical.

**2026-09-14 bounded paint-atomic refresh:** `display_thumbnails` may retain existing cards only
for a small non-progressive request with identical ordered known action identities. `clear_content`
still retires generations/timers/action ownership immediately; its internal `keep_widgets` option
defers only widget removal until the existing paint-disabled immediate build. Layout is activated
before repaint. Explicit clear, unknown/changed identity or membership/order, large sets and
progressive requests still remove old content immediately. Failed preparation clears pending
retained cards and permits retry. No cross-patient preview persistence or all-or-nothing card-error
recovery is claimed. 16 guards; 390 expanded passes / 1 skip, exit 0. Default-on; fresh live blocked.

**2026-09-14 Home render owner retirement:** clear now drops `_progressive_manager` after stopping
the progressive timer. The cache is render-scoped, not panel-scoped; normal timer completion keeps
current cards/actions alive. Existing card callbacks own their manager until deferred deletion.
The common Home action closure uses a weak panel reference, native-validity and render-token
guards before queue/delivery. Four fail-before cases, 10 final guards; 374 expanded passes /
1 existing skip, exit 0; 462 mirrors match. Fresh-source live pending. No eager native manager
deletion, generic state/timer reset, cadence, key/count or downloader change; full disposal remains open.

**2026-09-14 outward-signal lifetime:** patient tab creation now uses a tab-parented QObject relay
in `HomeTabService` for priority and Download Manager completion. It weakly references the owners,
keeps exact routing/primary-study filtering, rejects retired/closing targets, and disconnects its
own handles before explicit exit. Native destruction also disconnects for delete-without-close.
Six fail-before cases, 16 final guards; 364 adjacent passes / 1 existing GUI skip, exit 0.
17:57 fresh-source native open/close/reopen PASS: same Study/Series, visible pixels, no duplicate
tab, no interval error/deleted-object marker. Real completion/priority events remain live-unverified;
see OPT-60 for scoped logs, stalls and limitations. This addresses the capturing-callback retention edge;
it does not provide full generic ThumbnailManager disposal or change Home/Advanced rendering.

**Latest source-live receipt (2026-09-14, 16:35 launch):** sampled Server 13-card and Local
6-card preview retirement on empty results PASS. Server reselection plus native new/reused Home
series open retained exact Series UID / case-member Study UID, 8 slices and no duplicate tab.
The extended pin/advanced-overlap/Offline Cloud matrix remains code-only, not live acceptance.
See the OPT-60 master-plan/provenance receipt; this supersedes the fresh-launch prerequisite below.

**2026-09-14 search integration follow-up:** all five search-service table clears now use
`HomeSearchService._clear_search_results`. After the existing pinned-row-aware clear, preserve
the preview only for the same selected Patient/Study identity before/after and active preview.
Otherwise retire explicit selection, debounce/fetch/render state and call the panel's generation-
owning clear. Explicitly retired identity is not permissive initial state. Late producers cannot
repopulate an empty selection. A surviving pin's pending fetch follows its new row, not its old
index. Cancelled/superseded searches cannot perform the guarded clear; thumbnail completion
releases only its own task handle. No new I/O, cadence, decoder, count or download policy.
18 new guards and 302 adjacent passes, exit 0. Source-live pending a fresh launch; this supersedes
the caller-gap implementation status below, not the separate full manager-disposal work.

**2026-09-14 queued-render lifecycle update:** Home `clear_content()` now retires the render
generation as well as stopping its active timer. Deferred starts/input retries cannot repopulate
a cleared panel. Render single shots are Qt-context-bound; the progressive timer is a child of
the panel. Direct calls bind their generation before deferring. Cadence, large-set delegation,
input-sync guard, identity and counts are unchanged. Sixteen lifecycle guards; 197 adjacent
passes, exit 0. The 15:39 source sample passes replacement/open, but empty server search retains
the previous preview because the search caller clears only the table; old-card open is rejected.
This caller-side integration gap remains open. This corrects only the queued Home-render
subproblem below, not `ThumbnailManager` disposal or outward priority callback retention.

**Latest user contract, 2026-09-14:** Home image-button **double-click** opens/reuses the
normal patient tab and explicitly places the UID-matched series. Single click only selects
the preview. Name-based patient open keeps manual-only viewport placement. Cache producers
now share the worker-built `_build_cached_thumbnail_payload` projection, preserving both UIDs,
exact path/key hints and object/frame counts. Ambiguous legacy numeric cache matches are not
action identities. A tab-owned queued receiver waits for metadata/layout readiness; it cancels
on supersession/closure/tab change and expires without polling or number-based guessing.
Code gates pass; the user's two-study server-open live test is log-corroborated. A source restart
is still required to validate the later header correction and semantic refresh. This supersedes the
existing-tab-only click scope recorded immediately below. See the current provenance receipt
and `tests/code/ui_services/test_home_thumbnail_open.py`.

**Latest render contract:** coalescing and card creation share
`extract_series_info_from_thumbnail`. Normalized modality, description, object/display/pixel
counts, protocol, body part and group label participate alongside the path and immutable action
identity. Changed metadata at the same PNG path refreshes; alias-equivalent input does not
rebuild. No file stats, pixel reads or hashes are added. Same-path pixel revision/invalidation
and deferred small-set atomic replacement remain pending. Guards: 9 failures before correction,
68 focused passes afterward; see the provenance receipt for adjacent suites and live scope.

The following September 14 click-cutover and metadata-prerequisite paragraphs are historical
receipts; their pending semantic-refresh and no-auto-open statements are superseded above.

**2026-09-14 Home click cutover:** the two render schedules now share
`_create_action_thumbnail`. Its render-scoped manager maps card positions to a frozen
`SeriesActionIdentity`, defers the typed signal after input dispatch and rejects
retired-render callbacks. `HomeTabService` resolves both UIDs against a uniquely
matching open tab, revalidates after activation and hands off that tab's own key
to its normal viewer entry. No direct downloader or metadata/disk lookup is added.
The old Home click body is removed; automatic patient opening is not added.

The signature now includes the same immutable action value: identical PNG paths
cannot coalesce different known action identities. This narrowly advances an
identity-safety prerequisite; count/description/version-only visual refresh and
the pre-deferred-clear discrepancy remain pending. Numeric Home drag MIME and
retry/priority routes are NOT migrated. Generic patient-viewer key precedence,
backend isolation and manager disposal remain unchanged. Focused verification:
238 passed plus one stateful test; 462 mirrors match. Live/installed gates pending.
See `test_home_series_action.py` and the final provenance implementation record.

**2026-09-14 card metadata prerequisite:** both Home render schedules still use
`extract_series_info_from_thumbnail`, which now preserves supplied study/series UIDs,
original/display/storage keys, exact series path and display-frame count. The real-card
guard reproduces 2 objects / 420 frames being mislabeled as 2 images before the fix,
and verifies 420 afterward without altering object count. Focused suite: 205 passed.
This does not fix Home ordinals/signals, same-path semantic refresh, lifecycle or
download routing. See the provenance implementation record and
`tests/code/ui_services/test_right_panel_metadata_contract.py`.

**Source-run qualification:** the prior projection's multi-study route was observed
working, but two UID mismatches were blocked before matching renders. Keep identity
guards; full live acceptance is pending. Current `display_thumbnails` also clears
before the deferred rebuild, unlike the historical atomic-swap contract below.
Scheduling repair requires a separate fail-before guard, not a broad renderer merge.

**2026-09-14 identity implementation note:** the Local projection allocation prerequisite
is repaired, and patient-tab multi-study key/path construction now delegates to
`PacsClient.utils.series_identity.build_multistudy_series_projection`. The prior inline
algorithm and the stateful test's replica have been removed. The same 14 compatibility
cases passed before and after extraction; the final focused selection passes 171 tests
plus the stateful test. This changes ownership of the projection code, not the established
missing-number, collision-folder, UI-key or rendering rules. The following lifecycle and
right-panel action issues remain pending. See the September 14 implementation records in
`docs/plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md`.

The September 13 pre-fix source review corrected a misleading May/June reliability claim. `ThumbnailManager`
has no manager-level `cleanup()` or `dispose()`, but real-PySide6 probes showed that its
`ThemeManager.themeChanged` connection alone did not retain a standalone manager. An immediate
right-panel manager remained alive only while its cards and their callbacks remained alive, then
was collectible after card deletion. The disconnect inserted into
`CircularProgressborder.cleanup()` by commit `6617bca0` did not implement manager teardown.
September 14 real-Qt evidence also corrects the earlier absent-attribute rationale: the card
has `theme_manager` but no `_on_theme_changed`; the outer catch skipped its remaining cleanup.
No owner call was found in the audited paths. The current card cleanup is explicit retirement,
not a theme disconnect or native-widget detach/delete operation.

The confirmed strong-retention edge is the patient-tab priority signal connected to an external
lambda that closes over the patient widget/home owner; a matching Qt probe released the owner and
manager only after disconnect. Static delayed callbacks remain a bounded-retention and stale-work
risk. Until OPT-60 lands, treat this as **diagnosed, not fixed or guarded**. The correction must
disconnect confirmed outward callbacks, dispose managers from their owners, clear back-references
and pending state, and cancel or generation-gate delayed work. It must not change `series_uid`,
`folder_key`, digit-only `display_key`, thumbnail count/grouping, drag payloads, or any
Fast/Advanced/MPR execution-domain behavior. Full `gc.collect()` is not a substitute and must not
be moved to a worker where Qt/VTK finalizers could run.

### Right-panel action identity and render convergence

The main-page card ordinal is layout state, not series identity. A behavioral probe reproduced
`SeriesNumber=4` emitting `0` for drag, selection, and priority because the right panel passed
`thumbnail_index=0` and generic card construction intentionally gives that argument precedence.
Do not change that generic precedence: the patient viewer uses it for its digit-only
`display_key`. Correct the right-panel boundary with a self-describing immutable action identity
(`study_uid`, `series_uid`, raw `series_number`, `display_key`, and `folder_key`) and route server
priority through the existing Download Manager/series-intent coordinator. Local actions must
remain hard-offline.

The right-panel render signature currently includes only study UID, series number, and file path.
It was introduced to suppress duplicate fast-path/post-metadata rebuild flicker, so removing it
would regress UI stability. Extend it with cheap semantic identity, display-count, and payload
version fields rather than adding GUI-thread file stats, hashing, or disk walks.

---

## 1. Storage layers

A series thumbnail is a small PNG (a few KB). Three layers hold it:

| Layer | Where | Notes |
|-------|-------|-------|
| **Disk cache (canonical)** | `THUMBNAIL_PATH/<study_uid>/<folder_key>.png` | The single source of truth on disk. `folder_key == series_number` unless a study has duplicate numbers. |
| **In-memory cache** | `ThumbnailStore` singleton (`modules/storage/thumbnail_store.py`) | Thread-safe LRU, 300 entries / 50 MB, keyed `(study_uid, folder_key)`. On a miss it reads the canonical disk path and warms itself. |
| **DB hint column** | `series.thumbnail_path` (TEXT, nullable) | A convenience pointer; populated only by `save_image_as_png`. Treated as a *hint*, never the authority. |

### Canonical path — one definition, no aliases that diverge

* `data_paths.THUMBNAILS_DIR` = `USER_DATA_ROOT/patients/thumbnails`.
* `PacsClient.utils.config.THUMBNAIL_PATH` is an **aliased re-export** of
  `THUMBNAILS_DIR` — same `Path` object, not a copy. Both names are safe.
* `ThumbnailStore` resolves disk fallback against `config.THUMBNAIL_PATH`, so
  the in-memory store and every disk reader agree.
* **Do not** build a thumbnail path from `BASE_PATH` (`= PROJECT_ROOT`, the
  code root). `BASE_PATH/thumbnails` is the *legacy pre-migration* location and
  is empty after migration. This was the print-module bug fixed on 2026-05-24.

### Series-number collision rule (2026-08-30)

`SeriesNumber` is DICOM display/order metadata, not a unique series identity.
Two distinct `SeriesInstanceUID` values may share it. The shared
`resolve_series_folder_key` authority therefore defines the storage key:

* unique number: `<folder_key> == <series_number>` (legacy/common behavior);
* collision winner: bare number;
* other collision members: `<series_number>__<uid8>`.

Import, Download Manager, Local SQLite projection, viewer loading, and thumbnail
filenames must use the same key. For persisted Local data, `series.series_path`
is authoritative and `persisted_series_folder_key` returns its final component.
The raw `series_number` must remain unchanged for display and ordering. A
separate digit-only `display_key` is allocated for thumbnail maps and drag/drop;
the collision loser uses a deterministic reserved-band alias. `SeriesRef`
threads the raw number, exact `series_path`, and final `folder_key`/`storage_key`
independently so the viewport never reconstructs the wrong folder. See
`docs/reports/IMPORT_DUPLICATE_SERIES_NUMBER_IDENTITY_2026-08-30.md`.

The multi-study offset layer still requires digit-only UI handles. Apply the
existing offset to `display_key`; never inject a suffixed `folder_key` into that
arithmetic or into a drag payload.

### Pixel-bearing series gate (2026-08-30 follow-up)

**2026-09-16 performance follow-up (OPT-60 / OPT-58):** retain both UI
projections and their distinct responsibilities; share the expensive per-file
facts inside the existing `dicom_displayability` authority. Home supplies the
study-aware metadata map; the patient projection also repairs missing PNGs and
allocates its card entries. Neither may bypass pixel classification or project
PNG filenames directly as drag handles. Positive file facts are now coalesced
across concurrent workers and reused for at most 30 seconds in a 4,096-entry LRU.
Each access checks normalized absolute path, device/inode, size and nanosecond
mtime/ctime; publication checks the version again after the read. Enumeration
remains fresh, so added/removed/replaced files are not inferred from a directory
mtime. Non-pixel/failure results are not cached. Blank paths return no inventory,
never the working directory. This remains a UI metadata hint, not authoritative
download completion, and does not replace existing UI retirement/identity guards.
The September 17 layer extends reuse across process restart for managed files:
root/file path hashes, version, frames and original verification time only; schema,
checksum and type validation, 24-hour age (not renewed by hits), atomic worker writes.
Artifacts are capped at 8192 records / 1 MiB, with 256 published entries / 16 MiB
budget. Corruption, expiry, eviction, permission or busy-writer failure simply falls
back; no clinical DB, raw DICOM, decoder or thumbnail-directory mutation. A cold or
oversized uncached series still uses the existing probe, never unverified DB counts.

The header reader requests only NumberOfFrames while retaining the existing
pixel-tag stop callback. Defined-length unused values are skipped; undefined-length
sequences and deflated-transfer-syntax handling remain pydicom's responsibility.
No byte-level parser, pixel decode or codec change. The public single-file probe
remains uncached for Import/Fast callers. Only the two existing background Local
inventory consumers use reuse; no file I/O is moved onto Qt. Bounded stripe locks
coalesce file probes without holding the global cache lock during I/O.

`[LOCAL_PIXEL_INVENTORY]` records aggregate file/probe/cache-hit counts and wait/total
milliseconds, without paths or patient/Study/Series identifiers. A filesystem write
that deliberately preserves all version fields can remain cached until TTL expiry
(up to the persisted verification age plus the short memory lifetime);
these UI hints must never certify storage completeness. Validation: 24 new guards;
181 focused passes, three unavailable clinical-fixture skips. Fresh-source GUI and
cold-storage timing remain pending; see the September 16 follow-up in
`docs/reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md`.

A readable DICOM object is not necessarily an image. SR, presentation state,
and vendor metadata objects may have a study/series identity but no Pixel Data.
Import therefore keeps object, pixel-bearing-object, and frame counts. Local image-viewer projections verify
the persisted folder through `inspect_series_pixel_inventory` on the existing
background path, omit metadata-only series from thumbnail/viewer cards, and use
total frames as the card's display count for cine while retaining object count
for file completeness.

The inspection reads each object only up to the pixel element header and never
reads or decodes its value. This permits an exact sum of `NumberOfFrames` without
materializing a large cine payload. Both current callers already execute on
background paths, so the complete header inventory cannot block the Qt thread.
Metadata-only objects remain on disk and in SQLite for future dedicated
document/SR consumers. Never replace this gate with a modality-name allowlist:
displayability is determined by the pixel payload contract, not by `Modality`.

---

## 2. Producers (who writes thumbnails)

| Producer | Writes PNG to disk | Writes `ThumbnailStore` | Updates DB column |
|----------|:---:|:---:|:---:|
| Download manager — `executor._save_thumbnails` | ✅ | ✅ (write-through) | ❌ |
| Socket fetch — `save_thumbnail_with_bytes` (`patient_tab/utils/utils.py`) | ✅ | ❌ | ❌ |
| Viewer VTK→PNG — `save_image_as_png` (`utils.py`) | ✅ | ❌ | ✅ |

All three write the **canonical disk path**, so every disk reader and the
`ThumbnailStore` disk-fallback see them. The DB column and the in-memory store
are populated inconsistently — this is acceptable because **every consumer
treats disk as the authority** and the store/column as accelerators only.

---

## 3. Consumers (who renders thumbnails)

| Consumer | Code | Image source |
|----------|------|--------------|
| Main patient-list right panel | `right_panel_widget.py` `_build_pixmap_from_thumb` | Canonical PNG file → base64 fallback. |
| Opened patient viewer-tab sidebar | `_pw_panels.py` `add_thumbnail_to_thumbnail_layout` | **`ThumbnailImageSourceService`** → `ThumbnailStore` → canonical PNG fallback. |
| Tab-title icon (small image by the tab title) | patient tab widget | Canonical PNG file (first series). |
| Print module series list | `printing/ui/printing_widget.py` `_build_series_thumbnail_pixmap` | DB hint → **`ThumbnailStore`** (memory + canonical disk) → DICOM-decode fallback → placeholder. |

`ThumbnailImageSourceService` (`patient_tab/utils/thumbnail_image_source_service.py`)
is the shared read helper: `ThumbnailStore.get_bytes()` first, then
`QPixmap(file_path)`. The file-path fallback is always the correct per-series
path, so a store miss (e.g. a multi-study non-primary series whose store key
cannot match the widget's primary `study_uid`) degrades cleanly to a direct
disk read — never to a blank thumbnail.

---

## 4. Changes applied 2026-05-24 (thumbnail audit)

1. **Print module — unified source + correct directory.**
   `_build_series_thumbnail_pixmap` Tier 1.5 used
   `Path(BASE_PATH)/"thumbnails"/...`, the legacy code-root location, which
   almost always missed and forced the slow Tier-2 full-DICOM decode on the UI
   thread. It now resolves through `ThumbnailStore` (memory + canonical disk)
   and keys on the series' own `study_uid` for multi-study correctness.

2. **Viewer-tab sidebar — routed through the unified source.**
   `_pw_panels.add_thumbnail_to_thumbnail_layout` did `QPixmap(file_path)`
   directly. It now calls `ThumbnailImageSourceService.load_pixmap()`, so the
   sidebar shares the in-memory `ThumbnailStore` populated by the download
   write-through. The service's file fallback guarantees no regression.

3. **Multi-study flicker + ordering** (same day, first pass) — see
   `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md` §"Follow-up fixes".

4. **Viewer-tab sidebar latency — faster deferred-retry poll.**
   On a cache miss while a heavy download is active,
   `_load_server_thumbnails_async` defers the sidebar thumbnail load
   (`should_defer_noncritical_open_network`) and polls the local cache via
   `_schedule_deferred_server_thumbnail_retry`. The poll interval was a flat
   **700 ms**, so the sidebar lagged the main page by up to 700 ms even
   though the download warms the (tiny) thumbnail cache within a few hundred
   ms. The retry is now **150 ms for the first 8 ticks** (≈1.2 s of dense
   polling) then 700 ms for the slow-download tail — same ~8 s total budget,
   but the common case renders ~150–300 ms after the cache is ready. Each
   tick is only a cheap on-disk check; the heavy-download throttle policy
   itself is unchanged.

---

## 5. KPI summary

* **Loading speed** — Cached PNGs are a few KB; disk reads are sub-millisecond.
  Viewer sidebar and print also hit the in-memory store. Print's slow
  DICOM-decode path is now a rare last resort.
* **Stability** — `ThumbnailStore` is fully thread-safe; multi-study rendering
  is gated; renders are repaint-suppressed.
* **UI smoothness** — Multi-study previews render immediately (no progressive
  flicker); grouped sidebar is numerically ordered.
* **Cache behavior** — One canonical disk dir; in-memory LRU bounded by entries
  and bytes; disk-fallback warms the store automatically.
* **Database usage** — `series.thumbnail_path` is a hint only; consumers never
  depend on it being populated.
* **Disk usage** — Single dir, small files; cleanup managers exist
  (`modules/storage/*cleanup*`).
* **Repeated access** — Sidebar/print served from memory after first read.
* **Multi-study** — Offset-key sidebar (see multi-study doc); print and tab
  icon resolve per-study paths.

---

## 6. Regression guardrails — read before touching this area

1. **Disk is the authority.** Every consumer must resolve to
   `THUMBNAIL_PATH/<study_uid>/<folder_key>.png`. The DB column and
   `ThumbnailStore` are accelerators — never the sole source.
2. **Never use `BASE_PATH` for thumbnails.** `BASE_PATH` is the code root.
   Thumbnails live under `USER_DATA_ROOT` (`THUMBNAIL_PATH` / `THUMBNAILS_DIR`).
3. **Read through `ThumbnailImageSourceService`** where practical — it keeps the
   memory-first / disk-fallback policy in one place.
4. **`make_pixmap_from_bytes` is main-thread only.** Call it on the Qt main
   thread (QPixmap construction is not thread-safe).
5. **A store miss must fall back to the file path**, which is the correct
   per-series path — especially for multi-study non-primary series whose store
   key cannot match the widget's primary `study_uid`.
6. **Do not make a consumer depend on the DB `thumbnail_path` column** being
   populated — only `save_image_as_png` writes it.
7. **Never key a series solely by raw `SeriesNumber`.** Use `SeriesInstanceUID`
   for clinical identity, canonical/persisted `folder_key` for disk/PNG identity,
   and digit-only `display_key` for viewer maps, cards, and drag/drop.
8. **Never equate a DICOM object count with an image count.** Before creating a
   Local image-viewer card, require a pixel-bearing series. Persist count updates
   by `SeriesInstanceUID` so duplicate raw numbers remain isolated.
9. **Never infer colour or frame structure from incomplete DB metadata.** The
   DICOM dataset is authoritative for `SamplesPerPixel`, photometric state, and
   `NumberOfFrames`; preserve separate colour and multi-frame branches. Do not
   admit an instance to metadata-driven subprocess prefetch until its own pixel
   facts are authoritative.
10. **Never render a Local cache filename stem as a card or drag handle.** A
    collision stem such as `1_2` is a storage key, not a display identity. Wait
    for the SQLite/disk Local projection to provide the digit-only `display_key`
    and its exact storage path together. Drop parsers must validate decimal
    digits before `int()`; Python otherwise accepts numeric separators and would
    reinterpret `1_2` as Series 12.
11. **Style the thumbnail card root before constructing its native subtree.**
    `ThumbnailManager.create_thumbnail_widget` must use the scoped
    `QWidget#seriesThumbnailCard` selector before adding layouts, children,
    graphics effects, or the strip event filter. A late unscoped `QWidget`
    stylesheet recursively repolishes the complete subtree and was the exact
    main-thread site of the 2026-09-01 Windows `0xc0000374` termination during a
    multi-study grouped render. Guard:
    `test_thumbnail_card_root_style_is_scoped_and_applied_before_child_tree`.

**Live result (2026-08-30):** The source-build Local/Fast workflow was confirmed
by the human operator: the original 25-image still series retained its correct
card count and displayed normally while the duplicate-number cine series also
rendered. The broader re-import, explicit cable-disconnect, packaged-runtime,
and multi-study comparison gates remain independent.

**Native-stability follow-up (2026-09-01):** The PHI-safe crash analysis and
source-spawn correction are recorded in
`docs/reports/THUMBNAIL_HEAP_CRASH_AND_WINDOWS_SPAWN_FLASH_2026-09-01.md`.

## 7. Known non-blocking follow-ups

* The main-page right panel (`right_panel_widget._build_pixmap_from_thumb`)
  still reads the canonical PNG directly rather than via `ThumbnailStore`.
  Correct and fast (tiny files); could be unified later for symmetry.
* `ThumbnailPanel` (`patient_tab/ui/patient_ui/thumbnail_panel.py`) is a legacy
  class that is never instantiated — the live sidebar is built inline in
  `_pw_panels.py`. Left in place (removing it has no functional benefit and
  carries risk); do not wire new code to it.
* The print module's Tier-2 DICOM-decode fallback still runs on the UI thread.
  It is now rarely reached; moving it to a worker is optional polish.

---

## 8. Right-panel refresh / server-grew gate (2026-06-01 → 2026-06-02)

The main-page right-panel thumbnails for a clicked patient are rendered by
**`show_patient_studies` in `_hp_search.py`** (~:1230). It is a *fast-cache-first*
path: it builds a payload from the local disk cache
(`_build_cached_thumbnail_payload` → canonical PNGs) and displays it **without a
server call** whenever possible. A server thumbnail fetch
(`get_study_thumbnails(include_base64=True)`, which pulls every series and warms the
disk cache) only runs when the cache is judged stale/incomplete.

The staleness decision is the **server-grew gate** (~:1240–1266). Because the local
completeness checks are all local-only (`check_study_complete` makes no server call),
a study that gained series on the server would otherwise pin its stale partial cache
forever. The gate compares a **server series count** against the **local thumbnail
count** and, when the server has more, skips the cache once and falls through to the
server fetch.

Inputs to the gate:

* **`self._server_series_count_by_study[study_uid] = count_of_series`** — the server's
  series count, stashed as the patient list loads (`_add_socket_patient_to_table`,
  `_hp_search.py`) and on single-click reconcile (`_reconcile_patient_studies_on_click`,
  `_hp_series.py`), so it is ready before the gate runs.
* **`_local_thumbs`** — `len(_build_cached_thumbnail_payload(...).thumbnails)`.
* **`self._thumbs_server_refreshed_uids`** — a per-session set that records studies
  already refreshed, so the gate refreshes **once** rather than looping on a benign
  `count_of_series`-vs-fetchable-thumbnails off-by-one.

Diagnostic traces (in `download_diagnostics.log`): `right_panel_cache_gate`
(`local_thumbs` / `server_series` / `grew`), `right_panel_cache_hit`
(`thumbnail_count`), `right_panel_socket_start` / `right_panel_socket_done`.

### History — read before changing the gate
1. **44113 (2026-06-01):** introduced the stash + gate so a study that grew on the
   server (1→9 series) re-fetches on single-click. See
   `docs/reports/ROOTCAUSE_44113_SINGLE_CLICK_PIPELINE_2026-06-01.md`.
2. **44323 / 44534 (2026-06-02):** two gate defects found via live DB/disk/log ground
   truth (44323 MRI 20 series/20 PNGs = complete; 44534 DX 3/3 = complete):
   - **B1 — patient-aggregate count mis-attributed to one study.** `count_of_series`
     is the *patient* series total. The stash fired on `len(study_uids)==1`, but a
     **multi-study** patient still returns only the latest UID (so that is true), and
     then `count_of_series` aggregates all the patient's studies (44534 DX got
     `server_series=10` = DX 3 + MRI 7; DX really has 3) → a false "grew". **Fixed:**
     stash only when `total_studies <= 1`.
   - **B2 — "refresh once" never recovered on a later server growth.**
     `_thumbs_server_refreshed_uids` was keyed by **UID only**, so after the first
     refresh a genuine later growth was never re-fetched on re-click — the stale
     partial cache was pinned. **Fixed:** key the marker by the server series **count**
     (`f"{uid}@{server_series}"`). An unchanged count still hits the fast cache (same
     key → skip, so the benign off-by-one does not loop); a changed count gets a fresh
     key → exactly one re-fetch. See `docs/reports/MULTI_STUDY_MULTIMODALITY_44534_2026-06-02.md`.

Note the *missing MRI study* on 44534 is **not** a thumbnail bug — it is study
discovery: the server's `GetPatientList` returns only the latest study UID per patient,
so the MRI study is enumerated per-modality elsewhere (see the multi-study completeness
guard in `CLAUDE.md` and `docs/reports/MULTI_STUDY_MULTIMODALITY_44534_2026-06-02.md`). The gate only
governs thumbnails *within* a study that is already known.

### Refresh-gate guardrails (read before touching the gate)
1. **`count_of_series` is patient-level, not study-level.** Only attribute it to a
   single study when `total_studies <= 1`. For multi-study patients use the per-study
   series count, never the patient aggregate.
2. **Keep the refresh marker keyed by the server count** (`uid@count`), not the bare
   UID — that is what lets a genuine server growth re-fetch while an unchanged study
   stays on the fast cache and a benign count/thumbnail off-by-one does not loop.
3. **The fast cache must stay the default.** Only fall through to the server fetch when
   the gate says the study grew; do not make every click hit the network (that is the
   responsiveness regression 44113's design avoided).
4. **Disk remains the authority** (§6). The gate decides *whether to fetch*; it never
   changes where thumbnails are read from.
5. **Re-validate with the traces.** A correct gate logs `grew=1` exactly once per
   server-count value, then `grew=0` + `right_panel_cache_hit` on subsequent clicks.
   Persistent `grew=0` while `server_series > local_thumbs` across *different* counts
   is the bug class B1/B2 fixed.

## 9. Right-panel render smoothness (2026-06-02)

Two render-layer fixes make the main-page right panel load calmly and consistently.

**(a) Skip-identical coalescing (anti-flicker).** A single click triggers the right
panel twice (fast open path ~450 ms + post series-info ~1.2 s). `display_thumbnails`
(`right_panel_widget.py`) always `clear_content()`s then rebuilds, so two identical calls
clear+rebuilt the same set ~0.8 s apart = a flicker/reload. Fix: `display_thumbnails`
computes a visual signature (`_thumbnail_render_signature` = ordered
`(study_uid, series_number, file_path)` per thumb) and returns early when it equals
`self._last_render_signature` (already shown/rendering). Reset in `clear_content()`;
`None` at init. A new series, different patient, or changed path changes the current
signature, but a same-path count/identity update may not; that residual is recorded below.

**(b) `progressive=False` request on every main-page producer, with a large-set safety
override.** `progressive=True` → `display_thumbnails_progressively` paces card creation on
a 120 ms timer. `progressive=False` → `display_thumbnails_immediately` normally builds a
small set under `content_widget.setUpdatesEnabled(False)`→`(True)`, so the set paints once.
All main-page producers request `progressive=False` for consistent UX. However, since commit
`fddeaa83`, the component deliberately redirects a set larger than `_THUMB_IMMEDIATE_MAX`
(default 16) back to progressive construction; this fixed a measured ~23 s GUI freeze. The
two cadence implementations are complementary, not legacy alternatives.

Guardrails:
- Keep `display_thumbnails` **idempotent for semantically identical content** (do not remove
  the short-circuit or unconditionally rebuild). Extend the signature with stable identity,
  count, and payload-version fields; do not add volatile timestamps or filesystem probes.
- Main-page producers should continue requesting `progressive=False`; do not bypass the
  component's large-set redirect or force a large set into one synchronous Qt loop.
- Do not remove the progressive implementation. It is the bounded-work safety path for a
  large home-page set, even though small-set producers request the immediate presentation.

### Render coalescing — anti-flicker (2026-06-02)

A single patient click legitimately triggers the right panel **twice**: once on the
fast open path (`plus_entry → right_panel_begin`, ~450 ms) and again after series-info
loads (`series_info_entry → right_panel_begin`, ~1.2 s). Each call to
`RightPanelWidget.display_thumbnails` does `clear_content()` then rebuilds, so two
identical calls cleared and re-rendered the same set ~0.8 s apart — a visible
**flicker / jumpy reload**.

**Fix:** `display_thumbnails` now computes a **visual signature** of the requested set
(`_thumbnail_render_signature` = ordered `(study_uid, series_number, file_path)` per
thumbnail) and **returns early — no clear, no rebuild — when it equals the set already
shown/rendering** (`self._last_render_signature`). The signature is reset in
`clear_content()` (and `None` at init), so an explicit clear always allows the next
render. This is the single choke point for *all* render paths — single-study, the
socket-fetch render, the cache render, and the multi-study grouped main-page render
(`_hp_modules._show_grouped_patient_studies → display_thumbnails(combined_thumbnails)`)
all pass through it.

Guardrails:
- **Keep `display_thumbnails` idempotent for identical content.** Don't remove the
  signature short-circuit; don't make the panel unconditionally `clear_content()` +
  rebuild on every call.
- **The current signature is incomplete.** It contains `study_uid` + `series_number` +
  thumbnail path, but omits `series_uid`, `folder_key`, `display_key`, image/display counts,
  and a semantic payload version. Preserve the short-circuit while extending it with cheap,
  stable semantic fields so a same-path count or identity change is not suppressed. Do not
  add volatile timestamps, GUI-thread file stats, hashes, or directory scans.
- **The two triggers are intentionally left in place** (each covers a different
  open-completion path); the coalescing is at the render layer, so neither correctness
  path is removed. Reducing to one trigger is a deeper change and not required.

## 10. Main Page ↔ Patient Viewer unification — verified (2026-06-17)

A bug/architecture check asked whether the patient-viewer sidebar reuses the home
page's thumbnails or runs a separate/old path (it "seemed" to load slowly, one by one).

**Finding — thumbnail byte/source resolution is unified; action and lifecycle wiring are not.**
- Both consumers resolve through the SAME `ThumbnailStore` singleton (memory, keyed
  `(study_uid, folder_key)`) + canonical disk cache + `ThumbnailImageSourceService`.
  The viewer sidebar's live builder is `_pw_panels.add_thumbnail_to_thumbnail_layout`
  → `ThumbnailImageSourceService.load_pixmap` (store → disk). The legacy
  `thumbnail_panel.py` (`ThumbnailPanel`, with its `ThumbnailBatchRunner` drip) is
  **never instantiated** — do not attribute viewer behavior to it.
- On open, `_pw_thumbnails._load_server_thumbnails_async` calls
  `check_and_get_thumbnails` (disk) FIRST; on a **cache hit it renders directly with
  no server call and no regeneration** (the cache reuse return precedes the
  `get_study_thumbnails` fetch — pinned by
  `tests/code/ui_services/test_thumbnail_unified_pipeline.py`). It only fetches on a
  genuine miss, and never DICOM-re-decodes in the live path.

**Real causes of the *perceived* slowness (not a separate path):**
1. **Multi-study / non-primary study cache warmth.** The single-click home page warms
   the cache for the study/studies it displays; the viewer's primary loader fetches
   only `self.study_uid`, and other studies go through
   `_schedule_multistudy_thumbnail_prefetch` (per-study fetch on a daemon thread). A
   secondary study the home page did not pre-warm is a cache MISS on open → fetched
   fresh → slower/progressive. (Matches "especially second/non-primary study".)
2. **Cache miss during an active download** defers the (uncached) sidebar load behind
   the download and polls (150 ms ×8 then 700 ms, §4.4) → thumbnails trickle in.
3. Render cadence: home-page producers request `progressive=False`, but the right-panel
   component intentionally switches large sets to bounded progressive construction (§9).
   The cache-hit viewer sidebar is not the retired `ThumbnailPanel` drip path.

This unification statement applies to thumbnail source bytes and cache resolution. It does not
mean that main-page card actions and patient-viewer actions share a correct identity/routing
contract. Their historical divergence and the incomplete Zeta migration are documented in
`docs/plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md`.

**Structured logging added (2026-06-17)** for empirical validation on the next run —
`MainPageThumbnailRequested` (`_hp_search.py`), `PatientViewerThumbnailRequested` /
`ThumbnailCacheHit` / `ThumbnailReusedFromUnifiedPipeline` / `ThumbnailCacheMiss` /
`ThumbnailFetchedFromServer` (`_pw_thumbnails.py`), and `ThumbnailLoadedFromMemory` /
`ThumbnailLoadedFromDisk` (DEBUG, `thumbnail_image_source_service.py`). A
`ThumbnailCacheHit`+`ThumbnailReusedFromUnifiedPipeline` on open (no
`ThumbnailFetchedFromServer`) confirms reuse.

**Proposed follow-up (NOT yet implemented — needs live validation):** pre-warm ALL of a
multi-study patient's per-study thumbnail caches on the home page (so the viewer hits
cache for every study), and/or have the viewer reuse cached studies and fetch only the
genuinely-missing ones. This closes cause #1 — the dominant multi-study case. The
unification itself (shared store/service/keys) is already in place.

## 11. Patient-tab visibility ownership (2026-09-19)

Patient tabs are persistent owners: selecting another tab hides them but does not close
or supersede their catalog generation. Consequently, visibility is a pause/resume
boundary, while close and generation replacement remain cancellation boundaries.

- `PatientWidget.on_tab_deactivated()` pauses both the single-study Local stream and
  the prepared cached/server/grouped sidebar generation. No hidden Qt card mutation is
  allowed. One detached read or image preparation already in progress may finish.
- The Local producer pauses before advancing to another series. Its two-item mailbox,
  display-key allocation, verified inventory and database backfill remain owned by the
  same generation; returning to the tab resumes rather than rescans.
- The qasync sidebar retains its reserved rows, study headers, identity snapshot and
  progress. It waits before preparation and again before GUI application, so a result
  completing after deactivation cannot mutate the hidden layout. Its wait re-checks
  native owner validity every 50 ms because destruction does not wake an asyncio event.
- `on_tab_activated()` wakes both gates. `exit_patient_widget()` and generation
  supersession still cancel/retire through the existing paths; visibility must never be
  reinterpreted as disposal.
- Local intermediate INFO progress is sampled at card 1 and every tenth card. The
  terminal marker remains authoritative for the exact delivered total and elapsed time;
  do not restore one synchronous file write per Qt card.
- `AIPACS_PATIENT_THUMBNAIL_VISIBILITY_GATE=0` is the narrow legacy rollback.

This is shared catalog/presentation coordination only. It does not merge Fast,
Advanced or VTK decode, rendering or decoded-cache domains.
