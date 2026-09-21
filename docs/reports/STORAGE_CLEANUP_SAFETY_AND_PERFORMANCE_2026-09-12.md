# Storage Cleanup Safety and Performance — 2026-09-12

## Status

Source implementation and focused automated verification are complete. A source-build
operator run is still required before this work is called live-verified or release-ready.
This work is tracked as **OPT-59** in the canonical optimization master plan.

## Scope and authority

The canonical Viewer Configuration storage implementation is:

- `PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py`
- `modules/storage/local_storage_cleanup_manager.py`

`modules/storage/patient_cleanup_manager.py` is an unreferenced legacy implementation.
Do not reconnect it or add a third cleanup path. New storage cleanup behavior belongs in
`LocalStorageCleanupManager`, while the Qt panel remains presentation and orchestration only.

Disk is the source of truth for downloaded image availability. The database is the local
index. `studies.imported_at` is the retention authority for studies that have it;
`download_progress.created_at` and then DICOM StudyDate/StudyTime are compatibility fallbacks.

## Confirmed defects

1. Recursive folder sizing used `Path.rglob`, `is_file`, and `stat`, causing multiple
   filesystem operations per entry. A full measured scan exceeded 90 seconds.
2. Filtered cleanup trusted `studies.study_path` and could pass a path outside managed
   patient storage to `shutil.rmtree`.
3. File deletion errors were logged and swallowed; the database was then deleted anyway,
   creating silent orphan files.
4. Cleanup completion was connected through a bare Python lambda. A deterministic Qt probe
   showed the callback ran on the worker thread, where it could open dialogs and mutate UI.
5. QThreads were children of the transient settings panel, allowing panel destruction to
   destroy a running thread and abort the process.
6. Preview, consistency validation/repair, and logical-drive probing remained reachable on
   the GUI thread.
7. Two date options expressed the same operation, Clear ALL was the default, and the dialog
   showed neither reclaimable bytes nor unknown/unsafe selections.
8. Full database cleanup relied on foreign-key cascades and left child rows behind when a
   connection had foreign keys disabled.

## Implemented invariants

- Folder size and file count use one iterative `os.scandir` traversal. Directory links and
  reparse-point paths are not followed.
- A study deletion target must resolve strictly beneath the canonical patient-data root.
  Unsafe paths fail closed and retain the corresponding database record.
- If any authoritative DICOM folder for a patient cannot be removed, that patient's database
  rows are retained and the UI reports an incomplete cleanup. Thumbnail failure remains a
  visible cache warning and does not redefine DICOM authority.
- Full cleanup deletes instances, series, studies, and patients explicitly in child-to-parent
  order, then download progress, within the existing committed DB boundary.
- Cleanup, preview, consistency work, drive probing, and folder sizing run on workers.
  Worker results are captured by QObject slots and delivered only after QThread completion on
  the GUI thread.
- Background thread and worker wrappers have process-level ownership, not panel ownership.
  Application shutdown waits for a destructive job to reach a consistent boundary.
- The app owner injects one fail-closed activity probe. Destructive cleanup is refused while
  an import, active/pending download, or patient viewer tab can use the same storage.
- The bounded Imported On retention rule is selected by default. Clear ALL requires an
  explicit selection. Preview is recomputed before execution and includes selected count,
  estimated bytes, unknown dates, and rejected paths.
- Disk percentages use the actual managed-folder drive. A category spanning multiple drives
  is labelled as such instead of showing a false percentage. Low free space is red.

## Fail-before evidence

The new guards failed on the previous implementation for the expected reasons:

- recent local import was selected for deletion from its old acquisition date;
- an undatable patient was guessed into the oldest set;
- an external `study_path` was deleted and its DB row removed;
- a synthetic file lock was swallowed and its DB row removed;
- `Path.rglob` remained reachable in directory sizing;
- full cleanup left studies, series, and instances behind without FK cascades;
- cleanup completion ran on the worker thread;
- the cleanup QThread was parented to the transient panel.

Guards live in:

- `tests/code/storage/test_storage_cleanup_filtered.py`
- `tests/code/storage/test_storage_cleanup_consistency.py`
- `tests/code/storage/test_storage_cleanup_panel_async.py`

## Performance evidence

On the same local managed-storage workload, the previous full size scan exceeded 90 seconds.
After the single-pass traversal, the complete five-category scan took **2.915 seconds** and
returned approximately 59.9 GB. An immediate cache hit took **0.006 ms**. This is a source-run
engineering measurement, not a customer-hardware acceptance result.

## Automated verification

- Storage, cleanup, home-refresh, and GUI-thread disk guards: **59 passed**, exit code 0.
- Adjacent Settings lazy-init, settings integration, and download-state guards:
  **18 passed**, exit code 0.
- Python compilation for the three changed runtime modules: exit code 0.
- `git diff --check`: no patch whitespace errors.

No packaged mirror owns these core runtime files. No live database, DICOM payload, installed
executable, build output, or credential was changed.

## Required live gate

Use the source build only. The operator should open Viewer Configuration and verify:

1. the page paints immediately while sizes show a background-calculation placeholder;
2. totals complete without UI lag and Refresh remains responsive;
3. Preview reports a plausible selected count and reclaimable size;
4. cleanup is refused with an open patient tab and during an active import/download;
5. a small synthetic/local disposable selection cleans successfully and refreshes Local status;
6. closing/reopening Settings during a size scan does not crash;
7. no new native fault, application error, GUI-thread filesystem stack, or DB/disk mismatch
   appears in fresh logs.

Release/build validation remains separate and must follow `BUILD.md` and `RELEASE.md`.

## Rollback boundary

The patch is isolated to the canonical manager, storage panel, app-owned activity probe, guards,
and documentation. If live verification finds a regression, revert this OPT-59 slice as a unit.
Do not restore the unsafe GUI-thread callback or reconnect the legacy cleanup manager.
