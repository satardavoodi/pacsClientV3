"""The UI must show WHO a patient is assigned to — from the server — and manage it.

Before this (2026-07-14) the app could say a patient was *assigned* but not *to whom*:
every consumer read ``ino_assignment_history`` (the LOCAL action log), so for a
reception assigned on ANOTHER workstation (50210) there was no local record at all —
the details card stayed hidden and the tooltip said nothing.

``ino_assignment_details.get_assignment_details`` is now the ONE merged accessor:
the SERVER owns assignee / assigner / timestamp / type; the LOCAL log still owns the
comment and the ``completed`` / ``deactivated`` states (which have no INO endpoint).

Pure — no Qt, no network.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from modules.network import ino_assignment_details as d
from modules.network import ino_assignment_models as m

REPO = Path(__file__).resolve().parents[3]

# The real 50210 record (live, GET /api/patients/50210/assign).
VAHID = "6887a95ae7e66cdc2029a960"      # the assignee (the logged-in user)
REZA = "69f9041818d430369ecdab06"       # last_assigned_by


@pytest.fixture()
def env(monkeypatch, tmp_path):
    from modules.network import ino_assignment_server_state as state
    from modules.network import ino_assignment_history as hist
    import modules.network.ino_assignment as ia

    monkeypatch.setattr(state, "_base_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ia, "is_enabled", lambda: True)
    monkeypatch.setattr(hist, "current_assignment_details", lambda rid: {})
    d.reset_user_directory()
    d.prime_user_name(REZA, "Dr Reza Ahmadi")
    d.prime_user_name(VAHID, "Dr Vahid Alizadeh")
    return state


def _seed(state, **kw):
    base = dict(assigned=True, assignee_name="Dr Vahid Alizadeh", assignee_id=VAHID,
                mine=True, assign_type="radiologist", assignee_source="ris_personnel",
                assigned_by=REZA, assigned_at="2026-07-14T11:10:14.770000")
    base.update(kw)
    state.set_state("50210", **base)


# ── the assignee is shown, from the server ─────────────────────────────────
def test_details_show_who_it_is_assigned_to(env):
    _seed(env)
    out = d.get_assignment_details("50210")

    assert out["assignee_name"] == "Dr Vahid Alizadeh"
    assert out["assignee_id"] == VAHID
    assert out["mine"] is True
    assert out["from_server"] is True
    assert out["status"] == m.STATUS_ACTIVE


def test_details_show_who_assigned_it_and_when(env):
    _seed(env)
    out = d.get_assignment_details("50210")

    assert out["assigned_by_id"] == REZA
    assert out["assigned_by_name"] == "Dr Reza Ahmadi", "the raw id must be resolved"
    assert out["assigned_at"] == "2026-07-14 11:10:14", "ISO timestamp made readable"
    assert out["assign_type"] == "radiologist"


def test_details_survive_with_no_local_record_at_all(env):
    """THE 50210 CASE: assigned on another PC ⇒ the local log is empty. The details
    must still be complete, because they come from the server."""
    _seed(env)
    out = d.get_assignment_details("50210")
    assert out["assignee_name"] and out["assigned_by_name"] and out["assigned_at"]


def test_comment_comes_from_the_local_log(env, monkeypatch):
    """The server's /assign response has no comment field — the local log is its
    only source, so it must survive the merge."""
    from modules.network import ino_assignment_history as hist
    monkeypatch.setattr(hist, "current_assignment_details",
                        lambda rid: {"comment": "urgent — please report today"})
    _seed(env)
    out = d.get_assignment_details("50210")
    assert out["comment"] == "urgent — please report today"


def test_not_assigned_is_reported_cleanly(env):
    env.set_state("20179", assigned=False)
    out = d.get_assignment_details("20179")
    assert out["assigned"] is False
    assert out["status"] == ""
    assert out["status_label"] == "Not assigned"


def test_done_report_makes_the_assignment_completed(env):
    _seed(env)
    out = d.get_assignment_details("50210", report_status="completed")
    assert out["status"] == m.STATUS_COMPLETED


# ── the tooltip actually names the people ──────────────────────────────────
def test_tooltip_names_the_assignee_the_assigner_and_the_time(env):
    _seed(env)
    tip = d.format_tooltip(d.get_assignment_details("50210"))

    assert "Assigned to: Dr Vahid Alizadeh" in tip
    assert "(you)" in tip
    assert "Assigned by: Dr Reza Ahmadi" in tip
    assert "2026-07-14 11:10:14" in tip
    assert "Status: Active" in tip
    assert tip != "Assigned"          # the whole point of this change


def test_tooltip_for_an_unassigned_patient():
    assert d.format_tooltip(None).startswith("Not assigned")


# ── the paint path must never block on a REST call ─────────────────────────
def test_paint_path_does_not_fetch_the_user_directory(env, monkeypatch):
    d.reset_user_directory()
    calls = []
    monkeypatch.setattr(d, "_load_user_directory", lambda: calls.append(1))
    _seed(env)

    d.get_assignment_details("50210", resolve_names=False)
    assert calls == [], "rendering a row must not trigger a REST fetch"


def test_name_cache_is_used_and_not_refetched(env, monkeypatch):
    calls = []
    monkeypatch.setattr(d, "_load_user_directory", lambda: calls.append(1))
    assert d.resolve_user_name(REZA) == "Dr Reza Ahmadi"   # primed
    assert calls == []


# ── lifecycle actions: honest about what the server can actually do ────────
def test_only_remove_is_a_real_server_action():
    """Only ``removed`` (== the old deactivate / cancel / unassign) maps to a server
    call. ``completed`` has NO endpoint — the server's assign model has no status
    field at all — so it must be labelled as a local workflow state."""
    assert m.SERVER_BACKED_STATUSES == (m.STATUS_ACTIVE, m.STATUS_REMOVED)
    assert m.action_is_server_backed(m.STATUS_REMOVED) is True
    assert m.action_is_server_backed(m.STATUS_COMPLETED) is False


def _widget_src() -> str:
    return (REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
            / "patient_table_widget.py").read_text(encoding="utf-8", errors="replace")


def test_assign_column_has_a_lifecycle_menu():
    src = _widget_src()
    assert "_show_assign_menu" in src
    assert "customContextMenuRequested" in src


def test_menu_transitions_come_from_the_shared_table():
    """The Assign menu, the Assign popup and the Report popup must read ONE table —
    a local copy is how they drifted apart before."""
    src = _widget_src()
    block = src.split("def _show_assign_menu", 1)[1].split("\n    def ", 1)[0]
    assert "ASSIGN_TRANSITIONS" in block
    assert "ASSIGN_ACTION_LABELS_EN" in block
    assert "action_is_server_backed" in block


def test_local_only_actions_are_labelled_local():
    src = _widget_src()
    block = src.split("def _show_assign_menu", 1)[1].split("\n    def ", 1)[0]
    assert "(local)" in block, "a state with no server endpoint must say so"


def test_actions_go_through_the_one_shared_service():
    src = _widget_src()
    block = src.split("def _apply_assign_status", 1)[1].split("\n    def ", 1)[0]
    assert "get_internal_assignment_service" in block
    assert "set_assignment_status" in block
    assert "threading.Thread" in block, "must not block the GUI thread"


def test_failed_action_never_fakes_success():
    src = _widget_src()
    block = src.split("def _on_assign_status_changed", 1)[1].split("\n    def ", 1)[0]
    assert "if not data.get('ok')" in block
    assert "QMessageBox.warning" in block
    # the server cannot clear an assignment today — say so precisely
    assert "unsupported_by_server" in block
    assert "_start_assignment_refresh(force=True)" in block, (
        "a real server removal must be re-read from the server")


# ── the panel now reads the server too ─────────────────────────────────────
def test_panel_details_card_reads_the_merged_server_view():
    src = (REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
           / "internal_assignment_panel.py").read_text(encoding="utf-8", errors="replace")
    block = src.split("def _load_details", 1)[1].split("\n    def ", 1)[0]
    assert "ino_assignment_details" in block
    assert "get_assignment_details" in block
    assert "assigned_by_name" in block
    assert "current_assignment_details" not in block, (
        "the card must no longer read the LOCAL log only — that is why a "
        "cross-machine assignment (50210) showed nothing")
