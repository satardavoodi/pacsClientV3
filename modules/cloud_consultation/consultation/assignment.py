"""Assign an uploaded consultation to another physician.

Shares the consultation's remote folder with the assignee's Google email and records
the assignment in the DB + audit log. The assignee's own AI-PACS detects the shared
package via its poller (see ``notifications/detect.py``) and raises an in-app
notification — there is no cross-machine push.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def assign(
    transport, consultation_id: str, assignee_email: str, *,
    assigned_by: str = "", role: str = "reader", remote_folder_id: str | None = None,
):
    """Share the consultation's remote folder with ``assignee_email`` and record it.

    The package must already be uploaded (so a ``remote_folder_id`` exists, either
    passed in or stored on the consultation row). Returns the provider ``ShareInfo``.
    """
    from database import consultation_db

    row = consultation_db.get_consultation(consultation_id)
    folder_id = remote_folder_id or (row or {}).get("remote_folder_id")
    if not folder_id:
        raise ValueError(
            "Consultation has no remote_folder_id; upload the package before assigning."
        )

    share = transport.share(folder_id, assignee_email, role=role)
    consultation_db.update_consultation_fields(
        consultation_id,
        assignee_email=assignee_email,
        assigned_by=assigned_by,
        assigned_at=_now_iso(),
    )
    consultation_db.add_event(
        consultation_id, "assigned",
        details=f"shared with {assignee_email}", actor_handle=assigned_by,
    )
    return share
