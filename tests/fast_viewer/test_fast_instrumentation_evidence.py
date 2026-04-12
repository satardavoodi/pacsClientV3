"""
Phase I/J Evidence Test — FAST Instrumentation Verification
=============================================================
Verifies that every FAST: log prefix fires at the correct level and
captures exact cold-run vs warm-run log excerpts.

Cold run  = first get_rendered_frame() call on a fresh Lightweight2DPipeline
Warm run  = second call to same slice (pixel + frame cache both populated)

Run with:
    .venv\\Scripts\\python.exe -m pytest tests/fast_viewer/test_fast_instrumentation_evidence.py -v -s --log-cli-level=DEBUG
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import List

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_PIPE_LOGGER = "modules.viewer.fast.lightweight_2d_pipeline"
_IO_LOGGER   = "PacsClient.pacs.patient_tab.utils.image_io"


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _fast_lines(records) -> List[str]:
    return [r.getMessage() for r in records if "FAST:" in r.getMessage()]


def _assert_prefix(lines: List[str], prefix: str, context: str = "") -> str:
    matches = [l for l in lines if l.startswith(prefix)]
    assert matches, (
        f"[{context}] Expected log line starting with {prefix!r}\n"
        f"  Got {len(lines)} FAST: lines total:\n" +
        "\n".join(f"    {l}" for l in lines)
    )
    return matches[0]


def _make_pipeline(filter_enabled: bool = False):
    """Construct a Lightweight2DPipeline with a mutable config."""
    from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline, PipelineConfig
    cfg = PipelineConfig()
    cfg.opencv_filter_enabled = filter_enabled
    cfg.prefetch_workers = 1   # minimum allowed by ThreadPoolExecutor
    cfg.prefetch_radius = 0
    return Lightweight2DPipeline(config=cfg)


# ══════════════════════════════════════════════════════════════════════════════
# Scenario A — Cold (all caches empty, first render)
# ══════════════════════════════════════════════════════════════════════════════

class TestScenarioACold:

    def test_cold_frame_cache_miss(self, make_dicom_series, caplog):
        series_dir, _ = make_dicom_series(n=5)
        pipeline = _make_pipeline()
        pipeline.open_series(str(series_dir))

        with caplog.at_level(logging.DEBUG, logger=_PIPE_LOGGER):
            frame = pipeline.get_rendered_frame(0)

        lines = _fast_lines(caplog.records)
        print("\n[COLD] FAST: log lines:")
        for l in lines:
            print(f"  {l}")

        assert frame is not None
        _assert_prefix(lines, "FAST:frame_cache source=miss", "cold")
        _assert_prefix(lines, "FAST:pixel_cache source=miss", "cold")
        _assert_prefix(lines, "FAST:first_renderable_frame", "cold")
        pipeline.close_series()

    def test_cold_no_frame_cache_hit(self, make_dicom_series, caplog):
        series_dir, _ = make_dicom_series(n=3)
        pipeline = _make_pipeline()
        pipeline.open_series(str(series_dir))

        with caplog.at_level(logging.DEBUG, logger=_PIPE_LOGGER):
            pipeline.get_rendered_frame(0)

        lines = _fast_lines(caplog.records)
        hits  = [l for l in lines if "FAST:frame_cache source=hit"  in l]
        misses = [l for l in lines if "FAST:frame_cache source=miss" in l]
        assert misses, "Expected frame_cache miss on cold open"
        assert hits == [], f"Unexpected frame_cache hit on cold open: {hits}"
        pipeline.close_series()

    def test_cold_first_renderable_frame_fires_once(self, make_dicom_series, caplog):
        series_dir, _ = make_dicom_series(n=5)
        pipeline = _make_pipeline()
        pipeline.open_series(str(series_dir))

        with caplog.at_level(logging.INFO, logger=_PIPE_LOGGER):
            for i in range(5):
                pipeline.get_rendered_frame(i)

        renderable = [l for l in _fast_lines(caplog.records) if l.startswith("FAST:first_renderable_frame")]
        assert len(renderable) == 1, f"Expected exactly 1 first_renderable_frame, got {renderable}"
        pipeline.close_series()


# ══════════════════════════════════════════════════════════════════════════════
# Scenario B — Warm (second call to same slice)
# ══════════════════════════════════════════════════════════════════════════════

class TestScenarioBWarm:

    def test_warm_frame_cache_hit(self, make_dicom_series, caplog):
        series_dir, _ = make_dicom_series(n=5)
        pipeline = _make_pipeline()
        pipeline.open_series(str(series_dir))
        pipeline.get_rendered_frame(0)   # prime cache
        caplog.clear()

        with caplog.at_level(logging.DEBUG, logger=_PIPE_LOGGER):
            frame = pipeline.get_rendered_frame(0)  # warm

        lines = _fast_lines(caplog.records)
        print("\n[WARM] FAST: log lines:")
        for l in lines:
            print(f"  {l}")

        assert frame is not None
        _assert_prefix(lines, "FAST:frame_cache source=hit", "warm")
        misses = [l for l in lines if "FAST:frame_cache source=miss" in l]
        assert misses == [], f"Unexpected frame_cache miss on warm read: {misses}"
        pipeline.close_series()

    def test_warm_pixel_cache_hit_after_frame_cache_clear(self, make_dicom_series, caplog):
        """pixel_cache=hit when frame cache cleared but pixel cache still populated."""
        series_dir, _ = make_dicom_series(n=3)
        pipeline = _make_pipeline()
        pipeline.open_series(str(series_dir))
        pipeline.get_rendered_frame(0)  # prime both caches
        pipeline._frame_cache.clear()   # evict frame cache only
        caplog.clear()

        with caplog.at_level(logging.DEBUG, logger=_PIPE_LOGGER):
            pipeline.get_rendered_frame(0)  # frame miss → pixel hit

        lines = _fast_lines(caplog.records)
        pixel_hits = [l for l in lines if "FAST:pixel_cache source=hit" in l]
        assert pixel_hits, f"Expected pixel_cache=hit after clearing frame cache\n  Got: {lines}"
        pipeline.close_series()

    def test_warm_no_first_renderable_frame_refire(self, make_dicom_series, caplog):
        series_dir, _ = make_dicom_series(n=3)
        pipeline = _make_pipeline()
        pipeline.open_series(str(series_dir))
        pipeline.get_rendered_frame(0)
        caplog.clear()

        with caplog.at_level(logging.INFO, logger=_PIPE_LOGGER):
            pipeline.get_rendered_frame(0)
            pipeline.get_rendered_frame(1)

        refire = [l for l in _fast_lines(caplog.records) if l.startswith("FAST:first_renderable_frame")]
        assert refire == [], f"first_renderable_frame must not re-fire on warm: {refire}"
        pipeline.close_series()

    def test_warm_zero_decode_ms(self, make_dicom_series, caplog):
        """Frame cache hit must return decode_ms=0 (no pixel decode occurred)."""
        series_dir, _ = make_dicom_series(n=3)
        pipeline = _make_pipeline()
        pipeline.open_series(str(series_dir))
        pipeline.get_rendered_frame(0)
        frame = pipeline.get_rendered_frame(0)   # warm
        assert frame.decode_ms == 0.0, f"Expected decode_ms=0 on warm hit, got {frame.decode_ms}"
        pipeline.close_series()


# ══════════════════════════════════════════════════════════════════════════════
# Phase I — Individual prefix verification
# ══════════════════════════════════════════════════════════════════════════════

class TestPhaseIPrefix:

    def test_meta_cache_miss_on_first_call(self, caplog):
        from PacsClient.pacs.patient_tab.utils.image_io import _series_metadata_cache, _get_cached_metadata
        test_pk = 999900
        cache_key = f"series_{test_pk}"
        _series_metadata_cache.pop(cache_key, None)

        with caplog.at_level(logging.INFO, logger=_IO_LOGGER):
            try:
                _get_cached_metadata(series_pk=test_pk, instances=[])
            except Exception:
                pass  # DB has no row for fake PK — expected; log fires before the crash

        lines = _fast_lines(caplog.records)
        miss = [l for l in lines if "FAST:meta_cache source=miss" in l]
        assert miss, f"Expected FAST:meta_cache source=miss\n  Got: {lines}"
        print(f"\n[meta_cache miss]: {miss[0]}")
        _series_metadata_cache.pop(cache_key, None)

    def test_meta_cache_hit_on_second_call(self, caplog):
        from PacsClient.pacs.patient_tab.utils.image_io import _series_metadata_cache, _get_cached_metadata
        test_pk = 999901
        cache_key = f"series_{test_pk}"
        _series_metadata_cache[cache_key] = {"patient": {}, "study": {}, "series": {}, "instances": []}

        with caplog.at_level(logging.INFO, logger=_IO_LOGGER):
            _get_cached_metadata(series_pk=test_pk, instances=[])

        lines = _fast_lines(caplog.records)
        hit = [l for l in lines if "FAST:meta_cache source=hit" in l]
        assert hit, f"Expected FAST:meta_cache source=hit\n  Got: {lines}"
        print(f"\n[meta_cache hit]: {hit[0]}")
        _series_metadata_cache.pop(cache_key, None)

    def test_filter_apply_fires_when_enabled(self, make_dicom_series, caplog):
        series_dir, _ = make_dicom_series(n=2)
        pipeline = _make_pipeline(filter_enabled=True)
        pipeline.open_series(str(series_dir))

        with caplog.at_level(logging.DEBUG, logger=_PIPE_LOGGER):
            pipeline.get_rendered_frame(0)

        lines = _fast_lines(caplog.records)
        flines = [l for l in lines if l.startswith("FAST:filter_apply")]
        assert flines, f"Expected FAST:filter_apply with filter=True\n  Got: {lines}"
        print(f"\n[filter_apply]: {flines[0]}")
        pipeline.close_series()

    def test_filter_apply_absent_when_disabled(self, make_dicom_series, caplog):
        series_dir, _ = make_dicom_series(n=2)
        pipeline = _make_pipeline(filter_enabled=False)
        pipeline.open_series(str(series_dir))

        with caplog.at_level(logging.DEBUG, logger=_PIPE_LOGGER):
            pipeline.get_rendered_frame(0)

        lines = _fast_lines(caplog.records)
        flines = [l for l in lines if l.startswith("FAST:filter_apply")]
        assert flines == [], f"Expected no FAST:filter_apply with filter=False: {flines}"
        pipeline.close_series()

    def test_frame_cache_invalidated_on_wl_change_with_filter(self, make_dicom_series, caplog):
        """frame_cache_invalidated fires when W/L changes and filter is on (frame key includes filter)."""
        series_dir, _ = make_dicom_series(n=2)
        pipeline = _make_pipeline(filter_enabled=True)
        pipeline.open_series(str(series_dir))
        pipeline.get_rendered_frame(0)
        caplog.clear()

        with caplog.at_level(logging.DEBUG, logger=_PIPE_LOGGER):
            pipeline.set_window_level(500.0, 50.0)

        lines = _fast_lines(caplog.records)
        inv = [l for l in lines if l.startswith("FAST:frame_cache_invalidated")]
        assert inv, f"Expected FAST:frame_cache_invalidated\n  Got: {lines}"
        print(f"\n[frame_cache_invalidated]: {inv[0]}")
        pipeline.close_series()


# ══════════════════════════════════════════════════════════════════════════════
# Phase J — Structured cold vs warm evidence table
# ══════════════════════════════════════════════════════════════════════════════

class TestPhaseJEvidenceTable:

    def test_evidence_table_cold_vs_warm(self, make_dicom_series, caplog):
        series_dir, _ = make_dicom_series(n=10)

        # ── COLD ──────────────────────────────────────────────────────────────
        pipeline = _make_pipeline(filter_enabled=False)
        pipeline.open_series(str(series_dir))

        with caplog.at_level(logging.DEBUG, logger=_PIPE_LOGGER):
            t0 = time.perf_counter()
            cold_frame = pipeline.get_rendered_frame(0)
            cold_ms = (time.perf_counter() - t0) * 1000.0

        cold_lines = _fast_lines(caplog.records)
        caplog.clear()

        # ── WARM (same slice, same pipeline) ──────────────────────────────────
        with caplog.at_level(logging.DEBUG, logger=_PIPE_LOGGER):
            t0 = time.perf_counter()
            warm_frame = pipeline.get_rendered_frame(0)
            warm_ms = (time.perf_counter() - t0) * 1000.0

        warm_lines = _fast_lines(caplog.records)
        pipeline.close_series()

        # ── Print evidence table ──────────────────────────────────────────────
        print("\n" + "=" * 78)
        print("PHASE J — COLD vs WARM EVIDENCE")
        print("=" * 78)
        W = 44
        print(f"\n{'Metric':<{W}} {'COLD':>16} {'WARM':>16}")
        print("-" * (W + 34))
        print(f"{'total get_rendered_frame (ms)':<{W}} {cold_ms:>13.2f}ms {warm_ms:>13.2f}ms")
        print(f"{'RenderedFrame.decode_ms':<{W}} {cold_frame.decode_ms:>13.2f}ms {warm_frame.decode_ms:>13.2f}ms")
        print(f"{'RenderedFrame.filter_ms':<{W}} {cold_frame.filter_ms:>13.2f}ms {warm_frame.filter_ms:>13.2f}ms")
        print(f"{'RenderedFrame.wl_ms':<{W}} {cold_frame.wl_ms:>13.2f}ms {warm_frame.wl_ms:>13.2f}ms")
        print()
        print("[COLD] FAST: log excerpt:")
        for l in cold_lines:
            print(f"  {l}")
        print()
        print("[WARM] FAST: log excerpt:")
        for l in warm_lines:
            print(f"  {l}")
        print("=" * 78)

        # ── Assertions ────────────────────────────────────────────────────────
        assert cold_frame is not None and warm_frame is not None
        assert any("FAST:frame_cache source=miss" in l for l in cold_lines), \
            "Cold run: expected frame_cache=miss"
        assert any("FAST:pixel_cache source=miss" in l for l in cold_lines), \
            "Cold run: expected pixel_cache=miss"
        assert any("FAST:first_renderable_frame" in l for l in cold_lines), \
            "Cold run: expected first_renderable_frame"
        assert any("FAST:frame_cache source=hit" in l for l in warm_lines), \
            "Warm run: expected frame_cache=hit"
        assert warm_frame.decode_ms == 0.0, \
            f"Warm run frame_cache hit must have decode_ms=0, got {warm_frame.decode_ms}"
        assert warm_ms < cold_ms, \
            f"Warm ({warm_ms:.2f}ms) must be faster than cold ({cold_ms:.2f}ms)"
        print(">>> ALL evidence assertions passed")

