# -*- coding: utf-8 -*-
"""
Stage 0 diagnostic probe — capture ONE real GetPatientList socket payload.
==========================================================================

WHY THIS EXISTS
    Architecture investigation only. It confirms whether the socket
    `GetPatientList` response carries reporting-physician / report-status data,
    and under which field names (report / imagingWorkflow.report / radiologist /
    actor IDs). It answers the open question from the hybrid-architecture
    analysis without changing any AI-PACS production code.

WHAT IT DOES (read-only)
    1. Connects to the same socket server AI-PACS uses.
    2. Logs in with credentials YOU type at the prompt.
    3. Sends ONE `GetPatientList` request (the same params AI-PACS uses).
    4. Writes a PHI-safe, sanitized capture to:
           user_data/logs/stage0_getpatientlist_probe.json
    It performs no writes to the server and modifies no AI-PACS code.

SAFETY
    - Standalone & throwaway — delete this file after the capture.
    - PHI-safe: patient names, birth dates, addresses, phone numbers, and long
      free-text (descriptions / comments / findings) are redacted or omitted.
      Patient IDs are masked. Only report/reporter-related structure is kept.
    - Credentials are read with getpass (hidden), used only to Login, and are
      never stored, printed, or written to disk.

USAGE
    From the AI-PACS repo root, in the project's Python environment (the same
    interpreter VS Code uses to run main.py):

        python stage0_getpatientlist_probe.py
        # optional host/port override:
        python stage0_getpatientlist_probe.py <host> <port>

    Enter your PACS username / password when prompted.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from datetime import datetime

# --- Make the repo modules importable regardless of CWD ----------------------
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

# --- PHI-safety configuration ------------------------------------------------
# Keys whose values must never be written out (substring match, case-insensitive).
_HARD_REDACT = (
    "patientname", "patient_name", "birthdate", "birth_date", "patientbirth",
    "patientaddress", "address", "nationalid", "national_id", "phone", "mobile",
    "fathername", "father_name",
)
# Keys that hold long free-text — replace value with a length placeholder.
_LONG_TEXT = ("content", "findings", "comment", "description", "text", "note")
# Report/reporter-related keys we explicitly want to surface at the top level.
_REPORTER_KEYS = (
    "report", "imagingWorkflow", "report_status", "reportStatus",
    "latest_study_report_status", "radiologist", "radiologist_name",
    "radiologistName", "reporting_physician", "reporting_physician_name",
    "reportingPhysician", "reportingPhysicianName", "physician", "doctor",
)
_MAX_STR = 120          # strings longer than this are omitted
_MAX_LIST_ITEMS = 3     # only sanitize the first N items of any list
_MAX_PATIENTS = 12      # low-noise: only capture the first N patients


def _mask_id(value: object) -> str:
    s = str(value or "")
    return ("*" * max(0, len(s) - 3)) + s[-3:] if s else ""


def _san(obj: object, key_hint: str = "", depth: int = 0):
    """Recursively sanitize a payload fragment (PHI-safe, structure-preserving)."""
    kl = str(key_hint or "").lower()
    if any(tok in kl for tok in _HARD_REDACT):
        return "<redacted-PHI>"
    if kl in ("patient_id", "patientid", "pid"):
        return _mask_id(obj)
    if depth > 8:
        return "<max-depth>"
    if isinstance(obj, dict):
        return {k: _san(v, k, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        out = [_san(v, key_hint, depth + 1) for v in obj[:_MAX_LIST_ITEMS]]
        if len(obj) > _MAX_LIST_ITEMS:
            out.append(f"<+{len(obj) - _MAX_LIST_ITEMS} more items>")
        return out
    if isinstance(obj, str):
        if any(tok in kl for tok in _LONG_TEXT) and len(obj) > 40:
            return f"<omitted text len={len(obj)}>"
        if len(obj) > _MAX_STR:
            return f"<omitted str len={len(obj)}>"
        return obj
    return obj


def _resolve_report_status(p: dict) -> str:
    for k in ("report_status", "reportStatus", "latest_study_report_status"):
        v = p.get(k)
        if v:
            return str(v)
    rep = p.get("report")
    if isinstance(rep, dict) and rep.get("status"):
        return str(rep.get("status"))
    iw = p.get("imagingWorkflow")
    if isinstance(iw, dict) and isinstance(iw.get("report"), dict):
        if iw["report"].get("status"):
            return str(iw["report"]["status"])
    return ""


def _patient_report_view(p: dict) -> dict:
    """A compact, PHI-safe view of one patient's report/reporter structure."""
    if not isinstance(p, dict):
        return {"_not_a_dict": True}
    view = {
        "top_level_keys": sorted(p.keys()),
        "patient_id_masked": _mask_id(p.get("patient_id") or p.get("PatientID")),
        "report_status_resolved": _resolve_report_status(p),
        "has_report_object": isinstance(p.get("report"), dict),
        "has_imagingWorkflow": "imagingWorkflow" in p,
    }
    if isinstance(p.get("report"), dict):
        view["report"] = _san(p["report"], "report")
    iw = p.get("imagingWorkflow")
    if isinstance(iw, dict):
        view["imagingWorkflow_keys"] = sorted(iw.keys())
        if isinstance(iw.get("report"), dict):
            view["imagingWorkflow_report"] = _san(iw["report"], "report")
    reporter_top = {}
    for k in _REPORTER_KEYS:
        if k in ("report", "imagingWorkflow"):
            continue
        if k in p:
            reporter_top[k] = _san(p[k], k)
    if reporter_top:
        view["reporter_fields_top_level"] = reporter_top
    for sk in ("studies", "study_list"):
        studies = p.get(sk)
        if isinstance(studies, list) and studies and isinstance(studies[0], dict):
            view[f"{sk}_first_item"] = _san(studies[0], "")
            break
    return view


def main() -> int:
    settings = get_socket_server_settings() or {}
    host = settings.get("host") or "localhost"
    port = int(settings.get("port") or 50052)
    if len(sys.argv) >= 2:
        host = sys.argv[1]
    if len(sys.argv) >= 3:
        port = int(sys.argv[2])

    print("=" * 64)
    print("Stage 0 — GetPatientList payload probe (read-only, PHI-safe)")
    print("=" * 64)
    print(f"Socket target : {host}:{port}")
    print("If that host/port looks wrong, re-run as:")
    print("    python stage0_getpatientlist_probe.py <host> <port>")
    print("-" * 64)

    username = input("PACS username: ").strip()
    password = getpass.getpass("PACS password (hidden): ")
    if not username or not password:
        print("[probe] No credentials entered — aborting.")
        return 1

    client = PatientListSocketClient(host=host, port=port, timeout=20)

    print("[probe] Logging in ...")
    login_resp = client.send_request("Login", {"username": username, "password": password})
    password = "x" * 8  # drop the plaintext reference promptly
    if not isinstance(login_resp, dict):
        print("[probe] ERROR: no/invalid Login response (connection or host/port issue).")
        return 1
    token = login_resp.get("token")
    if not token and isinstance(login_resp.get("data"), dict):
        token = login_resp["data"].get("token")
    status = str(login_resp.get("status") or "")
    if not token:
        print(f"[probe] ERROR: Login did not return a token (status={status!r}, "
              f"message={login_resp.get('message') or login_resp.get('error')!r}).")
        return 1
    get_socket_token_manager().set_token(str(token))
    print("[probe] Login OK — token acquired.")

    params = {"limit": 100, "offset": 0, "include_study_count": True,
              "include_latest_study": True}
    print(f"[probe] Sending GetPatientList {params} ...")
    resp = client.send_request("GetPatientList", params)
    try:
        client.disconnect()
    except Exception:
        pass

    if not isinstance(resp, dict):
        print("[probe] ERROR: no/invalid GetPatientList response.")
        return 1

    data = resp.get("data")
    if isinstance(data, dict):
        patients = data.get("patients") or []
        data_shape = {"type": "dict", "keys": sorted(data.keys())}
    elif isinstance(data, list):
        patients = data
        data_shape = {"type": "list"}
    else:
        patients = []
        data_shape = {"type": type(data).__name__}

    patients = [p for p in patients if isinstance(p, dict)]
    completed = [p for p in patients
                 if _resolve_report_status(p).strip().lower() in ("completed", "complete")]
    non_completed = [p for p in patients
                     if _resolve_report_status(p).strip().lower() not in ("completed", "complete")]

    capture = {
        "_meta": {
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "socket_target": f"{host}:{port}",
            "purpose": "Stage 0 architecture investigation — PHI-safe",
        },
        "envelope": {
            "response_keys": sorted(resp.keys()),
            "status": resp.get("status"),
            "data_shape": data_shape,
        },
        "totals": {
            "patients_returned": len(patients),
            "completed_report": len(completed),
            "non_completed_report": len(non_completed),
        },
        "sample_completed_report_patient": (
            _patient_report_view(completed[0]) if completed else None),
        "sample_non_completed_report_patient": (
            _patient_report_view(non_completed[0]) if non_completed else None),
        "first_patients_report_view": [
            _patient_report_view(p) for p in patients[:_MAX_PATIENTS]
        ],
    }

    out_dir = os.path.join(_REPO_ROOT, "user_data", "logs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "stage0_getpatientlist_probe.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(capture, fh, ensure_ascii=False, indent=2)

    print("-" * 64)
    print(f"[probe] patients returned : {len(patients)}")
    print(f"[probe] completed reports : {len(completed)}")
    print(f"[probe] non-completed     : {len(non_completed)}")
    print(f"[probe] capture written   : {out_path}")
    print("-" * 64)
    print("Done. Share the JSON file above (it is PHI-safe). "
          "You may delete this probe script afterwards.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[probe] Cancelled.")
        sys.exit(130)
