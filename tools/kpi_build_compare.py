"""KPI cross-build comparison tool.

Reads the JSONL sink and segregates records by ``build_kind`` (source,
frozen, ci_offscreen, ...). For every KPI key, prints median + p95 per
build kind side-by-side so divergences pop out — useful for catching
build-specific regressions like "this is fast on source but slow on the
PyInstaller bundle".

Usage::

    python tools/kpi_build_compare.py
    python tools/kpi_build_compare.py --key patient_open.elapsed_ms
    python tools/kpi_build_compare.py --workflow viewer
    python tools/kpi_build_compare.py --since 2026-05-28

Exits 0 always; this is a reporting tool, not a gate. See
``docs/plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md`` §10.3.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SINK = _PROJECT_ROOT / "user_data" / "test_kpis"


def _load(sink: Path, since: str | None) -> list[dict]:
    if not sink.exists():
        return []
    records: list[dict] = []
    for p in sorted(sink.glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if since and r.get("ts", "") < since:
                continue
            records.append(r)
    return records


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    idx = int(round(p * (len(s) - 1) / 100))
    return s[max(0, min(idx, len(s) - 1))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sink", type=Path, default=_DEFAULT_SINK)
    parser.add_argument("--key", help="Restrict to one KPI key")
    parser.add_argument("--workflow", help="Restrict to one workflow")
    parser.add_argument("--since", help="ISO timestamp filter (records with ts >= since)")
    args = parser.parse_args(argv)

    records = _load(args.sink, args.since)
    if args.key:
        records = [r for r in records if r.get("key") == args.key]
    if args.workflow:
        records = [r for r in records if r.get("workflow") == args.workflow]

    if not records:
        print("(no matching KPI records)")
        return 0

    # Group: key → build_kind → values
    by_key: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list))
    for r in records:
        k = r.get("key", "?")
        bk = str(r.get("build_kind") or "unknown")
        try:
            v = float(r.get("value", 0))
        except (TypeError, ValueError):
            continue
        by_key[k][bk].append(v)

    # Determine the union of build kinds we'll print columns for.
    all_builds = sorted({bk for d in by_key.values() for bk in d})
    if not all_builds:
        print("(records have no build_kind field — nothing to compare)")
        return 0

    # Print header.
    col_w = 16
    name_w = 48
    head = f"{'KEY':<{name_w}}  " + "  ".join(
        f"{b[:col_w]:>{col_w}}" for b in all_builds
    )
    print(head)
    print("-" * len(head))

    # Per-key row: print median per build, plus the largest pairwise
    # delta across the row as a divergence signal.
    findings: list[tuple[str, float, str, str]] = []  # (key, pct_delta, build_a, build_b)
    for key in sorted(by_key):
        cells = []
        per_build_median = {}
        for b in all_builds:
            vals = by_key[key].get(b, [])
            if not vals:
                cells.append(f"{'-':>{col_w}}")
                continue
            m = median(vals)
            per_build_median[b] = m
            cells.append(f"{m:>{col_w}.1f}")
        print(f"{key[:name_w]:<{name_w}}  " + "  ".join(cells))

        # Divergence pairs
        meds = list(per_build_median.items())
        for i in range(len(meds)):
            for j in range(i + 1, len(meds)):
                a, ma = meds[i]
                b, mb = meds[j]
                if ma <= 0 and mb <= 0:
                    continue
                ratio_pct = abs(ma - mb) / max(ma, mb, 1e-9) * 100
                if ratio_pct >= 20.0:
                    findings.append((key, ratio_pct, a, b))

    if findings:
        print("\n=== Divergences (≥20% delta between builds) ===")
        for key, pct, a, b in sorted(findings, key=lambda x: -x[1]):
            print(f"  {pct:5.1f}%   {key:<48}   {a} vs {b}")
    else:
        print("\n(no ≥20% divergences across builds)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
