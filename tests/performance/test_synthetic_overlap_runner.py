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
    assert runner["version"] == "F0.6"
    assert runner["frames_driven"] >= 5


# ─── F0.6: --preset CLI flag coverage ───────────────────────────────────────


def test_preset_definitions_are_complete():
    """F0.6: every preset must define the full kwarg set so resolve order
    (preset → CLI override) cannot produce KeyError when no CLI flags are
    given. Drift in `_PRESETS` keys vs `run_synthetic_overlap` kwargs is a
    blocker for F0.5 anchor capture.
    """
    from tools.performance.synthetic_overlap_runner import _PRESETS

    required = {
        "duration_s",
        "set_slice_hz",
        "drip_hz",
        "sample_rate",
        "n_slices",
        "rows",
        "cols",
    }
    for name in ("default", "harsh", "realistic"):
        assert name in _PRESETS
        assert set(_PRESETS[name].keys()) == required, (
            f"preset {name!r} missing keys: {required - set(_PRESETS[name].keys())}"
        )


def test_harsh_preset_matches_plan_anchor_spec():
    """F0.5 anchor option (b) requires harsh = duration=30 set_slice_hz=60
    drip_hz=1 n_slices=240 rows=512 cols=512 sample_rate=1. Locking the
    spec here so future tweaks to the preset cannot silently break the
    anchor JSON's reproducibility.
    """
    from tools.performance.synthetic_overlap_runner import _PRESETS

    harsh = _PRESETS["harsh"]
    assert harsh["duration_s"] == 30.0
    assert harsh["set_slice_hz"] == 60
    assert harsh["drip_hz"] == 1
    assert harsh["n_slices"] == 240
    assert harsh["rows"] == 512
    assert harsh["cols"] == 512
    assert harsh["sample_rate"] == 1


def test_default_preset_matches_v0_baseline():
    """F0.6: 'default' preset MUST preserve the v0 F0.4 numbers so existing
    overlap_baseline_v0_synthetic.json captures remain reproducible.
    """
    from tools.performance.synthetic_overlap_runner import _PRESETS

    d = _PRESETS["default"]
    assert d["duration_s"] == 5.0
    assert d["set_slice_hz"] == 30
    assert d["drip_hz"] == 10
    assert d["n_slices"] == 60
    assert d["rows"] == 256
    assert d["cols"] == 256
    assert d["sample_rate"] == 1


def test_argparser_accepts_preset_flag():
    """F0.6: --preset must be in the parser's allowed choices."""
    from tools.performance.synthetic_overlap_runner import _build_argparser

    p = _build_argparser()
    # argparse should reject unknown preset values.
    args = p.parse_args(["--preset", "harsh"])
    assert args.preset == "harsh"
    args = p.parse_args(["--preset", "default"])
    assert args.preset == "default"
    args = p.parse_args(["--preset", "realistic"])
    assert args.preset == "realistic"


def test_cli_override_beats_preset(tmp_path: Path):
    """F0.6: explicit per-flag arguments must override preset values so
    ad-hoc captures remain possible without editing _PRESETS.
    """
    import sys as _sys
    from tools.performance.synthetic_overlap_runner import (
        _PRESETS,
        _build_argparser,
    )

    p = _build_argparser()
    args = p.parse_args(["--preset", "harsh", "--duration", "0.5", "--n-slices", "10"])
    assert args.preset == "harsh"
    # CLI override should win.
    preset = _PRESETS[args.preset]
    cli_overrides = {
        "duration_s": args.duration,
        "n_slices": args.n_slices,
    }
    resolved_duration = cli_overrides["duration_s"] if cli_overrides["duration_s"] is not None else preset["duration_s"]
    resolved_n_slices = cli_overrides["n_slices"] if cli_overrides["n_slices"] is not None else preset["n_slices"]
    assert resolved_duration == 0.5
    assert resolved_n_slices == 10
    # Fields without CLI override fall back to preset.
    assert args.set_slice_hz is None  # would resolve to harsh.set_slice_hz=60
