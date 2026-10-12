"""The capability gaps the Persian benchmark exposed (F4, F5, F6).

Each of these was a question the agent could not answer while the data sat in
the database: peak hour, the discount list, the deletion list, and «MRI با تزریق».
"""

from __future__ import annotations

import pytest

from reception_crm.local import datamodel as dm
from reception_crm.local import receptions as R


# --------------------------------------------------------------- F5 peak hour

def test_hour_and_half_hour_are_groupable():
    """«پیک پذیرش دیروز چه ساعتی بوده؟» had no path to an answer at all."""
    assert "hour" in R.GROUP_BY
    assert "halfHour" in R.GROUP_BY


def test_hour_is_taken_from_the_reception_time_field():
    expr = R.GROUP_BY["hour"]
    assert expr == {"$substrBytes": ["$Time", 0, 2]}, "hour must come from receptions.Time"


def test_unknown_group_by_still_refuses_with_the_known_list():
    class _Col:
        def aggregate(self, *a, **k):  # pragma: no cover - must not be reached
            raise AssertionError("must refuse before querying")

    with pytest.raises(R.FilterError) as exc:
        R._breakdown(_Col(), {}, "phase-of-the-moon", None)
    assert "hour" in str(exc.value), "the refusal must name what IS groupable"


# --------------------------------------------------------- F4 discounts/deletes

def test_discount_filter_uses_the_field_that_actually_holds_the_money():
    """`discountTotal` is 0 on every reception measured; `cashDeskDiscount` is not."""
    assert dm.DISCOUNT_FIELDS[0] == "cashDeskDiscount"
    query, applied = R.build_filter(date_from="1405/06/01", date_to="1405/06/01",
                                    discounted_only=True)
    ors = [c for c in query["$and"] if "$or" in c][0]["$or"]
    assert {"cashDeskDiscount": {"$gt": 0}} in ors
    assert applied["discount"]["any of"][0] == "cashDeskDiscount"


def test_deleted_only_selects_deleted_and_does_not_also_exclude_them():
    """The obvious bug here would be applying LIVE_ONLY as well and matching nothing."""
    query, applied = R.build_filter(date_from="1405/06/01", date_to="1405/06/01",
                                    deleted_only=True)
    assert {"deleted": True} in query["$and"]
    assert dm.LIVE_ONLY not in query["$and"], "deleted_only must not also exclude deleted"
    assert "ONLY deleted receptions" in applied["deleted"]


def test_default_still_excludes_deleted():
    query, applied = R.build_filter(date_from="1405/06/01", date_to="1405/06/01")
    assert dm.LIVE_ONLY in query["$and"]
    assert applied["deleted"] == "excluded"


# ------------------------------------------------------------------ F6 contrast

@pytest.mark.parametrize("name,expected", [
    ("MRI مغز شامل brainstem با ماده حاجب", "with"),
    ("ام آر آي ستون فقرات كمري بدون كنتراست ", "without"),
    ("MRI (به عنوان مثال proton) لگن با و بدون ماده حاجب", "both"),
    ("ام آر آي مجاري صفراوي و مجاري پانكراتيك با و بدون كنتراست", "both"),
    ("MRM (MR ماموگرافی- یک طرفه)", "unknown"),
])
def test_contrast_classification(name, expected):
    assert dm.contrast_of(name) == expected


def test_the_negation_is_the_discriminator():
    """The trap: «بدون کنتراست» CONTAINS «کنتراست».

    A substring match on the word would have returned 68 receptions on
    1405/06/01 for a question about contrast — every one of them explicitly
    performed WITHOUT it.
    """
    without = "ام آر آي ستون فقرات كمري بدون كنتراست "
    assert "كنتراست" in without, "the fixture must contain the word, or this proves nothing"
    assert dm.contrast_of(without) == "without"


def test_both_is_tested_before_without():
    """«با و بدون» contains «بدون»; wrong order files every combined study as plain."""
    assert dm.contrast_of("MRI شکم با و بدون مواد حاجب") == "both"


@pytest.mark.parametrize("text,expected", [
    ("با تزریق", "with"),
    ("تزریق", "with"),
    ("MRI با تزریق", "with"),
    ("با کنتراست", "with"),
    ("بدون تزریق", "without"),
    ("بدون کنتراست", "without"),
    ("with contrast", "with"),
    ("MRI مغز", None),
    ("", None),
])
def test_user_intent_is_read_correctly(text, expected):
    assert dm.contrast_intent(text) == expected


def test_without_intent_wins_over_with_intent():
    """«بدون تزریق» contains «تزریق» — the order of the intent scan matters."""
    assert dm.contrast_intent("بدون تزریق") == "without"


def test_combined_intent_wins_over_embedded_without_phrase():
    assert dm.contrast_intent("MRI کمر با و بدون کنتراست") == "both"


def test_with_intent_includes_the_combined_studies():
    """A «با و بدون» study did involve an injection; counting it is the honest answer."""
    catalogue = [
        {"Service": "MRI مغز با ماده حاجب", "Modality": "2"},
        {"Service": "MRI لگن با و بدون ماده حاجب", "Modality": "2"},
        {"Service": "MRI مغز بدون ماده حاجب", "Modality": "2"},
        {"Service": "CT شکم با ماده حاجب", "Modality": "1"},
    ]
    original = dm.service_catalog
    dm.service_catalog = lambda: catalogue          # type: ignore[assignment]
    try:
        got = dm.services_by_contrast("with", modality="2")
        assert "MRI مغز با ماده حاجب" in got
        assert "MRI لگن با و بدون ماده حاجب" in got
        assert "MRI مغز بدون ماده حاجب" not in got
        assert "CT شکم با ماده حاجب" not in got, "modality filter must apply"
    finally:
        dm.service_catalog = original               # type: ignore[assignment]


def test_without_intent_excludes_combined_studies():
    catalogue = [
        {"Service": "MRI کمر بدون ماده حاجب", "Modality": "2"},
        {"Service": "MRI کمر با و بدون ماده حاجب", "Modality": "2"},
    ]
    original = dm.service_catalog
    dm.service_catalog = lambda: catalogue          # type: ignore[assignment]
    try:
        assert dm.services_by_contrast("without", modality="2") == [
            "MRI کمر بدون ماده حاجب"
        ]
    finally:
        dm.service_catalog = original               # type: ignore[assignment]


def test_compound_lumbar_contrast_filter_keeps_anatomy_and_negation():
    performed = [
        "MRI کانال spinal و محتویات ان ناحیه لومبر بدون کنتراست (بدون ماده حاجب )",
        "ام آر آي ستون فقرات كمري بدون كنتراست ",
        "MRI مغز بدون ماده حاجب",
        "MRI ناحیه لومبار با و بدون ماده حاجب",
    ]

    query, applied = R.build_filter(
        service="ام‌آر‌آی کمر بدون تزریق ماده حاجب",
        modality="MRI",
        date_from="1405/06/05",
        date_to="1405/06/11",
        contrast_names=performed,
    )

    service_condition = next(
        item for item in query["$and"] if "services.Service" in item
    )
    assert service_condition["services.Service"]["$in"] == sorted(performed[:2])
    assert applied["service"]["canonicalConcept"] == "lumbar_spine"
    assert applied["service"]["contrastIntent"] == "without"
    assert applied["service"]["matchedCount"] == 2


def test_unmapped_anatomy_survives_contrast_qualifier_removal():
    performed = [
        "MRI مغز بدون ماده حاجب",
        "MRI شکم بدون ماده حاجب",
        "MRI مغز با و بدون ماده حاجب",
    ]

    matched, resolution = dm.narrow_contrast_services(
        "MRI مغز بدون کنتراست", performed, modality="MRI",
    )

    assert matched == ["MRI مغز بدون ماده حاجب"]
    assert resolution["subject"] == "مغز"
    assert resolution["canonicalConcept"] is None


def test_modality_can_be_inferred_from_compound_service_text():
    inferred = dm.modality_in_text(
        "MRI کانال spinal و محتویات آن ناحیه لومبر بدون کنتراست"
    )
    assert inferred is not None
    assert inferred.code == "2"


def test_numeric_department_code_is_not_inferred_from_free_text():
    assert dm.modality_in_text("مرحله 2 بدون کنتراست") is None


def test_disabled_mammography_department_is_not_inferred_from_service_text():
    assert dm.modality_in_text("ماموگرافی با ماده حاجب") is None


# ------------------------------------------------- F10 a zero with its vocabulary

def test_report_prompt_forbids_a_bare_zero_when_terms_do_match():
    """The tool computed «شکم ۲ / لگن ۲» and the answer printed only «۰».

    `_terms_that_do_match` exists precisely so a zero is never confident
    nothing. It ran, the breakdown was in the payload, and the answer dropped
    it — so the gap was in what the answer prompt asks for, not in the query.
    A capability nobody is told to use is a capability you do not have.
    """
    from reception_crm.llm import prompt_store

    text = prompt_store.read("answer_report.md")
    assert "termBreakdown" in text, "the answer prompt must name the field it must use"
    assert "شکم" in text and "لگن" in text, "the rule needs its worked example"
    # And it must forbid the arithmetic the breakdown invites.
    assert "Never add those figures together" in text
