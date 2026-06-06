# -*- coding: utf-8 -*-
"""
Patient study / series structure probe (read-only, PHI-safe).
=============================================================

WHY THIS EXISTS
    Multi-study patients (e.g. 42471, 43346) lose studies somewhere between
    the server and the viewer. Before changing client code we must see how
    the server ACTUALLY represents these patients: how many studies, how
    many series per study, body parts, and image/series counts.

WHAT IT DOES (read-only — no writes to server, no AI-PACS code changed)
    1. Logs in via the PACS socket (credentials typed at the prompt).
    2. For each patient ID you pass, calls `GetPatientList` filtered by that
       patient and dumps the patient row(s): study_uids, total_studies,
       count_of_series, count_of_instances, body_parts, modalities.
    3. For every study UID found, calls `get_study_thumbnails` and dumps the
       per-study series structure: series count, and for each series its
       number, description, modality, body part and image_count.
    4. Writes a PHI-safe capture to
           user_data/logs/probe_patient_structure.json

USAGE
    From the repo root, in the project's Python environment (the same
    interpreter VS Code uses to run main.py):

        python probe_patient_structure.py 42471 43346

    Enter your PACS username / password when prompted.
    Delete this file after the capture — it is a throwaway diagnostic.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from datetime import datetime

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from modules.network.socket_client import PatientListSocketClient
    from modules.network.socket_config import get_socket_server_settings
    from modules.network.socket_token_manager import get_socket_token_manager
except Exception as exc:  # pragma: no cover - environment issue
    print(f"[probe] ERROR importing AI-PACS network modules: {exc}")
    print("[probe] Run this from the AI-PACS repo root with the project Python.")
    sys.exit(1)

# --- PHI-safety: redact patient identifiers; keep study/series structure ----
_HARD_REDACT = (
    "patientname", "patient_name", "birthdate", "birth_date", "patientbirth",
    "patientbirthdate", "patientaddress", "address", "nationalid",
    "national_id", "phone", "mobile", "fathername", "father_name",
)
_MAX_LIST = 30


def _mask_id(value: object) -> str:
    s = str(value or "")
    return ("*" * max(0, len(s) - 3)) + s[-3:] if s else ""


def _san(obj: object, key: str = "", depth: int = 0):
    """Recursively sanitize: redact patient PHI, keep study/series structure."""
    kl = str(key or "").lower()
    if any(tok in kl for tok in _HARD_REDACT):
        return "<redacted-PHI>"
    if kl in ("patient_id", "patientid", "pid"):
        return _mask_id(obj)
    if depth > 12:
        return "<max-depth>"
    if isinstance(obj, dict):
        return {k: _san(v, k, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        out = [_san(v, key, depth + 1) for v in obj[:_MAX_LIST]]
        if len(obj) > _MAX_LIST:
            out.append(f"<+{len(obj) - _MAX_LIST} more>")
        return out
    if isinstance(obj, str) and len(obj) > 200:
        return f"<str len={len(obj)}>"
    return obj


def _study_uids_of(patient: dict) -> list:
    uids = patient.get("study_uids") or []
    if isinstance(uids, str):
        uids = [uids]
    elif not isinstance(uids, list):
        uids = []
    result = []
    for u in uids:
        u = str(u or "").strip()
        if u and u not in result:
            result.append(u)
    latest = str(patient.get("latest_study_uid") or "").strip()
    if latest and latest not in result:
        result.append(latest)
    return result


def main() -> int:
    settings = get_socket_server_settings() or {}
    host = settings.get("host") or "localhost"
    port = int(settings.get("port") or 50052)
    pids = [a.strip() for a in sys.argv[1:] if a.strip()] or ["42471", "43346"]

    print("=" * 68)
    print("Patient study / series structure probe (read-only, PHI-safe)")
    print("=" * 68)
    print(f"Socket target : {host}:{port}")
    print(f"Patients      : {pids}")
    print("-" * 68)

    username = input("PACS username: ").strip()
    password = getpass.getpass("PACS password (hidden): ")
    if not username or not password:
        print("[probe] No credentials entered — aborting.")
        return 1

    client = PatientListSocketClient(host=host, port=port, timeout=25)
    print("[probe] Logging in ...")
    login = client.send_request("Login", {"username": username, "password": password})
    password = "x" * 8
    if not isinstance(login, dict):
        print("[probe] ERROR: no/invalid Login response (connection/host/port).")
        return 1
    token = login.get("token")
    if not token and isinstance(login.get("data"), dict):
        token = login["data"].get("token")
    if not token:
        print(f"[probe] ERROR: Login returned no token "
              f"(status={login.get('status')!r}, "
              f"message={login.get('message') or login.get('error')!r}).")
        return 1
    get_socket_token_manager().set_token(str(token))
    print("[probe] Login OK.")

    capture = {
        "_meta": {
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "socket_target": f"{host}:{port}",
            "purpose": "Server study/series structure for multi-study patients",
        },
        "patients": [],
    }

    for pid in pids:
        print(f"\n[probe] ===== patient {pid} =====")
        entry: dict = {"patient_id_masked": _mask_id(pid)}

        # 1) GetPatientList filtered by this patient.
        pl = client.send_request("GetPatientList", {
            "patient_id": pid, "limit": 50, "offset": 0,
            "include_study_count": True, "include_latest_study": True,
        })
        patients = []
        if isinstance(pl, dict):
            data = pl.get("data")
            if isinstance(data, dict):
                patients = data.get("patients") or []
            elif isinstance(data, list):
                patients = data
        patients = [p for p in (patients or []) if isinstance(p, dict)]

        entry["getpatientlist_envelope_keys"] = sorted(pl.keys()) if isinstance(pl, dict) else []
        entry["getpatientlist_row_count"] = len(patients)

        study_uids: list = []
        rows_view = []
        for p in patients:
            for u in _study_uids_of(p):
                if u not in study_uids:
                    study_uids.append(u)
            raw_uids = p.get("study_uids")
            rows_view.append({
                "top_level_keys": sorted(p.keys()),
                "total_studies": p.get("total_studies"),
                "study_uids_count": (len(raw_uids) if isinstance(raw_uids, list)
                                     else (1 if raw_uids else 0)),
                "count_of_series": p.get("count_of_series"),
                "count_of_instances": p.get("count_of_instances"),
                "body_parts": p.get("body_parts"),
                "modalities": p.get("modalities"),
                "sanitized_patient_object": _san(p, ""),
            })
        entry["getpatientlist_rows"] = rows_view
        entry["resolved_study_uids"] = list(study_uids)

        # 2) Per-study series structure.
        studies = []
        for su in study_uids:
            st: dict = {"study_uid": su}
            try:
                data = client.get_study_thumbnails(
                    su, include_base64=False, include_image_data=False,
                )
                if isinstance(data, dict):
                    series = [s for s in (data.get("series_thumbnails") or [])
                              if isinstance(s, dict)]
                    st["response_keys"] = sorted(data.keys())
                    st["study_date"] = data.get("study_date")
                    st["study_description"] = data.get("study_description")
                    st["series_count"] = len(series)
                    st["series"] = [
                        {
                            "series_number": s.get("series_number"),
                            "series_uid": s.get("series_uid"),
                            "series_description": s.get("series_description"),
                            "modality": s.get("modality"),
                            "image_count": s.get("image_count"),
                            "body_part": (s.get("body_part_examined")
                                          or s.get("body_part")),
                            "all_keys": sorted(s.keys()),
                        }
                        for s in series
                    ]
                else:
                    st["error"] = "no / invalid get_study_thumbnails response"
            except Exception as exc:
                st["error"] = f"{type(exc).__name__}: {exc}"
            studies.append(st)
        entry["studies"] = studies

        # Console summary.
        print(f"  GetPatientList: {len(patients)} row(s)")
        for rv in rows_view:
            print(f"    total_studies={rv['total_studies']} "
                  f"study_uids_count={rv['study_uids_count']} "
                  f"count_of_series={rv['count_of_series']} "
                  f"count_of_instances={rv['count_of_instances']}")
            print(f"    body_parts={rv['body_parts']} modalities={rv['modalities']}")
        print(f"  resolved study UIDs: {len(study_uids)}")
        for st in studies:
            tail = st["study_uid"][-24:]
            if "error" in st:
                print(f"    study …{tail}: ERROR {st['error']}")
            else:
                bps = sorted({
                    str(s.get("body_part") or s.get("series_description") or "?")
                    for s in st.get("series", [])
                })
                imgs = sum(int(s.get("image_count") or 0) for s in st.get("series", []))
                print(f"    study …{tail}: series={st['series_count']} "
                      f"images={imgs} body_parts~={bps}")

        capture["patients"].append(entry)

    try:
        client.disconnect()
    except Exception:
        pass

    out_dir = os.path.join(_REPO_ROOT, "user_data", "logs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "probe_patient_structure.json")
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(capture, fh, indent=2, ensure_ascii=False)
        print(f"\n[probe] Capture written to: {out_path}")
    except Exception as exc:
        print(f"\n[probe] Could not write capture file: {exc}")
        print(json.dumps(capture, indent=2, ensure_ascii=False)[:6000])

    print("[probe] Done. Share the JSON (or the console summary above).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[probe] Interrupted.")
        sys.exit(1)
