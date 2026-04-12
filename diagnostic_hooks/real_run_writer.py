"""
diagnostic_hooks/real_run_writer.py
=====================================
Crash-safe event writer for the real-app (AIPACS_DIAG_MODE=1) path.

Unlike the synthetic harness which writes at scenario end, this writer
flushes incrementally:
 - events.jsonl : appended after every event (os.write, OS-atomic for small writes)
 - kpis_snapshot.json : written every 30 s (atomic tmp→rename)
 - ring_buffer.json : written every 60 s (last 200 events, atomic)
 - last_good_state.json : written every 60 s (atomic)

On SIGTERM/atexit the writer marks run_meta.json with ``process_died=true``
and ``atexit_ts`` so post-mortem analysis can detect abnormal exits.

Directory layout
----------------
    user_data/diagnostics/<YYYY-MM-DD_HHMMSS_<scenario>>/
        run_meta.json
        events.jsonl        ← incremental append
        kpis_snapshot.json  ← last 30s snapshot
        ring_buffer.json    ← last 200 events
        last_good_state.json
"""
from __future__ import annotations

import atexit
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from tests.diagnostics.event_log import EventLog, EventEntry
from tests.diagnostics.report_writer import ReportWriter, RunMeta
from tests.diagnostics.kpi_collector import KpiCollector


_FLUSH_INTERVAL_SEC = 30
_RING_INTERVAL_SEC = 60


class RealRunWriter:
    """Incremental writer for a live diagnostic run.

    Parameters
    ----------
    run_dir : Path
        Where to write artifacts.
    scenario_name : str
        Human-readable name (affects run_meta.json).
    modality : str
        "CT" or "MR" (from series metadata, may be updated via update_modality).
    slice_count : int
        Estimated total slices (updated when first series metadata is known).
    """

    def __init__(
        self,
        run_dir: Path,
        scenario_name: str = "real_run",
        modality: str = "CT",
        slice_count: int = 0,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self._log = EventLog(output_dir=self.run_dir)
        self._kpi = KpiCollector(log=self._log)

        self._meta = RunMeta(
            scenario_name=scenario_name,
            scenario_type="real_app",
            started_at=time.time(),
            modality=modality,
            slice_count=slice_count,
            run_count=1,
        )
        self._writer = ReportWriter(output_dir=self.run_dir)
        self._writer.write_run_meta(self._meta)

        self._lock = threading.Lock()
        self._closed = False

        # Periodic flush timers
        self._kpi_timer: Optional[threading.Timer] = None
        self._ring_timer: Optional[threading.Timer] = None
        self._start_timers()

        # Crash handler
        atexit.register(self._atexit_handler)
        try:
            signal.signal(signal.SIGTERM, self._sigterm_handler)
        except (OSError, ValueError):
            pass  # not the main thread

    # ── Public API ─────────────────────────────────────────────────────────

    @property
    def log(self) -> EventLog:
        return self._log

    @property
    def kpi(self) -> KpiCollector:
        return self._kpi

    def update_modality(self, modality: str, slice_count: int = 0) -> None:
        """Update modality/slice_count once a series is known."""
        with self._lock:
            self._meta.modality = modality
            if slice_count:
                self._meta.slice_count = slice_count

    def attach_controller(self, controller: Any) -> None:
        """Instrument a live ViewerController with KPI spy wrappers."""
        self._kpi.attach_controller(controller)

    def finalize(self) -> None:
        """Mark the run complete and write all remaining artifacts."""
        with self._lock:
            if self._closed:
                return
            self._closed = True

        self._stop_timers()

        from tests.diagnostics.failure_detector import detect_all, severity_order
        from tests.diagnostics.hypothesis_engine import HypothesisEngine
        from tests.diagnostics.state_machine import StateMachineReconstructor

        sm = StateMachineReconstructor()
        sm.feed(self._log.events())
        kpis = self._kpi.collect()
        findings = detect_all(
            events=self._log.events(),
            kpis=kpis,
            machines=sm.machines(),
            scenario_run_count=1,
        )
        findings.sort(key=severity_order)
        engine = HypothesisEngine(run_count=1, scenario_name=self._meta.scenario_name)
        hypotheses = engine.score_all(kpis, findings, events=self._log.events())

        self._writer.write_kpis(kpis)
        self._writer.write_findings(findings)
        self._writer.write_hypotheses(hypotheses)
        self._writer.write_state_machines(sm.summary())
        self._writer.write_full_summary(
            meta=self._meta,
            kpis=kpis,
            findings=findings,
            hypotheses=hypotheses,
        )
        self._log.flush_ring_buffer()
        self._writer.mark_ended(self._meta)
        self._kpi.detach()
        self._log.close()

    # ── Timer management ───────────────────────────────────────────────────

    def _start_timers(self) -> None:
        self._kpi_timer = threading.Timer(_FLUSH_INTERVAL_SEC, self._timer_kpi_flush)
        self._kpi_timer.daemon = True
        self._kpi_timer.start()

        self._ring_timer = threading.Timer(_RING_INTERVAL_SEC, self._timer_ring_flush)
        self._ring_timer.daemon = True
        self._ring_timer.start()

    def _stop_timers(self) -> None:
        if self._kpi_timer:
            self._kpi_timer.cancel()
        if self._ring_timer:
            self._ring_timer.cancel()

    def _timer_kpi_flush(self) -> None:
        if self._closed:
            return
        try:
            kpis = self._kpi.collect()
            self._writer.write_kpi_snapshot(kpis)
        except Exception:
            pass
        # Reschedule
        self._kpi_timer = threading.Timer(_FLUSH_INTERVAL_SEC, self._timer_kpi_flush)
        self._kpi_timer.daemon = True
        self._kpi_timer.start()

    def _timer_ring_flush(self) -> None:
        if self._closed:
            return
        try:
            self._log.flush_ring_buffer()
            self._log.flush_last_good_state()
        except Exception:
            pass
        # Reschedule
        self._ring_timer = threading.Timer(_RING_INTERVAL_SEC, self._timer_ring_flush)
        self._ring_timer.daemon = True
        self._ring_timer.start()

    # ── Crash handlers ─────────────────────────────────────────────────────

    def _atexit_handler(self) -> None:
        if not self._closed:
            self._meta.process_died = True
            try:
                self._writer.write_run_meta(self._meta)
            except Exception:
                pass

    def _sigterm_handler(self, signum, frame) -> None:
        self._atexit_handler()
        # Re-raise default SIGTERM behaviour
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTERM)
