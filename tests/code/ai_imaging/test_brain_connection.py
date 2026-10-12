"""Synthetic shared Brain accounting and private-authentication guards."""
import json
import pytest
from modules.ai_imaging.eagle_eye_remote import brain_connection as brain
from modules.ai_imaging.eagle_eye_remote.echomind import runtime

def test_all_models_sum_by_source_without_storing_content(tmp_path):
    for category, tokens in [('echomind', 3), ('echomind', 7), ('secretary', 5), ('agent', 11), ('crm', 13)]:
        with brain.source(category):
            rid = brain.begin(tmp_path)
            brain.finish(tmp_path, rid, {'prompt_tokens':tokens, 'completion_tokens':2})
    rows = {r['label']:r for r in brain.summary(tmp_path)['groups']}
    assert rows['EchoMind']['calls'] == 2
    assert rows['EchoMind']['total_tokens'] == 14
    assert rows['Secretary EchoMind']['calls'] == 1
    assert rows['Agent']['total_tokens'] == 13
    assert rows['CRM']['calls'] == 1

def test_company_transport_accounts_missing_and_failure_without_replay(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'company_identity', lambda: ('Synthetic', 'synthetic-provider-key'))
    class Reply:
        def json(self): return {'usage': {'prompt_tokens':4, 'completion_tokens':6}}
    with runtime.configuration(tmp_path), runtime.request_context(base={'llm_backend':'company'}):
        assert isinstance(brain.send('https://api.gapgpt.app/v1/chat/completions', Reply), Reply)
        def fail(): raise ValueError('synthetic failure')
        with pytest.raises(ValueError): brain.send('https://api.gapgpt.app/v1/responses', fail)
    row = brain.summary(tmp_path)['groups'][0]
    assert row['calls'] == 2 and row['failed'] == 1
    assert row['total_tokens'] == 10 and row['missing_usage'] == 1

def test_personal_is_excluded_and_native_company_call_is_accounted(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'company_identity', lambda: ('Synthetic', 'synthetic-provider-key'))
    with runtime.configuration(tmp_path), runtime.request_context(base={'llm_backend':'openai'}):
        assert brain.send('https://api.gapgpt.app/v1/chat/completions', lambda: 42) == 42
    with runtime.configuration(tmp_path), runtime.request_context(base={'llm_backend':'company'}):
        assert brain.send(__import__('modules.ai_imaging.eagle_eye_remote.echomind.core.ai_chat_config', fromlist=['URL_GEN_ASSISTANT']).URL_GEN_ASSISTANT, lambda: 42) == 42
    assert brain.summary(tmp_path)['groups'][0]['calls'] == 1
    assert brain.summary(tmp_path)['groups'][0]['missing_usage'] == 1

def test_private_auth_preserves_models_and_uses_registry(monkeypatch,tmp_path):
    from modules.ai_imaging.eagle_eye_remote import brain_administration as admin
    settings = tmp_path/'settings.json'
    settings.write_text(json.dumps({'crm_model':'unchanged', 'api_key':''}))
    monkeypatch.setattr(admin,'directory',lambda:tmp_path)
    monkeypatch.setattr(runtime,'company_identity',lambda:('Synthetic center','synthetic provider key'))
    initial=admin.snapshot()
    result=admin.authenticate(initial['revision'],'synthetic-code')
    assert result['authenticated']
    assert json.loads(settings.read_text())['crm_model']=='unchanged'
    assert 'synthetic-code' not in json.dumps(result)
    with pytest.raises(ValueError):admin.authenticate(initial['revision'],'another-code')


def test_brain_authority_denies_missing_context_disabled_and_invalid_code(monkeypatch,tmp_path):
    calls=[]
    send=lambda: calls.append('sent')
    with pytest.raises(ValueError, match='context'):
        brain.send('https://api.gapgpt.app/v1/chat/completions', send)
    with runtime.configuration(tmp_path), runtime.request_context(base={'brain_enabled':False}):
        with pytest.raises(ValueError,match='disabled'):
            brain.send('https://api.gapgpt.app/v1/chat/completions', send)
    def invalid(): raise ValueError('synthetic invalid code')
    monkeypatch.setattr(runtime,'company_identity',invalid)
    with runtime.configuration(tmp_path), runtime.request_context(base={}):
        with pytest.raises(ValueError,match='Authenticate'):
            brain.send('https://api.gapgpt.app/v1/chat/completions', send)
    assert calls==[]
    assert not (tmp_path/'brain-usage.sqlite3').exists()


def test_brain_authority_replaces_caller_authorization_without_changing_model(monkeypatch,tmp_path):
    monkeypatch.setattr(runtime,'company_identity',lambda:('Synthetic','shared-synthetic-key'))
    options={'headers':{'authorization':'unapproved-synthetic-key'}, 'json':{'model':'unchanged-model'}}
    class Reply:
        status_code=200
        def json(self):return {'usage':{}}
    def operation():
        assert options['headers']=={'Authorization':'Bearer shared-synthetic-key'}
        assert options['json']['model']=='unchanged-model'
        return Reply()
    with runtime.configuration(tmp_path),runtime.request_context(base={}):
        brain.send('https://api.gapgpt.app/v1/chat/completions',operation,options=options)


def test_unregistered_company_destination_and_request_center_override_are_denied(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.echomind import service
    with runtime.configuration(tmp_path),runtime.request_context(base={}):
        with pytest.raises(ValueError,match='not registered'):
            brain.send('https://unregistered.example.test/v1/chat/completions',lambda: pytest.fail('must not send'))
    request=service.ProcessRequest(text='synthetic',workflow='chat',provider='company')
    with pytest.raises(service.WorkflowError,match='owned by Eagle AI Brain'):
        service._overrides(request,'','alternate-synthetic-code')


def test_hosted_crm_diagnostic_cannot_use_independent_credentials(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.crm.vendor.reception_crm.llm import client
    from modules.ai_imaging.eagle_eye_remote.crm import provider
    seen=[]
    monkeypatch.setattr(provider,'completion',lambda messages,**options:seen.append(options))
    monkeypatch.setenv('CRM_EAGLE_CONFIG','synthetic-private-config')
    assert client.test_connection()['display_name']=='Eagle AI Brain'
    assert len(seen)==1
    monkeypatch.delenv('CRM_EAGLE_CONFIG')
    with pytest.raises(client.LLMAuthError):client.test_connection()


def test_operator_probe_uses_shared_private_context_and_redacts_result(monkeypatch,tmp_path):
    from modules.ai_imaging.eagle_eye_remote import brain_administration as admin
    from modules.ai_imaging.eagle_eye_remote.echomind.core import llm_client
    monkeypatch.setattr(admin,'directory',lambda:tmp_path)
    monkeypatch.setattr(admin,'snapshot',lambda:{'revision':'synthetic','authenticated':True,'usage':{}})
    def probe(**options):
        assert runtime.private_dir()==tmp_path
        assert runtime.current_settings()['llm_backend']=='company'
        return {'ok':True,'raw':'synthetic-private-provider-data'}
    monkeypatch.setattr(llm_client,'test_active_backend_connection',probe)
    result=admin.test_connection()
    assert result['connection_ok']
    assert 'raw' not in result
