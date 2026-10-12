"""Ordinary login capture; authority resolution is exclusively server-owned."""
import io
import json
import urllib.error
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.ai_imaging.eagle_eye_remote import client, user_session, session_revocation
from tests.code.ai_imaging.test_windows_human_session import transport


def test_first_request_uses_ordinary_login_and_reuses_opaque_session(transport, monkeypatch):
    connection, manager, calls = transport
    monkeypatch.setattr(session_revocation, 'schedule', lambda item: True)
    manager.set_token('synthetic-ordinary-socket-token')
    user_session.capture_login('synthetic-ordinary-user', 'synthetic-ordinary-password')
    assert not calls  # Capturing ordinary successful login does no I/O.
    connection.json('/v1/jobs')
    connection.json('/v1/usage')
    assert len(calls) == 3
    assert json.loads(calls[0].data) == dict(username='synthetic-ordinary-user',
                                         password='synthetic-ordinary-password')
    assert 'provider' not in json.loads(calls[0].data)
    assert 'synthetic-ordinary-password' not in repr(user_session._sessions)
    assert all('synthetic-ordinary-password' not in str(item.headers) for item in calls)
    manager.clear_token()
    assert user_session._login_credentials is None and not user_session._sessions


def test_authoritative_server_receipt_may_be_reception(transport, monkeypatch):
    connection, manager, calls = transport
    monkeypatch.setattr(session_revocation, 'schedule', lambda item: True)
    manager.set_token('synthetic-ordinary-socket-token')
    user_session.capture_login('synthetic-ordinary-user', 'synthetic-ordinary-password')
    original = connection.opener.open
    def opened(request, timeout):
        if request.full_url.endswith('/v1/auth/session'):
            calls.append(request)
            return io.BytesIO(json.dumps(dict(user_session='synthetic-session-value-for-tests-only',
                expires_in=3600, user=dict(provider='reception', principal='synthetic-person'))).encode())
        return original(request, timeout)
    connection.opener.open = opened
    assert connection.json('/v1/jobs')['ok']
    assert user_session.confirmed_admission(connection)['provider'] == 'reception'
    assert 'provider' not in json.loads(calls[0].data)


def test_module_grant_denial_never_reauthenticates_or_selects_another_provider(transport, monkeypatch):
    connection, manager, calls = transport
    monkeypatch.setattr(session_revocation, 'schedule', lambda item: True)
    manager.set_token('synthetic-ordinary-socket-token')
    user_session.capture_login('synthetic-ordinary-user', 'synthetic-ordinary-password')
    original = connection.opener.open
    def denied(request, timeout):
        if request.full_url.endswith('/v1/auth/session'):
            return original(request, timeout)
        calls.append(request)
        raise urllib.error.HTTPError(request.full_url, 403, 'synthetic', {}, io.BytesIO(b'{}'))
    connection.opener.open = denied
    with pytest.raises(client.ServerHTTPError) as failure:
        connection.json('/v1/jobs')
    assert failure.value.status == 403
    assert len(calls) == 2


def test_account_change_discards_ordinary_credentials(transport, monkeypatch):
    connection, manager, calls = transport
    monkeypatch.setattr(session_revocation, 'schedule', lambda item: True)
    manager.set_token('synthetic-first-socket-token')
    user_session.capture_login('synthetic-first-user', 'synthetic-first-password')
    manager.set_token('synthetic-second-socket-token')
    assert user_session._login_credentials is None
    with pytest.raises(client.ServerHTTPError) as failure:
        connection.json('/v1/jobs')
    assert failure.value.error_code == 'USER_SIGN_IN_REQUIRED'
    assert not calls


def test_late_capture_cannot_bind_old_credentials_to_new_account(transport):
    _, manager, _ = transport
    old_generation = manager.set_token('synthetic-first-token')
    manager.set_token('synthetic-second-token')
    assert user_session.capture_login('synthetic-first-user', 'synthetic-first-password',
                                     token_generation=old_generation) is None
    assert user_session._login_credentials is None


@pytest.mark.parametrize('auth_source', ['pacs', 'reception'])
def test_actual_ordinary_socket_login_captures_only_after_success(transport, auth_source):
    _, manager, calls = transport
    source = Path('PacsClient/app_handler.py')
    tree = ast.parse(source.read_text(encoding='utf-8'))
    method = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == '_authenticate_with_socket')
    namespace = dict(get_socket_token_manager=lambda: manager,
                     logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None))
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
    socket_client = SimpleNamespace(connected=True,
        login=lambda *a: (True, 'Accepted', 'synthetic-login-token', dict(full_name='Synthetic', role='user', auth_source=auth_source)))
    handler = SimpleNamespace(socket_service=SimpleNamespace(_ensure_client=lambda: socket_client))
    assert namespace['_authenticate_with_socket'](handler, 'synthetic-user', 'synthetic-password')[0]
    assert user_session._login_credentials[1:] == ('synthetic-user', 'synthetic-password')
    assert not calls
