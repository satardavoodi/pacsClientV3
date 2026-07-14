"""A failed assign/remove must report the SERVER'S REASON, not a generic error.

THE BUG (2026-07-14, screenshot: "Status change failed — socket assign rejected"):

Remove Assignment goes over the SOCKET (the default transport). Two client defects
turned a perfectly clear server refusal into a meaningless message:

1. ``ino_assignment_socket.assign_via_socket`` read only ``message`` from the
   response — but a rejected AssignStudy answers with **``error``**::

       {"status":"error","error":"assignee_id is required", ...}

   so every socket rejection collapsed to the literal string
   "socket assign rejected".

2. ``InoAssignmentClient.assign`` returned the SOCKET result unconditionally when
   both transports failed, discarding the REST answer — which carried the
   informative HTTP 422 (``assignee_id`` minLength=1).

Together they hid the real cause: **this server cannot remove an assignment.**
Verified live on both transports (probe reception, nothing real touched).

Pure/offline — the transports are stubbed.
"""
from __future__ import annotations

import pytest

import modules.network.ino_assignment as ia
from modules.network import ino_assignment_socket as sock


# ── the exact frames the live server returns ───────────────────────────────
SOCKET_REFUSAL = {"status": "error", "error": "assignee_id is required",
                  "response_type": "response", "endpoint": "AssignStudy"}
REST_REFUSAL_MSG = ("[{'type': 'string_too_short', 'loc': ['body', 'assignee_id'], "
                    "'msg': 'String should have at least 1 character'}]")


def test_socket_reads_the_servers_error_field(monkeypatch):
    """`error`, not `message` — that one word was the whole bug."""
    monkeypatch.setattr(sock, "_resolve_socket_target", lambda: ("h", 1))
    monkeypatch.setattr(sock, "_send_framed", lambda s, p: SOCKET_REFUSAL)
    monkeypatch.setattr(sock.socket, "create_connection",
                        lambda *a, **k: _DummySock())

    out = sock.assign_via_socket("tok", {"patient_id": "50202", "assignee_id": ""})
    assert out["ok"] is False
    assert out["message"] == "assignee_id is required"
    assert out["message"] != "socket assign rejected"
    assert out["server_answered"] is True, "the server validated and refused"


def test_socket_transport_failure_is_not_a_server_answer(monkeypatch):
    """A dropped connection must NOT be mistaken for a server refusal — otherwise a
    network blip would be reported as 'the server cannot remove assignments'."""
    monkeypatch.setattr(sock, "_resolve_socket_target", lambda: ("h", 1))

    def boom(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(sock.socket, "create_connection", boom)

    out = sock.assign_via_socket("tok", {})
    assert out["ok"] is False
    assert not out.get("server_answered")


class _DummySock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def settimeout(self, *_):
        pass


# ── the informative error must win when BOTH transports fail ───────────────
@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(ia, "is_enabled", lambda: True)
    monkeypatch.setattr(ia, "get_ino_assignment_transport", lambda: ia.TRANSPORT_SOCKET)
    monkeypatch.setattr(ia, "_headers", lambda: {"Authorization": "Bearer x"})
    return ia.InoAssignmentClient(base_url="http://pacs:8000")


def test_server_reason_beats_the_generic_socket_error(client, monkeypatch):
    """The socket used to win unconditionally, so the useful REST 422 was thrown
    away and the user saw 'socket assign rejected'."""
    monkeypatch.setattr(
        ia.InoAssignmentClient, "_assign_via_socket",
        lambda self, p: {"ok": False, "status": 0, "message": "socket assign rejected"},
    )

    class _R:
        status_code = 422
        headers = {"content-type": "application/json"}

        def json(self):
            return {"detail": [{"msg": "String should have at least 1 character"}]}
        text = REST_REFUSAL_MSG

    monkeypatch.setattr(ia.requests, "put", lambda *a, **k: _R())

    out = client.assign("50202", "radiologist", "", allow_empty=True)
    assert out["ok"] is False
    assert out["status"] == 422, "the REST answer (a real server refusal) must win"


def test_socket_refusal_is_kept_when_it_carries_the_reason(client, monkeypatch):
    """When the SOCKET is the one that answered, keep its reason."""
    monkeypatch.setattr(
        ia.InoAssignmentClient, "_assign_via_socket",
        lambda self, p: {"ok": False, "status": 0, "server_answered": True,
                         "message": "assignee_id is required"},
    )
    monkeypatch.setattr(ia.requests, "put",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no route")))

    out = client.assign("50202", "radiologist", "", allow_empty=True)
    assert out["message"] == "assignee_id is required"


# ── and the popup finally explains it ──────────────────────────────────────
@pytest.mark.parametrize("failure", [
    {"ok": False, "status": 0, "message": "assignee_id is required"},      # socket
    {"ok": False, "status": 422, "message": "String should have at least 1 character"},
    {"ok": False, "status": 400, "message": "whatever"},
])
def test_remove_explains_the_refusal_from_either_transport(failure, monkeypatch):
    monkeypatch.setattr(ia, "is_enabled", lambda: True)
    monkeypatch.setattr(ia.InoAssignmentClient, "assign",
                        lambda self, *a, **k: dict(failure))
    recorded = []
    monkeypatch.setattr(ia._history, "record", lambda rec: recorded.append(rec))

    out = ia.get_internal_assignment_service().unassign("50202")

    assert out["ok"] is False
    assert out["unsupported_by_server"] is True
    assert "cannot remove an assignment" in out["message"]
    assert "NOT changed" in out["message"]
    assert "socket assign rejected" not in out["message"]
    # never recorded as a successful removal
    from modules.network import ino_assignment_models as m
    assert recorded and recorded[0].action == m.ACTION_FAILED


def test_a_network_outage_is_not_reported_as_unsupported(monkeypatch):
    """A transport failure must stay a transport failure — telling the user the
    server 'cannot remove assignments' when the cable is unplugged would be a lie."""
    monkeypatch.setattr(ia, "is_enabled", lambda: True)
    monkeypatch.setattr(
        ia.InoAssignmentClient, "assign",
        lambda self, *a, **k: {"ok": False, "status": 0,
                               "message": "socket assign failed: timed out"},
    )
    monkeypatch.setattr(ia._history, "record", lambda rec: True)

    out = ia.get_internal_assignment_service().unassign("50202")
    assert out["ok"] is False
    assert not out.get("unsupported_by_server")
