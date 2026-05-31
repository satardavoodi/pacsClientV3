"""Notification kinds, statuses, and default titles."""

from __future__ import annotations

import enum


class NotificationKind(str, enum.Enum):
    CONSULTATION_ASSIGNED = "consultation_assigned"
    CONSULTATION_UPDATED = "consultation_updated"
    RESPONSE_RECEIVED = "response_received"
    UPLOAD_DONE = "upload_done"
    DOWNLOAD_DONE = "download_done"
    SYNC_ERROR = "sync_error"


class NotificationStatus(str, enum.Enum):
    UNREAD = "unread"
    READ = "read"
    ARCHIVED = "archived"


KIND_TITLES: dict[str, str] = {
    NotificationKind.CONSULTATION_ASSIGNED.value: "New consultation assigned to you",
    NotificationKind.CONSULTATION_UPDATED.value: "Consultation updated",
    NotificationKind.RESPONSE_RECEIVED.value: "Consultation response received",
    NotificationKind.UPLOAD_DONE.value: "Upload complete",
    NotificationKind.DOWNLOAD_DONE.value: "Download complete",
    NotificationKind.SYNC_ERROR.value: "Synchronization error",
}
