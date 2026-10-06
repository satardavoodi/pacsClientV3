from modules.EchoMind.secretary.adapters.home_selection_adapter import HomeSelectionAdapter
from modules.EchoMind.secretary.command_envelope import CommandPlan, validate_action_entities
import pytest

def test_prepared_cd_dialog_does_not_run_filesystem_or_drive_preflight_on_gui(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from modules.cd_burner import cd_burn_dialog as module
    app=QApplication.instance() or QApplication([])
    def forbidden(*args,**kwargs):
        raise AssertionError('Preflight was repeated on the GUI thread')
    for name in ('get_available_drives','check_imapi2_available','check_pydicom_available','load_center_identity'):
        monkeypatch.setattr(module,name,forbidden)
    monkeypatch.setattr(module.CDBurnManager,'get_studies_size_estimate',forbidden)
    monkeypatch.setattr(module.CDBurnManager,'get_media_info',forbidden)
    monkeypatch.setattr(module.CDBurnManager,'get_write_speeds',forbidden)
    prepared={'studies':[],'downloaded':[],'missing':[], 'size_mb':0,'identity':{},
              'viewer':{'path':None},'series':{},'drives':[{'id':'synthetic-drive','name':'Synthetic'}],
              'speeds':{'synthetic-drive':[]},'media':{'synthetic-drive':{'present':False}},
              'viewer_mb':0,'pydicom':True,'imapi':True}
    dialog=module.CDBurnDialog([],prepared=prepared)
    assert dialog.windowTitle()=='Write to CD/DVD'
    assert not dialog.is_burning
    dialog.close()

def test_media_preparation_revalidates_selection_and_redacts_private_snapshot(monkeypatch):
    import types
    import aipacs_runtime
    from modules.EchoMind.secretary.adapters.media_selection_adapter import MediaSelectionAdapter
    monkeypatch.setattr(aipacs_runtime,'is_module_enabled',lambda name:True)
    selections=types.SimpleNamespace(selected=lambda handle:None)
    adapter=MediaSelectionAdapter(selections)
    assert adapter.prepare_selection_media(CommandPlan(action='prepare_selection_media',
        entities={'selection_id':'synthetic'}),{}).error_code=='STALE_SELECTION'
    adapter.preparations['operation']='synthetic'
    adapter.probes=types.SimpleNamespace(status=lambda key:{'state':'succeeded','data':{'private':'never returned'}})
    result=adapter.media_status(CommandPlan(action='media_status',entities={'operation_id':'operation'}),{})
    assert result.data['state']=='failed'
    assert result.data['error_code']=='STALE_SELECTION'
    assert 'private' not in str(result.data)

def test_media_preparation_opens_once_and_returns_only_safe_receipt(monkeypatch):
    import types
    from modules.EchoMind.secretary.adapters.media_selection_adapter import MediaSelectionAdapter
    from modules.cd_burner import cd_burn_dialog as module
    events=[]
    class Dialog:
        def __init__(self,studies,parent,prepared):events.append('constructed')
        def open(self):events.append('opened')
    monkeypatch.setattr(module,'CDBurnDialog',Dialog)
    selections=types.SimpleNamespace(selected=lambda handle:[{'study_uid':'1.2.3'}],home=object())
    adapter=MediaSelectionAdapter(selections)
    adapter.preparations['operation']='synthetic'
    prepared={'studies':[{'patient_name':'Private synthetic value'}], 'downloaded':[], 'missing':[{}]}
    adapter.probes=types.SimpleNamespace(status=lambda key:{'state':'succeeded','data':prepared})
    plan=CommandPlan(action='media_status',entities={'operation_id':'operation'})
    first=adapter.media_status(plan,{})
    second=adapter.media_status(plan,{})
    assert first.data['dialog_open'] and second.data==first.data
    assert events==['constructed','opened']
    assert 'patient_name' not in str(first.data)

ROWS=[{'patient_id':'synthetic-'+str(i),'study_uid':'1.2.3.'+str(i)} for i in range(1,4)]
class Table:
    def __init__(self): self.rows=[dict(r) for r in ROWS];self.checked=set();self.results_table=self
    def rowCount(self): return len(self.rows)
    def get_patient_data_by_row(self,i): return self.rows[i]
    def clear_all_selections(self): self.checked.clear()
    def set_row_checked(self,i,value): self.checked.add(i)
    def get_selected_patient_data_list(self): return [self.rows[i] for i in sorted(self.checked)]
class Home:
    def __init__(self): self.patient_table_widget=Table();self.downloaded=[]
    def _on_download_requested(self,rows,**kwargs):self.downloaded=rows

def test_first_and_third_download_exact_studies():
    home=Home();adapter=HomeSelectionAdapter(home)
    result=adapter.select_patients(CommandPlan(action='select_patients',entities={'row_indices':[1,3]}),{'home_ordered_studies':[r['study_uid'] for r in ROWS]})
    assert result.ok and home.patient_table_widget.checked=={0,2}
    follow=adapter.download_selection(CommandPlan(action='download_selection',entities={'selection_id':result.data['selection_id']}),{'confirmed':True})
    assert follow.ok and [r['study_uid'] for r in home.downloaded]==[ROWS[0]['study_uid'],ROWS[2]['study_uid']]

def test_sort_change_rejects_ordinal_without_mutation():
    home=Home();home.patient_table_widget.rows.reverse();adapter=HomeSelectionAdapter(home)
    result=adapter.select_patients(CommandPlan(action='select_patients',entities={'row_indices':[1]}),{'home_ordered_studies':[r['study_uid'] for r in ROWS]})
    assert not result.ok and not home.patient_table_widget.checked

def test_changed_selection_invalidates_download_receipt():
    home=Home();adapter=HomeSelectionAdapter(home)
    result=adapter.select_patients(CommandPlan(action='select_patients',entities={'study_uids':[ROWS[0]['study_uid']]}),{})
    home.patient_table_widget.checked={1}
    assert not adapter.download_selection(CommandPlan(action='download_selection',entities={'selection_id':result.data['selection_id']}),{'confirmed':True}).ok
    assert not home.downloaded

@pytest.mark.parametrize('indices',[[0],[-1],[True]])
def test_schema_rejects_invalid_ordinals(indices):
    with pytest.raises(ValueError):validate_action_entities('select_patients',{'row_indices':indices})

def test_burn_requires_explicit_target_and_confirmation():
    from modules.EchoMind.secretary.adapters.media_selection_adapter import MediaSelectionAdapter
    adapter=MediaSelectionAdapter(None)
    result=adapter.write_selection_media(CommandPlan(action='write_selection_media',entities={}),{})
    assert result.error_code=='CONFIRM_REQUIRED'
    with pytest.raises(ValueError):validate_action_entities('write_selection_media',{'selection_id':'synthetic','mode':'burn'})


def test_media_worker_rejects_missing_selected_study_before_output(monkeypatch,tmp_path):
    import sys, types
    import aipacs_runtime
    from modules.EchoMind.secretary.adapters.media_selection_adapter import MediaSelectionAdapter
    monkeypatch.setattr(aipacs_runtime,'is_module_enabled',lambda name:True)
    class Signal:
        def __init__(self):self.slots=[]
        def connect(self,slot):self.slots.append(slot)
        def emit(self,*args):
            for slot in self.slots:slot(*args)
    class Worker:
        def __init__(self,**kwargs):
            self.__dict__.update(kwargs);self.completed=Signal();self.progress=Signal();self.finished=Signal();self.called=False
        def _collect_study_folders(self):return []
        def isRunning(self):return False
        def start(self):self.run();self.finished.emit()
        def run(self):self.called=True
        def cancel(self):pass
    monkeypatch.setitem(sys.modules,'modules.cd_burner.cd_burn_manager',types.SimpleNamespace(CDBurnWorker=Worker,BurnOptions=lambda **kwargs:kwargs))
    selection=types.SimpleNamespace(selected=lambda handle:[dict(ROWS[0]),dict(ROWS[1])])
    adapter=MediaSelectionAdapter(selection)
    target=tmp_path/'output'
    result=adapter.write_selection_media(CommandPlan(action='write_selection_media',entities={'selection_id':'synthetic','mode':'folder','output_folder':str(target)}),{'confirmed':True})
    assert result.ok
    assert adapter.operations[result.data['operation_id']]['state']=='failed'
    assert not target.exists()
    assert not adapter.worker.called


def test_search_and_selection_workflow_uses_observed_list_and_receipt():
    from modules.EchoMind.secretary.workflow import WorkflowExecutor,build_plan
    calls=[]
    def run(action,entities):
        calls.append((action,dict(entities)))
        if action=='advanced_search_patients':return {'ok':True,'data':{'state':'searching'}}
        if action=='read_patients':return {'ok':True,'data':{'state':'ready','list_id':'actual-list'}}
        if action=='select_patients':
            assert entities['list_id']=='actual-list'
            return {'ok':True,'data':{'selection_id':'actual-selection','selected_count':2}}
        if action=='download_selection':
            assert entities['selection_id']=='actual-selection'
            return {'ok':True,'data':{'selection_id':'actual-selection','state':'queued'}}
        if action=='download_selection_status':return {'ok':True,'data':{'state':'succeeded'}}
        raise AssertionError(action)
    plan=build_plan('Synthetic workflow',[
        {'action':'advanced_search_patients','entities':{'body_part':'KNEE'}},
        {'action':'select_patients','entities':{'row_indices':[1,3],'list_id':'$list_id'}},
        {'action':'download_selection','entities':{'selection_id':'$selection_id'}}])
    assert WorkflowExecutor(run,sleep=lambda seconds:None).run(plan).ok
    assert [action for action,entities in calls]==['advanced_search_patients','read_patients','select_patients','download_selection','download_selection_status']


def test_running_media_defers_quit_without_waiting():
    import types
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from modules.EchoMind.secretary.adapters.media_selection_adapter import _MediaQuitGuard
    app=QApplication.instance() or QApplication([])
    worker=types.SimpleNamespace(isRunning=lambda:True,cancelled=False)
    worker.cancel=lambda:setattr(worker,'cancelled',True)
    adapter=types.SimpleNamespace(worker=worker,selections=types.SimpleNamespace(home=None))
    guard=_MediaQuitGuard(app,adapter)
    assert guard.eventFilter(app,QEvent(QEvent.Type.Quit)) is True
    assert worker.cancelled and guard.exiting
    worker.isRunning=lambda:False
    assert guard.eventFilter(app,QEvent(QEvent.Type.Quit)) is False
    app.removeEventFilter(guard)
    guard.deleteLater()


@pytest.mark.parametrize('existing',[False,True])
def test_media_folder_preserves_existing_target_and_saved_viewer(monkeypatch,tmp_path,existing):
    import sys, types
    import aipacs_runtime
    from modules.EchoMind.secretary.adapters.media_selection_adapter import MediaSelectionAdapter
    monkeypatch.setattr(aipacs_runtime,'is_module_enabled',lambda name:True)
    class Signal:
        def __init__(self):self.slots=[]
        def connect(self,slot):self.slots.append(slot)
        def emit(self,*args):
            for slot in self.slots:slot(*args)
    class Worker:
        def __init__(self,**kwargs):
            self.__dict__.update(kwargs);self.completed=Signal();self.progress=Signal();self.finished=Signal();self.called=False
        def _collect_study_folders(self):return ['synthetic-local-content']
        def isRunning(self):return False
        def start(self):self.run();self.finished.emit()
        def run(self):self.called=True;self.completed.emit(True,'Synthetic output')
        def cancel(self):pass
    monkeypatch.setitem(sys.modules,'modules.cd_burner.cd_burn_manager',types.SimpleNamespace(CDBurnWorker=Worker,BurnOptions=lambda **kwargs:types.SimpleNamespace(**kwargs)))
    monkeypatch.setitem(sys.modules,'modules.cd_burner.center_identity',types.SimpleNamespace(load_center_identity=lambda:{'center_name':'Synthetic center'}))
    monkeypatch.setitem(sys.modules,'PacsClient.pacs.workstation_ui.settings_ui.lightviewer_settings',types.SimpleNamespace(LightViewerSettingsWidget=types.SimpleNamespace(get_viewer_selection=lambda:{'path':'synthetic-saved-viewer','display_name':'Synthetic viewer'})))
    selection=types.SimpleNamespace(selected=lambda handle:[dict(ROWS[0])])
    adapter=MediaSelectionAdapter(selection)
    target=tmp_path/'output'
    if existing:target.mkdir()
    result=adapter.write_selection_media(CommandPlan(action='write_selection_media',entities={'selection_id':'synthetic','mode':'folder','output_folder':str(target)}),{'confirmed':True})
    assert adapter.worker.called is (not existing)
    assert adapter.worker.light_viewer_path=='synthetic-saved-viewer'
    assert adapter.worker.options.center_name=='Synthetic center'
    assert adapter.operations[result.data['operation_id']]['state']==('failed' if existing else 'succeeded')
