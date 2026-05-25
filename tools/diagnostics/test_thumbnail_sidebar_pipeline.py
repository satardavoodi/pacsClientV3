import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Ensure Qt can initialize in headless test runs.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap

from modules.network.socket_client import PatientListSocketClient
from modules.network.socket_config import get_socket_server_settings
from PacsClient.pacs.workstation_ui.home_ui.right_panel_widget import RightPanelWidget
from PacsClient.pacs.workstation_ui.home_ui.home_panel._hp_series import _HPSeriesMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_tab_widget import PatientTabWidget
from PacsClient.pacs.patient_tab.utils import get_all_series_thumbnail_from_study_folder


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _collect_study_uids(patient_row: Dict[str, Any]) -> List[str]:
    uids: List[str] = []

    for key in ("study_uid", "latest_study_uid", "StudyInstanceUID", "study_instance_uid"):
        v = str(patient_row.get(key) or "").strip()
        if v and v not in uids:
            uids.append(v)

    raw_uids = patient_row.get("study_uids") or []
    if isinstance(raw_uids, str):
        raw_uids = [raw_uids]
    if isinstance(raw_uids, list):
        for v in raw_uids:
            uid = str(v or "").strip()
            if uid and uid not in uids:
                uids.append(uid)

    studies = patient_row.get("studies") or patient_row.get("study_list") or []
    if isinstance(studies, list):
        for st in studies:
            if not isinstance(st, dict):
                continue
            uid = str(st.get("study_uid") or st.get("StudyInstanceUID") or "").strip()
            if uid and uid not in uids:
                uids.append(uid)

    return uids


def _normalize_thumbnails(data: Dict[str, Any], patient_id: str, study_uid: str) -> Dict[str, Any]:
    out = {
        "patient_name": data.get("patient_name") or "",
        "patient_id": data.get("patient_id") or patient_id,
        "study_date": data.get("study_date") or "",
        "study_uid": data.get("study_instance_uid") or study_uid,
        "thumbnails": [],
    }

    series_items = data.get("series_thumbnails") or data.get("series") or data.get("thumbnails") or []
    if isinstance(series_items, dict):
        series_items = list(series_items.values())

    for series in series_items:
        if not isinstance(series, dict):
            continue

        series_uid = (
            series.get("series_uid")
            or series.get("series_instance_uid")
            or series.get("SeriesInstanceUID")
            or ""
        )
        series_number = series.get("series_number") or series.get("SeriesNumber") or ""
        series_description = series.get("series_description") or series.get("SeriesDescription") or ""
        modality = series.get("modality") or series.get("Modality") or ""
        image_count = series.get("image_count") or series.get("ImageCount") or series.get("number_of_images") or 0
        thumbnail_data = (
            series.get("thumbnail_data")
            or series.get("thumbnail_base64")
            or series.get("thumbnailBase64")
            or series.get("thumbnailData")
            or series.get("image_data")
            or series.get("imageBase64")
            or ""
        )

        out["thumbnails"].append(
            {
                "series_uid": series_uid,
                "series_number": str(series_number),
                "series_description": str(series_description),
                "modality": str(modality),
                "image_count": int(image_count or 0),
                "thumbnail_path": series.get("thumbnail_path", ""),
                "thumbnail_data": thumbnail_data,
            }
        )

    return out


class _DummySeries(_HPSeriesMixin):
    pass


def run(patient_id: str, timeout_seconds: int = 20) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "patient_id": str(patient_id),
        "socket": {},
        "fetch": {},
        "normalize": {},
        "save": {},
        "main_sidebar": {},
        "patient_sidebar": {},
        "status": "failed",
        "errors": [],
    }

    cfg = get_socket_server_settings() or {}
    host = cfg.get("host") or cfg.get("socket_host") or "localhost"
    port = int(cfg.get("port") or cfg.get("socket_port") or 50052)
    report["socket"] = {"host": host, "port": port}

    client = PatientListSocketClient(host=host, port=port, timeout=int(timeout_seconds))
    app = QApplication.instance() or QApplication([])

    try:
        t0 = _now_ms()
        rows = client.get_patient_list_safe(
            patient_id=str(patient_id),
            limit=50,
            offset=0,
            include_study_count=True,
            include_latest_study=True,
        ) or []
        report["fetch"]["search_ms"] = round(_now_ms() - t0, 2)
        report["fetch"]["rows"] = len(rows)

        target = None
        for row in rows:
            if str((row or {}).get("patient_id") or "").strip() == str(patient_id):
                target = row
                break

        if target is None:
            report["errors"].append(f"patient {patient_id} not found")
            return report

        study_uids = _collect_study_uids(target)
        report["fetch"]["study_uids"] = study_uids
        if not study_uids:
            report["errors"].append("no study_uids found for patient")
            return report

        study_uid = str(study_uids[0])
        report["fetch"]["study_uid_selected"] = study_uid

        t1 = _now_ms()
        raw = client.get_study_thumbnails(
            study_uid,
            include_base64=True,
            include_image_data=False,
        ) or {}
        report["fetch"]["get_study_thumbnails_ms"] = round(_now_ms() - t1, 2)
        report["fetch"]["raw_has_data"] = bool(raw)

        normalized = _normalize_thumbnails(raw, str(patient_id), study_uid)
        thumbs = normalized.get("thumbnails") or []
        report["normalize"]["count"] = len(thumbs)
        report["normalize"]["has_series_uid"] = sum(1 for t in thumbs if str(t.get("series_uid") or "").strip())
        report["normalize"]["has_thumbnail_data"] = sum(1 for t in thumbs if bool(t.get("thumbnail_data")))

        if not thumbs:
            report["errors"].append("normalized thumbnails list is empty")
            return report

        saver = _DummySeries()
        saved_payload = saver.save_thumbnail(normalized)
        saved_thumbs = saved_payload.get("thumbnails") or []

        saved_with_path = [t for t in saved_thumbs if str(t.get("file_path") or "").strip()]
        existing_paths = [p for p in [str(t.get("file_path") or "") for t in saved_with_path] if Path(p).exists()]

        report["save"]["saved_count"] = len(saved_with_path)
        report["save"]["existing_file_count"] = len(existing_paths)
        report["save"]["sample_file"] = existing_paths[0] if existing_paths else ""

        # Main left sidebar contract test (RightPanelWidget)
        right_panel = RightPanelWidget()
        pix_ok = 0
        for t in saved_thumbs:
            pm = right_panel._build_pixmap_from_thumb(t, t.get("file_path") or t.get("thumbnail_path"))
            if isinstance(pm, QPixmap) and not pm.isNull():
                pix_ok += 1

        right_panel.display_thumbnails_immediately(saved_thumbs, generation=right_panel._display_generation)
        app.processEvents()

        report["main_sidebar"]["pixmap_ok_count"] = pix_ok
        report["main_sidebar"]["grid_item_count"] = int(right_panel.content_grid.count())
        report["main_sidebar"]["count_label"] = str(right_panel.count_label.text())

        # Patient sidebar contract test (thumbnail path usable by patient tab widget)
        folder_list = get_all_series_thumbnail_from_study_folder(study_uid)
        folder_list = [str(p) for p in (folder_list or [])]
        folder_existing = [p for p in folder_list if Path(p).exists()]

        ptw = PatientTabWidget(
            patient_name=str(target.get("patient_name") or target.get("PatientName") or "Unknown"),
            patient_id=str(patient_id),
            thumbnail_path=(existing_paths[0] if existing_paths else ""),
            study_uid=study_uid,
        )
        app.processEvents()

        report["patient_sidebar"]["thumbnail_files_found"] = len(folder_list)
        report["patient_sidebar"]["thumbnail_files_existing"] = len(folder_existing)
        report["patient_sidebar"]["tab_thumbnail_loaded"] = bool(
            getattr(ptw, "thumbnail_pixmap", None) is not None and not ptw.thumbnail_pixmap.isNull()
        )

        # Final pass criteria
        pass_main = report["main_sidebar"]["pixmap_ok_count"] > 0 and report["main_sidebar"]["grid_item_count"] > 0
        pass_patient = report["patient_sidebar"]["thumbnail_files_existing"] > 0 and report["patient_sidebar"]["tab_thumbnail_loaded"]
        pass_save = report["save"]["existing_file_count"] > 0
        pass_fetch = report["normalize"]["count"] > 0

        report["status"] = "passed" if (pass_fetch and pass_save and pass_main and pass_patient) else "failed"
        report["checks"] = {
            "fetch_normalize": pass_fetch,
            "save_to_disk": pass_save,
            "main_sidebar_contract": pass_main,
            "patient_sidebar_contract": pass_patient,
        }

        return report

    except Exception as exc:
        report["errors"].append(str(exc))
        return report
    finally:
        try:
            client.disconnect()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Thumbnail pipeline check for main and patient sidebars")
    parser.add_argument("--patient-id", default="42136")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--json-out", default="generated-files/diagnostics/thumbnail_sidebar_pipeline/result.json")
    args = parser.parse_args()

    report = run(str(args.patient_id), timeout_seconds=max(5, int(args.timeout)))
    text = json.dumps(report, indent=2)
    print(text)

    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")

    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
