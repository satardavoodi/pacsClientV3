"""Server-only Turbo-first reporting; synthetic content, no live providers."""
import pytest
from modules.ai_imaging.eagle_eye_remote.echomind import service


def test_send_report_tries_turbo_before_company_service(monkeypatch):
    calls=[]
    monkeypatch.setattr(service,'build_turbo_system_prompt',lambda *a,**k:'Server Turbo prompt')
    monkeypatch.setattr(service.company,'reporter',lambda *a,**k:calls.append(('turbo',k)) or {'content':'Synthetic Turbo report'})
    monkeypatch.setattr(service,'_native',lambda r:calls.append(('company',r)) or {'content':'Synthetic company report'})
    result=service.process(service.ProcessRequest(text='Synthetic findings',workflow='report'),base={})
    assert [c[0] for c in calls]==['turbo']
    assert calls[0][1]['system_prompt_override']=='Server Turbo prompt'
    assert result['route_used']=='turbo'


@pytest.mark.parametrize('failure',[TimeoutError(),RuntimeError('private-provider-detail'),None,'   ',{}, {'error':'Synthetic failure'}])
def test_failed_or_empty_turbo_falls_back_once_preserving_report_inputs(monkeypatch,failure):
    calls=[]
    monkeypatch.setattr(service,'build_turbo_system_prompt',lambda *a,**k:'Server Turbo prompt')
    def turbo(*a,**k):
        calls.append('turbo')
        if isinstance(failure,Exception): raise failure
        return {'content':failure}
    monkeypatch.setattr(service.company,'reporter',turbo)
    def fallback(request):
        calls.append('company')
        assert request.text=='Synthetic findings' and request.modality=='MRI'
        assert request.normal_template=='Synthetic template'
        assert request.workflow=='report' and request.provider=='aipacs'
        return {'content':'Synthetic fallback','usage':{}}
    monkeypatch.setattr(service,'_native',fallback)
    result=service.process(service.ProcessRequest(text='Synthetic findings',modality='MRI',normal_template='Synthetic template'),base={})
    assert calls==['turbo','company']
    assert result['route_used']=='company_service'
    assert 'private-provider-detail' not in repr(result)


def test_personal_reporting_does_not_enter_company_fallback(monkeypatch):
    monkeypatch.setattr(service.openai,'reporter',lambda *a,**k:{'content':'Personal synthetic report'})
    monkeypatch.setattr(service.company,'reporter',lambda *a,**k:pytest.fail('Company route'))
    monkeypatch.setattr(service,'_native',lambda *a:pytest.fail('Company fallback'))
    assert service.process(service.ProcessRequest(text='Synthetic',provider='openai'),base={})['content']=='Personal synthetic report'


def test_both_empty_routes_fail_without_success(monkeypatch):
    monkeypatch.setattr(service,'build_turbo_system_prompt',lambda *a,**k:'Server Turbo prompt')
    monkeypatch.setattr(service.company,'reporter',lambda *a,**k:{'content':''})
    monkeypatch.setattr(service,'_native',lambda *a:{'content':' '})
    with pytest.raises(service.WorkflowError):
        service.process(service.ProcessRequest(text='Synthetic'),base={})


def test_attachment_failure_never_silently_drops_attachment(monkeypatch):
    monkeypatch.setattr(service,'build_turbo_system_prompt',lambda *a,**k:'Server Turbo prompt')
    monkeypatch.setattr(service.company,'reporter',lambda *a,**k: {'content':''})
    monkeypatch.setattr(service,'_native',lambda *a:pytest.fail('Cannot drop attachments'))
    request=service.ProcessRequest(text='Synthetic')
    request=request.model_copy(update={'attachments':[object()]})
    with pytest.raises(service.WorkflowError,match='attachments'):
        service._report_with_fallback(request,{'attachment_parts':['synthetic']})


def test_company_provider_alias_cannot_skip_turbo(monkeypatch):
    calls=[]
    monkeypatch.setattr(service,'build_turbo_system_prompt',lambda *a,**k:'Server Turbo prompt')
    monkeypatch.setattr(service.company,'reporter',lambda *a,**k:calls.append('turbo') or {'content':'Synthetic'})
    monkeypatch.setattr(service,'_native',lambda *a:pytest.fail('Unexpected fallback'))
    assert service.process(service.ProcessRequest(text='Synthetic',provider='aipacs'),base={})['route_used']=='turbo'
    assert calls==['turbo']


def test_fallback_is_one_hosted_request_and_duplicate_does_not_resend(tmp_path,monkeypatch):
    from uuid import uuid4
    from modules.ai_imaging.eagle_eye_remote.echomind import hosting
    (tmp_path/'settings.json').write_text('{}')
    host=hosting.EchoMind({'config_dir':str(tmp_path),'history_dir':str(tmp_path/'history')},['synthetic-device'])
    calls=[]
    monkeypatch.setattr(service,'build_turbo_system_prompt',lambda *a,**k:'Server Turbo prompt')
    monkeypatch.setattr(service.company,'reporter',lambda *a,**k:calls.append('turbo') or {'content':''})
    monkeypatch.setattr(service,'_native',lambda *a:calls.append('company') or {'content':'Synthetic report'})
    body=dict(text='Synthetic findings',workflow='report',request_id=str(uuid4()))
    result=host.process('synthetic-device',body)
    assert result['fallback_used'] is True and result['request_id']==body['request_id']
    with pytest.raises(hosting.RequestFailed) as error: host.process('synthetic-device',body)
    assert error.value.status==409
    assert calls==['turbo','company']


def test_server_advertises_single_report_workflow_not_turbo_choice(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.echomind import hosting
    (tmp_path/'settings.json').write_text('{}')
    host=hosting.EchoMind({'config_dir':str(tmp_path),'history_dir':str(tmp_path/'history')},['synthetic-device'])
    assert 'report' in host.capabilities['workflows']
    assert 'turbo' not in host.capabilities['workflows']
    assert host.capabilities['report_policy']=='turbo_then_company'
