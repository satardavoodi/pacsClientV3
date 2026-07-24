"""Pure multi-frame geometry + classification (2026-07-24).

Enhanced multi-frame files store geometry in the functional groups, NOT the
top-level tags. This module reads per-frame IPP/IOP/PixelMeasures and classifies
whether the series is a spatial volume (MPR-eligible), a temporal cine, a
multi-stack localizer, or a multi-dimensional (spatial x parametric) acquisition.

Pure stdlib + pydicom — no Qt/VTK/DB — so these run headless.
"""
import math

import pytest

from modules.viewer.fast.multiframe_geometry import (
    KIND_MULTI_DIMENSIONAL,
    KIND_MULTI_STACK,
    KIND_SINGLE,
    KIND_SPATIAL_VOLUME,
    KIND_TEMPORAL,
    KIND_UNKNOWN,
    FrameGeometry,
    classify_dataset,
    classify_frames,
    read_frame_geometries,
    slice_normal,
)


# ── synthetic Enhanced multi-frame builders ─────────────────────────────────

def _mk_dataset(n_frames, *, ipp_fn, iop=(1, 0, 0, 0, 1, 0), px=(0.75, 0.75),
                thickness=5.0, stack_fn=None, instack_fn=None, dimidx_fn=None,
                shared_orient=True):
    pydicom = pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset

    ds = Dataset()
    ds.NumberOfFrames = n_frames
    ds.Rows = 16
    ds.Columns = 16

    shared = Dataset()
    if shared_orient:
        po = Dataset()
        po.ImageOrientationPatient = list(iop)
        shared.PlaneOrientationSequence = [po]
    pm = Dataset()
    pm.PixelSpacing = list(px)
    pm.SliceThickness = thickness
    shared.PixelMeasuresSequence = [pm]
    ds.SharedFunctionalGroupsSequence = [shared]

    per_frame = []
    for k in range(n_frames):
        fr = Dataset()
        pp = Dataset()
        pp.ImagePositionPatient = list(ipp_fn(k))
        fr.PlanePositionSequence = [pp]
        if not shared_orient:
            po = Dataset()
            po.ImageOrientationPatient = list(iop if not callable(iop) else iop(k))
            fr.PlaneOrientationSequence = [po]
        fc = Dataset()
        if stack_fn is not None:
            fc.StackID = str(stack_fn(k))
        if instack_fn is not None:
            fc.InStackPositionNumber = int(instack_fn(k))
        if dimidx_fn is not None:
            fc.DimensionIndexValues = list(dimidx_fn(k))
        fr.FrameContentSequence = [fc]
        per_frame.append(fr)
    ds.PerFrameFunctionalGroupsSequence = per_frame
    return ds


def test_single_frame_is_not_multiframe():
    frames = [FrameGeometry(frame_index=0, ipp=(0, 0, 0), iop=(1, 0, 0, 0, 1, 0))]
    c = classify_frames(frames)
    assert c.kind == KIND_SINGLE
    assert not c.mpr_eligible


def test_spatial_volume_axial_stack():
    # 20 axial slices, 5 mm apart along +Z
    ds = _mk_dataset(20, ipp_fn=lambda k: (0.0, 0.0, k * 5.0),
                     iop=(1, 0, 0, 0, 1, 0), instack_fn=lambda k: k + 1, stack_fn=lambda k: 1)
    c = classify_dataset(ds)
    assert c.kind == KIND_SPATIAL_VOLUME
    assert c.mpr_eligible
    assert c.volume_frame_indices == list(range(20))
    assert c.per_frame_geometry_valid
    # normal is along Z
    n = slice_normal((1, 0, 0, 0, 1, 0))
    assert abs(abs(n[2]) - 1.0) < 1e-9


def test_temporal_cine_all_same_location():
    # 30 frames, identical position (angio / cine / echo loop)
    ds = _mk_dataset(30, ipp_fn=lambda k: (10.0, 20.0, 30.0),
                     iop=(1, 0, 0, 0, 1, 0), instack_fn=lambda k: 1)
    c = classify_dataset(ds)
    assert c.kind == KIND_TEMPORAL
    assert not c.mpr_eligible
    assert c.volume_frame_indices == []


def test_multi_stack_localizer_three_orientations():
    # 3-plane localizer: 6 axial + 6 sagittal + 6 coronal-ish, different IOP/StackID
    orients = {
        1: (1, 0, 0, 0, 1, 0),      # axial
        2: (1, 0, 0, 0, 0, -1),     # coronal
        3: (0, 1, 0, 0, 0, -1),     # sagittal
    }
    def ipp_fn(k):
        s = (k // 6) + 1
        i = k % 6
        return (i * 5.0, s * 3.0, i * 5.0)
    def iop_fn(k):
        return orients[(k // 6) + 1]
    ds = _mk_dataset(18, ipp_fn=ipp_fn, iop=iop_fn, shared_orient=False,
                     stack_fn=lambda k: (k // 6) + 1, instack_fn=lambda k: (k % 6) + 1)
    c = classify_dataset(ds)
    assert c.kind == KIND_MULTI_STACK
    assert c.stack_count == 3


def test_multi_dimensional_dwi_repeated_positions():
    # 40 frames = 8 positions x 5 b-values. positions repeat.
    n_pos, n_b = 8, 5
    def ipp_fn(k):
        pos = k // n_b            # 0..7  (5 consecutive frames share a position)
        return (0.0, 0.0, pos * 5.0)
    def dim_fn(k):
        pos = k // n_b
        b = k % n_b
        return (1, pos + 1, b + 1)
    ds = _mk_dataset(n_pos * n_b, ipp_fn=ipp_fn, iop=(1, 0, 0, 0, 1, 0),
                     instack_fn=lambda k: (k // n_b) + 1, dimidx_fn=dim_fn)
    c = classify_dataset(ds)
    assert c.kind == KIND_MULTI_DIMENSIONAL
    assert c.mpr_eligible
    # one representative per spatial position → 8-slice sub-volume
    assert len(c.volume_frame_indices) == n_pos


def test_per_frame_geometry_read_merges_shared_and_perframe():
    ds = _mk_dataset(4, ipp_fn=lambda k: (0.0, 0.0, k * 2.0),
                     iop=(1, 0, 0, 0, 1, 0), px=(0.5, 0.5), thickness=2.0)
    frames = read_frame_geometries(ds)
    assert len(frames) == 4
    # orientation + spacing come from SHARED, position from PER-FRAME
    assert frames[0].iop == (1, 0, 0, 0, 1, 0)
    assert frames[0].pixel_spacing == (0.5, 0.5)
    assert frames[2].ipp == (0.0, 0.0, 4.0)
    assert all(f.has_spatial_geometry for f in frames)


def test_no_functional_groups_is_unknown():
    pydicom = pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset
    ds = Dataset()
    ds.NumberOfFrames = 10          # multi-frame but NO functional groups (US cine w/o geometry)
    frames = read_frame_geometries(ds)
    assert len(frames) == 10
    assert all(not f.has_spatial_geometry for f in frames)
    c = classify_frames(frames)
    assert c.kind == KIND_UNKNOWN
    assert not c.mpr_eligible
    assert not c.per_frame_geometry_valid


def test_non_uniform_spacing_not_a_clean_volume():
    # positions 0, 5, 5.2, 40 — irregular → not MPR-eligible as a clean stack
    pos = [0.0, 5.0, 5.2, 40.0]
    ds = _mk_dataset(4, ipp_fn=lambda k: (0.0, 0.0, pos[k]), iop=(1, 0, 0, 0, 1, 0))
    c = classify_dataset(ds)
    # distinct positions but irregular → spatial kind, MPR not eligible
    assert c.kind in (KIND_SPATIAL_VOLUME, KIND_MULTI_DIMENSIONAL)
    assert not c.mpr_eligible


def test_degenerate_iop_is_not_spatial():
    frames = [FrameGeometry(frame_index=k, ipp=(0, 0, k * 5.0),
                            iop=(0, 0, 0, 0, 0, 0)) for k in range(5)]
    assert all(not f.has_spatial_geometry for f in frames)
    c = classify_frames(frames)
    assert c.kind == KIND_UNKNOWN
