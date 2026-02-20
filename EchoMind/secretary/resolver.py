from __future__ import annotations

import re
from typing import Any


def normalize_code(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", "", str(value).strip().lower())


def compact_patient_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "patient_id": str(row.get("patient_id") or "").strip(),
        "patient_name": str(row.get("patient_name") or "").strip(),
        "study_uid": str(row.get("study_uid") or "").strip(),
        "modality": str(row.get("modality") or "").strip(),
        "date": str(row.get("date") or row.get("study_date") or "").strip(),
        "time": str(row.get("time") or row.get("study_time") or "").strip(),
        "description": str(row.get("description") or "").strip(),
        "report_status": str(row.get("report_status") or "pending").strip() or "pending",
    }


def resolve_patient_by_code(rows: list[dict[str, Any]], code: str) -> dict[str, Any]:
    code_n = normalize_code(code)
    if not code_n:
        return {"status": "missing_code", "matches": []}

    exact_patient: list[dict[str, Any]] = []
    exact_study: list[dict[str, Any]] = []
    contains: list[dict[str, Any]] = []

    for row in rows:
        item = compact_patient_row(row)
        pid = normalize_code(item.get("patient_id"))
        suid = normalize_code(item.get("study_uid"))
        if code_n and pid == code_n:
            exact_patient.append(item)
            continue
        if code_n and suid == code_n:
            exact_study.append(item)
            continue
        if code_n and (code_n in pid or code_n in suid):
            contains.append(item)

    matches = exact_patient or exact_study or contains
    if not matches:
        return {"status": "not_found", "matches": []}
    if len(matches) == 1:
        return {"status": "resolved", "matches": matches}
    return {"status": "ambiguous", "matches": matches}

