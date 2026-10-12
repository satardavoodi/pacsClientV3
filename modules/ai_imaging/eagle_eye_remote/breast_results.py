"""Portable per-run calcium persistence; call disk helpers from workers only."""
import json
from pathlib import Path
from ..eagle_eye_engines.breast_dual import validate_calcium

LIMIT = 32 * 1024 * 1024


def save_calcium(result, study):
    if not result.get('csv'):
        raise ValueError('A detection run is required for calcium binding.')
    data = result.get('calcium') or dict(status='unavailable', reason='server_has_no_calcium_result')
    records = result.get('source_binding', [])
    if data.get('status') == 'success':
        if not records or any(r.get('study_uid') != study for r in records):
            raise ValueError('Calcium transfer lacks source binding.')
        validate_calcium(data, records, study)
    packet = dict(study_uid=study, detection_file=Path(result['csv']).name,
                  source_binding=records, calcium=data)
    text = json.dumps(packet, allow_nan=False)
    if len(text.encode('utf-8')) > LIMIT:
        raise ValueError('Calcium result exceeds the persistence limit.')
    target = Path(result['csv']).with_suffix('.calcium.json')
    temporary = target.with_suffix('.partial')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(target)


def load_calcium(detection, study):
    path = Path(detection).with_suffix('.calcium.json')
    if not path.is_file():
        return dict(status='unavailable', reason='no_calcium_for_this_run')
    with path.open('rb') as stream:
        raw = stream.read(LIMIT+1)
    if len(raw) > LIMIT:
        raise ValueError('Calcium result exceeds the persistence limit.')
    packet = json.loads(raw)
    if packet.get('study_uid') != study or packet.get('detection_file') != Path(detection).name:
        raise ValueError('Stale calcium result binding.')
    data = packet['calcium']
    if data.get('status') == 'success':
        records = packet['source_binding']
        if not records or any(r.get('study_uid') != study for r in records):
            raise ValueError('Invalid source binding.')
        validate_calcium(data, records, study)
    return data


def completion_message(result):
    lines = ['Breast detection results are available.']
    status = result.get('classification_status')
    if status == 'completed' or result.get('csv_classification'):
        lines.append('Lesion classification: completed.')
    elif status == 'no_detections':
        lines.append('Lesion classification: no detection candidates to classify.')
    else:
        lines.append('Lesion classification: unavailable; this is not a negative classification.')
    data = result.get('calcium') or {}
    if data.get('status') == 'success':
        lines.append('Microcalcification localization: completed; morphology is not classified.')
        if data.get('qualification') == 'research_only':
            lines.append('Microcalcification output is a research candidate and requires physician review.')
    else:
        lines.append('Microcalcification analysis: unavailable; absence has not been established.')
    return '\n'.join(lines)
