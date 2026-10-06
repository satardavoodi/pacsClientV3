"""Synthetic guards for the opt-in Razi server report route."""
import json
import pytest
from modules.EchoMind import remote_backend as remote


@pytest.fixture
def transport(monkeypatch, tmp_path):
    from modules.EchoMind import normal_templates as nt
    monkeypatch.setattr(nt, 'library_path', lambda: str(tmp_path / 'templates.json'))
    monkeypatch.setattr(remote, 'selected', lambda: True)
    from modules.ai_imaging.eagle_eye_remote import client
    calls = []
    class Client:
        def open(self, path, body=None, method=None, *, timeout=30):
            import io
            calls.append((path, {'json': body, 'timeout': timeout}))
            return io.BytesIO(json.dumps({'content': '{"Findings":"Synthetic result."}', 'usage': {}}).encode())
    monkeypatch.setattr(client, 'Client', Client)
    return calls


def test_turbo_sends_context_without_prompt_model_or_provider_secret(transport):
    remote.reporter('Synthetic dictation', 'MRI', 'Template.', workflow='turbo',
                    study_profile={'regions':['brain'], 'contrast':'without'},
                    CENTER_Key='synthetic-local-code', model='ignored-local-model')
    url, args = transport[0]
    assert url == '/v1/echomind/process'
    assert args['json'] == {'text':'Synthetic dictation', 'modality':'MRI',
        'normal_template':'Template.', 'workflow':'turbo', 'provider':'company',
        'response_format':'json', 'study_profile':{'regions':['brain'], 'contrast':'without'}}
    assert args['timeout'] == 360
    assert 'synthetic-local-code' not in json.dumps(args)


def test_missing_eagle_eye_pairing_fails_before_network(transport, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import client
    monkeypatch.setattr(client, 'Client', lambda: (_ for _ in ()).throw(ValueError('Private configuration detail')))
    with pytest.raises(remote.RemoteError, match='Eagle Eye connection'):
        remote.reporter('Synthetic', 'CT')
    assert transport == []


def test_custom_prompt_is_rejected_not_forwarded(transport):
    with pytest.raises(remote.RemoteError):
        remote.reporter('Synthetic', 'CT', system_prompt_override='Private prompt')
    assert transport == []


def test_correction_preserves_report_and_originating_template(transport):
    from modules.EchoMind import normal_templates as nt
    original = '{"Findings":"Original synthetic statement."}'
    template = 'Normal source.' + nt.PERSIAN_REFERENCE_MARKER + 'Source vocabulary.'
    nt.remember_report_template(original, template)
    remote.correction(original, 'Change only the measurement.')
    args = transport[0][1]['json']
    assert args['text'] == original
    assert args['correction_note'] == 'Change only the measurement.'
    assert args['normal_template'] == template


def test_timeout_never_retries_or_leaks_details(transport, monkeypatch):
    def fail(*a, **kw):
        raise OSError('sensitive transport detail')
    class Failing:
        def open(self, *a, **kw):
            transport.append('attempt')
            return fail()
        def close(self): pass
    from modules.ai_imaging.eagle_eye_remote import client
    monkeypatch.setattr(client, 'Client', Failing)
    with pytest.raises(remote.RemoteError) as err:
        remote.reporter('Synthetic', 'CT')
    assert 'sensitive' not in str(err.value)
    assert transport == ['attempt']


def test_profile_adapts_desktop_subtype_and_rejects_prompt_fields(transport):
    remote.reporter('Synthetic', 'CT', workflow='turbo', study_profile={'subtype':'angiography'})
    assert transport[0][1]['json']['study_profile']['subtype'] == ['angiography']
    with pytest.raises(remote.RemoteError):
        remote.reporter('Synthetic', 'CT', study_profile={'system_prompt':'private'})
    assert len(transport) == 1


def test_switching_away_from_pilot_never_sends(transport, monkeypatch):
    monkeypatch.setattr(remote, 'selected', lambda: False)
    with pytest.raises(remote.RemoteError):
        remote.reporter('Synthetic', 'CT')
    assert not transport


def test_ui_turbo_branches_before_building_a_local_prompt():
    import ast
    from pathlib import Path
    source = Path('modules/EchoMind/viewer_chat/ai_chat_pages.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    turbo = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_on_hq_all_modality_clicked')
    worker = next(n for n in ast.walk(turbo) if isinstance(n, ast.FunctionDef) and n.name == 'work')
    branch = next(n for n in worker.body if isinstance(n, ast.If))
    assert ast.unparse(branch.test) == 'remote_backend.selected()'
    assert any(isinstance(n, ast.Return) for n in branch.body)
    assert "workflow='turbo'" in ast.unparse(branch)
    assert 'build_turbo_system_prompt' not in ast.unparse(branch)


def test_each_access_alias_opens_only_its_matching_login_envelope(monkeypatch):
    from dataclasses import asdict
    from modules.EchoMind import center_registry
    from modules.EchoMind.credential_envelope import seal_provider_key
    login = {'username':'synthetic-pilot', 'password':'synthetic-test-password'}
    envelopes = tuple(asdict(seal_provider_key(code, json.dumps(login), 'RAZI_SERVER_LOGIN'))
                      for code in ('synthetic-alias-one', 'synthetic-alias-two'))
    monkeypatch.setattr(center_registry, 'REMOTE_LOGIN_ENVELOPES', envelopes, raising=False)
    for code in ('synthetic-alias-one', 'synthetic-alias-two'):
        assert remote._login_credentials(code) == login
    with pytest.raises(remote.RemoteError):
        remote._login_credentials('synthetic-wrong-alias')


@pytest.mark.parametrize('workflow', ['assistant', 'search'])
def test_reference_workflow_uses_central_server_native_provider(transport, workflow):
    result = getattr(remote, workflow)('Synthetic reference question')
    assert result['content']
    assert len(transport) == 1
    url, args = transport[0]
    assert url == '/v1/echomind/process'
    assert args['json'] == dict(text='Synthetic reference question', provider='aipacs',
                               workflow=workflow, response_format='json')


@pytest.mark.parametrize('workflow', ['assistant', 'search'])
def test_reference_failure_has_no_direct_fallback(transport, monkeypatch, workflow):
    class Unavailable:
        def open(self, *args, **kwargs):
            transport.append('attempt')
            raise OSError('private upstream details')
        def close(self): pass
    from modules.ai_imaging.eagle_eye_remote import client
    monkeypatch.setattr(client, 'Client', Unavailable)
    with pytest.raises(remote.RemoteError) as error:
        getattr(remote, workflow)('Synthetic question')
    assert transport == ['attempt']
    assert 'private' not in str(error.value)


def test_web_search_sends_only_text_and_server_workflow(transport):
    remote.web_search('Synthetic research question')
    assert transport[0][1]['json'] == dict(text='Synthetic research question',
        provider='company', workflow='web_search', response_format='json')


def test_assist_standardization_uses_server_question_workflow(transport):
    remote.standard_assist_search('Synthetic reference question')
    assert transport[0][1]['json']['workflow'] == 'standardize_assist'


def test_web_search_renders_safe_clickable_sources():
    rendered = remote.render_web_search({'Answer': '<script>unsafe</script>',
        'Sources': [{'title': '<ACR>', 'url': 'https://www.acr.org/example'},
                    {'title': 'Unsafe', 'url': 'javascript:alert(1)'}]})
    assert '<script>' not in rendered
    assert 'javascript:' not in rendered
    assert 'href="https://www.acr.org/example"' in rendered
    assert '&lt;ACR&gt;' in rendered


def test_assist_menu_has_three_distinct_routes():
    import ast
    from pathlib import Path
    tree = ast.parse(Path('modules/EchoMind/viewer_chat/ai_chat_pages.py').read_text(encoding='utf-8'))
    menu = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_open_assist_menu')
    items = next(n.value for n in menu.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'items' for t in n.targets))
    assert [(n.elts[0].value, n.elts[1].value) for n in items.elts] == [
        ('Radiopaedia', 'Assistant'), ('Textbook', 'Search'), ('Web Search', 'Web Search')]


@pytest.mark.parametrize('mode,key', [('Assistant', 'assistant_output'), ('Search', 'response')])
def test_reference_ui_worker_routes_remotely_and_preserves_content(monkeypatch, mode, key):
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    tree = ast.parse(Path('modules/EchoMind/viewer_chat/ai_chat_pages.py').read_text(encoding='utf-8'))
    send = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_send_with_mode')
    guard = next(n for n in send.body if isinstance(n, ast.If) and 'remote_route' in ast.unparse(n.test))
    assert not eval(compile(ast.Expression(guard.test), '<guard>', 'eval'), {},
                    dict(remote_route=True, has_images=False, mode=mode))
    assert eval(compile(ast.Expression(guard.test), '<guard>', 'eval'), {},
                dict(remote_route=True, has_images=True, mode=mode))
    branch = next(n for n in send.body if isinstance(n, ast.If) and ast.unparse(n.test) == f"mode == '{mode}'")
    worker = next(n for n in branch.body if isinstance(n, ast.FunctionDef) and n.name == 'work')
    calls = []
    content = {'Summary': 'Synthetic reference', 'Sources': ['Synthetic citation']}
    def request(text):
        calls.append(text)
        return {'content': content, 'usage': {'total_tokens': 7}}
    namespace = dict(remote_route=True, remote_backend=SimpleNamespace(**{mode.lower(): request}),
                     sent_text='Synthetic reference question', reference_text='Synthetic reference question')
    exec(compile(ast.Module(body=[worker], type_ignores=[]), '<worker>', 'exec'), namespace)
    result = namespace['work']()
    assert calls == ['Synthetic reference question']
    assert result[key] == content
    assert result['usage'] == {'total_tokens': 7}
