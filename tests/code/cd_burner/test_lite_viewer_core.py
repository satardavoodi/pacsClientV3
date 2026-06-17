"""Headless tests for the portable Lite Viewer core (scan + render + window)."""

import warnings
from pathlib import Path

import pytest
from pydicom.uid import generate_uid

from modules.cd_burner.portable_viewer.media_scan import (
    discover_media_root,
    scan_media,
)
from modules.cd_burner.portable_viewer.render import load_slice, slice_to_qimage

from .conftest import write_ct_slice, write_rgb_slice


# ---------------------------------------------------------------------------
# media_scan
# ---------------------------------------------------------------------------

def test_filescan_groups_and_sorts_series(tmp_path):
    study_uid = generate_uid()
    ct_uid = generate_uid()
    rgb_uid = generate_uid()

    # CT instances written out of order, nested, mixed extensions
    write_ct_slice(tmp_path / "a", ct_uid, study_uid, 3, filename="z_no_ext")
    write_ct_slice(tmp_path / "a" / "b", ct_uid, study_uid, 1)
    write_ct_slice(tmp_path / "a", ct_uid, study_uid, 2)
    write_rgb_slice(tmp_path / "doc", rgb_uid, study_uid)
    (tmp_path / "README.txt").write_text("not dicom", encoding="utf-8")

    result = scan_media(str(tmp_path))

    assert result.source == "filescan"
    assert not result.errors
    assert len(result.series) == 2
    assert result.total_images == 4

    ct = next(s for s in result.series if s.series_uid == ct_uid)
    assert [i.instance_number for i in ct.instances] == [1, 2, 3]
    assert ct.modality == "CT"
    assert ct.patient_id == "PID-CD-001"
    assert "PID-CD-001" in result.patient_labels()[0]


def test_scan_prefers_dicomdir(tmp_path):
    from pydicom.fileset import FileSet

    study_uid = generate_uid()
    series_uid = generate_uid()
    src = tmp_path / "src"
    paths = [
        write_ct_slice(src, series_uid, study_uid, n, filename=f"f{n}.dcm")
        for n in (2, 1)
    ]

    media = tmp_path / "media"
    fs = FileSet()
    for p in paths:
        fs.add(str(p))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        fs.write(media)
    assert (media / "DICOMDIR").exists()

    result = scan_media(str(media))
    assert result.source == "dicomdir"
    assert len(result.series) == 1
    assert [i.instance_number for i in result.series[0].instances] == [1, 2]


def test_scan_missing_folder_reports_error(tmp_path):
    result = scan_media(str(tmp_path / "nope"))
    assert result.series == []
    assert result.errors


def test_discover_media_root_prefers_cli_then_probes(tmp_path):
    study_uid = generate_uid()
    series_uid = generate_uid()

    plain = tmp_path / "plain"
    write_ct_slice(plain, series_uid, study_uid, 1)
    assert discover_media_root(str(plain)) == str(plain.resolve())

    empty = tmp_path / "empty"
    empty.mkdir()
    assert discover_media_root(str(empty)) is None


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

def test_load_slice_applies_rescale_and_header_window(tmp_path):
    study_uid, series_uid = generate_uid(), generate_uid()
    path = write_ct_slice(tmp_path, series_uid, study_uid, 1, raw_fill=1064)

    data = load_slice(str(path))
    assert not data.error
    assert not data.is_color
    # raw 1064 with intercept -1024 → 40 HU everywhere
    assert float(data.array[0, 0]) == pytest.approx(40.0)
    assert data.default_center == pytest.approx(40.0)
    assert data.default_width == pytest.approx(400.0)


def test_window_mapping_mid_low_high(tmp_path, qapp):
    study_uid, series_uid = generate_uid(), generate_uid()
    path = write_ct_slice(tmp_path, series_uid, study_uid, 1, raw_fill=1064)
    data = load_slice(str(path))

    # value == center → mid gray
    img = slice_to_qimage(data, center=40.0, width=400.0)
    mid = img.pixelColor(0, 0).red()
    assert abs(mid - 127) <= 2

    # center far above value → black; far below → white
    assert slice_to_qimage(data, 400.0, 100.0).pixelColor(0, 0).red() == 0
    assert slice_to_qimage(data, -400.0, 100.0).pixelColor(0, 0).red() == 255


def test_monochrome1_renders_inverted(tmp_path, qapp):
    study_uid, series_uid = generate_uid(), generate_uid()
    path = write_ct_slice(
        tmp_path, series_uid, study_uid, 1,
        photometric="MONOCHROME1", raw_fill=1064,
    )
    data = load_slice(str(path))
    assert data.invert

    img = slice_to_qimage(data, center=400.0, width=100.0)
    # value far BELOW window → would be black, inverted → white
    assert img.pixelColor(0, 0).red() == 255


def test_monochrome1_default_window_from_percentiles(tmp_path):
    study_uid, series_uid = generate_uid(), generate_uid()
    path = write_ct_slice(
        tmp_path, series_uid, study_uid, 1,
        photometric="MONOCHROME1", with_window=False,
    )
    data = load_slice(str(path))
    assert not data.error
    assert data.default_width > 1.0  # percentile fallback produced a usable span


def test_rgb_passthrough(tmp_path, qapp):
    study_uid, series_uid = generate_uid(), generate_uid()
    path = write_rgb_slice(tmp_path, series_uid, study_uid)
    data = load_slice(str(path))

    assert data.is_color
    img = slice_to_qimage(data, 0, 1)  # W/L ignored for color
    color = img.pixelColor(0, 0)
    assert (color.red(), color.green(), color.blue()) == (200, 10, 30)


def test_corrupt_file_yields_error_slice(tmp_path):
    bad = tmp_path / "bad.dcm"
    bad.write_bytes(b"this is not dicom at all")
    data = load_slice(str(bad))
    assert data.error


def test_selftest_slice_is_well_formed(qapp):
    """The frozen-bundle self-test must render a NON-degenerate image. The old
    1x1 placeholder could construct as a null QImage (0x0) under heavy
    build-time load and fail the release gate spuriously."""
    from modules.cd_burner.portable_viewer.render import SliceData

    data = SliceData.selftest_slice(16)
    assert data.array.shape == (16, 16)
    assert data.rows == 16 and data.cols == 16
    img = slice_to_qimage(data, data.default_center, data.default_width)
    assert img.width() == 16 and img.height() == 16


def test_run_selftest_returns_zero(qapp):
    """run_selftest is the build's release gate — it must pass in-process so a
    healthy bundle is never rejected. Keeps numpy access inside render (no
    second numpy import → no 'cannot load module more than once' crash)."""
    from modules.cd_burner.portable_viewer import viewer_app

    assert viewer_app.run_selftest() == 0


# ---------------------------------------------------------------------------
# viewer window (offscreen smoke test)
# ---------------------------------------------------------------------------

def test_window_loads_series_and_scrolls(tmp_path, qapp):
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    study_uid, series_uid = generate_uid(), generate_uid()
    for n in (1, 2, 3):
        write_ct_slice(tmp_path, series_uid, study_uid, n)

    window = LiteViewerWindow(media_root=None)
    try:
        result = scan_media(str(tmp_path))
        window._on_scan_done(result)

        # one header row + one series row
        assert window.series_list.count() == 2
        assert window._series_index == 0
        assert len(window._slice_keys) == 3
        assert window.slice_label.text() == "1/3"
        assert window.canvas._image is not None

        window._step_slice(1)
        assert window.slice_label.text() == "2/3"
        window._step_slice(10)  # clamps to last
        assert window.slice_label.text() == "3/3"

        # W/L drag changes current values and re-renders
        before = window._current_wl
        window._adjust_wl(20, 10)
        assert window._current_wl != before
        window._reset_wl()
        assert window._current_wl[1] == pytest.approx(400.0)
    finally:
        window._pool.waitForDone(3000)
        window.close()
