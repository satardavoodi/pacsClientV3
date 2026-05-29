"""
tests/diagnostics/comparison.py
=================================
MRI vs CT side-by-side KPI comparison for the FAST viewer diagnostic framework.

Compares two KPI dicts (one MR run, one CT run) and produces a structured diff
that highlights which KPIs diverge significantly — used to isolate CT-specific
regression causes (primarily H1: metadata stall).

Usage
-----
    from tests.diagnostics.comparison import compare_runs, format_diff

    mr_kpis = collector_mr.collect()
    ct_kpis = collector_ct.collect()

    diff = compare_runs(mr_kpis, ct_kpis, mr_label="MR_s01", ct_label="CT_s03")
    print(format_diff(diff))
    diff.write_json(Path(run_dir) / "comparison.json")
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tests.diagnostics.kpi_collector import (
    T05_METADATA_REFRESH_MAX_MS,
    T06_METADATA_REFRESH_MEAN_MS,
    T07_GROW_MAX_MS,
    T08_GROW_MEAN_MS,
    T09_PROGRESSIVE_START_DURATION_MS,
    C01_PROGRESSIVE_START_CALLS,
    C02_GROW_CALLS,
    C04_METADATA_REFRESH_CALLS,
    T01_FIRST_PROGRESS_TO_FIRST_GROW_MS,
    M02_RSS_MB_AT_PEAK,
    M04_RSS_DELTA_MB,
    S09_MODALITY,
)

# KPIs to compare in the MR vs CT diff (those most likely to differ)
_COMPARISON_KEYS: List[Tuple[str, str]] = [
    (T05_METADATA_REFRESH_MAX_MS,        "Metadata refresh max (ms)"),
    (T06_METADATA_REFRESH_MEAN_MS,       "Metadata refresh mean (ms)"),
    (T07_GROW_MAX_MS,                    "grow() max duration (ms)"),
    (T08_GROW_MEAN_MS,                   "grow() mean duration (ms)"),
    (T09_PROGRESSIVE_START_DURATION_MS,  "Progressive start (ms)"),
    (T01_FIRST_PROGRESS_TO_FIRST_GROW_MS,"First-progress → first-grow (ms)"),
    (C01_PROGRESSIVE_START_CALLS,        "progressive_start() calls"),
    (C02_GROW_CALLS,                     "grow() calls"),
    (C04_METADATA_REFRESH_CALLS,         "metadata refresh calls"),
    (M02_RSS_MB_AT_PEAK,                 "Peak RSS (MB)"),
    (M04_RSS_DELTA_MB,                   "RSS delta (MB)"),
]

# Ratio threshold above which a difference is marked "SIGNIFICANT"
_RATIO_THRESHOLD = 2.0       # CT value > 2× MR value
_ABSOLUTE_THRESHOLD = 100.0   # ms — always flag if absolute gap > this


@dataclass
class KpiDiffRow:
    key: str
    label: str
    mr_value: Any
    ct_value: Any
    ratio: Optional[float]    # ct / mr (None if either is 0 / None)
    delta: Optional[float]    # ct - mr
    significant: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ComparisonResult:
    mr_label: str
    ct_label: str
    rows: List[KpiDiffRow] = field(default_factory=list)
    significant_count: int = 0
    primary_concern: Optional[str] = None  # key of most divergent KPI

    def write_json(self, path: Path | str) -> None:
        data = {
            "mr_label": self.mr_label,
            "ct_label": self.ct_label,
            "significant_count": self.significant_count,
            "primary_concern": self.primary_concern,
            "rows": [r.to_dict() for r in self.rows],
        }
        Path(path).write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mr_label": self.mr_label,
            "ct_label": self.ct_label,
            "significant_count": self.significant_count,
            "primary_concern": self.primary_concern,
            "rows": [r.to_dict() for r in self.rows],
        }


def compare_runs(
    mr_kpis: Dict[str, Any],
    ct_kpis: Dict[str, Any],
    mr_label: str = "MR",
    ct_label: str = "CT",
) -> ComparisonResult:
    """Produce a structured MR vs CT KPI diff."""
    rows: List[KpiDiffRow] = []
    max_ratio = 0.0
    max_ratio_key = None

    for key, label in _COMPARISON_KEYS:
        mr_v = mr_kpis.get(key)
        ct_v = ct_kpis.get(key)

        # Compute ratio and delta for numeric types
        ratio: Optional[float] = None
        delta: Optional[float] = None
        significant = False

        if isinstance(mr_v, (int, float)) and isinstance(ct_v, (int, float)):
            delta = float(ct_v) - float(mr_v)
            if mr_v and mr_v > 0:
                ratio = float(ct_v) / float(mr_v)
                if ratio > _RATIO_THRESHOLD:
                    significant = True
                if ratio > max_ratio:
                    max_ratio = ratio
                    max_ratio_key = key
            if abs(delta) > _ABSOLUTE_THRESHOLD:
                significant = True

        rows.append(KpiDiffRow(
            key=key,
            label=label,
            mr_value=mr_v,
            ct_value=ct_v,
            ratio=ratio,
            delta=delta,
            significant=significant,
        ))

    significant_count = sum(1 for r in rows if r.significant)
    return ComparisonResult(
        mr_label=mr_label,
        ct_label=ct_label,
        rows=rows,
        significant_count=significant_count,
        primary_concern=max_ratio_key,
    )


def format_diff(result: ComparisonResult) -> str:
    """Return a human-readable table of the MR vs CT diff."""
    lines = [
        f"MR vs CT Comparison: {result.mr_label} ↔ {result.ct_label}",
        f"{'─'*70}",
        f"{'KPI':<42}  {'MR':>10}  {'CT':>10}  {'Ratio':>7}  {'!':>2}",
        f"{'─'*70}",
    ]
    for row in result.rows:
        flag = "⚠" if row.significant else " "
        mr_str = _fmt_val(row.mr_value)
        ct_str = _fmt_val(row.ct_value)
        ratio_str = f"{row.ratio:.2f}×" if row.ratio is not None else "n/a"
        lines.append(
            f"{row.label:<42}  {mr_str:>10}  {ct_str:>10}  {ratio_str:>7}  {flag:>2}"
        )
    lines.append(f"{'─'*70}")
    lines.append(f"Significant KPIs: {result.significant_count}")
    if result.primary_concern:
        lines.append(f"Primary concern: {result.primary_concern}")
    return "\n".join(lines)


def _fmt_val(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)
