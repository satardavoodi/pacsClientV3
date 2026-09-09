"""Regression guards for study-level Download Manager progress.

The queue row and the right-side ``Overall Progress`` bar represent all images
in one study.  Per-series progress may restart at zero, but the study-level
counter must remain monotonic and must distinguish series by SeriesInstanceUID.
"""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from modules.download_manager.ui.widget._dm_queue import _DMQueueMixin


_REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (_REPO_ROOT / relative_path).read_text(encoding="utf-8", errors="ignore")


class _StateStore:
    def __init__(self) -> None:
        self.state = SimpleNamespace(completed_series=[], skipped_series=[])

    def get(self, _study_uid: str):
        return self.state


def _series(uid: str, number: str, count: int):
    return SimpleNamespace(
        series_uid=uid,
        series_number=number,
        image_count=count,
    )


def _queue(series_list):
    queue = _DMQueueMixin()
    task = SimpleNamespace(
        series_list=list(series_list),
        total_image_count=sum(item.image_count for item in series_list),
    )
    queue._tasks = {"study": task}
    queue._series_image_count_cache = {}
    queue._overall_progress_accumulators = {}
    queue.state_store = _StateStore()
    return queue


def test_overall_progress_does_not_reset_when_a_series_terminal_state_is_late():
    queue = _queue([_series("uid-a", "1", 100), _series("uid-b", "2", 200)])

    assert queue._calculate_overall_progress("study", "1", 100, 100) == pytest.approx(
        (100, 300, 100 / 3)
    )

    # The main-process completed_series update can arrive late or be dropped at
    # the subprocess boundary.  Starting series 2 must still continue from 100.
    assert queue._calculate_overall_progress("study", "2", 1, 200) == pytest.approx(
        (101, 300, 101 / 3)
    )


def test_duplicate_series_numbers_are_accumulated_by_uid():
    queue = _queue([_series("uid-a", "7", 10), _series("uid-b", "7", 20)])

    assert queue._calculate_overall_progress(
        "study", "7", 10, 10, series_uid="uid-a"
    )[0] == 10
    assert queue._calculate_overall_progress(
        "study", "7", 1, 20, series_uid="uid-b"
    ) == pytest.approx((11, 30, 110 / 3))


def test_retry_or_out_of_order_progress_never_moves_overall_backwards():
    queue = _queue([_series("uid-a", "1", 100), _series("uid-b", "2", 100)])

    first = queue._calculate_overall_progress(
        "study", "1", 80, 100, series_uid="uid-a"
    )
    stale = queue._calculate_overall_progress(
        "study", "1", 20, 100, series_uid="uid-a"
    )

    assert first == pytest.approx((80, 200, 40.0))
    assert stale == first


def test_steady_state_updates_do_not_resum_series_totals():
    items = [_series(f"uid-{index}", str(index), 100) for index in range(500)]

    class _CountingTask:
        series_list = items
        total_reads = 0

        @property
        def total_image_count(self):
            self.total_reads += 1
            return sum(item.image_count for item in self.series_list)

    queue = _queue(items)
    task = _CountingTask()
    queue._tasks["study"] = task

    for downloaded in range(1, 101):
        queue._calculate_overall_progress(
            "study", "1", downloaded, 100, series_uid="uid-1"
        )

    assert task.total_reads == 1


def test_accumulator_reset_starts_a_new_download_generation_from_zero():
    queue = _queue([_series("uid-a", "1", 100), _series("uid-b", "2", 100)])

    queue._calculate_overall_progress("study", "1", 100, 100, series_uid="uid-a")
    queue._overall_progress_accumulators.pop("study", None)

    assert queue._calculate_overall_progress(
        "study", "1", 1, 100, series_uid="uid-a"
    ) == pytest.approx((1, 200, 0.5))


def test_authoritative_manifest_replaces_a_series_local_fallback_total():
    queue = _queue([_series("uid-a", "1", 0), _series("uid-b", "2", 0)])

    # A partial queue payload can have unknown image counts.  The legacy
    # fallback therefore starts with the first series total.
    assert queue._calculate_overall_progress(
        "study", "1", 25, 100, series_uid="uid-a"
    ) == pytest.approx((25, 100, 25.0))

    # The download subprocess fetches the authoritative server manifest before
    # downloading.  Its one-time total must replace the fallback without losing
    # progress already observed by the UI.
    assert queue._calculate_overall_progress(
        "study", "", 0, 0, overall_total_hint=300
    ) == pytest.approx((25, 300, 25 / 3))
    assert queue._calculate_overall_progress(
        "study", "2", 1, 200, series_uid="uid-b"
    ) == pytest.approx((26, 300, 26 / 3))


def test_progress_ipc_preserves_series_uid_and_terminal_delivery():
    socket_client = _read("modules/download_manager/network/socket_client.py")
    process_entry = _read("modules/download_manager/workers/download_process_entry.py")
    process_worker = _read("modules/download_manager/workers/download_process_worker.py")
    ui_worker = _read("modules/download_manager/ui/widget/_dm_workers.py")

    assert "series_uid=series_uid" in socket_client
    assert '"series_uid": str(metadata.get("series_uid") or "")' in process_entry
    assert "event_type == \"study_manifest\"" in process_entry
    assert "result_queue.put(message, timeout=1.0)" in process_entry
    assert "progress = Signal(str, str, str, str, float, int, int)" in process_worker
    assert "_series_identity = _raw_uid or _raw_series" in process_worker
    assert "series_uid: str," in ui_worker
    assert "series_uid=series_uid or None" in ui_worker


def test_authoritative_study_manifest_crosses_the_existing_progress_channel():
    downloader = _read("modules/download_manager/download/series_downloader.py")
    ui_worker = _read("modules/download_manager/ui/widget/_dm_workers.py")

    assert "'study_manifest'" in downloader
    assert "if event_type == 'study_manifest':" in ui_worker
    manifest_branch = ui_worker.split("if event_type == 'study_manifest':", 1)[1].split(
        "if event_type == 'series_accounted':", 1
    )[0]
    assert "overall_total_hint=total" in manifest_branch
    assert "_study_progress_args" in manifest_branch
    assert "_series_progress_args" not in manifest_branch


def test_complete_on_disk_series_has_one_aggregate_only_accounting_event():
    downloader = _read("modules/download_manager/download/series_downloader.py")
    ui_worker = _read("modules/download_manager/ui/widget/_dm_workers.py")

    assert "'series_accounted'" in downloader
    assert "series_uid=series_info.series_uid" in downloader
    assert "if event_type == 'series_accounted':" in ui_worker
    accounted_branch = ui_worker.split("if event_type == 'series_accounted':", 1)[1].split(
        "# Log series changes", 1
    )[0]
    assert "_study_progress_args" in accounted_branch
    assert "_series_progress_args" not in accounted_branch
