import argparse
import base64
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Allow running this script directly (python tools/diagnostics/...) without -m.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.network.socket_client import PatientListSocketClient
from modules.network.socket_config import get_socket_server_settings
from modules.download_manager.network.socket_client import SocketDicomClient


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


def _pick_series_uid(study_info: Dict[str, Any]) -> str:
    series = study_info.get("series") or study_info.get("series_thumbnails") or []
    if not isinstance(series, list):
        return ""
    for item in series:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("series_uid") or item.get("series_instance_uid") or "").strip()
        if uid:
            return uid
    return ""


def _download_batch_worker(
    queue: "mp.Queue[Dict[str, Any]]",
    host: str,
    port: int,
    timeout_seconds: int,
    study_uid: str,
    series_uid: str,
) -> None:
    payload: Dict[str, Any] = {"ok": False, "error": "", "instances": []}
    dcm_client = SocketDicomClient(host=host, port=port, timeout=timeout_seconds)
    try:
        resp = dcm_client.download_batch(
            study_uid=study_uid,
            series_uid=series_uid,
            batch_start=0,
            batch_size=1,
        )
        data = (resp or {}).get("data") or {}
        instances = data.get("instances") or []
        if isinstance(instances, list):
            payload["ok"] = True
            payload["instances"] = instances
        else:
            payload["error"] = "instances field is not a list"
    except Exception as exc:
        payload["error"] = str(exc)
    finally:
        try:
            dcm_client.disconnect()
        except Exception:
            pass
        queue.put(payload)


def run(patient_id: str, out_dir: Path, timeout_seconds: int = 20) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "patient_id": patient_id,
        "connection_ok": False,
        "patient_found": False,
        "study_count": 0,
        "studies": [],
        "dicom_download": {
            "attempted": False,
            "ok": False,
            "saved_file": "",
            "error": "",
        },
    }

    cfg = get_socket_server_settings() or {}
    host = cfg.get("host") or cfg.get("socket_host") or "localhost"
    port = int(cfg.get("port") or cfg.get("socket_port") or 50052)
    report["socket_target"] = {"host": host, "port": port}

    print(f"[PIPELINE] target={host}:{port} timeout={timeout_seconds}s", flush=True)

    pl_client = PatientListSocketClient(host=host, port=port, timeout=timeout_seconds)
    rows: List[Dict[str, Any]] = []
    try:
        t0 = _now_ms()
        print("[PIPELINE] step=search_patients_sync start", flush=True)
        rows = pl_client.get_patient_list_safe(
            patient_id=str(patient_id),
            limit=50,
            offset=0,
            include_study_count=True,
            include_latest_study=True,
        ) or []
        report["patient_search_ms"] = round(_now_ms() - t0, 2)
        report["connection_ok"] = True
        print(
            f"[PIPELINE] step=search_patients_sync ok rows={len(rows)} ms={report['patient_search_ms']}",
            flush=True,
        )
    except Exception as exc:
        report["patient_search_ms"] = round(_now_ms() - t0, 2)
        report["error"] = f"search_patients failed: {exc}"
        print(f"[PIPELINE] step=search_patients_sync error={exc}", flush=True)
        return report

    target = None
    for row in rows:
        if str((row or {}).get("patient_id") or "").strip() == str(patient_id):
            target = row
            break

    if target is None:
        report["error"] = f"Patient {patient_id} not found in socket search result"
        return report

    report["patient_found"] = True
    study_uids = _collect_study_uids(target)
    report["study_uids"] = study_uids
    report["study_count"] = len(study_uids)

    try:
        for study_uid in study_uids:
            print(f"[PIPELINE] step=study_probe uid={study_uid} start", flush=True)
            s_item: Dict[str, Any] = {
                "study_uid": study_uid,
                "get_study_info_ok": False,
                "get_study_info_series": 0,
                "get_study_thumbnails_ok": False,
                "get_study_thumbnails_series": 0,
            }

            t_info = _now_ms()
            info = pl_client.get_study_info(study_uid) or {}
            s_item["get_study_info_ms"] = round(_now_ms() - t_info, 2)
            series_info = info.get("series") or info.get("series_thumbnails") or []
            s_item["get_study_info_ok"] = bool(info)
            s_item["get_study_info_series"] = len(series_info) if isinstance(series_info, list) else 0

            t_thumb = _now_ms()
            thumbs = pl_client.get_study_thumbnails(
                study_uid,
                include_base64=False,
                include_image_data=False,
            ) or {}
            s_item["get_study_thumbnails_ms"] = round(_now_ms() - t_thumb, 2)
            series_thumb = thumbs.get("series_thumbnails") or thumbs.get("series") or []
            s_item["get_study_thumbnails_ok"] = bool(thumbs)
            s_item["get_study_thumbnails_series"] = len(series_thumb) if isinstance(series_thumb, list) else 0

            report["studies"].append(s_item)
            print(
                "[PIPELINE] step=study_probe"
                f" uid={study_uid} info_ok={s_item['get_study_info_ok']}"
                f" info_series={s_item['get_study_info_series']}"
                f" thumbs_ok={s_item['get_study_thumbnails_ok']}"
                f" thumbs_series={s_item['get_study_thumbnails_series']}",
                flush=True,
            )

        # DICOM download simulation: one batch from first resolvable study/series.
        chosen_study = ""
        chosen_series = ""
        for item in report["studies"]:
            if item.get("get_study_info_ok") and int(item.get("get_study_info_series", 0)) > 0:
                chosen_study = str(item.get("study_uid") or "")
                info = pl_client.get_study_info(chosen_study) or {}
                chosen_series = _pick_series_uid(info)
                if chosen_series:
                    break

        if chosen_study and chosen_series:
            report["dicom_download"]["attempted"] = True
            print(
                f"[PIPELINE] step=download_batch start study={chosen_study} series={chosen_series}",
                flush=True,
            )
            q: "mp.Queue[Dict[str, Any]]" = mp.Queue(maxsize=1)
            proc = mp.Process(
                target=_download_batch_worker,
                args=(q, host, port, timeout_seconds, chosen_study, chosen_series),
                daemon=True,
            )
            try:
                proc.start()
                proc.join(timeout=timeout_seconds + 5)
                if proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=2)
                    report["dicom_download"]["error"] = (
                        f"download_batch timed out after {timeout_seconds + 5}s"
                    )
                    print(
                        f"[PIPELINE] step=download_batch timeout>{timeout_seconds + 5}s",
                        flush=True,
                    )
                    instances = []
                else:
                    worker_payload = q.get_nowait() if not q.empty() else {}
                    if worker_payload.get("error"):
                        report["dicom_download"]["error"] = str(worker_payload.get("error"))
                        print(
                            f"[PIPELINE] step=download_batch error={report['dicom_download']['error']}",
                            flush=True,
                        )
                    instances = worker_payload.get("instances") or []
                if isinstance(instances, list) and instances:
                    first = instances[0] if isinstance(instances[0], dict) else {}
                    b64 = first.get("dicom_data") or ""
                    if b64:
                        out_dir.mkdir(parents=True, exist_ok=True)
                        file_path = out_dir / f"patient_{patient_id}_{chosen_series[:16]}_batch0_inst1.dcm"
                        file_path.write_bytes(base64.b64decode(b64))
                        report["dicom_download"]["ok"] = True
                        report["dicom_download"]["saved_file"] = str(file_path)
                        report["dicom_download"]["study_uid"] = chosen_study
                        report["dicom_download"]["series_uid"] = chosen_series
                        report["dicom_download"]["instances_returned"] = len(instances)
                        print(
                            f"[PIPELINE] step=download_batch ok instances={len(instances)}",
                            flush=True,
                        )
                    else:
                        report["dicom_download"]["error"] = "Batch returned instance without dicom_data"
                else:
                    report["dicom_download"]["error"] = report["dicom_download"]["error"] or "No instances returned from download_batch"
            except Exception as exc:
                report["dicom_download"]["error"] = str(exc)
                print(f"[PIPELINE] step=download_batch error={exc}", flush=True)
            finally:
                try:
                    q.close()
                except Exception:
                    pass
        else:
            report["dicom_download"]["error"] = "No study/series available for download_batch probe"

    finally:
        try:
            pl_client.disconnect()
        except Exception:
            pass

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Socket pipeline integration check for one patient")
    parser.add_argument("--patient-id", default="42136")
    parser.add_argument(
        "--out-dir",
        default="generated-files/diagnostics/patient_42136_pipeline",
    )
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    report = run(str(args.patient_id), Path(args.out_dir), timeout_seconds=max(5, int(args.timeout)))
    text = json.dumps(report, indent=2)
    print(text)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
