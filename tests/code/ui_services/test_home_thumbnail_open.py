"""Home double-click opens through the existing asynchronous patient workflow."""
import ast
import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from PacsClient.pacs.workstation_ui.home_ui.home_tab_service import HomeTabService
from PacsClient.utils.series_identity import SeriesActionIdentity

ROOT = Path(__file__).resolve().parents[3]
ROW = dict(study_uid="synthetic-study", series_uid="synthetic-cine",
           series_number="4", folder_key="4_cine", image_count=2, display_image_count=420)


@pytest.fixture
def cached_payload(monkeypatch):
    path = ROOT / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_search.py"
    method = next(n for n in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig")))
                  if isinstance(n, ast.FunctionDef) and n.name == "_build_cached_thumbnail_payload")
    rows, files = [], []
    db = ModuleType("database.manager")
    db.get_series_by_study_uid = lambda uid: rows
    monkeypatch.setitem(sys.modules, db.__name__, db)
    ns = {"get_all_series_thumbnail_from_study_folder": lambda uid: files,
          "get_name_file_from_path": lambda path: Path(path).stem}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), ns)
    owner = SimpleNamespace(get_series_info_from_database=lambda *a: {})
    return rows, files, lambda: ns[method.name](owner, "synthetic-study")


def test_cached_producer_keeps_identity_and_cine_counts(cached_payload):
    rows, files, run = cached_payload
    rows.append(dict(ROW, series_number="04", folder_key="04"))
    files.append("04.png")
    card = run()["thumbnails"][0]
    assert card.get("study_uid") == ROW["study_uid"]
    assert card.get("series_uid") == ROW["series_uid"]
    assert (card["image_count"], card.get("display_image_count")) == (2, 420)


def test_duplicate_number_cache_is_not_assigned_to_an_arbitrary_uid(cached_payload):
    rows, files, run = cached_payload
    rows.extend([dict(ROW), dict(ROW, series_uid="synthetic-still", folder_key="4_still")])
    files.append("4.png")
    assert SeriesActionIdentity.from_metadata(run()["thumbnails"][0]) is None


def test_collision_suffixed_cache_resolves_only_its_exact_series(cached_payload):
    rows, files, run = cached_payload
    rows.extend([dict(ROW), dict(ROW, series_uid="synthetic-still", folder_key="4_still")])
    files.append("4_cine.png")
    action = SeriesActionIdentity.from_metadata(run()["thumbnails"][0])
    assert action.series_uid == ROW["series_uid"] and action.series_number == "4"


def test_downloaded_preview_uses_shared_payload_off_gui_thread(monkeypatch, tmp_path):
    import threading
    import time
    path = ROOT / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py"
    method = next(n for n in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig")))
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "_load_thumbnails_for_downloaded_study")
    utils = ModuleType("PacsClient.pacs.patient_tab.utils.utils")
    utils.THUMBNAIL_PATH = tmp_path
    monkeypatch.setitem(sys.modules, utils.__name__, utils)
    folder = tmp_path / "synthetic-study"
    folder.mkdir()
    (folder / "4.png").touch()
    ns = {"asyncio": asyncio, "time": time, "print": lambda *a: None}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), ns)
    workers, rendered = [], []

    def payload(*args):
        workers.append(threading.get_ident())
        return {"thumbnails": [dict(ROW)]}

    owner = SimpleNamespace(_build_cached_thumbnail_payload=payload,
        _is_active_patient_selection=lambda *a: True,
        right_panel_widget=SimpleNamespace(display_thumbnails=lambda rows, **kw: rendered.extend(rows)))
    assert asyncio.run(ns[method.name](owner, "synthetic-study", [ROW]))
    assert workers and workers[0] != threading.get_ident()
    assert rendered[0]["display_image_count"] == 420


class Patient(QWidget):
    series_metadata_ready = Signal()
    loading_complete = Signal()

    def __init__(self):
        super().__init__()
        self.study_uid = "synthetic-study"
        self._server_series_info = {}
        self.selected = []

    def change_series_on_viewer(self, key):
        self.selected.append(key)


@pytest.fixture
def tab_service():
    app = QApplication.instance() or QApplication([])
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "Home")
    patient = Patient()
    service = HomeTabService(tabs)
    yield app, tabs, patient, service
    tabs.close()
    tabs.deleteLater()
    patient.deleteLater()


def test_new_tab_waits_for_metadata_then_uses_destination_key_once(tab_service):
    app, tabs, patient, service = tab_service
    calls = []

    async def open_patient():
        calls.append("normal-open")
        tabs.addTab(patient, "Synthetic")
        tabs.setCurrentWidget(patient)
        return patient

    assert asyncio.run(service.open_series_action(
        SeriesActionIdentity.from_metadata(ROW), open_patient, open_key="synthetic-study"))
    assert calls == ["normal-open"] and patient.selected == []
    patient._server_series_info = {"2000004": dict(ROW, series_number="2000004")}
    patient.series_metadata_ready.emit()
    app.processEvents()
    assert patient.selected == ["2000004"]
    patient.series_metadata_ready.emit()
    app.processEvents()
    assert patient.selected == ["2000004"]


def test_pending_open_cannot_steal_focus_after_user_leaves(tab_service):
    app, tabs, patient, service = tab_service

    async def open_patient():
        tabs.addTab(patient, "Synthetic")
        tabs.setCurrentWidget(patient)
        return patient

    asyncio.run(service.open_series_action(
        SeriesActionIdentity.from_metadata(ROW), open_patient, open_key="synthetic-study"))
    tabs.setCurrentIndex(0)
    patient._server_series_info = {"4": ROW}
    patient.series_metadata_ready.emit()
    app.processEvents()
    assert patient.selected == [] and tabs.currentIndex() == 0


def test_existing_tab_does_not_call_opener(tab_service):
    app, tabs, patient, service = tab_service
    tabs.addTab(patient, "Synthetic")
    patient._server_series_info = {"900001": ROW}

    async def forbidden():
        pytest.fail("An existing matching tab must be reused")

    assert asyncio.run(service.open_series_action(
        SeriesActionIdentity.from_metadata(ROW), forbidden, open_key="synthetic-study"))
    assert patient.selected == ["900001"] and tabs.count() == 2


def test_repeated_open_shares_one_task_and_last_intent_wins(tab_service):
    app, tabs, patient, service = tab_service
    calls = []

    async def scenario():
        gate = asyncio.Event()

        async def open_patient():
            calls.append(True)
            await gate.wait()
            tabs.addTab(patient, "Synthetic")
            tabs.setCurrentWidget(patient)
            return patient

        first = asyncio.create_task(service.open_series_action(
            SeriesActionIdentity.from_metadata(ROW), open_patient, open_key="synthetic-study"))
        await asyncio.sleep(0)
        second = asyncio.create_task(service.open_series_action(
            SeriesActionIdentity.from_metadata(dict(ROW, series_uid="new-intent")),
            open_patient, open_key="synthetic-study"))
        await asyncio.sleep(0)
        gate.set()
        assert await asyncio.gather(first, second) == [False, True]

    asyncio.run(scenario())
    assert len(calls) == 1 and tabs.count() == 2
    patient._server_series_info = {"4": ROW, "900001": dict(ROW, series_uid="new-intent")}
    patient.series_metadata_ready.emit()
    app.processEvents()
    assert patient.selected == ["900001"]
    assert service._series_open_tasks == service._series_open_intents == {}


def test_placement_during_open_supersedes_thumbnail_intent(tab_service):
    app, tabs, patient, service = tab_service

    async def open_patient():
        tabs.addTab(patient, "Synthetic")
        tabs.setCurrentWidget(patient)
        patient._home_series_selection_serial = 1
        return patient

    assert not asyncio.run(service.open_series_action(
        SeriesActionIdentity.from_metadata(ROW), open_patient, open_key="synthetic-study"))
    assert not getattr(patient, '_home_series_action_pending', None)


def test_metadata_alone_does_not_run_before_layout_ready(tab_service):
    app, tabs, patient, service = tab_service
    patient.viewer_controller = SimpleNamespace(lst_nodes_viewer=[])

    async def open_patient():
        tabs.addTab(patient, "Synthetic")
        tabs.setCurrentWidget(patient)
        patient._server_series_info = {"4": ROW}
        return patient

    asyncio.run(service.open_series_action(
        SeriesActionIdentity.from_metadata(ROW), open_patient, open_key="synthetic-study"))
    assert patient.selected == []
    patient.viewer_controller.lst_nodes_viewer = [object()]
    patient.loading_complete.emit()
    app.processEvents()
    assert patient.selected == ["4"]


@pytest.mark.parametrize("entries", [{"4": dict(ROW, study_uid="foreign")},
                                    {"4": ROW, "5": ROW}, {}])
def test_pending_missing_or_ambiguous_identity_expires_without_fallback(tab_service, entries):
    app, tabs, patient, service = tab_service

    async def open_patient():
        tabs.addTab(patient, "Synthetic")
        tabs.setCurrentWidget(patient)
        patient._server_series_info = entries
        return patient

    asyncio.run(service.open_series_action(
        SeriesActionIdentity.from_metadata(ROW), open_patient, open_key="synthetic-study"))
    pending = patient._home_series_action_pending
    pending.expire()
    patient.series_metadata_ready.emit()
    app.processEvents()
    assert patient.selected == [] and patient._home_series_action_pending is None


def test_worker_metadata_signal_is_consumed_on_gui_thread(tab_service):
    import threading
    app, tabs, patient, service = tab_service
    threads = []
    patient.change_series_on_viewer = lambda key: threads.append(threading.get_ident())

    async def open_patient():
        tabs.addTab(patient, "Synthetic")
        tabs.setCurrentWidget(patient)
        return patient

    asyncio.run(service.open_series_action(
        SeriesActionIdentity.from_metadata(ROW), open_patient, open_key="synthetic-study"))
    patient._server_series_info = {"4": ROW}
    thread = threading.Thread(target=patient.series_metadata_ready.emit)
    thread.start()
    thread.join()
    assert threads == []
    app.processEvents()
    assert threads == [threading.get_ident()]


def test_cached_payload_to_real_double_click_to_new_tab(cached_payload, tab_service):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtTest import QTest
    from PacsClient.pacs.workstation_ui.home_ui.right_panel_widget import RightPanelWidget

    rows, files, run = cached_payload
    rows.append(dict(ROW))
    files.append("4_cine.png")
    app, tabs, patient, service = tab_service
    panel = RightPanelWidget()
    pixmap = QPixmap(16, 16)
    pixmap.fill()
    card = panel._create_action_thumbnail(panel._new_action_thumbnail_manager(), pixmap,
                                          run()["thumbnails"][0], 0)
    actions = []
    panel.seriesActionRequested.connect(actions.append)
    card.image_button.click()
    app.processEvents()
    assert actions == []
    QTest.mouseDClick(card.image_button, Qt.LeftButton)
    app.processEvents()
    assert len(actions) == 1

    async def open_patient():
        tabs.addTab(patient, "Synthetic")
        tabs.setCurrentWidget(patient)
        patient._server_series_info = {"2000004": ROW}
        return patient

    assert asyncio.run(service.open_series_action(actions[0], open_patient, open_key="synthetic-study"))
    assert patient.selected == ["2000004"]
    card.deleteLater()
    panel.deleteLater()
