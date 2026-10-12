"""Hosted CRM identity never requires a second Reception identity."""
import sys
from pathlib import Path
import pytest

@pytest.fixture
def delegation(monkeypatch):
    monkeypatch.syspath_prepend(str(Path('modules/ai_imaging/eagle_eye_remote/crm/vendor').resolve()))
    from modules.ai_imaging.eagle_eye_remote.crm import delegation
    return delegation

def test_identity_is_private_header_only_and_bounded(delegation):
    token = delegation.encode_subject('pacs:synthetic-user')
    assert delegation.decode_subject(token) == 'pacs:synthetic-user'
    for value in ('', 'bad!header', delegation.encode_subject('other') + '='):
        with pytest.raises(ValueError): delegation.decode_subject(value)
    with pytest.raises(ValueError): delegation.encode_subject('x'*1025)

def test_read_and_read_planning_allowed_but_writes_never(delegation):
    principal = delegation.principal_for('pacs:synthetic-user','synthetic-center')
    policy = delegation.DelegatedPolicy(principal)
    for action in ('read','plan'):
        assert policy.check(principal.user,principal.center,'report.today',action,'read').allowed
    for action,safety in [('execute','read'),('plan','write'),('execute','destructive')]:
        assert not policy.check(principal.user,principal.center,'report.today',action,safety).allowed
    assert not policy.check('forged',principal.center,'report.today','read','read').allowed
    assert not policy.check(principal.user,'other','report.today','read','read').allowed

def test_host_does_not_require_personal_reception_login(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.crm.hosting import CRM
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    import threading
    obj=object.__new__(CRM);obj.clients={'device':threading.BoundedSemaphore(0)};obj.lock=threading.Lock();obj.sessions={}
    # Admission reaches bounded execution without examining personal credentials.
    with pytest.raises(RequestFailed,match='busy'):
        obj.process_request('device','POST','/v1/crm/session',{},principal='pacs:synthetic-user')
    with pytest.raises(RequestFailed,match='busy'):
        obj.process_request('device','POST','/v1/crm/command',{'text':'synthetic'},principal='pacs:synthetic-user')
    with pytest.raises(RequestFailed,match='authenticated human'):
        obj.process_request('device','POST','/v1/crm/command',{},principal=None)
    with pytest.raises(RequestFailed,match='session'):
        obj.process_request('device','POST','/v1/crm/command',{},session='foreign',principal='pacs:synthetic-user')


def test_private_worker_delegation_requires_internal_gate_and_keeps_subject(tmp_path):
    import json,subprocess,time,requests,psutil
    from modules.ai_imaging.eagle_eye_remote.crm.delegation import HEADER,encode_subject
    root=Path('modules/ai_imaging/eagle_eye_remote/crm').resolve()
    (tmp_path/'server.json').write_text(json.dumps({'center':'SYNTHETIC','session_secret':'synthetic-isolated-key','data_root':str(tmp_path/'data')}))
    (tmp_path/'roles.json').write_text(json.dumps({'users':{},'roles':{}}))
    script="import sys;sys.path.insert(0,sys.argv[1]);from reception_crm import local_host;local_host.resolve_reception_host=lambda port:'127.0.0.1';from modules.ai_imaging.eagle_eye_remote.crm.worker import main;main()"
    proc=subprocess.Popen([sys.executable,'-c',script,str(root/'vendor')],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,text=True)
    http=requests.Session();http.trust_env=False
    try:
        proc.stdin.write(json.dumps({'config_dir':str(tmp_path),'ai_config_dir':str(tmp_path),'token':'synthetic-private-gate'})+'\n');proc.stdin.close()
        ready=tmp_path/'worker-ready.json';deadline=time.monotonic()+15
        while not ready.exists() and proc.poll() is None and time.monotonic()<deadline:time.sleep(.05)
        assert ready.exists()
        url='http://127.0.0.1:'+str(json.loads(ready.read_text())['port'])+'/api/session'
        subject=encode_subject('pacs:synthetic-person')
        assert http.post(url,headers={HEADER:subject},json={},timeout=3).status_code==401
        gate={'X-Eagle-Internal':'synthetic-private-gate'}
        assert http.post(url,headers=gate,json={},timeout=3).status_code==401
        response=http.post(url,headers={**gate,HEADER:subject},json={'username':'forged','password':'synthetic-unused'},timeout=3)
        assert response.status_code==200
        assert response.json()['principal']['user']=='eagle:pacs:synthetic-person'
        assert response.json()['principal']['roles']==['eagle_crm_readonly']
        assert 'synthetic-unused' not in response.text and 'forged' not in response.text
        assert http.post(url,headers=gate,json={},timeout=3).status_code==401
    finally:
        http.close()
        if proc.poll() is None:
            for child in psutil.Process(proc.pid).children(recursive=True):child.kill()
            proc.kill()
        proc.wait(timeout=5)


def test_advertised_tools_match_actual_delegated_guard(delegation,monkeypatch):
    from reception_crm import permissions
    from reception_crm.core import guards
    from reception_crm.core.registry import ToolRegistry
    from reception_crm.core.types import ToolDefinition
    monkeypatch.setattr(permissions,'load_permissions',permissions.load_permissions)
    monkeypatch.setattr(guards,'load_permissions',guards.load_permissions)
    monkeypatch.setattr(permissions,'discover_roles_path',lambda _: (_ for _ in ()).throw(FileNotFoundError()))
    delegation.install_policy()
    p=delegation.principal_for('pacs:synthetic','center');marker=delegation.CURRENT.set(p)
    try:
        registry=ToolRegistry()
        for name,action,safety in [('read','read','read'),('read_plan','plan','read'),('write_plan','plan','clinical_write'),('write','execute','write')]:
            registry.register(ToolDefinition(name=name,kind='synthetic',handler=lambda _:None,permission_action=action,safety=safety))
        assert {x['name'] for x in registry.list_for(p)}=={'read','read_plan'}
    finally:delegation.CURRENT.reset(marker)
    assert registry.list_for(p)==[]


def test_logout_body_cannot_revoke_foreign_token(monkeypatch):
    import threading
    from modules.ai_imaging.eagle_eye_remote.crm.hosting import CRM
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    obj=object.__new__(CRM);obj.clients={'device':threading.BoundedSemaphore(1)};obj.slots=threading.BoundedSemaphore(1)
    obj.lock=threading.Lock();obj.sessions={};obj._start=lambda:None;obj.internal_token='synthetic';obj.url='http://127.0.0.1:1'
    seen=[]
    class HTTP:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def request(self,*args,**kwargs):
            seen.append(kwargs)
            raise RequestFailed(422,'synthetic stop before any network')
    monkeypatch.setattr('modules.ai_imaging.eagle_eye_remote.crm.hosting.requests.Session',HTTP)
    with pytest.raises(RequestFailed):
        obj.process_request('device','POST','/v1/crm/logout',{'accessToken':'foreign-token'},principal='pacs:synthetic')
    assert seen[0]['json']=={}
    assert seen[0]['headers']['Authorization']=='Bearer '
    with pytest.raises(RequestFailed,match='session'):
        obj.process_request('device','POST','/v1/crm/logout',{},session='foreign-token',principal='pacs:synthetic')
    assert len(seen)==1
