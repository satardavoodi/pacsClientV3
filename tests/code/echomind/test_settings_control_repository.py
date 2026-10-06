"""Synthetic settings receipts; never use live configuration or patient storage."""
import json
import pytest
from PacsClient.utils.assistant_settings_repository import SettingsRepository


def put(root, name, data):
    (root / name).write_text(json.dumps(data), encoding='utf-8')


def test_clone_preserves_transport_and_independent_identity(tmp_path):
    put(tmp_path, 'servers.json', [{'name':'Example','host':'127.0.0.1','port':'105','ae_title':'TEST'}])
    put(tmp_path, 'server_profiles.json', {'schema_version':1,'enabled':True,'profiles':[
        {'id':'example','display_name':'Example','host':'127.0.0.1','dicom_port':105,
         'socket_port':50123,'ae_title':'TEST','modules':{'reception_api':'http://localhost:7777'}}]})
    repo = SettingsRepository(tmp_path)
    result = repo.execute('clone_settings_server', {'source_name':'Example','new_name':'Example2'})
    assert result['saved'] and result['active_server_changed'] is False
    profiles = json.loads((tmp_path/'server_profiles.json').read_text())['profiles']
    assert profiles[0]['id'] != profiles[1]['id']
    assert profiles[1]['socket_port'] == 50123
    assert profiles[1]['modules']['reception_api'] == 'http://localhost:7777'
    with pytest.raises(ValueError):
        repo.execute('clone_settings_server', {'source_name':'Example','new_name':'Example2'})


def test_remove_grid_preserves_layout_and_rejects_empty(tmp_path):
    put(tmp_path, 'modality_grid.json', {'default':{'rows':1,'cols':2},'modality_layouts':{
        'MR':{'rows':1,'cols':2},'NM':{'rows':2,'cols':2},'XA':{'rows':1,'cols':1}}})
    repo = SettingsRepository(tmp_path)
    result = repo.execute('remove_settings_modalities', {'modalities':['NM','XA']})
    assert result['modalities'] == ['MR']
    with pytest.raises(ValueError):
        repo.execute('remove_settings_modalities', {'modalities':['MR']})
    assert json.loads((tmp_path/'modality_grid.json').read_text())['default']['cols'] == 2


def test_filter_updates_active_preset_and_runtime(tmp_path):
    filters = {'CT':{'min_slices':4},'MR':{'min_slices':4}}
    put(tmp_path, 'filter_settings.json', filters)
    put(tmp_path, 'filter_presets.json', {'active':'Default','presets':{'Default':filters},'base':filters})
    result = SettingsRepository(tmp_path).execute('set_settings_filter_parameter',
        {'modality':'CT','parameter':'min_slices','value':5})
    assert result['value'] == 5 and result['saved']
    assert json.loads((tmp_path/'filter_settings.json').read_text())['CT']['min_slices'] == 5
    presets = json.loads((tmp_path/'filter_presets.json').read_text())
    assert presets['presets']['Default']['CT']['min_slices'] == 5
    assert presets['base']['CT']['min_slices'] == 4


def test_verify_uses_exact_status_and_no_mutation(tmp_path):
    put(tmp_path, 'servers.json', [{'name':'Example','host':'127.0.0.1','port':'105','ae_title':'TEST','password':'hidden'}])
    before = (tmp_path/'servers.json').read_bytes()
    repo = SettingsRepository(tmp_path, echo=lambda host,port,aet: {'connected':port==105,'echo_success':port==105})
    result = repo.execute('verify_settings_server', {'server_name':'Example','ports':[105,104]})
    assert result['results'][0]['echo_success'] and not result['results'][1]['echo_success']
    assert 'password' not in json.dumps(repo.execute('get_settings_snapshot', {'section':'server'}))
    assert before == (tmp_path/'servers.json').read_bytes()


def test_tool_changes_use_isolated_database(tmp_path, monkeypatch):
    from PacsClient.utils import data_paths
    from database import _pool
    from PacsClient.pacs.patient_tab.utils import tools_settings
    _pool.cleanup_connection_pools()
    monkeypatch.setattr(data_paths, 'DATABASE_FILE', tmp_path/'test.db')
    monkeypatch.setattr(tools_settings.ToolsSettingsManager, '_instance', None)
    monkeypatch.setattr(tools_settings, '_settings_cache', None)
    try:
        repo = SettingsRepository(tmp_path)
        color = repo.execute('set_settings_tool_style', {'tool':'reference_line','color':'#00FF80'})
        assert color['style']['color'] == [0,1,128/255]
        arrow = repo.execute('set_settings_tool_style', {'tool':'arrow','line_width':4.0})
        assert arrow['style']['line_width'] == 4
    finally:
        _pool.cleanup_connection_pools()


@pytest.mark.parametrize('action,entities', [
    ('get_settings_snapshot', {'section':'server'}),
    ('verify_settings_server', {'server_name':'Example','ports':[105,104]}),
    ('clone_settings_server', {'source_name':'Example','new_name':'Example2'}),
    ('remove_settings_modalities', {'modalities':['NM','XA']}),
    ('set_settings_tool_style', {'tool':'arrow','line_width':4.0}),
    ('set_settings_filter_parameter', {'modality':'CT','parameter':'min_slices','value':5}),
])
def test_contract_bus_permissions_and_polling(action, entities):
    import importlib
    from types import SimpleNamespace
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    from modules.EchoMind.secretary.permissions import decide
    from modules.EchoMind.secretary.command_envelope import validate_action_entities
    from modules.EchoMind.secretary.workflow import _default_verify
    from modules.ai_imaging.eagle_eye_remote.secretary.validation.settings_controls import SETTINGS_CONTROL_WRITES
    assert action in build_command_bus(home_widget=SimpleNamespace()).actions()
    assert validate_action_entities(action, entities)
    for module in ('modules.EchoMind.secretary.validator','modules.ai_imaging.eagle_eye_remote.secretary.validation.validator'):
        plan, errors = importlib.import_module(module).validate_plan(dict(action=action,entities=entities,
            confidence=1.0,needs_confirmation=False,reason='Synthetic request'))
        assert not errors
        assert plan['needs_confirmation'] == (action in SETTINGS_CONTROL_WRITES)
    if action in SETTINGS_CONTROL_WRITES:
        assert not decide(action,mode='read_only',confirmed=True).allowed
    assert _default_verify(action, entities).probe_action == 'settings_operation_status'


def test_pair_write_rolls_back_on_second_replace_failure(tmp_path, monkeypatch):
    from PacsClient.utils import assistant_settings_repository as module
    put(tmp_path,'first.json',{'value':1})
    put(tmp_path,'second.json',{'value':2})
    original_replace = module.os.replace
    def fail_second(source, target):
        if str(target).endswith('second.json') and str(source).endswith('.tmp'):
            raise OSError('Synthetic replacement failure')
        return original_replace(source,target)
    monkeypatch.setattr(module.os,'replace',fail_second)
    with pytest.raises(OSError):
        SettingsRepository(tmp_path)._save({'first.json':{'value':3},'second.json':{'value':4}})
    assert json.loads((tmp_path/'first.json').read_text()) == {'value':1}
    assert json.loads((tmp_path/'second.json').read_text()) == {'value':2}


def test_manual_edit_after_read_is_not_overwritten(tmp_path):
    put(tmp_path,'first.json',{'value':1})
    repo = SettingsRepository(tmp_path)
    repo._read('first.json')
    put(tmp_path,'first.json',{'value':2})
    with pytest.raises(ValueError):
        repo._save({'first.json':{'value':3}})
    assert json.loads((tmp_path/'first.json').read_text()) == {'value':2}


@pytest.mark.parametrize('action,entities', [
    ('verify_settings_server', {'server_name':'Example','ports':[0]}),
    ('set_settings_tool_style', {'tool':'arrow','line_width':999.0}),
    ('set_settings_filter_parameter', {'modality':'MR','parameter':'min_slices','value':True}),
    ('set_settings_filter_parameter', {'modality':'MR','parameter':'arbitrary','value':1}),
    ('clone_settings_server', {'source_name':'Example','new_name':'../escape'}),
    ('remove_settings_modalities', {'modalities':['DEFAULT']}),
])
def test_unsafe_settings_entities_rejected_before_io(tmp_path, action, entities):
    with pytest.raises(ValueError):
        SettingsRepository(tmp_path).execute(action, entities)


def test_real_async_service_runs_io_off_gui_and_publishes_terminal_receipt(tmp_path, monkeypatch):
    import time, threading
    from PySide6.QtWidgets import QApplication
    from PacsClient.utils.assistant_settings_service import AssistantSettingsService
    from PacsClient.utils import assistant_settings_repository as module
    put(tmp_path,'modality_grid.json',{'modality_layouts':{'MR':{'rows':1,'cols':2},'NM':{'rows':1,'cols':1}}})
    repo = SettingsRepository(tmp_path)
    threads = []
    original_read = repo._read
    def read(name):
        threads.append(threading.get_ident())
        return original_read(name)
    monkeypatch.setattr(repo,'_read',read)
    monkeypatch.setattr(module,'SettingsRepository',lambda:repo)
    app = QApplication.instance() or QApplication([])
    service = AssistantSettingsService(None, lambda:None)
    refreshed = []
    service.modalitiesChanged.connect(refreshed.append)
    key = service.settings_control('remove_settings_modalities', {'modalities':['NM']})['operation_id']
    deadline = time.monotonic()+3
    while service.operation_status(key)['state'] == 'running' and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    result = service.operation_status(key)
    assert result['state'] == 'succeeded' and result['data']['saved']
    assert refreshed == [['MR']]
    assert threads and all(t != threading.get_ident() for t in threads)


@pytest.mark.parametrize('status,success', [(0,True),(0xA700,False),(None,False)])
def test_dicom_echo_requires_success_status(monkeypatch, status, success):
    from types import SimpleNamespace
    import pynetdicom
    from PacsClient.utils.assistant_settings_repository import dicom_echo
    releases = []
    association = SimpleNamespace(is_established=True,
        send_c_echo=lambda:SimpleNamespace(Status=status) if status is not None else None,
        release=lambda:releases.append(True))
    ae = SimpleNamespace(add_requested_context=lambda _:None,associate=lambda *args,**kwargs:association)
    monkeypatch.setattr(pynetdicom,'AE',lambda:ae)
    result = dicom_echo('127.0.0.1',105,'TEST')
    assert result['echo_success'] is success
    assert releases == [True]


def test_bus_does_not_start_settings_write_before_confirmation(monkeypatch):
    from types import SimpleNamespace
    from modules.EchoMind.secretary import registry
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    from modules.EchoMind.secretary.command_envelope import CommandPlan
    monkeypatch.setattr(registry,'_PERMISSIONS_ENABLED',True)
    calls = []
    def control(action, entities):
        calls.append((action,entities))
        return {'state':'running','operation_id':'synthetic-operation'}
    host = SimpleNamespace(assistant_settings_service=SimpleNamespace(settings_control=control))
    bus = build_command_bus(home_widget=SimpleNamespace(assistant_settings_host=host))
    plan = CommandPlan(action='set_settings_tool_style',entities={'tool':'arrow','line_width':5.0})
    result = bus.execute(plan,{'agent_mode':'assistant','confirmed':False})
    assert not result.ok and result.error_code == 'CONFIRM_REQUIRED' and not calls
    result = bus.execute(plan,{'agent_mode':'assistant','confirmed':True})
    assert result.ok and result.data['state'] == 'running' and len(calls) == 1
