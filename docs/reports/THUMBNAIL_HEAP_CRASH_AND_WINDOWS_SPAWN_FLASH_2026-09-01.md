# Thumbnail Heap Crash and Transient Windows During FAST Drop — 2026-09-01

## Outcome

Four related observations were separated and investigated:

1. Opening a multi-study patient could terminate the source application with
   Windows exception `0xc0000374` while the grouped sidebar created a thumbnail
   card.
2. An initial attempt to hide Windows source multiprocessing workers selected
   the virtual environment's `pythonw.exe` redirector.
3. A FAST series drop could flash a small native window while a one-frame
   preview was upgraded to the complete series.

4. That `pythonw.exe` selection introduced a download regression: the worker
   could reach the server thumbnail request, but failed before series transfer
   when reading its shared cancellation event with `PermissionError: [WinError
   5] Access is denied`.

The FAST flash was initially attributed to worker console visibility. Live
verification disproved that attribution: the restarted source application was
already using `pythonw.exe` descendants while the flash remained. Fresh viewer
logs exposed the separate Qt ownership defect described below. Later download
logs exposed item 4 and proved that it was a client bootstrap failure, not a
server-download failure.

No patient identifiers, DICOM paths, or clinical data are recorded here.

## Thumbnail crash evidence and correction

The main application log ended without an application-shutdown marker. The
native fault sink captured the main Qt thread inside this chain:

`_render_multistudy_grouped_slot` -> `_render_multistudy_grouped` ->
`add_thumbnail_to_thumbnail_layout` -> `create_thumbnail_widget` ->
`widget.setStyleSheet`.

The stylesheet was applied at the end of card construction with an unscoped
`QWidget` selector, after child widgets, graphics effects, z-order changes, and
an event filter already existed. The correction gives the card root an object
name and applies the root-only `QWidget#seriesThumbnailCard` style before the
native subtree is constructed. Series identity, multi-study offset keys,
thumbnail paths, counts, drag payloads, and image loading are unchanged.

## Download regression: evidence and corrected multiprocessing policy

The server-side thumbnail request completed successfully in approximately
25-32 ms. The spawned download worker then failed in the local cancellation
callback before requesting series data:

`cancel_check` -> `multiprocessing.Event.is_set()` -> semaphore lock ->
`PermissionError: [WinError 5] Access is denied`.

Windows process inspection showed why. In the supported source environment,
`.venv/Scripts/pythonw.exe` is a redirector rather than the base interpreter.
Selecting it as the multiprocessing executable added an extra launcher hop.
The shared Event/semaphore handles were prepared for the direct child and were
not valid in the final process. The parent consequently observed an unexpected
worker exit and retried, making a healthy server look unable to download.

`configure_hidden_multiprocessing` now distinguishes runtime types:

- supported virtual-environment source runs retain Python's default spawn
  executable so Event, Queue, and semaphore handles remain valid;
- a direct, non-virtual-environment `python.exe` may select its direct sibling
  `pythonw.exe` when present;
- frozen/installed applications, non-Windows systems, non-Python executables,
  and missing-`pythonw` environments are never overridden.

The authority still runs before `multiprocessing.freeze_support()`, but its
default behavior in the supported `.venv` checkout is deliberately a no-op.
The installed executable path is guarded independently and remains unchanged.
No server protocol, socket port, download request, cancellation semantics, or
payload handling was modified.

## FAST drop flash: log evidence and root cause

The fresh log correlated one user drop with this sequence:

- drop dispatch at `13:34:32.355`;
- a one-slice FAST preview became visible and completed by `13:34:32.524`;
- the complete four-slice series began replacing it at `13:34:32.547` and was
  visible by `13:34:32.599`.

This two-stage Preview -> Complete transition is intentional and must not be
deduplicated. It provides a fast first image while the complete metadata/file
set is prepared.

The defect was in both bridge-install paths in `QtFastContainer`. After taking
the old visible `QtSliceViewer` out of the layout, they called
`old_widget.setParent(None)` and then `deleteLater()`. On Windows, detaching the
visible child changes it into a top-level native widget. Deferred deletion runs
only after control returns to the event loop, leaving a short interval in which
Windows can present it as a standalone window. The measured Preview -> Complete
replacement interval matches the reported millisecond flash.

The correction is `_retire_embedded_viewer_widget`: hide the old viewer first,
retain its parent/Qt ownership, and schedule deferred deletion. Both the lazy
bridge installer and the normal series-switch installer use this authority.
The new viewer is still embedded and shown exactly as before. Preview loading,
complete-series promotion, force-reload semantics, DICOM decoding, viewer
identity, layout selection, and Advanced/VTK execution are unchanged.

## Files and invariants

- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`
  - Keep the `seriesThumbnailCard` style root-scoped and applied before children.
- `PacsClient/utils/windows_multiprocessing.py`
  - Never select a virtual-environment `pythonw.exe` redirector for spawn.
  - Keep supported `.venv` source and frozen/installed execution unchanged.
- `main.py`
  - Run that authority before `multiprocessing.freeze_support()`.
- `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/qt_fast_container.py`
  - Never detach an embedded viewer with `setParent(None)` during replacement.
  - Hide it, retain its parent, and use `deleteLater()`.
  - Do not suppress the Preview -> Complete upgrade as a duplicate switch.

The recurring `0x8001010d` OLE/COM diagnostic is a separate non-terminal issue.
Existing drag/drop deferral contracts remain unchanged.

**2026-09-13 integration note:** the Preview -> Complete path and the right-panel
immediate/progressive render paths are intentional parallel latency/safety strategies. They must
not be removed while repairing the separate card-identity, priority-routing, or manager-lifecycle
defects. Their provenance and guarded change order are documented in
`docs/plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md`.

## Regression evidence

The new FAST ownership guards failed before the fix:

- the retirement helper did not exist;
- both bridge-install paths detached the old child with `setParent(None)`.

After the correction:

- focused drop-replacement guard: **18 passed**;
- FAST/drop/progressive/lifecycle regression selection: **264 passed, 15
  skipped, 6 existing xfailed, 1 existing xpassed**;
- the multiprocessing policy and real Windows shared-Event probe are **7
  passed**;
- the focused download-manager, startup, shutdown, and package registry/builder
  selection is **59 passed, 4 deselected**;
- plugin materialization is **3 passed**, startup stage timing is **4 passed**,
  and runtime architecture logging is **4 passed**.

The real shared-Event guard and virtual-environment policy assertions both
failed before the download correction. Before the fix, the child recorded
`PermissionError`/WinError 5. After the fix it reads the set Event and exits
normally.

The unfiltered Download Manager suite cannot currently serve as a repository
gate: collection stops in
`test_instance_payload_key_variants.py` because the dirty worktree's test
expects `_INSTANCE_PAYLOAD_KEYS`, which its current `socket_client.py` does not
provide. A separate existing Nuitka ARM64 parity guard also fails because the
current build script lacks its expected `--arch` option. Neither target was
changed as part of this correction, and neither failure is reported as a pass.

The running source process has already imported the old bootstrap and viewer
class. Final acceptance therefore requires one human-controlled source restart,
then (1) download a study and confirm that series transfer begins without
WinError 5 or retry churn, and (2) drop an uncached FAST series that takes the
Preview -> Complete path and confirm that both stages appear without a separate
window flash. No installed executable or release build was launched during
this investigation.
