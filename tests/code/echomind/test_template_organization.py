"""Synthetic organization, preservation, cancellation and publishing guards."""
import copy
import json
import pytest
from modules.EchoMind import normal_templates as nt
from modules.EchoMind import reception_templates as rt


def test_organizer_uses_saved_gapgpt_connection_and_exact_sol_model(monkeypatch):
    from modules.EchoMind.viewer_chat import api_manager, openai_reporter
    calls = []
    class Manager:
        def ensure_detected(self):
            calls.append('saved-connection')
    monkeypatch.setattr(api_manager.Manage, 'instance', lambda: Manager())
    def reporter(**kwargs):
        calls.append(kwargs)
        return {'content': json.dumps({'groups': []})}
    monkeypatch.setattr(openai_reporter, 'reporter', reporter)
    assert rt._organizer_completion({'blocks': []}) == {'groups': []}
    assert calls[0] == 'saved-connection'
    assert calls[1]['model'] == 'gpt-5.6-sol'
    assert calls[1]['system_prompt_override'] == rt._ORGANIZER_PROMPT
    assert calls[1]['modality'] == ''


def test_organizer_provider_failure_has_no_fallback_or_saved_draft(monkeypatch, library):
    from modules.EchoMind.viewer_chat import api_manager, openai_reporter
    calls = []
    class Manager:
        def ensure_detected(self):
            pass
    monkeypatch.setattr(api_manager.Manage, 'instance', lambda: Manager())
    def unavailable(**kwargs):
        calls.append(kwargs['model'])
        raise RuntimeError('Provider unavailable')
    monkeypatch.setattr(openai_reporter, 'reporter', unavailable)
    assert rt.organize_templates([record()])['failed'] == 1
    assert calls == ['gpt-5.6-sol']
    assert rt.load_organized_templates() == []

@pytest.fixture
def library(monkeypatch, tmp_path):
    monkeypatch.setattr(nt, 'library_path', lambda: str(tmp_path / 'library.json'))
    return tmp_path

def record():
    r, _ = nt.normalize_record({'id':'synthetic-source','Name':'MRI sample','Modality':'MRI',
                               'Html':'<p>Normal statement.</p><p>Example abnormality.</p>'})
    return r

def complete(payload):
    return {'groups':[{'section':'Region','kind':'normal_candidate','ids':[payload['blocks'][0]['id']]},
                      {'section':'Review','kind':'pathological_example','ids':[payload['blocks'][1]['id']]}]}

def test_organization_preserves_source_and_excludes_examples(library):
    original = record()
    draft = rt.organize_template(original, complete=complete)
    assert draft['source'] == original
    assert draft['proposed_text'] == 'Region:\nNormal statement.'
    assert sum(len(g['ids']) for g in draft['groups']) == 2
    assert 'Example abnormality.' in draft['source']['html']

@pytest.mark.parametrize('ids', [['L0000'], ['L0000','L0000'], ['L0000','unknown']])
def test_invalid_model_coverage_rejected(library, ids):
    with pytest.raises(rt.TemplateError):
        rt.organize_template(record(), complete=lambda p: {'groups':[{'section':'X','kind':'normal_candidate','ids':ids}]})

def test_drafts_do_not_enter_library_until_published_and_retries_preserve_edits(library):
    r=record(); calls=[]
    def model(p):calls.append(1);return complete(p)
    assert rt.organize_templates([r], complete=model)['saved'] == 1
    assert nt.load_library() == []
    draft=rt.load_organized_templates()[0]
    records=rt.save_organized_edit(draft['id'], 'Final physician wording.', expected=draft['edited_text'])
    assert nt.template_body_text(records[0]) == 'Final physician wording.'
    result=rt.organize_templates([r], complete=model)
    assert result['cached']==1 and len(calls)==1
    assert rt.load_organized_templates()[0]['edited_text']=='Final physician wording.'
    assert nt.template_body_text(nt.load_library()[0])=='Final physician wording.'

def test_cancel_during_model_discards_pending_result(library):
    state=[]
    def model(p):state.append(1);return complete(p)
    result=rt.organize_templates([record()], complete=model, cancelled=lambda:bool(state))
    assert result['cancelled'] and not rt.load_organized_templates()

def test_changed_connection_discards_result(library):
    state=[]
    def model(p):state.append(1);return complete(p)
    result=rt.organize_templates([record()], complete=model, still_current=lambda:not state)
    assert result['cancelled'] and not rt.load_organized_templates()

def test_failed_item_does_not_discard_successes(library):
    a=record();b=copy.deepcopy(a);b['id']='second'
    def model(p):
        if p['name']=='bad':raise RuntimeError('sensitive remote body')
        return complete(p)
    b['name']='bad'
    result=rt.organize_templates([a,b],complete=model)
    assert result['saved']==1 and result['failed']==1
    assert len(rt.load_organized_templates())==1

def test_table_and_hex_entities_keep_boundaries():
    assert nt.html_to_text('<table><tr><td>A</td><td>B</td></tr></table>')=='A\tB'
    assert nt.html_to_text('<p>&#x2264; 5</p>')=='\u2264 5'

def test_stale_edit_cannot_replace_newer_text_and_name_edit_survives(library):
    original=record()
    rt.organize_templates([original],complete=complete)
    draft=rt.load_organized_templates()[0]
    records=rt.save_organized_edit(draft['id'],'First edit.',expected=draft['edited_text'])
    records[0]['name']='Physician renamed template'
    assert nt.save_library(records)
    with pytest.raises(rt.TemplateError):
        rt.save_organized_edit(draft['id'],'Stale edit.',expected=draft['edited_text'])
    records=rt.save_organized_edit(draft['id'],'Second edit.',expected='First edit.')
    assert records[0]['name']=='Physician renamed template'
    assert rt.load_organized_templates()[0]['source']==original


def test_cancel_close_retains_completed_items(library):
    a=record();b=copy.deepcopy(a);b['id']='second'
    state=[]
    result=rt.organize_templates([a,b],complete=complete,cancelled=lambda:bool(state),
                                 progress=lambda *args:state.append(1))
    assert result['cancelled'] and result['saved']==1
    assert len(rt.load_organized_templates())==1


def test_html_decodes_once_and_keeps_inequalities():
    assert nt.html_to_text('<p>&amp;lt; literal</p>')=='&lt; literal'
    assert nt.html_to_text('5 < 6 and 7 > 3')=='5 < 6 and 7 > 3'


def test_named_pathology_code_and_slots_survive_review_publish_reload(library):
    source, _ = nt.normalize_record({'id':'macro-test', 'Name':'Lumbar MRI',
        'Modality':'MRI', 'Html':'<p>Alignment is normal.</p><p>Code: degenerative</p>'
        '<p>Disc desiccation is present.</p><p>Marginal osteophytes are present.</p>'
        '<p>Canal diameter: ___ mm.</p>'})
    def classify(payload):
        return {'groups':[
            {'section':'Spine','kind':'normal_candidate','ids':['L0000']},
            {'section':'Spine','kind':'pathology_code','code_name_id':'L0001',
             'ids':['L0001','L0002','L0003']},
            {'section':'Spine','kind':'placeholder','ids':['L0004']}]}
    assert rt.organize_templates([source], complete=classify)['saved'] == 1
    draft = rt.load_organized_templates()[0]
    assert draft['source'] == source
    assert draft['groups'][1]['code_name'] == 'Code: degenerative'
    text = draft['edited_text']
    assert 'BEGIN ON_REQUEST_PATHOLOGY_CODE' in text
    assert 'Disc desiccation is present.' in text
    assert 'BEGIN TEMPLATE_FIELDS' in text and 'Canal diameter: ___ mm.' in text
    rt.save_organized_edit(draft['id'], text, expected=text)
    assert nt.template_body_text(nt.load_library()[0]) == text


def test_invented_code_name_is_rejected(library):
    with pytest.raises(rt.TemplateError):
        rt.organize_template(record(), complete=lambda p: {'groups':[
            {'section':'Region','kind':'pathology_code','code_name':'Invented shortcut',
             'ids':['L0000','L0001']}]})


def test_code_only_template_retains_label_and_all_sentences(library):
    source = record()
    draft = rt.organize_template(source, complete=lambda p: {'groups':[
        {'section':'Region','kind':'pathology_code','code_name_id':'template_name',
         'ids':['L0000','L0001']}]})
    assert draft['edited_text'].startswith('===== BEGIN ON_REQUEST_PATHOLOGY_CODE')
    assert draft['groups'][0]['code_name'] == source['name']
    assert 'Normal statement.' in draft['edited_text']
    assert 'Example abnormality.' in draft['edited_text']


def test_code_cannot_borrow_a_label_outside_its_group(library):
    with pytest.raises(rt.TemplateError):
        rt.organize_template(record(), complete=lambda p: {'groups':[
            {'section':'Region','kind':'normal_candidate','ids':['L0000']},
            {'section':'Region','kind':'pathology_code','code_name_id':'L0000',
             'ids':['L0001']}]})


def test_mammography_choices_are_preserved_as_conditional_not_normals(library):
    source, _ = nt.normalize_record({'id':'density-options','Name':'Synthetic mammography',
        'Modality':'MAMOGRAPHY', 'Html':'<p>BC: A (Almost entirely fatty.)</p>'
        '<p>BC: B (Scattered fibroglandular density.)</p>'
        '<p>BC: C (Heterogeneously dense.)</p><p>BC: D (Extremely dense.)</p>'})
    draft = rt.organize_template(source, complete=lambda p: {'groups':[
        {'section':'Breast composition','kind':'placeholder',
         'ids':['L0000','L0001','L0002','L0003']}]})
    assert draft['edited_text'].startswith('===== BEGIN TEMPLATE_OPTIONS')
    assert all(b['text'] in draft['edited_text'] for b in draft['blocks'])
    assert all(g['kind'] != 'normal_candidate' for g in draft['groups'])


def test_assessment_option_cannot_become_default_normal_even_if_model_mislabels_it(library):
    source, _ = nt.normalize_record({'id':'assessment','Name':'Synthetic mammography',
        'Html':'<p>BI-RADS: 1</p><p>Negative for malignancy.</p>'})
    draft = rt.organize_template(source, complete=lambda p: {'groups':[
        {'section':'Assessment','kind':'normal_candidate','ids':['L0000','L0001']}]})
    assert draft['groups'][0]['kind'] == 'template_option'
    assert draft['edited_text'].startswith('===== BEGIN TEMPLATE_OPTIONS')


def test_context_choice_keeps_parent_code_and_numbered_options(library):
    source, _ = nt.normalize_record({'id':'context','Name':'Synthetic mammography',
        'Html':'<p>FL:</p><p>1- First screening examination.</p>'
               '<p>2- Prior examination is unavailable.</p>'})
    draft = rt.organize_template(source, complete=lambda p: {'groups':[
        {'section':'History','kind':'template_option','ids':['L0000','L0001','L0002']}]})
    assert all(b['text'] in draft['edited_text'] for b in draft['blocks'])
    assert draft['edited_text'].startswith('===== BEGIN TEMPLATE_OPTIONS')
