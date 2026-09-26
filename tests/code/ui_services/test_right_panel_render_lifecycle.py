"""Retired Home renders cannot repopulate a cleared or destroyed panel."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from PacsClient.pacs.workstation_ui.home_ui import right_panel_widget as module


def payload(suffix="a"):
    return [dict(study_uid=f"study-{suffix}", series_uid=f"series-{suffix}",
                 series_number="4", file_path="synthetic.png", image_count=2)]


@pytest.fixture
def render(monkeypatch):
    app = QApplication.instance() or QApplication([])
    queued = []

    class ControlledTimer(QTimer):
        @staticmethod
        def singleShot(delay, *args):
            queued.append((delay, args[-1]))

    monkeypatch.setattr(module, "QTimer", ControlledTimer)
    monkeypatch.setattr(module, "_inside_input_synchronous_dispatch", lambda: False)
    widget = module.RightPanelWidget()
    builds = []
    pixmap = QPixmap(8, 8)
    pixmap.fill()
    monkeypatch.setattr(widget, "_build_pixmap_from_thumb", lambda *a: pixmap)
    monkeypatch.setattr(widget, "_new_action_thumbnail_manager", lambda: object())

    def build(manager, pixmap, thumb, ordinal):
        builds.append(thumb["series_uid"])
        return QLabel("Synthetic card")

    monkeypatch.setattr(widget, "_create_action_thumbnail", build)
    yield SimpleNamespace(widget=widget, queued=queued, builds=builds, app=app)
    widget._cancel_thumbnail_timer()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.mark.parametrize("progressive", [False, True])
def test_clear_cancels_queued_render_start(render, progressive):
    w = render.widget
    w.display_thumbnails(payload(), progressive=progressive)
    callback = render.queued.pop()[1]
    w.clear_content()
    label_after_clear = w.count_label.text()
    callback()
    assert w.content_grid.count() == 0
    assert w.thumbnail_timer is None
    assert render.builds == []
    assert w.count_label.text() == label_after_clear


@pytest.mark.parametrize("progressive", [False, True])
@pytest.mark.parametrize("explicit_generation", [False, True])
def test_clear_cancels_input_deferred_render(render, monkeypatch, progressive, explicit_generation):
    w = render.widget
    method = w.display_thumbnails_progressively if progressive else w.display_thumbnails_immediately
    monkeypatch.setattr(module, "_inside_input_synchronous_dispatch", lambda: True)
    generation = w._display_generation if explicit_generation else None
    method(payload(), generation)
    assert len(render.queued) == 1
    callback = render.queued.pop()[1]
    w.clear_content()
    monkeypatch.setattr(module, "_inside_input_synchronous_dispatch", lambda: False)
    callback()
    assert w.content_grid.count() == 0
    assert w.thumbnail_timer is None
    assert render.builds == []


def test_late_progressive_tick_after_clear_cannot_recreate_a_card(render):
    w = render.widget
    w.display_thumbnails_progressively(payload())
    w.clear_content()
    w.display_next_thumbnail()
    assert w.content_grid.count() == 0
    assert render.builds == []
    assert w.thumbnail_timer is None


@pytest.mark.parametrize("progressive", [False, True])
def test_cleared_payload_can_be_requested_again_without_stale_work(render, progressive):
    w = render.widget
    w.display_thumbnails(payload(), progressive=progressive)
    stale = render.queued.pop()[1]
    w.clear_content()
    w.display_thumbnails(payload(), progressive=progressive)
    current = render.queued.pop()[1]
    stale()
    assert render.builds == [] and w.thumbnail_timer is None
    current()
    if progressive:
        w._cancel_thumbnail_timer()
        for _ in w.thumbnail_rows_to_display:
            w.display_next_thumbnail()
    assert render.builds == ["series-a"]
    assert w.content_grid.count() == 1


@pytest.mark.parametrize("progressive", [False, True])
def test_replacement_renders_only_latest_generation_and_coalesces(render, progressive):
    w = render.widget
    w.display_thumbnails(payload(), progressive=progressive)
    stale = render.queued.pop()[1]
    w.display_thumbnails(payload("b"), progressive=progressive)
    current = render.queued.pop()[1]
    generation = w._display_generation
    w.display_thumbnails(payload("b"), progressive=progressive)
    assert w._display_generation == generation and render.queued == []
    stale()
    current()
    if progressive:
        w._cancel_thumbnail_timer()
        for _ in w.thumbnail_rows_to_display:
            w.display_next_thumbnail()
    assert render.builds == ["series-b"]


@pytest.mark.parametrize("progressive", [False, True])
def test_destroyed_panel_does_not_receive_queued_render(monkeypatch, progressive):
    app = QApplication.instance() or QApplication([])
    w = module.RightPanelWidget()
    calls = []
    method_name = "display_thumbnails_progressively" if progressive else "display_thumbnails_immediately"
    monkeypatch.setattr(w, method_name, lambda *a: calls.append("retired"))
    w.display_thumbnails(payload(), progressive=progressive)
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QTest.qWait(90)
    assert calls == []
    assert app is not None


@pytest.mark.parametrize("progressive", [False, True])
def test_destroyed_panel_does_not_receive_input_retry(monkeypatch, progressive):
    app = QApplication.instance() or QApplication([])
    w = module.RightPanelWidget()
    monkeypatch.setattr(module, "_inside_input_synchronous_dispatch", lambda: True)
    method_name = "display_thumbnails_progressively" if progressive else "display_thumbnails_immediately"
    getattr(w, method_name)(payload())
    calls = []
    monkeypatch.setattr(w, method_name, lambda *a: calls.append("retired"))
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QTest.qWait(40)
    assert calls == []
    assert app is not None


def test_progressive_timer_lifetime_belongs_to_panel(monkeypatch):
    from shiboken6 import isValid

    app = QApplication.instance() or QApplication([])
    w = module.RightPanelWidget()
    monkeypatch.setattr(module, "_inside_input_synchronous_dispatch", lambda: False)
    monkeypatch.setattr(w, "_new_action_thumbnail_manager", lambda: object())
    w.display_thumbnails_progressively(payload())
    timer = w.thumbnail_timer
    assert timer.parent() is w
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(timer)
    assert app is not None


def test_home_dispatch_uses_canonical_per_study_series_order(render, monkeypatch):
    """Home and Patient Tab share history ordering without mixing study groups."""
    w = render.widget
    received = []
    monkeypatch.setattr(
        w, 'display_thumbnails_immediately',
        lambda thumbnails, generation=None: received.extend(thumbnails),
    )
    rows = [
        dict(study_uid='study-a', series_uid='a-1', series_number='1', file_path='a1.png'),
        dict(study_uid='study-a', series_uid='a-history', series_number='100000', file_path='ah.png'),
        dict(study_uid='study-b', series_uid='b-1', series_number='1000001',
             _orig_series_number='1', file_path='b1.png'),
        dict(study_uid='study-b', series_uid='b-history', series_number='1100000',
             _orig_series_number='100000', file_path='bh.png'),
    ]

    w.display_thumbnails(rows, progressive=False)
    assert len(render.queued) == 1
    render.queued.pop()[1]()

    assert [row['series_uid'] for row in received] == [
        'a-history', 'a-1', 'b-history', 'b-1']
