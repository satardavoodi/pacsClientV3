"""One-off: the overnight profile of pid=1120 (3.6.2) — when did the stalls
happen, was anyone using the app, and what were the final minutes?
"""
import collections
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

LOGS = r"C:\Users\Dr.Alizadeh\Desktop\log on other pc\pc user 2 sanam\logs\logs"
PIDS = ("1120", "2940")

TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
PID = re.compile(r"pid=(\d+)")
DUR = re.compile(r"stall_duration_ms=([\d.]+)")
RSS = re.compile(r"rss=([\d.]+)MB")
CPU = re.compile(r"cpu=([\d.]+)%")
LOGGER = re.compile(r"\|\s*component=\S+\s+role=\S+\s*\|\s*([\w.<>_]+)\s*\|")


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
                yield line.rstrip("\n")


def main():
    per_hour_stall = collections.Counter()
    per_hour_ms = collections.Counter()
    per_hour_lines = collections.Counter()
    per_hour_loggers = collections.defaultdict(collections.Counter)
    rss = []
    cpu_by_hour = collections.defaultdict(list)

    for prefix in ("app.log", "viewer_diagnostics.log"):
        for line in stream(prefix):
            m, mp = TS.match(line), PID.search(line)
            if not (m and mp) or mp.group(1) != "1120":
                continue
            hour = m.group(1)[:13]
            if "MAIN_THREAD_STALL" in line and "TRACE" not in line:
                d = DUR.search(line)
                if d:
                    per_hour_stall[hour] += 1
                    per_hour_ms[hour] += float(d.group(1))
            if prefix != "app.log":
                continue
            per_hour_lines[hour] += 1
            mr, mc = RSS.search(line), CPU.search(line)
            if mr:
                rss.append((m.group(1), float(mr.group(1))))
                if mc:
                    cpu_by_hour[hour].append(float(mc.group(1)))
            else:
                mg = LOGGER.search(line)
                if mg:
                    per_hour_loggers[hour][mg.group(1).rsplit(".", 1)[-1]] += 1

    print("=" * 86)
    print("pid=1120 (3.6.2) HOUR BY HOUR   00:47 .. 06:00")
    print("=" * 86)
    print("   %-14s %8s %10s %10s %9s %9s   %s"
          % ("hour", "stalls", "stall ms", "app lines", "rss MB", "cpu %", "busiest non-resource logger"))
    hours = sorted(set(list(per_hour_stall) + list(per_hour_lines)))
    rss_map = {}
    for stamp, val in rss:
        rss_map.setdefault(stamp[:13], []).append(val)
    for hour in hours:
        top = per_hour_loggers[hour].most_common(1)
        cpus = cpu_by_hour.get(hour, [])
        rvals = rss_map.get(hour, [])
        print("   %-14s %8d %10.0f %10d %9s %9s   %s"
              % (hour, per_hour_stall[hour], per_hour_ms[hour], per_hour_lines[hour],
                 "%.0f" % (sum(rvals) / len(rvals)) if rvals else "-",
                 "%.1f" % (sum(cpus) / len(cpus)) if cpus else "-",
                 ("%s x%d" % top[0]) if top else "-"))

    print()
    print("=" * 86)
    print("LAST REAL (non-resource-summary) ACTIVITY of pid=1120")
    print("=" * 86)
    tail = collections.deque(maxlen=14)
    for prefix in ("app.log", "viewer_diagnostics.log", "download_diagnostics.log"):
        for line in stream(prefix):
            mp = PID.search(line)
            if not mp or mp.group(1) != "1120":
                continue
            if "resource-summary" in line or "MAIN_THREAD_STALL" in line:
                continue
            if "_probe_tick" in line:
                continue
            tail.append(line)
    for line in tail:
        print("   " + line[:200])

    print()
    print("=" * 86)
    print("pid=2940 (3.6.2, daytime, the CLEAN session) — same hour table")
    print("=" * 86)
    ph_s, ph_l = collections.Counter(), collections.Counter()
    for prefix in ("app.log", "viewer_diagnostics.log"):
        for line in stream(prefix):
            m, mp = TS.match(line), PID.search(line)
            if not (m and mp) or mp.group(1) != "2940":
                continue
            hour = m.group(1)[:13]
            if "MAIN_THREAD_STALL" in line and "TRACE" not in line:
                ph_s[hour] += 1
            if prefix == "app.log":
                ph_l[hour] += 1
    for hour in sorted(set(list(ph_s) + list(ph_l))):
        print("   %-14s stalls=%-6d app lines=%d" % (hour, ph_s[hour], ph_l[hour]))


if __name__ == "__main__":
    main()
