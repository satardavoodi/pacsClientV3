"""Owned background tasks for educational assets and presentation preflight."""
from pathlib import Path

from PySide6.QtCore import QThread


class CourseAssetCopyTask(QThread):
    """Copy away from Qt's GUI thread; owner retains task until finished."""

    def __init__(self, source, course_pk, parent=None):
        super().__init__(parent)
        self.source = source
        self.course_pk = course_pk
        self.result = None
        self.error = False

    def run(self):
        from modules.education.course_database import save_course_asset
        try:
            self.result = save_course_asset(self.source, self.course_pk)
        except Exception:
            self.error = True


def presentation_issues(course):
    """Check saved content/availability; does not certify clinical or pixel safety.

    Filesystem checks belong on a worker. Messages contain positions, not paths or
    clinical identifiers. No files are opened in external applications here.
    """
    issues = []
    slides = course.get("slides") or []
    if not slides:
        return ["The course has no slides."]
    for index, slide in enumerate(slides, 1):
        content = slide.get("content") or []
        if not content:
            issues.append(f"Slide {index}: add at least one content item.")
        for number, item in enumerate(content, 1):
            label = f"Slide {index}, item {number}"
            data = item.get("content_data")
            if not isinstance(data, dict):
                issues.append(f"{label}: invalid content data.")
                continue
            kind = item.get("content_type")
            if kind == "text":
                from modules.education.document_preview import TEXT_SUFFIXES
                text_path = str(data.get("path") or "")
                if text_path and Path(text_path).suffix.lower() in TEXT_SUFFIXES:
                    if not Path(text_path).is_file():
                        issues.append(f"{label}: the text file is unavailable.")
                elif not str(data.get("text") or "").strip():
                    issues.append(f"{label}: teaching text is empty.")
            elif kind in {"dicom_study", "dicom_series"}:
                if not data.get("study_uid"):
                    issues.append(f"{label}: study reference is missing.")
                else:
                    from PacsClient.pacs.patient_tab.utils import get_study_source_path
                    folder, _ = get_study_source_path(str(data["study_uid"]))
                    if not folder or not Path(folder).is_dir():
                        issues.append(f"{label}: DICOM study is not available locally.")
                if kind == "dicom_series" and data.get("series_number") is None:
                    issues.append(f"{label}: series reference is missing.")
            elif kind in {"image", "video", "audio", "pdf", "dicom", "document", "attachment", "presentation", "archive", "other"}:
                path = str(data.get("path") or "").strip()
                exists = bool(path) and (Path(path).is_dir() if kind == "dicom" else Path(path).is_file())
                if not exists:
                    issues.append(f"{label}: the source file or folder is unavailable.")
                elif kind in {"document", "attachment", "presentation", "archive", "other"} and Path(path).suffix.lower() not in {".docx", ".txt", ".md", ".csv", ".tsv", ".log", ".json", ".xml"}:
                    from modules.education.presentation_conversion import PRESENTATION_SUFFIXES, find_libreoffice
                    if Path(path).suffix.lower() in PRESENTATION_SUFFIXES and find_libreoffice():
                        issues.append(f"{label}: static PDF preview; verify slide layout before presenting. Animations require the original application.")
                    else:
                        issues.append(f"{label}: requires an external application; verify it before presenting.")
            else:
                issues.append(f"{label}: unsupported content type.")
    return issues


class CoursePreflightTask(QThread):
    def __init__(self, course, parent=None):
        super().__init__(parent)
        self.course = course
        self.issues = []

    def run(self):
        try:
            self.issues = presentation_issues(self.course)
        except Exception:
            self.issues = ["Could not complete the local resource check. Verify the course before presenting."]


class SlideThumbnailTask(QThread):
    """Normalize a chosen cover to a bounded PNG and persist it off the GUI thread."""

    def __init__(self, source, course_pk, slide_pk, parent=None):
        super().__init__(parent)
        self.source, self.course_pk, self.slide_pk = source, course_pk, slide_pk
        self.error = False

    def run(self):
        import uuid
        from PySide6.QtCore import QSize, Qt
        from PySide6.QtGui import QImageReader
        from modules.education.course_database import update_slide
        from PacsClient.utils.config import EDUCATION_STORAGE_PATH
        destination = None
        try:
            stored = ""
            if self.source:
                source = Path(self.source)
                if source.stat().st_size > 32 * 1024 * 1024:
                    raise ValueError("Image too large")
                reader = QImageReader(str(source))
                reader.setAutoTransform(True)
                size = reader.size()
                if not size.isValid() or size.width() * size.height() > 40_000_000:
                    raise ValueError("Invalid image dimensions")
                reader.setScaledSize(size.scaled(QSize(480, 320), Qt.KeepAspectRatio))
                image = reader.read()
                if image.isNull():
                    raise ValueError("Unsupported image")
                folder = Path(EDUCATION_STORAGE_PATH) / f"course_{self.course_pk}" / "assets"
                folder.mkdir(parents=True, exist_ok=True)
                destination = folder / f"slide-cover-{uuid.uuid4().hex}.png"
                if not image.save(str(destination), "PNG"):
                    raise ValueError("Image could not be saved")
                stored = str(destination)
            update_slide(self.slide_pk, thumbnail_path=stored)
        except Exception:
            self.error = True
            if destination is not None:
                destination.unlink(missing_ok=True)
