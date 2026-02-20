# ZetaBoost & Image Pipeline — Comprehensive Analysis & Optimization Plan

**Date:** 2026-02-15  
**Scope:** Full pipeline from download → DICOM I/O → ITK filters → VTK conversion → cache → viewer display  
**Goal:** Reduce RAM, improve responsiveness during download, enable progressive viewing

---

## Table of Contents

1. [Current Architecture Summary](#1-current-architecture-summary)
2. [Root Causes of Slowness & Crashes](#2-root-causes-of-slowness--crashes)
3. [Memory Budget Analysis](#3-memory-budget-analysis)
4. [VTK Partial Loading — Myth vs Reality](#4-vtk-partial-loading--myth-vs-reality)
5. [Optimization Strategies](#5-optimization-strategies)
   - [Strategy A: Sliding Window Cache (±N slices)](#strategy-a-sliding-window-cache-n-slices)
   - [Strategy B: Viewed-Series-Only Caching](#strategy-b-viewed-series-only-caching)
   - [Strategy C: Slab-Based Filter Processing](#strategy-c-slab-based-filter-processing)
   - [Strategy D: Deferred Filter Application](#strategy-d-deferred-filter-application)
   - [Strategy E: Progressive Series Loading](#strategy-e-progressive-series-loading)
   - [Strategy F: Memory Reduction in ITK→VTK Path](#strategy-f-memory-reduction-in-itkvtk-path)
6. [Priority Recommendation Matrix](#6-priority-recommendation-matrix)
7. [Implementation Roadmap](#7-implementation-roadmap)
8. [Implementation Details — Phase 1 (Quick Wins)](#8-implementation-details--phase-1-quick-wins)
9. [Implementation Details — Phase 2 (Core Refactor)](#9-implementation-details--phase-2-core-refactor)

---

## 1. Current Architecture Summary

### End-to-End Data Flow

```
User double-clicks patient in HomePanelWidget
    │
    ▼
DownloadManager starts Critical-priority download (series-by-series)
    │
    ▼ (background QThread, per DICOM file)
SeriesDownloader → saves .dcm files to disk → emits seriesDownloadCompleted
    │
    ▼ (Qt signal → PatientWidget.load_series_on_demand)
ViewerController._load_single_series_on_demand()
    │
    ├─ DB fast-path: query instance metadata from SQLite
    ├─ Filesystem fallback: scan folder for .dcm files
    │
    ▼
get_itk_image(dicom_filenames)              ⏱ 2–8s   💾 150 MB (300 slices)
    │ SimpleITK + GDCM pixel decompression
    │ Creates one contiguous 3D array in memory
    │
    ▼
apply_filters(itk_image, metadata)           ⏱ 0.3–6s  💾 450 MB–1.5 GB peak
    │ CT: 1-stage (Gaussian noise reduction)
    │ MR: 4-stage (Gaussian → multiscale sharp → Laplacian → adaptive sharp)
    │ Each filter creates float32 temporaries
    │
    ▼
convert_itk2vtk(itk_image)                  ⏱ 0.5–1s  💾 +450 MB peak (3 copies)
    │ GetArrayFromImage → Y-flip → C-contiguous copy → numpy_to_vtk(deep=False)
    │ Stores DirectionMatrix, ITKOrigin as VTK field data
    │
    ▼
ZetaBoost cache (put) or direct display
    │ Memory cache: dict[series_number] → (vtk_image_data, metadata, est_bytes)
    │ Disk cache: npz + json files in generated-files/zeta_boost_cache/
    │
    ▼
VTKWidget.switch_series() or start_process_series()
    │
    ▼
ImageViewer2D → ImageReslice (cubic) → color_mapper → ImageActor → Render
```

### Key Components

| Component | File | Role |
|-----------|------|------|
| **ZetaBoostEngine** | `zeta_boost/engine.py` | 3-lane priority queue (interactive/warmup/background) + LRU memory cache + disk L2 cache |
| **ZetaBoostDiskCache** | `zeta_boost/disk_cache.py` | npz/json persistence with SQLite manifest, 20 GB / 600 entry limit |
| **ViewerController** | `patient_widget_viewer_controller.py` | Central orchestrator — owns ZetaBoost, manages all viewer lifecycle, caching, prefetching |
| **image_io** | `utils/image_io.py` | DICOM→ITK→VTK conversion pipeline, preview loading |
| **image_filters** | `utils/image_filters.py` | ITK-domain noise reduction + sharpening (modality-specific) |
| **vtk_utils** | `utils/utils.py` | `convert_itk2vtk()` — ITK→VTK with Y-flip + field data storage |
| **VTKWidget** | `ui/patient_ui/vtk_widget.py` | QWidget wrapping VTK render window, slider, spinner |
| **ImageViewer2D** | `viewers/viewer_2d.py` | `vtkResliceImageViewer` subclass — preprocessing, reslice, color mapping |
| **DownloadManager** | `zeta_download_manager/` | Zeta-based download engine with priority queuing |

### Current ZetaBoost Behavior

- **One engine per PatientWidget** (per tab)
- **Caches ALL series** for the opened patient (warmup enqueues every series in the tab)
- **Active only on focused tab** (deactivated + cache cleared on tab switch)
- **3 lanes**: interactive (user actions), warmup (tab open), background (predictive prefetch)
- **Download-aware**: pauses warmup/background lanes while download is active
- **RAM-aware**: checks `psutil.virtual_memory()` — pauses if < 800 MB available
- **Capacity tiers**: 1.2–4.0 GB byte budget, 24–60 entries

---

## 2. Root Causes of Slowness & Crashes

### Problem 1: Warmup Tries to Cache Everything

When a tab opens with ZetaBoost enabled, `_start_open_tab_warmup()` enqueues **all series** for background processing:
- A patient with 20 series × 150 slices = 3,000 images
- Each 512×512 int16 series ≈ 23 MB (150 slices) to 150 MB (1000 slices)
- Caching all 20 series ≈ 460 MB–3 GB of persistent VTK data in memory

Even though warmup pauses during downloads (`set_download_active(True)`), once the download completes, warmup floods the system with ITK filter processing.

### Problem 2: ITK Filter Chain Creates Massive Temporaries

For each series processed by ZetaBoost warmup, the MR filter chain peaks at:

$$\text{Peak} = 5 \times W \times H \times D \times 4 \text{ bytes (float32)}$$

For a 300-slice 512×512 MR stack:
$$5 \times 512 \times 512 \times 300 \times 4 = 1.57 \text{ GB}$$

With `max_parallel_loads = 2`, two concurrent loads can peak at **~3 GB just for filter temporaries**, on top of the already cached data.

### Problem 3: Download + ZetaBoost Compete for Resources

Although ZetaBoost pauses during download, the **series completion signal** triggers `load_series_on_demand()` which runs the full DICOM→filter→VTK pipeline **synchronously on the download completion handler**. This means:

1. Download completes series → signal emits
2. `load_series_on_demand()` → starts ITK loading (2–8s CPU-bound)
3. While this runs, the next series continues downloading (network I/O is separate), but CPU is saturated by ITK
4. When that next series finishes downloading, another `load_series_on_demand()` fires — now two ITK loads compete for CPU

### Problem 4: convert_itk2vtk Creates 3 Copies at Peak

During `convert_itk2vtk()`, three full copies of the pixel data coexist:
1. ITK internal buffer (input)
2. `GetArrayFromImage()` numpy copy
3. C-contiguous copy after Y-flip

For 300 slices at 512×512×int16: 3 × 150 MB = **450 MB** just for conversion. This is transient but compounds with concurrent loads.

### Problem 5: `grow_current_series_inplace` Is Dead Code

Despite being fully implemented in `vtk_widget.py` and `viewer_2d.py`, the grow-in-place mechanism is **never called**. The preview→full transition uses full viewer recreation instead. The slider update code is commented out.

---

## 3. Memory Budget Analysis

### Per-Series Memory Footprint

For a typical 512×512 stack:

| Slices | int16 raw | float32 (filters) | VTK cached |
|--------|-----------|-------------------|------------|
| 50     | 26 MB     | 52 MB             | 26 MB      |
| 150    | 75 MB     | 150 MB            | 75 MB      |
| 300    | 150 MB    | 300 MB            | 150 MB     |
| 1000   | 500 MB    | 1000 MB           | 500 MB     |

### Whole-Patient Memory Scenarios

| Scenario | Series | Total slices | Cached VTK | Filter peak (×2 workers) |
|----------|--------|-------------|------------|--------------------------|
| Small CT | 3      | 900         | 450 MB     | 900 MB                   |
| Typical MR | 8   | 1,200       | 600 MB     | 2.4 GB                   |
| Large MR | 15     | 2,500       | 1.25 GB    | 3.0 GB                   |
| Complex study | 25 | 3,000      | 1.5 GB     | 3.0 GB                   |

### Current Total Memory at Peak

```
Cached VTK data (all series)          : 600 MB – 1.5 GB
+ Filter processing (2 concurrent)    : 1.5 – 3.0 GB
+ convert_itk2vtk transients          : 300 – 450 MB
+ Disk cache I/O buffers              : 50 – 200 MB
+ VTK renderer (preprocessing cache)  : 200 – 400 MB
+ Download manager buffers            : 50 – 100 MB
+ Python/Qt overhead                  : 200 – 400 MB
─────────────────────────────────────────────────────
TOTAL PEAK                            : 2.9 – 6.0 GB
```

On a 16 GB system, this leaves only 10–13 GB for the OS and other processes — tight but survivable. On an 8 GB system, this **easily causes crashes**.

---

## 4. VTK Partial Loading — Myth vs Reality

### Claim: "VTK cannot display until the full series is loaded"

**This is FALSE.** VTK can render any number of slices from 1 upward. The proof exists in the codebase:

1. **`load_series_preview()`** loads a single slice and displays it immediately
2. **`grow_vtk_inplace()`** / **`grow_current_series_inplace()`** can progressively add slices to a live viewer
3. **`vtkImageReslice`** works with any Z extent ≥ 1

### What VTK Actually Requires

1. A `vtkImageData` with valid `Dimensions`, `Spacing`, `Origin`, `Extent`
2. A scalar array (pixel data) matching those dimensions
3. The dimensions can be changed at runtime by calling `SetDimensions()`, `SetExtent()`, `Modified()`

### The Real Constraint

`vtkResliceImageViewer.UpdateDisplayExtent()` determines the valid slice range from the input extent. If you grow the data without calling `UpdateDisplayExtent()`, the viewer won't know about new slices. This is a **calling convention issue, not a VTK limitation**.

### What Other PACS Systems Do

Commercial PACS viewers (Horos, OsiriX, RadiAnt) typically:
1. Allocate a full-extent `vtkImageData` with zero-filled scalars
2. Stream DICOM slices into the scalar array as they download
3. The viewer can navigate the entire slice range immediately (seeing black for unloaded slices)
4. As slices arrive, the display updates progressively

This is exactly what our `grow_current_series_inplace` was designed for — it just needs to be activated and fixed.

---

## 5. Optimization Strategies

### Strategy A: Sliding Window Cache (±N slices)

**Concept:** Instead of caching entire series in VTK format, only keep ±N slices (e.g., ±10) around the current viewing position in full VTK resolution. The rest of the DICOM data remains on disk.

**How it works:**
1. DICOM files are already on disk after download
2. When user switches to a series, read only the central ±10 slices from DICOM
3. Apply ITK filters to only those 21 slices (not the full 300+)
4. As user scrolls, read and process new boundary slices
5. Evict slices that fall outside the window

**VTK implementation:**
- Allocate `vtkImageData` with **full Z extent** (all slices dimensioned)
- Fill scalars with zeros initially
- Populate only the active window with real pixel data
- On scroll, update the scalar sub-array using pointer manipulation
- Call `Modified()` + debounced `Render()`

**Pros:**
- Dramatically reduces RAM: 21 slices × 512×512×2 = **11 MB** vs 300 slices = **150 MB** (93% reduction)
- Filter processing on 21 slices takes ~0.1s vs ~3–6s for full volume
- Near-instant series switching

**Cons:**
- Z-direction Gaussian filter needs overlap slices (±3 kernel radius) = 27 slices instead of 21
- Scrolling near window boundaries may show brief artifacts/black before new slices load
- Complex implementation — needs scroll event interception, async loader, buffer management
- **Some VTK operations (3D reslice for oblique views, MPR) need the full volume**
- Not compatible with current preprocessing cache (upsampling needs full volume)

**Verdict:** High impact but high complexity. Best suited as a Phase 3 optimization. Requires careful VTK pipeline management and may break MPR/3D features.

**Estimated effort:** 3–4 weeks  
**RAM reduction:** 80–93% for cached data  
**Speed improvement:** ~95% faster series switching (from cache)

---

### Strategy B: Viewed-Series-Only Caching

**Concept:** Instead of caching all series for the patient, only cache the series currently displayed in active viewers (typically 1–4 series). Other series are loaded on demand.

**How it works:**
1. ZetaBoost only processes and caches the currently viewed series
2. When user switches to a new series via drag-drop, load it on demand (with preview-first)
3. Previously viewed series can remain in a small LRU (e.g., 4–6 entries) for quick back-navigation
4. Warmup/background lanes are disabled or limited to adjacent series only

**Changes required:**
- Modify `_start_open_tab_warmup()` to **not enqueue all series**
- Reduce `max_entries` from 24–60 down to 6–8
- Reduce `byte_budget` from 1.2–4 GB down to 400–800 MB
- Change `enqueue_many_warmup()` to only enqueue series visible in the current layout + 1–2 adjacent

**Pros:**
- Simple to implement (mostly parameter changes + logic changes in warmup)
- Immediate RAM reduction proportional to series count
- No VTK pipeline changes needed
- No risk to MPR/3D features

**Cons:**
- Series switching becomes slower (no warmup cache hit) — ~3–10s per switch
- User experiences loading spinners when switching series
- Can be mitigated by predictive prefetch of 2–3 most-likely-to-be-viewed series

**Verdict:** **Best first step.** Low risk, immediate benefit, easy to implement and rollback.

**Estimated effort:** 2–3 days  
**RAM reduction:** 60–80%  
**Speed impact:** Series switching ~3–10s slower (mitigated by preview-first)

---

### Strategy C: Slab-Based Filter Processing

**Concept:** Instead of applying ITK filters to the entire 3D volume at once, process in slabs of 16–32 slices. This dramatically reduces peak memory for the filter chain.

**How it works:**
1. Split the full ITK image into overlapping slabs along Z
2. For each slab, apply the full filter chain (Gaussian → sharpening → ...)
3. Trim the overlap region and concatenate results
4. Feed the concatenated result to `convert_itk2vtk()`

**Overlap calculation:**
- The Z-direction Gaussian with σ=0.25mm and typical slice thickness 1mm needs ~3 slices of overlap
- So a 32-slice slab with 3-slice overlap on each side = 38 slices read, 32 slices output
- For a 300-slice volume: ceil(300/32) = 10 slabs

**Memory comparison (300-slice MR stack):**

| | Current (full volume) | Slab-based (32-slice slab) |
|---|---|---|
| Input slab | 150 MB | 19.5 MB (38 slices) |
| Filter peak (5× float32) | **1.5 GB** | **98 MB** |
| Output slab | 150 MB | 16 MB |
| Total peak | **~1.8 GB** | **~134 MB** |

**Pros:**
- **93% reduction in peak filter memory**
- No changes to VTK pipeline, caching, or viewer
- Each slab is processed faster (better CPU cache utilization)
- Can be parallelized: process 2 slabs on 2 threads

**Cons:**
- Slight quality difference at slab boundaries due to overlap handling
- Total wall-clock time may be slightly higher (slab overhead) but peak memory is massively lower
- XY-only filters (which is most of them) don't need Z overlap — can process slice-by-slice
- Z-direction Gaussian needs careful overlap management
- SimpleITK doesn't natively support slab extraction; need `itk_image[:, :, start:end]`

**Verdict:** **Highest-impact memory optimization.** Can be combined with any other strategy. The XY-only fast path for CT (>320 slices) is already a step in this direction.

**Estimated effort:** 1–2 weeks  
**RAM reduction:** 90%+ for filter processing  
**Speed impact:** Neutral to slightly positive (better cache behavior)

---

### Strategy D: Deferred Filter Application

**Concept:** Cache raw (unfiltered) VTK data during warmup. Apply filters only when the user actually views a series. This separates the "have data ready" concern from the "make data pretty" concern.

**How it works:**
1. ZetaBoost warmup loads DICOM → ITK → `convert_itk2vtk()` (skip filters) → cache raw VTK
2. When user switches to a series:
   a. Display the raw (unfiltered) VTK data immediately (acceptable for navigation)
   b. Apply filters asynchronously on the background
   c. Once filtered data is ready, hot-swap it into the viewer
3. Cache the filtered version, evicting the raw version

**Cache entry states:**
```
RAW    → loaded from DICOM, no filters applied (fast warmup)
READY  → fully filtered and display-ready (post-view processing)
```

**Pros:**
- Warmup is ~50–70% faster per series (skips filter chain = saves 1–6s)
- Warmup RAM peak drops dramatically (no float32 filter temporaries)
- User sees the image immediately (raw → filtered transition is barely noticeable for CT)
- For MR, raw display is still diagnostically acceptable for navigation
- Filter application only happens for actually-viewed series

**Cons:**
- Two versions of the data may coexist briefly (raw + filtered) during the transition
- Raw images look slightly noisier/less sharp — acceptable for seconds, not for diagnosis
- Adds complexity: need a "filter_applied" flag per cache entry
- The hot-swap from raw→filtered needs careful VTK pipeline management

**Verdict:** **Excellent complementary strategy.** Makes warmup lightweight and moves heavy work to the moment of viewing, where it's amortized by user perception time.

**Estimated effort:** 1 week  
**RAM reduction:** 50–70% during warmup  
**Speed improvement:** 50–70% faster warmup, near-instant series switching from cache

---

### Strategy E: Progressive Series Loading

**Concept:** Instead of loading all slices of a series before displaying, show the first slice immediately and progressively add slices as they're read from disk.

**Current state:** The code for this exists (`grow_current_series_inplace`, `grow_vtk_inplace`, `load_series_preview`) but **is not connected**. The preview→full transition uses full viewer recreation.

**How to activate:**
1. Fix `grow_current_series_inplace` — uncomment slider update code
2. Fix `grow_input_image_inplace` — add `UpdateDisplayExtent()` call after dimension change
3. In `_schedule_async_load_and_switch()`, use grow-in-place instead of viewer recreation for preview→full transition
4. Modify `load_single_series_by_number()` to yield partial results (e.g., every 50 slices)

**Pros:**
- User sees something instantly (first slice in <0.5s)
- Progressive feedback — slider grows, image fills in
- No wasted work — if user switches away, partial load can be abandoned

**Cons:**
- ITK filters can't be applied to partial data without the slab approach
- Preview→full transition currently forces viewer recreation (needs fixing)
- Slider behavior during growth needs careful UX handling

**Verdict:** Already partially built. Fixing the dead code + connecting preview→grow is a medium effort with good UX payoff.

**Estimated effort:** 1 week  
**RAM reduction:** Indirect (user switches away from unneeded series sooner)  
**Speed improvement:** Perceived instant display (< 0.5s to first image)

---

### Strategy F: Memory Reduction in ITK→VTK Path

**Concept:** Eliminate one of the three copies created during `convert_itk2vtk()`.

**Specific optimizations:**

#### F1: In-place Y-flip (eliminates copy #3)
Currently: `arr[:, ::-1, :]` creates a non-contiguous view, then `.copy()` makes it contiguous.

Replace with:
```python
arr = sitk.GetArrayFromImage(itk_image)  # copy #2
np.flip(arr, axis=1)                       # returns view (no copy)
arr = np.ascontiguousarray(arr)            # copy #3 — STILL needed
```

Better approach — VTK coordinate flip:
```python
arr = sitk.GetArrayFromImage(itk_image)  # copy #2 (contiguous)
# Apply Y-flip via VTK reslice coordinate transform instead of numpy
# This eliminates copy #3 entirely
```

Or use `deep=True` in `numpy_to_vtk`:
```python
arr = sitk.GetArrayFromImage(itk_image)
arr = arr[:, ::-1, :]  # view
vtk_arr = numpy_support.numpy_to_vtk(arr.ravel(), deep=True)  # VTK copies, handles non-contiguous
# Now arr can be freed immediately
```

#### F2: Delete ITK image before VTK conversion
Currently `del itk_image` happens after `convert_itk2vtk()` returns. Move it inside:
```python
arr = sitk.GetArrayFromImage(itk_image)
del itk_image  # free 150 MB before creating the contiguous copy
gc.collect()
arr = np.ascontiguousarray(arr[:, ::-1, :])
```

This reduces peak from 3 simultaneous copies to 2.

#### F3: Defensive numpy reference on VTK object
```python
vtk_image._numpy_backing_store = arr  # prevent GC of the numpy array
```

**Estimated effort:** 1–2 days  
**RAM reduction:** 150 MB per series during conversion (33% of conversion peak)  

---

## 6. Priority Recommendation Matrix

| Priority | Strategy | Effort | RAM Impact | Speed Impact | Risk |
|----------|----------|--------|------------|--------------|------|
| **P0** | **B: Viewed-Series-Only Caching** | 2–3 days | -60–80% | Neutral | Low |
| **P0** | **F: Memory Reduction in ITK→VTK** | 1–2 days | -150 MB/series | Neutral | Very Low |
| **P1** | **D: Deferred Filter Application** | 1 week | -50% warmup | +50–70% faster warmup | Low |
| **P1** | **E: Fix Progressive Loading** | 1 week | Indirect | Instant first image | Medium |
| **P2** | **C: Slab-Based Filtering** | 1–2 weeks | -90% filter peak | Neutral | Medium |
| **P3** | **A: Sliding Window (±10)** | 3–4 weeks | -90% cached data | ~Instant switching | High |

---

## 7. Implementation Roadmap

### Phase 1: Quick Wins (Week 1) — Strategies B + F

**Goal:** Reduce RAM by 60–80% with minimal code changes.

1. **Limit warmup to viewed + adjacent series** (not all series)
2. **Reduce ZetaBoost cache capacity** to 6–8 entries / 600 MB
3. **Eliminate one copy in convert_itk2vtk** with early `del itk_image`
4. **Throttle concurrent loads during download** to max 1

### Phase 2: Core Refactor (Weeks 2–3) — Strategies D + E

**Goal:** Make warmup lightweight and viewing progressive.

1. **Deferred filters:** Cache raw VTK during warmup, apply filters on view
2. **Activate grow-in-place:** Fix dead code, connect preview→grow pipeline
3. **Add smart prefetch:** Predict next 2–3 series based on current view layout

### Phase 3: Deep Optimization (Weeks 4–6) — Strategies C + A

**Goal:** Approach the memory and speed profile of commercial PACS viewers.

1. **Slab-based filtering:** Process 16–32 slice slabs instead of full volumes
2. **Sliding window (if needed):** Only load ±10 slices for extreme cases
3. **Progressive DICOM streaming:** Show slices as they download

---

## 8. Implementation Details — Phase 1 (Quick Wins)

### 8.1 Limit Warmup to Viewed + Adjacent Series

**File:** `patient_widget_viewer_controller.py`

**Current behavior** (`_start_open_tab_warmup` → `_open_tab_warmup_worker`):
- Gathers ALL series from thumbnails + filesystem
- Enqueues light (≤500 slices) via `enqueue_many_warmup()`
- Enqueues heavy (>500 slices) 1.5s later

**Proposed change:**
```python
def _open_tab_warmup_worker(self):
    # Instead of all series, only warmup:
    # 1. Series currently displayed in active viewers (already loaded)
    # 2. 2-3 series adjacent to displayed ones in the thumbnail list
    
    displayed = self._get_displayed_series_numbers()
    adjacent = self._get_adjacent_series(displayed, count=2)  # ±2 in thumbnail order
    
    candidates = [s for s in adjacent if s not in displayed]
    candidates = candidates[:6]  # Hard cap at 6 warmup series
    
    if candidates:
        self._zeta_boost_engine.enqueue_many_warmup(candidates)
```

### 8.2 Reduce ZetaBoost Capacity

**File:** `patient_widget_viewer_controller.py` → `_compute_dynamic_capacity()`

**Current tiers:**

| RAM | Budget | Entries |
|-----|--------|---------|
| ≥30 GB | 4 GB | 60 |
| ≥15 GB | 2.4 GB | 48 |

**Proposed tiers:**

| RAM | Budget | Entries |
|-----|--------|---------|
| ≥30 GB | 800 MB | 8 |
| ≥15 GB | 600 MB | 6 |
| ≥7.5 GB | 400 MB | 4 |
| <7.5 GB | 300 MB | 3 |

This alone reduces peak cached data from 1.5–4 GB to 300–800 MB.

### 8.3 Early ITK Cleanup in convert_itk2vtk

**File:** `utils/utils.py` → `convert_itk2vtk()`

Move `del itk_image` **inside** the function, immediately after `GetArrayFromImage`:

```python
def convert_itk2vtk(itk_image):
    # ... extract metadata from itk_image ...
    arr = sitk.GetArrayFromImage(itk_image)
    
    # Free the ITK buffer BEFORE creating the contiguous copy
    # This reduces peak memory by ~150 MB per series
    del itk_image
    
    arr = arr[:, ::-1, :]  # Y-flip (non-contiguous view)
    if not arr.flags['C_CONTIGUOUS']:
        arr = arr.copy()  # Now only 2 copies exist, not 3
    
    # ... rest of VTK construction ...
```

### 8.4 Throttle During Download

**File:** `patient_widget_viewer_controller.py`

The `set_download_active()` mechanism already exists. Ensure it's called reliably:

```python
# In _connect_download_manager_to_widget or equivalent:
def _on_download_started(study_uid):
    for widget in active_patient_widgets:
        widget.viewer_controller._zeta_boost_engine.set_download_active(True)
        
def _on_download_completed(study_uid):
    for widget in active_patient_widgets:
        widget.viewer_controller._zeta_boost_engine.set_download_active(False)
```

Also reduce `max_parallel_loads` during download from 2 → 1:

```python
# In load_series_on_demand, if download is active:
# Queue serial loading, don't start parallel ITK processing
```

---

## 9. Implementation Details — Phase 2 (Core Refactor)

### 9.1 Deferred Filter Application

**New cache entry structure:**
```python
# In ZetaBoostEngine, change cache value from:
#   (vtk_image_data, metadata, est_bytes)
# To:
#   (vtk_image_data, metadata, est_bytes, filter_state)
# Where filter_state is one of: "raw", "filtered", "filtering"
```

**Warmup path (fast — skip filters):**
```python
def _zeta_boost_load_series_raw(self, series_number):
    """Load DICOM → ITK → VTK without filters. For warmup only."""
    # ... load DICOM files ...
    itk_image = get_itk_image(dicom_names)
    # SKIP: apply_filters(itk_image, metadata)
    vtk_image_data = convert_itk2vtk(itk_image)
    del itk_image
    self._zeta_boost_engine.put(series_number, vtk_image_data, metadata, 
                                 filter_state="raw")
```

**View path (apply filters on demand):**
```python
def change_series_on_viewer(self, viewer, series_number):
    cached = self._zeta_boost_engine.query(series_number)
    if cached:
        vtk_data, meta, _, filter_state = cached
        if filter_state == "raw":
            # Display raw immediately for instant response
            viewer.switch_series(vtk_data, meta, ...)
            # Schedule filter application in background
            self._schedule_background_filter(series_number, vtk_data, meta)
        else:
            # Already filtered — instant display
            viewer.switch_series(vtk_data, meta, ...)
```

### 9.2 Smart Prefetch Strategy

Instead of prefetching all series, predict the next 2–3 based on:

1. **Layout adjacency**: In a 2×2 layout, prefetch the other 2 visible slots
2. **Thumbnail order**: Prefetch the series above/below current in thumbnail list
3. **Historical patterns**: Track which series are commonly viewed together

```python
def _predict_next_series(self, current_series_number, count=3):
    """Predict which series the user is likely to view next."""
    candidates = []
    
    # 1. Other visible viewer slots that are empty
    for viewer in self._viewers:
        if viewer.is_empty() and viewer.is_visible():
            # Suggest the next series in thumbnail order
            next_sn = self._get_next_thumbnail_series(current_series_number)
            if next_sn:
                candidates.append(next_sn)
    
    # 2. Adjacent in thumbnail list (±2)
    adj = self._get_adjacent_series([current_series_number], count=2)
    candidates.extend(adj)
    
    # Deduplicate, exclude already cached
    seen = set()
    result = []
    for c in candidates:
        if c not in seen and not self._zeta_boost_engine.has_in_memory(c):
            seen.add(c)
            result.append(c)
    return result[:count]
```

### 9.3 Activate Grow-In-Place for Progressive Loading

**Fix 1: Uncomment slider update** in `vtk_widget.py`:
```python
def grow_current_series_inplace(self, new_vtk_image_data, new_metadata):
    grown = self.image_viewer.grow_input_image_inplace(new_vtk_image_data, new_metadata)
    if grown and hasattr(self, "slider"):
        max_slice = self.get_count_of_slices() - 1
        self.slider.setMaximum(max(0, max_slice))
    return grown
```

**Fix 2: Add `UpdateDisplayExtent()`** in `viewer_2d.py` → `grow_input_image_inplace()`:
```python
# After updating dimensions/extent/scalars:
self.image_reslice._reslice.Modified()
self.image_reslice._reslice.Update()
self.UpdateDisplayExtent()  # Critical — tells viewer about new Z range
self._schedule_render(50)
```

**Fix 3: Connect in ViewerController:**
```python
def _on_series_partially_loaded(self, series_number, vtk_data, metadata, progress):
    """Called when a batch of slices is loaded."""
    for viewer in self._get_viewers_showing(series_number):
        viewer.vtk_widget.grow_current_series_inplace(vtk_data, metadata)
    # Update slider label: "Loading... 150/300"
```

---

## Appendix: Key Files Reference

| File | Lines | Purpose |
|------|-------|---------|
| `PacsClient/pacs/patient_tab/zeta_boost/engine.py` | 964 | ZetaBoost engine — cache + queue + workers |
| `PacsClient/pacs/patient_tab/zeta_boost/disk_cache.py` | 426 | L2 disk cache with SQLite manifest |
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` | 4219 | Central orchestrator |
| `PacsClient/pacs/patient_tab/utils/image_io.py` | 1176 | DICOM→ITK→VTK loading |
| `PacsClient/pacs/patient_tab/utils/image_filters.py` | 1407 | ITK filter chain |
| `PacsClient/pacs/patient_tab/utils/utils.py` | ~300 | convert_itk2vtk + helpers |
| `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget.py` | ~950 | VTK render widget |
| `PacsClient/pacs/patient_tab/viewers/viewer_2d.py` | ~1200 | 2D viewer with reslice |
| `PacsClient/zeta_download_manager/download/executor.py` | ~500 | Download orchestration |
| `PacsClient/pacs/workstation_ui/home_ui/home_ui.py` | ~4000 | Patient list + tab opening |
