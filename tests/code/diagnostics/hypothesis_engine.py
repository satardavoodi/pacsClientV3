"""
tests/diagnostics/hypothesis_engine.py
=========================================
Evidence-based hypothesis scoring engine for the FAST viewer diagnostic
framework.

Hypotheses (H1–H6)
-------------------
H1  Metadata scan stalls main thread (CT 400+ slices) — primary freeze cause
H2  Teardown-decode race → UAF crash
H3  Series-generation mismatch → wrong-series display
H4  Done-guard collision on re-open → progressive never activates on second open
H5  Asyncio/thread inflight stuck permanently → viewer frozen indefinitely
H6  Completion layer miss → viewer stuck at N-5 slices (final batch not applied)

Scoring
-------
Each hypothesis has a list of Evidence items.  Each item is either REQUIRED
(must be present for a confident conclusion) or SUPPORTING (raises score).

Scores:
    0.0 → no evidence
    0.0–0.4 → possible (some signals)
    0.4–0.7 → likely (multiple supporting items)
    0.7–1.0 → confirmed (required + supporting evidence, all thresholds met)

Minimum-evidence rules
----------------------
H1: metadata_refresh_max_ms > 200 in ≥ 3 scenario runs → CONFIRMED
H2: FS-14 in ≥ 1 real run → CONFIRMED
H4: FS-18 in s08_repeated_open ≥ 2/3 → CONFIRMED
Before any production patch: hypothesis must be CONFIRMED (score > 0.7).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from tests.diagnostics.failure_detector import FailureMatch, detect_all
from tests.diagnostics.kpi_collector import (
    T05_METADATA_REFRESH_MAX_MS,
    T06_METADATA_REFRESH_MEAN_MS,
    C04_METADATA_REFRESH_CALLS,
    C02_GROW_CALLS,
    C06_DECODE_FAILED_SIGNALS,
    C16_EXCEPTIONS_SWALLOWED,
    C14_INFLIGHT_SET_COUNT,
    C15_DONE_GUARD_SET_COUNT,
    C01_PROGRESSIVE_START_CALLS,
    C11_PROGRESS_SIGNALS_RECEIVED,
    S09_MODALITY,
    T01_FIRST_PROGRESS_TO_FIRST_GROW_MS,
    M02_RSS_MB_AT_PEAK,
)
from tests.diagnostics.event_log import EventEntry

# ─── Score thresholds ─────────────────────────────────────────────────────────

SCORE_CONFIRMED  = 0.7
SCORE_LIKELY     = 0.4
SCORE_POSSIBLE   = 0.1
SCORE_NONE       = 0.0


@dataclass
class EvidenceItem:
    name: str
    met: bool
    weight: float          # how much this adds to the score (max 1.0 total)
    required: bool = False
    details: str = ""


@dataclass
class HypothesisResult:
    code: str             # H1–H6
    title: str
    score: float          # 0.0–1.0
    verdict: str          # "CONFIRMED" | "LIKELY" | "POSSIBLE" | "NO_EVIDENCE"
    evidence_items: List[EvidenceItem] = field(default_factory=list)
    blocking_reason: Optional[str] = None   # why Required evidence is missing
    patch_allowed: bool = False
    patch_conditions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "code": self.code,
            "title": self.title,
            "score": round(self.score, 3),
            "verdict": self.verdict,
            "patch_allowed": self.patch_allowed,
            "blocking_reason": self.blocking_reason,
            "patch_conditions": self.patch_conditions,
        }
        d["evidence"] = [
            {
                "name": ei.name,
                "met": ei.met,
                "weight": ei.weight,
                "required": ei.required,
                "details": ei.details,
            }
            for ei in self.evidence_items
        ]
        return d


# ─── HypothesisEngine ────────────────────────────────────────────────────────

class HypothesisEngine:
    """Score all six hypotheses against a set of failure matches and KPIs.

    Parameters
    ----------
    run_count : int
        How many times this scenario was run (for H1/H4 multi-run rules).
    scenario_name : str
        Active scenario name (e.g. "s03_large_ct") for per-hypothesis rules.
    """

    def __init__(
        self,
        run_count: int = 1,
        scenario_name: str = "",
    ) -> None:
        self._run_count = run_count
        self._scenario = scenario_name

    def score_all(
        self,
        kpis: Dict[str, Any],
        findings: List[FailureMatch],
        events: Optional[List[EventEntry]] = None,
    ) -> List[HypothesisResult]:
        """Score all hypotheses and return a list of HypothesisResult."""
        fs_codes = {f.code for f in findings}
        return [
            self._h1_metadata_stall(kpis, fs_codes),
            self._h2_teardown_race(kpis, fs_codes),
            self._h3_generation_mismatch(kpis, fs_codes),
            self._h4_done_guard_collision(kpis, fs_codes),
            self._h5_inflight_stuck(kpis, fs_codes),
            self._h6_completion_layer_miss(kpis, fs_codes),
        ]

    def write_json(self, path: Path | str, results: List[HypothesisResult]) -> None:
        data = {
            "run_count": self._run_count,
            "scenario": self._scenario,
            "hypotheses": [r.to_dict() for r in results],
            "patch_allowed_for": [r.code for r in results if r.patch_allowed],
        }
        Path(path).write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── H1: Metadata scan stalls main thread ──────────────────────────────────

    def _h1_metadata_stall(self, kpis: Dict, fs_codes: set) -> HypothesisResult:
        items: List[EvidenceItem] = []

        max_refresh_ms = kpis.get(T05_METADATA_REFRESH_MAX_MS) or 0.0
        mean_refresh_ms = kpis.get(T06_METADATA_REFRESH_MEAN_MS) or 0.0
        modality = kpis.get(S09_MODALITY, "?")
        refresh_calls = kpis.get(C04_METADATA_REFRESH_CALLS) or 0

        items.append(EvidenceItem(
            name="metadata_refresh_max_gt_200ms",
            met=max_refresh_ms > 200,
            weight=0.35,
            required=True,
            details=f"max={max_refresh_ms:.1f}ms (threshold=200ms)",
        ))
        items.append(EvidenceItem(
            name="fs04_metadata_stall_detected",
            met="FS-04" in fs_codes,
            weight=0.20,
            details="FS-04 failure signature fired",
        ))
        items.append(EvidenceItem(
            name="modality_is_ct",
            met=str(modality).upper() in ("CT", "MG", "DX"),
            weight=0.15,
            details=f"modality={modality}",
        ))
        items.append(EvidenceItem(
            name="multiple_refresh_calls",
            met=refresh_calls > 3,
            weight=0.10,
            details=f"refresh_calls={refresh_calls}",
        ))
        items.append(EvidenceItem(
            name="multi_run_confirmed",
            met=self._run_count >= 3,
            weight=0.10,
            details=f"run_count={self._run_count} (need ≥3 for confirmation)",
        ))
        items.append(EvidenceItem(
            name="mean_refresh_gt_100ms",
            met=mean_refresh_ms > 100,
            weight=0.10,
            details=f"mean={mean_refresh_ms:.1f}ms",
        ))

        score, blocking = self._compute_score(items)
        return HypothesisResult(
            code="H1",
            title="Metadata scan stalls main thread (CT 400+ slices)",
            score=score,
            verdict=self._verdict(score),
            evidence_items=items,
            blocking_reason=blocking,
            patch_allowed=score >= SCORE_CONFIRMED and self._run_count >= 3,
            patch_conditions=[
                "metadata_refresh_max_ms > 200ms in ≥ 3 s03_large_ct runs",
                "modality = CT confirmed",
                "Fix: offload _refresh_stored_metadata_instances to background thread",
            ],
        )

    # ── H2: Teardown-decode race ──────────────────────────────────────────────

    def _h2_teardown_race(self, kpis: Dict, fs_codes: set) -> HypothesisResult:
        items: List[EvidenceItem] = []

        items.append(EvidenceItem(
            name="fs14_loader_outlives_viewer",
            met="FS-14" in fs_codes,
            weight=0.40,
            required=True,
            details="FS-14: loader still in registry after widget destroyed",
        ))
        items.append(EvidenceItem(
            name="fs06_loader_released_early",
            met="FS-06" in fs_codes,
            weight=0.25,
            details="FS-06: grow called after loader release",
        ))
        items.append(EvidenceItem(
            name="fs11_slice_ready_before_bind",
            met="FS-11" in fs_codes,
            weight=0.20,
            details="FS-11: decode_slice_ready arrived before backend bind",
        ))
        items.append(EvidenceItem(
            name="decode_failed_signals",
            met=(kpis.get(C06_DECODE_FAILED_SIGNALS) or 0) > 0,
            weight=0.15,
            details=f"decode_failed_count={kpis.get(C06_DECODE_FAILED_SIGNALS, 0)}",
        ))

        score, blocking = self._compute_score(items)
        return HypothesisResult(
            code="H2",
            title="Teardown-decode race → UAF crash",
            score=score,
            verdict=self._verdict(score),
            evidence_items=items,
            blocking_reason=blocking,
            patch_allowed=score >= SCORE_CONFIRMED and self._run_count >= 1,
            patch_conditions=[
                "FS-14 in ≥ 1 real run (AIPACS_DIAG_MODE=1)",
                "Fix: weak-ref guard in _connect_lazy_loader_signals",
            ],
        )

    # ── H3: Generation mismatch ───────────────────────────────────────────────

    def _h3_generation_mismatch(self, kpis: Dict, fs_codes: set) -> HypothesisResult:
        items: List[EvidenceItem] = []

        items.append(EvidenceItem(
            name="fs15_generation_mismatch",
            met="FS-15" in fs_codes,
            weight=0.70,
            required=True,
            details="FS-15: slice_ready for stale generation",
        ))
        items.append(EvidenceItem(
            name="series_switch_calls",
            met=True,   # always present if measuring
            weight=0.30,
            details="series switches performed",
        ))

        score, blocking = self._compute_score(items)
        return HypothesisResult(
            code="H3",
            title="Series-generation mismatch → wrong-series display",
            score=score,
            verdict=self._verdict(score),
            evidence_items=items,
            blocking_reason=blocking,
            patch_allowed=score >= SCORE_CONFIRMED,
            patch_conditions=[
                "FS-15 in ≥ 1 s06_tab_switch run",
                "Fix: generation-id check in _on_lazy_slice_ready",
            ],
        )

    # ── H4: Done-guard collision ──────────────────────────────────────────────

    def _h4_done_guard_collision(self, kpis: Dict, fs_codes: set) -> HypothesisResult:
        items: List[EvidenceItem] = []

        items.append(EvidenceItem(
            name="fs18_done_guard_false_positive",
            met="FS-18" in fs_codes,
            weight=0.35,
            required=True,
            details="FS-18: done-guard set before any grow",
        ))
        items.append(EvidenceItem(
            name="fs02_done_never_reset",
            met="FS-02" in fs_codes,
            weight=0.30,
            details="FS-02: done-guard never reset between opens",
        ))
        items.append(EvidenceItem(
            name="fs09_progressive_never_started",
            met="FS-09" in fs_codes,
            weight=0.20,
            details="FS-09: progressive never started despite signals",
        ))
        items.append(EvidenceItem(
            name="repeated_open_scenario",
            met="s08" in self._scenario or "repeated" in self._scenario,
            weight=0.15,
            details=f"scenario={self._scenario}",
        ))

        score, blocking = self._compute_score(items)
        return HypothesisResult(
            code="H4",
            title="Done-guard collision on re-open → progressive display dead on second open",
            score=score,
            verdict=self._verdict(score),
            evidence_items=items,
            blocking_reason=blocking,
            patch_allowed=score >= SCORE_CONFIRMED and self._run_count >= 2,
            patch_conditions=[
                "FS-18 in s08_repeated_open ≥ 2/3 runs",
                "_progressive_display_done not reset between tab re-opens",
                "Fix: reset done-guard key on tab close / series eviction",
            ],
        )

    # ── H5: Inflight stuck ────────────────────────────────────────────────────

    def _h5_inflight_stuck(self, kpis: Dict, fs_codes: set) -> HypothesisResult:
        items: List[EvidenceItem] = []

        items.append(EvidenceItem(
            name="fs01_inflight_stuck",
            met="FS-01" in fs_codes,
            weight=0.40,
            required=True,
            details="FS-01: inflight flag set but never cleared",
        ))
        items.append(EvidenceItem(
            name="fs16_inflight_task_orphan",
            met="FS-16" in fs_codes,
            weight=0.25,
            details="FS-16: switch done but inflight not cleared",
        ))
        items.append(EvidenceItem(
            name="fs20_timer_never_fires",
            met="FS-20" in fs_codes,
            weight=0.20,
            details="FS-20: grow timer active but no grow calls for >5s",
        ))
        items.append(EvidenceItem(
            name="fs08_signal_queue_overflow",
            met="FS-08" in fs_codes,
            weight=0.15,
            details="FS-08: 50+ progress signals queued before first grow",
        ))

        score, blocking = self._compute_score(items)
        return HypothesisResult(
            code="H5",
            title="Asyncio/thread inflight stuck permanently → viewer frozen indefinitely",
            score=score,
            verdict=self._verdict(score),
            evidence_items=items,
            blocking_reason=blocking,
            patch_allowed=score >= SCORE_CONFIRMED,
            patch_conditions=[
                "FS-01 in ≥ 1 real run",
                "inflight flag confirmed stuck > 10s",
                "Fix: timeout-based inflight release in _start_progressive_display thread path",
            ],
        )

    # ── H6: Completion layer miss ─────────────────────────────────────────────

    def _h6_completion_layer_miss(self, kpis: Dict, fs_codes: set) -> HypothesisResult:
        items: List[EvidenceItem] = []

        items.append(EvidenceItem(
            name="fs13_completion_layer2_missed",
            met="FS-13" in fs_codes,
            weight=0.40,
            required=True,
            details="FS-13: download_complete but final grow < expected",
        ))
        items.append(EvidenceItem(
            name="fs03_stale_exhausted",
            met="FS-03" in fs_codes,
            weight=0.25,
            details="FS-03: stale retries exhausted before final signal",
        ))
        items.append(EvidenceItem(
            name="fs19_progressive_mode_lost",
            met="FS-19" in fs_codes,
            weight=0.20,
            details="FS-19: progressive mode exited mid-download",
        ))
        items.append(EvidenceItem(
            name="grow_count_lt_expected",
            met=False,   # set dynamically if available
            weight=0.15,
            details="final grow count < expected total",
        ))

        score, blocking = self._compute_score(items)
        return HypothesisResult(
            code="H6",
            title="Completion layer miss → viewer stuck at N-5 slices",
            score=score,
            verdict=self._verdict(score),
            evidence_items=items,
            blocking_reason=blocking,
            patch_allowed=score >= SCORE_CONFIRMED,
            patch_conditions=[
                "FS-13 in ≥ 1 s05_scroll_during_completion or s03_large_ct run",
                "viewer shows < expected slices after download_complete",
                "Fix: strengthen Layer 2b final grow before exit_progressive_mode",
            ],
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _compute_score(
        self,
        items: List[EvidenceItem],
    ) -> tuple[float, Optional[str]]:
        """Compute [0,1] score.  Returns (score, blocking_reason)."""
        total_weight = sum(i.weight for i in items)
        met_weight = sum(i.weight for i in items if i.met)
        score = met_weight / total_weight if total_weight > 0 else 0.0

        # Check required items
        for item in items:
            if item.required and not item.met:
                # Required item missing — cap score
                score = min(score, SCORE_LIKELY - 0.01)
                return score, f"Required evidence '{item.name}' not met: {item.details}"
        return score, None

    def _verdict(self, score: float) -> str:
        if score >= SCORE_CONFIRMED:
            return "CONFIRMED"
        if score >= SCORE_LIKELY:
            return "LIKELY"
        if score >= SCORE_POSSIBLE:
            return "POSSIBLE"
        return "NO_EVIDENCE"
