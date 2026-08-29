"""Regression guards for a network-independent Local workflow.

Local search, single/multi-study preview, and an already-downloaded viewer must
never require the live PACS socket. Server mode keeps its refresh behavior.
"""

import ast
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
HP_SERIES = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py"
HP_SEARCH = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_search.py"
HP_MODULES = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_modules.py"
HP_OPEN = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py"
PW_THUMBS = REPO / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py"


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    node = next(
        item for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    return ast.get_source_segment(source, node)


def test_local_database_auto_sync_is_opt_in(monkeypatch):
    monkeypatch.delenv("AIPACS_LOCALDB_AUTO_SERVER_SYNC", raising=False)
    from modules.storage import sync_mode_policy as policy

    assert policy.requires_remote_resync("db") is False
    assert policy.requires_live_server_sync("db") is False
    assert policy.missing_files_trigger_server_download("db") is False

    monkeypatch.setenv("AIPACS_LOCALDB_AUTO_SERVER_SYNC", "1")
    assert policy.requires_remote_resync("db") is True


def test_single_click_reconcile_returns_local_rows_before_socket_access():
    body = _function_source(HP_SERIES, "_reconcile_patient_studies_on_click")
    gate = body.index("requires_remote_resync")
    socket = body.index("get_socket_patient_service")
    assert gate < socket
    assert "return local_uids" in body[gate:socket]


def test_local_cache_miss_returns_before_home_thumbnail_socket():
    body = _function_source(HP_SEARCH, "show_patient_studies")
    local_branch = body.index("right_panel_cache_miss_local_mode")
    socket = body.index("PatientListSocketClient")
    assert local_branch < socket
    assert "return" in body[local_branch:socket]
    assert "_build_local_series_thumbnail_payload" in body[local_branch:socket]


def test_grouped_local_preview_does_not_require_selected_server():
    body = _function_source(HP_MODULES, "_show_grouped_patient_studies")
    local_gate = body.index("local_is_source_of_truth")
    server_lookup = body.index("get_server_selected")
    assert local_gate < server_lookup
    assert "_build_local_series_thumbnail_payload" in body


def test_local_viewer_thumbnail_cache_miss_returns_before_socket_import():
    body = _function_source(PW_THUMBS, "_load_server_thumbnails_async")
    local_branch = body.index("patient_tab_thumb_cache_miss_local_mode")
    socket = body.index("PatientListSocketClient")
    assert local_branch < socket
    assert "return" in body[local_branch:socket]


def test_local_open_does_not_refresh_existing_tab_or_previous_exams_from_server():
    body = _function_source(HP_OPEN, "_on_patient_double_clicked_async")
    assert "local_is_source_of_truth" in body
    refresh = body.index("_OPEN_REFRESH_ALREADY_OPEN")
    resync = body.index("_resync_patient_studies_from_server", refresh)
    assert "local_is_source_of_truth" in body[refresh:resync]
    previous = body.index("init_previous_exams")
    assert "if not is_local" in body[max(0, previous - 400):previous]


def test_local_multistudy_open_pushes_disk_series_metadata_to_viewer():
    body = _function_source(HP_OPEN, "_on_patient_double_clicked_async")
    background = body.index("def _background_setup_thread")
    aggregate = body.index("aggregated_series = []", background)
    push = body.index("widget.set_server_series_info(series_list)", aggregate)
    local_branch = body.index("if is_local:", aggregate, push)

    assert "_build_local_series_thumbnail_payload" in body[local_branch:push]
    assert "for current_study_uid in all_study_uids" in body[local_branch:push]
