from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import DEFAULT_DATA_ROOT


SECRET_KEYS = {
    "password",
    "pass",
    "token",
    "authorization",
    "cookie",
    "set-cookie",
    "api_key",
    "apikey",
}

# PHI must never be written to the audit log. The audit proves WHAT happened;
# it must not become a second patient database. These fields are replaced with a
# stable hash, so two records about the same patient still correlate.
# (docs/security-model.md §6)
PHI_KEYS = {
    "nationalcode",
    "nationalid",
    "nid",
    "patientname",
    "name",
    "firstname",
    "lastname",
    "tel",
    "mobile",
    "phone",
    "address",
    "birthdate",
    "text",            # a free-text agent command can contain a patient name
    "report_text",
    "report_html",
    "content",
    "findings",
}


def phi_hash(value: Any) -> str:
    import hashlib

    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]
    return f"phi:sha256:{digest}"


class AuditLogger:
    def __init__(self, data_root: Path = DEFAULT_DATA_ROOT):
        self.data_root = data_root

    def write(self, event_type: str, payload: dict[str, Any], audit_id: str | None = None) -> Path:
        now = datetime.now()
        directory = self.data_root / "manifests" / f"{now:%Y}" / f"{now:%m}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{date.today():%Y-%m-%d}_audit.jsonl"
        row = {
            "audit_id": audit_id or new_audit_id(),
            "captured_at": now.isoformat(timespec="seconds"),
            "event_type": event_type,
            **redact(payload),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str))
            handle.write("\n")
        return path


def new_audit_id() -> str:
    import uuid

    return f"aud_{uuid.uuid4().hex[:16]}"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            lowered = key.lower()
            if lowered in SECRET_KEYS:
                result[key] = "<redacted>"
            elif lowered in PHI_KEYS and child not in (None, "", [], {}):
                # Hashed, not stored: correlatable, not readable.
                result[key] = phi_hash(child)
            else:
                result[key] = redact(child)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
