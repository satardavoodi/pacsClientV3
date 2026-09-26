"""Behavioral wire-size, identity and resume contracts for both transfer modes."""
import asyncio
import base64
from types import SimpleNamespace

import pytest

from modules.download_manager.core.models import SeriesInfo
from modules.download_manager.network import socket_client as sc
from modules.network import socket_config


@pytest.fixture
def setup_client(monkeypatch):
    config = SimpleNamespace(poor=False, hosts=[])
    def resolve(host=None):
        config.hosts.append(host)
        return config.poor
    monkeypatch.setattr(socket_config, "get_socket_config", lambda: SimpleNamespace(is_poor_connectivity_enabled=resolve))
    monkeypatch.setattr(sc, "_normalize_received_dicom_bytes", lambda data: data)
    monkeypatch.setattr(sc.SocketDicomClient, "_global_adaptive_batch_size", 10)
    def make():
        c = sc.SocketDicomClient(host="download.example", port=50052)
        c.connected = True
        c._inter_batch_pause_s = 0
        c._post_request_yield_s = 0
        c._batch_size_cap = 40
        c.health_monitor = SimpleNamespace(should_test_connection=lambda: False)
        c._emit_resource_probe = lambda **kwargs: None
        return c
    return config, make


def run_transfer(client, directory, *, total=101, modality="MR", payload_size=256, fail_at=None, oversized_above=None):
    calls, delivered, progress = [], [], []
    blob = base64.b64encode(b"x" * payload_size).decode()
    async def batch(study, series, start, size):
        calls.append((start, size))
        if oversized_above is not None and size > oversized_above:
            return {"status": "error", "error": "Response too large"}
        if fail_at is not None and start >= fail_at:
            return {"status": "error", "error": "Synthetic connection loss"}
        offset = (start // size) * size
        numbers = list(range(offset + 1, min(offset + size, total) + 1))
        delivered.extend(numbers)
        return {"status": "success", "data": {
            "instances": [{"instance_number": n, "dicom_data": blob} for n in numbers],
            "has_more": offset + size < total,
        }}
    client._download_batch_with_retry = batch
    info = SeriesInfo("1.2.3.4", 1, "Synthetic", modality, total)
    result = asyncio.run(client.download_series("1.2.3", info, directory, lambda *a, **kw: progress.append(a[3])))
    return result, calls, delivered, progress


def test_poor_mode_pins_one_and_resolves_actual_host(setup_client, tmp_path):
    cfg, make = setup_client
    cfg.poor = True
    result, calls, delivered, _ = run_transfer(make(), tmp_path, total=17)
    assert result.success
    assert [size for _, size in calls] == [1] * 17
    assert delivered == list(range(1, 18))
    assert cfg.hosts == ["download.example"]


def test_normal_small_images_grow_without_repeating_or_skipping(setup_client, tmp_path):
    _, make = setup_client
    result, calls, delivered, progress = run_transfer(make(), tmp_path)
    assert result.success
    assert max(size for _, size in calls) == 40
    assert len(calls) < 11
    assert all(start % size == 0 for start, size in calls)
    assert delivered == list(range(1, 102))
    assert progress == list(range(1, 102))


def test_observed_byte_budget_limits_larger_images(setup_client, tmp_path):
    _, make = setup_client
    result, calls, delivered, _ = run_transfer(make(), tmp_path, total=35, payload_size=1024 * 1024)
    assert result.success
    # 1 MiB DICOM becomes about 1.33 MiB Base64; an 8 MiB budget fits at most five.
    assert max(size for _, size in calls[1:]) <= 5
    assert delivered == list(range(1, 36))


@pytest.mark.parametrize("modality", ["DX", "MG", "XA"])
def test_large_frame_modalities_remain_single(setup_client, tmp_path, modality):
    _, make = setup_client
    result, calls, _, _ = run_transfer(make(), tmp_path, modality=modality, total=12)
    assert result.success and all(size == 1 for _, size in calls)


def test_poor_disconnect_retains_files_and_resumes_at_missing_image(setup_client, tmp_path):
    cfg, make = setup_client
    cfg.poor = True
    result, _, _, _ = run_transfer(make(), tmp_path, total=19, fail_at=7)
    assert not result.success
    retained = {p.name: p.read_bytes() for p in tmp_path.glob("*.dcm")}
    assert len(retained) == 7
    result, calls, delivered, _ = run_transfer(make(), tmp_path, total=19)
    assert result.success
    assert calls[0] == (7, 1)
    assert delivered == list(range(8, 20))
    assert all((tmp_path / name).read_bytes() == data for name, data in retained.items())


def test_saved_mode_change_applies_to_next_client_without_restart(setup_client, tmp_path):
    cfg, make = setup_client
    old = make()
    run_transfer(old, tmp_path / "first", total=12)
    cfg.poor = True
    _, old_calls, _, _ = run_transfer(old, tmp_path / "second", total=12)
    _, new_calls, _, _ = run_transfer(make(), tmp_path / "third", total=12)
    assert old_calls[0][1] == 10
    assert all(size == 1 for _, size in new_calls)


@pytest.mark.parametrize("existing", [10, 20, 30, 40])
def test_normal_growth_preserves_resume_prefix(setup_client, tmp_path, existing):
    _, make = setup_client
    for n in range(1, existing + 1):
        (tmp_path / f"Instance_{n:04d}.dcm").write_bytes(b"r" * 256)
    result, calls, delivered, _ = run_transfer(make(), tmp_path)
    assert result.success
    assert delivered == list(range(existing + 1, 102))
    assert all(start % size == 0 for start, size in calls)
    assert max(size for _, size in calls) > 10


def test_oversized_response_does_not_regrow_into_the_same_error(setup_client, tmp_path):
    _, make = setup_client
    result, calls, delivered, _ = run_transfer(make(), tmp_path, oversized_above=5)
    assert result.success
    assert calls[0] == (0, 10)
    assert all(size <= 5 for _, size in calls[1:])
    assert delivered == list(range(1, 102))


@pytest.mark.parametrize("offset", [1, 7, 10, 20, 30, 40, 55, 100])
def test_slow_responses_reduce_size_without_offset_drift(offset):
    size = sc._next_aligned_batch_size(10, offset, 128, 3.0, 40)
    assert 1 <= size <= 2
    assert offset % size == 0


def test_small_configured_cap_is_preserved(setup_client, tmp_path):
    _, make = setup_client
    c = make()
    c._batch_size_cap = 4
    result, calls, delivered, _ = run_transfer(c, tmp_path, total=29)
    assert result.success
    assert max(size for _, size in calls) <= 4
    assert delivered == list(range(1, 30))


def test_mode_lookup_exception_uses_single_image(setup_client, tmp_path, monkeypatch):
    _, make = setup_client
    def unavailable():
        raise RuntimeError("Synthetic configuration failure")
    monkeypatch.setattr(socket_config, "get_socket_config", unavailable)
    result, calls, _, _ = run_transfer(make(), tmp_path, total=5)
    assert result.success and all(size == 1 for _, size in calls)
