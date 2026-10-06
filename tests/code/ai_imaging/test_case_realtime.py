"""Synthetic case sharing and broadcast guards; no live databases or PACS."""
import threading
import time
import uuid
from types import SimpleNamespace

import pytest

from modules.ai_imaging.eagle_eye_remote.case_realtime import CaseService, Events
from modules.ai_imaging.eagle_eye_remote.text_history import History


class Source:
    config = {'url': 'http://synthetic-pacs'}
    def case_identity(self, uid):
        if uid != '1.2.3':
            raise KeyError('Missing synthetic study')
        return {'study_uid': uid, 'patient_id': 'synthetic-person'}


def service(tmp_path):
    history = History(tmp_path / 'history')
    jobs = SimpleNamespace(root=tmp_path / 'jobs', source=Source(),
                           lock=threading.RLock(), jobs={})
    jobs.root.mkdir()
    return CaseService(jobs, history, {'first': 'center-a', 'second': 'center-a',
                                      'outside': 'center-b'}, 'center-a'), history


CASE = {'study_uid': '1.2.3', 'patient_id': 'synthetic-person'}


def test_same_center_reads_saved_echomind_from_other_owner(tmp_path):
    cases, history = service(tmp_path)
    rid = str(uuid.uuid4())
    history.begin(rid, 'first', {'study_uid': '1.2.3'}, {'workflow': 'report'})
    history.finish(rid, 'first', {'content': 'Synthetic saved report'})
    snapshot = cases.snapshot('second', CASE)
    assert snapshot['echomind'][0]['request_id'] == rid
    assert cases.text('second', CASE, rid)['content'] == 'Synthetic saved report'
    with pytest.raises(PermissionError):
        cases.snapshot('outside', CASE)
    with pytest.raises(PermissionError):
        cases.snapshot('second', {**CASE, 'patient_id': 'wrong-person'})


def test_unbound_failed_and_other_study_history_is_not_available(tmp_path):
    cases, history = service(tmp_path)
    for context, failed in (({}, False), ({'study_uid': '1.2.4'}, False),
                            ({'study_uid': '1.2.3'}, True)):
        rid = str(uuid.uuid4())
        history.begin(rid, 'first', context, {'workflow': 'report'})
        history.finish(rid, 'first', {'content': 'Synthetic'}, failed=failed)
    assert cases.snapshot('second', CASE)['echomind'] == []


def test_broadcast_wakes_two_readers_and_does_not_contain_clinical_content():
    events = Events()
    cursor = events.cursor()
    replies = []
    readers = [threading.Thread(target=lambda: replies.append(
        events.wait(cursor, '1.2.3', timeout=2))) for _ in range(2)]
    for reader in readers:
        reader.start()
    events.publish('1.2.3', 'echomind')
    for reader in readers:
        reader.join(3)
    assert len(replies) == 2
    assert all(r['changed'] is True for r in replies)
    assert all(set(r) == {'epoch', 'revision', 'changed'} for r in replies)


def test_restart_cursor_and_overflow_require_reconciliation():
    events = Events(capacity=2)
    cursor = events.cursor()
    for _ in range(3):
        events.publish('1.2.4', 'eagle_eye')
    assert events.wait(cursor, '1.2.3', timeout=0)['changed'] is True
    assert events.wait({'epoch': 'older', 'revision': 0}, '1.2.3', timeout=0)['changed'] is True
    assert events.wait(events.cursor(), '1.2.3', timeout=0)['changed'] is False


def test_pending_and_failed_jobs_do_not_make_saved_results_available(tmp_path):
    cases, _ = service(tmp_path)
    cases.jobs.jobs = {str(i): dict(job_id=str(i), owner='first', module='brain',
        study_uid='1.2.3', status=status, created_at=i) for i, status in
        enumerate(('running', 'failed', 'succeeded'))}
    result = cases.snapshot('second', CASE)
    assert [job['status'] for job in result['eagle_eye']] == ['succeeded']
    assert result['jobs'][0]['status'] == 'succeeded'


def test_history_page_is_bounded_and_exact_result_does_not_change_history(tmp_path):
    cases, history = service(tmp_path)
    for i in range(55):
        rid = str(uuid.uuid4())
        history.begin(rid, 'first', {'study_uid': '1.2.3'}, {'workflow': 'report'})
        history.finish(rid, 'first', {'content': str(i)})
    page = cases.snapshot('second', CASE)
    assert len(page['echomind']) == 50
    assert page['more_echomind'] is True
    rid = page['echomind'][0]['request_id']
    assert cases.text('second', CASE, rid)['request_id'] == rid
    assert cases.snapshot('second', CASE) == page


def test_workflow_publication_is_scoped_and_wakes_result_readers(tmp_path):
    cases, _ = service(tmp_path)
    cases.snapshot('first', CASE)
    cursor = cases.events.cursor()
    cases.workflow_update([dict(CASE, report_status='completed', audio_count=2)])
    assert cases.events.wait(cursor, CASE['study_uid'], timeout=0)['changed']
    assert cases.snapshot('second', CASE)['workflow']['audio_count'] == 2
    cursor = cases.events.cursor()
    cases.workflow_update([dict(CASE, patient_id='wrong', report_status='pending', audio_count=9)])
    assert not cases.events.wait(cursor, CASE['study_uid'], timeout=0)['changed']
    assert cases.snapshot('second', CASE)['workflow']['audio_count'] == 2


def test_receiver_rejects_wrong_source_and_patient(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.case_receiver import CaseReceiver
    cases, _ = service(tmp_path)
    snapshot = cases.snapshot('first', CASE)
    receiver = CaseReceiver(CASE, pacs_host='synthetic-pacs')
    receiver.validate(snapshot, 'synthetic-pacs')
    with pytest.raises(ValueError):
        receiver.validate(snapshot, 'other-pacs')
    with pytest.raises(ValueError):
        receiver.validate(dict(snapshot, case={**CASE, 'patient_id': 'other'}), 'synthetic-pacs')


def test_membership_revocation_during_held_socket_read_fails_closed(tmp_path):
    cases, _ = service(tmp_path)
    entered = threading.Event()
    original = cases.jobs.source.case_identity
    def identity(uid):
        entered.set()
        return original(uid)
    cases.jobs.source.case_identity = identity
    errors = []
    def read():
        try:
            cases.wait('second', CASE, cases.events.cursor())
        except Exception as exc:
            errors.append(type(exc))
    reader = threading.Thread(target=read)
    reader.start()
    assert entered.wait(2)
    cases.memberships['second'] = 'center-b'
    cases.events.publish('1.2.3', 'echomind')
    reader.join(2)
    assert not reader.is_alive() and errors == [PermissionError]


def test_colocated_loopback_source_maps_only_to_the_authenticated_eagle_host(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.case_receiver import CaseReceiver
    cases, _ = service(tmp_path)
    snapshot = dict(cases.snapshot('first', CASE), pacs_host='127.0.0.1')
    receiver = CaseReceiver(CASE, pacs_host='synthetic-pacs')
    receiver.validate(snapshot, 'synthetic-pacs', 'synthetic-pacs')
    assert snapshot['pacs_host'] == 'synthetic-pacs'
    with pytest.raises(ValueError):
        receiver.validate(dict(snapshot, pacs_host='127.0.0.1'), 'other-pacs', 'synthetic-pacs')


@pytest.mark.parametrize('module', ['bone-age','total-spine','alignment','brain','brain-lesions','breast'])
def test_all_ai_modules_are_shared_saved_results(tmp_path, module):
    cases, _ = service(tmp_path)
    cases.jobs.jobs={'synthetic':dict(job_id='synthetic',owner='first',module=module,
        study_uid='1.2.3',status='succeeded',created_at=1)}
    assert cases.snapshot('second',CASE)['eagle_eye'][0]['module'] == module
