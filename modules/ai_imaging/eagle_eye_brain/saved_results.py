"""Worker-only discovery of owned, exact-study brain results and review sessions."""
import hashlib
import json
from pathlib import Path


def _read(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Saved result exceeds the review limit.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Invalid saved result.')
    return value


def _same_study(result, study_uid):
    context = result.get('patient_context') or {}
    uids = {str(value) for value in (result.get('analysis_study_uid'), context.get('study_uid')) if value}
    return bool(study_uid) and uids == {str(study_uid)}


def _sessions(root, study_uid):
    for path in (root / 'manual-reviews').glob('*/session.json'):
        try:
            if not path.resolve().is_relative_to(root):
                continue
            record = _read(path)
            if _same_study(record.get('source_result', {}), study_uid):
                yield path.parent, record
        except (OSError, ValueError, TypeError, AttributeError):
            continue


def load_result(root, study_uid, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root) or path.name != 'result.json':
        raise ValueError('Choose a saved result owned by this workstation.')
    result = _read(path)
    if not _same_study(result, study_uid):
        raise ValueError('This result belongs to a different examination.')
    if Path(result.get('artifact_directory', '')).resolve() != path.parent:
        raise ValueError('Saved artifact location does not match its result.')
    if result.get('analysis_type') != 'brain_lesions' and not any(
            key in result for key in ('posterior_rows', 'manual_rows', 'normative')) and result.get('analysis_type') != 'brain':
        raise ValueError('This is not a brain result.')
    result['pdf_available'] = bool(result.get('pdf_available') and (path.parent / 'report.pdf').is_file())
    matches = [(directory, record) for directory, record in _sessions(root, study_uid)
               if Path(record['source_result'].get('artifact_directory', '')).resolve() == path.parent]
    if matches:
        directory, _ = max(matches, key=lambda item: (item[0] / 'session.json').stat().st_mtime_ns)
        result['_saved_manual_session'] = str(directory)
        result['_saved_correction_available'] = (directory / 'corrected.nii.gz').is_file()
    return result


def discover_results(root, study_uid):
    root = Path(root).resolve()
    if not study_uid:
        return []
    study_key = hashlib.sha256(str(study_uid).encode()).hexdigest()
    candidates = set()
    for directory in (root / 'brain' / 'patients').glob('*/studies/' + study_key):
        candidates.update(directory.rglob('result.json'))
    for directory, _ in _sessions(root, study_uid):
        candidates.update(directory.rglob('result.json'))
    rows = []
    for path in candidates:
        try:
            result = load_result(root, study_uid, path)
            kind = 'lesion' if result.get('analysis_type') == 'brain_lesions' else 'brain'
            rows.append(dict(path=str(path), kind=kind, modified=path.stat().st_mtime,
                             revision=bool(result.get('manual_correction')),
                             pdf_available=result['pdf_available']))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return sorted(rows, key=lambda row: (row['modified'], row['path']), reverse=True)
