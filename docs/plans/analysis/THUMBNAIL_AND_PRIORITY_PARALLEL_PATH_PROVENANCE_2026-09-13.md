# Thumbnail and Priority Parallel-Path Provenance — 2026-09-13

## Status and scope

### Patient-tab representative thumbnail owner (2026-09-26, code verified; live pending)

The title-bar image previously had several producers: cached-file startup was gated on
an asyncio loop, while sync/lazy/import/viewer-load paths assigned whichever thumbnail
finished first. None of those producers excluded the clinical-history document, and the
deferred update targeted `currentIndex()`. This was a parallel ownership defect: it
explains the intermittent plus icon, document header and possible cross-tab update
without implicating thumbnail bytes, decoding or VTK.

The existing sidebar card-admission function is now the sole producer. It passes the
same immutable series metadata used by the card to an O(1), identity-aware sink after
successful insertion. The sink excludes original SeriesNumber 100000, understands
multi-study offsets, requires no event loop and targets the PatientWidget's registered
tab. Independent assignments were removed from patient/viewer loading adapters. This
does not merge Home and Patient Qt lifecycles and does not create a second cache.

Four fail-before guards and 238 affected/adjacent passes protect the boundary; 42
packaging-input checks pass. Fresh source and frozen-artifact acceptance remain open.

### Canonical per-study presentation order (2026-09-26, code verified; live pending)

The historical cached-file, admitted-entry and grouped producers remain legitimate
input adapters, but they no longer own independent ordering. Their immutable rows
converge on `series_identity.series_presentation_order_key`; Home uses the same
per-study ordering boundary before render-signature calculation. Group order and
multi-study offset identity remain owner-local and unchanged. The bounded scheduler
also repositions retained cards when a newer generation supersedes an older partial
generation, preventing two series from occupying one grid row. Counts are derived
from planned series rows, excluding study headers. This removes duplicate presentation
authority; it does not merge Home and Patient Qt lifecycles or viewer backends.

Fail-before evidence reproduced a retained history card and an ordinary card at row
zero, and reproduced inconsistent per-study history order. Both guards pass after the
change; 230 adjacent tests pass. Source GUI and installed-artifact acceptance remain
open. See the thumbnail pipeline and UI-stall owner receipt for scope and rollback.

### Bounded cached/grouped application (2026-09-16, code verified; live pending)

The early cached path existed to give an exact count to startup routing; the
grouped path existed to preserve study headings and collision-free handles.
Neither purpose requires a synchronous full card build. Both now schedule through
the existing thumbnail batch service, returning the original exact count/acceptance
without treating pending presentation as a miss. Server entries join the same
owner after their existing metadata/count persistence step, avoiding two writers.
Worker image/readiness preparation feeds reserved GUI rows through the same manager.
The existing verified Local stream keeps its bounded pixel-inventory contract.
No-loop and process-start `AIPACS_SIDEBAR_BUILD_CHUNKED=0` are explicit compatibility/
rollback routes, not simultaneously active request owners. See the
[implementation and limitations](../../reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-bounded-cached-sidebar-build-opt-58--opt-60).

### Startup enumeration seam (2026-09-14, code implemented; sampled GUI verified)

The early single-study renderer's return count also selects startup hit/miss behavior. It
cannot simply become asynchronous and return zero: that would change import/download routing.
Normal qasync startup now prepares the same canonical listing in the existing executor and
passes an immutable tuple to the existing decision/render method. Layout exists before await
and is not replaced on delivery; close/identity/native validity reject obsolete results.
Grouped Server keeps its early skip; Local keeps authoritative DB display-key/frame projection.
This is preparation/application separation, not a second thumbnail renderer or download engine.
Direct refresh/Education/no-loop compatibility signatures remain; their disk I/O and grouped
availability/pixel preparation are explicitly later seams. Eighteen new guards include real
Qt/qasync heartbeat and deletion. The September 15 receipt for the fresh 23:16 source launch
observed grouped/Local pixels, counts, scroll and Local close/reopen; remaining GUI I/O and
scheduling waits prevent a whole-path performance pass. Exact UID, cold/cine and stress gates
remain open. See OPT-60 for current code/live and rollback receipts.

### Performance audit qualification (2026-09-14)

The sampled live receipt below is not a responsiveness pass. The
[current OPT-60 cost/stall audit](../../reports/UNIFY_PATH_COST_AND_STALL_AUDIT_2026-09-14.md)
re-read the same PID/window across log rotations: 81 F8 stalls, max 4116.3 ms; successive samples
show early single-study cache enumeration on GUI, and the grouped path still reaches `stat`.
Old scan helpers have no current HEAD diff; do not blame the new effect timers for their existence.
Keep the rationale for early/progressive display while moving blocking preparation through the
existing worker projection. The audit also measures owned-card overhead and documents missing
load/queue/teardown KPIs. No runtime change or new GUI lap; fresh lifetime tests: 31 passed.

### Sampled live receipt (2026-09-14, 21:04 source launch)

Fresh main PID 925068 contains the card-effect patch. Human login, existing client ping/action
discovery, then native Home double-click/wheel/close/reopen passed for a two-study 13-card case:
matching Study/Series UIDs, 8 slices, visible 5/8 -> 6/8; empty search cleared cards and exact
reselection restored them; tabs 5 -> 4 -> 5. A surviving tab still rendered its own 5-slice
series with matching identity. This is sampled input/output evidence, not proof of every
timer race, genuine same-identity changed-payload swap, large render or real completion event.
Native drag/Advanced/offline/cine/stress gates remain open. Scoped logs found an earlier
attachment worker failure and repeated response-size download errors, but no new errors in
the agent lap, no access violation or deleted-Qt markers. See canonical OPT-60 for timestamps,
classification limits and next work. No runtime source changed for this live receipt.

### Card-owned effects (2026-09-14, after the 20:41 source launch)

These effects are not a competing thumbnail pipeline: they provide short progress/Ready and
priority feedback. Preserve their existing cadence and keep them card-owned. The missing
boundary was cancellation across retry and retirement, not a reason to remove that feedback.
The progress animation now has a native card parent; the 450/2500 ms static callbacks became
two reusable card-owned timers. Manager reset/dispose stops card effects before releasing maps,
without detaching labels or changing paint-atomic replacement. All direct-child property
animations stop, including overlapping priority flashes whose latest reference was overwritten.

The old cleanup's `theme_manager` exists, but its `_on_theme_changed` does not: the broad outer
catch skipped animation cleanup. This corrects the earlier claim that a missing guarded
attribute made the misplaced disconnect harmless. No owner call was found before this change;
do not infer a live crash cause. Seven baseline failures, then two additional stuck-label
transition failures during adversarial review; 14 final real-Qt guards. Current test results,
rollback and fresh-source live gate are in the canonical OPT-60 receipt. The running 20:41
process predates this patch. Direct map clears and worker-image generation identity remain
separate follow-ups; download routing, counts, UID projection and cache keys are unchanged.

### Manager-owned callback retirement (2026-09-14, after the 20:03 live run)

The coalescing timers existed to limit repaint work; their cadence is valid. The missing
boundary was retirement: reset cleared visual maps without cancelling pending progress, and
retained card closures could dispatch the old numeric key after replacement. Seven initial
guards failed (behavior, absent disposal contract and owner wiring); two additional Home-owner
guards failed before that integration. Do not conflate these with native-crash reproduction.

All six manager scheduling sites now use parented cancellable generation-scoped timers. Reset
retires pending work; terminal idempotent disposal releases owner callbacks, connections and maps.
Patient exit retires the two panel managers independently; Home uses a weak render-manager
registry and disposes on clear without eager native deletion or changing atomic-swap semantics.
An adversarial native-destruction guard caught invalid timer/receiver disposal; validity checks
now preserve Python-state release without touching destroyed Qt resources. 17 final guards;
424 adjacent passes / 1 existing skip, exit 0; 462 mirrors match. Source GUI
blocked: documented ping failed and the previous main PID was absent. A fresh human source
bootstrap was requested. The prior 20:03 sample does not contain this change.

No routing/key/count/cadence/decoder/downloader change or new package dependency. Separate
card-owned animations, delete-without-owner-close reachability and legacy direct map clears
remain to be assessed. See canonical OPT-60 for acceptance/rollback and remaining Unify phases.

### Fresh-source sampled GUI receipt (2026-09-14, 20:03 session)

The user-requested source launch at 20:03:33 (main PID 1113400) includes the 19:17 patch;
human sign-in and documented client ping/action discovery succeeded. Server two-study Home
preview 13 -> empty search 0 -> restored 13, native exact-series double-click, wheel and
close/reopen passed with matching Study/Series identities, 8 slices and tab counts 3 -> 2 -> 3.
This removes the old-process/connectivity blocker, but does not exercise a real changed-payload
small same-identity swap or prove large/progressive owner replacement. Those live gates remain
open, alongside real completion/priority, native drag, heavy import and installed acceptance.

Through 20:12:47 the reviewed session logs had no ERROR/CRITICAL, deleted-object/traceback
markers or access violation; 38 stalls (max 1909.1 ms), one non-terminal startup COM event,
close exit 34.7 ms and deferred GC 154.5 ms. No real completion emission occurred. No runtime
edit or code-suite rerun in this lap. See OPT-60 for the complete bounded receipt.

New control-fidelity observation: `get_thumbnails_data` reported 1 row versus 13 native cards
and 13 `get_series_info` entries. Its `lst_thumbnails_data` projection is not yet a verified
displayed-list oracle. Keep investigation separate from product-rendering changes; do not
infer a missing clinical series from that adapter alone. Raw clinical responses remained private.

### Latest bounded slice: same-identity small refresh swap (2026-09-14)

Code PASS; live BLOCKED. The historical immediate renderer intended a paint-atomic refresh,
whereas the dispatcher cleared before scheduling it. The corrected dispatcher preserves cards
only for small non-progressive refreshes of the exact same ordered, known action identities.
All old actions/timers retire immediately. Actual removal/rebuild occurs in one paint-disabled
turn, with layout activation before paint resumes. Different/unknown identities, member/order
changes, empty clears and progressive/large sets keep their original clearing policy. This
deliberately does not retain a previous patient's cards while awaiting another patient's data.

Three failures before; 16 final real-Qt guards. One additional preparation-failure test exposed
an initial stale-card fallback; current pending refresh now clears on preparation failure and
permits retry. 390 expanded passes / 1 existing GUI skip, exit 0; 17 separate existing import/
overlay crash guards pass; 462 mirrors match. Default behavior, one core runtime file, no flag
or packaging change. This is not transactional recovery from each individual card failure.
Documented MCP client ping failed; 18:29 main.py launch predates latest 19:17 edit. Human source
restart/sign-in required; no recovery or live-pass claim. See OPT-60 for crash-status separation,
rollback, remaining generic disposal/routing/cache work and acceptance matrix.

**Default activation decision (2026-09-14):** the user requested default behavior for the recent
corrections. Inspection confirms Home action/metadata, search/render retirement and patient-tab
signal-lifetime changes already run without opt-in flags. No runtime/default change was necessary;
unrelated experimental flags and safety switches remain untouched. Default-path focused recheck:
90 passed, exit 0. Source restart is required to load the latest edit; live/installed gates below
remain open. See the canonical OPT-60 receipt.

### Latest bounded slice: Home render owner retirement (2026-09-14)

Code-verified, fresh-source live pending. The progressive manager was deliberately cached to
avoid reconstruction per card/timer tick. That is valid during a render, but clear never dropped
the reference, so old manager/card wrappers and the action map survived clear or a subsequent
immediate render. Separately, the Home action closure strongly captured the panel and could
schedule against its deleted native QObject. Real-Qt guards reproduced both ownership defects.

The fix drops the progressive reference only at existing clear/retirement, not at normal timer
completion. Existing card deferred deletion still owns the native widgets. The common Home action
factory weakly references its panel and checks validity/render token before queueing and again
on delivery. No patient-viewer manager, key precedence, cadence, download path or decoder changed.
Reuse of one stateful manager across patients was rejected (state-isolation risk); eager native
manager deletion/full reset was unnecessary and would couple the fix to generic delayed work.
This is reference retirement, NOT the unimplemented generic timer/state disposal contract.

Before: 4 failed / 3 passed, exit 1. Final 10 guards in `test_home_render_owner_lifetime.py`,
374 expanded passes / 1 existing GUI KPI skip, exit 0; 462 mirrors match. Compile/diff checks pass.
Only `right_panel_widget.py` changed at runtime (core-only). Existing source ping succeeds, but
17:57 process predates the 18:22 edit. Human restart/sign-in required for the replacement/empty/
small-set/exact-open live lap; previous GUI receipts do not validate this patch. See OPT-60 for
rollback and remaining full-disposal, atomic-swap, routing/cache and completion acceptance work.

### Latest bounded lifecycle slice: patient-tab external signals (2026-09-14)

Code-fixed; sampled fresh-source open/close/reopen PASS, completion/priority live pending.
The user requested continuing independent plan work. Investigation
of the documented priority-retention edge also found the adjacent app-lifetime `download_completed`
lambda retaining the patient widget. Real Qt tests using the production creation-time wiring show
both calls into closed/deleted tabs and a retained Python wrapper after native QObject deletion.
This is a demonstrated ownership defect, not an attribution of a particular clinical crash.

The shared tab service now creates a patient-parented `_PatientTabSignalRelay`; weak references
prevent outward ownership of Home/patient. Typed slots keep live routing on the GUI thread.
Per-connection disposal occurs before `exit_patient_widget` teardown; close-state checks reject
queued work, and native receiver destruction disconnects even without closeEvent. Replacement
retires the previous relay; unrelated subscribers remain connected. Priority still forwards the
same opaque key and supplied Study UID, and completion still filters the primary UID exactly as
before. Priority connection still occurs before lazy DM lookup. No priority coordinator migration,
new task, retry, downloader, IO, polling, forced collection or render scheduling change.

Alternatives rejected: disconnecting a whole publisher would break other open tabs; parentless
lambda callbacks leave receiver lifetime implicit; relying solely on closeEvent misses direct
delete/rejected-tab paths; changing generic ThumbnailManager state/keys couples this small fix to
a much larger migration. The relay belongs in the existing service, not another UI controller or
new runtime module. Its API is creation-time wiring and idempotent retirement, not a data cache.

Tests: 6 failed / 2 passed before correction, exit 1 after fixing one harness double-delete.
Final 16 guards; expanded 364 passed / 1 existing opt-in GUI KPI skip, 6 SWIG warnings, exit 0.
462 mirror pairs match; three core-only runtime files, no payload edits.

Fresh-source receipt 17:57:23-18:01:10: main PID 1114928, redirector 1110568; all three edits
predate launch, human signed in. Bounded MCP current-row selection found a two-study case with
13 Home cards. Native thumbnail double-click opened visible pixels, exact Series UID and
case-member Study UID, 8 slices. Native tab close removed only the patient tab; Home cards and
bridge stayed usable. Reselection/native double-click reopened the same Study/Series, 8 slices,
without duplicate tabs (3 -> 2 -> 3, including Home/DM). App left open; no saved patient data.
Logs: app 354, viewer 201, download 229, DB 181 records; zero ERROR/CRITICAL, traceback or
deleted-object markers. Close exit 42.5 ms, deferred GC 195.9 ms. No interval access violation;
one non-terminal startup main-PID COM event. 38 stalls, max 1773.8 ms: mixed workload, not a
performance comparison. No worker-completion/emission markers; actual priority/completion and
closed-tab non-delivery under these live events remain unverified. Wrapper collection is proven
by synthetic Qt guards, not by the GUI lap. No runtime edits/build/release in this live lap.
Full manager state/timer disposal, render-owned Home manager lifetime, atomic replacement and
priority/action/cache migration remain separate. See OPT-60 for rollback and verification scope.

### Latest follow-up: search-owned preview retirement (2026-09-14)

**16:35 fresh-source live receipt (through 16:41:32):** the user requested source launch and
confirmed human sign-in. Main PID 1111380, venv redirector 1111452; runtime edits at 16:32:08
and 16:27:52 predate process start 16:35:43. `ping`/live command inventory succeeded. One
bounded Server query (MR, September 12-14) supplied candidates; a two-study case was selected
through current-row MCP authority. Native observation: 13 Home cards -> empty query -> no
rows/cards and `0 series`. Selection of the retired row was rejected. Valid query/reselection
restored 13 cards. Actual Home image-button double-click opened a new patient tab: 13 sidebar
entries; rendered Series UID matched the unique Series 1 entry, Study UID belonged to the case,
8 slices and visible pixels. After the Local check, another actual Home double-click reused
the existing tab with unchanged UID/slice count and no duplicate tab.

Local was checked independently: valid Local selection displayed 6 cards for the selected
study; an empty Local query then cleared its table/cards/count. No source-switch-only assertion.
Source results and identity maps stayed transient; no patient identifiers/images were saved to
this receipt or fixtures. No pin configuration was changed. Pin retention/row-remap, advanced
overlap and Offline Cloud remain NOT EXERCISED live, covered by code guards only. No forced
timer race, native drag, installed build or download-completion acceptance is implied.

Session-scoped logs: app 405, viewer 142, download 243, DB 158 records; zero ERROR/CRITICAL and
zero thumbnail-task-cleanup errors. Native log contains one startup main-PID `0x8001010d`,
non-terminal, and no access violation in the interval. 41 timer stalls, max 2236.1 ms; mixed
startup/automation/idle workload, not matched before/after performance. No runtime changes in
this live lap. Sampled Server/Local retirement and new/reused open PASS; extended matrix open.
This receipt supersedes the implementation-handoff live-pending wording immediately below.

The user approved the next bounded prerequisite. The 15:39 source empty-search defect is now
code-fixed, not yet live-verified. Before editing, `home_search_service.py` matched HEAD; this
does not establish a regression from the preceding renderer correction.

Chosen seam: the existing search service, not a new signal path or table teardown rewrite.
All five service clear sites share `_clear_search_results`, with cancellation/generation checked
before mutation. It preserves only a selected pin whose Patient/Study identity matches before,
after and active preview; pending thumbnail fetch is rebound if its row moved. Other selection,
row debounce, fetch handle, render UID, action token and panel generation are retired. An explicit
retired flag distinguishes this from historical uninitialized identity, so late guarded producer
responses do not restore old content. Next valid selection restores normal behavior. Retiring
the task exposed two independently guarded cleanup defects: CancelledError escaped, and an old
failed task could clear a newer task handle. Cleanup now handles cancellation and checks ownership.

Alternatives rejected: clearing cards alone leaves late producers active; resetting all pins
changes existing UX; blanket cache/task cancellation risks patient-tab/download work; rewriting
native-safe table clear expands the crash surface. Existing Local/Offline early-clear timing and
Socket wait-for-results timing are retained. The helper adds only two in-memory row reads and
bounded state/timer operations beyond existing clear; it does not add disk/network/DB access or
an event pump. No measured speedup or complete epoch/disposal correctness is claimed.

Evidence: main guard 7 failed / 4 passed, exit 1 after fixing a fake-import setup omission; two
cleanup guards separately failed before correction. Final 18 synthetic guards and **302 adjacent
passes**, 6 existing SWIG warnings, exit 0; **462 mirrors match**. Both runtime files are core-only.
Two historical source guards were updated to inspect the shared seam, preserving/strengthening
the generation/no-event-pump invariants. No source relaunch or GUI action occurred in this slice.
Required live: empty query -> no old cards/0 series; valid reselection -> exact-series open;
surviving pins including shifted pending rows; Local/Offline where available. The already-running
15:39 source process cannot exercise these later edits. Scope/rollback and remaining ordered
Unify work are recorded in the canonical OPT-60 master-plan entry.

### Latest independent lifecycle slice: queued render retirement (2026-09-14)

The user deferred native-drag/stall investigation and requested progress elsewhere in Unify.
This slice isolates the documented stale-callback risk; full manager disposal and routing remain
separate. No current crash or measured UI stall is attributed to this defect without a trace.

**Reproduced:** `clear_content()` did not advance `_display_generation`. Scheduled initial
renders (0/50 ms), input-sync retries (16 ms) and late progressive ticks could survive a clear.
Direct renderer calls with `generation=None` bypassed stale checks on retries. Real Qt tests
also observed context-free callbacks after panel destruction. Actual clear paths include changed
selection in `show_patient_studies()` and `display_series_info()` during a new study load.
Correction after live inspection: empty server results clear the table, NOT the right panel.

**Correction:** clear is the single render-generation retirement authority; new display requests
capture its generation. Direct renderer entry binds an omitted generation once. Four render/retry
single shots use `QTimer.singleShot(delay, self, callback)` and progression uses `QTimer(self)`.
Clearing releases pending row payloads, invalidates actions and resets the old retry budget.
No new queue, worker, shared state, I/O, collection or polling is introduced. The two render
strategies retain their existing purpose, cadence, threshold, coalescing and input-sync bound.

Guards: `test_right_panel_render_lifecycle.py`, 9 failures / 4 passes before production change;
16 final tests including real Qt destruction/child timer ownership. The existing input-sync
guard's fake scheduler now accepts Qt's context overload without weakening its assertions.
Final adjacent gate: 197 passed, six existing SWIG warnings, exit 0. Mirrors: 462 pairs match.
Only `right_panel_widget.py` changes runtime behavior; it has no plugin payload mirror.

**Sampled live update:** the fresh 15:39 source lap below verifies selection replacement and
exact-series open, but reveals a separate empty-search preview-retirement gap. Forced timing
interleavings/panel destruction remain deterministic Qt evidence, not a claimed live pass.
Manager outward-signal
disposal, atomic replacement, native drag, completion oracle and full matrix remain open.
Rollback this slice's generation/context/timer-parent changes and guards only, leaving all earlier
Home metadata/identity/current-row fixes intact. No data migration or build is required to revert.

#### Fresh-source lifecycle integration receipt (15:39 session)

Source launch at the user's request, 2026-09-14 15:39:22; redirector PID 1109824, main PID
1106292, human sign-in. `ping`/`list_actions` and final ping passed. Base `5d3c72d5` plus existing
dirty worktree. `right_panel_widget.py` SHA-256:
`a0d7f5ad5295c8ad0b14e30925242498955c116623ee2668ca5a4139f40d2e95`.

- Bounded MR discovery for September 12-14 returned 100 cached rows and three multi-study
  candidates. Counts from that cache are not current-card readiness. Two selected cases showed
  13 and 17 Home cards. Five alternating MCP selections, separated by 0.65 seconds in the
  external client, all succeeded; the final observed panel returned to the 13-card case.
  No patient tab opened from selection alone. This samples cancellation/replacement across
  small/large sets; it does not instrument each timer or prove a particular race interleaving.
- **FAIL, separate empty-search presentation boundary:** a nonexistent synthetic-ID server
  query showed an empty table / No studies while the prior 13-card preview remained visible.
  Actual native double-click on an old card opened no tab (the current-row guard held).
  Code inspection: `HomeSearchService.search_server`'s no-results branch calls only
  `patient_table_widget.clear_table()` plus its status indicator; service source is unchanged
  against HEAD. This is a missing caller-side preview-retirement integration, not proof that
  `RightPanelWidget.clear_content()` allowed a retired render. The former receipt's claim that
  empty search already called that panel clear is corrected above. Full historical classification
  and a fail-before guard for search completion/cancellation/pinned selection remain pending.
- **PASS, recovery/open:** re-querying the valid case and selecting it restored valid context.
  Native Home Series 1 double-click opened the patient tab; 13 destination entries, exact
  Series UID match, Study UID in the selected case and 8 rendered slices. Initial blank-layout
  capture was during asynchronous loading; final pixels and metadata were verified afterward.

Log boundary 15:39:22-15:52:00: app 645 records, viewer 136, download 295, DB 170; zero
ERROR/CRITICAL and Home-action errors, zero `DM-CONVERGE-MISS`. Fifty timer stalls, maximum
2222.2 ms; one main-PID `0x8001010d` at startup and no new access violation. Continued GUI
operations and final ping establish that event was non-terminal. Startup, idle and automation
are included; no no-lag, speedup, complete-download or full stability claim is made.

No runtime change, new app launch, forced fault, clinical report/annotation, packet capture or
installed build occurred during this post-login lap. No patient data was stored in the receipt.
Native drag and stall investigations remain deferred by user request. Track empty-search
retirement under OPT-60 before calling the whole Home lifecycle integration complete.

**Latest slice, 2026-09-14:** the user expanded the requirement to explicit Home thumbnail
double-click: open/reuse the patient tab and place exactly that series. Single click remains
preview-only. Cache producer identity loss is corrected and guarded. Code acceptance passed;
the user has now live-verified the exercised double-click workflow, corroborated below.
The 13:22 source restart now verifies the sampled open/header route and observed count refresh;
targeted semantic-only refresh and the extended matrix remain pending (latest receipt below).
Earlier existing-tab-only
and failed-live receipts below remain historical evidence, not the current behavior contract.
Home drag MIME and retry/priority migration are still outside this slice.

### Current-row selection adapter correction (after the 13:22 live lap)

The two `select_patient` adapters now converge on the current table as selection authority.
The wrapper no longer resolves missing fields from accumulated search history. The UI adapter
matches one visible current Patient ID / optional Study UID, selects the actual Qt row and uses
the existing debounced selection timer. A grouped member UID resolves to that row's primary UID;
the supplied name cannot override current metadata. Current-row identity is rechecked after
selection signals. No direct call to the Home single-click handler remains in this adapter.
Search-in-progress, wrong-thread, absent/hidden/ambiguous and incomplete-identity cases fail closed.
Response `selection_state=queued` does not certify thumbnail readiness or first visible pixels.

Why this seam: the real table already owns highlight, single/double-click timing, supersession
and the paired `patientClicked`/`thumbnailRequested` signals. Reusing it avoids another callback
or polling loop, while retaining the downstream Home UID guard. The separate legacy secretary
checkbox-selection workflow (`select_rows_by_code` / `select_top_n_rows`) was inspected and is
not this preview-selection route; it is unchanged.

Guard: `tests/code/echomind/test_home_selection_fidelity.py`, synthetic real Qt table with the
production debounce methods, no live DB/network. Fifteen initial behavioral failures reproduced
the pre-fix defect; three extra safety cases were added afterward. Final Home/adapter neighbors:
99 passed, exit 0. Separate command/bus/permission/viewer/build lane: 89 passed / 1 failed;
the failure is stale generated-stage config parity, with its relevant source/config files
unchanged against HEAD. No quarantine or generated-stage repair. Two mirrors synced, 462 match.
MCP function argument shapes remain unchanged; selection results now distinguish queuing.

**Source-live PASS for the sampled prerequisite:** the 15:15:21 process contains this change;
the receipt below supersedes the earlier pending gate. No compensating native row click or
adapter hot-reload was used. Extended matrix and native-drag acceptance remain separate.
Rollback only the two adapters/mirrors and their related tests/docs. No decoder/download policy,
viewer execution-domain or persisted clinical-data change was made by this patch.

### Corrected selection source-live receipt (15:15 session; reviewed through 15:26:01)

One source launch at the user's explicit request: venv redirector PID 1101924 and main PID
1106228, started 2026-09-14 15:15:21 local. Human sign-in completed; `ping`, then `list_actions`
passed. Base revision `5d3c72d5` plus the preserved dirty worktree; adapter SHA-256 values:

- `home_widget_adapter.py`: `c8001aca1edbd4e222e2d9e4acd822f5fb0660f7db4291d903e090b566738589`
- `home_command_adapter.py`: `6f103f43f147d4f6ab43e635b260f7285a3f8c9c1612c8cbaca23d77bb721909`

Case alias `CASE-MR-MULTI`: bounded September 12-14 MR discovery, followed by exact-ID
selection from current results. Discovery returned 100 cached rows and three multi-study
candidates; an unrelated substring result from the narrowed query was not merged or opened.
The exercised case contained two studies and 13 series. No real identifiers or pixels were
saved into this receipt or fixtures; live responses remained transient in the local client.

| Gate | Result and observed boundary |
|---|---|
| Current-row MCP selection | PASS: `selection_state=queued`; the real row was highlighted and 13 Home cards appeared, without a native row click. |
| Home new-tab input | PASS: actual first-study Series 1 double-click opened the patient tab and displayed 8 slices. Rendered Series UID matched its destination series entry; Study UID belonged to the selected case. |
| Fail-closed selection | PASS: nonexistent synthetic ID returned `HOME_SELECT_FAILED`; tab count was unchanged. |
| Grouped member / tab reuse | PASS: member-UID reselection returned the same canonical row. Native second-study Series 1 double-click reused the tab and displayed that distinct Series/Study UID with 8 slices. It rendered in viewport 0; the initial viewport-1 probe was corrected after observing the actual destination. |
| Native wheel | PASS: viewport 0 index 4 -> 5, visually changed image, same second-study Series UID. |
| Native sidebar drag | INCONCLUSIVE: a real drag from Series 2 toward empty viewport 1 left the drag image active and destination slice count 0. Escape removed the drag image; later bridge commands worked. Input injection completion is not a verified Qt/OLE drop, and this is not evidence to rewrite the product drop route. |

Direct focused/adjacent pytest rerun, offscreen, debugging plugin disabled and reruns 0:
**99 passed, six existing SWIG warnings, exit 0** (7.70 s). Selection included the current-row
guards, adapter contracts/bus factory, Home series action/open, metadata/local projection,
right-panel input synchronization and patient single/double-click guards. Earlier separate
stage-config parity failure remains unresolved; no build or generated-stage rewrite occurred.

Regular log review, timestamp-scoped 15:15:21-15:26:01: app 526 records, viewer 172,
download 207 and DB 148; zero ERROR/CRITICAL. Three Home-action markers, none error/not-routed.
Across these logs, 37 `[MAIN_THREAD_STALL]` timer records, max gap 2263.1 ms; zero
`DM-CONVERGE-MISS`. Native fault headers identify one main-PID `0x8001010d` at startup
15:15:22, non-terminal as subsequent live operations succeeded; no new access violation.
Startup/idle/search/native automation are mixed in this interval: neither a matched speed
comparison nor proof of no lag or complete downloads. Final bridge ping passed.

No runtime implementation, decoder, download policy or configuration was changed during this
verification. The app remains open. Current-row selection's sampled live gate is closed;
native Home/sidebar drag, isolated same-path semantic refresh, unnamed/cine/offline cases,
full identity matrix and installed acceptance remain open under OPT-35/OPT-60 and OPT-04.

### Fresh-source native-input receipt (13:22 session; verified through 13:53)

The user explicitly requested normal close/restart, then completed sign-in. Only the source app
was restarted, with its existing local test bridge enabled. The old bridge was unavailable;
the new `ping` and `list_actions` succeeded. Direct client responses and identity comparisons
were kept transient/local; only aggregate outcomes are recorded here. No product code changed.

One bounded MR query found a two-study candidate. An exact-ID search also returned a different
substring-matching patient: that row was not selected or treated as another study of the case.
The selected case had two verified studies and 13 series with repeated numbers; initial metadata
counts were incomplete. Discovery cache counts are not authoritative rendered series counts.

Initial Home double-click attempts selected cards but emitted no open request. The test used
`select_patient`, whose adapter only calls `_on_patient_single_clicked`; it does not select the
actual table row. `_on_right_panel_thumbnail_clicked` requires `currentRow()` to resolve the
selected row and match the active-selection token. A native click on the actual row established
that missing precondition, after which the same Home workflow succeeded. This is an adapter
fidelity gap, not evidence that the UID or production double-click gate should be relaxed.

Verified results:

1. Normal open via the existing bridge produced a tab with two empty viewports (no unwanted
   auto-placement). A selected series loaded with exact UID match.
2. Two repeated-number series from different studies placed in viewports 0/1 had 9/11 slices,
   distinct metadata Study UIDs and exact requested Series UIDs. Images were visually observed.
3. Native wheel changed left index 4 -> 5; MCP `scroll_slices` set right index to 0. Both preserved
   series identity. Native wheel and bridge navigation are recorded separately.
4. Home metadata refreshed to 13 populated count badges after normal local preparation and
   re-selection. Observed groups: 8/1/1/9/9/25 and 8/1/1/11/11/18/1. This is not an isolated
   unchanged-path/unchanged-identity mutation; that narrow semantic-only gate is still pending.
5. After native row selection, native Home double-click reused the existing tab and placed the
   second-study series in viewport 0, exact UID, 11 slices. Then normal close of only the test
   patient tab followed by Home double-click created a new tab with the first-study series,
   exact UID, 8 slices. Request 13:52:31.439799, placement 13:52:32.412271, first-visible marker
   13:52:32.766740 (~1.327 s from request). Generic `Study 1/2` Home headers were observed.
6. One native patient-sidebar drag returned from the input tool but the destination retained
   its previous series. **INCONCLUSIVE**, not a confirmed completed OLE drop or a product-failure
   diagnosis. The bridge remained responsive. Do not replace this result with the successful
   downstream `change_series` test. No repeated drag retries or forced process recovery.

Health for the whole source session through 13:53:03: zero ERROR/CRITICAL in app/viewer/download/
DB logs, 51 timer stall records (max 1776.5 ms), seven `DM-CONVERGE-MISS` markers. Native log:
one main-process `0x8001010d` at startup, non-terminal; no access violation after the new boundary.
The previous session acquired a child access violation after its earlier review; it must not be
attributed to this source run or silently omitted by relying on the earlier snapshot. The final
ping succeeded and the source process remained alive. These session-wide counts include idle
time/startup/automation and are not comparable performance baselines or download completeness.

Remaining gates: semantic-only same-path refresh, cine/offline/unnamed matrix, native drag,
later priority/cache/lifecycle phases and installed acceptance. No clinical edits, deletion,
external image/report submission, build or release were performed. Normal open/download and
visit-state side effects followed the existing app workflow. The private client was closed;
the app remains open for the user.

### Latest source-session receipt and semantic-refresh follow-up

Reviewed the source session beginning **2026-09-14 12:49:16**, with regular records scoped by
their timestamps and native exceptions by their session header/PID. Open log files had stale
filesystem modification times: those times must not substitute for the actual record boundary.
No raw clinical identifiers, images or logs are copied into this receipt.

- Home request at 12:49:39.493488, two-study open, tab creation at 12:49:39.832112,
  seven-series metadata publication at 12:49:40.061181, placement request at 12:49:40.200202,
  and first visible image at 12:49:44.636046 corroborate the user's successful test.
  The identity gate reported neither study nor series mismatch; one rendered stack had 11 slices.
  There was no action timeout/open error or skipped identity gate in this scoped sample.
- Request-to-first-visible was approximately **5.143 seconds**. Renderer-local `total_ms=66.9`
  and `decode_ms=12.1` are not end-to-end click latency. This review does not attribute the whole
  interval to server delay or GUI blocking.
- No ERROR/CRITICAL records appeared in the reviewed app/viewer/download/DB session logs.
  Sixteen timer stall records exceeded 100 ms; maximum 2058.3 ms occurred at 12:49:26.753651,
  before the click. Click-adjacent records included 389.8 and 366.6 ms. Three separate trace
  markers are not additional independent stalls and must not be double-counted.
- Ten `DM-CONVERGE-MISS` markers remain OPT-04 evidence debt, not proof of missing downloads
  or a license to retry. Completion must still be established by the authoritative oracle.
- Two `STUDY-PK-GUARD` records began with an effective PK of `None`. Source inspection confirms
  this legacy guard runs before the SeriesRef DB authority override; its "NON-primary" wording
  can describe initialization. These records do not establish cross-study contamination or
  justify removing the guard. Future instrumentation must separate initialization from conflict.
- One 11-slice geometry-order diagnostic selected a reordered synchronization copy; it does not
  establish a decode failure. No geometry behavior changed here.
- One main-session native `0x8001010d` event was non-terminal in the observed run; the source
  process remained alive. There was no access violation after this session boundary. Earlier
  file history and child fault-handler registrations are not new main-app crashes.

**Acceptance scope:** user-confirmed Home double-click on the exercised two-study server-open
sample, corroborated by the above chain. This does not verify every series across both studies,
duplicate/unnamed cases, offline/cine behavior, actual Home native drag or installed builds.
The process started before the final header correction (12:51:50) and before the next change.

**Next guarded correction:** `_thumbnail_render_signature` formerly ignored changed visual
metadata at the same path. It now calls the same pure metadata normalizer used to create cards,
then includes modality, description, object/display/pixel counts, protocol, body part and study
label alongside path and immutable action identity. Alias-equivalent inputs still coalesce.
The normalizer became a static method without changing its mapping. This is not a new producer,
download route, scheduling policy or codec path. Same-path changed pixel bytes still require an
explicit producer revision/invalidation contract; no file reads/stats/hashes were added.

Fail-before evidence: **9 failed / 2 passed**, including a real Qt card remaining at "2 images"
after receiving 420 display frames at the same path. Pass-after: **68 focused passed**, then
**931 expanded passed / 1 skipped / 3 deselected / 3 existing xfails**, both exit 0 with reruns
disabled. The two explicit exclusions are the unchanged HEAD failures recorded below; the other
deselection follows the existing marker selection. No quarantine change or clinical fixture.
Mirror verification: **462 pairs match**, exit 0. Final diff whitespace check passed.
Warmed synthetic signature-only probe, 500 rows/50 runs: median **1.894 ms**, p95 **2.051 ms**,
max **2.121 ms**. This excludes Qt construction and is not a matched application benchmark.

Changed runtime boundary: `right_panel_widget.py` signature and normalizer binding only.
Guards: `test_home_series_action.py` (11 new cases), with the direct AST test invocation adapted
in `test_right_panel_metadata_contract.py`. **Code verified; new live gate PENDING.** On a human
restarted source app, check same-path count/description refresh, normal double-click, and the
extended identity matrix. Do not modify clinical files just to manufacture the refresh fixture.
Rollback only this signature/normalizer-binding slice and its associated tests; preserve all
earlier identity/open routing and unrelated dirty-tree changes. No release/build was performed.
Remaining order is maintained in OPT-35/OPT-60 and OPT-04 in the master plan.

### Explicit thumbnail-open implementation receipt

- Home alone installs a double-click filter on its image buttons. The shared patient-card
  single-click/drag implementation is unchanged. The existing render-token queue prevents native
  input reentrancy and rejects retired cards. Selection changes invalidate pending render work.
- Home captures the selected row and source, checks selection again before scheduling, and
  delegates to `HomeTabService.open_series_action`. The standard asynchronous patient-open
  method now returns its created/reused widget; no second constructor/downloader path exists.
- Repeated opens share one in-flight task; the last intent wins. The pending receiver is parented
  to that patient QWidget. `series_metadata_ready` and `loading_complete` use queued QObject
  slots, so worker metadata cannot perform GUI/VTK work. Resolution uses both UIDs and the
  destination's current key map, including primary-bucket/multi-study offsets.
- A tab change, close, newer placement or a placement during opening supersedes the pending
  intent. A single 30-second timer releases unresolved intent and logs `metadata_timeout`; it
  does not poll, perform I/O, fall back to Series Number or claim rendered completion.
- `_build_cached_thumbnail_payload` is the common cached-card projection for regular, grouped,
  downloaded-preview and Offline Cloud Home paths. Its reads execute through existing worker
  dispatch. Supplied downloaded-preview rows preserve that route's narrower scope; DB-mode
  missing-row fallback remains. Duplicate numeric filenames cannot acquire an arbitrary UID;
  unique collision-suffixed storage keys remain actionable. Object count and display-frame
  count remain separate. The Local pixel-inventory projection remains a complementary path,
  not an obsolete duplicate: it discovers displayable instances and expands frame counts.
- Socket and metadata-only placeholders retain request-scoped Study UID. No raw card ordinal,
  display name or foreign display key is accepted as a destination identity. No codec, pixel
  encoding, DICOM bytes, import grouping, download policy or backend boundary was changed.
- Presentation guard: retaining Study UID must not add a raw-UID header to a formerly ungrouped
  single-study preview. Single-study headers remain absent unless explicitly labeled; automatic
  multi-study labels use `Study N`, while explicit labels are preserved. Both guards failed
  before this corrective presentation adapter; grouping still keys on identity, not names.

Verification: six failures in the first requirement run (three behavioral defects, three absent
service API cases), followed by a separately failing downloaded-preview worker guard. The latest
focused run is 57 passed; the final expanded adjacent run is 920 passed, 1 skipped, 3 deselected and
3 existing xfails. The two intentionally excluded failures also fail against HEAD source and
their runtime files are byte-equivalent after newline normalization; no quarantine was added.
Stateful identity: 1 passed, 150 examples/up to 40 steps. Mirror verification: 462 pairs match.
All passing commands exited 0; reruns disabled. No live database or clinical fixtures were used.

Historical pre-user-test receipt: source-live gate was PENDING. A synthetic cache-to-real-Qt-double-click-to-service/new-tab
guard is not a live viewport pass. Restart/login was requested; the pre-change live session is
not evidence for this patch. Acceptance must inspect actual rendered identity, not just command
admission. Rollback is this coordinated source/test slice only (Home adapter/cache convergence,
service receiver, widget readiness signal/selection cancellation and async return values),
preserving all preceding dirty-tree Unify work. No build or installed binary was produced.

The original 2026-09-13 source, documentation, and Git-history analysis was read-only.
The 2026-09-14 implementation record below tracks the first guarded prerequisite separately.
It exists to prevent a future cleanup from deleting a parallel path merely because it looks
duplicated. Some paths represent deliberate latency, offline, reconciliation, or identity
contracts; other paths are incomplete migrations and should be retired only behind fail-before
guards.

The analysis covers the main-page right panel, patient-viewer thumbnail cards, local/cache/server
thumbnail supply, render cadence, series action identity, and priority-download routing. It does
not propose changes to DICOM decoding, grouping, storage bytes, Fast/Advanced/MPR rendering, or
the socket protocol.

## Executive conclusion

There are three different reasons for parallel code in this area:

1. **Deliberate complementary paths:** immediate versus progressive rendering, and local/cache
   projection versus server reconciliation. These paths solve different latency and availability
   problems and must remain.
2. **Compatibility and identity evolution:** `SeriesNumber` began as both label and action key,
   then multi-study offset keys and duplicate-number `folder_key`/`display_key` identities were
   added. The generic card still supports the patient-viewer display-key contract, while the
   right panel incorrectly supplies a visual ordinal at the action boundary.
3. **Incomplete migration:** direct single-series download code predates Zeta. Zeta became the
   primary downloader, then `SeriesIntentCoordinator` became the authority for viewer intent,
   but the old right-panel click handler and direct-downloader helpers survived mechanical source
   splitting. Their current API mismatches are migration residue, not a second supported download
   architecture.

The safe future direction is therefore **preserve and clarify the complementary paths, repair
identity at the boundary, and retire the stale download route through the existing Download
Manager/intent authority**. A broad deduplication would regress behavior.

## Provenance timeline

| Date / commit | Change | Original purpose | Current interpretation |
|---|---|---|---|
| 2026-01-27 `388dfcab` | Main-page `RightPanelWidget`, 120 ms progressive card creation, `thumbnailClicked`, direct priority helpers | Show a responsive series preview and make a clicked series load/download first | Valid UX intent, but ordinal position was used as the card action key because the early viewer model treated index and series key as interchangeable |
| 2026-02-05 `d5b4189c` | Zeta declared the primary download system; legacy priority manager removed; older download methods marked deprecated | Stop independent/parallel download orchestration and centralize queue/priority | Migration began, but transitional stubs and the old right-panel handler remained |
| 2026-04-04 `20fcc94f` | `SeriesIntentCoordinator` introduced | Centralize viewer/open intent so callers do not independently mutate queue state; coordinate preemption and restart | This is the architectural authority for priority intent |
| 2026-04-13 `b46b236f` | Large `home_ui.py` mechanically split into `_hp_*` mixins | Reduce the monolithic controller without changing behavior | The split preserved both the valid unified handler and stale direct handler; file separation did not complete semantic migration |
| 2026-05-24 | Multi-study single-tab implementation and Zeta architecture review | Preserve study-scoped identity; avoid duplicate download changes; document the live worker path | Confirms download was already correct for multi-study and that dead/stale worker paths are hazardous |
| 2026-05-25 `60e9106e` | Grouped right-panel rows and immediate render path | Render study headers and swap an entire small set without flicker | Row/card ordinal became explicitly separate from row index, but was still passed into the generic card as the action key |
| 2026-06-02 `0888ae43` | `_thumbnail_render_signature` | Coalesce the fast projection and later metadata projection so an identical set is not rebuilt twice | Both producers are intentional; coalescing is the correct seam, but the signature is now semantically incomplete |
| 2026-06-06 `d921473b` | input-synchronous dispatch deferral | Prevent a Windows `0x8001010d` native failure while building cards during double-click dispatch | Required Windows/Qt safety boundary; not removable as cosmetic delay |
| 2026-06-27 `fddeaa83` | large immediate requests redirect to progressive rendering | Avoid a measured ~23 s GUI freeze from building a large multi-study card set in one event-loop turn | Explains why immediate and progressive implementations must coexist |
| 2026-08-30/31 `7f96b392` / `4ba24be8` | duplicate-SeriesNumber identity, exact storage `folder_key`, digit-only `display_key`, pixel/display counts | Preserve distinct DICOM series without overwriting storage and keep viewer drag handles numeric | Patient-viewer consumers were migrated; the right-panel action seam was not, exposing the old ordinal assumption |

## Parallel thumbnail-supply paths: preserve them

### Local/cache projection

The first visual result should come from `ThumbnailStore`, canonical PNG storage, SQLite/disk
metadata, or an already supplied inline thumbnail. This supports:

- hard-offline Local operation;
- fast first paint when the server is slow or unavailable;
- reuse of already downloaded/imported data;
- no DICOM re-decode on the normal cache-hit path.

Local mode must return before any PACS socket access. A local cache miss may rebuild from the
exact local series folder off the GUI thread, but it must never be converted into a server fetch.

### Server reconciliation

A later server response is not a redundant second implementation. It detects a study that gained
series after the local cache was created, supplies missing metadata/thumbnails, and completes an
open workflow whose first paint came from cache. Removing it would make the UI fast but stale.

The correct structure is local-first plus one identity-scoped reconciliation result, with stale
generation rejection. It is not local-or-server as mutually exclusive alternatives.

### Render coalescing

The fast and reconciled projections can legitimately carry the same visual set. Commit
`0888ae43` therefore added `_thumbnail_render_signature` at the final render boundary. That is the
right architectural idea: producers remain independent, while identical results converge before
Qt card destruction/rebuild.

The original signature used only `(study_uid, series_number, file_path)`. The September 14
identity prerequisite added the immutable action identity; the latest follow-up above adds
normalized visual metadata, sharing the card-rendering normalizer. Same-path count/description
updates are now guarded; pixel-content revision/invalidation remains pending. Neither comparison
nor future revision handling may add GUI-thread file stats, hashes or directory scans.

## Parallel render paths: preserve both cadence strategies

`display_thumbnails_immediately` and `display_thumbnails_progressively` are not obsolete copies.

- The immediate path constructs a small set while painting is disabled. The original intent
  was an atomic old-to-new swap without an empty panel or one-card-at-a-time flicker. The
  September 14 follow-up found that today's dispatcher clears before deferring this build;
  that discrepancy needs its own regression-guarded scheduling correction below.
- The progressive path creates bounded work across event-loop turns. It prevents a large series
  set from monopolizing the GUI thread.
- Callers request `progressive=False` for a calm/atomic result, but the right panel intentionally
  redirects a set above `_THUMB_IMMEDIATE_MAX` to the progressive implementation. The public
  request expresses UX preference; the component retains the safety override.
- Both paths retain the input-synchronous Windows guard and render-generation checks.

A future refactor may share row/card construction, but it must preserve both scheduling policies.
Do not force all sets through one synchronous loop, and do not make every small set visibly drip
in one card at a time.

## Why the generic card and right panel disagree about identity

The original `ThumbnailManager` treated `thumbnail_index` as all of the following: list position,
selection key, viewer switch argument, drag payload, widget-map key, and priority series number.
That worked only while series numbers were effectively contiguous and unique in the active study.

Later viewer work deliberately kept `thumbnail_index` precedence because patient-viewer callers
pass an opaque digit-only `display_key`. That key may be a multi-study offset or a reserved-band
alias for duplicate raw SeriesNumber values. Changing generic precedence to prefer
`series_info.series_number` would reintroduce wrong-series collisions in the patient viewer.

The right panel, however, passes `0, 1, 2...` card ordinals. A behavioral probe with raw
`SeriesNumber=4` and `thumbnail_index=0` emitted `0` for drag, selection, and priority. This is a
boundary bug, not a reason to change the generic manager contract.

The future right-panel action envelope should be self-describing and immutable:

```text
study_uid
series_uid
series_number       # raw DICOM metadata / server ordering
display_key         # patient-viewer action handle
folder_key          # exact local storage identity
```

No one string can safely replace that envelope across main-page, local-storage, multi-study,
duplicate-number, viewer, and Download Manager boundaries.

## Priority-download paths: migration history and current authority

### The original direct path

The January source contained a main-page signal handler plus direct single-series helpers. It
also contained multiple definitions of `_handle_priority_download_from_thumbnail` in the same
monolith. The intent was reasonable for that architecture: clicking the preview should fetch the
requested series immediately, then display it.

### Why Zeta created a second path

The direct path could compete with a study already owned by the Download Manager. Zeta was made
primary in February specifically to own queue state, priority, cancellation, progress, resume,
and one worker/download task per study. The April coordinator then centralized viewer intent so a
caller promotes an existing task instead of starting a competing downloader.

### Why the old code still exists

The migration favored compatibility and incremental release safety:

- old methods were marked deprecated instead of deleted;
- a fallback branch was left for Download Manager unavailability;
- the large controller was later split mechanically into mixins;
- tests concentrated on Download Manager internals and patient-viewer behavior, not the
  main-page card-to-handler contract.

That explains survival, but not current validity. Today:

- `_on_right_panel_thumbnail_clicked` reads `right_panel_widget._current_study_info`, for which no
  assignment exists in current source or the inspected historical revisions;
- it calls `_download_single_series_immediate`, while the retained helper is named
  `_download_single_series_immediately` and has a different signature;
- that helper instantiates the current `SeriesDownloader` using a retired host/port API and calls
  methods the current class no longer exposes;
- `_download_single_series_with_priority` is a deprecated disk-check stub, not a real fallback;
- the nominal unified handler does reach `DownloadManagerWidget`, but references undefined
  `target_series` after dispatch and still performs synchronous disk/metadata/server work on the
  GUI thread.

Therefore the direct route is not a supported second implementation. It is a stranded migration
cluster. Future work should route both main-page and patient-viewer series intent through one
small identity-aware adapter into the existing Download Manager/`SeriesIntentCoordinator`, then
remove unreachable direct code after guards prove behavior. Do not revive the retired gRPC/direct
downloader API.

## Ownership findings adjacent to, but separate from, routing

`ThumbnailManager` still lacks a disposal contract, but the initial hypothesis required
correction:

- a standalone manager was collectible while connected to `ThemeManager.themeChanged`;
- an immediate right-panel manager remained alive while its cards existed, then was collectible
  after card deletion;
- the confirmed strong-retention edge is the patient-tab priority signal connected to an
  external lambda that closes over the patient widget/home owner;
- static delayed callbacks can retain an old render generation for a bounded interval and can
  deliver stale work.

Lifecycle correction must be a separate patch from action identity/routing. A stable manager
owned for one right-panel render generation is safer than either one manager per card or one
stateful manager reused across unrelated patients. Reusing one manager for the application
lifetime would risk carrying selected/ready/viewed state across patients.

## Additional prerequisite defect

At the 2026-09-13 baseline, `_build_local_series_thumbnail_payload` imported and called
`allocate_series_display_keys`, but the call was indented inside its exception handler. A
healthy local payload therefore did not receive the intended display keys. The existing test
only checked for the helper name in the source, not successful behavior. The 2026-09-14 fix
below closes this prerequisite before a new right-panel action contract depends on `display_key`.

Also note that `allocate_series_display_keys` groups collisions by `(study_uid, raw number)`.
Across several studies, identical raw numbers may remain identical. Grouped home cards should
carry the full action envelope instead of assuming a patient-global unique string.

## Required implementation sequence

1. Add fail-before behavioral guards for local display-key allocation, right-panel action
   identity, and the existing anti-flicker/large-set scheduling policies.
2. Define a plain immutable series-action value object or normalized dict at the right-panel
   boundary; keep Qt widgets and DICOM datasets out of it.
3. Correct Local payload projection without adding network access or GUI-thread disk work.
4. Route main-page actions and patient-tab priority actions through one adapter into the existing
   Download Manager/intent coordinator. The adapter must distinguish already-local display from
   server priority intent.
5. Remove the dead right-panel direct handler/helper cluster only after the new guards pass and
   repository-wide references are zero.
6. In a separate lifecycle slice, disconnect outward callbacks, add idempotent manager disposal,
   and generation-gate late callbacks.
7. Extend the render signature with semantic identity/count/version while retaining coalescing.
8. Run focused identity, Local-offline, thumbnail, Download Manager, patient-viewer, lifecycle,
   Windows input-dispatch, and packaging/mirror guards; then perform source live verification.

## Fail-before guard matrix

| Guard | Failure it must expose before the fix |
|---|---|
| Right-panel card action | raw Series 4 must not emit ordinal 0 |
| Duplicate SeriesNumber | two series with distinct SeriesInstanceUID/folder keys remain independently addressable |
| Multi-study | same raw number in two studies routes by study/series UID, never current selection or ordinal |
| Local hard-offline | click/drag and viewer open perform zero socket calls |
| Local payload display keys | healthy payload construction executes allocation and preserves exact folder/path identity |
| Download ownership | priority promotes/reuses one existing study task; no direct competing downloader |
| Render coalescing | identical fast/reconciled payload does not clear/rebuild |
| Semantic refresh | changed count/identity/version with the same PNG path does rebuild or update correctly |
| Large card set | bounded card construction keeps the GUI event loop responsive |
| Lifecycle | old-generation callbacks no-op and patient/home ownership graphs release after explicit teardown |
| Installed build | no dependency on development-only interpreter paths, console processes, or retired gRPC code |

## Non-decisions

- Do not delete progressive rendering.
- Do not delete server reconciliation in favor of a permanently stale local cache.
- Do not change generic `ThumbnailManager` key precedence as a shortcut.
- Do not add a new downloader, reconnect gRPC, or instantiate `SeriesDownloader` from the GUI.
- Do not perform disk enumeration, server metadata fetch, decode, or DB lock waits in the click
  handler.
- Do not combine lifecycle, identity, render-signature, and download migration into one patch.
- Do not claim a native crash cause from ownership analysis without a matching runtime trace.

## 2026-09-14 implementation record: Local identity prerequisite

**State: fixed and automated-verified; full right-panel action migration remains pending.**

The first production slice adds three lines to `_build_local_series_thumbnail_payload`:
key allocation runs after the projection error boundary whenever completed rows exist.
This uses the existing canonical allocator and preserves its behavior for partial results.
An early dependency-import failure leaves an empty payload and cannot call an unbound local.
Successful rows retain raw labels, SeriesInstanceUID, exact persisted path/folder, separate
instance/frame counts, and the existing metadata-only exclusion.

The new behavioral guard executes the actual method AST with synthetic database, thumbnail
path and inventory boundaries and the real pure allocator. It opens no live database, socket
or DICOM data. The fixture loads the pure module directly, matching the existing
`test_patient_study_set.py` isolation strategy; the initial fixture import-chain failure was
corrected before recording the meaningful pre-fix result.

| Verification | Result |
|---|---|
| New guard before production change | 3 failed, 2 passed, exit 1: successful duplicate/leading-zero rows lacked `display_key`; early import failure raised `UnboundLocalError` |
| New guard after change | All 5 passed, including partial inventory failure and empty/query-error behavior |
| Focused identity, Local, collision and thumbnail selection | 120 passed, exit 0; direct pytest with `--reruns 0` |
| Plugin mirror verification | 462 matching pairs, zero drift, exit 0; this Home mixin has no mirror |
| Source live / packaged application | Not performed; pending |

The final focused selection was `test_home_local_thumbnail_projection.py`,
`test_local_offline_contract.py`, `test_patient_study_set.py`, `test_thumb_batched_render.py`,
`test_thumbnail_unified_pipeline.py`, `test_series_ref_authority.py` and
`test_series_number_collision.py`. No speedup, full Unify completion, right-panel action fix,
or crash resolution is inferred from these results.

Rollback removes the three added lines in the Home method; no persistent data changes are
involved. The next slice still needs a complete study/series action envelope, including a test
for identical raw numbers in different studies. Do not replace the right-panel ordinal with a
study-local key alone: that would permit collisions in the manager's card map. The generic
patient-viewer key precedence, both render schedules, anti-flicker gate and Download Manager
routing were not changed by this prerequisite. Live acceptance should repeat Local preview and
open for a duplicate-number still/cine study, a unique-number study and a multi-study patient
with the network disconnected; the human starts the source application once.

## 2026-09-14 implementation record: shared multi-study projection (OPT-35)

**State: contract-preserving extraction automated-verified; full action route pending.**

The user emphasized that prior fixes for multiple studies, absent labels/numbers and
repeated series names must survive Unify. Fourteen synthetic compatibility cases therefore
ran against the actual controller method before runtime edits; all passed. The study-slot,
offset-key and per-entry path loop was then moved into
`PacsClient.utils.series_identity.build_multistudy_series_projection`, and the controller
now delegates once. The original loop was deleted. No second implementation or fallback
loop was introduced. The pure helper uses existing canonical series-field accessors.

Responsibilities remain explicit:

| Boundary | Authority retained |
|---|---|
| Absent server SeriesNumber | `modules.network.series_identity.normalize_series_entries`, per study, reserved band below 1,000,000 |
| Duplicate number within one study | `patient_study_set.allocate_series_display_keys`; persisted folder/path remains independent of the UI alias |
| Patient-tab multi-study slot/key/path projection | `series_identity.build_multistudy_series_projection`, consuming already-normalized records and prior owner slot order |
| Patient-tab presentation | Controller's exact history-first/numeric sort policy and single-study gate |
| Cross-domain read-only identity | Existing immutable `SeriesRef`; projection dictionaries belong only to their patient-tab owner |

Missing or identical descriptions never participate in identity. The normalizer, allocator,
folder naming, decoder, geometry and source DICOM bytes were not modified. The helper copies
the prior slot list and each entry; it does not access files, SQLite, the socket or Qt.
Explicit external import paths win over derived storage paths. The historical leading-zero
rule is preserved: the raw label/path retains `02`; the multi-study UI key is numeric.
New studies append after existing admitted slots. Existing study-removal behavior is preserved.

The final new guard has 15 cases (the original 14 plus input ownership). The old stateful
test formerly copied the controller's key/path algorithm; it now calls the shared production
helper, retaining its independent key/UID/slot oracles and adding an expected-cardinality
check. It passes with 150 configured examples and up to 40 state transitions. One old
source guard initially failed because the path-stamping code moved; it was converted to
assert the actual primary-study path, raw number and slot, plus controller delegation.
The final focused suite passed **171 tests, exit 0**; the property invocation passed
**1 test, exit 0**. All **462 mirror pairs match, exit 0**. Both edited runtime files already
ship as core source and have no plugin mirror; no new module or dependency was added.

This is equivalence evidence, not a fail-before bug-fix claim or a measured performance gain.
Rollback restores the helper/controller extraction hunks together. The next source live run
must exercise Local and Server multi-study opens, both same-study and cross-study duplicate
numbers, empty descriptions, normalized missing numbers, still/cine counts, later previous-exam
merges and reopening a single-study case. Confirm every selection resolves to its own study
and exact folder, with unchanged displayed labels, ordering and frame counts. The user starts
the source build once. Live acceptance and an installed build remain pending.

The home right-panel action envelope and the identity-aware adapter to viewer/Download Manager
remain the next routing slice. A home panel must not send its own slot key directly into
another tab: keys are scoped to their owner's lifetime, so the target must resolve study/series
UID first. The shared projection is preparation for that boundary, not evidence that it is
already migrated.

## 2026-09-14 source-run evidence (read-only log review)

The human started one source process. The inspection cutoff was 10:26 local time;
the viewer snapshot ended at 10:21. No patient identifiers or raw log excerpts are
copied here. This is a bounded observation, not a general clean bill of health.

| Observation | Supported interpretation and remaining gate |
|---|---|
| 15 first-image-visible events, including secondary-study offset keys; no logged multi-study rebuild failure | Multi-study viewing was exercised. These are render events, not 15 unique studies or end-to-end click latency measurements. Missing/duplicate-label, hard-offline and mixed still/cine coverage is not established. |
| Two UID mismatch rejections; matching render and image followed each within 0.5 s | The safety gate prevented a wrong-series render. The stale attempt's origin remains unproven; OPT-35's zero-SKIP oracle has not passed. No guard retirement is authorized by this run. |
| 99 main-thread timer gaps; median 158.3 ms, p95 480.6 ms, max 3730.7 ms | Timer gaps, not isolated operation durations. P95 uses sorted index floor((N-1)*0.95). No matched pre/post workload exists, so no improvement percentage is claimed. |
| Two gaps above 1 s: 3730.7 and 1931.2 ms | Startup/UI construction; samples include window show and theme application. Separate startup workstream, not evidence against the pure projection or proof of server latency. |
| Main process remained alive after one native `0x8001010d`; zero access violations in the inspected session portion | Non-terminal record in this run. The log's phrase "fatal exception" alone does not establish a crash. No Windows Event Log or packaged-run acceptance was performed. |
| One download ERROR says cancelled/preemption | Priority cancellation, not a demonstrated transport/server failure. Completion correctness still needs an independent completion oracle. |
| 25 `DM-CONVERGE-MISS` events | The status update could not find its table row. Existing OPT-04 debt; repeated downloading is not established by this count. |
| One visit-status persistence-false warning | Persistence remains unverified for that operation; keep in OPT-58, separate from thumbnail identity. |

Follow-up source review reconfirmed that `extract_series_info_from_thumbnail`
discards already-supplied study/series identity, exact storage path/key, display key
and display-frame count. Both immediate and progressive card creation consume this
lossy projection. Preserve those supplied facts at this shared boundary before changing
action routing; never overwrite the file/object count with the cine frame count.

Another documentation/code discrepancy remains separate: current `display_thumbnails`
calls `clear_content()` before its timer-deferred rebuild, despite the historical May
anti-flicker contract. Neither renderer currently owns that clear. A future scheduling
slice must reproduce the visible-gap/reentrancy behavior before moving it, preserving
signature state, generation cancellation and Windows input-dispatch deferral. Do not
claim the historical repaint-suppressed swap is implemented in today's dispatcher.

## 2026-09-14 implementation record: lossless card metadata prerequisite

**State: fixed and automated-verified; live acceptance and action migration pending.**
The common `RightPanelWidget.extract_series_info_from_thumbnail` boundary dropped
metadata that Local already supplied correctly. Both card schedules lost study/series
UIDs, raw/display/storage identity and the cine frame count. A synthetic real Qt card
therefore showed `2 images` for two objects containing 420 frames. This was a card
projection defect, not evidence of a codec, DICOM-byte or viewer decoding failure.

The existing method now copies a fixed allowlist of supplied fields into its detached
result: `study_uid`, `series_uid`, `series_instance_uid`, `_orig_series_number`,
`display_key`, `folder_key`, `series_path`, `display_image_count`, and
`pixel_instance_count`. Existing alias/default precedence and number types stay intact.
No paths/UIDs are inferred from card position, no image bytes/patient attributes are
copied, and object counts remain distinct from frame counts. No new I/O, scan,
decode, thread, timer, dependency, feature flag, module or schema was added.
The existing common method is the sole projection for both render schedules.

`tests/code/ui_services/test_right_panel_metadata_contract.py` compiles the actual
projection and both render methods with synthetic card-construction boundaries; a
separate case builds a real offscreen Qt card. Before runtime editing: **4 failed,
4 passed, exit 1** (both schedules lost identity, an alias/count was dropped, and
the visible count was 2 instead of 420). Afterward all eight pass. The focused
selection including Local, multi-study, collision, SeriesRef, missing-number,
thumbnail layout/active-state and existing render-policy guards is **205 passed,
6 existing SWIG deprecation warnings, exit 0**, with `--reruns 0`.
All **462 plugin mirror pairs match, exit 0**; the changed Home source has no mirror.

**Deliberately not changed:** the manager's opaque numeric-key precedence, Home card
ordinals and signal signatures, drag MIME, direct click/download handlers, cache
signature, render scheduling, lifecycle, and Fast/Advanced/VTK execution domains.
This is not an immutable action-envelope implementation and not a correction of
Home-to-viewer routing. The incomplete signature may still suppress a same-path
semantic refresh; this fix guarantees metadata on a card that is actually rebuilt.
No runtime speedup is claimed. Rollback removes only this metadata-copy block and
its docstring change; no persistent data migration is involved.

The already-running source process predates this patch. Remaining live gate: after
the human's next source restart, select a different patient then reselect the Local
mixed still/cine case; check the fresh cards show 25 and 420 while retaining two
cine objects internally, with unchanged labels/grouping. Repeat a large progressive
preview and a single-study case. Hard-offline and installed-runtime checks remain
separate. Next routing slice must create the immutable action envelope and resolve
it at the destination by study/series UID; never forward a Home ordinal or Home-owned
slot key as a patient-tab handle.

## 2026-09-14 follow-up source run (10:57 startup, inspected through 11:06)

This source launch followed the card-metadata patch. Ten first-image-visible events
and ten matching identity-gate evaluations were recorded, with zero identity SKIPs
and no ERROR/CRITICAL in the three inspected application/viewer/download channels.
There were 51 main-thread timer gaps (median 173.3 ms, p95 465.8 ms using the prior
floor-index definition; max 1982.8 ms during UI startup), plus a sampled 436.9 ms
gap in multi-study sidebar layout. Separate debt persisted: 19 DM missing-row
events and five visit-status persistence-false warnings. One non-terminal native
COM record occurred; no access violation was present in this session portion.

These are not matched-workload improvement metrics. The logs do not record the
visible Home-card frame-count text, so they do not prove the 420-frame label live
gate. No patient identifiers are included here. The click cutover below happened
AFTER this run; none of these observations verifies the new click route.

## 2026-09-14 implementation record: Home click identity cutover

**State: automated-verified; bounded to existing open patient tabs; live pending.**

The supported sequence is now:

1. Both render schedules call one `_create_action_thumbnail` implementation.
2. A render-owned manager maps its card positions to frozen `SeriesActionIdentity`
   values containing study/series UIDs plus original/display/storage/path hints.
3. A click is posted through a receiver-bound Qt timer after input dispatch.
   Clearing/replacing the render invalidates its token, including already-posted
   actions; destroyed receivers do not receive the timer callback.
4. `seriesActionRequested` reaches the existing Home handler, which delegates to
   `HomeTabService.show_series_action`. The old never-populated study-info lookup
   and nonexistent direct-downloader call have been removed from this handler.
5. The service resolves BOTH UIDs against existing patient-tab series maps. Exactly
   one tab and one decimal-key series must match. Primary-bucket fallback follows
   the existing rule for an entry with no explicit study UID. After activation it
   rechecks membership, liveness and identity before calling the public
   `change_series_on_viewer` entry point with the DESTINATION's own key.

`SeriesActionIdentity` is a pre-viewport value, not another disk/cache authority:
its hints must never overwrite the destination projection or `SeriesRef`. A
`SeriesRequest` cannot be minted by Home because the target viewport/patient context
is not yet known. No UID is inferred from a label, series number or current selection.
Missing identity, missing/closed tab, missing series and ambiguous destinations are
not routed. This slice does not auto-open patients or fetch metadata to fill a gap.
`[HOME-SERIES-ACTION] result=requested/not_routed/error` logs the boundary outcome
without raw identity fields. Requested means handed off, not image-visible/completed.

### Safety prerequisite discovered during the cutover

The prior plan put full semantic render-signature work later. Four new failing
guards showed that identical PNG paths could suppress a changed action UID,
display key, storage key or exact path. Enabling captured actions without addressing
that dependency would leave stale clickable metadata. The identity-only part of
the signature work was therefore advanced into this cutover: it compares the SAME
frozen value used by actions, not a second field list. Identical action metadata
still coalesces. No disk stats, file hashing or pixel reads were added. Count-only,
description/version and same-path pixel refresh remain a separate pending visual
contract. The pre-deferred-clear scheduling discrepancy is also still pending.

### Regression evidence and scope limits

- Before runtime edits: the first four real-behavior tests failed (both Qt card
  schedules emitted ordinal strings, a cleared card already dispatched its action,
  and the Home handler never reached the service); seven destination tests failed
  because that API did not yet exist. Total 11 failures, exit 1.
- Before the signature prerequisite: four additional identity-coalescing guards
  failed, with the remaining 23 tests in that focused run passing, exit 1.
- Final action guard file: 22 cases, including frozen values, duplicate numbers
  within/across studies, absent descriptions, exact external path preservation,
  leading-zero destination keys, incomplete/foreign/ambiguous rejection, render
  supersession and closure/identity changes during activation.
- The metadata harness now executes the extracted card factory as well as the
  real render methods. No metadata assertions were removed.
- Two Windows input-dispatch source-window pins were converted to real-method
  behavioral tests: no build while gated, 16 ms repost, stale-generation no-op,
  and retained maximum deferral bound. The immediate test's obsolete quarantine
  entry was removed only after an observed XPASS; no new quarantine was added.
- Final adjacent selection: **238 passed, 6 existing SWIG deprecation warnings,
  exit 0**, reruns disabled. Stateful production projection: **1 passed, exit 0**
  (150 configured examples, up to 40 transitions). **462 mirror pairs match,
  exit 0**; the five changed core runtime files have no plugin mirror.

The adapter scans existing in-memory tab/series maps; it does not perform network,
database or disk lookup, create a downloader, or change DICOM bytes/geometry/decode.
The normal viewer entry still owns loading and its existing DM interactions; this
is NOT proof that all downstream legacy priority/I/O paths are repaired or that
download completion is correct. No latency improvement is claimed.

Deliberately unchanged: generic card key precedence and numeric drag payload;
patient-viewer clicks; paired-series policy; all backend implementations; download
queue/progress/retry; manager disposal; and both render cadence strategies. The
legacy `thumbnailClicked(str)` signal remains for compatibility, but normal Home
cards and Home layout wiring use the typed action signal. Home drag/retry remain
known incomplete paths, not newly verified features.

Rollback the five runtime cutover hunks together (action value, card factory/signal/
signature, tab service and two Home mixins), retaining prior metadata/projection
fixes. There is no data migration, feature flag, new module or dependency. No build,
commit or deployment was performed.

Next source live gate, after a human restart: open a single-study and multi-study
patient, return Home, click cards with repeated/absent labels and confirm the
existing tab shows the intended series. Repeat Local/external-import still/cine
with the network disconnected, rapid A-to-B selection, tab close before callback,
and a large progressive preview. A missing/ambiguous open target must not select
another series or start a competing download. Native installed acceptance remains
pending. Next implementation slice is the separate Home drag/retry and coordinator
handoff; do not treat this existing-tab click seam as completion of that migration.

## September 14 live receipt: cached Home action identity gap

**State: Home-click live gate FAILED; no production edit in this verification turn.** This
receipt supersedes earlier login/connectivity blockers, not the bounded automated test evidence.
Source launch: 12:10:46/47 local, main PID 1090784, redirector PID 1097732, base `5d3c72d5` plus
the documented dirty click/metadata/projection patches. Login was human-operated. Local-client
`ping` and `list_actions` succeeded; no MCP registration, LAN gateway, or external AI was used.

### Observed workflow and control comparisons

- Bounded Server MR search, September 13-14: 54 rows. No returned row advertised multiple study
  UIDs, so none was claimed as a verified multi-study case. `CASE-MR-A` was selected for a
  single-study control (18 primary series); actual tab metadata confirmed one study/no previous
  exams. Real identifiers and pixels are not copied into this receipt.
- `select_patient` and `open_patient` reached the production handlers. Returned Home for the
  same case. The right panel showed Series 2 with 11 images. An actual native click on its image
  selected the card but left Home active; the read probe returned `NO_ACTIVE_TAB`. No
  `[HOME-SERIES-ACTION]` result appeared in the run's inspected log portion.
- Case-specific logs show a first socket fetch followed by `right_panel_cache_hit` renders.
  `_hp_search._build_cached_thumbnail_payload` returns visual/count fields but neither UID.
  A one-off isolated probe compiled and executed THAT method with a synthetic DB module and
  synthetic thumbnail-list helpers. Input contained `study_uid` and `series_uid`; output
  contained neither, while image count 11 was preserved. No live DB or DICOM/PNG file was opened
  by this probe. `_load_thumbnails_for_downloaded_study` also omits per-card study UID on source
  inspection, but this receipt does not attribute the observed cache-hit render to that helper.
- The new `SeriesActionIdentity.from_metadata` requires both UIDs; missing identity leaves no
  captured action, so its callback returns before Home's service logging. This is an incomplete
  producer migration, not evidence that UID safety should be relaxed. The existing Qt card tests
  supply complete metadata and did not cover the live cache producer.
- Control: native patient-tab activation, then MCP `change_series` for destination key 2 in
  viewport 0 rendered 11 images. `get_viewport_context` study/series UIDs matched the current
  tab and its expected series row. The actual rendered image was inspected.
- MCP `scroll_slices(index=0)` moved visible image 6 -> 1 (zero-based index 5 -> 0). Actual mouse
  wheel then moved image 1 -> 2 (probe index 1); image changes were visually observed.
- MCP key 3 in viewport 1 also rendered 11 images; both UIDs matched. This separates the Home
  dispatch failure from downstream decode/render for these two series. It does not prove all
  images, formats, previous studies, cine timing, or offline behavior.
- Native drag trials were **INCONCLUSIVE**: the blank target did not load, and a later trial
  against an initialized target left a visible drag ghost/highlight without completed handoff.
  Escape canceled the unfinished drag and restored normal state. Do not label this a confirmed
  product drag regression or a passing OLE test; a completed native-drop reproduction is needed.

### Health, limitations and next seam

The inspected app/viewer/download log entries from 12:17 onward contained no ERROR/CRITICAL
lines and no identity-gate SKIPs; the source main process stayed alive and responded to probes.
These observations do not prove absence of stalls/native faults or download completion. No
latency improvement is claimed. The existing automated baseline remains 61 focused tests passed
in the preflight rerun; no fresh runtime fix or fail-before/pass-after guard landed here.

Next: add a producer-to-card/action behavioral guard, then preserve authoritative UID metadata
through the existing cache producers. Audit filename/number lookup ambiguity (duplicate numbers,
missing labels, external paths and frame/object counts) before selecting the consolidation seam.
Never fill identity from an unrelated current selection or resurrect the dead direct downloader.
Re-run the failed real Home click, then verified multi-study and cine/offline cases. Keep the
broader Home drag/retry/coordinator and lifetime work separately gated.
### Producer-verified Local catalog facts (2026-09-17; code verified, live pending)

The next catalog-first slice extends the existing DB metadata index rather than
creating a parallel manifest. Import and Download Manager publish immutable pixel-
object/display-frame totals only after complete destination/index success, bound to
the exact managed series-directory revision. Home and patient Local projections may
skip the full header scan only while that revision and schema remain valid. Legacy,
external, partial, pre-existing and changed rows keep the original verifier.

Pixel/displayability verification is independent from geometry metadata indexing.
Both Local projections use the same batch writer after a legacy worker scan, carrying
the scan's directory revision into a compare-and-persist check. A concurrent managed
folder change rejects the backfill; it never produces a stale fast-path record.

This does not collapse the intentional local-first/server-reconciliation producers,
the immediate/progressive cadence policies, or Fast/Advanced/VTK domains. It also
does not promote `SeriesStateStore` from its current shadow state or confuse a Local
catalog fact with download/display completion. Exact Study/Series UID and persisted
`folder_key` remain storage identity; owner-local `display_key` allocation still
handles duplicate/missing/large SeriesNumber values.
