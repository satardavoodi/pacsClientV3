"""Synthetic conversation identity, reset and server-context guards."""
import json
import sqlite3
from uuid import UUID
import pytest
from modules.EchoMind.secretary.memory import memory_store as ms

@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, '_MEMORY_DIR', tmp_path/'memory')
    monkeypatch.setattr(ms, '_db_conn', lambda: sqlite3.connect(tmp_path/'test.db'))
    return ms.EchoMindMemoryStore()

def test_identity_modes_new_and_private_persistence(store):
    first=store.get_conversation('act')
    UUID(first['id'])
    assert store.get_conversation('ask')['id']==first['id']
    enriched={**store.get_conversation('ask'), 'title':'Viewer settings', 'topic':'Settings', 'goal':'Review modality grid', 'summary':'Discussing visible modalities.'}
    assert store.update_conversation(enriched)
    store.start_cycle('Synthetic follow-up');store.close_cycle()
    saved=json.loads(store._filepath.with_suffix('.conversation.json').read_text())
    assert saved==enriched
    store.new_memory()
    assert store.get_conversation('act')['id']!=first['id']
    assert store.get_conversation('act')['summary']==''
    assert not store.update_conversation(enriched)

def test_rollover_before_planning_drops_previous_context(store):
    for _ in range(10):
        store.start_cycle('Synthetic request');store.close_cycle()
    old=store.get_conversation('act')['id']
    store.prepare_conversation('guide')
    assert store.get_conversation('guide')['id']!=old
    assert store.get_context_for_llm()==''

def test_server_metadata_is_quoted_and_cannot_override_mode(monkeypatch, store):
    from modules.ai_imaging.eagle_eye_remote.secretary import service
    owner=object.__new__(service.Secretary);owner.modules=['homepage']
    captured=[]
    def complete(system,payload,route=False):
        captured.append((system,payload))
        return {'modules':['homepage'],'reason':'Synthetic route','conversation':{'title':'Patient search','topic':'Search','goal':'Review matching studies','summary':'Discussing search filters.'}}
    monkeypatch.setattr(owner,'_completion',complete)
    request=service.Request.model_validate(dict(protocol=1,request_id=str(__import__('uuid').uuid4()),phase='plan',text='Synthetic search',language='en',client_time='2026-10-09T10:00:00+03:30',interaction_mode='ask',conversation=store.get_conversation('ask')))
    routed=owner._route(request)
    assert routed['conversation']['id']==request.conversation.id
    assert routed['conversation']['mode']=='ask'
    assert captured[0][1]['quoted_conversation']['id']==request.conversation.id
    assert 'not authorization' in captured[0][0]
    with pytest.raises(ValueError):
        service.Request.model_validate({**request.model_dump(),'interaction_mode':'act'})

def test_server_answer_receives_context_without_executing(tmp_path, monkeypatch, store):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import EchoMind
    from modules.ai_imaging.eagle_eye_remote.secretary.service import Secretary
    (tmp_path/'settings.json').write_text('{}')
    echo=EchoMind({'config_dir':str(tmp_path),'history_dir':str(tmp_path/'echo')}, ['client'])
    server=Secretary({'history_dir':str(tmp_path/'secretary')}, echo)
    captured=[]
    def complete(system,payload,route=False):
        captured.append(payload)
        if route:
            return {'modules':['homepage'],'reason':'Synthetic route','conversation':{'title':'Daily workload','topic':'MRI reporting','goal':'Review remaining reports','summary':'User is checking reporting workload.'}}
        assert payload['quoted_conversation']['title']=='Daily workload'
        assert payload['quoted_memory_context']=='Synthetic preceding exchange'
        return {'answer':'The current data does not establish a count.'}
    monkeypatch.setattr(server,'_completion',complete)
    result=server.process('client', dict(protocol=1,request_id=str(__import__('uuid').uuid4()),phase='plan',text='Synthetic follow-up',language='en',client_time='2026-10-09T10:00:00+03:30',interaction_mode='ask',conversation=store.get_conversation('ask'),memory_context='Synthetic preceding exchange'))
    assert result['plan'] is None
    assert result['conversation']['id']==store.get_conversation('ask')['id']
    assert result['conversation']['summary']=='User is checking reporting workload.'
    assert len(captured)==2


def test_metadata_rejects_permissions_and_stale_modes(store):
    from modules.ai_imaging.eagle_eye_remote.secretary.conversation import Conversation
    context=store.get_conversation('act')
    with pytest.raises(ValueError):
        Conversation.model_validate({**context,'approved':True})
    with pytest.raises(ValueError):
        Conversation.model_validate({**context,'summary':'x'*1001})
    store.get_conversation('ask')
    assert not store.update_conversation({**context,'title':'Stale answer'})

def test_widget_displays_title_mode_and_full_identity(store, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from types import SimpleNamespace
    import sys
    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace())
    from PacsClient.pacs.workstation_ui.home_ui.secretary_button_widget import SecretaryButtonWidget
    app=QApplication.instance() or QApplication([])
    widget=SecretaryButtonWidget()
    widget._secretary_orchestrator=SimpleNamespace(memory_store=store)
    context=store.get_conversation('act')
    store.update_conversation({**context,'title':'Viewer configuration','goal':'Review modality grid'})
    widget._refresh_memory_label()
    assert 'Viewer configuration' in widget.memory_label.text()
    assert context['id'] in widget.memory_label.toolTip()
    widget.mode_selector.setCurrentIndex(widget.mode_selector.findData('guide'))
    assert 'Guide' in widget.memory_label.text()
    assert context['id'] in widget.memory_label.toolTip()
    widget.close()
    app.processEvents()

def test_help_ticket_worker_uses_same_conversation(store, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from types import SimpleNamespace
    from concurrent.futures import ThreadPoolExecutor
    import sys
    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace())
    from PacsClient.pacs.workstation_ui.home_ui.secretary_button_widget import SecretaryButtonWidget
    from modules.EchoMind.secretary import remote_planner
    app=QApplication.instance() or QApplication([])
    widget=SecretaryButtonWidget()
    widget._secretary_orchestrator=SimpleNamespace(memory_store=store)
    widget._ensure_secretary_runtime=lambda:True
    scheduled=[]
    widget._run_worker=lambda work,done,failed:scheduled.append(work)
    def request(phase,text,**fields):
        assert fields['conversation']['mode']=='help_ticket'
        assert fields['conversation']['id']==store.get_conversation('help_ticket')['id']
        return {'conversation':{**fields['conversation'],'title':'Upload problem'}}
    monkeypatch.setattr(remote_planner,'request',request)
    widget._prepare_help_ticket('Synthetic upload problem')
    with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(scheduled[0]).result()
    assert store.get_current_info()[1]==1
    assert store.get_conversation('help_ticket')['title']=='Upload problem'
    widget.close()
    app.processEvents()
