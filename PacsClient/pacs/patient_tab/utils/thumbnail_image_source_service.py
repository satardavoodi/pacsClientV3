from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

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
        if disk.isNull() and self._local_placeholder_allowed(parent_widget):
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
            disk = self._placeholder_pixmap(str(series_number))
        return disk

    @staticmethod
    def _local_placeholder_allowed(parent_widget) -> bool:
        caller = str(getattr(parent_widget, '_deferred_caller', '') or '').strip().lower()
        return caller in {'import', 'local'}

    @staticmethod
    def _placeholder_pixmap(series_number: str) -> QPixmap:
        """Return a lightweight Local-safe card when a cached PNG is unavailable."""
        pixmap = QPixmap(160, 120)
        pixmap.fill(QColor('#1f2937'))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor('#3b82f6'))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRoundedRect(2, 2, 156, 116, 8, 8)
        painter.setPen(QColor('#cbd5e1'))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, f"Series {series_number or '?'}")
        painter.end()
        return pixmap

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
