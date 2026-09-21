"""Synthetic native template/case UI; injected storage and study resolver only."""
import copy
import threading
import time
from types import SimpleNamespace

import pytest

from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from modules.ai_imaging.eagle_eye.datasets.definitions import lumbar_template
from modules.ai_imaging.eagle_eye.datasets.dialogs import CaseDialog, TemplateDialog
from modules.ai_imaging.eagle_eye.datasets.repository import DatasetRepository
from modules.ai_imaging.eagle_eye.datasets.workspace import DatasetWorkspace


_app = None


@pytest.fixture
def qtbot():
    """Small event-loop harness; pytest-qt is not a development dependency."""
    global _app
    _app = QApplication.instance() or QApplication([])
    widgets = []
    def wait_until(predicate, timeout=5000):
        deadline = time.monotonic() + timeout / 1000
        while not predicate():
            if time.monotonic() >= deadline:
                pytest.fail("Synthetic Qt operation did not finish")
            QTest.qWait(10)
    yield SimpleNamespace(addWidget=widgets.append, waitUntil=wait_until)
    for widget in reversed(widgets):
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    _app.processEvents()


def context(uid):
    return {"study_uid": uid, "patient_id": "SYNTHETIC-001", "patient_name": "Synthetic example",
            "modality": "MR", "study_date": "20260913", "source_namespace": "local-pacs"}


def wait_idle(qtbot, widget):
    qtbot.waitUntil(lambda: not widget.pending, timeout=5000)


def test_template_builder_add_remove_and_repeat(qtbot):
    dialog = TemplateDialog()
    qtbot.addWidget(dialog)
    dialog.remove_field("disc_bulge")
    dialog.add_field()
    row = dialog.fields.rowCount() - 1
    dialog.fields.item(row, 0).setText("Custom severity")
    dialog.fields.cellWidget(row, 1).setCurrentText("choice")
    dialog.fields.cellWidget(row, 2).setCurrentIndex(1)
    dialog.fields.cellWidget(row, 3).setCurrentIndex(1)
    dialog.fields.setItem(row, 4, QTableWidgetItem("low; high"))
    template = dialog.template()
    assert not any(f["id"] == "disc_bulge" for f in template["fields"])
    assert template["fields"][-1]["options"] == ["low", "high"]
    assert template["fields"][-1]["scope"] == "region"
    assert template["fields"][-1]["required"] is True
    dialog.dirty = False


def test_case_form_has_distinct_level_values_and_no_default_negatives(qtbot, tmp_path):
    repo = DatasetRepository(tmp_path)
    dataset = repo.create_dataset(lumbar_template())
    document = repo.add_case(dataset["id"], context("1.2.826.0.1.1"))
    dialog = CaseDialog(document)
    qtbot.addWidget(dialog)
    assert len(dialog.inputs) == 76
    assert dialog.windowModality() == Qt.NonModal
    assert dialog.values() == {}
    dialog.inputs["L5-S1/disc_extrusion"][0].setCurrentText("present")
    dialog.inputs["L4-L5/disc_extrusion"][0].setCurrentText("absent")
    assert dialog.values() == {"L5-S1/disc_extrusion": "present", "L4-L5/disc_extrusion": "absent"}
    dialog.dirty = False


def test_native_create_enroll_save_reopen_and_count(qtbot, tmp_path):
    repo = DatasetRepository(tmp_path)
    threads = []
    def loader(uid):
        threads.append(threading.get_ident())
        return context(uid)
    workspace = DatasetWorkspace("1.2.826.0.1.1", repo, loader)
    qtbot.addWidget(workspace)
    workspace.show()
    workspace.refresh()
    wait_idle(qtbot, workspace)
    workspace.new_dataset()
    workspace.dialog.name.setText("Synthetic lumbar collection")
    workspace.dialog.submit()
    qtbot.waitUntil(lambda: workspace.dialog is None and not workspace.pending, timeout=5000)
    assert workspace.selected_id
    workspace.add_current_study()
    qtbot.waitUntil(lambda: isinstance(workspace.dialog, CaseDialog) and not workspace.pending, timeout=5000)
    assert threads == [threads[0]] and threads[0] != threading.get_ident()
    workspace.dialog.inputs["L5-S1/disc_extrusion"][0].setCurrentText("present")
    workspace.dialog.author.setText("Synthetic reviewer")
    workspace.dialog.submit("complete")
    wait_idle(qtbot, workspace)
    assert workspace.dialog.document["status"] == "complete"
    workspace.dialog.reject()
    wait_idle(qtbot, workspace)
    assert workspace.table.rowCount() == 1
    assert workspace.table.item(0, 3).text() == "complete"
    workspace.add_current_study()
    qtbot.waitUntil(lambda: isinstance(workspace.dialog, CaseDialog) and not workspace.pending, timeout=5000)
    assert workspace.dialog.values()["L5-S1/disc_extrusion"] == "present"
    workspace.dialog.reject()
    wait_idle(qtbot, workspace)
    assert workspace.table.rowCount() == 1
    workspace.search.setText("no match")
    assert workspace.table.isRowHidden(0)
    workspace.search.clear()
    workspace.table.selectRow(0)
    workspace.open_case()
    qtbot.waitUntil(lambda: isinstance(workspace.dialog, CaseDialog) and not workspace.pending, timeout=5000)
    assert workspace.dialog.values()["L5-S1/disc_extrusion"] == "present"
    workspace.dialog.reject()
    wait_idle(qtbot, workspace)


def test_template_edit_retains_old_case_form(qtbot, tmp_path):
    repo = DatasetRepository(tmp_path)
    dataset = repo.create_dataset(lumbar_template())
    old = repo.add_case(dataset["id"], context("1.2.826.0.1.1"))
    new = copy.deepcopy(dataset["template"])
    new["fields"] = [f for f in new["fields"] if f["id"] != "disc_extrusion"]
    repo.update_dataset(dataset["id"], new, 1)
    dialog = CaseDialog(repo.get_case(old["id"]))
    qtbot.addWidget(dialog)
    assert "L5-S1/disc_extrusion" in dialog.inputs


def test_dataset_tab_keeps_legacy_results_and_skips_disk_scan_on_entry(qtbot, monkeypatch):
    from modules.ai_imaging.ai_module_ui.service_tab.dataset_tab import DataSetTab
    calls = []
    monkeypatch.setattr(DatasetWorkspace, "refresh", lambda self: calls.append("catalog"))
    monkeypatch.setattr(DataSetTab, "_refresh_results", lambda self: calls.append("legacy"))
    widget = DataSetTab(study_uid="synthetic-study")
    qtbot.addWidget(widget)
    widget.refresh()
    assert calls == ["catalog"]
    widget.get_stacked_layout().setCurrentIndex(1)
    assert calls == ["catalog", "legacy"]
    widget.set_rows([{"study_instance_uid": "1.2.826.0.1.1", "label": "synthetic"}])
    assert widget._rows_cache[0]["label"] == "synthetic"
    widget.get_stacked_layout().setCurrentIndex(0)
    widget.set_csv_paths(["synthetic.csv"])
    assert calls[-1] == "legacy"


def test_storage_failure_keeps_template_edits(qtbot, tmp_path):
    class Broken(DatasetRepository):
        def create_dataset(self, template):
            raise OSError("synthetic private path must not reach the UI")
    workspace = DatasetWorkspace(repository=Broken(tmp_path), context_loader=context)
    qtbot.addWidget(workspace)
    workspace.new_dataset()
    workspace.dialog.name.setText("Keep this edit")
    workspace.dialog.submit()
    wait_idle(qtbot, workspace)
    assert workspace.dialog.name.text() == "Keep this edit"
    assert workspace.dialog.isEnabled()
    assert "private path" not in workspace.dialog.error.text()
    workspace.dialog.dirty = False
    workspace.dialog.reject()
    wait_idle(qtbot, workspace)


def test_refresh_does_not_discard_an_open_draft(qtbot, tmp_path):
    repo = DatasetRepository(tmp_path)
    dataset = repo.create_dataset(lumbar_template())
    case = repo.add_case(dataset["id"], context("1.2.826.0.1.1"))
    workspace = DatasetWorkspace(repository=repo)
    qtbot.addWidget(workspace)
    workspace._open_document(case)
    workspace.dialog.inputs["case/notes"][0].setPlainText("Unsaved synthetic note")
    workspace.refresh()
    assert workspace.dialog.values()["case/notes"] == "Unsaved synthetic note"
    assert not workspace.pending
    workspace.dialog.dirty = False
    workspace.dialog.reject()
    wait_idle(qtbot, workspace)


def test_closed_workspace_does_not_receive_a_late_job(qtbot, tmp_path):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    class Slow(DatasetRepository):
        def list_datasets(self):
            entered.set()
            try:
                assert release.wait(3)
                return []
            finally:
                finished.set()
    widget = DatasetWorkspace(repository=Slow(tmp_path))
    widget.refresh()
    qtbot.waitUntil(entered.is_set)
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    release.set()
    qtbot.waitUntil(finished.is_set)
    QTest.qWait(20)


def test_viewing_another_case_does_not_change_current_study(qtbot, tmp_path):
    repo = DatasetRepository(tmp_path)
    dataset = repo.create_dataset(lumbar_template())
    other = repo.add_case(dataset["id"], context("1.2.826.0.1.2"))
    widget = DatasetWorkspace("1.2.826.0.1.1", repo, context)
    qtbot.addWidget(widget)
    widget._open_document(other)
    assert widget.dialog.document["study_uid"] == "1.2.826.0.1.2"
    assert widget.study_uid == "1.2.826.0.1.1"
    widget.dialog.reject()
    wait_idle(qtbot, widget)
