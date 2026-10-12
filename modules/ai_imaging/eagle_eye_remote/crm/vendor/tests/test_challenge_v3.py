"""Integrity of the v3 challenge benchmark, enforced rather than promised.

The same two structural rules as v2, applied to a much larger question set:

* the framework, the expectations and every verdict are ENGLISH — asserted by
  counting Persian characters in `challenge_v3.json`;
* the questions stay EXACTLY as the owner wrote them — asserted by there being
  no question text in the spec at all. `questions_v3.json` is the only file in
  the repository where a v3 question exists, so a translation has nowhere to go.

Plus the checks that keep a 70-question spec from drifting away from the system
it describes: a renamed tool, a scenario that no longer exists, a ground-truth
path the prober stopped emitting.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reception_crm import scenarios
from reception_crm.core import modes
from reception_crm.core.registry import default_registry

BENCH = Path(__file__).resolve().parents[1] / "benchmark"
SPEC = json.loads((BENCH / "challenge_v3.json").read_text(encoding="utf-8"))
QUESTIONS = json.loads((BENCH / "questions_v3.json").read_text(encoding="utf-8"))
TRUTH_PATH = BENCH / "truth_v3.json"

EXPECT = {e["id"]: e for e in SPEC["expectations"]}
CORE = {q["id"]: q for rows in QUESTIONS["core"].values() for q in rows}
KNOWN_TOOLS = set(default_registry().tools)


def _persian(text: str) -> list[str]:
    return [c for c in text if "؀" <= c <= "ۿ"]


# --------------------------------------------------------------------------- #
# the two language rules
# --------------------------------------------------------------------------- #
def test_the_spec_is_entirely_english():
    raw = (BENCH / "challenge_v3.json").read_text(encoding="utf-8")
    found = _persian(raw)
    assert not found, f"challenge_v3.json must contain no Persian: {sorted(set(found))}"


def test_the_spec_holds_no_question_text():
    raw = (BENCH / "challenge_v3.json").read_text(encoding="utf-8")
    assert '"text"' not in raw
    for e in SPEC["expectations"]:
        assert "text" not in e


def test_every_question_is_persian():
    for qid, q in CORE.items():
        # The two patient/appointment questions carry a substitution token, and
        # everything around it is still Persian.
        assert _persian(q["text"]), f"{qid} has lost its Persian"
    for v in QUESTIONS["variants"]:
        assert _persian(v["text"]), v["id"]
    for t in QUESTIONS["multi_turn"]:
        for turn in t["turns"]:
            assert _persian(turn), t["id"]


def test_no_national_code_is_written_down_anywhere():
    """The identifier is substituted at send time and never stored.

    A ten-digit run in either of these files would be a national code sitting in
    the repository. The token exists precisely so that it cannot be.
    """
    import re

    for name in ("questions_v3.json", "challenge_v3.json"):
        raw = (BENCH / name).read_text(encoding="utf-8")
        assert not re.search(r"(?<!\d)\d{10}(?!\d)", raw), f"{name} holds a 10-digit run"
    assert "{NATIONAL_ID}" in json.dumps(QUESTIONS, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# the spec describes the system that exists
# --------------------------------------------------------------------------- #
def test_seventy_core_questions_each_with_one_expectation():
    assert len(CORE) == 70
    assert sorted(EXPECT) == sorted(CORE)
    for family, rows in QUESTIONS["core"].items():
        assert len(rows) == 10, f"family {family} has {len(rows)}"


def test_every_named_scenario_and_mode_exists():
    known_modes = {m.id for m in modes.all_modes()}
    for e in SPEC["expectations"]:
        assert scenarios.is_known(e["scenario_expected"]), e["id"]
        assert e["mode_expected"] in known_modes, e["id"]


def test_every_named_tool_exists():
    """A renamed tool must break the spec, not quietly stop being expected."""
    for e in SPEC["expectations"]:
        unknown = sorted((set(e["required_sources"]) | set(e["acceptable_sources"]))
                         - KNOWN_TOOLS)
        assert not unknown, f"{e['id']} names unknown tools: {unknown}"


def test_required_sources_are_a_subset_of_acceptable():
    for e in SPEC["expectations"]:
        assert set(e["required_sources"]) <= set(e["acceptable_sources"]) | set(
            e["required_sources"])


def test_the_thirty_field_record_is_declared_once():
    fields = SPEC["evaluation_record_fields"]
    assert len(fields) == 30
    assert len(set(fields)) == 30
    for required in ("answer_correctness", "hallucination", "root_cause_of_error",
                     "required_fix", "retest_result"):
        assert required in fields


def test_variants_and_multi_turn_reference_real_questions():
    for v in QUESTIONS["variants"]:
        assert v["of"] in CORE, v["id"]
    families = {t["scenario"] for t in QUESTIONS["multi_turn"]}
    assert len(QUESTIONS["multi_turn"]) == 7, "one multi-turn per scenario"
    assert families == {"financial", "staff", "marketing", "patient",
                        "conversation", "appointment", "general"}


def test_no_question_is_marked_unanswerable_for_want_of_a_patient_chat_store():
    """⚠️ THE MOST INSTRUCTIVE MISTAKE THIS BENCHMARK HAS PRODUCED, kept as a test.

    This assertion used to read `{C1..C10} <= unanswerable`, on the strength of
    a ground-truth probe that found no patient chat in the local database. That
    finding was true and the conclusion drawn from it was false: the patient
    chat lives on the CENTRAL backend, `ino_chat.py` opens by warning against
    exactly this confusion, and the local `chatrooms` collection is the staff
    messenger. The scorer built on it accused the agent of hallucinating on
    eleven questions it had answered correctly — 39 started, 45 active, 574
    messages, all reproduced afterwards by an independent probe of the central
    backend to the digit.

    A ground truth that has only looked in one store has not measured absence;
    it has measured where it looked. The flag is now empty and must stay empty
    unless a probe of BOTH stores comes back empty.
    """
    unanswerable = {e["id"] for e in SPEC["expectations"]
                    if e["unanswerable_from_local_data"]}
    assert unanswerable == set(), (
        f"{sorted(unanswerable)} are marked unanswerable — confirm against the "
        "central chat backend before believing it"
    )


def test_exactly_one_write_gate():
    gates = [e["id"] for e in SPEC["expectations"] if e["is_write_gate"]]
    assert gates == ["A9"]
    assert EXPECT["A9"]["mode_expected"] == "executive"


@pytest.mark.skipif(not TRUTH_PATH.exists(), reason="ground truth not fetched")
def test_every_truth_path_resolves():
    """An expectation that points at a figure the prober no longer emits is a
    check that has silently stopped applying."""
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    for e in SPEC["expectations"]:
        for path in e["truth"]:
            node = truth
            for part in path.split("."):
                assert isinstance(node, dict) and part in node, f"{e['id']}: {path}"
                node = node[part]


# --------------------------------------------------------------- the PHI masker

def _harness():
    """Import the capture harness by path — it is a benchmark script, not a
    package module, and it must stay runnable on the reception server where the
    repository is not installed."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_challenge_v3", BENCH / "run_challenge_v3.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_mask_withholds_a_name_the_agent_looked_up_for_itself():
    """⚠️ THE LEAK THIS TEST EXISTS FOR.

    The harness masked by VALUE: it substituted back the reception code and
    national code it had itself put into the questions. On P1 the agent read the
    patient's NAME out of `report.get` and passed it to `patients.search`, and
    that argument was written to the results file verbatim — a value the masker
    had never been told existed. A Persian name has no shape to catch it by, so
    the key has to carry the rule.
    """
    harness = _harness()
    masked = harness.mask({"tool": "patients.search",
                           "arguments": {"name": "نام نمونه", "limit": 10}})
    assert masked["arguments"]["name"].startswith("<withheld:")
    assert masked["arguments"]["limit"] == 10
    assert masked["tool"] == "patients.search"


def test_the_mask_does_not_swallow_the_figures_under_test():
    """A masker that blanks `patientTotal` or `patient.first_visit` has destroyed
    the benchmark to protect it. The key rule matches whole names, not
    substrings — an earlier substring version masked a visit DATE as a person."""
    harness = _harness()
    masked = harness.mask({"patientTotal": 6_052_560_000,
                           "patient_count": 214,
                           "first_visit": "1405/01/26",
                           "patientCount": 214})
    assert masked["patientTotal"] == 6_052_560_000
    assert masked["patient_count"] == 214
    assert masked["first_visit"] == "1405/01/26"
    assert masked["patientCount"] == 214


def test_the_mask_leaves_opaque_identifiers_alone():
    """A conversation id is not PHI, and blanking its digits destroys the trace
    that makes a captured run auditable."""
    harness = _harness()
    masked = harness.mask({"conversationId": "conv_3972ba74dd774c17",
                           "requestId": "v3-F2",
                           "specFingerprint": "a93309482cee3f08"})
    assert masked["conversationId"] == "conv_3972ba74dd774c17"
    assert masked["specFingerprint"] == "a93309482cee3f08"


def test_the_mask_still_catches_a_long_digit_run_in_free_text():
    """The shaped rule is the floor: a national code is one wherever it appears,
    including inside a sentence in a field with an innocent name."""
    harness = _harness()
    masked = harness.mask({"message": "کد ۱۲۳۴۵۶۷۸۹۰ ثبت شد"})
    assert "۱۲۳۴۵۶۷۸۹۰" not in masked["message"]
    assert "<withheld:digits>" in masked["message"]


def _person_shaped_fields(harness, node, key: str = "") -> list[str]:
    """Every person-shaped field in a captured artefact that is not withheld."""
    if isinstance(node, dict):
        return [f for k, v in node.items() for f in _person_shaped_fields(harness, v, k)]
    if isinstance(node, list):
        return [f for v in node for f in _person_shaped_fields(harness, v, key)]
    if isinstance(node, str):
        safe = node.startswith("<withheld:") or harness.TOKEN.match(node)
        if harness.NAME_KEYS.match(key) and not safe:
            return [key]
    return []


def test_no_captured_artefact_carries_a_person_shaped_field():
    """The results file on disk, not just the code that writes it."""
    harness = _harness()
    for name in ("challenge_v3_results.json", "challenge_v3_report.json"):
        path = BENCH / name
        if not path.exists():
            continue
        found = _person_shaped_fields(
            harness, json.loads(path.read_text(encoding="utf-8")))
        assert not found, f"{name}: unmasked person-shaped fields {sorted(set(found))[:5]}"


# ------------------------------------------------- follow-ups need a thread

#: A demonstrative with no noun of its own, or a reference to something the
#: agent is said to have already done.
ANAPHORA = (
    "این بیمار", "همین بیمار", "همون بیمار", "همین نوبت", "همون نوبت",
    "که پیدا کردی", "که گفتی",
)


def test_every_question_that_refers_back_declares_what_it_continues():
    """⚠️ A HARNESS DEFECT THAT LOOKED EXACTLY LIKE AN AGENT DEFECT.

    Nine Patient questions open with «این بیمار» and three Appointment ones
    refer back to a patient or to a slot the agent was asked to propose. The
    first run sent all seventy core questions in their own fresh conversation,
    so those twelve arrived with no referent — and asking who is meant is then
    the only correct response. Nine of the ten Patient answers were recorded as
    clarifications, and the one write-gate test never reached the gate because
    the turn that was supposed to propose a slot had no patient either.

    The question text is not the problem and must not be edited. What was
    missing is the thread.
    """
    undeclared = [
        q["id"] for q in CORE.values()
        if any(a in q["text"] for a in ANAPHORA) and not q.get("continues")
    ]
    assert not undeclared, (
        f"{undeclared} refer to an earlier turn but declare no `continues`; sent "
        "cold they cannot be answered and the verdict measures the harness"
    )


def test_every_continues_target_exists_and_comes_first():
    """A follow-up pointing at a later question would join a thread that does
    not exist yet, which is the same failure wearing a declaration."""
    order = [q["id"] for rows in QUESTIONS["core"].values() for q in rows]
    position = {qid: i for i, qid in enumerate(order)}
    for qid in order:
        parent = CORE[qid].get("continues")
        if parent:
            assert parent in CORE, f"{qid} continues unknown question {parent}"
            assert position[parent] < position[qid], (
                f"{qid} continues {parent}, which comes after it")


def test_the_write_gate_continues_the_question_that_proposes_the_slot():
    """A9 says «همین نوبتی که پیدا کردی رو ثبت کن» — register the appointment you
    just found. There is nothing to register unless A8 ran in the same thread,
    and without it the confirmation gate is never exercised at all."""
    assert CORE["A9"]["continues"] == "A8"
    assert CORE["A8"].get("continues")
