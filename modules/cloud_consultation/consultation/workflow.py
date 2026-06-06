"""End-to-end consultation orchestration (Qt-free; the UI calls these via workers).

Ties together the pieces from earlier phases:
  create  → seal envelope (P3) + DB row (P4) + resumable upload (P4) + share (P5)
  open    → download (P4) + verify integrity (P3) + read envelope + record incoming
  respond → record response (P3) + re-upload into the shared folder (P4)

Transport-agnostic, so it is exercised in tests with the in-memory FakeTransport.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _notify(kind, *, title: str | None = None, body: str = "", consultation_id: str = "") -> None:
    """Best-effort local notification; a notify failure never breaks the workflow."""
    try:
        from ..notifications import inbox

        inbox.notify(kind, title=title, body=body, consultation_id=consultation_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("workflow notification skipped: %s", exc)


def create_and_upload_consultation(
    *, transport, package_root, aipacs_user: str, from_user: dict,
    case_title: str, clinical_question: str, assignee_email: str,
    study_uids=None, priority: str = "routine", due_at: str = "", progress_cb=None,
) -> str:
    """Seal an exported package as a consultation, upload it, and share with the
    assignee. Returns the consultation id. BLOCKING — run off the UI thread."""
    from database import consultation_db

    from .assignment import assign
    from .service import seal_package_as_consultation
    from ..sync.engine import CloudSyncEngine

    env = seal_package_as_consultation(
        package_root, case_title=case_title, clinical_question=clinical_question,
        from_user=from_user, assignee={"email": assignee_email}, study_uids=study_uids or [],
        priority=priority, due_at=due_at,
    )
    cid = env.consultation_id
    consultation_db.upsert_consultation(
        cid, direction="outgoing", status="pending", local_path=str(package_root),
        case_title=case_title, clinical_question=clinical_question,
        assignee_email=assignee_email, from_handle=(from_user or {}).get("email", ""),
        priority=priority, study_uids=study_uids or [], due_at=due_at,
        manifest_sha256=(env.integrity or {}).get("manifest_sha256", ""),
    )

    engine = CloudSyncEngine(transport, progress_cb=progress_cb)
    remote_folder_id = engine.upload(cid, package_root)
    if assignee_email:
        assign(transport, cid, assignee_email,
               assigned_by=(from_user or {}).get("email", ""), remote_folder_id=remote_folder_id)
    from ..notifications.models import NotificationKind

    _notify(NotificationKind.UPLOAD_DONE, title="Consultation sent",
            body=f"“{case_title}” sent to {assignee_email}" if assignee_email else case_title,
            consultation_id=cid)
    return cid


def download_and_open_consultation(
    *, transport, consultation_id: str, remote_folder_id: str, dest_root, progress_cb=None,
) -> dict:
    """Download a consultation package, verify integrity, and read its envelope.

    Records/updates the local (incoming) consultation row. Returns
    ``{dest, integrity, envelope, consultation_id}``. The caller ingests the verified
    package into the local DB via the existing offline engine and opens the viewer.
    """
    from database import consultation_db

    from .envelope import read_envelope, verify_integrity
    from ..sync.engine import CloudSyncEngine

    engine = CloudSyncEngine(transport, progress_cb=progress_cb)
    dest = engine.download(consultation_id, remote_folder_id, dest_root)
    integrity = verify_integrity(dest)
    envelope = read_envelope(dest)

    if envelope is not None:
        consultation_db.upsert_consultation(
            envelope.consultation_id, direction="incoming", status="downloaded",
            remote_folder_id=remote_folder_id, local_path=str(dest),
            case_title=envelope.case_title, clinical_question=envelope.clinical_question,
            from_handle=(envelope.from_user or {}).get("email", ""),
            assignee_email=(envelope.assignee or {}).get("email", ""),
            priority=envelope.priority, study_uids=envelope.study_uids,
        )

    from ..notifications.models import NotificationKind

    _notify(NotificationKind.DOWNLOAD_DONE, title="Consultation downloaded",
            body=(envelope.case_title if envelope else ""),
            consultation_id=(envelope.consultation_id if envelope else consultation_id))
    return {
        "dest": str(dest),
        "integrity": integrity,
        "envelope": envelope.to_dict() if envelope else None,
        "consultation_id": envelope.consultation_id if envelope else consultation_id,
    }


def record_and_upload_response(
    *, transport, consultation_id: str, package_root, from_user: dict,
    text: str = "", report_ref: str = "", attachments_ref=None,
    root_remote_id: str | None = None, progress_cb=None,
) -> str:
    """Reviewer adds a response, re-seals, and uploads it back into the SHARED folder."""
    from database import consultation_db

    from .service import record_response
    from ..sync.engine import CloudSyncEngine

    record_response(
        package_root, from_user=from_user, text=text,
        report_ref=report_ref, attachments_ref=attachments_ref,
    )
    rfid = root_remote_id or (consultation_db.get_consultation(consultation_id) or {}).get("remote_folder_id")
    engine = CloudSyncEngine(transport, progress_cb=progress_cb)
    engine.upload(consultation_id, package_root, root_remote_id=rfid)
    consultation_db.update_consultation_fields(consultation_id, status="answered")
    from ..notifications.models import NotificationKind

    _notify(NotificationKind.CONSULTATION_UPDATED, title="Response sent",
            body="Your opinion was uploaded to the shared consultation folder.",
            consultation_id=consultation_id)
    return consultation_id


def close_consultation(consultation_id: str, *, actor_handle: str = "") -> bool:
    """Mark a consultation closed (terminal) after the originator reviewed the answer.

    Validates the transition against the state machine, records the audit event, and
    raises a local "completed" notification. Returns True on success.
    """
    from database import consultation_db

    from ..sync.state_machine import assert_transition

    row = consultation_db.get_consultation(consultation_id)
    if row is None:
        raise ValueError(f"Unknown consultation: {consultation_id!r}")
    assert_transition(str(row.get("status") or "pending"), "closed")
    consultation_db.update_consultation_fields(consultation_id, status="closed")
    consultation_db.add_event(
        consultation_id, "closed", actor_handle=actor_handle, details="closed by originator"
    )
    from ..notifications.models import NotificationKind

    _notify(NotificationKind.CONSULTATION_UPDATED, title="Consultation completed",
            body=row.get("case_title", ""), consultation_id=consultation_id)
    return True
