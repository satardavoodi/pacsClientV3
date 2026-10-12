"""Department is centre policy; service is the work.

Every number asserted here was measured on the live database on 1405/06/02
(`benchmark/_dept_vs_service.py`) before any of this code existed. They are
regression anchors, not illustrations.
"""

from __future__ import annotations

import pytest

from reception_crm.lexicon import center


# --------------------------------------------------------------------------- #
# the configuration is real and was discovered, not written
# --------------------------------------------------------------------------- #
def test_the_centre_configuration_ships():
    assert center.is_available(), "center_config.json must be bundled"
    assert len(center.departments()) == 7
    assert len(center._service_index()) > 500


def test_mammography_is_a_disabled_department_here():
    """The case that started this. Code 9 exists and is switched off."""
    mammo = center.department("9")
    assert mammo is not None
    assert mammo.name_fa == "ماموگرافی"
    assert mammo.disabled is True
    assert mammo.active is False


def test_the_active_departments_are_the_five_in_use():
    active = {d.code for d in center.active_departments()}
    assert active == {"1", "2", "3", "4", "5"}


def test_a_deleted_department_survives_as_an_orphan_code():
    """Department 6 — the dental/panoramic one — was DELETED, not disabled.

    One service and two service groups still point at it. Disabled and deleted
    are different states and only one of them leaves a row you can read.
    """
    assert "6" in center.orphan_departments()
    assert center.department("6") is None


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #
def test_mammography_resolves_to_services_not_to_its_department():
    """The rule, in one assertion.

    A department filter would either under-count (department 9 is off) or
    over-count 27× (its services live in Radiology and MRI too). The resolver
    must land on `service`.
    """
    match = center.resolve_clinical_concept("ماموگرافی")
    assert match.level == "service"
    assert match.services, "mammography services exist in this catalogue"
    assert "9" in match.departments, "including some still filed under the retired department"
    assert "9" in match.retired_departments
    assert any("DISABLED" in n or "under-count" in n for n in match.notes)


def test_mammography_spans_more_than_one_department():
    """Ten services across three departments — 9 (retired), 4 (radiology) and
    2 (MRI, where MR mammography is a genuinely different examination)."""
    match = center.resolve_clinical_concept("ماموگرافی")
    assert len(match.departments) >= 3
    assert any("span" in n for n in match.notes)


def test_an_active_department_that_contains_all_its_services_wins():
    """The mirror-image bug, and it cost 29 receptions before it was caught.

    «ام آر آی» is an ACTIVE department of 73 services, 63 of which carry the
    words in their name. Preferring services whenever any matched counted **33**
    receptions on 1405/06/02 where the department counted **62** — the ten
    services not called "MRI" anything were silently dropped.

    When the centre models the concept AS a live department and nothing escapes
    it, the department is the complete set and the services are a subset.
    """
    match = center.resolve_clinical_concept("ام آر آی")
    assert match.level == "department"
    assert match.departments == ("2",)
    assert any("subset" in n for n in match.notes)


def test_ct_resolves_as_its_active_department_too():
    match = center.resolve_clinical_concept("سی تی اسکن")
    assert match.level == "department"
    assert match.departments == ("1",)


def test_the_two_directions_are_distinguished_by_whether_services_escape():
    """The whole rule in one comparison.

    Mammography: no ACTIVE department, services scattered across 2/4/9 → service.
    MRI: active department, every matching service inside it → department.
    """
    mammo = center.resolve_clinical_concept("ماموگرافی")
    mri = center.resolve_clinical_concept("ام آر آی")
    assert (mammo.level, mri.level) == ("service", "department")


def test_an_unknown_term_says_so_rather_than_guessing():
    match = center.resolve_clinical_concept("زیرآبی")
    assert match.level == "none"
    assert not match.found()


def test_lumbar_service_aliases_resolve_to_one_canonical_concept():
    """Regression: searching «کمر» omitted 75 of 97 live lumbar MRI visits.

    The omitted service names used «لومبر/لومبار» and therefore could not be
    recovered by Persian letter folding alone.
    """
    aliases = ("کمر", "کمری", "لومبر", "لومبار", "lumbar", "lumbosacral")
    matches = [center.resolve_clinical_concept(alias) for alias in aliases]

    assert {match.canonical_concept for match in matches} == {"lumbar_spine"}
    assert all(match.level == "service" for match in matches)
    assert all(any("لومبر" in name for name in match.services) for match in matches)
    assert all(any("لومبار" in name for name in match.services) for match in matches)


def test_service_concept_search_terms_are_center_configuration():
    concept = center.service_concept("LS spine")
    assert concept is not None
    assert concept.id == "lumbar_spine"
    assert "کمر" in concept.match_terms
    assert "لومبر" in concept.match_terms
    assert center.service_search_terms("unknown service") == ("unknown service",)


def test_a_short_term_is_refused():
    """Two-character particles match long descriptive catalogue names. That is
    how «رو» once became a modality."""
    assert center.resolve_clinical_concept("رو").level == "none"
    assert center.resolve_clinical_concept("تا").level == "none"


# --------------------------------------------------------------------------- #
# the filter
# --------------------------------------------------------------------------- #
def test_the_filter_is_over_services_not_over_departments():
    """Because the two give different answers — 4 versus 108."""
    match = center.resolve_clinical_concept("ماموگرافی")
    where = center.concept_filter(match)
    assert "services.Service" in where
    assert "modality" not in str(where)
    assert "$in" in where["services.Service"]


def test_the_filter_names_are_deduplicated():
    match = center.resolve_clinical_concept("ماموگرافی")
    names = center.concept_filter(match)["services.Service"]["$in"]
    assert len(names) == len(set(names))


def test_a_department_concept_filters_on_the_lines_own_department():
    """Not on `reception.modality`.

    A reception is stamped with ONE department while its lines may belong to
    several — the reception-level field answers "which department was this
    visit filed under", not "what work was done".
    """
    match = center.resolve_clinical_concept("ام آر آی")
    where = center.concept_filter(match)
    assert "services.Modality" in where
    assert "modality" not in [k for k in where if k == "modality"]


def test_a_term_matching_half_the_catalogue_is_refused():
    """A concept that matches most of the catalogue is a department, not an
    examination. Refused rather than truncated — a silently shortened `$in` is
    a confident undercount."""
    huge = center.ConceptMatch(
        concept="x", level="service",
        services=tuple(f"service {n}" for n in range(center.MAX_SERVICES_IN_FILTER + 1)),
    )
    with pytest.raises(center.ConceptTooBroad):
        center.concept_filter(huge)


def test_an_unresolvable_concept_never_produces_a_filter():
    """The lexicon's oldest rule: an unresolvable value RAISES, it never becomes
    an empty filter that quietly matches everything."""
    match = center.resolve_clinical_concept("زیرآبی")
    with pytest.raises(center.ConceptTooBroad):
        center.concept_filter(match)


# --------------------------------------------------------------------------- #
# what the reader is told
# --------------------------------------------------------------------------- #
def test_the_explanation_says_which_level_answered():
    match = center.resolve_clinical_concept("ماموگرافی")
    sentence = center.explain(match)
    assert "خدمت" in sentence
    assert sentence.endswith(".")


def test_the_centre_config_is_bundled_by_both_packaging_paths():
    """The F8 trap again, and this file is the worst one to lose.

    Without it every clinical concept falls back to the lexicon's general
    vocabulary, which resolves «ماموگرافی» to a disabled department. The server
    would start, answer, and be quietly wrong by 27× — the exact shape of the
    original packaging bug.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    spec = (root / "scripts" / "ReceptionCrmServer.spec").read_text(encoding="utf-8")
    assert "center_config.json" in pyproject
    assert "CENTER_CONFIG" in spec
    assert "refusing to build" in spec.lower()


def test_the_config_is_regenerable_and_says_so():
    """Centre-specific means it must be rebuilt per centre, not copied."""
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "build_center_config.py"
    assert script.exists(), "the generator must ship with the map it generates"
    text = script.read_text(encoding="utf-8")
    assert "never hardcode" in text.lower() or "discovered" in text.lower()
    assert "--concepts" in text, "regeneration must preserve the centre alias overlay"


def test_runtime_center_config_never_falls_back_to_another_centers_bundle(
    tmp_path, monkeypatch
):
    """A failed fresh install must be loud, not quietly RAZI-shaped."""
    missing = tmp_path / "center_config.json"
    monkeypatch.setenv(center.ENV_CENTER_CONFIG_PATH, str(missing))
    center.load_center.cache_clear()
    try:
        loaded = center.load_center()
        assert loaded["available"] is False
        assert str(missing) in loaded["reason"]
    finally:
        center.load_center.cache_clear()


def test_center_identity_mismatch_refuses_the_map(tmp_path, monkeypatch):
    path = tmp_path / "center_config.json"
    path.write_text('{"center":"OTHER","departments":[],"services":[]}', encoding="utf-8")
    monkeypatch.setenv(center.ENV_CENTER_CONFIG_PATH, str(path))
    monkeypatch.setenv("RECEPTION_HTTP_API_CENTER", "THIS CENTER")
    center.load_center.cache_clear()
    try:
        loaded = center.load_center()
        assert loaded["available"] is False
        assert "belongs to" in loaded["reason"]
        assert "run center bootstrap" in loaded["reason"]
    finally:
        center.load_center.cache_clear()


def test_the_five_levels_are_named():
    """They are related and not interchangeable, so they are named rather than
    inferred from a field name somewhere."""
    assert center.LEVELS == (
        "department", "service_group", "service", "modality", "examination",
    )
