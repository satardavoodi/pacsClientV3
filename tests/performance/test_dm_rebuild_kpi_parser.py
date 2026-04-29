"""KPI parser round-trip tests for ``[DM_REBUILD]`` and
``[DM_PRIORITY_TRANSITION]`` log tags.

Format contract is locked. If any production emit changes, this test
file MUST be updated in the same commit.

Plan reference: docs/plans/performance/DM_TABLE_REBUILD_STORM_2026-04-29.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


from tools.performance.clearcanvas_aipacs_kpi_harness import (
    parse_dm_priority_transition_log_text,
    parse_dm_rebuild_log_text,
)


# ────────────────────────────────────────────────────────────────────────────
# parse_dm_rebuild_log_text
# ────────────────────────────────────────────────────────────────────────────


class TestDmRebuildParser:
    def test_empty_text_returns_zero_counters(self):
        result = parse_dm_rebuild_log_text("")
        assert result["dm_rebuild_count"] == 0
        assert result["dm_rebuild_recursive_count"] == 0
        assert result["dm_rebuild_max_depth"] == 0
        assert result["dm_rebuild_duration_p95_ms"] == 0.0
        assert result["top_callers"] == []

    def test_single_rebuild_round_trip(self):
        text = (
            "2026-04-29 18:04:42.764 INFO [DM_REBUILD] event=enter depth=1 "
            "caller=series_intent_coordinator.py:request_critical_series\n"
            "2026-04-29 18:04:43.165 INFO [DM_REBUILD] event=exit depth=1 "
            "duration_ms=400.789 rows=12 "
            "caller=series_intent_coordinator.py:request_critical_series\n"
        )
        result = parse_dm_rebuild_log_text(text)
        assert result["dm_rebuild_count"] == 1
        assert result["dm_rebuild_enter_count"] == 1
        assert result["dm_rebuild_recursive_count"] == 0
        assert result["dm_rebuild_max_depth"] == 1
        assert result["dm_rebuild_duration_p95_ms"] == 400.789
        assert result["dm_rebuild_duration_max_ms"] == 400.789
        assert len(result["top_callers"]) == 1
        assert (
            result["top_callers"][0]["caller"]
            == "series_intent_coordinator.py:request_critical_series"
        )

    def test_recursive_rebuild_counted(self):
        """Pre-fix scenario: depth=1 enter, then nested depth=2 enter+exit
        (the ghost combo signal), then depth=1 exit."""
        text = (
            "[DM_REBUILD] event=enter depth=1 caller=request_critical_series\n"
            "[DM_REBUILD] event=enter depth=2 caller=_on_priority_changed\n"
            "[DM_REBUILD] event=exit depth=2 duration_ms=180.0 rows=12 "
            "caller=_on_priority_changed\n"
            "[DM_REBUILD] event=exit depth=1 duration_ms=405.0 rows=12 "
            "caller=request_critical_series\n"
        )
        result = parse_dm_rebuild_log_text(text)
        assert result["dm_rebuild_count"] == 2
        assert result["dm_rebuild_recursive_count"] == 1
        assert result["dm_rebuild_max_depth"] == 2

    def test_reenter_skip_counted_separately(self):
        text = (
            "[DM_REBUILD] event=enter depth=1 caller=foo\n"
            "[DM_REBUILD] event=reenter_skip depth=1 caller=bar\n"
            "[DM_REBUILD] event=reenter_skip depth=1 caller=baz\n"
            "[DM_REBUILD] event=exit depth=1 duration_ms=50.0 rows=5 caller=foo\n"
        )
        result = parse_dm_rebuild_log_text(text)
        assert result["dm_rebuild_count"] == 1
        assert result["dm_rebuild_reenter_skip_count"] == 2
        # reenter_skips do NOT bump recursive_count (they're rejected
        # before depth increments).
        assert result["dm_rebuild_recursive_count"] == 0

    def test_percentiles_aggregate_correctly(self):
        # Five rebuilds, durations 10, 50, 100, 200, 500 ms.
        lines = []
        for d in (10.0, 50.0, 100.0, 200.0, 500.0):
            lines.append(
                f"[DM_REBUILD] event=exit depth=1 duration_ms={d} rows=1 caller=xxx"
            )
        result = parse_dm_rebuild_log_text("\n".join(lines))
        assert result["dm_rebuild_count"] == 5
        # p50 ~ 100, p95 ~ 500
        assert result["dm_rebuild_duration_p50_ms"] == 100.0
        assert result["dm_rebuild_duration_p95_ms"] == 500.0
        assert result["dm_rebuild_duration_max_ms"] == 500.0
        assert result["dm_rebuild_per_session_total_ms"] == 860.0

    def test_top_callers_ranked_by_total_ms(self):
        text = "\n".join(
            [
                "[DM_REBUILD] event=exit depth=1 duration_ms=10.0 rows=1 caller=A",
                "[DM_REBUILD] event=exit depth=1 duration_ms=20.0 rows=1 caller=A",
                "[DM_REBUILD] event=exit depth=1 duration_ms=200.0 rows=1 caller=B",
                "[DM_REBUILD] event=exit depth=1 duration_ms=5.0 rows=1 caller=C",
            ]
        )
        result = parse_dm_rebuild_log_text(text)
        assert result["top_callers"][0]["caller"] == "B"
        assert result["top_callers"][0]["total_ms"] == 200.0
        assert result["top_callers"][1]["caller"] == "A"
        assert result["top_callers"][1]["total_ms"] == 30.0
        assert result["top_callers"][2]["caller"] == "C"

    def test_malformed_lines_silently_dropped(self):
        text = (
            "[DM_REBUILD] this is malformed\n"
            "[DM_REBUILD] event=exit depth=1 duration_ms=42.0 rows=2 caller=ok\n"
            "garbage line with no tag\n"
            "[DM_REBUILD] event=oops depth=1 caller=ignored\n"  # unknown event
        )
        result = parse_dm_rebuild_log_text(text)
        assert result["dm_rebuild_count"] == 1
        assert result["dm_rebuild_duration_max_ms"] == 42.0


# ────────────────────────────────────────────────────────────────────────────
# parse_dm_priority_transition_log_text
# ────────────────────────────────────────────────────────────────────────────


class TestDmPriorityTransitionParser:
    def test_during_rebuild_count_is_regression_alarm(self):
        """If any [DM_PRIORITY_TRANSITION] line shows
        during_rebuild=True, the G8.1 fix has regressed."""
        text = (
            "[DM_PRIORITY_TRANSITION] event=combo_changed new=Critical "
            "study=2.25.1234 during_rebuild=False\n"
            "[DM_PRIORITY_TRANSITION] event=combo_changed new=Normal "
            "study=2.25.1234 during_rebuild=True\n"
        )
        result = parse_dm_priority_transition_log_text(text)
        assert result["priority_combo_signal_count"] == 2
        assert result["priority_combo_signal_during_rebuild_count"] == 1
        assert result["priority_combo_signal_by_priority"]["Critical"] == 1
        assert result["priority_combo_signal_by_priority"]["Normal"] == 1

    def test_zero_during_rebuild_post_fix(self):
        """Post-G8.1 production logs should show during_rebuild=False
        for every transition (only user-driven changes survive)."""
        text = (
            "[DM_PRIORITY_TRANSITION] event=combo_changed new=High "
            "study=2.25.1234 during_rebuild=False\n"
            "[DM_PRIORITY_TRANSITION] event=combo_changed new=Critical "
            "study=2.25.5678 during_rebuild=False\n"
        )
        result = parse_dm_priority_transition_log_text(text)
        assert result["priority_combo_signal_during_rebuild_count"] == 0
        assert result["priority_combo_signal_count"] == 2

    def test_empty_input_returns_zero(self):
        result = parse_dm_priority_transition_log_text("")
        assert result["priority_combo_signal_count"] == 0
        assert result["priority_combo_signal_during_rebuild_count"] == 0
        assert result["priority_combo_signal_by_priority"] == {}


# ────────────────────────────────────────────────────────────────────────────
# Production emit format contract
# ────────────────────────────────────────────────────────────────────────────


class TestProductionEmitFormatContract:
    """Round-trip the EXACT format produced by the production code in
    `_dm_details.py::_refresh_table_order` and
    `_dm_controls.py::_on_priority_changed`. If either emit changes, this
    test must be updated in the same commit.
    """

    def test_dm_rebuild_enter_format(self):
        # Exact format string used in `_refresh_table_order`:
        #   "[DM_REBUILD] event=enter depth=%d caller=%s"
        line = "[DM_REBUILD] event=enter depth=1 caller=_dm_details.py:_refresh_table_order"
        result = parse_dm_rebuild_log_text(line)
        assert result["dm_rebuild_enter_count"] == 1
        assert result["dm_rebuild_count"] == 0  # enter alone does not count

    def test_dm_rebuild_exit_format(self):
        # Exact format string used in `_refresh_table_order`:
        #   "[DM_REBUILD] event=exit depth=%d duration_ms=%.3f rows=%d"
        line = (
            "[DM_REBUILD] event=exit depth=1 duration_ms=42.123 rows=7"
        )
        result = parse_dm_rebuild_log_text(line)
        assert result["dm_rebuild_count"] == 1
        assert result["dm_rebuild_duration_max_ms"] == 42.123

    def test_dm_priority_transition_exact_format(self):
        # Exact format string used in `_on_priority_changed`:
        #   "[DM_PRIORITY_TRANSITION] event=combo_changed new=%s study=%s during_rebuild=%s"
        line = (
            "[DM_PRIORITY_TRANSITION] event=combo_changed new=Critical "
            "study=2.25.987 during_rebuild=False"
        )
        result = parse_dm_priority_transition_log_text(line)
        assert result["priority_combo_signal_count"] == 1
        assert result["priority_combo_signal_during_rebuild_count"] == 0

    def test_log_with_diagnostic_logging_prefix_still_parses(self):
        """Production lines have `<timestamp> <level> diagnostic_logging:`
        prefix — the parser must tolerate it."""
        line = (
            "2026-04-29 18:04:42.764 INFO diagnostic_logging: "
            "[DM_REBUILD] event=exit depth=2 duration_ms=180.500 rows=12 "
            "caller=_on_priority_changed\n"
        )
        result = parse_dm_rebuild_log_text(line)
        assert result["dm_rebuild_count"] == 1
        assert result["dm_rebuild_recursive_count"] == 1
        assert result["dm_rebuild_max_depth"] == 2
