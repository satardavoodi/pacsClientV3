"""Read-only study selection, patient-scoped artifacts and local PDF export.

Call filesystem and repository operations only from a background worker.
"""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

from .contracts import BrainError


def patient_output_root(root, context):
    study = str(context.get('study_uid') or '')
    if not study:
        raise BrainError('A verified DICOM study is required for patient-scoped storage.')
    patient = '\0'.join(str(context.get(k) or '') for k in ('patient_id', 'institution', 'birth_date'))
    if not context.get('patient_id'):
        patient = study
    key = lambda value: hashlib.sha256(value.encode('utf-8')).hexdigest()
    return Path(root) / 'brain' / 'patients' / key(patient) / 'studies' / key(study)


def load_study_series(study_uid):
    from PacsClient.utils.db_manager import get_series_by_study_uid
    if not study_uid:
        raise BrainError('Open a brain MRI study before selecting its series.')
    rows = []
    for item in get_series_by_study_uid(study_uid):
        if str(item.get('modality') or '').upper() != 'MR':
            continue
        path = str(item.get('series_path') or '')
        description = str(item.get('series_description') or '')
        protocol = str(item.get('protocol_name') or '')
        blob = (description + ' ' + protocol).lower()
        preferred = any(word in blob for word in ('mprage', 'mp rage', 't1')) and not any(
            word in blob for word in ('flair', 't2', 'localizer', 'scout', 't1map', 't1 map'))
        rows.append(dict(series_uid=str(item.get('series_uid') or ''),
                         number=str(item.get('series_number') or ''), description=description,
                         image_count=item.get('image_count') or 0, path=path,
                         available=bool(path and Path(path).is_dir()), preferred=preferred))
    return sorted(rows, key=lambda row: (not row['preferred'], row['number']))


def run_study_analysis(source, study_uid, series_uid, *, root, flair_source='', flair_series_uid=None, **kwargs):
    from .patient_context import dicom_context, require_same_examination
    from .service import run_analysis
    context = dicom_context(source)
    if context.get('study_uid') != study_uid or context.get('series_uid') != series_uid:
        raise BrainError('The selected DICOM series no longer matches this examination. Select it again.')
    if flair_source:
        flair_context = dicom_context(flair_source)
        if (flair_context.get('study_uid') != study_uid
                or flair_context.get('series_uid') != flair_series_uid
                or flair_series_uid == series_uid):
            raise BrainError('Choose a distinct FLAIR series from this examination.')
        require_same_examination(context, flair_context)
    return run_analysis(source, flair_source, patient_output_root(root, context), **kwargs)


def export_pdf(result, destination):
    """Publish a complete copy; never leave a partly written destination PDF."""
    source = Path(result['artifact_directory']) / 'report.pdf'
    destination = Path(destination)
    if not result.get('pdf_available') or not source.is_file():
        raise BrainError('The completed PDF report is not available.')
    if source.resolve() == destination.resolve():
        return str(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.brain-report-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            with source.open('rb') as original:
                if original.read(5) != b'%PDF-':
                    raise BrainError('The report is not a valid PDF file.')
                original.seek(0)
                shutil.copyfileobj(original, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(destination)


def regenerate_patient_report(result_path, root, *, study_uid=None, **kwargs):
    import json
    from .report_service import regenerate_report
    from .patient_context import dicom_context
    try:
        result = json.loads(Path(result_path).read_text(encoding='utf-8'))
        context = result.get('patient_context', {})
    except (OSError, ValueError, AttributeError):
        raise BrainError('Choose a completed brain analysis result.') from None
    if kwargs.get('dicom_source'):
        context = dicom_context(kwargs['dicom_source'])
    if study_uid and context.get('study_uid') != study_uid:
        raise BrainError('This completed analysis belongs to another examination.')
    destination = patient_output_root(root, context) / 'reports'
    return regenerate_report(result_path, destination, **kwargs)
