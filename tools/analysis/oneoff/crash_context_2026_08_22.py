"""One-off: what was the app doing in the minutes before the 14:42:42 crash?

Prints the RSS trend, the process-id timeline, and the last non-routine app.log
lines before the fault, plus what happened after (restart?).  Read-only.
"""
import os
import re

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
LOGS = os.path.join(ROOT, "user_data", "logs")
CRASH = "2026-08-22 14:42:42"

TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
PID = re.compile(r"pid=(\d+)")
RSS = re.compile(r"rss=([\d.]+)MB")
CPU = re.compile(r"cpu=([\d.]+)%")


def read(name):
    path = os.path.join(LOGS, name)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read().splitlines()


def main():
    lines = read("app.log.1") + read("app.log")
    print("app.log(.1) lines: %d" % len(lines))

    # ── process timeline: first and last timestamp per pid ────────────────
    seen = {}
    for line in lines:
        mt, mp = TS.match(line), PID.search(line)
        if not (mt and mp):
            continue
        pid, stamp = mp.group(1), mt.group(1)
        if pid not in seen:
            seen[pid] = [stamp, stamp, 0]
        seen[pid][1] = stamp
        seen[pid][2] += 1
    print()
    print("== process timeline (pid: first .. last, lines) ==")
    for pid, (first, last, n) in sorted(seen.items(), key=lambda kv: kv[1][0]):
        print("   pid=%-8s %s .. %s   (%d lines)" % (pid, first, last, n))

    # ── RSS trend in the 15 minutes before the crash ─────────────────────
    print()
    print("== rss / cpu in the 20 min before %s ==" % CRASH)
    start = "2026-08-22 14:22"
    samples = []
    for line in lines:
        m = TS.match(line)
        if not m or not (start <= m.group(1) <= CRASH):
            continue
        r, c = RSS.search(line), CPU.search(line)
        if r:
            samples.append((m.group(1), float(r.group(1)), float(c.group(1)) if c else -1.0))
    if samples:
        print("   samples=%d  rss first=%.0f MB  last=%.0f MB  max=%.0f MB"
              % (len(samples), samples[0][1], samples[-1][1],
                 max(s[1] for s in samples)))
        step = max(1, len(samples) // 18)
        for stamp, rss, cpu in samples[::step]:
            print("      %s  rss=%8.1f MB  cpu=%5.1f%%" % (stamp, rss, cpu))
        print("      %s  rss=%8.1f MB  cpu=%5.1f%%  <- last before fault"
              % samples[-1])
    else:
        print("   (no resource-summary samples in the window)")

    # ── last interesting lines before the crash, and first after ──────────
    routine = ("resource-summary", "[MAIN_THREAD_STALL]", "heartbeat")
    before, after = [], []
    for line in lines:
        m = TS.match(line)
        if not m:
            continue
        stamp = m.group(1)
        if any(tok in line for tok in routine):
            continue
        if "2026-08-22 14:38" <= stamp <= CRASH:
            before.append(line)
        elif CRASH < stamp <= "2026-08-22 14:50":
            after.append(line)

    print()
    print("== last 25 non-routine lines before the fault ==")
    for line in before[-25:]:
        print("   " + line[:250])

    print()
    print("== first 15 lines after the fault ==")
    for line in after[:15]:
        print("   " + line[:250])


if __name__ == "__main__":
    main()
