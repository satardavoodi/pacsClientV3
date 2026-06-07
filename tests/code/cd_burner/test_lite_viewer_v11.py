"""Lite Viewer v1.1: 2-view layout, reference lines, ruler (headless)."""

import numpy as np
import pytest
from pydicom.uid import generate_uid

from modules.cd_burner.portable_viewer.media_scan import scan_media
from modules.cd_burner.portable_viewer.render import (
    SliceData,
    load_slice,
    reference_line_segment,
    ruler_length_label,
)

from .conftest import write_ct_slice


def _slice(position, row_dir, col_dir, spacing=(1.0, 1.0), rows=100, cols=100, frame="FOR1"):
    return SliceData(
        array=np.zeros((4, 4), dtype=np.float32),
        is_color=False, invert=False,
        default_center=0.0, default_width=1.0,
        rows=rows, cols=cols,
        position=position, row_dir=row_dir, col_dir=col_dir,
        pixel_spacing=spacing, measure_spacing=spacing,
        frame_of_reference=frame,
    )


# ---------------------------------------------------------------------------
# Reference-line geometry
# ---------------------------------------------------------------------------

def test_reference_line_sagittal_on_axial_is_vertical():
    axial = _slice((0.0, 0.0, 50.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    sagittal = _slice((30.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0))

    segment = reference_line_segment(axial, sagittal)
    assert segment is not None
    (u1, v1), (u2, v2) = segment
    # x = 30 mm → u = 30 px on the axial image, spanning full height
    assert u1 == pytest.approx(30.0, abs=1e-6)
    assert u2 == pytest.approx(30.0, abs=1e-6)
    assert sorted((v1, v2)) == [pytest.approx(0.0), pytest.approx(100.0)]


def test_reference_line_respects_spacing():
    axial = _slice((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), spacing=(0.5, 0.5))
    sagittal = _slice((10.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0))
    segment = reference_line_segment(axial, sagittal)
    assert segment is not None
    (u1, _), (u2, _) = segment
    assert u1 == pytest.approx(20.0)  # 10 mm / 0.5 mm-per-px
    assert u2 == pytest.approx(20.0)


def test_reference_line_parallel_planes_none():
    a = _slice((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    b = _slice((0.0, 0.0, 25.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    assert reference_line_segment(a, b) is None


def test_reference_line_frame_of_reference_mismatch_none():
    a = _slice((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), frame="FOR1")
    b = _slice((30.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0), frame="FOR2")
    assert reference_line_segment(a, b) is None


def test_reference_line_missing_geometry_none():
    a = _slice((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    bare = SliceData(
        array=np.zeros((4, 4), np.float32), is_color=False, invert=False,
        default_center=0, default_width=1, rows=10, cols=10,
    )
    assert reference_line_segment(a, bare) is None
    assert reference_line_segment(bare, a) is None


# ---------------------------------------------------------------------------
# Ruler
# ---------------------------------------------------------------------------

def test_ruler_label_mm_cm_and_px():
    calibrated = _slice((0, 0, 0), (1, 0, 0), (0, 1, 0), spacing=(0.5, 0.5))
    assert ruler_length_label(calibrated, (0, 0), (100, 0)) == "50.0 mm"
    assert ruler_length_label(calibrated, (0, 0), (300, 0)) == "15.0 cm"

    uncalibrated = SliceData(
        array=np.zeros((4, 4), np.float32), is_color=False, invert=False,
        default_center=0, default_width=1, rows=10, cols=10,
    )
    assert ruler_length_label(uncalibrated, (0, 0), (100, 0)) == "100 px"


def test_load_slice_geometry_and_spacing_sources(tmp_path):
    study_uid, series_uid = generate_uid(), generate_uid()
    ct = write_ct_slice(
        tmp_path / "geo", series_uid, study_uid, 1,
        ipp=(1.0, 2.0, 3.0), iop=(1, 0, 0, 0, 1, 0),
        pixel_spacing=(0.7, 0.6), frame_of_reference="FORX",
    )
    data = load_slice(str(ct))
    assert data.position == (1.0, 2.0, 3.0)
    assert data.row_dir == (1.0, 0.0, 0.0)
    assert data.pixel_spacing == (0.7, 0.6)
    assert data.measure_spacing == (0.7, 0.6)
    assert data.spacing_source == "PixelSpacing"
    assert data.frame_of_reference == "FORX"

    # DX-style: ImagerPixelSpacing only → measurement spacing via CP-586 chain
    dx = write_ct_slice(
        tmp_path / "dx", generate_uid(), study_uid, 1,
        imager_pixel_spacing=(0.1, 0.1),
    )
    data_dx = load_slice(str(dx))
    assert data_dx.pixel_spacing is None
    assert data_dx.measure_spacing == (0.1, 0.1)
    assert data_dx.spacing_source == "ImagerPixelSpacing"


# ---------------------------------------------------------------------------
# Window: 2-view default, pane behavior, ref lines + ruler integration
# ---------------------------------------------------------------------------

def _make_cross_series(tmp_path):
    """Axial stack (3 slices) + one sagittal slice, same frame of reference."""
    study_uid = generate_uid()
    frame = generate_uid()
    axial_uid, sagittal_uid = generate_uid(), generate_uid()
    for n in range(1, 4):
        write_ct_slice(
            tmp_path, axial_uid, study_uid, n,
            filename=f"AX{n:04d}.dcm",
            series_number=1, series_description="axial",
            ipp=(0.0, 0.0, float(n) * 5.0), iop=(1, 0, 0, 0, 1, 0),
            pixel_spacing=(1.0, 1.0), frame_of_reference=frame,
        )
    # col_dir = (0,0,-1) → the 16-px-tall image covers z = 16 … 0, which
    # CONTAINS the axial stack (z = 5/10/15) so the clipped line is visible.
    write_ct_slice(
        tmp_path, sagittal_uid, study_uid, 1,
        filename="SAG0001.dcm",
        series_number=2, series_description="sagittal",
        ipp=(8.0, 0.0, 16.0), iop=(0, 1, 0, 0, 0, -1),
        pixel_spacing=(1.0, 1.0), frame_of_reference=frame,
    )
    return study_uid


def test_window_two_view_default_with_reference_lines_and_ruler(tmp_path, qapp):
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    _make_cross_series(tmp_path)
    window = LiteViewerWindow(media_root=None)
    try:
        # Default layout: 2 views
        assert window._two_view is True
        assert window.two_view_action.isChecked()
        assert len(window.canvases) == 2
        assert window.ref_lines_action.isChecked()  # required tool, on by default

        window._on_scan_done(scan_media(str(tmp_path)))

        # Two series → auto-distributed to both panes
        assert window.pane_states[0].series_index == 0
        assert window.pane_states[1].series_index == 1
        assert window.canvases[0]._image is not None
        assert window.canvases[1]._image is not None

        # Cross-pane reference lines exist in both directions
        assert window.canvases[0].reference_line is not None
        assert window.canvases[1].reference_line is not None

        # Toggle off → lines disappear
        window.ref_lines_action.setChecked(False)
        assert window.canvases[0].reference_line is None

        # Scrolling the axial pane updates its slice
        window._set_active_pane(0)
        window._step_slice(1)
        assert window.pane_states[0].slice_index == 1
        assert window.slice_label.text() == "2/3"

        # Ruler on the active pane: 20 px at 1.0 mm/px → 20.0 mm
        window._add_ruler(0, (10.0, 10.0), (30.0, 10.0))
        assert len(window.canvases[0].rulers) == 1
        assert window.canvases[0].rulers[0][2] == "20.0 mm"

        # Measurements are per-image: slice change clears them
        window._step_slice(1)
        assert window.canvases[0].rulers == []

        # Clear button + tool selection plumbing
        window._add_ruler(0, (0.0, 0.0), (10.0, 0.0))
        window._clear_rulers()
        assert window.pane_states[0].rulers == []
        window._set_tool("ruler")
        assert all(c.active_tool == "ruler" for c in window.canvases)

        # 1-view mode hides pane 2 and keeps the app usable
        window._set_two_view(False)
        assert window.canvases[0].reference_line is None  # no second view → no lines
    finally:
        window._pool.waitForDone(3000)
        window.close()


def test_window_single_series_leaves_second_pane_empty(tmp_path, qapp):
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    study_uid, series_uid = generate_uid(), generate_uid()
    for n in (1, 2):
        write_ct_slice(tmp_path, series_uid, study_uid, n)

    window = LiteViewerWindow(media_root=None)
    try:
        window._on_scan_done(scan_media(str(tmp_path)))
        assert window.pane_states[0].series_index == 0
        assert window.pane_states[1].series_index == -1
        assert window.canvases[1]._image is None
        # Legacy accessors still drive the active pane
        assert window._series_index == 0
        assert len(window._slice_keys) == 2
    finally:
        window._pool.waitForDone(3000)
        window.close()
