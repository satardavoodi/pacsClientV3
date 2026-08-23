"""Stack-scroll lag on 55387 — is it the machine or the app? (2026-08-23)

Owner: *"check the stacking in 55387; there are some lag. Check if it's because
of pc resource or the app."*

The discriminator is not "was it slow" — it is WHERE the GUI thread was while it
was slow:

* **App**  — the sampled stall stacks land inside our own frames (decode, disk,
  VTK, widget building). The work is ours and it is on the wrong thread.
* **Machine** — the app is doing little or nothing, its CPU share is low, memory
  is flat, and yet frames are late. Then something outside us is taking the
  core, the disk or the RAM.

Rotated logs are read OLDEST FIRST (.3, .2, .1, base): name order corrupts the
first/last timestamps of a session.

Usage:  python tools/analysis/oneoff/stack_lag_55387_2026_08_23.py [study]
"""

from __future__ import annotations

import io
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[3]
LOGS = ROOT / "user_data" / "logs"
STUDY = (sys.argv[1] if len(sys.argv) > 1 else "55387")

TS = re.compile(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)")
PID = re.compile(r"\bpid=(\d+)")
# The study id must be a WHOLE number, not a digit run inside a longer one.
# First cut of this script used `if STUDY in line` and matched the microseconds
# of timestamps like `14:47:23.155387` — which silently widened the window from
# one session to 18 days and 429 443 lines. Cheap mistake, expensive answer.
ID = None  # built in main() once STUDY is known
TAG = re.compile(r"\[([A-Z][A-Z0-9_\-.]{2,40})\]")
GAP = re.compile(r"gap_ms=([0-9.]+)")
DUR = re.compile(r"stall_duration_ms=([0-9.]+)")
RSS = re.compile(r"(?:rss_mb|memory_mb|rss)[=: ]+([0-9.]+)", re.I)
CPU = re.compile(r"cpu(?:_percent|_pct)?[=: ]+([0-9.]+)", re.I)
MS = re.compile(r"\b(\w+_ms)=([0-9.]+)")


def ordered(stem: str) -> list[Path]:
    out = []
    for suffix in ("3", "2", "1"):
        p = LOGS / f"{stem}.{suffix}"
        if p.exists():
            out.append(p)
    base = LOGS / stem
    if base.exists():
        out.append(base)
    return out


def files() -> list[Path]:
    out = []
    for stem in ("app.log", "viewer_diagnostics.log", "download_diagnostics.log"):
        out.extend(ordered(stem))
    return out


def ts_of(line: str) -> str | None:
    m = TS.search(line)
    return m.group(1).replace("T", " ").replace(",", ".") if m else None


def main() -> int:
    if not LOGS.exists():
        print(f"log folder not found: {LOGS}")
        return 2
    paths = files()
    print(f"study={STUDY}")
    print(f"reading {len(paths)} files: {[p.name for p in paths]}\n")

    # ---- pass 1: when was this study active? --------------------------------
    global ID
    ID = re.compile(r"(?<!\d)" + re.escape(STUDY) + r"(?!\d)")
    hits: list[tuple[str, str, str, str]] = []
    for p in paths:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                t = ts_of(line)
                if not t:
                    continue
                # Strip the timestamp before matching: its microseconds are
                # digits too, and that is exactly how the first version of this
                # script matched 18 days of unrelated logs.
                if ID.search(line.replace(t, "", 1)):
                    pm = PID.search(line)
                    hits.append((t, p.name, line.rstrip()[:200], pm.group(1) if pm else "?"))
    if not hits:
        print(f"no log line mentions {STUDY}.")
        print("Open the study and scroll, then re-run — or pass another id as argv[1].")
        return 1

    hits.sort(key=lambda r: r[0])
    print(f"{len(hits)} lines genuinely mention {STUDY}")

    by_pid = Counter(h[3] for h in hits)
    print(f"sessions that touched it: {dict(by_pid)}")

    # Analyse the MOST RECENT session only — that is the one the owner is
    # describing. Older sessions carry fixed bugs (e.g. the 183 s storage-clear
    # rmtree of 08-22) and would swamp the numbers.
    last_pid = hits[-1][3]
    same = [h for h in hits if h[3] == last_pid]
    t0, t1 = same[0][0], same[-1][0]
    print(f"\nanalysing pid={last_pid}: {len(same)} mentions, "
          f"{t0} -> {t1}\n")
    print("first / last mentions in that session:")
    for t, f, s, _p in same[:3] + same[-3:]:
        print(f"   {t}  {f:<26} {s[:140]}")

    lo, hi = t0[:19], t1[:19]
    SESSION_PID = last_pid

    # ---- pass 2: everything inside the window -------------------------------
    tags = Counter()
    stalls: list[tuple[str, float, str]] = []
    traces: list[tuple[str, float, str]] = []
    timings: dict[str, list[float]] = defaultdict(list)
    rss: list[tuple[str, float]] = []
    cpu: list[tuple[str, float]] = []
    total = 0

    for p in paths:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                t = ts_of(line)
                if not t or not (lo <= t[:19] <= hi):
                    continue
                pm = PID.search(line)
                if pm and pm.group(1) != SESSION_PID:
                    continue          # another process running at the same time
                total += 1
                for tg in TAG.findall(line):
                    tags[tg] += 1
                if "MAIN_THREAD_STALL_TRACE" in line:
                    g = GAP.search(line)
                    traces.append((t, float(g.group(1)) if g else 0.0, line.rstrip()))
                elif "MAIN_THREAD_STALL" in line:
                    d = DUR.search(line) or GAP.search(line)
                    stalls.append((t, float(d.group(1)) if d else 0.0, line.rstrip()[:160]))
                for name, val in MS.findall(line):
                    if name not in ("threshold_ms", "stall_start_ms"):
                        timings[name].append(float(val))
                m = RSS.search(line)
                if m:
                    rss.append((t, float(m.group(1))))
                m = CPU.search(line)
                if m:
                    cpu.append((t, float(m.group(1))))

    print(f"\n{total} log lines inside the window\n")

    print("--- what the app was doing (tag frequency) ---")
    for tg, n in tags.most_common(25):
        print(f"   {n:>6}  [{tg}]")

    # ---- stalls -------------------------------------------------------------
    print(f"\n--- GUI-thread stalls in the window: {len(stalls)} ---")
    if stalls:
        vals = sorted(s[1] for s in stalls)
        print(f"   median={vals[len(vals)//2]:.0f} ms   p90={vals[int(len(vals)*0.9)]:.0f} ms   max={vals[-1]:.0f} ms")
        print("   worst 8:")
        for t, d, s in sorted(stalls, key=lambda r: -r[1])[:8]:
            print(f"     {t}  {d:>8.0f} ms")

    # ---- where the GUI thread actually was ---------------------------------
    print(f"\n--- sampled stall stacks: {len(traces)} ---")
    if traces:
        innermost = Counter()
        ours = 0
        for _t, _g, line in traces:
            frames = re.findall(r'File "([^"]+)", line (\d+), in (\w+)', line)
            if not frames:
                continue
            f, ln, fn = frames[-1]
            short = Path(f).name
            innermost[f"{short}:{ln} {fn}"] += 1
            low = f.replace("\\", "/").lower()
            if ("/ai-pacs" in low or "pacsclient" in low or "/modules/" in low):
                ours += 1
        print(f"   frames inside OUR code: {ours} / {len(traces)}")
        print("   innermost frame, most common:")
        for k, n in innermost.most_common(12):
            print(f"     {n:>4}x  {k}")

    # ---- named timings ------------------------------------------------------
    interesting = {k: v for k, v in timings.items() if len(v) >= 3}
    if interesting:
        print("\n--- named *_ms timings in the window (n>=3) ---")
        rows = sorted(interesting.items(), key=lambda kv: -max(kv[1]))[:16]
        print(f"   {'metric':<34}{'n':>6}{'median':>10}{'p90':>10}{'max':>10}")
        for k, v in rows:
            s = sorted(v)
            print(f"   {k:<34}{len(s):>6}{s[len(s)//2]:>10.1f}"
                  f"{s[int(len(s)*0.9)]:>10.1f}{s[-1]:>10.1f}")

    # ---- the app's own view of machine load --------------------------------
    print("\n--- the app's own resource samples in the window ---")
    if rss:
        vals = [v for _t, v in rss]
        print(f"   RSS  n={len(vals)}  min={min(vals):.0f} MB  max={max(vals):.0f} MB  "
              f"growth={max(vals)-min(vals):+.0f} MB")
    else:
        print("   RSS: no samples")
    if cpu:
        vals = [v for _t, v in cpu]
        vals_s = sorted(vals)
        print(f"   CPU  n={len(vals)}  median={vals_s[len(vals_s)//2]:.1f}%  max={max(vals):.1f}%")
    else:
        print("   CPU: no samples")

    print("\n--- how to read this ---")
    print("   APP     : stall stacks land in our frames, and named timings show")
    print("             real per-frame work (decode/disk/VTK) on the GUI thread.")
    print("   MACHINE : few or no stalls attributable to our frames, app CPU low")
    print("             and RSS flat, yet the user still felt lag -> look outside")
    print("             the process (other load, disk contention, thermal).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
