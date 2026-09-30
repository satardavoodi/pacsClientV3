"""Copy a teaching study into the existing educational folder layout off-thread."""
from pathlib import Path
import os
import shutil
import uuid

from PySide6.QtCore import QThread


def import_dicom_folder(source, course_pk, *, replacement_name=None, keep_patient_id=True,
                        study_uid=None, series_number=None):
    import pydicom
    from modules.education.course_database import _ensure_course_storage

    if study_uid is not None:
        from PacsClient.utils.config import SOURCE_PATH
        if not pydicom.uid.UID(study_uid).is_valid:
            raise ValueError("Invalid study reference.")
        source = Path(SOURCE_PATH) / study_uid
        if series_number is not None:
            source = source / str(int(series_number))
    source = Path(source)
    if replacement_name is not None and not replacement_name.strip():
        raise ValueError("Enter a replacement patient name.")
    if not source.is_dir():
        raise ValueError("Select a local folder containing DICOM files.")
    records = []
    studies = set()
    series_numbers = {}
    for folder, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(folder) / d).is_symlink() and not (Path(folder) / d).is_junction()]
        for name in sorted(files):
            path = Path(folder) / name
            if path.is_symlink():
                continue
            if path.suffix.lower() not in {".dcm", ".dic", ".ima"}:
                with path.open("rb") as stream:
                    stream.seek(128)
                    if stream.read(4) != b"DICM":
                        continue
            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True, force=True,
                                    specific_tags=["StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID", "SeriesNumber"])
                study = str(ds.StudyInstanceUID)
                series = str(ds.SeriesInstanceUID)
                sop = str(ds.SOPInstanceUID)
                number = int(ds.SeriesNumber)
                if not all(pydicom.uid.UID(uid).is_valid for uid in (study, series, sop)) or number < 0:
                    raise ValueError()
            except Exception:
                if path.suffix.lower() in {".dcm", ".dic", ".ima"}:
                    raise ValueError("A DICOM file is unreadable or lacks study/series identity. Check the source folder.") from None
                continue
            studies.add(study)
            if len(studies) > 1:
                raise ValueError("This folder contains multiple studies. Select the folder for one study.")
            if number in series_numbers and series_numbers[number] != series:
                raise ValueError("Different series share a Series Number. Import them as separate folders.")
            series_numbers[number] = series
            records.append((path, number))
    if not records:
        raise ValueError("No usable DICOM instances were found in this folder.")
    root = _ensure_course_storage(course_pk).resolve()
    destination = root / ("dicom_" + uuid.uuid4().hex)
    new_patient_id = "EDU-" + uuid.uuid4().hex[:12]
    try:
        for index, (path, number) in enumerate(records):
            target = destination / str(number) / f"{index:08d}.dcm"
            target.parent.mkdir(parents=True, exist_ok=True)
            if replacement_name is None:
                shutil.copy2(path, target)
            else:
                ds = pydicom.dcmread(path, force=True)
                ds.decode()
                ds.SpecificCharacterSet = "ISO_IR 192"
                for element in ds.iterall():
                    if element.keyword == "SpecificCharacterSet":
                        element.value = "ISO_IR 192"
                    if element.keyword in {"PatientName", "OtherPatientNames"}:
                        element.value = replacement_name.strip()
                    if not keep_patient_id and element.keyword in {"PatientID", "OtherPatientIDs"}:
                        element.value = new_patient_id
                ds.PatientName = replacement_name.strip()
                if not keep_patient_id:
                    ds.PatientID = new_patient_id
                ds.save_as(target, write_like_original=True)
        result = {"path": str(destination), "study_uid": next(iter(studies))}
        if series_number is not None:
            result["series_number"] = int(series_number)
        if replacement_name is not None:
            result["patient_name_changed"] = True
        return result
    except Exception:
        if destination.parent == root and destination.exists():
            shutil.rmtree(destination)
        raise


class DicomFolderImportTask(QThread):
    def __init__(self, source, course_pk, parent=None, **options):
        super().__init__(parent)
        self.source, self.course_pk = source, course_pk
        self.options = options
        self.result = None
        self.error = ""

    def run(self):
        try:
            self.result = import_dicom_folder(self.source, self.course_pk, **self.options)
        except ValueError as exc:
            self.error = str(exc)
        except Exception:
            self.error = "Could not import the folder. Check file access and available storage."
