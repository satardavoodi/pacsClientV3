# AIPacs Performance Status
**Version:** v2.2.3.2.2 | **Branch:** DR.vahid | **Updated:** 2026-02-27

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
                 ├─ ZETA BOOST WARMUP (background, post-download)
                 │    lane=warmup, 2 workers, max_parallel_loads=2 (8GB+)
                 │    max_itk_threads=2, BELOW_NORMAL OS priority
                 │
                 └─ DL_WARMUP (background, DURING download)
                      1 worker thread, IDLE OS priority
                      max_itk_threads=2 (v2.2.3.2.2), inter-delay=1.5s
```

---

## 2. Current Performance Numbers (v2.2.3.2.2, PC A, MR brain study)

### Mode A — No download active

| What | Metric | Value | Target |
|---|---|---|---|
| Scroll response (typical) | `set_slice_p50_ms` | ~18–31ms | <20ms |
| Scroll response (95th pct) | `set_slice_p95_ms` | ~28–59ms | <35ms |
| Scroll response (worst) | `set_slice_max_ms` | ~62–83ms | <80ms |
| Event queue delay | `queue_p95_ms` | **<5ms** (Mode A, no DL) | <5ms ✅ |
| Series load, cold (MR 20sl) | `load_single_series_total` | 1.2–1.9s (cold) | <1000ms |
| Series load, ZetaBoost hit | `load_single_series_total` | ~200ms | <300ms ✅ |
| ITK filter, MR ~20sl | `apply_filters duration_ms` | 150–500ms (interactive, 6t) | <500ms |

### Mode B — Download active (DL_WARMUP running)

| What | Metric | Value | Target |
|---|---|---|---|
| Scroll response (typical) | `set_slice_p50_ms` | ~31–57ms | <25ms (hard floor: SQLite I/O) |
| Queue delay during DL | `queue_p95_ms` | 80–3500ms bursts (signals) | <30ms — **partially open** |
| Stale-event drain (v2.2.3.2.1) | `stale_drain_complete skipped=N` | N events skipped, 1 render | eliminates 4s+ backlog ✅ |
| DL_WARMUP per-series (large MR) | `[DL_WARMUP] ✓ Cached` | ~4s (v2.2.3.2.1) → ~2s (v2.2.3.2.2) | <2000ms |
| DL_WARMUP per-series (small MR) | `[DL_WARMUP] ✓ Cached` | ~700–1200ms | <1200ms |
| DB insert (download subprocess) | `batch_insert_instances_total` | 6–455ms (was 2217ms) | <500ms ✅ |
| Instance create (viewer side) | `Instance create` | 0.36–0.8s (was 4.3s) | <1s ✅ |

---

## 3. What Was Fixed (Most Recent First)

| Version | Symptom Fixed | How |
|---|---|---|
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

### 🔴 P1 — Mode B queue delay still spikes on download signals
- `queue_delay_ms` reaches 2.8–3.6s during `SERIES_DOWNLOAD_COMPLETE` signal handling
- v2.2.3.2.1 stale guard drains the resulting backlog in <1ms but the signal handlers themselves still block the queue
- **Root cause:** DB pool_lock_wait calls and study-save sequence run on Qt main thread
- **Next step:** Profile which specific SERIES_DOWNLOAD_COMPLETE callback holds the main thread longest; offload to `asyncio.get_event_loop().run_in_executor` or a dedicated saver coroutine

### 🟡 P2 — ITK large-FOV MR filter still ~1.5s at 2 threads
- 500×640×24 slices MR: `apply_filters` = ~1.5s with `threads=2`
- Slowing DL_WARMUP even after v2.2.3.2.2
- **Next step:** Investigate `_smooth_xy_recursive` per-slice loop — currently N=24 sequential SimpleITK calls on float32 500×640 planes; consider batch via numpy

### 🟡 P3 — `viewer_db_read` (38–88ms) on every series load
- DB query runs on worker thread so it doesn't block scroll, but adds to perceived load time
- **Next step:** After study download, cache series_pk and instance paths in a simple dict — eliminates DB query on repeated open

### 🟢 P4 — ITK→VTK convert 11–44ms on large series
- `itk_to_vtk_convert` duration grows with size (500×640×24 ≈ 44ms)
- ITK stores as `[Z, Y, X]` C array → VTK needs `[X, Y, Z]` Fortran; currently always copies
- **Next step:** Check if `vtk.util.numpy_support.numpy_to_vtk(ravel_order='F')` avoids copy

---

## 5. Key Files

| File | Purpose |
|---|---|
| `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget.py` | VTK viewer widget, scroll events, stale-drain guard, series switch |
| `PacsClient/pacs/patient_tab/utils/image_filters.py` | ITK filter chain, adaptive threads, BELOW_NORMAL priority |
| `PacsClient/pacs/patient_tab/utils/image_io.py` | Series load pipeline: DB path, disk read, ITK, VTK conversion |
| `PacsClient/pacs/patient_tab/utils/utils.py` | `get_or_create_instance` — parallel pydicom reads (viewer side) |
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` | ZetaBoost engine, DL_WARMUP worker, RAM tier config |
| `PacsClient/zeta_download_manager/download/series_downloader.py` | Download pydicom reads, DB batch insert (download subprocess) |
| `PacsClient/zeta_download_manager/network/socket_client.py` | DICOM server communication |

---

## 6. Environment Tuning Knobs

| Variable | Default | Effect |
|---|---|---|
| `AIPACS_DL_WARMUP_MAX_CACHED` | `4` | Max series DL_WARMUP pre-caches per download session |
| `AIPACS_DL_WARMUP_MAX_SLICES` | `200` | Skip series with more slices than this |
| `AIPACS_DL_WARMUP_INTER_DELAY` | `1.5` | Seconds between DL_WARMUP jobs (v2.2.3.2.2: was 3.0) |
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
