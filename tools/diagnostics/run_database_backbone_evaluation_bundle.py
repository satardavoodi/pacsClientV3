"""
Run Database Backbone Evaluation Bundle

Evaluation helper that audits database backbone usage patterns and optionally
runs validation gates (DB tests, DM tests, logging lint).

Usage:
    python tools/diagnostics/run_database_backbone_evaluation_bundle.py
    python tools/diagnostics/run_database_backbone_evaluation_bundle.py --tag 2026-05-17_phaseD1
    python tools/diagnostics/run_database_backbone_evaluation_bundle.py --run-db-tests --run-dm-tests
    python tools/diagnostics/run_database_backbone_evaluation_bundle.py --summary-only
    python tools/diagnostics/run_database_backbone_evaluation_bundle.py --fail-on-db-kpi-regression
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _emit_command_output(prefix: str, res: subprocess.CompletedProcess[str], summary_only: bool) -> None:
    if not summary_only:
        if res.stdout:
            print(res.stdout.rstrip())
        if res.stderr:
            print(res.stderr.rstrip())
        return

    if res.stderr:
        print(f"{prefix} stderr: {res.stderr.strip()}")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _scan_metrics() -> dict:
    db_files = [
        p for p in (ROOT / "database").glob("*.py") if p.name not in {"__init__.py"}
    ]

    db_print_calls = 0
    db_get_db_connection_calls = 0
    db_commit_calls = 0
    db_sqlite_connect_calls = 0

    for path in db_files:
        txt = _read_text(path)
        db_print_calls += txt.count("print(")
        db_get_db_connection_calls += txt.count("get_db_connection(")
        db_commit_calls += txt.count("conn.commit(")
        db_sqlite_connect_calls += txt.count("sqlite3.connect(")

    direct_sqlite_connect_locations: list[str] = []
    direct_sqlite_connect_categories: dict[str, int] = {
        "database_pool_core": 0,
        "shared_db_migration": 0,
        "offline_cloud_packaging": 0,
        "zeta_cache_db": 0,
        "echomind_memory_db": 0,
        "module_system_pool": 0,
        "other": 0,
    }
    all_get_db_connection_calls = 0

    for top in ("database", "modules", "PacsClient"):
        base = ROOT / top
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            if "/tests/" in rel or rel.startswith("tests/"):
                continue
            if rel.startswith("builder/plugin package/"):
                continue
            if "/build/python-install/" in rel:
                continue
            txt = _read_text(path)
            all_get_db_connection_calls += txt.count("get_db_connection(")
            if "sqlite3.connect(" in txt:
                direct_sqlite_connect_locations.append(rel)
                if rel == "database/_pool.py":
                    direct_sqlite_connect_categories["database_pool_core"] += 1
                elif rel == "PacsClient/utils/data_paths.py":
                    direct_sqlite_connect_categories["shared_db_migration"] += 1
                elif rel == "PacsClient/utils/offline_cloud.py":
                    direct_sqlite_connect_categories["offline_cloud_packaging"] += 1
                elif rel == "modules/zeta_boost/disk_cache.py":
                    direct_sqlite_connect_categories["zeta_cache_db"] += 1
                elif rel == "modules/EchoMind/secretary/memory/memory_store.py":
                    direct_sqlite_connect_categories["echomind_memory_db"] += 1
                elif rel == "modules/module_system/module_manager.py":
                    direct_sqlite_connect_categories["module_system_pool"] += 1
                else:
                    direct_sqlite_connect_categories["other"] += 1

    return {
        "database_file_count": len(db_files),
        "db_print_calls": db_print_calls,
        "db_get_db_connection_calls": db_get_db_connection_calls,
        "db_commit_calls": db_commit_calls,
        "db_sqlite_connect_calls": db_sqlite_connect_calls,
        "all_get_db_connection_calls": all_get_db_connection_calls,
        "direct_sqlite_connect_count": len(direct_sqlite_connect_locations),
        "direct_sqlite_connect_categories": direct_sqlite_connect_categories,
        "direct_sqlite_connect_locations": sorted(direct_sqlite_connect_locations),
    }


def _build_baseline_delta(current: dict, baseline: dict) -> dict:
    cur = current.get("db_summary", {})
    base = baseline.get("db_summary", {})
    return {
        "baseline_tag": baseline.get("tag", ""),
        "db_print_calls_delta": int(cur.get("db_print_calls", 0)) - int(base.get("db_print_calls", 0)),
        "db_get_db_connection_calls_delta": int(cur.get("db_get_db_connection_calls", 0)) - int(base.get("db_get_db_connection_calls", 0)),
        "direct_sqlite_connect_count_delta": int(cur.get("direct_sqlite_connect_count", 0)) - int(base.get("direct_sqlite_connect_count", 0)),
    }


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run database backbone diagnostics bundle")
    parser.add_argument(
        "--tag",
        default=datetime.now().strftime("%Y-%m-%d_%H%M%S"),
        help="Tag suffix for output files",
    )
    parser.add_argument(
        "--output-dir",
        default="generated-files/benchmarks",
        help="Output directory for generated benchmark files",
    )
    parser.add_argument(
        "--run-db-tests",
        action="store_true",
        help="Run database test suite and include result in bundle summary",
    )
    parser.add_argument(
        "--run-dm-tests",
        action="store_true",
        help="Run DM regression suite and include result in bundle summary",
    )
    parser.add_argument(
        "--run-logging-lint",
        action="store_true",
        help="Run structured logging lint and include result in bundle summary",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print compact bundle summary instead of full command outputs",
    )
    parser.add_argument(
        "--fail-on-db-kpi-regression",
        action="store_true",
        help="Fail when DB KPI guard thresholds are violated",
    )
    parser.add_argument(
        "--expected-db-print-calls",
        type=int,
        default=0,
        help="Expected print() call count in database/*.py for KPI guard",
    )
    parser.add_argument(
        "--expected-direct-sqlite-connect-count",
        type=int,
        default=4,
        help="Expected direct sqlite3.connect callsite count across production paths for KPI guard",
    )
    parser.add_argument(
        "--baseline-bundle-json",
        default="",
        help="Optional prior database bundle JSON for delta comparison",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    bundle_json = output_dir / f"database_backbone_evaluation_bundle_{args.tag}.json"

    db_tests_cmd = [
        sys.executable,
        "tests/database/run_db_test.py",
    ]
    dm_tests_cmd = [
        sys.executable,
        "tests/download_manager/run_dm_test.py",
    ]
    lint_cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/utils/test_structured_logging_lint.py",
        "-q",
    ]

    db_test_status = {
        "enabled": bool(args.run_db_tests),
        "returncode": None,
        "passed": None,
    }
    if args.run_db_tests:
        print("[DB_BUNDLE] Running database test suite...")
        db_res = _run_command(db_tests_cmd)
        _emit_command_output("[DB_BUNDLE][db_tests]", db_res, args.summary_only)
        db_test_status = {
            "enabled": True,
            "returncode": db_res.returncode,
            "passed": db_res.returncode == 0,
        }
        if db_res.returncode != 0:
            return db_res.returncode

    dm_test_status = {
        "enabled": bool(args.run_dm_tests),
        "returncode": None,
        "passed": None,
    }
    if args.run_dm_tests:
        print("[DB_BUNDLE] Running DM test suite...")
        dm_res = _run_command(dm_tests_cmd)
        _emit_command_output("[DB_BUNDLE][dm_tests]", dm_res, args.summary_only)
        dm_test_status = {
            "enabled": True,
            "returncode": dm_res.returncode,
            "passed": dm_res.returncode == 0,
        }
        if dm_res.returncode != 0:
            return dm_res.returncode

    lint_status = {
        "enabled": bool(args.run_logging_lint),
        "returncode": None,
        "passed": None,
    }
    if args.run_logging_lint:
        print("[DB_BUNDLE] Running structured logging lint...")
        lint_res = _run_command(lint_cmd)
        _emit_command_output("[DB_BUNDLE][lint]", lint_res, args.summary_only)
        lint_status = {
            "enabled": True,
            "returncode": lint_res.returncode,
            "passed": lint_res.returncode == 0,
        }
        if lint_res.returncode != 0:
            return lint_res.returncode

    metrics = _scan_metrics()

    payload = {
        "tag": args.tag,
        "paths": {
            "db_results": "tests/database/db_results.txt",
            "dm_results": "tests/download_manager/dm_results.txt",
        },
        "db_summary": metrics,
        "validation": {
            "db_test_suite": db_test_status,
            "dm_test_suite": dm_test_status,
            "structured_logging_lint": lint_status,
        },
    }

    db_kpi_validation = {
        "enabled": bool(args.fail_on_db_kpi_regression),
        "expected": {
            "db_print_calls": int(args.expected_db_print_calls),
            "direct_sqlite_connect_count": int(args.expected_direct_sqlite_connect_count),
        },
        "actual": {
            "db_print_calls": int(metrics["db_print_calls"]),
            "direct_sqlite_connect_count": int(metrics["direct_sqlite_connect_count"]),
        },
        "passed": None,
        "failed_checks": [],
    }
    if db_kpi_validation["actual"]["db_print_calls"] != db_kpi_validation["expected"]["db_print_calls"]:
        db_kpi_validation["failed_checks"].append("db_print_calls")
    if db_kpi_validation["actual"]["direct_sqlite_connect_count"] != db_kpi_validation["expected"]["direct_sqlite_connect_count"]:
        db_kpi_validation["failed_checks"].append("direct_sqlite_connect_count")
    db_kpi_validation["passed"] = len(db_kpi_validation["failed_checks"]) == 0
    payload["validation"]["db_kpi_regression"] = db_kpi_validation

    baseline_delta = {
        "enabled": False,
        "baseline_path": "",
        "loaded": False,
        "delta": {},
    }
    if args.baseline_bundle_json:
        baseline_path = Path(args.baseline_bundle_json)
        if not baseline_path.is_absolute():
            baseline_path = ROOT / baseline_path
        baseline_payload = _load_json(baseline_path)
        baseline_delta = {
            "enabled": True,
            "baseline_path": str(baseline_path),
            "loaded": bool(baseline_payload),
            "delta": _build_baseline_delta(payload, baseline_payload) if baseline_payload else {},
        }
    payload["baseline_comparison"] = baseline_delta

    bundle_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if args.summary_only:
        print(
            "[DB_BUNDLE][SUMMARY] "
            f"db_print_calls={metrics['db_print_calls']} "
            f"db_get_db_connection_calls={metrics['db_get_db_connection_calls']} "
            f"direct_sqlite_connect_count={metrics['direct_sqlite_connect_count']}"
        )
        print(
            "[DB_BUNDLE][SUMMARY] "
            f"db_tests={db_test_status['passed']} "
            f"dm_tests={dm_test_status['passed']} "
            f"lint={lint_status['passed']} "
            f"kpi_passed={db_kpi_validation['passed']}"
        )

    print(f"[DB_BUNDLE] Bundle JSON written to: {bundle_json}")

    if args.fail_on_db_kpi_regression and not db_kpi_validation["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
