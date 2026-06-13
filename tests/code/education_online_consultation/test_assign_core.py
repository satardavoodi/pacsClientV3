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


# ── hub gate on the routing (owner directive 2026-06-11) ───────────────────────
def test_ensure_route_allowed_refuses_external_without_hub():
    with pytest.raises(ValueError) as exc:
        core.ensure_route_allowed({"type": "external"}, external_enabled=False)
    assert str(exc.value) == core.EXTERNAL_DISABLED_REASON


def test_ensure_route_allowed_internal_never_gated():
    assert core.ensure_route_allowed({"type": "internal"}, False) == core.INTERNAL
    # unknown type defaults to internal — also never gated
    assert core.ensure_route_allowed({}, False) == core.INTERNAL


def test_ensure_route_allowed_passes_external_when_hub_available():
    assert core.ensure_route_allowed({"type": "external"}, True) == core.EXTERNAL
    # default keeps legacy behaviour byte-identical
    assert core.ensure_route_allowed({"type": "external"}) == core.EXTERNAL


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


# ── workflow v2: creation-only metadata ────────────────────────────────────────
def test_assignment_metadata_only_non_empty_fields():
    assert core.assignment_metadata() == {}
    assert core.assignment_metadata(center_id=" ", patient_id="", modality="") == {}
    assert core.assignment_metadata(
        center_id="C1", patient_id="44113", study_date="2026-06-10",
        modality="MRI",
    ) == {
        "center_id": "C1", "patient_id": "44113",
        "study_date": "2026-06-10", "modality": "MRI",
    }


def test_internal_payload_without_metadata_is_byte_identical():
    """No metadata → exactly the pre-v2 payload (regression guard)."""
    payload = core.build_internal_payload(
        {"type": "internal", "consultation_address": "dr.b@hub"},
        "44113", "DOE^JOHN", study_uid="1.2.3", note="opinion?",
    )
    assert set(payload) == {"type", "consultant_address", "patient_ref",
                            "study_uid", "note"}


def test_internal_payload_carries_metadata_fields():
    payload = core.build_internal_payload(
        {"type": "internal", "consultation_address": "dr.b@hub"},
        "44113", "DOE^JOHN", study_uid="1.2.3",
        metadata={"center_id": "C1", "patient_id": "44113",
                  "study_date": "2026-06-10", "modality": "MRI"},
    )
    assert payload["center_id"] == "C1"
    assert payload["patient_id"] == "44113"
    assert payload["study_date"] == "2026-06-10"
    assert payload["modality"] == "MRI"
    assert "drive_folder_id" not in payload  # internal stays Drive-free


def test_external_registry_payload_carries_metadata_fields():
    payload = core.build_external_registry_payload(
        {"type": "external", "email": "dr.c@x.com"},
        "44113", "DOE^JOHN", drive_folder_id="folderX",
        metadata={"patient_id": "44113", "modality": "DX"},
    )
    assert payload["patient_id"] == "44113"
    assert payload["modality"] == "DX"
    assert payload["drive_folder_id"] == "folderX"


def test_external_payload_unchanged_without_metadata():
    payload = core.build_external_registry_payload(
        {"type": "external", "email": "dr.c@x.com"},
        "44113", "DOE^JOHN", study_uid="1.2.3", drive_folder_id="folderX",
    )
    assert set(payload) == {"type", "consultant_address", "patient_ref",
                            "study_uid", "drive_folder_id"}


# ── workflow v2: internal multi-assign ─────────────────────────────────────────
def test_multi_internal_payloads_one_per_physician():
    consultants = [
        {"type": "internal", "consultation_address": "dr.a@hub"},
        {"type": "internal", "consultation_address": "dr.b@hub"},
    ]
    payloads = core.build_multi_internal_payloads(
        consultants, "44113", "DOE^JOHN", study_uid="1.2.3", note="shared",
        metadata={"modality": "MRI"},
    )
    assert [p["consultant_address"] for p in payloads] == ["dr.a@hub", "dr.b@hub"]
    for p in payloads:
        assert p["type"] == "internal"
        assert p["patient_ref"] == "44113 DOE JOHN"
        assert p["note"] == "shared"          # shared note on every payload
        assert p["modality"] == "MRI"         # shared metadata on every payload
        assert "drive_folder_id" not in p


def test_multi_internal_payloads_dedupes_addresses():
    consultants = [
        {"type": "internal", "consultation_address": "dr.a@hub"},
        {"type": "internal", "consultation_address": "DR.A@HUB"},  # duplicate
    ]
    payloads = core.build_multi_internal_payloads(consultants, "1", "X")
    assert len(payloads) == 1


def test_multi_internal_payloads_empty_selection():
    assert core.build_multi_internal_payloads([], "1", "X") == []


def test_multi_internal_payloads_raise_on_missing_address():
    with pytest.raises(ValueError, match="address"):
        core.build_multi_internal_payloads([{}], "1", "X")


# ── workflow v2: patient metadata display line ─────────────────────────────────
def test_patient_metadata_summary_formats_present_fields():
    assert core.patient_metadata_summary(
        {"patient_id": "44113", "modality": "MRI", "study_date": "2026-06-10"}
    ) == "ID 44113 · MRI · 2026-06-10"
    assert core.patient_metadata_summary({"modality": "DX"}) == "DX"


def test_patient_metadata_summary_empty_for_pre_v2_rows():
    assert core.patient_metadata_summary({}) == ""
    assert core.patient_metadata_summary({"patient_ref": "44113 DOE"}) == ""
    assert core.patient_metadata_summary(None) == ""


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
