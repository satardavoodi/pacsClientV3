import threading

from modules.viewer.fast.system_load_controller import (
    BlockId,
    WorkClass,
    SystemLoadController,
)


def test_default_policy_is_normal_when_idle():
    ctrl = SystemLoadController()

    snap = ctrl.snapshot(heavy_download_active=False, now_ms=100.0)

    assert snap.fast_interaction_active is False
    assert snap.heavy_download_active is False
    assert snap.ui_event_loop_lag_ms == 0.0
    assert snap.protected_ui_cadence is False
    assert ctrl.progressive_signal_interval_ms(
        heavy_download_active=False,
        now_ms=100.0,
    ) == 100.0
    assert ctrl.thumbnail_progress_interval_ms(
        heavy_download_active=False,
        now_ms=100.0,
    ) == 100.0
    assert ctrl.thumbnail_log_interval_ms(
        heavy_download_active=False,
        now_ms=100.0,
    ) == 250.0


def test_fast_interaction_enters_protected_mode():
    ctrl = SystemLoadController()

    ctrl.update_fast_interaction(True, now_ms=100.0, grace_ms=250.0)
    snap = ctrl.snapshot(heavy_download_active=False, now_ms=200.0)

    assert snap.fast_interaction_active is True
    assert snap.protected_ui_cadence is True
    assert ctrl.progressive_signal_interval_ms(
        heavy_download_active=False,
        now_ms=200.0,
    ) == 500.0
    assert ctrl.cap_prefetch_radius(
        15,
        fast_interaction_active=True,
        heavy_download_active=False,
        now_ms=200.0,
    ) == 3


def test_ui_lag_probe_enables_protected_mode_without_download():
    ctrl = SystemLoadController()

    ctrl.record_ui_tick(now_ms=0.0)
    lag = ctrl.record_ui_tick(now_ms=90.0, nominal_interval_ms=16.0)
    snap = ctrl.snapshot(heavy_download_active=False, now_ms=90.0)

    assert lag >= 50.0
    assert snap.ui_event_loop_lag_ms >= 50.0
    assert snap.protected_ui_cadence is True
    policy = ctrl.policy_for(
        WorkClass.THUMBNAIL_UI,
        heavy_download_active=False,
        now_ms=90.0,
    )
    assert policy.coalesce_interval_ms == 500.0
    assert policy.defer_during_protected_ui is True


def test_ui_lag_stales_out_after_grace_window():
    ctrl = SystemLoadController()

    ctrl.record_ui_tick(now_ms=0.0)
    ctrl.record_ui_tick(now_ms=90.0, nominal_interval_ms=16.0)

    assert ctrl.get_ui_event_loop_lag_ms(now_ms=200.0) > 0.0
    assert ctrl.get_ui_event_loop_lag_ms(now_ms=1000.0) == 0.0


def test_heavy_download_prefetch_policy_caps_radius():
    ctrl = SystemLoadController()

    snap = ctrl.snapshot(heavy_download_active=True, now_ms=100.0)
    policy = ctrl.policy_for(
        WorkClass.PREFETCH,
        heavy_download_active=True,
        now_ms=100.0,
    )

    assert snap.protected_ui_cadence is True
    assert policy.radius_cap == 3
    assert ctrl.cap_prefetch_radius(
        8,
        fast_interaction_active=False,
        heavy_download_active=True,
        now_ms=100.0,
    ) == 3


def test_protected_ui_defers_nonterminal_progressive_grow():
    ctrl = SystemLoadController()

    ctrl.update_fast_interaction(True, now_ms=100.0, grace_ms=250.0)
    policy = ctrl.policy_for(
        WorkClass.PROGRESSIVE_GROW,
        heavy_download_active=False,
        now_ms=150.0,
    )

    assert policy.defer_during_protected_ui is True


def test_progressive_grow_interval_is_slowed_during_download_and_scroll():
    ctrl = SystemLoadController()

    ctrl.update_fast_interaction(True, now_ms=100.0, grace_ms=250.0)
    policy = ctrl.policy_for(
        WorkClass.PROGRESSIVE_GROW,
        heavy_download_active=True,
        now_ms=150.0,
    )

    assert policy.coalesce_interval_ms == 750.0
    assert policy.defer_during_protected_ui is True


def test_progressive_grow_interval_is_slowed_during_download_only():
    ctrl = SystemLoadController()

    policy = ctrl.policy_for(
        WorkClass.PROGRESSIVE_GROW,
        heavy_download_active=True,
        now_ms=150.0,
    )

    assert policy.coalesce_interval_ms == 500.0
    assert policy.defer_during_protected_ui is True


def test_protected_ui_defers_cache_warm_even_without_download():
    ctrl = SystemLoadController()

    ctrl.record_ui_tick(now_ms=0.0)
    ctrl.record_ui_tick(now_ms=90.0, nominal_interval_ms=16.0)
    policy = ctrl.policy_for(
        WorkClass.CACHE_WARM,
        heavy_download_active=False,
        now_ms=90.0,
    )

    assert policy.defer_during_protected_ui is True


def test_cache_warm_is_coalesced_until_interval_expires():
    ctrl = SystemLoadController()

    ctrl.update_fast_interaction(True, now_ms=100.0, grace_ms=250.0)

    first = ctrl.should_admit(
        WorkClass.CACHE_WARM,
        {"key": "series-101"},
        heavy_download_active=True,
        fast_interaction_active=True,
        now_ms=120.0,
    )
    second = ctrl.should_admit(
        WorkClass.CACHE_WARM,
        {"key": "series-101"},
        heavy_download_active=True,
        fast_interaction_active=True,
        now_ms=300.0,
    )
    third = ctrl.should_admit(
        WorkClass.CACHE_WARM,
        {"key": "series-101"},
        heavy_download_active=True,
        fast_interaction_active=True,
        now_ms=900.0,
    )

    assert first is True
    assert second is False
    assert third is True


def test_final_render_is_always_admitted_under_protected_ui():
    ctrl = SystemLoadController()

    ctrl.update_fast_interaction(True, now_ms=100.0, grace_ms=250.0)

    assert ctrl.should_admit(
        WorkClass.FINAL_RENDER,
        {"key": "viewer-1"},
        heavy_download_active=True,
        fast_interaction_active=True,
        now_ms=120.0,
    ) is True


def test_progress_update_is_coalesced_until_interval_expires():
    ctrl = SystemLoadController()

    first = ctrl.should_admit(
        WorkClass.PROGRESS_UPDATE,
        {"key": "series-101"},
        heavy_download_active=True,
        fast_interaction_active=False,
        now_ms=100.0,
    )
    second = ctrl.should_admit(
        WorkClass.PROGRESS_UPDATE,
        {"key": "series-101"},
        heavy_download_active=True,
        fast_interaction_active=False,
        now_ms=150.0,
    )
    third = ctrl.should_admit(
        WorkClass.PROGRESS_UPDATE,
        {"key": "series-101"},
        heavy_download_active=True,
        fast_interaction_active=False,
        now_ms=620.0,
    )

    assert first is True
    assert second is False
    assert third is True


def test_progress_update_interval_is_slowed_during_download_and_scroll():
    ctrl = SystemLoadController()

    ctrl.update_fast_interaction(True, now_ms=100.0, grace_ms=250.0)

    assert ctrl.progress_update_interval_ms(
        heavy_download_active=True,
        fast_interaction_active=True,
        now_ms=150.0,
    ) == 750.0


def test_progress_update_interval_is_slowed_during_download_only():
    ctrl = SystemLoadController()

    assert ctrl.progress_update_interval_ms(
        heavy_download_active=True,
        fast_interaction_active=False,
        now_ms=150.0,
    ) == 500.0


def test_prefetch_is_rejected_when_distance_exceeds_radius_cap():
    ctrl = SystemLoadController()

    ctrl.update_fast_interaction(True, now_ms=100.0, grace_ms=250.0)

    assert ctrl.should_admit(
        WorkClass.PREFETCH,
        {"key": "series-101:center-20", "distance": 1},
        heavy_download_active=True,
        fast_interaction_active=True,
        now_ms=120.0,
    ) is True
    assert ctrl.should_admit(
        WorkClass.PREFETCH,
        {"key": "series-101:center-20", "distance": 4},
        heavy_download_active=True,
        fast_interaction_active=True,
        now_ms=220.0,
    ) is False


def test_drag_prefetch_gets_wider_mixed_load_cap():
    ctrl = SystemLoadController()

    ctrl.update_fast_interaction(True, now_ms=100.0, grace_ms=250.0)

    policy = ctrl.policy_for(
        WorkClass.PREFETCH,
        heavy_download_active=True,
        fast_interaction_active=True,
        interaction_mode='drag',
        now_ms=120.0,
    )

    assert policy.radius_cap == 2

    assert ctrl.should_admit(
        WorkClass.PREFETCH,
        {"key": "series-101:center-20", "distance": 2, "interaction_mode": "drag"},
        heavy_download_active=True,
        fast_interaction_active=True,
        now_ms=130.0,
    ) is True


def test_prefetch_deferred_under_ui_lag_returns_without_deadlock():
    ctrl = SystemLoadController()

    ctrl.record_ui_tick(now_ms=0.0)
    ctrl.record_ui_tick(now_ms=90.0, nominal_interval_ms=16.0)

    assert ctrl.should_admit(
        WorkClass.PREFETCH,
        {"key": "series-101:center-20", "distance": 1},
        heavy_download_active=False,
        fast_interaction_active=False,
        now_ms=90.0,
    ) is True

    result: dict[str, object] = {}

    def _call_second_prefetch() -> None:
        result["value"] = ctrl.should_admit(
            WorkClass.PREFETCH,
            {"key": "series-101:center-20", "distance": 2},
            heavy_download_active=False,
            fast_interaction_active=False,
            now_ms=120.0,
        )

    thread = threading.Thread(target=_call_second_prefetch, daemon=True)
    thread.start()
    thread.join(timeout=1.0)

    assert not thread.is_alive(), "prefetch defer path deadlocked under protected UI"
    assert result["value"] is False
    stats = ctrl.admission_stats()
    assert stats[WorkClass.PREFETCH.value]["admitted"] == 1
    assert stats[WorkClass.PREFETCH.value]["deferred"] == 1


def test_perf_metrics_reports_cancelled_task_ratio():
    from modules.viewer.fast.perf_metrics import PerfMetrics

    pm = PerfMetrics.get()
    pm.enable()
    try:
        pm.record_prefetch_submitted()
        pm.record_prefetch_submitted()
        pm.record_cancelled_task()
        snap = pm.snapshot()
        assert snap["cancelled_task_count"] == 1
        assert snap["cancelled_task_ratio"] == 0.5
    finally:
        pm.disable()
        pm.reset()


def test_admission_stats_track_admitted_deferred_and_dropped_outcomes():
    ctrl = SystemLoadController()

    assert ctrl.should_admit(
        WorkClass.PROGRESS_UPDATE,
        {"key": "series-101"},
        heavy_download_active=True,
        fast_interaction_active=False,
        now_ms=100.0,
    ) is True
    assert ctrl.should_admit(
        WorkClass.PROGRESS_UPDATE,
        {"key": "series-101"},
        heavy_download_active=True,
        fast_interaction_active=False,
        now_ms=150.0,
    ) is False
    assert ctrl.should_admit(
        WorkClass.PREFETCH,
        {"key": "series-101:center-20", "distance": 4},
        heavy_download_active=True,
        fast_interaction_active=True,
        now_ms=200.0,
    ) is False

    stats = ctrl.admission_stats()

    assert stats[WorkClass.PROGRESS_UPDATE.value]["admitted"] == 1
    assert stats[WorkClass.PROGRESS_UPDATE.value]["deferred"] == 1
    assert stats[WorkClass.PROGRESS_UPDATE.value]["dropped"] == 0
    assert stats[WorkClass.PREFETCH.value]["admitted"] == 0
    assert stats[WorkClass.PREFETCH.value]["deferred"] == 0
    assert stats[WorkClass.PREFETCH.value]["dropped"] == 1


def test_admission_stats_reset_clears_counters():
    ctrl = SystemLoadController()

    assert ctrl.should_admit(
        WorkClass.FINAL_RENDER,
        {"key": "viewer-1"},
        heavy_download_active=True,
        fast_interaction_active=True,
        now_ms=100.0,
    ) is True

    snapshot = ctrl.admission_stats(reset=True)

    assert snapshot[WorkClass.FINAL_RENDER.value]["admitted"] == 1
    assert ctrl.admission_stats() == {}


def test_work_class_classification_matches_block_model():
    ctrl = SystemLoadController()

    assert ctrl.classify_work_class(WorkClass.INTERACTION) is BlockId.BLOCK_2_VIEWER_HOT_PATH
    assert ctrl.classify_work_class(WorkClass.FINAL_RENDER) is BlockId.BLOCK_2_VIEWER_HOT_PATH
    assert ctrl.classify_work_class(WorkClass.THUMBNAIL_UI) is BlockId.BLOCK_1_DATA_SERVICES
    assert ctrl.classify_work_class(WorkClass.PROGRESS_UPDATE) is BlockId.BLOCK_1_DATA_SERVICES
    assert ctrl.classify_work_class(WorkClass.PROGRESSIVE_GROW) is BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION
    assert ctrl.classify_work_class(WorkClass.PREFETCH) is BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION


def test_block_admission_stats_aggregate_across_work_classes():
    ctrl = SystemLoadController()

    assert ctrl.should_admit(
        WorkClass.THUMBNAIL_UI,
        {"key": "thumb-series-101"},
        heavy_download_active=False,
        fast_interaction_active=False,
        now_ms=100.0,
    ) is True
    assert ctrl.should_admit(
        WorkClass.INTERACTION,
        {"key": "viewer-1"},
        heavy_download_active=True,
        fast_interaction_active=True,
        now_ms=120.0,
    ) is True
    assert ctrl.should_admit(
        WorkClass.PREFETCH,
        {"key": "series-101:center-20", "distance": 6},
        heavy_download_active=True,
        fast_interaction_active=True,
        now_ms=140.0,
    ) is False

    stats = ctrl.block_admission_stats()

    assert stats[BlockId.BLOCK_1_DATA_SERVICES.value]["admitted"] == 1
    assert stats[BlockId.BLOCK_2_VIEWER_HOT_PATH.value]["admitted"] == 1
    assert stats[BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION.value]["dropped"] == 1


def test_debug_snapshot_includes_block_and_work_class_stats():
    ctrl = SystemLoadController()

    assert ctrl.should_admit(
        WorkClass.PROGRESS_UPDATE,
        {"key": "series-101"},
        heavy_download_active=True,
        fast_interaction_active=False,
        now_ms=100.0,
    ) is True

    snap = ctrl.debug_snapshot(
        heavy_download_active=True,
        fast_interaction_active=False,
        now_ms=110.0,
    )

    assert snap["heavy_download_active"] is True
    assert "admission_by_work_class" in snap
    assert "admission_by_block" in snap
    assert snap["admission_by_work_class"][WorkClass.PROGRESS_UPDATE.value]["admitted"] == 1
    assert snap["admission_by_block"][BlockId.BLOCK_1_DATA_SERVICES.value]["admitted"] == 1
