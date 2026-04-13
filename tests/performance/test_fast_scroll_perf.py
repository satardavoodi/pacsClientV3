"""
FAST Viewer Scroll Performance Benchmark
==========================================
Standalone benchmark that measures the FAST viewer pipeline performance
without launching the full GUI. Tests the hot path:

  pipeline.get_rendered_frame(idx)  →  cache hit / miss timing
  QtSliceViewer.set_image(qimage)   →  pixmap conversion
  QtSliceViewer.paintEvent()        →  QPainter rendering

Usage:
    python tests/performance/test_fast_scroll_perf.py [series_path]

If no series_path is given, uses a synthetic test series.

KPIs collected:
    - cache_hit_ratio: frame cache hit rate
    - decode_p50/p95/p99_ms: decode latency percentiles
    - frame_p50/p95/p99_ms: full frame latency (decode+filter+wl+qimage)
    - paint_p50/p95/p99_ms: paintEvent latency percentiles
    - set_slice_p50/p95/p99_ms: full set_slice latency
    - slow_frame_count: frames >16ms in rapid scroll
    - scroll_fps: actual frames per second during rapid scroll
    - first_image_visible_ms: time to first rendered frame
"""

from __future__ import annotations

import os
import sys
import time
import statistics
import argparse
from pathlib import Path
from typing import List, Optional, Tuple

# Add project root to path
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))


def _percentile(data: List[float], pct: float) -> float:
    """Calculate percentile from sorted data."""
    if not data:
        return 0.0
    data_s = sorted(data)
    k = (len(data_s) - 1) * pct / 100.0
    f = int(k)
    c = min(f + 1, len(data_s) - 1)
    d = k - f
    return data_s[f] + d * (data_s[c] - data_s[f])


class PerfCollector:
    """Collects timing samples for KPI reporting."""

    def __init__(self):
        self.decode_ms: List[float] = []
        self.filter_ms: List[float] = []
        self.wl_ms: List[float] = []
        self.frame_ms: List[float] = []
        self.paint_ms: List[float] = []
        self.set_slice_ms: List[float] = []
        self.cache_hits: int = 0
        self.cache_misses: int = 0
        self.first_image_ms: float = 0.0

    def report(self, label: str = "Benchmark") -> dict:
        """Generate KPI report."""
        total_frames = self.cache_hits + self.cache_misses
        hit_ratio = self.cache_hits / total_frames * 100 if total_frames > 0 else 0.0

        slow_16 = sum(1 for t in self.set_slice_ms if t > 16.0)
        slow_33 = sum(1 for t in self.set_slice_ms if t > 33.0)

        fps = 0.0
        if self.set_slice_ms:
            total_time = sum(self.set_slice_ms) / 1000.0
            fps = len(self.set_slice_ms) / total_time if total_time > 0 else 0.0

        kpis = {
            "label": label,
            "total_frames": total_frames,
            "cache_hit_ratio_pct": round(hit_ratio, 1),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "first_image_ms": round(self.first_image_ms, 2),
            # Decode
            "decode_p50_ms": round(_percentile(self.decode_ms, 50), 2),
            "decode_p95_ms": round(_percentile(self.decode_ms, 95), 2),
            "decode_p99_ms": round(_percentile(self.decode_ms, 99), 2),
            # Filter
            "filter_p50_ms": round(_percentile(self.filter_ms, 50), 2),
            "filter_p95_ms": round(_percentile(self.filter_ms, 95), 2),
            # W/L
            "wl_p50_ms": round(_percentile(self.wl_ms, 50), 2),
            "wl_p95_ms": round(_percentile(self.wl_ms, 95), 2),
            # Full frame (decode+filter+wl+qimage)
            "frame_p50_ms": round(_percentile(self.frame_ms, 50), 2),
            "frame_p95_ms": round(_percentile(self.frame_ms, 95), 2),
            "frame_p99_ms": round(_percentile(self.frame_ms, 99), 2),
            # set_slice (full pipeline)
            "set_slice_p50_ms": round(_percentile(self.set_slice_ms, 50), 2),
            "set_slice_p95_ms": round(_percentile(self.set_slice_ms, 95), 2),
            "set_slice_p99_ms": round(_percentile(self.set_slice_ms, 99), 2),
            # Paint
            "paint_p50_ms": round(_percentile(self.paint_ms, 50), 2),
            "paint_p95_ms": round(_percentile(self.paint_ms, 95), 2),
            # Scroll quality
            "slow_frames_16ms": slow_16,
            "slow_frames_33ms": slow_33,
            "scroll_fps": round(fps, 1),
        }
        return kpis

    def print_report(self, label: str = "Benchmark"):
        kpis = self.report(label)
        print(f"\n{'='*60}")
        print(f"  FAST Viewer Performance Report: {kpis['label']}")
        print(f"{'='*60}")
        print(f"  Total frames:       {kpis['total_frames']}")
        print(f"  Cache hit ratio:    {kpis['cache_hit_ratio_pct']:.1f}%")
        print(f"  First image:        {kpis['first_image_ms']:.1f}ms")
        print()
        print(f"  Decode P50/P95/P99: {kpis['decode_p50_ms']:.1f} / {kpis['decode_p95_ms']:.1f} / {kpis['decode_p99_ms']:.1f} ms")
        print(f"  Filter P50/P95:     {kpis['filter_p50_ms']:.1f} / {kpis['filter_p95_ms']:.1f} ms")
        print(f"  W/L P50/P95:        {kpis['wl_p50_ms']:.1f} / {kpis['wl_p95_ms']:.1f} ms")
        print(f"  Frame P50/P95/P99:  {kpis['frame_p50_ms']:.1f} / {kpis['frame_p95_ms']:.1f} / {kpis['frame_p99_ms']:.1f} ms")
        print(f"  SetSlice P50/P95:   {kpis['set_slice_p50_ms']:.1f} / {kpis['set_slice_p95_ms']:.1f} ms")
        print(f"  Paint P50/P95:      {kpis['paint_p50_ms']:.1f} / {kpis['paint_p95_ms']:.1f} ms")
        print()
        print(f"  Slow frames (>16ms): {kpis['slow_frames_16ms']}")
        print(f"  Slow frames (>33ms): {kpis['slow_frames_33ms']}")
        print(f"  Scroll FPS:          {kpis['scroll_fps']:.0f}")
        print(f"{'='*60}\n")
        return kpis


def benchmark_pipeline_only(series_path: str, n_passes: int = 3) -> dict:
    """
    Benchmark the Lightweight2DPipeline in isolation (no Qt widgets).
    Tests: decode, W/L, filter, QImage creation, cache efficiency.
    """
    from modules.viewer.fast.lightweight_2d_pipeline import (
        Lightweight2DPipeline,
        PipelineConfig,
    )

    collector = PerfCollector()

    config = PipelineConfig()
    pipeline = Lightweight2DPipeline(config=config)
    pipeline.open_series(series_path)
    n_slices = pipeline.slice_count
    if n_slices == 0:
        print(f"ERROR: No DICOM files found in {series_path}")
        return {}

    print(f"Series: {series_path}")
    print(f"Slices: {n_slices}")
    print(f"Passes: {n_passes}")
    print(f"Cache size: pixel={config.pixel_cache_size}, frame={config.frame_cache_size}")

    # --- First image timing ---
    t0 = time.perf_counter()
    frame = pipeline.get_rendered_frame(0)
    collector.first_image_ms = (time.perf_counter() - t0) * 1000.0

    # --- Forward scroll (multiple passes) ---
    for p in range(n_passes):
        label = f"Pass {p+1}"
        for i in range(n_slices):
            t_start = time.perf_counter()
            frame = pipeline.get_rendered_frame(i)
            elapsed = (time.perf_counter() - t_start) * 1000.0

            collector.frame_ms.append(elapsed)
            collector.set_slice_ms.append(elapsed)

            if frame.decode_ms > 0:
                collector.decode_ms.append(frame.decode_ms)
                collector.cache_misses += 1
            else:
                collector.cache_hits += 1

            if frame.filter_ms > 0:
                collector.filter_ms.append(frame.filter_ms)
            if frame.wl_ms > 0:
                collector.wl_ms.append(frame.wl_ms)

    # --- Rapid random scroll (simulates user) ---
    import random
    random.seed(42)
    for _ in range(200):
        idx = random.randint(0, n_slices - 1)
        t_start = time.perf_counter()
        frame = pipeline.get_rendered_frame(idx)
        elapsed = (time.perf_counter() - t_start) * 1000.0
        collector.set_slice_ms.append(elapsed)
        if frame.decode_ms > 0:
            collector.cache_misses += 1
        else:
            collector.cache_hits += 1

    pipeline.close_series()
    return collector.print_report("Pipeline-Only")


def benchmark_with_qt_viewer(series_path: str, n_passes: int = 2) -> dict:
    """
    Benchmark the full Qt rendering pipeline including QPainter paintEvent.
    """
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from modules.viewer.fast.lightweight_2d_pipeline import (
        Lightweight2DPipeline,
        PipelineConfig,
    )
    from modules.viewer.fast.qt_slice_viewer import QtSliceViewer

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    collector = PerfCollector()

    config = PipelineConfig()
    pipeline = Lightweight2DPipeline(config=config)
    pipeline.open_series(series_path)
    n_slices = pipeline.slice_count
    if n_slices == 0:
        print(f"ERROR: No DICOM files found in {series_path}")
        return {}

    viewer = QtSliceViewer()
    viewer.resize(512, 512)
    viewer.show()

    print(f"Series: {series_path}")
    print(f"Slices: {n_slices}")
    print(f"Qt viewer: {viewer.width()}x{viewer.height()}")

    # --- First image ---
    t0 = time.perf_counter()
    frame = pipeline.get_rendered_frame(0)
    viewer.set_image(frame.qimage)
    viewer.repaint()  # Force synchronous paint
    collector.first_image_ms = (time.perf_counter() - t0) * 1000.0

    # --- Sequential scroll ---
    for p in range(n_passes):
        for i in range(n_slices):
            t_start = time.perf_counter()

            # Pipeline
            frame = pipeline.get_rendered_frame(i)
            t_frame = time.perf_counter()

            # Display
            viewer.set_image(frame.qimage)
            viewer.repaint()  # Force synchronous paint
            t_paint = time.perf_counter()

            frame_elapsed = (t_frame - t_start) * 1000.0
            paint_elapsed = (t_paint - t_frame) * 1000.0
            total_elapsed = (t_paint - t_start) * 1000.0

            collector.frame_ms.append(frame_elapsed)
            collector.paint_ms.append(paint_elapsed)
            collector.set_slice_ms.append(total_elapsed)

            if frame.decode_ms > 0:
                collector.decode_ms.append(frame.decode_ms)
                collector.cache_misses += 1
            else:
                collector.cache_hits += 1
            if frame.filter_ms > 0:
                collector.filter_ms.append(frame.filter_ms)
            if frame.wl_ms > 0:
                collector.wl_ms.append(frame.wl_ms)

    viewer.close()
    pipeline.close_series()
    return collector.print_report("Full Qt Pipeline")


def benchmark_synthetic(n_slices: int = 200, image_size: int = 512) -> dict:
    """
    Benchmark with synthetic data — tests W/L, filter, and QImage
    conversion without DICOM decode overhead.
    """
    import numpy as np

    # Avoid heavy VTK import chain by importing the functions directly
    # from their defining modules instead of through __init__.py
    import importlib
    import sys as _sys

    # Pre-populate the fast module with a stub to avoid __init__ importing VTK
    if "modules.viewer.fast" not in _sys.modules:
        import types
        _sys.modules["modules.viewer.fast"] = types.ModuleType("modules.viewer.fast")

    collector = PerfCollector()

    print(f"Synthetic benchmark: {n_slices} slices, {image_size}x{image_size}")

    # Generate random images simulating CT data (int16)
    rng = np.random.RandomState(42)
    slices = [rng.randint(-1024, 3000, size=(image_size, image_size), dtype=np.int16)
              for _ in range(n_slices)]

    ww, wc = 400.0, 40.0

    # Import the functions we're testing — direct module import to avoid VTK chain
    from PacsClient.pacs.patient_tab.utils.dicom_windowing import window_to_uint8
    from PacsClient.pacs.patient_tab.utils.opencv_filter_pipeline import (
        pooyan_filter_center,
        PooyanFilterParams,
    )

    def _window_level_to_uint8(arr, window, level):
        return window_to_uint8(arr, window, level)

    def _apply_opencv_filter_uint8(gray, **kwargs):
        return pooyan_filter_center(gray, PooyanFilterParams(**kwargs) if kwargs else PooyanFilterParams())

    def _numpy_to_qimage_gray(arr, width, height):
        from PySide6.QtGui import QImage
        arr = np.ascontiguousarray(arr)
        return QImage(arr.data, width, height, width, QImage.Format.Format_Grayscale8).copy()

    # --- Benchmark W/L conversion ---
    wl_times = []
    for arr in slices[:50]:
        farr = arr.astype(np.float32)
        t0 = time.perf_counter()
        disp = _window_level_to_uint8(farr, ww, wc)
        wl_times.append((time.perf_counter() - t0) * 1000.0)
    print(f"  W/L P50: {_percentile(wl_times, 50):.2f}ms  P95: {_percentile(wl_times, 95):.2f}ms")

    # --- Benchmark OpenCV filter ---
    filter_times = []
    disp_sample = _window_level_to_uint8(slices[0].astype(np.float32), ww, wc)
    for _ in range(50):
        t0 = time.perf_counter()
        _apply_opencv_filter_uint8(disp_sample)
        filter_times.append((time.perf_counter() - t0) * 1000.0)
    print(f"  Filter P50: {_percentile(filter_times, 50):.2f}ms  P95: {_percentile(filter_times, 95):.2f}ms")

    # --- Benchmark QImage conversion ---
    qimg_times = []
    for _ in range(100):
        t0 = time.perf_counter()
        _numpy_to_qimage_gray(disp_sample, image_size, image_size)
        qimg_times.append((time.perf_counter() - t0) * 1000.0)
    print(f"  QImage P50: {_percentile(qimg_times, 50):.2f}ms  P95: {_percentile(qimg_times, 95):.2f}ms")

    # --- Benchmark full pipeline (W/L + filter + QImage) ---
    for arr in slices:
        t_start = time.perf_counter()
        farr = arr.astype(np.float32)
        t_cast = time.perf_counter()
        disp = _window_level_to_uint8(farr, ww, wc)
        t_wl = time.perf_counter()
        disp = _apply_opencv_filter_uint8(disp)
        t_filt = time.perf_counter()
        qimg = _numpy_to_qimage_gray(disp, image_size, image_size)
        t_end = time.perf_counter()

        collector.wl_ms.append((t_wl - t_cast) * 1000.0)
        collector.filter_ms.append((t_filt - t_wl) * 1000.0)
        collector.frame_ms.append((t_end - t_start) * 1000.0)
        collector.set_slice_ms.append((t_end - t_start) * 1000.0)
        collector.cache_misses += 1

    return collector.print_report("Synthetic (no decode)")


def benchmark_synthetic_fast_scroll(n_slices: int = 200, image_size: int = 512) -> dict:
    """
    Benchmark simulating fast scroll (filter skipped).
    This measures the real hot-path during active scrolling.
    """
    import numpy as np
    import sys as _sys

    if "modules.viewer.fast" not in _sys.modules:
        import types
        _sys.modules["modules.viewer.fast"] = types.ModuleType("modules.viewer.fast")

    collector = PerfCollector()
    print(f"Fast-scroll benchmark: {n_slices} slices, {image_size}x{image_size} (filter SKIPPED)")

    rng = np.random.RandomState(42)
    slices = [rng.randint(-1024, 3000, size=(image_size, image_size), dtype=np.int16)
              for _ in range(n_slices)]

    ww, wc = 400.0, 40.0

    from PacsClient.pacs.patient_tab.utils.dicom_windowing import window_to_uint8

    def _numpy_to_qimage_gray(arr, width, height):
        from PySide6.QtGui import QImage
        arr = np.ascontiguousarray(arr)
        qimg = QImage(arr.data, width, height, width, QImage.Format.Format_Grayscale8)
        qimg._np_buffer = arr
        return qimg

    # Fast scroll: W/L + QImage only (no filter)
    for arr in slices:
        t_start = time.perf_counter()
        disp = window_to_uint8(arr, ww, wc)  # int16 LUT path
        t_wl = time.perf_counter()
        qimg = _numpy_to_qimage_gray(disp, image_size, image_size)
        t_end = time.perf_counter()

        collector.wl_ms.append((t_wl - t_start) * 1000.0)
        collector.frame_ms.append((t_end - t_start) * 1000.0)
        collector.set_slice_ms.append((t_end - t_start) * 1000.0)
        collector.cache_misses += 1

    return collector.print_report("Fast-Scroll (filter skipped)")


def find_test_series() -> Optional[str]:
    """Find a DICOM series in user_data for testing."""
    from PacsClient.utils.config import SOURCE_PATH
    src = Path(SOURCE_PATH)
    if not src.exists():
        return None
    # Walk studies looking for a series with enough files
    for study_dir in src.iterdir():
        if not study_dir.is_dir():
            continue
        for series_dir in study_dir.iterdir():
            if not series_dir.is_dir():
                continue
            dcm_count = sum(1 for f in series_dir.iterdir()
                           if f.is_file() and f.suffix.lower() in {'.dcm', '.dicom'})
            if dcm_count >= 20:
                return str(series_dir)
    return None


def main():
    parser = argparse.ArgumentParser(description="FAST Viewer Performance Benchmark")
    parser.add_argument("series_path", nargs="?", help="Path to DICOM series directory")
    parser.add_argument("--synthetic", action="store_true", help="Run synthetic benchmark only")
    parser.add_argument("--fast-scroll", action="store_true", help="Simulate fast scroll (filter skipped)")
    parser.add_argument("--pipeline", action="store_true", help="Pipeline-only (no Qt widget)")
    parser.add_argument("--full", action="store_true", help="Full Qt pipeline benchmark")
    parser.add_argument("--passes", type=int, default=3, help="Number of scroll passes")
    parser.add_argument("--all", action="store_true", help="Run all benchmarks")
    args = parser.parse_args()

    results = {}

    # Always run synthetic
    if args.synthetic or args.all or not args.series_path:
        results["synthetic"] = benchmark_synthetic()

    if getattr(args, 'fast_scroll', False) or args.all:
        results["fast_scroll"] = benchmark_synthetic_fast_scroll()

    series_path = args.series_path
    if not series_path and not args.synthetic:
        series_path = find_test_series()
        if series_path:
            print(f"Auto-detected series: {series_path}")
        else:
            print("No DICOM series found. Use --synthetic or provide a path.")
            if not results:
                return

    if series_path:
        if args.pipeline or args.all or (not args.full and not args.synthetic):
            results["pipeline"] = benchmark_pipeline_only(series_path, args.passes)
        if args.full or args.all:
            results["full_qt"] = benchmark_with_qt_viewer(series_path, min(args.passes, 2))

    # Summary comparison
    if len(results) > 1:
        print("\n" + "="*60)
        print("  COMPARISON SUMMARY")
        print("="*60)
        for name, kpis in results.items():
            if kpis:
                print(f"  {name:20s}: FPS={kpis.get('scroll_fps',0):5.0f}  "
                      f"P95={kpis.get('set_slice_p95_ms',0):6.1f}ms  "
                      f"Cache={kpis.get('cache_hit_ratio_pct',0):5.1f}%")
        print("="*60)


if __name__ == "__main__":
    main()
