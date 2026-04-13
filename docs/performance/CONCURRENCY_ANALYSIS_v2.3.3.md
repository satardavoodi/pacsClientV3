# Concurrent Execution Analysis — AIPacs FAST Viewer v2.3.3

**Date:** 2026-04-19  
**Scope:** FAST mode only (`BACKEND_PYDICOM_QT`). Advanced/VTK paths excluded per engineering preferences.  
**Status:** Analysis complete. Recommended as the formal workload/contention model input for KPI-driven optimization.

---

## Executive Summary

AIPacs runs **3 OS processes** and up to **18 threads** in the main process during simultaneous download + viewing. Individual subsystems (viewer scroll, download, caching, progressive display) have been optimized in isolation. However, **no cross-subsystem resource coordination exists**. When all subsystems compete simultaneously:

1. **pydicom.dcmread holds the GIL for 3–8ms per call** — the single biggest bottleneck. With 4 decode workers + main thread, worst-case GIL convoy = 5 × 8ms = 40ms serialized.
2. **Thread pool sizes are mostly hardcoded** — an i3 (4 cores) runs the same 4 decode workers as an i9 (24 cores), saturating the i3 while underutilizing the i9.
3. **No backpressure exists between subsystems** — ZetaBoost, LW2D decode, download, and progressive display all run independently with no shared load signal.
4. **GPU detection does not influence compute paths** — only affects OpenGL mode (hardware vs software), not thread counts, decode strategy, or filter offloading.

The result: on low-end hardware, all subsystems compete for the same 4 cores and GIL, and nobody wins.

---

## Workload Class & Priority Model (Formal)

The FAST viewer performance program uses four workload classes:

| Class | Definition | Typical examples | Scheduling intent |
|---|---|---|---|
| **Foreground hard-interactive** | In-frame user-visible work with strict frame budget sensitivity | wheel-driven frame generation, immediate paint, direct slice switch response | Highest priority, shortest queue, preempt all lower classes |
| **Foreground soft-interactive** | User-visible work that can lag slightly without breaking interaction feel | post-scroll annotation refresh, post-stop filter refine | High priority, but preemptable by hard-interactive tasks |
| **Background latency-sensitive** | Needed for near-term UX continuity but not frame-critical | progressive grow, decode prefetch, batched progress dispatch | Budgeted and yield-aware; defer under sustained hard-interactive pressure |
| **Background deferrable** | Non-urgent work with no immediate UI value | warmup, low-priority maintenance/cleanup, non-critical reconciliations | Run opportunistically; suspend first under pressure |

Policy rule: a gain in background throughput never justifies a regression in hard-interactive KPIs.

---

## Producer/Consumer Boundaries and Queues

### Producer/consumer map

| Producer | Consumer | Boundary type | Queue/buffer | Contention risk |
|---|---|---|---|---|
| Download subprocess workers | DM bridge QThread | inter-process | `multiprocessing.Queue` (progress messages) | low GIL risk (wait releases GIL) |
| DM bridge batched signals | Qt main thread | cross-thread Qt signal | event loop queue | medium when burst aligns with scroll |
| LW2D decode submitter | decode workers | in-process thread pool | executor pending futures | high during cache-miss overlap |
| LW2D frame submitter | frame workers | in-process thread pool | executor pending futures | medium |
| progressive grow timer | Qt main thread | timer callback | timer/event queue | medium with scroll overlap |
| user wheel input | Qt main thread | UI event queue | event queue backlog | high if main thread delayed |

### Queue buildup and stale work hotspots

1. Decode and frame pending futures during rapid direction changes.
2. Progressive grow callbacks arriving while hard-interactive scroll is active.
3. UI event queue backlog when hard-interactive frame pipeline slips behind input rate.

---

## Stale Work and Cancellation Requirements

| Work unit | Can go stale? | Cancellation expectation | Failure if not canceled |
|---|---|---|---|
| Decode prefetch for old direction | Yes | cancel/skip once slice intent changes | wasted GIL time + queue pressure |
| Frame generation for superseded target | Yes | drop before paint if superseded | jank and stale frame flashes |
| Progressive grow updates older than current visible need | Partially | coalesce and skip obsolete increments | main-thread timer pressure |
| Warmup/background cache tasks | Yes | suspend during active overlap | unnecessary contention |

Required metric linkage:
- `stale_task_ratio`
- `canceled_task_ratio`
- `decode_queue_depth`
- `foreground_task_wait_ms`

---

## Starvation & Fairness Risks

Potential starvation patterns:
1. Background latency-sensitive tasks never run after prolonged hard-interactive bursts.
2. Hard-interactive tasks waiting behind decode-related GIL convoys.
3. Progressive update visibility delayed by repeated non-critical timer competition.

Fairness rule:
- Hard-interactive remains top priority.
- Soft-interactive receives bounded completion window after interaction stops.
- Latency-sensitive background tasks receive minimum service budget once hard-interactive pressure drops.

---

## Low-End System Behavior Contract

For low-end profiles (e.g., i3-class + lower RAM tiers), expected behavior prioritization is:
1. Maintain responsive slice interaction first.
2. Degrade background throughput before interaction quality.
3. Prefer cancellation/coalescing over queue growth.
4. Keep memory growth bounded and recover quickly after bursts.

Validation must be scenario-driven using:
- viewer-only baseline
- viewer + progressive download
- viewer + download + filter settle
- rapid reversal + low-end profile simulation

---

## 1. Process Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  P1 — Main Process (NORMAL priority)                           │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ Qt Main │  │ DM Bridge│  │ ZetaBoost│  │ LW2D Pipeline  │  │
│  │ Thread  │  │ QThread  │  │ Workers  │  │ Thread Pool    │  │
│  │         │  │ (polls   │  │ (1-6     │  │ (4 decode +    │  │
│  │ UI +    │  │  Queue   │  │  threads,│  │  2-4 frame     │  │
│  │ Render  │  │  every   │  │  cond.   │  │  workers)      │  │
│  │         │  │  20ms)   │  │  var     │  │                │  │
│  │         │  │         │  │  sleep)  │  │                │  │
│  └────┬────┘  └────┬────┘  └────┬────┘  └───────┬────────┘  │
│       │            │            │                │            │
│  ═════╪════════════╪════════════╪════════════════╪════════    │
│       │      SINGLE GIL — all threads share this GIL         │
│  ═════╪════════════╪════════════╪════════════════╪════════    │
└───────┼────────────┼────────────┼────────────────┼────────────┘
        │            │            │                │
   ┌────▼────┐  ┌────▼─────┐  (gated)        (hardcoded)
   │ QTimers │  │ mp.Queue │
   │ 8+      │  │ maxsize  │
   │ active  │  │ =1000    │
   └─────────┘  └────┬─────┘
                     │
         ┌───────────▼──────────────┐
         │  P2 — Download Process   │
         │  (BELOW_NORMAL priority) │
         │  Own GIL ✓               │
         │  Socket I/O + DB writes  │
         │  SUSPENDED during scroll │
         └──────────────────────────┘

         ┌──────────────────────────┐
         │  P3 — Warmup Process     │
         │  (IDLE priority)         │
         │  Own GIL ✓               │
         │  SimpleITK load+filter   │
         │  Not used in FAST mode   │
         └──────────────────────────┘
```

### Process Isolation Assessment

| Process | GIL | Priority | Scroll-time behavior | Verdict |
|---------|-----|----------|---------------------|---------|
| P1 Main | Shared | Normal | Active (all rendering here) | **Bottleneck** — all subsystem threads compete for this GIL |
| P2 Download | Own | Below Normal | **Suspended** via NtSuspendProcess | ✅ Strong isolation |
| P3 Warmup | Own | Idle | Not used in FAST mode | ✅ N/A |

**P2 isolation is excellent.** The download subprocess has its own GIL and is frozen during scroll bursts. No contention.

**P1 is where all contention lives.** Every background thread in the main process (decode workers, ZetaBoost, DM bridge, progressive display) shares one GIL.

---

## 2. Thread Inventory During Peak Load

Scenario: User scrolling through a series while another series downloads progressively.

| # | Thread | Priority | GIL behavior | Active during scroll? |
|---|--------|----------|-------------|----------------------|
| 1 | **Qt Main** | Normal → HIGHEST during scroll | Needs GIL for pydicom decode, QImage, paint | **YES — critical path** |
| 2 | DM Bridge QThread | Normal | Polls mp.Queue (20ms), releases GIL during wait | Yes but minimal |
| 3-8 | ZetaBoost Workers (1-6) | IDLE (-15) | **SLEEPING on cv.wait()** — zero GIL cost | **No** — triple-gated during download |
| 9-12 | LW2D Decode Workers (4) | Normal | **pydicom.dcmread holds GIL 3-8ms** ⚠️ | **YES — prefetch continues** |
| 13-16 | LW2D Frame Workers (2-4) | Normal | numpy/cv2 release GIL, QImage brief hold | Yes |
| 17 | Progressive load thread | Normal | Brief GIL for signals | Intermittent (150ms timer) |
| 18 | GC re-enable timer thread | N/A | QTimer callback | No (suppressed) |

### Thread Count by Hardware Tier

| Hardware | Total threads in P1 | Effective core competition |
|----------|---------------------|---------------------------|
| i3 (4C/8T) | ~14 threads / 4 physical cores | **3.5 threads per core** ⚠️ |
| i5 (6C/12T) | ~14 threads / 6 physical cores | 2.3 threads per core |
| i9 (8C/16T) | ~14 threads / 8 physical cores | 1.75 threads per core |
| i9 (24C/32T) | ~14 threads / 24 physical cores | 0.6 threads per core ✅ |

On an i3, the ~14 threads are spread across 4 physical cores. Context switching overhead alone costs ~5% CPU. Combined with GIL serialization, effective parallelism drops to ~1.5 real cores of work.

---

## 3. GIL Contention Analysis

### GIL Hold Times per Operation

| Operation | GIL Held? | Duration | Frequency during scroll | Impact |
|-----------|-----------|----------|------------------------|--------|
| `pydicom.dcmread()` | **YES** ⚠️ | 3–8ms | Every cache miss (0-5/scroll) | **CRITICAL** — blocks main thread |
| numpy array indexing | Mostly released | 0.1–0.3ms | Every frame | Low |
| W/L LUT application | Released in C | ~0.3ms | Every frame | Low |
| cv2.GaussianBlur | Released in C++ | 2–4ms | Skipped during fast scroll | None during scroll |
| QImage constructor | YES | ~0.05ms | Every frame | Negligible |
| QWidget.update() | YES | ~0.01ms | Every frame | Negligible |
| ZetaBoost cv.wait() | **Released** | 2000ms sleep | Not during scroll | Zero cost |
| DB pool_lock acquire | YES | ~0.01ms | Rare during scroll | Negligible |
| mp.Queue.get(timeout) | **Released** | Up to 20ms wait | DM bridge polling | Releases GIL while waiting ✅ |

### The pydicom.dcmread GIL Convoy Problem

```
Timeline: Main thread + 4 decode workers on cache miss
═══════════════════════════════════════════════════════

Main:     [--wait GIL--][dcmread 5ms][render 1.5ms]
Worker1:  [dcmread 5ms][--wait GIL 15ms--]..........
Worker2:  [--wait GIL--][dcmread 5ms][--wait GIL--].
Worker3:  [--wait GIL--][--wait GIL--][dcmread 5ms].
Worker4:  [--wait GIL--][--wait GIL--][--wait GIL--]

Worst case: 5 × 8ms = 40ms total serialized GIL time
Main thread blocked: up to 32ms waiting for 4 workers
Frame deadline: 16ms (60 FPS) — MISSED by 2× ⚠️
```

**This only occurs on cache misses.** The LW2D prefetch system means most scroll events hit cache. But during progressive download (new files arriving), cache misses are frequent for newly-arrived slices.

### GIL Timeline: Single Scroll Event (Cache Hit)

```
Time:  0ms                    1.5ms              2ms
Main:  [set_slice → cache hit → LUT → QImage → paint]
       └── GIL held: ~0.3ms total (LUT + QImage)

Workers: idle (nothing to prefetch if cache warm)
Total frame: ~1.8ms ✅ (matches measured P50)
```

### GIL Timeline: Scroll Event During Progressive Download + Cache Miss

```
Time:  0          5          10         15         20ms
Main:  [wait][dcmread 5ms][LUT 0.3ms][paint 0.2ms]....
       └── blocked by Worker1's dcmread ──┘

Worker1: [dcmread 5ms][idle]
Worker2: [wait GIL][dcmread 5ms][idle]
Worker3: [wait GIL][wait GIL][dcmread 5ms]

DM Bridge: [Queue.get – GIL released, no contention]

Total main-thread frame: ~8-12ms
Still under 16ms deadline, but 5× slower than cache-hit path
```

---

## 4. ZetaBoost Gating — Why It's Not a Problem

ZetaBoost workers have triple gating that effectively removes them from contention:

```python
# Gate 1: Global download counter (with lock)
if _GLOBAL_DOWNLOAD_ACTIVE.value > 0:   # int counter, thread-safe
    cv.wait(timeout=2.0)                  # SLEEP — GIL released
    continue

# Gate 2: Per-instance download flag (bare bool, GIL-atomic)
if self._download_active:
    cv.wait(timeout=2.0)                  # SLEEP — GIL released
    continue

# Gate 3: Study completion flag
if not self._study_download_complete:
    cv.wait(timeout=2.0)                  # SLEEP — GIL released
    continue
```

**During download + scroll, ZetaBoost workers are dormant.** They sleep on condition variables which release the GIL entirely. They consume zero GIL time, zero CPU cycles, and zero memory bus bandwidth. This is correctly engineered.

---

## 5. Scroll-Time Throttling Mechanisms

During scroll bursts, several mechanisms reduce background interference:

| Mechanism | Target | Effect | Duration |
|-----------|--------|--------|----------|
| `NtSuspendProcess` | P2 (download) | Frozen — zero CPU | Until scroll stops + 200ms |
| `gc.disable()` | GC collector | No collection pauses | Until 2000ms after last render |
| `SetThreadPriority(IDLE)` | Background threads matching keywords | OS schedules less often | Until scroll stops |
| `SetThreadPriority(HIGHEST)` | Main viewer thread | OS priority boost | During scroll burst |
| `fast_interaction=True` | LW2D pipeline | Skips filters, uses LUT fast path | During scroll |
| CPU affinity mask | P2 (download) | Pinned to upper-half cores (≥4 core systems) | During scroll |

### What Is NOT Throttled During Scroll

| Thread | Why not throttled | Risk |
|--------|-------------------|------|
| **LW2D Decode Workers** | Thread names "LW2D-Decode-N" don't match throttle keywords | **They compete for GIL with main thread** ⚠️ |
| **LW2D Frame Workers** | Thread names "LW2D-Frame-N" don't match | Lower risk (numpy/cv2 release GIL) |
| DM Bridge QThread | "DM-QThread" doesn't match (no "download" in name) | Minimal — mostly sleeping on Queue.get() |

**The LW2D decode workers are intentionally not throttled** — they're warming the cache for upcoming scroll positions. This is architecturally correct: throttling them would cause more cache misses, making scrolling worse. But their `pydicom.dcmread` calls still compete for GIL on cache miss paths.

---

## 6. Resource Competition Model

### Competition Matrix (Who Competes With Whom)

|  | Main Thread | LW2D Decode | LW2D Frame | ZetaBoost | DM Bridge | Progressive |
|--|-------------|-------------|------------|-----------|-----------|-------------|
| **Main Thread** | — | **GIL** ⚠️ | GIL (brief) | None ✅ | None ✅ | GIL (brief) |
| **LW2D Decode** | **GIL** ⚠️ | **GIL** between workers | GIL (brief) | None ✅ | None ✅ | GIL (brief) |
| **LW2D Frame** | GIL (brief) | GIL (brief) | GIL (brief) | None ✅ | None ✅ | None |
| **ZetaBoost** | None ✅ | None ✅ | None ✅ | None ✅ | None ✅ | None ✅ |
| **DM Bridge** | None ✅ | None ✅ | None ✅ | None ✅ | — | None ✅ |
| **Progressive** | GIL (brief) | GIL (brief) | None | None ✅ | None ✅ | — |

**Key conflict: Main Thread ↔ LW2D Decode Workers.** Both need the GIL for `pydicom.dcmread`. All other combinations have minimal or zero contention.

### Shared Mutable State

| Resource | Protection | Threads accessing | Risk |
|----------|-----------|-------------------|------|
| `_pixel_cache` (OrderedDict) | GIL only — no explicit lock | Main + 4 decode workers | **Medium** — GIL is sufficient for dict ops, but OrderedDict eviction under concurrent access is fragile |
| `_frame_cache` (OrderedDict) | GIL only — no explicit lock | Main + 2-4 frame workers | Same as above |
| `_prefetch_pending` (set) | `_prefetch_lock` (Lock) | Main + workers | ✅ Properly locked |
| `_GLOBAL_DOWNLOAD_ACTIVE` | `_DL_ACTIVE_LOCK` (Lock) | DM Bridge + ZetaBoost | ✅ Properly locked |
| `ZetaBoost._cache` | `_cache_lock` (Lock) | Interactive + warmup + background lanes | ✅ Properly locked |
| `StateStore._studies` | `_lock` (Lock) | DM workers + UI observer + coordinator | ✅ Properly locked |
| `DB connection pool` | `_pool_lock` (Lock) | Any thread needing DB | ✅ Properly locked |

---

## 7. Hardware Adaptation Gaps

### What IS Adaptive

| Feature | Detection method | Tiers | Assessment |
|---------|-----------------|-------|------------|
| ZetaBoost cache budget | `psutil.virtual_memory().total` | 4 RAM tiers | ✅ Well-designed |
| ZetaBoost worker RAM guard | `psutil.virtual_memory().available` | 1200 MB threshold | ✅ Dynamic, checked every 3s |
| ITK thread count | `os.cpu_count()` | `min(cores-2, 8)` | ✅ Adaptive (Advanced mode only) |
| Lazy volume workers | `os.cpu_count()` | `min(4, max(2, cores//2))` | ✅ Adaptive (pydicom_2d only) |
| GPU vs Software OpenGL | PowerShell GPU probe | Binary | ✅ But only affects render mode |
| CPU affinity isolation | `os.cpu_count()` | ≥4 cores only | ✅ Appropriate |

### What Is NOT Adaptive (Gaps)

| Feature | Current value | What should happen | Impact |
|---------|--------------|-------------------|--------|
| **LW2D Decode Workers** | Hardcoded 4 | i3: 2, i5: 3, i9: 4-6 | i3 saturated, i9 underutilized |
| **LW2D Frame Workers** | Hardcoded 2-4 | Scale with cores | Same |
| **Decode gate** | Hardcoded 1 | i9 could run 2-3 concurrent | Bottleneck on high-end |
| **Prefetch depth** | Fixed | Could be deeper on fast SSD + many cores | Missed optimization |
| **Download concurrency** | `MAX_CONCURRENT_STUDIES = 1` | Could be 2-3 on high-end systems | Lower throughput |
| **GPU → compute path** | No effect | Could offload W/L to GPU shader | Missed GPU acceleration |
| **CPU generation detection** | None | i3 vs i9 have different IPC, cache | Same core count ≠ same performance |
| **SSD vs HDD detection** | None | pydicom.dcmread latency: SSD ~3ms, HDD ~8-15ms | Would affect prefetch strategy |

### Hardware Tier Impact (Estimated)

| Scenario | i3 (4C/8T, 8GB) | i5 (6C/12T, 16GB) | i9 (8C/16T, 32GB) |
|----------|-----------------|-------------------|-------------------|
| Scroll P50 (cache hit) | ~2ms | ~1.8ms | ~1.5ms |
| Scroll P50 (cache miss) | ~15ms ⚠️ | ~10ms | ~6ms |
| Scroll during DL + cache miss | **~25ms** ⚠️⚠️ | ~15ms | ~8ms |
| Threads competing for 1 GIL | 14 on 4 cores | 14 on 6 cores | 14 on 8 cores |
| ZetaBoost cache budget | 400 MB | 800 MB | 2 GB |
| Effective parallelism | ~1.5 cores | ~3 cores | ~5 cores |

The i3 case is where "all race and all fail" — 14 threads on 4 cores, pydicom GIL convoy blocking the main thread, and no hardware-specific tuning.

---

## 8. QTimer Inventory and Interaction

Active QTimers during download + viewing:

| Timer | Interval | Callback | GIL needed? | Interaction risk |
|-------|----------|----------|-------------|------------------|
| DM Progress Batch | 100ms | Emit batched progress signals | Brief | Low — signals only |
| Viewer Progress Debounce | 100ms | `on_series_images_progress` | Brief | Low |
| Progressive Grow | 150ms | `_grow_progressive_fast` → `loader.grow()` | Medium (file scan) | Medium — disk I/O on main thread |
| GC Re-enable | 2000ms | `gc.enable()` | Brief | Low |
| Scroll-stop | 200ms | Resume P2, restore thread priorities | Brief | Low |
| Coordinator Recheck | 50ms | Check pending downloads | Brief | Low |
| Coordinator Retry | 200ms | Poll for worker start | Brief | Low |
| Completion Sweep | 3000ms | Verify disk files | Medium (disk I/O) | Low — infrequent |
| Resource Monitor | 2000ms | Log CPU %, memory | Brief | Negligible |
| Disk Count Cache TTL | 1000ms | Refresh os.scandir cache | Medium | Low |

**Timer collision risk:** The 100ms progress debounce and 150ms grow timer can fire within the same 16ms frame as a scroll event. The grow timer does `os.scandir` which is a kernel call (GIL released during syscall, but briefly held before/after). This is normally <1ms but adds to cumulative main-thread work.

---

## 9. Signal Flow Under Load

```
Download subprocess                    Main process (P1)
═══════════════════                    ═══════════════════

DM Worker writes chunk to disk
  │
  ├─ mp.Queue.put(progress)  ─────►  DM Bridge QThread
  │                                    ├─ Queue.get(timeout=20ms)
  │                                    │   GIL released during wait ✅
  │                                    ├─ Batches signals (100ms timer)
  │                                    └─ seriesProgressUpdated.emit
  │                                         │
  │                                    ┌────▼────────────────────────┐
  │                                    │  Main Thread (Qt event loop)│
  │                                    │                             │
  │                                    │  on_series_images_progress  │
  │                                    │  (100ms per-series debounce)│
  │                                    │         │                   │
  │                                    │  _grow_progressive_fast     │
  │                                    │  (150ms timer)              │
  │                                    │    ├─ os.scandir (syscall)  │
  │                                    │    ├─ loader.grow()         │
  │                                    │    ├─ slider update         │
  │                                    │    └─ metadata refresh      │
  │                                    │         │                   │
  │                                    │  Meanwhile, user scrolling: │
  │                                    │    ├─ wheelEvent            │
  │                                    │    ├─ set_slice (1.8ms)     │
  │                                    │    └─ paint (0.5ms)         │
  │                                    │                             │
  │                                    │  ⚠️ Both scroll AND grow   │
  │                                    │  share the same main thread │
  │                                    └─────────────────────────────┘
  │
  │         SIMULTANEOUSLY:
  │
  │     LW2D Decode Workers (4 threads)
  │       ├─ Worker 0: pydicom.dcmread ← GIL held 3-8ms
  │       ├─ Worker 1: pydicom.dcmread ← GIL held 3-8ms
  │       ├─ Worker 2: waiting for GIL
  │       └─ Worker 3: waiting for GIL
  │
  │     ZetaBoost Workers (dormant)
  │       └─ cv.wait() ← GIL released, zero cost ✅
```

---

## 10. Standards Assessment

### Python Concurrency Best Practices vs Current Implementation

| Practice | Standard | Current | Gap |
|----------|----------|---------|-----|
| GIL-bound CPU work → subprocess | Move GIL-heavy CPU work to `multiprocessing` | pydicom.dcmread runs in P1 threads | **Major gap** — decode should be in subprocess |
| Thread pools sized to CPU cores | `ThreadPoolExecutor(max_workers=cpu_count)` typical | LW2D hardcoded to 4 | **Gap** — no adaptation |
| Backpressure between producer/consumer | Bounded queues, semaphores | LW2D `_request_queue` sized 4×slices | **Partial** — queue sized but no feedback loop |
| I/O work → async or threads | Use threads for I/O-bound work | ✅ Correct — socket/DB in threads | OK |
| CPU work → process pool | `ProcessPoolExecutor` for CPU-bound | Not used — all CPU in P1 threads | **Gap** |
| Priority inversion prevention | Don't hold shared locks in low-priority threads | ✅ ZetaBoost uses cv.wait, no lock hold | OK |
| Resource monitoring + adaptation | Adjust concurrency based on load | ZetaBoost has RAM guard; LW2D has none | **Partial gap** |

### Qt Concurrency Best Practices

| Practice | Standard | Current | Gap |
|----------|----------|---------|-----|
| Never block event loop >16ms | All heavy work in threads/subprocess | ✅ Most heavy work offloaded | OK (but grow timer does disk I/O) |
| Signal/slot for cross-thread | Qt signals with AutoConnection | ✅ Correctly used throughout | OK |
| QTimer callbacks guard exceptions | Wrapper+impl pattern | ✅ Applied to critical timers | OK (H5b/H5c pattern) |
| Thread affinity respected | Don't access QWidget from threads | ✅ QTimer.singleShot(0) for marshal | OK |

### Medical Imaging Concurrency Patterns

| Pattern | Industry practice | Current | Gap |
|---------|------------------|---------|-----|
| Decode pipeline isolation | DICOM decode in dedicated process pool | In-process threads only | **Gap** |
| Adaptive quality degradation | Reduce quality under load (lower res, skip filters) | `fast_interaction` flag during scroll | **Partial** — only scroll path |
| Prefetch prediction | Predict scroll direction, pre-decode ahead | LW2D prefetches ±N slices | ✅ Implemented |
| Resource budget per subsystem | Fixed CPU/memory budget per module | ZetaBoost has RAM budget; others don't | **Partial gap** |

---

## 11. Worst-Case Scenario Analysis

### Scenario: i3 user scrolls through CT during active progressive download

```
Hardware: 4 cores / 8 hyperthreads, 8 GB RAM, SSD
Active threads in P1: ~14
ZetaBoost: dormant (gated) → 0 threads active
Effective contending threads: ~8 (main + 4 decode + 2 frame + DM bridge)

Timeline for ONE scroll frame:

T=0ms:    wheelEvent fires
T=0.1ms:  gc.disable(), thread throttle, P2 suspended
T=0.2ms:  set_slice() calls get_frame(fast_interaction=True)
          Cache MISS (new progressive slice just arrived)
T=0.3ms:  Synchronous pydicom.dcmread on main thread
          GIL acquired by main thread
T=0.3ms:  Meanwhile, Worker1 also doing dcmread — blocked on GIL
T=0.3ms:  Worker2 also doing dcmread — blocked on GIL
T=5ms:    Main thread dcmread completes, GIL released
T=5ms:    Worker1 acquires GIL, starts its dcmread
T=5.1ms:  Main thread wants GIL back for LUT+render — must wait
T=10ms:   Worker1 dcmread done, main thread gets GIL
T=10.1ms: LUT application (0.3ms, numpy releases GIL)
T=10.5ms: QImage creation (0.05ms)
T=10.6ms: paint() (0.5ms)
T=11.1ms: Frame complete

Result: 11.1ms per frame → 90 FPS (acceptable)
But: 2 more scroll events queued → 33ms total → stutter visible
```

### Scenario: Same i3 user, but 5 consecutive cache misses (fast scrolling into unseen area)

```
T=0ms:    First scroll event, cache miss
T=11ms:   Frame 1 done (as above)
T=11ms:   Second scroll event, cache miss
T=22ms:   Frame 2 done
T=22ms:   Third scroll event queued
...
T=55ms:   Frame 5 done

5 frames × 11ms = 55ms → only 18 FPS → visible stutter ⚠️
User perceives "lag when scrolling into new download area"
```

This matches the reported symptom: "separately fast, together slow."

---

## 12. Findings Summary

### Critical (Must Fix)

| ID | Finding | Impact | Root cause |
|----|---------|--------|------------|
| **C1** | pydicom.dcmread holds GIL 3–8ms in P1 threads | Main thread blocked during decode worker GIL convoy | GIL-bound CPU work in threads instead of subprocess |
| **C2** | LW2D decode worker count hardcoded (4) | i3 saturated, i9 underutilized | No CPU detection for thread pool sizing |
| **C3** | No cross-subsystem load signal | Subsystems can't throttle based on overall system load | Each operates independently |

### Important (Should Fix)

| ID | Finding | Impact | Root cause |
|----|---------|--------|------------|
| **I1** | No i3/i5/i9 classification | Same thread counts regardless of CPU capability | Only core count detected, not performance class |
| **I2** | GPU detection doesn't influence compute | Missed GPU acceleration for W/L, filters | GPU probe only affects OpenGL mode |
| **I3** | `DynamicThreadOptimizer` exists but unused | Working adaptive tuning code going to waste | Never imported in production code |
| **I4** | Progressive grow timer does disk I/O on main thread | `os.scandir` + metadata refresh in Qt event loop | Could be offloaded to background thread |
| **I5** | `_pixel_cache` / `_frame_cache` OrderedDict no lock | Relies on GIL for dict operations | Works under CPython but fragile |
| **I6** | Decode gate hardcoded to 1 | i9 could safely run 2-3 concurrent decodes | H12 safety fix never relaxed for capable hardware |

### Low Priority (Nice to Have)

| ID | Finding | Impact |
|----|---------|--------|
| **L1** | No SSD vs HDD detection | Prefetch strategy should differ |
| **L2** | `HomePanelWidget.thread_pool` unbounded | Up to ~36 threads on i9 (usually benign) |
| **L3** | No memory-bus bandwidth monitoring | Can't detect when DRAM becomes bottleneck |

---

## 13. Recommendations

### R1: Move pydicom.dcmread to ProcessPoolExecutor (Addresses C1)

**Problem:** pydicom.dcmread holds the GIL for 3–8ms, blocking the main thread.

**Solution:** Replace LW2D's `ThreadPoolExecutor` for decode with a `concurrent.futures.ProcessPoolExecutor`:

```
Current:
  Main Thread ──GIL──► ThreadPoolExecutor (4 workers)
                        Each runs pydicom.dcmread (holds GIL)

Proposed:
  Main Thread ──────► ProcessPoolExecutor (N workers)
                       Each has OWN GIL
                       pydicom.dcmread never blocks main thread
                       Results sent via IPC (pickle serialization)
```

**Trade-offs:**
- ✅ Eliminates GIL convoy entirely
- ⚠️ IPC overhead: ~0.5–1ms per slice for pickle/unpickle of numpy array
- ⚠️ Memory: each subprocess has its own memory space (~50–100 MB base)
- ⚠️ Startup cost: ~200ms to spawn each process (amortize by keeping pool warm)

**Recommended worker count:** `max(2, min(4, cpu_count // 2))` — same formula as pydicom_lazy_volume.

### R2: Adaptive Thread Pool Sizing (Addresses C2, I1)

**Solution:** Detect hardware tier at startup and size all thread pools accordingly:

```python
import os, psutil

def get_hardware_profile():
    cores = os.cpu_count() or 4
    ram_gb = psutil.virtual_memory().total / (1024**3)
    
    if cores >= 16 and ram_gb >= 24:
        return 'high'      # i9 / workstation
    elif cores >= 8 and ram_gb >= 12:
        return 'medium'    # i5-i7 / mid-range
    else:
        return 'low'       # i3 / budget

PROFILES = {
    'high':   {'decode_workers': 6, 'frame_workers': 4, 'decode_gate': 3, 'prefetch_depth': 20},
    'medium': {'decode_workers': 4, 'frame_workers': 3, 'decode_gate': 2, 'prefetch_depth': 12},
    'low':    {'decode_workers': 2, 'frame_workers': 2, 'decode_gate': 1, 'prefetch_depth': 6},
}
```

**Files to change:**
- `modules/viewer/fast/lightweight_2d_pipeline.py` — PipelineConfig factory
- `modules/viewer/fast/_decode_guard.py` — relaxed gate for high-end
- New file: `modules/viewer/fast/hardware_profile.py`

### R3: Cross-Subsystem Load Signal (Addresses C3)

**Solution:** Introduce a lightweight shared load indicator:

```python
# modules/concurrency/load_signal.py
import threading, time

class SystemLoadSignal:
    """Shared, low-overhead load indicator for all subsystems."""
    
    _lock = threading.Lock()
    _scroll_active = False
    _download_active = False
    _decode_pressure = 0  # number of pending decode futures
    
    @classmethod
    def is_scroll_active(cls) -> bool:
        return cls._scroll_active  # GIL-atomic bool read, no lock needed
    
    @classmethod
    def get_decode_pressure(cls) -> int:
        return cls._decode_pressure  # GIL-atomic int read
```

Subsystems would check this before starting work:
- LW2D: reduce prefetch batch if `decode_pressure > threshold`
- Progressive grow: delay timer restart if `is_scroll_active`
- DM bridge: reduce signal frequency if `is_scroll_active`

### R4: Progressive Grow Offload (Addresses I4)

Move `os.scandir` and metadata refresh in `_grow_progressive_fast` to a background thread, marshaling results back via `QTimer.singleShot(0, callback)`:

```python
# Instead of:
def _grow_progressive_fast(self):
    count = os.scandir(path)  # blocks main thread ~1ms
    ...

# Do:
def _grow_progressive_fast(self):
    threading.Thread(target=self._grow_progressive_bg, daemon=True).start()

def _grow_progressive_bg(self):
    count = os.scandir(path)  # in background
    # ... compute new slices ...
    QTimer.singleShot(0, lambda: self._grow_progressive_apply(results))
```

### R5: Activate DynamicThreadOptimizer (Addresses I3)

The existing `DynamicThreadOptimizer` in `modules/module_system/dynamic_thread_optimizer.py` already implements throughput-based thread tuning (1–8 threads). Wire it to the LW2D decode pool for runtime adaptation.

---

## 14. Priority Matrix

| Recommendation | Effort | Impact | Priority |
|---------------|--------|--------|----------|
| R2: Adaptive thread pool sizing | Small | Medium | **Do first** — easy, immediate benefit on i3 |
| R3: Cross-subsystem load signal | Small | Medium | **Do second** — enables smarter throttling |
| R4: Progressive grow offload | Small | Low-Medium | **Do third** — reduces main-thread jitter |
| R1: ProcessPoolExecutor for decode | Large | High | **Do fourth** — biggest payoff but most risk |
| R5: Activate DynamicThreadOptimizer | Medium | Medium | **Do fifth** — leverage existing code |

### Recommended Implementation Order

**Phase 1 (Quick wins, ~1-2 days):**
- R2: Hardware profile detection + adaptive worker counts
- R4: Offload grow timer disk I/O

**Phase 2 (Medium effort, ~2-3 days):**
- R3: SystemLoadSignal shared indicator
- R5: Wire DynamicThreadOptimizer to LW2D

**Phase 3 (Major architecture, ~5-7 days):**
- R1: ProcessPoolExecutor for pydicom.dcmread (most impactful but requires careful IPC design)

---

## Appendix A: Timing Constants Reference

| Constant | Value | Location | Purpose |
|----------|-------|----------|---------|
| DM progress batch | 100ms | download_process_worker.py | Batch signals to reduce overhead |
| Viewer progress debounce | 100ms | patient_widget_viewer_controller.py | Per-series throttle |
| Progressive grow timer | 150ms | patient_widget_viewer_controller.py | Batch growth cadence |
| Coordinator queue recheck | 50ms | series_intent_coordinator.py | Priority preemption latency |
| Coordinator retry poll | 200ms | series_intent_coordinator.py | Worker start retry |
| Queue poll interval | 20ms | download_process_worker.py | mp.Queue check frequency |
| GC re-enable | 2000ms | _vw_scroll.py | After last render event |
| Scroll-stop timer | 200ms | _vw_scroll.py | Resume background threads |
| ZetaBoost cv.wait | 2000ms | _zb_workers.py | Worker sleep timeout |
| RAM guard check | 3000ms | _zb_workers.py | Memory availability |
| Disk count cache TTL | 1000ms | patient_widget_viewer_controller.py | os.scandir result cache |
| Completion sweep | 3000ms | patient_widget_viewer_controller.py | Final file verification |
| Completion verify retry | 500ms × 3 | patient_widget_viewer_controller.py | OS flush wait |
| DM notify cooldown | 500ms | patient_widget_viewer_controller.py | Per-series dedup |
| Worker completion → next | 0ms | series_intent_coordinator.py | Immediate next worker |
| Observer refresh delay | 0ms | observers.py | Immediate UI update |

## Appendix B: Thread Name → Priority Map

| Thread name pattern | Base priority | Scroll priority | Matched by throttle? |
|---------------------|-------------|-----------------|---------------------|
| MainThread | Normal | HIGHEST (+2) | N/A (boosted) |
| DM-QThread | Normal | Normal | No (no keyword match) |
| LW2D-Decode-N | Normal | Normal | **No** (intentional) |
| LW2D-Frame-N | Normal | Normal | **No** (intentional) |
| ZetaBoost-Worker-N | IDLE (-15) | IDLE | Yes (dormant anyway) |
| SliceBooster | IDLE (-15) | IDLE | Yes |
| *download* | Normal | IDLE | Yes |
| *filter* | Normal | IDLE | Yes |
| *warmup* | Normal | IDLE | Yes |
| *network* | Normal | IDLE | Yes |
| *socket* | Normal | IDLE | Yes |

## Appendix C: Existing `DynamicThreadOptimizer` (Unused)

Location: `modules/module_system/dynamic_thread_optimizer.py`

```
Features:
- Throughput-based thread tuning (1-8 threads)
- 5-second measurement windows
- Gradient-based scaling decisions
- Min/max bounds with configurable step size
- Thread-safe counter for throughput tracking

Status: Exists in codebase, no production imports found.
Could be wired to LW2D decode pool for automatic adaptation.
```
