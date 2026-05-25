# AIPacs Release Notes (Consolidated)

**Current Stable Version:** v3.0.9 (2026-05-25)
**Previous Stable:** v3.0.8 (2026-05-20)
**Release Date:** 2026-05-25
**Branch:** beta-version

---

## v3.0.9 (2026-05-25) - Workspace sync rollup: multi-study viewer, thumbnail pipeline, DB test isolation, Zeta DM review

### Summary

Consolidation release on top of v3.0.8 that bundles the accumulated workspace work since the last stable checkpoint and publishes it across all mirrored remotes.

### Included

- Multi-study single-tab viewer fix (offset-keyed series, grouped sidebar, repaint-suppressed rebuild) — see `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`
- Thumbnail pipeline audit and canonicalization (`THUMBNAIL_PATH/<study_uid>/<series_number>.png`) — see `docs/pipelines/thumbnail-pipeline.md`
- Database test-isolation hardening + production-DB cleanup tooling — see `COPILOT_REPORT_db_cleanup.md` and `tools/maintenance/cleanup_test_pollution.py`
- Zeta Download Manager review + fix plan (atomic DICOM/thumbnail writes, single GetStudyInfo probe, dead-gRPC quarantine) — see `docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`
- EchoMind viewer-chat updates, AI imaging service-tab fixes, reception report viewer updates
- Home panel / search service / right-panel thumbnail flow updates
- Settings UI, mainwindow UI, patient table widget polish
- Plugin package mirrors resynchronized for canonical module changes
- Runtime profile, config, and database manager updates

---

## v3.0.8 (2026-05-20) - Hardening rollup: DM retry, socket client, worker pool, UI fixes

### Summary

Hardening release on top of v3.0.7 incorporating all accumulated changes since the last stable checkpoint.

### Included

- DM retry / queue / worker-pool hardening
- Socket client improvements
- Viewer fast-container and interactor fixes
- Home panel / search service updates
- Plugin package mirrors synced
- Config and DB updates

---

## v3.0.7 (2026-05-19) - Stable backup and release freeze point

### Summary

This release marks the current beta branch state as a stable version checkpoint
and backup baseline for continued development.

Full details in [`VERSION_3.0.7_RELEASE.md`](VERSION_3.0.7_RELEASE.md).

### Included

- Stable snapshot of the current validated codebase
- Version marker alignment across runtime and documentation
- Local backup generation and GitHub publication workflow

---

## v3.0.6 (2026-05-18) - DB/UI/data-flow optimization rollup and repository organization

### Summary

This release consolidates the current optimization workstream across database operations,
UI/UI responsiveness paths, and data-flow stability improvements, together with
documentation and test re-organization updates.

Full details in [`VERSION_3.0.6_RELEASE.md`](VERSION_3.0.6_RELEASE.md).

### Included

- Database optimization updates and related persistence-path refinements
- UI/UI responsiveness and workflow updates across workstation/patient-tab paths
- Data-flow and coordination hardening in download/viewer/network pathways
- Documentation and test organization cleanup (archival/re-indexing)

---

## v3.0.3 (2026-05-16) - FAST-to-MPR route hardening and geometry boundary stabilization

### Summary

This release packages the FAST-to-MPR route fixes and geometry boundary hardening into the beta branch as a release snapshot.
Full details in [`VERSION_3.0.3_RELEASE.md`](VERSION_3.0.3_RELEASE.md).

### Included

- FAST MPR route resolution from FAST viewer state
- VTK bridge and audit-safe full-volume loading for MPR
- Geometry boundary guard logging and regression coverage
- Release snapshot updates and version marker alignment

### Validation Scope

- `tests/viewer/test_mpr_launch_route.py`
- `tests/viewer/test_mpr_vtk_load_bridge.py`
- `tests/architecture/test_backend_geometry_boundary_guards.py`
- `tests/viewer/test_fast_viewer_pipeline.py`

---

## v2.5.0 beta (2026-05-05) - FAST 2D cell separation: VTK-free viewer cells

### Summary

Replaces `VTKWidget` (which allocates a GPU context) with a lightweight
`QtFastContainer(QWidget)` in FAST mode (`BACKEND_PYDICOM_QT`).  Eliminates
40–80 MB GPU allocation and 100–400 ms initialisation time per cell in FAST
mode.  Advanced/VTK path is completely unchanged.
Full details in [`VERSION_2.5.0_RELEASE.md`](VERSION_2.5.0_RELEASE.md)
(beta section).

### Changes

- **`QtFastContainer`** — new VTK-free cell widget with `_NullVtkObject` /
  `_NullImageViewer` stubs.  Crash-site register C1–C9 covered.  Eagle Eye
  guard respected.
- **Package export** — `QtFastContainer` and `_NullVtkObject` exported from
  `vtk_widget` package.
- **`is_vtk_widget()`** — accepts `(VTKWidget, QtFastContainer, CurvedMPRViewport)`.
- **Factory switch** — both primary (`_pw_viewers.py`) and fallback
  (`_vc_layout.py`) factory methods return `QtFastContainer` when backend is
  `BACKEND_PYDICOM_QT`.

### Verification

- `pytest tests/viewer/test_fast_viewer_pipeline.py` → 167 passed, 1
  pre-existing failure (timing, unrelated to this change).

---

## v2.5.0 (2026-05-04) - Window Level split-button and toolbar stability release

### Summary

This release adds a split-button CT preset menu next to the Window Level tool and rolls in the required toolbar repairs so patient opening remains stable after the WL feature work.
Full details in [`VERSION_2.5.0_RELEASE.md`](VERSION_2.5.0_RELEASE.md).

### Fixes

- **Window Level split-button presets** - the toolbar now exposes CT presets for Lung, Abdomen, Brain, and Bone through a hamburger dropdown next to the main Window Level action.
- **FAST and Advanced support** - preset application routes to the active viewer target for both FAST and Advanced workflows.
- **Toolbar construction repair** - microphone timer/state initialization was restored so `ToolbarManager` setup does not break patient tab opening.
- **Toolbar wiring cleanup** - restored the AI Analyze button click path and removed an accidental stray callback from an unrelated error path.
- **Focused diff cleanup** - reverted unrelated Curved MPR drift so this release stays scoped to the WL feature and its follow-up repair.

### Verification

- `pytest tests/gui/qt/test_main_window_basic.py -q` passed.
- Offscreen `PatientWidget()` construction smoke passed.
- Latest May 4 log review showed no fresh runtime `ERROR` or `CRITICAL` entries for the validated run.

---

## v2.4.8c (2026-05-02) - Advanced MPR launch/install reliability build

### Summary

Reliability follow-up release to ensure installed builds always use the latest
Advanced MPR startup compatibility logic and cleanly upgrade from previous
installations.
Full details in [`VERSION_2.4.8c_RELEASE.md`](VERSION_2.4.8c_RELEASE.md).

### Fixes

- **Advanced MPR startup validation now checks all runtime script locations** -
  launcher compatibility validation accepts any valid runtime script among:
  source module path, legacy runtime `bin/Python/startup_script.py`, and
  plugin-python runtime path.
- **Clearer stale-runtime diagnostics** - when no compatible script is found,
  the message reports searched paths and missing markers, reducing false
  guidance and support ambiguity.
- **Release upgrade hygiene** - version bump to `2.4.8c` guarantees installer
  upgrade flow replaces old launcher code in deployed builds.
- **FAST clinical consistency during stacking** - OpenCV filtering remains
  enabled across wheel, drag, and settled frames so physicians see stable
  image appearance while navigating.
- **Sync slice mapping reuses geometry cache** - Qt bridge closest-slice lookup
  now uses pipeline-cached slice normal and positions when available, reducing
  repeated geometry recomputation during lock-sync/reference workflows.
- **Advanced backend switch persistence hotfix (2026-05-03)** - fixed installed
  behavior where explicit Advanced selection in Settings could be ignored:
  - `seed_user_config_defaults()` now preserves existing user backend config
    files instead of overwriting them at startup.
  - `_get_requested_viewer_backend()` now honors parent override only when
    configured backend is FAST; configured Advanced remains authoritative.
  - Added/updated backend precedence tests to prevent future regression.

### Verification

- Source launcher contains multi-candidate validation markers:
  `source_module_script` and `candidate_scripts`.
- Build completed and produced installer artifacts for this version.

---

## v2.4.7c (2026-05-02) — Conservative FAST additive cache growth

### Summary

Conservative FAST-mode cache stabilization release.  Progressive download growth
now preserves compatible pixel/frame cache entries instead of clearing the whole
FAST cache, keeps current-slice ownership stable during additive growth, and
adds reusable geometry metadata caching for active FAST viewers.
Full details in [`VERSION_2.4.7c_RELEASE.md`](VERSION_2.4.7c_RELEASE.md).

### Fixes

- **Additive cache growth** — new downloaded slices are appended and sorted while
  existing cache entries are remapped by slice file identity.
- **Stable current slice** — additive growth updates availability and slice count
  without forcing `set_slice()` or resetting the viewer position.
- **Geometry metadata cache** — repeated sync/reference-line geometry work can
  reuse cached basis vectors, stack normal, and slice positions.
- **Stacking jitter guard** — drag-time surrogates remain available for
  smoothness, but terminal slices, visibly far substitutes, and repeated
  non-near surrogates now fall through to exact rendering.
- **Surrogate diagnostics** — overlap logs now include `source_idx` and
  `source_dist` so requested-slice/displayed-source mismatches are measurable.

---

## v2.4.6 (2026-04-26) — Advanced MPR runtime compatibility guard

### Summary

Adds a fail-fast startup check that blocks the Advanced MPR module from launching
when the installed runtime payload (`startup_script.py`) is outdated.  Before this
fix, a stale runtime silently caused the Advanced Viewer to open in a generic
four-up / fourth-box layout instead of the correct Advanced MPR mode.
Full details in [`VERSION_2.4.6_RELEASE.md`](VERSION_2.4.6_RELEASE.md).

### Fix

- **Advanced MPR stale runtime payload guard** — `SlicerLauncherWorker._check_runtime_installed()`
  now calls a new `_validate_runtime_startup_script(runtime_root)` step that verifies
  the three required remote-command-server markers in `startup_script.py`.  If any
  marker is absent, launch is blocked and a clear reinstall dialog is shown to the user.
  **File:** `modules/mpr/advanced_3d_slicer/slicer_launcher.py`
- **Nuitka Advanced MPR package bridge** — the Nuitka external `advanced_mpr`
  package now includes both the Slicer runtime payload and the Python bridge at
  `payload/python/modules/mpr/advanced_3d_slicer`, with `python_paths: ["python"]`.
  This fixes installed Nuitka launch errors where the core could not import
  `modules.mpr.advanced_3d_slicer`.
- **Nuitka FAST/OpenCV verification** — the staged Nuitka `Engine/` now verifies
  `cv2.pyd`, `opencv_videoio_ffmpeg4130_64.dll`, and
  `config/pooyan_opencv_filter.json` for FAST mode parity.
- **Nuitka plugin/core boundary** — `modules.data_analysis` is staged as an
  external module package to keep analytics dependencies out of the compiled
  Nuitka core.

### Verification

Confirmed on installed build (2026-04-26):
- Stale runtime → dialog shows incompatible-runtime message; no process launched.
- After module reinstall → Advanced MPR launches correctly in Advanced MPR mode.
- Nuitka checks passed: `--smoke-test`, `check_module_plugin_readiness.py`, and
  `check_build_coherence.py`.

---

## v2.4.5 patch (2026-04-26) — MPR frozen-build crash + user_data_root writable fallback

### Summary

Post-release patch applied on top of v2.4.5.  No version number bump; the installer
produced on 2026-04-26 is a corrected v2.4.5 build.
Full details in [`VERSION_2.4.5_RELEASE.md`](VERSION_2.4.5_RELEASE.md) §Post-release patches.

### Fixes

- **MPR frozen-build crash** — `sys.stdout.flush()` called inside
  `_log_orientation_info()` crashes with `'NoneType' object has no attribute 'flush'`
  in no-console PyInstaller builds.  Fixed in `_mpr_orientation.py` and
  `standard_mpr_viewer_original.py` by returning early when `sys.stdout is None`.
- **`user_data_root()` writable fallback** — On machines where
  `Program Files\AIPacs\User Data` is not writable (e.g., non-admin users or strict
  group policies), the runtime now falls back to `%LOCALAPPDATA%\AIPacs\user_data\`
  instead of crashing on first write.  Added `_is_path_writable()` helper in
  `aipacs_runtime.py`.
- **Build script ASCII-safe print** — `builder/build_release.py` replaced Unicode `→`
  with ASCII `->` in two print statements to prevent `UnicodeEncodeError` on Windows
  consoles without UTF-8 mode active.

---

## v2.4.5 - Advanced MPR launch UX + structural FAST refit guard (2026-04-25)

### Summary

Stabilizes Advanced MPR launch UX for long startup times and restores the structural
fix for the FAST viewer corner-zoom regression in installed builds.
Full release notes in [`VERSION_2.4.5_RELEASE.md`](VERSION_2.4.5_RELEASE.md).

### Highlights

- Advanced MPR loading overlay now uses user-facing text aligned with product naming:
  `AI Advanced Analysis is launching` -> `AI Advanced Analysis launched`.
- Loading overlay now remains visible until launch-readiness is confirmed from runtime
  startup criteria (not just process spawn):
  - preferred marker in startup log: `STARTUP SEQUENCE COMPLETED SUCCESSFULLY`
  - fallback: process remains stable with startup log output.
- FAST viewer structural fix: startup refit callbacks are now epoch-guarded so stale
  delayed callbacks from older bursts cannot re-apply an outdated fit and shrink the
  image into a corner after drag-drop/layout churn.
- Added build/integration documentation for Advanced MPR runtime packaging and
  anti-regression validation gates.

---

## v2.4.4 - Nuitka Pipeline Sync After Docs Reorganization (2026-04-25)

### Summary

Captures post-pull synchronization work for the staged Nuitka pipeline after repository docs/build-structure updates.
Full release notes in [`VERSION_2.4.4_RELEASE.md`](VERSION_2.4.4_RELEASE.md).

### Highlights

- Pulled latest upstream and synced with updated Python build structure in `builder/`.
- Kept canonical Nuitka planning in `builder/docs/NUITKA_BUILD_PLAN.md`.
- Added `builder/docs/NUITKA_BUILD_AGENT_HANDOFF.md` for operator/agent continuity.
- Updated `builder/docs/README.md` so both Nuitka docs are discoverable in build docs index.
- Preserved build-system boundary (`builder/` PyInstaller vs `builder nuitka/` Nuitka staged pipeline).

---

## v2.4.7 - Build warning cleanup + spec hardening (2026-04-24)

### Summary

Eliminates all actionable build warnings from v2.4.6 log. Three changes:
1. Inno Setup `Architecture "x64"` deprecation warning fixed.
2. Dev-only `test.py` excluded from PyInstaller bundle to remove spurious missing-module warnings.
3. All remaining warnings in `warn-appA_workstation.txt` confirmed as known false positives (third-party optional deps).

### Changes

- **`builder/installer/AIPacs_Setup.iss`**: Changed `ArchitecturesInstallIn64BitMode=x64` to
  `ArchitecturesInstallIn64BitMode=x64compatible` — resolves Inno Setup 6 deprecation warning.
- **`builder/spec/appA_workstation.spec`**: Added `PacsClient.pacs.patient_tab.utils.test` to
  the `excludes` list — removes spurious `missing module named image_filters / utils` warnings
  that appeared because the dev test file uses bare (non-relative) imports.
- **`pyproject.toml`**: version bumped to `2.4.7`.
- **`builder/plugin package/packages/*/module_package.json`**: version bumped to `2.4.7` (all 11 packages).
- **`builder/docs/BUILD_CHECKLIST.md`**: Added PyInstaller warnings file guidance section and
  production test file exclusion note.

### Root cause detail

- **Architecture warning**: Inno Setup 6 deprecated the `"x64"` architecture identifier in favour
  of `"x64compatible"` (handles both native x64 and ARM64 Windows). Using the old identifier
  caused Inno Setup to emit `Warning: Architecture identifier "x64" is deprecated` and return
  exit code 1, which could mask real errors.
- **test.py imports**: `PacsClient/pacs/patient_tab/utils/test.py` is a legacy dev helper that
  imports `image_filters` and `utils` as bare top-level names (not proper package paths). PyInstaller
  attempted to trace these imports, emitting top-level `missing module` warnings even though the
  file is never used in production. Excluding it from the bundle eliminates the noise.

### Validation

- Build log contains no `Architecture identifier` deprecation warning.
- Build log contains no `missing module named image_filters` or `missing module named utils` entries.
- All remaining `warn-appA_workstation.txt` entries are third-party optional deps (numpy, pandas, comtypes, anyio, etc.) — confirmed harmless.

---

## v2.4.6 - Printing Module `data/` Package (2026-04-23)

### Summary

Fixes `ModuleNotFoundError: No module named 'modules.printing.data'` that occurred
on installed machines when the Printing module was enabled. The root cause was a
two-layer omission: the `data/` subpackage was missing from both the main codebase
**and** the plugin package (the canonical production runtime path).

### Changes

- **`modules/printing/data/`** (new): Created 4 files:
  - `__init__.py` — exports `get_series_for_study`
  - `series_repository.py` — DB + filesystem DICOM path resolver
  - `filming_manager.py` — save/load/delete filming page PNG+JSON sidecars
  - `dicom_enrichment.py` — series list enriched with live on-disk file counts
- **`builder/plugin package/packages/printing/payload/python/modules/printing/data/`** (new):
  Identical copy of all 4 files for the plugin package (production runtime override path).
- **`.gitignore`**: Added `!modules/*/data/` exception so Python packages inside
  `data/` directories are not accidentally excluded from git.
- **`builder/docs/BUILD_CHECKLIST.md`**: Added Dual-Location Rule section,
  pre-build dependency checks, and Inno Setup exit-code-1 false-alarm note.
- **`builder/docs/BUILD_DOCUMENT.md`**: Added §F Plugin Package Architecture
  and filled §G Known Issues with v2.4.5 and v2.4.6 documented entries.

### Root cause detail

When the Printing module is enabled, its plugin package prepends
`payload/python/` to `sys.path` before the PyInstaller `engine/` bundle.
This means `modules.printing` is loaded from the **plugin package**, not the bundle.
Fixing only the main codebase (bundled path) is insufficient — the plugin
package must also carry the `data/` subpackage.
See `builder/docs/BUILD_DOCUMENT.md §F` for the full Dual-Location Rule.

### Validation

- Both pre-build checks in `BUILD_CHECKLIST.md` pass (main codebase and plugin paths).
- Build log contains no `ModuleNotFoundError` entries.
- `ai-pacs installer v2.4.6.exe` = 458.8 MB (2026-04-23).

---

## v2.4.5 - OpenCV / cv2 Dependency Fix (2026-04-23)

### Summary

Fixes `ImportError: No module named 'cv2'` that caused the FAST viewer to fall
back to the VTK backend on launch, displaying an incorrect "Advanced" badge and
breaking drag-drop series switching.

### Changes

- **`modules/viewer/fast/opencv_filter_pipeline.py`**: Wrapped `import cv2` in a
  `try/except ImportError` guard so the module loads gracefully when OpenCV is
  unavailable at runtime.
- **`builder/requirements/build_requirements.txt`**: Added `opencv-python-headless`
  so it is installed in `.venv_build` and bundled by PyInstaller.
- **`builder/inventory/imports_summary.json`**: Added `cv2` to
  `suggested_hiddenimports` so PyInstaller explicitly collects the extension module.

### Root cause

`opencv-python-headless` was not listed in the build venv requirements. PyInstaller
could not collect the `cv2` extension, so it was absent from the installed bundle.
Without OpenCV the filter pipeline import failed, which propagated up to the
backend selector and forced VTK fallback.

### Validation

- FAST viewer starts with `BACKEND_PYDICOM_QT` (verified via `[BACKEND_SWITCH]`
  startup log line).
- "Advanced" badge only appears when Advanced mode is explicitly selected.
- `ai-pacs installer v2.4.5.exe` = 458.8 MB (2026-04-23).

---

## v2.4.3 - Incremental Build Pipeline / Installer Artifact Fix (2026-04-25)

### Summary

Hardens the PyInstaller build pipeline with incremental dist-sync, a build lock,
and correct installer artifact preservation. Subsequent builds after a single
source-file change complete in under 30 seconds instead of ~5 minutes.
Full release notes in [`VERSION_2.4.3_RELEASE.md`](VERSION_2.4.3_RELEASE.md).

### Highlights

- **Incremental dist-sync**: PyInstaller writes to `dist_tmp/`, then only changed
  files are patched into the live `dist/AIPacs/` folder via
  `sync_dist_bundle_incremental()`. SHA-256 content comparison prevents false
  copies for timestamp-only changes. Typical result: `1 copied, 9484 skipped`.
- **Build lock**: `builder/output/.build.lock` prevents two concurrent build
  processes from racing over the same output directory.
- **`preserve_installer` fix**: `clean_outputs()` now preserves
  `builder/output/installer/` on incremental and `--skip-installer-compile` runs,
  so previously compiled installers survive across build phases. Previously the
  installer folder was always deleted even when ISCC was not invoked.
- **Confirmed installer output**: `builder/output/installer/` now consistently
  contains `ai-pacs installer.exe`, versioned copy, SHA256 checksums, and
  install notes after a full build.
- Version metadata bumped `2.3.7 → 2.4.3` in `main.py` and `pyproject.toml`.

### Validation

- `build.py --skip-pyinstaller`: exit code 0, installer produced.
- Incremental sync: `0 copied, 9484 skipped, 1 removed` after single-file change.
- `build.py --skip-pyinstaller --skip-installer-compile`: installer folder preserved.

---

## v2.3.7 - Stack-Drag Smoothness Stabilized / R13 Revert (2026-04-22)

### Summary

Finalizes the FAST-viewer stack-drag smoothness work. Worst-case `ui_lag_max`
on long drags drops from ~412 ms (log 99) to ~280 ms (log 100), and
short-drag `ui_lag_max` drops from ~150 ms to ~60 ms. Full release notes in
[`VERSION_2.3.7_RELEASE.md`](VERSION_2.3.7_RELEASE.md).

### Highlights

- **R13 reverted to opt-in** (`AIPACS_DRAG_SUBPROC_THROTTLE=1`). Default-on
  in the v2.3.7-dev iteration caused a priority-inversion regression on the
  `multiprocessing.Queue` IPC mutex (viewer at ABOVE_NORMAL blocked on a lock
  held by an IDLE-scheduled subprocess thread). Unconditional
  `BELOW_NORMAL_PRIORITY_CLASS` at subprocess startup is retained — it
  provides viewer/download separation without mutex starvation.
- **`[SP]` subprocess logs now visible** when R13 is enabled. Each log site
  passes `extra={"component": "ipc"}` so they bypass the default
  `component=download` WARNING threshold that was silently dropping them.
- **Drag hot-path tightening.** `QtViewerBridge._apply_interaction_target()`
  no longer runs the `has_object` / `request_object` loop when the default
  `NoopObjectCache` is in place (pure overhead in FAST mode). New
  `is_noop_object_cache()` probe in `modules/viewer/fast/object_cache.py`.
- **R14 codified** in `.github/copilot-instructions.md`: surrogate hot-path
  reads of `_last_surrogate_pixel_idx` / `_surrogate_repeat_count` must use
  `getattr` to tolerate test stubs that bypass `__init__`.
- Version metadata bumped 2.3.5 → 2.3.7 across `main.py`, `pyproject.toml`,
  `build_nuitka.py`, all `builder/plugin package/packages/*/module_package.json`,
  `README.md`, `docs/README.md`, and the builder docs.

### Validation

- 168/168 tests pass across `test_fast_viewer_pipeline.py`,
  `test_priority_retry_dedup.py`, `test_socket_client_cancellation.py`.
- Log 100 (PC A, Windows, low-config) shows worst `ui_lag_max_ms` = 280,
  avg ~150. `handler_p95_ms` ≈ 2 on all drag KPIs. Cache `src=hit` ratio
  dominant across multi-second drags.

### Notes

- Rules R1–R12, R14 from v2.3.6 remain intact. R13 is the only rule whose
  default state changed; its infrastructure (viewer-side flag touching,
  subprocess-side poller, env gate) is preserved behind the opt-in env var.

---

## v2.3.5 - Stable Workspace Snapshot / Backup / GitHub Sync (2026-04-19)

### Summary

Publishes the current workspace as **v2.3.5** and marks this repository state as
the new local stable checkpoint before the next development round.

### Highlights

- Updated the application version in `main.py` to `2.3.5`
- Updated the package version in `pyproject.toml` to `2.3.5`
- Updated the Windows product version in `build_nuitka.py` to `2.3.5`
- Updated builder package feed and module package manifests under
  `builder/plugin package/packages/` to `2.3.5`
- Refreshed current stable references in `README.md`, `docs/README.md`,
  `builder/docs/WINDOWS_RELEASE_FLOW.md`, and
  `builder/docs/INSTALLER_QA_CHECKLIST.md`
- Recorded `v2.3.5` as the current stable release note and local backup target

### Validation

- Version metadata updated consistently across app, package, builder, and
  release-tracking files
- Local backup target prepared under `backups/v2.3.5_2026-04-19/`
- GitHub connectivity/push readiness checked from the current workspace

### Notes

- This entry records the repository publication state for the `v2.3.5` stable
  checkpoint.
- Existing earlier unreleased entries remain below as historical context for
  work that may also be included in this checkpoint.

---

## Unreleased — Download preemption backoff hardening (2026-04-18)

### Summary

Reduced Block-1 preemption latency by making socket retry/reconnect backoff waits
cancellation-aware and by classifying cancelled reconnects as auto-pause/preemption
instead of ordinary series failure.

### What changed

- `modules/download_manager/network/socket_client.py`
  - added sliced sleep helpers for sync/async retry waits
  - `send_request()` now aborts retry backoff immediately when cancellation is requested
  - `connect_with_retry()` now aborts reconnect backoff immediately when cancellation is requested
  - batch retry backoff/reconnect now exits early on cancellation instead of walking the full retry ladder
- `modules/download_manager/download/series_downloader.py`
  - reconnect failures caused by cancellation/preemption now return the standard auto-paused/preemption result
  - added `_build_preempted_result(...)` helper so preemption exits stay consistent across early-return paths
- added focused regressions in `tests/download_manager/test_socket_client_cancellation.py`

### Why this matters

Before this change, a preempted download could still be stuck sleeping inside reconnect
or retry backoff. The worker pool slot remained occupied until that stale retry path
finished, which could delay the next critical start enough to trigger
`[INTENT] Priority start retry exhausted ...` in live runs.

### Validation

- `python -m pytest tests/download_manager/test_priority_retry_dedup.py tests/download_manager/test_socket_client_cancellation.py -v`
  - Result: **8 passed, 3 warnings**
- `python tests/download_manager/run_dm_test.py`
  - Result: **exit code 0**

---

## v2.3.4 - FAST Protected-UI Deadlock Fix / Stable Checkpoint (2026-04-18)

### Summary

Publishes the current workspace as **v2.3.4** and records the FAST viewer
stability fix that removed the protected-UI deadlock behind the “first series
loads, second viewer stalls/crashes” startup failure.

### Highlights

- Fixed a self-deadlock in `modules/viewer/fast/system_load_controller.py`
  triggered by protected-UI prefetch admission deferrals
- Restored stable second-viewer startup for FAST `pydicom_qt` layouts where the
  second series previously stalled during `QtViewerBridge.set_slice(...)`
- Added a targeted regression in
  `tests/viewer/test_system_load_controller.py` covering repeated protected-UI
  `PREFETCH` admissions for the same key
- Updated release docs, app metadata, builder metadata, and package manifests
  to publish `v2.3.4` as the current stable workspace version

### Validation

- `python -m pytest tests/viewer/test_system_load_controller.py -q`
  - Result: **21 passed**
- Offscreen two-viewer reproduction using series `4` then series `7`
  - Result: second viewer completed `set_slice(mid)` and
    `apply_default_window_level(mid)` without hanging

### Notes

- Historical `v2.3.3`, `v2.3.2`, `v2.3.1`, and earlier release entries remain
  below as prior stable references.
- This release is the new local stable checkpoint before further heavy-series
  lag investigation.

---

## Unreleased — FAST execution plan Phase 1/2 package updates (2026-04-16)

### Summary

Recorded the two most recent FAST overlap execution-plan packages in the workspace:

- **Phase 1** thumbnail/progress projection cleanup
- **Phase 2** shared progressive terminal-owner cleanup

Together these changes reduce low-value thumbnail churn and remove duplicate progressive terminal follow-up around the shared finalizer.

### Phase 1 — thumbnail/progress projection cleanup

- `ThumbnailManager` now keeps stable per-series projection state and stable total-count memory
- repeated start/complete transitions are idempotent and skip redundant overlay/border/count-label writes
- `_hp_priority.py` no longer injects direct thumbnail per-progress updates during priority flow; the thumbnail contract is now projection-style `start → stable total → complete`
- active download count stays stable as `N images`; completion finalizes as `N/N`

### Phase 2 — shared progressive terminal owner cleanup

- Layer 2b, Layer 3, and Layer 4 now rely on `_finalize_progressive_series(...)` as the single terminal close owner
- Layer 2b final close now passes matched viewers into the shared finalizer instead of doing duplicate close/update work around it
- Layer 3 and Layer 4 no longer add duplicate post-finalize corner/thumbnail follow-up after the shared finalizer runs
- added regressions proving Layer 2b delegates terminal close through the shared finalizer and Layer 3 does not duplicate finalize follow-up work

### Validation

- Phase 1 focused validation:
  - `tests/fast/test_fast_thumbnail_vs_download_separation.py`
  - `tests/fast/test_thumbnail_progress_state_binding.py`
  - `tests/fast/test_series_completion_state_transition.py`
  - `tests/fast/test_series_download_order_top_to_bottom.py`
  - `tests/ui_services/test_lifecycle_hygiene.py`
  - Result: **61 passed**
- Phase 2 focused validation:
  - `tests/viewer/test_fast_viewer_pipeline.py`
  - `tests/viewer/test_b43_progressive_lifecycle_state.py`
  - `tests/viewer/test_dragdrop_progressive.py`
  - Result: **128 passed, 3 warnings**

---

## Unreleased — FAST overlap layout churn guard (2026-04-16)

### Summary

Reduced the “new series inserted into layout” hitch during simultaneous download + viewing by preventing two redundant viewer-side actions:

- an untargeted background series starting a first progressive display load while all viewers were already occupied
- a completed series being reloaded again after Layer 2b had already grown the active viewer to the final disk count

### Fixes

- `_start_progressive_display()` now defers untargeted first-display work once a first series is already visible and there is no empty or explicitly awaiting viewer
- untargeted background first-display deferral is now sticky until layout eligibility changes, so later progress pulses do not keep retrying the same blocked `_start_progressive_display()` path
- `load_series_on_demand()` now skips the redundant post-completion reload when any viewer already shows the completed series at the current disk count
- `load_series_on_demand()` now also short-circuits untargeted FAST-mode background completions when no viewer is empty, awaiting that series, or already showing it; the series is marked ready and progressive lifecycle state is finalized without running the viewer-completion/reload path
- viewer/sidebar sync now avoids redundant state writes: unchanged available-slice counts are skipped, append-only metadata grows extend in place, and thumbnail overlay/border/count-label updates no-op when already current
- added focused regressions in `tests/viewer/test_fast_viewer_pipeline.py`

### Validation

- `python -m pytest tests/viewer/test_fast_viewer_pipeline.py -q`
- `python -m pytest tests/fast/test_thumbnail_progress_state_binding.py -q`
- Result: **87 passed, 3 warnings** (`test_fast_viewer_pipeline.py`) and **13 passed** (`test_thumbnail_progress_state_binding.py`)

---

## v2.3.3 - FAST Viewer Stabilization / Release Metadata Sync (2026-04-14)

### Summary

Publishes the current workspace as **v2.3.3** and aligns the application,
package, build, installation, update-feed, and release-tracking metadata with
that version.

### Highlights

- Updated the application version in `main.py` to `2.3.3`
- Kept the package version in `pyproject.toml` at `2.3.3`
- Kept the Windows product version in `build_nuitka.py` at `2.3.3`
- Updated the plugin package feed and package manifests under
  `builder/plugin package/packages/` to `2.3.3`
- Promoted current viewer/performance release docs from `v2.3.3-dev` to
  published `v2.3.3`
- Refreshed the build/install-facing docs and current-stable links for the
  `2.3.3` publication
- Included the current documentation, tests, and active plan documents in the
  published workspace state

### Notes

- Historical `v2.3.2`, `v2.3.1`, and earlier release entries remain below as
  prior stable references.
- This entry records the repository publication state; build artifact
  regeneration should be verified from the current workspace before external
  distribution.

---

## v2.3.1 - Workspace Publication / Release Metadata Sync (2026-04-13)

### Summary

Publishes the current workspace as **v2.3.1** and aligns the application,
package, build, installation, and release-tracking metadata with that version.

### Highlights

- Updated the application version in `main.py` to `2.3.1`
- Updated the package version in `pyproject.toml` to `2.3.1`
- Updated the Windows product version in `build_nuitka.py` to `2.3.1`
- Updated the plugin package feed and package manifests under
  `builder/plugin package/packages/` to `2.3.1`
- Refreshed the build/install-facing docs and current-stable links for the
  `2.3.1` publication
- Included the current documentation, tests, and active plan documents in the
  published workspace state

### Notes

- Historical `v2.3.0` release entries remain below as prior stable references.
- This entry records the repository publication state; build artifact
  regeneration should be verified from the current workspace before external
  distribution.
## Unreleased ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Thumbnail system stabilization (v2.3.3+thumb-stable)

### Summary

Fixed intermittent thumbnail not-showing bug and eliminated hot-path stdout I/O
flood in `ThumbnailManager`.

### Root Cause 1 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ `set_server_series_info` double-call overwrites gRPC data

`_hp_patient_open.py` calls `set_server_series_info` twice:
1. **Line 268 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ main async thread**: from `study_data['series']` (server response at double-click)
2. **Line 343 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ background `threading.Thread`**: from `right_panel_widget._current_series_info`
   or a fresh `get_series_info_from_server()` call

The old implementation unconditionally replaced `_server_series_info` on every call.
The second call arrived after the gRPC thumbnail fetch had already enriched
`image_count` per series.  This caused:
- gRPC-fetched `image_count` values silently discarded (count badges show wrong value)
- `_series_uid_to_number` mapping cleared mid-session ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ DM `_resolve_sn` falls back
  to DM task list for all subsequent signals instead of the fast O(1) map
- A redundant `_load_server_thumbnails` job queued even when thumbnails were
  already on screen

### Fix 1 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Merge instead of overwrite (`_pw_thumbnails.py`)

`set_server_series_info` now distinguishes first vs subsequent calls:
- **First call**: full replace (same as before)
- **Subsequent calls**: merge-only ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ only adds genuinely new series (not in existing
  `_server_series_info`); never overwrites `image_count` or `series_description`
  that were already populated; only schedules a new `_load_server_thumbnails` if
  there are new series AND the previous load is not still running.

This preserves all enriched gRPC data across multiple `set_server_series_info`
calls.

### Root Cause 2 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Hot-path `print()` flood in `ThumbnailManager`

`ThumbnailManager` had ~35 `print()` calls, several in very hot paths:
- `start_series_download` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ called once per series download start
- `update_series_progress` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ called on every single progress tick (potentially
  hundreds of times per study)
- `complete_series_download` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ called once per series completion
- `apply_border_states_new` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ called after every state change

`print()` is synchronous stdout I/O.  On Windows, each call acquires the console
lock, blocking the calling thread for 0.1ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œ2ms.  During a 6-series study with
progress events every 100ms this adds up to dozens of ms of unnecessary blocking.

### Fix 2 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Replace `print()` with `_tm_logger.debug()` / `.exception()`

All 35 `print()` calls in `ThumbnailManager` converted to logger calls.  Debug
messages are suppressed at the default `INFO` level (zero runtime cost).  Error
handlers upgraded to `_tm_logger.exception()` so stack traces are preserved in
log files without going to stdout.

### Fix 3 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Memory leak in `_thumb_pipeline_start`

`complete_series_download` now uses `.pop(series_key, None)` instead of `.get()`
so completed per-series timing entries are cleaned up immediately.

### Files Changed
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py`
  ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ `set_server_series_info` merge logic
- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`
  ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ All print() ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ logger; memory leak fix
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_panels.py`
  ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Removed two debug-only prints from `add_thumbnail_to_thumbnail_layout`

## Unreleased ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ pydicom_qt ITK pipeline bypass (v2.3.3)

### Summary

**Eliminated a 6ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œ9 second wasted ITK stall every time a series was opened in FAST
(pydicom_qt) mode.**

### Root Cause

`load_single_series_by_number` called `resolve_viewer_backend(metadata=None, ...)`.
Because `metadata=None` means `instances=[]`, the `BACKEND_PYDICOM_QT` guard inside
`resolve_viewer_backend` fell back to `BACKEND_VTK`, and the full ITK pipeline ran:

| Step | Time (MR 11 slices) | Time (MR 25 slices) | Used? |
|---|---|---|---|
| SimpleITK read | ~170ms | ~170ms | **Wasted** |
| `apply_filters()` SimpleITK | **6,884ms** | **9,437ms** | **Wasted** |
| `convert_itk2vtk()` | 11ms | 24ms | **Wasted** |
| Qt bridge `open_series` | ~60ms | ~80ms | ط·آ£ط¢آ¢ط·آ¥أ¢â‚¬إ“ط£آ¢أ¢â€ڑآ¬ط¢آ¦ Actual display |

For every series click in FAST mode, 7ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œ10 seconds of ITK work was discarded
because `_bind_backend_from_metadata` (called by `switch_series`) selected
`pydicom_qt` from the user's viewport setting, ignoring the VTK payload entirely.

### Fix

Added a `BACKEND_PYDICOM_QT` fast-path early exit in `load_single_series_by_number`
**before** the `resolve_viewer_backend` call:

1. Detected by: `allow_lazy_backend and viewer_backend == BACKEND_PYDICOM_QT`
2. Builds series metadata only (from DB or DICOM headers) ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ same data the Qt bridge
   needs, taking ~0ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œ5ms
3. Creates a minimal stub `vtkImageData` (correct rowط·آ·ط¢آ£ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œcolط·آ·ط¢آ£ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œslice dimensions, no pixel
   data) so downstream `vtk_data is not None` cache-key checks continue working
4. Annotates metadata with `viewer_backend=pydicom_qt` so `_bind_backend_from_metadata`
   confirms the selection without ambiguity
5. Yields and returns ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ the full ITK+SimpleITK pipeline never runs
6. Falls back to the ITK pipeline if metadata build fails (safe degradation)

**Advanced mode (`vtk_simpleitk`) is completely unaffected** ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ the early exit only
triggers when `viewer_backend == BACKEND_PYDICOM_QT` is passed explicitly.

### Files changed

- `PacsClient/pacs/patient_tab/utils/image_io.py` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ `BACKEND_PYDICOM_QT` import +
  fast-path early exit in `load_single_series_by_number`

### Expected series-switch latency after fix

| Modality | Before (FAST mode) | After (FAST mode) |
|---|---|---|
| MR 11 slices | ~7,200ms | ~300ms |
| MR 25 slices | ~9,750ms | ~350ms |
| CT 50+ slices | ~3,000ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œ5,000ms | ~300ms |

---

## v2.3.0 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Stable Release / Installer, Modules, and Cross-PC Delivery (2026-04-04)

### Summary

This release publishes **v2.3.0** as the current stable AIPacs version and finishes the release packaging work for deployment on other PCs.

### Highlights

- Installer flow clarified so `Custom` setup explicitly lets the operator choose optional modules for the target workstation.
- Graphics setup clarified so the installer recommends GPU usage when Windows detects a likely supported GPU, while the application still validates the decision again on first launch.
- First-launch module bootstrap remains tied to `installation_profile.json`, so setup-selected packages are copied during install and activated automatically when the app starts.
- Build metadata and release notes were aligned to describe the real staging output, installer artifacts, and cross-PC validation path.
- Canonical documentation for the modular structure, home UI services, network layer, and download pipeline was refreshed around the `2.3.0` stable release.

### Installer and Deployment Notes

- Core modules are always installed.
- Optional modules are selected per PC during `Custom` setup.
- The target machine can still add or change optional modules later from `Settings -> Installation Module`.
- Systems without a usable GPU are expected to run through the software OpenGL fallback path.

---

## Unreleased ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Viewer Metadata Sync + Defensive W/L Bounds (v2.2.8.7)

### Summary

Fixes the **white images from slice N onward** bug observed during progressive download.
When a series was opened during download (e.g. 22 slices on disk) and new slices arrived
via progressive grow (up to 135), the VTK viewer's `apply_default_window_level(n)` would
crash with `IndexError` for any slice `n >= 22` because the viewer held a stale deep-copy
of the metadata.  The exception was silently swallowed, leaving VTK's color mapper with
the last-applied W/L ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ which clipped the different-anatomy slices to **white (255)** or
rendered them with incorrect contrast.

Also fixes the same IndexError crash paths in `set_window_level`, `update_corners_actors`,
and `load_bottom_left_actors` with defensive bounds-checking and auto-fallback.

### Root Cause

**The stale metadata deep-copy problem:**

```
                     Creation time (22 slices on disk)
                     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¥أ¢â‚¬â„¢ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ¯
lst_thumbnails_data  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک metadata["instances"] = [22] ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œط£آ¢أ¢â€ڑآ¬أ¢â‚¬ع†ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ SOURCE OF TRUTH
                     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¢ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ©
                                    ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک copy.deepcopy()
                     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¥أ¢â‚¬â„¢ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ“ط·آ¢ط¢آ¼ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ¯
ImageViewer2D        ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک self.metadata["instances"]   ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œط£آ¢أ¢â€ڑآ¬أ¢â‚¬ع†ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ STALE COPY (never updated)
                     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک = [22] (frozen at creation)  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
                     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ©

                     After grow (135 slices on disk)
                     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¥أ¢â‚¬â„¢ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ¯
lst_thumbnails_data  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک metadata["instances"] = [135]ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œط£آ¢أ¢â€ڑآ¬أ¢â‚¬ع†ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Updated by _refresh_stored_metadata_instances
                     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ©
                     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¥أ¢â‚¬â„¢ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ¯
ImageViewer2D        ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک self.metadata["instances"]    ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œط£آ¢أ¢â€ڑآ¬أ¢â‚¬ع†ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ STILL [22]!
                     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک = [22] (never synced)         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
                     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ©

When user scrolls to slice 23:
  apply_default_window_level(23)
    ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ self.metadata['instances'][23]  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط·آ¹ط¢آ¯ IndexError! (only 22 entries)
    ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ exception swallowed ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ VTK keeps last-applied W/L
    ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ pixels clipped to white
```

The deep-copy happens in `create_new_vtk_widget()` at line 3553:
```python
metadata = copy.deepcopy(thumbnail_item['metadata'])
```

And in `_clone_metadata_for_switch()` (shallow clone, shares `instances` by reference ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’
but the creator path uses `deepcopy`):
```python
cloned = dict(metadata)
```

The `_refresh_stored_metadata_instances()` method correctly mutates the *source* dict in
`lst_thumbnails_data` (in-place: `metadata["instances"] = new_instances`), and updates
the series cache.  But the live `ImageViewer2D.metadata` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ which is a separate object
from `copy.deepcopy()` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ was never patched.

### Metadata Object Graph

```
ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¥أ¢â‚¬â„¢ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ¯
ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک                   lst_thumbnails_data[i]              ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¥أ¢â‚¬â„¢ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ¯     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک "metadata" ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ“ط·آ·أ¢â‚¬ط›  { "series": {...},          ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک                   "instances": [0..N-1] }   ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œط£آ¢أ¢â€ڑآ¬أ¢â‚¬ع†ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ _refresh_stored_metadata_instances
ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ©     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک    mutates THIS dict
ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¥أ¢â‚¬â„¢ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ¯     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک "vtk_image_data" ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ“ط·آ·أ¢â‚¬ط› vtkImageData           ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ©     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ©
                       ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
                       ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک _series_cache[sn] = (vtk_data, metadata, idx)
                       ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک   ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬ط¹آ© tuple points to SAME metadata object
                       ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
                       ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ“ط·آ¢ط¢آ¼
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¥أ¢â‚¬â„¢ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ¯
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک copy.deepcopy(metadata)               ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œط£آ¢أ¢â€ڑآ¬أ¢â‚¬ع†ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ create_new_vtk_widget
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک   ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ SEPARATE dict with SEPARATE list  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک   ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ passed to ImageViewer2D.__init__  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¢ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ©
                                 ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
                                 ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ“ط·آ¢ط¢آ¼
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¥أ¢â‚¬â„¢ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ¯
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک ImageViewer2D.metadata                ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک   .instances = [0..21]  (frozen)      ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œط£آ¢أ¢â€ڑآ¬أ¢â‚¬ع†ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ NEVER UPDATED until v2.2.8.7
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک                                       ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک Used by:                              ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ¢ط¢آ¢ apply_default_window_level(idx)    ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ¢ط¢آ¢ set_window_level (is_rgb check)    ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ¢ط¢آ¢ update_corners_actors (rows/cols)  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک  ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ¢ط¢آ¢ load_bottom_left_actors (rows/cols) ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
         ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¹ط¢آ©
```

### Fixes

**Fix 1 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ `_sync_viewer_metadata_instances()` (NEW METHOD):**

New method in `ViewerController` that patches `ImageViewer2D.metadata['instances']`
on all live viewers showing a given series.  Copies the reference from the freshly-updated
`lst_thumbnails_data` source.  Also syncs `series.image_count`.

Called from **5 grow paths** (every path that calls `_refresh_stored_metadata_instances`):

| Call site | When it fires |
|-----------|---------------|
| `_grow_progressive_fast` | Every 150ms progressive grow tick |
| `on_series_download_fully_complete` | Layer 2b: final grow before exiting progressive mode |
| `change_series_on_viewer` (in-place grow) | Same-series re-drop with disk growth |
| `_completion_verify_series` | Layer 3: 500ms deferred verification (up to 3 retries) |
| `_completion_sweep_tick` | Layer 4: 3s periodic safety-net sweep |

**Fix 2 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Defensive bounds-checking in `ImageViewer2D` (viewer_2d.py):**

Four methods in `ImageViewer2D` directly indexed `self.metadata['instances'][slice_index]`
without bounds checking.  If `slice_index >= len(instances)` (stale metadata), they threw
`IndexError` that was silently caught by outer exception handlers.

| Method | Before (crash) | After (fallback) |
|--------|----------------|-------------------|
| `apply_default_window_level(idx)` | `instances[idx]` ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ IndexError | Bounds-check; fall back to `GetScalarRange()` auto-calc |
| `set_window_level(ww, wc)` | `instances[GetSlice()]['is_rgb']` ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ IndexError | Bounds-check; default `is_rgb=False` |
| `update_corners_actors()` | `instances[current_slice]['rows']` ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ IndexError | Bounds-check; fall back to VTK `GetDimensions()` |
| `load_bottom_left_actors()` | `instances[current_slice]['rows']` ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ IndexError | Bounds-check; fall back to VTK `GetDimensions()` |

The `GetScalarRange()` fallback computes W/L from the actual VTK volume data, which
produces correct windowing for any slice ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ slightly less optimal than per-slice DICOM W/L
but visually correct (no white/black images).

### Signal Flow With Fix

```
DM seriesProgressUpdated(sn, 50, 135)
  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ“ط·آ¢ط¢آ¼
on_series_images_progress  [100ms debounce]
  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ“ط·آ¢ط¢آ¼
_grow_progressive_fast(sn, 50, viewers)
  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¥أ¢â‚¬إ“ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ loader.grow()                          ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ VTK volume: 50 slices
  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¥أ¢â‚¬إ“ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ update_available_slice_count(50)
  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¥أ¢â‚¬إ“ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ slider.setMaximum(49)
  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¥أ¢â‚¬إ“ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ _refresh_stored_metadata_instances()   ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ lst_thumbnails_data: 50 instances ط·آ£ط¢آ¢ط·آ¥أ¢â‚¬إ“ط£آ¢أ¢â€ڑآ¬ط¢آ¦
  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط·آ¥أ¢â‚¬إ“ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ _sync_viewer_metadata_instances()      ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ ImageViewer2D.metadata: 50 instances ط·آ£ط¢آ¢ط·آ¥أ¢â‚¬إ“ط£آ¢أ¢â€ڑآ¬ط¢آ¦ (NEW)
  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬ط¹â€ک
  ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ“ط·آ¢ط¢آ¼
User scrolls to slice 35:
  apply_default_window_level(35)
    ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ instances[35] exists (50 entries)     ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ per-slice W/L applied correctly ط·آ£ط¢آ¢ط·آ¥أ¢â‚¬إ“ط£آ¢أ¢â€ڑآ¬ط¢آ¦
```

### Files Changed

| File | Change |
|------|--------|
| `patient_widget_viewer_controller.py` | New `_sync_viewer_metadata_instances()` method; called from 5 grow paths |
| `modules/viewer/advanced/viewer_2d.py` | Bounds-checking in `apply_default_window_level`, `set_window_level`, `update_corners_actors`, `load_bottom_left_actors` |
| `builder/.../viewer_2d.py` | Same bounds-checking fixes (builder copy) |
| `.github/copilot-instructions.md` | Two new critical rules documenting the sync requirement and bounds-check rule |

### Tests

All existing tests pass (no new tests needed ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ the fix is structural):
- 18 viewer pipeline tests ط·آ£ط¢آ¢ط·آ¥أ¢â‚¬إ“ط£آ¢أ¢â€ڑآ¬ط¢آ¦
- 24 smoke import tests ط·آ£ط¢آ¢ط·آ¥أ¢â‚¬إ“ط£آ¢أ¢â€ڑآ¬ط¢آ¦
- 27 DM scenarios (129 assertions) ط·آ£ط¢آ¢ط·آ¥أ¢â‚¬إ“ط£آ¢أ¢â€ڑآ¬ط¢آ¦
- 1 module connection test ط·آ£ط¢آ¢ط·آ¥أ¢â‚¬إ“ط£آ¢أ¢â€ڑآ¬ط¢آ¦

---

## Unreleased ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ FAST Viewer Count Accuracy + Stale Exhaustion Fix (v2.2.8.4)

### Summary

Fixes five production-observed bugs in the FAST Viewer progressive download path:
1. **Series count/scroll mismatch** ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ viewer stuck at 30 of 40 downloaded images (Series 201 symptom)
2. **Thumbnail image_count not updating** ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ thumbnail shows server-reported 20 instead of actual 40
3. **Safety-net infinite loop** ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ stale-grow exhaustion caused `_flush_progressive_grow` to loop forever
4. **In-place grow violated snapshot rule** ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ `backend.refresh_file_list()` was called before `loader.grow()`
5. **Per-grow-tick `iterdir` lag** ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ expensive disk scan ran every 150ms even when disk count unchanged

Three new tests (L24ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œL26) added; total viewer test count: **57 tests** across 3 suites.

### Root Causes

**Bug 1 (Series 201 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ 20/40/30 mismatch):**
When DM initially reported `total=30`, progressive mode exited at 30. When 10 more files arrived and DM sent a completion signal `(40, 40)`, the done-guard code hit a bare `return` for the `downloaded >= total` case ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ `_grow_progressive_fast` was never called. Viewer stuck at 30 (slider=29), but the `_total_expected_slices` counter showed 40 briefly during re-entry, causing the observed count mismatch.

**Bug 2 (stale-grow exhaustion ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ infinite loop):**
When `_stale_retry_count` reached 3 (max), the stale guard silently did nothing. The safety-net `_flush_progressive_grow` saw `pending_downloaded(40) > last_grow_count(30)` and restarted the timer ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ indefinitely. Each cycle: grow returns 30, stale guard does nothing, safety-net restarts. CPU was consumed but images never appeared.

**Bug 3 (thumbnail shows 20 not 40):**
`_refresh_stored_metadata_instances` updated `metadata["instances"]` but not `metadata["series"]["image_count"]`. The thumbnail widget reads `image_count` (server metadata), so it permanently showed the original server-reported count.

**Bug 4 (in-place grow snapshot violation):**
`change_series_on_viewer`'s same-series in-place grow called `backend.refresh_file_list()` BEFORE `loader.grow()`. This pre-refreshed the backend's file-path index, poisoning the old-path snapshot that `grow()` uses for interleaved DICOM instance-number remap.

**Bug 5 (per-grow-tick lag):**
`_refresh_stored_metadata_instances` ran `Path.iterdir()` (full disk listing) every 150ms grow tick even when no new files had landed. With 200+ DICOM files, this added 2ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œ10ms of main-thread I/O per tick.

### Fixes

**Fix 1 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Done-guard completion one-shot (`on_series_images_progress`):**
Added an `else:` branch to the `if sn in done:` + `if downloaded < total:` done-guard block. When `downloaded >= total`, scans for non-progressive viewers showing `sn` with fewer slices than `downloaded`, re-enters progressive mode on the viewer, and fires `_grow_progressive_fast` directly. This reliably recovers any viewer that was stuck at a lower count.

**Fix 2 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Stale exhaustion handling + retry max 5 (`_grow_progressive_fast`):**
Increased max stale retries from 3 ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ 5 (750ms window). Added an `else:` branch on exhaustion:
- Logs `STALE-EXHAUSTED` error
- Sets `info["pending_downloaded"] = new_count` (stops safety-net from looping)
- Pops series from `_progressive_series`
- Updates slider to `(new_count - 1)` so no empty positions are accessible
- Calls `exit_progressive_mode()` on each viewer
- Returns early ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ done-guard completion one-shot (Fix 1) recovers the remaining images when DM sends the final signal

**Fix 3 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ `_refresh_stored_metadata_instances` updates `series["image_count"]`:**
After `metadata["instances"] = new_instances`, also sets:
```python
_series_meta = metadata.get("series")
if isinstance(_series_meta, dict):
    _series_meta["image_count"] = len(new_instances)
```

**Fix 4 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ In-place grow calls `loader.grow()` first (not `backend.refresh_file_list()`):**
Restructured same-series in-place grow: `if _has_grow: new_count = loader.grow() elif _has_refresh: new_count = backend.refresh_file_list()`. Preserves snapshot integrity for interleaved DICOM.

**Fix 5 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ TTL pre-check in `_refresh_stored_metadata_instances`:**
Added `_count_series_files_on_disk(sn)` (1s TTL cache) guard before the expensive `Path.iterdir()` scan. If the TTL-cached disk count ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ°ط·آ¢ط¢آ¤ existing instance count, returns immediately without running `iterdir`. Reduces per-150ms-tick I/O to max once per second.

**Bonus ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Convert hot-path `print()` to `logger.debug()`:**
Converted all `print()` calls in `_refresh_stored_metadata_instances`, `change_series_on_viewer` same-series path, cache-invalidate, and switch-dedup to structured logger calls. Eliminates console noise and minor I/O overhead.

### New Tests

`tests/viewer/test_fast_viewer_live_sync.py` extended from 23 to **26 tests**:

| Test | Scenario |
|------|----------|
| **L24** `test_done_guard_completion_triggers_one_shot_grow` | Done-guard fires `_grow_progressive_fast` when `downloaded>=total` and non-progressive viewer shows fewer slices than downloaded (Series 201 fix) |
| **L25** `test_stale_grow_exhaustion_exits_progressive_mode` | Max retries (5) exhausted: `exit_progressive_mode` called, series popped, slider updated, timer NOT restarted, STALE-EXHAUSTED logged |
| **L26** `test_refresh_metadata_updates_series_image_count` | `_refresh_stored_metadata_instances` updates `series["image_count"]` from old server count (20) to actual disk count (40) |

### Files Changed

- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py`
  - `on_series_images_progress`: done-guard completion one-shot (Fix 1)
  - `_grow_progressive_fast`: stale exhaustion branch, max retries 3ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢5 (Fix 2)
  - `_refresh_stored_metadata_instances`: `series["image_count"]` update (Fix 3), TTL pre-check (Fix 5), printط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢logger
  - `change_series_on_viewer` in-place grow: `loader.grow()` first (Fix 4), printط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢logger
  - Cache-invalidate, switch-fail, switch-dedup: printط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢logger
- `tests/viewer/test_fast_viewer_live_sync.py` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ L24, L25, L26 added (57 total tests)

---

## Unreleased ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ FAST Viewer Stale-Grow Robustness Fix + Test Suite (v2.2.8.3)

### Summary

Fixes the "last N images stuck" stability bug in the FAST Viewer progressive display path.
When `loader.grow()` returned a stale count (OS file-system flush delay), the single-shot
`_progressive_grow_timer` would fire once, record the stale count as `last_grow_count`, and
never fire again ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ permanently leaving the viewer showing fewer images than were available on
disk. Three new tests (L21ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œL23) cover all stale-grow scenarios.

### Root Cause

`_progressive_grow_timer` uses `setSingleShot(True)` (150ms interval). When the DM writes
the final batch of files and emits the completion signal, the timer fires, calls
`loader.grow()`, and records whatever the OS reports at that instant. If the OS file-system
buffer has not yet committed some files, the count is stale (e.g. 20 instead of 25). Since
the timer is single-shot and no more DM signals arrive (download is complete), the viewer
is stuck at 20/25 images with no recovery mechanism.

The **one-shot path** (non-progressive viewer receiving a completion signal) has the same
problem: `_grow_progressive_fast` is called directly without any timer, so there is no retry
regardless of the stale count.

### Bugs Fixed

#### Bug: Single-shot timer exhaustion on stale `loader.grow()` count

**Files changed:** `patient_widget_viewer_controller.py`

**Fix 1 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Stale-grow guard in `_grow_progressive_fast`:**
After each grow, if `new_count < pending_count` and fewer than 3 retries have been attempted:
- Increment `info["_stale_retry_count"]`
- Set `info["pending_downloaded"] = pending_count` so `_flush_progressive_grow` knows to retry
- Call `enter_progressive_mode()` on any non-progressive viewer so `_find_progressive_viewers`
  can locate it on the retry tick (critical for the one-shot path)
- Restart the single-shot timer ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ it exhausted after the first fire and needs to restart

**Fix 2 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Safety-net restart in `_flush_progressive_grow`:**
After the per-series for-loop, if any tracked series still has
`pending_downloaded > last_grow_count`, restart the timer. This is an independent second
protection layer; both layers must remain.

#### Bug: One-shot path had no retry mechanism

When a non-progressive viewer received the completion signal, `_grow_progressive_fast` was
called directly without a timer. On stale grow: no timer was started, viewer stayed at stale
count. Fix 1 above also resolves this: `enter_progressive_mode()` is called on the viewer
(enabling the retry to find it via `_find_progressive_viewers`), and the timer is started.

### New Tests

`tests/viewer/test_fast_viewer_live_sync.py` extended from 20 to **23 tests**:

| Test | Scenario |
|------|----------|
| **L21** `test_stale_grow_restarts_timer_and_tracks_retry` | Stale grow: `_stale_retry_count` incremented, `pending_downloaded` preserved, timer started, `exit_progressive_mode` NOT called, STALE warning logged |
| **L22** `test_one_shot_stale_grow_sets_up_retry_via_progressive_mode` | One-shot path: non-progressive viewer calls `enter_progressive_mode` so retry can find it; timer started |
| **L23** `test_flush_progressive_grow_safety_net_restarts_timer` | `_flush_progressive_grow` safety-net: restarts timer when `pending > last_grow_count` after all grows |

### Documentation Updated

- `docs/pipelines/viewer-pipeline.md` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ added "Stale OS-Flush Guard (v2.2.8.3)" section
- `.github/copilot-instructions.md` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ added three new critical rules

---

## Unreleased ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Drag-Drop Progressive Display: Three-Bug Fix + Test Suite (2026-04-02)

### Summary

Fixes three independent bugs in the drag-and-drop ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ progressive display pipeline that caused the viewer to (A) never show the first downloaded batch, (B) never show the second batch even when the first appeared, and (C) keep the old image on screen instead of switching to a loading state. A new test suite (`test_dragdrop_progressive.py`, 16 scenarios) was added to lock in all three fixes.


### Summary

Fixes the "last N images stuck" stability bug in the FAST Viewer progressive display path.
When `loader.grow()` returned a stale count (OS file-system flush delay), the single-shot
`_progressive_grow_timer` would fire once, record the stale count as `last_grow_count`, and
never fire again ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ permanently leaving the viewer showing fewer images than were available on
disk. Three new tests (L21ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œL23) cover all stale-grow scenarios.

### Root Cause

`_progressive_grow_timer` uses `setSingleShot(True)` (150ms interval). When the DM writes
the final batch of files and emits the completion signal, the timer fires, calls
`loader.grow()`, and records whatever the OS reports at that instant. If the OS file-system
buffer has not yet committed some files, the count is stale (e.g. 20 instead of 25). Since
the timer is single-shot and no more DM signals arrive (download is complete), the viewer
is stuck at 20/25 images with no recovery mechanism.

The **one-shot path** (non-progressive viewer receiving a completion signal) has the same
problem: `_grow_progressive_fast` is called directly without any timer, so there is no retry
regardless of the stale count.

### Bugs Fixed

#### Bug: Single-shot timer exhaustion on stale `loader.grow()` count

**Files changed:** `patient_widget_viewer_controller.py`

**Fix 1 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Stale-grow guard in `_grow_progressive_fast`:**
After each grow, if `new_count < pending_count` and fewer than 3 retries have been attempted:
- Increment `info["_stale_retry_count"]`
- Set `info["pending_downloaded"] = pending_count` so `_flush_progressive_grow` knows to retry
- Call `enter_progressive_mode()` on any non-progressive viewer so `_find_progressive_viewers`
  can locate it on the retry tick (critical for the one-shot path)
- Restart the single-shot timer ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ it exhausted after the first fire and needs to restart

**Fix 2 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Safety-net restart in `_flush_progressive_grow`:**
After the per-series for-loop, if any tracked series still has
`pending_downloaded > last_grow_count`, restart the timer. This is an independent second
protection layer; both layers must remain.

#### Bug: One-shot path had no retry mechanism

When a non-progressive viewer received the completion signal, `_grow_progressive_fast` was
called directly without a timer. On stale grow: no timer was started, viewer stayed at stale
count. Fix 1 above also resolves this: `enter_progressive_mode()` is called on the viewer
(enabling the retry to find it via `_find_progressive_viewers`), and the timer is started.

### New Tests

`tests/viewer/test_fast_viewer_live_sync.py` extended from 20 to **23 tests**:

| Test | Scenario |
|------|----------|
| **L21** `test_stale_grow_restarts_timer_and_tracks_retry` | Stale grow: `_stale_retry_count` incremented, `pending_downloaded` preserved, timer started, `exit_progressive_mode` NOT called, STALE warning logged |
| **L22** `test_one_shot_stale_grow_sets_up_retry_via_progressive_mode` | One-shot path: non-progressive viewer calls `enter_progressive_mode` so retry can find it; timer started |
| **L23** `test_flush_progressive_grow_safety_net_restarts_timer` | `_flush_progressive_grow` safety-net: restarts timer when `pending > last_grow_count` after all grows |

### Documentation Updated

- `docs/pipelines/viewer-pipeline.md` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ added "Stale OS-Flush Guard (v2.2.8.3)" section
- `.github/copilot-instructions.md` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ added three new critical rules

---

## Unreleased ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Drag-Drop Progressive Display: Three-Bug Fix + Test Suite (2026-04-02)

### Summary

Fixes three independent bugs in the drag-and-drop ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ progressive display pipeline that caused the viewer to (A) never show the first downloaded batch, (B) never show the second batch even when the first appeared, and (C) keep the old image on screen instead of switching to a loading state. A new test suite (`test_dragdrop_progressive.py`, 16 scenarios) was added to lock in all three fixes.

### Bugs Found & Fixed

#### Bug A ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ First batch (10 images) never populated the dragged-to viewer

**Root cause:** When a user drag-dropped a series that was not yet on disk, `change_series_on_viewer` failed the async load (`ok=False`) and returned early ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ but it never marked the viewer as "waiting" for that series. When the DM later emitted `seriesProgressUpdated(sn=5, downloaded=10)`, `on_series_images_progress` had no scan for an awaiting viewer. It found no progressive viewer and no existing viewer showing the series, so it fell into `_start_progressive_display` with `target_vtk_widget=None`. The loaded data was placed in the first available empty slot, which was often the wrong layout position or not displayed at all.

**Fix (`patient_widget_viewer_controller.py`):**
- In the `_finish_on_ui(ok=False)` path, set `vtk_widget._awaiting_series_number = str(series_number)` and keep the spinner visible with a "Downloading series N..." message instead of hiding it.
- Added an awaiting-viewer scan at the start of `on_series_images_progress` (before the done-guard):
  ```python
  for node in self.lst_nodes_viewer:
      if getattr(node.vtk_widget, '_awaiting_series_number', None) == sn:
          _awaiting_viewer = node.vtk_widget
          _awaiting_node  = node
          break
  ```
- Extended `_start_progressive_display` signature with `target_vtk_widget=None, target_node=None`.
- Added `_apply_progressive_to_target_viewer(series_number, total, vtk_widget, node)` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ clears the marker, calls `_display_loaded_series` on that exact viewer, enters progressive mode, hides the spinner.
- `change_series_on_viewer` clears `vtk_widget._awaiting_series_number = None` at the start of every new switch (so old markers from prior drops don't linger).

#### Bug B ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Second batch (images 11ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œ20) never triggered a grow

**Root cause:** A race condition in the threaded fallback of `_start_progressive_display`. Before the fix, the background thread called `done.add(sn)` immediately after loading files ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ **before** `QTimer.singleShot(0, ...)` fired the activation callback. The next progress signal arrived, found `sn` in the done-set, scanned for a progressive viewer (found none because activation hadn't fired yet), and returned early from the done-guard. The grow timer was never started, permanently blocking all subsequent batches.

**Fix (`patient_widget_viewer_controller.py` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ threaded path of `_start_progressive_display`):**
- Moved `done.add(sn)` **inside** the `QTimer.singleShot(0, _display_activate_and_mark_done)` callback, after both `_display_series_after_load` and `_activate_progressive_mode_on_viewers` complete.
- The done-guard recovery path was strengthened: if `sn` is already in `done` but no progressive viewer is found, the guard scans for any non-progressive viewer showing that series and re-enters progressive mode, keeping the grow path alive.

#### Bug C ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Drag-drop showed old image instead of loading state

**Root cause:** `change_series_on_viewer` always sent `request_critical_series()` to escalate priority, but when the async load failed (`ok=False`) it called `_hide_spinner_for_widget` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ restoring the previous series image and providing no visual cue that a download was about to begin.

**Fix:** The `ok=False` branch now:
1. Sets `vtk_widget._awaiting_series_number = str(series_number)` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ visually marks the viewport.
2. Calls `vtk_widget.viewport_spinner.show_loading("Downloading series N...")` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ replaces the old image with a recognizable loading state.
3. Does **not** hide the spinner (the spinner persists until `_apply_progressive_to_target_viewer` completes).

### Related Coordinator Fix

`negotiate_priority_change` in `series_intent_coordinator.py` was updated to attempt `_start_download_worker(study_uid)` immediately when `worker_pool.can_add_worker()` is True, falling back to the 50ms deferred path only if the immediate start fails. This reduces priority-escalation latency from ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ°ط·آ¢ط¢آ¥50ms to ~0ms in most cases.

### Test Suite Added

**File:** `tests/viewer/test_dragdrop_progressive.py` (16 tests, 48 KPI assertions)

| # | Scenario | Covers |
|---|----------|--------|
| S1 | `_awaiting_series_number` set on `ok=False` | Bug C |
| S2 | Marker cleared on new drag-drop | Bug C |
| S3 | Repeated drag-drop overwrites marker | Bug C |
| S4 | Progress scan finds awaiting viewer | Bug A |
| S5 | Two layouts track independent series | Bug A |
| S6 | `_apply_progressive_to_target_viewer` happy path | Bug A |
| S7 | Cache miss path hides spinner | Bug A |
| S8 | Inflight guard blocks restart | Guards |
| S9 | Done guard blocks restart | Guards |
| S10 | KPI: scan over 10 nodes < 1ms avg | Perf |
| S11 | End-to-end: 10-series patient, drag sn=5 | A+B+C |
| S12 | Bug A regression: first batch populates awaiting viewer | Bug A |
| S13 | Bug B regression: second batch takes grow path, not restart | Bug B |
| S14 | Bug C regression: drag-drop replaces image AND escalates priority | Bug C |
| S15 | Stability: 10 batches ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ 1 start + 9 grows (3 reps) | A+B |
| S16 | Repeatability: full lifecycle ط·آ·ط¢آ£ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ 5, timing < 5ms/rep | A+B+C |

**Run commands:**
```
.venv\Scripts\python.exe -m pytest tests/viewer/test_dragdrop_progressive.py -v
.venv\Scripts\python.exe tests/viewer/test_dragdrop_progressive.py
```

### Files Changed

| File | Change |
|------|--------|
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` | `_finish_on_ui(ok=False)` keeps spinner; `change_series_on_viewer` clears awaiting; `on_series_images_progress` awaiting scan; `_start_progressive_display` gets `target_*` params; new `_apply_progressive_to_target_viewer`; done.add ordering fix |
| `modules/download_manager/coordinator/series_intent_coordinator.py` | `negotiate_priority_change` tries immediate worker start |
| `tests/download_manager/test_download_manager.py` | S27 updated (accepts immediate-start path) |
| `tests/viewer/test_dragdrop_progressive.py` | **New** ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ 16-scenario drag-drop + progressive display test suite |

---

## Unreleased ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Critical Series Intent & Preemption Hardening (2026-04-01)

### Summary

Hardens the FAST Viewer ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Download Manager interaction when users drag-and-drop a not-yet-downloaded series during active study download. The system now handles repeated user intent reliably and avoids silent no-op paths.

### Challenge

In real workflow, users repeatedly drag different series (or the same series multiple times) while another series is already downloading. The expected behavior is deterministic:

- requested series becomes **Critical** immediately,
- active lower-priority series are preempted,
- requested series is downloaded first,
- then study returns to **High** and routine order resumes.

### Problems Found

1. **Constructor-order regression**
	- `DownloadManagerWidget` instantiated coordinator before `_tasks` existed.
	- Result: DM tab creation crash (`AttributeError: ... has no attribute '_tasks'`).

2. **Repeated same-series drag/drop could be swallowed**
	- Same-series fast path treated repeated requests as no-op even when the series was still incomplete on disk.

3. **Critical retry accepted but not enforced immediately**
	- Retry path could skip effective preemption for same-study active worker scenarios.

4. **Preemption depended on potentially stale state**
	- Pause logic relied on `state.status` and could miss an actually running subprocess worker.
	- Outcome: scheduler continued normal order (`...6,7,8,9...`) instead of switching to the requested critical series.

5. **Slow cancel reaction under large in-flight request**
	- Cancel checks were too coarse in socket receive/retry flow, causing delayed slot release.

### Solution Implemented

- Fixed DM initialization order so `_tasks` is initialized before coordinator construction.
- Added same-series incomplete detection in viewer routing; repeated drag/drop now re-triggers download intent when files are still missing.
- Strengthened `_on_series_retry()` behavior to avoid false skip and force preemption path for active same-study, different-series requests.
- Hardened `_pause_all_active_downloads()` to use **active worker pool as source of truth** (not only state flags), then normalize state to `PAUSED`.
- Added faster cancellation checks in socket request loop/retry path to reduce cancellation latency.
- Added prioritized-start retry scheduling when pool is temporarily full.

### Engineering Outcome

- Better repeatability under high-frequency drag/drop interactions.
- Reduced drift between UI intent and actual download execution.
- Improved stability of Critical ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ High transition model in FAST workflow.

---

## v2.3.0 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Stable Release (2026-03-31)

### Summary

Publishes **v2.3.0** as the next stable AIPacs release and aligns the runtime, packaging, build metadata, backup snapshot, and GitHub publication around the same release number.

### Highlights

- Updated application version in `main.py` to `2.3.0`
- Updated package metadata in `pyproject.toml` to `2.3.0`
- Updated Nuitka Windows product version in `build_nuitka.py` to `2.3.0`
- Updated plugin package feed and package manifests under `builder/plugin package/packages/` to `2.3.0`
- Rebuilt release artifacts and installer outputs for `2.3.0`
- Published `main` and tagged the release as `v2.3.0`

### Notes

- `v2.2.7` remains the previous stable line in release history.
- `v2.3.0` is now the active published stable release.

---

## v2.2.7 Stable Snapshot Refresh (2026-03-31)

### Summary

Reaffirms **v2.2.7** as the stable published line for this workspace and refreshes the build, installer, backup, and documentation surfaces around that release number.

### Highlights

- Regenerated release-facing build metadata under `builder/output/` for the active `2.2.7` version
- Added automatic installer notes and SHA256 generation in `builder/build_release.py`
- Updated release documentation and helper scripts so the stable packaging flow matches the actual installer artifact names
- Prepared the workspace for a fresh local backup snapshot and GitHub publication on `main`

### Notes

- Entries `v2.2.7.1` through `v2.2.7.4` remain valuable stabilization notes inside the `2.2.7` development line.
- The published stable release number for this snapshot remains **`v2.2.7`**.

---

## v2.2.7.4 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Non-Blocking Retry & Freeze Elimination (2026-03-28)

### Summary

Eliminates all UI freeze paths in the download manager retry/refresh flow. All blocking I/O (file deletion, gRPC metadata fetch, worker stop) is now offloaded to background threads, keeping the Qt event loop responsive at all times.

### Problem

Pressing the series refresh button (ط·آ¸أ¢â‚¬آ¹ط·آ¹ط·â€؛ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â€ڑآ¬أ¢â‚¬ع†) or download manager retry button caused the entire application to freeze for 2ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œ90+ seconds, blocking all other modules (viewer, thumbnails, etc.). Three specific bottlenecks were identified:

- **F1 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ `worker_pool.stop_all()`**: Called `worker.wait(5000)` per active worker on the main thread (5ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œ15s freeze)
- **F2 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ `shutil.rmtree()`**: File deletion in retry methods on the main thread (2ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œ30s freeze)
- **F3 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ `_reconstruct_task_from_database()`**: Synchronous gRPC call with 30s timeout ط·آ·ط¢آ£ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ 3 retries (90s+ potential freeze)

### Fixes

**Non-blocking worker preemption (F1):**
- Added `cancel_all_non_blocking()` to `WorkerPool` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ sets cancel flags without waiting
- `_pause_all_active_downloads()` now uses `cancel_all_non_blocking()` instead of `stop_all()`
- Workers clean up asynchronously via their existing `finished` ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ `_remove_worker` signal chain

**Non-blocking `_on_series_retry()` (F2 + F3):**
- Fast path on main thread: state checks, series list reorder, priority promotion, state reset to PENDING
- Slow path in `threading.Thread("series-retry-io")`: file I/O + gRPC task reconstruction
- Marshals back to main thread via `QTimer.singleShot(0, callback)` for worker start + UI refresh

**Non-blocking `_on_per_patient_retry()` (F2 + F3):**
- Same pattern: fast state reset on main thread, background thread for file cleanup + gRPC, marshal back for worker start

### Architecture Principle

Each module in a DICOM Workstation must operate as an independent loop. Download manager operations must never block the Qt event loop, ensuring the viewer, thumbnails, and other modules remain responsive regardless of download state.

### Files Changed

| File | Change |
|------|--------|
| `modules/download_manager/workers/worker_pool.py` | Added `cancel_all_non_blocking()` method |
| `modules/download_manager/ui/main_widget.py` | `_on_series_retry`, `_on_per_patient_retry`, `_pause_all_active_downloads` made non-blocking |

### Documentation

- Created `docs/architecture/FREEZE_BOTTLENECK_ANALYSIS.md` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ comprehensive analysis of all freeze paths

---

## v2.2.7.3 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ R19b Verified Batch-Skip & Skip Count Fix (2026-03-27)

### Summary

Hardens R19b batch-skip to verify actual sequential file existence instead of trusting a simple file count. Fixes `skipped_count` double-counting that inflated progress and result values.

### Highlights

**R19b Verified Batch-Skip:**
- Previously, R19b computed `batch_start = (file_count // batch_size) * batch_size`, assuming the first N files filled leading batches sequentially
- If files were non-sequential (e.g., gaps in batch 1 with files from batch 2 present), R19b would skip batches containing missing instances
- Now R19b iterates leading batches and checks that every `Instance_{i:04d}.dcm` file exists before skipping. If any file is missing in a batch, the skip stops there
- Falls back to file-level skip (R19) for any batch that isnط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â‚¬â€چط¢آ¢t fully verified

**skipped_count Double-Counting Fix:**
- `skipped_count` was initialized from `_scan_existing_files()` (e.g., 22 files ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ skipped=22)
- During batch processing, per-instance `file_path.exists()` incremented `skipped_count` again for files already counted in the initial scan
- This caused `downloaded + skipped > expected`, inflating progress and `SeriesDownloadResult.skipped`
- Now uses an `existing_files_set` to track initial files; per-instance skip only increments for NEW files (created between scan and batch processing)

### Files Changed

| File | Change |
|------|--------|
| `modules/download_manager/network/socket_client.py` | R19b verified batch-skip + skipped_count fix |
| `modules/download_manager/ui/main_widget.py` | Per-patient retry now deletes "complete" series files before re-download |
| `modules/download_manager/download/series_downloader.py` | R20 diagnostic logging (existing/expected/is_complete) |

### Bug Fixed: Series 202 Missing Last 10 Images on Redownload

**Symptom:** When retrying a partially-downloaded series (e.g., 22/32 images), the last 10 images were not downloaded correctly. Logs showed ZERO download activity ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ R20 skipped the series entirely.

**Root Cause (1 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ primary):** `_on_per_patient_retry()` reset download state (PENDING, cleared completed_series etc.) but **never deleted files from disk**. R20 `check_series_complete()` counts `.dcm` files and, finding `existing >= expected`, skipped the series. The download worker never called `download_series()` at all.

**Root Cause (2):** R19b batch-skip used raw file count to skip leading batches. If existing files didn't fill exact sequential batch ranges, some batches with missing files were incorrectly skipped.

**Root Cause (3):** `skipped_count` was double-counted ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ initial scan + per-instance skip for pre-existing files ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ causing inflated progress reports.

**Fix:** `_on_per_patient_retry()` now iterates all series in the study before starting the download worker. For each series: if `existing_count < expected_count`, files are kept for incremental resume; if `existing_count >= expected_count` (or unknown), `shutil.rmtree()` deletes the directory to force a clean re-download. R19b also verifies sequential file existence per batch, and `skipped_count` uses a set to prevent double-counting.

---

## v2.2.7.2 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Resume Batch-Skip & Retry Button Fix (2026-03-27)

### Summary

Optimizes partial series resume to skip already-downloaded batches instead of re-transferring them, and fixes the retry button to preserve existing files for incremental resume.

### Highlights

**R19b ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Batch-Skip on Resume:**
- `download_series()` in `socket_client.py` now advances `batch_start` past leading complete batches when existing files are found on disk
- With 10 existing files and batch_size=10, batch 0 is skipped entirely ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ previously wasted ~87 seconds re-transferring data that was discarded on arrival
- Individual files within the first re-downloaded batch are still checked via R19 file-level skip

**Retry Button Incremental Resume:**
- `_on_series_retry()` in `main_widget.py` no longer calls `shutil.rmtree()` on incomplete series
- Keeps existing `.dcm` files on disk so the downloader resumes from where it left off
- Only deletes files when the series is already fully complete (to handle corruption/force re-download)

### Files Changed

| File | Change |
|------|--------|
| `modules/download_manager/network/socket_client.py` | R19b: skip leading complete batches on resume |
| `modules/download_manager/ui/main_widget.py` | Retry button: keep partial files for incremental resume |

### Bug Fixed: Series 201 Resume Wasting ~87 Seconds

**Symptom:** When resuming an incomplete series (10/32 images), the downloader started from batch 0 and re-downloaded all 10 existing images from the server (~87 seconds) only to skip every file on the `file_path.exists()` check.

**Root Cause:** `batch_start` was always initialized to 0 regardless of how many files already existed on disk.

**Fix:** R19b calculates `batch_start = (existing_count // batch_size) * batch_size`, skipping leading complete batches entirely.

---

## v2.2.7.1 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Download Resilience & Incomplete Resume (2026-03-26)

### Summary

This release adds robust retry/reconnection logic to the download manager, fixes incomplete download resume (previously blocked by validation rules), and resolves a progressive viewer CPU spike triggered by rapid download progress signals.

### Highlights

**Retry & Reconnection (3 layers):**
- Added 10 configurable retry constants to `constants.py`
- `connect_with_retry()` now uses exponential backoff with jitter, capped at 30s
- `send_request()` refactored into retry wrapper (3 attempts, backoff + reconnect); Login is fail-fast (no retry)
- Per-series retry loop in `series_downloader.py`: after main download loop, retries all failed series up to 3 rounds with backoff (3sط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢6sط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢12s) and socket reconnect between rounds

**Incomplete Download Resume (R17 validation fix):**
- R17a (StateStore check): Was unconditionally blocking ANY existing download ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ Now allows resume for non-terminal states (PENDING, DOWNLOADING, PAUSED, FAILED); only COMPLETED/CANCELLED are truly blocked
- R17b (DB check): Was blindly trusting DB "Completed" status ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ Now verifies actual `.dcm` file counts on disk per series directory; allows re-download if files are incomplete
- `start_priority_download_immediately()`: Added `should_resume` branch that falls through to STEP 3+ instead of returning False; resets progress counters for a fresh attempt

**Progressive Viewer & COL NameError:**
- `on_series_images_progress`: Added 250ms per-series throttle + `_progressive_display_inflight` dedup guard to prevent CPU spike
- `_start_progressive_display`: Added `finally` block to always clear inflight guard
- Fixed `COL` NameError in `home_ui.py` import that caused cascading failures in `_on_study_download_failed`

### Files Changed

| File | Change |
|------|--------|
| `modules/download_manager/core/constants.py` | 10 new retry/reconnection constants |
| `modules/download_manager/network/socket_client.py` | `connect_with_retry` backoff, `send_request` retry wrapper, batch reconnect |
| `modules/download_manager/download/series_downloader.py` | Per-series retry loop (3 rounds, exponential backoff), `connect_with_retry` |
| `modules/download_manager/rules/validation_rules.py` | R17a: resume for non-terminal states; R17b: filesystem `.dcm` count verification |
| `modules/download_manager/ui/main_widget.py` | `should_resume` path, state reset on resume |
| `PacsClient/pacs/workstation_ui/home_ui/home_ui.py` | `COL` import fix |
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` | 250ms throttle, inflight dedup guard, finally cleanup |

### Bug Fixed: Patient 35281 Series 201 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ 35 images, only 10 downloaded

**Symptom:** When reopening a patient whose download was incomplete, the system logged `"Cannot add download: Download already exists (Status: Pendding)"` and blocked all resume attempts. The viewer loaded only 10 of 35 images.

**Root Cause:** R17a validation rule unconditionally returned `is_valid=False` for any existing download in StateStore, regardless of whether the download had actually finished. This meant PENDING/FAILED downloads could never be retried through the normal patient-open flow.

**Fix:** R17a now distinguishes terminal vs non-terminal states. Non-terminal states return `should_resume=True`, which tells `start_priority_download_immediately()` to re-enter the download pipeline at STEP 3 (metadata fetch) with reset progress counters.

---

## v2.2.7 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Stable Release / Install and Build Alignment (2026-03-21)

### Summary

This release publishes the current stable workspace as **v2.2.7** and aligns the runtime version, package metadata, install flow, build flow, and release documentation around the same release number.

### Highlights
- Updated application version in `main.py`
- Updated package version in `pyproject.toml`
- Updated Nuitka product version in `build_nuitka.py`
- Updated plugin package feed and package manifests under `builder/plugin package/packages/`
- Updated `setup_env.ps1` to prefer `requirements-core.txt`, support `-IncludeDev`, and retain a legacy fallback to `requirements.txt`
- Updated builder dependency installation in `builder/scripts/_common.ps1`
- Refreshed install/build/release documentation in `README.md`, `docs/README.md`, `docs/development/setup-and-tooling.md`, `docs/pipelines/PYDICOM_2D_BACKEND.md`, `builder/docs/BUILD_CHECKLIST.md`, and `builder/docs/WINDOWS_RELEASE_FLOW.md`

### Release Intent
- Publish the current `main` branch state as stable version **`2.2.7`**
- Keep runtime, build, and plugin package metadata synchronized
- Make setup and release instructions match the repository's current split dependency model

---

## v2.2.6.3 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ GitHub Push / Package Metadata Alignment (2026-03-17)

### Summary

This release packages the current working changes for GitHub publication under **v2.2.6.3** and aligns the visible application/build/package metadata to the same version.

### Version Alignment
- Updated application version in `main.py`
- Updated package version in `pyproject.toml`
- Updated Nuitka product version in `build_nuitka.py`
- Updated plugin package manifest versions under `builder/plugin package/packages/**`
- Updated consolidated release notes to reflect `v2.2.6.3`

### Release Intent
- Publish current `main` branch state to GitHub as **`v2.2.6.3`**
- Keep package feed and module manifests synchronized with the tagged application version

---

## v2.2.6 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Stable Release (2026-03-15)

### Critical Bug Fix: Wheel Scroll Freeze

**Symptom:** After using stack drag (left mouse), switching to wheel scroll caused the image to freeze ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ scrollbar moved but image stayed fixed. Neither scroll method worked after that.

**Root Cause:** The `wheelEvent` performance optimization (v2.2.3.4.0) called `reslice.SetInterpolationModeToNearestNeighbor()` + `reslice.Modified()` to degrade quality during fast scroll. However, the `vtkImageReslice` carries a non-identity direction-matrix transform (Y-flip from `convert_itk2vtk`). Dirtying the reslice caused VTK's `UpdateDisplayExtent()` to compute a wrong output extent, collapsing the slice range (e.g. `(0,24)` ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ `(14,14)`, `data_z` ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ 1). All subsequent `SetSlice()` calls were clamped to that single slice.

**Fix:** Disabled NN interpolation degradation for ALL backends (`_skip_nn_degrade = True`). Made `_restore_reslice_quality()` a no-op. The performance gain from NN was negligible (<1ms) compared to the catastrophic freeze it caused.

**Files Changed:**
- `PacsClient/pacs/patient_tab/ui/patient_ui/widget_viewer.py` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ `wheelEvent`, `_restore_reslice_quality`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ study path exists() guard

### Other Fixes
- **Study path corruption:** Added `exists()` check before overwriting `import_folder_path` with stale legacy `source\` path from metadata
- **Post-scroll sync render:** Added `_post_scroll_sync_render()` one-shot callback to force VTK + annotation sync after scroll settles

### New Documentation
- `docs/pipelines/VIEWER_BACKENDS_REFERENCE.md` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Complete Advanced vs Fast backend pipeline reference
- Updated `docs/pipelines/viewer-pipeline.md` with reslice corruption warning

### GPU / Software OpenGL
- Verified: GPU detection (`resolve_graphics_profile`) and Software OpenGL fallback (`build_windows_graphics_environment`) remain fully functional
- Both modes produce correct viewer rendering and scroll behavior

### Rule Added
> **CRITICAL:** Never call `reslice.SetInterpolationMode*()` or `reslice.Modified()` during interactive scroll. See `VIEWER_BACKENDS_REFERENCE.md ط·آ·ط¢آ¢ط·آ¢ط¢آ§4.6`.

---

## v2.2.3.4.0 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Performance Sprint (2026-02-27)

**Commit:** `5215a89`

## Summary
This consolidated release note covers the performance optimization sprint from v2.2.3.0 through v2.2.3.4.0. The primary focus was eliminating scroll lag during Mode B (active download) and Mode A (post-download) on software OpenGL renderers.

## Highlights (v2.2.3.4.0)

### Scroll Performance (Mode B ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ during download)
- **GIL contention eliminated:** DL_WARMUP moved to separate process with own GIL (v2.2.3.2.3). `queue_p95_ms` dropped from 200ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œ510ms ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ **0.00ms**.
- **Per-frame overhead reduced:** Camera zoom save/restore, interactor style update, and Lock Sync skipped during wheel scroll (v2.2.3.4.0). Saves 4ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œ6ms per frame.
- **Subprocess priority:** IDLE_PRIORITY_CLASS for warmup subprocess (v2.2.3.4.0). Eliminates memory-bus contention during scroll.
- **Reference line optimization:** Round-robin single-target repaint (v2.2.3.3.7). Caps ref-line blocking to ~20ms per tick.
- **GC suppression hardened:** 2000ms re-enable timer + elevated thresholds kept (v2.2.3.3.2). Eliminates 660ms periodic lag.

### Scroll Performance (Mode A ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ no download)
- **Adaptive throttle:** Replaced debounce with adaptive frame-gap throttle (v2.2.3.2.8). ~2x frame rate improvement.
- **VTK render pipeline:** FXAA off, MSAA disabled, redundant color_mapper.Update() skipped (v2.2.3.2.5).
- **Stale-event drain:** Skip render for events queued >500ms, render final position once (v2.2.3.2.1).

### Series Load Performance
- **Parallel pydicom:** Instance create from 4.3s ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ 0.8s for 330-file CT (v2.2.3.1.9).
- **Cast-once filter:** ITK filter 423ms ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ 151ms for MR 20sl (v2.2.3.1.6).
- **Download DB insert:** batch_insert from 2217ms ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ 326ms (v2.2.3.2.0).

## Version History (v2.2.3.x)

| Version | Commit | Key Change |
|---|---|---|
| v2.2.3.4.0 | `5215a89` | Scroll fast-path: skip camera/style/locksync during wheel scroll; subprocess IDLE priority |
| v2.2.3.3.9 | `af11baf` | Reduce Mode B subprocess contention: ITK 2ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢1 thread, defer poll, tighten notify |
| v2.2.3.3.8 | `125c00a` | Fix size-mismatch detection for incomplete downloads |
| v2.2.3.3.7 | `f6c4dda` | Round-robin reference line repaint |
| v2.2.3.3.6 | `f90b608` | Eliminate ref-line paint blocking from scroll loop |
| v2.2.3.3.5 | `6b18b94` | Real-time reference line sync (dual-timer) |
| v2.2.3.3.4 | `5b3b77c` | Reference lines sync with stack drag + lock sync |
| v2.2.3.3.3 | `1f2cd36` | Debounce reference line updates during scroll |
| v2.2.3.3.2 | `edfff7f` | Eliminate 660ms periodic GC lag (PC B) |
| v2.2.3.3.1 | `0382270` | Cache os.getenv; event-loop bypass for timer congestion |
| v2.2.3.3.0 | `66914e0` | Strengthen GC suppression for heavy volumes |
| v2.2.3.2.9 | `495a61a` | GC suppression during scroll + throttle booster |
| v2.2.3.2.8 | `e34c6b1` | Adaptive throttle replaces debounce (~2x fps) |
| v2.2.3.2.7 | `8fb6629` | Fix infinite stale-drain loop |
| v2.2.3.2.5/6 | `34b559b` | Render pipeline + signal coalescing |
| v2.2.3.2.2 | `ff0d4b1` | DL_WARMUP speed improvements |
| v2.2.3.2.1 | `9724dea` | Stale-event fast-drain guard |
| v2.2.3.2.0 | `3cd1a09` | Parallel pydicom + adaptive ITK + BELOW_NORMAL priority |

## Known Issues
- First-series load still runs in-process (~2.4s via asyncio.to_thread)
- `update_corners_actors()` updates 6 VTK text actors per scroll (only 2 change)
- `viewer_db_read` 38ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬ط¥â€œ88ms on series load (could be cached)

## Documentation
- Performance status: `docs/PERFORMANCE_STATUS.md`
- Detailed metrics: `docs/METRICS_TRACKING_v2.2.3.x.md`
- Decision log: `docs/PERFORMANCE_DECISION_LOG_2026-02-27.md`
- Cross-PC workflow: `docs/CROSS_PC_IMPROVEMENT_WORKFLOW.md`

