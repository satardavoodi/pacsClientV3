"""F3.5.1 — DM priority-handoff KPI parser tests.

These tests exercise the ``[INTENT_PRIORITY]``-tag parser added in
``tools/performance/clearcanvas_aipacs_kpi_harness.py``.

The parser consumes the structured emit produced by
``SeriesIntentCoordinator._emit_intent_priority`` and returns a payload that the
KPI harness can compare across sessions.

Plan reference: plan-fastViewerOverlap100PercentImprovement.prompt.prompt.md
Step:           F3.5.1.
"""

from __future__ import annotations

import pytest

from tools.performance.clearcanvas_aipacs_kpi_harness import (
    parse_priority_handoff_log_text,
    _INTENT_PRIORITY_RE,
)


# ---------------------------------------------------------------------------
# Helper: emit a line in the EXACT format produced by
# SeriesIntentCoordinator._emit_intent_priority. Tests round-trip this format
# so any drift in the production emit (e.g. reordered fields) breaks here
# first.
# ---------------------------------------------------------------------------

def _emit(
    *,
    tag,
    study="study-aaaaaaaa-1111-2222-3333-4444",
    series="42",
    attempt=0,
    max_attempts=90,
    recovery=False,
    pool_busy=False,
    pool_active=2,
    pool_max=3,
    state="pending",
    auto_paused=False,
    elapsed_ms=0,
    token=1,
    branch=None,
    reason=None,
):
    parts = [
        f"[INTENT_PRIORITY] tag={tag}",
        f"study={study}",
        f"series={series}",
        f"attempt={attempt}/{max_attempts}",
        f"recovery={recovery}",
        f"pool_busy={pool_busy}",
        f"pool_capacity={pool_active}/{pool_max}",
        f"state={state}",
        f"auto_paused={auto_paused}",
        f"elapsed_ms={elapsed_ms}",
        f"token={token}",
    ]
    if branch is not None:
        parts.append(f"branch={branch}")
    if reason is not None:
        parts.append(f"reason={reason}")
    return " ".join(parts)


def _with_log_prefix(line: str) -> str:
    """Prefix the line with a representative `diagnostic_logging`-style timestamp."""
    return f"2026-04-29 08:30:00,123 INFO download | {line}"


# ---------------------------------------------------------------------------
# Empty input + safe defaults
# ---------------------------------------------------------------------------

def test_parse_priority_handoff_log_text_empty_emits_zero_payload():
    payload = parse_priority_handoff_log_text("")
    assert payload["samples"] == 0
    assert payload["begin_count"] == 0
    assert payload["started_count"] == 0
    assert payload["primary_exhaust_count"] == 0
    assert payload["recovery_exhaust_count"] == 0
    assert payload["overlap_priority_handoff_latency_p50_ms"] == 0.0
    assert payload["overlap_priority_handoff_latency_p95_ms"] == 0.0
    assert payload["overlap_priority_handoff_latency_max_ms"] == 0.0
    assert payload["overlap_priority_handoff_pool_busy_ratio_pct"] == 0.0


def test_parse_priority_handoff_log_text_ignores_unrelated_lines():
    text = "\n".join([
        "2026-04-29 08:30:00 [INTENT] Priority retry already active for x (token=4)",
        "2026-04-29 08:30:01 [B3.8_SCROLL] frame=1 slice=0 total_ms=2.0",
        "2026-04-29 08:30:02 some unrelated download log line",
    ])
    payload = parse_priority_handoff_log_text(text)
    assert payload["samples"] == 0


# ---------------------------------------------------------------------------
# One round-trip per tag
# ---------------------------------------------------------------------------

def test_parse_priority_handoff_log_text_round_trip_begin():
    line = _emit(tag="begin", attempt=0, max_attempts=90)
    payload = parse_priority_handoff_log_text(line)
    assert payload["samples"] == 1
    assert payload["begin_count"] == 1


def test_parse_priority_handoff_log_text_round_trip_tick():
    line = _emit(tag="tick", attempt=5, max_attempts=90)
    payload = parse_priority_handoff_log_text(line)
    assert payload["samples"] == 1
    assert payload["tick_count"] == 1


def test_parse_priority_handoff_log_text_round_trip_defer_pool_busy_true():
    line = _emit(tag="defer", attempt=10, pool_busy=True)
    payload = parse_priority_handoff_log_text(line)
    assert payload["defer_count"] == 1
    assert payload["overlap_priority_handoff_pool_busy_ratio_pct"] == 100.0


def test_parse_priority_handoff_log_text_round_trip_defer_pool_busy_false():
    line = _emit(tag="defer", attempt=10, pool_busy=False)
    payload = parse_priority_handoff_log_text(line)
    assert payload["defer_count"] == 1
    assert payload["overlap_priority_handoff_pool_busy_ratio_pct"] == 0.0


def test_parse_priority_handoff_log_text_round_trip_recover_branch_primary():
    line = _emit(tag="recover", attempt=90, max_attempts=90, branch="primary")
    payload = parse_priority_handoff_log_text(line)
    assert payload["recover_count"] == 1
    # `recover` marks primary chain expiration → counted as primary exhaust.
    assert payload["primary_exhaust_count"] == 1
    assert payload["recovery_exhaust_count"] == 0


def test_parse_priority_handoff_log_text_round_trip_exhaust_branch_recovery():
    line = _emit(
        tag="exhaust",
        attempt=3,
        max_attempts=3,
        recovery=True,
        branch="recovery",
    )
    payload = parse_priority_handoff_log_text(line)
    assert payload["exhaust_count"] == 1
    assert payload["recovery_exhaust_count"] == 1
    assert payload["primary_exhaust_count"] == 0


def test_parse_priority_handoff_log_text_round_trip_started_with_elapsed():
    line = _emit(tag="started", attempt=4, max_attempts=90, elapsed_ms=1234)
    payload = parse_priority_handoff_log_text(line)
    assert payload["started_count"] == 1
    assert payload["overlap_priority_handoff_latency_p50_ms"] == 1234.0
    assert payload["overlap_priority_handoff_latency_p95_ms"] == 1234.0
    assert payload["overlap_priority_handoff_latency_max_ms"] == 1234.0


# ---------------------------------------------------------------------------
# Realistic sequence — chain begin → multiple ticks → started
# ---------------------------------------------------------------------------

def test_parse_priority_handoff_log_text_full_chain_started():
    text = "\n".join([
        _with_log_prefix(_emit(tag="begin", attempt=0, max_attempts=90, elapsed_ms=0)),
        _with_log_prefix(_emit(tag="defer", attempt=0, pool_busy=True, elapsed_ms=12)),
        _with_log_prefix(_emit(tag="defer", attempt=1, pool_busy=True, elapsed_ms=215)),
        _with_log_prefix(_emit(tag="defer", attempt=2, pool_busy=True, elapsed_ms=420)),
        _with_log_prefix(_emit(tag="started", attempt=3, max_attempts=90, elapsed_ms=625)),
    ])
    payload = parse_priority_handoff_log_text(text)
    assert payload["samples"] == 5
    assert payload["begin_count"] == 1
    assert payload["defer_count"] == 3
    assert payload["started_count"] == 1
    assert payload["overlap_priority_handoff_latency_p50_ms"] == 625.0
    assert payload["overlap_priority_handoff_latency_max_ms"] == 625.0
    # All defers had pool_busy=True → 100% pool-busy ratio.
    assert payload["overlap_priority_handoff_pool_busy_ratio_pct"] == 100.0


def test_parse_priority_handoff_log_text_full_chain_exhaust_via_recovery():
    text = "\n".join([
        _with_log_prefix(_emit(tag="begin", attempt=0, max_attempts=90)),
        _with_log_prefix(_emit(tag="recover", attempt=90, max_attempts=90, branch="primary")),
        _with_log_prefix(_emit(
            tag="exhaust",
            attempt=3,
            max_attempts=3,
            recovery=True,
            branch="recovery",
        )),
    ])
    payload = parse_priority_handoff_log_text(text)
    assert payload["begin_count"] == 1
    assert payload["recover_count"] == 1
    assert payload["exhaust_count"] == 1
    # recover bumps primary; exhaust bumps recovery.
    assert payload["primary_exhaust_count"] == 1
    assert payload["recovery_exhaust_count"] == 1
    # No started → latency 0.0.
    assert payload["overlap_priority_handoff_latency_p95_ms"] == 0.0


# ---------------------------------------------------------------------------
# Production emit format compatibility — ensure the regex matches the EXACT
# string built by SeriesIntentCoordinator._emit_intent_priority.
# ---------------------------------------------------------------------------

def test_intent_priority_re_matches_production_emit_format():
    # Reproduce the exact joiner used in production.
    parts = [
        "[INTENT_PRIORITY] tag=started",
        "study=abc123",
        "series=42",
        "attempt=4/90",
        "recovery=False",
        "pool_busy=False",
        "pool_capacity=2/3",
        "state=pending",
        "auto_paused=False",
        "elapsed_ms=625",
        "token=7",
    ]
    line = " ".join(parts)
    m = _INTENT_PRIORITY_RE.search(line)
    assert m is not None
    assert m.group("tag") == "started"
    assert m.group("attempt") == "4"
    assert m.group("max_attempts") == "90"
    assert m.group("elapsed_ms") == "625"
    assert m.group("branch") is None  # branch is optional


def test_intent_priority_re_extracts_branch_field():
    line = (
        "[INTENT_PRIORITY] tag=exhaust study=abc123 series=42 attempt=3/3 "
        "recovery=True pool_busy=False pool_capacity=2/3 state=pending "
        "auto_paused=False elapsed_ms=27000 token=7 branch=recovery"
    )
    m = _INTENT_PRIORITY_RE.search(line)
    assert m is not None
    assert m.group("branch") == "recovery"


def test_parse_priority_handoff_log_text_diagnostic_logging_prefix_tolerated():
    """Production lines arrive prefixed by diagnostic_logging with timestamp +
    component. The parser must locate the [INTENT_PRIORITY] anchor regardless
    of leading text."""
    raw = (
        "2026-04-29 08:30:00,123 INFO download | "
        + _emit(tag="started", attempt=4, max_attempts=90, elapsed_ms=1500)
    )
    payload = parse_priority_handoff_log_text(raw)
    assert payload["samples"] == 1
    assert payload["started_count"] == 1
    assert payload["overlap_priority_handoff_latency_max_ms"] == 1500.0


# ---------------------------------------------------------------------------
# Multi-handoff aggregation — p50 / p95 across many started events.
# ---------------------------------------------------------------------------

def test_parse_priority_handoff_log_text_aggregates_p50_p95_across_handoffs():
    elapsed_samples = [50, 120, 240, 480, 960, 1920, 3840]
    lines = [
        _emit(tag="started", attempt=i, max_attempts=90, elapsed_ms=v, token=i + 1)
        for i, v in enumerate(elapsed_samples)
    ]
    payload = parse_priority_handoff_log_text("\n".join(lines))
    assert payload["started_count"] == len(elapsed_samples)
    # max == max of the input.
    assert payload["overlap_priority_handoff_latency_max_ms"] == 3840.0
    # p50 must lie within the inner-quartile band of the input.
    assert 240.0 <= payload["overlap_priority_handoff_latency_p50_ms"] <= 960.0
    # p95 must approach the max but not exceed it.
    assert payload["overlap_priority_handoff_latency_p95_ms"] >= 1920.0
    assert payload["overlap_priority_handoff_latency_p95_ms"] <= 3840.0


# ---------------------------------------------------------------------------
# F3.5.2 — V2 wall-clock retry path: branch=v2 + reason=<R> aggregation.
# ---------------------------------------------------------------------------


def test_parse_priority_handoff_log_text_round_trip_v2_begin():
    line = _emit(tag="begin", branch="v2", attempt=0, max_attempts=60000)
    payload = parse_priority_handoff_log_text(line)
    assert payload["v2_begin_count"] == 1
    assert payload["begin_count"] == 1


def test_parse_priority_handoff_log_text_round_trip_v2_started():
    line = _emit(tag="started", branch="v2", elapsed_ms=25000, attempt=100)
    payload = parse_priority_handoff_log_text(line)
    assert payload["v2_started_count"] == 1
    assert payload["started_count"] == 1
    assert payload["overlap_priority_handoff_latency_max_ms"] == 25000.0


def test_parse_priority_handoff_log_text_round_trip_v2_defer_reclaimed():
    line = _emit(
        tag="defer", branch="v2", reason="reclaimed", pool_busy=False, attempt=5
    )
    payload = parse_priority_handoff_log_text(line)
    assert payload["v2_defer_reclaimed_count"] == 1
    assert payload["defer_count"] == 1
    # pool_busy=False means it should NOT count toward the busy ratio numerator.
    assert payload["overlap_priority_handoff_pool_busy_ratio_pct"] == 0.0


@pytest.mark.parametrize(
    "reason,counter_key",
    [
        ("pool_busy", "v2_exhaust_pool_busy_count"),
        ("reclaimed", "v2_exhaust_reclaimed_count"),
        ("state_lost", "v2_exhaust_state_lost_count"),
        ("timeout", "v2_exhaust_timeout_count"),
    ],
)
def test_parse_priority_handoff_log_text_v2_exhaust_partitioned_by_reason(
    reason, counter_key
):
    line = _emit(tag="exhaust", branch="v2", reason=reason, attempt=240)
    payload = parse_priority_handoff_log_text(line)
    assert payload[counter_key] == 1
    assert payload["overlap_priority_handoff_v2_total_exhaust_count"] == 1
    # V2 exhaust does NOT inflate primary_exhaust or recovery_exhaust.
    assert payload["primary_exhaust_count"] == 0
    assert payload["recovery_exhaust_count"] == 0


def test_intent_priority_re_captures_optional_reason_field():
    line = _emit(tag="exhaust", branch="v2", reason="timeout")
    m = _INTENT_PRIORITY_RE.search(line)
    assert m is not None
    assert m.group("branch") == "v2"
    assert m.group("reason") == "timeout"


def test_intent_priority_re_legacy_line_without_reason_still_matches():
    line = _emit(tag="exhaust", branch="primary")
    m = _INTENT_PRIORITY_RE.search(line)
    assert m is not None
    assert m.group("branch") == "primary"
    assert m.group("reason") is None


def test_parse_priority_handoff_log_text_v2_full_chain_with_reclamation_race():
    # 1 V2 begin -> 2 reclaimed defers -> 1 started: legitimate F3.5.2 success path.
    lines = [
        _emit(tag="begin", branch="v2"),
        _emit(tag="defer", branch="v2", reason="reclaimed", attempt=1, pool_busy=False),
        _emit(tag="defer", branch="v2", reason="reclaimed", attempt=2, pool_busy=False),
        _emit(tag="started", branch="v2", elapsed_ms=25500, attempt=100),
    ]
    payload = parse_priority_handoff_log_text("\n".join(lines))
    assert payload["v2_begin_count"] == 1
    assert payload["v2_started_count"] == 1
    assert payload["v2_defer_reclaimed_count"] == 2
    assert payload["overlap_priority_handoff_v2_total_exhaust_count"] == 0
    assert payload["recovery_exhaust_count"] == 0
