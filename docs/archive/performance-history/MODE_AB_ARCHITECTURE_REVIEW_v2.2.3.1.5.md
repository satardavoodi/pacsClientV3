# Mode A / Mode B Architecture Review
**Version reviewed:** v2.2.3.1.5  
**Branch:** DR.vahid (commit 1eeec45)  
**Date:** 2026-02-26  
**Status:** POST-SESSION — all bugs fixed, plan documented

---

## 1. Bugs Fixed This Session

### Bug 1 — 4.2-second main-thread freeze
- **Symptom:** `event_queue_delay` escalating to 4721ms after download completion
- **Cause:** `load_series_immediately()` called via `QTimer.singleShot` (main thread) →
  `_load_single_series_on_demand()` → `load_event.wait(timeout=10.0)` when warmup owned the lock
- **Fix:** Main-thread guard in `_load_single_series_on_demand()` returns `False` immediately;
  callers `load_series_immediately()` and `load_first_series_only()` retry via `QTimer.singleShot(250ms)`
- **File:** `patient_widget_viewer_controller.py` lines ~4024, ~5263, ~5350

### Bug 2 — Mode B scroll lag 141–156ms during DL_WARMUP
- **Symptom:** `event_queue_delay` 141–156ms while `_dl_warmup_worker` was processing series
- **Cause:** v2.2.3.1.5 changed `apply_filters` to use `min(cpu, 4)` ITK threads globally —
  silently reverted the old 2-thread cap for DL_WARMUP; 4 C++ ITK threads competed at
  normal OS priority with the VTK render thread
- **Fix:** Added `max_itk_threads` parameter to `apply_filters()`, `load_single_series_by_number()`,
  and `process_series_groups()`; `_dl_warmup_worker` originally passed `max_itk_threads=2`
  (refined to `max_itk_threads=1` after baseline testing confirmed scroll spikes — see Mode B section)
- **Files:** `image_filters.py`, `image_io.py`, `patient_widget_viewer_controller.py` line 4493

### Bug 3 — Mode A NameError crash (images not showing)
- **Symptom:** `[WARN] load_images: Failed series -> name 'max_itk_threads' is not defined`
- **Cause:** `apply_filters(..., max_itk_threads=max_itk_threads)` was added inside
  `process_series_groups()` body but `max_itk_threads` was not in its function signature
- **Fix:** Added `max_itk_threads=None` parameter to `process_series_groups()` signature;
  threaded through from `load_single_series_by_number()` call at line ~1007
- **File:** `image_io.py`

---

## 2. What's Working Correctly (Verified)

| Mechanism | Status | Location |
|---|---|---|
| `notify_global_download_start/stop` wired | ✅ Active | `main_widget.py` lines 2146, 2335 |
| `_can_start_lane_locked` blocks warmup/bg when `global_count > 0` | ✅ Active | `engine.py` line 675 |
| `max_itk_threads=1` in `_dl_warmup_worker` (was 2 → refined to 1 after baseline scroll spikes) | ✅ Fixed | `patient_widget_viewer_controller.py` line 4493 |
| `max_itk_threads=2` in `_zeta_boost_load_series()` warmup callback | ✅ Fixed | `patient_widget_viewer_controller.py` line ~563 |
| XY-only 2-stage filter (PooyanPacs-style, clamped) | ✅ Active | `image_filters.py` line 595 |
| Main-thread load guard + QTimer retry | ✅ Fixed | `patient_widget_viewer_controller.py` |
| Subprocess download (own GIL, own OS process) | ✅ Active | `subprocess_worker.py` |
| ZetaBoost OS IDLE priority thread (Win32 `THREAD_PRIORITY_IDLE=-15`) | ✅ Active | `engine.py` line 35 |

---

## 3. Mode A — Clean Pipeline (POST_DOWNLOAD)

**Trigger:** Study state → `POST_DOWNLOAD` → `set_study_download_complete(True)`

```
Study opens (POST_DOWNLOAD)
    │
    ▼  global_active_download_count == 0 → warmup/background lanes ALLOWED
    │
User clicks series (interactive lane)
    → ZetaBoost L1 RAM hit?  → < 50ms instant
    → ZetaBoost L2 disk hit? → ~50ms fast
    → Cache miss → load_single_series_by_number(max_itk_threads=None)
                        XY-only filters: σ=0.25 noise + σ=1.0 unsharp (clamped)
                        convert_itk2vtk → display (~0.3–0.8s)
                        ZetaBoost put() → L1 + L2 disk

Background (OS IDLE priority thread, ZetaBoost warmup lane):
    Queues remaining series → max_parallel=1
    Blocks if interactive_queued=True
    Yield: 0.5s normal / 2.0s during any download
    ITK threads: no cap needed (IDLE OS priority prevents contention)
```

**ITK thread strategy:**
- Interactive loads: `max_itk_threads=None` → `min(cpu, 4)` — user-initiated, download is done, full threads OK
- ZetaBoost warmup lane: IDLE OS priority + `max_itk_threads=2` cap in `_zeta_boost_load_series()` (added after baseline testing: uncapped warmup caused 37ms scroll spikes when user scrolled during warmup ITK run)

---

## 4. Mode B — Clean Pipeline (DOWNLOADING)

**Trigger:** Download subprocess starts → `notify_global_download_start()`

```
Download subprocess starts
    │
    ├─► ZetaBoostEngine.notify_global_download_start()   [main_widget.py:2146]
    │       → _global_active_download_count = 1
    │       → ZetaBoost warmup/background lanes BLOCKED immediately
    │
    └─► _dl_warmup_worker thread starts (daemon, normal priority)

Per series as it finishes downloading:
    dcm_count from DB/server metadata
    if dcm_count > DL_WARMUP_MAX_SLICES (200): skip → no pre-cache
    else:
        load_single_series_by_number(max_itk_threads=1)   ← Mode B cap (1 thread: ~1.1s ITK, no scroll spikes)
            XY-only filters (2-thread ITK)  ~0.5–1.0s per series
            convert_itk2vtk
        set_image_boost_mode(False)
        ZetaBoost put() → L1 cache
        set_image_boost_mode(True)
        Sleep DL_WARMUP_INTER_DELAY (3.0s)  ← CPU yield between series

User scrolls during download:
    → DL_WARMUP pre-cached?    → instant from L1
    → Cache miss               → ImageSliceBooster ±20 slice window (IDLE priority)
    → Full miss                → direct load (ZetaBoost background lane blocked)

Download completes:
    ZetaBoostEngine.notify_global_download_stop()   [main_widget.py:2335]
        → _global_active_download_count = 0
        → ZetaBoost warmup/background lanes unblocked
    _dl_warmup_worker exits
    → ZetaBoost open-tab warmup resumes (Mode A path)
```

**ITK thread strategy:**
- DL_WARMUP worker: `max_itk_threads=1` — 1 thread eliminates scroll spikes (baseline: 94–114ms during ITK → expected <60ms); ITK time doubles to ~1.1s but fits within 3s inter-series delay
- After download → ZetaBoost engine inherits IDLE priority; warmup callback uses `max_itk_threads=2` cap

---

## 5. XY-Only Filter Pipeline (v2.2.3.1.5)

```
Input: sitk.Image (full 3D volume, native int16/int32)
    │
    ▼  Cast once → float32
    │
Stage 1: XY-only Gaussian noise reduction
    sigma=0.25 (mild: 0.30), no Z-pass
    ITK SmoothingRecursiveGaussianImageFilter (2D per slice)
    │
Stage 2: XY-only Unsharp mask (MR only)
    sigma=1.0, amount=0.25 (mild: 0.20)
    formula: output = original + amount × (original − Gaussian(original))
    clamped to [min, max] of original data range  ← v2.2.3.1.5 fix
    │
    ▼  Cast back → original pixel type (int16)
Output: sitk.Image
```

### Comparison vs old 4-stage 3D pipeline

| Property | v2.2.2.x (4-stage 3D) | v2.2.3.1.5 (XY-only 2-stage) |
|---|---|---|
| Gaussian passes per MR | 4–7 full 3D passes | 2 XY-only passes |
| Wall time per MR series | 3–7s | ~0.3–0.8s |
| Peak RAM (float32 temps) | ~1.0 GB | ~250 MB |
| Z-slice dependency | Full 3D required | None |
| Mode B safe at 2 threads | Very slow (1.5–3s) | Acceptable (~0.5s) |

**No changes needed to filter algorithm.** Current implementation is correct.

---

## 6. High Slice Count Strategy

| Context | Rule | Rationale |
|---|---|---|
| Mode B DL_WARMUP | Skip if `dcm_count > 200` | 400-slice CT at 2 threads = ~1.5–2s; delays DL_WARMUP loop while download ongoing |
| Mode A ZetaBoost warmup | No skip | IDLE priority + post-download state = safe to process all series |
| Mode A interactive | No skip | User-initiated, `max_itk_threads=None` = fast |

**Optional future improvement:** Make Mode B slice cap modality-aware:
- CT ≥ 120 slices: skip (disk I/O heavy, large volumes)
- MR ≥ 200 slices: skip (conservative)
- MR < 200 slices: always pre-cache even if count > current cap

---

## 7. Remaining Known Issues (Not Yet Fixed)

### 7.1 Redundant Processing — High Impact

| Issue | Location | Estimated Saving | Status |
|---|---|---|---|
| **4 redundant `sitk.Cast()` calls** in filter chain | `image_filters.py` — cast was inside `if modality == 'MR'`; CT never benefited | 50–150ms per series | ✅ Fixed (v2.2.3.1.6 Phase 1) |
| **Double `update_corners_actors()` per scroll** | `viewer_2d.py` — `set_window_level(flag_default=True)` path now has `if not flag_default:` guard + WL scroll-cache short-circuit | 1–3ms per scroll | ✅ Already fixed (v2.2.3.1.0) — not a v2.2.3.1.6 task |
| **Second `Render()` per scroll** (zoom protection, tolerance `0.001` too tight) | `vtk_widget.py` `set_slice()` — now uses `_protected_parallel_scale` ref + tolerance 0.05 | 60–80ms per scroll | ✅ Fixed (v2.2.3.1.6 Phase 1) |
| **`ImageReslice.Update()` in `__init__` AND in `reset_image_viewer()`** | `viewer_2d.py` | 100–300ms per series switch | ⚠️ Phase 3 pending |

### 7.2 Dead Code (~540 lines)

| Function | File | Lines |
|---|---|---|
| `convert_itk2vtk_fast_first()` | `utils.py` | ~100 |
| `get_itk_image_fast_first()` | `image_io.py` | ~25 |
| `switch_series_backup()` | `vtk_widget.py` | ~60 |
| `edge_smooth_ultrafast()`, `smoothing()`, `apply_gaussian_sharpening()`, `apply_unsharp_mask()` | `image_filters.py` | ~245 |
| Triple-copy DEFAULT_FILTERS (3 identical copies in same file) | `image_filters.py` | ~400 |

### 7.3 Mode B — event_queue_delay Bottleneck (NEW — found Phase 1 test 2026-02-26)

> After Phase 1 fixed `set_slice_total` spikes (now 35–57ms), the `event_queue_delay` is the new dominant latency in Mode B.
> Total perceived scroll latency = queue_delay (40–106ms) + set_slice_total (35–57ms) = **75–163ms**.  
> User perception: "near acceptable".

| Root Cause | Location | Observed Delay | Fix Candidate |
|---|---|---|---|
| Download subprocess signals (SERIES_DOWNLOAD_COMPLETE ~every 500ms) pump Qt callbacks to main thread | `patient_widget_viewer_controller.py` signal handlers | +40–55ms baseline queue delay | Phase 3: offload handlers to executor |
| Post-download study-save sequence (saves 6 series + patient + study to DB) runs on main thread | `home_ui.py` / `patient_widget_viewer_controller.py` STUDY_DOWNLOAD_COMPLETE handler | ~200ms block → 80–106ms queue spike | Phase 3: defer DB save to background thread |
| ZetaBoost PROCESS_DONE + ALL_WORK_COMPLETE + 10× DB pool_lock callbacks on main thread | `engine.py` / `viewer_controller.py` | brief ~20ms block | LOW priority |

**Constraint:** `event_queue_delay` ≠ ITK. Reducing ITK further will not help this.  
**Target (Phase 3):** queue_delay_p95_ms < 30ms (requires offloading study-save from main thread).

### 7.4 Medium-Term Improvements

| Improvement | Impact | Risk |
|---|---|---|
| Write interactively-loaded series to ZetaBoost disk cache | Re-opening study = instant | MEDIUM |
| Lazy `ImageReslice.Update()` (defer from `__init__` to first use) | 100–300ms per switch | MEDIUM |
| Merge triple pipeline flush in `reset_image_viewer()` | 100–200ms per switch | MEDIUM |
| Size-aware preprocess cache eviction (currently 8 entries regardless of size) | Prevent re-upsampling | MEDIUM |
| Offload STUDY_DOWNLOAD_COMPLETE DB save to executor thread | Eliminate 80–106ms queue spike in Mode B | LOW-MEDIUM |

---

## 8. Phased Implementation Plan

### Phase 1 — v2.2.3.1.6 (Quick wins, low risk) — COMPLETED

- [x] **Cast-once pattern** in `apply_filters()`:  
  Cast to float32 BEFORE noise reduction (was inside `if modality == 'MR'` block — CT never benefited).  
  Cast back once at end of whole pipeline (covers CT and MR).  
  Eliminates 2 explicit + 2 internal ITK int16↔float32 conversions. **~50–150ms saving per series.**

- [x] **`update_corners_actors()` per scroll** — discovered already done: `set_window_level()` has  
  `if not flag_default: update_corners_actors()` guard since v2.2.3.1.0, plus WL scroll-cache  
  short-circuits the mapper call entirely on identical WL. No changes needed.

- [x] **Guard zoom-protection second `Render()`** in `vtk_widget.py` `set_slice()`:  
  Changed reference from `saved_scale` (captured every scroll = accumulated FP drift) to  
  `_protected_parallel_scale` (stable user-set zoom). Tolerance widened 0.001 → 0.05.  
  **Eliminates spurious extra Render() on scroll (~60–80ms saving per scroll).**

### Phase 2 — v2.2.3.1.7 (Cleanup + cache improvement)

- [ ] Dead code removal (~540 lines across 5 files)
- [ ] Consolidate triple DEFAULT_FILTERS to single source (~400 lines saved)
- [ ] Write interactive-load results to ZetaBoost disk cache

### Phase 3 — v2.2.3.2.x (Rendering pipeline)

- [ ] Lazy `ImageReslice.Update()` (defer from `__init__` to first read)
- [ ] Merge triple pipeline flush in `reset_image_viewer()` into single flush
- [ ] Size-aware preprocess cache eviction

### Phase 4 — Future (Architecture)

- [ ] Two-phase display: noise reduction now → sharpening in background (perceived load: 3–7s → ~1s)
- [ ] Consolidate 5 cache layers into unified lookup
- [ ] Modality-aware slice count cap for Mode B

---

## 9. Key Constraints (Do Not Violate)

1. **Do NOT re-sort `metadata['instances']` by IPP** — VTK slices are in instance_number order; IPP sort broke reference lines in v1.09.5–v1.09.7
2. **The stored DirectionMatrix in field data has row 1 negated** (Y-flip compensation from `convert_itk2vtk`); do not compare directly to DICOM normal without un-negating row 1
3. **Do not change filter output quality** without radiologist comparison
4. **`numpy_to_vtk(deep=False)`** — the numpy backing store must stay pinned in memory
5. **ITK thread count must be restored** after `sitk.ProcessObject.SetGlobalDefaultNumberOfThreads()` calls
6. **Mode B `put()` is a no-op when `_image_boost_mode=True`** — DL_WARMUP must set it False before storing, True after

---

## 10. File Reference Map

| File | Role | Last Changed |
|---|---|---|
| `patient_widget_viewer_controller.py` | ViewerController orchestration (5472 lines) | This session |
| `image_filters.py` | ITK filter pipeline (`apply_filters`) | This session |
| `image_io.py` | DICOM load pipeline (`load_single_series_by_number`, `process_series_groups`) | This session |
| `engine.py` | ZetaBoostEngine — LRU cache, 3 lanes, download gates | Unmodified this session |
| `image_slice_booster.py` | Mode B per-slice ±20 slice prefetch | Unmodified this session |
| `subprocess_worker.py` | Subprocess download (own GIL) | Unmodified this session |
| `main_widget.py` | Download manager UI — wires `notify_global_download_start/stop` | Unmodified this session |
| `vtk_widget.py` | VTK rendering widget — zoom-guard tolerance fixed (0.001→0.05, ref→`_protected_parallel_scale`) | ✅ Fixed (Phase 1) |
| `viewer_2d.py` | Double `get_window_level()` fixed (this session); double `update_corners_actors()` was already fixed v2.2.3.1.0 | ✅ All fixed |
| `image_filters.py` | Cast-once pattern implemented; redundant int16↔float32 conversions eliminated | ✅ Fixed (Phase 1) |
