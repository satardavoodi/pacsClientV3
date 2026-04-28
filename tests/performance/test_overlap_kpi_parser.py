"""F0.2 — overlap-scenario KPI parser tests.

These tests exercise the [OVERLAP_SCENARIO]-tag parser added in
``tools/performance/clearcanvas_aipacs_kpi_harness.py``.

The tests only depend on the harness's own pure-Python parsing path, so
they are safe to run without a full DICOM dataset, viewer, or download
manager.

Plan reference: docs/plans/... (untitled plan-fastViewerOverlap...).
Step:           F0.2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.performance.clearcanvas_aipacs_kpi_harness import (
    parse_overlap_log_text,
    parse_overlap_log_file,
)


def _build_log(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_parse_overlap_log_text_empty_emits_zero_payload():
    payload = parse_overlap_log_text("")
    assert payload["overlap_sample_count"] == 0
    assert payload["overlap_set_slice_present_p95_ms"] == 0.0
    assert payload["overlap_decode_p95_ms"] == 0.0
    assert payload["overlap_cache_hit_ratio_pct"] == 0.0
    assert payload["overlap_effective_fps"] == 0.0
    assert payload["overlap_cache_breakdown"] == {"hit": 0, "surrogate": 0, "decode": 0}
    assert payload["overlap_pixel_hash_match_pct_settled"] is None


def test_parse_overlap_log_text_ignores_unrelated_lines():
    text = _build_log(
        "2026-04-28 10:00:00 [B3.8_SCROLL] frame=1 slice=0 total_ms=2.0 decode_ms=0.0 wl_ms=1.0 src=hit",
        "2026-04-28 10:00:01 progressive-fast: series=42 COMPLETE",
        "2026-04-28 10:00:02 component=download some unrelated message",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_sample_count"] == 0


def test_parse_overlap_log_text_basic_shape():
    text = _build_log(
        "[OVERLAP_SCENARIO] frame idx=10 cache=hit decode_ms=0.0 wl_ms=1.5 total_ms=4.2 settled=False",
        "[OVERLAP_SCENARIO] frame idx=11 cache=surrogate decode_ms=0.0 wl_ms=2.0 total_ms=6.0 settled=False",
        "[OVERLAP_SCENARIO] frame idx=12 cache=decode decode_ms=18.5 wl_ms=2.1 total_ms=22.0 settled=False",
        "[OVERLAP_SCENARIO] frame idx=13 cache=hit decode_ms=0.0 wl_ms=1.4 total_ms=3.5 settled=True",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_sample_count"] == 4
    assert payload["overlap_cache_breakdown"] == {"hit": 2, "surrogate": 1, "decode": 1}
    assert payload["overlap_settled_breakdown"] == {"settled_true": 1, "settled_false": 3}

    # Cache hit ratio = (hit + surrogate) / total = 3/4 = 75%.
    assert payload["overlap_cache_hit_ratio_pct"] == pytest.approx(75.0, abs=0.01)

    # Slow-frame share at >16 ms: only the decode sample qualifies.
    assert payload["overlap_slow_frame_count_16ms"] == 1
    assert payload["overlap_slow_frame_pct_16ms"] == pytest.approx(25.0, abs=0.01)

    # p95 over [4.2, 6.0, 22.0, 3.5] sorted = [3.5, 4.2, 6.0, 22.0].
    # Linear-interp p95 between idx 2.85 -> ~17.2 ms.
    assert payload["overlap_set_slice_present_p95_ms"] >= 6.0
    assert payload["overlap_set_slice_present_p95_ms"] <= 22.0

    # Effective FPS uses the median total_ms; median of [3.5, 4.2, 6.0, 22.0]
    # is the linear-interp midpoint of the two middle values = (4.2+6.0)/2 = 5.1.
    assert payload["overlap_effective_fps"] == pytest.approx(1000.0 / 5.1, rel=0.01)


def test_parse_overlap_log_text_tolerates_trailing_fields():
    """Future extensions add k=v fields after settled=...; parser must ignore."""
    text = _build_log(
        "[OVERLAP_SCENARIO] frame idx=5 cache=hit decode_ms=0.0 wl_ms=1.2 total_ms=3.0 settled=False extra_field=42 priority=P1",
        "[OVERLAP_SCENARIO] frame idx=6 cache=surrogate decode_ms=0.0 wl_ms=1.0 total_ms=2.5 settled=False radius=5",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_sample_count"] == 2


def test_parse_overlap_log_text_rejects_malformed_line():
    """Malformed numbers do not crash the parser; the line is skipped."""
    text = _build_log(
        "[OVERLAP_SCENARIO] frame idx=5 cache=hit decode_ms=NaNny wl_ms=1.0 total_ms=3.0 settled=False",
        "[OVERLAP_SCENARIO] frame idx=6 cache=hit decode_ms=0.0 wl_ms=1.0 total_ms=4.0 settled=False",
    )
    payload = parse_overlap_log_text(text)
    # The float() conversion on decode_ms='NaNny' fails -> 'NaNny' is not a
    # valid float literal so the regex must guard. We accept either:
    #   - the malformed line skipped (sample_count == 1), or
    #   - both lines parsed if the regex enforces digit/decimal only.
    # Current implementation enforces [0-9.] only, so the bad line never
    # matches the regex -> sample_count == 1.
    assert payload["overlap_sample_count"] == 1


def test_parse_overlap_log_file_round_trip(tmp_path: Path):
    log = tmp_path / "viewer_diagnostics.log"
    log.write_text(
        _build_log(
            "[OVERLAP_SCENARIO] frame idx=1 cache=hit decode_ms=0.0 wl_ms=1.0 total_ms=3.0 settled=False",
            "[OVERLAP_SCENARIO] frame idx=2 cache=surrogate decode_ms=0.0 wl_ms=1.5 total_ms=5.0 settled=False",
        ),
        encoding="utf-8",
    )
    payload = parse_overlap_log_file(log)
    assert payload["viewer"] == "AI-PACS"
    assert payload["mode"] == "overlap-log-parse"
    assert payload["scenario"] == "aipacs_live_download_overlap"
    assert payload["log_path"] == str(log)
    assert payload["overlap_metrics"]["overlap_sample_count"] == 2


def test_parse_overlap_log_text_pixel_hash_keys_are_none():
    """Runtime log cannot observe pixel hashes; they must be None, not 0."""
    text = _build_log(
        "[OVERLAP_SCENARIO] frame idx=1 cache=hit decode_ms=0.0 wl_ms=1.0 total_ms=3.0 settled=True",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_pixel_hash_match_pct_settled"] is None
    assert payload["overlap_pixel_hash_match_pct_surrogate"] is None


def test_parse_overlap_log_text_matches_production_emit_format():
    """F2.1 contract test: the production emit format
    (Lightweight2DPipeline._maybe_emit_overlap_tag) MUST be parseable.

    The production format wraps the tag with a structured logging prefix
    of the form ``YYYY-MM-DD HH:MM:SS.uuuuuu | INFO | ... | <message>``.
    The parser must locate the tag inside that line and extract the
    KPI fields verbatim. If this test fails, either the emitter format
    changed or the harness regex drifted -- both should be reconciled
    before merging.
    """
    text = _build_log(
        # Verbatim shape of the diagnostic_logging formatter prefix +
        # the exact format string from
        # Lightweight2DPipeline._maybe_emit_overlap_tag.
        "2026-04-28 22:10:11.123456 | INFO     | pid=17452 tid=27692 | "
        "component=viewer role=main | "
        "modules.viewer.fast.lightweight_2d_pipeline._maybe_emit_overlap_tag | "
        "action=- study=- series=202 job=- viewevt=- fn=- stage=- result=- | "
        "[OVERLAP_SCENARIO] frame idx=42 cache=hit decode_ms=0.00 wl_ms=1.40 "
        "total_ms=3.20 settled=False",
        "2026-04-28 22:10:11.234567 | INFO     | pid=17452 tid=27692 | "
        "component=viewer role=main | "
        "modules.viewer.fast.lightweight_2d_pipeline._maybe_emit_overlap_tag | "
        "action=- study=- series=202 job=- viewevt=- fn=- stage=- result=- | "
        "[OVERLAP_SCENARIO] frame idx=43 cache=surrogate decode_ms=0.00 "
        "wl_ms=1.80 total_ms=5.20 settled=False",
        "2026-04-28 22:10:11.345678 | INFO     | pid=17452 tid=27692 | "
        "component=viewer role=main | "
        "modules.viewer.fast.lightweight_2d_pipeline._maybe_emit_overlap_tag | "
        "action=- study=- series=202 job=- viewevt=- fn=- stage=- result=- | "
        "[OVERLAP_SCENARIO] frame idx=44 cache=decode decode_ms=18.50 wl_ms=2.10 "
        "total_ms=22.00 settled=True",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_sample_count"] == 3, (
        "F2.1 emitter format must be parseable by the F0.2 harness; "
        "either the emit format drifted or the harness regex did."
    )
    assert payload["overlap_cache_breakdown"] == {
        "hit": 1,
        "surrogate": 1,
        "decode": 1,
    }
    assert payload["overlap_settled_breakdown"] == {
        "settled_true": 1,
        "settled_false": 2,
    }
