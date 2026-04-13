# AIPacs Copilot Instructions

**Current Stable Version:** v2.2.8.1 (2026-04-02)

## Architecture map (start here)
- App entry is `main.py` → `AppHandler` (login) → `MainWindowWidget` → `ControlPanelInterface` → `HomePanelWidget` for patient list and downloads.
- UI is PySide6 with qasync (`main.py` sets `QEventLoop`) and VTK; keep async UI work on the Qt event loop and offload heavy work to executor threads.
- Patient workflow lives in `PacsClient/pacs/workstation_ui/home_ui/home_ui.py` (thin controller) with services in `home_db_service.py`, `home_tab_service.py`, `home_download_service.py`, `home_search_service.py`.  See `docs/architecture/home-ui-services.md`.
- Download stack is Zeta-based: `PacsClient/zeta_download_manager/**` with adapter helpers in `PacsClient/components/zeta_adapter.py`. Legacy download helpers in `home_ui.py` are marked deprecated.
- Socket comms go through `modules/network/socket_service.py` (singleton facade) and config via `modules/network/socket_config.py` + `config/socket_config.json`.  See `docs/architecture/network-architecture.md`.
- Download-path socket client lives in `modules/download_manager/network/socket_client.py` (SocketDicomClient) with health monitoring in `health_monitor.py`.
- gRPC client is `modules/network/grpc_client.py` — used only for thumbnails; has auto-reconnect via `_ensure_stub()`.

## Critical rules (learned the hard way)
- **Do NOT re-sort metadata['instances'] by IPP.** VTK slices are in instance_number order (files are `Instance_NNNN.dcm` loaded via `natsort`). Metadata from DB is already in the correct order. Re-sorting by IPP broke reference lines in v1.09.5-v1.09.7.
- **The stored DirectionMatrix in field data has row 1 negated** (Y-flip compensation from `convert_itk2vtk`). Do not use it directly for DICOM normal comparisons without un-negating row 1 first.
- **Scroll fast-path (`_in_wheel_scroll` flag):** During wheelEvent-driven scroll, `set_slice()` skips camera zoom save/restore, interactor style update, and throttles Lock Sync to 100ms.  Do NOT add expensive per-frame operations inside `set_slice()` without guarding them with `if not _wheel:`. See v2.2.3.4.0.
- **DL_WARMUP subprocess runs at IDLE priority** (v2.2.3.4.0). It has its own GIL. Do not bump priority above IDLE — it causes memory-bus contention that spikes the viewer's SetSlice from 8→45ms.
- **GC is suppressed during scroll bursts** (`gc.disable()` in wheelEvent, re-enabled 2000ms after last render). Do not call `gc.collect()` during scroll. See v2.2.3.3.2.
- **Reference line repaint during scroll uses round-robin** (v2.2.3.3.7): trailing-edge timer paints ONE target viewer per tick. Do not change to paint-all-targets per tick — it blocks the event loop N×20ms.
- **Local backup of this stable version:** `backups/v2.2.7_2026-03-21/`
- **Download validation R17a allows resume for non-terminal states** (v2.2.7.1). PENDING/DOWNLOADING/PAUSED/FAILED downloads return `should_resume=True` instead of blocking. Only COMPLETED and CANCELLED are truly blocked. Do NOT revert R17a to unconditional blocking — it caused the "Download already exists" bug where incomplete downloads could never resume.
- **R17b verifies actual .dcm files on disk** (v2.2.7.1). Even if DB says "Completed", R17b counts `.dcm` files per series directory against `image_count`. Do NOT trust DB status alone for completeness checks.
- **Download retry has 3 layers** (v2.2.7.1): send_request wrapper (3 retries), connect_with_retry (exponential backoff+jitter), per-series retry loop (3 rounds, 3s→6s→12s). All constants in `modules/download_manager/core/constants.py`. Do NOT add retry to Login requests (fail-fast by design).
- **`load_single_series_by_number` pydicom_qt fast path** (v2.3.1). When `allow_lazy_backend=True` and `viewer_backend == BACKEND_PYDICOM_QT`, the function exits early **before** calling `resolve_viewer_backend`. It builds metadata from DB (or DICOM headers) and yields a minimal stub `vtkImageData` (correct dimensions, no pixel data). The entire SimpleITK filter chain (`apply_filters` 6–9s) and `convert_itk2vtk` are skipped. Do NOT remove this early exit — without it, every series click in FAST mode wasted 7–10 seconds on ITK work that was immediately discarded because `_bind_backend_from_metadata` always overrides the VTK payload with the Qt bridge. The stub VTK object satisfies `vtk_data is not None` cache checks in `_get_series_by_number_fast` so second-visit cache hits still work. Advanced mode (`vtk_simpleitk`) is completely unaffected — it never passes `BACKEND_PYDICOM_QT` to the function.
- **`load_single_series_by_number` does NOT call `resolve_viewer_backend(metadata=None)` for pydicom_qt** (v2.3.1). The old call with `metadata=None` forced `instances=[]` inside `resolve_viewer_backend`, which triggered the `BACKEND_PYDICOM_QT → BACKEND_VTK` fallback guard. This is why the ITK pipeline ran even in FAST mode. The fix bypasses this entirely by checking `viewer_backend == BACKEND_PYDICOM_QT` directly before that call.
- **`load_single_series_by_number` ITK pipeline guard** (v2.3.1). `BACKEND_PYDICOM_QT` is now imported in `image_io.py` from `modules.viewer.viewer_backend_config`. Do NOT remove this import — it is the guard comparison for the fast path.
- **PYDICOM_QT stubs have no VTK scalar data by design** (v2.3.1). `load_single_series_by_number` creates a `vtkImageData` stub with `SetDimensions()` only — pixel data comes from DICOM files at render time via `Lightweight2DPipeline`. Never abort a series switch or any other code path because `GetPointData().GetScalars()` returns `None` without first checking `metadata['series']['viewer_backend'] == BACKEND_PYDICOM_QT`. The `switch_series` scalar guard in `_vw_series.py` already does this check (`_is_qt_stub` flag). Any NEW scalar-presence guard added anywhere in the viewer switch path MUST apply the same exception or it will reproduce the "scrollbar moves but image frozen" regression.
- **pydicom_2d viewer MUST be wired directly to the raw lazy vtkImageData — NOT through image_reslice** (v2.3.1 / 2026-04-10). `SetInputData(image_reslice.GetOutput())` wraps the reslice output in a VTK trivial producer. `Render()` asks the trivial producer for data but NEVER calls `image_reslice.Update()`. The lazy decoder fills `lazy_vtk_image_data` (numpy backing store), but `image_reslice.GetOutput()` is a separate object still holding zeros — every scroll shows a frozen image. Fix: use `SetInputData(raw_lazy_vtk)` directly in `ImageViewer2D.__init__` and `reset_image_viewer` when `_active_backend == 'pydicom_2d'`. Also skip `_preprocess_vtk_image_data` for pydicom_2d — it runs `vtkImageResample` which creates a disconnected copy that `mark_vtk_modified()` cannot reach. Do NOT add `image_reslice.Modified()` or `image_reslice.Update()` to the pydicom_2d scroll path (`_vw_scroll.py`) or lazy-slice-ready callback (`_vw_backend.py`) — these are architecturally wrong for the trivial producer model and silently re-introduce the frozen image regression. See `docs/pipelines/IMAGE_PIPELINE_REFERENCE.md` Rule 11 and `docs/pipelines/PYDICOM_2D_BACKEND.md` "VTK Viewer Wiring" section.
- **Progressive viewer has 250ms per-series throttle** (v2.2.7.1). `on_series_images_progress` debounces to prevent CPU spike from rapid signals. Do not remove the throttle or the `_progressive_display_inflight` guard.
- **R19b batch-skip on resume** (v2.2.7.2; hardened v2.2.7.3). `download_series()` advances `batch_start` past **verified** leading complete batches. Each batch is verified by checking that all sequential `Instance_NNNN.dcm` files exist — do NOT revert to count-based skip (it skips batches with gaps). Do NOT reset `batch_start` to 0 unconditionally — it wastes minutes re-transferring data.
- **Retry button keeps partial files** (v2.2.7.2). `_on_series_retry()` only deletes files when series is fully complete. Do NOT add unconditional `shutil.rmtree()` for incomplete series — it forces full re-download instead of incremental resume.
- **Per-patient retry deletes "complete" series files** (v2.2.7.3). `_on_per_patient_retry()` iterates all series and deletes series directories where `existing_count >= expected_count` — R20 would otherwise skip them. Incomplete series are kept for incremental resume. Do NOT remove the file deletion from `_on_per_patient_retry()` — without it, R20 sees the series as complete and the download never triggers.
- **skipped_count uses existing_files_set** (v2.2.7.3). Per-instance file-skip only increments `skipped_count` for files NOT in the initial scan set. Do NOT remove the `existing_files_set` check — it prevents double-counting that inflates progress and result values.
- **Retry methods are non-blocking** (v2.2.7.4). `_on_series_retry()` and `_on_per_patient_retry()` offload all file I/O (`shutil.rmtree`, `os.listdir`) and gRPC calls (`_reconstruct_task_from_database`) to `threading.Thread` background threads. Results are marshaled back via `QTimer.singleShot(0, callback)`. Do NOT add blocking I/O to the fast path of these methods — it freezes the entire application.
- **Worker preemption is non-blocking** (v2.2.7.4). `_pause_all_active_downloads()` uses `cancel_all_non_blocking()` (sets cancel flags only) instead of `stop_all()` (which waits 5s/worker). Do NOT revert to `stop_all()` in any main-thread code path — only use it for app shutdown.
- **Module independence rule** (v2.2.7.4). Each DICOM workstation module (viewer, download manager, thumbnails) must operate as an independent loop. No module may block the Qt event loop >16ms. All cross-module communication uses Qt signals (AutoConnection). Blocking I/O must be in background threads with `QTimer.singleShot(0, callback)` to marshal results back.
- **Home UI service layer** (v2.2.8.0). `HomePanelWidget` is a thin controller — DB ops go in `home_db_service.py`, tab ops in `home_tab_service.py`, DM wiring in `home_download_service.py`, search in `home_search_service.py`. Do NOT add DB/network/FS I/O directly in `home_ui.py` — delegate to a service. Use `is_widget_alive()` from `home_widget_utils.py` instead of inline `sip.isdeleted()`. Use `activate_or_create_module_tab()` from `home_module_tabs.py` instead of duplicating tab-find-or-create logic.
- **Lazy imports in home_ui** (v2.2.8.0). `PatientWidget` and `AiMainWindow` are loaded via `_get_patient_widget_class()` / `_get_ai_mainwindow_class()` on first use. Do NOT import them at module level — it adds ~200ms to startup.
- **Database commit rule** (v2.2.8.0). `get_db_connection()` context manager does NOT auto-commit — pool calls `rollback()` on return. Every DML (INSERT/UPDATE/DELETE) inside a `with get_db_connection()` block MUST call `conn.commit()` before the block exits, or the write is silently lost.
- **Database context manager rule** (v2.2.8.0). All DB operations MUST use `with get_db_connection() as conn:` — not bare `get_connection_database()`. The old function leaks connections on exception. All of `database/manager.py` was converted in v2.2.8.0.
- **FK indexes** (v2.2.8.0). `init_database()` creates indexes on `studies.patient_fk`, `series.study_fk`, `instances.series_fk`, and `instances(series_fk, group_id)`. Do NOT remove them — they prevent full-table scans.
- **No PRAGMA read_uncommitted** (v2.2.8.0). It leaks via the connection pool. Was removed from `get_incomplete_downloads()`.
- **DB log throttle** (v2.2.8.0). `log_stage_timing(min_ms=5.0)` suppresses sub-5ms pool operations. Use `min_ms=5.0` for new pool-level timing; `min_ms=0` for business-logic timing.
- **Socket sendall() rule** (v2.2.8.0). All socket writes MUST use `sendall()` — never `send()`. `send()` can do partial writes that corrupt the 4-byte length-prefix framing. Fixed in `PatientListSocketClient`.
- **Socket recv exact rule** (v2.2.8.0). All exact-length reads MUST use `_recv_exact(size)` — never bare `recv(4)`. Partial reads on slow networks corrupt framing. Fixed in `PatientListSocketClient`.
- **Response size limit** (v2.2.8.0). Socket responses are capped at 50 MB before allocation. Do NOT remove this check — it prevents unbounded memory growth from corrupted length headers or server bugs.
- **No hardcoded server IPs** (v2.2.8.0). Server host/port comes from `SocketConfig` → `config/socket_config.json` or `AIPACS_SOCKET_HOST`/`AIPACS_SOCKET_PORT` env vars. `constants.py` defaults to `localhost`. Do NOT put production IPs in source code.
- **gRPC auto-reconnect** (v2.2.8.0). `DicomGrpcClient._ensure_stub()` reconnects if stub is `None`. All public methods call `_ensure_stub()` first. Do NOT remove this — it prevents permanent failure after transient disconnection.
- **Login no-retry** (v2.2.8.0). `send_request()` wrapper MUST NOT retry Login requests. Login uses fail-fast design — retrying with wrong credentials wastes server resources and may trigger rate limits.
- **Lazy connection pool** (v2.2.8.0). `SocketConnectionPool` creates connections on demand and validates `is_connected()` before returning. Do NOT revert to eager creation — it wastes sockets when only 1 is typically needed.
- **Network logging discipline** (v2.2.8.0). Use `logger.debug()` for routine send/recv byte counts. Use `logger.info()` only for connection state changes (connect/disconnect/reconnect). Use `logger.error()` for failures. Do NOT use `print()` in network code.
- **Progressive display done-guard must fire AFTER activation** (v2.2.8.1). In `_start_progressive_display`, the threaded fallback MUST run `_display_series_after_load` → `_activate_progressive_mode_on_viewers` → `done.add(sn)` sequentially on the main thread via a single `QTimer.singleShot(0)` callback. If `done.add` runs from the background thread before activation, ALL subsequent progress signals are blocked and the grow path is permanently dead. This caused a 5-minute stall in v2.2.8.0.
- **Progressive display done-guard has recovery path** (v2.2.8.1). If `sn in _progressive_display_done` but no progressive viewer is found, the guard scans for any non-progressive viewer showing that series and re-enters progressive mode. Do NOT return unconditionally from the done-guard — the recovery path handles edge cases where progressive mode was lost (e.g., after series switch).
- **DM notify on drag-drop is non-blocking** (v2.2.8.1). `_notify_dm_viewed_series()` in ViewerController is called via `QTimer.singleShot(0)` — NOT synchronously. It was blocking 183ms before. The method also scans existing tabs before calling `_get_or_create_download_manager_tab` to avoid 100+ms widget creation overhead on first call.
- **DM notify has 500ms per-series cooldown** (v2.2.8.1). `_DM_VIEWED_NOTIFY_COOLDOWN_MS = 500`. Uses `_dm_notify_last_ts` dict keyed by series_number. Do NOT remove the cooldown — rapid drag-drop on the same series overwhelms the coordinator.
- **Stale guard uses show-then-refresh** (v2.2.8.1). In `change_series_on_viewer`, when the cache has fewer slices than disk (`cached_instances < disk_files`), the stale cache is displayed IMMEDIATELY and a background reload fires after 150ms via `QTimer.singleShot(150)`. Do NOT block the viewer switch for a full reload — it adds 200+ms of perceived latency.
- **`_ensure_import_folder_path()` resolves study path during download** (v2.2.8.1). Called at the top of `_start_progressive_display`. Resolves `SOURCE_PATH / study_uid` and stamps it on `parent_widget.import_folder_path`. Without this, `_load_single_series_on_demand` returns False with "No valid study path found" because `import_folder_path` is None during active download.
- **Disk file count uses `os.scandir` + 1s TTL cache** (v2.2.8.1). `_count_series_files_on_disk()` uses `os.scandir` (single syscall per entry) instead of `Path.iterdir()` + per-file stat. Results cached for 1 second in `_disk_count_cache` dict to avoid re-scanning during rapid progress signals. Do NOT remove the TTL cache — it prevents I/O on every stale-guard check.
- **Show loading spinner on empty drag-drop** (v2.2.8.1). When a drag-drop/thumbnail-click targets a series not in cache, `viewport_spinner.show_loading("Downloading series N...")` is called on the target viewer BEFORE `_schedule_async_load_and_switch`. The previous image must NOT remain visible — users interpret it as a crash.
- **Progressive display throttle is 100ms** (v2.2.8.1, was 250ms in v2.2.7.1). `on_series_images_progress` per-series debounce reduced to 100ms to match DM's progress timer. Do NOT increase back to 250ms — it causes visible stutter.
- **Progressive grow timer is 150ms** (v2.2.8.1, was 500ms). `_progressive_grow_timer.setInterval(150)`. Do NOT increase — it controls how fast new batch images appear in the viewer during download.
- **Coordinator queue_recheck is 50ms** (v2.2.8.1, was 150ms). `queue_recheck_ms=50` in `negotiate_priority_change`. Reduced to make priority preemption feel instant.
- **Coordinator retry interval is 200ms** (v2.2.8.1, was 500ms). `schedule_priority_start_retry(interval_ms=200)`. Polling interval when worker can't start immediately after preemption.
- **Coordinator retry budget is 90 attempts** (v2.2.9.1, was 60). `schedule_priority_start_retry(max_retries=90)` = 18s total window. Increased to cover slow-network edge cases where subprocess cancel detection is delayed by in-flight socket I/O. Do NOT reduce below 60 — it causes "Priority start retry exhausted" warnings in production.
- **WorkerPool on_worker_removed callback** (v2.2.9.1). `WorkerPool.__init__` accepts `on_worker_removed` callback. `_remove_worker` fires the callback OUTSIDE the lock after freeing the pool slot. `DownloadManagerWidget` wires this to `_on_pool_slot_freed` → `QTimer.singleShot(0, _start_next_pending)`. This provides an event-driven path to start the next download immediately when a pool slot frees — eliminates dependence on the 200ms retry poller. Do NOT remove this callback — it reduces perceived preemption latency from up to 200ms (poll tick) to ~0ms (next event loop tick).
- **WorkerPool add_worker logging is debug-level** (v2.2.9.1). Reduced from `logger.info` to `logger.debug` to eliminate 15+ log lines per worker add in the hot path. Only the final "Worker added" confirmation remains at info level.
- **negotiate_priority_change also calls schedule_priority_start_retry** (v2.2.8.1). After deferring `_start_next_pending`, the coordinator schedules a retry poller as backup — prevents PENDING studies from getting stuck when the pool is still occupied by a dying worker.
- **Same-study series interrupt** (v2.2.8.1). `request_critical_series` cancels the study's OWN worker if `current_series_number` differs from the requested series. This converts "wait for entire series to finish" into "wait for current batch to finish" (~1 socket round-trip). The state is set to PENDING (not PAUSED) so `_start_next_pending` picks it up. Do NOT remove the `current_series != series_number` guard — without it, requesting the SAME series that's downloading would needlessly restart the worker.
- **Worker completion timer is 0ms** (v2.2.8.1, was 100ms). `_on_worker_completed` and `_on_worker_error` use `QTimer.singleShot(0, _start_next_pending)`. The `finished` signal (which frees the pool) is always processed before the deferred callback. Do NOT increase — it adds dead time between worker termination and new worker start.
- **Observer priority→refresh is 0ms** (v2.2.8.1, was 100ms). `QTimer.singleShot(0, self.ui.refresh_table_order)` in UIObserver for priority field changes. Do NOT add delay — it makes the DM UI feel sluggish after Critical promotion.
- **Stale OS-flush guard in `_grow_progressive_fast`** (v2.2.8.3). If `loader.grow()` returns fewer slices than `pending_count` (OS has not yet flushed all downloaded files to disk), the method must: (1) increment `info["_stale_retry_count"]` (max 5 — was 3 in v2.2.8.3), (2) set `info["pending_downloaded"] = pending_count`, (3) call `enter_progressive_mode()` on any non-progressive viewer so `_find_progressive_viewers` can locate it on the retry tick, (4) restart the single-shot timer. Do NOT skip the timer restart — without it, the viewer is stuck on the last N images forever. Root cause of the "last 5 images stuck" bug.
- **Stale exhaustion exits progressive mode and stops safety-net** (v2.2.8.4). When `_stale_retry_count >= 5` (_STALE_RETRY_MAX), the exhaustion branch: (1) logs STALE-EXHAUSTED error, (2) sets `info["pending_downloaded"] = new_count` to stop `_flush_progressive_grow` from looping, (3) pops series from `_progressive_series`, (4) updates slider to `(new_count - 1)`, (5) calls `exit_progressive_mode()` on each viewer, (6) returns early. The done-guard completion one-shot recovers the remaining images when DM sends the final signal. Do NOT remove the exhaustion branch — without it, the safety-net loops infinitely calling `_grow_progressive_fast` forever.
- **Done-guard completion one-shot** (v2.2.8.4). In `on_series_images_progress`, the `if sn in done:` block must handle `downloaded >= total` explicitly. When the completion signal arrives and a non-progressive viewer shows fewer slices than `downloaded`, the guard fires `_grow_progressive_fast` directly (after re-entering progressive mode). Do NOT leave a bare `return` at the end of the done-guard block — it permanently blocks the recovery path for Series 201-type count mismatches.
- **`_progressive_display_done` is a lifecycle guard, NOT a permanent cache** (v2.2.9.2 — H4 fix). Every code path that calls `self._progressive_series.pop(sn, None)` as a lifecycle-close MUST also call `done.discard(sn)` immediately after. This applies to all three completion layers: Layer 2b (`_on_series_download_fully_complete_impl`), Layer 3 (`_completion_verify_series`), and Layer 4 (`_completion_sweep_tick_impl`). `discard()` is idempotent — safe if another layer already removed the key. **H4 root cause (fixed v2.2.9.2):** absence of `done.discard(sn)` caused stale keys to block `_start_progressive_display` on every re-open of the same series number within a session, producing a frozen viewer with no error in the log. s08 is the detection canary (H4 CONFIRMED always expected — tests detector logic); s11 is the post-fix health check (H4 NO_EVIDENCE always expected — tests real bound production methods).
- **Global `sys.excepthook` captures crash tracebacks** (v2.2.9.3 — H5a). `main.py` installs `_aipacs_excepthook` after `configure_diagnostic_logging()`. It logs the FULL Python traceback to `aipacs.crash` logger at CRITICAL level BEFORE Qt intercepts the exception with the generic "Qt has caught an exception" message. Without this, the throwing file/line is permanently lost. Chains to the original hook. Do NOT remove this — it is the primary diagnostic tool for all Qt boundary crashes.
- **QTimer callback slots MUST use wrapper+impl guard pattern** (v2.2.9.3 — H5b/H5c). Direct `QTimer.timeout` slots (`_reenable_gc`, `_flush_pending_wheel_slice`) are Qt event handler entry points. If any exception propagates through them, Qt catches it with the fatal "Qt has caught an exception" message and the Python traceback is lost (even with `sys.excepthook`, the exception may not reach it in all Qt versions). The wrapper+impl pattern (`_reenable_gc` → `_reenable_gc_impl`, `_flush_pending_wheel_slice` → `_flush_pending_wheel_slice_impl`) ensures exceptions are caught, logged with `exc_info=True`, and suppressed. Apply this pattern to ALL new QTimer.timeout slots and Qt signal slots that access VTK objects or cross-module state.
- **`_refresh_stored_metadata_instances` updates `series["image_count"]`** (v2.2.8.4). After `metadata["instances"] = new_instances`, also sets `metadata["series"]["image_count"] = len(new_instances)`. Do NOT update `instances` without updating `image_count` — the thumbnail widget reads `image_count` (server metadata), and without this fix it permanently shows the original server-reported count (e.g. 20 instead of 40).
- **`_refresh_stored_metadata_instances` TTL pre-check** (v2.2.8.4). Uses `_count_series_files_on_disk(sn)` (1s TTL cache) as a fast pre-check before the expensive `Path.iterdir()` scan. If TTL-cached disk count ≤ existing instance count, returns immediately without scanning. Do NOT remove this guard — it prevents 2–10ms of main-thread I/O on every 150ms grow tick with large series.
- **`_sync_viewer_metadata_instances` after every grow** (v2.2.8.7). `ImageViewer2D.metadata` is a deep copy from creation time; `_refresh_stored_metadata_instances` only updates `lst_thumbnails_data`. After every `_refresh_stored_metadata_instances` call, also call `_sync_viewer_metadata_instances(series_number)` to patch live `ImageViewer2D.metadata['instances']`. Without this, `apply_default_window_level(n)` throws `IndexError` for slices `n >= initial_count`, silently killing per-slice W/L and corner text. Fixed in: `_grow_progressive_fast`, `on_series_download_fully_complete`, `change_series_on_viewer` in-place grow, `_completion_verify_series`, `_completion_sweep_tick`.
- **`apply_default_window_level` bounds-checks `metadata['instances']`** (v2.2.8.7). Falls back to `GetScalarRange()` auto-calc when `slice_index >= len(instances)` instead of crashing. Same bounds-checking applied to `set_window_level` (is_rgb check), `update_corners_actors`, and `load_bottom_left_actors`. Do NOT revert to bare indexing — it causes white/missing images during progressive download.
- **`_fill_stub_from_dicom_header` populates per-slice geometry on new stubs** (v2.2.8.7). During `_refresh_stored_metadata_instances`, each new stub is enriched with `pydicom.dcmread(stop_before_pixels=True)` to extract `image_position_patient` (IPP), `image_orientation_patient` (IOP), `pixel_spacing`, `window_width/center`, `rows`, `columns`, `slice_thickness`, `spacing_between_slices`, `rescale_slope/intercept`. Without this, stubs have `IPP = None` → `manage_reference_line()` silently skips new slices → reference lines disappear for progressively-added images. Reading is ~1-3ms per file (header only). Do NOT remove this call — it is the ONLY source of per-slice geometry during progressive grow.
- **In-place grow calls `loader.grow()` first** (v2.2.8.4). `change_series_on_viewer`'s same-series in-place grow must call `loader.grow()` FIRST and only fall back to `backend.refresh_file_list()` if no `grow()` exists. Do NOT add a pre-call to `backend.refresh_file_list()` before `loader.grow()` — it poisons the old-path snapshot used by `grow()` for interleaved DICOM instance-number remap.
- **Four-layer completion protocol** (v2.2.8.5). Progressive display uses defense-in-depth to guarantee all downloaded images reach the viewer: Layer 1 = DM throttled progress → incremental grows (existing); Layer 2a = `on_series_completed` emits `series_images_progress(sn, total, total)` completion pulse before `series_downloaded` — guarantees viewer sees `downloaded == total`; Layer 2b = `on_series_download_fully_complete` does `loader.grow()` + slider update BEFORE exiting progressive mode — direct final grow at the definitive completion signal; Layer 3 = `_completion_verify_series` fires 500ms after completion with up to 3 retries at 500ms intervals — catches OS-flush-delayed files; Layer 4 = `_completion_sweep_timer` (3s interval) registers completed series and periodically verifies disk count vs viewer count — catches any missed signal. Do NOT remove any layer — they are complementary, not redundant.
- **`on_series_download_fully_complete` must grow before exit** (v2.2.8.5). Was: pop series + exit progressive. Now: final `loader.grow()` + slider update on ALL viewers showing the series, THEN `exit_progressive_mode()`, THEN pop series, THEN schedule Layer 3 verify + Layer 4 sweep registration. Do NOT remove the final grow — it was the root cause of "Series 202 shows 120/135" where `seriesDownloadCompleted` fired BEFORE the DM throttle timer emitted the final progress signal.
- **`on_series_completed` emits completion pulse** (v2.2.8.5). `home_download_service.on_series_completed` now calls `_emit_final_progress(w, sn)` → `w.series_images_progress.emit(sn, total, total)` BEFORE `w.series_downloaded.emit(sn)`. The total is resolved from `dm._tasks[study_uid].series_list[sn].image_count`. This guarantees the viewer's `on_series_images_progress` receives a `downloaded >= total` signal for batch-gate bypass. Both `_flush` (batched completions) and `on_series_completed` (first completion) emit the pulse. Do NOT remove this — without it, the viewer never learns a series is complete when the DM's 100ms throttle timer hasn't flushed the last progress batch.
- **Completion sweep timer is 3 seconds** (v2.2.8.5). `_completion_sweep_timer.setInterval(3000)`. Registered by `_completion_sweep_register(sn, total)` from `on_series_download_fully_complete`. Self-stops when `_completion_sweep_series_set` is empty. Do NOT reduce below 2 seconds — it adds periodic disk I/O via `_count_series_files_on_disk`.
- **Completion verify has 3 retries at 500ms** (v2.2.8.5). `_COMPLETION_VERIFY_MAX_RETRIES = 3`, `_COMPLETION_VERIFY_INTERVAL_MS = 500`. Total window = 1.5 seconds for OS flush. On exhaustion, logs warning but does not loop. Layer 4 sweep provides additional coverage beyond this window.
- **`load_series_on_demand` calls `on_series_download_fully_complete` exactly once** (v2.2.8.5). Was called twice (copy-paste bug). The duplicate was removed. Do NOT add it back.
- **FAST backend switch v2.3.3 — Stage 1+2** (v2.3.3). FAST mode default changed from `BACKEND_PYDICOM` ("pydicom_2d") to `BACKEND_PYDICOM_QT` ("pydicom_qt"). Config file `config/viewer_backend_settings.json` now says `"pydicom_qt"`. The resolver alias in `viewer_backend_config.py` unconditionally remaps `BACKEND_PYDICOM` → `BACKEND_PYDICOM_QT` (safety net for stale configs). Advanced mode is completely unaffected — `force_vtk=True` always resolves to `BACKEND_VTK`. All VTK render-chain constructs (PyDicomLazyVolume, ImageViewer2D, mark_vtk_modified, image_reslice.Update, Render) are unreachable in FAST mode. Do NOT revert the config without also removing the alias block — config-only rollback has no effect.
- **`AIPACS_FORCE_PYDICOM_2D=1` emergency escape hatch** (v2.3.3 Stage 2). Set this env var to revert FAST mode to the old VTK lazy-hybrid backend without code changes. The escape hatch fires BEFORE the alias remap, converting `BACKEND_PYDICOM_QT` or `BACKEND_PYDICOM` → `BACKEND_PYDICOM`, and the alias `not _force_legacy` guard prevents the remap from overriding it. Requires restart. Do NOT use in production — it re-enables the H13 crash-prone VTK path. Remove once Stage 3 (dead code cleanup) is complete.
- **`_bind_backend_from_metadata` has BACKEND_PYDICOM leak guard** (v2.3.3 Stage 2). If `BACKEND_PYDICOM` reaches the binding stage without the escape hatch, the guard logs an ERROR and remaps to `BACKEND_PYDICOM_QT`. This should never fire in normal operation. If it fires, investigate why the resolver alias failed.
- **Post-bind sanity check** (v2.3.3 Stage 2). After `_bind_backend_from_metadata` exits via the VTK fallback path, a check verifies `_active_backend != BACKEND_PYDICOM` (unless escape hatch is active). Logs ERROR if violated.
- **Startup banner `[BACKEND_SWITCH]`** (v2.3.3 Stage 2). `main.py` logs `[BACKEND_SWITCH] Startup: FAST backend=... Advanced=vtk_simpleitk` immediately after `configure_diagnostic_logging()`. This is the first backend-related log line and confirms which backend is configured for the session.

## Key flows to preserve
- Opening a study: `HomePanelWidget._on_patient_double_clicked_async` opens tab immediately, then starts Zeta download with priority and wires progress signals.
- Download UI: always use `DownloadManagerWidget` from `PacsClient/zeta_download_manager/ui/main_widget.py` (created via `_get_or_create_download_manager_tab`).
- Shutdown behavior: `main.py` clears only the Download Manager UI state file but keeps DB download history; do not delete DB progress in shutdown.
- Drag-drop priority: `change_series_on_viewer` → `_notify_dm_viewed_series` (deferred) → `dm.set_viewed_series` → `intent_coordinator.request_critical_series` → `state_store.update(priority=CRITICAL)` → UIObserver → `refresh_table_order`. Paused peers get `status=PAUSED, is_auto_paused=True`.
- Progressive display lifecycle: DM `seriesProgressUpdated` → `home_download_service.on_series_progress` → `widget.series_images_progress.emit(sn, downloaded, total)` → `on_series_images_progress` → first batch: `_start_progressive_display` → subsequent: `_grow_progressive_fast`. Completion: DM `seriesDownloadCompleted` → `on_series_completed` → `_emit_final_progress(sn, total, total)` (Layer 2a), then `series_downloaded` → `load_series_on_demand` → `on_series_download_fully_complete` (Layer 2b: final grow + exit progressive), then 500ms `_completion_verify_series` (Layer 3), plus 3s `_completion_sweep_timer` (Layer 4). Guard states: `_progressive_display_inflight` (set), `_progressive_display_done` (set). FAST mode only (returns early for Advanced/VTK).

## Project-specific conventions
- Resource paths must go through `PacsClient/utils/config.py` (`BASE_PATH`, `ICON_PATH`, `IMAGES_LOGIN_PATH`) to work for both dev and PyInstaller.
- For sockets, update settings via `update_socket_server_settings()` before querying server-side lists.
- Prefer signals/slots for UI updates; download progress is emitted from background threads via Qt signals.
- **`set_server_series_info` is called TWICE per patient open** (v2.3.0+thumb-stable). Call 1 (main async thread, `_hp_patient_open.py` line 268) is the primary call; call 2 (from `_background_setup_thread`) is a merge-only call. The method now MERGES on subsequent calls (never overwrites `image_count` or `series_description` already populated by gRPC). Do NOT revert to unconditional `_server_series_info = {}` replacement — it discards gRPC-fetched image counts and triggers redundant thumbnail reloads.
- **`ThumbnailManager` must not use `print()`** (v2.3.0+thumb-stable). All logging goes through `_tm_logger` (debug/info/exception). `print()` in hot paths (`update_series_progress`, `start_series_download`, `apply_border_states_new`) causes synchronous stdout I/O that blocks the calling thread on Windows. Use `_tm_logger.debug()` for routine events, `_tm_logger.exception()` for errors in except blocks.
- **`QMetaObject.invokeMethod` for cross-thread UI dispatch in thumbnails** (v2.2.9.2). `set_server_series_info` may be called from a background `threading.Thread`. Use `QMetaObject.invokeMethod(self, "_load_server_thumbnails", Qt.QueuedConnection)` — never `QTimer.singleShot` — since QTimer.singleShot from a non-Qt thread has no event loop and is silently dropped. The `_load_server_thumbnails` and render slots must be decorated with `@Slot()`.
- **`_thumbnail_load_inflight` guard prevents concurrent thumbnail loads** (v2.2.9.2). Set to `True` in `_load_server_thumbnails` before the worker starts; reset to `False` in the worker's `finally` block. Do NOT schedule another load while this is `True` — it results in duplicate work and may reset pending/ready series border states.

## Build/run/test workflows
- Run app: `python main.py` (Windows uses software OpenGL flags set in `main.py`).
- Build executable: `build.bat` → `build.py` (PyInstaller spec `AIPacs.spec`).
- Tests are ad-hoc scripts like `test_*.py`; there is no single test runner configured.
- DM tests: `.venv\Scripts\python.exe tests/download_manager/run_dm_test.py` (27 scenarios, 129 assertions — covers state store, coordinator, priority, observer, series-interrupt).
- DM stress tests: `.venv\Scripts\python.exe tests/download_manager/test_dm_stress.py` (10 heavy-load scenarios H1–H10).
- Load tests: `.venv\Scripts\python.exe tests/load/run_load_test.py` (11 scenarios L1–L11 — multi-patient multi-modality: 2CT+3XR+1MRI, preemption, cache, scroll, progressive grow, pool-freed callback).
- Viewer tests: `.venv\Scripts\python.exe -m pytest tests/viewer/test_fast_viewer_pipeline.py -v` (13 tests — covers progressive display, done-guard, stale-guard, DM notify cooldown, import path resolution, H4-fix done-guard lifecycle).
- Network tests: `.venv\Scripts\python.exe tests/network/test_network.py` (8 scenarios).
- Database tests: `.venv\Scripts\python.exe tests/database/run_db_test.py` (7 scenarios).
- UI services tests: `.venv\Scripts\python.exe tests/ui_services/test_ui_services.py`.
- Smoke tests (imports): `.venv\Scripts\python.exe -m pytest tests/smoke/test_import_smoke.py -v` (26+ module imports).
- Connection tests: `.venv\Scripts\python.exe -m pytest tests/connection_between_modules/ -v`.
- All tests: run each suite separately; no unified test runner.

## Where to look for feature work
- Patient UI and tabs: `PacsClient/pacs/patient_tab/**`.
- MPR modules: `PacsClient/pacs/patient_tab/zeta mpr/**` and `advance_mpr_3d_slicer/**`.
- Home UI services: `PacsClient/pacs/workstation_ui/home_ui/{home_db_service,home_tab_service,home_download_service,home_search_service,home_module_tabs,home_widget_utils}.py`.
- Download engine + state: `PacsClient/zeta_download_manager/{core,download,network,storage,state,ui}`.
- Download manager (modular): `modules/download_manager/{core,download,network,rules,state,ui}` — retry constants, validation rules (R17), series downloader, socket client.
- Download validation rules: `modules/download_manager/rules/validation_rules.py` (R17a/R17b duplicate/resume detection).
- Network / server comms: `modules/network/{socket_service,socket_client,socket_config,socket_token_manager,grpc_client}.py` — see `docs/architecture/network-architecture.md`.
- Download-path socket client: `modules/download_manager/network/socket_client.py` (SocketDicomClient) with health monitoring in `health_monitor.py`.
- Progressive viewer loading: `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` (throttle, inflight guard, done-guard, grow timer, `_ensure_import_folder_path`, stale-guard show-then-refresh, DM notify cooldown).
- Scroll performance: `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget.py` (set_slice, wheelEvent, adaptive throttle, GC suppression).
- DL_WARMUP subprocess: `PacsClient/pacs/patient_tab/zeta_boost/warmup_subprocess.py`.
- Image pipeline / ITK filters: `PacsClient/pacs/patient_tab/utils/image_filters.py` and `image_io.py`.
- Reference lines during scroll: `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget.py` (`_schedule_reference_line_update`, `_do_lock_sync`).

## Documentation rules for AI
- When changing image pipeline or sync mapping, update `docs/IMAGE_PIPELINE_REFERENCE.md`.
- When changing Zeta MPR internals, update `PacsClient/pacs/patient_tab/zeta mpr/ZETA_MPR_PIPELINE_REFERENCE.md`.
- When bumping versions, update `VERSION_*.md` with date, tag, and commit.
- When changing scroll performance, update `docs/PERFORMANCE_STATUS.md`, `docs/METRICS_TRACKING_v2.2.3.x.md`, and `docs/PERFORMANCE_DECISION_LOG_2026-02-27.md`.
- When adding new per-frame overhead to `set_slice()`, guard it with `_in_wheel_scroll` check and document in `PERFORMANCE_STATUS.md`.
- When changing download retry/reconnection/validation logic, update `docs/pipelines/download-pipeline.md` and `docs/releases/RELEASE_NOTES.md`.
- When changing R17 validation rules, update the "Validation Rules (R17)" section in `docs/pipelines/download-pipeline.md`.
- When changing home UI services (DB, tab, download, search), update `docs/architecture/home-ui-services.md`.
- When changing database connection management, commit patterns, indexes, or logging, update `docs/architecture/database-architecture.md`.
- When adding new home_ui service files, update the file map in `docs/architecture/home-ui-services.md` and add exports to `PacsClient/pacs/workstation_ui/home_ui/__init__.py`.
- When changing socket protocol (framing, endpoints, auth) or gRPC service, update `docs/architecture/network-architecture.md`.
- When changing retry/reconnection constants or health monitor rules, update `docs/architecture/network-architecture.md` and `docs/pipelines/download-pipeline.md`.
- When adding new socket endpoints, add them to the endpoint table in `docs/architecture/network-architecture.md`.
- When changing `SocketConfig` defaults or TCP tuning, update the config tables in `docs/architecture/network-architecture.md`.
- When changing progressive display guards (`_progressive_display_done`, `_progressive_display_inflight`), grow timer intervals, or `_start_progressive_display` threading model, update this copilot-instructions.md and verify with `tests/viewer/test_fast_viewer_pipeline.py`.
- When changing DM priority notification timing (`_notify_dm_viewed_series`, cooldown, coordinator intervals), verify with `tests/download_manager/run_dm_test.py` scenarios S22-S26.
- When changing throttle/timer constants (progressive grow, progress debounce, coordinator recheck/retry, observer refresh delay), document old→new values in this file under Critical rules.

## Cross-PC improvement cycle (mandatory)
- **PC roles:** treat the current development machine as **PC A (Developer PC)**. Other machines (e.g., PC B) are validation targets.
- **Standard cycle for every optimization/debugging change:**
	1. Apply code changes locally on **PC A**.
	2. Validate locally on **PC A** (focused run/log check for the changed flow).
	3. Push updated code from **PC A** to GitHub.
	4. Pull the same commit on **PC B**.
	5. Re-run the same scenario on **PC B** and compare behavior/logs.
	6. Decide next iteration based on **PC A vs PC B** deltas, then repeat.
- **Scope:** use this cycle for all future cross-PC performance, stability, and debugging work.
- **Reference:** `docs/CROSS_PC_IMPROVEMENT_WORKFLOW.md`.

## Pipeline latency budget (v2.2.8.1)
End-to-end from DM worker progress → visible in viewer:
| Layer | Timer | Purpose |
|---|---|---|
| DM progress batch | 100ms | `_progress_throttle_timer` — batches per-image signals into one Qt emission |
| Viewer progress debounce | 100ms | `on_series_images_progress` per-series throttle — prevents CPU spike |
| Progressive grow timer | 150ms | `_progressive_grow_timer` — controls batch growth cadence |
| Coordinator queue recheck | 50ms | `negotiate_priority_change` — delay before paused→pending starts |
| Coordinator retry | 200ms | `schedule_priority_start_retry` — polling when worker can't start |
| Observer refresh | 0ms | UIObserver priority→`refresh_table_order` — next event loop tick |
| Worker completion → next | 0ms | `_on_worker_completed` → `_start_next_pending` — next event loop tick |
| DM notify cooldown | 500ms | `_DM_VIEWED_NOTIFY_COOLDOWN_MS` — per-series dedup for drag-drop |

Worst-case perceived latency (image downloaded → visible): **~350ms**. Do NOT increase any timer without measuring the user-visible impact.

Worst-case series-switch latency (drag-drop → new series starts): **~batch RTT + 250ms** (cancel detection at next chunk/batch boundary + coordinator queue_recheck + pool cleanup). Previously was "remaining current series download time" (could be minutes).

## Complete file map (AI agent quick-lookup)

### Entry points and shell
| File | Key class / function | Purpose |
|------|---------------------|---------|
| `main.py` | — | App entry; sets OpenGL flags, creates `QEventLoop`, launches `AppHandler` |
| `aipacs_runtime.py` | `user_data_root()`, `roaming_config_root()` | Path resolution for dev vs PyInstaller |
| `_project_root.py` | `PROJECT_ROOT` | Canonical root path resolution |
| `PacsClient/app_handler.py` | `AppHandler` | Login → main window transition |
| `PacsClient/login/ui/login_ui.py` | `LoginWindow` | Login form UI |

### Workstation shell (PacsClient/pacs/workstation_ui/)
| File | Key class | Purpose |
|------|----------|---------|
| `mainwindow_ui.py` | `MainWindowWidget` | Top-level window with sidebar + tab container |
| `AIPacs_ui.py` | `ControlPanelInterface` | Sidebar control panel |
| `combined_tab_widget.py` | `CombinedTabWidget` | Tab container for patient/module tabs |
| `loading_screen.py` | `LoadingScreen` | Splash screen |
| `shortcut_manager.py` | `ShortcutManager` | Global keyboard shortcuts |
| `theme_ui.py` | — | Theme switching logic |
| `user_manual_widget.py` | `UserManualWidget` | Built-in help |
| `web_browser_ui.py` | — | Web browser tab integration |

### Home UI (PacsClient/pacs/workstation_ui/home_ui/)
| File | Key class | Purpose |
|------|----------|---------|
| `home_ui.py` | — (shim) | Backward-compatible shim re-exporting from `home_panel/` |
| `home_panel/widget.py` | `HomePanelWidget` | Core class: `__init__`, class attrs, 10 mixin bases |
| `home_panel/_hp_layout.py` | `_HpLayoutMixin` | UI layout setup |
| `home_panel/_hp_patient_open.py` | `_HpPatientOpenMixin` | Patient open/double-click |
| `home_panel/_hp_search.py` | `_HpSearchMixin` | Search logic |
| `home_panel/_hp_import.py` | `_HpImportMixin` | CD/local DICOM import |
| `home_panel/_hp_download.py` | `_HpDownloadMixin` | Download start/wiring |
| `home_panel/_hp_series.py` | `_HpSeriesMixin` | Series ops |
| `home_panel/_hp_priority.py` | `_HpPriorityMixin` | Priority management |
| `home_panel/_hp_modules.py` | `_HpModulesMixin` | Module tab management |
| `home_panel/_hp_offline.py` | `_HpOfflineMixin` | Offline/cloud operations |
| `home_panel/_hp_study_save.py` | `_HpStudySaveMixin` | Study save to DB |
| `home_db_service.py` | `HomeDbService` | DB ops: save patient, get studies, search local |
| `home_tab_service.py` | `HomeTabService` | Tab create/activate/find logic |
| `home_download_service.py` | `HomeDownloadService` | Wire DM signals, start downloads, connect progress |
| `home_search_service.py` | `HomeSearchService` | Server search via socket, result handling |
| `home_module_tabs.py` | `activate_or_create_module_tab()`, `find_existing_module_tab()` | Shared tab-find-or-create |
| `home_widget_utils.py` | `is_widget_alive()` | Safe `sip.isdeleted()` wrapper |
| `patient_table_widget.py` | `PatientTableWidget` | Table showing patient/study list |
| `patient_search_widget.py` | `PatientSearchWidget` | Search bar and filters |
| `right_panel_widget.py` | `RightPanelWidget` | Right-side panel (study details) |
| `data_access_panel.py` | `DataAccessPanelWidget` | CD import / local DICOM source selector |
| `import_preview_dialog.py` | — | Preview before importing local DICOM |
| `report_status_dialog.py` | — | Report status display |
| `secretary_button_widget.py` | `SecretaryButtonWidget` | EchoMind AI secretary button |

### Settings UI (PacsClient/pacs/workstation_ui/settings_ui/)
| File | Key class | Purpose |
|------|----------|---------|
| `settings_ui.py` | `SettingsTabWidget` | Settings tab container |
| `server_settings.py` | `ServerSettingsWidget` | Server IP/port config |
| `servers_config.py` | `ServersConfigWidget` | Multi-server management |
| `viewerconfigsetting.py` | `ModalityGridConfigWidget` | Grid layout per modality |
| `filter_config.py` | `FilterConfigWidget` | Image filter presets |
| `tools_settings_ui.py` | `ToolsSettingsWidget` | Measurement/annotation tools config |
| `storage_cleanup_panel.py` | `StorageCleanupPanelWidget` | Disk cleanup settings |
| `installation_module_settings.py` | `InstallationModuleSettingsWidget` | Module enable/disable |
| `lightviewer_settings.py` | `LightViewerSettingsWidget` | CD-burner light viewer config |
| `external_pacs_settings.py` | `ExternalPacsSettingsWidget` | External PACS server config |
| `echomind_settings.py` | `EchoMindSettingsWidget` | AI assistant settings |

### Patient tab (PacsClient/pacs/patient_tab/ui/patient_ui/)
| File | Key class | Purpose |
|------|----------|---------|
| `patient_widget.py` | — (shim) | Backward-compatible shim re-exporting from `patient_widget_core/` |
| `patient_widget_core/widget.py` | `PatientWidget` | Core class: `__init__`, class attrs, 9 mixin bases |
| `patient_widget_core/_pw_sync.py` | `_PwSyncMixin` | Cross-viewer sync, lock sync |
| `patient_widget_core/_pw_advanced.py` | `_PwAdvancedMixin` | Advanced viewer, 3D, MPR |
| `patient_widget_core/_pw_panels.py` | `_PwPanelsMixin` | Side panels, toolbars |
| `patient_widget_core/_pw_viewers.py` | `_PwViewersMixin` | Viewer creation and management |
| `patient_widget_core/_pw_series.py` | `_PwSeriesMixin` | Series switch, selection |
| `patient_widget_core/_pw_pipeline.py` | `_PwPipelineMixin` | Image pipeline, progressive display |
| `patient_widget_core/_pw_thumbnails.py` | `_PwThumbnailsMixin` | Thumbnail management |
| `patient_widget_core/_pw_metadata.py` | `_PwMetadataMixin` | Metadata handling |
| `patient_widget_core/_pw_lifecycle.py` | `_PwLifecycleMixin` | Init, cleanup, tab lifecycle |
| `patient_widget_viewer_controller.py` | `ViewerController` (mixin) | Series switch, progressive display, DM notify, stale guard |
| `vtk_widget.py` | `VTKWidget` | VTK render widget; `set_slice()`, wheelEvent, GC suppression |
| `widget_viewer.py` | — | Viewer wrapper coordinating VTK + overlays |
| `viewer_state_controller.py` | — | Viewer state (active/inactive, selected) |
| `viewer_isolation_guard.py` | — | Prevents cross-viewer interference during operations |
| `multi_viewer_layout_manager.py` | `MultiViewerLayoutManager` | 1×1, 2×2, 3×3 grid layout |
| `center_layout_widget.py` | `CenterLayoutWidget` | Central viewer area |
| `header_widget.py` | `HeaderWidget` | Patient info header bar |
| `sidebar_widget.py` | `SidebarWidget` | Thumbnail sidebar |
| `thumbnail_panel.py` | — | Series thumbnail display |
| `custom_tab_manager.py` | `CustomTabManager` | Per-patient tab management |
| `patient_tab_widget.py` | `PatientTabWidget` | Tab wrapper for PatientWidget |
| `reception_panel_widget.py` | — | Reception reports panel |
| `reception_reports_viewer.py` | — | Report viewer inside patient tab |
| `service_tab_widget.py` | — | Service/module tab in patient context |

### Patient tab toolbar (PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/)
| File | Key class | Purpose |
|------|----------|---------|
| `toolbar_manager.py` | `ToolbarManager` | Main toolbar; tool select, annotations, W/L |
| `reference_line.py` | — | Reference line computation and rendering |
| `attachments_dropdown.py` | `AttachmentsDropdownWidget` | Voice/AI attachments panel |
| `voice_tool_ui.py` | `VoiceWidget` | Voice recording tool |

### Patient tab utilities (PacsClient/pacs/patient_tab/utils/)
| File | Key class / function | Purpose |
|------|---------------------|---------|
| `image_filters.py` | — | ITK/VTK image filter pipeline |
| `image_io.py` | — | DICOM read/write, ITK↔VTK conversion (`convert_itk2vtk`) |
| `image_io_improved.py` | — | Optimized image I/O variant |
| `cache.py` | — | In-memory image cache |
| `vtk_utils.py` | `ThreadSafeOverlayManager`, `VTKMemoryManager` | VTK memory and overlay helpers |
| `thumbnail_manager.py` | `ThumbnailManager` | Thumbnail generation and caching |
| `patient_sync_service.py` | `PatientSyncService` | Cross-viewer sync (scroll, W/L) |
| `config_manager.py` | — | Per-patient viewer config |
| `dicom_windowing.py` | — | Window/Level presets and calculation |
| `corner_labels.py` | — | DICOM tag overlay on viewer corners |
| `series_layout_matrix.py` | `MatrixSelector` | Grid layout selector widget |
| `preload_settings.py` | — | Prefetch/preload configuration |
| `state_management.py` | — | Viewer state persistence |
| `tools_settings.py` | `ToolsSettingsManager` | Tool preferences |
| `button_safeguard.py` | — | Button debounce/safe-click guard |
| `cancellation.py` | — | Cancellation token pattern |
| `circuit_breaker.py` | — | Circuit breaker for external calls |
| `retry.py` | — | Retry decorator |
| `exceptions.py` | — | Patient tab specific exceptions |
| `validation.py` | — | Input validation helpers |
| `file_watcher.py` | — | Filesystem change monitoring |
| `node_viewer.py` | — | Node/tree viewer utility |
| `opencv_filter_pipeline.py` | — | OpenCV image filter chain |

### Application components (PacsClient/components/)
| File | Key class | Purpose |
|------|----------|---------|
| `lifecycle_manager.py` | `LifecycleManager` | Shutdown callback registry, health checks |
| `loading_overlay.py` | `AiPacsLoadingOverlay` | Animated loading overlay |

### Shared utils (PacsClient/utils/)
| File | Key class / function | Purpose |
|------|---------------------|---------|
| `config.py` | `BASE_PATH`, `SOURCE_PATH`, `ICON_PATH`, etc. | Central path registry (dev + PyInstaller) |
| `data_paths.py` | `USER_DATA_ROOT`, `DICOM_IMAGES_DIR`, `DATABASE_FILE`, etc. | All user-data path definitions |
| `database.py` | `get_db_connection()`, `init_database()` | DB connection pool, schema, FK indexes |
| `db_manager.py` | — | Query helpers (patient/study/series CRUD) |
| `theme_manager.py` | `ThemeManager` | CSS theme loading and switching |
| `font_manager.py` | `FontManager` | Font loading (IranYekan) |
| `css_utils.py` | — | CSS generation utilities |
| `diagnostic_logging.py` | — | Structured logging setup |
| `single_instance_lock.py` | — | Prevent multiple app instances |
| `scroll_style.py` | — | Scrollbar CSS styling |
| `utils.py` | `BoxManager`, `get_server_url()` | Misc utilities |

### Download Manager (modules/download_manager/)
| File | Key class | Purpose |
|------|----------|---------|
| `core/constants.py` | `BATCH_SIZE`, `MAX_RETRIES`, `RECONNECT_*`, etc. | All retry/timing/limit constants |
| `core/enums.py` | `DownloadPriority`, `DownloadStatus`, `PreemptionAction` | Priority (LOW→CRITICAL), status states |
| `core/models.py` | `DownloadTask`, `DownloadState`, `DownloadResult`, `RuleResult`, etc. | Data classes for entire DM pipeline |
| `core/exceptions.py` | `DownloadError` | DM exception hierarchy |
| `state/state_store.py` | `DownloadStateStore` | In-memory state with observer notifications |
| `state/state_machine.py` | `DownloadStateMachine` | Valid state transitions |
| `state/observers.py` | `StateObserver` (ABC), `UIObserver`, `DatabaseObserver`, `PriorityObserver`, `LoggingObserver`, `ValidationObserver` | Observer pattern for state changes |
| `coordinator/series_intent_coordinator.py` | `SeriesIntentCoordinator` | Priority negotiation, series-interrupt, worker lifecycle |
| `rules/rule_engine.py` | `DownloadRuleEngine`, `RuleContext` | Rule evaluation pipeline |
| `rules/validation_rules.py` | `ValidationRules` | R17a/R17b duplicate/resume detection |
| `rules/priority_rules.py` | `PriorityRules`, `PreemptionResult` | Preemption logic |
| `rules/resume_rules.py` | `ResumeRules` | R19b batch-skip, file verification |
| `download/executor.py` | `DownloadExecutor` | Download execution engine |
| `download/series_downloader.py` | `SeriesDownloader` | Per-series download with batch skip |
| `download/batch_processor.py` | `BatchProcessor` | Batch-level download (BATCH_SIZE instances) |
| `download/progress_tracker.py` | `ProgressTracker`, `ProgressUpdate` | Progress signal emission |
| `workers/download_process_worker.py` | `DownloadProcessWorker` | QThread subprocess wrapper |
| `workers/download_subprocess.py` | — | Subprocess entry point (own GIL) |
| `workers/download_worker.py` | — | In-process worker variant |
| `workers/subprocess_worker.py` | — | Subprocess communication bridge |
| `workers/worker_pool.py` | — | Worker pool management |
| `workers/database_worker.py` | — | Background DB operations |
| `workers/download_process_entry.py` | — | Subprocess entry registration |
| `network/socket_client.py` | `SocketDicomClient` | DICOM download socket client |
| `network/connection_pool.py` | `ConnectionPool` | Socket connection pooling |
| `network/health_monitor.py` | `ConnectionHealthMonitor`, `HealthMetrics` | R30–R34 health rules |
| `network/grpc_client.py` | `GrpcMetadataClient` | gRPC metadata/thumbnail fetcher |
| `storage/file_manager.py` | `FileManager` | Directory/file management |
| `storage/database_manager.py` | `DatabaseManager` | DM-specific DB operations |
| `storage/thumbnail_cache.py` | `ThumbnailCache` | Thumbnail file caching |
| `ui/main_widget.py` | — (shim) | Backward-compatible shim re-exporting from `ui/widget/` |
| `ui/widget/widget.py` | `DownloadManagerWidget` | Core DM UI class with 9 mixin bases |
| `ui/widget/_dm_ui_setup.py` | `_DmUiSetupMixin` | UI initialization & table setup |
| `ui/widget/_dm_queue.py` | `_DmQueueMixin` | Queue management & task creation |
| `ui/widget/_dm_controls.py` | `_DmControlsMixin` | Pause/resume/cancel controls |
| `ui/widget/_dm_workers.py` | `_DmWorkersMixin` | Worker lifecycle & signals |
| `ui/widget/_dm_retry.py` | `_DmRetryMixin` | Retry logic (series + per-patient) |
| `ui/widget/_dm_details.py` | `_DmDetailsMixin` | Detail panel & status display |
| `ui/widget/_dm_priority.py` | `_DmPriorityMixin` | Priority management |
| `ui/widget/_dm_reception.py` | `_DmReceptionMixin` | Reception/AI integration |
| `ui/widget/_dm_theming.py` | `_DmThemingMixin` | Theme color & stylesheet |
| `utils/config_loader.py` | — | DM config loading |
| `utils/logger.py` | — | DM-specific logger |
| `utils/validators.py` | — | Input validators |

### Network (modules/network/)
| File | Key class / function | Purpose |
|------|---------------------|---------|
| `socket_service.py` | `SocketService` (singleton) | Single entry point for all socket calls |
| `socket_client.py` | `PatientListSocketClient` | Patient list and general socket requests |
| `socket_config.py` | `SocketConfig` | Config from `config/socket_config.json` or env vars |
| `socket_token_manager.py` | `SocketTokenManager` | JWT token management |
| `socket_patient_service.py` | — | Patient-specific socket operations |
| `socket_report_status_service.py` | — | Report status socket operations |
| `grpc_client.py` | `DicomGrpcClient` | gRPC client for thumbnails (`_ensure_stub()` auto-reconnect) |
| `connection_health_monitor.py` | — | Network-level health monitoring |
| `dicom_downloader.py` | — | Legacy DICOM downloader |
| `dicom_downloader_client_help.py` | — | Legacy download helper |
| `series_utils.py` | — | Series-level utility functions |
| `server_settings_dialog.py` | — | Server settings UI dialog |
| `upload_download_attchments.py` | — | Attachment upload/download |
| `upload_task_manager.py` | — | Upload task management |
| `zeta_adapter.py` | — | Zeta DM adapter (legacy bridge) |
| `multi.py` | — | Multi-connection handling |

### Viewer module (modules/viewer/)
| File | Key class | Purpose |
|------|----------|---------|
| `fast/lightweight_2d_pipeline.py` | `Lightweight2DPipeline` | Fast 2D rendering pipeline |
| `fast/pydicom_2d_backend.py` | `PyDicom2DBackend` | PyDicom-based 2D slice backend |
| `fast/pydicom_lazy_volume.py` | `PyDicomLazyVolume` | Lazy-loading volume for progressive display |
| `fast/qt_slice_viewer.py` | `QtSliceViewer` | Qt widget rendering individual slices |
| `fast/qt_viewer_bridge.py` | `QtViewerBridge` | Bridge between Qt viewer and VTK API |
| `fast/contracts.py` | `IViewer2DBackend` (Protocol), `FrameData`, `GeometryData` | Viewer backend interface contract |
| `fast/stale_frame_guard.py` | — | Detects and handles stale cached frames |
| `fast/lazy_volume_registry.py` | — | Registry of loaded lazy volumes |
| `backends/pydicom_2d_backend.py` | `PyDicom2DBackend` | Alternate backend location |
| `backends/pydicom_lazy_volume.py` | `PyDicomLazyVolume` | Alternate lazy volume location |
| `pipeline/orchestrator.py` | `PipelineOrchestrator`, `PipelineState` | Series loading orchestration |
| `pipeline/load_coordinator.py` | `LoadCoordinator` | In-flight load deduplication |
| `pipeline/preview_engine.py` | `PreviewEngine` | Quick preview before full load |
| `advanced/viewer_2d.py` | — | Advanced 2D viewer (VTK) |
| `advanced/viewer_2d_optimized.py` | — | Optimized advanced viewer |
| `advanced/viewer_2d_with_tools.py` | `Viewer2DWithTools` | 2D viewer with measurement tools |
| `advanced/viewer_3d.py` | `Viewer3DWidget` | 3D volume rendering |
| `advanced/vtk_3d_presets.py` | `VolumePresetConfig` | 3D rendering presets (bone, soft tissue, etc.) |
| `advanced/filter_config_widget.py` | `FilterConfigWidget` | Filter UI |
| `advanced/image_filter_sidebar.py` | — | Filter sidebar |
| `advanced/preset_manager.py` | — | User preset management |
| `advanced/advanced_tools_panel.py` | — | Advanced tools toolbar |
| `widgets/loading_spinner.py` | `LoadingSpinner`, `ViewportSpinner` | Viewport loading indicators |
| `widgets/medical_loading_overlay.py` | `MedicalLoadingOverlay` | Medical-themed overlay |
| `interactor_styles/` | `AbstractInteractorStyle` + tool implementations | Ruler, angle, ROI, eraser, etc. |
| `interactor_styles/tools_object_manager.py` | `RulerObject`, `AngleObject`, `RoiObject`, etc. | Measurement tool objects |
| `boost_viewer_config.py` | — | Boost viewer configuration |
| `viewer_backend_config.py` | — | Backend selection config |
| `gpu_boost.py` | — | GPU acceleration utilities |

### ZetaBoost cache (modules/zeta_boost/)
| File | Key class | Purpose |
|------|----------|---------|
| `engine.py` | — (shim) | Backward-compatible shim re-exporting from `cache_engine/` |
| `cache_engine/widget.py` | `ZetaBoostEngine` | Core class: `__init__`, class attrs, mixin assembly |
| `cache_engine/_zb_globals.py` | — | Module-level globals: `_GLOBAL_DOWNLOAD_ACTIVE`, `set_global_download_active`, `_set_thread_low_priority` |
| `cache_engine/_zb_cache.py` | `_ZBCacheMixin` | Cache ops: query, get, put, trim, clear, evict, invalidate |
| `cache_engine/_zb_lanes.py` | `_ZBLanesMixin` | Lane management: enqueue, clear pending, lane-locked helpers |
| `cache_engine/_zb_workers.py` | `_ZBWorkersMixin` | Worker loop, disk promotion, memory check, failsafe |
| `cache_engine/_zb_lifecycle.py` | `_ZBLifecycleMixin` | Lifecycle, state, health, global lock, boost mode |
| `disk_cache.py` | — | L2 disk cache management |
| `image_slice_booster.py` | — | Per-slice boost/prefetch |
| `warmup_subprocess.py` | `WarmupSubprocessManager` | Dedicated subprocess for cache warmup (IDLE priority) |

### Other modules
| Module | Key files | Purpose |
|--------|----------|---------|
| `modules/module_system/module_manager.py` | `ModuleManager`, `ModuleState` | Dynamic module loading/lifecycle |
| `modules/module_system/pipeline_orchestrator.py` | — | Module execution pipeline |
| `modules/module_system/dynamic_thread_optimizer.py` | — | Thread pool auto-tuning |
| `modules/zeta_sync/sync_manager.py` | `SyncManager` | Cross-viewer synchronization |
| `modules/zeta_sync/sync_context.py` | — | Sync state context |
| `modules/zeta_sync/geometry_utils.py` | — | Geometry calculations for sync |
| `modules/storage/disk_alert_service.py` | — | Low disk space alerts |
| `modules/storage/local_storage_cleanup_manager.py` | — | Automated cleanup |
| `modules/storage/patient_cleanup_manager.py` | — | Per-patient file cleanup |
| `modules/storage/storage_calculator.py` | — | Disk usage calculation |
| `modules/storage/thumbnail_store.py` | — | Thumbnail storage management |
| `modules/printing/` | `PrintingWidget`, `GridLayoutEngine`, `PrintToolManager` | Film printing pipeline |
| `modules/cd_burner/` | `CDBurnManager`, `DicomDirBuilder` | CD/DVD burning with light viewer |
| `modules/stitching/` | `StitchingWidget`, `StitchController`, `StitchEngine`, `LandmarkStore` | Image stitching/panorama |
| `modules/ai_imaging/` | — | AI segmentation and analysis UI |
| `modules/EchoMind/` | `ChatController`, `AIChatViewer` | AI assistant (LLM chat) |
| `modules/data_analysis/` | — | Data analysis tools |
| `modules/web_browser/` | `WebBrowserWidget`, `BrowserStateStore` | Integrated web browser |

### Database (database/)
| File | Key function | Purpose |
|------|-------------|---------|
| `core.py` | `get_db_connection()`, `init_database()`, `SocketConnectionPool` | Connection pool, schema, WAL mode, FK indexes |
| `manager.py` | CRUD helpers | Patient/study/series/instance DB operations |
| `migrations/` | — | Schema migration scripts |

### Config files (config/)
| File | Purpose | Loaded by |
|------|---------|-----------|
| `socket_config.json` | Server host/port/timeout | `SocketConfig` |
| `boostviewer_settings.json` | ZetaBoost cache sizes, thread counts | `ZetaBoostEngine` |
| `viewer_backend_settings.json` | Backend selection (fast vs advanced) | `viewer_backend_config.py` |
| `modality_grid.json` | Default grid layout per modality (CT=1×1, MR=2×2, etc.) | `ModalityGridConfigWidget` |
| `filter_presets.json` | Saved image filter presets | `FilterConfigWidget` |
| `filter_settings.json` | Default filter parameters | Image filter pipeline |
| `patient_table_columns.json` | Visible columns in patient table | `PatientTableWidget` |
| `patient_table_font.json` | Patient table font settings | `PatientTableWidget` |
| `patient_table_sort.json` | Default sort column and order | `PatientTableWidget` |
| `printing_config.json` | Print paper size, DPI, layout | Printing module |
| `slicer_config.json` | 3D Slicer integration settings | MPR module |
| `installation_profile.json` | Enabled/disabled modules | `ModuleManager` |
| `external_pacs_servers.json` | External PACS server list | External PACS settings |
| `lightviewer_settings.json` | CD-burner light viewer config | CD burner module |
| `pooyan_opencv_filter.json` | OpenCV filter chain presets | `opencv_filter_pipeline.py` |

## Class hierarchy quick-reference

### Viewer stack
```
QWidget
  ├─ PatientWidget (patient_widget_core/widget.py) — container, 9 mixins (sync, advanced, panels, viewers, series, pipeline, thumbnails, metadata, lifecycle)
  │   └─ mixin: ViewerController (patient_widget_viewer_controller.py) — series switch, progressive
  ├─ VTKWidget (vtk_widget.py) — VTK rendering, set_slice, scroll
  ├─ QtSliceViewer (qt_slice_viewer.py) — fast 2D Qt viewer
  ├─ Viewer2DWithTools (viewer_2d_with_tools.py) — measurement tools
  └─ Viewer3DWidget (viewer_3d.py) — 3D volume rendering

QObject
  ├─ PyDicomLazyVolume — progressive volume loading
  ├─ PyDicom2DBackend — slice extraction
  ├─ Lightweight2DPipeline — fast render pipeline
  ├─ ThumbnailManager — thumbnail generation
  └─ PatientSyncService — cross-viewer sync
```

### Download Manager stack
```
DownloadStateStore — in-memory state, observer notify
  ├─ observers: UIObserver, DatabaseObserver, PriorityObserver, LoggingObserver, ValidationObserver
  └─ state machine: DownloadStateMachine

SeriesIntentCoordinator — priority negotiation, series-interrupt
  ├─ uses: DownloadStateStore, PriorityRules
  └─ timers: queue_recheck (50ms), retry_poller (200ms)

DownloadRuleEngine — R17a/R17b/R19b/R20 rule evaluation
  ├─ ValidationRules, PriorityRules, ResumeRules
  └─ context: RuleContext enum

DownloadProcessWorker (QThread) — subprocess wrapper
  └─ subprocess: SeriesDownloader → BatchProcessor → SocketDicomClient
```

### Home UI service layer
```
HomePanelWidget (thin controller)
  ├─ HomeDbService — DB reads/writes
  ├─ HomeTabService — tab create/find/activate
  ├─ HomeDownloadService — wire DM signals, start downloads
  └─ HomeSearchService — server search via socket
```

## Function lookup (common searches)

### "Where does X happen?"
| What you're looking for | File → function |
|------------------------|----------------|
| App startup | `main.py` → `main()` |
| Login authentication | `PacsClient/login/ui/login_ui.py` → `LoginWindow` |
| Patient double-click → open tab | `home_ui.py` → `_on_patient_double_clicked_async()` |
| Series drag-drop → viewer | `patient_widget_viewer_controller.py` → `change_series_on_viewer()` |
| Download priority change | `series_intent_coordinator.py` → `request_critical_series()` |
| Progressive display start | `patient_widget_viewer_controller.py` → `_start_progressive_display()` |
| Progressive display grow | `patient_widget_viewer_controller.py` → `_grow_progressive_fast()` |
| Scroll / slice change | `vtk_widget.py` → `set_slice()`, `wheelEvent()` |
| Window/Level adjustment | `vtk_widget.py` → window/level interactor style |
| Reference line update | `patient_widget.py` → `_schedule_reference_line_update()` |
| Lock sync (cross-viewer scroll) | `patient_widget.py` → `_do_lock_sync()` |
| Save patient to DB | `home_db_service.py` → `save_patient_and_study_on_db()` |
| Search patients on server | `home_search_service.py` → `search_patients_server()` |
| Socket request/response | `socket_service.py` → `send_request()` |
| gRPC thumbnail fetch | `grpc_client.py` → `get_thumbnail()` |
| Series download (single) | `series_downloader.py` → `download_series()` |
| Batch skip (R19b) | `series_downloader.py` → batch_start advance logic |
| Duplicate detection (R17) | `validation_rules.py` → `check_duplicate()` |
| DM state change → UI | `observers.py` → `UIObserver.on_state_changed()` |
| DB connection acquire | `database/core.py` → `get_db_connection()` |
| Init DB schema + indexes | `database/core.py` → `init_database()` |
| Theme switch | `PacsClient/utils/theme_manager.py` → `ThemeManager.apply_theme()` |
| Shutdown / cleanup | `PacsClient/components/lifecycle_manager.py` → `LifecycleManager.shutdown_all()` |
| Module enable/disable | `modules/module_system/module_manager.py` |
| ZetaBoost cache warmup | `modules/zeta_boost/cache_engine/widget.py` → `ZetaBoostEngine` |
| Warmup subprocess | `modules/zeta_boost/warmup_subprocess.py` → `WarmupSubprocessManager` |
| Disk cleanup | `modules/storage/local_storage_cleanup_manager.py` |
| Image stitching | `modules/stitching/stitch_engine.py` |
| CD burn | `modules/cd_burner/cd_burn_manager.py` → `CDBurnManager` |
| Print film | `modules/printing/ui/printing_widget.py` → `PrintingWidget` |
| AI chat | `modules/EchoMind/viewer_chat/ai_chat_api.py` → `ChatController` |

### "Where are the constants for X?"
| Constant category | File |
|------------------|------|
| Download retry/timing | `modules/download_manager/core/constants.py` |
| Download priorities | `modules/download_manager/core/enums.py` → `DownloadPriority` |
| Download statuses | `modules/download_manager/core/enums.py` → `DownloadStatus` |
| Socket config | `config/socket_config.json` + `modules/network/socket_config.py` |
| Viewer backend | `config/viewer_backend_settings.json` |
| Boost cache sizes | `config/boostviewer_settings.json` |
| Grid layout defaults | `config/modality_grid.json` |
| Resource paths | `PacsClient/utils/config.py` + `PacsClient/utils/data_paths.py` |
| All user data paths | `PacsClient/utils/data_paths.py` |
| Filter presets | `config/filter_presets.json` |

## Signal flow quick-reference

```
# ── Download start ──
HomePanelWidget._on_patient_double_clicked_async
  → HomeDownloadService.get_or_create_download_manager_tab
  → DownloadManagerWidget.start_priority_download_immediately(task)

# ── Download progress → Viewer ──
DownloadProcessWorker._progress_throttle_timer (100ms)
  → seriesProgressUpdated.emit(series_number, downloaded, total)
  → HomeDownloadService.on_series_progress
  → PatientWidget.series_images_progress.emit(sn, downloaded, total)
  → ViewerController.on_series_images_progress (100ms debounce)
  → _start_progressive_display (first) or _grow_progressive_fast (subsequent)

# ── Drag-drop priority change ──
ViewerController.change_series_on_viewer
  → QTimer.singleShot(0, _notify_dm_viewed_series)  [500ms cooldown]
  → DownloadManagerWidget.set_viewed_series
  → SeriesIntentCoordinator.request_critical_series
  → StateStore.update(priority=CRITICAL)
  → negotiate_priority_change → pause peers, 50ms recheck
  → UIObserver → QTimer.singleShot(0, refresh_table_order)

# ── Series interrupt (same study, different series) ──
request_critical_series(study_uid, series_number)
  → if worker downloading different series → cancel worker (non-blocking)
  → StateStore.update(status=PENDING)  [not PAUSED]
  → _start_next_pending picks up immediately

# ── Download completion ──
DownloadProcessWorker.finished
  → _on_worker_completed → QTimer.singleShot(0, _start_next_pending)
  → ZetaBoostEngine.notify_global_download_stop → prefetch begins

# ── State → DB + UI ──
StateStore.update(field, value)
  → _notify_observers
  → DatabaseObserver: persist to SQLite
  → UIObserver: update table row
  → PriorityObserver: trigger preemption check
  → LoggingObserver: structured log
  → ValidationObserver: integrity check
```

## Common debugging patterns

### "Download stuck / not starting"
1. Check `StateStore` state: series status should be PENDING, study not CANCELLED
2. Check `SeriesIntentCoordinator._start_next_pending()` — is it finding the study?
3. Check worker pool — is `_active_workers` at capacity?
4. Check rules: `ValidationRules.check_duplicate()` may be blocking (R17a)
5. Files: `modules/download_manager/coordinator/series_intent_coordinator.py`, `modules/download_manager/rules/validation_rules.py`

### "Progressive display not updating"
1. Check `_progressive_display_done` set — is series already marked done?
2. Check `_progressive_display_inflight` set — is a load already in progress?
3. Check done-guard recovery path — is it finding a viewer to re-activate?
4. Check `_progressive_grow_timer` — is it running?
5. Files: `patient_widget_viewer_controller.py` → `on_series_images_progress`, `_start_progressive_display`, `_grow_progressive_fast`

### "Viewer shows stale/wrong image"
1. Check stale guard: `_count_series_files_on_disk()` vs cache count
2. Check `_disk_count_cache` TTL (1s) — may be returning old count
3. Check show-then-refresh pattern — 150ms QTimer for background reload
4. Files: `patient_widget_viewer_controller.py` → `change_series_on_viewer` stale guard

### "UI freezes / blocks"
1. Check for synchronous I/O on main thread (must be in background thread)
2. Check no `stop_all()` in main-thread code (use `cancel_all_non_blocking()`)
3. Check QTimer.singleShot callbacks — are they marshaling back correctly?
4. Check 16ms rule — no module may block Qt event loop >16ms
5. Profile: wrap suspect code in `time.perf_counter()` calls

### "Database writes lost"
1. Check `conn.commit()` is called before `with get_db_connection()` block exits
2. Check not using bare `get_connection_database()` (leaks on exception)
3. Check no `PRAGMA read_uncommitted` (leaks via pool)
4. Files: `database/core.py`, `PacsClient/utils/database.py`

### "Socket connection failures"
1. Check `config/socket_config.json` — correct host/port?
2. Check `AIPACS_SOCKET_HOST`/`AIPACS_SOCKET_PORT` env vars
3. Check `ConnectionHealthMonitor` metrics
4. Check retry layers: send_request (3), connect_with_retry (5), per-series (3)
5. Files: `modules/network/socket_config.py`, `modules/download_manager/network/socket_client.py`

## Test coverage map

| Area | Test file | Scenarios | Run command |
|------|----------|-----------|-------------|
| State machine | `tests/download_manager/test_download_manager.py` S1 | State transitions | `python tests/download_manager/run_dm_test.py` |
| Priority preemption | S2 | HIGH pauses NORMAL, CRITICAL pauses all | same |
| Disconnect/reconnect | S3 | Socket failure → resume | same |
| File cleanup (R20) | S4 | Skip + per-patient deletion | same |
| Batch skip (R19b) | S5 | Sequential verification, gap detect | same |
| Thread safety | S6 | 8 threads × 12 ops | same |
| Observer fan-out | S7 | State → all observers | same |
| Rule engine (R17) | S8 | Duplicate + resume detection | same |
| Skip-count accuracy | S9 | existing_files_set | same |
| Priority ordering | S10 | CRITICAL > HIGH > NORMAL | same |
| Coordinator latency | S22 | negotiate <5ms | same |
| Series interrupt | S27 | Cancel + PENDING state | same |
| 50 concurrent patients | `tests/download_manager/test_dm_stress.py` H1 | StateStore capacity | `python tests/download_manager/test_dm_stress.py` |
| 500 series switches | H2 | Coordinator throughput | same |
| 16-thread contention | H3 | P99 lock wait | same |
| 10K progress updates | H4 | No dropped signals | same |
| Multi-patient load | `tests/load/run_load_test.py` L1–L11 | 2CT+3XR+1MRI, preemption, cache, scroll, progressive grow, pool-freed callback | `python tests/load/run_load_test.py` |
| Progressive display | `tests/viewer/test_fast_viewer_pipeline.py` | 20 tests | `python -m pytest tests/viewer/test_fast_viewer_pipeline.py -v` |
| Stage 1 migration | `tests/viewer/test_stage1_migration_validation.py` | 34 tests — resolution, alias, unreachability, guards, exhaustive matrix | `python -m pytest tests/viewer/test_stage1_migration_validation.py -v` |
| Stage 2 hardening | `tests/viewer/test_stage2_hardening_validation.py` | 15 tests — escape hatch, bind remap, sanity check, force_vtk override | `python -m pytest tests/viewer/test_stage2_hardening_validation.py -v` |
| Network protocol | `tests/network/test_network.py` | 8 scenarios | `python tests/network/test_network.py` |
| Database pool | `tests/database/run_db_test.py` | 7 scenarios | `python tests/database/run_db_test.py` |
| Import smoke | `tests/smoke/test_import_smoke.py` | 26+ modules | `python -m pytest tests/smoke/ -v` |
| Module connections | `tests/connection_between_modules/` | 5+ tests | `python -m pytest tests/connection_between_modules/ -v` |
| UI services | `tests/ui_services/test_ui_services.py` | import + basic | `python tests/ui_services/test_ui_services.py` |

## KPI thresholds

| KPI | Target | Measured | Test |
|-----|--------|----------|------|
| Coordinator latency | <5ms | ~0.2ms | S22 |
| State transitions (8 threads) | no corruption | pass | S6 |
| 500 series switches total time | <5s | ~1s | H2 |
| 16-thread P99 lock wait | <5ms | ~127ms (expected) | H3 |
| 10K progress updates (dropped) | 0 | 0 | H4 |
| Image downloaded → visible | <350ms | ~350ms | Pipeline budget |
| Scroll frame time | <16ms | 8–12ms | Performance test |
| Series-switch (drag-drop) | <batch RTT+250ms | ~250ms+RTT | Pipeline budget |

## Tools directory reference

| Directory | Purpose |
|-----------|---------|
| `tools/dev/` | Dev scripts: temp edits, import rewriting, test helpers |
| `tools/diagnostics/` | Diagnostic scripts: DB debug, series pipeline, path verification |
| `tools/git/` | Git automation: `Push-GitHub.ps1` |
| `tools/performance/` | Performance analysis: bottleneck reports, instrumentation |
| `tools/slicer/` | 3D Slicer integration: runtime assembly, DICOM testing |
| `tools/vtk/` | VTK merge conflict resolution patches |

## Builder / plugin system

- `builder/build_release.py` — Release build orchestrator
- `builder/plugin_package_registry.py` — Plugin package definition registry
- `builder/materialize_plugin_packages.py` — Copies plugin packages to build output
- `builder/plugin package/packages/` — Per-module plugin packages (download_manager, viewer, zeta_boost, printing, education, echomind, stitching, web_browser, run_cd)
- Each plugin package has: `payload/python/modules/<name>/` mirroring `modules/<name>/`
- **Builder copies override modules/** — for production builds, the builder copies may differ from `modules/`. Always check both locations when investigating production vs dev behavior.
