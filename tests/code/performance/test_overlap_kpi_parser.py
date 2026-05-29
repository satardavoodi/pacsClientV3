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


# ─── F2.3: effective_fps wall-clock derivation ─────────────────────────────


def test_effective_fps_uses_wall_clock_delta_when_timestamps_present():
    """F2.3: when log lines carry a YYYY-MM-DD HH:MM:SS.uuuuuu prefix,
    fps is derived from (n-1) / (last_ts - first_ts), not from median
    total_ms. This matches real frame cadence regardless of how cheap
    the per-frame compute is.

    The synthetic baseline reported overlap_effective_fps=0.00 because
    the previous implementation used 1000/median(total_ms) and many
    surrogate samples report total_ms=0.00 → division by zero collapse.
    """
    # 5 samples spaced 100ms apart starting at 22:10:11.000000
    # → wall span = 0.4s, fps = (5-1)/0.4 = 10.0
    text = _build_log(
        "2026-04-28 22:10:11.000000 | INFO | x | "
        "[OVERLAP_SCENARIO] frame idx=1 cache=surrogate decode_ms=0.00 wl_ms=0.00 total_ms=0.00 settled=False",
        "2026-04-28 22:10:11.100000 | INFO | x | "
        "[OVERLAP_SCENARIO] frame idx=2 cache=surrogate decode_ms=0.00 wl_ms=0.00 total_ms=0.00 settled=False",
        "2026-04-28 22:10:11.200000 | INFO | x | "
        "[OVERLAP_SCENARIO] frame idx=3 cache=hit decode_ms=0.00 wl_ms=1.00 total_ms=2.00 settled=False",
        "2026-04-28 22:10:11.300000 | INFO | x | "
        "[OVERLAP_SCENARIO] frame idx=4 cache=hit decode_ms=0.00 wl_ms=1.00 total_ms=2.00 settled=False",
        "2026-04-28 22:10:11.400000 | INFO | x | "
        "[OVERLAP_SCENARIO] frame idx=5 cache=hit decode_ms=0.00 wl_ms=1.00 total_ms=2.00 settled=False",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_sample_count"] == 5
    assert payload["overlap_effective_fps_source"] == "wall_clock"
    assert payload["overlap_effective_fps"] == pytest.approx(10.0, rel=0.01)


def test_effective_fps_falls_back_to_median_when_no_timestamps():
    """F2.3: untimestamped fixtures (test fixtures built via _build_log)
    must still produce a non-zero fps via the legacy 1000/median formula.
    """
    text = _build_log(
        "[OVERLAP_SCENARIO] frame idx=1 cache=hit decode_ms=0.0 wl_ms=1.0 total_ms=4.0 settled=False",
        "[OVERLAP_SCENARIO] frame idx=2 cache=hit decode_ms=0.0 wl_ms=1.0 total_ms=4.0 settled=False",
        "[OVERLAP_SCENARIO] frame idx=3 cache=hit decode_ms=0.0 wl_ms=1.0 total_ms=4.0 settled=False",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_effective_fps_source"] == "median_total_ms"
    assert payload["overlap_effective_fps"] == pytest.approx(250.0, rel=0.01)


def test_effective_fps_supports_comma_milliseconds_format():
    """F2.3: the synthetic runner default asctime emits
    ``YYYY-MM-DD HH:MM:SS,mmm`` (comma + 3-digit ms) instead of the
    production microsecond form. Both must parse identically.
    """
    text = _build_log(
        "2026-04-28 22:10:11,000 | INFO | x | "
        "[OVERLAP_SCENARIO] frame idx=1 cache=hit decode_ms=0.0 wl_ms=1.0 total_ms=2.0 settled=False",
        "2026-04-28 22:10:11,500 | INFO | x | "
        "[OVERLAP_SCENARIO] frame idx=2 cache=hit decode_ms=0.0 wl_ms=1.0 total_ms=2.0 settled=False",
        "2026-04-28 22:10:12,000 | INFO | x | "
        "[OVERLAP_SCENARIO] frame idx=3 cache=hit decode_ms=0.0 wl_ms=1.0 total_ms=2.0 settled=False",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_effective_fps_source"] == "wall_clock"
    # 3 samples over 1.0s wall span = 2 fps
    assert payload["overlap_effective_fps"] == pytest.approx(2.0, rel=0.01)


def test_effective_fps_zero_for_empty_input():
    payload = parse_overlap_log_text("")
    assert payload["overlap_effective_fps"] == 0.0
    assert payload["overlap_effective_fps_source"] == "none"


def test_effective_fps_zero_when_all_timestamps_identical():
    """Defensive: if every sample has the same timestamp (degenerate
    capture), we cannot derive a wall-clock rate and must report 0.0
    rather than a division-by-zero or nan.
    """
    text = _build_log(
        "2026-04-28 22:10:11.000000 | INFO | x | "
        "[OVERLAP_SCENARIO] frame idx=1 cache=hit decode_ms=0.0 wl_ms=1.0 total_ms=2.0 settled=False",
        "2026-04-28 22:10:11.000000 | INFO | x | "
        "[OVERLAP_SCENARIO] frame idx=2 cache=hit decode_ms=0.0 wl_ms=1.0 total_ms=2.0 settled=False",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_effective_fps"] == 0.0

# ─── F2.4: cache-source-split KPIs (post-F0.5 retarget) ─────────────────────


def test_overlap_kpis_include_per_source_present_p95():
    """F2.4: parser must emit per-cache-source p95 of total_ms so the plan
    can target the decode-cache-miss tail without it being washed out by
    the surrogate-dominated mean.
    """
    text = _build_log(
        "[OVERLAP_SCENARIO] frame idx=1 cache=hit decode_ms=0.0 wl_ms=0.5 total_ms=1.0 settled=False",
        "[OVERLAP_SCENARIO] frame idx=2 cache=hit decode_ms=0.0 wl_ms=0.5 total_ms=2.0 settled=False",
        "[OVERLAP_SCENARIO] frame idx=3 cache=surrogate decode_ms=0.0 wl_ms=0.5 total_ms=0.5 settled=False",
        "[OVERLAP_SCENARIO] frame idx=4 cache=surrogate decode_ms=0.0 wl_ms=0.5 total_ms=0.6 settled=False",
        "[OVERLAP_SCENARIO] frame idx=5 cache=decode decode_ms=20.0 wl_ms=2.0 total_ms=25.0 settled=False",
        "[OVERLAP_SCENARIO] frame idx=6 cache=decode decode_ms=18.0 wl_ms=2.0 total_ms=22.0 settled=False",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_hit_present_p95_ms"] >= 1.0
    assert payload["overlap_hit_present_p95_ms"] <= 2.0
    assert payload["overlap_surrogate_present_p95_ms"] >= 0.5
    assert payload["overlap_surrogate_present_p95_ms"] <= 0.6
    assert payload["overlap_decode_only_p95_ms"] >= 22.0
    assert payload["overlap_decode_only_p95_ms"] <= 25.0
    assert payload["overlap_decode_only_max_ms"] == pytest.approx(25.0, abs=0.01)


def test_overlap_kpis_decode_sample_share_and_count():
    """F2.4: decode sample count + share are first-class KPIs because
    the retargeted plan optimizes for reducing the share (currently
    4.4% in the harsh anchor)."""
    text = _build_log(
        "[OVERLAP_SCENARIO] frame idx=1 cache=hit decode_ms=0.0 wl_ms=0.5 total_ms=1.0 settled=False",
        "[OVERLAP_SCENARIO] frame idx=2 cache=surrogate decode_ms=0.0 wl_ms=0.5 total_ms=0.6 settled=False",
        "[OVERLAP_SCENARIO] frame idx=3 cache=surrogate decode_ms=0.0 wl_ms=0.5 total_ms=0.6 settled=False",
        "[OVERLAP_SCENARIO] frame idx=4 cache=decode decode_ms=20.0 wl_ms=2.0 total_ms=25.0 settled=False",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_decode_sample_count"] == 1
    assert payload["overlap_decode_sample_share_pct"] == pytest.approx(25.0, abs=0.01)


def test_overlap_kpis_settled_present_p95_and_count():
    """F2.4: settled=true frames are the user-visible end-of-drag re-render.
    The harness exposes their tail latency separately so the plan can
    target it without it being averaged into the in-drag surrogate flood.
    """
    text = _build_log(
        "[OVERLAP_SCENARIO] frame idx=1 cache=surrogate decode_ms=0.0 wl_ms=0.5 total_ms=0.5 settled=False",
        "[OVERLAP_SCENARIO] frame idx=2 cache=surrogate decode_ms=0.0 wl_ms=0.5 total_ms=0.6 settled=False",
        "[OVERLAP_SCENARIO] frame idx=3 cache=decode decode_ms=18.0 wl_ms=2.0 total_ms=21.0 settled=True",
        "[OVERLAP_SCENARIO] frame idx=4 cache=decode decode_ms=20.0 wl_ms=2.0 total_ms=24.0 settled=True",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_settled_sample_count"] == 2
    assert payload["overlap_settled_present_p95_ms"] >= 21.0
    assert payload["overlap_settled_present_p95_ms"] <= 24.0


def test_overlap_kpis_slow_frame_source_breakdown():
    """F2.4: when a frame breaches the 16ms slow-frame threshold the
    parser records which cache source produced it so plan reviewers can
    see at a glance whether the tail is a decode-miss problem or a
    surrogate W/L problem.
    """
    text = _build_log(
        "[OVERLAP_SCENARIO] frame idx=1 cache=hit decode_ms=0.0 wl_ms=0.5 total_ms=1.0 settled=False",
        "[OVERLAP_SCENARIO] frame idx=2 cache=surrogate decode_ms=0.0 wl_ms=0.5 total_ms=18.0 settled=False",
        "[OVERLAP_SCENARIO] frame idx=3 cache=decode decode_ms=20.0 wl_ms=2.0 total_ms=25.0 settled=False",
        "[OVERLAP_SCENARIO] frame idx=4 cache=decode decode_ms=22.0 wl_ms=2.0 total_ms=27.0 settled=True",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_slow_frame_count_16ms"] == 3
    assert payload["overlap_slow_frame_source_breakdown"] == {
        "hit": 0,
        "surrogate": 1,
        "decode": 2,
    }


def test_overlap_kpis_empty_payload_includes_new_fields():
    """F2.4: empty input must still emit the new keys with safe defaults
    so downstream diff tooling never sees missing fields.
    """
    payload = parse_overlap_log_text("")
    assert payload["overlap_hit_present_p95_ms"] == 0.0
    assert payload["overlap_surrogate_present_p95_ms"] == 0.0
    assert payload["overlap_decode_only_p95_ms"] == 0.0
    assert payload["overlap_decode_only_max_ms"] == 0.0
    assert payload["overlap_decode_sample_count"] == 0
    assert payload["overlap_decode_sample_share_pct"] == 0.0
    assert payload["overlap_settled_sample_count"] == 0
    assert payload["overlap_settled_present_p95_ms"] == 0.0
    assert payload["overlap_slow_frame_source_breakdown"] == {
        "hit": 0,
        "surrogate": 0,
        "decode": 0,
    }


# ---------------------------------------------------------------------------
# F2.1b sentinel-emit + F2.4b drag-KPI tests (live-run-2026-04-29 retarget).
# ---------------------------------------------------------------------------


def test_overlap_kpis_sentinel_field_optional_for_old_logs():
    """F2.1b: pre-F2.1b emits have no `sentinel=` field. Parser must
    accept them and report sentinel breakdown of all-zeros."""
    text = _build_log(
        "[OVERLAP_SCENARIO] frame idx=1 cache=hit decode_ms=0.0 wl_ms=0.5 total_ms=1.0 settled=False",
        "[OVERLAP_SCENARIO] frame idx=2 cache=surrogate decode_ms=0.0 wl_ms=0.5 total_ms=0.6 settled=False",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_sample_count"] == 2
    assert payload["overlap_sentinel_emit_count"] == 0
    assert payload["overlap_sentinel_breakdown"] == {
        "decode": 0, "drag_begin": 0, "drag_end": 0, "other": 0,
    }


def test_overlap_kpis_sentinel_field_captured_when_present():
    """F2.1b: production emits with sentinel reasons must be aggregated
    into overlap_sentinel_breakdown by reason."""
    text = _build_log(
        "[OVERLAP_SCENARIO] frame idx=1 cache=hit decode_ms=0.0 wl_ms=0.5 total_ms=1.0 settled=False sentinel=-",
        "[OVERLAP_SCENARIO] frame idx=2 cache=decode decode_ms=18.0 wl_ms=2.0 total_ms=22.0 settled=False sentinel=decode",
        "[OVERLAP_SCENARIO] frame idx=3 cache=decode decode_ms=20.0 wl_ms=2.0 total_ms=25.0 settled=False sentinel=decode",
        "[OVERLAP_SCENARIO] frame idx=4 cache=surrogate decode_ms=0.0 wl_ms=0.5 total_ms=0.7 settled=False sentinel=drag_begin",
        "[OVERLAP_SCENARIO] frame idx=5 cache=hit decode_ms=0.0 wl_ms=1.4 total_ms=3.5 settled=True sentinel=drag_end",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_sample_count"] == 5
    assert payload["overlap_sentinel_emit_count"] == 4  # excludes the "-" sentinel
    assert payload["overlap_sentinel_breakdown"]["decode"] == 2
    assert payload["overlap_sentinel_breakdown"]["drag_begin"] == 1
    assert payload["overlap_sentinel_breakdown"]["drag_end"] == 1
    assert payload["overlap_sentinel_breakdown"]["other"] == 0


def test_overlap_kpis_mixed_old_and_new_format_lines():
    """F2.1b: a single log window may straddle an in-place upgrade. The
    parser must accept both shapes interleaved without errors."""
    text = _build_log(
        "[OVERLAP_SCENARIO] frame idx=1 cache=hit decode_ms=0.0 wl_ms=0.5 total_ms=1.0 settled=False",
        "[OVERLAP_SCENARIO] frame idx=2 cache=decode decode_ms=18.0 wl_ms=2.0 total_ms=22.0 settled=False sentinel=decode",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_sample_count"] == 2
    assert payload["overlap_sentinel_breakdown"]["decode"] == 1


def test_overlap_kpis_drag_kpi_aggregation_from_fast_drag_kpi_lines():
    """F2.4b: parse_overlap_log_text must surface real-world Tier-2 KPIs
    from [FAST_DRAG_KPI] end-of-burst lines (event_p95, ui_lag_max,
    handler_p95, prefetch_per_s, background_decode_count). Live
    2026-04-28 run had event_p95=607.9 ms / ui_lag_max=363.9 ms which
    the per-frame [OVERLAP_SCENARIO] tag cannot capture."""
    text = _build_log(
        "[FAST_DRAG_KPI] bridge=B1 viewer=V1 duration_s=1.287 targets=1 "
        "event_p50_ms=31.0 event_p95_ms=607.9 handler_p50_ms=3.7 "
        "handler_p95_ms=3.7 ui_lag_max_ms=0.0 prefetch_per_s=0.0 "
        "background_decode_count=0",
        "[FAST_DRAG_KPI] bridge=B1 viewer=V1 duration_s=0.771 targets=7 "
        "event_p50_ms=68.0 event_p95_ms=328.3 handler_p50_ms=2.8 "
        "handler_p95_ms=3.2 ui_lag_max_ms=363.9 prefetch_per_s=0.0 "
        "background_decode_count=0",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_drag_burst_count"] == 2
    assert payload["overlap_drag_event_p95_max_ms"] == pytest.approx(607.9, abs=0.01)
    assert payload["overlap_drag_ui_lag_max_max_ms"] == pytest.approx(363.9, abs=0.01)
    assert payload["overlap_drag_handler_p95_max_ms"] == pytest.approx(3.7, abs=0.01)
    assert payload["overlap_drag_background_decode_count_total"] == 0


def test_overlap_kpis_drag_kpi_zero_when_no_fast_drag_lines():
    """F2.4b: payload must contain the new keys with zero-defaults even
    when no [FAST_DRAG_KPI] lines are present, so diff tooling can
    detect the empty case explicitly."""
    payload = parse_overlap_log_text("")
    assert payload["overlap_drag_burst_count"] == 0
    assert payload["overlap_drag_event_p95_max_ms"] == 0.0
    assert payload["overlap_drag_ui_lag_max_max_ms"] == 0.0
    assert payload["overlap_drag_handler_p95_max_ms"] == 0.0
    assert payload["overlap_drag_background_decode_count_total"] == 0


def test_overlap_kpis_drag_kpi_independent_from_overlap_predicate():
    """F2.4b: [FAST_DRAG_KPI] lines are not gated by overlap predicate
    (incomplete-series-during-active-download); they appear in every
    drag burst. The parser must aggregate them regardless of whether
    [OVERLAP_SCENARIO] samples are present."""
    text = _build_log(
        "[FAST_DRAG_KPI] bridge=B1 viewer=V1 duration_s=2.0 targets=10 "
        "event_p50_ms=10.0 event_p95_ms=100.0 handler_p50_ms=2.0 "
        "handler_p95_ms=4.0 ui_lag_max_ms=50.0 prefetch_per_s=5.0 "
        "background_decode_count=3",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_sample_count"] == 0  # no [OVERLAP_SCENARIO] lines
    assert payload["overlap_drag_burst_count"] == 1
    assert payload["overlap_drag_event_p95_max_ms"] == pytest.approx(100.0, abs=0.01)
    assert payload["overlap_drag_ui_lag_max_max_ms"] == pytest.approx(50.0, abs=0.01)
    assert payload["overlap_drag_background_decode_count_total"] == 3


def test_parse_overlap_log_text_matches_production_emit_format_with_sentinel():
    """F2.1b contract test: the NEW production emit format from
    Lightweight2DPipeline._maybe_emit_overlap_tag (with trailing
    `sentinel=<reason>` field) MUST be parseable."""
    text = _build_log(
        "2026-04-29 10:00:00.123456 | INFO     | pid=17452 tid=27692 | "
        "component=viewer role=main | "
        "modules.viewer.fast.lightweight_2d_pipeline._maybe_emit_overlap_tag | "
        "action=- study=- series=303 job=- viewevt=- fn=- stage=- result=- | "
        "[OVERLAP_SCENARIO] frame idx=42 cache=decode decode_ms=18.50 "
        "wl_ms=2.10 total_ms=22.00 settled=False sentinel=decode",
        "2026-04-29 10:00:00.234567 | INFO     | pid=17452 tid=27692 | "
        "component=viewer role=main | "
        "modules.viewer.fast.lightweight_2d_pipeline._maybe_emit_overlap_tag | "
        "action=- study=- series=303 job=- viewevt=- fn=- stage=- result=- | "
        "[OVERLAP_SCENARIO] frame idx=43 cache=hit decode_ms=0.00 "
        "wl_ms=1.40 total_ms=3.50 settled=True sentinel=drag_end",
    )
    payload = parse_overlap_log_text(text)
    assert payload["overlap_sample_count"] == 2, (
        "F2.1b emitter format with sentinel= MUST be parseable; either "
        "the emit format drifted or the harness regex did."
    )
    assert payload["overlap_sentinel_breakdown"]["decode"] == 1
    assert payload["overlap_sentinel_breakdown"]["drag_end"] == 1
