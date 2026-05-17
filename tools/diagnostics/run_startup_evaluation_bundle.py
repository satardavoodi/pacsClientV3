"""
Run Startup Evaluation Bundle

Evaluation-only helper that executes both startup diagnostics scripts and writes
an aggregate bundle JSON for quick cross-PC comparison.

Usage:
    python tools/diagnostics/run_startup_evaluation_bundle.py
    python tools/diagnostics/run_startup_evaluation_bundle.py --tag 2026-05-17_phaseC2
    python tools/diagnostics/run_startup_evaluation_bundle.py --output-dir generated-files/benchmarks
    python tools/diagnostics/run_startup_evaluation_bundle.py --run-logging-lint
    python tools/diagnostics/run_startup_evaluation_bundle.py --run-dm-tests
    python tools/diagnostics/run_startup_evaluation_bundle.py --run-startup-syntax-check
    python tools/diagnostics/run_startup_evaluation_bundle.py --summary-only
    python tools/diagnostics/run_startup_evaluation_bundle.py --fail-on-startup-kpi-regression
    python tools/diagnostics/run_startup_evaluation_bundle.py --baseline-bundle-json generated-files/benchmarks/startup_evaluation_bundle_2026-05-17_phaseC2_step9.json
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


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _build_baseline_delta(current: dict, baseline: dict) -> dict:
    cur_sw = current.get("startup_warmup_summary", {})
    base_sw = baseline.get("startup_warmup_summary", {})
    cur_qt = current.get("qtimer_summary", {})
    base_qt = baseline.get("qtimer_summary", {})

    cur_qtimer_total = _to_int(cur_qt.get("total", 0))
    base_qtimer_total = _to_int(base_qt.get("total", 0))

    cur_import_mode = ((cur_qt.get("startup_import_delay_timer") or {}).get("mode")) or "unknown"
    base_import_mode = ((base_qt.get("startup_import_delay_timer") or {}).get("mode")) or "unknown"

    return {
        "baseline_tag": baseline.get("tag", ""),
        "print_calls_startup_delta": _to_int(cur_sw.get("print_calls_startup", 0)) - _to_int(base_sw.get("print_calls_startup", 0)),
        "blocking_candidates_startup_delta": _to_int(cur_sw.get("blocking_candidates_startup", 0)) - _to_int(base_sw.get("blocking_candidates_startup", 0)),
        "qtimer_singleshot_startup_delta": _to_int(cur_sw.get("qtimer_singleshot_startup", 0)) - _to_int(base_sw.get("qtimer_singleshot_startup", 0)),
        "qtimer_total_delta": cur_qtimer_total - base_qtimer_total,
        "startup_import_delay_mode_changed": cur_import_mode != base_import_mode,
        "startup_import_delay_mode_current": cur_import_mode,
        "startup_import_delay_mode_baseline": base_import_mode,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run startup diagnostics bundle")
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
        "--run-logging-lint",
        action="store_true",
        help="Run structured logging lint gate and include result in bundle summary",
    )
    parser.add_argument(
        "--run-dm-tests",
        action="store_true",
        help="Run DM regression suite and include result in bundle summary",
    )
    parser.add_argument(
        "--run-startup-syntax-check",
        action="store_true",
        help="Run Python syntax check on startup-critical files and include result in bundle summary",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print compact bundle summary instead of full tool outputs",
    )
    parser.add_argument(
        "--fail-on-startup-kpi-regression",
        action="store_true",
        help="Fail when startup KPI guard thresholds are violated",
    )
    parser.add_argument(
        "--expected-qtimer-singleshot-startup",
        type=int,
        default=11,
        help="Expected qtimer_singleshot_startup count for KPI regression guard",
    )
    parser.add_argument(
        "--baseline-bundle-json",
        default="",
        help="Optional prior startup bundle JSON for delta comparison",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    audit_json = output_dir / f"startup_warmup_audit_bundle_{args.tag}.json"
    classifier_json = output_dir / f"startup_qtimer_classification_bundle_{args.tag}.json"
    bundle_json = output_dir / f"startup_evaluation_bundle_{args.tag}.json"

    audit_cmd = [
        sys.executable,
        str(ROOT / "tools" / "diagnostics" / "startup_warmup_evaluation_audit.py"),
        "--json-out",
        str(audit_json),
    ]
    classifier_cmd = [
        sys.executable,
        str(ROOT / "tools" / "diagnostics" / "startup_qtimer_classifier.py"),
        "--json-out",
        str(classifier_json),
    ]
    lint_cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/utils/test_structured_logging_lint.py",
        "-q",
    ]
    dm_tests_cmd = [
        sys.executable,
        "tests/download_manager/run_dm_test.py",
    ]
    startup_syntax_cmd = [
        sys.executable,
        "-m",
        "py_compile",
        "main.py",
        "PacsClient/app_handler.py",
        "PacsClient/pacs/workstation_ui/mainwindow_ui.py",
        "PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py",
    ]

    print("[BUNDLE] Running startup warmup audit...")
    audit_res = _run_command(audit_cmd)
    _emit_command_output("[BUNDLE][audit]", audit_res, args.summary_only)
    if audit_res.returncode != 0:
        return audit_res.returncode

    print("[BUNDLE] Running startup qtimer classifier...")
    classifier_res = _run_command(classifier_cmd)
    _emit_command_output("[BUNDLE][qtimer]", classifier_res, args.summary_only)
    if classifier_res.returncode != 0:
        return classifier_res.returncode

    lint_status = {
        "enabled": bool(args.run_logging_lint),
        "returncode": None,
        "passed": None,
    }
    if args.run_logging_lint:
        print("[BUNDLE] Running structured logging lint...")
        lint_res = _run_command(lint_cmd)
        _emit_command_output("[BUNDLE][lint]", lint_res, args.summary_only)
        lint_status = {
            "enabled": True,
            "returncode": lint_res.returncode,
            "passed": lint_res.returncode == 0,
        }
        if lint_res.returncode != 0:
            return lint_res.returncode

    dm_test_status = {
        "enabled": bool(args.run_dm_tests),
        "returncode": None,
        "passed": None,
    }
    if args.run_dm_tests:
        print("[BUNDLE] Running DM test suite...")
        dm_res = _run_command(dm_tests_cmd)
        _emit_command_output("[BUNDLE][dm]", dm_res, args.summary_only)
        dm_test_status = {
            "enabled": True,
            "returncode": dm_res.returncode,
            "passed": dm_res.returncode == 0,
        }
        if dm_res.returncode != 0:
            return dm_res.returncode

    startup_syntax_status = {
        "enabled": bool(args.run_startup_syntax_check),
        "returncode": None,
        "passed": None,
    }
    if args.run_startup_syntax_check:
        print("[BUNDLE] Running startup syntax check...")
        startup_syntax_res = _run_command(startup_syntax_cmd)
        _emit_command_output("[BUNDLE][syntax]", startup_syntax_res, args.summary_only)
        startup_syntax_status = {
            "enabled": True,
            "returncode": startup_syntax_res.returncode,
            "passed": startup_syntax_res.returncode == 0,
        }
        if startup_syntax_res.returncode != 0:
            return startup_syntax_res.returncode

    audit_payload = _load_json(audit_json)
    classifier_payload = _load_json(classifier_json)

    bundle_payload = {
        "tag": args.tag,
        "paths": {
            "startup_warmup_audit": str(audit_json.relative_to(ROOT)).replace("\\", "/"),
            "startup_qtimer_classification": str(classifier_json.relative_to(ROOT)).replace("\\", "/"),
        },
        "startup_warmup_summary": {
            "print_calls_startup": len(audit_payload.get("print_calls_startup", [])),
            "blocking_candidates_startup": len(audit_payload.get("blocking_candidates_startup", [])),
            "qtimer_singleshot_startup": len(audit_payload.get("qtimer_singleshot_startup", [])),
            "lazy_import_helpers": len(audit_payload.get("lazy_import_helpers", [])),
            "startup_import_delay": audit_payload.get("startup_import_delay", {}),
        },
        "qtimer_summary": {
            "total": classifier_payload.get("total", 0),
            "startup_import_delay_timer": classifier_payload.get("startup_import_delay_timer", {}),
        },
        "validation": {
            "structured_logging_lint": lint_status,
            "dm_test_suite": dm_test_status,
            "startup_syntax_check": startup_syntax_status,
        },
    }

    startup_kpi_validation = {
        "enabled": bool(args.fail_on_startup_kpi_regression),
        "expected": {
            "print_calls_startup": 0,
            "qtimer_singleshot_startup": int(args.expected_qtimer_singleshot_startup),
        },
        "actual": {
            "print_calls_startup": bundle_payload["startup_warmup_summary"]["print_calls_startup"],
            "qtimer_singleshot_startup": bundle_payload["startup_warmup_summary"]["qtimer_singleshot_startup"],
        },
        "passed": None,
        "failed_checks": [],
    }

    if startup_kpi_validation["actual"]["print_calls_startup"] != startup_kpi_validation["expected"]["print_calls_startup"]:
        startup_kpi_validation["failed_checks"].append("print_calls_startup")
    if startup_kpi_validation["actual"]["qtimer_singleshot_startup"] != startup_kpi_validation["expected"]["qtimer_singleshot_startup"]:
        startup_kpi_validation["failed_checks"].append("qtimer_singleshot_startup")

    startup_kpi_validation["passed"] = len(startup_kpi_validation["failed_checks"]) == 0
    bundle_payload["validation"]["startup_kpi_regression"] = startup_kpi_validation

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
            "delta": _build_baseline_delta(bundle_payload, baseline_payload) if baseline_payload else {},
        }
    bundle_payload["baseline_comparison"] = baseline_delta

    bundle_json.write_text(json.dumps(bundle_payload, indent=2), encoding="utf-8")
    if args.summary_only:
        print(
            "[BUNDLE][SUMMARY] "
            f"print_calls_startup={bundle_payload['startup_warmup_summary']['print_calls_startup']} "
            f"blocking_candidates_startup={bundle_payload['startup_warmup_summary']['blocking_candidates_startup']} "
            f"qtimer_singleshot_startup={bundle_payload['startup_warmup_summary']['qtimer_singleshot_startup']}"
        )
        print(
            "[BUNDLE][SUMMARY] "
            f"qtimer_total={bundle_payload['qtimer_summary']['total']} "
            f"startup_import_delay_mode={bundle_payload['qtimer_summary']['startup_import_delay_timer'].get('mode', 'unknown')}"
        )
        print(
            "[BUNDLE][SUMMARY] "
            f"lint_passed={bundle_payload['validation']['structured_logging_lint']['passed']} "
            f"dm_passed={bundle_payload['validation']['dm_test_suite']['passed']} "
            f"syntax_passed={bundle_payload['validation']['startup_syntax_check']['passed']}"
        )
        if args.fail_on_startup_kpi_regression:
            print(
                "[BUNDLE][SUMMARY] "
                f"startup_kpi_passed={bundle_payload['validation']['startup_kpi_regression']['passed']} "
                f"failed_checks={bundle_payload['validation']['startup_kpi_regression']['failed_checks']}"
            )
        if args.baseline_bundle_json:
            bc = bundle_payload["baseline_comparison"]
            if bc.get("loaded"):
                d = bc.get("delta", {})
                print(
                    "[BUNDLE][SUMMARY] "
                    f"vs_baseline(print={d.get('print_calls_startup_delta')}, "
                    f"blocking={d.get('blocking_candidates_startup_delta')}, "
                    f"qtimer={d.get('qtimer_singleshot_startup_delta')}, "
                    f"mode_changed={d.get('startup_import_delay_mode_changed')})"
                )
            else:
                print("[BUNDLE][SUMMARY] baseline comparison skipped: baseline JSON not loaded")
    print(f"[BUNDLE] Bundle JSON written to: {bundle_json}")

    if args.fail_on_startup_kpi_regression and not bundle_payload["validation"]["startup_kpi_regression"]["passed"]:
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
