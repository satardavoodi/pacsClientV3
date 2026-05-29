"""v2.3.8 R15: Advanced (VTK) viewer protected-interaction latch tests.

Validates that the parallel Advanced latch extends the unified
``is_protected_drag_active()`` predicate so R3/R4/R5 policies cover
Advanced viewer wheel/stack interactions without touching their read
sites.
"""
from __future__ import annotations

import time

import pytest

from modules.viewer.fast import ui_throttle


@pytest.fixture(autouse=True)
def _reset_latches():
    """Ensure a clean latch state for each test."""
    # Clear both FAST and Advanced latches via the public APIs.
    ui_throttle.record_protected_drag(False, grace_ms=0.0)
    ui_throttle.record_advanced_protected_interaction(False, grace_ms=0.0)
    yield
    ui_throttle.record_protected_drag(False, grace_ms=0.0)
    ui_throttle.record_advanced_protected_interaction(False, grace_ms=0.0)


def test_advanced_latch_alone_marks_protected():
    assert ui_throttle.is_protected_drag_active() is False
    ui_throttle.record_advanced_protected_interaction(True, grace_ms=1000.0, source="wheel")
    assert ui_throttle.is_protected_drag_active() is True


def test_advanced_latch_release_respects_grace_window():
    ui_throttle.record_advanced_protected_interaction(True, grace_ms=1000.0, source="wheel")
    assert ui_throttle.is_protected_drag_active() is True
    ui_throttle.record_advanced_protected_interaction(False, grace_ms=200.0, source="gc_reenable")
    # Active latch cleared, but grace window still open.
    assert ui_throttle.is_protected_drag_active() is True
    # Wait past grace window.
    time.sleep(0.25)
    assert ui_throttle.is_protected_drag_active() is False


def test_advanced_latch_does_not_disturb_fast_latch():
    ui_throttle.record_protected_drag(True, grace_ms=1500.0)
    ui_throttle.record_advanced_protected_interaction(True, grace_ms=1000.0, source="wheel")
    ui_throttle.record_advanced_protected_interaction(False, grace_ms=0.0)
    # FAST latch must still hold the protection flag.
    assert ui_throttle.is_protected_drag_active() is True
    ui_throttle.record_protected_drag(False, grace_ms=0.0)
    assert ui_throttle.is_protected_drag_active() is False


def test_keepalive_semantics_only_extend_deadline():
    ui_throttle.record_advanced_protected_interaction(True, grace_ms=2500.0, source="stack_drag")
    # A later begin with a SMALLER grace must not shorten the deadline.
    ui_throttle.record_advanced_protected_interaction(True, grace_ms=100.0, source="stack_drag")
    time.sleep(0.15)
    assert ui_throttle.is_protected_drag_active() is True


def test_dm_progress_skip_path_sees_advanced_latch():
    """R5: ``_apply_throttled_progress`` checks ``is_protected_drag_active()``.

    Confirm the unified predicate reports True for Advanced-only activity so
    no code change at the DM read site is required.
    """
    assert ui_throttle.is_protected_drag_active() is False
    ui_throttle.record_advanced_protected_interaction(True, grace_ms=1500.0, source="stack_drag")
    # R5 reads this value (modules/download_manager/ui/widget/_dm_workers.py).
    assert ui_throttle.is_protected_drag_active() is True


def test_admission_shell_denies_cache_warm_during_advanced_drag():
    """R3: ``should_admit(CACHE_WARM)`` denies unconditionally while protected."""
    from modules.viewer.fast.system_load_controller import WorkClass

    ui_throttle.record_advanced_protected_interaction(True, grace_ms=1500.0, source="wheel")
    admitted = ui_throttle.should_admit(WorkClass.CACHE_WARM, {"owner": "test"})
    assert admitted is False


def test_advanced_begin_without_grace_keeps_active_flag():
    """``active=True`` with ``grace_ms=0`` still latches the flag."""
    ui_throttle.record_advanced_protected_interaction(True, grace_ms=0.0, source="wheel")
    assert ui_throttle.is_protected_drag_active() is True
    # But once we explicitly release with no grace, it clears immediately.
    ui_throttle.record_advanced_protected_interaction(False, grace_ms=0.0)
    assert ui_throttle.is_protected_drag_active() is False
