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
#
# THREE states (2026-07-14). "Deactivate", "Cancel" and "Unassign" all meant the
# same thing in practice — the assignment is taken off the user and the patient —
# so they are ONE terminal state: REMOVED. Keeping three names for one state was
# the source of the confusing menus and of the "Cancel does nothing" report.
#
# WHAT THE SERVER ACTUALLY MODELS (verified against its OpenAPI schema, not guessed):
#   PUT /api/patients/{id}/assign   AssignPayload{assign_type, assignee_id(minLength=1),
#                                   assignee_name, assignee_source, study_uid}
#   GET /api/patients/{id}/assign   → {radiologist:{id,name,source}, typist:{...}}
#   * There is **NO status field anywhere in the server's assign model.** ACTIVE /
#     COMPLETED / REMOVED are entirely CLIENT-side lifecycle states.
#   * The server's only notion of "assigned" is a non-empty ``radiologistId`` —
#     which is exactly how we read it back (empty id ⇒ not assigned).
#   * `assignee_id` has **minLength=1**, and there is **no DELETE verb** (405), so
#     the server currently offers NO way to clear an assignment. See
#     InternalAssignmentService.remove_assignment() — it calls the correct endpoint
#     and surfaces the server's real refusal rather than faking a removal.
STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"
STATUS_REMOVED = "removed"        # deactivate == cancel == unassign
ASSIGNMENT_STATUSES = (STATUS_ACTIVE, STATUS_COMPLETED, STATUS_REMOVED)

# Legacy aliases — old history rows on disk still carry these; they all normalize
# to REMOVED. Kept so an existing record never renders as an unknown status.
STATUS_DEACTIVATED = "deactivated"
STATUS_CANCELLED = "cancelled"
STATUS_UNASSIGNED = "unassigned"
_REMOVED_ALIASES = (STATUS_REMOVED, STATUS_DEACTIVATED, STATUS_CANCELLED,
                    STATUS_UNASSIGNED, "deactive", "cancel", "unassign")

#: Statuses that require a real server call. REMOVED does (it must clear the
#: assignment on the server); COMPLETED is a local workflow state only.
SERVER_BACKED_STATUSES = (STATUS_ACTIVE, STATUS_REMOVED)


def normalize_status(status: str) -> str:
    """Map any legacy/loose status onto one of the THREE canonical states.

    ``deactivated`` / ``cancelled`` / ``unassigned`` (and their loose spellings) all
    mean the assignment is gone ⇒ :data:`STATUS_REMOVED`. Unknown ⇒ "".
    """
    s = str(status or "").strip().lower()
    if not s:
        return ""
    if s in _REMOVED_ALIASES:
        return STATUS_REMOVED
    if s in (STATUS_ACTIVE, STATUS_COMPLETED):
        return s
    return ""


STATUS_LABELS_EN = {
    STATUS_ACTIVE: "Active",
    STATUS_COMPLETED: "Completed",
    STATUS_REMOVED: "Removed",
}
STATUS_LABELS_FA = {
    STATUS_ACTIVE: "فعال",
    STATUS_COMPLETED: "تکمیل‌شده",
    STATUS_REMOVED: "حذف‌شده",
}
STATUS_COLORS = {
    STATUS_ACTIVE: "#f59e0b",       # amber — assigned, work in progress
    STATUS_COMPLETED: "#10b981",    # green — done
    STATUS_REMOVED: "#6b7280",      # gray  — no longer assigned
}


#: THE lifecycle transition table — ONE definition, shared by every entry point
#: (the Assign column menu, the Assign popup and the Report popup), so they can
#: never offer different actions for the same state.
ASSIGN_TRANSITIONS = {
    STATUS_ACTIVE:    (STATUS_COMPLETED, STATUS_REMOVED),
    STATUS_COMPLETED: (STATUS_ACTIVE, STATUS_REMOVED),
    STATUS_REMOVED:   (STATUS_ACTIVE,),           # re-assign brings it back
    "":               (),                          # never assigned → nothing to manage
}

#: What each action is called in the UI, and whether the SERVER backs it.
ASSIGN_ACTION_LABELS_EN = {
    STATUS_COMPLETED: "Mark as completed",
    STATUS_REMOVED:   "Remove assignment (deactivate / cancel / unassign)",
    STATUS_ACTIVE:    "Reactivate assignment",
}


def action_is_server_backed(status: str) -> bool:
    """True when the action hits the server (REMOVED does; COMPLETED does not).

    The server's assign model has NO status field — ``completed`` exists only in
    our local history, so the UI must label it as a local workflow state and must
    never imply the server confirmed it.
    """
    return normalize_status(status) in SERVER_BACKED_STATUSES


def status_label(status: str, lang: str = "en") -> str:
    # Normalize first: a legacy "cancelled"/"deactivated" row must read "Removed".
    s = normalize_status(status)
    table = STATUS_LABELS_FA if lang == "fa" else STATUS_LABELS_EN
    return table.get(s, s.capitalize() if s else "")


def status_color(status: str) -> str:
    return STATUS_COLORS.get(normalize_status(status), "#6b7280")


# --- Eligible-user GROUPING (shared by every internal-assignment UI) ----------
# INO returns two distinct populations that must be shown separately:
#   ris_personnel → Personnel / Staff Management (primarily physicians)
#   ris_user      → Center Users (physicians + secretaries / other)
# This lives in CORE so both entry points (the Assign column and the Reporting
# Physician column) group users identically. Pure — no Qt, no I/O.
GROUP_PHYSICIANS = ASSIGNEE_SOURCE_RIS_PERSONNEL
GROUP_USERS = ASSIGNEE_SOURCE_RIS_USER
GROUP_OTHER = "other"

GROUP_TITLES = {
    GROUP_PHYSICIANS: "پزشکان (پرسنل مرکز) — Physicians",
    GROUP_USERS: "کاربران مرکز (منشی/سایر) — Users / Secretaries",
    GROUP_OTHER: "سایر — Other",
}
_GROUP_ORDER = (GROUP_PHYSICIANS, GROUP_USERS, GROUP_OTHER)


def partition_user_groups(users: List[Any]) -> List[tuple]:
    """Split eligible users into ordered, labelled groups.

    Accepts either :class:`AssignableUser` objects or plain dicts carrying a
    ``source`` / ``_ino_source`` key. Returns ``[(group_key, title, [users])]``
    in stable order (physicians → users/secretaries → other), omitting empty
    groups.
    """
    buckets: Dict[str, List[Any]] = {k: [] for k in _GROUP_ORDER}
    for u in users or []:
        src = getattr(u, "source", None)
        if src is None and isinstance(u, dict):
            src = u.get("source") or u.get("_ino_source")
        src = str(src or "").strip()
        key = src if src in (GROUP_PHYSICIANS, GROUP_USERS) else GROUP_OTHER
        buckets[key].append(u)
    return [(k, GROUP_TITLES[k], buckets[k]) for k in _GROUP_ORDER if buckets[k]]


# --- Person-name comparison (assignee vs displayed reporting physician) -------
_NAME_TITLES = ("دکتر", "دكتر", "پزشک", "dr.", "dr", "doctor", "prof.", "prof")


def _normalize_person_name(name: str) -> str:
    s = str(name or "").strip().lower()
    # drop an "(ID: …)" suffix and collapse whitespace
    if " (id:" in s:
        s = s.split(" (id:", 1)[0]
    s = " ".join(s.replace("‌", " ").split())
    for t in _NAME_TITLES:
        if s.startswith(t + " "):
            s = s[len(t) + 1:]
        s = s.replace(" " + t + " ", " ")
    return " ".join(s.split())


def same_person_name(a: str, b: str) -> bool:
    """True when two person names refer to the same person.

    Tolerates titles (دکتر / Dr.), zero-width joiners, extra whitespace and an
    "(ID: …)" suffix. Used to decide whether the physician shown in the Report
    column IS the internal assignee — red must never be shown for a *different*
    physician.
    """
    na, nb = _normalize_person_name(a), _normalize_person_name(b)
    return bool(na) and na == nb


# --- Patient-list Assign-column icon, per lifecycle status --------------------
# One pure mapping so the initial row render and the post-change refresh cannot
# drift apart. Icons are qtawesome (fa5s) names.
STATUS_ICON_UNASSIGNED = "fa5s.user-times"

ASSIGN_ICONS = {
    STATUS_ACTIVE:    ("fa5s.user-check",   "#ef4444"),  # red   — assigned, action needed
    STATUS_COMPLETED: ("fa5s.check-circle", "#10b981"),  # green — done
    STATUS_REMOVED:   ("fa5s.user-slash",   "#9ca3af"),  # gray  — taken off the user
}
_ASSIGN_ICON_NONE = (STATUS_ICON_UNASSIGNED, "#6b7280")    # never assigned


def assign_icon_for_status(status: str, assignee_name: str = "") -> Dict[str, str]:
    """Icon name / colour / tooltip for the patient-list Assign column.

    ``status`` is the value from :func:`resolve_assignment_status` (i.e. derived
    from the persisted, ``server_ok``-gated record — never from transient UI
    state). An empty/unknown status renders the neutral "not assigned" icon.
    """
    st = normalize_status(status)
    icon, color = ASSIGN_ICONS.get(st, _ASSIGN_ICON_NONE)
    who = str(assignee_name or "").strip()
    if st == STATUS_ACTIVE:
        tip = f"Assigned (active) — {who}" if who else "Assigned (active)"
    elif st == STATUS_COMPLETED:
        tip = f"Assignment completed — {who}" if who else "Assignment completed"
    elif st == STATUS_REMOVED:
        tip = "Assignment removed"
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
            s = normalize_status(r.get("assignment_status"))
            if s:
                status = s
            continue
        if not r.get("server_ok"):
            continue  # a failed/local-only assign never changes the state
        if act in (ACTION_ASSIGNED, ACTION_REASSIGNED):
            status = STATUS_ACTIVE
        elif act == ACTION_UNASSIGNED:
            status = STATUS_REMOVED
    return status


#: Report-workflow statuses that mean the reporting work is DONE. When the report
#: is finished, an assignment is no longer "active" — it is COMPLETED. Without this
#: every reception that has a reporting radiologist rendered the same red "active"
#: icon forever, which is what made the whole Assign column red.
REPORT_DONE_STATUSES = frozenset({
    "completed", "complete", "archived",
    "physician_approved", "secretary_approved",
})


def report_is_done(report_status: str) -> bool:
    return str(report_status or "").strip().lower() in REPORT_DONE_STATUSES


def effective_assign_status(assign_status: str, report_status: str) -> str:
    """PURE. The Assign column's lifecycle state (2026-07-14).

    An ACTIVE assignment whose report is finished is a **completed** assignment —
    it must not keep showing the red "needs action" icon. Terminal local states
    (cancelled / deactivated / completed) are never overridden by the report.
    """
    st = str(assign_status or "").strip().lower()
    if st == STATUS_ACTIVE and report_is_done(report_status):
        return STATUS_COMPLETED
    return st


def merge_assignment_status(
    server_assigned: Optional[bool],
    server_name: str,
    local_status: str,
    local_name: str = "",
) -> Dict[str, str]:
    """PURE. Reconcile the SERVER's answer with the LOCAL lifecycle log (2026-07-14).

    Division of authority:

    * **The server owns "is this patient assigned, and to whom".** That is the only
      dimension it stores (``active`` / ``cancelled``), and it is the dimension that
      was previously invisible — an assignment made on ANOTHER workstation lives
      only on the server, so the local log can never see it (patient 50210).
    * **The local log owns ``completed``** — the one lifecycle state with no server
      endpoint, layered on top of a server assignment. The server refresh must not
      clobber it.

    ``server_assigned=None`` means "not fetched / the call failed" — NOT
    "unassigned". In that case the local status stands, so an unreachable server
    never wipes a known assignment.

    Returns ``{"status": ..., "assignee_name": ...}`` — the status is always one of
    the THREE canonical states (or "" for never assigned).
    """
    local = normalize_status(local_status)
    lname = str(local_name or "").strip()
    sname = str(server_name or "").strip()

    if server_assigned is None:
        return {"status": local, "assignee_name": lname}

    # The server always has the authoritative NAME when it has an assignment.
    name = sname or lname

    if server_assigned:
        # A local COMPLETED sits on top of a still-present server assignment.
        # A local REMOVED, however, is stale: the server says the assignment is
        # still there, and the server is the authority on that dimension.
        if local == STATUS_COMPLETED:
            return {"status": STATUS_COMPLETED, "assignee_name": name}
        return {"status": STATUS_ACTIVE, "assignee_name": name}

    # Server says there is no assignment.
    if local == STATUS_COMPLETED:
        # The work was finished here and the assignment was then cleared; keep the
        # terminal local state rather than showing it as removed.
        return {"status": STATUS_COMPLETED, "assignee_name": lname}
    if local:
        return {"status": STATUS_REMOVED, "assignee_name": lname}
    return {"status": "", "assignee_name": ""}

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


# REMOVED 2026-07-10 — `reporter_display(report_status, physician_name)`.
#
# It returned RED for ANY non-completed report that merely had a reporting
# physician set in the RIS workflow — it never looked at the internal-assignment
# record. Once the feature became default-ON this painted unassigned patients red
# (reported on 49868 / 49836) with a tooltip falsely claiming "Assigned to …".
#
# RED in the Report column must be derived ONLY from an ACTIVE internal
# assignment whose assignee is the physician being displayed:
#     ino_assignment_history.current_assignment_details(reception_id)
#       → assignment_status == STATUS_ACTIVE
#       → same_person_name(assignee_name, displayed_physician)
# Do NOT reintroduce a colour helper keyed on the report's physician field.


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
