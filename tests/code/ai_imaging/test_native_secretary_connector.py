"""Synthetic SCM and GUI lifecycle qualification; no service mutation."""
from pathlib import Path
import asyncio
import threading
import json
import pytest

from modules.ai_imaging.eagle_eye_remote import secretary_native_connector as bridge


def test_preparation_diagnostic_never_exposes_exception_content():
    def fail():
        raise PermissionError('SYNTHETIC_PRIVATE_CONTENT')
    with pytest.raises(bridge.AttachmentFailure) as caught:
        bridge._prepare_step('service_verification', fail)
    assert caught.value.stage == 'service_verification'
    assert caught.value.category == 'access_denied'
    assert 'SYNTHETIC_PRIVATE_CONTENT' not in str(caught.value)


def test_lifecycle_snapshot_is_bounded_fixed_fields():
    attachment = bridge.Attachment()
    snapshot = attachment.diagnostics()
    assert snapshot == {'stage':'scheduled','category':'none','closed':False}
    attachment.failure_stage = 'SYNTHETIC_PRIVATE_CONTENT'
    attachment.failure_category = 'SYNTHETIC_PRIVATE_CONTENT'
    assert attachment.diagnostics() == {'stage':'unknown','category':'unknown','closed':False}


def test_nested_pipe_diagnostic_strips_untrusted_fields():
    value = bridge.safe_lifecycle({'stage':'pipe_thread_stopped','category':'runtime',
        'pipe': {'stage':'receive','category':'filesystem','acknowledged':True,
                 'session':'SYNTHETIC_PRIVATE_CONTENT'}})
    assert value['pipe'] == {'stage':'receive','category':'filesystem','acknowledged':True}
    assert 'SYNTHETIC_PRIVATE_CONTENT' not in str(value)
    assert bridge.safe_lifecycle({'pipe':{'stage':[], 'category':{}, 'acknowledged':1}})['pipe'] == {
        'stage':'unknown','category':'unknown','acknowledged':False}


@pytest.mark.parametrize('error,category', [(TimeoutError('private'),'timeout'),
    (OSError('private'),'filesystem'), (ValueError('private'),'invalid_state'),
    (RuntimeError('private'),'runtime'), (asyncio.CancelledError(),'cancelled')])
def test_diagnostic_categories_are_fixed(error,category):
    assert bridge._failure_category(error)==category


def fixtures():
    executable = str(Path('synthetic-python.exe').resolve())
    parent = dict(pid=100, ppid=1, exe=executable, cmdline=[executable, 'service-entry', 'config'],
                  sid='S-1-5-19', created=10)
    child = dict(pid=101, ppid=100, exe=executable, cmdline=[executable, 'child-entry', 'config'],
                 sid='S-1-5-19', created=11)
    state = dict(pid=100, owned=True, running=True)
    return executable, parent, child, state


def test_exact_owned_scm_child_is_attested():
    exe, parent, child, state = fixtures()
    assert bridge.attest_process(101, lambda: dict(state), lambda pid: {100: parent, 101: child}[pid],
                                 exe, parent['cmdline'], child['cmdline'])


def test_similar_process_name_wrong_executable_is_rejected():
    exe, parent, child, state = fixtures()
    child['exe'] = str(Path('untrusted/synthetic-python.exe').resolve())
    assert not bridge.attest_process(101, lambda: dict(state), lambda pid: {100: parent, 101: child}[pid],
                                     exe, parent['cmdline'], child['cmdline'])


def test_other_account_wrong_parent_or_reused_pid_is_rejected():
    exe, parent, original, state = fixtures()
    for delta in ({'sid': 'S-1-5-21-1'}, {'ppid': 99}, {'created': 9}, {'cmdline': [exe, 'other-entry']}):
        child = dict(original, **delta)
        assert not bridge.attest_process(101, lambda: dict(state), lambda pid: {100: parent, 101: child}[pid],
                                         exe, parent['cmdline'], original['cmdline'])


def test_scm_stopped_unowned_or_changed_mid_attestation_is_rejected():
    exe, parent, child, state = fixtures()
    for delta in ({'running': False}, {'owned': False}, {'pid': 0}):
        assert not bridge.attest_process(101, lambda: dict(state, **delta), lambda pid: {100: parent, 101: child}[pid],
                                         exe, parent['cmdline'], child['cmdline'])
    samples = iter([state, dict(state, pid=102)])
    assert not bridge.attest_process(101, lambda: next(samples), lambda pid: {100: parent, 101: child}[pid],
                                     exe, parent['cmdline'], child['cmdline'])


def test_close_attachment_invalidates_remote_without_stopping_native_brain():
    class Runtime:
        closed = False
        def close(self):
            self.closed = True
    class Connector:
        closed = False
        def close(self):
            self.closed = True
    runtime, connector = Runtime(), Connector()
    attachment = bridge.Attachment()
    attachment.runtime, attachment.connector = runtime, connector
    attachment.close()
    assert runtime.closed and connector.closed
    assert attachment.closed


def test_cross_session_access_denied_fails_closed():
    exe, parent, child, state = fixtures()
    def denied(pid):
        raise PermissionError('Synthetic process access denial')
    assert not bridge.attest_process(101, lambda: state, denied,
                                    exe, parent['cmdline'], child['cmdline'])


def test_client_widget_never_attaches_native_server(monkeypatch):
    monkeypatch.setenv('AIPACS_EAGLE_EYE_ROLE', 'standard')
    class Widget:
        _secretary_orchestrator = object()
    assert bridge.schedule_widget(Widget()) is None


def test_preparation_runs_on_worker_and_runtime_lifecycle_on_gui_loop(monkeypatch):
    import builtins
    original_import = builtins.__import__
    def no_audio_import(name, *args, **kwargs):
        if name == 'sounddevice':
            raise RuntimeError('Synthetic headless PortAudio initialization is unavailable')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', no_audio_import)
    from modules.ai_imaging.eagle_eye_remote import user_session, secretary_pipe
    import sys
    from types import ModuleType
    gui_thread = threading.get_ident()
    calls = []
    client = object()
    def prepare():
        assert threading.get_ident() != gui_thread
        return client, 'synthetic', 'canonical', (1, 1), lambda pid: True
    class Runtime:
        def __init__(self, widget, getter):
            assert threading.get_ident() == gui_thread
            assert getter() == 'canonical'
            calls.append('created')
        def capture_session(self):
            calls.append('captured')
        def close(self):
            assert threading.get_ident() == gui_thread
            calls.append('runtime_closed')
    class Connector:
        def __init__(self, runtime, token_getter, loop, verifier):
            self.thread = self
        def start(self):
            calls.append('connector_started')
        def is_alive(self):
            return False
        def close(self):
            calls.append('connector_closed')
    monkeypatch.setattr(bridge, '_prepare', prepare)
    monkeypatch.setattr(user_session, 'confirmed_admission', lambda value: {'principal': 'canonical'})
    monkeypatch.setattr(user_session, 'require_generation', lambda value: None)
    # This scheduling guard supplies its own runtime; importing Home here would
    # initialize unrelated GUI/audio dependencies on a headless service host.
    runtime_name = 'PacsClient.pacs.workstation_ui.home_ui.secretary_native_runtime'
    runtime_module = ModuleType(runtime_name)
    runtime_module.NativeSecretaryRuntime = Runtime
    monkeypatch.setitem(sys.modules, runtime_name, runtime_module)
    monkeypatch.setattr(secretary_pipe, 'NativePipeConnector', Connector)
    class Widget:
        _secretary_orchestrator = type('Brain', (), {'memory_store': object()})()
    attachment = bridge.Attachment()
    asyncio.run(attachment.run(Widget()))
    assert calls == ['created', 'captured', 'connector_started', 'connector_closed', 'runtime_closed']
    assert attachment.closed


@pytest.mark.parametrize('existing,invalidated', [(False,False),(True,False),(False,True),(False,'closed'),(False,'failed'),(False,'generation'),(False,'runtime_failed')])
def test_home_readiness_primes_memory_before_native_attachment(monkeypatch, existing, invalidated):
    import ast
    from types import SimpleNamespace
    import sys
    from modules.ai_imaging.eagle_eye_remote import user_session, secretary_pipe
    gui = threading.get_ident()
    calls = []
    admitted = ['owner']
    epoch = [True]
    class Brain:
        _memory_store = None
        @property
        def memory_store(self):
            assert threading.get_ident() != gui
            calls.append('memory')
            if invalidated == 'failed': return None
            self._memory_store = object()
            if invalidated is True: admitted[0] = None
            if invalidated == 'closed': widget._native_secretary_attachment.closed = True
            if invalidated == 'generation': epoch[0] = False
            return self._memory_store
    brain = Brain()
    widget = SimpleNamespace(_secretary_orchestrator=brain if existing else None)
    def create(home_widget):
        assert threading.get_ident() == gui
        assert home_widget is home
        calls.append('construct')
        return brain
    home = SimpleNamespace(secretary_button_widget=widget,command_bus=object())
    tree = ast.parse(Path('PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py').read_text(encoding='utf-8'))
    method = next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_ensure_secretary_runtime')
    entry_scope = {'os':bridge.os}
    exec(compile(ast.Module(body=[method],type_ignores=[]),'<healthy-entry>','exec'),entry_scope)
    monkeypatch.setenv('AIPACS_EAGLE_EYE_ROLE','server')
    monkeypatch.setattr(bridge,'_prepare',lambda:(object(),'synthetic','owner',(1,1),lambda pid:True))
    monkeypatch.setattr(user_session,'confirmed_admission',lambda client:{'principal':admitted[0]})
    def require_generation(value):
        if not epoch[0]: raise ValueError('Synthetic login epoch changed')
    monkeypatch.setattr(user_session,'require_generation',require_generation)
    from modules.EchoMind import secretary_bridge
    monkeypatch.setattr(secretary_bridge,'create_secretary_orchestrator',create)
    class Runtime:
        def __init__(self, value, getter):
            assert threading.get_ident() == gui and brain._memory_store is not None
            calls.append('runtime')
            if invalidated == 'runtime_failed':
                raise RuntimeError('SYNTHETIC_PRIVATE_CONTENT')
        def capture_session(self):pass
        def close(self):pass
    class Connector:
        def __init__(self,*args):self.thread=self; self.polls=0
        def start(self):pass
        def is_alive(self):
            assert not widget._native_secretary_initializing
            assert widget._native_secretary_lifecycle_state == 'attached'
            assert not widget._native_secretary_attachment.closed
            assert entry_scope['_ensure_secretary_runtime'](widget) is True
            self.polls += 1
            calls.append('live_unfenced')
            return self.polls == 1
        def close(self):pass
    name='PacsClient.pacs.workstation_ui.home_ui.secretary_native_runtime'
    monkeypatch.setitem(sys.modules,name,SimpleNamespace(NativeSecretaryRuntime=Runtime))
    monkeypatch.setattr(secretary_pipe,'NativePipeConnector',Connector)
    async def exercise():
        first=bridge.schedule_home(home)
        assert first is not None and bridge.schedule_home(home) is first
        await first.task
    asyncio.run(exercise())
    assert calls.count('construct') == (0 if existing else 1)
    assert calls.count('memory') == 1
    assert calls.count('runtime') == (1 if not invalidated or invalidated == 'runtime_failed' else 0)
    assert calls.count('live_unfenced') == (0 if invalidated else 2)
    assert widget._secretary_orchestrator is brain
    if not invalidated:
        assert widget._native_secretary_attachment.diagnostics() == {
            'stage':'pipe_thread_stopped','category':'runtime','closed':True}
    if invalidated == 'runtime_failed':
        assert widget._native_secretary_attachment.diagnostics() == {
            'stage':'runtime_construction','category':'runtime','closed':True}


def test_home_hook_is_default_server_bus_ready_and_client_is_untouched(monkeypatch):
    from types import SimpleNamespace
    from pathlib import Path
    home = SimpleNamespace(secretary_button_widget=SimpleNamespace(), command_bus=object())
    monkeypatch.setenv('AIPACS_EAGLE_EYE_ROLE','standard')
    assert bridge.schedule_home(home) is None
    monkeypatch.setenv('AIPACS_EAGLE_EYE_ROLE','server')
    assert bridge.schedule_home(SimpleNamespace(command_bus=None)) is None
    source = Path('PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py').read_text(encoding='utf-8')
    assert source.index('self._wire_agent_background_layer()') < source.index('schedule_home(self)')


def test_local_entry_and_memory_label_are_fenced_during_bootstrap():
    import ast
    from types import SimpleNamespace
    tree = ast.parse(Path('PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py').read_text(encoding='utf-8'))
    scope = {'os':bridge.os}
    for name in ('_ensure_secretary_runtime','_refresh_memory_label'):
        method = next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name==name)
        exec(compile(ast.Module(body=[method],type_ignores=[]),'<bootstrap-fence>','exec'),scope)
    widget = SimpleNamespace(_native_secretary_initializing=True, _post_log=lambda *args:None)
    assert scope['_ensure_secretary_runtime'](widget) is False
    assert scope['_refresh_memory_label'](widget) is None


def test_failed_server_prime_cannot_retry_lazy_storage_on_gui(monkeypatch):
    import ast
    from types import SimpleNamespace
    monkeypatch.setenv('AIPACS_EAGLE_EYE_ROLE','server')
    class Cold:
        _memory_store = None
        @property
        def memory_store(self):
            pytest.fail('Failed prime must not retry storage on GUI')
    widget = SimpleNamespace(_native_secretary_initializing=False,
                             _secretary_orchestrator=Cold(),_post_log=lambda *args:None)
    tree = ast.parse(Path('PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py').read_text(encoding='utf-8'))
    scope={'os':bridge.os}
    for name in ('_ensure_secretary_runtime','_refresh_memory_label'):
        method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name)
        exec(compile(ast.Module(body=[method],type_ignores=[]),'<failed-prime>','exec'),scope)
    assert scope['_ensure_secretary_runtime'](widget) is False
    assert scope['_refresh_memory_label'](widget) is None


def test_exact_venv_redirector_chain_is_attested_but_unrelated_ancestor_is_not():
    exe, parent, child, state = fixtures()
    launcher = str(Path('synthetic-venv/python.exe').resolve())
    redirector = dict(child, pid=102, exe=launcher, created=10.5)
    child['ppid'] = 102
    snapshots = {100: parent, 101: child, 102: redirector}
    assert bridge.attest_process(101, lambda: state, snapshots.__getitem__,
                                 exe, parent['cmdline'], child['cmdline'], launcher)
    redirector['cmdline'] = [launcher, 'unrelated']
    assert not bridge.attest_process(101, lambda: state, snapshots.__getitem__,
                                     exe, parent['cmdline'], child['cmdline'], launcher)


def test_private_target_acl_rejects_nonprivileged_writers_and_requires_service_read():
    system, admin, service = 'S-1-5-18', 'S-1-5-32-544', 'S-1-5-19'
    good = [(0, 0x10000000, system), (0, 0x10000000, admin), (0, 0x80000000, service)]
    assert bridge.trusted_acl(admin, good)
    assert not bridge.trusted_acl('S-1-5-21-1', good)
    assert not bridge.trusted_acl(admin, None)
    assert not bridge.trusted_acl(admin, good + [(0, 0x2, 'S-1-1-0')])
    assert not bridge.trusted_acl(admin, good + [(0, 0x40000, service)])
    assert not bridge.trusted_acl(admin, good[:2])
    assert not bridge.trusted_acl(admin, good + [(1, 0x1, service)])


def test_source_target_binds_executables_source_config_and_service_entry(tmp_path):
    source = tmp_path / 'source'
    entry = source / 'tools/eagle_eye/windows_service.py'
    entry.parent.mkdir(parents=True)
    entry.write_text('# Synthetic entry', encoding='utf-8')
    private = tmp_path / 'private'
    private.mkdir()
    config = private / 'server.json'
    launcher, base = tmp_path / 'venv.exe', tmp_path / 'base.exe'
    launcher.write_bytes(b'synthetic launcher')
    base.write_bytes(b'synthetic base')
    value = {'schema': 1, 'source': str(source), 'config': str(config),
             'runtime_executable': str(launcher), 'runtime_sha256': bridge._digest(launcher),
             'base_executable': str(base), 'base_sha256': bridge._digest(base),
             'service_entry_sha256': bridge._digest(entry)}
    target = private / 'native-service-target.json'
    target.write_text(json.dumps(value), encoding='utf-8')
    checked = []
    assert bridge.read_source_target(config, source, protector=checked.append) == value
    assert checked == [target]
    base.write_bytes(b'tampered base')
    with pytest.raises(ValueError, match='executable differs'):
        bridge.read_source_target(config, source, protector=checked.append)
    base.write_bytes(b'synthetic base')
    with pytest.raises(ValueError, match='selection differs'):
        bridge.read_source_target(config, tmp_path / 'wrong-source', protector=checked.append)
    entry.write_text('# Changed entry', encoding='utf-8')
    with pytest.raises(ValueError, match='entry differs'):
        bridge.read_source_target(config, source, protector=checked.append)


def test_unprotected_source_target_is_rejected_before_read(tmp_path):
    def reject(path):
        raise PermissionError('Synthetic unprotected target')
    with pytest.raises(PermissionError):
        bridge.read_source_target(tmp_path / 'server.json', tmp_path, protector=reject)


def test_staged_target_validation_cannot_leave_private_directory(tmp_path):
    with pytest.raises(ValueError, match='private directory'):
        bridge.read_source_target(tmp_path / 'private/server.json', tmp_path / 'source',
                                  target_path=tmp_path / 'elsewhere/target.json',
                                  protector=lambda path: None)


def test_attachment_cleanup_preserves_first_idle_close_proof():
    class Connector:
        calls = []
        def close(self, **kwargs):
            self.calls.append(kwargs)
    class Runtime:
        calls = 0
        def close(self):
            self.calls += 1
    attachment = bridge.Attachment()
    attachment.runtime, attachment.connector = Runtime(), Connector()
    proof = {'synthetic': 'proof'}
    attachment.close(idle_detach=proof)
    attachment.close()  # Task-finally cannot replace grace with immediate loss.
    assert attachment.connector.calls == [{'idle_detach': proof}]
    assert attachment.runtime.calls == 1
