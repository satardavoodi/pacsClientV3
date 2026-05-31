"""Build, seal, read, and verify the consultation envelope (``consultation.json``).

The envelope is a sibling file in the package root. Integrity is a SHA-256 of every
file in the package EXCEPT the envelope itself (so the clinical payload —
``manifest.json``, ``package.db`` and everything under ``patients/`` — is covered and
tamper-evident). The offline package is never modified by this module.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    ENVELOPE_FILENAME,
    ConsultationEnvelope,
    ConsultationResponse,
    ConsultationStatus,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def compute_files_sha256(package_root, *, exclude: set[str] | None = None) -> dict[str, str]:
    """Return ``{posix_rel_path: sha256}`` for every file under the package root,
    excluding the envelope file (and any names in ``exclude``)."""
    root = Path(package_root)
    exclude = set(exclude or set()) | {ENVELOPE_FILENAME}
    result: dict[str, str] = {}
    for p in sorted(root.rglob("*"), key=lambda x: x.as_posix()):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel in exclude:
            continue
        result[rel] = _sha256_file(p)
    return result


def build_envelope(
    *, case_title: str, clinical_question: str, from_user: dict,
    assignee: dict | None = None, study_uids: list | None = None,
    priority: str = "routine", consultation_id: str | None = None, due_at: str = "",
) -> ConsultationEnvelope:
    now = _utc_now_iso()
    return ConsultationEnvelope(
        consultation_id=consultation_id or str(uuid.uuid4()),
        case_title=case_title,
        clinical_question=clinical_question,
        priority=priority or "routine",
        from_user=dict(from_user or {}),
        assignee=dict(assignee or {}),
        status=ConsultationStatus.PENDING.value,
        created_at=now,
        updated_at=now,
        due_at=due_at or "",
        package_version=1,
        study_uids=list(study_uids or []),
        responses=[],
        integrity={},
    )


def seal_envelope(package_root, envelope: ConsultationEnvelope) -> ConsultationEnvelope:
    """Compute integrity over the package files and (over)write ``consultation.json``."""
    root = Path(package_root)
    files = compute_files_sha256(root)
    envelope.integrity = {
        "algo": "sha256",
        "manifest_sha256": files.get("manifest.json", ""),
        "files_sha256": files,
        "file_count": len(files),
    }
    envelope.updated_at = _utc_now_iso()
    (root / ENVELOPE_FILENAME).write_text(
        json.dumps(envelope.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return envelope


def read_envelope(package_root) -> ConsultationEnvelope | None:
    p = Path(package_root) / ENVELOPE_FILENAME
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read consultation envelope %s: %s", p, exc)
        return None
    if not isinstance(data, dict):
        return None
    return ConsultationEnvelope.from_dict(data)


def verify_integrity(package_root) -> dict:
    """Recompute hashes and compare to the sealed envelope.

    Returns ``{ok, reason, mismatched[], missing[], added[]}``. ``missing`` = files the
    envelope recorded but are now gone; ``added`` = files present now but not sealed.
    """
    env = read_envelope(package_root)
    if env is None:
        return {"ok": False, "reason": "no_envelope", "mismatched": [], "missing": [], "added": []}
    stored = dict((env.integrity or {}).get("files_sha256", {}) or {})
    current = compute_files_sha256(package_root)
    mismatched = sorted([k for k in stored if k in current and stored[k] != current[k]])
    missing = sorted([k for k in stored if k not in current])
    added = sorted([k for k in current if k not in stored])
    ok = not (mismatched or missing or added)
    return {
        "ok": ok,
        "reason": "" if ok else "integrity_mismatch",
        "mismatched": mismatched,
        "missing": missing,
        "added": added,
    }


def add_response(
    package_root, response: ConsultationResponse, *,
    new_status: str = ConsultationStatus.ANSWERED.value,
) -> ConsultationEnvelope:
    """Append a response, bump the package version, and re-seal (re-hashing all files
    so any newly added report/attachment files are covered)."""
    env = read_envelope(package_root)
    if env is None:
        raise FileNotFoundError("No consultation envelope to add a response to.")
    env.responses.append(response.to_dict())
    env.status = new_status
    env.package_version = int(env.package_version) + 1
    return seal_envelope(package_root, env)


def set_status(package_root, status: str) -> ConsultationEnvelope:
    env = read_envelope(package_root)
    if env is None:
        raise FileNotFoundError("No consultation envelope.")
    env.status = status
    return seal_envelope(package_root, env)
