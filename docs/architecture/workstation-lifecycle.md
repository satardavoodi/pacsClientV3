# Workstation Lifecycle

> **Canonical application version:** 3.6.6
>
> **Lifecycle review:** 2026-09-15
>
> **Implementation authority:** current source and focused guards; this document is the maintained architectural summary.

This document describes the ownership boundaries that keep the Windows DICOM workstation
responsive and stable across startup, repeated patient workflows, and shutdown. For the full
system inventory, read `PRE_DEVELOPMENT_SYSTEM_MAP_2026-08-27.md`. Historical reliability
reports remain evidence for their recorded runs, but they do not override current source.

## Application startup

```text
main.py
  1. Establish multiprocessing and graphics policy before Qt/VTK-heavy imports.
  2. Initialize diagnostic logging and process-role metadata.
  3. Create the single QApplication and integrate one qasync event loop.
  4. Initialize startup-owned schemas, services, authentication, and the main window.
  5. Start background services through explicit owners.
  6. Run the event loop until application shutdown.
```

Startup invariants:

- There is one Qt GUI thread and one application event loop. A qasync coroutine still runs on
  that event loop unless it explicitly delegates blocking work; `async` alone is not a worker.
- Filesystem traversal, network I/O, DICOM decoding, database lock waits, AI calls, and expensive
  VTK construction must not run on the GUI thread.
- Startup-only schema and compatibility work must not be repeated inside patient-open or other
  interactive handlers.
- A background worker may receive immutable values and return immutable results. It must not
  read or mutate live Qt widgets or VTK objects.

## Repeating patient workflow

```text
Patient selection
  -> server, import, or local projection resolves study/series identity
  -> main-page thumbnail projection
  -> patient tab and viewer-domain owner creation
  -> optional Download Manager request
       -> worker subprocess
       -> PACS custom socket protocol
       -> durable files/state
       -> throttled progress projection on the GUI thread
  -> series display in the selected execution domain
  -> tab close performs the inverse ownership sequence
```

The active DICOM download route is the PACS socket protocol. References in older documents to
gRPC series download describe a retired implementation and must not be used to reconnect that
path. The DICOM port is not the thumbnail/patient/download protocol endpoint.

## Viewer execution domains

The workstation has separate rendering and lifecycle domains:

| Domain | Responsibility | Ownership rule |
|---|---|---|
| Fast Viewer | Qt/pydicom 2D stack display | Must remain VTK-free. |
| Advanced Viewer | Its own decode, cache, render, and teardown | Do not borrow mutable Fast or MPR state. |
| Standard and specialized MPR | VTK/OpenGL rendering and geometry | Release interactors/render windows before Qt orphaning or deletion. |
| Other VTK modules | Module-specific rendering | Each module owns its VTK graph and cleanup contract. |

Only immutable, identity-keyed data may cross these domains. Do not share mutable render
objects, cameras, transforms, VTK images, widget instances, or lifecycle state as an
optimization.

## Qt callback and ownership rules

- UI presentation and Qt object mutation occur on the GUI thread.
- Long-lived/global signals require an explicit, idempotent disconnect by the receiver's owner.
  Qt parent destruction is useful, but it is not a substitute for a missing owner teardown when
  a global signal or Python reference can retain the object graph.
- Repeating and delayed callbacks must be cancelable or generation-gated. A static two-argument
  `QTimer.singleShot` that captures a transient manager/widget is not an ownership boundary.
- Teardown first closes callback admission, then stops timers/workers, disconnects external
  signals, releases native resources, removes registries/back-references, and only then calls
  `deleteLater()` or orphans a widget.
- Do not call `processEvents()` inside layout mutation or teardown. It may re-enter code while
  the object graph is only partially valid.
- Full `gc.collect()` is diagnostic pressure, not a cleanup authority. It must not be used to
  compensate for missing signal, timer, worker, Qt-parent, or VTK ownership.

## Patient-tab close contract

The tab owner must perform these actions in order, with every step safe to repeat:

1. Mark the patient/viewer generation closed so late results become no-ops.
2. Cancel or detach outstanding per-tab work and delayed callbacks.
3. Release MPR and other VTK/OpenGL resources before widget orphaning.
4. Dispose Fast/Advanced viewer state through their own domain-specific paths.
5. Dispose thumbnail/controller resources, disconnect app-lifetime signals, and clear strong
   back-references and registries.
6. Remove the tab from application-owned maps.
7. Schedule Qt destruction with `deleteLater()`.
8. Measure post-close memory/threads/handles after a settle interval; do not infer ownership
   correctness from one GC-forced snapshot.

## Thumbnail lifecycle: historical diagnosis and current bounded correction

September 14 update: the patient-owned signal relay and explicit manager reset/disposal now
retire confirmed callbacks before owner teardown. The latest card-effect slice also cancels
superseded Ready/hide timers and stops running card property animations while leaving native
children parented for normal deletion. Fourteen card-effect guards complement the manager
guards; live validation requires a source run newer than the 20:41 launch. See current OPT-60
for exact evidence, remaining direct-map/worker-identity gates and rollback. The following
diagnosis describes the pre-fix review, not the present implementation.

As of the 2026-09-13 source review, `ThumbnailManager` has no manager-level `cleanup()` or
`dispose()` method. Real-PySide6 probes do **not** support the earlier claim that
`ThemeManager.themeChanged` alone pins a standalone manager: that manager was collectible while
still connected. The immediate right-panel manager is retained while its cards exist through
their callbacks, then is collectible after card deletion. These are not deterministic permanent
leaks merely because the managers are parentless.

The confirmed retention boundary is an outward patient-tab priority signal connected to a home
callback lambda that closes over the patient widget. A matching Qt ownership probe kept the
owner and manager alive after `deleteLater()` and collection until explicit disconnect. Static
`singleShot` callbacks also create bounded retention and may deliver stale work. The historical
May disconnect landed in `CircularProgressborder.cleanup()` instead. Correction from the
September 14 behavioral guard: `theme_manager` exists but the referenced callback does not;
the outer exception handler aborted remaining cleanup. No owner call was found in the audited
paths; the current card cleanup retires effects without that unrelated manager disconnect.

At the September 13 review this was **diagnosed, not fixed or guarded**, not proof of a native crash. OPT-60
must begin with fail-before ownership tests, then disconnect confirmed outward callbacks, add an
idempotent owner-driven manager disposal contract, and cancel or generation-gate delayed work.
Do not move the full collector to a worker: 11 GUI-thread samples measured 149.1–1501.1 ms
(median 234.1 ms), but global collection can execute Qt/VTK finalizers and therefore is not a
safe worker task. Establish explicit teardown first, then re-measure whether forced collection is
still needed. Keep DICOM grouping, series identity, download, Fast Viewer, Advanced Viewer, and
VTK/MPR behavior outside this lifecycle slice.

The related identity/routing history is analyzed separately in
`docs/plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md`; do not bundle
its Download Manager migration work into the ownership patch.

## Application shutdown

The intended inverse-ownership contract at process scope is:

1. stop accepting new UI operations;
2. close patient/module owners and their native resources;
3. stop download/warm-up processes and background services through their owners;
4. disconnect the socket service;
5. drain/stop logging and bounded workers;
6. close database connection pools;
7. let Qt complete deferred destruction before the event loop exits.

This is a target contract, not proof the current implementation drains every owner.
MainWindow currently invokes registered callbacks synchronously in LIFO order,
then retains the existing collection/quit path; main retains its hard-exit failsafe.
Timeouts are advisory measurements after callback return, not enforced deadlines.
Do not infer native destruction from a callback result or an exit-intent breadcrumb.

The September 15 OPT-60/OPT-21 correction rejects overlapping `shutdown_all()` calls
without resetting the outer admission guard. Optional read-only completion probes
are sampled once after callbacks, without waiting, I/O or event pumping. Primitive
copied observations separately report callback outcome/duration and owner completion;
the manager retains no probe/owner closures after return. Unprobed owners are unknown.
The consultation probe includes retired application-owned producers and requires
queued worker-finished delivery, but does not certify deferred QObject deletion.
`[SHUTDOWN_FINAL]` precedes log-listener shutdown and reports unverified owner
completion and hard-exit intent. Actual process exit and process-exclusive native
evidence remain separate live gates. See the fourth follow-up in
`../reports/CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md`.

Every new timer, thread, process, socket, global signal, VTK object, or external client must
document creation, cancellation, close, restart, error, and stale-result ownership before it is
added.
