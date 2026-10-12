"""Report author and internal assignment are separate Home projections.

Owner requirement, 2026-10-07: Report names the reporting physician; Assign
shows the verified internal assignment lifecycle. A finished report completes
an active assignment, but an assignee never substitutes for the report author.
Historical identity/lifecycle guards below remain independent of presentation.
Pure model/source guards; no application database or network.
"""
from __future__ import annotations

from pathlib import Path

from modules.network import ino_assignment_models as m
from modules.network import ino_assignment_refresh as refresh

REPO = Path(__file__).resolve().parents[3]


# ── 1. the Assign lifecycle: a done report completes the assignment ─────────
def test_active_assignment_with_a_finished_report_is_completed_not_active():
    for done in ("completed", "complete", "archived",
                 "physician_approved", "secretary_approved"):
        assert m.effective_assign_status(m.STATUS_ACTIVE, done) == m.STATUS_COMPLETED, done


def test_active_assignment_with_a_pending_report_stays_active():
    for pending in ("pending", "awaiting_approval", "awaiting_physician_approval",
                    "awaiting_secretary_approval", "", None):
        assert m.effective_assign_status(m.STATUS_ACTIVE, pending) == m.STATUS_ACTIVE


def test_no_assignment_stays_the_default_state_whatever_the_report():
    """A patient who was never assigned must keep the neutral icon — the Assign icon
    may only change when a real server-side assignment exists."""
    for report in ("completed", "pending", ""):
        assert m.effective_assign_status("", report) == ""
    icon = m.assign_icon_for_status("", "")
    assert icon["tooltip"] == "Not assigned"


def test_terminal_states_are_never_overridden_by_the_report():
    for st in (m.STATUS_CANCELLED, m.STATUS_DEACTIVATED, m.STATUS_COMPLETED):
        assert m.effective_assign_status(st, "completed") == st
        assert m.effective_assign_status(st, "pending") == st


def test_every_lifecycle_state_has_its_own_icon_and_colour():
    seen = {}
    for st in ("", m.STATUS_ACTIVE, m.STATUS_COMPLETED,
               m.STATUS_DEACTIVATED, m.STATUS_CANCELLED):
        ic = m.assign_icon_for_status(st, "Dr X")
        seen[st] = (ic["icon"], ic["color"])
    # not-assigned / active / completed must be visually distinct
    assert seen[""] != seen[m.STATUS_ACTIVE]
    assert seen[m.STATUS_ACTIVE] != seen[m.STATUS_COMPLETED]
    assert seen[""] != seen[m.STATUS_COMPLETED]


def test_report_is_done_vocabulary():
    assert m.report_is_done("completed") and m.report_is_done("COMPLETE")
    assert not m.report_is_done("pending")
    assert not m.report_is_done("")


# ── 2. "mine" is an ID match — the whole reason the column went red ─────────
def test_another_doctors_assignment_is_not_mine():
    """Live data: rows 50178/50336/49936 are assigned to دكتر رضا علیزاده, while the
    logged-in user is دكتر وحید علیزاده. Those rows must NOT go red."""
    me = ["6887a95ae7e66cdc2029a960"]              # دكتر وحید علیزاده
    other = "69f314c684663b7ae6e6318a"             # دكتر رضا علیزاده
    assert refresh.assignment_is_mine(other, me) is False
    assert refresh.assignment_is_mine("6887a95ae7e66cdc2029a960", me) is True
    # and never by name
    assert refresh.assignment_is_mine("دكتر وحید علیزاده", me) is False


def test_snapshot_persists_mine_and_the_assignee_id(monkeypatch, tmp_path):
    from modules.network import ino_assignment_server_state as state

    monkeypatch.setattr(state, "_base_dir", lambda: str(tmp_path))
    state.set_state("50210", assigned=True, assignee_name="دكتر وحید علیزاده",
                    assignee_id="6887a95ae7e66cdc2029a960", mine=True)
    state.set_state("50178", assigned=True, assignee_name="دكتر رضا علیزاده",
                    assignee_id="69f314c684663b7ae6e6318a", mine=False)

    assert state.get_state("50210")["mine"] is True
    assert state.get_state("50178")["mine"] is False
    assert state.get_state("50178")["assignee_id"] == "69f314c684663b7ae6e6318a"


# ── 3. wiring pins ─────────────────────────────────────────────────────────
def _widget_src() -> str:
    return (REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
            / "patient_table_widget.py").read_text(encoding="utf-8", errors="replace")


def test_report_column_is_separate_from_assignment_lifecycle():
    block = _widget_src().split("def _apply_report_status_display", 1)[1].split("\n    def ", 1)[0]
    assert "assignment_display_for" not in block
    assert "Assigned to:" not in block
    assert "Reporting Physician:" in block


def test_report_column_has_no_assignee_substitution():
    block = _widget_src().split("def _apply_report_status_display", 1)[1].split("\n    def ", 1)[0]
    assert "assignee_name" not in block
    assert "setText(physician_text)" in block


def test_report_author_does_not_depend_on_assignment_identity():
    block = _widget_src().split("def _apply_report_status_display", 1)[1].split("\n    def ", 1)[0]
    assert "same_person_name" not in block
    assert "STATUS_ACTIVE" not in block


def test_login_carries_the_user_identity_ids():
    """`mine` (and any future "assigned to me" filter) needs the logged-in user's id;
    the login user dict used to carry only full_name/username/role."""
    src = (REPO / "modules" / "network" / "socket_client.py")
    src = (REPO / "modules" / "download_manager" / "network" / "socket_client.py").read_text(
        encoding="utf-8", errors="replace")
    block = src.split("Try to extract user info", 1)[1][:1600]
    for key in ("user_id", "personnel_id", "ris_user_id"):
        assert f"'{key}'" in block, f"login must carry {key} for identity matching"


def test_completed_report_keeps_green_author_display():
    block = _widget_src().split("def _apply_report_status_display", 1)[1].split("\n    def ", 1)[0]
    assert "#10b981" in block
    assert "normalized_status in ('completed', 'complete')" in block
    assert "STATUS_COLORS.get(report_status" in block


def test_assign_icon_uses_the_effective_lifecycle_status():
    src = _widget_src()
    block = src.split("def _assign_icon_state", 1)[1].split("\n    def ", 1)[0]
    assert "effective_assign_status" in block
    assert "report_status_for_reception" in block


def test_assign_icon_repaints_when_the_report_status_changes():
    """The Assign lifecycle depends on the report being done, so a late report
    status must repaint the icon — otherwise it keeps the stale red active icon."""
    src = _widget_src()
    block = src.split("def _update_report_status_in_table", 1)[1].split("\n    def ", 1)[0]
    assert "refresh_assign_icon_for_patient" in block
