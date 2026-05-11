"""Before/after KPI comparison for DM_REBUILD and MAIN_THREAD_STALL."""
import re
from pathlib import Path
from collections import defaultdict

DL_LOG = Path("user_data/logs/download_diagnostics.log")
VW_LOG = Path("user_data/logs/viewer_diagnostics.log")

rebuild_by_pid = defaultdict(lambda: {"enters": 0, "exits": 0, "reenters": 0,
                                       "durations": [], "first_ts": None, "last_ts": None,
                                       "callers": defaultdict(int)})
stall_by_pid = defaultdict(lambda: {"count": 0, "durations": [], "first_ts": None, "last_ts": None})

with open(DL_LOG, encoding="utf-8", errors="replace") as f:
    for line in f:
        if "[DM_REBUILD]" in line:
            m_process = re.search(r"pid=(\d+)", line)
            m_ts  = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            p_key = m_process.group(1) if m_process else "nopid"
            bucket = rebuild_by_pid[p_key]
            if not bucket["first_ts"] and m_ts:
                bucket["first_ts"] = m_ts.group(1)
            if m_ts:
                bucket["last_ts"] = m_ts.group(1)
            if "event=enter" in line:
                bucket["enters"] += 1
            elif "event=exit" in line:
                bucket["exits"] += 1
                m_dur = re.search(r"duration_ms=([\d.]+)", line)
                if m_dur:
                    bucket["durations"].append(float(m_dur.group(1)))
                m_cal = re.search(r"caller=(\S+)", line)
                if m_cal:
                    bucket["callers"][m_cal.group(1)] += 1
            elif "event=reenter_skip" in line:
                bucket["reenters"] += 1

with open(VW_LOG, encoding="utf-8", errors="replace") as f:
    for line in f:
        if "MAIN_THREAD_STALL_TRACE" in line:
            m_proc = re.search(r"pid=(\d+)", line)
            m_gap  = re.search(r"gap_ms=([\d.]+)", line)
            m_ts   = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if m_proc and m_gap:
                proc = m_proc.group(1)
                g = float(m_gap.group(1))
                stall_by_pid[proc]["count"] += 1
                stall_by_pid[proc]["durations"].append(g)
                ts = m_ts.group(1) if m_ts else None
                if not stall_by_pid[proc]["first_ts"]:
                    stall_by_pid[proc]["first_ts"] = ts
                stall_by_pid[proc]["last_ts"] = ts


def pct(lst, p):
    if not lst:
        return 0
    s = sorted(lst)
    return s[min(int(len(s) * p / 100), len(s) - 1)]


print("\n" + "=" * 80)
print(" DM_REBUILD per session (PID)  -- sorted by time")
print("=" * 80)
for proc, b in sorted(rebuild_by_pid.items(), key=lambda x: x[1]["first_ts"] or ""):
    d = b["durations"]
    avg = sum(d) / len(d) if d else 0
    p95 = pct(d, 95)
    mx  = max(d) if d else 0
    total_ms = sum(d)
    top_callers = sorted(b["callers"].items(), key=lambda x: -x[1])[:3]
    print(f"\n  PID={proc}  [{b['first_ts']} to {b['last_ts']}]")
    print(f"    rebuilds={b['exits']}  reenters_skipped={b['reenters']}")
    print(f"    avg={avg:.0f}ms  p95={p95:.0f}ms  max={mx:.0f}ms  total_blocked={total_ms/1000:.1f}s")
    if top_callers:
        print(f"    top callers: {top_callers}")

print("\n" + "=" * 80)
print(" MAIN_THREAD_STALL per session (PID)  -- sorted by time")
print("=" * 80)
for proc, s in sorted(stall_by_pid.items(), key=lambda x: x[1]["first_ts"] or ""):
    d = s["durations"]
    avg = sum(d) / len(d) if d else 0
    mx  = max(d) if d else 0
    over200  = sum(1 for x in d if x >= 200)
    over1000 = sum(1 for x in d if x >= 1000)
    total_ms = sum(d)
    print(f"\n  PID={proc}  [{s['first_ts']} to {s['last_ts']}]")
    print(f"    total_stalls={s['count']}  >=200ms={over200}  >=1000ms={over1000}")
    print(f"    avg={avg:.0f}ms  max={mx:.0f}ms  total_blocked={total_ms/1000:.1f}s")

print()
