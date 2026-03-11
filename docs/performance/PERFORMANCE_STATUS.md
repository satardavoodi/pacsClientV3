# AIPacs Performance Status
**Version:** v2.2.3.4.0 | **Branch:** DR.vahid | **Updated:** 2026-02-27

> **Quick-start:** Start here. After reading this file, go to `METRICS_TRACKING_v2.2.3.x.md` for detailed measurements, or `docs/CROSS_PC_IMPROVEMENT_WORKFLOW.md` for the PC A/B validation process.

---

## 1. Architecture — Three Paths to Display

```
User double-clicks study
        │
        ▼
[HOME UI] opens patient tab immediately
        │
        ├─► [DOWNLOAD SUBPROCESS pid=N]  ← background, BELOW_NORMAL priority
        │        SeriesDownloader → socket → DICOM files on disk
        │        parallel pydicom header reads → DB insert (v2.2.3.2.0)
        │
        └─► [VIEWER — Qt main thread]
                 │
                 ├─ INTERACTIVE LOAD (user clicks series thumbnail)
                 │    image_io.load_single_series_by_number
                 │      ├─ DB query (38–88ms)
                 │      ├─ disk read (27–384ms)
                 │      ├─ ITK filter chain (150ms–3s, adaptive threads)
                 │      └─ ITK→VTK convert (2–45ms)
                 │
                 ├─ FIRST-SERIES DISPLAY (Mode B, asyncio.to_thread)
                 │    v2.2.3.2.4: max_itk_threads=2, max_pydicom_workers=2
                 │    (was unlimited → massive GIL contention with UI thread)
                 │
                 ├─ ZETA BOOST WARMUP (background, post-download)
                 │    lane=warmup, 2 workers, max_parallel_loads=2 (8GB+)
                 │    max_itk_threads=2, BELOW_NORMAL OS priority
                 │
                 └─► [DL_WARMUP SUBPROCESS pid=M] ← separate process (v2.2.3.2.3)
                      warmup_subprocess.py, own GIL, IDLE priority (v2.2.3.4.0)
                      max_itk_threads=1 (v2.2.3.3.9), results polled via QTimer (100ms)
                      queue_p95_ms dropped from 200-510ms → 0.00ms
```

---

## 2. Current Performance Numbers (v2.2.3.4.0, PC A)

### Mode A — No download active

| What | Metric | Value | Target |
|---|---|---|---|
| Scroll response (typical) | `set_slice_p50_ms` | ~17–42ms | <20ms |
| Scroll response (95th pct) | `set_slice_p95_ms` | ~45–83ms | <35ms |
| Scroll response (worst) | `set_slice_max_ms` | ~60–98ms | <80ms |
| Event queue delay | `queue_p95_ms` | **0.00ms** (Mode A, no DL) | <5ms ✅ |
| Scroll frame interval | frame-to-frame | ~85–116ms (~10fps sw GL) | — |
| Series load, cold (MR 20sl) | `load_single_series_total` | 1.2–1.9s (cold) | <1000ms |
| Series load, ZetaBoost hit | `load_single_series_total` | ~200ms | <300ms ✅ |
| ITK filter, MR ~20sl | `apply_filters duration_ms` | 150–500ms (interactive, 6t) | <500ms |
| Sub-timing: SetSlice | VTK `SetSlice()` | 20–35ms | — |
| Sub-timing: Render | VTK `Render()` | 7–14ms | — |

### Mode B — Download active (DL_WARMUP running in subprocess)

| What | Metric | Value | Target |
|---|---|---|---|
| Scroll response (typical) | `set_slice_p50_ms` | ~35ms (expected v2.2.3.4.0, was ~45ms) | <25ms |
| Scroll response (95th pct) | `set_slice_p95_ms` | ~45ms (expected, was ~61ms) | <50ms |
| Queue delay during DL (scroll) | `queue_p95_ms` | **0.00ms** (subprocess DL_WARMUP, v2.2.3.2.3) | <30ms ✅ |
| Queue delay during DL (signals) | `queue_p95_ms` | 620–5437ms → **<200ms** (v2.2.3.2.6 coalescing) | <30ms — **mitigated** |
| Stale-event drain (v2.2.3.2.1) | `stale_drain_complete skipped=N` | N events skipped, 1 render | eliminates 4s+ backlog ✅ |
| DL_WARMUP per-series (large MR) | `[DL_WARMUP_SUB] ✓ Cached` | ~402ms (subprocess, v2.2.3.2.3) | <2000ms ✅ |
| DL_WARMUP per-series (small MR) | `[DL_WARMUP_SUB] ✓ Cached` | ~200–500ms | <1200ms ✅ |
| DB insert (download subprocess) | `batch_insert_instances_total` | 6–455ms (was 2217ms) | <500ms ✅ |
| First-series GIL pressure | ITK threads + pydicom workers | **2+2** (v2.2.3.2.4, was N+8) | low contention ✅ |
| Series switch (VTK data mapping) | `switch_series()` | ~718ms (once, not per-scroll) | — |
| Subprocess warmup priority | OS priority class | **IDLE** (v2.2.3.4.0, was BELOW_NORMAL) | minimal contention ✅ |
| Camera save/restore on scroll | per-frame overhead | **0ms** (v2.2.3.4.0, skipped) | was ~3-5ms |
| Lock Sync during scroll | callback rate | **≤10/sec** (v2.2.3.4.0, 100ms throttle) | was every frame |

---

## 3. What Was Fixed (Most Recent First)

| Version | Symptom Fixed | How |
|---|---|---|
| **v2.2.3.4.0** | 5-15ms per-frame overhead in set_slice during wheel scroll (camera save/restore, style update, Lock Sync) + subprocess warmup memory-bus contention | Wheel-scroll fast-path: skip camera zoom save/restore (~3-5ms), skip interactor style update (~1ms), throttle Lock Sync to 100ms; subprocess priority BELOW_NORMAL→IDLE |
| **v2.2.3.3.9** | Mode B scroll lag from warmup subprocess contention (ITK 2 threads + unthrottled result poll + frequent notify) | Subprocess ITK threads 2→1; defer poll during scroll (idle<300ms); max 1 result/tick; notify throttle 500→250ms |
| **v2.2.3.3.8** | Size-mismatch false positives during active downloads triggering warmup retries | Compare against DB expected count, not just cached data |
| **v2.2.3.3.7** | Reference line repaint blocking scroll loop (N×20ms per tick) | Round-robin: paint ONE target viewer per tick; scroll-end repaints ALL targets |
| **v2.2.3.3.6** | Ref-line Render() called during scroll loop blocking main thread | Trailing-edge uses geometry-only update (repaint=False); actual Render deferred to scroll-end |
| **v2.2.3.3.5** | Reference lines lagging behind scroll (only updating on trailing edge) | Dual-timer: leading-edge immediate geometry-only + trailing-edge 50ms with repaint |
| **v2.2.3.3.4** | Reference lines stale during lock sync drag | Ref-line update fires after lock sync completes; debounced at 80ms |
| **v2.2.3.3.3** | _update_reference_lines() Render on every scroll frame (~20-40ms) | Debounced via `_schedule_reference_line_update()` with 80ms trailing-edge QTimer |
| **v2.2.3.3.2** | 660ms periodic lag on PC B (500ms GC timer + 150ms GC collection) | GC re-enable timer 500→2000ms; keep elevated thresholds on re-enable; save originals only once |
| **v2.2.3.3.1** | 100-300ms stalls from event-loop congestion between download signals | Cache `os.getenv` in `__init__` (was 3-5ms/call ×2/frame); bypass coalesce timer when gap expired |
| **v2.2.3.3.0** | Sporadic 400-660ms GC stalls on PC B during heavy volume scroll | Strengthened GC suppression: longer timer, elevated thresholds kept on re-enable |
| **v2.2.3.2.9** | Sporadic ~100–400ms freezes during smooth scrolling (Python GC pauses) | GC suppressed during scroll bursts (`gc.disable()`), re-enabled 300ms after last render with soft gen-0 collect; ImageSliceBooster `on_slice_changed` throttled to once per 200ms (was every render) |
| **v2.2.3.2.8** | Scroll debounce added 16ms latency to EVERY frame, ~5–8fps on sw GL | Adaptive THROTTLE replaces debounce: immediate render on first scroll, paced subsequent renders with adaptive gap (25% of frame time); skip redundant per-event ruler/border/camera checks; throttle `notify_viewer_interaction` to once per 500ms |
| **v2.2.3.2.7** | Infinite stale-drain re-arm loop froze UI for 44s+; gRPC on main thread; viewer creation starvation | Fixed re-arm loop in `_flush_pending_wheel_slice` (reset `_last_scroll_event_ms` on each flush); `processEvents()` yield between viewer creations; gRPC offloaded to `asyncio.to_thread` |
| **v2.2.3.2.6** | SERIES_DOWNLOAD_COMPLETE signals fire back-to-back, blocking Qt event loop 620–5437ms | Coalesced `on_series_completed` handler in `home_ui.py`: first series immediate, rest batched with 100ms debounce + processEvents yield every 2 series; added `processEvents()` yield after first-series viewer init in controller |
| **v2.2.3.2.5** | VTK render overhead on software OpenGL: FXAA +20-50ms/frame, MSAA 8x, redundant `color_mapper.Update()` on scroll | FXAA off (`renderer.UseFXAAOff()`); `SetMultiSamples(0)`; skip `color_mapper.Update()` on default-WL scroll path (Render() auto-updates); sub-timing instrumentation in `set_slice` |
| **v2.2.3.2.4** | First-series load floods GIL (unlimited ITK threads + 8 pydicom workers in viewer process) | `max_itk_threads=2, max_pydicom_workers=2` for in-process first-series load; `process_series_groups` yields 50ms→5ms |
| **v2.2.3.2.3** | DL_WARMUP thread in viewer process causes 200–510ms `queue_p95_ms` during scroll | Moved DL_WARMUP to `multiprocessing.Process` (own GIL); results polled via QTimer 100ms; `queue_p95_ms` → **0.00ms** |
| **v2.2.3.2.2** | DL_WARMUP taking 4s per large MR series | `max_itk_threads=1→2`, delay 3.0→1.5s, max_parallel_loads 1→2 |
| **v2.2.3.2.1** | Scroll backlog: 84 events × 50ms = 4s freeze after any main-thread block | Stale-event drain guard: skip render when queue_delay>500ms, 1 render at final pos |
| **v2.2.3.2.0** | Download DB insert 2217ms (serial pydicom); ITK scroll spikes during filter | Parallel asyncio pydicom; adaptive threads + BELOW_NORMAL OS priority |
| **v2.2.3.1.9** | Viewer-side instance creation 4.3s (330-file CT) | Parallel pydicom via ThreadPoolExecutor on viewer path |
| **v2.2.3.1.8** | Series switch 1.4s overhead | Skip redundant `SetInputData` when reslice output already connected |
| **v2.2.3.1.8p1** | Download subprocess competing with VTK render | Download subprocess → BELOW_NORMAL Windows priority |
| **v2.2.3.1.6** | `apply_filters` 423ms due to repeated int16↔float32 casts | Cast-once to float32 before all stages; cast back once at end |
| **v2.2.3.0.8** | MR mild_mode filter 29s on first load | 2 threads + 2 sigmas + skip adaptive sharpening on thick slices |
| **v2.2.3.0.5** | 14–17s event_queue_delay after series switch | Clear stale `_last_scroll_event_ms` on `switch_series` |

---

## 4. Open Issues (Ranked)

### 🟡 P1 — First-series in-process load still ~2.4s
- v2.2.3.2.4 caps threads+workers to 2+2, reducing GIL contention during the load
- But the load itself still runs in the viewer process via `asyncio.to_thread()`
- **Ideal fix:** Route first-series through the warmup subprocess too (eliminates ALL in-process GIL contention during Mode B first-series load)
- **Complexity:** Subprocess must load → serialize result → QTimer polls → `_display_first_series_in_all_viewers()` — requires refactoring display path

### 🟡 P2 — `update_corners_actors()` runs 6+ VTK text updates per scroll
- Currently does metadata dict lookups + string formatting + 6 `change_actor_text()` calls on every scroll frame
- Only `im_slice_actor` and `im_series_window_level` actually change per-scroll; others (date, series name, thickness, size) are constant within a series
- **Next step:** Split into `_update_scroll_varying_actors()` (slice count + WL only) and `_update_series_constant_actors()` (called once on series switch)
- **Expected savings:** ~5-10ms per scroll frame on software-GL renderer

### 🟡 P3 — `viewer_db_read` (38–88ms) on every series load
- DB query runs on worker thread so it doesn't block scroll, but adds to perceived load time
- **Next step:** After study download, cache series_pk and instance paths in a simple dict — eliminates DB query on repeated open

### 🟡 P4 — Lock Sync callback runs coordinate math on every scroll
- `_do_lock_sync()` in patient_widget.py does IPP interpolation + applies to target viewers on every slice change when Lock Sync is enabled
- Consider debouncing to every 2nd or 3rd scroll event (user won't notice 1-frame delay in synced viewer)

### 🟢 P5 — ITK→VTK convert 11–44ms on large series
- `itk_to_vtk_convert` duration grows with size (500×640×24 ≈ 44ms)
- ITK stores as `[Z, Y, X]` C array → VTK needs `[X, Y, Z]` Fortran; currently always copies
- **Next step:** Check if `vtk.util.numpy_support.numpy_to_vtk(ravel_order='F')` avoids copy

### ✅ Resolved — Mode B queue delay (was P1)
- v2.2.3.2.6 coalesces `SERIES_DOWNLOAD_COMPLETE` signals (100ms debounce, processEvents yield)
- Measured `queue_p95_ms` = **0.00ms** in v2.2.3.2.8 logs — fully resolved

### ✅ Resolved — Sporadic GC stutters (was P0 in v2.2.3.2.8)
- ~338ms gaps observed with zero main-thread activity → Python GC gen-1/gen-2 pauses
- v2.2.3.2.9 suppresses GC during scroll bursts, re-enables 300ms after last render

### ✅ Resolved — Infinite stale-drain loop (was P0 in v2.2.3.2.6)
- `_flush_pending_wheel_slice` re-armed indefinitely because `_last_scroll_event_ms` wasn't reset
- v2.2.3.2.7 resets timestamp on each flush, breaking the loop

### ✅ Resolved — Debounce latency (was P0 in v2.2.3.2.7)
- Every wheel event restarted 16ms timer → added 16ms latency to every frame
- v2.2.3.2.8 replaced with adaptive throttle: 0ms first-scroll, paced subsequent renders
---

## 5. Key Files

| File | Purpose |
|---|---|
| `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget.py` | VTK viewer widget, scroll events, stale-drain guard, series switch |
| `PacsClient/pacs/patient_tab/utils/image_filters.py` | ITK filter chain, adaptive threads, BELOW_NORMAL priority |
| `PacsClient/pacs/patient_tab/utils/image_io.py` | Series load pipeline: DB path, disk read, ITK, VTK conversion |
| `PacsClient/pacs/patient_tab/utils/utils.py` | `get_or_create_instance` — parallel pydicom reads (viewer side) |
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` | ZetaBoost engine, DL_WARMUP subprocess integration, RAM tier config |
| `PacsClient/pacs/patient_tab/zeta_boost/warmup_subprocess.py` | **NEW v2.2.3.2.3** — GIL-free DL_WARMUP in separate process (`multiprocessing.Process`) |
| `PacsClient/zeta_download_manager/download/series_downloader.py` | Download pydicom reads, DB batch insert (download subprocess) |
| `PacsClient/zeta_download_manager/network/socket_client.py` | DICOM server communication |

---

## 6. Environment Tuning Knobs

| Variable | Default | Effect |
|---|---|---|
| `AIPACS_DL_WARMUP_MAX_CACHED` | `4` | Max series DL_WARMUP pre-caches per download session |
| `AIPACS_DL_WARMUP_MAX_SLICES` | `200` | Skip series with more slices than this |
| `AIPACS_DL_WARMUP_INTER_DELAY` | `1.5` | Seconds between DL_WARMUP jobs (v2.2.3.2.2: was 3.0) |
| `AIPACS_DL_WARMUP_SUBPROCESS` | `1` | Enable subprocess-based DL_WARMUP (v2.2.3.2.3; set 0 to fall back to in-process thread) |
| `AIPACS_SCROLL_COALESCE_MS` | `16` | Scroll coalesce timer interval (ms); adaptive throttle overrides during burst |
| `AIPACS_SCROLL_LAG_PROBE_ENABLED` | `1` | Enable/disable scroll performance probe |
| `AIPACS_SCROLL_LAG_PROBE_WINDOW_SEC` | `12` | Scroll probe measurement window (seconds) |
| `AIPACS_VIEWER_TIMING_MIN_MS` | `35` | Only log scroll timings ≥ this threshold |
| `AIPACS_VIEWER_TIMING_SAMPLE_EVERY` | `25` | Sample normal-speed scroll events 1-in-N |
| `AIPACS_LOG_MAX_BYTES` | `20971520` | Rotating log file max size (20MB) |
| `AIPACS_LOG_BACKUP_COUNT` | `3` | Number of log file backups to keep |

---

## 7. Test Sequence (Quick Validation)

```
1. Pull latest DR.vahid on both PC A and PC B
2. python main.py → log in → select a new study (not yet downloaded)
3. Observe: first series opens in < 3s, subsequent series < 2s (DL_WARMUP pre-caching)
4. Scroll series — check no freeze during download (stale drain guard active)
5. Wait for download to complete → open ZetaBoost warmup phase
6. Switch between all series — each should load in < 300ms (ZetaBoost L1 hit)
7. Grab log file → run extract commands from METRICS_TRACKING_v2.2.3.x.md §13
8. Fill in PC A / PC B columns and compare
```

---

## 8. Cross-PC Improvement Cycle

See `docs/CROSS_PC_IMPROVEMENT_WORKFLOW.md` for the full PC A → GitHub → PC B → compare cycle.

**Stable backup:** `backups/v2.2.2_2026-02-19/` (pre-optimization baseline; safe rollback point)
