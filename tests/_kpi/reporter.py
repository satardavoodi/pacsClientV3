"""KPI reporter — CLI over the JSONL sink.

Subcommands:
    last        — Pretty table of the most recent run.
    trend KEY   — ASCII chart of one KPI over the last N runs.
    diff A B    — Per-key delta between two run_ids.
    summary     — Per-workflow PASS/WARN/FAIL counts over the last run.

No external deps. Reads ``user_data/test_kpis/*.jsonl``.

Example::
    python tests/_kpi/reporter.py last
    python tests/_kpi/reporter.py trend patient_open.elapsed_ms
    python tests/_kpi/reporter.py diff 2026-05-28-10-25-XX 2026-05-28-11-40-YY
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SINK = _PROJECT_ROOT / "user_data" / "test_kpis"


def _all_records() -> list[dict]:
    if not _SINK.exists():
        return []
    out: list[dict] = []
    for p in sorted(_SINK.glob("*.jsonl")):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except Exception:
            continue
    return out


def _records_by_run() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in _all_records():
        grouped[r.get("run_id", "?")].append(r)
    return grouped


def _latest_run_id() -> str | None:
    grouped = _records_by_run()
    if not grouped:
        return None
    # run_id starts with YYYY-MM-DD-HH-MM — lexicographic sort = chronological
    return sorted(grouped.keys())[-1]


# ─────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────

def cmd_last() -> int:
    rid = _latest_run_id()
    if rid is None:
        print("(no KPI records found yet — sink dir empty)")
        return 0
    records = _records_by_run()[rid]
    print(f"Run: {rid}   records: {len(records)}")
    print("-" * 100)
    print(f"{'KEY':<48} {'VALUE':>12} {'UNIT':>6} {'HARD':>10} {'VERDICT':>8}")
    print("-" * 100)
    for r in sorted(records, key=lambda x: (x.get("workflow", ""), x.get("key", ""))):
        key = r.get("key", "?")[:47]
        val = r.get("value", float("nan"))
        unit = r.get("unit", "")
        hard = r.get("threshold_hard")
        hard_s = f"{hard}" if hard is not None else "-"
        verdict = r.get("verdict", "?")
        print(f"{key:<48} {val:>12.2f} {unit:>6} {hard_s:>10} {verdict:>8}")
    counts = defaultdict(int)
    for r in records:
        counts[r.get("verdict", "?")] += 1
    print("-" * 100)
    print(f"Summary: PASS={counts['PASS']}  WARN={counts['WARN']}  FAIL={counts['FAIL']}")
    return 0 if counts["FAIL"] == 0 else 2


def cmd_trend(key: str, n_runs: int = 20) -> int:
    grouped = _records_by_run()
    if not grouped:
        print("(no KPI records found yet)")
        return 0
    series: list[tuple[str, float]] = []
    for rid in sorted(grouped.keys())[-n_runs:]:
        vals = [r.get("value") for r in grouped[rid]
                if r.get("key") == key]
        if not vals:
            continue
        # median is the per-run summary statistic
        series.append((rid, sorted(vals)[len(vals)//2]))
    if not series:
        print(f"(no records for key {key!r})")
        return 0
    lo = min(v for _, v in series)
    hi = max(v for _, v in series)
    span = max(hi - lo, 1e-9)
    print(f"Trend for {key}   (last {len(series)} runs)")
    print(f"min={lo:.2f}   max={hi:.2f}")
    print("-" * 80)
    for rid, v in series:
        bar_len = int(((v - lo) / span) * 40)
        bar = "▇" * bar_len + "·" * (40 - bar_len)
        print(f"{rid[:28]:28s}  {bar}  {v:>10.2f}")
    return 0


def cmd_diff(run_a: str, run_b: str) -> int:
    grouped = _records_by_run()
    a = {r["key"]: r["value"] for r in grouped.get(run_a, [])}
    b = {r["key"]: r["value"] for r in grouped.get(run_b, [])}
    if not a:
        print(f"(no records for run {run_a!r})")
        return 1
    if not b:
        print(f"(no records for run {run_b!r})")
        return 1
    keys = sorted(set(a) | set(b))
    print(f"{'KEY':<48} {'A':>12} {'B':>12} {'DELTA':>12}")
    print("-" * 86)
    for k in keys:
        va = a.get(k)
        vb = b.get(k)
        delta = (vb - va) if (va is not None and vb is not None) else float("nan")
        va_s = f"{va:>12.2f}" if va is not None else f"{'-':>12}"
        vb_s = f"{vb:>12.2f}" if vb is not None else f"{'-':>12}"
        delta_s = f"{delta:>+12.2f}" if delta == delta else f"{'-':>12}"
        print(f"{k:<48} {va_s} {vb_s} {delta_s}")
    return 0


def cmd_summary() -> int:
    rid = _latest_run_id()
    if rid is None:
        print("(no records)")
        return 0
    records = _records_by_run()[rid]
    by_wf: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in records:
        by_wf[r.get("workflow", "?")][r.get("verdict", "?")] += 1
    print(f"Run: {rid}")
    print(f"{'workflow':<24} {'PASS':>6} {'WARN':>6} {'FAIL':>6}")
    print("-" * 50)
    for wf in sorted(by_wf):
        c = by_wf[wf]
        print(f"{wf:<24} {c['PASS']:>6} {c['WARN']:>6} {c['FAIL']:>6}")
    return 0


# ─────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("last", help="pretty table of the most recent run")
    p_trend = sub.add_parser("trend", help="ASCII chart of one KPI over last N runs")
    p_trend.add_argument("key")
    p_trend.add_argument("-n", "--n-runs", type=int, default=20)
    p_diff = sub.add_parser("diff", help="delta between two run_ids")
    p_diff.add_argument("run_a")
    p_diff.add_argument("run_b")
    sub.add_parser("summary", help="per-workflow PASS/WARN/FAIL")
    args = parser.parse_args(argv)

    if args.cmd == "last" or args.cmd is None:
        return cmd_last()
    if args.cmd == "trend":
        return cmd_trend(args.key, args.n_runs)
    if args.cmd == "diff":
        return cmd_diff(args.run_a, args.run_b)
    if args.cmd == "summary":
        return cmd_summary()
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
