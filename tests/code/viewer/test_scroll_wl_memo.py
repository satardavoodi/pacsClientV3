"""Scrolling must not re-read the DICOM header on every slice (2026-08-03).

`_set_slice_impl` calls `get_default_window_level(idx)` on EVERY slice change
(`_FAST_PER_INSTANCE_WINDOW`, default on), and that resolver did an UNCACHED
`pydicom.dcmread(path, stop_before_pixels=True)` on the GUI thread. For a
single-file MULTI-FRAME series all N slices share ONE path, so the identical header
was re-parsed on every wheel tick — the cost that made a 192-slice series choppy
while a 34-slice one felt smooth.

`_resolve_cs_window_level_cached` memoises per (path, photometric). Flag
`AIPACS_FAST_WL_MEMO` (module `_FAST_WL_MEMO`), default on.
"""
from pathlib import Path

import pytest

from tests.code.viewer.test_fast_multiframe import _make_multiframe_dicom  # noqa: E402


def _pipeline_module():
    pytest.importorskip("PySide6")
    pytest.importorskip("pydicom")
    from modules.viewer.fast import lightweight_2d_pipeline as lw
    return lw


def _open(lw, tmp_path, n_frames=12):
    series_dir = tmp_path / "mf"
    series_dir.mkdir(parents=True, exist_ok=True)
    _make_multiframe_dicom(series_dir / "cine.dcm", n_frames=n_frames, rows=16, cols=12)
    p = lw.Lightweight2DPipeline()
    p.open_series(str(series_dir))
    return p


def _count_resolver_calls(lw, monkeypatch):
    box = {"n": 0}
    real = lw.resolve_cornerstone_like_window_level_from_dicom

    def _spy(*a, **k):
        box["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(lw, "resolve_cornerstone_like_window_level_from_dicom", _spy)
    return box


def test_window_level_header_is_resolved_once_for_all_frames(tmp_path, monkeypatch):
    lw = _pipeline_module()
    p = _open(lw, tmp_path, n_frames=12)
    box = _count_resolver_calls(lw, monkeypatch)

    for k in range(10):                      # simulate a scroll-through
        p.get_default_window_level(k)

    assert box["n"] <= 1, (
        f"the same multi-frame header was re-read {box['n']}x while scrolling "
        f"— the W/L memo is not being used"
    )


def test_flag_off_reresolves_every_slice(tmp_path, monkeypatch):
    lw = _pipeline_module()
    monkeypatch.setattr(lw, "_FAST_WL_MEMO", False)
    p = _open(lw, tmp_path, n_frames=8)
    box = _count_resolver_calls(lw, monkeypatch)

    for k in range(6):
        p.get_default_window_level(k)

    assert box["n"] >= 6, f"legacy path should re-resolve per slice, saw {box['n']}"


def test_memo_returns_the_same_values_as_the_uncached_path(tmp_path, monkeypatch):
    """The memo must not change WHAT is resolved — only how often."""
    lw = _pipeline_module()

    p_off = _open(lw, tmp_path / "a", n_frames=6)
    monkeypatch.setattr(lw, "_FAST_WL_MEMO", False)
    legacy = [p_off.get_default_window_level(k) for k in range(6)]

    monkeypatch.setattr(lw, "_FAST_WL_MEMO", True)
    p_on = _open(lw, tmp_path / "b", n_frames=6)
    memoised = [p_on.get_default_window_level(k) for k in range(6)]

    assert memoised == legacy


def test_cache_is_per_series_not_global(tmp_path):
    """A new open_series must not inherit the previous series' entries."""
    lw = _pipeline_module()
    p = _open(lw, tmp_path / "s1", n_frames=4)
    p.get_default_window_level(0)
    assert getattr(p, "_cs_wl_cache", None), "memo should be populated after a call"

    series2 = tmp_path / "s2"
    series2.mkdir(parents=True, exist_ok=True)
    _make_multiframe_dicom(series2 / "cine.dcm", n_frames=4, rows=16, cols=12)
    p.open_series(str(series2))
    assert p._cs_wl_cache == {}, "memo must be reset on open_series"


def test_ds_cache_has_a_lock():
    """The whole-file ds cache is touched by the decode/prefetch worker threads and
    the GUI thread; OrderedDict.move_to_end during another thread's popitem is not
    safe."""
    lw = _pipeline_module()
    p = lw.Lightweight2DPipeline()
    lock = getattr(p, "_mf_ds_lock", None)
    assert lock is not None and hasattr(lock, "acquire")


def test_multiframe_decode_bypasses_the_l2_disk_cache_when_ds_is_in_memory(tmp_path, monkeypatch):
    """Once the whole file is decoded in memory, an L2 disk read/write per frame is
    pure overhead — it is bypassed via the null cache."""
    lw = _pipeline_module()
    p = _open(lw, tmp_path, n_frames=8)

    gets = {"n": 0}
    real_get = lw.get_disk_pixel_cache

    class _CountingCache:
        def __init__(self, inner):
            self._inner = inner

        def get(self, *a, **k):
            gets["n"] += 1
            return self._inner.get(*a, **k)

        def put(self, *a, **k):
            return self._inner.put(*a, **k)

    monkeypatch.setattr(lw, "get_disk_pixel_cache", lambda: _CountingCache(real_get()))

    p.get_pixel_array(0)          # cold: decodes the whole file, caches the ds
    gets_after_first = gets["n"]
    for k in range(1, 6):         # warm frames must not touch the disk cache
        p.get_pixel_array(k)

    assert gets["n"] == gets_after_first, (
        f"L2 disk cache was consulted {gets['n'] - gets_after_first}x for frames "
        f"already decoded in memory"
    )
