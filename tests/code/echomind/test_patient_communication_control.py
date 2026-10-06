"""Patient communication uses synthetic identities and mocked transport only."""
import time
import threading
from types import SimpleNamespace
from modules.EchoMind.secretary.command_envelope import CommandPlan


def wait_status(adapter, key):
    deadline = time.monotonic()+2
    while time.monotonic()<deadline:
        result = adapter.patient_comment_status(CommandPlan(action='patient_comment_status',
            entities={'operation_id':key}), {})
        if result.data['state']!='running':
            return result.data
        time.sleep(.005)
    raise AssertionError('Worker timeout')


def test_comment_requires_confirmation_rechecks_study_and_returns_actual_receipt():
    from modules.EchoMind.secretary.adapters.patient_communication_adapter import PatientCommunicationAdapter
    calls = []
    store = SimpleNamespace(
        _save_local_comment_entry=lambda *args,**kwargs: calls.append(('cache',threading.get_ident())) or True,
        _sync_comment_to_server=lambda *args: calls.append(('send',threading.get_ident())) or {'success':True})
    tab = SimpleNamespace(study_uid='synthetic-study', patient_id='synthetic-admission',
        _get_shared_comment_store=lambda:store)
    adapter = PatientCommunicationAdapter(lambda:tab)
    prepared = adapter.prepare_patient_comment(CommandPlan(action='prepare_patient_comment',
        entities={'study_uid':tab.study_uid, 'comment':'Synthetic comment'}), {})
    plan = CommandPlan(action='sync_patient_comment', entities={'draft_id':prepared.data['draft_id']})
    assert adapter.sync_patient_comment(plan, {}).error_code=='CONFIRM_REQUIRED'
    assert not calls
    tab.study_uid='different-study'
    assert adapter.sync_patient_comment(plan, {'confirmed':True}).error_code=='PATIENT_CONTEXT_MISMATCH'
    tab.study_uid='synthetic-study'
    sent = adapter.sync_patient_comment(plan, {'confirmed':True})
    done = wait_status(adapter, sent.data['operation_id'])
    assert done['data']['delivered'] is True
    assert done['data']['report_status_changed'] is False
    assert all(thread!=threading.get_ident() for _,thread in calls)
    adapter.sync_patient_comment(plan, {'confirmed':True})
    assert len([kind for kind,_ in calls if kind=='send'])==1


def test_transport_failure_never_reports_delivery():
    from modules.EchoMind.secretary.adapters.patient_communication_adapter import PatientCommunicationAdapter
    store = SimpleNamespace(_save_local_comment_entry=lambda *a,**k:True,
                            _sync_comment_to_server=lambda *a:{'success':False, 'error':'private secret'})
    tab = SimpleNamespace(study_uid='synthetic', patient_id='synthetic', _get_shared_comment_store=lambda:store)
    adapter = PatientCommunicationAdapter(lambda:tab)
    prepared = adapter.prepare_patient_comment(CommandPlan(action='prepare_patient_comment',
        entities={'study_uid':'synthetic', 'comment':'Synthetic'}), {})
    sent = adapter.sync_patient_comment(CommandPlan(action='sync_patient_comment',
        entities={'draft_id':prepared.data['draft_id']}), {'confirmed':True})
    done = wait_status(adapter, sent.data['operation_id'])
    assert done['data']['delivered'] is False
    assert done['data']['delivery_state']=='unknown'
    assert 'private' not in str(done)


def test_new_actions_have_strict_schema_and_permissions():
    import pytest
    from modules.EchoMind.secretary.command_envelope import validate_action_entities
    from modules.EchoMind.secretary.permissions import ACTION_SIDE_EFFECTS, SERVER_WRITE
    assert ACTION_SIDE_EFFECTS['sync_patient_comment']==SERVER_WRITE
    assert ACTION_SIDE_EFFECTS['send_patient_voice']==SERVER_WRITE
    with pytest.raises(ValueError):
        validate_action_entities('send_patient_voice', {'recording_id':'synthetic', 'path':'C:/private'})
