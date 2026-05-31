"""ConsultationPoller — periodically checks the cloud for consultations assigned to me.

The network scan runs in a short-lived QThread (never on the UI thread); detected
assignments are recorded + turned into notifications on the main thread. Polling is
driven by a QTimer (mirrors the existing DiskUsageAlertService cadence pattern).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from . import inbox
from .detect import find_assigned_consultations
from .models import NotificationKind

logger = logging.getLogger(__name__)


class _ScanThread(QThread):
    found = Signal(list)
    error = Signal(str)

    def __init__(self, transport, app_folder_id, my_email, known, parent=None):
        super().__init__(parent)
        self._transport = transport
        self._app_folder_id = app_folder_id
        self._my_email = my_email
        self._known = set(known)

    def run(self):
        try:
            self.found.emit(find_assigned_consultations(
                self._transport, self._app_folder_id, self._my_email, self._known))
        except Exception as exc:
            self.error.emit(str(exc))


class ConsultationPoller(QObject):
    notified = Signal(int)   # notification id

    def __init__(self, transport_provider, my_email, *, interval_ms: int = 120000, parent=None):
        super().__init__(parent)
        self._provider = transport_provider     # callable -> CloudTransport | None
        self._my_email = my_email
        self._known: set[str] = set()
        self._scan: _ScanThread | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll_once)

    def start(self) -> None:
        self._timer.start()
        self.poll_once()

    def stop(self) -> None:
        self._timer.stop()

    def poll_once(self) -> None:
        if self._scan is not None and self._scan.isRunning():
            return
        try:
            transport = self._provider() if callable(self._provider) else self._provider
        except Exception as exc:
            logger.debug("poller transport provider failed: %s", exc)
            return
        if transport is None:
            return
        try:
            app_id = transport.ensure_app_folder()
        except Exception as exc:
            logger.debug("poller ensure_app_folder failed: %s", exc)
            return
        self._scan = _ScanThread(transport, app_id, self._my_email, set(self._known), self)
        self._scan.found.connect(self._on_found)
        self._scan.error.connect(lambda msg: logger.debug("poller scan error: %s", msg))
        self._scan.start()

    def _on_found(self, items: list) -> None:
        for item in items or []:
            env = item.get("envelope", {}) or {}
            cid = str(env.get("consultation_id") or "")
            if not cid or cid in self._known:
                continue
            self._known.add(cid)
            try:
                from database import consultation_db

                consultation_db.upsert_consultation(
                    cid, direction="incoming", status="uploaded",
                    case_title=env.get("case_title", ""),
                    clinical_question=env.get("clinical_question", ""),
                    remote_folder_id=item.get("remote_folder_id", ""),
                    assignee_email=(env.get("assignee") or {}).get("email", ""),
                )
            except Exception as exc:
                logger.debug("recording incoming consultation failed: %s", exc)
            nid = inbox.notify(
                NotificationKind.CONSULTATION_ASSIGNED,
                body=env.get("case_title", ""), consultation_id=cid,
            )
            self.notified.emit(nid)
