"""Guard: the other two region-specific spans in the CT prompt are gated too.

The region normal-findings blocks were the obvious one. Two more were hiding in
MODALITY LOGIC and are sent whole on every CT study:

  GROUPING VOCABULARY   eight region heading-sets — and the prompt instructs the model
                        to use "the organ/region groupings the MODALITY RULES below
                        already name for this study — do not invent a different
                        vocabulary". On a knee CT it names chest, abdomen and brain.
  PERSIAN LEXICON       sixteen dictation terms. "Appendicitis" and "Concha bullosa"
                        are not useful on a temporal bone study.

Same contract as the region blocks: byte-for-byte reassembly, a drift self-check, and
every uncertainty leaving the span whole.
"""

import ast
import io
import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind.session_metadata import REGION_KEYS          # noqa: E402
from modules.EchoMind.viewer_chat import turbo_prompt as tp        # noqa: E402
from modules.EchoMind.viewer_chat import turbo_regions as tr       # noqa: E402
from modules.EchoMind.viewer_chat import turbo_regions_extra as tx  # noqa: E402


@pytest.fixture(autouse=True)
def _v2_off(monkeypatch):
    """This file tests the NARROWING path, which only runs when the template is off.

    The template became the default on 2026-08-09; before that these tests got the
    narrowing path for free. Pinning it here keeps them testing what they were written
    to test, rather than silently becoming template tests.
    """
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "0")

@pytest.fixture(scope="module")
def base():
    return tp.build_turbo_system_prompt("CT", "")


def _span(prompt, start, end):
    i = prompt.find(start)
    j = prompt.find(end, i + 1)
    return prompt[i:j]


# ── 1. both extractions are lossless ─────────────────────────────────────────

def test_the_grouping_vocabulary_reproduces_byte_for_byte(base):
    assert _span(base, "• GROUPING VOCABULARY (CT)", "• Exclude any anatomical") \
        == tr.gv_full(), "re-run tools/dev/regen_turbo_regions.py"


def test_the_lexicon_reproduces_byte_for_byte(base):
    assert _span(base, "* Recognise Persian", "━") == tr.lex_full(), \
        "re-run tools/dev/regen_turbo_regions.py"


def test_every_grouping_entry_and_lexicon_term_is_mapped():
    """An unmapped entry can never be selected — dead content that still looks present."""
    for n, _t in tr.GV_ITEMS:
        assert n in tr.GV_REGION_MAP, f"grouping entry {n!r} maps to no region"
    for n, _t in tr.LEX_ITEMS:
        assert n in tr.LEX_REGION_MAP or n in tr.LEX_ALWAYS, \
            f"lexicon term {n!r} maps to no region and is not always-on"


def test_the_mappings_use_canonical_region_keys():
    for src in (tr.GV_REGION_MAP, tr.LEX_REGION_MAP, tx.EXTRA_GV_REGION_MAP):
        for key, regions in src.items():
            targets = regions if src is not tx.EXTRA_GV_REGION_MAP else [key]
            for r in targets:
                assert r in REGION_KEYS, f"{key} -> {r!r} is not a canonical region"


# ── 2. narrowing keeps what belongs and drops what does not ─────────────────

def test_grouping_headings_follow_the_regions():
    g = tp.build_turbo_system_prompt("CT", "", profile={"regions": ["chest", "abdomen"]})
    assert "– Chest: Lungs" in g and "– Abdomen: Liver" in g
    for gone in ("– Brain: Cerebral", "– MSK: Bones", "– Pelvis: Urinary",
                 "– Neck: Pharynx", "– Paranasal sinuses:"):
        assert gone not in g, f"{gone} survived a chest/abdomen study"


def test_the_lexicon_follows_the_regions():
    g = tp.build_turbo_system_prompt("CT", "", profile={"regions": ["chest", "abdomen"]})
    assert "Ground-glass" in g and "Appendicitis" in g
    assert "Concha bullosa" not in g
    assert "Tenosynovitis" not in g


def test_the_always_on_terms_are_never_dropped():
    """Hyperdense/Hypodense and Lymphadenopathy are general CT vocabulary, not anatomy."""
    for region in ("knee", "temporal_bone", "brain", "chest"):
        g = tp.build_turbo_system_prompt("CT", "", profile={"regions": [region]})
        for term in tr.LEX_ALWAYS:
            assert term in g, f"{term} was dropped for a {region} study"


def test_the_new_regions_have_grouping_headings():
    """The inconsistency this fixed: three normal-findings blocks were added without
    grouping entries, so the model was handed a structure list and told to head it
    with a vocabulary that did not cover it."""
    for region, heading in (("temporal_bone", "– Temporal bone:"),
                            ("orbit", "– Orbit: Globes"),
                            ("dental_maxillofacial", "– Maxillofacial:")):
        g = tp.build_turbo_system_prompt("CT", "", profile={"regions": [region]})
        assert heading in g, f"{region} has a block but no grouping heading"


def test_the_line_after_a_narrowed_span_keeps_its_indentation():
    """NOT cosmetic. The last grouping entry carries the 24 spaces that place
    `• Exclude any anatomical region…` at the right level of the outline; dropping that
    entry without preserving them puts the next rule at column 0."""
    g = tp.build_turbo_system_prompt("CT", "", profile={"regions": ["chest"]})
    line = next(l for l in g.split("\n") if "Exclude any anatomical" in l)
    assert line.startswith(" " * 24), f"indent lost: {line[:40]!r}"


def test_gating_the_extra_spans_saves_more_than_the_blocks_alone(base):
    g = tp.build_turbo_system_prompt("CT", "", profile={"regions": ["chest", "abdomen"]})
    assert len(g) < len(base) * 0.70


# ── 3. the safety posture is unchanged ───────────────────────────────────────

@pytest.mark.parametrize("profile", [None, {}, {"regions": []}, {"regions": ["zzz"]}])
def test_uncertainty_leaves_every_span_whole(base, profile):
    assert tp.build_turbo_system_prompt("CT", "", profile=profile) == base


def test_a_region_with_no_grouping_entry_keeps_the_whole_vocabulary():
    """`gv_for` returns everything when nothing matches — a model told to use headings
    and given none would invent its own."""
    assert tr.gv_for(["obstetric"]) == tr.gv_full()
    assert tr.lex_for(["obstetric"]) == tr.lex_full()


def test_drift_leaves_the_span_alone(monkeypatch, base):
    monkeypatch.setattr(tr, "gv_full", lambda: "not what the prompt says")
    g = tp.build_turbo_system_prompt("CT", "", profile={"regions": ["chest"]})
    assert "– Brain: Cerebral" in g, (
        "the grouping vocabulary was narrowed despite drifting from the library"
    )


def test_the_shared_rules_survive_all_three_narrowings():
    g = tp.build_turbo_system_prompt("CT", "", profile={"regions": ["knee"]})
    for phrase in ("SOURCE FIDELITY", "OUTPUT FORMAT (STRICT)",
                   "NORMAL FINDINGS CONSTRUCTION", "REPORT FEATURES, NOT VERDICTS",
                   "GROUPING VOCABULARY", "Recognise Persian",
                   "Exclude any anatomical", "MODALITY LOGIC"):
        assert phrase in g, f"narrowing removed {phrase!r}"
