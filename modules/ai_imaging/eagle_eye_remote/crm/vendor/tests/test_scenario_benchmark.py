"""The scenario benchmark's own integrity, enforced rather than promised.

Two rules the owner set are structural here, not conventions someone has to
remember:

* the framework, the instructions and every expectation are ENGLISH -- so
  `scenario_v2.json` is asserted to contain no Persian character at all;
* the questions stay EXACTLY as the owner wrote them and are never translated
  -- so `scenario_v2.json` is asserted to contain no question text either. It
  refers to questions by id, `persian_v1.json` is the only place a question
  exists, and there is therefore nothing for a translation to be written into.

The rest is the ordinary defence against a spec that drifts away from the code
it describes: a renamed tool, a scenario that no longer exists, a probe id
nothing points at. Every one of those failures is silent in a JSON file and
loud here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reception_crm import scenarios
from reception_crm.core import modes, scenario_router
from reception_crm.core.registry import default_registry
from reception_crm.lexicon import center

BENCH = Path(__file__).resolve().parents[1] / "benchmark"
SPEC = json.loads((BENCH / "scenario_v2.json").read_text(encoding="utf-8"))
PROBES = json.loads((BENCH / "probes_v2.json").read_text(encoding="utf-8"))
QUESTIONS = json.loads((BENCH / "persian_v1.json").read_text(encoding="utf-8"))

EXPECTATIONS = SPEC["expectations"]
GROUPS = {k: v for k, v in SPEC["source_groups"].items() if not k.startswith("_")}
KNOWN_TOOLS = set(default_registry().tools)


def _persian(text: str) -> list[str]:
    return [c for c in text if "؀" <= c <= "ۿ"]


# --------------------------------------------------------------------------- #
# the two language rules
# --------------------------------------------------------------------------- #
def test_the_spec_is_entirely_english():
    """No Persian character anywhere in the framework file.

    The owner's instruction was that the prompt structure, the instructions,
    the analysis framework and the evaluation output are all English. A single
    Persian expectation string would be the first step back towards a spec
    written half in each, which is how a translated question gets in.
    """
    raw = (BENCH / "scenario_v2.json").read_text(encoding="utf-8")
    found = _persian(raw)
    assert not found, f"scenario_v2.json must contain no Persian: found {sorted(set(found))}"


def test_the_spec_holds_no_question_text():
    """Questions live in exactly one file, so they cannot be re-typed in another."""
    raw = (BENCH / "scenario_v2.json").read_text(encoding="utf-8")
    assert '"text"' not in raw
    for expectation in EXPECTATIONS:
        assert "text" not in expectation
        assert set(expectation) & {"question_id"}, "expectations refer to questions by id"


def test_every_question_is_still_persian_and_unchanged_in_shape():
    """A translated question would be ASCII. This is the tripwire for that."""
    assert len(QUESTIONS["questions"]) == 20
    for question in QUESTIONS["questions"]:
        assert _persian(question["text"]), f"question {question['id']} has lost its Persian"


# --------------------------------------------------------------------------- #
# the spec describes the system that exists
# --------------------------------------------------------------------------- #
def test_every_question_has_exactly_one_expectation():
    ids = [e["question_id"] for e in EXPECTATIONS]
    assert sorted(ids) == sorted(q["id"] for q in QUESTIONS["questions"])
    assert len(ids) == len(set(ids))


def test_the_phases_partition_the_questions():
    """Eleven phases, twenty questions, every question in exactly one phase."""
    phases = SPEC["phases"]
    assert [p["id"] for p in phases] == list(range(1, 12))
    covered = [qid for p in phases for qid in p["question_ids"]]
    assert sorted(covered) == list(range(1, 21))
    assert len(covered) == len(set(covered))
    for expectation in EXPECTATIONS:
        owner = [p for p in phases if expectation["question_id"] in p["question_ids"]]
        assert len(owner) == 1
        assert expectation["phase"] == owner[0]["id"]


def test_the_evaluation_record_is_thirty_named_fields():
    fields = SPEC["evaluation_record_fields"]
    assert len(fields) == 30
    assert len(set(fields)) == 30
    # The two a human fills in are present, because a record that cannot carry a
    # verdict or a re-test result is a capture, not an evaluation.
    assert "error_category" in fields
    assert "retest_result" in fields
    assert "answer_verdict" in fields


def test_every_named_scenario_exists():
    for expectation in EXPECTATIONS:
        wanted = [expectation["primary_scenario_expected"]]
        wanted += expectation["primary_scenario_acceptable"]
        wanted += [s for s in expectation["secondary_scenario_acceptable"] if s is not None]
        for scenario_id in wanted:
            assert scenarios.is_known(scenario_id), scenario_id


def test_every_named_mode_exists():
    known = {m.id for m in modes.all_modes()}
    for expectation in EXPECTATIONS:
        assert expectation["mode_expected"] in known


def test_every_named_tool_exists():
    """A renamed tool must break the spec, not quietly stop being forbidden.

    A forbidden list that names a tool the registry no longer holds forbids
    nothing, and the metric that depended on it keeps reporting a clean number.
    This is the same discipline as the packaging spec that refuses to build
    without its data files.
    """
    for name, group in GROUPS.items():
        unknown = sorted(set(group) - KNOWN_TOOLS)
        assert not unknown, f"source group {name!r} names unknown tools: {unknown}"
    for expectation in EXPECTATIONS:
        for key in ("required_sources", "acceptable_sources", "forbidden_sources"):
            for entry in expectation.get(key) or []:
                if entry.startswith("@"):
                    assert entry[1:] in GROUPS, f"question {expectation['question_id']}: {entry}"
                else:
                    assert entry in KNOWN_TOOLS, f"question {expectation['question_id']}: {entry}"


def _expand(expectation: dict, key: str) -> set[str]:
    out: set[str] = set()
    for entry in expectation.get(key) or []:
        out.update(GROUPS[entry[1:]] if entry.startswith("@") else [entry])
    return out


def test_required_sources_are_never_also_forbidden():
    """The one contradiction that would make a question unscoreable."""
    for expectation in EXPECTATIONS:
        clash = _expand(expectation, "required_sources") & _expand(expectation, "forbidden_sources")
        assert not clash, f"question {expectation['question_id']} both needs and forbids {clash}"


def test_every_concept_block_points_at_a_real_probe():
    known = {c["id"] for c in PROBES["concept_probes"]["cases"]}
    seen = set()
    for expectation in EXPECTATIONS:
        concept = expectation.get("concept")
        if not concept:
            continue
        assert concept["probe_ids"], expectation["question_id"]
        for probe_id in concept["probe_ids"]:
            assert probe_id in known, probe_id
            seen.add(probe_id)
    assert seen, "section 12 requires the concept rule to be tested on questions 12-20"


def test_the_department_rule_is_tested_on_questions_twelve_to_twenty():
    """Section 12, as a check rather than a paragraph."""
    with_concept = {e["question_id"] for e in EXPECTATIONS if e.get("concept")}
    assert with_concept <= set(range(12, 21))
    # Every question that names a clinical concept carries the block. 16 and 17
    # name none -- they are the control group -- so they are the only two in the
    # range that may be without one.
    assert set(range(12, 21)) - with_concept == {16, 17}


def test_a_zero_for_want_of_a_department_is_a_failure_by_definition():
    assert "DEPARTMENT_ASSUMPTION" in SPEC["error_categories"]
    for question_id in (12, 13, 14, 15, 18, 19, 20):
        expectation = next(e for e in EXPECTATIONS if e["question_id"] == question_id)
        assert expectation["zero_is_failure"] is True


# --------------------------------------------------------------------------- #
# the probes are a live regression, not documentation
# --------------------------------------------------------------------------- #
def _routing_cases(known_gap: bool) -> list[dict]:
    return [c for c in PROBES["routing_probes"]["cases"] if bool(c.get("known_gap")) is known_gap]


@pytest.mark.parametrize("case", _routing_cases(False), ids=lambda c: c["id"])
def test_routing_probe(case):
    """Section 6. Every live question carries a strong term, so none of them is
    ever unsure; these inputs are the ones a router SHOULD be unsure about, and
    being unsure is the pass. Running them here rather than only in the scorer
    means a change to the term tables breaks the suite on the developer's
    machine instead of on the reception box six weeks later.
    """
    match = scenario_router.classify(case["text"], None, chat=None)
    wanted = case.get("expected_scenario_in") or [case["expected_scenario"]]
    assert match.scenario in wanted, f"{case['id']}: {case['why']}"
    if case.get("expected_methods"):
        assert match.method in case["expected_methods"]
    if case.get("confidence_at_most") is not None:
        assert match.confidence <= case["confidence_at_most"]
    if case.get("confidence_at_least") is not None:
        assert match.confidence >= case["confidence_at_least"]
    if case.get("secondary_required"):
        assert match.secondary


@pytest.mark.parametrize("case", _routing_cases(True), ids=lambda c: c["id"])
def test_known_routing_gap_still_open(case):
    """A documented gap is asserted to be STILL a gap.

    Marking a failure `known_gap` and then never looking again is how a
    to-do becomes a permanent feature. This test fails the day the gap closes,
    which is the day the note should be deleted and the probe promoted.
    """
    match = scenario_router.classify(case["text"], None, chat=None)
    wanted = case.get("expected_scenario_in") or [case["expected_scenario"]]
    assert match.scenario not in wanted, (
        f"{case['id']} now routes correctly -- remove `known_gap` from probes_v2.json "
        "and let this probe be a normal expectation"
    )


def _concept_cases(known_gap: bool) -> list[dict]:
    return [c for c in PROBES["concept_probes"]["cases"] if bool(c.get("known_gap")) is known_gap]


@pytest.mark.parametrize("case", _concept_cases(False), ids=lambda c: c["id"])
def test_concept_probe(case):
    """Section 12 against the centre's own configuration. No database."""
    if case["expected_level"] == "none":
        match = center.resolve_clinical_concept(case["term"])
        assert match.level == "none", f"{case['id']}: {case['why']}"
        return
    match = center.resolve_clinical_concept(case["term"])
    assert match.level == case["expected_level"], f"{case['id']}: {case['why']}"
    if case.get("expected_departments") is not None:
        assert sorted(match.departments) == sorted(case["expected_departments"])
    if case.get("expected_retired_departments") is not None:
        assert sorted(match.retired_departments) == sorted(case["expected_retired_departments"])
    if case.get("expected_min_services") is not None:
        assert len(match.services) >= case["expected_min_services"]


@pytest.mark.parametrize("case", _concept_cases(True), ids=lambda c: c["id"])
def test_known_concept_gap_still_open(case):
    match = center.resolve_clinical_concept(case["term"])
    assert match.level != case["expected_level"], (
        f"{case['id']} now resolves -- remove `known_gap` from probes_v2.json"
    )


def test_every_probe_level_is_one_the_resolver_can_return():
    allowed = set(center.LEVELS) | {"none"}
    for case in PROBES["concept_probes"]["cases"]:
        assert case["expected_level"] in allowed, case["id"]


def test_probe_ids_are_unique():
    for section in ("routing_probes", "concept_probes"):
        ids = [c["id"] for c in PROBES[section]["cases"]]
        assert len(ids) == len(set(ids)), section
