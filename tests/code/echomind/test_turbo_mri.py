"""Guard: the MRI region modules and the modality-keyed registry (2026-08-09).

MRI is the second modality to get a region library, and adding it is what forced the
library to become modality-keyed rather than implicitly CT. The two things this file
protects are (a) that MRI content is MRI content — not CT content wearing an MRI label
— and (b) that with the template flag off, an MRI report is byte-identical to what the
shared builder produced yesterday.
"""

import io
import os
import re
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
from modules.EchoMind.viewer_chat.turbo_mri_modules import MRI_MODULES     # noqa: E402


# ── 1. the registry ──────────────────────────────────────────────────────────

def test_the_registry_knows_mri():
    """The exact set is pinned in test_turbo_xr.py; this file only cares that
    MRI is in it and that it did not lose CT on the way."""
    assert "MRI" in TM.supported_modalities()
    assert "CT" in TM.supported_modalities()


@pytest.mark.parametrize("raw,expect", [
    ("MRI", "MRI"), ("mri", "MRI"), ("MR", "MRI"), (" Mr ", "MRI"),
    ("CT", "CT"), ("ct", "CT"),
    ("MAMOGRAPHY", ""), ("", ""), (None, ""),
])
def test_modality_normalisation(raw, expect):
    assert TM.normalise_modality(raw) == expect


def test_a_modality_with_no_library_selects_nothing():
    """Mammography has no library. Returning [] is what makes the prompt builder
    fall back to the full shared prompt. Radiography and ultrasound both HAD no
    library when this was written and have one now — each time, the assertion moved
    to what was still true rather than being deleted."""
    assert TM.modules_for("MAMOGRAPHY", ["breast"]) == []
    assert TM.library_for("MAMOGRAPHY") == {}


def test_the_two_libraries_are_not_the_same_object():
    assert TM.library_for("CT") is not TM.library_for("MRI")
    assert TM.module_for("MRI", "spine_lumbar") is not TM.module_for("CT", "spine_lumbar")


def test_shared_titles_share_one_module_on_mri_too():
    assert len(TM.modules_for("MRI", ["head_neck", "thyroid"])) == 1


# ── 2. the modules ───────────────────────────────────────────────────────────

def test_every_mri_module_key_is_canonical():
    for k in MRI_MODULES:
        assert k in REGION_KEYS, f"{k!r} is not a canonical region key"


def test_every_mri_module_has_all_five_sections():
    for key, m in MRI_MODULES.items():
        assert m["title"].strip(), f"{key}: no title"
        assert m["headings"].strip(), f"{key}: no headings"
        assert m["pathology"], f"{key}: no pathology rules"
        assert len(m["normal"]) >= 8, f"{key}: only {len(m['normal'])} normal lines"
        assert m["terms"], f"{key}: no dictation terms"


def test_mri_modules_do_not_carry_ct_attenuation_terms():
    """The CT always-on lexicon says هایپردنس → hyperdense/hypodense. Attenuation is a
    CT concept; on MRI the physician says hyperintense. Reusing the CT list wholesale
    would teach the model the wrong word for the modality."""
    for key, m in MRI_MODULES.items():
        blob = " ".join(m["terms"]).lower()
        assert "hyperdense" not in blob, f"{key}: CT attenuation term in an MRI module"
        assert "hypodense" not in blob, f"{key}: CT attenuation term in an MRI module"


def test_mri_modules_name_the_sequences():
    """Signal has no meaning without the sequence that shows it — the one thing MRI
    needs that CT does not."""
    for key, m in MRI_MODULES.items():
        terms = " ".join(m["terms"])
        assert "T1" in terms and "T2" in terms and "DWI" in terms, f"{key}"


def test_the_sex_rule_did_not_leak_into_the_normal_lines():
    """The ABDOMEN / PELVIS block embeds the sex rule as prose. Cutting it bullet by
    bullet left continuation lines behind that merged into the Bladder line."""
    for key, m in MRI_MODULES.items():
        for line in m["normal"]:
            for leak in ("DO NOT assume", "reliably determined",
                         "ONE set of organs", "NEVER include BOTH"):
                assert leak not in line, f"{key}: rule text leaked into a normal line"


def test_the_sex_rule_itself_still_exists_exactly_once_in_the_shared_slot():
    assert "Never infer the patient's sex" in T.RULES_NORMAL


@pytest.mark.parametrize("key,present,absent", [
    ("spine_cervical", "Craniocervical junction", "Sacrum and sacroiliac"),
    ("spine_lumbar", "Sacrum and sacroiliac", "Craniocervical junction"),
])
def test_spine_level_conditionals_are_resolved_per_level(key, present, absent):
    """The source block carries [Cervical] and [Lumbar] markers on shared lines."""
    blob = " ".join(MRI_MODULES[key]["normal"])
    assert present in blob
    assert absent not in blob
    assert "[Cervical]" not in blob and "[Lumbar]" not in blob


def test_the_all_levels_spine_package_keeps_both_markers():
    blob = " ".join(MRI_MODULES["spine"]["normal"])
    assert "[Cervical]" in blob and "[Lumbar]" in blob


def test_extremity_draws_on_every_msk_sub_block():
    blob = " ".join(MRI_MODULES["extremity"]["normal"]).lower()
    for probe in ("meniscus", "supraspinatus", "acetabular labrum", "achilles",
                  "triangular fibrocartilage"):
        assert probe in blob, f"extremity is missing {probe!r}"


# ── 3. the pathology half ────────────────────────────────────────────────────

#: system -> the only MRI region titles allowed to mention it.
MRI_SYSTEM_OWNERS = {
    "Pfirrmann": {"Spine", "Cervical spine", "Thoracic spine", "Lumbar spine"},
    "Modic": {"Spine", "Cervical spine", "Thoracic spine", "Lumbar spine"},
    "Schizas": {"Spine", "Cervical spine", "Thoracic spine", "Lumbar spine"},
    "Meyerding": {"Spine", "Cervical spine", "Thoracic spine", "Lumbar spine"},
    "Wiltse": {"Spine", "Cervical spine", "Thoracic spine", "Lumbar spine"},
    "Fazekas": {"Brain"},
    "ASPECTS": {"Brain"},
    "RANO": {"Brain"},
    "Koedam": {"Brain"},
    "Outerbridge": {"Knee"},
    "ICRS": {"Knee"},
    "Goutallier": {"Shoulder"},
    "Patte": {"Shoulder"},
    "Ellman": {"Shoulder"},
    "ISAKOS": {"Shoulder"},
    "SLAP": {"Shoulder"},
    "Tonnis": {"Hip"},
    "ARCO": {"Hip"},
    "Czerny": {"Hip"},
    "Hepple": {"Ankle and foot"},
    "Berndt-Harty": {"Ankle and foot"},
    "Palmer": {"Wrist and hand"},
    "BI-RADS": {"Breast"},
    "PI-RADS": {"Prostate"},
    "LI-RADS": {"Abdomen"},
    "Bosniak": {"Abdomen"},
    "O-RADS": {"Pelvis"},
    "Enzian": {"Pelvis"},
    "NI-RADS": {"Neck"},
    "Koos": {"Temporal bone"},
}


@pytest.mark.parametrize("system,owners", sorted(MRI_SYSTEM_OWNERS.items()))
def test_an_mri_region_never_sees_another_regions_system(system, owners):
    for key, m in MRI_MODULES.items():
        if system in T.render_region_context([m]):
            assert m["title"] in owners, (
                f"{key} ({m['title']}) was shown {system}, which belongs to {owners}")


@pytest.mark.parametrize("key", sorted(MRI_MODULES))
def test_mri_pathology_rules_preserve_rather_than_produce(key):
    produce = ("specify ", "calculate ", "measure ", "estimate ", "assign a", "compute ")
    keep = ("preserve", "he dictated", "he gave", "he named", "as dictated",
            "only when", "never assign", "standardise", "unless he", "he stated",
            "he described", "he used", "he saw", "he assigned", "he made")
    for line in MRI_MODULES[key]["pathology"]:
        low = line.lower()
        assert not any(low.startswith(v) for v in produce), f"{key}: produce: {line}"
        assert any(w in low for w in keep), f"{key}: no preservation clause: {line}"


#: (region, measurement, the caveat that must travel with it)
MRI_CONTESTED = [
    ("spine", "Pfirrmann", "which Pfirrmann"),
    ("spine_lumbar", "circumference thresholds", "disagree between"),
    ("knee", "Outerbridge", "differ between sources"),
    ("hip", "ARCO", "different systems"),
    ("prostate", "PI-RADS", "version"),
    ("head_neck", "NI-RADS", "version"),
    ("brain", "Fazekas", "both in use"),
    ("orbit", "muscle", "differ between series"),
]


@pytest.mark.parametrize("region,measurement,caveat", MRI_CONTESTED)
def test_a_contested_mri_definition_travels_with_its_caveat(region, measurement, caveat):
    """Two systems share the name Pfirrmann; ARCO has two incompatible versions;
    PI-RADS v2 and v2.1 differ in the transition-zone rule. Encoding one side silently
    produces a confidently wrong report."""
    lines = [l for l in MRI_MODULES[region]["pathology"]
             if measurement.lower() in l.lower()]
    assert lines, f"{region}: no pathology line mentions {measurement!r}"
    assert any(caveat.lower() in l.lower() for l in lines), (
        f"{region}: {measurement!r} is stated without the caveat {caveat!r}")


# ── 4. the seam: nothing changes until the flag is on ────────────────────────

def test_with_the_template_off_an_mri_report_is_unchanged(monkeypatch):
    """The whole safety argument for landing this: v2 off means byte-identical."""
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "0")
    from modules.EchoMind.viewer_chat.openai_reporter import build_report_system_prompt
    got = tp.build_turbo_system_prompt("MRI", "", profile={"regions": ["spine_lumbar"]})
    assert got == build_report_system_prompt("MRI", "")


def test_narrowing_is_never_applied_to_mri(monkeypatch):
    """The three narrowed spans were extracted from the CT branch and the drift
    self-check is against that extraction. Applying them to MRI would cut blind."""
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "0")
    from modules.EchoMind.viewer_chat.openai_reporter import build_report_system_prompt
    base = build_report_system_prompt("MRI", "")
    for regions in (["brain"], ["knee"], ["abdomen", "pelvis"]):
        assert tp.build_turbo_system_prompt("MRI", "", profile={"regions": regions}) == base


def test_with_the_template_on_mri_renders(monkeypatch):
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "1")
    got = tp.build_turbo_system_prompt("MRI", "", profile={"regions": ["knee"]})
    assert got.startswith("# ROLE")
    assert "# MODALITY — MRI" in got
    assert "## Knee" in got
    assert "Menisci" in got


def test_an_mri_region_with_no_module_falls_back(monkeypatch):
    """Cardiac, chest and fetal MRI have no block in the shared prompt and none was
    invented. A study gated to one of those must get the FULL prompt, not a thin one."""
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "1")
    from modules.EchoMind.viewer_chat.openai_reporter import build_report_system_prompt
    got = tp.build_turbo_system_prompt("MRI", "", profile={"regions": ["chest"]})
    assert got == build_report_system_prompt("MRI", "")


def test_mammography_keeps_its_shared_prompt_whole(monkeypatch):
    """Mammography gained a PREFIX on 2026-08-09, not a template — its schema is
    regex-locked. So it is no longer byte-identical, but the shared prompt behind the
    prefix must still be there in full. That is the invariant this test kept."""
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "1")
    from modules.EchoMind.viewer_chat.openai_reporter import build_report_system_prompt
    base = build_report_system_prompt("MAMOGRAPHY", "")
    got = tp.build_turbo_system_prompt("MAMOGRAPHY", "", profile={"regions": ["breast"]})
    assert got.endswith(base)
    assert not got.startswith("# ROLE"), "the template rendered into a regex-locked prompt"


@pytest.mark.parametrize("key", sorted(MRI_MODULES))
def test_every_mri_region_renders_a_complete_prompt(key):
    p = T.render(modality="MRI",
                 study_facts=[("Modality", "MRI", "DICOM"), ("Regions", key, "gate")],
                 modules=[MRI_MODULES[key]])
    assert p.startswith("# ROLE") and p.rstrip().endswith("Start with { and end with }.")
    assert 3000 < len(p) < 16000, f"{key}: {len(p)} chars is out of the sane range"


def test_the_mri_prompt_is_much_smaller_than_the_one_it_replaces():
    from modules.EchoMind.viewer_chat.openai_reporter import build_report_system_prompt
    shared = len(build_report_system_prompt("MRI", ""))
    for key in MRI_MODULES:
        p = T.render(modality="MRI", study_facts=[("Modality", "MRI", "DICOM")],
                     modules=[MRI_MODULES[key]])
        assert len(p) < shared * 0.5, f"{key} is not meaningfully smaller"


# ── 5. provenance ────────────────────────────────────────────────────────────

def test_the_authored_mri_content_declares_its_provenance():
    p = os.path.join(_ROOT, "tools", "dev", "turbo_mri_authored.py")
    assert os.path.exists(p), "the authored MRI content file was moved or deleted"
    src = io.open(p, encoding="utf-8-sig").read()
    assert "CLINICAL REVIEW REQUIRED" in src
    assert "Not read by a radiologist" in src
    assert "SOURCES" in src


def test_the_generator_still_exists_and_self_verifies():
    p = os.path.join(_ROOT, "tools", "dev", "gen_turbo_mri_modules.py")
    src = io.open(p, encoding="utf-8-sig").read()
    assert "round trip lost a module" in src
    assert "round trip changed" in src


def test_the_uncovered_mri_studies_are_named_in_the_generated_file():
    """Cardiac MRI is 6 of this centre's 65 MRI service codes and has no block. The
    gap has to be visible where someone would look for the module."""
    p = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "turbo_mri_modules.py")
    src = io.open(p, encoding="utf-8-sig").read()
    assert "NOT COVERED" in src
    assert "cardiac" in src.lower()
