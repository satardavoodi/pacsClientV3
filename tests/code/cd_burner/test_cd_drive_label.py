"""When a CD is inserted, Explorer should show the AI-PACS icon on the drive and
name the drive after the patient. Both come from autorun.inf (icon= / label=)
plus the volume label — all driven by the DICOM PatientName at burn time."""

import json
from pathlib import Path

from pydicom.uid import generate_uid

from modules.cd_burner.cd_burn_manager import CDBurnWorker

from .conftest import write_ct_slice


def test_cd_display_label_is_patient_name():
    w = CDBurnWorker(studies=[], burn_to_disc=False)
    # DICOM "Family^Given" → "FAMILY GIVEN" (normalized, ASCII-safe, ≤32)
    assert w._cd_display_label("GHSEMIYAM^SEKINEH", "FALLBACK") == "GHSEMIYAM SEKINEH"
    assert w._cd_display_label("TEST^PATIENT", "FALLBACK") == "TEST PATIENT"
    # no name → keep the resolved fallback label
    assert w._cd_display_label("", "FALLBACK") == "FALLBACK"


def test_cd_display_label_hidden_when_anonymized():
    w = CDBurnWorker(studies=[], burn_to_disc=False)
    w.options.anonymize = True
    # never put the real patient name on an anonymized disc
    assert w._cd_display_label("GHSEMIYAM^SEKINEH", "ANON_DISC") == "ANON_DISC"


def test_resolve_labels_returns_patient_name(tmp_path):
    study = tmp_path / "study"
    write_ct_slice(study, generate_uid(), generate_uid(), 1)  # PatientName=TEST^PATIENT
    w = CDBurnWorker(studies=[], burn_to_disc=False)
    fileset, volume, patient_name = w._resolve_labels([str(study)])
    assert patient_name == "TEST^PATIENT"
    assert w._cd_display_label(patient_name, volume) == "TEST PATIENT"


def test_autorun_sets_aipacs_icon_and_patient_label(tmp_path):
    """autorun.inf must point the drive icon at the AI-PACS .ico and name the
    drive after the patient (the volume_label passed in is the patient name)."""
    staging = tmp_path / "staging"
    staging.mkdir()
    w = CDBurnWorker(studies=[], burn_to_disc=False)
    w._write_portable_support_files(
        str(staging),
        fileset_label="DICOM",
        volume_label="TEST PATIENT",            # = the patient name (cd_name)
        viewer_launcher_relative_path=Path("VIEWER") / "AIPacsLiteViewer.exe",
        viewer_display_name="AI-PACS Lite Viewer",
        launcher_exe_name="AIPacsViewer.exe",
    )

    # the AI-PACS drive icon is staged at the media root
    assert (staging / "AIPACS.ico").exists()

    autorun = (staging / "autorun.inf").read_text(encoding="utf-8")
    assert "icon=AIPACS.ico" in autorun          # AI-PACS icon on the drive
    assert "label=TEST PATIENT" in autorun       # drive named after the patient

    manifest = json.loads((staging / "AIPACS_MEDIA_INFO.json").read_text(encoding="utf-8"))
    assert manifest["drive_icon"] == "AIPACS.ico"
    assert manifest["volume_label"] == "TEST PATIENT"
