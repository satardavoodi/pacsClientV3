"""Synthetic current-turn CRM language guards; no provider or clinical reads."""
from pathlib import Path

import pytest


@pytest.fixture
def crm(monkeypatch):
    monkeypatch.syspath_prepend(str(Path('modules/ai_imaging/eagle_eye_remote/crm/vendor').resolve()))
    monkeypatch.setenv('CRM_EAGLE_CONFIG', 'synthetic-private-context')
    from reception_crm.core import orchestrator
    return orchestrator


@pytest.mark.parametrize(('text', 'preference', 'expected'), [
    ('Show the admission summary.', 'fa', 'en'),
    ('گزارش پذیرش را نشان بده', 'en', 'fa'),
    ('Reply in English: گزارش پذیرش', 'fa', 'en'),
    ('Please respond in Persian.', 'en', 'fa'),
    ('12345', 'fa', 'fa'),
    ('', 'en', 'en'),
    ('hello سلام', 'fa', 'fa'),
    ('hello سلام', 'en', 'en'),
    ('Show summary for "نمونه"', 'fa', 'en'),
])
def test_original_turn_language_governs_all_model_stages(crm, monkeypatch, text, preference, expected):
    from modules.ai_imaging.eagle_eye_remote import response_language
    seen = []
    machine = {'action': {'tool': 'daily-summary', 'parameters': {'date': '1405/07/16'}},
               'result': {'count': 12}, 'success': True, 'message': 'Synthetic answer'}
    def run(request, context, registry=None, chat=None, confirmations=None):
        # Analysis payload and history must not replace the original request.
        for content in ['{"patientName":"نمونه","count":12}', 'Write the previous answer']:
            chat([{'role': 'system', 'content': 'Legacy language policy'},
                  {'role': 'user', 'content': content}])
        return machine
    def chat(messages, **kwargs):
        seen.append((response_language.current_reply_language(), messages))
        return {'content': 'synthetic'}
    monkeypatch.setattr(crm, '_handle_command', run)
    result = crm.handle_command(crm.CommandRequest(text=text, language_preference=preference,
        history=[{'role': 'user', 'content': 'Old English request'}]), object(), chat=chat)
    assert len(seen) == 2
    assert all(lang == expected for lang, _ in seen)
    assert all(any(response_language.response_language_instruction(expected) in m['content']
                   for m in messages) for _, messages in seen)
    assert result['action'] == machine['action'] and result['result'] == machine['result']


def test_language_switch_is_per_turn_and_context_is_reset(crm, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import response_language
    seen = []
    def run(*args, **kwargs):
        seen.append(response_language.current_reply_language())
        return {'success': True, 'message': 'Synthetic'}
    monkeypatch.setattr(crm, '_handle_command', run)
    for text in ['گزارش پذیرش', 'Show admissions', 'گزارش بعدی']:
        crm.handle_command(crm.CommandRequest(text, language_preference='en'), object())
    assert seen == ['fa', 'en', 'fa']
    assert response_language.current_reply_language() == 'en'


def test_empty_english_request_has_english_deterministic_error(crm):
    result = crm.handle_command(crm.CommandRequest('', language_preference='en'), object())
    assert result['error']['code'] == 'VALIDATION'
    assert result['message'] == 'Enter a request.'


def test_english_fallback_preserves_machine_values(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.crm.language import render_english_fallback
    data = {'admissions': {'total_receptions': 106, 'unique_patients': 105},
            'period': {'start_jalali': '1405/07/16'}, 'patient_name': 'نمونه'}
    import copy
    before = copy.deepcopy(data)
    rendered = render_english_fallback(data, inherited_day='1405/07/16', snapshot='synthetic-time')
    assert '106' in rendered and '105' in rendered and '1405/07/16' in rendered
    assert 'saved' in rendered.lower() and data == before
    assert 'نمونه' not in rendered  # No arbitrary record text promoted into narrative.


def test_language_preference_is_validated(crm):
    with pytest.raises(ValueError, match='language_preference'):
        crm.handle_command(crm.CommandRequest('Synthetic', language_preference='invalid'), object())


@pytest.mark.parametrize(('text', 'preference', 'reply'), [
    ('Show the admission summary', 'fa', 'There are 12 admissions.'),
    ('گزارش پذیرش را نشان بده', 'en', '۱۲ پذیرش ثبت شده است.'),
    ('Show the admission summary', 'fa', ''),
])
def test_real_command_pipeline_preserves_tool_contract(crm, monkeypatch, tmp_path, text, preference, reply):
    import json
    from reception_crm.core.registry import ToolRegistry
    from reception_crm.core.types import DispatchContext, Principal, ToolDefinition, ToolResult
    registry = ToolRegistry()
    registry.register(ToolDefinition(name='daily-summary', kind='skill',
        handler=lambda args: {'admissions': 12}, safety='read', audit=False,
        input_schema={'type': 'object', 'properties': {'date': {'type': 'string'}}}))
    monkeypatch.setattr(registry, 'list_for', lambda principal: [{
        'name': 'daily-summary', 'description': 'Synthetic summary',
        'inputSchema': {'type': 'object', 'properties': {'date': {'type': 'string'}}}}])
    monkeypatch.setattr(crm.llm_client, 'is_configured', lambda: True)
    monkeypatch.setattr(crm, '_audit', lambda *a, **kw: None)
    monkeypatch.setattr(crm, 'dispatch', lambda call, **kw: ToolResult(True, call.name, {'admissions': 12}))
    outputs = iter([json.dumps({'intent': 'summary', 'requiresClarification': False,
        'clarificationFa': None, 'requiresConfirmation': False, 'confidence': 1,
        'toolCalls': [{'tool': 'daily-summary', 'arguments': {'date': '1405/07/16'}}]}), reply])
    seen = []
    def chat(messages, **kwargs):
        seen.append(messages)
        return {'content': next(outputs), 'usage': {}}
    result = crm.handle_command(crm.CommandRequest(text, language_preference=preference),
        DispatchContext(principal=Principal(user='synthetic', center='SYNTHETIC'),
                        data_root=tmp_path, audit=False), registry=registry, chat=chat)
    assert result['success'] is True and reply in result['message']
    assert result['result'] == {'admissions': 12}
    assert result['action'] == {'tool': 'daily-summary', 'parameters': {'date': '1405/07/16'}}
    assert len(seen) == 2
    if not reply:
        assert '12' in result['message'] and 'Result' in result['display']
        assert not any('\u0600' <= char <= '\u06ff' for char in result['message'])


def test_english_model_response_date_notes_stay_english(crm):
    from modules.ai_imaging.eagle_eye_remote.response_language import request_language
    from reception_crm.core import presentation
    with request_language('Show results', 'fa'):
        display, fallback = presentation.build_display('Synthetic results.', {},
            inherited_day='1405/07/16', session_snapshot_at='synthetic-time')
    assert not fallback and 'Date inherited' in display and 'saved snapshot' in display
    assert not any('\u0600' <= char <= '\u06ff' for char in display)


def test_english_assumed_day_note_and_fallback(crm):
    from modules.ai_imaging.eagle_eye_remote.response_language import request_language
    from reception_crm.core import presentation
    data = {'count': 12, 'date_assumption': {'was_assumed': True, 'day': '1405/07/16'}}
    with request_language('Show results', 'fa'):
        display, _ = presentation.build_display('Synthetic results.', data)
        fallback, used = presentation.build_display('', data)
    assert 'today (1405/07/16)' in display
    assert used and '12' in fallback and '1405/07/16' in fallback


@pytest.mark.parametrize('preference', ['unsupported', [], {}, None, 1])
def test_http_ingress_rejects_invalid_preference_before_execution(crm, preference):
    from reception_crm.adapters.http_api import HttpApiHandler, BadRequest
    class Handler:
        def authenticate(self): return object()
        def read_json(self): return {'text': 'Synthetic', 'language_preference': preference}
        def reject_identity_keys(self, payload): return True
    with pytest.raises(BadRequest, match='language_preference'):
        HttpApiHandler.handle_agent_command(Handler())


@pytest.mark.parametrize('preference', ['fa', 'en', 'absent'])
def test_http_ingress_forwards_preference_without_changing_text(crm, monkeypatch, preference):
    from reception_crm.adapters import http_api
    seen = []
    class Handler:
        def authenticate(self): return object()
        def read_json(self):
            payload = {'text': 'Synthetic current request'}
            if preference != 'absent': payload['language_preference'] = preference
            return payload
        def reject_identity_keys(self, payload): return True
        def context_for(self, principal): return object()
        def respond_json(self, result): pass
    def run(request, **kwargs):
        seen.append(request)
        return {'success': False, 'error': {'code': 'SYNTHETIC'}}
    monkeypatch.setattr(http_api, 'handle_command', run)
    http_api.HttpApiHandler.handle_agent_command(Handler())
    assert seen[0].text == 'Synthetic current request'
    assert seen[0].language_preference == ('en' if preference == 'absent' else preference)


def test_progress_follows_original_request_language(crm, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.response_language import request_language
    from reception_crm.core import progress
    seen = []
    monkeypatch.setattr(progress.board, 'publish', lambda *args: seen.append(args[-1]))
    with request_language('Show summary', 'fa'):
        reporter = progress.Reporter(object(), 'synthetic-conversation')
        reporter.fetched('daily-summary')
    assert seen[0].message_fa == 'Reading daily summary...'
    assert seen[0].sources == ['daily summary']


def test_confirmation_narratives_do_not_change_steps_or_authority(crm, monkeypatch):
    steps = [{'tool': 'appointments.schedule', 'arguments': {'receptionId': 'synthetic'}}]
    machine = {'success': False, 'message': '', 'error': {'code': 'CONFIRMATION_REQUIRED'},
               'requiresUserAction': True, 'userAction': {'steps': steps, 'planId': 'synthetic-plan',
               'summaryFa': '', 'effects': []}}
    monkeypatch.setattr(crm, '_handle_command', lambda *args, **kwargs: machine)
    result = crm.handle_command(crm.CommandRequest('Schedule an appointment', language_preference='fa'), object())
    assert result['userAction']['steps'] == steps
    assert result['userAction']['planId'] == 'synthetic-plan'
    assert result['error']['code'] == 'CONFIRMATION_REQUIRED'
    assert 'approve' in result['userAction']['summaryFa']
