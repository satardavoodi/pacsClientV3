"""What a clean install tells the operator about the centre name.

Found on the first clean-install rehearsal, running the frozen exe against an
empty config directory: `describe` printed ``"problems": []`` while the centre
was ``""``. The service starts, /api/health looks healthy, and every sign-in is
then refused deep inside the policy with "user is not allowed for this center"
-- a message that names neither the centre that was configured nor any centre
that would have worked.

These tests pin the *content* of the warning, not just its presence: a note
that does not name the centres the policy knows sends the operator back to
guessing, which is the failure this was written to end.
"""

from __future__ import annotations

import json

import pytest

from reception_crm.server import config as server_config


@pytest.fixture
def roles_file(tmp_path, monkeypatch):
    """A roles policy on disk, discovered the way the service discovers it."""

    def _write(centers):
        path = tmp_path / "roles.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "roles": {"owner": {"can_read": ["*"]}},
                    "users": {
                        f"user{index}": {"center": center, "roles": ["owner"]}
                        for index, center in enumerate(centers)
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "reception_crm.permissions._candidate_roles_paths", lambda: (path,)
        )
        return path

    return _write


def _config(center, tmp_path):
    return server_config.ServerConfig(
        center=center,
        data_root=tmp_path,
        reception=server_config.ReceptionConfig(username="u", password="p"),
    )


def test_an_unnamed_centre_is_reported_rather_than_passing_silently(tmp_path, roles_file):
    roles_file(["RAZI"])
    notes = _config("", tmp_path).warnings()
    assert any("center is empty" in note for note in notes)


def test_an_unnamed_centre_is_still_not_a_reason_to_refuse_to_start(tmp_path, roles_file):
    """The operator has to be able to start the service and read /api/health to
    find out what is wrong with it."""
    roles_file(["RAZI"])
    assert _config("", tmp_path).validate() == []


def test_a_mistyped_centre_is_caught_and_the_working_ones_are_named(tmp_path, roles_file):
    """'RAZ' instead of 'RAZI' passes every other check and denies every user."""
    roles_file(["RAZI", "INO"])
    notes = "\n".join(_config("RAZ", tmp_path).warnings())
    assert "'RAZ'" in notes
    assert "INO" in notes and "RAZI" in notes


def test_a_centre_the_policy_knows_produces_no_note(tmp_path, roles_file):
    roles_file(["RAZI"])
    notes = "\n".join(_config("RAZI", tmp_path).warnings())
    assert "center" not in notes.lower() or "matches no user" not in notes


def test_a_missing_policy_is_named_as_the_cause(tmp_path, monkeypatch):
    monkeypatch.setattr("reception_crm.permissions._candidate_roles_paths", lambda: ())
    notes = "\n".join(_config("RAZI", tmp_path).warnings())
    assert "roles.json" in notes


def test_a_malformed_policy_does_not_stop_the_service_starting(tmp_path, monkeypatch):
    """warnings() runs on the start path. A broken roles.json must produce a
    note, not an exception that takes the service down with it."""
    broken = tmp_path / "roles.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(
        "reception_crm.permissions._candidate_roles_paths", lambda: (broken,)
    )
    notes = "\n".join(_config("RAZI", tmp_path).warnings())
    assert "roles policy could not be read" in notes
