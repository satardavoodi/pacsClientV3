"""Guard: per-chat case metadata — storage, three-layer merge, safety rules
(2026-08-06, step 1 of the chat-metadata plan).

THE INVARIANT THAT MATTERS MOST: nothing here reaches a prompt yet. This is the
foundation layer. A test below asserts that, so wiring it into report generation
has to be a deliberate act with its own guard, not an accident.

The rest pins the three design decisions that make it safe:
  * three layers (auto / user / effective) so re-detection cannot destroy a
    physician's correction, and one edit cannot freeze future enrichment;
  * `sex` is NEVER inferred — DICOM has it for 3% of patients here and the report
    prompts forbid assuming it;
  * unknown body parts map to NOTHING, never to a plausible guess.
"""

import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind import session_metadata as sm  # noqa: E402


# ── region normalisation: conservative by design ─────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("CHEST", ("chest",)),
    ("BRAIN", ("brain",)),
    ("HEAD", ("brain",)),
    ("LSPINE", ("spine_lumbar",)),
    ("CSPINE", ("spine_cervical",)),
    ("KNEE", ("knee",)),
    ("BREAST", ("breast",)),
])
def test_known_body_parts_map(raw, expected):
    assert sm.normalize_region(raw) == expected


def test_multi_region_tag_expands():
    """ABDOMENPELVIS is a real value in this database (68 series) — one tag, two
    regions."""
    assert sm.normalize_region("ABDOMENPELVIS") == ("abdomen", "pelvis")


@pytest.mark.parametrize("raw", ["", None, "   ", "WHATEVER", "XYZ", "12345"])
def test_unknown_body_parts_map_to_nothing(raw):
    """A wrong region silently removes the correct reporting rules; a missing one
    only falls back to the full prompt. So: never guess."""
    assert sm.normalize_region(raw) == ()


def test_every_mapped_region_is_in_the_canonical_vocabulary():
    for regions in sm._DICOM_REGION_MAP.values():
        for r in regions:
            assert r in sm.REGION_KEYS, f"{r} is not a canonical region key"


# ── the three-layer merge ────────────────────────────────────────────────────

def test_user_wins_field_by_field():
    auto = {"case": {"regions": ["chest"], "modality_selected": "CT"}}
    user = {"case": {"regions": ["chest", "abdomen"]}}
    eff = sm.merge_layers(auto, user)
    assert eff["case"]["regions"] == ["chest", "abdomen"], "user edit must win"
    assert eff["case"]["modality_selected"] == "CT", "a sibling field must survive"


def test_a_user_edit_does_not_wipe_the_rest_of_its_branch():
    """The failure a single merged blob would cause."""
    auto = {"patient": {"patient_id": "53341", "sex": "unknown", "age": "57"}}
    user = {"patient": {"sex": "F"}}
    eff = sm.merge_layers(auto, user)
    assert eff["patient"] == {"patient_id": "53341", "sex": "F", "age": "57"}


def test_none_in_the_user_layer_never_blanks_an_auto_value():
    auto = {"case": {"regions": ["chest"]}}
    assert sm.merge_layers(auto, {"case": {"regions": None}})["case"]["regions"] == ["chest"]


def test_refreshing_auto_preserves_user_edits():
    """Re-detection must not destroy a correction — the whole reason for 2 layers."""
    user = {"case": {"regions": ["chest", "abdomen", "pelvis"]}}
    first = sm.merge_layers({"case": {"regions": ["chest"]}}, user)
    later = sm.merge_layers({"case": {"regions": ["brain"]}}, user)   # detection changed
    assert first["case"]["regions"] == later["case"]["regions"] == ["chest", "abdomen", "pelvis"]


def test_edited_fields_lists_dotted_paths():
    assert sm.edited_fields({"case": {"regions": ["a"]}, "patient": {"sex": "F"}}) == [
        "case.regions", "patient.sex",
    ]


def test_merge_is_non_destructive_to_its_inputs():
    auto = {"case": {"regions": ["chest"]}}
    user = {"case": {"regions": ["abdomen"]}}
    sm.merge_layers(auto, user)
    assert auto["case"]["regions"] == ["chest"] and user["case"]["regions"] == ["abdomen"]


# ── building the auto layer ──────────────────────────────────────────────────

def test_build_from_study_and_patient():
    auto = sm.build_auto_from_context(
        study={"study_uid": "1.2.3", "modality": "CT", "body_part": "CHEST",
               "study_description": "CT CHEST", "study_date": "20260806"},
        patient={"patient_id": "53341", "sex": "F", "age": "57"},
        modality_selected="CT",
    )
    assert auto["patient"]["patient_id"] == "53341"
    assert auto["studies"][0]["study_uid"] == "1.2.3"
    assert auto["case"]["regions"] == ["chest"]
    assert auto["case"]["modality_selected"] == "CT"
    assert auto["case"]["multi_region"] is False


def test_series_body_parts_widen_the_region_set():
    """A chest/abdomen/pelvis study is frequently tagged per series."""
    auto = sm.build_auto_from_context(
        study={"study_uid": "1.2.3", "modality": "CT", "body_part": "CHEST"},
        series=[{"body_part_examined": "ABDOMENPELVIS"}, {"body_part_examined": "CHEST"}],
    )
    assert auto["case"]["regions"] == ["chest", "abdomen", "pelvis"]
    assert auto["case"]["multi_region"] is True


def test_sex_is_never_inferred():
    """DICOM sex is 3% populated here, and the report prompts forbid assuming it.
    An absent value must read as an explicit 'unknown', with low-confidence
    provenance — never a guess and never an inviting blank."""
    auto = sm.build_auto_from_context(patient={"patient_id": "1", "sex": ""})
    assert auto["patient"]["sex"] == "unknown"
    assert auto["provenance"]["patient.sex"]["source"] == "none"
    assert auto["provenance"]["patient.sex"]["confidence"] == "low"


def test_verified_sex_is_kept_with_provenance():
    auto = sm.build_auto_from_context(patient={"patient_id": "1", "sex": "m"})
    assert auto["patient"]["sex"] == "M"
    assert auto["provenance"]["patient.sex"]["source"] == "dicom"


def test_unknown_body_part_yields_no_regions():
    auto = sm.build_auto_from_context(study={"study_uid": "1", "body_part": "MYSTERY"})
    assert "regions" not in auto["case"]


def test_every_auto_value_carries_provenance():
    auto = sm.build_auto_from_context(
        study={"study_uid": "1.2.3", "body_part": "KNEE"},
        patient={"patient_id": "9"},
        modality_selected="MRI",
    )
    for key in ("patient.patient_id", "case.modality_selected", "case.regions"):
        assert key in auto["provenance"], f"missing provenance for {key}"
        assert auto["provenance"][key]["confidence"] in ("high", "medium", "low")


def test_empty_context_is_harmless():
    auto = sm.build_auto_from_context()
    assert auto["schema_ver"] == sm.SCHEMA_VERSION
    assert auto["studies"] == [] and auto["case"] == {}


# ── THE step-1 boundary: nothing consumes this yet ───────────────────────────

def test_no_prompt_path_consumes_metadata_yet():
    """Step 1 is the foundation ONLY. Wiring this into report generation must be a
    deliberate, separately-guarded change — gated on measuring detection accuracy
    against real cases first. If this test fails, that step happened by accident."""
    for rel in ("modules/EchoMind/viewer_chat/openai_reporter.py",
                "modules/EchoMind/viewer_chat/openai_parallel_backend.py"):
        with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
            assert "session_metadata" not in fh.read(), (
                f"{rel} consumes chat metadata — that is a later, flagged step"
            )


def test_seeding_is_wired_but_cannot_break_chat_creation():
    with open(os.path.join(_ROOT, "modules/EchoMind/viewer_chat/ai_chat_pages.py"),
              encoding="utf-8") as fh:
        src = fh.read()
    i = src.index("def _seed_session_metadata")
    j = src.index("\n    def ", i + 10)
    helper = src[i:j]
    assert "try:" in helper and "except Exception" in helper, "must be fully swallowed"
    assert "populate_for_chat" in helper
    # and it is actually called when a chat is created
    k = src.index("def _new_session")
    assert "_seed_session_metadata(sid)" in src[k:k + 600]


# ═════════════════════════════════════════════════════════════════════════════
# Physician attribution (Phase A) — conservative on purpose
# ═════════════════════════════════════════════════════════════════════════════

def test_single_identity_resolves():
    assert sm.resolve_physician_id_from_identities(
        [{"aipacs_user": "vahid"}, {"aipacs_user": "vahid"}]
    ) == "vahid"


def test_ambiguous_identities_resolve_to_nothing():
    """A WRONG attribution is worse than none — it credits one radiologist with
    another's report. AI-PACS has no per-report login, so a shared workstation
    must produce an unattributed row rather than a guessed one."""
    assert sm.resolve_physician_id_from_identities(
        [{"aipacs_user": "vahid"}, {"aipacs_user": "someone_else"}]
    ) is None


@pytest.mark.parametrize("rows", [[], [{}], [{"aipacs_user": ""}], [{"aipacs_user": "   "}]])
def test_no_identity_resolves_to_none(rows):
    assert sm.resolve_physician_id_from_identities(rows) is None
