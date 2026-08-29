"""Local persistence for configured Legion Consult requests."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from uuid import uuid4

from .models import LegionConsultRequest


def _default_root() -> Path:
    try:
        from PacsClient.utils.data_paths import AI_DIR

        return Path(AI_DIR) / "legion_consult"
    except (ImportError, AttributeError, TypeError):
        return Path.cwd() / "user_data" / "ai" / "legion_consult"


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._")
    if not safe:
        raise ValueError("A safe persistence identifier is required.")
    return safe[:160]


def save_configured_request(
    request: LegionConsultRequest,
    *,
    root: str | Path | None = None,
) -> Path:
    """Atomically save a local request manifest and return its final path."""
    storage_root = Path(root) if root is not None else _default_root()
    request_dir = (
        storage_root
        / _safe_segment(request.selection.study_uid)
        / _safe_segment(request.session_id)
    )
    request_dir.mkdir(parents=True, exist_ok=True)
    destination = request_dir / "request.json"
    temporary = request_dir / f".{uuid4().hex}.tmp"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(request.as_dict(), handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def update_request_state(
    request_path: str | Path,
    *,
    status: str,
    remote_send_status: str,
) -> Path:
    """Atomically update only the persisted request lifecycle fields."""
    destination = Path(request_path)
    try:
        document = json.loads(destination.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError("The saved Legion Consult request is missing.") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError("The saved Legion Consult request is unreadable.") from exc
    document["status"] = str(status)
    document["remote_send_status"] = str(remote_send_status)
    temporary = destination.with_name(f".{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination
