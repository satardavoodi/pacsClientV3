"""
Offline Cloud Server Module - End-to-End Pipeline & KPI Test Suite
==================================================================

Run:
    python tests/offline_cloud_server/test_offline_cloud_server.py
    # Or via pytest:
    python -m pytest tests/offline_cloud_server/test_offline_cloud_server.py -v

This suite validates the Offline Cloud Server pipeline end-to-end:
  - receives a local study that represents data already retrieved from AI PACS
  - exports DICOM + attachments + report/admission data into an Offline Cloud package
  - validates the package manifest, package database, files, queries, and permissions
  - imports the study back from the Offline Cloud package into local storage
  - records KPI results and functional pass/fail checks

No live server connection is required. The suite uses isolated temporary storage.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import PacsClient.utils.offline_cloud as offline_cloud_impl
from modules.offline_cloud_server.service import (
    export_studies_to_offline_cloud,
    get_offline_cloud_study_info,
    list_offline_cloud_studies,
    read_offline_cloud_manifest,
    sync_offline_cloud_study_to_local,
    validate_offline_cloud_package,
)


class KPICollector:
    def __init__(self):
        self._records: List[Dict[str, Any]] = []

    def record(self, scenario: str, metric: str, value: Any, unit: str = "", passed: Optional[bool] = None):
        self._records.append(
            {
                "scenario": scenario,
                "metric": metric,
                "value": value,
                "unit": unit,
                "passed": passed,
            }
        )

    def report(self) -> str:
        lines = ["", "=" * 100, "  OFFLINE CLOUD SERVER - KPI REPORT", "=" * 100]
        scenarios: Dict[str, list] = defaultdict(list)
        for record in self._records:
            scenarios[record["scenario"]].append(record)

        total_pass = total_fail = total_info = 0
        for scenario, records in scenarios.items():
            lines.append(f"\n  +- Scenario: {scenario}")
            lines.append(f"  |{'Metric':<55} {'Value':>10} {'Unit':<8} {'Status':>8}")
            lines.append(f"  |{'-' * 84}")
            for record in records:
                if record["passed"] is True:
                    status = "  PASS"
                    total_pass += 1
                elif record["passed"] is False:
                    status = "  FAIL"
                    total_fail += 1
                else:
                    status = "  info"
                    total_info += 1
                value = record["value"]
                if isinstance(value, float):
                    rendered = f"{value:>10.3f}"
                else:
                    rendered = f"{str(value):>10}"
                lines.append(
                    f"  | {record['metric']:<54} {rendered} {record['unit']:<8}{status}"
                )
            lines.append(f"  +{'-' * 84}")

        lines += [
            "",
            "=" * 100,
            f"  TOTALS:  PASS {total_pass}   FAIL {total_fail}   info {total_info}",
            "=" * 100,
            "",
        ]
        return "\n".join(lines)

    @property
    def failed_count(self) -> int:
        return sum(1 for record in self._records if record["passed"] is False)


_kpi = KPICollector()


def _reset_kpi() -> None:
    _kpi._records.clear()


@contextmanager
def _temp_offline_cloud_env():
    root = Path(tempfile.mkdtemp(prefix="offline_cloud_test_"))
    local_root = root / "local"
    package_root = root / "offline_cloud_package"
    local_root.mkdir(parents=True, exist_ok=True)
    package_root.mkdir(parents=True, exist_ok=True)

    local_db = local_root / "dicom.db"
    dicom_dir = local_root / "patients" / "dicom"
    attachments_dir = local_root / "patients" / "attachments"
    thumbnails_dir = local_root / "patients" / "thumbnails"
    for path in (dicom_dir, attachments_dir, thumbnails_dir):
        path.mkdir(parents=True, exist_ok=True)

    original_paths = {
        "DATABASE_FILE": offline_cloud_impl.DATABASE_FILE,
        "DICOM_IMAGES_DIR": offline_cloud_impl.DICOM_IMAGES_DIR,
        "ATTACHMENTS_DIR": offline_cloud_impl.ATTACHMENTS_DIR,
        "THUMBNAILS_DIR": offline_cloud_impl.THUMBNAILS_DIR,
    }

    offline_cloud_impl.DATABASE_FILE = local_db
    offline_cloud_impl.DICOM_IMAGES_DIR = dicom_dir
    offline_cloud_impl.ATTACHMENTS_DIR = attachments_dir
    offline_cloud_impl.THUMBNAILS_DIR = thumbnails_dir

    try:
        yield {
            "root": root,
            "local_db": local_db,
            "local_dicom_dir": dicom_dir,
            "local_attachments_dir": attachments_dir,
            "local_thumbnails_dir": thumbnails_dir,
            "package_root": package_root,
            "server": {
                "name": "Offline Cloud QA",
                "folder_path": str(package_root),
                "server_type": "offline_cloud",
            },
            "actor_hub": {
                "username": "hub.user",
                "full_name": "Hub User",
                "role": "hub",
                "user_id": "hub-1",
            },
            "actor_offline": {
                "username": "offline.reader",
                "full_name": "Offline Reader",
                "role": "reporter",
                "user_id": "offline-2",
            },
            "source_server": {
                "name": "AI PACS Razi",
                "host": "razi.local",
                "port": "104",
                "ae_title": "RAZI",
                "server_type": "ai_pacs",
            },
        }
    finally:
        offline_cloud_impl.DATABASE_FILE = original_paths["DATABASE_FILE"]
        offline_cloud_impl.DICOM_IMAGES_DIR = original_paths["DICOM_IMAGES_DIR"]
        offline_cloud_impl.ATTACHMENTS_DIR = original_paths["ATTACHMENTS_DIR"]
        offline_cloud_impl.THUMBNAILS_DIR = original_paths["THUMBNAILS_DIR"]
        shutil.rmtree(root, ignore_errors=True)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _create_schema(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE patients (
                patient_pk INTEGER PRIMARY KEY,
                patient_id TEXT UNIQUE NOT NULL,
                patient_name TEXT
            );

            CREATE TABLE studies (
                study_pk INTEGER PRIMARY KEY,
                patient_fk INTEGER,
                study_uid TEXT UNIQUE NOT NULL,
                study_path TEXT,
                attachments_uploaded TEXT,
                filming_folder_path TEXT,
                study_date TEXT,
                study_time TEXT,
                study_description TEXT,
                modality TEXT,
                body_part TEXT,
                number_of_series INTEGER,
                number_of_instances INTEGER,
                reportStatus TEXT,
                visit_status TEXT
            );

            CREATE TABLE series (
                series_pk INTEGER PRIMARY KEY,
                study_fk INTEGER,
                series_uid TEXT UNIQUE NOT NULL,
                series_number INTEGER,
                thumbnail_path TEXT,
                series_path TEXT
            );

            CREATE TABLE instances (
                instance_pk INTEGER PRIMARY KEY,
                series_fk INTEGER,
                sop_uid TEXT UNIQUE NOT NULL,
                instance_number INTEGER,
                instance_path TEXT
            );

            CREATE TABLE download_progress (
                progress_pk INTEGER PRIMARY KEY,
                study_uid TEXT UNIQUE NOT NULL,
                status TEXT,
                progress_percent REAL
            );

            CREATE TABLE ai_sessions (
                sid TEXT PRIMARY KEY,
                study_uid TEXT NOT NULL,
                title TEXT
            );

            CREATE TABLE ai_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sid TEXT NOT NULL,
                role TEXT,
                content TEXT,
                created_at INTEGER,
                ts INTEGER
            );

            CREATE TABLE ai_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                study_uid TEXT NOT NULL,
                sid TEXT,
                msg_id INTEGER,
                created_at INTEGER,
                report_text TEXT
            );

            CREATE TABLE ai_last_session (
                study_uid TEXT PRIMARY KEY,
                sid TEXT
            );

            CREATE TABLE ai_reception_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                study_uid TEXT,
                patient_id TEXT,
                created_at INTEGER,
                admission_status TEXT,
                notes TEXT
            );
            """
        )
        conn.commit()


def _seed_local_study(env: dict[str, Any]) -> dict[str, str]:
    study_uid = "1.2.840.113619.2.55.3.604688435.999.20260403120000.1"
    patient_id = "P1001"
    patient_name = "Offline Cloud Patient"
    series_uid_1 = study_uid + ".101"
    series_uid_2 = study_uid + ".201"
    session_id = "session-study-1"

    dicom_root = env["local_dicom_dir"] / study_uid
    attachments_root = env["local_attachments_dir"] / study_uid
    thumbnails_root = env["local_thumbnails_dir"] / study_uid
    for path in (
        dicom_root / "101",
        dicom_root / "201",
        attachments_root / "voice",
        attachments_root / "reports",
        thumbnails_root,
    ):
        path.mkdir(parents=True, exist_ok=True)

    (dicom_root / "101" / "image_001.dcm").write_bytes(b"DICOM101-A")
    (dicom_root / "101" / "image_002.dcm").write_bytes(b"DICOM101-B")
    (dicom_root / "201" / "image_001.dcm").write_bytes(b"DICOM201-A")
    (attachments_root / "voice" / "voice_note.wav").write_bytes(b"VOICE-DATA-001")
    (attachments_root / "reports" / "final_report.txt").write_text(
        "Final report from workstation side.",
        encoding="utf-8",
    )
    (thumbnails_root / "thumb_001.png").write_bytes(b"PNGDATA")

    with _connect(env["local_db"]) as conn:
        conn.execute(
            "INSERT INTO patients (patient_pk, patient_id, patient_name) VALUES (?, ?, ?)",
            (1, patient_id, patient_name),
        )
        conn.execute(
            """
            INSERT INTO studies (
                study_pk, patient_fk, study_uid, study_path, attachments_uploaded,
                filming_folder_path, study_date, study_time, study_description,
                modality, body_part, number_of_series, number_of_instances,
                reportStatus, visit_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                1,
                study_uid,
                str(dicom_root),
                str(attachments_root / "voice" / "voice_note.wav"),
                None,
                "20260403",
                "120000",
                "Chest offline cloud workflow",
                "CT",
                "CHEST",
                2,
                3,
                "finalized",
                "downloaded",
            ),
        )
        conn.execute(
            "INSERT INTO series (series_pk, study_fk, series_uid, series_number, thumbnail_path, series_path) VALUES (?, ?, ?, ?, ?, ?)",
            (1, 1, series_uid_1, 101, str(thumbnails_root / "thumb_001.png"), str(dicom_root / "101")),
        )
        conn.execute(
            "INSERT INTO series (series_pk, study_fk, series_uid, series_number, thumbnail_path, series_path) VALUES (?, ?, ?, ?, ?, ?)",
            (2, 1, series_uid_2, 201, str(thumbnails_root / "thumb_001.png"), str(dicom_root / "201")),
        )
        conn.execute(
            "INSERT INTO instances (instance_pk, series_fk, sop_uid, instance_number, instance_path) VALUES (?, ?, ?, ?, ?)",
            (1, 1, study_uid + ".101.1", 1, str(dicom_root / "101" / "image_001.dcm")),
        )
        conn.execute(
            "INSERT INTO instances (instance_pk, series_fk, sop_uid, instance_number, instance_path) VALUES (?, ?, ?, ?, ?)",
            (2, 1, study_uid + ".101.2", 2, str(dicom_root / "101" / "image_002.dcm")),
        )
        conn.execute(
            "INSERT INTO instances (instance_pk, series_fk, sop_uid, instance_number, instance_path) VALUES (?, ?, ?, ?, ?)",
            (3, 2, study_uid + ".201.1", 1, str(dicom_root / "201" / "image_001.dcm")),
        )
        conn.execute(
            "INSERT INTO download_progress (progress_pk, study_uid, status, progress_percent) VALUES (?, ?, ?, ?)",
            (1, study_uid, "complete", 100.0),
        )
        conn.execute(
            "INSERT INTO ai_sessions (sid, study_uid, title) VALUES (?, ?, ?)",
            (session_id, study_uid, "Primary report session"),
        )
        conn.execute(
            "INSERT INTO ai_messages (sid, role, content, created_at, ts) VALUES (?, ?, ?, ?, ?)",
            (session_id, "user", "Please prepare the report.", 1712145600, 1712145600),
        )
        msg_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO ai_reports (study_uid, sid, msg_id, created_at, report_text) VALUES (?, ?, ?, ?, ?)",
            (study_uid, session_id, msg_id, 1712145660, "Impression: no acute finding."),
        )
        conn.execute(
            "INSERT INTO ai_last_session (study_uid, sid) VALUES (?, ?)",
            (study_uid, session_id),
        )
        conn.execute(
            "INSERT INTO ai_reception_reports (study_uid, patient_id, created_at, admission_status, notes) VALUES (?, ?, ?, ?, ?)",
            (study_uid, patient_id, 1712145500, "admitted", "Admission synced with package."),
        )
        conn.commit()

    return {
        "study_uid": study_uid,
        "patient_id": patient_id,
        "patient_name": patient_name,
        "voice_file_name": "voice_note.wav",
        "report_file_name": "final_report.txt",
        "session_id": session_id,
    }


def _clear_local_study(env: dict[str, Any], seeded: dict[str, str]) -> None:
    study_uid = seeded["study_uid"]
    with _connect(env["local_db"]) as conn:
        conn.execute("DELETE FROM ai_reports WHERE study_uid = ?", (study_uid,))
        conn.execute("DELETE FROM ai_messages WHERE sid IN (SELECT sid FROM ai_sessions WHERE study_uid = ?)", (study_uid,))
        conn.execute("DELETE FROM ai_sessions WHERE study_uid = ?", (study_uid,))
        conn.execute("DELETE FROM ai_last_session WHERE study_uid = ?", (study_uid,))
        conn.execute("DELETE FROM ai_reception_reports WHERE study_uid = ?", (study_uid,))
        conn.execute("DELETE FROM download_progress WHERE study_uid = ?", (study_uid,))
        conn.execute(
            "DELETE FROM instances WHERE series_fk IN (SELECT series_pk FROM series WHERE study_fk IN (SELECT study_pk FROM studies WHERE study_uid = ?))",
            (study_uid,),
        )
        conn.execute(
            "DELETE FROM series WHERE study_fk IN (SELECT study_pk FROM studies WHERE study_uid = ?)",
            (study_uid,),
        )
        conn.execute("DELETE FROM studies WHERE study_uid = ?", (study_uid,))
        conn.commit()

    shutil.rmtree(env["local_dicom_dir"] / study_uid, ignore_errors=True)
    shutil.rmtree(env["local_attachments_dir"] / study_uid, ignore_errors=True)
    shutil.rmtree(env["local_thumbnails_dir"] / study_uid, ignore_errors=True)


def scenario_export_package_pipeline() -> None:
    scenario = "OC1: Export local study to Offline Cloud package"
    with _temp_offline_cloud_env() as env:
        _create_schema(env["local_db"])
        seeded = _seed_local_study(env)

        started = time.perf_counter()
        result = export_studies_to_offline_cloud(
            env["server"],
            [seeded["study_uid"]],
            actor=env["actor_hub"],
            source_server=env["source_server"],
            operation="export_from_ai_pacs",
        )
        export_ms = (time.perf_counter() - started) * 1000

        _kpi.record(scenario, "export_studies_to_offline_cloud latency", export_ms, "ms", result.get("ok") is True)
        _kpi.record(scenario, "exported study count", int(result.get("exported", 0)), "", int(result.get("exported", 0)) == 1)
        _kpi.record(scenario, "export errors", len(result.get("errors") or []), "", len(result.get("errors") or []) == 0)

        manifest = validate_offline_cloud_package(env["package_root"])
        validation = manifest.get("validation") or {}
        _kpi.record(scenario, "package validation status", validation.get("status"), "", validation.get("status") == "ready")
        _kpi.record(scenario, "patient count", int(manifest.get("patient_count") or 0), "", int(manifest.get("patient_count") or 0) == 1)
        _kpi.record(scenario, "study count", int(manifest.get("study_count") or 0), "", int(manifest.get("study_count") or 0) == 1)
        _kpi.record(scenario, "folder count", int(manifest.get("folder_count") or 0), "", int(manifest.get("folder_count") or 0) >= 4)

        origin_server = (manifest.get("origin_server") or {}).get("name")
        hub_user = (manifest.get("hub_user") or {}).get("username")
        _kpi.record(scenario, "origin server captured", origin_server, "", origin_server == env["source_server"]["name"])
        _kpi.record(scenario, "hub user captured", hub_user, "", hub_user == env["actor_hub"]["username"])

        package_voice = env["package_root"] / "patients" / "attachments" / seeded["study_uid"] / "voice" / seeded["voice_file_name"]
        package_report = env["package_root"] / "patients" / "attachments" / seeded["study_uid"] / "reports" / seeded["report_file_name"]
        package_dicom = env["package_root"] / "patients" / "dicom" / seeded["study_uid"] / "101" / "image_001.dcm"
        _kpi.record(scenario, "voice file exported", package_voice.exists(), "", package_voice.exists())
        _kpi.record(scenario, "report attachment exported", package_report.exists(), "", package_report.exists())
        _kpi.record(scenario, "dicom file exported", package_dicom.exists(), "", package_dicom.exists())

        with _connect(env["package_root"] / "package.db") as conn:
            report_count = conn.execute("SELECT COUNT(*) FROM ai_reports WHERE study_uid = ?", (seeded["study_uid"],)).fetchone()[0]
            admission_count = conn.execute("SELECT COUNT(*) FROM ai_reception_reports WHERE study_uid = ?", (seeded["study_uid"],)).fetchone()[0]
        _kpi.record(scenario, "report rows exported", report_count, "", report_count == 1)
        _kpi.record(scenario, "admission rows exported", admission_count, "", admission_count == 1)


def scenario_offline_queries_and_permissions() -> None:
    scenario = "OC2: Offline package query, files, and permissions"
    with _temp_offline_cloud_env() as env:
        _create_schema(env["local_db"])
        seeded = _seed_local_study(env)
        export_studies_to_offline_cloud(
            env["server"],
            [seeded["study_uid"]],
            actor=env["actor_hub"],
            source_server=env["source_server"],
            operation="export_from_ai_pacs",
        )

        started = time.perf_counter()
        studies = list_offline_cloud_studies(env["server"], {"patient_id": seeded["patient_id"]})
        query_ms = (time.perf_counter() - started) * 1000
        info = get_offline_cloud_study_info(env["server"], seeded["study_uid"])
        manifest = read_offline_cloud_manifest(env["package_root"])

        root_path = env["package_root"]
        manifest_path = root_path / "manifest.json"
        database_path = root_path / "package.db"

        _kpi.record(scenario, "query latency", query_ms, "ms", len(studies) == 1)
        _kpi.record(scenario, "study query count", len(studies), "", len(studies) == 1)
        _kpi.record(scenario, "study info available", info is not None, "", info is not None)
        _kpi.record(scenario, "series count in study info", len((info or {}).get("series") or []), "", len((info or {}).get("series") or []) == 2)
        _kpi.record(scenario, "manifest load order includes manifest first", (manifest.get("items_to_load") or {}).get("load_order", [None])[0], "", ((manifest.get("items_to_load") or {}).get("load_order") or [None])[0] == "manifest.json")

        read_ok = os.access(root_path, os.R_OK) and os.access(manifest_path, os.R_OK) and os.access(database_path, os.R_OK)
        write_ok = os.access(root_path, os.W_OK) and os.access(manifest_path, os.W_OK) and os.access(database_path, os.W_OK)
        _kpi.record(scenario, "package read access", read_ok, "", read_ok)
        _kpi.record(scenario, "package write access", write_ok, "", write_ok)

        voice_file = root_path / "patients" / "attachments" / seeded["study_uid"] / "voice" / seeded["voice_file_name"]
        _kpi.record(scenario, "offline side can see exported voice file", voice_file.exists(), "", voice_file.exists())


def scenario_roundtrip_import_from_offline_cloud() -> None:
    scenario = "OC3: Round-trip import from Offline Cloud package"
    with _temp_offline_cloud_env() as env:
        _create_schema(env["local_db"])
        seeded = _seed_local_study(env)
        export_studies_to_offline_cloud(
            env["server"],
            [seeded["study_uid"]],
            actor=env["actor_hub"],
            source_server=env["source_server"],
            operation="export_from_ai_pacs",
        )

        _clear_local_study(env, seeded)

        started = time.perf_counter()
        result = sync_offline_cloud_study_to_local(
            env["server"],
            seeded["study_uid"],
            actor=env["actor_offline"],
        )
        import_ms = (time.perf_counter() - started) * 1000
        _kpi.record(scenario, "sync_offline_cloud_study_to_local latency", import_ms, "ms", result.get("ok") is True)
        _kpi.record(scenario, "import result ok", result.get("ok"), "", result.get("ok") is True)

        local_voice = env["local_attachments_dir"] / seeded["study_uid"] / "voice" / seeded["voice_file_name"]
        local_report = env["local_attachments_dir"] / seeded["study_uid"] / "reports" / seeded["report_file_name"]
        local_dicom = env["local_dicom_dir"] / seeded["study_uid"] / "101" / "image_001.dcm"
        _kpi.record(scenario, "voice file restored locally", local_voice.exists(), "", local_voice.exists())
        _kpi.record(scenario, "report attachment restored locally", local_report.exists(), "", local_report.exists())
        _kpi.record(scenario, "dicom restored locally", local_dicom.exists(), "", local_dicom.exists())

        with _connect(env["local_db"]) as conn:
            study_row = conn.execute("SELECT reportStatus, visit_status FROM studies WHERE study_uid = ?", (seeded["study_uid"],)).fetchone()
            report_count = conn.execute("SELECT COUNT(*) FROM ai_reports WHERE study_uid = ?", (seeded["study_uid"],)).fetchone()[0]
            admission_count = conn.execute("SELECT COUNT(*) FROM ai_reception_reports WHERE study_uid = ?", (seeded["study_uid"],)).fetchone()[0]
        report_status = study_row["reportStatus"] if study_row is not None else None
        visit_status = study_row["visit_status"] if study_row is not None else None
        _kpi.record(scenario, "report status restored", report_status, "", report_status == "finalized")
        _kpi.record(scenario, "visit status restored", visit_status, "", visit_status == "downloaded")
        _kpi.record(scenario, "report rows restored", report_count, "", report_count == 1)
        _kpi.record(scenario, "admission rows restored", admission_count, "", admission_count == 1)

        manifest = validate_offline_cloud_package(env["package_root"])
        timeline = manifest.get("timeline") or []
        importer = (manifest.get("last_imported_by") or {}).get("username")
        _kpi.record(scenario, "timeline event count", len(timeline), "", len(timeline) >= 2)
        _kpi.record(scenario, "last importer captured", importer, "", importer == env["actor_offline"]["username"])


def main() -> int:
    import datetime

    _reset_kpi()
    print(f"\n{'=' * 100}")
    print("  OFFLINE CLOUD SERVER - TEST SUITE")
    print(f"  Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Platform: {sys.platform}")
    print(f"{'=' * 100}")

    scenario_export_package_pipeline()
    scenario_offline_queries_and_permissions()
    scenario_roundtrip_import_from_offline_cloud()

    report = _kpi.report()
    print(report)
    return 0 if _kpi.failed_count == 0 else 1


def test_offline_cloud_server_kpis():
    _reset_kpi()
    scenario_export_package_pipeline()
    scenario_offline_queries_and_permissions()
    scenario_roundtrip_import_from_offline_cloud()
    assert _kpi.failed_count == 0, f"Offline Cloud Server KPI failures: {_kpi.failed_count}"


if __name__ == "__main__":
    sys.exit(main())
