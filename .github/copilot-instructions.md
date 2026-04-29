# AIPacs Copilot Instructions

**Current Stable Version:** v2.4.6 (2026-04-26) — Advanced MPR stale runtime payload guard; fail-fast check blocks launch when installed `startup_script.py` is outdated (missing remote-command-server markers), preventing silent four-up/fourth-box fallback behavior. See `docs/releases/VERSION_2.4.6_RELEASE.md`. Inherits all v2.4.5 fixes (Advanced MPR launch UX, FAST corner-zoom structural fix, MPR frozen crash guard, `user_data_root()` writable fallback, build ASCII-safe print).

**In-flight (dev):** v2.3.8 R15 — Advanced (VTK) viewer joins the unified protected-interaction latch so R3/R4/R5 auto-extend to Advanced wheel/stack bursts. See R15 below.

## Architecture map (start here)
- App entry is `main.py` → `AppHandler` (login) → `MainWindowWidget` → `ControlPanelInterface` → `HomePanelWidget` for patient list and downloads.
- UI is PySide6 with qasync (`main.py` sets `QEventLoop`) and VTK; keep async UI work on the Qt event loop and offload heavy work to executor threads.
- Patient workflow lives in `PacsClient/pacs/workstation_ui/home_ui/home_ui.py` (thin controller) with services in `home_db_service.py`, `home_tab_service.py`, `home_download_service.py`, `home_search_service.py`.  See `docs/architecture/home-ui-services.md`.
- Download stack is Zeta-based: `PacsClient/zeta_download_manager/**` with adapter helpers in `PacsClient/components/zeta_adapter.py`. Legacy download helpers in `home_ui.py` are marked deprecated.
- Socket comms go through `modules/network/socket_service.py` (singleton facade) and config via `modules/network/socket_config.py` + `config/socket_config.json`.  See `docs/architecture/network-architecture.md`.
- Download-path socket client lives in `modules/download_manager/network/socket_client.py` (SocketDicomClient) with health monitoring in `health_monitor.py`.
- gRPC client is `modules/network/grpc_client.py` — used only for thumbnails; has auto-reconnect via `_ensure_stub()`.

## Critical rules (learned the hard way)

### v2.3.6 stack-drag smoothness rules (DO NOT REGRESS — see `docs/plans/STACK_DRAG_PLAYBOOK_v2.3.6.md`)
- **R1 — Surrogate-staleness break must stay** (v2.3.6 / GC#5). `Lightweight2DPipeline._try_surrogate_frame()` tracks `_last_surrogate_pixel_idx` + `_surrogate_repeat_count`. When the same `nearest_idx` would be served for the 3rd consecutive different target, return `None` → caller does one synchronous decode (15–45 ms) so the user sees CORRECT pixels. Both the cached-frame path and cached-pixel path apply this policy. Reset counters in `begin_protected_drag_session()`. Frame path skips the check when `nearest_idx == idx` (exact hit). Do NOT remove, do NOT make unconditional, do NOT change threshold from `>= 2` to `>= 1`. Log 95 = frozen image; log 96 = smooth.
- **R2 — `record_protected_drag()` is a real latch with keepalive** (v2.3.5 / GC#2). Not a ternary. `_PROTECTED_DRAG_ACTIVE` boolean + `_PROTECTED_DRAG_UNTIL_MS` deadline. `keepalive_protected_drag(1500)` MUST be called from `qt_slice_viewer.mouseMoveEvent` during active drag. Begin grace = 1500 ms; end tail grace = 250 ms. Do NOT reduce begin grace below 1000 ms — drags on low-config PCs last 3–10 s.
- **R3 — PREFETCH + CACHE_WARM both denied during protected drag** (v2.3.5). `ui_throttle.should_admit()` blocks BOTH work classes. Pipeline-local `_prefetch_around()` still admits its tiny-directional-P1 lane via its own P1 check. Do NOT clamp `cap_prefetch_radius()=0` at the ui_throttle level during drag — that killed cache growth in log 94 and caused stuck-on-surrogate.
- **R4 — Progressive grow defers non-terminal during drag, terminal always fires** (v2.3.5). `should_defer_progressive_grow(terminal=False)` returns `True` during drag. Grow interval during drag = 1500 ms (matches keepalive). Terminal completion is never deferred — user must see download complete.
- **R5 — DM `_apply_throttled_progress` SKIPS apply during drag** (v2.3.5 / GC#4). Not a slowdown from 100→750 ms — full skip. Timer stays armed at 1500 ms; `_pending_progress` accumulates; drains after drag. Each tick would otherwise cascade 4–5 main-thread slots (`studyProgressUpdated → on_series_progress → _flush_progress → series_images_progress.emit → on_series_images_progress`) at ~10 Hz = 40–50 slot invocations/sec competing with mouse events.
- **R6 — GC disabled during stack drag** (v2.3.5 / GC#4). `_begin_stack_drag_session()` calls `gc.disable()` + sets `_gc_suppressed_drag=True`. `_end_stack_drag_session()` restarts `QTimer.singleShot(1500, _reenable_gc_after_drag)`. `_reenable_gc_after_drag()` wraps `gc.enable()` in try/except. Mirrors the wheel-scroll pattern. Eliminates 100–500 ms gen-2 GC pauses.
- **R7 — Async logging via QueueHandler/QueueListener** (v2.3.5 / GC#1). File handlers behind `queue.Queue(-1)` + daemon listener thread. Console stays sync (stderr is cheap). Filters/formatters attached to real file handlers (run on listener thread). Escape hatch: `AIPACS_LOG_SYNC=1`. Shutdown: `shutdown_diagnostic_logging()` from `main.py` finally block + atexit hook. Without this, 50+ `logger.info()` per drag = 50–150 ms ui_lag/cycle.
- **R8 — `AIPACS_PRIORITY` Windows priority boost (opt-in default)** (v2.3.6). `main.py` calls `SetPriorityClass(ABOVE_NORMAL_PRIORITY_CLASS)` after `QApplication()`. Env override: `AIPACS_PRIORITY=normal|above_normal|high`. Logs `[CPU_BUDGET]` banner. Do NOT set HIGH by default — it starves the download subprocess.
- **R9 — `AIPACS_DECODE_WORKERS` default is 1, capped at 4** (v2.3.6). `decode_service._resolve_decode_workers()` reads env. More workers = more IPC contention on low-core PCs, not faster decode. Single worker + disk pixel cache is the happy path.
- **R10 — KPI regression alarm thresholds** (v2.3.6). `background_decode_count > 0` → R3 broken. `prefetch_per_s = 0 AND ui_lag_max > 500 ms` → R2 broken. `event_p50 > 150 ms` on multi-second drag → R5 broken. `ui_lag` steady-state > 500 ms → R6 broken. "Scrollbar moves but image frozen" user report → R1 broken. See `docs/plans/CURRENT_KPIS_v2.3.6.md`.
- **R11 — Startup refit signature dedup** (v2.3.7). `_vw_series._sync_qt_viewer_presentation(refit_view=True)` caches the `(host_width, host_height)` signature in `self._last_refit_signature` after a successful `zoom_to_fit()`. Subsequent refits with the identical host size are skipped at debug level (`[QT_PRESENTATION] zoom_to_fit skipped (dedupe)`). `_queue_qt_startup_refit` resets the signature to `None` so the first refit in each burst always runs. Do NOT remove the reset — without it the first delayed refit dedupes against the initial-sync refit from `_start_qt_viewer` and never fires. Log 96 showed 4 identical `scale=324.64` calls; log 97 verified the dedup produces 1 actual + 3 skipped.
- **R12 — P1-neighbor prefetch admitted during protected drag** (v2.3.7). `ui_throttle.should_admit(WorkClass.PREFETCH, ctx)` during protected drag now reads `ctx.get("priority", 999)` and admits only when `priority <= 1` (`FastWorkPriority.P1_NEIGHBOR`). `CACHE_WARM` remains unconditionally denied (R3 intact). `Lightweight2DPipeline._prefetch_around`'s `protected_drag and direction != 0` branch is the only caller passing `priority=P1_NEIGHBOR`. `qt_viewer_bridge.py` now invokes `pipeline._prefetch_around(new_val, direction=decision.direction)` right after `begin_stack_drag_target()` — before this the scheduler's work_items went through `NoopObjectCache` and the P1 lane was permanently dark. Default priority (999) in the ctx means legacy callers without explicit priority are still denied → no bypass of R3.
- **R13 — Download subprocess IDLE-priority during protected drag (DISABLED by default; opt-in)** (v2.3.7). Originally shipped as default-on in v2.3.7, **reverted to opt-in after log 99** showed a ui_lag regression (229 ms → 412 ms peak) under comparable load. Root cause: dropping the subprocess to IDLE while it holds the `multiprocessing.Queue` IPC mutex caused priority inversion — the viewer (ABOVE_NORMAL) blocked waiting on a lock held by an IDLE-scheduled thread. Diagnostic signature: `event_p95` up to 376 ms while `handler_p95` stayed ~15 ms (event loop stalled, not handler work). Infrastructure kept behind `AIPACS_DRAG_SUBPROC_THROTTLE=1` (explicit opt-in, default `0`). When enabled: viewer touches `{user_data}/cache/.drag_active` on `record_protected_drag(True)` / every `keepalive_protected_drag()` (rate-limited to 200 ms); subprocess daemon poller (`aipacs-sp-drag-priority`, 150 ms cadence) flips priority between IDLE (flag fresh <2000 ms) and BELOW_NORMAL (flag stale). Poller lives in `modules/download_manager/workers/download_process_entry.py` (ACTIVE subprocess entry); **dead copy in `workers/download_subprocess.py` is legacy — do NOT edit there**. `[SP]` log lines require `extra={"component": "ipc"}` — without it, `_infer_component` classifies the logger as `download` which has WARNING threshold and drops INFO messages. BELOW_NORMAL (applied unconditionally at subprocess start) is sufficient for viewer separation under normal load. Do NOT re-enable R13 by default without first solving the IPC queue priority-inversion problem (e.g. switching progress IPC to a lock-free channel, or using `PROCESS_MODE_BACKGROUND_BEGIN` which lowers I/O priority without starving mutex-holding threads).
- **R14 — `_last_surrogate_pixel_idx` must be read via `getattr` in surrogate hot-path** (v2.3.7). Both branches of `_try_surrogate_frame` (cached-frame path and cached-pixel path) use `getattr(self, '_last_surrogate_pixel_idx', -1)` / `getattr(self, '_surrogate_repeat_count', 0)` to tolerate test stubs that bypass `__init__`. Real instances initialize these fields in `__init__` and reset them in `begin_protected_drag_session`. Do NOT replace with bare attribute access — it breaks 17 pipeline tests.
- **R16 — `vtkImageViewer2.FirstRender` MUST be consumed via `self.Render()` BEFORE applying the final ParallelScale** (v2.3.8). `vtkImageViewer2` (base of `vtkResliceImageViewer` / `ImageViewer2D`) sets an internal `FirstRender=1` one-shot whenever `SetInputData()` is called. The next call to `vtkImageViewer2::Render()` (the override) runs `InitializeRendererFromImage()` → `renderer.ResetCamera()`, which **wipes any custom `ParallelScale`** with `(dims-1)/2`-style values (e.g. 255.5 / 319.5 / 383.5). Calling `self.image_render_window.Render()` directly bypasses the override, so `FirstRender` stays `1` and the next pipeline `self.Render()` (e.g. on first `_set_slice_impl`) silently overwrites the scale on first scroll/series-display. **Canonical fix**: in both `ImageViewer2D.__init__` and `reset_image_viewer` (`modules/viewer/advanced/viewer_2d.py`), call `self.Render()` (Phase 1) BEFORE `zoom_to_fit()` / `SetParallelScale()` (Phase 2). The Phase 1 render consumes the one-shot on a throwaway state; the Phase 2 scale then sticks. Do NOT add reactive "if zoom changed → revert to ref_scale" guards in scroll/wheel mixins (`_vw_scroll.py`, `_legacy_widget.py`) — those are band-aids that hide this root cause and were removed in v2.3.8. The plugin-package copy at `builder/plugin package/packages/viewer/payload/python/modules/viewer/advanced/viewer_2d.py` MUST be kept in sync (per "Builder copies override modules/" rule) or production builds will regress. Diagnostic signature of regression: `[CAMERA INIT]` log shows correct scale (e.g. 188.56), then within 6–10 ms a different scale appears matching `(dims_y - 1) / 2` of the loaded image. Applies to both stack mode and series-switch in Advanced/VTK viewer; FAST (`QtViewerBridge`) path is architecturally unaffected.
- **R17 — FAST pipeline MUST force `preserve_dimensions=True` when invoking the PooyanPacs OpenCV filter, AND `_numpy_to_qimage_gray/rgb` MUST derive width/height/bytesPerLine from `arr.shape` — not from caller-supplied dims** (v2.3.8). Root cause of "two brains overlapping with scan-lines on stationary viewer, correct on stacking viewer" artifact: `pooyan_filter_center` with `preserve_dimensions=False` + `small_threshold=280` enlarges images narrower than 280 px by 2× on both axes (e.g. 256×184 → 512×368) — this is documented C# PooyanPacs behavior for a display backbuffer that does not exist in the FAST Qt path. `Lightweight2DPipeline._render_frame_uncached` then fed this enlarged buffer to `_numpy_to_qimage_gray(disp, sm.cols, sm.rows)` using the ORIGINAL `sm.cols=184, sm.rows=256`. QImage interpreted 184 as both image width and `bytesPerLine`, reading a 368-byte-wide array as if each row were 184 bytes → exactly the wrapped/doubled/scan-line pattern. Why stacking appeared normal: `filter_enabled = opencv_filter_enabled AND (NOT fast_interaction OR interaction_type=='wheel')` — during stack-drag `filter_enabled=False`, so the filter was skipped and dimensions remained (256, 184). On release, the settled re-render applied the filter and produced the corrupted output. **Canonical fix**: (1) force `preserve_dimensions=True` at the FAST call site in `modules/viewer/fast/lightweight_2d_pipeline.py::_render_frame_uncached` — the 2× enlargement is redundant in the FAST path because `QGraphicsView` handles display scaling natively; (2) make `_numpy_to_qimage_gray` derive `actual_w, actual_h = arr.shape[:2]` and use those for BOTH image dimensions AND `bytesPerLine`, logging an error if the caller's supplied dims disagree (defense-in-depth for any future dimension-changing filter); (3) set `"preserve_dimensions": true` in `config/pooyan_opencv_filter.json` so config-sourced default agrees. The plugin-package copy at `builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/lightweight_2d_pipeline.py` MUST be kept in sync or production builds regress. Advanced (VTK) path is unaffected — it handles filter-induced dimension changes through `_preprocess_vtk_image_data`'s `vtkImageResample`. Do NOT add new callers that pass hard-coded `sm.cols/sm.rows` to the QImage helpers; always pass `disp.shape[1]/disp.shape[0]` if you must pass anything. Do NOT relax `preserve_dimensions` back to `False` at the FAST call site. Diagnostic signature of regression: image looks correct while stacking/wheel-scrolling but becomes "wrapped / two-brains / horizontal scan-lines" on release for any series with width OR height < 280 px (common for MR).\n- **R18 — Prefetch pre-queue cancellation gates AND direction-flip target invalidation** (v2.4.7 / plan F3.1+F3.2). `Lightweight2DPipeline._submit_prefetch(idx, generation, request_epoch=0)` rejects stale tasks BEFORE `executor.submit()` (saves IPC + pickle + worker-dispatch cost) using three gates evaluated under `_prefetch_lock`: (1) **generation gate** — `generation > 0 and generation != self._prefetch_generation` rejects (W/L change or series close already bumped generation); (2) **request-epoch gate** — `request_epoch > 0 and request_epoch != self._prefetch_request_epoch and idx not in self._active_prefetch_targets` rejects (neighborhood replaced; only admit if idx is still in the latest active target set, which preserves overlap-prefetch when scroll continues in the same direction); (3) **distance gate** — `abs(idx - self._current_index) > _max_distance` rejects, where `_max_distance = 6` during `_fast_interaction` and `_config.prefetch_radius` otherwise. Each rejection increments `PerfMetrics.cancelled_task`. F3.2 layers on top: `_prefetch_around` tracks `self._last_prefetch_direction` (set on every `direction != 0` call) and forces `_prefetch_request_epoch += 1 + _active_prefetch_targets = uncached_targets` when the new direction differs from the last non-zero one — even if the new neighborhood overlaps the old. This guarantees that when the user reverses scroll direction mid-drag, every queued task in the OLD direction fails gate (2) and gets cancelled pre-queue. `_last_prefetch_direction` is reset to 0 in `close_series`, `begin_protected_drag_session`, and the W/L-change path (mirroring `_last_prefetch_center` resets). Post-decode guards in `_decode_into_cache` remain intact as a safety net but should be reached only by tasks that started before the gate was evaluable. Do NOT remove the pre-queue gates — they are the difference between cancelled-task-ratio ≈10% (post-decode only) and ≈50%+ (pre-queue + post-decode). Do NOT update `_last_prefetch_direction` on `direction == 0` calls (idle/centering prefetch) — that would silently overwrite the tracked direction and make legitimate same-direction continuation look like a flip. The plugin-package copy at `builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/lightweight_2d_pipeline.py` MUST be kept in sync. Tests: `tests/viewer/test_prefetch_pre_queue_cancel.py` (9, F3.1) + `tests/viewer/test_b34_interaction_aware_policy.py::TestDirectionReversal` (4, F3.2).\n- **R15 — Advanced (VTK) viewer participates in the unified protected-interaction latch** (v2.3.8). `modules/viewer/fast/ui_throttle.py` now exposes `record_advanced_protected_interaction(active, *, grace_ms, source)` writing a parallel `_ADVANCED_PROTECTED_*` state. `is_protected_drag_active()` returns `True` if EITHER the FAST latch (`_PROTECTED_DRAG_*`) OR the Advanced latch (`_ADVANCED_PROTECTED_*`) is active/within its grace window. The Advanced viewer calls this from exactly two sites in `vtk_widget/_vw_scroll.py`: (1) `_flush_pending_wheel_slice_impl` after the `_in_wheel_scroll`/`_in_stack_scroll` flags are set → `(True, grace_ms=2500.0)` acting as begin + per-frame keepalive (2500 ms covers the 2000 ms `_gc_reenable_timer` + margin), and (2) `_reenable_gc_impl` at the end-of-burst path → `(False, grace_ms=250.0)` with a tail grace mirroring FAST's `record_protected_drag`. The end-of-burst call runs **outside** the `self._gc_suppressed` guard because stack-drag bursts start the GC re-enable timer without flipping `_gc_suppressed`. Because R3 (CACHE_WARM denial, PREFETCH denial unless priority≤1), R4 (progressive grow defer — architecturally no-op in Advanced; docstring states Advanced progressive is unreachable in production), and R5 (DM `_apply_throttled_progress` skip) all gate on `is_protected_drag_active()`, the read sites require zero changes — extension is automatic. The latches are kept **separate** (not unified into one flag) so `[PROTECTED_DRAG]` vs `[PROTECTED_ADVANCED]` log lines remain distinguishable for diagnostics. R13 cross-process `.drag_active` flag is touched on every Advanced `active=True` call, so when `AIPACS_DRAG_SUBPROC_THROTTLE=1` is enabled, Advanced drags throttle the download subprocess identically to FAST drags. Do NOT add a second Advanced release call in the wheel-coalesce `finally:` block — the `_gc_reenable_timer` is the single source of truth for "burst tail", and adding a synchronous release there would defeat the 250 ms tail grace. Do NOT consolidate the FAST and Advanced latches into one variable — separate state is required for the `[PROTECTED_*]` log disambiguation and for independent `reset_ui_tick_baseline()` semantics. Verify with `tests/viewer/test_advanced_protected_interaction.py` (7 tests).

### Legacy rules (still current)
- **Do NOT re-sort metadata['instances'] by IPP.** VTK slices are in instance_number order (files are `Instance_NNNN.dcm` loaded via `natsort`). Metadata from DB is already in the correct order. Re-sorting by IPP broke reference lines in v1.09.5-v1.09.7.
- **The stored DirectionMatrix in field data has row 1 negated** (Y-flip compensation from `convert_itk2vtk`). Do not use it directly for DICOM normal comparisons without un-negating row 1 first.
- **Scroll fast-path (`_in_wheel_scroll` flag):** During wheelEvent-driven scroll, `set_slice()` skips camera zoom save/restore, interactor style update, and throttles Lock Sync to 100ms.  Do NOT add expensive per-frame operations inside `set_slice()` without guarding them with `if not _wheel:`. See v2.2.3.4.0.
- **DL_WARMUP subprocess runs at IDLE priority** (v2.2.3.4.0). It has its own GIL. Do not bump priority above IDLE — it causes memory-bus contention that spikes the viewer's SetSlice from 8→45ms.
- **GC is suppressed during scroll bursts** (`gc.disable()` in wheelEvent, re-enabled 2000ms after last render). Do not call `gc.collect()` during scroll. See v2.2.3.3.2.
- **Reference line repaint during scroll uses round-robin** (v2.2.3.3.7): trailing-edge timer paints ONE target viewer per tick. Do not change to paint-all-targets per tick — it blocks the event loop N×20ms.
- **Local backup of this stable version:** `backups/v2.3.6_2026-04-20/` (and prior `backups/v2.3.5_2026-04-19/`)
- **F1 overlap pixel-quality gate (F1.3 — 2026-04-28).** Any change to `modules/viewer/fast/lightweight_2d_pipeline.py`, `qt_viewer_bridge.py`, `qt_slice_viewer.py`, or their plugin-package mirrors at `builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/*` REQUIRES the overlap regression bundle green BEFORE commit/push: `.\tools\dev\run_overlap_regression.ps1` (settled hash gate + drag-mode hash gate + KPI parser + harness; ~12s, 25 tests). Settled goldens live in `tests/viewer/golden/overlap_pixel_*.json` and are byte-deterministic across runs. Re-capture only with `-Capture` flag and a deliberate human review of the JSON diff — a hash change is by definition a user-visible image change. Drag-mode test reuses the settled goldens (validity + ±10 surrogate proximity + settle exactness contracts) — no separate goldens. Plan reference: `plan-fastViewerOverlap100PercentImprovement.prompt.prompt.md` F1.
- **F2.1 `[OVERLAP_SCENARIO]` runtime log tag (2026-04-28).** `Lightweight2DPipeline.get_rendered_frame` emits a structured INFO line `[OVERLAP_SCENARIO] frame idx=<i> cache=<hit|surrogate|decode> decode_ms=<f> wl_ms=<f> total_ms=<f> settled=<True|False>` at all three return paths, sampled 1-in-N (default 5, env `AIPACS_OVERLAP_LOG_SAMPLE`) when `is_heavy_download_active() AND not is_viewed_series_complete(self._series_number)`. The harness `parse_overlap_log_text` (in `tools/performance/clearcanvas_aipacs_kpi_harness.py`) consumes it. Format must stay stable: contract test `tests/performance/test_overlap_kpi_parser.py::test_parse_overlap_log_text_matches_production_emit_format` round-trips the exact emit shape including the `diagnostic_logging` prefix. Do NOT remove the per-call counter or move the call sites outside the three return paths — KPI distribution accuracy depends on covering all of (hit / surrogate / decode). Mirror to plugin package copy when modifying. Plan reference: F2.1.
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
- **`servers.json` uses `CONFIG_DIR` absolute path** (v2.4.2-patch2). `_AIPACS_SERVERS_FILE = CONFIG_DIR / "servers.json"` in `PacsClient/utils/utils.py`. In frozen mode `CONFIG_DIR = roaming_config_root()` = `%APPDATA%\AIPacs\config\`. `get_all_servers()`, `get_server()`, and `ServerSettingsWidget.save_to_json()` all use `_AIPACS_SERVERS_FILE`. `config/servers.json` (empty `[]`) is the bundled default seeded to `%APPDATA%\AIPacs\config\servers.json` by `seed_user_config_defaults()` on first launch. Do NOT use a relative `'servers.json'` path — it only resolves correctly when CWD is the project root (dev only). Do NOT remove the `mkdir(parents=True, exist_ok=True)` call in `save_to_json` — it ensures the config dir exists on a fresh install before the first write.
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
- **B3.7: Cache-first fast scroll — nearest-cached surrogate** (v2.3.3-perf; overlap tuning 2026-04-16). During `fast_interaction=True`, if `pixel_cache` has no entry for the requested slice, `get_rendered_frame` searches for the **nearest cached pixel** within ±10 slices and renders that as a surrogate (~2ms W/L only, 0ms decode). During active heavy-download overlap on an **incomplete viewed series**, drag navigation may widen that search window to **±20** so sparse-cache regions still avoid foreground decode. Separately, **very fast drag** may also widen to **±20** even for completed viewed series so transient cache gaps do not fall back to a 15–20ms foreground decode spike. The actual target slice is prefetched in the background. This converts 100% foreground decode (17-45ms each) to 0ms decode during fast scroll. The surrogate frame reports `decode_ms=0.0` and `slice_index=requested_idx` (not the surrogate's index). If no cached pixel exists within the active window, falls through to synchronous decode (first frame of a new region). On scroll stop, `end_fast_interaction()` → `rerender_current_filtered()` renders the exact final slice. Do NOT remove the `_find_nearest_cached_pixel` call or revert to unconditional synchronous decode during fast interaction — it was the root cause of 20-45ms per-frame latency and 220% CPU during stack drag.
- **B3.7 follow-up: nearest cached rendered-frame reuse** (2026-04-16). During drag navigation, `get_rendered_frame` now probes `_frame_cache` for a nearby exact-W/L rendered frame before calling `_render_frame_uncached()` on a nearby cached pixel. This removes a remaining 10–16ms UI-thread W/L conversion spike on some fast-drag surrogate frames. Preserve the order: cached frame first, cached pixel second, synchronous exact decode last. If a cached-frame surrogate is used while the exact target pixel is already cached, queue `_submit_frame_prefetch(idx)` so the exact frame fills in the background.
- **Exact filtered frame cache outranks exact unfiltered cache during fast interaction** (2026-04-17). When `opencv_filter_enabled` is on and an exact filtered frame for the requested slice/WL already exists in `_frame_cache`, `get_rendered_frame()` must reuse that filtered frame BEFORE falling back to the exact unfiltered cache entry. This keeps the scrolling image visually consistent with the settled image and avoids the subtle brightness/clarity pop reported in `log 52`. Do NOT restore the old order (unfiltered exact first) — it reintroduces a user-visible image-type change even when full-quality pixels are already cached.
- **B3.7: Prefetch radius during fast interaction raised from 1 to 3** (v2.3.3-perf, was 1 in B3.4). With foreground decode eliminated by nearest-cached surrogate, background workers have more CPU headroom. Radius 3 fills the cache 3 slices ahead in the scroll direction, reducing surrogate distance from ±6-10 to ±1-3. Do NOT reduce back to 1 — it increases surrogate distance and makes the visual approximation more noticeable.
- **B3.8a: Per-frame scroll metrics** (v2.3.3-perf). `qt_viewer_bridge.py` `set_slice()` logs `[B3.8_SCROLL]` every 20th frame during fast interaction with: frame#, slice, total_ms, decode_ms, wl_ms, cache source (hit/surrogate/decode), pixel_cache size, frame_cache size. `_scroll_frame_count` resets on non-fast-interaction calls. Do NOT remove — this is the primary production KPI measurement hook for scroll performance.
- **B3.8b: Layer 2b FAST viewer matching** (v2.3.3-perf). `_on_series_download_fully_complete_impl` uses 3-tier grow priority matching `_grow_progressive_fast`: (1) `_lazy_loader.grow()`, (2) `backend.refresh_file_list()`, (3) `vtk_w._qt_bridge_active → bridge.grow()`. Do NOT remove tiers 2 and 3 — they are the ONLY path for FAST/pydicom_qt viewers. Without them, Layer 2b final grow silently fails → viewer shows fewer slices than downloaded.
- **B3.8c: Post-completion cache warm** (v2.3.3-perf). After `_grow_progressive_fast` step 6 detects series COMPLETE, triggers `pipeline._prefetch_around(current_slice, direction=0)` with `_last_prefetch_center = -1` reset. This fills pixel_cache bidirectionally with full radius around the current position. Do NOT remove — without it, first scroll after download completion hits 17-45ms foreground decode for non-cached slices.
- **B3.8d: Duplicate Layer 2b call guard** (v2.3.3-perf). `_layer2b_complete_guard` set in `_on_series_download_fully_complete_impl` prevents double execution. Guard cleared at all 3 lifecycle cleanup points: Layer 2b (`all_viewers_complete`), Layer 3 (`_completion_verify_series_impl`), Layer 4 (`_completion_sweep_tick_impl`). Do NOT remove guard or any cleanup site — removing guard causes 2× expensive file scanning; removing cleanup causes stale entries blocking future downloads of the same series number.
- **B3.12: Disk pixel cache** (v2.3.3-perf). `modules/viewer/fast/disk_pixel_cache.py` provides L2 persistent cache for decoded pixel arrays. `Lightweight2DPipeline._decode_slice()` checks disk cache BEFORE `pydicom.dcmread` and stores decoded result AFTER successful decode. Cache uses custom binary format `.apc` (14-byte header: `APDC` magic + version + dtype_code + rows + cols + raw array bytes). Key is `sha256(sop_instance_uid)[:16]`. Location: `{USER_DATA_ROOT}/cache/pixel_cache/{study_hash}/{key}.apc`. Default 2 GB LRU eviction. Writes are async fire-and-forget on daemon threads with atomic tmp→rename. Do NOT remove the disk cache get() call at the top of `_decode_slice` — it provides 11.5× speedup (0.43ms vs 4.88ms) for series re-opens. Do NOT remove the disk cache put() calls at the 3 return paths — without them, the cache is never populated. Do NOT call `disk_cache.put()` inside a lock or semaphore — it spawns a background thread. The `put()` method copies the array (`arr.copy()`) before handing to the background thread — safe even if caller mutates the original.
- **B3.11: Decode service** (v2.3.3-perf). `modules/viewer/fast/decode_service.py` provides subprocess-based DICOM decode for GIL isolation. `Lightweight2DPipeline._decode_into_cache()` tries the subprocess service FIRST for background prefetch (disk cache check → subprocess decode → fallback to in-process). Foreground decode (`_decode_slice` → `_get_pixel_array`) stays in-process for lowest latency. Service uses `ProcessPoolExecutor(1, spawn)` with `max_tasks_per_child=200`. IPC overhead is ~2.4ms (26%) per 512×512 slice. Toggle: `AIPACS_DECODE_SERVICE=0` env var disables. Auto-disables when failure rate >50%. `shutdown_decode_service()` called from `main.py` finally block. Do NOT route foreground (main-thread) cache misses through the service — pickle round-trip adds 2.4ms that the user perceives directly. Do NOT remove the in-process fallback — it is the safety net when the service is disabled, broken, or starting up.
- **Progressive grow timer default is 150ms** (v2.2.8.1, was 500ms). `_progressive_grow_timer.setInterval(150)` remains the default idle cadence. In protected UI, non-terminal grow retry now intentionally backs off to **500ms** during active download and **750ms** during active download + fast interaction so deferred viewer admission does not keep waking the control plane every 150ms. Terminal completion remains immediate/uncapped. Do NOT remove the protected-mode backoff or apply it to terminal completion.
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
- **B4.3 incremental cleanup helper** (v2.3.4-perf). Layer 2b/3/4 lifecycle-close paths now use a single shared cleanup helper (`_cleanup_progressive_lifecycle_state(obj, sn, source)`) to perform the required triple cleanup atomically: `_progressive_series.pop(sn, None)` + `done.discard(sn)` + `_layer2b_complete_guard.discard(sn)`. Keep this helper as the canonical path — do NOT reintroduce copy-pasted cleanup blocks per layer.
- **B4.3 lifecycle state-map** (v2.3.4-perf). Progressive display now tracks explicit per-series state in `_progressive_lifecycle_state` with states: `NO_VIEWER → AWAITING → PROGRESSIVE → COMPLETING → DONE`. This state-map is additive (legacy guard sets still exist) and must be updated at major transitions (`on_series_images_progress`, `_start_progressive_display`, grow ticks, completion layers). Keep `_cleanup_progressive_lifecycle_state()` as the only Layer 2b/3/4 close path so `DONE` is written consistently.
- **B4.x terminal idempotence rule** (2026-04-15, implemented). For a given series and download epoch/job, terminal progressive actions are one-shot: duplicate late terminal progress must not recreate `_progressive_series`, re-fire one-shot grow, or re-open `AWAITING` after terminal completion has already been observed. The compatibility guard is cleared only by a verified new partial cycle after `DONE`. When changing `_on_series_images_progress`, `_grow_progressive_fast`, or completion cleanup, preserve this invariant.
- **B4.x single terminal authority** (2026-04-15, implemented). Progressive terminal close now routes through `_finalize_progressive_series(...)` guarded by `_progressive_finalized_series`. Layer 2b, Layer 3, Layer 4, and terminal grow completion must not each perform their own independent pop/exit/update sequence. Preserve restart-after-DONE semantics by clearing `_progressive_finalized_series` only for a verified new partial cycle.
- **Layer 2b/3/4 follow-up must not duplicate the shared finalizer** (2026-04-16, hardened). After `_finalize_progressive_series(...)` handles a terminal close, callers must NOT separately re-run terminal follow-up for the same cycle (`exit_progressive_mode`, corner/thumbnail refresh, or equivalent duplicate close/update work). Layer 2b may still do provisional grow/count work before finalization, but the shared finalizer is the only terminal-close owner once invoked.
- **B4.x load-controller shell** (2026-04-15, implemented). `modules/viewer/fast/system_load_controller.py` is now the shared policy front door for cadence/radius decisions. Existing throttles should go through `modules/viewer/fast/ui_throttle.py` wrappers instead of sprinkling direct `500ms`, `250ms`, or ad hoc overload checks across call sites.
- **B4.x progress fan-out gate** (2026-04-15, implemented). `HomeDownloadService` coalesces raw `seriesProgressUpdated` fan-out behind one admitted per-series progress gateway. Do NOT emit direct DM progress to multiple viewer-facing consumers from separate call sites — progressive display and thumbnail progress should ride the same admitted update.
- **B4.x cache-warm admission gate** (2026-04-17, implemented). Post-completion cache warm and warmup-lane entry points (`_dispatch_post_completion_cache_warm`, `_start_open_tab_warmup`, `_start_deferred_heavy_warmup`) must go through the shared `ui_throttle.should_admit(..., "cache_warm", ...)` front door with owner-scoped keys. Under protected UI, `CACHE_WARM` is now coalesced at **750ms** instead of free-running retry loops. Do NOT add direct `QTimer.singleShot` retry storms for warmup/cache-warm work outside the shared admission shell.
- **B4.x prefetch admission rule** (2026-04-15, implemented). `Lightweight2DPipeline._prefetch_around()` must route prefetch submission through `ui_throttle.should_admit(...)` / `SystemLoadController.should_admit(...)`. Do NOT bypass the shared admission shell with ad hoc prefetch bursts during overlap.
- **B4.x UI lag probe** (2026-04-15, implemented). The current `ui_event_loop_lag_ms` signal is a callback-gap estimate recorded from the Qt bridge interaction path, not a standalone timer heartbeat. Treat it as a conservative responsiveness signal for protected-mode policy, and keep docs truthful about that.
- **B4.x progressive viewer admission gate** (2026-04-16, implemented; tuned same day). Non-terminal progressive growth may know about more downloaded slices than the viewer should expose immediately. `_flush_progressive_grow_impl()` must admit viewer-visible slices in bounded steps via `_progressive_admit_batch_size`, while terminal completion remains uncapped. Default admission batch is now **8** (was effectively **10** by inheriting `_progressive_grow_batch_size`) because the one-knob storm sweep on series `202` reduced overlap `set_slice_present_p95_ms`/max, kept >16ms slow frames at zero, and beat both **5** and **12** on the combined balance score. Do NOT apply this gate to the direct stack/wheel interaction path, and do NOT remove the terminal uncapped behavior — the design is “gate background viewer admission, not user interaction.”
- **Progressive slider range stays at total expected slices** (2026-04-17). `_update_vtk_slice_range()` must keep the slider maximum anchored to `_total_expected_slices` while progressive mode is active; only `update_available_slice_count()` / `_is_slice_available()` may limit what can actually be rendered. Do NOT shrink the slider max to the admitted/downloaded count (e.g. `20 → 40 → ...`) — that creates visible UI churn and extra slider work while the total series size is already known.
- **B4.x progressive viewer admission cadence** (2026-04-16, implemented). The count gate alone is not sufficient under protected UI: when non-terminal grow is deferred, retry cadence must also slow down so the viewer does not poll the admission path every 150ms while download/scroll overlap is active. Protected retry cadence is now **500ms** during active download and **750ms** during active download + fast interaction. Do NOT revert the retry cadence to unconditional 150ms during protected UI — that recreates control-plane wakeup storm without improving visible smoothness.
- **B4.x-i9 workstation hygiene** (2026-04-17, implemented). HomeDownloadService has `cleanup()`/`disconnect_widget()` with `_ConnectionRecord`-based per-widget signal teardown. Tab close (`_hp_patient_open.py` `close_tab()`) wires `disconnect_widget` before `deleteLater`. `ui_throttle.py` has an orchestrator bridge: `set_active_orchestrator()`/`clear_active_orchestrator()` registered by ViewerController on init and cleared in `cleanup_all_viewers()`. `is_heavy_download_active()` probes both ZetaBoost globals AND PipelineOrchestrator. Do NOT query download activity directly — go through `ui_throttle.is_heavy_download_active()`. Do NOT add top-level imports of PatientWidget/AiMainWindow in home_ui (lazy-loaded per v2.2.8.0 rule).
- **Epoch-aware Layer 3 completion verify** (v2.3.4-cp1). `_completion_verify_series_impl` checks `_is_series_download_completed(sn)` before transitioning DONE→COMPLETING. If the series is truly complete AND the viewer's slice count matches the cached disk count, the verify is a no-op. This eliminates spurious DONE→COMPLETING→DONE churn that added 25-40ms set_slice spikes during overlap. Do NOT remove the epoch check — it was the root cause of log-38 re-entry storms.
- **Series-level prefetch readiness** (v2.3.4-cp1). `ui_throttle.is_viewed_series_complete(sn)` queries `PipelineOrchestrator.is_series_downloaded(sn)`. `cap_prefetch_radius(series_number=sn)` and `_compute_adaptive_radius()` in `Lightweight2DPipeline` use this to clear the `heavy_download_active` override for completed series — a viewed series gets full prefetch radius even while other series are still downloading. Do NOT remove the series-number parameter from `cap_prefetch_radius` — without it, completed series are starved of prefetch during study download.
- **Progressive display completeness gate** (v2.3.4-cp1). `_start_progressive_display` defers when `downloaded/total < 0.30` AND `target_vtk_widget is None` AND `is_heavy_download_active()`. The next progress signal retries. This prevents 500ms+ `load_single_series_by_number` during heavy download overlap. Do NOT lower `_PROGRESSIVE_MIN_COMPLETENESS` below 0.20 — it causes repeated failed load attempts that spike CPU.
- **Untargeted progressive is manual-only for layout insertion** (2026-04-20). `_start_progressive_display`, `on_series_images_progress`, `load_series_on_demand`, and post-open local-series checks must NOT auto-place a series into any viewer when `target_vtk_widget is None`. Background/download/local discovery stays in Block A (thumbnail/loading lane) until a viewer explicitly requests the series (`_awaiting_series_number` or equivalent viewer interest). Do NOT restore the old “first visible image” auto-start for untargeted series — it creates competing flows during download and hurts responsiveness.
- **Untargeted progressive defer is sticky until an explicit viewer request exists** (2026-04-20). Once an untargeted background series is deferred, `on_series_images_progress` must NOT keep re-entering `_start_progressive_display` on every later progress pulse just because the layout is empty or the first series has not yet been shown. Keep the series in `_progressive_untargeted_defer` until a viewer explicitly awaits it or is already showing it. Do NOT weaken this guard-set — it reintroduces auto-placement churn and duplicate startup work.
- **Local first-series discovery is thumbnail-only on patient open** (2026-04-20). `_check_and_load_local_first_series()` and tab-activation recovery paths may discover local DICOM series and log availability, but they must NOT emit `series_downloaded` or otherwise route the first local series into a viewer automatically. The user chooses when to place a local series into Block B/layouts. Do NOT re-add automatic first-series insertion on open/activate — it recreates the dual-flow performance regression.
- **Thumbnail progress updates must be property-idempotent** (2026-04-16, implemented). `ThumbnailManager.update_series_progress`, `start_series_download`, and `complete_series_download` now skip `setVisible`, `setText`, and progress-border state setters when the widget already has the requested state. Preserve these no-op guards — repeatedly writing the same overlay/border/count-label state during overlap adds sidebar/layout churn with no visible benefit.
- **Thumbnail projection contract is start/total/complete only** (2026-04-16, implemented). `HomeDownloadService` remains the canonical viewer-facing per-series progress stream, but thumbnail projection must stay simpler: `ThumbnailManager.start_series_download()` remembers the stable total count, active state shows `N images`, and `complete_series_download()` finalizes as `N/N`. `_hp_priority.py` must NOT inject direct thumbnail per-progress updates during priority flows — use projection-style start/complete only. Preserve idempotence on repeated start/complete calls.
- **Harsher mixed-load PREFETCH policy** (v2.3.4-cp1). During `heavy_download + fast_interaction`, prefetch radius cap is 1 (was 3). During `heavy_download` alone, stays at 3. This reduces background decode CPU contention during simultaneous scroll+download. Do NOT increase the radius back to 3 during the combined condition — it was the root cause of 149% CPU spikes in log-38.
- **Harsher mixed-load PROGRESSIVE_SIGNAL coalesce** (v2.3.4-cp1). During `heavy_download + fast_interaction`, coalesce interval is 750ms (was 500ms). During `heavy_download` alone, stays at 500ms. Prevents progressive grow from competing with scroll for CPU time. Do NOT reduce below 500ms during combined condition.
- **ZetaBoost RAM cache is architecturally empty in FAST mode** (v2.3.4-cp1). In FAST/pydicom_qt mode, `Lightweight2DPipeline` decodes directly from DICOM files — no VTK `put()` runs. `set_study_download_complete(True)` still fires for correctness (Advanced mode uses it), but warmup lanes find zero work. The `entries=0 bytes=0.0MB` log at study completion is expected, not a bug.
- **Two PipelineOrchestrator classes exist** (2026-04-17). `modules.module_system.pipeline_orchestrator.PipelineOrchestrator` is the module-system multi-pipeline cache manager (unused in active code, re-exported from `PacsClient/components/__init__.py` for archived docs). `modules.viewer.pipeline.orchestrator.PipelineOrchestrator` is the viewer download→warmup FSM (used by _vc_load.py, _vc_cache.py, patient_widget_viewer_controller.py). Do NOT confuse them.
- **Socket routing** (2026-04-17). Patient list / report metadata → `modules/network/socket_client.py` (PatientListSocketClient). DICOM batch downloads → `modules/download_manager/network/socket_client.py` (SocketDicomClient). `SocketService` (modules/network/socket_service.py) is a convenience singleton wrapping SocketDicomClient for ad-hoc DICOM ops — NOT used by the Download Manager hot path.
- **Global `sys.excepthook` captures crash tracebacks** (v2.2.9.3 — H5a). `main.py` installs `_aipacs_excepthook` after `configure_diagnostic_logging()`. It logs the FULL Python traceback to `aipacs.crash` logger at CRITICAL level BEFORE Qt intercepts the exception with the generic "Qt has caught an exception" message. Without this, the throwing file/line is permanently lost. Chains to the original hook. Do NOT remove this — it is the primary diagnostic tool for all Qt boundary crashes.
- **QTimer callback slots MUST use wrapper+impl guard pattern** (v2.2.9.3 — H5b/H5c). Direct `QTimer.timeout` slots (`_reenable_gc`, `_flush_pending_wheel_slice`) are Qt event handler entry points. If any exception propagates through them, Qt catches it with the fatal "Qt has caught an exception" message and the Python traceback is lost (even with `sys.excepthook`, the exception may not reach it in all Qt versions). The wrapper+impl pattern (`_reenable_gc` → `_reenable_gc_impl`, `_flush_pending_wheel_slice` → `_flush_pending_wheel_slice_impl`) ensures exceptions are caught, logged with `exc_info=True`, and suppressed. Apply this pattern to ALL new QTimer.timeout slots and Qt signal slots that access VTK objects or cross-module state.
- **`_refresh_stored_metadata_instances` updates `series["image_count"]`** (v2.2.8.4). After `metadata["instances"] = new_instances`, also sets `metadata["series"]["image_count"] = len(new_instances)`. Do NOT update `instances` without updating `image_count` — the thumbnail widget reads `image_count` (server metadata), and without this fix it permanently shows the original server-reported count (e.g. 20 instead of 40).
- **`_refresh_stored_metadata_instances` TTL pre-check** (v2.2.8.4). Uses `_count_series_files_on_disk(sn)` (1s TTL cache) as a fast pre-check before the expensive `Path.iterdir()` scan. If TTL-cached disk count ≤ existing instance count, returns immediately without scanning. Do NOT remove this guard — it prevents 2–10ms of main-thread I/O on every 150ms grow tick with large series.
- **Viewport spinner hide delay is 180ms** (2026-04-20, was 50ms). `_SPINNER_HIDE_DELAY_MS` in `vtk_widget/_vw_globals.py` intentionally lingers a little after series switch/reset so the loading GIF is perceptible instead of flashing. Do NOT reduce it back to near-zero unless you re-measure the perceived UX impact.
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
- **`load_series_on_demand` skips redundant post-completion reloads** (2026-04-16). After `on_series_download_fully_complete(series_number)` performs the authoritative Layer 2b final grow, `load_series_on_demand` checks whether any viewer already shows that series at the current disk-count. If yes, it only marks the thumbnail ready and returns. Do NOT invalidate/reload a fully visible series again — it reintroduces same-series rebind churn and layout lag right after completion.
- **`load_series_on_demand` short-circuits untargeted FAST background completions** (2026-04-16, same-day hardening). When FAST mode is active, a first series is already displayed, there is no empty viewer, no viewer is awaiting the completed series, and no viewer is currently showing it, `load_series_on_demand` must NOT run the full Layer 2b viewer-completion/reload path. Finalize the progressive lifecycle bookkeeping, mark the thumbnail ready, and return. Do NOT force off-screen background completions through `on_series_download_fully_complete()` or a full load/rebind — it adds layout/control-plane churn with no user-visible benefit.
- **Terminal progress for untargeted FAST background completions must not enter `_start_progressive_display`** (2026-04-18). If `downloaded >= total` and there is no awaiting viewer, no empty viewer, and no viewer already showing the series, `on_series_images_progress` must defer to `load_series_on_demand` instead of creating transient progressive state for an off-screen completed series. Mark the terminal-progress guard and return. Do NOT let off-screen completion pulses re-enter the progressive first-display path — it causes duplicate thumbnail/progressive churn with no visible benefit.
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
- Progressive display lifecycle: DM `seriesProgressUpdated` → `home_download_service.on_series_progress` → `widget.series_images_progress.emit(sn, downloaded, total)` → `on_series_images_progress` → first batch: `_start_progressive_display` (only for the first displayed series, an empty viewer, or an explicitly awaiting target viewer; otherwise deferred) → subsequent: `_grow_progressive_fast`. Completion: DM `seriesDownloadCompleted` → `on_series_completed` → `_emit_final_progress(sn, total, total)` (Layer 2a), then `series_downloaded` → `load_series_on_demand` → either (a) `on_series_download_fully_complete` (Layer 2b: final grow, then terminal close routes through `_finalize_progressive_series(...)`; skip reload if a viewer already shows the full disk count) or (b) FAST untargeted background short-circuit (finalize bookkeeping + mark thumbnail ready when no viewer can use the completed series yet), then 500ms `_completion_verify_series` (Layer 3 repair), plus 3s `_completion_sweep_timer` (Layer 4 repair) for real viewer-bound completions. Guard states: `_progressive_display_inflight` (set), `_progressive_display_done` (set). FAST mode only (returns early for Advanced/VTK).

## Project-specific conventions
- Resource paths must go through `PacsClient/utils/config.py` (`BASE_PATH`, `ICON_PATH`, `IMAGES_LOGIN_PATH`) to work for both dev and PyInstaller.
- For sockets, update settings via `update_socket_server_settings()` before querying server-side lists.
- Prefer signals/slots for UI updates; download progress is emitted from background threads via Qt signals.
- **`set_server_series_info` is called TWICE per patient open** (v2.3.0+thumb-stable). Call 1 (main async thread, `_hp_patient_open.py` line 268) is the primary call; call 2 (from `_background_setup_thread`) is a merge-only call. The method now MERGES on subsequent calls (never overwrites `image_count` or `series_description` already populated by gRPC). Do NOT revert to unconditional `_server_series_info = {}` replacement — it discards gRPC-fetched image counts and triggers redundant thumbnail reloads.
- **`ThumbnailManager` must not use `print()`** (v2.3.0+thumb-stable). All logging goes through `_tm_logger` (debug/info/exception). `print()` in hot paths (`update_series_progress`, `start_series_download`, `apply_border_states_new`) causes synchronous stdout I/O that blocks the calling thread on Windows. Use `_tm_logger.debug()` for routine events, `_tm_logger.exception()` for errors in except blocks.
- **`QMetaObject.invokeMethod` for cross-thread UI dispatch in thumbnails** (v2.2.9.2). `set_server_series_info` may be called from a background `threading.Thread`. Use `QMetaObject.invokeMethod(self, "_load_server_thumbnails", Qt.QueuedConnection)` — never `QTimer.singleShot` — since QTimer.singleShot from a non-Qt thread has no event loop and is silently dropped. The `_load_server_thumbnails` and render slots must be decorated with `@Slot()`.
- **`_thumbnail_load_inflight` guard prevents concurrent thumbnail loads** (v2.2.9.2). Set to `True` in `_load_server_thumbnails` before the worker starts; reset to `False` in the worker's `finally` block. Do NOT schedule another load while this is `True` — it results in duplicate work and may reset pending/ready series border states.

## Build & installation layout (v2.3.7+)

### Install folder layout on end-user machines
```
C:\Program Files\AIPacs\
    AIPacs.exe                     ← launcher only
    engine\                        ← PyInstaller bundle root (renamed from _internal)
        base_library.zip
        PySide6\, vtkmodules\, ...
        config\installation_profile.json  ← fallback only; canonical is ProgramData
    Qss\                           ← QSS stylesheets

C:\ProgramData\AIPacs\
    config\
        installation_profile.json  ← canonical install config, written by installer
    module_packages\
        module_package_feed.json
        advanced_mpr\              ← optional runtime payloads (not in Program Files)
        printing\, echomind\, ...

%LOCALAPPDATA%\AIPacs\
    user_data\                     ← per-user DICOM cache and downloaded studies
    updates\                       ← update cache

%APPDATA%\AIPacs\config\           ← per-user runtime profile and update sources
```

### Key files for the build chain
| File | Purpose |
|------|---------|
| `pyproject.toml` | Single source of truth for `version = "X.Y.Z"` |
| `setup_build_env.ps1` | Creates `.venv_build` on any PC after git clone |
| `build.bat` | PyInstaller-builder Windows entry point — uses `.venv_build\Scripts\python.exe` when present |
| `builder/build_release.py` | PyInstaller builder orchestration: PyInstaller → staging → Inno Setup |
| `builder/spec/appA_workstation.spec` | PyInstaller spec; `contents_directory="engine"` in `EXE()` renames `_internal` |
| `builder/installer/AIPacs_Setup.iss` | PyInstaller installer script; writes profile + packages to ProgramData |
| `builder/requirements/build_requirements.txt` | Pinned build toolchain for `.venv_build` (includes `psutil>=5.9`) |
| `builder/inventory/imports_summary.json` | `suggested_hiddenimports` list read by `load_hiddenimports()` in spec |
| `build_nuitka.bat` | Nuitka-builder wrapper that routes to the staged pipeline |
| `build_nuitka_release.bat` | Nuitka-builder release wrapper with `.venv_build` bootstrap |
| `builder nuitka/build_nuitka_release.py` | Staged Nuitka orchestration: preflight → staged compile → stage → installer |
| `builder nuitka/installer/AIPacs_Nuitka_Setup.iss` | Nuitka installer script |
| `builder/docs/README.md` | Canonical index describing which builder to use for which task |

### Two independent builders (AI agent rule)

This repo has **two separate build systems** and AI agents must not mix them:

- **PyInstaller builder**
  - root: `builder/`
  - entrypoints: `build.bat`, `build.py`, `builder/build_release.py`
  - outputs: `builder/output/`
  - use for the current Python/PyInstaller release pipeline
- **Nuitka builder**
  - root: `builder nuitka/`
  - entrypoints: `build_nuitka.bat`, `build_nuitka_release.bat`, `builder nuitka/build_nuitka_release.py`
  - outputs: `builder nuitka/output/`
  - use for staged/resumable Nuitka work only

Decision rule for AI agents:

- If the user asks for `build.py`, `build.bat`, PyInstaller, `builder/spec/appA_workstation.spec`, or `builder/output/`, work in `builder/` only.
- If the user asks for Nuitka, stages, resume/checkpoints, `build_nuitka*`, `build_state.json`, or `builder nuitka/output/`, work in `builder nuitka/` only.
- Do NOT apply PyInstaller flags to Nuitka commands.
- Do NOT write Nuitka recovery guidance into the PyInstaller build path unless explicitly cross-referencing it.

### Critical build rules for AI agents
- **Version flows from `pyproject.toml` only.** `load_version()` reads it via `tomllib`; never hardcode a version in the spec or installer script.
- **`contents_directory="engine"` belongs in `EXE()`, NOT `COLLECT()`.** PyInstaller silently ignores unknown kwargs on `COLLECT` — the rename only works when set on `EXE`.
- **`psutil` MUST be in both `.venv_build` AND `suggested_hiddenimports`** (`builder/inventory/imports_summary.json`). It is a top-level import in `single_instance_lock.py`; missing it causes immediate crash on first launch of the built exe.
- **Any non-optional top-level import added to the codebase must be added to `suggested_hiddenimports`** in `imports_summary.json`. The `unique_imports` section in that file is NOT read by `load_hiddenimports()`.
- **`collect_submodules` covers `modules`, `database`, AND `PacsClient`** (v2.4.2). `builder/spec/appA_workstation.spec` iterates all three packages in the `collect_submodules` loop with the deny-filter applied to both `modules` and `PacsClient`. This auto-discovers every submodule in all three trees — no need to individually list PacsClient submodules in `suggested_hiddenimports`. Do NOT remove `"PacsClient"` from that loop or revert to per-file listing — missing a newly added PacsClient submodule causes `No module named 'PacsClient.xxx'` crash on first launch of the installed exe (confirmed v2.4.2: `echomind_settings.py` added `settings_ui` import that triggered this crash).
- **`installation_profile_path()` returns `%PROGRAMDATA%\AIPacs\config\installation_profile.json`** in frozen mode. `bundled_config_root()` (inside `engine\config\`) is the fallback only — do NOT write the canonical profile there at runtime.
- **`bundled_module_packages_search_roots()` searches ProgramData first** in frozen Windows mode. The installer deploys all optional module packages to `{commonappdata}\AIPacs\module_packages\` — not inside Program Files.
- **`program_data_config_root()`** is the new helper in `aipacs_runtime.py` that returns the ProgramData config path. Use it when reading system-wide deployment config.
- **`InternalConfigDir()` in the installer has a 3-tier fallback:** ProgramData config → `engine\config` → `_internal\config` (legacy). Do NOT collapse this to a single path — it keeps upgrades from old installs working.
- **`user_data_root()` has a writable-path fallback** (v2.4.5-patch). In frozen mode the preferred path is `install_root() / "User Data"` (Program Files). If that path is not writable (non-admin user, group policy, UAC), `_is_path_writable()` detects this and the function returns `local_state_root() / USER_DATA_DIRNAME` (`%LOCALAPPDATA%\AIPacs\user_data\`) instead. This is transparent to all callers. Do NOT hardcode `install_root() / "User Data"` directly — always call `user_data_root()`. Do NOT remove `_is_path_writable()` — it is the only runtime guard against `PermissionError` on restricted machines.
- **`sys.stdout` guard rule for frozen builds** (v2.4.5-patch). In PyInstaller windowed/no-console builds `sys.stdout is None`. Any method that calls `print()` or `sys.stdout.flush()` and is reachable from `__init__` of a widget constructed in the installed build MUST check `if sys.stdout is None: return` before any print/flush call. Use `logger.debug()` for persistent diagnostic output instead of `print()`. Confirmed crash pattern: `AttributeError: 'NoneType' object has no attribute 'flush'` from `_log_orientation_info()` in `_mpr_orientation.py`. Fixed in `_mpr_orientation.py` and `standard_mpr_viewer_original.py`; same guard must be applied to any future debug-logging helper called unconditionally from an `__init__` path.
- **`build_release.py` must use ASCII-only print statements.** Unicode characters (e.g., `→`) in `print()` calls inside `builder/build_release.py` raise `UnicodeEncodeError` on Windows consoles without UTF-8 mode. Use ASCII `->` instead. The canonical build command sets `PYTHONUTF8=1` as a belt-and-suspenders measure, but the source should be ASCII-safe regardless.
- **PyInstaller build command:** `.venv_build\Scripts\python.exe build.py` (full build including PyInstaller). Use `--skip-pyinstaller` only if `builder/output/dist/AIPacs/AIPacs.exe` already exists from this session — the `--skip-pyinstaller` flag still cleans staging outputs and re-runs Inno Setup.
- **Canonical env vars for the build command:** `AIPACS_ALLOW_MISSING_ADVANCED_MPR=1` (allows build to proceed when Advanced MPR payload is absent) and `PYTHONUTF8=1` (prevents Unicode console errors). Set both for every build invocation: `$env:AIPACS_ALLOW_MISSING_ADVANCED_MPR="1"; $env:PYTHONUTF8="1"; .venv_build\Scripts\python.exe build.py`.
- **Nuitka build command:** `.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --resume` (staged Nuitka pipeline). Use Nuitka-specific flags like `--stage`, `--from-stage`, `--clean-stage`, and `--smoke-test`; do not use `--skip-pyinstaller` here.

## Build/run/test workflows
- Run app: `python main.py` (Windows uses software OpenGL flags set in `main.py`).
- Build executable (PyInstaller builder): `build.bat` → `build.py` (PyInstaller spec `builder/spec/appA_workstation.spec`). Build venv: `.venv_build` (created by `setup_build_env.ps1`).
- Build executable (Nuitka builder): `build_nuitka.bat` or `.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --resume`. Outputs go to `builder nuitka/output/` and are independent from `builder/output/`.
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
- When changing B4.3 lifecycle helpers, preserve restart-after-DONE semantics: terminal late callbacks stay rejected, but a verified new partial cycle may clear `_series_download_completed` and re-enter the first-display path.
- When changing scroll/download UI throttling, preserve the protected 2 Hz cadence for thumbnail/progressive updates during active scroll or heavy download.
- When changing download-aware orchestration, prefer incremental policy routing (idempotence first, then probes, then central controller). Do not introduce a broad rewrite ahead of measured `ui_event_loop_lag_ms` or equivalent responsiveness evidence.
- When changing B4.x load shedding, route defer/pause decisions through SystemLoadController or ui_throttle helpers instead of ad hoc call-site checks. Non-terminal progressive grow may yield under protected UI, but terminal completion must remain visible.
- When changing DM priority notification timing (`_notify_dm_viewed_series`, cooldown, coordinator intervals), verify with `tests/download_manager/run_dm_test.py` scenarios S22-S26.
- When changing throttle/timer constants (progressive grow, progress debounce, coordinator recheck/retry, observer refresh delay), document old→new values in this file under Critical rules.
- When changing Layer 3 completion verify or adding new DONE→COMPLETING transitions, preserve the epoch-aware guard that skips re-entry when series is fully complete and viewer is up-to-date. Verify with `tests/viewer/test_fast_viewer_pipeline.py`.
- When changing prefetch radius caps or `_compute_adaptive_radius()`, preserve the series-level readiness override: `is_viewed_series_complete(sn)` must clear the `heavy_download_active` cap for completed series. Verify with `tests/viewer/test_b34_interaction_aware_policy.py`.
- When changing `_start_progressive_display` entry guards, preserve the completeness gate (`_PROGRESSIVE_MIN_COMPLETENESS`): defer first display during heavy overlap to avoid 500ms+ load spikes.

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
| `aipacs_runtime.py` | `user_data_root()`, `roaming_config_root()`, `program_data_config_root()`, `_is_path_writable()` | Path resolution for dev vs PyInstaller; `installation_profile_path()` → ProgramData in frozen mode; `bundled_module_packages_search_roots()` → ProgramData first; `user_data_root()` has writable-fallback to LocalAppData (v2.4.5-patch) |
| `_project_root.py` | `PROJECT_ROOT` | Canonical root path resolution |
| `setup_build_env.ps1` | — | Creates `.venv_build` on any PC after git clone; installs pinned build toolchain from `builder/requirements/build_requirements.txt` |
| `build.bat` | — | PyInstaller-builder Windows entry point; uses `.venv_build\Scripts\python.exe` when present, falls back to ambient Python with warning |
| `build.py` | — | Thin PyInstaller-builder launcher; delegates to `builder/build_release.py` |
| `builder/build_release.py` | `load_version()`, `validate_release_bundle_graphics_runtime()` | Full PyInstaller-builder orchestration: PyInstaller → DLL validation → staging → Inno Setup |
| `builder/spec/appA_workstation.spec` | — | PyInstaller spec; `contents_directory="engine"` in `EXE()` renames `_internal` → `engine` |
| `builder/installer/AIPacs_Setup.iss` | — | PyInstaller installer script; installs exe + engine/ to Program Files; writes profile + module_packages to ProgramData |
| `build_nuitka.bat` | — | Nuitka-builder entry point; routes to staged `builder nuitka/build_nuitka_release.py` |
| `build_nuitka_release.bat` | — | Nuitka-builder wrapper with `.venv_build` bootstrap and requirements install |
| `builder nuitka/build_nuitka_release.py` | — | Staged Nuitka orchestration with checkpoints, resume, reports, and smoke-test support |
| `builder nuitka/installer/AIPacs_Nuitka_Setup.iss` | — | Nuitka installer script |
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
| `fast/disk_pixel_cache.py` | `DiskPixelCache` | B3.12 L2 persistent disk cache for decoded pixels |
| `fast/decode_service.py` | `DecodeService` | B3.11 subprocess-based decode for GIL isolation |
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
| Build release executable (PyInstaller) | `build.bat` → `build.py` → `builder/build_release.py` |
| Build release executable (Nuitka) | `build_nuitka.bat` / `build_nuitka_release.bat` → `builder nuitka/build_nuitka_release.py` |
| Set up build environment | `setup_build_env.ps1` → creates `.venv_build` |
| PyInstaller spec (bundle layout) | `builder/spec/appA_workstation.spec` |
| Nuitka staged build state | `builder nuitka/output/build_state.json` |
| Hidden imports list | `builder/inventory/imports_summary.json` → `suggested_hiddenimports` |
| Install profile written at install | `builder/installer/AIPacs_Setup.iss` → `WriteInstallationProfile()` |
| Install profile read at runtime | `aipacs_runtime.py` → `installation_profile_path()` |
| Module packages resolved at runtime | `aipacs_runtime.py` → `bundled_module_packages_search_roots()` |
| ProgramData config path | `aipacs_runtime.py` → `program_data_config_root()` |
| Graphics DLL validation (build) | `builder/build_release.py` → `validate_release_bundle_graphics_runtime()` |
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
| Progressive display | `tests/viewer/test_fast_viewer_pipeline.py` | 61 tests | `python -m pytest tests/viewer/test_fast_viewer_pipeline.py -v` |
| Stage 1 migration | `tests/viewer/test_stage1_migration_validation.py` | 34 tests — resolution, alias, unreachability, guards, exhaustive matrix | `python -m pytest tests/viewer/test_stage1_migration_validation.py -v` |
| Stage 2 hardening | `tests/viewer/test_stage2_hardening_validation.py` | 15 tests — escape hatch, bind remap, sanity check, force_vtk override | `python -m pytest tests/viewer/test_stage2_hardening_validation.py -v` |
| Disk pixel cache | `tests/viewer/test_disk_pixel_cache.py` | 12 tests — round-trip, corruption, eviction, benchmark | `python -m pytest tests/viewer/test_disk_pixel_cache.py -v` |
| Decode service | `tests/viewer/test_decode_service.py` | 9 tests — lifecycle, correctness, benchmark | `python -m pytest tests/viewer/test_decode_service.py -v` |
| Control-plane governance | `tests/viewer/test_cp1_control_plane_governance.py` | 18 tests — epoch-aware L3, series readiness, completeness gate, mixed-load throttle, ZetaBoost triage | `python -m pytest tests/viewer/test_cp1_control_plane_governance.py -v` |
| Advanced protected latch (R15) | `tests/viewer/test_advanced_protected_interaction.py` | 7 tests — latch, grace window, keepalive, FAST/Advanced OR, admission shell, R5 skip visibility | `python -m pytest tests/viewer/test_advanced_protected_interaction.py -v` |
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

