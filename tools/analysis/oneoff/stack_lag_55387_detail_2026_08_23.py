"""55387 stacking lag — what the FAST stack path actually did (2026-08-23).

Follow-up to stack_lag_55387_2026_08_23.py, which bounded the window to
pid 90364, 15:11:09 -> 15:29:35, and surfaced two things worth chasing:

  * 4 930 `[FAST_FG_DISK]` lines in 18 minutes — foreground disk on the
    stack path;
  * 14 of 19 sampled stall stacks bottom out in `run_forever` with NOTHING
    below it, i.e. the main thread was NOT running our Python. That is the
    signature of WAITING, not computing.

This pass reads the stack path line by line so the two can be told apart.

Usage:  python tools/analysis/oneoff/stack_lag_55387_detail_2026_08_23.py [pid]
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
PID = sys.argv[1] if len(sys.argv) > 1 else "55387"
# Window = the session's OWN first/last log line, resolved below.
# CORRECTION (owner clarified): 55387 is the PATIENT id — not a process id
# and not a study id. No process 55387 exists in these logs; the session
# that read patient 55387 is pid 90364. Pass the pid as argv[1].
# The FIRST cut of this analysis read 55387 as a study id and matched it
# inside timestamp microseconds (14:47:23.155387), widening an 18-minute
# window to 18 days / 429,443 lines. Match digits with (?<!\d)N(?!\d)
# after stripping the timestamp, never a bare substring test.
LO, HI = "0000", "9999"

TS = re.compile(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)")
PIDRE = re.compile(r"\bpid=(\d+)")
KV = re.compile(r"(\w+)=([-\w./\\:]+)")


def ordered(stem: str):
    out = []
    for s in ("3", "2", "1"):
        p = LOGS / f"{stem}.{s}"
        if p.exists():
            out.append(p)
    b = LOGS / stem
    if b.exists():
        out.append(b)
    return out


def lines_in_window():
    for stem in ("app.log", "viewer_diagnostics.log"):
        for p in ordered(stem):
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    m = TS.search(line)
                    if not m:
                        continue
                    t = m.group(1).replace("T", " ").replace(",", ".")
                    if not (LO <= t[:19] <= HI):
                        continue
                    pm = PIDRE.search(line)
                    if pm and pm.group(1) != PID:
                        continue
                    yield t, line.rstrip()


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def stats(vals):
    if not vals:
        return "n=0"
    s = sorted(vals)
    return (f"n={len(s):<6} median={s[len(s)//2]:>9.1f}  "
            f"p90={s[int(len(s)*0.9)]:>9.1f}  max={s[-1]:>9.1f}")


def resolve_window() -> tuple[str, str, int]:
    """First and last log line written BY THIS PID."""
    first = last = None
    n = 0
    for stem in ("app.log", "viewer_diagnostics.log", "download_diagnostics.log"):
        for p in ordered(stem):
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    pm = PIDRE.search(line)
                    if not pm or pm.group(1) != PID:
                        continue
                    m = TS.search(line)
                    if not m:
                        continue
                    t = m.group(1).replace("T", " ").replace(",", ".")
                    n += 1
                    if first is None or t < first:
                        first = t
                    if last is None or t > last:
                        last = t
    return first, last, n


def main() -> int:
    global LO, HI
    first, last, n_lines = resolve_window()
    if not first:
        print(f"no log line was written by pid={PID}.")
        print("Sessions present in these logs:")
        seen = Counter()
        for stem in ("app.log", "viewer_diagnostics.log"):
            for p in ordered(stem):
                with p.open("r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        pm = PIDRE.search(line)
                        if pm:
                            seen[pm.group(1)] += 1
        for pid_, c in seen.most_common(20):
            print(f"   pid={pid_:<10} {c} lines")
        return 1
    LO, HI = first[:19], last[:19]
    print(f"pid={PID}: {n_lines} log lines, {first} -> {last}")

    fg_keys = defaultdict(list)
    fg_samples = []
    scroll_keys = defaultdict(list)
    drag_keys = defaultdict(list)
    stall_times = []
    fg_times = []
    tag_examples = {}
    zeta = Counter()

    for t, line in lines_in_window():
        if "[FAST_FG_DISK]" in line:
            fg_times.append(t)
            tag_examples.setdefault("FAST_FG_DISK", line)
            for k, v in KV.findall(line):
                f = num(v)
                if f is not None and k not in ("pid", "tid"):
                    fg_keys[k].append(f)
            if len(fg_samples) < 4:
                fg_samples.append(line)
        elif "[B3.8_SCROLL]" in line:
            tag_examples.setdefault("B3.8_SCROLL", line)
            for k, v in KV.findall(line):
                f = num(v)
                if f is not None and k not in ("pid", "tid"):
                    scroll_keys[k].append(f)
        elif "[FAST_DRAG_KPI]" in line:
            tag_examples.setdefault("FAST_DRAG_KPI", line)
            for k, v in KV.findall(line):
                f = num(v)
                if f is not None and k not in ("pid", "tid"):
                    drag_keys[k].append(f)
        elif "[MAIN_THREAD_STALL]" in line and "TRACE" not in line:
            stall_times.append(t)
        if "ZetaBoost" in line or "[ZETA_BOOST]" in line:
            for word in ("HIT", "MISS", "hit", "miss", "INACTIVE", "ACTIVE"):
                if word in line:
                    zeta[word.upper()] += 1
                    break

    print(f"pid={PID}   window {LO} -> {HI}\n")

    print("=== sample lines ===")
    for k, v in tag_examples.items():
        print(f"\n[{k}]\n   {v[:260]}")

    print("\n\n=== [FAST_FG_DISK] — foreground disk on the stack path ===")
    print(f"   occurrences: {len(fg_times)}")
    if fg_times:
        span = (len(fg_times))
        print(f"   that is ~{span/18.0:.0f} per minute over the 18-minute window")
    for k, v in sorted(fg_keys.items(), key=lambda kv: -max(kv[1]))[:12]:
        print(f"   {k:<26} {stats(v)}")

    print("\n=== [B3.8_SCROLL] ===")
    for k, v in sorted(scroll_keys.items(), key=lambda kv: -max(kv[1]))[:12]:
        print(f"   {k:<26} {stats(v)}")

    print("\n=== [FAST_DRAG_KPI] ===")
    for k, v in sorted(drag_keys.items(), key=lambda kv: -max(kv[1]))[:12]:
        print(f"   {k:<26} {stats(v)}")

    if zeta:
        print(f"\n=== ZetaBoost cache mentions === {dict(zeta)}")

    # ---- do the stalls coincide with foreground disk? ----------------------
    print("\n=== do the stalls land ON the disk reads? ===")
    fg_secs = Counter(t[:19] for t in fg_times)
    st_secs = Counter(t[:19] for t in stall_times)
    both = sorted(set(fg_secs) & set(st_secs))
    print(f"   seconds with foreground disk : {len(fg_secs)}")
    print(f"   seconds with a GUI stall     : {len(st_secs)}")
    print(f"   seconds with BOTH            : {len(both)}")
    if st_secs:
        pct = 100.0 * len(both) / len(st_secs)
        print(f"   -> {pct:.0f}% of stall-seconds also had a foreground disk read")
    print("\n   busiest seconds (disk reads / stalls):")
    for s, n in fg_secs.most_common(10):
        print(f"     {s}   fg_disk={n:<4} stalls={st_secs.get(s, 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
