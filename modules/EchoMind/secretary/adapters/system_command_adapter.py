"""SystemAdapter — process/resource probes for stability KPIs.

Wraps ``psutil`` so the CommandBus can emit ``proc.*``, ``crash.*``, and
``recovery.*`` KPIs without each test rewriting the probe code.

Lowest-risk adapter to land first: it touches no GUI code, no Qt, no
clinical workflow.

Actions exposed
---------------
``snapshot_resources``
    Returns RSS (MB), CPU% sample, thread count, open-fd count, child-
    process count for the current process.

``count_aipacs_processes``
    Returns ``{python_exe: N, aipacs_exe: M, total: N+M}``. Tests use
    this after close to assert no zombies.

``count_native_faults_since``
    Reads ``user_data/logs/native_fault.log`` and counts ``Windows
    fatal exception`` entries since the timestamp in ``plan.entities``
    (or since file start if absent). Optional filter on a hex code
    (e.g. ``0x8001010d``).

``probe_idle_cpu``
    Samples CPU% over ``plan.entities.seconds`` (default 5). Returns
    the median sample.

See ``docs/plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md`` §7.
"""
from __future__ import annotations

import logging
import os
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..command_envelope import CommandPlan, CommandResult

logger = logging.getLogger(__name__)

try:
    import psutil  # type: ignore
except ImportError:
    psutil = None  # type: ignore


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_NATIVE_FAULT_LOG = _PROJECT_ROOT / "user_data" / "logs" / "native_fault.log"


class SystemCommandAdapter:
    """Stability KPI probes. Pure-Python, no GUI dependency."""

    SUPPORTED_ACTIONS: tuple[str, ...] = (
        "snapshot_resources",
        "count_aipacs_processes",
        "count_native_faults_since",
        "probe_idle_cpu",
    )

    # ── helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _no_psutil(action: str) -> CommandResult:
        return CommandResult(
            ok=False, action=action,
            message="psutil is not installed",
            error_code="DEP_MISSING",
        )

    @staticmethod
    def _self_proc() -> "psutil.Process | None":
        if psutil is None:
            return None
        try:
            return psutil.Process(os.getpid())
        except Exception:
            return None

    # ── action: snapshot_resources ───────────────────────────────────
    def snapshot_resources(self, plan: CommandPlan, state: dict) -> CommandResult:
        if psutil is None:
            return self._no_psutil("snapshot_resources")
        p = self._self_proc()
        if p is None:
            return CommandResult(
                ok=False, action="snapshot_resources",
                message="cannot read current process",
                error_code="PROC_UNREADABLE",
            )
        try:
            with p.oneshot():
                mem = p.memory_info()
                rss_mb = mem.rss / (1024 * 1024)
                cpu_pct = p.cpu_percent(interval=0.1)
                threads = p.num_threads()
                try:
                    children = len(p.children(recursive=False))
                except Exception:
                    children = -1
                try:
                    open_files = len(p.open_files())
                except Exception:
                    open_files = -1
            return CommandResult(
                ok=True, action="snapshot_resources",
                message=f"RSS={rss_mb:.0f} MB cpu={cpu_pct:.1f}% threads={threads}",
                data={
                    "rss_mb": rss_mb,
                    "cpu_pct": cpu_pct,
                    "threads": threads,
                    "child_count": children,
                    "open_files": open_files,
                    "pid": p.pid,
                    "ts": datetime.now().isoformat(),
                },
            )
        except Exception as exc:
            return CommandResult(
                ok=False, action="snapshot_resources",
                message=f"snapshot failed: {exc}",
                error_code="PROC_READ_ERROR",
            )

    # ── action: count_aipacs_processes ───────────────────────────────
    def count_aipacs_processes(self, plan: CommandPlan, state: dict) -> CommandResult:
        """Count python.exe / aipacs.exe / ai pacs viewer.exe instances."""
        if psutil is None:
            return self._no_psutil("count_aipacs_processes")
        names = {
            "python_exe": ("python.exe", "py.exe"),
            "aipacs_exe": ("aipacs.exe", "ai pacs viewer.exe"),
        }
        counts = {k: 0 for k in names}
        pids: dict[str, list[int]] = {k: [] for k in names}
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pname = (proc.info.get("name") or "").lower()
            except Exception:
                continue
            for bucket, candidates in names.items():
                if pname in candidates:
                    counts[bucket] += 1
                    pids[bucket].append(proc.info.get("pid"))
        total = sum(counts.values())
        return CommandResult(
            ok=True, action="count_aipacs_processes",
            message=f"python={counts['python_exe']} aipacs={counts['aipacs_exe']} total={total}",
            data={"counts": counts, "pids": pids, "total": total},
        )

    # ── action: count_native_faults_since ────────────────────────────
    def count_native_faults_since(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        since_iso = ent.get("since_iso")
        only_code = (ent.get("code") or "").lower().strip()

        if not _NATIVE_FAULT_LOG.exists():
            return CommandResult(
                ok=True, action="count_native_faults_since",
                message="native_fault.log not present",
                data={"total": 0, "code_filtered": 0, "file_exists": False},
            )
        try:
            text = _NATIVE_FAULT_LOG.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return CommandResult(
                ok=False, action="count_native_faults_since",
                message=f"read failed: {exc}",
                error_code="LOG_READ_FAILED",
            )

        total = 0
        code_filtered = 0
        for line in text.splitlines():
            if "Windows fatal exception" not in line:
                continue
            total += 1
            if only_code and only_code in line.lower():
                code_filtered += 1

        # If a 'since' is provided, we don't have per-line timestamps in
        # the native_fault.log format, so we fall back to file-mtime
        # gating: report 'mtime_before_since' so the caller can decide.
        mtime_before_since = False
        if since_iso:
            try:
                since_dt = datetime.fromisoformat(since_iso)
                mtime = datetime.fromtimestamp(_NATIVE_FAULT_LOG.stat().st_mtime)
                mtime_before_since = mtime < since_dt
            except Exception:
                pass

        return CommandResult(
            ok=True, action="count_native_faults_since",
            message=f"total={total} filtered={code_filtered}",
            data={
                "total": total,
                "code_filtered": code_filtered,
                "code_filter": only_code or None,
                "file_exists": True,
                "mtime_before_since": mtime_before_since,
            },
        )

    # ── action: probe_idle_cpu ───────────────────────────────────────
    def probe_idle_cpu(self, plan: CommandPlan, state: dict) -> CommandResult:
        if psutil is None:
            return self._no_psutil("probe_idle_cpu")
        ent = plan.entities or {}
        seconds = float(ent.get("seconds") or 5.0)
        interval = float(ent.get("interval") or 0.5)
        p = self._self_proc()
        if p is None:
            return CommandResult(
                ok=False, action="probe_idle_cpu",
                message="cannot read current process",
                error_code="PROC_UNREADABLE",
            )
        samples: list[float] = []
        start = time.monotonic()
        while time.monotonic() - start < seconds:
            try:
                samples.append(p.cpu_percent(interval=interval))
            except Exception:
                break
        if not samples:
            return CommandResult(
                ok=False, action="probe_idle_cpu",
                message="no samples collected",
                error_code="NO_SAMPLES",
            )
        median = statistics.median(samples)
        return CommandResult(
            ok=True, action="probe_idle_cpu",
            message=f"median={median:.2f}% over {len(samples)} samples",
            data={"median_pct": median, "samples": samples,
                  "max_pct": max(samples), "min_pct": min(samples),
                  "duration_s": time.monotonic() - start},
        )


__all__ = ["SystemCommandAdapter"]
