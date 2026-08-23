"""One-off: is the 3.6.2 stall rate a real regression or a coverage/startup artifact?

Normalises by the window where viewer_diagnostics ACTUALLY covers each version,
buckets stall durations, and splits startup (first 3 min of a session) from
steady state.  Read-only.
"""
import bisect
import collections
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

LOGS = r"C:\Users\Dr.Alizadeh\Desktop\log on other pc\pc user 2 sanam\logs\logs"

VERSION_MARKS = [
    ("0000-00-00 00:00:00", "pre-3.5.4"),
    ("2026-07-19 20:49:43", "3.5.4"),
    ("2026-07-25 22:44:53", "3.5.5"),
    ("2026-07-27 14:46:56", "3.5.6"),
    ("2026-08-02 21:46:25", "3.5.7"),
    ("2026-08-10 10:57:01", "3.5.9"),
    ("2026-08-22 21:56:07", "3.6.1"),
    ("2026-08-23 00:08:54", "3.6.2*"),
]
_KEYS = [m[0] for m in VERSION_MARKS]

TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
PID = re.compile(r"pid=(\d+)")
DUR = re.compile(r"stall_duration_ms=([\d.]+)")
GAP = re.compile(r"gap_ms=([\d.]+)")
FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')

# app sessions (role=main) discovered earlier, oldest first
SESSIONS = [
    ("7084", "2026-08-19 12:20:50", "2026-08-22 09:24:05", "3.5.9"),
    ("26332", "2026-08-22 09:24:14", "2026-08-22 17:14:21", "3.5.9"),
    ("14684", "2026-08-22 15:41:43", "2026-08-22 16:05:38", "3.5.9"),
    ("24936", "2026-08-22 16:31:59", "2026-08-22 21:41:42", "3.5.9"),
    ("19540", "2026-08-22 21:55:46", "2026-08-22 22:11:17", "3.5.9"),
    ("3584", "2026-08-22 22:13:00", "2026-08-23 00:06:25", "3.6.1"),
    ("24696", "2026-08-23 00:08:33", "2026-08-23 00:46:45", "3.6.1"),
    ("1120", "2026-08-23 00:47:13", "2026-08-23 06:00:27", "3.6.2*"),
    ("2940", "2026-08-23 09:34:45", "2026-08-23 10:33:25", "3.6.2*"),
]
START = {s[0]: s[1] for s in SESSIONS}
VERS = {s[0]: s[3] for s in SESSIONS}


def secs(stamp):
    d = int(stamp[8:10])
    h, m, s = stamp[11:].split(":")
    return d * 86400 + int(h) * 3600 + int(m) * 60 + int(s)


def short(path):
    p = path.replace("\\", "/")
    for marker in ("/ai-pacs beta version/", "/_internal/"):
        if marker in p:
            p = p.split(marker, 1)[1]
    return p


def ordered(prefix):
    names = [n for n in os.listdir(LOGS) if n.startswith(prefix)]

    def key(n):
        tail = n[len(prefix):].lstrip(".")
        return -int(tail) if tail.isdigit() else 0
    return [os.path.join(LOGS, n) for n in sorted(names, key=key)]


def stream(prefix):
    for path in ordered(prefix):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                yield os.path.basename(path), line.rstrip("\n")


def main():
    # ── coverage of the stall probe, per file ────────────────────────────
    print("=" * 78)
    print("viewer_diagnostics COVERAGE (where the stall probe actually wrote)")
    print("=" * 78)
    cover = {}
    for fname, line in stream("viewer_diagnostics.log"):
        m = TS.match(line)
        if not m:
            continue
        rec = cover.setdefault(fname, [m.group(1), m.group(1), 0])
        rec[1] = m.group(1)
        rec[2] += 1
    for fname in sorted(cover, key=lambda f: cover[f][0]):
        a, b, n = cover[fname]
        print("   %-28s %s .. %s  (%d lines)" % (fname, a, b, n))

    # ── stalls per SESSION, split startup vs steady ──────────────────────
    per_sess = collections.defaultdict(list)
    traces = collections.defaultdict(list)
    for prefix in ("app.log", "viewer_diagnostics.log"):
        for _f, line in stream(prefix):
            if "MAIN_THREAD_STALL" not in line:
                continue
            m, mp = TS.match(line), PID.search(line)
            if not (m and mp):
                continue
            pid = mp.group(1)
            if pid not in START:
                continue
            if "TRACE" in line:
                g = GAP.search(line)
                traces[pid].append((m.group(1), float(g.group(1)) if g else 0.0,
                                    FRAME.findall(line)))
            else:
                d = DUR.search(line)
                if d:
                    per_sess[pid].append((m.group(1), float(d.group(1))))

    print()
    print("=" * 78)
    print("STALLS PER SESSION — startup (first 3 min) vs steady state")
    print("=" * 78)
    print("   %-7s %-7s %7s %7s %8s %8s %9s %9s"
          % ("pid", "ver", "total", "startup", "steady", "steady/h", "median", "worst"))
    for pid, s0, s1, v in SESSIONS:
        rows = per_sess.get(pid, [])
        if not rows:
            print("   %-7s %-7s      -   (no stall records retained)" % (pid, v))
            continue
        t0 = secs(s0)
        boot = [r for r in rows if secs(r[0]) - t0 <= 180]
        steady = [r for r in rows if secs(r[0]) - t0 > 180]
        hours = max(0.01, (secs(s1) - t0 - 180) / 3600.0)
        vals = sorted(x for _t, x in rows)
        print("   %-7s %-7s %7d %7d %8d %8.1f %9.0f %9.0f"
              % (pid, v, len(rows), len(boot), len(steady), len(steady) / hours,
                 vals[len(vals) // 2], vals[-1]))

    # ── duration buckets for the two 3.6.2 sessions vs 3.5.9 ─────────────
    print()
    print("=" * 78)
    print("STALL DURATION BUCKETS (ms)")
    print("=" * 78)
    buckets = [(100, 200), (200, 500), (500, 1000), (1000, 3000), (3000, 10 ** 9)]
    print("   %-7s %-7s %10s %10s %10s %10s %10s"
          % ("pid", "ver", "100-200", "200-500", "500-1k", "1k-3k", ">3s"))
    for pid, _s0, _s1, v in SESSIONS:
        rows = per_sess.get(pid, [])
        if not rows:
            continue
        counts = []
        for lo, hi in buckets:
            counts.append(sum(1 for _t, x in rows if lo <= x < hi))
        print("   %-7s %-7s %10d %10d %10d %10d %10d" % (pid, v, *counts))

    # ── what the 3.6.2 steady-state stalls actually are ──────────────────
    print()
    print("=" * 78)
    print("3.6.2 STEADY-STATE STALL STACKS (after the first 3 min)")
    print("=" * 78)
    inner = collections.Counter()
    app = collections.Counter()
    deep = []
    for pid in ("1120", "2940"):
        t0 = secs(START[pid])
        for stamp, gap, frames in traces.get(pid, []):
            if secs(stamp) - t0 <= 180 or not frames:
                continue
            p, _l, fn = frames[-1]
            inner["%s :: %s" % (short(p), fn)] += 1
            for p2, l2, f2 in frames:
                s = short(p2)
                if s.startswith(("<", "C:")) or s.endswith(("main.py", "qasync/__init__.py")):
                    continue
                app["%s:%s in %s" % (s, l2, f2)] += 1
            deep.append((gap, stamp, frames))
    print("   traces after startup: %d" % len(deep))
    print("   -- innermost --")
    for key, n in inner.most_common(12):
        print("      %5d  %s" % (n, key))
    print("   -- app frames anywhere --")
    for key, n in app.most_common(15):
        print("      %5d  %s" % (n, key))
    print("   -- worst 6 --")
    for gap, stamp, frames in sorted(deep, reverse=True)[:6]:
        print("      %s gap=%.0f ms" % (stamp, gap))
        for f in frames[-4:]:
            print("           %s:%s in %s" % (short(f[0]), f[1], f[2]))


if __name__ == "__main__":
    main()
