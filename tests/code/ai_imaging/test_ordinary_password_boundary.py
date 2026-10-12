"""Ordinary Windows Eagle ingress never borrows provider/device credentials."""
import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

from modules.ai_imaging.eagle_eye_remote import client, user_session
from tests.code.ai_imaging.test_windows_human_session import transport


def test_socket_token_alone_is_not_an_eagle_login_context(transport):
    connection, manager, calls = transport
    manager.set_token('synthetic-provider-token')
    assert not user_session.has_login_context()
    with pytest.raises(client.ServerHTTPError) as failure:
        connection.json('/v1/jobs')
    assert failure.value.error_code == 'USER_SIGN_IN_REQUIRED'
    assert calls == []


@pytest.mark.parametrize('endpoint', ['/v1/jobs', '/v1/secretary/plan', '/v1/echomind/process', '/v1/crm/status'])
def test_password_exchange_and_business_never_send_device_bearer(transport, endpoint):
    connection, _, calls = transport
    user_session.capture_login('synthetic-user', 'synthetic-password')
    connection.json(endpoint)
    assert json.loads(calls[0].data) == {'username': 'synthetic-user', 'password': 'synthetic-password'}
    assert all(not request.has_header('Authorization') for request in calls)
    assert calls[1].get_header('X-eagle-user-session')


def test_constructor_ignores_legacy_bearer_and_client_certificate(monkeypatch, tmp_path):
    token_file = tmp_path/'legacy-device-token'
    token_file.write_text('synthetic-device-token')
    monkeypatch.setenv('AIPACS_EAGLE_EYE_TOKEN', 'synthetic-environment-token')
    context = SimpleNamespace(load_cert_chain=lambda *args: pytest.fail('Ordinary ingress must not load device identity'))
    monkeypatch.setattr(client.ssl, 'create_default_context', lambda **kwargs: context)
    monkeypatch.setattr(client.urllib.request, 'HTTPSHandler', lambda **kwargs: object())
    monkeypatch.setattr(client.urllib.request, 'build_opener', lambda *args: SimpleNamespace())
    connection = client.Client({'url': 'http://192.0.2.17:8002', 'token_file': str(token_file),
        'client_certificate': str(token_file), 'client_private_key': str(token_file)})
    assert connection.token == ''


def test_http_connection_does_not_initialize_legacy_tls_settings(monkeypatch):
    monkeypatch.setattr(client.ssl, 'create_default_context', lambda **kwargs: pytest.fail('HTTP must not initialize TLS'))
    connection = client.Client({'url': 'http://192.0.2.17:8002', 'ca_file': 'not-used'})
    assert connection.url == 'http://192.0.2.17:8002'


def test_legacy_reception_wrapper_accepts_server_resolved_pacs(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import client_login
    calls = []
    connection = SimpleNamespace(authenticate_user=lambda provider, username, password:
        calls.append(provider) or {'provider': 'pacs', 'enabled': True, 'principal': 'synthetic-person'})
    monkeypatch.setattr(client, 'Client', lambda: connection)
    monkeypatch.setattr(user_session, 'confirmed_admission', lambda current:
        {'provider': 'pacs', 'principal': 'synthetic-person', 'generation': user_session.identity()[0]})
    receipt = client_login.authenticate_reception('synthetic-user', 'synthetic-password')
    assert calls == [None]
    assert client_login.valid_reception_admission(receipt)


def test_late_ordinary_401_cannot_clear_new_login(transport):
    connection, _, calls = transport
    user_session.capture_login('synthetic-old-user', 'synthetic-password')
    connection.json('/v1/jobs')
    def denied(request, timeout):
        user_session.capture_login('synthetic-new-user', 'synthetic-new-password')
        raise urllib.error.HTTPError(request.full_url, 401, 'synthetic', {}, io.BytesIO(b'{}'))
    connection.opener.open = denied
    with pytest.raises(client.ServerHTTPError):
        connection.json('/v1/jobs')
    assert user_session._login_credentials[1] == 'synthetic-new-user'
