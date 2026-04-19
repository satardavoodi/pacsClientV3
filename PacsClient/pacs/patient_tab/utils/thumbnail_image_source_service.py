from __future__ import annotations

from PySide6.QtGui import QPixmap

from modules.storage.thumbnail_store import ThumbnailStore, make_pixmap_from_bytes  # type: ignore


class ThumbnailImageSourceService:
    """Resolve the sidebar thumbnail image source in one place.

    Source priority:
    1. In-memory/disk-backed `ThumbnailStore`
    2. Explicit thumbnail file path passed by the caller
    """

    @staticmethod
    def _resolve_study_uid(parent_widget) -> str:
        try:
            return str(getattr(parent_widget, "study_uid", "") or "")
        except Exception:
            return ""

    def load_pixmap(self, parent_widget, series_number: str, file_path_thumbnail: str) -> QPixmap:
        pixmap = self._load_from_store(parent_widget, str(series_number))
        if pixmap is not None and not pixmap.isNull():
            return pixmap
        return QPixmap(file_path_thumbnail)

    def _load_from_store(self, parent_widget, series_number: str) -> QPixmap | None:
        try:
            study_uid = self._resolve_study_uid(parent_widget)
            if not study_uid:
                return None
            thumb_bytes = ThumbnailStore.instance().get_bytes(study_uid, str(series_number))
            if not thumb_bytes:
                return None
            return make_pixmap_from_bytes(thumb_bytes)
        except Exception:
            return None