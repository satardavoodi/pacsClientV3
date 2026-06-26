"""Guard: fundamental fix — multi-study SECONDARY-study series grow LIVE (2026-06-26).

Root cause: the DM→widget bridge is bound to ONE primary study_uid; on_series_progress /
on_series_completed hard-return on `uid != study_uid`. A dropped secondary-study series therefore
got NO live grow events and relied solely on the 2s disk watchdog → "groups late / never groups /
must re-drag".

Fix: route grow events by the globally-unique `series_uid` (identity), not the primary study_uid.
A sibling-study event is admitted into the grow lane ONLY when a viewport in THIS patient's tab is
awaiting/progressively-displaying that series_uid (`display_key_for_active_series_uid`), re-keyed to
that viewport's display key — cross-patient safe (the map is this patient's server_series_info). The
primary path is byte-identical. Flag `AIPACS_GROW_SIBLING_STUDY` (default on).

Functional test: a real Qt fake-DM emits signals; we assert the re-keyed grow event reaches the
widget's `series_images_progress` / `series_downloaded` only for an actively-shown sibling series,
that a foreign sibling is dropped, that the primary path is unchanged, and that the kill switch
restores the legacy drop.
"""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PRIMARY = "1.2.studyA"
SECONDARY = "1.2.studyB"
UID_PRIM = "uid-primary-203"
UID_SEC = "uid-secondary-500"
SEC_DISPLAY_KEY = "1000500"   # offset/display key the secondary-study viewport awaits/shows


@pytest.fixture(scope="module")
def _qt_app():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _wait(app, pred, timeout_s=2.5):
    end = time.time() + timeout_s
    while time.time() < end:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.02)
    app.processEvents()
    return pred()


def _build(active_map):
    """active_map: series_uid -> display_key for viewports CURRENTLY awaiting/showing it."""
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QTabWidget
    from PacsClient.pacs.workstation_ui.home_ui import home_download_service as hds

    class FakeDM(QObject):
        studyProgressUpdated = Signal(str, int, int, float)
        seriesDownloadStarted = Signal(str, str, str)
        seriesProgressUpdated = Signal(str, str, int, int)
        seriesDownloadCompleted = Signal(str, str)

        def __init__(self):
            super().__init__()
            self._tasks = {}
            self._active_workers = []

    class FakeSeries:
        def __init__(self, series_uid, series_number, image_count):
            self.series_uid = series_uid
            self.series_number = series_number
            self.image_count = image_count

    class FakeTask:
        def __init__(self, series):
            self.series_list = series

    class FakeTM:
        def __init__(self):
            self.series_widgets = {"203": object(), "202": object(), SEC_DISPLAY_KEY: object()}
            self._series_uid_to_number = {UID_PRIM: "203", UID_SEC: SEC_DISPLAY_KEY}
            self.started, self.completed = [], []

        def start_series_download(self, sn, total_images=None):
            self.started.append(str(sn))

        def complete_series_download(self, sn, total_images=None):
            self.completed.append(str(sn))

    class FakeVC:
        def __init__(self, amap):
            self._amap = amap

        def display_key_for_active_series_uid(self, series_uid):
            return self._amap.get(str(series_uid))

    class FakeWidget(QObject):
        series_downloaded = Signal(str)
        series_images_progress = Signal(str, int, int)

        def __init__(self, tm, vc):
            super().__init__()
            self.thumbnail_manager = tm
            self.viewer_controller = vc
            self._studies_series = {PRIMARY: [], SECONDARY: []}
            self._is_multistudy_hint = True
            self._series_uid_to_number = dict(tm._series_uid_to_number)
            self._server_series_info = {}
            self.progress_calls, self.downloaded_calls = [], []
            self.series_images_progress.connect(
                lambda s, c, t: self.progress_calls.append((str(s), int(c), int(t))))
            self.series_downloaded.connect(lambda s: self.downloaded_calls.append(str(s)))

        def isVisible(self):
            return True

    dm = FakeDM()
    dm._tasks[PRIMARY] = FakeTask([FakeSeries(UID_PRIM, "203", 8)])
    dm._tasks[SECONDARY] = FakeTask([FakeSeries(UID_SEC, "500", 10)])
    tm = FakeTM()
    widget = FakeWidget(tm, FakeVC(active_map))
    svc = hds.HomeDownloadService(QTabWidget())
    svc.connect_dm_to_widget(dm, widget, PRIMARY)
    return hds, dm, widget


def test_sibling_progress_reaches_grow_lane(_qt_app):
    """A viewport here is actively showing the secondary series → its progress is admitted,
    re-keyed to the display key, and reaches series_images_progress (the grow lane)."""
    hds, dm, widget = _build({UID_SEC: SEC_DISPLAY_KEY})
    dm.seriesProgressUpdated.emit(SECONDARY, UID_SEC, 5, 10)
    assert _wait(_qt_app, lambda: (SEC_DISPLAY_KEY, 5, 10) in widget.progress_calls), \
        "sibling-study progress must reach the grow lane at the display key"


def test_sibling_progress_dropped_when_not_active(_qt_app):
    """No viewport here is showing/awaiting that series_uid → the event is dropped (cross-patient
    safe; we never grow a series this tab isn't displaying)."""
    hds, dm, widget = _build({})            # nothing active
    dm.seriesProgressUpdated.emit(SECONDARY, UID_SEC, 5, 10)
    _wait(_qt_app, lambda: False, timeout_s=0.4)
    assert widget.progress_calls == [], "an inactive/foreign sibling series must not grow here"


def test_primary_progress_unchanged(_qt_app):
    hds, dm, widget = _build({})
    dm.seriesProgressUpdated.emit(PRIMARY, UID_PRIM, 4, 8)
    assert _wait(_qt_app, lambda: ("203", 4, 8) in widget.progress_calls), \
        "primary-study progress must still flow unchanged"


def test_kill_switch_restores_primary_only(_qt_app, monkeypatch):
    from PacsClient.pacs.workstation_ui.home_ui import home_download_service as hds
    monkeypatch.setattr(hds, "_GROW_SIBLING_STUDY", False)
    _hds, dm, widget = _build({UID_SEC: SEC_DISPLAY_KEY})
    dm.seriesProgressUpdated.emit(SECONDARY, UID_SEC, 5, 10)
    _wait(_qt_app, lambda: False, timeout_s=0.4)
    assert widget.progress_calls == [], "flag off → sibling grow events stay filtered (legacy)"


def test_sibling_completion_finalizes(_qt_app):
    """Sibling completion for an actively-shown series finalizes the stack (series_downloaded)."""
    hds, dm, widget = _build({UID_SEC: SEC_DISPLAY_KEY})
    dm.seriesDownloadCompleted.emit(SECONDARY, UID_SEC)
    assert _wait(_qt_app, lambda: SEC_DISPLAY_KEY in widget.downloaded_calls), \
        "sibling completion must finalize the grow (series_downloaded at the display key)"


def test_sibling_completion_dropped_when_not_active(_qt_app):
    hds, dm, widget = _build({})
    dm.seriesDownloadCompleted.emit(SECONDARY, UID_SEC)
    _wait(_qt_app, lambda: False, timeout_s=0.4)
    assert widget.downloaded_calls == [], "an inactive sibling completion must not finalize here"
