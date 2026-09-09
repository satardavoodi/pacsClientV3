# Large Local Import and Qt Re-entrancy Crash — 2026-09-05

## Status

- Root cause: diagnosed from application, stall-probe, native-fault, and Windows
  Application Error evidence.
- Source fix: implemented and guarded.
- Headless verification: complete for the affected import, local-viewer,
  multiframe/color, layout, overlay, and drag/drop boundaries.
- Live source-build verification: pending a human restart and import retry.
- Installed release: not built or deployed by this change.

No patient identity, DICOM payload, or clinical path is recorded in this report.

## Observed failure

The affected source session imported a large local folder containing 2,890
DICOM objects across 20 series (approximately 773 MB). The application copied
the files, then became unresponsive during local-database registration and
terminated while opening the imported study.

The termination was not a Python exception and was not caused by the PACS
server:

- the application log had no normal shutdown initiator or Python traceback;
- Windows Application Error Event 1000 attributed the terminating process to
  `python.exe` / `Qt6Core.dll` 6.10.2 with exception `0xc0000005`;
- the process ID in the Windows event matched the source GUI session;
- DICOM copy and preparation had already progressed into the local open path.

## Root cause

Two independent defects formed one crash chain.

### 1. Imported-study registration blocked the Qt thread

`_hp_import._import_folder_with_preview_impl()` called
`save_complete_study_info()` synchronously for every imported study. That
function enumerates every copied series folder, performs one header-only
`pydicom.dcmread()` per object, and writes the instance index to SQLite.

Header-only reads from IMP-2 remain correct and substantially reduce bytes
read, but they do not make a 2,890-file traversal suitable for the GUI thread.
The stall probe captured one continuous UI stall reaching 37.6 seconds in this
registration path. SQLite already uses thread-owned pooled connections, WAL,
and the main-process timeout policy, so the safe seam is the existing managed
import worker boundary rather than a schema, durability, or DICOM change.

### 2. Layout construction re-entered Qt with a partial viewport tree

`_vc_layout.apply_multi_viewer()` disabled updates, destroyed the old viewers,
and began constructing replacement viewers. Between viewer creations it called
`QApplication.processEvents()`. That call can run arbitrary queued timers,
switches, overlay work, and deferred deletes while the new layout is only
partially constructed.

The final stall samples returned from that nested event loop and entered the
loading-overlay path immediately before the native Qt access violation. This is
the same defect family documented in
`OVERLAY_REENTRANCY_CRASH_2026-08-26.md`; it was a remaining call site, not a
DICOM codec or transfer-syntax failure.

## Implemented correction

1. Imported studies are still registered sequentially and with the same
   `save_complete_study_info()` authority, inputs, return values, UID handling,
   path handling, and per-study failure list. The complete registration loop is
   now submitted through `_run_background_job_with_progress()`, which already
   owns scan, copy, and fast-viewer preparation workers.
2. `apply_multi_viewer()` no longer pumps the Qt event loop during layout
   mutation. Layout construction remains atomic; QWidget/VTK construction
   remains on the GUI thread as required by Qt.
3. Unexpected registration failure now reports that files were copied but the
   local index step failed. It does not misreport a copy failure or continue to
   auto-open an unregistered study.

## Boundaries deliberately unchanged

- No DICOM bytes are rewritten by registration.
- Transfer syntax, pixel data, color/YBR handling, frame expansion, cine timing,
  and decoder selection are unchanged.
- Study/Series/SOP Instance UIDs, raw Series Number, collision-aware storage
  folder, display alias, and multi-study offset identity are unchanged.
- Pixel-bearing object count, total frame count, metadata-only object handling,
  thumbnails, and Fast Viewer series selection are unchanged.
- Database schema, WAL mode, durability, busy timeout, and download-manager
  process behavior are unchanged.
- No new dependency, runtime module, feature flag, plugin payload, or build
  asset was introduced. The edited source modules are part of the normal
  application source bundle and have no packaged mirror.

## Regression guards and verification

`tests/code/system/test_import_registration_layout_crash_guard.py` failed on
the pre-fix source with three failures. It now proves:

- the import orchestration cannot call `save_complete_study_info()` directly on
  its UI path;
- registration is dispatched through the existing worker/progress authority;
- study order, arguments, failure reporting, and input identity are preserved;
- a real isolated SQLite index write happens on a worker thread without server
  access and without changing the synthetic DICOM file bytes;
- `apply_multi_viewer()` contains no `processEvents()` call.

The focused cross-boundary run passed 206 tests with three fixture-dependent
skips. It covered the new guard, overlay re-entrancy, import header reads,
import grouping/counting, Local/offline behavior, viewer layouts, viewport
replacement, multiframe/cine, color decode, and SeriesRef identity.

Packaging verification also passed without producing a release artifact:

- Python compilation passed for both changed runtime modules and the new guard;
- all 462 canonical/plugin mirror pairs matched; the changed modules have no
  separate plugin-payload copy;
- 38 release-candidate, plugin-registry/builder, Nuitka ARM64, and Windows Qt
  ICU hygiene guards passed, with four intentionally deselected cases;
- the Nuitka specification includes the complete `PacsClient` package, so the
  corrected modules use the same source path in the installed application.

## Live acceptance gate

After restarting the source build once, import a representative large local
folder and verify:

1. scan, copy, registration, and viewer preparation each complete once;
2. the registration phase does not produce a GUI-thread DICOM-read or SQLite
   stall stack;
3. the study auto-opens once and all expected series/thumbnails/images remain
   available;
4. no `Qt6Core.dll` access violation, orphan top-level viewer window, or
   unexpected process termination occurs;
5. application shutdown remains clean.

Do not claim the live defect closed until that restarted source-build run is
captured. A release build is a separate safety gate.
