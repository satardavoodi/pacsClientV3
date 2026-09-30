"""Synthetic text-only acceptance; never saves reports, provider keys or prompts."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def run(connection, *, quick=False):
    rows = []
    report = '{"Report Title":"Synthetic knee MRI","Pathological Findings":["Small effusion."]}'
    question = 'Synthetic educational question without a patient: describe imaging features of a simple renal cyst with reference sources.'
    requests = [
        ('report', {'modality': 'MRI', 'text': 'Synthetic test: knee MRI. Small joint effusion.'}),
        ('turbo', {'modality': 'MRI', 'text': 'Synthetic test: knee MRI. Small joint effusion.', 'study_profile': {'regions': ['knee']}}),
        ('standardize_assist', {'text': question}),
        ('web_search', {'text': question}),
    ]
    if not quick:
        requests.extend([
            ('correction', {'text': report, 'correction_note': 'Change small effusion to moderate effusion.'}),
            ('correction', {'text': report, 'correction_note': 'Change small effusion to moderate effusion.',
                            'turbo_correction': True, 'modality': 'MRI', 'study_profile': {'regions': ['knee']}}),
            ('standardize', {'text': 'Synthetic test: small knee effusion.'}),
            ('translate_report', {'text': report}),
            ('translate_text', {'text': 'Synthetic educational statement: small joint effusion.'}),
            ('chat', {'text': question}), ('breast', {'text': 'Synthetic educational question: describe BI-RADS categories.'}),
            ('assistant', {'text': question, 'provider': 'aipacs'}),
            ('search', {'text': question, 'provider': 'aipacs'}),
            ('organize_template', {'text': json.dumps({'name': 'Synthetic knee', 'modality': 'MRI',
                'blocks': [{'id': 'L0000', 'text': 'The menisci are intact.'}]})}),
            ('template_languages', {'text': 'The menisci are intact.'}),
        ])
    for workflow, fields in requests:
        started = time.monotonic()
        row = {'workflow': workflow, 'turbo_correction': bool(fields.get('turbo_correction'))}
        body = {'workflow': workflow, 'provider': 'company', 'response_format': 'json', **fields}
        try:
            with connection.open('/v1/echomind/process', body, timeout=360) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError('Response limit')
            value = json.loads(raw)
            content = value.get('content')
            row['passed'] = bool(content) and value.get('workflow') == workflow
            if workflow in ('report', 'turbo', 'correction'):
                from modules.ai_imaging.eagle_eye_remote.echomind.core.viewer_chat.openai_reporter import _clean_model_json_text
                parsed = json.loads(_clean_model_json_text(content)) if isinstance(content, str) else content
                row['structured_report'] = isinstance(parsed, dict)
                row['passed'] = row['passed'] and row['structured_report']
            if workflow == 'web_search':
                from modules.EchoMind.remote_backend import render_web_search
                row['citations'] = len(content.get('Sources', []))
                row['passed'] = row['passed'] and bool(render_web_search(content))
            if workflow == 'organize_template':
                row['passed'] = row['passed'] and isinstance(content, dict) and bool(content.get('groups'))
            if workflow == 'template_languages':
                row['passed'] = row['passed'] and content.get('en') == fields['text'] and bool(content.get('fa'))
        except Exception as exc:
            row.update(passed=False, error_type=type(exc).__name__)
            if getattr(exc, 'status', None):
                row['http_status'] = exc.status
        row['seconds'] = round(time.monotonic() - started, 2)
        rows.append(row)
        print(json.dumps(row), flush=True)
    return {'scope': 'synthetic-only', 'passed': all(r['passed'] for r in rows), 'results': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--quick', action='store_true')
    args = parser.parse_args()
    from modules.ai_imaging.eagle_eye_remote.client import Client
    connection = Client(json.loads(args.config.read_text(encoding='utf-8-sig')))
    result = run(connection, quick=args.quick)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
