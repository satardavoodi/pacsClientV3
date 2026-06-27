"""Guard: real-time THUMBNAIL download status for MULTI-STUDY secondary studies
(2026-06-25, patient 47084).

Root cause: ``HomeDownloadService.connect_dm_to_widget`` binds the DM→widget bridge
to ONE (primary) ``study_uid``; ``on_series_started`` / ``on_series_completed``
hard-return on ``uid != study_uid``. For a multi-study patient the SECONDARY
study's series-download events were dropped, so those thumbnails never turned
downloading/ready in real time (only after a tab-switch rebuild).

Fix (flag ``AIPACS_THUMB_SIBLING_STUDY_STATUS``, default on): admit a sibling-study
event into the THUMBNAIL lane ONLY when its globally-unique ``series_uid`` resolves
to a thumbnail already shown for THIS patient (``_series_uid_to_number`` — built
solely from this patient's server_series_info, so cross-patient safe). It resolves
to the OFFSET/display key via ``_resolve_sn`` and calls
start/complete_series_download — and NOTHING else (no ``series_downloaded`` emit, no
viewport progress, no load trigger).

Functional test: a real Qt fake-DM emits the signals; we assert the sibling routes
to the thumbnail lane at the offset key, the primary path is unchanged, an unknown
(cross-patient) UID is rejected, and the kill switch restores the legacy filter.
"""
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found")


def _src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
        / "home_download_service.py"
    ).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Source-pin: flag default-on + the sibling path touches ONLY the thumbnail lane
# --------------------------------------------------------------------------- #

def test_thumbnail_sibling_now_unconditional():
    """S3b cutover 2026-06-27: the AIPACS_THUMB_SIBLING_STUDY_STATUS flag + its `=0` legacy branch
    were removed — a sibling-study event admits to the THUMBNAIL lane unconditionally when its
    series_uid belongs to THIS patient's open thumbnails (cross-patient safe). One rule, no flag."""
    src = _src()
    # the flag's env-read + its `=0` branch are gone (the doc comment may still NAME the retired
    # flag for grep-ability); the unconditional thumbnail-lane admission gate remains.
    assert 'getenv("AIPACS_THUMB_SIBLING_STUDY_STATUS"' not in src
    assert "_belongs_to_open_thumbnails(series_uid)" in src   # the unconditional admission gate


def test_sibling_projection_thumbnail_only():
    """The sibling projection must call ONLY start/complete_series_download — it must
    NOT emit series_downloaded or series_images_progress (those would trigger a viewer
    load / progress lane for a series the user did not open)."""
    src = _src()
    fn = src[src.index("def _project_sibling_thumbnail"):]
    fn = fn[: fn.index("def _flush(")]
    # Strip the docstring so prose ("never series_downloaded …") isn't matched as code.
    body = fn[fn.index('"""', fn.index('"""') + 3) + 3:]
    assert "complete_series_download" in body
    assert "start_series_download" in body
    # The projection must perform NO signal emits at all (no series_downloaded, no
    # series_images_progress) — it is the thumbnail-border lane only.
    assert ".emit(" not in body, "sibling thumbnail path must not emit any signal"


# --------------------------------------------------------------------------- #
# Functional: drive the real bridge with a fake Qt DM
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def _qt_app():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _build_harness():
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QTabWidget
    from PacsClient.pacs.workstation_ui.home_ui import home_download_service as hds

    PRIMARY = "1.2.studyA"
    SECONDARY = "1.2.studyB"
    UID_PRIM = "uid-primary-203"
    UID_SEC = "uid-secondary-203"

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
            # series_widgets keyed by the multi-study OFFSET/display keys.
            self.series_widgets = {"203": object(), "202": object(), "1000203": object()}
            self._series_uid_to_number = {UID_PRIM: "203", UID_SEC: "1000203"}
            self.started = []
            self.completed = []

        def start_series_download(self, sn, total_images=None):
            self.started.append(str(sn))

        def complete_series_download(self, sn, total_images=None):
            self.completed.append(str(sn))

    class FakeWidget(QObject):
        series_downloaded = Signal(str)
        series_images_progress = Signal(str, int, int)

        def __init__(self, tm):
            super().__init__()
            self.thumbnail_manager = tm
            self._studies_series = {PRIMARY: [], SECONDARY: []}   # multi-study
            self._is_multistudy_hint = True
            self._series_uid_to_number = dict(tm._series_uid_to_number)
            self._server_series_info = {}
            self.series_downloaded_calls = []
            self.series_downloaded.connect(self.series_downloaded_calls.append)

        def isVisible(self):
            return True

    dm = FakeDM()
    dm._tasks[PRIMARY] = FakeTask([FakeSeries(UID_PRIM, "203", 8)])
    dm._tasks[SECONDARY] = FakeTask([FakeSeries(UID_SEC, "203", 10)])
    tm = FakeTM()
    widget = FakeWidget(tm)

    svc = hds.HomeDownloadService(QTabWidget())
    svc.connect_dm_to_widget(dm, widget, PRIMARY)
    return hds, dm, tm, widget, dict(PRIMARY=PRIMARY, SECONDARY=SECONDARY,
                                     UID_PRIM=UID_PRIM, UID_SEC=UID_SEC)


def test_sibling_completion_routes_to_offset_key(_qt_app):
    hds, dm, tm, widget, ids = _build_harness()
    # Secondary-study completion (uid != primary study_uid) → offset-key thumbnail.
    dm.seriesDownloadCompleted.emit(ids["SECONDARY"], ids["UID_SEC"])
    assert "1000203" in tm.completed, "sibling completion must hit the offset/display key"
    # Must NOT trigger the viewer-load lane.
    assert widget.series_downloaded_calls == [], "sibling path must not emit series_downloaded"


def test_sibling_start_routes_to_offset_key(_qt_app):
    hds, dm, tm, widget, ids = _build_harness()
    dm.seriesDownloadStarted.emit(ids["SECONDARY"], ids["UID_SEC"], "MR series")
    assert "1000203" in tm.started, "sibling start must mark the offset-key thumbnail downloading"


def test_unknown_uid_cross_patient_rejected(_qt_app):
    hds, dm, tm, widget, ids = _build_harness()
    # A foreign series_uid not in this patient's uid→number map must be ignored.
    dm.seriesDownloadCompleted.emit("1.2.foreign", "uid-foreign-999")
    assert tm.completed == [], "an unknown/foreign UID must never update a thumbnail"


def test_primary_path_still_completes(_qt_app):
    hds, dm, tm, widget, ids = _build_harness()
    # uid == primary study_uid → normal path → primary thumbnail completes.
    dm.seriesDownloadCompleted.emit(ids["PRIMARY"], ids["UID_PRIM"])
    assert "203" in tm.completed, "primary-study completion must still update its thumbnail"


# Kill-switch test removed: the AIPACS_THUMB_SIBLING_STUDY_STATUS flag + its legacy `=0` branch
# were deleted in the S3b cutover (2026-06-27); the sibling thumbnail admission is now the ONE
# unconditional `_belongs_to_open_thumbnails` rule (the functional tests above cover it).
