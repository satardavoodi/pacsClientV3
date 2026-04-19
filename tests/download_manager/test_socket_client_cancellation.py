import asyncio
from pathlib import Path
from types import SimpleNamespace

from modules.download_manager.core.enums import DownloadPriority, DownloadStatus
from modules.download_manager.core.models import DownloadTask, SeriesInfo
from modules.download_manager.download.series_downloader import SeriesDownloader
from modules.download_manager.network.socket_client import SocketDicomClient
from modules.download_manager.state.state_store import DownloadStateStore


def _make_task(study_uid: str = "study-cancel") -> DownloadTask:
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
        study_date="2026-04-18",
        study_time="10:00:00",
        modality="CT",
        description="Cancellation Test",
        series_list=[series],
        priority=DownloadPriority.HIGH,
        output_dir=Path("."),
    )


def test_connect_with_retry_stops_when_cancelled_during_backoff(monkeypatch):
    cancel_state = {"value": False}
    client = SocketDicomClient(cancel_check=lambda: cancel_state["value"])

    attempts = []

    def _fake_connect():
        attempts.append("connect")
        return False

    def _fake_sleep(_delay, _interval=0.1):
        cancel_state["value"] = True
        return False

    monkeypatch.setattr(client, "connect", _fake_connect)
    monkeypatch.setattr(client, "_sleep_with_cancel", _fake_sleep)

    assert client.connect_with_retry(max_retries=5, retry_delay=1.0) is False
    assert len(attempts) == 1


def test_send_request_stops_retry_when_cancelled_during_backoff(monkeypatch):
    client = SocketDicomClient(cancel_check=lambda: False)
    calls = []

    monkeypatch.setattr(client, "_send_request_once", lambda *args, **kwargs: calls.append("once") or None)
    monkeypatch.setattr(client, "_sleep_with_cancel", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(client, "disconnect", lambda: calls.append("disconnect"))
    monkeypatch.setattr(client, "connect", lambda: calls.append("connect") or True)
    client.connected = True

    assert client.send_request("GetSeriesImages", {"series_uid": "s1"}) is None
    assert calls == ["once"]


def test_series_downloader_reconnect_cancel_returns_preempted_result(monkeypatch, tmp_path):
    task = _make_task()
    store = DownloadStateStore()
    store.create(task)

    class _Rules:
        resume_rules = SimpleNamespace(check_series_complete=lambda *_args, **_kwargs: (False, 0))

        def should_interrupt_for_priority(self, *_args, **_kwargs):
            return False

    class _TokenManager:
        def has_token(self):
            return True

    class _CancelledSocketClient:
        def __init__(self, cancel_check=None):
            self._cancel_check = cancel_check
            self.connected = False

        def ensure_authenticated(self):
            return True

        def connect_with_retry(self, *args, **kwargs):
            return False

        def is_cancelled(self):
            return True

        def disconnect(self):
            self.connected = False

    monkeypatch.setattr(
        "modules.download_manager.download.series_downloader.get_socket_token_manager",
        lambda: _TokenManager(),
    )
    monkeypatch.setattr(
        "modules.download_manager.download.series_downloader.SocketDicomClient",
        _CancelledSocketClient,
    )

    downloader = SeriesDownloader(
        state_store=store,
        rule_engine=_Rules(),
        base_output_dir=tmp_path,
        cancel_check=lambda: True,
    )

    result = asyncio.run(
        downloader.download_all_series(
            study_uid=task.study_uid,
            series_list=task.series_list,
            patient_id=task.patient_id,
        )
    )

    state = store.get(task.study_uid)
    assert result.success is False
    assert "preemption" in (result.error_message or "").lower()
    assert state is not None
    assert state.status == DownloadStatus.PAUSED
    assert state.is_auto_paused is True