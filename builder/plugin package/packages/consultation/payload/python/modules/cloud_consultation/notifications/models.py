"""Notification kinds, statuses, priorities, categories, and default titles."""

from __future__ import annotations

import enum


class NotificationKind(str, enum.Enum):
    CONSULTATION_ASSIGNED = "consultation_assigned"
    CONSULTATION_UPDATED = "consultation_updated"
    RESPONSE_RECEIVED = "response_received"
    UPLOAD_DONE = "upload_done"
    DOWNLOAD_DONE = "download_done"
    SYNC_ERROR = "sync_error"
    # Failure kinds (2026-06-11; severity tiers) — written by UI failure
    # handlers only (engine/transport never notify directly).
    UPLOAD_FAILED = "upload_failed"
    AUTH_FAILED = "auth_failed"
    QUOTA_EXCEEDED = "quota_exceeded"
    # Low-priority informational kinds for future sources.
    SYSTEM_INFO = "system_info"
    BROWSER_INFO = "browser_info"
    EDUCATION_INFO = "education_info"


class NotificationStatus(str, enum.Enum):
    UNREAD = "unread"
    READ = "read"
    ARCHIVED = "archived"


class NotificationPriority(str, enum.Enum):
    """Severity tier, DERIVED from the kind at render time (no DB column).

    Every notification source maps deterministically from its kind, so
    persisting the priority would duplicate the kind. A future source that
    needs a different priority adds a new kind (cheap — it also carries the
    default title and category), not a schema migration.
    """

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


KIND_TITLES: dict[str, str] = {
    NotificationKind.CONSULTATION_ASSIGNED.value: "New consultation assigned to you",
    NotificationKind.CONSULTATION_UPDATED.value: "Consultation updated",
    NotificationKind.RESPONSE_RECEIVED.value: "Consultation response received",
    NotificationKind.UPLOAD_DONE.value: "Upload complete",
    NotificationKind.DOWNLOAD_DONE.value: "Download complete",
    NotificationKind.SYNC_ERROR.value: "Synchronization error",
    NotificationKind.UPLOAD_FAILED.value: "Upload failed",
    NotificationKind.AUTH_FAILED.value: "Sign-in required",
    NotificationKind.QUOTA_EXCEEDED.value: "Cloud storage almost full",
    NotificationKind.SYSTEM_INFO.value: "System notice",
    NotificationKind.BROWSER_INFO.value: "Web browser notice",
    NotificationKind.EDUCATION_INFO.value: "Education notice",
}


# ── severity tiers (derived; see NotificationPriority docstring) ──────────────
_KIND_PRIORITIES: dict[str, NotificationPriority] = {
    NotificationKind.CONSULTATION_ASSIGNED.value: NotificationPriority.HIGH,
    NotificationKind.RESPONSE_RECEIVED.value: NotificationPriority.HIGH,
    NotificationKind.CONSULTATION_UPDATED.value: NotificationPriority.NORMAL,
    NotificationKind.UPLOAD_DONE.value: NotificationPriority.NORMAL,
    NotificationKind.DOWNLOAD_DONE.value: NotificationPriority.NORMAL,
    NotificationKind.SYNC_ERROR.value: NotificationPriority.CRITICAL,
    NotificationKind.UPLOAD_FAILED.value: NotificationPriority.CRITICAL,
    NotificationKind.AUTH_FAILED.value: NotificationPriority.CRITICAL,
    NotificationKind.QUOTA_EXCEEDED.value: NotificationPriority.CRITICAL,
    NotificationKind.SYSTEM_INFO.value: NotificationPriority.LOW,
    NotificationKind.BROWSER_INFO.value: NotificationPriority.LOW,
    NotificationKind.EDUCATION_INFO.value: NotificationPriority.LOW,
}

_KIND_CATEGORIES: dict[str, str] = {
    NotificationKind.CONSULTATION_ASSIGNED.value: "Consultation",
    NotificationKind.RESPONSE_RECEIVED.value: "Consultation",
    NotificationKind.CONSULTATION_UPDATED.value: "Consultation",
    NotificationKind.UPLOAD_DONE.value: "Transfer",
    NotificationKind.DOWNLOAD_DONE.value: "Transfer",
    NotificationKind.SYNC_ERROR.value: "Urgent",
    NotificationKind.UPLOAD_FAILED.value: "Urgent",
    NotificationKind.AUTH_FAILED.value: "Urgent",
    NotificationKind.QUOTA_EXCEEDED.value: "Urgent",
    NotificationKind.SYSTEM_INFO.value: "System",
    NotificationKind.BROWSER_INFO.value: "Browser",
    NotificationKind.EDUCATION_INFO.value: "Education",
}


def _kind_value(kind) -> str:
    return kind.value if isinstance(kind, NotificationKind) else str(kind)


def priority_for(kind) -> NotificationPriority:
    """Severity tier for *kind* (string or enum). Unknown kinds → NORMAL."""
    return _KIND_PRIORITIES.get(_kind_value(kind), NotificationPriority.NORMAL)


def category_for(kind) -> str:
    """Display category chip for *kind*. Unknown kinds → "Notification"."""
    return _KIND_CATEGORIES.get(_kind_value(kind), "Notification")
