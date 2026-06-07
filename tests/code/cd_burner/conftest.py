"""Shared fixtures for CD-burner / Lite-Viewer tests (headless-safe)."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

CT_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.2"          # CT Image Storage
SC_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.7"          # Secondary Capture


def _base_dataset(sop_class: str) -> Dataset:
    sop_uid = generate_uid()
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = sop_class
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = file_meta
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = sop_uid
    ds.PatientName = "TEST^PATIENT"
    ds.PatientID = "PID-CD-001"
    ds.PatientBirthDate = "19700101"
    ds.PatientSex = "O"
    ds.StudyDate = "20260101"
    ds.StudyTime = "120000"
    ds.StudyID = "1"
    ds.AccessionNumber = "ACC1"
    ds.ReferringPhysicianName = ""
    ds.Manufacturer = "AIPACS-TEST"
    return ds


def write_ct_slice(
    folder: Path,
    series_uid: str,
    study_uid: str,
    instance_number: int,
    *,
    photometric: str = "MONOCHROME2",
    raw_fill: int | None = None,
    filename: str | None = None,
    series_number: int = 3,
    series_description: str = "t2_test_series",
    with_window: bool = True,
    size: tuple = (16, 16),
    ipp: tuple | None = None,
    iop: tuple | None = None,
    pixel_spacing: tuple | None = None,
    imager_pixel_spacing: tuple | None = None,
    frame_of_reference: str | None = None,
) -> Path:
    """Write one synthetic uncompressed CT slice; returns its path."""
    ds = _base_dataset(CT_SOP_CLASS)
    ds.Modality = "CT"
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_number
    ds.SeriesDescription = series_description
    ds.StudyDescription = "TEST STUDY"
    ds.InstanceNumber = instance_number

    rows, cols = size
    if raw_fill is None:
        # horizontal gradient 0..4095
        arr = np.tile(
            np.linspace(0, 4095, cols, dtype=np.uint16), (rows, 1)
        )
    else:
        arr = np.full((rows, cols), raw_fill, dtype=np.uint16)

    ds.Rows, ds.Columns = rows, cols
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.RescaleSlope = 1
    ds.RescaleIntercept = -1024
    if with_window:
        ds.WindowCenter = 40
        ds.WindowWidth = 400
    if ipp is not None:
        ds.ImagePositionPatient = list(ipp)
    if iop is not None:
        ds.ImageOrientationPatient = list(iop)
    if pixel_spacing is not None:
        ds.PixelSpacing = list(pixel_spacing)
    if imager_pixel_spacing is not None:
        ds.ImagerPixelSpacing = list(imager_pixel_spacing)
    if frame_of_reference is not None:
        ds.FrameOfReferenceUID = frame_of_reference
    ds.PixelData = arr.tobytes()

    folder.mkdir(parents=True, exist_ok=True)
    name = filename or f"IM{instance_number:04d}.dcm"
    path = folder / name
    ds.save_as(str(path), write_like_original=False)
    return path


def write_rgb_slice(folder: Path, series_uid: str, study_uid: str, instance_number: int = 1) -> Path:
    """Write one synthetic RGB Secondary Capture instance."""
    ds = _base_dataset(SC_SOP_CLASS)
    ds.Modality = "OT"
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = 100
    ds.SeriesDescription = "rgb_doc"
    ds.StudyDescription = "TEST STUDY"
    ds.InstanceNumber = instance_number

    rows, cols = 8, 8
    arr = np.zeros((rows, cols, 3), dtype=np.uint8)
    arr[..., 0] = 200  # red-dominant
    arr[..., 1] = 10
    arr[..., 2] = 30

    ds.Rows, ds.Columns = rows, cols
    ds.SamplesPerPixel = 3
    ds.PhotometricInterpretation = "RGB"
    ds.PlanarConfiguration = 0
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = arr.tobytes()

    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"RGB{instance_number:04d}.dcm"
    ds.save_as(str(path), write_like_original=False)
    return path


@pytest.fixture()
def qapp():
    """Offscreen QGuiApplication for QImage/widget tests."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
