from __future__ import annotations

import json
import threading
import time
from collections import Counter, deque
from itertools import combinations
from typing import Any, Optional

from modules.viewer.fast.perf_metrics import PerfMetrics
from modules.viewer.fast.system_load_controller import (
    BlockId,
    SystemLoadController,
    get_system_load_controller,
)


_BLOCK_LABELS = {
    BlockId.BLOCK_1_DATA_SERVICES.value: "Block 1 - Data services",
    BlockId.BLOCK_2_VIEWER_HOT_PATH.value: "Block 2 - Viewer hot path",
    BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION.value: "Block 3 - Cache, scroll, orchestration",
}

_BLOCK_SHORT_LABELS = {
    BlockId.BLOCK_1_DATA_SERVICES.value: "B1",
    BlockId.BLOCK_2_VIEWER_HOT_PATH.value: "B2",
    BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION.value: "B3",
}

_BLOCK_KPI_KEYS = {
    BlockId.BLOCK_1_DATA_SERVICES.value: (
        "download_session_active",
        "active_download_count",
        "completed_series_count",
        "heavy_download_active",
        "progress_update_admitted_total",
        "thumbnail_ui_admitted_total",
    ),
    BlockId.BLOCK_2_VIEWER_HOT_PATH.value: (
        "first_image_ms",
        "set_slice_p95_ms",
        "decode_p95_ms",
        "frame_render_p95_ms",
        "slow_frame_count_16ms",
        "total_frames",
    ),
    BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION.value: (
        "stale_task_ratio",
        "cancelled_task_ratio",
        "cache_hit_ratio_pct",
        "longest_ui_gap_ms",
        "ui_event_loop_lag_ms",
        "protected_ui_cadence",
        "fast_interaction_active",
    ),
}


def _counter_total(bucket: dict[str, int] | None) -> int:
    if not isinstance(bucket, dict):
        return 0
    return sum(int(bucket.get(name, 0) or 0) for name in ("admitted", "deferred", "dropped"))


def _delta_counts(
    current: dict[str, dict[str, int]] | None,
    previous: dict[str, dict[str, int]] | None,
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    all_keys = set((current or {}).keys()) | set((previous or {}).keys())
    for key in all_keys:
        curr_bucket = (current or {}).get(key, {}) or {}
        prev_bucket = (previous or {}).get(key, {}) or {}
        delta_bucket: dict[str, int] = {}
        for field in ("admitted", "deferred", "dropped"):
            curr_value = int(curr_bucket.get(field, 0) or 0)
            prev_value = int(prev_bucket.get(field, 0) or 0)
            delta_bucket[field] = max(0, curr_value - prev_value)
        result[key] = delta_bucket
    return result


def _sanitize_live_value(value: Any) -> Any:
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, float):
        return round(float(value), 2)
    if isinstance(value, int):
        return int(value)
    return value


def _block_rows_by_id(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(block.get("block_id", "")): block
        for block in (snapshot.get("blocks") or [])
        if isinstance(block, dict)
    }


def _build_block_kpi_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    block_payload: dict[str, Any] = {}
    for block_id in (
        BlockId.BLOCK_1_DATA_SERVICES.value,
        BlockId.BLOCK_2_VIEWER_HOT_PATH.value,
        BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION.value,
    ):
        block = _block_rows_by_id(snapshot).get(block_id, {})
        live_kpis = {
            str(key): _sanitize_live_value(value)
            for key, value in (block.get("live_kpis") or {}).items()
        }
        block_payload[_BLOCK_SHORT_LABELS.get(block_id, block_id)] = {
            "label": _BLOCK_LABELS.get(block_id, block_id),
            "active": bool(block.get("active", False)),
            "recent_event_count": int(block.get("recent_event_count", 0) or 0),
            "recent_admission_total": int(block.get("recent_admission_total", 0) or 0),
            "recent_admission_delta": {
                str(name): int(count)
                for name, count in (block.get("recent_admission_delta") or {}).items()
            },
            "admission_count_total": int(block.get("admission_count_total", 0) or 0),
            "live_kpis": live_kpis,
        }
    return {
        "label": snapshot.get("label", ""),
        "state": snapshot.get("orchestrator", {}).get("state", "UNKNOWN"),
        "overlap_state": snapshot.get("overlap", {}).get("overlap_state", "idle"),
        "active_blocks": snapshot.get("overlap", {}).get("active_blocks", []),
        "active_block_count": int(snapshot.get("overlap", {}).get("active_block_count", 0) or 0),
        "transition_seq": int(snapshot.get("orchestrator", {}).get("transition_seq", 0) or 0),
        "ui_event_loop_lag_ms": round(float(snapshot.get("load", {}).get("ui_event_loop_lag_ms", 0.0) or 0.0), 2),
        "blocks": block_payload,
    }


def _build_block_kpi_line(snapshot: dict[str, Any]) -> str:
    blocks = _block_rows_by_id(snapshot)
    b1 = blocks.get(BlockId.BLOCK_1_DATA_SERVICES.value, {})
    b1_kpis = b1.get("live_kpis") or {}
    b2 = blocks.get(BlockId.BLOCK_2_VIEWER_HOT_PATH.value, {})
    b2_kpis = b2.get("live_kpis") or {}
    b3 = blocks.get(BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION.value, {})
    b3_kpis = b3.get("live_kpis") or {}

    prefix_parts = [
        "[BLOCK_KPI]",
        f"state={snapshot.get('orchestrator', {}).get('state', 'UNKNOWN')}",
        f"overlap={snapshot.get('overlap', {}).get('overlap_state', 'idle')}",
        f"active_blocks={int(snapshot.get('overlap', {}).get('active_block_count', 0) or 0)}",
        f"lag_ms={round(float(snapshot.get('load', {}).get('ui_event_loop_lag_ms', 0.0) or 0.0), 1)}",
    ]
    label = str(snapshot.get("label", "") or "").strip()
    if label:
        prefix_parts.insert(1, f'label="{label}"')

    block_parts = [
        (
            f"B1(active={int(bool(b1.get('active', False)))}"
            f", dl={int(b1_kpis.get('active_download_count', 0) or 0)}"
            f", done={int(b1_kpis.get('completed_series_count', 0) or 0)}"
            f", progress_adm={int(b1_kpis.get('progress_update_admitted_total', 0) or 0)}"
            f", thumb_adm={int(b1_kpis.get('thumbnail_ui_admitted_total', 0) or 0)}"
            f", evt+={int(b1.get('recent_event_count', 0) or 0)}"
            f", admit+={int(b1.get('recent_admission_total', 0) or 0)})"
        ),
        (
            f"B2(active={int(bool(b2.get('active', False)))}"
            f", first={round(float(b2_kpis.get('first_image_ms', 0.0) or 0.0), 1)}ms"
            f", slice_p95={round(float(b2_kpis.get('set_slice_p95_ms', 0.0) or 0.0), 1)}ms"
            f", decode_p95={round(float(b2_kpis.get('decode_p95_ms', 0.0) or 0.0), 1)}ms"
            f", frame_p95={round(float(b2_kpis.get('frame_render_p95_ms', 0.0) or 0.0), 1)}ms"
            f", slow16={int(b2_kpis.get('slow_frame_count_16ms', 0) or 0)}"
            f", frames={int(b2_kpis.get('total_frames', 0) or 0)})"
        ),
        (
            f"B3(active={int(bool(b3.get('active', False)))}"
            f", stale={round(float(b3_kpis.get('stale_task_ratio', 0.0) or 0.0), 2)}"
            f", cancel={round(float(b3_kpis.get('cancelled_task_ratio', 0.0) or 0.0), 2)}"
            f", hit={round(float(b3_kpis.get('cache_hit_ratio_pct', 0.0) or 0.0), 1)}%"
            f", ui_lag={round(float(b3_kpis.get('ui_event_loop_lag_ms', 0.0) or 0.0), 1)}ms"
            f", protected={int(bool(b3_kpis.get('protected_ui_cadence', False)))}"
            f", fast={int(bool(b3_kpis.get('fast_interaction_active', False)))}"
            f", evt+={int(b3.get('recent_event_count', 0) or 0)}"
            f", admit+={int(b3.get('recent_admission_total', 0) or 0)})"
        ),
    ]
    return " ".join(prefix_parts + block_parts)


class LiveBlockTelemetry:
    """Low-overhead live block KPI and overlap telemetry.

    This object fuses three runtime views into one snapshot suitable for live
    exams and compact heartbeat logging:
      - PipelineOrchestrator lifecycle/events (block-owned transitions)
      - SystemLoadController admission decisions (admitted/deferred/dropped)
      - PerfMetrics interaction/render KPIs
    """

    def __init__(
        self,
        *,
        orchestrator=None,
        load_controller: Optional[SystemLoadController] = None,
        perf_metrics: Optional[PerfMetrics] = None,
        history_maxlen: int = 120,
    ) -> None:
        self._orchestrator = orchestrator
        self._load_controller = load_controller or get_system_load_controller()
        self._perf_metrics = perf_metrics or PerfMetrics.get()
        self._history: deque[dict[str, Any]] = deque(maxlen=max(8, int(history_maxlen)))
        self._lock = threading.Lock()
        self._last_event_counts_by_block: dict[str, int] = {}
        self._last_admission_by_block: dict[str, dict[str, int]] = {}

    def set_orchestrator(self, orchestrator) -> None:
        with self._lock:
            self._orchestrator = orchestrator

    def snapshot(
        self,
        *,
        heavy_download_active: bool,
        fast_interaction_active: bool,
        label: str = "",
        now_ms: Optional[float] = None,
    ) -> dict[str, Any]:
        now = time.monotonic() * 1000.0 if now_ms is None else float(now_ms)
        orch = self._orchestrator
        orch_snapshot = orch.snapshot() if orch is not None else {}
        load_snapshot = self._load_controller.debug_snapshot(
            heavy_download_active=heavy_download_active,
            fast_interaction_active=fast_interaction_active,
            now_ms=now,
        )
        perf_snapshot = self._perf_metrics.snapshot()

        current_event_counts = {
            str(key): int(value)
            for key, value in (orch_snapshot.get("event_counts_by_block") or {}).items()
        }
        current_admission_by_block = {
            str(key): {name: int(count) for name, count in (bucket or {}).items()}
            for key, bucket in (load_snapshot.get("admission_by_block") or {}).items()
        }

        with self._lock:
            delta_events = {
                key: max(0, int(current_event_counts.get(key, 0)) - int(self._last_event_counts_by_block.get(key, 0)))
                for key in set(current_event_counts) | set(self._last_event_counts_by_block)
            }
            delta_admissions = _delta_counts(current_admission_by_block, self._last_admission_by_block)
            self._last_event_counts_by_block = dict(current_event_counts)
            self._last_admission_by_block = {
                key: dict(bucket) for key, bucket in current_admission_by_block.items()
            }

        metric_pool = {
            "download_session_active": bool(orch_snapshot.get("download_session_active", False)),
            "active_download_count": int(orch_snapshot.get("active_download_count", 0) or 0),
            "completed_series_count": int(orch_snapshot.get("completed_series_count", 0) or 0),
            "heavy_download_active": bool(heavy_download_active),
            "progress_update_admitted_total": int(
                (load_snapshot.get("admission_by_work_class", {}) or {})
                .get("progress_update", {})
                .get("admitted", 0)
                or 0
            ),
            "thumbnail_ui_admitted_total": int(
                (load_snapshot.get("admission_by_work_class", {}) or {})
                .get("thumbnail_ui", {})
                .get("admitted", 0)
                or 0
            ),
            "first_image_ms": float(perf_snapshot.get("first_image_ms", 0.0) or 0.0),
            "set_slice_p95_ms": float(perf_snapshot.get("set_slice_p95_ms", 0.0) or 0.0),
            "decode_p95_ms": float(perf_snapshot.get("decode_p95_ms", 0.0) or 0.0),
            "frame_render_p95_ms": float(perf_snapshot.get("frame_render_p95_ms", 0.0) or 0.0),
            "slow_frame_count_16ms": int(perf_snapshot.get("slow_frame_count_16ms", 0) or 0),
            "total_frames": int(perf_snapshot.get("total_frames", 0) or 0),
            "stale_task_ratio": float(perf_snapshot.get("stale_task_ratio", 0.0) or 0.0),
            "cancelled_task_ratio": float(perf_snapshot.get("cancelled_task_ratio", 0.0) or 0.0),
            "cache_hit_ratio_pct": float(perf_snapshot.get("cache_hit_ratio_pct", 0.0) or 0.0),
            "longest_ui_gap_ms": float(perf_snapshot.get("longest_ui_gap_ms", 0.0) or 0.0),
            "ui_event_loop_lag_ms": float(load_snapshot.get("ui_event_loop_lag_ms", 0.0) or 0.0),
            "protected_ui_cadence": bool(load_snapshot.get("protected_ui_cadence", False)),
            "fast_interaction_active": bool(fast_interaction_active),
        }

        block_rows: list[dict[str, Any]] = []
        active_blocks: list[str] = []
        for block_id in (
            BlockId.BLOCK_1_DATA_SERVICES.value,
            BlockId.BLOCK_2_VIEWER_HOT_PATH.value,
            BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION.value,
        ):
            recent_admission_bucket = delta_admissions.get(block_id, {})
            recent_admission_total = _counter_total(recent_admission_bucket)
            recent_event_count = int(delta_events.get(block_id, 0) or 0)

            active = False
            if block_id == BlockId.BLOCK_1_DATA_SERVICES.value:
                active = bool(heavy_download_active) or metric_pool["active_download_count"] > 0 or recent_event_count > 0 or recent_admission_total > 0
            elif block_id == BlockId.BLOCK_2_VIEWER_HOT_PATH.value:
                active = bool(fast_interaction_active) or metric_pool["total_frames"] > 0 or metric_pool["set_slice_p95_ms"] > 0.0
            elif block_id == BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION.value:
                active = bool(load_snapshot.get("protected_ui_cadence", False)) or bool(fast_interaction_active) or recent_event_count > 0 or recent_admission_total > 0

            if active:
                active_blocks.append(block_id)

            live_kpis = {
                key: metric_pool[key]
                for key in _BLOCK_KPI_KEYS.get(block_id, ())
            }
            block_rows.append(
                {
                    "block_id": block_id,
                    "label": _BLOCK_LABELS.get(block_id, block_id),
                    "active": bool(active),
                    "recent_event_count": recent_event_count,
                    "recent_admission_delta": recent_admission_bucket,
                    "recent_admission_total": recent_admission_total,
                    "event_count_total": int(current_event_counts.get(block_id, 0) or 0),
                    "admission_count_total": _counter_total(current_admission_by_block.get(block_id, {})),
                    "live_kpis": live_kpis,
                }
            )

        overlap_state = "+".join(active_blocks) if active_blocks else "idle"
        overlap_pairs = [list(pair) for pair in combinations(active_blocks, 2)]
        snapshot = {
            "mode": "live-block-telemetry",
            "label": str(label or ""),
            "timestamp_ms": round(now, 2),
            "overlap": {
                "active_blocks": active_blocks,
                "active_block_count": len(active_blocks),
                "overlap_state": overlap_state,
                "overlap_pairs": overlap_pairs,
                "heavy_download_active": bool(heavy_download_active),
                "fast_interaction_active": bool(fast_interaction_active),
                "protected_ui_cadence": bool(load_snapshot.get("protected_ui_cadence", False)),
            },
            "orchestrator": {
                "state": orch_snapshot.get("state", "UNKNOWN"),
                "transition_seq": int(orch_snapshot.get("transition_seq", 0) or 0),
                "most_recent_event": orch_snapshot.get("most_recent_event"),
                "event_counts_by_block": current_event_counts,
            },
            "load": load_snapshot,
            "perf": perf_snapshot,
            "blocks": block_rows,
        }

        with self._lock:
            self._history.append(snapshot)
            history_counts = Counter(str(item.get("overlap", {}).get("overlap_state", "idle")) for item in self._history)
            active_samples_by_block = Counter()
            for item in self._history:
                for block_id in item.get("overlap", {}).get("active_blocks", []):
                    active_samples_by_block[str(block_id)] += 1
            snapshot["history"] = {
                "sample_count": len(self._history),
                "overlap_state_counts": dict(history_counts),
                "active_samples_by_block": dict(active_samples_by_block),
                "peak_active_block_count": max((item.get("overlap", {}).get("active_block_count", 0) for item in self._history), default=0),
            }

        return snapshot

    def emit_heartbeat(
        self,
        *,
        heavy_download_active: bool,
        fast_interaction_active: bool,
        logger=None,
        label: str = "",
        now_ms: Optional[float] = None,
        snapshot: Optional[dict[str, Any]] = None,
        include_idle: bool = False,
    ) -> dict[str, Any]:
        snap = snapshot or self.snapshot(
            heavy_download_active=heavy_download_active,
            fast_interaction_active=fast_interaction_active,
            label=label,
            now_ms=now_ms,
        )
        if not include_idle and not snap.get("overlap", {}).get("active_blocks"):
            return snap

        block_compact = {}
        for block in snap.get("blocks", []):
            block_compact[block["block_id"]] = {
                "active": bool(block.get("active", False)),
                "recent_event_count": int(block.get("recent_event_count", 0) or 0),
                "recent_admission_total": int(block.get("recent_admission_total", 0) or 0),
                "live_kpis": block.get("live_kpis", {}),
            }

        payload = {
            "label": snap.get("label", ""),
            "state": snap.get("orchestrator", {}).get("state", "UNKNOWN"),
            "overlap_state": snap.get("overlap", {}).get("overlap_state", "idle"),
            "active_blocks": snap.get("overlap", {}).get("active_blocks", []),
            "transition_seq": snap.get("orchestrator", {}).get("transition_seq", 0),
            "ui_event_loop_lag_ms": round(float(snap.get("load", {}).get("ui_event_loop_lag_ms", 0.0) or 0.0), 2),
            "blocks": block_compact,
        }
        message = f"[BLOCK_DIAG] {json.dumps(payload, sort_keys=True, default=str)}"
        kpi_payload = _build_block_kpi_payload(snap)
        kpi_message = f"[BLOCK_KPI_JSON] {json.dumps(kpi_payload, sort_keys=True, default=str)}"
        summary_message = _build_block_kpi_line(snap)
        if logger is not None:
            try:
                logger.info(message)
                logger.info(kpi_message)
                logger.info(summary_message)
            except Exception:
                pass
        else:
            try:
                print(message)
                print(kpi_message)
                print(summary_message)
            except Exception:
                pass
        return snap
