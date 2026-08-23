"""One-off: MPR open/close timeline + cache-release audit (patient 54921).

Two floor questions:
  1. What did MPR cost on 54921?
  2. MPR was opened on several different series - did the cache actually free?

IMPORTANT LESSON BAKED IN: the MPR *timings* are in `viewer_diagnostics.log*`
but the *close* path (`toolbar_manager._restore_selected_viewer`) logs to
`app.log*`. Reading only the viewer log makes every activation look leaked.
This reads BOTH, or the answer is wrong in the alarming direction.

Open  = "STANDARD MPR VIEWER INITIALIZATION STARTED"   (viewer_diagnostics)
Freed = "mpr_widget.cleanup() completed"                (app.log)

Run:  .venv\\Scripts\\python.exe tools\\analysis\\oneoff\\mpr_54921_timeline_2026_08_19.py
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LOGS = REPO / "user_data" / "logs"
OUT = Path(__file__).with_name("_mpr_54921_timeline.txt")
LINES: list[str] = []

SESSION_FROM = "2026-08-19 17:40:00"
SESSION_TO = "2026-08-19 18:10:00"

FILES = ["viewer_diagnostics.log.3", "viewer_diagnostics.log.2",
         "viewer_diagnostics.log.1", "viewer_diagnostics.log",
         "app.log.3", "app.log.2", "app.log.1", "app.log"]


def say(msg=""):
    LINES.append(str(msg))
    OUT.write_text("\n".join(LINES), encoding="utf-8")
    try:
        sys.__stdout__.write(str(msg) + "\n")
        sys.__stdout__.flush()
    except Exception:
        pass


TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)")
PID = re.compile(r"pid=(\d+)")


def load():
    out = []
    for name in FILES:
        p = LOGS / name
        if not p.is_file():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8",
                                             errors="replace").splitlines()):
            out.append((name, i + 1, line))
    return out


def when(line):
    m = TS.match(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1)[:26], "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None


def pid_of(line):
    m = PID.search(line)
    return m.group(1) if m else "?"


ALL = load()


def main() -> int:
    say("AI-PACS — MPR review for patient 54921 + cache-release audit")
    say(f"read {len(ALL)} lines from {len([f for f in FILES if (LOGS/f).is_file()])} "
        f"log files (viewer_diagnostics* AND app.log* — the close path only "
        f"logs to app.log)")

    # ── whole-log open/close ledger, per process ───────────────────────
    say("\n" + "=" * 78)
    say("A. OPEN / FREED LEDGER ACROSS EVERY LOGGED PROCESS")
    say("=" * 78)
    ledger = defaultdict(lambda: {"open": [], "freed": []})
    for f, n, l in ALL:
        t = when(l)
        if t is None:
            continue
        if "STANDARD MPR VIEWER INITIALIZATION STARTED" in l:
            ledger[pid_of(l)]["open"].append(t)
        elif "mpr_widget.cleanup() completed" in l:
            ledger[pid_of(l)]["freed"].append(t)

    say(f"   {'pid':>10}  {'opened':>7} {'freed':>7} {'still open':>11}   window")
    for pid, d in sorted(ledger.items(), key=lambda kv: -len(kv[1]['open'])):
        o, fr = len(d["open"]), len(d["freed"])
        times = sorted(d["open"] + d["freed"])
        span = (f"{times[0].strftime('%m-%d %H:%M')} .. "
                f"{times[-1].strftime('%m-%d %H:%M')}") if times else ""
        say(f"   {pid:>10}  {o:>7} {fr:>7} {o - fr:>11}   {span}")

    say("\n   NOTE: 'still open' counts the MPR viewer the user simply left")
    say("   open — that is not a leak. It only becomes one if it stays")
    say("   unfreed after the viewport is closed or replaced.")

    # ── the 54921 session ──────────────────────────────────────────────
    sess = [(f, n, l) for f, n, l in ALL if SESSION_FROM <= l[:19] <= SESSION_TO]
    say("\n" + "=" * 78)
    say(f"B. THE 54921 SESSION  ({SESSION_FROM[11:16]}–{SESSION_TO[11:16]}, "
        f"{len(sess)} lines)")
    say("=" * 78)

    events = []
    for f, n, l in sess:
        t = when(l)
        if t is None:
            continue
        if "toggle_zeta_mpr called" in l:
            events.append((t, "CLICK", "MPR button pressed"))
        elif "[MPR OPEN] Opening Zeta MPR" in l:
            events.append((t, "OPEN", "toggle ON"))
        elif "[MPR CLOSE] Closing Zeta MPR" in l:
            events.append((t, "CLOSE", "toggle OFF"))
        elif "mpr_widget.cleanup() completed" in l:
            events.append((t, "FREED", "cleanup() completed"))
        elif "vtk_image_data dimensions:" in l:
            m = re.search(r"dimensions: (\(.*?\))", l)
            events.append((t, "VOLUME", m.group(1) if m else "?"))
        elif "[MPR-OPEN-KPI]" in l:
            m = re.search(r"standard_mpr_construct_ms=([\d.]+) slices=(\d+)", l)
            if m:
                events.append((t, "KPI",
                               f"construct {float(m.group(1)):,.0f} ms, "
                               f"{m.group(2)} slices"))
        elif "Active series_number from viewer:" in l:
            m = re.search(r"viewer: (\S+)", l)
            events.append((t, "SERIES", f"series {m.group(1)}" if m else "?"))

    events.sort()
    t0 = events[0][0] if events else None
    for t, kind, detail in events:
        off = (t - t0).total_seconds() if t0 else 0
        say(f"   +{off:6.0f}s  {t.strftime('%H:%M:%S')}  {kind:<7} {detail}")

    opens = sum(1 for e in events if e[1] == "OPEN")
    closes = sum(1 for e in events if e[1] == "CLOSE")
    freed = sum(1 for e in events if e[1] == "FREED")

    say("")
    say("=" * 78)
    say("C. DID THE CACHE FREE?")
    say("=" * 78)
    say(f"   MPR opened                 : {opens}")
    say(f"   MPR closed (toggle OFF)    : {closes}")
    say(f"   cleanup() completed        : {freed}")
    say("")
    if closes and freed == closes:
        say(f"   -> every one of the {closes} closes ran the full teardown to")
        say(f"      completion. {opens - freed} viewer(s) left open by the user at")
        say("      the end of the session, which is expected, not a leak.")
    else:
        say(f"   -> {closes - freed} close(s) did NOT complete teardown.")

    # ── per-activation cost from MPR-STEP ──────────────────────────────
    say("")
    say("=" * 78)
    say("D. PER-ACTIVATION COST  ([MPR-STEP] begin/end pairs)")
    say("=" * 78)
    act = -1
    open_ts, pend = {}, {}
    dur = defaultdict(lambda: defaultdict(float))
    steps = defaultdict(lambda: defaultdict(float))
    for f, n, l in sess:
        t = when(l)
        if t is None:
            continue
        if "STANDARD MPR VIEWER INITIALIZATION STARTED" in l:
            act += 1
            open_ts[act] = t
            pend.clear()
            continue
        m = re.search(r"\[MPR-STEP\] view=(\S+) step=(\S+) phase=(\S+)", l)
        if not m or act < 0:
            continue
        view, step, phase = m.groups()
        key = (view, step)
        if phase == "begin":
            pend[key] = t
        elif phase == "end" and key in pend:
            ms = (t - pend.pop(key)).total_seconds() * 1000.0
            dur[act][view] += ms
            steps[act][f"{view}.{step}"] += ms

    for a in sorted(dur):
        say(f"\n   Activation #{a + 1} @ {open_ts[a].strftime('%H:%M:%S')}"
            f"   instrumented total ~{sum(dur[a].values()):,.0f} ms")
        for view, ms in sorted(dur[a].items(), key=lambda kv: -kv[1]):
            say(f"      {view:<10} {ms:9,.1f} ms")
        top = sorted(steps[a].items(), key=lambda kv: -kv[1])[:4]
        say("      slowest: " + ", ".join(f"{k} {v:,.0f}ms" for k, v in top))

    # ── stalls ─────────────────────────────────────────────────────────
    say("")
    say("=" * 78)
    say("E. MAIN-THREAD STALLS IN THE SESSION")
    say("=" * 78)
    st = []
    for f, n, l in sess:
        m = re.search(r"MAIN_THREAD_STALL.*?gap_ms=([\d.]+)", l)
        t = when(l)
        if m and t:
            st.append((float(m.group(1)), t))
    st.sort(reverse=True)
    say(f"   {len(st)} sample(s); largest 10:")
    for gap, t in st[:10]:
        say(f"      {gap:8.1f} ms at {t.strftime('%H:%M:%S')}")
    if st:
        say(f"   worst single stall: {st[0][0]:,.0f} ms")

    say("\nDONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
