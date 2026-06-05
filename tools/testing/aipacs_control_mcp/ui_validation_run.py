# -*- coding: utf-8 -*-
"""Fast UI validation pass — runs the glitch checklist through UiProbe.

Covers: thumbnail-click smoothness (repeat clicks incl. same patient twice),
double-click open (tab immediacy + small tab-thumbnail presence), CT + DX
drag-and-drop under load (loader, freeze, priority escalation, progressive
sync). Writes artifacts + records.json under ui_probe_runs/<ts>/ and a
summary.json that also joins download-priority / first-image / progressive
marks from the app logs by wall-clock window.
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
                 "44829", "44876", "44823"}

OUT = HERE / "ui_probe_runs" / time.strftime("%Y%m%d_%H%M%S")
RUN_T0 = time.time()


def rows_for(c, modality):
    r = c.send("list_patients", {"modality": modality, "date_from": "20260603",
                                 "date_to": "20260603", "source": "server"},
               timeout_ms=90000)
    rows = (r.get("data") or {}).get("rows") or []
    out = []
    for row in rows:
        mods = row.get("modalities")
        mods_s = ",".join(mods) if isinstance(mods, (list, tuple)) else str(mods or "")
        if modality.upper() in mods_s.upper():
            out.append(row)
    out.sort(key=lambda x: -(x.get("series_count") or 0))
    return out


def main() -> None:
    c = AipacsControlClient()
    probe = UiProbe(c, OUT, fps=25.0)
    summary = {"out": str(OUT), "steps": []}

    def step(label, action, entities=None, observe=5.0, timeout=60000):
        rec = probe.run(label, action, entities, observe_s=observe,
                        timeout_ms=timeout)
        full = (rec.get("analysis") or {}).get("full", {})
        summary["steps"].append({
            "label": label, "ok": rec.get("ok"),
            "bus_ms": rec.get("bus_elapsed_ms"),
            "first_response_ms": full.get("first_response_ms"),
            "stable_ms": full.get("stable_ms"),
            "flickers": len(full.get("flicker_events") or []),
            "dips": len(full.get("blank_dips") or []),
            "fps": rec.get("capture_fps"),
        })
        _flush()
        return rec

    def _flush():
        with open(OUT / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1, default=str)

    # ── search + targets ────────────────────────────────────────────
    ct = rows_for(c, "CT")
    dx = rows_for(c, "DX")
    fresh_ct = [r for r in ct if r["patient_id"] not in LOCAL_ALREADY]
    summary["targets"] = {"ct_n": len(ct), "dx_n": len(dx),
                          "fresh_ct": [r["patient_id"] for r in fresh_ct[:4]]}

    # ── §4 thumbnail-click smoothness: 4 distinct + 1 repeat ────────
    picks = (ct[:2] + fresh_ct[:2])[:4]
    for i, row in enumerate(picks):
        step(f"04_thumb_click_{i}_{row['patient_id']}", "select_patient",
             {"patient_id": row["patient_id"]}, observe=4.0)
    if picks:
        step(f"04_thumb_click_repeat_{picks[0]['patient_id']}", "select_patient",
             {"patient_id": picks[0]["patient_id"]}, observe=4.0)

    # ── §5 double-click open: fresh CT (tab + tab-thumbnail) ────────
    open_ct = (fresh_ct or ct)[0]
    step(f"05_open_{open_ct['patient_id']}", "open_patient",
         {"patient_id": open_ct["patient_id"],
          "patient_name": open_ct.get("patient_name", ""),
          "study_uid": open_ct["study_uid"]}, observe=7.0)

    # ── §6/§7/§8 drag-drop CT under download (priority + progressive) ─
    sr = c.send("get_series_info", {})
    series = ((sr.get("data") or {}).get("series") or [])
    summary["ct_series"] = series[:8]
    if len(series) >= 2:
        step("06_ct_drop_vp0", "change_series",
             {"series_number": series[1]["series_number"], "viewport": 0},
             observe=10.0)
        step("06_ct_drop_vp1", "change_series",
             {"series_number": series[min(2, len(series) - 1)]["series_number"],
              "viewport": 1}, observe=8.0)
        # progressive sync window — no input, watch the viewport grow
        step("08_progressive_watch", "query_viewport_state", {}, observe=10.0)

    # ── §6 DX open + drop (heavy single images) ─────────────────────
    if dx:
        d0 = dx[0]
        step(f"05_open_dx_{d0['patient_id']}", "open_patient",
             {"patient_id": d0["patient_id"],
              "patient_name": d0.get("patient_name", ""),
              "study_uid": d0["study_uid"]}, observe=6.0)
        sr = c.send("get_series_info", {})
        dseries = ((sr.get("data") or {}).get("series") or [])
        summary["dx_series"] = dseries[:6]
        if dseries:
            step("06_dx_drop_vp0", "change_series",
                 {"series_number": dseries[0]["series_number"], "viewport": 0},
                 observe=8.0)

    # final state queries
    vp = c.send("query_viewport_state", {})
    summary["final_viewports"] = vp.get("data")
    dl = c.send("download_statistics", {})
    summary["final_downloads"] = dl.get("data")

    # ── §9 log-join: priority escalation / first image / progressive ─
    marks = {"INTENT_PRIORITY": [], "UX_FIRST_IMAGE_VISIBLE": [],
             "PROGRESSIVE_GROW] phase=start": [], "preempt": [],
             "load-on-demand FAILED": []}
    t0_str = datetime.fromtimestamp(RUN_T0).strftime("%Y-%m-%d %H:%M")
    cut = datetime.fromtimestamp(RUN_T0 - 5)
    for lg in ("app.log", "download_diagnostics.log", "viewer_diagnostics.log"):
        p = LOGDIR / lg
        if not p.exists():
            continue
        try:
            data = p.read_bytes()[-4_000_000:].decode("utf-8", "replace")
        except Exception:
            continue
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
            for key in marks:
                if key in ln and len(marks[key]) < 30:
                    marks[key].append(ln[11:19] + " " + ln.split(" | ")[-1][:130])
    summary["log_marks"] = {k: v for k, v in marks.items()}
    summary["run_window"] = [t0_str, datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    _flush()
    probe.close()
    c.close()
    print("done ->", OUT)


if __name__ == "__main__":
    main()
