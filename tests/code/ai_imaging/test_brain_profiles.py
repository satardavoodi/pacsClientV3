"""Named Brain profiles preserve models and isolate custom identity and usage."""
import pytest
from modules.ai_imaging.eagle_eye_remote import brain_connection as brain
from modules.ai_imaging.eagle_eye_remote.echomind import runtime

@pytest.mark.parametrize('profile',['server_2','server_3'])
def test_reserved_gpu_routes_never_send_or_fallback(tmp_path,profile):
    with runtime.configuration(tmp_path),runtime.request_context(base={'brain_server':profile}):
        with pytest.raises(ValueError,match='no qualified model'):
            brain.send('https://api.gapgpt.app/v1/chat/completions',lambda:pytest.fail('must not send'))
    assert not (tmp_path/'brain-usage.sqlite3').exists()

def test_custom_route_uses_own_key_prompt_model_and_separate_accounting(tmp_path,monkeypatch):
    monkeypatch.setattr(runtime,'company_identity',lambda:pytest.fail('must not use company identity'))
    settings={'brain_server':'custom','openai_api_key':'synthetic-own-key', 'openai_base_url':'https://custom.example.test/v1',
              'brain_modality':'CT','prompt_report_ct':'User-defined synthetic report prompt','openai_report_model':'own-report-model','prompt_report_generation':'User-defined synthetic report prompt'}
    options={'headers':{'Authorization':'Bearer synthetic-company-key'},'json':{'model':'company-model','messages':[{'role':'system','content':'company-prompt'},{'role':'user','content':'synthetic'}]}}
    class Reply:
        status_code=200
        def json(self):return {'usage':{'input_tokens':2,'output_tokens':3}}
    def send():
        assert options['_brain_url']=='https://custom.example.test/v1/chat/completions'
        assert options['headers']['Authorization']=='Bearer synthetic-own-key'
        assert options['json']['model']=='own-report-model'
        assert options['json']['messages'][0]['content'].startswith('User-defined')
        return Reply()
    with runtime.configuration(tmp_path),runtime.request_context(base=settings):
        brain.send('https://api.gapgpt.app/v1/chat/completions',send,options=options)
    assert brain.summary(tmp_path,'custom')['groups'][0]['total_tokens']==5
    assert brain.summary(tmp_path,'server_1')['groups'][0]['calls']==0
    assert settings['openai_report_model']=='own-report-model'

def test_custom_requires_explicit_prompt_and_never_contacts_provider(tmp_path):
    base={'brain_server':'custom','openai_api_key':'synthetic','openai_base_url':'https://api.openai.com/v1','openai_report_model':'own-model'}
    with runtime.configuration(tmp_path),runtime.request_context(base=base):
        with pytest.raises(ValueError,match='own.*prompt'):
            brain.send('https://api.gapgpt.app/v1/chat/completions',lambda:pytest.fail('must not send'),options={'json':{'messages':[]}})

def test_profile_save_preserves_company_models_and_private_keys(monkeypatch,tmp_path):
    import json
    from modules.ai_imaging.eagle_eye_remote import brain_administration as admin
    monkeypatch.setattr(admin,'directory',lambda:tmp_path)
    p=tmp_path/'settings.json';p.write_text(json.dumps({'crm_model':'keep-model','openai_api_key':'synthetic-existing'}))
    initial=admin.snapshot()
    result=admin.save_profile(initial['revision'],'custom',{'openai_base_url':'https://api.openai.com/v1','openai_api_key':'','prompt_report_generation':'own prompt'})
    saved=json.loads(p.read_text())
    assert saved['crm_model']=='keep-model' and saved['openai_api_key']=='synthetic-existing'
    assert 'synthetic-existing' not in json.dumps(result)


def test_custom_brain_key_never_changes_company_speech_identity(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind.core.voice_transcription import resolve_auth_token
    monkeypatch.setattr(runtime,'company_identity',lambda:('Synthetic','synthetic-speech-registry-key'))
    with runtime.request_context(base={'brain_server':'custom','openai_api_key':'synthetic-own-llm-key'}):
        assert resolve_auth_token({'provider':'aipacs_3'})=='synthetic-speech-registry-key'

def test_connection_form_exposes_four_named_routes_and_custom_fields(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PacsClient.pacs.workstation_ui.settings_ui.brain_connection_settings import BrainConnectionWidget
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(BrainConnectionWidget,'load',lambda self:None)
    widget=BrainConnectionWidget()
    try:
        assert [widget.profile.itemText(i) for i in range(4)]==['Server 1 - LLM G','Server 2 - LLM A','Server 3 - LLM V','Custom API']
        widget.render({'revision':'synthetic','authenticated':False,'selected':'custom','custom':{'openai_base_url':'https://api.openai.com/v1'},'usage':{'groups':[]}})
        assert not widget.custom_group.isHidden()
        assert widget.custom_fields['openai_api_key'].text()==''
        assert widget.code.isHidden()
    finally:
        widget.close();widget.deleteLater();app.processEvents()


def test_usage_directory_can_be_separate_from_read_only_credentials(monkeypatch,tmp_path):
    monkeypatch.setattr(runtime,'company_identity',lambda:('Synthetic','synthetic-key'))
    class Reply:
        status_code=200
        def json(self):return {'usage':{}}
    with runtime.configuration(tmp_path/'credentials'),runtime.request_context(base={'brain_usage_dir':str(tmp_path/'usage')}):
        brain.send('https://api.gapgpt.app/v1/chat/completions',Reply)
    assert (tmp_path/'usage/brain-usage.sqlite3').is_file()
    assert not (tmp_path/'credentials/brain-usage.sqlite3').exists()
