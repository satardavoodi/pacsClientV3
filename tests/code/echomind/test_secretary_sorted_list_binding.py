"""Ordered list receipts bind an identity, not the row after later sorting."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from modules.EchoMind.secretary.adapters.home_command_adapter import HomeCommandAdapter
from modules.EchoMind.secretary.command_envelope import CommandPlan

ROWS=[{'patient_id':'synthetic-a','study_uid':'1.2.3.1','voice_presence':'absent'},
      {'patient_id':'synthetic-b','study_uid':'1.2.3.2','voice_presence':'present'}]

@pytest.fixture
def surface():
    rows=deepcopy(ROWS);opened=[];source=['server']
    table=SimpleNamespace(results_table=SimpleNamespace(rowCount=lambda:len(rows)),get_patient_data_by_row=lambda i:rows[i])
    home=SimpleNamespace(patient_table_widget=table,data_access_panel_widget=SimpleNamespace(get_result=lambda:source[0]))
    class Legacy:
        def is_available(self):return True
        def list_rows(self):return rows
        def get_active_source(self):return source[0]
        def open_patient(self,patient_id,patient_name,study_uid,report_status):
            opened.append({'patient_id':patient_id,'study_uid':study_uid})
    legacy=Legacy();legacy.home=home
    return HomeCommandAdapter(legacy),rows,opened,source

@pytest.mark.parametrize('change',['sort','sort_twice','append','remove_other'])
def test_original_target_survives_list_order_changes(surface,change):
    adapter,rows,opened,_=surface
    receipt=adapter.read_patients(CommandPlan(action='read_patients'),{}).data['list_id']
    if change=='sort':rows.reverse()
    if change=='sort_twice':
        rows.reverse();adapter.read_patients(CommandPlan(action='read_patients'),{});rows.reverse();rows.reverse()
    if change=='append':rows.insert(0,{'patient_id':'synthetic-c','study_uid':'1.2.3.3'})
    if change=='remove_other':rows.pop()
    result=adapter.open_patient(CommandPlan(action='open_patient',entities={'row_index':1,'list_id':receipt}),{})
    assert result.ok
    assert opened[0]['study_uid']==ROWS[0]['study_uid']

@pytest.mark.parametrize('change',['remove_target','duplicate_target','source','voice','unknown_receipt'])
def test_changed_or_unverifiable_target_never_opens(surface,change):
    adapter,rows,opened,source=surface
    receipt=adapter.read_patients(CommandPlan(action='read_patients'),{}).data['list_id']
    if change=='remove_target':rows.pop(0)
    if change=='duplicate_target':rows.append(deepcopy(rows[0]))
    if change=='source':source[0]='local'
    if change=='voice':rows[0]['voice_presence']='present'
    if change=='unknown_receipt':receipt='a'*64
    result=adapter.open_patient(CommandPlan(action='open_patient',entities={'row_index':1,'list_id':receipt,'required_voice_presence':'absent'}),{})
    assert not result.ok
    assert not opened



def test_real_confirmation_round_trip_preserves_original_identity_after_sort(surface):
    from modules.EchoMind.secretary.registry import AdapterRegistry
    from modules.EchoMind.secretary.command_bus import CommandBus
    from modules.EchoMind.secretary.executor import SecretaryExecutor
    from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator
    adapter,rows,opened,_=surface
    registry=AdapterRegistry();registry.register('home',adapter,{'read_patients':'read_patients','open_patient':'open_patient'})
    bus=CommandBus(registry)
    receipt=bus.execute({'action':'read_patients','entities':{}}).data['list_id']
    owner=object.__new__(SecretaryOrchestrator);owner.adapter=adapter._home
    owner.executor=SecretaryExecutor(adapter._home,command_bus_getter=lambda:bus)
    plan={'action':'open_patient','entities':{'row_index':1,'list_id':receipt},'needs_confirmation':True}
    state={}
    assert owner._run_plan(plan,state,False)['error_code']=='CONFIRM_REQUIRED'
    assert not opened
    rows.reverse()
    result=owner._run_plan(state['pending']['plan'],state,True)
    assert result['ok']
    assert opened[0]['study_uid']==ROWS[0]['study_uid']
    assert state['pending'] is None


def test_receipt_cache_is_bounded_and_evicted_changed_list_is_rejected(surface):
    adapter,rows,opened,_=surface
    first=adapter.read_patients(CommandPlan(action='read_patients'),{}).data['list_id']
    for i in range(20):
        rows.append({'patient_id':f'synthetic-{i}','study_uid':f'1.2.4.{i}'})
        adapter.read_patients(CommandPlan(action='read_patients'),{})
    assert len(adapter._ordinal_receipts)==16
    assert first not in adapter._ordinal_receipts
    result=adapter.open_patient(CommandPlan(action='open_patient',entities={'row_index':1,'list_id':first}),{})
    assert result.error_code=='STALE_LIST' and not opened
