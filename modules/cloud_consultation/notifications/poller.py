"""ConsultationPoller — periodically checks the cloud for consultation activity.

Two scans per cycle, both in a short-lived QThread (never on the UI thread):

* **assignee side** — consultations on the cloud assigned to me
  (``find_assigned_consultations``) → "consultation assigned" notification;
* **originator side** — responses uploaded into consultations I sent
  (``find_response_updates``) → "response received" notification + local status
  ``answered``.

Detected items are recorded + notified on the main thread. Polling is driven by a
QTimer (mirrors the existing DiskUsageAlertService cadence pattern).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from . import inbox
from .detect import find_assigned_consultations, find_response_updates
from .models import NotificationKind

logger = logging.getLogger(__name__)


class _ScanThread(QThread):
    found = Signal(list)
    found_responses = Signal(list)
    error = Signal(str)

    def __init__(self, transport_provider, my_email, known,
                 outgoing=None, known_answered=None, parent=None):
        super().__init__(parent)
        self._provider = transport_provider
        self._my_email = my_email
        self._known = set(known)
        self._outgoing = list(outgoing or [])
        self._known_answered = set(known_answered or ())

    def run(self):
        # EVERYTHING network-touching lives in this thread. Building the
        # transport refreshes the OAuth token (HTTPS) and ensure_app_folder
        # is a Drive API round-trip — running either on the GUI thread
        # froze the app for seconds per poll (3–20 s observed on slow
        # connectivity; see MAIN_THREAD_STALL_TRACE 2026-06-07).
        try:
            transport = self._provider() if callable(self._provider) else self._provider
        except Exception as exc:
            self.error.emit(f"transport provider failed: {exc}")
            return
        if transport is None:
            return
        try:
            app_folder_id = transport.ensure_app_folder()
        except Exception as exc:
            self.error.emit(f"ensure_app_folder failed: {exc}")
            return
        try:
            self.found.emit(find_assigned_consultations(
                transport, app_folder_id, self._my_email, self._known))
        except Exception as exc:
            self.error.emit(str(exc))
        try:
            if self._outgoing:
                self.found_responses.emit(find_response_updates(
                    transport, self._outgoing, self._known_answered))
        except Exception as exc:
            self.error.emit(str(exc))


class ConsultationPoller(QObject):
    notified = Signal(int)   # notification id

    #: Offline backoff cap — when scans fail (no internet / Google unreachable)
    #: the poll interval doubles per failure up to this bound, then resets to
    #: the base interval on the first successful scan. Keeps an offline
    #: workstation from churning connect attempts every 2 minutes.
    MAX_BACKOFF_INTERVAL_MS = 600000  # 10 min

    def __init__(self, transport_provider, my_email, *, interval_ms: int = 120000, parent=None):
        super().__init__(parent)
        self._provider = transport_provider     # callable -> CloudTransport | None
        self._my_email = my_email
        self._known: set[str] = set()
        self._known_answered: set[str] = set()
        self._scan: _ScanThread | None = None
        self._base_interval_ms = int(interval_ms)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll_once)

    def start(self) -> None:
        self._timer.start()
        # First poll is deferred a few seconds: app startup is the most
        # IO-contended window and consultation-notification latency is
        # irrelevant at a 2-minute cadence. (The poll itself is fully
        # off-thread, but the deferral also keeps thread/token churn out
        # of the login/startup path.)
        QTimer.singleShot(5000, self.poll_once)

    def stop(self) -> None:
        self._timer.stop()

    def _outgoing_awaiting_response(self) -> list[dict]:
        """Sent consultations whose remote folder may now contain a response."""
        try:
            from database import consultation_db

            rows = consultation_db.list_consultations(direction="outgoing")
            return [
                {"consultation_id": r.get("consultation_id"),
                 "remote_folder_id": r.get("remote_folder_id")}
                for r in rows
                if r.get("remote_folder_id")
                and r.get("status") in ("uploaded", "downloaded", "reviewed")
                and r.get("consultation_id") not in self._known_answered
            ]
        except Exception as exc:
            logger.debug("listing outgoing consultations failed: %s", exc)
            return []

    def poll_once(self) -> None:
        """Kick off one scan cycle. MUST stay cheap — runs on the GUI thread.

        All blocking work (transport build + OAuth refresh, ensure_app_folder,
        Drive scans) happens inside _ScanThread.run(). Never add a network or
        Drive call here: this method froze the UI for 3–20 s per poll when
        ensure_app_folder ran on the main thread.
        """
        if self._scan is not None and self._scan.isRunning():
            return
        self._scan = _ScanThread(
            self._provider, self._my_email, set(self._known),
            outgoing=self._outgoing_awaiting_response(),
            known_answered=set(self._known_answered), parent=self,
        )
        self._scan.found.connect(self._on_found)
        self._scan.found_responses.connect(self._on_found_responses)
        self._scan.error.connect(self._on_scan_error)
        self._scan.start()

    def _on_scan_error(self, msg: str) -> None:
        """Offline / unreachable Google: back off instead of retrying eagerly.

        The scan already runs off-thread with bounded socket timeouts, so a
        failure costs nothing visible — backoff just avoids pointless connect
        churn while disconnected. Consultations are a background convenience;
        the workstation must behave identically with no internet at all.
        """
        logger.debug("poller scan error: %s", msg)
        current = max(self._timer.interval(), self._base_interval_ms)
        self._timer.setInterval(min(current * 2, self.MAX_BACKOFF_INTERVAL_MS))

    def _on_found(self, items: list) -> None:
        # Successful scan → connectivity is back; restore the base cadence.
        if self._timer.interval() != self._base_interval_ms:
            self._timer.setInterval(self._base_interval_ms)
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
                    from_handle=(env.get("from_user") or {}).get("email", ""),
                )
            except Exception as exc:
                logger.debug("recording incoming consultation failed: %s", exc)
            nid = inbox.notify(
                NotificationKind.CONSULTATION_ASSIGNED,
                body=env.get("case_title", ""), consultation_id=cid,
            )
            self.notified.emit(nid)

    def _on_found_responses(self, items: list) -> None:
        for item in items or []:
            cid = str(item.get("consultation_id") or "")
            if not cid or cid in self._known_answered:
                continue
            self._known_answered.add(cid)
            env = item.get("envelope", {}) or {}
            try:
                from database import consultation_db

                consultation_db.update_consultation_fields(cid, status="answered")
                consultation_db.add_event(
                    cid, "responded",
                    details=f"{len(env.get('responses') or [])} response(s) detected on cloud",
                )
            except Exception as exc:
                logger.debug("recording answered consultation failed: %s", exc)
            nid = inbox.notify(
                NotificationKind.RESPONSE_RECEIVED,
                body=env.get("case_title", ""), consultation_id=cid,
            )
            self.notified.emit(nid)
