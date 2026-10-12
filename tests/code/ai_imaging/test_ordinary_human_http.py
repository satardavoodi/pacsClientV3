"""Synthetic network guards for device-independent human admission."""
from tests.code.ai_imaging.test_user_access_http import service
import json
import threading
import urllib.request
import urllib.error
import socket
import ssl
from types import SimpleNamespace
import pytest
from modules.ai_imaging.eagle_eye_remote import server
from modules.ai_imaging.eagle_eye_remote.user_access import AccessStore, UserAuthority


def test_capabilities_are_public_without_device(service):
    call, *_ = service
    status, result = call('/v1/capabilities', device='')
    assert status == 200
    assert result['user_auth']['session_header'] == 'X-Eagle-User-Session'


def test_ordinary_login_and_principal_owner_without_device(service):
    call, authority, provider, principal, grant, calls = service
    status, result = call('/v1/auth/session', {'username':'synthetic-user','password':'synthetic-password'}, device='')
    assert status == 200
    session = result['user_session']
    status, _ = call('/v1/jobs', session=session, device='')
    assert status == 200
    status, _ = call('/v1/jobs', device='')
    assert status == 401
    provider.revoked = True
    status, _ = call('/v1/jobs', session=session, device='')
    assert status == 401


def test_unknown_bearer_cannot_impersonate_paired_device(service):
    call, *_ = service
    status, _ = call('/v1/jobs', device='not-a-paired-token')
    assert status == 401


@pytest.fixture(params=['http', 'https'])
def ordinary_service(tmp_path, request):
    class Provider:
        def login(self, username, password):
            if username not in ('alpha', 'beta') or password != 'synthetic-password':
                raise ValueError('Rejected')
            return username, self.verify(username)
        def verify(self, token):
            if token not in ('alpha', 'beta'):
                raise ValueError('Rejected')
            return {'subject': token, 'username': token}
    authority = UserAuthority(AccessStore(tmp_path/'access.sqlite3', 'synthetic-center'), {'pacs': Provider()})
    for name in ('alpha', 'beta'):
        principal = authority.store.identify({'provider':'pacs', **Provider().verify(name)})
        authority.store.grant(principal, dict(enabled=True, imaging=True, echomind=True, secretary=True, crm=True, modules=['bone-age']), 'fixture')
    from tests.code.ai_imaging.test_eagle_eye_remote import SyntheticSource, synthetic_runner
    jobs = server.Jobs(tmp_path/'jobs', SyntheticSource(), runner=synthetic_runner)
    http = server.HumanHTTPServer(('127.0.0.1', 0), server.handler(jobs, {}, user_authority=authority, license_guard=lambda:True,
        deployment_identity={'mode':'developer','source_path':'synthetic-private-path','provider_key':'synthetic-private-key'}))
    context = None
    if request.param == 'https':
        from datetime import datetime, timedelta, timezone
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic human service')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
            .not_valid_after(now+timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),False).sign(key,hashes.SHA256()))
        cp, kp = tmp_path/'cert.pem', tmp_path/'key.pem'
        cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        kp.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        http.tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        http.tls_context.load_cert_chain(cp,kp)
        http.tls_context.verify_mode = ssl.CERT_OPTIONAL
        context = ssl.create_default_context(cafile=str(cp))
    thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
    def call(path, body=None, session=None, scheme=None):
        headers = {'Content-Type':'application/json'}
        if session: headers['X-Eagle-User-Session'] = session
        req = urllib.request.Request(f'{scheme or request.param}://127.0.0.1:{http.server_port}'+path,
            data=None if body is None else json.dumps(body).encode(),headers=headers)
        try:
            with urllib.request.urlopen(req,context=context,timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code,json.load(exc)
    try:
        yield call, authority, http
    finally:
        http.shutdown();http.server_close();thread.join(3);jobs.close()


def test_password_login_two_humans_job_cancel_artifact_isolation(ordinary_service):
    call, authority, http = ordinary_service
    sessions = []
    for name in ('alpha', 'beta'):
        status, result = call('/v1/auth/session', {'username':name,'password':'synthetic-password'})
        assert status == 200
        sessions.append(result['user_session'])
    from tests.code.ai_imaging.test_eagle_eye_remote import request
    status, result = call('/v1/jobs',request(),sessions[0])
    assert status == 202
    jid = result['job_id']
    for suffix, body in [('',None),('/cancel',{}),('/artifacts',None)]:
        assert call('/v1/jobs/'+jid+suffix,body,sessions[1])[0] == 404
    assert call('/v1/jobs',session=sessions[1])[1]['jobs'] == []
    assert call('/v1/jobs/'+jid,session=sessions[0])[0] == 200
    assert call('/v1/auth/logout',{},sessions[0])[0] == 200
    assert call('/v1/jobs',session=sessions[0])[0] == 401


def test_stalled_peer_does_not_block_http_or_tls(ordinary_service):
    call, authority, http = ordinary_service
    idle = socket.create_connection(http.server_address,timeout=2)
    try:
        assert call('/v1/capabilities')[0] == 200
        assert call('/v1/capabilities',scheme='http')[0] == 200
    finally:
        idle.close()


def test_public_capabilities_exclude_private_deployment_values(ordinary_service):
    call, *_ = ordinary_service
    status, result = call('/v1/capabilities')
    assert status == 200
    assert result['deployment'] == {'mode':'developer'}
    encoded = json.dumps(result)
    assert 'synthetic-private' not in encoded
    assert not any(key in encoded for key in ('source_path', 'provider_key', 'user_session', 'password', 'client_certificate'))


def test_principal_owned_history_and_crm_session_cannot_cross_users(tmp_path):
    import hashlib
    from uuid import uuid4
    from modules.ai_imaging.eagle_eye_remote.text_history import History
    from modules.ai_imaging.eagle_eye_remote.crm.hosting import CRM
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    owners = ['human:' + hashlib.sha256(value.encode()).hexdigest() for value in ('principal-alpha','principal-beta')]
    history = History(tmp_path/'history')
    rid = str(uuid4())
    history.begin(rid,owners[0],{'study_uid':'1.2.3'},{'workflow':'synthetic'})
    history.finish(rid,owners[0],{'answer':'Synthetic'})
    with pytest.raises(KeyError):
        history.case_result([owners[1]],'1.2.3',rid)
    crm = CRM.__new__(CRM)
    crm.clients = server.HumanOwnerSlots({})
    crm.lock = threading.Lock()
    crm.sessions = {hashlib.sha256(b'synthetic-reception-session').hexdigest():(owners[0],'principal-alpha')}
    with pytest.raises(RequestFailed) as error:
        crm.process_request(owners[1],'POST','/v1/crm/command',{'text':'Synthetic'},
            'synthetic-reception-session',principal='principal-beta')
    assert error.value.status == 401


def test_login_peer_bucket_cannot_be_rotated_with_device_name(ordinary_service):
    _, authority, _ = ordinary_service
    from modules.ai_imaging.eagle_eye_remote.user_access import UserDenied
    body = {'username':'alpha','password':'synthetic-password'}
    for index in range(10):
        authority.login('synthetic-device-'+str(index),body,peer='synthetic-peer')
    with pytest.raises(UserDenied) as error:
        authority.login('another-device',body,peer='synthetic-peer')
    assert error.value.status == 429


def test_ordinary_expiration_restart_and_grant_revocation(ordinary_service):
    call, authority, _ = ordinary_service
    status, result = call('/v1/auth/session',{'username':'alpha','password':'synthetic-password'})
    assert status == 200
    session = result['user_session']
    user = result['user']
    authority.store.grant(user['principal'],dict(enabled=True,imaging=False,echomind=True,secretary=True,crm=True,modules=[]),'fixture')
    assert call('/v1/jobs',session=session)[0] == 403
    # A new service authority has no inherited process-local opaque sessions.
    replacement = UserAuthority(authority.store,authority.providers)
    from modules.ai_imaging.eagle_eye_remote.user_access import UserDenied
    with pytest.raises(UserDenied) as error:
        replacement.verify(None,session)
    assert error.value.status == 401
    with authority.lock:
        for cached in authority.sessions.values(): cached['expires'] = 0
    assert call('/v1/jobs',session=session)[0] == 401


def test_http10_pool_advertises_close_across_capabilities_login_and_identity(ordinary_service, tmp_path):
    import requests
    call, authority, http = ordinary_service
    scheme = 'https' if http.tls_context is not None else 'http'
    verify = str(tmp_path / 'cert.pem') if scheme == 'https' else True
    origin = f'{scheme}://127.0.0.1:{http.server_port}'
    with requests.Session() as pool:
        pool.trust_env = False
        response = pool.get(origin + '/v1/capabilities', timeout=3, verify=verify)
        assert response.status_code == 200
        assert response.headers.get('Connection', '').casefold() == 'close'
        response = pool.post(origin + '/v1/auth/session',
            json={'username':'alpha','password':'synthetic-password'}, timeout=3, verify=verify)
        assert response.status_code == 200
        assert response.headers.get('Connection', '').casefold() == 'close'
        session = response.json()['user_session']
        response = pool.get(origin + '/v1/auth/me',
            headers={'X-Eagle-User-Session':session}, timeout=3, verify=verify)
        assert response.status_code == 200
        assert response.headers.get('Connection', '').casefold() == 'close'
        assert response.json()['user']['enabled']
