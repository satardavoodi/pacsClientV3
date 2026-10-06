"""Worker-only input check for complete, identity-bound DICOM media studies."""
from pathlib import Path


def study_files_ready(study, expected_count=0):
    from pydicom import dcmread
    path = study.get('study_path')
    uid = str(study.get('study_uid') or '').strip()
    if not path or not uid or not Path(path).is_dir():
        return False
    identities = set()
    for file in Path(path).rglob('*'):
        if file.name.upper() == 'DICOMDIR':
            continue
        if not file.is_file() or file.suffix.lower() not in ('', '.dcm', '.dicom'):
            continue
        try:
            ds = dcmread(file, stop_before_pixels=True,
                         specific_tags=['StudyInstanceUID', 'SOPInstanceUID', 'PatientID'])
            if str(ds.get('StudyInstanceUID', '')) != uid:
                return False
            patient = str(study.get('patient_id') or '').strip()
            if patient and str(ds.get('PatientID', '')).strip() != patient:
                return False
            sop = str(ds.get('SOPInstanceUID', ''))
            if not sop:
                return False
            identities.add(sop)
        except Exception:
            # Extensionless incidental files are not necessarily DICOM payloads.
            if file.suffix:
                return False
    return bool(identities) and len(identities) >= max(0, int(expected_count or 0))
