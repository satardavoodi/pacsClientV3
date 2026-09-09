"""Synthetic guards for explicit axial-plane identity on sagittal evidence."""

from dataclasses import replace
import json
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from modules.ai_imaging.eagle_eye_lumbar import focus_evidence
from modules.ai_imaging.eagle_eye_lumbar.axial_locator import draw_locator, plane_segment
from modules.ai_imaging.evidence_core import DicomSlice, EvidenceError, SeriesVolume
from test_eagle_eye_focused_v3 import _SCREENING, _axial_slice_stack, _package
from test_eagle_eye_parasagittal import MODE, _prepare, _sagittal_volume


REFERENCE = "1.2.826.0.1.3680043.10.543.910"


def test_sagittal_supplement_reports_plane_link_availability(tmp_path, monkeypatch):
    result, manifest = _prepare(tmp_path, monkeypatch, MODE)
    supplement = manifest["parasagittal_supplements"][0]
    # A level title on a multi-level crop is not a visible plane correspondence.
    # Legacy sources without a shared DICOM reference must not invent a link.
    assert "axial_locator" in supplement
    assert supplement["axial_locator"]["status"] == "unavailable"
    assert supplement["axial_locator"]["reason"] == "frame_of_reference_unverified"
    assert "axial_locator_unavailable:focus-01" in manifest["warnings"]
    assert "adjacent levels" in result.header


def _planes(angle=0.0, reverse=False):
    theta = np.deg2rad(angle)
    volume = SeriesVolume(
        pixels=np.zeros((9, 140, 180), dtype=np.float32),
        origin=(32.0 if reverse else 0.0, 0.0, 100.0),
        spacing=(0.7, 1.2, 4.0),
        direction=(0, 0, -1 if reverse else 1, 1, 0, 0, 0, -1, 0),
        plane="sagittal", frame_of_reference_uid=REFERENCE, source_geometry_verified=True,
    )
    axial = DicomSlice(
        pixels=np.zeros((200, 300), dtype=np.float32),
        position_lps=(-80.0, -20.0, 40.0),
        orientation_lps=(1, 0, 0, 0, np.cos(theta), np.sin(theta)),
        pixel_spacing=(1.3, 0.8), source_ordinal=9,
        frame_of_reference_uid=REFERENCE,
    )
    return volume, axial


@pytest.mark.parametrize("angle", [-25.0, 0.0, 30.0])
@pytest.mark.parametrize("reverse", [False, True])
def test_plane_link_round_trips_oblique_anisotropic_and_reversed_geometry(angle, reverse):
    volume, axial = _planes(angle, reverse)
    segment = plane_segment(volume, 4, axial, (10, 10, 160, 125))
    normal = np.cross(axial.orientation_lps[:3], axial.orientation_lps[3:])
    for x, y in segment:
        assert 10 <= x <= 159 and 10 <= y <= 124
        patient = np.asarray(volume.continuous_index_to_patient((x, y, 4)))
        assert float(normal @ (patient - axial.position_lps)) == pytest.approx(0, abs=1e-8)
        assert patient[0] == pytest.approx(16)
    if angle == 0:
        assert segment[0][1] == pytest.approx(50)
        assert segment[1][1] == pytest.approx(50)


def test_plane_segment_respects_axial_fov_not_infinite_plane_extension():
    volume, axial = _planes()
    axial = replace(axial, pixels=np.zeros((30, 300)), position_lps=(-80, 35, 40))
    segment = plane_segment(volume, 4, axial, (0, 0, 180, 140))
    y_patient = sorted(volume.continuous_index_to_patient((*point, 4))[1] for point in segment)
    assert y_patient == pytest.approx([35, 35 + 29 * 1.3])


@pytest.mark.parametrize("bad_uid", ["", "1.2.3.4"])
def test_foreign_or_missing_reference_cannot_generate_a_plane_link(bad_uid):
    volume, axial = _planes()
    with pytest.raises(EvidenceError, match="frame_of_reference_unverified"):
        plane_segment(volume, 4, replace(axial, frame_of_reference_uid=bad_uid), (0, 0, 180, 140))


@pytest.mark.parametrize("fault", ["parallel", "outside", "nonfinite", "singular"])
def test_invalid_geometry_does_not_invent_a_center_line(fault):
    volume, axial = _planes()
    if fault == "parallel":
        axial = replace(axial, orientation_lps=(0, 1, 0, 0, 0, 1))
    elif fault == "outside":
        axial = replace(axial, position_lps=(-80, -20, 1000))
    elif fault == "nonfinite":
        volume = replace(volume, origin=(float("nan"), 0, 0))
    else:
        volume = replace(volume, direction=(0,) * 9)
    with pytest.raises(EvidenceError):
        plane_segment(volume, 4, axial, (0, 0, 180, 140))


def _prepared_with_reference(tmp_path, monkeypatch, reference=REFERENCE):
    volume = replace(_sagittal_volume(), frame_of_reference_uid=reference, source_geometry_verified=True)
    stack = _axial_slice_stack()
    stack = replace(stack, slices=tuple(replace(s, frame_of_reference_uid=REFERENCE) for s in stack.slices))
    monkeypatch.setattr(focus_evidence, "load_series_volume", lambda _: volume)
    monkeypatch.setattr(focus_evidence, "load_dicom_slice_stack", lambda _: stack)
    package = _package(tmp_path)
    structured = json.loads(_SCREENING.split("```json")[1].split("```")[0])
    return focus_evidence.prepare_verification_package(package, _SCREENING, structured, None, mode=MODE)


def test_locator_uses_only_spare_cell_keeps_clean_pixels_and_budget(tmp_path, monkeypatch):
    linked = _prepared_with_reference(tmp_path / "linked", monkeypatch)
    unlinked = _prepared_with_reference(tmp_path / "unlinked", monkeypatch, "")
    assert len(linked.images) == len(unlinked.images)
    for old, new in zip(unlinked.images[:-1], linked.images[:-1]):
        assert old.path.read_bytes() == new.path.read_bytes()
    record = linked.evidence_audit["parasagittal_supplements"][0]
    audit = record["axial_locator"]
    assert audit["status"] == "included"
    assert audit["anatomical_numbering_verified"] is False
    assert audit["lesion_correspondence_verified"] is False
    assert audit["anchor_capture_frame"] == 3
    # The capture sequence here is reversed relative to source ordinals.
    assert [p["capture_frame"] for p in audit["planes"]] == [1, 2, 3, 4, 5]
    with Image.open(linked.images[-1].path) as new, Image.open(unlinked.images[-1].path) as old:
        assert new.size == old.size
        before, after = np.asarray(old), np.asarray(new)
        x, y = audit["cell_origin_xy"]
        width, height = audit["tile_size"]
        mask = np.ones(before.shape[:2], dtype=bool)
        mask[y:y + height, x:x + width] = False
        assert np.array_equal(before[mask], after[mask])
        assert not np.array_equal(before[~mask], after[~mask])
    assert linked.evidence_audit["budget"]["pixel_count"] == unlinked.evidence_audit["budget"]["pixel_count"]
    assert REFERENCE not in json.dumps(linked.evidence_audit)
    assert "LOCATOR ONLY" in linked.images[-1].caption
    assert "clean tiles" in linked.images[-1].caption
    assert record["tile_count"] == 7  # The locator is a duplicate, not an eighth source slice.


def test_partial_locator_identifies_missing_plane_without_suppressing_valid_lines():
    volume, axial = _planes()
    canvas = Image.new("RGB", (384, 304), "black")
    audit = draw_locator(canvas, volume, 5, (0, 0, 180, 140), np.ones((140, 180)),
                         [(17, axial), (18, replace(axial, position_lps=(-80, -20, 1000)))],
                         17, (0, 0), (384, 304))
    assert audit["status"] == "partial"
    assert [p["capture_frame"] for p in audit["planes"]] == [17]
    assert [p["capture_frame"] for p in audit["omitted_planes"]] == [18]


@pytest.mark.parametrize("references", [(REFERENCE,) * 3, ("",) * 3, (REFERENCE, "1.2.3", REFERENCE)])
def test_dicom_loaders_preserve_reference_identity_without_guessing(tmp_path, monkeypatch, references):
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage
    from modules.ai_imaging.evidence_core import volume as loader

    files = []
    for index, reference in enumerate(references):
        path = tmp_path / f"synthetic_{index}.dcm"
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = MRImageStorage
        meta.MediaStorageSOPInstanceUID = f"{REFERENCE}.{index + 1}"
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
        ds.is_little_endian, ds.is_implicit_VR = True, False
        ds.SOPClassUID, ds.SOPInstanceUID = MRImageStorage, meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID = REFERENCE + ".20", REFERENCE + ".21"
        ds.Modality = "MR"
        ds.Rows, ds.Columns = 16, 20
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 0
        ds.ImagePositionPatient = [0, 0, index * 2]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.PixelSpacing, ds.SliceThickness = [1.2, 0.8], 2
        ds.InstanceNumber = 10 - index
        if reference:
            ds.FrameOfReferenceUID = reference
        ds.PixelData = (np.arange(320, dtype=np.uint16).reshape(16, 20) + index).tobytes()
        ds.save_as(str(path), write_like_original=False)
        files.append(str(path))
    monkeypatch.setattr(loader, "_dicom_files", lambda _: files)
    candidate = SimpleNamespace(plane="axial")
    stack = loader.load_dicom_slice_stack(candidate)
    volume = loader.load_series_volume(candidate)
    assert [s.frame_of_reference_uid for s in stack.slices] == list(references)
    assert volume.frame_of_reference_uid == (references[0] if len(set(references)) == 1 else "")
    assert volume.spacing == pytest.approx((0.8, 1.2, 2))
    assert volume.source_geometry_verified is True
    for index, image_slice in enumerate(stack.slices):
        assert np.array_equal(volume.pixels[index], image_slice.pixels)
        assert volume.continuous_index_to_patient((0, 0, index)) == pytest.approx(image_slice.position_lps)
    assert REFERENCE not in repr(volume)
    assert all(REFERENCE not in repr(s) for s in stack.slices)


@pytest.mark.parametrize("fault", ["position", "orientation", "spacing", "missing", "depth"])
def test_nonuniform_or_unverified_source_cannot_claim_a_valid_volume_affine(fault):
    from modules.ai_imaging.evidence_core.volume import _volume_matches_source_planes
    reader = SimpleNamespace(GetMetaData=lambda index, key: {
        "0020|0032": "0\\0\\" + str(index * 2 + (0.8 if fault == "position" else 0)),
        "0020|0037": "1\\0\\0\\0\\1\\0" if fault != "orientation" else "1\\0\\0\\0\\0\\1",
        "0028|0030": "1.2\\0.8" if fault != "spacing" else "0.8\\1.2",
    }[key])
    if fault == "missing":
        def missing(*args):
            raise RuntimeError("Missing synthetic metadata")
        reader.GetMetaData = missing
    image = SimpleNamespace(
        GetSize=lambda: (20, 16, 4 if fault == "depth" else 3),
        GetDirection=lambda: (1, 0, 0, 0, 1, 0, 0, 0, 1),
        GetSpacing=lambda: (0.8, 1.2, 2),
        TransformIndexToPhysicalPoint=lambda index: (0, 0, index[2] * 2),
    )
    assert _volume_matches_source_planes(reader, image, 3) is False


def test_unverified_source_geometry_leaves_locator_cell_unchanged():
    volume, axial = _planes()
    canvas = Image.new("RGB", (384, 304), "black")
    before = canvas.tobytes()
    audit = draw_locator(canvas, replace(volume, source_geometry_verified=False), 5,
                         (0, 0, 180, 140), np.ones((140, 180)), [(17, axial)],
                         17, (0, 0), (384, 304))
    assert audit["status"] == "unavailable"
    assert audit["reason"] == "source_geometry_unverified"
    assert canvas.tobytes() == before


@pytest.mark.parametrize("value", ["", ".1.2", "1..2", "1.2.", "abc", "1" * 65])
def test_reference_identity_is_bounded_and_never_repaired(value):
    from modules.ai_imaging.evidence_core.volume import _safe_reference_uid
    assert _safe_reference_uid(value) == ""
    assert _safe_reference_uid(REFERENCE) == REFERENCE


def test_oversized_geometry_metadata_fails_closed_without_splitting_it():
    from modules.ai_imaging.evidence_core.volume import _volume_matches_source_planes
    reader = SimpleNamespace(GetMetaData=lambda index, key: "1" * 257)
    image = SimpleNamespace(GetSize=lambda: (20, 16, 1),
                            GetDirection=lambda: (1, 0, 0, 0, 1, 0, 0, 0, 1),
                            GetSpacing=lambda: (1, 1, 1),
                            TransformIndexToPhysicalPoint=lambda index: (0, 0, 0))
    assert _volume_matches_source_planes(reader, image, 1) is False
