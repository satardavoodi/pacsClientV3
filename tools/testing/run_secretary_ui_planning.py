"""Evaluate synthetic user requests against the authenticated company brain. Never execute proposals."""
import json
import sys
import time
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

def main():
    from modules.EchoMind.secretary.command_bus import CommandBus
    from modules.EchoMind.secretary.registry import AdapterRegistry
    from modules.EchoMind.secretary.adapters.settings_command_adapter import SettingsCommandAdapter,SETTINGS_ACTIONS
    from modules.EchoMind.secretary.remote_planner import request
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    source_bus=build_command_bus(home_widget=SimpleNamespace())
    registry=source_bus.registry
    from modules.EchoMind.secretary.adapters.home_command_adapter import HomeCommandAdapter
    from modules.EchoMind.secretary.adapters.viewer_write_adapter import ViewerWriteCommandAdapter
    # Preserve Home selection/opening/read contracts from the real factory.
    registry.register('viewer_write',ViewerWriteCommandAdapter(),{'activate_tool':'activate_tool'})
    bus=CommandBus(registry=registry)
    folder=ROOT/'tests/scenarios/secretary_ui'
    cases=json.loads((folder/'execution_cases.json').read_text(encoding='utf-8'))+json.loads((folder/'domain_cases.json').read_text(encoding='utf-8'))
    parser=argparse.ArgumentParser();parser.add_argument('--resume',action='store_true');parser.add_argument('--case',action='append');args=parser.parse_args()
    prior=json.loads((folder/'brain_results.json').read_text(encoding='utf-8')).get('results',[]) if args.resume and (folder/'brain_results.json').exists() else []
    results=list(prior)
    for case in cases:
        if args.case and case['id'] not in args.case:continue
        previous=next((r for r in results if r['id']==case['id']),None)
        if previous and previous['status']!='error' and not args.case:continue
        if previous:results.remove(previous)
        row={'id':case['id'],'expected_action':case['action'],'native_execution':'not_run'}
        started=time.monotonic()
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                response=pool.submit(request,'plan',case['request'],language='en',timeout=90,
                    modules=case.get('modules',['settings']),interaction_mode='act',runtime_capabilities=bus.capabilities()).result()
            plan=response.get('plan') or {}
            proposals=plan.get('steps',[]) if plan.get('action')=='__workflow__' else [plan]
            row['actions']=[p.get('action') for p in proposals]
            targets=[p for p in proposals if p.get('action') in case.get('acceptable_actions',[case['action']])]
            def equivalent(key,actual,expected):
                if key=='body_part' and isinstance(actual,str) and isinstance(expected,str):return actual.strip().casefold()==expected.strip().casefold()
                return actual==expected
            row['mismatched_fields']=[key for key,value in case['entities'].items()
                if not any(equivalent(key,p.get('entities',{}).get(key),value) for p in targets)]
            row['observed_entities']=[{k:p.get('entities',{}).get(k) for k in case['entities']} for p in targets]
            if args.case and plan.get('action')=='unknown':
                print(json.dumps({'diagnostic_case':case['id'],'reason':str(plan.get('reason',''))[:300]}),flush=True)
            row['status']='pass' if targets and not row['mismatched_fields'] else 'mismatch'
            row['runtime_receipt_acknowledged']=response.get('capability_digest')==bus.capabilities()['digest']
        except Exception as error:
            row.update(status='error',error_code=getattr(error,'error_code',type(error).__name__))
        row['elapsed_seconds']=round(time.monotonic()-started,2)
        if previous:row['previous_attempt']=previous
        results.append(row)
        (folder/'brain_results.json').write_text(json.dumps({'scope':'authenticated_server_planning_only_synthetic_no_execution','results':results},indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in row.items() if k!='previous_attempt'}),flush=True)
        if row.get('error_code')=='SERVER_HTTP_429':
            print('Server busy: queue paused; unattempted cases remain pending.',flush=True)
            break
        if row['status']=='error':time.sleep(15)
    return 0 if len(results)==len(cases) and all(r['status']=='pass' for r in results) else 1

if __name__=='__main__':raise SystemExit(main())
