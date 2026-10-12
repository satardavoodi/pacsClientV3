"""Actual Qt cells, synthetic identities, no application DB or network."""
import ast
from pathlib import Path
from types import SimpleNamespace, ModuleType, MethodType
import sys

import pytest
from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget, QTableWidget, QTableWidgetItem, QLabel, QHBoxLayout, QVBoxLayout, QPushButton

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
        def __init__(self, *args, **kwargs):
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
    QHBoxLayout(home)
    center = QWidget(home); QVBoxLayout(center)
    home.layout().addWidget(center)
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
    chips_source = Path('PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py').read_text(encoding='utf-8')
    chips_node = next(n for n in ast.walk(ast.parse(chips_source))
                      if isinstance(n, ast.FunctionDef) and n.name == '_populate_status_chips')
    chips_env = dict(QLabel=QLabel, Qt=Qt)
    exec(compile(ast.Module(body=[chips_node], type_ignores=[]), '<status-chips>', 'exec'), chips_env)
    owner._populate_status_chips = MethodType(chips_env['_populate_status_chips'], owner)
    owner._SHOW_LOCAL_DOCS_FOLDER_ICON = False
    owner._SHOW_PREVIOUS_HISTORY_FOLDER_ICON = False
    owner._contrast_safe_color = lambda *args: '#ef4444'
    home.patient_table_widget = owner
    owner.layout = center.layout
    owner.refresh_btn = QPushButton(center)
    center.layout().addWidget(owner.refresh_btn)
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
    voice = table.cellWidget(0, 4).findChild(QLabel, "patientVoiceAvailability")
    QApplication.processEvents()
    assert voice and not voice.isHidden()
    adapter.receiver.mailbox.publish([state(count=0)]); adapter.tick()
    assert table.cellWidget(0, 4).findChild(QLabel, 'patientVoiceAvailability') is None


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


def test_local_home_can_bind_the_verified_pacs_source(ui):
    home, adapter=ui
    home.data_access_panel_widget.tab_selected_name='Local'
    adapter.bind('127.0.0.1',1,'Synthetic server',1,mode='Local')
    adapter.tick()
    assert adapter.receiver is not None
    assert adapter.receiver.watched


def test_home_records_live_protocol_failure_without_a_status_panel(ui):
    home, adapter=ui
    adapter.receiver.status='unavailable'
    adapter.tick()
    assert home.property('workflowRealtimeStatus') == 'unavailable'
    assert home.findChild(QLabel, 'homeWorkflowRealtimeStatus') is None


def test_authoritative_report_author_replaces_the_cached_author(ui):
    home, adapter=ui
    from PySide6.QtCore import Qt
    item=home.patient_table_widget.results_table.item(0,1)
    item.setData(Qt.UserRole+2,'Old author')
    value=state(); value['reporting_physician']='New verified author'
    adapter.receiver.mailbox.publish([value]); adapter.tick()
    assert item.data(Qt.UserRole+2)=='New verified author'


def test_background_updates_add_no_home_column(ui):
    home, adapter = ui
    assert home.layout().count() == 1
    assert home.patient_table_widget.layout().count() <= 2
    assert not hasattr(adapter, 'status_label')


def test_initial_empty_home_explains_search_instead_of_token_failure(ui):
    home, adapter = ui
    adapter.binding = None
    home.patient_table_widget.results_table.setRowCount(0)
    adapter.tick()
    assert home.property('workflowRealtimeStatus') == 'waiting_for_search'
    assert home.findChild(QLabel, 'homeWorkflowRealtimeStatus') is None


@pytest.mark.parametrize('status,text', [('connected','Online'), ('compatibility','Periodic'),
    ('connected_legacy','Online'), ('compatibility_partial','Periodic'), ('compatibility_reconnecting','Connecting'),
    ('reconnecting','Connecting'), ('unavailable','Offline')])
def test_connection_badge_beside_refresh_reflects_transport(ui, status, text):
    home, adapter = ui
    adapter.receiver.status = status
    adapter.tick()
    badge = home.findChild(QLabel, 'homeWorkflowConnectionBadge')
    assert badge is not None and badge.text() == text
    layout = home.patient_table_widget.refresh_btn.parentWidget().layout()
    assert layout.indexOf(badge) == layout.indexOf(home.patient_table_widget.refresh_btn) + 1


def test_local_and_server_voice_share_one_chip_through_async_local_refresh(ui):
    home, adapter = ui
    owner = home.patient_table_widget
    container = owner.results_table.cellWidget(0, 4)
    container.status_flags = {'voice':True, 'dicom':True}
    owner._populate_status_chips(container.layout(), container.status_flags)
    adapter.receiver.mailbox.publish([state(count=2)]); adapter.tick()
    owner._populate_status_chips(container.layout(), container.status_flags)
    chips=container.findChildren(QLabel, 'patientVoiceAvailability')
    assert len(chips)==1 and 'Local and server' in chips[0].toolTip()
    assert container.layout().count()==2
    adapter.receiver.mailbox.publish([state(count=0)]); adapter.tick()
    chips=container.findChildren(QLabel, 'patientVoiceAvailability')
    assert len(chips)==1 and chips[0].toolTip()=='Local voice files'


def test_unknown_assignment_does_not_repaint_assign_or_color_report_as_assigned(ui):
    home, adapter=ui
    row=state(); row.update(assignment_enabled=False, display_assignment={})
    assign=home.patient_table_widget.results_table.cellWidget(0,6)
    adapter.receiver.mailbox.publish([row]); adapter.tick()
    assert assign.text()=='unassigned' and not hasattr(assign, '_workflow_snapshot')


def test_report_enrichment_does_not_replay_an_older_voice_observation(ui):
    home, adapter=ui
    table=home.patient_table_widget.results_table
    adapter.receiver.mailbox.publish([state(count=2)]); adapter.tick()
    patch=state(count=0); patch['_report_only']=True
    patch['reporting_physician']='Verified reporter'
    adapter._apply(0,patch)
    assert table.cellWidget(0,4).property('serverVoiceCount')==2
    assert table.item(0,1).data(Qt.UserRole+2)=='Verified reporter'


def test_fast_inventory_never_reverts_verified_report_or_assignment(ui):
    home, adapter = ui
    verified = state()
    verified['reporting_physician'] = 'Verified reporter'
    adapter._apply(0, verified)
    table = home.patient_table_widget.results_table
    label = table.cellWidget(0, 5).layout().itemAt(0).widget()
    signature = label._workflow_snapshot
    assign_signature = table.cellWidget(0, 6)._workflow_snapshot
    fast = state(count=3)
    fast.update(_voice_only=True, report_status='pending', reporting_physician='',
                assignment_enabled=False, display_assignment={})
    adapter._apply(0, fast)
    assert label._workflow_snapshot == signature
    assert table.item(0, 1).data(Qt.UserRole+2) == 'Verified reporter'
    assert table.cellWidget(0, 6)._workflow_snapshot == assign_signature
    assert table.cellWidget(0, 4).property('serverVoiceCount') == 3


def test_report_column_never_substitutes_an_assignee_for_the_reporter(ui):
    home, _ = ui
    owner = home.patient_table_widget
    source = Path('PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py').read_text(encoding='utf-8')
    method = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == '_apply_report_status_display')
    env = dict(QLabel=QLabel, Qt=Qt, REPORT_STATUSES={'pending':'Pending'},
               STATUS_COLORS={'pending':'#f59e0b'})
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<report-display>', 'exec'), env)
    label = QLabel(); label.reception_id = 'synthetic'
    env['_apply_report_status_display'](owner, label, 'pending', 'Verified reporter',
        workflow_assignment={'status':'active', 'assignee_name':'Different assignee'})
    assert label.text() == 'Verified reporter'
    assert 'Different assignee' not in label.toolTip()


def test_unknown_report_fields_preserve_confirmed_values_during_network_failure(ui):
    home, adapter = ui
    verified = state(); verified['reporting_physician'] = 'Verified reporter'
    adapter._apply(0, verified)
    unknown = state(count=0)
    unknown.update(_report_only=True, _report_status_known=False,
                   _reporting_physician_known=False, report_status='pending',
                   reporting_physician='', assignment_enabled=False)
    adapter._apply(0, unknown)
    table = home.patient_table_widget.results_table
    assert table.cellWidget(0, 5).report_status == 'completed'
    assert table.item(0, 1).data(Qt.UserRole+2) == 'Verified reporter'
    assert table.cellWidget(0, 4).property('serverVoiceCount') == 2


def test_late_older_enrichment_cannot_repaint_after_newer_inventory(ui):
    home, adapter = ui
    confirmed = state(); confirmed.update(_observation=1, reporting_physician='Confirmed reporter')
    adapter._apply(0, confirmed)
    fast = state(count=3); fast.update(_observation=3, _voice_only=True)
    adapter._apply(0, fast)
    stale = state(); stale.update(_observation=2, _report_only=True,
        reporting_physician='Stale reporter', report_status='pending')
    adapter._apply(0, stale)
    table = home.patient_table_widget.results_table
    assert table.item(0, 1).data(Qt.UserRole+2) == 'Confirmed reporter'
    assert table.cellWidget(0, 5).report_status == 'completed'
    assert table.cellWidget(0, 4).property('serverVoiceCount') == 3


def test_unknown_assignment_retains_verified_assignee_when_report_completes(ui):
    home, adapter = ui
    assigned = state(); assigned['report_status'] = 'pending'
    adapter._apply(0, assigned)
    update = state(); update.update(assignment_enabled=False, display_assignment={})
    adapter._apply(0, update)
    widget = home.patient_table_widget.results_table.cellWidget(0, 6)
    assert widget._workflow_snapshot == ('completed', 'Synthetic')


def test_session_renewal_accepts_new_receiver_observation_sequence(ui, monkeypatch):
    home, adapter = ui
    previous = state(); previous.update(_observation=50, reporting_physician='Previous reporter')
    adapter._apply(0, previous)
    monkeypatch.setitem(adapter._active_key.__globals__, 'get_socket_token_manager',
        lambda:SimpleNamespace(get_token=lambda:'renewed-synthetic-session'))
    adapter.tick()
    current = state(count=3); current.update(_observation=1, reporting_physician='Current reporter')
    adapter._apply(0, current)
    assert home.patient_table_widget.results_table.item(0, 1).data(Qt.UserRole+2) == 'Current reporter'
    assert home.patient_table_widget.results_table.cellWidget(0, 4).property('serverVoiceCount') == 3
