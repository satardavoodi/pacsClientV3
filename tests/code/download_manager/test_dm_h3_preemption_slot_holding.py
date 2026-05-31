"""DM-H3 / S4.1 guard: preemption must treat slot-holding states (not just
DOWNLOADING) as preemptable.

Background: MAX_CONCURRENT_STUDIES == 1. A study can hold the single worker slot
in a non-DOWNLOADING state (e.g. VALIDATING). Before S4.1, evaluate_preemption
only considered status == DOWNLOADING, so a VALIDATING slot-holder was invisible
to preemption and a higher-priority (just-opened) study waited behind it — the
"download starts slowly after opening a patient" symptom.

These tests pin the fixed behavior so a future refactor can't silently revert it.
evaluate_preemption only reads .priority / .status / .study_uid off its inputs, so
lightweight stubs are sufficient (no heavy model/Qt construction).
"""
from types import SimpleNamespace

from modules.download_manager.rules.priority_rules import PriorityRules
from modules.download_manager.core.enums import (
    DownloadPriority,
    DownloadStatus,
    PreemptionAction,
)


def _rules():
    return PriorityRules(state_store=None, config={})


def _state(uid, status, priority):
    return SimpleNamespace(study_uid=uid, status=status, priority=priority)


def test_high_preempts_validating_slot_holder():
    """A just-opened HIGH study must preempt a NORMAL study holding the slot in VALIDATING."""
    result = _rules().evaluate_preemption(
        SimpleNamespace(priority=DownloadPriority.HIGH),
        [_state("bg", DownloadStatus.VALIDATING, DownloadPriority.NORMAL)],
    )
    assert result.action == PreemptionAction.PREEMPT_LOWER
    assert "bg" in result.affected_downloads


def test_critical_pauses_validating_slot_holder():
    """CRITICAL must pause a slot-holder that is VALIDATING (any priority)."""
    result = _rules().evaluate_preemption(
        SimpleNamespace(priority=DownloadPriority.CRITICAL),
        [_state("bg", DownloadStatus.VALIDATING, DownloadPriority.NORMAL)],
    )
    assert result.action == PreemptionAction.PAUSE_ALL
    assert "bg" in result.affected_downloads


def test_high_still_preempts_downloading():
    """Existing behavior preserved: HIGH preempts a DOWNLOADING NORMAL study."""
    result = _rules().evaluate_preemption(
        SimpleNamespace(priority=DownloadPriority.HIGH),
        [_state("bg", DownloadStatus.DOWNLOADING, DownloadPriority.NORMAL)],
    )
    assert result.action == PreemptionAction.PREEMPT_LOWER
    assert "bg" in result.affected_downloads


def test_no_active_downloads_queues():
    """No slot-holders -> nothing to preempt -> QUEUE."""
    result = _rules().evaluate_preemption(
        SimpleNamespace(priority=DownloadPriority.HIGH), []
    )
    assert result.action == PreemptionAction.QUEUE
    assert result.affected_downloads == []
