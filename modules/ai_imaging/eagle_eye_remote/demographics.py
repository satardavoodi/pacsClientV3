"""Shared study-bound demographics; never infer sex or modify source DICOM."""
from urllib.parse import quote


def normalize(value):
    return {'m': 'M', 'male': 'M', 'f': 'F', 'female': 'F'}.get(str(value or '').strip().lower())


def reception_sex(payload, patient_id):
    if not isinstance(payload, dict) or not patient_id:
        return None
    rows = payload.get('data')
    rows = rows if isinstance(rows, list) else [rows]
    matches = [r for r in rows if isinstance(r, dict) and
               str(r.get('receptionId', '')) == str(patient_id)]
    if len(matches) != 1 or not isinstance(matches[0].get('patient'), dict):
        return None
    return normalize(matches[0]['patient'].get('Gender'))


def lookup_payload(patient_id):
    """Call only from an analysis worker; bounded configured Reception endpoint."""
    import requests
    from modules.network.reception_api_config import get_reception_api_base_url
    if not patient_id:
        return None
    try:
        url = get_reception_api_base_url().rstrip('/') + '/api/pacs/patients/' + quote(str(patient_id), safe='')
        with requests.get(url, timeout=(5, 15), stream=True) as response:
            response.raise_for_status()
            raw = bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw) > 1024 * 1024:
                    return None
            import json
            return json.loads(raw)
    except (requests.RequestException, ValueError, TypeError):
        return None


def lookup_reception(patient_id):
    return reception_sex(lookup_payload(patient_id), patient_id)


def parse_date(value, *, reception=False):
    """Reception BD uses Jalali for 12xx-15xx; DICOM dates remain Gregorian."""
    import re
    from datetime import date
    text = str(value or '').strip()
    match = re.fullmatch(r'(\d{4})([-/]?)(\d{2})\2(\d{2})',text)
    if not match:
        return None, None
    year, month, day = map(int,(match[1],match[3],match[4]))
    if reception and 1200 <= year <= 1500:
        from PySide6.QtCore import QCalendar
        calendar = QCalendar(QCalendar.System.Jalali)
        if not calendar.isDateValid(year,month,day):
            return None, None
        converted = calendar.dateFromParts(year,month,day)
        result = date(converted.year(),converted.month(),converted.day())
        return (result,'Jalali') if 1900 <= result.year <= 2100 else (None,None)
    try:
        result = date(year,month,day)
        return (result,'Gregorian') if 1900 <= year <= 2100 else (None,None)
    except ValueError:
        return None,None


def prepare_review(context, sex, study_uid, *, lookup=None):
    """Prepare a private, study-bound draft off the GUI thread."""
    patient_id = str(context.get('patient_id') or '')
    payload = (lookup or lookup_payload)(patient_id) if patient_id else None
    rows = payload.get('data') if isinstance(payload, dict) else None
    rows = rows if isinstance(rows, list) else [rows]
    matches = [r for r in rows if isinstance(r, dict) and str(r.get('receptionId', '')) == patient_id]
    patient = matches[0].get('patient', {}) if len(matches) == 1 else {}
    patient = patient if isinstance(patient, dict) else {}
    sources = {}
    def select(key, reception, dicom):
        if reception not in (None, ''):
            sources[key] = 'reception'
            return reception
        sources[key] = 'dicom' if dicom not in (None, '') else 'missing'
        return dicom or ''
    name = select('name', patient.get('Name'), context.get('patient_name'))
    chosen_sex = select('sex', normalize(patient.get('Gender')), normalize(sex))
    reception_birth, reception_calendar = parse_date(patient.get('BD'),reception=True)
    dicom_birth, dicom_calendar = parse_date(context.get('patient_birth_date'))
    birth = select('birth_date', reception_birth, dicom_birth)
    birth_calendar = reception_calendar if reception_birth else dicom_calendar
    study_date = parse_date(context.get('study_date'))[0]
    months = None
    if birth and study_date and birth <= study_date:
        months = (study_date.year - birth.year) * 12 + study_date.month - birth.month
        months -= study_date.day < birth.day
    return dict(study_uid=study_uid, patient_id=patient_id, name=str(name), sex=chosen_sex,
                birth_date=birth.isoformat() if birth else '',
                birth_calendar=birth_calendar,
                study_date=study_date.isoformat() if study_date else '',
                chronological_age_months=months, sources=sources)


def validate_review(value, study_uid, patient_id):
    if (not isinstance(value, dict) or value.get('study_uid') != study_uid or
            value.get('patient_id') != patient_id or not str(value.get('name') or '').strip() or
            normalize(value.get('sex')) is None or
            type(value.get('chronological_age_months')) is not int or
            not 0 <= value['chronological_age_months'] <= 240):
        raise ValueError('Confirm patient name, sex and age for this study.')
    return dict(value, name=value['name'].strip(), sex=normalize(value['sex']), physician_confirmed=True)


def resolve(dicom_sex, patient_id, study_uid, *, lookup=None):
    sex = normalize(dicom_sex)
    if sex:
        return sex, None
    if not patient_id:
        return None, None
    sex = normalize((lookup or lookup_reception)(patient_id))
    if sex:
        return sex, dict(source='reception', patient_id=str(patient_id), study_uid=study_uid)
    return None, None


def validate_provenance(evidence, study_uid):
    if (not isinstance(evidence, dict) or set(evidence) != {'source', 'patient_id', 'study_uid'}
            or evidence['source'] not in ('reception', 'physician', 'physician-review')
            or evidence['study_uid'] != study_uid
            or not isinstance(evidence['patient_id'], str)
            or not 1 <= len(evidence['patient_id']) <= 64):
        raise ValueError('Bone Age demographic confirmation does not match this study.')
    return evidence
