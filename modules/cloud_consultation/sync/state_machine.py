"""Consultation status transitions + conflict detection (pure functions)."""

from __future__ import annotations

import hashlib
import json

from modules.cloud_consultation.consultation.models import ConsultationStatus
from .models import ConflictInfo

S = ConsultationStatus

# Allowed forward transitions. Same-state is always allowed (idempotent no-op).
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    S.PENDING.value:    {S.UPLOADED.value, S.CONFLICT.value, S.CLOSED.value},
    S.UPLOADED.value:   {S.DOWNLOADED.value, S.CONFLICT.value, S.CLOSED.value},
    S.DOWNLOADED.value: {S.REVIEWED.value, S.CONFLICT.value, S.CLOSED.value},
    S.REVIEWED.value:   {S.ANSWERED.value, S.CONFLICT.value, S.CLOSED.value},
    S.ANSWERED.value:   {S.UPLOADED.value, S.DOWNLOADED.value, S.REVIEWED.value,
                         S.CONFLICT.value, S.CLOSED.value},
    S.CONFLICT.value:   {S.UPLOADED.value, S.DOWNLOADED.value, S.REVIEWED.value,
                         S.ANSWERED.value, S.CLOSED.value},
    S.CLOSED.value:     set(),   # terminal
}


def can_transition(from_status: str, to_status: str) -> bool:
    if from_status == to_status:
        return True
    return to_status in ALLOWED_TRANSITIONS.get(from_status, set())


def assert_transition(from_status: str, to_status: str) -> None:
    if not can_transition(from_status, to_status):
        raise ValueError(f"Illegal consultation transition: {from_status!r} -> {to_status!r}")


def fingerprint(envelope) -> str:
    """Stable content fingerprint of a consultation envelope (dict or object).

    Prefers the sealed ``integrity.manifest_sha256``; falls back to a hash over the
    per-file sha256 map so two packages with identical payloads fingerprint equally.
    """
    d = envelope.to_dict() if hasattr(envelope, "to_dict") else dict(envelope or {})
    integrity = d.get("integrity") or {}
    files = integrity.get("files_sha256") or {}
    if files:
        blob = json.dumps(files, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()
    return str(integrity.get("manifest_sha256") or "")


def _version(envelope) -> int:
    d = envelope.to_dict() if hasattr(envelope, "to_dict") else dict(envelope or {})
    try:
        return int(d.get("package_version", 1) or 1)
    except Exception:
        return 1


def detect_conflict(local_envelope, remote_envelope) -> ConflictInfo | None:
    """Return a :class:`ConflictInfo` if local and remote diverged, else ``None``.

    Conflict = same ``package_version`` but different content fingerprints (two parties
    edited the same base independently). Differing versions are a normal update
    (higher version wins) and are NOT a conflict.
    """
    lv, rv = _version(local_envelope), _version(remote_envelope)
    lf, rf = fingerprint(local_envelope), fingerprint(remote_envelope)
    if lv == rv and lf != rf:
        return ConflictInfo(
            reason="divergent_same_version",
            local_version=lv, remote_version=rv,
            local_fingerprint=lf, remote_fingerprint=rf,
        )
    return None
