"""Guard: mammography is gated by PREFIX, because its schema is regex-locked.

Every other modality renders the nine-slot template, whose OUTPUT slot defines the
five-key contract. Mammography returns a different shape — `Breast Composition`,
`Normal Findings {Right Breast, Left Breast}`, `Axillary Evaluation`,
`BI-RADS Category {Right Breast, Left Breast}` — with NO `Impression` and NO
`Recommendations` key, behind `SECTION 0 — REGEX-LOCKED JSON SCHEMA (HARD ENFORCEMENT)`.
Rendering the template here would emit the wrong shape and the regex would reject it.

So this file mostly guards a negative: the shared prompt must survive verbatim.
"""

import io
import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind.viewer_chat import turbo_prompt as tp                # noqa: E402
from modules.EchoMind.viewer_chat.openai_reporter import (                 # noqa: E402
    build_report_system_prompt as shared)
from modules.EchoMind.viewer_chat.turbo_mammo_modules import (             # noqa: E402
    MAMMO_CONTEXT, MAMMO_SUBTYPE_PACKAGES)

_PROFILE = {"regions": ["breast"]}


# ── the contract survives ────────────────────────────────────────────────────

def test_the_shared_mammography_prompt_survives_verbatim():
    """The whole reason this is a prefix. If the base is ever altered here, the regex
    lock, the key list and the nine sections behind it are all at risk."""
    base = shared("MAMOGRAPHY", "")
    got = tp.build_turbo_system_prompt("MAMOGRAPHY", "", profile=_PROFILE)
    assert got.endswith(base), "the shared mammography prompt was modified"
    assert "REGEX-LOCKED JSON SCHEMA" in got


def test_the_template_is_never_rendered_for_mammography():
    got = tp.build_turbo_system_prompt("MAMOGRAPHY", "", profile=_PROFILE)
    assert not got.startswith("# ROLE"), "the nine-slot template rendered"
    assert "# OUTPUT" not in got.split("REGEX-LOCKED")[0], \
        "the template's five-key OUTPUT slot reached a regex-locked prompt"


def test_the_prefix_does_not_redefine_the_schema():
    pre = tp.build_mammography_prefix(_PROFILE)
    for key in ('"Report Title"', '"Pathological Findings"', '"Impression"',
                '"Recommendations"'):
        assert key not in pre, f"the prefix is restating {key}"


@pytest.mark.parametrize("mod", ["MAMOGRAPHY", "MAMMOGRAPHY", "mammogram", "Mamogram"])
def test_every_spelling_reaches_the_prefix(mod):
    base = shared(mod, "")
    got = tp.build_turbo_system_prompt(mod, "", profile=_PROFILE)
    assert got != base and got.endswith(base)


def test_without_a_profile_nothing_changes():
    base = shared("MAMOGRAPHY", "")
    assert tp.build_turbo_system_prompt("MAMOGRAPHY", "") == base


def test_the_kill_switch_reaches_mammography(monkeypatch):
    monkeypatch.setenv("AIPACS_TURBO_PROMPT", "0")
    assert tp.build_turbo_system_prompt("MAMOGRAPHY", "", profile=_PROFILE) is None


# ── the content ──────────────────────────────────────────────────────────────

def test_the_context_is_complete():
    assert MAMMO_CONTEXT["headings"].strip()
    for key in ("technique", "pathology", "notes", "terms"):
        assert MAMMO_CONTEXT[key], key


@pytest.mark.parametrize("probe", [
    "clock position", "composition category", "shape, margin and density",
    "morphology and the distribution", "developing asymmetry",
    "architectural distortion", "BI-RADS category",
])
def test_the_birads_lexicon_axes_are_each_named(probe):
    blob = " ".join(MAMMO_CONTEXT["pathology"]).lower()
    assert probe.lower() in blob, f"missing: {probe}"


def test_the_missing_keys_are_called_out_where_they_matter():
    """A dictated impression must be preserved inside Pathological Findings, never
    promoted to a key the schema does not have."""
    blob = " ".join(MAMMO_CONTEXT["notes"]).lower()
    assert "no impression" in blob and "no recommendations" in blob
    assert "never dropped" in blob


def test_the_category_is_never_derived():
    blob = " ".join(MAMMO_CONTEXT["pathology"]).lower()
    for rule in ("never assign", "never derive one from the descriptors"):
        assert rule in blob, rule


def test_mammography_terms_are_not_borrowed_from_another_modality():
    blob = " ".join(MAMMO_CONTEXT["terms"]).lower()
    for wrong in ("hyperdense", "hypointense", "echogenicity", "attenuation"):
        assert wrong not in blob, f"{wrong!r} is not mammographic vocabulary"


# ── the study types ──────────────────────────────────────────────────────────

EXPECTED = ("mm_diagnostic", "mm_implant", "mm_post_treatment", "mm_screening",
            "mm_tomosynthesis")


def test_the_five_study_types_exist():
    assert tuple(sorted(MAMMO_SUBTYPE_PACKAGES)) == EXPECTED


@pytest.mark.parametrize("key", EXPECTED)
def test_every_study_type_is_complete(key):
    p = MAMMO_SUBTYPE_PACKAGES[key]
    assert p["title"].strip() and p["must_report"] and p["pathology"]


@pytest.mark.parametrize("key,probe", [
    ("mm_screening", "incomplete assessment"),
    ("mm_diagnostic", "recall reason"),
    ("mm_tomosynthesis", "synthesised"),
    ("mm_implant", "eklund"),
    ("mm_post_treatment", "expected post-treatment change"),
])
def test_each_study_type_carries_its_defining_content(key, probe):
    p = MAMMO_SUBTYPE_PACKAGES[key]
    blob = " ".join(p["technique"] + p["must_report"] + p["pathology"]).lower()
    assert probe.lower() in blob, f"{key}: {probe!r} missing"


def test_a_selected_study_type_reaches_the_prompt():
    got = tp.build_turbo_system_prompt(
        "MAMOGRAPHY", "", profile={"regions": ["breast"], "subtype": "mm_implant"})
    assert "## Mammography with implants" in got


def test_an_unknown_study_type_is_ignored_rather_than_fatal():
    got = tp.build_turbo_system_prompt(
        "MAMOGRAPHY", "", profile={"regions": ["breast"], "subtype": "not_a_type"})
    assert got.endswith(shared("MAMOGRAPHY", ""))
    assert "# REPORTING CONTEXT — BREAST" in got


@pytest.mark.parametrize("key", EXPECTED)
def test_study_type_pathology_is_in_preserve_register(key):
    produce = ("specify ", "calculate ", "measure ", "estimate ", "assign a", "compute ")
    keep = ("preserve", "never", "do not", "he said", "he stated", "he described",
            "he made", "he asked", "he characterised", "he explicitly")
    for line in MAMMO_SUBTYPE_PACKAGES[key]["pathology"]:
        low = line.lower()
        assert not any(low.startswith(v) for v in produce), f"{key}: produce: {line}"
        assert any(w in low for w in keep), f"{key}: no preservation clause: {line}"


# ── provenance, and the honest trade ─────────────────────────────────────────

def test_the_authored_file_declares_its_provenance_and_the_trade():
    p = os.path.join(_ROOT, "tools", "dev", "turbo_mammo_authored.py")
    src = io.open(p, encoding="utf-8-sig").read()
    assert "CLINICAL REVIEW REQUIRED" in src
    assert "SOURCES" in src
    assert "BI-RADS" in src
    assert "no token reduction" in src, \
        "mammography gains coverage and not brevity — that has to be written down"


def test_the_prompt_really_does_get_longer():
    """Stated as a fact in the docstring, so assert it rather than trusting it."""
    base = shared("MAMOGRAPHY", "")
    got = tp.build_turbo_system_prompt("MAMOGRAPHY", "", profile=_PROFILE)
    assert len(got) > len(base)
