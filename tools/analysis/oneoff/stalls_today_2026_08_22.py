"""One-off: find today's main-thread stalls wherever they were written.

Yesterday the stall records were in app.log; the probe also writes to
viewer_diagnostics.log. Scan BOTH (plus their rotations) and report per day so a
"there are no stalls" answer can never come from looking in the wrong file.
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
GAP = re.compile(r"gap_ms=([\d.]+)")
DUR = re.compile(r"stall_duration_ms=([\d.]+)")
FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')


def short(path):
    p = path.replace(ROOT.lower(), "").replace(ROOT, "")
    return p.lstrip("\\/").replace("\\", "/")


def files():
    for name in sorted(os.listdir(LOGS)):
        if name.startswith(("app.log", "viewer_diagnostics.log")):
            yield name


def main():
    per_day = collections.Counter()
    per_day_file = collections.Counter()
    today_stalls = []
    today_traces = []

    for name in files():
        path = os.path.join(LOGS, name)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "MAIN_THREAD_STALL" not in line:
                    continue
                m = TS.match(line)
                if not m:
                    continue
                day = m.group(1)[:10]
                per_day[day] += 1
                per_day_file[(day, name)] += 1
                if day != DAY:
                    continue
                mp = PID.search(line)
                pid = mp.group(1) if mp else "?"
                if "MAIN_THREAD_STALL_TRACE" in line:
                    g = GAP.search(line)
                    today_traces.append((m.group(1), pid,
                                         float(g.group(1)) if g else 0.0,
                                         FRAME.findall(line)))
                else:
                    d = DUR.search(line)
                    today_stalls.append((m.group(1), pid,
                                         float(d.group(1)) if d else 0.0))

    print("== stall records per day (all app.log* + viewer_diagnostics.log*) ==")
    for day, count in sorted(per_day.items())[-8:]:
        srcs = ", ".join("%s=%d" % (f, n) for (d, f), n in
                         sorted(per_day_file.items()) if d == day)
        print("   %s  %5d   [%s]" % (day, count, srcs))

    print()
    print("== %s ==" % DAY)
    print("   [MAIN_THREAD_STALL]       : %d" % len(today_stalls))
    print("   [MAIN_THREAD_STALL_TRACE] : %d" % len(today_traces))
    if not today_stalls and not today_traces:
        print("   -> the probe produced NOTHING today; check it is enabled.")
        return

    by_pid = collections.Counter(p for _t, p, _d in today_stalls)
    print()
    print("   stalls per pid:", dict(by_pid))
    worst = sorted(today_stalls, key=lambda s: -s[2])[:12]
    print()
    print("== worst 12 stall durations today ==")
    for ts, pid, ms in worst:
        print("   %s  pid=%-8s %8.0f ms" % (ts, pid, ms))

    inner = collections.Counter()
    weighted = collections.Counter()
    app_frames = collections.Counter()
    for _ts, _pid, gap, frames in today_traces:
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

    print()
    print("== innermost frame (what was executing) ==")
    print("   %5s %10s  %s" % ("n", "sum_gap_ms", "frame"))
    for key, count in inner.most_common(20):
        print("   %5d %10.0f  %s" % (count, weighted[key], key))

    print()
    print("== app frames anywhere in the stack ==")
    for key, count in app_frames.most_common(25):
        print("   %5d  %s" % (count, key))

    print()
    print("== deepest 3 frames of the 10 longest traces ==")
    for ts, pid, gap, frames in sorted(today_traces, key=lambda t: -t[2])[:10]:
        print("   %s pid=%s gap=%.0f ms" % (ts, pid, gap))
        for p, l, fn in frames[-3:]:
            print("        %s:%s in %s" % (short(p), l, fn))


if __name__ == "__main__":
    main()
