"""One-off: deep dive on PC "sanam" — the 3.6.2 disappearance, memory trend,
stall rate normalised by uptime, network + DICOM failures.
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
RSS = re.compile(r"rss=([\d.]+)MB")
DUR = re.compile(r"stall_duration_ms=([\d.]+)")
THR = re.compile(r"threshold_ms=([\d.]+)")

CRASH_PID = "1120"


def ver(stamp):
    return VERSION_MARKS[max(0, bisect.bisect_right(_KEYS, stamp) - 1)][1]


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


def secs(stamp):
    d = stamp[8:10]
    h, m, s = stamp[11:].split(":")
    return int(d) * 86400 + int(h) * 3600 + int(m) * 60 + int(s)


def main():
    # ── 1. absolute last activity of every log for the crashed pid ─────────
    print("=" * 78)
    print("1. LAST ACTIVITY OF pid=%s (3.6.2, vanished) ACROSS ALL LOGS" % CRASH_PID)
    print("=" * 78)
    for prefix in ("app.log", "viewer_diagnostics.log", "db_diagnostics.log",
                   "download_diagnostics.log"):
        last, count = None, 0
        for line in stream(prefix):
            mp = PID.search(line)
            if mp and mp.group(1) == CRASH_PID:
                m = TS.match(line)
                if m:
                    last = line
                    count += 1
        print("   %-28s lines=%-7d last=%s" % (prefix, count,
                                               (last or "")[:150]))

    # ── 2. the quiet window: any activity between the death and the next start
    print()
    print("=" * 78)
    print("2. ANY LOG LINE BETWEEN 2026-08-23 06:00:28 AND 09:34:33")
    print("=" * 78)
    found = []
    for prefix in ("app.log", "viewer_diagnostics.log", "db_diagnostics.log",
                   "download_diagnostics.log"):
        for line in stream(prefix):
            m = TS.match(line)
            if m and "2026-08-23 06:00:28" <= m.group(1) <= "2026-08-23 09:34:33":
                found.append((prefix, line[:170]))
    print("   lines in that window: %d" % len(found))
    for prefix, line in found[:15]:
        print("   [%s] %s" % (prefix, line))

    # ── 3. RSS trend per session ──────────────────────────────────────────
    print()
    print("=" * 78)
    print("3. MEMORY TREND (rss) PER SESSION")
    print("=" * 78)
    per_pid = collections.defaultdict(list)
    for line in stream("app.log"):
        mr = RSS.search(line)
        if not mr:
            continue
        m, mp = TS.match(line), PID.search(line)
        if m and mp:
            per_pid[mp.group(1)].append((m.group(1), float(mr.group(1))))
    for pid, samples in sorted(per_pid.items(), key=lambda kv: kv[1][0][0]):
        if len(samples) < 40:
            continue
        first, last = samples[0], samples[-1]
        peak = max(samples, key=lambda s: s[1])
        hours = max(0.01, (secs(last[0]) - secs(first[0])) / 3600.0)
        print("   pid=%-7s [%-6s] %s .. %s  %5.1f h  start=%6.0f  end=%6.0f  peak=%6.0f MB (%s)  growth=%+6.0f MB/h"
              % (pid, ver(first[0]), first[0][5:16], last[0][5:16], hours,
                 first[1], last[1], peak[1], peak[0][11:], (last[1] - first[1]) / hours))

    # ── 4. stall rate normalised by uptime + thresholds ───────────────────
    print()
    print("=" * 78)
    print("4. STALL RATE PER VERSION (normalised) + THRESHOLD")
    print("=" * 78)
    dur = collections.defaultdict(list)
    thr = collections.defaultdict(collections.Counter)
    uptime = collections.defaultdict(float)
    seen_pid_ver = {}
    for prefix in ("app.log", "viewer_diagnostics.log"):
        for line in stream(prefix):
            if "MAIN_THREAD_STALL" not in line or "TRACE" in line:
                continue
            m = TS.match(line)
            if not m:
                continue
            v = ver(m.group(1))
            d, t = DUR.search(line), THR.search(line)
            if d:
                dur[v].append(float(d.group(1)))
            if t:
                thr[v][t.group(1)] += 1
    # uptime per version from app.log session spans
    spans = {}
    for line in stream("app.log"):
        m, mp = TS.match(line), PID.search(line)
        if not (m and mp):
            continue
        rec = spans.setdefault(mp.group(1), [m.group(1), m.group(1), 0])
        rec[1] = m.group(1)
        rec[2] += 1
    for pid, (a, b, n) in spans.items():
        if n < 100:
            continue
        uptime[ver(a)] += max(0.0, (secs(b) - secs(a)) / 3600.0)

    print("   %-10s %8s %9s %9s %9s %10s %10s" %
          ("version", "stalls", "uptime h", "per hour", ">=1s", "worst ms", "median ms"))
    for _k, v in VERSION_MARKS:
        if v not in dur:
            continue
        d = sorted(dur[v])
        up = uptime.get(v, 0.0)
        med = d[len(d) // 2]
        print("   %-10s %8d %9.1f %9.1f %9d %10.0f %10.0f"
              % (v, len(d), up, len(d) / up if up else 0,
                 sum(1 for x in d if x >= 1000), d[-1], med))
        print("        thresholds seen: %s" % dict(thr[v]))

    # ── 5. network + DICOM failures per version ───────────────────────────
    print()
    print("=" * 78)
    print("5. NETWORK / DICOM / RESOURCE FAILURE MARKERS PER VERSION")
    print("=" * 78)
    MARKERS = {
        "WinError 10061 (connection refused)": "10061",
        "WinError 10054 (reset by peer)": "10054",
        "WinError 10060 (timed out)": "10060",
        "socket timeout": "timed out",
        "Search returned None": "Search returned None",
        "reconnect": "reconnect",
        "MemoryError": "MemoryError",
        "Unable to decode": "Unable to decode",
        "pixel data": "pixel data",
        "corrupt": "corrupt",
        "database is locked": "database is locked",
        "Traceback": "Traceback",
        "RuntimeError": "RuntimeError",
        "wrapped C/C++ object": "wrapped C/C++ object",
        "TimeoutError": "TimeoutError",
        "BrokenProcessPool": "BrokenProcessPool",
        "decode service": "[B3.11]",
        "OSError": "OSError",
    }
    counts = collections.defaultdict(collections.Counter)
    for prefix in ("app.log", "download_diagnostics.log", "viewer_diagnostics.log"):
        for line in stream(prefix):
            m = TS.match(line)
            if not m:
                continue
            v = ver(m.group(1))
            for label, needle in MARKERS.items():
                if needle in line:
                    counts[label][v] += 1
    vers = [v for _k, v in VERSION_MARKS]
    print("   %-38s %s" % ("marker", "".join("%10s" % v for v in vers if any(counts[l][v] for l in MARKERS))))
    live = [v for v in vers if any(counts[l][v] for l in MARKERS)]
    for label in MARKERS:
        row = counts[label]
        if not sum(row.values()):
            continue
        print("   %-38s %s" % (label, "".join("%10d" % row[v] for v in live)))


if __name__ == "__main__":
    main()
