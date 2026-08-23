"""One-off: what blocked the UI thread during the 2026-08-21 13:49 import?

Scans app.log* / viewer_diagnostics.log* for MAIN_THREAD_STALL_TRACE records in
the import window, extracts the INNERMOST frames (the code actually running) and
ranks them.  Read-only.
"""
import collections
import os
import re

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
LOGS = os.path.join(ROOT, "user_data", "logs")
WINDOW_START = "2026-08-21 13:45"
WINDOW_END = "2026-08-21 14:10"

TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+")
GAP = re.compile(r"gap_ms=([\d.]+)")
FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')


def iter_lines():
    for name in sorted(os.listdir(LOGS)):
        if not name.startswith(("app.log", "viewer_diagnostics.log")):
            continue
        with open(os.path.join(LOGS, name), "r", encoding="utf-8",
                  errors="replace") as fh:
            for line in fh:
                yield line.rstrip("\n")


def short(path):
    p = path.replace(ROOT.lower(), "").replace(ROOT, "")
    return p.lstrip("\\/").replace("\\", "/")


def main():
    traces = []
    for line in iter_lines():
        m = TS.match(line)
        if not m or not (WINDOW_START <= m.group(1)[:16] <= WINDOW_END):
            continue
        if "MAIN_THREAD_STALL_TRACE" not in line:
            continue
        gap = float(GAP.search(line).group(1)) if GAP.search(line) else 0.0
        frames = FRAME.findall(line)
        traces.append((m.group(1), gap, frames))

    print("== %d traces in %s .. %s ==" % (len(traces), WINDOW_START, WINDOW_END))

    # Longest contiguous freeze: gap_ms grows monotonically while blocked.
    worst = max(traces, key=lambda t: t[1]) if traces else None
    if worst:
        print("   worst single sample: %s gap=%.0f ms" % (worst[0], worst[1]))

    innermost = collections.Counter()
    weighted = collections.Counter()
    for _ts, gap, frames in traces:
        if not frames:
            continue
        path, _lineno, func = frames[-1]
        key = "%s :: %s" % (short(path), func)
        innermost[key] += 1
        weighted[key] += gap

    print()
    print("== innermost frame (what was actually executing) ==")
    print("   %5s %10s  %s" % ("n", "sum_gap_ms", "frame"))
    for key, count in innermost.most_common(25):
        print("   %5d %10.0f  %s" % (count, weighted[key], key))

    print()
    print("== deepest 3 frames of the 12 longest stalls ==")
    for ts, gap, frames in sorted(traces, key=lambda t: -t[1])[:12]:
        print("   %s  gap=%.0f ms" % (ts, gap))
        for path, lineno, func in frames[-3:]:
            print("        %s:%s in %s" % (short(path), lineno, func))

    print()
    print("== app-code frames only (ignore qasync/main.py/importlib) ==")
    app_frames = collections.Counter()
    for _ts, gap, frames in traces:
        for path, lineno, func in frames:
            s = short(path)
            if s.startswith((".venv/", "<")) or s in ("main.py",):
                continue
            app_frames["%s:%s in %s" % (s, lineno, func)] += 1
    for key, count in app_frames.most_common(30):
        print("   %5d  %s" % (count, key))


if __name__ == "__main__":
    main()
