#!/usr/bin/env python
"""
tests/diagnostics/run_diagnostic.py
=====================================
CLI runner for the FAST viewer automated diagnostic framework.

Usage
-----
    # Run a single scenario
    python tests/diagnostics/run_diagnostic.py --scenario s03_large_ct

    # Run all 10 scenarios
    python tests/diagnostics/run_diagnostic.py --all

    # Replay saved events.jsonl
    python tests/diagnostics/run_diagnostic.py --replay path/to/events.jsonl

    # Compare two existing runs
    python tests/diagnostics/run_diagnostic.py \\
        --compare tests/diagnostics/runs/s01_small_mri \\
                  tests/diagnostics/runs/s03_large_ct

Options
-------
    --scenario NAME     Name of scenario to run (e.g. s03_large_ct)
    --all               Run all 10 scenarios in order
    --replay PATH       Replay a saved events.jsonl file
    --compare DIR DIR   Load KPIs from two run directories and diff them
    --output-dir DIR    Where to write run artifacts (default: runs/<scenario>)
    --run-count N       Repetition index for H1/H4 minimum-evidence scenarios
    --verbose           Print summary.txt after each run
    --no-color          Disable ANSI colour in output
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path when running directly
_THIS = Path(__file__).resolve()
_ROOT = _THIS.parents[3]  # tests/diagnostics/run_diagnostic.py → project root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_DEFAULT_RUN_ROOT = _THIS.parent / "runs"

_ALL_SCENARIOS = [
    "s01_small_mri",
    "s02_medium_ct",
    "s03_large_ct",
    "s04_early_teardown",
    "s05_scroll_completion",
    "s06_tab_switch",
    "s07_series_interrupt",
    "s08_repeated_open",
    "s09_mri_vs_ct",
    "s10_memory_pressure",
]


def _load_scenario(name: str):
    """Import and return a scenario module."""
    module_name = f"tests.diagnostics.scenarios.{name}"
    try:
        return importlib.import_module(module_name)
    except ImportError as e:
        print(f"ERROR: Cannot import scenario '{name}': {e}", file=sys.stderr)
        sys.exit(1)


def _run_scenario(
    name: str,
    output_dir: Path,
    run_count: int = 1,
    verbose: bool = False,
) -> int:
    """Run a single scenario.  Returns 0 on success, 1 on failure."""
    from tests.diagnostics.harness import DiagnosticHarness

    scenario = _load_scenario(name)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'─'*60}")
    print(f"  Scenario : {name}")
    print(f"  Output   : {output_dir}")
    print(f"  Run #    : {run_count}")
    print(f"{'─'*60}")

    t0 = time.perf_counter()
    try:
        result = scenario.run(output_dir=output_dir, run_count=run_count)
    except TypeError:
        # Some scenarios don't accept run_count
        result = scenario.run(output_dir=output_dir)
    elapsed = (time.perf_counter() - t0) * 1000

    # Print findings summary
    if result.findings:
        print(f"\n  ⚠  {len(result.findings)} finding(s):")
        for f in result.findings:
            flag = "🔴" if f.severity == "CRITICAL" else "🟠" if f.severity == "HIGH" else "🟡"
            print(f"     {flag} [{f.code}] {f.title}")
    else:
        print("  ✓  No findings")

    # Print hypothesis summary
    confirmed = [h for h in result.hypotheses if h.verdict == "CONFIRMED"]
    likely = [h for h in result.hypotheses if h.verdict == "LIKELY"]
    if confirmed:
        print(f"\n  CONFIRMED: {', '.join(h.code for h in confirmed)}")
    if likely:
        print(f"  LIKELY:    {', '.join(h.code for h in likely)}")

    print(f"\n  Elapsed: {elapsed:.0f} ms")
    print(f"  Artifacts written to: {output_dir}")

    if verbose:
        summary = output_dir / "summary.txt"
        if summary.exists():
            print("\n" + summary.read_text(encoding="utf-8"))

    return 0 if not result.critical_findings else 1


def _run_all(
    run_root: Path,
    run_count: int = 1,
    verbose: bool = False,
) -> int:
    """Run all 10 scenarios sequentially."""
    failures = 0
    for name in _ALL_SCENARIOS:
        out = run_root / name
        rc = _run_scenario(name, out, run_count=run_count, verbose=verbose)
        failures += rc

    print(f"\n{'═'*60}")
    print(f"  All scenarios complete.  Failures: {failures}/{len(_ALL_SCENARIOS)}")
    print(f"{'═'*60}")
    return 0 if failures == 0 else 1


def _replay(events_jsonl: Path, output_dir: Path, verbose: bool = False) -> int:
    """Replay a saved events.jsonl through the analysis pipeline."""
    from tests.diagnostics.event_log import load_from_jsonl
    from tests.diagnostics.failure_detector import detect_all, severity_order
    from tests.diagnostics.hypothesis_engine import HypothesisEngine
    from tests.diagnostics.state_machine import StateMachineReconstructor
    from tests.diagnostics.report_writer import ReportWriter, RunMeta
    from tests.diagnostics.kpi_collector import KpiCollector

    print(f"\n  Replaying: {events_jsonl}")
    events = load_from_jsonl(events_jsonl)
    print(f"  {len(events)} events loaded")

    output_dir.mkdir(parents=True, exist_ok=True)

    sm = StateMachineReconstructor()
    sm.feed(events)

    # KpiCollector in replay mode: no spy wrappers, just derive from events
    from tests.diagnostics.event_log import EventLog
    log = EventLog(output_dir=output_dir)
    for ev in events:
        log._events.append(ev)
    kpi = KpiCollector(log=log)
    kpis = kpi.collect()

    findings = detect_all(events, kpis, sm.machines(), scenario_run_count=1)
    findings.sort(key=severity_order)
    engine = HypothesisEngine(run_count=1, scenario_name="replay")
    hypotheses = engine.score_all(kpis, findings, events=events)

    meta = RunMeta(
        scenario_name="replay",
        scenario_type="replay",
        started_at=events[0].wall_ts if events else 0,
        source_file=str(events_jsonl),
    )
    writer = ReportWriter(output_dir=output_dir)
    writer.write_run_meta(meta)
    writer.write_kpis(kpis)
    writer.write_findings(findings)
    writer.write_hypotheses(hypotheses)
    writer.write_state_machines(sm.summary())
    writer.write_full_summary(meta=meta, kpis=kpis, findings=findings, hypotheses=hypotheses)
    writer.mark_ended(meta)

    if verbose:
        summary = output_dir / "summary.txt"
        if summary.exists():
            print(summary.read_text(encoding="utf-8"))

    return 0


def _compare(dir_a: Path, dir_b: Path, output_dir: Path) -> int:
    """Load kpis.json from two run directories and print a diff table."""
    from tests.diagnostics.comparison import compare_runs, format_diff

    ka = dir_a / "kpis.json"
    kb = dir_b / "kpis.json"
    for p in (ka, kb):
        if not p.exists():
            print(f"ERROR: {p} not found", file=sys.stderr)
            return 1

    kpis_a = json.loads(ka.read_text())
    kpis_b = json.loads(kb.read_text())

    result = compare_runs(mr_kpis=kpis_a, ct_kpis=kpis_b)
    output_dir.mkdir(parents=True, exist_ok=True)
    result.write_json(output_dir / "comparison.json")

    print(format_diff(result))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FAST Viewer Automated Diagnostic Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scenario", metavar="NAME", help="Single scenario to run")
    group.add_argument("--all", action="store_true", help="Run all 10 scenarios")
    group.add_argument("--replay", metavar="PATH", help="Replay saved events.jsonl")
    group.add_argument("--compare", nargs=2, metavar=("DIR_A", "DIR_B"),
                       help="Diff KPIs from two run directories")

    parser.add_argument("--output-dir", metavar="DIR",
                        help="Artifact output directory (default: runs/<scenario>)")
    parser.add_argument("--run-count", type=int, default=1, metavar="N",
                        help="Repetition index for multi-run scenarios (default: 1)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print summary.txt after each run")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI colour in output")

    args = parser.parse_args()

    if args.output_dir:
        base_dir = Path(args.output_dir)
    else:
        base_dir = _DEFAULT_RUN_ROOT

    rc = 0
    if args.scenario:
        out = base_dir / args.scenario if not args.output_dir else base_dir
        rc = _run_scenario(args.scenario, out, run_count=args.run_count, verbose=args.verbose)

    elif args.all:
        rc = _run_all(base_dir, run_count=args.run_count, verbose=args.verbose)

    elif args.replay:
        out = base_dir / "replay" if not args.output_dir else base_dir
        rc = _replay(Path(args.replay), out, verbose=args.verbose)

    elif args.compare:
        out = base_dir / "comparison" if not args.output_dir else base_dir
        rc = _compare(Path(args.compare[0]), Path(args.compare[1]), out)

    sys.exit(rc)


if __name__ == "__main__":
    main()
