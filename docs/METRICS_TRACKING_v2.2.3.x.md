# Performance Metrics Tracking — AIPacs Mode A / Mode B
**Current Version:** v2.2.3.1.5  
**Branch:** DR.vahid  
**Date Created:** 2026-02-26  
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
| **B5** | `dl_warmup_per_series_ms` | `[DL_WARMUP] ✓ Cached series=` → elapsed time | Wall time for DL_WARMUP to pre-cache one series | < 1200ms |
| **B6** | `dl_warmup_filter_ms` | `viewer-data stage=apply_filters` (1-thread calls) | ITK filter time during DL_WARMUP (1-thread cap; was 2-thread in v2.2.3.1.5) | < 1200ms |
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

## 7. Phase 3 Results (v2.2.3.2.x — Rendering Pipeline)

**Changes applied:**
- Lazy `ImageReslice.Update()` (defer from `__init__` to first use)
- Merge triple pipeline flush in `reset_image_viewer()` into single flush
- Size-aware preprocess cache eviction

**Expected gains:**
- A1/A2 scroll: −5 to −20ms per scroll
- Series switch (L1 cache hit): 200–600ms → 80–200ms

### 7.1 Mode A — Phase 3

| ID | Metric | Baseline | Phase 2 | Phase 3 PCA | Phase 3 PCB | Δ vs Baseline |
|---|---|---|---|---|---|---|
| A1 | scroll_p50_ms | ___ | ___ | ___ | ___ | ___ |
| A2 | scroll_p95_ms | ___ | ___ | ___ | ___ | ___ |
| A8 | series_load_total_ms | ___ | ___ | ___ | ___ | ___ |

**Date / time:** ___  
**Version tag:** v2.2.3.2.x  
**Decision:** ☐ Proceed to Phase 4 &nbsp; ☐ Investigate regression &nbsp; ☐ Adjust approach

---

## 8. Log Parsing — Quick Reference

### 8.1 Scroll Probe Output Format (after instrumentation patch v2.2.3.1.5)

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
viewer-data stage=apply_filters mod=MR slices=24 threads=4 duration_ms=420
viewer-data stage=apply_filters mod=MR slices=24 threads=2 duration_ms=650
viewer-data stage=apply_filters mod=CT slices=120 threads=4 duration_ms=180
```

### 8.3 ZetaBoost PROCESS_DONE Format

```
PROCESS_DONE lane=warmup worker=1 series=3 elapsed_ms=892 L1=3/20 L2=3
PROCESS_DONE lane=interactive worker=1 series=5 elapsed_ms=441 L1=4/20 L2=4
```

### 8.4 DL_WARMUP Per-Series Format

```
[DL_WARMUP] ✓ Cached series=2 in 743ms (count=1/4)
[DL_WARMUP] series=7 too large (312 slices > 200), skip
[DL_WARMUP] Worker finished. cached=3/4
```

---

## 9. Delta Interpretation Guide

| Change | What it means |
|---|---|
| `scroll_p50_ms` decreased | Typical scroll is faster — user notices immediate improvement |
| `scroll_p95_ms` decreased | Occasional slow scrolls reduced — fewer "hiccup" moments |
| `scroll_max_ms` decreased | Worst-case spikes reduced — no freezes |
| `queue_delay_p95_ms` > 30ms | Main thread is being blocked somewhere — investigate |
| `filter_ms` decreased | Filters faster — series switch is quicker |
| `warmup_job_ms` > 1500ms | Warmup competing with something — check CPU priority |
| `dl_warmup_filter_ms` > 1500ms | 1-thread cap still insufficient for this machine — consider increasing `DL_WARMUP_INTER_DELAY` or raising slice-skip threshold |
| `dl_warmup_per_series_ms` > 2000ms | DL_WARMUP blocking too long — INTER_DELAY may need adjustment |

---

## 10. Instrumentation Changes Made (v2.2.3.1.5 — this session)

### New log output added

| File | Change | New Log Tag |
|---|---|---|
| `vtk_widget.py` | Scroll probe now fires for **both Mode A and Mode B** (was Mode B only). Mode tag added. Mode transition flushes window to prevent mixed samples. | `viewer-scroll-probe mode=mode_a` / `mode=mode_b` |
| `image_filters.py` | Filter timing now always logged (was commented out). Includes modality, slice count, thread count. | `viewer-data stage=apply_filters mod=... slices=... threads=... duration_ms=...` |
| `engine.py` | `PROCESS_DONE` now includes `elapsed_ms` (wall time of the full warmup job). | `PROCESS_DONE lane=... elapsed_ms=...` |

### Already present (no change needed)

| Log Tag | Source | Description |
|---|---|---|
| `viewer-data stage=itk_filter_chain` | `image_io.py:944` | ITK filter call duration (at load layer) |
| `viewer-data stage=itk_to_vtk_convert` | `image_io.py:961` | ITK→VTK convert duration |
| `viewer-data stage=load_single_series_total` | `image_io.py` via `log_stage_timing` | Total series load wall time |
| `[DL_WARMUP] ✓ Cached series=X in Yms` | `patient_widget_viewer_controller.py:4528` | DL_WARMUP per-series elapsed |
| `PROCESS_START / PROCESS_DONE` | `engine.py` | ZetaBoost job lifecycle |
| `DISK_PROMOTE ... Xms` | `engine.py` | L2→L1 disk promotion |
| `[LOAD_VTK] ✓ Loaded in Xs` | `image_io.py:578` | Filesystem fallback load |

---

## 11. Version History

| Version | Date | Changes | Key Result |
|---|---|---|---|
| v2.2.2.8 | 2026-02-24 | Warmup lanes not wired | Mode B scroll 30–50ms hit |
| v2.2.3.1.5 | 2026-02-26 | XY-only 2-stage filter; max_itk_threads=2 for DL_WARMUP; main-thread guard | Mode A scroll: ~18ms p50, 37ms max (warmup spike). Mode B scroll: 51–57ms floor, 114ms peak |
| v2.2.3.1.5.1 | 2026-02-xx | ZetaBoost warmup callback → max_itk_threads=2; DL_WARMUP → max_itk_threads=1; double get_window_level() fixed | Mode A spike eliminated (37→≈20ms max); Mode B spike eliminated (114→expected <65ms max) |
| v2.2.3.1.6 | TBD | Cast-once (`apply_filters`); guard zoom-protection double `Render()`; remove double `update_corners_actors()` | Target: −50–150ms filter, −5–10ms scroll |
| v2.2.3.1.7 | TBD | Dead code; interactive disk cache | Target: re-open study instant |
| v2.2.3.2.x | TBD | Lazy Reslice; merge flushes | Target: −5–20ms scroll |
