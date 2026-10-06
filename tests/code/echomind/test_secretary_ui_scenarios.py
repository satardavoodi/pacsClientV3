"""Natural-request scenarios exercised through real bus, async service and isolated persistence.
Brain planning and native UI acceptance are independent gates, never inferred here.
"""
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import pytest

CASES=json.loads(Path('tests/scenarios/secretary_ui/execution_cases.json').read_text(encoding='utf-8'))

@pytest.fixture
def environment(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PacsClient.utils import data_paths,assistant_settings_repository
    from PacsClient.utils.assistant_settings_service import AssistantSettingsService
    from PacsClient.pacs.patient_tab.utils import tools_settings
    from database import _pool
    from modules.EchoMind import settings_store
    from modules.ai_imaging.eagle_eye_remote import administration
    from modules.EchoMind.secretary.command_bus import CommandBus
    from modules.EchoMind.secretary.registry import AdapterRegistry
    from modules.EchoMind.secretary.adapters.settings_command_adapter import SettingsCommandAdapter,SETTINGS_ACTIONS
    app=QApplication.instance() or QApplication([])
    _pool.cleanup_connection_pools()
    monkeypatch.setattr(data_paths,'DATABASE_FILE',tmp_path/'scenario.db')
    monkeypatch.setattr(tools_settings.ToolsSettingsManager,'_instance',None)
    monkeypatch.setattr(tools_settings,'_settings_cache',None)
    monkeypatch.setattr(settings_store,'_config_path',lambda:tmp_path/'echomind_settings.json')
    monkeypatch.setattr(administration,'load_settings',lambda:{'value':{'url':'https://localhost:8002'},'role':'client','revision':'synthetic','path':'synthetic'})
    settings_store.save_settings({'stt_provider':'auto','stt_auth_token':'synthetic-private-token'})
    def put(name,data):(tmp_path/name).write_text(json.dumps(data),encoding='utf-8')
    put('servers.json',[{'name':'Test Center','host':'127.0.0.1','port':'105','ae_title':'TEST'}])
    put('server_profiles.json',{'schema_version':1,'enabled':True,'profiles':[{'id':'test','display_name':'Test Center','host':'127.0.0.1','dicom_port':105,'socket_port':50123,'ae_title':'TEST','modules':{'reception_api':'http://localhost:7777'}}]})
    put('modality_grid.json',{'default':{'rows':1,'cols':2},'modality_layouts':{m:{'rows':1,'cols':2} for m in ['MR','CT','NM','XA']}})
    filters={m:{'enabled':True,'min_slices':4,'gaussian_smoothing':{'sigma':1.0},'gaussian_high_pass':{'sigma':1.0},'laplacian_sharpening':{'alpha':0.2}} for m in ['CT','MR']}
    put('filter_settings.json',filters)
    put('filter_presets.json',{'active':'Default','presets':{'Default':filters},'base':filters})
    threads=[]
    original=assistant_settings_repository.SettingsRepository
    def repository():
        threads.append(threading.get_ident())
        return original(tmp_path,echo=lambda host,port,aet:{'connected':port==105,'echo_success':port==105})
    monkeypatch.setattr(assistant_settings_repository,'SettingsRepository',repository)
    service=AssistantSettingsService(None,lambda:None)
    host=SimpleNamespace(assistant_settings_service=service)
    registry=AdapterRegistry();registry.register('settings',SettingsCommandAdapter(lambda:host),SETTINGS_ACTIONS)
    bus=CommandBus(registry=registry)
    def run(action,entities,confirmed=True):
        result=bus.execute({'action':action,'entities':entities},{'agent_mode':'assistant','confirmed':confirmed})
        assert result.ok,result.error_code
        key=result.data['operation_id'];deadline=time.monotonic()+5
        while service.operation_status(key)['state']=='running' and time.monotonic()<deadline:
            app.processEvents();time.sleep(.005)
        final=bus.execute({'action':'settings_operation_status','entities':{'operation_id':key}},{'agent_mode':'assistant'})
        assert final.ok and final.data['state']=='succeeded',final.data
        assert threads and all(t!=threading.get_ident() for t in threads)
        return final.data['data']
    try:yield SimpleNamespace(run=run,bus=bus,root=tmp_path,store=settings_store)
    finally:
        app.processEvents();service.deleteLater();app.processEvents();_pool.cleanup_connection_pools()

@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_natural_request_typed_execution_and_readback(environment,case):
    env=environment
    from modules.ai_imaging.eagle_eye_remote.secretary.validation.settings_controls import SETTINGS_CONTROL_WRITES
    if case['action'] in SETTINGS_CONTROL_WRITES:
        blocked=env.bus.execute({'action':case['action'],'entities':case['entities']},{'agent_mode':'assistant','confirmed':False})
        assert not blocked.ok and blocked.error_code=='CONFIRM_REQUIRED'
    if case['id']=='voice_openai':
        env.store.save_settings({'openai_api_key':'synthetic-private-own-key','prompt_secretary_action':'Synthetic user-defined prompt'})
    result=env.run(case['action'],case['entities'])
    kind=case['expected'];ent=case['entities']
    def load(name):return json.loads((env.root/name).read_text(encoding='utf-8'))
    if kind=='port_receipts':
        assert [row['echo_success'] for row in result['results']]==[True,False]
        assert len(load('servers.json'))==1 and load('servers.json')[0]['port']=='105'
    elif kind=='independent_clone':
        assert result['saved'] and not result['active_server_changed']
        profiles=load('server_profiles.json')['profiles']
        assert profiles[0]['id']!=profiles[1]['id'] and profiles[1]['socket_port']==50123
        assert {k:v for k,v in profiles[1]['modules'].items() if v is not None}=={k:v for k,v in profiles[0]['modules'].items() if v is not None}
    elif kind=='persist_grid':
        snapshot=env.run('get_settings_snapshot',{'section':'modality_grid'})
        assert set(load('modality_grid.json')['modality_layouts'])=={'MR','CT'} and snapshot
    elif kind in ('tool_color','tool_width'):
        styles=env.run('get_settings_snapshot',{'section':'tools'})['styles']
        expected=[0,1,128/255] if kind=='tool_color' else 4
        actual=styles[ent['tool']]['color' if kind=='tool_color' else 'line_width']
        assert (list(actual) if kind=='tool_color' else actual)==expected
        assert result['saved'] and result['active_images_changed'] is False
    elif kind=='filter_persistence':
        def value(data):
            current=data[ent['modality']]
            for key in ent['parameter'].split('.'):current=current[key]
            return current
        assert value(load('filter_settings.json'))==ent['value']
        presets=load('filter_presets.json')
        assert value(presets['presets']['Default'])==ent['value']
        assert value(presets['base'])!=ent['value']
        env.run('get_settings_snapshot',{'section':'image_filter'})
    elif kind=='voice_persistence':
        assert env.run('get_ai_settings',{})['voice_to_text']['provider']==ent['provider']
        assert env.store.get_stt_settings()['auth_token']=='synthetic-private-token'
    elif kind=='proxy_persistence':
        assert env.store.get_proxy_settings()['connection_type']==ent['connection_type']
        env.run('get_ai_settings',{})
    elif kind=='safe_snapshot':assert 'synthetic-private-token' not in json.dumps(result)


def test_catalog_discovers_existing_custom_search_fields():
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('ui_builder',Path('tools/dev/build_secretary_ui_catalog.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    records=module.inventory(Path('PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py').resolve())
    names={record['name'] for record in records}
    assert {'self.patient_id_edit','self.patient_name_edit','self.date_selector','self.date_from_edit','self.date_to_edit'}<=names


@pytest.fixture
def search_form(monkeypatch):
    from PySide6.QtWidgets import QApplication,QWidget,QTabWidget
    from PySide6.QtCore import QObject,Signal
    from PacsClient.pacs.workstation_ui.home_ui import patient_search_widget as module
    from PacsClient.utils import login_form_styles
    class Theme(QObject):
        themeChanged=Signal(object)
        def current_theme(self):return {key:'#102030' for key in ['accent','border','card_bg','danger','danger_hover','panel_alt_bg','panel_bg','success','success_hover','text_muted','text_primary']}
    app=QApplication.instance() or QApplication([]);theme=Theme()
    monkeypatch.setattr(module,'get_theme_manager',lambda:theme)
    monkeypatch.setattr(module.PatientSearchWidget,'_load_configured_modalities',lambda _:['MR','CT'])
    home=QWidget();home.resize(500,850)
    home.patient_search_widget=module.PatientSearchWidget(home)
    tabs=QTabWidget();[tabs.addTab(QWidget(),name) for name in ['Local','Server','Import']]
    home.data_access_panel_widget=SimpleNamespace(tabs=tabs)
    home._search_task=None;home.search_sources=[];home.advanced_queries=[]
    home.patient_list_function_identifier=lambda source:home.search_sources.append(source)
    home._on_advanced_search_requested=lambda query:home.advanced_queries.append(query)
    home.show();app.processEvents()
    try:yield home
    finally:home.close();tabs.close();app.processEvents()

@pytest.mark.parametrize('id,entities',[
    ('patient_id',{'source':'server','patient_id':'SYN-001'}),
    ('patient_name',{'source':'local','patient_name':'Synthetic Example'}),
    ('exact_date_mr',{'source':'server','modality':'MR','date_from':'20261002','date_to':'20261002'}),
    ('ct_date_range',{'source':'server','modality':'CT','date_from':'20261001','date_to':'20261003'}),
    ('advanced_age_body',{'source':'server','modality':'MR','body_part':'KNEE','age_min':12,'age_max':18}),
    ('advanced_multiple_ids',{'source':'server','patient_ids':['SYN-001','SYN-002'],'modality':'MR'})])
def test_home_scenarios_populate_actual_form_or_advanced_query(search_form,id,entities):
    from modules.EchoMind.secretary.adapters.home_widget_adapter import HomeWidgetAdapter
    from modules.EchoMind.secretary.adapters.home_command_adapter import HomeCommandAdapter
    from modules.EchoMind.secretary.command_bus import CommandBus
    from modules.EchoMind.secretary.registry import AdapterRegistry
    legacy=HomeWidgetAdapter(search_form)
    registry=AdapterRegistry();registry.register('home',HomeCommandAdapter(legacy),{'advanced_search_patients':'advanced_search_patients'})
    result=CommandBus(registry=registry).execute({'action':'advanced_search_patients','entities':entities},{'agent_mode':'assistant'})
    assert result.ok,result.error_code
    assert search_form.data_access_panel_widget.tabs.currentIndex()==(1 if entities['source']=='server' else 0)
    if id.startswith('advanced'):
        query=search_form.advanced_queries[-1]
        for key,value in entities.items():
            if key=='source':continue
            assert query['modalities' if key=='modality' else key]==([value] if key=='modality' else value)
    else:
        data=search_form.patient_search_widget.get_search_data()
        for key,value in entities.items():
            if key not in ('source','modality'):assert data[key]==value
        wanted=set(entities.get('modality','').split(','))-{''}
        assert {name for name,box in search_form.patient_search_widget.modality_checks.items() if box.isChecked()}==wanted
        assert search_form.search_sources==[entities['source']]


def test_custom_field_inspection_preserves_source_name_and_redacts_value(search_form):
    from PacsClient.utils.secretary_ui_observation import collect
    search_form.patient_search_widget.patient_id_edit.setText('synthetic-private-patient')
    controls=collect(search_form)[0]['controls']
    assert any(c['name']=='patient_id_edit' for c in controls)
    assert 'synthetic-private-patient' not in str(controls)

@pytest.mark.parametrize('field',['patient_sex','study_description','series_description'])
def test_discovered_search_field_gaps_fail_closed_before_changing_ui(search_form,field):
    from modules.EchoMind.secretary.command_bus import CommandBus
    from modules.EchoMind.secretary.registry import AdapterRegistry
    from modules.EchoMind.secretary.adapters.home_widget_adapter import HomeWidgetAdapter
    from modules.EchoMind.secretary.adapters.home_command_adapter import HomeCommandAdapter
    registry=AdapterRegistry();registry.register('home',HomeCommandAdapter(HomeWidgetAdapter(search_form)),{'advanced_search_patients':'advanced_search_patients'})
    result=CommandBus(registry=registry).execute({'action':'advanced_search_patients','entities':{field:'Synthetic'}},{'agent_mode':'assistant'})
    assert not result.ok and result.error_code=='INVALID_ARGUMENTS'
    assert not search_form.search_sources and not search_form.advanced_queries


@pytest.mark.parametrize('tool,expected',[
    ('ruler','RULER'),('angle','ANGLE'),('two_line_angle','TWO_LINE_ANGLE'),
    ('roi_rect','ROI_RECT'),('roi_circle','ROI_CIRCLE'),('arrow','ARROW'),
    ('text','TEXT'),('eraser','ERASER'),('select',None)])
def test_viewer_toolbar_request_changes_real_tool_controller(tool,expected):
    from PySide6.QtWidgets import QApplication,QWidget
    from modules.viewer.tools.controller import ToolController
    from modules.viewer.tools.store import ToolStore
    from modules.viewer.tools.enums import ToolType
    from modules.EchoMind.secretary.adapters.viewer_write_adapter import ViewerWriteCommandAdapter
    from modules.EchoMind.secretary.command_bus import CommandBus
    from modules.EchoMind.secretary.registry import AdapterRegistry
    app=QApplication.instance() or QApplication([])
    canvas=QWidget();canvas.tool_controller=ToolController(ToolStore(),None)
    tab=SimpleNamespace(lst_nodes_viewer=[SimpleNamespace(vtk_widget=SimpleNamespace(_qt_viewer_widget=canvas))])
    registry=AdapterRegistry();registry.register('viewer_write',ViewerWriteCommandAdapter(lambda:tab),{'activate_tool':'activate_tool'})
    try:
        result=CommandBus(registry=registry).execute({'action':'activate_tool','entities':{'tool':tool,'viewport':0}},{'agent_mode':'assistant','confirmed':True})
        assert result.ok,result.error_code
        assert canvas.tool_controller.active_tool==(getattr(ToolType,expected) if expected else None)
    finally:canvas.close()


def test_advanced_backend_does_not_claim_fast_toolbar_support():
    from modules.EchoMind.secretary.adapters.viewer_write_adapter import ViewerWriteCommandAdapter
    from modules.EchoMind.secretary.command_envelope import CommandPlan
    tab=SimpleNamespace(lst_nodes_viewer=[SimpleNamespace(vtk_widget=SimpleNamespace())])
    result=ViewerWriteCommandAdapter(lambda:tab).activate_tool(CommandPlan(action='activate_tool',entities={'tool':'arrow','viewport':0}),{})
    assert not result.ok and result.error_code=='NOT_IMPLEMENTED'
