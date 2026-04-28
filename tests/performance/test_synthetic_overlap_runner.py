"""F0.4 — smoke test for the synthetic overlap headless runner."""
from __future__ import annotations

import json
import time
from pathlib import Path

def test_synthetic_overlap_runner_smoke(tmp_path: Path) -> None:
    """Runner completes < 60s on tiny duration, emits valid JSON with samples."""
    from tools.performance.synthetic_overlap_runner import run_synthetic_overlap

    out = tmp_path / "smoke.json"

    started = time.perf_counter()
    payload = run_synthetic_overlap(
        duration_s=1.0,
        set_slice_hz=30,
        sample_rate=1,
        n_slices=20,        # smaller for CI smoke
        rows=128,
        cols=128,
        output_path=out,
    )
    elapsed = time.perf_counter() - started

    # Plan F0.4 success criterion.
    assert elapsed < 60.0, f"Runner took too long: {elapsed:.2f}s"

    # JSON exists and matches what the function returned.
    assert out.exists()
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["overlap_metrics"] == payload["overlap_metrics"]

    metrics = parsed["overlap_metrics"]
    # F2.1 emits overlap tags only on heavy_download paths in get_rendered_frame
    # — drag loop with sample_rate=1 must produce at least a handful of samples.
    assert metrics["overlap_sample_count"] >= 5, (
        f"Too few overlap samples: {metrics['overlap_sample_count']}"
    )

    breakdown = metrics["overlap_cache_breakdown"]
    # Sum of (hit + surrogate + decode) matches the recorded sample count.
    assert sum(breakdown.values()) == metrics["overlap_sample_count"]

    settled = metrics["overlap_settled_breakdown"]
    assert sum(settled.values()) == metrics["overlap_sample_count"]

    runner = parsed["runner"]
    assert runner["version"] == "F0.4"
    assert runner["frames_driven"] >= 5
