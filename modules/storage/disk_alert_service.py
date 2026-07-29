from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Set

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from modules.storage.local_storage_cleanup_manager import LocalStorageCleanupManager

logger = logging.getLogger(__name__)

_PREFS_FILENAME = "disk_alert_prefs.json"
_SUPPRESS_KEY = "suppress_disk_space_alert"
_DONT_SHOW_AGAIN_LABEL = "Don't show again"


def _prefs_path() -> Path:
    from PacsClient.utils.data_paths import USER_DATA_ROOT

    return Path(USER_DATA_ROOT) / "config" / _PREFS_FILENAME


def is_disk_space_alert_suppressed() -> bool:
    """True when the user chose not to see disk-space alerts again."""
    try:
        path = _prefs_path()
        if not path.exists():
            return False
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return False
        return bool(raw.get(_SUPPRESS_KEY))
    except Exception:
        logger.debug("disk alert prefs read failed; treating as not suppressed", exc_info=True)
        return False


def set_disk_space_alert_suppressed(suppressed: bool = True) -> bool:
    """Persist the user's choice to hide future disk-space alerts."""
    try:
        path = _prefs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {_SUPPRESS_KEY: bool(suppressed)}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception:
        logger.warning("failed to persist disk alert suppression", exc_info=True)
        return False


def disk_space_alert_enabled() -> bool:
    """Global gate: env kill-switch + user suppression preference."""
    if os.getenv("AIPACS_DISK_SPACE_ALERT", "").strip() == "0":
        return False
    return not is_disk_space_alert_suppressed()


class DiskUsageAlertService(QObject):
    """Reusable global disk usage threshold alert service."""

    def __init__(
        self,
        parent_widget: QWidget | None = None,
        threshold_percent: float = 90.0,
        interval_ms: int = 5 * 60 * 1000,
    ):
        super().__init__(parent_widget)
        self.parent_widget = parent_widget
        self.threshold_percent = float(threshold_percent)
        self.interval_ms = int(interval_ms)
        self._alerted_high_usage_drives: Set[str] = set()
        self._timer = QTimer(self)
        self._timer.setInterval(self.interval_ms)
        self._timer.timeout.connect(self.check_now)

    def start(self, initial_delay_ms: int = 2000):
        if not disk_space_alert_enabled():
            return
        QTimer.singleShot(int(initial_delay_ms), self.check_now)
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _show_disk_alert(self, title: str, message: str):
        if is_disk_space_alert_suppressed():
            self.stop()
            return

        parent_pos = None
        parent_size = None
        if self.parent_widget is not None:
            parent_pos = self.parent_widget.pos()
            parent_size = self.parent_widget.size()

        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setStandardButtons(QMessageBox.Ok)
        dont_show_btn = msg_box.addButton(
            _DONT_SHOW_AGAIN_LABEL,
            QMessageBox.ButtonRole.ActionRole,
        )
        msg_box.setWindowModality(Qt.ApplicationModal)

        if self.parent_widget is not None and self.parent_widget.isVisible():
            parent_frame = self.parent_widget.frameGeometry()
            msg_box.adjustSize()
            msg_frame = msg_box.frameGeometry()
            msg_frame.moveCenter(parent_frame.center())
            msg_box.move(msg_frame.topLeft())

        msg_box.exec()

        if msg_box.clickedButton() is dont_show_btn:
            set_disk_space_alert_suppressed(True)
            self.stop()

        if (
            self.parent_widget is not None
            and self.parent_widget.isVisible()
            and parent_pos is not None
            and parent_size is not None
        ):
            if self.parent_widget.pos() != parent_pos:
                self.parent_widget.move(parent_pos)
            if self.parent_widget.size() != parent_size:
                self.parent_widget.resize(parent_size)

    def check_now(self):
        if not disk_space_alert_enabled():
            self.stop()
            return
        try:
            high_rows = LocalStorageCleanupManager.get_high_usage_drives(self.threshold_percent)
            current_high_drives = {str(r.get("drive", "")) for r in high_rows}

            # keep only drives still high
            self._alerted_high_usage_drives = {
                d for d in self._alerted_high_usage_drives if d in current_high_drives
            }

            new_high = [
                r for r in high_rows if str(r.get("drive", "")) not in self._alerted_high_usage_drives
            ]
            if not new_high:
                return

            lines = []
            for row in new_high:
                drive = str(row.get("drive", ""))
                pct = float(row.get("used_percent", 0.0))
                lines.append(f"• {drive} is {pct:.1f}% full")
                self._alerted_high_usage_drives.add(drive)

            message = (
                "Disk space is almost full on one or more drives:\n\n"
                + "\n".join(lines)
                + "\n\nPlease go to Settings → Viewer Configuration and clear local data "
                  "using the Storage Cleanup tools."
            )
            self._show_disk_alert("Disk Space Alert", message)
        except Exception:
            # keep runtime lightweight and resilient
            return
