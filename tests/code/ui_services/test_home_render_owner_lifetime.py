"""Home render retirement releases old owners without changing card identity."""
import gc
import weakref

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from PacsClient.pacs.workstation_ui.home_ui import right_panel_widget as module
from PacsClient.utils.series_identity import SeriesActionIdentity


def payload(suffix="a"):
    return [dict(study_uid=f"synthetic-study-{suffix}", series_uid=f"synthetic-series-{suffix}",
                 series_number="04", folder_key="04_cine", file_path="synthetic.png",
                 image_count=2, display_image_count=420)]


def drain_deletes():
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    # Test-only reachability probe, never a production cleanup strategy.
    gc.collect()


@pytest.fixture
def panels(monkeypatch):
    app = QApplication.instance() or QApplication([])
    refs = []
    pixmap = QPixmap(8, 8)
    pixmap.fill()
    monkeypatch.setattr(module, "_inside_input_synchronous_dispatch", lambda: False)
    monkeypatch.setattr(module.RightPanelWidget, "_build_pixmap_from_thumb", lambda *args: pixmap)

    def create():
        panel = module.RightPanelWidget()
        refs.append(weakref.ref(panel))
        return panel

    yield create
    for ref in refs:
        panel = ref()
        if panel is not None and isValid(panel):
            panel.clear_content()
            panel.deleteLater()
    drain_deletes()
    assert app is not None


def progressive_card(panel):
    panel.display_thumbnails_progressively(payload())
    panel._cancel_thumbnail_timer()
    panel.display_next_thumbnail()
    assert panel.content_grid.count() == 1
    return weakref.ref(panel._progressive_manager), weakref.ref(panel.content_grid.itemAt(0).widget())


def test_clear_releases_progressive_manager_and_deleted_card_wrappers(panels):
    panel = panels()
    manager_ref, card_ref = progressive_card(panel)
    panel.clear_content()
    drain_deletes()
    assert panel.content_grid.count() == 0
    assert manager_ref() is None
    assert card_ref() is None


def test_progressive_to_immediate_does_not_retain_previous_manager(panels):
    panel = panels()
    manager_ref, card_ref = progressive_card(panel)
    panel.clear_content()
    panel.display_thumbnails_immediately(payload("b"))
    drain_deletes()
    assert panel.content_grid.count() == 1
    assert manager_ref() is None
    assert card_ref() is None


def test_retained_action_callback_does_not_own_destroyed_panel(panels):
    panel = panels()
    manager = panel._new_action_thumbnail_manager()
    manager._home_series_actions["0"] = SeriesActionIdentity.from_metadata(payload()[0])
    callback = manager._home_activate_series
    panel_ref = weakref.ref(panel)
    panel.deleteLater()
    drain_deletes()
    del panel
    drain_deletes()
    assert panel_ref() is None
    callback("0")  # A retained callback is harmless after its owner is gone.


def test_retained_action_rejects_native_deleted_owner_before_queueing(panels):
    panel = panels()
    manager = panel._new_action_thumbnail_manager()
    manager._home_series_actions["0"] = SeriesActionIdentity.from_metadata(payload()[0])
    panel.deleteLater()
    drain_deletes()
    assert not isValid(panel)
    manager._home_activate_series("0")


def test_current_action_keeps_exact_identity_and_is_deferred(panels):
    panel = panels()
    manager = panel._new_action_thumbnail_manager()
    action = SeriesActionIdentity.from_metadata(payload()[0])
    manager._home_series_actions["0"] = action
    received = []
    panel.seriesActionRequested.connect(received.append)
    manager._home_activate_series("0")
    assert received == []
    QApplication.processEvents()
    assert received == [action]
    assert received[0].series_number == "04" and received[0].folder_key == "04_cine"


def test_clear_rejects_already_queued_action_and_retained_old_callback(panels):
    panel = panels()
    manager = panel._new_action_thumbnail_manager()
    manager._home_series_actions["0"] = SeriesActionIdentity.from_metadata(payload()[0])
    received = []
    panel.seriesActionRequested.connect(received.append)
    manager._home_activate_series("0")
    panel.clear_content()
    manager._home_activate_series("0")
    QApplication.processEvents()
    assert received == []


def test_clear_one_panel_preserves_other_panel_action(panels):
    first, second = panels(), panels()
    manager = second._new_action_thumbnail_manager()
    action = SeriesActionIdentity.from_metadata(payload("b")[0])
    manager._home_series_actions["0"] = action
    received = []
    second.seriesActionRequested.connect(received.append)
    first.clear_content()
    manager._home_activate_series("0")
    QApplication.processEvents()
    assert received == [action]


def test_finished_progressive_render_keeps_current_cards_and_actions(panels):
    panel = panels()
    manager_ref, card_ref = progressive_card(panel)
    panel.display_next_thumbnail()  # Normal end of the timer, not retirement.
    drain_deletes()
    assert manager_ref() is not None and isValid(card_ref())
    assert panel.count_label.text() == "1 series"
    assert card_ref().count_label.text() == "420 images"
    received = []
    panel.seriesActionRequested.connect(received.append)
    manager_ref()._home_activate_series("0")
    QApplication.processEvents()
    assert received == [SeriesActionIdentity.from_metadata(payload()[0])]


def test_repeated_render_retirement_does_not_accumulate_old_owners(panels):
    panel = panels()
    retired = []
    for _ in range(4):
        retired.extend(progressive_card(panel))
        panel.clear_content()
        panel.clear_content()  # Repeated cleanup is harmless.
        drain_deletes()
    assert all(ref() is None for ref in retired)
    assert panel.content_grid.count() == 0


def test_owner_deleted_after_action_queue_does_not_emit(panels):
    panel = panels()
    manager = panel._new_action_thumbnail_manager()
    manager._home_series_actions["0"] = SeriesActionIdentity.from_metadata(payload()[0])
    received = []
    panel.seriesActionRequested.connect(received.append)
    manager._home_activate_series("0")
    panel.deleteLater()
    drain_deletes()
    QApplication.processEvents()
    assert received == []
