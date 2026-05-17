"""
Cross-part harmony evaluator for Startup + UI/UX/Button + Download Manager integration.

This tool consumes existing startup and UI evaluation bundle JSON artifacts and
produces a compact, gateable harmony summary for cross-PC and regression checks.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _bool(value: Any) -> bool:
    return bool(value)


def _validation_passed(bundle: dict[str, Any], key: str) -> bool:
    return _bool(bundle.get("validation", {}).get(key, {}).get("passed", False))


def _summary_value(bundle: dict[str, Any], section: str, key: str, default: Any = None) -> Any:
    return bundle.get(section, {}).get(key, default)


def _build_result(tag: str, startup_bundle_path: Path, ui_bundle_path: Path) -> dict[str, Any]:
    startup = _load_json(startup_bundle_path)
    ui = _load_json(ui_bundle_path)

    startup_print_calls = _summary_value(startup, "startup_warmup_summary", "print_calls_startup", None)
    startup_blocking = _summary_value(startup, "startup_warmup_summary", "blocking_candidates_startup", None)
    startup_qtimer = _summary_value(startup, "startup_warmup_summary", "qtimer_singleshot_startup", None)

    ui_lambda = _summary_value(ui, "ui_summary", "pyside_connect_lambda_calls", None)
    ui_blocking = _summary_value(ui, "ui_summary", "blocking_candidates", None)
    ui_qtimer = _summary_value(ui, "ui_summary", "qtimer_singleshot_calls", None)

    checks: dict[str, bool] = {
        "startup_logging_lint_passed": _validation_passed(startup, "structured_logging_lint"),
        "startup_dm_tests_passed": _validation_passed(startup, "dm_test_suite"),
        "startup_syntax_passed": _validation_passed(startup, "startup_syntax_check"),
        "startup_kpi_regression_passed": _validation_passed(startup, "startup_kpi_regression"),
        "ui_logging_lint_passed": _validation_passed(ui, "structured_logging_lint"),
        "ui_dm_tests_passed": _validation_passed(ui, "dm_test_suite"),
        "ui_kpi_regression_passed": _validation_passed(ui, "ui_kpi_regression"),
        "startup_print_calls_zero": startup_print_calls == 0,
        "ui_lambda_connect_zero": ui_lambda == 0,
        "blocking_candidate_alignment": startup_blocking is not None and ui_blocking is not None and startup_blocking <= ui_blocking,
        "startup_qtimer_stable_expected_11": startup_qtimer == 11,
    }

    failed_checks = [name for name, passed in checks.items() if not passed]

    return {
        "tag": tag,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "startup_bundle": str(startup_bundle_path),
            "ui_bundle": str(ui_bundle_path),
            "startup_tag": startup.get("tag"),
            "ui_tag": ui.get("tag"),
        },
        "metrics": {
            "startup": {
                "print_calls_startup": startup_print_calls,
                "blocking_candidates_startup": startup_blocking,
                "qtimer_singleshot_startup": startup_qtimer,
            },
            "ui": {
                "pyside_connect_lambda_calls": ui_lambda,
                "blocking_candidates": ui_blocking,
                "qtimer_singleshot_calls": ui_qtimer,
            },
        },
        "checks": checks,
        "summary": {
            "total_checks": len(checks),
            "failed_checks": failed_checks,
            "harmony_passed": len(failed_checks) == 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run cross-part harmony evaluation bundle")
    parser.add_argument("--tag", required=True, help="Tag suffix for output artifact")
    parser.add_argument("--startup-bundle-json", required=True, help="Path to startup evaluation bundle JSON")
    parser.add_argument("--ui-bundle-json", required=True, help="Path to UI evaluation bundle JSON")
    parser.add_argument("--summary-only", action="store_true", help="Print compact summary lines")
    args = parser.parse_args()

    workspace = Path.cwd()
    out_dir = workspace / "generated-files" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)

    startup_path = (workspace / args.startup_bundle_json).resolve() if not Path(args.startup_bundle_json).is_absolute() else Path(args.startup_bundle_json)
    ui_path = (workspace / args.ui_bundle_json).resolve() if not Path(args.ui_bundle_json).is_absolute() else Path(args.ui_bundle_json)

    result = _build_result(args.tag, startup_path, ui_path)
    out_path = out_dir / f"cross_part_harmony_bundle_{args.tag}.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    if args.summary_only:
        print(
            "[HARMONY][SUMMARY]"
            f" startup_print_calls={result['metrics']['startup']['print_calls_startup']}"
            f" ui_lambda_connects={result['metrics']['ui']['pyside_connect_lambda_calls']}"
            f" startup_qtimer={result['metrics']['startup']['qtimer_singleshot_startup']}"
            f" ui_qtimer={result['metrics']['ui']['qtimer_singleshot_calls']}"
        )
        print(
            "[HARMONY][SUMMARY]"
            f" checks_passed={result['summary']['total_checks'] - len(result['summary']['failed_checks'])}/{result['summary']['total_checks']}"
            f" harmony_passed={result['summary']['harmony_passed']}"
            f" failed_checks={result['summary']['failed_checks']}"
        )
    else:
        print(json.dumps(result, indent=2))

    print(f"[HARMONY] Bundle JSON written to: {out_path}")
    return 0 if result["summary"]["harmony_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
