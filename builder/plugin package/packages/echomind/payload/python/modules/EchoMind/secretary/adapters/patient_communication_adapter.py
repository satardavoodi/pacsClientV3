"""Patient-bound Comment Sync; private Note and report status remain separate."""
from collections import OrderedDict
from uuid import uuid4
from PacsClient.utils.support_diagnostics import OperationStore
from ..command_envelope import CommandResult

COMMUNICATION_ACTIONS = {name:name for name in ('prepare_patient_comment',
    'sync_patient_comment', 'patient_comment_status')}


class PatientCommunicationAdapter:
    def __init__(self, get_active_patient_tab):
        self._get_tab = get_active_patient_tab
        self._drafts = OrderedDict()
        self._operations = OperationStore()
        self._active_operation = None

    def _error(self, plan, code):
        return CommandResult(ok=False, action=plan.action, error_code=code)

    def _identity(self):
        tab = self._get_tab()
        uid = str(getattr(tab, 'study_uid', '') or '')
        pid = str(getattr(tab, 'patient_id', '') or '')
        return tab, uid, pid

    def prepare_patient_comment(self, plan, state):
        tab, uid, pid = self._identity()
        text = str(plan.entities.get('comment', '')).strip()
        if not tab or not uid or not pid or uid != plan.entities.get('study_uid'):
            return self._error(plan, 'PATIENT_CONTEXT_MISMATCH')
        if not text or len(text)>4000:
            return self._error(plan, 'INVALID_COMMENT')
        store = tab._get_shared_comment_store()
        if store is None:
            return self._error(plan, 'COMMENT_SYNC_UNAVAILABLE')
        if len(self._drafts)>=32:
            self._drafts.popitem(last=False)
        key = str(uuid4())
        self._drafts[key] = {'tab':tab, 'uid':uid, 'pid':pid,
                            'text':text, 'store':store, 'operation_id':None}
        return CommandResult(ok=True, action=plan.action,
            data={'draft_id':key, 'state':'awaiting_confirmation',
                  'report_status_changed':False, 'local_note_changed':False},
            message='Comment prepared for the active study. Confirm before sending.')

    def sync_patient_comment(self, plan, state):
        draft = self._drafts.get(plan.entities.get('draft_id'))
        if not draft:
            return self._error(plan, 'UNKNOWN_DRAFT')
        tab, uid, pid = self._identity()
        if tab is not draft['tab'] or (uid,pid)!=(draft['uid'],draft['pid']):
            return self._error(plan, 'PATIENT_CONTEXT_MISMATCH')
        if state.get('confirmed') is not True:
            return self._error(plan, 'CONFIRM_REQUIRED')
        if draft['operation_id']:
            return CommandResult(ok=True, action=plan.action,
                data=self._operations.status(draft['operation_id']))
        if self._active_operation and self._operations.status(self._active_operation)['state']=='running':
            return self._error(plan, 'COMMENT_SYNC_BUSY')
        store, text = draft['store'], draft['text']
        def send():
            if not store._save_local_comment_entry(pid, uid, text, sync_state='local_only'):
                return {'delivery_state':'failed', 'delivered':False, 'error_code':'COMMENT_CACHE_FAILED'}
            response = store._sync_comment_to_server(pid, text)
            delivered = response.get('success') is True
            cache_saved = store._save_local_comment_entry(pid, uid, text,
                sync_state='synced' if delivered else 'sync_failed',
                sync_error='' if delivered else 'COMMENT_SYNC_UNCONFIRMED')
            return {'delivery_state':'delivered' if delivered else 'unknown',
                    'delivered':delivered, 'cache_updated':bool(cache_saved),
                    'report_status_changed':False, 'local_note_changed':False,
                    'error_code':None if delivered else 'COMMENT_SYNC_UNCONFIRMED'}
        result = self._operations.start('comment_sync', send)
        draft['operation_id'] = result['operation_id']
        self._active_operation = result['operation_id']
        return CommandResult(ok=True, action=plan.action, data=result,
                             message='Comment synchronization started. Check its final result.')

    def patient_comment_status(self, plan, state):
        try:
            result = self._operations.status(plan.entities.get('operation_id', ''))
        except ValueError:
            return self._error(plan, 'UNKNOWN_OPERATION')
        return CommandResult(ok=True, action=plan.action, data=result)
