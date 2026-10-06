"""Authenticated synthetic Ask/Guide smoke; never executes proposals or sends clinical data."""
import json
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
def main():
    from modules.EchoMind.secretary.remote_planner import request
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    from modules.EchoMind.secretary.guide_knowledge import page_guides
    caps=build_command_bus(home_widget=SimpleNamespace()).capabilities()
    guides=page_guides()
    cases=[
        ('guide_current_ai','guide','Explain this AI page and its fields without changing anything.',dict(page_guides={'echomind':guides['echomind']},ui_controls={'navigation':[{'current_label':'EchoMind','current_index':0}],'controls':[]},tutorials={})),
        ('guide_modality_grid','guide','What is Modality Grid for, and how does it differ from the Home search modality checkboxes?',dict(page_guides={'viewer':guides['viewer']},tutorials={})),
        ('ask_settings','ask','Report current AI settings and tell me which Settings sections are unavailable.',dict(settings_report={'scope':'persisted_configuration_not_unsaved_forms_or_connectivity','complete':False,'sections':{'ai':{'state':'available','data':{'voice_to_text':{'provider':'v2t','timeout_seconds':30},'company_prompts_models':'authenticated_eagle_eye_server_owned'}}},'unavailable_sections':['installation','education','agent_policy','storage_usage']})),
        ('ask_voice_report','ask','How many of today\'s MRI studies have voice recordings, and how many have completed reports? Did I personally record them?',dict(scope='currently loaded studies, not all daily admissions',daily_population_complete=False,voice_author_metrics='unavailable',report_author_metrics='unavailable',workflow_groups=[{'date':'20261004','modality':'MR','displayed_rows':6,'voice_presence':{'present':2,'absent':3,'unknown':1},'report_statuses':{'completed':1,'pending':4,'unknown':1}}])),
    ]
    rows=[];output=ROOT/'tests/scenarios/secretary_ui/modes/expanded_brain_results.json'
    for identifier,mode,text,context in cases:
        row={'id':identifier,'mode':mode,'source':'authenticated_eagle_eye','execution':'none','synthetic':True}
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                reply=pool.submit(request,'plan',text,language='en',timeout=90,modules=['settings' if identifier!='ask_voice_report' else 'homepage'],interaction_mode=mode,question_context=context,runtime_capabilities=caps).result()
            row.update(contract_ok=isinstance(reply.get('answer'),str) and bool(reply['answer'].strip()) and reply.get('plan') is None,answer=reply.get('answer'),semantic_status='requires_review',capability_acknowledged=reply.get('capability_digest')==caps['digest'])
        except Exception as error:
            row.update(contract_ok=False,error_code=getattr(error,'error_code',type(error).__name__),semantic_status='not_evaluated')
        rows.append(row);output.write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(row),flush=True)
        if row.get('error_code')=='SERVER_HTTP_429':break
    return 0 if len(rows)==len(cases) and all(r['contract_ok'] for r in rows) else 1
if __name__=='__main__':raise SystemExit(main())
