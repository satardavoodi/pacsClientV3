import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from statistics import mean

from modules.network.socket_client import PatientListSocketClient
from modules.network.socket_config import get_socket_server_settings
from modules.network.socket_patient_service import get_socket_patient_service


def _extract_uid(patient_row):
    for key in ("latest_study_uid", "study_uid", "StudyInstanceUID", "study_instance_uid"):
        value = str(patient_row.get(key) or "").strip()
        if value:
            return value

    studies = patient_row.get("studies") or patient_row.get("study_list") or []
    if isinstance(studies, list):
        for item in studies:
            if not isinstance(item, dict):
                continue
            value = str(item.get("study_uid") or item.get("StudyInstanceUID") or "").strip()
            if value:
                return value
    return ""


def _thumbnail_fetch(host, port, uid, include_image_data=False, timeout=15):
    t0 = time.perf_counter()
    client = PatientListSocketClient(host=host, port=port, timeout=timeout)
    data = client.get_study_thumbnails(
        uid,
        include_base64=True,
        include_image_data=include_image_data,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    series = (data or {}).get("series_thumbnails") or []
    return {
        "uid": uid,
        "ok": bool(data),
        "series_count": len(series),
        "latency_ms": elapsed_ms,
    }


def run_audit(date_from, date_to, patient_limit, study_limit, sequential_requests, workers):
    summary = {
        "date_from": date_from,
        "date_to": date_to,
        "patient_limit": patient_limit,
        "study_limit": study_limit,
    }

    # Stage 1: connection + patient search
    svc = get_socket_patient_service()
    connected = bool(svc.test_connection())
    summary["connection_ok"] = connected

    params = {
        "date_from": date_from,
        "date_to": date_to,
        "limit": patient_limit,
        "offset": 0,
        "include_study_count": True,
        "include_latest_study": True,
    }

    t0 = time.perf_counter()
    patients = svc.search_patients_sync(params) or []
    search_ms = (time.perf_counter() - t0) * 1000.0
    summary["search"] = {
        "returned_patients": len(patients),
        "latency_ms": round(search_ms, 2),
    }

    uids = []
    for row in patients:
        uid = _extract_uid(row)
        if uid and uid not in uids:
            uids.append(uid)
        if len(uids) >= study_limit:
            break
    summary["unique_study_uids"] = len(uids)

    server = get_socket_server_settings() or {}
    host = server.get("host") or server.get("socket_host")
    port = int(server.get("port") or server.get("socket_port") or 50052)
    summary["socket_target"] = {"host": host, "port": port}

    # Stage 2: single pass per study
    per_study = []
    for uid in uids:
        result = _thumbnail_fetch(host, port, uid, include_image_data=False, timeout=20)
        per_study.append(result)

    summary["per_study"] = {
        "ok": sum(1 for item in per_study if item["ok"]),
        "failed": sum(1 for item in per_study if not item["ok"]),
        "zero_series": sum(1 for item in per_study if item["ok"] and item["series_count"] == 0),
        "avg_latency_ms": round(mean([item["latency_ms"] for item in per_study]) if per_study else 0.0, 2),
        "max_latency_ms": round(max([item["latency_ms"] for item in per_study]) if per_study else 0.0, 2),
        "samples": per_study,
    }

    # Stage 3: DM readiness heuristic (series must be present)
    summary["dm_readiness"] = {
        "ready_studies": sum(1 for item in per_study if item["ok"] and item["series_count"] > 0),
        "not_ready_studies": sum(1 for item in per_study if (not item["ok"]) or item["series_count"] == 0),
    }

    # Stage 4: sequential pressure test
    seq_lat = []
    seq_fail = 0
    if uids:
        for i in range(sequential_requests):
            uid = uids[i % len(uids)]
            result = _thumbnail_fetch(host, port, uid, include_image_data=False, timeout=20)
            seq_lat.append(result["latency_ms"])
            if (not result["ok"]) or result["series_count"] == 0:
                seq_fail += 1

    summary["sequential_pressure"] = {
        "requests": sequential_requests,
        "failures": seq_fail,
        "failure_rate_pct": round((seq_fail / sequential_requests) * 100.0, 2) if sequential_requests else 0.0,
        "avg_latency_ms": round(mean(seq_lat), 2) if seq_lat else 0.0,
        "max_latency_ms": round(max(seq_lat), 2) if seq_lat else 0.0,
    }

    # Stage 5: concurrent pressure test
    conc_fail = 0
    conc_lat = []
    conc_n = min(sequential_requests, max(10, len(uids) * 4)) if uids else 0
    if conc_n > 0:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = []
            for i in range(conc_n):
                uid = uids[i % len(uids)]
                futures.append(ex.submit(_thumbnail_fetch, host, port, uid, False, 20))

            for future in as_completed(futures):
                result = future.result()
                conc_lat.append(result["latency_ms"])
                if (not result["ok"]) or result["series_count"] == 0:
                    conc_fail += 1

    summary["concurrent_pressure"] = {
        "requests": conc_n,
        "workers": workers,
        "failures": conc_fail,
        "failure_rate_pct": round((conc_fail / conc_n) * 100.0, 2) if conc_n else 0.0,
        "avg_latency_ms": round(mean(conc_lat), 2) if conc_lat else 0.0,
        "max_latency_ms": round(max(conc_lat), 2) if conc_lat else 0.0,
    }

    # Stage 6: one include_image_data=True probe for comparison
    probe = {"uid": "", "ok": False, "series_count": 0, "latency_ms": 0.0}
    if uids:
        probe = _thumbnail_fetch(host, port, uids[0], include_image_data=True, timeout=20)
    summary["include_image_data_true_probe"] = probe

    return summary


def main():
    parser = argparse.ArgumentParser(description="Audit socket patient->thumbnail pipeline stability")
    parser.add_argument("--date-from", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--date-to", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--patient-limit", type=int, default=50)
    parser.add_argument("--study-limit", type=int, default=15)
    parser.add_argument("--sequential-requests", type=int, default=80)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    summary = run_audit(
        date_from=args.date_from,
        date_to=args.date_to,
        patient_limit=args.patient_limit,
        study_limit=args.study_limit,
        sequential_requests=args.sequential_requests,
        workers=args.workers,
    )

    text = json.dumps(summary, indent=2)
    print(text)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)


if __name__ == "__main__":
    main()
