"""Real-Qt synthetic guards for card-local effects across retry and retirement."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QObject, Signal, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from PacsClient.pacs.patient_tab.utils import thumbnail_manager as module


class ThemeSource(QObject):
    themeChanged = Signal(dict)

    def current_theme(self):
        return {}


@pytest.fixture
def scene(monkeypatch):
    app = QApplication.instance() or QApplication([])
    theme = ThemeSource()
    monkeypatch.setattr(module, "get_theme_manager", lambda: theme)
    owners, managers = [], []

    def border():
        owner = QWidget()
        owners.append(owner)
        return module.CircularProgressborder(owner)

    def managed():
        manager = module.ThumbnailManager(lambda key: None)
        managers.append(manager)
        pixmap = QPixmap(8, 8)
        pixmap.fill()
        card = manager.create_thumbnail_widget(pixmap, "1", thumbnail_index="1")
        owners.append(card)
        return manager, card.progress_border

    yield SimpleNamespace(app=app, border=border, managed=managed)
    # Native parent deletion cancels owned timers; no per-test wall-clock drain needed.
    for manager in managers:
        if isValid(manager):
            manager.dispose()
            manager.deleteLater()
    for owner in owners:
        if isValid(owner):
            owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_cleanup_stops_animation_without_detaching_label(scene):
    border = scene.border()
    border.setDownloading(True)
    border.setProgressAnimated(75)
    assert border._animation.state() == QAbstractAnimation.Running
    border.cleanup()
    assert border._animation.state() == QAbstractAnimation.Stopped
    assert border._progress_label.parent() is border
    border.cleanup()


def test_new_progress_cancels_old_delayed_ready(scene):
    border = scene.border()
    border.setDownloading(True)
    border.setProgressAnimated(100)
    border.setProgressAnimated(20)
    QTest.qWait(550)
    assert not border._is_ready
    assert border._downloading
    assert border._progress == pytest.approx(20)


def test_old_ready_hide_does_not_hide_new_download(scene):
    border = scene.border()
    border.setReady(True)
    border.setDownloading(True)
    border.set_progress(25)
    QTest.qWait(2650)
    assert not border._progress_label.isHidden()
    assert border._progress_label.text() == "25%"


def test_cleanup_cancels_ready_and_rejects_late_progress(scene):
    border = scene.border()
    border.setProgressAnimated(100)
    border.cleanup()
    progress = border._progress
    border.setProgressAnimated(40)
    QTest.qWait(550)
    assert not border._is_ready
    assert border._progress == progress


@pytest.mark.parametrize("operation", ["dispose", "reset_all_states"])
def test_owner_retirement_stops_only_its_card_effects(scene, operation):
    retired, old = scene.managed()
    live, current = scene.managed()
    old.setProgressAnimated(100)
    current.setProgressAnimated(100)
    getattr(retired, operation)()
    QTest.qWait(550)
    assert not old._is_ready
    assert current._is_ready
    assert old._animation.state() == QAbstractAnimation.Stopped


def test_progress_animation_has_native_card_owner(scene):
    border = scene.border()
    assert border._animation.parent() is border


def test_normal_completion_and_label_timing_remain(scene):
    border = scene.border()
    border.setDownloading(True)
    border.setProgressAnimated(100)
    QTest.qWait(550)
    assert border._is_ready and not border._downloading
    assert border._progress == 100
    assert "Ready" in border._progress_label.text()
    assert not border._progress_label.isHidden()
    QTest.qWait(2650)
    assert border._progress_label.isHidden()


def test_native_parent_deletion_cancels_card_callback(scene):
    delivered = []

    class RecordingBorder(module.CircularProgressborder):
        def _finish_progress_animation(self):
            delivered.append(True)

    owner = QWidget()
    border = RecordingBorder(owner)
    animation = border._animation
    border.setProgressAnimated(100)
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QTest.qWait(550)
    assert not isValid(border) and not isValid(animation)
    assert delivered == []
    border.cleanup()
    border.cleanup()
    border.setReady(True)
    border.setDownloading(True)
    border.setProgressAnimated(50)


def test_cleanup_preserves_atomic_swap_snapshot_and_stops_hide(scene):
    border = scene.border()
    border.setReady(True)
    label = border._progress_label
    snapshot = (label.text(), label.isHidden(), border._progress, border._is_ready)
    border.cleanup()
    border.setReady(False)
    border.setDownloading(True)
    border.set_progress(30)
    border.force_green_border()
    QTest.qWait(2650)
    assert (label.text(), label.isHidden(), border._progress, border._is_ready) == snapshot
    assert label.parent() is border


def test_card_timers_are_bounded_and_native_owned(scene):
    border = scene.border()
    for _ in range(25):
        border.setReady(True)
        border.setDownloading(True)
        border.setProgressAnimated(100)
    timers = border.findChildren(QTimer)
    assert len(timers) == 2
    assert {timer.interval() for timer in timers} == {450, 2500}
    assert all(timer.parent() is border and timer.isSingleShot() for timer in timers)
    border.cleanup()
    assert all(not timer.isActive() for timer in timers)


def test_retirement_stops_running_priority_flash_without_return(scene):
    manager, border = scene.managed()
    manager.highlight_priority_series("1")
    scene.app.processEvents()
    animation = border._priority_flash_anim
    assert animation.state() == QAbstractAnimation.Running
    manager.dispose()
    QTest.qWait(600)
    assert animation.state() == QAbstractAnimation.Stopped
    assert not hasattr(border, "_priority_flash_anim2")


@pytest.mark.parametrize("transition", ["pending", "retry"])
def test_leaving_ready_does_not_leave_a_stuck_ready_label(scene, transition):
    border = scene.border()
    border.setReady(True)
    if transition == "pending":
        border.setReady(False)
    else:
        border.setDownloading(True)
    assert border._progress_label.isHidden()
