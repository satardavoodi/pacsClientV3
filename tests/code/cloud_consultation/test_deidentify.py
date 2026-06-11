"""Guards for the consultation package de-identifier (B3 / ADR-0003, 2026-06-10).

Qt-free. Invariants under test:
* identifying attributes are blanked/replaced in every staged DICOM, in place;
* a file that cannot be de-identified is DELETED from the package (never leaks);
* sidecar json manifests are scrubbed key-by-key;
* an empty staging tree is tolerated (unit tests stub the export engine);
* losing EVERY image to exclusions is a hard fail (``ok`` False) and the
  export callable in study_select raises on it.
"""

from pathlib import Path

import pytest

from modules.cloud_consultation.consultation.deidentify import (
    ANONYMOUS_VALUE,
    DeidentifyResult,
    deidentify_package,
)


def _write_dicom(path: Path, patient_name="DOE^JANE", patient_id="12345"):
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.PatientBirthDate = "19800101"
    ds.AccessionNumber = "ACC-77"
    ds.InstitutionName = "Alizadeh Imaging Center"
    ds.ReferringPhysicianName = "REF^DOC"
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "OT"
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), write_like_original=False)
    return ds.StudyInstanceUID


def test_dicom_attributes_scrubbed_in_place(tmp_path):
    from pydicom import dcmread

    study_uid = _write_dicom(tmp_path / "1.2.3" / "1" / "img1.dcm")
    result = deidentify_package(str(tmp_path))

    assert result.ok and result.processed_files == 1 and result.excluded_files == 0
    ds = dcmread(str(tmp_path / "1.2.3" / "1" / "img1.dcm"))
    assert str(ds.PatientName).startswith("ANONYMOUS")
    assert str(ds.PatientID).startswith("ANON")
    assert str(ds.AccessionNumber).startswith("ANON")
    assert ds.PatientBirthDate == ""
    assert ds.InstitutionName == ""
    assert ds.ReferringPhysicianName == ""
    # UIDs intentionally preserved so package metadata keeps matching.
    assert ds.StudyInstanceUID == study_uid


def test_unreadable_file_is_excluded_never_leaked(tmp_path):
    bad = tmp_path / "study" / "broken.dcm"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"NOT A DICOM FILE")
    good = tmp_path / "study" / "img.dcm"
    _write_dicom(good)

    result = deidentify_package(str(tmp_path))

    assert result.processed_files == 1
    assert result.excluded_files == 1
    assert not bad.exists()  # the identified/broken file must be GONE
    assert good.exists()
    assert result.ok  # one clean image survived


def test_all_images_lost_is_a_hard_fail(tmp_path):
    bad = tmp_path / "only.dcm"
    bad.write_bytes(b"garbage")

    result = deidentify_package(str(tmp_path))

    assert result.excluded_files == 1 and result.processed_files == 0
    assert result.ok is False


def test_sidecar_json_scrubbed(tmp_path):
    import json

    _write_dicom(tmp_path / "img.dcm")
    meta = tmp_path / "metadata.json"
    meta.write_text(
        json.dumps(
            {
                "patient_name": "DOE^JANE",
                "patient_id": "12345",
                "studies": [{"PatientName": "DOE^JANE", "study_uid": "1.2.3"}],
                "study_description": "Brain MRI",
            }
        ),
        encoding="utf-8",
    )

    result = deidentify_package(str(tmp_path))
    payload = json.loads(meta.read_text(encoding="utf-8"))

    assert result.scrubbed_json == 1
    assert payload["patient_name"] == ANONYMOUS_VALUE
    assert payload["patient_id"] == ANONYMOUS_VALUE
    assert payload["studies"][0]["PatientName"] == ANONYMOUS_VALUE
    assert payload["studies"][0]["study_uid"] == "1.2.3"  # non-identifying kept
    assert payload["study_description"] == "Brain MRI"


def test_summary_written_and_empty_tree_tolerated(tmp_path):
    result = deidentify_package(str(tmp_path / "does-not-exist"))
    assert result.ok and result.processed_files == 0  # stubbed-export tolerance

    _write_dicom(tmp_path / "img.dcm")
    result = deidentify_package(str(tmp_path))
    assert (tmp_path / "deidentification.json").exists()
    assert result.ok


def test_result_ok_semantics():
    assert DeidentifyResult().ok is True
    assert DeidentifyResult(processed_files=3, excluded_files=1).ok is True
    assert DeidentifyResult(processed_files=0, excluded_files=2).ok is False
