from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QWidget, QListWidget, QListWidgetItem
from PySide6.QtGui import QImage, QColor

from tests.code.education.test_course_importer import temp_env, _write_dicom


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _pixels(path):
    import pydicom
    _write_dicom(path, study_uid="1.2.3", series_uid="1.2.3.1", series_number=1)
    ds = pydicom.dcmread(path)
    ds.PatientName = "Original^Synthetic"
    ds.PatientID = "SYNTHETIC-ID"
    ds.Rows = ds.Columns = 2
    ds.SamplesPerPixel = 1
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelData = bytes([0, 80, 160, 255])
    ds[0x7fe00010].VR = "OB"
    ds.save_as(path)
    return ds


@pytest.mark.parametrize("keep_id", [True, False])
def test_name_change_only_affects_copy_and_keeps_pixels(temp_env, tmp_path, keep_id):
    import pydicom
    from modules.education.dicom_folder_import import import_dicom_folder
    source = tmp_path / "source" / "one.dcm"
    original = _pixels(source)
    before = source.read_bytes()
    result = import_dicom_folder(source.parent, 7, replacement_name="Teaching^Example", keep_patient_id=keep_id)
    copy = pydicom.dcmread(next(Path(result["path"]).rglob("*.dcm")))
    assert source.read_bytes() == before
    assert str(copy.PatientName) == "Teaching^Example"
    assert (str(copy.PatientID) == "SYNTHETIC-ID") == keep_id
    assert copy.PixelData == original.PixelData
    assert copy.file_meta.TransferSyntaxUID == original.file_meta.TransferSyntaxUID
    assert copy.StudyInstanceUID == original.StudyInstanceUID
    assert result["patient_name_changed"] is True


def test_image_and_local_dicom_have_real_previews(app, temp_env, tmp_path):
    from modules.education.authoring_thumbnails import item_preview
    image_path = tmp_path / "synthetic.png"
    image = QImage(20, 20, QImage.Format_RGB32)
    image.fill(QColor("red"))
    image.save(str(image_path))
    preview = item_preview({"content_type": "image", "content_data": {"path": str(image_path)}})
    assert preview.pixelColor(0, 0).red() == 255
    _pixels(tmp_path / "dicom" / "1" / "one.dcm")
    preview = item_preview({"content_type": "dicom", "content_data": {
        "path": str(tmp_path / "dicom"), "study_uid": "1.2.3", "patient_name_changed": True}})
    assert not preview.isNull()
    assert preview.pixelColor(0, 0).red() < 5
    assert preview.pixelColor(preview.width()-1, preview.height()-1).red() > 250


def test_late_preview_does_not_replace_current_item(app):
    from modules.education.authoring_thumbnails import AuthoringThumbnails
    import threading
    owner = QWidget()
    listing = QListWidget(owner)
    listing.addItem(QListWidgetItem("Current"))
    previews = AuthoringThumbnails(owner)
    previews.targets["items"] = (listing, 2, threading.Event())
    image = QImage(4, 4, QImage.Format_RGB32)
    image.fill(QColor("red"))
    previews._ready("items", 1, 0, image)
    assert listing.item(0).icon().isNull()
    previews._ready("items", 2, 0, image)
    assert not listing.item(0).icon().isNull()
    owner.close()


def test_async_preview_reaches_current_row(app, tmp_path):
    from modules.education import authoring_thumbnails as previews
    owner = QWidget()
    listing = QListWidget(owner)
    listing.addItem("Image")
    path = tmp_path / "red.png"
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(QColor("red"))
    image.save(str(path))
    controller = previews.AuthoringThumbnails(owner)
    controller.request("items", listing, [{"content_type": "image", "content_data": {"path": str(path)}}])
    assert previews._pool.waitForDone(5000)
    app.processEvents()
    assert listing.item(0).icon().pixmap(96,64).toImage().pixelColor(0,0).red() == 255
    owner.close()
