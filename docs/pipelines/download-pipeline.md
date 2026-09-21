# Download Pipeline

> **Execution order (2026-09-18):** this maintained reference does not authorize a
> parallel Download Manager plan. Shared changes follow the
> [U0-U5 ledger](../plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md#current-execution-ledger---2026-09-18).
> U1's authoritative completion publication begins only after U0 acceptance; state
> authority, invalidation and path retirement follow in order. Do not infer completion
> from notification, PNG presence or an unverified count.

## Download-process liveness contract (2026-09-16)

Viewport interaction must not hard-suspend an active download or an idle prewarm
child. PID registration is lifecycle/shutdown ownership, not permission for native
`NtSuspendProcess` / `NtResumeProcess`. The historical compatibility hook names
remain callable no-ops in both widget routes. Preserve the child's existing lower
OS-priority request and Download Manager's explicit pause/cancel/preemption state
machine; do not add another download/recovery path in the viewer. An alive child
or `Downloading` queue state is not proof of job acceptance or file progress.

See [the OPT-04 correction and pending live gate](../reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-16-opt-04-download-liveness-independent-of-viewport-settling).
The change requires a fresh process and does not repair an already suspended child
by hot reload. Full scroll-performance and installed-client acceptance are not claimed.

> **Canonical application version:** 3.6.6
>
> **Current-source review:** 2026-09-15 (bounded transport follow-up)
>
> **Scope:** active server-to-local DICOM download, progress, resume, and ownership boundaries.

This is the maintained architectural reference for the active Download Manager. Historical
retry experiments and implementation detail remain in
`docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`; reconcile them
against current source before reuse.

**2026-09-14 source-log qualification:** the inspected run contained 25
`DM-CONVERGE-MISS` events (status updates with no matching UI row, OPT-04) and one
ERROR-level priority-preemption cancellation. Neither proves a server failure, a
duplicate download, or study completeness. No download code was changed by the
thumbnail metadata prerequisite. The bounded evidence and remaining acceptance gates
are recorded in the source-run section of
`docs/plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md`.

## Transport authority

**September 15 response correction (OPT-04):** the DM socket now accumulates the
four-byte prefix exactly, uses an elapsed broadcast-wait budget instead of the
hard ten-frame count, retires incomplete/invalid streams and permits owner-local
request/connect lock reentry. Header timeout is restored before body transfer;
large payloads retain their existing receive policy. No UI, progress, priority,
encoding or file-layout change. The [review and verification receipt](../reports/DOWNLOAD_SOCKET_RESPONSE_REVIEW_2026-09-15.md)
records 189 boundary passes, five builder passes, known pre-existing test failures
and pending fresh-source GUI. This does not close the completion-proof gate below.

The active patient, study, thumbnail, metadata, and DICOM-byte route uses the PACS custom socket
protocol. Bulk instances are fetched through `GetSeriesImages` by
`modules/download_manager/network/socket_client.py`.

gRPC is retired for this imaging route. Names such as `GrpcMetadataClient`, `grpc_client.py`, or
old constructor parameters are compatibility names; the Download Manager metadata adapter is
socket-backed and resolves the socket host/port. Do not reconnect the retired gRPC download path,
and never substitute the DICOM service port for the socket-protocol port.

## Active flow

```text
Home patient/open or explicit download action
  -> DownloadManagerWidget queues an identity-complete DownloadTask
  -> DownloadProcessWorker owns a spawned worker process
  -> DownloadExecutor validates state and fetches server metadata
       -> socket-backed GrpcMetadataClient compatibility adapter
       -> GetStudyThumbnails without pixel payload
  -> SeriesDownloader freezes the study manifest
       -> publishes one aggregate-only study_manifest event
       -> orders work by priority/active-series intent
       -> SocketDicomClient calls GetSeriesImages in resumable batches
       -> writes DICOM files and updates local database/state
  -> multiprocessing queue carries bounded progress/terminal events
  -> main-process bridge emits Qt signals
  -> Download Manager and open patient tab project progress on the GUI thread
```

Blocking network, filesystem, compression, and database download work belongs to the worker
process. The GUI thread owns only bounded state projection and widget updates. Progress handlers
must not add disk scans, database reads, decode work, VTK work, or per-image widget creation.

### Priority-intent authority

Viewer and thumbnail actions must express intent through `DownloadManagerWidget` and
`SeriesIntentCoordinator`; they must not instantiate `SeriesDownloader` or a socket client from a
GUI handler. As of 2026-09-14, `_on_right_panel_thumbnail_clicked` delegates immutable UID
intent to the existing-tab viewer entry through `HomeTabService`; its obsolete direct-download
body is removed. This is not a new download admission route or full DM migration. The other
retained `_download_single_series_*` helpers predate Zeta and remain migration residue,
not an authorized fallback. Preserve the valid goal—promote/reuse one
study task and prioritize the requested series—but route it through the current coordinator with
complete study/series identity. See
`docs/plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md`.

## Current components

| Responsibility | Current location |
|---|---|
| Queue UI and orchestration | `modules/download_manager/ui/widget/widget.py` plus `_dm_*.py` mixins |
| Worker-process bridge | `modules/download_manager/workers/download_process_worker.py` |
| Spawn-safe worker entry | `modules/download_manager/workers/download_process_entry.py` |
| Workflow coordinator | `modules/download_manager/download/executor.py` |
| Per-series download and frozen totals | `modules/download_manager/download/series_downloader.py` |
| Socket batch client | `modules/download_manager/network/socket_client.py` |
| Socket-backed metadata compatibility adapter | `modules/download_manager/network/grpc_client.py` |
| State/rules/resume | `modules/download_manager/state/`, `rules/` |
| File/database/thumbnail projection | `modules/download_manager/storage/` |
| Viewer/thumbnail fan-out | `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py` |

`modules/download_manager/ui/main_widget.py` is a compatibility re-export, not the implementation
owner. Likewise, the `grpc` word in a class/file name is not evidence that the active transport is
gRPC.

## Identity contract

- `StudyInstanceUID` scopes one download task and its progress generation.
- `SeriesInstanceUID` is the authoritative per-series identity for progress and terminal
  accounting.
- `SeriesNumber` is display/order metadata and may be duplicated or malformed.
- Final storage folders follow the shared series-folder authority. Do not reconstruct a path from
  UI ordinal position or assume `SeriesNumber` is globally unique.
- A progress/result event must carry the identity supplied by the worker; the current patient or
  current viewport is not a safe substitute.

See `docs/pipelines/thumbnail-pipeline.md` and
`docs/reports/IMPORT_DUPLICATE_SERIES_NUMBER_IDENTITY_2026-08-30.md` before changing identity or
folder behavior.

## Overall Progress contract

`Overall Progress` is cumulative across every series in one study/queue row. It is not the
percentage of the currently downloading series and is not a grand total across all queued
patients.

- The worker freezes image/series totals before priority reordering or yield/reinsert behavior.
- Before the first series, it sends one reliable aggregate-only `study_manifest` event from the
  same server metadata used for transfer.
- The main process maintains an O(1), integer-only accumulator keyed by
  `SeriesInstanceUID`.
- Per-series progress may restart, but the study numerator is monotonic within one download
  generation.
- A series already complete on disk contributes through an aggregate-only `series_accounted`
  event and must not create viewer/per-instance fan-out.
- The UI cadence remains throttled; do not emit one expensive Qt operation per image.

The source-build Overall Progress behavior was human-verified on 2026-09-01. That observation is
not installer or release acceptance.

## Resume and completion

**Sampled source acceptance:** the September 15 16:51:38 launch completed five
MR series / 117 files with independent disk-count agreement and both terminal
Overall Progress displays at 117/117. Count-check cost was 0.97-2.55 ms including
a separate document task. Native Home open/wheel and MCP second-series rendering
passed; native drag and the failure/retry/in-flight matrices remain unverified.
See the [live receipt](../reports/DOWNLOAD_FILE_COUNT_GATE_2026-09-15.md).

**September 15 count gate (OPT-04):** normal socket-series termination now checks
the existing resume-eligible file count once off-loop and fails when it is below
the metadata's expected instance count. Duplicate responses do not inflate skipped
counts. Coordinator retries reuse the first UID-scoped destination, including
collision suffixes. Encoding, layout, retry budgets and UI design are unchanged.
This is not SOP membership/pixel validation; zero-count metadata and skip routes
retain their prior contracts. See [evidence, guards and limits](../reports/DOWNLOAD_FILE_COUNT_GATE_2026-09-15.md).

Resume rules combine task state with file-aware checks. A database `COMPLETED` state is not enough
when required files are missing; partial series retain reusable files and resume at bounded batch
boundaries. Cancellation/preemption is distinct from failure and must preserve resumable state.

The current worker evaluates success against frozen series totals and failed-series state, and
existing resume rules inspect disk completeness. However, the architecture still lacks one
durable authoritative completion marker that independently states that the frozen study manifest
is satisfied on disk. Until that marker exists:

- a 100% progress bar, terminal notification, timeout absence, or lack of logged errors is not
  standalone proof of complete local study content;
- soak tests must not claim download correctness solely from UI progress;
- land the completion marker before further download-path optimization, as tracked by OPT-58's
  open follow-up.

## Lifecycle and shutdown

- The main process owns worker references and result-queue bridging.
- Preemption and close use non-blocking cancellation; do not synchronously join a long network
  worker from the GUI thread.
- Terminal delivery is bounded-reliable so a full progress queue cannot lose completion.
- **Current-source qualification (September 15):** bounded-reliable terminal
  delivery is the required contract, not fully proven implementation. The final
  `result_queue.put` is currently unbounded; progress/manifest puts are separately
  bounded or best-effort. Audit this with completion convergence before claiming
  delivery under a stalled/full queue. This transport slice does not change it.
- Late events are admitted only for the matching study/download generation.
- Application shutdown stops accepting new work, requests worker cancellation, drains/terminates
  through the documented owner, then closes shared services and database pools.
- Windows spawn safety is mandatory: worker entry imports must not construct Qt UI, open a second
  application window, or depend on the development interpreter layout. Source and packaged paths
  require the same spawn-safe entry contract.

## Regression boundaries

Before changing this pipeline, preserve all of the following:

1. socket-only active imaging transport;
2. no GUI-thread network, disk traversal, decode, or lock-waiting database work;
3. immutable Study/Series UID identity across process and Qt envelopes;
4. monotonic study-level Overall Progress across series boundaries;
5. resumable partial files and explicit preemption semantics;
6. bounded-reliable terminal delivery;
7. Fast/Advanced/MPR rendering-domain separation;
8. source/package mirror parity when a mirrored payload changes;
9. explicit installed-build verification after source tests, without launching multiple app
   instances.
10. no GUI-side direct downloader fallback; series priority reuses the Download Manager task and
    the intent coordinator.

Use direct focused pytest invocations and check exit codes. The current repository-wide fast-lane
wrapper is not authoritative proof of success.


## 2026-09-16 VTK handoff: remote drop waits without visible download

User reports dragging a never-downloaded series into Advanced viewports did not
produce a download. Read-only log evidence: `[DROP] apply force_reload=1` at 21:31:10
and 21:31:11; `RemoteSeriesDownloadAttached` at 21:31:10.889 / 21:31:11.916;
`INTENT_PRIORITY tag=begin state=Downloading` five times between 21:31:10.418 and
21:31:12.282; waiting events persist beyond 21:37. These are intent/state records,
not network-byte/worker-start proof. Other drops in the window have DL-SKIP-COMPLETE;
do not attribute those to these remote series without canonical identity correlation.
No raw identifiers or patient data are copied into this handoff.

Owner follow-up: correlate canonical study/series identity from drop through
`_coalesce_dm_view_intent`, `_trigger_download_if_needed`, `_on_retry_series_download`,
`request_critical_series_download` and `SeriesIntentCoordinator`, then prove worker
start, file arrival and progressive callback delivery. Check stale Downloading state,
missing task registration, coalescing and retry admission as hypotheses, not established
causes. Preserve unrelated active downloads. No DM runtime changes in the VTK task.
The associated floating black overlay was separately reproduced and fixed at show-time
anchor visibility; see [VTK report](../reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md#opt-23-native-cover-after-page-switch-2026-09-16).
