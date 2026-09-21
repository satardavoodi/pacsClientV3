"""OPT-04: an exhausted response is not evidence of all expected local files.

Synthetic transport only: no clinical database, token store, or PACS connection.
This is a file-count gate, not a SOP-manifest or pixel-validity validator.
"""
import asyncio
import base64
import gzip
import threading
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage

from modules.download_manager.core.models import SeriesInfo
from modules.download_manager.network import socket_client as transport


@pytest.fixture
def payload():
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = "1.2.826.0.1.3680043.10.999.1"
    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.Rows = ds.Columns = 1
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = b"\x01\0"
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    stream = BytesIO()
    ds.save_as(stream, write_like_original=False)
    return stream.getvalue()


@pytest.fixture
def client(monkeypatch):
    client = transport.SocketDicomClient(
        host="127.0.0.1", token_manager=object(),
        health_monitor=SimpleNamespace(should_test_connection=lambda: False),
    )
    client.connected = True
    client._adaptive_batch_size = client._batch_size_cap = 10
    client._inter_batch_pause_s = 0
    monkeypatch.setattr(client, "connect", Mock(side_effect=AssertionError("No network")))
    monkeypatch.setattr(client, "_emit_resource_probe", lambda **kwargs: None)
    return client


def instance(number, payload, compressed=False):
    return {
        "instance_number": number,
        "dicom_data": base64.b64encode(gzip.compress(payload) if compressed else payload).decode("ascii"),
        "is_compressed": compressed,
    }


def run(client, directory, instances, expected=2, progress=None):
    client._download_batch_with_retry = AsyncMock(return_value={
        "status": "success", "data": {"instances": instances, "has_more": False},
    })
    info = SeriesInfo("1.2.826.0.1.3680043.10.999.2", 1, "Synthetic", "CT", expected)
    return asyncio.run(client.download_series("1.2.826.0.1.3680043.10.999.3", info, directory, progress))


@pytest.mark.parametrize("failure", ["early_end", "empty", "missing_payload", "base64", "gzip", "short_file", "duplicate"])
def test_incomplete_response_cannot_report_success(client, tmp_path, payload, failure):
    rows = [instance(1, payload)]
    if failure == "empty":
        rows = []
    elif failure == "missing_payload":
        rows.append({"instance_number": 2})
    elif failure == "base64":
        rows.append({"instance_number": 2, "dicom_data": "a"})
    elif failure == "gzip":
        rows.append({**instance(2, payload), "is_compressed": True})
    elif failure == "short_file":
        rows.append(instance(2, b"short"))
    elif failure == "duplicate":
        rows.append(instance(1, payload))
    result = run(client, tmp_path, rows)
    assert not result.success
    assert "Incomplete series" in result.error_message
    assert "expected=2" in result.error_message


def test_duplicate_does_not_inflate_progress(client, tmp_path, payload):
    progress = Mock()
    result = run(client, tmp_path, [instance(1, payload), instance(1, payload), instance(2, payload)], progress=progress)
    assert result.success
    assert (result.downloaded, result.skipped) == (2, 0)
    assert result.completion_rate == 100
    assert all(call.args[2] <= 100 and call.args[3] <= 2 for call in progress.call_args_list)


@pytest.mark.parametrize("compressed", [False, True])
def test_complete_payload_preserves_bytes(client, tmp_path, payload, compressed):
    result = run(client, tmp_path, [instance(1, payload, compressed), instance(2, payload, compressed)])
    assert result.success
    assert result.error_message is None
    assert result.downloaded == 2
    assert all(path.read_bytes() == payload for path in tmp_path.glob("*.dcm"))
    assert not list(tmp_path.glob("*.part"))


def test_retry_keeps_file_and_fetches_missing_instance(client, tmp_path, payload):
    first = run(client, tmp_path, [instance(1, payload)])
    assert not first.success
    preserved = tmp_path / "Instance_0001.dcm"
    before = preserved.stat().st_mtime_ns
    second = run(client, tmp_path, [instance(1, payload), instance(2, payload)])
    assert second.success
    assert (second.downloaded, second.skipped) == (1, 1)
    assert preserved.stat().st_mtime_ns == before
    assert preserved.read_bytes() == payload


def test_write_error_cannot_report_success(client, tmp_path, payload, monkeypatch):
    replace = transport.os.replace

    def fail_second(source, target):
        if target.name == "Instance_0002.dcm":
            raise OSError("Synthetic write failure")
        replace(source, target)

    monkeypatch.setattr(transport.os, "replace", fail_second)
    result = run(client, tmp_path, [instance(1, payload), instance(2, payload)])
    assert not result.success
    assert (tmp_path / "Instance_0001.dcm").read_bytes() == payload
    assert not list(tmp_path.glob("*.part"))


def test_final_scan_failure_cannot_report_success(client, tmp_path, payload, monkeypatch):
    monkeypatch.setattr(client, "_scan_existing_files", Mock(return_value=[]))
    result = run(client, tmp_path, [instance(1, payload), instance(2, payload)])
    assert not result.success


def test_part_and_short_resume_files_do_not_prove_completion(client, tmp_path, payload):
    (tmp_path / "Instance_0001.dcm").write_bytes(b"short")
    (tmp_path / "Instance_0002.dcm.part").write_bytes(payload)
    assert not run(client, tmp_path, []).success


def test_preexisting_complete_series_keeps_resume_semantics(client, tmp_path, payload):
    for number in (1, 2):
        (tmp_path / f"Instance_{number:04d}.dcm").write_bytes(payload)
    client._adaptive_batch_size = client._batch_size_cap = 1
    result = run(client, tmp_path, [])
    assert result.success and result.downloaded == 0 and result.skipped == 2
    client._download_batch_with_retry.assert_not_awaited()


def test_cancel_remains_distinct_from_incomplete(client, tmp_path):
    client._cancelled = True
    result = run(client, tmp_path, [])
    assert not result.success
    assert "cancelled" in result.error_message.lower()
    client._download_batch_with_retry.assert_not_awaited()


def test_one_final_scan_runs_off_event_loop_thread(client, tmp_path, payload, monkeypatch):
    scan = client._scan_existing_files
    owner = threading.get_ident()
    threads = []

    def record(directory):
        threads.append(threading.get_ident())
        return scan(directory)

    monkeypatch.setattr(client, "_scan_existing_files", record)
    assert run(client, tmp_path, [instance(1, payload), instance(2, payload)]).success
    assert len(threads) == 2  # Existing initial resume scan plus one final scan.
    assert threads[0] == owner and threads[1] != owner


def test_cancel_during_final_scan_wins_over_complete_count(client, tmp_path, payload, monkeypatch):
    scan = client._scan_existing_files
    calls = 0

    def cancel_on_final(directory):
        nonlocal calls
        calls += 1
        if calls == 2:
            client._cancelled = True
        return scan(directory)

    monkeypatch.setattr(client, "_scan_existing_files", cancel_on_final)
    result = run(client, tmp_path, [instance(1, payload), instance(2, payload)])
    assert not result.success and "cancelled" in result.error_message.lower()


def test_zero_count_metadata_contract_is_not_reinterpreted(client, tmp_path):
    result = run(client, tmp_path, [], expected=0)
    assert result.success and result.total == 0
    client._download_batch_with_retry.assert_not_awaited()


@pytest.mark.parametrize("collision", [False, True])
@pytest.mark.parametrize("recover", [False, True])
def test_study_retry_preserves_series_folder_and_failure_state(client, tmp_path, payload, monkeypatch, collision, recover):
    from modules.download_manager.download import series_downloader as coordinator
    from modules.download_manager.core import series_folder

    monkeypatch.setattr(series_folder, "_DEDUP_ENABLED", True)
    state = SimpleNamespace(patient_name="Synthetic", completed_series=[], failed_series=[], skipped_series=[])

    def update(_uid, **values):
        for key, value in values.items():
            setattr(state, key, value)

    store = SimpleNamespace(get=lambda _uid: state, update=update, get_by_status=lambda _status: [])
    rules = SimpleNamespace(
        should_interrupt_for_priority=lambda *_: False,
        resume_rules=SimpleNamespace(check_series_complete=lambda *_: (False, 0)),
    )
    monkeypatch.setattr(coordinator, "get_socket_token_manager", lambda: SimpleNamespace(has_token=lambda: True))
    monkeypatch.setattr(coordinator, "SocketDicomClient", lambda **_: client)
    monkeypatch.setattr(coordinator, "MAX_SERIES_RETRIES", 1)
    monkeypatch.setattr(coordinator, "SERIES_RETRY_BASE_DELAY", 0)
    monkeypatch.setattr(client, "ensure_authenticated", lambda: True)
    monkeypatch.setattr(client, "disconnect", lambda: None)
    requests = 0

    async def batch(*_args):
        nonlocal requests
        requests += 1
        complete = requests == 1 or (requests == 3 and recover)
        rows = [instance(1, payload), instance(2, payload)] if complete else [instance(1, payload)]
        return {"status": "success", "data": {"instances": rows, "has_more": False}}

    client._download_batch_with_retry = batch
    real_download = client.download_series
    paths = []

    async def record(**kwargs):
        paths.append((kwargs["series_info"].series_uid, kwargs["output_dir"]))
        return await real_download(**kwargs)

    monkeypatch.setattr(client, "download_series", record)
    downloader = coordinator.SeriesDownloader(store, rules, tmp_path, database_manager=None)
    monkeypatch.setattr(downloader, "_update_progress", lambda *_: None)
    series = [
        SeriesInfo("1.2.826.0.1.3680043.10.999.2", 1, "Synthetic", "CT", 2),
        SeriesInfo("1.2.826.0.1.3680043.10.999.4", 1 if collision else 2, "Synthetic", "CT", 2),
    ]
    result = asyncio.run(downloader.download_all_series("1.2.826.0.1.3680043.10.999.3", series, "synthetic"))
    assert len(paths) == 3
    assert paths[0][1] != paths[1][1]
    assert paths[2] == paths[1], "Retry must reuse the same UID-scoped folder, not the bare series number"
    assert result.success is recover
    assert result.failed_series == (0 if recover else 1)
    assert len(state.completed_series) == (2 if recover else 1)
    assert len(list(paths[1][1].glob("*.dcm"))) == (2 if recover else 1)
