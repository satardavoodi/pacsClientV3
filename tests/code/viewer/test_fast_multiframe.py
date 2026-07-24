"""FAST multi-frame / cine / enhanced support (2026-07-01).

A single DICOM file with NumberOfFrames > 1 (ultrasound cine, XA, enhanced CT/MR)
used to show ONLY frame 0 in the FAST viewer: the pipeline built one SliceMeta per
FILE and the decoder did arr = arr[0]. This change expands such a file into N
scrollable slices, each decoding its OWN frame with a frame-aware disk-cache key.

Single-frame series are byte-identical (the expansion + frame-select branches are
never reached); AIPACS_FAST_MULTIFRAME=0 disables the feature entirely.
"""
from pathlib import Path

import numpy as np
import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _make_multiframe_dicom(path: Path, n_frames: int = 8, rows: int = 16, cols: int = 12,
                           *, per_frame_ipp=None, iop=(1, 0, 0, 0, 1, 0),
                           pixel_spacing=(0.75, 0.75), enhanced_sop=False):
    pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    sop = "1.2.840.10008.5.1.4.1.1.4.1" if enhanced_sop else "1.2.840.10008.5.1.4.1.1.3.1"
    ds.file_meta.MediaStorageSOPClassUID = sop
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = sop
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "MR" if enhanced_sop else "US"
    ds.InstanceNumber = 1
    ds.Rows = rows
    ds.Columns = cols
    ds.NumberOfFrames = n_frames
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    if per_frame_ipp is not None:
        # Enhanced-style geometry: top-level tags EMPTY, geometry in the
        # functional groups (Shared orientation/spacing + Per-Frame position).
        shared = Dataset()
        po = Dataset(); po.ImageOrientationPatient = list(iop)
        shared.PlaneOrientationSequence = [po]
        pm = Dataset(); pm.PixelSpacing = list(pixel_spacing); pm.SliceThickness = 5.0
        shared.PixelMeasuresSequence = [pm]
        ds.SharedFunctionalGroupsSequence = [shared]
        per_frame = []
        for k in range(n_frames):
            fr = Dataset()
            pp = Dataset(); pp.ImagePositionPatient = list(per_frame_ipp(k))
            fr.PlanePositionSequence = [pp]
            fc = Dataset(); fc.StackID = "1"; fc.InStackPositionNumber = k + 1
            fr.FrameContentSequence = [fc]
            per_frame.append(fr)
        ds.PerFrameFunctionalGroupsSequence = per_frame
    frames = np.stack([np.full((rows, cols), k, dtype=np.uint16) for k in range(n_frames)])
    ds.PixelData = frames.tobytes()
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.save_as(str(path), write_like_original=False)


def test_header_scan_captures_number_of_frames(tmp_path):
    pytest.importorskip("pydicom")
    import importlib.util
    import sys
    mod_path = _repo_root() / "modules" / "viewer" / "fast" / "dicom_header_scan.py"
    spec = importlib.util.spec_from_file_location("aipacs_dhs_under_test", mod_path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # pragma: no cover
        pytest.skip("header-scan import unavailable: %s" % exc)
    scan_series_header_entries = m.scan_series_header_entries
    _safe_number_of_frames = m._safe_number_of_frames

    assert _safe_number_of_frames(8) == 8
    assert _safe_number_of_frames(1) == 1
    assert _safe_number_of_frames(None) == 1
    assert _safe_number_of_frames("garbage") == 1
    assert _safe_number_of_frames(0) == 1

    series_dir = tmp_path / "1"
    series_dir.mkdir()
    _make_multiframe_dicom(series_dir / "img0.dcm", n_frames=8)
    entries = scan_series_header_entries(str(series_dir))
    assert len(entries) == 1
    assert int(entries[0].num_frames) == 8


def test_pixel_array_frame_indexing_assumption(tmp_path):
    pydicom = pytest.importorskip("pydicom")
    p = tmp_path / "mf.dcm"
    _make_multiframe_dicom(p, n_frames=6, rows=8, cols=8)
    ds = pydicom.dcmread(str(p), force=True)
    arr = np.asarray(ds.pixel_array)
    assert arr.ndim == 3 and arr.shape[0] == 6
    for k in range(6):
        assert int(arr[k].flat[0]) == k
        assert int(arr[k].min()) == k and int(arr[k].max()) == k


def _pipeline_src() -> str:
    return (
        _repo_root() / "modules" / "viewer" / "fast" / "lightweight_2d_pipeline.py"
    ).read_text(encoding="utf-8")


def test_slice_meta_has_frame_fields():
    src = _pipeline_src()
    assert "frame_index: Optional[int] = None" in src
    assert "num_frames: int = 1" in src


def test_flag_default_on_kill_switch():
    src = _pipeline_src()
    assert 'os.environ.get("AIPACS_FAST_MULTIFRAME", "1")' in src
    assert "_FAST_MULTIFRAME = str(" in src


def test_expansion_wired_in_open_series():
    src = _pipeline_src()
    assert "self._slices = self._expand_multiframe_slices(self._slices)" in src
    i_build = src.find("self._slices = self._scan_series_headers(series_path)")
    i_expand = src.find("self._slices = self._expand_multiframe_slices(self._slices)")
    i_sort = src.find("self._slices = self._sort_slices(self._slices)")
    assert -1 < i_build < i_expand < i_sort


def test_expansion_logic_pins():
    src = _pipeline_src()
    fn = src.find("def _expand_multiframe_slices")
    body = src[fn:fn + 3200]
    assert "if not _FAST_MULTIFRAME or not slices:" in body
    assert 'int(getattr(sm, "num_frames", 1) or 1)' in body
    # per-frame geometry stamping (spatial frame) + the legacy fallback branch
    assert "geoms = self._read_multiframe_geometry(sm.path, n)" in body
    assert "g is not None and g.has_spatial_geometry" in body
    assert "_dc_replace(sm, frame_index=k, num_frames=n)" in body  # fallback path
    assert "len(slices) == 1" in body


def test_decode_selects_own_frame_and_frame_aware_cache_key():
    src = _pipeline_src()
    assert "_frame = int(_fi) if (_FAST_MULTIFRAME and _fi is not None) else 0" in src
    assert "arr = arr[_frame] if 0 <= _frame < arr.shape[0] else arr[0]" in src
    fn = src.find("def _decode_cache_key")
    body = src[fn:fn + 700]
    assert 'return f"{base}::f{int(fi)}"' in body
    assert "return base" in body
    assert "self._decode_cache_key(sm)" in src


def test_sort_keeps_frames_ordered():
    src = _pipeline_src()
    fn = src.find("def _sort_slices")
    body = src[fn:fn + 900]
    assert 's.frame_index if getattr(s, "frame_index", None) is not None else -1' in body


def test_disk_cache_policy_tag_bumped_to_invalidate_stale_multiframe():
    """The pixel-cache policy tag must be bumped past v4 so poisoned multi-frame
    entries written by a pre-2026-07-01 build (which cached the WRONG frame for
    NumberOfFrames>1 files) are invalidated on upgrade — else a multi-frame
    series shows a scrambled/edge frame at the wrong slice (Charles Walker MRI,
    imported Enhanced-MR)."""
    src = _pipeline_src()
    assert '_FAST_DISK_CACHE_POLICY_TAG = "decode-v4"' not in src
    assert '_FAST_DISK_CACHE_POLICY_TAG = "decode-v5"' in src


def test_multiframe_subproc_guard_flag_default_on():
    src = _pipeline_src()
    assert 'os.environ.get("AIPACS_FAST_MULTIFRAME_SUBPROC_GUARD", "1")' in src
    assert "_FAST_MULTIFRAME_SUBPROC_GUARD = str(" in src
    # the guard must force in-process (frame-aware) decode for a multi-frame frame
    fn = src.find("def _decode_into_cache")
    body = src[fn:fn + 7000]
    assert "_FAST_MULTIFRAME_SUBPROC_GUARD" in body
    assert "getattr(sm, 'frame_index', None) is not None" in body
    assert "use_subprocess_prefetch = False" in body


def test_background_prefetch_does_not_poison_multiframe_with_frame0(tmp_path):
    """THE fast-scroll regression: the subprocess decode service is NOT
    frame-aware (returns arr[0] for any NumberOfFrames>1 file). Background
    prefetch used it, caching frame 0 under EVERY frame's key → wrong/"missing"
    frames while stacking. This drives the real `_decode_into_cache` prefetch
    path with a stubbed frame-UNAWARE service (always returns frame 0) and
    asserts the guard keeps each frame's cache entry frame-aware."""
    pytest.importorskip("pydicom")
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    import importlib
    lw = importlib.import_module("modules.viewer.fast.lightweight_2d_pipeline")

    series_dir = tmp_path / "1"
    series_dir.mkdir()
    n = 8
    _make_multiframe_dicom(series_dir / "mf.dcm", n_frames=n, rows=16, cols=12)

    # a stub decode service that MIMICS the real frame-unaware subprocess:
    # "available" and always returns frame 0 (all-zeros here, since frame k == k)
    class _FrameUnawareSvc:
        is_available = True

        def decode(self, *, rows, cols, **_):
            return np.zeros((rows, cols), dtype=np.uint16)

    cache = lw.get_disk_pixel_cache()
    if hasattr(cache, "clear"):
        cache.clear()
    orig = lw.get_decode_service
    lw.get_decode_service = lambda: _FrameUnawareSvc()
    try:
        p = lw.Lightweight2DPipeline()
        p.open_series(str(series_dir))
        sc = p.slice_count
        assert (sc() if callable(sc) else sc) == n
        wrong = []
        for k in range(n):
            p._current_index = k                 # stay inside the relevance window
            p._decode_into_cache(k, 0, 0, 0)     # the real background prefetch path
            got = p._pixel_cache.get(k)
            val = None if got is None else int(np.asarray(got).flat[0])
            if val != k:
                wrong.append((k, val))
        assert not wrong, f"prefetch cached wrong frame (frame-0 poison): {wrong}"
    finally:
        lw.get_decode_service = orig
        if hasattr(cache, "clear"):
            cache.clear()


def test_expansion_stamps_per_frame_geometry(tmp_path):
    """Enhanced multi-frame: each expanded SliceMeta must carry its OWN
    per-frame IPP + real pixel spacing from the functional groups, not the
    (absent → default) top-level geometry."""
    pytest.importorskip("pydicom")
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import importlib
    lw = importlib.import_module("modules.viewer.fast.lightweight_2d_pipeline")

    series_dir = tmp_path / "1"
    series_dir.mkdir()
    # 6 axial slices 5 mm apart along +Z, spacing 0.75 mm, in functional groups
    _make_multiframe_dicom(series_dir / "mf.dcm", n_frames=6, rows=16, cols=16,
                           per_frame_ipp=lambda k: (0.0, 0.0, k * 5.0),
                           pixel_spacing=(0.75, 0.75), enhanced_sop=True)
    p = lw.Lightweight2DPipeline()
    p.open_series(str(series_dir))
    sc = p.slice_count
    sc = sc() if callable(sc) else sc
    assert sc == 6
    zs = [round(p._slices[k].ipp[2], 3) for k in range(6)]
    assert zs == [0.0, 5.0, 10.0, 15.0, 20.0, 25.0], zs     # distinct per-frame positions
    assert p._slices[0].pixel_spacing == (0.75, 0.75)        # real spacing, not (1,1)
    cls = p.multiframe_classification()
    assert cls is not None and cls.kind == "spatial_volume" and cls.mpr_eligible


def test_single_frame_series_geometry_is_top_level_and_unchanged(tmp_path):
    """An ordinary single-frame file must keep reading geometry from the
    top-level tags with frame_index None and NO multi-frame classification."""
    pydicom = pytest.importorskip("pydicom")
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    import importlib
    lw = importlib.import_module("modules.viewer.fast.lightweight_2d_pipeline")

    series_dir = tmp_path / "1"
    series_dir.mkdir()
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "MR"
    ds.InstanceNumber = 1
    ds.Rows = 16
    ds.Columns = 16
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.ImagePositionPatient = [1.0, 2.0, 3.0]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.PixelSpacing = [0.6, 0.6]
    ds.PixelData = np.zeros((16, 16), dtype=np.uint16).tobytes()
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.save_as(str(series_dir / "im.dcm"), write_like_original=False)

    p = lw.Lightweight2DPipeline()
    p.open_series(str(series_dir))
    sc = p.slice_count
    sc = sc() if callable(sc) else sc
    assert sc == 1
    assert p._slices[0].frame_index is None
    assert p._slices[0].ipp == (1.0, 2.0, 3.0)
    assert p._slices[0].pixel_spacing == (0.6, 0.6)
    assert p.multiframe_classification() is None


def test_mpr_gate_classify_series_files_only_flags_single_multiframe(tmp_path):
    """The MPR gate helper: block ONLY a single multi-frame file. A standard
    multi-FILE series (or a single-frame file) returns None → MPR proceeds."""
    pytest.importorskip("pydicom")
    from modules.viewer.fast.multiframe_geometry import classify_series_files

    mf = tmp_path / "mf.dcm"
    _make_multiframe_dicom(mf, n_frames=8, rows=16, cols=16,
                           per_frame_ipp=lambda k: (0.0, 0.0, k * 5.0), enhanced_sop=True)
    single = tmp_path / "single.dcm"
    _make_multiframe_dicom(single, n_frames=1, rows=16, cols=16)  # NumberOfFrames=1

    c = classify_series_files([str(mf)])
    assert c is not None and c.kind == "spatial_volume"          # single multi-frame → gated
    assert classify_series_files([str(mf), str(mf)]) is None     # >1 file (standard) → not gated
    assert classify_series_files([str(single)]) is None          # single-frame → not gated
    assert classify_series_files([]) is None


def test_export_frame_instances_carries_per_frame_geometry(tmp_path):
    """The pipeline must export ONE per-frame instance dict (with each frame's
    own IPP/IOP/spacing) so reference lines / sync / overlay — which read
    metadata['instances'] — get real geometry for a single-file multi-frame
    series. Ordinary single-frame series export [] (real per-file instances
    untouched)."""
    pytest.importorskip("pydicom")
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import importlib
    lw = importlib.import_module("modules.viewer.fast.lightweight_2d_pipeline")

    series_dir = tmp_path / "1"
    series_dir.mkdir()
    _make_multiframe_dicom(series_dir / "mf.dcm", n_frames=6, rows=16, cols=16,
                           per_frame_ipp=lambda k: (0.0, 0.0, k * 4.0),
                           pixel_spacing=(0.5, 0.5), enhanced_sop=True)
    # real app path: metadata carries ONE DB instance row (no per-frame geometry)
    meta = {"instances": [{"instance_path": str(series_dir / "mf.dcm")}],
            "series": {"series_number": "1"}}
    p = lw.Lightweight2DPipeline()
    p.open_series(str(series_dir), metadata=meta)
    assert p.is_multiframe_series()
    inst = p.export_frame_instances()
    assert len(inst) == 6
    zs = [round(i["image_position_patient"][2], 3) for i in inst]
    assert zs == [0.0, 4.0, 8.0, 12.0, 16.0, 20.0]          # per-frame + frame order
    assert inst[0]["pixel_spacing"] == [0.5, 0.5]
    assert len({tuple(i["image_position_patient"]) for i in inst}) == 6  # all distinct
    assert [i["frame_index"] for i in inst] == [0, 1, 2, 3, 4, 5]


def test_factory_mirrors_frame_instances_into_metadata():
    """The FAST bridge factory must mirror the pipeline's per-frame geometry into
    metadata['instances'] after open_series (so the DB's single multi-frame row
    is replaced with N per-frame rows for the geometry consumers)."""
    import importlib
    src = importlib.import_module(
        "PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals"
    )
    import inspect
    text = inspect.getsource(src._create_qt_viewer_bridge)
    assert "export_frame_instances()" in text
    assert 'AIPACS_MULTIFRAME_SYNC_INSTANCES' in text
    # bridge gets a SHALLOW COPY with per-frame instances; shared metadata untouched
    assert 'bridge_metadata = dict(metadata)' in text
    assert 'bridge_metadata["instances"] = _frame_instances' in text
    assert 'metadata=bridge_metadata' in text
    # only replaces when the DB list is shorter → never shrinks an expanded list
    assert "_n_existing < len(_frame_instances)" in text


def test_export_frame_instances_empty_for_single_frame(tmp_path):
    pytest.importorskip("pydicom")
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import importlib
    lw = importlib.import_module("modules.viewer.fast.lightweight_2d_pipeline")
    # a fresh pipeline with no series → export is empty (never fabricates)
    assert lw.Lightweight2DPipeline().export_frame_instances() == []


def test_compressed_multiframe_decodes_each_frame(tmp_path):
    """A COMPRESSED multi-frame file must still decode each frame correctly
    (frame-aware). Uses RLE Lossless (built into pydicom, no external plugin)."""
    pydicom = pytest.importorskip("pydicom")
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from pydicom.uid import RLELossless
    import importlib
    lw = importlib.import_module("modules.viewer.fast.lightweight_2d_pipeline")

    # build an uncompressed multi-frame, then RLE-compress it
    src = tmp_path / "raw.dcm"
    _make_multiframe_dicom(src, n_frames=5, rows=16, cols=16)
    ds = pydicom.dcmread(str(src), force=True)
    try:
        ds.compress(RLELossless)
    except Exception as exc:  # pragma: no cover - encoder unavailable in this env
        pytest.skip("RLE encoder unavailable: %s" % exc)
    series_dir = tmp_path / "1"
    series_dir.mkdir()
    ds.save_as(str(series_dir / "rle.dcm"), write_like_original=False)

    # sanity: pydicom decodes 5 distinct frames
    ref = np.asarray(pydicom.dcmread(str(series_dir / "rle.dcm"), force=True).pixel_array)
    assert ref.shape[0] == 5

    cache = lw.get_disk_pixel_cache()
    if hasattr(cache, "clear"):
        cache.clear()
    try:
        p = lw.Lightweight2DPipeline()
        p.open_series(str(series_dir))
        sc = p.slice_count
        sc = sc() if callable(sc) else sc
        assert sc == 5
        for k in range(5):
            arr = p.get_pixel_array(k)
            assert arr is not None
            assert int(arr.min()) == k and int(arr.max()) == k, f"frame {k} decoded wrong"
    finally:
        if hasattr(cache, "clear"):
            cache.clear()


def test_multiframe_frames_do_not_collide_in_the_disk_cache(tmp_path):
    """THE regression this class caused: with a POPULATED disk cache, each frame
    must still return its OWN pixels. Every frame k here is filled with the
    constant k, so a cross-frame cache collision is trivially detectable. Decode
    twice (populate, then read-through-cache) and assert frame k == k both times."""
    pytest.importorskip("pydicom")
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    import importlib
    lw = importlib.import_module("modules.viewer.fast.lightweight_2d_pipeline")

    series_dir = tmp_path / "1"
    series_dir.mkdir()
    n = 8
    _make_multiframe_dicom(series_dir / "mf.dcm", n_frames=n, rows=16, cols=12)

    # isolate the disk cache so we neither read poisoned real entries nor pollute
    cache = lw.get_disk_pixel_cache()
    if hasattr(cache, "clear"):
        cache.clear()
    try:
        p = lw.Lightweight2DPipeline()
        p.open_series(str(series_dir))
        sc = p.slice_count
        assert (sc() if callable(sc) else sc) == n, "each frame should be its own slice"

        for _pass in range(2):  # 1st populates the cache, 2nd reads it back
            for k in range(n):
                arr = p.get_pixel_array(k)
                assert arr is not None
                assert int(arr.min()) == k and int(arr.max()) == k, (
                    f"frame {k} returned frame {int(arr.flat[0])} — disk-cache collision")
    finally:
        if hasattr(cache, "clear"):
            cache.clear()
