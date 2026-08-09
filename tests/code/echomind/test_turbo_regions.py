"""Guard: the CT region blocks were extracted LOSSLESSLY, and narrowing is safe.

The 19 blocks in `turbo_regions.py` are clinical content a radiologist wrote, lifted out
of the monolithic prompt by `tools/dev/regen_turbo_regions.py`. Two things have to stay
true, and the first is not negotiable:

  1. The extraction still reproduces the live prompt's region section BYTE FOR BYTE.
     If it does not, the library and the prompt have drifted and narrowing would ship
     stale clinical text.
  2. Every uncertainty resolves to "send the full prompt". Narrowing to nothing would
     delete every region's reporting rules and still look like a successful call.
"""

import ast
import io
import os
import sys
import typing

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_REPORTER = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "openai_reporter.py")

from modules.EchoMind.viewer_chat import turbo_prompt as tp          # noqa: E402
from modules.EchoMind.viewer_chat import turbo_regions as tr         # noqa: E402


@pytest.fixture(autouse=True)
def _v2_off(monkeypatch):
    """This file tests the NARROWING path, which only runs when the template is off.

    The template became the default on 2026-08-09; before that these tests got the
    narrowing path for free. Pinning it here keeps them testing what they were written
    to test, rather than silently becoming template tests.
    """
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "0")

def _shared_builder():
    src = io.open(_REPORTER, encoding="utf-8-sig").read()
    lines = src.split("\n")
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef)
                and n.name == "build_report_system_prompt")
    ns = {"_to_str": lambda x: "" if x is None else str(x),
          "Optional": typing.Optional, "Dict": dict, "Any": object}
    exec(compile("\n".join(lines[node.lineno - 1:node.end_lineno]), _REPORTER, "exec"), ns)
    return ns["build_report_system_prompt"]


@pytest.fixture(scope="module")
def base():
    return _shared_builder()("CT", "")


CAP = {"regions": ["chest", "abdomen", "pelvis"], "contrast": "with_and_without"}


# ── 1. the extraction is lossless ────────────────────────────────────────────

def test_the_library_reproduces_the_live_section_byte_for_byte(base):
    """THE test. Everything else is only safe because this holds."""
    span = tp._locate_ct_section(base)
    assert span is not None, "the region section markers moved"
    a, b = span
    assert base[a:b] == tr.full_section(), (
        "turbo_regions.py has drifted from the live prompt — re-run "
        "tools/dev/regen_turbo_regions.py once the change is deliberate"
    )


def test_all_nineteen_blocks_survived():
    assert len(tr.CT_BLOCKS) == 19
    assert len({n for n, _t in tr.CT_BLOCKS}) == 19, "a block name is duplicated"
    for name, text in tr.CT_BLOCKS:
        assert text.strip(), f"{name} is empty"
        assert name in text, f"{name}'s own heading is missing from its text"


def test_every_block_is_reachable_from_some_mapping():
    """An unreachable block is content that can never be sent — worse than deleted,
    because it still looks present."""
    reachable = {b for v in tr.REGION_TO_BLOCKS.values() for b in v}
    reachable |= {b for v in tr.COMBO_BLOCKS.values() for b in v}
    reachable |= {b for v in tr.AXIS_BLOCKS.values() for b in v}
    orphans = [n for n, _t in tr.CT_BLOCKS if n not in reachable]
    assert not orphans, f"unreachable blocks: {orphans}"


def test_the_mappings_only_name_blocks_that_exist():
    known = {n for n, _t in tr.CT_BLOCKS}
    for src in (tr.REGION_TO_BLOCKS, tr.COMBO_BLOCKS, tr.AXIS_BLOCKS):
        for key, names in src.items():
            for n in names:
                assert n in known, f"{key} maps to unknown block {n!r}"


def test_region_keys_are_canonical():
    """They have to match what the gate emits, or nothing will ever select them."""
    from modules.EchoMind.session_metadata import REGION_KEYS
    for k in tr.REGION_TO_BLOCKS:
        assert k in REGION_KEYS, f"{k!r} is not a canonical region key"
    for combo in tr.COMBO_BLOCKS:
        for k in combo:
            assert k in REGION_KEYS


# ── 2. narrowing keeps everything it should ──────────────────────────────────

#: The ONLY spans narrowing is allowed to touch. Widened on 2026-08-08 from "the
#: region section" to three spans, when the grouping vocabulary and the Persian lexicon
#: were gated too — both sit BEFORE the region section, so the original
#: "nothing before it may change" assertion started failing on a correct change.
#: Listing them explicitly is stronger than a positional check: anything outside these
#: three must be byte-identical, and the test says which three.
GATEABLE_SPANS = (
    ("• GROUPING VOCABULARY (CT)", "• Exclude any anatomical"),
    ("* Recognise Persian", "━"),
)


def _blank_gateable(prompt):
    """Replace every gateable span with a fixed marker, so what remains is the text
    narrowing must never touch."""
    span = tp._locate_ct_section(prompt)
    if span:
        a, b = span
        prompt = prompt[:a] + "<<REGION-SECTION>>" + prompt[b:]
    for start, end in GATEABLE_SPANS:
        i = prompt.find(start)
        j = prompt.find(end, i + 1) if i >= 0 else -1
        if i >= 0 and j > i:
            prompt = prompt[:i] + f"<<{start[:24]}>>" + prompt[j:]
    return prompt


def test_narrowing_changes_only_the_gateable_spans(base):
    """Source fidelity, report organisation, the output contract — none of it may move."""
    got = tp.build_turbo_system_prompt("CT", "", profile=CAP)
    assert _blank_gateable(got) == _blank_gateable(base), (
        "narrowing changed text outside the three gateable spans"
    )


def test_the_relevant_blocks_are_kept_and_the_rest_dropped():
    got = tp.build_turbo_system_prompt("CT", "", profile=CAP)
    for keep in ("CHEST CT AND HRCT", "ABDOMEN CT", "PELVIS CT", "ABDOMINOPELVIC CT"):
        assert keep in got, f"{keep} was dropped from a chest/abdomen/pelvis study"
    for drop in ("LUMBAR SPINE CT", "CORONARY CTA", "MSK CT KNEE", "NECK CT",
                 "PARANASAL SINUS CT", "BRAIN CT (NON-CONTRAST)", "MSK CT WRIST AND HAND"):
        assert drop not in got, f"{drop} survived a chest/abdomen/pelvis study"


def test_the_shared_rules_all_survive():
    got = tp.build_turbo_system_prompt("CT", "", profile=CAP)
    for phrase in ("SOURCE FIDELITY", "OUTPUT FORMAT (STRICT)", "REPORT ORGANIZATION",
                   "NORMAL FINDINGS CONSTRUCTION", "REPORT FEATURES, NOT VERDICTS",
                   "THE NORMAL-REPORT REQUEST", "GROUPING VOCABULARY"):
        assert phrase in got, f"narrowing removed {phrase!r}"


def test_it_actually_gets_smaller(base):
    got = tp.build_turbo_system_prompt("CT", "", profile=CAP)
    assert len(got) < len(base) * 0.80, (
        f"expected a real reduction, got {len(base)} -> {len(got)}"
    )


def test_a_combination_block_needs_both_regions():
    abd_only = tp.build_turbo_system_prompt("CT", "", profile={"regions": ["abdomen"]})
    assert "ABDOMINOPELVIC CT" not in abd_only
    both = tp.build_turbo_system_prompt("CT", "",
                                        profile={"regions": ["abdomen", "pelvis"]})
    assert "ABDOMINOPELVIC CT" in both


def test_contrast_refines_brain_but_only_when_it_is_certain():
    unknown = tp.build_turbo_system_prompt("CT", "", profile={"regions": ["brain"]})
    assert "BRAIN CT WITH CONTRAST" in unknown, (
        "an unknown contrast state must keep both brain blocks, not guess"
    )
    none = tp.build_turbo_system_prompt(
        "CT", "", profile={"regions": ["brain"], "contrast": "none"})
    assert "BRAIN CT WITH CONTRAST" not in none
    assert "BRAIN CT (NON-CONTRAST)" in none


# ── 3. every uncertainty sends the full prompt ───────────────────────────────

@pytest.mark.parametrize("profile", [
    None, {}, {"regions": []}, {"regions": None},
    {"regions": ["not_a_region"]}, {"regions": ["", "  "]},
])
def test_anything_unresolvable_sends_the_full_prompt(base, profile):
    assert tp.build_turbo_system_prompt("CT", "", profile=profile) == base


def test_no_other_modality_is_narrowed():
    """NARROWING is CT-only: its three spans were extracted from the CT branch and the
    drift self-check is against that extraction, so applying it elsewhere would cut
    blind. Every other modality reaches the gate by template or, for mammography, by
    prefix — never by narrowing. (This file pins the template off, so with a profile
    these all fall through to the shared builder.)"""
    for m in ("MRI", "SONOGRAPHY", "RADIOLOGY", "OBSTETRIC ULTRASOUND", ""):
        assert (tp.build_turbo_system_prompt(m, "", profile=CAP)
                == tp.build_turbo_system_prompt(m, "")), m
    # Mammography is the exception: prefix in front, shared prompt whole behind it.
    base = tp.build_turbo_system_prompt("MAMOGRAPHY", "")
    assert tp.build_turbo_system_prompt("MAMOGRAPHY", "", profile=CAP).endswith(base)


def test_drift_between_the_prompt_and_the_library_refuses_to_narrow(base, monkeypatch):
    """The failure this is really guarding: someone edits the prompt, forgets the
    library, and Turbo quietly starts sending last month's clinical text."""
    monkeypatch.setattr(tr, "full_section", lambda: "not what the prompt says")
    assert tp.build_turbo_system_prompt("CT", "", profile=CAP) == base


def test_a_selection_can_never_be_empty():
    """section_for([]) would produce a header with no regions under it."""
    for profile in ({"regions": ["not_a_region"]}, {"regions": ["xyz", "abc"]}):
        names = tp._select_ct_blocks(profile)
        assert names is None, "an unmatched profile must return None, not []"


def test_an_exception_inside_narrowing_still_returns_a_prompt(base, monkeypatch):
    monkeypatch.setattr(tp, "_locate_ct_section",
                        lambda *_a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert tp.build_turbo_system_prompt("CT", "", profile=CAP) == base


def test_the_regenerator_exists_and_verifies_itself():
    """The library is generated. If the tool is gone, the next prompt edit cannot be
    re-baselined and someone will hand-edit 19 clinical blocks instead."""
    p = os.path.join(_ROOT, "tools", "dev", "regen_turbo_regions.py")
    assert os.path.exists(p), "the regenerator was moved or deleted"
    src = io.open(p, encoding="utf-8-sig").read()
    assert "full_section() == SECTION" in src, (
        "the regenerator no longer verifies its own output round-trips"
    )
