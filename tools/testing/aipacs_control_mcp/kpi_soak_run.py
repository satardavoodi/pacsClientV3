# -*- coding: utf-8 -*-
"""kpi_soak_run — stability soak of the download optimizations + yield.

Cycle 1: restart → open fresh P1 (steady-state check: NO probe, prewarm reuse)
         → open fresh P2 → at ~2.5 s drop its LAST series (mid-download)
         → measure batch-boundary yield: intent file, yield log, critical
           first file, no new normal batches before it, drop render.
Cycle 2: restart → open fresh P3 → FIRST open of the session must show NO
         probe (persisted capability cache) and prewarm reuse.
Correctness: per-tab uid, downloads completed, no duplicate batches, yielded
series not marked failed, queue stats. Output → ui_probe_runs/<ts>_soak/.
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

import lifecycle  # noqa: E402

R = Path(r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version")
LOGDIR = R / "user_data" / "logs"
OUT = HERE / "ui_probe_runs" / (time.strftime("%Y%m%d_%H%M%S") + "_soak")
SUM: dict = {"out": str(OUT), "cycles": {}}


def flush():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(
        json.dumps(SUM, indent=1, default=str), encoding="utf-8")


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
    except Exception as exc:
        print("freshness check failed:", exc)
    return uids


def grep_window(t0: float, t1: float, pattern: str, logs=None) -> list:
    rx = re.compile(pattern)
    rows = []
    for lg in logs or ("app.log", "download_diagnostics.log"):
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
    from client import AipacsControlClient

    local = _local_uids()
    SUM["local_studies"] = len(local)
    flush()

    def fresh_rows(c):
        r = c.send("list_patients", {"modality": "CT", "date_from": "20260601",
                                     "date_to": "20260605", "source": "server"},
                   timeout_ms=90000)
        rows = [x for x in ((r.get("data") or {}).get("rows") or [])
                if "CT" in str(x.get("modalities") or "").upper()
                and str(x.get("study_uid")) not in local
                and (x.get("series_count") or 0) >= 3]
        rows.sort(key=lambda x: -(x.get("series_count") or 0))
        return rows

    def ent(p):
        return {"patient_id": p["patient_id"],
                "patient_name": p.get("patient_name", ""),
                "study_uid": p["study_uid"]}

    # ════ CYCLE 1 ════════════════════════════════════════════════════
    cyc = SUM["cycles"]["c1"] = {}
    lifecycle.stop_app(force=False)
    res = lifecycle.launch_app(wait_ready_s=200)
    cyc["launch_ok"] = res.get("ok")
    flush()
    if not res.get("ok"):
        return
    c = AipacsControlClient()
    rows = fresh_rows(c)
    cyc["fresh"] = [(x["patient_id"], x.get("series_count")) for x in rows[:4]]
    flush()
    if len(rows) < 2:
        cyc["error"] = "not enough fresh patients"
        flush()
        return
    P1, P2 = rows[0], rows[1]

    # Open P1 — steady-state open (cache means no probe even on 1st open)
    t0 = time.time()
    c.send("open_patient", ent(P1), timeout_ms=90000)
    time.sleep(8.0)
    cyc["p1"] = {"pid": P1["patient_id"], "t0": t0}
    cyc["p1"]["probe_lines"] = grep_window(t0, time.time(), r"GetStudyInfo")
    cyc["p1"]["prewarm"] = grep_window(t0, time.time(), r"Reused pre-warmed|PREWARM\] spawned")
    cyc["p1"]["queue_ms"] = next((r["t"] * 1000 for r in grep_window(
        t0, time.time(), r"FAST-SERIES-DOWNLOAD-QUEUE")), None)
    cyc["p1"]["first_file_ms"] = next((r["t"] * 1000 for r in grep_window(
        t0, time.time(), r"series_images_progress")), None)
    flush()

    # Open P2 and drop its LAST series mid-download
    t2 = time.time()
    c.send("open_patient", ent(P2), timeout_ms=90000)
    time.sleep(2.5)
    si = c.send("get_series_info", {}, timeout_ms=60000)
    series = ((si.get("data") or {}).get("series") or [])
    cyc["p2"] = {"pid": P2["patient_id"], "t0": t2, "n_series": len(series)}
    if series:
        late = series[-1]["series_number"]
        d0 = time.time()
        c.send("change_series", {"series_number": late, "viewport": 0},
               timeout_ms=90000)
        cyc["p2"]["dropped"] = late
        cyc["p2"]["drop_t0"] = d0
        # poll for render of the dropped series
        render_s = None
        for _ in range(40):
            time.sleep(1.5)
            vp = (c.send("query_viewport_state", {}, timeout_ms=60000).get("data") or {})
            v0 = (vp.get("viewports") or [{}])[0]
            if (v0.get("slice_count") or 0) > 0 and not v0.get("awaiting_series"):
                render_s = round(time.time() - d0, 2)
                cyc["p2"]["viewport"] = v0
                break
        cyc["p2"]["drop_render_s"] = render_s
        t_end = time.time()
        cyc["p2"]["yield_log"] = grep_window(d0 - 0.5, t_end, r"Yielding after batch|YIELDED|critical_intent|intent file")
        cyc["p2"]["intent_writes"] = grep_window(d0 - 0.5, t_end, r"signalled to the RUNNING worker")
        cyc["p2"]["teardown_preempts"] = grep_window(d0 - 0.5, t_end, r"Preempting current study worker|download_batch cancelled")
        cyc["p2"]["drop_first_file"] = next((r for r in grep_window(
            d0, t_end, rf"series_images_progress series={late} ")), None)
        # ordering check:批 batches AFTER yield must be the dropped series first
        cyc["p2"]["post_yield_series"] = [r["line"][:90] for r in grep_window(
            d0, t_end, r"Downloading series \d+")][:6]
    cyc["final_downloads"] = c.send("download_statistics", {}, timeout_ms=60000).get("data")
    # per-tab identity
    per_tab = []
    for idx in (2, 3):
        c.send("switch_tab", {"index": idx}, timeout_ms=60000)
        time.sleep(1.0)
        d = c.send("get_series_info", {}, timeout_ms=60000).get("data") or {}
        per_tab.append({"tab": idx, "uid": str(d.get("study_uid") or "")[-10:],
                        "n_series": len(d.get("series") or [])})
    cyc["per_tab"] = per_tab
    expected = {str(P1["study_uid"])[-10:], str(P2["study_uid"])[-10:]}
    cyc["no_mixing"] = {t["uid"] for t in per_tab} == expected
    flush()
    c.close()

    # ════ CYCLE 2: restart → first open must skip probe ══════════════
    cyc2 = SUM["cycles"]["c2"] = {}
    lifecycle.stop_app(force=False)
    res = lifecycle.launch_app(wait_ready_s=200)
    cyc2["launch_ok"] = res.get("ok")
    flush()
    if not res.get("ok"):
        return
    c = AipacsControlClient()
    rows = fresh_rows(c)
    if not rows:
        cyc2["error"] = "no fresh patient left"
        flush()
        c.close()
        return
    P3 = rows[0]
    t0 = time.time()
    c.send("open_patient", ent(P3), timeout_ms=90000)
    time.sleep(8.0)
    cyc2["p3"] = {"pid": P3["patient_id"]}
    cyc2["p3"]["probe_lines"] = grep_window(t0, time.time(), r"GetStudyInfo")
    cyc2["p3"]["prewarm"] = grep_window(t0, time.time(), r"Reused pre-warmed|PREWARM\] spawned")
    cyc2["p3"]["queue_ms"] = next((r["t"] * 1000 for r in grep_window(
        t0, time.time(), r"FAST-SERIES-DOWNLOAD-QUEUE")), None)
    cyc2["p3"]["first_file_ms"] = next((r["t"] * 1000 for r in grep_window(
        t0, time.time(), r"series_images_progress")), None)
    # duplicate-request check for P3's study
    cyc2["p3"]["thumbnail_fetches"] = len(grep_window(
        t0, time.time(), r"GetStudyThumbnails"))
    cyc2["final_downloads"] = c.send("download_statistics", {}, timeout_ms=60000).get("data")
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
