"""Synthetic Qt guards for manager-owned deferred work and explicit retirement."""
import ast
import gc
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import weakref

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from shiboken6 import isValid

from PacsClient.pacs.patient_tab.utils import thumbnail_manager as module


class ThemeSource(QObject):
    themeChanged = Signal(dict)

    def current_theme(self):
        return {}


def click_retry(card):
    buttons = [b for b in card.findChildren(QPushButton)
               if b.toolTip() == "Retry download for this series"]
    assert len(buttons) == 1
    buttons[0].click()


@pytest.fixture
def scene(monkeypatch):
    app = QApplication.instance() or QApplication([])
    theme = ThemeSource()
    monkeypatch.setattr(module, "get_theme_manager", lambda: theme)
    managers, cards = [], []

    def make(callback=lambda key: None):
        manager = module.ThumbnailManager(callback)
        managers.append(manager)
        return manager

    def card(manager, key="1000001"):
        pixmap = QPixmap(8, 8)
        pixmap.fill()
        widget = manager.create_thumbnail_widget(
            pixmap, key, thumbnail_index=key,
            series_info={"series_uid": "synthetic-series", "study_uid": "synthetic-study",
                         "_orig_series_number": "1", "display_image_count": 420,
                         "image_count": 2},
        )
        cards.append(widget)
        return widget

    yield SimpleNamespace(app=app, theme=theme, make=make, card=card)
    for manager in managers:
        if isValid(manager):
            if hasattr(manager, "dispose"):
                manager.dispose()
            manager.deleteLater()
    for widget in cards:
        if isValid(widget):
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QTest.qWait(20)


def test_reset_drops_old_progress_and_allows_new_generation(scene, monkeypatch):
    manager = scene.make()
    delivered = []
    monkeypatch.setattr(manager, "update_series_progress", lambda *a, **kw: delivered.append(a))
    manager._progress_update_pending["1"] = ("1", 75, "old")
    manager._schedule_progress_flush(0)
    manager.reset_all_states()
    scene.app.processEvents()
    assert delivered == []
    assert not manager._progress_update_timer_active
    manager._progress_update_pending["1"] = ("1", 10, "new")
    manager._schedule_progress_flush(0)
    scene.app.processEvents()
    assert delivered == [("1", 10, "new")]


def test_reset_rejects_retained_old_card_with_same_key(scene):
    changed, priority = [], []
    manager = scene.make(changed.append)
    old = scene.card(manager)
    manager.priority_download_requested.connect(lambda *args: priority.append(args))
    manager.reset_all_states()
    current = scene.card(manager)
    old.image_button.click()
    click_retry(old)
    assert changed == [] and priority == []
    current.image_button.click()
    assert changed == [1000001]
    assert priority == [("1000001", "synthetic-study")]
    assert "420" in current.count_label.text()


def test_dispose_cancels_pending_work_and_clears_owner_state(scene, monkeypatch):
    manager = scene.make()
    scene.card(manager)
    delivered = []
    monkeypatch.setattr(manager, "update_series_progress", lambda *a, **kw: delivered.append(a))
    manager._progress_update_pending["1"] = ("1", 40, "old")
    manager._schedule_progress_flush(0)
    manager.dispose()
    manager.dispose()
    scene.app.processEvents()
    assert delivered == []
    assert manager.series_widgets == {}
    assert manager.buttons == []
    assert manager._progress_update_pending == {}
    assert manager._series_uid_to_number == {}
    assert manager.method_change_series is None
    assert not manager._progress_update_timer_active


def test_dispose_disconnects_only_own_theme_receiver(scene):
    retired, live = scene.make(), scene.make()
    retired.dispose()
    scene.theme.themeChanged.emit({"accent": "synthetic-new"})
    assert retired._theme != {"accent": "synthetic-new"}
    assert live._theme == {"accent": "synthetic-new"}


def test_dispose_rejects_retained_card_actions_and_late_updates(scene):
    changed, requested = [], []
    manager = scene.make(changed.append)
    widget = scene.card(manager)
    manager.priority_download_requested.connect(lambda *args: requested.append(args))
    manager.retry_download_requested.connect(lambda *args: requested.append(args))
    manager.dispose()
    widget.image_button.click()
    click_retry(widget)
    manager.update_series_progress("1", 25)
    manager.set_series_ready("1")
    manager.set_active_series("1")
    assert changed == [] and requested == []
    assert manager.series_widgets == {} and manager.ready_series == set()
    assert manager.selected_series is None
    assert manager._progress_update_pending == {}


def test_dispose_releases_bound_owner_even_with_retained_manager(scene):
    class Owner:
        def change(self, key):
            pass

    owner = Owner()
    ref = weakref.ref(owner)
    manager = scene.make(owner.change)
    manager.dispose()
    del owner
    gc.collect()  # Reachability measurement only; never part of production disposal.
    assert ref() is None


def test_patient_exit_retires_both_independent_managers_before_viewers(scene):
    path = Path(__file__).resolve().parents[3] / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_lifecycle.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "_PWLifecycleMixin")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "exit_patient_widget")
    namespace = {"_close_step": lambda *a: nullcontext()}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), "exec"), namespace)
    primary, advanced = scene.make(), scene.make()
    scene.card(primary)
    scene.card(advanced)
    owner = SimpleNamespace(thumbnail_manager=primary, _adv_thumbnail_manager=advanced)
    owner._exit_patient_widget_impl = lambda: (
        pytest.fail("Thumbnail owners still active during viewer teardown")
        if primary.series_widgets or advanced.series_widgets else None
    )
    namespace["exit_patient_widget"](owner)
    assert primary.method_change_series is None and advanced.method_change_series is None


@pytest.mark.parametrize("keep_widgets", [False, True])
def test_home_clear_disposes_all_render_managers_without_native_card_deletion(scene, keep_widgets):
    from PacsClient.pacs.workstation_ui.home_ui.right_panel_widget import RightPanelWidget

    panel = RightPanelWidget()
    try:
        manager = panel._new_action_thumbnail_manager()
        widget = scene.card(manager)
        panel.content_grid.addWidget(widget, 0, 0)
        panel.clear_content(keep_widgets=keep_widgets)
        assert manager.method_change_series is None
        assert manager.series_widgets == {}
        assert isValid(widget)  # The existing owner still owns deferred deletion/atomic swap.
        assert panel.content_grid.count() == int(keep_widgets)
    finally:
        panel.clear_content()
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_owned_delayed_callback_is_released_immediately_on_reset(scene):
    manager = scene.make()
    class Payload:
        pass
    payload = Payload()
    ref = weakref.ref(payload)
    manager._schedule_owned_callback(60000, lambda p=payload: None)
    del payload
    assert ref() is not None
    manager.reset_all_states()
    assert ref() is None
    assert not manager._deferred_callbacks


def test_native_manager_deletion_cancels_timer_delivery(scene):
    manager = scene.make()
    delivered = []
    manager._schedule_owned_callback(0, lambda: delivered.append(True))
    manager.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    scene.app.processEvents()
    assert delivered == []


def test_callback_can_reset_and_schedule_new_work(scene):
    manager = scene.make()
    delivered = []
    def first():
        delivered.append("first")
        manager.reset_all_states()
        manager._schedule_owned_callback(0, lambda: delivered.append("second"))
    manager._schedule_owned_callback(0, first)
    QTest.qWait(20)
    assert delivered == ["first", "second"]
    assert not manager._deferred_callbacks


def test_progress_burst_keeps_one_timer_and_delivers_latest_payload(scene, monkeypatch):
    manager = scene.make()
    delivered = []
    monkeypatch.setattr(manager, "update_series_progress", lambda *a, **kw: delivered.append(a))
    for value in range(1, 100):
        manager._progress_update_pending["1"] = ("1", value, "current")
        manager._schedule_progress_flush(0)
    assert len(manager._deferred_callbacks) == 1
    scene.app.processEvents()
    assert delivered == [("1", 99, "current")]
    assert not manager._deferred_callbacks


def test_reset_cancels_queued_border_refresh(scene, monkeypatch):
    manager = scene.make()
    manager.set_scroll_active(True)
    manager.apply_border_states_new()
    manager.set_scroll_active(False)
    delivered = []
    monkeypatch.setattr(manager, "apply_border_states_new", lambda **kw: delivered.append(True))
    manager.reset_all_states()
    scene.app.processEvents()
    assert delivered == []
    assert not manager._border_state_update_pending


def test_theme_publisher_deleted_before_dispose(scene):
    manager = scene.make()
    scene.theme.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    manager.dispose()
    manager.dispose()
    assert manager.method_change_series is None


def test_queued_image_cannot_repaint_retired_card(scene):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    manager = scene.make()
    card = scene.card(manager)
    before = card.image_button.icon().cacheKey()
    manager.thumbnail_image_ready.disconnect(manager._apply_thumbnail_image)
    manager.thumbnail_image_ready.connect(manager._apply_thumbnail_image, Qt.QueuedConnection)
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(Qt.red)
    manager.update_thumbnail_image("1000001", image)
    manager.dispose()
    scene.app.processEvents()
    assert card.image_button.icon().cacheKey() == before


def test_dispose_after_native_destruction_still_releases_python_owner(scene):
    manager = scene.make()
    manager._schedule_owned_callback(60000, lambda: None)
    manager.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(manager)
    manager.dispose()
    assert manager.method_change_series is None
    assert not manager._deferred_callbacks
