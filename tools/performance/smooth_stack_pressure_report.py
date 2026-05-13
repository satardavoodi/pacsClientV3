from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


_SUMMARY_TAG = "[FAST_STACK_PRESSURE]"
_PHASE_TAG = "[FAST_STACK_PRESSURE_PHASE]"
_FG_DISK_TAG = "[FAST_FG_DISK]"
_PACING_TAG = "[FAST_EVENT_PACING]"
_FIELD_RE = re.compile(r"(?P<key>[A-Za-z0-9_]+)=(?P<value>[^\s]+)")


def _coerce_value(value: str) -> Any:
    lowered = value.strip()
    if lowered in {"True", "False"}:
        return lowered == "True"
    try:
        if any(ch in lowered for ch in (".", "e", "E")):
            return float(lowered)
        return int(lowered)
    except Exception:
        return lowered


def _parse_fields(line: str, tag: str) -> dict[str, Any]:
    idx = line.find(tag)
    if idx < 0:
        return {}
    tail = line[idx + len(tag):]
    return {
        match.group("key"): _coerce_value(match.group("value"))
        for match in _FIELD_RE.finditer(tail)
    }


def classify_pressure_bottleneck(row: dict[str, Any]) -> str:
    longest_ui_gap_ms = float(row.get("longest_ui_gap_max_ms", 0.0) or 0.0)
    handler_p95_ms = float(row.get("handler_p95_ms", 0.0) or 0.0)
    main_thread_stall_count = int(row.get("main_thread_stall_count", 0) or 0)
    disk_write_q_max = int(row.get("disk_write_q_max", 0) or 0)
    disk_write_mb_s_p95 = float(row.get("disk_write_mb_s_p95", 0.0) or 0.0)
    proc_write_mb_s_p95 = float(row.get("proc_write_mb_s_p95", 0.0) or 0.0)
    decode_q_p95 = int(row.get("decode_q_p95", 0) or 0)
    frame_q_p95 = int(row.get("frame_q_p95", 0) or 0)
    active_download_max = int(row.get("active_download_max", 0) or 0)
    progressive_visible_ratio_pct = float(row.get("progressive_visible_ratio_pct", 0.0) or 0.0)
    cpu_p95_pct = float(row.get("cpu_p95_pct", 0.0) or 0.0)
    prefetch_shedding_ratio_pct = float(row.get("prefetch_shedding_ratio_pct", 0.0) or 0.0)

    if main_thread_stall_count > 0 and longest_ui_gap_ms >= 100.0 and handler_p95_ms < 16.0:
        return "main_thread_block"
    if disk_write_q_max >= 4 or disk_write_mb_s_p95 >= 20.0 or proc_write_mb_s_p95 >= 10.0:
        return "disk_pressure"
    if decode_q_p95 >= 2 or frame_q_p95 >= 2:
        return "decode_backlog"
    if active_download_max > 0 and progressive_visible_ratio_pct >= 25.0:
        return "download_progressive_contention"
    if cpu_p95_pct >= 100.0 or prefetch_shedding_ratio_pct >= 50.0:
        return "cpu_pressure"
    return "mixed_or_light"


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    pos = (len(ordered) - 1) * float(pct) / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return float(ordered[lo] + (pos - lo) * (ordered[hi] - ordered[lo]))


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip() == "True"


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _compute_miss_bursts(rows: list[dict[str, Any]]) -> dict[str, int]:
    burst_count = 0
    max_burst_len = 0
    current = 0
    for row in rows:
        is_miss = not _bool_value(row.get("cache_hit", False))
        if is_miss:
            current += 1
            if current == 1:
                burst_count += 1
            if current > max_burst_len:
                max_burst_len = current
        else:
            current = 0
    return {
        "cache_miss_burst_count": int(burst_count),
        "cache_miss_burst_max_len": int(max_burst_len),
    }


def _p95_or_zero(values: list[float]) -> float:
    return _percentile(values, 95.0) if values else 0.0


def parse_smooth_stack_pressure_log_text(text: str) -> dict[str, Any]:
    summary_rows: list[dict[str, Any]] = []
    phase_rows: list[dict[str, Any]] = []
    foreground_rows: list[dict[str, Any]] = []
    pacing_rows: list[dict[str, Any]] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if _SUMMARY_TAG in line:
            row = _parse_fields(line, _SUMMARY_TAG)
            if row:
                row["bottleneck"] = classify_pressure_bottleneck(row)
                summary_rows.append(row)
            continue
        if _PHASE_TAG in line:
            row = _parse_fields(line, _PHASE_TAG)
            if row:
                row["bottleneck"] = classify_pressure_bottleneck(row)
                phase_rows.append(row)
            continue
        if _FG_DISK_TAG in line:
            row = _parse_fields(line, _FG_DISK_TAG)
            if row:
                foreground_rows.append(row)
            continue
        if _PACING_TAG in line:
            row = _parse_fields(line, _PACING_TAG)
            if row:
                pacing_rows.append(row)

    bottleneck_counts = Counter(str(row.get("bottleneck", "mixed_or_light")) for row in phase_rows or summary_rows)
    phase_sample_totals = Counter()
    for row in phase_rows:
        phase_sample_totals[str(row.get("phase", "unknown"))] += int(row.get("samples", 0) or 0)

    ranked_phases = sorted(
        phase_rows,
        key=lambda row: (
            float(row.get("event_p95_ms", 0.0) or 0.0),
            float(row.get("ui_lag_max_ms", 0.0) or 0.0),
            float(row.get("cpu_p95_pct", 0.0) or 0.0),
        ),
        reverse=True,
    )

    total_fg_events = len(foreground_rows)
    memory_events = [
        row for row in foreground_rows
        if str(row.get("source", "memory_cache")) == "memory_cache"
        and _bool_value(row.get("cache_hit", False))
        and _float_value(row.get("disk_wait_ms", 0.0)) <= 0.0
        and _int_value(row.get("foreground_disk_reads", 0)) == 0
    ]
    disk_required_events = [
        row for row in foreground_rows
        if not (
            str(row.get("source", "memory_cache")) == "memory_cache"
            and _bool_value(row.get("cache_hit", False))
            and _float_value(row.get("disk_wait_ms", 0.0)) <= 0.0
            and _int_value(row.get("foreground_disk_reads", 0)) == 0
        )
    ]

    memory_ui_lag_values = [_float_value(row.get("ui_lag_ms", 0.0)) for row in memory_events]
    disk_ui_lag_values = [_float_value(row.get("ui_lag_ms", 0.0)) for row in disk_required_events]
    disk_wait_values = [_float_value(row.get("disk_wait_ms", 0.0)) for row in foreground_rows]
    additive_true = [_float_value(row.get("ui_lag_ms", 0.0)) for row in foreground_rows if _bool_value(row.get("additive_flush_overlap", False))]
    additive_false = [_float_value(row.get("ui_lag_ms", 0.0)) for row in foreground_rows if not _bool_value(row.get("additive_flush_overlap", False))]
    grow_true = [_float_value(row.get("ui_lag_ms", 0.0)) for row in foreground_rows if _bool_value(row.get("cache_grow_overlap", False))]
    grow_false = [_float_value(row.get("ui_lag_ms", 0.0)) for row in foreground_rows if not _bool_value(row.get("cache_grow_overlap", False))]
    miss_bursts = _compute_miss_bursts(foreground_rows)
    fg_ratio = (100.0 * len(disk_required_events) / float(total_fg_events)) if total_fg_events else 0.0

    # F8: event pacing aggregates across all drag sessions
    _pacing_s2i_p95 = _p95_or_zero([_float_value(r.get("set_to_image_p95_ms")) for r in pacing_rows])
    _pacing_s2i_max = max((_float_value(r.get("set_to_image_max_ms")) for r in pacing_rows), default=0.0)
    _pacing_fpi_p95 = _p95_or_zero([_float_value(r.get("frame_present_interval_p95_ms")) for r in pacing_rows])
    _pacing_fpi_max = max((_float_value(r.get("frame_present_interval_max_ms")) for r in pacing_rows), default=0.0)
    _pacing_jitter_p95 = _p95_or_zero([_float_value(r.get("event_jitter_p95_ms")) for r in pacing_rows])
    _pacing_jitter_max = max((_float_value(r.get("event_jitter_max_ms")) for r in pacing_rows), default=0.0)
    _pacing_repaint_p95 = _p95_or_zero([_float_value(r.get("qt_repaint_delay_p95_ms")) for r in pacing_rows])
    _pacing_repaint_max = max((_float_value(r.get("qt_repaint_delay_max_ms")) for r in pacing_rows), default=0.0)
    _pacing_iqw_p95 = _p95_or_zero([_float_value(r.get("implied_queue_wait_p95_ms")) for r in pacing_rows])
    _pacing_iqw_max = max((_float_value(r.get("implied_queue_wait_max_ms")) for r in pacing_rows), default=0.0)
    _total_evts = sum(_int_value(r.get("total_events")) for r in pacing_rows)
    _accepted_evts = sum(_int_value(r.get("accepted_events")) for r in pacing_rows)
    _same_slice_rej = sum(_int_value(r.get("same_slice_rejected")) for r in pacing_rows)
    _sched_rej = sum(_int_value(r.get("scheduler_rejected")) for r in pacing_rows)
    _coalesce_ratio = (_p95_or_zero([_float_value(r.get("coalesce_ratio_pct")) for r in pacing_rows]))
    _same_ratio = (_p95_or_zero([_float_value(r.get("same_slice_ratio_pct")) for r in pacing_rows]))

    return {
        "summary_rows": summary_rows,
        "phase_rows": phase_rows,
        "foreground_rows": foreground_rows,
        "pacing_rows": pacing_rows,
        "aggregate": {
            "session_count": len(summary_rows),
            "phase_row_count": len(phase_rows),
            "pacing_session_count": len(pacing_rows),
            "foreground_event_count": total_fg_events,
            "foreground_memory_event_count": len(memory_events),
            "foreground_disk_required_event_count": len(disk_required_events),
            "foreground_disk_dependency_ratio_pct": fg_ratio,
            "foreground_ui_lag_p95_memory_hit_ms": _p95_or_zero(memory_ui_lag_values),
            "foreground_ui_lag_p95_disk_hit_ms": _p95_or_zero(disk_ui_lag_values),
            "foreground_disk_wait_p95_ms": _p95_or_zero(disk_wait_values),
            "foreground_disk_wait_max_ms": max(disk_wait_values) if disk_wait_values else 0.0,
            "foreground_additive_flush_overlap_ui_lag_p95_ms": _p95_or_zero(additive_true),
            "foreground_non_additive_flush_ui_lag_p95_ms": _p95_or_zero(additive_false),
            "foreground_cache_grow_overlap_ui_lag_p95_ms": _p95_or_zero(grow_true),
            "foreground_non_cache_grow_ui_lag_p95_ms": _p95_or_zero(grow_false),
            **miss_bursts,
            "phase_sample_totals": dict(phase_sample_totals),
            "worst_event_p95_ms": max((float(row.get("event_p95_ms", 0.0) or 0.0) for row in summary_rows), default=0.0),
            "worst_ui_lag_max_ms": max((float(row.get("ui_lag_max_ms", 0.0) or 0.0) for row in summary_rows), default=0.0),
            "worst_cpu_p95_pct": max((float(row.get("cpu_p95_pct", 0.0) or 0.0) for row in summary_rows), default=0.0),
            "total_main_thread_stall_count": sum(int(row.get("main_thread_stall_count", 0) or 0) for row in summary_rows),
            "bottleneck_counts": dict(bottleneck_counts),
            "ranked_phase_rows": ranked_phases,
            # F8: event pacing
            "pacing_total_events": _total_evts,
            "pacing_accepted_events": _accepted_evts,
            "pacing_same_slice_rejected": _same_slice_rej,
            "pacing_scheduler_rejected": _sched_rej,
            "pacing_same_slice_ratio_p95_pct": _same_ratio,
            "pacing_coalesce_ratio_p95_pct": _coalesce_ratio,
            "pacing_event_jitter_p95_ms": _pacing_jitter_p95,
            "pacing_event_jitter_max_ms": _pacing_jitter_max,
            "pacing_set_to_image_p95_ms": _pacing_s2i_p95,
            "pacing_set_to_image_max_ms": _pacing_s2i_max,
            "pacing_frame_present_interval_p95_ms": _pacing_fpi_p95,
            "pacing_frame_present_interval_max_ms": _pacing_fpi_max,
            "pacing_qt_repaint_delay_p95_ms": _pacing_repaint_p95,
            "pacing_qt_repaint_delay_max_ms": _pacing_repaint_max,
            "pacing_implied_queue_wait_p95_ms": _pacing_iqw_p95,
            "pacing_implied_queue_wait_max_ms": _pacing_iqw_max,
        },
    }


def _render_text_report(payload: dict[str, Any]) -> str:
    aggregate = dict(payload.get("aggregate", {}) or {})
    lines = [
        f"sessions={int(aggregate.get('session_count', 0) or 0)} phase_rows={int(aggregate.get('phase_row_count', 0) or 0)}",
        f"foreground_events={int(aggregate.get('foreground_event_count', 0) or 0)} memory_events={int(aggregate.get('foreground_memory_event_count', 0) or 0)} disk_required_events={int(aggregate.get('foreground_disk_required_event_count', 0) or 0)} FOREGROUND_DISK_DEPENDENCY_RATIO={float(aggregate.get('foreground_disk_dependency_ratio_pct', 0.0) or 0.0):.1f}%",
        f"foreground_ui_lag_p95_memory_hit_ms={float(aggregate.get('foreground_ui_lag_p95_memory_hit_ms', 0.0) or 0.0):.1f} foreground_ui_lag_p95_disk_hit_ms={float(aggregate.get('foreground_ui_lag_p95_disk_hit_ms', 0.0) or 0.0):.1f}",
        f"foreground_disk_wait_p95_ms={float(aggregate.get('foreground_disk_wait_p95_ms', 0.0) or 0.0):.1f} foreground_disk_wait_max_ms={float(aggregate.get('foreground_disk_wait_max_ms', 0.0) or 0.0):.1f}",
        f"cache_miss_burst_count={int(aggregate.get('cache_miss_burst_count', 0) or 0)} cache_miss_burst_max_len={int(aggregate.get('cache_miss_burst_max_len', 0) or 0)}",
        f"additive_flush_overlap_ui_lag_p95_ms={float(aggregate.get('foreground_additive_flush_overlap_ui_lag_p95_ms', 0.0) or 0.0):.1f} non_additive_flush_ui_lag_p95_ms={float(aggregate.get('foreground_non_additive_flush_ui_lag_p95_ms', 0.0) or 0.0):.1f}",
        f"cache_grow_overlap_ui_lag_p95_ms={float(aggregate.get('foreground_cache_grow_overlap_ui_lag_p95_ms', 0.0) or 0.0):.1f} non_cache_grow_ui_lag_p95_ms={float(aggregate.get('foreground_non_cache_grow_ui_lag_p95_ms', 0.0) or 0.0):.1f}",
        f"worst_event_p95_ms={float(aggregate.get('worst_event_p95_ms', 0.0) or 0.0):.1f} worst_ui_lag_max_ms={float(aggregate.get('worst_ui_lag_max_ms', 0.0) or 0.0):.1f} worst_cpu_p95_pct={float(aggregate.get('worst_cpu_p95_pct', 0.0) or 0.0):.1f}",
        f"total_main_thread_stall_count={int(aggregate.get('total_main_thread_stall_count', 0) or 0)}",
        f"bottleneck_counts={json.dumps(aggregate.get('bottleneck_counts', {}), sort_keys=True)}",
        # F8: event pacing section
        f"--- EVENT PACING (F8) ---",
        f"pacing_sessions={int(aggregate.get('pacing_session_count', 0) or 0)} total_events={int(aggregate.get('pacing_total_events', 0) or 0)} accepted={int(aggregate.get('pacing_accepted_events', 0) or 0)}",
        f"same_slice_rejected={int(aggregate.get('pacing_same_slice_rejected', 0) or 0)} scheduler_rejected={int(aggregate.get('pacing_scheduler_rejected', 0) or 0)}",
        f"same_slice_ratio_p95_pct={float(aggregate.get('pacing_same_slice_ratio_p95_pct', 0.0) or 0.0):.1f} coalesce_ratio_p95_pct={float(aggregate.get('pacing_coalesce_ratio_p95_pct', 0.0) or 0.0):.1f}",
        f"A_event_jitter_p95_ms={float(aggregate.get('pacing_event_jitter_p95_ms', 0.0) or 0.0):.1f} event_jitter_max_ms={float(aggregate.get('pacing_event_jitter_max_ms', 0.0) or 0.0):.1f}",
        f"B_frame_present_interval_p95_ms={float(aggregate.get('pacing_frame_present_interval_p95_ms', 0.0) or 0.0):.1f} frame_present_interval_max_ms={float(aggregate.get('pacing_frame_present_interval_max_ms', 0.0) or 0.0):.1f}",
        f"C_set_to_image_p95_ms={float(aggregate.get('pacing_set_to_image_p95_ms', 0.0) or 0.0):.1f} set_to_image_max_ms={float(aggregate.get('pacing_set_to_image_max_ms', 0.0) or 0.0):.1f}",
        f"D_qt_repaint_delay_p95_ms={float(aggregate.get('pacing_qt_repaint_delay_p95_ms', 0.0) or 0.0):.1f} qt_repaint_delay_max_ms={float(aggregate.get('pacing_qt_repaint_delay_max_ms', 0.0) or 0.0):.1f}",
        f"E_implied_queue_wait_p95_ms={float(aggregate.get('pacing_implied_queue_wait_p95_ms', 0.0) or 0.0):.1f} implied_queue_wait_max_ms={float(aggregate.get('pacing_implied_queue_wait_max_ms', 0.0) or 0.0):.1f}",
    ]
    ranked_phase_rows = list(aggregate.get("ranked_phase_rows", []) or [])
    for row in ranked_phase_rows[:5]:
        lines.append(
            "phase={phase} samples={samples} event_p95_ms={event_p95_ms:.1f} ui_lag_max_ms={ui_lag_max_ms:.1f} cpu_p95_pct={cpu_p95_pct:.1f} bottleneck={bottleneck}".format(
                phase=str(row.get("phase", "unknown")),
                samples=int(row.get("samples", 0) or 0),
                event_p95_ms=float(row.get("event_p95_ms", 0.0) or 0.0),
                ui_lag_max_ms=float(row.get("ui_lag_max_ms", 0.0) or 0.0),
                cpu_p95_pct=float(row.get("cpu_p95_pct", 0.0) or 0.0),
                bottleneck=str(row.get("bottleneck", "mixed_or_light")),
            )
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse FAST smooth stack pressure KPI logs.")
    parser.add_argument("paths", nargs="+", help="Log files to parse")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args(argv)

    text = "\n".join(Path(path).read_text(encoding="utf-8", errors="replace") for path in args.paths)
    payload = parse_smooth_stack_pressure_log_text(text)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_render_text_report(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())