"""Where was the main thread when it stalled? pid 90364, 2026-08-23.

Third pass on the owner's report "check the stacking in 55387; there are some
lag / check if it's because of pc resource or the app". 55387 is the PATIENT
id; the session that read it is pid 90364 (14:28:45 -> 15:39:45).

The first two passes established that the app's per-frame stacking work is
fast (frame_total_ms median 1.6 ms, disk_wait/decode/cache all ~0) while the
observed per-drag latency is not (ui_lag_max_ms median 300 ms). This script
answers the only question that separates "our code is slow" from "our thread
was not running": WHERE was the main thread when the stall probe sampled it?

Note the probe lives in viewer_diagnostics.log, NOT app.log -- looking only in
app.log returns 2 lines and the wrong conclusion.

Usage:  python tools/analysis/oneoff/stall_trace_frames_90364_2026_08_23.py [pid]
"""

from __future__ import annotations

import io
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[3]
LOGS = ROOT / "user_data" / "logs"
PID = sys.argv[1] if len(sys.argv) > 1 else "90364"

FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
GAP = re.compile(r"gap_ms=([\d.]+)")


def _logs(stem: str):
    for suffix in (".3", ".2", ".1", ""):
        p = LOGS / (stem + suffix)
        if p.exists():
            yield p


def main() -> int:
    gaps: list[float] = []
    plain = 0
    inner: Counter[str] = Counter()
    anyframe: Counter[str] = Counter()
    traced = 0

    for stem in ("viewer_diagnostics.log", "app.log"):
        for path in _logs(stem):
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if "MAIN_THREAD_STALL" not in line or f"pid={PID}" not in line:
                        continue
                    if "armed" in line:
                        continue
                    m = GAP.search(line)
                    if m:
                        gaps.append(float(m.group(1)))
                    if "MAIN_THREAD_STALL_TRACE" not in line:
                        plain += 1
                        continue
                    if "stack=" not in line:
                        continue
                    traced += 1
                    frames = FRAME.findall(line.split("stack=", 1)[1])
                    if not frames:
                        inner["<no frames>"] += 1
                        continue
                    last = frames[-1]
                    inner[f"{Path(last[0]).name}:{last[2]}"] += 1
                    for f in frames:
                        anyframe[f"{Path(f[0]).name}:{f[2]}"] += 1

    if not gaps and not traced:
        print(f"no stall records for pid={PID}")
        return 1

    gaps.sort()
    n = len(gaps)
    print(f"pid={PID}: {n} stall records ({plain} plain, {traced} traced)")
    print("  gap_ms  median=%.0f  p90=%.0f  max=%.0f" % (
        gaps[n // 2], gaps[int(n * 0.9)], gaps[-1]))

    print("\n-- innermost frame (where the main thread actually was) --")
    for k, v in inner.most_common(15):
        print("  %4d  %s" % (v, k))

    bottomed = inner.get("__init__.py:run_forever", 0)
    if traced:
        print(f"\n  {bottomed}/{traced} samples bottom out in run_forever with NOTHING")
        print("  below it -- the main thread was inside the Qt event loop, not")
        print("  executing our Python. That is WAITING, not computing.")

    print("\n-- any frame --")
    for k, v in anyframe.most_common(18):
        print("  %4d  %s" % (v, k))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
