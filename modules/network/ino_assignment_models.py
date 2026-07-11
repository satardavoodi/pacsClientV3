# -*- coding: utf-8 -*-
"""Internal-center (INO) assignment — state model, constants and labels.

This is the **internal, same-center** assignment workflow (assign a radiologist
or typist to a reception's studies through INO/RIS). It is **completely
separate** from the AI-PACS **Consultation / External Assignment** workflow
(`modules/cloud_consultation` / `modules/education/online_consultation`):

* Internal assignment = operational work-routing **inside one center**, free of
  charge, based on INO/RIS users + roles + center membership. No image upload,
  no Google Drive, no AI-PACS website submission, **no payment**, no cross-center.
* External consultation = a separate, unchanged feature (de-identified case sent
  to another physician/center, possibly paid).

Pure stdlib — no Qt, no network, no consultation imports — so it stays trivially
testable and cannot pull in the external workflow. See
`docs/reports/ASSIGNMENT_WORKFLOWS_REVIEW_INO_VS_EDUCATION_2026-07-09.md`.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
from typing import Any, Dict, List, Optional

# --- Assignment kinds (who is being assigned) --------------------------------
ASSIGN_TYPE_RADIOLOGIST = "radiologist"   # reporting physician
ASSIGN_TYPE_TYPIST = "typist"             # report typist
ASSIGN_TYPES = (ASSIGN_TYPE_RADIOLOGIST, ASSIGN_TYPE_TYPIST)

# --- Assignee source (which INO/RIS directory the user came from) ------------
ASSIGNEE_SOURCE_PACS = "pacs"                 # local MongoDB `users`
ASSIGNEE_SOURCE_RIS_PERSONNEL = "ris_personnel"  # RIS `Personnel._id` (usually radiologist)
ASSIGNEE_SOURCE_RIS_USER = "ris_user"         # RIS `AdminUser._id` (usually typist)
ASSIGNEE_SOURCES = (
    ASSIGNEE_SOURCE_PACS,
    ASSIGNEE_SOURCE_RIS_PERSONNEL,
    ASSIGNEE_SOURCE_RIS_USER,
)

# --- Local action/history kinds (this workstation's own record) --------------
# These describe the LOCAL assignment action recorded in the internal history —
# they are intentionally distinct from any consultation status vocabulary.
ACTION_ASSIGNED = "assigned"
ACTION_REASSIGNED = "reassigned"
ACTION_UNASSIGNED = "unassigned"
ACTION_FAILED = "failed"
ACTION_STATUS_CHANGED = "status_changed"
ACTIONS = (ACTION_ASSIGNED, ACTION_REASSIGNED, ACTION_UNASSIGNED, ACTION_FAILED,
           ACTION_STATUS_CHANGED)

# --- Assignment LIFECYCLE STATUS (state of an existing assignment) ------------
# IMPORTANT — which transitions the backend actually backs:
#   * assign / reassign  → SERVER (PUT /api/patients/{id}/assign) ⇒ becomes ACTIVE
#   * cancel / unassign  → SERVER (assign with an empty assignee)  ⇒ CANCELLED
#   * completed / deactivated → NO INO endpoint exists for these; they are LOCAL
#     workflow states recorded in the internal history (server_ok=False) and are
#     labelled as local in the UI. Never present them as server-confirmed.
STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"
STATUS_DEACTIVATED = "deactivated"
STATUS_CANCELLED = "cancelled"
ASSIGNMENT_STATUSES = (STATUS_ACTIVE, STATUS_COMPLETED, STATUS_DEACTIVATED,
                       STATUS_CANCELLED)
# Statuses that require a real server call to reach.
SERVER_BACKED_STATUSES = (STATUS_ACTIVE, STATUS_CANCELLED)

STATUS_LABELS_EN = {
    STATUS_ACTIVE: "Active",
    STATUS_COMPLETED: "Completed",
    STATUS_DEACTIVATED: "Deactivated",
    STATUS_CANCELLED: "Cancelled",
}
STATUS_LABELS_FA = {
    STATUS_ACTIVE: "فعال",
    STATUS_COMPLETED: "تکمیل‌شده",
    STATUS_DEACTIVATED: "غیرفعال",
    STATUS_CANCELLED: "لغو شده",
}
STATUS_COLORS = {
    STATUS_ACTIVE: "#f59e0b",       # amber — assigned, work in progress
    STATUS_COMPLETED: "#10b981",    # green
    STATUS_DEACTIVATED: "#6b7280",  # gray
    STATUS_CANCELLED: "#ef4444",    # red
}


def status_label(status: str, lang: str = "en") -> str:
    s = str(status or "").strip().lower()
    table = STATUS_LABELS_FA if lang == "fa" else STATUS_LABELS_EN
    return table.get(s, s.capitalize() if s else "")


def status_color(status: str) -> str:
    return STATUS_COLORS.get(str(status or "").strip().lower(), "#6b7280")


# --- Patient-list Assign-column icon, per lifecycle status --------------------
# One pure mapping so the initial row render and the post-change refresh cannot
# drift apart. Icons are qtawesome (fa5s) names.
STATUS_ICON_UNASSIGNED = "fa5s.user-times"

ASSIGN_ICONS = {
    STATUS_ACTIVE:      ("fa5s.user-check",   "#ef4444"),  # red   — assigned, action needed
    STATUS_COMPLETED:   ("fa5s.check-circle", "#10b981"),  # green — done (shape + colour differ)
    STATUS_DEACTIVATED: ("fa5s.user-minus",   "#6b7280"),  # gray  — inactive
    STATUS_CANCELLED:   ("fa5s.user-slash",   "#9ca3af"),  # gray  — crossed-out
}
_ASSIGN_ICON_NONE = (STATUS_ICON_UNASSIGNED, "#6b7280")    # never assigned


def assign_icon_for_status(status: str, assignee_name: str = "") -> Dict[str, str]:
    """Icon name / colour / tooltip for the patient-list Assign column.

    ``status`` is the value from :func:`resolve_assignment_status` (i.e. derived
    from the persisted, ``server_ok``-gated record — never from transient UI
    state). An empty/unknown status renders the neutral "not assigned" icon.
    """
    st = str(status or "").strip().lower()
    icon, color = ASSIGN_ICONS.get(st, _ASSIGN_ICON_NONE)
    who = str(assignee_name or "").strip()
    if st == STATUS_ACTIVE:
        tip = f"Assigned (active) — {who}" if who else "Assigned (active)"
    elif st == STATUS_COMPLETED:
        tip = f"Assignment completed — {who}" if who else "Assignment completed"
    elif st == STATUS_DEACTIVATED:
        tip = f"Assignment deactivated — {who}" if who else "Assignment deactivated"
    elif st == STATUS_CANCELLED:
        tip = "Assignment cancelled"
    else:
        tip = "Not assigned"
    return {"icon": icon, "color": color, "tooltip": tip, "status": st}


def resolve_assignment_status(rows: List[Dict[str, Any]]) -> str:
    """Current lifecycle status from the reception's history rows (chronological).

    A server-confirmed assign/reassign makes it ACTIVE; a confirmed unassign makes
    it CANCELLED; an explicit local ``status_changed`` record (completed /
    deactivated / …) overrides. ``failed`` rows are ignored. Returns "" when the
    reception has never been assigned.
    """
    status = ""
    for r in rows or []:
        act = str(r.get("action") or "").strip().lower()
        if act == ACTION_STATUS_CHANGED:
            s = str(r.get("assignment_status") or "").strip().lower()
            if s in ASSIGNMENT_STATUSES:
                status = s
            continue
        if not r.get("server_ok"):
            continue  # a failed/local-only assign never changes the state
        if act in (ACTION_ASSIGNED, ACTION_REASSIGNED):
            status = STATUS_ACTIVE
        elif act == ACTION_UNASSIGNED:
            status = STATUS_CANCELLED
    return status

# --- Labels (Persian + English) — internal-assignment terminology ------------
# Deliberately NOT "consultation": these read as an internal operational action.
FEATURE_LABEL_FA = "ارجاع داخلی مرکز"
FEATURE_LABEL_EN = "Internal Assignment"

ASSIGN_TYPE_LABELS_FA = {
    ASSIGN_TYPE_RADIOLOGIST: "پزشک گزارش‌دهنده (رادیولوژیست)",
    ASSIGN_TYPE_TYPIST: "تایپیست گزارش",
}
ASSIGN_TYPE_LABELS_EN = {
    ASSIGN_TYPE_RADIOLOGIST: "Reporting radiologist",
    ASSIGN_TYPE_TYPIST: "Report typist",
}
ASSIGNEE_SOURCE_LABELS_FA = {
    ASSIGNEE_SOURCE_PACS: "کاربر PACS",
    ASSIGNEE_SOURCE_RIS_PERSONNEL: "پرسنل پذیرش (RIS)",
    ASSIGNEE_SOURCE_RIS_USER: "کاربر مرکز (RIS)",
}
ACTION_LABELS_FA = {
    ACTION_ASSIGNED: "ارجاع داده شد",
    ACTION_REASSIGNED: "ارجاع تغییر کرد",
    ACTION_UNASSIGNED: "ارجاع لغو شد",
    ACTION_FAILED: "ارجاع ناموفق",
}

# Messages the (future) UI can reuse — kept here so they stay separate from the
# consultation messages.
MSG_PERMISSION_DENIED_FA = "شما مجاز به ارجاع داخلی این پرونده نیستید."
MSG_NO_SERVER_FA = "سرور پذیرش (INO) در دسترس نیست."
MSG_ASSIGNED_OK_FA = "پرونده با موفقیت ارجاع داده شد."


# --- Reporter cell colour semantics (patient list) ---------------------------
# RED = assigned to a physician but reporting NOT yet completed.
# GREEN = report completed / final. These are SEMANTICALLY distinct even though
# the same cell shows a name — an assigned physician is not a completed reporter.
COLOR_ASSIGNED_PENDING = "#ef4444"   # red
COLOR_COMPLETED = "#10b981"          # green
_COMPLETED_STATES = ("completed", "complete")


def reporter_display(report_status: str, physician_name: str):
    """Return ``(text, color_hex)`` for the patient-list reporter cell.

    * completed → the name in GREEN (final reporting physician).
    * a name present but not completed → the name in RED (assigned, pending).
    * no usable name → ``("", "")`` so the caller falls back to the status icon.
    Pure — no Qt. Lets the color logic be unit-tested and shared.
    """
    name = str(physician_name or "").strip()
    # Drop obviously non-name values (ids / "ID:" markers).
    if name.startswith("ID:"):
        name = ""
    if len(name) == 24 and all(c in "0123456789abcdefABCDEF" for c in name):
        name = ""
    if " (ID:" in name:
        name = name.split(" (ID:", 1)[0].strip()
    if not name:
        return "", ""
    status = str(report_status or "").strip().lower()
    if status in _COMPLETED_STATES:
        return name, COLOR_COMPLETED
    return name, COLOR_ASSIGNED_PENDING


def is_valid_assign_type(value: str) -> bool:
    return value in ASSIGN_TYPES


def is_valid_source(value: str) -> bool:
    return value in ASSIGNEE_SOURCES


def assign_type_label(value: str, lang: str = "fa") -> str:
    table = ASSIGN_TYPE_LABELS_EN if lang == "en" else ASSIGN_TYPE_LABELS_FA
    return table.get(value, value)


def default_source_for_type(assign_type: str) -> str:
    """Best-default assignee source for an assign type (radiologist→personnel,
    typist→center user). The UI can still let the user override the source."""
    if assign_type == ASSIGN_TYPE_TYPIST:
        return ASSIGNEE_SOURCE_RIS_USER
    return ASSIGNEE_SOURCE_RIS_PERSONNEL


@dataclasses.dataclass
class AssignableUser:
    """A user returned by the INO assignable-users list."""
    id: str
    full_name: str
    source: str
    username: str = ""
    role: str = ""
    personnel_id: str = ""
    is_active: bool = True
    assign_types: List[str] = dataclasses.field(default_factory=list)

    @classmethod
    def from_api(cls, row: Dict[str, Any]) -> "AssignableUser":
        return cls(
            id=str(row.get("id") or row.get("_id") or ""),
            full_name=str(row.get("full_name") or row.get("fullName") or row.get("name") or ""),
            source=str(row.get("source") or ""),
            username=str(row.get("username") or ""),
            role=str(row.get("role") or ""),
            personnel_id=str(row.get("personnel_id") or row.get("personnelId") or ""),
            is_active=bool(row.get("is_active", True)),
            assign_types=list(row.get("assign_types") or []),
        )

    @classmethod
    def from_personnel(cls, row: Dict[str, Any]) -> "AssignableUser":
        """Map an INO `GET /api/personnel` row (radiologist/physician source)."""
        name = (str(row.get("FirstName") or "") + " " + str(row.get("LastName") or "")).strip()
        return cls(
            id=str(row.get("_id") or ""),
            full_name=name or str(row.get("FullName") or ""),
            source=ASSIGNEE_SOURCE_RIS_PERSONNEL,
            username=str(row.get("PersonnelCode") or ""),
            role=str(row.get("PersonnelType") or row.get("Position") or ""),
            personnel_id=str(row.get("_id") or ""),
            is_active=not bool(row.get("Deactive")) and bool(row.get("IsActive", True)),
            assign_types=[ASSIGN_TYPE_RADIOLOGIST],
        )

    @classmethod
    def from_center_user(cls, row: Dict[str, Any]) -> "AssignableUser":
        """Map an INO `GET /api/AdminUser/getCenterUsers` row (center user / typist)."""
        roles = row.get("roles")
        role_name = ""
        if isinstance(roles, dict):
            role_name = str(roles.get("Name") or "")
        elif isinstance(roles, str):
            role_name = roles
        return cls(
            id=str(row.get("_id") or ""),
            full_name=str(row.get("FullName") or row.get("EnglishName") or row.get("User") or ""),
            source=ASSIGNEE_SOURCE_RIS_USER,
            username=str(row.get("User") or ""),
            role=role_name,
            personnel_id=str(row.get("PersonnelID") or ""),
            is_active=not bool(row.get("Deactive")),
            assign_types=[ASSIGN_TYPE_TYPIST],
        )


@dataclasses.dataclass
class AssignmentRecord:
    """One local internal-assignment action (for the separate history log)."""
    reception_id: str
    assign_type: str
    assignee_id: str
    assignee_name: str
    assignee_source: str
    action: str = ACTION_ASSIGNED
    study_uid: str = ""
    assigned_by: str = ""
    comment: str = ""              # optional user note captured at assign time
    assignment_status: str = ""    # set on ACTION_STATUS_CHANGED rows
    server_ok: bool = False
    message: str = ""
    timestamp: str = dataclasses.field(
        default_factory=lambda: _dt.datetime.now().isoformat(timespec="seconds")
    )

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)
