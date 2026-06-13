"""Robust optical reads: retry on transient errors, staging, scan/render use."""

import builtins
import io

import pytest
from pydicom.uid import generate_uid

from modules.cd_burner.portable_viewer import optical_io
from modules.cd_burner.portable_viewer.media_scan import scan_media
from modules.cd_burner.portable_viewer.render import load_slice

from .conftest import write_ct_slice


def test_read_bytes_round_trip(tmp_path):
    path = tmp_path / "f.bin"
    payload = b"DICOM-bytes" * 100
    path.write_bytes(payload)
    assert optical_io.read_bytes(str(path)) == payload


def test_read_bytes_retries_then_succeeds(tmp_path, monkeypatch):
    path = tmp_path / "f.bin"
    path.write_bytes(b"good-data")

    real_open = builtins.open
    calls = {"n": 0}

    def flaky_open(file, *args, **kwargs):
        # Fail the first two reads of OUR file, then succeed.
        if str(file) == str(path) and "b" in (args[0] if args else kwargs.get("mode", "")):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError(23, "Data error (cyclic redundancy check)")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", flaky_open)
    monkeypatch.setattr(optical_io.time, "sleep", lambda *_a: None)  # no real waiting

    data = optical_io.read_bytes(str(path), retries=3)
    assert data == b"good-data"
    assert calls["n"] == 3  # two failures + one success


def test_read_bytes_raises_after_exhausting_retries(tmp_path, monkeypatch):
    path = tmp_path / "f.bin"
    path.write_bytes(b"x")
    monkeypatch.setattr(optical_io.time, "sleep", lambda *_a: None)

    def always_fail(*_a, **_k):
        raise OSError(23, "CRC")

    monkeypatch.setattr(builtins, "open", always_fail)
    with pytest.raises(OSError):
        optical_io.read_bytes(str(path), retries=2)


def test_is_optical_path_non_windows_is_false(tmp_path, monkeypatch):
    # On the CI/dev box these are local disks; the helper must never crash.
    monkeypatch.setattr(optical_io.os, "name", "posix")
    assert optical_io.is_optical_path(str(tmp_path)) is False


def test_stage_files_to_temp_copies_and_cleanup(tmp_path):
    srcs = []
    for n in range(3):
        p = tmp_path / f"s{n}.dcm"
        p.write_bytes(f"data{n}".encode())
        srcs.append(str(p))

    mapping = optical_io.stage_files_to_temp(srcs)
    assert len(mapping) == 3
    for src in srcs:
        staged = mapping[src]
        assert staged != src
        assert open(staged, "rb").read() == open(src, "rb").read()

    example = next(iter(mapping.values()))
    optical_io.cleanup_temp_dir(example)
    import os
    assert not os.path.exists(example)


def test_render_and_scan_still_work_through_robust_path(tmp_path):
    """The retry-buffered read must produce identical results to a plain read."""
    study_uid, series_uid = generate_uid(), generate_uid()
    for n in (1, 2):
        write_ct_slice(tmp_path, series_uid, study_uid, n, raw_fill=1064)

    result = scan_media(str(tmp_path))
    assert len(result.series) == 1
    assert result.total_images == 2

    path = result.series[0].instances[0].path
    data = load_slice(path)
    assert not data.error
    assert float(data.array[0, 0]) == pytest.approx(40.0)  # rescale applied


def test_render_falls_back_when_buffered_read_fails(tmp_path, monkeypatch):
    """If the buffered read raises, load_slice falls back to a direct read."""
    study_uid, series_uid = generate_uid(), generate_uid()
    path = write_ct_slice(tmp_path, series_uid, study_uid, 1)

    import modules.cd_burner.portable_viewer.render as render_mod

    def boom(_path, **_k):
        raise OSError("simulated optical failure")

    monkeypatch.setattr(render_mod, "read_bytes", boom)  # buffered path fails
    data = load_slice(str(path))                          # direct fallback works
    assert not data.error
    assert data.rows == 16
