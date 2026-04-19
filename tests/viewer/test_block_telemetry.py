from __future__ import annotations

from modules.viewer.fast.block_telemetry import LiveBlockTelemetry
from modules.viewer.fast.perf_metrics import PerfMetrics
from modules.viewer.fast.system_load_controller import (
    BlockId,
    SystemLoadController,
    WorkClass,
)
from modules.viewer.pipeline.orchestrator import PipelineOrchestrator


def _block_map(snapshot):
    return {block["block_id"]: block for block in snapshot["blocks"]}


def test_live_block_telemetry_snapshot_tracks_overlap_and_live_kpis():
    orch = PipelineOrchestrator()
    ctrl = SystemLoadController()
    pm = PerfMetrics.get()
    pm.enable()
    try:
        orch.on_download_session_started("study-1")
        orch.on_series_download_started("101")
        ctrl.should_admit(
            WorkClass.PROGRESS_UPDATE,
            {"key": "series-101"},
            heavy_download_active=True,
            fast_interaction_active=False,
            now_ms=100.0,
        )
        ctrl.should_admit(
            WorkClass.INTERACTION,
            {"key": "viewer-1"},
            heavy_download_active=True,
            fast_interaction_active=True,
            now_ms=110.0,
        )
        pm.record_first_image(42.0)
        pm.record_set_slice(22.0)
        pm.record_decode(18.0)
        pm.record_frame_render(19.0)
        pm.record_prefetch_submitted()
        pm.record_stale_task()
        pm.record_cache_hit()
        pm.record_cache_miss()
        pm.record_longest_ui_gap(11.0)

        telemetry = LiveBlockTelemetry(
            orchestrator=orch,
            load_controller=ctrl,
            perf_metrics=pm,
        )
        snap = telemetry.snapshot(
            heavy_download_active=True,
            fast_interaction_active=True,
            label="live-exam",
            now_ms=120.0,
        )

        assert snap["label"] == "live-exam"
        assert snap["overlap"]["active_block_count"] == 3
        assert BlockId.BLOCK_1_DATA_SERVICES.value in snap["overlap"]["active_blocks"]
        assert BlockId.BLOCK_2_VIEWER_HOT_PATH.value in snap["overlap"]["active_blocks"]
        assert BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION.value in snap["overlap"]["active_blocks"]

        blocks = _block_map(snap)
        block1 = blocks[BlockId.BLOCK_1_DATA_SERVICES.value]
        block2 = blocks[BlockId.BLOCK_2_VIEWER_HOT_PATH.value]
        block3 = blocks[BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION.value]

        assert block1["recent_event_count"] >= 2
        assert block1["live_kpis"]["active_download_count"] == 1
        assert block2["live_kpis"]["first_image_ms"] == 42.0
        assert block2["live_kpis"]["set_slice_p95_ms"] == 22.0
        assert block3["live_kpis"]["stale_task_ratio"] == 1.0
        assert block3["live_kpis"]["cache_hit_ratio_pct"] == 50.0
        assert snap["history"]["sample_count"] == 1
    finally:
        pm.disable()
        pm.reset()


def test_live_block_telemetry_recent_deltas_only_count_new_activity():
    orch = PipelineOrchestrator()
    ctrl = SystemLoadController()
    telemetry = LiveBlockTelemetry(orchestrator=orch, load_controller=ctrl)

    orch.on_download_session_started("study-2")
    first = telemetry.snapshot(
        heavy_download_active=True,
        fast_interaction_active=False,
        now_ms=100.0,
    )
    second = telemetry.snapshot(
        heavy_download_active=True,
        fast_interaction_active=False,
        now_ms=130.0,
    )

    first_blocks = _block_map(first)
    second_blocks = _block_map(second)

    assert first_blocks[BlockId.BLOCK_1_DATA_SERVICES.value]["recent_event_count"] >= 1
    assert second_blocks[BlockId.BLOCK_1_DATA_SERVICES.value]["recent_event_count"] == 0

    ctrl.should_admit(
        WorkClass.PREFETCH,
        {"key": "series-201:center-20", "distance": 4},
        heavy_download_active=True,
        fast_interaction_active=True,
        now_ms=140.0,
    )
    orch.on_study_download_completed("study-2")
    third = telemetry.snapshot(
        heavy_download_active=False,
        fast_interaction_active=True,
        now_ms=150.0,
    )
    third_blocks = _block_map(third)

    assert third_blocks[BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION.value]["recent_event_count"] >= 1
    assert third_blocks[BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION.value]["recent_admission_total"] >= 1
    assert third["history"]["sample_count"] == 3


def test_ui_throttle_live_block_snapshot_uses_registered_orchestrator():
    from modules.viewer.fast import ui_throttle

    orch = PipelineOrchestrator()
    orch.on_download_session_started("study-3")
    ui_throttle.set_active_orchestrator(orch)
    try:
        snap = ui_throttle.get_live_block_telemetry_snapshot(label="facade")
        assert snap["label"] == "facade"
        assert snap["orchestrator"]["state"] == "DOWNLOADING"
        assert snap["overlap"]["active_block_count"] >= 1
    finally:
        ui_throttle.clear_active_orchestrator(orch)


def test_live_block_telemetry_emit_heartbeat_logs_diag_and_kpi_lines():
    class _CaptureLogger:
        def __init__(self):
            self.messages = []

        def info(self, message):
            self.messages.append(str(message))

    orch = PipelineOrchestrator()
    ctrl = SystemLoadController()
    pm = PerfMetrics.get()
    pm.enable()
    try:
        orch.on_download_session_started("study-log")
        orch.on_series_download_started("501")
        ctrl.should_admit(
            WorkClass.PROGRESS_UPDATE,
            {"key": "series-501"},
            heavy_download_active=True,
            fast_interaction_active=False,
            now_ms=100.0,
        )
        ctrl.should_admit(
            WorkClass.PREFETCH,
            {"key": "series-501:center-5", "distance": 2},
            heavy_download_active=True,
            fast_interaction_active=True,
            now_ms=110.0,
        )
        pm.record_first_image(42.0)
        pm.record_set_slice(22.0)
        pm.record_decode(18.0)
        pm.record_frame_render(19.0)
        pm.record_prefetch_submitted()
        pm.record_stale_task()
        pm.record_cache_hit()
        pm.record_cache_miss()

        telemetry = LiveBlockTelemetry(
            orchestrator=orch,
            load_controller=ctrl,
            perf_metrics=pm,
        )
        logger = _CaptureLogger()
        telemetry.emit_heartbeat(
            heavy_download_active=True,
            fast_interaction_active=True,
            logger=logger,
            label="live-kpi",
            now_ms=120.0,
            include_idle=True,
        )

        assert len(logger.messages) == 3
        assert logger.messages[0].startswith("[BLOCK_DIAG] ")
        assert logger.messages[1].startswith("[BLOCK_KPI_JSON] ")
        assert logger.messages[2].startswith('[BLOCK_KPI] label="live-kpi" ')
        assert "B1(active=" in logger.messages[2]
        assert "B2(active=" in logger.messages[2]
        assert "B3(active=" in logger.messages[2]
        assert "first=42.0ms" in logger.messages[2]
        assert "slice_p95=22.0ms" in logger.messages[2]
        assert "stale=1.0" in logger.messages[2]
        assert '"B2"' in logger.messages[1]
    finally:
        pm.disable()
        pm.reset()
