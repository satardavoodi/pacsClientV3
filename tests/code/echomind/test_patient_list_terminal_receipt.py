"""Aggregate-only terminal receipts, without live PACS or provider requests."""
from modules.EchoMind.secretary.workflow import WorkflowExecutor, WorkflowPlan, WorkflowStep, VerifySpec
from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator


def test_workflow_projects_actual_terminal_probe_count_without_patient_rows():
    calls = []
    def run(action, entities):
        calls.append(action)
        if action == 'advanced_search_patients':
            return {'ok': True, 'data': {'state': 'searching', 'count': 0, 'source':'server', 'search_id':'00000000-0000-4000-8000-000000000001'}}
        return {'ok': True, 'data': {'state': 'ready', 'count': 9, 'source': 'server',
                'search_id':'00000000-0000-4000-8000-000000000001', 'list_id': 'synthetic-executor-only', 'rows': ['SYNTHETIC_PRIVATE_ROW']}}
    plan = WorkflowPlan(goal='Bring the current list', steps=[WorkflowStep('advanced_search_patients',
        verify=VerifySpec('search_ready', 'read_patients', retries=1))])
    result = WorkflowExecutor(run).run(plan)
    projected = object.__new__(SecretaryOrchestrator)._workflow_result(result)
    receipt = projected['data']['steps'][0]['receipt']
    assert receipt == {'state': 'ready', 'count': 9, 'source': 'server'}
    assert 'SYNTHETIC_PRIVATE_ROW' not in str(projected)
    assert 'synthetic-executor-only' not in str(projected)
    assert calls == ['advanced_search_patients', 'read_patients']


def test_unverified_search_cannot_emit_a_terminal_count_receipt():
    def run(action, entities):
        return {'ok': True, 'data': {'state': 'searching', 'count': 999}}
    result = WorkflowExecutor(run).run(WorkflowPlan(goal='Synthetic', steps=[WorkflowStep('advanced_search_patients',
        verify=VerifySpec('search_ready', 'read_patients', retries=1))]))
    assert result.ok is False
    projected = object.__new__(SecretaryOrchestrator)._workflow_result(result)
    assert not projected['data']['steps'][0].get('receipt')


def test_later_unverified_search_cannot_reuse_prior_ready_count():
    from modules.EchoMind.secretary.patient_list_receipt import terminal_receipt
    result = {'ok': True, 'action': '__workflow__', 'data': {'steps': [
        {'tool': 'read_patients', 'ok': True, 'verified': True,
         'receipt': {'state': 'ready', 'count': 9, 'source': 'server'}},
        {'tool': 'advanced_search_patients', 'ok': True, 'verified': False}]}}
    assert terminal_receipt(result) == {}


def test_executed_dates_follow_only_same_verified_list_boundary():
    from modules.EchoMind.secretary.patient_list_receipt import terminal_provenance
    def run(action, entities):
        return {'ok': True, 'data': {'state': 'ready', 'count': 2, 'source': 'server', 'list_id': 'synthetic-list'}}
    plan = WorkflowPlan(goal='Synthetic', steps=[
        WorkflowStep('advanced_search_patients', args={'date_from':'20261010','date_to':'20261010'},
                     verify=VerifySpec('search_ready', 'read_patients', retries=1)),
        WorkflowStep('read_patients', verify=VerifySpec('search_ready', 'read_patients', retries=1))])
    result = object.__new__(SecretaryOrchestrator)._workflow_result(WorkflowExecutor(run).run(plan))
    assert terminal_provenance(result) == {'date_from':'20261010','date_to':'20261010'}
    assert 'synthetic-list' not in str(result)


def test_invalid_missing_or_new_list_dates_do_not_create_proof():
    from modules.EchoMind.secretary.patient_list_receipt import terminal_provenance
    for bounds in ({}, {'date_from':'20260230','date_to':'20261010'},
                   {'date_from':'20261011','date_to':'20261010'}):
        def run(action, entities):
            return {'ok': True, 'data': {'state':'ready','count':2,'source':'server','list_id':'synthetic-list'}}
        plan = WorkflowPlan(goal='Synthetic', steps=[WorkflowStep('advanced_search_patients', args=bounds,
            verify=VerifySpec('search_ready','read_patients',retries=1))])
        result=object.__new__(SecretaryOrchestrator)._workflow_result(WorkflowExecutor(run).run(plan))
        assert terminal_provenance(result) == {}
    calls = [0]
    def changed_list(action, entities):
        calls[0] += 1
        return {'ok': True, 'data': {'state':'ready','count':2,'source':'server',
                'list_id':'first' if calls[0] <= 2 else 'second'}}
    plan = WorkflowPlan(goal='Synthetic', steps=[
        WorkflowStep('advanced_search_patients',args={'date_from':'20261010','date_to':'20261010'},
                     verify=VerifySpec('search_ready','read_patients',retries=1)),
        WorkflowStep('read_patients',verify=VerifySpec('search_ready','read_patients',retries=1))])
    result=object.__new__(SecretaryOrchestrator)._workflow_result(WorkflowExecutor(changed_list).run(plan))
    assert terminal_provenance(result) == {}


def test_new_workflow_and_missing_or_unverified_list_boundary_never_reuse_dates():
    from modules.EchoMind.secretary.patient_list_receipt import terminal_provenance
    def run(action, entities):
        return {'ok': True, 'data': {'state':'ready','count':2,'source':'server','list_id':'synthetic-list'}}
    executor = WorkflowExecutor(run)
    plan = WorkflowPlan(goal='Synthetic', steps=[WorkflowStep('read_patients',
        verify=VerifySpec('search_ready','read_patients',retries=1))])
    result = executor.run(plan, {'_patient_date_boundary':('synthetic-list',
        {'date_from':'20261010','date_to':'20261010'})})
    assert terminal_provenance(object.__new__(SecretaryOrchestrator)._workflow_result(result)) == {}
    for state in ('ready','searching'):
        def no_boundary(action, entities):
            return {'ok': True, 'data': {'state':state,'count':2,'source':'server'}}
        plan=WorkflowPlan(goal='Synthetic',steps=[WorkflowStep('advanced_search_patients',
            args={'date_from':'20261009','date_to':'20261009'},
            verify=VerifySpec('search_ready','read_patients',retries=1))])
        result=object.__new__(SecretaryOrchestrator)._workflow_result(WorkflowExecutor(no_boundary).run(plan))
        assert terminal_provenance(result) == {}


import asyncio
from types import SimpleNamespace
import pytest

@pytest.mark.parametrize('action', ['advanced_search_patients','list_patients','search_patients','advanced_search'])
def test_direct_search_waits_without_replaying_initial_action(action):
    calls=[]
    handle='00000000-0000-4000-8000-000000000001'
    async def execute(plan,state,confirmed=False):
        calls.append(plan['action'])
        if plan['action'] != 'read_patients' or calls.count('read_patients') == 1:
            return {'ok':True,'action':plan['action'],'data':{'state':'searching','count':0,'source':'server','search_id':handle}}
        return {'ok':True,'action':'read_patients','data':{'state':'ready','count':3,
            'source':'server','list_id':'synthetic-list','search_id':handle,'rows':[]}}
    brain=object.__new__(SecretaryOrchestrator)
    brain.executor=SimpleNamespace(execute_async=execute,execute=lambda *a,**k:None)
    result=asyncio.run(brain._run_plan_async({'action':action,'entities':{'source':'server',
        'date_from':'20261011','date_to':'20261011'}},{},True))
    from modules.EchoMind.secretary.patient_list_receipt import terminal_receipt,terminal_provenance
    assert calls == [action,'read_patients','read_patients']
    assert terminal_receipt(result) == {'state':'ready','count':3,'source':'server'}
    assert terminal_provenance(result) == {'date_from':'20261011','date_to':'20261011'}

@pytest.mark.parametrize('action',['list_patients','search_patients','advanced_search'])
def test_legacy_patient_search_aliases_have_readiness_verification(action):
    from modules.EchoMind.secretary.workflow import build_plan
    spec=build_plan('Synthetic',[{'action':action,'entities':{}}]).steps[0].verify
    assert spec is not None and spec.kind=='search_ready' and spec.probe_action=='read_patients'


@pytest.mark.parametrize('initial,final',[
    ({'state':'searching','source':'server'},None),
    ({'state':'ready','source':'server'},None),
    ({'state':'ready','source':'server','list_id':'first'}, {'state':'ready','source':'server','list_id':'other','count':1}),
    ({'state':'ready','source':'server','list_id':'first'}, {'state':'ready','source':'local','list_id':'first','count':1}),
])
def test_search_verification_rejects_unbound_or_changed_lists(initial,final):
    from modules.EchoMind.secretary.workflow import drive_steps
    calls=[]
    def probe(action,args):
        calls.append((action,args))
        return {'ok':True,'data':final}
    executor=WorkflowExecutor(probe,sleep=lambda _:None)
    result=drive_steps(executor.verify_executed_patient_search_steps('list_patients',{}, {'ok':True,'data':initial}))
    assert result['ok'] is False and result['error_code']=='VERIFY_FAILED'
    assert len(calls)==(0 if final is None else 1)


def test_bound_pending_verification_deadline_and_async_responsiveness():
    from modules.EchoMind.secretary.workflow import drive_steps_async
    handle='00000000-0000-4000-8000-000000000001'
    calls=[]
    async def probe(action,args):
        calls.append((action,args))
        await asyncio.sleep(0)
        return {'ok':True,'data':{'state':'searching','source':'server','search_id':handle}}
    async def exercise():
        from unittest.mock import patch
        ticks=[]
        original=asyncio.sleep
        async def short_sleep(delay):
            ticks.append(True)
            await original(0)
        executor=WorkflowExecutor(probe)
        with patch('modules.EchoMind.secretary.workflow.asyncio.sleep',short_sleep):
            result=await drive_steps_async(executor.verify_executed_patient_search_steps('list_patients',{},
                {'ok':True,'data':{'state':'searching','source':'server','search_id':handle}}))
        assert result['ok'] is False and len(calls)==90 and ticks
        assert all(action=='read_patients' and args=={'source':'server','search_id':handle} for action,args in calls)
    asyncio.run(exercise())


def test_direct_ready_search_uses_only_bound_read_and_original_action_once():
    calls=[]
    def execute(plan,state,confirmed=False):
        calls.append((plan['action'],plan['entities']))
        return {'ok':True,'action':plan['action'],'data':{'state':'ready','source':'server',
            'count':0,'list_id':'synthetic-list','rows':[]}}
    brain=object.__new__(SecretaryOrchestrator)
    brain.executor=SimpleNamespace(execute=execute,execute_async=None)
    result=brain._run_plan({'action':'advanced_search_patients','entities':{'source':'server'}},{},True)
    assert result['ok'] is True
    assert [a for a,e in calls]==['advanced_search_patients','read_patients']
    assert calls[1][1]=={'source':'server','list_id':'synthetic-list'}


def test_failed_bound_probe_stops_without_retrying_search():
    from modules.EchoMind.secretary.workflow import drive_steps
    calls=[]
    def probe(action,args):
        calls.append(action)
        return {'ok':False,'error_code':'VERIFY_FAILED'}
    result=drive_steps(WorkflowExecutor(probe).verify_executed_patient_search_steps('list_patients',{},
        {'ok':True,'data':{'state':'ready','source':'server','list_id':'synthetic-list'}}))
    assert result['ok'] is False and calls==['read_patients']


def test_malformed_result_shape_diagnostic_remains_fixed_and_private():
    from modules.EchoMind.secretary.patient_list_receipt import result_diagnostic
    value=result_diagnostic({'action':'__workflow__','ok':True,'message':'PRIVATE_CONTENT',
        'data':{'steps':[{'tool':[],'receipt':{'rows':['PRIVATE_CONTENT']}}]}})
    assert value['terminal_receipt_present'] is False
    assert value['patient_step_action']=='unknown'
    assert 'PRIVATE_CONTENT' not in str(value)


def test_uncertain_executed_search_is_never_repaired_into_a_replay():
    from modules.EchoMind.secretary.execution_repair import is_repairable
    assert is_repairable({'ok':False,'action':'advanced_search_patients','error_code':'VERIFY_FAILED'}) is False
