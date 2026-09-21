"""Linked language versions and report-bound translation references (synthetic)."""
import pytest
from modules.EchoMind import normal_templates as nt, reception_templates as rt


def test_linked_versions_survive_library_reload_and_edits_invalidate_them(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, 'library_path', lambda: str(tmp_path/'library.json'))
    rec, _ = nt.normalize_record({'Name':'Synthetic', 'Html':'Original wording.',
        'translations':{'en':'Original wording.', 'fa':'Source vocabulary.',
                        'source_hash':nt.text_digest('Original wording.')}})
    assert nt.save_library([rec])
    saved = nt.load_library()[0]
    assert nt.template_body_text(saved, 'fa') == 'Source vocabulary.'
    saved['text'] = 'Changed wording.'
    assert nt.template_body_text(saved, 'fa') == 'Changed wording.'


def test_reference_is_bound_to_report_and_ambiguous_match_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, 'library_path', lambda: str(tmp_path/'library.json'))
    bundle = 'Normal wording.' + nt.PERSIAN_REFERENCE_MARKER + 'Original vocabulary.'
    report = '{"Normal Findings":"Normal wording."}'
    nt.remember_report_template(report, bundle)
    assert nt.report_template_reference('{ "Normal Findings": "Normal wording." }')['fa'] == 'Original vocabulary.'
    assert nt.report_template_reference('{"Normal Findings":"Different report."}') == {}
    nt.remember_report_template(report, 'Other wording.' + nt.PERSIAN_REFERENCE_MARKER + 'Other vocabulary.')
    assert nt.report_template_reference(report) == {}


def test_no_template_report_cannot_inherit_a_past_template(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, 'library_path', lambda: str(tmp_path/'library.json'))
    report = '{"Normal Findings":"Normal wording."}'
    nt.remember_report_template(report, 'Normal wording.' + nt.PERSIAN_REFERENCE_MARKER + 'Source vocabulary.')
    nt.remember_report_template(report, '')
    assert nt.report_template_reference(report) == {}


def test_corrected_report_inherits_only_its_originating_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, 'library_path', lambda: str(tmp_path/'library.json'))
    before = '{"Findings":"Original finding."}'
    after = {'content': '{"Findings":"Corrected finding."}'}
    nt.remember_report_template(before, 'Normal statement.' + nt.PERSIAN_REFERENCE_MARKER + 'Source vocabulary.')
    assert nt.inherit_report_template(before, after) is after
    assert nt.report_template_reference(after['content']) == nt.report_template_reference(before)


def test_exact_reuse_does_not_restore_deleted_or_narrowed_normal_clauses():
    import json
    ref = {'en':'Both cortices are normal.\nNo hydronephrosis.',
           'fa':'Authored paired statement.\nAuthored negative statement.'}
    report = {'Normal Findings':'No hydronephrosis.', 'Other':'Right cortex is normal.'}
    translated = {'Normal Findings':'Reworded negative.', 'Other':'Translated right-only finding.'}
    result = json.loads(nt.reuse_persian_template_wording(json.dumps(report), json.dumps(translated), ref))
    assert result['Normal Findings'] == 'Authored negative statement.'
    assert result['Other'] == 'Translated right-only finding.'
    assert 'Authored paired statement.' not in json.dumps(result)


def test_translation_rejects_changed_measurement_or_missing_lines():
    def bad(payload):
        return {'lines':[{'id':p['id'],'text':p['text'].replace('74','24')} for p in payload['lines']]}
    with pytest.raises(rt.TemplateError):
        rt.prepare_template_languages('Uterus: 74 x 34 mm.', complete=bad)
    with pytest.raises(rt.TemplateError):
        rt.prepare_template_languages('First line.\nSecond line.', complete=lambda p:{'lines':[]})


def test_source_language_and_boundary_markers_are_preserved():
    source = 'Code name: "Example"\n===== BEGIN TEMPLATE_FIELDS =====\nLength: ___ mm.\n===== END TEMPLATE_FIELDS ====='
    pair = rt.prepare_template_languages(source, complete=lambda p:{'lines':[
        {'id':line['id'],'text':line['text']} for line in p['lines']]})
    assert pair['en'] == source
    assert pair['source_hash'] == nt.text_digest(source)
    assert 'Code name: "Example"' in pair['fa']


@pytest.mark.parametrize('source,replacement', [
    ('Length ___ mm.', 'Length ___ cm.'),
    ('Length .... mm.', 'Length normal mm.'),
    ('Length [value] mm.', 'Length normal mm.'),
])
def test_translation_rejects_unit_and_slot_changes(source, replacement):
    with pytest.raises(rt.TemplateError):
        rt.prepare_template_languages(source, complete=lambda p: {'lines': [
            {'id': p['lines'][0]['id'], 'text': replacement}]})


def test_mixed_source_preserves_authored_persian_register():
    source = 'Corticomedullary differentiation and renal cortical echogenicity ' + '\u0637\u0628\u06cc\u0639\u06cc'
    def translate(payload):
        assert payload['source_language'] == 'fa'
        return {'lines': [{'id': p['id'], 'text': 'Normal differentiation and cortical echogenicity.'}
                          for p in payload['lines']]}
    assert rt.prepare_template_languages(source, complete=translate)['fa'] == source


def test_bilingual_publish_requires_prepared_reviewable_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, 'library_path', lambda: str(tmp_path/'library.json'))
    record, _ = nt.normalize_record({'id':'test', 'Name':'Synthetic', 'Html':'Normal statement.'})
    rt.organize_templates([record], complete=lambda p: {'groups': [
        {'kind':'normal_candidate','section':'Region','ids':['L0000']}]})
    draft = rt.load_organized_templates()[0]
    with pytest.raises(rt.TemplateError, match='Generate and review'):
        rt.save_organized_edit(draft['id'], draft['edited_text'], expected=draft['edited_text'], bilingual=True)
    prepared = rt.prepare_organized_languages(draft['id'], 'Reviewed source.',
        expected=draft['edited_text'], complete=lambda p: {'lines': p['lines']})
    assert nt.load_library() == []
    assert prepared['translations']['en'] == 'Reviewed source.'
    rt.save_organized_edit(draft['id'], 'Reviewed source.', expected=prepared['edited_text'], bilingual=True)
    assert nt.load_library()[0]['translations']['en'] == 'Reviewed source.'


def test_bilingual_reference_is_not_a_second_generation_template():
    from modules.EchoMind.viewer_chat.openai_reporter import build_report_system_prompt
    prompt = build_report_system_prompt('MRI', 'Normal source sentence.' +
                                       nt.PERSIAN_REFERENCE_MARKER + 'Reference-only vocabulary.')
    assert 'Normal source sentence.' in prompt
    assert 'Reference-only vocabulary.' not in prompt


def test_both_translation_backends_receive_bound_reference(monkeypatch):
    from modules.EchoMind.viewer_chat import openai_reporter as company, openai_parallel_backend as direct
    reference = {'en':'Source phrase.', 'fa':'Authored vocabulary.'}
    monkeypatch.setattr(nt, 'report_template_reference', lambda report: reference)
    class Manager:
        def get_center_and_gapgpt_key(self):
            return 'synthetic', 'test-only-credential'
    monkeypatch.setattr(company.Manage, 'instance', lambda: Manager())
    monkeypatch.setattr(company, '_log_usage_safe', lambda *a: None)
    calls = []
    class Response:
        status_code = 200
        def json(self):
            return {'choices':[{'message':{'content':'{}'}}]}
    def post(url, **kwargs):
        calls.append(kwargs['json']['messages'][0]['content'])
        return Response()
    monkeypatch.setattr(company.echomind_http, 'post', post)
    monkeypatch.setattr(direct, '_call', lambda **kw: (calls.append(kw['system_prompt']) or {'content':'{}'}))
    company.translate_report('{}')
    direct.translate_report('{}')
    for prompt in calls:
        assert 'Authored vocabulary.' in prompt
        assert 'Never restore a removed' in prompt
        assert 'including Persian medical/anatomical words' in prompt


def test_non_bilingual_edit_drops_outdated_linked_versions(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, 'library_path', lambda: str(tmp_path/'library.json'))
    record, _ = nt.normalize_record({'id':'test', 'Name':'Synthetic', 'Html':'Normal statement.'})
    rt.organize_templates([record], complete=lambda p:{'groups':[
        {'kind':'normal_candidate','section':'Region','ids':['L0000']}]},
        bilingual=True, translate=lambda p:{'lines':p['lines']})
    draft = rt.load_organized_templates()[0]
    rt.save_organized_edit(draft['id'], 'Changed wording.', expected=draft['edited_text'])
    assert 'translations' not in rt.load_organized_templates()[0]
    assert 'translations' not in nt.load_library()[0]
