from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_log = logging.getLogger(__name__)

from aipacs_runtime import roaming_config_root, seed_user_config_defaults

from PacsClient.utils.data_paths import (
    ATTACHMENTS_DIR,
    DATABASE_FILE,
    DICOM_IMAGES_DIR,
    THUMBNAILS_DIR,
)
from _project_root import PROJECT_ROOT


OFFLINE_CLOUD_FORMAT = "aipacs-offline-cloud"
OFFLINE_CLOUD_VERSION = 2
PACKAGE_DB_NAME = "package.db"
MANIFEST_NAME = "manifest.json"
_PACKAGE_REQUIRED_FOLDERS = (
    "patients",
    "patients/dicom",
    "patients/attachments",
    "patients/thumbnails",
)

_RELEVANT_TABLES = (
    "patients",
    "studies",
    "series",
    "instances",
    "download_progress",
    "ai_sessions",
    "ai_messages",
    "ai_reports",
    "ai_last_session",
    "ai_reception_reports",
)


def _config_root() -> Path:
    if getattr(sys, "frozen", False):
        seed_user_config_defaults()
        return roaming_config_root()
    return PROJECT_ROOT / "config"


OFFLINE_CLOUD_CONFIG_PATH = _config_root() / "offline_cloud_servers.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _default_config() -> dict[str, Any]:
    return {"servers": []}


def load_offline_cloud_config() -> dict[str, Any]:
    default = _default_config()
    if not OFFLINE_CLOUD_CONFIG_PATH.exists():
        return default
    try:
        with open(OFFLINE_CLOUD_CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return default
        if not isinstance(data.get("servers"), list):
            data["servers"] = []
        return data
    except (OSError, json.JSONDecodeError):
        return default


def save_offline_cloud_config(data: dict[str, Any]) -> None:
    OFFLINE_CLOUD_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OFFLINE_CLOUD_CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=4, ensure_ascii=False)


def get_all_offline_cloud_servers() -> list[dict[str, Any]]:
    servers = load_offline_cloud_config().get("servers", [])
    result: list[dict[str, Any]] = []
    for server in servers:
        if not isinstance(server, dict):
            continue
        name = str(server.get("name") or "").strip()
        folder_path = str(server.get("folder_path") or "").strip()
        if not name or not folder_path:
            continue
        result.append(
            {
                "name": name,
                "folder_path": folder_path,
                "description": str(server.get("description") or "").strip(),
                "server_type": "offline_cloud",
            }
        )
    return result


def get_offline_cloud_server(name: str) -> dict[str, Any] | None:
    wanted = str(name or "").strip()
    if not wanted:
        return None
    for server in get_all_offline_cloud_servers():
        if server.get("name") == wanted:
            return server
    return None


def package_paths(root: str | Path) -> dict[str, Path]:
    base = Path(root).expanduser().resolve()
    patients_root = base / "patients"
    return {
        "root": base,
        "manifest": base / MANIFEST_NAME,
        "database": base / PACKAGE_DB_NAME,
        "patients_root": patients_root,
        "dicom": patients_root / "dicom",
        "attachments": patients_root / "attachments",
        "thumbnails": patients_root / "thumbnails",
    }


def _default_manifest(*, valid_format: bool = False) -> dict[str, Any]:
    return {
        "format": OFFLINE_CLOUD_FORMAT if valid_format else None,
        "version": OFFLINE_CLOUD_VERSION,
        "package_id": "",
        "package_status": "manifest_missing",
        "transfer_status": "incomplete",
        "created_at": None,
        "updated_at": None,
        "validated_at": None,
        "origin_server": None,
        "hub_user": None,
        "last_imported_by": None,
        "last_applied_by": None,
        "created_by": None,
        "last_modified_by": None,
        "actors": [],
        "timeline": [],
        "sync_events": [],
        "folder_count": 0,
        "patient_count": 0,
        "study_count": 0,
        "folder_summary": {
            "package_roots": 0,
            "dicom_study_folders": 0,
            "attachment_study_folders": 0,
            "thumbnail_study_folders": 0,
            "total_managed_folders": 0,
        },
        "items_to_load": {
            "load_order": [MANIFEST_NAME, PACKAGE_DB_NAME, *_PACKAGE_REQUIRED_FOLDERS],
            "required_files": [MANIFEST_NAME, PACKAGE_DB_NAME],
            "required_folders": list(_PACKAGE_REQUIRED_FOLDERS),
            "module_tables": [],
            "study_uids": [],
        },
        "validation": {
            "status": "manifest_missing",
            "is_complete": False,
            "manifest_present": False,
            "database_present": False,
            "required_paths": {},
            "missing_items": [MANIFEST_NAME],
            "warnings": [],
        },
        "studies": [],
    }


def _normalize_manifest(data: dict[str, Any] | None) -> dict[str, Any]:
    manifest = _default_manifest(valid_format=False)
    if isinstance(data, dict):
        manifest.update(data)

    if not isinstance(manifest.get("studies"), list):
        manifest["studies"] = []
    if not isinstance(manifest.get("actors"), list):
        manifest["actors"] = []
    if not isinstance(manifest.get("sync_events"), list):
        manifest["sync_events"] = []
    if not isinstance(manifest.get("timeline"), list):
        manifest["timeline"] = []
    if not isinstance(manifest.get("folder_summary"), dict):
        manifest["folder_summary"] = _default_manifest()["folder_summary"]
    if not isinstance(manifest.get("items_to_load"), dict):
        manifest["items_to_load"] = _default_manifest()["items_to_load"]
    if not isinstance(manifest.get("validation"), dict):
        manifest["validation"] = _default_manifest()["validation"]

    manifest["folder_summary"] = {
        **_default_manifest()["folder_summary"],
        **dict(manifest.get("folder_summary") or {}),
    }
    manifest["items_to_load"] = {
        **_default_manifest()["items_to_load"],
        **dict(manifest.get("items_to_load") or {}),
    }
    manifest["validation"] = {
        **_default_manifest()["validation"],
        **dict(manifest.get("validation") or {}),
    }

    timeline = [item for item in manifest.get("timeline") or [] if isinstance(item, dict)]
    sync_events = [item for item in manifest.get("sync_events") or [] if isinstance(item, dict)]
    if timeline and not sync_events:
        sync_events = list(timeline)
    if sync_events and not timeline:
        timeline = list(sync_events)
    if not timeline and not sync_events:
        timeline = []
        sync_events = []
    manifest["timeline"] = timeline[-50:]
    manifest["sync_events"] = sync_events[-50:]
    manifest["study_count"] = len(manifest["studies"])
    if not isinstance(manifest.get("patient_count"), int):
        manifest["patient_count"] = len(
            {
                str(study.get("patient_id") or "").strip()
                for study in manifest["studies"]
                if isinstance(study, dict) and str(study.get("patient_id") or "").strip()
            }
        )
    if not isinstance(manifest.get("folder_count"), int):
        manifest["folder_count"] = int(
            manifest.get("folder_summary", {}).get("total_managed_folders") or 0
        )
    return manifest


def read_offline_cloud_manifest(root: str | Path) -> dict[str, Any]:
    paths = package_paths(root)
    default = _default_manifest(valid_format=False)
    manifest_path = paths["manifest"]
    if not manifest_path.exists():
        return default
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return default
        manifest = _normalize_manifest(data)
        if manifest.get("format") != OFFLINE_CLOUD_FORMAT:
            return default
        return manifest
    except (OSError, json.JSONDecodeError):
        return default


def write_offline_cloud_manifest(root: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    paths = package_paths(root)
    paths["root"].mkdir(parents=True, exist_ok=True)
    normalized = _normalize_manifest(manifest)
    normalized["format"] = OFFLINE_CLOUD_FORMAT
    normalized["version"] = OFFLINE_CLOUD_VERSION
    normalized["package_id"] = str(normalized.get("package_id") or uuid4())
    normalized["created_at"] = normalized.get("created_at") or _utc_now_iso()
    normalized["updated_at"] = _utc_now_iso()
    normalized["timeline"] = list(normalized.get("sync_events") or normalized.get("timeline") or [])[-50:]
    normalized["sync_events"] = list(normalized["timeline"])
    with open(paths["manifest"], "w", encoding="utf-8") as fh:
        json.dump(normalized, fh, indent=2, ensure_ascii=False)
    return validate_offline_cloud_package(paths["root"], rewrite_manifest=True)


def validate_offline_cloud_package(root: str | Path, *, rewrite_manifest: bool = False) -> dict[str, Any]:
    paths = package_paths(root)
    now = _utc_now_iso()
    raw_manifest: dict[str, Any] | None = None
    manifest_exists = paths["manifest"].exists()
    manifest_error: str | None = None

    if manifest_exists:
        try:
            with open(paths["manifest"], "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                raw_manifest = loaded
            else:
                manifest_error = "Manifest root must be a JSON object."
        except (OSError, json.JSONDecodeError) as exc:
            manifest_error = str(exc)

    manifest = _normalize_manifest(raw_manifest)
    warnings: list[str] = []
    missing_items: list[str] = []
    required_paths = {
        relative_path: (paths["root"] / relative_path).exists()
        for relative_path in _PACKAGE_REQUIRED_FOLDERS
    }

    if not paths["root"].exists():
        warnings.append("Package root folder does not exist yet.")
    if not manifest_exists:
        missing_items.append(MANIFEST_NAME)
    if manifest_error:
        warnings.append(f"Manifest could not be read: {manifest_error}")
    if manifest_exists and not manifest_error and manifest.get("format") != OFFLINE_CLOUD_FORMAT:
        warnings.append("Manifest format is not recognized as an AI PACS Offline Cloud package.")
    if not paths["database"].exists():
        missing_items.append(PACKAGE_DB_NAME)
    for relative_path, exists in required_paths.items():
        if not exists:
            missing_items.append(relative_path)

    module_tables: list[str] = []
    actual_study_rows: list[dict[str, Any]] = []
    actual_study_uids: list[str] = []
    actual_patient_ids: set[str] = set()
    if paths["database"].exists():
        try:
            with _connect(paths["database"]) as conn:
                module_tables = [table for table in _RELEVANT_TABLES if _has_table(conn, table)]
                if _has_table(conn, "studies"):
                    actual_study_rows = _fetch_all(
                        conn,
                        "SELECT study_uid, patient_fk FROM studies ORDER BY study_uid",
                    )
                if _has_table(conn, "patients"):
                    for row in actual_study_rows:
                        study_uid = str(row.get("study_uid") or "").strip()
                        if study_uid:
                            actual_study_uids.append(study_uid)
                        patient_fk = row.get("patient_fk")
                        if patient_fk is None:
                            continue
                        patient_row = _fetch_one(
                            conn,
                            "SELECT patient_id FROM patients WHERE patient_pk = ?",
                            (patient_fk,),
                        )
                        patient_id = str((patient_row or {}).get("patient_id") or "").strip()
                        if patient_id:
                            actual_patient_ids.add(patient_id)
        except Exception as exc:
            warnings.append(f"Package database could not be inspected: {exc}")

    manifest_study_uids = [
        str(study.get("study_uid") or "").strip()
        for study in manifest.get("studies", [])
        if isinstance(study, dict) and str(study.get("study_uid") or "").strip()
    ]
    study_uids = actual_study_uids or manifest_study_uids

    if actual_study_uids and manifest_study_uids and set(actual_study_uids) != set(manifest_study_uids):
        warnings.append("Manifest study list does not match the package database study list.")

    missing_dicom_studies = [
        study_uid
        for study_uid in study_uids
        if _count_files(paths["dicom"] / study_uid) <= 0
    ]
    if missing_dicom_studies:
        missing_items.extend([f"patients/dicom/{study_uid}" for study_uid in missing_dicom_studies[:20]])
        if len(missing_dicom_studies) > 20:
            warnings.append(
                f"{len(missing_dicom_studies) - 20} more study folders are missing DICOM payloads."
            )

    folder_summary = {
        "package_roots": sum(1 for relative_path in _PACKAGE_REQUIRED_FOLDERS if (paths["root"] / relative_path).exists()),
        "dicom_study_folders": _count_immediate_dirs(paths["dicom"]),
        "attachment_study_folders": _count_immediate_dirs(paths["attachments"]),
        "thumbnail_study_folders": _count_immediate_dirs(paths["thumbnails"]),
    }
    folder_summary["total_managed_folders"] = int(
        folder_summary["package_roots"]
        + folder_summary["dicom_study_folders"]
        + folder_summary["attachment_study_folders"]
        + folder_summary["thumbnail_study_folders"]
    )

    patient_count = len(actual_patient_ids) or len(
        {
            str(study.get("patient_id") or "").strip()
            for study in manifest.get("studies", [])
            if isinstance(study, dict) and str(study.get("patient_id") or "").strip()
        }
    )
    study_count = len(study_uids) or len(manifest.get("studies", []))
    items_to_load = {
        "load_order": [MANIFEST_NAME, PACKAGE_DB_NAME, *_PACKAGE_REQUIRED_FOLDERS],
        "required_files": [MANIFEST_NAME, PACKAGE_DB_NAME],
        "required_folders": list(_PACKAGE_REQUIRED_FOLDERS),
        "module_tables": module_tables,
        "study_uids": study_uids,
    }

    if not paths["root"].exists():
        status = "folder_missing"
    elif not manifest_exists:
        status = "manifest_missing"
    elif manifest_error or manifest.get("format") != OFFLINE_CLOUD_FORMAT:
        status = "manifest_invalid"
    elif missing_items:
        status = "incomplete"
    else:
        status = "ready"

    validation = {
        "status": status,
        "is_complete": status == "ready",
        "manifest_present": manifest_exists and manifest_error is None,
        "database_present": paths["database"].exists(),
        "required_paths": required_paths,
        "missing_items": sorted({str(item) for item in missing_items}),
        "warnings": warnings,
    }

    try:
        manifest["version"] = int(manifest.get("version") or OFFLINE_CLOUD_VERSION)
    except (TypeError, ValueError):
        manifest["version"] = OFFLINE_CLOUD_VERSION
    manifest["package_status"] = status
    manifest["transfer_status"] = "complete" if validation["is_complete"] else "incomplete"
    manifest["validated_at"] = now
    manifest["folder_count"] = folder_summary["total_managed_folders"]
    manifest["patient_count"] = patient_count
    manifest["study_count"] = study_count
    manifest["folder_summary"] = folder_summary
    manifest["items_to_load"] = items_to_load
    manifest["validation"] = validation
    manifest["timeline"] = list(manifest.get("sync_events") or manifest.get("timeline") or [])[-50:]
    manifest["sync_events"] = list(manifest["timeline"])

    if rewrite_manifest and manifest_exists and manifest_error is None:
        manifest["format"] = OFFLINE_CLOUD_FORMAT
        manifest["version"] = OFFLINE_CLOUD_VERSION
        manifest["package_id"] = str(manifest.get("package_id") or uuid4())
        manifest["created_at"] = manifest.get("created_at") or now
        manifest["updated_at"] = now
        with open(paths["manifest"], "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)

    return manifest


def list_offline_cloud_studies(server: dict[str, Any], search_data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    manifest = read_offline_cloud_manifest(server.get("folder_path", ""))
    search_data = search_data or {}
    patient_id_filter = str(search_data.get("patient_id") or "").strip().lower()
    patient_name_filter = str(search_data.get("patient_name") or "").strip().lower()
    modality_filter = str(search_data.get("modality") or "").strip().lower()
    date_from = _normalize_date_for_compare(search_data.get("date_from"))
    date_to = _normalize_date_for_compare(search_data.get("date_to"))

    results: list[dict[str, Any]] = []
    for study in manifest.get("studies", []):
        if not isinstance(study, dict):
            continue
        patient_id = str(study.get("patient_id") or "")
        patient_name = str(study.get("patient_name") or "")
        modality = str(study.get("modality") or "")
        study_date = str(study.get("study_date") or "")
        compare_date = _normalize_date_for_compare(study_date)

        if patient_id_filter and patient_id_filter not in patient_id.lower():
            continue
        if patient_name_filter and patient_name_filter not in patient_name.lower():
            continue
        if modality_filter and modality_filter not in modality.lower():
            continue
        if date_from and compare_date and compare_date < date_from:
            continue
        if date_to and compare_date and compare_date > date_to:
            continue

        results.append(
            {
                "source": "offline_cloud",
                "server_type": "offline_cloud",
                "patient_id": patient_id,
                "patient_name": patient_name,
                "study_uid": str(study.get("study_uid") or ""),
                "study_date": study_date,
                "study_time": str(study.get("study_time") or ""),
                "study_description": str(study.get("study_description") or ""),
                "description": str(study.get("study_description") or ""),
                "modality": modality,
                "body_part": str(study.get("body_part") or ""),
                "series_count": int(study.get("number_of_series") or 0),
                "images_count": int(study.get("number_of_instances") or 0),
                "report_status": str(study.get("report_status") or "pending"),
                "visit_status": study.get("visit_status"),
                "package_paths": study.get("package_paths") or {},
            }
        )

    results.sort(
        key=lambda item: (
            str(item.get("study_date") or ""),
            str(item.get("study_time") or ""),
            str(item.get("patient_name") or ""),
        ),
        reverse=True,
    )
    return results


def get_offline_cloud_study_info(server: dict[str, Any], study_uid: str) -> dict[str, Any] | None:
    study_uid = str(study_uid or "").strip()
    if not study_uid:
        return None
    paths = package_paths(server.get("folder_path", ""))
    if not paths["database"].exists():
        return None

    with _connect(paths["database"]) as conn:
        study_row = _fetch_one(conn, "SELECT * FROM studies WHERE study_uid = ?", (study_uid,))
        if not study_row:
            return None

        patient_row = _fetch_one(
            conn,
            "SELECT * FROM patients WHERE patient_pk = ?",
            (study_row.get("patient_fk"),),
        )
        series_rows = _fetch_all(
            conn,
            "SELECT * FROM series WHERE study_fk = ? ORDER BY series_number",
            (study_row.get("study_pk"),),
        )
        return {
            "study": study_row,
            "patient": patient_row or {},
            "series": series_rows,
            "paths": paths,
        }


DICOMDIR_NAME = "DICOMDIR"
DICOMDIR_STAMP_NAME = ".aipacs_dicomdir.json"
DICOMDIR_FILESET_ID = "AIPACS_OFFLINE"
# Human-readable interchange tree: DICOM/<Patient_Name>/<StudyInstanceUID>/
#   ├── DICOMDIR                (File IDs are relative to THIS folder → compliant)
#   └── PT000000/ST000000/SE000000/IM000001
# The readable names sit ABOVE the DICOMDIR, where the <=8-char [A-Z0-9_] File ID
# rule (PS3.10) does not apply — which is why a single media-root DICOMDIR can
# never have readable folder names.
DICOM_INTERCHANGE_DIRNAME = "DICOM"


# ---------------------------------------------------------------------------
# Per-series export selection (2026-07-30)
# ---------------------------------------------------------------------------
# A caller may pass ``series_selection`` = {study_uid: {series_number, ...}} to
# export only SOME series of a study. ``None`` (or a study absent from the map)
# means "all series" — byte-identical to the historical whole-study export.
# The filter is applied at three points that MUST agree, or the package,
# package.db and DICOMDIR would disagree with each other:
#   1. the ``series`` DB rows written to package.db
#   2. the ``instances`` DB rows (nested under the kept series)
#   3. the on-disk DICOM subfolders copied into patients/dicom/<study_uid>/
# DICOMDIR is then rebuilt from the copied files, so it inherits the filter
# automatically. Kill switch: AIPACS_EXPORT_SERIES_SELECTION=0 → ignore the map
# entirely and export every series (legacy behaviour).
SeriesSelection = dict[str, "set[str]"]


def _series_selection_enabled() -> bool:
    return str(os.getenv("AIPACS_EXPORT_SERIES_SELECTION", "1")).strip().lower() not in ("0", "false", "no")


def _normalize_series_number(value: Any) -> str:
    """Canonical string key for a series number, tolerant of ``'02'`` / ``2`` / ``2.0``.

    Folder names on disk and ``series.series_number`` in the DB are both the
    series number; this makes the two comparable regardless of how each was
    stored (leading zeros, int vs str, a stray ``.0``).
    """
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    try:
        # 2, "2", "02", "2.0" all collapse to "2"; non-numeric stays verbatim.
        if text.replace(".", "", 1).lstrip("-").isdigit():
            return str(int(float(text)))
    except (TypeError, ValueError):
        pass
    return text


def _selected_series_for(study_uid: str, series_selection: "SeriesSelection | None") -> "set[str] | None":
    """Return the normalized set of series numbers to KEEP, or ``None`` for all."""
    if not series_selection or not _series_selection_enabled():
        return None
    if study_uid not in series_selection:
        return None  # caller did not filter this study → keep everything
    chosen = series_selection.get(study_uid) or set()
    return {_normalize_series_number(sn) for sn in chosen if _normalize_series_number(sn)}


def _dicom_content_signature(dicom_root: Path) -> dict[str, int]:
    """Cheap (file_count, total_bytes) signature of the package's DICOM payload.

    Used to skip regenerating DICOMDIR when nothing changed — the incremental
    Offline-Sync autosave calls the export on every study-state change, and
    rebuilding the whole File-set each time would be very expensive.
    """
    count = 0
    total = 0
    if dicom_root.is_dir():
        for dirpath, _dirs, files in os.walk(dicom_root):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                    count += 1
                except OSError:
                    continue
    return {"file_count": count, "total_bytes": total}


def _clear_previous_dicomdir(root: Path) -> None:
    """Remove the previous interchange output so the rebuild is authoritative.

    Clears the readable ``DICOM/`` tree, plus (for packages written by the earlier
    flat implementation) a root ``DICOMDIR`` and top-level ``PT<digits>`` folders.
    The package's own ``patients/``, ``manifest.json`` and ``package.db`` are
    NEVER touched.
    """
    shutil.rmtree(root / DICOM_INTERCHANGE_DIRNAME, ignore_errors=True)

    legacy_dicomdir = root / DICOMDIR_NAME
    if legacy_dicomdir.exists():
        try:
            legacy_dicomdir.unlink()
        except OSError:
            pass
    for child in root.iterdir():
        if child.is_dir() and re.fullmatch(r"PT\d+", child.name, re.IGNORECASE):
            shutil.rmtree(child, ignore_errors=True)


_ILLEGAL_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_folder_component(text: Any, *, fallback: str = "UNKNOWN", max_len: int = 64) -> str:
    """Filesystem-safe, human-READABLE folder name from DICOM text.

    ``DOE^JOHN`` -> ``DOE_JOHN``. Strips illegal characters, collapses runs of
    whitespace/underscores, trims trailing dots/spaces (Windows rejects those)
    and caps the length. The DICOM metadata itself is never modified — this only
    affects the folder name.
    """
    value = str(text or "").strip()
    value = value.replace("^", " ")               # DICOM PN component separator
    value = _ILLEGAL_FS_CHARS.sub("", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = value.replace(" ", "_")
    value = re.sub(r"_+", "_", value).strip("._ ")
    value = value[:max_len].strip("._ ")
    return value or fallback


def _study_patient_identity(study_dir: Path) -> tuple[str, str]:
    """(PatientName, PatientID) from the first readable DICOM in the study dir."""
    try:
        from pydicom import dcmread
    except Exception:
        return "", ""
    for candidate in sorted(study_dir.rglob("*")):
        if not candidate.is_file():
            continue
        try:
            ds = dcmread(str(candidate), stop_before_pixels=True)
        except Exception:
            continue
        return (
            str(getattr(ds, "PatientName", "") or ""),
            str(getattr(ds, "PatientID", "") or ""),
        )
    return "", ""


def _patient_folder_map(study_dirs: list[Path]) -> dict[Path, str]:
    """Map each study dir -> its readable patient folder name.

    Patients whose names collide (different PatientID, same readable name) are
    disambiguated by appending the PatientID, so every patient keeps an
    independent folder.
    """
    identity: dict[Path, tuple[str, str]] = {
        d: _study_patient_identity(d) for d in study_dirs
    }

    # base readable name per patient id
    base_by_pid: dict[str, str] = {}
    for name, pid in identity.values():
        key = pid or name
        if key not in base_by_pid:
            base_by_pid[key] = safe_folder_component(name or pid, fallback="UNKNOWN_PATIENT")

    # detect collisions: same base name shared by >1 distinct patient key
    owners: dict[str, set[str]] = {}
    for key, base in base_by_pid.items():
        owners.setdefault(base, set()).add(key)

    folder_by_key: dict[str, str] = {}
    for key, base in base_by_pid.items():
        if len(owners[base]) > 1:
            suffix = safe_folder_component(key, fallback="ID", max_len=24)
            folder_by_key[key] = f"{base}_{suffix}"
        else:
            folder_by_key[key] = base

    return {
        d: folder_by_key[(pid or name)]
        for d, (name, pid) in identity.items()
    }


def build_offline_cloud_dicomdir(
    root: str | Path,
    *,
    fileset_id: str = DICOMDIR_FILESET_ID,
    force: bool = False,
) -> dict[str, Any]:
    """Generate a standards-compliant DICOMDIR at the package ROOT.

    Third-party viewers/PACS import interchange media through DICOMDIR. The
    package's own payload lives at ``patients/dicom/<study_uid>/…``, but a DICOM
    File ID component must be <= 8 chars of [A-Z0-9_] (PS3.10) — a StudyInstanceUID
    can NEVER be a valid File ID — so a compliant DICOMDIR cannot reference that
    layout in place. We therefore write the standard ``PT######/ST######/SE######/
    IM######`` tree + ``DICOMDIR`` at the root (pydicom ``FileSet.write``), which
    every DICOM reader understands. The AI-PACS package layout is left untouched,
    so AI-PACS↔AI-PACS sync/import is byte-identical.

    Skips the (expensive) rebuild when the DICOM payload is unchanged, unless
    ``force``. Returns a dict with ``ok`` plus the counts required for logging.
    """
    paths = package_paths(root)
    pkg_root = paths["root"]
    dicom_root = paths["dicom"]

    signature = _dicom_content_signature(dicom_root)
    stamp_path = pkg_root / DICOMDIR_STAMP_NAME

    if signature["file_count"] <= 0:
        msg = "No DICOM files in the package — DICOMDIR not generated."
        _log.warning("DICOMDIR: %s (%s)", msg, dicom_root)
        return {"ok": False, "skipped": False, "error": msg, **signature}

    # Unchanged payload + an interchange tree already present → nothing to do.
    if (
        not force
        and (pkg_root / DICOM_INTERCHANGE_DIRNAME).is_dir()
        and stamp_path.is_file()
    ):
        try:
            previous = json.loads(stamp_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
        if (
            previous.get("file_count") == signature["file_count"]
            and previous.get("total_bytes") == signature["total_bytes"]
        ):
            _log.info(
                "DICOMDIR: up to date (files=%s) — skipping rebuild",
                signature["file_count"],
            )
            return {"ok": True, "skipped": True, **signature, **{
                k: previous.get(k) for k in
                ("patients", "studies", "series", "instances_added")
                if k in previous
            }}

    study_dirs = sorted((d for d in dicom_root.iterdir() if d.is_dir()), key=lambda p: p.name)
    if not study_dirs:
        msg = "No study folders under patients/dicom — DICOMDIR not generated."
        _log.warning("DICOMDIR: %s", msg)
        return {"ok": False, "skipped": False, "error": msg, **signature}

    try:
        from modules.dicom_media.dicomdir import DicomDirBuilder
    except Exception as exc:  # pragma: no cover - pydicom/module missing
        msg = f"DICOMDIR builder unavailable: {exc}"
        _log.error("DICOMDIR: %s", msg)
        return {"ok": False, "skipped": False, "error": msg, **signature}

    folder_by_study = _patient_folder_map(study_dirs)
    _log.info(
        "DICOMDIR: generating readable interchange tree for %s study folder(s), "
        "%s DICOM file(s) at %s/%s",
        len(study_dirs), signature["file_count"], pkg_root, DICOM_INTERCHANGE_DIRNAME,
    )

    # Rebuild from scratch so the output always matches the FINAL structure
    # (a study removed from the package disappears from the interchange tree).
    _clear_previous_dicomdir(pkg_root)
    interchange_root = pkg_root / DICOM_INTERCHANGE_DIRNAME

    totals = {
        "files_found": 0, "series": 0, "instances_added": 0,
        "duplicates_skipped": 0, "unreadable": 0, "failed": 0,
    }
    patient_folders: set[str] = set()
    study_entries: list[dict[str, Any]] = []
    failures: list[str] = []

    for study_dir in study_dirs:
        study_uid = study_dir.name
        patient_folder = folder_by_study.get(study_dir) or "UNKNOWN_PATIENT"
        # DICOM/<Patient_Name>/<StudyInstanceUID>/  — readable AND unique.
        out_dir = interchange_root / patient_folder / study_uid

        builder = DicomDirBuilder()
        ok_study = builder.build_from_study_folders(
            [str(study_dir)], str(out_dir), fileset_id=fileset_id
        )
        st = dict(builder.last_stats or {})

        for key in totals:
            try:
                totals[key] += int(st.get(key) or 0)
            except (TypeError, ValueError):
                pass

        if ok_study:
            patient_folders.add(patient_folder)
            study_entries.append({
                "patient_folder": patient_folder,
                "study_uid": study_uid,
                "path": str(out_dir),
                "dicomdir": str(out_dir / DICOMDIR_NAME),
                "series": st.get("series"),
                "instances": st.get("instances_added"),
            })
            _log.info(
                "DICOMDIR: %s/%s — series=%s instances=%s",
                patient_folder, study_uid, st.get("series"), st.get("instances_added"),
            )
        else:
            failures.append(
                f"{patient_folder}/{study_uid}: "
                f"files_found={st.get('files_found')} "
                f"instances_added={st.get('instances_added')} "
                f"failed={st.get('failed')} unreadable={st.get('unreadable')}"
            )
            _log.error("DICOMDIR: FAILED for %s/%s", patient_folder, study_uid)

    ok = not failures and bool(study_entries)
    result: dict[str, Any] = {
        "ok": ok,
        "skipped": False,
        **signature,
        **totals,
        "patients": len(patient_folders),
        "studies": len(study_entries),
        "patient_folders": sorted(patient_folders),
        "studies_detail": study_entries,
        "interchange_root": str(interchange_root),
    }

    if not ok:
        result["error"] = (
            "DICOMDIR generation failed for "
            f"{len(failures)} of {len(study_dirs)} study folder(s): "
            + "; ".join(failures[:5])
        )
        _log.error("DICOMDIR: %s", result["error"])
        return result

    if totals["failed"] or totals["unreadable"] or totals["duplicates_skipped"]:
        _log.warning(
            "DICOMDIR: completed with issues — failed=%s unreadable=%s duplicates_skipped=%s",
            totals["failed"], totals["unreadable"], totals["duplicates_skipped"],
        )

    try:
        stamp_path.write_text(json.dumps({
            **signature,
            "patients": result["patients"],
            "studies": result["studies"],
            "series": totals["series"],
            "instances_added": totals["instances_added"],
        }), encoding="utf-8")
    except OSError:
        pass

    _log.info(
        "DICOMDIR: OK — patients=%s studies=%s series=%s instances=%s under %s",
        result["patients"], result["studies"], totals["series"],
        totals["instances_added"], interchange_root,
    )
    return result


def export_studies_to_offline_cloud(
    server: dict[str, Any],
    study_uids: list[str],
    *,
    actor: dict[str, Any] | None = None,
    source_server: dict[str, Any] | None = None,
    operation: str = "export",
    include_dicomdir: bool = False,
    series_selection: "SeriesSelection | None" = None,
) -> dict[str, Any]:
    """Export studies into an Offline-Cloud package.

    ``include_dicomdir`` (default **False**) additionally writes a
    standards-compliant DICOMDIR + PT/ST/SE/IM tree at the package root so
    third-party viewers/PACS can import the media. It is OFF by default so the
    cloud-consultation / education packages (which are uploaded) stay exactly as
    they are; the Offline-Sync call site turns it on.

    ``series_selection`` (default **None** = every series) is a
    ``{study_uid: {series_number, ...}}`` map to export only SOME series of a
    study. The filter is applied to the package.db series/instance rows, the
    copied DICOM folders, and (via rebuild) the DICOMDIR — so all three stay
    consistent. A study absent from the map keeps all its series.
    """
    selected_uids = sorted({str(uid or "").strip() for uid in study_uids if str(uid or "").strip()})
    if not selected_uids:
        return {"ok": False, "exported": 0, "errors": ["No study selected."]}

    paths = package_paths(server.get("folder_path", ""))
    for key in ("root", "dicom", "attachments", "thumbnails"):
        paths[key].mkdir(parents=True, exist_ok=True)

    with _connect(DATABASE_FILE) as source_conn, _connect(paths["database"]) as package_conn:
        _ensure_package_schema(source_conn, package_conn)

        exported: list[str] = []
        errors: list[str] = []
        series_summaries: list[dict[str, Any]] = []
        for study_uid in selected_uids:
            try:
                summary = _export_single_study(
                    source_conn, package_conn, paths, study_uid,
                    series_selection=series_selection,
                )
                exported.append(study_uid)
                if isinstance(summary, dict):
                    series_summaries.append(summary)
            except Exception as exc:
                errors.append(f"{study_uid}: {exc}")
        package_conn.commit()

    # DICOMDIR is generated AFTER the final export structure is written, so its
    # File IDs always match what is actually on disk.
    dicomdir_result: dict[str, Any] | None = None
    if include_dicomdir and exported:
        dicomdir_result = build_offline_cloud_dicomdir(paths["root"])
        if not dicomdir_result.get("ok"):
            # Never silently produce an export that a third-party viewer cannot
            # import — surface the exact cause.
            errors.append(
                "DICOMDIR generation failed: "
                + str(dicomdir_result.get("error") or "see log for details")
            )

    manifest = rebuild_offline_cloud_manifest(
        paths["root"],
        actor=actor,
        source_server=source_server,
        changed_studies=exported,
        operation=operation,
    )
    result: dict[str, Any] = {
        "ok": len(exported) > 0,
        "exported": len(exported),
        "study_uids": exported,
        "errors": errors,
        "manifest_path": str(paths["manifest"]),
        "study_count": int(manifest.get("study_count") or 0),
        "series_summaries": series_summaries,
    }
    if dicomdir_result is not None:
        result["dicomdir"] = dicomdir_result
    _log.info(
        "Offline export: studies=%s errors=%s dicomdir=%s",
        len(exported), len(errors),
        (dicomdir_result or {}).get("ok") if dicomdir_result is not None else "not requested",
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# OFFLINE-PACKAGE MANAGEMENT — list / delete (P1, 2026-07-21)
#
# Turns the export-only Offline Service into a package manager. These are thin
# orchestrations over the SAME primitives export/import already use
# (_delete_rows_for_study, build_offline_cloud_dicomdir, rebuild_offline_cloud_
# manifest, validate_offline_cloud_package) — nothing here forks the engine.
#
# INVARIANTS:
#   * study_uid is the identity; patient-level delete = delete ALL that
#     patient's studies, then prune the now-orphan patient row.
#   * DESTRUCTIVE OPS ARE RECOVERABLE: package.db + manifest.json are snapshotted
#     and the removed study folders are MOVED (not unlinked) into <root>/.trash/
#     <ts>/ before anything else, so a delete can be undone and a mid-operation
#     failure auto-rolls-back.
#   * EVERY delete ends with rebuild(DICOMDIR + manifest) + validate; a package
#     that does not validate as complete is ROLLED BACK.
#   * UIDs are never touched (delete only removes; it never rewrites identity).
# ─────────────────────────────────────────────────────────────────────────────

_TRASH_DIRNAME = ".trash"


def list_offline_cloud_patients(server: dict[str, Any]) -> list[dict[str, Any]]:
    """Patients currently stored in a package, grouped for the manage UI.

    Reads ``package.db`` (the authority for what is actually in the package) and
    returns one row per patient with a study/image summary. A patient row with
    no studies is skipped (it would be an orphan). Never raises — a broken
    package returns ``[]`` so the UI degrades gracefully."""
    try:
        paths = package_paths(server.get("folder_path", ""))
        if not paths["database"].exists():
            return []
        out: list[dict[str, Any]] = []
        with _connect(paths["database"]) as conn:
            if not _has_table(conn, "patients") or not _has_table(conn, "studies"):
                return []
            for p in _fetch_all(conn, "SELECT * FROM patients"):
                pk = p.get("patient_pk")
                studies = _fetch_all(
                    conn,
                    "SELECT study_uid, study_date, study_time, modality, "
                    "number_of_series, number_of_instances "
                    "FROM studies WHERE patient_fk = ?",
                    (pk,),
                )
                if not studies:
                    continue  # orphan patient — do not present
                study_uids = [str(s.get("study_uid") or "").strip() for s in studies]
                study_uids = [u for u in study_uids if u]
                dates = sorted(
                    (str(s.get("study_date") or "").strip() for s in studies
                     if str(s.get("study_date") or "").strip()),
                    reverse=True,
                )
                modalities = sorted({
                    str(s.get("modality") or "").strip().upper()
                    for s in studies if str(s.get("modality") or "").strip()
                })
                out.append({
                    "patient_pk": pk,
                    "patient_id": str(p.get("patient_id") or "").strip(),
                    "patient_name": str(p.get("patient_name") or "").strip(),
                    "study_count": len(studies),
                    "image_count": sum(int(s.get("number_of_instances") or 0) for s in studies),
                    "series_count": sum(int(s.get("number_of_series") or 0) for s in studies),
                    "study_uids": study_uids,
                    "latest_study_date": dates[0] if dates else "",
                    "modalities": modalities,
                })
        out.sort(key=lambda r: (r.get("latest_study_date") or "", r.get("patient_name") or ""), reverse=True)
        return out
    except Exception:
        _log.debug("[OFFLINE-MANAGE] list patients failed", exc_info=True)
        return []


def _package_validation(root: str | Path) -> tuple[bool, dict[str, Any]]:
    """(is_complete, manifest-with-validation). Rewrites the manifest."""
    res = validate_offline_cloud_package(root, rewrite_manifest=True)
    if isinstance(res, dict):
        v = res.get("validation")
        if isinstance(v, dict):
            return bool(v.get("is_complete")), res
        return bool(res.get("is_complete")), res
    return False, {}


def remove_studies_from_offline_cloud(
    server: dict[str, Any],
    study_uids: list[str],
    *,
    actor: dict[str, Any] | None = None,
    operation: str = "delete",
) -> dict[str, Any]:
    """Remove studies from a package: DB rows + on-disk folders + orphan patient
    rows, then rebuild DICOMDIR + manifest and validate. Recoverable + atomic.

    The building block for patient-level delete. Returns
    ``{ok, removed, removed_study_uids, removed_patient_ids, trash_dir,
    validation, errors}``."""
    uids = sorted({str(u or "").strip() for u in study_uids if str(u or "").strip()})
    if not uids:
        return {"ok": False, "removed": 0, "errors": ["No study selected."]}

    paths = package_paths(server.get("folder_path", ""))
    root = paths["root"]
    if not paths["database"].exists():
        return {"ok": False, "removed": 0, "errors": ["Package database not found."]}

    # 1. Snapshot db + manifest into the trash BEFORE touching anything.
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    trash = root / _TRASH_DIRNAME / f"delete_{ts}"
    trash.mkdir(parents=True, exist_ok=True)
    backup_db = trash / PACKAGE_DB_NAME
    backup_manifest = trash / MANIFEST_NAME
    try:
        shutil.copy2(paths["database"], backup_db)
        if paths["manifest"].exists():
            shutil.copy2(paths["manifest"], backup_manifest)
    except Exception as exc:
        return {"ok": False, "removed": 0,
                "errors": [f"Could not back up the package before deleting: {exc}"]}

    moved_folders: list[tuple[Path, Path]] = []  # (original, trash_dest) for rollback
    removed_patient_ids: list[str] = []
    try:
        # 2. Delete DB rows (study→series→instances + AI tables) and prune orphan
        #    patients (no remaining studies).
        with _connect(paths["database"]) as conn:
            affected_pks: set[Any] = set()
            for uid in uids:
                row = _fetch_one(conn, "SELECT patient_fk FROM studies WHERE study_uid = ?", (uid,))
                if row and row.get("patient_fk") is not None:
                    affected_pks.add(row["patient_fk"])
                _delete_rows_for_study(conn, uid)  # existing cascade
            for pk in affected_pks:
                still = _fetch_one(conn, "SELECT 1 FROM studies WHERE patient_fk = ? LIMIT 1", (pk,))
                if not still:
                    prow = _fetch_one(conn, "SELECT patient_id FROM patients WHERE patient_pk = ?", (pk,))
                    if prow and str(prow.get("patient_id") or "").strip():
                        removed_patient_ids.append(str(prow["patient_id"]).strip())
                    conn.execute("DELETE FROM patients WHERE patient_pk = ?", (pk,))
            conn.commit()

        # 3. MOVE (not delete) the on-disk study folders into the trash.
        for uid in uids:
            for key in ("dicom", "attachments", "thumbnails"):
                folder = paths[key] / uid
                if folder.exists():
                    dest = trash / key / uid
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(folder), str(dest))
                    moved_folders.append((folder, dest))

        # 4. Rebuild the interchange tree. A now-EMPTY package is valid, not a
        #    failure — clear the DICOM/ tree instead of building an empty one.
        if _count_files(paths["dicom"]) > 0:
            dicomdir_result = build_offline_cloud_dicomdir(root, force=True)
            if not dicomdir_result.get("ok"):
                raise RuntimeError(
                    "DICOMDIR rebuild failed: " + str(dicomdir_result.get("error") or "unknown"))
        else:
            _clear_previous_dicomdir(root)
            dicomdir_result = {"ok": True, "skipped": True, "empty_package": True}

        # 5. Rebuild manifest from the (now smaller) DB and validate.
        rebuild_offline_cloud_manifest(
            root, actor=actor, changed_studies=uids, operation=operation)
        is_complete, validation = _package_validation(root)
        if not is_complete:
            raise RuntimeError("Post-delete validation did not report a complete package.")

        _log.info("[OFFLINE-MANAGE] removed studies=%s patients=%s trash=%s",
                  len(uids), len(removed_patient_ids), trash)
        return {
            "ok": True,
            "removed": len(uids),
            "removed_study_uids": uids,
            "removed_patient_ids": removed_patient_ids,
            "trash_dir": str(trash),
            "dicomdir": dicomdir_result,
            "validation": validation.get("validation") if isinstance(validation, dict) else None,
        }
    except Exception as exc:
        # ROLLBACK: restore db + manifest + moved folders, rebuild interchange.
        _log.exception("[OFFLINE-MANAGE] delete failed — rolling back")
        try:
            if backup_db.exists():
                shutil.copy2(backup_db, paths["database"])
            if backup_manifest.exists():
                shutil.copy2(backup_manifest, paths["manifest"])
            for original, dest in moved_folders:
                if dest.exists() and not original.exists():
                    original.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dest), str(original))
            if _count_files(paths["dicom"]) > 0:
                build_offline_cloud_dicomdir(root, force=True)
        except Exception:
            _log.exception("[OFFLINE-MANAGE] ROLLBACK ALSO FAILED — backup is at %s", trash)
        return {"ok": False, "removed": 0, "errors": [str(exc)], "trash_dir": str(trash),
                "rolled_back": True}


def remove_patients_from_offline_cloud(
    server: dict[str, Any],
    patient_ids: list[str],
    *,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Patient-level delete: remove every study of each given patient_id from the
    package (which prunes the patient rows), in ONE rebuild/validate pass.

    Resolves patient_ids -> their package study_uids from ``package.db`` and
    delegates to :func:`remove_studies_from_offline_cloud`."""
    wanted = [str(p or "").strip() for p in patient_ids if str(p or "").strip()]
    if not wanted:
        return {"ok": False, "removed": 0, "errors": ["No patient selected."]}

    paths = package_paths(server.get("folder_path", ""))
    if not paths["database"].exists():
        return {"ok": False, "removed": 0, "errors": ["Package database not found."]}

    study_uids: list[str] = []
    try:
        with _connect(paths["database"]) as conn:
            if not _has_table(conn, "patients") or not _has_table(conn, "studies"):
                return {"ok": False, "removed": 0, "errors": ["Package has no patient data."]}
            placeholders = ",".join("?" * len(wanted))
            rows = _fetch_all(
                conn,
                f"SELECT s.study_uid AS study_uid FROM studies s "
                f"JOIN patients p ON p.patient_pk = s.patient_fk "
                f"WHERE p.patient_id IN ({placeholders})",
                tuple(wanted),
            )
            study_uids = [str(r.get("study_uid") or "").strip() for r in rows if str(r.get("study_uid") or "").strip()]
    except Exception as exc:
        return {"ok": False, "removed": 0, "errors": [f"Could not resolve patient studies: {exc}"]}

    if not study_uids:
        return {"ok": False, "removed": 0,
                "errors": ["Selected patient(s) have no studies in the package."]}

    result = remove_studies_from_offline_cloud(
        server, study_uids, actor=actor, operation="delete_patient")
    result["requested_patient_ids"] = wanted
    return result


def sync_offline_cloud_study_preview_to_local(
    server: dict[str, Any],
    study_uid: str,
    *,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _sync_offline_cloud_study(server, study_uid, include_dicom=False, actor=actor)


def sync_offline_cloud_study_to_local(
    server: dict[str, Any],
    study_uid: str,
    *,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _sync_offline_cloud_study(server, study_uid, include_dicom=True, actor=actor)


def record_offline_cloud_sync_event(
    root: str | Path,
    *,
    event_type: str,
    actor: dict[str, Any] | None = None,
    server: dict[str, Any] | None = None,
    study_uids: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    paths = package_paths(root)
    manifest = read_offline_cloud_manifest(paths["root"])
    if manifest.get("format") != OFFLINE_CLOUD_FORMAT:
        manifest["format"] = OFFLINE_CLOUD_FORMAT
        manifest["version"] = OFFLINE_CLOUD_VERSION
        manifest["package_id"] = manifest.get("package_id") or str(uuid4())
        manifest["created_at"] = manifest.get("created_at") or _utc_now_iso()

    actor_meta = _sanitize_actor(actor)
    server_meta = _sanitize_server(server)
    event = {
        "event_type": str(event_type or "").strip() or "sync",
        "at": _utc_now_iso(),
        "actor": actor_meta,
        "server": server_meta,
        "study_uids": sorted({str(uid or "").strip() for uid in (study_uids or []) if str(uid or "").strip()}),
        "details": details or {},
    }
    sync_events = list(manifest.get("sync_events") or [])
    sync_events.append(event)
    manifest["sync_events"] = sync_events[-50:]
    manifest["timeline"] = list(manifest["sync_events"])
    manifest["actors"] = _merge_actor_lists(manifest.get("actors") or [], actor_meta)
    manifest["last_modified_by"] = actor_meta or manifest.get("last_modified_by")
    _apply_event_identity(manifest, event["event_type"], actor_meta)
    return write_offline_cloud_manifest(paths["root"], manifest)


def rebuild_offline_cloud_manifest(
    root: str | Path,
    *,
    actor: dict[str, Any] | None = None,
    source_server: dict[str, Any] | None = None,
    changed_studies: list[str] | None = None,
    operation: str = "export",
) -> dict[str, Any]:
    paths = package_paths(root)
    manifest_path = paths["manifest"]
    manifest = read_offline_cloud_manifest(paths["root"])
    package_id = str(manifest.get("package_id") or uuid4())
    created_at = manifest.get("created_at") or _utc_now_iso()
    actor_meta = _sanitize_actor(actor)
    source_meta = _sanitize_server(source_server)
    changed_uids = {str(uid or "").strip() for uid in (changed_studies or []) if str(uid or "").strip()}
    export_timestamp = _utc_now_iso()
    reuse_unchanged_entries = operation != "rebuild_manifest"
    study_meta_map = {
        str(study.get("study_uid") or ""): study
        for study in manifest.get("studies", [])
        if isinstance(study, dict) and str(study.get("study_uid") or "").strip()
    }

    studies_payload: list[dict[str, Any]] = []
    if paths["database"].exists():
        with _connect(paths["database"]) as conn:
            study_rows = _fetch_all(
                conn,
                "SELECT * FROM studies ORDER BY COALESCE(study_date, ''), COALESCE(study_time, ''), study_uid",
            )
            patient_rows_by_pk: dict[Any, dict[str, Any]] = {}
            series_numbers_by_study_fk: dict[Any, list[Any]] = {}

            patient_fks = sorted({row.get("patient_fk") for row in study_rows if row.get("patient_fk") is not None})
            if patient_fks and _has_table(conn, "patients"):
                placeholders = ", ".join("?" for _ in patient_fks)
                patient_rows = _fetch_all(
                    conn,
                    f"SELECT * FROM patients WHERE patient_pk IN ({placeholders})",
                    tuple(patient_fks),
                )
                patient_rows_by_pk = {row.get("patient_pk"): row for row in patient_rows}

            study_pks = sorted({row.get("study_pk") for row in study_rows if row.get("study_pk") is not None})
            if study_pks and _has_table(conn, "series"):
                placeholders = ", ".join("?" for _ in study_pks)
                series_rows = _fetch_all(
                    conn,
                    f"SELECT study_fk, series_number FROM series WHERE study_fk IN ({placeholders}) ORDER BY study_fk, series_number",
                    tuple(study_pks),
                )
                for row in series_rows:
                    study_fk = row.get("study_fk")
                    if study_fk is None:
                        continue
                    series_numbers_by_study_fk.setdefault(study_fk, []).append(row.get("series_number"))

            for study_row in study_rows:
                study_uid = str(study_row.get("study_uid") or "")
                if not study_uid:
                    continue
                previous_meta = study_meta_map.get(study_uid, {})
                if reuse_unchanged_entries and study_uid not in changed_uids and previous_meta:
                    studies_payload.append(previous_meta)
                    continue

                patient_row = patient_rows_by_pk.get(study_row.get("patient_fk"), {})
                series_numbers = list(series_numbers_by_study_fk.get(study_row.get("study_pk"), []))
                relative_paths = {
                    "dicom": f"patients/dicom/{study_uid}",
                    "attachments": f"patients/attachments/{study_uid}",
                    "thumbnails": f"patients/thumbnails/{study_uid}",
                }
                dicom_dir = paths["root"] / relative_paths["dicom"]
                attachments_dir = paths["root"] / relative_paths["attachments"]
                thumbnails_dir = paths["root"] / relative_paths["thumbnails"]

                sync_payload = {
                    "study_uid": study_uid,
                    "patient_id": patient_row.get("patient_id"),
                    "study_date": study_row.get("study_date"),
                    "study_time": study_row.get("study_time"),
                    "report_status": study_row.get("reportStatus"),
                    "visit_status": study_row.get("visit_status"),
                    "series_numbers": series_numbers,
                    "file_counts": {
                        "dicom": _count_files(dicom_dir),
                        "attachments": _count_files(attachments_dir),
                        "thumbnails": _count_files(thumbnails_dir),
                    },
                    "latest_file_mtime": _latest_mtime_iso(dicom_dir, attachments_dir, thumbnails_dir),
                }
                previous_provenance = previous_meta.get("provenance") or {}
                origin_server = previous_provenance.get("origin_server") or manifest.get("origin_server") or source_meta
                created_by = previous_provenance.get("created_by") or manifest.get("created_by") or actor_meta
                last_modified_by = previous_provenance.get("last_modified_by")
                if study_uid in changed_uids and actor_meta:
                    last_modified_by = actor_meta
                studies_payload.append(
                    {
                        "study_uid": study_uid,
                        "patient_id": str(patient_row.get("patient_id") or ""),
                        "patient_name": str(patient_row.get("patient_name") or ""),
                        "study_date": str(study_row.get("study_date") or ""),
                        "study_time": str(study_row.get("study_time") or ""),
                        "study_description": str(study_row.get("study_description") or ""),
                        "modality": str(study_row.get("modality") or ""),
                        "body_part": str(study_row.get("body_part") or ""),
                        "number_of_series": int(study_row.get("number_of_series") or 0),
                        "number_of_instances": int(study_row.get("number_of_instances") or 0),
                        "report_status": str(study_row.get("reportStatus") or "pending"),
                        "visit_status": study_row.get("visit_status"),
                        "package_paths": relative_paths,
                        "provenance": {
                            "origin_server": origin_server,
                            "created_by": created_by,
                            "last_modified_by": last_modified_by,
                            "last_operation": operation,
                        },
                        "sync": {
                            **sync_payload,
                            "record_hash": _stable_hash(sync_payload),
                            "last_exported_at": export_timestamp,
                            "last_exported_by": actor_meta or previous_meta.get("sync", {}).get("last_exported_by"),
                        },
                    }
                )

    actors = _merge_actor_lists(manifest.get("actors") or [], actor_meta)
    sync_events = list(manifest.get("sync_events") or [])
    if changed_uids or operation == "rebuild_manifest":
        sync_events.append(
            _build_timeline_event(
                event_type=operation,
                actor=actor_meta,
                server=source_meta or manifest.get("origin_server"),
                study_uids=sorted(changed_uids),
            )
        )
        sync_events = sync_events[-50:]

    manifest_payload = {
        "format": OFFLINE_CLOUD_FORMAT,
        "version": OFFLINE_CLOUD_VERSION,
        "package_id": package_id,
        "created_at": created_at,
        "updated_at": _utc_now_iso(),
        "origin_server": manifest.get("origin_server") or source_meta,
        "hub_user": manifest.get("hub_user"),
        "last_imported_by": manifest.get("last_imported_by"),
        "last_applied_by": manifest.get("last_applied_by"),
        "created_by": manifest.get("created_by") or actor_meta,
        "last_modified_by": actor_meta or manifest.get("last_modified_by"),
        "actors": actors,
        "timeline": sync_events,
        "sync_events": sync_events,
        "study_count": len(studies_payload),
        "studies": studies_payload,
    }
    _apply_event_identity(manifest_payload, operation, actor_meta)
    return write_offline_cloud_manifest(manifest_path.parent, manifest_payload)


def _sync_offline_cloud_study(
    server: dict[str, Any],
    study_uid: str,
    *,
    include_dicom: bool,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    study_uid = str(study_uid or "").strip()
    if not study_uid:
        return {"ok": False, "error": "Missing study UID."}

    validation = validate_offline_cloud_package(server.get("folder_path", ""))
    validation_state = validation.get("validation") or {}
    if validation.get("format") != OFFLINE_CLOUD_FORMAT:
        return {"ok": False, "error": "Offline Cloud manifest.json is missing or invalid."}
    if not validation_state.get("database_present"):
        return {"ok": False, "error": "Offline Cloud package.db is missing."}
    if not validation_state.get("is_complete"):
        missing_text = "\n".join((validation_state.get("missing_items") or [])[:6])
        return {
            "ok": False,
            "error": "Offline Cloud package is incomplete.\n" + (missing_text or "Check manifest.json validation."),
        }

    info = get_offline_cloud_study_info(server, study_uid)
    if not info:
        return {"ok": False, "error": f"Study {study_uid} not found in offline cloud package."}

    paths = info["paths"]
    with _connect(paths["database"]) as package_conn, _connect(DATABASE_FILE) as local_conn:
        local_conn.execute("PRAGMA foreign_keys = ON")
        _import_single_study(package_conn, local_conn, paths, study_uid, include_dicom=include_dicom)
        local_conn.commit()

    try:
        record_offline_cloud_sync_event(
            paths["root"],
            event_type="import_to_local" if include_dicom else "preview_to_local",
            actor=actor,
            server=_sanitize_server(server),
            study_uids=[study_uid],
            details={"include_dicom": include_dicom},
        )
    except Exception:
        pass

    return {
        "ok": True,
        "study_uid": study_uid,
        "study_path": str(DICOM_IMAGES_DIR / study_uid),
        "thumbnail_path": str(THUMBNAILS_DIR / study_uid),
        "attachments_path": str(ATTACHMENTS_DIR / study_uid),
        "include_dicom": include_dicom,
    }


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _ensure_package_schema(source_conn: sqlite3.Connection, package_conn: sqlite3.Connection) -> None:
    package_conn.execute("PRAGMA foreign_keys = ON")
    for table in _RELEVANT_TABLES:
        if not _has_table(source_conn, table):
            continue
        row = source_conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if row and row[0]:
            if not _has_table(package_conn, table):
                package_conn.execute(row[0])
            source_cols = source_conn.execute(f"PRAGMA table_info({table})").fetchall()
            package_cols = {str(item[1]) for item in package_conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for col in source_cols:
                col_name = str(col[1])
                if col_name in package_cols:
                    continue
                col_type = str(col[2] or "TEXT")
                default_sql = ""
                if col[4] is not None:
                    default_sql = f" DEFAULT {col[4]}"
                package_conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}{default_sql}"
                )
    package_conn.commit()


def _fetch_one(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def _fetch_all(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _has_table(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _upsert_row(
    conn: sqlite3.Connection,
    table: str,
    row: dict[str, Any],
    *,
    unique_col: str,
    pk_col: str | None = None,
) -> int | None:
    columns = _table_columns(conn, table)
    payload = {k: v for k, v in row.items() if k in columns}
    if unique_col not in payload or payload.get(unique_col) in (None, ""):
        return None

    existing_pk = None
    if pk_col and pk_col in columns:
        existing = conn.execute(
            f"SELECT {pk_col} FROM {table} WHERE {unique_col} = ?",
            (payload[unique_col],),
        ).fetchone()
        if existing:
            existing_pk = existing[0]

    update_payload = {k: v for k, v in payload.items() if k != pk_col}
    if existing_pk is not None:
        set_cols = [k for k in update_payload.keys() if k != unique_col]
        if set_cols:
            conn.execute(
                f"UPDATE {table} SET "
                + ", ".join(f"{col} = ?" for col in set_cols)
                + f" WHERE {unique_col} = ?",
                tuple(update_payload[col] for col in set_cols) + (update_payload[unique_col],),
            )
        return int(existing_pk)

    insert_cols = list(update_payload.keys())
    conn.execute(
        f"INSERT INTO {table} ({', '.join(insert_cols)}) VALUES ({', '.join('?' for _ in insert_cols)})",
        tuple(update_payload[col] for col in insert_cols),
    )
    if pk_col and pk_col in columns:
        row_obj = conn.execute(
            f"SELECT {pk_col} FROM {table} WHERE {unique_col} = ?",
            (update_payload[unique_col],),
        ).fetchone()
        if row_obj:
            return int(row_obj[0])
    return None


def _delete_rows_for_study(conn: sqlite3.Connection, study_uid: str) -> None:
    if _has_table(conn, "studies"):
        study_row = _fetch_one(conn, "SELECT study_pk FROM studies WHERE study_uid = ?", (study_uid,))
        if study_row:
            if _has_table(conn, "series"):
                series_rows = _fetch_all(conn, "SELECT series_pk FROM series WHERE study_fk = ?", (study_row["study_pk"],))
                if _has_table(conn, "instances"):
                    for series_row in series_rows:
                        conn.execute("DELETE FROM instances WHERE series_fk = ?", (series_row["series_pk"],))
                conn.execute("DELETE FROM series WHERE study_fk = ?", (study_row["study_pk"],))
            conn.execute("DELETE FROM studies WHERE study_uid = ?", (study_uid,))

    if _has_table(conn, "ai_sessions"):
        session_rows = _fetch_all(conn, "SELECT sid FROM ai_sessions WHERE study_uid = ?", (study_uid,))
        session_ids = [row["sid"] for row in session_rows if row.get("sid")]
        if _has_table(conn, "ai_messages"):
            for sid in session_ids:
                conn.execute("DELETE FROM ai_messages WHERE sid = ?", (sid,))
        if _has_table(conn, "ai_reports"):
            for sid in session_ids:
                conn.execute("DELETE FROM ai_reports WHERE sid = ?", (sid,))
            conn.execute("DELETE FROM ai_reports WHERE study_uid = ?", (study_uid,))
        conn.execute("DELETE FROM ai_sessions WHERE study_uid = ?", (study_uid,))

    if _has_table(conn, "ai_last_session"):
        conn.execute("DELETE FROM ai_last_session WHERE study_uid = ?", (study_uid,))
    if _has_table(conn, "ai_reception_reports"):
        conn.execute("DELETE FROM ai_reception_reports WHERE study_uid = ?", (study_uid,))
    if _has_table(conn, "download_progress"):
        conn.execute("DELETE FROM download_progress WHERE study_uid = ?", (study_uid,))


def _export_single_study(
    source_conn: sqlite3.Connection,
    package_conn: sqlite3.Connection,
    package_root_paths: dict[str, Path],
    study_uid: str,
    *,
    series_selection: "SeriesSelection | None" = None,
) -> dict[str, Any]:
    study_row = _fetch_one(source_conn, "SELECT * FROM studies WHERE study_uid = ?", (study_uid,))
    if not study_row:
        raise ValueError("Study does not exist in local database.")

    patient_row = _fetch_one(
        source_conn,
        "SELECT * FROM patients WHERE patient_pk = ?",
        (study_row.get("patient_fk"),),
    )
    if not patient_row:
        raise ValueError("Patient row is missing for this study.")

    local_study_dir = DICOM_IMAGES_DIR / study_uid
    if not local_study_dir.exists():
        raise ValueError("Study is not available locally and cannot be exported.")

    # None → keep all series (byte-identical legacy). Otherwise the normalized
    # set of series numbers the user ticked for THIS study.
    keep_series = _selected_series_for(study_uid, series_selection)
    summary = {"study_uid": study_uid, "series_kept": 0, "series_skipped": 0, "instances": 0}

    _delete_rows_for_study(package_conn, study_uid)

    package_patient_pk = _upsert_row(
        package_conn,
        "patients",
        patient_row,
        unique_col="patient_id",
        pk_col="patient_pk",
    )

    study_export = dict(study_row)
    study_export["patient_fk"] = package_patient_pk
    study_export["study_path"] = _rewrite_path(study_row.get("study_path"), to_package=True)
    study_export["attachments_uploaded"] = _rewrite_attachment_list(study_row.get("attachments_uploaded"), to_package=True)
    study_export["filming_folder_path"] = _rewrite_path(study_row.get("filming_folder_path"), to_package=True)
    package_study_pk = _upsert_row(
        package_conn,
        "studies",
        study_export,
        unique_col="study_uid",
        pk_col="study_pk",
    )

    series_rows = _fetch_all(source_conn, "SELECT * FROM series WHERE study_fk = ? ORDER BY series_number", (study_row["study_pk"],))
    for series_row in series_rows:
        if keep_series is not None and _normalize_series_number(series_row.get("series_number")) not in keep_series:
            summary["series_skipped"] += 1
            continue  # deselected series → no DB rows, no files (see copy below)
        summary["series_kept"] += 1
        exported_series = dict(series_row)
        exported_series["study_fk"] = package_study_pk
        exported_series["thumbnail_path"] = _rewrite_path(series_row.get("thumbnail_path"), to_package=True)
        exported_series["series_path"] = _rewrite_path(series_row.get("series_path"), to_package=True)
        package_series_pk = _upsert_row(
            package_conn,
            "series",
            exported_series,
            unique_col="series_uid",
            pk_col="series_pk",
        )

        instance_rows = _fetch_all(
            source_conn,
            "SELECT * FROM instances WHERE series_fk = ? ORDER BY instance_number, instance_pk",
            (series_row["series_pk"],),
        )
        for instance_row in instance_rows:
            exported_instance = dict(instance_row)
            exported_instance["series_fk"] = package_series_pk
            exported_instance["instance_path"] = _rewrite_path(instance_row.get("instance_path"), to_package=True)
            _upsert_row(
                package_conn,
                "instances",
                exported_instance,
                unique_col="sop_uid",
                pk_col="instance_pk",
            )
            summary["instances"] += 1

    dp_row = None
    if _has_table(source_conn, "download_progress") and _has_table(package_conn, "download_progress"):
        dp_row = _fetch_one(source_conn, "SELECT * FROM download_progress WHERE study_uid = ?", (study_uid,))
    if dp_row:
        _upsert_row(package_conn, "download_progress", dp_row, unique_col="study_uid", pk_col="progress_pk")

    session_rows: list[dict[str, Any]] = []
    message_id_map: dict[int, int] = {}
    if _has_table(source_conn, "ai_sessions") and _has_table(package_conn, "ai_sessions"):
        session_rows = _fetch_all(source_conn, "SELECT * FROM ai_sessions WHERE study_uid = ?", (study_uid,))
        for session_row in session_rows:
            _upsert_row(package_conn, "ai_sessions", session_row, unique_col="sid", pk_col=None)
            if not (_has_table(source_conn, "ai_messages") and _has_table(package_conn, "ai_messages")):
                continue
            message_rows = _fetch_all(
                source_conn,
                "SELECT * FROM ai_messages WHERE sid = ? ORDER BY COALESCE(created_at, ts, 0), id",
                (session_row["sid"],),
            )
            for message_row in message_rows:
                columns = _table_columns(package_conn, "ai_messages")
                payload = {k: v for k, v in message_row.items() if k in columns and k != "id"}
                if not payload:
                    continue
                insert_cols = list(payload.keys())
                cur = package_conn.execute(
                    f"INSERT INTO ai_messages ({', '.join(insert_cols)}) VALUES ({', '.join('?' for _ in insert_cols)})",
                    tuple(payload[col] for col in insert_cols),
                )
                old_id = message_row.get("id")
                if old_id is not None:
                    message_id_map[int(old_id)] = int(cur.lastrowid)

    if _has_table(source_conn, "ai_reports") and _has_table(package_conn, "ai_reports"):
        report_rows = _fetch_all(
            source_conn,
            "SELECT * FROM ai_reports WHERE study_uid = ? ORDER BY COALESCE(created_at, 0), id",
            (study_uid,),
        )
        for report_row in report_rows:
            columns = _table_columns(package_conn, "ai_reports")
            payload = {k: v for k, v in report_row.items() if k in columns and k != "id"}
            if not payload:
                continue
            if payload.get("msg_id") in message_id_map:
                payload["msg_id"] = message_id_map[int(payload["msg_id"])]
            insert_cols = list(payload.keys())
            package_conn.execute(
                f"INSERT INTO ai_reports ({', '.join(insert_cols)}) VALUES ({', '.join('?' for _ in insert_cols)})",
                tuple(payload[col] for col in insert_cols),
            )

    last_session_row = None
    if _has_table(source_conn, "ai_last_session") and _has_table(package_conn, "ai_last_session"):
        last_session_row = _fetch_one(source_conn, "SELECT * FROM ai_last_session WHERE study_uid = ?", (study_uid,))
    if last_session_row:
        _upsert_row(package_conn, "ai_last_session", last_session_row, unique_col="study_uid", pk_col=None)

    if _has_table(source_conn, "ai_reception_reports") and _has_table(package_conn, "ai_reception_reports"):
        patient_id = patient_row.get("patient_id")
        reception_rows = _fetch_all(
            source_conn,
            "SELECT * FROM ai_reception_reports WHERE study_uid = ? OR patient_id = ? ORDER BY created_at, id",
            (study_uid, patient_id),
        )
        for reception_row in reception_rows:
            columns = _table_columns(package_conn, "ai_reception_reports")
            payload = {k: v for k, v in reception_row.items() if k in columns and k != "id"}
            if not payload:
                continue
            insert_cols = list(payload.keys())
            package_conn.execute(
                f"INSERT INTO ai_reception_reports ({', '.join(insert_cols)}) VALUES ({', '.join('?' for _ in insert_cols)})",
                tuple(payload[col] for col in insert_cols),
            )

    # Translate the kept series NUMBERS into the actual on-disk subfolder names.
    # Folder names are the series number, but tolerate leading-zero / int-vs-str
    # differences by normalizing both sides. None → copy the whole study tree.
    allowed_dirs: "set[str] | None" = None
    if keep_series is not None:
        allowed_dirs = set()
        for child in local_study_dir.iterdir():
            if child.is_dir() and _normalize_series_number(child.name) in keep_series:
                allowed_dirs.add(child.name)

    _copy_tree_replace(local_study_dir, package_root_paths["dicom"] / study_uid, allowed_top_dirs=allowed_dirs)
    _copy_tree_replace(ATTACHMENTS_DIR / study_uid, package_root_paths["attachments"] / study_uid)
    _copy_tree_replace(THUMBNAILS_DIR / study_uid, package_root_paths["thumbnails"] / study_uid)
    return summary


def _import_single_study(
    package_conn: sqlite3.Connection,
    local_conn: sqlite3.Connection,
    package_root_paths: dict[str, Path],
    study_uid: str,
    *,
    include_dicom: bool,
) -> None:
    study_row = _fetch_one(package_conn, "SELECT * FROM studies WHERE study_uid = ?", (study_uid,))
    if not study_row:
        raise ValueError("Study is missing from package database.")

    patient_row = _fetch_one(
        package_conn,
        "SELECT * FROM patients WHERE patient_pk = ?",
        (study_row.get("patient_fk"),),
    ) or {}

    local_patient_pk = _upsert_row(
        local_conn,
        "patients",
        patient_row,
        unique_col="patient_id",
        pk_col="patient_pk",
    )

    imported_study = dict(study_row)
    imported_study["patient_fk"] = local_patient_pk
    imported_study["study_path"] = str(DICOM_IMAGES_DIR / study_uid)
    imported_study["attachments_uploaded"] = _rewrite_attachment_list(study_row.get("attachments_uploaded"), to_package=False)
    imported_study["filming_folder_path"] = _rewrite_path(study_row.get("filming_folder_path"), to_package=False)
    local_study_pk = _upsert_row(
        local_conn,
        "studies",
        imported_study,
        unique_col="study_uid",
        pk_col="study_pk",
    )

    if include_dicom:
        _copy_tree_replace(package_root_paths["dicom"] / study_uid, DICOM_IMAGES_DIR / study_uid)
    _copy_tree_replace(package_root_paths["attachments"] / study_uid, ATTACHMENTS_DIR / study_uid)
    _copy_tree_replace(package_root_paths["thumbnails"] / study_uid, THUMBNAILS_DIR / study_uid)

    series_rows = _fetch_all(package_conn, "SELECT * FROM series WHERE study_fk = ? ORDER BY series_number", (study_row["study_pk"],))
    for series_row in series_rows:
        imported_series = dict(series_row)
        imported_series["study_fk"] = local_study_pk
        imported_series["thumbnail_path"] = _rewrite_path(series_row.get("thumbnail_path"), to_package=False)
        imported_series["series_path"] = _rewrite_path(series_row.get("series_path"), to_package=False)
        local_series_pk = _upsert_row(
            local_conn,
            "series",
            imported_series,
            unique_col="series_uid",
            pk_col="series_pk",
        )

        instance_rows = _fetch_all(package_conn, "SELECT * FROM instances WHERE series_fk = ? ORDER BY instance_number, instance_pk", (series_row["series_pk"],))
        for instance_row in instance_rows:
            imported_instance = dict(instance_row)
            imported_instance["series_fk"] = local_series_pk
            imported_instance["instance_path"] = _rewrite_path(instance_row.get("instance_path"), to_package=False)
            _upsert_row(
                local_conn,
                "instances",
                imported_instance,
                unique_col="sop_uid",
                pk_col="instance_pk",
            )

    dp_row = None
    if _has_table(package_conn, "download_progress") and _has_table(local_conn, "download_progress"):
        dp_row = _fetch_one(package_conn, "SELECT * FROM download_progress WHERE study_uid = ?", (study_uid,))
    if dp_row:
        _upsert_row(local_conn, "download_progress", dp_row, unique_col="study_uid", pk_col="progress_pk")

    session_rows: list[dict[str, Any]] = []
    session_ids: list[Any] = []

    if _has_table(package_conn, "ai_sessions") and _has_table(local_conn, "ai_sessions"):
        session_rows = _fetch_all(package_conn, "SELECT * FROM ai_sessions WHERE study_uid = ?", (study_uid,))
        session_ids = [row["sid"] for row in session_rows if row.get("sid")]
        for session_row in session_rows:
            _upsert_row(local_conn, "ai_sessions", session_row, unique_col="sid", pk_col=None)

    message_id_map: dict[int, int] = {}
    if session_ids and _has_table(package_conn, "ai_messages") and _has_table(local_conn, "ai_messages"):
        for sid in session_ids:
            local_conn.execute("DELETE FROM ai_messages WHERE sid = ?", (sid,))
            message_rows = _fetch_all(
                package_conn,
                "SELECT * FROM ai_messages WHERE sid = ? ORDER BY COALESCE(created_at, ts, 0), id",
                (sid,),
            )
            for message_row in message_rows:
                columns = _table_columns(local_conn, "ai_messages")
                payload = {k: v for k, v in message_row.items() if k in columns and k != "id"}
                insert_cols = list(payload.keys())
                cur = local_conn.execute(
                    f"INSERT INTO ai_messages ({', '.join(insert_cols)}) VALUES ({', '.join('?' for _ in insert_cols)})",
                    tuple(payload[col] for col in insert_cols),
                )
                old_id = message_row.get("id")
                if old_id is not None:
                    message_id_map[int(old_id)] = int(cur.lastrowid)

    if _has_table(package_conn, "ai_reports") and _has_table(local_conn, "ai_reports"):
        local_conn.execute("DELETE FROM ai_reports WHERE study_uid = ?", (study_uid,))
        report_rows = _fetch_all(
            package_conn,
            "SELECT * FROM ai_reports WHERE study_uid = ? ORDER BY COALESCE(created_at, 0), id",
            (study_uid,),
        )
        for report_row in report_rows:
            columns = _table_columns(local_conn, "ai_reports")
            payload = {k: v for k, v in report_row.items() if k in columns and k != "id"}
            if not payload:
                continue
            if payload.get("msg_id") in message_id_map:
                payload["msg_id"] = message_id_map[int(payload["msg_id"])]
            insert_cols = list(payload.keys())
            local_conn.execute(
                f"INSERT INTO ai_reports ({', '.join(insert_cols)}) VALUES ({', '.join('?' for _ in insert_cols)})",
                tuple(payload[col] for col in insert_cols),
            )

    last_session_row = None
    if _has_table(package_conn, "ai_last_session") and _has_table(local_conn, "ai_last_session"):
        last_session_row = _fetch_one(package_conn, "SELECT * FROM ai_last_session WHERE study_uid = ?", (study_uid,))
    if last_session_row:
        _upsert_row(local_conn, "ai_last_session", last_session_row, unique_col="study_uid", pk_col=None)

    if _has_table(package_conn, "ai_reception_reports") and _has_table(local_conn, "ai_reception_reports"):
        local_conn.execute("DELETE FROM ai_reception_reports WHERE study_uid = ?", (study_uid,))
        reception_rows = _fetch_all(
            package_conn,
            "SELECT * FROM ai_reception_reports WHERE study_uid = ? ORDER BY created_at, id",
            (study_uid,),
        )
        for reception_row in reception_rows:
            columns = _table_columns(local_conn, "ai_reception_reports")
            payload = {k: v for k, v in reception_row.items() if k in columns and k != "id"}
            if not payload:
                continue
            insert_cols = list(payload.keys())
            local_conn.execute(
                f"INSERT INTO ai_reception_reports ({', '.join(insert_cols)}) VALUES ({', '.join('?' for _ in insert_cols)})",
                tuple(payload[col] for col in insert_cols),
            )


def _copy_tree_replace(src: Path, dst: Path, *, allowed_top_dirs: "set[str] | None" = None) -> None:
    """Mirror ``src`` into ``dst``, deleting anything at ``dst`` not in ``src``.

    ``allowed_top_dirs`` (used for per-series export): when provided, only the
    named FIRST-LEVEL subdirectories of ``src`` are copied (root-level files are
    always copied). Because the stale-cleanup pass below removes any dst entry
    not seen in ``src``, a re-export with fewer series automatically drops the
    now-deselected series folders from the package — so package, package.db and
    DICOMDIR stay consistent with each other.
    """
    if not src.exists():
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.mkdir(parents=True, exist_ok=True)

    source_files: set[str] = set()
    source_dirs: set[str] = {""}

    for root, dirs, files in os.walk(src):
        root_path = Path(root)
        rel_root = root_path.relative_to(src)
        rel_root_text = "" if str(rel_root) == "." else rel_root.as_posix()

        if allowed_top_dirs is not None:
            if rel_root_text == "":
                # At the study root, do not descend into deselected series.
                dirs[:] = [d for d in dirs if d in allowed_top_dirs]
            else:
                top = rel_root.parts[0]
                if top not in allowed_top_dirs:
                    dirs[:] = []
                    continue  # skip this excluded series subtree entirely

        source_dirs.add(rel_root_text)

        target_root = dst if not rel_root_text else dst / rel_root
        target_root.mkdir(parents=True, exist_ok=True)

        for dir_name in dirs:
            rel_dir = f"{rel_root_text}/{dir_name}" if rel_root_text else dir_name
            source_dirs.add(rel_dir)
            (dst / rel_dir).mkdir(parents=True, exist_ok=True)

        for file_name in files:
            rel_file = f"{rel_root_text}/{file_name}" if rel_root_text else file_name
            source_files.add(rel_file)
            src_file = root_path / file_name
            dst_file = dst / rel_file
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            if _files_are_equivalent(src_file, dst_file):
                continue
            shutil.copy2(src_file, dst_file)

    if not dst.exists():
        return

    for root, dirs, files in os.walk(dst, topdown=False):
        root_path = Path(root)
        rel_root = root_path.relative_to(dst)
        rel_root_text = "" if str(rel_root) == "." else rel_root.as_posix()

        for file_name in files:
            rel_file = f"{rel_root_text}/{file_name}" if rel_root_text else file_name
            if rel_file in source_files:
                continue
            try:
                (root_path / file_name).unlink(missing_ok=True)
            except Exception:
                pass

        for dir_name in dirs:
            rel_dir = f"{rel_root_text}/{dir_name}" if rel_root_text else dir_name
            if rel_dir in source_dirs:
                continue
            shutil.rmtree(root_path / dir_name, ignore_errors=True)


def _files_are_equivalent(src: Path, dst: Path) -> bool:
    if not dst.exists() or not dst.is_file():
        return False
    try:
        src_stat = src.stat()
        dst_stat = dst.stat()
    except OSError:
        return False
    return (
        int(src_stat.st_size) == int(dst_stat.st_size)
        and int(src_stat.st_mtime_ns) == int(dst_stat.st_mtime_ns)
    )


def _rewrite_attachment_list(value: Any, *, to_package: bool) -> str | None:
    if not value:
        return None
    parts = [item.strip() for item in str(value).split(",") if item.strip()]
    rewritten = [_rewrite_path(item, to_package=to_package) for item in parts]
    rewritten = [item for item in rewritten if item]
    return ",".join(rewritten) if rewritten else None


def _rewrite_path(value: Any, *, to_package: bool) -> str | None:
    if not value:
        return None
    try:
        path = Path(str(value))
    except Exception:
        return None

    if to_package:
        mappings = (
            (DICOM_IMAGES_DIR, Path("patients") / "dicom"),
            (ATTACHMENTS_DIR, Path("patients") / "attachments"),
            (THUMBNAILS_DIR, Path("patients") / "thumbnails"),
        )
        for src_root, dst_root in mappings:
            try:
                rel = path.resolve().relative_to(src_root.resolve())
                return str(dst_root / rel).replace("\\", "/")
            except Exception:
                continue
        return str(path).replace("\\", "/")

    relative_text = str(value).replace("\\", "/")
    mappings = {
        "patients/dicom": DICOM_IMAGES_DIR,
        "patients/attachments": ATTACHMENTS_DIR,
        "patients/thumbnails": THUMBNAILS_DIR,
    }
    for prefix, dst_root in mappings.items():
        if relative_text == prefix:
            return str(dst_root)
        if relative_text.startswith(prefix + "/"):
            suffix = relative_text[len(prefix) + 1 :]
            return str(dst_root / Path(suffix))
    return str(path)


def _normalize_date_for_compare(value: Any) -> str:
    if value is None:
        return ""
    text = "".join(ch for ch in str(value) if ch.isdigit())
    if len(text) >= 8:
        return text[:8]
    return text


def _stable_hash(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _count_immediate_dirs(folder: Path) -> int:
    if not folder.exists():
        return 0
    try:
        return sum(1 for path in folder.iterdir() if path.is_dir())
    except OSError:
        return 0


def _count_files(folder: Path) -> int:
    if not folder.exists():
        return 0
    return sum(1 for path in folder.rglob("*") if path.is_file())


def _latest_mtime_iso(*folders: Path) -> str | None:
    latest = 0.0
    for folder in folders:
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if path.is_file():
                latest = max(latest, path.stat().st_mtime)
    if latest <= 0:
        return None
    return datetime.fromtimestamp(latest, tz=timezone.utc).replace(microsecond=0).isoformat()


def _sanitize_actor(actor: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(actor, dict):
        return None
    username = str(actor.get("username") or "").strip()
    full_name = str(actor.get("full_name") or actor.get("name") or "").strip()
    role = str(actor.get("role") or "").strip()
    user_id = str(actor.get("id") or actor.get("user_id") or "").strip()
    if not any((username, full_name, role, user_id)):
        return None
    return {
        "username": username or None,
        "full_name": full_name or None,
        "role": role or None,
        "user_id": user_id or None,
    }


def _sanitize_server(server: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(server, dict):
        return None
    name = str(server.get("name") or "").strip()
    host = str(server.get("host") or server.get("folder_path") or "").strip()
    port = str(server.get("port") or "").strip()
    ae_title = str(server.get("ae_title") or "").strip()
    server_type = str(server.get("server_type") or "").strip()
    if not any((name, host, port, ae_title, server_type)):
        return None
    return {
        "name": name or None,
        "host": host or None,
        "port": port or None,
        "ae_title": ae_title or None,
        "server_type": server_type or None,
    }


def _build_timeline_event(
    *,
    event_type: str,
    actor: dict[str, Any] | None = None,
    server: dict[str, Any] | None = None,
    study_uids: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_type": str(event_type or "").strip() or "sync",
        "at": _utc_now_iso(),
        "actor": _sanitize_actor(actor),
        "server": _sanitize_server(server),
        "study_uids": sorted({str(uid or "").strip() for uid in (study_uids or []) if str(uid or "").strip()}),
        "details": details or {},
    }


def _apply_event_identity(
    manifest: dict[str, Any],
    event_type: str,
    actor: dict[str, Any] | None,
) -> None:
    actor = _sanitize_actor(actor)
    event_type = str(event_type or "").strip().lower()
    if not actor:
        return
    if event_type in {"export_from_ai_pacs", "import_to_ai_pacs", "hub_export", "hub_import"}:
        manifest["hub_user"] = actor
    if event_type in {"import_to_local", "preview_to_local", "import_from_offline_cloud"}:
        manifest["last_imported_by"] = actor
    if event_type in {"offline_update", "manual_edit", "save_from_offline"}:
        manifest["last_applied_by"] = actor


def _merge_actor_lists(existing: list[Any], actor: dict[str, Any] | None) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(existing or []) + ([actor] if actor else []):
        clean = _sanitize_actor(item if isinstance(item, dict) else None)
        if not clean:
            continue
        key = json.dumps(clean, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        merged.append(clean)
    return merged
