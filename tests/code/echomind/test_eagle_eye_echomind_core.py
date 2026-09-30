"""Headless EchoMind isolation, workflow and prompt parity without live traffic."""
import ast
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading

import pytest

from modules.ai_imaging.eagle_eye_remote.echomind import hosting, runtime, service


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    (tmp_path / 'settings.json').write_text('{}')
    monkeypatch.setattr(service.echomind_http.requests.Session, 'request',
                        lambda *a, **kw: pytest.fail('Live network forbidden'))
    return hosting.EchoMind({'config_dir': str(tmp_path)}, ['first', 'second'])


@pytest.mark.parametrize('field,value', [('model', 'client-choice'), ('system_prompt', 'private'),
    ('api_key', 'fake'), ('url', 'https://untrusted.invalid'), ('provider', 'openai'),
    ('pixels', [1, 2]), ('translate', True)])
def test_caller_cannot_select_credentials_prompts_or_destination(hosted, field, value):
    with pytest.raises(hosting.RequestFailed) as error:
        hosted.process('first', {'text': 'Synthetic.', 'workflow': 'report', field: value})
    assert error.value.status == 422
    assert 'private' not in str(error.value)


@pytest.mark.parametrize('workflow', hosting.WORKFLOWS)
def test_all_declared_workflows_reach_server_dispatch(hosted, monkeypatch, workflow):
    def process(request):
        assert runtime.private_dir() == hosted.directory
        assert request.workflow == workflow
        return {'content': 'Synthetic.', 'workflow': workflow}
    monkeypatch.setattr(service, 'process', process)
    assert hosted.process('first', {'text': 'Synthetic.', 'workflow': workflow})['workflow'] == workflow


def test_server_failure_is_redacted_and_request_slot_is_released(hosted, monkeypatch):
    monkeypatch.setattr(service, 'process', lambda *a: (_ for _ in ()).throw(RuntimeError('private-report-token')))
    for _ in range(3):
        with pytest.raises(hosting.RequestFailed) as error:
            hosted.process('first', {'text': 'Synthetic.'})
        assert error.value.status == 502
        assert 'private-report-token' not in str(error.value)


def test_one_client_cannot_fill_all_worker_slots(hosted, monkeypatch):
    started, release = threading.Event(), threading.Event()
    def process(request):
        if request.text == 'hold':
            started.set()
            assert release.wait(3)
        return {'content': 'Synthetic.'}
    monkeypatch.setattr(service, 'process', process)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(hosted.process, 'first', {'text': 'hold'})
        try:
            assert started.wait(3)
            with pytest.raises(hosting.RequestFailed) as error:
                hosted.process('first', {'text': 'repeat'})
            assert error.value.status == 429
            assert hosted.process('second', {'text': 'independent'})['content']
        finally:
            release.set()
        assert first.result()['content']


def test_request_configuration_and_template_state_are_thread_local():
    barrier = threading.Barrier(2)
    def request(identity):
        with runtime.request_context(base={'api_key': identity}):
            runtime.template_references()['synthetic'] = identity
            barrier.wait(timeout=3)
            return runtime.current_settings()['api_key'], runtime.template_references()['synthetic']
    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(request, ['first', 'second'])) == [('first', 'first'), ('second', 'second')]
    with pytest.raises(RuntimeError):
        runtime.current_settings()


def test_long_prompt_literals_match_current_workstation_source():
    root = Path(__file__).resolve().parents[3]
    core = root / 'modules/ai_imaging/eagle_eye_remote/echomind/core'
    for path in (core / 'viewer_chat').glob('*.py'):
        original = root / 'modules/EchoMind/viewer_chat' / path.name
        if not original.is_file():
            continue
        def literals(source):
            return sorted(n.value for n in ast.walk(ast.parse(source.read_text(encoding='utf-8-sig')))
                          if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) > 1000)
        assert literals(path) == literals(original), path.name


def test_web_research_requires_completed_search_and_trusted_citations():
    from modules.ai_imaging.eagle_eye_remote.echomind import web_search
    with pytest.raises(ValueError):
        web_search.parse_result({'status': 'completed', 'output': []})
    assert not web_search.trusted_url('https://acr.org.evil.invalid/')
    assert web_search.trusted_url('https://www.acr.org/example')


def test_turbo_correction_profile_moves_desktop_modality_to_request(monkeypatch):
    from modules.EchoMind import remote_backend
    monkeypatch.setattr(remote_backend, '_request', lambda *a, **kw: kw)
    monkeypatch.setattr(remote_backend, '_template_for', lambda report: '')
    from modules.EchoMind import normal_templates
    monkeypatch.setattr(normal_templates, 'inherit_report_template', lambda original, value: value)
    value = remote_backend.correction('Synthetic.', 'Synthetic edit.', turbo=True,
        study_profile={'modality': 'MRI', 'regions': ['knee']})
    assert value['study_profile'] == {'regions': ['knee']}
    assert value['modality'] == 'MRI'


def test_server_turbo_correction_retains_modality_for_region_context(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind import service
    calls = []
    monkeypatch.setattr(service, 'build_turbo_correction_prefix', lambda profile: calls.append(profile) or 'Server frame')
    monkeypatch.setattr(service.company, 'correction', lambda *a, **kw: {'content': 'Synthetic result'})
    request = service.ProcessRequest(text='Synthetic report', workflow='correction',
        correction_note='Synthetic edit', turbo_correction=True, modality='MRI',
        study_profile={'regions': ['knee']})
    service._process(request)
    assert calls[0]['modality'] == 'MRI'
    assert calls[0]['regions'] == ['knee']


def test_template_organization_uses_server_and_preserves_source_wording(monkeypatch):
    from modules.EchoMind import reception_templates, remote_backend
    calls = []
    monkeypatch.setattr(remote_backend, 'selected', lambda: True)
    def request(payload):
        calls.append(payload)
        return {'groups': [{'kind': 'normal_candidate', 'ids': ['L0000'], 'section': 'Synthetic'}]}
    monkeypatch.setattr(remote_backend, 'organize_template_blocks', request)
    result = reception_templates.organize_template({'name': 'Synthetic template', 'text': 'Source wording.'})
    assert result['proposed_text'] == 'Synthetic:\nSource wording.'
    assert calls[0]['blocks'] == [{'id': 'L0000', 'text': 'Source wording.'}]


def test_template_languages_use_server_without_a_client_prompt(monkeypatch):
    from modules.EchoMind import reception_templates, remote_backend
    monkeypatch.setattr(remote_backend, 'selected', lambda: True)
    monkeypatch.setattr(remote_backend, 'prepare_template_languages', lambda text: {'en': text, 'fa': 'Synthetic counterpart.'})
    assert reception_templates.prepare_template_languages('Source wording.')['en'] == 'Source wording.'
