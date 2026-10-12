"""Actual framed legacy event stream, synthetic identities, no clinical services."""
import json
import socket
import threading
import time
import pytest

from modules.network.workflow_realtime import WorkflowReceiver, receive
from modules.network.home_live_workflow import EnrichmentWorker


def wait_for(predicate, timeout=4):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():
            return
        time.sleep(.01)
    pytest.fail('Synthetic live workflow deadline')


@pytest.fixture
def legacy_server():
    listener=socket.socket(); listener.bind(('127.0.0.1',0)); listener.listen(); listener.settimeout(.1)
    stop=threading.Event()
    state={'voice':0,'valid':True,'calls':[],'stream':None,'errors':[],'lock':threading.Lock()}
    peers=[]; workers=[]
    def reply(peer,payload):
        body=json.dumps(payload).encode()
        with state['lock']:
            peer.sendall(len(body).to_bytes(4,'big')+body)
    state['reply']=reply
    def handle(peer):
        peer.settimeout(1)
        try:
            while not stop.is_set():
                try: request=receive(peer,timeout=.3)
                except TimeoutError: continue
                except ConnectionError: break
                assert request['token']=='synthetic-token'
                endpoint=request['endpoint']; state['calls'].append(endpoint)
                response={'status':'success','request_id':request['request_id']}
                if endpoint=='SubscribeToEvents':
                    state['stream']=peer
                    response['data']={'subscribed':True}
                elif endpoint=='VerifyToken':
                    assert request['params']['token']=='synthetic-token'
                    response.update(valid=state['valid'])
                    if not state['valid']: response['status']='error'
                elif endpoint=='ping': response['message']='pong'
                elif endpoint=='GetPatientStatus':
                    response['data']={'patient_id':'synthetic','latest_study':{'study_uid':'1.2.3'},
                        'studies':[{'study_uid':'1.2.3','voice_count':state['voice'],'report_status':'pending'}]}
                else: raise AssertionError('Unexpected legacy endpoint')
                reply(peer,response)
        except (OSError, ConnectionError): pass
        except Exception as error: state['errors'].append(type(error).__name__)
        finally: peer.close()
    def accept():
        while not stop.is_set():
            try: peer,_=listener.accept()
            except socket.timeout: continue
            except OSError: break
            peers.append(peer); worker=threading.Thread(target=handle,args=(peer,)); workers.append(worker); worker.start()
    thread=threading.Thread(target=accept); thread.start()
    state['address']=listener.getsockname()
    yield state
    stop.set(); listener.close()
    for peer in peers:
        try: peer.shutdown(socket.SHUT_RDWR)
        except OSError: pass
        peer.close()
    thread.join(2)
    for worker in workers: worker.join(2)


def receiver_for(server, **kwargs):
    receiver=WorkflowReceiver(*server['address'],'synthetic-token',allow_legacy=True,
        allow_legacy_events=True,transform=lambda states:states,**kwargs)
    receiver.watch({'1.2.3':(0,'synthetic')})
    receiver.start()
    return receiver


def test_existing_broadcast_is_live_without_v1_snapshot_or_periodic_sleep(legacy_server):
    receiver=receiver_for(legacy_server)
    try:
        wait_for(lambda:receiver.status=='connected_legacy' and 'GetPatientStatus' in legacy_server['calls'])
        wait_for(lambda:bool(receiver.mailbox.states))
        assert receiver.mailbox.drain()[0]['audio_count']==0
        legacy_server['voice']=2
        legacy_server['reply'](legacy_server['stream'],{'type':'broadcast','event_type':'audio_uploaded',
            'data':{'study_uid':'1.2.3','patient_id':'synthetic'}})
        wait_for(lambda:bool(receiver.mailbox.states),timeout=2)
        assert receiver.mailbox.drain()[0]['audio_count']==2
        assert receiver.status=='connected_legacy' and not legacy_server['errors']
        assert 'GetWorkflowStates' not in legacy_server['calls'] and 'GetPatientList' not in legacy_server['calls']
    finally:
        receiver.stop(); receiver.join(3)
    assert not receiver.is_alive()


def test_slow_reception_cannot_delay_voice_or_event_reader(legacy_server):
    started=threading.Event(); release=threading.Event()
    def enrich(states):
        started.set(); release.wait(3)
        return states
    receiver=receiver_for(legacy_server,enrich=enrich)
    try:
        assert started.wait(2)
        assert receiver.mailbox.drain()[0]['audio_count']==0
        legacy_server['voice']=1
        legacy_server['reply'](legacy_server['stream'],{'type':'broadcast','event_type':'audio_uploaded',
            'data':{'study_uid':'1.2.3','patient_id':'synthetic'}})
        wait_for(lambda:bool(receiver.mailbox.states),timeout=2)
        assert receiver.mailbox.drain()[0]['audio_count']==1
        assert receiver.status=='connected_legacy'
    finally:
        release.set(); receiver.stop(); receiver.join(3)
        receiver.enrichment.join(3)


def test_legacy_stream_is_not_online_with_rejected_session(legacy_server):
    legacy_server['valid']=False
    receiver=receiver_for(legacy_server)
    receiver.join(2)
    assert receiver.status=='unavailable' and not receiver.is_alive()
    assert 'GetPatientStatus' not in legacy_server['calls']


def test_outside_study_event_does_not_fetch_or_update_another_patient(legacy_server):
    receiver=receiver_for(legacy_server)
    try:
        wait_for(lambda:bool(receiver.mailbox.states)); receiver.mailbox.drain()
        count=legacy_server['calls'].count('GetPatientStatus')
        legacy_server['reply'](legacy_server['stream'],{'type':'broadcast','event_type':'audio_uploaded',
            'data':{'study_uid':'outside','patient_id':'other'}})
        time.sleep(.3)
        assert legacy_server['calls'].count('GetPatientStatus')==count
        assert receiver.mailbox.drain()==[]
    finally:
        receiver.stop(); receiver.join(3)


def test_stale_enrichment_is_discarded_and_fast_observation_is_not_replayed():
    started=threading.Event(); release=threading.Event()
    def enrich(states):
        started.set(); release.wait(2)
        return states
    worker=EnrichmentWorker(enrich); worker.start()
    try:
        worker.submit([{'study_uid':'1.2.3','patient_id':'synthetic','audio_count':0}])
        assert started.wait(1)
        worker.submit([{'study_uid':'1.2.3','patient_id':'synthetic','audio_count':2}])
        release.set()
        wait_for(lambda:bool(worker.results))
        result=worker.drain()
        assert len(result)==1 and result[0]['audio_count']==2 and result[0]['_report_only']
    finally:
        worker.stop(); worker.join(2)


def test_reconnect_reverifies_session_and_reconciles_without_another_search(legacy_server):
    receiver=receiver_for(legacy_server)
    try:
        wait_for(lambda:bool(receiver.mailbox.states)); receiver.mailbox.drain()
        legacy_server['voice']=3
        legacy_server['stream'].shutdown(socket.SHUT_RDWR)
        wait_for(lambda:legacy_server['calls'].count('VerifyToken')>=2)
        wait_for(lambda:bool(receiver.mailbox.states))
        assert receiver.mailbox.drain()[0]['audio_count']==3
        assert receiver.status=='connected_legacy'
    finally:
        receiver.stop(); receiver.join(3)


def test_session_revocation_disconnects_stream_and_prevents_further_delivery(legacy_server,monkeypatch):
    from modules.network import workflow_realtime
    monkeypatch.setattr(workflow_realtime,'LEGACY_VERIFY_SECONDS',.1)
    receiver=receiver_for(legacy_server)
    try:
        wait_for(lambda:bool(receiver.mailbox.states)); receiver.mailbox.drain()
        legacy_server['valid']=False
        wait_for(lambda:receiver.status=='unavailable')
        receiver.join(2)
        assert not receiver.is_alive() and receiver.mailbox.drain()==[]
    finally:
        receiver.stop(); receiver.join(3)


def test_event_burst_is_coalesced_into_bounded_inventory_reads(legacy_server):
    receiver=receiver_for(legacy_server)
    try:
        wait_for(lambda:bool(receiver.mailbox.states)); receiver.mailbox.drain()
        previous=legacy_server['calls'].count('GetPatientStatus')
        legacy_server['voice']=4
        for _ in range(100):
            legacy_server['reply'](legacy_server['stream'],{'type':'broadcast','event_type':'audio_uploaded',
                'data':{'study_uid':'1.2.3'}})
        wait_for(lambda:bool(receiver.mailbox.states))
        time.sleep(.3)
        assert receiver.mailbox.drain()[0]['audio_count']==4
        assert legacy_server['calls'].count('GetPatientStatus')-previous<=3
    finally:
        receiver.stop(); receiver.join(3)


def test_enrichment_stop_never_delivers_a_late_completed_result():
    started=threading.Event(); release=threading.Event()
    def enrich(states):
        started.set(); release.wait(2); return states
    worker=EnrichmentWorker(enrich); worker.start()
    worker.submit([{'study_uid':'1.2.3','patient_id':'synthetic'}])
    assert started.wait(1)
    worker.stop(); release.set(); worker.join(2)
    assert worker.drain()==[] and not worker.is_alive()


def test_v1_snapshot_also_publishes_voice_before_slow_report_enrichment(monkeypatch):
    from modules.network import workflow_realtime as module
    started=threading.Event(); release=threading.Event()
    def enrich(states):
        started.set(); release.wait(2); return states
    receiver=WorkflowReceiver('synthetic',1,'synthetic',transform=lambda states:states,enrich=enrich)
    class Peer:
        def close(self): pass
    monkeypatch.setattr(receiver,'_connect',lambda:Peer())
    monkeypatch.setattr(module,'send',lambda *args:'request')
    monkeypatch.setattr(module,'receive',lambda peer:{'status':'success','request_id':'request',
        'data':{'realtime_version':1,'states':[{'study_uid':'1.2.3','patient_id':'synthetic',
            'audio_count':1,'report_status':'pending','assignment':{}}]}})
    receiver.enrichment.start()
    try:
        receiver._snapshot(('1.2.3',))
        assert started.wait(1)
        assert receiver.mailbox.drain()[0]['audio_count']==1
    finally:
        release.set(); receiver.stop(); receiver.enrichment.join(2)


def test_three_node_legacy_bridge_wakes_only_verified_same_center_case(legacy_server,tmp_path):
    from types import SimpleNamespace
    from modules.ai_imaging.eagle_eye_remote.case_realtime import CaseService
    from modules.ai_imaging.eagle_eye_remote.pacs_case_bridge import PacsCaseBridge
    case={'study_uid':'1.2.3','patient_id':'synthetic'}
    source=SimpleNamespace(config={'url':'http://127.0.0.1'},
        session=SimpleNamespace(headers={'Authorization':'Bearer synthetic-token'}),
        case_identity=lambda uid:dict(case))
    jobs=SimpleNamespace(source=source,lock=threading.RLock(),jobs={},root=tmp_path)
    cases=CaseService(jobs,None,{'first':'center','second':'center','outside':'other'},'center')
    cases.authorize('first',case); cases.authorize('second',case)
    bridge=PacsCaseBridge(cases,{'url':'http://127.0.0.1','socket_port':legacy_server['address'][1]})
    jobs.case_bridge=bridge; bridge.start()
    try:
        wait_for(lambda:bridge.status=='connected_legacy' and bool(cases.workflow))
        assert cases.snapshot('second',case)['workflow']['audio_count']==0
        cursor=cases.events.cursor()
        legacy_server['voice']=2
        legacy_server['reply'](legacy_server['stream'],{'type':'broadcast','event_type':'audio_uploaded',
            'data':dict(case,clinical_text='Synthetic private content')})
        wait_for(lambda:cases.workflow['1.2.3']['audio_count']==2)
        assert cases.events.wait(cursor,'1.2.3',timeout=0)['changed']
        assert cases.snapshot('second',case)['workflow']['audio_count']==2
        assert all(len(item)==2 for item in cases.events.ring)
        with pytest.raises(PermissionError): cases.snapshot('outside',case)
    finally:
        bridge.stop(); bridge.join(3)
    assert not bridge.is_alive()


def test_receiver_shutdown_retains_ownership_until_slow_enrichment_quiesces(monkeypatch):
    started = threading.Event(); release = threading.Event()
    def enrich(states):
        started.set(); release.wait(3); return states
    receiver = WorkflowReceiver('synthetic', 1, 'synthetic', transform=lambda states:states, enrich=enrich)
    def run_without_network():
        receiver._deliver([{'study_uid':'1.2.3','patient_id':'synthetic',
            'audio_count':1,'report_status':'pending','assignment':{}}], ('1.2.3',))
        receiver.stopped.wait(3)
    monkeypatch.setattr(receiver, '_run', run_without_network)
    receiver.start()
    try:
        assert started.wait(1)
        before = time.monotonic()
        receiver.stop()
        assert time.monotonic() - before < .2  # GUI stop stays nonblocking.
        receiver.join(.1)
        assert receiver.is_alive()  # Source switching cannot orphan this worker.
    finally:
        release.set(); receiver.stop(); receiver.join(2)
    assert not receiver.is_alive() and not receiver.enrichment.is_alive()
    assert receiver.drain_enrichment() == []


def test_silent_connection_can_be_stopped_without_waiting_on_the_calling_thread(legacy_server):
    receiver = receiver_for(legacy_server)
    try:
        wait_for(lambda:receiver.status == 'connected_legacy')
        before = time.monotonic()
        receiver.stop()
        assert time.monotonic() - before < .2
        receiver.join(3)
        assert not receiver.is_alive()
        assert not receiver.sockets
    finally:
        receiver.stop(); receiver.join(3)


def test_trickling_partial_frame_has_one_total_deadline():
    first, second = socket.socketpair()
    finished = threading.Event()
    def trickle():
        try:
            second.sendall((100).to_bytes(4, 'big'))
            while not finished.wait(.02):
                second.sendall(b' ')
        except OSError:
            pass
    peer = threading.Thread(target=trickle, daemon=True); peer.start()
    before = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            receive(first, timeout=.12)
        assert time.monotonic() - before < .6
    finally:
        finished.set(); first.close(); second.close(); peer.join(1)
