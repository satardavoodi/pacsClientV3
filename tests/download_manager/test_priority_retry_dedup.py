import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules.download_manager.coordinator.series_intent_coordinator import SeriesIntentCoordinator
from modules.download_manager.core.enums import DownloadPriority, DownloadStatus
from modules.download_manager.core.models import DownloadResult, DownloadTask, PatientInfo, SeriesInfo, StudyMetadata
from modules.download_manager.state.state_store import DownloadStateStore


class _PoolBusy:
    def can_add_worker(self):
        return False


class _PoolFree:
    def can_add_worker(self):
        return True


class _RuleEngineStub:
    def evaluate_preemption(self, _task):
        return None


def _make_task(study_uid: str = "study-1") -> DownloadTask:
    return DownloadTask(
        study_uid=study_uid,
        patient_id="p1",
        patient_name="Patient One",
        study_date="2026-04-16",
        study_time="10:00:00",
        modality="CT",
        description="Test Study",
        series_list=[],
        priority=DownloadPriority.HIGH,
        output_dir=Path("."),
    )


def _make_task_with_series(study_uid: str = "study-preempt") -> DownloadTask:
    series = SeriesInfo(
        series_uid="series-1",
        series_number=1,
        series_description="Series 1",
        modality="CT",
        image_count=10,
    )
    return DownloadTask(
        study_uid=study_uid,
        patient_id="p1",
        patient_name="Patient One",
        study_date="2026-04-16",
        study_time="10:00:00",
        modality="CT",
        description="Test Study",
        series_list=[series],
        priority=DownloadPriority.HIGH,
        output_dir=Path("."),
    )


def test_priority_retry_deduplicates_same_study_chain():
    store = DownloadStateStore()
    task = _make_task()
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    deferred = []

    coordinator = SeriesIntentCoordinator(
        state_store=store,
        rule_engine=_RuleEngineStub(),
        worker_pool=_PoolBusy(),
        tasks_ref={task.study_uid: task},
        pause_downloads_for_preemption=lambda _uids: None,
        start_download_worker=lambda _uid: False,
        start_next_pending=lambda: None,
        refresh_table_order=lambda: None,
        check_auto_resume=lambda: None,
        defer_call=lambda _delay, cb: deferred.append(cb),
    )

    coordinator.schedule_priority_start_retry(task.study_uid)
    coordinator.schedule_priority_start_retry(task.study_uid)

    assert len(deferred) == 1


def test_priority_retry_guard_clears_after_state_changes():
    store = DownloadStateStore()
    task = _make_task()
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    deferred = []

    coordinator = SeriesIntentCoordinator(
        state_store=store,
        rule_engine=_RuleEngineStub(),
        worker_pool=_PoolBusy(),
        tasks_ref={task.study_uid: task},
        pause_downloads_for_preemption=lambda _uids: None,
        start_download_worker=lambda _uid: False,
        start_next_pending=lambda: None,
        refresh_table_order=lambda: None,
        check_auto_resume=lambda: None,
        defer_call=lambda _delay, cb: deferred.append(cb),
    )

    coordinator.schedule_priority_start_retry(task.study_uid)
    assert len(deferred) == 1

    first_callback = deferred.pop(0)
    store.update(task.study_uid, status=DownloadStatus.DOWNLOADING)
    first_callback()

    store.update(task.study_uid, status=DownloadStatus.PENDING)
    coordinator.schedule_priority_start_retry(task.study_uid)

    assert len(deferred) == 1


def test_priority_retry_guard_clears_after_successful_start():
    store = DownloadStateStore()
    task = _make_task()
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    starts = []

    coordinator = SeriesIntentCoordinator(
        state_store=store,
        rule_engine=_RuleEngineStub(),
        worker_pool=_PoolFree(),
        tasks_ref={task.study_uid: task},
        pause_downloads_for_preemption=lambda _uids: None,
        start_download_worker=lambda uid: starts.append(uid) or True,
        start_next_pending=lambda: None,
        refresh_table_order=lambda: None,
        check_auto_resume=lambda: None,
        defer_call=lambda _delay, _cb: None,
    )

    coordinator.schedule_priority_start_retry(task.study_uid)
    coordinator.schedule_priority_start_retry(task.study_uid)

    assert starts == [task.study_uid, task.study_uid]


def test_executor_keeps_auto_paused_state_for_preemption_result(tmp_path):
    from modules.download_manager.download.executor import DownloadExecutor
    from modules.download_manager.core.enums import ResumeAction

    task = _make_task_with_series("study-preempt")
    store = DownloadStateStore()
    store.create(task)

    metadata = StudyMetadata(
        study_uid=task.study_uid,
        patient_info=PatientInfo(patient_id=task.patient_id, patient_name=task.patient_name),
        study_date=task.study_date,
        study_description=task.description,
        series_list=task.series_list,
        thumbnails={},
    )

    class _Rules:
        validation_rules = SimpleNamespace(
            validate_study_structure=lambda _metadata: SimpleNamespace(allowed=True, reason="")
        )

        def can_add_download(self, _task):
            return SimpleNamespace(allowed=True, reason="")

        def should_resume_or_restart(self, *_args, **_kwargs):
            return SimpleNamespace(action=ResumeAction.RESUME, message="resume")

    class _Grpc:
        async def fetch_study_metadata(self, _study_uid):
            return metadata

    class _Db:
        async def initialize_study(self, *_args, **_kwargs):
            return None

        def get_download_progress(self, *_args, **_kwargs):
            return None

    class _PreemptedSeriesDownloader:
        def __init__(self, state_store, **_kwargs):
            self._state_store = state_store

        async def download_all_series(self, study_uid, **_kwargs):
            self._state_store.update(
                study_uid,
                status=DownloadStatus.PAUSED,
                is_auto_paused=True,
                error_message="Paused for higher priority download (preemption)",
            )
            return DownloadResult(
                success=False,
                study_uid=study_uid,
                error_message="Paused for higher priority download (preemption)",
            )

    executor = DownloadExecutor(
        state_store=store,
        rule_engine=_Rules(),
        grpc_client=_Grpc(),
        database_manager=_Db(),
        base_output_dir=tmp_path,
    )

    completions = []
    with patch("modules.download_manager.download.executor.SeriesDownloader", _PreemptedSeriesDownloader):
        result = asyncio.run(
            executor.execute_download(
                task=task,
                completion_callback=lambda study_uid, success: completions.append((study_uid, success)),
            )
        )

    state = store.get(task.study_uid)
    assert result.success is False
    assert state is not None
    assert state.status == DownloadStatus.PAUSED
    assert state.is_auto_paused is True
    assert "higher priority download" in str(state.error_message or "").lower()
    assert completions == [(task.study_uid, False)]


def test_worker_completed_ignores_auto_paused_failure(monkeypatch):
    from modules.download_manager.ui.widget import _dm_workers as _dm_workers_mod

    store = DownloadStateStore()
    task = _make_task_with_series("study-worker-preempt")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PAUSED, is_auto_paused=True)

    scheduled = []
    calls = {"refresh": 0, "resume": 0, "start_next": 0}
    monkeypatch.setattr(_dm_workers_mod.QTimer, "singleShot", lambda delay, fn: scheduled.append(delay))

    dummy = SimpleNamespace(
        state_store=store,
        _refresh_table_order=lambda: calls.__setitem__("refresh", calls["refresh"] + 1),
        _check_auto_resume=lambda: calls.__setitem__("resume", calls["resume"] + 1),
        _start_next_pending=lambda: calls.__setitem__("start_next", calls["start_next"] + 1),
        log_message=lambda *_args, **_kwargs: None,
        _tasks={},
        download_completed=SimpleNamespace(emit=lambda *_args, **_kwargs: None),
    )

    _dm_workers_mod._DMWorkersMixin._on_worker_completed(dummy, task.study_uid, False)

    state = store.get(task.study_uid)
    assert state is not None
    assert state.status == DownloadStatus.PAUSED
    assert state.is_auto_paused is True
    assert calls["refresh"] == 1
    assert calls["resume"] == 1
    assert scheduled == [0]
