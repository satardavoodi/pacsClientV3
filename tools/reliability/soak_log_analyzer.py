#!/usr/bin/env python3
"""
soak_log_analyzer.py - AI-PACS repeated-workflow / long-session reliability analyzer.

Parses AI-PACS structured diagnostic logs and reports, per *main-app* session:
  * session duration + whether it ended cleanly or terminated abruptly (crash)
  * process RSS trend (first / last / max + slope MB/hour)  -> memory-leak signal
  * thread / subprocess-count trend                         -> thread/handle-leak signal
  * counts of ERROR / CRITICAL lines and known native-fault signatures
Short-lived download worker subprocesses are summarized separately so they do
not drown out the main-session analysis.

It consumes instrumentation the app ALREADY emits
(`stage-timing ... process_rss_mb=...` and `resource-summary ... rss=...MB`),
so it needs no code changes and runs on logs you already have.

Usage:
  python soak_log_analyzer.py                       # scans ./user_data/logs
  python soak_log_analyzer.py --logs-dir PATH [--json out.json] [--all]
  python soak_log_analyzer.py FILE1 FILE2 ...
"""
from __future__ import annotations
import argparse, glob, json, os, re, sys
from datetime import datetime

TS_RE      = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)")
PID_RE     = re.compile(r"pid=(\d+)")
RSS_RE     = re.compile(r"process_rss_mb=([\d.]+)|\brss=([\d.]+)MB")
THREAD_RE  = re.compile(r"thread_count=(\d+)")
SUBPROC_RE = re.compile(r"subprocess_count=(\d+)")
START_RE   = re.compile(r"\[SESSION_START\].*?session_id=(\S+)")
END_RE     = re.compile(r"\[SESSION_END\].*?session_id=(\S+).*?uptime_s=([\d.]+)")
LEVEL_RE   = re.compile(r"^\S+ \S+\s*\|\s*(\w+)")

# leak-verdict gates: ignore tiny/short samples (e.g. download workers)
MIN_SAMPLES, MIN_SPAN_MIN = 5, 10.0

SIGNATURES = {
    "native_fault_0x8001010d_COM_wrong_thread": re.compile(r"0x8001010d"),
    "native_fail_fast_0xC0000409":              re.compile(r"0x[cC]0000409"),
    "deleted_Cpp_object":                       re.compile(r"wrapped C/C\+\+ object|already deleted|has been deleted"),
    "database_is_locked":                       re.compile(r"database is locked"),
}

def parse_ts(line):
    m = TS_RE.match(line)
    if not m: return None
    try: return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f")
    except ValueError: return None

def slope_per_hour(samples):
    if len(samples) < 3: return None
    t0 = samples[0][0]
    xs = [(t - t0).total_seconds() / 3600.0 for t, _ in samples]
    ys = [v for _, v in samples]
    n = len(xs); sx = sum(xs); sy = sum(ys)
    sxx = sum(x*x for x in xs); sxy = sum(x*y for x, y in zip(xs, ys))
    denom = n*sxx - sx*sx
    return None if abs(denom) < 1e-9 else (n*sxy - sx*sy) / denom

def new_proc():
    return {"first": None, "last": None, "rss": [], "threads": [], "subproc": [],
            "errors": 0, "criticals": 0, "sig": {k: 0 for k in SIGNATURES},
            "started": False, "ended": False, "uptime_s": None, "session_id": None}

def analyze(files):
    procs = {}
    for path in files:
        try:
            fh = open(path, "r", encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"  (skip {path}: {e})"); continue
        with fh:
            for line in fh:
                ts = parse_ts(line)
                pm = PID_RE.search(line)
                pid = pm.group(1) if pm else "unknown"
                p = procs.setdefault(pid, new_proc())
                if ts:
                    if p["first"] is None or ts < p["first"]: p["first"] = ts
                    if p["last"]  is None or ts > p["last"]:  p["last"]  = ts
                lv = LEVEL_RE.match(line)
                if lv:
                    if lv.group(1) == "ERROR": p["errors"] += 1
                    elif lv.group(1) == "CRITICAL": p["criticals"] += 1
                for name, rx in SIGNATURES.items():
                    if rx.search(line): p["sig"][name] += 1
                if "[SESSION_START]" in line:
                    mm = START_RE.search(line)
                    if mm: p["started"] = True; p["session_id"] = mm.group(1)
                em = END_RE.search(line)
                if em:
                    p["ended"] = True; p["session_id"] = em.group(1)
                    try: p["uptime_s"] = float(em.group(2))
                    except ValueError: pass
                if ts:
                    rm = RSS_RE.search(line)
                    if rm:
                        try: p["rss"].append((ts, float(rm.group(1) or rm.group(2))))
                        except (TypeError, ValueError): pass
                    tm = THREAD_RE.search(line)
                    if tm: p["threads"].append((ts, int(tm.group(1))))
                    sm = SUBPROC_RE.search(line)
                    if sm: p["subproc"].append((ts, int(sm.group(1))))
    return procs

def summarize(pid, p):
    dur = (p["last"] - p["first"]).total_seconds() / 60.0 if (p["first"] and p["last"]) else 0.0
    rss = p["rss"]; thr = p["threads"]
    rss_first = rss[0][1] if rss else None
    rss_last  = rss[-1][1] if rss else None
    slope = slope_per_hour(rss)
    rss_max = max((v for _, v in rss), default=None)
    net_growth = (rss_max - rss_first) if (rss_first is not None and rss_max is not None) else 0.0
    thr_first = thr[0][1] if thr else None
    thr_last  = thr[-1][1] if thr else None
    thr_max   = max((v for _, v in thr), default=None)
    crashed = p["started"] and not p["ended"]
    long_enough = len(rss) >= MIN_SAMPLES and dur >= MIN_SPAN_MIN
    # net growth to peak is robust to end-of-session GC noise that fools a slope fit
    leak = bool(long_enough and net_growth > 200)
    thr_leak = bool(thr_first is not None and thr_max is not None and thr_max - thr_first > 20
                    and dur >= MIN_SPAN_MIN)
    return {
        "pid": pid, "session_id": p["session_id"],
        "start": str(p["first"]), "end": str(p["last"]),
        "duration_min": round(dur, 1), "uptime_s": p["uptime_s"],
        "ended_cleanly": p["ended"], "abrupt_termination": crashed,
        "rss_first_mb": rss_first, "rss_last_mb": rss_last,
        "rss_max_mb": rss_max, "rss_net_growth_mb": round(net_growth, 1),
        "rss_slope_mb_per_hour": (round(slope, 1) if slope is not None else None),
        "rss_samples": len(rss),
        "thread_first": thr_first, "thread_last": thr_last,
        "thread_max": thr_max,
        "errors": p["errors"], "criticals": p["criticals"],
        "signatures": {k: v for k, v in p["sig"].items() if v},
        "verdict_memory_leak": leak, "verdict_thread_leak": thr_leak,
    }

def is_main(rec, p):
    return bool(p["started"] or p["ended"] or rec["duration_min"] >= MIN_SPAN_MIN
                or rec["rss_samples"] >= 10)

def report(procs, as_json=None, show_all=False):
    mains, workers = [], []
    for pid, p in procs.items():
        if p["first"] is None: continue
        rec = summarize(pid, p)
        (mains if is_main(rec, p) else workers).append(rec)
    mains.sort(key=lambda r: r["start"])
    workers.sort(key=lambda r: r["start"])
    if as_json:
        with open(as_json, "w", encoding="utf-8") as f:
            json.dump({"main_sessions": mains, "worker_subprocesses": workers}, f, indent=2)
        print(f"Wrote JSON report -> {as_json}")
    print("=" * 78)
    print("AI-PACS SOAK / LONG-SESSION RELIABILITY REPORT")
    print("=" * 78)
    n_crash = sum(1 for r in mains if r["abrupt_termination"])
    n_leak  = sum(1 for r in mains if r["verdict_memory_leak"])
    n_thr   = sum(1 for r in mains if r["verdict_thread_leak"])
    print(f"Main-app sessions: {len(mains)} | abrupt terminations: {n_crash} | "
          f"memory-leak flags: {n_leak} | thread-leak flags: {n_thr}")
    print(f"Worker subprocesses observed: {len(workers)}\n")
    print("-- MAIN-APP SESSIONS " + "-" * 57)
    for r in mains:
        flag = ("CRASH/ABRUPT-END" if r["abrupt_termination"]
                else "clean-exit" if r["ended_cleanly"] else "running/rotated")
        print(f"\n* PID {r['pid']}  session={r['session_id']}  [{flag}]")
        print(f"    {r['start']} -> {r['end']}  ({r['duration_min']} min"
              + (f", uptime={r['uptime_s']}s" if r['uptime_s'] else "") + ")")
        if r["rss_samples"]:
            sl = f"{r['rss_slope_mb_per_hour']}MB/h" if r["rss_slope_mb_per_hour"] is not None else "n/a"
            tag = "   <== MEMORY-LEAK FLAG" if r["verdict_memory_leak"] else ""
            print(f"    RSS first={r['rss_first_mb']} last={r['rss_last_mb']} "
                  f"max={r['rss_max_mb']} MB | slope={sl} | n={r['rss_samples']}{tag}")
        if r["thread_first"] is not None:
            tag = "   <== THREAD GROWTH" if r["verdict_thread_leak"] else ""
            print(f"    threads first={r['thread_first']} last={r['thread_last']} max={r['thread_max']}{tag}")
        if r["errors"] or r["criticals"]:
            print(f"    log levels: ERROR={r['errors']} CRITICAL={r['criticals']}")
        if r["signatures"]:
            print(f"    signatures: {r['signatures']}")
    if workers:
        rssvals = [r["rss_max_mb"] for r in workers if r["rss_max_mb"]]
        thrmax  = [r["thread_max"] for r in workers if r["thread_max"]]
        print("\n-- WORKER SUBPROCESSES (download/enrich) " + "-" * 37)
        print(f"    count={len(workers)}  "
              f"rss_max range={min(rssvals):.0f}-{max(rssvals):.0f}MB  " if rssvals else f"    count={len(workers)}  ")
        if thrmax:
            print(f"    thread_max range={min(thrmax)}-{max(thrmax)}  (short-lived; excluded from leak verdicts)")
        if show_all:
            for r in workers:
                print(f"      PID {r['pid']}: {r['duration_min']}min rss_max={r['rss_max_mb']} thr_max={r['thread_max']}")
    print("\n" + "=" * 78)
    print("Heuristics: memory-leak flag = RSS grew >150MB AND slope >30MB/h over a")
    print(f"  session with >={MIN_SAMPLES} samples and >={MIN_SPAN_MIN:.0f} min span.")
    print("  abrupt termination = SESSION_START with no SESSION_END (fail-fast/kill).")
    return {"main_sessions": mains, "worker_subprocesses": workers}

def main():
    ap = argparse.ArgumentParser(description="AI-PACS soak / long-session log analyzer")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--logs-dir", default=os.path.join("user_data", "logs"))
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--all", action="store_true", help="list every worker subprocess too")
    a = ap.parse_args()
    files = a.files or sorted(glob.glob(os.path.join(a.logs_dir, "*.log")))
    if not files:
        print(f"No log files found (looked in {a.logs_dir}).", file=sys.stderr); sys.exit(2)
    print(f"Scanning {len(files)} log file(s): {', '.join(os.path.basename(f) for f in files)}")
    report(analyze(files), as_json=a.json_out, show_all=a.all)

if __name__ == "__main__":
    main()
