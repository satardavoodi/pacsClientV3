"""
ClearCanvas vs AI-PACS KPI harness.

Purpose:
  - run repeatable headless KPI scenarios on the AI-PACS FAST pipeline
  - monitor an external viewer process such as ClearCanvas during the same steps
  - parse AI-PACS runtime logs for mixed-load orchestration signals
  - compare result files and emit a Markdown report

Expected inputs:
  - scenario JSON from tests/performance/clearcanvas_aipacs_scenarios.json
  - a local DICOM series directory
  - optional AI-PACS log file
  - optional target process name/PID for external monitoring

Side effects:
  - reads DICOM files and logs
  - writes JSON and Markdown reports only

Safe execution:
  - read-only with respect to the dataset and application state
  - no network calls

Owner:
  - viewer/performance
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency in some envs
    psutil = None


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


_FIRST_IMAGE_RE = re.compile(
    r"FAST:first_image_visible .*?total_ms=(?P<total>[0-9.]+)"
)
_SCROLL_RE = re.compile(
    r"\[B3\.8_SCROLL\].*?total_ms=(?P<total>[0-9.]+)\s+"
    r"decode_ms=(?P<decode>[0-9.]+)\s+wl_ms=(?P<wl>[0-9.]+)\s+src=(?P<src>\w+)"
)
_QT_SET_SLICE_RE = re.compile(
    r"qt-viewer-bridge set_slice idx=(?P<slice>\d+)\s+total_ms=(?P<total>[0-9.]+)\s+"
    r"decode=(?P<decode>[0-9.]+)\s+filter=(?P<filter>[0-9.]+)\s+wl=(?P<wl>[0-9.]+)"
)
_FAST_SET_SLICE_STAGE_RE = re.compile(
    r"\[FAST_SET_SLICE_STAGE\]\s+idx=(?P<slice>\d+)\s+total_ms=(?P<total>[0-9.]+)\s+"
    r"prepare_ms=(?P<prepare>[0-9.]+)\s+interaction_prep_ms=(?P<interaction_prep>[0-9.]+)\s+"
    r"frame_ms=(?P<frame>[0-9.]+)\s+display_ms=(?P<display>[0-9.]+)\s+"
    r"annotation_ms=(?P<annotation>[0-9.]+)\s+metrics_ms=(?P<metrics>[0-9.]+)\s+"
    r"ui_lag_ms=(?P<ui_lag>[0-9.]+)\s+fast=(?P<fast>True|False)\s+"
    r"interaction=(?P<interaction>\w+)\s+decode_ms=(?P<decode>[0-9.]+)\s+"
    r"filter_ms=(?P<filter>[0-9.]+)\s+wl_ms=(?P<wl>[0-9.]+)"
)
_FAST_QT_SCROLL_STAGE_RE = re.compile(
    r"\[FAST_QT_SCROLL_STAGE\]\s+target=(?P<slice>\d+)\s+total_ms=(?P<total>[0-9.]+)\s+"
    r"set_slice_ms=(?P<set_slice>[0-9.]+)\s+slider_ms=(?P<slider>[0-9.]+)\s+"
    r"sync_ms=(?P<sync>[0-9.]+)\s+reference_ms=(?P<reference>[0-9.]+)\s+"
    r"drag=(?P<drag>True|False)\s+interaction=(?P<interaction>\w+)"
)
_COMPLETE_RE = re.compile(r"progressive-fast: series=(?P<series>\S+) COMPLETE")
_CACHE_WARM_RE = re.compile(r"progressive-fast: series=(?P<series>\S+) cache-warm dispatched")
_DUPLICATE_TERMINAL_RE = re.compile(r"duplicate terminal progress ignored series=(?P<series>\S+)")
_STACK_DRAG_START_RE = re.compile(r"\[B3\.4_DIAG\] STACK_DRAG_START slice=(?P<slice>\d+)")
_STACK_DRAG_STOP_RE = re.compile(r"\[B3\.4_DIAG\] STACK_DRAG_STOP slice=(?P<slice>\d+)")
_STACK_DRAG_SETTLE_RE = re.compile(r"\[B3\.4_DIAG\] (?:INTERACTION_SETTLED|QT_SCROLL_SETTLE|END_FAST_INTERACTION) slice=(?P<slice>\d+)")
_MANUAL_FIRST_IMAGE_STEP_IDS = {"S2", "S13"}
_MANUAL_SCROLL_STEP_IDS = {"S4", "S5", "S6", "S14"}
_STACK_HITCH_TOTAL_MS = 16.0
_STACK_DECODE_HITCH_DECODE_MS = 8.0


def _percentile(values: Iterable[float], pct: float) -> float:
    data = sorted(float(v) for v in values)
    if not data:
        return 0.0
    if len(data) == 1:
        return data[0]
    idx = (len(data) - 1) * pct / 100.0
    lo = int(idx)
    hi = min(lo + 1, len(data) - 1)
    return data[lo] + (idx - lo) * (data[hi] - data[lo])


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_scenarios(path: Path) -> Dict[str, Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    scenarios = {}
    for scenario in payload.get("scenarios", []):
        scenarios[str(scenario["id"])] = scenario
    return scenarios


def get_scenario(path: Path, scenario_id: str) -> Dict[str, Any]:
    scenarios = load_scenarios(path)
    if scenario_id not in scenarios:
        raise KeyError(f"Unknown scenario '{scenario_id}'. Available: {', '.join(sorted(scenarios))}")
    return scenarios[scenario_id]


def load_benchmark_model(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_block_kpi_model(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@dataclass
class ProcessSample:
    timestamp_s: float
    step_id: str
    cpu_pct: float
    rss_mb: float
    thread_count: int
    read_mb: float
    write_mb: float


def _scenario_duration_s(scenario: Dict[str, Any]) -> float:
    return float(sum(float(step.get("duration_s", 0.0)) for step in scenario.get("steps", [])))


def _step_for_elapsed(scenario: Dict[str, Any], elapsed_s: float) -> str:
    cursor = 0.0
    steps = scenario.get("steps", [])
    for step in steps:
        cursor += float(step.get("duration_s", 0.0))
        if elapsed_s <= cursor:
            return str(step.get("id", "unknown"))
    return str(steps[-1].get("id", "unknown")) if steps else "unknown"


def summarize_process_samples(samples: List[ProcessSample]) -> Dict[str, Any]:
    if not samples:
        return {
            "sample_count": 0,
            "cpu_p50_pct": 0.0,
            "cpu_p95_pct": 0.0,
            "cpu_max_pct": 0.0,
            "rss_peak_mb": 0.0,
            "thread_count_p95": 0.0,
            "thread_count_max": 0,
            "read_mb_delta": 0.0,
            "write_mb_delta": 0.0,
            "steps": {},
        }

    cpu = [s.cpu_pct for s in samples]
    rss = [s.rss_mb for s in samples]
    threads = [float(s.thread_count) for s in samples]
    steps: Dict[str, List[ProcessSample]] = defaultdict(list)
    for sample in samples:
        steps[sample.step_id].append(sample)

    per_step = {}
    for step_id, step_samples in steps.items():
        per_step[step_id] = {
            "cpu_p95_pct": round(_percentile((s.cpu_pct for s in step_samples), 95), 2),
            "rss_peak_mb": round(max((s.rss_mb for s in step_samples), default=0.0), 2),
            "thread_count_max": max((s.thread_count for s in step_samples), default=0),
        }

    return {
        "sample_count": len(samples),
        "cpu_p50_pct": round(_percentile(cpu, 50), 2),
        "cpu_p95_pct": round(_percentile(cpu, 95), 2),
        "cpu_max_pct": round(max(cpu), 2),
        "rss_peak_mb": round(max(rss), 2),
        "thread_count_p95": round(_percentile(threads, 95), 2),
        "thread_count_max": max(int(t) for t in threads),
        "read_mb_delta": round(max(samples[-1].read_mb - samples[0].read_mb, 0.0), 2),
        "write_mb_delta": round(max(samples[-1].write_mb - samples[0].write_mb, 0.0), 2),
        "steps": per_step,
    }


def _resolve_process(*, pid: Optional[int], process_name: Optional[str], wait_timeout_s: float) -> "psutil.Process":
    if psutil is None:  # pragma: no cover - environment dependent
        raise RuntimeError("psutil is required for process monitoring")

    if pid is not None:
        return psutil.Process(int(pid))

    deadline = time.time() + float(wait_timeout_s)
    while time.time() <= deadline:
        candidates = []
        for proc in psutil.process_iter(["name", "create_time"]):
            try:
                name = proc.info.get("name") or ""
                if process_name and name.lower() == process_name.lower():
                    candidates.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if candidates:
            return sorted(candidates, key=lambda p: p.info.get("create_time", 0.0), reverse=True)[0]
        time.sleep(0.5)
    raise RuntimeError(f"Could not find process '{process_name}' within {wait_timeout_s:.1f}s")


def monitor_process_run(
    *,
    scenario: Dict[str, Any],
    pid: Optional[int] = None,
    process_name: Optional[str] = None,
    wait_timeout_s: float = 30.0,
    interval_ms: int = 250,
    label: str = "",
) -> Dict[str, Any]:
    proc = _resolve_process(pid=pid, process_name=process_name, wait_timeout_s=wait_timeout_s)
    proc.cpu_percent(None)

    samples: List[ProcessSample] = []
    total_duration = max(_scenario_duration_s(scenario), 1.0)
    start = time.monotonic()
    end = start + total_duration

    while time.monotonic() <= end:
        try:
            cpu = float(proc.cpu_percent(None))
            mem = proc.memory_info()
            io = proc.io_counters() if hasattr(proc, "io_counters") else None
            elapsed = time.monotonic() - start
            step_id = _step_for_elapsed(scenario, elapsed)
            samples.append(
                ProcessSample(
                    timestamp_s=round(elapsed, 3),
                    step_id=step_id,
                    cpu_pct=cpu,
                    rss_mb=mem.rss / (1024 * 1024),
                    thread_count=proc.num_threads(),
                    read_mb=(io.read_bytes / (1024 * 1024)) if io else 0.0,
                    write_mb=(io.write_bytes / (1024 * 1024)) if io else 0.0,
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):  # pragma: no cover - runtime dependent
            break
        time.sleep(max(interval_ms, 50) / 1000.0)

    return {
        "viewer": label or process_name or f"pid:{proc.pid}",
        "mode": "external-process-monitor",
        "scenario_id": scenario.get("id"),
        "scenario_title": scenario.get("title"),
        "process_name": proc.name(),
        "pid": proc.pid,
        "process_summary": summarize_process_samples(samples),
        "samples": [asdict(s) for s in samples],
    }


def parse_aipacs_log_text(text: str) -> Dict[str, Any]:
    first_image_ms: List[float] = []
    scroll_total_ms: List[float] = []
    scroll_decode_ms: List[float] = []
    src_counts: Counter[str] = Counter()
    complete_counts: Counter[str] = Counter()
    cache_warm_counts: Counter[str] = Counter()
    duplicate_terminal_counts: Counter[str] = Counter()
    stack_drag_active = False
    stack_drag_total_ms: List[float] = []
    stack_drag_decode_ms: List[float] = []
    stack_drag_decode_hitch_total_ms: List[float] = []
    stack_drag_nondecode_hitch_total_ms: List[float] = []
    set_slice_stage_hitch_count = 0
    set_slice_stage_frame_max_ms = 0.0
    set_slice_stage_display_max_ms = 0.0
    set_slice_stage_annotation_max_ms = 0.0
    set_slice_stage_metrics_max_ms = 0.0
    set_slice_stage_ui_lag_max_ms = 0.0
    qt_scroll_stage_hitch_count = 0
    qt_scroll_stage_set_slice_max_ms = 0.0
    qt_scroll_stage_slider_max_ms = 0.0
    qt_scroll_stage_sync_max_ms = 0.0
    qt_scroll_stage_reference_max_ms = 0.0

    for line in text.splitlines():
        if _STACK_DRAG_START_RE.search(line):
            stack_drag_active = True
        elif _STACK_DRAG_STOP_RE.search(line) or _STACK_DRAG_SETTLE_RE.search(line):
            stack_drag_active = False

        m = _FIRST_IMAGE_RE.search(line)
        if m:
            first_image_ms.append(float(m.group("total")))
        m = _SCROLL_RE.search(line)
        if m:
            total_ms = float(m.group("total"))
            decode_ms = float(m.group("decode"))
            scroll_total_ms.append(total_ms)
            scroll_decode_ms.append(decode_ms)
            src_counts[str(m.group("src"))] += 1
            if stack_drag_active:
                stack_drag_total_ms.append(total_ms)
                stack_drag_decode_ms.append(decode_ms)
                if total_ms >= _STACK_HITCH_TOTAL_MS:
                    if decode_ms >= _STACK_DECODE_HITCH_DECODE_MS:
                        stack_drag_decode_hitch_total_ms.append(total_ms)
                    elif decode_ms == 0.0:
                        stack_drag_nondecode_hitch_total_ms.append(total_ms)
        m = _QT_SET_SLICE_RE.search(line)
        if m and stack_drag_active:
            total_ms = float(m.group("total"))
            decode_ms = float(m.group("decode"))
            if total_ms >= _STACK_HITCH_TOTAL_MS:
                if decode_ms >= _STACK_DECODE_HITCH_DECODE_MS:
                    stack_drag_decode_hitch_total_ms.append(total_ms)
                elif decode_ms == 0.0:
                    stack_drag_nondecode_hitch_total_ms.append(total_ms)
        m = _FAST_SET_SLICE_STAGE_RE.search(line)
        if m:
            total_ms = float(m.group("total"))
            if total_ms >= _STACK_HITCH_TOTAL_MS:
                set_slice_stage_hitch_count += 1
                set_slice_stage_frame_max_ms = max(set_slice_stage_frame_max_ms, float(m.group("frame")))
                set_slice_stage_display_max_ms = max(set_slice_stage_display_max_ms, float(m.group("display")))
                set_slice_stage_annotation_max_ms = max(set_slice_stage_annotation_max_ms, float(m.group("annotation")))
                set_slice_stage_metrics_max_ms = max(set_slice_stage_metrics_max_ms, float(m.group("metrics")))
                set_slice_stage_ui_lag_max_ms = max(set_slice_stage_ui_lag_max_ms, float(m.group("ui_lag")))
        m = _FAST_QT_SCROLL_STAGE_RE.search(line)
        if m:
            total_ms = float(m.group("total"))
            if total_ms >= _STACK_HITCH_TOTAL_MS:
                qt_scroll_stage_hitch_count += 1
                qt_scroll_stage_set_slice_max_ms = max(qt_scroll_stage_set_slice_max_ms, float(m.group("set_slice")))
                qt_scroll_stage_slider_max_ms = max(qt_scroll_stage_slider_max_ms, float(m.group("slider")))
                qt_scroll_stage_sync_max_ms = max(qt_scroll_stage_sync_max_ms, float(m.group("sync")))
                qt_scroll_stage_reference_max_ms = max(qt_scroll_stage_reference_max_ms, float(m.group("reference")))
        m = _COMPLETE_RE.search(line)
        if m:
            complete_counts[str(m.group("series"))] += 1
        m = _CACHE_WARM_RE.search(line)
        if m:
            cache_warm_counts[str(m.group("series"))] += 1
        m = _DUPLICATE_TERMINAL_RE.search(line)
        if m:
            duplicate_terminal_counts[str(m.group("series"))] += 1

    duplicate_complete = sum(max(0, count - 1) for count in complete_counts.values())
    duplicate_cache_warm = sum(max(0, count - 1) for count in cache_warm_counts.values())
    total_scroll = len(scroll_total_ms)
    decode_zero = sum(1 for value in scroll_decode_ms if value == 0.0)
    total_stack_drag = len(stack_drag_total_ms)
    stack_drag_decode_zero = sum(1 for value in stack_drag_decode_ms if value == 0.0)

    return {
        "first_image_visible_ms": round(_percentile(first_image_ms, 50), 2),
        "first_image_visible_p95_ms": round(_percentile(first_image_ms, 95), 2),
        "set_slice_present_p50_ms": round(_percentile(scroll_total_ms, 50), 2),
        "set_slice_present_p95_ms": round(_percentile(scroll_total_ms, 95), 2),
        "set_slice_present_max_ms": round(max(scroll_total_ms) if scroll_total_ms else 0.0, 2),
        "scroll_sample_count": total_scroll,
        "decode_zero_scroll_ratio_pct": round((decode_zero / total_scroll) * 100.0, 2) if total_scroll else 0.0,
        "surrogate_scroll_ratio_pct": round((src_counts.get("surrogate", 0) / total_scroll) * 100.0, 2) if total_scroll else 0.0,
        "cache_hit_scroll_ratio_pct": round((src_counts.get("hit", 0) / total_scroll) * 100.0, 2) if total_scroll else 0.0,
        "stack_drag_sample_count": total_stack_drag,
        "stack_drag_decode_zero_ratio_pct": round((stack_drag_decode_zero / total_stack_drag) * 100.0, 2) if total_stack_drag else 0.0,
        "stack_drag_decode_hitch_count": len(stack_drag_decode_hitch_total_ms),
        "stack_drag_decode_hitch_p95_ms": round(_percentile(stack_drag_decode_hitch_total_ms, 95), 2),
        "stack_drag_decode_hitch_max_ms": round(max(stack_drag_decode_hitch_total_ms) if stack_drag_decode_hitch_total_ms else 0.0, 2),
        "stack_drag_nondecode_hitch_count": len(stack_drag_nondecode_hitch_total_ms),
        "stack_drag_nondecode_hitch_p95_ms": round(_percentile(stack_drag_nondecode_hitch_total_ms, 95), 2),
        "stack_drag_nondecode_hitch_max_ms": round(max(stack_drag_nondecode_hitch_total_ms) if stack_drag_nondecode_hitch_total_ms else 0.0, 2),
        "set_slice_stage_hitch_count": set_slice_stage_hitch_count,
        "set_slice_stage_frame_max_ms": round(set_slice_stage_frame_max_ms, 2),
        "set_slice_stage_display_max_ms": round(set_slice_stage_display_max_ms, 2),
        "set_slice_stage_annotation_max_ms": round(set_slice_stage_annotation_max_ms, 2),
        "set_slice_stage_metrics_max_ms": round(set_slice_stage_metrics_max_ms, 2),
        "set_slice_stage_ui_lag_max_ms": round(set_slice_stage_ui_lag_max_ms, 2),
        "qt_scroll_stage_hitch_count": qt_scroll_stage_hitch_count,
        "qt_scroll_stage_set_slice_max_ms": round(qt_scroll_stage_set_slice_max_ms, 2),
        "qt_scroll_stage_slider_max_ms": round(qt_scroll_stage_slider_max_ms, 2),
        "qt_scroll_stage_sync_max_ms": round(qt_scroll_stage_sync_max_ms, 2),
        "qt_scroll_stage_reference_max_ms": round(qt_scroll_stage_reference_max_ms, 2),
        "terminal_completion_duplicate_count": duplicate_complete + sum(duplicate_terminal_counts.values()),
        "cache_warm_duplicate_count": duplicate_cache_warm,
        "unique_completed_series_count": len(complete_counts),
        "duplicate_terminal_guard_hits": sum(duplicate_terminal_counts.values()),
    }


def parse_aipacs_log_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {
        "viewer": "AI-PACS",
        "mode": "log-parse",
        "log_path": str(path),
        "log_metrics": parse_aipacs_log_text(text),
    }


def _normalize_headless_kpis(snapshot: Dict[str, Any], process_summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "first_image_visible_ms": round(float(snapshot.get("first_image_ms", 0.0)), 2),
        "set_slice_present_p50_ms": round(float(snapshot.get("set_slice_p50_ms", 0.0)), 2),
        "set_slice_present_p95_ms": round(float(snapshot.get("set_slice_p95_ms", 0.0)), 2),
        "set_slice_present_max_ms": round(float(snapshot.get("set_slice_max_ms", 0.0)), 2),
        "decode_p95_ms": round(float(snapshot.get("decode_p95_ms", 0.0)), 2),
        "frame_render_p95_ms": round(float(snapshot.get("frame_render_p95_ms", 0.0)), 2),
        "cache_hit_ratio_pct": round(float(snapshot.get("cache_hit_ratio_pct", 0.0)), 2),
        "slow_frame_count_16ms": int(snapshot.get("slow_frame_count_16ms", 0)),
        "longest_ui_gap_ms": round(float(snapshot.get("longest_ui_gap_ms", 0.0)), 2),
        "stale_task_ratio": round(float(snapshot.get("stale_task_ratio", 0.0)), 4),
        "cpu_p95_pct": float(process_summary.get("cpu_p95_pct", 0.0)),
        "rss_peak_mb": float(process_summary.get("rss_peak_mb", 0.0)),
        "thread_count_p95": float(process_summary.get("thread_count_p95", 0.0)),
    }


def load_manual_step_results(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def summarize_manual_step_results(
    rows: List[Dict[str, str]],
    *,
    app: str = "clearcanvas",
) -> Dict[str, Any]:
    app_rows = [row for row in rows if str(row.get("app", "")).strip().lower() == app.lower()]
    timed_rows = []
    timings_by_step: Dict[str, List[float]] = defaultdict(list)
    for row in app_rows:
        value = _to_float(row.get("time_ms"))
        if value is None:
            continue
        timed_rows.append(row)
        timings_by_step[str(row.get("step_id", ""))].append(value)

    first_image_values: List[float] = []
    scroll_values: List[float] = []
    for step_id, values in timings_by_step.items():
        if step_id in _MANUAL_FIRST_IMAGE_STEP_IDS:
            first_image_values.extend(values)
        if step_id in _MANUAL_SCROLL_STEP_IDS:
            scroll_values.extend(values)

    step_timings = {}
    for step_id, values in sorted(timings_by_step.items()):
        step_timings[step_id] = {
            "count": len(values),
            "p50_ms": round(_percentile(values, 50), 2),
            "p95_ms": round(_percentile(values, 95), 2),
            "max_ms": round(max(values), 2),
        }

    return {
        "app": app,
        "manual_row_count": len(app_rows),
        "timed_row_count": len(timed_rows),
        "first_image_visible_ms": round(_percentile(first_image_values, 50), 2),
        "set_slice_present_p95_ms": round(_percentile(scroll_values, 95), 2),
        "set_slice_present_p50_ms": round(_percentile(scroll_values, 50), 2),
        "step_timings": step_timings,
    }


def build_manual_result_payload(
    *,
    process_payload: Dict[str, Any],
    manual_rows: List[Dict[str, str]],
    app: str,
    viewer_label: str,
) -> Dict[str, Any]:
    process_summary = process_payload.get("process_summary", process_payload)
    manual_summary = summarize_manual_step_results(manual_rows, app=app)
    kpis = {
        "first_image_visible_ms": float(manual_summary.get("first_image_visible_ms", 0.0)),
        "set_slice_present_p50_ms": float(manual_summary.get("set_slice_present_p50_ms", 0.0)),
        "set_slice_present_p95_ms": float(manual_summary.get("set_slice_present_p95_ms", 0.0)),
        "cpu_p95_pct": float(process_summary.get("cpu_p95_pct", 0.0)),
        "rss_peak_mb": float(process_summary.get("rss_peak_mb", 0.0)),
        "thread_count_p95": float(process_summary.get("thread_count_p95", 0.0)),
        "read_mb_delta": float(process_summary.get("read_mb_delta", 0.0)),
        "write_mb_delta": float(process_summary.get("write_mb_delta", 0.0)),
    }
    return {
        "viewer": viewer_label,
        "mode": "manual-step-summary",
        "kpis": kpis,
        "manual_summary": manual_summary,
        "process_summary": process_summary,
        "source_process_viewer": process_payload.get("viewer", ""),
    }


def _make_pipeline(series_dir: str, scenario: Dict[str, Any]):
    from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline, PipelineConfig

    cfg_data = dict(scenario.get("pipeline_config", {}))
    cfg = PipelineConfig(
        pixel_cache_size=int(cfg_data.get("pixel_cache_size", 96)),
        frame_cache_size=int(cfg_data.get("frame_cache_size", 96)),
        prefetch_radius=int(cfg_data.get("prefetch_radius", 12)),
        prefetch_workers=int(cfg_data.get("prefetch_workers", 4)),
    )
    pipe = Lightweight2DPipeline(config=cfg)
    pipe.open_series(series_dir)
    return pipe


def _ensure_qapplication() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        QApplication([])


def _resolve_stack_drag_policy(
    *,
    scenario: Dict[str, Any],
    step: Dict[str, Any],
    cli_policy: str = "",
) -> str:
    return str(
        cli_policy
        or step.get("stack_drag_policy", "")
        or scenario.get("stack_drag_policy", "")
        or ""
    ).strip()


def _stack_drag_event_deltas(viewer, step: Dict[str, Any]) -> List[float]:
    events = max(1, int(step.get("events", step.get("count", 25))))

    if "total_dy" in step:
        dy_each = float(step.get("total_dy", 0.0)) / float(events)
        return [dy_each] * events

    if "dy_per_event" in step:
        dy_each = float(step.get("dy_per_event", 0.0))
        return [dy_each] * events

    steps_per_event = max(1, int(step.get("steps_per_event", 4)))
    threshold_px, _ = viewer._get_stack_drag_profile()
    dy_each = float(threshold_px) * float(steps_per_event)
    return [dy_each] * events


def _run_stack_drag_step(
    pipeline,
    step: Dict[str, Any],
    *,
    stack_drag_policy: str = "",
) -> None:
    from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    _ensure_qapplication()

    viewer = QtSliceViewer()
    width = int(step.get("viewer_width", 512))
    height = int(step.get("viewer_height", 512))
    viewer.resize(width, height)
    if stack_drag_policy:
        viewer.set_stack_drag_policy(stack_drag_policy)

    metadata = {
        "series": {
            "series_number": step.get("series_number", 1),
            "modality": step.get("modality", "CT"),
            "series_description": step.get("instruction", "stack_drag"),
            "image_count": int(getattr(pipeline, "slice_count", 0) or 0),
        },
        "instances": [],
    }
    bridge = QtViewerBridge(viewer, pipeline, metadata)
    bridge.set_slice(0, fast_interaction=False)

    bridge._on_stack_drag_state(True)
    viewer._stacked_accum = 0.0

    for dy in _stack_drag_event_deltas(viewer, step):
        delta = int(viewer._consume_stack_drag_delta(dy))
        if delta:
            bridge._on_qt_scroll(delta)

    bridge._on_stack_drag_state(False)
    bridge._on_interaction_settled()


def _run_pattern_step(pipeline, step: Dict[str, Any], *, stack_drag_policy: str = "") -> None:
    from modules.viewer.fast.perf_metrics import PerfMetrics
    from tests.performance.perf_helpers import (
        scroll_direction_reversal,
        scroll_forward,
        scroll_random,
        scroll_rapid_burst,
        scroll_stack_drag,
    )

    kind = str(step.get("kind", ""))
    n_slices = max(int(pipeline.slice_count), 1)
    count = int(step.get("count", n_slices))

    if kind == "forward_scan":
        pattern = scroll_forward(min(n_slices, count))
    elif kind == "rapid_burst":
        pattern = scroll_rapid_burst(n_slices, burst_length=min(n_slices, count))
    elif kind == "direction_reversal":
        pattern = scroll_direction_reversal(
            n_slices,
            cycles=int(step.get("cycles", 10)),
            segment=int(step.get("segment", 8)),
        )
    elif kind == "random_access":
        pattern = scroll_random(n_slices, count=count, seed=int(step.get("seed", 42)))
    elif kind == "stack_drag":
        _run_stack_drag_step(
            pipeline,
            step,
            stack_drag_policy=stack_drag_policy,
        )
        return
    else:
        return

    pm = PerfMetrics.get()
    pipeline.set_fast_interaction(bool(step.get("fast_interaction", True)))
    for idx in pattern:
        t0 = time.perf_counter()
        frame = pipeline.get_rendered_frame(idx)
        total_ms = (time.perf_counter() - t0) * 1000.0
        pm.record_set_slice(total_ms)
        if frame.decode_ms > 0:
            pm.record_foreground_wait(frame.decode_ms)
            pm.record_decode(frame.decode_ms)
        pm.record_frame_render(frame.total_ms)
        if frame.wl_ms > 0:
            pm.record_wl(frame.wl_ms)
        if frame.filter_ms > 0:
            pm.record_filter(frame.filter_ms)


def run_aipacs_headless(
    *,
    dataset: Path,
    scenario: Dict[str, Any],
    label: str = "AI-PACS FAST",
    stack_drag_policy: str = "",
) -> Dict[str, Any]:
    from modules.viewer.fast.perf_metrics import PerfMetrics
    from tests.performance.perf_helpers import GILContentionSimulator

    pipeline = _make_pipeline(str(dataset), scenario)
    pm = PerfMetrics.get()
    pm.enable()

    sim = None
    workers = int(scenario.get("simulated_download_workers", 0))
    if workers > 0:
        file_paths = [Path(p) for p in pipeline.get_file_paths()]
        sim = GILContentionSimulator(file_paths, workers=workers)
        sim.start()

    if psutil is not None:
        this_proc = psutil.Process(os.getpid())
        this_proc.cpu_percent(None)
    else:
        this_proc = None

    start = time.monotonic()
    samples: List[ProcessSample] = []

    try:
        t_first = time.perf_counter()
        pipeline.set_fast_interaction(False)
        pipeline.get_rendered_frame(0)
        pm.record_first_image((time.perf_counter() - t_first) * 1000.0)

        for step in scenario.get("steps", []):
            kind = str(step.get("kind", ""))
            if kind in {"forward_scan", "rapid_burst", "direction_reversal", "random_access", "stack_drag"}:
                _run_pattern_step(
                    pipeline,
                    step,
                    stack_drag_policy=_resolve_stack_drag_policy(
                        scenario=scenario,
                        step=step,
                        cli_policy=stack_drag_policy,
                    ),
                )
            elif kind == "settle":
                pipeline.set_fast_interaction(False)
                if hasattr(pipeline, "rerender_current_filtered"):
                    pipeline.rerender_current_filtered()
                time.sleep(float(step.get("duration_s", 0.0)))
            elif kind == "reopen_series":
                pipeline.close_series()
                pipeline = _make_pipeline(str(dataset), scenario)
                t0 = time.perf_counter()
                pipeline.get_rendered_frame(0)
                pm.record_first_image((time.perf_counter() - t0) * 1000.0)
            elif kind == "initial_frame":
                continue

            if this_proc is not None:
                mem = this_proc.memory_info()
                io = this_proc.io_counters() if hasattr(this_proc, "io_counters") else None
                elapsed = time.monotonic() - start
                samples.append(
                    ProcessSample(
                        timestamp_s=round(elapsed, 3),
                        step_id=str(step.get("id", "unknown")),
                        cpu_pct=float(this_proc.cpu_percent(None)),
                        rss_mb=mem.rss / (1024 * 1024),
                        thread_count=this_proc.num_threads(),
                        read_mb=(io.read_bytes / (1024 * 1024)) if io else 0.0,
                        write_mb=(io.write_bytes / (1024 * 1024)) if io else 0.0,
                    )
                )
    finally:
        if sim is not None:
            sim.stop()
        pipeline.close_series()
        pm.disable()

    process_summary = summarize_process_samples(samples)
    snapshot = pm.snapshot()
    return {
        "viewer": label,
        "mode": "headless-aipacs-fast",
        "dataset": str(dataset),
        "scenario_id": scenario.get("id"),
        "scenario_title": scenario.get("title"),
        "stack_drag_policy": stack_drag_policy or str(scenario.get("stack_drag_policy", "") or ""),
        "kpis": _normalize_headless_kpis(snapshot, process_summary),
        "raw_perf_metrics": snapshot,
        "process_summary": process_summary,
    }


def _extract_metrics(payload: Dict[str, Any]) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    for key in ("kpis", "log_metrics", "process_summary"):
        blob = payload.get(key)
        if isinstance(blob, dict):
            metrics.update(blob)
    return metrics


def summarize_payload_by_block(payload: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
    metrics = _extract_metrics(payload)
    blocks: List[Dict[str, Any]] = []

    for block in model.get("blocks", []):
        present_metrics: List[Dict[str, Any]] = []
        missing_metrics: List[Dict[str, Any]] = []
        for metric in block.get("metrics", []):
            key = str(metric.get("key", "")).strip()
            if not key:
                continue
            metric_row = {
                "key": key,
                "label": metric.get("label", key),
                "goal": metric.get("goal", ""),
                "source": metric.get("source", ""),
                "status": metric.get("status", "existing"),
            }
            if key in metrics:
                metric_row["value"] = metrics[key]
                present_metrics.append(metric_row)
            else:
                missing_metrics.append(metric_row)

        total_metrics = len(present_metrics) + len(missing_metrics)
        blocks.append(
            {
                "block_id": block.get("id", ""),
                "label": block.get("label", ""),
                "role": block.get("role", ""),
                "position": block.get("position", ""),
                "preferred_worker_model": block.get("preferred_worker_model", {}),
                "present_metrics": present_metrics,
                "missing_metrics": missing_metrics,
                "coverage_pct": round((len(present_metrics) / total_metrics) * 100.0, 2) if total_metrics else 0.0,
            }
        )

    scenario_map = {
        str(scenario.get("id", "")): scenario
        for scenario in model.get("scenarios", [])
        if isinstance(scenario, dict)
    }

    return {
        "viewer": payload.get("viewer", "unknown"),
        "mode": "block-kpi-summary",
        "source_mode": payload.get("mode", ""),
        "scenario_id": payload.get("scenario_id", ""),
        "scenario_title": payload.get("scenario_title", ""),
        "scenario_block_focus": scenario_map.get(str(payload.get("scenario_id", "")), {}),
        "blocks": blocks,
    }


def block_summary_to_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# FAST Block KPI Summary",
        "",
        f"- Viewer: `{summary.get('viewer', 'unknown')}`",
        f"- Source mode: `{summary.get('source_mode', '')}`",
        f"- Scenario: `{summary.get('scenario_id', '')}` {summary.get('scenario_title', '')}`".rstrip("`") if summary.get("scenario_title") else f"- Scenario: `{summary.get('scenario_id', '')}`",
        "",
    ]

    focus = summary.get("scenario_block_focus") or {}
    if focus:
        lines.extend(
            [
                "## Scenario block focus",
                "",
                f"- Primary blocks: `{', '.join(focus.get('primary_blocks', []))}`",
                f"- Intent: {focus.get('intent', '')}",
                "",
            ]
        )

    for block in summary.get("blocks", []):
        lines.extend(
            [
                f"## {block.get('label', '')}",
                "",
                f"- Role: {block.get('role', '')}",
                f"- Position: {block.get('position', '')}",
                f"- Coverage: {block.get('coverage_pct', 0.0)}%",
                "",
                "| Metric | Value | Goal | Source | Status |",
                "|---|---:|---|---|---|",
            ]
        )
        for metric in block.get("present_metrics", []):
            lines.append(
                f"| `{metric['label']}` | {metric.get('value')} | {metric.get('goal', '')} | `{metric.get('source', '')}` | `{metric.get('status', '')}` |"
            )
        for metric in block.get("missing_metrics", []):
            lines.append(
                f"| `{metric['label']}` | _missing_ | {metric.get('goal', '')} | `{metric.get('source', '')}` | `{metric.get('status', '')}` |"
            )
        lines.append("")

    return "\n".join(lines)


def compare_payloads(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    left_metrics = _extract_metrics(left)
    right_metrics = _extract_metrics(right)
    shared_keys = sorted(set(left_metrics).intersection(right_metrics))

    rows = []
    for key in shared_keys:
        left_value = left_metrics[key]
        right_value = right_metrics[key]
        if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
            delta = round(float(left_value) - float(right_value), 2)
        else:
            delta = None
        rows.append(
            {
                "metric": key,
                "left": left_value,
                "right": right_value,
                "delta_left_minus_right": delta,
            }
        )

    findings: List[str] = []
    left_name = str(left.get("viewer", "left"))
    right_name = str(right.get("viewer", "right"))

    if float(left_metrics.get("terminal_completion_duplicate_count", 0.0)) > 0 and float(right_metrics.get("terminal_completion_duplicate_count", 0.0)) == 0:
        findings.append(
            f"{left_name} still repeats terminal progressive work while {right_name} does not."
        )
    if float(left_metrics.get("cache_warm_duplicate_count", 0.0)) > 0 and float(right_metrics.get("cache_warm_duplicate_count", 0.0)) == 0:
        findings.append(
            f"{left_name} is still dispatching duplicate post-completion cache warm work."
        )
    if (
        "cpu_p95_pct" in left_metrics
        and "cpu_p95_pct" in right_metrics
        and float(left_metrics["cpu_p95_pct"]) > float(right_metrics["cpu_p95_pct"]) * 1.15
    ):
        findings.append(
            f"{left_name} consumes materially more CPU under the same scripted steps, which points to control-plane overhead rather than pure rendering."
        )
    if (
        "thread_count_p95" in left_metrics
        and "thread_count_p95" in right_metrics
        and float(left_metrics["thread_count_p95"]) > float(right_metrics["thread_count_p95"]) + 4.0
    ):
        findings.append(
            f"{left_name} keeps more concurrent actors alive than {right_name}, which matches the ownership spread seen in the code review."
        )
    if (
        "set_slice_present_p95_ms" in left_metrics
        and float(left_metrics["set_slice_present_p95_ms"]) > 16.0
    ):
        findings.append(
            f"{left_name} still misses the 16ms interactive frame budget in the compared run."
        )
    if float(left_metrics.get("stack_drag_decode_hitch_count", 0.0)) > 0:
        findings.append(
            f"{left_name} still shows cache-edge foreground decode hitches during stack drag."
        )
    if float(left_metrics.get("stack_drag_nondecode_hitch_count", 0.0)) > 0:
        findings.append(
            f"{left_name} still shows non-decode main-thread hitches during stack drag, so not all lag is explained by lazy decode."
        )
    if not findings:
        findings.append("No dominant regression signal was found in the overlapping metrics.")

    return {
        "left": left_name,
        "right": right_name,
        "rows": rows,
        "findings": findings,
    }


def comparison_to_markdown(comparison: Dict[str, Any]) -> str:
    lines = [
        "# Viewer KPI Comparison",
        "",
        f"- Left: `{comparison['left']}`",
        f"- Right: `{comparison['right']}`",
        "",
        "## Findings",
        "",
    ]
    for finding in comparison["findings"]:
        lines.append(f"- {finding}")
    lines.extend(
        [
            "",
            "## Shared Metrics",
            "",
            "| Metric | Left | Right | Delta (Left-Right) |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in comparison["rows"]:
        lines.append(
            f"| `{row['metric']}` | {row['left']} | {row['right']} | {row['delta_left_minus_right']} |"
    )
    lines.append("")
    return "\n".join(lines)


def _default_output(name: str, suffix: str) -> Path:
    out_dir = REPO_ROOT / "generated-files" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return out_dir / f"{name}_{stamp}.{suffix}"


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _viewer_label_to_apps(viewer: str) -> List[str]:
    if viewer == "aipacs":
        return ["aipacs"]
    if viewer == "clearcanvas":
        return ["clearcanvas"]
    return ["aipacs", "clearcanvas"]


def _app_action(step: Dict[str, Any], app: str) -> str:
    if app == "aipacs":
        return str(step.get("aipacs_action", "")).strip()
    return str(step.get("clearcanvas_action", "")).strip()


def build_execution_pack(
    *,
    scenarios: List[Dict[str, Any]],
    model: Dict[str, Any],
    output_dir: Path,
    viewer: str,
    dataset: str = "",
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    apps = _viewer_label_to_apps(viewer)
    scenario_ids = {str(s["id"]) for s in scenarios}
    phases = {str(p["id"]): p for p in model.get("phases", [])}
    steps = [
        step
        for step in model.get("steps", [])
        if str(step.get("scenario_id", "")) in scenario_ids
    ]

    instructions_path = output_dir / "instructions.md"
    manual_csv_path = output_dir / "manual_step_results.csv"
    manifest_path = output_dir / "result_manifest.json"

    instruction_lines = [
        "# Viewer Benchmark Execution Pack",
        "",
        f"- Viewer selection: `{viewer}`",
        f"- Dataset: `{dataset or 'SET_THIS_BEFORE_RUN'}`",
        "",
        "## Scenarios",
        "",
    ]
    for scenario in scenarios:
        instruction_lines.append(f"- `{scenario['id']}`: {scenario.get('title', '')}")
    instruction_lines.extend(
        [
            "",
            "## Phases",
            "",
            "| Phase | Meaning |",
            "|---|---|",
        ]
    )
    for phase_id in ("A", "B", "C", "D", "E"):
        phase = phases.get(phase_id)
        if phase:
            instruction_lines.append(f"| `{phase_id}` | {phase.get('title', '')} |")

    instruction_lines.extend(
        [
            "",
            "## Step Mapping",
            "",
            "| Step ID | Phase | Scenario | AI-PACS Action | ClearCanvas Action | Confidence | Fairness | Automation |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for step in steps:
        instruction_lines.append(
            "| `{}` | `{}` | `{}` | {} | {} | {} | {} | {} |".format(
                step.get("id", ""),
                step.get("phase", ""),
                step.get("scenario_id", ""),
                str(step.get("aipacs_action", "")).replace("\n", " "),
                str(step.get("clearcanvas_action", "")).replace("\n", " "),
                step.get("equivalence_confidence", ""),
                step.get("fairness", ""),
                step.get("automation", ""),
            )
        )

    instruction_lines.extend(
        [
            "",
            "## Operator Notes",
            "",
            "- Fill `manual_step_results.csv` during or immediately after the run.",
            "- Use process JSON output for CPU/RSS/thread/disk metrics.",
            "- Use AI-PACS log parsing for AI-PACS-only internal diagnostics.",
            "- Treat `clearcanvas_background_copy_pressure_approx` as approximate, not equivalent, to AI-PACS live progressive download.",
            "",
        ]
    )
    instructions_path.write_text("\n".join(instruction_lines), encoding="utf-8")

    with manual_csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "step_id",
                "phase",
                "scenario_id",
                "app",
                "action",
                "timing_marker_start",
                "timing_marker_end",
                "time_ms",
                "cpu_pct",
                "rss_mb",
                "thread_count",
                "notes",
                "fairness",
                "equivalence_confidence",
            ],
        )
        writer.writeheader()
        for step in steps:
            for app in apps:
                action = _app_action(step, app)
                if not action:
                    continue
                writer.writerow(
                    {
                        "step_id": step.get("id", ""),
                        "phase": step.get("phase", ""),
                        "scenario_id": step.get("scenario_id", ""),
                        "app": app,
                        "action": action,
                        "timing_marker_start": "; ".join(step.get("timing_markers_start", [])),
                        "timing_marker_end": "; ".join(step.get("timing_markers_end", [])),
                        "time_ms": "",
                        "cpu_pct": "",
                        "rss_mb": "",
                        "thread_count": "",
                        "notes": "",
                        "fairness": step.get("fairness", ""),
                        "equivalence_confidence": step.get("equivalence_confidence", ""),
                    }
                )

    manifest = {
        "viewer_selection": viewer,
        "dataset": dataset or "",
        "scenario_ids": [str(s["id"]) for s in scenarios],
        "instructions_path": str(instructions_path),
        "manual_step_results_path": str(manual_csv_path),
        "expected_outputs": {
            "aipacs_common_json": str(output_dir / "aipacs_common.json"),
            "clearcanvas_common_json": str(output_dir / "clearcanvas_common.json"),
            "aipacs_overlap_log_json": str(output_dir / "aipacs_overlap_log.json"),
            "comparison_markdown": str(output_dir / "comparison.md"),
        },
    }
    _write_json(manifest_path, manifest)
    return manifest


def _cmd_run_aipacs_headless(args: argparse.Namespace) -> int:
    scenario = get_scenario(Path(args.scenario_file), args.scenario)
    payload = run_aipacs_headless(
        dataset=Path(args.dataset),
        scenario=scenario,
        label=args.label,
        stack_drag_policy=args.stack_drag_policy,
    )
    out = Path(args.output) if args.output else _default_output("aipacs_headless", "json")
    _write_json(out, payload)
    print(out)
    return 0


def _cmd_monitor_process(args: argparse.Namespace) -> int:
    scenario = get_scenario(Path(args.scenario_file), args.scenario)
    payload = monitor_process_run(
        scenario=scenario,
        pid=args.pid,
        process_name=args.process_name,
        wait_timeout_s=args.wait_timeout,
        interval_ms=args.interval_ms,
        label=args.label,
    )
    out = Path(args.output) if args.output else _default_output("external_viewer_monitor", "json")
    _write_json(out, payload)
    print(out)
    return 0


def _cmd_parse_aipacs_log(args: argparse.Namespace) -> int:
    payload = parse_aipacs_log_file(Path(args.log))
    out = Path(args.output) if args.output else _default_output("aipacs_log_metrics", "json")
    _write_json(out, payload)
    print(out)
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    left = json.loads(Path(args.left).read_text(encoding="utf-8"))
    right = json.loads(Path(args.right).read_text(encoding="utf-8"))
    comparison = compare_payloads(left, right)
    out = Path(args.output) if args.output else _default_output("viewer_comparison", "md")
    _ensure_parent(out)
    out.write_text(comparison_to_markdown(comparison), encoding="utf-8")
    print(out)
    return 0


def _cmd_emit_execution_pack(args: argparse.Namespace) -> int:
    scenario_file = Path(args.scenario_file)
    scenarios = [get_scenario(scenario_file, scenario_id) for scenario_id in args.scenario]
    model = load_benchmark_model(Path(args.model_file))
    out_dir = Path(args.output_dir) if args.output_dir else _default_output("execution_pack", "tmp").with_suffix("")
    manifest = build_execution_pack(
        scenarios=scenarios,
        model=model,
        output_dir=out_dir,
        viewer=args.viewer,
        dataset=args.dataset,
    )
    print(manifest["instructions_path"])
    print(Path(manifest["manual_step_results_path"]).resolve())
    print(Path(out_dir).resolve())
    return 0


def _cmd_summarize_manual_results(args: argparse.Namespace) -> int:
    process_payload = json.loads(Path(args.process_json).read_text(encoding="utf-8"))
    manual_rows = load_manual_step_results(Path(args.manual_csv))
    payload = build_manual_result_payload(
        process_payload=process_payload,
        manual_rows=manual_rows,
        app=args.app,
        viewer_label=args.viewer_label,
    )
    out = Path(args.output) if args.output else _default_output("manual_result_summary", "json")
    _write_json(out, payload)
    print(out)
    return 0


def _cmd_summarize_blocks(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    model = load_block_kpi_model(Path(args.block_model))
    summary = summarize_payload_by_block(payload, model)
    out = Path(args.output) if args.output else _default_output("block_kpi_summary", "json")
    _write_json(out, summary)
    if args.markdown_output:
        md_out = Path(args.markdown_output)
        _ensure_parent(md_out)
        md_out.write_text(block_summary_to_markdown(summary), encoding="utf-8")
        print(md_out)
    print(out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ClearCanvas vs AI-PACS KPI harness")
    sub = parser.add_subparsers(dest="command", required=True)

    p_headless = sub.add_parser("run-aipacs-headless", help="Run a headless FAST pipeline scenario")
    p_headless.add_argument("--dataset", required=True, help="Path to a local DICOM series directory")
    p_headless.add_argument(
        "--scenario-file",
        default=str(REPO_ROOT / "tests" / "performance" / "clearcanvas_aipacs_scenarios.json"),
    )
    p_headless.add_argument("--scenario", required=True)
    p_headless.add_argument("--label", default="AI-PACS FAST")
    p_headless.add_argument(
        "--stack-drag-policy",
        default="",
        help="Optional Qt stack-drag policy override (for example: adaptive or clearcanvas).",
    )
    p_headless.add_argument("--output")
    p_headless.set_defaults(func=_cmd_run_aipacs_headless)

    p_monitor = sub.add_parser("monitor-process", help="Sample an external viewer process during a scenario")
    p_monitor.add_argument(
        "--scenario-file",
        default=str(REPO_ROOT / "tests" / "performance" / "clearcanvas_aipacs_scenarios.json"),
    )
    p_monitor.add_argument("--scenario", required=True)
    p_monitor.add_argument("--process-name")
    p_monitor.add_argument("--pid", type=int)
    p_monitor.add_argument("--label", default="")
    p_monitor.add_argument("--wait-timeout", type=float, default=30.0)
    p_monitor.add_argument("--interval-ms", type=int, default=250)
    p_monitor.add_argument("--output")
    p_monitor.set_defaults(func=_cmd_monitor_process)

    p_parse = sub.add_parser("parse-aipacs-log", help="Extract AI-PACS runtime KPIs from a log file")
    p_parse.add_argument("--log", required=True)
    p_parse.add_argument("--output")
    p_parse.set_defaults(func=_cmd_parse_aipacs_log)

    p_compare = sub.add_parser("compare", help="Compare two KPI JSON payloads")
    p_compare.add_argument("--left", required=True)
    p_compare.add_argument("--right", required=True)
    p_compare.add_argument("--output")
    p_compare.set_defaults(func=_cmd_compare)

    p_pack = sub.add_parser("emit-execution-pack", help="Generate operator instructions and manual result templates")
    p_pack.add_argument(
        "--scenario-file",
        default=str(REPO_ROOT / "tests" / "performance" / "clearcanvas_aipacs_scenarios.json"),
    )
    p_pack.add_argument(
        "--model-file",
        default=str(REPO_ROOT / "tests" / "performance" / "clearcanvas_aipacs_benchmark_model.json"),
    )
    p_pack.add_argument("--scenario", action="append", required=True)
    p_pack.add_argument("--viewer", choices=["both", "aipacs", "clearcanvas"], default="both")
    p_pack.add_argument("--dataset", default="")
    p_pack.add_argument("--output-dir")
    p_pack.set_defaults(func=_cmd_emit_execution_pack)

    p_manual = sub.add_parser("summarize-manual-results", help="Combine manual step CSV and process JSON into KPI JSON")
    p_manual.add_argument("--manual-csv", required=True)
    p_manual.add_argument("--process-json", required=True)
    p_manual.add_argument("--app", default="clearcanvas")
    p_manual.add_argument("--viewer-label", default="ClearCanvas")
    p_manual.add_argument("--output")
    p_manual.set_defaults(func=_cmd_summarize_manual_results)

    p_blocks = sub.add_parser("summarize-blocks", help="Group a KPI payload by Block 1/2/3 ownership")
    p_blocks.add_argument("--payload", required=True)
    p_blocks.add_argument(
        "--block-model",
        default=str(REPO_ROOT / "tests" / "performance" / "block_kpi_model.json"),
    )
    p_blocks.add_argument("--output")
    p_blocks.add_argument("--markdown-output")
    p_blocks.set_defaults(func=_cmd_summarize_blocks)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
