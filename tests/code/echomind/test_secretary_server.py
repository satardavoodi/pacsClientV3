"""Synthetic headless Secretary planning on the existing authenticated listener."""
import json
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import EchoMind
    from modules.ai_imaging.eagle_eye_remote.secretary.service import Secretary
    (tmp_path / 'settings.json').write_text('{}')
    echo = EchoMind({'config_dir': str(tmp_path), 'history_dir': str(tmp_path / 'echo')}, ['client'])
    return Secretary({'history_dir': str(tmp_path / 'secretary')}, echo)


def body(phase='route', **fields):
    return dict(protocol=1, request_id=str(uuid4()), phase=phase,
                text='List today\'s patients.', language='en', client_time='2026-09-30T15:00:00+03:30', **fields)


def test_route_uses_server_catalog_and_returns_shared_id(hosted, monkeypatch):
    monkeypatch.setattr(hosted, '_completion', lambda *args: {'modules': ['homepage'], 'reason': 'Patient list.'})
    request = body()
    response = hosted.process('client', request)
    assert response == {'protocol': 1, 'request_id': request['request_id'], 'phase': 'route',
                        'route': {'modules': ['homepage'], 'reason': 'Patient list.'}, 'plan': None}


@pytest.mark.parametrize('phase,modules', [('route', None), ('plan', ['settings'])])
def test_server_instructs_settings_vs_current_page_boundary(hosted, monkeypatch, phase, modules):
    def completion(system, *args, **kwargs):
        assert 'SETTINGS VERSUS CURRENT PAGE' in system
        assert 'available modality options' in system
        assert 'Do not substitute a patient search' in system
        assert 'MATERIAL AMBIGUITY ONLY' in system
        assert 'one concise question' in system
        assert 'Do not ask again' in system
        if phase == 'route':
            return {'modules': ['settings'], 'reason': 'Persistent configuration.'}
        return {'action': 'open_settings', 'entities': {'section': 'viewer'},
                'confidence': 0.95, 'needs_confirmation': False,
                'reason': 'Open configuration; no settings have been changed.'}
    monkeypatch.setattr(hosted, '_completion', completion)
    request = body(phase)
    request['text'] = 'Remove unused modality options from the patient search panel.'
    if modules is not None:
        request['modules'] = modules
    response = hosted.process('client', request)
    assert response['route']['modules'] == ['settings']


@pytest.mark.parametrize('field', ['prompt', 'model', 'provider', 'key', 'catalog', 'url'])
def test_client_cannot_select_server_authorities(hosted, field):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    with pytest.raises(RequestFailed) as exc:
        hosted.process('client', body(**{field: 'untrusted'}))
    assert exc.value.status == 422


def test_unknown_module_or_action_is_rejected(hosted, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    with pytest.raises(RequestFailed):
        hosted.process('client', body('plan', modules=['../private']))
    monkeypatch.setattr(hosted, '_completion', lambda *args: {
        'action': 'delete_everything', 'entities': {}, 'confidence': 1,
        'needs_confirmation': False, 'reason': 'Untrusted.'})
    with pytest.raises(RequestFailed) as exc:
        hosted.process('client', body('plan', modules=['homepage']))
    assert exc.value.status == 422


def test_plan_returns_validated_local_action_without_execution(hosted, monkeypatch):
    monkeypatch.setattr(hosted, '_completion', lambda *args: {
        'action': 'list_patients', 'entities': {'date': '2026-09-30'},
        'confidence': 0.95, 'needs_confirmation': False, 'reason': 'Patient list.'})
    response = hosted.process('client', body('plan', modules=['homepage']))
    assert response['plan']['action'] == 'list_patients'
    assert not hasattr(hosted, 'executor')


@pytest.mark.parametrize('fields', [{'client_time': '2026-09-30T15:00:00'}, {'attempt': 4, 'max_attempts': 3}])
def test_clock_and_retry_bounds_are_strict(hosted, fields):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    request = body(); request.update(fields)
    with pytest.raises(RequestFailed) as exc:
        hosted.process('client', request)
    assert exc.value.status == 422


def test_shared_admission_and_duplicate_protection(hosted, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    monkeypatch.setattr(hosted, '_completion', lambda *args: {'modules': ['homepage'], 'reason': 'Patient list.'})
    assert hosted.echo.clients['client'].acquire(blocking=False)
    try:
        with pytest.raises(RequestFailed) as exc:
            hosted.process('client', body())
        assert exc.value.status == 429
    finally:
        hosted.echo.clients['client'].release()
    request = body(); hosted.process('client', request)
    with pytest.raises(RequestFailed) as exc:
        hosted.process('client', request)
    assert exc.value.status == 409


def test_repair_prompt_is_constructed_on_server(hosted, monkeypatch):
    captured = []
    def completion(system, payload, route=False):
        captured.append((system, payload))
        return {'action': 'list_patients', 'entities': {}, 'confidence': .9,
                'needs_confirmation': False, 'reason': 'Corrected request.'}
    monkeypatch.setattr(hosted, '_completion', completion)
    response = hosted.process('client', body('repair', modules=['homepage'],
        invalid_plan={'action': 'bad'}, validation_errors=[{'code': 'INVALID_ACTION'}]))
    assert response['plan']['action'] == 'list_patients'
    assert captured[0][1]['invalid_plan'] == {'action': 'bad'}
    assert 'Treat memory' in captured[0][0]


def test_existing_listener_authenticates_secretary_before_processing(hosted):
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    from modules.ai_imaging.eagle_eye_remote import server
    class Jobs:
        pass
    http = ThreadingHTTPServer(('127.0.0.1', 0), server.handler(Jobs(), {'client': 'test-token'}, secretary=hosted))
    thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
    try:
        request = urllib.request.Request(f'http://127.0.0.1:{http.server_port}/v1/secretary/plan',
            data=json.dumps(body()).encode(), headers={'Authorization': 'Bearer incorrect'})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)
        assert exc.value.code == 401
    finally:
        http.shutdown(); http.server_close(); thread.join(3)


def test_unknown_intent_returns_nonexecuting_clarification(hosted, monkeypatch):
    monkeypatch.setattr(hosted, '_completion', lambda *args: {'action': 'unknown', 'reason': 'Please clarify.'})
    result = hosted.process('client', body('plan', modules=['homepage']))
    assert result['plan'] == {'action': 'unknown', 'reason': 'Please clarify.',
                             'entities': {}, 'confidence': 0.0, 'needs_confirmation': False}


def test_multistep_validation_keeps_confirmation(hosted, monkeypatch):
    monkeypatch.setattr(hosted, '_completion', lambda *args: {'steps': [
        {'action': 'list_patients', 'entities': {}},
        {'action': 'open_patient', 'entities': {'patient_code': 'synthetic-case'}}]})
    plan = hosted.process('client', body('plan', modules=['homepage', 'patient_viewer']))['plan']
    assert plan['action'] == '__workflow__'
    assert plan['needs_confirmation'] is True
    assert plan['steps'][1]['needs_confirmation'] is True


def test_ordinal_open_is_validated_and_keeps_confirmation(hosted, monkeypatch):
    monkeypatch.setattr(hosted, '_completion', lambda *args: {'steps': [
        {'action': 'list_patients', 'entities': {'date':'2026-09-30'}},
        {'action': 'open_patient', 'entities': {'row_index':1}}]})
    plan = hosted.process('client', body('plan', modules=['homepage']))['plan']
    assert [s['action'] for s in plan['steps']] == ['list_patients','open_patient']
    assert plan['steps'][1]['entities'] == {'row_index':1}
    assert plan['steps'][1]['needs_confirmation'] is True


@pytest.mark.parametrize('entities', [
    {'row_index':True}, {'row_index':0}, {'row_index':10001}, {'row_index':'1'},
    {'row_index':1,'patient_code':'synthetic'},
    {'row_index':1,'resolved_patient':{'patient_id':'synthetic'}}])
def test_ordinal_open_rejects_invalid_or_ambiguous_reference(hosted, monkeypatch, entities):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    monkeypatch.setattr(hosted, '_completion', lambda *args: {
        'action':'open_patient','entities':entities,'confidence':.9,
        'needs_confirmation':True,'reason':'Synthetic ordinal request.'})
    with pytest.raises(RequestFailed) as exc:
        hosted.process('client', body('plan',modules=['homepage']))
    assert exc.value.status == 422


@pytest.mark.parametrize('response', [
    {'action':'open_patient','entities':{'row_index':1},'confidence':.9,
     'needs_confirmation':True,'reason':'Synthetic ordinal request.'},
    {'steps':[{'action':'set_source_mode','entities':{'mode':'local'}},
              {'action':'open_patient','entities':{'row_index':1}}]}])
def test_ordinal_without_preceding_list_returns_clarification(hosted, monkeypatch, response):
    monkeypatch.setattr(hosted, '_completion', lambda *args: response)
    plan=hosted.process('client',body('plan',modules=['homepage']))['plan']
    assert plan['action']=='unknown'
    assert plan['needs_confirmation'] is False


@pytest.mark.parametrize("mode", ["ask", "guide"])
def test_non_action_mode_uses_dedicated_prompt_without_action_plan(hosted, monkeypatch, mode):
    calls = []
    def completion(system, payload, route=False):
        calls.append((system, payload))
        if route: return {"modules":["homepage"], "reason":"Synthetic"}
        return {"answer":"Synthetic mode answer"}
    monkeypatch.setattr(hosted, "_completion", completion)
    response = hosted.process("client", body("plan", interaction_mode=mode))
    assert response["plan"] is None
    assert response["interaction_mode"] == mode
    assert response["answer"] == "Synthetic mode answer"
    assert ("Ask mode" if mode == "ask" else "Guide mode") in calls[-1][0]


@pytest.mark.parametrize('mode', ['ask', 'guide'])
def test_answer_modes_reject_action_smuggling(hosted, monkeypatch, mode):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    monkeypatch.setattr(hosted, '_completion', lambda system, payload, route=False:
        {'modules':['homepage'], 'reason':'Synthetic'} if route else
        {'answer':'Synthetic answer', 'action':'release_memory'})
    with pytest.raises(RequestFailed) as exc:
        hosted.process('client', body('plan', interaction_mode=mode))
    assert exc.value.status == 422


def test_help_ticket_dedicated_prompt_returns_only_valid_draft(hosted, monkeypatch):
    def completion(system, payload, route=False):
        if route: return {'modules':['support_control'], 'reason':'Synthetic'}
        assert 'Help Ticket mode' in system
        return {'answer':'Review the draft.', 'ticket':{'category':'hang', 'description':'Synthetic toolbar froze.'}}
    monkeypatch.setattr(hosted, '_completion', completion)
    response = hosted.process('client', body('plan', interaction_mode='help_ticket'))
    assert response['plan'] is None
    assert response['ticket']['category'] == 'hang'


@pytest.mark.parametrize('operation',['prepare','retry','status'])
def test_help_ticket_intent_is_typed_and_never_executable(hosted,monkeypatch,operation):
    monkeypatch.setattr(hosted,'_completion',lambda system,payload,route=False:
        {'modules':['support_control'],'reason':'Synthetic'} if route else
        {'answer':'Review the local ticket state.','ticket':{'operation':operation,'category':'other','description':'Synthetic ticket request.'}})
    response = hosted.process('client',body('plan',interaction_mode='help_ticket',question_context={'support_ticket_intents':1}))
    assert response['ticket']['operation'] == operation
    assert response['plan'] is None


def test_help_ticket_rejects_untrusted_transport_operation(hosted,monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    monkeypatch.setattr(hosted,'_completion',lambda system,payload,route=False:
        {'modules':['support_control'],'reason':'Synthetic'} if route else
        {'answer':'Synthetic','ticket':{'operation':'upload-to-arbitrary-url','category':'other','description':'Synthetic ticket request.'}})
    with pytest.raises(RequestFailed):
        hosted.process('client',body('plan',interaction_mode='help_ticket'))


def test_guide_rejects_invented_tutorial_target(hosted, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    monkeypatch.setattr(hosted, '_completion', lambda system,payload,route=False:
        {'modules':['homepage'], 'reason':'Synthetic'} if route else {'answer':'Synthetic', 'tutorial_id':'invented'})
    with pytest.raises(RequestFailed):
        hosted.process('client', body('plan', interaction_mode='guide', question_context={'tutorials':{}}))


def test_server_preserves_bounded_choice_question(hosted,monkeypatch):
    question={'question':'Which scope?', 'options':[{'id':'settings','label':'Change Settings'},
               {'id':'results','label':'Filter current results'}]}
    monkeypatch.setattr(hosted,'_completion',lambda *a,**kw:{'action':'unknown',
        'reason':question['question'],'clarification':question})
    result=hosted.process('client',body('plan',modules=['settings']))
    assert result['plan']['clarification']==question
    assert result['plan']['needs_confirmation'] is False
