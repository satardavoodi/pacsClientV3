"""One-off: app sessions, how each ended, and what is still stalling today.

Separates real app instances (role=main) from download subprocesses, shows how
each session ended (clean shutdown marker vs abrupt), and ranks the main-thread
stall frames per session.  Read-only.
"""
import collections
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
LOGS = os.path.join(ROOT, "user_data", "logs")
DAY = "2026-08-22"

TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
PID = re.compile(r"pid=(\d+)")
ROLE = re.compile(r"role=([\w-]+)")
GAP = re.compile(r"gap_ms=([\d.]+)")
DUR = re.compile(r"stall_duration_ms=([\d.]+)")
FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')

SHUTDOWN_MARKERS = (
    "closeEvent", "shutting down", "Shutting down", "SHUTDOWN", "shutdown",
    "aboutToQuit", "Application exit", "app_exit", "Cleanup complete",
)


def read(name):
    path = os.path.join(LOGS, name)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read().splitlines()


def short(path):
    p = path.replace(ROOT.lower(), "").replace(ROOT, "")
    return p.lstrip("\\/").replace("\\", "/")


def main():
    lines = read("app.log.1") + read("app.log")

    sessions = {}
    for line in lines:
        mt, mp = TS.match(line), PID.search(line)
        if not (mt and mp):
            continue
        mr = ROLE.search(line)
        role = mr.group(1) if mr else "?"
        pid = mp.group(1)
        rec = sessions.setdefault(pid, {"first": mt.group(1), "last": mt.group(1),
                                        "n": 0, "roles": collections.Counter(),
                                        "tail": collections.deque(maxlen=6)})
        rec["last"] = mt.group(1)
        rec["n"] += 1
        rec["roles"][role] += 1
        rec["tail"].append(line)

    mains = {p: r for p, r in sessions.items()
             if r["roles"].get("main", 0) > 50 and r["n"] > 300}

    print("== APP sessions (role=main) ==")
    order = sorted(mains.items(), key=lambda kv: kv[1]["first"])
    for pid, rec in order:
        clean = any(any(m in ln for m in SHUTDOWN_MARKERS) for ln in rec["tail"])
        print("   pid=%-8s %s .. %s  lines=%-6d ended=%s"
              % (pid, rec["first"], rec["last"], rec["n"],
                 "clean-ish" if clean else "ABRUPT (no shutdown marker)"))
    print()
    print("   (everything else in app.log is a download/decode subprocess)")

    # ── gaps between sessions = the restarts the user felt ────────────────
    print()
    print("== restarts today ==")
    prev = None
    for pid, rec in order:
        if prev and rec["first"][:10] == DAY:
            print("   %s (pid %s ends)  ->  %s (pid %s starts)"
                  % (prev[1]["last"], prev[0], rec["first"], pid))
        prev = (pid, rec)

    # ── stalls per session today ─────────────────────────────────────────
    print()
    print("== main-thread stalls today, per session ==")
    per_pid_stalls = collections.defaultdict(list)
    per_pid_traces = collections.defaultdict(list)
    for line in lines:
        mt = TS.match(line)
        if not mt or not mt.group(1).startswith(DAY):
            continue
        mp = PID.search(line)
        if not mp:
            continue
        pid = mp.group(1)
        if "MAIN_THREAD_STALL_TRACE" in line:
            g = GAP.search(line)
            per_pid_traces[pid].append(
                (mt.group(1), float(g.group(1)) if g else 0.0, FRAME.findall(line)))
        elif "[MAIN_THREAD_STALL]" in line:
            d = DUR.search(line)
            per_pid_stalls[pid].append(
                (mt.group(1), float(d.group(1)) if d else 0.0))

    for pid, rec in order:
        if rec["last"][:10] != DAY and rec["first"][:10] != DAY:
            continue
        st = per_pid_stalls.get(pid, [])
        tr = per_pid_traces.get(pid, [])
        if not st and not tr:
            continue
        worst = max((s[1] for s in st), default=0.0)
        over1s = sum(1 for s in st if s[1] >= 1000)
        over3s = sum(1 for s in st if s[1] >= 3000)
        print("   pid=%-8s stalls=%-5d worst=%8.0f ms   >=1s: %-4d >=3s: %-3d  traces=%d"
              % (pid, len(st), worst, over1s, over3s, len(tr)))

    # ── what is stalling in the CURRENT session ──────────────────────────
    current = order[-1][0] if order else None
    print()
    print("== current session pid=%s: innermost stall frames ==" % current)
    inner = collections.Counter()
    weighted = collections.Counter()
    app_frames = collections.Counter()
    for _ts, gap, frames in per_pid_traces.get(current, []):
        if not frames:
            continue
        p, _l, fn = frames[-1]
        key = "%s :: %s" % (short(p), fn)
        inner[key] += 1
        weighted[key] += gap
        for p2, l2, f2 in frames:
            s = short(p2)
            if s.startswith((".venv/", "<")) or s == "main.py":
                continue
            app_frames["%s:%s in %s" % (s, l2, f2)] += 1
    print("   %5s %10s  %s" % ("n", "sum_gap_ms", "frame"))
    for key, count in inner.most_common(15):
        print("   %5d %10.0f  %s" % (count, weighted[key], key))
    print()
    print("   -- app frames anywhere in the stack --")
    for key, count in app_frames.most_common(20):
        print("   %5d  %s" % (count, key))

    print()
    print("== worst 8 stalls in the current session, deepest 3 frames ==")
    for ts, gap, frames in sorted(per_pid_traces.get(current, []),
                                  key=lambda t: -t[1])[:8]:
        print("   %s  gap=%.0f ms" % (ts, gap))
        for p, l, fn in frames[-3:]:
            print("        %s:%s in %s" % (short(p), l, fn))


if __name__ == "__main__":
    main()
