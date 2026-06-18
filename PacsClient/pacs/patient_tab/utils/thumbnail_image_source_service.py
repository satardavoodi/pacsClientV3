from __future__ import annotations

import logging

from PySide6.QtGui import QPixmap

from modules.storage.thumbnail_store import ThumbnailStore, make_pixmap_from_bytes  # type: ignore

logger = logging.getLogger(__name__)


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
            # Served from the shared in-memory ThumbnailStore (warmed from the
            # canonical disk PNG on first access) — the same store the home page
            # uses, so this is a true unified-pipeline reuse. DEBUG: per-series.
            try:
                logger.debug("[THUMB-SRC] ThumbnailLoadedFromMemory series=%s", series_number)
            except Exception:
                pass
            return pixmap
        disk = QPixmap(file_path_thumbnail)
        if not disk.isNull():
            try:
                logger.debug("[THUMB-SRC] ThumbnailLoadedFromDisk series=%s path=%s", series_number, file_path_thumbnail)
            except Exception:
                pass
        if disk.isNull():
            # Neither the in-memory/disk store nor the explicit file yielded a
            # thumbnail — the caller falls back to a placeholder. Log at DEBUG so
            # a genuinely-missing thumbnail is traceable without spamming during
            # normal first-load (many series have no thumbnail yet).
            try:
                logger.debug(
                    "[THUMB-MISS] no store/disk thumbnail series=%s path=%s (placeholder used)",
                    series_number, file_path_thumbnail,
                )
            except Exception:
                pass
        return disk

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