"""One-off: is [MPR_DIAG] "1/12 FAILED" new in 3.6.x or was it already failing
on 3.5.9?  Also: how long does the attachments timeout hold a study open?"""
import bisect
import collections
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

LOGS = r"C:\Users\Dr.Alizadeh\Desktop\log on other pc\pc user 2 sanam\logs\logs"
VERSION_MARKS = [
    ("0000-00-00 00:00:00", "pre-3.5.4"), ("2026-07-19 20:49:43", "3.5.4"),
    ("2026-07-25 22:44:53", "3.5.5"), ("2026-07-27 14:46:56", "3.5.6"),
    ("2026-08-02 21:46:25", "3.5.7"), ("2026-08-10 10:57:01", "3.5.9"),
    ("2026-08-22 21:56:07", "3.6.1"), ("2026-08-23 00:08:54", "3.6.2*"),
]
_KEYS = [m[0] for m in VERSION_MARKS]
TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
ATT = re.compile(r"phase=attachments_\w+ t_ms=([\d.]+)")


def ver(s):
    return VERSION_MARKS[max(0, bisect.bisect_right(_KEYS, s) - 1)][1]


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
                yield line.rstrip("\n")


def main():
    diag = collections.defaultdict(collections.Counter)
    passes = collections.defaultdict(collections.Counter)
    att = collections.defaultdict(list)
    voice = collections.Counter()
    notify = collections.Counter()
    for prefix in ("app.log", "viewer_diagnostics.log"):
        for line in stream(prefix):
            m = TS.match(line)
            if not m:
                continue
            v = ver(m.group(1))
            if "[MPR_DIAG]" in line:
                tail = line.split("[MPR_DIAG]", 1)[1].strip()
                key = re.sub(r"\d+/", "N/", tail)[:46]
                if "FAILED" in tail:
                    diag[v][key] += 1
                else:
                    passes[v][key] += 1
            ma = ATT.search(line)
            if ma:
                att[v].append(float(ma.group(1)))
            if "[VOICE-DELETE-GUARD]" in line:
                voice[v] += 1
            if "skipped malformed dispatch" in line:
                notify[v] += 1

    print("=" * 78)
    print("[MPR_DIAG] FAILED lines per version")
    print("=" * 78)
    for _k, v in VERSION_MARKS:
        if v in diag or v in passes:
            print("   -- %s --   failed=%d  ok=%d"
                  % (v, sum(diag[v].values()), sum(passes[v].values())))
            for key, n in diag[v].most_common(6):
                print("      FAIL %5d  %s" % (n, key))
            for key, n in passes[v].most_common(3):
                print("      ok   %5d  %s" % (n, key))

    print()
    print("=" * 78)
    print("study-open ATTACHMENTS phase duration per version (ms)")
    print("=" * 78)
    for _k, v in VERSION_MARKS:
        if v not in att:
            continue
        vals = sorted(att[v])
        print("   %-8s n=%-5d median=%8.0f  p90=%8.0f  max=%8.0f"
              % (v, len(vals), vals[len(vals) // 2],
                 vals[int(len(vals) * 0.9)], vals[-1]))

    print()
    print("   VOICE-DELETE-GUARD per version:", dict(voice))
    print("   notify() malformed-dispatch per version:", dict(notify))


if __name__ == "__main__":
    main()
