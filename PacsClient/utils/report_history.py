"""Normalize a reception-server patient record into report dicts for display.

The Medical Report Editor's "Previous Exams" feature lets a user pick a prior
Patient ID and view that record's reports READ-ONLY. The reception server
exposes a record via ``GET /api/pacs/patients/{id}`` (the same endpoint the
reception tab already uses for the current patient), whose body carries the
report under ``report`` or ``imagingWorkflow.report``. This module turns that
raw record into the report-dict shape ``ReceptionReportsViewer`` renders, so a
LIVE server report can be shown in the existing read-only viewer without
writing anything to the local database.

Pure stdlib — no Qt, no network, no DB. Keep it that way so it is unit-testable
in isolation and cannot couple the UI to the transport. NEVER raises: a
malformed record yields ``[]`` and the caller falls back to the local
reception-reports DB.

SCOPE: read-only display shaping. It does not persist, edit, or send anything,
and it never touches the ACTIVE report being edited.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List


def _clean(value) -> str:
    return str(value if value is not None else "").strip()


def _first(*values) -> str:
    for v in values:
        c = _clean(v)
        if c:
            return c
    return ""


def study_datetime_to_epoch(study_date, study_time="") -> int:
    """A date(+time)-ish value -> unix epoch seconds (UTC). 0 when unusable.

    Accepts a plain DICOM ``"20250601"`` (optionally with a separate
    ``"143000"`` time) AND an ISO-ish string like ``"2026-07-21T13:48:15"`` —
    separators are stripped and the leading 8 digits are the date, the next 6
    (or the explicit ``study_time``) the time. The viewer sorts reports by
    ``created_at`` (epoch, desc) and prints a timestamp, so a stable numeric key
    keeps previous reports newest-first. Tolerant: any parse failure returns 0."""
    digits = "".join(ch for ch in _clean(study_date) if ch.isdigit())
    if len(digits) < 8:
        return 0
    d = digits[0:8]
    t_src = _clean(study_time) or digits[8:14]
    t = "".join(ch for ch in t_src if ch.isdigit())[:6].ljust(6, "0")
    try:
        dt = datetime(
            int(d[0:4]), int(d[4:6]), int(d[6:8]),
            int(t[0:2]), int(t[2:4]), int(t[4:6]),
            tzinfo=timezone.utc,
        )
        return int(dt.timestamp())
    except (ValueError, OverflowError):
        return 0


def _person_name(value) -> str:
    """Coerce a physician field (string OR an object like
    ``{"name": "..."}``) to a display name."""
    if isinstance(value, dict):
        return _first(
            value.get("name"), value.get("fullName"), value.get("displayName"),
            value.get("fullname"), value.get("username"), value.get("title"),
        )
    return _clean(value)


def _modality_text(value) -> str:
    """Coerce a modality field to a short label. The reception server sends
    modality as an OBJECT, e.g.
    ``{"_id":"1","Modality":"CT","FullName":"CT Scan","PerFullName":"سی تی اسکن"}``
    — a bare ``str()`` of that leaked ``{'_id': '1'...}`` into the overlay label.
    Prefer the short code, then the full names."""
    if isinstance(value, dict):
        return _first(
            value.get("Modality"), value.get("modality"),
            value.get("FullName"), value.get("PerFullName"), value.get("name"),
        )
    return _clean(value)


def _unwrap_record(record):
    """Descend into the reception API's ``{"success", "data"}`` envelope.

    ``GET /api/pacs/patients/{id}`` returns the patient/reception record wrapped
    as ``{"success": true, "data": {...}}`` (verified against the live server) —
    the report lives at ``data.report``, NOT at the top level. Unwrap so the
    normalizer reads the real record whether it is handed the raw response or an
    already-unwrapped record. Handles ``data`` being a single-element list."""
    if not isinstance(record, dict):
        return {}
    if "report" not in record and "imagingWorkflow" not in record and "data" in record:
        inner = record.get("data")
        if isinstance(inner, list):
            inner = inner[0] if inner else {}
        if isinstance(inner, dict):
            return inner
    return record


def _extract_report_block(record: dict) -> dict:
    """The report sub-object, from ``report`` or ``imagingWorkflow.report``."""
    if not isinstance(record, dict):
        return {}
    rep = record.get("report")
    if isinstance(rep, dict) and rep:
        return rep
    iw = record.get("imagingWorkflow")
    if isinstance(iw, dict):
        rep = iw.get("report")
        if isinstance(rep, dict):
            return rep
    return {}


def normalize_reception_record_reports(record, *, patient_id: str = "") -> List[dict]:
    """Turn a ``GET /api/pacs/patients/{id}`` record into viewer report dicts.

    Returns a list (0 or 1 server reports for a single record) of dicts with the
    exact keys ``ReceptionReportsViewer`` consumes: ``id``, ``patient_id``,
    ``study_uid``, ``created_at`` (epoch int), ``status``, ``sender_info``,
    ``html_content``, ``reporting_physician_name``, plus a ``source`` tag. A
    record with no report HTML yields ``[]`` (caller falls back to local DB).
    Never raises."""
    try:
        rec = _unwrap_record(record or {})
        if not isinstance(rec, dict):
            return []
        report = _extract_report_block(rec)

        html = _first(
            report.get("content"), report.get("findings"),
            report.get("html"), report.get("html_content"),
            rec.get("report_content"),
        )
        if not html:
            return []

        pid = _first(
            patient_id, rec.get("receptionId"), rec.get("ReceptionID"),
            rec.get("patientId"), rec.get("patient_id"), rec.get("_id"),
        )
        study_uid = _first(
            rec.get("studyUID"), rec.get("study_uid"),
            rec.get("StudyInstanceUID"), report.get("study_uid"),
        )
        study_date = _first(
            rec.get("studyDate"), rec.get("StudyDate"), rec.get("study_date"),
            report.get("study_date"),
            report.get("reportDate"), report.get("date"),
            rec.get("date"), rec.get("createdAt"), rec.get("updatedAt"),
        )
        study_time = _first(rec.get("studyTime"), rec.get("StudyTime"),
                            rec.get("study_time"), rec.get("time"))
        modality = _first(
            _modality_text(rec.get("modality")), _modality_text(rec.get("Modality")),
            _modality_text(report.get("modality")),
        )
        physician = _first(
            _person_name(report.get("radiologist")),
            report.get("reportingPhysicianName"), report.get("reporting_physician_name"),
            report.get("reportingPhysician"), report.get("reporting_physician"),
            _person_name(rec.get("radiologist")),
            _person_name(rec.get("referrerPhysician")),
            _person_name(rec.get("reportingPhysician")),
        )
        status = _first(report.get("status"), rec.get("reportStatus"), rec.get("report_status")) or "completed"
        report_id = _first(
            report.get("_id"), report.get("id"), rec.get("receptionId"), rec.get("_id"),
        ) or pid

        sender_bits = []
        if modality:
            sender_bits.append(f"Modality: {modality}")
        sender_bits.append("Previous exam (read-only)")

        return [{
            "id": report_id,
            "patient_id": pid,
            "study_uid": study_uid,
            "created_at": study_datetime_to_epoch(study_date, study_time),
            "status": status,
            "sender_info": " | ".join(sender_bits),
            "html_content": html,
            "reporting_physician_name": physician,
            "source": "server",
        }]
    except Exception:
        return []
