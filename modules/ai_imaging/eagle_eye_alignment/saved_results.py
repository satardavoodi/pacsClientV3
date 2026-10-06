"""Worker-only exact-study discovery of retained Alignment reports."""
import hashlib
import json
from pathlib import Path


def load_result(root, study_uid, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root) or path.name != 'report.json':
        raise ValueError('Invalid saved Alignment report location.')
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Saved Alignment report exceeds the limit.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('identity', {}).get('study_uid') != study_uid:
        raise ValueError('Saved Alignment report belongs to another study.')
    if value.get('format_version') != 4 or not isinstance(value.get('measurements'), dict):
        raise ValueError('Invalid saved Alignment report.')
    pdf = (path.parent / 'report.pdf').resolve()
    if not pdf.is_relative_to(root) or pdf.parent != path.parent or pdf.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('Invalid saved Alignment PDF location or size.')
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != value.get('pdf_sha256'):
        raise ValueError('Saved Alignment PDF changed.')
    return dict(measurements=value['measurements'], notes=value.get('notes', {}),
                server_module='alignment', saved_files=[str(pdf)])


def discover_results(root, study_uid):
    root = Path(root).resolve()
    if not study_uid:
        return []
    key = hashlib.sha256(study_uid.encode()).hexdigest()
    candidates = list((root / 'alignment' / 'studies' / key).glob('*/report.json'))
    # Authenticated remote downloads retain the same report companion format.
    candidates.extend(root.glob('remote-*/report.json'))
    rows = []
    for path in candidates:
        try:
            load_result(root, study_uid, path)
            rows.append(dict(kind='alignment', path=str(path), modified=path.stat().st_mtime))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return sorted(rows, key=lambda row: row['modified'], reverse=True)
