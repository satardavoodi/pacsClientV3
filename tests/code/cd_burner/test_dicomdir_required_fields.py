"""DICOMDIR build must not silently drop images missing directory fields.

Regression for patient 46419 (2026-06-15): a single image lacking
StudyDate/StudyTime/StudyID/AccessionNumber made pydicom's FileSet.add()
raise; the exception was swallowed and an empty DICOMDIR (0 images) was
written, yet the burn reported success → a disc with no DICOM files.
"""

import warnings

import numpy as np
import pytest
from pydicom import dcmread
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from modules.cd_burner.dicomdir_builder import (
    DicomDirBuilder,
    _ensure_dicomdir_fields,
)


def _minimal_image(path, *, drop=()):  # drop = element keywords to omit
    sop = generate_uid()
    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"  # Secondary Capture
    fm.MediaStorageSOPInstanceUID = sop
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = fm
    ds.SOPClassUID = fm.MediaStorageSOPClassUID
    ds.SOPInstanceUID = sop
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientName = "ONE^IMAGE"
    ds.PatientID = "46419"
    # Fields a server image may omit (the bug): StudyDate/Time/ID/Accession
    ds.StudyDate = "20260615"
    ds.StudyTime = "120000"
    ds.StudyID = "1"
    ds.AccessionNumber = "A1"
    ds.Modality = "OT"
    ds.SeriesNumber = "1"
    ds.InstanceNumber = "1"
    for keyword in drop:
        if keyword in ds:
            delattr(ds, keyword)

    rows, cols = 16, 16
    ds.Rows, ds.Columns = rows, cols
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.PixelData = np.zeros((rows, cols), dtype=np.uint16).tobytes()
    ds.save_as(str(path), write_like_original=False)
    return path


def test_ensure_fields_backfills_missing():
    ds = Dataset()
    ds.PatientName = "X"
    _ensure_dicomdir_fields(ds)
    assert ds.StudyID == "1"
    assert ds.Modality == "OT"
    assert ds.SeriesNumber == "1"
    assert ds.InstanceNumber == "1"
    assert ds.PatientID == "ANONYMOUS"
    assert "StudyDate" in ds  # present (empty allowed)


def test_ensure_fields_keeps_existing_values():
    ds = Dataset()
    ds.StudyID = "REAL-STUDY"
    ds.Modality = "CT"
    ds.PatientID = "P42"
    _ensure_dicomdir_fields(ds)
    assert ds.StudyID == "REAL-STUDY"
    assert ds.Modality == "CT"
    assert ds.PatientID == "P42"


@pytest.mark.parametrize("drop", [
    (),                                              # complete image
    ("StudyDate", "StudyTime"),                      # common server omission
    ("StudyID",),
    ("AccessionNumber",),
    ("StudyDate", "StudyTime", "StudyID", "AccessionNumber"),  # the 46419 case
])
def test_single_image_lands_in_dicomdir(tmp_path, drop):
    study = tmp_path / "study"
    study.mkdir()
    _minimal_image(study / "IM0001.dcm", drop=drop)
    out = tmp_path / "out"

    builder = DicomDirBuilder()
    ok = builder.build_from_study_folders([str(study)], str(out), fileset_id="PATIENT_CD")
    assert ok, f"build failed for dropped fields {drop}"

    # DICOMDIR references exactly one instance, and the image tree was written.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from pydicom.fileset import FileSet
        fs = FileSet(str(out / "DICOMDIR"))
    instances = list(fs)
    assert len(instances) == 1
    assert dcmread(str(instances[0].path)).pixel_array.shape == (16, 16)


def test_empty_or_unreadable_study_fails_loudly(tmp_path):
    """No addable instance → build returns False (never a silent empty disc)."""
    study = tmp_path / "junk"
    study.mkdir()
    (study / "notdicom.dcm").write_bytes(b"this is not a DICOM file")
    out = tmp_path / "out"

    builder = DicomDirBuilder()
    ok = builder.build_from_study_folders([str(study)], str(out), fileset_id="PATIENT_CD")
    assert ok is False
