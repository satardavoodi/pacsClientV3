"""Synthetic source-backed Reception identity guards; no live authentication."""
import json
import pytest
import requests
from modules.ai_imaging.eagle_eye_remote.reception_identity import ReceptionIdentity, ReceptionIdentityUnavailable

USER = {'id': '1234567890abcdef12345678', 'username': 'canonical-user'}
CONFIG = {'protocol': 'ino-admin-user-v1', 'base_url': 'https://127.0.0.1:8080'}

class Response:
    def __init__(self, data=None, status=200, raw=None):
        self.status_code = status
        self.raw = raw if raw is not None else json.dumps(data).encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, chunk_size):
        for start in range(0, len(self.raw), chunk_size):
            yield self.raw[start:start + chunk_size]

@pytest.fixture
def transport(monkeypatch):
    replies, calls = [], []
    class Session:
        trust_env = True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def request(self, method, url, **options):
            calls.append((method, url, options, self.trust_env))
            result = replies.pop(0)
            if isinstance(result, Exception): raise result
            return result
    monkeypatch.setattr(requests, 'Session', Session)
    return replies, calls

@pytest.mark.parametrize('config', [None, '', [], 1])
def test_non_mapping_configuration(config):
    with pytest.raises(ValueError): ReceptionIdentity(config)

@pytest.mark.parametrize('protocol', [None, '', 'guessed'])
def test_explicit_protocol_required(protocol, transport):
    _, calls = transport
    adapter = ReceptionIdentity({'protocol': protocol})
    assert not adapter.available
    with pytest.raises(ReceptionIdentityUnavailable) as caught:
        adapter.login('synthetic-user', 'synthetic-password')
    assert caught.value.status == 503
    with pytest.raises(ReceptionIdentityUnavailable): adapter.verify('synthetic-token')
    assert calls == []

@pytest.mark.parametrize('origin', ['', 'https://user:secret@127.0.0.1', 'https://127.0.0.1/path', 'https://127.0.0.1?url=other', 'https://127.0.0.1#other', 'file:///tmp/data', 'https://127.0.0.1:0', 'https://127.0.0.1\n', 'https://reception.example:8080', 'http://192.0.2.1:8080', 'http://127.0.0.2:8080', 'http://localhost.example:8080', 'http://127.0.0.1\t:8080', ' http://127.0.0.1:8080'])
def test_invalid_origin(origin):
    with pytest.raises(ValueError): ReceptionIdentity(dict(CONFIG, base_url=origin))

@pytest.mark.parametrize('origin', ['http://127.0.0.1:8080', 'https://localhost:8080', 'http://[::1]:8080'])
def test_only_explicit_loopback_origins_are_supported(origin):
    adapter = ReceptionIdentity(dict(CONFIG, base_url=origin))
    assert adapter.available
    assert adapter.origin == origin

def test_login_identity_is_authoritatively_verified(transport):
    replies, calls = transport
    replies.extend([Response({'success': True, 'token': 'synthetic-token', 'user': USER}), Response({'success': True, 'user': USER})])
    adapter = ReceptionIdentity(CONFIG)
    token, identity = adapter.login('caller-alias', 'synthetic-password')
    assert token == 'synthetic-token'
    assert identity == {'subject': USER['id'], 'username': USER['username'], 'provider': 'reception'}
    assert calls[0][0:2] == ('POST', CONFIG['base_url'] + '/api/AdminUser/getToken')
    assert calls[1][0:2] == ('GET', CONFIG['base_url'] + '/api/AdminUser/verify-token')
    assert calls[1][2]['headers']['Authorization'] == 'Bearer synthetic-token'
    for _, _, options, trust_env in calls:
        assert trust_env is False
        assert options['allow_redirects'] is False
        assert options['verify'] is True
        assert options['stream'] is True
        assert options['timeout'] == (3, 8)
    assert 'synthetic-password' not in repr(vars(adapter))

@pytest.mark.parametrize('status', [301, 302, 307, 400, 401, 403, 404, 500])
def test_upstream_failure_no_redirect_or_disclosure(status, transport):
    replies, calls = transport
    replies.append(Response(status=status, raw=b'synthetic-secret-response'))
    with pytest.raises(ReceptionIdentityUnavailable) as caught:
        ReceptionIdentity(CONFIG).verify('synthetic-token')
    assert 'synthetic' not in str(caught.value)
    assert len(calls) == 1

@pytest.mark.parametrize('user', [None, {}, {'id': '0'*24, 'username': 'local'}, {'id': USER['id'], 'username': ''}, {'id': 'client-asserted', 'username': 'admin'}])
def test_invalid_identity(user, transport):
    replies, _ = transport
    replies.append(Response({'success': True, 'user': user}))
    with pytest.raises(ReceptionIdentityUnavailable): ReceptionIdentity(CONFIG).verify('synthetic-token')

@pytest.mark.parametrize('raw', [b'[]', b'not-json', b'x' * 65537], ids=['array', 'invalid-json', 'oversized'])
def test_response_shape_parse_size(raw, transport):
    replies, _ = transport
    replies.append(Response(raw=raw))
    with pytest.raises(ReceptionIdentityUnavailable): ReceptionIdentity(CONFIG).verify('synthetic-token')

def test_network_failure_sanitized_without_retry(transport):
    replies, calls = transport
    replies.append(requests.Timeout('synthetic-secret'))
    with pytest.raises(ReceptionIdentityUnavailable) as caught:
        ReceptionIdentity(CONFIG).verify('synthetic-token')
    assert 'synthetic' not in str(caught.value)
    assert len(calls) == 1

def test_login_verification_identity_mismatch(transport):
    replies, _ = transport
    replies.extend([Response({'success': True, 'token': 'synthetic-token', 'user': USER}), Response({'success': True, 'user': dict(USER, username='different')})])
    with pytest.raises(ReceptionIdentityUnavailable): ReceptionIdentity(CONFIG).login('caller', 'synthetic-password')

@pytest.mark.parametrize('token', ['', 'synthetic\r\nheader', 'x' * 16385, None], ids=['empty', 'header-injection', 'oversized', 'null'])
def test_invalid_bearer_before_network(token, transport):
    _, calls = transport
    with pytest.raises(ReceptionIdentityUnavailable): ReceptionIdentity(CONFIG).verify(token)
    assert calls == []

def test_no_guessed_routes_or_fallback():
    with pytest.raises(ValueError): ReceptionIdentity(dict(CONFIG, verify_path='/guessed'))
    with pytest.raises(ValueError): ReceptionIdentity(dict(CONFIG, fallback='pacs'))
