# AIPacs Release Notes (Consolidated)

**Current Stable Version:** v2.2.7
**Release Date:** 2026-03-31
**Branch:** main  

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

## v2.2.7.4 — Non-Blocking Retry & Freeze Elimination (2026-03-28)

### Summary

Eliminates all UI freeze paths in the download manager retry/refresh flow. All blocking I/O (file deletion, gRPC metadata fetch, worker stop) is now offloaded to background threads, keeping the Qt event loop responsive at all times.

### Problem

Pressing the series refresh button (🔄) or download manager retry button caused the entire application to freeze for 2–90+ seconds, blocking all other modules (viewer, thumbnails, etc.). Three specific bottlenecks were identified:

- **F1 — `worker_pool.stop_all()`**: Called `worker.wait(5000)` per active worker on the main thread (5–15s freeze)
- **F2 — `shutil.rmtree()`**: File deletion in retry methods on the main thread (2–30s freeze)
- **F3 — `_reconstruct_task_from_database()`**: Synchronous gRPC call with 30s timeout × 3 retries (90s+ potential freeze)

### Fixes

**Non-blocking worker preemption (F1):**
- Added `cancel_all_non_blocking()` to `WorkerPool` — sets cancel flags without waiting
- `_pause_all_active_downloads()` now uses `cancel_all_non_blocking()` instead of `stop_all()`
- Workers clean up asynchronously via their existing `finished` → `_remove_worker` signal chain

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

- Created `docs/architecture/FREEZE_BOTTLENECK_ANALYSIS.md` — comprehensive analysis of all freeze paths

---

## v2.2.7.3 — R19b Verified Batch-Skip & Skip Count Fix (2026-03-27)

### Summary

Hardens R19b batch-skip to verify actual sequential file existence instead of trusting a simple file count. Fixes `skipped_count` double-counting that inflated progress and result values.

### Highlights

**R19b Verified Batch-Skip:**
- Previously, R19b computed `batch_start = (file_count // batch_size) * batch_size`, assuming the first N files filled leading batches sequentially
- If files were non-sequential (e.g., gaps in batch 1 with files from batch 2 present), R19b would skip batches containing missing instances
- Now R19b iterates leading batches and checks that every `Instance_{i:04d}.dcm` file exists before skipping. If any file is missing in a batch, the skip stops there
- Falls back to file-level skip (R19) for any batch that isn’t fully verified

**skipped_count Double-Counting Fix:**
- `skipped_count` was initialized from `_scan_existing_files()` (e.g., 22 files → skipped=22)
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

**Symptom:** When retrying a partially-downloaded series (e.g., 22/32 images), the last 10 images were not downloaded correctly. Logs showed ZERO download activity — R20 skipped the series entirely.

**Root Cause (1 — primary):** `_on_per_patient_retry()` reset download state (PENDING, cleared completed_series etc.) but **never deleted files from disk**. R20 `check_series_complete()` counts `.dcm` files and, finding `existing >= expected`, skipped the series. The download worker never called `download_series()` at all.

**Root Cause (2):** R19b batch-skip used raw file count to skip leading batches. If existing files didn't fill exact sequential batch ranges, some batches with missing files were incorrectly skipped.

**Root Cause (3):** `skipped_count` was double-counted — initial scan + per-instance skip for pre-existing files — causing inflated progress reports.

**Fix:** `_on_per_patient_retry()` now iterates all series in the study before starting the download worker. For each series: if `existing_count < expected_count`, files are kept for incremental resume; if `existing_count >= expected_count` (or unknown), `shutil.rmtree()` deletes the directory to force a clean re-download. R19b also verifies sequential file existence per batch, and `skipped_count` uses a set to prevent double-counting.

---

## v2.2.7.2 — Resume Batch-Skip & Retry Button Fix (2026-03-27)

### Summary

Optimizes partial series resume to skip already-downloaded batches instead of re-transferring them, and fixes the retry button to preserve existing files for incremental resume.

### Highlights

**R19b — Batch-Skip on Resume:**
- `download_series()` in `socket_client.py` now advances `batch_start` past leading complete batches when existing files are found on disk
- With 10 existing files and batch_size=10, batch 0 is skipped entirely — previously wasted ~87 seconds re-transferring data that was discarded on arrival
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

## v2.2.7.1 — Download Resilience & Incomplete Resume (2026-03-26)

### Summary

This release adds robust retry/reconnection logic to the download manager, fixes incomplete download resume (previously blocked by validation rules), and resolves a progressive viewer CPU spike triggered by rapid download progress signals.

### Highlights

**Retry & Reconnection (3 layers):**
- Added 10 configurable retry constants to `constants.py`
- `connect_with_retry()` now uses exponential backoff with jitter, capped at 30s
- `send_request()` refactored into retry wrapper (3 attempts, backoff + reconnect); Login is fail-fast (no retry)
- Per-series retry loop in `series_downloader.py`: after main download loop, retries all failed series up to 3 rounds with backoff (3s→6s→12s) and socket reconnect between rounds

**Incomplete Download Resume (R17 validation fix):**
- R17a (StateStore check): Was unconditionally blocking ANY existing download → Now allows resume for non-terminal states (PENDING, DOWNLOADING, PAUSED, FAILED); only COMPLETED/CANCELLED are truly blocked
- R17b (DB check): Was blindly trusting DB "Completed" status → Now verifies actual `.dcm` file counts on disk per series directory; allows re-download if files are incomplete
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

### Bug Fixed: Patient 35281 Series 201 — 35 images, only 10 downloaded

**Symptom:** When reopening a patient whose download was incomplete, the system logged `"Cannot add download: Download already exists (Status: Pendding)"` and blocked all resume attempts. The viewer loaded only 10 of 35 images.

**Root Cause:** R17a validation rule unconditionally returned `is_valid=False` for any existing download in StateStore, regardless of whether the download had actually finished. This meant PENDING/FAILED downloads could never be retried through the normal patient-open flow.

**Fix:** R17a now distinguishes terminal vs non-terminal states. Non-terminal states return `should_resume=True`, which tells `start_priority_download_immediately()` to re-enter the download pipeline at STEP 3 (metadata fetch) with reset progress counters.

---

## v2.2.7 — Stable Release / Install and Build Alignment (2026-03-21)

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

## v2.2.6.3 — GitHub Push / Package Metadata Alignment (2026-03-17)

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

## v2.2.6 — Stable Release (2026-03-15)

### Critical Bug Fix: Wheel Scroll Freeze

**Symptom:** After using stack drag (left mouse), switching to wheel scroll caused the image to freeze — scrollbar moved but image stayed fixed. Neither scroll method worked after that.

**Root Cause:** The `wheelEvent` performance optimization (v2.2.3.4.0) called `reslice.SetInterpolationModeToNearestNeighbor()` + `reslice.Modified()` to degrade quality during fast scroll. However, the `vtkImageReslice` carries a non-identity direction-matrix transform (Y-flip from `convert_itk2vtk`). Dirtying the reslice caused VTK's `UpdateDisplayExtent()` to compute a wrong output extent, collapsing the slice range (e.g. `(0,24)` → `(14,14)`, `data_z` → 1). All subsequent `SetSlice()` calls were clamped to that single slice.

**Fix:** Disabled NN interpolation degradation for ALL backends (`_skip_nn_degrade = True`). Made `_restore_reslice_quality()` a no-op. The performance gain from NN was negligible (<1ms) compared to the catastrophic freeze it caused.

**Files Changed:**
- `PacsClient/pacs/patient_tab/ui/patient_ui/widget_viewer.py` — `wheelEvent`, `_restore_reslice_quality`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` — study path exists() guard

### Other Fixes
- **Study path corruption:** Added `exists()` check before overwriting `import_folder_path` with stale legacy `source\` path from metadata
- **Post-scroll sync render:** Added `_post_scroll_sync_render()` one-shot callback to force VTK + annotation sync after scroll settles

### New Documentation
- `docs/pipelines/VIEWER_BACKENDS_REFERENCE.md` — Complete Advanced vs Fast backend pipeline reference
- Updated `docs/pipelines/viewer-pipeline.md` with reslice corruption warning

### GPU / Software OpenGL
- Verified: GPU detection (`resolve_graphics_profile`) and Software OpenGL fallback (`build_windows_graphics_environment`) remain fully functional
- Both modes produce correct viewer rendering and scroll behavior

### Rule Added
> **CRITICAL:** Never call `reslice.SetInterpolationMode*()` or `reslice.Modified()` during interactive scroll. See `VIEWER_BACKENDS_REFERENCE.md §4.6`.

---

## v2.2.3.4.0 — Performance Sprint (2026-02-27)

**Commit:** `5215a89`

## Summary
This consolidated release note covers the performance optimization sprint from v2.2.3.0 through v2.2.3.4.0. The primary focus was eliminating scroll lag during Mode B (active download) and Mode A (post-download) on software OpenGL renderers.

## Highlights (v2.2.3.4.0)

### Scroll Performance (Mode B — during download)
- **GIL contention eliminated:** DL_WARMUP moved to separate process with own GIL (v2.2.3.2.3). `queue_p95_ms` dropped from 200–510ms → **0.00ms**.
- **Per-frame overhead reduced:** Camera zoom save/restore, interactor style update, and Lock Sync skipped during wheel scroll (v2.2.3.4.0). Saves 4–6ms per frame.
- **Subprocess priority:** IDLE_PRIORITY_CLASS for warmup subprocess (v2.2.3.4.0). Eliminates memory-bus contention during scroll.
- **Reference line optimization:** Round-robin single-target repaint (v2.2.3.3.7). Caps ref-line blocking to ~20ms per tick.
- **GC suppression hardened:** 2000ms re-enable timer + elevated thresholds kept (v2.2.3.3.2). Eliminates 660ms periodic lag.

### Scroll Performance (Mode A — no download)
- **Adaptive throttle:** Replaced debounce with adaptive frame-gap throttle (v2.2.3.2.8). ~2x frame rate improvement.
- **VTK render pipeline:** FXAA off, MSAA disabled, redundant color_mapper.Update() skipped (v2.2.3.2.5).
- **Stale-event drain:** Skip render for events queued >500ms, render final position once (v2.2.3.2.1).

### Series Load Performance
- **Parallel pydicom:** Instance create from 4.3s → 0.8s for 330-file CT (v2.2.3.1.9).
- **Cast-once filter:** ITK filter 423ms → 151ms for MR 20sl (v2.2.3.1.6).
- **Download DB insert:** batch_insert from 2217ms → 326ms (v2.2.3.2.0).

## Version History (v2.2.3.x)

| Version | Commit | Key Change |
|---|---|---|
| v2.2.3.4.0 | `5215a89` | Scroll fast-path: skip camera/style/locksync during wheel scroll; subprocess IDLE priority |
| v2.2.3.3.9 | `af11baf` | Reduce Mode B subprocess contention: ITK 2→1 thread, defer poll, tighten notify |
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
- `viewer_db_read` 38–88ms on series load (could be cached)

## Documentation
- Performance status: `docs/PERFORMANCE_STATUS.md`
- Detailed metrics: `docs/METRICS_TRACKING_v2.2.3.x.md`
- Decision log: `docs/PERFORMANCE_DECISION_LOG_2026-02-27.md`
- Cross-PC workflow: `docs/CROSS_PC_IMPROVEMENT_WORKFLOW.md`
