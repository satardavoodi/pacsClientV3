"""Bounded, asynchronous Education previews; never modify clinical thumbnail caches."""
import threading
import copy
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot, QRunnable, QThreadPool, Qt, QSize
from PySide6.QtGui import QImage, QImageReader, QIcon, QPixmap, QPainter, QColor, QFont

_pool = None
SIZE = QSize(96, 64)


def _badge(kind, text=""):
    """A legible document tile rather than a tiny paragraph or generic attachment."""
    labels = {"text": "TEXT", "attachment": "FILE", "slide": "SLIDE",
              "presentation": "PPT", "video": "VIDEO", "audio": "AUDIO"}
    label = labels.get(str(kind).lower(), str(kind).upper())[:8]
    image = QImage(SIZE, QImage.Format_RGB32)
    image.fill(QColor("#203349"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QColor("#73c3ef"))
    painter.drawRoundedRect(33, 6, 29, 30, 3, 3)
    for y in (14, 21, 28):
        painter.drawLine(39, y, 56, y)
    font = QFont()
    font.setPixelSize(13)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#e2e8f0"))
    painter.drawText(image.rect().adjusted(3, 39, -3, -2), Qt.AlignCenter, label)
    painter.end()
    return image


def _cover_image(path):
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 40_000_000:
        return QImage()
    reader.setScaledSize(size.scaled(SIZE, Qt.KeepAspectRatio))
    return reader.read()


def slide_preview(slide, content):
    if slide.get("thumbnail_path"):
        image = _cover_image(slide["thumbnail_path"])
        if not image.isNull():
            return image
    item = next((v for v in content if v["content_type"] in
                 {"image", "dicom", "dicom_study", "dicom_series"}),
                content[0] if content else {"content_type": "slide"})
    return item_preview(item)


def _dicom_image(path):
    """Preview-only first frame, bounded before decode; unsupported objects get a badge."""
    import numpy as np
    import pydicom
    from pydicom.pixel_data_handlers.util import apply_modality_lut, apply_voi_lut, apply_color_lut, convert_color_space
    if Path(path).stat().st_size > 64 * 1024 * 1024:
        return QImage()
    header = pydicom.dcmread(path, stop_before_pixels=True)
    estimate = (int(header.get("Rows", 0)) * int(header.get("Columns", 0)) *
                int(header.get("SamplesPerPixel", 1)) * int(header.get("NumberOfFrames", 1)) *
                max(1, int(header.get("BitsAllocated", 8)) // 8))
    if not 0 < estimate <= 32 * 1024 * 1024:
        return QImage()
    ds = pydicom.dcmread(path)
    array = ds.pixel_array
    if int(ds.get("NumberOfFrames", 1)) > 1:
        array = array[0]
    photo = str(ds.get("PhotometricInterpretation", ""))
    if photo == "PALETTE COLOR":
        array = apply_color_lut(array, ds)
        if array.dtype == np.uint16:
            array = (array / 257).astype(np.uint8)
    elif photo.startswith("YBR"):
        array = convert_color_space(array, photo, "RGB")
    elif photo in {"MONOCHROME1", "MONOCHROME2"}:
        array = apply_voi_lut(apply_modality_lut(array, ds), ds).astype(float)
        lo, hi = float(np.nanmin(array)), float(np.nanmax(array))
        array = np.nan_to_num((array - lo) / max(hi - lo, 1e-12) * 255).clip(0, 255).astype(np.uint8)
        if photo == "MONOCHROME1":
            array = 255 - array
    if array.dtype != np.uint8:
        return QImage()
    array = np.ascontiguousarray(array)
    if array.ndim == 2:
        image = QImage(array.data, array.shape[1], array.shape[0], array.strides[0], QImage.Format_Grayscale8)
    elif array.ndim == 3 and array.shape[2] == 3:
        image = QImage(array.data, array.shape[1], array.shape[0], array.strides[0], QImage.Format_RGB888)
    else:
        return QImage()
    return image.copy().scaled(SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def item_preview(item):
    kind = item.get("content_type", "item")
    data = item.get("content_data") or {}
    try:
        if kind == "image":
            reader = QImageReader(str(data.get("path") or ""))
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                reader.setScaledSize(size.scaled(SIZE, Qt.KeepAspectRatio))
            image = reader.read()
            if not image.isNull():
                return image
        elif kind in {"dicom", "dicom_study", "dicom_series"}:
            from PacsClient.utils.config import THUMBNAIL_PATH, SOURCE_PATH
            uid = str(data.get("study_uid") or "")
            import re
            if uid and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", uid):
                return _badge("DICOM")
            number = data.get("series_number")
            if kind == "dicom" and data.get("path") and number is None:
                local_series = sorted(p.name for p in Path(data["path"]).iterdir() if p.is_dir() and p.name.isdigit())
                if local_series:
                    number = int(local_series[0])
            cache = Path(THUMBNAIL_PATH) / uid
            if uid and not data.get("patient_name_changed"):
                candidates = [cache / f"{int(number)}.png"] if number is not None else sorted(cache.glob("*.png"))
                for candidate in candidates[:1]:
                    if not candidate.is_file():
                        continue
                    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
                    image = ThumbnailImageSourceService.prepare_image(uid, candidate.stem, str(candidate))
                    if not image.isNull():
                        return image.scaled(SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            folder = Path(data["path"]) if data.get("path") else (Path(SOURCE_PATH) / uid if uid else None)
            if folder is not None:
                if number is not None and folder.name != str(number):
                    folder = folder / str(int(number))
                for index, path in enumerate(folder.rglob("*.dcm")):
                    if index >= 8:
                        break
                    try:
                        image = _dicom_image(path)
                    except Exception:
                        continue
                    if not image.isNull():
                        return image
    except Exception:
        pass
    suffix = Path(str(data.get("path") or "")).suffix.lower()
    if suffix in {".ppt", ".pptx", ".ppx", ".pps", ".ppsx", ".odp", ".pptm", ".ppsm"}:
        kind = "presentation"
    elif suffix in {".txt", ".md", ".csv", ".log", ".json", ".xml", ".tsv"}:
        kind = "text"
    elif suffix == ".pdf":
        kind = "pdf"
    elif suffix and kind in {"attachment", "item"}:
        kind = suffix.lstrip(".")
    return _badge(kind)


class _Signals(QObject):
    ready = Signal(str, int, int, QImage)


class _Job(QRunnable):
    def __init__(self, channel, generation, entries, cancel, signals):
        super().__init__()
        self.channel, self.generation, self.entries = channel, generation, entries
        self.cancel, self.signals = cancel, signals

    def run(self):
        for index, entry in enumerate(self.entries):
            if self.cancel.is_set():
                return
            try:
                if self.channel == "slides":
                    from modules.education.course_database import get_content_for_slide
                    content = get_content_for_slide(entry["slide_pk"])
                    image = slide_preview(entry, content)
                else:
                    image = item_preview(entry)
                if not self.cancel.is_set():
                    self.signals.ready.emit(self.channel, self.generation, index, image)
            except Exception:
                continue


class AuthoringThumbnails(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.targets = {}
        self.serial = 0
        self.signals = _Signals()
        self.signals.ready.connect(self._ready)
        targets = self.targets
        self.destroyed.connect(lambda: [target[2].set() for target in targets.values()])

    def invalidate(self):
        for _, _, cancel in self.targets.values():
            cancel.set()
        self.targets.clear()

    def request(self, channel, widget, entries):
        global _pool
        if _pool is None:
            _pool = QThreadPool()
            _pool.setMaxThreadCount(2)
        old = self.targets.get(channel)
        if old:
            old[2].set()
        self.serial += 1
        cancel = threading.Event()
        self.targets[channel] = (widget, self.serial, cancel)
        widget.setIconSize(SIZE)
        for index in range(widget.count()):
            widget.item(index).setIcon(QIcon(QPixmap.fromImage(_badge("..."))))

        _pool.start(_Job(channel, self.serial, copy.deepcopy(entries), cancel, self.signals))

    @Slot(str, int, int, QImage)
    def _ready(self, channel, generation, index, image):
        target = self.targets.get(channel)
        if target and target[1] == generation:
            item = target[0].item(index)
            if item is not None:
                item.setIcon(QIcon(QPixmap.fromImage(image)))
