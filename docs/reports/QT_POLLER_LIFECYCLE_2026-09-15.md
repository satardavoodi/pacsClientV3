# Qt lifecycle audit: consultation producer retirement

## Completion observation follow-up

The central lifecycle manager now distinguishes callback return from producer
completion. `shutdown_complete` observes stopped timers and processed scan-finished
delivery on the owner thread; it does not certify deferred QObject/native deletion.
The application probe covers direct QApplication-owned pollers, including a replaced
identity's still-finishing owner, without creating a producer or doing I/O/waits.
`worker_finished_after_stop` remains the later producer breadcrumb. Other lifecycle
owners without probes are unknown, never implicitly drained. The fourth follow-up in
`CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md` records 105 focused passes, mirror parity,
scope/rollback and the still-pending fresh-source close/exit gate. No historical native
crash is attributed to this producer merely because its thread appears in a dump.

## Scope and evidence

This is the next bounded OPT-60 stability slice, not a new shutdown architecture
or proof that the two earlier native exit faults are fixed. See
[the signature/exit-fault evidence](QT_SIGNATURE_IMPORT_RACE_2026-09-15.md).
Google/poller stacks were on other threads in those dumps, not the faulting frame.

The concrete reproduced defect is in `ConsultationPoller`: `stop()` stopped only
the periodic timer. Its independent five-second startup callback still launched a
scan. Late assigned/response/error signals still wrote state/notified/changed
backoff. Completed QThreads remained children of the application-owned poller.
Identity replacement stopped but retained the old owner. There was no app-close
producer gate in the central lifecycle registry.

## Implemented contract

- Retain the existing QApplication-level singleton and QThread execution domain.
  Own both startup and periodic timers; repeated start is idempotent. Manual
  `poll_once()` before initial start remains supported. Explicit start after stop
  resumes; disposal and application shutdown are terminal.
- Stop both timers and invalidate the scan generation before requesting cooperative
  interruption. Never wait, terminate a worker, run network work on GUI, or spin a
  nested production event loop. Existing provider/folder/detection calls stay on
  the worker; interruption is checked between stages. An active HTTP operation
  still runs to its existing timeout/return, not an invented hard cancellation.
- Deliver through explicit queued QObject slots. Reject stopped, disposed, old-owner
  and old-generation results, including results queued before the worker finished.
  Recheck each notification batch item in case a notification receiver stops the
  poller. Preserve current-generation deduplication, status values and backoff.
- Release the worker reference and schedule its deletion on the owner thread after
  `finished`. An identity-replaced owner is disposed only after its scan finishes.
  No new scan overlaps a previous scan awaiting its completion delivery.
- Register `consultation_poller.request_stop` last in the existing MainWindow LIFO
  registry, ahead of shared DB cleanup. The callback only uses an already-loaded
  optional autostart module: no plugin load during shutdown. Add an `aboutToQuit`
  fallback and reject autostart after the terminal app-close gate.

Qt documents [thread ownership and queued delivery](https://doc.qt.io/qt-6/threads-qobject.html)
and requires waiting for [QThread completion before deleting its object](https://doc.qt.io/qt-6/qthread.html#dtor.QThread).
This patch follows that owner-level contract. It does not yet implement the
application-wide asynchronous drain described below.

## Structural findings still open

| Boundary | Evidence / required next step |
|---|---|
| Central lifecycle manager | Calls callbacks synchronously; timeout is checked after return, not enforced. A synthetic 60 ms callback with 1 ms budget still blocks its caller for 60 ms. Docstrings corrected; runtime semantics unchanged. Extend this existing manager with observable request-stop/completion phases, not a parallel global manager. |
| Application exit | Stop requests are not a drain barrier. In-flight cloud I/O may still exist when the application event loop ends; native QApplication destruction must not race live QThreads. Do not claim this patch prevents that exit fault. Keep GC, hard-exit policy and teardown ordering outside this slice until native shutdown evidence supports the next guarded change. |
| Other executor/task owners | Home `shutdown(wait=False)` and task cancellation do not prove completion. qasync's default executor, in contrast, waits in loop close; a stuck task can block that wait. Instrument each domain rather than generalizing that all pools lack cleanup. Fast/Advanced/VTK remain separate owners. |
| Poller local DB work | Outgoing snapshot and notification persistence still run synchronously as before. This patch introduces no new GUI I/O, but does not claim the entire poll cycle is nonblocking. Profile and move this through a reviewed repository boundary separately. |

Preserve existing thumbnail ownership and reentrancy fixes. A repeated Shiboken DLL
name is not evidence that every historical incident shares the same root cause.

## Verification receipt

- Nine initial real-Qt guards failed before the Poller fix, exit 1: delayed start,
  manual/queued start, late delivery/backoff, stage cancellation, worker retention,
  restart and absent terminal disposal. Three additional autostart/registry guards
  failed before integration after correcting a test-factory setup error, exit 1.
- Adversarial review found one additional failing batch-reentrancy guard; corrected
  by checking retirement between items. Current queued-generation and normal
  GUI-thread notification guards passed as well. Final lifecycle file: 15 guards.
- Combined cloud consultation, Identity, Education consultation, plugin registry,
  shutdown/startup, shutdown-initiator and signature-adapter selection: **367 passed,
  3 SWIG deprecation warnings, exit 0**, 16.86 seconds; final repeat after timer-test
  margin and documentation changes: **367 passed, 3 warnings, exit 0**, 12.83 seconds.
  Direct pytest, reruns disabled; scoped syntax/diff/whitespace checks passed.
  The broad run patched `data_paths.DATABASE_FILE` to temporary storage, cleared
  the pool before/after, and rejected raw connections to the live DB path.
- The old provider-failure test had an unmocked outgoing DB read and was run once
  before this gap was noticed. It now uses a synthetic outgoing snapshot. Do not
  describe that earlier invocation as isolated. Two older tests also expected
  finished worker retention; they now observe completion/reference release.
- Both consultation payload mirrors synchronized with the repository tool;
  **464 pairs match, zero plugin-only files**. No new module, dependency, feature
  flag, credential, schema, decoder or download-protocol change; no release build.
- Fresh-source GUI **BLOCKED**: no aipacs-control connector in the active inventory;
  documented client `ping` returns QLocalSocket Invalid name. No old process,
  offscreen test, synthetic notification or command acceptance is counted as GUI QA.

## Live gate and rollback

Human launches one fresh source instance with `AIPACS_TEST_SERVER=1` and signs in
outside clinical reading. Probe ping/list_actions, verify Home and real patient
open/close still work, then observe normal application exit. With an already
configured consultation identity, inspect PHI-free `[CONSULTATION_POLLER]`
`stop_requested worker_pending=...` and, when delivered, `worker_finished_after_stop`.
Do not relink identities, send synthetic clinical notifications or change cloud
content just to manufacture this test. The offline/in-flight/replacement edge
cases have synthetic Qt guards; cloud round-trip acceptance remains separate.
Missing completion evidence is not completion. Fresh signature-adapter and
thumbnail split-timing gates also remain open.

Rollback only the two notification runtime files, their two matching payloads,
and the new MainWindow stop registration from this slice. Do not revert unrelated
worktree changes or the preceding signature/thumbnail corrections. Keep the
corrected lifecycle documentation and recorded failing requirements as evidence.
