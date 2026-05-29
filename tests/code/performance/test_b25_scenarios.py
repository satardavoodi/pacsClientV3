"""
B2.5 Concurrent-Load Baseline Scenarios
=========================================
Runnable scenario suite that captures Layer 1 + Layer 2 KPIs under
controlled concurrent workloads.

Scenarios (from FAST_VIEWER_TEST_SCENARIOS.md):
  S1  Viewer-only baseline (no contention)
  S2  Viewer + simulated download (GIL contention)
  S3  Viewer + download + filter settle
  S4  Rapid scroll burst
  S5  Rapid direction reversal (stale work exposure)
  S6  Low-end profile simulation (2 workers)
  S7  Repeated open/close cycles (leak detection)

Usage:
  python tests/performance/test_b25_scenarios.py               # all scenarios
  python tests/performance/test_b25_scenarios.py S1 S2          # specific scenarios
  python tests/performance/test_b25_scenarios.py --slices 200   # large series
  python tests/performance/test_b25_scenarios.py --json         # JSON output

KPI output: printed + optional JSON file in tests/performance/b25_output/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

# Project root
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from modules.viewer.fast.perf_metrics import PerfMetrics

from tests.performance.perf_helpers import (
    CPULoadSimulator,
    GILContentionSimulator,
    ProcessSampler,
    make_dicom_series_on_disk,
    scroll_direction_reversal,
    scroll_forward,
    scroll_rapid_burst,
    scroll_random,
)


# ── Pipeline factory ─────────────────────────────────────────────────────────

def _make_pipeline(series_dir: str, prefetch_workers: int = 4, prefetch_radius: int = 20):
    """Create and open a Lightweight2DPipeline for the given series."""
    from modules.viewer.fast.lightweight_2d_pipeline import (
        Lightweight2DPipeline,
        PipelineConfig,
    )
    cfg = PipelineConfig(
        pixel_cache_size=96,
        frame_cache_size=96,
        prefetch_radius=prefetch_radius,
        prefetch_workers=prefetch_workers,
    )
    pipeline = Lightweight2DPipeline(config=cfg)
    pipeline.open_series(series_dir)
    return pipeline


def _run_scroll_pattern(pipeline, pattern: List[int], fast_interaction: bool = True) -> None:
    """Scroll through the given slice pattern, recording PerfMetrics."""
    pm = PerfMetrics.get()
    prev_end = time.perf_counter()
    for idx in pattern:
        t0 = time.perf_counter()
        pipeline.set_fast_interaction(fast_interaction)
        frame = pipeline.get_rendered_frame(idx)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        pm.record_set_slice(elapsed_ms)
        if frame.decode_ms > 0:
            pm.record_foreground_wait(frame.decode_ms)
            pm.record_decode(frame.decode_ms)
        pm.record_frame_render(frame.total_ms)
        if frame.wl_ms > 0:
            pm.record_wl(frame.wl_ms)
        if frame.filter_ms > 0:
            pm.record_filter(frame.filter_ms)
        # UI gap tracking
        gap_ms = (t0 - prev_end) * 1000.0
        pm.record_longest_ui_gap(gap_ms)
        prev_end = time.perf_counter()


# ── Scenarios ─────────────────────────────────────────────────────────────────

def scenario_s1_viewer_only(series_dir: str, n_slices: int) -> Dict:
    """S1: Viewer-only baseline — no concurrent load."""
    pm = PerfMetrics.get()
    pm.enable()
    sampler = ProcessSampler(interval_s=0.25)
    sampler.start()

    pipeline = _make_pipeline(series_dir)

    # First image timing
    t_first = time.perf_counter()
    pipeline.get_rendered_frame(0)
    pm.record_first_image((time.perf_counter() - t_first) * 1000.0)

    # Forward scroll (warm cache on pass 1, measure on pass 2+)
    for _ in range(3):
        _run_scroll_pattern(pipeline, scroll_forward(n_slices), fast_interaction=True)

    # Random access
    _run_scroll_pattern(pipeline, scroll_random(n_slices, count=100), fast_interaction=True)

    proc = sampler.stop()
    kpis = pm.snapshot()
    kpis["process"] = proc
    pipeline.close_series()
    pm.disable()
    return kpis


def scenario_s2_viewer_plus_download(series_dir: str, n_slices: int, dicom_files) -> Dict:
    """S2: Viewer + simulated download GIL contention."""
    pm = PerfMetrics.get()
    pm.enable()
    sampler = ProcessSampler(interval_s=0.25)
    sampler.start()

    # Start GIL contention (simulates decode workers from download path)
    sim = GILContentionSimulator(dicom_files, workers=4)
    sim.start()

    pipeline = _make_pipeline(series_dir)
    time.sleep(0.2)  # let contention threads warm up

    # First image under contention
    t_first = time.perf_counter()
    pipeline.get_rendered_frame(0)
    pm.record_first_image((time.perf_counter() - t_first) * 1000.0)

    # Scroll under contention
    for _ in range(3):
        _run_scroll_pattern(pipeline, scroll_forward(n_slices), fast_interaction=True)

    decode_count = sim.stop()
    proc = sampler.stop()
    kpis = pm.snapshot()
    kpis["process"] = proc
    kpis["contention_decodes"] = decode_count
    pipeline.close_series()
    pm.disable()
    return kpis


def scenario_s3_viewer_download_filter(series_dir: str, n_slices: int, dicom_files) -> Dict:
    """S3: Viewer + download + filter settle (scroll-stop recovery)."""
    pm = PerfMetrics.get()
    pm.enable()
    sampler = ProcessSampler(interval_s=0.25)
    sampler.start()

    sim = GILContentionSimulator(dicom_files, workers=4)
    sim.start()

    pipeline = _make_pipeline(series_dir)
    time.sleep(0.2)

    # Fast scroll burst (filter skipped)
    _run_scroll_pattern(pipeline, scroll_forward(n_slices), fast_interaction=True)

    # Scroll-stop: re-render with filter (measures recovery)
    pipeline.set_fast_interaction(False)
    t_recover = time.perf_counter()
    pipeline.rerender_current_filtered()
    recovery_ms = (time.perf_counter() - t_recover) * 1000.0

    # Another burst
    _run_scroll_pattern(pipeline, scroll_forward(n_slices), fast_interaction=True)

    # Second recovery
    pipeline.set_fast_interaction(False)
    t_recover2 = time.perf_counter()
    pipeline.rerender_current_filtered()
    recovery_ms_2 = (time.perf_counter() - t_recover2) * 1000.0

    sim.stop()
    proc = sampler.stop()
    kpis = pm.snapshot()
    kpis["process"] = proc
    kpis["recovery_after_scroll_ms"] = round(recovery_ms, 2)
    kpis["recovery_after_scroll_ms_2"] = round(recovery_ms_2, 2)
    pipeline.close_series()
    pm.disable()
    return kpis


def scenario_s4_rapid_burst(series_dir: str, n_slices: int) -> Dict:
    """S4: Rapid scroll burst — hard-interactive stability test."""
    pm = PerfMetrics.get()
    pm.enable()
    sampler = ProcessSampler(interval_s=0.25)
    sampler.start()

    pipeline = _make_pipeline(series_dir)

    # Warm cache
    _run_scroll_pattern(pipeline, scroll_forward(n_slices), fast_interaction=True)
    pm.reset()

    # Rapid burst x3
    for _ in range(3):
        burst = scroll_rapid_burst(n_slices, burst_length=min(n_slices, 100))
        _run_scroll_pattern(pipeline, burst, fast_interaction=True)

    proc = sampler.stop()
    kpis = pm.snapshot()
    kpis["process"] = proc
    pipeline.close_series()
    pm.disable()
    return kpis


def scenario_s5_direction_reversal(series_dir: str, n_slices: int) -> Dict:
    """S5: Rapid direction reversal — exposes stale work and cancellation weakness."""
    pm = PerfMetrics.get()
    pm.enable()
    sampler = ProcessSampler(interval_s=0.25)
    sampler.start()

    pipeline = _make_pipeline(series_dir)

    # Warm a strip
    _run_scroll_pattern(pipeline, scroll_forward(min(30, n_slices)), fast_interaction=True)
    pm.reset()

    # Rapid reversals
    pattern = scroll_direction_reversal(n_slices, cycles=20, segment=8)
    _run_scroll_pattern(pipeline, pattern, fast_interaction=True)

    proc = sampler.stop()
    kpis = pm.snapshot()
    kpis["process"] = proc
    pipeline.close_series()
    pm.disable()
    return kpis


def scenario_s6_lowend_simulation(series_dir: str, n_slices: int, dicom_files) -> Dict:
    """S6: Low-end profile — 2 decode workers, download contention."""
    pm = PerfMetrics.get()
    pm.enable()
    sampler = ProcessSampler(interval_s=0.25)
    sampler.start()

    # Simulate low-end: fewer workers, contention
    sim = GILContentionSimulator(dicom_files, workers=2)
    sim.start()

    pipeline = _make_pipeline(series_dir, prefetch_workers=2, prefetch_radius=6)
    time.sleep(0.2)

    for _ in range(3):
        _run_scroll_pattern(pipeline, scroll_forward(n_slices), fast_interaction=True)

    sim.stop()
    proc = sampler.stop()
    kpis = pm.snapshot()
    kpis["process"] = proc
    pipeline.close_series()
    pm.disable()
    return kpis


def scenario_s7_open_close_cycles(n_slices: int, cycles: int = 20) -> Dict:
    """S7: Repeated open/close — leak and degradation detection."""
    pm = PerfMetrics.get()
    pm.enable()
    sampler = ProcessSampler(interval_s=0.5)
    sampler.start()

    set_slice_times_per_cycle: List[float] = []

    for c in range(cycles):
        with tempfile.TemporaryDirectory(prefix=f"b25_s7_{c}_") as td:
            series_dir = Path(td) / "series"
            make_dicom_series_on_disk(series_dir, n=n_slices, rows=64, cols=64)
            pipeline = _make_pipeline(str(series_dir))
            t0 = time.perf_counter()
            _run_scroll_pattern(pipeline, scroll_forward(n_slices), fast_interaction=True)
            cycle_ms = (time.perf_counter() - t0) * 1000.0
            set_slice_times_per_cycle.append(cycle_ms / n_slices)
            pipeline.close_series()

    proc = sampler.stop()
    kpis = pm.snapshot()
    kpis["process"] = proc
    kpis["per_cycle_avg_ms"] = [round(v, 2) for v in set_slice_times_per_cycle]
    # Check for degradation trend
    if len(set_slice_times_per_cycle) >= 4:
        first_q = sum(set_slice_times_per_cycle[:cycles // 4]) / (cycles // 4)
        last_q = sum(set_slice_times_per_cycle[-(cycles // 4):]) / (cycles // 4)
        kpis["degradation_ratio"] = round(last_q / first_q if first_q > 0 else 1.0, 3)
    pm.disable()
    return kpis


# ── Interference index calculation ───────────────────────────────────────────

def compute_download_interference_index(s1_kpis: Dict, s2_kpis: Dict) -> float:
    """Compute download interference index: % increase in P95 set_slice under download."""
    baseline = s1_kpis.get("set_slice_p95_ms", 0.001)
    with_dl = s2_kpis.get("set_slice_p95_ms", 0.001)
    if baseline <= 0:
        return 0.0
    return round(((with_dl - baseline) / baseline) * 100.0, 1)


# ── Runner ────────────────────────────────────────────────────────────────────

SCENARIOS = {
    "S1": ("Viewer-only baseline", scenario_s1_viewer_only),
    "S2": ("Viewer + download (GIL contention)", scenario_s2_viewer_plus_download),
    "S3": ("Viewer + download + filter settle", scenario_s3_viewer_download_filter),
    "S4": ("Rapid scroll burst", scenario_s4_rapid_burst),
    "S5": ("Direction reversal (stale work)", scenario_s5_direction_reversal),
    "S6": ("Low-end simulation", scenario_s6_lowend_simulation),
    "S7": ("Open/close cycles (leak test)", scenario_s7_open_close_cycles),
}


def run_scenarios(
    selected: Optional[List[str]] = None,
    n_slices: int = 50,
    image_size: int = 64,
    output_json: bool = False,
) -> Dict[str, Dict]:
    """Run selected (or all) B2.5 scenarios and return KPI dicts."""
    if selected is None:
        selected = list(SCENARIOS.keys())

    # Create shared synthetic series
    tmp = Path(tempfile.mkdtemp(prefix="b25_"))
    series_dir = tmp / "series"
    files = make_dicom_series_on_disk(series_dir, n=n_slices, rows=image_size, cols=image_size)

    print(f"\nB2.5 Concurrent-Load Baseline")
    print(f"Series: {n_slices} slices, {image_size}x{image_size}")
    print(f"Scenarios: {', '.join(selected)}")
    print(f"Temp dir: {tmp}\n")

    results: Dict[str, Dict] = {}
    pm = PerfMetrics.get()

    for sid in selected:
        if sid not in SCENARIOS:
            print(f"  SKIP unknown scenario: {sid}")
            continue
        label, func = SCENARIOS[sid]
        print(f"  Running {sid}: {label} ...", end=" ", flush=True)
        t0 = time.perf_counter()

        try:
            if sid in ("S2", "S3", "S6"):
                kpis = func(str(series_dir), n_slices, files)
            elif sid == "S7":
                kpis = func(n_slices, cycles=20)
            else:
                kpis = func(str(series_dir), n_slices)

            elapsed = time.perf_counter() - t0
            print(f"done ({elapsed:.1f}s)")
            results[sid] = kpis
            pm.print_report(f"{sid}: {label}")

        except Exception as exc:
            elapsed = time.perf_counter() - t0
            print(f"FAILED ({elapsed:.1f}s): {exc}")
            results[sid] = {"error": str(exc)}

    # Derived: download interference index
    if "S1" in results and "S2" in results and "error" not in results.get("S2", {}):
        dii = compute_download_interference_index(results["S1"], results["S2"])
        results["download_interference_index"] = dii
        print(f"\n  Download Interference Index: {dii:.1f}%")

    # Summary table
    print("\n" + "=" * 80)
    print(f"  B2.5 BASELINE SUMMARY ({n_slices} slices, {image_size}x{image_size})")
    print("=" * 80)
    print(f"  {'Scenario':<35} {'P50':>8} {'P95':>8} {'max':>8} {'slow>16':>8} {'Q-depth':>8} {'stale':>6}")
    print(f"  {'-'*35} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*6}")
    for sid in selected:
        if sid not in results or "error" in results[sid]:
            continue
        k = results[sid]
        print(
            f"  {sid + ': ' + SCENARIOS[sid][0]:<35} "
            f"{k.get('set_slice_p50_ms', 0):>7.2f} "
            f"{k.get('set_slice_p95_ms', 0):>7.2f} "
            f"{k.get('set_slice_max_ms', 0):>7.2f} "
            f"{k.get('slow_frame_count_16ms', 0):>8} "
            f"{k.get('decode_queue_depth_max', 0):>8} "
            f"{k.get('stale_task_count', 0):>6}"
        )
    if "download_interference_index" in results:
        print(f"\n  Download Interference Index (DII): {results['download_interference_index']:.1f}%")
    print("=" * 80)

    # JSON output
    if output_json:
        out_dir = Path(__file__).parent / "b25_output"
        out_dir.mkdir(exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_file = out_dir / f"b25_baseline_{ts}.json"
        with open(out_file, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\n  JSON output: {out_file}")

    # Cleanup
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    return results


def main():
    parser = argparse.ArgumentParser(description="B2.5 Concurrent-Load Baseline Scenarios")
    parser.add_argument("scenarios", nargs="*", help="Specific scenarios to run (S1, S2, ...)")
    parser.add_argument("--slices", type=int, default=50, help="Number of slices (default: 50)")
    parser.add_argument("--size", type=int, default=64, help="Image size (default: 64)")
    parser.add_argument("--json", action="store_true", help="Write JSON output")
    args = parser.parse_args()

    selected = args.scenarios if args.scenarios else None
    run_scenarios(selected=selected, n_slices=args.slices, image_size=args.size, output_json=args.json)


if __name__ == "__main__":
    main()
