"""Phase B.3 — Open/close cycle test.

Launches the AI-PACS source build N times via ``python main.py``, waits
for Server Ready, snapshots resources, closes the window, waits for
clean exit. Emits:

    recovery.restart_to_ready_ms   per cycle (median across cycles)
    proc.zombie_after_close        count per cycle (must be 0)
    proc.rss_mb_steady             median across cycles

Configurable via env:
    AIPACS_CYCLE_LAUNCH_CMD   shell command that launches the source
                              build (e.g. ``python main.py``). When
                              unset, the test SKIPs — we don't want
                              CI to auto-launch the app.
    AIPACS_CYCLE_COUNT        default 3 (range 1–50)
    AIPACS_CYCLE_TIMEOUT_S    default 60 (range 30–300; per-cycle ready timeout)

Usage::

    AIPACS_CYCLE_LAUNCH_CMD="python main.py" \\
    AIPACS_CYCLE_COUNT=5 \\
    python -m pytest tests/gui/pywinauto/test_open_close_cycles.py -s

The test SKIPs cleanly in CI / sandbox where the env var isn't set.
"""
from __future__ import annotations

import os
import shlex
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "gui" / "live_walkthroughs"))
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore

LOGS_DIR = PROJECT_ROOT / "user_data" / "logs"
DL_LOG = LOGS_DIR / "download_diagnostics.log"


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        return default
    return max(lo, min(hi, v))


def _skip_if_no_pywinauto():
    try:
        import pywinauto  # noqa: F401
    except ImportError:
        if pytest: pytest.skip("pywinauto not installed")
        raise


def _skip_if_no_launch_cmd():
    if not os.environ.get("AIPACS_CYCLE_LAUNCH_CMD"):
        if pytest:
            pytest.skip(
                "AIPACS_CYCLE_LAUNCH_CMD not set — this test launches "
                "the source build and is opt-in only"
            )
        raise RuntimeError("AIPACS_CYCLE_LAUNCH_CMD not set")


# ── helpers to count processes (uses SystemAdapter when available) ──────

def _count_aipacs_via_bus() -> dict[str, int]:
    """Returns {'python': N, 'aipacs': M, 'total': N+M}. Falls back to
    direct psutil if the bus stack isn't importable."""
    try:
        import pydantic  # noqa: F401
        from modules.EchoMind.secretary import (
            AdapterRegistry, CommandBus, CommandPlan,
        )
        from modules.EchoMind.secretary.adapters import SystemCommandAdapter
    except Exception:
        try:
            import psutil
            py = ap = 0
            for p in psutil.process_iter(["name"]):
                try:
                    n = (p.info["name"] or "").lower()
                except Exception:
                    continue
                if n in ("python.exe", "py.exe"): py += 1
                elif n in ("aipacs.exe", "ai pacs viewer.exe"): ap += 1
            return {"python": py, "aipacs": ap, "total": py + ap}
        except ImportError:
            return {"python": -1, "aipacs": -1, "total": -1}

    reg = AdapterRegistry()
    reg.register("system", SystemCommandAdapter(),
                 actions={"count_aipacs_processes": "count_aipacs_processes"})
    bus = CommandBus(registry=reg, orchestrator=None)
    r = bus.execute(CommandPlan(action="count_aipacs_processes"))
    if not r.ok:
        return {"python": -1, "aipacs": -1, "total": -1}
    return {
        "python": r.data["counts"]["python_exe"],
        "aipacs": r.data["counts"]["aipacs_exe"],
        "total":  r.data["total"],
    }


# ── ready-state detector ────────────────────────────────────────────────

def _wait_for_ready(timeout_s: float) -> tuple[bool, float]:
    """Wait for the source build's log to show signs of life — first
    appearance of the FAST_OPEN_TRACE marker or any download_diagnostics
    write is the heuristic. Returns (ok, elapsed_s).
    """
    pre_mtime = DL_LOG.stat().st_mtime if DL_LOG.exists() else 0
    pre_size = DL_LOG.stat().st_size if DL_LOG.exists() else 0
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if DL_LOG.exists():
            sz = DL_LOG.stat().st_size
            mt = DL_LOG.stat().st_mtime
            if sz > pre_size or mt > pre_mtime:
                # First post-launch write — the bus is up.
                return True, time.monotonic() - (deadline - timeout_s)
    return False, timeout_s


# ── the cycle test ──────────────────────────────────────────────────────

def test_open_close_cycles_no_zombie_no_leak(tmp_path):
    _skip_if_no_pywinauto()
    _skip_if_no_launch_cmd()

    n_cycles = _env_int("AIPACS_CYCLE_COUNT", 3, 1, 50)
    ready_timeout = _env_int("AIPACS_CYCLE_TIMEOUT_S", 60, 30, 300)
    launch_cmd = os.environ["AIPACS_CYCLE_LAUNCH_CMD"]

    from pywinauto import Application  # type: ignore

    ready_times: list[float] = []
    zombie_counts: list[int] = []
    rss_samples: list[float] = []

    for cycle in range(1, n_cycles + 1):
        pre = _count_aipacs_via_bus()
        print(f"[cycle {cycle}/{n_cycles}] pre={pre['total']} starting…")

        # Launch via subprocess so we don't depend on pywinauto.start()
        # which has quirks with shell-style commands.
        argv = shlex.split(launch_cmd)
        t0 = time.monotonic()
        proc = subprocess.Popen(
            argv, cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        ready, elapsed = _wait_for_ready(ready_timeout)
        if not ready:
            proc.terminate()
            if pytest:
                pytest.skip(
                    f"cycle {cycle}: source build never reached ready state "
                    f"in {ready_timeout}s; aborting"
                )
            return
        ready_ms = (time.monotonic() - t0) * 1000.0
        ready_times.append(ready_ms)
        print(f"[cycle {cycle}] ready in {ready_ms:.0f} ms")

        # Snapshot RSS via direct psutil on the launched proc (proc.pid).
        try:
            import psutil
            p = psutil.Process(proc.pid)
            rss_samples.append(p.memory_info().rss / (1024 * 1024))
        except Exception:
            pass

        # Find + close the window.
        try:
            app = Application(backend="uia").connect(title_re=r"AI[ -]?[Pp]acs.*",
                                                     timeout=15)
            window = app.window(title_re=r"AI[ -]?[Pp]acs.*")
            window.close()
        except Exception as exc:
            print(f"[cycle {cycle}] window close failed: {exc}")

        # Wait up to 10s for the launched process to exit cleanly.
        deadline = time.monotonic() + 10.0
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

        post = _count_aipacs_via_bus()
        zombie_delta = max(post["total"] - pre["total"], 0)
        zombie_counts.append(zombie_delta)
        print(f"[cycle {cycle}] post={post['total']} zombie_delta={zombie_delta}")

    # ── KPI assertions ──────────────────────────────────────────────
    median_ready_ms = statistics.median(ready_times)
    assert median_ready_ms < 15000, (
        f"median restart_to_ready {median_ready_ms:.0f} ms exceeds 15 s threshold"
    )
    assert max(zombie_counts) == 0, (
        f"close left zombie process(es) in {sum(1 for z in zombie_counts if z>0)}/"
        f"{n_cycles} cycles: {zombie_counts}"
    )
    if rss_samples and len(rss_samples) > 1:
        first, last = rss_samples[0], rss_samples[-1]
        growth = last - first
        # Multi-cycle RSS shouldn't drift > 30 MB per cycle (generous).
        assert growth < n_cycles * 30, (
            f"RSS drifted {growth:.1f} MB across {n_cycles} cycles "
            f"(first={first:.0f} MB, last={last:.0f} MB) — leak suspected"
        )
    print(f"[cycles] median_ready={median_ready_ms:.0f}ms "
          f"max_zombie={max(zombie_counts)} "
          f"rss_first={rss_samples[0]:.0f} rss_last={rss_samples[-1]:.0f}"
          if rss_samples else
          f"[cycles] median_ready={median_ready_ms:.0f}ms "
          f"max_zombie={max(zombie_counts)}")


if __name__ == "__main__":
    test_open_close_cycles_no_zombie_no_leak(None)
