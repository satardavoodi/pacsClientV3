"""
B2.5 Performance Metrics Collector
===================================
Lightweight, opt-in instrumentation for concurrent-load KPI capture.

Enable:   PerfMetrics.get().enable()
Disable:  PerfMetrics.get().disable()
Snapshot: PerfMetrics.get().snapshot() → dict
Reset:    PerfMetrics.get().reset()

When disabled, all record_*() methods return immediately (single bool check).
Overhead when enabled: one lock acquire per record call (~0.1µs on Windows).

Thread-safe. All public methods are safe to call from any thread.

KPI schema matches FAST_VIEWER_KPI_CATALOG.md.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional


def _percentile(data: List[float], pct: float) -> float:
    """Compute percentile from unsorted data. Returns 0.0 for empty list."""
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * pct / 100.0
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (k - f) * (s[c] - s[f])


class PerfMetrics:
    """Singleton performance metrics collector for B2.5 scenario tests.

    Designed for low overhead:
    - ``enabled`` is a bare bool — GIL-atomic read, no lock needed for the
      fast exit check in every ``record_*`` method.
    - Lock is only acquired when actually storing data.
    """

    _instance: Optional["PerfMetrics"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def get(cls) -> "PerfMetrics":
        """Return the singleton instance (created on first call)."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._enabled: bool = False
        self._lock = threading.Lock()
        self._reset_unlocked()

    # ── Lifecycle ─────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        with self._lock:
            self._reset_unlocked()
            self._enabled = True
            self._start_time_s = time.monotonic()

    def disable(self) -> None:
        self._enabled = False

    def reset(self) -> None:
        with self._lock:
            self._reset_unlocked()
            if self._enabled:
                self._start_time_s = time.monotonic()

    # ── Recording methods (fast exit when disabled) ───────────────────

    def record_set_slice(self, ms: float) -> None:
        """Record one set_slice call latency (full pipeline: decode+wl+paint)."""
        if not self._enabled:
            return
        with self._lock:
            self._set_slice_ms.append(ms)
            if ms > 33.0:
                self._slow_33ms += 1
                self._slow_16ms += 1
            elif ms > 16.0:
                self._slow_16ms += 1

    def record_decode(self, ms: float) -> None:
        """Record one slice decode latency."""
        if not self._enabled:
            return
        with self._lock:
            self._decode_ms.append(ms)

    def record_frame_render(self, ms: float) -> None:
        """Record full frame render latency (decode+wl+filter+qimage)."""
        if not self._enabled:
            return
        with self._lock:
            self._frame_render_ms.append(ms)

    def record_paint(self, ms: float) -> None:
        """Record QPainter paint latency."""
        if not self._enabled:
            return
        with self._lock:
            self._paint_ms.append(ms)

    def record_wl(self, ms: float) -> None:
        """Record window/level conversion latency."""
        if not self._enabled:
            return
        with self._lock:
            self._wl_ms.append(ms)

    def record_filter(self, ms: float) -> None:
        """Record OpenCV filter apply latency."""
        if not self._enabled:
            return
        with self._lock:
            self._filter_ms.append(ms)

    def record_foreground_wait(self, ms: float) -> None:
        """Record foreground (main-thread) decode wait on cache miss."""
        if not self._enabled:
            return
        with self._lock:
            self._foreground_wait_ms.append(ms)

    def record_queue_depths(self, decode_pending: int, frame_pending: int) -> None:
        """Record instantaneous queue depths (sampled per set_slice call)."""
        if not self._enabled:
            return
        with self._lock:
            self._decode_queue_depth.append(decode_pending)
            self._frame_queue_depth.append(frame_pending)

    def record_cache_hit(self) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._cache_hits += 1

    def record_cache_miss(self) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._cache_misses += 1

    def record_prefetch_submitted(self) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._prefetch_submitted += 1

    def record_prefetch_completed(self) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._prefetch_completed += 1

    def record_stale_task(self) -> None:
        """Increment stale prefetch counter (task completed for irrelevant slice)."""
        if not self._enabled:
            return
        with self._lock:
            self._stale_tasks += 1

    def record_cancelled_task(self) -> None:
        """Increment cancelled prefetch counter (dropped before useful work)."""
        if not self._enabled:
            return
        with self._lock:
            self._cancelled_tasks += 1

    def record_first_image(self, ms: float) -> None:
        if not self._enabled:
            return
        with self._lock:
            if self._first_image_ms == 0.0:
                self._first_image_ms = ms

    def record_longest_ui_gap(self, ms: float) -> None:
        """Track the longest gap between consecutive set_slice completions."""
        if not self._enabled:
            return
        with self._lock:
            if ms > self._longest_ui_gap_ms:
                self._longest_ui_gap_ms = ms

    # ── Snapshot ──────────────────────────────────────────────────────

    def snapshot(self) -> Dict:
        """Return all KPIs as a flat dict. Safe to call from any thread."""
        with self._lock:
            total_tasks = max(self._prefetch_submitted, 1)
            total_cache = max(self._cache_hits + self._cache_misses, 1)
            elapsed_s = max(time.monotonic() - self._start_time_s, 0.001) if self._start_time_s else 1.0
            n_frames = len(self._set_slice_ms)
            dq = [float(x) for x in self._decode_queue_depth]
            fq = [float(x) for x in self._frame_queue_depth]

            return {
                # --- Component KPIs (Layer 1) ---
                "set_slice_p50_ms": round(_percentile(self._set_slice_ms, 50), 2),
                "set_slice_p95_ms": round(_percentile(self._set_slice_ms, 95), 2),
                "set_slice_p99_ms": round(_percentile(self._set_slice_ms, 99), 2),
                "set_slice_max_ms": round(max(self._set_slice_ms) if self._set_slice_ms else 0.0, 2),
                "decode_p50_ms": round(_percentile(self._decode_ms, 50), 2),
                "decode_p95_ms": round(_percentile(self._decode_ms, 95), 2),
                "frame_render_p50_ms": round(_percentile(self._frame_render_ms, 50), 2),
                "frame_render_p95_ms": round(_percentile(self._frame_render_ms, 95), 2),
                "wl_p50_ms": round(_percentile(self._wl_ms, 50), 2),
                "wl_p95_ms": round(_percentile(self._wl_ms, 95), 2),
                "filter_p50_ms": round(_percentile(self._filter_ms, 50), 2),
                "paint_p95_ms": round(_percentile(self._paint_ms, 95), 2),

                # --- System KPIs (Layer 2) ---
                # Queue depths
                "decode_queue_depth_max": max(self._decode_queue_depth) if self._decode_queue_depth else 0,
                "decode_queue_depth_p95": int(_percentile(dq, 95)),
                "frame_queue_depth_max": max(self._frame_queue_depth) if self._frame_queue_depth else 0,
                "frame_queue_depth_p95": int(_percentile(fq, 95)),
                # Task lifecycle
                "stale_task_ratio": round(self._stale_tasks / total_tasks, 4),
                "cancelled_task_ratio": round(self._cancelled_tasks / total_tasks, 4),
                "stale_task_count": self._stale_tasks,
                "cancelled_task_count": self._cancelled_tasks,
                "prefetch_submitted": self._prefetch_submitted,
                "prefetch_completed": self._prefetch_completed,
                # Cache
                "cache_hit_ratio_pct": round((self._cache_hits / total_cache) * 100, 1),
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                # Foreground wait
                "foreground_wait_p50_ms": round(_percentile(self._foreground_wait_ms, 50), 2),
                "foreground_wait_p95_ms": round(_percentile(self._foreground_wait_ms, 95), 2),
                "foreground_wait_max_ms": round(max(self._foreground_wait_ms) if self._foreground_wait_ms else 0.0, 2),

                # --- Derived / aggregate ---
                "slow_frame_count_16ms": self._slow_16ms,
                "slow_frame_count_33ms": self._slow_33ms,
                "total_frames": n_frames,
                "first_image_ms": round(self._first_image_ms, 2),
                "longest_ui_gap_ms": round(self._longest_ui_gap_ms, 2),
                "effective_fps": round(n_frames / elapsed_s, 1) if n_frames else 0.0,
                "capture_duration_s": round(elapsed_s, 2),
            }

    # ── Pretty printer ────────────────────────────────────────────────

    def print_report(self, label: str = "B2.5 Baseline") -> Dict:
        """Print a formatted KPI report and return the snapshot dict."""
        kpis = self.snapshot()
        lines = [
            "",
            "=" * 72,
            f"  {label}  ({kpis['total_frames']} frames, {kpis['capture_duration_s']:.1f}s)",
            "=" * 72,
            "",
            "  Component KPIs (Layer 1):",
            f"    set_slice  P50={kpis['set_slice_p50_ms']:.2f}  P95={kpis['set_slice_p95_ms']:.2f}  P99={kpis['set_slice_p99_ms']:.2f}  max={kpis['set_slice_max_ms']:.2f} ms",
            f"    decode     P50={kpis['decode_p50_ms']:.2f}  P95={kpis['decode_p95_ms']:.2f} ms",
            f"    frame      P50={kpis['frame_render_p50_ms']:.2f}  P95={kpis['frame_render_p95_ms']:.2f} ms",
            f"    W/L        P50={kpis['wl_p50_ms']:.2f}  P95={kpis['wl_p95_ms']:.2f} ms",
            f"    filter     P50={kpis['filter_p50_ms']:.2f} ms",
            f"    paint      P95={kpis['paint_p95_ms']:.2f} ms",
            f"    cache hit  {kpis['cache_hit_ratio_pct']:.1f}%  ({kpis['cache_hits']} / {kpis['cache_hits'] + kpis['cache_misses']})",
            "",
            "  System KPIs (Layer 2):",
            f"    fg wait    P50={kpis['foreground_wait_p50_ms']:.2f}  P95={kpis['foreground_wait_p95_ms']:.2f}  max={kpis['foreground_wait_max_ms']:.2f} ms",
            f"    decode Q   max={kpis['decode_queue_depth_max']}  P95={kpis['decode_queue_depth_p95']}",
            f"    frame Q    max={kpis['frame_queue_depth_max']}  P95={kpis['frame_queue_depth_p95']}",
            f"    stale      {kpis['stale_task_count']} ({kpis['stale_task_ratio']:.2%} of {kpis['prefetch_submitted']} submitted)",
            f"    cancelled  {kpis['cancelled_task_count']} ({kpis['cancelled_task_ratio']:.2%} of {kpis['prefetch_submitted']} submitted)",
            f"    prefetch   submitted={kpis['prefetch_submitted']}  completed={kpis['prefetch_completed']}",
            "",
            "  Scroll quality:",
            f"    slow >16ms: {kpis['slow_frame_count_16ms']}   slow >33ms: {kpis['slow_frame_count_33ms']}",
            f"    FPS: {kpis['effective_fps']:.0f}",
            f"    first image: {kpis['first_image_ms']:.1f}ms",
            f"    longest UI gap: {kpis['longest_ui_gap_ms']:.1f}ms",
            "",
            "=" * 72,
        ]
        print("\n".join(lines))
        return kpis

    # ── Internal ──────────────────────────────────────────────────────

    def _reset_unlocked(self) -> None:
        """Reset all counters. Caller must hold ``_lock``."""
        # Component latencies
        self._set_slice_ms: List[float] = []
        self._decode_ms: List[float] = []
        self._frame_render_ms: List[float] = []
        self._paint_ms: List[float] = []
        self._wl_ms: List[float] = []
        self._filter_ms: List[float] = []
        # System — queue depth snapshots
        self._decode_queue_depth: List[int] = []
        self._frame_queue_depth: List[int] = []
        # System — task lifecycle
        self._prefetch_submitted: int = 0
        self._prefetch_completed: int = 0
        self._stale_tasks: int = 0
        self._cancelled_tasks: int = 0
        # System — foreground wait
        self._foreground_wait_ms: List[float] = []
        # Cache
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        # Scroll quality
        self._slow_16ms: int = 0
        self._slow_33ms: int = 0
        # First image
        self._first_image_ms: float = 0.0
        # Longest UI gap
        self._longest_ui_gap_ms: float = 0.0
        # Timing
        self._start_time_s: float = 0.0
