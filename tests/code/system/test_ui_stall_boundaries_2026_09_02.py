import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _function_body(path: str, class_name: str, function_name: str) -> str:
    source = (ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == function_name:
                    return ast.get_source_segment(source, child) or ""
    raise AssertionError(f"{class_name}.{function_name} not found in {path}")


def test_components_package_does_not_eagerly_import_retired_grpc():
    source = (ROOT / "PacsClient" / "components" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    eager_modules = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "modules.network.grpc_client" not in eager_modules
    assert "modules.network.dicom_downloader" not in eager_modules


def test_control_panel_does_not_repolish_the_completed_tree_from_the_root():
    init_body = _function_body(
        "PacsClient/pacs/workstation_ui/AIPacs_ui.py", "ControlPanelInterface", "__init__"
    )
    theme_body = _function_body(
        "PacsClient/pacs/workstation_ui/AIPacs_ui.py", "ControlPanelWindow", "apply_theme"
    )
    assert "self.setStyleSheet(" not in init_body
    assert "self.MainWindow.setStyleSheet(" not in theme_body


def test_enabled_agent_gateway_uses_the_nonblocking_start_boundary():
    home = (ROOT / "PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py").read_text(
        encoding="utf-8"
    )
    service = (ROOT / "modules/agent_gateway/service.py").read_text(encoding="utf-8")
    assert "_gw.start_if_enabled_async()" in home
    assert "def start_if_enabled_async(" in service


def test_patient_tab_activation_never_scans_study_files_inline():
    body = _function_body(
        "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_cache.py",
        "_VCCacheMixin",
        "on_tab_activated",
    )
    assert "check_study_complete(" not in body
    assert "_schedule_activation_study_check(" in body


def test_zeta_manifest_schema_is_initialized_off_the_ui_path():
    body = _function_body("modules/zeta_boost/disk_cache.py", "ZetaBoostDiskCache", "__init__")
    conn_body = _function_body("modules/zeta_boost/disk_cache.py", "ZetaBoostDiskCache", "_conn")
    assert "_start_schema_initialization" in body
    assert "PRAGMA journal_mode = WAL" not in conn_body


def test_voice_stop_dispatches_wav_flush_instead_of_writing_inline():
    source = (
        ROOT
        / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/voice_tool_ui.py"
    ).read_text(encoding="utf-8")
    body = _function_body(
        "PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/voice_tool_ui.py",
        "VoiceWidget",
        "_on_stop_internal",
    )
    assert "def _write_wav_atomic(" in source
    assert "sf.write(" not in body
    assert "_dispatch_wav_write(" in body


def test_eagle_eye_builds_only_the_active_imaging_tab_at_startup():
    body = _function_body(
        "modules/ai_imaging/ai_module_ui/ai_mainwindow.py", "AiMainWindow", "__init__"
    )
    assert "ImagingToolsTab(" in body
    assert "DataSetTab(" not in body
    assert "ModelTrainingTab(" not in body
    assert "ReceptionDataTab(" not in body
    assert "_install_lazy_tabs(" in body


def test_eagle_eye_series_probe_is_dispatched_off_the_gui_thread():
    body = _function_body(
        "modules/ai_imaging/eagle_eye_lumbar/workflow_coordinator.py",
        "EagleEyeWorkflowCoordinator",
        "start_capture",
    )
    assert "build_candidates_for_widget(" not in body
    assert "_start_series_probe(" in body
