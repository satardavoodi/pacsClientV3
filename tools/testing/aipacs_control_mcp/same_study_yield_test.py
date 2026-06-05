# -*- coding: utf-8 -*-
"""same_study_yield_test — dedicated check of the batch-boundary yield.

Waits for ALL current downloads to finish (so nothing else holds the slot),
opens ONE fresh patient, waits until its own download is mid-flight, drops
the LAST series, then verifies from logs:
  * intent file written + 'signalled to the RUNNING worker' (no teardown)
  * NO 'download_batch cancelled' / 'Preempting current study worker'
  * subprocess 'Yielding after batch N' + dropped series next
  * current series resumes after the critical one (R19 skip)
Output → ui_probe_runs/<ts>_yield/summary.json
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

R = Path(r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version")
LOGDIR = R / "user_data" / "logs"
OUT = HERE / "ui_probe_runs" / (time.strftime("%Y%m%d_%H%M%S") + "_yield")
SUM: dict = {"out": str(OUT)}

TARGET_PID = ""  # empty → auto-pick the first FRESH patient (no local instances)


def _local_uids() -> set:
    import sqlite3
    uids = set()
    try:
        conn = sqlite3.connect(f"file:{R / 'user_data/database/dicom.db'}?mode=ro",
                               uri=True, timeout=3.0)
        try:
            cur = conn.execute(
                "SELECT DISTINCT st.study_uid FROM studies st "
                "JOIN series se ON se.study_fk = st.study_pk "
                "JOIN instances i ON i.series_fk = se.series_pk")
            uids = {str(r[0]) for r in cur.fetchall()}
        finally:
            conn.close()
    except Exception:
        pass
    return uids


def flush():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(
        json.dumps(SUM, indent=1, default=str), encoding="utf-8")


def grep_window(t0: float, t1: float, pattern: str) -> list:
    rx = re.compile(pattern)
    rows = []
    for lg in ("app.log", "download_diagnostics.log"):
        p = LOGDIR / lg
        if not p.exists():
            continue
        data = p.read_bytes()[-9_000_000:].decode("utf-8", "replace")
        for ln in data.splitlines():
            m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)", ln)
            if not m:
                continue
            try:
                ts = datetime.strptime(m.group(1)[:26], "%Y-%m-%d %H:%M:%S.%f").timestamp()
            except ValueError:
                continue
            if t0 <= ts <= t1 and rx.search(ln):
                rows.append({"t": round(ts - t0, 2), "line": ln.split(" | ")[-1][:170]})
    rows.sort(key=lambda x: x["t"])
    return rows


def main() -> None:
    import os

    # Singleton guard: a stray duplicate of this script (argv-replay child,
    # observed 2026-06-05) must not race the measurement.
    lock = Path(os.environ.get("TEMP", ".")) / "same_study_yield_test.lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        try:
            age = time.time() - lock.stat().st_mtime
        except Exception:
            age = 0
        if age < 600:
            SUM["error"] = "another instance is running (singleton lock)"
            flush()
            return
        lock.unlink(missing_ok=True)
        return main()
    import atexit
    atexit.register(lambda: lock.unlink(missing_ok=True))

    if os.environ.get("YIELD_TEST_SKIP_RESTART", "") != "1":
        # Clean restart so the coordinator yield change is live.
        import lifecycle
        SUM["restart"] = {"stop": lifecycle.stop_app(force=False).get("ok")}
        res = lifecycle.launch_app(wait_ready_s=200)
        SUM["restart"]["launch_ok"] = res.get("ok")
        flush()
        if not res.get("ok"):
            return
    else:
        SUM["restart"] = "skipped (YIELD_TEST_SKIP_RESTART=1)"
        flush()

    from client import AipacsControlClient
    c = AipacsControlClient()

    def q(action, ent=None, timeout=90000):
        return c.send(action, ent or {}, timeout_ms=timeout)

    # 1) wait for the slot to be idle (all current downloads done)
    for k in range(60):  # up to 5 min
        d = (q("download_statistics").get("data") or {})
        if not (d.get("active") or 0):
            break
        time.sleep(5.0)
    SUM["pre_dl"] = q("download_statistics").get("data")
    flush()

    # 2) open the fresh patient
    r = q("list_patients", {"modality": "CT", "date_from": "20260601",
                            "date_to": "20260605", "source": "server"})
    all_rows = (r.get("data") or {}).get("rows") or []
    if TARGET_PID:
        rows = [x for x in all_rows if str(x.get("patient_id")) == TARGET_PID]
    else:
        local = _local_uids()
        rows = [x for x in all_rows
                if "CT" in str(x.get("modalities") or "").upper()
                and str(x.get("study_uid")) not in local
                and (x.get("series_count") or 0) >= 4]
        rows.sort(key=lambda x: -(x.get("series_count") or 0))
        if not rows:
            # CT pool exhausted — fall back to fresh MRI studies.
            r2 = q("list_patients", {"modality": "MRI", "date_from": "20260601",
                                     "date_to": "20260605", "source": "server"})
            mri = (r2.get("data") or {}).get("rows") or []
            rows = [x for x in mri
                    if str(x.get("study_uid")) not in local
                    and (x.get("series_count") or 0) >= 4]
            rows.sort(key=lambda x: -(x.get("series_count") or 0))
            SUM["modality_fallback"] = "MRI"
    if not rows:
        SUM["error"] = "no fresh patient available"
        flush()
        return
    P = rows[0]
    SUM["patient"] = P["patient_id"]
    t0 = time.time()
    q("open_patient", {"patient_id": P["patient_id"],
                       "patient_name": P.get("patient_name", ""),
                       "study_uid": P["study_uid"]})
    SUM["open_t0"] = t0
    time.sleep(3.5)  # own download mid-flight; nothing else active

    si = q("get_series_info")
    series = ((si.get("data") or {}).get("series") or [])
    SUM["n_series"] = len(series)
    if not series:
        SUM["error"] = "no series bound"
        flush()
        return
    late = series[-1]["series_number"]
    SUM["dropped"] = late
    d0 = time.time()
    q("change_series", {"series_number": late, "viewport": 0})
    SUM["drop_rel_s"] = round(d0 - t0, 2)

    # intent file path (the GUI writes it ~instantly on the drop)
    try:
        from PacsClient.utils.config import SOURCE_PATH
        intent_path = Path(SOURCE_PATH) / str(P["study_uid"]) / ".critical_intent.json"
    except Exception:
        intent_path = None

    # 3) poll for the dropped series' first file + render (+ intent lifecycle)
    first_file_s = None
    render_s = None
    intent_seen_s = None
    intent_consumed_s = None
    for _ in range(40):
        time.sleep(1.0)
        if intent_path is not None:
            exists = intent_path.exists()
            if exists and intent_seen_s is None:
                intent_seen_s = round(time.time() - d0, 2)
            if (not exists) and intent_seen_s is not None and intent_consumed_s is None:
                intent_consumed_s = round(time.time() - d0, 2)
        if first_file_s is None:
            ff = grep_window(d0, time.time(),
                             rf"series_images_progress series={late} ")
            if ff:
                first_file_s = ff[0]["t"]
        vp = (q("query_viewport_state").get("data") or {})
        v0 = (vp.get("viewports") or [{}])[0]
        if (v0.get("slice_count") or 0) > 0 and not v0.get("awaiting_series"):
            render_s = round(time.time() - d0, 2)
            SUM["viewport"] = v0
            break
    t_end = time.time()
    SUM["drop_first_file_s"] = first_file_s
    SUM["drop_render_s"] = render_s
    SUM["intent_file_seen_s"] = intent_seen_s
    SUM["intent_file_consumed_s"] = intent_consumed_s

    # 4) log evidence (coordinator logs at WARNING → download_diagnostics)
    SUM["intent_signalled"] = grep_window(
        d0 - 0.5, t_end, r"Series yield:|signalled via intent file|signalled to the RUNNING worker")
    SUM["yield_lines"] = grep_window(d0 - 0.5, t_end, r"Yielding after batch|YIELDED: series")
    SUM["teardown_lines"] = grep_window(d0 - 0.5, t_end,
                                        r"download_batch cancelled|Preempting current study worker|Series interrupt")
    SUM["series_order_after_drop"] = [f"t+{r['t']}s {r['line'][:80]}" for r in grep_window(
        d0, t_end + 1, r"Downloading series \d+|SKIPPED: Series|Series \d+ complete")][:10]
    SUM["final_dl"] = q("download_statistics").get("data")
    flush()
    c.close()
    print("done ->", OUT)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        SUM["exception"] = traceback.format_exc()
        flush()
