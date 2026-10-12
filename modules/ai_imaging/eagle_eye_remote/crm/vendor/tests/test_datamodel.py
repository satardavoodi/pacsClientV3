"""Picking the right FIELD for a question.

Every case here is drawn from a measured fact about the live database, because
the bug this module exists for was not a coding mistake — it was a confident
guess about what a field meant. `scripts/_probe_datamodel*.py` produced the
numbers quoted in the docstrings.

The one that matters most: a filter value this database has no such thing as
must REFUSE. It used to build a filter that matched nothing, and "no such
modality" then read exactly like "no such patients".
"""

from __future__ import annotations

import pytest

from reception_crm.local import datamodel as dm

_MEASURED_MODALITIES = (
    dm.Modality("1", "CT Scan", "سی تی اسکن", "CT", False),
    dm.Modality("2", "MRI", "ام آر آی", "MR", False),
    dm.Modality("3", "Sonography", "سونوگرافی", "US", False),
    dm.Modality("4", "Radiology", "رادیولوژی", "DX", False),
    dm.Modality("5", "Bone Density", "سنجش تراکم استخوان", "BD", False),
    dm.Modality("9", "Mammography", "ماموگرافی", "Mammography", True),
    dm.Modality("14", "تخصصی هیسترو", "تخصصی هیسترو", "تخصصی هیسترو", True),
)


@pytest.fixture(autouse=True)
def _measured_catalog(monkeypatch):
    """Use the measured snapshot rather than whatever database is reachable.

    The real loader reads the vendor's `Modality` collection, which is the
    point of it — but a test that needs a live clinical database is a test that
    does not run.
    """
    monkeypatch.setattr(
        dm, "_cache",
        dm._Cache(at=float("inf"),
                  modalities={m.code: m for m in _MEASURED_MODALITIES},
                  services=[
                      {"_id": "36", "Service": "ماموگرافی دو طرفه", "Modality": "9"},
                      {"_id": "700195", "Service": "ماموگرافی دو طرفه (روی4 فیلم مخصوص ماموگرافی)",
                       "Modality": "4"},
                      {"_id": "704200", "Service": "MRM ( MRماموگرافی- دو طرفه )", "Modality": "2"},
                      {"_id": "1", "Service": "سونوگرافی کامل شکم و لگن", "Modality": "3"},
                      {"_id": "2", "Service": "ام آر آي ستون فقرات كمري بدون كنتراست ", "Modality": "2"},
                      {"_id": "3", "Service": "MRI کانال spinal و محتویات ان ناحیه لومبر بدون کنتراست", "Modality": "2"},
                      {"_id": "4", "Service": "MRI ناحیه لومبار با و بدون ماده حاجب", "Modality": "2"},
                  ]),
    )


# --------------------------------------------------------------------------- #
# The defect, stated as a test
# --------------------------------------------------------------------------- #
def test_filtering_on_mammography_as_a_modality_refuses():
    """The whole bug in one assertion.

    `modality_filter("mammography")` used to return
    `{"$or": [{"modality": "mammography"}, ...]}` — zero documents, reported as
    "no BI-RADS 3 mammography cases in five months". There were 418 mammography
    receptions and 15 with BI-RADS 3.

    Note what it does NOT do: call mammography unknown. Modality 9 really is
    named Mammography. It is disabled, and saying *that* is the honest answer.
    """
    with pytest.raises(dm.DisabledValue) as caught:
        dm.modality_filter("mammography")

    error = caught.value
    assert error.meaning == "modality"
    assert error.code == "MODALITY_DISABLED"
    # The refusal must carry what DOES exist, or the answer cannot say it —
    # and only the ACTIVE ones, since suggesting another dead end is no help.
    assert any("Sonography" in k for k in error.known)
    assert not any("Mammography" in k for k in error.known)


def test_the_mammography_refusal_says_where_to_look_instead():
    """A refusal that does not point anywhere is a dead end for the reader."""
    with pytest.raises(dm.DisabledValue) as caught:
        dm.modality_filter("ماموگرافی")
    assert "خدمت" in caught.value.hint_fa


def test_a_modality_that_really_does_not_exist_is_still_unknown():
    """The two refusals are different facts and must stay distinguishable."""
    with pytest.raises(dm.UnknownValue):
        dm.modality_filter("PET")
    # Both are catchable as one thing at the call sites that only need to
    # report them.
    with pytest.raises(dm.FilterValueProblem):
        dm.modality_filter("PET")
    with pytest.raises(dm.FilterValueProblem):
        dm.modality_filter("mammography")


def test_a_known_modality_still_matches_both_storage_shapes():
    """48 of 400 sampled receptions embed the whole Modality document."""
    assert dm.modality_filter("MRI") == {"$or": [{"modality": "2"}, {"modality._id": "2"}]}
    assert dm.modality_filter("ام آر آی") == dm.modality_filter("2")
    assert dm.modality_filter("MR") == dm.modality_filter("MRI")


def test_bone_density_resolves_now_that_the_map_is_not_hardcoded():
    """Code 5 is ACTIVE and was missing from the old four-entry map, so a bone
    density question would have failed exactly as mammography did."""
    assert dm.resolve_modality("Bone Density").code == "5"
    assert dm.resolve_modality("سنجش تراکم استخوان").code == "5"


def test_a_disabled_modality_resolves_but_says_it_is_disabled():
    """Code 9 exists and is switched off. Hiding it would be a second kind of
    lie: the honest answer is "that modality exists but nothing uses it"."""
    mammography = dm.resolve_modality("Mammography")
    assert mammography.code == "9"
    assert mammography.disabled is True


# --------------------------------------------------------------------------- #
# Spelling — the thing that halves a count without anyone noticing
# --------------------------------------------------------------------------- #
def test_arabic_and_persian_letter_forms_fold_together():
    """«سونوگرافی کامل شکم و لگن» (294 receptions) and «سونوگرافي کامل شکم و لگن»
    (221) are ONE service spelled two ways."""
    assert dm.fold("سونوگرافي") == dm.fold("سونوگرافی")
    assert dm.fold("رادیولوژي") == dm.fold("رادیولوژی")
    assert dm.fold("ماموگرافي پستان") == dm.fold("ماموگرافی پستان")


def test_folding_normalises_persian_digits():
    assert dm.fold("۳") == "3"


def test_a_service_regex_matches_either_spelling():
    import re

    pattern = re.compile(dm.fold_regex("ماموگرافی"), re.IGNORECASE)
    assert pattern.search("ماموگرافی دو طرفه")
    assert pattern.search("ماموگرافي پستان دوطرفه")   # Arabic yeh, as stored
    assert not pattern.search("سونوگرافی پستان")


# --------------------------------------------------------------------------- #
# Service is the field mammography actually lives in
# --------------------------------------------------------------------------- #
def test_service_filter_is_a_substring_match_not_an_equality():
    """519 catalogued services, 432 distinct names used in one month. Somebody
    asking for «ماموگرافی» means all ten mammography services."""
    built = dm.service_filter("ماموگرافی")
    assert "services.Service" in built
    assert built["services.Service"]["$options"] == "i"


def test_matching_services_names_what_a_count_counted():
    """A count whose definition is invisible is a count nobody can check."""
    matched = dm.matching_services("ماموگرافی")
    assert "ماموگرافی دو طرفه" in matched
    assert any("MRM" in name for name in matched), "MR mammography is mammography too"
    assert not any("سونوگرافی" in name for name in matched)


def test_lumbar_service_filter_expands_the_center_aliases():
    """The production defect: a raw «کمر» regex matched 22 instead of 97."""
    import re

    built = dm.service_filter("کمر")
    alternatives = built["$or"]
    patterns = [
        re.compile(item["services.Service"]["$regex"], re.IGNORECASE)
        for item in alternatives
    ]

    names = (
        "ام آر آي ستون فقرات كمري بدون كنتراست ",
        "MRI کانال spinal و محتویات ان ناحیه لومبر بدون کنتراست",
        "MRI ناحیه لومبار با و بدون ماده حاجب",
    )
    assert all(any(pattern.search(name) for pattern in patterns) for name in names)
    assert not any(pattern.search("MRI مغز بدون کنتراست") for pattern in patterns)


def test_lumbar_resolution_names_catalogue_and_expansion():
    resolution = dm.service_resolution("lumbar")
    assert resolution["canonicalConcept"] == "lumbar_spine"
    assert "کمر" in resolution["expandedTerms"]
    assert any("كمري" in name for name in resolution["matchedCatalogServices"])
    assert any("لومبر" in name for name in resolution["matchedCatalogServices"])


def test_service_resolution_falls_back_to_the_bundled_center_catalog(monkeypatch):
    """A transient catalogue outage must not erase explanation metadata."""
    monkeypatch.setattr(
        dm,
        "_cache",
        dm._Cache(
            at=float("inf"),
            modalities={m.code: m for m in _MEASURED_MODALITIES},
            services=[],
        ),
    )

    resolution = dm.service_resolution("کمر")

    assert resolution["canonicalConcept"] == "lumbar_spine"
    assert any("لومبر" in name for name in resolution["matchedCatalogServices"])
    assert any("لومبار" in name for name in resolution["matchedCatalogServices"])


def test_service_resolution_catalogue_provenance_honours_modality(monkeypatch):
    """MRI cohort metadata must not list CT or X-ray lumbar services."""
    monkeypatch.setattr(
        dm,
        "_cache",
        dm._Cache(
            at=float("inf"),
            modalities={m.code: m for m in _MEASURED_MODALITIES},
            services=[],
        ),
    )

    resolution = dm.service_resolution("کمر", modality="MRI")

    assert resolution["matchedCatalogServices"]
    assert all(
        row["Modality"] == "2"
        for row in dm.service_catalog()
        if row["Service"] in resolution["matchedCatalogServices"]
    )


def test_mammography_services_span_more_than_one_modality():
    """The reason a modality filter can never answer this question: the ten
    mammography services sit under modality 9, 4 AND 2."""
    catalogue = {row["Service"]: row["Modality"] for row in dm.service_catalog()}
    mammography = {name: code for name, code in catalogue.items() if "ماموگراف" in dm.fold(name)}
    assert len(set(mammography.values())) > 1, mammography


# --------------------------------------------------------------------------- #
# Insurance: label only what the vendor names
# --------------------------------------------------------------------------- #
def test_named_insurance_codes_resolve_from_either_side():
    assert dm.insurance_filter("4") == {"insuranceType": "4"}
    assert dm.insurance_filter("تامین اجتماعی") == {"insuranceType": "4"}


def test_an_unnamed_insurance_code_still_filters():
    """Codes 0, 1 and 3 are in use but have no row in `InsuranceSetting`. They
    are real stored values, so they filter — they just get no label."""
    assert dm.insurance_filter("1") == {"insuranceType": "1"}


def test_an_insurance_NAME_that_does_not_exist_refuses():
    """Rather than inventing "1 = آزاد". A guessed label on a financial answer
    is worse than no label."""
    with pytest.raises(dm.UnknownValue):
        dm.insurance_filter("بیمهٔ ناموجود")


# --------------------------------------------------------------------------- #
# The rest of the model
# --------------------------------------------------------------------------- #
def test_report_status_refuses_a_status_that_does_not_exist():
    assert dm.report_status_filter("completed") == {"imagingWorkflow.report.status": "completed"}
    with pytest.raises(dm.UnknownValue):
        dm.report_status_filter("done")


def test_dates_are_jalali_strings_only():
    """`Date` is a zero-padded Jalali string; `createdAt` is a real datetime and
    must never be mixed into the same filter."""
    assert dm.date_range_filter("1405/01/01", "1405/06/01") == {
        "Date": {"$gte": "1405/01/01", "$lte": "1405/06/01"}
    }
    assert dm.date_range_filter("2026-08-23", None) is None


def test_deleted_receptions_are_excluded_by_default():
    """Every index the vendor built on this collection carries the flag."""
    assert dm.LIVE_ONLY == {"deleted": {"$ne": True}}


def test_the_prompt_description_lists_the_disabled_modalities_too():
    """A planner that cannot see that modality 9 exists-but-is-empty will keep
    proposing it."""
    text = dm.describe_for_prompt()
    assert "service" in text and "modality" in text
    assert "Disabled" in text and "Mammography" in text
