"""Synthetic pixel-level guards; no clinical files or printer devices."""
import numpy as np
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian
from PySide6.QtWidgets import QApplication
from modules.printing.core.models import ViewportState
from modules.printing.render import dicom_renderer as render


@pytest.fixture
def pixels(monkeypatch):
    app = QApplication.instance() or QApplication([])
    def draw(values, photometric="MONOCHROME2", viewport=None, **attrs):
        arr = np.asarray(values, dtype=np.uint8)
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.Rows, ds.Columns = arr.shape[:2]
        ds.SamplesPerPixel = 3 if arr.ndim == 3 else 1
        if arr.ndim == 3:
            ds.PlanarConfiguration = 0
        ds.PhotometricInterpretation = photometric
        ds.BitsAllocated = ds.BitsStored = 8
        ds.HighBit = 7
        ds.PixelRepresentation = 0
        ds.PixelData = arr.tobytes() + (b"\x00" if arr.nbytes % 2 else b"")
        for key, value in attrs.items():
            setattr(ds, key, value)
        monkeypatch.setattr(render, "_safe_dcmread", lambda path: ds)
        result = render.load_dicom_as_pixmap("synthetic-fidelity", viewport)
        assert result is not None
        return result.pixmap.toImage()
    return draw


def test_window_preserves_absolute_gray_levels(pixels):
    image = pixels([[100, 110, 120]], WindowWidth=400, WindowCenter=200)
    assert [image.pixelColor(x, 0).red() for x in range(3)] == [63, 70, 76]


def test_uniform_image_does_not_turn_black(pixels):
    image = pixels([[100, 100]], WindowWidth=400, WindowCenter=200)
    assert image.pixelColor(0, 0).red() == 63


def test_crop_preserves_windowed_gray(pixels):
    image = pixels([[100,110,120,130]] * 4, viewport=ViewportState(400,200,2))
    assert image.pixelColor(0, 0).red() == 70


def test_native_ybr_is_converted_to_rgb(pixels):
    image = pixels([[[76,85,255],[76,85,255]]], "YBR_FULL")
    assert image.pixelColor(0,0).getRgb()[:3] == (254,0,0)


def test_rgb_zoom_uses_same_crop_as_grayscale(pixels):
    image = pixels([[[x*60,0,0] for x in range(4)]] * 4, "RGB", ViewportState(zoom=2))
    assert (image.width(), image.height()) == (2,2)
    assert image.pixelColor(0,0).red() == 60


def test_window_width_one_is_a_threshold(pixels):
    image = pixels([[99,100,101]], WindowWidth=1, WindowCenter=100)
    assert [image.pixelColor(x,0).red() for x in range(3)] == [0,255,255]
