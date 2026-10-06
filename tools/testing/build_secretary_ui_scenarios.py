"""Trace one user scenario to every discovered control; unknown bindings never become executable."""
import json,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from PacsClient.utils.secretary_ui_source_catalog import SOURCE_CATALOG
from modules.EchoMind.secretary.adapters.ui_observation_adapter import area

def build():
    rows=[]
    for record in SOURCE_CATALOG['controls']:
        scope=area(record['source']);kind=record['kind']
        label=next((record.get(k) for k in ('label','setAccessibleName','setToolTip','setPlaceholderText','setText') if record.get(k)),record['name'])
        page=Path(record['source']).stem.replace('_',' ')
        location=f'{scope.replace("_"," ")} / {page}'
        identity=hashlib.sha256(f"{record['source']}:{record['line']}:{record['name']}".encode()).hexdigest()[:12]
        persona='Workstation administrator' if scope=='settings' else 'Radiologist'
        constraints=record.get('constraints',{});value=None
        if record['sensitive']:
            mode='guide';request=f'Show me how to enter {label} locally in {location}. Do not read or send its value.'
            verification='Local form handoff only; no credentials in plans, images, logs or remote requests.'
        elif kind=='QComboBox':
            if record['options']:
                value=record['options'][0];mode='act';request=f'In {location}, select {value} in the {label} dropdown for this test workflow.'
            else:
                mode='guide';request=f'In {location}, show the currently available choices for {label} and explain which workflow each choice controls.'
            verification='Inspect real current options and enabled state; match exact option through a registered typed action; verify readback and domain-specific apply/save outcome.'
        elif kind in ('QLineEdit','QSpinBox','QDoubleSpinBox','NumericField','QSlider','QDateEdit','QTimeEdit'):
            mode='guide';request=f'For my test workflow in {location}, explain what the {label} field controls, the valid input format, and how I apply and verify a change.'
            verification='Resolve field meaning and format first. Execute only a reviewed valid value through a typed contract; separately test invalid/boundary input and unchanged persistence after rejection.'
        elif kind in ('QCheckBox','QRadioButton'):
            mode='act';request=f'In {location}, enable {label} for this test workflow and tell me when the change takes effect.'
            verification='Verify checked state, correct local versus persistent scope, required confirmation, saved state and whether active images actually changed.'
        else:
            mode='act';request=f'For this test workflow in {location}, use {label}, then verify the operation has actually completed.'
            verification='Resolve actual callback behavior and supported backend; execute its typed action with required identity/confirmation; poll terminal status rather than equating a click with success.'
        rows.append({'id':'control_'+identity,'persona':persona,'mode':mode,'story':f'{persona} is preparing a synthetic test workflow in {location}.',
            'request':request,'source':record['source'],'line':record['line'],'control':record['name'],'kind':kind,'options':record['options'],'constraints':constraints,
            'candidate_value':value,'expected':verification,'native_status':'not_run_test_control_unavailable',
            'typed_binding':'manual_semantic_review_required','source_callback_reference':record['callbacks']})
    return rows

if __name__=='__main__':
    rows=build();folder=ROOT/'tests/scenarios/secretary_ui'
    (folder/'control_scenarios.json').write_text(json.dumps({'scope':'source_traced_scenario_drafts_not_execution_claims','scenarios':rows},indent=2)+'\n',encoding='utf-8')
    lines=['# Per-control Secretary scenarios','','Source-traced drafts: typed action binding and native execution remain explicit gates. No generated source callback is executable.','',
        '| ID / source | User request | Expected verification | Native result |','| --- | --- | --- | --- |']
    for row in rows:
        values=[f"{row['id']} / {row['source']}:{row['line']}",row['request'],row['expected'],'NOT RUN: source Test Control unavailable; reviewed typed binding required']
        lines.append('| '+' | '.join(v.replace('|','/').replace('\n',' ') for v in values)+' |')
    (ROOT/'docs/agent_control/SECRETARY_UI_PER_CONTROL_SCENARIOS_2026-10-04.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'control_scenarios':len(rows),'executed_native':0}))
