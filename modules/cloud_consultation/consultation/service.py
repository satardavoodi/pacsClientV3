"""High-level consultation operations on a package folder (envelope-centric).

These functions are transport- and engine-agnostic: they only read/write the
``consultation.json`` sibling and hash the package files. The actual *ingest* of a
downloaded package into the local database reuses the EXISTING offline engine and is
wired in a later phase:

    from PacsClient.utils.offline_cloud import (
        validate_offline_cloud_package, sync_offline_cloud_study_to_local)
    # after verify_integrity(...)["ok"]:
    #   validate_offline_cloud_package(package_root)
    #   sync_offline_cloud_study_to_local(package_root, study_uid, ...)

Keeping that out of here means Phase 3 has no hard dependency on the clinical engine
and stays fully unit-testable.
"""

from __future__ import annotations

import logging
import uuid

from .envelope import (
    _utc_now_iso,
    add_response as _add_response,
    build_envelope,
    read_envelope,
    seal_envelope,
    verify_integrity,
)
from .models import ConsultationEnvelope, ConsultationResponse, ConsultationStatus

logger = logging.getLogger(__name__)


def seal_package_as_consultation(
    package_root, *, case_title: str, clinical_question: str, from_user: dict,
    assignee: dict | None = None, study_uids: list | None = None,
    priority: str = "routine", due_at: str = "",
) -> ConsultationEnvelope:
    """Turn an existing Offline Cloud package folder into a consultation package by
    writing a sealed ``consultation.json``. The offline package is not modified."""
    env = build_envelope(
        case_title=case_title,
        clinical_question=clinical_question,
        from_user=from_user,
        assignee=assignee,
        study_uids=study_uids,
        priority=priority,
        due_at=due_at,
    )
    return seal_envelope(package_root, env)


def open_consultation_package(package_root, *, verify: bool = True) -> dict:
    """Read and (optionally) verify a package before review/ingest.

    Returns ``{is_consultation, envelope, integrity}``. A normal (non-consultation)
    offline package yields ``is_consultation=False`` — fully backward compatible.
    """
    env = read_envelope(package_root)
    if env is None:
        return {"is_consultation": False, "envelope": None, "integrity": None}
    integrity = verify_integrity(package_root) if verify else None
    return {"is_consultation": True, "envelope": env, "integrity": integrity}


def record_response(
    package_root, *, from_user: dict, text: str = "", kind: str = "opinion",
    report_ref: str = "", attachments_ref: list | None = None,
    new_status: str = ConsultationStatus.ANSWERED.value,
) -> ConsultationEnvelope:
    """Append a physician's response (opinion/report) and re-seal the package."""
    response = ConsultationResponse(
        response_id=str(uuid.uuid4()),
        from_user=dict(from_user or {}),
        created_at=_utc_now_iso(),
        kind=kind,
        text=text,
        report_ref=report_ref,
        attachments_ref=list(attachments_ref or []),
    )
    return _add_response(package_root, response, new_status=new_status)
