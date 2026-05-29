"""
B3.3 Stack-Drag KPI Scenario
==============================
Compares stack-drag performance WITH and WITHOUT fast_interaction.

Runs two scenarios on the same synthetic series:
  A) fast_interaction=False (old behavior — full filter on every step)
  B) fast_interaction=True  (B3.3 — filter skipped, settle at end)

Each scenario scrolls through the series with a stack-drag pattern
(4 steps per event, 30 events = 120 frames).

Usage:
  python tests/performance/test_b33_kpi_scenario.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from modules.viewer.fast.perf_metrics import PerfMetrics
from tests.performance.perf_helpers import (
    make_dicom_series_on_disk,
    scroll_stack_drag,
    GILContentionSimulator,
)


def _make_pipeline(series_dir: str, prefetch_workers: int = 4):
    from modules.viewer.fast.lightweight_2d_pipeline import (
        Lightweight2DPipeline,
        PipelineConfig,
    )
    cfg = PipelineConfig(
        pixel_cache_size=96,
        frame_cache_size=96,
        prefetch_radius=10,
        prefetch_workers=prefetch_workers,
    )
    pipeline = Lightweight2DPipeline(config=cfg)
    pipeline.open_series(series_dir)
    return pipeline


def _run_scenario(pipeline, pattern: List[int], fast_interaction: bool) -> Dict:
    pm = PerfMetrics.get()
    pm.enable()

    timings: List[float] = []

    # First image
    t_first = time.perf_counter()
    pipeline.set_fast_interaction(False)
    pipeline.get_rendered_frame(0)
    first_ms = (time.perf_counter() - t_first) * 1000.0

    # Scroll phase
    pipeline.set_fast_interaction(fast_interaction)
    for idx in pattern:
        t0 = time.perf_counter()
        frame = pipeline.get_rendered_frame(idx)
        elapsed = (time.perf_counter() - t0) * 1000.0
        timings.append(elapsed)
        pm.record_set_slice(elapsed)
        if frame.decode_ms > 0:
            pm.record_foreground_wait(frame.decode_ms)

    # Settle (re-render with filter)
    pipeline.set_fast_interaction(False)
    t_settle = time.perf_counter()
    pipeline.rerender_current_filtered()
    settle_ms = (time.perf_counter() - t_settle) * 1000.0

    timings.sort()
    n = len(timings)
    slow_16 = sum(1 for t in timings if t > 16.0)
    slow_33 = sum(1 for t in timings if t > 33.0)

    snap = pm.snapshot()

    return {
        "frames": n,
        "P50": timings[n // 2] if n else 0,
        "P95": timings[int(n * 0.95)] if n else 0,
        "max": timings[-1] if n else 0,
        "slow>16ms": slow_16,
        "slow>33ms": slow_33,
        "total_ms": sum(timings),
        "first_ms": first_ms,
        "settle_ms": settle_ms,
        "cache_hit": snap.get("cache_hit_ratio_pct", 0),
    }


def main():
    n_slices = 100
    steps_per_event = 4
    events = 25
    n_runs = 2

    with tempfile.TemporaryDirectory() as td:
        series_dir = Path(td) / "series"
        files = make_dicom_series_on_disk(series_dir, n=n_slices, rows=128, cols=128)
        pattern = scroll_stack_drag(n_slices, steps_per_event=steps_per_event, events=events)

        print(f"\n{'='*70}")
        print(f"B3.3 Stack-Drag KPI Scenario")
        print(f"Series: {n_slices} slices, 128x128")
        print(f"Pattern: {steps_per_event} steps/event × {events} events = {len(pattern)} frames")
        print(f"Runs: {n_runs}")
        print(f"{'='*70}")

        for run_idx in range(n_runs):
            print(f"\n--- Run {run_idx + 1} ---")

            for label, fast in [("A: fast_interaction=False (old)", False),
                                ("B: fast_interaction=True  (B3.3)", True)]:
                pipeline = _make_pipeline(str(series_dir))
                PerfMetrics.get().reset()
                result = _run_scenario(pipeline, pattern, fast)
                pipeline.close_series()

                print(f"\n  {label}:")
                print(f"    P50={result['P50']:.2f}ms  P95={result['P95']:.2f}ms  max={result['max']:.2f}ms")
                print(f"    slow>16ms={result['slow>16ms']}  slow>33ms={result['slow>33ms']}")
                print(f"    total={result['total_ms']:.1f}ms  settle={result['settle_ms']:.2f}ms")
                print(f"    cache_hit={result['cache_hit']:.1%}")

            # With GIL contention
            for label, fast in [("C: fast=False + GIL contention (old)", False),
                                ("D: fast=True  + GIL contention (B3.3)", True)]:
                pipeline = _make_pipeline(str(series_dir))
                PerfMetrics.get().reset()
                gil = GILContentionSimulator(files, workers=4)
                gil.start()
                try:
                    result = _run_scenario(pipeline, pattern, fast)
                finally:
                    gil.stop()
                pipeline.close_series()

                print(f"\n  {label}:")
                print(f"    P50={result['P50']:.2f}ms  P95={result['P95']:.2f}ms  max={result['max']:.2f}ms")
                print(f"    slow>16ms={result['slow>16ms']}  slow>33ms={result['slow>33ms']}")
                print(f"    total={result['total_ms']:.1f}ms  settle={result['settle_ms']:.2f}ms")
                print(f"    cache_hit={result['cache_hit']:.1%}")

        print(f"\n{'='*70}")
        print("Expected: B < A and D < C (fast_interaction reduces per-frame cost)")
        print(f"{'='*70}")


if __name__ == "__main__":
    main()
