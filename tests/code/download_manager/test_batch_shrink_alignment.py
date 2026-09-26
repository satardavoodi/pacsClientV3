"""Exercise real download paging against a synthetic index-paged PACS."""
import asyncio
import base64
from types import SimpleNamespace

import pytest

from modules.download_manager.network import socket_client as sc
from modules.download_manager.core.models import SeriesInfo


@pytest.mark.parametrize("initial_size", [3, 5, 7, 10])
@pytest.mark.parametrize("reason", ["payload", "error"])
@pytest.mark.parametrize("resume", [False, True])
def test_shrinking_preserves_exact_next_server_offset(tmp_path, monkeypatch, initial_size, reason, resume):
    client = sc.SocketDicomClient.__new__(sc.SocketDicomClient)
    client.connected = True
    client._adaptive_batch_size = initial_size
    client._batch_size_cap = initial_size
    client._inter_batch_pause_s = 0
    client.health_monitor = SimpleNamespace(should_test_connection=lambda: False)
    monkeypatch.setattr(client, "_emit_resource_probe", lambda **kwargs: None)
    monkeypatch.setattr(client, "is_cancelled", lambda: False)
    monkeypatch.setattr(sc, "_normalize_received_dicom_bytes", lambda data: data)
    monkeypatch.setattr(sc, "_BATCH_BYTES_SOFT_CAP", 1 if reason == "payload" else 10**9)
    monkeypatch.setattr(sc.SocketDicomClient, "_global_adaptive_batch_size", initial_size)
    total = 27
    existing = initial_size if resume else 0
    for n in range(1, existing + 1):
        (tmp_path / f"Instance_{n:04d}.dcm").write_bytes(b"retained" * 32)
    delivered = []
    rejected = False

    async def batch(study_uid, series_uid, batch_start, batch_size):
        nonlocal rejected
        # Match the deployed wire contract: server offset = index * size.
        server_start = (batch_start // batch_size) * batch_size
        if reason == "error" and batch_start == initial_size and not rejected:
            rejected = True
            return {"status": "error", "error": "Response too large"}
        numbers = list(range(server_start + 1, min(server_start + batch_size, total) + 1))
        delivered.extend(numbers)
        return {"status": "success", "data": {
            "instances": [{"instance_number": n, "dicom_data": base64.b64encode(b"synthetic" * 32).decode()} for n in numbers],
            "has_more": server_start + batch_size < total,
        }}

    monkeypatch.setattr(client, "_download_batch_with_retry", batch)
    series = SeriesInfo("1.2.3.4", 1, "Synthetic", "MR", total)
    result = asyncio.run(client.download_series("1.2.3", series, tmp_path))
    assert result.success
    assert delivered == list(range(existing + 1, total + 1)), "Paging must neither repeat nor omit an instance"
    assert len(list(tmp_path.glob("*.dcm"))) == total
    for n in range(1, existing + 1):
        assert (tmp_path / f"Instance_{n:04d}.dcm").read_bytes() == b"retained" * 32
