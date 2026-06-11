"""Guards for the Assign-consultation decision logic + registry merge (ADR-0006).

Qt-free: the dialog/page only compose these pieces. Covers internal-vs-external
routing, payload shapes (an internal payload must NEVER carry Drive fields), the
patient_ref format, the Inbox/Sent registry merge, and the per-status actions."""

import pytest

from modules.education.online_consultation import assign_core as core


# ── routing ────────────────────────────────────────────────────────────────────
def test_explicit_types_route_as_declared():
    assert core.decide_route({"type": "internal"}) == core.INTERNAL
    assert core.decide_route({"type": "External"}) == core.EXTERNAL
    assert core.decide_route({"consultant_type": "external"}) == core.EXTERNAL


def test_unknown_type_defaults_to_internal_no_upload():
    """Clinically safer default: no images ever leave the workstation."""
    assert core.decide_route({}) == core.INTERNAL
    assert core.decide_route({"type": "weird"}) == core.INTERNAL


def test_is_external_flag_is_honoured():
    assert core.decide_route({"is_external": True}) == core.EXTERNAL


# ── patient_ref + addresses ────────────────────────────────────────────────────
def test_patient_ref_is_id_then_name_with_carets_collapsed():
    assert core.build_patient_ref("44113", "DOE^JOHN") == "44113 DOE JOHN"
    assert core.build_patient_ref(" 7 ", "") == "7"


def test_consultant_address_prefers_consultation_address():
    c = {"consultation_address": "dr.a@hub", "email": "dr.a@gmail.com"}
    assert core.consultant_address(c) == "dr.a@hub"
    assert core.consultant_address({"email": "x@y.z"}) == "x@y.z"


def test_consultant_display_snapshot():
    d = core.consultant_display({
        "name": "Dr A", "specialty": "Neuroradiology",
        "availability": "Mon-Wed", "type": "external", "email": "a@x.com",
    })
    assert d["name"] == "Dr A"
    assert d["specialty"] == "Neuroradiology"
    assert d["availability"] == "Mon-Wed"
    assert d["badge"] == "External"
    assert d["address"] == "a@x.com"


# ── payloads ───────────────────────────────────────────────────────────────────
def test_internal_payload_shape_and_no_drive_fields():
    payload = core.build_internal_payload(
        {"type": "internal", "consultation_address": "dr.b@hub"},
        "44113", "DOE^JOHN", study_uid="1.2.3", note="opinion?",
    )
    assert payload == {
        "type": "internal",
        "consultant_address": "dr.b@hub",
        "patient_ref": "44113 DOE JOHN",
        "study_uid": "1.2.3",
        "note": "opinion?",
    }
    assert "drive_folder_id" not in payload


def test_internal_payload_requires_address():
    with pytest.raises(ValueError, match="address"):
        core.build_internal_payload({}, "1", "X")


def test_external_registry_payload_carries_drive_folder():
    payload = core.build_external_registry_payload(
        {"type": "external", "email": "dr.c@x.com"},
        "44113", "DOE^JOHN", study_uid="1.2.3",
        note="", drive_folder_id="folderX",
    )
    assert payload["type"] == "external"
    assert payload["drive_folder_id"] == "folderX"
    assert payload["patient_ref"] == "44113 DOE JOHN"
    assert "note" not in payload  # empty fields are omitted


# ── registry merge into Inbox/Sent ─────────────────────────────────────────────
def test_internal_rows_always_shown_and_tagged():
    rows = core.registry_rows_to_display(
        [{"id": 1, "type": "internal", "status": "pending"}],
        [{"consultation_id": "c1", "remote_folder_id": "fX"}],
    )
    assert len(rows) == 1
    assert rows[0]["_registry"] is True
    assert rows[0]["_tag"] == core.INTERNAL_ROW_TAG


def test_external_registry_row_deduped_against_drive_row():
    drive = [{"consultation_id": "c1", "remote_folder_id": "folderX"}]
    rows = core.registry_rows_to_display(
        [
            {"id": 1, "type": "external", "drive_folder_id": "folderX"},
            {"id": 2, "type": "external", "drive_folder_id": "folderY"},
        ],
        drive,
    )
    assert [r["id"] for r in rows] == [2]  # folderX already shown via Drive


def test_drive_rows_are_never_modified():
    drive = [{"consultation_id": "c1", "remote_folder_id": "fX", "status": "uploaded"}]
    before = [dict(d) for d in drive]
    core.registry_rows_to_display([{"id": 1, "type": "internal"}], drive)
    assert drive == before


# ── actions per role/status ────────────────────────────────────────────────────
def test_inbox_actions_lifecycle():
    assert core.registry_actions({"status": "pending"}, "inbox") == ["accept", "decline"]
    assert core.registry_actions({"status": "accepted"}, "inbox") == ["answer"]
    assert core.registry_actions({"status": "answered"}, "inbox") == []
    assert core.registry_actions({"status": "closed"}, "inbox") == []


def test_sent_actions_lifecycle():
    assert core.registry_actions({"status": "pending"}, "sent") == ["close"]
    assert core.registry_actions({"status": "answered"}, "sent") == ["close"]
    assert core.registry_actions({"status": "declined"}, "sent") == []


def test_action_patch_bodies():
    assert core.action_patch("accept") == {"status": "accepted"}
    assert core.action_patch("decline") == {"status": "declined"}
    assert core.action_patch("close") == {"status": "closed"}
    assert core.action_patch("answer", "my opinion") == {
        "status": "answered", "answer": "my opinion",
    }


def test_unknown_action_raises():
    with pytest.raises(ValueError, match="Unknown registry action"):
        core.action_patch("explode")
