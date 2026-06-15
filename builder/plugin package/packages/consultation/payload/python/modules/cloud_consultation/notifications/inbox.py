"""Qt-free notification operations (thin layer over ``database.notifications_db``)."""

from __future__ import annotations

import logging

from .models import KIND_TITLES, NotificationKind, category_for, priority_for

logger = logging.getLogger(__name__)


def _kind_value(kind) -> str:
    return kind.value if isinstance(kind, NotificationKind) else str(kind)


def notify(kind, *, title: str | None = None, body: str = "", consultation_id: str = "",
           priority=None) -> int:
    """Record a notification; returns its id. Default title comes from the kind.

    ``priority`` is an optional override hook (2026-06-11). Priority is DERIVED
    from the kind at render time (``models.priority_for``) and is NOT persisted
    — every source maps deterministically from its kind, so no schema change is
    needed. A mismatching override is logged (a source that genuinely needs a
    different tier should add a kind, which also carries title + category).
    """
    from database import notifications_db

    kv = _kind_value(kind)
    if priority is not None and priority != priority_for(kv):
        logger.debug(
            "notify(%s): priority override %r ignored (derived=%s); add a kind "
            "for a different tier", kv, priority, priority_for(kv).value,
        )
    return notifications_db.add_notification(
        kv, title=title or KIND_TITLES.get(kv, "Notification"), body=body, consultation_id=consultation_id
    )


def _decorate(row: dict) -> dict:
    """Attach derived ``priority`` + ``category`` keys (render-time only)."""
    kind = row.get("kind") or ""
    row["priority"] = priority_for(kind).value
    row["category"] = category_for(kind)
    return row


def list_notifications(status: str | None = None, limit: int | None = None) -> list[dict]:
    from database import notifications_db

    return notifications_db.list_notifications(status=status, limit=limit)


def latest_notifications(limit: int = 4) -> list[dict]:
    """The popup feed: latest *limit* rows, UNREAD first then read, each
    newest-first; archived rows excluded. Rows carry derived ``priority`` and
    ``category`` keys."""
    rows = list_notifications(status="unread", limit=limit)
    if len(rows) < limit:
        rows += list_notifications(status="read", limit=limit - len(rows))
    return [_decorate(dict(r)) for r in rows]


def mark_read(notification_id: int) -> bool:
    from database import notifications_db

    return notifications_db.set_status(notification_id, "read")


def archive(notification_id: int) -> bool:
    from database import notifications_db

    return notifications_db.set_status(notification_id, "archived")


def unread_count() -> int:
    from database import notifications_db

    return notifications_db.count(status="unread")


def clear_all() -> int:
    """Mark ALL unread notifications read ("cleared" semantics — they remain
    listable as read history; new notifications appear afterwards as usual).
    Returns the number of rows cleared."""
    from database import notifications_db

    return notifications_db.mark_all_read()
