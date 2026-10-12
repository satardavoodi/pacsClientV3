"""Console admission must require an upstream administrator, not an AI grant."""
import pytest
from modules.ai_imaging.eagle_eye_remote import admin_auth as auth
from modules.ai_imaging.eagle_eye_remote.user_access import UserDenied


@pytest.fixture(autouse=True)
def clean_sessions():
    auth._FAILURES.clear()
    auth._SESSIONS.clear()


@pytest.mark.parametrize('role', ['admin', 'system_admin', 'doctor', None])
def test_pacs_console_requires_verified_admin_role(monkeypatch, role):
    from modules.ai_imaging.eagle_eye_remote.pacs_identity import PacsIdentity
    identity = {'provider': 'pacs', 'subject': 'synthetic-1', 'username': 'Synthetic'}
    adapter = PacsIdentity({'url': 'http://127.0.0.1:9999'})
    monkeypatch.setattr(adapter, 'login', lambda *a: ('synthetic-token', identity))
    monkeypatch.setattr(adapter, '_verified_user', lambda *a: {
        'id': 'synthetic-1', 'username': 'Synthetic', 'role': role})
    if role in ('admin', 'system_admin'):
        assert adapter.login_console('Synthetic', 'synthetic-only') == identity
    else:
        with pytest.raises(UserDenied) as denied:
            adapter.login_console('Synthetic', 'synthetic-only')
        assert denied.value.status == 403


@pytest.mark.parametrize('admin', [True, False, 'true', 1, None])
def test_reception_console_requires_boolean_authoritative_admin(monkeypatch, admin):
    from modules.ai_imaging.eagle_eye_remote.reception_identity import (
        ReceptionIdentity, ReceptionIdentityUnavailable)
    adapter = ReceptionIdentity({'protocol': 'ino-admin-user-v1',
                                 'base_url': 'http://127.0.0.1:9999'})
    user = {'id': '1234567890abcdef12345678', 'username': 'Synthetic', 'admin': admin}
    monkeypatch.setattr(adapter, '_request', lambda *a, **kw: {
        'success': True, 'token': 'synthetic-token', 'user': user})
    if admin is True:
        assert adapter.login_console('Synthetic', 'synthetic-only')['provider'] == 'reception'
    else:
        with pytest.raises(ReceptionIdentityUnavailable):
            adapter.login_console('Synthetic', 'synthetic-only')


def test_verified_upstream_admin_gets_console_session(monkeypatch):
    monkeypatch.setattr(auth, 'authenticate', lambda *a: None)
    monkeypatch.setattr(auth, '_upstream_administrator', lambda *a: {
        'provider': 'pacs', 'subject': 'synthetic-1', 'username': 'SyntheticAdmin'})
    result = auth.authenticate_console('SyntheticAdmin', 'synthetic-only')
    assert result['user']['role'] == 'admin'
    assert result['user']['auth_source'] == 'pacs'
    assert auth.valid_session(result['session'])
    assert 'token' not in result


def test_local_superadmin_keeps_priority(monkeypatch):
    expected = {'session': 'synthetic-local'}
    monkeypatch.setattr(auth, 'authenticate', lambda *a: expected)
    monkeypatch.setattr(auth, '_upstream_administrator', lambda *a: pytest.fail('Unexpected upstream call'))
    assert auth.authenticate_console('SyntheticOwner', 'synthetic-only') is expected


def test_upstream_failure_cannot_admit_console(monkeypatch):
    monkeypatch.setattr(auth, 'authenticate', lambda *a: None)
    def denied(*args):
        raise UserDenied(403, 'CONSOLE_ADMIN_REQUIRED')
    monkeypatch.setattr(auth, '_upstream_administrator', denied)
    assert auth.authenticate_console('SyntheticUser', 'synthetic-only') is None


@pytest.mark.parametrize('status,expected_reception', [(401, True), (403, False), (503, False)])
def test_authority_fallback_requires_pacs_credential_rejection(tmp_path, monkeypatch, status, expected_reception):
    import json
    from modules.ai_imaging.eagle_eye_remote.pacs_identity import PacsIdentity
    from modules.ai_imaging.eagle_eye_remote.reception_identity import ReceptionIdentity
    config = tmp_path / 'server.json'
    config.write_text(json.dumps({'user_access': {'providers': {
        'pacs': {'url': 'http://127.0.0.1:9999'},
        'reception': {'protocol': 'ino-admin-user-v1', 'base_url': 'http://127.0.0.1:9998'}}}}))
    monkeypatch.setenv('AIPACS_EAGLE_EYE_SERVER_CONFIG', str(config))
    def reject(*args):
        raise UserDenied(status, 'SYNTHETIC_DENIAL')
    monkeypatch.setattr(PacsIdentity, 'login_console', reject)
    called = []
    monkeypatch.setattr(ReceptionIdentity, 'login_console', lambda *a: called.append(True) or {
        'provider': 'reception', 'subject': 'synthetic', 'username': 'Synthetic'})
    if expected_reception:
        assert auth._upstream_administrator('Synthetic', 'synthetic-only')['provider'] == 'reception'
    else:
        with pytest.raises(UserDenied):
            auth._upstream_administrator('Synthetic', 'synthetic-only')
    assert bool(called) is expected_reception
