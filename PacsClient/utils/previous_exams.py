"""Previous-Exams data contract + server-response parsers (pure, stdlib-only).

Feature: a patient opened in the workstation may be the SAME real person as
other patients imaged before at this center under DIFFERENT PatientIDs. The
server links them by National ID / RIS reception and exposes:

  * ``GetPatientReceptionHistory`` — cross-PatientID history (the National-ID
    path): ``nationalCode`` + ``history[]`` of prior receptions, each with its
    own (possibly different) PatientID and ``studies[]``.
  * ``GetPatientStatus`` — the full past-study list for ONE PatientID.

This module turns those two response shapes into one normalized, immutable
``PreviousExamSet`` the UI and the unified study pipeline consume.

CLINICAL SAFETY — read before extending:
  This layer is METADATA ONLY. It never touches pixel data, DICOM geometry,
  downloads, Qt, or the network. Keep it pure (stdlib only) so it stays
  unit-testable in isolation. Each ``PreviousExamStudy`` PRESERVES its own
  ``study_uid`` and ``patient_id`` — previous exams are linked to the current
  real patient for display/comparison but must never be silently re-attributed
  to the current PatientID (cross-patient isolation). The set of previous-exam
  ``study_uid`` values is the "sanctioned" allow-list the isolation guard
  (``patient_study_set.merge_study_uids``) consults so these — and ONLY these,
  and only on the explicit user action of selecting a previous exam — may be
  admitted into the current patient's grouped viewer.

Server doc: ``patient-past-studies-api.md`` (§1.2 GetPatientStatus,
§1.3 GetPatientReceptionHistory).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional


def _clean(value) -> str:
    return str(value if value is not None else "").strip()


def _to_int(value) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return 0


def format_study_date(yyyymmdd) -> str:
    """``"20250601"`` -> ``"2025/06/01"``. Tolerant: returns the cleaned input
    unchanged when it is not an 8-digit date (server doc display suggestion)."""
    s = _clean(yyyymmdd)
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}/{s[4:6]}/{s[6:8]}"
    return s


def _as_iter(value) -> Iterable:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        return value
    return (value,)


def normalize_modalities(value, *, drop_sr: bool = False) -> tuple:
    """Normalize a modality field to an ordered, de-duplicated tuple.

    Accepts a list (``["MR", "CT"]``), a DICOM multi-value string
    (``"MR\\CT"``), or a comma/space-separated string. ``drop_sr`` removes the
    ``SR`` (structured-report) pseudo-modality (server's patient-level
    ``modalities`` list excludes it; per-study lists keep it by default)."""
    out: List[str] = []
    seen = set()
    for item in _as_iter(value):
        text = _clean(item)
        if not text:
            continue
        # split DICOM multi-value / delimited strings
        parts = [p for chunk in text.replace(",", "\\").split("\\")
                 for p in chunk.split()]
        for p in (parts or [text]):
            m = p.strip().upper()
            if not m:
                continue
            if drop_sr and m == "SR":
                continue
            if m not in seen:
                seen.add(m)
                out.append(m)
    return tuple(out)


@dataclass(frozen=True)
class PreviousExamStudy:
    """One prior study/exam of the same real person. ``study_uid`` and
    ``patient_id`` are PRESERVED exactly as the server reported them — a previous
    exam keeps its own identity even though it is displayed alongside the
    current patient."""

    study_uid: str
    patient_id: str = ""           # the exam's OWN PatientID (may differ from current)
    patient_name: str = ""
    study_date: str = ""           # YYYYMMDD
    study_time: str = ""           # HHMMSS
    study_description: str = ""
    modalities: tuple = ()
    number_of_series: int = 0
    number_of_instances: int = 0
    number_of_attachments: int = 0
    report_status: str = ""
    reception_id: str = ""
    national_code: str = ""
    is_current: bool = False       # True = the study already open (excluded from "previous")

    @property
    def display_date(self) -> str:
        return format_study_date(self.study_date)

    @property
    def modality_label(self) -> str:
        return "/".join(self.modalities) if self.modalities else ""

    @property
    def sort_key(self) -> tuple:
        # newest first: date desc, then time desc; missing dates sort last
        d = self.study_date if (len(self.study_date) == 8 and self.study_date.isdigit()) else ""
        return (d, self.study_time or "")


@dataclass(frozen=True)
class PreviousExamSet:
    """Immutable, normalized result the UI + unified pipeline consume."""

    current_patient_id: str
    current_study_uid: str = ""
    national_code: str = ""
    studies: tuple = ()            # tuple[PreviousExamStudy, ...] newest-first
    source: str = "none"           # reception_history | patient_status | merged | none
    warnings: tuple = ()

    @property
    def previous_studies(self) -> tuple:
        """Exams OTHER than the currently-open one (what the list shows)."""
        return tuple(s for s in self.studies if not s.is_current)

    @property
    def has_previous(self) -> bool:
        return len(self.previous_studies) > 0

    @property
    def count(self) -> int:
        return len(self.previous_studies)

    def study(self, study_uid: str) -> Optional[PreviousExamStudy]:
        target = _clean(study_uid)
        for s in self.studies:
            if s.study_uid == target:
                return s
        return None


def parse_patient_status(
    data,
    *,
    current_patient_id: str = "",
    current_study_uid: str = "",
) -> List[PreviousExamStudy]:
    """Parse a ``GetPatientStatus`` ``data`` payload -> list[PreviousExamStudy].

    All studies belong to ONE PatientID (``data['patient_id']`` or the caller's
    ``current_patient_id``). Tolerant of missing/partial fields."""
    info = data or {}
    pid = _clean(info.get("patient_id")) or _clean(current_patient_id)
    name = _clean(info.get("patient_name"))
    cur_uid = _clean(current_study_uid)

    out: List[PreviousExamStudy] = []
    for s in _as_iter(info.get("studies")):
        if not isinstance(s, dict):
            continue
        uid = _clean(s.get("study_uid") or s.get("StudyInstanceUID"))
        if not uid:
            continue
        out.append(PreviousExamStudy(
            study_uid=uid,
            patient_id=pid,
            patient_name=name,
            study_date=_clean(s.get("study_date") or s.get("StudyDate")),
            study_time=_clean(s.get("study_time") or s.get("StudyTime")),
            study_description=_clean(s.get("study_description") or s.get("StudyDescription")),
            modalities=normalize_modalities(
                s.get("modalities") or s.get("ModalitiesInStudy") or s.get("modality")),
            number_of_series=_to_int(s.get("number_of_series") or s.get("NumberOfSeries")),
            number_of_instances=_to_int(s.get("number_of_instances") or s.get("NumberOfInstances")),
            number_of_attachments=_to_int(s.get("number_of_attachments")),
            report_status=_clean(s.get("report_status") or s.get("reportStatus")) or "pending",
            reception_id=_clean(s.get("reception_id")),
            national_code="",
            is_current=bool(cur_uid) and uid == cur_uid,
        ))
    return out


def parse_reception_history(
    data,
    *,
    current_patient_id: str = "",
    current_study_uid: str = "",
) -> List[PreviousExamStudy]:
    """Parse a ``GetPatientReceptionHistory`` ``data`` payload -> list[PreviousExamStudy].

    Flattens ``history[].studies[]``; each reception may carry a DIFFERENT
    PatientID (the ``receptionId`` is used as the per-exam id surrogate, as in
    RIS ``patient_id`` aliases ``reception_id``). The reception ``isCurrent``
    flag (or a study_uid match) marks the open exam. Tolerant of partial data."""
    info = data or {}
    national = _clean(info.get("nationalCode") or info.get("national_code"))
    default_name = _clean(info.get("patientName") or info.get("patient_name"))
    cur_uid = _clean(current_study_uid)

    out: List[PreviousExamStudy] = []
    for rec in _as_iter(info.get("history")):
        if not isinstance(rec, dict):
            continue
        rec_id = _clean(rec.get("receptionId") or rec.get("reception_id")
                        or rec.get("patientId") or rec.get("patient_id"))
        rec_is_current = bool(rec.get("isCurrent") or rec.get("is_current"))
        rec_modality = rec.get("modality")
        rec_report = _clean(rec.get("reportStatus") or rec.get("report_status"))
        for s in _as_iter(rec.get("studies")):
            if not isinstance(s, dict):
                continue
            uid = _clean(s.get("StudyInstanceUID") or s.get("study_uid"))
            if not uid:
                continue
            out.append(PreviousExamStudy(
                study_uid=uid,
                patient_id=rec_id or _clean(current_patient_id),
                patient_name=default_name,
                study_date=_clean(s.get("StudyDate") or s.get("study_date")),
                study_time=_clean(s.get("StudyTime") or s.get("study_time")),
                study_description=_clean(s.get("StudyDescription") or s.get("study_description")),
                modalities=normalize_modalities(
                    s.get("ModalitiesInStudy") or s.get("modalities") or rec_modality),
                number_of_series=_to_int(s.get("NumberOfSeries") or s.get("number_of_series")),
                number_of_instances=_to_int(s.get("NumberOfInstances") or s.get("number_of_instances")),
                number_of_attachments=_to_int(s.get("number_of_attachments")),
                report_status=(_clean(s.get("reportStatus") or s.get("report_status"))
                               or rec_report or "pending"),
                reception_id=rec_id,
                national_code=national,
                is_current=rec_is_current or (bool(cur_uid) and uid == cur_uid),
            ))
    return out


def _merge_study_records(
    primary: PreviousExamStudy,
    secondary: PreviousExamStudy,
) -> PreviousExamStudy:
    """Combine two records for the same ``study_uid`` — ``primary`` wins on
    non-empty fields; ``is_current`` is OR-ed; counts/national take the larger /
    present value. Keeps the contract immutable."""
    def pick(a, b):
        return a if _clean(a) else b
    return PreviousExamStudy(
        study_uid=primary.study_uid,
        patient_id=pick(primary.patient_id, secondary.patient_id),
        patient_name=pick(primary.patient_name, secondary.patient_name),
        study_date=pick(primary.study_date, secondary.study_date),
        study_time=pick(primary.study_time, secondary.study_time),
        study_description=pick(primary.study_description, secondary.study_description),
        modalities=primary.modalities or secondary.modalities,
        number_of_series=max(primary.number_of_series, secondary.number_of_series),
        number_of_instances=max(primary.number_of_instances, secondary.number_of_instances),
        number_of_attachments=max(primary.number_of_attachments, secondary.number_of_attachments),
        report_status=pick(primary.report_status, secondary.report_status),
        reception_id=pick(primary.reception_id, secondary.reception_id),
        national_code=pick(primary.national_code, secondary.national_code),
        is_current=primary.is_current or secondary.is_current,
    )


def build_previous_exam_set(
    *,
    current_patient_id: str,
    current_study_uid: str = "",
    reception_data=None,
    status_data=None,
) -> PreviousExamSet:
    """Build the normalized, de-duplicated, newest-first ``PreviousExamSet`` from
    either/both server payloads (the chained ReceptionHistory + PatientStatus
    strategy). Reception-history records take precedence on conflict because they
    carry the cross-PatientID / National-ID linkage.

    De-dup is by ``study_uid``. Returns an empty set (``has_previous=False``)
    when neither payload yields studies, so a server without these endpoints
    leaves the feature inert."""
    cur_pid = _clean(current_patient_id)
    cur_uid = _clean(current_study_uid)

    recs = parse_reception_history(
        reception_data, current_patient_id=cur_pid, current_study_uid=cur_uid) if reception_data else []
    stats = parse_patient_status(
        status_data, current_patient_id=cur_pid, current_study_uid=cur_uid) if status_data else []

    by_uid: dict = {}
    order: List[str] = []
    # reception history first (authoritative for identity linkage)
    for rec in recs:
        if rec.study_uid in by_uid:
            by_uid[rec.study_uid] = _merge_study_records(by_uid[rec.study_uid], rec)
        else:
            by_uid[rec.study_uid] = rec
            order.append(rec.study_uid)
    for st in stats:
        if st.study_uid in by_uid:
            # existing record (from reception history) is primary
            by_uid[st.study_uid] = _merge_study_records(by_uid[st.study_uid], st)
        else:
            by_uid[st.study_uid] = st
            order.append(st.study_uid)

    studies = [by_uid[u] for u in order]
    studies.sort(key=lambda s: s.sort_key, reverse=True)

    national = ""
    if isinstance(reception_data, dict):
        national = _clean(reception_data.get("nationalCode") or reception_data.get("national_code"))

    if recs and stats:
        source = "merged"
    elif recs:
        source = "reception_history"
    elif stats:
        source = "patient_status"
    else:
        source = "none"

    return PreviousExamSet(
        current_patient_id=cur_pid,
        current_study_uid=cur_uid,
        national_code=national,
        studies=tuple(studies),
        source=source,
    )


def sanctioned_study_uids(exam_set: Optional[PreviousExamSet]) -> frozenset:
    """The allow-list of ``study_uid`` values that may be admitted into the
    current patient's grouped viewer despite belonging to a different PatientID.

    This is exactly the set of previous exams the server linked to the same real
    person (by National ID / reception). ``patient_study_set.merge_study_uids``
    consults it so the cross-patient isolation guard admits these — and only
    these — when the user explicitly selects a previous exam."""
    if not exam_set:
        return frozenset()
    return frozenset(_clean(s.study_uid) for s in exam_set.studies if _clean(s.study_uid))
