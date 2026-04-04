from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

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


def export_studies_to_offline_cloud(
    server: dict[str, Any],
    study_uids: list[str],
    *,
    actor: dict[str, Any] | None = None,
    source_server: dict[str, Any] | None = None,
    operation: str = "export",
) -> dict[str, Any]:
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
        for study_uid in selected_uids:
            try:
                _export_single_study(source_conn, package_conn, paths, study_uid)
                exported.append(study_uid)
            except Exception as exc:
                errors.append(f"{study_uid}: {exc}")
        package_conn.commit()

    manifest = rebuild_offline_cloud_manifest(
        paths["root"],
        actor=actor,
        source_server=source_server,
        changed_studies=exported,
        operation=operation,
    )
    return {
        "ok": len(exported) > 0,
        "exported": len(exported),
        "study_uids": exported,
        "errors": errors,
        "manifest_path": str(paths["manifest"]),
        "study_count": int(manifest.get("study_count") or 0),
    }


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
) -> None:
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

    _copy_tree_replace(local_study_dir, package_root_paths["dicom"] / study_uid)
    _copy_tree_replace(ATTACHMENTS_DIR / study_uid, package_root_paths["attachments"] / study_uid)
    _copy_tree_replace(THUMBNAILS_DIR / study_uid, package_root_paths["thumbnails"] / study_uid)


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


def _copy_tree_replace(src: Path, dst: Path) -> None:
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
