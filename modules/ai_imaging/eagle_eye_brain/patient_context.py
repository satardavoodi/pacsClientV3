"""Local DICOM report identity. Never include this context in model inputs or logs."""
from datetime import datetime
from pathlib import Path
import re

from .contracts import BrainError
from .normative import BrainDemographics

TAGS = {"patient_name": "PatientName", "patient_id": "PatientID", "birth_date": "PatientBirthDate",
        "sex": "PatientSex", "study_date": "StudyDate", "accession": "AccessionNumber",
        "institution": "InstitutionName", "study_uid": "StudyInstanceUID",
        "series_uid": "SeriesInstanceUID", "frame_uid": "FrameOfReferenceUID", "age_tag": "PatientAge",
        "manufacturer": "Manufacturer", "field_strength_t": "MagneticFieldStrength"}


def age_at_examination(birth, study, age_tag=""):
    try:
        dob, exam = [datetime.strptime(value, "%Y%m%d").date() for value in (birth, study)]
        days = (exam - dob).days
        return (days / 365.2425, "DICOM birth date / study date") if 0 <= days <= 120 * 365.2425 else (None, "Invalid DICOM date interval")
    except ValueError:
        match = re.fullmatch(r"(\d{3})([DWMY])", age_tag)
        if match:
            amount, unit = match.groups()
            years = int(amount) * {"D": 1 / 365.2425, "W": 7 / 365.2425, "M": 1 / 12, "Y": 1}[unit]
            if years <= 120:
                return years, "DICOM PatientAge (approximate)"
        return None, "Age not available in DICOM"


def dicom_context(source):
    if not Path(source).is_dir():
        return {"identity_status": "Unavailable: NIfTI has no verified DICOM identity"}
    import SimpleITK as sitk
    import pydicom
    ids = sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(source))
    if len(ids or ()) != 1:
        raise BrainError("Report identity requires exactly one DICOM series.")
    files = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(source), ids[0])
    values = {key: set() for key in TAGS}
    for file in files:
        ds = pydicom.dcmread(file, stop_before_pixels=True, specific_tags=list(TAGS.values()))
        for key, tag in TAGS.items():
            value = str(getattr(ds, tag, "")).strip()
            if value:
                values[key].add(value)
    if any(len(items) > 1 for items in values.values()):
        raise BrainError("DICOM demographics or examination identity differ within the selected series.")
    result = {key: next(iter(items), "") for key, items in values.items()}
    if not result["study_uid"] or not result["series_uid"]:
        raise BrainError("DICOM examination identity is incomplete.")
    result["age_years"], result["age_source"] = age_at_examination(result["birth_date"], result["study_date"], result["age_tag"])
    result["identity_status"] = "DICOM series verified" if result["patient_id"] and result["patient_name"] else "DICOM patient fields incomplete"
    return result


def demographics_for_report(context, manual=None):
    manual = manual or BrainDemographics()
    recorded = context.get("sex")
    sex = {"F": "female", "M": "male"}.get(recorded, "unknown") if recorded else manual.sex
    age = context.get("age_years")
    return BrainDemographics(age if age is not None else manual.age_years, sex)


def require_same_examination(t1_context, flair_context):
    for key in ("patient_id", "study_uid", "frame_uid"):
        a, b = t1_context.get(key), flair_context.get(key)
        if a and b and a != b:
            raise BrainError("T1 and FLAIR DICOM examinations do not match.")
