from __future__ import annotations

from tools.performance.smooth_stack_pressure_report import (
    classify_pressure_bottleneck,
    parse_smooth_stack_pressure_log_text,
)


def test_parse_smooth_stack_pressure_log_text_tolerates_production_prefixes():
    text = """
    2026-05-12 | INFO | component=viewer role=main | modules.viewer.fast.qt_viewer_bridge._log_drag_metrics_summary | action=sess study=s series=1 job=- viewevt=v fn=- stage=- result=- | [FAST_STACK_PRESSURE] drag_session_id=d1 bridge=b1 viewer=v1 duration_s=2.500 samples=8 phase_count=2 current_phase=download_only event_p95_ms=155.0 handler_p95_ms=5.0 ui_lag_max_ms=88.0 cpu_p95_pct=121.0 cpu_max_pct=148.0 rss_p95_mb=812.5 avail_ram_min_mb=2048.0 proc_write_mb_s_p95=3.5 disk_write_mb_s_p95=24.0 decode_q_p95=3 frame_q_p95=1 disk_write_q_max=5 disk_deferred_q_max=7 active_download_max=2 progressive_visible_ratio_pct=50.0 protected_cadence_ratio_pct=75.0 prefetch_shedding_ratio_pct=62.5 cache_hit_ratio_min_pct=81.0 longest_ui_gap_max_ms=222.0 main_thread_stall_count=1 dm_rebuild_count=0
    2026-05-12 | INFO | component=viewer role=main | modules.viewer.fast.qt_viewer_bridge._log_drag_metrics_summary | action=sess study=s series=1 job=- viewevt=v fn=- stage=- result=- | [FAST_STACK_PRESSURE_PHASE] drag_session_id=d1 phase=download_only samples=5 share_pct=62.5 event_p95_ms=155.0 handler_p95_ms=5.0 ui_lag_max_ms=88.0 cpu_p95_pct=121.0 rss_p95_mb=812.5 avail_ram_min_mb=2048.0 proc_write_mb_s_p95=3.5 disk_write_mb_s_p95=24.0 decode_q_p95=3 frame_q_p95=1 disk_write_q_max=5 disk_deferred_q_max=7 active_download_max=2 progressive_visible_ratio_pct=60.0 protected_cadence_ratio_pct=80.0 prefetch_shedding_ratio_pct=70.0 cache_hit_ratio_min_pct=81.0 longest_ui_gap_max_ms=222.0 main_thread_stall_count=1 dm_rebuild_count=0
    2026-05-12 | INFO | component=viewer role=main | modules.viewer.fast.qt_viewer_bridge._log_drag_metrics_summary | action=sess study=s series=1 job=- viewevt=v fn=- stage=- result=- | [FAST_STACK_PRESSURE_PHASE] drag_session_id=d1 phase=baseline samples=3 share_pct=37.5 event_p95_ms=42.0 handler_p95_ms=3.0 ui_lag_max_ms=12.0 cpu_p95_pct=44.0 rss_p95_mb=800.0 avail_ram_min_mb=2300.0 proc_write_mb_s_p95=0.0 disk_write_mb_s_p95=0.0 decode_q_p95=0 frame_q_p95=0 disk_write_q_max=0 disk_deferred_q_max=0 active_download_max=0 progressive_visible_ratio_pct=0.0 protected_cadence_ratio_pct=0.0 prefetch_shedding_ratio_pct=0.0 cache_hit_ratio_min_pct=94.0 longest_ui_gap_max_ms=18.0 main_thread_stall_count=0 dm_rebuild_count=0
    2026-05-12 | INFO | component=viewer role=main | modules.viewer.fast.qt_viewer_bridge._emit_foreground_disk_event | action=sess study=s series=1 job=- viewevt=v fn=- stage=- result=- | [FAST_FG_DISK] drag_session_id=d1 bridge=b1 viewer=v1 slice=10 source=memory_cache cache_hit=True disk_wait_ms=0.000 decode_wait_ms=0.000 cache_lookup_ms=0.000 file_open_count=0 foreground_disk_reads=0 foreground_bytes_read=0 cache_grow_overlap=False additive_flush_overlap=False disk_cache_queue_depth=0 decode_queue_depth=0 foreground_frame_ready_immediate=True ui_lag_ms=8.000 frame_total_ms=3.000 sqlite_overlap_count=0 corr_session=s1 corr_mono_ms=1.0
    2026-05-12 | INFO | component=viewer role=main | modules.viewer.fast.qt_viewer_bridge._emit_foreground_disk_event | action=sess study=s series=1 job=- viewevt=v fn=- stage=- result=- | [FAST_FG_DISK] drag_session_id=d1 bridge=b1 viewer=v1 slice=11 source=direct_dicom_read cache_hit=False disk_wait_ms=22.000 decode_wait_ms=24.000 cache_lookup_ms=0.200 file_open_count=1 foreground_disk_reads=1 foreground_bytes_read=524288 cache_grow_overlap=True additive_flush_overlap=True disk_cache_queue_depth=4 decode_queue_depth=2 foreground_frame_ready_immediate=False ui_lag_ms=155.000 frame_total_ms=36.000 sqlite_overlap_count=1 corr_session=s1 corr_mono_ms=2.0
    2026-05-12 | INFO | component=viewer role=main | modules.viewer.fast.qt_viewer_bridge._emit_foreground_disk_event | action=sess study=s series=1 job=- viewevt=v fn=- stage=- result=- | [FAST_FG_DISK] drag_session_id=d1 bridge=b1 viewer=v1 slice=12 source=decode_wait cache_hit=False disk_wait_ms=0.000 decode_wait_ms=18.000 cache_lookup_ms=0.000 file_open_count=0 foreground_disk_reads=0 foreground_bytes_read=0 cache_grow_overlap=True additive_flush_overlap=False disk_cache_queue_depth=3 decode_queue_depth=3 foreground_frame_ready_immediate=False ui_lag_ms=120.000 frame_total_ms=28.000 sqlite_overlap_count=0 corr_session=s1 corr_mono_ms=3.0
    """

    payload = parse_smooth_stack_pressure_log_text(text)

    assert payload["aggregate"]["session_count"] == 1
    assert payload["aggregate"]["phase_row_count"] == 2
    assert payload["aggregate"]["foreground_event_count"] == 3
    assert payload["aggregate"]["foreground_memory_event_count"] == 1
    assert payload["aggregate"]["foreground_disk_required_event_count"] == 2
    assert abs(payload["aggregate"]["foreground_disk_dependency_ratio_pct"] - ((2.0 / 3.0) * 100.0)) < 1e-6
    assert payload["aggregate"]["foreground_ui_lag_p95_memory_hit_ms"] == 8.0
    assert payload["aggregate"]["foreground_ui_lag_p95_disk_hit_ms"] > 120.0
    assert payload["aggregate"]["foreground_disk_wait_max_ms"] == 22.0
    assert payload["aggregate"]["cache_miss_burst_count"] == 1
    assert payload["aggregate"]["cache_miss_burst_max_len"] == 2
    assert payload["aggregate"]["phase_sample_totals"]["download_only"] == 5
    assert payload["aggregate"]["phase_sample_totals"]["baseline"] == 3
    assert payload["aggregate"]["worst_event_p95_ms"] == 155.0
    assert payload["aggregate"]["worst_ui_lag_max_ms"] == 88.0
    assert payload["aggregate"]["total_main_thread_stall_count"] == 1
    assert payload["aggregate"]["ranked_phase_rows"][0]["phase"] == "download_only"


def test_classify_pressure_bottleneck_prefers_main_thread_block_signature():
    row = {
        "handler_p95_ms": 4.0,
        "longest_ui_gap_max_ms": 410.0,
        "main_thread_stall_count": 2,
        "disk_write_q_max": 0,
        "decode_q_p95": 0,
    }

    assert classify_pressure_bottleneck(row) == "main_thread_block"


def test_classify_pressure_bottleneck_distinguishes_disk_and_decode_pressure():
    disk_row = {
        "disk_write_q_max": 6,
        "disk_write_mb_s_p95": 31.0,
        "proc_write_mb_s_p95": 12.0,
        "decode_q_p95": 0,
        "frame_q_p95": 0,
    }
    decode_row = {
        "disk_write_q_max": 0,
        "disk_write_mb_s_p95": 0.0,
        "proc_write_mb_s_p95": 0.0,
        "decode_q_p95": 4,
        "frame_q_p95": 2,
    }

    assert classify_pressure_bottleneck(disk_row) == "disk_pressure"
    assert classify_pressure_bottleneck(decode_row) == "decode_backlog"


def test_parse_fast_event_pacing_tag():
    """[FAST_EVENT_PACING] rows parsed and aggregated into pacing_* aggregate keys."""
    text = (
        "2026-05-13 | INFO | component=viewer | [FAST_EVENT_PACING] "
        "drag_session_id=d1 bridge=b1 viewer=v1 duration_s=3.200 "
        "total_events=60 accepted_events=55 same_slice_rejected=2 scheduler_rejected=3 "
        "same_slice_ratio_pct=3.3 coalesce_ratio_pct=8.3 "
        "event_jitter_p95_ms=18.0 event_jitter_max_ms=55.0 "
        "set_to_image_p50_ms=4.5 set_to_image_p95_ms=14.0 set_to_image_max_ms=42.0 "
        "frame_present_interval_p50_ms=57.0 frame_present_interval_p95_ms=120.0 frame_present_interval_max_ms=310.0 "
        "implied_queue_wait_p95_ms=22.0 implied_queue_wait_max_ms=90.0 "
        "qt_repaint_delay_p50_ms=1.2 qt_repaint_delay_p95_ms=6.0 qt_repaint_delay_max_ms=15.0 "
        "corr_session=s1 corr_mono_ms=1000.0\n"
        "2026-05-13 | INFO | component=viewer | [FAST_EVENT_PACING] "
        "drag_session_id=d2 bridge=b1 viewer=v1 duration_s=2.100 "
        "total_events=40 accepted_events=38 same_slice_rejected=0 scheduler_rejected=2 "
        "same_slice_ratio_pct=0.0 coalesce_ratio_pct=5.0 "
        "event_jitter_p95_ms=12.0 event_jitter_max_ms=30.0 "
        "set_to_image_p50_ms=3.8 set_to_image_p95_ms=11.0 set_to_image_max_ms=28.0 "
        "frame_present_interval_p50_ms=52.0 frame_present_interval_p95_ms=95.0 frame_present_interval_max_ms=210.0 "
        "implied_queue_wait_p95_ms=15.0 implied_queue_wait_max_ms=60.0 "
        "qt_repaint_delay_p50_ms=0.8 qt_repaint_delay_p95_ms=4.0 qt_repaint_delay_max_ms=9.0 "
        "corr_session=s1 corr_mono_ms=5000.0\n"
    )
    payload = parse_smooth_stack_pressure_log_text(text)
    agg = payload["aggregate"]

    assert len(payload["pacing_rows"]) == 2
    assert agg["pacing_session_count"] == 2
    assert agg["pacing_total_events"] == 100
    assert agg["pacing_accepted_events"] == 93
    assert agg["pacing_same_slice_rejected"] == 2
    assert agg["pacing_scheduler_rejected"] == 5
    # p95 of [14.0, 11.0] = 14.0 (max of worst row)
    assert agg["pacing_set_to_image_p95_ms"] > 0.0
    assert agg["pacing_set_to_image_max_ms"] == 42.0
    # frame present interval max
    assert agg["pacing_frame_present_interval_max_ms"] == 310.0
    # jitter
    assert agg["pacing_event_jitter_max_ms"] == 55.0
    # Qt repaint delay
    assert agg["pacing_qt_repaint_delay_max_ms"] == 15.0
    assert agg["pacing_qt_repaint_delay_p95_ms"] > 0.0
    # implied queue wait
    assert agg["pacing_implied_queue_wait_max_ms"] == 90.0