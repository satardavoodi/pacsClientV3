"""Regression guards for server-collapsed DICOM multi-value text elements.

The socket server has emitted standard VM>1 elements such as Image Type as one
literal Python-list string. Strict consumers then cannot classify magnitude and
phase series. These fixtures are synthetic and contain no clinical data.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from pydicom import dcmread
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.tag import Tag
from pydicom.uid import ImplicitVRLittleEndian, MRImageStorage, generate_uid

from PacsClient.utils.dicom_vm_normalization import (
    normalize_collapsed_multivalue_dataset,
    normalize_dicom_bytes,
)
from modules.dicom_media.dicomdir import DicomDirBuilder


pytestmark = [
    pytest.mark.filterwarnings("ignore:.*Invalid value for VR CS.*"),
    pytest.mark.filterwarnings("ignore:The 'DicomDir' class is deprecated.*"),
]


_COLLAPSED_IMAGE_TYPE = "['ORIGINAL', 'PRIMARY', 'P', 'RETRO', 'DIS2D']"


def _synthetic_flow_dataset(*, collapsed: bool = True) -> FileDataset:
    sop_uid = generate_uid()
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = MRImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ImplicitVRLittleEndian

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = True
    ds.SOPClassUID = MRImageStorage
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.FrameOfReferenceUID = generate_uid()
    ds.PatientName = "SYNTHETIC"
    ds.PatientID = "SYNTHETIC"
    ds.StudyDate = "20260901"
    ds.StudyTime = "120000"
    ds.StudyID = "1"
    ds.AccessionNumber = ""
    ds.Modality = "MR"
    ds.SeriesNumber = "43"
    ds.InstanceNumber = "1"

    if collapsed:
        ds.ImageType = _COLLAPSED_IMAGE_TYPE
        ds.ScanningSequence = "['GR', 'IR']"
        ds.SequenceVariant = "['SK', 'SP', 'OSP']"
        ds.ScanOptions = "['PFP', 'CT']"
    else:
        ds.ImageType = ["ORIGINAL", "PRIMARY", "P", "RETRO", "DIS2D"]
        ds.ScanningSequence = ["GR", "IR"]
        ds.SequenceVariant = ["SK", "SP", "OSP"]
        ds.ScanOptions = ["PFP", "CT"]

    # A VM=1 standard element and a private element that merely look like list
    # literals must remain untouched.
    ds.SeriesDescription = "['LEGITIMATE VM ONE TEXT']"
    ds.add_new((0x0019, 0x0010), "LO", "SYNTHETIC_PRIVATE")
    ds.add_new((0x0019, 0x1010), "LO", "['PRIVATE', 'TEXT']")

    nested = Dataset()
    nested.ImageType = _COLLAPSED_IMAGE_TYPE if collapsed else [
        "ORIGINAL",
        "PRIMARY",
        "P",
        "RETRO",
        "DIS2D",
    ]
    ds.SourceImageSequence = [nested]

    pixels = np.array([[0, 2048], [4094, 1024]], dtype=np.uint16)
    ds.Rows = 2
    ds.Columns = 2
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.PixelData = pixels.tobytes()
    return ds


def _serialize(ds: FileDataset) -> bytes:
    output = BytesIO()
    ds.save_as(output, write_like_original=False)
    return output.getvalue()


def test_dataset_normalization_restores_only_standard_multivalue_text():
    ds = _synthetic_flow_dataset()

    normalized_tags = normalize_collapsed_multivalue_dataset(ds)

    assert Tag("ImageType") in normalized_tags
    assert Tag("ScanningSequence") in normalized_tags
    assert Tag("SequenceVariant") in normalized_tags
    assert Tag("ScanOptions") in normalized_tags
    assert list(ds.ImageType) == ["ORIGINAL", "PRIMARY", "P", "RETRO", "DIS2D"]
    assert ds["ImageType"].VM == 5
    assert list(ds.SourceImageSequence[0].ImageType) == [
        "ORIGINAL",
        "PRIMARY",
        "P",
        "RETRO",
        "DIS2D",
    ]
    assert ds.SeriesDescription == "['LEGITIMATE VM ONE TEXT']"
    assert ds[(0x0019, 0x1010)].value == "['PRIVATE', 'TEXT']"


def test_byte_normalization_preserves_pixels_identity_and_transfer_syntax():
    original = _synthetic_flow_dataset()
    payload = _serialize(original)

    result = normalize_dicom_bytes(payload)

    assert result.error_type is None
    assert result.changed is True
    repaired = dcmread(BytesIO(result.payload), force=True)
    assert repaired.file_meta.TransferSyntaxUID == ImplicitVRLittleEndian
    assert repaired.SOPInstanceUID == original.SOPInstanceUID
    assert repaired.StudyInstanceUID == original.StudyInstanceUID
    assert repaired.SeriesInstanceUID == original.SeriesInstanceUID
    assert repaired.FrameOfReferenceUID == original.FrameOfReferenceUID
    assert bytes(repaired.PixelData) == bytes(original.PixelData)
    assert repaired.pixel_array.tolist() == original.pixel_array.tolist()
    assert repaired["ImageType"].VM == 5
    assert repaired.ImageType[2] == "P"


def test_clean_and_unreadable_payloads_are_preserved_byte_for_byte():
    clean_payload = _serialize(_synthetic_flow_dataset(collapsed=False))

    clean = normalize_dicom_bytes(clean_payload)
    unreadable = normalize_dicom_bytes(b"not a DICOM payload")

    assert clean.changed is False
    assert clean.error_type is None
    assert clean.payload is clean_payload
    assert unreadable.changed is False
    assert unreadable.error_type is not None
    assert unreadable.payload == b"not a DICOM payload"


def test_socket_ingestion_normalizes_before_the_atomic_write():
    from modules.download_manager.network.socket_client import (
        _normalize_received_dicom_bytes,
    )

    payload = _serialize(_synthetic_flow_dataset())
    repaired = dcmread(BytesIO(_normalize_received_dicom_bytes(payload)), force=True)
    assert repaired["ImageType"].VM == 5
    assert repaired.ImageType[2] == "P"

    source = (
        Path(__file__).resolve().parents[3]
        / "modules"
        / "download_manager"
        / "network"
        / "socket_client.py"
    ).read_text(encoding="utf-8")
    normalize_call = "dicom_bytes = _normalize_received_dicom_bytes(dicom_bytes)"
    assert normalize_call in source
    assert source.index("gzip.decompress(dicom_bytes)") < source.index(normalize_call)
    assert source.index(normalize_call) < source.index("with open(tmp_path, 'wb') as f:")


def test_dicomdir_export_repairs_copy_without_mutating_local_source(tmp_path: Path):
    study = tmp_path / "study"
    study.mkdir()
    source_path = study / "IM000001.dcm"
    source_path.write_bytes(_serialize(_synthetic_flow_dataset()))
    source_before = source_path.read_bytes()
    output = tmp_path / "media"

    builder = DicomDirBuilder()
    assert builder.build_from_study_folders([str(study)], str(output)) is True

    assert source_path.read_bytes() == source_before
    assert builder.last_stats["vm_instances_normalized"] == 1
    assert builder.last_stats["vm_elements_normalized"] >= 4

    from pydicom.fileset import FileSet

    fileset = FileSet(str(output / "DICOMDIR"))
    exported = dcmread(str(next(iter(fileset)).path), force=True)
    assert exported["ImageType"].VM == 5
    assert exported.ImageType[2] == "P"
    assert bytes(exported.PixelData) == bytes(_synthetic_flow_dataset().PixelData)
