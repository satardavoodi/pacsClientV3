from __future__ import annotations

import json

from tools.performance.clearcanvas_aipacs_kpi_harness import REPO_ROOT


MODEL_PATH = REPO_ROOT / "tests" / "performance" / "pipeline_job_block_model.json"


def _load_model() -> dict:
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def test_pipeline_job_block_model_has_expected_scenarios():
    model = _load_model()

    scenario_ids = [scenario["id"] for scenario in model["scenarios"]]
    assert scenario_ids == ["open_new_patient", "stack_scroll_image"]
    assert set(model["blocks"].keys()) == {
        "block_1_data_services",
        "block_2_viewer_hot_path",
        "block_3_cache_scroll_orchestration",
    }


def test_every_listed_job_has_block_owner_and_is_not_orphaned():
    model = _load_model()
    valid_blocks = set(model["blocks"].keys())

    all_job_ids: set[str] = set()
    for scenario in model["scenarios"]:
        jobs = scenario["jobs"]
        assert jobs, f"Scenario {scenario['id']} must list at least one job"
        for job in jobs:
            assert job["id"] not in all_job_ids, f"Duplicate job id: {job['id']}"
            all_job_ids.add(job["id"])
            assert job["block_id"] in valid_blocks
            assert job["owner_file"].strip()
            assert job["trigger"].strip()
            assert job["worker_model"].strip()
            assert job["orphan_allowed"] is False, f"Job {job['id']} must not be orphaned"


def test_open_new_patient_flow_has_data_viewer_and_orchestration_jobs():
    model = _load_model()
    scenario = next(s for s in model["scenarios"] if s["id"] == "open_new_patient")
    job_ids = {job["id"] for job in scenario["jobs"]}

    assert {
        "open_request_guard",
        "download_manager_start_priority",
        "single_series_full_load",
        "progressive_start",
        "terminal_completion_finalize",
    }.issubset(job_ids)

    by_block = {}
    for job in scenario["jobs"]:
        by_block.setdefault(job["block_id"], set()).add(job["id"])

    assert "block_1_data_services" in by_block
    assert "block_2_viewer_hot_path" in by_block
    assert "block_3_cache_scroll_orchestration" in by_block


def test_stack_scroll_flow_keeps_visible_present_in_block2_and_control_in_block3():
    model = _load_model()
    scenario = next(s for s in model["scenarios"] if s["id"] == "stack_scroll_image")
    jobs = {job["id"]: job for job in scenario["jobs"]}

    assert jobs["qt_set_slice_present"]["block_id"] == "block_2_viewer_hot_path"
    assert jobs["rendered_frame_fetch"]["block_id"] == "block_2_viewer_hot_path"
    assert jobs["slider_sync"]["block_id"] == "block_3_cache_scroll_orchestration"
    assert jobs["interaction_settle_timer"]["block_id"] == "block_3_cache_scroll_orchestration"
    assert jobs["settled_exact_rerender"]["block_id"] == "block_2_viewer_hot_path"
