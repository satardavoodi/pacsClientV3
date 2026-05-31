"""Assignee-side detection: find consultation packages on the cloud assigned to me.

Qt-free and transport-agnostic. Lists the app folder's consultation subfolders, reads
each ``consultation.json`` (downloaded to a temp file), and returns those whose
``assignee.email`` matches the current user and that aren't already known locally.
The Qt poller turns these into notifications.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from modules.cloud_consultation.consultation.models import ENVELOPE_FILENAME

logger = logging.getLogger(__name__)


def _download_and_read_envelope(transport, file_id: str) -> dict | None:
    try:
        with tempfile.TemporaryDirectory() as td:
            local = os.path.join(td, ENVELOPE_FILENAME)
            transport.download_file(file_id, local)
            data = json.loads(Path(local).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.debug("could not read remote envelope %s: %s", file_id, exc)
        return None


def find_assigned_consultations(
    transport, app_folder_id: str, my_email: str, known_ids=None
) -> list[dict]:
    """Return ``[{remote_folder_id, envelope}]`` for consultations on the cloud that are
    assigned to ``my_email`` and not in ``known_ids``."""
    known = {str(k) for k in (known_ids or ())}
    me = (my_email or "").strip().lower()
    found: list[dict] = []
    for entry in transport.list_folder(app_folder_id):
        if not entry.is_folder:
            continue
        child = transport.find_child(entry.id, ENVELOPE_FILENAME)
        if child is None:
            continue
        env = _download_and_read_envelope(transport, child.id)
        if not env:
            continue
        cid = str(env.get("consultation_id") or "")
        assignee_email = str((env.get("assignee") or {}).get("email", "")).strip().lower()
        if assignee_email == me and me and cid and cid not in known:
            found.append({"remote_folder_id": entry.id, "envelope": env})
    return found
