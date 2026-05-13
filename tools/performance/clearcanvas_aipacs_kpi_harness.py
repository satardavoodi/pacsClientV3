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
_FAST_DRAG_KPI_RE = re.compile(
    r"\[FAST_DRAG_KPI\].*?duration_s=(?P<duration>[0-9.]+)\s+targets=(?P<targets>\d+)\s+"
    r"event_p50_ms=(?P<event_p50>[0-9.]+)\s+event_p95_ms=(?P<event_p95>[0-9.]+)\s+"
    r"handler_p50_ms=(?P<handler_p50>[0-9.]+)\s+handler_p95_ms=(?P<handler_p95>[0-9.]+)\s+"
    r"ui_lag_max_ms=(?P<ui_lag_max>[0-9.]+)\s+prefetch_per_s=(?P<prefetch_per_s>[0-9.]+)\s+"
    r"background_decode_count=(?P<background_decode_count>\d+)"
)
_ADVANCED_SCROLL_SUBTIMING_RE = re.compile(
    r"viewer-scroll sub-timing:\s+SetSlice=(?P<set_slice>[0-9.]+)ms\s+"
    r"WL=(?P<wl>[0-9.]+)ms\s+corners=(?P<corners>[0-9.]+)ms\s+"
    r"Render=(?P<render>[0-9.]+)ms\s+total=(?P<total>[0-9.]+)ms"
)
# F3.5.1 — DM coordinator priority-handoff structured emit. Tags:
# begin / tick / defer / recover / exhaust / started. Optional branch=primary|recovery|v2.
# F3.5.2 — Optional reason=pool_busy|reclaimed|state_lost|timeout (V2 exhaust + reclaimed defer).
_INTENT_PRIORITY_RE = re.compile(
    r"\[INTENT_PRIORITY\]\s+tag=(?P<tag>\w+)\s+study=(?P<study>\S*)\s+series=(?P<series>\S*)\s+"
    r"attempt=(?P<attempt>\d+)/(?P<max_attempts>\d+)\s+recovery=(?P<recovery>True|False)\s+"
    r"pool_busy=(?P<pool_busy>True|False)\s+pool_capacity=(?P<pool_active>\d+)/(?P<pool_max>\d+)\s+"
    r"state=(?P<state>\S+)\s+auto_paused=(?P<auto_paused>True|False)\s+"
    r"elapsed_ms=(?P<elapsed_ms>\d+)\s+token=(?P<token>\d+)"
    r"(?:\s+branch=(?P<branch>\w+))?"
    r"(?:\s+reason=(?P<reason>\w+))?"
)
# G6 — Slot-timing observability emitted by `modules/viewer/fast/slot_timing.py`.
# Format (kept stable; extend with optional groups only):
#   [SLOT_TIMING] tag=<TAG> duration_ms=<F.3> drag_active=<True|False>
#                 threshold_ms=<F.1> series=<SN|none> extra=<k1=v1;k2=v2>
_SLOT_TIMING_RE = re.compile(
    r"\[SLOT_TIMING\]\s+tag=(?P<tag>\S+)\s+"
    r"duration_ms=(?P<duration_ms>[0-9.]+)\s+"
    r"drag_active=(?P<drag_active>True|False)\s+"
    r"threshold_ms=(?P<threshold_ms>[0-9.]+)\s+"
    r"series=(?P<series>\S+)"
    r"(?:\s+extra=(?P<extra>\S*))?"
)
# G7 — DM table-rebuild observability emitted by
# `modules/download_manager/ui/widget/_dm_details.py::_refresh_table_order`.
# Format (kept stable):
#   [DM_REBUILD] event=<enter|exit|reenter_skip> depth=<N>
#       [duration_ms=<F.3>] [rows=<R>] caller=<file.py:func>
_DM_REBUILD_RE = re.compile(
    r"\[DM_REBUILD\]\s+event=(?P<event>\w+)\s+"
    r"depth=(?P<depth>\d+)"
    r"(?:\s+duration_ms=(?P<duration_ms>[0-9.]+))?"
    r"(?:\s+rows=(?P<rows>\d+))?"
    r"(?:\s+caller=(?P<caller>\S+))?"
)
# G7 — DM priority-transition tag emitted by `_dm_controls._on_priority_changed`.
# Format:
#   [DM_PRIORITY_TRANSITION] event=combo_changed new=<P> study=<UID>
#       during_rebuild=<True|False>
_DM_PRIORITY_TRANSITION_RE = re.compile(
    r"\[DM_PRIORITY_TRANSITION\]\s+event=(?P<event>\w+)\s+"
    r"new=(?P<new>\S+)\s+"
    r"study=(?P<study>\S*)\s+"
    r"during_rebuild=(?P<during_rebuild>True|False)"
)
_STAGE_TIMING_RE = re.compile(
    r"component=(?P<component>\w+)\s+role=(?P<role>[^|]+)\s+\|.*?"
    r"fn=(?P<function>\S+)\s+stage=(?P<stage>\S+)\s+result=(?P<result>\S+)\s+\|.*?"
    r"stage-timing duration_ms=(?P<duration>[0-9.]+)(?P<fields>.*)"
)
_KV_FIELD_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>[^\s|]+)")
_BACKEND_RESOLVE_RE = re.compile(
    r"viewer-backend .*?requested=(?P<requested>\S+)\s+chosen=(?P<chosen>\S+)"
)
_DOWNLOAD_IMPACT_RE = re.compile(
    r"download-impact-window .*?delay_ms=(?P<delay>[0-9.]+)\s+"
    r"elapsed_ms=(?P<elapsed>[0-9.]+)\s+active_workers=(?P<active_workers>\d+)"
)
_THUMBNAIL_END_RE = re.compile(
    r"thumbnail_pipeline event=end .*?dl_ms=(?P<duration>[0-9.]+)"
)
_ZETABOOST_RE = re.compile(
    r"\[ZetaBoost\].*?entries=(?P<entries>\d+)\s+bytes=(?P<bytes>[0-9.]+)MB/"
    r"(?P<budget>[0-9.]+)MB\s+queued=(?P<queued>\d+)\s+inflight=(?P<inflight>\d+)"
)
_PRIORITY_RETRY_EXHAUSTED_RE = re.compile(
    r"Priority start retry exhausted .*? after (?:recovery )?(?:attempts=)?(?P<attempts>\d+)(?: attempts)?"
)
_SEND_REQUEST_RETRY_RE = re.compile(
    r"send_request\((?P<endpoint>[^)]+)\) attempt (?P<attempt>\d+)/(?P<max>\d+) failed"
)
_SEND_REQUEST_FAILED_RE = re.compile(
    r"send_request\((?P<endpoint>[^)]+)\) failed after (?P<attempts>\d+) attempts"
)
_DOWNLOAD_PIPELINE_SUMMARY_RE = re.compile(
    r"download-pipeline-summary .*?disk_write_ms=(?P<disk_write>[0-9.]+)\s+"
    r"decode_ms=(?P<decode>[0-9.]+)\s+decompress_ms=(?P<decompress>[0-9.]+)"
)
_VIEWER_DATA_STAGE_RE = re.compile(
    r"viewer-data stage=(?P<stage>\w+)\s+duration_ms=(?P<duration>[0-9.]+)(?P<fields>.*)"
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


def _parse_kv_fields(text: str) -> Dict[str, str]:
    return {m.group("key"): m.group("value") for m in _KV_FIELD_RE.finditer(text or "")}


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
    fast_cached_display_ms: List[float] = []
    fast_drag_event_p50_ms: List[float] = []
    fast_drag_event_p95_ms: List[float] = []
    fast_drag_handler_p95_ms: List[float] = []
    fast_drag_ui_lag_max_ms: List[float] = []
    fast_drag_prefetch_per_s: List[float] = []
    fast_drag_background_decode_count: List[float] = []
    fast_queue_wait_sessions: List[Dict[str, Any]] = []
    fast_queue_wait_class_counts: Counter[str] = Counter()
    advanced_set_slice_ms: List[float] = []
    advanced_wl_ms: List[float] = []
    advanced_render_ms: List[float] = []
    advanced_total_ms: List[float] = []
    db_stage_ms: List[float] = []
    db_read_stage_ms: List[float] = []
    db_write_stage_ms: List[float] = []
    main_thread_db_fast_interaction_ms: List[float] = []
    main_thread_db_advanced_interaction_ms: List[float] = []
    main_thread_db_all_ms: List[float] = []
    grpc_stage_ms: List[float] = []
    socket_request_total_ms: List[float] = []
    server_connect_ms: List[float] = []
    main_thread_blocking_io_ms: List[float] = []
    download_impact_elapsed_ms: List[float] = []
    dicom_file_write_ms: List[float] = []
    dicom_file_write_summary_ms: List[float] = []
    dicom_file_read_ms: List[float] = []
    dicom_file_write_bytes_total = 0
    main_thread_disk_scan_ms: List[float] = []
    main_thread_disk_scan_fast_interaction_ms: List[float] = []
    main_thread_disk_scan_advanced_interaction_ms: List[float] = []
    thumbnail_generation_ms: List[float] = []
    zeta_cache_bytes_mb: List[float] = []
    zeta_cache_budget_mb: List[float] = []
    zeta_queue_depths: List[float] = []
    process_rss_samples_mb: List[float] = []
    available_ram_samples_mb: List[float] = []
    subprocess_count_samples: List[int] = []
    viewer_switch_total_ms: List[float] = []
    progressive_grow_apply_ms: List[float] = []
    completion_verify_ms: List[float] = []
    advanced_series_load_total_ms_samples: List[float] = []
    stale_request_drop_count = 0
    duplicate_load_suppressed_count = 0
    src_counts: Counter[str] = Counter()
    complete_counts: Counter[str] = Counter()
    cache_warm_counts: Counter[str] = Counter()
    duplicate_terminal_counts: Counter[str] = Counter()
    viewer_mode_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    db_caller_area_counts: Counter[str] = Counter()
    db_viewer_mode_counts: Counter[str] = Counter()
    download_counts: Counter[str] = Counter()
    stack_drag_active = False
    stack_drag_total_ms: List[float] = []
    stack_drag_decode_ms: List[float] = []
    stack_drag_decode_hitch_total_ms: List[float] = []
    stack_drag_nondecode_hitch_total_ms: List[float] = []
    fast_foreground_decode_during_drag_count = 0
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
        if "component=download" in line or "SocketDicomClient" in line or "GrpcMetadataClient" in line:
            viewer_mode_counts["Shared"] += 1
        if "pydicom_qt" in line or "[FAST_" in line or "QtViewerBridge" in line or "qt-viewer-bridge" in line:
            viewer_mode_counts["FAST_QT"] += 1
        if "pydicom_2d" in line or "PyDicomLazyVolume" in line:
            viewer_mode_counts["FAST_LAZY_VTK"] += 1
        if "vtk_simpleitk" in line or "ImageViewer2D" in line or "viewer-scroll sub-timing" in line:
            viewer_mode_counts["Advanced"] += 1

        if _STACK_DRAG_START_RE.search(line):
            stack_drag_active = True
        elif _STACK_DRAG_STOP_RE.search(line) or _STACK_DRAG_SETTLE_RE.search(line):
            stack_drag_active = False

        m = _BACKEND_RESOLVE_RE.search(line)
        if m:
            chosen = str(m.group("chosen"))
            if chosen == "pydicom_qt":
                viewer_mode_counts["FAST_QT"] += 1
            elif chosen == "pydicom_2d":
                viewer_mode_counts["FAST_LAZY_VTK"] += 1
            elif chosen == "vtk_simpleitk":
                viewer_mode_counts["Advanced"] += 1

        m = _FIRST_IMAGE_RE.search(line)
        if m:
            first_image_ms.append(float(m.group("total")))

        m = _FAST_DRAG_KPI_RE.search(line)
        if m:
            fast_drag_event_p50_ms.append(float(m.group("event_p50")))
            fast_drag_event_p95_ms.append(float(m.group("event_p95")))
            fast_drag_handler_p95_ms.append(float(m.group("handler_p95")))
            fast_drag_ui_lag_max_ms.append(float(m.group("ui_lag_max")))
            fast_drag_prefetch_per_s.append(float(m.group("prefetch_per_s")))
            fast_drag_background_decode_count.append(float(m.group("background_decode_count")))

        if "[FAST_EVENT_PACING]" in line:
            fields = _parse_kv_fields(line)
            implied_queue_wait_p95 = _to_float(fields.get("implied_queue_wait_p95_ms"))
            if implied_queue_wait_p95 is not None:
                drag_session_id = str(fields.get("drag_session_id", ""))
                queue_wait_class = str(fields.get("queue_wait_classification", "UNKNOWN_QUEUE_WAIT"))
                input_gap_p95 = _to_float(fields.get("input_event_gap_p95_ms")) or 0.0
                request_to_execute_p95 = _to_float(fields.get("request_to_execute_p95_ms")) or 0.0
                frame_ready_to_paint_p95 = _to_float(fields.get("frame_ready_to_paint_p95_ms")) or 0.0
                paint_to_present_p95 = _to_float(fields.get("paint_to_present_p95_ms")) or 0.0
                frame_present_interval_p95 = _to_float(fields.get("frame_present_interval_p95_ms")) or 0.0
                stage_candidates = {
                    "INPUT_DELIVERY_GAP": float(input_gap_p95),
                    "SET_SLICE_QUEUE_WAIT": float(request_to_execute_p95),
                    "QT_UPDATE_PAINT_DELAY": float(frame_ready_to_paint_p95),
                    "FRAME_PRESENT_DELAY": float(frame_present_interval_p95),
                    "PAINT_TO_PRESENT": float(paint_to_present_p95),
                }
                dominant_stage = max(stage_candidates.items(), key=lambda kv: kv[1])[0]
                fast_queue_wait_sessions.append({
                    "drag_session_id": drag_session_id,
                    "queue_wait_classification": queue_wait_class,
                    "implied_queue_wait_p95_ms": float(implied_queue_wait_p95),
                    "implied_queue_wait_max_ms": float(_to_float(fields.get("implied_queue_wait_max_ms")) or 0.0),
                    "input_event_gap_p95_ms": float(input_gap_p95),
                    "request_to_execute_p95_ms": float(request_to_execute_p95),
                    "frame_ready_to_paint_p95_ms": float(frame_ready_to_paint_p95),
                    "paint_to_present_p95_ms": float(paint_to_present_p95),
                    "frame_present_interval_p95_ms": float(frame_present_interval_p95),
                    "qt_update_pending_count": int(_to_float(fields.get("qt_update_pending_count")) or 0),
                    "pending_set_slice_queue_depth_p95": float(_to_float(fields.get("pending_set_slice_queue_depth_p95")) or 0.0),
                    "stale_slice_request_count": int(_to_float(fields.get("stale_slice_request_count")) or 0),
                    "dropped_or_superseded_slice_request_count": int(_to_float(fields.get("dropped_or_superseded_slice_request_count")) or 0),
                    "dominant_queue_wait_stage": dominant_stage,
                })
                fast_queue_wait_class_counts[queue_wait_class] += 1

        m = _ADVANCED_SCROLL_SUBTIMING_RE.search(line)
        if m:
            advanced_set_slice_ms.append(float(m.group("set_slice")))
            advanced_wl_ms.append(float(m.group("wl")))
            advanced_render_ms.append(float(m.group("render")))
            advanced_total_ms.append(float(m.group("total")))

        m = _STAGE_TIMING_RE.search(line)
        if m:
            duration_ms = float(m.group("duration"))
            component = str(m.group("component")).strip().lower()
            role = str(m.group("role")).strip().lower()
            function = str(m.group("function"))
            stage = str(m.group("stage"))
            fields = _parse_kv_fields(m.group("fields"))
            stage_counts[f"{component}.{function}.{stage}"] += 1
            if component == "db":
                db_stage_ms.append(duration_ms)
                query_type = str(fields.get("query_type", "mixed")).lower()
                if "read" in query_type or "select" in query_type:
                    db_read_stage_ms.append(duration_ms)
                elif "write" in query_type or "insert" in query_type or "update" in query_type:
                    db_write_stage_ms.append(duration_ms)
                caller_area = str(fields.get("caller_area", "unknown"))
                viewer_mode = str(fields.get("viewer_mode", "unknown"))
                db_caller_area_counts[caller_area] += 1
                db_viewer_mode_counts[viewer_mode] += 1
                if role == "main":
                    main_thread_db_all_ms.append(duration_ms)
                    if caller_area == "fast_interaction":
                        main_thread_db_fast_interaction_ms.append(duration_ms)
                    elif caller_area == "advanced_interaction":
                        main_thread_db_advanced_interaction_ms.append(duration_ms)
            if "grpc" in function.lower():
                grpc_stage_ms.append(duration_ms)
            if function == "SocketDicomClient.send_request" and stage == "request_total":
                socket_request_total_ms.append(duration_ms)
            if (
                component == "download"
                and function == "SocketDicomClient.download_series"
                and stage == "dicom_file_write_batch"
            ):
                disk_write_value = _to_float(fields.get("disk_write_ms"))
                dicom_file_write_ms.append(disk_write_value if disk_write_value is not None else duration_ms)
                download_counts["dicom_file_write_batch_count"] += 1
                try:
                    dicom_file_write_bytes_total += int(float(fields.get("bytes", "0")))
                except ValueError:
                    pass
            if component == "download" and stage == "dicom_header_decode_total":
                dicom_file_read_ms.append(duration_ms)
                download_counts["dicom_file_read_batch_count"] += 1
            if component in {"download", "viewer"} and stage == "resource_probe":
                rss_mb = _to_float(fields.get("process_rss_mb"))
                if rss_mb is not None:
                    process_rss_samples_mb.append(rss_mb)
                available_mb = _to_float(fields.get("available_ram_mb"))
                if available_mb is not None:
                    available_ram_samples_mb.append(available_mb)
                try:
                    subprocess_count = int(float(fields.get("subprocess_count", "0")))
                    subprocess_count_samples.append(subprocess_count)
                except ValueError:
                    pass
            if component == "viewer" and stage == "viewer_event_total":
                viewer_switch_total_ms.append(duration_ms)
            if component == "viewer" and stage == "progressive_grow_apply":
                progressive_grow_apply_ms.append(duration_ms)
            if component == "viewer" and stage == "completion_verify":
                completion_verify_ms.append(duration_ms)
            if (
                component == "viewer"
                and stage == "load_single_series_total"
                and fields.get("source", "") in {"db_path", "filesystem_path"}
            ):
                advanced_series_load_total_ms_samples.append(duration_ms)
            if component != "db" and "connect" in stage.lower():
                server_connect_ms.append(duration_ms)
            if role == "main" and component in {"db", "download", "ipc"}:
                main_thread_blocking_io_ms.append(duration_ms)

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
                if decode_ms > 0.0:
                    fast_foreground_decode_during_drag_count += 1
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
            decode_ms = float(m.group("decode"))
            filter_ms = float(m.group("filter"))
            wl_ms = float(m.group("wl"))
            if decode_ms == 0.0 and filter_ms == 0.0 and wl_ms == 0.0:
                fast_cached_display_ms.append(float(m.group("display")))
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

        m = _DOWNLOAD_IMPACT_RE.search(line)
        if m:
            download_impact_elapsed_ms.append(float(m.group("elapsed")))

        m = _DOWNLOAD_PIPELINE_SUMMARY_RE.search(line)
        if m:
            dicom_file_write_summary_ms.append(float(m.group("disk_write")))

        m = _VIEWER_DATA_STAGE_RE.search(line)
        if m:
            viewer_data_stage = str(m.group("stage"))
            viewer_data_duration_ms = float(m.group("duration"))
            stage_counts[f"viewer.image_io.load_single_series_by_number.{viewer_data_stage}"] += 1
            if viewer_data_stage == "disk_read":
                dicom_file_read_ms.append(viewer_data_duration_ms)
                download_counts["dicom_file_read_batch_count"] += 1
            if viewer_data_stage in {"path_resolution", "path_scan", "group_images"} and "role=main" in line:
                main_thread_disk_scan_ms.append(viewer_data_duration_ms)
                if stack_drag_active and ("pydicom_qt" in line or "[FAST_" in line or "QtViewerBridge" in line):
                    main_thread_disk_scan_fast_interaction_ms.append(viewer_data_duration_ms)
                elif stack_drag_active and ("vtk_simpleitk" in line or "ImageViewer2D" in line):
                    main_thread_disk_scan_advanced_interaction_ms.append(viewer_data_duration_ms)

        m = _THUMBNAIL_END_RE.search(line)
        if m:
            thumbnail_generation_ms.append(float(m.group("duration")))

        m = _ZETABOOST_RE.search(line)
        if m:
            zeta_cache_bytes_mb.append(float(m.group("bytes")))
            zeta_cache_budget_mb.append(float(m.group("budget")))
            zeta_queue_depths.append(float(m.group("queued")) + float(m.group("inflight")))

        m = _PRIORITY_RETRY_EXHAUSTED_RE.search(line)
        if m:
            download_counts["priority_retry_exhausted_count"] += 1
            download_counts["priority_retry_exhausted_attempts_total"] += int(m.group("attempts"))
            download_counts["priority_retry_exhausted_attempts_max"] = max(
                download_counts["priority_retry_exhausted_attempts_max"],
                int(m.group("attempts")),
            )
        if "Socket connection lost" in line:
            download_counts["socket_lost_count"] += 1
        if "Worker error:" in line:
            download_counts["worker_error_count"] += 1
            if "preemption" in line.lower() or "higher priority" in line.lower():
                download_counts["preemption_worker_error_count"] += 1
        if "preemption" in line.lower() or "higher priority" in line.lower():
            download_counts["expected_preemption_signal_count"] += 1
        if "Invalid transition" in line:
            download_counts["invalid_state_transition_count"] += 1
        if "Skipped" in line and "DICOM files with read errors" in line:
            download_counts["dicom_read_error_skip_count"] += 1
        if "download_batch: No response" in line:
            download_counts["download_batch_no_response_count"] += 1
        if "stale_request_drop" in line:
            stale_request_drop_count += 1
        if "duplicate_load_suppressed" in line:
            duplicate_load_suppressed_count += 1
        m = _SEND_REQUEST_RETRY_RE.search(line)
        if m:
            download_counts["send_request_retry_count"] += 1
        m = _SEND_REQUEST_FAILED_RE.search(line)
        if m:
            download_counts["send_request_failed_count"] += 1

    duplicate_complete = sum(max(0, count - 1) for count in complete_counts.values())
    duplicate_cache_warm = sum(max(0, count - 1) for count in cache_warm_counts.values())
    total_scroll = len(scroll_total_ms)
    decode_zero = sum(1 for value in scroll_decode_ms if value == 0.0)
    total_stack_drag = len(stack_drag_total_ms)
    stack_drag_decode_zero = sum(1 for value in stack_drag_decode_ms if value == 0.0)
    total_fast_drag_kpi = len(fast_drag_event_p95_ms)
    fast_prefetch_zero_drag_count = sum(1 for value in fast_drag_prefetch_per_s if value == 0.0)
    dicom_file_write_metric_ms = dicom_file_write_ms or dicom_file_write_summary_ms
    fast_queue_wait_sessions_sorted = sorted(
        fast_queue_wait_sessions,
        key=lambda item: float(item.get("implied_queue_wait_p95_ms", 0.0) or 0.0),
        reverse=True,
    )
    fast_queue_wait_top_sessions = fast_queue_wait_sessions_sorted[:5]

    return {
        "viewer_mode_counts": dict(viewer_mode_counts),
        "stage_timing_counts": dict(stage_counts),
        "db_caller_area_counts": dict(db_caller_area_counts),
        "db_viewer_mode_counts": dict(db_viewer_mode_counts),
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
        "fast_first_image_visible_ms": round(_percentile(first_image_ms, 50), 2),
        "fast_drag_kpi_sample_count": total_fast_drag_kpi,
        "fast_drag_event_p50_ms": round(_percentile(fast_drag_event_p50_ms, 50), 2),
        "fast_drag_event_p95_ms": round(_percentile(fast_drag_event_p95_ms, 95), 2),
        "fast_drag_handler_p95_ms": round(_percentile(fast_drag_handler_p95_ms, 95), 2),
        "fast_drag_ui_lag_p95_ms": round(_percentile(fast_drag_ui_lag_max_ms, 95), 2),
        "fast_drag_ui_lag_max_ms": round(max(fast_drag_ui_lag_max_ms) if fast_drag_ui_lag_max_ms else 0.0, 2),
        "fast_prefetch_zero_drag_ratio_pct": round((fast_prefetch_zero_drag_count / total_fast_drag_kpi) * 100.0, 2) if total_fast_drag_kpi else 0.0,
        "fast_background_decode_count": int(sum(fast_drag_background_decode_count)),
        "fast_queue_wait_session_count": len(fast_queue_wait_sessions),
        "fast_queue_wait_class_counts": dict(fast_queue_wait_class_counts),
        "fast_queue_wait_p95_ms": round(
            _percentile([float(item.get("implied_queue_wait_p95_ms", 0.0) or 0.0) for item in fast_queue_wait_sessions], 95),
            2,
        ),
        "fast_queue_wait_max_ms": round(
            max([float(item.get("implied_queue_wait_max_ms", 0.0) or 0.0) for item in fast_queue_wait_sessions], default=0.0),
            2,
        ),
        "fast_queue_wait_top_sessions": fast_queue_wait_top_sessions,
        "fast_foreground_decode_during_drag_count": int(fast_foreground_decode_during_drag_count),
        "fast_cached_display_p95_ms": round(_percentile(fast_cached_display_ms, 95), 2),
        "fast_pixel_cache_hit_ratio_pct": round((src_counts.get("hit", 0) / total_scroll) * 100.0, 2) if total_scroll else 0.0,
        "fast_frame_cache_hit_ratio_pct": round((src_counts.get("hit", 0) / total_scroll) * 100.0, 2) if total_scroll else 0.0,
        "advanced_stack_sample_count": len(advanced_total_ms),
        "advanced_stack_event_p95_ms": round(_percentile(advanced_total_ms, 95), 2),
        "advanced_series_load_total_ms": round(_percentile(advanced_series_load_total_ms_samples, 95), 2),
        "advanced_series_load_total_ms_p50": round(_percentile(advanced_series_load_total_ms_samples, 50), 2),
        "advanced_first_image_visible_ms": round(_percentile(advanced_series_load_total_ms_samples, 50), 2),
        "advanced_render_p95_ms": round(_percentile(advanced_total_ms, 95), 2),
        "advanced_vtk_render_ms_p95": round(_percentile(advanced_render_ms, 95), 2),
        "advanced_simpleitk_load_ms_p95": round(_percentile(advanced_series_load_total_ms_samples, 95), 2),
        "advanced_whole_series_cache_hit_ratio_pct": 0.0,
        "advanced_set_slice_p95_ms": round(_percentile(advanced_set_slice_ms, 95), 2),
        "advanced_wl_p95_ms": round(_percentile(advanced_wl_ms, 95), 2),
        "db_transaction_scope_p95_ms": round(_percentile(db_stage_ms, 95), 2),
        "db_stage_timing_sample_count": len(db_stage_ms),
        "db_read_transaction_p95_ms": round(_percentile(db_read_stage_ms, 95), 2),
        "db_write_transaction_p95_ms": round(_percentile(db_write_stage_ms, 95), 2),
        "db_busy_retry_count": download_counts.get("db_busy_retry_count", 0),
        "main_thread_db_ms": round(sum(main_thread_db_all_ms), 2),
        "main_thread_db_p95_ms": round(_percentile(main_thread_db_all_ms, 95), 2),
        "main_thread_db_ms_during_fast_drag": round(sum(main_thread_db_fast_interaction_ms), 2),
        "main_thread_db_ms_during_advanced_stack": round(sum(main_thread_db_advanced_interaction_ms), 2),
        "server_connect_ms": round(_percentile(server_connect_ms, 95), 2),
        "grpc_metadata_fetch_ms": round(_percentile(grpc_stage_ms, 95), 2),
        "socket_batch_rtt_p95_ms": round(_percentile(socket_request_total_ms, 95), 2),
        "download_throughput_mb_s": 0.0,
        "socket_lost_count": int(download_counts.get("socket_lost_count", 0)),
        "download_progress_write_rate_per_s": 0.0,
        "dicom_file_write_ms_p95": round(_percentile(dicom_file_write_metric_ms, 95), 2),
        "dicom_file_write_batch_count": int(download_counts.get("dicom_file_write_batch_count", 0)),
        "dicom_file_write_bytes_total": int(dicom_file_write_bytes_total),
        "dicom_file_read_ms_p95": round(_percentile(dicom_file_read_ms, 95), 2),
        "dicom_file_read_batch_count": int(download_counts.get("dicom_file_read_batch_count", 0)),
        "main_thread_disk_scan_ms": round(sum(main_thread_disk_scan_ms), 2),
        "main_thread_disk_scan_p95_ms": round(_percentile(main_thread_disk_scan_ms, 95), 2),
        "main_thread_disk_scan_ms_during_fast_drag": round(sum(main_thread_disk_scan_fast_interaction_ms), 2),
        "main_thread_disk_scan_ms_during_advanced_stack": round(sum(main_thread_disk_scan_advanced_interaction_ms), 2),
        "thumbnail_generation_ms_p95": round(_percentile(thumbnail_generation_ms, 95), 2),
        "process_rss_peak_mb": round(max(process_rss_samples_mb) if process_rss_samples_mb else 0.0, 2),
        "available_ram_min_mb": round(min(available_ram_samples_mb) if available_ram_samples_mb else 0.0, 2),
        "subprocess_count": int(max(subprocess_count_samples) if subprocess_count_samples else 0),
        "main_thread_blocking_io_ms": round(sum(main_thread_blocking_io_ms), 2),
        "main_thread_blocking_io_p95_ms": round(_percentile(main_thread_blocking_io_ms, 95), 2),
        "download_impact_elapsed_p95_ms": round(_percentile(download_impact_elapsed_ms, 95), 2),
        "priority_retry_exhausted_count": int(download_counts.get("priority_retry_exhausted_count", 0)),
        "priority_retry_exhausted_attempts_max": int(download_counts.get("priority_retry_exhausted_attempts_max", 0)),
        "preemption_worker_error_count": int(download_counts.get("preemption_worker_error_count", 0)),
        "download_preemption_fail_count": int(download_counts.get("preemption_worker_error_count", 0)),
        "worker_error_count": int(download_counts.get("worker_error_count", 0)),
        "expected_preemption_signal_count": int(download_counts.get("expected_preemption_signal_count", 0)),
        "invalid_state_transition_count": int(download_counts.get("invalid_state_transition_count", 0)),
        "send_request_retry_count": int(download_counts.get("send_request_retry_count", 0)),
        "send_request_failed_count": int(download_counts.get("send_request_failed_count", 0)),
        "download_batch_no_response_count": int(download_counts.get("download_batch_no_response_count", 0)),
        "dicom_read_error_skip_count": int(download_counts.get("dicom_read_error_skip_count", 0)),
        "zeta_cache_bytes_peak_mb": round(max(zeta_cache_bytes_mb) if zeta_cache_bytes_mb else 0.0, 2),
        "zeta_cache_budget_peak_mb": round(max(zeta_cache_budget_mb) if zeta_cache_budget_mb else 0.0, 2),
        "zeta_queue_depth_p95": round(_percentile(zeta_queue_depths, 95), 2),
        "viewer_switch_total_ms_p50": round(_percentile(viewer_switch_total_ms, 50), 2),
        "viewer_switch_total_ms_p95": round(_percentile(viewer_switch_total_ms, 95), 2),
        "viewer_switch_sample_count": len(viewer_switch_total_ms),
        "progressive_grow_apply_ms_p50": round(_percentile(progressive_grow_apply_ms, 50), 2),
        "progressive_grow_apply_ms_p95": round(_percentile(progressive_grow_apply_ms, 95), 2),
        "progressive_grow_sample_count": len(progressive_grow_apply_ms),
        "completion_verify_ms_p95": round(_percentile(completion_verify_ms, 95), 2),
        "completion_verify_sample_count": len(completion_verify_ms),
        "stale_request_drop_count": stale_request_drop_count,
        "duplicate_load_suppressed_count": duplicate_load_suppressed_count,
    }


def parse_aipacs_log_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {
        "viewer": "AI-PACS",
        "mode": "log-parse",
        "log_path": str(path),
        "log_metrics": parse_aipacs_log_text(text),
    }


# ---------------------------------------------------------------------------
# Overlap-scenario parser (F0.2)
#
# Parses the [OVERLAP_SCENARIO] log tag emitted by Lightweight2DPipeline when
# `is_heavy_download_active() and not is_viewed_series_complete(series_number)`.
# Tag format (introduced in plan step F2.1):
#
#   [OVERLAP_SCENARIO] frame idx=<int> cache=<hit|surrogate|decode>
#       decode_ms=<f> wl_ms=<f> total_ms=<f> settled=<True|False>
#
# Optional trailing key=value fields are tolerated (and ignored) so future
# extensions do not break the parser.
#
# This parser is intentionally separate from parse_aipacs_log_text so that:
#   - the existing parser surface stays byte-identical (no regression),
#   - overlap KPIs can be computed/inspected in isolation.
# ---------------------------------------------------------------------------

_OVERLAP_TAG_RE = re.compile(
    r"\[OVERLAP_SCENARIO\]\s+frame\s+"
    r"idx=(?P<idx>\d+)\s+"
    r"cache=(?P<cache>hit|surrogate|decode)\s+"
    r"decode_ms=(?P<decode>[0-9.]+)\s+"
    r"wl_ms=(?P<wl>[0-9.]+)\s+"
    r"total_ms=(?P<total>[0-9.]+)\s+"
    r"settled=(?P<settled>True|False)"
    # F2.1b: optional sentinel reason for forced (always-emit) samples.
    # Older logs (pre-F2.1b) do not have this field; the trailing group
    # is non-capturing-optional so the parser tolerates both shapes.
    r"(?:\s+sentinel=(?P<sentinel>\S+))?"
)

# F2.3: leading diagnostic-logging timestamp probe. Production emits
# "YYYY-MM-DD HH:MM:SS.uuuuuu" (dot, microseconds); the synthetic runner's
# default asctime emits "YYYY-MM-DD HH:MM:SS,mmm" (comma, milliseconds).
# Both shapes are captured. The fractional component is normalized to
# seconds (float) so the parser does not care which form is present.
_OVERLAP_TS_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+"
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})"
    r"(?:[.,](?P<frac>\d{1,6}))?"
)


def _parse_overlap_timestamp_seconds(line: str) -> Optional[float]:
    """Return monotonic-ish seconds-since-epoch for a log line, or None.

    Used by ``parse_overlap_log_text`` to derive ``overlap_effective_fps``
    from wall-clock spacing of [OVERLAP_SCENARIO] samples (F2.3). We only
    need a relative ordinal so we accept either microsecond or millisecond
    precision and ignore the date when computing deltas across same-day
    runs (callers always operate on a single contiguous log window).
    """
    m = _OVERLAP_TS_RE.match(line)
    if not m:
        return None
    try:
        h = int(m.group("h"))
        mi = int(m.group("m"))
        s = int(m.group("s"))
        frac_str = m.group("frac") or ""
        # Pad/truncate to microseconds.
        frac_us = int((frac_str + "000000")[:6]) if frac_str else 0
        # Date is included so cross-day runs don't wrap; treat as days*86400.
        # We avoid datetime parsing to keep the harness import-free.
        y, mo, d = (int(x) for x in m.group("date").split("-"))
        # A simple ordinal: (y * 372 + mo * 31 + d) is monotonic for the
        # narrow window we care about (single capture session). Multiply
        # by seconds-per-day to keep units consistent with h/m/s/frac.
        day_ord = (y * 372 + mo * 31 + d) * 86400.0
        return day_ord + h * 3600.0 + mi * 60.0 + s + frac_us / 1_000_000.0
    except (TypeError, ValueError):
        return None


def parse_overlap_log_text(text: str) -> Dict[str, Any]:
    """Extract overlap-scenario KPIs from runtime log text.

    Returns a payload with the canonical overlap_* keys defined in
    docs/performance/FAST_VIEWER_KPI_CATALOG.md (Phase F0.2).

    All values are best-effort; if zero overlap samples were observed the
    KPIs are emitted as 0.0 / 0 with `sample_count = 0` so downstream
    diff tooling can detect the empty-run case explicitly.
    """
    total_ms: List[float] = []
    decode_ms: List[float] = []
    wl_ms: List[float] = []
    cache_counts: Counter[str] = Counter()
    settled_counts: Counter[str] = Counter()
    timeline_seconds: List[float] = []  # filled from leading "[ts]" if present
    wall_seconds: List[float] = []  # F2.3: seconds-since-epoch per overlap sample
    # F2.4 (post-F0.5 retarget): per-source total_ms buckets so the harness
    # can report tail latency for the path that actually drives user-visible
    # spikes (decode-cache-miss) without it being washed out by the 95%+ of
    # surrogate samples reporting total_ms <= 1ms.
    total_ms_by_cache: Dict[str, List[float]] = {"hit": [], "surrogate": [], "decode": []}
    total_ms_by_settled: Dict[str, List[float]] = {"True": [], "False": []}
    # decode_ms collected only from cache=decode samples (the only path
    # where decode_ms is non-zero by construction). Surfaces the "real"
    # decode tail without dilution.
    decode_only_ms: List[float] = []
    # Slow-frame (>16ms) breakdown by cache source for retarget plan KPI
    # 'overlap_slow_frame_source_breakdown'.
    slow_frame_by_cache: Dict[str, int] = {"hit": 0, "surrogate": 0, "decode": 0}
    # F2.1b: count sentinel-emit reasons so the harness can verify that
    # forced emits (decode / drag_begin / drag_end) are reaching the log.
    sentinel_counts: Counter[str] = Counter()
    # foreground_wait is reported by a different (future) tag; kept as 0.0
    # until F4.x ships its own [OVERLAP_FG_WAIT] sub-tag.
    foreground_wait_ms: List[float] = []

    # F2.4b (post-live-run-2026-04-29): aggregate end-of-burst summaries
    # from [FAST_DRAG_KPI] lines so the same parse_overlap_log_text call
    # surfaces real-world Qt event-loop and UI-lag KPIs alongside the
    # per-frame [OVERLAP_SCENARIO] aggregates. These end-of-burst lines
    # are 100% sampled (one per drag) so log volume is not a concern.
    drag_event_p95_ms: List[float] = []
    drag_handler_p95_ms: List[float] = []
    drag_ui_lag_max_ms: List[float] = []
    drag_prefetch_per_s: List[float] = []
    drag_background_decode_count_total: int = 0
    drag_burst_count: int = 0

    # Optional leading-timestamp probe: most diagnostic logs begin with
    # "YYYY-MM-DD HH:MM:SS,mmm" or "YYYY-MM-DD HH:MM:SS.uuuuuu". F2.3 uses
    # the wall-clock delta between the first and last overlap sample to
    # compute effective fps so the value reflects real frame cadence
    # rather than per-sample compute time.
    for line_idx, raw in enumerate(text.splitlines()):
        m = _OVERLAP_TAG_RE.search(raw)
        if not m:
            continue
        try:
            t_total = float(m.group("total"))
            t_decode = float(m.group("decode"))
            t_wl = float(m.group("wl"))
        except (TypeError, ValueError):
            continue
        total_ms.append(t_total)
        decode_ms.append(t_decode)
        wl_ms.append(t_wl)
        cache_src = m.group("cache")
        settled_key = m.group("settled")
        cache_counts[cache_src] += 1
        settled_counts[settled_key] += 1
        timeline_seconds.append(float(line_idx))
        ts = _parse_overlap_timestamp_seconds(raw)
        if ts is not None:
            wall_seconds.append(ts)
        # F2.4 splits.
        if cache_src in total_ms_by_cache:
            total_ms_by_cache[cache_src].append(t_total)
        if settled_key in total_ms_by_settled:
            total_ms_by_settled[settled_key].append(t_total)
        if cache_src == "decode":
            decode_only_ms.append(t_decode)
        if t_total > 16.0 and cache_src in slow_frame_by_cache:
            slow_frame_by_cache[cache_src] += 1
        # F2.1b: track sentinel reason if present (older logs have no group).
        sentinel_reason = m.groupdict().get("sentinel")
        if sentinel_reason and sentinel_reason != "-":
            sentinel_counts[sentinel_reason] += 1

    # F2.4b: scan [FAST_DRAG_KPI] end-of-burst lines independently. These
    # are emitted by qt_viewer_bridge._log_drag_metrics_summary at drag-
    # end; one line per burst; not gated by overlap predicate. We include
    # them in the overlap payload because the live 2026-04-28 run showed
    # event_p95=607.9ms / ui_lag_max=363.9ms during overlap, which the
    # per-frame [OVERLAP_SCENARIO] tag cannot capture (it only reports
    # pipeline compute time, not Qt event-loop spacing).
    for raw in text.splitlines():
        m_drag = _FAST_DRAG_KPI_RE.search(raw)
        if not m_drag:
            continue
        try:
            drag_event_p95_ms.append(float(m_drag.group("event_p95")))
            drag_handler_p95_ms.append(float(m_drag.group("handler_p95")))
            drag_ui_lag_max_ms.append(float(m_drag.group("ui_lag_max")))
            drag_prefetch_per_s.append(float(m_drag.group("prefetch_per_s")))
            drag_background_decode_count_total += int(m_drag.group("background_decode_count"))
            drag_burst_count += 1
        except (TypeError, ValueError):
            continue

    sample_count = len(total_ms)
    cache_hits = cache_counts.get("hit", 0) + cache_counts.get("surrogate", 0)
    cache_hit_ratio = (cache_hits / sample_count * 100.0) if sample_count else 0.0

    # Foreground wait p95: placeholder until dedicated tag exists.
    fg_wait_p95 = _percentile(foreground_wait_ms, 95.0) if foreground_wait_ms else 0.0

    # Slow-frame share: total_ms > 16 ms.
    slow_frame_count = sum(1 for v in total_ms if v > 16.0)
    slow_frame_pct = (slow_frame_count / sample_count * 100.0) if sample_count else 0.0

    # Effective FPS — F2.3:
    #   primary: wall-clock delta between first and last sample timestamp
    #            captured from the diagnostic_logging prefix. This reflects
    #            real frame cadence (frames per second of wall time), not
    #            per-frame compute time.
    #   fallback: if <2 timestamps were parsed (e.g. the log lines did not
    #            carry a leading asctime, as in unit-test fixtures built
    #            via _build_log), fall back to the legacy formula
    #            1000 / median(total_ms).
    effective_fps_source = "none"
    if len(wall_seconds) >= 2:
        wall_span = wall_seconds[-1] - wall_seconds[0]
        if wall_span > 0:
            effective_fps = (len(wall_seconds) - 1) / wall_span
            effective_fps_source = "wall_clock"
        else:
            effective_fps = 0.0
    elif total_ms:
        median_total = _percentile(total_ms, 50.0)
        effective_fps = (1000.0 / median_total) if median_total > 0 else 0.0
        if effective_fps > 0:
            effective_fps_source = "median_total_ms"
    else:
        effective_fps = 0.0

    # Pixel-hash match percentages are populated only by the F1 harness;
    # the runtime log cannot observe them directly. Emit as None so the
    # diff tooling can distinguish "not measured" from "0%".
    decode_sample_count = cache_counts.get("decode", 0)
    decode_sample_share = (decode_sample_count / sample_count * 100.0) if sample_count else 0.0
    settled_total = total_ms_by_settled["True"]
    return {
        "overlap_sample_count": sample_count,
        "overlap_set_slice_present_p95_ms": round(_percentile(total_ms, 95.0), 2),
        "overlap_set_slice_present_p50_ms": round(_percentile(total_ms, 50.0), 2),
        "overlap_decode_p95_ms": round(_percentile(decode_ms, 95.0), 2),
        "overlap_decode_p50_ms": round(_percentile(decode_ms, 50.0), 2),
        "overlap_wl_p95_ms": round(_percentile(wl_ms, 95.0), 2),
        "overlap_cache_hit_ratio_pct": round(cache_hit_ratio, 2),
        "overlap_cache_breakdown": {
            "hit": cache_counts.get("hit", 0),
            "surrogate": cache_counts.get("surrogate", 0),
            "decode": cache_counts.get("decode", 0),
        },
        "overlap_settled_breakdown": {
            "settled_true": settled_counts.get("True", 0),
            "settled_false": settled_counts.get("False", 0),
        },
        "overlap_slow_frame_count_16ms": slow_frame_count,
        "overlap_slow_frame_pct_16ms": round(slow_frame_pct, 2),
        "overlap_slow_frame_source_breakdown": dict(slow_frame_by_cache),
        # F2.4 retarget KPIs — split tail latency by cache source so the
        # decode-cache-miss path (the only one >1ms in the harsh anchor)
        # is not washed out by the surrogate-dominated mean.
        "overlap_hit_present_p95_ms": round(_percentile(total_ms_by_cache["hit"], 95.0), 2),
        "overlap_surrogate_present_p95_ms": round(_percentile(total_ms_by_cache["surrogate"], 95.0), 2),
        "overlap_decode_only_p95_ms": round(_percentile(total_ms_by_cache["decode"], 95.0), 2),
        "overlap_decode_only_max_ms": round(max(total_ms_by_cache["decode"]), 2)
            if total_ms_by_cache["decode"] else 0.0,
        "overlap_decode_sample_count": decode_sample_count,
        "overlap_decode_sample_share_pct": round(decode_sample_share, 2),
        "overlap_settled_present_p95_ms": round(_percentile(settled_total, 95.0), 2),
        "overlap_settled_sample_count": len(settled_total),
        "overlap_effective_fps": round(effective_fps, 2),
        "overlap_effective_fps_source": effective_fps_source,
        "overlap_foreground_wait_p95_ms": round(fg_wait_p95, 2),
        "overlap_pixel_hash_match_pct_settled": None,
        "overlap_pixel_hash_match_pct_surrogate": None,
        # F2.1b: sentinel emit visibility — counts of decode / drag_begin
        # / drag_end forced emits in the parsed window. Pre-F2.1b logs
        # have no sentinel field and report zeros across the board.
        "overlap_sentinel_breakdown": {
            "decode": sentinel_counts.get("decode", 0),
            "drag_begin": sentinel_counts.get("drag_begin", 0),
            "drag_end": sentinel_counts.get("drag_end", 0),
            "other": sum(v for k, v in sentinel_counts.items()
                         if k not in ("decode", "drag_begin", "drag_end")),
        },
        "overlap_sentinel_emit_count": sum(sentinel_counts.values()),
        # F2.4b: real-world Tier-2 KPIs from [FAST_DRAG_KPI] end-of-burst
        # summaries. These are the metrics the user actually perceives
        # (Qt event-loop spacing, ui_lag_max). The per-frame [OVERLAP_*]
        # tag CANNOT measure these — it only reports pipeline compute
        # time. Live 2026-04-28 23:01 run showed event_p95=607.9ms /
        # ui_lag_max=363.9ms during overlap, none of which is visible
        # in the per-frame totals.
        "overlap_drag_burst_count": drag_burst_count,
        "overlap_drag_event_p95_max_ms": round(max(drag_event_p95_ms), 2)
            if drag_event_p95_ms else 0.0,
        "overlap_drag_event_p95_p95_ms": round(_percentile(drag_event_p95_ms, 95.0), 2),
        "overlap_drag_handler_p95_max_ms": round(max(drag_handler_p95_ms), 2)
            if drag_handler_p95_ms else 0.0,
        "overlap_drag_ui_lag_max_max_ms": round(max(drag_ui_lag_max_ms), 2)
            if drag_ui_lag_max_ms else 0.0,
        "overlap_drag_ui_lag_max_p95_ms": round(_percentile(drag_ui_lag_max_ms, 95.0), 2),
        "overlap_drag_prefetch_per_s_avg": round(
            sum(drag_prefetch_per_s) / len(drag_prefetch_per_s), 2
        ) if drag_prefetch_per_s else 0.0,
        "overlap_drag_background_decode_count_total": drag_background_decode_count_total,
    }


def parse_overlap_log_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {
        "viewer": "AI-PACS",
        "mode": "overlap-log-parse",
        "scenario": "aipacs_live_download_overlap",
        "log_path": str(path),
        "overlap_metrics": parse_overlap_log_text(text),
    }


def parse_priority_handoff_log_text(text: str) -> Dict[str, Any]:
    """Parse `[INTENT_PRIORITY]` records emitted by SeriesIntentCoordinator (F3.5.1).

    Returns a dict with KPI keys covering the DM priority-handoff path:
      - samples: total `[INTENT_PRIORITY]` lines parsed.
      - begin_count / tick_count / defer_count / recover_count / exhaust_count / started_count.
      - primary_exhaust_count / recovery_exhaust_count: counts of `tag=exhaust`
        partitioned by the `branch=primary|recovery` field. The `recover` tag also
        bumps `primary_exhaust_count` because it marks the moment the primary 90×200 ms
        chain expired (entering recovery is the primary-exhaust event from the user's POV).
      - p50_ms / p95_ms / max_ms: percentile / max of `elapsed_ms` extracted from `tag=started`
        emissions (handoff latency = drag-drop begin → worker started). Empty samples → 0.0.
      - pool_busy_ratio_pct: percentage of defer events with `pool_busy=True` — when this
        is high the bottleneck is peer-worker holding the slot (F3.5.2 wall-clock fix);
        when low, the bottleneck is reclamation race (F3.5.2 prefer_study_uid fix).
    """
    started_elapsed_ms: list = []
    counts = {
        "begin": 0,
        "tick": 0,
        "defer": 0,
        "recover": 0,
        "exhaust": 0,
        "started": 0,
    }
    primary_exhaust = 0
    recovery_exhaust = 0
    pool_busy_true = 0
    pool_busy_total = 0
    samples = 0
    # F3.5.2 — V2 wall-clock retry path bookkeeping.
    v2_begin = 0
    v2_started = 0
    v2_exhaust_pool_busy = 0
    v2_exhaust_reclaimed = 0
    v2_exhaust_state_lost = 0
    v2_exhaust_timeout = 0
    v2_defer_reclaimed = 0

    for m in _INTENT_PRIORITY_RE.finditer(text or ""):
        samples += 1
        tag = m.group("tag")
        branch = m.group("branch")
        reason = m.group("reason")
        if tag in counts:
            counts[tag] += 1
        if tag == "started":
            try:
                started_elapsed_ms.append(int(m.group("elapsed_ms")))
            except (TypeError, ValueError):
                pass
        if tag == "defer":
            pool_busy_total += 1
            if m.group("pool_busy") == "True":
                pool_busy_true += 1
            if branch == "v2" and reason == "reclaimed":
                v2_defer_reclaimed += 1
        # `recover` marks primary chain expiration (entering recovery round).
        if tag == "recover":
            primary_exhaust += 1
        if tag == "exhaust":
            if branch == "primary":
                primary_exhaust += 1
            elif branch == "recovery":
                recovery_exhaust += 1
            elif branch == "v2":
                # V2 wall-clock budget exhaust — partition by reason.
                if reason == "pool_busy":
                    v2_exhaust_pool_busy += 1
                elif reason == "reclaimed":
                    v2_exhaust_reclaimed += 1
                elif reason == "state_lost":
                    v2_exhaust_state_lost += 1
                else:
                    v2_exhaust_timeout += 1
            else:
                # Defensive: branch missing — count as recovery (legacy path).
                recovery_exhaust += 1
        if tag == "begin" and branch == "v2":
            v2_begin += 1
        if tag == "started" and branch == "v2":
            v2_started += 1

    if started_elapsed_ms:
        p50 = round(_percentile(started_elapsed_ms, 50), 2)
        p95 = round(_percentile(started_elapsed_ms, 95), 2)
        max_ms = float(max(started_elapsed_ms))
    else:
        p50 = 0.0
        p95 = 0.0
        max_ms = 0.0

    pool_busy_ratio = (
        round((pool_busy_true / pool_busy_total) * 100.0, 2)
        if pool_busy_total > 0
        else 0.0
    )

    return {
        "samples": samples,
        "begin_count": counts["begin"],
        "tick_count": counts["tick"],
        "defer_count": counts["defer"],
        "recover_count": counts["recover"],
        "exhaust_count": counts["exhaust"],
        "started_count": counts["started"],
        "primary_exhaust_count": primary_exhaust,
        "recovery_exhaust_count": recovery_exhaust,
        "overlap_priority_handoff_latency_p50_ms": p50,
        "overlap_priority_handoff_latency_p95_ms": p95,
        "overlap_priority_handoff_latency_max_ms": round(max_ms, 2),
        "overlap_priority_retry_primary_exhaust_count": primary_exhaust,
        "overlap_priority_retry_recovery_exhaust_count": recovery_exhaust,
        "overlap_priority_handoff_pool_busy_ratio_pct": pool_busy_ratio,
        # F3.5.2 — V2 wall-clock retry counters (zeros when V2 disabled).
        "v2_begin_count": v2_begin,
        "v2_started_count": v2_started,
        "v2_exhaust_pool_busy_count": v2_exhaust_pool_busy,
        "v2_exhaust_reclaimed_count": v2_exhaust_reclaimed,
        "v2_exhaust_state_lost_count": v2_exhaust_state_lost,
        "v2_exhaust_timeout_count": v2_exhaust_timeout,
        "v2_defer_reclaimed_count": v2_defer_reclaimed,
        "overlap_priority_handoff_v2_total_exhaust_count": (
            v2_exhaust_pool_busy
            + v2_exhaust_reclaimed
            + v2_exhaust_state_lost
            + v2_exhaust_timeout
        ),
    }


def parse_priority_handoff_log_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {
        "viewer": "AI-PACS",
        "mode": "priority-handoff-parse",
        "scenario": "aipacs_dm_priority_handoff",
        "log_path": str(path),
        "priority_handoff_metrics": parse_priority_handoff_log_text(text),
    }


def parse_slot_timing_log_text(text: str) -> Dict[str, Any]:
    """Parse `[SLOT_TIMING]` records emitted by `modules/viewer/fast/slot_timing.py` (G6+).

    Aggregates per-tag percentiles and totals so the harness can attribute
    drag-active main-thread stalls to specific Qt slots / callsites without
    requiring a per-call attribution from the F11 stack sampler.

    Returned dict (stable contract):
      - samples: total `[SLOT_TIMING]` lines parsed.
      - drag_sample_count / idle_sample_count: counts split by `drag_active`.
      - per_tag: ``{tag: {samples, drag_samples, p50_ms, p95_ms, max_ms,
                           drag_p95_ms, drag_max_ms, drag_total_ms}}``.
        Idle thresholds (default 30 ms) and drag thresholds (default 8 ms)
        differ, so `drag_*` percentiles are computed from the drag-only subset.
      - top_drag_tags: top 5 tags by `drag_total_ms` (sum of durations whose
        `drag_active=True`). This is the prime "where is the silent blocker"
        signal — the tag with the largest drag_total_ms is the candidate for
        the next G-step defer.
      - overlap_slot_timing_drag_blocked_ms_total: sum of drag_total_ms across
        all tags. A budget overrun on this single number proves the user-visible
        freeze surface is in observed slots and not in unobserved code.
      - overlap_slot_timing_worst_drag_call_ms: max single-call duration among
        drag-active samples (any tag).

    The parser is robust to legacy / future variations: missing `extra=` is
    accepted; unknown tags are bucketed normally.
    """
    samples = 0
    drag_count = 0
    idle_count = 0
    worst_drag_ms = 0.0
    worst_drag_tag = ""

    # Per-tag working lists.
    tag_all: Dict[str, list] = {}
    tag_drag: Dict[str, list] = {}
    tag_drag_total: Dict[str, float] = {}

    for m in _SLOT_TIMING_RE.finditer(text or ""):
        samples += 1
        tag = m.group("tag")
        try:
            duration_ms = float(m.group("duration_ms"))
        except (TypeError, ValueError):
            continue
        drag_active = m.group("drag_active") == "True"

        tag_all.setdefault(tag, []).append(duration_ms)
        if drag_active:
            drag_count += 1
            tag_drag.setdefault(tag, []).append(duration_ms)
            tag_drag_total[tag] = tag_drag_total.get(tag, 0.0) + duration_ms
            if duration_ms > worst_drag_ms:
                worst_drag_ms = duration_ms
                worst_drag_tag = tag
        else:
            idle_count += 1

    per_tag: Dict[str, Dict[str, Any]] = {}
    for tag, all_values in tag_all.items():
        drag_values = tag_drag.get(tag, [])
        per_tag[tag] = {
            "samples": len(all_values),
            "drag_samples": len(drag_values),
            "p50_ms": round(_percentile(all_values, 50), 2),
            "p95_ms": round(_percentile(all_values, 95), 2),
            "max_ms": round(float(max(all_values)), 2),
            "drag_p95_ms": (
                round(_percentile(drag_values, 95), 2) if drag_values else 0.0
            ),
            "drag_max_ms": (
                round(float(max(drag_values)), 2) if drag_values else 0.0
            ),
            "drag_total_ms": round(tag_drag_total.get(tag, 0.0), 2),
        }

    # Rank top drag tags by total drag-active time (the budget signal).
    ranked = sorted(
        per_tag.items(), key=lambda kv: kv[1]["drag_total_ms"], reverse=True
    )
    top_drag_tags = [
        {
            "tag": tag,
            "drag_total_ms": stats["drag_total_ms"],
            "drag_samples": stats["drag_samples"],
            "drag_p95_ms": stats["drag_p95_ms"],
            "drag_max_ms": stats["drag_max_ms"],
        }
        for tag, stats in ranked[:5]
        if stats["drag_total_ms"] > 0.0
    ]

    drag_blocked_total = round(
        sum(stats["drag_total_ms"] for stats in per_tag.values()), 2
    )

    return {
        "samples": samples,
        "drag_sample_count": drag_count,
        "idle_sample_count": idle_count,
        "per_tag": per_tag,
        "top_drag_tags": top_drag_tags,
        "overlap_slot_timing_drag_blocked_ms_total": drag_blocked_total,
        "overlap_slot_timing_worst_drag_call_ms": round(worst_drag_ms, 2),
        "overlap_slot_timing_worst_drag_tag": worst_drag_tag,
    }


def parse_slot_timing_log_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {
        "viewer": "AI-PACS",
        "mode": "slot-timing-parse",
        "scenario": "aipacs_fast_silent_blocker_triage",
        "log_path": str(path),
        "slot_timing_metrics": parse_slot_timing_log_text(text),
    }


def parse_dm_rebuild_log_text(text: str) -> Dict[str, Any]:
    """Parse ``[DM_REBUILD]`` log lines emitted by the DM table refresh.

    Returns counters and percentile statistics that quantify the
    historical recursion bug (silent main-thread blocker fixed in G8).

    Output schema:

    - ``dm_rebuild_count``           : total ``event=exit`` lines
    - ``dm_rebuild_recursive_count`` : exits with ``depth >= 2``
    - ``dm_rebuild_reenter_skip_count`` : ``event=reenter_skip`` lines
      (G8.2 guard catching attempted recursion — should be 0 in
      well-behaved code, > 0 indicates upstream signal regressions)
    - ``dm_rebuild_max_depth``       : highest ``depth`` observed at exit
    - ``dm_rebuild_duration_p50_ms`` / ``_p95_ms`` / ``_max_ms``
    - ``dm_rebuild_per_session_total_ms``
    - ``top_callers``                : list of dicts ``{caller, count, total_ms}``
      sorted by ``total_ms`` descending (top 5)

    Plan reference: docs/plans/performance/DM_TABLE_REBUILD_STORM_2026-04-29.md
    """
    durations: List[float] = []
    by_caller: Dict[str, Dict[str, float]] = {}
    recursive_count = 0
    max_depth = 0
    reenter_skip_count = 0
    enter_count = 0

    for m in _DM_REBUILD_RE.finditer(text or ""):
        event = m.group("event")
        depth = int(m.group("depth") or 0)
        if event == "enter":
            enter_count += 1
            continue
        if event == "reenter_skip":
            reenter_skip_count += 1
            continue
        if event != "exit":
            continue
        # exit
        d_raw = m.group("duration_ms")
        if d_raw is None:
            continue
        d = float(d_raw)
        durations.append(d)
        if depth > max_depth:
            max_depth = depth
        if depth >= 2:
            recursive_count += 1
        caller = m.group("caller") or "unknown"
        slot = by_caller.setdefault(caller, {"count": 0, "total_ms": 0.0})
        slot["count"] += 1
        slot["total_ms"] += d

    durations_sorted = sorted(durations)
    n = len(durations_sorted)

    def _percentile(p: float) -> float:
        if n == 0:
            return 0.0
        idx = max(0, min(n - 1, int(round(p / 100.0 * (n - 1)))))
        return float(durations_sorted[idx])

    top_callers = sorted(
        (
            {"caller": c, "count": int(v["count"]), "total_ms": round(v["total_ms"], 3)}
            for c, v in by_caller.items()
        ),
        key=lambda r: r["total_ms"],
        reverse=True,
    )[:5]

    return {
        "dm_rebuild_count": len(durations),
        "dm_rebuild_enter_count": enter_count,
        "dm_rebuild_recursive_count": recursive_count,
        "dm_rebuild_reenter_skip_count": reenter_skip_count,
        "dm_rebuild_max_depth": max_depth,
        "dm_rebuild_duration_p50_ms": round(_percentile(50), 3),
        "dm_rebuild_duration_p95_ms": round(_percentile(95), 3),
        "dm_rebuild_duration_max_ms": round(durations_sorted[-1], 3) if n else 0.0,
        "dm_rebuild_per_session_total_ms": round(sum(durations), 3),
        "top_callers": top_callers,
    }


def parse_dm_priority_transition_log_text(text: str) -> Dict[str, Any]:
    """Parse ``[DM_PRIORITY_TRANSITION]`` lines.

    The defining counter is ``priority_combo_signal_during_rebuild_count``
    — the number of ``_on_priority_changed`` invocations that fired
    while ``_refresh_table_order`` was running. Pre-G8.1 this was 1
    per drag-drop. Post-G8.1 it must be 0; any non-zero value is a
    regression alarm.
    """
    during_rebuild = 0
    total = 0
    by_priority: Dict[str, int] = {}
    for m in _DM_PRIORITY_TRANSITION_RE.finditer(text or ""):
        total += 1
        if m.group("during_rebuild") == "True":
            during_rebuild += 1
        new = m.group("new")
        by_priority[new] = by_priority.get(new, 0) + 1

    return {
        "priority_combo_signal_count": total,
        "priority_combo_signal_during_rebuild_count": during_rebuild,
        "priority_combo_signal_by_priority": by_priority,
    }


def parse_dm_rebuild_log_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {
        "viewer": "AI-PACS",
        "mode": "dm-rebuild-parse",
        "scenario": "aipacs_dm_table_rebuild_storm_triage",
        "log_path": str(path),
        "dm_rebuild_metrics": parse_dm_rebuild_log_text(text),
        "dm_priority_transition_metrics": parse_dm_priority_transition_log_text(text),
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
        "# Unified Viewer Block KPI Summary",
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


def _cmd_parse_overlap_log(args: argparse.Namespace) -> int:
    """F0.2: extract overlap-scenario KPIs from a runtime log file."""
    payload = parse_overlap_log_file(Path(args.log))
    if getattr(args, "scenario", None):
        payload["scenario"] = str(args.scenario)
    out = Path(args.output) if args.output else _default_output("overlap_kpi", "json")
    _write_json(out, payload)
    print(out)
    return 0


def _cmd_parse_priority_handoff_log(args: argparse.Namespace) -> int:
    """F3.5.1: extract DM priority-handoff KPIs from a runtime log file."""
    payload = parse_priority_handoff_log_file(Path(args.log))
    if getattr(args, "scenario", None):
        payload["scenario"] = str(args.scenario)
    out = Path(args.output) if args.output else _default_output("priority_handoff_kpi", "json")
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

    p_overlap = sub.add_parser(
        "parse-overlap-log",
        help="Extract overlap-scenario KPIs ([OVERLAP_SCENARIO] tag) from a log file",
    )
    p_overlap.add_argument("--log", required=True)
    p_overlap.add_argument(
        "--scenario",
        default="aipacs_live_download_overlap",
        help="Scenario id stored in the output payload",
    )
    p_overlap.add_argument("--output")
    p_overlap.set_defaults(func=_cmd_parse_overlap_log)

    p_handoff = sub.add_parser(
        "parse-priority-handoff-log",
        help="Extract DM priority-handoff KPIs ([INTENT_PRIORITY] tag) from a log file",
    )
    p_handoff.add_argument("--log", required=True)
    p_handoff.add_argument(
        "--scenario",
        default="aipacs_dm_priority_handoff",
        help="Scenario id stored in the output payload",
    )
    p_handoff.add_argument("--output")
    p_handoff.set_defaults(func=_cmd_parse_priority_handoff_log)

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
