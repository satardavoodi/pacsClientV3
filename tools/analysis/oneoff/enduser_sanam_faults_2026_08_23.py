"""One-off: native faults, session endings and main-thread stalls for PC "sanam",
bucketed by the app version installed at the time.

Rotated logs are read OLDEST-FIRST (.3, .2, .1, base) — reading them in name
order puts the newest file first and silently corrupts every first/last stamp.
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

TS = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")
PID = re.compile(r"pid=(\d+)")
ROLE = re.compile(r"role=([\w-]+)")
DUR = re.compile(r"stall_duration_ms=([\d.]+)")
GAP = re.compile(r"gap_ms=([\d.]+)")
FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
RSS = re.compile(r"rss=([\d.]+)MB")


def ver(stamp):
    s = stamp.replace("T", " ")
    return VERSION_MARKS[max(0, bisect.bisect_right(_KEYS, s) - 1)][1]


def short(path):
    p = path.replace("\\", "/")
    for marker in ("/ai-pacs beta version/", "/AIPacs/", "/_internal/", "/app/"):
        if marker in p:
            p = p.split(marker, 1)[1]
    low = p.lower()
    if low.startswith("c:/") or low.startswith("<"):
        p = ".../" + p.rsplit("/", 1)[-1]
    return p


def ordered(prefix):
    """Rotated logs oldest-first: name.3, name.2, name.1, name."""
    names = [n for n in os.listdir(LOGS) if n.startswith(prefix)]

    def key(n):
        tail = n[len(prefix):]
        return -int(tail.lstrip(".")) if tail.lstrip(".").isdigit() else 0

    return [os.path.join(LOGS, n) for n in sorted(names, key=key)]


def stream(prefix):
    for path in ordered(prefix):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                yield line.rstrip("\n")


# ────────────────────────── native faults ──────────────────────────────────

def native_faults():
    path = os.path.join(LOGS, "native_fault.log")
    lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
    print("native_fault.log: %d lines" % len(lines))
    records, i = [], 0
    while i < len(lines):
        if "fatal exception" in lines[i] or "Fatal Python error" in lines[i]:
            stamp = ""
            for back in range(i, max(-1, i - 12), -1):
                m = TS.search(lines[back])
                if m:
                    stamp = m.group(1)
                    break
            frames, j, seen = [], i, False
            while j < len(lines) and j < i + 400:
                if lines[j].startswith("Current thread"):
                    seen = True
                elif seen:
                    m = FRAME.search(lines[j])
                    if m:
                        frames.append((short(m.group(1)), m.group(2), m.group(3)))
                    elif not lines[j].strip() and frames:
                        break
                j += 1
            records.append((stamp, lines[i].strip(), frames))
            i = j
        else:
            i += 1

    by_ver = collections.Counter()
    sites = collections.Counter()
    for stamp, kind, frames in records:
        v = ver(stamp) if stamp else "?"
        by_ver[v] += 1
        app = [f for f in frames if not f[0].startswith((".../", "<"))]
        site = "%s:%s in %s" % app[0] if app else (frames[-1][2] if frames else "?")
        sites[(v, kind[:46], site)] += 1

    print("   records: %d" % len(records))
    print()
    print("   faults per version:")
    for _k, v in VERSION_MARKS:
        if by_ver.get(v):
            print("      %-10s %4d" % (v, by_ver[v]))
    if by_ver.get("?"):
        print("      %-10s %4d" % ("(no stamp)", by_ver["?"]))
    print()
    print("   fault sites:")
    for (v, kind, site), n in sites.most_common(18):
        print("      %-9s %4d  %-44s %s" % (v, n, kind, site))
    print()
    print("   last 8 records:")
    for stamp, kind, frames in records[-8:]:
        print("      %s  [%s]  %s" % (stamp or "?", ver(stamp) if stamp else "?", kind[:70]))
        for f in frames[:5]:
            print("           %s:%s in %s" % f)
    return records


# ────────────────────────── sessions ───────────────────────────────────────

def sessions():
    recs = {}
    order = []
    for line in stream("app.log"):
        m, mp = TS.match(line), PID.search(line)
        if not (m and mp):
            continue
        pid, stamp = mp.group(1), m.group(1)
        mr = ROLE.search(line)
        r = recs.get(pid)
        if r is None:
            r = recs[pid] = {"first": stamp, "last": stamp, "n": 0,
                             "roles": collections.Counter(),
                             "tail": collections.deque(maxlen=10), "rss": 0.0}
            order.append(pid)
        r["last"] = stamp
        r["n"] += 1
        r["roles"][mr.group(1) if mr else "?"] += 1
        r["tail"].append(line)
        mrss = RSS.search(line)
        if mrss:
            r["rss"] = max(r["rss"], float(mrss.group(1)))

    SHUT = ("SHUTDOWN-INITIATOR", "aboutToQuit", "instance lock released",
            "Application shutdown", "AGENT_GATEWAY] stopped")
    print()
    print("=" * 78)
    print("APP SESSIONS, oldest first (role=main only)")
    print("=" * 78)
    out = []
    for pid in order:
        r = recs[pid]
        if r["roles"].get("main", 0) < 30 or r["n"] < 100:
            continue
        clean = any(any(s in ln for s in SHUT) for ln in r["tail"])
        out.append((pid, r, clean))
        print("   pid=%-7s %s .. %s  [%-6s] lines=%-7d rssMax=%6.0fMB  end=%s"
              % (pid, r["first"], r["last"], ver(r["first"]), r["n"], r["rss"],
                 "clean" if clean else "**ABRUPT**"))
    print()
    print("   last lines of every ABRUPT session:")
    for pid, r, clean in out:
        if clean:
            continue
        print()
        print("   -- pid=%s (%s) ended %s --" % (pid, ver(r["first"]), r["last"]))
        for ln in list(r["tail"])[-6:]:
            print("      " + ln[:220])
    return out


# ────────────────────────── stalls ─────────────────────────────────────────

def stalls():
    per_ver_dur = collections.defaultdict(list)
    per_ver_inner = collections.defaultdict(collections.Counter)
    per_ver_app = collections.defaultdict(collections.Counter)
    worst = []
    for prefix in ("app.log", "viewer_diagnostics.log"):
        for line in stream(prefix):
            if "MAIN_THREAD_STALL" not in line:
                continue
            m = TS.match(line)
            if not m:
                continue
            v = ver(m.group(1))
            if "MAIN_THREAD_STALL_TRACE" in line:
                g = GAP.search(line)
                gap = float(g.group(1)) if g else 0.0
                frames = FRAME.findall(line)
                if frames:
                    p, _l, fn = frames[-1]
                    per_ver_inner[v]["%s :: %s" % (short(p), fn)] += 1
                    for p2, l2, f2 in frames:
                        s = short(p2)
                        if s.startswith((".../", "<")) or s.endswith("main.py"):
                            continue
                        per_ver_app[v]["%s:%s in %s" % (s, l2, f2)] += 1
                worst.append((gap, m.group(1), v, frames))
            else:
                d = DUR.search(line)
                if d:
                    per_ver_dur[v].append((float(d.group(1)), m.group(1)))

    print()
    print("=" * 78)
    print("MAIN-THREAD STALLS PER VERSION")
    print("=" * 78)
    print("   %-10s %8s %8s %8s %10s" % ("version", "stalls", ">=1s", ">=5s", "worst ms"))
    for _k, v in VERSION_MARKS:
        d = per_ver_dur.get(v)
        if not d:
            continue
        print("   %-10s %8d %8d %8d %10.0f"
              % (v, len(d), sum(1 for x, _ in d if x >= 1000),
                 sum(1 for x, _ in d if x >= 5000), max(x for x, _ in d)))

    for _k, v in VERSION_MARKS:
        if v not in per_ver_inner:
            continue
        print()
        print("   -- %s: innermost frame --" % v)
        for key, n in per_ver_inner[v].most_common(10):
            print("      %5d  %s" % (n, key))
        print("   -- %s: app frames anywhere --" % v)
        for key, n in per_ver_app[v].most_common(12):
            print("      %5d  %s" % (n, key))

    print()
    print("   worst 10 stalls overall:")
    for gap, stamp, v, frames in sorted(worst, reverse=True)[:10]:
        print("      %s [%-6s] gap=%8.0f ms" % (stamp, v, gap))
        for f in frames[-3:]:
            print("           %s:%s in %s" % (short(f[0]), f[1], f[2]))


if __name__ == "__main__":
    native_faults()
    sessions()
    stalls()
