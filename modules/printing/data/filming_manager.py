"""
modules.printing.data.filming_manager
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Manages saved filming pages (print-preview thumbnails) stored under the
patient's attachment folder.

Layout on disk::

    <attachment_root>/<study_uid>/Filming/
        page_001.png
        page_001.json    ← metadata sidecar
        page_002.png
        page_002.json
        …

``FilmingDataManager`` is a stateless helper — all methods are class methods.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtGui import QPixmap

logger = logging.getLogger(__name__)

_FILMING_SUBDIR = "Filming"
_THUMB_PREFIX = "page_"
_IMG_EXT = ".png"
_META_EXT = ".json"


class FilmingDataManager:
    """Save, load, and delete filming pages."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def save_filming_page(
        cls,
        patient_folder: Path,
        page_number: int,
        pixmap: QPixmap,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Save *pixmap* as PNG plus a JSON sidecar.

        Returns the path of the saved PNG, or ``None`` on failure.
        """
        try:
            filming_dir = cls._ensure_filming_dir(patient_folder)
            stem = f"{_THUMB_PREFIX}{page_number:03d}"
            img_path = filming_dir / f"{stem}{_IMG_EXT}"
            meta_path = filming_dir / f"{stem}{_META_EXT}"

            ok = pixmap.save(str(img_path), "PNG")
            if not ok:
                logger.warning("[FilmingDataManager] pixmap.save failed: %s", img_path)
                return None

            if metadata:
                meta_path.write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            logger.debug("[FilmingDataManager] saved page %d → %s", page_number, img_path)
            return str(img_path)
        except Exception as exc:
            logger.exception("[FilmingDataManager] save_filming_page failed: %s", exc)
            return None

    @classmethod
    def load_filming_pages(cls, patient_folder: Path) -> List[Dict[str, Any]]:
        """Return a sorted list of page-data dicts from the Filming directory.

        Each dict has keys:
            thumbnail_path (str), page_number (int), metadata (dict)
        """
        try:
            filming_dir = patient_folder / _FILMING_SUBDIR
            if not filming_dir.is_dir():
                return []

            pages: List[Dict[str, Any]] = []
            for img_path in sorted(filming_dir.glob(f"{_THUMB_PREFIX}*{_IMG_EXT}")):
                meta_path = img_path.with_suffix(_META_EXT)
                meta: Dict[str, Any] = {}
                if meta_path.is_file():
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    except Exception:
                        pass

                # Derive page number from filename (page_001.png → 1)
                try:
                    page_num = int(img_path.stem.replace(_THUMB_PREFIX, ""))
                except ValueError:
                    page_num = 0

                pages.append(
                    {
                        "thumbnail_path": str(img_path),
                        "page_number": page_num,
                        "metadata": meta,
                    }
                )
            return pages
        except Exception as exc:
            logger.exception("[FilmingDataManager] load_filming_pages failed: %s", exc)
            return []

    @classmethod
    def delete_filming_page(cls, thumbnail_path: str) -> bool:
        """Delete the PNG and its JSON sidecar.  Returns True on success."""
        try:
            img = Path(thumbnail_path)
            if img.is_file():
                img.unlink()
            meta = img.with_suffix(_META_EXT)
            if meta.is_file():
                meta.unlink()
            logger.debug("[FilmingDataManager] deleted %s", img.name)
            return True
        except Exception as exc:
            logger.exception("[FilmingDataManager] delete_filming_page failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @classmethod
    def _ensure_filming_dir(cls, patient_folder: Path) -> Path:
        filming_dir = patient_folder / _FILMING_SUBDIR
        filming_dir.mkdir(parents=True, exist_ok=True)
        return filming_dir
