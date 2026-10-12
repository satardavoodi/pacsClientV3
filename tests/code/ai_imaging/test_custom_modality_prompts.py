"""Custom reporting requires the exact user modality prompt without generic fallback."""
import pytest
from modules.ai_imaging.eagle_eye_remote import brain_profiles
from modules.ai_imaging.eagle_eye_remote.echomind import service, runtime

@pytest.mark.parametrize('modality,key',[('MRI','mri'),('CT','ct'),('Sonography','sonography'),('Obstetrics','obstetrics'),('Cardiology','cardiology')])
@pytest.mark.parametrize('workflow',['report','turbo','correction'])
def test_exact_modality_prompt_replaces_company_messages(modality,key,workflow):
    settings={'openai_base_url':'https://example.invalid/v1','openai_api_key':'synthetic','openai_report_model':'own-model','brain_workflow':workflow,'brain_modality':modality,'prompt_report_generation':'Forbidden generic','prompt_report_'+key:'Own '+key}
    options={'json':{'messages':[{'role':'system','content':'Forbidden company'},{'role':'developer','content':'Forbidden developer'},{'role':'user','content':'Synthetic data'}]}}
    brain_profiles.custom_options(settings,options,'echomind')
    assert options['json']['messages']==[{'role':'system','content':'Own '+key},{'role':'user','content':'Synthetic data'}]

@pytest.mark.parametrize('modality',['','MR','Unknown'])
def test_no_generic_prompt_fallback(modality):
    settings={'openai_base_url':'https://example.invalid/v1','openai_api_key':'synthetic','openai_report_model':'own','brain_workflow':'report','brain_modality':modality,'prompt_report_generation':'Forbidden generic'}
    with pytest.raises(ValueError,match='modality'):
        brain_profiles.custom_options(settings,{'json':{'messages':[]}},'echomind')

def test_service_captures_modality():
    request=service.ProcessRequest(workflow='correction',text='Synthetic',modality='CT',correction_note='Synthetic correction')
    assert service._overrides(request,'','')['brain_modality']=='CT'

@pytest.mark.parametrize('workflow',['report','turbo','correction'])
def test_custom_reporting_sends_only_user_prompt_and_data(monkeypatch, workflow):
    import json
    monkeypatch.setattr(runtime,'company_identity',lambda:pytest.fail('Company identity'))
    monkeypatch.setattr(service.company,'reporter',lambda *a,**k:pytest.fail('Company reporter'))
    monkeypatch.setattr(service,'build_turbo_system_prompt',lambda *a,**k:pytest.fail('Company prompt'))
    captured=[]
    class Reply:
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':'Synthetic result'}}]}
    def post(url, **options):
        brain_profiles.custom_options(runtime.current_settings(),options,'echomind')
        assert options['_brain_url']=='https://example.invalid/v1/chat/completions'
        assert options['headers']['Authorization']=='Bearer synthetic'
        captured.append(options['json']['messages'])
        return Reply()
    monkeypatch.setattr(service.echomind_http,'post',post)
    request=service.ProcessRequest(workflow=workflow,text='Synthetic source',modality='CT',normal_template='Synthetic template',correction_note='Synthetic correction')
    settings={'brain_server':'custom','openai_base_url':'https://example.invalid/v1','openai_api_key':'synthetic','openai_report_model':'own','prompt_report_ct':'User CT instructions'}
    assert service.process(request,base=settings)['content']=='Synthetic result'
    assert captured[0][0]=={'role':'system','content':'User CT instructions'}
    data=json.loads(captured[0][1]['content'])
    assert data=={'text':'Synthetic source','modality':'CT','normal_template':'Synthetic template','correction_note':'Synthetic correction','target_section':''}
    assert len(captured[0])==2

def test_custom_ui_exposes_empty_modality_prompts(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PacsClient.pacs.workstation_ui.settings_ui.brain_connection_settings import BrainConnectionWidget
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(BrainConnectionWidget,'load',lambda self:None)
    widget=BrainConnectionWidget()
    try:
        for key in brain_profiles.MODALITY_PROMPTS.values():
            assert widget.custom_fields[key].toPlainText()==''
    finally:
        widget.deleteLater();app.processEvents()

@pytest.mark.parametrize('alias,key',[('SONOGRAPHY','sonography'),('OBSTETRIC ULTRASOUND','obstetrics'),('ECHOCARDIOGRAPHY','cardiology')])
def test_known_wire_modality_aliases(alias,key):
    settings={'openai_base_url':'https://example.invalid/v1','openai_api_key':'synthetic','openai_report_model':'own','brain_workflow':'report','brain_modality':alias,'prompt_report_'+key:'Own selected'}
    options={'json':{'messages':[{'role':'user','content':'Synthetic'}]}}
    brain_profiles.custom_options(settings,options,'echomind')
    assert options['json']['messages'][0]['content']=='Own selected'

def test_custom_chat_has_no_company_identity_dependency(monkeypatch):
    import json
    monkeypatch.setattr(runtime,'company_identity',lambda:pytest.fail('Company identity'))
    monkeypatch.setattr(service.company,'chat',lambda *a,**k:pytest.fail('Company chat'))
    class Reply:
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':'Synthetic answer'}}]}
    def post(url,**options):
        brain_profiles.custom_options(runtime.current_settings(),options,'echomind')
        assert options['json']['messages']==[{'role':'system','content':'Own chat prompt'},{'role':'user','content':json.dumps({'text':'Synthetic'},ensure_ascii=True)}]
        assert options['json']['model']=='own-chat'
        return Reply()
    monkeypatch.setattr(service.echomind_http,'post',post)
    settings={'brain_server':'custom','openai_base_url':'https://example.invalid/v1','openai_api_key':'synthetic','openai_text_model':'own-chat','prompt_report_generation':'Own chat prompt'}
    assert service.process(service.ProcessRequest(workflow='chat',provider='aipacs',text='Synthetic'),base=settings)['content']=='Synthetic answer'
