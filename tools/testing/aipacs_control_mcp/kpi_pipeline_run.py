# -*- coding: utf-8 -*-
"""kpi_pipeline_run — per-phase timing of double-click open + drag-drop.

Clean-slate restart, then on FRESH (never-downloaded) patients:
  A) open_patient  → poll viewport until first image renders
  B) open second patient → after 2.5 s drop its LAST (undownloaded) series
     → poll until first image renders
Afterwards joins app.log / download_diagnostics.log / viewer_diagnostics.log /
db_diagnostics.log into a tagged, ms-resolution timeline per run and computes
the KPI set (tab visible, request sent, first byte/file, first thumbnail,
first render, priority escalation). Output → ui_probe_runs/<ts>_kpi/.
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
OUT = HERE / "ui_probe_runs" / (time.strftime("%Y%m%d_%H%M%S") + "_kpi")
SUM: dict = {"out": str(OUT), "runs": {}}

def _locally_downloaded_study_uids() -> set:
    """Study UIDs that already have instances in the local DB (read-only)."""
    import sqlite3
    db = R / "user_data" / "database" / "dicom.db"
    uids = set()
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3.0)
        try:
            cur = conn.execute(
                "SELECT DISTINCT st.study_uid FROM studies st "
                "JOIN series se ON se.study_fk = st.study_pk "
                "JOIN instances i ON i.series_fk = se.series_pk")
            uids = {str(r[0]) for r in cur.fetchall()}
        finally:
            conn.close()
    except Exception as exc:  # pragma: no cover
        print("local-db freshness check failed:", exc)
    return uids

PATTERNS = [
    ("open_trace", re.compile(r"\[FAST[-_]OPEN[-_]TRACE\] study=(\S+) phase=(\S+) t_ms=([\d.]+)")),
    ("intent", re.compile(r"\[INTENT_PRIORITY\] tag=(\w+).*?series=(\S*)")),
    ("queue", re.compile(r"\[FAST-SERIES-DOWNLOAD-QUEUE\].*series_count=(\d+)")),
    ("sock_send", re.compile(r"send_request called for endpoint: (\w+)")),
    ("sock_stage", re.compile(r"stage=\"?(request_lock_wait|request_sent|response_first_byte|response_done)\"?")),
    ("img_prog", re.compile(r"series_images_progress series=(\S+) downloaded=(\d+) total=(\d+)")),
    ("first_img", re.compile(r"\[UX_FIRST_IMAGE_VISIBLE\] series=(\S+)")),
    ("prog_grow", re.compile(r"\[PROGRESSIVE_GROW\] phase=(\w+) series=(\S+)")),
    ("rp_thumb", re.compile(r"right_panel_(socket_start|socket_done|cache_gate|cache_hit)")),
    ("thumb_png", re.compile(r"thumbnail.*?(saved|written|ready)", re.I)),
    ("spawn", re.compile(r"(subprocess|DownloadProcessWorker).*(spawn|start|started)", re.I)),
    ("db_ins", re.compile(r"(batch_insert_instances|initialize_study)", re.I)),
    ("dl_begin", re.compile(r"(download_series begin|Starting download|download_started)", re.I)),
    ("dl_preempt", re.compile(r"Paused for higher priority|preempt", re.I)),
    ("drop", re.compile(r"change_series_on_viewer|load-on-demand", re.I)),
]


def flush():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(
        json.dumps(SUM, indent=1, default=str), encoding="utf-8")


def collect_timeline(t0: float, t1: float) -> list[dict]:
    rows = []
    for lg in ("app.log", "download_diagnostics.log",
               "viewer_diagnostics.log", "db_diagnostics.log"):
        p = LOGDIR / lg
        if not p.exists():
            continue
        data = p.read_bytes()[-8_000_000:].decode("utf-8", "replace")
        for ln in data.splitlines():
            m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)", ln)
            if not m:
                continue
            try:
                ts = datetime.strptime(m.group(1)[:26], "%Y-%m-%d %H:%M:%S.%f").timestamp()
            except ValueError:
                continue
            if not (t0 <= ts <= t1):
                continue
            for tag, rx in PATTERNS:
                mm = rx.search(ln)
                if mm:
                    rows.append({"t": ts, "rel_ms": round((ts - t0) * 1000.0, 1),
                                 "log": lg[:3], "tag": tag,
                                 "detail": (ln.split(" | ")[-1])[:200]})
                    break
    rows.sort(key=lambda x: x["t"])
    return rows


def main() -> None:
    SUM["restart"] = {"stop": lifecycle.stop_app(force=False)}
    flush()
    res = lifecycle.launch_app(wait_ready_s=200)
    SUM["restart"]["launch_ok"] = res.get("ok")
    flush()
    if not res.get("ok"):
        SUM["restart"]["launch"] = res
        flush()
        return

    from client import AipacsControlClient
    c = AipacsControlClient()

    def q(action, ent=None, timeout=90000):
        return c.send(action, ent or {}, timeout_ms=timeout)

    # Fresh CT patients — on the server but with no local instances.
    local = _locally_downloaded_study_uids()
    SUM["local_study_count"] = len(local)
    r = q("list_patients", {"modality": "CT", "date_from": "20260601",
                            "date_to": "20260605", "source": "server"})
    rows = [x for x in ((r.get("data") or {}).get("rows") or [])
            if "CT" in str(x.get("modalities") or "").upper()
            and str(x.get("study_uid")) not in local
            and (x.get("series_count") or 0) >= 3]
    rows.sort(key=lambda x: -(x.get("series_count") or 0))
    SUM["fresh"] = [(x["patient_id"], x.get("series_count")) for x in rows[:6]]
    flush()
    if len(rows) < 2:
        SUM["error"] = "not enough fresh patients"
        flush()
        return
    A, B = rows[0], rows[1]

    def ent(p):
        return {"patient_id": p["patient_id"],
                "patient_name": p.get("patient_name", ""),
                "study_uid": p["study_uid"]}

    # ── Run A: double-click open of a fresh patient ──────────────────
    a0 = time.time()
    res_open = q("open_patient", ent(A))
    SUM["runs"]["A"] = {"patient": A["patient_id"], "study_uid": A["study_uid"],
                        "t0": a0, "bus_ok": res_open.get("ok")}
    first_render_s = None
    for k in range(40):                       # up to ~60 s
        time.sleep(1.5)
        vp = (q("query_viewport_state").get("data") or {})
        v0 = (vp.get("viewports") or [{}])[0]
        if (v0.get("slice_count") or 0) > 0:
            first_render_s = round(time.time() - a0, 2)
            SUM["runs"]["A"]["viewport"] = v0
            break
    SUM["runs"]["A"]["first_render_poll_s"] = first_render_s
    SUM["runs"]["A"]["t1"] = time.time()
    flush()

    # ── Run B: open second fresh patient, drop its LAST series ──────
    b0 = time.time()
    q("open_patient", ent(B))
    time.sleep(2.5)
    si = q("get_series_info")
    series = ((si.get("data") or {}).get("series") or [])
    SUM["runs"]["B"] = {"patient": B["patient_id"], "study_uid": B["study_uid"],
                        "t0": b0, "n_series": len(series)}
    if series:
        late = series[-1]["series_number"]
        d0 = time.time()
        q("change_series", {"series_number": late, "viewport": 0})
        SUM["runs"]["B"]["dropped"] = late
        SUM["runs"]["B"]["drop_t0"] = d0
        drop_render_s = None
        for k in range(40):
            time.sleep(1.5)
            vp = (q("query_viewport_state").get("data") or {})
            v0 = (vp.get("viewports") or [{}])[0]
            if (v0.get("slice_count") or 0) > 0 and not v0.get("awaiting_series"):
                drop_render_s = round(time.time() - d0, 2)
                SUM["runs"]["B"]["viewport"] = v0
                break
        SUM["runs"]["B"]["drop_first_render_poll_s"] = drop_render_s
    SUM["runs"]["B"]["t1"] = time.time()
    flush()

    # ── timelines ────────────────────────────────────────────────────
    time.sleep(2.0)  # let log buffers flush
    for run_key in ("A", "B"):
        rn = SUM["runs"][run_key]
        tl = collect_timeline(rn["t0"] - 0.5, rn["t1"] + 2.0)
        (OUT / f"timeline_{run_key}.json").write_text(
            json.dumps(tl, indent=1), encoding="utf-8")
        rn["timeline_rows"] = len(tl)
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
