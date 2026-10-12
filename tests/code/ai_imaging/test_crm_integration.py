"""Synthetic guards for the hosted reception CRM boundary."""
import pytest


def test_owned_worker_preserves_tools_and_rejects_untrusted_loopback(tmp_path):
    import json
    import subprocess
    import sys
    import time
    from pathlib import Path
    import requests
    import psutil
    root = Path('modules/ai_imaging/eagle_eye_remote/crm').resolve()
    (tmp_path / 'server.json').write_text(json.dumps({'center': 'SYNTHETIC',
        'session_secret': 'synthetic-session-secret-for-isolated-test', 'data_root': str(tmp_path / 'data')}))
    (tmp_path / 'roles.json').write_text(json.dumps({'users': {}, 'roles': {}}))
    script = "import sys; sys.path.insert(0, sys.argv[1]); from reception_crm import local_host; local_host.resolve_reception_host=lambda port:'127.0.0.1'; from modules.ai_imaging.eagle_eye_remote.crm.worker import main; main()"
    process = subprocess.Popen([sys.executable, '-c', script, str(root / 'vendor')],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    http = requests.Session()
    http.trust_env = False
    try:
        process.stdin.write(json.dumps({'config_dir': str(tmp_path), 'ai_config_dir': str(tmp_path),
                                       'token': 'synthetic-internal-worker-token'}) + '\n')
        process.stdin.close()
        ready = tmp_path / 'worker-ready.json'
        deadline = time.monotonic() + 15
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        assert ready.exists(), process.stderr.read() if process.poll() is not None else 'CRM readiness timeout'
        state = json.loads(ready.read_text())
        assert state['pid'] == process.pid or process.pid in [p.pid for p in psutil.Process(state['pid']).parents()]
        url = f"http://127.0.0.1:{state['port']}/api/health"
        assert http.get(url, timeout=3).status_code == 401
        health = http.get(url, headers={'X-Eagle-Internal': 'synthetic-internal-worker-token'}, timeout=3)
        assert health.status_code == 200
        assert health.json()['tool_count'] == 39
        assert health.json()['writes_enabled'] is False
        assert health.json()['llm_configured'] is True
    finally:
        http.close()
        if process.poll() is None:
            for child in psutil.Process(process.pid).children(recursive=True):
                child.kill()
            process.kill()
        process.wait(timeout=5)


def test_host_owns_redirected_interpreter_and_closes_it(tmp_path, monkeypatch):
    import json
    import subprocess
    import sys
    import threading
    from pathlib import Path
    from types import SimpleNamespace
    import psutil
    from modules.ai_imaging.eagle_eye_remote.crm.hosting import CRM
    root = Path('modules/ai_imaging/eagle_eye_remote/crm').resolve()
    (tmp_path / 'server.json').write_text(json.dumps({'center': 'SYNTHETIC',
        'session_secret': 'synthetic-owned-worker-secret', 'data_root': str(tmp_path / 'data')}))
    (tmp_path / 'roles.json').write_text(json.dumps({'users': {}, 'roles': {}}))
    popen = subprocess.Popen
    def isolated(command, **options):
        script = "import sys; sys.path.insert(0, sys.argv[1]); from reception_crm import local_host; local_host.resolve_reception_host=lambda port:'127.0.0.1'; from modules.ai_imaging.eagle_eye_remote.crm.worker import main; main()"
        return popen([sys.executable, '-c', script, str(root / 'vendor')], **options)
    monkeypatch.setattr(subprocess, 'Popen', isolated)
    crm = CRM({'config_dir': str(tmp_path)},
        SimpleNamespace(directory=tmp_path, slots=threading.BoundedSemaphore(1)), {'paired': ''})
    pid = None
    try:
        status, health = crm.process_request('paired', 'GET', '/v1/crm/health', None)
        assert status == 200 and health['tool_count'] == 39
        assert 'snapshots' not in health and 'center_catalog' not in health
        pid = json.loads((tmp_path / 'worker-ready.json').read_text())['pid']
        assert psutil.pid_exists(pid)
    finally:
        crm.close()
    assert not psutil.pid_exists(pid)


def test_frozen_definitions_compile_crm_and_preserve_prompt_data():
    from pathlib import Path
    from builder.spec.spec_utils import collect_tree_datas
    root = Path('modules/ai_imaging/eagle_eye_remote/crm/vendor/reception_crm')
    datas = collect_tree_datas(root.as_posix(), 'reception_crm')
    assert sum('/prompts/' in source.replace('\\', '/') for source, _ in datas) == 10
    assert all(not target.startswith('modules/') for _, target in datas)
    spec = Path('builder/spec/appA_workstation.spec').read_text()
    assert 'collect_submodules("reception_crm")' in spec
    compiler = Path('builder nuitka/build_nuitka_release.py').read_text()
    assert '--include-package=reception_crm' in compiler
    assert 'env["PYTHONPATH"] = vendor' in compiler


def test_crm_host_is_optional_and_has_bounded_admission():
    from modules.ai_imaging.eagle_eye_remote.crm.hosting import CRM
    with pytest.raises(ValueError):
        CRM({'max_requests': 99}, None, {})


def test_crm_routes_do_not_expose_legacy_dispatch_or_confirmation():
    from modules.ai_imaging.eagle_eye_remote.crm.hosting import route
    assert route('POST', '/v1/crm/command') == '/api/agent/command'
    assert route('POST', '/v1/crm/session') == '/api/session'
    for path in ('/v1/crm/dispatch', '/v1/crm/confirm', '/v1/crm/settings'):
        with pytest.raises(ValueError):
            route('POST', path)


def test_crm_queries_cannot_bypass_command_license_mode_or_ai_admission():
    from modules.ai_imaging.eagle_eye_remote.crm.hosting import route
    for path in ('/v1/crm/command?mode=executive', '/v1/crm/session?x=1',
                 '/v1/crm/conversations/extra/create', '/v1/crm/progress?unexpected=1'):
        with pytest.raises(ValueError):
            route('GET' if '/progress' in path else 'POST', path)
    assert route('GET', '/v1/crm/progress?conversationId=synthetic') == '/api/agent/progress?conversationId=synthetic'


def test_crm_source_receipt_preserves_all_prompts():
    import hashlib
    import json
    from pathlib import Path
    root = Path('modules/ai_imaging/eagle_eye_remote/crm')
    receipt = json.loads((root / 'migration_manifest.json').read_text())
    assert receipt['version'] == '1.32.6'
    prompts = {p: h for p, h in receipt['files'].items() if '/prompts/' in p}
    assert len(prompts) == 10
    for path, digest in prompts.items():
        assert hashlib.sha256((root / 'vendor' / path).read_bytes()).hexdigest() == digest


def test_crm_http_requires_pairing_and_license(human_access):
    import threading
    import requests
    from http.server import ThreadingHTTPServer
    from modules.ai_imaging.eagle_eye_remote.server import handler
    class Hosted:
        capabilities = {'version': 1}
        calls = []
        def process_request(self, *args, **kwargs):
            self.calls.append(args)
            return 200, {'ok': True}
    crm = Hosted()
    server = ThreadingHTTPServer(('127.0.0.1', 0),
        handler(type('SyntheticJobs', (), {})(), {'paired': 'x' * 32}, crm=crm, license_guard=lambda: False,user_authority=human_access))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    http = requests.Session()
    http.trust_env = False
    url = f'http://127.0.0.1:{server.server_port}/v1/crm/command'
    try:
        assert http.post(url, json={'text': 'synthetic'}, timeout=3).status_code == 401
        assert http.post(url, json={'text': 'synthetic'},
                         headers={'Authorization': 'Bearer ' + 'x' * 32}, timeout=3).status_code == 401
        from tests.code.ai_imaging.human_access_fixture import session_headers
        headers=session_headers(url.removesuffix('/v1/crm/command'),'x'*32)
        assert http.post(url,json={'text':'synthetic'},headers=headers,timeout=3).status_code==403
        assert crm.calls == []
    finally:
        http.close()
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_crm_routes_share_pairing_and_forward_user_session(human_access):
    import threading
    import requests
    from http.server import ThreadingHTTPServer
    from modules.ai_imaging.eagle_eye_remote.server import handler
    class Hosted:
        capabilities = {'version': 1}
        def process_request(self, owner, method, path, body, session, *, principal):
            assert human_access.store.user(principal)['username']=='synthetic-user'
            import hashlib
            assert (owner, method, path, session) == ('human:' + hashlib.sha256(principal.encode()).hexdigest(), 'POST', '/v1/crm/command', 'user-session')
            assert body == {'text': 'synthetic'}
            return 200, {'success': True}
    server = ThreadingHTTPServer(('127.0.0.1', 0),
        handler(type('SyntheticJobs', (), {})(), {'paired': 'x' * 32}, crm=Hosted(), license_guard=lambda: True,user_authority=human_access))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    http = requests.Session()
    http.trust_env = False
    try:
        from tests.code.ai_imaging.human_access_fixture import session_headers
        headers=session_headers(f'http://127.0.0.1:{server.server_port}','x'*32)
        result = http.post(f'http://127.0.0.1:{server.server_port}/v1/crm/command',
            json={'text': 'synthetic'}, headers={**headers,
            'X-CRM-Session': 'user-session'}, timeout=3)
        assert result.status_code == 200 and result.json()['success']
    finally:
        http.close()
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_foreign_crm_session_cannot_launch_worker(tmp_path):
    import json
    from types import SimpleNamespace
    from modules.ai_imaging.eagle_eye_remote.crm.hosting import CRM
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    (tmp_path / 'server.json').write_text('{}')
    (tmp_path / 'roles.json').write_text('{}')
    crm = CRM({'config_dir': str(tmp_path)}, SimpleNamespace(), {'one': '', 'two': ''})
    crm.sessions['other'] = 'one'
    with pytest.raises(RequestFailed) as error:
        crm.process_request('two', 'POST', '/v1/crm/command', {'text': 'synthetic'}, 'other')
    assert error.value.status == 401 and crm.process is None


@pytest.mark.parametrize('principal',['synthetic-other-person',None])
def test_crm_session_cannot_cross_humans_on_same_paired_device(tmp_path,monkeypatch,principal):
    import hashlib
    from types import SimpleNamespace
    from modules.ai_imaging.eagle_eye_remote.crm.hosting import CRM
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    (tmp_path/'server.json').write_text('{}');(tmp_path/'roles.json').write_text('{}')
    crm=CRM({'config_dir':str(tmp_path)},SimpleNamespace(),{'synthetic-device':''})
    token='synthetic-reception-session'
    crm.sessions[hashlib.sha256(token.encode()).hexdigest()]=('synthetic-device','synthetic-person')
    monkeypatch.setattr(crm,'_start',lambda:pytest.fail('Cross-user request must not launch a worker'))
    with pytest.raises(RequestFailed) as caught:
        crm.process_request('synthetic-device','GET','/v1/crm/tools',None,token,principal=principal)
    assert caught.value.status==401 and crm.process is None


def test_crm_provider_uses_eagle_context_and_server_model(monkeypatch, tmp_path):
    from contextlib import nullcontext
    from modules.ai_imaging.eagle_eye_remote.crm import provider
    monkeypatch.setenv('CRM_EAGLE_CONFIG', str(tmp_path))
    monkeypatch.setattr(provider.runtime, 'configuration', lambda directory: nullcontext())
    monkeypatch.setattr(provider.runtime, 'request_context', lambda options: nullcontext())
    monkeypatch.setattr(provider.runtime, 'current_settings', lambda: {'crm_model': 'server-selected'})
    def completion(**kwargs):
        assert kwargs['model'] == 'server-selected'
        assert kwargs['messages'] == [{'role': 'user', 'content': 'synthetic'}]
        return {'content': 'ok', 'usage': {}, 'raw': {'private': 'not-forwarded'}}
    monkeypatch.setattr(provider.llm_client, 'chat_completion', completion)
    result = provider.completion([{'role': 'user', 'content': 'synthetic'}], model='client-selected')
    assert result['provider'] == 'eagle_eye' and 'raw' not in result


_APP = None


def test_crm_ui_is_lazy_in_both_roles(monkeypatch):
    from PySide6.QtWidgets import QApplication, QWidget
    from PacsClient.pacs.workstation_ui.settings_ui import settings_ui
    global _APP
    _APP = app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_ui, 'is_module_enabled', lambda _: False)
    for role in ('standard', 'server'):
        monkeypatch.setenv('AIPACS_EAGLE_EYE_ROLE', role)
        widget = settings_ui.SettingsTabWidget()
        monkeypatch.setattr(widget, '_create_crm_settings', lambda: QWidget())
        group = widget._create_ai_group()
        assert [group.tabText(i) for i in range(group.count())] == ['Eagle Eye', 'Agent', 'CRM'] + (['Users'] if role == 'server' else []) + ['Connection']
        assert not hasattr(widget, 'crm_settings')
        group.deleteLater()
        widget.deleteLater()
        app.processEvents()
