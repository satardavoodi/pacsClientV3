"""Lost end notifications must not permanently starve background UI work."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from modules.viewer.fast import ui_throttle as throttle


@pytest.fixture
def clock(monkeypatch):
    app = QApplication.instance() or QApplication([])
    now = [1000.0]
    monkeypatch.setattr(throttle, '_now_ms', lambda: now[0])
    for field in ('_PROTECTED_DRAG_ACTIVE', '_ADVANCED_PROTECTED_ACTIVE'):
        monkeypatch.setattr(throttle, field, False)
    for field in ('_PROTECTED_DRAG_UNTIL_MS', '_ADVANCED_PROTECTED_UNTIL_MS',
                  '_PROTECTED_DRAG_BEGIN_MS', '_ADVANCED_PROTECTED_BEGIN_MS'):
        monkeypatch.setattr(throttle, field, 0.0)
    monkeypatch.setattr(QApplication, 'mouseButtons', lambda: Qt.MouseButton.NoButton)
    yield now
    assert app is not None


@pytest.mark.parametrize('domain', ['fast', 'advanced'])
def test_missing_end_recovers_after_idle(clock, domain):
    if domain == 'fast':
        throttle.record_protected_drag(True, grace_ms=1500)
    else:
        throttle.record_advanced_protected_interaction(True, grace_ms=2500)
    clock[0] += 86400000
    assert not throttle.is_protected_drag_active()


@pytest.mark.parametrize('domain', ['fast', 'advanced'])
def test_held_mouse_keeps_long_drag_protected(clock, monkeypatch, domain):
    if domain == 'fast':
        throttle.record_protected_drag(True, grace_ms=1500)
    else:
        throttle.record_advanced_protected_interaction(True, grace_ms=2500)
    clock[0] += 86400000
    monkeypatch.setattr(QApplication, 'mouseButtons', lambda: Qt.MouseButton.LeftButton)
    assert throttle.is_protected_drag_active()


def test_recent_keepalive_and_tail_remain_protected(clock):
    throttle.record_advanced_protected_interaction(True, grace_ms=2500)
    clock[0] += 86400000
    throttle.record_advanced_protected_interaction(True, grace_ms=2500)
    assert throttle.is_protected_drag_active()
    throttle.record_advanced_protected_interaction(False, grace_ms=250)
    assert throttle.is_protected_drag_active()


def test_refresh_button_requests_queue_recovery():
    from modules.download_manager.ui.widget._dm_controls import _DMControlsMixin
    ui = SimpleNamespace(_update_status_label=Mock(), refresh_table_order=Mock())
    _DMControlsMixin._on_refresh(ui)
    ui.refresh_table_order.assert_called_once_with()


def test_worker_query_cannot_release_gui_interaction(clock):
    from concurrent.futures import ThreadPoolExecutor
    throttle.record_protected_drag(True, grace_ms=1500)
    clock[0] += 86400000
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(throttle.is_protected_drag_active).result(timeout=5)
    assert throttle._PROTECTED_DRAG_ACTIVE
    assert not throttle.is_protected_drag_active()


def test_fast_keepalive_survives_long_session(clock):
    throttle.record_protected_drag(True, grace_ms=1500)
    clock[0] += 86400000
    throttle.keepalive_protected_drag(1500)
    assert throttle.is_protected_drag_active()


def test_visible_queue_resumes_after_missing_end(clock, monkeypatch):
    from modules.download_manager.ui.widget._dm_details import _DMDetailsMixin
    throttle.record_advanced_protected_interaction(True, grace_ms=2500)
    clock[0] += 86400000
    ui = SimpleNamespace(_rebuild_defer_pending=True, _refresh_table_order=Mock())
    # Exercise the actual deferred queue callback with the real throttle query.
    _DMDetailsMixin._fire_deferred_rebuild_after_drag(ui)
    ui._refresh_table_order.assert_called_once_with()
    assert not ui._rebuild_defer_pending
