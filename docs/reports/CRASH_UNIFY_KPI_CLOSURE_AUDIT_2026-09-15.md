# Crash closure, Unify acceptance and KPI audit - 2026-09-15

## 2026-09-18 cross-PC classification and current stop condition

This dated readout updates classification, not root-cause closure. The current developer
log set spans September 3-18 and the archived client application logs span September
6-13; their raw totals are not comparable rates.

- The recent developer process-exclusive native files contain **12 access-violation
  records**. PID/session correlation places all 12 at normal application shutdown, next
  to close/lifecycle/finalization markers. This narrows the affected boundary to native
  teardown/lifetime; it does not identify the responsible QObject, worker, Qt/VTK owner
  or callback.
- The same developer set contains **27 COM `0x8001010d` records** and no Fatal Python
  marker. Observed processes remained responsive after sampled COM records, so they are
  non-terminal evidence unless a session proves otherwise.
- The archived client legacy native log contains **12 access-violation records** and no
  COM record. Its shared legacy format does not provide enough session attribution to
  claim the same shutdown cause.
- Windows Application evidence for the developer period contains 14 filtered Event 1000
  records and 23 Event 1001/WER records. These are records, not 37 independent crashes;
  Windows may emit more than one event for one failure.
- Application-log classification finds 3,017 socket-send ERROR lines among 3,243 in the
  archived client window, and 92 among 179 in the current developer window. This locates
  a large error family at the request/network/download boundary but cannot distinguish
  server, transport or client retry behavior without matched server logs.

Decision: shutdown/native lifetime is a release stop condition and owns its correction
here. It must not be attributed to Unify, Advanced, VTK or Thumbnail code without a
session-specific stack/owner transition. The next acceptance run follows U0 in the
[canonical Unify ledger](../plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md#current-execution-ledger---2026-09-18)
and ends with normal exit. If an access violation recurs, pause later U1-U5 behavior
changes and identify which registered owner remains pending/unknown at finalization.
Do not add blocking GUI-thread joins or speculative destruction order changes.

**September 17 completed-load follow-up:** the 8/104 incident now has synthetic
reproductions and coordinated shared-delivery / Advanced-cache corrections. Twenty-five
shared guards pass; fresh native tab-switch acceptance is still required. The current
23:40 process predates these changes. Neither this code gate nor 467 matching mirrors
closes native crash, cold-thumbnail, MPR latency or installed acceptance. A separate
release stage-config parity check remains red. See the
[authoritative receipt](UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-completed-load-tab-handoff-opt-35--opt-60).

**Latest 2026-09-17 acceptance update:** source PID 739276 (September 16, 23:40:15)
executes the bounded builder; Local grouped admission still takes 6.570/27.004 s.
The subsequent shared inventory persistence patch is code-verified, not loaded in
that process. Public viewer probes and download completion are unchanged. Source
cold/reopen/restart GUI/KPI, first uncached catalog latency, native stress/exit and
installed gates stay open. See the [current receipt](UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-17-local-inventory-persistence-opt-58--opt-60).
This supersedes the historical old-PID bootstrap status below, not its remaining
acceptance requirements. No terminal crash was observed in the bounded 23:40 window;
one non-terminal main COM event is not a clean-zero-native-exception claim.

**Later 2026-09-16 code correction:** cached/grouped thumbnail construction is now
scheduled in bounded GUI turns with worker image/readiness preparation and fixed
header/card reservations. This addresses the identified shared handler bursts,
not Advanced/MPR rendering or native crash closure. Synthetic code/cost evidence
is in the [OPT-58/60 receipt](UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-bounded-cached-sidebar-build-opt-58--opt-60).
PID 1197880 predates this patch; source restart and GUI/KPI acceptance are pending.

**Fresh 2026-09-16 22:47:00 source receipt:** main PID 1197880 remains alive and
answers documented test-control ping/actions after the user workflow. Scoped logs
through 23:04:47 contain no ERROR/CRITICAL (all PIDs). Shared reads of this session's
eight native sinks find zero access-violation/fatal-Python markers; main sink has
one COM 0x8001010d event and remains responsive, so it is non-terminal evidence,
not a clean-zero-native-exception claim. FileInfo length was stale/zero despite
readable main-sink content: inspect shared-read contents, not size/mtime alone.
There is no shutdown/installed/stress or all-crash-closure acceptance. Five current
download tasks complete and 150 count checks pass; see the UI-stall report's 22:47
receipt for liveness success and remaining 3.908/2.566-second shared thumbnail stalls.

Unify readout, **2026-09-16 20:51:54 source session**, main PID 1207756: current
session-specific native sink contains one COM `0x8001010d`, zero access-violation and
fatal-Python markers. Its filesystem last-write time is 20:52:28; do not promote that
mtime to a precise exception timestamp or terminal-crash count. The same source remains
responsive to documented ping/actions afterward. App/viewer/download severity scans
across rotations find no ERROR/CRITICAL during 20:51:54-20:58:29 (all PIDs). This remains
unclassified non-terminal evidence, not proof of crash closure or a VTK root cause.
The shared-path/header KPI receipt is in the UI-stall report; no native-handler or
Viewer implementation was changed by this review.

VTK acceptance handoff, **2026-09-16 17:58:46 source session**: the session-specific
source-child native log again contains COM `0x8001010d`; existing control ping/actions
and read-only viewport query succeed afterward. No actual ERROR/CRITICAL in inspected
app/viewer/download logs through approximately 18:04. This remains unclassified native
evidence, not a terminal VTK crash. No process or handler changes in this review.

Latest VTK-task readout, source session **2026-09-16 17:14:46**: native COM
`0x8001010d` recurs in the session-specific source-child sink. Existing control
ping succeeds afterward; no terminal-crash attribution is supported. Through
17:23:40 app / 17:22:57 viewer, no actual ERROR/CRITICAL severity occurs there.
Downloader has one `Download cancelled (preemption)` ERROR at 17:15:36; do not
classify that cancellation as a VTK failure. No corrective changes in this review.

## VTK-review handoff: 16:51:12 source session on 2026-09-16

Session-specific native log records Windows COM exception `0x8001010d`; the same
source child remains alive/responding afterward. Do not classify it as a terminal
VTK crash. A background stack includes `resident_service.start` / `_ensure_ready`
and `advanced_analysis_startup.prepare` while spawning a subprocess; concurrent
stack presence alone does not establish causality. No process recovery or native
handler change was made. Actual viewer log severity contains no ERROR/CRITICAL in
the inspected window; text `-> CRITICAL` refers to download priority, not severity.

## Handoff from VTK review: 2026-09-16, 15:01 source session

**Owner routing requested by the user:** the VTK conversation records these findings
for this workstream; it does not implement general KPI/native-crash corrections.
No acknowledgment or completion by another conversation is implied by this handoff.

- `tools/kpi_dashboard.py::_probe_latest_run` selects `max(run_id)` lexically. The
  dashboard's three PASS records came from `2026-05-28-multibuild-synth.jsonl`, dated
  2026-05-28 under `run_id=source-run`, not the fresh September 16 session. Its 42-key
  schema alignment remains valid, but the displayed latest-run health is not current
  GUI performance acceptance. Investigate chronological, provenance-aware selection
  and explicit missing-current-run reporting within the KPI workstream.
- Two fresh first-display KPI records contain `ttssd_ms`, `widget_creation_ms` and
  `first_render_request_ms` equal to -1.0. Treat as unavailable, not zero or PASS.
  Coordinate any instrumentation inside the VTK viewer with the VTK workstream.
- The new main-process native sink recorded one COM exception `0x8001010d`; its
  process remained alive and ping succeeded. No Python-fatal record or watchdog dump
  was present in that sample. Do not classify it as a terminal crash or as VTK-caused
  without attribution. Historical dashboard inventory (428 records) is not a fresh
  crash count. Review the session-native evidence under the existing native contract.

Evidence and limits: [VTK review, fresh source log receipt](VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md).
The sampled window was approximately 15:01-15:06 local time. No runtime changes or
new crash-closure claim were made for this handoff.

## Fourth corrective follow-up: shutdown admission and completion observations

**Status:** a reproduced central-manager reentrancy defect is code-fixed; shutdown
observability is extended. Fresh-source close/exit acceptance and the original
native-crash closure remain OPEN. The currently running source predates this slice;
its responsiveness cannot certify these changes. Human fresh launch/sign-in has
been requested. The prior native-header publication hardening also needs that run.

### Cause and safest seam

`LifecycleManager.shutdown_all()` previously allowed nested/concurrent invocation.
The inner empty run reset `_shutting_down=False` while the outer callback was still
executing, admitting late resources into teardown. Two synthetic behavioral guards
reproduced this; no evidence establishes that this was the cause of the recorded
native access violations. The existing manager now ignores an overlapping invocation
without releasing the outer guard. A `finally` restores state for exceptional unwind
without swallowing `BaseException`. Normal subsequent use remains supported.

The old LIFO callback order, resource tuples, advisory budgets, error dictionary,
and caller thread are preserved. There is no new wait, join, event pumping, stop
deadline, teardown reorder, GC change, hard-exit policy, or rendering/download change.
Blocking drain on the GUI and speculative Qt/VTK destruction changes were rejected:
the present evidence supports admission repair and observation, not those changes.

### Evidence contract

- `[LIFECYCLE_SHUTDOWN]` emits callback begin/return and owner observations, with
  ordinal, fixed resource name, outcome and separate callback/probe durations.
  Returned/over-budget/error is distinct from complete/pending/unknown/probe_error.
- An optional read-only, nonblocking completion probe is sampled once after each
  registered callback. Other owners remain explicitly unknown. Results contain only
  primitive copies; the manager does not retain owner/probe closures after the run.
  Exceptions in a probe neither certify completion nor abort remaining callbacks.
- Consultation is the first observed producer. Read direct QApplication-owned
  pollers, including identity-replaced owners awaiting worker finish. Completion
  means stopped timers and queued scan-finished delivery processed, not merely
  `isRunning()==False`. It does **not** certify deferred QObject/native deletion.
  No optional plugin import, network/DB/filesystem read, or widget-tree walk is added.
- `[SHUTDOWN_FINAL] phase=before_log_shutdown` records hard-exit **intent** while
  logging is available, with `owner_completion=unverified`. The misleading late
  `all cleanup done` claim is removed. Existing `os._exit(0)` and its escape hatch
  remain unchanged; this breadcrumb is not proof the process exited successfully.

### Verification, packaging and remaining gate

Nine initial manager cases failed before implementation, including real nested and
concurrent state failures. Three further fail-before cases cover queued producer
completion, replaced-owner aggregation and final breadcrumb ordering. Final manager
suite has 12 cases, adding probe-duration separation, advisory over-budget semantics,
late-probe rejection and weak-reference ownership release.

Direct offscreen pytest with reruns disabled: **105 passed, 4 build-marked cases
deselected, exit 0**, 11.34 seconds. Selection: lifecycle observations; consultation
lifecycle; startup/shutdown; shutdown initiators; MainWindow close confirmation;
close-path hang visibility; process-exclusive native isolation; MCP native health;
safe builder materialization and package guards. The two consultation payload files
were synchronized using the standard tool; **465 mirror pairs match**, exit 0.
No full build, release, installed-client, broad-repository, or matched KPI pass.

Live gate: one fresh source process, human sign-in, `ping` then action inventory,
representative open/close and normal application exit; correlate callback pairs,
pending/unknown producer observations, process-exclusive fault evidence and actual
process exit. Repeat active-work/heavy workflows only within the agreed safe test
scope. Do not close the crash workstream from callback return or a clean short smoke.

Rollback: reverse only this slice's manager admission/observation changes,
consultation probe/property plus MainWindow wiring, and finalization breadcrumb;
resynchronize the two consultation mirrors. Preserve all earlier poller stop/generation
fixes and native capture changes. No schema, data migration, dependency, module,
configuration family or feature flag was added.

## Third corrective follow-up: process-exclusive native capture and reader cutover

**Current status:** capture and its active readers are migrated and source-startup
smoke-tested. One final publication-order hardening change was made after that
source launch and is code-verified only; recheck it on the next fresh source run.
Shutdown owner completion and prevention of the original Qt exit
crashes remain OPEN. This supersedes the reader-migration pending status below,
not the historical incident evidence or the outstanding download-wait assertion.

`PacsClient/utils/native_fault_log.py` now exclusively creates
`native_fault.<pid>.<32-hex-session-token>.log` per process run. A second enable in
that process reuses the live handle; PID reuse gets another filename. Exclusive
creation refuses collisions rather than overwriting evidence or falling back to
the shared sink. Default-on `AIPACS_NATIVE_FAULT_LOG`, early main entry, the
process-lifetime handle, all-thread native capture and existing watchdog remain.
Unwritable paths/setup failures do not break startup; an unpublished failed handle
is closed. The ready-looking session header is published only after successful
native enable; once enabled, retain the handle even if header publication fails.
No logger/callback is added to the native-fault path, and no directory
enumeration is added to GUI startup or viewer work. Historical `native_fault.log`
is retained; new capture no longer writes it. No automatic retention/deletion.

One import-light discovery function recognizes only the legacy filename and the
exact exclusive format. Generated filtered reports are excluded. External readers
retain old evidence as unattributed and validate a process file's single session
header against its filename PID. They never infer legacy ownership from an adjacent
header. Directory probes cap recognized sources at 256 and aggregate samples at
16 MiB; incomplete/oversized evidence fails closed rather than becoming zero.
Future children are included from byte zero in a running observation window.
File identity plus the last observed prefix hash catches deletion, replacement,
truncation and loss of previously observed child records. A briefly unpublished
child header is inconclusive and can be retried without losing its records.

### Coordinated consumer changes

| Consumer | Current contract |
|---|---|
| External MCP `snapshot_health` / `run_scenario` | Legacy directory anchor discovers both formats; cumulative windows include new children. Process records include safe source filenames to distinguish PID reuse. No raw stack payload is returned. |
| `filter_native_fault.py` | Default discovers all supported sources; `--in` still selects one. Preserve following stacks and source-file boundaries; reject output aliases and native-sink output names. |
| KPI dashboard / historical May extractor | Use bounded multi-source inventory; explicitly inconclusive for retrospective/terminal-crash claims. No green verdict from missing logs or file mtime. |
| Native GUI guards | Use real byte-window baselines; detect new child faults and missing evidence. Merely adding a session header is not a crash. Python fatal/watchdog records are included. |
| Raw in-app `count_native_faults_since` | Registered compatibility action now returns `ok=False`, `EXTERNAL_NATIVE_PROBE_REQUIRED`, null counts, and instructions for the external probes. This is an intentional API correction: no filesystem read on the Qt bus and no false zero from the wrong path. It is not a new asynchronous in-app counter. |

The raw adapter's EchoMind payload mirror was synchronized by the standard tool;
**465 pairs match**. No new runtime module, external dependency, feature flag,
installer profile, DB migration, encoding, download state, rendering or shutdown
behavior was introduced. The COM tracer's explanatory comments now distinguish
candidate correlation from proof and refer to process-scoped evidence.

### Verification and rollout limits

- Six initial isolation/consumer guards failed before implementation (exit 1).
  Two additional guards reproduced loss of a child's previously observed records
  and the raw GUI-bus I/O boundary before their corrections (exit 1). An overly
  broad test monkeypatch initially interfered with pytest reporting; it was scoped
  and rerun before using the two-failure receipt as evidence.
- A final adversarial guard also failed before correction: the session-start header
  was written before `faulthandler.enable` succeeded, so failed setup could leave
  ready-looking evidence. Native enable now precedes header publication. This
  additional guard is code-only relative to the 22:05 launch below.
- The new isolation file has 19 tests, including two real hidden Python children
  writing harmless `faulthandler.dump_traceback` output into synthetic temporary
  logs. No crash was deliberately triggered. Tests use the child's self-reported
  PID, not the Windows venv redirector PID. Frozen-flag behavior, collision refusal,
  failure cleanup, legacy coexistence, dashboard/filter/native-GUI helper consumers
  and source publication/rewriting limits are covered.
- Direct final focused/adjacent verification: **120 passed, 4 deselected, exit 0**,
  16.62 seconds (the earlier selection had 119 passes). Syntax and scoped diff checks
  pass; no lint or full-repository claim. The four deselections are explicitly `build`-marked package-builder
  cases, not passes. Three safe materialization guards ran. No full build or installed
  acceptance was attempted. Source/native/watchdog/control and prior parser guards ran.
- User explicitly requested `run it now` after the old source instance was absent.
  Launched one `.venv` source app at **22:05:08**, redirector PID 1099320, actual main
  PID 1110808, with the local test bridge enabled and production gateway disabled.
  No authentication automation or installed executable. Home was observed signed in,
  empty of patient rows; native menu expand/collapse worked and original layout was
  restored. No patient open/search, clinical write, download, cleanup or application
  shutdown was performed.
- Current bridge: ping and **77-action** discovery pass. The main's new exclusive
  file contains one startup COM `0x8001010d` record; the same process subsequently
  responds, so this observed event is non-terminal, not evidence of a fixed crash.
  No Python-fatal/watchdog record in that new file at the check. Two read-only health
  assertions plus final check passed over a roughly **0.40-second** post-startup
  window with no new native bytes. Both formats were observed together. The live raw
  command returned the documented explicit redirect/null count, proving the new
  adapter is loaded. This is bounded startup/capture acceptance, not long-run,
  heavy-import, production-child, shutdown or clinical viewer acceptance.

Rollback must keep producer and readers coordinated. Prefer retaining compatible
readers if reverting the producer; never restore a shared-only zero-count consumer
while the exclusive producer is active. The existing `AIPACS_NATIVE_FAULT_LOG=0`
disables observation only, not a crash fix; missing evidence must remain inconclusive.
Collect the entire native-log family in support bundles. Large histories require an
explicit evidence/archive strategy; do not silently delete logs to satisfy a limit.

**Next boundary:** instrument actual completion of shutdown owners before changing
Qt/VTK destruction or hard-exit policy. The Preview/DM convergence and GUI metadata
I/O findings remain separate. The scenario download-wait return is still ignored
and must be repaired before certifying a whole download soak.

## Second corrective follow-up: MCP health assertions must actually assert

Consumer review found another prerequisite before the native-sink migration:
`run_scenario` obtained a baseline but never used it, and its `assert_health`
pseudo-action discarded the response without checking a limit or recording a
failure. Even final native evidence could be unavailable with no scenario failure.
The in-app `SystemCommandAdapter` derives its log path from the EchoMind module
tree rather than the application data root; its `minutes` input is ignored, and
`since_iso` only qualifies file mtime rather than selecting dated records. It also
reads the file synchronously on the command bus/Qt thread. Therefore the old MCP
health result is NOT evidence of a clean run. These are pre-existing testing defects,
not proof that the recent Unify code introduced a clinical crash.

**Bounded correction:** the external MCP wrapper now uses
`tools/diagnostics/native_fault_probe.py`; it does not dispatch the legacy native
log reader into the app. A scenario captures an immutable byte baseline, requires
a capture-start marker for the live resource-probe PID, and compares cumulative
appended records. Same-PID presence does not assign interleaved dumps to that PID.
Later checks require the same responding application process. Windows exceptions,
Python fatal records and watchdog dumps are counted separately; all are evidence,
not a terminal-crash classification. Native and watchdog limits default to zero;
explicit per-step limits apply cumulatively, and top-level limits govern the final
check. A missing baseline stops before scenario work.

The reader is bounded to 16 MiB per sample, runs outside the application, checks
file identity and the full baseline-prefix hash, and returns inconclusive/failure
on missing, unreadable, empty-baseline, partial, replaced, truncated or oversized
evidence. It never exports native stack text or modifies source logs. No automatic
rotation/deletion is performed; an oversized source requires a separately scoped
evidence strategy, not silent truncation. `snapshot_health(since_minutes=...)` now
labels the read as a whole-file historical inventory with an inconclusive requested
time window. Untimed records cannot prove a retrospective ten-minute count.

**Code gate:** the initial scenario guards failed **7 / 8 cases**, exit 1, before
implementation. The final two new guard files contain **32 cases**; native parser,
capture/watchdog/shutdown and control-bus/inventory neighbors bring the direct
pytest selection to **93 passed, exit 0**, 8.15 seconds. No real log/DB/crash fixtures.
Final rerun also passed all 93 (4.80 seconds); syntax and scoped diff checks passed.
Control-wrapper tests require the optional MCP SDK; an SDK-missing skip is not a pass.
The earlier Home-selection docstring diff in the MCP server was preserved.

**Live diagnostic gate (approximately 20:36-20:37):** documented client `ping` and
`list_actions` succeeded (83 actions). The new `native_health_readonly.json` scenario
ran two health assertions plus the final check against the existing signed-in
source app: no failures, no appended native bytes/exception/watchdog records in
the approximately 0.45-second sampled window. Scenario body time was 427 ms;
this is external probe duration, NOT GUI handler time or a performance benchmark.
The same live probe confirmed that the retrospective inventory remains explicitly
inconclusive. Resource-only MCP receipts contain no patient payload. The app was
not restarted, closed, logged into, or asked to change patient/download state.

This is a **development control/acceptance-tool fix**, not a runtime crash fix.
No installed runtime, mirror, UI, decoder, downloader, native sink or shutdown
policy changed. No new patient GUI acceptance is claimed or required for this
read-only tool boundary. Roll back only these tool/probe/scenario hunks together
if necessary; doing so restores the old unreliable health gate, not a safe pass.
Restart an already loaded MCP server to load its wrapper change; the application
does not require restart for this tool-only slice.

**Still open:** coordinated process-exclusive capture/consumer migration, owner
drain at shutdown, then Preview/DM convergence and GUI DICOM I/O. Direct calls to
the old in-app `count_native_faults_since`, the dashboard and historical native GUI
readers are not repaired by this wrapper change. Also, the separate
`wait_for_download` scenario branch discards its returned success/failure; this
remains an acceptance-harness follow-up before treating an entire download soak
summary as authoritative. Native health pass alone is not download completion,
patient identity/pixel validation, whole-scenario correctness or crash closure.

## First corrective follow-up: offline native-report integrity

Consumer inspection before migrating the native sink found a deterministic defect
in `tools/diagnostics/filter_native_fault.py`: it treated each Windows fault header
as the END of a record, assigning preceding stacks to the next exception. Excluding
a COM record could therefore remove an earlier access-violation stack while keeping
the COM stack under a misleading retained report. The historical summary also
called every retained fault a real crash. Neither classification was trustworthy.

The bounded correction keeps each header with its following stack, splits Python
fatal and watchdog headers independently, and preserves session/unclassified text.
It never infers a dump's process or time from the preceding shared-log header.
Default COM exclusion and CLI options/output filename remain compatible; the help
and summary now explicitly distinguish exclusion policy from terminal-crash proof.
Input/output aliases (including hard links) are rejected before writing, so the
utility cannot replace its source with a filtered copy.

**Verification:** 12 failed / 6 passed before correction, exit 1. Final guard file
has 20 synthetic tests; with native sink/watchdog/shutdown-initiator neighbors,
**42 passed, exit 0**, 3.16 seconds. Cases cover both fault orders, excluded stacks,
watchdogs, Python fatal errors, session interleaving boundaries, truncated/unknown
text, CRLF, custom/no exclusions, and source preservation. An in-memory-only read
of the existing approximately 2 MB native log reconstructed the input text exactly;
one parse took 25.69 ms in the diagnostic process, not the application's GUI.
No raw report was exported, existing log deleted, or deliberate crash triggered.

This is a development diagnostic-tool fix, not an application runtime fix. No
packaged mirror, startup, logger sink, shutdown policy, UI, download, decoder or
live DB behavior changed. Native GUI acceptance is not applicable to this offline
tool; the prior app live lap remains separate evidence. No release/build was run.
Rollback is limited to the filter tool's hunks; retain the guard and failing
requirement. Old generated filtered reports must not be used for stack attribution
without rechecking the original source (do not silently overwrite old evidence).

**Next:** process-attributable native capture plus consumer compatibility, then
observable owner completion at shutdown. Existing readers include the control
adapter, KPI dashboard and native GUI guards; moving the sink alone would create
false-zero crash checks. Keep that migration in one separately guarded slice.
The known Preview/Download Manager projection findings and GUI DICOM I/O follow
after the crash-evidence/exit boundary; none is declared fixed by this utility.

## Follow-up: three-patient source GUI lap, 19:12-19:20

The user explicitly requested live downloads and several patient tabs. Attached to
the single source main PID 1079608 launched at 18:01:33 and already signed in by
the human. Documented client ping/action discovery passed. No restart, login,
clinical report/measurement, cleanup or installed executable was involved.

**Automated gate:** 149 passed, six existing SWIG warnings, exit 0, 21.50 seconds.
Direct pytest with offscreen Qt and reruns disabled: series file completion, socket
response framing, Overall Progress accumulator, retry file retention, socket
cancellation, signature adapter, thumbnail effects/manager retirement and viewport
drop replacement. Transport/files are synthetic; no live DB test was introduced.
These 149 are this lap's selection, not an additive recount of the earlier 124.
Tests finished before the patient interaction measurement window.

**Live gate:** today's bounded MR search returned 40 rows. Three small cases were
selected from the current results; identifiers stayed in local ephemeral memory.
Case A used a real non-first Home thumbnail double-click. Cases B/C used the
documented patient-open route and real patient-thumbnail image double-clicks.
Three patient tabs coexisted. Actual rendered pixels were observed in each;
native wheel advanced A from 6/11 to 7/11 and B from 13/24 to 14/24. This is not
a new real mouse/OLE drag acceptance run.

| Alias | MR series | Expected instances | Independent local DICOM files / unique SOP UIDs | Outcome |
|---|---:|---:|---:|---|
| A | 7 | 65 | 65 / 65 | Queue complete; selected series UID and study UID match |
| B | 7 | 114 | 114 / 114 | Queue and details Overall Progress both 114/114; selected file identity matches |
| C | 7 | 72 | 72 / 72 | Queue complete; selected series UID and study UID match |

Read-only header validation was bounded to each observed slice's exact study
directory, after asserting its UID-named boundary. All **251 MR files** had readable
headers and the expected Study UID, with zero `.part` files. No full pixel-decode
sweep or authoritative server SOP-list comparison was performed. Three additional
document tasks showed 1/1 in the queue and matching count-check records; their
files were not included in the 251-file independent audit. Twenty-three terminal
file-count checks passed at 0.76-2.78 ms. Already-on-disk skip routes are separate;
do not equate number of gate records with number of all study series.

Native close of case B preserved case A's pixels, identity and 11-slice stack.
Reopened B from retained files, then used documented `change_series` in viewport 1.
The second viewport rendered all 24 slices; `scroll_slices(direction=last)` reached
index 23 and visible 24/24, with exact Series/Study UID and `preview_only=False`.
The command is downstream switch coverage, not a native drag. The app and three
patient tabs were left open; application shutdown itself was NOT tested.

### Findings not to hide behind successful downloads

- B's first loaded stack retained `preview_only=True` and lacked series-level UID
  fields even after Download Manager completed. It contained 24 actual DICOM paths
  and wheel navigation changed pixels. Direct header checks proved the selected
  file belonged to the expected study/series; the earlier false metadata equality
  probe was **missing fields**, not evidence of wrong-patient pixels. Reopen loaded
  full identity metadata. Investigate completion-to-viewer metadata convergence;
  do not call it data loss, misrouting, or a proved new regression.
- Download Manager displayed all six queue rows COMPLETED while its summary still
  showed Active: 2 / Downloading: 1. The selected completed details retained a
  nonzero speed / unknown ETA; B/C MR rows displayed Unknown modality. These are
  observable status/projection inconsistencies, not evidence that files failed to
  download. Their provenance and source-of-truth update path need guarded review.
- `get_series_info` reported zero image counts for initially unselected B/C
  entries, despite full files on disk; selected cards then displayed their stack
  counts. Do not use this projection alone as the downloaded-file count oracle.

For 19:11:30-19:18:00, the existing PID-scoped stall script found 48 threshold-
selected gaps, median 220.55 ms, p95 548.0 ms, max 604.2 ms, zero above one second.
Seven traces include first Download Manager retint, patient construction/activation
and a **458.0 ms GUI DICOM read** through `_apply_preview_ui -> get_meta_fixed ->
_safe_dcmread`. The MCP search adapter also uses nested event processing; its trace
is not an uncontaminated native-search latency measurement. Do not claim uniform
performance improvement from this mixed, unmatched workload.

Timestamp-validated app/viewer/download/DB records through 19:19:11 contained no
ERROR/CRITICAL or selected deleted-wrapper/KeyError/WinError-5 markers. No matching
new Windows Application 1000/1001/1002 event or appended native access violation
was found during the lap. Process remained responsive. Shared native-log attribution
limitations still apply. One close/reopen is not a soak or native shutdown proof.
Resource snapshots were approximately 631 -> 646 MiB RSS and 92 -> 89 threads;
different loaded/cached states and one cycle cannot prove either a leak or its absence.

**Result:** focused code and sampled source download/open/scroll/close/reopen PASS.
Preview/status convergence and GUI I/O remain OPEN. Heavy import, pause/resume,
collision/error live recovery, hard-offline, Advanced/VTK, shutdown under load and
installed-package acceptance remain separate gates. No runtime code changed here.

## Decision and evidence boundary

Continue the existing OPT-60 / OPT-35 / OPT-04 master plan in this order:
crash/lifecycle acceptance, remaining identity/completion convergence, then measured
performance acceptance. This is a read-only runtime audit and documentation update,
not another runtime patch or a declaration that Unify is complete.

The user confirms native patient-tab thumbnail drag/drop works. Record that as a
human live pass for that workflow. The earlier automated drag was unfinished and
cancelled; it is not evidence of an application defect. Neither result certifies
Home drag, Advanced/VTK, all multi-study cases or repeated shutdown under load.

Source session: September 15, 16:51:38 launch, main PID 1169344. App records were
examined through 17:40:21.408914, including rotated logs. At 17:44:57 the main
process and its source launcher were absent and the documented control client
could no longer connect. No main shutdown-initiator/drain receipt was found.
Whether the human closed the application is awaiting clarification. Do not call
this a crash, graceful exit, or shutdown acceptance without that evidence.

## Crash findings

| Family | Evidence and current conclusion |
|---|---|
| Signature/import mapping race | Current startup installs the binding/version-gated snapshot adapter. Its tests pass; no matching KeyError was found in the latest PID. The adapter runs before configured logging, so absent activation logging does not prove it was skipped. Not the same diagnosis as native exit faults. |
| Import/layout reentrancy and thumbnail ownership | Existing import registration, overlay, root-style, retirement and viewer replacement guards pass again. Preserve these corrections. The sampled GUI lap is not the heavy repeated import/open/close acceptance matrix. |
| Windows spawn IPC and viewer flash | Shared-Event/spawn and embedded-widget ownership guards pass; the preceding live download completed. Preserve supported venv spawning and hide/retain-parent retirement. Do not detach a visible Qt child or substitute the venv pythonw redirector. |
| Main exit native faults | Windows recorded Shiboken access violations at 10:57:23 and 11:04:36, with matching main PIDs and native exit stacks. These precede the latest run. Exact native destructor/owner cause and post-fix shutdown acceptance remain open. |
| Other Windows failures | 12:08:11 ucrtbase fail-fast temporally follows the earlier signature failure. The 12:11:35 Qt6Core fail-fast PID is not established as a main application session. Temporal proximity alone is not proof of common cause. |
| Latest source run | No new Python/AI-PACS Application event 1000/1001/1002 after its launch was found, nor a newly appended access violation in the latest log segment. A startup COM 0x8001010d record was non-terminal: the main process continued for roughly 49 minutes. Absence of an event is not proof of graceful exit or elimination of all crashes. |

### Native dump attribution correction

`PacsClient/utils/native_fault_log.py` opens one append-mode `native_fault.log`;
both source main and spawned interpreters can append session headers. A dump must
not be assigned a PID or timestamp solely from the immediately preceding header.

Concrete example: the 12:36:16 header names PID 1141548. The app log's structured
prefix identifies **parent PID 1153108**, while `prewarm.ensure_warm` reports
**child PID 1141548** in its message. The subsequent access-violation dump contains
the application exit frame plus active consultation, viewer-cache and UI retry
threads. This is not sufficient evidence to attribute that dump to the idle
prewarm child, or to date the fault at 12:36:16. It is a separate historical exit
dump with unresolved attribution, not a newly observed latest-session crash.
Do not blame the Google HTTP frame: it is another thread, not the faulting frame.

Next diagnostic slice should make native output process-attributable while keeping
source/frozen support and early fault capture. Use a guarded per-process sink or an
equally reliable existing-logger extension; preserve historical dumps. Correlate
Windows PID/time and shutdown initiation/completion before changing native teardown.

## Structural lifecycle boundary still open

The existing lifecycle manager invokes callbacks synchronously in LIFO order and
checks timeouts after callbacks return. A returned stop request is not evidence
that a worker finished. The consultation fix owns both timers, invalidates late
results, requests interruption and releases completed workers, but does not add an
application-wide asynchronous drain barrier. In-flight provider I/O still has its
existing timeout. The final hard-exit path is not a substitute for owner completion.

Extend the existing lifecycle boundary, not a second global manager: observable
stop requests, owner completion, bounded nonblocking drain and explicit escalation
outcomes, each separately guarded. Preserve Fast, Advanced and VTK ownership domains.
Do not change GC, DLLs, hard-exit policy or teardown order based only on a DLL name.

## Automated verification in this audit

Direct pytest, offscreen Qt, reruns disabled, exit codes checked:

- 93 passed: signature guard; consultation lifecycle; isolated import registration;
  overlay reentrancy/liveness; startup/shutdown and initiator logging; thumbnail
  card effects and manager retirement. Six existing SWIG warnings, 23.92 seconds.
- 31 passed: Windows multiprocessing visibility; thumbnail panel UI; viewport drop
  replacement. Six existing SWIG warnings, 3.30 seconds.
- Total: **124 distinct focused passes**. Mirror verifier: **465 matching pairs,
  zero plugin-only files**, exit 0. No full-repository, release or installed-build pass.

The preceding download slice's 217 passes are a separate historical receipt, not
additional tests rerun here. No regression was implemented in this audit, so no
new fixed-defect catalog row or fabricated fail-before result is added.

## Remaining Unify acceptance

1. Close the crash evidence and owner-completion boundary above before claiming
   stability. Exercise heavy import/open/close with active work on one source app;
   require actual GUI results and attributable logs, not just command acceptance.
2. Reconcile current readers against OPT-35 and the thumbnail/priority provenance
   map: Study/Series UID authority, pixel-revision invalidation, Home input,
   retry/priority routing, and same-number/unnamed/multi-study identity cases.
   Current default-on identity readers already exist; do not restart the old S0
   design or infer an unimplemented phase merely because a historical flag vanished.
3. Complete OPT-04 durable SOP/study-manifest evidence, including already-on-disk,
   retry, cancellation and terminal IPC convergence. A lower-bound filename/size
   count is not a durable SOP or pixel certificate. Keep this ahead of further
   download scheduling optimization. Existing sampled 117/117 completion remains
   valid within its documented scope.
4. Retire compatibility paths only after a representative zero-firing/shadow and
   soak matrix. Preview-to-Complete, immediate/progressive presentation and separate
   Fast/Advanced/VTK execution domains are intentional, not duplication to delete.

## Latest KPI receipt and remaining cost

Reproduction: `tools/analysis/oneoff/unify_stall_summary_2026_09_14.ps1`, Start
`2026-09-15 16:51:38`, End `2026-09-15 17:40:22`, AppProcessId `1169344`.
Ten log files including rotations; PID/time scoped and deduplicated.

- 42 threshold-selected F8 stalls; median 160.8 ms, nearest-rank p95 555.0 ms,
  maximum 1658.8 ms; one above one second.
- Six captured trace samples include first Home construction, first Download
  Manager construction, patient activation and one 416.6 ms GUI cache-miss path:
  `set_slice -> get_rendered_frame -> _get_pixel_array -> _decode_slice -> dcmread`.
- That DICOM read is not the final download file-count scan; those previously
  measured checks took 0.97-2.55 ms off the event loop. Do not remove correctness
  checks to address an unrelated GUI cache miss.

These are threshold-selected stalls, not all-interaction latency percentiles.
Workload and cold/warm state are not matched to older sessions; no general speedup
or percentile improvement is claimed. Browser cold opening was not exercised in
this lap. Its feedback patch does not eliminate the known WebEngine cold-start cost.

After correctness gates, measure matched cold/warm TTFF, first/all thumbnails,
queue age and GUI apply time; enumerate remaining GUI filesystem/QPixmap work and
bound large-card batches. Track RSS, handles and worker counts across repeated
cycles. Move only evidenced expensive preparation through the existing immutable
data boundary; do not merge renderer domains or rewrite the healthy decoder broadly.

## Acceptance status

Code guards: PASS for the focused selection. Sampled source GUI: PASS as recorded
in the download receipt plus the user's patient drag confirmation. Crash/shutdown
closure, full Unify matrix, matched KPI acceptance and installed-build verification:
OPEN. This document updates the existing master plan, not a parallel project.
