"""Synthetic authoritative PACS token checks; no clinical service access."""
import io
import json
import pytest
from modules.ai_imaging.eagle_eye_remote import pacs_identity as identity
from modules.ai_imaging.eagle_eye_remote.user_access import UserDenied


@pytest.mark.parametrize('url', ['http://external.example', 'http://127.0.0.1/path',
    'http://user:secret@localhost', 'http://localhost?redirect=other', 'file:///tmp/source',
    'http://localhost\n', 'http://localhost:0'])
def test_identity_requires_configured_same_host_origin(url):
    with pytest.raises(ValueError): identity.PacsIdentity({'url':url})


@pytest.fixture
def transport(monkeypatch):
    state = {'status':200,'body':{'success':True,'user':{'id':'synthetic-id','username':'canonical-user'}},'calls':[]}
    class Response:
        def __init__(self):
            self.status_code = state['status']
            self.raw = io.BytesIO(state.get('raw',json.dumps(state['body']).encode()))
        def close(self): state['closed'] = True
    class Raw:
        def __init__(self, data): self.data = data
        def read(self, size, **kwargs): return self.data.read(size)
    class Session:
        trust_env = True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, **kwargs):
            state['calls'].append((url,kwargs,self.trust_env))
            response = Response();response.raw=Raw(response.raw);return response
    monkeypatch.setattr(identity.requests,'Session',Session)
    return state


def test_token_is_verified_by_authority_with_no_proxy_or_redirect(transport):
    adapter = identity.PacsIdentity({'url':'http://127.0.0.1:8080'})
    value = adapter.verify('synthetic-token')
    assert value == {'provider':'pacs','subject':'synthetic-id','username':'canonical-user'}
    url,options,trust_env = transport['calls'][0]
    assert url.endswith('/api/auth/verify')
    assert options['allow_redirects'] is False and options['verify'] is True and trust_env is False
    assert options['timeout'] == (3,5) and options['stream'] is True
    assert transport['closed']
    assert 'synthetic-token' not in repr(vars(adapter))


@pytest.mark.parametrize('status,body', [(302,{}),(401,{}),(500,{}),(200,{'success':False}),
    (200,{'success':True,'user':{'username':'spoofed'}}),
    (200,{'success':True,'user':{'id':'synthetic-id','username':'synthetic-user','is_active':False}})])
def test_invalid_upstream_identity_fails_closed(transport,status,body):
    transport.update(status=status,body=body)
    with pytest.raises(UserDenied): identity.PacsIdentity({'url':'http://localhost'}).verify('synthetic-token')
    assert transport['closed']


def test_upstream_body_is_bounded(transport):
    transport['raw'] = b'x'*65537
    with pytest.raises(UserDenied): identity.PacsIdentity({'url':'http://localhost'}).verify('synthetic-token')


def test_standard_client_cannot_manage_server_user_grants(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import user_administration
    monkeypatch.setattr(user_administration,'settings_role',lambda:'standard')
    monkeypatch.setattr(user_administration,'valid_session',lambda session:True)
    with pytest.raises(PermissionError): user_administration.snapshot('synthetic-session')
    monkeypatch.setattr(user_administration,'settings_role',lambda:'server')
    monkeypatch.setattr(user_administration,'valid_session',lambda session:False)
    with pytest.raises(PermissionError): user_administration.snapshot('synthetic-session')


@pytest.mark.parametrize('oversized',[False,True])
def test_socket_login_uses_ris_aware_protocol_and_verified_token(monkeypatch,oversized):
    import struct
    body = json.dumps({'status':'success','data':{'token':'synthetic-token'}}).encode()
    received = bytearray(struct.pack('!I',65537 if oversized else len(body))+body)
    sent = []
    class Connection:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def sendall(self,data): sent.append(data)
        def settimeout(self,timeout): assert 0 < timeout <= 8
        def recv(self,count):
            chunk = bytes(received[:min(count,3)]);del received[:len(chunk)];return chunk
    monkeypatch.setattr(identity.socket,'create_connection',lambda *a,**kw:Connection())
    adapter = identity.PacsIdentity({'url':'http://localhost'})
    verified = []
    monkeypatch.setattr(adapter,'verify',lambda token:verified.append(token) or {'subject':'synthetic-id','username':'canonical-user'})
    if oversized:
        with pytest.raises(UserDenied): adapter.login('synthetic-user','synthetic-password')
        assert not verified
    else:
        assert adapter.login('synthetic-user','synthetic-password')[0] == 'synthetic-token'
        assert verified == ['synthetic-token']
    size = struct.unpack('!I',sent[0][:4])[0]
    assert size == len(sent[0])-4
    packet = json.loads(sent[0][4:])
    assert packet['endpoint']=='Login'
    assert packet['params']=={'username':'synthetic-user','password':'synthetic-password'}
