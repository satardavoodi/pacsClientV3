"""One-off: stability review of the end-user logs from PC "sanam".

Buckets everything by the app version that was installed at the time (from
auto_update.log), so a historical bug is never mistaken for a live one.

Read-only. Streams the ~226 MB of logs once and prints compact aggregates.
"""
import bisect
import collections
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

LOGS = r"C:\Users\Dr.Alizadeh\Desktop\log on other pc\pc user 2 sanam\logs\logs"

# From auto_update.log — "reconciled app_version X -> Y" marks the FIRST run of Y.
VERSION_MARKS = [
    ("0000-00-00 00:00:00", "<= 3.5.4 (pre-2026-07-19)"),
    ("2026-07-19 20:49:43", "3.5.4"),
    ("2026-07-25 22:44:53", "3.5.5"),
    ("2026-07-27 14:46:56", "3.5.6"),
    ("2026-08-02 21:46:25", "3.5.7"),
    ("2026-08-10 10:57:01", "3.5.9"),
    ("2026-08-22 21:56:07", "3.6.1"),
    ("2026-08-23 00:08:54", "3.6.2  << CURRENT"),
]
_MARK_KEYS = [m[0] for m in VERSION_MARKS]

TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
LEVEL = re.compile(r"\|\s*(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*\|")
PID = re.compile(r"pid=(\d+)")
ROLE = re.compile(r"role=([\w-]+)")
LOGGER = re.compile(r"\|\s*component=\S+\s+role=\S+\s*\|\s*([\w.<>_]+)\s*\|")
DUR = re.compile(r"stall_duration_ms=([\d.]+)")
GAP = re.compile(r"gap_ms=([\d.]+)")
FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
RSS = re.compile(r"rss=([\d.]+)MB")


def version_at(stamp: str) -> str:
    i = bisect.bisect_right(_MARK_KEYS, stamp) - 1
    return VERSION_MARKS[max(0, i)][1]


def short(path: str) -> str:
    p = path.replace("\\", "/")
    for marker in ("/ai-pacs beta version/", "/AIPacs/", "/_internal/"):
        if marker in p:
            p = p.split(marker, 1)[1]
    if p.lower().startswith("c:/users"):
        p = ".../" + p.rsplit("/", 2)[-1]
    return p


def files(prefix):
    for name in sorted(os.listdir(LOGS)):
        if name.startswith(prefix):
            yield os.path.join(LOGS, name)


def stream(prefix):
    for path in files(prefix):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    yield os.path.basename(path), line.rstrip("\n")
        except OSError as exc:
            print("!! %s: %s" % (path, exc), file=sys.stderr)


def main():
    sessions = {}                      # pid -> dict
    lvl_by_ver = collections.defaultdict(collections.Counter)
    err_by_ver = collections.defaultdict(collections.Counter)   # (ver) -> logger
    err_msg = collections.defaultdict(collections.Counter)      # ver -> short message
    days = collections.Counter()

    for _fname, line in stream("app.log"):
        m = TS.match(line)
        if not m:
            continue
        stamp = m.group(1)
        ver = version_at(stamp)
        days[stamp[:10]] += 1

        mp, mr = PID.search(line), ROLE.search(line)
        if mp:
            pid = mp.group(1)
            role = mr.group(1) if mr else "?"
            rec = sessions.setdefault(pid, {
                "first": stamp, "last": stamp, "n": 0,
                "roles": collections.Counter(), "tail": collections.deque(maxlen=8),
                "errors": 0, "rss_max": 0.0})
            rec["last"] = stamp
            rec["n"] += 1
            rec["roles"][role] += 1
            rec["tail"].append(line[:260])
            mrss = RSS.search(line)
            if mrss:
                rec["rss_max"] = max(rec["rss_max"], float(mrss.group(1)))

        ml = LEVEL.search(line)
        if not ml:
            continue
        level = ml.group(1)
        lvl_by_ver[ver][level] += 1
        if level in ("ERROR", "CRITICAL"):
            if mp:
                sessions[mp.group(1)]["errors"] += 1
            mg = LOGGER.search(line)
            err_by_ver[ver][mg.group(1) if mg else "?"] += 1
            tail = line.split("|")[-1].strip()
            tail = re.sub(r"\d{2,}", "N", tail)[:110]
            err_msg[ver][tail] += 1

    print("=" * 78)
    print("LOG COVERAGE")
    print("=" * 78)
    for day, n in sorted(days.items()):
        print("   %s  %8d app.log lines   [%s]" % (day, n, version_at(day + " 12:00:00")))

    print()
    print("=" * 78)
    print("APP SESSIONS (role=main)")
    print("=" * 78)
    mains = {p: r for p, r in sessions.items()
             if r["roles"].get("main", 0) > 30 and r["n"] > 100}
    SHUT = ("SHUTDOWN-INITIATOR", "aboutToQuit", "instance lock released",
            "Application shutdown")
    for pid, rec in sorted(mains.items(), key=lambda kv: kv[1]["first"]):
        clean = any(any(s in ln for s in SHUT) for ln in rec["tail"])
        print("   pid=%-7s %s .. %s  ver=%-24s lines=%-7d errors=%-5d rssMax=%7.0fMB  end=%s"
              % (pid, rec["first"], rec["last"], version_at(rec["first"]),
                 rec["n"], rec["errors"], rec["rss_max"],
                 "clean" if clean else "ABRUPT"))

    print()
    print("=" * 78)
    print("LOG LEVELS PER VERSION (app.log)")
    print("=" * 78)
    print("   %-26s %9s %9s %9s" % ("version", "WARNING", "ERROR", "CRITICAL"))
    for _k, ver in VERSION_MARKS:
        c = lvl_by_ver.get(ver)
        if not c:
            continue
        print("   %-26s %9d %9d %9d"
              % (ver, c["WARNING"], c["ERROR"], c["CRITICAL"]))

    print()
    print("=" * 78)
    print("TOP ERROR SOURCES PER VERSION")
    print("=" * 78)
    for _k, ver in VERSION_MARKS:
        if ver not in err_by_ver:
            continue
        print("   -- %s --" % ver)
        for logger_name, n in err_by_ver[ver].most_common(8):
            print("      %5d  %s" % (n, logger_name))

    print()
    print("=" * 78)
    print("MOST REPEATED ERROR MESSAGES — CURRENT BUILD ONLY")
    print("=" * 78)
    cur = VERSION_MARKS[-1][1]
    for msg, n in err_msg.get(cur, collections.Counter()).most_common(20):
        print("   %5d  %s" % (n, msg))


if __name__ == "__main__":
    main()
