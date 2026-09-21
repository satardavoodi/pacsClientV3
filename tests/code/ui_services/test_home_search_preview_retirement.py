"""Search replacement retires orphaned Home previews, not surviving selections."""
import ast
import asyncio
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QTableWidget, QTableWidgetItem

from PacsClient.pacs.workstation_ui.home_ui.home_search_service import HomeSearchService
from PacsClient.pacs.workstation_ui.home_ui.right_panel_widget import RightPanelWidget


@pytest.fixture
def scene(monkeypatch):
    app = QApplication.instance() or QApplication([])
    table = QTableWidget(1, 1)
    table.setItem(0, 0, QTableWidgetItem("Synthetic selection"))
    table.setCurrentCell(0, 0)
    panel = RightPanelWidget()
    panel.content_grid.addWidget(QLabel("Old preview"), 0, 0)
    panel.count_label.setText("13 series")
    panel._active_action_token = object()
    row = dict(patient_id="synthetic-p", study_uid="synthetic-s")
    pt = SimpleNamespace(results_table=table, click_timer=QTimer(),
                         _pending_selection_row=0, keep=False, clear_calls=0)

    def clear():
        pt.clear_calls += 1
        if not pt.keep:
            table.setRowCount(0)

    pt.clear_table = clear
    pt.get_patient_data_by_row = lambda index: row if index == 0 and table.rowCount() else {}
    pt.begin_bulk_insert = Mock()
    pt.end_bulk_insert = Mock()
    home = SimpleNamespace(
        patient_table_widget=pt, right_panel_widget=panel,
        _active_thumb_patient_id="synthetic-p", _active_thumb_study_uid="synthetic-s",
        _active_thumb_request_id=4, _search_generation=10, _cancel_search_requested=False,
        _thumbnail_request_timer=QTimer(), _pending_thumbnail_row=0,
        _current_thumbnail_task=Mock(), _right_panel_fetch_inflight_uid="synthetic-s",
        _right_panel_render_study_uid="synthetic-s", _series_info_loading_active=True,
        data_access_panel_widget=SimpleNamespace(get_server_selected=lambda: dict(host="synthetic", port=1)),
        patient_search_widget=SimpleNamespace(get_search_data=lambda: {}, set_searching_state=Mock()),
        search_progress=Mock(), connection_indicator=Mock(), show_loading=Mock(), hide_loading=Mock(),
        _update_connection_indicator_by_status=Mock(), _sync_completed_reporting_physicians_after_search=Mock(),
        _add_socket_patient_to_table=Mock(), thread_pool=None,
    )
    home._current_thumbnail_task.done.return_value = False
    # Exercise production selection predicates without constructing Home's DB/network graph.
    source = Path(__file__).resolve().parents[3] / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    names = {"_mark_active_patient_selection", "_is_active_patient_selection", "_thumbnail_task_cleanup"}
    ns = {"time": time, "asyncio": asyncio}
    for method in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names):
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), ns)
        setattr(home, method.name, ns[method.name].__get__(home))
    pt.click_timer.start(60000)
    home._thumbnail_request_timer.start(60000)
    service = HomeSearchService(home)
    monkeypatch.setattr(service, "_maybe_switch_profile_and_restart", lambda *a: False)
    monkeypatch.setattr(service, "_connectivity_is_fresh", lambda: True)
    monkeypatch.setattr(service, "_mark_connectivity", lambda *a: None)
    monkeypatch.setattr(service, "_maybe_probe_enrich_cost", lambda *a: None)
    monkeypatch.setattr(service, "_convert_search_data_to_socket_params", lambda *a: {})
    from PacsClient.pacs.workstation_ui.home_ui import home_search_service as search_module
    monkeypatch.setattr(search_module.QMessageBox, "critical", Mock(side_effect=AssertionError("Unexpected error dialog")))
    socket = SimpleNamespace(search_patients_sync=lambda params: [], test_connection=lambda: True)
    for name, members in (
        ("modules.network.socket_config", dict(update_socket_server_settings=lambda **kw: None,
                                               get_socket_server_settings=lambda: {"port": 1})),
        ("modules.network.socket_patient_service", dict(get_socket_patient_service=lambda: socket)),
        ("PacsClient.utils.server_profiles", dict(server_profiles_enabled=lambda: False,
                                                 socket_port_for_server=lambda server: 1)),
    ):
        fake = ModuleType(name)
        fake.__dict__.update(members)
        monkeypatch.setitem(sys.modules, name, fake)
    monkeypatch.setenv("AIPACS_SEARCH_SKIP_PROBE", "1")
    monkeypatch.setenv("AIPACS_SEARCH_KEEP_POOL", "1")
    yield SimpleNamespace(home=home, service=service, panel=panel, table=table, pt=pt, socket=socket)
    pt.click_timer.stop()
    home._thumbnail_request_timer.stop()
    panel._cancel_thumbnail_timer()
    table.deleteLater()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def search(scene, advanced):
    asyncio.run(scene.service.search_server_advanced({}) if advanced else scene.service.search_server())


@pytest.mark.parametrize("advanced", [False, True])
def test_empty_search_retires_preview_and_pending_selection(scene, advanced):
    task = scene.home._current_thumbnail_task
    search(scene, advanced)
    assert scene.table.rowCount() == 0
    assert scene.panel.content_grid.count() == 0
    assert scene.panel.count_label.text() == "0 series"
    assert scene.panel._active_action_token is None
    assert not scene.pt.click_timer.isActive()
    assert scene.pt._pending_selection_row == -1
    assert not scene.home._thumbnail_request_timer.isActive()
    assert scene.home._pending_thumbnail_row is None
    task.cancel.assert_called_once()
    assert scene.home._right_panel_fetch_inflight_uid == ""
    assert scene.home._right_panel_render_study_uid == ""
    assert not scene.home._is_active_patient_selection("synthetic-p", "synthetic-s")
    scene.home._mark_active_patient_selection("synthetic-new", "synthetic-new-study")
    assert scene.home._is_active_patient_selection("synthetic-new", "synthetic-new-study")


@pytest.mark.parametrize("advanced", [False, True])
def test_empty_query_preserves_surviving_pinned_selection(scene, advanced):
    scene.pt.keep = True
    token = scene.panel._active_action_token
    task = scene.home._current_thumbnail_task
    search(scene, advanced)
    assert scene.panel.content_grid.count() == 1
    assert scene.panel._active_action_token is token
    assert scene.home._is_active_patient_selection("synthetic-p", "synthetic-s")
    task.cancel.assert_not_called()
    # Row-number debounce must not leak into the next population, even with pins.
    assert not scene.pt.click_timer.isActive()
    assert scene.home._thumbnail_request_timer.isActive()
    assert scene.home._pending_thumbnail_row == scene.table.currentRow()


@pytest.mark.parametrize("advanced", [False, True])
@pytest.mark.parametrize("stop", ["cancel", "supersede"])
def test_cancelled_or_superseded_empty_response_keeps_current_preview(scene, advanced, stop):
    def finish(params):
        if stop == "cancel":
            scene.home._cancel_search_requested = True
        else:
            scene.home._search_generation += 1
        return []
    scene.socket.search_patients_sync = finish
    search(scene, advanced)
    assert scene.pt.clear_calls == 0
    assert scene.panel.content_grid.count() == 1
    assert scene.home._is_active_patient_selection("synthetic-p", "synthetic-s")


@pytest.mark.parametrize("advanced", [False, True])
def test_pin_without_matching_active_identity_does_not_keep_old_preview(scene, advanced):
    scene.pt.keep = True
    scene.home._active_thumb_study_uid = "different-study"
    search(scene, advanced)
    assert scene.table.rowCount() == 1
    assert scene.panel.content_grid.count() == 0


def test_initial_unselected_compatibility_is_not_explicit_retirement(scene):
    scene.home._active_thumb_patient_id = ""
    scene.home._active_thumb_study_uid = ""
    assert scene.home._is_active_patient_selection("synthetic-p", "synthetic-s")


def test_cancelled_thumbnail_cleanup_is_normal_and_cannot_clear_new_owner(scene):
    async def run():
        old = asyncio.create_task(asyncio.sleep(60))
        old.cancel()
        try:
            await old
        except asyncio.CancelledError:
            pass
        new = scene.home._current_thumbnail_task
        scene.home._thumbnail_task_cleanup(old)
        assert scene.home._current_thumbnail_task is new
    asyncio.run(run())


def test_failed_old_thumbnail_cleanup_cannot_clear_new_owner(scene):
    old = Mock()
    old.exception.return_value = RuntimeError("Synthetic failure")
    new = scene.home._current_thumbnail_task
    scene.home._thumbnail_task_cleanup(old)
    assert scene.home._current_thumbnail_task is new


@pytest.mark.parametrize("mode", ["local", "offline"])
def test_other_search_clear_boundaries_retire_preview_without_external_io(scene, monkeypatch, mode):
    from PacsClient.pacs.workstation_ui.home_ui import home_search_service as search_module
    if mode == "local":
        monkeypatch.setattr(search_module, "search_patients_local", lambda criteria: [])
        asyncio.run(scene.service.search_local())
    else:
        scene.home.data_access_panel_widget.get_server_selected = lambda: {"server_type": "offline_cloud"}
        monkeypatch.setattr(search_module, "list_offline_cloud_studies", lambda *a: [])
        asyncio.run(scene.service.search_server())
    assert scene.panel.content_grid.count() == 0
    assert not scene.home._is_active_patient_selection("synthetic-p", "synthetic-s")


def test_nonempty_socket_replacement_also_retires_removed_selection(scene):
    scene.socket.search_patients_sync = lambda params: [dict(patient_id="new-p", latest_study_uid="new-s")]
    search(scene, False)
    scene.home._add_socket_patient_to_table.assert_called_once()
    assert scene.panel.content_grid.count() == 0
    assert not scene.home._is_active_patient_selection("synthetic-p", "synthetic-s")


def test_pending_pinned_fetch_rebinds_after_row_removal(scene):
    scene.table.insertRow(0)
    assert scene.table.currentRow() == 1
    scene.home._pending_thumbnail_row = 1
    scene.pt.get_patient_data_by_row = lambda row: (
        dict(patient_id="synthetic-p", study_uid="synthetic-s")
        if row == scene.table.currentRow() else {})
    scene.pt.clear_table = lambda: scene.table.removeRow(0)
    search(scene, False)
    assert scene.table.currentRow() == 0
    assert scene.home._pending_thumbnail_row == 0
    assert scene.home._thumbnail_request_timer.isActive()
    assert scene.panel.content_grid.count() == 1


def test_empty_search_rejects_old_queued_render(scene):
    generation = scene.panel._display_generation
    search(scene, False)
    scene.panel.display_thumbnails_immediately([
        dict(study_uid="synthetic-s", series_uid="synthetic-series", image_count=1)
    ], generation)
    assert scene.panel.content_grid.count() == 0
    assert scene.panel.count_label.text() == "0 series"
