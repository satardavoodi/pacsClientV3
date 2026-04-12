"""
tests/diagnostics/report_writer.py
=====================================
Crash-safe incremental artifact writer for the FAST viewer diagnostic framework.

Artifact schema
---------------
output_dir/
    run_meta.json         — scenario info, process id, study uid, crash flag
    events.jsonl          — append-only event stream (managed by EventLog)
    ring_buffer.json      — last 200 events (periodic atomic write)
    kpis.json             — final KPI dict (written at scenario end)
    kpis_snapshot.json    — last periodic KPI snapshot (atomic write every 30s)
    last_good_state.json  — viewer/controller state snapshot (every 60s)
    hypotheses.json       — scored hypothesis results
    state_machines.json   — per-series state machine reconstruction
    comparison.json       — MR vs CT diff (optional)
    summary.txt           — human-readable one-page summary

All JSON writes use an atomic tmp→rename pattern to avoid corrupt output on crash.
"""
from __future__ import annotations

import atexit
import json
import os
import sys
import time
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from tests.diagnostics.event_log import EventLog


ARTIFACT_NAMES = (
    "run_meta.json",
    "events.jsonl",
    "ring_buffer.json",
    "kpis.json",
    "kpis_snapshot.json",
    "last_good_state.json",
    "hypotheses.json",
    "state_machines.json",
    "comparison.json",
    "summary.txt",
)


@dataclass
class RunMeta:
    scenario_name: str
    scenario_type: str          # "synthetic" | "real_app" | "replay"
    started_at: float           # time.time()
    ended_at: Optional[float] = None
    process_id: int = field(default_factory=os.getpid)
    process_died: bool = False  # set True if atexit fires before normal close
    study_uid: Optional[str] = None
    series_number: Optional[str] = None
    modality: Optional[str] = None
    slice_count: Optional[int] = None
    run_count: int = 1      # repetition number for repeated-open scenarios
    python_version: str = field(default_factory=lambda: sys.version.split()[0])
    platform: str = field(default_factory=lambda: sys.platform)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ReportWriter:
    """Writes all diagnostic artifacts for one scenario run.

    Parameters
    ----------
    output_dir : Path | str
        Directory where all artifacts are written.
    """

    def __init__(self, output_dir: Path | str) -> None:
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._closed = False
        self._lock = threading.Lock()
        # Register atexit handler to mark process_died if we crash
        atexit.register(self._atexit_handler)

    # ── run-meta ──────────────────────────────────────────────────────────────

    def write_run_meta(self, meta: RunMeta) -> None:
        self._atomic_write("run_meta.json", meta.to_dict())

    def mark_ended(self, meta: RunMeta) -> None:
        meta.ended_at = time.time()
        meta.process_died = False
        self.write_run_meta(meta)

    # ── KPI snapshots ─────────────────────────────────────────────────────────

    def write_kpis(self, kpis: Dict[str, Any]) -> None:
        """Write final KPIs (called at scenario end)."""
        self._atomic_write("kpis.json", kpis)

    def write_kpi_snapshot(self, kpis: Dict[str, Any]) -> None:
        """Periodic atomic snapshot of current KPIs (safe to call from timer)."""
        snap = dict(kpis)
        snap["_snapshot_ts"] = time.time()
        self._atomic_write("kpis_snapshot.json", snap)

    # ── last_good_state ───────────────────────────────────────────────────────

    def write_last_good_state(self, state: Dict[str, Any]) -> None:
        state = dict(state)
        state["_snapshot_ts"] = time.time()
        self._atomic_write("last_good_state.json", state)

    # ── hypotheses ────────────────────────────────────────────────────────────

    def write_hypotheses(self, results: List[Any]) -> None:
        """Write a list of HypothesisResult objects."""
        data = [r.to_dict() if hasattr(r, "to_dict") else r for r in results]
        self._atomic_write("hypotheses.json", {"hypotheses": data})

    # ── state machines ────────────────────────────────────────────────────────

    def write_state_machines(self, machines_data: Dict[str, Any]) -> None:
        self._atomic_write("state_machines.json", machines_data)

    # ── failure signatures ────────────────────────────────────────────────────

    def write_findings(self, findings: List[Any]) -> None:
        data = [f.to_dict() if hasattr(f, "to_dict") else f for f in findings]
        self._atomic_write("findings.json", {"findings": data, "count": len(data)})

    # ── comparison ────────────────────────────────────────────────────────────

    def write_comparison(self, comparison: Any) -> None:
        data = comparison.to_dict() if hasattr(comparison, "to_dict") else comparison
        self._atomic_write("comparison.json", data)

    # ── summary ───────────────────────────────────────────────────────────────

    def write_summary(self, text: str) -> None:
        try:
            (self._dir / "summary.txt").write_text(text, encoding="utf-8")
        except Exception:
            pass

    def write_full_summary(
        self,
        meta: RunMeta,
        kpis: Dict[str, Any],
        findings: List[Any],
        hypotheses: List[Any],
    ) -> str:
        """Generate and write the human-readable summary.txt."""
        lines = [
            "=" * 72,
            f"AIPacs FAST Viewer Diagnostic Report",
            f"Scenario : {meta.scenario_name}  ({meta.scenario_type})",
            f"Modality : {meta.modality or '?'}  Slices: {meta.slice_count or '?'}",
            f"Started  : {_fmt_time(meta.started_at)}",
            f"Ended    : {_fmt_time(meta.ended_at) if meta.ended_at else 'N/A'}",
            f"Crash    : {'YES' if meta.process_died else 'NO'}",
            "=" * 72,
            "",
            "── KPI Highlights ──",
        ]

        _kpi_labels = {
            "T05_metadata_refresh_max_ms": "Metadata refresh max (ms)",
            "T07_grow_max_ms":             "Grow max (ms)",
            "T01_first_progress_to_first_grow_ms": "First-progress→first-grow (ms)",
            "C01_progressive_start_calls": "Progressive start calls",
            "C02_grow_calls":              "Grow calls",
            "C06_decode_failed_signals":   "Decode failures",
            "C16_exceptions_swallowed":    "Exceptions swallowed",
            "M02_rss_mb_at_peak":          "Peak RSS (MB)",
        }
        for k, label in _kpi_labels.items():
            v = kpis.get(k, "—")
            lines.append(f"  {label:<40}  {v}")

        if findings:
            lines += ["", "── Failure Signatures ──"]
            for f in sorted(findings, key=lambda x: getattr(x, "severity", "Z")):
                code = getattr(f, "code", "?")
                title = getattr(f, "title", "?")
                sev = getattr(f, "severity", "?")
                lines.append(f"  [{sev:8}] {code}: {title}")
        else:
            lines += ["", "── Failure Signatures: NONE DETECTED ──"]

        if hypotheses:
            lines += ["", "── Hypothesis Results ──"]
            for h in hypotheses:
                code = getattr(h, "code", "?")
                verdict = getattr(h, "verdict", "?")
                score = getattr(h, "score", 0.0)
                title = getattr(h, "title", "?")
                patch = "✓ PATCH ALLOWED" if getattr(h, "patch_allowed", False) else ""
                lines.append(f"  {code}: {verdict:<12} ({score:.2f})  {title[:40]}  {patch}")

        lines += ["", "=" * 72, ""]
        text = "\n".join(lines)
        self.write_summary(text)
        return text

    # ── close ─────────────────────────────────────────────────────────────────

    def close(self) -> None:
        with self._lock:
            self._closed = True

    # ── internal ─────────────────────────────────────────────────────────────

    def _atomic_write(self, filename: str, data: Any) -> None:
        """Write *data* as JSON to filename using tmp→rename for crash safety."""
        if self._closed:
            return
        try:
            tmp = self._dir / (filename + ".tmp")
            dst = self._dir / filename
            content = json.dumps(data, indent=2, ensure_ascii=False, default=str)
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(dst)
        except Exception:
            pass  # Never crash the framework on output failure

    def _atexit_handler(self) -> None:
        """Mark process_died=True in run_meta if we exit abnormally."""
        try:
            meta_path = self._dir / "run_meta.json"
            if meta_path.exists():
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                if not data.get("ended_at"):
                    data["process_died"] = True
                    data["_atexit_ts"] = time.time()
                    self._atomic_write("run_meta.json", data)
        except Exception:
            pass


def _fmt_time(ts: Optional[float]) -> str:
    if ts is None:
        return "—"
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
