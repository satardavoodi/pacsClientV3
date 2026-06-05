# -*- coding: utf-8 -*-
"""issue_verify_run — CLEAN-SLATE verification of issues 1, 3, 5.

Restarts the app (lifecycle), then:
  I5: open ONE fresh patient → wait 3 s (study download in flight on early
      series) → drop the LAST series → poll download/viewport state every 3 s
      for 36 s → verdict: did the dragged series escalate, start, and show
      images (priority order respected)?
  I1: close the (single) patient tab → probed; return to main page → probed.
      Clean slate makes these transitions unambiguous.
  I3: open three fresh patients quickly → per-tab uid check at indexes 2,3,4
      (valid on a clean slate) + tab-thumbnail std per tab.
Summary → ui_probe_runs/<ts>_verify/summary.json.
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

OUT = HERE / "ui_probe_runs" / (time.strftime("%Y%m%d_%H%M%S") + "_verify")
RUN_T0 = time.time()
USED = {"44868", "44915", "44704", "44866", "43971", "44964", "44829",
        "44876", "44823", "44734", "44942", "44976", "44974", "44987"}
LOGDIR = Path(r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version\user_data\logs")
SUM: dict = {"out": str(OUT), "steps": [], "i5": {}, "i3": {}, "i1": {}}


def flush():
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "summary.json", "w", encoding="utf-8") as f:
        json.dump(SUM, f, indent=1, default=str)


def main() -> None:
    # ── clean slate ──────────────────────────────────────────────────
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
    from ui_probe import UiProbe
    c = AipacsControlClient()
    probe = UiProbe(c, OUT, fps=25.0)

    def step(label, action, entities=None, observe=6.0, timeout=90000):
        rec = probe.run(label, action, entities, observe_s=observe, timeout_ms=timeout)
        full = (rec.get("analysis") or {}).get("full", {})
        SUM["steps"].append({"label": label, "ok": rec.get("ok"),
                             "resp_ms": full.get("first_response_ms"),
                             "stable_ms": full.get("stable_ms"),
                             "flickers": len(full.get("flicker_events") or []),
                             "dips": len(full.get("blank_dips") or []),
                             "tab_std": rec.get("tab_strip_std")})
        flush()
        return rec

    def q(action, ent=None):
        return c.send(action, ent or {}, timeout_ms=90000)

    r = q("list_patients", {"modality": "CT", "date_from": "20260603",
                            "date_to": "20260603", "source": "server"})
    rows = [x for x in ((r.get("data") or {}).get("rows") or [])
            if "CT" in str(x.get("modalities") or "").upper()
            and x["patient_id"] not in USED]
    rows.sort(key=lambda x: -(x.get("series_count") or 0))
    SUM["fresh"] = [(x["patient_id"], x.get("series_count")) for x in rows[:5]]
    flush()
    if len(rows) < 4:
        SUM["error"] = "not enough fresh patients"
        flush()
        return
    P5, Q1, Q2, Q3 = rows[0], rows[1], rows[2], rows[3]

    def ent(p):
        return {"patient_id": p["patient_id"],
                "patient_name": p.get("patient_name", ""),
                "study_uid": p["study_uid"]}

    # ── Issue 5: priority order, long observation ────────────────────
    step(f"i5_open_{P5['patient_id']}", "open_patient", ent(P5), observe=5.0)
    time.sleep(3.0)
    si = q("get_series_info")
    series = ((si.get("data") or {}).get("series") or [])
    SUM["i5"]["series"] = series
    if series:
        late = series[-1]["series_number"]
        SUM["i5"]["dropped"] = late
        SUM["i5"]["drop_wall"] = time.time()
        step(f"i5_drop_{late}", "change_series",
             {"series_number": late, "viewport": 0}, observe=5.0)
        polls = []
        for k in range(12):
            time.sleep(3.0)
            vp = (q("query_viewport_state").get("data") or {})
            v0 = (vp.get("viewports") or [{}])[0]
            ds = q("check_download_status",
                   {"study_uid": P5["study_uid"]}).get("data") or {}
            polls.append({
                "t_s": round(time.time() - SUM["i5"]["drop_wall"], 1),
                "slices": v0.get("slice_count"),
                "awaiting": v0.get("awaiting_series"),
                "progressive": v0.get("progressive_mode"),
                "dl_status": ds.get("status"),
                "dl_pct": ds.get("progress_percent"),
            })
            SUM["i5"]["polls"] = polls
            flush()
            if (v0.get("slice_count") or 0) > 0:
                break
        SUM["i5"]["first_slices_at_s"] = next(
            (p["t_s"] for p in polls if (p["slices"] or 0) > 0), None)
    flush()

    # ── Issue 1: close (single tab) → main page ──────────────────────
    step("i1_close", "close_patient_tab", {}, observe=6.0)
    step("i1_return_main", "switch_tab", {"index": 0}, observe=6.0)

    # ── Issue 3: three fresh opens, clean indexes ────────────────────
    for p in (Q1, Q2, Q3):
        step(f"i3_open_{p['patient_id']}", "open_patient", ent(p), observe=2.2)
    per_tab = []
    for idx in (2, 3, 4):
        q("switch_tab", {"index": idx})
        time.sleep(1.4)
        d = q("get_series_info").get("data") or {}
        rec = probe.run(f"i3_tabcheck_{idx}", "query_viewport_state", {},
                        observe_s=1.5)
        per_tab.append({"tab": idx, "study_uid": str(d.get("study_uid") or ""),
                        "n_series": len(d.get("series") or []),
                        "tab_std": rec.get("tab_strip_std")})
    expected = {p["patient_id"]: str(p["study_uid"]) for p in (Q1, Q2, Q3)}
    got = [t["study_uid"] for t in per_tab]
    SUM["i3"] = {"expected": expected, "per_tab": per_tab,
                 "no_mixing": (set(got) == set(expected.values())
                               and len(set(got)) == 3)}
    SUM["final_downloads"] = q("download_statistics").get("data")
    flush()

    # ── log-join for I5 ──────────────────────────────────────────────
    keys = ("VIEWED-SERIES", "INTENT_PRIORITY", "preempt", "Paused for higher",
            "UX_FIRST_IMAGE_VISIBLE", "FAST-SERIES-DOWNLOAD-QUEUE",
            "load-on-demand FAILED")
    cut = datetime.fromtimestamp(RUN_T0)
    tl = []
    for lg in ("app.log", "download_diagnostics.log", "viewer_diagnostics.log"):
        p = LOGDIR / lg
        if not p.exists():
            continue
        data = p.read_bytes()[-5_000_000:].decode("utf-8", "replace")
        for ln in data.splitlines():
            m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", ln)
            if not m:
                continue
            try:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if ts < cut:
                continue
            for k in keys:
                if k in ln:
                    tl.append(ln[11:19] + " [" + k + "] " +
                              ln.split(" | ")[-1][:130])
                    break
    SUM["i5"]["log"] = tl[:80]
    flush()
    probe.close()
    c.close()
    print("done ->", OUT)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        SUM["exception"] = traceback.format_exc()
        flush()
