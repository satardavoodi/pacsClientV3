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

## Session 2026-02-27 (night) — Scroll Optimization Sprint v2.2.3.2.7–v2.2.3.2.9

### v2.2.3.2.7 — Fixed infinite stale-drain re-arm loop

**Data Observed (post v2.2.3.2.6 test):**

| Stage | Measured | Problem |
|---|---|---|
| UI freeze on scroll | **44,000ms** (44 seconds) | `_flush_pending_wheel_slice` re-armed indefinitely |
| Root cause | `_last_scroll_event_ms` never reset | Stale-drain guard always saw "stale" → skipped render → re-armed timer → infinite loop |
| Main-thread starvation | Viewer creation blocked | No `processEvents()` between creating multiple VTK viewers |
| gRPC on main thread | Synchronous `authorize_user` | Blocked event loop during login |

**Fixes applied:**
1. `_flush_pending_wheel_slice`: Reset `_last_scroll_event_ms = now_ms()` on each flush — breaks infinite re-arm
2. `processEvents()` yield between viewer creations in controller
3. gRPC `authorize_user` offloaded to `asyncio.to_thread()`

**Result:** 44s freeze eliminated. Scrolling now ~8fps on software GL.

**Commit:** `8fb6629`

---

### v2.2.3.2.8 — Adaptive throttle replaces debounce (~2x frame rate)

**Data Observed (post v2.2.3.2.7 test, user: "better but there is some small lags"):**

| Stage | Measured | Problem |
|---|---|---|
| `scroll_probe p50` | 42.85ms | Acceptable |
| `scroll_probe p95` | 82.85ms | Elevated |
| `queue_p95_ms` | **0.00ms** | ✅ Stale drain fixed |
| Frame interval | 125–237ms (5–8fps) | Debounce timer restarts on every event → 16ms latency per frame |
| Per-event overhead | Ruler update, border check, camera save | Redundant work on each wheelEvent (10–15/sec) |
| `notify_viewer_interaction` | Called per-event | Creates QTimer.singleShot + toggles ZetaBoost pausing 15x/sec |

**Fixes applied:**
1. **Adaptive THROTTLE** replaces debounce: render immediately on first scroll after idle, pace subsequent renders with adaptive gap (25% of frame time, clamped [4ms, 50ms])
2. **Skip per-event overhead**: Removed ruler update, border check, camera save from `wheelEvent` (these run in `set_slice` anyway)
3. **Throttle `notify_viewer_interaction`** to once per 500ms (was per-event)

**Result:** User reports "great its much better we have few lag". Measured:
- `set_slice_total`: 17–60ms, mostly 40–58ms (was 30–98ms)
- Frame interval: ~85–116ms (~10fps, was 125–237ms / 5–8fps)
- **~2x frame rate improvement**

**Commit:** `e34c6b1`

---

### v2.2.3.2.9 — GC suppression during scroll + booster throttle

**Data Observed (post v2.2.3.2.8 test, user: "great its much better we have few lag"):**

| Stage | Measured | Problem |
|---|---|---|
| Frame intervals (typical) | 85–116ms (~10fps) | ✅ Consistently smooth |
| Frame interval (sporadic gap) | **338ms** (04:26:33.536→33.926) | Zero main-thread activity in logs → **Python GC pause** |
| `set_slice_total` | 17–60ms | Good for sw GL |
| Sub-timing: SetSlice | 20–35ms | VTK pipeline baseline |
| Sub-timing: Render | 7–14ms | Draw call baseline |
| ImageSliceBooster | Called per-render | Prefetch window re-centered every frame during rapid scroll |
| Series switch (203) | 718ms | VTK data mapping — one-time cost, not per-scroll |
| `_load_single_series_on_demand` | 5746ms (background) | asyncio.to_thread — does NOT block main thread |

**Analysis:**
- 338ms gap with zero main-thread log entries = classic Python GC gen-1/gen-2 pause
- GC can collect 100–400ms worth of cyclic references when gen counts reach threshold
- During scroll at 10fps, ~10 VTK/numpy objects created per second → triggers thresholds
- ImageSliceBooster.on_slice_changed called per-render wastes CPU scheduling prefetch that's immediately invalidated

**Fixes applied:**
1. **GC suppression during scroll bursts:**
   - `gc.disable()` on first `wheelEvent` of a burst
   - `_gc_reenable_timer` (QTimer, 300ms, singleShot) restarts after every render
   - When timer fires (300ms idle): `gc.enable()` + `gc.collect(0)` (gen-0 only, ~0.1ms)
   - `switch_series` also re-enables GC to avoid state leaks
2. **Throttle ImageSliceBooster notification:**
   - `on_slice_changed` now called at most once per 200ms (was every render)
   - At 10fps, 4 out of 5 calls were wasted (prefetch window immediately invalidated)

**Expected:** Eliminates random 100–400ms GC-induced stutters. Reduces per-frame overhead from booster.

**Commit:** `495a61a`

---

## Open Questions for Next Session (post v2.2.3.2.9)

1. **Does v2.2.3.2.9 actually eliminate the sporadic ~338ms gaps?**
   Run scroll test for 30+ seconds, check for gaps >200ms in logs.

2. **Can `update_corners_actors()` be split into scroll-varying vs series-constant parts?**
   Only `im_slice_actor` (slice count) and `im_series_window_level` (WL) change per-scroll.

3. **Should first-series also route through subprocess?**
   Would eliminate ALL in-process GIL contention in Mode B.

4. **Does Lock Sync `_do_lock_sync()` need debouncing?**
   Runs coordinate math on every scroll event.

5. **What still causes 38–88ms `viewer_db_read` per series load?**

---

## Session 2026-02-27 (continued) — GC Hardening + Event-Loop Bypass (v2.2.3.3.0–v2.2.3.3.2)

### Data Observed (PC B test with heavy volumes)

| Stage | Measured | Problem |
|---|---|---|
| Periodic lag pattern (PC B) | **660–700ms** every few seconds | 500ms GC re-enable timer + ~150ms gen-1 GC collection |
| `os.getenv` per frame | 3–5ms × 2 calls = 6–10ms | Per-frame overhead in `_should_log_timing` |
| Coalesce timer bypass | Timer stuck behind queued signals | Event-loop congestion delayed timer callback 100–300ms |

### Decisions Made

**v2.2.3.3.0** (`66914e0`) — Strengthen GC suppression for heavy volumes (PC B)
- Increased GC re-enable timer from 500ms → 2000ms
- Keep elevated thresholds (700,50,50) on re-enable instead of restoring originals
- Avoid overwriting saved thresholds on re-enter
- Result: Eliminated 660ms periodic lag pattern on PC B

**v2.2.3.3.1** (`0382270`) — Event-loop bypass eliminates periodic lag
- Cache `os.getenv` values in `__init__` (was 3–5ms per call × 2 per frame)
- Bypass coalesce timer when adaptive gap already expired during event-loop congestion
- Result: Eliminated 100–300ms stalls from download signal congestion

**v2.2.3.3.2** (`edfff7f`) — Eliminate 660ms periodic GC lag
- Final refinement of GC suppression: save original thresholds only once (not on re-enter)
- Combined fix verified on PC B: no more periodic lag pattern

---

## Session 2026-02-27 (continued) — Reference Line Optimization Sprint (v2.2.3.3.3–v2.2.3.3.7)

### Data Observed

| Stage | Measured | Problem |
|---|---|---|
| `_update_reference_lines()` per scroll | 20–40ms Render per target viewer | Blocks main thread on every scroll frame |
| N viewers × Render per tick | N × 20ms overhead | Linear scaling with viewer count |

### Decisions Made (progressive refinement)

**v2.2.3.3.3** (`1f2cd36`) — Debounce reference line updates during scroll
- `_schedule_reference_line_update()` with 80ms trailing-edge QTimer
- Result: Reference line Render no longer fires on every scroll frame

**v2.2.3.3.4** (`5b3b77c`) — Sync reference lines with stack drag + lock sync
- Ref-line update fires after lock sync completes
- Debounced at 80ms to prevent Render-per-target
- Result: Reference lines stay current during lock sync drag

**v2.2.3.3.5** (`6b18b94`) — Real-time reference line sync
- Dual-timer pattern: leading-edge (immediate, geometry-only) + trailing-edge (50ms, with repaint)
- Result: Instant actor positioning + deferred repaint

**v2.2.3.3.6** (`f90b608`) — Eliminate ref-line paint blocking from scroll loop
- Trailing-edge uses `repaint=False` geometry-only update
- Actual VTK Render deferred to scroll-end
- Result: Scroll loop never blocked by ref-line Render

**v2.2.3.3.7** (`f6c4dda`) — Round-robin reference line repaint
- Trailing-edge paints ONE target viewer per tick (round-robin)
- Scroll-end tick repaints ALL targets for full visual correctness
- Result: Capped ref-line event-loop blocking to ~20ms per tick

---

## Session 2026-02-27 (continued) — Mode B Contention Fix (v2.2.3.3.8–v2.2.3.3.9)

### Data Observed (CT study, 34 slices, Mode B with active download)

| Stage | Measured | Problem |
|---|---|---|
| Size-mismatch false positives | Multiple during download | Compared against cached count instead of DB expected count |
| Subprocess apply_filters (2 ITK threads) | 7161ms for 34 CT slices | Memory-bus contention spiked SetSlice 8→45ms |
| Result poll during scroll | Unthrottled | Poll could fire mid-scroll, causing stalls |
| notify_viewer_interaction throttle | 500ms | Left 150ms gap where warmup workers could start |

### Decisions Made

**v2.2.3.3.8** (`125c00a`) — Fix size-mismatch detection for incomplete downloads
- Compare against DB expected instance count, not just cached data
- Result: Eliminated spurious warmup retries during download

**v2.2.3.3.9** (`af11baf`) — Reduce Mode B scroll lag from warmup contention
- Subprocess ITK threads 2→1 (memory-bus contention reduction)
- Defer result poll during scroll (idle<300ms guard)
- Max 1 result per poll tick (was 2)
- Tighten notify_viewer_interaction throttle 500→250ms
- Result: Reduced SetSlice spikes during warmup window

---

## Session 2026-02-27 (final) — Scroll Fast-Path (v2.2.3.4.0)

### Data Observed (CT study, 34 slices, Mode B)

Scroll probe: `mode=mode_b p50=44.80ms p95=60.87ms max=91.76ms queue_p95=0.00ms`

| Stage | Measured | Problem |
|---|---|---|
| Camera zoom save/restore | ~3–5ms per frame | VTK→Python round-trips + comparison on every scroll |
| Interactor style update | ~1ms per frame | Ruler tool hook with no visual effect during scroll |
| Lock Sync callback | 5–20ms per frame (when active) | World-coord computation + sync ALL target viewers on every frame |
| Subprocess warmup (BELOW_NORMAL) | SetSlice 20→45ms during warmup | Memory-bus contention from ITK allocations |
| Gap: viewer total vs set_slice_total | 5–15ms per frame | Sum of above overhead items |

### Decisions Made

**v2.2.3.4.0** (`5215a89`) — Scroll fast-path: skip non-essential per-frame overhead
- **Camera zoom save/restore:** Skip during wheel scroll. The wheel event is consumed (`event.accept`) so VTK's built-in zoom is blocked. `_protected_parallel_scale` remains valid from the last non-scroll interaction. Saves ~3–5ms/frame.
- **Interactor style update:** Skip `style.update_slice()` during wheel scroll. Ruler tools are not meaningfully updated during rapid scrolling. Saves ~1ms/frame.
- **Lock Sync throttle:** `_on_slice_changed_cb` throttled to once per 100ms during wheel scroll (was every frame). `_do_lock_sync()` computes world coordinates + syncs all target viewers. At 10–15fps, calling on every frame wastes 5–20ms of immediately-superseded work. 100ms spacing is visually smooth. Saves 0–20ms/frame.
- **Subprocess warmup priority:** `BELOW_NORMAL_PRIORITY_CLASS` (0x4000) → `IDLE_PRIORITY_CLASS` (0x40). IDLE lets the OS fully favour the viewer process during scroll; subprocess runs in scroll-pause gaps. Reduces SetSlice spikes from 20→45ms to near baseline.

**Implementation:**
- `vtk_widget.py`: Added `_in_wheel_scroll` flag (set True in `_flush_pending_wheel_slice`, False in finally block). `set_slice()` checks flag to skip camera save/restore, interactor style, and throttle Lock Sync.
- `warmup_subprocess.py`: Changed `SetPriorityClass` constant from `0x00004000` to `0x00000040`.

**Expected:** `set_slice_total` p50: ~45ms → ~35ms (4–5ms overhead skip + reduced contention); p95: ~61ms → ~45ms (warmup spike attenuation from IDLE priority).

---

## Open Questions for Next Session (post v2.2.3.4.0)

1. **Does v2.2.3.4.0 actually reduce `set_slice_p50_ms` to ~35ms during Mode B scroll?**
   Run Mode B test: scroll during active download with CT study, check scroll probe.

2. **Does IDLE priority cause the warmup to finish too slowly?**
   Check `[DL_WARMUP_SUB] ✓ Cached series=X in Yms` — should still be <2000ms per series.

3. **Can `update_corners_actors()` be split into scroll-varying vs series-constant parts?**
   Only `im_slice_actor` (slice count) and `im_series_window_level` (WL) change per-scroll.

4. **Should first-series also route through subprocess?**
   Would eliminate ALL in-process GIL contention in Mode B.

5. **What still causes 38–88ms `viewer_db_read` per series load?**

---

## Rollback Notes

If any v2.2.3.x change causes regression:

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
| DL_WARMUP threads=1 too slow for warmup | Set `max_itk_threads=2` in subprocess config (reverts v2.2.3.3.9) |
| max_parallel_loads=2 causes overshooting | Set `max_parallel_loads=1` in the tier config block (~line 420) |
| Inter-delay 1.5s too aggressive | Set `AIPACS_DL_WARMUP_INTER_DELAY=3.0` env var (no code change needed) |
| GC suppression leaks memory | Remove `gc.disable()` from `wheelEvent` in vtk_widget.py; delete `_gc_reenable_timer` setup from `__init__` |
| Adaptive throttle skips frames | Set `AIPACS_SCROLL_COALESCE_MS=16` and revert `wheelEvent` to debounce pattern (restart timer on every event) |
| Booster throttle causes stale prefetch | Remove `_last_booster_notify_ms` guard in `set_slice` — call `on_slice_changed` on every render |
| Scroll fast-path skips needed camera restore | Set `_in_wheel_scroll = False` always (remove flag from `_flush_pending_wheel_slice`) — restores full per-frame overhead |
| Lock Sync throttle causes visible desync | Remove `_last_lock_sync_ms` throttle in `set_slice` — restore per-frame Lock Sync callback |
| IDLE priority stalls warmup | Revert `IDLE_PRIORITY_CLASS` to `BELOW_NORMAL_PRIORITY_CLASS` (0x00004000) in `warmup_subprocess.py` |
| Ref-line round-robin leaves stale lines | Increase `_ref_line_rr_repaint_ms` or revert to full repaint on every trailing-edge tick |
