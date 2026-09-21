"""Unified patient-open identity and tab-admission regression guards."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from PacsClient.pacs.workstation_ui.home_ui.home_tab_service import HomeTabService


ROOT = Path(__file__).resolve().parents[3]
HP_MODULES = ROOT / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_modules.py"
HP_OPEN = ROOT / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py"
HP_WIDGET = ROOT / "PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py"
THUMB_UTILS = ROOT / "PacsClient/pacs/patient_tab/utils/utils.py"


class _CapacityManager:
    def __init__(self, active=0):
        self.active = active
        self.study_uid_to_tab = {}

    def patient_tab_count(self):
        return self.active


@pytest.fixture
def tab_service():
    app = QApplication.instance() or QApplication([])
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "Home")
    manager = _CapacityManager()
    service = HomeTabService(tabs, manager)
    yield app, tabs, manager, service
    tabs.close()
    tabs.deleteLater()


def test_capacity_is_rejected_before_any_patient_widget_is_constructed(tab_service):
    _app, _tabs, manager, service = tab_service
    from PacsClient.pacs.patient_tab.ui.patient_ui.custom_tab_manager import MAX_PATIENT_TABS

    manager.active = MAX_PATIENT_TABS
    admission = service.reserve_patient_tab("study-new")
    assert admission.status == "capacity"
    assert not admission.admitted
    assert service.patient_tab_reservations == frozenset()


def test_full_capacity_never_calls_real_patient_widget_factory(tab_service, monkeypatch):
    _app, tabs, manager, service = tab_service
    from PacsClient.pacs.patient_tab.ui.patient_ui.custom_tab_manager import MAX_PATIENT_TABS
    from PacsClient.pacs.workstation_ui.home_ui.home_panel import _hp_modules

    manager.active = MAX_PATIENT_TABS
    manager.find_tab_by_study_uid = lambda _uid: -1
    warnings = []
    owner = SimpleNamespace(
        tab_widget=tabs,
        custom_tab_manager=manager,
        tab_service=service,
        dict_tabs_widget={},
        _defer_patient_tab_limit_warning=lambda limit: warnings.append(limit),
    )

    def forbidden_factory():
        raise AssertionError("PatientWidget construction must follow admission")

    monkeypatch.setattr(_hp_modules, "_ensure_patient_widget", forbidden_factory)
    result = _hp_modules._HPModulesMixin.add_new_tab_widget(
        owner,
        patient_id="synthetic-patient",
        patient_name="Synthetic",
        study_uid="synthetic-study",
    )
    assert result is None
    assert warnings == [MAX_PATIENT_TABS]
    assert service.patient_tab_reservations == frozenset()


def test_capacity_reservation_is_single_flight_and_released(tab_service):
    _app, _tabs, manager, service = tab_service
    from PacsClient.pacs.patient_tab.ui.patient_ui.custom_tab_manager import MAX_PATIENT_TABS

    manager.active = MAX_PATIENT_TABS - 1
    first = service.reserve_patient_tab("study-a")
    second = service.reserve_patient_tab("study-b")
    duplicate = service.reserve_patient_tab("study-a")

    assert first.admitted
    assert second.status == "capacity"
    assert duplicate.status == "duplicate"
    service.abort_patient_tab("study-a")
    assert service.reserve_patient_tab("study-b").admitted


def test_opening_state_has_one_service_owner(tab_service):
    _app, _tabs, _manager, service = tab_service
    assert service.begin_patient_open("study-a")
    assert not service.begin_patient_open("study-a")
    service.end_patient_open("study-a")
    assert service.begin_patient_open("study-a")

    source = HP_WIDGET.read_text(encoding="utf-8-sig")
    assert "self._opening_studies = self.tab_service.opening_studies" in source
    assert "self._opening_studies = set()" not in source


def _call_lines(path: Path, function_name: str) -> dict[str, list[int]]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    )
    found: dict[str, list[int]] = {}
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        parts = []
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
        name = ".".join(reversed(parts))
        found.setdefault(name, []).append(node.lineno)
    return found


def test_open_identity_is_finalized_before_tab_creation():
    calls = _call_lines(HP_OPEN, "_on_patient_double_clicked_async")
    finalizer = calls["finalize_open_study_identity"][0]
    constructor = calls["self.add_new_tab_widget"][0]
    assert finalizer < constructor


def test_capacity_reservation_precedes_patient_widget_constructor():
    calls = _call_lines(HP_MODULES, "add_new_tab_widget")
    reserve = calls["self.tab_service.reserve_patient_tab"][0]
    constructor = calls["_ensure_patient_widget"][0]
    assert reserve < constructor


def test_empty_study_uid_never_enumerates_thumbnail_root():
    tree = ast.parse(THUMB_UTILS.read_text(encoding="utf-8-sig"))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "get_all_series_thumbnail_from_study_folder"
    )
    calls = []

    def forbidden(_path):
        calls.append(True)
        raise AssertionError("empty identity must not enumerate the thumbnail root")

    namespace = {
        "_thumbnail_cache": {},
        "is_cache_valid": lambda _uid: False,
        "remove_from_cache": lambda _uid: None,
        "THUMBNAIL_PATH": Path("thumbnail-root"),
        "get_image_files": forbidden,
        "cache_thumbnail_data": lambda *_args: None,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(THUMB_UTILS), "exec"), namespace)
    assert namespace[function.name]("  ") == []
    assert calls == []
