"""Reference calculations must be reproducible and refuse missing context."""
import pytest

from modules.ai_imaging.eagle_eye_remote.echomind.reference_report import (
    ReferenceContext, fetal_reference, compare, Measurement, validate_evidence,
)


@pytest.mark.parametrize('name,value,z', [
    ('HC',230,0.7420728378581799), ('AC',210,1.474873271111466),
    ('FL',50,3.6067496338973846), ('BPD',70,2.7016484323407166),
    ('OFD',80,0.31313241988717905), ('EFW',870.1617721519996,2.549942896377175),
])
def test_official_calculator_example(name, value, z):
    # Public INTERGROWTH workbook example, row 6; not a patient fixture.
    result = fetal_reference(name, value, 171)
    assert result['z'] == pytest.approx(z, abs=1e-9)


def test_context_missing_and_bpd_technique_do_not_generate_centiles():
    m = Measurement(parameter='BPD', value=70, unit='mm', evidence='BPD 70 mm')
    assert 'Unavailable' in compare(m, ReferenceContext(), 'OBSTETRIC ULTRASOUND')['comparison']
    ctx = ReferenceContext(ga_days=171, singleton=True)
    assert 'outer-to-outer' in compare(m, ctx, 'OBSTETRIC ULTRASOUND')['comparison']


def test_adult_sex_method_and_child_safety():
    m = Measurement(parameter='LVEF', value=52, unit='%', evidence='LVEF 52%')
    assert 'Unavailable' in compare(m, ReferenceContext(age_years=10, sex='male', ef_method='biplane'), 'ECHOCARDIOGRAPHY')['comparison']
    male = compare(m, ReferenceContext(age_years=40, sex='male', ef_method='biplane'), 'ECHOCARDIOGRAPHY')
    female = compare(m, ReferenceContext(age_years=40, sex='female', ef_method='biplane'), 'ECHOCARDIOGRAPHY')
    assert male['comparison'].startswith('Within')
    assert female['comparison'].startswith('Below')
    assert male['percentile'] is None


def test_invented_number_or_quote_rejected():
    m = Measurement(parameter='HC', value=250, unit='mm', evidence='HC 230 mm')
    with pytest.raises(ValueError):
        validate_evidence(m, 'HC 230 mm')
    m = m.model_copy(update={'value':230})
    with pytest.raises(ValueError):
        validate_evidence(m, 'AC 230 mm')


@pytest.mark.parametrize('days', [97,281,294])
def test_no_fetal_extrapolation(days):
    with pytest.raises(ValueError):
        fetal_reference('HC',230,days)


def test_unknown_measurement_is_retained_without_invented_reference():
    m = Measurement(parameter='Valve length', value=12, unit='mm', evidence='Valve length 12 mm')
    result = compare(m, ReferenceContext(age_years=40), 'ECHOCARDIOGRAPHY')
    assert result['value'] == '12 mm'
    assert result['percentile'] is None
    assert 'Unavailable' in result['comparison']


def test_server_extraction_retains_original_and_computes_only_verified_values(monkeypatch):
    import json
    from modules.ai_imaging.eagle_eye_remote.echomind import service, reference_report
    text = 'HC 230 mm. AC 210 mm. FL 50 mm.'
    def fake_provider(received, modality, template, **kwargs):
        assert received == text and modality == ''
        assert 'Do not generate normals' in kwargs['system_prompt_override']
        return {'content':json.dumps({'measurements':[
            {'parameter':k,'value':v,'unit':'mm','evidence':f'{k} {v} mm'}
            for k,v in [('HC',230),('AC',210),('FL',50)]]}), 'usage':{}}
    monkeypatch.setattr(service.company,'reporter',fake_provider)
    result = service._process(service.ProcessRequest(text=text, workflow='add_reference',
        modality='OBSTETRIC ULTRASOUND',reference_context={'ga_days':171,'singleton':True}))
    assert result['content']['Original report'] == text
    assert '77.1' in result['content']['Measurement assessment']
    assert 'FL' in result['content']['Integrated review']


def test_client_reference_transport_has_no_prompt_or_provider_fallback(monkeypatch):
    from modules.EchoMind import remote_backend
    captured = []
    monkeypatch.setattr(remote_backend,'_request',lambda *a,**k: captured.append((a,k)))
    remote_backend.add_reference('Edited report','ECHOCARDIOGRAPHY',{'age_years':40})
    assert captured == [(('add_reference','Edited report'),
                         {'modality':'ECHOCARDIOGRAPHY','reference_context':{'age_years':40}})]


def test_reference_callback_on_all_live_and_restored_report_paths():
    import ast
    from pathlib import Path
    tree = ast.parse(Path('modules/EchoMind/viewer_chat/ai_chat_pages.py').read_text('utf-8'))
    calls = [n for n in ast.walk(tree) if isinstance(n,ast.Call)
             and any(k.arg == 'on_medical_consult' for k in n.keywords)]
    assert len(calls) == 4
    assert all(any(k.arg == 'on_add_reference' for k in n.keywords) for n in calls)


def test_reference_button_callback():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from modules.EchoMind.viewer_chat.ai_chat_widgets import MessageBubble
    seen=[]
    bubble=MessageBubble('AI ChatBot','Synthetic report',on_add_reference=seen.append)
    bubble.btnAddReference.click()
    assert seen == [bubble]
    bubble.close()
    bubble.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('provider', ['openai','aipacs'])
def test_reference_workflow_rejects_other_providers(provider):
    from modules.ai_imaging.eagle_eye_remote.echomind import service
    with pytest.raises(service.WorkflowError):
        service._process(service.ProcessRequest(text='Synthetic',workflow='add_reference',provider=provider))


def test_host_accepts_context_and_rejects_untrusted_reference_definitions(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind import hosting, service
    (tmp_path/'settings.json').write_text('{}')
    host=hosting.EchoMind({'config_dir':str(tmp_path),'history_dir':str(tmp_path/'history')},['client'])
    monkeypatch.setattr(service,'process',lambda r: {'content':'Synthetic','workflow':r.workflow})
    request={'workflow':'add_reference','text':'HC 230 mm','modality':'OBSTETRIC ULTRASOUND',
             'reference_context':{'ga_days':171,'singleton':True}}
    assert host.process('client',request)['content']=='Synthetic'
    request['reference_context']['normal_hc']=999
    with pytest.raises(hosting.RequestFailed) as error:
        host.process('client',request)
    assert error.value.status==422


@pytest.mark.parametrize('quote', ['EF 50-55%', 'EF >50%', 'EF ~50%'])
def test_bounds_do_not_become_exact_values(quote):
    with pytest.raises(ValueError):
        validate_evidence(Measurement(parameter='LVEF',value=50,unit='%',evidence=quote),quote)


def test_negative_unsupported_strain_is_retained_without_aborting_report():
    m=Measurement(parameter='GLS',value=-18,unit='%',evidence='GLS -18%')
    validate_evidence(m,'GLS -18%')
    row=compare(m,ReferenceContext(age_years=50),'ECHOCARDIOGRAPHY')
    assert row['value']=='-18 %'
    assert row['comparison'].startswith('Unavailable')
