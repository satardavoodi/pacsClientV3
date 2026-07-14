"""THREE assignment states, ONE source, and an honest Remove.

Two problems, 2026-07-14:

1. **The Report popup showed nothing.** Its summary row (``internal_assign_ui``) and
   the consultation dialog's assignment card both read ``ino_assignment_history`` —
   the LOCAL action log — while the Assign column already read the merged SERVER
   view. So a reception assigned on another workstation appeared in one popup and
   not the other. All three entry points now call
   ``ino_assignment_details.get_assignment_details``.

2. **"Cancel" errored and removed nothing.** Verified against the server's own
   OpenAPI schema (live, not guessed):

       PUT /api/patients/{id}/assign  AssignPayload{assign_type,
                                      assignee_id  **minLength = 1**, ...}
       GET /api/patients/{id}/assign
       (no DELETE verb → 405)

   * the server's assign model has **NO status field at all** — active / completed /
     removed are purely client-side;
   * ``assignee_id`` may not be empty, so the empty-assignee PUT we send to express
     an unassign comes back **HTTP 422 string_too_short**. The server has no way to
     clear an assignment today.

   Deactivate / Cancel / Unassign all meant the same thing, so they collapse into
   ONE terminal state: REMOVED. We still issue the correct request (it starts
   working the moment the server drops ``minLength``) and surface the server's real
   refusal — we never fake a removal, which would leave this workstation showing the
   patient as unassigned while every other one still shows the assignment.

Pure — no Qt, no network.
"""
from __future__ import annotations

from pathlib import Path

from modules.network import ino_assignment_models as m

REPO = Path(__file__).resolve().parents[3]


# ── three states ───────────────────────────────────────────────────────────
def test_there_are_exactly_three_states():
    assert m.ASSIGNMENT_STATUSES == (m.STATUS_ACTIVE, m.STATUS_COMPLETED, m.STATUS_REMOVED)


def test_deactivate_cancel_and_unassign_all_mean_removed():
    for legacy in ("deactivated", "cancelled", "unassigned",
                   "deactive", "cancel", "unassign", "CANCELLED", " Deactivated "):
        assert m.normalize_status(legacy) == m.STATUS_REMOVED, legacy


def test_active_and_completed_normalize_to_themselves():
    assert m.normalize_status("Active") == m.STATUS_ACTIVE
    assert m.normalize_status("completed") == m.STATUS_COMPLETED
    assert m.normalize_status("") == ""
    assert m.normalize_status("nonsense") == ""


def test_legacy_history_rows_still_render():
    """A record written before the change carries 'cancelled'/'deactivated'; it must
    never show up as an unknown status."""
    assert m.status_label("cancelled") == "Removed"
    assert m.status_label("deactivated") == "Removed"
    assert m.status_color("cancelled") == m.STATUS_COLORS[m.STATUS_REMOVED]
    icon = m.assign_icon_for_status("deactivated", "Dr X")
    assert icon["status"] == m.STATUS_REMOVED
    assert icon["tooltip"] == "Assignment removed"


def test_completed_is_green_and_the_three_states_are_distinct():
    assert m.STATUS_COLORS[m.STATUS_COMPLETED] == "#10b981"      # green
    icons = {s: m.assign_icon_for_status(s, "X")["icon"]
             for s in ("", m.STATUS_ACTIVE, m.STATUS_COMPLETED, m.STATUS_REMOVED)}
    assert len(set(icons.values())) == 4, "each state needs its own icon"


# ── the shared transition table ────────────────────────────────────────────
def test_one_transition_table_for_every_entry_point():
    assert m.ASSIGN_TRANSITIONS[m.STATUS_ACTIVE] == (m.STATUS_COMPLETED, m.STATUS_REMOVED)
    assert m.ASSIGN_TRANSITIONS[m.STATUS_COMPLETED] == (m.STATUS_ACTIVE, m.STATUS_REMOVED)
    assert m.ASSIGN_TRANSITIONS[m.STATUS_REMOVED] == (m.STATUS_ACTIVE,)
    assert m.ASSIGN_TRANSITIONS[""] == ()


def test_only_remove_is_server_backed():
    """The server's assign model has no status field, so 'completed' can only ever
    be a LOCAL state and the UI must label it as such."""
    assert m.action_is_server_backed(m.STATUS_REMOVED) is True
    assert m.action_is_server_backed(m.STATUS_COMPLETED) is False
    assert m.action_is_server_backed("cancelled") is True      # legacy alias


# ── merge: a stale local "removed" must not beat the server ────────────────
def test_server_assignment_beats_a_stale_local_removed():
    """The server owns 'is this assigned'. If a local removal never reached it, the
    server is still the authority — otherwise this workstation would silently
    disagree with every other one."""
    out = m.merge_assignment_status(True, "Dr S", local_status="cancelled")
    assert out["status"] == m.STATUS_ACTIVE


def test_local_completed_still_sits_on_top_of_a_server_assignment():
    out = m.merge_assignment_status(True, "Dr S", local_status=m.STATUS_COMPLETED)
    assert out["status"] == m.STATUS_COMPLETED


def test_server_cleared_assignment_reads_as_removed():
    out = m.merge_assignment_status(False, "", local_status=m.STATUS_ACTIVE,
                                    local_name="Dr X")
    assert out["status"] == m.STATUS_REMOVED


# ── remove: honest about the server's refusal ──────────────────────────────
def test_remove_reports_the_server_refusal_and_changes_nothing(monkeypatch):
    """PUT /assign with an empty assignee_id → 422 (minLength=1). We must surface
    that, not pretend the assignment was removed."""
    import modules.network.ino_assignment as ia

    monkeypatch.setattr(ia, "is_enabled", lambda: True)
    monkeypatch.setattr(
        ia.InoAssignmentClient, "assign",
        lambda self, *a, **k: {"ok": False, "status": 422,
                               "message": "String should have at least 1 character"},
    )
    recorded = []
    monkeypatch.setattr(ia._history, "record", lambda rec: recorded.append(rec))

    out = ia.get_internal_assignment_service().unassign("50210")

    assert out["ok"] is False
    assert out["unsupported_by_server"] is True
    assert "assignee_id" in out["message"]
    assert "NOT changed" in out["message"]
    # the history row must be a FAILED action — never an "unassigned"
    assert recorded and recorded[0].action == m.ACTION_FAILED
    assert recorded[0].server_ok is False


def test_set_status_removed_routes_to_the_server_unassign(monkeypatch):
    import modules.network.ino_assignment as ia

    monkeypatch.setattr(ia, "is_enabled", lambda: True)
    called = []
    monkeypatch.setattr(ia.InternalAssignmentService, "unassign",
                        lambda self, rid, *a, **k: called.append(rid) or {"ok": True})

    svc = ia.get_internal_assignment_service()
    for legacy in ("removed", "cancelled", "deactivated", "unassign"):
        svc.set_assignment_status("50210", legacy)
    assert called == ["50210"] * 4, "every removal alias must hit the server unassign"


def test_completed_stays_local(monkeypatch):
    import modules.network.ino_assignment as ia

    monkeypatch.setattr(ia, "is_enabled", lambda: True)
    monkeypatch.setattr(ia._history, "record", lambda rec: True)
    out = ia.get_internal_assignment_service().set_assignment_status("50210", "completed")
    assert out["ok"] is True and out["local"] is True and out["status_set"] == "completed"


# ── all three entry points read the SAME assignment data ───────────────────
def _src(*parts) -> str:
    return (REPO.joinpath(*parts)).read_text(encoding="utf-8", errors="replace")


def test_report_popup_reads_the_merged_server_view():
    """THE BUG: the Report popup's summary read the LOCAL log, so it showed nothing
    for an assignment made elsewhere while the Assign popup showed it."""
    src = _src("PacsClient", "pacs", "patient_tab", "ui", "patient_ui",
               "patient_toolbar", "internal_assign_ui.py")
    block = src.split("def _refresh_summary", 1)[1].split("\n    # --", 1)[0]
    assert "ino_assignment_details" in block
    assert "get_assignment_details" in block
    assert "current_assignment_details" not in block


def test_assign_popup_reads_the_merged_server_view():
    src = _src("modules", "education", "online_consultation", "assign_dialog.py")
    assert "ino_assignment_details" in src
    assert "get_assignment_details" in src


def test_all_entry_points_share_one_transition_table():
    for parts in (
        ("PacsClient", "pacs", "workstation_ui", "home_ui", "patient_table_widget.py"),
        ("PacsClient", "pacs", "workstation_ui", "home_ui", "internal_assignment_panel.py"),
        ("modules", "education", "online_consultation", "assign_dialog.py"),
    ):
        src = _src(*parts)
        assert "ASSIGN_TRANSITIONS" in src, parts[-1]
        # no local copy of the old 4-state table
        assert '"deactivated": ("active", "cancelled")' not in src, parts[-1]
        assert "'deactivated': ('active', 'cancelled')" not in src, parts[-1]
