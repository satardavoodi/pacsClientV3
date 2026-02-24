"""
A/B bottleneck report for diagnostic stage-timing logs.

Usage:
  python tools/ab_bottleneck_report.py \
      --a logs\condition_a\viewer_diagnostics.log logs\condition_a\download_diagnostics.log \
      --b logs\condition_b\viewer_diagnostics.log logs\condition_b\download_diagnostics.log

Output:
  - Top bottlenecks during download (Condition B)
  - Typical vs worst duration
  - Whether the bottleneck exists in baseline (Condition A)
  - Heuristic cause tags (disk I/O, CPU, DB contention, UI loop delay, IPC/network)
"""

from __future__ import annotations

import argparse
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


STAGE_RE = re.compile(
    r"component=(?P<component>\w+)"
    r".*?fn=(?P<fn>\S+)"
    r"\s+stage=(?P<stage>\S+)"
    r"\s+result=(?P<result>\S+)"
    r".*?stage-timing\s+duration_ms=(?P<duration>[0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)

RESOURCE_RE = re.compile(
    r"resource-summary\s+cpu=(?P<cpu>[0-9]+(?:\.[0-9]+)?)%\s+rss=(?P<rss>[0-9]+(?:\.[0-9]+)?)MB",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StageKey:
    component: str
    function: str
    stage: str


def _read_lines(paths: Iterable[str]) -> Iterable[str]:
    for p in paths:
        path = Path(p)
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                yield line.rstrip("\n")


def _collect_stage_data(paths: Iterable[str]) -> Tuple[Dict[StageKey, List[float]], List[Tuple[float, float]]]:
    stage_data: Dict[StageKey, List[float]] = {}
    resources: List[Tuple[float, float]] = []

    for line in _read_lines(paths):
        m = STAGE_RE.search(line)
        if m:
            key = StageKey(
                component=m.group("component").lower(),
                function=m.group("fn"),
                stage=m.group("stage"),
            )
            duration = float(m.group("duration"))
            stage_data.setdefault(key, []).append(duration)
            continue

        r = RESOURCE_RE.search(line)
        if r:
            resources.append((float(r.group("cpu")), float(r.group("rss"))))

    return stage_data, resources


def _median(values: List[float]) -> float:
    return statistics.median(values) if values else 0.0


def _p95(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round(0.95 * (len(s) - 1))))
    return s[idx]


def _cause_tag(key: StageKey) -> str:
    blob = f"{key.component} {key.function} {key.stage}".lower()

    if "db" in blob or any(t in blob for t in ["query", "transaction", "pool", "connection"]):
        return "DB contention"
    if any(t in blob for t in ["lock_wait", "send", "recv", "socket", "serialize", "parse"]):
        return "IPC/network"
    if any(t in blob for t in ["disk", "write", "read", "io"]):
        return "disk I/O"
    if any(t in blob for t in ["queue_delay", "event", "wheel", "scroll"]):
        return "UI loop delay"
    if any(t in blob for t in ["render", "vtk", "itk", "decode", "decompress", "filter"]):
        return "CPU/render"
    return "mixed/other"


def _format_ms(value: float) -> str:
    return f"{value:.2f}"


def build_report(a_paths: List[str], b_paths: List[str], top_n: int = 15) -> str:
    a_data, a_resources = _collect_stage_data(a_paths)
    b_data, b_resources = _collect_stage_data(b_paths)

    rows = []
    for key, b_values in b_data.items():
        if len(b_values) < 3:
            continue
        a_values = a_data.get(key, [])
        b_typ = _median(b_values)
        b_worst = max(b_values)
        b_p95 = _p95(b_values)
        a_typ = _median(a_values)

        rows.append(
            {
                "key": key,
                "b_count": len(b_values),
                "b_typ": b_typ,
                "b_p95": b_p95,
                "b_worst": b_worst,
                "a_count": len(a_values),
                "a_typ": a_typ,
                "present_a": len(a_values) >= 3,
                "delta_typ": b_typ - a_typ,
                "cause": _cause_tag(key),
            }
        )

    rows.sort(key=lambda r: (r["b_typ"], r["b_p95"], r["b_worst"]), reverse=True)
    top = rows[:top_n]

    out: List[str] = []
    out.append("Top bottlenecks during download (Condition B)")
    out.append("=" * 72)
    out.append(
        "rank | component | function | stage | typical_ms_B | p95_ms_B | worst_ms_B | "
        "present_in_A | typical_ms_A | delta_typical_ms | suspected_cause"
    )

    for i, r in enumerate(top, start=1):
        key: StageKey = r["key"]
        out.append(
            f"{i:>4} | {key.component:<9} | {key.function:<24} | {key.stage:<20} | "
            f"{_format_ms(r['b_typ']):>12} | {_format_ms(r['b_p95']):>8} | {_format_ms(r['b_worst']):>10} | "
            f"{str(r['present_a']):<12} | {_format_ms(r['a_typ']):>11} | {_format_ms(r['delta_typ']):>16} | {r['cause']}"
        )

    if b_resources:
        cpu_values = [c for c, _ in b_resources]
        rss_values = [r for _, r in b_resources]
        out.append("")
        out.append("Resource summary during Condition B")
        out.append("-" * 72)
        out.append(
            "cpu_avg=%0.1f%% cpu_peak=%0.1f%% rss_avg=%0.1fMB rss_peak=%0.1fMB samples=%d"
            % (
                statistics.mean(cpu_values),
                max(cpu_values),
                statistics.mean(rss_values),
                max(rss_values),
                len(b_resources),
            )
        )

    if not top:
        out.append("")
        out.append("No stage-timing rows found. Ensure new logs include fn/stage/result fields and stage-timing entries.")

    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate A/B bottleneck ranking from diagnostic logs")
    parser.add_argument("--a", nargs="+", required=True, help="Condition A log files")
    parser.add_argument("--b", nargs="+", required=True, help="Condition B log files")
    parser.add_argument("--top", type=int, default=15, help="Number of ranked rows")
    parser.add_argument("--out", default="", help="Optional output file path")
    args = parser.parse_args()

    report = build_report(args.a, args.b, top_n=max(1, int(args.top)))
    print(report)

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
