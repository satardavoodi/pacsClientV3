"""Synthetic Secretary language scope without provider traffic."""
import json
from pathlib import Path
import pytest
from tests.code.echomind.test_secretary_server import hosted, body

MOBILE_CAPABILITY = json.loads(Path(__file__).with_name('request_language_capability.json').read_text(encoding='utf-8'))['request_language']


def test_optional_preference_and_legacy_language_contract():
    from modules.ai_imaging.eagle_eye_remote.secretary.service import Request
    request = body()
    assert Request.model_validate(request).language == 'en'
    assert Request.model_validate(dict(request, language='auto', language_preference='fa')).language_preference == 'fa'
    with pytest.raises(ValueError):
        Request.model_validate(dict(request, language_preference='fr'))


@pytest.mark.parametrize('text,preference,selected', [
    ('Explain this page', 'fa', 'en'),
    ('\u0627\u06cc\u0646 \u0635\u0641\u062d\u0647 \u0631\u0627 \u062a\u0648\u0636\u06cc\u062d \u0628\u062f\u0647', 'en', 'fa'),
    ('123', 'fa', 'fa'),
])
def test_process_scopes_completion_policy_and_resets(hosted, monkeypatch, text, preference, selected):
    from modules.ai_imaging.eagle_eye_remote.secretary import service
    from modules.ai_imaging.eagle_eye_remote.response_language import current_reply_language
    calls = []
    monkeypatch.setattr(service.llm_client, 'gapgpt_chat', lambda **kw: calls.append(kw) or json.dumps({'modules':['homepage'], 'reason':'Synthetic'}))
    request = dict(body(), text=text, language_preference=preference)
    hosted.process('client', request)
    system, user = calls[0]['messages']
    assert ('in Persian' if selected == 'fa' else 'in English') in system['content']
    assert 'always English' not in system['content']
    assert json.loads(user['content'])['language'] == selected
    assert current_reply_language() == 'en'


def test_process_language_resets_after_failure(hosted, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.response_language import current_reply_language
    def fail(request):
        assert current_reply_language() == 'fa'
        raise RuntimeError('Synthetic failure')
    monkeypatch.setattr(hosted, '_route', fail)
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    with pytest.raises(RequestFailed) as failure:
        hosted.process('client', dict(body(), text='123', language_preference='fa'))
    assert failure.value.status == 502
    assert any('\u0600' <= c <= '\u06ff' for c in str(failure.value))
    assert current_reply_language() == 'en'


def test_fixed_clarification_preserves_machine_fields(hosted):
    from modules.ai_imaging.eagle_eye_remote.response_language import request_language
    from modules.ai_imaging.eagle_eye_remote.secretary.service import Request
    with request_language('123', 'fa'):
        plan = hosted._plan(Request.model_validate(body()), {'modules':[]})
    assert plan['action'] == 'unknown' and plan['entities'] == {}
    assert plan['needs_confirmation'] is False
    assert plan['reason'] != 'Please clarify the requested workstation task.'


@pytest.mark.parametrize('policy,expected', [
    (MOBILE_CAPABILITY, True),
    ({}, False),
    ({'protocol':1,'preference_field':'language_preference','supported_preferences':['fa','en'],'workflows':['crm']}, False),
    (dict(MOBILE_CAPABILITY, protocol=True), False),
    (dict(MOBILE_CAPABILITY, protocol='1'), False),
    (dict(MOBILE_CAPABILITY, supported_preferences=['fa']), False),
    (dict(MOBILE_CAPABILITY, supported_preferences='fa,en'), False),
    (dict(MOBILE_CAPABILITY, workflows='secretary'), False),
])
def test_transport_preference_requires_ready_workflow(monkeypatch, policy, expected):
    import io
    from concurrent.futures import ThreadPoolExecutor
    from modules.EchoMind.secretary import remote_planner
    captured = []
    class Client:
        def json(self, path):
            return {'request_language':policy}
        def open(self, path, payload, **kwargs):
            captured.append(payload)
            return io.BytesIO(json.dumps({'protocol':1,'request_id':payload['request_id'],'phase':'route',
                'route':{'modules':['homepage'],'reason':'Synthetic'},'plan':None}).encode())
    monkeypatch.setattr(remote_planner, 'Client', Client)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(remote_planner.request, 'route', 'Synthetic request', language='auto', language_preference='fa').result()
    assert ('language_preference' in captured[0]) == expected
    assert captured[0]['language'] == 'auto'
    assert captured[0]['text'] == 'Synthetic request'


@pytest.mark.parametrize('enabled,crm_enabled,workflows', [(False,False,[]),(True,False,['secretary']),(True,True,['secretary','crm'])])
def test_listener_advertises_only_configured_language_workflows(hosted, enabled, crm_enabled, workflows):
    import threading
    import urllib.request
    from types import SimpleNamespace
    from http.server import ThreadingHTTPServer
    from modules.ai_imaging.eagle_eye_remote import server
    crm = SimpleNamespace(capabilities={'version':1}) if crm_enabled else None
    http = ThreadingHTTPServer(('127.0.0.1',0), server.handler(SimpleNamespace(), {}, secretary=hosted if enabled else None, crm=crm))
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{http.server_port}/v1/capabilities',timeout=3) as response:
            capability = json.load(response)
        assert capability['request_language'] == {'protocol':1,'preference_field':'language_preference','supported_preferences':['fa','en'],'workflows':workflows}
        for key in ('protocol','preference_field','supported_preferences'):
            assert capability['request_language'][key] == MOBILE_CAPABILITY[key]
        assert 'lumbar_vision' in capability
    finally:
        http.shutdown()
        http.server_close()
        thread.join(3)
