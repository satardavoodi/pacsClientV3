"""Actual Qt Patient buttons with synthetic worker delivery; no network/DB."""
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QWidget, QPushButton
from PySide6.QtCore import QCoreApplication, QEvent

from modules.ai_imaging.eagle_eye_remote.case_ui import PatientCaseController, availability_style


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


class Receiver:
    def __init__(self, reference):
        self.reference = reference
        self.connection = object()
        self.value = None
        self.alive = False
    def start(self): self.alive = True
    def stop(self): self.alive = False
    def is_alive(self): return self.alive
    def drain(self):
        value, self.value = self.value, None
        return value


def patient(qapp):
    widget = QWidget()
    widget.study_uid, widget.patient_id = '1.2.3', 'synthetic'
    widget.btn_ai_chat, widget.btn_ai_module = QPushButton(widget), QPushButton(widget)
    widget._safe_set_sidebar_button_style = lambda b, selected: b.setStyleSheet(
        availability_style('QPushButton { color: blue; }', bool(b.property('savedResultAvailable')), selected))
    control = PatientCaseController(widget, receiver_factory=Receiver, local_finder=lambda reference: [])
    control.timer.stop()
    control.tick()
    return widget, control


def test_saved_results_are_red_even_when_selected(qapp):
    widget, control = patient(qapp)
    widget.btn_ai_chat.setCheckable(True)
    widget.btn_ai_chat.setChecked(True)
    control.receiver.value = dict(case=control.reference, status='connected', workflow={},
        echomind=[{'request_id': 'synthetic'}], eagle_eye=[])
    control.tick()
    assert widget.btn_ai_chat.property('savedResultAvailable') is True
    assert '#54232b' in widget.btn_ai_chat.styleSheet()
    assert '#79bde8' in widget.btn_ai_chat.styleSheet()
    assert widget.btn_ai_module.property('savedResultAvailable') is False
    widget.deleteLater()


def test_delayed_other_patient_and_disconnect_cannot_leave_red(qapp):
    widget, control = patient(qapp)
    control.receiver.value = dict(case={'study_uid': '1.2.4', 'patient_id': 'other'},
        status='connected', workflow={}, echomind=[{}], eagle_eye=[{}])
    control.tick()
    assert not widget.btn_ai_chat.property('savedResultAvailable')
    control.receiver.value = dict(case=control.reference, status='connected',
        workflow={}, echomind=[{}], eagle_eye=[{}])
    control.tick()
    control.receiver.value = dict(case=control.reference, status='disconnected')
    control.tick()
    assert not widget.btn_ai_chat.property('savedResultAvailable')
    assert 'unknown' in widget.btn_ai_chat.toolTip()
    widget.deleteLater()


def test_case_switch_stops_old_receiver_and_clears_availability(qapp):
    widget, control = patient(qapp)
    old = control.receiver
    widget.study_uid = '1.2.4'
    control.tick()
    assert not old.is_alive()
    assert control.reference['study_uid'] == '1.2.4'
    assert not widget.btn_ai_module.property('savedResultAvailable')
    widget.deleteLater()


def test_selected_study_is_bound_in_a_multiple_study_patient_tab(qapp):
    widget, control = patient(qapp)
    widget.selected_widget = SimpleNamespace(vtk_widget=SimpleNamespace(
        image_viewer=SimpleNamespace(metadata={'series': {'study_uid': '1.2.9'}}, metadata_fixed={})))
    control.tick()
    assert control.reference == {'study_uid': '1.2.9', 'patient_id': 'synthetic'}
    assert not widget.btn_ai_chat.property('savedResultAvailable')
    widget.deleteLater()


def test_readable_saved_response_hides_transport_details():
    from modules.ai_imaging.eagle_eye_remote.case_ui import saved_content
    text = saved_content({'summary': 'Synthetic findings', 'server_job_id': 'private-handle',
        'artifact_directory': 'private-path', 'measurements': {'angle': 10}})
    assert 'Synthetic findings' in text and 'Angle' in text
    assert 'private-handle' not in text and 'private-path' not in text


def test_other_selected_study_does_not_overwrite_primary_report_status(qapp):
    widget, control = patient(qapp)
    widget.report_status = 'pending'
    widget.selected_widget = SimpleNamespace(vtk_widget=SimpleNamespace(
        image_viewer=SimpleNamespace(metadata={'series': {'study_uid': '1.2.9'}}, metadata_fixed={})))
    control.tick()
    control.receiver.value = dict(case=control.reference, status='connected',
        workflow=dict(control.reference, report_status='completed', audio_count=4),
        echomind=[{}], eagle_eye=[])
    control.tick()
    assert widget.report_status == 'pending'
    assert widget.property('serverVoiceCount') is None
    assert widget.btn_ai_chat.property('savedResultAvailable')
    widget.deleteLater()


def test_parent_destruction_stops_the_worker_without_a_gui_join(qapp):
    widget, control = patient(qapp)
    receiver = control.receiver
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not receiver.is_alive()


def test_local_brain_result_marks_sidebar_without_server_inventory(qapp):
    from concurrent.futures import Future
    widget, control = patient(qapp)
    control.local_future = Future()
    control.local_binding = dict(control.reference)
    control.local_future.set_result([{'path':'synthetic-result'}])
    control.tick()
    assert widget.btn_ai_module.property('savedResultAvailable') is True
    assert '#54232b' in widget.btn_ai_module.styleSheet()
    control.clear('Server availability is unknown.')
    assert widget.btn_ai_module.property('savedResultAvailable') is True
    widget.study_uid='different-study'
    control.tick()
    assert not widget.btn_ai_module.property('savedResultAvailable')
    widget.deleteLater()


def test_late_local_brain_result_cannot_mark_another_study(qapp):
    from concurrent.futures import Future
    widget, control = patient(qapp)
    control.local_future=Future(); control.local_binding=dict(control.reference)
    widget.study_uid='other-study'
    control.local_future.set_result([{'path':'old-result'}])
    control.tick()
    assert not widget.btn_ai_module.property('savedResultAvailable')
    widget.deleteLater()


def test_local_badge_opens_saved_brain_tab_without_analysis(qapp, monkeypatch):
    from modules.ai_imaging import eagle_eye_workspace
    widget, control=patient(qapp)
    control.local_count=1
    events=[]
    workspace=SimpleNamespace(ensure_saved_brain_results=lambda:events.append('ensure'),
        saved_brain_results='saved-tab',tab_widget=SimpleNamespace(setCurrentWidget=lambda page:events.append(page)))
    monkeypatch.setattr(eagle_eye_workspace,'open_eagle_eye_workspace',lambda p:workspace)
    assert control.open('eagle_eye')
    assert events==['ensure','saved-tab']
    widget.deleteLater()


def test_local_alignment_report_is_in_sidebar_inventory(tmp_path, monkeypatch):
    import hashlib, json
    from PacsClient.utils import data_paths
    from modules.ai_imaging.eagle_eye_remote.case_ui import local_brain_results
    monkeypatch.setattr(data_paths, 'AI_DIR', tmp_path)
    uid = '1.2.840.999'
    folder = tmp_path / 'eagle_eye' / 'alignment' / 'studies' / hashlib.sha256(uid.encode()).hexdigest() / 'synthetic'
    folder.mkdir(parents=True)
    pdf = b'%PDF synthetic alignment'
    (folder / 'report.pdf').write_bytes(pdf)
    (folder / 'report.json').write_text(json.dumps(dict(format_version=4,
        identity=dict(study_uid=uid, sop_uid='1.2.3.4'), measurements={'R': {'hka_deg': 2}},
        pdf_sha256=hashlib.sha256(pdf).hexdigest())))
    rows = local_brain_results(dict(study_uid=uid, patient_id='synthetic'))
    assert any(row['kind'] == 'alignment' for row in rows)
    assert not local_brain_results(dict(study_uid='1.2.840.998', patient_id='synthetic'))
    (folder / 'report.pdf').write_bytes(b'changed')
    assert not local_brain_results(dict(study_uid=uid, patient_id='synthetic'))


def test_local_alignment_badge_opens_existing_report_without_inference(qapp, tmp_path, monkeypatch):
    import hashlib, json
    from concurrent.futures import Future
    from PacsClient.utils import data_paths
    monkeypatch.setattr(data_paths, 'AI_DIR', tmp_path)
    folder = tmp_path / 'eagle_eye' / 'alignment' / 'studies' / 'synthetic' / 'report'
    folder.mkdir(parents=True)
    pdf = b'%PDF synthetic'
    (folder / 'report.pdf').write_bytes(pdf)
    path = folder / 'report.json'
    path.write_text(json.dumps(dict(format_version=4, identity={'study_uid':'1.2.3'},
        measurements={'R':{'hka_deg':2}}, pdf_sha256=hashlib.sha256(pdf).hexdigest())))
    widget, control = patient(qapp)
    control.local_future = Future(); control.local_binding = dict(control.reference)
    control.local_future.set_result([dict(kind='alignment', path=str(path))])
    control.tick()
    assert widget.btn_ai_module.property('savedResultAvailable')
    assert '#54232b' in widget.btn_ai_module.styleSheet()
    assert control.open('eagle_eye')
    received = []
    monkeypatch.setattr(control, 'show_result', lambda kind, value: received.append(value))
    control.dialog.open_button.click()
    control.future.result(timeout=3)
    control.tick()
    assert received[0]['saved_files'] == [str(folder / 'report.pdf')]
    control.receiver.value = dict(case=control.reference, status='connected', eagle_eye=[], echomind=[])
    control.tick()
    control.clear('Server unavailable')
    assert control.dialog.open_button.isEnabled()
    control.dialog.close()
    widget.deleteLater()


@pytest.mark.parametrize('module', ['bone-age', 'total-spine', 'alignment', 'brain', 'brain-lesions', 'breast'])
def test_all_remote_ai_modules_enter_local_inventory(tmp_path, monkeypatch, module):
    import json
    from PacsClient.utils import data_paths
    from modules.ai_imaging.eagle_eye_remote.case_ui import local_brain_results
    monkeypatch.setattr(data_paths, 'AI_DIR', tmp_path)
    folder = tmp_path / 'eagle_eye' / 'remote-synthetic'
    folder.mkdir(parents=True)
    (folder / 'report.pdf').write_bytes(b'%PDF synthetic')
    (folder / 'result.json').write_text(json.dumps(dict(server_module=module,
        analysis_study_uid='1.2.3', artifact_directory=str(folder), summary='Synthetic',
        pdf_available=True)))
    rows = local_brain_results(dict(study_uid='1.2.3', patient_id='synthetic'))
    assert any(row['kind'] == module for row in rows)
    assert not local_brain_results(dict(study_uid='1.2.4', patient_id='synthetic'))


@pytest.fixture(autouse=True)
def isolated_echo_history(tmp_path, monkeypatch):
    from PacsClient.utils import data_paths
    monkeypatch.setattr(data_paths, 'ECHOMIND_DIR', tmp_path / 'echo')
    monkeypatch.setattr(data_paths, 'ATTACHMENTS_DIR', tmp_path / 'attachments')


def test_echo_report_history_marks_red_and_reopens_without_server(qapp, tmp_path):
    import uuid
    from concurrent.futures import Future
    from modules.ai_imaging.eagle_eye_remote.local_results import echo_results, load_echo
    from modules.ai_imaging.eagle_eye_remote.text_history import History
    history = History(tmp_path / 'echo' / 'remote_history')
    rid = str(uuid.uuid4())
    history.begin(rid, 'local', {'study_uid':'1.2.3'}, {'workflow':'report'})
    history.finish(rid, 'local', {'content':'Synthetic original report'})
    widget, control = patient(qapp)
    rows = echo_results(control.reference)
    assert load_echo(control.reference, rows[0])['content'] == 'Synthetic original report'
    assert not echo_results(dict(study_uid='1.2.4',patient_id='synthetic'))
    control.local_future=Future(); control.local_binding=dict(control.reference)
    control.local_future.set_result(rows); control.tick()
    assert widget.btn_ai_chat.property('savedResultAvailable')
    assert not widget.btn_ai_module.property('savedResultAvailable')
    control.clear('Server unavailable')
    assert widget.btn_ai_chat.property('savedResultAvailable')
    assert control.open('echomind')
    control.dialog.close(); widget.deleteLater()


def test_image_and_doctor_changes_update_patient_and_request_background_catalog(qapp):
    widget, control=patient(qapp)
    calls=[]
    widget._load_server_thumbnails=lambda:calls.append('refresh')
    def publish(count, name):
        control.receiver.value=dict(case=control.reference,status='connected',echomind=[],eagle_eye=[],
            workflow=dict(control.reference,report_status='completed',audio_count=0,image_count=count,
                series_count=2, assignment={'radiologist':{'id':'doctor','name':name,'source':'pacs'}}))
        control.tick()
    publish(10,'First physician')
    assert not calls
    publish(11,'Second physician'); control.tick()
    assert calls == ['refresh']
    assert widget.property('serverImageCount') == 11
    assert widget.property('serverReportingDoctor')['name'] == 'Second physician'
    control.clear('Disconnected')
    assert widget.property('serverReportingDoctor') is None
    widget.deleteLater()


def test_server_history_picker_also_lists_retained_local_modules(qapp):
    widget, control=patient(qapp)
    from concurrent.futures import Future
    control.local_future=Future(); control.local_binding=dict(control.reference)
    control.local_future.set_result([dict(kind='bone-age',storage='remote-result',path='synthetic')])
    control.receiver.value=dict(case=control.reference,status='connected',echomind=[],
        eagle_eye=[dict(job_id='a'*32,module='breast',created_at=1)])
    control.tick()
    assert control.open('eagle_eye')
    assert control.dialog.results.count() == 2
    assert control.dialog.results.item(1).data(256)['local'] is True
    control.dialog.close(); widget.deleteLater()


@pytest.mark.parametrize('module', ['bone-age', 'breast'])
def test_legacy_engine_receipts_are_exact_study_results(tmp_path, module):
    import json
    from modules.ai_imaging.eagle_eye_remote.local_results import discover_results, load_result
    folder=tmp_path / 'owned-job'; folder.mkdir()
    value=dict(status='success', study_id='1.2.3', job_directory=str(folder))
    value.update({'predicted_bone_age_months':100} if module=='bone-age' else
                 {'csv':str(folder/'measurements.csv'),'auxiliary_head_available':False})
    (folder/'result.json').write_text(json.dumps(value))
    (folder/'measurements.csv').write_text('synthetic')
    rows=discover_results(tmp_path,'1.2.3')
    assert rows[0]['kind']==module
    assert load_result(tmp_path,'1.2.3',rows[0])['server_module']==module
    assert not discover_results(tmp_path,'1.2.4')


def test_total_spine_local_report_is_verified_and_reopened(tmp_path):
    import hashlib, json
    from modules.ai_imaging.eagle_eye_remote.local_results import discover_results, load_result
    folder=tmp_path/'total-spine'/'studies'/hashlib.sha256(b'1.2.3').hexdigest()/'revision'
    folder.mkdir(parents=True)
    pdf=b'%PDF synthetic spine'; (folder/'report.pdf').write_bytes(pdf)
    (folder/'report.json').write_text(json.dumps(dict(format_version=1,study_uid='1.2.3',
        views=[dict(measurements={'cobb':4})],pdf_sha256=hashlib.sha256(pdf).hexdigest())))
    rows=discover_results(tmp_path,'1.2.3')
    assert rows[0]['kind']=='total-spine'
    assert load_result(tmp_path,'1.2.3',rows[0])['saved_files']==[str(folder/'report.pdf')]
    (folder/'report.pdf').write_bytes(b'changed')
    assert not discover_results(tmp_path,'1.2.3')
