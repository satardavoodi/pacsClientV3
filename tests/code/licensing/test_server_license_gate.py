"""Paid HTTP admission is licensed; existing results and authentication survive expiry."""
from http.server import ThreadingHTTPServer
import json
import socket
import threading
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from modules.ai_imaging.eagle_eye_remote import server


@pytest.fixture
def service(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.user_access import AccessStore, UserAuthority
    class Provider:
        def verify(self, token):
            assert token == 'synthetic-upstream'
            return {'subject':'synthetic-subject','username':'synthetic-user'}
    authority = UserAuthority(AccessStore(tmp_path/'access.sqlite3','synthetic-center'),{'pacs':Provider()})
    principal = authority.store.identify({'provider':'pacs',**Provider().verify('synthetic-upstream')})
    authority.store.grant(principal,dict(enabled=True,echomind=True,imaging=True,crm=True,secretary=True,
        modules=['bone-age']),'synthetic-admin')
    session = authority.login('synthetic',{'provider':'pacs','upstream_token':'synthetic-upstream'})['user_session']
    state = {'licensed': False, 'submitted': 0}
    state['user_session'] = session
    def submit(owner, body, **kwargs):
        state['submitted'] += 1
        return {'job_id': 'a' * 32}
    jobs = SimpleNamespace(submit=submit, recent=lambda owner: {'jobs': []})
    http = ThreadingHTTPServer(('127.0.0.1', 0), server.handler(jobs, {'synthetic': 'fixture-token'},
                              license_guard=lambda: state['licensed'], user_authority=authority))
    state['http'] = http
    state['jobs'] = jobs
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    def call(path, body=None, token='fixture-token'):
        request = urllib.request.Request(f'http://127.0.0.1:{http.server_port}' + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
                     'X-Eagle-User-Session': session})
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)
    try:
        yield state, call
    finally:
        http.shutdown()
        http.server_close()
        thread.join(3)


@pytest.mark.parametrize('path', ['/v1/jobs', '/v1/echomind/process', '/v1/secretary/plan'])
def test_missing_license_rejects_paid_work_before_execution(service, path):
    state, call = service
    assert call(path, {'module':'bone-age'} if path == '/v1/jobs' else {})[0] == 403
    assert state['submitted'] == 0
    assert call('/v1/capabilities')[0] == 200
    assert call('/v1/jobs')[0] == 200


def test_renewal_takes_effect_without_service_restart_and_auth_still_applies(service):
    state, call = service
    assert call('/v1/jobs', {'module':'bone-age'})[0] == 403
    state['licensed'] = True
    assert call('/v1/jobs', {'module':'bone-age'})[0] == 202
    assert state['submitted'] == 1
    state['licensed'] = False
    assert call('/v1/jobs', {'module':'bone-age'})[0] == 403
    assert call('/v1/jobs', {}, token='wrong')[0] == 401
    assert call('/v1/jobs')[0] == 200


def test_handler_without_an_authority_fails_closed(service):
    state, call = service
    state['http'].RequestHandlerClass = server.handler(state['jobs'], {'synthetic': 'fixture-token'})
    assert call('/v1/jobs', {})[0] == 401
    assert state['submitted'] == 0


def test_license_denial_consumes_bounded_post_body_before_reply(service):
    state, _ = service
    raw = json.dumps({'module':'bone-age','synthetic_padding': 'a' * 8192}).encode()
    with socket.create_connection(state['http'].server_address, timeout=2) as connection:
        header = (f'POST /v1/jobs HTTP/1.0\r\nAuthorization: Bearer fixture-token\r\n'
                  f"X-Eagle-User-Session: {state['user_session']}\r\n"
                  f'Content-Type: application/json\r\nContent-Length: {len(raw)}\r\n\r\n').encode()
        connection.sendall(header + raw[:1])
        connection.settimeout(.2)
        with pytest.raises(socket.timeout):
            connection.recv(4096)
        connection.sendall(raw[1:])
        connection.settimeout(2)
        response = connection.recv(4096)
        assert b'403' in response.split(b'\r\n', 1)[0]
    assert state['submitted'] == 0


def test_server_store_is_shared_and_requires_absolute_path(tmp_path, monkeypatch):
    from modules.LicenseGenerator import renewal, license_manager
    monkeypatch.setattr(license_manager, '_compute_app_data_dir', lambda: tmp_path / 'legacy')
    config = {'job_root': str(tmp_path / 'jobs')}
    manager = renewal.server_manager(config)
    assert manager.product == 'eagle-eye-server'
    assert manager.directory == tmp_path / 'licensing'
    with pytest.raises(ValueError):
        renewal.server_manager({**config, 'license_directory': 'relative'})


def test_speech_requires_server_license_before_upstream(service):
    state,call=service
    assert call('/v1/speech/transcribe',{'feature':'echomind'})[0]==403
    assert state['submitted']==0
