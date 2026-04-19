from __future__ import annotations

import json

from tools.performance.clearcanvas_aipacs_kpi_harness import (
    REPO_ROOT,
    block_summary_to_markdown,
    load_block_kpi_model,
    summarize_payload_by_block,
)


def test_load_block_kpi_model_contains_three_blocks():
    model = load_block_kpi_model(REPO_ROOT / "tests" / "performance" / "block_kpi_model.json")

    assert model["version"] == "2026-04-17"
    assert [block["id"] for block in model["blocks"]] == [
        "block_1_data_services",
        "block_2_viewer_hot_path",
        "block_3_cache_scroll_orchestration",
    ]


def test_summarize_payload_by_block_groups_existing_metrics_and_flags_missing():
    model = load_block_kpi_model(REPO_ROOT / "tests" / "performance" / "block_kpi_model.json")
    payload = {
        "viewer": "AI-PACS",
        "mode": "headless-aipacs-fast",
        "scenario_id": "aipacs_live_download_overlap",
        "scenario_title": "Live overlap",
        "kpis": {
            "first_image_visible_ms": 640.0,
            "set_slice_present_p95_ms": 24.5,
            "decode_p95_ms": 5.2,
            "frame_render_p95_ms": 8.7,
            "slow_frame_count_16ms": 4,
            "stale_task_ratio": 0.22,
            "cache_hit_ratio_pct": 91.5,
            "longest_ui_gap_ms": 17.1,
        },
        "log_metrics": {
            "terminal_completion_duplicate_count": 0,
            "cache_warm_duplicate_count": 0,
            "stack_drag_decode_hitch_count": 1,
            "stack_drag_nondecode_hitch_count": 0,
        },
        "process_summary": {
            "cpu_p95_pct": 74.0,
            "thread_count_p95": 11.0,
            "read_mb_delta": 512.0,
            "write_mb_delta": 128.0,
        },
    }

    summary = summarize_payload_by_block(payload, model)

    assert summary["viewer"] == "AI-PACS"
    assert summary["scenario_block_focus"]["primary_blocks"] == [
        "block_1_data_services",
        "block_2_viewer_hot_path",
        "block_3_cache_scroll_orchestration",
    ]

    by_id = {block["block_id"]: block for block in summary["blocks"]}

    block1 = by_id["block_1_data_services"]
    assert any(metric["key"] == "cpu_p95_pct" for metric in block1["present_metrics"])
    assert any(metric["key"] == "download_preemption_fail_count" for metric in block1["missing_metrics"])

    block2 = by_id["block_2_viewer_hot_path"]
    assert any(metric["key"] == "first_image_visible_ms" for metric in block2["present_metrics"])
    assert any(metric["key"] == "set_slice_present_p95_ms" for metric in block2["present_metrics"])

    block3 = by_id["block_3_cache_scroll_orchestration"]
    assert any(metric["key"] == "stale_task_ratio" for metric in block3["present_metrics"])
    assert any(metric["key"] == "ui_event_loop_lag_ms_p95" for metric in block3["missing_metrics"])


def test_block_summary_to_markdown_lists_present_and_missing_metrics():
    model = load_block_kpi_model(REPO_ROOT / "tests" / "performance" / "block_kpi_model.json")
    payload = {
        "viewer": "AI-PACS",
        "mode": "log-parse",
        "scenario_id": "common_local_viewing",
        "scenario_title": "Common local viewing",
        "kpis": {
            "first_image_visible_ms": 420.0,
            "set_slice_present_p95_ms": 12.0,
            "stale_task_ratio": 0.1,
        },
        "process_summary": {
            "cpu_p95_pct": 48.0,
            "thread_count_p95": 8.0,
            "read_mb_delta": 42.0,
            "write_mb_delta": 6.0,
        },
        "log_metrics": {
            "terminal_completion_duplicate_count": 0,
            "cache_warm_duplicate_count": 0,
            "stack_drag_nondecode_hitch_count": 0,
        },
    }

    summary = summarize_payload_by_block(payload, model)
    markdown = block_summary_to_markdown(summary)

    assert "# FAST Block KPI Summary" in markdown
    assert "## Block 1 - Data services" in markdown
    assert "## Block 2 - Viewer hot path" in markdown
    assert "## Block 3 - Cache, scroll, orchestration" in markdown
    assert "_missing_" in markdown
    assert "`First image visible`" in markdown
