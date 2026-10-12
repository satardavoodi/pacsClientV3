"""The v3 routing misses, pinned as regressions, in the owner's own words.

⚠️ The questions are read from `benchmark/questions_v3.json`, never copied here.
That file is the only place a v3 Persian question exists, and a test that
retyped one would be asserting against a paraphrase — which is how a suite comes
to pass while the thing it describes has drifted.

Eleven of these routed somewhere else before the vocabulary was corrected. The
four that still do are listed with them, as expectations rather than omissions:
a known miss that nobody has written down is indistinguishable from one nobody
noticed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reception_crm.core import scenario_router

BENCH = Path(__file__).resolve().parents[1] / "benchmark"
QUESTIONS = json.loads((BENCH / "questions_v3.json").read_text(encoding="utf-8"))
CORE = {q["id"]: q["text"] for rows in QUESTIONS["core"].values() for q in rows}


def route(qid: str) -> str:
    return scenario_router.classify(CORE[qid], chat=None).scenario


# --------------------------------------------------- availability is bookings

@pytest.mark.parametrize("qid", ["A1", "A2", "A3", "A4", "A5",
                                 "A6", "A7", "A8", "A9", "A10"])
def test_every_appointment_question_routes_to_appointment(qid):
    """Five of these lost — A2 and A3 to a modality word, A6/A7/A8 to a patient
    referent — and none was a close call the weights got wrong. The table held
    «ظرفیت خالی» and the owner says «ساعت خالی»; the phrase simply was not
    there, so `appointment` scored ZERO on A2 and the sentence went wherever
    else it had a word."""
    assert route(qid) == "appointment"


# ------------------------------------------------------ the conversation ones

@pytest.mark.parametrize("qid", ["C1", "C2", "C3", "C4", "C5",
                                 "C6", "C7", "C8", "C9", "C10"])
def test_every_conversation_question_routes_to_conversation(qid):
    assert route(qid) == "conversation"


def test_the_first_reply_question_scores_at_all():
    """⚠️ C3 scored NOTHING — not a low score, zero — and fell to General with
    no signal. «زمان پاسخ» was in the table; the sentence says «زمان اولین
    پاسخ», which is not the same contiguous span, and matching is by span."""
    match = scenario_router.classify(CORE["C3"], chat=None)
    assert match.scenario == "conversation"
    assert match.confidence > 0.5
    assert match.method == "lexical"


# ------------------------------------------------------------- the money ones

def test_a_reconciliation_question_is_financial_not_insurance():
    """F5 asks whether the two shares add up to the reception total. One «بیمه»
    sent it to `insurance` 3.5 to 3.0, and the answer that came back compared
    the shares against the SERVICE total while calling it the reception total."""
    assert route("F5") == "financial"


def test_a_change_trail_question_beats_the_patient_referent():
    """P8 asks what was deleted, cancelled or altered for a patient. It routed
    to `patient`, because the only audit-ish word in it — the bare «حذف» — is
    deliberately financial, being the word for a deleted TRANSACTION."""
    assert route("P8") == "audit"


# ------------------------------------------- known misses, recorded not hidden

@pytest.mark.parametrize("qid,goes_to,why", [
    ("F7", "financial",
     "genuinely both: which receptions were deleted, and what they were worth. "
     "The answer it produced was correct and complete."),
    ("S4", "financial",
     "«تخفیف» and «حذف» outweigh «صندوق‌دار». Its real defect was the date, not "
     "the destination — it queried 1405/06/03 for «دیروز»."),
    ("P4", "financial",
     "cold, the money words win 7 to 4. In a threaded conversation the carried "
     "patient reaches the router and it goes to `patient` at 0.58, which is the "
     "situation this question is actually asked in."),
])
def test_the_remaining_misses_are_where_we_left_them(qid, goes_to, why):
    """A known miss that nobody has written down is indistinguishable from one
    nobody noticed. If one of these starts passing, delete its row and say so —
    do not leave a test asserting the old wrong answer."""
    assert route(qid) == goes_to, why
