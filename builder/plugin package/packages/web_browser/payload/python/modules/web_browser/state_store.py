from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from _project_root import PROJECT_ROOT
from PacsClient.utils.data_paths import (
    BROWSER_DOWNLOADS_DIR,
    BROWSER_PROFILE_DIR,
    BROWSER_SAVED_PAGES_DIR,
    BROWSER_SCREENSHOTS_DIR,
    BROWSER_STATE_DIR,
)

logger = logging.getLogger(__name__)


class BrowserStateStore:
    """Persistence helper for browser favorites, history, and saved pages."""

    MAX_PAGE_HISTORY = 300
    MAX_DOWNLOAD_HISTORY = 200
    MAX_SAVED_PAGES = 100
    MAX_SAVED_ITEMS = 400

    def __init__(
        self,
        root_dir: Path | None = None,
        profile_dir: Path | None = None,
        downloads_dir: Path | None = None,
        saved_pages_dir: Path | None = None,
        screenshots_dir: Path | None = None,
        legacy_root: Path | None = None,
    ) -> None:
        self.root_dir = Path(root_dir or BROWSER_STATE_DIR)
        self.profile_dir = Path(profile_dir or BROWSER_PROFILE_DIR)
        self.downloads_dir = Path(downloads_dir or BROWSER_DOWNLOADS_DIR)
        self.saved_pages_dir = Path(saved_pages_dir or BROWSER_SAVED_PAGES_DIR)
        self.screenshots_dir = Path(screenshots_dir or BROWSER_SCREENSHOTS_DIR)
        self.legacy_root = Path(legacy_root or PROJECT_ROOT)

        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.saved_pages_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        self.favorites_file = self.root_dir / "favorites.json"
        self.page_history_file = self.root_dir / "page_history.json"
        self.download_history_file = self.root_dir / "download_history.json"
        self.saved_pages_file = self.root_dir / "saved_pages.json"
        self.saved_items_file = self.root_dir / "saved_items.json"

    def load_favorites(self) -> dict[str, dict[str, Any]]:
        data = self._load_json(
            self.favorites_file,
            {},
            legacy_files=["browser_bookmarks.json"],
        )
        return data if isinstance(data, dict) else {}

    def save_favorites(self, favorites: dict[str, dict[str, Any]]) -> None:
        self._save_json(self.favorites_file, favorites)

    def load_page_history(self) -> list[dict[str, Any]]:
        data = self._load_json(self.page_history_file, [])
        return self._trim_list(data, self.MAX_PAGE_HISTORY)

    def save_page_history(self, entries: list[dict[str, Any]]) -> None:
        self._save_json(
            self.page_history_file,
            self._trim_list(entries, self.MAX_PAGE_HISTORY),
        )

    def load_download_history(self) -> list[dict[str, Any]]:
        data = self._load_json(
            self.download_history_file,
            [],
            legacy_files=["browser_download_history.json"],
        )
        return self._trim_list(data, self.MAX_DOWNLOAD_HISTORY)

    def save_download_history(self, entries: list[dict[str, Any]]) -> None:
        self._save_json(
            self.download_history_file,
            self._trim_list(entries, self.MAX_DOWNLOAD_HISTORY),
        )

    def load_saved_pages(self) -> list[dict[str, Any]]:
        data = self._load_json(self.saved_pages_file, [])
        return self._trim_list(data, self.MAX_SAVED_PAGES)

    def save_saved_pages(self, entries: list[dict[str, Any]]) -> None:
        self._save_json(
            self.saved_pages_file,
            self._trim_list(entries, self.MAX_SAVED_PAGES),
        )

    def load_saved_items(self) -> list[dict[str, Any]]:
        data = self._load_json(self.saved_items_file, None)
        if isinstance(data, list):
            return self._trim_list(data, self.MAX_SAVED_ITEMS)

        migrated = []
        for entry in self.load_saved_pages():
            migrated.append(
                {
                    "item_type": "page",
                    "title": entry.get("title") or entry.get("url", "Saved Page"),
                    "url": entry.get("url", ""),
                    "path": entry.get("save_path", ""),
                    "created_at": entry.get("saved_at", ""),
                }
            )
        for entry in self.load_download_history():
            migrated.append(
                {
                    "item_type": "download",
                    "title": entry.get("filename", "Download"),
                    "url": entry.get("url", ""),
                    "path": entry.get("save_path", ""),
                    "created_at": entry.get("timestamp", ""),
                }
            )
        migrated = self._trim_list(migrated, self.MAX_SAVED_ITEMS)
        if migrated:
            self.save_saved_items(migrated)
        return migrated

    def save_saved_items(self, entries: list[dict[str, Any]]) -> None:
        self._save_json(
            self.saved_items_file,
            self._trim_list(entries, self.MAX_SAVED_ITEMS),
        )

    def _load_json(
        self,
        path: Path,
        default: Any,
        legacy_files: list[str] | None = None,
    ) -> Any:
        if path.exists():
            return self._read_json(path, default)

        for legacy_name in legacy_files or []:
            legacy_path = self.legacy_root / legacy_name
            if not legacy_path.exists():
                continue
            payload = self._read_json(legacy_path, default)
            self._save_json(path, payload)
            return payload

        return default

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception as exc:
            logger.warning("Failed to read browser state %s: %s", path, exc)
            return default

    def _save_json(self, path: Path, payload: Any) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to write browser state %s: %s", path, exc)

    @staticmethod
    def _trim_list(entries: Any, limit: int) -> list[dict[str, Any]]:
        if not isinstance(entries, list):
            return []
        return [entry for entry in entries if isinstance(entry, dict)][:limit]
