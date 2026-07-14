"""Report + Assign columns must render the SERVER workflow state — not "all red".

THE BUG (2026-07-14, live screenshot):
Every row on the Main Patient List showed a red assignee name in the Report column
and a red "active" icon in the Assign column.

Root cause — the PACS ``/assign`` endpoint's ``assignment.radiologist`` is populated
by the RIS **report workflow** for MOST receptions; it is the *reporting radiologist*,
not only an explicit hand-assignment. Live proof (192.168.2.222:8000):

    50178 → دكتر رضا علیزاده     50336 → دكتر رضا علیزاده
    49936 → دكتر رضا علیزاده     50210 → دكتر وحید علیزاده  (the logged-in user)
    20179 → <empty>              50347 → <empty>

So "an assignee exists" was true for nearly every row. Two consequences:
  * the Report column went red for everyone — with SOMEONE ELSE's name — and the red
    name HID the real report-workflow icon (a completed report never showed green);
  * the Assign column showed the same red "active, needs action" icon forever, even
    for receptions whose report was already finished.

The rules this pins:
  1. Report red  ⇔ the assignment is **MINE** (ID match) **and** the report is not done.
  2. Assign icon ⇔ the assignment LIFECYCLE: an active assignment whose report is done
     is **completed** (green), not active (red). No assignment ⇒ the default state.

Pure — no Qt, no network.
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


def test_report_red_mirrors_the_assign_icon():
    """RED name in Report  ⇔  RED icon in Assign. Both columns must compute the
    SAME effective status from the SAME merged source, so they can never disagree."""
    src = _widget_src()
    block = src.split("def _apply_report_status_display", 1)[1].split("\n    def ", 1)[0]
    assert "assignment_display_for" in block
    assert "effective_assign_status" in block, (
        "the Report column must use the same effective status as the Assign icon — "
        "a finished report is 'completed', never red")
    assert "STATUS_ACTIVE" in block


def test_report_red_is_not_gated_on_mine():
    """The column shows the ASSIGNED PERSON, whoever that is. Gating on `mine` also
    never worked: the socket Login response does not reliably carry the user's id,
    while the server identifies an assignee by ObjectId — so `mine` was always False
    and the red name never appeared at all."""
    src = _widget_src()
    block = src.split("def _apply_report_status_display", 1)[1].split("\n    def ", 1)[0]
    red = block.split("STATUS_ACTIVE", 1)[1]
    assert "if _assignee:" in red, "an active assignment must render its assignee"
    assert "and _is_mine" not in block
    assert "AIPACS_REPORT_RED_ONLY_MINE" not in block


def test_report_red_is_not_suppressed_by_a_different_reporting_physician():
    """The old `same_person_name(assignee, physician_text)` gate hid the assignment
    exactly when the reporting physician differed from the assignee — the case an
    assignment exists to make visible."""
    src = _widget_src()
    block = src.split("def _apply_report_status_display", 1)[1].split("\n    def ", 1)[0]
    # ignore the comment that documents the removal
    code = "\n".join(ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))
    assert "same_person_name" not in code


def test_login_carries_the_user_identity_ids():
    """`mine` (and any future "assigned to me" filter) needs the logged-in user's id;
    the login user dict used to carry only full_name/username/role."""
    src = (REPO / "modules" / "network" / "socket_client.py")
    src = (REPO / "modules" / "download_manager" / "network" / "socket_client.py").read_text(
        encoding="utf-8", errors="replace")
    block = src.split("Try to extract user info", 1)[1][:1600]
    for key in ("user_id", "personnel_id", "ris_user_id"):
        assert f"'{key}'" in block, f"login must carry {key} for identity matching"


def test_completed_report_still_reaches_the_green_branch():
    """The green (completed) branch runs BEFORE the assignment branch, and the
    assignment branch can no longer swallow a done report."""
    src = _widget_src()
    block = src.split("def _apply_report_status_display", 1)[1].split("\n    def ", 1)[0]
    green = block.index("#10b981")
    red = block.index("#ef4444")
    assert green < red, "the completed/green branch must be evaluated first"


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
