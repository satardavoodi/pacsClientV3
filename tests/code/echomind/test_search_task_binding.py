"""Synthetic task identity guards; no PACS or clinical data."""
from types import SimpleNamespace
from uuid import uuid4
import pytest
from modules.EchoMind.secretary.adapters.home_command_adapter import HomeCommandAdapter
from modules.EchoMind.secretary.command_envelope import CommandPlan,validate_action_entities


def fixture():
    source=['server']
    tasks=[]
    home=SimpleNamespace(data_access_panel_widget=SimpleNamespace(get_result=lambda:source[0]),
        patient_table_widget=SimpleNamespace(results_table=SimpleNamespace(rowCount=lambda:0)))
    def start_search(**kwargs):
        task=SimpleNamespace(done=lambda:False,result=lambda:None)
        home._search_task=task
        tasks.append(task)
        return task
    legacy=SimpleNamespace(home=home,is_available=lambda:True,start_search=start_search,
        get_active_source=lambda:source[0],list_rows=lambda:[])
    return HomeCommandAdapter(legacy),home,source,tasks


def test_pending_search_handle_is_issued_once_and_probe_binds_task_and_source():
    adapter,home,source,tasks=fixture()
    initial=adapter.list_patients(CommandPlan(action='list_patients',entities={'source':'server'}),{})
    handle=initial.data['search_id']
    probe=CommandPlan(action='read_patients',entities={'source':'server','search_id':handle})
    assert adapter.read_patients(probe,{}).data['state']=='searching'
    tasks[0].done=lambda:True
    result=adapter.read_patients(probe,{})
    assert result.ok and result.data['state']=='ready' and result.data['search_id']==handle
    assert result.data['source']=='server' and result.data['list_id']
    assert len(tasks)==1
    source[0]='local'
    assert adapter.read_patients(probe,{}).ok is False


@pytest.mark.parametrize('kind',['forged','replaced','evicted'])
def test_stale_unknown_or_evicted_task_handles_fail_closed(kind):
    adapter,home,source,tasks=fixture()
    initial=adapter.list_patients(CommandPlan(action='list_patients',entities={'source':'server'}),{})
    handle=initial.data['search_id']
    if kind=='forged':handle=str(uuid4())
    elif kind=='replaced':home._search_task=SimpleNamespace(done=lambda:True)
    else:
        for _ in range(16):adapter.list_patients(CommandPlan(action='list_patients',entities={'source':'server'}),{})
        assert len(adapter._search_receipts)==16
    result=adapter.read_patients(CommandPlan(action='read_patients',entities={'source':'server','search_id':handle}),{})
    assert result.ok is False and result.error_code=='VERIFY_FAILED'


def test_unbound_legacy_read_remains_available_and_handle_schema_is_canonical():
    adapter,home,source,tasks=fixture()
    home._search_task=None
    assert adapter.read_patients(CommandPlan(action='read_patients',entities={}),{}).ok
    with pytest.raises(ValueError):validate_action_entities('read_patients',{'search_id':'forged'})
    valid=str(uuid4())
    assert validate_action_entities('read_patients',{'search_id':valid})['search_id']==valid
