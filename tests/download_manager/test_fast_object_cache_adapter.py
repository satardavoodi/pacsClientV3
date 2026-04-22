from __future__ import annotations

from pathlib import Path

from modules.download_manager.core.enums import DownloadPriority, DownloadStatus
from modules.download_manager.core.models import DownloadTask, SeriesInfo
from modules.download_manager.state.state_store import DownloadStateStore
from modules.download_manager.ui.widget._dm_priority import _DMPriorityMixin


class _ObjectCacheAdapter(_DMPriorityMixin):
    pass


class _IntentStub:
    def __init__(self):
        self.calls = []

    def request_critical_series(self, study_uid: str, series_number: str) -> bool:
        self.calls.append((study_uid, series_number))
        return True


def _make_adapter(tmp_path: Path):
    series = SeriesInfo(
        series_uid="series-uid-1",
        series_number=7,
        series_description="CT",
        modality="CT",
        image_count=100,
    )
    task = DownloadTask(
        study_uid="study-uid-1",
        patient_id="p1",
        patient_name="Patient One",
        study_date="2026-04-21",
        modality="CT",
        description="Study",
        series_list=[series],
        priority=DownloadPriority.HIGH,
    )
    store = DownloadStateStore()
    store.create(task)

    adapter = _ObjectCacheAdapter()
    adapter.base_output_dir = tmp_path
    adapter._tasks = {task.study_uid: task}
    adapter.state_store = store
    adapter.intent_coordinator = _IntentStub()
    adapter.retry_calls = []
    adapter._on_series_retry = lambda study_uid, series_number, series_uid=None: adapter.retry_calls.append(
        (study_uid, series_number, series_uid)
    )
    return adapter, task, series


def test_fast_object_cache_reports_local_instance_file(tmp_path):
    adapter, task, series = _make_adapter(tmp_path)
    series_dir = tmp_path / task.study_uid / str(series.series_number)
    series_dir.mkdir(parents=True)
    (series_dir / "Instance_0081.dcm").write_bytes(b"DICM")

    assert adapter.has_object(series.series_uid, 80) is True
    assert adapter.has_object(series.series_uid, 79) is False


def test_fast_object_request_promotes_missing_series_and_starts_retry(tmp_path):
    adapter, task, series = _make_adapter(tmp_path)

    ok = adapter.request_object(0, series.series_uid, 80)

    assert ok is True
    assert adapter.intent_coordinator.calls == [(task.study_uid, str(series.series_number))]
    assert adapter.retry_calls == [(task.study_uid, str(series.series_number), series.series_uid)]


def test_fast_object_request_returns_true_without_retry_when_file_exists(tmp_path):
    adapter, task, series = _make_adapter(tmp_path)
    series_dir = tmp_path / task.study_uid / str(series.series_number)
    series_dir.mkdir(parents=True)
    (series_dir / "Instance_0081.dcm").write_bytes(b"DICM")

    ok = adapter.request_object(0, series.series_uid, 80)

    assert ok is True
    assert adapter.intent_coordinator.calls == []
    assert adapter.retry_calls == []


def test_fast_object_request_debounces_repeated_drag_requests(tmp_path):
    adapter, task, series = _make_adapter(tmp_path)

    first = adapter.request_object(0, series.series_uid, 80)
    second = adapter.request_object(0, series.series_uid, 81)

    assert first is True
    assert second is False
    assert adapter.intent_coordinator.calls == [(task.study_uid, str(series.series_number))]
    assert len(adapter.retry_calls) == 1


def test_fast_object_request_does_not_retry_active_same_series(tmp_path):
    adapter, task, series = _make_adapter(tmp_path)
    adapter.state_store.update(
        task.study_uid,
        status=DownloadStatus.DOWNLOADING,
        current_series_number=str(series.series_number),
    )

    ok = adapter.request_object(0, series.series_uid, 80)

    assert ok is True
    assert adapter.intent_coordinator.calls == [(task.study_uid, str(series.series_number))]
    assert adapter.retry_calls == []
