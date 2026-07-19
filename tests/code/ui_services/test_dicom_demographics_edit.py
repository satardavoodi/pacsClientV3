"""Guards for the right-click ▸ "Edit patient / study info…" demographic editor.

THE INVARIANT THIS FILE EXISTS TO PROTECT
-----------------------------------------
A demographic edit must NEVER rewrite a DICOM identity element. The on-disk
layout, the thumbnails, the local DB and the fail-closed viewport identity gate
are all keyed on Study/Series/SOP InstanceUID — regenerating one would present
as the recurring "series won't display" class of defect (48912 / 49836 / 50238).

Tests run against REAL synthetic DICOM files written to a tmp_path, not mocks,
so the guarantee is checked on the bytes actually written.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pydicom = pytest.importorskip("pydicom")

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from PacsClient.utils import dicom_demographics_edit as dde


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_instance(path: Path, study_uid: str, series_uid: str, sop_uid: str):
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = meta
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.FrameOfReferenceUID = generate_uid()

    ds.PatientName = "WRONG^NAME"
    ds.PatientID = "OLD123"
    ds.PatientAge = "030Y"
    ds.InstitutionName = "Old Clinic"
    ds.StudyDate = "20200101"
    ds.StudyTime = "090000"
    ds.Modality = "CT"
    ds.SeriesNumber = 1

    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), write_like_original=False)


@pytest.fixture()
def study(tmp_path):
    """A 2-series study, 3 instances each."""
    study_uid = generate_uid()
    root = tmp_path / "dicom" / study_uid
    sop_uids = []
    for series_number in (1, 2):
        series_uid = generate_uid()
        for i in range(1, 4):
            sop = generate_uid()
            sop_uids.append(sop)
            _make_instance(
                root / str(series_number) / f"Instance_{i:04d}.dcm",
                study_uid,
                series_uid,
                sop,
            )
    return study_uid, root, sop_uids


def _all_uids(root: Path):
    found = {}
    for path in dde.iter_study_dicom_files(root):
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        found[path.name + str(path.parent.name)] = (
            str(ds.StudyInstanceUID),
            str(ds.SeriesInstanceUID),
            str(ds.SOPInstanceUID),
            str(ds.file_meta.MediaStorageSOPInstanceUID),
        )
    return found


# ---------------------------------------------------------------------------
# THE core guarantee
# ---------------------------------------------------------------------------


def test_uids_are_never_rewritten(study, tmp_path):
    study_uid, root, _sops = study
    before = _all_uids(root)

    result = dde.apply_demographic_edit(
        [(study_uid, root)],
        {
            "patient_name": "RIGHT^NAME",
            "patient_id": "NEW999",
            "institution_name": "New Clinic",
            "study_date": "20260718",
            "study_time": "143000",
            "patient_age": "045Y",
        },
        backup_root=tmp_path / "backups",
    )

    assert result.ok, result.summary()
    assert _all_uids(root) == before, "a DICOM identity element was rewritten"


def test_edit_reaches_every_series_and_every_image(study, tmp_path):
    study_uid, root, _sops = study

    result = dde.apply_demographic_edit(
        [(study_uid, root)],
        {"patient_name": "RIGHT^NAME"},
        backup_root=tmp_path / "backups",
    )

    assert result.total_files == 6
    assert result.edited_files == 6
    for path in dde.iter_study_dicom_files(root):
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        assert str(ds.PatientName) == "RIGHT^NAME"


def test_all_six_fields_are_written(study, tmp_path):
    study_uid, root, _sops = study
    values = {
        "patient_name": "TEST^PATIENT",
        "patient_id": "P-42",
        "institution_name": "Alizadeh Imaging",
        "study_date": "20260718",
        "study_time": "143000",
        "patient_age": "045Y",
    }
    dde.apply_demographic_edit(
        [(study_uid, root)], values, backup_root=tmp_path / "backups"
    )

    ds = pydicom.dcmread(
        str(next(dde.iter_study_dicom_files(root))), stop_before_pixels=True, force=True
    )
    assert str(ds.PatientName) == "TEST^PATIENT"
    assert ds.PatientID == "P-42"
    assert ds.InstitutionName == "Alizadeh Imaging"
    assert ds.StudyDate == "20260718"
    assert ds.StudyTime == "143000"
    assert ds.PatientAge == "045Y"


def test_unicode_name_survives_roundtrip(study, tmp_path):
    """Persian names are routine here — they must not come back mojibake."""
    study_uid, root, _sops = study
    dde.apply_demographic_edit(
        [(study_uid, root)],
        {"patient_name": "علیزاده^وحید"},
        backup_root=tmp_path / "backups",
    )
    ds = pydicom.dcmread(
        str(next(dde.iter_study_dicom_files(root))), stop_before_pixels=True, force=True
    )
    assert str(ds.PatientName) == "علیزاده^وحید"
    assert "ISO_IR 192" in str(ds.SpecificCharacterSet)


# ---------------------------------------------------------------------------
# Backup / rollback / atomicity
# ---------------------------------------------------------------------------


def test_backup_is_created_before_any_write(study, tmp_path):
    study_uid, root, _sops = study
    backups = tmp_path / "backups"

    result = dde.apply_demographic_edit(
        [(study_uid, root)], {"patient_name": "X^Y"}, backup_root=backups
    )

    sr = result.studies[0]
    assert sr.backup_dir is not None
    backup = Path(sr.backup_dir)
    assert backup.is_dir()
    assert len(list(backup.rglob("*.dcm"))) == 6
    # the backup holds the ORIGINAL values
    ds = pydicom.dcmread(str(next(backup.rglob("*.dcm"))), force=True)
    assert str(ds.PatientName) == "WRONG^NAME"


def test_failure_rolls_the_study_back(study, tmp_path, monkeypatch):
    study_uid, root, _sops = study
    calls = {"n": 0}
    real = dde._edit_one_file

    def flaky(path, values, force_utf8):
        calls["n"] += 1
        if calls["n"] == 3:
            raise ValueError("simulated mid-study failure")
        return real(path, values, force_utf8)

    monkeypatch.setattr(dde, "_edit_one_file", flaky)

    result = dde.apply_demographic_edit(
        [(study_uid, root)],
        {"patient_name": "SHOULD^NOTSTICK"},
        backup_root=tmp_path / "backups",
    )

    assert not result.ok
    assert result.studies[0].rolled_back
    for path in dde.iter_study_dicom_files(root):
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        assert str(ds.PatientName) == "WRONG^NAME", "rollback left a partial edit"


def test_uid_violation_is_detected_and_rolled_back(study, tmp_path, monkeypatch):
    """If anything ever did disturb a UID, the write must fail loudly."""
    study_uid, root, _sops = study
    real = dde._apply_to_dataset

    def sabotage(ds, values, force_utf8):
        changed = real(ds, values, force_utf8)
        ds.SeriesInstanceUID = generate_uid()  # the thing we must never allow
        return changed

    monkeypatch.setattr(dde, "_apply_to_dataset", sabotage)

    result = dde.apply_demographic_edit(
        [(study_uid, root)],
        {"patient_name": "X^Y"},
        backup_root=tmp_path / "backups",
    )

    assert not result.ok
    assert "UID immutability violated" in (result.studies[0].error or "")
    assert result.studies[0].rolled_back


def test_no_part_files_are_left_behind(study, tmp_path):
    study_uid, root, _sops = study
    dde.apply_demographic_edit(
        [(study_uid, root)], {"patient_name": "X^Y"}, backup_root=tmp_path / "backups"
    )
    assert not list(root.rglob("*.part"))


def test_in_flight_part_files_are_never_edited(study, tmp_path):
    """A .part belongs to an in-flight download — touching it corrupts it."""
    study_uid, root, _sops = study
    part = root / "1" / "Instance_0009.dcm.part"
    part.write_bytes(b"\x00" * 512)

    files = list(dde.iter_study_dicom_files(root))
    assert part not in files
    assert len(files) == 6

    dde.apply_demographic_edit(
        [(study_uid, root)], {"patient_name": "X^Y"}, backup_root=tmp_path / "backups"
    )
    assert part.read_bytes() == b"\x00" * 512


# ---------------------------------------------------------------------------
# Validation / normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key,raw,expected",
    [
        ("study_date", "2026-07-18", "20260718"),
        ("study_time", "14:30:00", "143000"),
        ("patient_age", "45", "045Y"),
        ("patient_age", "45y", "045Y"),
        ("patient_age", "6m", "006M"),
        ("patient_name", "  Doe^John  ", "Doe^John"),
    ],
)
def test_normalisation(key, raw, expected):
    assert dde.normalize_value(key, raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["18 July 2026", "not-a-date", "July18", "2026/13/01"],
)
def test_a_mistyped_date_is_rejected_not_silently_cleared(raw):
    """Regression: normalisation used to strip ALL non-digits, so a typo
    collapsed to "" — which reads as "clear this tag" and would have DELETED
    the study date instead of reporting the mistake."""
    normalized = dde.normalize_value("study_date", raw)
    assert normalized != "", f"{raw!r} collapsed to empty (silent data loss)"
    assert dde.validate_edit({"study_date": raw}), f"{raw!r} should be rejected"


@pytest.mark.parametrize(
    "values",
    [
        {"study_date": "20261301"},   # month 13
        {"study_date": "2026"},       # too short
        {"study_time": "996000"},     # hour 99
        {"patient_age": "45years"},
        {"patient_id": ""},           # keys the whole local hierarchy
        {"patient_id": "a" * 65},     # over the DICOM LO limit
    ],
)
def test_invalid_values_are_rejected(values):
    assert dde.validate_edit(values), f"{values} should have been rejected"


def test_invalid_input_writes_nothing(study, tmp_path):
    study_uid, root, _sops = study
    with pytest.raises(ValueError):
        dde.apply_demographic_edit(
            [(study_uid, root)],
            {"study_date": "not-a-date"},
            backup_root=tmp_path / "backups",
        )
    ds = pydicom.dcmread(
        str(next(dde.iter_study_dicom_files(root))), stop_before_pixels=True, force=True
    )
    assert ds.StudyDate == "20200101"


def test_read_demographics_round_trips(study):
    _study_uid, root, _sops = study
    values = dde.read_demographics(root)
    assert values["patient_name"] == "WRONG^NAME"
    assert values["patient_id"] == "OLD123"
    assert values["institution_name"] == "Old Clinic"
    assert values["study_date"] == "20200101"
    assert values["study_time"] == "090000"
    assert values["patient_age"] == "030Y"


def test_missing_study_folder_is_reported_not_fatal(tmp_path):
    result = dde.apply_demographic_edit(
        [("1.2.3.missing", tmp_path / "nope")],
        {"patient_name": "X^Y"},
        backup_root=tmp_path / "backups",
    )
    assert not result.ok
    assert "not found" in (result.studies[0].error or "")


def test_multi_study_edit_covers_every_study(tmp_path):
    studies = []
    for _ in range(3):
        uid = generate_uid()
        root = tmp_path / "dicom" / uid
        _make_instance(root / "1" / "Instance_0001.dcm", uid, generate_uid(), generate_uid())
        studies.append((uid, root))

    result = dde.apply_demographic_edit(
        studies, {"patient_id": "SHARED-1"}, backup_root=tmp_path / "backups"
    )

    assert result.ok
    assert len(result.studies) == 3
    for _uid, root in studies:
        ds = pydicom.dcmread(
            str(next(dde.iter_study_dicom_files(root))), stop_before_pixels=True, force=True
        )
        assert ds.PatientID == "SHARED-1"


# ---------------------------------------------------------------------------
# Scope honesty + wiring pins
# ---------------------------------------------------------------------------


def test_server_push_is_reported_unsupported():
    """No socket command and no REST endpoint accepts a demographic field.

    If a server-side endpoint is ever added, flip `server_push_supported()` —
    this test is the reminder that the UI copy depends on it.
    """
    assert dde.server_push_supported() is False


def test_result_carries_the_local_only_note(study, tmp_path):
    study_uid, root, _sops = study
    result = dde.apply_demographic_edit(
        [(study_uid, root)], {"patient_name": "X^Y"}, backup_root=tmp_path / "backups"
    )
    assert "local to this workstation" in result.server_push_note


def _src(rel: str) -> str:
    root = Path(__file__).resolve().parents[3]
    return (root / rel).read_text(encoding="utf-8", errors="ignore")


def test_context_menu_offers_edit_and_is_wired():
    table = _src("PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py")
    assert "editPatientInfoRequested = Signal(str, str, list)" in table
    assert "Edit patient / study info" in table
    assert "_CONTEXT_MENU_QSS" in table
    assert "editPatientInfoRequested.emit" in table
    # the pre-existing action must survive
    assert "Refresh / Sync from server" in table

    layout = _src("PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_layout.py")
    assert "editPatientInfoRequested.connect" in layout
    assert "resyncFromServerRequested.connect" in layout

    widget = _src("PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py")
    assert "_HPPatientEditMixin" in widget


def test_editor_runs_off_the_gui_thread():
    dialog = _src("PacsClient/pacs/workstation_ui/home_ui/patient_edit_dialog.py")
    assert "QThread" in dialog
    assert "class _DemographicEditWorker" in dialog
    # the apply must not be called inline from the GUI thread
    assert "self._worker.start()" in dialog


def test_db_force_helpers_exist_and_are_unconditional():
    manager = _src("database/manager.py")
    for fn in (
        "def force_update_patient_demographics",
        "def force_update_study_demographics",
        "def force_update_series_institution",
    ):
        assert fn in manager
    # the fill-only guard must NOT be reused by the force helpers
    forced = manager.split("def force_update_patient_demographics", 1)[1]
    forced = forced.split("def update_series_missing_fields", 1)[0]
    assert "_build_update_if_missing_clause" not in forced
