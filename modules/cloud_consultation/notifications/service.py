"""NotificationService — a thin QObject over the Qt-free ``inbox`` operations.

Emits ``notificationAdded`` so the account-area badge / notification center can
refresh. UI wiring lands in Phase 6.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from . import inbox


class NotificationService(QObject):
    notificationAdded = Signal(int)   # notification id
    changed = Signal()

    def notify(self, kind, *, title: str | None = None, body: str = "", consultation_id: str = "") -> int:
        nid = inbox.notify(kind, title=title, body=body, consultation_id=consultation_id)
        self.notificationAdded.emit(nid)
        self.changed.emit()
        return nid

    def list(self, status: str | None = None, limit: int | None = None) -> list[dict]:
        return inbox.list_notifications(status=status, limit=limit)

    def unread_count(self) -> int:
        return inbox.unread_count()

    def mark_read(self, notification_id: int) -> bool:
        ok = inbox.mark_read(notification_id)
        if ok:
            self.changed.emit()
        return ok

    def archive(self, notification_id: int) -> bool:
        ok = inbox.archive(notification_id)
        if ok:
            self.changed.emit()
        return ok
