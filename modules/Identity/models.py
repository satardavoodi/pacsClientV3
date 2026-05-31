"""Data models for the Identity module (pure stdlib; no Qt, no third-party)."""

from __future__ import annotations

import enum
import json
from dataclasses import asdict, dataclass, field
from typing import Any


class Capability(enum.Enum):
    """What an external identity can do for AI-PACS."""

    PROFILE = "profile"            # name, email/handle, avatar
    CLOUD_STORAGE = "cloud_storage"  # Drive / OneDrive / Dropbox / S3 transport
    MESSAGING = "messaging"        # Telegram, etc. (future)
    PHONE = "phone"


@dataclass
class ExternalIdentity:
    """An external account linked to a specific AI-PACS user.

    Refresh tokens are NOT stored on this object or in the DB row; they live in the
    OS keychain via :mod:`modules.Identity.secure_store`, keyed by
    ``(provider, subject_id)``.
    """

    provider: str                 # "google" | "telegram" | "instagram"
    subject_id: str               # provider-stable id (Google "sub")
    handle: str = ""              # email / @handle / phone
    display_name: str = ""
    avatar_url: str = ""
    avatar_cache: str = ""        # local cached avatar path (optional)
    capabilities: list[str] = field(default_factory=list)
    aipacs_user: str = ""         # link key = current login username
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ExternalIdentity":
        def _loads(value: Any, default: Any):
            if value is None or value == "":
                return default
            if isinstance(value, (list, dict)):
                return value
            try:
                return json.loads(value)
            except Exception:
                return default

        return cls(
            provider=row.get("provider", ""),
            subject_id=row.get("subject_id", ""),
            handle=row.get("handle") or "",
            display_name=row.get("display_name") or "",
            avatar_url=row.get("avatar_url") or "",
            avatar_cache=row.get("avatar_cache") or "",
            capabilities=_loads(row.get("capabilities"), []),
            aipacs_user=row.get("aipacs_user") or "",
            extra=_loads(row.get("extra"), {}),
        )


@dataclass
class ProviderInfo:
    """UI-facing snapshot of a provider's availability and connection state."""

    id: str
    display_name: str
    capabilities: list[str]
    available: bool          # dependencies installed AND configured
    detail: str = ""         # reason shown when unavailable
    connected: bool = False
    connected_handle: str = ""
    subject_id: str = ""
