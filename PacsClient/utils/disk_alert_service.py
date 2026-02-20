from __future__ import annotations

from typing import Set

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMessageBox, QWidget

from PacsClient.utils.local_storage_cleanup_manager import LocalStorageCleanupManager


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
        QTimer.singleShot(int(initial_delay_ms), self.check_now)
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def check_now(self):
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
            QMessageBox.warning(self.parent_widget, "Disk Space Alert", message)
        except Exception:
            # keep runtime lightweight and resilient
            return
