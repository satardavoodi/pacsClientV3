"""Same-identity small refreshes replace cards in one paint-disabled turn."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from PacsClient.pacs.workstation_ui.home_ui import right_panel_widget as module


def rows(count=1, images=2):
    return [dict(study_uid="synthetic-study", series_uid=f"synthetic-series-{i}",
                 series_number=str(i + 1), file_path="synthetic.png", image_count=images)
            for i in range(count)]


@pytest.fixture
def lap(monkeypatch):
    app = QApplication.instance() or QApplication([])
    queued, builds = [], []

    class ControlledTimer(QTimer):
        @staticmethod
        def singleShot(delay, *args):
            queued.append(args[-1])

    monkeypatch.setattr(module, "QTimer", ControlledTimer)
    monkeypatch.setattr(module, "_inside_input_synchronous_dispatch", lambda: False)
    panel = module.RightPanelWidget()
    pixmap = QPixmap(8, 8)
    pixmap.fill()
    monkeypatch.setattr(panel, "_build_pixmap_from_thumb", lambda *args: pixmap)
    original_build = panel._create_action_thumbnail

    def build(*args):
        builds.append(panel.content_widget.updatesEnabled())
        return original_build(*args)

    monkeypatch.setattr(panel, "_create_action_thumbnail", build)

    def seed(count=1):
        panel.display_thumbnails(rows(count), progressive=False)
        queued.pop(0)()
        assert panel.content_grid.count() == count
        return panel.content_grid.itemAt(0).widget()

    yield SimpleNamespace(panel=panel, queued=queued, builds=builds, seed=seed, app=app)
    panel.clear_content()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_same_identity_refresh_keeps_old_card_until_deferred_build(lap):
    old = lap.seed()
    lap.panel.display_thumbnails(rows(images=3), progressive=False)
    assert lap.panel.content_grid.count() == 1
    assert not old.isHidden()
    assert old.count_label.text() == "2 images"
    lap.queued.pop(0)()
    new = lap.panel.content_grid.itemAt(0).widget()
    assert new is not old and old.isHidden()
    assert new.count_label.text() == "3 images"
    assert lap.builds == [False, False]
    assert lap.panel.content_widget.updatesEnabled()


def test_input_dispatch_retry_keeps_old_card_until_safe_turn(lap, monkeypatch):
    old = lap.seed()
    lap.panel.display_thumbnails(rows(images=3), progressive=False)
    monkeypatch.setattr(module, "_inside_input_synchronous_dispatch", lambda: True)
    lap.queued.pop(0)()
    assert lap.panel.content_grid.count() == 1 and not old.isHidden()
    assert len(lap.builds) == 1
    monkeypatch.setattr(module, "_inside_input_synchronous_dispatch", lambda: False)
    lap.queued.pop(0)()
    assert lap.panel.content_grid.itemAt(0).widget().count_label.text() == "3 images"


@pytest.mark.parametrize("change", [dict(study_uid="another-study"),
                                    dict(series_uid="another-series"), dict(series_uid="")])
def test_changed_or_unknown_identity_clears_immediately(lap, change):
    old = lap.seed()
    lap.panel.display_thumbnails([dict(rows(images=3)[0], **change)], progressive=False)
    assert lap.panel.content_grid.count() == 0 and old.isHidden()


def test_explicit_clear_cancels_pending_swap(lap):
    old = lap.seed()
    lap.panel.display_thumbnails(rows(images=3), progressive=False)
    lap.panel.clear_content()
    lap.queued.pop(0)()
    assert lap.panel.content_grid.count() == 0 and old.isHidden()
    assert len(lap.builds) == 1


def test_newest_small_refresh_wins_without_empty_gap(lap):
    old = lap.seed()
    lap.panel.display_thumbnails(rows(images=3), progressive=False)
    lap.panel.display_thumbnails(rows(images=4), progressive=False)
    lap.queued.pop(0)()  # Superseded build may not remove the retained card.
    assert lap.panel.content_grid.count() == 1 and not old.isHidden()
    assert len(lap.builds) == 1
    lap.queued.pop(0)()
    assert lap.panel.content_grid.itemAt(0).widget().count_label.text() == "4 images"
    assert len(lap.builds) == 2


def test_large_refresh_still_delegates_to_progressive(lap, monkeypatch):
    old = lap.seed(count=2)
    monkeypatch.setattr(module, "_THUMB_IMMEDIATE_MAX", 1)
    lap.panel.display_thumbnails(rows(count=2, images=3), progressive=False)
    assert old.isHidden() and lap.panel.content_grid.count() == 0
    lap.queued.pop(0)()
    assert lap.panel.thumbnail_timer.isActive()
    assert len(lap.builds) == 2  # No synchronous new cards.


def test_explicit_progressive_refresh_preserves_its_original_policy(lap):
    old = lap.seed()
    lap.panel.display_thumbnails(rows(images=3), progressive=True)
    assert old.isHidden() and lap.panel.content_grid.count() == 0
    lap.queued.pop(0)()
    assert lap.panel.thumbnail_timer.isActive()


def test_identical_payload_still_coalesces(lap):
    old = lap.seed()
    lap.panel.display_thumbnails(rows(), progressive=False)
    assert lap.queued == [] and lap.panel.content_grid.itemAt(0).widget() is old


def test_retained_old_card_cannot_open_during_pending_refresh(lap):
    old = lap.seed()
    received = []
    lap.panel.seriesActionRequested.connect(received.append)
    lap.panel.display_thumbnails(rows(images=3), progressive=False)
    old.image_button._home_activate_series()
    assert len(lap.queued) == 1 and received == []
    lap.queued.pop(0)()
    new = lap.panel.content_grid.itemAt(0).widget()
    new.image_button._home_activate_series()
    lap.queued.pop(0)()
    assert len(received) == 1 and received[0].series_uid == "synthetic-series-0"


def test_failed_refresh_preparation_drops_retained_cards_and_allows_retry(lap, monkeypatch):
    old = lap.seed()
    original = lap.panel._build_grouped_thumbnail_rows
    lap.panel.display_thumbnails(rows(images=3), progressive=False)

    def fail(*args):
        raise ValueError("Synthetic render preparation failure")

    monkeypatch.setattr(lap.panel, "_build_grouped_thumbnail_rows", fail)
    lap.queued.pop(0)()
    assert lap.panel.content_grid.count() == 0 and old.isHidden()
    assert lap.panel.content_widget.updatesEnabled()
    monkeypatch.setattr(lap.panel, "_build_grouped_thumbnail_rows", original)
    lap.panel.display_thumbnails(rows(images=3), progressive=False)
    assert len(lap.queued) == 1
    lap.queued.pop(0)()
    assert lap.panel.content_grid.itemAt(0).widget().count_label.text() == "3 images"


@pytest.mark.parametrize("initial_count,replacement", [
    (1, []), (1, rows(2)), (2, list(reversed(rows(2, images=3))))])
def test_empty_or_changed_membership_order_is_not_retained(lap, initial_count, replacement):
    old = lap.seed(count=initial_count)
    lap.panel.display_thumbnails(replacement, progressive=False)
    assert lap.panel.content_grid.count() == 0 and old.isHidden()


def test_grouped_duplicate_numbers_keep_distinct_actions_and_headers(lap):
    source = [dict(rows()[0], series_number="4", series_description="", study_label="Current"),
              dict(rows()[0], study_uid="synthetic-prior", series_uid="synthetic-prior-series",
                   series_number="4", series_description="", study_label="Previous")]
    lap.panel.display_thumbnails(source, progressive=False)
    lap.queued.pop(0)()
    count = lap.panel.content_grid.count()
    lap.panel.display_thumbnails([dict(row, image_count=5) for row in source], progressive=False)
    assert lap.panel.content_grid.count() == count
    lap.queued.pop(0)()
    assert lap.panel.content_grid.count() == count
    actions = []
    lap.panel.seriesActionRequested.connect(actions.append)
    for index in range(count):
        card = lap.panel.content_grid.itemAt(index).widget()
        if hasattr(card, "image_button"):
            assert card.count_label.text() == "5 images"
            card.image_button._home_activate_series()
            lap.queued.pop(0)()
    assert {(a.study_uid, a.series_uid) for a in actions} == {
        (row["study_uid"], row["series_uid"]) for row in source}
