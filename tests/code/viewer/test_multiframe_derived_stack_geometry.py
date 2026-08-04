"""Derived per-frame geometry for a top-level-only multi-frame stack (2026-08-03).

A Siemens "syngo" multi-frame Secondary Capture packs a whole 2D slice stack into
ONE file per series, with the geometry in the TOP-LEVEL tags (IOP + IPP of frame 0
+ SpacingBetweenSlices) and NO Per-Frame Functional Groups. The OPT-42 reader only
looked at functional groups, so every frame came back geometry-less → classified
`unknown` → all frames stamped with the SAME position → reference lines / sync /
slice-location could not tell the frames apart.

`derive_stack_frame_geometries` synthesises IPP_k = IPP_0 + k*step*normal (IOP
constant). Gated `AIPACS_FAST_MULTIFRAME_DERIVE_GEOMETRY` (module
`_DERIVE_STACK_GEOMETRY`), default OFF (synthesised clinical geometry → opt-in until
the direction is visually verified). Cine / no-spacing / functional-group /
single-frame cases must NOT be derived.
"""
import math

import pytest


def _mfg():
    pytest.importorskip("pydicom")
    from modules.viewer.fast import multiframe_geometry as mfg
    return mfg


def _mf_ds(n=8, iop=(1, 0, 0, 0, 1, 0), ipp=(10.0, 20.0, 30.0), sbs=5.0,
           thickness=4.0, px=(0.5, 0.5), frame_time=None, cine=None):
    from pydicom.dataset import Dataset
    ds = Dataset()
    ds.NumberOfFrames = n
    if iop is not None:
        ds.ImageOrientationPatient = list(iop)
    if ipp is not None:
        ds.ImagePositionPatient = list(ipp)
    if sbs is not None:
        ds.SpacingBetweenSlices = sbs
    if thickness is not None:
        ds.SliceThickness = thickness
    if px is not None:
        ds.PixelSpacing = list(px)
    if frame_time is not None:
        ds.FrameTime = frame_time
    if cine is not None:
        ds.CineRate = cine
    return ds


def _fg_ds(n=6, iop=(1, 0, 0, 0, 1, 0), z0=100.0, step=3.0):
    """Multi-frame WITH real functional-group geometry (Enhanced-style)."""
    from pydicom.dataset import Dataset
    ds = Dataset()
    ds.NumberOfFrames = n
    # shared orientation
    orient = Dataset(); orient.ImageOrientationPatient = list(iop)
    shared = Dataset(); shared.PlaneOrientationSequence = [orient]
    ds.SharedFunctionalGroupsSequence = [shared]
    # per-frame position
    pf = []
    for k in range(n):
        pos = Dataset(); pos.ImagePositionPatient = [0.0, 0.0, z0 + k * step]
        item = Dataset(); item.PlanePositionSequence = [pos]
        pf.append(item)
    ds.PerFrameFunctionalGroupsSequence = pf
    # ALSO put (different) top-level tags to prove the FG path wins
    ds.ImageOrientationPatient = list(iop)
    ds.ImagePositionPatient = [0.0, 0.0, -999.0]
    ds.SpacingBetweenSlices = 50.0
    return ds


def _normal(iop):
    r, c = iop[0:3], iop[3:6]
    n = (r[1] * c[2] - r[2] * c[1], r[2] * c[0] - r[0] * c[2], r[0] * c[1] - r[1] * c[0])
    m = math.sqrt(sum(x * x for x in n))
    return tuple(x / m for x in n)


def test_flag_off_is_byte_identical_unknown(monkeypatch):
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", False)
    ds = _mf_ds(n=8)
    frames = mfg.read_frame_geometries(ds)
    assert len(frames) == 8
    assert all(not f.has_spatial_geometry for f in frames)
    assert mfg.classify_frames(frames).kind == mfg.KIND_UNKNOWN


def test_flag_on_derives_uniform_stack(monkeypatch):
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    monkeypatch.setattr(mfg, "_DERIVE_UNIFORM_FALLBACK", True)
    monkeypatch.delenv("AIPACS_FAST_MULTIFRAME_STACK_SIGN", raising=False)
    ipp0 = (10.0, 20.0, 30.0)
    ds = _mf_ds(n=8, iop=(1, 0, 0, 0, 1, 0), ipp=ipp0, sbs=5.0)
    frames = mfg.read_frame_geometries(ds)
    assert len(frames) == 8
    assert all(f.has_spatial_geometry for f in frames)
    # frame 0 == top-level IPP; consecutive frames step by 5.0 along +Z normal
    assert frames[0].ipp == pytest.approx(ipp0)
    normal = _normal((1, 0, 0, 0, 1, 0))          # (0,0,1)
    for k in range(8):
        expect = tuple(ipp0[i] + k * 5.0 * normal[i] for i in range(3))
        assert frames[k].ipp == pytest.approx(expect)
    res = mfg.classify_frames(frames)
    assert res.kind == mfg.KIND_SPATIAL_VOLUME
    assert res.per_frame_geometry_valid is True
    assert res.mpr_eligible is True


def test_distinct_positions_reference_lines_can_differentiate(monkeypatch):
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    monkeypatch.setattr(mfg, "_DERIVE_UNIFORM_FALLBACK", True)
    ds = _mf_ds(n=10, ipp=(0.0, 0.0, 0.0), sbs=2.0)
    frames = mfg.read_frame_geometries(ds)
    zs = [f.ipp[2] for f in frames]
    assert len(set(round(z, 3) for z in zs)) == 10   # every frame a DISTINCT plane
    assert zs == pytest.approx([2.0 * k for k in range(10)])


def test_sign_flip_reverses_direction(monkeypatch):
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    monkeypatch.setattr(mfg, "_DERIVE_UNIFORM_FALLBACK", True)
    monkeypatch.setenv("AIPACS_FAST_MULTIFRAME_STACK_SIGN", "-1")
    ds = _mf_ds(n=5, ipp=(0.0, 0.0, 0.0), sbs=4.0)
    frames = mfg.read_frame_geometries(ds)
    assert [f.ipp[2] for f in frames] == pytest.approx([-4.0 * k for k in range(5)])


def test_falls_back_to_slice_thickness_when_no_spacing(monkeypatch):
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    monkeypatch.setattr(mfg, "_DERIVE_UNIFORM_FALLBACK", True)
    ds = _mf_ds(n=4, ipp=(0.0, 0.0, 0.0), sbs=None, thickness=3.0)
    frames = mfg.read_frame_geometries(ds)
    assert all(f.has_spatial_geometry for f in frames)
    assert [f.ipp[2] for f in frames] == pytest.approx([3.0 * k for k in range(4)])


def test_cine_is_never_derived(monkeypatch):
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    monkeypatch.setattr(mfg, "_DERIVE_UNIFORM_FALLBACK", True)
    # cine: has IOP+IPP but a FrameTime and no spatial step → must stay unknown
    ds = _mf_ds(n=12, ipp=(0.0, 0.0, 0.0), sbs=None, thickness=None, frame_time=33.3)
    frames = mfg.read_frame_geometries(ds)
    assert all(not f.has_spatial_geometry for f in frames)
    assert mfg.classify_frames(frames).kind == mfg.KIND_UNKNOWN


def test_no_step_no_derivation(monkeypatch):
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    monkeypatch.setattr(mfg, "_DERIVE_UNIFORM_FALLBACK", True)
    ds = _mf_ds(n=6, ipp=(0.0, 0.0, 0.0), sbs=None, thickness=None)
    frames = mfg.read_frame_geometries(ds)
    assert all(not f.has_spatial_geometry for f in frames)


def test_degenerate_iop_not_derived(monkeypatch):
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    monkeypatch.setattr(mfg, "_DERIVE_UNIFORM_FALLBACK", True)
    ds = _mf_ds(n=6, iop=(0, 0, 0, 0, 0, 0), ipp=(0.0, 0.0, 0.0), sbs=5.0)
    frames = mfg.read_frame_geometries(ds)
    assert all(not f.has_spatial_geometry for f in frames)


def test_functional_group_geometry_wins_over_derivation(monkeypatch):
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    monkeypatch.setattr(mfg, "_DERIVE_UNIFORM_FALLBACK", True)
    ds = _fg_ds(n=6, z0=100.0, step=3.0)
    frames = mfg.read_frame_geometries(ds)
    # functional-group positions (z = 100 + 3k), NOT the top-level -999 derivation
    assert [f.ipp[2] for f in frames] == pytest.approx([100.0 + 3.0 * k for k in range(6)])
    assert all(f.ipp[2] > -900 for f in frames)


def test_single_frame_not_derived(monkeypatch):
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    monkeypatch.setattr(mfg, "_DERIVE_UNIFORM_FALLBACK", True)
    ds = _mf_ds(n=1, ipp=(0.0, 0.0, 0.0), sbs=5.0)
    frames = mfg.read_frame_geometries(ds)
    assert len(frames) == 1
    # n<=1 → single-frame; derivation loop is gated on n>1
    assert mfg.classify_frames(frames).kind in (mfg.KIND_SINGLE,)


def test_derive_helper_returns_none_for_bad_input(monkeypatch):
    mfg = _mfg()
    ds = _mf_ds(n=6, iop=None, ipp=(0.0, 0.0, 0.0), sbs=5.0)   # no orientation
    assert mfg.derive_stack_frame_geometries(ds, 6) is None


# ── Vendor protocol (Siemens CSA ASCCONV) — the PROVEN source ──────────────
#
# The uniform guess above assumes frame 0 == top-level IPP and that the stack runs
# along +normal. On real data that is false: for this scanner the axial/sagittal
# series anchor on the FIRST protocol slice while the coronal anchors on the LAST,
# and the sagittal steps along -normal. Guessing put the coronal plane ~160 mm
# outside the patient. The CSA protocol block carries the true per-slice positions.

def _csa_ds(n, iop, ipp, positions, normals=None, sbs=5.0):
    """Multi-frame ds whose CSA private tag carries an ASCCONV slice array."""
    from pydicom.dataset import Dataset
    ds = _mf_ds(n=n, iop=iop, ipp=ipp, sbs=sbs)
    lines = ["### ASCCONV BEGIN ###", f"sSliceArray.lSize\t = \t{len(positions)}"]
    for i, p in enumerate(positions):
        lines.append(f"sSliceArray.asSlice[{i}].sPosition.dSag\t = \t{p[0]}")
        lines.append(f"sSliceArray.asSlice[{i}].sPosition.dCor\t = \t{p[1]}")
        lines.append(f"sSliceArray.asSlice[{i}].sPosition.dTra\t = \t{p[2]}")
        if normals is not None:
            nv = normals[i]
            lines.append(f"sSliceArray.asSlice[{i}].sNormal.dSag\t = \t{nv[0]}")
            lines.append(f"sSliceArray.asSlice[{i}].sNormal.dCor\t = \t{nv[1]}")
            lines.append(f"sSliceArray.asSlice[{i}].sNormal.dTra\t = \t{nv[2]}")
    lines.append("### ASCCONV END ###")
    blob = ("\n".join(lines)).encode("latin-1")
    block = ds.private_block(0x0029, "SIEMENS CSA HEADER", create=True)
    block.add_new(0x20, "OB", blob)
    return ds


def test_protocol_positions_are_parsed():
    mfg = _mfg()
    pos = [(0.0, 0.0, float(z)) for z in (0, 5, 10, 15)]
    ds = _csa_ds(4, (1, 0, 0, 0, 1, 0), (0.0, 0.0, 0.0), pos)
    got = mfg.read_protocol_slice_positions(ds)
    assert len(got) == 4
    assert got[0] == pytest.approx((0.0, 0.0, 0.0))
    assert got[3] == pytest.approx((0.0, 0.0, 15.0))


def test_protocol_anchored_on_the_LAST_slice_runs_backwards(monkeypatch):
    """The coronal case: the top-level IPP matches the LAST protocol slice, so the
    frames must march AWAY from it (backwards), not forwards off the anatomy."""
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    pos = [(0.0, 0.0, float(z)) for z in (0, 5, 10, 15)]     # protocol runs +Z
    # top-level IPP sits on the LAST protocol slice (z=15)
    ds = _csa_ds(4, (1, 0, 0, 0, 1, 0), (0.0, 0.0, 15.0), pos)
    frames = mfg.read_frame_geometries(ds)
    zs = [f.ipp[2] for f in frames]
    assert zs == pytest.approx([15.0, 10.0, 5.0, 0.0]), (
        "frames must run from the anchor back down the protocol, not +15..+30"
    )
    # every derived position must be one the protocol actually contains
    assert set(round(z, 3) for z in zs) == {0.0, 5.0, 10.0, 15.0}


def test_protocol_anchored_on_the_FIRST_slice_runs_forwards(monkeypatch):
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    pos = [(0.0, 0.0, float(z)) for z in (0, 5, 10, 15)]
    ds = _csa_ds(4, (1, 0, 0, 0, 1, 0), (0.0, 0.0, 0.0), pos)
    frames = mfg.read_frame_geometries(ds)
    assert [f.ipp[2] for f in frames] == pytest.approx([0.0, 5.0, 10.0, 15.0])


def test_protocol_preserves_non_uniform_spacing(monkeypatch):
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    pos = [(0.0, 0.0, float(z)) for z in (0, 4, 11, 15)]
    ds = _csa_ds(4, (1, 0, 0, 0, 1, 0), (0.0, 0.0, 0.0), pos, sbs=5.0)
    frames = mfg.read_frame_geometries(ds)
    assert [f.ipp[2] for f in frames] == pytest.approx([0.0, 4.0, 11.0, 15.0]), (
        "true protocol spacing must win over the nominal SpacingBetweenSlices"
    )


def test_protocol_that_does_not_enumerate_the_frames_is_refused(monkeypatch):
    """Scout / reformat / 3D slab: protocol has 1 entry for N frames. We cannot prove
    the layout, so we must produce NO geometry rather than invent it."""
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    monkeypatch.setattr(mfg, "_DERIVE_UNIFORM_FALLBACK", True)   # even then: refuse
    ds = _csa_ds(128, (1, 0, 0, 0, 1, 0), (0.0, 0.0, 0.0), [(0.0, 0.0, 0.0)])
    frames = mfg.read_frame_geometries(ds)
    assert all(not f.has_spatial_geometry for f in frames)
    assert mfg.classify_frames(frames).kind == mfg.KIND_UNKNOWN


def test_multi_orientation_localizer_is_refused(monkeypatch):
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    monkeypatch.setattr(mfg, "_DERIVE_UNIFORM_FALLBACK", True)
    pos = [(0.0, 0.0, 0.0), (0.0, 0.0, 5.0), (0.0, 0.0, 10.0)]
    normals = [(0, 0, 1), (1, 0, 0), (0, 1, 0)]     # three different planes
    ds = _csa_ds(3, (1, 0, 0, 0, 1, 0), (0.0, 0.0, 0.0), pos, normals=normals)
    assert mfg.protocol_is_multi_orientation(ds) is True
    frames = mfg.read_frame_geometries(ds)
    assert all(not f.has_spatial_geometry for f in frames)


def test_uniform_guess_is_opt_in(monkeypatch):
    """With no protocol at all, the unproven uniform guess must NOT run by default."""
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    monkeypatch.setattr(mfg, "_DERIVE_UNIFORM_FALLBACK", False)
    ds = _mf_ds(n=6, ipp=(0.0, 0.0, 0.0), sbs=5.0)      # no CSA block
    frames = mfg.read_frame_geometries(ds)
    assert all(not f.has_spatial_geometry for f in frames)


def test_functional_groups_still_beat_the_protocol(monkeypatch):
    """Enhanced files keep their own per-frame geometry — the CSA path never runs."""
    mfg = _mfg()
    monkeypatch.setattr(mfg, "_DERIVE_STACK_GEOMETRY", True)
    ds = _fg_ds(n=6, z0=100.0, step=3.0)
    frames = mfg.read_frame_geometries(ds)
    assert [f.ipp[2] for f in frames] == pytest.approx([100.0 + 3.0 * k for k in range(6)])
