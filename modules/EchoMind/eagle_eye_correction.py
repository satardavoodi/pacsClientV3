"""Worker-only import of existing, exact-study Eagle Eye report artifacts."""
import json
from pathlib import Path

from .reception_correction import _Text


def _report_text(row):
    html = row.get('content') or ''
    if html.strip():
        parser = _Text()
        parser.feed(html)
        return '\n'.join(s.strip() for s in ''.join(parser.parts).splitlines() if s.strip())
    if row.get('pdf'):
        from pypdf import PdfReader
        path = Path(row['pdf'])
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('Saved PDF exceeds the source limit.')
        reader = PdfReader(path)
        if reader.is_encrypted or len(reader.pages) > 30:
            raise ValueError('Saved PDF cannot be read.')
        pages = [page.extract_text() or '' for page in reader.pages]
        if any(not page.strip() for page in pages):
            raise ValueError('Saved PDF needs OCR before Correction.')
        return '\n'.join(pages)
    # JSON-only artifacts retain their structured findings without filesystem links.
    excluded = {'artifact_directory', 'job_directory', 'saved_files', 'preview',
                'report_html', 'review_assets', 'study_uid', 'study_id',
                'analysis_study_uid', 'patient_id', 'patient_name'}
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()
                    if key not in excluded and not key.endswith(('_path', '_directory'))}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value
    return json.dumps(clean(row['result']), ensure_ascii=False, allow_nan=False)


def load_from_roots(root, attachments, study_uid):
    if not study_uid:
        return []
    from modules.ai_imaging.eagle_eye_saved_results import discover_workspace, TITLES
    from modules.ai_imaging.eagle_eye_remote.local_results import discover_results, load_result
    rows = discover_workspace(root, attachments, study_uid)
    known = {Path(row['result']['artifact_directory']).resolve() for row in rows}
    # Include JSON-only results that do not have an HTML/PDF presentation artifact.
    for source in discover_results(root, study_uid):
        if Path(source['path']).resolve().parent in known:
            continue
        value = load_result(root, study_uid, source)
        rows.append({'module': source['kind'], 'result': value})
    items = []
    for row in rows:
        from .correction_source import pack
        if row.get('content'):
            raw = pack('eagle-eye-report.html', row['content'].encode('utf-8'))
        elif row.get('pdf'):
            with Path(row['pdf']).open('rb') as stream:
                raw = pack('eagle-eye-report.pdf', stream.read(1024 * 1024 + 1))
        else:
            raw = pack('eagle-eye-report.json', _report_text(row).encode('utf-8'))
        label = 'Eagle Eye — ' + TITLES.get(row['module'], row['module'])
        items.append((raw, label))
    return items


def load_for_study(study_uid):
    from PacsClient.utils.data_paths import AI_DIR, ATTACHMENTS_DIR
    return load_from_roots(Path(AI_DIR) / 'eagle_eye', ATTACHMENTS_DIR, study_uid)
