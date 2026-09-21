"""Synthetic Qt guards for command selection of current Home result rows."""
from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import time

import pytest
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QWidget
from PySide6.QtTest import QTest

from modules.EchoMind.secretary.adapters.home_command_adapter import HomeCommandAdapter
from modules.EchoMind.secretary.adapters.home_widget_adapter import HomeWidgetAdapter
from modules.EchoMind.secretary.command_envelope import CommandPlan


_TABLE = Path(__file__).resolve().parents[3] / "PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py"
_METHODS = {"_emit_patient_selection", "_emit_patient_selection_now",
            "_on_current_row_changed", "_on_single_click_timeout"}
_tree = ast.parse(_TABLE.read_text(encoding="utf-8-sig"))
_methods = [node for owner in _tree.body if isinstance(owner, ast.ClassDef)
            for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in _METHODS]
_ns = {"QApplication": QApplication, "time": time,
       "COL": {"patient_id": 0, "patient_name": 1, "study_uid": 2}}
exec(compile(ast.Module(body=_methods, type_ignores=[]), str(_TABLE), "exec"), _ns)


class SelectionPanel(QWidget):
    patientClicked = Signal(str, str, str)
    thumbnailRequested = Signal(int)

    def __init__(self):
        super().__init__()
        self.results_table = QTableWidget(0, 3, self)
        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self._on_single_click_timeout)
        self.results_table.selectionModel().currentRowChanged.connect(self._on_current_row_changed)

    def add(self, pid, uid, name="Synthetic patient", study_uids=None):
        table = self.results_table
        row = table.rowCount()
        table.insertRow(row)
        for col, value in enumerate((pid, name, uid)):
            table.setItem(row, col, QTableWidgetItem(value))
        table.item(row, 0).setData(Qt.UserRole, {
            "patient_id": pid, "patient_name": name, "study_uid": uid,
            "study_uids": study_uids or [uid],
        })

    def get_patient_data_by_row(self, row):
        item = self.results_table.item(row, 0)
        return dict(item.data(Qt.UserRole)) if item else None


for _name in _METHODS:
    setattr(SelectionPanel, _name, _ns[_name])


@pytest.fixture
def qtbot():
    """Use the bundled Qt test API; pytest-qt is not a checkout dependency."""
    app = QApplication.instance() or QApplication([])
    widgets = []

    def wait_until(predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        assert predicate(), "Timed out waiting for deferred selection"

    yield SimpleNamespace(addWidget=widgets.append, waitUntil=wait_until)
    for widget in widgets:
        widget.click_timer.stop()
        widget.close()
        widget.deleteLater()
    app.processEvents()


@pytest.fixture
def selection(qtbot):
    panel = SelectionPanel()
    qtbot.addWidget(panel)
    panel.add("CASE-A", "study-a")
    panel.add("CASE-B", "study-b")
    emitted = []
    thumbnails = []
    direct = []
    panel.patientClicked.connect(lambda *args: emitted.append(args))
    panel.thumbnailRequested.connect(thumbnails.append)
    home = SimpleNamespace(patient_table_widget=panel, _search_task=None,
                           _on_patient_single_clicked=lambda *args: direct.append(args))
    return HomeWidgetAdapter(home), panel, emitted, thumbnails, direct


def test_select_sets_current_row_then_uses_normal_deferred_signals(selection, qtbot):
    adapter, panel, emitted, thumbnails, direct = selection
    result = adapter.select_patient("CASE-B", "Untrusted name", "study-b")
    assert panel.results_table.currentRow() == 1
    assert result["patient_name"] == "Synthetic patient"
    assert not emitted and not direct
    qtbot.waitUntil(lambda: len(emitted) == 1)
    assert emitted == [("CASE-B", "Synthetic patient", "study-b")]
    assert thumbnails == [1]


@pytest.mark.parametrize("pid,uid", [
    ("CASE", ""), ("MISSING", "study-a"), ("CASE-A", "study-b"), ("", "study-a")])
def test_missing_or_foreign_identity_never_selects(selection, pid, uid):
    adapter, panel, emitted, _, direct = selection
    with pytest.raises(ValueError):
        adapter.select_patient(pid, "Synthetic patient", uid)
    assert panel.results_table.currentRow() == -1
    assert not emitted and not direct and not panel.click_timer.isActive()


def test_hidden_row_is_not_a_current_result(selection):
    adapter, panel, _, _, direct = selection
    panel.results_table.setRowHidden(1, True)
    with pytest.raises(ValueError):
        adapter.select_patient("CASE-B", "", "study-b")
    assert not direct and panel.results_table.currentRow() == -1


@pytest.mark.parametrize("uid", ["", "study-a"])
def test_duplicate_current_identity_is_ambiguous(selection, uid):
    adapter, panel, _, _, direct = selection
    panel.add("CASE-A", "study-a")
    with pytest.raises(ValueError):
        adapter.select_patient("CASE-A", "", uid)
    assert not direct and panel.results_table.currentRow() == -1


def test_grouped_secondary_uid_resolves_to_canonical_row(selection, qtbot):
    adapter, panel, emitted, _, direct = selection
    panel.add("CASE-C", "study-c-primary", study_uids=["study-c-primary", "study-c-extra"])
    result = adapter.select_patient("CASE-C", "", "study-c-extra")
    assert result["study_uid"] == "study-c-primary"
    qtbot.waitUntil(lambda: len(emitted) == 1)
    assert emitted[0][2] == "study-c-primary" and not direct


def test_selection_follows_sorted_rows_not_cached_indices(selection, qtbot):
    adapter, panel, emitted, _, _ = selection
    panel.results_table.setSortingEnabled(True)
    panel.results_table.sortItems(0, Qt.DescendingOrder)
    adapter.select_patient("CASE-B", "", "study-b")
    assert panel.results_table.currentRow() == 0
    qtbot.waitUntil(lambda: len(emitted) == 1)
    assert emitted[0][0] == "CASE-B"


def test_rapid_selection_supersedes_pending_selection(selection, qtbot):
    adapter, panel, emitted, thumbnails, direct = selection
    adapter.select_patient("CASE-A", "", "study-a")
    adapter.select_patient("CASE-B", "", "study-b")
    adapter.select_patient("CASE-B", "", "study-b")
    qtbot.waitUntil(lambda: len(emitted) == 1)
    assert emitted == [("CASE-B", "Synthetic patient", "study-b")]
    assert thumbnails == [1] and not direct


def test_search_in_progress_rejects_selection(selection):
    adapter, panel, _, _, direct = selection
    adapter.home._search_task = SimpleNamespace(done=lambda: False)
    with pytest.raises(RuntimeError):
        adapter.select_patient("CASE-A", "", "study-a")
    assert not direct and panel.results_table.currentRow() == -1


def test_off_gui_thread_rejected_before_widget_access(selection):
    adapter, panel, _, _, direct = selection
    with ThreadPoolExecutor(max_workers=1) as worker:
        result = worker.submit(adapter.select_patient, "CASE-A", "", "study-a")
        with pytest.raises(RuntimeError):
            result.result(timeout=2)
    assert not direct and panel.results_table.currentRow() == -1


def test_command_ignores_accumulated_search_cache(selection, qtbot):
    adapter, panel, emitted, _, _ = selection
    adapter.read_patient_rows = lambda: [{"patient_id": "CASE-A", "patient_name": "Stale",
                                         "study_uid": "stale-study"}]
    result = HomeCommandAdapter(adapter).select_patient(
        CommandPlan(action="select_patient", entities={"patient_id": "CASE-A"}), {})
    assert result.ok
    assert result.data["study_uid"] == "study-a"
    assert result.data["selection_state"] == "queued"
    assert panel.results_table.currentRow() == 0
    qtbot.waitUntil(lambda: len(emitted) == 1)
    assert emitted[0][2] == "study-a"


def test_stale_cache_only_match_is_not_success(selection):
    adapter, panel, _, _, direct = selection
    adapter.read_patient_rows = lambda: [{"patient_id": "GONE", "patient_name": "Stale",
                                         "study_uid": "gone-study"}]
    result = HomeCommandAdapter(adapter).select_patient(
        CommandPlan(action="select_patient", entities={"patient_id": "GONE"}), {})
    assert not result.ok and result.error_code == "HOME_SELECT_FAILED"
    assert not direct and panel.results_table.currentRow() == -1


def test_missing_canonical_study_identity_is_rejected(selection):
    adapter, panel, _, _, direct = selection
    panel.add("CASE-C", "", study_uids=["study-c-extra"])
    with pytest.raises(ValueError):
        adapter.select_patient("CASE-C", "", "study-c-extra")
    assert not direct and panel.results_table.currentRow() == -1


def test_reentrant_result_replacement_is_not_reported_as_success(selection):
    adapter, panel, _, _, direct = selection

    def replace_rows(current, previous):
        panel.results_table.item(current.row(), 0).setData(Qt.UserRole, {
            "patient_id": "REPLACED", "study_uid": "replacement-study"})

    panel.results_table.selectionModel().currentRowChanged.connect(replace_rows)
    with pytest.raises(RuntimeError, match="changed during dispatch"):
        adapter.select_patient("CASE-A", "", "study-a")
    assert not direct


def test_selection_has_no_io_or_nested_event_pump(selection, monkeypatch):
    adapter, panel, emitted, _, direct = selection

    def forbidden(*args, **kwargs):
        raise AssertionError("Selection must only read the current Qt model")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("os.scandir", forbidden)
    monkeypatch.setattr("sqlite3.connect", forbidden)
    monkeypatch.setattr(QApplication, "processEvents", forbidden)
    adapter.select_patient("CASE-A", "", "study-a")
    assert panel.click_timer.isActive() and not emitted and not direct
