"""Unit tests for the Previous-Exams data contract + parsers and the
cross-identity sanctioned override in the study-set isolation authority.

Pure-Python (no Qt / no network) so it runs in any environment.
"""
import importlib.util
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _load(mod_name, rel_path):
    """Load a module directly from file so the test does not import the heavy
    PacsClient package __init__ (Qt etc.)."""
    path = os.path.join(_REPO, *rel_path.split("/"))
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec: with ``from __future__ import annotations`` the
    # dataclass decorator resolves annotations via sys.modules[cls.__module__].
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


pe = _load("previous_exams_mod", "PacsClient/utils/previous_exams.py")
pss = _load("patient_study_set_mod", "PacsClient/utils/patient_study_set.py")


# ── server response fixtures (from patient-past-studies-api.md) ───────────────

PATIENT_STATUS = {
    "patient_id": "12345",
    "patient_name": "ALI REZA",
    "total_studies": 2,
    "first_study_date": "20240320",
    "latest_study_date": "20250601",
    "studies": [
        {
            "study_uid": "1.2.840.UID.A",
            "study_date": "20250601",
            "study_description": "BRAIN MRI",
            "modalities": ["MR"],
            "number_of_series": 5,
            "number_of_instances": 120,
            "number_of_attachments": 0,
            "report_status": "pending",
        },
        {
            "study_uid": "1.2.840.UID.B",
            "study_date": "20240320",
            "study_description": "CHEST CT",
            "modalities": ["CT"],
            "number_of_series": 2,
            "number_of_instances": 350,
            "number_of_attachments": 1,
            "report_status": "final",
        },
    ],
}

RECEPTION_HISTORY = {
    "patientId": "12345",
    "nationalCode": "0012345678",
    "currentReceptionId": 999,
    "patientName": "ALI REZA",
    "history": [
        {
            "receptionId": 999,
            "date": "20250601",
            "modality": "MR",
            "reportStatus": "pending",
            "isCurrent": True,
            "studies": [
                {
                    "StudyInstanceUID": "1.2.840.UID.A",
                    "StudyDate": "20250601",
                    "StudyTime": "143022",
                    "StudyDescription": "BRAIN MRI",
                    "reportStatus": "pending",
                    "ModalitiesInStudy": ["MR"],
                }
            ],
        },
        {
            "receptionId": 777,           # DIFFERENT PatientID / reception
            "date": "20240320",
            "modality": "CT",
            "reportStatus": "final",
            "isCurrent": False,
            "studies": [
                {
                    "StudyInstanceUID": "1.2.840.UID.B",
                    "StudyDate": "20240320",
                    "StudyTime": "090000",
                    "StudyDescription": "CHEST CT",
                    "reportStatus": "final",
                    "ModalitiesInStudy": ["CT"],
                }
            ],
        },
    ],
}


# ── format / normalize helpers ───────────────────────────────────────────────

def test_format_study_date():
    assert pe.format_study_date("20250601") == "2025/06/01"
    assert pe.format_study_date("") == ""
    assert pe.format_study_date("bad") == "bad"


def test_normalize_modalities_variants():
    assert pe.normalize_modalities(["MR", "MR", "CT"]) == ("MR", "CT")
    assert pe.normalize_modalities("MR\\CT") == ("MR", "CT")
    assert pe.normalize_modalities("mr, ct") == ("MR", "CT")
    assert pe.normalize_modalities(["MR", "SR"], drop_sr=True) == ("MR",)
    assert pe.normalize_modalities(None) == ()


# ── parsers ──────────────────────────────────────────────────────────────────

def test_parse_patient_status():
    rows = pe.parse_patient_status(
        PATIENT_STATUS, current_patient_id="12345", current_study_uid="1.2.840.UID.A")
    assert len(rows) == 2
    a = next(r for r in rows if r.study_uid == "1.2.840.UID.A")
    b = next(r for r in rows if r.study_uid == "1.2.840.UID.B")
    assert a.is_current is True            # the open study
    assert b.is_current is False
    assert b.patient_id == "12345"
    assert b.modalities == ("CT",)
    assert b.display_date == "2024/03/20"
    assert b.number_of_instances == 350


def test_parse_reception_history_cross_patient_ids():
    rows = pe.parse_reception_history(
        RECEPTION_HISTORY, current_patient_id="12345", current_study_uid="1.2.840.UID.A")
    assert len(rows) == 2
    b = next(r for r in rows if r.study_uid == "1.2.840.UID.B")
    assert b.patient_id == "777"           # preserves the DIFFERENT reception id
    assert b.reception_id == "777"
    assert b.national_code == "0012345678"
    assert b.is_current is False
    a = next(r for r in rows if r.study_uid == "1.2.840.UID.A")
    assert a.is_current is True            # reception isCurrent


# ── build set: merge, dedup, sort, current exclusion ─────────────────────────

def test_build_set_merged_dedup_sorted():
    s = pe.build_previous_exam_set(
        current_patient_id="12345",
        current_study_uid="1.2.840.UID.A",
        reception_data=RECEPTION_HISTORY,
        status_data=PATIENT_STATUS,
    )
    assert s.source == "merged"
    assert s.national_code == "0012345678"
    # 2 unique studies (deduped across both payloads)
    assert len(s.studies) == 2
    # newest first
    assert s.studies[0].study_uid == "1.2.840.UID.A"
    assert s.studies[1].study_uid == "1.2.840.UID.B"
    # current excluded from "previous"
    assert s.has_previous is True
    assert s.count == 1
    assert s.previous_studies[0].study_uid == "1.2.840.UID.B"
    # reception-history identity (own patient id) survives the merge
    assert s.previous_studies[0].patient_id == "777"


def test_build_set_empty_is_inert():
    s = pe.build_previous_exam_set(current_patient_id="12345")
    assert s.has_previous is False
    assert s.count == 0
    assert s.source == "none"


def test_build_set_status_only():
    s = pe.build_previous_exam_set(
        current_patient_id="12345", current_study_uid="1.2.840.UID.A",
        status_data=PATIENT_STATUS)
    assert s.source == "patient_status"
    assert s.has_previous is True
    assert s.count == 1


def test_sanctioned_study_uids():
    s = pe.build_previous_exam_set(
        current_patient_id="12345", current_study_uid="1.2.840.UID.A",
        reception_data=RECEPTION_HISTORY)
    uids = pe.sanctioned_study_uids(s)
    assert "1.2.840.UID.A" in uids and "1.2.840.UID.B" in uids
    assert pe.sanctioned_study_uids(None) == frozenset()


# ── sanctioned override in merge_study_uids ──────────────────────────────────

def _owner_of(uid):
    # UID.B belongs to a DIFFERENT patient (777); UID.A belongs to current
    return {"1.2.840.UID.A": "12345", "1.2.840.UID.B": "777"}.get(uid)


def test_merge_drops_foreign_without_sanction():
    kept, dropped = pss.merge_study_uids(
        [["1.2.840.UID.A", "1.2.840.UID.B"]],
        selected_study_uid="1.2.840.UID.A",
        owner_of=_owner_of, patient_id="12345")
    assert kept == ["1.2.840.UID.A"]
    assert dropped == ["1.2.840.UID.B"]


def test_merge_keeps_foreign_when_sanctioned():
    kept, dropped = pss.merge_study_uids(
        [["1.2.840.UID.A", "1.2.840.UID.B"]],
        selected_study_uid="1.2.840.UID.A",
        owner_of=_owner_of, patient_id="12345",
        sanctioned_uids={"1.2.840.UID.B"})
    assert kept == ["1.2.840.UID.A", "1.2.840.UID.B"]
    assert dropped == []


def test_merge_unsanctioned_foreign_still_dropped():
    # Sanctioning B must not admit an unrelated foreign C.
    kept, dropped = pss.merge_study_uids(
        [["1.2.840.UID.A", "1.2.840.UID.B", "1.2.840.UID.C"]],
        selected_study_uid="1.2.840.UID.A",
        owner_of=lambda u: {"1.2.840.UID.A": "12345", "1.2.840.UID.B": "777",
                            "1.2.840.UID.C": "555"}.get(u),
        patient_id="12345",
        sanctioned_uids={"1.2.840.UID.B"})
    assert kept == ["1.2.840.UID.A", "1.2.840.UID.B"]
    assert dropped == ["1.2.840.UID.C"]


def test_merge_default_empty_sanction_is_byte_identical():
    # No sanctioned arg => unchanged legacy behavior.
    kept, dropped = pss.merge_study_uids(
        [["1.2.840.UID.A", "1.2.840.UID.B"]],
        selected_study_uid="1.2.840.UID.A",
        owner_of=_owner_of, patient_id="12345")
    kept2, dropped2 = pss.merge_study_uids(
        [["1.2.840.UID.A", "1.2.840.UID.B"]],
        selected_study_uid="1.2.840.UID.A",
        owner_of=_owner_of, patient_id="12345",
        sanctioned_uids=None)
    assert kept == kept2 == ["1.2.840.UID.A"]
    assert dropped == dropped2 == ["1.2.840.UID.B"]


def test_resolve_study_uids_threads_sanctioned():
    kept, dropped = pss.resolve_study_uids(
        table_uids=["1.2.840.UID.A", "1.2.840.UID.B"],
        selected_study_uid="1.2.840.UID.A",
        owner_of=_owner_of, patient_id="12345",
        sanctioned_uids={"1.2.840.UID.B"})
    assert "1.2.840.UID.B" in kept
    assert dropped == []
