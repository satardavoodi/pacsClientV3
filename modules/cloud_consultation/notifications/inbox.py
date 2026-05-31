"""Qt-free notification operations (thin layer over ``database.notifications_db``)."""

from __future__ import annotations

from .models import KIND_TITLES, NotificationKind


def _kind_value(kind) -> str:
    return kind.value if isinstance(kind, NotificationKind) else str(kind)


def notify(kind, *, title: str | None = None, body: str = "", consultation_id: str = "") -> int:
    """Record a notification; returns its id. Default title comes from the kind."""
    from database import notifications_db

    kv = _kind_value(kind)
    return notifications_db.add_notification(
        kv, title=title or KIND_TITLES.get(kv, "Notification"), body=body, consultation_id=consultation_id
    )


def list_notifications(status: str | None = None, limit: int | None = None) -> list[dict]:
    from database import notifications_db

    return notifications_db.list_notifications(status=status, limit=limit)


def mark_read(notification_id: int) -> bool:
    from database import notifications_db

    return notifications_db.set_status(notification_id, "read")


def archive(notification_id: int) -> bool:
    from database import notifications_db

    return notifications_db.set_status(notification_id, "archived")


def unread_count() -> int:
    from database import notifications_db

    return notifications_db.count(status="unread")
