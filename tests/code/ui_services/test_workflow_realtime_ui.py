"""Actual Qt cells, synthetic identities, no application DB or network."""
import ast
from pathlib import Path
from types import SimpleNamespace, ModuleType
import sys

import pytest
from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget, QTableWidget, QTableWidgetItem, QLabel, QHBoxLayout

from modules.network.workflow_realtime import Mailbox

COL = dict(patient_name=1, patient_id=2, status=4, report=5, assign=6, study_uid=13)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def ui(qapp, monkeypatch):
    name = "PacsClient.pacs.workstation_ui.home_ui.patient_table_widget"
    stub = ModuleType(name); stub.COL = COL
    monkeypatch.setitem(sys.modules, name, stub)
    class Receiver:
        def __init__(self, *args):
            self.mailbox = Mailbox(); self.alive = False
        def start(self): self.alive = True
        def stop(self): self.alive = False
        def is_alive(self): return self.alive
        def watch(self, uids): self.watched = tuple(uids)
    source = Path("PacsClient/pacs/workstation_ui/home_ui/workflow_realtime.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef))
    token = SimpleNamespace(get_token=lambda: "synthetic")
    import os
    env = dict(QObject=QObject, QTimer=QTimer, Qt=Qt, QLabel=QLabel, os=os,
               WorkflowReceiver=Receiver, get_socket_token_manager=lambda: token,
               __package__="PacsClient.pacs.workstation_ui.home_ui", __name__="synthetic_ui")
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<workflow-ui>", "exec"), env)
    home = QWidget(); home.resize(900, 400)
    table = QTableWidget(2, 14, home); table.resize(800, 300)
    for row in range(2):
        for col, text in [(1, "Synthetic"), (2, f"p{row}"), (13, f"1.2.{row}")]:
            table.setItem(row, col, QTableWidgetItem(text))
        for col in (4, 5):
            widget = QWidget(); layout = QHBoxLayout(widget)
            label = QLabel("original"); label.reception_id = f"p{row}"
            layout.addWidget(label); table.setCellWidget(row, col, widget)
        table.setCellWidget(row, 6, QLabel("unassigned"))
    table.selectRow(1)
    owner = SimpleNamespace(results_table=table, _icon_pixmap=lambda *a: QPixmap(10, 10),
                            _apply_report_status_display=lambda label, status, physician, **kw: label.setText(status),
                            _on_report_status_clicked=lambda *a: None)
    home.patient_table_widget = owner
    home.data_access_panel_widget = SimpleNamespace(tab_selected_name="Server", server_selected="Synthetic server")
    home._search_generation = 1
    adapter = env["WorkflowRealtime"](home)
    adapter.bind("127.0.0.1", 1, "Synthetic server", 1)
    home.show(); qapp.processEvents(); adapter.tick()
    yield home, adapter
    adapter.close(); home.close(); home.deleteLater(); qapp.processEvents()


def state(pid="p0", count=2):
    return dict(study_uid="1.2.0", patient_id=pid, report_status="completed", audio_count=count,
                assignment={}, display_assignment={"status": "active", "assignee_name": "Synthetic"})


def test_delta_preserves_selection_rows_and_cell_objects(ui):
    home, adapter = ui
    table = home.patient_table_widget.results_table
    report = table.cellWidget(0, 5); assign = table.cellWidget(0, 6)
    selection = table.currentRow()
    adapter.receiver.mailbox.publish([state()]); adapter.tick()
    assert table.rowCount() == 2 and table.currentRow() == selection
    assert table.cellWidget(0, 5) is report and table.cellWidget(0, 6) is assign
    assert report.layout().itemAt(0).widget().text() == "completed"
    voice = table.cellWidget(0, 4).findChild(QLabel, "serverVoiceAvailability")
    assert voice and not voice.isHidden()
    adapter.receiver.mailbox.publish([state(count=0)]); adapter.tick()
    assert voice.isHidden()


def test_wrong_patient_is_never_applied(ui):
    home, adapter = ui
    adapter.receiver.mailbox.publish([state(pid="another-person")]); adapter.tick()
    assert home.patient_table_widget.results_table.cellWidget(0, 5).layout().itemAt(0).widget().text() == "original"


def test_shared_voice_observation_is_identity_bound_and_invalidated_by_source(ui):
    from PacsClient.utils.patient_workflow_facts import WORKFLOW_ROLE_OFFSET
    home,adapter=ui
    item=home.patient_table_widget.results_table.item(0,13)
    adapter.receiver.mailbox.publish([state(count=0)]); adapter.tick()
    snapshot=item.data(Qt.UserRole+WORKFLOW_ROLE_OFFSET)
    assert snapshot['audio_count']==0 and snapshot['patient_id']=='p0'
    assert snapshot['binding']==home.patient_table_widget.results_table._secretary_workflow_binding
    home.data_access_panel_widget.server_selected='Other server'
    adapter.tick()
    assert home.patient_table_widget.results_table._secretary_workflow_binding is None


@pytest.mark.parametrize("change", ["local", "server", "search", "logout"])
def test_stale_context_stops_receiver_without_applying(ui, change, monkeypatch):
    home, adapter = ui
    old = adapter.receiver
    old.mailbox.publish([state()])
    if change == "local": home.data_access_panel_widget.tab_selected_name = "Local"
    if change == "server": home.data_access_panel_widget.server_selected = "Other server"
    if change == "search": home._search_generation = 2
    if change == "logout": monkeypatch.setitem(adapter._active_key.__globals__, "get_socket_token_manager", lambda: SimpleNamespace(get_token=lambda: None))
    adapter.tick()
    assert not old.is_alive()
    assert home.patient_table_widget.results_table.cellWidget(0, 5).layout().itemAt(0).widget().text() == "original"
