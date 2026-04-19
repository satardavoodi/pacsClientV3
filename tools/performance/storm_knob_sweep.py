from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS = REPO_ROOT / "tools" / "performance" / "clearcanvas_aipacs_kpi_harness.py"
DEFAULT_SCENARIO_FILE = REPO_ROOT / "tests" / "performance" / "clearcanvas_aipacs_scenarios.json"

OVERLAP_SCENARIO = "aipacs_live_download_overlap"
COMMON_SCENARIO = "common_local_viewing"

LOWER_IS_BETTER = (
    "first_image_visible_ms",
    "set_slice_present_p95_ms",
    "set_slice_present_max_ms",
    "cpu_p95_pct",
    "slow_frame_count_16ms",
    "thread_count_p95",
)

CLEARCANVAS_TOLERANCE_METRICS = (
    "first_image_visible_ms",
    "set_slice_present_p95_ms",
    "cpu_p95_pct",
)


@dataclass(frozen=True)
class SweepProfile:
    key: str
    label: str
    description: str
    env: Dict[str, str]


SWEEP_PROFILES: List[SweepProfile] = [
    SweepProfile(
        key="baseline",
        label="Baseline",
        description="Current defaults with no extra environment overrides.",
        env={},
    ),
    SweepProfile(
        key="admit_batch_small",
        label="Admission batch 5",
        description="Smaller non-terminal progressive admission to spread burst shock over more ticks.",
        env={"AIPACS_PROGRESSIVE_ADMIT_BATCH": "5"},
    ),
    SweepProfile(
        key="admit_batch_large",
        label="Admission batch 20",
        description="Larger non-terminal progressive admission to reduce control churn at the cost of bigger visible jumps.",
        env={"AIPACS_PROGRESSIVE_ADMIT_BATCH": "20"},
    ),
    SweepProfile(
        key="lazy_workers_1",
        label="Lazy workers 1",
        description="Force a single lazy decode worker to reduce overlap concurrency and CPU spikes.",
        env={"AIPACS_PYDICOM_SINGLE_WORKER": "1"},
    ),
    SweepProfile(
        key="lazy_workers_2",
        label="Lazy workers 2",
        description="Cap lazy decode workers to 2 to reduce concurrency without full serialization.",
        env={"AIPACS_PYDICOM_LAZY_WORKERS": "2"},
    ),
    SweepProfile(
        key="decode_service_off",
        label="Decode service off",
        description="Disable subprocess decode service to measure whether IPC/process overhead helps or hurts this storm class.",
        env={"AIPACS_DECODE_SERVICE": "0"},
    ),
    SweepProfile(
        key="prefetch_conservative",
        label="Conservative prefetch",
        description="Shrink prefetch radii to reduce background decode pressure during overlap.",
        env={
            "AIPACS_PYDICOM_PREFETCH_RADIUS_IDLE": "6",
            "AIPACS_PYDICOM_PREFETCH_RADIUS_FAST": "2",
            "AIPACS_PYDICOM_PREFETCH_RADIUS_HIGH": "1",
            "AIPACS_PYDICOM_PREFETCH_RADIUS_VERY_HIGH": "1",
        },
    ),
    SweepProfile(
        key="guaranteed_band_tighter",
        label="Guaranteed band 10",
        description="Reduce the guaranteed warm band to lower always-on decode pressure around the cursor.",
        env={"AIPACS_PYDICOM_GUARANTEED_BAND_RADIUS": "10"},
    ),
]


def _default_output_dir() -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return REPO_ROOT / "generated-files" / "benchmarks" / f"storm_knob_sweep_{stamp}"


def get_profile_map() -> Dict[str, SweepProfile]:
    return {p.key: p for p in SWEEP_PROFILES}


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _ratio(current: float, baseline: float) -> float:
    if baseline <= 0:
        return 1.0 if current <= 0 else float("inf")
    return float(current) / float(baseline)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def within_tolerance(aipacs_value: float, clearcanvas_value: float, tolerance: float = 0.10) -> bool:
    if clearcanvas_value <= 0:
        return False
    return float(aipacs_value) <= float(clearcanvas_value) * (1.0 + float(tolerance))


def compute_relative_changes(current: Dict[str, Any], baseline: Dict[str, Any], metrics: Iterable[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for metric in metrics:
        out[metric] = round(
            _ratio(_safe_float(current.get(metric, 0.0)), _safe_float(baseline.get(metric, 0.0))),
            4,
        )
    return out


def compute_storm_index(overlap_current: Dict[str, Any], overlap_baseline: Dict[str, Any]) -> float:
    metrics = (
        "set_slice_present_p95_ms",
        "set_slice_present_max_ms",
        "cpu_p95_pct",
        "slow_frame_count_16ms",
    )
    ratios = [
        _ratio(_safe_float(overlap_current.get(m, 0.0)), _safe_float(overlap_baseline.get(m, 0.0)))
        for m in metrics
    ]
    return round(sum(ratios) / len(ratios), 4)


def compute_balance_index(
    overlap_current: Dict[str, Any],
    overlap_baseline: Dict[str, Any],
    common_current: Dict[str, Any],
    common_baseline: Dict[str, Any],
) -> float:
    storm_index = compute_storm_index(overlap_current, overlap_baseline)
    startup_penalty = _ratio(
        _safe_float(common_current.get("first_image_visible_ms", 0.0)),
        _safe_float(common_baseline.get("first_image_visible_ms", 0.0)),
    )
    common_p95_penalty = _ratio(
        _safe_float(common_current.get("set_slice_present_p95_ms", 0.0)),
        _safe_float(common_baseline.get("set_slice_present_p95_ms", 0.0)),
    )
    return round((0.55 * storm_index) + (0.30 * startup_penalty) + (0.15 * common_p95_penalty), 4)


def discover_clearcanvas_reference(clearcanvas_source_root: Optional[Path]) -> Dict[str, Any]:
    if not clearcanvas_source_root:
        return {}
    root = Path(clearcanvas_source_root)
    desktop_sln = root / "Desktop" / "Desktop.sln"
    imageviewer_sln = root / "ImageViewer" / "ImageViewer.sln"
    desktop_exe_proj = root / "Desktop" / "Executable" / "ClearCanvas.Desktop.Executable.csproj"
    return {
        "source_root": str(root),
        "desktop_solution": str(desktop_sln) if desktop_sln.exists() else None,
        "imageviewer_solution": str(imageviewer_sln) if imageviewer_sln.exists() else None,
        "desktop_executable_project": str(desktop_exe_proj) if desktop_exe_proj.exists() else None,
    }


def _run_headless_profile(
    *,
    python_exe: str,
    dataset: Path,
    scenario: str,
    scenario_file: Path,
    output_path: Path,
    env_overrides: Dict[str, str],
) -> Dict[str, Any]:
    env = os.environ.copy()
    env.update(env_overrides)
    cmd = [
        python_exe,
        str(HARNESS),
        "run-aipacs-headless",
        "--dataset",
        str(dataset),
        "--scenario-file",
        str(scenario_file),
        "--scenario",
        scenario,
        "--output",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, env=env, cwd=str(REPO_ROOT))
    return _load_json(output_path)


def build_summary_rows(
    run_results: List[Dict[str, Any]],
    clearcanvas_payload: Optional[Dict[str, Any]] = None,
    tolerance: float = 0.10,
) -> List[Dict[str, Any]]:
    baseline = next(r for r in run_results if r["profile_key"] == "baseline")
    baseline_overlap = baseline["overlap"]["kpis"]
    baseline_common = baseline["common"]["kpis"]
    cc_kpis = (clearcanvas_payload or {}).get("kpis", {})

    rows: List[Dict[str, Any]] = []
    for result in run_results:
        overlap_kpis = result["overlap"]["kpis"]
        common_kpis = result["common"]["kpis"]
        row = {
            "profile_key": result["profile_key"],
            "label": result["label"],
            "description": result["description"],
            "overlap": overlap_kpis,
            "common": common_kpis,
            "overlap_vs_baseline": compute_relative_changes(overlap_kpis, baseline_overlap, LOWER_IS_BETTER),
            "common_vs_baseline": compute_relative_changes(common_kpis, baseline_common, LOWER_IS_BETTER),
            "storm_index": compute_storm_index(overlap_kpis, baseline_overlap),
            "balance_index": compute_balance_index(overlap_kpis, baseline_overlap, common_kpis, baseline_common),
            "clearcanvas_within_10pct": {},
        }
        if cc_kpis:
            row["clearcanvas_within_10pct"] = {
                metric: within_tolerance(_safe_float(overlap_kpis.get(metric, 0.0)), _safe_float(cc_kpis.get(metric, 0.0)), tolerance)
                for metric in CLEARCANVAS_TOLERANCE_METRICS
                if metric in cc_kpis
            }
        rows.append(row)
    rows.sort(key=lambda r: (r["balance_index"], r["storm_index"]))
    return rows


def summary_to_markdown(
    rows: List[Dict[str, Any]],
    *,
    dataset: Path,
    clearcanvas_reference: Dict[str, Any],
    clearcanvas_payload: Optional[Dict[str, Any]] = None,
) -> str:
    dataset_display = dataset.as_posix()
    lines = [
        "# Storm Knob Sweep",
        "",
        f"- Dataset: `{dataset_display}`",
        f"- AI-PACS overlap scenario: `{OVERLAP_SCENARIO}`",
        f"- AI-PACS common scenario: `{COMMON_SCENARIO}`",
    ]
    if clearcanvas_reference:
        lines.append(f"- ClearCanvas source root: `{clearcanvas_reference.get('source_root')}`")
        if clearcanvas_reference.get("desktop_solution"):
            lines.append(f"- ClearCanvas desktop solution: `{clearcanvas_reference['desktop_solution']}`")
        if clearcanvas_reference.get("imageviewer_solution"):
            lines.append(f"- ClearCanvas image viewer solution: `{clearcanvas_reference['imageviewer_solution']}`")
    if clearcanvas_payload:
        lines.append(f"- ClearCanvas metrics payload: `{clearcanvas_payload.get('viewer', 'ClearCanvas')}`")
    lines.extend([
        "",
        "## Ranked profiles",
        "",
        "| Profile | Storm Index | Balance Index | Overlap P95 ms | Overlap CPU P95 % | Common First Image ms | Common P95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for row in rows:
        lines.append(
            f"| `{row['profile_key']}` | {row['storm_index']} | {row['balance_index']} | "
            f"{_safe_float(row['overlap'].get('set_slice_present_p95_ms')):.2f} | "
            f"{_safe_float(row['overlap'].get('cpu_p95_pct')):.2f} | "
            f"{_safe_float(row['common'].get('first_image_visible_ms')):.2f} | "
            f"{_safe_float(row['common'].get('set_slice_present_p95_ms')):.2f} |"
        )
    lines.extend(["", "## Notes", ""])
    best = rows[0] if rows else None
    if best:
        lines.append(
            f"- Best current balance: `{best['profile_key']}` with balance index {best['balance_index']} and storm index {best['storm_index']}."
        )
    lines.append("- Lower Storm Index is better; it focuses on overlap interaction and CPU behavior versus AI-PACS baseline.")
    lines.append("- Lower Balance Index is better; it rewards storm reduction while penalizing common-path and first-image regressions.")
    lines.append("- ClearCanvas tolerance, when available, is checked with a 10% upper bound for lower-is-better metrics.")
    lines.append("")
    for row in rows:
        lines.append(f"### {row['label']}")
        lines.append("")
        lines.append(f"- {row['description']}")
        lines.append(
            f"- Overlap vs baseline ratios: p95={row['overlap_vs_baseline']['set_slice_present_p95_ms']}, "
            f"max={row['overlap_vs_baseline']['set_slice_present_max_ms']}, "
            f"cpu={row['overlap_vs_baseline']['cpu_p95_pct']}, slow16={row['overlap_vs_baseline']['slow_frame_count_16ms']}"
        )
        lines.append(
            f"- Common vs baseline ratios: first-image={row['common_vs_baseline']['first_image_visible_ms']}, "
            f"p95={row['common_vs_baseline']['set_slice_present_p95_ms']}"
        )
        if row["clearcanvas_within_10pct"]:
            cc_bits = ", ".join(
                f"{metric}={'yes' if ok else 'no'}" for metric, ok in row['clearcanvas_within_10pct'].items()
            )
            lines.append(f"- ClearCanvas within 10%: {cc_bits}")
        lines.append("")
    return "\n".join(lines)


def run_sweep(
    *,
    dataset: Path,
    output_dir: Path,
    python_exe: str,
    profile_keys: List[str],
    scenario_file: Path,
    clearcanvas_source_root: Optional[Path] = None,
    clearcanvas_json: Optional[Path] = None,
    tolerance: float = 0.10,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_map = get_profile_map()
    selected = [profile_map[key] for key in profile_keys]

    run_results: List[Dict[str, Any]] = []
    for profile in selected:
        profile_dir = output_dir / profile.key
        overlap_path = profile_dir / "aipacs_overlap.json"
        common_path = profile_dir / "aipacs_common.json"
        overlap = _run_headless_profile(
            python_exe=python_exe,
            dataset=dataset,
            scenario=OVERLAP_SCENARIO,
            scenario_file=scenario_file,
            output_path=overlap_path,
            env_overrides=profile.env,
        )
        common = _run_headless_profile(
            python_exe=python_exe,
            dataset=dataset,
            scenario=COMMON_SCENARIO,
            scenario_file=scenario_file,
            output_path=common_path,
            env_overrides=profile.env,
        )
        run_results.append(
            {
                "profile_key": profile.key,
                "label": profile.label,
                "description": profile.description,
                "env": profile.env,
                "overlap": overlap,
                "common": common,
            }
        )

    clearcanvas_payload = _load_json(clearcanvas_json) if clearcanvas_json else None
    clearcanvas_reference = discover_clearcanvas_reference(clearcanvas_source_root)
    rows = build_summary_rows(run_results, clearcanvas_payload=clearcanvas_payload, tolerance=tolerance)
    summary = {
        "dataset": str(dataset),
        "scenario_file": str(scenario_file),
        "profiles": run_results,
        "rows": rows,
        "clearcanvas_reference": clearcanvas_reference,
        "clearcanvas_payload": clearcanvas_payload,
        "tolerance": tolerance,
    }
    summary_json = output_dir / "storm_sweep_summary.json"
    summary_md = output_dir / "storm_sweep_summary.md"
    _write_json(summary_json, summary)
    summary_md.write_text(
        summary_to_markdown(
            rows,
            dataset=dataset,
            clearcanvas_reference=clearcanvas_reference,
            clearcanvas_payload=clearcanvas_payload,
        ),
        encoding="utf-8",
    )
    return {
        "summary_json": str(summary_json),
        "summary_md": str(summary_md),
        "rows": rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one-knob-at-a-time storm benchmarks for AI-PACS FAST mode")
    parser.add_argument("--dataset", required=True, help="Path to local DICOM series directory")
    parser.add_argument("--output-dir", default=str(_default_output_dir()))
    parser.add_argument("--python-exe", default=sys.executable)
    parser.add_argument("--scenario-file", default=str(DEFAULT_SCENARIO_FILE))
    parser.add_argument("--profiles", nargs="+", default=[p.key for p in SWEEP_PROFILES])
    parser.add_argument("--clearcanvas-source-root", default="")
    parser.add_argument("--clearcanvas-json", default="")
    parser.add_argument("--tolerance", type=float, default=0.10)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = run_sweep(
        dataset=Path(args.dataset),
        output_dir=Path(args.output_dir),
        python_exe=args.python_exe,
        profile_keys=args.profiles,
        scenario_file=Path(args.scenario_file),
        clearcanvas_source_root=Path(args.clearcanvas_source_root) if args.clearcanvas_source_root else None,
        clearcanvas_json=Path(args.clearcanvas_json) if args.clearcanvas_json else None,
        tolerance=args.tolerance,
    )
    print(result["summary_json"])
    print(result["summary_md"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
