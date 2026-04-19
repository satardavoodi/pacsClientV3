# B2.5 Concurrent-Load Baseline Report

**Date:** 2026-04-14
**Version:** v2.3.3
**Hardware:** Developer PC (PC A)
**Series:** 100 slices, 128×128 pixels (synthetic DICOM)
**Pipeline:** `Lightweight2DPipeline` (FAST mode, `pydicom_qt` backend)

---

## 1. Scenario Summary Table

| Scenario | Description | P50 ms | P95 ms | max ms | slow>16ms | slow>33ms | Q-depth max | stale% | FPS |
|----------|-------------|-------:|-------:|-------:|----------:|----------:|------------:|-------:|----:|
| S1 | Viewer-only baseline | 0.06 | 41.12 | 180.38 | 56 | 23 | 20 | 81.4% | 70 |
| S2 | Viewer + download (GIL) | 1.00 | 58.73 | 89.51 | 67 | 58 | 20 | 84.0% | 51 |
| S3 | Viewer + DL + filter settle | 0.07 | 68.47 | 692.05 | 35 | 30 | 20 | 83.4% | 30 |
| S4 | Rapid scroll burst | 0.47 | 45.11 | 77.11 | 67 | 45 | 6 | 88.2% | 106 |
| S5 | Direction reversal | 0.03 | 0.06 | 39.27 | 6 | 2 | 37 | — | 673 |
| S6 | Low-end (2 workers) | 1.25 | 33.90 | 46.87 | 102 | 18 | 7 | 94.5% | 74 |
| S7 | Open/close cycles ×20 | 0.23 | 33.50 | 104.63 | 334 | 101 | 21 | 79.8% | 20 |

**Download Interference Index (DII):** 42.8% (S2 P95 vs S1 P95)

---

## 2. System KPI Details

### Foreground Wait (cache-miss main-thread decode)

| Scenario | fg_wait P50 ms | fg_wait P95 ms | fg_wait max ms |
|----------|---------------:|---------------:|---------------:|
| S1 | 0.01 | 50.69 | 173.08 |
| S2 | 0.01 | 58.54 | 79.20 |
| S3 | 0.01 | 93.14 | 244.06 |
| S4 | 0.02 | 47.64 | 69.16 |
| S6 | 16.65 | 33.00 | 45.33 |
| S7 | 0.01 | 36.06 | 100.59 |

### Cache Efficiency

| Scenario | Hit ratio | Hits | Misses |
|----------|----------:|-----:|-------:|
| S1 | 8.6% | 14 | 148 |
| S2 | 0.0% | 0 | 169 |
| S3 | 0.0% | 0 | 73 |
| S4 | 0.0% | 0 | 152 |
| S5 | 94.6% | 123 | 7 |
| S6 | 0.0% | 0 | 184 |
| S7 | 0.0% | 0 | 1034 |

### Prefetch Task Lifecycle

| Scenario | Submitted | Completed | Stale | Stale ratio |
|----------|----------:|----------:|------:|------------:|
| S1 | 242 | 242 | 197 | 81.4% |
| S2 | 250 | 250 | 210 | 84.0% |
| S3 | 151 | 150 | 126 | 83.4% |
| S4 | 229 | 228 | 202 | 88.2% |
| S6 | 235 | 236 | 222 | 94.5% |
| S7 | 1980 | 1980 | 1580 | 79.8% |

### Process Metrics

| Scenario | CPU P50% | CPU P95% | RSS start MB | RSS end MB | RSS growth MB |
|----------|----------:|----------:|-------------:|-----------:|--------------:|
| S1 | 42.5 | 270.9 | 207.7 | 218.8 | 11.2 |
| S2 | 177.8 | 237.6 | 213.1 | 219.4 | 6.3 |
| S6 | 210.5 | 279.5 | 214.2 | 218.7 | 4.6 |
| S7 | 18.5 | 197.2 | 213.0 | 217.9 | 5.0 |

---

## 3. Key Findings

### 3.1. GIL Contention (CONFIRMED — HIGH IMPACT)

**DII = 42.8%:** Under simulated download GIL contention (4 background `pydicom.dcmread` threads), P95 set_slice latency increases from 41ms → 59ms. The first image time nearly doubles (22.5ms → 36ms). Slow frames (>33ms) increase from 23 → 58.

**Mechanism:** Background threads holding GIL for 3-8ms during `dcmread` delay the main thread's decode calls. With 4 contention threads + 4 pipeline decode workers, worst-case GIL convoy can reach ~40ms.

**S2 CPU P50 = 178%** vs S1 CPU P50 = 43%: The contention threads consume significant CPU but the work is largely wasted from the viewer's perspective.

### 3.2. Stale Prefetch Work (CONFIRMED — VERY HIGH)

**80-94% of prefetch work is wasted across all scenarios.** This means the decode workers are spending the vast majority of their time decoding slices that are never displayed — scroll speed consistently outpaces the prefetch-ahead window.

Key observations:
- S1: 81.4% stale — even without contention, prefetch is mostly wasted
- S4 (burst): 88.2% stale — burst scroll makes prefetch deeply obsolete
- S6 (low-end): 94.5% stale — fewer workers + contention = even more wasted work
- This represents a massive GIL contention amplifier: stale work holds the GIL competing with useful work

### 3.3. Cache Efficiency (LOW in most scenarios)

Cache hit ratio is 0-8.6% in most scrolling scenarios with 100 slices. Only S5 (direction reversals within a small range) achieves 94.6% hit ratio. This means every scroll consistently triggers foreground decode, and the cache provides almost no benefit during continuous scrolling.

**Root cause:** With 100 slices and prefetch_radius=20, the cache (96 slots) should hold most of the series. But the combination of rapid scrolling + stale work + cache eviction means the cache is constantly churning with stale entries.

### 3.4. Filter Settle Spikes (MODERATE)

S3's max of 692ms is the highest latency across all scenarios. The `rerender_current_filtered()` call after scroll-stop must re-decode and apply filters, and under GIL contention this can take nearly 700ms. The recovery time is not separately instrumented yet but the max set_slice gives an upper bound.

### 3.5. Memory Stability (GOOD)

S7 degradation_ratio = 0.667 (later cycles FASTER than earlier ones — JIT/warmup effect). RSS growth: ~5MB over 20 open/close cycles with 100 slices each. No memory leak detected.

### 3.6. Low-End Profile (MODERATE CONCERN)

S6 with 2 workers: P50 jumps to 1.25ms (21× vs S1's 0.06ms), 102/300 frames exceed 16ms, foreground wait P50 = 16.65ms (vs 0.01ms baseline). Reduced worker pool significantly impacts performance because there are fewer workers to absorb the prefetch load and cache misses force main-thread decode.

---

## 4. Bottleneck Ranking (by impact on user-visible scroll quality)

| Rank | Bottleneck | Evidence | Estimated impact |
|------|-----------|----------|-----------------|
| 1 | **Stale prefetch amplifying GIL** | 80-94% wasted work | Fixing could reduce GIL contention by ~4× |
| 2 | **GIL contention (download path)** | DII=42.8%, P95 +18ms | Directly degrades scroll under download |
| 3 | **Cache churn from stale entries** | 0-8.6% hit ratio on scroll | Forces foreground decode on nearly every frame |
| 4 | **Filter settle under contention** | max=692ms | Blocks viewer for up to 700ms after scroll-stop |
| 5 | **Low-end worker starvation** | 102/300 slow frames at 2 workers | Performance cliff for slower hardware |

---

## 5. Recommended First Optimization Target

**Target: Stale Prefetch Cancellation (Rank 1)**

Rationale: 80-94% of decode worker time is wasted on slices that scroll past before they're needed. This is the single largest waste of GIL time. A prefetch cancellation mechanism that aborts irrelevant work would:
- Reduce GIL contention by up to 4× (fewer workers holding GIL for stale work)
- Improve cache hit ratio (cache slots not wasted on stale slices)
- Indirectly improve DII (less background GIL competition)
- Benefit all scenarios — not just contention ones

**Expected KPI movement:**
- Stale ratio: 80-94% → target <20%
- Cache hit ratio: 0-8% → target >50%
- set_slice P95: target -30% or more
- DII: target <25% (from 42.8%)

---

## 6. Reproduction

```bash
# Full baseline (100 slices, 128×128)
python tests/performance/test_b25_scenarios.py --slices 100 --size 128 --json

# Quick validation (30 slices, 32×32)
python tests/performance/test_b25_scenarios.py --slices 30 --size 32

# Single scenario
python tests/performance/test_b25_scenarios.py S2 --slices 100 --size 128
```

JSON output stored in `tests/performance/b25_output/`.

---

## 7. Files Created/Modified for B2.5

### New files
| File | Purpose |
|------|---------|
| `modules/viewer/fast/perf_metrics.py` | Central metrics collector (singleton, thread-safe, opt-in) |
| `tests/performance/perf_helpers.py` | Scenario test helpers: GIL/CPU simulators, process sampler, scroll patterns |
| `tests/performance/test_b25_scenarios.py` | 7 automated scenario tests with KPI output |
| `docs/performance/WORKLOAD_MODEL.md` | Code-path-to-workload-class mapping |
| `docs/performance/B25_BASELINE_REPORT.md` | This report |

### Modified files (instrumentation hooks)
| File | Changes |
|------|---------|
| `modules/viewer/fast/lightweight_2d_pipeline.py` | 5 hook insertions: queue depth, cache hit/miss, foreground wait, prefetch submit/complete, stale detection |
| `modules/viewer/fast/qt_viewer_bridge.py` | 2 hook insertions: set_slice timing, first-image recording |

All hooks are guarded by `if not _pm.enabled: return` (single bool check, zero overhead when disabled).
