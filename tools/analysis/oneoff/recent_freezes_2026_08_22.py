"""One-off: the freezes in the two most recent sessions, and how pid 497328 ended.

Reads BOTH app.log* and viewer_diagnostics.log* (the stall probe writes to the
latter; the close path to the former).  Read-only.
"""
import collections
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
LOGS = os.path.join(ROOT, "user_data", "logs")

TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
PID = re.compile(r"pid=(\d+)")
GAP = re.compile(r"gap_ms=([\d.]+)")
DUR = re.compile(r"stall_duration_ms=([\d.]+)")
FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')


def short(path):
    p = path.replace(ROOT.lower(), "").replace(ROOT, "")
    return p.lstrip("\\/").replace("\\", "/")


def scan(prefixes):
    for name in sorted(os.listdir(LOGS)):
        if not name.startswith(prefixes):
            continue
        with open(os.path.join(LOGS, name), "r", encoding="utf-8",
                  errors="replace") as fh:
            for line in fh:
                yield line.rstrip("\n")


def episodes(stalls, gap_s=20.0):
    """Group consecutive stall samples into freeze EPISODES."""
    out = []
    cur = None
    for ts, ms in stalls:
        if cur and (_secs(ts) - _secs(cur[-1][0])) <= gap_s:
            cur.append((ts, ms))
        else:
            if cur:
                out.append(cur)
            cur = [(ts, ms)]
    if cur:
        out.append(cur)
    return out


def _secs(ts):
    h, m, s = ts[11:].split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def main():
    for pid in ("497328", "522184"):
        stalls, traces = [], []
        for line in scan(("app.log", "viewer_diagnostics.log")):
            mt = TS.match(line)
            if not mt or "MAIN_THREAD_STALL" not in line:
                continue
            mp = PID.search(line)
            if not mp or mp.group(1) != pid:
                continue
            if "MAIN_THREAD_STALL_TRACE" in line:
                g = GAP.search(line)
                traces.append((mt.group(1), float(g.group(1)) if g else 0.0,
                               FRAME.findall(line)))
            else:
                d = DUR.search(line)
                stalls.append((mt.group(1), float(d.group(1)) if d else 0.0))

        stalls.sort()
        print("=" * 72)
        print("pid=%s   stall samples=%d   traces=%d" % (pid, len(stalls), len(traces)))
        eps = [e for e in episodes(stalls) if max(x[1] for x in e) >= 1500]
        print("freeze episodes >= 1.5 s : %d" % len(eps))
        for ep in sorted(eps, key=lambda e: -max(x[1] for x in e))[:6]:
            peak = max(x[1] for x in ep)
            print("   %s .. %s   peak=%.1f s   samples=%d"
                  % (ep[0][0][11:], ep[-1][0][11:], peak / 1000.0, len(ep)))
            lo, hi = ep[0][0], ep[-1][0]
            frames = collections.Counter()
            deepest = None
            for ts, gap, fr in traces:
                if lo <= ts <= hi and fr:
                    for p, l, fn in fr:
                        s = short(p)
                        if s.startswith((".venv/", "<")) or s == "main.py":
                            continue
                        frames["%s:%s in %s" % (s, l, fn)] += 1
                    if deepest is None or gap > deepest[0]:
                        deepest = (gap, fr)
            for key, n in frames.most_common(4):
                print("        %3d  %s" % (n, key))
            if deepest:
                print("        deepest: %s" % " <- ".join(
                    "%s:%s" % (short(p), l) for p, l, _f in deepest[1][-3:]))
        print()

    # ── how did pid 497328 end? ─────────────────────────────────────────
    print("=" * 72)
    print("== last 20 lines logged by pid 497328 ==")
    tail = collections.deque(maxlen=20)
    for line in scan(("app.log",)):
        mp = PID.search(line)
        if mp and mp.group(1) == "497328":
            tail.append(line)
    for line in tail:
        print("   " + line[:230])


if __name__ == "__main__":
    main()
