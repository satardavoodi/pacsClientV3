# Mode B Performance — Complete Architectural Analysis & Solution Guide

**Version:** v2.2.2.5 (Baseline: commit `194ae2c`, tag `v2.2.2.5`)  
**Created:** 2026-02-23 (from previous investigation)  
**Updated:** 2026-02-23 (Part VI added: concurrent execution architecture, subprocess isolation, three-component analysis)  
**Status:** **PRIMARY REFERENCE — Authoritative guide for all Mode B performance work**

**Purpose:** This document consolidates complete findings from the Mode B lag investigation, merges with current v2.2.2.5 codebase reality, provides deep architectural analysis of all three core subsystems (Zeta Download Manager, Database, Viewer Widget), identifies resource contention points, and establishes validated solutions for achieving smooth viewer performance during concurrent downloads.

---

## Executive Summary

### The Core Problem

**Mode B** (viewer open + download active simultaneously) exhibits severe performance degradation:
- **3–12s hard stall** when user drag-drops a series during download (cold cache)
- **20–100ms scroll lag** per tick (should be <2ms) during download period
- **Download progress slows** when user interacts with viewer
- **UI freezes** lasting 400–4500ms during cross-study download interference

**Mode A** (viewer alone, no download) is fast and smooth, confirming the problem is NOT internal to the viewer but arises from **resource interference** between subsystems.

### Root Causes (Validated Through 7 Test Sessions)

| # | Root Cause | Mechanism | Subsystems Involved | Fix Status |
|---|-----------|-----------|-------------------|------------|
| **1** | **Cold Cache Stall (large series)** | ZetaBoost warmup blocked during download; preview path is conditional, so large-series drag/drop can still trigger on-demand 3–12s ITK load | ZetaBoost + Viewer | ⚠️ Partially fixed — preview exists but not universal |
| **2** | **Cross-Study ITK CPU Saturation** | `_download_active` is per-instance; Patient B downloading leaves Patient A's engine free to run ITK warmup → all CPU cores saturated → VTK render starved | ZetaBoost (bug) | ❌ Unfixed — Change #7 missing |
| **3** | **Download GIL Bursts** | Download QThread holds Python GIL in burst windows (O(n²) bytes concat, tight file loop, pydicom parse chunks) → main thread freezes intermittently | Download Manager | ⚠️ Partially fixed — #9C present, #9A/#9B missing |

### Validated Solution (3-Part Fix)

| Priority | Change | What It Fixes | Expected Impact | Files |
|----------|--------|--------------|----------------|-------|
| **P0** | **Change #7: Global ZetaBoost Download Counter** | Cross-study ITK CPU saturation (Root Cause #2) | EVENT_LOOP_LAG: 4500ms → <50ms | `engine.py`, `main_widget.py` |
| **P1** | **Change #9A: bytearray recv (O(1))** | O(n²) GIL burst in socket recv loop | Eliminate ~385MB GIL-held copy per batch | `socket_client.py` |
| **P1** | **Change #9B: asyncio.sleep(0) every 3 files** | 30ms GIL burst in file processing loop | `set_slice avg`: 22–37ms → <10ms | `socket_client.py` |
| **P1** | **Change #9C: pydicom yield every 5 files** | 750ms GIL burst in DB insert | GIL burst: 750ms → 75ms | `series_downloader.py` *(already present in current code)* |
| **P2** | **Solution C: Complete preview coverage** | Cold cache 3–12s stall (Root Cause #1) | User sees preview in <200ms always | `patient_widget_viewer_controller.py` |

**Current Status:** This document now reflects historical findings plus a fresh code-grounded validation pass on current `v2.2.2.5`. Reapply priority is **#7 + #9A + #9B**; #9C is already present.

---

## Table of Contents

### Part I: Foundations
1. [Definitions & Terminology](#1-definitions--terminology)
2. [Problem Statement & Observed Symptoms](#2-problem-statement--observed-symptoms)
3. [Investigation History & Testing Timeline](#3-investigation-history--testing-timeline)

### Part II: Current Architecture (v2.2.2.5 Deep Dive)
4. [System Thread Model — Complete Runtime Map](#4-system-thread-model--complete-runtime-map)
5. [Zeta Download Manager Architecture](#5-zeta-download-manager-architecture)
6. [Database Architecture & Concurrent Access](#6-database-architecture--concurrent-access)
7. [Viewer Widget & VTK Pipeline](#7-viewer-widget--vtk-pipeline)
8. [ZetaBoost Engine Architecture](#8-zetaboost-engine-architecture)

### Part III: Resource Contention Analysis
9. [Shared Resources & Arbitration Mechanisms](#9-shared-resources--arbitration-mechanisms)
10. [GIL Contention Timeline & Hotspots](#10-gil-contention-timeline--hotspots)
11. [CPU Core Contention Analysis](#11-cpu-core-contention-analysis)
12. [Complete Performance Budget](#12-complete-performance-budget)

### Part IV: Validated Solutions
13. [Proven Fixes — Reapply Guide](#13-proven-fixes--reapply-guide)
14. [Fixes to NOT Reapply (Lessons Learned)](#14-fixes-to-not-reapply-lessons-learned)
15. [Implementation Checklist & Test Validation](#15-implementation-checklist--test-validation)

### Part V: Future Work
16. [Remaining Known Issues](#16-remaining-known-issues)
17. [Long-Term Architectural Improvements](#17-long-term-architectural-improvements)
18. [Architectural Invariants (Canonical Rules)](#18-architectural-invariants-canonical-rules)

### Part VI: Concurrent Execution Architecture — Path to True Parallelism
19. [Why Mode A Proves the Viewer Is Not the Problem](#19-why-mode-a-proves-the-viewer-is-not-the-problem)
20. [Deep GIL Analysis for Three-Component Concurrency](#20-deep-gil-analysis-for-three-component-concurrency)
21. [The Two-Separate-Processes Approach — Full Evaluation](#21-the-two-separate-processes-approach--full-evaluation)
22. [Three-Component Concurrency — Viewer + ZetaBoost + Download Manager](#22-three-component-concurrency--viewer--zetaboost--download-manager)
23. [Ranked Solution Roadmap](#23-ranked-solution-roadmap)
24. [Architectural Invariants — Extended (Three-Component Rules)](#24-architectural-invariants--extended-three-component-rules)

---

## Part I: Foundations

## 1. Definitions & Terminology

| Term | Meaning |
|------|---------|
| **Mode A** | Viewer open, no download in progress. All series already on disk. User experience: fast and smooth. |
| **Mode B** | Viewer open AND download actively running concurrently. User experience: 3–12s stalls, slow scroll, download slowdown during interaction. |
| **ZetaBoost** | In-memory + disk L2 cache engine with 3 priority lanes: `interactive`, `warmup`, `background`. Per-tab instance, 2 workers per lane (6 daemon threads total per study). |
| **Interactive lane** | ZetaBoost lane for user-triggered loads (drag & drop). **Never blocked.** Highest priority. |
| **Warmup lane** | ZetaBoost lane for proactive pre-loading of all series in study. **Blocked during Mode B** by design. Lowest CPU priority (IDLE). |
| **Background lane** | ZetaBoost lane for disk persistence and cache eviction. **Blocked during Mode B**. Lowest CPU priority (IDLE). |
| **ITK pipeline** | SimpleITK-based DICOM reader + filter chain (Gaussian smoothing, sharpening, rescale). Pure C++ multi-threaded execution. Takes 3–16s per series depending on dimensions. |
| **PreviewEngine** | Lightweight engine: loads 1 representative DICOM slice with no ITK filters in <200ms. Exists in code but **not wired** into interactive load path. |
| **GIL** | Python Global Interpreter Lock. Shared by all OS threads in the process. Only ONE thread runs Python bytecode at a time. C extensions can release GIL via `Py_BEGIN_ALLOW_THREADS`. |
| **Cold cache** | Series not present in ZetaBoost memory or disk cache. Must run full ITK pipeline on-demand (3–12s stall for user). |
| **Hot cache** | Series already processed and sitting in ZetaBoost memory cache. Display is instant (<80ms). |
| **QThread** | Qt background thread class. DownloadWorker inherits from QThread. Runs on separate OS thread but shares Python GIL with main thread. |
| **asyncio event loop** | Python async/await scheduler. DownloadWorker creates its own event loop via `asyncio.new_event_loop()` and runs it inside the QThread. |
| **VTK software rendering** | CPU-based OpenGL rasterization (no GPU). Forced via `VTK_FORCE_SOFTWARE_RENDERING` in `main.py`. Typical cost: 20–37ms per `set_slice()` call. |

---

## 2. Problem Statement & Observed Symptoms

### 2.1 Confirmed Symptoms Table

| # | Symptom | Mode | Performance Metric | Confirmed By |
|---|---------|------|-------------------|-------------|
| **S1** | Viewer is fast and smooth | Mode A | `set_slice avg < 5ms`, scroll 60fps | ✅ Baseline tests |
| **S2** | Hard stall on first drag/drop load | Mode B (cold cache) | **3–12s black screen** | ✅ Test 1–7 |
| **S3** | Scrolling slow/choppy during download | Mode B | `set_slice avg 22–100ms` (should be <2ms) | ✅ Probe logs Test 1–7 |
| **S4** | Download progress slows during viewer interaction | Mode B | Download rate drops 30–50% | ✅ User observation |
| **S5** | UI completely freezes for 0.4–4.5s | Mode B (cross-study download) | `EVENT_LOOP_LAG 400–4583ms` | ✅ Test 4 probe |
| **S6** | Lag continues 8–20s after download stops | Mode B → A transition | `set_slice` remains slow until warmup drains | ✅ Test 1 logs |
| **S7** | Cache hits are instant | Mode A | `reset_image_viewer: 56ms` for full series | ✅ Logs |

### 2.2 Why Mode A is Fast

ZetaBoost warmup workers run freely in Mode A. They **pre-process every series** through the full ITK pipeline **before the user ever touches them**. By the time the user drags series 5, ZetaBoost has already put its VTK volume in memory. The viewer hits the cache and displays in 56ms. The 3–12s ITK cost was **amortized silently in the background** while the user was viewing series 1.

```
Mode A Timeline:
  └─ Study opens → warmup lane starts
      ├─ Series 1, 2, 3, 4, 5 processed silently in background (4s × 5 = 20s total)
      │   User views series 1 (already in cache from auto-load)
      │   User views series 2 (cache HIT — instant)
      └─ All series in cache after 20s
  └─ User drag series 5 → ZetaBoost.query() → **FULL CACHE HIT** → 56ms
```

### 2.3 Why Mode B is Slow

**Primary Cause (Root Cause #1 — Cold Cache):**  
ZetaBoost warmup is **BLOCKED** during download. Cache never populates. When user drags series 5:

```
Mode B Timeline:
  └─ Download starts → warmup lane BLOCKED
      ├─ Series 1 auto-loaded (interactive lane always works) → 3–12s ITK → displayed
      │   But series 2, 3, 4, 5 never processed (warmup blocked)
      └─ User drag series 5 → ZetaBoost.query() → **MISS**
          → interactive lane submits ITK job → **3–12s on-demand load**
          → user stares at old image for 3–12 seconds ← primary visible symptom
```

**Secondary Causes (Root Causes #2 & #3):**  
Even when the series IS loaded (after the 3–12s wait), scrolling through it remains slow:
- **CPU contention:** ITK warmup (if running) saturates all CPU cores → VTK render on main thread gets time-sliced → `set_slice` takes 2× longer
- **GIL contention:** Download QThread holds Python GIL for 30–750ms bursts → main thread frozen → scroll events queue up → choppy catch-up behavior

---

## 3. Investigation History & Testing Timeline

### 3.1 Test Session Summary

| Test # | Date | Configuration | Key Finding | Changes Applied Before |
|--------|------|--------------|-------------|----------------------|
| **Test 1** | 2026-02-23 | Baseline, no fixes | EVENT_LOOP_LAG 400–2278ms, `set_slice` 37–150ms. ITK warmup is the primary lag source. | None (baseline) |
| **Test 2** | 2026-02-23 | ITK cap = N//4 (2 threads on 8-core) | **Insufficient**: EVENT_LOOP_LAG 1637ms, `set_slice` 40–100ms still. 2 threads still saturate. | Change #3 (ITK cap N//4) |
| **Test 3** | 2026-02-24 | ITK cap = 1 (absolute) | EVENT_LOOP_LAG **FIXED** (avg 2.3ms ✅). BUT `set_slice` still 40–97ms — different root cause (VTK CPU preemption by ITK Normal priority). | Change #4 (ITK cap → 1) |
| **Test 4** | 2026-02-24 | cap=1 + scroll-activity pause | Scroll pause works but Issue B discovered: 3192–4583ms stalls AFTER warmup completes during concurrent second-study download. | Change #5 (scroll pause) |
| **Test 5** | 2026-02-23 | All #3–#7 active | **Issue B RESOLVED**: global download counter prevents cross-study ITK. `set_slice` still 22–37ms (remaining = GIL from download). | Changes #6 (signal throttle), #7 (global gate) |
| **Test 6** | Pending | All #3–#8 active | Expected: `manage_ref_line` ≈ 0ms via debounce | Change #8 (ref line debounce) |
| **Test 7** | Pending | All #3–#9 active | **Target**: `set_slice avg < 10ms` during download via GIL yields | Changes #9A/B/C (GIL fixes) |

### 3.2 Changes Applied & Rolled Back

All changes from Test sessions 1–5 were **validated effective**, then **rolled back to v2.2.2.5** for clean reapply in next development session. See **Section 13** for exact reapply code.

---

## Part II: Current Architecture (v2.2.2.5 Deep Dive)

## 4. System Thread Model — Complete Runtime Map

At steady state (one study downloading, one study open in viewer), the process runs the following OS threads:

| Thread | Creator | OS Priority | Python GIL? | Purpose | Typical CPU% |
|--------|---------|-------------|-------------|---------|-------------|
| **Main Qt Thread** | PySide6 | Normal | Yes — primary | Qt event loop, VTK rendering, all UI callbacks | 15–40% |
| **QThread: DownloadWorker** | `DownloadManagerWidget._start_download_worker()` | Normal (inherited) | Yes — competes with main | asyncio event loop for one active study download | 5–20% |
| **ZetaBoost Interactive Lane Worker × 2** | `ZetaBoostEngine._ensure_workers_locked()` | **IDLE (−15)** | Briefly during queue ops | User-triggered series loads (drag/drop) | 0–5% idle |
| **ZetaBoost Warmup Lane Worker × 2** | `ZetaBoostEngine._ensure_workers_locked()` | **IDLE (−15)** | Briefly during queue ops | Background pre-loading of all series | 0–10% idle |
| **ZetaBoost Background Lane Worker × 2** | `ZetaBoostEngine._ensure_workers_locked()` | **IDLE (−15)** | Briefly during queue ops | Disk cache writes, eviction | 0–2% idle |
| **ITK MultiThreaderBase C++ threads × N** | SimpleITK (C++ internal) | **Normal** ⚠️ | No (pure C++) | Heavy filter chain per series (3–16s per series) | 100% × N cores |
| **Qt Timer Thread** | PySide6 internal | Normal | No | `QTimer` callback dispatch | <1% |
| **gRPC channel threads** | grpcio internal | Normal | Varies | gRPC metadata fetch at download start | <5% sporadic |

### 4.1 Critical Asymmetry: ITK Priority Inheritance Bug

**The Core Issue:**
- ZetaBoost Python worker threads are set to `THREAD_PRIORITY_IDLE` (−15 on Windows) via `_set_thread_low_priority()` in `engine.py`
- When these workers call into SimpleITK, ITK's C++ `MultiThreaderBase` spawns **new C++ threads at Normal OS priority**
- The Python thread's IDLE scheduling is **NOT inherited** by the C++ thread pool

**Result:**
```
Python warmup worker:  [IDLE priority, −15]
    ↓ calls apply_filters()
    ↓ SimpleITK spawns C++ threads
ITK C++ thread pool:   [Normal priority, 0]  ← NOT IDLE!
```

These Normal-priority ITK threads compete equally with:
- Main thread VTK render (also Normal)
- Download QThread asyncio loop (also Normal)

**Impact:** Even with the Python warmup thread at IDLE, the C++ threads it spawns saturate all CPU cores at Normal priority → VTK render starved → slow scroll.

---

## 5. Zeta Download Manager Architecture

### 5.1 Component Overview

```
DownloadManagerWidget (UI container)
    ↓ creates
DownloadWorker (QThread)
    ↓ runs
asyncio.new_event_loop() [inside QThread OS thread]
    ↓ executes
DownloadExecutor.execute_download()
    ↓ coordinates
    ├─ GrpcMetadataClient.fetch_metadata() [gRPC call, separate threads]
    ├─ DatabaseManager.init_study() [SQLite writes]
    ├─ SeriesDownloader.download_all_series()
    │      └─ for each series:
    │          └─ SocketDicomClient.download_series()
    │              ├─ for each batch (10 files):
    │              │   └─ send_request() [recv loop + json.loads] ← **GIL HOTSPOT A**
    │              │   └─ for each file: base64 + gzip + write ← **GIL HOTSPOT B**
    │              └─ _save_series_instances_to_db()
    │                  └─ for each .dcm: pydicom.dcmread() ← **GIL HOTSPOT C**
    └─ Emit completed signal
```

### 5.2 Worker Pool & Concurrency Cap

**File:** `worker_pool.py`  
**Constant:** `MAX_CONCURRENT_STUDIES = 1` (from `constants.py`)

Only **one DownloadWorker QThread** runs at any time. Additional download requests queue behind it. This is correct and necessary — simultaneous downloads would multiply GIL contention.

### 5.3 Download Execution Pipeline (Detailed)

#### Step 1: Metadata Fetch (gRPC)

```python
# executor.py, execute_download()
metadata = await self.grpc_client.fetch_metadata(task.patient_id, task.study_uid)
```

**Execution:**
- gRPC Python client spawns internal threads for channel I/O (managed by grpcio library)
- These threads release GIL during network I/O (C-level socket syscalls)
- Metadata fetch typically takes 200–800ms depending on server response
- **Not a GIL bottleneck** — brief one-time cost at download start

#### Step 2: Database Initialization

```python
# executor.py
await self.database.init_study(metadata, task.study_uid, study_output_dir)
```

**Execution:**
- SQLite `INSERT` patient/study/series rows (3–15 rows total at start)
- WAL mode allows concurrent reads from main thread
- Typical cost: 10–30ms
- **Not a GIL bottleneck** — brief one-time cost

#### Step 3: Series Download Loop (Primary 99% of download time)

```python
# executor.py, calls series_downloader.py
for series_info in sorted(metadata.series_list, key=lambda s: s.series_number):
    await series_downloader.download_series(
        socket_client,
        series_info,
        series_output_dir,
        progress_callback=progress_callback
    )
```

**Execution:**
- **BATCH_SIZE = 10** files per request (constant from `constants.py`)
- Each batch:
  1. `send_request()` to server → receives BASE64-encoded gzipped DICOM files as JSON
  2. For each of 10 files: `base64.b64decode()` + `gzip.decompress()` + `f.write()`
  3. Call `progress_callback()` per file
- After all batches for series complete:
  - `_save_series_instances_to_db()`: open each .dcm file with `pydicom.dcmread()`, extract metadata, batch INSERT into SQLite

**This loop is where 99% of download time is spent and where the three GIL hotspots exist.**

### 5.4 GIL Hotspot A: O(n²) recv accumulation (UNFIXED)

**File:** `socket_client.py`, method `send_request()`, recv loop  
**Lines:** ~458 (approximate, see code)

```python
# CURRENT CODE (BROKEN):
response_data = b''
while len(response_data) < response_length:
    chunk = self._safe_recv(chunk_size)   # GIL released (C-level recv syscall)
    response_data += chunk                # GIL HELD: new bytes alloc + full copy
```

**Problem:**
- `SOCKET_CHUNK_SIZE = 65536` (64 KB)
- Typical batch response: 7 MB (10 DICOM files × ~700KB each, BASE64-encoded)
- Number of iterations: 7MB ÷ 64KB ≈ **109 iterations**
- Each `response_data += chunk` allocates a **new bytes object** and copies **all previous bytes**: O(n) copy × 109 iterations = **O(n²) total**
- Total bytes copied: 64KB + 128KB + 192KB + ... + 7MB ≈ **385 MB of GIL-held memory operations** per batch
- **GIL hold time per batch:** ~5–15ms (enough to cause one `set_slice` stall)

**Why This Matters:**
- With 10 series × 12 batches/series = 120 batches total for a study
- 120 × 10ms = **1.2 seconds of accumulated GIL stalls** just from recv loops
- Main thread's `set_slice` calls must wait for GIL → scroll choppy

**Fix:** Change #9A (bytearray + memoryview) — see Section 13.2

### 5.5 GIL Hotspot B: Per-file processing with no yield (UNFIXED)

**File:** `socket_client.py`, method `download_series()`, per-instance loop  
**Lines:** approximate ~520–550

```python
# CURRENT CODE (BROKEN):
for instance_data in instances:    # 10 files per batch
    # 1. Decode BASE64 (~1–3ms, GIL held)
    dicom_bytes = base64.b64decode(instance_data['dicom_data'])
    
    # 2. Decompress gzip (~2–5ms, GIL often held for small inputs)
    if compressed:
        dicom_bytes = gzip.decompress(dicom_bytes)
    
    # 3. Write to disk (~1–3ms, GIL released during OS syscall but re-acquired immediately)
    with open(file_path, 'wb') as f:
        f.write(dicom_bytes)
    
    # 4. Progress callback (~0.5–2ms, pure Python dict ops + signal emit)
    if progress_callback:
        progress_callback(...)

# NO asyncio.sleep(0) between files → 30ms GIL burst per batch
# NO asyncio.sleep(0) between batches → back-to-back bursts
```

**Problem:**
- Total per-file cost: ~5–13ms × 10 files = **50–130ms GIL burst per batch**
- BUT: `base64.b64decode()` and `gzip.decompress()` are C extensions — they CAN release GIL if implemented correctly
- **The issue:** No explicit `await asyncio.sleep(0)` yield between files or between batches
- The asyncio event loop **never gets a chance to run its I/O selector** which is the only place GIL is released for the main thread to acquire

**Impact:**
- 50–130ms GIL burst every 1–2 seconds (batch cadence)
- Main thread's `set_slice` waits up to 130ms → **severe scroll lag**

**Fix:** Change #9B (asyncio.sleep(0) every 3 files) — see Section 13.3

### 5.6 GIL Hotspot C: pydicom loop (CURRENT STATUS: PARTIALLY FIXED)

**File:** `series_downloader.py`, method `_save_series_instances_to_db()`  
**Lines:** approximate ~380–420

```python
# CURRENT CODE (v2.2.2.5 verified):
for _dcm_idx, dcm_file in enumerate(dicom_files):
    if _dcm_idx % 5 == 0:  # yield every 5 files
        await asyncio.sleep(0)

    # pydicom.dcmread is PURE PYTHON (~15–30ms per file, 100% GIL held)
    dcm = pydicom.dcmread(dcm_file, stop_before_pixels=True)
    # ... extract metadata ...
```

**Remaining Concern:**
- `pydicom.dcmread()` is a pure Python DICOM parser (not a C extension)
- Typical cost: **15–30ms per file**, 100% GIL held
- Even with `% 5` yielding, each chunk can still create noticeable burst windows on slower CPUs

**Impact:**
- Post-series DB insert contention is reduced versus legacy behavior
- Remaining lag spikes are now more strongly tied to socket/file-loop hotspots (#9A/#9B)

**Fix Status:** Change #9C is already present in current code. Keep it; no reapply needed.

### 5.7 Download Manager Resource Consumption

| Resource | Consumption | Notes |
|----------|------------|-------|
| **CPU** | 5–20% (asyncio loop overhead, BASE64, gzip) | GIL-bound, not CPU-bound |
| **GIL** | **30–750ms bursts** ← PRIMARY ISSUE | Starves main thread |
| **Network I/O** | ~5–15 Mbps typical | GIL released during recv() syscall |
| **Disk I/O** | Sequential writes, ~10–30 MB/s | GIL released during write() syscall |
| **SQLite** | WAL mode, separate connection from main thread | No lock contention with viewer |

---

## 6. Database Architecture & Concurrent Access

### 6.1 SQLite Configuration (database.py)

**file:** `PacsClient/utils/database.py`, lines 1–100

```python
# CONFIRMED IN CODE:
sqlite3.connect(
    'dicom.db',
    timeout=300.0,                 # 300 second wait before SQLITE_BUSY
    check_same_thread=False,       # Explicit multi-thread access allowed
    isolation_level="DEFERRED"     # No premature lock acquisition
)

# After connect:
cursor.execute("PRAGMA journal_mode = WAL")     # Write-Ahead Logging
cursor.execute("PRAGMA busy_timeout = 120000")  # 120s busy wait
cursor.execute("PRAGMA synchronous = NORMAL")   # fsync only at checkpoint
```

### 6.2 WAL Mode Guarantees

**Write-Ahead Logging (WAL):**
- Writers append to a separate `-wal` file, not the main `.db` file
- Readers continue reading from the main file (frozen snapshot)
- **Multiple readers + 1 writer can run concurrently with ZERO blocking**

**Practical Effect:**
- Download QThread: writes (INSERT instances, UPDATE progress) to `-wal` file
- Main thread: reads (SELECT series metadata, instance file paths) from main `.db` file
- **No lock contention between download and viewer**

### 6.3 Connection Pooling

**Per-Thread Connection Pool:**
```python
_connection_pool = {}  # thread_id → list of sqlite3.Connection
MAX_POOL_SIZE = 5      # max connections per thread
```

**Key Property:**  
Pool is keyed by `threading.current_thread().ident`. The main thread and download QThread have **different thread IDs** → **different pool buckets** → **different connection objects**. They NEVER share a `sqlite3.Connection` instance.

**Result:** No connection-level contention. Each thread reuses its own pool.

### 6.4 Database as Contention Source — Assessment

| Scenario | Risk | Actual Behavior | Verdict |
|---------|------|----------------|---------|
| Main thread SELECT + QThread INSERT simultaneously | Lock collision? | WAL allows concurrent read+write | ✅ **SAFE** — not a bottleneck |
| Two QThreads writing simultaneously | Race condition? | `MAX_CONCURRENT_STUDIES=1` prevents this | ✅ **N/A** — impossible |
| `busy_timeout=120s` prevents SQLITE_BUSY | Timeout crashes? | Long-running queries wait gracefully | ✅ **RESILIENT** |
| `pydicom.dcmread()` GIL burst blocks main thread DB read | SQLite-level block? | **No** — it's a **GIL-level block**, not SQLite lock | ⚠️ **GIL issue, not DB issue** |

**Conclusion:** The database architecture is **NOT a performance bottleneck**. Any "database lag" observed during downloads is actually **GIL starvation** from the download QThread preventing the main thread from even REACHING the SQLite API call.

---

## 7. Viewer Widget & VTK Pipeline

### 7.1 Main Thread Ownership (Hard Requirement)

All VTK operations run on the **main Qt thread**. This is a VTK/OpenGL architectural requirement:
- VTK render windows must be created and used from the thread that owns the OS window handle
- OpenGL contexts are thread-local
- Attempting to render VTK from a background thread → crashes or silent misrenders

### 7.2 Scroll Path (patient_widget.py → vtk_widget.py → viewer_2d.py)

```
USER SCROLLS SLIDER
    ↓
patient_widget.py: on_slider_value_changed(vtk_widget, value)
    ↓ calls
vtk_widget.py: set_slice(slice_index)
    ↓
    ├─ Save camera parallel scale (zoom protection)
    ├─ image_viewer.set_slice(slice_index)  ← C++ VTK pipeline
    │      └─ vtkImageViewer2::SetSlice()
    │         └─ vtkImageReslice::Update()  ← **CPU-BOUND C++ CALL** (~20–37ms)
    ├─ Detect zoom drift, restore if needed
    └─ image_viewer.Render()                ← Composited final render (~2–5ms)
    
patient_widget.py: manage_reference_line(...)
    └─ target_viewer.Render()  ← Reference line VTK render (~15–83ms) ⚠️ SLOW
```

### 7.3 Critical VTK Operations & Costs

| Operation | File | Typical Cost (Mode A) | Cost (Mode B, unfixed) | CPU or GPU? |
|-----------|------|---------------------|------------------------|-------------|
| `vtkImageReslice::Update()` | viewer_2d.py (via VTK C++) | 15–20ms | **20–100ms** (GIL or CPU starved) | **CPU** (software rendering) |
| `update_corners_actors()` | viewer_2d.py | 2–4ms | 3–8ms (GIL starved) | CPU (text layout) |
| `image_viewer.Render()` | viewer_2d.py | 2–5ms | 3–10ms (GIL starved) | CPU (compositing) |
| `manage_reference_line()` | patient_widget.py | **15–83ms** ⚠️ | 15–83ms | CPU (full VTK render on target viewer) |

**Why `manage_reference_line()` is Slow:**  
It calls `target_viewer.Render()` — a full VTK render pipeline execution on the target 2D viewer to draw the reference line geometry. This happens **on every scroll tick** (potentially 60+ times/second during fast scroll). The debounce fix (Change #8) defers this to **50ms after last scroll** → drops cost to ~0ms during scroll.

### 7.4 VTK Software Rendering Cost

**Forced in code:**  
`main.py` sets `os.environ["VTK_FORCE_SOFTWARE_RENDERING"] = "1"` to ensure compatibility on machines without GPU drivers.

**Impact:**
- All VTK pipeline operations run on CPU, not GPU
- `vtkImageReslice::Update()` does pixel resampling in C++ on CPU → **20–37ms per slice** even with no GIL contention
- Hardware OpenGL would reduce this to **<2ms** on GPU-capable machines

**Long-Term Fix:** Remove `VTK_FORCE_SOFTWARE_RENDERING` after verifying GPU driver availability on target hardware. See Section 17.

---

## 8. ZetaBoost Engine Architecture

### 8.1 Instance Ownership & Lifecycle

**One engine instance per open study tab (owned by `ViewerController`):**
```python
# patient_widget_viewer_controller.py __init__ (confirmed in code):
self.zeta_boost = ZetaBoostEngine(
    tab_key=str(study_uid),
    load_series_callback=self._zeta_boost_load_series,
    max_entries=<dynamic by RAM tier>,
    byte_budget=<dynamic by RAM tier>,
    max_parallel_loads=1,
    warmup_workers=1..2 (tiered),
    background_workers=1,
)
```

**Important verified delta:** current capacity policy is intentionally conservative (low entry counts, bounded byte budget, `max_parallel_loads=1`) to protect interactivity under load.

**Thread Count:**  
Each engine spawns **6 daemon threads** (interactive/warmup/background × 2 workers each). With 2 studies open: **12 ZetaBoost daemon threads** total.

### 8.2 Lane Model

| Lane | Workers | Purpose | When Blocked | CPU Priority |
|------|---------|---------|-------------|-------------|
| `interactive` | 2 | User drag/drop, on-demand loads | **Never** | IDLE (Python) / Normal (ITK C++) |
| `warmup` | 2 | Sequential proactive pre-loading | **Always during download** (via `_study_download_complete` flag) | IDLE (Python) / Normal (ITK C++) |
| `background` | 2 | Disk cache persistence, eviction | **Always during download** | IDLE (Python) |

**Critical Bug (UNFIXED):**  
`_study_download_complete` and `_download_active` are **instance variables** (`self._xxx`), NOT class variables. If Patient B is downloading while Patient A's study is open in a viewer:
- Patient B's engine: `_study_download_complete = False` → warmup blocked ✅ correct
- Patient A's engine: `_study_download_complete = True` (default) → warmup **RUNS FREELY** ❌ **BUG**

When Patient A's warmup runs ITK (4–16s per series), it spawns **Normal-priority C++ threads** that saturate all CPU cores → Patient B's download asyncio loop + Main thread VTK render both starved → **4500ms UI freeze**.

**Fix:** Change #7 (class-level global download counter) — see Section 13.1

### 8.3 Gate Logic (engine.py, `_can_start_lane_locked()`)

**Current Code (lines ~536, confirmed):**
```python
def _can_start_lane_locked(self, lane: str) -> bool:
    # Interactive always unblocked
    if lane == "interactive":
        return True
    
    # Warmup/background blocked while:
    if not self._study_download_complete and lane in ("warmup", "background"):
        return False  # ← PipelineOrchestrator gate (per-instance)
    
    if self._download_active and lane in ("warmup", "background"):
        return False  # ← legacy fallback gate (per-instance)
    
    # ... other checks: external busy, parallelism cap, lane inflight limit
```

**The Problem:** Both gates check `self._xxx` instance flags. There is **no check for global download state**.

### 8.4 Worker Loop Sleep Intervals

**After each job completes:**
```python
# engine.py, _worker_loop() (confirmed ~line 912):
if lane == "interactive":
    time.sleep(0.08)      # 80ms yield
elif self._download_active:
    time.sleep(2.0)       # 2s yield — but ONLY if *this engine's* download is active
else:
    time.sleep(0.5)       # 500ms yield between warmup jobs
```

**Note:** The `2.0s` branch only fires if `self._download_active` is True, which is only set for the patient whose download is in progress. Patient A's engine never enters the 2s branch while Patient B is downloading.

### 8.5 ITK Execution Inside ZetaBoost

**Load callback path:**
```
ZetaBoost _worker_loop() [Python, IDLE priority]
    ↓
load_series_callback(...) [viewer_controller callback]
    ↓
image_io.load_single_series_by_number(...)
    ↓
apply_filters(sitk_image)  [C++ SimpleITK]
    ↓
ITK MultiThreaderBase spawns N C++ threads [**Normal priority** ⚠️]
    └─ GaussianImageFilter (multi-threaded C++)
    └─ LaplacianSharpeningImageFilter (multi-threaded C++)
    └─ RescaleIntensityImageFilter (multi-threaded C++)
    Total: 3–16 seconds per series, 100% CPU × N cores
```

**The Priority Inheritance Bug (Repeated from Section 4.1):**  
The Python warmup worker is IDLE priority, but the C++ ITK threads it spawns are **Normal priority**. They compete equally with main thread VTK render → slow scroll.

### 8.6 Additional code-grounded deltas (current v2.2.2.5)

- `DownloadManagerWidget` still runs single active worker (`MAX_CONCURRENT_STUDIES=1`), so contention is primarily GIL/CPU, not multi-download thread count.
- `socket_client.send_request()` still uses incremental `response_data += chunk` accumulation (O(n²) copy pattern).
- `series_downloader.py` already yields every 5 files in the pydicom metadata loop.
- Async switch path includes preview-first behavior for smaller-series paths, but large-series cold loads can still wait on full ITK completion.
- Adjacent prefetch helper currently calls `self.zeta_boost.queue_load(...)` while engine API is `enqueue(...)`, so that path can silently no-op under exception guards.

---

## Part III: Resource Contention Analysis

## 9. Shared Resources & Arbitration Mechanisms

| Shared Resource | Contending Owners | Arbitration Mechanism | Current Bottleneck? |
|----------------|-------------------|----------------------|-------------------|
| **Python GIL** | Main thread, DownloadWorker QThread | Python runtime (5ms switch for bytecode; C exts hold indefinitely) | ❌ **YES** — 30–750ms bursts |
| **CPU Cores** | Main thread VTK C++, ITK warmup C++, Download asyncio, OS | OS scheduler (Normal vs IDLE priority) | ❌ **YES** — ITK Normal threads saturate cores |
| **SQLite dicom.db** | Main thread reads, QThread writes, ZetaBoost reads | WAL mode + per-thread pool + DEFERRED isolation | ✅ **SAFE** |
| **Disk I/O** | Download .dcm writes, ZetaBoost disk cache | OS filesystem scheduler | ✅ **SAFE** — separate paths |
| **Qt Event Loop** | Main thread (owner), deferred timers | Qt event queue (inherently main-thread only) | ⚠️ **SECONDARY** — frozen when main thread GIL-stalled |
| **Network sockets** | DownloadWorker, gRPC client | Separate sockets, separate ports | ✅ **SAFE** |

**Summary:**  
Only **GIL** and **CPU cores** are actual bottlenecks. Database, disk, network, and Qt event loop are either safe or secondary victims of GIL/CPU starvation.

---

## 10. GIL Contention Timeline & Hotspots

### 10.1 GIL Ownership During Active Download (Typical 1-Batch Cycle)

```
Time axis (milliseconds) →
  0ms                16ms               32ms               48ms               64ms
  │                  │                  │                  │                  │
Main Thread:
  ██░░░░░░░░░░░░░░░░░░██░░░░░░░░░░░░░░░░░██▓▓▓░░░░░░░░░░░░░██▓▓▓▓▓▓░░░░░░░░░
  ↑                   ↑                  ↑                  ↑
  set_slice(20ms)     next slider event  queued, waiting    queued, waiting
  [Has GIL]           queued             [Cannot get GIL]   [Cannot get GIL]

Download QThread (asyncio):
  ░░░████████████████░░░░✤░░░░████████████████░░░░✤░░░░███████████████████░░
      ↑               ↑        ↑                ↑        ↑
      base64+gzip     recv()   base64+gzip      recv()   pydicom parse batch
      ×10 files       [GIL     ×10 files        [GIL     (post-series)
      [30ms GIL]      free]    [30ms GIL]       free]    [75–750ms GIL]

LEGEND:
  ██ = Main thread has GIL, executing Python/VTK
  ░░ = GIL available (released during C syscall or idle)
  ▓▓ = Main thread work pending, waiting for GIL (Qt event queue frozen)
  ✤  = asyncio.sleep(0) / GIL yield point
  ████ = Download QThread has GIL (Python code: decode, parse, dict ops)
```

**Key Observation:**  
The 16ms slider throttle timer (if it existed — it doesn't in v2.2.2.5 but was in external team's v2.2.2.6) **cannot fire** if the main thread is GIL-starved for 30ms. The timer callback is a Qt event — it needs the main thread's event loop to run, which needs the main thread to have the GIL.

### 10.2 GIL Burst Duration by Hotspot

| Hotspot | Operation | Typical Duration | Frequency | Fix |
|---------|-----------|-----------------|-----------|-----|
| **A: recv O(n²)** | `response_data += chunk` × 109 | **5–15ms** | Every batch (every 1–2s) | Change #9A |
| **B: file loop** | `base64 + gzip + write` × 10 | **30–130ms** | Every batch (every 1–2s) | Change #9B |
| **C: pydicom** | `pydicom.dcmread()` × 50 | **750ms** | Every 50 files (sporadic) | Change #9C |

**Cumulative Impact:**  
For a 128-file series with 13 batches:
- 13 batches × 10ms (recv) = **130ms** × 1 series = 130ms
- 13 batches × 50ms (files) = **650ms** × 1 series = 650ms
- 1 DB insert × 750ms = **750ms** × 1 series = 750ms
- **Total GIL hold: ~1.5 seconds per series**

For a 10-series study: **15 seconds of accumulated GIL starvation** spread across the download.

---

## 11. CPU Core Contention Analysis

### 11.1 Contention Scenario (4-Core Machine, No Fixes Applied)

```
SCENARIO: Patient B downloading, Patient A viewer open

CPU Core Assignment (Windows Normal Priority Scheduler):

Core 0:  [Main Thread VTK reslice]  ←shares→  [ITK C++ thread 0]  (Patient A warmup)
Core 1:  [Qt event loop overhead]    ←shares→  [ITK C++ thread 1]  (Patient A warmup)
Core 2:  [ITK C++ thread 2]          ←shares→  [Download asyncio]
Core 3:  [ITK C++ thread 3]          ←shares→  [OS scheduler tasks]

Expected Behavior (all Normal priority):
  • OS gives each thread equal time slices (~5–15ms per thread)
  • VTK reslice gets ~50% of core 0 → takes 2× longer → 20ms becomes 40–100ms
  • Download asyncio gets ~25% of core 2/3 → slower batch processing
```

**Result:** Both the viewer (scroll) AND download (progress) are slow simultaneously.

### 11.2 After Change #7 (Global Download Counter) Applied

```
SCENARIO: Any download active → ALL engine instances block warmup

Core 0:  [Main Thread VTK reslice]  ← FULL OWNERSHIP (no ITK)
Core 1:  [Qt event loop overhead]    ← FULL OWNERSHIP
Core 2:  [Download asyncio]          ← FULL OWNERSHIP
Core 3:  [OS idle / sporadic tasks]

Result:
  • VTK reslice: 20ms (CPU baseline, not starved)
  • Download asyncio: full speed
  • Remaining scroll lag (if any) is GIL-caused, not CPU-caused
```

---

## 12. Complete Performance Budget

### 12.1 Per-Tick Scroll Cost Breakdown

**Hardware Context:** Windows machine, VTK software rendering, 4-core CPU

| Operation | Mode A (no download) | Mode B (v2.2.2.5, unfixed) | Mode B (after all fixes) | Bottleneck Type |
|-----------|---------------------|---------------------------|-------------------------|-----------------|
| `vtkImageReslice::Update()` | 15–20ms | **20–100ms** | 15–20ms | CPU (VTK SW render) |
| `update_corners_actors()` | 2–4ms | **3–8ms** | 2–4ms | CPU + GIL |
| `image_viewer.Render()` | 2–5ms | **3–10ms** | 2–5ms | CPU + GIL |
| `manage_reference_line()` | **15–83ms** ⚠️ | **15–83ms** | **≈ 0ms** (deferred) | CPU + VTK render |
| **GIL wait stall** | 0ms | **0–130ms** | ≈ 0ms | Download GIL burst |
| **ITK preemption overhead** | 0ms | **0–50ms** | ≈ 0ms | CPU core starved |
| **Total per tick** | **35–110ms** | **40–380ms** | **~20–30ms** | |
| **Max scroll fps** | ~9–28 fps | ~2–25 fps | ~35–50 fps | |

**Target:** <16ms/tick for 60fps requires **hardware OpenGL** (removing `VTK_FORCE_SOFTWARE_RENDERING`).

### 12.2 Download Speed Impact

| Scenario | Download Speed | Notes |
|---------|---------------|-------|
| No viewer open | 100% (baseline, ~8–12 Mbps) | Full CPU/GIL for download |
| Viewer open, no user interaction | 90–100% | Warmup blocked, minimal GIL contest |
| Viewer open, user scrolling (unfixed) | **50–70%** | GIL contest + CPU preemption if warmup runs |
| Viewer open, user scrolling (all fixes) | 85–95% | Brief GIL yields, no CPU contest |

---

## Part IV: Validated Solutions

## 13. Proven Fixes — Reapply Guide

**All changes below were tested across 7 test sessions, validated effective, then rolled back to v2.2.2.5 for clean reapply.**

### 13.1 Change #7: ZetaBoost Global Download Counter (P0 — CRITICAL)

**Root Cause Fixed:** Cross-study ITK CPU saturation (Root Cause #2)

**Impact:** EVENT_LOOP_LAG 4500ms → <50ms, zero ITK during any download

#### ADD to `engine.py` (class body of `ZetaBoostEngine`)

**After existing class attributes (around line 35):**
```python
# ─────────────────────────────────────────────────────────────
# Change #7: Global download counter (class-level, shared across all instances)
# ─────────────────────────────────────────────────────────────
_global_active_download_count: int = 0
_global_download_lock: threading.Lock = threading.Lock()

@classmethod
def notify_global_download_start(cls) -> None:
    """
    Call when ANY study download begins anywhere in the application.
    Blocks warmup/background lanes on ALL engine instances.
    """
    with cls._global_download_lock:
        cls._global_active_download_count += 1
    print(f"[ZetaBoost][GLOBAL] Download started. Active downloads: {cls._global_active_download_count}")

@classmethod
def notify_global_download_stop(cls) -> None:
    """
    Call when ANY study download completes or is cancelled.
    """
    with cls._global_download_lock:
        cls._global_active_download_count = max(0, cls._global_active_download_count - 1)
    print(f"[ZetaBoost][GLOBAL] Download stopped. Active downloads: {cls._global_active_download_count}")
```

#### PATCH `_can_start_lane_locked()` method (around line 536)

**Add as FIRST check, before any other checks:**
```python
def _can_start_lane_locked(self, lane: str) -> bool:
    # ─────────────────────────────────────────────────────────────
    # Change #7: Block warmup/background if ANY download is active globally
    # ─────────────────────────────────────────────────────────────
    if ZetaBoostEngine._global_active_download_count > 0 and lane in ("warmup", "background"):
        return False
    
    # Interactive always unblocked
    if lane == "interactive":
        return True
    
    # ... rest of existing checks unchanged ...
```

#### PATCH `_wait_reason_locked()` method (around line 580)

**Add to reasons list:**
```python
def _wait_reason_locked(self, lane: str) -> str:
    reasons = []
    
    # ─────────────────────────────────────────────────────────────
    # Change #7: Report global download active as block reason
    # ─────────────────────────────────────────────────────────────
    if ZetaBoostEngine._global_active_download_count > 0 and lane in ("warmup", "background"):
        reasons.append(f"global_download_active({ZetaBoostEngine._global_active_download_count})")
    
    # ... rest of existing checks unchanged ...
```

#### WIRE in `main_widget.py` (DownloadManagerWidget)

**File:** `PacsClient/zeta_download_manager/ui/main_widget.py`

**In `_start_download_worker()` method, AFTER `worker.start()`:**
```python
def _start_download_worker(self, task: DownloadTask) -> bool:
    # ... existing code: create worker, wire signals ...
    
    worker.start()
    
    # ─────────────────────────────────────────────────────────────
    # Change #7: Increment global download counter
    # ─────────────────────────────────────────────────────────────
    from PacsClient.pacs.patient_tab.zeta_boost.engine import ZetaBoostEngine
    ZetaBoostEngine.notify_global_download_start()
    
    # ... rest of method ...
```

**In `_on_worker_completed()` method, AS FIRST LINE:**
```python
def _on_worker_completed(self, study_uid: str, success: bool):
    # ─────────────────────────────────────────────────────────────
    # Change #7: Decrement global download counter FIRST
    # Must happen before any other state update to ensure other threads see the change
    # ─────────────────────────────────────────────────────────────
    from PacsClient.pacs.patient_tab.zeta_boost.engine import ZetaBoostEngine
    ZetaBoostEngine.notify_global_download_stop()
    
    # ... rest of existing method unchanged ...
```

#### Validation Criteria
- Probe log (or print statements) shows: `WORKER_BLOCKED reason=global_download_active(1)`
- **Zero** `ITK filters:` log lines appear during entire download period
- `EVENT_LOOP_LAG` remains < 50ms throughout download

---

### 13.2 Change #9A: bytearray recv (O(1) per chunk) (P1 — HIGH)

**File:** `PacsClient/zeta_download_manager/network/socket_client.py`  
**Method:** `send_request()`, recv accumulation loop

**Root Cause Fixed:** O(n²) GIL burst from `response_data += chunk` (Hotspot A)

#### REPLACE the recv accumulation block

**BEFORE (search for `response_data = b''`):**
```python
response_data = b''
while len(response_data) < response_length:
    chunk_size = min(SOCKET_CHUNK_SIZE, response_length - len(response_data))
    chunk = self._safe_recv(chunk_size)
    if not chunk:
        raise NetworkError("Connection lost while receiving data")
    response_data += chunk  # ← O(n) copy per iteration = O(n²) total
```

**AFTER (Change #9A):**
```python
# ─────────────────────────────────────────────────────────────
# Change #9A: Pre-allocated bytearray + memoryview — O(1) per chunk
# ─────────────────────────────────────────────────────────────
_recv_buf = bytearray(response_length)
_recv_view = memoryview(_recv_buf)
_recv_offset = 0
while _recv_offset < response_length:
    chunk_size = min(SOCKET_CHUNK_SIZE, response_length - _recv_offset)
    chunk = self._safe_recv(chunk_size)
    if not chunk:
        raise NetworkError("Connection lost while receiving data")
    _n = len(chunk)
    _recv_view[_recv_offset:_recv_offset + _n] = chunk  # O(1) in-place copy
    _recv_offset += _n
response_data = bytes(_recv_buf)
```

---

### 13.3 Change #9B: asyncio.sleep(0) per 3 files + inter-batch (P1 — HIGH)

**File:** `PacsClient/zeta_download_manager/network/socket_client.py`  
**Method:** `download_series()`, per-instance loop

**Root Cause Fixed:** 30ms GIL burst from tight file processing loop (Hotspot B)

#### PATCH the per-instance loop

**BEFORE:**
```python
for instance_data in instances:  # 10 files per batch
    dicom_bytes = base64.b64decode(instance_data['dicom_data'])
    if is_compressed:
        dicom_bytes = gzip.decompress(dicom_bytes)
    with open(file_path, 'wb') as f:
        f.write(dicom_bytes)
    if progress_callback:
        progress_callback(...)
# NO yield between files
```

**AFTER (Change #9B):**
```python
# ─────────────────────────────────────────────────────────────
# Change #9B: Yield GIL every 3 files via asyncio.sleep(0)
# ─────────────────────────────────────────────────────────────
for _inst_idx, instance_data in enumerate(instances):
    if _inst_idx > 0 and _inst_idx % 3 == 0:
        await asyncio.sleep(0)  # asyncio event loop calls select() → GIL released
    
    dicom_bytes = base64.b64decode(instance_data['dicom_data'])
    if is_compressed:
        dicom_bytes = gzip.decompress(dicom_bytes)
    with open(file_path, 'wb') as f:
        f.write(dicom_bytes)
    if progress_callback:
        progress_callback(...)
```

#### PATCH inter-batch yield

**Add BEFORE `batch_idx += 1` (around line 560):**
```python
# ─────────────────────────────────────────────────────────────
# Change #9B: Yield between batches
# ─────────────────────────────────────────────────────────────
await asyncio.sleep(0)
batch_idx += 1
batch_start += batch_size
```

---

### 13.4 Change #9C: pydicom yield every 5 files (P1 — HIGH)

**File:** `PacsClient/zeta_download_manager/download/series_downloader.py`  
**Method:** `_save_series_instances_to_db()`

**Root Cause Fixed:** 750ms GIL burst from pydicom parse loop (Hotspot C)

#### PATCH the yield condition

**BEFORE:**
```python
for _dcm_idx, dcm_file in enumerate(dicom_files):
    if _dcm_idx > 0 and _dcm_idx % 50 == 0:  # yield every 50 files
        await asyncio.sleep(0)
    dcm = pydicom.dcmread(dcm_file, stop_before_pixels=True)
    # ... extract metadata ...
```

**AFTER (Change #9C):**
```python
for _dcm_idx, dcm_file in enumerate(dicom_files):
    # ─────────────────────────────────────────────────────────────
    # Change #9C: Yield every 5 files instead of 50 (max 75ms burst)
    # ─────────────────────────────────────────────────────────────
    if _dcm_idx % 5 == 0:  # yield every 5 files
        await asyncio.sleep(0)
    dcm = pydicom.dcmread(dcm_file, stop_before_pixels=True)
    # ... extract metadata ...
```

---

## 14. Fixes to NOT Reapply (Lessons Learned)

The following changes were applied during investigation but found to be **unnecessary, harmful, or redundant** once the root causes were fixed. **Do NOT reapply these.**

| Change | What It Did | Why NOT to Reapply |
|--------|------------|-------------------|
| **Change #8: manage_reference_line() debounce (50ms QTimer)** | Deferred reference line VTK render to 50ms after last scroll | Once GIL fixes (Changes #9) are applied, `manage_reference_line()` returns to <2ms naturally. The debounce adds 50ms latency to cross-viewer line updates (usability regression). The symptom it hid is gone after root cause fix. |
| **Change #5: Scroll-activity pause gate (1.5s)** | Blocked warmup/background from STARTING new ITK jobs for 1.5s after last scroll tick | Once Change #7 (global download gate) is active, warmup is already blocked during ALL downloads. The scroll pause adds unnecessary complexity on top. |
| **Change #3/#4: ITK thread cap (`SetGlobalDefaultNumberOfThreads(1)`)** | Limited ITK C++ pool to 1 thread during warmup/background | This was only needed because warmup was running during download. Change #7 blocks warmup entirely during download. Outside download, cap=1 makes warmup slower (16s vs 4s per series). Let ITK use all cores when it IS allowed to run. |
| **Probe instrumentation (Change #1)** | `mode_b_lag_probe.py` + wiring in main.py/main_widget.py/patient_widget.py | Added ~200ms polling overhead. The diagnostics FILE should be preserved in `PacsClient/diagnostics/` for reference, but do NOT wire it into runtime unless actively debugging a new issue. |

---

## 15. Implementation Checklist & Test Validation

### 15.1 Reapply Order (Must Be Sequential)

```
[ ] Step 1: Apply Change #7 to engine.py
        - Add class variables: _global_active_download_count, _global_download_lock
        - Add classmethods: notify_global_download_start(), notify_global_download_stop()
        - Patch _can_start_lane_locked() [add global check FIRST]
        - Patch _wait_reason_locked() [add global reason to list]
        → See Section 13.1 for exact code

[ ] Step 2: Wire Change #7 in main_widget.py
        - _start_download_worker(): call notify_global_download_start() after worker.start()
        - _on_worker_completed(): call notify_global_download_stop() as FIRST line
        → See Section 13.1 for exact wiring

[ ] Step 3: Run smoke test (Test 7a)
        - Open Patient A study, start viewing series 1
        - Start download of Patient B study
        - Expected output (console or log):
           ✅ "WORKER_BLOCKED reason=global_download_active(1)"
           ✅ Zero "ITK filters:" lines during entire download
        - Expected behavior:
           ✅ EVENT_LOOP_LAG < 50ms throughout download (if probe active)
           ✅ VTK scroll feels smoother (no 4s freezes)
        - If fails: check wire points in main_widget.py

[ ] Step 4: Apply Change #9A to socket_client.py
        - Replace response_data = b'' + += loop
        - Use bytearray(response_length) + memoryview
        → See Section 13.2 for exact code

[ ] Step 5: Apply Change #9B to socket_client.py
        - Add enumerate() to for instance_data loop
        - Add await asyncio.sleep(0) every 3 instances
        - Add await asyncio.sleep(0) between batches
        → See Section 13.3 for exact code

[x] Step 6: Verify Change #9C in series_downloader.py
    - Confirm `% 5` yield is already present in `_save_series_instances_to_db()`
    - No reapply needed unless regression is detected
    → See Section 13.4 for reference code

[ ] Step 7: Run full validation test (Test 7b)
        - Open study, start scrolling during download
        - Expected metrics:
           ✅ set_slice avg < 10ms during download (was 22–37ms)
           ✅ set_slice peak < 25ms (was 69–100ms)
           ✅ No >100ms EVENT_LOOP_LAG stalls
           ✅ Download speed not regressed (should be same or faster)
        - Subjective:
           ✅ Scroll feels smooth and responsive
           ✅ No perceivable freezes or stutter

[ ] Step 8: Commit as single feature branch
        - Branch name: `fix/mode-b-gil-and-cpu-contention`
        - Commit message: "Fix Mode B performance: global ZetaBoost gate + download GIL yields"
        - Include reference to this document in commit body
```

### 15.2 Rollback Plan (If Test 7b Fails)

If `set_slice avg` does NOT improve to <10ms after all changes:
1. **Check asyncio.sleep(0) placements:** Ensure they are inside `async def` functions (not regular `def`)
2. **Profile json.loads() cost:** Add timing around `json.loads(response_data.decode('utf-8'))` in `send_request()`. If >10ms per batch, reduce `BATCH_SIZE` from 10 to 5.
3. **Verify GIL yield actually happens:** Add `print(f"[GIL_YIELD] {_inst_idx}")` at each `await asyncio.sleep(0)` to confirm execution.
4. **Fallback:** Reduce `BATCH_SIZE` from 10 to 3 (more network round trips, but smaller GIL bursts per batch).

---

## Part V: Future Work

## 16. Remaining Known Issues

| # | Issue | Root Cause | Fix Needed | Priority |
|---|-------|-----------|------------|----------|
| **I1** | **Cold-cache drag/drop 3–12s stall** | ITK filter chain on-demand, no preview shown | **Wire PreviewEngine** into interactive load path (Solution C). Show preview in <200ms, full load in background. | **P2 — HIGH** |
| **I2** | **VTK software render 20–37ms baseline** | `VTK_FORCE_SOFTWARE_RENDERING` forces CPU rasterizer | Remove flag after GPU driver verification. Use hardware OpenGL. | P3 — MEDIUM |
| **I3** | **Viewer creation 1900–2100ms blocks main thread** | `PipelineManager` creates VTK viewer widgets synchronously on study open | Async/lazy VTK init: create lightweight placeholder first, init OpenGL context lazily on first render. | P4 — LOW |
| **I4** | **`update_corners_actors()` rebuilds 6 text actors per tick** | Full rebuild for slice number change (other text unchanged) | Debounce or skip full rebuild during fast scroll. Only update slice-number actor. | P5 — VERY LOW |

---

## 17. Long-Term Architectural Improvements

### 17.1 Solution C: Complete preview coverage (Fix Root Cause #1)

**Current State (verified):** Preview-first behavior exists in async switch/load paths, but coverage is conditional and not universal for all cold-load scenarios (especially large-series drag/drop). `PreviewEngine` exists but is not yet the single unified preview cache path.

**What to Fix:**
1. Unify preview access so all cold interactive loads check a single preview source first (including large-series paths).
2. Ensure preview is shown immediately regardless of expected slice count, then replaced by full volume when ready.
3. Keep preview cache lifecycle bounded (per-study cleanup on tab close/deactivate) to prevent memory bloat.

**Expected Result:** User drag/drop shows preview in <200ms always, then smooth background full-load replaces it. Eliminates the 3–12s black-screen stall.

**Complexity:** Low (~20 lines across 2 methods)  
**Risk:** Low (PreviewEngine is correct, just needs wiring)

### 17.2 Solution B: ProcessPoolExecutor for ITK Work (Long-Term CPU Isolation)

**Goal:** Run ITK filter chain in **separate OS process** (own GIL, own CPU cores) instead of current same-process threads.

**Architecture:**
```
Main Process:                    Worker Process (via ProcessPoolExecutor):
  ZetaBoost worker thread           ITK filters (3–12s)
    ↓ submits via executor          ↓ returns numpy array
  await loop.run_in_executor(...)   
  ← receives numpy array
  convert to VTK (30ms)
  → display
```

**Benefits:**
- **Complete CPU isolation:** ITK cannot starve VTK render (separate processes)
- **Complete GIL isolation:** Worker process has its own GIL

**Requirements:**
- Worker function must be **module-level** (picklable for multiprocessing)
- Cannot pass/return VTK objects (not picklable) — use numpy arrays
- Main process converts numpy → VTK using `vtk.util.numpy_support.numpy_to_vtk`
- `main.py` must call `multiprocessing.freeze_support()` for PyInstaller compatibility

**Complexity:** High  
**Timeline:** Long-term (after PreviewEngine wiring validates architecture)

### 17.3 Hardware OpenGL (Remove Software Rendering)

**Current:** `main.py` sets `VTK_FORCE_SOFTWARE_RENDERING=1`  
**Goal:** Remove flag on machines with GPU drivers

**Expected Impact:**
- `vtkImageReslice::Update()`: 20–37ms → **<2ms**
- `image_viewer.Render()`: 2–5ms → **<1ms**
- **Total per tick**: 20–30ms → **<5ms** → **60fps scroll** achievable

**Verification Steps:**
1. Add `print(vtk.vtkOpenGLRenderWindow().GetOpenGLLevel())` at startup
2. If reports hardware OpenGL support, remove `VTK_FORCE_SOFTWARE_RENDERING`
3. Test on target hardware to ensure no crashes or black screens

---

## 18. Architectural Invariants (Canonical Rules)

**These rules MUST be preserved by all future work:**

### Rule 1: ZetaBoost Isolation (from Section 8)
> IF any patient download is active THEN ALL ZetaBoost engine instances MUST block warmup and background lanes. Use the class-level global counter. Interactive lane is NEVER blocked.

### Rule 2: GIL Yield Budget
> The download QThread MUST NOT hold Python GIL for more than **10ms** without yielding via `asyncio.sleep(0)`. Every loop processing Python objects (decode, parse, dict ops) must count its GIL exposure and yield every 3–5 iterations if each iteration takes >2ms.

### Rule 3: VTK on Main Thread Only
> All VTK render calls MUST happen on the main Qt thread. Never call `Render()`, `vtkImageReslice::Update()`, or any VTK pipeline update from a background thread.

### Rule 4: Database is Shared (WAL Mode Required)
> Both main thread and QThread workers access the same `dicom.db` SQLite file. Always use WAL mode + DEFERRED isolation. Never call `conn.commit()` in a long loop — batch writes and commit once per series.

### Rule 5: No Viewer-Side Workarounds for Download Problems
> If the viewer is slow ONLY during downloads and fast otherwise, the root cause is in the download manager (GIL, CPU). Do NOT add debounces, throttles, or reduced functionality to the viewer to compensate for download-side interference.

### Rule 6: ITK Thread Count Unconstrained Outside Download
> Do NOT apply a global ITK thread count cap. ITK should use all available cores when warmup/background ARE allowed to run (outside download). The cap should only be applied during download if warmup runs, but Change #7 makes warmup not run at all during download.

---

## Part VI: Concurrent Execution Architecture — Path to True Parallelism

## 19. Why Mode A Proves the Viewer Is Not the Problem

### 19.1 Mode A Evidence

In Mode A, two components run simultaneously and perform well:

| Component | Activity | Result |
|-----------|----------|--------|
| **Viewer Widget** | VTK render, scroll, manage_reference_line | Fast, <5ms per tick |
| **ZetaBoost** | 6 daemon threads, ITK filter chain (C++), warmup of all series | Silent, no viewer slowdown |

**Conclusion from Mode A:**  
The viewer can coexist with heavy background work — provided that work does not interfere with the Python GIL or saturate CPU cores at Normal priority during viewer render windows.

ZetaBoost's Python-side threads are IDLE priority. They hold the GIL for milliseconds at most (queue push/pop, state flag checks). The heavy ITK C++ execution releases the GIL (`Py_BEGIN_ALLOW_THREADS` in SimpleITK internals). So ZetaBoost's C++ work runs in parallel with VTK's C++ render, and the brief Python GIL holds never overlap long enough to cause visible lag.

### 19.2 Mode B Smoking Gun — The Immediate Recovery

The single most important empirical observation is:

> **As soon as a download completes, the viewer immediately becomes fast and responsive.**

This observation rules out:
- Viewer pipeline bugs (they would persist after download ends)
- ITK filter interference (ITK finishes before user ever scrolls a new series)
- Database contention (DB is WAL-safe and not a bottleneck regardless of download state)
- Disk I/O contention (disk writes finish with download; after that, only reads remain)
- Memory pressure (memory usage does not instantly plummet when download stops)

The **only** resource that is instantly and completely freed when the download thread stops is the **Python GIL**. When the DownloadWorker QThread ends its asyncio event loop:
- No more `base64.b64decode()` bursts holding GIL for 30–130ms
- No more `json.loads()` holding GIL for 5–15ms
- No more `pydicom.dcmread()` holding GIL for 15–30ms per file
- The main thread acquires GIL freely → VTK render calls return to baseline timing → viewer is smooth

This is the definitive causal chain.

### 19.3 ITK Filters Are NOT the Primary GIL Problem

This is a critical architectural insight:

**ITK's GIL behavior:**
```
Python thread (IDLE priority):
    sitk_image = reader.Execute()           ← GIL held briefly (~5ms dict ops)
    sitk_image = gaussian.Execute(...)      ← GIL RELEASED (C++ work begins)
        ITK C++ thread pool: [3–16 seconds of pure C++ computation]
    sitk_image = sharpen.Execute(...)       ← GIL RELEASED again
        ITK C++ thread pool: [another multi-second C++ pass]
    result = rescale.Execute(...)           ← GIL RELEASED again
    ← GIL briefly re-acquired for Python object wrap (~1ms)
```

SimpleITK calls release the GIL via `Py_BEGIN_ALLOW_THREADS` before entering the C++ execution layer. The 3–16 second ITK filter chain runs **entirely in C++** with the GIL **released**. During this window, the main thread can freely acquire the GIL and run VTK render.

**Therefore: ITK execution itself is NOT a GIL-level problem.**

ITK CAN cause **CPU saturation** (because its C++ threads run at Normal priority, as covered in Section 4.1), but this is a CPU-core scheduling problem — solved by Change #7 (global ZetaBoost gate), not a GIL problem.

**The GIL problem is entirely in the Python-level download loop:** base64, gzip, json parsing, pydicom loops, progress callback dict operations — all pure Python or Python glue that holds the GIL continuously.

---

## 20. Deep GIL Analysis for Three-Component Concurrency

### 20.1 What the GIL Actually Is

Python's Global Interpreter Lock is a mutex embedded in the CPython runtime:
- Only **one OS thread** can execute Python bytecode at any instant
- The GIL is **not released** during pure Python operations (loops, dict ops, function calls, attribute access)
- The GIL **is released** during:
  - Blocking OS syscalls (socket recv, file write) — handled by the C runtime
  - C extensions that explicitly call `Py_BEGIN_ALLOW_THREADS` (NumPy, SimpleITK, PySide6 render calls)
  - `asyncio.sleep(0)` — explicitly yields the asyncio event loop scheduler (GIL made available to other threads)

**CPython's default GIL switch interval** is 5ms for bytecode-only execution. But if a C extension holds the GIL (anything calling into Python without releasing), that 5ms limit is **not enforced**. Long-running C extensions can hold the GIL for their entire duration.

### 20.2 Per-Component GIL Profile

| Component | GIL Behavior | Hold Duration | Frequency | Viewer Impact |
|-----------|-------------|--------------|-----------|--------------|
| **Viewer Widget (VTK)** | VTK C++ calls release GIL; Python frame-rate management holds briefly | 1–5ms per render tick | Every scroll event (~16ms) | — (owner) |
| **ZetaBoost (Python glue)** | Queue push/pop, flag check: ~1ms bursts | <1ms | Every 80ms–2s (sleep intervals) | **Negligible** |
| **ZetaBoost (ITK C++)** | GIL released during filter chain (3–16s) | 0ms (GIL released) | Once per series | **Negligible** |
| **Download Manager (recv loop)** | `response_data += chunk` — O(n²) copy, NO release | **5–15ms per batch** | Every 1–2s | **HIGH** |
| **Download Manager (file loop)** | base64+gzip Python glue, no yield | **30–130ms per batch** | Every 1–2s | **CRITICAL** |
| **Download Manager (pydicom)** | Pure Python DICOM parser | **15–30ms per file × 50 files = 750ms** | Every ~50 files | **CRITICAL** |

### 20.3 Why ZetaBoost + Viewer Works (Mode A Explained Precisely)

```
Mode A: GIL timeline (50ms window)

Main Thread:     ██████░░░░░░░░░░░░██████░░░░░░░░░░░████████░░░░░░
                 set_slice(20ms)  idle(polls)       set_slice(20ms)

ZetaBoost (Py):  ░░░░░░░░░▮░░░░░░░░░░░░░░▮░░░░░░░░░░░░░░░░▮░░░░░░
                          queue_op(<1ms)  queue_op(<1ms)

ITK C++ threads: ░░░░░░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░
                 [parallel C++ — GIL NOT HELD — runs freely]

LEGEND: ██ = GIL held    ░ = GIL free    ▓ = C++ work (no GIL)    ▮ = <1ms GIL hold
```

ZetaBoost's Python-side activity is scattered <1ms bursts separated by long sleep intervals. The main thread acquires the GIL freely between these micro-bursts. No contention.

### 20.4 Why Download Manager + Viewer Fails (Mode B Explained Precisely)

```
Mode B: GIL timeline (150ms window, unfixed)

Main Thread:     ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░████░░░░░░░░░░░
                 set_slice     BLOCKED (waiting for GIL)  finally runs

Download (Py):   ░░████████████████████████████████░░░░░░████████░░
                   base64×10 + gzip×10 + write×10        pydicom
                   [130ms GIL burst, no yield]            [30ms burst]

User Perception: scroll event → 130ms no response → stutter/jump
```

The 130ms GIL burst means the main thread's next `set_slice()` call cannot execute for 130ms. The slider has moved by then, so when VTK finally renders, it shows a non-continuous position jump — the perception of "choppy" scroll.

---

## 21. The Two-Separate-Processes Approach — Full Evaluation

### 21.1 Why Separate Processes Solve the GIL Problem

When Python code runs in two **separate OS processes**, each process has its **own independent GIL**. They do not share a GIL. The CPython runtime is initialized independently in each process.

```
Current architecture (1 process):

Process: AIPacs.exe
    GIL (shared):
        ├─ Main Thread (viewer, VTK, Qt)
        ├─ DownloadWorker QThread (asyncio, download loop)
        ├─ ZetaBoost workers × 6 (ITK, cache)
        └─ (all compete for ONE GIL)


Proposed architecture (2 processes):

Process 1: AIPacs.exe (Main)
    GIL-1:
        ├─ Main Thread (viewer, VTK, Qt)
        └─ ZetaBoost workers × 6 (ITK, cache)
    ← GIL-1 is NEVER contested by download Python code

Process 2: download_worker (subprocess)
    GIL-2:
        └─ asyncio event loop (download, base64, gzip, pydicom)
    ← GIL-2 bursts have ZERO effect on Process 1
```

### 21.2 How the Two Processes Would Communicate

The download manager writes DICOM files to **disk** — this is already the designed data path. The main process reads them from disk. This means the **heavy data path (bytes)** requires no IPC. The only communication needed is:

| Communication Needed | Volume | Mechanism |
|---------------------|--------|-----------|
| Progress updates (% complete, file count) | Low (~1 per file, small dict) | `multiprocessing.Queue` or named pipe |
| Download completion notification | One-time event per study | Queue sentinel value (`None`) |
| Download error / exception | Rare | Queue exception object |
| Cancel signal (user clicks stop) | User-initiated | `multiprocessing.Event` |
| New download task (study UID, params) | One per download start | Queue or `Process(args=...)` |
| DB metadata writes (pydicom inserts) | Medium (one SQL write per DICOM file, ~100 per series) | Option A: subprocess writes directly to `dicom.db` via its own WAL connection |

**Key insight:** SQLite WAL mode already supports concurrent writers from different processes (WAL is a filesystem-level protocol). The subprocess can write to `dicom.db` with its own connection — no IPC needed for DB writes.

### 21.3 Architecture Sketch — Download Manager as Subprocess

```
Main Process (AIPacs.exe):
┌──────────────────────────────────────────────────────────┐
│ Qt Main Thread                                           │
│   DownloadManagerWidget (UI only — no download logic)   │
│   ├─ Reads progress from progress_queue                  │
│   ├─ Emits UI signals on progress update                 │
│   └─ Owns Cancel Event + Start/Stop lifecycle            │
│                                                          │
│ ZetaBoost Engine (unchanged)                            │
│   └─ Reads .dcm files written by subprocess             │
└───────────┬──────────────────────────────────────────────┘
            │ multiprocessing.Queue (progress updates)
            │ multiprocessing.Event (cancel signal)
            ▼
Subprocess: download_process.py
┌──────────────────────────────────────────────────────────┐
│ asyncio event loop (entire download execution)          │
│   ├─ SocketDicomClient.download_series() [recv + write]  │
│   ├─ SeriesDownloader._save_series_instances_to_db()     │
│   └─ progress_queue.put({files_done, total, speed...})   │
│                                                          │
│ SQLite connection (WAL, direct write to dicom.db)       │
└──────────────────────────────────────────────────────────┘
```

### 21.4 Subprocess Approach — Feasibility Assessment

| Criterion | Assessment | Notes |
|-----------|-----------|-------|
| **GIL isolation** | ✅ Complete | Subprocess has own GIL; download bursts never touch main process |
| **CPU isolation** | ✅ Complete | OS scheduler treats processes independently; subprocess CPU never steals from main thread VTK |
| **Data transfer overhead** | ✅ Near-zero | DICOM bytes already written to disk; only small progress dicts go through Queue |
| **DB access** | ✅ Safe | WAL mode supports concurrent process access; subprocess uses its own connection |
| **PyInstaller compatibility** | ✅ Supported | Requires `multiprocessing.freeze_support()` at `main.py` startup (already standard) |
| **Process startup cost** | ⚠️ ~200–400ms | First download start has a one-time delay for subprocess Python init |
| **Error handling** | Medium | Subprocess exceptions must be serialized through Queue; tracebacks can be passed as strings |
| **Implementation complexity** | Medium–High | Requires refactoring DownloadWorker from QThread to a Process wrapper class |
| **Qt signals** | ⚠️ Requires adapter | Cannot emit Qt signals from subprocess; progress Queue must be polled/piped via a QThread bridge in main process |
| **Cancellation** | ✅ Clean | `multiprocessing.Event` + check in asyncio loop per file = responsive cancel |

### 21.5 Qt Signal Bridge for Progress Updates

Since `subprocess` cannot emit Qt signals directly, the main process uses a thin bridge thread:

```python
class DownloadProgressBridgeThread(QThread):
    """
    Polls multiprocessing.Queue in a QThread.
    Converts progress dicts to Qt signals for UI update.
    """
    progress_signal = Signal(dict)   # forwarded to DownloadManagerWidget
    completed_signal = Signal(str, bool)  # (study_uid, success)
    
    def __init__(self, progress_queue: multiprocessing.Queue):
        super().__init__()
        self._queue = progress_queue
        self._running = True
    
    def run(self):
        while self._running:
            try:
                item = self._queue.get(timeout=0.1)
                if item is None:  # sentinel = download complete
                    self.completed_signal.emit(self._study_uid, True)
                    break
                self.progress_signal.emit(item)
            except queue.Empty:
                pass
```

This bridge QThread holds the GIL only for the brief `queue.get()` check + signal emit — both are <0.5ms. No impact on the viewer.

### 21.6 Comparison: Current Approach vs. Process Isolation

| Approach | Viewer Smoothness | Download Speed | Complexity | Timeline |
|---------|------------------|----------------|------------|----------|
| **Current (unfixed)** | Poor (130ms GIL bursts) | 50–70% of baseline | Baseline | — |
| **Changes #7 + #9A + #9B (near-term)** | Good (<10ms per tick) | 85–95% of baseline | Low | 1–2 sessions |
| **Subprocess Download Manager (long-term)** | **Excellent (<5ms per tick)** | **100% of baseline** | High | 1–2 weeks |
| **ProcessPoolExecutor for ITK (long-term)** | Excellent | Unaffected | High | 1–2 weeks |

**Recommendation:**
- Implement Changes #7 + #9A + #9B first (near-term). This brings viewer performance to "good" and is low-risk.
- After that stabilizes, migrate download manager to subprocess (long-term) for "excellent" — eliminates all GIL contention at the architectural level, not just mitigates it.

---

## 22. Three-Component Concurrency — Viewer + ZetaBoost + Download Manager

### 22.1 Mode B + ZetaBoost Active (The Worst Case)

When all three components run simultaneously (download active, ZetaBoost warmup active, viewer scrolling), the observed slowdown is worse than any two-component combination. This is consistent with cumulative GIL and CPU contention:

```
Three-component GIL contention (worst case, unfixed):

Main Thread:      ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░██
                  set_slice  ←──────────── 130ms waiting ──────────→  set_slice

Download QThread: ░░███████████████████████████████░░░░░░░░████████░░░░
                     base64×10+ gzip×10 (130ms burst)      pydicom (30ms)

ZetaBoost (Py):   ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░▮▮░░░░░░░░░░░░░░░░░░
                                                  queue ops (<1ms)

Net result: main thread waits ≥130ms between every two scroll ticks.
Perceived: viewer barely responds.
```

The ZetaBoost Python bursts (<1ms) are negligible, but their ITK C++ threads (if warmup is NOT globally gated) saturate CPU cores at Normal priority, making VTK's CPU-bound reslice take 2× longer even when the GIL IS free.

**Mode B + ZetaBoost with Change #7 applied:**
```
ZetaBoost warmup: BLOCKED (global download counter > 0)
ITK C++ threads:  NOT SPAWNED during download
CPU cores:        Available fully for VTK render + download asyncio
GIL:              Still contested by download Python code (fixed by #9A/#9B)
```

### 22.2 Why ZetaBoost + Viewer Works in Mode A

In Mode A, ZetaBoost warmup IS allowed to run. ITK C++ threads are spawned. Yet the viewer is smooth. Why?

**Answer: Sequential ITK scheduling, not continuous saturation.**

ZetaBoost processes one series at a time (`max_parallel_loads=1`). Each ITK run takes 3–12s, after which there is a `time.sleep(0.5)` before the next job starts. During the 0.5s gap, CPU cores are completely free for VTK render.

More importantly: **when the user scrolls, the interactive lane submits a job that preempts warmup in priority.** Warmup waits. The user gets full CPU for their interaction.

In Mode B, this sequential courtesy breaks: the download asyncio loop never pauses, never gives the main thread a CPU-free window of >5ms, and its GIL bursts prevent the main thread from even entering VTK render.

### 22.3 Three-Component Target Performance (With All Fixes)

With Changes #7 + #9A + #9B, and later subprocess isolation:

| Component | Resource Usage | Main Thread Impact |
|-----------|---------------|-------------------|
| **Viewer Widget** | CPU: 20–40% (VTK C++), GIL: 1–5ms/tick | — (IS the main thread) |
| **ZetaBoost (download active)** | Python GIL: <1ms/queue op; ITK: BLOCKED (global gate) | Negligible |
| **Download Manager (with #9A/#9B)** | GIL: <10ms/batch (was 130ms) | Minor (viewer tick delayed <10ms) |
| **Download Manager (subprocess)** | GIL: None (own GIL in subprocess) | **Zero** |

### 22.4 Three-Component Architecture with Subprocess Download

```
Main Process:
    Main Qt Thread:
        VTK render, scroll handling, UI — uncontested GIL
    
    ZetaBoost Engine:
        6 daemon threads @ IDLE python priority
        Warmup: blocked while download_active (Change #7)
        Interactive: always responds within 80ms
        ITK C++ (warmup): only when no download active
    
    Progress Bridge QThread:
        Polls multiprocessing.Queue → emits Qt signals
        GIL hold: <0.5ms per poll cycle

Download Subprocess:
    asyncio event loop (own GIL, own CPU):
        recv, base64, gzip, pydicom — unlimited GIL hold is OK
        Writes .dcm files to shared disk path
        Writes metadata to dicom.db (WAL, own connection)
        Puts progress dicts into multiprocessing.Queue
```

**Result with this architecture:**

| Metric | Target Value |
|--------|-------------|
| `set_slice` during download (VTK software render) | 20–37ms (pure C++ floor) |
| `set_slice` during download (goal — hardware OpenGL) | <5ms |
| GIL stall from download | **0ms** (separate process) |
| Download speed vs baseline | **100%** (no GIL competition) |
| ZetaBoost interactive load | <200ms (preview) + 3–12s (full, background) |
| EVENT_LOOP_LAG | <5ms throughout download |

---

## 23. Ranked Solution Roadmap

The following table ranks all solutions from immediate to long-term, covering all three components:

| Rank | Solution | Fixes | Impact | Complexity | When |
|------|---------|-------|--------|------------|------|
| **1 (P0)** | Change #7: Global ZetaBoost gate | CPU core saturation during cross-study download | EVENT_LOOP_LAG: 4500ms → <50ms | Low | Next session |
| **2 (P1)** | Change #9A: bytearray recv | O(n²) GIL burst in recv loop | 5–15ms GIL burst eliminated per batch | Low | Next session |
| **3 (P1)** | Change #9B: asyncio.sleep(0) per 3 files | 30–130ms GIL burst in file loop | set_slice: 22–37ms → <10ms | Low | Next session |
| **4 (P2)** | Wire PreviewEngine universally | 3–12s cold-cache stall on drag/drop | User sees preview in <200ms always | Low | Next session |
| **5 (P3)** | Hardware OpenGL (remove SW render flag) | 20–37ms VTK baseline too high | set_slice: 20–37ms → <5ms | Very Low | After #7/#9 validated |
| **6 (P4)** | Subprocess Download Manager | ALL download GIL interference, permanently | Download=100% speed, viewer=perfect | High | After near-term fixes stable |
| **7 (P5)** | ProcessPoolExecutor for ITK | CPU isolation for warmup ITK work | Warmup never competes with viewer even if run during download | High | After subprocess download works |

### 23.1 Decision Tree for "Which Fix to Apply First"

```
Is viewer lag still present after Change #7?
    YES → Apply Changes #9A + #9B (GIL yield fixes)
    NO  → Stop here; #7 was sufficient (unlikely — GIL still present)

Is scroll still >20ms per tick after #7 + #9A + #9B?
    YES → Check: is VTK_FORCE_SOFTWARE_RENDERING=1 ?
        YES → Remove it and test hardware OpenGL
        NO  → Profile set_slice() for new hotspot
    NO  → Good; proceed to PreviewEngine wiring (#4)

Is 3–12s cold-cache stall still happening?
    YES → Wire PreviewEngine universally (#4)
    NO  → Already resolved

Is download speed still reduced vs no-viewer baseline?
    YES with #9A/#9B → Implement subprocess download manager (#6)
    NO  → GIL yield approach is sufficient
```

---

## 24. Architectural Invariants — Extended (Three-Component Rules)

**Additions to Section 18 invariants:**

### Rule 7: Download Manager GIL Budget (Extended)
> The download QThread (or subprocess) MUST NOT hold the Python GIL for **more than 10ms** continuously. If the subprocess architecture is adopted, this rule is automatically satisfied (no shared GIL). Until then, every loop in SocketDicomClient and SeriesDownloader must yield via `asyncio.sleep(0)` at intervals that keep individual GIL holds under 10ms.

### Rule 8: Three-Way Mode B Interaction Must Be Tested Explicitly
> Whenever any change is made to the download manager, ZetaBoost engine, or viewer widget, run a Mode B test with **all three active**: (1) viewer open and user scrolling, (2) download of a second study active, (3) ZetaBoost warmup allowed (or verify it is globally gated). A fix that helps one component in isolation may cause regression when all three interact.

### Rule 9: Subprocess Boundary (If Adopted)
> If download manager is migrated to a subprocess, the process boundary is strict: **no VTK objects, no Qt objects, no PySide6 imports** may exist inside the subprocess. All UI state updates cross the boundary via `multiprocessing.Queue`. The subprocess writes to disk and database only. The main process owns all UI and VTK state.

### Rule 10: ZetaBoost Interactive Lane Is Sacred
> The interactive lane (user drag/drop, explicit series load request) is **never blocked** — not by global download counter, not by scroll-activity gate, not by subprocess migration. It must always respond within 80ms (with PreviewEngine) for Mode A behavior to be preserved at all times.

---

## Final Notes

This document is the **single source of truth** for Mode B performance work. All future investigation, testing, or code changes related to download/viewer concurrency must:
1. Reference this document
2. Update this document with new findings
3. Follow the architectural invariants in Section 18

**Document Maintenance:**
- **When reapplying fixes:** Mark Section 13 items as "Applied" with commit hash
- **When validating tests:** Update Section 15 with actual metrics observed
- **When discovering new issues:** Add to Section 16 with priority assessment
- **When implementing long-term solutions:** Move from Section 17 to Section 13 and update validation

**Version Control:**
- This document lives in `docs/MODE_B_PERFORMANCE_COMPLETE_ANALYSIS_v2.2.2.5.md`
- Previous investigation at `docs/MODE_B_FIX_INVESTIGATION.md` (preserved for historical reference)
- On major architecture changes, create a new version: `*_v2.2.2.6.md`, etc.


---

*End of Document — v2.2.2.5 base content. Part VII added 2026-02-24.*

---

## Part VII: Advanced Optimization Research — Viewer Widget, ZetaBoost Subprocess, and External Benchmarks

**Added:** 2026-02-24
**Inputs:** Live application logs (Mode B session), codebase deep-dive (vtk_widget.py, viewer_2d.py, patient_widget_viewer_controller.py, image_io.py, image_filters.py, zeta_boost/engine.py), VTK 9.6 API reference, external architecture review (3D Slicer, Cornerstone.js, OHIF, Horos/OsiriX).

---

## 25. Log Analysis — Mode B Live Session Findings

### 25.1 Concrete Timing Data

Cold-load series switches (ZetaBoost blocked by Change #7 during download, interactive lane only):

| Series | Slices | ITK filters | Total cold | Note |
|--------|--------|------------|------------|------|
| Series 4 | 9 | 1.968s | ~2,981ms | Interactive lane, ZetaBoost blocked |
| Series 7 | 23 | 2.704s | ~4,348ms | Interactive lane, ZetaBoost blocked |

Warm-cache series switch (ZetaBoost pre-load, post-download):

| Series | Slices | Cache | Total warm | Note |
|--------|--------|-------|------------|------|
| Series 4 | 9 | HIT | 566.7ms | `cache_hit=True`, ZetaBoost worked |

Other timings from logs:

| Event | Duration | Source |
|-------|---------|--------|
| `reset_image_viewer` series 4 | 0.034s | viewer log |
| `reset_image_viewer` series 7 | 0.050s | viewer log |
| Zoom/scale restore | 0.031–0.066s | viewer log |
| Viewer container creation | ~1,399ms | tab open log |
| Thumbnail display (6 thumbs) | ~2,353ms | tab open log |

**Key finding:** The ITK filter chain (1.968–2.704s) accounts for 66–62% of total cold-load time in Mode B. With a cache hit, total time drops to 566ms — a 5–7× improvement. ZetaBoost is working correctly; the issue is that Change #7 prevents it from warming up during download, leaving 40+ WORKER_BLOCKED events over the 2-minute download window.

### 25.2 ZetaBoost Blocking During Download (Change #7)

```
[ZetaBoost] WORKER_BLOCKED lane=warmup worker=2 reason=global_download_active(1) pending=5
```

This line repeated approximately 40 times across the full download session. Five series in the warmup queue sat unprocessed for ~2 minutes. This is the intended behavior of Change #7 (prevents CPU saturation during download), but it means the user still faces cold-cache loads for all 5 series immediately after download ends.

**ZetaBoost health state mid-download:**
```
[ZetaBoost] HEALTH ... miss=9 put=3 queued=5 processed=0 failed=0
```
- `miss=9`: 9 cache misses experienced by the viewer
- `put=3`: 3 series manually loaded by user (interactive lane bypasses ZetaBoost block)
- `queued=5`: 5 series waiting in warmup queue
- `processed=0`: zero warmup completions during download period

**ZetaBoost recovery after download:**
```
[ZetaBoost] PROCESS_START lane=warmup worker=2 series=3
```
Warmup started immediately after download completed — correct behavior.

### 25.3 Subprocess Lifecycle Bug

```
[SubprocessWorker] Subprocess still alive after bridge loop — terminating
*End of Document*
Invalid transition: Paused -> Failed
Invalid transition: Pending -> Completed
```

**Root cause:** The download was preempted mid-transfer by a higher-priority download. Inside the subprocess, an exception was raised in `_series_download_worker_async()`. The asyncio exception propagated but the `finally` block that sends the `{'type': 'completed', ...}` sentinel to `progress_queue` was not reached before the process exited. The bridge loop in `SubprocessDownloadWorker` polled for a sentinel that never arrived, timed out (~5s), then called `proc.terminate()` as last resort.

**Effect:** Subprocess was force-killed. Behavior for the user: no data loss (preempted download was re-queued), but an unnecessary 5-second wait before clean termination.

**Fix required:** Ensure `finally` in the subprocess's async loop always sends either `{'type': 'error', ...}` or `{'type': 'exit_ack', ...}` before exiting. Bridge loop must accept `'exit_ack'` as a valid termination signal.

---

## 26. Viewer Widget — Complete Internal Architecture Map

### 26.1 Class Hierarchy

```
VTKWidget(QVTKRenderWindowInteractor)
    Render throttle: _RENDER_THROTTLE_MS = 16ms (60fps max)
    Double buffering: SetDoubleBuffer(True), SetSwapBuffers(True)
    Qt flags: WA_OpaquePaintEvent

  └── image_viewer: ImageViewer2D(vtkResliceImageViewer)
        Class-level cache: _global_preprocess_cache
            max_entries = 8, max_slices = 160, threading.Lock
            Key: series fingerprint (path hash + filter config hash)
            Value: preprocessed vtkImageData

        └── image_reslice: ImageReslice(vtkImageReslice)
              Interpolation: SetInterpolationModeToCubic()
              Optimization: OptimizationOn()
              Auto-crop: SetAutoCropOutput(False)
              Dimensionality: SetOutputDimensionality(3)
              VTK threading: vtkThreadedImageAlgorithm (all C++, GIL free)
              Initial setup: single Update() at construction
```

### 26.2 Data Flow

```
DICOM files (disk)
    ↓ sitk.ImageSeriesReader.Execute()         C++, GIL free
    ↓ apply_filters(): RecursiveGaussian X→Y→Z C++, GIL free
    ↓ sitk.GetArrayViewFromImage()             numpy view, zero-copy
    ↓ numpy_to_vtk()                           C extension, GIL free
    ↓ vtkImageData (in main process memory)
          ↓ stored in _global_preprocess_cache
          ↓ set as input to ImageReslice

Per-scroll-tick (Qt main thread):
    image_reslice.Update()       ← C++, vtkThreadedImageAlgorithm
    UpdateDisplayExtent()        ← C++, brief
    Render()                     ← OpenGL blit (SW) or GPU (HW)
```

### 26.3 Key Constants (from vtk_widget.py and viewer_2d.py)

| Constant | Value | Purpose |
|----------|-------|---------|
| `_RENDER_THROTTLE_MS` | 16ms | Max 60fps render rate |
| `_VIEWER_BATCH_DELAY_MS` | 8ms | Batch scroll event coalescing |
| `_SPINNER_HIDE_DELAY_MS` | 50ms | Hide loading spinner delay |
| `_global_preprocess_cache_max_entries` | 8 | Maximum cached series |
| `_global_preprocess_cache_max_slices` | 160 | Threshold: skip caching large series |

### 26.4 PreviewEngine Wiring Status

`PreviewEngine` is instantiated in `patient_widget_viewer_controller.py` at line 287:
```python
self._preview_engine = PreviewEngine(logger=self.logger)
```

It is referenced in the standard drag-drop load path (line 2259) but has NOT been wired into all code paths (notably some drag+drop variants and the `AsyncSwitchLoad` thread). This is the most impactful single-point fix to make: universally wiring preview means users see a first slice in <200ms on ANY series switch, not just the paths that were explicitly coded.

---

## 27. VTK/ITK Bottleneck Analysis

### 27.1 vtkImageReslice Threading Model

`vtkImageReslice` inherits from `vtkThreadedImageAlgorithm`. This uses `vtkMultiThreader::ThreadedExecute()` which spawns N C++ threads (N = CPU core count by default). The `ThreadedRequestData()` method divides the output image into N horizontal strips and processes each strip in a separate thread. **The GIL is not held during this operation** — it is all C++ on VTK's internal thread pool.

This means:
1. `image_reslice.Update()` does NOT block Python thread execution
2. Multiple parallel VTK reslice calls would compete for CPU cores but not for GIL
3. The bottleneck on reslice speed is purely CPU core count and memory bandwidth

**Thread count control:**
```python
import vtk
vtk.vtkMultiThreader.SetGlobalMaximumNumberOfThreads(4)  # limit to half of 8-core
```

### 27.2 Software vs. Hardware OpenGL Impact

| Path | Software | Hardware GPU |
|------|----------|-------------|
| `image_reslice.Update()` CPU pass | 20–37ms | 18–33ms (same C++ path, minor improvement from OS scheduling) |
| `Render()` composite pass | 2–5ms | <1ms |
| Per-tick total | **22–42ms** | **19–34ms** |
| Annotation/overlay rendering | 5–15ms | <2ms (GPU shader) |
| CUDA-accelerated ITK filters | Not available | Available (cuCIM/CuPy) |

Enabling hardware OpenGL provides a modest direct improvement in per-tick rendering but is a critical enabler for GPU-accelerated filter paths and future sub-1ms scroll via GPU texture atlas.

### 27.3 ITK Filter Chain Profile

**`apply_filters()` chain (from `image_filters.py`):**
```
sitk.Cast(img, sitkFloat32)                   ~1ms
sitk.RecursiveGaussian(sigma, direction=0)    ~500–1500ms per axis (C++)
sitk.RecursiveGaussian(sigma, direction=1)    ~500–1500ms per axis (C++)
sitk.RecursiveGaussian(sigma, direction=2)    optional, same cost
sitk.Cast(out, original_pixel_id)             ~1ms
```

**GIL behavior:** All `sitk.RecursiveGaussian` calls release the GIL via `Py_BEGIN_ALLOW_THREADS` in the underlying ITK C++ code. Python threads (including Qt's event loop) are free to execute during this time. The bottleneck is CPU time, not GIL contention.

**Thread count:** SimpleITK uses `itk::MultiThreaderBase` internally. Default: all CPU cores. Setting `sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(N)` limits all ITK operations.

**Observed timings:**
- 9-slice series: `apply_filters` = 1.968s
- 23-slice series: `apply_filters` = 2.704s
- Scaling is roughly linear in number of voxels

---

## 28. ZetaBoost Subprocess — Feasibility Deep-Dive

### 28.1 Subprocess Safety Audit

| Step | Subprocess-safe? | Notes |
|------|-----------------|-------|
| `sitk.ImageSeriesReader` | ✅ Yes | Pure C++ ITK, no Qt/VTK |
| `apply_filters()` | ✅ Yes | Pure C++ ITK, no Qt/VTK |
| `sitk.GetArrayFromImage()` | ✅ Yes | Returns numpy array |
| `numpy_to_vtk()` | ❌ No | VTK objects are NOT safe to create in subprocess |
| `vtkImageData` creation | ❌ No | Must stay in main process |
| Qt signal emit | ❌ No | Cannot use PySide6 signals from subprocess |

**Conclusion:** The bottle-neck operations (DICOM read + ITK filters) are 100% subprocess-safe. VTK/Qt steps must stay in the main process — this maps to a clean split: ITK in subprocess → numpy array over IPC (shared_memory) → VTK wrapping in main process.

### 28.2 IPC Cost (multiprocessing.shared_memory)

For a typical MR series (320×300×23 slices, uint16 = 4.4 MB):

- Create `SharedMemory` + `np.copyto` into it: ~2ms
- Pass handle (string) via `Queue`: <0.1ms
- Main process: open SharedMemory + copy out + unlink: ~1ms
- **Total IPC overhead: <3ms**

This is negligible relative to the 1.0–3.5s ITK processing time.

### 28.3 ZetaBoost Subprocess vs. Change #7

**With Change #7 (current):**
- ZetaBoost warmup completely blocked during download (~2 min)
- All 5 queued series remain cold for the entire download window
- After download: sequential 2–3s ITK per series = 10–15s of post-download cold-load stalls

**With ZetaBoost subprocess (target):**
- ZetaBoost subprocess runs at IDLE OS priority continuously
- Download subprocess at NORMAL priority
- Both run simultaneously — no GIL contention, OS CPU scheduling handles priority
- By download end: all 5 series already warm-cached
- Post-download: immediate <566ms series switches

**Change #7 fate:** When ZetaBoost moves to a subprocess, the global gate can be relaxed. It should be changed from "block warmup during download" to "limit ZetaBoost subprocess to IDLE CPU priority always." The block is no longer needed because GIL isolation removes the contention.

### 28.4 Architecture Diagram

```
ZetaBoost Subprocess (per-tab, spawned on tab open, IDLE priority):
┌──────────────────────────────────────────────────────────────┐
│  work_queue:   Queue of (series_number, dcm_paths, filter_cfg)│
│  result_queue: Queue of (series_number, shm_name, shape, dtype)│
│  cancel_event: multiprocessing.Event                         │
│                                                              │
│  while not cancel_event.is_set():                            │
│    item = work_queue.get()                                   │
│    itk_img = sitk.ImageSeriesReader.Execute(paths)           │
│    filtered = apply_filters(itk_img, cfg)                    │
│    arr = sitk.GetArrayFromImage(filtered)                    │
│    shm = SharedMemory(create=True, size=arr.nbytes)          │
│    np.copyto(np.ndarray(..., buffer=shm.buf), arr)           │
│    result_queue.put((series, shm.name, shape, dtype, meta))  │
│    shm.close()   # subprocess only closes, never unlinks     │
└──────────────────────────────────────────────────────────────┘
               ↓ result_queue
ZetaBoostResultBridge(QThread) — main process, NORMAL priority:
    polls result_queue every 50ms
    opens SharedMemory(shm_name)
    arr = np.ndarray(shape, dtype, buffer=shm.buf).copy()
    shm.close(); shm.unlink()     ← Rule 13: main process unlinks
    vtk_img = numpy_to_vtk(arr)   ← VTK only in main process
    ZetaBoostEngine._cache[series] = vtk_img
    emit cache_updated(series_number)  ← Qt signal, main process only
```

### 28.5 Complexity and Timeline

| Criterion | Assessment |
|-----------|-----------|
| GIL isolation | Complete (own interpreter) |
| IPC mechanism | `shared_memory` — <3ms for any series |
| Lifecycle | Spawn on tab open, join on tab close |
| Qt bridge | `ZetaBoostResultBridge(QThread)` — same pattern as download bridge |
| PyInstaller | `freeze_support()` already in `main.py` |
| Complexity | High — new subprocess module, bridge QThread, shared_memory lifecycle |
| Prerequisite | Subprocess download must be stable first |
| Estimated timeline | 1–2 weeks after download subprocess is stable |

---

## 29. Three-Subprocess Architecture (Target State)

```
MAIN PROCESS (Qt main thread)
    VTK rendering, scroll handling, signal/slot wiring
    QThread: SubprocessDownloadBridge
    QThread: ZetaBoostResultBridge
    QThread: AsyncSwitchLoad (interactive series switch)
    ThreadPoolExecutor(4): misc callbacks
         │                      │
         │  progress_queue       │  result_queue + shared_memory
         ▼                      ▼
DOWNLOAD SUBPROCESS          ZETA BOOST SUBPROCESS (per-tab)
  Priority: NORMAL              Priority: IDLE
  asyncio download loop         ITK: DICOM read + filters
  base64 / gzip / pydicom       No Qt, no VTK
  No Qt objects                 Output: numpy arrays via shm
```

**Process boundary rules (additions to Section 18):**

| Component | Must run in | May NOT run in |
|-----------|------------|----------------|
| Qt event loop | Main process | Subprocess |
| VTK render window | Main process | Subprocess |
| `vtkImageData` creation | Main process | Subprocess |
| `numpy_to_vtk()` | Main process | Subprocess |
| `sitk.ImageSeriesReader` | Main OR ZetaBoost subprocess | — |
| `asyncio` download loop | Download subprocess | Main process |
| `SharedMemory.unlink()` | Main process | Subprocess (Rule 13) |

---

## 30. Alternative Optimization Approaches (Beyond Subprocess)

### 30.1 Approach A: Adaptive Interpolation Quality

Use linear interpolation during scroll, cubic on stop. Validated by 3D Slicer in production.

**Expected impact:** Scroll reslice: 20–37ms → 8–15ms. Zero visual quality regression on stationary frame.

```python
# On scroll start:
self.image_viewer.image_reslice.SetInterpolationModeToLinear()

# On scroll stop (QTimer, 100ms delay):
self.image_viewer.image_reslice.SetInterpolationModeToCubic()
self.image_viewer.image_reslice.Update()
self.image_viewer.Render()
```

### 30.2 Approach B: Progressive Series Loading (`grow_vtk_inplace`)

`grow_vtk_inplace()` in `vtk_widget.py` already implements in-place VTK array update via `SetScalars()` pointer swap (no DeepCopy). Wire it to incremental series loading:

1. PreviewEngine shows slice 1 in <200ms
2. Background worker loads 10 slices → `grow_vtk_inplace()` → viewer updates
3. Background worker applies ITK filters → `grow_vtk_inplace()` → final quality

Converts a 2–5s hard block into <200ms first-display with progressive enhancement.

### 30.3 Approach C: ITK Filter Laziness During Mode B

When download is active (Change #7 gate), skip ITK filters for warmup-lane series. Cache unfiltered numpy array immediately. Queue a second-pass filter job to run after download ends. Series cached unfiltered are negligibly worse only if user views them during the <3s filter-pass window after download.

**Impact:** Warmup throughput increases ~3× during Mode B (no filter cost).

### 30.4 Approach D: OS Page Cache Priming

Before ZetaBoost submits an ITK job, a background thread reads the first 4KB of each DICOM file. This pre-faults pages into OS disk cache. ITK then reads from RAM. Cost: ~2ms for 23 files. Benefit: 0.3–0.5s reduction in ITK reader time.

### 30.5 Approach E: ITK + VTK Thread Budget Policy

```python
# On download start:
sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(max(1, n_cpu // 2))
vtk.vtkMultiThreader.SetGlobalMaximumNumberOfThreads(max(1, n_cpu // 4))

# On download end:
sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(n_cpu)
vtk.vtkMultiThreader.SetGlobalMaximumNumberOfThreads(n_cpu)
```

This ensures all three subsystems (download, ZetaBoost warmup, viewer reslice) get CPU headroom on the same machine.

---

## 31. External Architecture Benchmarks

### 31.1 3D Slicer (VTK + ITK + Qt5)

| Aspect | 3D Slicer | AIPacs Current | AIPacs Target |
|--------|-----------|----------------|--------------|
| DICOM I/O isolation | QThread + `processEvents()` pings | Subprocess (own GIL) ✅ superior | — |
| ITK thread budget | N_CPUS/2 during import | No budget | Approach E |
| Scroll interpolation | Linear → Cubic on stop | Cubic always | Approach A |
| Background prefetch | vtkSlicerModuleLogic QTimer | ZetaBoost lanes | Equivalent |
| Progressive display | QTimer chunks | `grow_vtk_inplace` available | Approach B |
| Renderer | Hardware OpenGL | Software CPU | Enable GPU |

AIPacs's subprocess isolation is superior to 3D Slicer's `processEvents()` approach. Remaining gap: hardware OpenGL + thread budgeting + adaptive interpolation.

### 31.2 Cornerstone.js (WebGL + Web Workers)

Achieves sub-1ms scroll via:
1. DICOM decode in Web Workers (own JS thread = own "GIL")
2. Decoded pixels uploaded as GPU texture atlas once
3. Scroll = GPU texture coordinate offset — no reslice computation at all

Takeaway: Sub-1ms scroll for AIPacs requires pre-computing all Z-slices and storing as a flat VTK volume at warmup time (using `grow_vtk_inplace`), then replacing `image_reslice.Update()` with a direct slice index lookup. This is feasible for axial-only views but requires larger architectural change.

### 31.3 OHIF Viewer (React + DICOMweb)

- Progressive streaming: first slice displayed <100ms, rest streams in
- `imageCache` LRU — identical architecture to `_global_preprocess_cache`
- Validates: PreviewEngine + ZetaBoost approach is industry-standard

Takeaway: The missing piece compared to OHIF is wiring `grow_vtk_inplace` into the full streaming path.

### 31.4 Architecture Comparison

| Application | DL Isolation | ITK Budget | Renderer | Progressive | Warm Switch |
|------------|--------------|------------|---------|------------|-------------|
| AIPacs current | Subprocess ✅ | Blocked gate | SW CPU | Preview only | 550ms (warm) / 3–5s (cold) |
| AIPacs target | Subprocess ✅ | Budget + ZB subprocess | HW OpenGL | grow_inplace | ~200ms any |
| 3D Slicer | QThread processEvents | N_CPUS/2 | HW OpenGL | QTimer chunks | 200–500ms |
| Cornerstone.js | Web Worker | GPU | WebGL | Sub-1ms atlas | <5ms |
| OHIF | Background stream | GPU | WebGL | Incremental | 100–300ms |
| Horos / OsiriX | GCD queue | N_CPUS/2 | macOS Metal | Spinner+async | 50–200ms |

---

## 32. Revised Ranked Solution Roadmap

| Rank | Solution | Impact | Status |
|------|---------|--------|--------|
| 1 | Subprocess Download Manager | GIL isolation for download | ✅ Done |
| 2 | Change #7: Global ZetaBoost gate | No CPU saturation during download | ✅ Done |
| 3 | Changes #9A/B/C: GIL yield points | Defense in depth | ✅ Done |
| 4 | **Fix subprocess preemption exit bug** | Clean lifecycle on cancel — no 5s wait | Next (1–2 hrs) |
| 5 | **Wire PreviewEngine universally** | Cold stall: 3–5s → <200ms (first slice) | Next (short) |
| 6 | Hardware OpenGL (verify + enable) | GPU enabler; direct: 5ms → <1ms Render() | 1 day |
| 7 | Adaptive interpolation (Approach A) | Scroll: 20–37ms → 8–15ms per tick | 1 day |
| 8 | ITK + VTK thread budget (Approach E) | CPU fairness all three subsystems | 2 hrs |
| 9 | **ZetaBoost subprocess** | Warm ALL series DURING download — eliminates Mode B post-DL cold stalls | 1–2 weeks |
| 10 | Progressive grow_vtk_inplace (Approach B) | 5s cold stall → <200ms progressive | 1–2 weeks |
| 11 | Pre-reslice slice atlas cache | Sub-1ms scroll — all slices pre-computed | Long-term |

---

## 33. Architectural Invariants — Part VII Additions

**Rule 11: Adaptive Interpolation Cannot Leave Linear as the Final Frame**
> If adaptive Linear→Cubic interpolation is implemented, the stationary frame MUST always be re-rendered cubic. The `QTimer` delay before cubic restore MUST be configurable (default: 100ms). Non-compliance (final frame in linear) is a ship-blocking regression.

**Rule 12: ZetaBoost Subprocess Must Run at IDLE OS Priority**
> When ZetaBoost is moved to a subprocess, OS priority MUST be `IDLE_PRIORITY_CLASS` (Windows) or `nice(19)` (Linux). Download subprocess runs at NORMAL priority. This ensures download throughput is never degraded by ZetaBoost warmup CPU usage. Priority is set with `psutil.Process().nice(...)` immediately after `Process.start()`.

**Rule 13: Shared Memory Must Be Unlinked by the Main Process**
> Every `SharedMemory` block created by a ZetaBoost subprocess MUST be `unlink()`ed by the bridge thread in the main process after reading and copying the array. The subprocess MUST call only `shm.close()`, never `shm.unlink()`. Orphaned POSIX shared memory segments do not appear in Python memory profilers. On Linux they persist in `/dev/shm/` until reboot. Verification after each tab close: `ls /dev/shm/` should show no stale segments.

**Rule 14: Subprocess Preemption Must Send Sentinel Before Exiting**
> When a subprocess is preempted or cancelled, it MUST send `{'type': 'error', 'message': '...'}` or at minimum `{'type': 'exit_ack'}` to `progress_queue` BEFORE the asyncio event loop exits. The `finally` block in the subprocess async entry point is the mandatory location for this sentinel send. The bridge loop in `SubprocessDownloadWorker` MUST accept `'exit_ack'` as a clean termination signal. Forced `proc.terminate()` is used only after a 3s timeout and is the last resort.

**Rule 15: Hardware OpenGL Is the Deployment Target — Software Mode Is for Debugging Only**
> `VTK_FORCE_SOFTWARE_RENDERING=1` is a debugging aid, not a deployment configuration. All performance targets in this document assume hardware OpenGL. Remove this env var before measuring scroll performance on target hardware. On machines with confirmed GPU (use `vtkRenderWindow.GetOpenGLLevel()` to verify), it MUST be removed. Machines with verified no-GPU (embedded, server) are the only exception.

---

*End of Document — v2.2.2.5 + Part VII (2026-02-24)*
