# Workstation Loops & Cycles

> **Version:** v2.2.3.4.0 | **Updated:** 2026-03-10

## Purpose

A DICOM workstation is fundamentally a **loop machine**. It repeatedly opens patients, downloads series, displays images, runs modules, and closes — thousands of times per session. Each of these loops must be **independently stable** and **composable** within larger loops. This document defines every loop, its stability guarantees, and the patterns that ensure reliable repetition.

---

## Loop Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│ SESSION LOOP (hours)                                         │
│   Login → Work → Logout                                     │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ PATIENT LOOP (minutes)                                │   │
│  │   Open patient → View/Download → Close patient        │   │
│  │                                                        │   │
│  │  ┌──────────────────────────────────────────────┐    │   │
│  │  │ SERIES LOOP (seconds)                         │    │   │
│  │  │   Select series → Load → View → Next series   │    │   │
│  │  │                                                │    │   │
│  │  │  ┌────────────────────────────────────┐      │    │   │
│  │  │  │ SCROLL LOOP (milliseconds)          │      │    │   │
│  │  │  │   wheelEvent → set_slice → render   │      │    │   │
│  │  │  │   (60 Hz target, <16ms/frame)       │      │    │   │
│  │  │  └────────────────────────────────────┘      │    │   │
│  │  └──────────────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ DOWNLOAD LOOP (parallel)                              │   │
│  │   Queue study → Fetch metadata → Download series      │   │
│  │   → Save to DB/disk → Signal completion               │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ CACHE LOOP (background, continuous)                   │   │
│  │   Prefetch → Store L1/L2 → Evict expired → Repeat    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ DB MAINTENANCE LOOP (per-operation)                   │   │
│  │   Acquire connection → Execute → Return to pool       │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Loop Definitions

### 1. Session Loop

**Frequency:** Once per application launch (hours-long)

```
START: Login (auth + socket connect)
  │
  ├─ Initialize infrastructure
  │   ├─ Database pool ready
  │   ├─ Socket service connected
  │   ├─ Module system ready
  │   └─ UI fully loaded
  │
  ├─ REPEAT: Patient loops + Download loops + Module loops
  │
  └─ END: Logout / close
      ├─ Stop all background workers
      ├─ Cleanup all resources
      └─ Persist essential state (DB preserved, UI state cleared)
```

**Stability guarantee:**
- All resources created during session must be cleaned up on exit
- No resource may accumulate across the session without bound
- Memory usage must be stable (verified: 0 MB drift over 50 cycles)

---

### 2. Patient Loop (Open/Close Cycle)

**Frequency:** Every few minutes (100-500+ per session)

```
OPEN:
  ├─ Create PatientWidget tab
  ├─ Allocate VTK render windows
  ├─ Create thumbnail manager
  ├─ Start ZetaBoost engine instance
  └─ Wire signal connections

USE:
  ├─ Series loops (scroll, view, measure)
  ├─ Module activations (MPR, AI, etc.)
  └─ ZetaBoost prefetch (background)

CLOSE:
  ├─ Stop ZetaBoost engine
  ├─ Release VTK render windows
  ├─ Clear L1 cache for this study
  ├─ Shutdown thread executors
  ├─ Disconnect signals
  └─ Destroy widget (Qt cascade)
```

**Stability guarantee:**
- After closing a patient tab, ALL resources allocated for that patient must be freed
- No VTK objects, timers, threads, or cache entries may survive tab closure
- Memory after close must return to pre-open baseline (±1MB tolerance)

**What gets cleaned:**
| Resource | Cleanup method | Verified |
|----------|---------------|----------|
| VTK viewers | `cleanup_image_viewer()` | Yes |
| Thread pools | `executor.shutdown(wait=False)` | Needs fix |
| QTimers | Qt parent-child cascade | Yes |
| ZetaBoost L1 cache | `engine.clear()` | Yes |
| Thumbnail cache entries | TTL expiry (300s) | Yes |
| DB connections | Return to pool | Yes |

---

### 3. Series Loop (Load/View Cycle)

**Frequency:** Multiple times per patient (10-50+ per patient)

```
SELECT: User clicks series thumbnail
  │
  ├─ LOAD:
  │   ├─ DB query: get series instances
  │   ├─ Disk read: DICOM files
  │   ├─ ITK filters: image processing
  │   └─ VTK convert: display-ready volume
  │
  ├─ DISPLAY:
  │   ├─ Set VTK image data
  │   ├─ Configure window/level
  │   ├─ Reset camera
  │   └─ Initial render
  │
  ├─ INTERACT:
  │   ├─ Scroll loops (see below)
  │   ├─ Zoom, pan, rotate
  │   ├─ Measurements, annotations
  │   └─ Reference line sync
  │
  └─ UNLOAD (when switching to another series):
      ├─ Previous VTK data dereferences
      └─ Python GC handles actual cleanup
```

**Stability guarantee:**
- Each series load must complete or fail cleanly (no partial state)
- Loading a new series must not leak references to the previous series
- Error during load → fallback UI state (not crash)

---

### 4. Scroll Loop (Render Cycle)

**Frequency:** Continuous during scroll (30-60 Hz, milliseconds)

```
wheelEvent fired
  │
  ├─ GC disabled (prevent collection pause)
  ├─ _in_wheel_scroll = True
  │
  ├─ COALESCE (adaptive throttle):
  │   └─ set_slice(new_index)
  │       ├─ Update VTK slice
  │       ├─ Skip expensive operations (camera save, interactor update)
  │       ├─ Throttle reference line sync (100ms)
  │       └─ Render frame
  │
  ├─ REFERENCE LINES (round-robin):
  │   └─ Paint ONE target viewer per tick
  │
  └─ IDLE DETECTED (2000ms no wheel):
      ├─ _in_wheel_scroll = False
      ├─ GC re-enabled
      ├─ Full reference line update
      └─ Camera state saved
```

**Stability guarantee:**
- GC is ALWAYS re-enabled after scroll stops (2000ms timer)
- No per-frame allocations during scroll (reuse existing objects)
- No blocking operations in the scroll path
- Reference line updates are throttled (never N×20ms per tick)

---

### 5. Download Loop

**Frequency:** Per study opened (runs in parallel with viewing)

```
QUEUE: Study download requested
  │
  ├─ VALIDATE: Rule engine checks permissions, disk space
  │
  ├─ PREPARE:
  │   ├─ Fetch metadata (gRPC)
  │   ├─ Create DB records
  │   └─ Notify global download counter (blocks ZetaBoost warmup)
  │
  ├─ DOWNLOAD (subprocess, own GIL):
  │   ├─ Per-series loop:
  │   │   ├─ Download DICOM files via gRPC stream
  │   │   ├─ Save to disk
  │   │   ├─ Insert instance records to DB
  │   │   └─ Progress signal → UI
  │   └─ All series complete
  │
  └─ COMPLETE:
      ├─ Update download state → COMPLETED
      ├─ Decrement global download counter (unblock ZetaBoost)
      └─ Signal UI → 100%
```

**Stability guarantee:**
- Download state persists across app restart (DB-backed)
- Subprocess isolation: cannot crash the viewer
- Global counter prevents CPU contention with warmup
- Network errors → retry with exponential backoff (3 attempts)

---

### 6. Cache Loop (Background)

**Frequency:** Continuous background operation

```
ZetaBoost Warmup (IDLE priority threads):
  │
  ├─ CHECK: Any download active?
  │   ├─ Yes → Sleep 2s, retry
  │   └─ No → Continue
  │
  ├─ PREFETCH:
  │   ├─ Select next series (adjacent to current view)
  │   ├─ Load from disk
  │   ├─ Apply ITK filters (max_itk_threads=1)
  │   ├─ Store in L1 cache (memory)
  │   └─ Update L2 manifest (disk)
  │
  └─ EVICT (if memory pressure):
      ├─ LRU eviction (unpinned entries first)
      └─ Pin active series (prevent eviction during viewing)

Thumbnail Cache:
  ├─ Generate thumbnails on demand
  ├─ Store with 300s TTL
  ├─ Background cleanup every 60s
  └─ Remove expired entries
```

**Stability guarantee:**
- Cache size is bounded (LRU eviction + TTL)
- IDLE priority prevents CPU contention with viewer
- max_itk_threads=1 prevents memory-bus contention
- Cleanup thread stops on app shutdown

---

### 7. Database Connection Loop

**Frequency:** Every DB operation (hundreds per minute)

```
ACQUIRE:
  ├─ Lock pool (brief)
  ├─ Reusable connection available?
  │   ├─ Yes → Validate (SELECT 1) → Return
  │   └─ No → Create new connection (WAL mode, DEFERRED)
  └─ Unlock pool

USE:
  └─ Execute query/update within context manager

RELEASE:
  └─ Return connection to pool (automatic via __exit__)
```

**Stability guarantee:**
- Max 5 connections per thread (bounded pool)
- Reuse validation catches stale connections
- Context manager guarantees return-to-pool
- WAL mode prevents reader/writer blocking
- Pool cleanup on app shutdown

---

## Parallel Loop Interaction

These loops run concurrently and must not interfere:

```
┌─────────────────┐         ┌─────────────────┐
│ VIEWER LOOP     │         │ DOWNLOAD LOOP   │
│ (main process)  │         │ (subprocess)    │
│                 │         │                 │
│ scroll → render │  ───X──▶│ gRPC → disk     │
│ 60 Hz, <16ms   │  no     │ own GIL         │
│                 │  block  │                 │
└────────┬────────┘         └────────┬────────┘
         │                           │
         │ reads                     │ writes
         ▼                           ▼
    ┌─────────────────────────────────────┐
    │ DATABASE (WAL mode)                  │
    │ concurrent read + write              │
    │ no blocking                          │
    └─────────────────────────────────────┘
```

### Isolation Guarantees

| Loop A | Loop B | Isolation Mechanism |
|--------|--------|---------------------|
| Viewer scroll | Download | Separate process (own GIL) |
| Viewer scroll | ZetaBoost warmup | IDLE priority + max_itk_threads=1 |
| Viewer scroll | GC | GC disabled during scroll bursts |
| Viewer scroll | Reference lines | Round-robin (1 target/tick) |
| Download | ZetaBoost warmup | Global counter blocks warmup |
| DB reads | DB writes | WAL mode (concurrent) |
| Cache eviction | Active viewing | Pin/unpin prevents active eviction |

---

## Failure Modes & Recovery

| Loop | Failure Mode | Recovery | Max Impact |
|------|-------------|----------|------------|
| Patient open | VTK init fails | Show error tab, don't crash | Single patient |
| Series load | ITK filter error | Fallback to unfiltered | Single series |
| Scroll | GC not re-enabled | 2000ms timer forces re-enable | Temporary GC delay |
| Download | Network timeout | Retry 3× with backoff | Single download delayed |
| Download | Subprocess crash | Error state in UI, study can retry | Single download |
| Cache fill | Disk full | Stop caching, log warning | No prefetch |
| DB operation | Connection failure | New connection from pool | Single operation |
| Session | Main thread freeze | QTimer watchdogs detect | Full UI (rare) |

---

## Validation: 1000-Cycle Test

Validated in v2.2.3.4.0 (see `HIGH_FREQUENCY_LOOP_OPTIMIZATION.md`):

```
Test: Select Study → Download → View → Send → Repeat (1000 times)

Results:
  ✅ DB connection pool: 0 leaked connections
  ✅ Download state: 0 accumulated entries
  ✅ Reception cache: bounded (TTL cleanup)
  ✅ File manager cache: bounded (TTL cleanup)
  ✅ Memory stability: 0 MB drift over 50 cycles
```
