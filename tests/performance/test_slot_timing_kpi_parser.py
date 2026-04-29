"""Contract tests for `parse_slot_timing_log_text` (G6).

Locks the `[SLOT_TIMING]` emit format consumed by the KPI harness so that
any future change to `modules/viewer/fast/slot_timing.py::emit_slot_timing`
that breaks the parser is caught here, not in production triage.
"""
from __future__ import annotations

import pytest

from tools.performance.clearcanvas_aipacs_kpi_harness import (
    parse_slot_timing_log_text,
)


def _line(
    tag: str,
    duration_ms: float,
    *,
    drag: bool = False,
    threshold_ms: float = 30.0,
    series: str = "none",
    extra: str = "",
    prefix: str = "",
) -> str:
    """Render a `[SLOT_TIMING]` line matching the production emit format."""
    return (
        f"{prefix}[SLOT_TIMING] tag={tag} duration_ms={duration_ms:.3f} "
        f"drag_active={'True' if drag else 'False'} "
        f"threshold_ms={threshold_ms:.1f} series={series} extra={extra}"
    )


def test_empty_text_returns_zero_metrics():
    out = parse_slot_timing_log_text("")
    assert out["samples"] == 0
    assert out["drag_sample_count"] == 0
    assert out["per_tag"] == {}
    assert out["top_drag_tags"] == []
    assert out["overlap_slot_timing_drag_blocked_ms_total"] == 0.0
    assert out["overlap_slot_timing_worst_drag_call_ms"] == 0.0
    assert out["overlap_slot_timing_worst_drag_tag"] == ""


def test_single_idle_line_round_trip():
    text = _line("thumbnail.complete_series_download", 42.5, drag=False, series="201")
    out = parse_slot_timing_log_text(text)
    assert out["samples"] == 1
    assert out["idle_sample_count"] == 1
    assert out["drag_sample_count"] == 0
    tag_stats = out["per_tag"]["thumbnail.complete_series_download"]
    assert tag_stats["samples"] == 1
    assert tag_stats["drag_samples"] == 0
    assert tag_stats["max_ms"] == 42.5
    assert tag_stats["drag_total_ms"] == 0.0


def test_drag_line_populates_drag_metrics():
    text = _line("thumbnail.complete_series_download", 120.0, drag=True,
                 threshold_ms=8.0, series="202")
    out = parse_slot_timing_log_text(text)
    assert out["drag_sample_count"] == 1
    assert out["overlap_slot_timing_worst_drag_call_ms"] == 120.0
    assert out["overlap_slot_timing_worst_drag_tag"] == \
        "thumbnail.complete_series_download"
    assert out["overlap_slot_timing_drag_blocked_ms_total"] == 120.0


def test_top_drag_tags_ranking_by_total_drag_ms():
    lines = [
        _line("tag.a", 50.0, drag=True),
        _line("tag.a", 70.0, drag=True),
        _line("tag.b", 200.0, drag=True),
        _line("tag.c", 30.0, drag=False),
    ]
    out = parse_slot_timing_log_text("\n".join(lines))
    tags_in_order = [entry["tag"] for entry in out["top_drag_tags"]]
    assert tags_in_order == ["tag.b", "tag.a"]
    assert out["top_drag_tags"][0]["drag_total_ms"] == 200.0
    assert out["top_drag_tags"][1]["drag_total_ms"] == 120.0


def test_idle_only_tag_not_in_top_drag_tags():
    text = _line("thumbnail.update_series_progress", 35.0, drag=False)
    out = parse_slot_timing_log_text(text)
    assert out["top_drag_tags"] == []
    assert out["per_tag"]["thumbnail.update_series_progress"]["drag_total_ms"] == 0.0


def test_diagnostic_logging_prefix_tolerated():
    """Real production lines have a logging-formatter prefix before the tag."""
    prefix = (
        "2026-04-29 15:47:38.435291 | INFO     | pid=27520 tid=37680 | "
        "component=viewer role=main | aipacs.viewer.slot_timing.emit_slot_timing | "
        "action=- study=- series=- job=- viewevt=- fn=- stage=- result=- | "
    )
    text = _line("zetaboost.notify_global_download_stop", 88.123, drag=True,
                 threshold_ms=8.0, series="none", prefix=prefix)
    out = parse_slot_timing_log_text(text)
    assert out["samples"] == 1
    assert out["per_tag"]["zetaboost.notify_global_download_stop"]["drag_max_ms"] == \
        pytest.approx(88.123, abs=0.01)


def test_extra_field_optional():
    text_no_extra = (
        "[SLOT_TIMING] tag=foo duration_ms=15.000 drag_active=False "
        "threshold_ms=30.0 series=none"
    )
    out = parse_slot_timing_log_text(text_no_extra)
    assert out["samples"] == 1


def test_extra_field_with_kv_pairs_does_not_break_parse():
    text = _line("progressive.finalize_terminal", 480.0, drag=True,
                 threshold_ms=8.0, series="201",
                 extra="source=on_series_completed;force=1;viewers=1")
    out = parse_slot_timing_log_text(text)
    assert out["samples"] == 1
    assert out["overlap_slot_timing_worst_drag_call_ms"] == 480.0


def test_malformed_lines_silently_dropped():
    text = "\n".join([
        "[SLOT_TIMING] this is garbage",
        _line("real.tag", 50.0, drag=False),
        "[SLOT_TIMING] tag=x duration_ms=NOTANUMBER drag_active=True threshold_ms=8.0 series=none",
    ])
    out = parse_slot_timing_log_text(text)
    assert out["samples"] >= 1
    assert "real.tag" in out["per_tag"]


def test_per_tag_p50_p95_max_correct():
    lines = [_line("foo", v, drag=False) for v in (10.0, 20.0, 30.0, 40.0, 100.0)]
    out = parse_slot_timing_log_text("\n".join(lines))
    stats = out["per_tag"]["foo"]
    assert stats["samples"] == 5
    assert stats["max_ms"] == 100.0
    assert stats["p50_ms"] >= 20.0
    assert stats["p95_ms"] >= 40.0


def test_drag_total_ms_aggregates_only_drag_samples():
    lines = [
        _line("foo", 100.0, drag=True),
        _line("foo", 200.0, drag=False),
        _line("foo", 50.0, drag=True),
    ]
    out = parse_slot_timing_log_text("\n".join(lines))
    stats = out["per_tag"]["foo"]
    assert stats["drag_total_ms"] == 150.0
    assert stats["samples"] == 3
    assert stats["drag_samples"] == 2


def test_worst_drag_tag_picks_largest_single_call():
    lines = [
        _line("a", 100.0, drag=True),
        _line("b", 200.0, drag=True),
        _line("c", 150.0, drag=True),
    ]
    out = parse_slot_timing_log_text("\n".join(lines))
    assert out["overlap_slot_timing_worst_drag_tag"] == "b"
    assert out["overlap_slot_timing_worst_drag_call_ms"] == 200.0


def test_emit_format_matches_production_helper():
    """Round-trip: helper emits a line; parser sees it."""
    import logging
    from modules.viewer.fast.slot_timing import emit_slot_timing

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    log = logging.getLogger("aipacs.viewer.slot_timing")
    handler = _Capture(level=logging.INFO)
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        ok = emit_slot_timing(
            "round.trip",
            150.0,
            drag_active=True,
            series="201",
            extra={"src": "test"},
        )
        assert ok
        assert records, "emit_slot_timing did not produce a log record"
        msg = records[-1].getMessage()
        out = parse_slot_timing_log_text(msg)
        assert out["samples"] == 1
        assert "round.trip" in out["per_tag"]
        assert out["per_tag"]["round.trip"]["drag_max_ms"] == 150.0
    finally:
        log.removeHandler(handler)


def test_threshold_field_present_but_unused_for_aggregation():
    """Parser captures threshold_ms but does not gate aggregation on it."""
    text = _line("foo", 5.0, drag=True, threshold_ms=8.0)
    out = parse_slot_timing_log_text(text)
    # Even though 5.0 < 8.0 (would not have been emitted normally), if it
    # appears in the log the parser counts it.
    assert out["samples"] == 1


def test_drag_blocked_ms_total_sums_across_tags():
    lines = [
        _line("a", 50.0, drag=True),
        _line("b", 80.0, drag=True),
        _line("c", 40.0, drag=False),
    ]
    out = parse_slot_timing_log_text("\n".join(lines))
    assert out["overlap_slot_timing_drag_blocked_ms_total"] == 130.0
