from __future__ import annotations

import json
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from PacsClient.utils.config import CASE_OF_DAY_STORAGE_PATH
from PacsClient.utils.database import get_db_connection

# Subfolder names used inside every case-of-day package directory.
# DICOM_SUBDIR is what the DB's `dicom_folder_path` actually points to, so
# the existing viewer (PatientWidget) keeps working unchanged.
PACKAGE_DICOM_SUBDIR = "dicom"
PACKAGE_METADATA_FILE = "metadata.json"
PACKAGE_RECEPTION_FILE = "reception.json"
PACKAGE_ATTACHMENTS_SUBDIR = "attachments"


# ---------------------------------------------------------------------------
# Global signal hub. Keeps the rest of the app decoupled from the toolbar:
# anyone interested in "a case was just saved" can connect to
# ``case_of_day_events().saved`` without depending on the toolbar widget.
# The Education tab subscribes to it to refresh its list, and the home page
# patient list subscribes to refresh the Status column icons.
# ---------------------------------------------------------------------------
try:
    from PySide6.QtCore import QObject, Signal

    class _CaseOfDayEvents(QObject):
        saved = Signal(dict)  # {"study_uid": str, "patient_id": str}

    _events_singleton: Optional["_CaseOfDayEvents"] = None

    def case_of_day_events() -> "_CaseOfDayEvents":
        global _events_singleton
        if _events_singleton is None:
            _events_singleton = _CaseOfDayEvents()
        return _events_singleton

except Exception:  # PySide6 unavailable in some build paths — degrade gracefully.
    def case_of_day_events():  # type: ignore[no-redef]
        return None


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
    patient_name: str
    study_uid: str
    study_description: str
    study_date: str
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
        # The connection pool rolls back on return-to-pool. Without an
        # explicit commit, this INSERT is silently undone.
        conn.commit()
    return value


def _row_field(row: sqlite3.Row, name: str, default: str = "") -> str:
    """Defensive accessor for sqlite3.Row — columns that don't exist (older DB
    without our new ALTER TABLE migration applied yet) just return the default."""
    try:
        value = row[name]
    except (IndexError, KeyError):
        return default
    return str(value) if value is not None else default


def _row_to_entry(row: sqlite3.Row) -> CaseOfDayEntry:
    return CaseOfDayEntry(
        case_pk=int(row["case_pk"]),
        saved_by=_row_field(row, "saved_by"),
        modality=_row_field(row, "modality"),
        body_part=_row_field(row, "body_part"),
        diagnosis=_row_field(row, "diagnosis"),
        anatomical_classification=_row_field(row, "anatomical_classification"),
        protocol_details=_row_field(row, "protocol_details"),
        description=_row_field(row, "description"),
        differential_diagnosis=_row_field(row, "differential_diagnosis"),
        dicom_folder_path=_row_field(row, "dicom_folder_path"),
        original_source_path=_row_field(row, "original_source_path"),
        source_type=_row_field(row, "source_type", "manual"),
        patient_id=_row_field(row, "patient_id"),
        patient_name=_row_field(row, "patient_name"),
        study_uid=_row_field(row, "study_uid"),
        study_description=_row_field(row, "study_description"),
        study_date=_row_field(row, "study_date"),
        created_at=_row_field(row, "created_at"),
        updated_at=_row_field(row, "updated_at"),
    )


def get_all_cases() -> List[CaseOfDayEntry]:
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM case_of_day_entries ORDER BY updated_at DESC, case_pk DESC")
        return [_row_to_entry(row) for row in cur.fetchall()]


def has_case_of_day_for_patient(patient_id: str = "", study_uid: str = "") -> int:
    """Return the number of Case-of-Day entries saved for the given patient
    and/or study. Used by:

    * the patient viewer toolbar — to show a "1" indicator badge near the
      Case-of-Day button when this study/patient already has a saved case;
    * the patient list Status column — to show a graduation-cap icon when
      any case exists for this patient.

    Either argument may be empty; the query simply skips the unsupplied
    filter. Returns 0 on any failure so the UI degrades quietly.
    """
    patient_id = str(patient_id or "").strip()
    study_uid = str(study_uid or "").strip()
    if not patient_id and not study_uid:
        return 0
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            where = []
            params: List[Any] = []
            if study_uid:
                where.append("study_uid = ?")
                params.append(study_uid)
            if patient_id:
                where.append("patient_id = ?")
                params.append(patient_id)
            # OR semantics: a case can be referenced by either identifier.
            sql = (
                "SELECT COUNT(*) FROM case_of_day_entries WHERE "
                + " OR ".join(where)
            )
            cur.execute(sql, params)
            row = cur.fetchone()
            return int(row[0] if row else 0)
    except Exception:
        return 0


def get_cases_for_patient(patient_id: str = "", study_uid: str = "") -> List[CaseOfDayEntry]:
    """Return all Case-of-Day rows that reference this patient and/or study.
    Same OR-semantics as :func:`has_case_of_day_for_patient`."""
    patient_id = str(patient_id or "").strip()
    study_uid = str(study_uid or "").strip()
    if not patient_id and not study_uid:
        return []
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            where = []
            params: List[Any] = []
            if study_uid:
                where.append("study_uid = ?")
                params.append(study_uid)
            if patient_id:
                where.append("patient_id = ?")
                params.append(patient_id)
            sql = (
                "SELECT * FROM case_of_day_entries WHERE "
                + " OR ".join(where)
                + " ORDER BY updated_at DESC, case_pk DESC"
            )
            cur.execute(sql, params)
            return [_row_to_entry(row) for row in cur.fetchall()]
    except Exception:
        return []


def get_case(case_pk: int) -> Optional[CaseOfDayEntry]:
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM case_of_day_entries WHERE case_pk = ?", (int(case_pk),))
        row = cur.fetchone()
        return _row_to_entry(row) if row else None


def count_cases_for_patient(patient_id: str = "", study_uid: str = "") -> int:
    """Return the number of saved local Case-of-Day entries that match this
    patient_id and/or study_uid. Used to drive the Education-cap status icon
    in the patient list, and the badge on the patient-viewer toolbar button.

    Empty arguments are ignored — pass any non-empty subset; the match is
    inclusive (any provided value must match).
    """
    pid = str(patient_id or "").strip()
    suid = str(study_uid or "").strip()
    if not pid and not suid:
        return 0
    clauses: List[str] = []
    params: List[Any] = []
    if pid:
        clauses.append("patient_id = ?")
        params.append(pid)
    if suid:
        clauses.append("study_uid = ?")
        params.append(suid)
    where = " OR ".join(clauses)
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT COUNT(*) FROM case_of_day_entries WHERE {where}",
                params,
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


def get_cases_for_patient(patient_id: str = "", study_uid: str = "") -> List[CaseOfDayEntry]:
    """Same matching rule as ``count_cases_for_patient`` but returns the
    full entry list. Empty result on no match / DB error."""
    pid = str(patient_id or "").strip()
    suid = str(study_uid or "").strip()
    if not pid and not suid:
        return []
    clauses: List[str] = []
    params: List[Any] = []
    if pid:
        clauses.append("patient_id = ?")
        params.append(pid)
    if suid:
        clauses.append("study_uid = ?")
        params.append(suid)
    where = " OR ".join(clauses)
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                f"SELECT * FROM case_of_day_entries WHERE {where} "
                f"ORDER BY updated_at DESC, case_pk DESC",
                params,
            )
            return [_row_to_entry(r) for r in cur.fetchall()]
    except Exception:
        return []


def search_cases(query: str = "", modality: str = None, body_part: str = None) -> List[CaseOfDayEntry]:
    """Filter saved cases. Search is a case-insensitive substring match across
    every text field — diagnosis, body part, modality, patient ID/name,
    study description, protocol, notes, DDX, etc. This is what makes "find by
    patient", "find by body part", "find by diagnosis" all work from the same
    search box on the Education page."""
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
                    entry.patient_name,
                    entry.study_uid,
                    entry.study_description,
                    entry.study_date,
                ]
            ).lower()
            if q not in blob:
                continue
        filtered.append(entry)
    return filtered


def insert_case(
    *,
    diagnosis: str,
    saved_by: str = "",
    modality: str = "",
    body_part: str = "",
    dicom_folder_path: str = "",
    anatomical_classification: str = "",
    protocol_details: str = "",
    description: str = "",
    differential_diagnosis: str = "",
    original_source_path: str = "",
    source_type: str = "manual",
    patient_id: str = "",
    patient_name: str = "",
    study_uid: str = "",
    study_description: str = "",
    study_date: str = "",
) -> int:
    """Persist a Case-of-Day entry. **Only `diagnosis` is required** — every
    other field is stored as empty-string when omitted. This keeps the
    save-flow low-friction from the patient toolbar (where most metadata can
    be auto-filled) and from the manual Education entry point alike."""
    diagnosis = str(diagnosis or "").strip()
    if not diagnosis:
        raise ValueError("Diagnosis is required")

    # If the user typed a brand-new body part value, register it in the lookup
    # table so future cases get it in the dropdown. Silent on duplicates.
    body_part_norm = str(body_part or "").strip()
    if body_part_norm:
        try:
            add_body_part(body_part_norm)
        except Exception:
            # Already exists / DB lock — non-fatal for the save itself.
            pass

    with get_db_connection() as conn:
        cur = conn.cursor()
        # We always provide a value for every column (empty string when
        # unknown) so the older NOT-NULL-flavored schemas keep accepting it.
        cur.execute(
            """
            INSERT INTO case_of_day_entries (
                saved_by, modality, body_part, diagnosis,
                anatomical_classification, protocol_details, description, differential_diagnosis,
                dicom_folder_path, original_source_path, source_type,
                patient_id, patient_name, study_uid, study_description, study_date,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                str(saved_by or "").strip(),
                str(modality or "").strip(),
                body_part_norm,
                diagnosis,
                str(anatomical_classification or ""),
                str(protocol_details or ""),
                str(description or ""),
                str(differential_diagnosis or ""),
                str(dicom_folder_path or "").strip(),
                str(original_source_path or ""),
                str(source_type or "manual"),
                str(patient_id or ""),
                str(patient_name or ""),
                str(study_uid or ""),
                str(study_description or ""),
                str(study_date or ""),
            ),
        )
        new_pk = int(cur.lastrowid)
        # CRITICAL: ``get_db_connection``'s pool calls ``conn.rollback()`` when
        # the connection is returned to the pool (see database/_pool.py
        # ``_return_to_pool``). Without an explicit commit here, the INSERT
        # above is silently undone — every save would return ``case_pk=1`` and
        # leave the table empty. Don't remove this commit.
        conn.commit()
        return new_pk


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
        "patient_id",
        "patient_name",
        "study_uid",
        "study_description",
        "study_date",
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
        # See note in insert_case — explicit commit is required because the
        # pool rolls back on return.
        conn.commit()


def delete_case(case_pk: int) -> None:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM case_of_day_entries WHERE case_pk = ?", (int(case_pk),))
        conn.commit()


def _allocate_case_package_dir(case_hint: str = "") -> Path:
    """Reserve a unique package directory under ``CASE_OF_DAY_STORAGE_PATH``.

    Returned dir does NOT exist on disk yet — the caller decides whether to
    populate it. Naming pattern: ``case_<YYYYMMDD_HHMMSS>[_<hint>][_N]``.
    """
    CASE_OF_DAY_STORAGE_PATH.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe_hint = "".join(
        ch for ch in str(case_hint or "").strip().replace(" ", "_")
        if ch.isalnum() or ch in {"_", "-"}
    )
    base_name = f"case_{stamp}"
    if safe_hint:
        base_name = f"{base_name}_{safe_hint[:40]}"
    dst = CASE_OF_DAY_STORAGE_PATH / base_name
    counter = 1
    while dst.exists():
        dst = CASE_OF_DAY_STORAGE_PATH / f"{base_name}_{counter}"
        counter += 1
    return dst


def copy_dicom_folder_to_case_storage(source_folder: str, case_hint: str = "") -> str:
    """Copy a study folder into a fresh case package and return the **DICOM
    subfolder** path (this is what the DB ``dicom_folder_path`` should be set
    to, since the viewer treats that as the DICOM root).

    On-disk layout produced::

        Case of the Day/
            case_<stamp>_<hint>/
                dicom/        <-- everything from `source_folder` lands here
                              (metadata.json + reception.json are written
                               later by ``write_case_package_metadata`` once
                               the user has typed the case fields)
    """
    src = Path(source_folder)
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"DICOM folder not found: {source_folder}")

    package_dir = _allocate_case_package_dir(case_hint)
    dicom_dir = package_dir / PACKAGE_DICOM_SUBDIR
    # Create the package + dicom subfolder atomically via copytree.
    shutil.copytree(src, dicom_dir)
    return str(dicom_dir)


def resolve_case_package_dir(dicom_folder_path: str) -> Optional[Path]:
    """Given the DB ``dicom_folder_path`` (which points at the DICOM root),
    return the enclosing case-package directory if that folder follows the
    new structure (``<package>/dicom/``).

    Returns ``None`` for legacy cases where the DICOM folder *is* the case
    folder (no ``dicom/`` subdir). Callers should treat None as "this is an
    old-style case, just use the dicom_folder_path itself".
    """
    if not dicom_folder_path:
        return None
    p = Path(dicom_folder_path)
    if p.name == PACKAGE_DICOM_SUBDIR and p.parent.exists():
        return p.parent
    return None


def write_case_package_metadata(
    *,
    dicom_folder_path: str,
    case_pk: int,
    metadata: Dict[str, Any],
    reception_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Write the JSON sidecars (``metadata.json``, optional ``reception.json``)
    next to the DICOM subfolder.

    No-op (returns empty dict) for legacy cases where ``dicom_folder_path``
    is not nested inside a package dir — those continue to work as plain
    DICOM folders without sidecars.

    Returned mapping points to the files actually written, so callers can log
    them or stash the paths in the DB if desired.
    """
    package_dir = resolve_case_package_dir(dicom_folder_path)
    if package_dir is None:
        return {}

    written: Dict[str, str] = {}
    try:
        package_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return {}

    enriched = {
        "schema": "ai-pacs.case_of_day.v1",
        "case_pk": int(case_pk),
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dicom_relpath": PACKAGE_DICOM_SUBDIR,
        **metadata,
    }
    metadata_path = package_dir / PACKAGE_METADATA_FILE
    try:
        metadata_path.write_text(
            json.dumps(enriched, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written["metadata"] = str(metadata_path)
    except Exception:
        # Sidecar failure must not break the save — DB row is the source of truth.
        pass

    if reception_payload:
        reception_path = package_dir / PACKAGE_RECEPTION_FILE
        try:
            reception_path.write_text(
                json.dumps(reception_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            written["reception"] = str(reception_path)
        except Exception:
            pass

    return written


def attach_file_to_case_package(dicom_folder_path: str, file_path: str) -> Optional[str]:
    """Copy *file_path* into the package's ``attachments/`` subfolder, if the
    case follows the new package layout. Returns the destination path or
    ``None`` if the case is legacy / the source doesn't exist."""
    package_dir = resolve_case_package_dir(dicom_folder_path)
    if package_dir is None:
        return None
    src = Path(file_path)
    if not src.exists() or not src.is_file():
        return None
    target_dir = package_dir / PACKAGE_ATTACHMENTS_SUBDIR
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / src.name
        counter = 1
        while dest.exists():
            dest = target_dir / f"{src.stem}_{counter}{src.suffix}"
            counter += 1
        shutil.copy2(src, dest)
        return str(dest)
    except Exception:
        return None


def load_reception_payload_for_patient(patient_id: str) -> Optional[Dict[str, Any]]:
    """Best-effort lookup of cached reception data for *patient_id*. Mirrors
    the path used elsewhere in the app
    (``RECEPTION_REPORTS_DIR/downloads/patient_<id>.json``). Returns ``None``
    if the file is missing or unreadable.
    """
    pid = "".join(ch for ch in str(patient_id or "").strip() if ch.isalnum() or ch in {"_", "-"})
    if not pid:
        return None
    try:
        from PacsClient.utils.data_paths import RECEPTION_REPORTS_DIR
    except Exception:
        return None
    bundle = Path(RECEPTION_REPORTS_DIR) / "downloads" / f"patient_{pid}.json"
    if not bundle.exists():
        return None
    try:
        return json.loads(bundle.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# DICOM tag extraction — used to auto-fill the entry dialog from a study.
# Reads only the first DICOM file found (header only, stop_before_pixels) so
# this is cheap to call from a UI thread before opening the dialog.
# ---------------------------------------------------------------------------

_DICOM_EXTS = {".dcm", ".dicom", ""}  # some PACS exports drop the extension


def _find_first_dicom_file(folder: Path, max_scan: int = 200) -> Optional[Path]:
    """Locate one readable DICOM file under *folder* (recurses one or two
    levels). Returns None if none found within *max_scan* candidates."""
    if folder is None or not folder.exists():
        return None
    if folder.is_file():
        return folder if folder.suffix.lower() in _DICOM_EXTS else None

    scanned = 0
    # 1) Fast pass: explicit .dcm extension.
    for child in folder.rglob("*.dcm"):
        if child.is_file():
            return child
    for child in folder.rglob("*.DCM"):
        if child.is_file():
            return child
    # 2) Slower fallback: peek at the DICM magic at offset 128.
    for child in folder.rglob("*"):
        if not child.is_file():
            continue
        scanned += 1
        if scanned > max_scan:
            break
        try:
            with child.open("rb") as f:
                head = f.read(132)
            if len(head) >= 132 and head[128:132] == b"DICM":
                return child
        except Exception:
            continue
    return None


def extract_dicom_metadata(source_folder: str) -> Dict[str, str]:
    """Read a sample DICOM file from *source_folder* and return the subset of
    tags that the Case-of-Day entry form auto-fills:

    * modality           — DICOM (0008,0060)
    * body_part          — DICOM (0018,0015) BodyPartExamined
    * patient_id         — DICOM (0010,0020)
    * patient_name       — DICOM (0010,0010)
    * study_uid          — DICOM (0020,000D)
    * study_description  — DICOM (0008,1030)
    * study_date         — DICOM (0008,0020) (YYYYMMDD)

    Best-effort — returns an empty dict if pydicom is unavailable or no file
    can be read. The caller MUST treat this as advisory data, not a guarantee."""
    out: Dict[str, str] = {}
    try:
        folder = Path(str(source_folder or "")).expanduser()
        sample = _find_first_dicom_file(folder)
        if sample is None:
            return out
        try:
            from pydicom import dcmread  # local import: pydicom may be optional in some builds
        except Exception:
            return out
        try:
            ds = dcmread(str(sample), stop_before_pixels=True, force=True)
        except Exception:
            return out

        def _val(tag_name: str) -> str:
            try:
                raw = getattr(ds, tag_name, None)
                if raw is None:
                    return ""
                text = str(raw).strip()
                return "" if text.lower() in {"unknown", "n/a", "na"} else text
            except Exception:
                return ""

        out["modality"] = _val("Modality")
        out["body_part"] = _val("BodyPartExamined")
        out["patient_id"] = _val("PatientID")
        out["patient_name"] = _val("PatientName")
        out["study_uid"] = _val("StudyInstanceUID")
        out["study_description"] = _val("StudyDescription")
        out["study_date"] = _val("StudyDate")
    except Exception:
        return {}
    # Drop empty values so the caller can do `prefill.update(extracted)` cleanly.
    return {k: v for k, v in out.items() if v}
