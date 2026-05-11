from __future__ import annotations

from dataclasses import dataclass, field

from modules.download_manager.core.enums import DownloadPriority, DownloadStatus
from modules.download_manager.core.models import DownloadTask, SeriesInfo
from modules.download_manager.state.state_store import DownloadStateStore


@dataclass
class _ObserverSpy:
    events: list = field(default_factory=list)

    def on_state_change(self, event, study_uid, state, *args):
        self.events.append((event, study_uid, args))


def _make_task(study_uid: str = "1.2.3.4") -> DownloadTask:
    series = SeriesInfo(
        series_uid="9.8.7.6",
        series_number=1,
        series_description="S1",
        modality="CT",
        image_count=10,
    )
    return DownloadTask(
        study_uid=study_uid,
        patient_id="P1",
        patient_name="Patient One",
        study_date="20260506",
        modality="CT",
        description="Study",
        series_list=[series],
        priority=DownloadPriority.NORMAL,
    )


def _events_of(spy: _ObserverSpy, name: str):
    return [e for e in spy.events if e[0] == name]


def test_update_batch_emits_single_updated_batch_notification():
    store = DownloadStateStore()
    spy = _ObserverSpy()
    store.register_observer(spy)

    task = _make_task("1.2.3.10")
    store.create(task)

    store.update_batch(
        task.study_uid,
        status=DownloadStatus.PENDING,
        is_auto_paused=False,
        error_message=None,
    )

    updated_batch = _events_of(spy, "updated_batch")
    updated = _events_of(spy, "updated")

    assert len(updated_batch) == 1
    assert len(updated) == 0

    args = updated_batch[0][2]
    assert len(args) == 2
    changes, old_values = args
    assert set(changes.keys()) == {"status", "is_auto_paused", "error_message"}
    assert "status" in old_values


def test_update_keeps_per_field_updated_notifications():
    store = DownloadStateStore()
    spy = _ObserverSpy()
    store.register_observer(spy)

    task = _make_task("1.2.3.11")
    store.create(task)

    store.update(
        task.study_uid,
        status=DownloadStatus.PENDING,
        is_auto_paused=False,
        error_message=None,
    )

    updated = _events_of(spy, "updated")
    updated_batch = _events_of(spy, "updated_batch")

    # update() should continue firing one event per changed field.
    assert len(updated) == 3
    assert len(updated_batch) == 0


def test_update_batch_on_terminal_state_ignores_status_change():
    store = DownloadStateStore()
    spy = _ObserverSpy()
    store.register_observer(spy)

    task = _make_task("1.2.3.12")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.COMPLETED)

    before_status = store.get(task.study_uid).status

    store.update_batch(
        task.study_uid,
        status=DownloadStatus.PENDING,
        error_message="x",
    )

    state = store.get(task.study_uid)
    assert before_status == DownloadStatus.COMPLETED
    assert state.status == DownloadStatus.COMPLETED
    assert state.error_message == "x"

    updated_batch = _events_of(spy, "updated_batch")
    assert len(updated_batch) >= 1
    changes, _old = updated_batch[-1][2]
    assert "status" not in changes
    assert changes.get("error_message") == "x"
