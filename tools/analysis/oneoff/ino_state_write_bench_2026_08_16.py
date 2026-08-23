"""What one ino_assignment refresh costs the GUI thread — before vs after.

Background: `_save()` rewrites the WHOLE snapshot while holding `_LOCK`, and
`get_state()` — called per patient row from the GUI thread — takes the same
lock. Before 2026-08-16 the refresh called `set_state` per reception, so a
batch of N rows meant N full rewrites, each blocking the GUI.

Run with no args for the write-cost table; the batch simulation always runs.
Read-only w.r.t. the real snapshot: benchmarks into a scratch dir on the same
volume, never touches server_state.json.
"""
from __future__ import annotations

import json
import os
import shutil
import statistics
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REAL = ROOT / "user_data" / "ino_assignment" / "server_state.json"
SCRATCH = ROOT / "user_data" / "_bench_ino_tmp"

#: rows in the batch that produced the observed 10.79 s stall (10793 / 118)
OBSERVED_BATCH = 91


def save_like_the_app(p: Path, data: dict, *, fsync: bool) -> float:
    """Byte-for-byte the shape of _save(): dump -> flush -> [fsync] -> replace."""
    tmp = "%s.%d.%d.part" % (p, os.getpid(), threading.get_ident())
    t0 = time.perf_counter()
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
        fh.flush()
        if fsync:
            os.fsync(fh.fileno())
    os.replace(tmp, p)
    return (time.perf_counter() - t0) * 1000.0


def main() -> None:
    if not REAL.exists():
        print("no snapshot at", REAL)
        return
    raw = REAL.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    print(f"snapshot: {len(raw):,} bytes, {len(data):,} receptions\n")

    SCRATCH.mkdir(parents=True, exist_ok=True)
    target = SCRATCH / "server_state.json"
    per_write = {}
    try:
        for label, fsync in (("with fsync (old)", True), ("without fsync (new)", False)):
            s = sorted(save_like_the_app(target, data, fsync=fsync) for _ in range(12))
            per_write[fsync] = statistics.median(s)
            print(f"one write, {label:<22} n=12  min={s[0]:7.1f}  "
                  f"median={statistics.median(s):7.1f}  p90={s[int(len(s) * 0.9)]:7.1f}  "
                  f"max={s[-1]:7.1f}  ms")

        t0 = time.perf_counter()
        for _ in range(12):
            json.dumps(data, ensure_ascii=False)
        print(f"\njson.dumps only (no disk):        {(time.perf_counter() - t0) * 1000 / 12:7.1f} ms")
        t0 = time.perf_counter()
        for _ in range(200):
            os.stat(target)
        print(f"os.stat (get_state fast path):    "
              f"{(time.perf_counter() - t0) * 1000 / 200:7.3f} ms")

        # ── the thing that actually matters: GUI-blocking time per refresh ──
        old = OBSERVED_BATCH * per_write[True]
        new = per_write[False]
        print(f"\n--- one {OBSERVED_BATCH}-reception refresh, lock-held time ---")
        print(f"  BEFORE  {OBSERVED_BATCH} writes x {per_write[True]:.0f} ms = {old:9.0f} ms")
        print(f"  AFTER    1 write  x {per_write[False]:.0f} ms = {new:9.0f} ms")
        print(f"  improvement: {old / new:.0f}x   ({old / 1000:.1f} s -> {new / 1000:.3f} s)")

        full = len(data)
        print(f"\n--- worst case, a full {full}-reception refresh ---")
        print(f"  BEFORE  {full * per_write[True] / 1000:8.1f} s of lock-held time")
        print(f"  AFTER   {per_write[False] / 1000:8.3f} s")
        print("  (the old cost grew with the snapshot: O(all receptions) per row)")
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)


if __name__ == "__main__":
    main()
