"""Synthetic invalidation and retained-volume budget regression guards."""
import threading
import time

import pytest

from PacsClient.utils.volume_cache import VolumeCache, VolumeCacheError
from PacsClient.utils import vtk_volume_service as service


@pytest.mark.parametrize('scope', ['key', 'study', 'all'])
def test_invalidated_builder_cannot_publish_or_replace_new_generation(scope):
    cache = VolumeCache()
    key = ('synthetic-study', 'synthetic-series')
    started, release = threading.Event(), threading.Event()
    results = []

    def build():
        started.set()
        assert release.wait(3)
        return 'stale'

    def run():
        try:
            results.append(cache.get_or_create(key, build))
        except VolumeCacheError:
            results.append('invalidated')

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert started.wait(3)
        if scope == 'key':
            cache.invalidate(key)
        elif scope == 'study':
            cache.invalidate_study(key[0])
        else:
            cache.invalidate_all()
        cache.put(key, 'fresh')
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert cache.peek(key) == 'fresh'
    assert results == ['invalidated']


def test_volume_wrapper_enforces_byte_budget(monkeypatch):
    monkeypatch.setattr(service, '_VTK_VOLUME_CACHE_ENABLED', True)
    monkeypatch.setattr(service, '_VTK_VOLUME_CACHE_CROSS_DOMAIN', False)
    monkeypatch.setattr(service, '_cache_max_bytes', lambda: 1024)
    instance = service.VtkVolumeService()
    monkeypatch.setattr(service, 'get_vtk_volume_service', lambda: instance)

    class Volume:
        def GetActualMemorySize(self):
            return 2  # VTK reports KiB, not bytes.

    calls = []
    def build():
        calls.append(1)
        return Volume()

    assert service.build_or_get_volume('mpr', 'study', 'series', build) is not None
    assert service.build_or_get_volume('mpr', 'study', 'series', build) is not None
    assert len(calls) == 2  # Oversized outputs are delivered but not retained.


@pytest.mark.parametrize('outcome', ['invalidate', 'oversized', 'failure'])
def test_waiters_receive_their_own_flight_outcome(outcome):
    cache = VolumeCache(max_bytes=1)
    key = ('study', 'series')
    started, release = threading.Event(), threading.Event()
    results = []
    volume = object()

    def build():
        started.set()
        assert release.wait(3)
        if outcome == 'failure':
            raise ValueError('synthetic failure')
        return volume

    def run():
        try:
            results.append(cache.get_or_create(key, build, size=2))
        except (VolumeCacheError, ValueError) as exc:
            results.append(type(exc))

    threads = [threading.Thread(target=run) for _ in range(4)]
    try:
        threads[0].start()
        assert started.wait(3)
        for thread in threads[1:]:
            thread.start()
        deadline = time.monotonic() + 3
        while cache.stats()['coalesced'] != 3 and time.monotonic() < deadline:
            time.sleep(0.001)
        assert cache.stats()['coalesced'] == 3
        if outcome == 'invalidate':
            cache.invalidate(key)
            # New generation can complete before the old owner; old waiters must
            # receive cancellation, never this unrelated generation's result.
            assert cache.get_or_create(key, lambda: 'fresh') == 'fresh'
            for thread in threads[1:]:
                thread.join(1)
                assert not thread.is_alive()
    finally:
        release.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(3)
    assert all(not thread.is_alive() for thread in threads)
    if outcome == 'invalidate':
        assert results == [VolumeCacheError] * 4
        assert cache.peek(key) == 'fresh'
    elif outcome == 'oversized':
        assert results == [volume] * 4
        assert cache.peek(key) is None
    else:
        assert results.count(ValueError) == 1
        assert results.count(VolumeCacheError) == 3
        assert cache.peek(key) is None
    assert cache.stats()['inflight'] == 0


def test_real_vtk_budget_preserves_pixels_and_domain_separation(monkeypatch):
    import vtk
    monkeypatch.setattr(service, '_VTK_VOLUME_CACHE_ENABLED', True)
    monkeypatch.setattr(service, '_VTK_VOLUME_CACHE_CROSS_DOMAIN', False)
    monkeypatch.setattr(service, '_cache_max_bytes', lambda: 70 * 1024)
    instance = service.VtkVolumeService()
    monkeypatch.setattr(service, 'get_vtk_volume_service', lambda: instance)
    calls = []

    def build():
        calls.append(1)
        image = vtk.vtkImageData()
        image.SetDimensions(32, 32, 32)
        image.AllocateScalars(vtk.VTK_SHORT, 1)
        image.GetPointData().GetScalars().Fill(17)
        return image

    first = service.build_or_get_volume('mpr', 'study', 'one', build)
    assert service.build_or_get_volume('mpr', 'study', 'one', build) is first
    assert service.build_or_get_volume('ai', 'study', 'one', build) is not first
    service.build_or_get_volume('mpr', 'study', 'two', build)
    assert instance.peek('mpr', 'study', 'one') is None
    assert instance.peek('ai', 'study', 'one') is not None
    assert first.GetScalarRange() == (17, 17)  # Consumer survives cache eviction.
    assert len(calls) == 3
