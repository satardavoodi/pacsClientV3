# -*- coding: utf-8 -*-
"""Tests for the INO approval-flag sync (modules.network.ino_report_workflow).

Verifies the two live-discovered endpoints are used correctly (no real network):
  * resolve workflow id: GET /api/imagingWorkflow/workflow/reporting?receptionID=<n>
    -> item.receptionId (the imagingWorkflow ObjectId)
  * set flags: PATCH /api/imagingWorkflow/{workflowId}/workflow/report/approval-flags
    { physicianApproved, secretaryApproved }
and that sync_report_approval_for_status maps the status to the right flags.

Live-verified 2026-07-09 on reception 49476 (workflow id 6a4de81218a091772b582325).
"""

import pytest

pytest.importorskip("PySide6.QtCore")

from modules.network import ino_report_workflow as iw  # noqa: E402

_WID = "6a4de81218a091772b582325"


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(
        iw, "get_socket_token_manager",
        lambda: type("T", (), {"get_token": staticmethod(lambda: "JWT")})(),
    )
    monkeypatch.setattr(iw, "get_reception_api_base_url", lambda: "http://host:8080")
    monkeypatch.setattr(iw, "get_reception_api_timeout", lambda: 8)
    monkeypatch.setattr(iw, "reception_api_breaker_open", lambda *a, **k: False)
    monkeypatch.setattr(iw, "record_reception_api_success", lambda *a, **k: None)
    monkeypatch.setattr(iw, "record_reception_api_failure", lambda *a, **k: None)


def test_resolve_workflow_id_matches_numeric_receptionID(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["auth"] = headers.get("Authorization")
        return _Resp(200, {"data": [
            {"receptionID": 49722, "receptionId": "a" * 24},
            {"receptionID": 49476, "receptionId": _WID},
        ]})

    monkeypatch.setattr(iw.requests, "get", fake_get)
    wid = iw.resolve_workflow_id(49476)
    assert wid == _WID
    assert captured["url"].endswith("/api/imagingWorkflow/workflow/reporting")
    assert captured["params"] == {"receptionID": 49476}
    assert captured["auth"] == "Bearer JWT"


def test_resolve_returns_none_when_absent(monkeypatch):
    monkeypatch.setattr(iw.requests, "get", lambda *a, **k: _Resp(200, {"data": []}))
    assert iw.resolve_workflow_id(11111) is None


def test_set_report_approval_flags_builds_patch(monkeypatch):
    captured = {}

    def fake_patch(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _Resp(200, {"message": "ok"})

    monkeypatch.setattr(iw.requests, "patch", fake_patch)
    ok = iw.set_report_approval_flags(_WID, True, False)
    assert ok is True
    assert captured["url"].endswith(f"/api/imagingWorkflow/{_WID}/workflow/report/approval-flags")
    assert captured["json"] == {"physicianApproved": True, "secretaryApproved": False}


def test_set_flags_rejects_bad_workflow_id(monkeypatch):
    called = {"patch": False}
    monkeypatch.setattr(iw.requests, "patch", lambda *a, **k: called.__setitem__("patch", True) or _Resp(200))
    assert iw.set_report_approval_flags("not-an-objectid", True, True) is False
    assert called["patch"] is False  # never attempted


@pytest.mark.parametrize(
    "status,phys,sec",
    [
        ("completed", True, True),
        ("physician_approved", True, False),
        ("awaiting_physician_approval", False, False),
        ("pending", False, False),
    ],
)
def test_sync_maps_status_to_flags(monkeypatch, status, phys, sec):
    monkeypatch.setattr(iw, "resolve_workflow_id", lambda *a, **k: _WID)
    sent = {}

    def fake_patch(url, json=None, headers=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        return _Resp(200, {"message": "وضعیت تاییدات بروزرسانی شد"})

    monkeypatch.setattr(iw.requests, "patch", fake_patch)
    ok = iw.sync_report_approval_for_status(49476, status)
    assert ok is True
    assert sent["json"] == {"physicianApproved": phys, "secretaryApproved": sec}
    assert _WID in sent["url"]


def test_sync_noop_when_workflow_id_unresolved(monkeypatch):
    monkeypatch.setattr(iw, "resolve_workflow_id", lambda *a, **k: None)
    called = {"patch": False}
    monkeypatch.setattr(iw.requests, "patch", lambda *a, **k: called.__setitem__("patch", True) or _Resp(200))
    assert iw.sync_report_approval_for_status(49476, "completed") is False
    assert called["patch"] is False


def test_sync_respects_disable_flag(monkeypatch):
    monkeypatch.setattr(iw, "INO_APPROVAL_SYNC", False)
    called = {"resolve": False}
    monkeypatch.setattr(iw, "resolve_workflow_id", lambda *a, **k: called.__setitem__("resolve", True) or _WID)
    assert iw.sync_report_approval_for_status(49476, "completed") is False
    assert called["resolve"] is False


# --- permission / access-control handling ----------------------------------- #
@pytest.mark.parametrize(
    "status_code,message,expected",
    [
        (403, "", "permission"),
        (200, "", ""),
        (401, "", "auth"),
        (400, "شما مجاز به این عملیات نیستید", "permission"),  # Persian "not allowed"
        (400, "عدم دسترسی", "permission"),                     # Persian "no access"
        (409, "some other error", "http"),
    ],
)
def test_classify_error(status_code, message, expected):
    assert iw._classify_error(status_code, message) == expected


def test_permission_denied_is_logged_and_notified(monkeypatch):
    """A 403 from INO must NOT be silently ignored — it is classified as a
    permission error and forwarded to the UI notifier (AI-PACS surfaces INO's
    access-control decision instead of bypassing it)."""
    emitted = []
    monkeypatch.setattr(iw, "_emit_failure", lambda msg, kind: emitted.append((msg, kind)))

    class _Denied:
        status_code = 403
        def json(self):
            return {"message": "شما مجاز به تأیید گزارش نیستید"}

    monkeypatch.setattr(iw.requests, "patch", lambda *a, **k: _Denied())
    ok = iw.set_report_approval_flags(_WID, True, True)
    assert ok is False
    assert emitted and emitted[0][1] == "permission"


def test_success_does_not_notify(monkeypatch):
    emitted = []
    monkeypatch.setattr(iw, "_emit_failure", lambda msg, kind: emitted.append((msg, kind)))
    monkeypatch.setattr(iw.requests, "patch", lambda *a, **k: _Resp(200, {"message": "ok"}))
    assert iw.set_report_approval_flags(_WID, True, True) is True
    assert emitted == []
