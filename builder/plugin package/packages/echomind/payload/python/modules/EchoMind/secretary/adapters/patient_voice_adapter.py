"""Explicit, study-bound recording and one-take PACS attachment upload."""
from collections import OrderedDict
from pathlib import Path
import re
from uuid import uuid4
from PacsClient.utils.support_diagnostics import OperationStore
from ..command_envelope import CommandResult

VOICE_ACTIONS = {name:name for name in ('prepare_patient_voice', 'start_patient_voice',
    'pause_patient_voice', 'resume_patient_voice', 'stop_patient_voice',
    'patient_voice_status', 'send_patient_voice')}


class PatientVoiceAdapter:
    def __init__(self, getter):
        self._getter = getter
        self._takes = OrderedDict()
        self._operations = OperationStore()

    def _error(self, plan, code):
        return CommandResult(ok=False, action=plan.action, error_code=code)

    def _take(self, plan):
        take = self._takes.get(plan.entities.get('recording_id'))
        tab = self._getter()
        if not take or tab is not take['tab'] or str(getattr(tab, 'study_uid', ''))!=take['uid']:
            return None
        return take

    def prepare_patient_voice(self, plan, state):
        tab = self._getter()
        uid = str(getattr(tab, 'study_uid', '') or '')
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', uid) or len(uid)>64 or uid!=plan.entities.get('study_uid'):
            return self._error(plan, 'PATIENT_CONTEXT_MISMATCH')
        if len(self._takes)>=32:
            return self._error(plan, 'RECORDING_CAPACITY_REACHED')
        soundbox = tab.toolbar_manager.get_soundbox()
        if soundbox.is_recording() or soundbox._save_in_progress:
            return self._error(plan, 'MICROPHONE_BUSY')
        from PacsClient.utils.config import ATTACHMENT_PATH
        key = str(uuid4())
        path = Path(ATTACHMENT_PATH)/uid/('REC_'+key+'.wav')
        take = {'tab':tab, 'uid':uid, 'soundbox':soundbox, 'path':path,
                'state':'preparing', 'upload_id':None, 'write_ok':None}
        def saved(result):
            if isinstance(result, dict) and result.get('path')==path:
                take['write_ok'] = result.get('ok') is True
        soundbox._wav_write_finished.connect(saved)
        def prepare():
            path.parent.mkdir(parents=True, exist_ok=True)
            return {'ready':True}
        take['prepare_id'] = self._operations.start('voice_prepare', prepare)['operation_id']
        self._takes[key] = take
        return CommandResult(ok=True, action=plan.action,
            data={'recording_id':key, 'state':'preparing'}, message='Recording preparation started.')

    def start_patient_voice(self, plan, state):
        take = self._take(plan)
        if not take:
            return self._error(plan, 'PATIENT_CONTEXT_MISMATCH')
        ready = self._operations.status(take['prepare_id'])['state']
        if ready!='succeeded' or take['state']!='preparing':
            return self._error(plan, 'RECORDING_NOT_READY')
        box = take['soundbox']
        if box.is_recording() or box._save_in_progress:
            return self._error(plan, 'MICROPHONE_BUSY')
        try:
            started = box.start_recording_inline(take['tab'].selected_widget, prepared_path=take['path'])
        except Exception:
            box.cancel_recording_inline()
            take['state'] = 'failed'
            return self._error(plan, 'MICROPHONE_START_FAILED')
        if not started:
            return self._error(plan, 'MICROPHONE_START_FAILED')
        take['tab'].toolbar_manager._set_mic_recording_ui(True)
        take['state'] = 'recording'
        return self.patient_voice_status(plan, state)

    def pause_patient_voice(self, plan, state):
        return self._pause(plan, True)

    def resume_patient_voice(self, plan, state):
        return self._pause(plan, False)

    def _pause(self, plan, paused):
        take = self._take(plan)
        if not take or take['state'] not in ('recording', 'paused'):
            return self._error(plan, 'RECORDING_NOT_ACTIVE')
        box = take['soundbox']
        if not box.is_recording():
            return self._error(plan, 'RECORDING_NOT_ACTIVE')
        if box.is_paused()!=paused:
            box.toggle_pause_inline()
        take['state'] = 'paused' if paused else 'recording'
        take['tab'].toolbar_manager._update_mic_record_ui()
        return self.patient_voice_status(plan, {})

    def stop_patient_voice(self, plan, state):
        take = self._take(plan)
        if not take or take['state'] not in ('recording', 'paused'):
            return self._error(plan, 'RECORDING_NOT_ACTIVE')
        take['soundbox'].stop_and_save_inline()
        take['tab'].toolbar_manager._set_mic_recording_ui(False)
        take['state'] = 'saving'
        return self.patient_voice_status(plan, state)

    def patient_voice_status(self, plan, state):
        take = self._take(plan)
        if not take:
            return self._error(plan, 'PATIENT_CONTEXT_MISMATCH')
        if take['state']=='saving' and not take['soundbox']._save_in_progress:
            take['state'] = 'saved' if take['write_ok'] is True else 'failed'
        data = {'state':take['state'], 'recording_id':plan.entities['recording_id']}
        if take['state']=='preparing':
            data['preparation'] = self._operations.status(take['prepare_id'])['state']
        if take['upload_id']:
            data['upload'] = self._operations.status(take['upload_id'])
        return CommandResult(ok=True, action=plan.action, data=data)

    def send_patient_voice(self, plan, state):
        take = self._take(plan)
        if not take:
            return self._error(plan, 'PATIENT_CONTEXT_MISMATCH')
        if state.get('confirmed') is not True:
            return self._error(plan, 'CONFIRM_REQUIRED')
        self.patient_voice_status(plan, state)
        if take['state']!='saved':
            return self._error(plan, 'VOICE_NOT_SAVED')
        if not take['upload_id']:
            uid, path = take['uid'], take['path']
            def upload():
                if path.is_symlink() or not path.is_file() or path.stat().st_size<=44:
                    return {'uploaded':False, 'error_code':'VOICE_FILE_INVALID'}
                from modules.network.upload_download_attchments import upload_attachments_for_study
                result = upload_attachments_for_study(uid, '', selected_files=[str(path)],
                    attachment_type='audio', verbose=False, stop_on_error=True)
                success = result.get('success')==1 and result.get('failed')==0
                return {'uploaded':success, 'destination':'study_pacs_attachment',
                        'reception_delivery_confirmed':False,
                        'error_code':None if success else 'VOICE_UPLOAD_UNCONFIRMED'}
            take['upload_id'] = self._operations.start('voice_upload', upload)['operation_id']
        return self.patient_voice_status(plan, state)
