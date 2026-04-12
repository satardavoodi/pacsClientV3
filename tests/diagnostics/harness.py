"""
tests/diagnostics/harness.py
==============================
DiagnosticHarness — orchestrates a single diagnostic scenario run.

Responsibilities
----------------
1. Create the run directory and initialise all framework components
   (EventLog, KpiCollector, ReportWriter, StateMachineReconstructor).
2. Inject signal events into a mock or real controller, calling
   QApplication.processEvents() after each one to drain the Qt event queue.
3. Collect KPIs, run all 20 failure detectors, score hypotheses.
4. Write all artifacts to the run directory.
5. Return a HarnessResult that test assertions can query.

Usage
-----
    from tests.diagnostics.harness import DiagnosticHarness

    with DiagnosticHarness(scenario_name="s03_large_ct", output_dir=run_dir) as h:
        ctrl = h.make_controller()
        h.emit_progress("1", 50, 400, times=8)
        h.emit_download_complete("1")
        result = h.finish()

    assert result.kpis["C01_progressive_start_calls"] >= 1
    assert not result.h1_confirmed  # or True — depends on measurements
"""
from __future__ import annotations

import sys
import time
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from tests.diagnostics.event_log import (
    EventLog,
    ET_SCENARIO_BEGIN,
    ET_SCENARIO_STEP,
    ET_SCENARIO_END,
    ET_SERIES_PROGRESS,
    ET_SERIES_DOWNLOAD_COMPLETE,
)
from tests.diagnostics.kpi_collector import KpiCollector
from tests.diagnostics.state_machine import StateMachineReconstructor
from tests.diagnostics.failure_detector import detect_all, FailureMatch, severity_order
from tests.diagnostics.hypothesis_engine import HypothesisEngine, HypothesisResult
from tests.diagnostics.report_writer import ReportWriter, RunMeta


def _noop(*args, **kwargs):
    return None


# ─── HarnessResult ───────────────────────────────────────────────────────────

class HarnessResult:
    """Returned by DiagnosticHarness.finish().  Provides convenient accessors."""

    def __init__(
        self,
        kpis: Dict[str, Any],
        findings: List[FailureMatch],
        hypotheses: List[HypothesisResult],
        run_dir: Path,
        scenario_name: str,
    ) -> None:
        self.kpis = kpis
        self.findings = findings
        self.hypotheses = hypotheses
        self.run_dir = run_dir
        self.scenario_name = scenario_name
        self._finding_codes = {f.code for f in findings}
        self._hyp_by_code = {h.code: h for h in hypotheses}

    # Quick accessors
    def has_finding(self, code: str) -> bool:
        return code in self._finding_codes

    def hypothesis(self, code: str) -> Optional[HypothesisResult]:
        return self._hyp_by_code.get(code)

    @property
    def h1_confirmed(self) -> bool:
        h = self._hyp_by_code.get("H1")
        return h is not None and h.verdict == "CONFIRMED"

    @property
    def h4_confirmed(self) -> bool:
        h = self._hyp_by_code.get("H4")
        return h is not None and h.verdict == "CONFIRMED"

    @property
    def patch_allowed_for(self) -> List[str]:
        return [h.code for h in self.hypotheses if h.patch_allowed]

    @property
    def critical_findings(self) -> List[FailureMatch]:
        return [f for f in self.findings if f.severity == "CRITICAL"]

    def __repr__(self) -> str:
        codes = ", ".join(sorted(self._finding_codes)) or "none"
        return (
            f"<HarnessResult scenario={self.scenario_name!r} "
            f"findings=[{codes}] "
            f"patch_allowed={self.patch_allowed_for}>"
        )


# ─── DiagnosticHarness ────────────────────────────────────────────────────────

class DiagnosticHarness:
    """Orchestrates a single diagnostic scenario run.

    Parameters
    ----------
    scenario_name : str
        Identifying name, e.g. "s03_large_ct".
    output_dir : Path | str | None
        Where to write artifacts.  If None, uses a tmp directory.
    modality : str
        "CT" or "MR" — stored in run_meta for H1 scoring.
    slice_count : int
        Total expected slices — stored in run_meta.
    run_count : int
        Repetition index for multi-run scenarios (H1/H4 minimum evidence).
    study_uid : str
        Optional real study UID for real-run mode correlation.
    process_events : bool
        If True, call QApplication.processEvents() after each signal injection.
        Requires a QApplication to be present (set QT_QPA_PLATFORM=offscreen).
    """

    def __init__(
        self,
        scenario_name: str,
        output_dir: Optional[Path | str] = None,
        modality: str = "CT",
        slice_count: int = 400,
        run_count: int = 1,
        study_uid: Optional[str] = None,
        process_events: bool = False,
    ) -> None:
        self.scenario_name = scenario_name
        self.modality = modality
        self.slice_count = slice_count
        self.run_count = run_count
        self.study_uid = study_uid
        self._process_events = process_events

        if output_dir is None:
            import tempfile
            output_dir = Path(tempfile.mkdtemp(prefix=f"diag_{scenario_name}_"))
        self.run_dir = Path(output_dir)

        self._log = EventLog(output_dir=self.run_dir)
        self._kpi = KpiCollector(log=self._log)
        self._sm = StateMachineReconstructor()
        self._writer = ReportWriter(output_dir=self.run_dir)
        self._engine = HypothesisEngine(
            run_count=run_count,
            scenario_name=scenario_name,
        )
        self._meta = RunMeta(
            scenario_name=scenario_name,
            scenario_type="synthetic",
            started_at=time.time(),
            modality=modality,
            slice_count=slice_count,
            run_count=run_count,
            study_uid=study_uid,
        )
        self._controller: Optional[object] = None
        self._finished = False

    # ── context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "DiagnosticHarness":
        self._writer.write_run_meta(self._meta)
        self._log.append(ET_SCENARIO_BEGIN,
                         scenario=self.scenario_name,
                         modality=self.modality,
                         slice_count=self.slice_count)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if not self._finished:
            if exc_type is not None:
                self._meta.process_died = True
            self.finish()

    # ── controller factory ────────────────────────────────────────────────────

    def make_controller(self) -> object:
        """Create and instrument a minimal mock ViewerController."""
        ctrl = self._build_mock_controller()
        self._kpi.attach_controller(ctrl)
        self._controller = ctrl
        return ctrl

    # ── signal injection ──────────────────────────────────────────────────────

    def emit_progress(
        self,
        series_number: str,
        downloaded: int,
        total: int,
        times: int = 1,
        interval_ms: int = 0,
    ) -> None:
        """Simulate DM progress signals.  Calls processEvents() after each emit."""
        for i in range(times):
            # linear ramp: downloaded grows from 0→total over `times` calls
            d = downloaded if times == 1 else int((i + 1) * downloaded / times)
            self._log.append(
                ET_SERIES_PROGRESS,
                series_number=series_number,
                downloaded=d,
                total=total,
            )
            if self._controller and hasattr(self._controller, "on_series_images_progress"):
                try:
                    self._controller.on_series_images_progress(series_number, d, total)
                except Exception:
                    pass
            self._drain_events()
            if interval_ms > 0:
                time.sleep(interval_ms / 1000)

    def emit_download_complete(self, series_number: str) -> None:
        """Emit a download-complete signal."""
        self._log.append(
            ET_SERIES_DOWNLOAD_COMPLETE,
            series_number=series_number,
        )
        if self._controller and hasattr(self._controller, "on_series_download_fully_complete"):
            try:
                self._controller.on_series_download_fully_complete(series_number)
            except Exception:
                pass
        self._drain_events()

    def step(self, label: str) -> None:
        """Record a named scenario step in the event log."""
        self._log.append(ET_SCENARIO_STEP, label=label)

    def snapshot_memory(self) -> None:
        self._kpi.snapshot_memory()

    # ── finish ────────────────────────────────────────────────────────────────

    def finish(self) -> "HarnessResult":
        """Finalise artifacts and return a HarnessResult."""
        if self._finished:
            raise RuntimeError("finish() already called")
        self._finished = True

        self._log.append(ET_SCENARIO_END, scenario=self.scenario_name)

        # Feed event log into state machine
        self._sm.feed(self._log.events())

        # Collect KPIs
        self._kpi.set_scenario_state(
            **{
                "S09_modality": self.modality,
                "S10_series_number": "1",
            }
        )
        kpis = self._kpi.collect()

        # Run failure detectors
        findings = detect_all(
            events=self._log.events(),
            kpis=kpis,
            machines=self._sm.machines(),
            scenario_run_count=self.run_count,
        )
        findings.sort(key=severity_order)

        # Score hypotheses
        hypotheses = self._engine.score_all(kpis, findings, events=self._log.events())

        # Write artifacts
        self._writer.write_kpis(kpis)
        self._writer.write_findings(findings)
        self._writer.write_hypotheses(hypotheses)
        self._writer.write_state_machines(self._sm.summary())
        self._writer.write_full_summary(
            meta=self._meta,
            kpis=kpis,
            findings=findings,
            hypotheses=hypotheses,
        )
        self._log.flush_ring_buffer()
        self._writer.mark_ended(self._meta)

        # Detach spy wrappers
        self._kpi.detach()
        self._log.close()

        return HarnessResult(
            kpis=kpis,
            findings=findings,
            hypotheses=hypotheses,
            run_dir=self.run_dir,
            scenario_name=self.scenario_name,
        )

    # ── internal ─────────────────────────────────────────────────────────────

    def _drain_events(self) -> None:
        if not self._process_events:
            return
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                app.processEvents()
        except Exception:
            pass

    def _build_mock_controller(self) -> object:
        """Build a minimal mock ViewerController for synthetic scenarios."""
        ctrl = SimpleNamespace()
        ctrl.logger = SimpleNamespace(
            info=_noop, debug=_noop, warning=_noop, error=_noop,
        )
        ctrl.lst_nodes_viewer = []
        # Progressive tracking
        ctrl._progressive_series = {}
        ctrl._progressive_display_done = set()
        ctrl._progressive_display_inflight = set()
        ctrl._progressive_grow_batch_size = 10
        ctrl._is_fast_viewer_mode = lambda: True
        ctrl._progressive_grow_timer = SimpleNamespace(
            isActive=lambda: False, start=_noop, stop=_noop,
        )
        # Completion layers
        ctrl._completion_sweep_series_set = set()
        ctrl._completion_sweep_timer = SimpleNamespace(
            isActive=lambda: False, start=_noop, stop=_noop,
        )
        # Caches
        ctrl._series_cache = {}
        ctrl._hot_series_cache = {}
        ctrl._metadata_flat_cache = {}
        ctrl._disk_count_cache = {}
        ctrl._series_number_to_index = {}
        ctrl.zeta_boost = SimpleNamespace(invalidate_series=_noop)
        ctrl.parent_widget = SimpleNamespace(
            lst_thumbnails_data=[],
            thumbnail_manager=SimpleNamespace(update_series_image_count=_noop),
        )
        # Methods used by KpiCollector spy targets
        ctrl.on_series_images_progress = lambda sn, dl, tot: None
        ctrl.on_series_download_fully_complete = lambda sn: None
        ctrl._start_progressive_display = lambda *a, **kw: None
        ctrl._grow_progressive_fast = lambda *a, **kw: None
        ctrl._refresh_stored_metadata_instances = lambda *a, **kw: None
        ctrl._completion_verify_series = lambda *a, **kw: None
        ctrl._completion_sweep_tick = lambda *a, **kw: None
        return ctrl
