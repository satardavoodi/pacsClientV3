"""Hermetic tests for the consultation envelope (no Qt, no network, no DB, no engine)."""

from pathlib import Path

from modules.cloud_consultation.consultation import envelope as env_mod
from modules.cloud_consultation.consultation import service
from modules.cloud_consultation.consultation.models import ConsultationStatus, ENVELOPE_FILENAME


def _make_package(tmp: Path) -> Path:
    pkg = tmp / "pkg_1.2.840.STUDY"
    (pkg / "patients" / "dicom" / "1.2.3").mkdir(parents=True)
    (pkg / "manifest.json").write_text(
        '{"format":"aipacs-offline-cloud","version":2}', encoding="utf-8"
    )
    (pkg / "package.db").write_bytes(b"SQLite format 3\x00data")
    (pkg / "patients" / "dicom" / "1.2.3" / "img1.dcm").write_bytes(b"DICM\x00\x01")
    (pkg / "patients" / "dicom" / "1.2.3" / "img2.dcm").write_bytes(b"DICM\x02\x03")
    return pkg


def test_seal_and_read_roundtrip(tmp_path):
    pkg = _make_package(tmp_path)
    env = service.seal_package_as_consultation(
        pkg,
        case_title="Chest CT review",
        clinical_question="Rule out PE?",
        from_user={"provider": "google", "email": "a@x.com", "name": "Dr A"},
        assignee={"email": "b@x.com", "name": "Dr B"},
        study_uids=["1.2.3"],
        priority="urgent",
    )
    assert (pkg / ENVELOPE_FILENAME).exists()
    assert env.consultation_id
    assert env.status == ConsultationStatus.PENDING.value
    # Integrity covers the payload but never the envelope itself.
    assert ENVELOPE_FILENAME not in env.integrity["files_sha256"]
    assert "manifest.json" in env.integrity["files_sha256"]
    assert "patients/dicom/1.2.3/img1.dcm" in env.integrity["files_sha256"]

    read = env_mod.read_envelope(pkg)
    assert read is not None
    assert read.case_title == "Chest CT review"
    assert read.clinical_question == "Rule out PE?"
    assert read.assignee["email"] == "b@x.com"
    assert read.priority == "urgent"
    assert read.study_uids == ["1.2.3"]


def test_integrity_ok_then_detects_tamper_and_additions(tmp_path):
    pkg = _make_package(tmp_path)
    service.seal_package_as_consultation(
        pkg, case_title="t", clinical_question="q",
        from_user={"email": "a@x.com"}, study_uids=["1.2.3"],
    )
    assert env_mod.verify_integrity(pkg)["ok"] is True

    # Tamper an existing DICOM file.
    (pkg / "patients" / "dicom" / "1.2.3" / "img1.dcm").write_bytes(b"TAMPERED")
    rep = env_mod.verify_integrity(pkg)
    assert rep["ok"] is False
    assert "patients/dicom/1.2.3/img1.dcm" in rep["mismatched"]

    # Add a stray file -> reported as added.
    (pkg / "patients" / "dicom" / "1.2.3" / "extra.dcm").write_bytes(b"X")
    rep2 = env_mod.verify_integrity(pkg)
    assert rep2["ok"] is False
    assert "patients/dicom/1.2.3/extra.dcm" in rep2["added"]

    # Remove a sealed file -> reported as missing.
    (pkg / "patients" / "dicom" / "1.2.3" / "img2.dcm").unlink()
    rep3 = env_mod.verify_integrity(pkg)
    assert "patients/dicom/1.2.3/img2.dcm" in rep3["missing"]


def test_record_response_bumps_version_and_reseals(tmp_path):
    pkg = _make_package(tmp_path)
    service.seal_package_as_consultation(
        pkg, case_title="t", clinical_question="q",
        from_user={"email": "a@x.com"}, assignee={"email": "b@x.com"}, study_uids=["1.2.3"],
    )
    # Dr B adds a report file, then records a response referencing it.
    (pkg / "patients" / "attachments").mkdir(parents=True, exist_ok=True)
    (pkg / "patients" / "attachments" / "report_b.html").write_text("<p>opinion</p>", encoding="utf-8")

    env2 = service.record_response(
        pkg,
        from_user={"email": "b@x.com", "name": "Dr B"},
        text="Findings consistent with ...",
        report_ref="patients/attachments/report_b.html",
    )
    assert env2.package_version == 2
    assert env2.status == ConsultationStatus.ANSWERED.value
    assert len(env2.responses) == 1
    assert env2.responses[0]["from_user"]["email"] == "b@x.com"
    # Re-seal re-hashed the package, so the new report is covered and integrity holds.
    assert "patients/attachments/report_b.html" in env2.integrity["files_sha256"]
    assert env_mod.verify_integrity(pkg)["ok"] is True


def test_non_consultation_package_is_backward_compatible(tmp_path):
    pkg = _make_package(tmp_path)  # no envelope written
    assert env_mod.read_envelope(pkg) is None
    info = service.open_consultation_package(pkg)
    assert info["is_consultation"] is False
    assert info["envelope"] is None


def test_open_consultation_package_verifies(tmp_path):
    pkg = _make_package(tmp_path)
    service.seal_package_as_consultation(
        pkg, case_title="t", clinical_question="q",
        from_user={"email": "a@x.com"}, study_uids=["1.2.3"],
    )
    info = service.open_consultation_package(pkg, verify=True)
    assert info["is_consultation"] is True
    assert info["envelope"].case_title == "t"
    assert info["integrity"]["ok"] is True
