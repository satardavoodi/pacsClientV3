"""Opt-in authenticated brain -> real isolated CommandBus scenarios; never clinical mutation."""
import json,os,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from tests.code.echomind.test_secretary_ui_scenarios import environment

CASES=json.loads(Path('tests/scenarios/secretary_ui/execution_cases.json').read_text(encoding='utf-8'))[:2]
pytestmark=pytest.mark.skipif(os.environ.get('AIPACS_LIVE_SCENARIO_PLANNING')!='1',reason='Explicit authenticated synthetic planning session required')

@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_authenticated_read_result_continuation_and_isolated_execution(environment,case):
    from PySide6.QtWidgets import QApplication
    from modules.EchoMind.secretary.remote_planner import request
    env=environment;app=QApplication.instance();history=[];receipts=[];finished=False
    def record(status,cycle,error=None):
        target=Path('tests/scenarios/secretary_ui/continuation_results.json')
        existing=json.loads(target.read_text()) if target.exists() else []
        existing=[r for r in existing if r['id']!=case['id']]
        existing.append({'id':case['id'],'status':status,'cycle':cycle,'error_code':error,'receipts':list(receipts),
            'brain':'authenticated_eagle_eye','execution':'real_command_bus_async_service_isolated_persistence','network_echo':'synthetic_stub','native_app':'not_run'})
        target.write_text(json.dumps(existing,indent=2)+'\n',encoding='utf-8')
    for cycle in range(3):
        record('planning',cycle)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(request,'plan',case['request'],language='en',timeout=90,modules=['settings'],
                interaction_mode='act',runtime_capabilities=env.bus.capabilities(),memory_context=json.dumps(history))
            while not future.done():app.processEvents();time.sleep(.01)
            try:response=future.result()
            except Exception as error:
                record('blocked_planning',cycle,getattr(error,'error_code',type(error).__name__))
                raise
        plan=response.get('plan') or {}
        steps=plan.get('steps',[]) if plan.get('action')=='__workflow__' else [plan]
        assert steps and len(steps)<=5
        for step in steps:
            action=step.get('action');entities=step.get('entities',{})
            assert action in ('get_settings_snapshot',case['action']), 'Brain proposed an unrelated action; no execution'
            if action==case['action']:
                assert all(entities.get(key)==value for key,value in case['entities'].items()),'Proposal does not match requested scope'
            result=env.run(action,entities)
            history.append({'action':action,'ok':True,'data':result})
            receipts.append({'action':action,'completion':'succeeded'})
            record('continuing',cycle)
            if action==case['action']:
                if action=='verify_settings_server':assert [row['echo_success'] for row in result['results']]==[True,False]
                else:
                    assert result['saved'] and not result['active_server_changed']
                    profiles=json.loads((env.root/'server_profiles.json').read_text())['profiles']
                    assert profiles[0]['id']!=profiles[1]['id'] and profiles[1]['socket_port']==50123
                finished=True;break
        if finished:break
    assert finished,'Requested operation did not complete after actual prerequisite results'
    record('pass',cycle)
