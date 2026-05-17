"""
Run UI + Window + PySide + Button Evaluation Bundle

Evaluation-only helper that executes the UI audit and optional validation gates,
then writes an aggregate bundle JSON for repeatable cross-PC comparison.

Usage:
    python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py
    python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --tag 2026-05-17_phaseA2
    python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --run-logging-lint --run-dm-tests
    python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --summary-only
    python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --fail-on-ui-kpi-regression
    python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --baseline-bundle-json generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step1.json
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
    cur = current.get("ui_summary", {})
    base = baseline.get("ui_summary", {})
    return {
        "baseline_tag": baseline.get("tag", ""),
        "print_calls_delta": _to_int(cur.get("print_calls", 0)) - _to_int(base.get("print_calls", 0)),
        "blocking_candidates_delta": _to_int(cur.get("blocking_candidates", 0)) - _to_int(base.get("blocking_candidates", 0)),
        "pyside_connect_lambda_calls_delta": _to_int(cur.get("pyside_connect_lambda_calls", 0)) - _to_int(base.get("pyside_connect_lambda_calls", 0)),
        "qtimer_singleshot_calls_delta": _to_int(cur.get("qtimer_singleshot_calls", 0)) - _to_int(base.get("qtimer_singleshot_calls", 0)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run UI/window/PySide/button diagnostics bundle")
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
        "--summary-only",
        action="store_true",
        help="Print compact bundle summary instead of full tool outputs",
    )
    parser.add_argument(
        "--fail-on-ui-kpi-regression",
        action="store_true",
        help="Fail when UI KPI guard thresholds are violated",
    )
    parser.add_argument(
        "--expected-pyside-connect-lambda-calls",
        type=int,
        default=77,
        help="Expected pyside_connect_lambda_calls count for KPI regression guard",
    )
    parser.add_argument(
        "--expected-blocking-candidates",
        type=int,
        default=5,
        help="Expected blocking_candidates count for KPI regression guard",
    )
    parser.add_argument(
        "--baseline-bundle-json",
        default="",
        help="Optional prior UI bundle JSON for delta comparison",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    audit_json = output_dir / f"ui_window_pyside_button_audit_bundle_{args.tag}.json"
    bundle_json = output_dir / f"ui_window_pyside_button_evaluation_bundle_{args.tag}.json"

    audit_cmd = [
        sys.executable,
        str(ROOT / "tools" / "diagnostics" / "ui_window_pyside_button_evaluation_audit.py"),
        "--json-out",
        str(audit_json),
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

    print("[UI_BUNDLE] Running UI/window/PySide/button audit...")
    audit_res = _run_command(audit_cmd)
    _emit_command_output("[UI_BUNDLE][audit]", audit_res, args.summary_only)
    if audit_res.returncode != 0:
        return audit_res.returncode

    lint_status = {
        "enabled": bool(args.run_logging_lint),
        "returncode": None,
        "passed": None,
    }
    if args.run_logging_lint:
        print("[UI_BUNDLE] Running structured logging lint...")
        lint_res = _run_command(lint_cmd)
        _emit_command_output("[UI_BUNDLE][lint]", lint_res, args.summary_only)
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
        print("[UI_BUNDLE] Running DM test suite...")
        dm_res = _run_command(dm_tests_cmd)
        _emit_command_output("[UI_BUNDLE][dm]", dm_res, args.summary_only)
        dm_test_status = {
            "enabled": True,
            "returncode": dm_res.returncode,
            "passed": dm_res.returncode == 0,
        }
        if dm_res.returncode != 0:
            return dm_res.returncode

    audit_payload = _load_json(audit_json)

    ui_summary = {
        "scanned_files": _to_int(audit_payload.get("scanned_files", 0)),
        "print_calls": len(audit_payload.get("print_calls", [])),
        "blocking_candidates": len(audit_payload.get("blocking_candidates", [])),
        "pyside_connect_calls": len(audit_payload.get("pyside_connect_calls", [])),
        "pyside_connect_lambda_calls": len(audit_payload.get("pyside_connect_lambda_calls", [])),
        "pyside_signal_declarations": len(audit_payload.get("pyside_signal_declarations", [])),
        "pyside_slot_decorators": len(audit_payload.get("pyside_slot_decorators", [])),
        "qtimer_singleshot_calls": len(audit_payload.get("qtimer_singleshot_calls", [])),
        "button_instantiations": len(audit_payload.get("button_instantiations", [])),
        "button_clicked_connects": len(audit_payload.get("button_clicked_connects", [])),
        "button_other_connects": len(audit_payload.get("button_other_connects", [])),
        "window_ops": len(audit_payload.get("window_ops", [])),
    }

    bundle_payload = {
        "tag": args.tag,
        "paths": {
            "ui_window_pyside_button_audit": str(audit_json.relative_to(ROOT)).replace("\\", "/"),
        },
        "ui_summary": ui_summary,
        "validation": {
            "structured_logging_lint": lint_status,
            "dm_test_suite": dm_test_status,
        },
    }

    ui_kpi_validation = {
        "enabled": bool(args.fail_on_ui_kpi_regression),
        "expected": {
            "pyside_connect_lambda_calls": int(args.expected_pyside_connect_lambda_calls),
            "blocking_candidates": int(args.expected_blocking_candidates),
        },
        "actual": {
            "pyside_connect_lambda_calls": ui_summary["pyside_connect_lambda_calls"],
            "blocking_candidates": ui_summary["blocking_candidates"],
        },
        "passed": None,
        "failed_checks": [],
    }
    if ui_kpi_validation["actual"]["pyside_connect_lambda_calls"] != ui_kpi_validation["expected"]["pyside_connect_lambda_calls"]:
        ui_kpi_validation["failed_checks"].append("pyside_connect_lambda_calls")
    if ui_kpi_validation["actual"]["blocking_candidates"] != ui_kpi_validation["expected"]["blocking_candidates"]:
        ui_kpi_validation["failed_checks"].append("blocking_candidates")
    ui_kpi_validation["passed"] = len(ui_kpi_validation["failed_checks"]) == 0
    bundle_payload["validation"]["ui_kpi_regression"] = ui_kpi_validation

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
            "[UI_BUNDLE][SUMMARY] "
            f"scanned_files={ui_summary['scanned_files']} "
            f"lambda_connects={ui_summary['pyside_connect_lambda_calls']} "
            f"blocking_candidates={ui_summary['blocking_candidates']}"
        )
        print(
            "[UI_BUNDLE][SUMMARY] "
            f"qtimer_singleshot_calls={ui_summary['qtimer_singleshot_calls']} "
            f"button_clicked_connects={ui_summary['button_clicked_connects']}"
        )
        print(
            "[UI_BUNDLE][SUMMARY] "
            f"lint_passed={bundle_payload['validation']['structured_logging_lint']['passed']} "
            f"dm_passed={bundle_payload['validation']['dm_test_suite']['passed']}"
        )
        if args.fail_on_ui_kpi_regression:
            print(
                "[UI_BUNDLE][SUMMARY] "
                f"ui_kpi_passed={bundle_payload['validation']['ui_kpi_regression']['passed']} "
                f"failed_checks={bundle_payload['validation']['ui_kpi_regression']['failed_checks']}"
            )
        if args.baseline_bundle_json:
            bc = bundle_payload["baseline_comparison"]
            if bc.get("loaded"):
                d = bc.get("delta", {})
                print(
                    "[UI_BUNDLE][SUMMARY] "
                    f"vs_baseline(lambda={d.get('pyside_connect_lambda_calls_delta')}, "
                    f"blocking={d.get('blocking_candidates_delta')}, "
                    f"qtimer={d.get('qtimer_singleshot_calls_delta')})"
                )
            else:
                print("[UI_BUNDLE][SUMMARY] baseline comparison skipped: baseline JSON not loaded")

    print(f"[UI_BUNDLE] Bundle JSON written to: {bundle_json}")

    if args.fail_on_ui_kpi_regression and not bundle_payload["validation"]["ui_kpi_regression"]["passed"]:
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
