"""Data models for the consultation envelope."""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from typing import Any

ENVELOPE_FILENAME = "consultation.json"
ENVELOPE_SCHEMA_VERSION = 1


class ConsultationStatus(str, enum.Enum):
    PENDING = "pending"
    UPLOADED = "uploaded"
    DOWNLOADED = "downloaded"
    REVIEWED = "reviewed"
    ANSWERED = "answered"
    CLOSED = "closed"
    CONFLICT = "conflict"


@dataclass
class ConsultationParty:
    provider: str = "google"
    subject: str = ""
    email: str = ""
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "ConsultationParty":
        d = d or {}
        return cls(
            provider=d.get("provider", "google"),
            subject=d.get("subject", ""),
            email=d.get("email", ""),
            name=d.get("name", ""),
        )


@dataclass
class ConsultationResponse:
    response_id: str
    from_user: dict
    created_at: str
    kind: str = "opinion"
    text: str = ""
    report_ref: str = ""
    attachments_ref: list = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ConsultationResponse":
        d = d or {}
        return cls(
            response_id=d.get("response_id", ""),
            from_user=dict(d.get("from_user", {}) or {}),
            created_at=d.get("created_at", ""),
            kind=d.get("kind", "opinion"),
            text=d.get("text", ""),
            report_ref=d.get("report_ref", ""),
            attachments_ref=list(d.get("attachments_ref", []) or []),
        )


@dataclass
class ConsultationEnvelope:
    consultation_id: str
    schema_version: int = ENVELOPE_SCHEMA_VERSION
    case_title: str = ""
    clinical_question: str = ""
    priority: str = "routine"            # routine | urgent
    from_user: dict = field(default_factory=dict)
    assignee: dict = field(default_factory=dict)
    status: str = ConsultationStatus.PENDING.value
    created_at: str = ""
    updated_at: str = ""
    due_at: str = ""
    package_version: int = 1
    study_uids: list = field(default_factory=list)
    responses: list = field(default_factory=list)   # list[dict] (ConsultationResponse)
    integrity: dict = field(default_factory=dict)    # {algo, manifest_sha256, files_sha256, file_count}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "ConsultationEnvelope":
        d = d or {}
        return cls(
            consultation_id=d.get("consultation_id", ""),
            schema_version=int(d.get("schema_version", ENVELOPE_SCHEMA_VERSION) or ENVELOPE_SCHEMA_VERSION),
            case_title=d.get("case_title", ""),
            clinical_question=d.get("clinical_question", ""),
            priority=d.get("priority", "routine"),
            from_user=dict(d.get("from_user", {}) or {}),
            assignee=dict(d.get("assignee", {}) or {}),
            status=d.get("status", ConsultationStatus.PENDING.value),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            due_at=d.get("due_at", ""),
            package_version=int(d.get("package_version", 1) or 1),
            study_uids=list(d.get("study_uids", []) or []),
            responses=list(d.get("responses", []) or []),
            integrity=dict(d.get("integrity", {}) or {}),
        )
