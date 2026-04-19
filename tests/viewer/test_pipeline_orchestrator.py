from modules.viewer.pipeline.orchestrator import PipelineOrchestrator, PipelineState


def test_orchestrator_snapshot_tracks_recent_events_and_counts():
    orch = PipelineOrchestrator()

    orch.on_download_session_started("study-1")
    orch.on_series_download_started("101")
    orch.on_series_download_completed("101")
    orch.on_study_download_completed("study-1")

    snap = orch.snapshot()

    assert snap["state"] == PipelineState.POST_DOWNLOAD.name
    assert snap["study_download_complete"] is True
    assert snap["active_download_count"] == 0
    assert snap["completed_series_count"] == 1
    assert snap["completed_series"] == ["101"]
    assert snap["transition_seq"] >= 4
    assert len(snap["recent_events"]) >= 4
    assert snap["recent_events"][-1]["event"] == "study_download_completed"
    assert snap["recent_events"][-1]["owner_block"] == "block_3_cache_scroll_orchestration"
    assert snap["most_recent_event"]["event"] == "study_download_completed"
    assert snap["event_counts_by_block"]["block_1_data_services"] == 3
    assert snap["event_counts_by_block"]["block_3_cache_scroll_orchestration"] == 1
    assert snap["event_counts_by_name"]["series_download_started"] == 1
    assert snap["event_counts_by_name"]["series_download_completed"] == 1


def test_orchestrator_event_sequence_is_monotonic_and_block_owned():
    orch = PipelineOrchestrator()

    orch.on_download_session_started("study-2")
    orch.on_series_download_started("201")
    orch.mark_pre_downloaded()
    orch.reset()

    events = orch.snapshot()["recent_events"]
    seqs = [event["seq"] for event in events]
    owner_blocks = {event["owner_block"] for event in events}

    assert seqs == sorted(seqs)
    assert "block_1_data_services" in owner_blocks
    assert "block_3_cache_scroll_orchestration" in owner_blocks


def test_orchestrator_ready_transition_is_recorded_in_snapshot():
    orch = PipelineOrchestrator()
    orch.mark_pre_downloaded()

    orch.on_all_warmed_up()

    snap = orch.snapshot()

    assert snap["state"] == PipelineState.READY.name
    assert snap["recent_events"][-1]["event"] == "all_warmed_up"
    assert snap["recent_events"][-1]["state_after"] == PipelineState.READY.name


def test_orchestrator_snapshot_exposes_compact_event_summary():
    orch = PipelineOrchestrator()

    orch.on_download_session_started("study-3")
    orch.on_series_download_started("301")
    orch.on_series_download_started("302")
    orch.on_series_download_completed("301")

    snap = orch.snapshot()

    assert snap["most_recent_event"]["event"] == "series_download_completed"
    assert snap["most_recent_event"]["series_number"] == "301"
    assert snap["event_counts_by_block"]["block_1_data_services"] == 4
    assert snap["event_counts_by_name"]["series_download_started"] == 2
    assert snap["event_counts_by_name"]["series_download_completed"] == 1