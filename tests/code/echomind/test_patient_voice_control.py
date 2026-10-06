"""Synthetic voice handles; no microphones, patients or live PACS connections."""
import time
from types import SimpleNamespace
from modules.EchoMind.secretary.command_envelope import CommandPlan


class Signal:
    def __init__(self):
        self.slots=[]
    def connect(self, slot):
        self.slots.append(slot)
    def emit(self, data):
        for slot in self.slots:
            slot(data)


class Box:
    _save_in_progress=False
    _file_path=None
    active=False
    paused=False
    def __init__(self):
        self._wav_write_finished=Signal()
    def is_recording(self):
        return self.active
    def is_paused(self):
        return self.paused
    def toggle_pause_inline(self):
        self.paused=not self.paused
    def start_recording_inline(self, selected_widget, prepared_path=None):
        self._file_path=prepared_path
        self.active=True
        return True
    def stop_and_save_inline(self):
        self.active=False
        self._save_in_progress=True


def test_voice_saved_requires_receipt_and_tab_switch_blocks_control(monkeypatch, tmp_path):
    from PacsClient.utils import config
    from modules.EchoMind.secretary.adapters.patient_voice_adapter import PatientVoiceAdapter
    monkeypatch.setattr(config, 'ATTACHMENT_PATH', tmp_path)
    box=Box()
    toolbar=SimpleNamespace(get_soundbox=lambda:box,
        _set_mic_recording_ui=lambda _:None, _update_mic_record_ui=lambda:None)
    tab=SimpleNamespace(study_uid='1.2.3', toolbar_manager=toolbar, selected_widget=None)
    adapter=PatientVoiceAdapter(lambda:tab)
    result=adapter.prepare_patient_voice(CommandPlan(action='prepare_patient_voice',
        entities={'study_uid':'1.2.3'}), {})
    plan=CommandPlan(action='patient_voice_status', entities={'recording_id':result.data['recording_id']})
    deadline=time.monotonic()+2
    while adapter.patient_voice_status(plan, {}).data['preparation']=='running' and time.monotonic()<deadline:
        time.sleep(.005)
    assert adapter.start_patient_voice(plan, {}).data['state']=='recording'
    assert adapter.pause_patient_voice(plan, {}).data['state']=='paused'
    assert adapter.resume_patient_voice(plan, {}).data['state']=='recording'
    assert adapter.stop_patient_voice(plan, {}).data['state']=='saving'
    assert adapter.send_patient_voice(plan, {'confirmed':True}).error_code=='VOICE_NOT_SAVED'
    box._save_in_progress=False
    box._wav_write_finished.emit({'path':box._file_path, 'ok':True})
    assert adapter.patient_voice_status(plan, {}).data['state']=='saved'
    assert adapter.send_patient_voice(plan, {}).error_code=='CONFIRM_REQUIRED'
    tab.study_uid='1.2.4'
    assert adapter.send_patient_voice(plan, {'confirmed':True}).error_code=='PATIENT_CONTEXT_MISMATCH'


def test_upload_selects_only_requested_take(tmp_path, monkeypatch):
    import modules.network.upload_download_attchments as upload
    from modules.network import attachment_pending_sync as pending
    from PacsClient.utils import config
    root=tmp_path/'1.2.3'
    root.mkdir()
    selected=root/'take.wav'
    other=root/'other.wav'
    selected.write_bytes(b'synthetic')
    other.write_bytes(b'private')
    monkeypatch.setattr(config, 'ATTACHMENT_PATH', tmp_path)
    monkeypatch.setattr(upload, 'ATTACHMENT_PATH', tmp_path)
    monkeypatch.setattr(upload, 'list_files_in_folder', lambda _:[str(selected), str(other)])
    monkeypatch.setattr(upload, 'append_attachments_uploaded', lambda **_:None)
    calls=[]
    class Client:
        def supports_idempotent_upload(self):
            return False
        def send_request(self, endpoint, params):
            calls.append(params)
            return {'status':'success'}
    result=upload.upload_attachments_for_study('1.2.3', '', selected_files=[str(selected)],
        client=Client(), verbose=False)
    assert result['success']==1
    assert len(calls)==1
    import pytest
    with pytest.raises(ValueError):
        upload.upload_attachments_for_study('1.2.3', '', selected_files=[str(tmp_path/'outside.wav')],
            client=Client(), verbose=False)
