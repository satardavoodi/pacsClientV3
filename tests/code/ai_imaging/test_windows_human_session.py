"""Synthetic Windows human-session boundaries; no clinical data or live services."""
import io
import json
from types import SimpleNamespace
import urllib.error

import pytest

from modules.ai_imaging.eagle_eye_remote import client, user_session
from modules.network.socket_token_manager import get_socket_token_manager
from tests.code.ai_imaging.test_user_access_http import service


@pytest.fixture
def transport():
    manager = get_socket_token_manager()
    manager.clear_token()
    user_session.clear()
    calls = []
    def send(request, timeout):
        calls.append(request)
        if request.full_url.endswith('/v1/auth/session'):
            value = dict(user_session='synthetic-session-value-for-tests-only', expires_in=3600,
                         user=dict(provider=json.loads(request.data).get('provider', 'pacs'), principal='synthetic-person'))
        else:
            value = dict(ok=True)
        return io.BytesIO(json.dumps(value).encode())
    connection = client.Client.__new__(client.Client)
    connection.url = 'https://synthetic.invalid'
    connection.token = 'synthetic-device-value'
    connection.opener = SimpleNamespace(open=send)
    yield connection, manager, calls
    manager.clear_token()
    user_session.clear()


def test_pairing_discovery_allowed_but_device_only_ai_rejected(transport):
    connection, _, calls = transport
    assert connection.json('/v1/capabilities')['ok']
    with pytest.raises(client.ServerHTTPError) as failure:
        connection.json('/v1/secretary/plan', {})
    assert failure.value.status == 401
    assert len(calls) == 1


@pytest.mark.parametrize('endpoint', ['/v1/jobs', '/v1/cases/snapshot', '/v1/echomind/process',
                                      '/v1/secretary/plan', '/v1/crm/status', '/v1/usage'])
def test_exchange_and_header_for_all_protected_callers(transport, endpoint):
    connection, manager, calls = transport
    manager.set_token('synthetic-upstream-value')
    user_session.capture_login('synthetic-user', 'synthetic-password')
    connection.json(endpoint)
    connection.json(endpoint)
    assert len(calls) == 3
    assert json.loads(calls[0].data) == {'username': 'synthetic-user', 'password': 'synthetic-password'}
    assert not calls[0].has_header('X-eagle-user-session')
    assert calls[1].get_header('X-eagle-user-session') == 'synthetic-session-value-for-tests-only'
    assert calls[1].get_header('Authorization') is None
    assert 'synthetic-upstream-value' not in str(calls[1].headers)


def test_logout_clears_cache_and_rejects_inflight_bytes(transport):
    connection, manager, _ = transport
    manager.set_token('synthetic-upstream-value')
    user_session.capture_login('synthetic-user', 'synthetic-password')
    response = connection.open('/v1/jobs')
    manager.clear_token()
    assert not user_session._sessions
    with pytest.raises(client.ServerHTTPError):
        response.read()
    response.close()
    with pytest.raises(client.ServerHTTPError):
        connection.json('/v1/jobs')


def test_same_token_new_login_is_a_new_generation(transport):
    connection, manager, calls = transport
    manager.set_token('synthetic-upstream-value')
    user_session.capture_login('synthetic-user', 'synthetic-password')
    connection.json('/v1/jobs')
    manager.set_token('synthetic-upstream-value')
    user_session.capture_login('synthetic-user', 'synthetic-password')
    with pytest.raises(client.ServerHTTPError):
        connection.json('/v1/jobs')
    assert len(calls) == 2


@pytest.mark.parametrize('status', [401, 403])
def test_access_errors_are_not_network_errors_or_automatically_replayed(transport, status):
    connection, manager, calls = transport
    manager.set_token('synthetic-upstream-value')
    user_session.capture_login('synthetic-user', 'synthetic-password')
    connection.json('/v1/jobs')
    before = len(calls)
    def denied(request, timeout):
        calls.append(request)
        raise urllib.error.HTTPError(request.full_url, status, 'synthetic', {}, io.BytesIO(b'{}'))
    connection.opener.open = denied
    with pytest.raises(client.ServerHTTPError) as failure:
        connection.json('/v1/secretary/plan', {})
    assert failure.value.status == status
    assert len(calls) == before + 1
    assert 'Sign in' in str(failure.value) if status == 401 else 'approved' in str(failure.value)


def test_profile_change_refuses_old_client(transport, monkeypatch):
    connection, manager, calls = transport
    manager.set_token('synthetic-upstream-value')
    user_session.capture_login('synthetic-user', 'synthetic-password')
    connection._connection_snapshot = {'url': connection.url}
    monkeypatch.setattr(client, 'client_settings', lambda: {'url': 'https://other.invalid'})
    with pytest.raises(client.ServerHTTPError):
        connection.json('/v1/jobs')
    assert not calls


def test_expired_session_reexchanges_without_replaying_inference(transport):
    connection, manager, calls = transport
    manager.set_token('synthetic-upstream-value')
    user_session.capture_login('synthetic-user', 'synthetic-password')
    connection.json('/v1/jobs')
    for cached in user_session._sessions.values():
        cached['deadline'] = 0
    connection.json('/v1/jobs')
    assert [request.full_url.rsplit('/', 1)[-1] for request in calls] == ['session', 'jobs', 'session', 'jobs']


def test_login_changes_during_exchange_never_send_inference(transport):
    connection, manager, calls = transport
    manager.set_token('synthetic-upstream-value')
    user_session.capture_login('synthetic-user', 'synthetic-password')
    original = connection.opener.open
    def changed(request, timeout):
        response = original(request, timeout)
        manager.clear_token()
        return response
    connection.opener.open = changed
    with pytest.raises(client.ServerHTTPError):
        connection.json('/v1/jobs')
    assert len(calls) == 1 and not user_session._sessions


def test_durable_handle_is_bound_to_person_not_session_secret(transport, tmp_path, monkeypatch):
    import hashlib
    connection, manager, _ = transport
    manager.set_token('synthetic-upstream-value')
    user_session.capture_login('synthetic-user', 'synthetic-password')
    monkeypatch.setattr(client, 'validate', lambda value: value)
    connection._observe = lambda handle, path, destination, **kw: (handle, path)
    handle, path = connection.analyze('bone-age', '1.2.3', {}, {}, tmp_path)
    assert handle['human_binding'] == hashlib.sha256(b'synthetic-person').hexdigest()
    raw = path.read_text()
    assert 'synthetic-person' not in raw and 'synthetic-session' not in raw and 'synthetic-upstream' not in raw
    handle['human_binding'] = 'other-person'
    path.write_text(json.dumps(handle))
    with pytest.raises(ValueError, match='another user'):
        connection.resume(path, tmp_path)


def test_legacy_worker_sign_in_does_not_choose_authority_or_fall_back(transport):
    connection, manager, calls = transport
    assert not manager.get_token()
    user = connection.authenticate_user('reception', 'synthetic-user', 'synthetic-password')
    assert user['provider'] == 'pacs'
    assert connection.json('/v1/secretary/plan', {})['ok']
    assert json.loads(calls[0].data) == dict(username='synthetic-user', password='synthetic-password')
    assert calls[1].get_header('X-eagle-user-session')
    admission=user_session.confirmed_admission(connection)
    assert admission['provider']=='pacs' and set(admission)=={'provider','generation','principal'}
    assert 'synthetic-password' not in repr(user_session._sessions)
    for cached in user_session._sessions.values():
        cached['deadline'] = 0
    with pytest.raises(client.ServerHTTPError):
        connection.json('/v1/secretary/plan', {})
    with pytest.raises(client.ServerHTTPError):
        user_session.confirmed_admission(connection)
    assert len(calls) == 2


def test_explicit_pacs_expiry_cannot_revert_to_a_previous_socket_user(transport):
    connection, manager, calls = transport
    manager.set_token('synthetic-previous-person-token')
    user_session.capture_login('synthetic-user', 'synthetic-password')
    connection.authenticate_user('pacs', 'synthetic-new-user', 'synthetic-password')
    for cached in user_session._sessions.values():
        cached['deadline'] = 0
    with pytest.raises(client.ServerHTTPError):
        connection.json('/v1/jobs')
    assert len(calls) == 1


@pytest.mark.parametrize('status', [429, 503])
def test_sign_in_busy_or_unavailable_is_typed_and_does_not_fall_back(transport, status):
    connection, manager, calls = transport
    def unavailable(request, timeout):
        calls.append(request)
        raise urllib.error.HTTPError(request.full_url, status, 'synthetic', {}, io.BytesIO(b'{}'))
    connection.opener.open = unavailable
    with pytest.raises(client.ServerHTTPError) as failure:
        connection.authenticate_user('reception', 'synthetic-user', 'synthetic-password')
    assert failure.value.status == status
    assert len(calls) == 1 and not manager.get_token()


def test_reception_crm_preserves_both_human_and_workflow_sessions(transport):
    from modules.ai_imaging.eagle_eye_remote.crm.client import CRMClient
    connection, manager, calls = transport
    original = connection.opener.open
    def opened(request, timeout):
        if request.full_url.endswith('/v1/crm/session'):
            calls.append(request)
            return io.BytesIO(b'{"accessToken":"synthetic-crm-workflow-session"}')
        return original(request, timeout)
    connection.opener.open = opened
    crm = CRMClient.__new__(CRMClient)
    crm.server, crm.session = connection, ''
    manager.set_token('synthetic-current-person-token')
    user_session.capture_login('synthetic-user', 'synthetic-password')
    user_session.capture_login('synthetic-current-person', 'synthetic-current-password')
    crm.login('synthetic-user', 'synthetic-password')
    crm.request('health')
    assert manager.get_token()
    assert json.loads(calls[0].data) == dict(username='synthetic-current-person', password='synthetic-current-password')
    assert calls[-1].get_header('X-eagle-user-session')
    assert calls[-1].get_header('X-crm-session') == 'synthetic-crm-workflow-session'


@pytest.mark.parametrize('failed_stage', ['human', 'workflow'])
def test_new_crm_login_failure_discards_previous_workflow_session(transport, monkeypatch, failed_stage):
    from modules.ai_imaging.eagle_eye_remote.crm.client import CRMClient
    connection, _, _ = transport
    crm = CRMClient.__new__(CRMClient)
    crm.server, crm.session = connection, 'synthetic-previous-person-crm-session'
    if failed_stage == 'human':
        def rejected(*args, **kwargs):
            raise client.ServerHTTPError(401, 'Synthetic identity rejected')
        monkeypatch.setattr(connection, 'open', rejected)
        expected = client.ServerHTTPError
    else:
        def rejected(*args):
            raise ValueError('Synthetic workflow session rejected')
        monkeypatch.setattr(crm, 'request', rejected)
        expected = ValueError
    with pytest.raises(expected):
        crm.login('synthetic-new-person', 'synthetic-password')
    assert crm.session == ''


def test_isolated_slicer_payload_refuses_device_only_work_without_network(tmp_path):
    import subprocess
    import sys
    from builder.eagle_eye_client_payload import stage_client
    target = stage_client(tmp_path / 'payload')
    code = '''
import sys
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from eagle_eye_remote.client import Client, ServerHTTPError
connection = Client.__new__(Client)
connection.url, connection.token = 'https://synthetic.invalid', 'synthetic-device'
def prohibited(*args, **kwargs):
    raise AssertionError('Unauthenticated child must not contact the server')
connection.opener = SimpleNamespace(open=prohibited)
try:
    connection.open('/v1/jobs', {})
except ServerHTTPError as error:
    assert error.status == 401
    print('identity-required')
else:
    raise AssertionError('Device-only child work was admitted')
'''
    result = subprocess.run([sys.executable, '-I', '-S', '-c', code, str(target.parent)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'identity-required'


def test_protected_client_to_real_http_handler(service):
    call, authority, provider, principal, grant, calls = service
    # The fixture's callable owns the synthetic endpoint. Discover it from its closure,
    # not from a clinical configuration or network inventory.
    http = next(cell.cell_contents for cell in call.__closure__
                if hasattr(cell.cell_contents, 'server_port'))
    # Ordinary Client ingress does not present the fixture's paired device identity.
    connection = client.Client.__new__(client.Client)
    connection.url = f'http://127.0.0.1:{http.server_port}'
    connection.token = 'synthetic-pairing'
    import urllib.request
    connection.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    manager = get_socket_token_manager()
    manager.set_token('synthetic-upstream')
    user_session.capture_login('synthetic-user', 'synthetic-password')
    try:
        assert connection.json('/v1/jobs')['jobs'] == [{'module': 'bone-age'}]
        assert connection.json('/v1/usage')['version'] == 2
        authority.store.grant(principal, {**grant, 'enabled': False}, 'synthetic-admin')
        with pytest.raises(client.ServerHTTPError) as failure:
            connection.json('/v1/jobs')
        assert failure.value.status == 403
        authority.store.grant(principal, grant, 'synthetic-admin')
        provider.revoked = True
        with pytest.raises(client.ServerHTTPError) as failure:
            connection.json('/v1/jobs')
        assert failure.value.status == 401
    finally:
        manager.clear_token()


def test_reception_only_client_authenticates_against_real_http_gate(service):
    call, authority, provider, _principal, grant, _calls = service
    http = next(cell.cell_contents for cell in call.__closure__ if hasattr(cell.cell_contents, 'server_port'))
    provider.login = lambda username, password: ('synthetic-upstream', provider.verify('synthetic-upstream'))
    authority.providers = {'reception': provider}
    principal = authority.store.identify({'provider': 'reception', **provider.verify('synthetic-upstream')})
    authority.store.grant(principal, grant, 'synthetic-admin')
    connection = client.Client.__new__(client.Client)
    connection.url, connection.token = f'http://127.0.0.1:{http.server_port}', 'synthetic-pairing'
    import urllib.request
    connection.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    manager = get_socket_token_manager()
    manager.clear_token()
    try:
        assert connection.authenticate_user('reception', 'synthetic-user', 'synthetic-password')['provider'] == 'reception'
        assert connection.json('/v1/jobs')['jobs'] == [{'module': 'bone-age'}]
        assert not manager.get_token()
    finally:
        manager.clear_token()


def test_version_two_audit_is_distinct_from_legacy_token_summary():
    from modules.ai_imaging.eagle_eye_remote.user_usage import validate_user_usage
    value = dict(version=2, scope='this_user', counts=[dict(operation='imaging.brain', outcome='succeeded', requests=2)], events=[])
    assert validate_user_usage(value) is value
    for invalid in (dict(version=1, scope='this_paired_client'), {**value, 'scope': 'all_users'},
                    {**value, 'counts': [dict(operation='imaging.brain', outcome='succeeded', requests=True)]}):
        with pytest.raises(ValueError):
            validate_user_usage(invalid)


def test_usage_ui_displays_human_outcomes_without_fabricated_tokens():
    from PySide6.QtWidgets import QApplication
    from PacsClient.pacs.workstation_ui.settings_ui.ai_usage_settings import AIUsageWidget
    app = QApplication.instance() or QApplication([])
    widget = AIUsageWidget('eagle_eye')
    widget._render_user_audit(dict(version=2, scope='this_user', counts=[
        dict(operation='imaging.brain', outcome='succeeded', requests=2),
        dict(operation='secretary.ask', outcome='failed', requests=9)], events=[]))
    assert widget.table.columnCount() == 3 and widget.table.rowCount() == 1
    assert widget.table.item(0, 2).text() == '2'
    assert 'token accounting is unavailable' in widget.status.text()
    widget.close()
