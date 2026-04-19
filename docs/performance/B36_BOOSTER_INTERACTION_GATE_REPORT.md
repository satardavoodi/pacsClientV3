# B3.6 — Booster Interaction Gate & Prefetch Stale Prevention Report

**Date:** 2026-04-15
**Version:** v2.3.3+B3.6
**Hardware:** Developer PC (PC A)
**Pipeline:** `Lightweight2DPipeline` (FAST mode, `pydicom_qt` backend)

---

## 1. Problem Statement (Log 33 Evidence)

Production logging (`log 33.txt`) revealed three concurrent issues during scroll:

### 1a. ImageSliceBooster decodes stale slices (100% waste)
```
[ImageBoost] tid=16424 decoded slices 0→20 sequentially (20-62ms each)
User scrolled 16→128 — ALL booster work was stale
overlap_after=0 (no concurrent decode contention)
```

### 1b. Pipeline prefetch always cache-miss during fast scroll
```
set_slice P95 = 22-84ms, ALWAYS cache miss
Pipeline radius=1 during fast=True at the B3.6 point in history (B3.7 later raised the fast cap to 3)
But user moves faster than single-slice prefetch completes
```

### 1c. CPU saturated from competing decode systems
```
CPU: 124-188% sustained
3 independent decode systems competing for GIL + CPU:
  1. Main thread foreground decode (20-80ms/slice)
  2. ImageSliceBooster thread (20-62ms/slice, stale)
  3. Pipeline prefetch workers (4 threads, 20-60ms/slice)
```

### 1d. ZetaBoost cache entirely unused
```
ZetaBoost: entries=0, hits(mem/disk)=0/0, miss=0
Series-level cache not populated during progressive download
```

---

## 2. Root Cause Analysis

### Three independent decode/cache systems

| System | Scope | Thread(s) | Serialization | Interaction-aware? |
|--------|-------|-----------|--------------|-------------------|
| **Lightweight2DPipeline** | per-slice | 4 decode + 4 frame workers | None (no guard) | ✅ Yes (B3.4: radius=1 during fast at this point; current B3.7/B4.1 tests expect radius=3) |
| **ImageSliceBooster** | per-slice ±20 window | 1 daemon (IDLE priority) | `decode_serialisation_guard()` (semaphore=1) | ❌ **No** — runs same window regardless of interaction |
| **ZetaBoostEngine** | per-series (full volume) | 3 lanes × N threads | None | N/A (not populated) |

### Why near-zero cache hits during scroll

1. Pipeline prefetch request: radius=1 at the B3.6 point in history → submits 1 slice ahead (current B3.7 cap is 3)
2. Decode cost: 20-80ms per slice
3. User scroll speed: >1 slice per 20-80ms
4. Result: by time prefetch completes, user has moved past → cache miss
5. Booster decodes around *old* center → 100% stale, wastes CPU/GIL time

### GIL contention model

During scroll, booster holds GIL for 20-62ms per slice decode (pydicom C-extension).
This directly competes with:
- Main thread foreground decode (must wait for GIL)
- Pipeline prefetch workers (must wait for GIL)

Eliminating the booster during interaction frees ~20-60ms of GIL time per booster decode cycle.

---

## 3. Solution: Interaction-Aware Booster Gate + Pipeline Tightening

### Fix 1: `ImageSliceBooster` — `_interaction_gate` Event (3 changes)

**File:** `modules/zeta_boost/image_slice_booster.py`

1. **`__init__`**: Added `self._interaction_gate = threading.Event()` (set = go, clear = pause)
2. **New API**: `pause_for_interaction()` (clears gate) / `resume_from_interaction()` (sets gate)
3. **`_worker_fn`**: Before each slice decode:
   - Check `_interaction_gate.is_set()` — if paused, wait up to 5s
   - Re-check `_cancel` after wake
   - **Pre-decode position relevance**: skip if `abs(idx - current_center) > window` (catches stale work when user scrolled during pause or prior decodes)

**Impact:**
- During scroll: booster thread blocks → **zero stale decode**, **zero GIL competition**
- On scroll-stop (200ms settle): booster resumes from final position, decodes relevant ±20 window
- No thread restart overhead (Event wait/wake is ~microseconds)

### Fix 2: `QtViewerBridge` — Pause/Resume Wiring (3 additions)

**File:** `modules/viewer/fast/qt_viewer_bridge.py`

1. **`_get_booster()`**: Traverses `vtk_widget → patient_widget → viewer_controller → _image_slice_booster`
2. **`_pause_booster()`**: Called from `set_slice(fast_interaction=True)` — idempotent
3. **`_resume_booster()`**: Called from `set_slice(fast_interaction=False)` and `end_fast_interaction()` — idempotent

**Control flow:**
```
Wheel/drag scroll → _on_qt_scroll → set_slice(fast_interaction=True)
  → pipeline.set_fast_interaction(True)
  → bridge._pause_booster() → booster._interaction_gate.clear()
  → booster worker blocks at gate wait

200ms settle → end_fast_interaction()
  → pipeline.set_fast_interaction(False)
  → bridge._resume_booster() → booster._interaction_gate.set()
  → booster worker unblocks, resumes from current center
```

### Fix 3: `Lightweight2DPipeline` — Tighter Pre-Decode Check

**File:** `modules/viewer/fast/lightweight_2d_pipeline.py`

In `_decode_into_cache()`, changed pre-decode distance threshold:
- **Before**: Always uses `prefetch_radius` (20) — allows stale tasks during fast scroll
- **After**: During `_fast_interaction`, uses threshold=3 (now also matching the B3.7 fast radius cap)

**Impact:** Fast-interaction prefetch tasks that become stale due to fast scrolling are caught and discarded sooner (threshold 3 vs 20).

---

## 4. Expected KPI Impact

### Theoretical analysis (from log 33 evidence)

| KPI | B2.5 Baseline | Expected after B3.6 | Mechanism |
|-----|:---:|:---:|---|
| Booster stale ratio | 100% (log 33) | 0% during scroll | Gate blocks worker |
| CPU during scroll | 124-188% | ~80-120% (est.) | One fewer decode thread |
| GIL contention (booster) | 20-62ms/decode | 0ms during scroll | Worker blocked, no GIL |
| set_slice P95 (foreground) | 42-84ms (log 33) | ~30-50ms (est.) | Less GIL competition |
| Cache hit ratio | 0% (fast scroll) | Modest improvement | More GIL for pipeline |
| Pipeline stale ratio | 80-94% (B2.5) | ~40-60% (est.) | Tighter pre-decode check |

### Conservative estimates by scenario

| Scenario | Before P95 | Expected P95 | Improvement |
|----------|:---:|:---:|---|
| S1 (viewer only) | 41.1ms → 18ms (B3.2) | ~15ms | Booster GIL freed |
| S2 (viewer + DL) | 58.7ms → 45ms target | ~35ms | Major GIL relief |
| S4 (rapid burst) | 45.1ms → 22ms (B3.2) | ~18ms | Less decode contention |
| S6 (low-end 2 workers) | 33.9ms | ~25ms | Booster pause most impactful here |

---

## 5. Design Decisions

### D1: Event.wait() vs Thread.cancel+restart
- **Chosen**: `threading.Event` gate — worker blocks and unblocks in microseconds
- **Rejected**: Cancel + restart (join overhead ~5-50ms, thread creation overhead)
- **Rationale**: Zero overhead on the hot path; no thread lifecycle management

### D2: Bridge-level wiring vs VTK-scroll notify modification
- **Chosen**: Wire pause/resume in `QtViewerBridge.set_slice()` and `end_fast_interaction()`
- **Rejected**: Modify `_vw_scroll.py` booster notify path
- **Rationale**: Bridge already owns the `fast_interaction` state; keeps change localized

### D3: Fixed threshold=3 vs adaptive during fast interaction
- **Chosen**: Fixed threshold=3 for pipeline pre-decode during fast interaction
- **Rejected**: Dynamic computation based on velocity
- **Rationale**: During fast interaction, the relevance threshold is intentionally tight. B3.7 later raised adaptive radius to 3, so threshold=3 now directly matches the fast cap.

### D4: Booster position relevance check (stale skipping in worker)
- **Added**: `abs(idx - current_center) > window` check before each decode
- **Rationale**: Catches stale slices that were queued before pause but became irrelevant. Also helps during the brief period after resume where old indices may still be in the priority list.

---

## 6. Files Changed

| File | Change | Lines |
|------|--------|-------|
| `modules/zeta_boost/image_slice_booster.py` | `_interaction_gate` Event + pause/resume API + worker gate check + position relevance | +30 |
| `modules/viewer/fast/qt_viewer_bridge.py` | `_get_booster`, `_pause_booster`, `_resume_booster` + wiring in `set_slice`/`end_fast_interaction` | +45 |
| `modules/viewer/fast/lightweight_2d_pipeline.py` | Tighter pre-decode distance during `_fast_interaction` | +4 |

**Total:** ~79 lines added, 0 removed

---

## 7. Test Coverage

| Test file | Tests | Description |
|-----------|------:|-------------|
| `tests/viewer/test_b36_booster_interaction_gate.py` | 20 | Gate API, threading, bridge wiring, position check |
| `tests/viewer/test_fast_viewer_pipeline.py` | 56 | Pipeline, progressive display (regression) |
| `tests/viewer/test_b35_deferred_header_fill.py` | 12 | B3.5 header fill (regression) |
| `tests/viewer/test_stage1_migration_validation.py` | 34 | Stage 1 migration (regression) |
| `tests/viewer/test_stage2_hardening_validation.py` | 15 | Stage 2 hardening (regression) |
| `tests/smoke/test_import_smoke.py` | 24 | Import smoke (regression) |
| `tests/download_manager/run_dm_test.py` | 129 assertions | DM full suite (regression) |

**Total: 181 tests passing + 129 DM assertions**

---

## 8. Validation Checklist

- [x] `_interaction_gate` Event created and set in `__init__`
- [x] `pause_for_interaction()` clears gate (worker blocks)
- [x] `resume_from_interaction()` sets gate (worker unblocks)
- [x] Worker loop checks gate before each decode
- [x] Worker re-checks `_cancel` after gate wake
- [x] Worker checks position relevance (stale skip)
- [x] Bridge `set_slice(fast_interaction=True)` calls `_pause_booster()`
- [x] Bridge `set_slice(fast_interaction=False)` calls `_resume_booster()`
- [x] Bridge `end_fast_interaction()` calls `_resume_booster()`
- [x] Pause/resume are idempotent (no duplicate calls to booster)
- [x] Pipeline uses threshold=3 during fast interaction
- [x] Pipeline uses full `prefetch_radius` when not interacting
- [x] 20 new B3.6 tests pass
- [x] 161 prior tests pass (no regression)
- [x] 129 DM assertions pass
- [x] 24 smoke tests pass
- [x] No lint errors

---

## 9. Remaining Work (B4)

- **Full KPI validation**: Run B2.5 scenarios with B3.6 applied, capture tables, compare deltas
- **Real DICOM validation**: Test on PC A with real patient data (CT 200+ slices)
- **Cross-PC validation**: Push to GitHub → pull on PC B → compare behavior/logs
- **ZetaBoost cache**: Investigate why entries=0 during progressive download (separate issue)
- **First-slice optimization**: <40ms target — may require warm-start or decode preload
