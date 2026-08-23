"""One-off: pid 24696 (3.6.2) hung at 00:47:02 per Windows Application Hang 1002.
What was it doing in its last two minutes?  Read-only.
"""
import collections
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

LOGS = r"C:\Users\Dr.Alizadeh\Desktop\log on other pc\pc user 2 sanam\logs\logs"
PID = "24696"
LO, HI = "2026-08-23 00:45:00", "2026-08-23 00:47:30"

TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
PIDRE = re.compile(r"pid=(\d+)")
LOGGER = re.compile(r"\|\s*component=\S+\s+role=\S+\s*\|\s*([\w.<>_]+)\s*\|")
DUR = re.compile(r"stall_duration_ms=([\d.]+)")


def ordered(prefix):
    names = [n for n in os.listdir(LOGS) if n.startswith(prefix)]

    def key(n):
        t = n[len(prefix):].lstrip(".")
        return -int(t) if t.isdigit() else 0
    return [os.path.join(LOGS, n) for n in sorted(names, key=key)]


def stream(prefix):
    for path in ordered(prefix):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                yield prefix, line.rstrip("\n")


def main():
    lines = []
    for prefix in ("app.log", "viewer_diagnostics.log", "db_diagnostics.log",
                   "download_diagnostics.log"):
        for src, line in stream(prefix):
            m, mp = TS.match(line), PIDRE.search(line)
            if not (m and mp) or mp.group(1) != PID:
                continue
            if LO <= m.group(1) <= HI:
                lines.append((m.group(1), src, line))
    lines.sort()
    print("lines for pid=%s in %s .. %s : %d" % (PID, LO, HI, len(lines)))

    print()
    print("== busiest loggers in that window ==")
    c = collections.Counter()
    for _t, _s, line in lines:
        if "resource-summary" in line or "MAIN_THREAD_STALL" in line:
            continue
        mg = LOGGER.search(line)
        if mg:
            c[mg.group(1)] += 1
    for who, n in c.most_common(12):
        print("   %5d  %s" % (n, who))

    print()
    print("== stalls recorded in that window ==")
    for t, s, line in lines:
        d = DUR.search(line)
        if d and "TRACE" not in line:
            print("   %s  %8.0f ms" % (t, float(d.group(1))))

    print()
    print("== last 40 non-heartbeat lines before the hang ==")
    tail = [x for x in lines if "resource-summary" not in x[2]
            and "_probe_tick" not in x[2]][-40:]
    for t, s, line in tail:
        body = line.split("result=- |", 1)[-1].strip() if "result=- |" in line else line
        mg = LOGGER.search(line)
        print("   %s [%-24s] %-52s %s"
              % (t, s, (mg.group(1) if mg else "?")[-52:], body[:110]))

    print()
    print("== final heartbeats (rss / cpu) ==")
    for t, s, line in lines:
        if "resource-summary" in line:
            print("   %s  %s" % (t, line.split("|")[-1].strip()[:110]))


if __name__ == "__main__":
    main()
