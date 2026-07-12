"""Offline Sync export: human-readable folders + standards-compliant DICOMDIR.

Layout (the user's preferred "Option A"):

    <package>/
    ├── patients/dicom/<study_uid>/…        AI-PACS payload — MUST stay untouched
    └── DICOM/
        └── <Patient_Name>/
            └── <StudyInstanceUID>/
                ├── DICOMDIR                File IDs relative to HERE → compliant
                └── PT000000/ST000000/SE000000/IM000001

The readable names sit ABOVE the DICOMDIR, where the <=8-char [A-Z0-9_] File ID
rule (PS3.10) does not apply — which is exactly why a single media-root DICOMDIR
can never carry readable folder names.
"""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.fileset import FileSet
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from PacsClient.utils.offline_cloud import (
    build_offline_cloud_dicomdir,
    safe_folder_component,
)

CT_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.2"


def _write_ct(folder: Path, *, study_uid, series_uid, instance_number,
              patient_id="PID-1", patient_name="DOE^JOHN",
              series_number=1, sop_uid=None, filename=None) -> Path:
    sop_uid = sop_uid or generate_uid()
    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = CT_SOP_CLASS
    fm.MediaStorageSOPInstanceUID = sop_uid
    fm.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = fm
    ds.SOPClassUID = CT_SOP_CLASS
    ds.SOPInstanceUID = sop_uid
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.StudyDate = "20260101"
    ds.StudyTime = "120000"
    ds.StudyID = "1"
    ds.AccessionNumber = "ACC1"
    ds.Modality = "CT"
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_number
    ds.InstanceNumber = instance_number

    arr = np.full((8, 8), 100, dtype=np.uint16)
    ds.Rows, ds.Columns = 8, 8
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.PixelData = arr.tobytes()

    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (filename or f"IM{instance_number:04d}.dcm")
    ds.save_as(str(path), write_like_original=False)
    return path


def _pkg(tmp_path: Path) -> Path:
    root = tmp_path / "package"
    (root / "patients" / "dicom").mkdir(parents=True)
    (root / "patients" / "attachments").mkdir(parents=True)
    (root / "patients" / "thumbnails").mkdir(parents=True)
    return root


def _fs(study_folder: Path) -> FileSet:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return FileSet(str(study_folder / "DICOMDIR"))


# ---------------------------------------------------------------------------
# filename safety
# ---------------------------------------------------------------------------

def test_safe_folder_component_normalizes_names():
    assert safe_folder_component("DOE^JOHN") == "DOE_JOHN"
    assert safe_folder_component("  Jane   Smith  ") == "Jane_Smith"
    # illegal filesystem characters removed, readability preserved
    assert safe_folder_component('Bad<>:"/\\|?*Name') == "BadName"
    # Windows rejects trailing dots/spaces
    assert safe_folder_component("Trailing. ") == "Trailing"
    assert safe_folder_component("") == "UNKNOWN"
    assert safe_folder_component("^^^") == "UNKNOWN"


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------

def test_single_patient_readable_folder_with_study_uid(tmp_path):
    root = _pkg(tmp_path)
    study, series = generate_uid(), generate_uid()
    _write_ct(root / "patients" / "dicom" / study / "1",
              study_uid=study, series_uid=series, instance_number=1)
    _write_ct(root / "patients" / "dicom" / study / "1",
              study_uid=study, series_uid=series, instance_number=2)

    result = build_offline_cloud_dicomdir(root)

    assert result["ok"] is True
    assert result["patients"] == 1 and result["studies"] == 1
    assert result["instances_added"] == 2

    # readable patient folder, study UID still present, DICOMDIR inside
    study_folder = root / "DICOM" / "DOE_JOHN" / study
    assert study_folder.is_dir()                     # human-readable + unique
    assert (study_folder / "DICOMDIR").is_file()
    assert any(p.name.startswith("PT") for p in study_folder.iterdir() if p.is_dir())

    # DICOM hierarchy Patient -> Study -> Series -> Image resolves
    for inst in _fs(study_folder):
        assert Path(str(inst.path)).exists()
        assert str(inst.StudyInstanceUID) == study
        assert str(inst.SeriesInstanceUID) == series


def test_multiple_patients_get_independent_folders(tmp_path):
    root = _pkg(tmp_path)
    dicom = root / "patients" / "dicom"
    people = [
        ("DOE^JOHN", "P1", "DOE_JOHN"),
        ("SMITH^JANE", "P2", "SMITH_JANE"),
        ("BROWN^MICHAEL", "P3", "BROWN_MICHAEL"),
    ]
    uids = {}
    for name, pid, _folder in people:
        s = generate_uid()
        uids[pid] = s
        _write_ct(dicom / s / "1", study_uid=s, series_uid=generate_uid(),
                  instance_number=1, patient_name=name, patient_id=pid)

    result = build_offline_cloud_dicomdir(root)

    assert result["ok"] is True
    assert result["patients"] == 3 and result["studies"] == 3
    assert sorted(result["patient_folders"]) == ["BROWN_MICHAEL", "DOE_JOHN", "SMITH_JANE"]

    for _name, pid, folder in people:
        study_folder = root / "DICOM" / folder / uids[pid]
        assert (study_folder / "DICOMDIR").is_file()      # independent DICOMDIR
        assert len(list(_fs(study_folder))) == 1


def test_multiple_studies_for_one_patient(tmp_path):
    root = _pkg(tmp_path)
    dicom = root / "patients" / "dicom"
    s1, s2 = generate_uid(), generate_uid()
    for s in (s1, s2):
        _write_ct(dicom / s / "1", study_uid=s, series_uid=generate_uid(),
                  instance_number=1, patient_name="DOE^JOHN", patient_id="P1")

    result = build_offline_cloud_dicomdir(root)

    assert result["ok"] is True
    assert result["patients"] == 1 and result["studies"] == 2
    # one readable patient folder, one sub-folder per study UID
    patient_dir = root / "DICOM" / "DOE_JOHN"
    assert sorted(p.name for p in patient_dir.iterdir()) == sorted([s1, s2])
    for s in (s1, s2):
        assert (patient_dir / s / "DICOMDIR").is_file()


def test_same_name_different_patients_are_disambiguated(tmp_path):
    """Two distinct patients with the same name must NOT share a folder."""
    root = _pkg(tmp_path)
    dicom = root / "patients" / "dicom"
    s1, s2 = generate_uid(), generate_uid()
    _write_ct(dicom / s1 / "1", study_uid=s1, series_uid=generate_uid(),
              instance_number=1, patient_name="DOE^JOHN", patient_id="P1")
    _write_ct(dicom / s2 / "1", study_uid=s2, series_uid=generate_uid(),
              instance_number=1, patient_name="DOE^JOHN", patient_id="P2")

    result = build_offline_cloud_dicomdir(root)

    assert result["ok"] is True
    assert result["patients"] == 2
    folders = sorted(result["patient_folders"])
    assert folders == ["DOE_JOHN_P1", "DOE_JOHN_P2"]     # PatientID disambiguates
    for f, s in (("DOE_JOHN_P1", s1), ("DOE_JOHN_P2", s2)):
        assert (root / "DICOM" / f / s / "DICOMDIR").is_file()


def test_ten_patients_keep_relationships(tmp_path):
    root = _pkg(tmp_path)
    dicom = root / "patients" / "dicom"
    expected = {}
    for i in range(10):
        s = generate_uid()
        ser = generate_uid()
        name = f"PATIENT^{i:02d}"
        _write_ct(dicom / s / "1", study_uid=s, series_uid=ser, instance_number=1,
                  patient_name=name, patient_id=f"PID{i:02d}")
        expected[f"PATIENT_{i:02d}"] = (s, ser)

    result = build_offline_cloud_dicomdir(root)

    assert result["ok"] is True
    assert result["patients"] == 10 and result["studies"] == 10
    for folder, (s, ser) in expected.items():
        fs = _fs(root / "DICOM" / folder / s)
        inst = list(fs)
        assert len(inst) == 1
        assert str(inst[0].StudyInstanceUID) == s
        assert str(inst[0].SeriesInstanceUID) == ser


# ---------------------------------------------------------------------------
# compliance / integrity
# ---------------------------------------------------------------------------

def test_dicomdir_stores_relative_file_ids_only(tmp_path):
    root = _pkg(tmp_path)
    study = generate_uid()
    _write_ct(root / "patients" / "dicom" / study / "1",
              study_uid=study, series_uid=generate_uid(), instance_number=1)
    assert build_offline_cloud_dicomdir(root)["ok"] is True

    raw = (root / "DICOM" / "DOE_JOHN" / study / "DICOMDIR").read_bytes()
    # no absolute/staging path, and no readable name leaks into a File ID
    assert bytes(str(root), "ascii", "ignore") not in raw
    assert b"DOE_JOHN" not in raw
    assert b"patients" not in raw


def test_duplicate_sops_skipped_and_uids_match_source(tmp_path):
    root = _pkg(tmp_path)
    study, series = generate_uid(), generate_uid()
    d = root / "patients" / "dicom" / study / "1"
    sop_a, sop_b = generate_uid(), generate_uid()
    _write_ct(d, study_uid=study, series_uid=series, instance_number=1, sop_uid=sop_a)
    _write_ct(d, study_uid=study, series_uid=series, instance_number=2, sop_uid=sop_b)
    _write_ct(d, study_uid=study, series_uid=series, instance_number=3,
              sop_uid=sop_a, filename="DUP.dcm")

    result = build_offline_cloud_dicomdir(root)

    assert result["ok"] is True
    assert result["duplicates_skipped"] == 1
    assert result["instances_added"] == 2
    fs = _fs(root / "DICOM" / "DOE_JOHN" / study)
    assert {str(i.SOPInstanceUID) for i in fs} == {sop_a, sop_b}


def test_files_without_extension_are_indexed(tmp_path):
    root = _pkg(tmp_path)
    study = generate_uid()
    _write_ct(root / "patients" / "dicom" / study / "1",
              study_uid=study, series_uid=generate_uid(), instance_number=1,
              filename="IM000001")
    result = build_offline_cloud_dicomdir(root)
    assert result["ok"] is True and result["instances_added"] == 1


def test_no_dicom_files_fails_loudly(tmp_path):
    root = _pkg(tmp_path)
    result = build_offline_cloud_dicomdir(root)
    assert result["ok"] is False and result["error"]
    assert not (root / "DICOM").exists()


# ---------------------------------------------------------------------------
# AI-PACS compatibility + regeneration
# ---------------------------------------------------------------------------

def test_aipacs_payload_layout_is_byte_identical(tmp_path):
    """patients/dicom/<study_uid> is the AI-PACS import contract — generating the
    readable interchange tree must not touch it (any AI-PACS version can import)."""
    root = _pkg(tmp_path)
    study = generate_uid()
    src = _write_ct(root / "patients" / "dicom" / study / "1",
                    study_uid=study, series_uid=generate_uid(), instance_number=1)
    before = src.read_bytes()

    assert build_offline_cloud_dicomdir(root)["ok"] is True

    assert (root / "patients" / "dicom" / study).is_dir()   # still keyed by UID
    assert src.is_file() and src.read_bytes() == before


def test_skip_when_unchanged_force_and_auto_rebuild(tmp_path):
    root = _pkg(tmp_path)
    study, series = generate_uid(), generate_uid()
    _write_ct(root / "patients" / "dicom" / study / "1",
              study_uid=study, series_uid=series, instance_number=1)

    first = build_offline_cloud_dicomdir(root)
    assert first["ok"] and first["skipped"] is False

    second = build_offline_cloud_dicomdir(root)
    assert second["ok"] and second["skipped"] is True      # cheap no-op

    third = build_offline_cloud_dicomdir(root, force=True)
    assert third["ok"] and third["skipped"] is False

    _write_ct(root / "patients" / "dicom" / study / "1",
              study_uid=study, series_uid=series, instance_number=2)
    fourth = build_offline_cloud_dicomdir(root)
    assert fourth["ok"] and fourth["skipped"] is False
    assert fourth["instances_added"] == 2


def test_regeneration_drops_removed_studies(tmp_path):
    root = _pkg(tmp_path)
    dicom = root / "patients" / "dicom"
    s1, s2 = generate_uid(), generate_uid()
    _write_ct(dicom / s1 / "1", study_uid=s1, series_uid=generate_uid(), instance_number=1,
              patient_name="DOE^JOHN", patient_id="P1")
    _write_ct(dicom / s2 / "1", study_uid=s2, series_uid=generate_uid(), instance_number=1,
              patient_name="SMITH^JANE", patient_id="P2")
    assert build_offline_cloud_dicomdir(root)["studies"] == 2

    shutil.rmtree(dicom / s2)
    result = build_offline_cloud_dicomdir(root)

    assert result["ok"] is True
    assert result["studies"] == 1
    assert result["patient_folders"] == ["DOE_JOHN"]
    assert (root / "DICOM" / "DOE_JOHN" / s1).is_dir()
    assert not (root / "DICOM" / "SMITH_JANE").exists()   # stale patient removed


def test_every_offline_sync_export_call_site_requests_dicomdir():
    """The builder being correct is worthless if the export never asks for it.

    Live regression (2026-07-12): the readable DICOMDIR tree was wired into the
    *autosync* path only, so the user-facing "Export to Offline Cloud" action
    still shipped a folder with no DICOMDIR and no patient-named folders. Both
    call sites in _hp_offline.py must pass include_dicomdir=True.
    """
    src = (
        Path(__file__).resolve().parents[3]
        / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "home_panel" / "_hp_offline.py"
    ).read_text(encoding="utf-8")

    call_sites = sum(
        1
        for line in src.splitlines()
        if "export_studies_to_offline_cloud" in line
        and not line.lstrip().startswith(("from ", "import ", "#", "def "))
    )
    assert call_sites >= 2, "expected the export + autosync call sites"
    assert src.count("include_dicomdir=True") == call_sites, (
        "every export_studies_to_offline_cloud call in _hp_offline.py must pass "
        "include_dicomdir=True — otherwise the exported media has no DICOMDIR"
    )
