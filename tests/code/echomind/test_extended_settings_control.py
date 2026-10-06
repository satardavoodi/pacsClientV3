"""Synthetic settings receipts: no real patient deletion or settings writes."""
from types import SimpleNamespace
import threading
import time
import pytest
from PySide6.QtWidgets import QApplication
from modules.EchoMind.secretary.command_envelope import validate_action_entities


@pytest.mark.parametrize('values', [
    {'category':'patients'}, {'category':'patients','strategy':'delete_oldest_count'},
    {'category':'patients','strategy':'all','value':30},
    {'category':'cache','strategy':'all'}, {'category':'patients','strategy':'delete_oldest_count','value':True}])
def test_patient_cleanup_rejects_unspecified_or_conflicting_scope(values):
    with pytest.raises(ValueError): validate_action_entities('request_storage_cleanup', values)


def test_patient_cleanup_forwards_scope_without_deleting():
    from PacsClient.utils.assistant_settings_service import AssistantSettingsService
    app = QApplication.instance() or QApplication([])
    calls=[]
    panel=SimpleNamespace(request_assistant_cleanup=lambda category,**kwargs:calls.append((category,kwargs)))
    service=AssistantSettingsService(None,lambda:panel)
    result=service.request_cleanup('patients','delete_oldest_count',30)
    assert result['state']=='awaiting_local_confirmation'
    assert result['deleted_files'] is None
    assert calls==[('patients',{'strategy':'delete_oldest_count','value':30})]


def test_patient_cleanup_defers_preview_and_blocks_duplicate(monkeypatch):
    from PacsClient.pacs.workstation_ui.settings_ui import storage_cleanup_panel as m
    callbacks=[]; jobs=[]
    monkeypatch.setattr(m,'QTimer',SimpleNamespace(singleShot=lambda delay,owner,fn:callbacks.append(fn)))
    panel=SimpleNamespace(_cleanup_thread=None, _can_start_destructive_cleanup=lambda _:True,
        cleanup_manager=SimpleNamespace(build_patient_cleanup_preview=lambda *args:None),
        _confirm_patient_cleanup=lambda *args:None, _on_category_cleanup_failed=lambda *args:None,
        _run_cleanup_job=lambda *args,**kwargs:jobs.append((args,kwargs)))
    method=m.StorageCleanupPanelWidget.request_assistant_cleanup
    assert method(panel,'patients',strategy='all')
    assert not jobs
    callbacks[0]()
    assert len(jobs)==1 and panel._assistant_cleanup_state['state']=='preparing_preview'
    assert method(panel,'patients',strategy='all') is False


def wait(app,service,key):
    deadline=time.monotonic()+3
    while service.operation_status(key)['state']=='running' and time.monotonic()<deadline:
        app.processEvents(); time.sleep(.005)
    return service.operation_status(key)


def test_viewer_write_is_worker_owned_and_read_back(monkeypatch):
    from PacsClient.utils.assistant_settings_service import AssistantSettingsService
    from modules.viewer import viewer_backend_config as b, gpu_boost as g
    app=QApplication.instance() or QApplication([])
    values={'backend':'pydicom_qt','gpu_boost':False}; threads=[]
    def save(key,value): threads.append(threading.get_ident()); values[key]=value
    monkeypatch.setattr(b,'save_viewer_backend',lambda value:save('backend',value))
    monkeypatch.setattr(b,'load_viewer_backend',lambda:values['backend'])
    monkeypatch.setattr(g,'save_gpu_boost_enabled',lambda value:save('gpu_boost',value))
    monkeypatch.setattr(g,'load_gpu_boost_enabled',lambda:values['gpu_boost'])
    service=AssistantSettingsService(None,lambda:None)
    response=service.set_viewer_preferences('vtk_simpleitk',True)
    result=wait(app,service,response['operation_id'])
    assert result['state']=='succeeded'
    assert result['data']['restart_required'] and not result['data']['active_viewers_changed']
    assert threads and all(t!=threading.get_ident() for t in threads)


def test_memory_release_uses_current_process_only_and_reports_measurements(monkeypatch):
    import psutil,ctypes
    from PacsClient.utils.assistant_settings_service import AssistantSettingsService
    app=QApplication.instance() or QApplication([])
    readings=iter([1000,700]); handles=[]
    monkeypatch.setattr(psutil,'Process',lambda:SimpleNamespace(memory_info=lambda:SimpleNamespace(rss=next(readings))))
    class Function:
        def __init__(self,fn): self.fn=fn
        def __call__(self,*args): return self.fn(*args)
    kernel=SimpleNamespace(GetCurrentProcess=Function(lambda:42))
    api=SimpleNamespace(EmptyWorkingSet=Function(lambda handle:handles.append(handle) or 1))
    monkeypatch.setattr(ctypes,'WinDLL',lambda name,**kwargs:kernel if name=='kernel32' else api)
    service=AssistantSettingsService(None,lambda:None)
    result=wait(app,service,service.release_memory()['operation_id'])
    assert result['state']=='succeeded' and handles==[42]
    assert result['data']['released_resident_bytes']==300
    assert result['data']['deleted_files']==0


def test_new_controls_are_exposed_with_mutation_permissions():
    from modules.EchoMind.secretary.adapters.settings_command_adapter import SETTINGS_ACTIONS
    from modules.EchoMind.secretary.permissions import decide
    for name in ('release_memory','get_viewer_preferences','set_viewer_preferences'):
        assert name in SETTINGS_ACTIONS
    assert decide('set_viewer_preferences',mode='assistant').requires_confirmation
    assert not decide('release_memory',mode='read_only').allowed


def test_operation_workflow_captures_handles_and_polls_before_completion():
    from modules.EchoMind.secretary.workflow import build_plan, WorkflowExecutor
    calls=[]
    def run(action,entities):
        calls.append(action)
        if action=='release_memory':
            return {'ok':True,'data':{'operation_id':'synthetic-op','state':'running'}}
        assert action=='settings_operation_status'
        assert entities['operation_id']=='synthetic-op'
        return {'ok':True,'data':{'state':'succeeded','data':{'released_resident_bytes':12}}}
    result=WorkflowExecutor(run,sleep=lambda _:None).run(build_plan('Synthetic memory release',[
        {'action':'release_memory','entities':{}}]))
    assert result.ok and calls==['release_memory','settings_operation_status']


def test_cleanup_cancel_stops_workflow_without_following_action():
    from modules.EchoMind.secretary.workflow import build_plan, WorkflowExecutor
    calls=[]
    def run(action,entities):
        calls.append(action)
        if action=='request_storage_cleanup':
            return {'ok':True,'data':{'state':'awaiting_local_confirmation'}}
        return {'ok':True,'data':{'state':'cancelled_or_blocked'}}
    result=WorkflowExecutor(run,sleep=lambda _:None).run(build_plan('Synthetic cleanup',[
        {'action':'request_storage_cleanup','entities':{'category':'patients','strategy':'all'}},
        {'action':'open_settings','entities':{}}]))
    assert not result.ok and 'open_settings' not in calls
