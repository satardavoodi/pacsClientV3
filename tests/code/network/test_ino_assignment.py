# -*- coding: utf-8 -*-
"""Tests for the isolated internal-center (INO) assignment foundation.

Covers the pure state model, the REST client's URL/params/body + permission
handling, the separate history store, and — critically — an **isolation guard**
that the internal-assignment modules import NOTHING from the external
Consultation / Google-Drive / payment / Identity workflow.
"""

import ast
import os

import pytest

from modules.network import ino_assignment_models as m  # noqa: E402


# --------------------------------------------------------------------------- #
# State model
# --------------------------------------------------------------------------- #
def test_assign_type_and_source_validation():
    assert m.is_valid_assign_type("radiologist")
    assert m.is_valid_assign_type("typist")
    assert not m.is_valid_assign_type("consultation")  # never a consultation
    assert m.is_valid_source("ris_personnel")
    assert not m.is_valid_source("google_drive")


def test_default_source_for_type():
    assert m.default_source_for_type("radiologist") == "ris_personnel"
    assert m.default_source_for_type("typist") == "ris_user"


def test_labels_are_internal_not_consultation():
    assert m.FEATURE_LABEL_EN == "Internal Assignment"
    # Terminology must not read as "consultation".
    assert "consult" not in m.FEATURE_LABEL_EN.lower()
    assert m.assign_type_label("radiologist", "en") == "Reporting radiologist"


def test_assignable_user_from_api():
    u = m.AssignableUser.from_api({
        "id": "64abc", "full_name": "دکتر احمدی", "source": "ris_personnel",
        "username": "1234", "role": "پزشک", "assign_types": ["radiologist"],
    })
    assert u.id == "64abc" and u.source == "ris_personnel"
    assert u.assign_types == ["radiologist"]


def test_reporter_display_is_gone():
    """REGRESSION (49868 / 49836): `reporter_display` coloured the Report cell RED
    from the report's physician field alone — no assignment required. It must stay
    deleted; red may only come from an ACTIVE assignment record."""
    assert not hasattr(m, "reporter_display")


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("دکتر وحید علیزاده", "وحید علیزاده", True),      # title tolerated
        ("Dr. Vahid Alizadeh", "vahid alizadeh", True),   # title + case
        ("Vahid  Alizadeh", "Vahid Alizadeh", True),      # whitespace
        ("Vahid Alizadeh (ID: 123)", "Vahid Alizadeh", True),
        ("Vahid Alizadeh", "Reza Alizadeh", False),       # DIFFERENT physician → no red
        ("", "Vahid Alizadeh", False),
        ("Vahid Alizadeh", "", False),
    ],
)
def test_same_person_name(a, b, expected):
    assert m.same_person_name(a, b) is expected


def test_report_red_requires_active_assignment_of_that_physician(tmp_path, monkeypatch):
    """The exact 49868/49836 scenario: a reception with a reporting physician set in
    the RIS workflow but NO internal assignment must NOT be red."""
    h = pytest.importorskip("modules.network.ino_assignment_history")
    monkeypatch.setattr(h, "_base_dir", lambda: str(tmp_path))

    def is_red(reception_id, displayed_physician):
        rec = h.current_assignment_details(reception_id)
        status = str((rec or {}).get("assignment_status") or "").lower()
        if not rec or status != m.STATUS_ACTIVE:
            return False
        assignee = str(rec.get("assignee_name") or "").strip()
        return bool(assignee) and (
            not displayed_physician or m.same_person_name(assignee, displayed_physician))

    # 49868 — reporter present, NO assignment at all → never red
    assert is_red("49868", "دکتر وحید علیزاده") is False

    # a real, server-confirmed assignment to that physician → red
    h.record(m.AssignmentRecord(reception_id="49868", assign_type="radiologist",
                                assignee_id="1", assignee_name="دکتر وحید علیزاده",
                                assignee_source="ris_personnel", server_ok=True))
    assert is_red("49868", "وحید علیزاده") is True          # title tolerated

    # the report shows a DIFFERENT physician than the assignee → not red
    assert is_red("49868", "دکتر رضا علیزاده") is False

    # cancelled/completed are not "active" → not red
    h.record(m.AssignmentRecord(reception_id="49868", assign_type="", assignee_id="",
                                assignee_name="", assignee_source="",
                                action=m.ACTION_STATUS_CHANGED,
                                assignment_status="completed", server_ok=False))
    assert is_red("49868", "وحید علیزاده") is False


@pytest.mark.parametrize(
    "rows,expected",
    [
        ([{"action": "failed", "server_ok": False}], ""),                      # failed → no status
        ([{"action": "assigned", "server_ok": False}], ""),                    # local-only → NOT assigned
        ([{"action": "assigned", "server_ok": True}], "active"),               # server-confirmed → active
        ([{"action": "assigned", "server_ok": True},
          {"action": "status_changed", "assignment_status": "completed"}], "completed"),
        # THREE states (2026-07-14): deactivate == cancel == unassign == REMOVED.
        ([{"action": "assigned", "server_ok": True},
          {"action": "status_changed", "assignment_status": "deactivated"}], "removed"),
        ([{"action": "assigned", "server_ok": True},
          {"action": "unassigned", "server_ok": True}], "removed"),            # server unassign
    ],
)
def test_resolve_assignment_status(rows, expected):
    assert m.resolve_assignment_status(rows) == expected


@pytest.mark.parametrize(
    "status,icon,color",
    [
        ("active",      "fa5s.user-check",   "#ef4444"),  # red   — assigned/pending
        ("completed",   "fa5s.check-circle", "#10b981"),  # green — done
        ("removed",     "fa5s.user-slash",   "#9ca3af"),  # gray  — taken off the user
        # legacy aliases all normalize onto REMOVED
        ("deactivated", "fa5s.user-slash",   "#9ca3af"),
        ("cancelled",   "fa5s.user-slash",   "#9ca3af"),
        ("",            "fa5s.user-times",   "#6b7280"),  # never assigned
        ("bogus",       "fa5s.user-times",   "#6b7280"),  # unknown → neutral
    ],
)
def test_assign_icon_for_status(status, icon, color):
    out = m.assign_icon_for_status(status, "Dr. Vahid Alizadeh")
    assert out["icon"] == icon
    assert out["color"] == color
    # the reported status is the NORMALIZED one: a legacy "cancelled"/"deactivated"
    # row is the same state as "removed"; an unknown status is "" (not assigned).
    assert out["status"] == m.normalize_status(status)
    assert out["tooltip"]                      # always has a tooltip
    # every state is visually distinct from the active red assignment
    if status != "active":
        assert (out["icon"], out["color"]) != ("fa5s.user-check", "#ef4444")


def test_assign_icon_end_to_end_from_history(tmp_path, monkeypatch):
    """The icon follows the PERSISTED record: server assign → red active;
    local completed → green; server unassign → gray cancelled."""
    h = pytest.importorskip("modules.network.ino_assignment_history")
    monkeypatch.setattr(h, "_base_dir", lambda: str(tmp_path))

    def icon():
        rec = h.current_assignment_details("49628")
        if not rec:
            return m.assign_icon_for_status("", "")
        return m.assign_icon_for_status(rec["assignment_status"], rec.get("assignee_name", ""))

    assert icon()["icon"] == "fa5s.user-times"          # nothing yet

    h.record(m.AssignmentRecord(reception_id="49628", assign_type="radiologist",
                                assignee_id="64abc", assignee_name="Dr. V",
                                assignee_source="ris_personnel", server_ok=True))
    assert (icon()["icon"], icon()["color"]) == ("fa5s.user-check", "#ef4444")   # active

    h.record(m.AssignmentRecord(reception_id="49628", assign_type="", assignee_id="",
                                assignee_name="", assignee_source="",
                                action=m.ACTION_STATUS_CHANGED,
                                assignment_status="completed", server_ok=False))
    assert (icon()["icon"], icon()["color"]) == ("fa5s.check-circle", "#10b981")  # completed

    h.record(m.AssignmentRecord(reception_id="49628", assign_type="radiologist",
                                assignee_id="", assignee_name="", assignee_source="",
                                action=m.ACTION_UNASSIGNED, server_ok=True))
    assert (icon()["icon"], icon()["color"]) == ("fa5s.user-slash", "#9ca3af")    # removed


def test_partition_user_groups_is_in_core(tmp_path):
    """User grouping lives in CORE so BOTH entry points (Assign column and
    Reporting Physician) group identically — not only the education plugin."""
    users = [
        m.AssignableUser.from_personnel({"_id": "1", "FirstName": "Dr", "LastName": "A",
                                         "PersonnelType": "پزشک", "IsActive": True}),
        m.AssignableUser.from_center_user({"_id": "2", "FullName": "Sec B", "User": "b",
                                           "roles": {"Name": "typist"}, "Deactive": False}),
        m.AssignableUser.from_personnel({"_id": "3", "FirstName": "Dr", "LastName": "C",
                                         "PersonnelType": "پزشک", "IsActive": True}),
    ]
    groups = m.partition_user_groups(users)
    keys = [g[0] for g in groups]
    assert keys == [m.GROUP_PHYSICIANS, m.GROUP_USERS]      # physicians first
    assert len(dict((g[0], g[2]) for g in groups)[m.GROUP_PHYSICIANS]) == 2
    assert "Physicians" in dict((g[0], g[1]) for g in groups)[m.GROUP_PHYSICIANS]
    assert m.partition_user_groups([]) == []


def test_reporting_physician_path_has_no_own_assignment_logic():
    """REGRESSION GUARD for the two-implementations bug.

    The Report-popup entry point must be an ENTRY POINT ONLY — it must not call
    the assignment API, build its own user list, or create notifications. All of
    that belongs to the ONE shared panel it opens.
    """
    import os
    root = _repo_root()
    path = os.path.join(
        root, "PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/internal_assign_ui.py")
    src = open(path, encoding="utf-8").read()
    # it must delegate to the shared component…
    assert "internal_assignment_panel" in src
    assert "open_internal_assignment_dialog" in src
    # …and must NOT re-implement assignment logic
    for banned in ("assign_async", "svc.assign(", "list_users(",
                   "notify_local_assignment", "set_assignment_status"):
        assert banned not in src, f"legacy assignment logic reintroduced: {banned}"


def test_status_labels_and_colors():
    assert m.status_label("active") == "Active"
    assert m.status_color("completed") == "#10b981"
    # deactivate / cancel / unassign are ONE state: removed
    assert m.status_label("cancelled") == "Removed"
    assert m.status_color("cancelled") == m.STATUS_COLORS[m.STATUS_REMOVED]
    # only assign and remove are reachable through the server (it has no status field)
    assert m.SERVER_BACKED_STATUSES == (m.STATUS_ACTIVE, m.STATUS_REMOVED)


def test_unassign_sends_empty_assignee_and_records(ia, monkeypatch, tmp_path):
    """Cancel/Unassign = PUT /assign with an EMPTY assignee (no dedicated endpoint)."""
    monkeypatch.setattr(ia, "get_ino_assignment_transport", lambda: ia.TRANSPORT_REST)
    h = pytest.importorskip("modules.network.ino_assignment_history")
    monkeypatch.setattr(h, "_base_dir", lambda: str(tmp_path))
    cap = {}
    monkeypatch.setattr(ia.requests, "put",
                        lambda url, json=None, headers=None, timeout=None:
                        cap.update(url=url, body=json) or _Resp(200, {"success": True}))
    out = ia.get_internal_assignment_service().unassign("49628")
    assert out["ok"]
    assert cap["body"]["assignee_id"] == ""          # empty = clear
    assert cap["url"].endswith("/api/patients/49628/assign")
    # a confirmed clear → REMOVED, and the row is no longer "assigned"
    assert m.resolve_assignment_status(h.read_for_reception("49628")) == "removed"
    assert h.current_assignee("49628") is None


def test_set_status_local_states_are_marked_local(ia, monkeypatch, tmp_path):
    """completed/deactivated have NO INO endpoint → recorded locally, flagged local
    (never presented as server-confirmed) and no HTTP call is made."""
    h = pytest.importorskip("modules.network.ino_assignment_history")
    monkeypatch.setattr(h, "_base_dir", lambda: str(tmp_path))
    called = {"n": 0}
    monkeypatch.setattr(ia.requests, "put",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or _Resp(200, {}))
    svc = ia.get_internal_assignment_service()
    out = svc.set_assignment_status("49628", "completed")
    assert out["ok"] is True and out["local"] is True and out["status_set"] == "completed"
    assert called["n"] == 0                       # no server call for a local state
    assert m.resolve_assignment_status(h.read_for_reception("49628")) == "completed"
    assert svc.set_assignment_status("49628", "bogus")["ok"] is False


def test_assignment_record_to_dict():
    rec = m.AssignmentRecord(
        reception_id="10380", assign_type="radiologist", assignee_id="64abc",
        assignee_name="دکتر احمدی", assignee_source="ris_personnel", server_ok=True,
    )
    d = rec.to_dict()
    assert d["reception_id"] == "10380" and d["action"] == "assigned"
    assert d["server_ok"] is True and "timestamp" in d


# --------------------------------------------------------------------------- #
# REST client
# --------------------------------------------------------------------------- #
@pytest.fixture()
def ia(monkeypatch):
    ino = pytest.importorskip("modules.network.ino_assignment")
    monkeypatch.setattr(ino, "get_ino_assignment_base_url", lambda: "http://host:8000")
    monkeypatch.setattr(ino, "get_reception_api_timeout", lambda: 8)
    monkeypatch.setattr(
        ino, "get_socket_token_manager",
        lambda: type("T", (), {
            "get_token": staticmethod(lambda: "JWT"),
            "get_user": staticmethod(lambda: {"id": "u1"}),
        })(),
    )
    return ino


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.headers = {"content-type": "application/json"}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_list_radiologists_from_personnel(ia, monkeypatch):
    """radiologist source = /api/personnel (NOT the consultation registry, NOT
    the guide's 404 /api/assign/users)."""
    cap = {"urls": []}

    def fake_get(url, params=None, headers=None, timeout=None):
        cap["urls"].append(url)
        cap["auth"] = headers.get("Authorization")
        return _Resp(200, {"success": True, "data": [
            {"_id": "6a1a", "FirstName": "حسنا", "LastName": "تابه‌زر",
             "PersonnelType": "پزشک", "IsActive": True},
        ]})

    monkeypatch.setattr(ia.requests, "get", fake_get)
    out = ia.InoAssignmentClient().list_assignable_users("radiologist")
    assert out["ok"] and len(out["users"]) == 1
    u = out["users"][0]
    assert u.full_name == "حسنا تابه‌زر" and u.source == "ris_personnel"
    assert cap["urls"][0].endswith("/api/personnel")
    assert cap["auth"] == "Bearer JWT"


def test_list_typists_from_center_users(ia, monkeypatch):
    """typist source = /api/AdminUser/getCenterUsers."""
    cap = {"urls": []}

    def fake_get(url, params=None, headers=None, timeout=None):
        cap["urls"].append(url)
        return _Resp(200, [{"_id": "687e", "User": "reza", "FullName": "رضا",
                            "Deactive": False, "roles": {"Name": "typist"}}])

    monkeypatch.setattr(ia.requests, "get", fake_get)
    out = ia.InoAssignmentClient().list_assignable_users("typist")
    assert out["ok"] and out["users"][0].full_name == "رضا"
    assert out["users"][0].source == "ris_user"
    assert cap["urls"][0].endswith("/api/AdminUser/getCenterUsers")


def test_personnel_mappers():
    ru = m.AssignableUser.from_personnel({"_id": "x1", "FirstName": "A", "LastName": "B", "PersonnelType": "پزشک", "IsActive": True})
    assert ru.full_name == "A B" and ru.source == "ris_personnel" and ru.assign_types == ["radiologist"]
    cu = m.AssignableUser.from_center_user({"_id": "y1", "FullName": "C", "User": "c", "Deactive": True, "roles": {"Name": "r"}})
    assert cu.full_name == "C" and cu.source == "ris_user" and cu.is_active is False


def test_assign_puts_to_pacs_patients_endpoint(ia, monkeypatch):
    """PACS client contract (ASSIGN_CLIENT_GUIDE_FA §3.2): PUT /api/patients/{rid}/assign
    with the full body, on the ASSIGN base (PACS :8000), NOT the RIS :8080 list base."""
    monkeypatch.setattr(ia, "get_ino_assignment_transport", lambda: ia.TRANSPORT_REST)
    cap = {}

    def fake_put(url, json=None, headers=None, timeout=None):
        cap.update(url=url, body=json, xuid=(headers or {}).get("X-User-Id"))
        return _Resp(200, {"success": True, "modified_count": 2})

    monkeypatch.setattr(ia.requests, "put", fake_put)
    out = ia.InoAssignmentClient().assign(
        "49476", "radiologist", "64abc", assignee_name="دکتر احمدی", assignee_source="ris_personnel",
    )
    assert out["ok"] and out["modified_count"] == 2
    assert cap["url"].endswith("/api/patients/49476/assign")
    assert cap["body"] == {
        "assign_type": "radiologist", "assignee_id": "64abc", "assignee_name": "دکتر احمدی",
        "assignee_source": "ris_personnel", "study_uid": "",
    }
    assert cap["xuid"] == "u1"


def test_assign_typist_supported_defaults_source(ia, monkeypatch):
    """Typist IS supported on the PACS endpoint; source defaults to ris_user."""
    monkeypatch.setattr(ia, "get_ino_assignment_transport", lambda: ia.TRANSPORT_REST)
    cap = {}
    monkeypatch.setattr(ia.requests, "put",
                        lambda url, json=None, headers=None, timeout=None: cap.update(body=json) or _Resp(200, {"success": True}))
    out = ia.InoAssignmentClient().assign("49476", "typist", "u9")
    assert out["ok"] and cap["body"]["assign_type"] == "typist"
    assert cap["body"]["assignee_source"] == "ris_user"


def test_assign_missing_assignee_id(ia, monkeypatch):
    monkeypatch.setattr(ia.requests, "put", lambda *a, **k: _Resp(200, {}))
    out = ia.InoAssignmentClient().assign("49476", "radiologist", "")
    assert out["ok"] is False


def test_assign_permission_denied(ia, monkeypatch):
    monkeypatch.setattr(ia, "get_ino_assignment_transport", lambda: ia.TRANSPORT_REST)
    monkeypatch.setattr(ia.requests, "put", lambda *a, **k: _Resp(403, {"message": "شما مجاز نیستید"}))
    out = ia.InoAssignmentClient().assign("49476", "radiologist", "64abc")
    assert out["ok"] is False and out["permission_denied"] is True


def test_assign_auth_error(ia, monkeypatch):
    monkeypatch.setattr(ia, "get_ino_assignment_transport", lambda: ia.TRANSPORT_REST)
    monkeypatch.setattr(ia.requests, "put", lambda *a, **k: _Resp(401, {"message": "expired"}))
    out = ia.InoAssignmentClient().assign("49476", "radiologist", "64abc")
    assert out["auth_error"] is True


def test_get_assignment_reads_pacs_assignment(ia, monkeypatch):
    """get_assignment = GET /api/patients/{rid}/assign → body.assignment.

    The read now goes through the POOLED keep-alive session
    (modules/network/http_session) — the patient list issues one of these per
    visible reception, so a fresh TCP connection per call was pure overhead.
    """
    import modules.network.http_session as hs

    def fake_get(url, base_url="", headers=None, timeout=None, params=None):
        assert url.endswith("/api/patients/49476/assign")
        return _Resp(200, {"success": True,
                           "assignment": {"radiologist": {"id": "64abc", "name": "Dr A"}}})
    monkeypatch.setattr(hs, "http_get", fake_get)
    out = ia.InoAssignmentClient().get_assignment("49476")
    assert out["ok"] and out["assignment"]["radiologist"]["name"] == "Dr A"


def test_derive_pacs_http_base_uses_the_active_profile_host(ia, monkeypatch):
    """The assign base is the ACTIVE SERVER PROFILE's host :8000 — NOT the reception
    host (corrected 2026-07-14).

    The assign REST API runs on the PACS service; reception is a different service
    and can be a different machine. Deriving it from the reception host sent assign
    calls to the wrong box at any center where the two differ (here the profile host
    is 192.168.2.222 while reception is the port-forwarded 81.16.117.196 — both
    answered, so the defect was latent).
    """
    import PacsClient.utils.server_profiles as sp

    monkeypatch.setattr(sp, "get_active_profile", lambda: None)
    monkeypatch.setattr(sp, "active_host", lambda: "192.168.2.222")
    monkeypatch.setattr(ia, "get_reception_api_base_url", lambda: "http://81.16.117.196:8080")

    assert ia._derive_pacs_http_base() == "http://192.168.2.222:8000"


def test_derive_pacs_http_falls_back_to_reception_when_no_profile(ia, monkeypatch):
    """No profile configured at all → the legacy reception-derived base still works."""
    import PacsClient.utils.server_profiles as sp

    monkeypatch.setattr(sp, "get_active_profile", lambda: None)
    monkeypatch.setattr(sp, "active_host", lambda: "")
    monkeypatch.setattr(ia, "get_reception_api_base_url", lambda: "http://81.16.117.196:8080")

    assert ia._derive_pacs_http_base() == "http://81.16.117.196:8000"


# --------------------------------------------------------------------------- #
# Transport: REST default + socket fallback (ASSIGN_CLIENT_GUIDE_FA §4)
# --------------------------------------------------------------------------- #
def test_transport_defaults_to_socket(ia, monkeypatch):
    """Socket (:50052) is the DEFAULT transport for INO assign."""
    monkeypatch.delenv("AIPACS_INO_ASSIGNMENT_TRANSPORT", raising=False)
    monkeypatch.setattr(ia, "_config", lambda: {})
    assert ia.get_ino_assignment_transport() == ia.TRANSPORT_SOCKET


def test_default_assign_uses_socket_not_rest(ia, monkeypatch):
    """With no override, assign() goes over the socket; no HTTP PUT is made."""
    monkeypatch.delenv("AIPACS_INO_ASSIGNMENT_TRANSPORT", raising=False)
    monkeypatch.setattr(ia, "_config", lambda: {})
    put_called = {"n": 0}
    monkeypatch.setattr(ia.requests, "put",
                        lambda *a, **k: put_called.__setitem__("n", put_called["n"] + 1) or _Resp(200, {}))
    cap = {}
    monkeypatch.setattr(ia.InoAssignmentClient, "_assign_via_socket",
                        lambda self, params: cap.update(params=params) or {"ok": True, "modified_count": 1})
    out = ia.InoAssignmentClient().assign("49476", "radiologist", "64abc", assignee_name="Dr A")
    assert out["ok"] and put_called["n"] == 0
    assert cap["params"]["patient_id"] == "49476" and cap["params"]["assign_type"] == "radiologist"


def test_socket_falls_back_to_rest_when_socket_fails(ia, monkeypatch):
    """Socket-primary: if the socket can't deliver, fall back to REST :8000."""
    monkeypatch.setattr(ia, "get_ino_assignment_transport", lambda: ia.TRANSPORT_SOCKET)
    monkeypatch.setattr(ia.InoAssignmentClient, "_assign_via_socket",
                        lambda self, params: {"ok": False, "status": 0, "message": "socket assign failed"})
    monkeypatch.setattr(ia.requests, "put",
                        lambda *a, **k: _Resp(200, {"success": True, "modified_count": 3}))
    out = ia.InoAssignmentClient().assign("49476", "radiologist", "64abc")
    assert out["ok"] and out["modified_count"] == 3


def test_rest_transport_falls_back_to_socket_on_connection_error(ia, monkeypatch):
    """transport=rest but PACS :8000 unreachable → socket fallback."""
    monkeypatch.setattr(ia, "get_ino_assignment_transport", lambda: ia.TRANSPORT_REST)

    def boom(*a, **k):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(ia.requests, "put", boom)
    monkeypatch.setattr(ia.InoAssignmentClient, "_assign_via_socket",
                        lambda self, params: {"ok": True, "modified_count": 2})
    out = ia.InoAssignmentClient().assign("49476", "radiologist", "64abc")
    assert out["ok"] and out["modified_count"] == 2


def test_save_config_merges_keys(tmp_path, monkeypatch):
    ino = pytest.importorskip("modules.network.ino_assignment")
    path = tmp_path / "ino_assignment_config.json"
    path.write_text('{"enabled": false, "note": "keep me"}', encoding="utf-8")
    monkeypatch.setattr(ino, "get_config_path", lambda: str(path))
    assert ino.save_ino_assignment_config({"enabled": True, "transport": "socket"}) is True
    import json as _json
    data = _json.loads(path.read_text(encoding="utf-8"))
    assert data["enabled"] is True and data["transport"] == "socket"
    assert data["note"] == "keep me"  # untouched keys preserved


def test_service_disabled_when_turned_off(ia, monkeypatch):
    monkeypatch.setattr(ia, "is_enabled", lambda: False)
    out = ia.get_internal_assignment_service().assign("10380", "radiologist", "64abc")
    assert out.get("disabled") is True


def test_feature_enabled_by_default(ia, monkeypatch):
    """Default ON: no env, empty config → enabled. Explicit off tokens disable."""
    monkeypatch.delenv("AIPACS_INO_ASSIGNMENT", raising=False)
    monkeypatch.setattr(ia, "_config", lambda: {})
    assert ia.is_enabled() is True
    monkeypatch.setenv("AIPACS_INO_ASSIGNMENT", "0")
    assert ia.is_enabled() is False
    monkeypatch.setenv("AIPACS_INO_ASSIGNMENT", "off")
    assert ia.is_enabled() is False
    monkeypatch.setenv("AIPACS_INO_ASSIGNMENT", "1")
    assert ia.is_enabled() is True
    monkeypatch.delenv("AIPACS_INO_ASSIGNMENT", raising=False)
    monkeypatch.setattr(ia, "_config", lambda: {"enabled": False})
    assert ia.is_enabled() is False


# --------------------------------------------------------------------------- #
# History store
# --------------------------------------------------------------------------- #
def test_history_round_trip(tmp_path, monkeypatch):
    h = pytest.importorskip("modules.network.ino_assignment_history")
    monkeypatch.setattr(h, "_base_dir", lambda: str(tmp_path))
    rec = m.AssignmentRecord(
        reception_id="10380", assign_type="radiologist", assignee_id="64abc",
        assignee_name="دکتر احمدی", assignee_source="ris_personnel", server_ok=True,
    )
    assert h.record(rec) is True
    rows = h.read_for_reception("10380")
    assert len(rows) == 1 and rows[0]["assignee_name"] == "دکتر احمدی"
    assert h.read_for_reception("99999") == []


def test_current_assignee_is_server_confirmed(tmp_path, monkeypatch):
    """The Assign-icon red source: latest server_ok assignment wins; a local-only
    (server_ok=False) record must NOT count; unassign clears; unknown → None."""
    h = pytest.importorskip("modules.network.ino_assignment_history")
    monkeypatch.setattr(h, "_base_dir", lambda: str(tmp_path))
    # a failed/local-only attempt does not turn the row red
    h.record(m.AssignmentRecord(reception_id="49628", assign_type="radiologist",
                                assignee_id="x", assignee_name="Local Only",
                                assignee_source="ris_personnel",
                                action=m.ACTION_FAILED, server_ok=False))
    assert h.current_assignee("49628") is None
    # a server-confirmed assignment turns it red with that name
    h.record(m.AssignmentRecord(reception_id="49628", assign_type="radiologist",
                                assignee_id="64abc", assignee_name="Dr. Vahid Alizadeh",
                                assignee_source="ris_personnel", server_ok=True))
    assert h.current_assignee("49628") == "Dr. Vahid Alizadeh"
    assert h.current_assignee("00000") is None


# --------------------------------------------------------------------------- #
# ISOLATION GUARD — internal assignment must not import the external workflow
# --------------------------------------------------------------------------- #
_FORBIDDEN_PREFIXES = (
    "modules.cloud_consultation",
    "modules.education",
    "modules.Identity",
    "googleapiclient",
    "google",
)
_FORBIDDEN_SUBSTR = ("consultation", "google_drive", "payment", "stripe", "drive")

_MODULE_FILES = (
    "modules/network/ino_assignment.py",
    "modules/network/ino_assignment_models.py",
    "modules/network/ino_assignment_history.py",
    "modules/network/ino_assignment_socket.py",
)


def _repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


def _imported_modules(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


def test_internal_assignment_imports_are_isolated():
    root = _repo_root()
    for rel in _MODULE_FILES:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            pytest.skip(f"missing {rel}")
        for mod in _imported_modules(path):
            low = mod.lower()
            assert not any(mod.startswith(p) for p in _FORBIDDEN_PREFIXES), f"{rel} imports {mod}"
            assert not any(s in low for s in _FORBIDDEN_SUBSTR), f"{rel} imports {mod}"
