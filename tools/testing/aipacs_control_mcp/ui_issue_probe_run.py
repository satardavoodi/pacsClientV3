# -*- coding: utf-8 -*-
"""ui_issue_probe_run — targeted glitch hunt on 6 known UI/workflow issues.

1 close-patient → main-page flicker/reflow + stable time
2 un-downloaded patient open (tab, thumbs, download start, tab mini-thumb)
3 several un-downloaded patients fast (lost/mixed thumbnails, per-tab uid check)
4 drag not-yet-downloaded series (loader vs freeze, first image, progressive)
5 priority order (drop a LATE series mid-study-download → must start first)
6 impatient burst (lag/freeze/stalls)

Artifacts → ui_probe_runs/<ts>_issues/ ; verdicts + log timeline → summary.json.
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

from client import AipacsControlClient  # noqa: E402
from ui_probe import UiProbe  # noqa: E402

LOGDIR = Path(r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version\user_data\logs")
LOCAL_ALREADY = {"44868", "44915", "44704", "44866", "43971", "44964",
                 "44829", "44876", "44823", "44734"}
OUT = HERE / "ui_probe_runs" / (time.strftime("%Y%m%d_%H%M%S") + "_issues")
RUN_T0 = time.time()
SUM: dict = {"out": str(OUT), "steps": [], "checks": {}, "events": []}


def flush():
    with open(OUT / "summary.json", "w", encoding="utf-8") as f:
        json.dump(SUM, f, indent=1, default=str)


def mark(label, **kw):
    SUM["events"].append({"wall": time.time(), "t": round(time.time() - RUN_T0, 2),
                          "label": label, **kw})


def main() -> None:
    c = AipacsControlClient()
    probe = UiProbe(c, OUT, fps=25.0)

    def step(label, action, entities=None, observe=6.0, timeout=90000):
        rec = probe.run(label, action, entities, observe_s=observe, timeout_ms=timeout)
        full = (rec.get("analysis") or {}).get("full", {})
        SUM["steps"].append({
            "label": label, "ok": rec.get("ok"), "err": rec.get("error_code"),
            "bus_ms": rec.get("bus_elapsed_ms"),
            "resp_ms": full.get("first_response_ms"),
            "stable_ms": full.get("stable_ms"),
            "flickers": full.get("flicker_events"),
            "dips": len(full.get("blank_dips") or []),
            "tab_std": rec.get("tab_strip_std"),
        })
        mark(label, ok=rec.get("ok"))
        flush()
        return rec

    def q(action, entities=None):
        return c.send(action, entities or {}, timeout_ms=60000)

    # fresh CT targets
    r = q("list_patients", {"modality": "CT", "date_from": "20260603",
                            "date_to": "20260603", "source": "server"})
    rows = (r.get("data") or {}).get("rows") or []
    fresh = [x for x in rows
             if "CT" in str(x.get("modalities") or "").upper()
             and x["patient_id"] not in LOCAL_ALREADY]
    fresh.sort(key=lambda x: -(x.get("series_count") or 0))
    SUM["fresh_targets"] = [(x["patient_id"], x.get("series_count")) for x in fresh[:6]]
    flush()
    if len(fresh) < 4:
        fresh += [x for x in rows if x["patient_id"] in LOCAL_ALREADY]

    A, B, C3, D = fresh[0], fresh[1], fresh[2], fresh[3]

    def open_ent(p):
        return {"patient_id": p["patient_id"],
                "patient_name": p.get("patient_name", ""),
                "study_uid": p["study_uid"]}

    # ── Issue 2: un-downloaded patient open ──────────────────────────
    step(f"i2_open_fresh_{A['patient_id']}", "open_patient", open_ent(A), observe=8.0)
    si = q("get_series_info")
    SUM["checks"]["i2_series_bound"] = ((si.get("data") or {}).get("series") or [])[:6]
    SUM["checks"]["i2_uid_match"] = (
        str((si.get("data") or {}).get("study_uid")) == str(A["study_uid"]))
    dl = q("download_statistics")
    SUM["checks"]["i2_downloads"] = dl.get("data")
    flush()

    # ── Issue 1: close patient → main page flicker ───────────────────
    step("i1_close_patient_tab", "close_patient_tab", {}, observe=5.0)
    step("i1_return_main_page", "switch_tab", {"index": 0}, observe=6.0)

    # ── Issue 3: several un-downloaded patients quickly ──────────────
    for p in (B, C3, D):
        step(f"i3_open_{p['patient_id']}", "open_patient", open_ent(p), observe=2.2)
    # verify per-tab identity: walk patient tabs (start at index 2: 0=home,1=DM)
    tabs = q("list_open_tabs")
    SUM["checks"]["i3_open_tabs"] = tabs.get("data")
    uid_by_pid = {p["patient_id"]: str(p["study_uid"]) for p in (B, C3, D)}
    per_tab = []
    for idx in (2, 3, 4):
        q("switch_tab", {"index": idx})
        time.sleep(1.2)
        si = q("get_series_info")
        d = si.get("data") or {}
        per_tab.append({"tab": idx, "study_uid": str(d.get("study_uid") or ""),
                        "n_series": len(d.get("series") or [])})
    SUM["checks"]["i3_per_tab"] = per_tab
    SUM["checks"]["i3_expected_uids"] = uid_by_pid
    got = {t["study_uid"] for t in per_tab if t["study_uid"]}
    SUM["checks"]["i3_no_mixing"] = got.issubset(set(uid_by_pid.values()) |
                                                 {str(A["study_uid"])}) and len(got) == 3
    dl = q("download_statistics")
    SUM["checks"]["i3_downloads"] = dl.get("data")
    flush()

    # ── Issues 4+5: drop a LATE not-downloaded series mid-download ───
    # Stay on the LAST opened patient (D, tab 4): its study download started
    # seconds ago → early series are in flight; drop the LAST series now.
    si = q("get_series_info")
    dser = ((si.get("data") or {}).get("series") or [])
    SUM["checks"]["i5_series_list"] = dser
    if dser:
        late = dser[-1]["series_number"]
        mark("i5_drop_wall", series=late)
        step(f"i5_drop_late_series_{late}", "change_series",
             {"series_number": late, "viewport": 0}, observe=14.0)
        vp = q("query_viewport_state")
        SUM["checks"]["i5_viewport_after"] = vp.get("data")
    flush()

    # ── Issue 6: impatient burst ─────────────────────────────────────
    t6 = time.time()
    mark("i6_burst_begin")
    for pid in (A["patient_id"], B["patient_id"], C3["patient_id"]):
        q("select_patient", {"patient_id": pid})
        time.sleep(0.25)
    for idx in (2, 3, 4, 2, 3, 4):
        q("switch_tab", {"index": idx})
        time.sleep(0.15)
    rec = step("i6_burst_settle", "query_viewport_state", {}, observe=6.0)
    SUM["checks"]["i6_burst_wall"] = [t6, time.time()]
    flush()

    # final downloads + viewport state
    SUM["checks"]["final_downloads"] = q("download_statistics").get("data")
    SUM["checks"]["final_viewports"] = q("query_viewport_state").get("data")

    # ── log-join: ordered per-series download/priority timeline ──────
    pats = {
        "intent": re.compile(r"\[INTENT_PRIORITY\] tag=(\w+) study=\S+ series=(\S*)"),
        "queue": re.compile(r"\[FAST-SERIES-DOWNLOAD-QUEUE\].*series_count=(\d+)"),
        "dl_series": re.compile(r"download_series", re.I),
        "first_img": re.compile(r"\[UX_FIRST_IMAGE_VISIBLE\] series=(\S+)"),
        "grow": re.compile(r"\[PROGRESSIVE_GROW\] phase=start series=(\S+)"),
        "stall": re.compile(r"MAIN_THREAD_STALL\] stall", re.I),
        "preempt": re.compile(r"preempt|Paused for higher", re.I),
        "fail": re.compile(r"load-on-demand FAILED for series (\S+)"),
        "sig_prog": re.compile(r"series_images_progress series=(\S+) downloaded=(\d+) total=(\d+)"),
    }
    cut = datetime.fromtimestamp(RUN_T0 - 3)
    timeline = []
    for lg in ("app.log", "download_diagnostics.log", "viewer_diagnostics.log"):
        p = LOGDIR / lg
        if not p.exists():
            continue
        data = p.read_bytes()[-6_000_000:].decode("utf-8", "replace")
        for ln in data.splitlines():
            m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)", ln)
            if not m:
                continue
            try:
                ts = datetime.strptime(m.group(1)[:26], "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                continue
            if ts < cut:
                continue
            for name, rx in pats.items():
                mm = rx.search(ln)
                if mm:
                    timeline.append({"t": ts.strftime("%H:%M:%S.%f")[:-3],
                                     "kind": name,
                                     "detail": ln.split(" | ")[-1][:150]})
                    break
    timeline.sort(key=lambda x: x["t"])
    SUM["log_timeline"] = timeline[:400]
    SUM["counts"] = {k: sum(1 for e in timeline if e["kind"] == k) for k in pats}
    flush()
    probe.close()
    c.close()
    print("done ->", OUT)


if __name__ == "__main__":
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        main()
    except Exception:
        import traceback
        SUM["exception"] = traceback.format_exc()
        flush()
