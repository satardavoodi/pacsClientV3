"""Plan-step KPI gate tests for DM optimization workflow.

These tests ensure each plan step has deterministic pass/fail checks from
metrics fixtures, so progression is test-driven rather than manual.
"""
from __future__ import annotations

import sys
from pathlib import Path


_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


from tools.performance.clearcanvas_aipacs_kpi_harness import (
    evaluate_dm_plan_step_results,
    parse_priority_handoff_sessions_log_text,
)


def _base_rebuild_metrics(**overrides):
    data = {
        "dm_rebuild_enter_count": 5,
        "dm_rebuild_count": 4,
        "dm_rebuild_recursive_count": 0,
        "dm_rebuild_reenter_skip_count": 0,
        "dm_rebuild_duration_p95_ms": 60.0,
        "dm_rebuild_duration_max_ms": 120.0,
    }
    data.update(overrides)
    return data


def _base_priority_transition_metrics(**overrides):
    data = {
        "priority_combo_signal_during_rebuild_count": 0,
    }
    data.update(overrides)
    return data


def _base_latest_session_metrics(**overrides):
    data = {
        "dm_rebuild_duration_p95_ms": 47.329,
        "dm_rebuild_duration_max_ms": 47.329,
        "dm_rebuild_recursive_count": 0,
        "dm_rebuild_reenter_skip_count": 0,
        "dm_rebuild_defer_hidden_count": 10,
    }
    data.update(overrides)
    return data


def test_all_plan_steps_pass_with_green_metrics():
    result = evaluate_dm_plan_step_results(
        rebuild_metrics=_base_rebuild_metrics(),
        priority_transition_metrics=_base_priority_transition_metrics(),
        latest_session_metrics=_base_latest_session_metrics(),
        priority_handoff_metrics={"primary_exhaust_count": 0, "recovery_exhaust_count": 0},
    )

    assert result["overall_pass"] is True
    assert result["steps"]["phase0_integrity"]["pass"] is True
    assert result["steps"]["phase1a_global_budget"]["pass"] is True
    assert result["steps"]["phase1a_latest_budget"]["pass"] is True
    assert result["steps"]["phase1b_hidden_defer"]["pass"] is True
    assert result["steps"]["phase1b_observer_fanout"]["pass"] is True
    assert result["steps"]["phase1c_priority_handoff"]["pass"] is True


def test_phase1a_global_budget_fails_when_rebuild_budget_exceeded():
    result = evaluate_dm_plan_step_results(
        rebuild_metrics=_base_rebuild_metrics(dm_rebuild_duration_p95_ms=1019.6, dm_rebuild_duration_max_ms=2129.8),
        priority_transition_metrics=_base_priority_transition_metrics(),
        latest_session_metrics=_base_latest_session_metrics(),
        priority_handoff_metrics={"primary_exhaust_count": 0, "recovery_exhaust_count": 0},
    )

    assert result["steps"]["phase1a_global_budget"]["pass"] is False
    assert result["overall_pass"] is False


def test_phase1a_latest_budget_can_pass_even_when_global_historical_is_red():
    result = evaluate_dm_plan_step_results(
        rebuild_metrics=_base_rebuild_metrics(dm_rebuild_duration_p95_ms=900.0, dm_rebuild_duration_max_ms=1800.0),
        priority_transition_metrics=_base_priority_transition_metrics(),
        latest_session_metrics=_base_latest_session_metrics(dm_rebuild_duration_p95_ms=47.3, dm_rebuild_duration_max_ms=47.3),
        priority_handoff_metrics={"primary_exhaust_count": 0, "recovery_exhaust_count": 0},
    )

    assert result["steps"]["phase1a_global_budget"]["pass"] is False
    assert result["steps"]["phase1a_latest_budget"]["pass"] is True


def test_phase0_integrity_fails_on_ghost_or_recursion_signal():
    result = evaluate_dm_plan_step_results(
        rebuild_metrics=_base_rebuild_metrics(dm_rebuild_recursive_count=1),
        priority_transition_metrics=_base_priority_transition_metrics(priority_combo_signal_during_rebuild_count=1),
        latest_session_metrics=_base_latest_session_metrics(),
        priority_handoff_metrics={"primary_exhaust_count": 0, "recovery_exhaust_count": 0},
    )

    assert result["steps"]["phase0_integrity"]["pass"] is False


def test_phase1c_priority_handoff_fails_when_exhaust_present():
    result = evaluate_dm_plan_step_results(
        rebuild_metrics=_base_rebuild_metrics(),
        priority_transition_metrics=_base_priority_transition_metrics(),
        latest_session_metrics=_base_latest_session_metrics(),
        priority_handoff_metrics={"primary_exhaust_count": 2, "recovery_exhaust_count": 1},
    )

    assert result["steps"]["phase1c_priority_handoff"]["pass"] is False


def test_missing_optional_inputs_mark_steps_not_passed_with_reason():
    result = evaluate_dm_plan_step_results(
        rebuild_metrics=_base_rebuild_metrics(),
        priority_transition_metrics=_base_priority_transition_metrics(),
        latest_session_metrics=None,
        priority_handoff_metrics=None,
    )

    assert result["steps"]["phase1a_latest_budget"]["pass"] is False
    assert result["steps"]["phase1b_hidden_defer"]["pass"] is False
    assert result["steps"]["phase1c_priority_handoff"]["pass"] is False
    assert "not provided" in result["steps"]["phase1a_latest_budget"]["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1C — latest-session handoff gate (V2 default-on validation)
# ─────────────────────────────────────────────────────────────────────────────

def test_phase1c_passes_when_latest_session_clean_despite_global_historical_exhaust():
    """Latest-session zero exhaust overrides global aggregate with historical hits."""
    result = evaluate_dm_plan_step_results(
        rebuild_metrics=_base_rebuild_metrics(),
        priority_transition_metrics=_base_priority_transition_metrics(),
        latest_session_metrics=_base_latest_session_metrics(),
        priority_handoff_metrics={"primary_exhaust_count": 10, "recovery_exhaust_count": 7},
        latest_handoff_session_metrics={
            "primary_exhaust_count": 0,
            "recovery_exhaust_count": 0,
            "v2_exhaust_count": 0,
        },
    )

    assert result["steps"]["phase1c_priority_handoff"]["pass"] is True
    assert "latest session" in result["steps"]["phase1c_priority_handoff"]["reason"]
    assert "primary=0" in result["steps"]["phase1c_priority_handoff"]["reason"]


def test_phase1c_fails_when_latest_session_has_v2_exhaust():
    """V2 exhaust in latest session makes gate fail."""
    result = evaluate_dm_plan_step_results(
        rebuild_metrics=_base_rebuild_metrics(),
        priority_transition_metrics=_base_priority_transition_metrics(),
        latest_session_metrics=_base_latest_session_metrics(),
        priority_handoff_metrics={"primary_exhaust_count": 0, "recovery_exhaust_count": 0},
        latest_handoff_session_metrics={
            "primary_exhaust_count": 0,
            "recovery_exhaust_count": 0,
            "v2_exhaust_count": 1,
        },
    )

    assert result["steps"]["phase1c_priority_handoff"]["pass"] is False
    assert "v2=1" in result["steps"]["phase1c_priority_handoff"]["reason"]


def test_phase1c_falls_back_to_global_when_no_latest_session():
    """Without latest_handoff_session_metrics, global aggregate is used."""
    result = evaluate_dm_plan_step_results(
        rebuild_metrics=_base_rebuild_metrics(),
        priority_transition_metrics=_base_priority_transition_metrics(),
        latest_session_metrics=_base_latest_session_metrics(),
        priority_handoff_metrics={"primary_exhaust_count": 2, "recovery_exhaust_count": 0},
        latest_handoff_session_metrics=None,
    )

    assert result["steps"]["phase1c_priority_handoff"]["pass"] is False
    assert "global aggregate" in result["steps"]["phase1c_priority_handoff"]["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# parse_priority_handoff_sessions_log_text round-trip
# ─────────────────────────────────────────────────────────────────────────────

_SAMPLE_INTENT_LINES = """\
2026-05-06 10:00:00 pid=1234 [INTENT_PRIORITY] tag=begin study=UID1 series=1 attempt=0/60000 recovery=False pool_busy=True pool_capacity=1/1 state=PENDING auto_paused=False elapsed_ms=0 token=100 branch=v2
2026-05-06 10:00:01 pid=1234 [INTENT_PRIORITY] tag=defer study=UID1 series=1 attempt=1/60000 recovery=False pool_busy=True pool_capacity=1/1 state=PENDING auto_paused=False elapsed_ms=250 token=100 branch=v2
2026-05-06 10:00:02 pid=1234 [INTENT_PRIORITY] tag=started study=UID1 series=1 attempt=4/60000 recovery=False pool_busy=False pool_capacity=0/1 state=PENDING auto_paused=False elapsed_ms=1000 token=100 branch=v2
2026-05-06 10:00:03 pid=1234 [INTENT_PRIORITY] tag=begin study=UID2 series=2 attempt=0/60000 recovery=False pool_busy=True pool_capacity=1/1 state=PENDING auto_paused=False elapsed_ms=0 token=101 branch=v2
2026-05-06 10:00:60 pid=1234 [INTENT_PRIORITY] tag=exhaust study=UID2 series=2 attempt=240/60000 recovery=False pool_busy=True pool_capacity=1/1 state=PENDING auto_paused=False elapsed_ms=60001 token=101 branch=v2 reason=timeout
"""


def test_parse_priority_handoff_sessions_groups_by_pid():
    metrics = parse_priority_handoff_sessions_log_text(_SAMPLE_INTENT_LINES)
    assert metrics["priority_handoff_session_count"] == 1
    session = metrics["priority_handoff_sessions"][0]
    assert session["pid"] == "1234"
    assert session["begin_count"] == 2
    assert session["v2_started_count"] == 1
    assert session["v2_exhaust_count"] == 1
    assert session["total_exhaust_count"] == 1
    assert metrics["priority_handoff_latest_pid"] == "1234"


def test_parse_priority_handoff_sessions_multi_pid():
    """Two PIDs produce two sessions; latest is the one with the later timestamp."""
    lines = (
        "2026-05-06 09:00:00 pid=100 [INTENT_PRIORITY] tag=begin study=U1 series=1 attempt=0/90 recovery=False pool_busy=True pool_capacity=1/1 state=PENDING auto_paused=False elapsed_ms=0 token=1\n"
        "2026-05-06 09:00:01 pid=100 [INTENT_PRIORITY] tag=exhaust study=U1 series=1 attempt=90/90 recovery=True pool_busy=True pool_capacity=1/1 state=PENDING auto_paused=False elapsed_ms=19000 token=1 branch=recovery\n"
        "2026-05-06 10:00:00 pid=200 [INTENT_PRIORITY] tag=begin study=U2 series=2 attempt=0/60000 recovery=False pool_busy=True pool_capacity=1/1 state=PENDING auto_paused=False elapsed_ms=0 token=2 branch=v2\n"
        "2026-05-06 10:00:01 pid=200 [INTENT_PRIORITY] tag=started study=U2 series=2 attempt=4/60000 recovery=False pool_busy=False pool_capacity=0/1 state=PENDING auto_paused=False elapsed_ms=800 token=2 branch=v2\n"
    )
    metrics = parse_priority_handoff_sessions_log_text(lines)
    assert metrics["priority_handoff_session_count"] == 2
    assert metrics["priority_handoff_latest_pid"] == "200"
    latest = metrics["priority_handoff_latest_session"]
    # Latest session (pid=200) is clean
    assert latest["v2_started_count"] == 1
    assert latest["total_exhaust_count"] == 0
    # Older session (pid=100) had recovery exhaust
    old = next(s for s in metrics["priority_handoff_sessions"] if s["pid"] == "100")
    assert old["recovery_exhaust_count"] == 1


def test_parse_priority_handoff_sessions_empty_text():
    metrics = parse_priority_handoff_sessions_log_text("")
    assert metrics["priority_handoff_session_count"] == 0
    assert metrics["priority_handoff_latest_session"] is None
