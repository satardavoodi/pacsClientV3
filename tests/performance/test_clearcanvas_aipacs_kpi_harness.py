from __future__ import annotations

import pytest

from tools.performance.clearcanvas_aipacs_kpi_harness import (
    REPO_ROOT,
    _resolve_stack_drag_policy,
    _run_pattern_step,
    build_manual_result_payload,
    build_execution_pack,
    compare_payloads,
    load_benchmark_model,
    load_manual_step_results,
    load_scenarios,
    parse_aipacs_log_text,
    summarize_manual_step_results,
)


def test_parse_aipacs_log_text_counts_duplicates():
    text = """
    2026-04-15 10:00:00 FAST:first_image_visible series=101 slice=0 decode_ms=3.0 total_ms=12.5
    2026-04-15 10:00:01 [B3.8_SCROLL] frame=20 slice=40 total_ms=4.2 decode_ms=0.0 wl_ms=1.2 src=surrogate px_cache=20 fr_cache=19
    2026-04-15 10:00:02 [B3.8_SCROLL] frame=40 slice=41 total_ms=2.3 decode_ms=0.0 wl_ms=0.0 src=hit px_cache=20 fr_cache=19
    2026-04-15 10:00:03 progressive-fast: series=303 COMPLETE (123 slices)
    2026-04-15 10:00:04 progressive-fast: series=303 COMPLETE (123 slices)
    2026-04-15 10:00:05 progressive-fast: series=303 cache-warm dispatched around slice=12
    2026-04-15 10:00:06 progressive-fast: series=303 cache-warm dispatched around slice=12
    2026-04-15 10:00:07 progressive: duplicate terminal progress ignored series=303 downloaded=123 total=123 guard=terminal_complete
    """

    metrics = parse_aipacs_log_text(text)

    assert metrics["first_image_visible_ms"] == 12.5
    assert metrics["scroll_sample_count"] == 2
    assert metrics["terminal_completion_duplicate_count"] == 2
    assert metrics["cache_warm_duplicate_count"] == 1
    assert metrics["surrogate_scroll_ratio_pct"] == 50.0
    assert metrics["cache_hit_scroll_ratio_pct"] == 50.0


def test_parse_aipacs_log_text_tracks_stack_drag_decode_and_nondecode_hitches():
    text = """
    2026-04-16 20:08:29.924632 | INFO | modules.viewer.fast.qt_viewer_bridge._on_stack_drag_state | [B3.4_DIAG] STACK_DRAG_START slice=140
    2026-04-16 20:08:31.286345 | INFO | modules.viewer.fast.qt_viewer_bridge.set_slice | [B3.8_SCROLL] frame=40 slice=136 total_ms=2.5 decode_ms=0.0 wl_ms=0.0 src=hit px_cache=51 fr_cache=58
    2026-04-16 20:08:43.199580 | INFO | modules.viewer.fast.qt_viewer_bridge.set_slice | [B3.8_SCROLL] frame=120 slice=278 total_ms=17.4 decode_ms=12.5 wl_ms=2.4 src=decode px_cache=96 fr_cache=96
    2026-04-16 20:08:47.009102 | INFO | modules.viewer.fast.qt_viewer_bridge.set_slice | qt-viewer-bridge set_slice idx=316 total_ms=68.4 decode=0.0 filter=0.0 wl=0.0
    2026-04-16 20:08:47.213813 | INFO | modules.viewer.fast.qt_viewer_bridge._on_stack_drag_state | [B3.4_DIAG] STACK_DRAG_STOP slice=317 (settle in 200ms)
    """

    metrics = parse_aipacs_log_text(text)

    assert metrics["stack_drag_sample_count"] == 2
    assert metrics["stack_drag_decode_zero_ratio_pct"] == 50.0
    assert metrics["stack_drag_decode_hitch_count"] == 1
    assert metrics["stack_drag_decode_hitch_max_ms"] == 17.4
    assert metrics["stack_drag_nondecode_hitch_count"] == 1
    assert metrics["stack_drag_nondecode_hitch_max_ms"] == 68.4


def test_parse_aipacs_log_text_tracks_set_slice_and_scroll_stage_hitches():
    text = """
    2026-04-16 20:08:47.009102 | INFO | modules.viewer.fast.qt_viewer_bridge.set_slice | [FAST_SET_SLICE_STAGE] idx=316 total_ms=68.4 prepare_ms=0.1 interaction_prep_ms=0.4 frame_ms=1.7 display_ms=24.6 annotation_ms=0.0 metrics_ms=0.2 ui_lag_ms=33.3 fast=True interaction=drag decode_ms=0.0 filter_ms=0.0 wl_ms=0.0
    2026-04-16 20:08:47.010905 | INFO | modules.viewer.fast.qt_viewer_bridge._on_qt_scroll | [FAST_QT_SCROLL_STAGE] target=316 total_ms=73.2 set_slice_ms=68.4 slider_ms=0.1 sync_ms=3.8 reference_ms=0.5 drag=True interaction=drag
    """

    metrics = parse_aipacs_log_text(text)

    assert metrics["set_slice_stage_hitch_count"] == 1
    assert metrics["set_slice_stage_display_max_ms"] == 24.6
    assert metrics["set_slice_stage_ui_lag_max_ms"] == 33.3
    assert metrics["qt_scroll_stage_hitch_count"] == 1
    assert metrics["qt_scroll_stage_set_slice_max_ms"] == 68.4
    assert metrics["qt_scroll_stage_sync_max_ms"] == 3.8


def test_parse_aipacs_log_text_tracks_unified_fast_advanced_and_shared_metrics():
    text = """
    2026-04-23 | INFO | component=viewer role=main | modules.viewer.fast.qt_viewer_bridge.set_slice | action=sess study=s series=1 job=- viewevt=v fn=- stage=- result=- | FAST:first_image_visible series=1 slice=0 decode_ms=3.0 total_ms=42.0
    2026-04-23 | INFO | component=viewer role=main | modules.viewer.fast.qt_viewer_bridge._emit_drag | action=sess study=s series=1 job=- viewevt=v fn=- stage=- result=- | [FAST_DRAG_KPI] bridge=b1 viewer=q1 duration_s=2.000 targets=20 event_p50_ms=44.0 event_p95_ms=121.0 handler_p50_ms=2.0 handler_p95_ms=9.0 ui_lag_max_ms=210.0 prefetch_per_s=0.0 background_decode_count=3
    2026-04-23 | INFO | component=viewer role=main | modules.viewer.advanced.viewer_2d._set_slice_impl | action=sess study=s series=2 job=- viewevt=v fn=ImageViewer2D.set_slice stage=sub_timing result=- | viewer-scroll sub-timing: SetSlice=13.4ms WL=0.7ms corners=0.1ms Render=16.3ms total=30.5ms
    2026-04-23 | INFO | component=db role=download-subprocess | modules.download_manager.download.series_downloader.log_stage_timing | action=sess study=s series=2 job=j viewevt=- fn=SeriesDownloader._save_series_instances_to_db stage=batch_insert_instances result=ok | stage-timing duration_ms=37.25 query_type=write caller_area=shared_download viewer_mode=Shared
    2026-04-23 | INFO | component=db role=main | database._pool.log_stage_timing | action=sess study=s series=1 job=- viewevt=v fn=database.get_db_connection stage=transaction_scope result=ok | stage-timing duration_ms=6.50 query_type=mixed caller_area=fast_interaction viewer_mode=FAST caller_module=modules.viewer.fast.qt_viewer_bridge caller_function=set_slice thread_role=main
    2026-04-23 | INFO | component=download role=download-subprocess | modules.download_manager.network.socket_client.log_stage_timing | action=sess study=s series=2 job=j viewevt=- fn=SocketDicomClient.send_request stage=request_total result=ok | stage-timing duration_ms=88.5
    2026-04-23 | INFO | component=download role=download-subprocess | modules.download_manager.network.socket_client.log_stage_timing | action=sess study=s series=2 job=j viewevt=- fn=SocketDicomClient.download_series stage=dicom_file_write_batch result=ok | stage-timing duration_ms=44.0 files=5 bytes=102400 disk_write_ms=7.50 query_type=disk_write viewer_mode=Shared
    2026-04-23 | INFO | component=download role=download-subprocess | modules.download_manager.download.series_downloader.log_stage_timing | action=sess study=s series=2 job=j viewevt=- fn=SeriesDownloader._save_series_instances_to_db stage=dicom_header_decode_total result=ok | stage-timing duration_ms=12.0 files=5 query_type=disk_read viewer_mode=Shared
    2026-04-23 | INFO | component=download role=download-subprocess | modules.download_manager.network.socket_client.download_series | action=sess study=s series=2 job=j viewevt=- fn=- stage=- result=- | download-pipeline-summary series=2 elapsed_s=1.20 disk_write_ms=22.00 decode_ms=30.00 decompress_ms=0.00
    2026-04-23 | INFO | component=viewer role=main | PacsClient.pacs.patient_tab.utils.image_io.load_single_series_by_number | action=sess study=s series=2 job=- viewevt=v fn=- stage=group_images result=- | viewer-data stage=group_images duration_ms=4.25
    2026-04-23 | WARNING | component=download role=main | modules.download_manager.coordinator.series_intent_coordinator.schedule_priority_start_retry | action=sess study=s series=2 job=- viewevt=v fn=- stage=- result=- | [INTENT] Priority start retry exhausted for s after 3 attempts
    2026-04-23 | ERROR | component=download role=main | modules.download_manager.ui.widget._dm_workers._on_worker_error | action=sess study=s series=2 job=- viewevt=v fn=- stage=- result=- | Worker error: s - Paused for higher priority download (preemption)
    2026-04-23 | INFO | component=viewer role=main | PacsClient.pacs.patient_tab.utils.thumbnail_manager.complete_series_download | action=sess study=- series=- job=- viewevt=- fn=- stage=- result=- | FAST:thumbnail_pipeline event=end series=1 t_abs=100.0 dl_ms=74.3
    """

    metrics = parse_aipacs_log_text(text)

    assert metrics["fast_first_image_visible_ms"] == 42.0
    assert metrics["fast_drag_event_p95_ms"] == 121.0
    assert metrics["fast_prefetch_zero_drag_ratio_pct"] == 100.0
    assert metrics["advanced_stack_event_p95_ms"] == 30.5
    assert metrics["advanced_vtk_render_ms_p95"] == 16.3
    assert metrics["db_transaction_scope_p95_ms"] == 35.71
    assert metrics["db_stage_timing_sample_count"] == 2
    assert metrics["db_write_transaction_p95_ms"] == 37.25
    assert metrics["db_caller_area_counts"]["shared_download"] == 1
    assert metrics["db_caller_area_counts"]["fast_interaction"] == 1
    assert metrics["db_viewer_mode_counts"]["FAST"] == 1
    assert metrics["main_thread_db_ms_during_fast_drag"] == 6.5
    assert metrics["socket_batch_rtt_p95_ms"] == 88.5
    assert metrics["dicom_file_write_ms_p95"] == 7.5
    assert metrics["dicom_file_write_batch_count"] == 1
    assert metrics["dicom_file_write_bytes_total"] == 102400
    assert metrics["dicom_file_read_ms_p95"] == 12.0
    assert metrics["dicom_file_read_batch_count"] == 1
    assert metrics["main_thread_disk_scan_ms"] == 4.25
    assert metrics["main_thread_disk_scan_p95_ms"] == 4.25
    assert metrics["priority_retry_exhausted_count"] == 1
    assert metrics["preemption_worker_error_count"] == 1
    assert metrics["thumbnail_generation_ms_p95"] == 74.3
    assert metrics["viewer_mode_counts"]["FAST_QT"] >= 1
    assert metrics["viewer_mode_counts"]["Advanced"] >= 1
    assert metrics["viewer_mode_counts"]["Shared"] >= 1


def test_compare_payloads_flags_aipacs_overhead():
    left = {
        "viewer": "AI-PACS",
        "kpis": {
            "set_slice_present_p95_ms": 28.0,
            "terminal_completion_duplicate_count": 3,
            "cache_warm_duplicate_count": 2,
            "stack_drag_decode_hitch_count": 2,
            "stack_drag_nondecode_hitch_count": 1,
        },
        "process_summary": {
            "cpu_p95_pct": 160.0,
            "thread_count_p95": 14.0,
        },
    }
    right = {
        "viewer": "ClearCanvas",
        "process_summary": {
            "cpu_p95_pct": 95.0,
            "thread_count_p95": 7.0,
        },
        "log_metrics": {
            "terminal_completion_duplicate_count": 0,
            "cache_warm_duplicate_count": 0,
        },
    }

    comparison = compare_payloads(left, right)

    assert comparison["rows"]
    joined = "\n".join(comparison["findings"])
    assert "repeats terminal progressive work" in joined
    assert "duplicate post-completion cache warm work" in joined
    assert "consumes materially more CPU" in joined
    assert "more concurrent actors alive" in joined
    assert "cache-edge foreground decode hitches during stack drag" in joined
    assert "non-decode main-thread hitches during stack drag" in joined


def test_load_scenarios_contains_expected_ids():
    scenario_file = REPO_ROOT / "tests" / "performance" / "clearcanvas_aipacs_scenarios.json"
    scenarios = load_scenarios(scenario_file)

    assert "common_local_viewing" in scenarios
    assert "aipacs_live_download_overlap" in scenarios
    assert "aipacs_stack_drag_policy_compare" in scenarios
    assert "clearcanvas_background_copy_pressure_approx" in scenarios
    assert scenarios["common_local_viewing"]["steps"][0]["id"] == "open_dataset"
    assert scenarios["common_local_viewing"]["steps"][0]["phase"] == "A"
    assert "kpi_targets" in scenarios["common_local_viewing"]
    assert "common" in scenarios["common_local_viewing"]["kpi_targets"]
    assert scenarios["aipacs_live_download_overlap"]["kpi_targets"]["aipacs_overlap"]["terminal_completion_duplicate_count"]["goal"] == "0"
    assert scenarios["aipacs_live_download_overlap"]["kpi_targets"]["aipacs_overlap"]["stack_drag_decode_hitch_count"]["goal"] == "0 preferred"
    assert scenarios["aipacs_stack_drag_policy_compare"]["kpi_targets"]["aipacs_stack_drag"]["stack_drag_nondecode_hitch_count"]["goal"] == "0 preferred"


def test_resolve_stack_drag_policy_prefers_cli_then_step_then_scenario():
    scenario = {"stack_drag_policy": "scenario_policy"}
    step = {"stack_drag_policy": "step_policy"}

    assert _resolve_stack_drag_policy(scenario=scenario, step=step, cli_policy="cli_policy") == "cli_policy"
    assert _resolve_stack_drag_policy(scenario=scenario, step=step, cli_policy="") == "step_policy"
    assert _resolve_stack_drag_policy(scenario=scenario, step={}, cli_policy="") == "scenario_policy"


def test_run_pattern_step_stack_drag_uses_qt_viewer_policy(monkeypatch):
    pytest.importorskip("PySide6")
    calls = []

    class DummyPipeline:
        slice_count = 64

    class DummyViewer:
        def __init__(self):
            self._stacked_accum = 0.0

        def resize(self, width, height):
            calls.append(("resize", width, height))

        def set_stack_drag_policy(self, policy):
            calls.append(("policy", policy))

        def _get_stack_drag_profile(self):
            return 5.0, 4

        def _consume_stack_drag_delta(self, dy):
            calls.append(("consume", round(float(dy), 2)))
            return 2

    class DummyBridge:
        def __init__(self, viewer, pipeline, metadata):
            calls.append(("bridge", metadata["series"]["image_count"]))

        def set_slice(self, idx, fast_interaction=False):
            calls.append(("set_slice", idx, fast_interaction))

        def _on_stack_drag_state(self, active):
            calls.append(("drag_state", active))

        def _on_qt_scroll(self, delta):
            calls.append(("scroll", delta))

        def _on_interaction_settled(self):
            calls.append(("settled",))

    monkeypatch.setattr(
        "tools.performance.clearcanvas_aipacs_kpi_harness._ensure_qapplication",
        lambda: None,
    )
    monkeypatch.setattr(
        "modules.viewer.fast.qt_slice_viewer.QtSliceViewer",
        DummyViewer,
    )
    monkeypatch.setattr(
        "modules.viewer.fast.qt_viewer_bridge.QtViewerBridge",
        DummyBridge,
    )

    _run_pattern_step(
        DummyPipeline(),
        {
            "kind": "stack_drag",
            "events": 3,
            "total_dy": 30.0,
            "instruction": "stack drag test",
        },
        stack_drag_policy="clearcanvas",
    )

    assert ("policy", "clearcanvas") in calls
    assert calls.count(("scroll", 2)) == 3
    assert ("drag_state", True) in calls
    assert ("drag_state", False) in calls
    assert ("settled",) in calls


def test_build_execution_pack_writes_templates(tmp_path):
    scenario_file = REPO_ROOT / "tests" / "performance" / "clearcanvas_aipacs_scenarios.json"
    model_file = REPO_ROOT / "tests" / "performance" / "clearcanvas_aipacs_benchmark_model.json"
    scenarios = load_scenarios(scenario_file)
    model = load_benchmark_model(model_file)

    manifest = build_execution_pack(
        scenarios=[scenarios["common_local_viewing"]],
        model=model,
        output_dir=tmp_path,
        viewer="both",
        dataset=r"C:\bench\dicom",
    )

    instructions = tmp_path / "instructions.md"
    manual_csv = tmp_path / "manual_step_results.csv"

    assert instructions.exists()
    assert manual_csv.exists()
    assert "common_local_viewing" in instructions.read_text(encoding="utf-8")
    assert manifest["dataset"] == r"C:\bench\dicom"


def test_summarize_manual_results_builds_clearcanvas_payload(tmp_path):
    manual_csv = tmp_path / "manual.csv"
    manual_csv.write_text(
        "\n".join(
            [
                "step_id,phase,scenario_id,app,action,timing_marker_start,timing_marker_end,time_ms,cpu_pct,rss_mb,thread_count,notes,fairness,equivalence_confidence",
                "S2,A,common_local_viewing,clearcanvas,Open same local study/series,open command issued,first image visible,920,,,,,,High",
                "S4,C,common_local_viewing,clearcanvas,Scroll 10 slices slowly,first wheel event,10th slice visibly presented,120,,,,,,High",
                "S5,C,common_local_viewing,clearcanvas,Fast burst,burst start,burst visibly complete,180,,,,,,Medium",
                "S6,C,common_local_viewing,clearcanvas,Direction reversal,reversal loop start,reversal loop end,140,,,,,,High",
            ]
        ),
        encoding="utf-8",
    )
    process_payload = {
        "viewer": "ClearCanvas",
        "process_summary": {
            "cpu_p95_pct": 91.0,
            "rss_peak_mb": 512.0,
            "thread_count_p95": 8.0,
            "read_mb_delta": 120.0,
            "write_mb_delta": 4.0,
        },
    }

    rows = load_manual_step_results(manual_csv)
    manual_summary = summarize_manual_step_results(rows, app="clearcanvas")
    payload = build_manual_result_payload(
        process_payload=process_payload,
        manual_rows=rows,
        app="clearcanvas",
        viewer_label="ClearCanvas",
    )

    assert manual_summary["first_image_visible_ms"] == 920.0
    assert manual_summary["set_slice_present_p95_ms"] > 0
    assert payload["kpis"]["cpu_p95_pct"] == 91.0
    assert payload["kpis"]["first_image_visible_ms"] == 920.0
