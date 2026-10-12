"""Human identity and local grants are mandatory even on a paired device."""
from http.server import ThreadingHTTPServer
import json
import hashlib
import threading
from types import SimpleNamespace
import urllib.request
import urllib.error
import pytest

from modules.ai_imaging.eagle_eye_remote import server
from modules.ai_imaging.eagle_eye_remote.user_access import AccessStore, UserAuthority


def test_paired_device_alone_cannot_submit_paid_work():
    calls = []
    jobs = SimpleNamespace(submit=lambda *args: calls.append(args) or {'job_id':'a'*32})
    http = ThreadingHTTPServer(('127.0.0.1', 0), server.handler(
        jobs, {'synthetic-device':'synthetic-pairing-token'}, license_guard=lambda: True))
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    try:
        request = urllib.request.Request(f'http://127.0.0.1:{http.server_port}/v1/jobs',
            data=json.dumps({'module':'bone-age'}).encode(),
            headers={'Authorization':'Bearer synthetic-pairing-token'})
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        assert status == 401
        assert calls == []
    finally:
        http.shutdown(); http.server_close(); worker.join(3)


def test_capabilities_do_not_claim_lumbar_when_the_handler_is_unavailable():
    jobs = SimpleNamespace()
    http = ThreadingHTTPServer(('127.0.0.1', 0), server.handler(jobs, {}))
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    try:
        with urllib.request.urlopen(
            f'http://127.0.0.1:{http.server_port}/v1/capabilities', timeout=2
        ) as response:
            assert json.load(response)['lumbar_vision'] is None
    finally:
        http.shutdown(); http.server_close(); worker.join(3)


@pytest.fixture
def service(tmp_path):
    class Provider:
        revoked = False
        calls = 0
        def login(self, username, password):
            if (username,password)!=('synthetic-user','synthetic-password'):raise ValueError('Rejected')
            return 'synthetic-upstream', {'subject':'synthetic-subject','username':'synthetic-user'}
        def verify(self, token):
            self.calls += 1
            if self.revoked or token != 'synthetic-upstream': raise ValueError('Rejected')
            return {'subject':'synthetic-subject','username':'synthetic-user'}
    provider = Provider()
    authority = UserAuthority(AccessStore(tmp_path/'access.sqlite3','synthetic-center'),{'pacs':provider})
    principal = authority.store.identify({'provider':'pacs',**provider.verify('synthetic-upstream')})
    grant = dict(enabled=True,echomind=True,imaging=True,crm=False,secretary=False,modules=['bone-age','lumbar'])
    authority.store.grant(principal,grant,'synthetic-admin')
    calls = []
    jobs = SimpleNamespace(submit=lambda *args,**kw: calls.append((args,kw)) or {'job_id':'a'*32},
        recent=lambda owner:{'jobs':[{'module':'bone-age'},{'module':'brain'}]},
        get=lambda owner,jid:{'module':'brain'},
        cancel=lambda *a: calls.append('cancel'))
    def process_lumbar_vision(owner, body):
        calls.append(('lumbar-vision', owner, body['request_id']))
        if body.get('header') == 'Synthetic connection failure':
            raise ConnectionError('Synthetic upstream disconnect')
        return {
            'request_id': body['request_id'], 'stage_id': body['stage_id'],
            'stage_version': body['stage_version'], 'content': '{}',
        }

    echomind = SimpleNamespace(
        capabilities={'protocol':1,'features':['lumbar_derived_cards_v1']},
        process_lumbar_vision=process_lumbar_vision,
    )
    http = ThreadingHTTPServer(('127.0.0.1',0),server.handler(jobs,
        {'synthetic-device':'synthetic-pairing'},license_guard=lambda:True,user_authority=authority,
        echomind=echomind,
        speech=SimpleNamespace(capabilities={'protocol':1},
            process=lambda body: calls.append(('speech',body['feature'])) or {'ok':True,'transcript':'Synthetic'})))
    thread = threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    def call(path,body=None,session=None,device='synthetic-pairing'):
        headers={'Authorization':'Bearer '+device,'Content-Type':'application/json'}
        if session: headers['X-Eagle-User-Session']=session
        request=urllib.request.Request(f'http://127.0.0.1:{http.server_port}'+path,
            data=None if body is None else json.dumps(body).encode(),headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=3) as response: return response.status,json.load(response)
        except urllib.error.HTTPError as exc: return exc.code,json.load(exc)
    try: yield call,authority,provider,principal,grant,calls
    finally: http.shutdown();http.server_close();thread.join(3)


def test_both_gates_module_scope_and_upstream_revalidation(service):
    call,authority,provider,principal,grant,calls=service
    status,value=call('/v1/auth/session',{'username':'synthetic-user','password':'synthetic-password'})
    assert status==200
    session=value['user_session']
    assert call('/v1/jobs',{'module':'bone-age','request_id':'synthetic-request'},session)[0]==202
    assert calls[0][1]['principal']==principal
    assert call('/v1/jobs',{'module':'brain'},session)[0]==403
    assert call('/v1/jobs/'+'a'*32,None,session)[0]==403
    assert call('/v1/jobs',None,session)[1]['jobs']==[{'module':'bone-age'}]
    authority.store.grant(principal,{**grant,'enabled':False},'synthetic-admin')
    assert call('/v1/jobs',{'module':'bone-age'},session)[0]==403
    authority.store.grant(principal,grant,'synthetic-admin')
    provider.revoked=True
    assert call('/v1/jobs',{'module':'bone-age'},session)[0]==401
    assert len(calls)==1


def test_public_auth_user_permissions_are_booleans_without_changing_store(service):
    call, authority, provider, principal, grant, calls = service
    status, login = call('/v1/auth/session', {'username':'synthetic-user','password':'synthetic-password'})
    assert status == 200
    session = login['user_session']
    status, current = call('/v1/auth/me', None, session)
    assert status == 200
    fields = ('enabled', 'echomind', 'imaging', 'crm', 'secretary')
    for public in (login['user'], current['user']):
        for field in fields:
            assert type(public[field]) is bool
            assert public[field] is grant[field]
        assert public['principal'] == principal
        assert public['provider'] == 'pacs'
        assert public['subject'] == 'synthetic-subject'
        assert public['modules'] == grant['modules']
    assert all(type(authority.store.user(principal)[field]) is int for field in fields)
    authority.store.grant(principal, {**grant, 'echomind':False}, 'synthetic-admin')
    assert call('/v1/auth/me', None, session)[1]['user']['echomind'] is False
    authority.store.grant(principal, {**grant, 'enabled':False}, 'synthetic-admin')
    assert call('/v1/auth/me', None, session)[0] == 403
    assert calls == []


@pytest.mark.parametrize('malformed', ['1', 'true', 2, -1, None, [], {}])
def test_public_permission_projection_rejects_truthy_malformed_grants(malformed):
    original = dict(principal='synthetic', modules=['bone-age'], enabled=malformed,
                    echomind=1, imaging=0, crm=True, secretary=False)
    projected = server.public_user(original)
    assert projected['enabled'] is False
    assert projected['echomind'] is True and projected['imaging'] is False
    assert projected['crm'] is True and projected['secretary'] is False
    assert projected['modules'] == original['modules']
    assert original['enabled'] is malformed


def test_identity_missing_permission_missing_and_logout_have_distinct_results(service):
    call,authority,provider,principal,grant,calls=service
    assert call('/v1/jobs',{'module':'bone-age'})[0]==401
    assert call('/v1/auth/session',{'provider':'pacs','username':'spoofed'})[0]==401
    authority.store.grant(principal,{**grant,'enabled':False},'synthetic-admin')
    assert call('/v1/auth/session',{'username':'synthetic-user','password':'synthetic-password'})[0]==403
    authority.store.grant(principal,grant,'synthetic-admin')
    session=call('/v1/auth/session',{'username':'synthetic-user','password':'synthetic-password'})[1]['user_session']
    assert call('/v1/secretary/plan',{'request_id':'synthetic-request'},session)[0]==403
    assert call('/v1/auth/logout',{},session)[0]==200
    assert call('/v1/auth/me',None,session)[0]==401
    assert not calls


def test_reception_only_server_starts_without_pacs_source(tmp_path, monkeypatch):
    from modules.LicenseGenerator import renewal
    monkeypatch.setattr(renewal, 'server_manager', lambda config: SimpleNamespace(check_license=lambda:(True, 'Synthetic')))
    token_file = tmp_path/'device-token.txt'
    token_file.write_text('synthetic-device-token-'*3)
    http,jobs = server.create_server(dict(host='127.0.0.1',port=0,job_root=str(tmp_path/'jobs'),
        clients={'synthetic-device':str(token_file)},center_id='synthetic-center',
        user_access={'providers':{'reception':{'protocol':'ino-admin-user-v1','base_url':'http://127.0.0.1:8080'}}}))
    try:
        assert set(jobs.user_authority.providers) == {'reception'}
        assert jobs.source.available is False
        assert not hasattr(jobs, 'case_bridge')
        with pytest.raises(ValueError, match='not configured'):
            jobs.source.stage({},tmp_path,threading.Event())
    finally:
        http.server_close();jobs.close()


def test_speech_requires_human_and_context_grant_before_service(service):
    call,authority,provider,principal,grant,calls=service
    body=dict(feature='crm',request_id='synthetic-request')
    assert call('/v1/speech/transcribe',body)[0]==401
    session=call('/v1/auth/session',{'username':'synthetic-user','password':'synthetic-password'})[1]['user_session']
    assert call('/v1/speech/transcribe',body,session)[0]==403
    assert not calls
    assert call('/v1/speech/transcribe',{**body,'feature':'echomind'},session)[0]==200
    authority.store.grant(principal,{**grant,'crm':True},'synthetic-admin')
    assert call('/v1/speech/transcribe',body,session)[0]==200
    assert calls==[('speech','echomind'),('speech','crm')]


def test_lumbar_vision_requires_human_lumbar_grant_and_uses_server_service(service):
    call,authority,provider,principal,grant,calls=service
    body={
        'protocol':1,'request_id':'11111111-1111-4111-8111-111111111111',
        'study_uid':'1.2.840.10008.1','stage_id':'lumbar_clinical_context',
        'stage_version':'2.3.0','header':'Synthetic','images':[{'synthetic':True}],
    }
    assert call('/v1/imaging/lumbar-vision',body)[0]==401
    session=call('/v1/auth/session',{'username':'synthetic-user','password':'synthetic-password'})[1]['user_session']
    status,result=call('/v1/imaging/lumbar-vision',body,session)
    assert status==200 and result['request_id']==body['request_id']
    assert calls==[('lumbar-vision', 'human:'+hashlib.sha256(principal.encode()).hexdigest(), body['request_id'])]
    with authority.store.connect() as db:
        assert db.execute(
            "SELECT outcome FROM events WHERE operation='imaging.lumbar-vision'"
        ).fetchone()['outcome'] == 'succeeded'
        assert db.execute("SELECT COUNT(*) FROM events WHERE outcome='admitted'").fetchone()[0] == 0
    authority.store.grant(principal,{**grant,'modules':['bone-age']},'synthetic-admin')
    assert call('/v1/imaging/lumbar-vision',body,session)[0]==403


def test_connection_failure_after_admission_terminalizes_the_same_audit_event(service):
    call, authority, _provider, _principal, _grant, _calls = service
    session = call(
        '/v1/auth/session', {'username':'synthetic-user','password':'synthetic-password'}
    )[1]['user_session']
    body = {
        'protocol':1,'request_id':'22222222-2222-4222-8222-222222222222',
        'study_uid':'1.2.840.10008.2','stage_id':'lumbar_anatomy_map',
        'stage_version':'3.0.0','header':'Synthetic connection failure',
        'images':[{'synthetic':True}],
    }

    with pytest.raises(Exception):
        call('/v1/imaging/lumbar-vision', body, session)

    with authority.store.connect() as db:
        rows = db.execute(
            "SELECT outcome FROM events WHERE operation='imaging.lumbar-vision'"
        ).fetchall()
    assert [row['outcome'] for row in rows] == ['interrupted']


def test_capabilities_bind_lumbar_contract_to_the_available_handler(service):
    from modules.ai_imaging.eagle_eye_remote import lumbar_vision

    call, _authority, _provider, _principal, _grant, _calls = service
    status, value = call('/v1/capabilities')
    assert status == 200
    assert value['lumbar_vision'] == lumbar_vision.capabilities()
