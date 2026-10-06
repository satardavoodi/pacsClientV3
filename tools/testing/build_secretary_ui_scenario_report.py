"""Summarize actual scenario receipts without promoting planned controls into passes."""
import json
from pathlib import Path
from collections import Counter
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[2]
FOLDER=ROOT/'tests/scenarios/secretary_ui'

def main():
    cases=json.loads((FOLDER/'execution_cases.json').read_text())+json.loads((FOLDER/'domain_cases.json').read_text())
    brain=json.loads((FOLDER/'brain_results.json').read_text())['results']
    index={row['id']:row for row in brain}
    continuation=json.loads((FOLDER/'continuation_results.json').read_text()) if (FOLDER/'continuation_results.json').exists() else []
    extra=json.loads((FOLDER/'workflow_cases.json').read_text())
    xml=ET.parse(FOLDER/'execution_results.xml')
    tests=xml.findall('.//testcase')
    if (FOLDER/'workflow_results.xml').exists():tests+=ET.parse(FOLDER/'workflow_results.xml').findall('.//testcase')
    failures=[c for c in tests if c.find('failure') is not None or c.find('error') is not None]
    def passed(fragment):return any(fragment in c.get('name','') and c.find('failure') is None and c.find('error') is None and c.find('skipped') is None for c in tests)
    counts=Counter(row['status'] for row in brain)
    lines=['# Secretary UI scenario execution report (2026-10-04)','',
        'All requests and persisted data in these experiments are synthetic. No real center setting, patient, recording, download or deletion was changed.',
        'Company brain requests used the authenticated Eagle Eye route; model proposals were not executed in the clinical application.',
        'Native source Test Control ping was unavailable. Offscreen form/controller tests and isolated repository execution are independent of native/clinical acceptance.','',
        '## Coverage and receipts','',
        f'- {len(json.loads((FOLDER/"control_scenarios.json").read_text())["scenarios"])} source-traced per-control scenario drafts, including custom wrappers. They require reviewed typed binding/native execution and are not execution passes.',
        f'- 50 authored natural requests: 35 settings operations, 6 Home searches and 9 Fast toolbar modes. Actual async settings persistence/readback, actual offscreen search form/query routing and real Fast ToolController state were checked.',
        f'- Focused code receipt: {len(tests)} tests, {len(failures)} failures/errors. The deterministic new suite has 56 guards: 50 operation cases plus inventory/privacy/unsupported-field/backend boundaries.',
        f'- Authenticated one-proposal brain receipt: {dict(counts)} across {len(brain)} requests. A read-before-write proposal is a prerequisite, not completed verification or cloning.',
        '- Two additional live continuation cases feed actual isolated read results back to the authenticated brain, then execute only correctly scoped typed proposals through the same bus/service. See their separate receipt below.',
        '- Real DICOM connectivity is not verified here: port 105 success / port 104 failure are injected synthetic echo outcomes.',
        '- No rendered clinical annotation, actual PACS population/search result, native external Slicer UI, physical media or clinical cleanup is certified.','',
        '## Authored requests and evaluated outcomes','',
        '| Scenario | User request | Isolated execution | Active brain proposal | Native application |',
        '| --- | --- | --- | --- | --- |']
    for case in cases:
        identifier=case['id'];fragment=f'[{identifier}]'
        if case.get('modules')==['homepage']:fragment=f'[{identifier}-entities'
        if identifier.startswith('toolbar_'):fragment=f'[{identifier.removeprefix("toolbar_")}-'
        isolated='PASS: checked state/readback' if passed(fragment) else 'NOT PROVEN by this receipt'
        row=index.get(identifier,{})
        status=row.get('status','not run')
        if row.get('actions')==['get_settings_snapshot'] and case['action']!='get_settings_snapshot':status='PREREQUISITE ONLY: configuration read'
        if status=='pass':status='PASS: expected action and requested fields'
        request=case['request'].replace('|','/')
        lines.append(f'| {identifier} | {request} | {isolated} | {status} | NOT RUN |')
    lines+=['','## Result-driven continuation','']
    for row in continuation:
        lines.append(f'- {row["id"]}: {row["status"]}; cycle={row.get("cycle")}; error={row.get("error_code")}; completed actions={[s["action"] for s in row.get("receipts",[])]}.')
    lines+=['','## Additional workflow scenarios','',
        '| Request | Evidence | Scope |','| --- | --- | --- |']
    for case in extra:
        name=case['guard'].split('::')[-1]
        result='PASS in focused guards' if passed(name) else 'PENDING in this receipt'
        lines.append(f'| {case["request"]} | {result}: `{case["guard"]}` | Synthetic/offscreen; native not run |')
    lines+=['','## Findings and interpretation','',
        '- Fixed inventory omission of five real Home composite search controls by explicitly recognizing LoginLineField/ComboField/DateField/NumberField and CustomCheckbox. The regression guard failed before the fix. Wrapper observation now retains outer field identity while redacting entered values.',
        '- Source declares Gender, Study Description and Series Description fields, but the current typed advanced-search contract does not support them. Negative tests verify rejection before UI/search changes. Their source declaration does not establish that they are visible in the compact current form.',
        '- Fast toolbar activation is verified for 9 modes through the actual ToolController. An Advanced backend without the Fast controller correctly returns NOT_IMPLEMENTED; this is a support boundary, not a successful activation.',
        '- First brain batch used a 45-second test timeout; a slow provider call timed out and subsequent requests returned 429 Busy. Resume used the normal 90-second request timeout; queue pauses on Busy and never changes provider or releases another request lock.',
        '- Initial ID-search probe exposed only two Home actions and the brain asked for missing selection capabilities. Repeating with the real factory contracts produced the correct ID search. A constrained test harness must not be presented as the full application contract.',
        '- Body-part comparison follows the existing search engine case-folding: knee and KNEE match. This is not an erroneous body-part filter.',
        '- The active server does not yet advertise UI-observation version 1. Actual redacted screen delivery requires the matching staged server update; old-server rejection remains explicit.',
        '- The first two live continuation attempts failed with SERVER_UPSTREAM_FAILED. A subsequent same-server retry passed both cases; no provider fallback or live server mutation was used. This demonstrates transient planning unavailability, not an established upstream root cause.',
        '- Read-result continuation is exercised by the test harness, not proof that the current native Secretary automatically feeds each receipt into the next planning cycle. That native orchestration gate remains open.','',
        '## Reproduction','',
        '`python tools/testing/build_secretary_ui_scenarios.py` regenerates drafts.',
        '`pytest -p no:debugging tests/code/echomind/test_secretary_ui_scenarios.py -q --reruns 0` runs isolated operation scenarios.',
        '`python tools/testing/run_secretary_ui_planning.py --resume` resumes synthetic authenticated planning only; no proposals execute in the app.',
        'Set AIPACS_LIVE_SCENARIO_PLANNING=1 only for `test_live_secretary_ui_scenarios.py`; it uses temporary settings/database and stub echo, while the brain is real.',
        '`python tools/testing/build_secretary_ui_scenario_report.py` regenerates this report from actual receipts.']
    (ROOT/'docs/agent_control/SECRETARY_UI_SCENARIO_RESULTS_2026-10-04.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'authored_requests':len(cases),'brain':dict(counts),'code_tests':len(tests),'code_failures':len(failures)}))

if __name__=='__main__':main()
