"""Guards for the Eagle Eye lumbar benchmark's report parser and scorer.

The bench is what tells us whether a pipeline change helped, so a parser that
silently mis-reads a report is worse than no bench at all. Every case below is
taken from a real FINAL REPORT produced on 2026-08-30.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.eagle_eye_bench import reference as reference_mod  # noqa: E402
from tools.eagle_eye_bench import scoring  # noqa: E402


REFERENCE = {
    "schema_version": "1.0.0",
    "case_id": "unit",
    "recorded_by": "unit test",
    "levels": {
        "L1-L2": {"normal": True},
        "L3-L4": {"disc": {"morphology": "bulge"}, "annular_fissure": True},
        "L4-L5": {"disc": {"morphology": "protrusion", "zone": "central"}},
        "L5-S1": {
            "disc": {"morphology": "extrusion", "zone": "paracentral",
                     "side": "right", "critical": True},
            "lateral_recess": {"side": "right", "severity": "severe", "critical": True},
            "root": {"effect": "compression", "side": "right", "root": "S1",
                     "critical": True},
        },
    },
    "endplates": [{"vertebra": "L5", "modic": "ii",
                   "accept_levels": ["L4-L5", "L5-S1"]}],
    "normal_structures": {"neural_foramen": ["L5-S1"]},
}

MISSED_REPORT = """LEVEL MAP
  L4-L5: axial frames 16-20
  L5-S1: axial frames 21-25

PATHOLOGICAL FINDINGS
  L4-L5: Disc desiccation and height loss with a broad-based central disc protrusion, producing Lee grade 1 central canal stenosis and Bartynski grade 1 bilateral lateral recess stenosis with traversing-root contact but no deviation or compression. Modic type II endplate change and marginal osteophytes.
  L5-S1: Disc desiccation with moderate height loss, generalized disc bulge, Modic type II endplate change and marginal osteophytes. Lee grade 1 bilateral neural foraminal stenosis.
"""

CAUGHT_REPORT = """LEVEL MAP
  L5-S1: axial frames 21-25

PATHOLOGICAL FINDINGS
  L5-S1: Right paracentral disc extrusion causing severe right lateral recess stenosis and compression of the traversing right S1 nerve root.
"""

INVERTED_MAP = """LEVEL MAP
  T12-L1: axial frames 21-25
  L1-L2: axial frames 16-20
  L5-S1: axial frames 1-3

PATHOLOGICAL FINDINGS
  L5-S1: Generalized disc bulge.
"""


def _finding(report_text, level):
    return scoring.parse_report(report_text).findings[level]


def test_disc_side_is_not_borrowed_from_a_consequence_in_the_same_sentence():
    """"central protrusion ... bilateral lateral recess" must not make the disc bilateral."""
    finding = _finding(MISSED_REPORT, "L4-L5")
    assert finding.morphology == "protrusion"
    assert finding.zone == "central"
    assert finding.side in ("", "central")


def test_negated_morphology_is_not_counted_as_present():
    text = "  L4-L5: Shallow generalized disc bulge; no focal herniation, migration, or extrusion.\n"
    finding = scoring.parse_level_prose("L4-L5", text)
    assert finding.morphology == "bulge"
    assert "protrusion" in finding.morphology_denied
    assert "extrusion" in finding.morphology_denied


def test_the_most_specific_zone_wins():
    finding = scoring.parse_level_prose(
        "L5-S1", "Central to left paracentral/subarticular disc protrusion.")
    assert finding.zone == "paracentral"
    assert finding.side == "left"


def test_consequences_and_root_effect_are_extracted_with_side_and_severity():
    finding = _finding(CAUGHT_REPORT, "L5-S1")
    assert finding.morphology == "extrusion"
    assert finding.side == "right"
    assert finding.consequences["lateral_recess"]["side"] == "right"
    assert finding.consequences["lateral_recess"]["severity"] == "severe"
    assert finding.root["effect"] == "compression"
    assert finding.root["side"] == "right"
    assert finding.root["root"] == "S1"


def test_a_correct_report_scores_every_critical_claim():
    score = scoring.score_report(REFERENCE, scoring.parse_report(CAUGHT_REPORT))
    assert score.critical_misses == []
    outcomes = {c.claim_id: c.outcome for c in score.claims}
    assert outcomes["L5-S1/disc/morphology"] == scoring.HIT
    assert outcomes["L5-S1/disc/side"] == scoring.HIT
    assert outcomes["L5-S1/lateral_recess"] == scoring.HIT
    assert outcomes["L5-S1/root"] == scoring.HIT


def test_the_real_missed_report_fails_every_critical_claim():
    score = scoring.score_report(REFERENCE, scoring.parse_report(MISSED_REPORT))
    missed = {c.claim_id for c in score.critical_misses}
    assert missed == {
        "L5-S1/disc/morphology", "L5-S1/disc/side",
        "L5-S1/lateral_recess", "L5-S1/root",
    }
    outcomes = {c.claim_id: c.outcome for c in score.claims}
    # bulge where an extrusion lives is two steps down the morphology scale.
    assert outcomes["L5-S1/disc/morphology"] == scoring.UNDER
    # Foraminal stenosis at a level the reference calls normal is a false positive.
    assert any(fp["structure"] == "neural_foramen" for fp in score.false_positives)


def test_an_inverted_level_map_is_flagged_rather_than_scored_silently():
    parsed = scoring.parse_report(INVERTED_MAP)
    assert parsed.level_map_monotonic is False
    assert any("monotonic" in note for note in parsed.parse_notes)


def test_aggregate_reports_rates_not_verdicts():
    caught = scoring.score_report(REFERENCE, scoring.parse_report(CAUGHT_REPORT), "a")
    missed = scoring.score_report(REFERENCE, scoring.parse_report(MISSED_REPORT), "b")
    summary = scoring.aggregate([caught, missed, missed, missed])
    assert summary["runs"] == 4
    assert summary["critical_miss_rate"] == 0.75
    assert summary["claims"]["L5-S1/disc/morphology"]["hit_rate"] == 0.25
    assert "L5-S1/disc/morphology" in summary["unstable_claims"]


def test_reference_validation_rejects_an_unattributed_or_malformed_read():
    problems = reference_mod.validate({"schema_version": "1.0.0", "case_id": "x",
                                       "levels": {"L5-S1": {"disc": {"morphology": "slipped"}}}})
    assert any("recorded_by" in p for p in problems)
    assert any("morphology" in p for p in problems)


def test_reference_requires_accept_levels_for_an_endplate_claim():
    problems = reference_mod.validate({
        "schema_version": "1.0.0", "case_id": "x", "recorded_by": "unit",
        "levels": {"L5-S1": {"normal": True}},
        "endplates": [{"vertebra": "L5", "modic": "ii"}],
    })
    assert any("accept_levels" in p for p in problems)


def test_critical_claims_are_derived_from_the_reference():
    assert set(reference_mod.critical_claims(REFERENCE)) == {
        "L5-S1/disc/morphology", "L5-S1/lateral_recess", "L5-S1/root",
    }


@pytest.mark.parametrize("text,effect", [
    ("Contact, but no deviation, of the traversing right L4 root.", "contact"),
    ("Contact but no compression of the traversing right L4 root.", "contact"),
    ("No compression, but contact of the traversing right L4 root.", "contact"),
    ("The right L4 root is contacted without deviation or compression.", "contact"),
    ("The right L4 root is deviated but not compressed.", "deviation"),
    ("Compression is absent; contact of the right L4 root is present.", "contact"),
    ("Contact of the right L4 root. No compression or deviation.", "contact"),
    ("No foraminal stenosis, with contact of the right L4 root.", "contact"),
    ("Compression of the right L4 root without contact of the left L4 root.", "compression"),
])
def test_root_effect_negation_is_attribute_scoped(text, effect):
    finding = scoring.parse_level_prose("L3-L4", text)
    assert finding.root["effect"] == effect
    assert finding.root["side"] == "right"
    assert finding.root["root"] == "L4"


@pytest.mark.parametrize("text", [
    "No contact, deviation or compression of the right L4 root.",
    "Contact of the right L4 root is absent.",
    "The right L4 root is not compressed.",
    "Compression fracture of L3; the right L4 root is normal.",
])
def test_root_effect_negation_does_not_create_a_positive(text):
    finding = scoring.parse_level_prose("L3-L4", text)
    assert not finding.root or finding.root["effect"] == "none"


def test_root_contact_with_negated_deviation_scores_under_not_miss():
    report = scoring.parse_report(
        "PATHOLOGICAL FINDINGS\n"
        "  L3-L4: Contact, but no deviation, of the traversing right L4 root.\n"
    )
    reference = {"case_id": "synthetic-root", "levels": {
        "L3-L4": {"root": {"root": "L4", "side": "right", "effect": "compression"}}
    }}
    score = scoring.score_report(reference, report)
    claim = next(c for c in score.claims if c.kind == "root")
    assert claim.outcome == scoring.UNDER
    assert claim.observed["effect"] == "contact"
    assert score.as_dict()["scorer_version"] == "1.1.0"
    assert claim.observed["effect_assertions"] == {
        "contact": "present", "deviation": "absent", "compression": "unmentioned",
    }
