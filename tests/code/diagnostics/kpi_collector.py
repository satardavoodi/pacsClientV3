"""
tests/diagnostics/kpi_collector.py
=====================================
KPI collection for the FAST viewer diagnostic framework.

Wraps key lifecycle methods with spy closures that record timing and counts
into an EventLog without modifying production source code.

KPI Categories
--------------
Count KPIs  (C-xx)  — how many times a method/path was reached
Timing KPIs (T-xx)  — duration of a call in milliseconds
State KPIs  (S-xx)  — boolean/enum fields at checkpoints
Memory KPIs (M-xx)  — RSS / VMS / numpy memmap usage

Usage
-----
    from tests.diagnostics.kpi_collector import KpiCollector
    from tests.diagnostics.event_log import EventLog

    log = EventLog(output_dir=run_dir)
    col = KpiCollector(log=log)

    # Instrument a real or mock controller
    col.attach_controller(controller)
    col.attach_loader(loader)

    # ... run scenario ...

    kpis = col.collect()
    print(kpis)
"""
from __future__ import annotations

import gc
import os
import sys
import time
import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from tests.diagnostics.event_log import (
    EventLog,
    ET_PROGRESSIVE_START,
    ET_PROGRESSIVE_GROW,
    ET_PROGRESSIVE_STALE,
    ET_PROGRESSIVE_STALE_EXHAUSTED,
    ET_PROGRESSIVE_COMPLETE,
    ET_PROGRESSIVE_MODE_ENTERED,
    ET_PROGRESSIVE_MODE_EXITED,
    ET_METADATA_REFRESH_BEGIN,
    ET_METADATA_REFRESH_DONE,
    ET_GROW_CALLED,
    ET_GROW_RETURNED,
    ET_DECODE_SLICE_READY,
    ET_DECODE_FAILED,
    ET_BACKEND_BIND,
    ET_GENERATION_INCR,
    ET_SERIES_SWITCH_BEGIN,
    ET_SERIES_SWITCH_DONE,
    ET_LOADER_CREATED,
    ET_LOADER_RELEASED,
    ET_COMPLETION_VERIFY_START,
    ET_COMPLETION_VERIFY_DONE,
    ET_COMPLETION_SWEEP_TICK,
    ET_INFLIGHT_SET,
    ET_INFLIGHT_CLEARED,
    ET_DONE_GUARD_SET,
    ET_MEMORY_SNAPSHOT,
    ET_SERIES_PROGRESS,
    ET_EXCEPTION_SWALLOWED,
)

# ─── KPI name constants ───────────────────────────────────────────────────────

# Count KPIs
C01_PROGRESSIVE_START_CALLS           = "C01_progressive_start_calls"
C02_GROW_CALLS                        = "C02_grow_calls"
C03_GROW_STALE_RETURNS                = "C03_grow_stale_returns"
C04_METADATA_REFRESH_CALLS            = "C04_metadata_refresh_calls"
C05_DECODE_SLICE_READY_SIGNALS        = "C05_decode_slice_ready_signals"
C06_DECODE_FAILED_SIGNALS             = "C06_decode_failed_signals"
C07_SERIES_SWITCH_CALLS               = "C07_series_switch_calls"
C08_BACKEND_BIND_CALLS                = "C08_backend_bind_calls"
C09_COMPLETION_VERIFY_CALLS           = "C09_completion_verify_calls"
C10_COMPLETION_SWEEP_TICKS            = "C10_completion_sweep_ticks"
C11_PROGRESS_SIGNALS_RECEIVED         = "C11_progress_signals_received"
C12_PROGRESSIVE_MODE_ENTERS           = "C12_progressive_mode_enters"
C13_PROGRESSIVE_MODE_EXITS            = "C13_progressive_mode_exits"
C14_INFLIGHT_SET_COUNT                = "C14_inflight_set_count"
C15_DONE_GUARD_SET_COUNT              = "C15_done_guard_set_count"
C16_EXCEPTIONS_SWALLOWED              = "C16_exceptions_swallowed"
C17_LOADER_CREATED_COUNT              = "C17_loader_created_count"
C18_LOADER_RELEASED_COUNT             = "C18_loader_released_count"

# Timing KPIs (first / last / max / p95 derived from event log)
T01_FIRST_PROGRESS_TO_FIRST_GROW_MS   = "T01_first_progress_to_first_grow_ms"
T02_FIRST_GROW_TO_PROGRESSIVE_START_MS = "T02_first_grow_to_progressive_start_ms"
T03_SERIES_SWITCH_DURATION_MS         = "T03_series_switch_duration_ms"
T04_DOWNLOAD_COMPLETE_TO_FINAL_GROW_MS = "T04_download_complete_to_final_grow_ms"
T05_METADATA_REFRESH_MAX_MS           = "T05_metadata_refresh_max_ms"
T06_METADATA_REFRESH_MEAN_MS          = "T06_metadata_refresh_mean_ms"
T07_GROW_MAX_MS                       = "T07_grow_max_ms"
T08_GROW_MEAN_MS                      = "T08_grow_mean_ms"
T09_PROGRESSIVE_START_DURATION_MS     = "T09_progressive_start_duration_ms"
T10_DECODE_SLICE_MAX_MS               = "T10_decode_slice_max_ms"
T11_STALE_RETRY_TOTAL_MS              = "T11_stale_retry_total_ms"
T12_INFLIGHT_DURATION_MS              = "T12_inflight_duration_ms"
T13_FIRST_TO_LAST_GROW_MS             = "T13_first_to_last_grow_ms"
T14_SWEEP_TICK_MAX_MS                 = "T14_sweep_tick_max_ms"

# State KPIs
S01_FINAL_GROW_COUNT                  = "S01_final_grow_count"
S02_EXPECTED_TOTAL                    = "S02_expected_total"
S03_LAST_GROW_RETURN_VALUE            = "S03_last_grow_return_value"
S04_STALE_MAX_RETRY_REACHED           = "S04_stale_max_retry_reached"
S05_INFLIGHT_STILL_SET_AT_END         = "S05_inflight_still_set_at_end"
S06_DONE_GUARD_KEYS                   = "S06_done_guard_keys"
S07_PROGRESSIVE_STILL_ACTIVE_AT_END   = "S07_progressive_still_active_at_end"
S08_GENERATION_IDS_SEEN               = "S08_generation_ids_seen"
S09_MODALITY                          = "S09_modality"
S10_SERIES_NUMBER                     = "S10_series_number"

# Memory KPIs
M01_RSS_MB_AT_START                   = "M01_rss_mb_at_start"
M02_RSS_MB_AT_PEAK                    = "M02_rss_mb_at_peak"
M03_RSS_MB_AT_END                     = "M03_rss_mb_at_end"
M04_RSS_DELTA_MB                      = "M04_rss_delta_mb"
M05_GC_OBJECTS_AT_START               = "M05_gc_objects_at_start"
M06_GC_OBJECTS_AT_END                 = "M06_gc_objects_at_end"
M07_GC_DELTA                          = "M07_gc_delta"
M08_MEMMAP_HANDLE_COUNT               = "M08_memmap_handle_count"
M09_LOADER_REGISTRY_SIZE              = "M09_loader_registry_size"
M10_PEAK_GROW_ARRAY_MB                = "M10_peak_grow_array_mb"


def _rss_mb() -> float:
    """Return current RSS in MB, or 0 if psutil not available."""
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def _gc_count() -> int:
    return sum(gc.get_count())


# ─── KpiCollector ─────────────────────────────────────────────────────────────

class KpiCollector:
    """Collects KPIs by wrapping controller / loader methods.

    All timings are in milliseconds.  Thread-safe for concurrent signal dispatch.
    """

    def __init__(self, log: Optional[EventLog] = None) -> None:
        self._log = log or EventLog()  # in-memory only if no dir given
        self._lock = threading.Lock()
        self._counts: Dict[str, int] = defaultdict(int)
        self._timings: Dict[str, List[float]] = defaultdict(list)
        self._states: Dict[str, Any] = {}
        self._timestamps: Dict[str, float] = {}   # named checkpoints
        self._t0 = time.monotonic()
        self._rss_start = _rss_mb()
        self._gc_start = _gc_count()
        self._rss_peak = self._rss_start
        self._originals: Dict[str, Tuple[object, str, Callable]] = {}
        self._closed = False

    # ── instrument a controller ───────────────────────────────────────────────

    def attach_controller(self, controller: object) -> None:
        """Wrap key methods on *controller* with timing/count spies."""
        self._wrap(controller, "_start_progressive_display",
                   self._spy_progressive_start)
        self._wrap(controller, "_grow_progressive_fast",
                   self._spy_grow_fast)
        self._wrap(controller, "_refresh_stored_metadata_instances",
                   self._spy_metadata_refresh)
        self._wrap(controller, "on_series_images_progress",
                   self._spy_progress_signal)
        self._wrap(controller, "on_series_download_fully_complete",
                   self._spy_download_complete)
        self._wrap(controller, "_completion_verify_series",
                   self._spy_completion_verify)
        self._wrap(controller, "_completion_sweep_tick",
                   self._spy_completion_sweep)

    def attach_loader(self, loader: object) -> None:
        """Wrap grow() and request_slice_loaded() on *loader*."""
        self._wrap(loader, "grow", self._spy_loader_grow)

    # ── spy wrappers ──────────────────────────────────────────────────────────

    def _spy_progressive_start(self, orig, *args, **kwargs):
        t0 = time.monotonic()
        self._bump(C01_PROGRESSIVE_START_CALLS)
        self._mark_ts("progressive_start_begin")
        result = orig(*args, **kwargs)
        dur_ms = (time.monotonic() - t0) * 1000
        self._record_timing(T09_PROGRESSIVE_START_DURATION_MS, dur_ms)
        self._log.append(ET_PROGRESSIVE_START, duration_ms=dur_ms)
        return result

    def _spy_grow_fast(self, orig, *args, **kwargs):
        t0 = time.monotonic()
        self._bump(C02_GROW_CALLS)
        if not self._has_ts("first_grow"):
            self._mark_ts("first_grow")
            self._compute_t01_latency()
        result = orig(*args, **kwargs)
        dur_ms = (time.monotonic() - t0) * 1000
        self._record_timing(T07_GROW_MAX_MS, dur_ms)
        self._mark_ts("last_grow")
        self._log.append(ET_PROGRESSIVE_GROW, duration_ms=dur_ms)
        return result

    def _spy_metadata_refresh(self, orig, *args, **kwargs):
        t0 = time.monotonic()
        self._bump(C04_METADATA_REFRESH_CALLS)
        self._log.append(ET_METADATA_REFRESH_BEGIN, series=args[0] if args else None)
        result = orig(*args, **kwargs)
        dur_ms = (time.monotonic() - t0) * 1000
        self._record_timing(T05_METADATA_REFRESH_MAX_MS, dur_ms)
        self._log.append(ET_METADATA_REFRESH_DONE, duration_ms=dur_ms)
        # Snapshot RSS after each metadata refresh (primary H1 diagnostic)
        rss = _rss_mb()
        with self._lock:
            self._rss_peak = max(self._rss_peak, rss)
        return result

    def _spy_progress_signal(self, orig, *args, **kwargs):
        self._bump(C11_PROGRESS_SIGNALS_RECEIVED)
        if not self._has_ts("first_progress"):
            self._mark_ts("first_progress")
        sn = args[0] if args else kwargs.get("series_number", "?")
        downloaded = args[1] if len(args) > 1 else kwargs.get("downloaded", 0)
        total = args[2] if len(args) > 2 else kwargs.get("total", 0)
        self._log.append(ET_SERIES_PROGRESS,
                         series_number=str(sn),
                         downloaded=downloaded,
                         total=total)
        return orig(*args, **kwargs)

    def _spy_download_complete(self, orig, *args, **kwargs):
        self._mark_ts("download_complete")
        result = orig(*args, **kwargs)
        self._compute_t04_latency()
        return result

    def _spy_completion_verify(self, orig, *args, **kwargs):
        t0 = time.monotonic()
        self._bump(C09_COMPLETION_VERIFY_CALLS)
        self._log.append(ET_COMPLETION_VERIFY_START)
        result = orig(*args, **kwargs)
        dur_ms = (time.monotonic() - t0) * 1000
        self._log.append(ET_COMPLETION_VERIFY_DONE, duration_ms=dur_ms)
        return result

    def _spy_completion_sweep(self, orig, *args, **kwargs):
        t0 = time.monotonic()
        self._bump(C10_COMPLETION_SWEEP_TICKS)
        result = orig(*args, **kwargs)
        dur_ms = (time.monotonic() - t0) * 1000
        self._record_timing(T14_SWEEP_TICK_MAX_MS, dur_ms)
        self._log.append(ET_COMPLETION_SWEEP_TICK, duration_ms=dur_ms)
        return result

    def _spy_loader_grow(self, orig, *args, **kwargs):
        t0 = time.monotonic()
        self._log.append(ET_GROW_CALLED)
        result = orig(*args, **kwargs)
        dur_ms = (time.monotonic() - t0) * 1000
        self._record_timing(T07_GROW_MAX_MS, dur_ms)
        with self._lock:
            self._states[S03_LAST_GROW_RETURN_VALUE] = result
        self._log.append(ET_GROW_RETURNED, count=result, duration_ms=dur_ms)
        return result

    # ── public checkpoints (called manually from harness/scenarios) ───────────

    def record_decode_ready(self, slice_index: int, decode_ms: float) -> None:
        self._bump(C05_DECODE_SLICE_READY_SIGNALS)
        self._record_timing(T10_DECODE_SLICE_MAX_MS, decode_ms)
        self._log.append(ET_DECODE_SLICE_READY,
                         slice_index=slice_index,
                         decode_ms=decode_ms)

    def record_decode_failed(self, reason: str) -> None:
        self._bump(C06_DECODE_FAILED_SIGNALS)
        self._log.append(ET_DECODE_FAILED, reason=reason)

    def record_progressive_enter(self, series_number: str) -> None:
        self._bump(C12_PROGRESSIVE_MODE_ENTERS)
        self._log.append(ET_PROGRESSIVE_MODE_ENTERED, series_number=series_number)

    def record_progressive_exit(self, series_number: str) -> None:
        self._bump(C13_PROGRESSIVE_MODE_EXITS)
        self._log.append(ET_PROGRESSIVE_MODE_EXITED, series_number=series_number)

    def record_inflight_set(self, key: str) -> None:
        self._bump(C14_INFLIGHT_SET_COUNT)
        self._mark_ts(f"inflight_set_{key}")
        self._log.append(ET_INFLIGHT_SET, key=key)

    def record_inflight_cleared(self, key: str) -> None:
        self._log.append(ET_INFLIGHT_CLEARED, key=key)

    def record_done_guard_set(self, key: str) -> None:
        self._bump(C15_DONE_GUARD_SET_COUNT)
        self._log.append(ET_DONE_GUARD_SET, key=key)

    def record_exception_swallowed(self, location: str, exc_type: str) -> None:
        self._bump(C16_EXCEPTIONS_SWALLOWED)
        self._log.append(ET_EXCEPTION_SWALLOWED,
                         location=location,
                         exc_type=exc_type)

    def snapshot_memory(self) -> None:
        """Record an RSS snapshot to the event log."""
        rss = _rss_mb()
        gc_count = _gc_count()
        with self._lock:
            self._rss_peak = max(self._rss_peak, rss)
        self._log.append(
            ET_MEMORY_SNAPSHOT,
            rss_mb=rss,
            gc_objects=gc_count,
            elapsed_s=time.monotonic() - self._t0,
        )

    def set_scenario_state(self, **kwargs: Any) -> None:
        """Record arbitrary key/value state at end of scenario for state KPIs."""
        with self._lock:
            self._states.update(kwargs)

    # ── derived KPI computation ───────────────────────────────────────────────

    def collect(self) -> Dict[str, Any]:
        """Return the complete KPI dict.  Safe to call multiple times."""
        with self._lock:
            counts = dict(self._counts)
            timings = {k: list(v) for k, v in self._timings.items()}
            states = dict(self._states)
            timestamps = dict(self._timestamps)

        rss_end = _rss_mb()
        gc_end = _gc_count()

        kpis: Dict[str, Any] = {}

        # Count KPIs
        kpis.update({
            C01_PROGRESSIVE_START_CALLS:    counts.get(C01_PROGRESSIVE_START_CALLS, 0),
            C02_GROW_CALLS:                 counts.get(C02_GROW_CALLS, 0),
            C03_GROW_STALE_RETURNS:         counts.get(C03_GROW_STALE_RETURNS, 0),
            C04_METADATA_REFRESH_CALLS:     counts.get(C04_METADATA_REFRESH_CALLS, 0),
            C05_DECODE_SLICE_READY_SIGNALS: counts.get(C05_DECODE_SLICE_READY_SIGNALS, 0),
            C06_DECODE_FAILED_SIGNALS:      counts.get(C06_DECODE_FAILED_SIGNALS, 0),
            C07_SERIES_SWITCH_CALLS:        counts.get(C07_SERIES_SWITCH_CALLS, 0),
            C08_BACKEND_BIND_CALLS:         counts.get(C08_BACKEND_BIND_CALLS, 0),
            C09_COMPLETION_VERIFY_CALLS:    counts.get(C09_COMPLETION_VERIFY_CALLS, 0),
            C10_COMPLETION_SWEEP_TICKS:     counts.get(C10_COMPLETION_SWEEP_TICKS, 0),
            C11_PROGRESS_SIGNALS_RECEIVED:  counts.get(C11_PROGRESS_SIGNALS_RECEIVED, 0),
            C12_PROGRESSIVE_MODE_ENTERS:    counts.get(C12_PROGRESSIVE_MODE_ENTERS, 0),
            C13_PROGRESSIVE_MODE_EXITS:     counts.get(C13_PROGRESSIVE_MODE_EXITS, 0),
            C14_INFLIGHT_SET_COUNT:         counts.get(C14_INFLIGHT_SET_COUNT, 0),
            C15_DONE_GUARD_SET_COUNT:       counts.get(C15_DONE_GUARD_SET_COUNT, 0),
            C16_EXCEPTIONS_SWALLOWED:       counts.get(C16_EXCEPTIONS_SWALLOWED, 0),
            C17_LOADER_CREATED_COUNT:       counts.get(C17_LOADER_CREATED_COUNT, 0),
            C18_LOADER_RELEASED_COUNT:      counts.get(C18_LOADER_RELEASED_COUNT, 0),
        })

        # Timing KPIs
        kpis[T05_METADATA_REFRESH_MAX_MS] = (
            max(timings.get(T05_METADATA_REFRESH_MAX_MS, [0])) if timings.get(T05_METADATA_REFRESH_MAX_MS) else 0.0
        )
        kpis[T06_METADATA_REFRESH_MEAN_MS] = (
            _mean(timings.get(T05_METADATA_REFRESH_MAX_MS, [])) or 0.0
        )
        kpis[T07_GROW_MAX_MS] = (
            max(timings.get(T07_GROW_MAX_MS, [0])) if timings.get(T07_GROW_MAX_MS) else 0.0
        )
        kpis[T08_GROW_MEAN_MS] = (
            _mean(timings.get(T07_GROW_MAX_MS, [])) or 0.0
        )
        kpis[T09_PROGRESSIVE_START_DURATION_MS] = (
            max(timings.get(T09_PROGRESSIVE_START_DURATION_MS, [0])) if timings.get(T09_PROGRESSIVE_START_DURATION_MS) else 0.0
        )
        kpis[T10_DECODE_SLICE_MAX_MS] = (
            max(timings.get(T10_DECODE_SLICE_MAX_MS, [0])) if timings.get(T10_DECODE_SLICE_MAX_MS) else 0.0
        )
        kpis[T14_SWEEP_TICK_MAX_MS] = (
            max(timings.get(T14_SWEEP_TICK_MAX_MS, [0])) if timings.get(T14_SWEEP_TICK_MAX_MS) else 0.0
        )
        kpis[T01_FIRST_PROGRESS_TO_FIRST_GROW_MS] = states.get(T01_FIRST_PROGRESS_TO_FIRST_GROW_MS, -1.0)
        kpis[T04_DOWNLOAD_COMPLETE_TO_FINAL_GROW_MS] = states.get(T04_DOWNLOAD_COMPLETE_TO_FINAL_GROW_MS, -1.0)

        t_fg = timestamps.get("first_grow", 0)
        t_lg = timestamps.get("last_grow", 0)
        kpis[T13_FIRST_TO_LAST_GROW_MS] = (t_lg - t_fg) * 1000 if t_lg > t_fg else 0.0

        # State KPIs
        kpis.update({
            k: states.get(k) for k in (
                S01_FINAL_GROW_COUNT, S02_EXPECTED_TOTAL,
                S03_LAST_GROW_RETURN_VALUE,
                S04_STALE_MAX_RETRY_REACHED,
                S05_INFLIGHT_STILL_SET_AT_END,
                S06_DONE_GUARD_KEYS,
                S07_PROGRESSIVE_STILL_ACTIVE_AT_END,
                S08_GENERATION_IDS_SEEN,
                S09_MODALITY, S10_SERIES_NUMBER,
            )
        })

        # Memory KPIs
        kpis[M01_RSS_MB_AT_START] = self._rss_start
        kpis[M02_RSS_MB_AT_PEAK]  = self._rss_peak
        kpis[M03_RSS_MB_AT_END]   = rss_end
        kpis[M04_RSS_DELTA_MB]    = rss_end - self._rss_start
        kpis[M05_GC_OBJECTS_AT_START] = self._gc_start
        kpis[M06_GC_OBJECTS_AT_END]   = gc_end
        kpis[M07_GC_DELTA]            = gc_end - self._gc_start
        kpis[M09_LOADER_REGISTRY_SIZE] = self._registry_size()

        return kpis

    # ── internal helpers ──────────────────────────────────────────────────────

    def _wrap(self, obj: object, method_name: str, spy_factory: Callable) -> None:
        """Replace obj.method_name with a spy that calls spy_factory(original, ...)."""
        orig = getattr(obj, method_name, None)
        if orig is None:
            return
        key = (id(obj), method_name)
        self._originals[key] = (obj, method_name, orig)

        def _wrapped(*args, **kwargs):
            return spy_factory(orig, *args, **kwargs)

        try:
            setattr(obj, method_name, _wrapped)
        except (AttributeError, TypeError):
            pass  # read-only attribute — can't patch; skip silently

    def _restore_all(self) -> None:
        """Remove all spy wrappers (used in teardown)."""
        for key, (obj, method_name, orig) in self._originals.items():
            try:
                setattr(obj, method_name, orig)
            except (AttributeError, TypeError):
                pass
        self._originals.clear()

    def _bump(self, key: str, n: int = 1) -> None:
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + n

    def _record_timing(self, key: str, dur_ms: float) -> None:
        with self._lock:
            self._timings[key].append(dur_ms)

    def _mark_ts(self, name: str) -> None:
        with self._lock:
            self._timestamps[name] = time.monotonic()

    def _has_ts(self, name: str) -> bool:
        with self._lock:
            return name in self._timestamps

    def _compute_t01_latency(self) -> None:
        with self._lock:
            t_fp = self._timestamps.get("first_progress", 0)
            t_fg = self._timestamps.get("first_grow", 0)
            if t_fp and t_fg and t_fg >= t_fp:
                self._states[T01_FIRST_PROGRESS_TO_FIRST_GROW_MS] = (t_fg - t_fp) * 1000

    def _compute_t04_latency(self) -> None:
        with self._lock:
            t_dc = self._timestamps.get("download_complete", 0)
            t_lg = self._timestamps.get("last_grow", 0)
            if t_dc and t_lg and t_lg >= t_dc:
                self._states[T04_DOWNLOAD_COMPLETE_TO_FINAL_GROW_MS] = (t_lg - t_dc) * 1000

    def _registry_size(self) -> int:
        try:
            from modules.viewer.fast import lazy_volume_registry as reg
            return len(reg._REGISTRY)
        except Exception:
            return -1

    def detach(self) -> None:
        """Remove all spy wrappers (call in teardown to avoid test pollution)."""
        self._restore_all()

    def __repr__(self) -> str:
        return f"<KpiCollector counts={dict(self._counts)}>"


def _mean(vals: List[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None
