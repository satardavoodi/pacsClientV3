"""Selected Brain routes native chat; unsupported Custom Assist stays disabled."""
import pytest
from modules.ai_imaging.eagle_eye_remote.echomind import service, runtime

@pytest.mark.parametrize('profile', ['server_1'])
def test_native_chat_uses_shared_company_backend(monkeypatch, profile):
    calls=[]
    monkeypatch.setattr(service.company, 'chat', lambda text, **options: calls.append((text,options)) or {'content':'Synthetic answer'})
    monkeypatch.setattr(service, '_native', lambda request: pytest.fail('Legacy chat destination'))
    with runtime.request_context(base={'brain_server':profile}):
        assert service._process(service.ProcessRequest(workflow='chat',provider='aipacs',text='Synthetic'))['content']=='Synthetic answer'
    assert calls==[('Synthetic',{})]

@pytest.mark.parametrize('workflow', ['assistant','search','web_search'])
def test_custom_disables_legacy_assist_before_dispatch(monkeypatch, workflow):
    monkeypatch.setattr(service, '_native', lambda request: pytest.fail('Legacy Assist destination'))
    from modules.ai_imaging.eagle_eye_remote.echomind import web_search
    monkeypatch.setattr(web_search, 'search', lambda text: pytest.fail('Unsupported Custom web search'))
    with runtime.request_context(base={'brain_server':'custom'}):
        with pytest.raises(service.WorkflowError,match='unavailable.*Custom'):
            service._process(service.ProcessRequest(workflow=workflow,provider='aipacs' if workflow!='web_search' else 'company',text='Synthetic'))

@pytest.mark.parametrize('workflow', ['assistant','search'])
def test_server_one_keeps_legacy_assist(monkeypatch, workflow):
    calls=[]
    monkeypatch.setattr(service, '_native', lambda request: calls.append(request.workflow) or {'content':'Synthetic'})
    with runtime.request_context(base={'brain_server':'server_1'}):
        service._process(service.ProcessRequest(workflow=workflow,provider='aipacs',text='Synthetic'))
    assert calls==[workflow]

def test_capabilities_follow_saved_brain_profile_without_reconstruction(tmp_path):
    import json
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import EchoMind
    settings=tmp_path/'settings.json'
    settings.write_text(json.dumps({'brain_server':'server_1'}))
    host=EchoMind({'config_dir':str(tmp_path),'history_dir':str(tmp_path/'history')}, [])
    for workflow in ('assistant','search','web_search'):
        assert workflow in host.capabilities['workflows']
    settings.write_text(json.dumps({'brain_server':'custom'}))
    assert all(workflow not in host.capabilities['workflows'] for workflow in ('assistant','search','web_search'))
    assert 'chat' in host.capabilities['workflows']
    assert 'cited_web_search' not in host.capabilities['features']
    settings.write_text(json.dumps({'brain_server':'server_1'}))
    assert 'web_search' in host.capabilities['workflows']
