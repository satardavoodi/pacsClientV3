# Performance Decision Log — 2026-02-26 / 2026-02-27

> Continuation of `PERFORMANCE_DECISION_LOG_2026-02-24.md`.  
> See `docs/PERFORMANCE_STATUS.md` for the current one-page summary of all findings.

---

## Session 2026-02-26 — Parallel I/O + Scroll Drain

### Data Observed

**Logs from PC A (study: 330-slice CT + MR brain, ~10 series):**

| Stage | Before | Measured |
|---|---|---|
| Instance create (viewer, 330 files) | — | 4.307s serial |
| batch_insert_instances_total (download subprocess, ~480 files) | — | 2217ms serial |
| apply_filters MR 20sl (Mode B DL_WARMUP, 1-thread) | — | ~2.9s per series |
| scroll spike during DL_WARMUP ITK | — | 200–309ms spikes |
| queue_p95_ms in scroll probe | — | **19,496ms** (stale-event backlog) |

### Decisions Made

**v2.2.3.1.9** — Parallel pydicom, viewer side  
- `utils.py` `get_or_create_instance`: replaced serial pydicom loop with `ThreadPoolExecutor(max_workers=min(8, cpu_count))`  
- Result: 4.307s → ~0.8s for 330-file CT

**v2.2.3.2.0** — Parallel pydicom, download subprocess + adaptive ITK + BELOW_NORMAL filter priority  
- `series_downloader.py`: parallel `asyncio.gather` + ThreadPoolExecutor for header reads  
- `image_filters.py`: adaptive `max(min(cpu_count-2, 8), 2)` threads (was fixed at 1)  
- `image_filters.py`: `THREAD_PRIORITY_BELOW_NORMAL` via ctypes during filter pass  
- Result: batch_insert 2217ms → 326ms

**v2.2.3.2.1** — Stale-event fast-drain guard in `set_slice`  
- Root cause: main thread blocked by SERIES_DOWNLOAD_COMPLETE signal handlers → Qt event queue fills with stale scroll events → each renders fully at ~50ms  
- Fix: when `queue_delay_ms > 500ms`, skip VTK render (slider only), set `_pending_wheel_slice` for one render after drain  
- Result: 84-event backlog drained in <1ms, one render at final position

---

## Session 2026-02-27 — DL_WARMUP Speed

### Data Observed

**Logs from PC A (new MR brain study download, threads=1 DL_WARMUP):**

| Stage | Observed | Problem |
|---|---|---|
| DL_WARMUP series=6 (500×640×24 MR) | 4138ms | threads=1 ITK 2939ms |
| DL_WARMUP series=7 (620×640×20 MR) | 3884ms | threads=1 ITK 2976ms |
| DL_WARMUP series=8 (176×176×40 MR) | 1172ms | threads=1 ITK 473ms — OK |
| WORKER_BLOCKED reason=max_parallel(1/1) | 5 events | ZetaBoost can't run workers in parallel |
| queue_delay_ms during scroll | 2804–3587ms | stale-drain guard not yet deployed in this run |

### Decision

**v2.2.3.2.2** — DL_WARMUP speed improvements  
- `max_itk_threads=1` → `max_itk_threads=2` in DL_WARMUP path (halves large-FOV MR time: 4.1s → ~2.0s)  
- Inter-series delay `3.0s` → `1.5s` (ITK now faster; 3s was conservative)  
- `max_parallel_loads=1` → `max_parallel_loads=2` for 8GB+ and 15GB+ RAM tiers  
  - Justified by: BELOW_NORMAL OS priority (v2.2.3.2.0) + stale-drain guard (v2.2.3.2.1) protect VTK render from ITK contention  
  - Expected: two ZetaBoost workers can overlap; 6-series warmup finishes in ~8–10s instead of ~20s

---

## Session 2026-02-27 (afternoon) — Subprocess DL_WARMUP + First-Series GIL Cap

### Data Observed (post v2.2.3.2.2 test)

**Logs from PC A (study: MR brain, Mode B with active download):**

| Stage | Measured (v2.2.3.2.3) | Problem / Win |
|---|---|---|
| `queue_p95_ms` during scroll (DL active) | **0.00ms** | **GIL contention from DL_WARMUP: ELIMINATED** ✅ |
| `set_slice_p95_ms` during DL | 52–61ms | Still elevated vs Mode A (~28ms) — first-series in-process |
| `slice_apply_p95_ms` | 37–45ms | VTK software-GL baseline |
| `[DL_WARMUP_SUB] ✓ Cached series=101` | 402ms | Subprocess: very fast, own GIL |
| First-series load (series=201) | 2465ms IN-PROCESS | Unlimited ITK threads + 8 pydicom workers |
| `Parallel DICOM read: 52 files` | 492ms | 8 pydicom workers all hitting GIL |
| `Instance create` | 826ms | DB writes |
| `ITK filters` | 683ms | Unlimited threads competing with UI |

### Decisions Made

**v2.2.3.2.3** — DL_WARMUP moved to `multiprocessing.Process`
- **Root cause:** DL_WARMUP ran as a background thread in the viewer process. Every `sitk.ReadImage`, `apply_filters`, `convert_itk2vtk` call acquired the GIL, competing with VTK `Render()` and Qt event processing. This caused `queue_p95_ms` of 200–510ms during scroll.
- **Fix:** New file `warmup_subprocess.py` implements `WarmupSubprocessManager`:
  - `multiprocessing.Process(start_method='spawn')` with own Python interpreter + own GIL
  - Worker function `_warmup_subprocess_main()` loads series → sends `(series_number, numpy_array, metadata_dict)` via `mp.Queue`
  - Viewer-side QTimer (100ms) polls `_poll_warmup_subprocess_results()`, converts numpy→VTK, stores in ZetaBoost L1
  - Process runs at IDLE priority, `max_itk_threads=2`
- **Also fixed:**
  - Removed redundant `sitk.Cast(float_img, sitk.sitkFloat32)` in `_smooth_xy_recursive` (already float32 from cast-once)
  - GIL yield sleeps 50ms→5ms in `image_io.py` DB load path
- **Result:** `queue_p95_ms` = **0.00ms** — zero GIL contention from DL_WARMUP

**v2.2.3.2.4** — First-series in-process GIL contention cap
- **Root cause:** After subprocess fix, remaining `set_slice_p95_ms=52-61ms` traced to first-series load via `asyncio.to_thread(_load_single_series_on_demand)`. This called `load_single_series_by_number()` without `max_itk_threads` (= all CPU cores) and pydicom ThreadPool with 8 workers. Total ~16 threads all flooding GIL during 2.4s load.
- **Fix:**
  - `patient_widget_viewer_controller.py`: pass `max_itk_threads=2, max_pydicom_workers=2` to `load_single_series_by_number()`
  - `utils.py`: `get_or_create_instance(max_workers=None)` → accepts optional cap
  - `image_io.py`: `load_single_series_by_number(max_pydicom_workers=None)` → threads through to `process_series_groups` → `get_or_create_instance`
  - `image_io.py`: `process_series_groups` CPU yields 50ms→5ms (matched DB-path reduction)
- **Trade-off:** First-series load may be ~5% slower (fewer parallel workers), but GIL contention drops from ~16 threads to 4 — scroll during load should be significantly smoother
- **Expected:** `set_slice_p95_ms` drops from 52-61ms to <40ms during first-series Mode B load

---

## Open Questions for Next Session

1. **Does v2.2.3.2.4 actually reduce `set_slice_p95_ms` below 40ms during first-series Mode B load?**  
   Run Mode B test: open study during download, scroll continuously during first-series load, check scroll probe.

2. **Is the P1 queue spike (2.8–3.5s) from `SERIES_DOWNLOAD_COMPLETE` signal handlers still present?**  
   The subprocess fix only eliminates DL_WARMUP GIL contention. Download-complete signals still run on Qt main thread.
   Add `t0 = time.monotonic()` at top of signal handler, log at end.

3. **Should first-series also route through subprocess?**  
   Would eliminate ALL in-process GIL contention in Mode B, but requires display path refactoring (subprocess
   result must trigger `_display_first_series_in_all_viewers()` via QTimer poll instead of sequential return).

4. **Can `update_corners_actors()` be split into scroll-varying vs series-constant parts?**  
   Only `im_slice_actor` (slice count) and `im_series_window_level` (WL) change per-scroll.
   Others (date, series name, thickness, size) are constant within a series — call once on switch.

5. **Does Lock Sync `_do_lock_sync()` need debouncing?**  
   Currently runs coordinate math + applies to target viewers on every scroll.
   Debouncing to every 2nd or 3rd event would reduce overhead without visible sync delay.

6. **What still causes 38–88ms `viewer_db_read` per series load?**  
   The query is `SELECT pk, instances FROM series WHERE uid=?` — may be missing an index or scanning.

---

## Session 2026-02-27 (evening) — Render Pipeline + Signal Coalescing

### Data Observed (post v2.2.3.2.4 test)

**Logs from PC A (study: MR brain, Mode B, scrolling during download):**

| Stage | Measured | Problem / Win |
|---|---|---|
| `event_queue_delay_ms` over time | 620ms → 1847ms → 3249ms → 5437ms | **Escalating** — signals starving scroll events |
| `set_slice_p95_ms` when no signals | ~37–45ms | VTK software-GL baseline — FXAA + MSAA overhead |
| `Render()` sub-timing | ~35–50ms | FXAA (20-50ms) + MSAA (10-30ms) — pure waste for 2D images |
| `color_mapper.Update()` per scroll | ~5–15ms | Redundant — `Render()` auto-updates after `SetWindow()/SetLevel()` |
| Series-completion signal burst | 5+ signals in <500ms | Each triggers synchronous thumbnail + warmup work |

### Decisions Made

**v2.2.3.2.5** — Render pipeline optimizations (software OpenGL)
- **Root cause:** On software OpenGL (WARP/Mesa/SwiftShader), VTK's default pipeline adds 35-95ms of unnecessary overhead per `Render()`:
  1. FXAA (CPU post-process AA): 20-50ms — useless for 2D pixel-exact medical images
  2. 8x MSAA: multiplies per-pixel work — no polygon edges to antialias on `vtkImageActor`
  3. `color_mapper.Update()` called on every scroll — redundant since `Render()` auto-updates
- **Fix:**
  - `viewer_2d.py`: `renderer.UseFXAAOff()` (was `UseFXAAOn()`)
  - `vtk_widget.py`: `render_window.SetMultiSamples(0)` (VTK defaults to 8)
  - `viewer_2d.py` `set_window_level()`: skip `color_mapper.Update()` when `flag_default=True` (scroll path)
  - `viewer_2d.py` `set_slice()`: sub-timing instrumentation for performance analysis
  - `patient_widget_viewer_controller.py`: `max_pydicom_workers=2` in DL_WARMUP warmup callback
- **Expected:** VTK Render component drops from 35-95ms to <25ms

**v2.2.3.2.6** — Coalesce SERIES_DOWNLOAD_COMPLETE signals
- **Root cause:** `seriesDownloadCompleted` signals from download subprocess fire back-to-back for 5+ series during first-series VTK viewer init (200-500ms on software GL). Each signal triggers synchronous main-thread work (thumbnail border update + pipeline signal + warmup enqueue). Queue delay escalates from 620ms to 5437ms as signals compound.
- **Fix — `home_ui.py` (`_connect_download_manager_to_widget`):**
  - Replaced immediate `on_series_completed()` with coalesced handler
  - First series in burst → dispatched immediately (first-series display latency preserved)
  - Subsequent series → accumulated in `_pending_completed` list
  - `_flush_timer` (100ms singleShot QTimer) debounces batch processing
  - `_flush_pending_completions()` processes batch with `processEvents()` yield every 2 series
- **Fix — `patient_widget_viewer_controller.py` (`_display_first_series_in_all_viewers`):**
  - Added `QApplication.processEvents()` after `_mark_first_series_displayed()` so pending scroll events fire between VTK init and queued completion signals
- **Expected:** `event_queue_delay_ms` drops from 620–5437ms to <200ms; stale-drain guard activations become rare

---

## Open Questions for Next Session (post v2.2.3.2.6)

1. **Does v2.2.3.2.6 actually keep `event_queue_delay_ms` below 200ms during bulk completion bursts?**  
   Run Mode B test: open study during download with 8+ series, scroll continuously, check queue_delay logs.

2. **Does v2.2.3.2.5 reduce Render component to <25ms?**  
   Check `viewer-scroll sub-timing` logs — Render column should be significantly lower.

3. **Should first-series also route through subprocess?**  
   Would eliminate ALL in-process GIL contention in Mode B. Complexity: subprocess must load → serialize → QTimer polls → display.

4. **Can `update_corners_actors()` be split into scroll-varying vs series-constant parts?**  

5. **Does Lock Sync `_do_lock_sync()` need debouncing?**  

6. **What still causes 38–88ms `viewer_db_read` per series load?**

---

## Rollback Notes

If any v2.2.3.2.x change causes regression:

| Issue | Rollback |
|---|---|
| Stale drain causes missed renders | Set `_STALE_SCROLL_MS = 99999` in vtk_widget.py (effectively disables guard) |
| FXAA-off causes visual regression | Revert to `renderer.UseFXAAOn()` in `viewer_2d.py` (line ~219) |
| MSAA=0 causes visual regression | Remove `render_window.SetMultiSamples(0)` in `vtk_widget.py` (line ~110) |
| Skip color_mapper.Update causes stale WL | Remove the `if not flag_default:` guard in `set_window_level()` — always call `.Update()` |
| Signal coalescing misses series completions | Remove coalesced handler in `home_ui.py` `_connect_download_manager_to_widget` — restore direct `on_series_completed` |
| processEvents yield causes reentrancy issues | Remove `QApplication.processEvents()` in `_display_first_series_in_all_viewers` |
| Subprocess DL_WARMUP crashes or hangs | Set `AIPACS_DL_WARMUP_SUBPROCESS=0` env var → falls back to in-process thread |
| Subprocess DL_WARMUP produces corrupt images | Check `result_to_vtk()` in `warmup_subprocess.py` — verify array shape/dtype matches |
| First-series threads=2 too slow for large studies | Remove `max_itk_threads=2` from `_load_single_series_on_demand` call (~line 4116 of controller) |
| First-series pydicom workers=2 too slow | Remove `max_pydicom_workers=2` from `_load_single_series_on_demand` call |
| DL_WARMUP threads=2 causes scroll spikes (unlikely with subprocess) | Set `max_itk_threads=1` in subprocess config |
| max_parallel_loads=2 causes overshooting | Set `max_parallel_loads=1` in the tier config block (~line 420) |
| Inter-delay 1.5s too aggressive | Set `AIPACS_DL_WARMUP_INTER_DELAY=3.0` env var (no code change needed) |
