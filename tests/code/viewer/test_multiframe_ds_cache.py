"""Multi-frame stacking must not re-decode the whole file per frame (2026-08-02).

A NumberOfFrames>1 DICOM (cine / enhanced MR/CT — patient 9202182227 series 11)
decodes EVERY frame on each ``ds.pixel_array``. The FAST pipeline expands it into
N scrollable slices, so stacking through the frames re-read + re-decoded the WHOLE
file at every step — O(N^2), slow on a large series. The fix caches the decoded
``ds`` per file path so frames 2..N reuse pydicom's already-decoded array.

Behavioural: spy on ``pydicom.dcmread`` and confirm decoding many frames reads the
file at most ONCE. Flag ``AIPACS_FAST_MULTIFRAME_WHOLE_CACHE`` (module-level
``_FAST_MULTIFRAME_WHOLE_CACHE``) gates it.
"""
from pathlib import Path

import pytest

# reuse the synthetic multi-frame builder from the sibling test module
from tests.code.viewer.test_fast_multiframe import _make_multiframe_dicom  # noqa: E402


def _pipeline_module():
    pytest.importorskip("PySide6")
    pytest.importorskip("pydicom")
    pytest.importorskip("numpy")
    from modules.viewer.fast import lightweight_2d_pipeline as lw
    return lw


def _count_reads(monkeypatch):
    import pydicom
    box = {"n": 0}
    real = pydicom.dcmread

    def _spy(*a, **k):
        box["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(pydicom, "dcmread", _spy)
    return box


def test_multiframe_reads_the_file_once_for_all_frames(tmp_path, monkeypatch):
    lw = _pipeline_module()
    series_dir = tmp_path / "mf"
    series_dir.mkdir()
    _make_multiframe_dicom(series_dir / "cine.dcm", n_frames=8, rows=16, cols=12)

    p = lw.Lightweight2DPipeline()
    p.open_series(str(series_dir))

    # count ONLY the reads that happen during frame decode (after open)
    box = _count_reads(monkeypatch)
    arrs = [p.get_pixel_array(k) for k in range(6)]

    assert all(a is not None for a in arrs), "every frame must decode"
    # THE FIX: the whole multi-frame file is read at most once; frames 2..N reuse
    # the cached ds (or an even-earlier L2 hit). O(N), not O(N^2).
    assert box["n"] <= 1, f"multi-frame decode re-read the file {box['n']}x — ds cache not reused"


def test_flag_off_rereads_per_frame(tmp_path, monkeypatch):
    lw = _pipeline_module()
    # kill switch → legacy behaviour: each distinct frame re-reads the file
    monkeypatch.setattr(lw, "_FAST_MULTIFRAME_WHOLE_CACHE", False)
    series_dir = tmp_path / "mf_off"
    series_dir.mkdir()
    _make_multiframe_dicom(series_dir / "cine.dcm", n_frames=6, rows=16, cols=12)

    p = lw.Lightweight2DPipeline()
    p.open_series(str(series_dir))

    box = _count_reads(monkeypatch)
    for k in range(4):
        p.get_pixel_array(k)
    # legacy path: no ds reuse → one file read per distinct frame
    assert box["n"] >= 4, f"flag off should re-read per frame, saw {box['n']}"
