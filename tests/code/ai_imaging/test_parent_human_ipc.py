"""Synthetic resident IPC and exact-session logout; no GUI or patient records."""
import ast
import hashlib
import importlib.util
import importlib
import io
import json
import queue
import secrets
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.ai_imaging.eagle_eye_remote import client, user_session, session_revocation
from modules.ai_imaging.eagle_eye_remote.human_session_ipc import HumanSessionBroker
from modules.ai_imaging.eagle_eye_remote.parent_ipc import ChildIdentityQueue
from modules.mpr.advanced_3d_slicer.resident_service import LocalRuntime
from tests.code.ai_imaging.test_windows_human_session import transport


def test_child_identity_bridge_exists():
    assert callable(getattr(user_session, 'install_parent_bridge', None))


def test_clearing_identity_schedules_exact_old_session(monkeypatch):
    queued = []
    monkeypatch.setattr(session_revocation, 'schedule', queued.append)
    user_session._sessions['synthetic'] = {'revocation': ('synthetic-url', None, 'device', 'opaque')}
    user_session.clear()
    assert queued == [('synthetic-url', None, 'device', 'opaque')]


@pytest.fixture
def broker(transport, monkeypatch):
    connection, manager, calls = transport
    monkeypatch.setattr(session_revocation, 'schedule', lambda item: True)
    connection._profile_key = 'synthetic-profile'
    manager.set_token('synthetic-upstream-value')
    user_session.capture_login('synthetic-user', 'synthetic-password')
    broker = HumanSessionBroker(lambda: connection)
    payload = dict(action='acquire', url=connection.url,
        device=hashlib.sha256(connection.token.encode()).hexdigest(),
        profile=connection._profile_key, lease=None)
    yield broker, payload, connection, manager, calls
    broker.close()


def test_parent_lease_rejects_account_change_and_foreign_profile(broker):
    handler, request, connection, manager, calls = broker
    receipt = handler.handle(request)
    assert receipt['ok'] and receipt['session']
    assert len(calls) == 1
    assert handler.handle(dict(request, lease=receipt['lease']))['lease'] == receipt['lease']
    assert not handler.handle(dict(request, profile='other'))['ok']
    assert not handler.handle(dict(request, device='other'))['ok']
    assert not handler.handle(dict(request, password='not-allowed'))['ok']
    manager.set_token('second-synthetic-human')
    assert handler.handle(dict(action='validate', lease=receipt['lease'])) == dict(ok=False, status=401)
    assert not handler.handle(dict(request, lease=receipt['lease']))['ok']
    assert len(calls) == 1  # No inference or identity retry under the stale lease.


def test_parent_lease_expires_and_profile_change_invalidates(broker, monkeypatch):
    handler, request, connection, _, _ = broker
    receipt = handler.handle(request)
    handler.leases[receipt['lease']]['deadline'] = 0
    assert not handler.handle(dict(action='validate', lease=receipt['lease']))['ok']
    receipt = handler.handle(request)
    def changed():
        raise client.ServerHTTPError(401, 'Changed profile')
    monkeypatch.setattr(connection, '_check_profile', changed)
    assert not handler.handle(dict(action='validate', lease=receipt['lease']))['ok']


def test_disconnected_parent_is_bounded_and_fails_closed():
    bridge = ChildIdentityQueue(timeout=0.01)
    with pytest.raises(client.ServerHTTPError) as failure:
        bridge.validate('synthetic-lease')
    assert failure.value.status == 401 and not bridge.pending


def test_queue_is_bounded():
    bridge = ChildIdentityQueue(timeout=0.1)
    bridge.pending = {str(i): {} for i in range(4)}
    with pytest.raises(client.ServerHTTPError) as failure:
        bridge.validate('synthetic-lease')
    assert failure.value.status == 429


def test_real_private_rpc_child_response_checks_parent_generation(broker, tmp_path, monkeypatch):
    handler, _, connection, manager, calls = broker
    # Load the staged client under a distinct process-like namespace. Its bridge
    # must never replace the workstation's canonical identity authority.
    from builder.eagle_eye_client_payload import stage_client
    target = stage_client(tmp_path / 'payload')
    spec = importlib.util.spec_from_file_location('synthetic_child_eagle', target / '__init__.py',
                                                submodule_search_locations=[str(target)])
    import sys
    package = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, package)
    spec.loader.exec_module(package)
    child_client = importlib.import_module(spec.name + '.client')
    child_sessions = importlib.import_module(spec.name + '.user_session')
    child_queue = importlib.import_module(spec.name + '.parent_ipc').ChildIdentityQueue(timeout=2)
    child_sessions.install_parent_bridge(child_queue)
    source = Path('modules/mpr/advanced_3d_slicer/slicer_modules/AIPacsBackgroundRuntime.py')
    tree = ast.parse(source.read_text(encoding='utf-8'))
    runtime_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Runtime')
    runtime_class.body = [node for node in runtime_class.body
                          if isinstance(node, ast.FunctionDef) and node.name in ('serve', 'accept')]
    namespace = dict(socket=socket, json=json, secrets=secrets, os=__import__('os'))
    exec(compile(ast.Module(body=[runtime_class], type_ignores=[]), str(source), 'exec'), namespace)
    runtime = namespace['Runtime']()
    runtime.root, runtime.role, runtime.token = tmp_path, 'viewer', 'private-synthetic-rpc-token'
    runtime.ready, runtime.human_identity = True, child_queue
    runtime.completed = queue.Queue()
    server = threading.Thread(target=runtime.serve, daemon=True)
    server.start()
    local = LocalRuntime('viewer')
    local.root, local.token = tmp_path, runtime.token
    local.process = SimpleNamespace(poll=lambda: None)
    deadline = time.monotonic() + 2
    while not (tmp_path / 'ready.json').exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    import modules.ai_imaging.eagle_eye_remote.human_session_ipc as broker_module
    monkeypatch.setattr(broker_module, 'HumanSessionBroker', lambda: handler)
    try:
        assert local.ready()
        child = child_client.Client.__new__(child_client.Client)
        child.url, child.token, child._profile_key = connection.url, connection.token, connection._profile_key
        child.opener = connection.opener
        with child.open('/v1/jobs') as response:
            assert json.loads(response.read())['ok']
        assert calls[-1].get_header('X-eagle-user-session')
        response = child.open('/v1/jobs')
        manager.clear_token()
        with pytest.raises(child_client.ServerHTTPError):
            response.read()
        response.close()
        # The authenticated RPC itself rejects an unrelated caller.
        local.token = 'wrong-rpc-token'
        with pytest.raises(Exception):
            local.exchange(dict(operation='identity_poll'))
        descriptor = (tmp_path / 'ready.json').read_text()
        assert 'session' not in descriptor and 'token' not in descriptor
    finally:
        local._identity_stop.set()
        runtime.ready = False
        if local._identity_thread:
            local._identity_thread.join(3)
        server.join(2)
        for name in list(sys.modules):
            if name.startswith(spec.name + '.'):
                monkeypatch.delitem(sys.modules, name)


def test_account_switch_revocation_uses_old_transport_and_only_logout(transport, monkeypatch):
    connection, manager, calls = transport
    queued = []
    monkeypatch.setattr(session_revocation, 'schedule', lambda item: queued.append(item))
    manager.set_token('first-synthetic-human')
    user_session.capture_login('synthetic-user', 'synthetic-password')
    connection.json('/v1/jobs')
    old_opener, old_url = connection.opener, connection.url
    manager.set_token('second-synthetic-human')
    assert not user_session._sessions and len(queued) == 1
    assert queued[0][0:2] == (old_url, old_opener)
    connection.opener = SimpleNamespace(open=lambda *a, **k: pytest.fail('Wrong current transport'))
    connection.url = 'https://other-synthetic.invalid'
    session_revocation._revoke(queued.pop())
    request = calls[-1]
    assert request.full_url == old_url + '/v1/auth/logout'
    assert request.data == b'{}' and request.get_method() == 'POST'
    assert request.get_header('X-eagle-user-session') == 'synthetic-session-value-for-tests-only'
    assert request.get_header('Authorization') is None
    assert b'upstream' not in request.data


def test_revocation_worker_is_background_bounded_and_drains(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    threads = []
    def revoke(item):
        threads.append(threading.current_thread())
        entered.set()
        assert release.wait(2)
    monkeypatch.setattr(session_revocation, '_revoke', revoke)
    assert session_revocation.schedule(('url', None, 'device', 'opaque'))
    assert entered.wait(1)
    assert threads[0] is not threading.current_thread()
    release.set()
    session_revocation._pending.join()
    worker = session_revocation._worker
    if worker:
        worker.join(2)
    assert session_revocation._worker is None
