"""Synthetic rolling native leases: no credentials, live database or provider."""
import hashlib
from types import SimpleNamespace

import pytest

from modules.ai_imaging.eagle_eye_remote import user_access as access, user_session as sessions


@pytest.fixture
def lease(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(access, 'time', SimpleNamespace(monotonic=lambda: clock[0], time=lambda: clock[0]))
    provider = SimpleNamespace(login=lambda username,password: ('fixture-token', {'subject':'fixture-id','username':'fixture-user'}),
                               verify=lambda token: {'subject': 'fixture-id', 'username': 'fixture-user'})
    authority = access.UserAuthority(access.AccessStore(tmp_path/'fixture.sqlite3', 'fixture-center'), {'pacs': provider})
    principal = authority.store.identify({'provider': 'pacs', 'subject': 'fixture-id', 'username': 'fixture-user'})
    grant = dict(enabled=True, secretary=True, echomind=False, imaging=False, crm=False, modules=[])
    authority.store.grant(principal, grant, 'fixture-admin')
    opaque = authority.login('fixture-device', {'username':'fixture-user','password':'fixture-password'})['user_session']
    key = hashlib.sha256(opaque.encode()).hexdigest()
    return authority, provider, opaque, key, clock, grant, principal


def test_rolling_renewal_preserves_opaque_and_verifies_each_hour(lease):
    authority, provider, opaque, key, clock, _, _ = lease
    calls = []
    provider.verify = lambda token: calls.append(token) or {'subject': 'fixture-id', 'username': 'fixture-user'}
    for now in (3400, 6700, 10000):
        clock[0] = now
        result = authority.refresh('fixture-device', opaque)
        assert result['user_session'] == opaque and result['expires_in'] == 3600
        assert authority.sessions[key]['expires'] == now + 3600
    assert len(calls) == 3


@pytest.mark.parametrize('mutation', ['logout', 'replace', 'expire', 'disable', 'grant', 'identity', 'unavailable'])
def test_refresh_never_resurrects_or_extends_invalid_lease(lease, mutation):
    authority, provider, opaque, key, clock, grant, principal = lease
    original = authority.sessions[key]
    expiry = original['expires']
    def verify(token):
        if mutation == 'logout': authority.logout('fixture-device', opaque)
        if mutation == 'replace': authority.sessions[key] = dict(original)
        if mutation == 'expire': clock[0] = expiry
        if mutation in ('disable', 'grant'):
            authority.store.grant(principal, {**grant, 'enabled': mutation != 'disable', 'secretary': False}, 'fixture-admin')
        if mutation == 'identity': return {'subject': 'other-id', 'username': 'fixture-user'}
        if mutation == 'unavailable': raise access.UserDenied(503, 'UPSTREAM_IDENTITY_UNAVAILABLE')
        return {'subject': 'fixture-id', 'username': 'fixture-user'}
    provider.verify = verify
    with pytest.raises(access.UserDenied): authority.refresh('fixture-device', opaque)
    assert original['expires'] == expiry
    if key in authority.sessions: assert authority.sessions[key]['expires'] == expiry


def test_wrong_device_and_expired_session_do_not_call_provider(lease):
    authority, provider, opaque, key, clock, _, _ = lease
    provider.verify = lambda token: pytest.fail('Provider must not be called')
    with pytest.raises(access.UserDenied): authority.refresh('other-device', opaque)
    clock[0] = authority.sessions[key]['expires']
    with pytest.raises(access.UserDenied): authority.refresh('fixture-device', opaque)


@pytest.fixture
def cached(monkeypatch):
    clock = [100.0]
    generation = (7, 2)
    monkeypatch.setattr(sessions, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(sessions, 'identity', lambda: (generation, 'fixture-upstream'))
    monkeypatch.setattr(sessions, '_sessions', {})
    client = SimpleNamespace(url='https://fixture.invalid', token='fixture-device', _profile_key=None, _human_generation=generation)
    opaque = 'x'*40
    value = dict(session=opaque, principal='pacs:fixture', provider='pacs', deadline=350.0)
    sessions._sessions[sessions._key(client, generation)] = value
    return client, opaque, generation, value, clock


def test_worker_refreshes_same_cache_only_after_valid_receipt(cached):
    client, opaque, generation, value, clock = cached
    calls = []
    client.refresh_human_session = lambda token, gen: calls.append((token, gen)) or dict(user_session=opaque, expires_in=3600, user=dict(principal=value['principal'], provider='pacs'))
    assert sessions.renew_native(client, opaque, value['principal'], generation)
    assert value['deadline'] == clock[0] + 3595
    assert not sessions.renew_native(client, opaque, value['principal'], generation)
    assert calls == [(opaque, generation)]


def test_transient_refresh_bounded_retry_preserves_old_expiry(cached):
    from modules.ai_imaging.eagle_eye_remote.client import ServerHTTPError
    client, opaque, generation, value, clock = cached
    calls = []
    def unavailable(*args):
        calls.append(1)
        raise ServerHTTPError(503, 'Fixture unavailable')
    client.refresh_human_session = unavailable
    for _ in range(10): assert not sessions.renew_native(client, opaque, value['principal'], generation)
    assert len(calls) == 1 and value['deadline'] == 350
    clock[0] += 60
    assert not sessions.renew_native(client, opaque, value['principal'], generation)
    assert len(calls) == 2 and value['deadline'] == 350


@pytest.mark.parametrize('mutation', ['logout', 'replace', 'identity', 'generation'])
def test_worker_discards_refresh_races(cached, monkeypatch, mutation):
    assert callable(getattr(sessions, 'renew_native', None))
    client, opaque, generation, value, clock = cached
    def refresh(*args):
        if mutation == 'logout': sessions._sessions.clear()
        if mutation == 'replace': sessions._sessions[sessions._key(client, generation)] = dict(value)
        if mutation == 'generation': monkeypatch.setattr(sessions, 'identity', lambda: ((8, 2), 'fixture-upstream'))
        return dict(user_session=opaque, expires_in=3600, user=dict(principal='other' if mutation == 'identity' else value['principal'], provider='pacs'))
    client.refresh_human_session = refresh
    with pytest.raises(Exception): sessions.renew_native(client, opaque, value['principal'], generation)
    assert value['deadline'] == 350


def test_worker_singleflight_and_network_latency_never_inflate_lease(cached):
    client, opaque, generation, value, clock = cached
    calls = []
    def refresh(*args):
        calls.append(1)
        assert not sessions.renew_native(client, opaque, value['principal'], generation)
        clock[0] += 20
        return dict(user_session=opaque, expires_in=3600, user=dict(principal=value['principal'], provider='pacs'))
    client.refresh_human_session = refresh
    assert sessions.renew_native(client, opaque, value['principal'], generation)
    assert len(calls) == 1 and value['deadline'] == 3695


def test_refresh_http_contract_uses_existing_device_and_exact_empty_body(lease):
    import json
    import threading
    import urllib.request
    import urllib.error
    from http.server import ThreadingHTTPServer
    from modules.ai_imaging.eagle_eye_remote import server
    authority, provider, opaque, key, clock, _, _ = lease
    http = ThreadingHTTPServer(('127.0.0.1', 0), server.handler(SimpleNamespace(), {'fixture-device': 'fixture-pair'}, user_authority=authority))
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    try:
        clock[0] = 3400
        for body, expected in (({}, 200), ({'unexpected': True}, 404)):
            request = urllib.request.Request(f'http://127.0.0.1:{http.server_port}/v1/auth/session/refresh', data=json.dumps(body).encode(), headers={'Authorization': 'Bearer fixture-pair', 'X-Eagle-User-Session': opaque})
            try:
                with urllib.request.urlopen(request, timeout=2) as response:
                    assert response.status == expected
                    assert json.load(response)['user_session'] == opaque
            except urllib.error.HTTPError as error:
                assert error.code == expected
        assert authority.sessions[key]['expires'] == 7000
    finally:
        http.shutdown()
        http.server_close()
        worker.join(3)


def test_client_captured_session_cannot_bypass_other_routes(cached):
    from modules.ai_imaging.eagle_eye_remote.client import Client
    client, opaque, generation, _, _ = cached
    client._check_profile = lambda: None
    client.opener = SimpleNamespace(open=lambda *args, **kwargs: pytest.fail('No network admission'))
    with pytest.raises(ValueError): Client.open(client, '/v1/jobs', {}, _native_session=(opaque, generation))


def test_late_refresh_401_cannot_clear_new_login(cached, monkeypatch):
    import urllib.error
    from modules.ai_imaging.eagle_eye_remote.client import Client, ServerHTTPError
    client, opaque, generation, value, _ = cached
    client._check_profile = lambda: None
    newer = dict(value, session='n'*40)
    def denied(*args, **kwargs):
        monkeypatch.setattr(sessions, 'identity', lambda: ((8, 2), 'new-upstream'))
        sessions._sessions.clear()
        sessions._sessions[sessions._key(client, (8, 2))] = newer
        raise urllib.error.HTTPError('https://fixture.invalid', 401, 'Denied', {}, None)
    client.opener = SimpleNamespace(open=denied)
    with pytest.raises(ServerHTTPError): Client.open(client, '/v1/auth/session/refresh', {}, _native_session=(opaque, generation))
    assert list(sessions._sessions.values()) == [newer]


def test_attachment_renewal_is_off_gui_thread():
    import ast
    from pathlib import Path
    source = Path('modules/ai_imaging/eagle_eye_remote/secretary_native_connector.py').read_text()
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'to_thread']
    assert any(node.args and isinstance(node.args[0], ast.Attribute) and node.args[0].attr == 'renew_native' for node in calls)
    assert 'next_renewal = time.monotonic() + 30' in source


def test_closed_attachment_never_starts_or_commits_worker_renewal(cached):
    client, opaque, generation, value, _ = cached
    current = [False]
    calls = []
    def refresh(*args):
        calls.append(1)
        current[0] = False
        return dict(user_session=opaque, expires_in=3600, user=dict(principal=value['principal'], provider='pacs'))
    client.refresh_human_session = refresh
    assert not sessions.renew_native(client, opaque, value['principal'], generation, is_current=lambda: current[0])
    assert calls == []
    current[0] = True
    assert not sessions.renew_native(client, opaque, value['principal'], generation, is_current=lambda: current[0])
    assert calls == [1] and value['deadline'] == 350


def test_actual_client_refresh_network_failure_preserves_valid_cache(cached):
    import urllib.error
    from modules.ai_imaging.eagle_eye_remote.client import Client
    client, opaque, generation, value, _ = cached
    client._check_profile = lambda: None
    def unavailable(*args, **kwargs):
        raise urllib.error.URLError('Synthetic network unavailable')
    client.opener = SimpleNamespace(open=unavailable)
    client.open = lambda *args, **kwargs: Client.open(client, *args, **kwargs)
    client.refresh_human_session = lambda *args: Client.refresh_human_session(client, *args)
    assert not sessions.renew_native(client, opaque, value['principal'], generation)
    assert value['deadline'] == 350


def test_refresh_malformed_json_is_not_a_recoverable_network_failure(cached):
    import io
    from modules.ai_imaging.eagle_eye_remote.client import Client
    client, opaque, generation, value, _ = cached
    client._check_profile = lambda: None
    client.opener = SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(b'not-json'))
    client.open = lambda *args, **kwargs: Client.open(client, *args, **kwargs)
    client.refresh_human_session = lambda *args: Client.refresh_human_session(client, *args)
    with pytest.raises(ValueError): sessions.renew_native(client, opaque, value['principal'], generation)
    assert value['deadline'] == 350


def test_ordinary_network_failure_retains_existing_client_behavior(cached):
    import urllib.error
    from modules.ai_imaging.eagle_eye_remote.client import Client
    client, _, _, _, _ = cached
    client._check_profile = lambda: None
    def unavailable(*args, **kwargs): raise urllib.error.URLError('Synthetic network unavailable')
    client.opener = SimpleNamespace(open=unavailable)
    with pytest.raises(RuntimeError) as error: Client.open(client, '/v1/capabilities')
    assert type(error.value) is RuntimeError
