from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from database.core import get_db_connection
from modules.storage.local_storage_cleanup_manager import LocalStorageCleanupManager
from PacsClient.utils.data_paths import (
    ATTACHMENTS_DIR,
    DATABASE_FILE,
    DICOM_IMAGES_DIR,
    ECHOMIND_DIR,
    REPORTS_DIR,
    THUMBNAILS_DIR,
    USER_DATA_ROOT,
)


class DataAnalysisService:
    """Collect operational data for the Data Analysis dashboard."""

    DATE_RANGES = [
        "All Time",
        "Today",
        "Yesterday",
        "Last 7 Days",
        "Last 30 Days",
        "Last 90 Days",
        "This Year",
    ]

    def build_snapshot(
        self,
        auth_user: dict[str, Any] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        filters = filters or {}

        snapshot: dict[str, Any] = {
            "account": self._build_account_info(auth_user),
            "active_filters": {
                "date_range": str(filters.get("date_range") or "All Time"),
                "server": str(filters.get("server") or "All Servers"),
                "user": str(filters.get("user") or "All Users"),
            },
            "filter_options": {
                "date_ranges": list(self.DATE_RANGES),
                "servers": ["All Servers"],
                "users": ["All Users"],
            },
            "totals": {},
            "modalities": [],
            "module_usage": [],
            "study_trend": [],
            "report_status": [],
            "servers": [],
            "storage": [],
            "storage_cleanup": {"drives": [], "folders": []},
            "recent_studies": [],
            "generated_at": None,
        }

        studies_where_sql, studies_params = self._build_studies_filter_where(filters)
        selected_user = snapshot["active_filters"]["user"]

        with get_db_connection() as conn:
            cur = conn.cursor()
            studies_columns = self._table_columns(cur, "studies")

            snapshot["totals"] = self._collect_totals(
                cur,
                studies_columns,
                studies_where_sql,
                studies_params,
                selected_user,
            )
            snapshot["modalities"] = self._collect_modality_distribution(cur, studies_where_sql, studies_params)
            snapshot["module_usage"] = self._collect_module_usage(
                cur,
                studies_columns,
                studies_where_sql,
                studies_params,
                selected_user,
            )
            snapshot["study_trend"] = self._collect_study_trend(cur, studies_where_sql, studies_params)
            snapshot["report_status"] = self._collect_report_status_distribution(
                cur,
                studies_columns,
                studies_where_sql,
                studies_params,
            )
            snapshot["recent_studies"] = self._collect_recent_studies(
                cur,
                studies_columns,
                studies_where_sql,
                studies_params,
            )
            snapshot["generated_at"] = self._query_scalar(cur, "SELECT datetime('now', 'localtime')")
            snapshot["filter_options"]["users"] = self._collect_user_options(cur, snapshot["account"])

        snapshot["servers"] = self._collect_servers()
        snapshot["storage"] = self._collect_storage_stats()
        force_storage_refresh = bool(filters.get("force_storage_refresh", False))
        snapshot["storage_cleanup"] = self._collect_storage_cleanup_info(force_refresh=force_storage_refresh)

        server_options = ["All Servers"]
        for s in snapshot["servers"]:
            name = str(s.get("name", "")).strip()
            if name and name not in server_options:
                server_options.append(name)
        snapshot["filter_options"]["servers"] = server_options

        snapshot["totals"]["configured_servers"] = len(snapshot["servers"])
        return snapshot

    def _build_account_info(self, auth_user: dict[str, Any] | None) -> dict[str, str]:
        auth_user = auth_user or {}
        return {
            "full_name": str(auth_user.get("full_name") or auth_user.get("username") or "Local User"),
            "username": str(auth_user.get("username") or "local"),
            "role": str(auth_user.get("role") or "user"),
        }

    def _collect_user_options(self, cur, account: dict[str, str]) -> list[str]:
        options = ["All Users"]

        current_username = str(account.get("username") or "").strip()
        if current_username and current_username not in options:
            options.append(current_username)

        for table_name in ("user_token_usage", "api_token_usage", "api_transcript_usage"):
            if not self._table_exists(cur, table_name):
                continue
            rows = self._query_all(
                cur,
                f"SELECT DISTINCT center_name FROM {table_name} WHERE center_name IS NOT NULL AND TRIM(center_name) != ''",
            )
            for (center_name,) in rows:
                value = str(center_name).strip()
                if value and value not in options:
                    options.append(value)

        return options

    def _build_studies_filter_where(self, filters: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
        conditions: list[str] = ["1=1"]
        params: list[Any] = []

        date_range = str(filters.get("date_range") or "All Time").strip()
        exact_date, cutoff = self._date_filters_for_range(date_range)
        if exact_date:
            conditions.append("REPLACE(COALESCE(s.study_date, ''), '-', '') = ?")
            params.append(exact_date)
        elif cutoff:
            conditions.append("REPLACE(COALESCE(s.study_date, ''), '-', '') >= ?")
            params.append(cutoff)

        server_value = str(filters.get("server") or "All Servers").strip()
        if server_value and server_value != "All Servers":
            conditions.append("LOWER(COALESCE(s.institution_name, '')) LIKE LOWER(?)")
            params.append(f"%{server_value}%")

        return " AND ".join(conditions), tuple(params)

    def _date_filters_for_range(self, date_range: str) -> tuple[str | None, str | None]:
        today = date.today()
        if date_range == "Today":
            return today.strftime("%Y%m%d"), None
        if date_range == "Yesterday":
            return (today - timedelta(days=1)).strftime("%Y%m%d"), None
        if date_range == "Last 7 Days":
            return None, (today - timedelta(days=7)).strftime("%Y%m%d")
        if date_range == "Last 30 Days":
            return None, (today - timedelta(days=30)).strftime("%Y%m%d")
        if date_range == "Last 90 Days":
            return None, (today - timedelta(days=90)).strftime("%Y%m%d")
        if date_range == "This Year":
            return None, today.replace(month=1, day=1).strftime("%Y%m%d")
        return None, None

    def _collect_totals(
        self,
        cur,
        studies_columns: set[str],
        studies_where_sql: str,
        studies_params: tuple[Any, ...],
        selected_user: str,
    ) -> dict[str, Any]:
        totals = {
            "patients": 0,
            "studies": 0,
            "series": 0,
            "instances": 0,
            "download_jobs": self._safe_count(cur, "download_progress"),
            "echomind_sessions": self._safe_count(cur, "ai_sessions"),
            "echomind_reports": self._safe_count(cur, "ai_reports"),
            "total_user_tokens": self._sum_tokens_by_user(cur, "user_token_usage", "total_tokens", selected_user),
            "total_api_tokens": self._sum_tokens_by_user(cur, "api_token_usage", "total_tokens", selected_user),
            "total_transcript_seconds": self._sum_tokens_by_user(cur, "api_transcript_usage", "total_seconds", selected_user),
            "configured_servers": 0,
            "pending_reports": 0,
        }

        if self._table_exists(cur, "studies"):
            totals["studies"] = int(
                self._query_scalar(cur, f"SELECT COUNT(*) FROM studies s WHERE {studies_where_sql}", studies_params) or 0
            )
            totals["patients"] = int(
                self._query_scalar(cur, f"SELECT COUNT(DISTINCT s.patient_fk) FROM studies s WHERE {studies_where_sql}", studies_params) or 0
            )

            if self._table_exists(cur, "series"):
                totals["series"] = int(
                    self._query_scalar(
                        cur,
                        f"SELECT COUNT(*) FROM series se JOIN studies s ON s.study_pk = se.study_fk WHERE {studies_where_sql}",
                        studies_params,
                    )
                    or 0
                )

            if self._table_exists(cur, "instances") and self._table_exists(cur, "series"):
                totals["instances"] = int(
                    self._query_scalar(
                        cur,
                        f"""
                        SELECT COUNT(*)
                        FROM instances i
                        JOIN series se ON se.series_pk = i.series_fk
                        JOIN studies s ON s.study_pk = se.study_fk
                        WHERE {studies_where_sql}
                        """,
                        studies_params,
                    )
                    or 0
                )

            if "reportStatus" in studies_columns:
                totals["pending_reports"] = int(
                    self._query_scalar(
                        cur,
                        f"SELECT COUNT(*) FROM studies s WHERE {studies_where_sql} AND COALESCE(s.reportStatus, 'pending') = 'pending'",
                        studies_params,
                    )
                    or 0
                )

        return totals

    def _sum_tokens_by_user(self, cur, table_name: str, column_name: str, selected_user: str) -> int:
        columns = self._table_columns(cur, table_name)
        if column_name not in columns:
            return 0

        if selected_user and selected_user != "All Users" and "center_name" in columns:
            value = self._query_scalar(
                cur,
                f"SELECT COALESCE(SUM({column_name}), 0) FROM {table_name} WHERE COALESCE(center_name, '') = ?",
                (selected_user,),
            )
            return int(value or 0)

        value = self._query_scalar(cur, f"SELECT COALESCE(SUM({column_name}), 0) FROM {table_name}")
        return int(value or 0)

    def _collect_modality_distribution(self, cur, studies_where_sql: str, studies_params: tuple[Any, ...]) -> list[dict[str, Any]]:
        if not self._table_exists(cur, "studies"):
            return []

        rows = self._query_all(
            cur,
            f"""
            SELECT COALESCE(NULLIF(s.modality, ''), 'Unknown') AS modality,
                   COUNT(*) AS count
            FROM studies s
            WHERE {studies_where_sql}
            GROUP BY COALESCE(NULLIF(s.modality, ''), 'Unknown')
            ORDER BY count DESC, modality ASC
            """,
            studies_params,
        )
        total = sum(int(row[1] or 0) for row in rows) or 1
        result = []
        for modality, count in rows:
            c = int(count or 0)
            result.append({"modality": str(modality), "count": c, "percent": round((c / total) * 100.0, 1)})
        return result

    def _collect_module_usage(
        self,
        cur,
        studies_columns: set[str],
        studies_where_sql: str,
        studies_params: tuple[Any, ...],
        selected_user: str,
    ) -> list[dict[str, Any]]:
        usage = [
            {"module": "EchoMind Sessions", "count": self._safe_count(cur, "ai_sessions")},
            {"module": "EchoMind Messages", "count": self._safe_count(cur, "ai_messages")},
            {"module": "EchoMind Reports", "count": self._safe_count(cur, "ai_reports")},
            {"module": "Secretary Actions", "count": self._safe_count(cur, "ai_secretary_actions")},
            {"module": "Reception Reports", "count": self._safe_count(cur, "ai_reception_reports")},
            {"module": "Download Jobs", "count": self._safe_count(cur, "download_progress")},
        ]

        if self._table_exists(cur, "download_progress"):
            done = self._query_scalar(
                cur,
                "SELECT COUNT(*) FROM download_progress WHERE LOWER(COALESCE(status, '')) IN ('completed', 'done', 'success')",
            )
            in_progress = self._query_scalar(
                cur,
                "SELECT COUNT(*) FROM download_progress WHERE LOWER(COALESCE(status, '')) IN ('in_progress', 'running', 'queued')",
            )
            usage.append({"module": "Download Completed", "count": int(done or 0)})
            usage.append({"module": "Download In Progress", "count": int(in_progress or 0)})

        if self._table_exists(cur, "studies") and "visit_status" in studies_columns:
            synced = self._query_scalar(
                cur,
                f"SELECT COUNT(*) FROM studies s WHERE {studies_where_sql} AND LOWER(COALESCE(s.visit_status, '')) = 'synced'",
                studies_params,
            )
            usage.append({"module": "Synced Studies", "count": int(synced or 0)})

        usage.append({
            "module": "Filtered User Tokens",
            "count": self._sum_tokens_by_user(cur, "user_token_usage", "total_tokens", selected_user),
        })

        usage.sort(key=lambda item: int(item.get("count", 0)), reverse=True)
        return usage

    def _collect_study_trend(self, cur, studies_where_sql: str, studies_params: tuple[Any, ...]) -> list[dict[str, Any]]:
        if not self._table_exists(cur, "studies"):
            return []

        rows = self._query_all(
            cur,
            f"""
            SELECT s.study_date, COUNT(*) AS count
            FROM studies s
            WHERE {studies_where_sql} AND s.study_date IS NOT NULL AND TRIM(s.study_date) != ''
            GROUP BY s.study_date
            ORDER BY s.study_date DESC
            LIMIT 14
            """,
            studies_params,
        )
        rows = list(reversed(rows))
        return [{"date": str(date_value), "count": int(count or 0)} for date_value, count in rows]

    def _collect_report_status_distribution(
        self,
        cur,
        studies_columns: set[str],
        studies_where_sql: str,
        studies_params: tuple[Any, ...],
    ) -> list[dict[str, Any]]:
        if "reportStatus" not in studies_columns or not self._table_exists(cur, "studies"):
            return []

        rows = self._query_all(
            cur,
            f"""
            SELECT COALESCE(NULLIF(s.reportStatus, ''), 'pending') AS status, COUNT(*) AS count
            FROM studies s
            WHERE {studies_where_sql}
            GROUP BY COALESCE(NULLIF(s.reportStatus, ''), 'pending')
            ORDER BY count DESC, status ASC
            """,
            studies_params,
        )
        return [{"status": str(status_value), "count": int(count or 0)} for status_value, count in rows]

    def _collect_recent_studies(
        self,
        cur,
        studies_columns: set[str],
        studies_where_sql: str,
        studies_params: tuple[Any, ...],
    ) -> list[dict[str, Any]]:
        if not self._table_exists(cur, "studies"):
            return []

        report_col = "s.reportStatus" if "reportStatus" in studies_columns else "''"

        rows = self._query_all(
            cur,
            f"""
            SELECT
                COALESCE(p.patient_name, '') AS patient_name,
                COALESCE(s.study_uid, '') AS study_uid,
                COALESCE(s.modality, 'Unknown') AS modality,
                COALESCE(s.study_date, '') AS study_date,
                COALESCE(s.number_of_instances, 0) AS images,
                COALESCE({report_col}, '') AS report_status
            FROM studies s
            LEFT JOIN patients p ON p.patient_pk = s.patient_fk
            WHERE {studies_where_sql}
            ORDER BY COALESCE(s.study_date, '') DESC, COALESCE(s.study_time, '') DESC
            LIMIT 20
            """,
            studies_params,
        )

        result = []
        for patient_name, study_uid, modality, study_date, images, report_status in rows:
            result.append(
                {
                    "patient_name": str(patient_name),
                    "study_uid": str(study_uid),
                    "modality": str(modality or "Unknown"),
                    "study_date": str(study_date),
                    "images": int(images or 0),
                    "report_status": str(report_status or ""),
                }
            )
        return result

    def _collect_servers(self) -> list[dict[str, str]]:
        servers: list[dict[str, str]] = []

        legacy_file = Path("servers.json")
        if legacy_file.exists():
            try:
                raw = json.loads(legacy_file.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    for item in raw:
                        if not isinstance(item, dict):
                            continue
                        servers.append(
                            {
                                "source": "servers.json",
                                "name": str(item.get("name") or "Unnamed"),
                                "endpoint": self._compose_endpoint(item),
                            }
                        )
            except Exception:
                pass

        config_file = Path("config") / "servers_address.json"
        if config_file.exists():
            try:
                raw = json.loads(config_file.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("services"), dict):
                    for name, endpoint in raw["services"].items():
                        servers.append(
                            {
                                "source": "config/services",
                                "name": str(name),
                                "endpoint": str(endpoint),
                            }
                        )
                elif isinstance(raw, list):
                    for item in raw:
                        if not isinstance(item, dict):
                            continue
                        servers.append(
                            {
                                "source": "config/list",
                                "name": str(item.get("name") or "Unnamed"),
                                "endpoint": str(item.get("url") or item.get("endpoint") or ""),
                            }
                        )
            except Exception:
                pass

        dedup: dict[tuple[str, str], dict[str, str]] = {}
        for server in servers:
            key = (server.get("name", ""), server.get("endpoint", ""))
            dedup[key] = server

        return sorted(dedup.values(), key=lambda row: (row.get("source", ""), row.get("name", "")))

    def _collect_storage_stats(self) -> list[dict[str, Any]]:
        entries = [
            ("Database", DATABASE_FILE),
            ("DICOM Storage", DICOM_IMAGES_DIR),
            ("Attachments", ATTACHMENTS_DIR),
            ("Thumbnails", THUMBNAILS_DIR),
            ("EchoMind", ECHOMIND_DIR),
            ("Reports", REPORTS_DIR),
            ("User Data Root", USER_DATA_ROOT),
        ]

        stats: list[dict[str, Any]] = []
        for label, path in entries:
            size_bytes, files = self._path_stats(path)
            stats.append({"name": label, "path": str(path), "size_bytes": size_bytes, "files": files})
        return stats

    def _collect_storage_cleanup_info(self, force_refresh: bool = False) -> dict[str, list[dict[str, Any]]]:
        cleanup = LocalStorageCleanupManager()
        drives = cleanup.get_drive_usage_info()
        folder_usage = cleanup.get_folder_usage_breakdown(force_refresh=force_refresh)
        folder_map = cleanup.get_folder_map()

        current_drive_anchor = str(Path(USER_DATA_ROOT).anchor or "").upper()
        current_drive_used = 0
        for row in drives:
            if str(row.get("drive", "")).upper().startswith(current_drive_anchor):
                current_drive_used = int(row.get("used", 0))
                break
        if current_drive_used <= 0 and drives:
            current_drive_used = int(drives[0].get("used", 0))

        folder_titles = {
            "patients": "Patients Data Folder",
            "education": "Education Folder",
            "cache": "Cache Folder",
            "printing": "Printing Folder",
        }
        folders: list[dict[str, Any]] = []
        for key, size_bytes in folder_usage.items():
            ratio = (float(size_bytes) / current_drive_used * 100.0) if current_drive_used > 0 else 0.0
            folders.append(
                {
                    "key": key,
                    "name": folder_titles.get(key, key.title()),
                    "size_bytes": int(size_bytes),
                    "size_text": cleanup.format_size(int(size_bytes)),
                    "used_disk_percent": round(ratio, 2),
                    "paths": [str(p) for p in folder_map.get(key, [])],
                }
            )

        return {
            "drives": drives,
            "folders": folders,
        }

    def _path_stats(self, path: Path) -> tuple[int, int]:
        if not path.exists():
            return 0, 0

        if path.is_file():
            try:
                return path.stat().st_size, 1
            except Exception:
                return 0, 0

        total_size = 0
        total_files = 0
        for root, _dirs, files in os.walk(path):
            for file_name in files:
                file_path = Path(root) / file_name
                try:
                    total_size += file_path.stat().st_size
                    total_files += 1
                except Exception:
                    continue
        return total_size, total_files

    def _table_exists(self, cur, table_name: str) -> bool:
        value = self._query_scalar(
            cur,
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table_name,),
        )
        return bool(value)

    def _table_columns(self, cur, table_name: str) -> set[str]:
        if not self._table_exists(cur, table_name):
            return set()
        rows = self._query_all(cur, f"PRAGMA table_info({table_name})")
        return {str(row[1]) for row in rows if len(row) > 1}

    def _safe_count(self, cur, table_name: str) -> int:
        if not self._table_exists(cur, table_name):
            return 0
        return int(self._query_scalar(cur, f"SELECT COUNT(*) FROM {table_name}") or 0)

    def _query_scalar(self, cur, sql: str, params: tuple[Any, ...] = ()) -> Any:
        try:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def _query_all(self, cur, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        try:
            cur.execute(sql, params)
            return cur.fetchall() or []
        except Exception:
            return []

    def _compose_endpoint(self, server: dict[str, Any]) -> str:
        if server.get("url"):
            return str(server.get("url"))

        host = server.get("host") or server.get("ip") or ""
        port = server.get("port") or ""
        ae_title = server.get("ae_title") or server.get("aet") or ""

        endpoint = str(host)
        if port:
            endpoint = f"{endpoint}:{port}"
        if ae_title:
            endpoint = f"{endpoint} ({ae_title})" if endpoint else str(ae_title)
        return endpoint
