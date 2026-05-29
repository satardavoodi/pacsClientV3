"""Tests for DM plan-step payload builder and CLI parser wiring."""
from __future__ import annotations

import sys
from pathlib import Path


_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


from tools.performance.clearcanvas_aipacs_kpi_harness import (
    build_dm_plan_step_payload_from_log_text,
    build_parser,
)


def test_build_dm_plan_step_payload_contains_expected_sections():
    text = "\n".join(
        [
            "2026-05-06 22:17:57.343466 INFO diagnostic_logging: pid=33000 [DM_REBUILD] event=defer_hidden depth=1 caller=_dm_details.py:_refresh_table_order",
            "2026-05-06 22:18:30.100000 INFO diagnostic_logging: pid=33000 [DM_REBUILD] event=enter depth=1 caller=_dm_details.py:_refresh_table_order",
            "2026-05-06 22:18:34.489222 INFO diagnostic_logging: pid=33000 [DM_REBUILD] event=exit depth=1 duration_ms=47.329 rows=8 caller=_dm_details.py:_refresh_table_order",
            "2026-05-06 22:18:35.000000 WARNING diagnostic_logging: [DM_PRIORITY_TRANSITION] event=combo_changed new=Critical study=2.25.1 during_rebuild=False",
            "2026-05-06 22:18:36.000000 WARNING diagnostic_logging: [INTENT_PRIORITY] tag=started study=2.25.1 series=12 attempt=2/90 recovery=False pool_busy=False pool_capacity=1/1 state=PENDING auto_paused=False elapsed_ms=240 token=7 branch=primary",
        ]
    )

    payload = build_dm_plan_step_payload_from_log_text(text)
    assert payload["mode"] == "dm-plan-step-eval"
    assert "dm_rebuild_metrics" in payload
    assert "dm_rebuild_session_metrics" in payload
    assert "dm_priority_transition_metrics" in payload
    assert "dm_priority_handoff_metrics" in payload
    assert "dm_plan_step_gates" in payload

    latest = payload["dm_rebuild_session_metrics"]["dm_rebuild_latest_session"]
    assert latest is not None
    assert latest["pid"] == "33000"
    assert latest["dm_rebuild_duration_max_ms"] == 47.329


def test_build_dm_plan_step_payload_respects_target_overrides():
    text = "\n".join(
        [
            "2026-05-06 22:00:00.000 INFO x: pid=1 [DM_REBUILD] event=enter depth=1 caller=A",
            "2026-05-06 22:00:00.200 INFO x: pid=1 [DM_REBUILD] event=exit depth=1 duration_ms=90.0 rows=3 caller=A",
            "2026-05-06 22:00:00.210 WARNING x: [DM_PRIORITY_TRANSITION] event=combo_changed new=Critical study=2.25.1 during_rebuild=False",
            "2026-05-06 22:00:00.220 WARNING x: [INTENT_PRIORITY] tag=started study=2.25.1 series=1 attempt=1/90 recovery=False pool_busy=False pool_capacity=0/1 state=PENDING auto_paused=False elapsed_ms=100 token=1 branch=primary",
        ]
    )

    strict_payload = build_dm_plan_step_payload_from_log_text(
        text,
        dm_p95_target_ms=80.0,
        dm_max_target_ms=200.0,
    )
    loose_payload = build_dm_plan_step_payload_from_log_text(
        text,
        dm_p95_target_ms=120.0,
        dm_max_target_ms=200.0,
    )

    assert strict_payload["dm_plan_step_gates"]["steps"]["phase1a_global_budget"]["pass"] is False
    assert loose_payload["dm_plan_step_gates"]["steps"]["phase1a_global_budget"]["pass"] is True


def test_build_parser_has_evaluate_dm_plan_steps_command():
    parser = build_parser()
    args = parser.parse_args([
        "evaluate-dm-plan-steps",
        "--log",
        "user_data/logs/download_diagnostics.log",
        "--dm-p95-target-ms",
        "70",
        "--dm-max-target-ms",
        "180",
    ])

    assert args.command == "evaluate-dm-plan-steps"
    assert args.log.endswith("download_diagnostics.log")
    assert args.dm_p95_target_ms == 70.0
    assert args.dm_max_target_ms == 180.0
    assert callable(args.func)
