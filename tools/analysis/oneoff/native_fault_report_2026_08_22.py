"""One-off: summarise user_data/logs/native_fault.log.

For every fault record: the timestamp, the fault kind, and the innermost
application frame of the faulting thread.  Read-only.
"""
import collections
import os
import re

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
LOG = os.path.join(ROOT, "user_data", "logs", "native_fault.log")

TS = re.compile(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")
FRAME = re.compile(r'File "([^"]+)", line (\d+) in (\S+)')


def short(path):
    p = path.replace(ROOT.lower(), "").replace(ROOT, "")
    return p.lstrip("\\/").replace("\\", "/")


def main():
    with open(LOG, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    print("native_fault.log: %d lines, %.1f KB" % (len(lines), os.path.getsize(LOG) / 1024))

    records = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "fatal exception" in line or "Fatal Python error" in line:
            # walk back for the nearest timestamp
            stamp = ""
            for back in range(i, max(-1, i - 12), -1):
                m = TS.search(lines[back])
                if m:
                    stamp = m.group(1)
                    break
            kind = line.strip()
            # walk forward to "Current thread" and take its app frames
            frames = []
            j = i
            seen_current = False
            while j < len(lines) and j < i + 400:
                if lines[j].startswith("Current thread"):
                    seen_current = True
                elif seen_current:
                    m = FRAME.search(lines[j])
                    if m:
                        frames.append((short(m.group(1)), m.group(2), m.group(3)))
                    elif lines[j].strip() == "" and frames:
                        break
                j += 1
            records.append((stamp, kind, frames))
            i = j
        else:
            i += 1

    print("fault records: %d" % len(records))
    print()

    by_site = collections.Counter()
    for stamp, kind, frames in records:
        app = [f for f in frames if not f[0].startswith((".venv/", "C:/", "<"))]
        site = "%s:%s in %s" % app[0] if app else "?"
        by_site[(kind[:60], site)] += 1

    print("== fault sites (kind + innermost app frame) ==")
    for (kind, site), count in by_site.most_common(20):
        print("   %4d  %-46s  %s" % (count, kind, site))

    print()
    print("== last 6 records ==")
    for stamp, kind, frames in records[-6:]:
        print("   %s  %s" % (stamp or "<no timestamp>", kind[:80]))
        for f in frames[:6]:
            print("        %s:%s in %s" % f)
        print()

    print("== first record ==")
    if records:
        stamp, kind, frames = records[0]
        print("   %s  %s" % (stamp or "<no timestamp>", kind[:80]))


if __name__ == "__main__":
    main()
