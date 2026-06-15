"""Per-physician Drive folders + ``physician.json`` control file (ADR-0005, 2026-06-10).

Hub-mode layout on the shared Drive:

    AI-PACS Consultations/                 (app root, drive.file-owned)
        <consultation_address>/            (one folder per physician)
            physician.json                 (quota/usage/sharing snapshot)
            <consultation_id>/             (item folders)

Authority: **the Laravel backend owns quota/sharing/ownership** (its
``physician:quota`` / ``drive:sync-usage`` / ``physician:push-meta`` write the
authoritative values). This module only (a) creates the folder layout, (b)
reads the snapshot to gate uploads client-side, and (c) bumps usage
*approximately* after an upload (``approximate: true``) until the server
recompute self-heals it.

Qt-free; every transport call is network-touching → worker threads only.
Fail-open rule: a missing/unreadable ``physician.json`` must never block a
clinical upload (the admin simply hasn't configured quotas yet) — only an
EXPLICIT exceeded quota blocks.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PHYSICIAN_META_FILENAME = "physician.json"
PHYSICIAN_META_FORMAT = "aipacs-physician-meta-v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_meta(address: str) -> dict:
    return {
        "format": PHYSICIAN_META_FORMAT,
        "address": (address or "").strip().lower(),
        "identity": {"name": "", "user_id": None},
        "quota": {"storage_bytes": None, "max_consultations": None, "max_courses": None},
        "usage": {
            "storage_bytes": 0,
            "consultations": 0,
            "courses": 0,
            "computed_at": "",
            "approximate": True,
        },
        "shared_items": [],
        "updated_at": _utc_now_iso(),
    }


def ensure_physician_folder(transport, address: str, app_folder_id: str | None = None) -> str:
    """Return the physician's folder id under the app root (created if missing)."""
    addr = (address or "").strip().lower()
    if not addr:
        raise ValueError("Physician address is required for the hub Drive layout.")
    app_id = app_folder_id or transport.ensure_app_folder()
    return transport.make_child_folder(app_id, addr)


def read_physician_meta(transport, physician_folder_id: str) -> dict | None:
    """Download and parse ``physician.json``; None when absent/unreadable."""
    try:
        child = transport.find_child(physician_folder_id, PHYSICIAN_META_FILENAME)
        if child is None or child.is_folder:
            return None
        with tempfile.TemporaryDirectory() as td:
            local = os.path.join(td, PHYSICIAN_META_FILENAME)
            transport.download_file(child.id, local)
            data = json.loads(Path(local).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.debug("physician.json read failed: %s", exc)
        return None


def write_physician_meta(transport, physician_folder_id: str, meta: dict) -> None:
    """Create-or-replace ``physician.json`` in the physician folder."""
    meta = dict(meta or {})
    meta["updated_at"] = _utc_now_iso()
    existing = transport.find_child(physician_folder_id, PHYSICIAN_META_FILENAME)
    with tempfile.TemporaryDirectory() as td:
        local = Path(td) / PHYSICIAN_META_FILENAME
        local.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        if existing is not None and not existing.is_folder:
            try:
                transport.delete(existing.id)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("stale physician.json delete failed: %s", exc)
        transport.upload_file(str(local), physician_folder_id, PHYSICIAN_META_FILENAME)


def local_tree_size(path) -> int:
    """Total bytes of all files under ``path`` (the package about to upload)."""
    total = 0
    for dirpath, _dirs, files in os.walk(str(path)):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:  # pragma: no cover - defensive
                pass
    return total


def check_quota(meta: dict | None, *, package_bytes: int, consultation_count: int) -> tuple[bool, str]:
    """Pure client-side quota gate.

    ``consultation_count`` = consultations already in the physician folder.
    Returns ``(ok, reason)``. FAILS OPEN when meta/quota is absent (None
    limits = unlimited); blocks only on an explicit exceeded limit.
    """
    if not isinstance(meta, dict):
        return True, ""
    quota = meta.get("quota") or {}
    usage = meta.get("usage") or {}

    max_consult = quota.get("max_consultations")
    if isinstance(max_consult, int) and max_consult >= 0:
        if consultation_count + 1 > max_consult:
            return False, (
                f"Cloud consultation limit reached ({consultation_count}/{max_consult}). "
                "Ask the administrator to raise your quota or remove old consultations."
            )

    limit = quota.get("storage_bytes")
    if isinstance(limit, int) and limit >= 0:
        used = usage.get("storage_bytes")
        used = int(used) if isinstance(used, (int, float)) else 0
        if used + int(package_bytes) > limit:
            mb = 1024 * 1024
            return False, (
                f"Cloud storage quota exceeded: {used // mb} MB used + "
                f"{int(package_bytes) // mb} MB package > {limit // mb} MB allowed. "
                "Ask the administrator to raise your quota or free up space."
            )
    return True, ""


def bump_usage(meta: dict | None, address: str, *, added_bytes: int, added_consultations: int = 1) -> dict:
    """Approximate post-upload usage bump (server recompute is authoritative)."""
    out = dict(meta) if isinstance(meta, dict) else default_meta(address)
    usage = dict(out.get("usage") or {})
    usage["storage_bytes"] = int(usage.get("storage_bytes") or 0) + int(added_bytes)
    usage["consultations"] = int(usage.get("consultations") or 0) + int(added_consultations)
    usage["computed_at"] = _utc_now_iso()
    usage["approximate"] = True
    out["usage"] = usage
    out.setdefault("address", (address or "").strip().lower())
    out.setdefault("format", PHYSICIAN_META_FORMAT)
    return out


def count_consultation_folders(transport, physician_folder_id: str) -> int:
    """Item folders currently in the physician folder (cheap, one listing)."""
    try:
        return sum(1 for e in transport.list_folder(physician_folder_id) if e.is_folder)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("physician folder count failed: %s", exc)
        return 0
