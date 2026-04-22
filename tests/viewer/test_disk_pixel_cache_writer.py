import numpy as np

from modules.viewer.fast.disk_pixel_cache import DiskPixelCache


def test_disk_pixel_cache_put_uses_single_writer_queue(tmp_path):
    cache = DiskPixelCache(tmp_path, max_size_mb=1)
    cache.initialize()

    arr = np.zeros((4, 4), dtype=np.int16)
    cache.put("sop-1", "study-1", arr)
    cache.put("sop-2", "study-1", arr)

    stats = cache.stats()
    assert "write_queue_depth" in stats
    assert hasattr(cache, "_write_thread")
    assert cache._write_thread.name == "DiskPixelCacheWriter"


def test_disk_pixel_cache_put_can_defer_during_protected_drag(tmp_path):
    cache = DiskPixelCache(tmp_path, max_size_mb=1)
    cache.initialize()

    arr = np.zeros((4, 4), dtype=np.int16)
    cache.put("sop-1", "study-1", arr, defer=True)

    assert cache.stats()["write_queue_depth"] == 0
    assert cache.stats()["deferred_queue_depth"] == 1


def test_disk_pixel_cache_flushes_deferred_writes_into_single_writer_queue(tmp_path):
    cache = DiskPixelCache(tmp_path, max_size_mb=1)
    cache.initialize()

    arr = np.ones((4, 4), dtype=np.int16)
    cache.put("sop-1", "study-1", arr, defer=True)

    flushed = cache.flush_deferred()

    assert flushed == 1
    stats = cache.stats()
    assert stats["deferred_queue_depth"] == 0
    assert stats["write_queue_depth"] <= 1
