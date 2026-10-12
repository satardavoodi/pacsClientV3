"""Synthetic liveness never confers permission to execute business work."""
import asyncio
import hashlib
import threading
from types import SimpleNamespace
import pytest
from modules.ai_imaging.eagle_eye_remote import secretary_pipe as pipe
from modules.ai_imaging.eagle_eye_remote.user_access import UserAuthority, UserDenied
from modules.ai_imaging.eagle_eye_remote.secretary_remote import NativeRemote, RemoteError
from modules.ai_imaging.eagle_eye_remote.admission import Admission
OWNER='synthetic-owner'
INSTANCE='00000000-0000-4000-8000-000000000001'

class Channel:
 def __init__(self):self.sent=[];self.closes=0;self.response=None
 def send(self,value,timeout):self.sent.append(value);self.response={'id':value['id'],'result':{'ok':True,'runtime_instance':INSTANCE}}
 def receive(self,timeout):return self.response
 def close(self):self.closes+=1

@pytest.mark.parametrize('status,code',[(503,'UPSTREAM_IDENTITY_UNAVAILABLE'),(429,'UPSTREAM_AUTH_BUSY')])
def test_typed_pre_send_failure_has_no_close_or_uncertain_lease(status,code):
 channel=Channel();calls=[]
 def authority():calls.append('upstream');raise UserDenied(status,code)
 rpc=pipe.PipeRPC(channel,authority,OWNER)
 remote=NativeRemote(Admission());epoch=remote.attach(OWNER,INSTANCE,rpc)
 with pytest.raises(RemoteError) as caught:remote._call(OWNER,'status',{})
 assert caught.value.status==status and caught.value.code==code
 assert channel.sent==[] and channel.closes==0 and calls==['upstream']
 assert remote.admission.snapshot()['completion_uncertain'] is False
 rpc.authority=lambda:calls.append('fresh-upstream') or OWNER
 assert remote._call(OWNER,'status',{})['ok'] is True
 assert calls==['upstream','fresh-upstream'] and len(channel.sent)==1
 remote.close()

@pytest.mark.parametrize('status,code',[(401,'USER_SESSION_REQUIRED'),(403,'EAGLE_PERMISSION_DENIED'),(503,'OTHER_UNAVAILABLE')])
def test_definitive_or_untyped_auth_failure_still_closes(status,code):
 channel=Channel()
 def authority():raise UserDenied(status,code)
 rpc=pipe.PipeRPC(channel,authority,OWNER)
 with pytest.raises(UserDenied):rpc('status',{'owner_id':OWNER})
 assert channel.sent==[] and channel.closes==1

def test_post_send_typed_failure_still_closes_and_is_not_known_rejection():
 channel=Channel()
 def receive(timeout):raise UserDenied(503,'UPSTREAM_IDENTITY_UNAVAILABLE')
 channel.receive=receive;rpc=pipe.PipeRPC(channel,lambda:OWNER,OWNER)
 with pytest.raises(UserDenied):rpc('status',{'owner_id':OWNER})
 assert len(channel.sent)==1 and channel.closes==1

def test_sustained_virtual_outage_transport_ping_does_not_call_upstream():
 channel=Channel();upstream=[];local=[]
 def authority():upstream.append(True);raise UserDenied(503,'UPSTREAM_IDENTITY_UNAVAILABLE')
 rpc=pipe.PipeRPC(channel,authority,OWNER,transport_authority=lambda:local.append(True) or OWNER)
 for virtual_second in range(0,46,5):assert rpc('transport.ping',{'owner_id':OWNER})['ok'] is True
 assert len(local)==10 and upstream==[] and len(channel.sent)==10 and channel.closes==0
 with pytest.raises(pipe.AuthorityBeforeSend):rpc('status',{'owner_id':OWNER})
 assert len(upstream)==1 and len(channel.sent)==10 and channel.closes==0

def test_ping_without_transport_authority_cannot_bypass_auth():
 channel=Channel();rpc=pipe.PipeRPC(channel,lambda:OWNER,OWNER)
 with pytest.raises(ConnectionError):rpc('transport.ping',{'owner_id':OWNER})
 assert channel.sent==[] and channel.closes==1

@pytest.mark.parametrize('fault',['expired','disabled','secretary_revoked','wrong_device','logout'])
def test_local_transport_validation_denials(fault):
 authority=object.__new__(UserAuthority);authority.lock=threading.Lock();token='x'*40;key=hashlib.sha256(token.encode()).hexdigest()
 authority.sessions={key:{'device':'device','expires':float('inf'),'principal':OWNER}}
 user={'principal':OWNER,'enabled':True,'secretary':True};authority.store=SimpleNamespace(user=lambda principal:user)
 if fault=='expired':authority.sessions[key]['expires']=0
 if fault=='disabled':user['enabled']=False
 if fault=='secretary_revoked':user['secretary']=False
 if fault=='logout':authority.sessions.clear()
 with pytest.raises(UserDenied):authority.verify_transport('foreign' if fault=='wrong_device' else 'device',token,'secretary')

def test_gui_ping_is_identity_only_and_does_not_read_session():
 from PacsClient.pacs.workstation_ui.home_ui.secretary_native_runtime import NativeSecretaryRuntime
 runtime=object.__new__(NativeSecretaryRuntime);runtime.closed=False;runtime.owner=OWNER;runtime.owner_getter=lambda:OWNER;runtime.runtime_instance=INSTANCE
 runtime._session=lambda:(_ for _ in ()).throw(AssertionError('No session or patient reads'))
 assert asyncio.run(runtime.dispatch('transport.ping',{'owner_id':OWNER}))=={'ok':True,'runtime_instance':INSTANCE}
 assert asyncio.run(runtime.dispatch('transport.ping',{'owner_id':'foreign'}))['error_code']=='OWNER_MISMATCH'

@pytest.mark.parametrize('reject_on,expected,uncertain,sends',[(1,'failed',False,0),(2,'completion_unknown',True,1)])
def test_initial_submission_and_later_poll_failure_have_distinct_completion(reject_on,expected,uncertain,sends,monkeypatch):
 from modules.ai_imaging.eagle_eye_remote import secretary_remote as facade
 monkeypatch.setattr(facade,'time',SimpleNamespace(sleep=lambda seconds:None))
 channel=Channel();auth_calls=[]
 def authority():
  auth_calls.append(True)
  if len(auth_calls)==reject_on:raise UserDenied(503,'UPSTREAM_IDENTITY_UNAVAILABLE')
  return OWNER
 def send(value,timeout):
  channel.sent.append(value);channel.response={'id':value['id'],'result':{'ok':True,'runtime_instance':INSTANCE,'state':'queued'}}
 channel.send=send;rpc=pipe.PipeRPC(channel,authority,OWNER);remote=NativeRemote(Admission());epoch=remote.attach(OWNER,INSTANCE,rpc)
 request='00000000-0000-4000-8000-000000000002';session='00000000-0000-4000-8000-000000000003';key=(OWNER,request)
 remote.records[key]={'binding':remote._binding(OWNER),'lease':remote.admission.begin('secretary'),
  'value':{'protocol':1,'runtime_id':epoch,'request_id':request,'session_id':session,'state':'queued','output':None}}
 body={'request_id':request,'session_id':session,'kind':'text','text':'synthetic','interaction_mode':'act','language_preference':'en'}
 remote._run(OWNER,body,False,key)
 assert remote.records[key]['value']['state']==expected
 assert remote.admission.snapshot()['completion_uncertain'] is uncertain
 assert len(channel.sent)==sends and channel.closes==0 and len(auth_calls)==reject_on
 assert all(frame['operation']=='command.submit' for frame in channel.sent)
 remote.close()

@pytest.mark.parametrize('operation',['status','admission.hold','admission.release','command.submit'])
def test_business_and_transition_never_use_transport_permission(operation):
 channel=Channel();calls=[]
 def authority():calls.append('upstream');raise UserDenied(403,'EAGLE_PERMISSION_DENIED')
 rpc=pipe.PipeRPC(channel,authority,OWNER,transport_authority=lambda:calls.append('local') or OWNER)
 with pytest.raises(UserDenied):rpc(operation,{'owner_id':OWNER})
 assert calls==['upstream'] and channel.sent==[] and channel.closes==1

@pytest.mark.parametrize('bad',['owner_error','runtime_mismatch','healthy'])
def test_actual_host_validates_ping_and_preserves_transition_boundaries(monkeypatch,bad):
 class Closed:
  def __init__(self):self.cycles=0
  def is_set(self):return self.cycles>=10
  def wait(self,seconds):
   if seconds==5:self.cycles+=1;return self.cycles>=10
   return True
 channel=Channel();channel.accept=lambda:None;first=[True];upstream=[];local=[]
 def receive(timeout):
  if first[0]:first[0]=False;return {'protocol':1,'session':'synthetic','runtime_instance':INSTANCE}
  value=channel.response
  if bad=='owner_error':value['result']={'ok':False,'runtime_instance':INSTANCE,'error_code':'OWNER_MISMATCH'}
  if bad=='runtime_mismatch':value['result']['runtime_instance']='00000000-0000-4000-8000-000000000099'
  return value
 def send(value,timeout=None):
  channel.sent.append(value)
  if 'id' in value:channel.response={'id':value['id'],'result':{'ok':True,'runtime_instance':INSTANCE}}
 channel.receive=receive;channel.send=send
 remote=NativeRemote(Admission());host=pipe.NativePipeHost(remote,lambda token:upstream.append(True) or OWNER,
  validate_transport_session=lambda token:local.append(True) or OWNER)
 host.channel=channel;host.closed=Closed();host._run()
 assert upstream==[True]
 pings=[v for v in channel.sent if v.get('operation')=='transport.ping']
 assert len(pings)==(9 if bad=='healthy' else 1) and len(local)==len(pings)
 assert all(set(v['payload'])=={'owner_id'} for v in pings)
 assert channel.closes>=1 and remote.rpc is None
 if bad!='healthy':assert remote.admission.snapshot()['completion_uncertain'] is True
 remote.close()

def test_expired_rpc_budget_never_becomes_recoverable_auth_rejection(monkeypatch):
 clock=[0.0];monkeypatch.setattr(pipe,'time',SimpleNamespace(monotonic=lambda:clock[0]))
 channel=Channel()
 def authority():clock[0]=16.0;raise UserDenied(503,'UPSTREAM_IDENTITY_UNAVAILABLE')
 rpc=pipe.PipeRPC(channel,authority,OWNER)
 with pytest.raises(UserDenied):rpc('status',{'owner_id':OWNER})
 assert channel.closes==1 and channel.sent==[]
