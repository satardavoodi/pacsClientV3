"""Detail of the 2026-08-18 11:23:55-11:24:10 MPR activation.

Prints: who the study belongs to, the per-step MPR-STEP timings, and every
stall/trace in the window with full stacks.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOGDIR = ROOT / "user_data" / "logs"
STUDY = sys.argv[1] if len(sys.argv) > 1 else "1.2.840.1.99.1.47.1.1786976120177.87313"
LO, HI = "2026-08-18 11:23:50", "2026-08-18 11:24:15"


def whose_study() -> None:
    print(f"=== who owns study {STUDY} ===")
    dbs = list(ROOT.glob("user_data/**/*.db")) + list(ROOT.glob("*.db"))
    for db in dbs:
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            names = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            for t in names:
                try:
                    cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})")]
                except sqlite3.Error:
                    continue
                uid_cols = [c for c in cols if "study" in c.lower() and "uid" in c.lower()]
                if not uid_cols:
                    continue
                for uc in uid_cols:
                    try:
                        rows = con.execute(
                            f"SELECT * FROM {t} WHERE {uc}=?", (STUDY,)).fetchall()
                    except sqlite3.Error:
                        continue
                    for r in rows:
                        pairs = {c: v for c, v in zip(cols, r)
                                 if v not in (None, "") and len(str(v)) < 90}
                        keep = {k: v for k, v in pairs.items() if re.search(
                            r"patient|accession|name|id|date|desc|modal", k, re.I)}
                        print(f"  [{db.name}:{t}] {keep}")
            con.close()
        except sqlite3.Error:
            continue


def msg(line: str) -> str:
    return line.rsplit("| ", 1)[-1].rstrip()


def mpr_steps() -> None:
    print("\n=== MPR-STEP timeline (begin/end pairs -> ms) ===")
    p = LOGDIR / "viewer_diagnostics.log"
    events = []
    with p.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not (LO <= line[:19] <= HI):
                continue
            if "[MPR-STEP]" not in line:
                continue
            m = re.search(r"view=(\S+) step=(\S+) phase=(\S+)", line)
            if m:
                events.append((line[11:23], m.group(1), m.group(2), m.group(3)))
    open_at = {}
    total = 0.0
    for ts, view, step, phase in events:
        key = (view, step)
        if phase == "begin":
            open_at[key] = ts
        else:
            t0 = open_at.pop(key, None)
            if t0:
                d = _ms(ts) - _ms(t0)
                total += d
                flag = "  <<<" if d >= 100 else ""
                print(f"  {t0} -> {ts}  {d:8.1f} ms  {view:<10} {step}{flag}")
            else:
                print(f"  {'':>12}    {ts}   (end without begin)  {view} {step}")
    print(f"  instrumented total: {total:.0f} ms   views seen: "
          f"{sorted({v for _, v, _, _ in events})}")


def _ms(ts: str) -> float:
    h, m, s = ts.split(":")
    return (int(h) * 3600 + int(m) * 60 + float(s)) * 1000.0


def stalls_and_traces() -> None:
    print("\n=== stalls + full traces in the window ===")
    for name in ("viewer_diagnostics.log",):
        p = LOGDIR / name
        with p.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not (LO <= line[:19] <= HI):
                    continue
                if "[MAIN_THREAD_STALL]" in line:
                    m = re.search(r"stall_duration_ms=([\d.]+)", line)
                    if m:
                        print(f"\n  STALL {line[11:23]}  {float(m.group(1)):.1f} ms")
                elif "[MAIN_THREAD_STALL_TRACE]" in line:
                    g = re.search(r"gap_ms=([\d.]+)", line)
                    stack = line.split("stack=", 1)[-1]
                    print(f"\n  TRACE {line[11:23]}  gap={float(g.group(1)):.1f} ms")
                    for fr in stack.split(">>"):
                        fr = fr.strip()
                        mm = re.search(r'File "([^"]+)", line (\d+), in (\S+)', fr)
                        if mm and "site-packages\\qasync" not in mm.group(1):
                            print(f"      {Path(mm.group(1)).name}:{mm.group(2)} {mm.group(3)}")


if __name__ == "__main__":
    whose_study()
    mpr_steps()
    stalls_and_traces()
