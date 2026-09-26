"""Synthetic PACS expiry/restart tests; never read workstation credentials."""
import pytest
from modules.ai_imaging.eagle_eye_remote import source


class Response:
    def __init__(self, status, data=None):
        self.status_code, self.data, self.closed = status, data, False
    def json(self):
        return self.data
    def close(self):
        self.closed = True


class Session:
    def __init__(self, statuses):
        self.headers = {}
        self.statuses = iter(statuses)
        self.logins = 0
        self.responses = []
    def get(self, url, **kwargs):
        response = Response(next(self.statuses))
        self.responses.append(response)
        return response
    def post(self, url, **kwargs):
        assert url == 'http://127.0.0.1:8000/api/auth/login'
        assert kwargs['allow_redirects'] is False
        assert kwargs['json'] == {'username': 'synthetic-user', 'password': 'synthetic-password'}
        self.logins += 1
        return Response(200, {'success': True, 'token': 'synthetic-token-' + str(self.logins)})


def pacs(monkeypatch, statuses):
    monkeypatch.setattr(source, 'read_pacs_credentials', lambda path, url:
                        {'username': 'synthetic-user', 'password': 'synthetic-password'}, raising=False)
    session = Session(statuses)
    monkeypatch.setattr(source.requests, 'Session', lambda: session)
    return source.PacsSource({'url': 'http://127.0.0.1:8000', 'credential_file': 'synthetic.bin'}), session


def test_expired_token_reauthenticates_once_and_closes_rejected_response(monkeypatch):
    provider, session = pacs(monkeypatch, [401, 200])
    assert provider.get('http://127.0.0.1:8000/api/example').status_code == 200
    assert session.logins == 2  # initial login and one expiry renewal
    assert session.responses[0].closed


def test_repeated_rejection_has_bounded_retry(monkeypatch):
    provider, session = pacs(monkeypatch, [401, 401])
    with pytest.raises(ValueError):
        provider.get('http://127.0.0.1:8000/api/example')
    assert session.logins == 2
    assert all(r.closed for r in session.responses)


def test_restart_reacquires_token_without_persisting_token(monkeypatch):
    for _ in range(2):
        provider, session = pacs(monkeypatch, [200])
        provider.get('http://127.0.0.1:8000/api/example')
        assert session.logins == 1


def test_never_forward_credentials_to_another_origin(monkeypatch):
    provider, session = pacs(monkeypatch, [200])
    with pytest.raises(ValueError):
        provider.get('https://other.invalid/api/example')
    assert session.logins == 0


def test_forbidden_is_not_retried_as_expiry(monkeypatch):
    provider, session = pacs(monkeypatch, [403])
    with pytest.raises(ValueError):
        provider.get('http://127.0.0.1:8000/api/example')
    assert session.logins == 1


def test_bad_password_is_redacted_and_backed_off(monkeypatch):
    provider, session = pacs(monkeypatch, [])
    attempts = []
    session.post = lambda *a, **kw: attempts.append(1) or Response(401, {'detail': 'synthetic-password'})
    for _ in range(3):
        with pytest.raises(ValueError) as error:
            provider.get('http://127.0.0.1:8000/api/example')
        assert 'synthetic-password' not in str(error.value)
    assert len(attempts) == 1


def test_dpapi_payload_is_bound_to_configured_pacs(tmp_path):
    import json
    win32crypt = pytest.importorskip('win32crypt')
    from modules.ai_imaging.eagle_eye_remote.pacs_credentials import read_pacs_credentials
    payload = {'url': 'http://127.0.0.1:8000', 'username': 'synthetic-user', 'password': 'synthetic-password'}
    protected = win32crypt.CryptProtectData(json.dumps(payload).encode(), 'test only', None, None, None, 4)
    path = tmp_path / 'synthetic.bin'
    path.write_bytes(protected)
    assert b'synthetic-password' not in path.read_bytes()
    assert read_pacs_credentials(path, payload['url'])['username'] == 'synthetic-user'
    with pytest.raises(ValueError):
        read_pacs_credentials(path, 'http://127.0.0.1:9000')
