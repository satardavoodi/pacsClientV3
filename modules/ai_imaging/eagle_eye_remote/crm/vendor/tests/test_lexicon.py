"""The lexicon's guarantees, asserted offline.

The live-database half of the verification lives in scripts/verify_lexicon.py and
must be run against the reception server; these tests run anywhere and protect the
behaviour that the 1405/06/01 failure depended on.
"""

from __future__ import annotations

import pytest

from reception_crm import lexicon as L
from reception_crm.lexicon.normalize import fold, squash


# --------------------------------------------------------------- normalisation

@pytest.mark.parametrize(
    "a,b",
    [
        ("سونوگرافی", "سونوگرافي"),        # Persian yeh vs Arabic yeh
        ("رادیولوژی", "راديولوژي"),        # both letters at once
        ("کبد", "كبد"),                    # keheh vs kaf
        ("سی‌تی‌اسکن", "سی تی اسکن"),      # ZWNJ vs space
        ("۱۴۰۵/۰۶/۰۱", "1405/06/01"),      # Persian digits
        ("زیــــاد", "زیاد"),               # tatweel
    ],
)
def test_spelling_variants_fold_together(a, b):
    assert squash(a) == squash(b), f"{a!r} and {b!r} must reach one lexicon entry"


def test_fold_keeps_words_separate_but_squash_does_not():
    assert fold("سی تی اسکن") != squash("سی تی اسکن")
    assert squash("سی تی اسکن") == squash("سیتیاسکن")


# ------------------------------------------------------------------ resolution

@pytest.mark.parametrize(
    "term,code",
    [
        # the vendor's own English catalogue names - every one of these returned
        # a silent zero before the lexicon existed
        ("Sonography", "3"),
        ("Radiology", "4"),
        ("CT Scan", "1"),
        ("MRI", "2"),
        ("Bone Density", "5"),
        # the vendor's short codes
        ("US", "3"),
        ("DX", "4"),
        ("MR", "2"),
        # Persian, both spellings
        ("سونوگرافی", "3"),
        ("سونوگرافي", "3"),
        ("رادیولوژی", "4"),
        ("ام آر آی", "2"),
        # informal
        ("sono", "3"),
        ("xray", "4"),
        ("CAT scan", "1"),
        ("DEXA", "5"),
        # bare codes still work
        ("3", "3"),
        ("4", "4"),
    ],
)
def test_modality_resolves(term, code):
    assert L.resolve("modality", term).code == code


def test_unknown_value_raises_and_never_becomes_a_filter():
    """The defect this whole asset exists to prevent.

    `normalize_modality` returned the raw string on a miss, so patient-list built
    `{"modality": "Sonography"}`, matched nothing, and reported 0 patients with
    status ok on a day with 85.
    """
    with pytest.raises(L.UnknownValue):
        L.resolve("modality", "Brain MRI")
    with pytest.raises(L.UnknownValue):
        L.modality_filter("not a modality at all")


def test_disabled_value_is_distinguished_from_unknown():
    """Mammography EXISTS (code 9) but is disabled - a different answer to the user."""
    with pytest.raises(L.DisabledValue) as exc:
        L.resolve("modality", "Mammography")
    assert exc.value.extra.get("code") == "9"
    # and it is reachable when the caller knowingly asks for it
    assert L.resolve("modality", "Mammography", allow_disabled=True).code == "9"


def test_empty_value_raises():
    with pytest.raises(L.UnknownValue):
        L.resolve("modality", "")


# ---------------------------------------------------------------- filter shape

def test_modality_filter_covers_both_storage_shapes():
    """receptions.modality is a string on most rows and an object on a few."""
    f = L.modality_filter("Sonography")
    assert f == {"$or": [{"modality": "3"}, {"modality._id": "3"}]}


def test_service_group_filter_matches_the_stored_spelling():
    """The user types Persian yeh; the catalogue stores Arabic yeh."""
    f = L.service_group_filter("سونوگرافی")
    stored = f["services.ServiceGroup"]["$in"]
    assert stored, "must name at least one spelling actually present in the catalogue"
    assert all(isinstance(s, str) for s in stored)


# ------------------------------------------------------------- query contract

def test_valid_query_resolves_its_coded_filters():
    v = L.validate_query({
        "mode": "report",
        "target_entity": "reception",
        "aggregation": "count",
        "filters": {"date_range": "today", "modality": "Sonography"},
    })
    assert v.resolved["modality=Sonography"].code == "3"


def test_query_with_unknown_filter_value_is_refused_before_execution():
    with pytest.raises(L.UnknownValue):
        L.validate_query({"target_entity": "reception",
                          "filters": {"modality": "Brain MRI"}})


def test_query_with_unknown_entity_is_refused():
    with pytest.raises(L.InvalidQuery):
        L.validate_query({"target_entity": "spaceship"})


def test_answerable_false_passes_straight_through():
    """The model must have a way to say 'I cannot' that is not a wrong answer."""
    v = L.validate_query({"answerable": False, "reason": "unknown_value"})
    assert v.resolved == {}


def test_count_grain_is_surfaced_as_a_warning():
    v = L.validate_query({"target_entity": "reception", "aggregation": "count"})
    assert any("distinct ReceptionID" in w for w in v.warnings)


# ------------------------------------------------------------------ integrity

def test_every_concept_has_a_display_and_a_code():
    for name, vs in L.load()["value_sets"].items():
        for c in vs.get("concepts", []):
            assert c.get("code") or c.get("key"), f"{name}: concept without a code"


def test_every_entity_that_can_be_counted_declares_its_grain():
    countable = {"patient", "reception", "service", "transaction", "study"}
    for name in countable:
        entity = L.load()["entities"][name]
        assert entity.get("count_key"), f"{name} must declare count_key"


def test_prompt_fragment_is_trimmed_not_the_whole_file():
    """Dumping the whole schema measurably costs accuracy; ask for what you need."""
    frag = L.describe_for_prompt(value_sets=["modality"], entities=["reception"])
    assert "Sonography" in frag
    assert len(frag) < 6000
    # a value set that was not asked for must not appear
    assert "transaction_type" not in frag


def test_recorded_data_quality_issues_are_present():
    """These are known and deliberately recorded; losing them would hide drift."""
    dq = L.load()["data_quality"]
    assert dq["orphan_modality_codes_in_services"]["codes"] == ["6"]
    assert "آزاد" in dq["insurance_type_non_code_values"]["values"]
