"""Bounded advanced search must visit older pages before claiming completion."""
import asyncio
from tests.code.ui_services.test_home_search_preview_retirement import scene


def test_older_matching_rows_are_found_with_filters_unchanged(scene):
    calls = []
    def fetch(params, **kwargs):
        calls.append(dict(params))
        start = params["offset"]
        return [dict(patient_id=f"synthetic-{i}", study_uid=f"study-{i}",
                     body_parts=["Knee" if i >= 100 else "Brain"], study_date="20260710")
                for i in range(start, min(start + 100, 205))]
    scene.socket.search_patients_sync = fetch
    query = dict(date_from="20260702", date_to="20260930", modalities=["MR"], body_part="knee")
    asyncio.run(scene.service.search_server_advanced(query))
    assert [c["offset"] for c in calls] == [0, 100, 200]
    assert all(c["date_from"] == "20260702" and c["modality"] == "MR" for c in calls)
    assert scene.home._add_socket_patient_to_table.call_count == 105


def test_superseded_page_does_not_render_or_hide_new_search(scene):
    def fetch(params, **kwargs):
        scene.home._search_generation += 1
        return [dict(patient_id="old", study_uid="old")]
    scene.socket.search_patients_sync = fetch
    asyncio.run(scene.service.search_server_advanced({}))
    scene.home._add_socket_patient_to_table.assert_not_called()
    scene.home.hide_loading.assert_not_called()
    assert scene.pt.clear_calls == 0


def test_cancel_between_pages_retains_partial_rows_and_yields(scene):
    calls = []
    def fetch(params, **kwargs):
        calls.append(params)
        return [dict(patient_id=str(i), study_uid=str(i)) for i in range(100)]
    scene.socket.search_patients_sync = fetch
    async def run():
        task = asyncio.create_task(scene.service.search_server_advanced({}))
        while not scene.home._add_socket_patient_to_table.call_count:
            await asyncio.sleep(0)
        scene.home._cancel_search_requested = True
        await task
    asyncio.run(run())
    assert len(calls) == 1
    assert 0 < scene.home._add_socket_patient_to_table.call_count < 100
    assert "incomplete" in scene.home._update_connection_indicator_by_status.call_args.args[1]


def test_repeated_page_stops_with_explicit_incomplete_notice(scene, monkeypatch):
    from unittest.mock import Mock
    from PacsClient.pacs.workstation_ui.home_ui import home_search_service as module
    warning = Mock(); monkeypatch.setattr(module.QMessageBox, "warning", warning)
    scene.socket.search_patients_sync = lambda p, **kw: [dict(patient_id=str(i), study_uid=str(i)) for i in range(100)]
    asyncio.run(scene.service.search_server_advanced({}))
    assert scene.home._add_socket_patient_to_table.call_count == 100
    assert "INCOMPLETE" in scene.home._update_connection_indicator_by_status.call_args.args[1]
    warning.assert_called_once()


def test_result_limit_is_bounded_and_visible(scene, monkeypatch):
    from unittest.mock import Mock
    from PacsClient.pacs.workstation_ui.home_ui import home_search_service as module
    monkeypatch.setattr(module.QMessageBox, "warning", Mock())
    monkeypatch.setattr(scene.service, "_ADVANCED_RESULT_LIMIT", 15)
    scene.socket.search_patients_sync = lambda p, **kw: [dict(patient_id=str(i), study_uid=str(i)) for i in range(100)]
    asyncio.run(scene.service.search_server_advanced({}))
    assert scene.home._add_socket_patient_to_table.call_count == 15
    assert "INCOMPLETE" in scene.home._update_connection_indicator_by_status.call_args.args[1]


def test_page_failure_never_claims_completion(scene, monkeypatch):
    from unittest.mock import Mock
    from PacsClient.pacs.workstation_ui.home_ui import home_search_service as module
    critical = Mock(); monkeypatch.setattr(module.QMessageBox, "critical", critical)
    def fetch(params, **kwargs):
        if params["offset"]:
            raise RuntimeError("Synthetic connection failure")
        return [dict(patient_id=str(i), study_uid=str(i)) for i in range(100)]
    scene.socket.search_patients_sync = fetch
    asyncio.run(scene.service.search_server_advanced({}))
    assert scene.home._add_socket_patient_to_table.call_count == 100
    assert "incomplete" in scene.home._update_connection_indicator_by_status.call_args.args[1]
    critical.assert_called_once()


def test_strict_socket_failure_returns_client_and_raises():
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import Mock
    import pytest
    tree = ast.parse(Path("modules/network/socket_patient_service.py").read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "search_patients_sync")
    namespace = dict(Dict=dict, Any=object, List=list, logger=Mock())
    exec(compile(ast.Module(body=[node], type_ignores=[]), "strict-search", "exec"), namespace)
    client = SimpleNamespace(get_patient_list_safe=lambda **kw: None)
    owner = SimpleNamespace(_get_client=lambda: client, _return_client=Mock())
    with pytest.raises(RuntimeError):
        namespace["search_patients_sync"](owner, {}, raise_on_error=True)
    owner._return_client.assert_called_once_with(client)
    assert namespace["search_patients_sync"](owner, {}) == []


def test_paged_search_never_covers_the_interactive_tab(scene):
    asyncio.run(scene.service.search_server_advanced({}))
    scene.home.show_loading.assert_not_called()
    scene.home.hide_loading.assert_not_called()


def test_external_stream_defers_whole_table_work():
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    source = Path("PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py")
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_stream_in_flight")
    ns = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), ns)
    owner = SimpleNamespace(_external_search_generation=12, _prog_cursor=0, _prog_total=0)
    assert ns["_stream_in_flight"](owner)
    owner._external_search_generation = None
    assert not ns["_stream_in_flight"](owner)


def test_page_metadata_runs_off_gui_and_stream_retires(scene, monkeypatch):
    import threading
    gui_thread = threading.get_ident()
    worker_threads = []
    def prefetch(rows):
        worker_threads.append(threading.get_ident())
        return dict(uids=[], imported_at={}, known_patient_ids={"known"})
    monkeypatch.setattr(scene.service, "_prefetch_advanced_page", prefetch)
    scene.socket.search_patients_sync = lambda p, **kw: [dict(patient_id="known", latest_study_uid="synthetic")]
    def render(row):
        assert scene.pt._external_search_generation == scene.home._search_generation
        assert threading.get_ident() == gui_thread
    scene.home._add_socket_patient_to_table.side_effect = render
    asyncio.run(scene.service.search_server_advanced({}))
    assert worker_threads and all(t != gui_thread for t in worker_threads)
    assert scene.pt._external_search_generation is None
    scene.pt._arm_stream_settle_sort.assert_called_once()


def test_prefetch_covers_patient_and_nested_study_references(monkeypatch):
    from PacsClient.pacs.workstation_ui.home_ui.home_search_service import HomeSearchService
    references = []
    monkeypatch.setattr(HomeSearchService, "_collect_list_prefetch", staticmethod(lambda rows: references.extend(rows)))
    HomeSearchService._prefetch_advanced_page([dict(patient_id="synthetic", latest_study_uid="one",
        study_uids=["two"], studies=[dict(StudyInstanceUID="three")])])
    assert {r["study_uid"] for r in references} == {"one", "two", "three"}
