"""Worker-only retained AI result reads; identity never inferred from patient names."""
import hashlib
import json
from pathlib import Path

MODULES = {'bone-age', 'alignment', 'total-spine', 'brain', 'brain-lesions', 'breast', 'lumbar'}


def read_json(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Saved result exceeds the limit.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Invalid saved result.')
    return value


def module_kind(value):
    module = value.get('server_module') or value.get('engine_module')
    if module in MODULES:
        return module
    if value.get('analysis_type') in ('brain', 'brain_lesions'):
        return 'brain-lesions' if value['analysis_type'] == 'brain_lesions' else 'brain'
    if value.get('status') == 'success' and 'predicted_bone_age_months' in value:
        return 'bone-age'
    if value.get('status') == 'success' and value.get('csv') and 'auxiliary_head_available' in value:
        return 'breast'
    return None


def load_result(root, study_uid, row):
    root = Path(root).resolve()
    path = Path(row['path']).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Saved result escaped its owned directory.')
    if row.get('storage') == 'alignment-report':
        from ..eagle_eye_alignment.saved_results import load_result as alignment
        return alignment(root, study_uid, path)
    value = read_json(path)
    if row.get('storage') == 'spine-report':
        if value.get('study_uid') != study_uid or value.get('format_version') != 1 or not value.get('views'):
            raise ValueError('Invalid saved spine identity.')
        pdf = (path.parent / 'report.pdf').resolve()
        if pdf.parent != path.parent or pdf.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('Invalid saved spine PDF.')
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != value.get('pdf_sha256'):
            raise ValueError('Saved spine PDF changed.')
        return dict(views=value['views'], notes=value.get('notes'), server_module='total-spine', saved_files=[str(pdf)])
    if path.name != 'result.json' or value.get('analysis_study_uid', value.get('study_uid', value.get('study_id'))) != study_uid:
        raise ValueError('Saved result belongs to another study.')
    module = module_kind(value)
    if module not in MODULES or module != row['kind']:
        raise ValueError('Invalid saved module identity.')
    if Path(value.get('artifact_directory') or value.get('job_directory') or '').resolve() != path.parent:
        raise ValueError('Saved artifact directory changed.')
    files = []
    for file in path.parent.rglob('*'):
        if file.suffix.lower() in {'.pdf', '.png', '.jpg', '.jpeg', '.csv'} and file.is_file():
            if not file.resolve().is_relative_to(path.parent):
                raise ValueError('Saved artifact escaped its directory.')
            files.append(str(file))
            if len(files) > 256:
                raise ValueError('Saved artifact inventory exceeds the limit.')
    return dict(value, server_module=module, saved_files=files)


def discover_results(root, study_uid):
    root = Path(root).resolve()
    if not study_uid:
        return []
    rows = []
    key = hashlib.sha256(study_uid.encode()).hexdigest()
    for path in (root / 'total-spine' / 'studies' / key).glob('*/report.json'):
        row = dict(kind='total-spine', storage='spine-report', path=str(path))
        try:
            load_result(root, study_uid, row)
            rows.append(row)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    for index, path in enumerate(root.glob('*/result.json')):
        if index >= 1000:
            break
        try:
            value = read_json(path)
            row = dict(kind=module_kind(value), storage='remote-result', path=str(path))
            load_result(root, study_uid, row)
            rows.append(row)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return rows


def echo_results(reference):
    from PacsClient.utils.data_paths import ECHOMIND_DIR
    from .text_history import History
    directory = Path(ECHOMIND_DIR) / 'remote_history'
    if not (directory / 'history.sqlite3').is_file():
        return []
    return [dict(row, kind='echomind', storage='echo-history') for row in
            History(directory).case_list(['local'], reference['study_uid'])[:50]]


def load_echo(reference, row):
    from PacsClient.utils.data_paths import ECHOMIND_DIR
    from .text_history import History
    return History(Path(ECHOMIND_DIR) / 'remote_history').case_result(
        ['local'], reference['study_uid'], row['request_id'])
