"""AI-PACS session KPI report — read-only, offline log analyzer.

Consolidates the manual KPI review (see docs/reports/KPI_SESSION_REVIEW_2026-07-01.md)
into one repeatable tool. It parses the current runtime logs, computes the KPI panel
(startup, first-image/TTFI, decode, render, drag, main-thread stalls, DB, download
stage-timing, log hygiene), compares each metric to the catalog targets in
`kpi_targets.py`, and writes a dated Markdown + JSON report.

Design constraints (do not break):
  * READ-ONLY / OFFLINE: imports no viewer/VTK/DB-pool/Qt code and never opens dicom.db.
    It only reads the log text files. Safe to run any time, including during clinical use.
  * Robust to pathological logs: single records can be multi-MB (a known logging defect),
    so every line is byte-guarded; oversized records are counted as a hygiene metric,
    never parsed.
  * Boundary aware: a log file can hold several app runs; by default the tool analyzes
    only the most recent run (detected from the last startup line), so "fresh log" reviews
    are not contaminated by history. Override with --since or --full.
  * Field/marker conventions align with tools/performance/stall_correlation_report.py.

Usage:
  .venv/Scripts/python.exe tools/performance/kpi_session_report.py
  .venv/Scripts/python.exe tools/performance/kpi_session_report.py --since "2026-07-01 14:09:32"
  .venv/Scripts/python.exe tools/performance/kpi_session_report.py --full --print
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

try:
    from kpi_targets import TARGETS, evaluate  # when run from tools/performance
except Exception:  # pragma: no cover - import shim for test / external callers
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from kpi_targets import TARGETS, evaluate

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOGDIR = ROOT / "user_data" / "logs"
DEFAULT_OUTDIR = ROOT / "docs" / "reports"

MAX_LINE_BYTES = 8000          # skip (but count) lines larger than this
OVERSIZED_BYTES = 256 * 1024   # a single log record this large is a hygiene failure
CUR_FILES = ("app.log", "viewer_diagnostics.log", "db_diagnostics.log", "download_diagnostics.log")

_KV = re.compile(r"([a-zA-Z_][\w]*)=(-?\d+\.?\d*)(?=\s|$)")
# Once-per-process markers (NOT STARTUP_STAGE, which repeats per stage within one boot).
_BOOT_SENTINELS = ("single_instance_lock.try_acquire", "configure_diagno")


def pct(values, p):
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * (p / 100.0)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    if lo == hi:
        return float(ordered[lo])
    w = pos - lo
    return float(ordered[lo] * (1 - w) + ordered[hi] * w)


def _numfields(s):
    return {k: float(v) for k, v in _KV.findall(s)}


def _sval(s, key):
    m = re.search(rf"{re.escape(key)}=([^\s]+)", s)
    return m.group(1) if m else None


def detect_session_boundary(logdir: Path):
    """Return the timestamp of the MOST RECENT app startup, or None.

    A log file can hold several runs (the single-instance takeover relaunches, or the
    user restarts). We default to the latest run only, so "current execution" reviews
    are not diluted by earlier runs. Uses once-per-process sentinels (not STARTUP_STAGE,
    which repeats within one boot). Pass --since / --full to override.
    """
    app = logdir / "app.log"
    if not app.exists():
        return None
    latest = None
    with app.open("rb") as fh:
        for raw in fh:
            if len(raw) > MAX_LINE_BYTES:
                continue
            line = raw.decode("utf-8", "replace")
            if not line[:4].isdigit():
                continue
            if any(s in line for s in _BOOT_SENTINELS):
                ts = line[:26]
                if latest is None or ts > latest:
                    latest = ts
    return latest


def _iter_lines(path: Path, since):
    """Yield (line, oversized_flag). Oversized lines yield ("", True) and are not decoded."""
    if not path.exists():
        return
    with path.open("rb") as fh:
        for raw in fh:
            if len(raw) > OVERSIZED_BYTES:
                yield "", True
                continue
            if len(raw) > MAX_LINE_BYTES:
                # large but not an oversized-hygiene failure: skip parse, don't flag
                continue
            line = raw.decode("utf-8", "replace")
            if since and line[:19] < since and line[:4].isdigit():
                continue
            yield line, False


def analyze(logdir: Path, since=None) -> dict:
    stalls, drag, ttfi, setslice, vswitch, startup = [], [], [], [], [], []
    geo_mismatch = 0
    db_read, db_write, db_all = [], [], []
    dl_stages: dict = {}
    files_meta: dict = {}
    oversized_total = 0
    span = [None, None]

    for name in CUR_FILES:
        path = logdir / name
        total = warn = oversized = 0
        for line, big in _iter_lines(path, since):
            if big:
                oversized += 1
                oversized_total += 1
                continue
            total += 1
            if "WARNING" in line:
                warn += 1
            ts = line[:26]
            if ts[:4].isdigit():
                if span[0] is None or ts < span[0]:
                    span[0] = ts
                if span[1] is None or ts > span[1]:
                    span[1] = ts

            if name == "viewer_diagnostics.log":
                if "[MAIN_THREAD_STALL]" in line and "TRACE" not in line:
                    d = _numfields(line).get("stall_duration_ms")
                    if d is not None:
                        near = {k: _sval(line, "nearest_" + k) for k in
                                ("dm_rebuild", "viewer_switch", "progressive", "fast_drag", "table_refresh")}
                        near = {k: v for k, v in near.items() if v and v != "none"}
                        stalls.append((ts[11:19], d, _sval(line, "active_viewer_state"), near))
                elif "[FAST_DRAG_KPI]" in line:
                    drag.append(_numfields(line))
                elif "[KPI]" in line and "TTFI" in line:
                    ttfi.append(_numfields(line))
                elif "[FAST_SET_SLICE_STAGE]" in line:
                    setslice.append(_numfields(line))
                elif "[VIEWER_SWITCH]" in line and "first_image_visible" in line:
                    vswitch.append(_numfields(line))
                elif "[STARTUP_STAGE]" in line:
                    # parse the stage name from AFTER the marker (the line header also
                    # carries a generic 'stage=-' field that would otherwise shadow it).
                    seg = line.split("[STARTUP_STAGE]", 1)[1]
                    startup.append((_sval(seg, "stage"), _numfields(seg).get("ms")))
                elif "[FAST_GEOMETRY_ORDER_MISMATCH]" in line:
                    geo_mismatch += 1
            elif name == "db_diagnostics.log":
                f = _numfields(line)
                dur = f.get("duration_ms", f.get("duration"))
                if dur is not None:
                    db_all.append(dur)
                    # Only the main app's DB timings count against the interaction targets;
                    # download-subprocess DB writes are off the GUI thread and expected to be heavier.
                    if "role=main" in line:
                        qt = (_sval(line, "query_type") or _sval(line, "classification") or "").lower()
                        if "read" in qt:
                            db_read.append(dur)
                        elif "write" in qt:
                            db_write.append(dur)
            elif name == "download_diagnostics.log":
                if "stage-timing" in line:
                    st = _sval(line, "stage")
                    d = _numfields(line).get("duration_ms")
                    if st and d is not None:
                        dl_stages.setdefault(st, []).append(d)
        files_meta[name] = {
            "lines": total, "warning": warn, "oversized": oversized,
            "warning_pct": round(100.0 * warn / total, 1) if total else 0.0,
        }

    def col(rows, key):
        return [r[key] for r in rows if key in r]

    stall_durs = [s[1] for s in stalls]
    drag_event_p95 = col(drag, "event_p95_ms")
    drag_ui_lag = col(drag, "ui_lag_max_ms")

    metrics = {
        "ttfi_total_p95_ms": pct(col(ttfi, "total_ms"), 95),
        "decode_p95_ms": pct(col(ttfi, "ttd_ms"), 95),
        "set_slice_total_p95_ms": pct(col(setslice, "total_ms"), 95),
        "drag_event_p95_ms": pct(drag_event_p95, 95),
        "drag_ui_lag_max_ms": (max(drag_ui_lag) if drag_ui_lag else None),
        "stall_p95_ms": pct(stall_durs, 95),
        "stall_over_500_count": (float(len([d for d in stall_durs if d >= 500])) if stalls else None),
        "db_read_p95_ms": pct(db_read, 95),
        "db_write_p95_ms": pct(db_write, 95),
        "oversized_log_records": float(oversized_total),
        "max_warning_ratio_pct": (max((m["warning_pct"] for m in files_meta.values()), default=0.0)),
    }

    by_state, near_counts = {}, {}
    for _t, d, state, near in stalls:
        by_state.setdefault(state, []).append(d)
        for k in near:
            near_counts[k] = near_counts.get(k, 0) + 1
    worst = sorted(stalls, key=lambda x: -x[1])[:6]

    detail = {
        "span": span,
        "files": files_meta,
        "stalls": {
            "count": len(stalls),
            "p50": pct(stall_durs, 50), "p95": pct(stall_durs, 95),
            "max": (max(stall_durs) if stall_durs else None),
            "ge250": len([d for d in stall_durs if d >= 250]),
            "ge500": len([d for d in stall_durs if d >= 500]),
            "ge1000": len([d for d in stall_durs if d >= 1000]),
            "by_state": {k: {"n": len(v), "max": max(v), "p95": pct(v, 95)} for k, v in by_state.items()},
            "nearest": near_counts,
            "worst": [{"t": t, "ms": round(d, 1), "state": s, "near": n} for t, d, s, n in worst],
        },
        "ttfi": {k: pct(col(ttfi, k), 95) for k in ("total_ms", "ttd_ms", "ttr_ms")},
        "set_slice": {k: pct(col(setslice, k), 95) for k in ("total_ms", "decode_ms", "wl_ms", "frame_ms")},
        "drag": {
            "n": len(drag),
            "event_p95_ms": pct(drag_event_p95, 95),
            "ui_lag_max_ms": (max(drag_ui_lag) if drag_ui_lag else None),
            "handler_p95_ms": pct(col(drag, "handler_p95_ms"), 95),
        },
        "viewer_switch": {k: pct(col(vswitch, k), 95) for k in ("total_ms", "decode_ms")},
        "startup_stages": [{"stage": s, "ms": m} for s, m in startup if s],
        "download_stage_timing": {
            k: {"n": len(v), "p50": pct(v, 50), "p95": pct(v, 95), "max": max(v)}
            for k, v in sorted(dl_stages.items(), key=lambda kv: -max(kv[1]))
        },
        "db": {"n": len(db_all), "p95": pct(db_all, 95), "max": (max(db_all) if db_all else None)},
        "geometry_order_mismatch": geo_mismatch,
    }
    return {"since": since, "metrics": metrics, "detail": detail}


def _fmt(v, nd=1):
    return "—" if v is None else f"{v:.{nd}f}"


def render_markdown(result: dict) -> str:
    m, d = result["metrics"], result["detail"]
    L = []
    L.append("# AI-PACS KPI Session Report")
    L.append("")
    L.append(f"Generated: {_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    L.append(f"Session boundary (since): `{result['since'] or 'full file'}`  ")
    L.append(f"Span: `{d['span'][0]}` -> `{d['span'][1]}`")
    L.append("")
    L.append("## Verdict vs. catalog targets")
    L.append("")
    L.append("| KPI | Value | Target | Verdict | Source |")
    L.append("|---|---|---|---|---|")
    for t, val, passed in evaluate(m):
        verdict = "n/a" if passed is None else ("PASS" if passed else "FAIL")
        vs = "—" if val is None else f"{val:.1f} {t.unit}"
        L.append(f"| {t.label} | {vs} | {t.limit:.0f} {t.unit} | {verdict} | {t.source} |")
    st = d["stalls"]
    L.append("")
    L.append("## Main-thread stalls")
    L.append(f"- count={st['count']}  p50={_fmt(st['p50'])}  p95={_fmt(st['p95'])}  max={_fmt(st['max'])} ms")
    L.append(f"- >=250ms={st['ge250']}  >=500ms={st['ge500']}  >=1000ms={st['ge1000']}")
    if st["by_state"]:
        L.append("- by active_viewer_state: " +
                 "; ".join(f"{k}(n={v['n']},max={v['max']:.0f})" for k, v in
                           sorted(st["by_state"].items(), key=lambda kv: -kv[1]['max'])))
    if st["nearest"]:
        L.append(f"- nearest-correlated events: {st['nearest']}")
    for w in st["worst"]:
        L.append(f"  - {w['t']}  {w['ms']} ms  state={w['state']}  near={w['near']}")
    L.append("")
    L.append("## Render / first image")
    L.append(f"- TTFI p95: total={_fmt(d['ttfi']['total_ms'])}  decode={_fmt(d['ttfi']['ttd_ms'])}  "
             f"render={_fmt(d['ttfi']['ttr_ms'])} ms")
    L.append(f"- set-slice p95: total={_fmt(d['set_slice']['total_ms'])}  frame={_fmt(d['set_slice']['frame_ms'])} ms")
    L.append(f"- viewer-switch first-image p95: total={_fmt(d['viewer_switch']['total_ms'])} ms")
    L.append("")
    L.append("## Drag")
    L.append(f"- n={d['drag']['n']}  event_p95={_fmt(d['drag']['event_p95_ms'])}  "
             f"ui_lag_max={_fmt(d['drag']['ui_lag_max_ms'])}  handler_p95={_fmt(d['drag']['handler_p95_ms'])} ms")
    L.append("")
    if d["startup_stages"]:
        L.append("## Startup stages (ms)")
        for s in d["startup_stages"]:
            L.append(f"- {s['stage']}: {_fmt(s['ms'])}")
        L.append("")
    L.append("## Download stage-timing (ms)")
    for k, v in d["download_stage_timing"].items():
        L.append(f"- {k}: n={v['n']} p50={_fmt(v['p50'])} p95={_fmt(v['p95'])} max={_fmt(v['max'])}")
    L.append("")
    L.append("## Log hygiene")
    for name, fm in d["files"].items():
        flag = "  WARNING-saturated" if fm["warning_pct"] >= 90 else ""
        L.append(f"- {name}: lines={fm['lines']} warning={fm['warning']} ({fm['warning_pct']}%){flag}")
    L.append(f"- oversized records (>256KB): {m['oversized_log_records']:.0f}")
    L.append(f"- geometry-order-mismatch markers: {d['geometry_order_mismatch']}")
    L.append("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="AI-PACS read-only session KPI report")
    ap.add_argument("--logs", default=str(DEFAULT_LOGDIR))
    ap.add_argument("--since", default=None, help="only analyze lines >= this 'YYYY-MM-DD HH:MM:SS'")
    ap.add_argument("--full", action="store_true", help="analyze whole files (ignore auto session boundary)")
    ap.add_argument("--out", default=None, help="output .md path (a sibling .json is written too)")
    ap.add_argument("--print", dest="do_print", action="store_true")
    args = ap.parse_args(argv)

    logdir = Path(args.logs)
    since = args.since
    if since is None and not args.full:
        since = detect_session_boundary(logdir)

    result = analyze(logdir, since=since)
    md = render_markdown(result)

    stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_md = Path(args.out) if args.out else (DEFAULT_OUTDIR / f"KPI_SESSION_REPORT_{stamp}.md")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    out_md.with_suffix(".json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    if args.do_print:
        print(md)
    print(f"\nWrote {out_md}")
    print(f"Wrote {out_md.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
