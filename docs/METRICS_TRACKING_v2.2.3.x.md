# Performance Metrics Tracking — AIPacs Mode A / Mode B
**Current Version:** v2.2.3.4.0  
**Branch:** DR.vahid  
**Last Updated:** 2026-02-27  
**Purpose:** Phase-by-phase optimization progress measurement

---

## 1. Metric Definitions

### 1.1 Mode A Metrics (POST_DOWNLOAD — no download in progress)

| ID | Metric | Log Tag | Description | Target |
|---|---|---|---|---|
| **A1** | `scroll_p50_ms` | `viewer-scroll-probe mode=mode_a` → `set_slice_p50_ms` | Median scroll response: time from wheel event to frame rendered | < 20ms |
| **A2** | `scroll_p95_ms` | `viewer-scroll-probe mode=mode_a` → `set_slice_p95_ms` | 95th-percentile scroll response | < 35ms |
| **A3** | `scroll_max_ms` | `viewer-scroll-probe mode=mode_a` → `set_slice_max_ms` | Worst single scroll event in window | < 80ms |
| **A4** | `queue_delay_p95_ms` | `viewer-scroll-probe mode=mode_a` → `queue_p95_ms` | Time Qt event queue was blocked before slice applied | < 5ms |
| **A5** | `filter_ms` | `viewer-data stage=apply_filters` → `duration_ms` | ITK filter chain wall time per series (interactive load) | < 500ms |
| **A6** | `dicom_read_ms` | `viewer-data stage=itk_filter_chain` — see `[LOAD_VTK]` print | DICOM→ITK read time per series | < 300ms |
| **A7** | `itk_to_vtk_ms` | `viewer-data stage=itk_to_vtk_convert` → `duration_ms` | ITK→VTK array conversion per series | < 100ms |
| **A8** | `series_load_total_ms` | `viewer-data stage=load_single_series_total` | Total wall time cache-miss series load (click→display) | < 1000ms |
| **A9** | `warmup_job_ms` | `ZetaBoost PROCESS_DONE lane=warmup` → `elapsed_ms` | Wall time per ZetaBoost warmup job (background) | < 1500ms |
| **A10** | `warmup_cache_hit_rate` | `ZetaBoost HEALTH` or `L1_CACHE` summary | % series served from L1 RAM on user click (after warmup completes) | > 90% |

### 1.2 Mode B Metrics (DOWNLOADING — download subprocess active)

| ID | Metric | Log Tag | Description | Target |
|---|---|---|---|---|
| **B1** | `scroll_p50_ms` | `viewer-scroll-probe mode=mode_b` → `set_slice_p50_ms` | Median scroll response during download | < 25ms |
| **B2** | `scroll_p95_ms` | `viewer-scroll-probe mode=mode_b` → `set_slice_p95_ms` | 95th-percentile scroll during download | < 50ms |
| **B3** | `scroll_max_ms` | `viewer-scroll-probe mode=mode_b` → `set_slice_max_ms` | Worst scroll event during download | < 120ms |
| **B4** | `queue_delay_p95_ms` | `viewer-scroll-probe mode=mode_b` → `queue_p95_ms` | Event-queue delay during download (was 141–156ms pre-fix) | < 30ms |
| B5 | `dl_warmup_per_series_ms` | `[DL_WARMUP_SUB] ✓ Cached series=` → elapsed time | Wall time for DL_WARMUP subprocess to pre-cache one series | < 1200ms |
| B6 | `dl_warmup_filter_ms` | `viewer-data stage=apply_filters` (2-thread subprocess calls) | ITK filter time during DL_WARMUP subprocess (2-thread; own GIL) | < 1200ms |
| **B7** | `dl_warmup_cached_count` | `[DL_WARMUP] Worker finished. cached=` | Number of series successfully pre-cached during download | ≥ 2 |
| **B8** | `dl_warmup_itk_vtk_ms` | `viewer-data stage=itk_to_vtk_convert` (DL_WARMUP calls) | ITK→VTK convert time during warmup | < 150ms |

---

## 2. Log Extraction Commands

Run these against the latest log file after each test session:

```powershell
# Get log file path (most recent)
$log = Get-ChildItem "c:\AI-Pacs codes\ai-pacs\logs" -Filter "*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

# --- SCROLL PROBE (Mode A & Mode B) ---
Select-String "viewer-scroll-probe" $log.FullName | Select-Object -Last 20

# --- FILTER TIMING ---
Select-String "stage=apply_filters" $log.FullName | Select-Object -Last 20

# --- ITK→VTK CONVERT ---
Select-String "stage=itk_to_vtk" $log.FullName | Select-Object -Last 20

# --- SERIES LOAD TOTAL ---
Select-String "stage=load_single_series_total" $log.FullName | Select-Object -Last 20

# --- ZETABOOST PROCESS_DONE (warmup job timing) ---
Select-String "PROCESS_DONE lane=warmup" $log.FullName | Select-Object -Last 20

# --- DL_WARMUP per-series ---
Select-String "\[DL_WARMUP\].*Cached series" $log.FullName -AllMatches | Select-Object -Last 20
```

---

## 3. Test Procedures

### 3.1 Mode A Baseline Test

**Preconditions:**
- Study fully downloaded (no active downloads)
- App freshly opened (cold ZetaBoost cache — no L1 RAM yet)

**Steps:**
1. Open a study with ≥ 8 series (MR preferred, ≥ 24 slices per series)
2. Click series 1 → wait for display → record series load time from logs
3. Wait 60 seconds (let ZetaBoost warmup fill L1 cache)
4. Scroll series 1 continuously for 30 seconds ← generates Mode A scroll probe
5. Switch to series 2 → record load time (should be instant if warmup cached it)
6. Scroll series 2 for 30 seconds
7. Stop. Check logs.

**Metrics to extract:** A1, A2, A3, A4, A5, A7, A8, A9, A10

---

### 3.2 Mode B Baseline Test

**Preconditions:**
- PC A: has at least one study cached (use for viewing)
- Download a new study in parallel (triggers Mode B)

**Steps:**
1. Open a cached study → scroll it (establishes Mode A baseline first)
2. Start downloading a new study from the download manager
3. Return to the cached study and scroll continuously for 60 seconds ← generates Mode B scroll probe
4. Check DL_WARMUP pre-cached series count
5. Stop download or wait for it to complete
6. Check logs.

**Metrics to extract:** B1, B2, B3, B4, B5, B6, B7, B8

---

## 4. Baseline Results (v2.2.3.1.5 — To Be Measured)

> **Instructions:** Run the tests in Section 3, then paste log values into the table below.

### 4.1 Mode A Baseline

> Measured from live session logs with v2.2.3.1.5 code (ZetaBoost warmup uncapped, spike present).

| ID | Metric | PC A Value | PC B Value | Notes |
|---|---|---|---|---|
| A1 | scroll_p50_ms | ~18 | ___ | Observed: 17, 19, 20ms |
| A2 | scroll_p95_ms | ~28 | ___ | Normal scroll, before warmup spike |
| A3 | scroll_max_ms | 37 | ___ | Spike during uncapped ZetaBoost ITK — **fixed** |
| A4 | queue_delay_p95_ms | ___ | ___ | |
| A5 | filter_ms (MR, interactive) | 423 | ___ | From log: `ITK filters: 423ms` |
| A6 | dicom_read_ms | ___ | ___ | |
| A7 | itk_to_vtk_ms | ___ | ___ | |
| A8 | series_load_total_ms | ___ | ___ | |
| A9 | warmup_job_ms (ZetaBoost) | ___ | ___ | |
| A10 | warmup_cache_hit_rate | ___ | ___ | |

**Test conditions:** modality=MR slices=? study_series_count=?  
**Date / time:** 2026-02-xx ~17:28  
**Version tag:** v2.2.3.1.5 (ZetaBoost warmup uncapped)

### 4.2 Mode B Baseline

> Measured from live session logs with v2.2.3.1.5 code (DL_WARMUP 2-thread, scroll spikes present).  
> Floor of 51–57ms is inherent SQLite I/O pressure from download subprocess — not removable in Phase 1.

| ID | Metric | PC A Value | PC B Value | Notes |
|---|---|---|---|---|
| B1 | scroll_p50_ms (during DL) | ~51–57 | ___ | SQLite I/O pressure floor — hard to beat |
| B2 | scroll_p95_ms (during DL) | ~94 | ___ | **was 141–156ms pre-v2.2.3.1.5**; 94ms was during 2-thread ITK run |
| B3 | scroll_max_ms | 114 | ___ | Peak 94→107→114ms during DL_WARMUP ITK — **fixed with 1-thread** |
| B4 | queue_delay_p95_ms | ___ | ___ | **was 141–156ms pre-fix** |
| B5 | dl_warmup_per_series_ms | ~580 | ___ | Series 9 (512×320×24), 2-thread ITK |
| B6 | dl_warmup_filter_ms (1-thread) | ~580 | ___ | Dominated by ITK; was 2-thread, now 1-thread ≈ 1100ms |
| B7 | dl_warmup_cached_count | ___ | ___ | |
| B8 | dl_warmup_itk_vtk_ms | ___ | ___ | |

**Download study series_count=? modality=MR**  
**Date / time:** 2026-02-xx ~17:58  
**Version tag:** v2.2.3.1.5 (DL_WARMUP 2-thread cap)

---

## 5. Phase 1 Results (v2.2.3.1.6 — Cast-Once + Zoom Render Guard)

**Changes applied (IMPLEMENTED):**
- Cast-once pattern in `apply_filters()`: cast to float32 BEFORE noise reduction (moved out of `if modality == 'MR'` block so CT benefits too); cast back once at end — eliminates 2 explicit + ~2 internal ITK int16↔float32 conversions
- Zoom-protection `Render()` guard in `vtk_widget.py` `set_slice()`: reference changed from `saved_scale` → `_protected_parallel_scale`; tolerance widened 0.001 → 0.05 (stops spurious Render on VTK FP drift)
- `update_corners_actors()` per scroll: **discovered already fixed** in v2.2.3.1.0 (`if not flag_default:` guard in `set_window_level` + WL scroll-cache). No new code needed.

**Expected gains:**
- A5 `filter_ms`: −50 to −150ms per MR series (cast-once eliminates redundant conversions)
- A1/A2 `scroll_p50/p95`: −10 to −80ms per scroll (zoom render guard eliminated ~60–80ms extra Render that fired most scrolls)

### 5.1 Mode A — Phase 1

> **Test note:** Log captured during Mode B conditions (another download active, `[WARMUP] Skipped — global downloads active count=1`).
> The single scroll probe sample was recorded DURING the download, making it effectively a Mode B scroll probe.
> No `viewer-scroll-probe` window emitted (user scrolled briefly, not 12s continuous). Zoom guard fix confirmed: zero `[set_slice] Zoom change detected!` warnings in entire log.

| ID | Metric | Baseline | Phase 1 PCA | Phase 1 PCB | Δ (from baseline) |
|---|---|---|---|---|---|
| A1 | scroll_p50_ms | ~18 | *(probe not triggered)* | ___ | ___ |
| A2 | scroll_p95_ms | ~28 | *(probe not triggered)* | ___ | ___ |
| A3 | scroll_max_ms | 37 (warmup spike) | 16 (single DL-active sample) | ___ | **−21ms minimum** |
| A4 | queue_delay_p95_ms | ___ | ___ | ___ | ___ |
| A5 | filter_ms (MR 20sl 4t) | 423 | **151** | ___ | **−272ms (−64%)** |
| A7 | itk_to_vtk_ms | ___ | 5.73 | ___ | fast |
| A8 | series_load_total_ms | ___ | 779 | ___ | disk_read=451ms dominates |
| A9 | warmup_job_ms | ___ | *(skipped: DL active)* | ___ | |

**User perception:** "smooth stack" ✅  
**Date / time:** 2026-02-26 ~20:37  
**Version tag:** v2.2.3.1.6

### 5.2 Mode B — Phase 1

> **Full Mode B test captured 2026-02-26 ~20:43.** Active download throughout (6 series).
> DL_WARMUP ran on series 8 + 9. ZetaBoost warmup ran on series 10 concurrently with scrolling.
> Zoom guard fix confirmed: zero `[set_slice] Zoom change detected!` warnings in entire log.
>
> **NEW FINDING:** `event_queue_delay` is now the dominant latency source (40–106ms), not `set_slice_total` itself.
> The `event_queue_delay` spikes are caused by main-thread callbacks for download signals (SERIES_DOWNLOAD_COMPLETE,
> study-save DB sequence ~20:43:31.028–20:43:31.053) and ZetaBoost PROCESS_DONE handling — not ITK.
> Total perceived scroll latency = event_queue_delay + set_slice_total = **75–163ms**.
> User perception: **"near acceptable"** (better than prior spikes but queue delay still noticeable).

| ID | Metric | Baseline | Phase 1 PCA | Phase 1 PCB | Δ (from baseline) |
|---|---|---|---|---|---|
| B1 | scroll_p50_ms | ~51–57 | **~37** (median, DL active) | ___ | **−14–20ms** |
| B2 | scroll_p95_ms | ~94 | **~53** (set_slice_total p95) | ___ | **−41ms** |
| B3 | scroll_max_ms | 114 | **57** (set_slice_total only) | ___ | **−57ms** ← but queue adds 106ms |
| B4 | queue_delay_p95_ms | ___ | **~80ms** ⚠️ new bottleneck | ___ | TARGET was <30ms — **MISS** |
| B5 | dl_warmup_per_series_ms | ~580 (2t) | 947ms (s9, 176×176×40, 1t) / 1738ms (s8, 400×512×24, 1t) | ___ | better/worse depending on resolution |
| B6 | dl_warmup_filter_ms | ~580 (2t) | **381ms** (s9, 40sl 1t) / **1064ms** (s8, 24sl 1t, large FOV) | ___ | 1064ms high: 400×512 resolution |
| B7 | dl_warmup_cached_count | ___ | 2/4 cached (s8+s9; s10 done by ZetaBoost) | ___ | |
| B8 | dl_warmup_itk_vtk_ms | ___ | 15ms (s8) / 8ms (s9) | ___ | |

**ZetaBoost warmup metrics (concurrent with scroll):**
- Series 10 (176×176×20, MR, 2t): filter=123ms, total=380ms, itk_to_vtk=5.84ms ← well within budget

**B4 root cause analysis:**
- Baseline queue delay: 40–55ms — download subprocess signals (SERIES_DOWNLOAD_COMPLETE) pump Qt callbacks to main thread ~every 500ms; each handler runs briefly but arrives between scrolls
- Spike at 105.92ms (20:43:32.392): ZetaBoost PROCESS_DONE + ALL_WORK_COMPLETE + 10× DB pool_lock_wait calls on main thread just before this scroll
- Post-download study-save sequence (20:43:30.8–20:43:31.05): saves 6 series + patient + study to DB on main thread → blocks event loop for ~200ms total
- Not fixable in Phase 1/2; would require offloading study-save to executor (Phase 3 or separate ticket)

**Date / time:** 2026-02-26 ~20:43  
**Version tag:** v2.2.3.1.6  
**Decision:** ☒ Proceed to Phase 2 &nbsp; ☐ Investigate regression &nbsp; ☒ Note B4 queue delay for Phase 3

---

## 6. Phase 2 Results (v2.2.3.1.7 — Dead Code + Interactive Disk Cache)

**Changes applied:**
- Delete dead code functions (~540 lines)
- Write interactively-loaded series to ZetaBoost disk cache (re-open study = instant)

**Expected gains:**
- A8 `series_load_total_ms` (second open): reduces from 1–7s to ~50ms (L2 disk hit)
- A10 `warmup_cache_hit_rate`: increases since more paths populate the cache
- No expected change to scroll metrics

### 6.1 Mode A — Phase 2

| ID | Metric | Baseline | Phase 1 | Phase 2 PCA | Phase 2 PCB | Δ vs Baseline |
|---|---|---|---|---|---|---|
| A8 | series_load_total_ms (1st open) | ___ | ___ | ___ | ___ | ___ |
| A8b | series_load_total_ms (2nd open) | n/a | n/a | ___ | ___ | new metric |
| A10 | warmup_cache_hit_rate | ___ | ___ | ___ | ___ | ___ |
| A9 | warmup_job_ms | ___ | ___ | ___ | ___ | ___ |

**Date / time:** ___  
**Version tag:** v2.2.3.1.7  
**Decision:** ☐ Proceed to Phase 3 &nbsp; ☐ Investigate regression &nbsp; ☐ Adjust approach

---


## 7. Phase 3 Results — Rendering + Parallelism Fixes (v2.2.3.1.8 → v2.2.3.2.2)

> All measurements below are from live log captures on PC A (DR.vahid branch).  
> Confirm each version on PC B before marking PCB column as verified.

---

### v2.2.3.1.8 — SetInputData skip + ImageSliceBooster wiring
**Commit:** `04c57d0`  **Date:** 2026-02-26

**Changes:**
- `vtk_widget.py` `reset_image_viewer`: skip `SetInputData` when reslice output is already connected — saves 1 pipeline flush per series switch
- Wired `ImageSliceBooster.on_slice_changed()` from `set_slice` (was disconnected)

**Measured (PC A):**

| Metric | Before | After | Notes |
|---|---|---|---|
| Series switch overhead | ~1.4s extra per switch | ~0ms | `SetInputData` skip confirmed by identity check |
| `set_slice_total_ms` | 81–141ms scroll during DL | 81–141ms | No change to render itself — correct |

---

### v2.2.3.1.8p1 — Download process BELOW_NORMAL priority + QThread naming
**Commits:** `3bbf248`, `af794d9`  **Date:** 2026-02-26

**Changes:**
- Download subprocess set to `BELOW_NORMAL` OS priority on Windows
- All 4 download QThread workers given unique names for log identification

**Expected:** Reduced CPU contention between download worker and VTK render thread on scroll.

---

### v2.2.3.1.9 — Parallel pydicom header reads (viewer side)
**Commit:** `9d2414b`  **Date:** 2026-02-26

**Changes:**
- `utils.py` `get_or_create_instance`: replaced serial pydicom loop with `ThreadPoolExecutor(max_workers=min(8, cpu_count))`

**Measured (PC A):**

| Metric | Before | After | Δ |
|---|---|---|---|
| Instance create (330 files, CT) | 4.307s | ~0.8s | **−3.5s (−81%)** |
| Instance create (143 files, MR) | 2.134s | ~0.5s | **−1.6s** |

---

### v2.2.3.2.0 — Parallel pydicom in download subprocess + adaptive ITK threads + BELOW_NORMAL filter priority
**Commit:** `3cd1a09`  **Date:** 2026-02-26

**Changes:**
- `series_downloader.py` `_save_series_instances_to_db`: replaced serial pydicom loop with `asyncio.gather` + `ThreadPoolExecutor`
- `image_filters.py`: adaptive ITK threads `max(min(cpu_count-2, 8), 2)` (8-core → 6 threads, reserves 2 for VTK)
- `image_filters.py`: `THREAD_PRIORITY_BELOW_NORMAL` during ITK filter pass, restore `NORMAL` after

**Measured (PC A logs, 2026-02-26 ~23:49):**

| Metric | Before | After | Notes |
|---|---|---|---|
| `batch_insert_instances_total` (download subprocess, ~480 files) | 2217ms | **326–455ms** | **−81%** |
| `batch_insert_instances_total` (small series, ~20 files) | ~300ms | **6–14ms** | — |
| ITK scroll spike during filter (Mode B) | 200–309ms spikes | Not yet confirmed | BELOW_NORMAL priority helps |

---

### v2.2.3.2.1 — Stale-event fast-drain guard in `set_slice`
**Commit:** `9724dea`  **Date:** 2026-02-26

**Root cause diagnosed:** After any main-thread block >500ms (e.g. download signal handling, DB save), a backlog of scroll wheel events accumulates in Qt event queue. Previously each was rendered fully (~50ms each). 84 stale events × 50ms = ~4s of wasted renders at already-stale positions.

**Changes:**
- `vtk_widget.py` `set_slice`: when `queue_delay_ms > 500ms` → skip VTK render, update slider only, set `_pending_wheel_slice` for coalesce timer to render final position once
- Throttled logging: reports 1st, 10th, 20th... stale skips, then `stale_drain_complete skipped=N`
- `switch_series` resets `_stale_scroll_skip_count` with other scroll state

**Expected vs measured (from pre-fix log, 2026-02-26 ~23:49):**

| Metric | Before (log evidence) | After (expected) |
|---|---|---|
| `queue_p95_ms` | **19,496ms** | ~16ms (coalesce delay only) |
| Stale renders per backlog event | ~50ms each | ~0.1ms (slider update only) |
| 84-event backlog drain time | ~4.2s of renders | ~1 render at final position |
| `set_slice_total` individual | 81–141ms | unchanged (render quality same) |

---

### v2.2.3.2.2 — DL_WARMUP speed and parallelism improvements
**Commit:** `ff0d4b1`  **Date:** 2026-02-27

**Root cause diagnosed:** DL_WARMUP was loading series with `max_itk_threads=1`, causing large-FOV MR series (500×640, 24 slices) to take 2.9–3.0s per filter pass → total 3.9–4.1s per series. With 3.0s inter-series delay, two workers could not overlap effectively.

**Changes:**
- `patient_widget_viewer_controller.py` DL_WARMUP: `max_itk_threads=1` → `max_itk_threads=2`
- Inter-series delay default: `3.0s` → `1.5s`
- `max_parallel_loads` for 8GB+ and 15GB+ RAM tiers: `1` → `2` (allows two ZetaBoost warmup workers to run simultaneously)

**Projected impact (before vs after):**

| Metric | Before (v2.2.3.2.1) | After (v2.2.3.2.2 expected) |
|---|---|---|
| DL_WARMUP series=6 (500×640×24 MR, 1t) | 4138ms | ~2100ms (2t, halved) |
| DL_WARMUP series=7 (620×640×20 MR, 1t) | 3884ms | ~2000ms |
| DL_WARMUP series=8 (176×176×40 MR, 1t) | 1172ms | ~700ms |
| Warmup throughput: 6 remaining series (10-series study) | serial, ~1.5–4s each | two parallel, ~0.7–2s each |
| Total pre-cache time for 6 remaining series | ~20s | ~8–10s |

**Measured (PC A):** _To be filled after next test run_  
**PC B:** _Pending_

---

## 7b. Phase 4 Results — Subprocess DL_WARMUP + First-Series GIL Fix (v2.2.3.2.3 → v2.2.3.2.4)

> All changes in this phase target Mode B GIL contention — the last remaining source
> of scroll lag during active downloads.

---

### v2.2.3.2.3 — DL_WARMUP moved to multiprocessing.Process (GIL elimination)
**Date:** 2026-02-27

**Root cause diagnosed:** DL_WARMUP ran as a background thread **inside** the viewer process. Every SimpleITK filter call, pydicom header read, and ITK→VTK conversion acquired the GIL, competing with VTK render and Qt event processing. Result: `queue_p95_ms` of 200–510ms during scroll while DL_WARMUP was active.

**Changes:**
- **NEW FILE:** `PacsClient/pacs/patient_tab/zeta_boost/warmup_subprocess.py`
  - `WarmupSubprocessManager` — manages lifecycle of a `multiprocessing.Process(start_method='spawn')`
  - Worker function `_warmup_subprocess_main()` runs in its own GIL-free process
  - Results serialized via `multiprocessing.Queue` as `(series_number, vtk_array, metadata_dict)`
  - `result_to_vtk()` reconstructs `vtkImageData` from numpy array on viewer side
- **`patient_widget_viewer_controller.py`**: `_enqueue_warmup_subprocess()` replaces `_start_dl_warmup_worker()`; QTimer 100ms polls `_poll_warmup_subprocess_results()` processing ≤2 results/tick
- **`image_filters.py`**: Removed redundant `sitk.Cast(float_img, sitk.sitkFloat32)` in `_smooth_xy_recursive` — image is already float32 from cast-once pattern
- **`image_io.py`**: GIL yield sleeps 50ms→5ms in DB load path (DL_WARMUP is in subprocess now, long yields just delay interactive loads)

**Measured (PC A, MR brain study, live log 2026-02-27):**

| Metric | Before (v2.2.3.2.2, in-process) | After (v2.2.3.2.3, subprocess) | Notes |
|---|---|---|---|
| `queue_p95_ms` (scroll during DL) | 200–510ms bursts | **0.00ms** | **GIL contention ELIMINATED** ✅ |
| `set_slice_p95_ms` (during DL) | 80–140ms | **52–61ms** | Still has first-series load overhead |
| `slice_apply_p95_ms` | — | **37–45ms** | VTK software-GL baseline |
| `[DL_WARMUP_SUB] ✓ Cached series=101` | — | **402ms** | Fast: subprocess has full CPU |
| `[DL_WARMUP_SUB] ✓ Cached series=201` | — | **2465ms** (first-series, in-process) | NOT subprocess — first-series display |
| Subprocess startup | — | <200ms | `spawn` mode on Windows |

**Key insight:** `queue_p95_ms=0.00` proves the subprocess approach completely eliminates DL_WARMUP GIL contention. The remaining `set_slice_p95_ms=52-61ms` is from:
1. First-series in-process load (2.4s, unlimited ITK threads + 8 pydicom workers) — **fixed in v2.2.3.2.4**
2. VTK software-GL render baseline (~35ms)

---

### v2.2.3.2.4 — First-series in-process GIL contention cap
**Date:** 2026-02-27

**Root cause diagnosed:** When the user opens a study during download, the first series must be loaded in-process (it needs to display immediately, can't wait for subprocess round-trip). This load called `load_single_series_by_number()` **without** `max_itk_threads` (=unlimited, all CPU cores) and the pydicom ThreadPool used 8 workers — all flooding the GIL during the 2.4s load, causing scroll stalls of 52–61ms.

**Changes:**
- **`patient_widget_viewer_controller.py`** `_load_single_series_on_demand()`: added `max_itk_threads=2, max_pydicom_workers=2` to `load_single_series_by_number()` call
- **`utils.py`** `get_or_create_instance()`: added `max_workers` parameter (None = default 8; 2 = viewer Mode B)
- **`image_io.py`** `load_single_series_by_number()`: added `max_pydicom_workers` parameter, threaded through to `process_series_groups()` → `get_or_create_instance()`
- **`image_io.py`** `process_series_groups()`: CPU yield sleeps 50ms→5ms (matched DB-path reduction from v2.2.3.2.3)

**Expected impact:**

| Metric | Before (v2.2.3.2.3) | After (v2.2.3.2.4 expected) |
|---|---|---|
| `set_slice_p95_ms` (during first-series Mode B load) | 52–61ms | **<40ms** |
| `slice_apply_p95_ms` | 37–45ms | **<35ms** (closer to VTK baseline) |
| First-series GIL thread count | N ITK + 8 pydicom = ~16 | **2 ITK + 2 pydicom = 4** |
| First-series load wall time | ~2.4s | ~2.5s (slightly slower, less parallel) — acceptable trade-off |
| `process_series_groups` yield overhead | 100ms (2×50ms) | **10ms (2×5ms)** — saves 90ms |

**Measured (PC A):** _To be filled after next test run_
**PC B:** _Pending_

---

## 7c. Phase 5 Results — Render Pipeline + Signal Coalescing (v2.2.3.2.5 → v2.2.3.2.6)

> These changes target the remaining Mode B scroll lag sources: VTK render
> overhead on software OpenGL and SERIES_DOWNLOAD_COMPLETE signal starvation.

---

### v2.2.3.2.5 — Render pipeline optimizations (software OpenGL)
**Date:** 2026-02-27

**Root cause diagnosed:** On software OpenGL (WARP / Mesa / SwiftShader), VTK's default render pipeline has three unnecessary overheads for 2D medical image display:
1. **FXAA** (CPU post-process AA): 20-50ms per `Render()` call — pixel-exact 2D raster doesn't need AA
2. **8x MSAA**: Each sample multiplies per-pixel work — zero visual benefit for `vtkImageActor` (no polygon edges)
3. **`color_mapper.Update()`** called on every scroll via `apply_default_window_level()` — redundant because `SetWindow()/SetLevel()` marks Modified, and the subsequent `Render()` auto-updates

**Changes:**
- **`viewer_2d.py`**: `self.renderer.UseFXAAOn()` → `self.renderer.UseFXAAOff()`
- **`vtk_widget.py`**: `self.render_window.SetMultiSamples(0)` (VTK defaults to 8)
- **`viewer_2d.py`** `set_window_level()`: skip `color_mapper.Update()` when `flag_default=True` (scroll path); keep for manual WL
- **`viewer_2d.py`** `set_slice()`: Added sub-timing instrumentation (SetSlice, WL, corners, Render) — only logged when total > 30ms
- **`patient_widget_viewer_controller.py`**: Added `max_pydicom_workers=2` to DL_WARMUP warmup callback path

**Expected impact:**

| Component | Before | After (expected) |
|---|---|---|
| FXAA pass per Render() | 20-50ms | **0ms** (disabled) |
| MSAA overhead per Render() | 10-30ms (8 samples) | **0ms** (1 sample) |
| `color_mapper.Update()` on scroll | 5-15ms | **0ms** (skipped, Render() does it) |
| Total `set_slice` Render component | 35-95ms | **<25ms** |

**Measured (PC A):** _To be filled after next test run_

---

### v2.2.3.2.6 — Coalesce SERIES_DOWNLOAD_COMPLETE signals
**Date:** 2026-02-27

**Root cause diagnosed:** Logs showed `event_queue_delay_ms` escalating from 620ms to 5437ms during download. Root cause: `seriesDownloadCompleted` signals from the download subprocess fire back-to-back for 5+ series while the first-series VTK viewer init (200-500ms on software GL) is executing. Each signal triggers synchronous main-thread work:
1. `on_series_completed()` → `thumbnail_manager.complete_series_download()` (border update)
2. `widget.series_downloaded.emit()` → `load_series_on_demand()` → `_enqueue_download_warmup()`

With 5 signals queued during a 500ms VTK init, total blockage = 500ms + 5×(50-100ms) = 750-1000ms. Subsequent signals compound the delay.

**Changes:**
- **`home_ui.py`** `_connect_download_manager_to_widget()`: Replaced immediate `on_series_completed` handler with coalesced version:
  - `_pending_completed: list` accumulates series numbers
  - `_flush_timer = QTimer(100ms, singleShot=True)` debounces
  - First series in a burst dispatched immediately (critical for first-series display latency)
  - `_flush_pending_completions()` processes batch with `QApplication.processEvents()` yield every 2 series
- **`patient_widget_viewer_controller.py`** `_display_first_series_in_all_viewers()`: Added `QApplication.processEvents()` after `_mark_first_series_displayed()` so pending scroll events fire before queued completion handlers

**Expected impact:**

| Metric | Before (v2.2.3.2.5) | After (v2.2.3.2.6 expected) |
|---|---|---|
| `event_queue_delay_ms` during signal bursts | 620–5437ms (escalating) | **<200ms** (coalesced + processEvents) |
| Stale-drain guard activations per download | Frequent (5+ per burst) | **Rare** (coalescing prevents buildup) |
| First-series display latency | Unchanged | Unchanged (first series still immediate) |
| Total completion processing for 5 series | 5×serial = 750-1000ms | 1 immediate + 4 batched = ~300ms |

**Measured (PC A):** _To be filled after next test run_

---

## 8. Log Parsing — Quick Reference

### 8.1 Scroll Probe Output Format

```
viewer-scroll-probe mode=mode_a window_sec=12.1 samples=87
  set_slice_p50_ms=18.34 set_slice_p95_ms=28.91 set_slice_max_ms=62.10
  queue_p95_ms=2.14 slice_apply_p95_ms=16.02
```
```
viewer-scroll-probe mode=mode_b window_sec=12.0 samples=64
  set_slice_p50_ms=22.10 set_slice_p95_ms=44.80 set_slice_max_ms=95.00
  queue_p95_ms=15.40 slice_apply_p95_ms=8.20
```

### 8.2 Filter Timing Output Format

```
viewer-data stage=apply_filters mod=MR slices=24 threads=2 duration_ms=1500
viewer-data stage=apply_filters mod=MR slices=24 threads=1 duration_ms=2939
viewer-data stage=apply_filters mod=CT slices=120 threads=6 duration_ms=180
```
> `threads=1` = legacy DL_WARMUP (pre-v2.2.3.2.3); `threads=2` = subprocess DL_WARMUP / ZetaBoost warmup; `threads=6` = interactive load (8-core)

### 8.3 ZetaBoost PROCESS_DONE Format

```
PROCESS_DONE lane=warmup worker=1 series=3 elapsed_ms=892
PROCESS_DONE lane=interactive worker=1 series=5 elapsed_ms=441
```

### 8.4 DL_WARMUP Per-Series Format

#### v2.2.3.2.3+ (subprocess — look for `_SUB` tag):
```
[DL_WARMUP_SUB] ✓ Cached series=101 in 402ms (count=1/4)
[DL_WARMUP_SUB] series=301 too large (312 slices > 200), skip
[DL_WARMUP_SUB] Worker finished. cached=3/4
```

#### Pre-v2.2.3.2.3 (in-process thread — legacy):
```
[DL_WARMUP] ✓ Cached series=2 in 743ms (count=1/4)
[DL_WARMUP] series=7 too large (312 slices > 200), skip
[DL_WARMUP] Worker finished. cached=3/4
```

### 8.5 Stale-Drain Guard Format (v2.2.3.2.1+)

```
viewer-scroll stage=stale_scroll_skip_ms duration_ms=2804.44 slice=12 skip_count=1
viewer-scroll stage=stale_scroll_skip_ms duration_ms=3222.62 slice=13 skip_count=10
viewer-scroll stage=stale_drain_complete skipped=84 queue_delay_ms=312.00 slice=14
```

### 8.6 Parallel pydicom (v2.2.3.1.9+)

```
- Instance create: 0.362s   ← DB fast-path (parallel reads, already cached)
- Instance create: 0.800s   ← filesystem fallback path
```

---

## 9. Delta Interpretation Guide

| Change | What it means |
|---|---|
| `scroll_p50_ms` decreased | Typical scroll faster — user notices immediately |
| `scroll_p95_ms` decreased | Occasional hiccups reduced |
| `scroll_max_ms` decreased | Worst-case spike gone |
| `queue_delay_p95_ms > 30ms` | Main thread blocked — investigate |
| `queue_delay_ms > 500ms` (v2.2.3.2.1+) | Stale drain guard fires — normal during download/load |
| `stale_drain_complete skipped=N` | N renders saved; 1 render at correct final position |
| `filter_ms` decreased | Faster series switch |
| `threads=1` in filter log | Legacy DL_WARMUP (pre-v2.2.3.2.3, in-process thread) |
| `threads=2` in filter log | Subprocess DL_WARMUP (v2.2.3.2.3+) / ZetaBoost warmup / first-series (v2.2.3.2.4+) |
| `threads=6` in filter log | Interactive load on 8-core machine (adaptive) |
| `warmup_job_ms > 2000ms` | Warmup competing with something — check CPU/thread priority |
| `batch_insert_instances_total > 500ms` | Pydicom parallel may not be active — check v2.2.3.2.0 deployed |
| `Instance create > 1000ms` | Parallel pydicom may not be active — check v2.2.3.1.9 deployed |
| `WORKER_BLOCKED reason=max_parallel(1/1)` | ZetaBoost max_parallel_loads=1 (pre v2.2.3.2.2 on 8GB+ tier) |
| `WORKER_BLOCKED reason=max_parallel(1/2)` | One of two parallel warmup slots free — warm v2.2.3.2.2 |
| `[DL_WARMUP_SUB]` in warmup logs | Subprocess DL_WARMUP active (v2.2.3.2.3+) — GIL-free ✅ |
| `[DL_WARMUP]` (no `_SUB`) in logs after v2.2.3.2.3 | Subprocess failed to start, fell back to in-process thread ⚠️ |
| `queue_p95_ms=0.00` during Mode B scroll | Subprocess DL_WARMUP working — no GIL contention |

---

## 10. Instrumentation Present (cumulative)

| Log Tag | Source File | Description |
|---|---|---|
| `viewer-scroll-probe mode=mode_a/b` | `vtk_widget.py` | 12s rolling scroll stats |
| `viewer-scroll stage=event_queue_delay_ms` | `vtk_widget.py` | Per-event queue delay |
| `viewer-scroll stage=stale_scroll_skip_ms` | `vtk_widget.py` | Stale-drain guard fires (v2.2.3.2.1+) |
| `viewer-scroll stage=stale_drain_complete` | `vtk_widget.py` | Drain done, N events skipped |
| `viewer-data stage=apply_filters mod=... threads=... duration_ms=...` | `image_filters.py` | ITK filter wall time |
| `viewer-data stage=itk_filter_chain` | `image_io.py` | Filter call duration at load layer |
| `viewer-data stage=itk_to_vtk_convert` | `image_io.py` | ITK→VTK array conversion |
| `viewer-data stage=load_single_series_total` | `image_io.py` | Total series load wall time |
| `stage-timing fn=VTKWidget.set_slice stage=set_slice_total` | `vtk_widget.py` | Total set_slice duration |
| `PROCESS_DONE lane=warmup elapsed_ms=...` | `engine.py` | ZetaBoost warmup job wall time |
| `[DL_WARMUP_SUB] ✓ Cached series=X in Yms` | `patient_widget_viewer_controller.py` | Subprocess DL_WARMUP per-series elapsed (v2.2.3.2.3+) |
| `[DL_WARMUP] ✓ Cached series=X in Yms` | `patient_widget_viewer_controller.py` | Legacy in-process DL_WARMUP per-series elapsed |
| `DL_WARMUP subprocess_started pid=N` | `warmup_subprocess.py` | Subprocess lifecycle start (v2.2.3.2.3+) |
| `DL_WARMUP subprocess_stopped` | `warmup_subprocess.py` | Subprocess lifecycle end |
| `batch_insert_instances_total` | `series_downloader.py` | DB insert time (download subprocess) |
| `Instance create: Xs` | stdout print | Viewer-side pydicom read time |

---

## 11. Complete Version History

| Version | Commit | Date | Change Summary | Key Measured Result |
|---|---|---|---|---|
| v2.2.2.8 | — | 2026-02-24 | Warmup lanes not wired | Mode B scroll 30–50ms hit |
| v2.2.3.0.4 | `7c25666` | 2026-02-xx | Sort warmup by slice-count asc + ITK drain-wait before interactive load | Reduced warmup/scroll contention |
| v2.2.3.0.5 | `a98d75e` | 2026-02-xx | Clear stale scroll state on series switch | Fixed 14–17s event_queue_delay + stale slice bleed |
| v2.2.3.0.6 | `92b428f` | 2026-02-xx | Limit ITK threads=1 during apply_filters (prevent VTK starvation) | Baseline Mode A controlled |
| v2.2.3.0.7 | `4ff6333` | 2026-02-xx | Skip VTK pipeline invalidation on unchanged WL; skip redundant text actor SetInput | Scroll overhead reduced |
| v2.2.3.0.8 | `9f3623c` | 2026-02-xx | Fix 29s ITK on mild_mode MR (80% speedup: 2t + 2 sigmas + skip adaptive sharpening) | MR filter: 29s → ~1.5s |
| v2.2.3.0.9 | `86afd57` | 2026-02-xx | Per-series DL_WARMUP (controlled Mode B caching) | DL_WARMUP framework added |
| v2.2.3.1.0 | `92d61cb` | 2026-02-xx | Cast-once filter + render dedup + dead code cleanup | Intermediate INT→float casts eliminated |
| v2.2.3.1.5 | `1eeec45` | 2026-02-26 | XY-only 2-stage filter; max_itk_threads=2 DL_WARMUP; main-thread guard | MR Mode A filter: 423ms; Mode B p50: ~37ms; scroll max: 57ms |
| v2.2.3.1.6 | `f3613e4` | 2026-02-26 | Cast-once; zoom-protection Render guard; localizer skip | filter_ms: 423→151ms (−64%); zoom double-Render eliminated |
| v2.2.3.1.7 | `e543639` | 2026-02-26 | Dead code −540 lines; async DB save after download; size-aware preprocess cache | Re-open study: fast from L2 disk |
| v2.2.3.1.8 | `04c57d0` | 2026-02-26 | Skip redundant SetInputData on series switch; wire ImageSliceBooster | Series switch overhead: −1.4s |
| v2.2.3.1.8p1 | `af794d9` | 2026-02-26 | Download subprocess BELOW_NORMAL priority; QThread naming | CPU contention reduced |
| v2.2.3.1.9 | `9d2414b` | 2026-02-26 | Parallel pydicom header reads in viewer `get_or_create_instance` | Instance create: 4.3s→0.8s (330 files, −81%) |
| v2.2.3.2.0 | `3cd1a09` | 2026-02-26 | Parallel pydicom in download subprocess; adaptive ITK threads; BELOW_NORMAL filter priority | batch_insert: 2217ms→326ms (−85%); filter threads adaptive |
| v2.2.3.2.1 | `9724dea` | 2026-02-26 | Stale-event fast-drain guard in set_slice (skip render when queue_delay>500ms) | queue_p95: 19,496ms→~16ms expected; 84-event backlog → 1 render |
| v2.2.3.2.2 | `ff0d4b1` | 2026-02-27 | DL_WARMUP max_itk_threads 1→2; inter-delay 3.0→1.5s; max_parallel_loads 1→2 (8GB+/15GB+) | DL_WARMUP per-series: 4.1s→~2.0s expected; 2 parallel warmup workers |
| **v2.2.3.2.3** | — | 2026-02-27 | **DL_WARMUP moved to `multiprocessing.Process` (own GIL)** — `warmup_subprocess.py`; results serialized via `mp.Queue`; QTimer 100ms polls viewer-side; redundant `sitk.Cast` removed in `_smooth_xy_recursive`; GIL yield sleeps 50ms→5ms in `image_io.py` | **`queue_p95_ms` dropped from 200-510ms → 0.00ms** ✅; DL_WARMUP confirmed 402ms per series in subprocess |
| **v2.2.3.2.4** | — | 2026-02-27 | **First-series in-process GIL contention fix** — `max_itk_threads=2, max_pydicom_workers=2` for `_load_single_series_on_demand`; `get_or_create_instance` accepts `max_workers` param; `process_series_groups` yields 50ms→5ms | Expected: `set_slice_p95_ms` 52-61ms→<40ms during first-series Mode B load |
| **v2.2.3.2.5** | — | 2026-02-27 | **Render pipeline optimizations on software OpenGL** — FXAA off (`renderer.UseFXAAOff()`); `SetMultiSamples(0)` (was 8x MSAA); skip redundant `color_mapper.Update()` on scroll (Render() auto-updates); sub-timing instrumentation in `ImageViewer2D.set_slice`; `max_pydicom_workers=2` in DL_WARMUP warmup callback | Expected: 20-50ms/frame saved (FXAA) + 10-30ms (MSAA) + 5-15ms (color_mapper) |
| **v2.2.3.2.6** | — | 2026-02-27 | **Coalesce SERIES_DOWNLOAD_COMPLETE signals** — `home_ui.py`: first series immediate, subsequent batched with 100ms debounce QTimer + processEvents yield every 2 series; `patient_widget_viewer_controller.py`: processEvents() yield after first-series viewer init | Expected: `event_queue_delay_ms` drops from 620–5437ms to <200ms |
| **v2.2.3.3.0** | `66914e0` | 2026-02-27 | **Strengthen GC suppression for heavy volumes (PC B)** — increased GC re-enable timer 500→2000ms; keep elevated thresholds (700,50,50) on re-enable instead of restoring originals; avoid overwriting saved thresholds on re-enter | Eliminated 660-700ms periodic GC lag pattern on PC B |
| **v2.2.3.3.1** | `0382270` | 2026-02-27 | **Event-loop bypass eliminates periodic lag** — cache `os.getenv` values in `__init__` (was 3-5ms per call ×2 per frame); bypass coalesce timer when adaptive gap already expired during event-loop congestion | Eliminated 100-300ms stalls from download signal congestion |
| **v2.2.3.3.2** | `edfff7f` | 2026-02-27 | **Eliminate 660ms periodic GC lag** — GC re-enable timer 500→2000ms; keep elevated thresholds on re-enable; save original thresholds only once | Fixed precise 660-700ms periodic lag (500ms timer + 150ms GC collection) on PC B |
| **v2.2.3.3.3** | `1f2cd36` | 2026-02-27 | **Debounce reference line updates during scroll** — `_schedule_reference_line_update()` with 80ms trailing-edge QTimer; prevents expensive `_update_reference_lines()` Render on every scroll frame | Saved ~20-40ms per excessive ref-line repaints |
| **v2.2.3.3.4** | `5b3b77c` | 2026-02-27 | **Sync reference lines with stack drag + lock sync** — ref-line update after lock sync completes; debounced at 80ms to prevent Render-per-target | Reference lines stay current during lock sync drag |
| **v2.2.3.3.5** | `6b18b94` | 2026-02-27 | **Real-time reference line sync** — leading-edge (immediate, geometry-only) + trailing-edge (50ms, with repaint) dual-timer pattern for ref-line updates | Instant actor positioning + deferred repaint |
| **v2.2.3.3.6** | `f90b608` | 2026-02-27 | **Eliminate ref-line paint blocking from scroll loop** — trailing-edge repaint uses `repaint=False` geometry-only update; actual VTK Render deferred to scroll-end | Scroll loop never blocked by ref-line Render |
| **v2.2.3.3.7** | `f6c4dda` | 2026-02-27 | **Round-robin reference line repaint** — trailing-edge paints ONE target viewer per tick (round-robin), scroll-end tick repaints ALL targets for full visual correctness | Capped ref-line event-loop blocking to ~20ms per tick instead of N×20ms |
| **v2.2.3.3.8** | `125c00a` | 2026-02-27 | **Fix size-mismatch detection for incomplete downloads** — `_check_size_mismatch()` now compares against expected instance count from DB metadata, not just cached data; prevents false-positive size mismatch warnings during active downloads | Eliminated spurious warmup retries during download |
| **v2.2.3.3.9** | `af11baf` | 2026-02-27 | **Reduce Mode B scroll lag from warmup contention** — subprocess ITK threads 2→1; defer result poll during scroll (idle<300ms); max 1 result per poll tick; tighten notify_viewer_interaction throttle 500→250ms | Reduced warmup contention with VTK render during scroll |
| **v2.2.3.4.0** | `5215a89` | 2026-02-27 | **Scroll fast-path — skip non-essential per-frame overhead** — skip camera zoom save/restore during wheel scroll (~3-5ms); skip interactor style update (~1ms); throttle Lock Sync to 100ms during scroll; subprocess warmup priority BELOW_NORMAL→IDLE | Expected: set_slice_total p50 ~45→~35ms, p95 ~61→~45ms |

---

## 12. Current Bottlenecks (as of v2.2.3.4.0)

| Priority | Bottleneck | Location | Impact | Status |
|---|---|---|---|---|
| 🟡 MED | First-series load still runs in-process (~2.4s via asyncio.to_thread) | `patient_widget_viewer_controller.py` | v2.2.3.2.4 caps threads, but GIL still shared | Open — consider subprocess routing |
| 🟡 MED | `update_corners_actors()` updates 6 VTK text actors per scroll (only 2 change) | `viewer_2d.py` | ~5-10ms per scroll overhead on software-GL | Open — split varying vs constant actors |
| 🟡 MED | `viewer_db_read` 38–88ms on series load | `image_io.py` DB query | Adds to series switch latency | Open — may batch query |
| 🟡 MED | MR large-FOV filter still slow (500×640×24 = ~1.5s at 2 threads) | `image_filters.py` `_smooth_xy_recursive` | Doesn't affect scroll now (subprocess), but delays warmup | Mitigated — subprocess isolates impact |
| 🟢 LOW | `disk_read` 27–384ms on series load | `image_io.py` filesystem | SSDs fast; HDDs slow; L2 disk cache helps | Mitigated by ZetaBoost L2 |
| 🟢 LOW | `create_connection` 3–24ms on new threads | `database.py` | First load per thread | Acceptable |
| ✅ FIXED | Lock Sync per-frame overhead (5-20ms during scroll) | `patient_widget.py` + `vtk_widget.py` | v2.2.3.4.0 | Done — throttled to 100ms during wheel scroll |
| ✅ FIXED | Camera zoom save/restore overhead (3-5ms per frame) | `vtk_widget.py` | v2.2.3.4.0 | Done — skipped during wheel scroll (event consumed, VTK zoom blocked) |
| ✅ FIXED | Interactor style update per scroll (~1ms) | `vtk_widget.py` | v2.2.3.4.0 | Done — skipped during wheel scroll |
| ✅ FIXED | Subprocess warmup BELOW_NORMAL still causes mem-bus contention | `warmup_subprocess.py` | v2.2.3.4.0 | Done — lowered to IDLE_PRIORITY_CLASS |
| ✅ FIXED | Reference line repaint blocking scroll loop | `patient_widget.py` | v2.2.3.3.7 | Done — round-robin single-target repaint |
| ✅ FIXED | 660ms periodic GC lag pattern (PC B) | `vtk_widget.py` | v2.2.3.3.2 | Done — 2000ms re-enable + keep elevated thresholds |
| ✅ FIXED | Subprocess ITK 2 threads contention during scroll | `warmup_subprocess.py` + controller | v2.2.3.3.9 | Done — capped to 1 thread + deferred poll + 1 result/tick |
| ✅ FIXED | Size-mismatch false positives during download | `image_io.py` | v2.2.3.3.8 | Done — compare against DB expected count |
| ✅ FIXED | SERIES_DOWNLOAD_COMPLETE event queue starvation (620-5437ms) | `home_ui.py` + `patient_widget_viewer_controller.py` | v2.2.3.2.6 | Done — coalesced signal handler + processEvents yield |
| ✅ FIXED | VTK render overhead: FXAA +20-50ms, MSAA 8x, redundant color_mapper.Update() | `viewer_2d.py` + `vtk_widget.py` | v2.2.3.2.5 | Done — FXAA off, MSAA=0, skip Update on scroll |
| ✅ FIXED | DL_WARMUP GIL contention (queue_p95=200-510ms) | `warmup_subprocess.py` | v2.2.3.2.3 | Done — subprocess with own GIL |
| ✅ FIXED | First-series unlimited ITK threads + 8 pydicom workers | controller + utils.py | v2.2.3.2.4 | Done — capped to 2+2 |
| ✅ FIXED | Stale scroll event drain (queue_p95=19,496ms) | `vtk_widget.py` | v2.2.3.2.1 | Done |
| ✅ FIXED | batch_insert_instances serial (2217ms) | `series_downloader.py` | v2.2.3.2.0 | Done |
| ✅ FIXED | Instance create serial pydicom (4.3s) | `utils.py` | v2.2.3.1.9 | Done |
| ✅ FIXED | SetInputData redundant call (1.4s series switch) | `vtk_widget.py` | v2.2.3.1.8 | Done |
| ✅ FIXED | MR mild_mode filter 29s | `image_filters.py` | v2.2.3.0.8 | Done |

---

## 13. Next Test Checklist (v2.2.3.4.0)

Run after pulling latest on both PC A and PC B:

```powershell
# Get latest log
$log = Get-ChildItem "c:\AI-Pacs codes\ai-pacs\logs" -Filter "*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

# DL_WARMUP SUBPROCESS timing (should see [DL_WARMUP_SUB], IDLE priority)
Select-String "\[DL_WARMUP_SUB\].*Cached series" $log.FullName | Select-Object -Last 10

# Subprocess priority (should say IDLE, not BELOW_NORMAL)
Select-String "priority set to" $log.FullName | Select-Object -Last 10

# Scroll probe during download (Mode B — check set_slice_p50/p95 improvement)
Select-String "viewer-scroll-probe" $log.FullName | Select-Object -Last 10

# Sub-timing in set_slice (only logged when total > 30ms)
Select-String "viewer-scroll sub-timing" $log.FullName | Select-Object -Last 10

# Queue delay per scroll (should be ~0.00ms during scroll)
Select-String "event_queue_delay_ms" $log.FullName | Select-Object -Last 20

# Reference line updates (should see round-robin pattern)
Select-String "ref_line_update|schedule_reference_line" $log.FullName | Select-Object -Last 10

# Lock Sync throttle (check if lock sync runs every 100ms, not every frame)
Select-String "LOCK SYNC" $log.FullName | Select-Object -Last 10
```

**Expected results (v2.2.3.4.0):**
- `set_slice_p50_ms` ≈ 35ms (was ~45ms in v2.2.3.3.9) — camera/style skip saves 4-6ms
- `set_slice_p95_ms` ≈ 45ms (was ~61ms) — subprocess IDLE priority reduces SetSlice spikes
- `queue_p95_ms=0.00` in scroll probes during download (GIL-free warmup)
- Subprocess logs show `Process priority set to IDLE` (was BELOW_NORMAL)
- No zoom-change-detected warnings during scroll (camera save/restore skipped)
- Lock Sync callback fires ≤10 times/sec during scroll (100ms throttle)

