"""Guard: ultrasound region modules and the obstetric SUBTYPE axis (2026-08-09).

Ultrasound is the fourth library and the one that forced a second gate axis. Every
other modality gates on region alone. Obstetric ultrasound cannot: a dating scan, an NT
scan, an anomaly scan, a growth scan and a biophysical profile all have region
`obstetric` and share almost no reporting content — this centre books 17 distinct
obstetric codes. Most of what this file protects is that the two axes stay independent
and that neither leaks into the other.
"""

import io
import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind.session_metadata import REGION_KEYS                  # noqa: E402
from modules.EchoMind.viewer_chat import turbo_modules as TM               # noqa: E402
from modules.EchoMind.viewer_chat import turbo_prompt as tp                # noqa: E402
from modules.EchoMind.viewer_chat import turbo_template as T               # noqa: E402
from modules.EchoMind.viewer_chat.turbo_us_modules import (                # noqa: E402
    US_MODULES, US_SUBTYPE_PACKAGES)


# ── 1. registry ──────────────────────────────────────────────────────────────

def test_four_modalities_now_have_libraries():
    """THE ONE PLACE the exact set is pinned. Every other modality test asserts
    membership only — pinning it in four files meant adding a library broke the
    other three, which happened twice before this note was written."""
    assert TM.supported_modalities() == ("CT", "MRI", "RADIOLOGY", "SONOGRAPHY")


@pytest.mark.parametrize("raw", ["SONOGRAPHY", "ultrasound", "US", "obstetric ultrasound",
                                 "OB ultrasound", "pregnancy ultrasound",
                                 "fetal ultrasound"])
def test_every_name_for_an_ultrasound_reaches_one_library(raw):
    """`openai_reporter` branches on 'obstetric ultrasound' at line 1311 and the modality
    menu never emits it, so that prompt has been unreachable. All of these names now
    resolve to one library."""
    assert TM.normalise_modality(raw) == "SONOGRAPHY"


def test_mammography_is_the_only_modality_left_without_a_library():
    assert TM.normalise_modality("MAMOGRAPHY") == ""
    assert TM.modules_for("MAMOGRAPHY", ["breast"]) == []


# ── 2. the region modules ────────────────────────────────────────────────────

def test_every_us_module_key_is_canonical():
    for k in US_MODULES:
        assert k in REGION_KEYS


def test_every_us_module_is_complete():
    for key, m in US_MODULES.items():
        assert m["title"].strip() and m["headings"].strip(), key
        assert m["technique"], f"{key}: no technique guidance"
        assert m["pathology"], f"{key}: no pathology rules"
        assert len(m["normal"]) >= 8, f"{key}: only {len(m['normal'])} normal lines"


def test_the_technique_section_renders_and_is_ultrasound_only():
    """Not-visualised and normal are different statements on ultrasound. Same class of
    section as radiography's `projection`, and CT and MRI have neither."""
    ctx = T.render_region_context([US_MODULES["abdomen"]])
    assert ctx.count("Technique and what it limits") == 1
    assert ctx.index("Technique") < ctx.index("Pathological findings")
    for mods in (TM.modules_for("CT", ["abdomen"]), TM.modules_for("MRI", ["abdomen"])):
        assert "Technique and what it limits" not in T.render_region_context(mods)


def test_the_shared_title_regions_carry_identical_content():
    """`thyroid` and `head_neck` de-duplicate to one block, so whichever key the gate
    emitted first would otherwise decide whether the carotids were covered."""
    assert US_MODULES["thyroid"]["normal"] == US_MODULES["head_neck"]["normal"]
    assert US_MODULES["thyroid"]["pathology"] == US_MODULES["head_neck"]["pathology"]
    assert len(TM.modules_for("SONOGRAPHY", ["head_neck", "thyroid"])) == 1


def test_the_extracted_thresholds_survived():
    """These are the radiologist's numbers, in the shared prompt's exam templates."""
    blob = " ".join(US_MODULES["abdomen"]["normal"])
    for probe in ("15–16 cm", "≤13 mm", "≤6 mm", "≤12 cm", "9–12 cm"):
        assert probe in blob, f"{probe!r} was lost from the abdominal reference"
    assert "125 cm/s" in " ".join(US_MODULES["head_neck"]["normal"])
    assert "3–5" in " ".join(US_MODULES["scrotum"]["normal"])


def test_the_sex_rule_did_not_leak_out_of_the_gynaecologic_block():
    for key, m in US_MODULES.items():
        for line in m["normal"]:
            for leak in ("DO NOT infer", "NEVER include BOTH", "ONE set of organs"):
                assert leak not in line, f"{key}: the sex rule leaked into a normal line"
    assert "Never infer the patient's sex" in T.RULES_NORMAL


# ── 3. the subtype axis ──────────────────────────────────────────────────────

EXPECTED_SUBTYPES = ("ob_anomaly", "ob_bpp", "ob_doppler", "ob_ectopic",
                     "ob_first_trimester", "ob_growth", "ob_multiple", "ob_nt",
                     "ob_placenta")


def test_the_obstetric_subtypes_exist():
    assert TM.known_subtypes("SONOGRAPHY") == EXPECTED_SUBTYPES


def test_the_cross_sectional_modalities_have_no_subtypes():
    """CT and MRI gate on region alone. Radiography got its own subtype library later
    the same day — the assertion moved to what is still true rather than being deleted."""
    for mod in ("CT", "MRI", "MAMOGRAPHY"):
        assert TM.known_subtypes(mod) == ()


def test_an_obstetric_subtype_never_reaches_another_modality():
    """Two libraries now exist on this axis. They must not see each other's keys."""
    for mod in ("CT", "MRI", "RADIOLOGY", "MAMOGRAPHY"):
        assert TM.subtypes_for(mod, ["ob_nt", "ob_anomaly"]) == []
    assert TM.subtypes_for("SONOGRAPHY", ["xr_bone_age"]) == []


@pytest.mark.parametrize("key", EXPECTED_SUBTYPES)
def test_every_subtype_package_is_complete(key):
    p = US_SUBTYPE_PACKAGES[key]
    assert p["title"].strip()
    assert p["must_report"], f"{key}: nothing it must report"
    assert p["pathology"], f"{key}: no pathology rules"


def test_a_study_with_no_subtype_renders_no_study_type_block():
    """Most studies have no subtype. A bare heading would be worse than nothing."""
    assert T.render_subtype_context([]) == ""
    p = T.render(modality="SONOGRAPHY", study_facts=[("Modality", "SONOGRAPHY", "")],
                 modules=[US_MODULES["abdomen"]])
    assert "# STUDY TYPE" not in p


def test_the_subtype_block_comes_after_the_region_context():
    """It narrows within the region, so it has to follow it."""
    p = T.render(modality="SONOGRAPHY", study_facts=[("Modality", "SONOGRAPHY", "")],
                 modules=[US_MODULES["obstetric"]],
                 subtypes=[US_SUBTYPE_PACKAGES["ob_nt"]])
    assert p.index("# REPORTING CONTEXT") < p.index("# STUDY TYPE") < p.index("# OUTPUT")


def test_subtypes_de_duplicate_by_title():
    got = TM.subtypes_for("SONOGRAPHY", ["ob_nt", "ob_nt", "ob_growth"])
    assert len(got) == 2


def test_an_unknown_subtype_is_ignored_rather_than_fatal():
    assert TM.subtypes_for("SONOGRAPHY", ["not_a_subtype"]) == []
    assert len(TM.subtypes_for("SONOGRAPHY", ["not_a_subtype", "ob_nt"])) == 1


@pytest.mark.parametrize("key,probe", [
    ("ob_first_trimester", "14 days"),
    ("ob_ectopic", "unknown location"),
    ("ob_nt", "crown-rump length"),
    ("ob_anomaly", "cavum septi pellucidi"),
    ("ob_growth", "growth chart"),
    ("ob_doppler", "end-diastolic flow"),
    ("ob_bpp", "five components"),
    ("ob_placenta", "clear zone"),
    ("ob_multiple", "chorionicity"),
])
def test_each_subtype_carries_its_own_defining_content(key, probe):
    """The whole reason the axis exists: these share a region and share nothing else."""
    blob = " ".join(US_SUBTYPE_PACKAGES[key]["must_report"]
                    + US_SUBTYPE_PACKAGES[key]["pathology"]
                    + US_SUBTYPE_PACKAGES[key].get("technique", [])).lower()
    assert probe.lower() in blob, f"{key}: {probe!r} missing"


def test_the_anatomy_survey_reaches_only_the_anomaly_scan():
    """Sending the ISUOG survey to a viability scan is the error the axis prevents."""
    for key, p in US_SUBTYPE_PACKAGES.items():
        blob = " ".join(p["must_report"]).lower()
        if "cavum septi pellucidi" in blob:
            assert key == "ob_anomaly", f"{key} received the anatomy survey"


#: Verbs that would instruct the model to PRODUCE a value the physician did not give.
_PRODUCE = ("specify ", "calculate ", "measure ", "estimate ", "assign a", "compute ")


@pytest.mark.parametrize("key", EXPECTED_SUBTYPES)
def test_subtype_pathology_is_in_preserve_register(key):
    keep = ("preserve", "never", "do not", "he gave", "he stated", "he used",
            "he made", "he measured", "he described", "he assigned", "he determined",
            "he calculated", "he recorded", "he took", "he could")
    for line in US_SUBTYPE_PACKAGES[key]["pathology"]:
        low = line.lower()
        assert not any(low.startswith(v) for v in _PRODUCE), f"{key}: produce: {line}"
        assert any(w in low for w in keep), f"{key}: no preservation clause: {line}"


@pytest.mark.parametrize("key", EXPECTED_SUBTYPES)
def test_subtype_must_report_is_a_coverage_list_not_an_instruction(key):
    """`must_report` is a different KIND of section from `pathology`. It is a coverage
    checklist — the ISUOG anatomy survey, the five BPP components, the biometric set —
    and reads like `normal` or `headings`, not like a rule about the physician's words.
    Holding it to preserve-register was a category error in an earlier version of this
    test. What it must NOT do is instruct the model to produce a value."""
    for line in US_SUBTYPE_PACKAGES[key]["must_report"]:
        low = line.lower()
        assert not any(low.startswith(v) for v in _PRODUCE), f"{key}: produce: {line}"
        assert not any(v in low for v in ("you must calculate", "you should compute",
                                          "derive the")), f"{key}: derives: {line}"


@pytest.mark.parametrize("key,measurement,caveat", [
    ("ob_growth", "centile", "growth chart"),
    ("ob_growth", "amniotic fluid", "not interchangeable"),
    ("ob_nt", "risk", "not yours to derive"),
    ("ob_doppler", "index", "not interchangeable"),
    ("ob_bpp", "total", "never compute"),
    ("ob_placenta", "grade", "never assign a grade"),
])
def test_a_derived_obstetric_value_is_never_computed_by_the_model(key, measurement,
                                                                 caveat):
    """A centile depends on the chart, a risk on the software, a BPP total on a clinical
    instrument. None of them can be re-derived from what was dictated."""
    blob = " ".join(US_SUBTYPE_PACKAGES[key]["must_report"]
                    + US_SUBTYPE_PACKAGES[key]["pathology"]).lower()
    assert measurement.lower() in blob, f"{key}: {measurement!r} not mentioned"
    assert caveat.lower() in blob, f"{key}: missing the caveat {caveat!r}"


# ── 4. the seam ──────────────────────────────────────────────────────────────

def test_with_the_template_off_an_ultrasound_report_is_unchanged(monkeypatch):
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "0")
    from modules.EchoMind.viewer_chat.openai_reporter import build_report_system_prompt
    base = build_report_system_prompt("SONOGRAPHY", "")
    for prof in ({"regions": ["abdomen"]},
                 {"regions": ["obstetric"], "subtype": "ob_nt"},
                 {"regions": ["scrotum"]}):
        assert tp.build_turbo_system_prompt("SONOGRAPHY", "", profile=prof) == base


def test_with_the_template_on_ultrasound_renders(monkeypatch):
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "1")
    got = tp.build_turbo_system_prompt(
        "SONOGRAPHY", "", profile={"regions": ["obstetric"], "subtype": "ob_anomaly"})
    assert got.startswith("# ROLE")
    assert "## Obstetric" in got
    assert "# STUDY TYPE" in got and "Mid-trimester anomaly scan" in got


def test_a_subtype_string_or_a_list_both_work(monkeypatch):
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "1")
    a = tp.build_turbo_system_prompt(
        "SONOGRAPHY", "", profile={"regions": ["obstetric"], "subtype": "ob_nt"})
    b = tp.build_turbo_system_prompt(
        "SONOGRAPHY", "", profile={"regions": ["obstetric"], "subtype": ["ob_nt"]})
    assert a == b


def test_narrowing_is_never_applied_to_ultrasound(monkeypatch):
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "0")
    from modules.EchoMind.viewer_chat.openai_reporter import build_report_system_prompt
    got = tp.build_turbo_system_prompt("SONOGRAPHY", "", profile={"regions": ["pelvis"]})
    assert got == build_report_system_prompt("SONOGRAPHY", "")


@pytest.mark.parametrize("key", sorted(US_MODULES))
def test_every_us_region_renders_a_complete_prompt(key):
    p = T.render(modality="SONOGRAPHY",
                 study_facts=[("Modality", "SONOGRAPHY", "DICOM"),
                              ("Regions", key, "gate")],
                 modules=[US_MODULES[key]])
    assert p.startswith("# ROLE") and p.rstrip().endswith("Start with { and end with }.")
    assert 3000 < len(p) < 22000, f"{key}: {len(p)} chars"


# ── 5. provenance ────────────────────────────────────────────────────────────

def test_the_authored_us_content_declares_its_provenance():
    p = os.path.join(_ROOT, "tools", "dev", "turbo_us_authored.py")
    src = io.open(p, encoding="utf-8-sig").read()
    assert "CLINICAL REVIEW REQUIRED" in src
    assert "SOURCES" in src
    assert "ISUOG" in src


def test_the_unreachable_obstetric_prompt_is_recorded():
    """A complete 10-section ISUOG prompt that nothing could invoke. The finding has to
    live where the next person will look."""
    p = os.path.join(_ROOT, "tools", "dev", "turbo_us_authored.py")
    src = io.open(p, encoding="utf-8-sig").read()
    assert "unreachable" in src.lower()
    assert "1311" in src


def test_the_generator_self_verifies():
    p = os.path.join(_ROOT, "tools", "dev", "gen_turbo_us_modules.py")
    src = io.open(p, encoding="utf-8-sig").read()
    assert "the block moved" in src
    assert "round trip lost a subtype" in src
