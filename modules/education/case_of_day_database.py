from __future__ import annotations

import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from PacsClient.utils.config import CASE_OF_DAY_STORAGE_PATH
from PacsClient.utils.database import get_db_connection


@dataclass(frozen=True)
class CaseOfDayEntry:
    case_pk: int
    saved_by: str
    modality: str
    body_part: str
    diagnosis: str
    anatomical_classification: str
    protocol_details: str
    description: str
    differential_diagnosis: str
    dicom_folder_path: str
    original_source_path: str
    source_type: str
    patient_id: str
    study_uid: str
    created_at: str
    updated_at: str


def list_body_parts() -> List[str]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT body_part FROM case_of_day_body_parts ORDER BY body_part ASC")
        return [row[0] for row in cur.fetchall()]


def add_body_part(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        raise ValueError("Body part name is required")
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO case_of_day_body_parts (body_part) VALUES (?)", (value,))
    return value


def _row_to_entry(row: sqlite3.Row) -> CaseOfDayEntry:
    return CaseOfDayEntry(
        case_pk=int(row["case_pk"]),
        saved_by=str(row["saved_by"] or ""),
        modality=str(row["modality"] or ""),
        body_part=str(row["body_part"] or ""),
        diagnosis=str(row["diagnosis"] or ""),
        anatomical_classification=str(row["anatomical_classification"] or ""),
        protocol_details=str(row["protocol_details"] or ""),
        description=str(row["description"] or ""),
        differential_diagnosis=str(row["differential_diagnosis"] or ""),
        dicom_folder_path=str(row["dicom_folder_path"] or ""),
        original_source_path=str(row["original_source_path"] or ""),
        source_type=str(row["source_type"] or "manual"),
        patient_id=str(row["patient_id"] or ""),
        study_uid=str(row["study_uid"] or ""),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


def get_all_cases() -> List[CaseOfDayEntry]:
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM case_of_day_entries ORDER BY updated_at DESC, case_pk DESC")
        return [_row_to_entry(row) for row in cur.fetchall()]


def get_case(case_pk: int) -> Optional[CaseOfDayEntry]:
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM case_of_day_entries WHERE case_pk = ?", (int(case_pk),))
        row = cur.fetchone()
        return _row_to_entry(row) if row else None


def search_cases(query: str = "", modality: str = None, body_part: str = None) -> List[CaseOfDayEntry]:
    rows = get_all_cases()
    q = str(query or "").strip().lower()
    allowed_modality = str(modality).strip() if modality else None
    allowed_body = str(body_part).strip() if body_part else None

    filtered: List[CaseOfDayEntry] = []
    for entry in rows:
        if allowed_modality and entry.modality != allowed_modality:
            continue
        if allowed_body and entry.body_part != allowed_body:
            continue
        if q:
            blob = " ".join(
                [
                    entry.saved_by,
                    entry.modality,
                    entry.body_part,
                    entry.diagnosis,
                    entry.anatomical_classification,
                    entry.protocol_details,
                    entry.description,
                    entry.differential_diagnosis,
                    entry.patient_id,
                    entry.study_uid,
                ]
            ).lower()
            if q not in blob:
                continue
        filtered.append(entry)
    return filtered


def insert_case(
    *,
    saved_by: str,
    modality: str,
    body_part: str,
    diagnosis: str,
    dicom_folder_path: str,
    anatomical_classification: str = "",
    protocol_details: str = "",
    description: str = "",
    differential_diagnosis: str = "",
    original_source_path: str = "",
    source_type: str = "manual",
    patient_id: str = "",
    study_uid: str = "",
) -> int:
    saved_by = str(saved_by or "").strip()
    modality = str(modality or "").strip()
    body_part = str(body_part or "").strip()
    diagnosis = str(diagnosis or "").strip()
    dicom_folder_path = str(dicom_folder_path or "").strip()

    if not saved_by:
        raise ValueError("Saved By is required")
    if not modality:
        raise ValueError("Modality is required")
    if not body_part:
        raise ValueError("Body Part is required")
    if not diagnosis:
        raise ValueError("Diagnosis is required")
    if not dicom_folder_path:
        raise ValueError("DICOM folder path is required")

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO case_of_day_entries (
                saved_by, modality, body_part, diagnosis,
                anatomical_classification, protocol_details, description, differential_diagnosis,
                dicom_folder_path, original_source_path, source_type, patient_id, study_uid, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                saved_by,
                modality,
                body_part,
                diagnosis,
                str(anatomical_classification or ""),
                str(protocol_details or ""),
                str(description or ""),
                str(differential_diagnosis or ""),
                dicom_folder_path,
                str(original_source_path or ""),
                str(source_type or "manual"),
                str(patient_id or ""),
                str(study_uid or ""),
            ),
        )
        return int(cur.lastrowid)


def update_case(case_pk: int, **fields: Any) -> None:
    allowed = {
        "saved_by",
        "modality",
        "body_part",
        "diagnosis",
        "anatomical_classification",
        "protocol_details",
        "description",
        "differential_diagnosis",
    }
    updates: List[str] = []
    params: List[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        updates.append(f"{key} = ?")
        params.append(str(value or "").strip())
    if not updates:
        return
    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(int(case_pk))
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE case_of_day_entries SET {', '.join(updates)} WHERE case_pk = ?", params)


def delete_case(case_pk: int) -> None:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM case_of_day_entries WHERE case_pk = ?", (int(case_pk),))


def copy_dicom_folder_to_case_storage(source_folder: str, case_hint: str = "") -> str:
    src = Path(source_folder)
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"DICOM folder not found: {source_folder}")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe_hint = "".join(ch for ch in str(case_hint or "").strip().replace(" ", "_") if ch.isalnum() or ch in {"_", "-"})
    name = f"case_{stamp}"
    if safe_hint:
        name = f"{name}_{safe_hint[:30]}"
    dst = CASE_OF_DAY_STORAGE_PATH / name
    counter = 1
    while dst.exists():
        dst = CASE_OF_DAY_STORAGE_PATH / f"{name}_{counter}"
        counter += 1

    shutil.copytree(src, dst)
    return str(dst)

