"""Guard tests: disk pixel cache must never corrupt multi-channel images.

Root cause of the series-100000 (dicomized JPEG clinical-history page,
Modality=DOC, RGB, 2200x1598) second-drop corruption: the .apc on-disk format
records rows/cols only. An RGB (H, W, 3) array was written with ALL its bytes
but read back as rows*cols single-channel — the first third of the
interleaved RGB stream reshaped to (H, W): a striped, cropped grayscale page.
First load (cache miss) decoded correctly; every later load (cache hit)
displayed the corrupt frame and ran the grayscale W/L path.

Pinned here:
  1. 2D grayscale round-trip stays intact (the cache's whole purpose).
  2. put() refuses non-2D arrays (no new corrupt entries).
  3. Legacy oversized entries on disk are rejected and DELETED on get()
     (self-healing for caches written before the guard).
"""
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.viewer.fast.disk_pixel_cache import (  # noqa: E402
    DiskPixelCache,
    _HEADER_FMT,
    _HEADER_MAGIC,
    _HEADER_VERSION,
    _uid_hash,
)

_SOP = "1.2.3.4.5.100000"
_STUDY = "9.8.7.6"


def _make_cache(tmp_path):
    cache = DiskPixelCache(user_data_root=tmp_path)
    cache.initialize()
    return cache


def _drain(cache):
    cache._write_queue.join()


def test_2d_grayscale_round_trip(tmp_path):
    cache = _make_cache(tmp_path)
    arr = (np.arange(64 * 48) % 251).astype(np.int16).reshape(64, 48)
    cache.put(_SOP, _STUDY, arr)
    _drain(cache)
    out = cache.get(_SOP, _STUDY, expected_shape=(64, 48))
    assert out is not None
    assert out.shape == (64, 48)
    assert out.dtype == np.int16
    assert np.array_equal(out, arr)


def test_put_refuses_rgb_array(tmp_path):
    cache = _make_cache(tmp_path)
    rgb = np.zeros((220, 159, 3), dtype=np.uint8)  # document-page-like
    cache.put(_SOP, _STUDY, rgb)
    _drain(cache)
    assert cache.get(_SOP, _STUDY, expected_shape=(220, 159)) is None
    # nothing written to disk either
    study_dir = tmp_path / "cache" / "pixel_cache" / _uid_hash(_STUDY)
    assert not study_dir.exists() or not any(study_dir.glob("*.apc"))


def test_legacy_multichannel_entry_rejected_and_deleted(tmp_path):
    """A pre-guard cache file written from an RGB array must self-heal."""
    rows, cols = 220, 159
    key = _uid_hash(_SOP)
    study_dir = tmp_path / "cache" / "pixel_cache" / _uid_hash(_STUDY)
    study_dir.mkdir(parents=True)
    path = study_dir / f"{key}.apc"
    header = struct.pack(_HEADER_FMT, _HEADER_MAGIC, _HEADER_VERSION, 3, rows, cols)
    payload = bytes(rows * cols * 3)  # full interleaved RGB byte count
    path.write_bytes(header + payload)

    cache = _make_cache(tmp_path)  # initialize() indexes the legacy file
    out = cache.get(_SOP, _STUDY, expected_shape=(rows, cols))
    assert out is None, "legacy multi-channel entry must not be served"
    assert not path.exists(), "corrupt entry must be deleted on detection"


def test_truncated_entry_still_rejected(tmp_path):
    rows, cols = 64, 48
    key = _uid_hash(_SOP)
    study_dir = tmp_path / "cache" / "pixel_cache" / _uid_hash(_STUDY)
    study_dir.mkdir(parents=True)
    path = study_dir / f"{key}.apc"
    header = struct.pack(_HEADER_FMT, _HEADER_MAGIC, _HEADER_VERSION, 3, rows, cols)
    path.write_bytes(header + bytes(10))  # far too short

    cache = _make_cache(tmp_path)
    assert cache.get(_SOP, _STUDY, expected_shape=(rows, cols)) is None
    assert not path.exists()
