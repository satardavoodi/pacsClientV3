"""Qt-free decision logic for the Assign-consultation popup + registry merge.

ADR-0006: consultations are either **internal** (registry record on the AI-PACS
web backend only — NO image upload, no Drive involvement) or **external** (the
existing Drive package flow, plus a best-effort registry record carrying the
``drive_folder_id``). This module owns the routing decision, the payload shapes,
and the Inbox/Sent merge of registry rows alongside the Drive rows — all pure
Python so it is unit-testable headless. The Qt dialog/page in
``assign_dialog.py`` / ``consultation_page.py`` only composes these pieces.
"""

from __future__ import annotations

INTERNAL = "internal"
EXTERNAL = "external"

# Internal registry rows carry this caption in the UI so a physician can never
# mistake them for an image-bearing Drive consultation.
INTERNAL_ROW_TAG = "Internal — no image upload"


# ── consultant profile helpers ─────────────────────────────────────────────────
def consultant_kind(consultant: dict) -> str:
    """``internal`` or ``external`` for a consultant profile row.

    Reads ``type`` (ADR-0006 contract); tolerates legacy/alternate keys. An
    unknown value defaults to INTERNAL — the clinically safer route (no images
    ever leave the workstation by default).
    """
    raw = str(
        (consultant or {}).get("type")
        or (consultant or {}).get("consultant_type")
        or (consultant or {}).get("kind")
        or ""
    ).strip().lower()
    if raw in (INTERNAL, EXTERNAL):
        return raw
    if (consultant or {}).get("is_external"):
        return EXTERNAL
    return INTERNAL


def consultant_address(consultant: dict) -> str:
    """The routing address for a consultant (consultation_address > email)."""
    c = consultant or {}
    return str(
        c.get("consultation_address") or c.get("address") or c.get("email") or ""
    ).strip()


def consultant_display(consultant: dict) -> dict:
    """UI-facing snapshot: name, specialty, availability, badge, address."""
    c = consultant or {}
    kind = consultant_kind(c)
    return {
        "name": str(c.get("name") or c.get("full_name") or consultant_address(c) or "Consultant"),
        "specialty": str(c.get("specialty") or c.get("speciality") or ""),
        "availability": str(c.get("availability") or c.get("availability_note") or ""),
        "kind": kind,
        "badge": "Internal" if kind == INTERNAL else "External",
        "address": consultant_address(c),
    }


# ── routing + payloads ─────────────────────────────────────────────────────────
def decide_route(consultant: dict) -> str:
    """INTERNAL → registry-only POST; EXTERNAL → existing Drive flow (+registry)."""
    return consultant_kind(consultant)


def build_patient_ref(patient_id: str, patient_name: str) -> str:
    """The registry ``patient_ref``: ``"<PatientID> <patient name>"``."""
    pid = str(patient_id or "").strip()
    name = str(patient_name or "").replace("^", " ").strip()
    return f"{pid} {name}".strip()


def build_internal_payload(
    consultant: dict, patient_id: str, patient_name: str,
    study_uid: str = "", note: str = "",
) -> dict:
    """POST body for an internal consultation. NO Drive fields, ever."""
    addr = consultant_address(consultant)
    if not addr:
        raise ValueError("The selected consultant has no consultation address.")
    payload = {
        "type": INTERNAL,
        "consultant_address": addr,
        "patient_ref": build_patient_ref(patient_id, patient_name),
    }
    if study_uid:
        payload["study_uid"] = str(study_uid)
    if note:
        payload["note"] = str(note)
    return payload


def build_external_registry_payload(
    consultant: dict, patient_id: str, patient_name: str,
    study_uid: str = "", note: str = "", drive_folder_id: str = "",
) -> dict:
    """Best-effort registry record AFTER a successful external Drive upload."""
    addr = consultant_address(consultant)
    if not addr:
        raise ValueError("The selected consultant has no consultation address.")
    payload = {
        "type": EXTERNAL,
        "consultant_address": addr,
        "patient_ref": build_patient_ref(patient_id, patient_name),
    }
    if study_uid:
        payload["study_uid"] = str(study_uid)
    if note:
        payload["note"] = str(note)
    if drive_folder_id:
        payload["drive_folder_id"] = str(drive_folder_id)
    return payload


# ── Inbox/Sent merge of registry rows (Education tab) ──────────────────────────
def registry_rows_to_display(registry_rows: list[dict], drive_rows: list[dict]) -> list[dict]:
    """Registry rows to APPEND to the existing Drive rows in Inbox/Sent.

    * internal rows are always shown (tagged :data:`INTERNAL_ROW_TAG`);
    * external registry rows that mirror an already-displayed Drive row
      (matching ``drive_folder_id`` ↔ ``remote_folder_id``) are dropped —
      the Drive row is the authoritative display for those.

    Drive rows are NEVER modified — this merge is purely additive.
    """
    known_folders = {
        str(d.get("remote_folder_id") or "").strip()
        for d in (drive_rows or [])
        if d.get("remote_folder_id")
    }
    out: list[dict] = []
    for r in registry_rows or []:
        r = dict(r or {})
        kind = str(r.get("type") or INTERNAL).strip().lower()
        folder = str(r.get("drive_folder_id") or "").strip()
        if kind == EXTERNAL and folder and folder in known_folders:
            continue  # already shown as a Drive row
        r["_registry"] = True
        r["_tag"] = INTERNAL_ROW_TAG if kind != EXTERNAL else "External (registry)"
        out.append(r)
    return out


# Allowed actions per registry status and box. The registry status vocabulary is
# the Laravel side's (ADR-0006): pending → accepted/declined → answered → closed.
_INBOX_ACTIONS = {
    "pending": ["accept", "decline"],
    "accepted": ["answer"],
    "answered": [],
}
_SENT_ACTIONS = {
    "pending": ["close"],
    "accepted": [],
    "answered": ["close"],
}

# action id → PATCH body
_ACTION_PATCH = {
    "accept": {"status": "accepted"},
    "decline": {"status": "declined"},
    "answer": {"status": "answered"},
    "close": {"status": "closed"},
}

# action id → button caption
ACTION_LABELS = {
    "accept": "Accept",
    "decline": "Decline",
    "answer": "Answer…",
    "close": "Close",
}


def registry_actions(row: dict, box: str) -> list[str]:
    """Action ids available for a registry row in ``inbox`` or ``sent``."""
    status = str((row or {}).get("status") or "pending").strip().lower()
    table = _INBOX_ACTIONS if box == "inbox" else _SENT_ACTIONS
    return list(table.get(status, []))


def action_patch(action: str, answer_text: str = "") -> dict:
    """PATCH body for an action; ``answer`` may carry the consultant's text."""
    patch = dict(_ACTION_PATCH.get(action) or {})
    if not patch:
        raise ValueError(f"Unknown registry action: {action!r}")
    if action == "answer" and answer_text:
        patch["answer"] = str(answer_text)
    return patch
