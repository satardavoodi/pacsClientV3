# Performance Decision Log — 2026-02-26 / 2026-02-27

> Continuation of `PERFORMANCE_DECISION_LOG_2026-02-24.md`.  
> See `docs/PERFORMANCE_STATUS.md` for the current one-page summary of all findings.

---

## Session 2026-02-26 — Parallel I/O + Scroll Drain

### Data Observed

**Logs from PC A (study: 330-slice CT + MR brain, ~10 series):**

| Stage | Before | Measured |
|---|---|---|
| Instance create (viewer, 330 files) | — | 4.307s serial |
| batch_insert_instances_total (download subprocess, ~480 files) | — | 2217ms serial |
| apply_filters MR 20sl (Mode B DL_WARMUP, 1-thread) | — | ~2.9s per series |
| scroll spike during DL_WARMUP ITK | — | 200–309ms spikes |
| queue_p95_ms in scroll probe | — | **19,496ms** (stale-event backlog) |

### Decisions Made

**v2.2.3.1.9** — Parallel pydicom, viewer side  
- `utils.py` `get_or_create_instance`: replaced serial pydicom loop with `ThreadPoolExecutor(max_workers=min(8, cpu_count))`  
- Result: 4.307s → ~0.8s for 330-file CT

**v2.2.3.2.0** — Parallel pydicom, download subprocess + adaptive ITK + BELOW_NORMAL filter priority  
- `series_downloader.py`: parallel `asyncio.gather` + ThreadPoolExecutor for header reads  
- `image_filters.py`: adaptive `max(min(cpu_count-2, 8), 2)` threads (was fixed at 1)  
- `image_filters.py`: `THREAD_PRIORITY_BELOW_NORMAL` via ctypes during filter pass  
- Result: batch_insert 2217ms → 326ms

**v2.2.3.2.1** — Stale-event fast-drain guard in `set_slice`  
- Root cause: main thread blocked by SERIES_DOWNLOAD_COMPLETE signal handlers → Qt event queue fills with stale scroll events → each renders fully at ~50ms  
- Fix: when `queue_delay_ms > 500ms`, skip VTK render (slider only), set `_pending_wheel_slice` for one render after drain  
- Result: 84-event backlog drained in <1ms, one render at final position

---

## Session 2026-02-27 — DL_WARMUP Speed

### Data Observed

**Logs from PC A (new MR brain study download, threads=1 DL_WARMUP):**

| Stage | Observed | Problem |
|---|---|---|
| DL_WARMUP series=6 (500×640×24 MR) | 4138ms | threads=1 ITK 2939ms |
| DL_WARMUP series=7 (620×640×20 MR) | 3884ms | threads=1 ITK 2976ms |
| DL_WARMUP series=8 (176×176×40 MR) | 1172ms | threads=1 ITK 473ms — OK |
| WORKER_BLOCKED reason=max_parallel(1/1) | 5 events | ZetaBoost can't run workers in parallel |
| queue_delay_ms during scroll | 2804–3587ms | stale-drain guard not yet deployed in this run |

### Decision

**v2.2.3.2.2** — DL_WARMUP speed improvements  
- `max_itk_threads=1` → `max_itk_threads=2` in DL_WARMUP path (halves large-FOV MR time: 4.1s → ~2.0s)  
- Inter-series delay `3.0s` → `1.5s` (ITK now faster; 3s was conservative)  
- `max_parallel_loads=1` → `max_parallel_loads=2` for 8GB+ and 15GB+ RAM tiers  
  - Justified by: BELOW_NORMAL OS priority (v2.2.3.2.0) + stale-drain guard (v2.2.3.2.1) protect VTK render from ITK contention  
  - Expected: two ZetaBoost workers can overlap; 6-series warmup finishes in ~8–10s instead of ~20s

---

## Open Questions for Next Session

1. **Does v2.2.3.2.1 actually drain the 2804–3587ms queue_delay events in the latest run?**  
   Check for `stale_drain_complete` in logs after pulling `9724dea`.

2. **Does DL_WARMUP with `threads=2` now show ~2s per large MR series?**  
   Check `[DL_WARMUP] ✓ Cached series=X in Yms` after pulling `ff0d4b1`.

3. **Does `WORKER_BLOCKED reason=max_parallel(1/2)` appear (vs old `max_parallel(1/1)`)?**  
   Confirms the 8GB+ tier is using the new `max_parallel_loads=2`.

4. **What still causes 38–88ms `viewer_db_read` per series load?**  
   The query is `SELECT pk, instances FROM series WHERE uid=?` — may be missing an index or scanning.

5. **Is the P1 queue spike (2.8–3.5s) actually coming from `SERIES_DOWNLOAD_COMPLETE` signal handlers?**  
   Add `t0 = time.monotonic()` at the top of that handler, log at the end. Confirm duration matches.

---

## Rollback Notes

If any v2.2.3.2.x change causes regression:

| Issue | Rollback |
|---|---|
| Stale drain causes missed renders | Set `_STALE_SCROLL_MS = 99999` in vtk_widget.py (effectively disables guard) |
| DL_WARMUP threads=2 causes scroll spikes | Set `max_itk_threads=1` in `_dl_warmup_worker` call (line ~4500 of viewer_controller) |
| max_parallel_loads=2 causes overshooting | Set `max_parallel_loads=1` in the tier config block (~line 420) |
| Inter-delay 1.5s too aggressive | Set `AIPACS_DL_WARMUP_INTER_DELAY=3.0` env var (no code change needed) |
