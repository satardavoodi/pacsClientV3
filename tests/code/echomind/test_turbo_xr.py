"""Guard: the radiography (X-ray) region modules (2026-08-09).

X-ray is the third modality library and the first with a shape of its own. CT and MRI
acquire a volume; a radiograph acquires one view, and a view cannot assess what it does
not show. That is the `projection` section, and most of what this file protects is that
it exists, that it reaches the model, and that CT and MRI are unaffected by it.

It is also the first library that is mostly AUTHORED rather than extracted — the
RADIOLOGY branch of the shared prompt has about twenty normal-findings lines in total —
so the cross-check that nothing a radiologist wrote was dropped is a guard here too.
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
from modules.EchoMind.viewer_chat.turbo_mri_modules import MRI_MODULES     # noqa: E402
from modules.EchoMind.viewer_chat.turbo_region_modules import REGION_MODULES  # noqa: E402
from modules.EchoMind.viewer_chat.turbo_xr_modules import (                # noqa: E402
    XR_MODULES, XR_SUBTYPE_PACKAGES)


# ── 1. the registry ──────────────────────────────────────────────────────────

def test_the_registry_knows_radiography():
    """Membership only. The exact set is pinned once, in test_turbo_us.py."""
    assert "RADIOLOGY" in TM.supported_modalities()


@pytest.mark.parametrize("raw", ["RADIOLOGY", "radiography", "CR", "DX", "DR",
                                 "XR", "X-ray", "xray", " Radiology "])
def test_every_name_for_a_radiograph_reaches_one_library(raw):
    """The menu says RADIOLOGY, DICOM says CR/DX/DR, people say X-ray."""
    assert TM.normalise_modality(raw) == "RADIOLOGY"


def test_mammography_still_has_no_library():
    """Ultrasound was in this list until it got a library on the same day."""
    for m in ("MAMOGRAPHY", "MAMMOGRAPHY", "MAMMOGRAM"):
        assert TM.normalise_modality(m) == ""
        assert TM.modules_for(m, ["breast"]) == []


# ── 2. the two new canonical keys ────────────────────────────────────────────

@pytest.mark.parametrize("key", ["elbow", "bone_density"])
def test_the_new_region_keys_are_canonical(key):
    """A key that is not in REGION_KEYS can never be detected, so the module written
    for it would be unreachable."""
    assert key in REGION_KEYS
    assert key in XR_MODULES


@pytest.mark.parametrize("key", ["elbow", "bone_density"])
def test_the_new_keys_do_not_break_the_other_libraries(key):
    """CT and MRI have no elbow or DEXA package. That must fall back, not crash."""
    assert TM.modules_for("CT", [key]) == []
    assert TM.modules_for("MRI", [key]) == []
    assert key not in REGION_MODULES and key not in MRI_MODULES


def test_the_dicom_map_can_reach_the_new_keys():
    from modules.EchoMind.session_metadata import normalize_region
    assert "elbow" in normalize_region("ELBOW")
    assert "bone_density" in normalize_region("DEXA")


# ── 3. the projection section ────────────────────────────────────────────────

def test_every_xr_module_has_a_projection_section():
    for key, m in XR_MODULES.items():
        assert m["projection"], f"{key}: no projection guidance"


def test_the_projection_block_renders_once_and_before_the_findings():
    """It constrains everything after it, and it was briefly emitted twice."""
    ctx = T.render_region_context([XR_MODULES["knee"]])
    assert ctx.count("What the performed projection can and cannot assess") == 1
    assert ctx.index("performed projection") < ctx.index("Pathological findings")
    assert ctx.index("Pathological findings") < ctx.index("Normal-findings reference")


def test_ct_and_mri_render_no_projection_block():
    """They have no such key, and adding the section must not have changed them."""
    for mods in (TM.modules_for("CT", ["chest", "abdomen"]),
                 TM.modules_for("MRI", ["brain", "knee"])):
        assert "performed projection" not in T.render_region_context(mods)


@pytest.mark.parametrize("key,probe", [
    ("chest", "supine"),
    ("abdomen", "supine film"),
    ("knee", "skyline"),
    ("shoulder", "axillary"),
    ("elbow", "true lateral"),
    ("ankle_foot", "mortise"),
    ("spine_cervical", "T1"),
    ("bone_density", "lowest T-score"),
])
def test_the_projection_rules_carry_their_specific_trap(key, probe):
    """Each of these is a real error the section exists to prevent: heart size on a
    supine chest, free air excluded from a supine abdomen, the patellofemoral joint
    read off an AP knee, dislocation direction from an AP shoulder."""
    blob = " ".join(XR_MODULES[key]["projection"]).lower()
    assert probe.lower() in blob, f"{key}: {probe!r} missing from the projection rules"


# ── 4. the modules ───────────────────────────────────────────────────────────

def test_every_xr_module_key_is_canonical():
    for k in XR_MODULES:
        assert k in REGION_KEYS, f"{k!r} is not a canonical region key"


def test_every_xr_module_is_complete():
    for key, m in XR_MODULES.items():
        assert m["title"].strip(), f"{key}: no title"
        assert m["headings"].strip(), f"{key}: no headings"
        assert m["pathology"], f"{key}: no pathology rules"
        assert len(m["normal"]) >= 8, f"{key}: only {len(m['normal'])} normal lines"
        assert m["terms"], f"{key}: no dictation terms"


def test_xr_modules_do_not_carry_cross_sectional_terms():
    """Attenuation is CT, signal intensity is MRI. Neither belongs on a radiograph."""
    for key, m in XR_MODULES.items():
        blob = " ".join(m["terms"]).lower()
        for wrong in ("hyperdense", "hypodense", "hyperintense", "hypointense"):
            assert wrong not in blob, f"{key}: {wrong!r} is not radiographic vocabulary"


#: system -> the only X-ray region titles allowed to mention it
XR_SYSTEM_OWNERS = {
    "Kellgren-Lawrence": {"Knee", "Hip", "Pelvis"},
    "Schatzker": {"Knee"},
    "Insall-Salvati": {"Knee"},
    "Neer": {"Shoulder"},
    "Rockwood": {"Shoulder"},
    "Garden": {"Hip", "Pelvis"},
    "Pauwels": {"Hip", "Pelvis"},
    "Tonnis": {"Hip", "Pelvis"},
    "Gustilo-Anderson": {"Hip", "Pelvis"},
    "Mason": {"Elbow"},
    "Gartland": {"Elbow"},
    "Baumann": {"Elbow"},
    "Weber": {"Ankle and foot"},
    "Lauge-Hansen": {"Ankle and foot"},
    "Genant": {"Spine", "Cervical spine", "Thoracic spine", "Lumbar spine"},
    "Meyerding": {"Spine", "Cervical spine", "Thoracic spine", "Lumbar spine"},
    "Wiltse": {"Spine", "Cervical spine", "Thoracic spine", "Lumbar spine"},
    "Cobb": {"Spine", "Cervical spine", "Thoracic spine", "Lumbar spine"},
    "ILO": {"Chest"},
}


@pytest.mark.parametrize("system,owners", sorted(XR_SYSTEM_OWNERS.items()))
def test_an_xr_region_never_sees_another_regions_system(system, owners):
    for key, m in XR_MODULES.items():
        if system in T.render_region_context([m]):
            assert m["title"] in owners, (
                f"{key} ({m['title']}) was shown {system}, which belongs to {owners}")


@pytest.mark.parametrize("key", sorted(XR_MODULES))
def test_xr_pathology_rules_preserve_rather_than_produce(key):
    produce = ("specify ", "calculate ", "measure ", "estimate ", "assign a", "compute ")
    keep = ("preserve", "he dictated", "he gave", "he named", "as dictated",
            "only when", "never assign", "standardise", "unless he", "he stated",
            "he described", "he used", "he measured", "he assigned", "he called",
            "he made", "he identified", "he localised", "he attributed", "do not",
            "never")
    for line in XR_MODULES[key]["pathology"]:
        low = line.lower()
        assert not any(low.startswith(v) for v in produce), f"{key}: produce: {line}"
        assert any(w in low for w in keep), f"{key}: no preservation clause: {line}"


#: (region, measurement, the caveat that must travel with it)
XR_CONTESTED = [
    ("chest", "6 to 8 cm", "carry his number"),
    ("abdomen", "2.5 cm", "carry his figure"),
    ("hip", "centre-edge", "Published normals disagree"),
    ("elbow", "Baumann", "differ widely between series"),
    ("spine_cervical", "Prevertebral", "thresholds disagree"),
    ("knee", "Patellar height", "different normal bands"),
    ("wrist_hand", "magnification-dependent", "carry his number as his"),
]


@pytest.mark.parametrize("region,measurement,caveat", XR_CONTESTED)
def test_a_contested_radiographic_value_travels_with_its_caveat(region, measurement,
                                                                caveat):
    lines = [l for l in XR_MODULES[region]["pathology"]
             if measurement.lower() in l.lower()]
    assert lines, f"{region}: no pathology line mentions {measurement!r}"
    assert any(caveat.lower() in l.lower() for l in lines), (
        f"{region}: {measurement!r} is stated without the caveat {caveat!r}")


def test_gustilo_is_never_assignable_from_a_film():
    """It classifies the wound at physical examination, not the radiograph."""
    blob = " ".join(XR_MODULES["hip"]["pathology"]).lower()
    assert "never assign a gustilo" in blob


# ── 5. the seam ──────────────────────────────────────────────────────────────

def test_with_the_template_off_a_radiograph_report_is_unchanged(monkeypatch):
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "0")
    from modules.EchoMind.viewer_chat.openai_reporter import build_report_system_prompt
    base = build_report_system_prompt("RADIOLOGY", "")
    for regions in (["knee"], ["chest"], ["bone_density"], ["spine_lumbar"]):
        got = tp.build_turbo_system_prompt("RADIOLOGY", "", profile={"regions": regions})
        assert got == base, regions


def test_narrowing_is_never_applied_to_radiography(monkeypatch):
    """The narrowed spans were extracted from the CT branch."""
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "0")
    from modules.EchoMind.viewer_chat.openai_reporter import build_report_system_prompt
    got = tp.build_turbo_system_prompt("RADIOLOGY", "", profile={"regions": ["abdomen"]})
    assert got == build_report_system_prompt("RADIOLOGY", "")


def test_with_the_template_on_radiography_renders(monkeypatch):
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "1")
    got = tp.build_turbo_system_prompt("RADIOLOGY", "", profile={"regions": ["chest"]})
    assert got.startswith("# ROLE")
    assert "# MODALITY — RADIOLOGY" in got
    assert "## Chest" in got
    assert "performed projection" in got


@pytest.mark.parametrize("key", sorted(XR_MODULES))
def test_every_xr_region_renders_a_complete_prompt(key):
    p = T.render(modality="RADIOLOGY",
                 study_facts=[("Modality", "RADIOLOGY", "DICOM"),
                              ("Regions", key, "gate")],
                 modules=[XR_MODULES[key]])
    assert p.startswith("# ROLE") and p.rstrip().endswith("Start with { and end with }.")
    assert 3000 < len(p) < 16000, f"{key}: {len(p)} chars is out of the sane range"


def test_the_three_libraries_stay_distinct():
    """Same region key, three modalities, three different packages."""
    for key in ("chest", "abdomen", "knee", "spine_lumbar"):
        ct = TM.module_for("CT", key)
        mr = TM.module_for("MRI", key)
        xr = TM.module_for("RADIOLOGY", key)
        got = [m for m in (ct, mr, xr) if m]
        assert len(got) >= 2, key
        normals = [tuple(m["normal"]) for m in got]
        assert len(set(normals)) == len(normals), f"{key}: two libraries share content"


# ── 6. provenance ────────────────────────────────────────────────────────────

def test_the_authored_xr_content_declares_its_provenance():
    p = os.path.join(_ROOT, "tools", "dev", "turbo_xr_authored.py")
    src = io.open(p, encoding="utf-8-sig").read()
    assert "CLINICAL REVIEW REQUIRED" in src
    assert "Not read by a radiologist" in src
    assert "SOURCES" in src
    assert "MAGNIFICATION" in src


def test_the_generator_cross_checks_the_extracted_lines():
    """The shared prompt's twenty lines are few but they are the radiologist's. The
    generator must fail loudly if they move, and report any that lost a counterpart."""
    p = os.path.join(_ROOT, "tools", "dev", "gen_turbo_xr_modules.py")
    src = io.open(p, encoding="utf-8-sig").read()
    assert "the RADIOLOGY blocks moved" in src
    assert "no counterpart in the built library" in src
    assert "round trip changed" in src


def test_the_uncovered_studies_are_named_in_the_generated_file():
    p = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "turbo_xr_modules.py")
    src = io.open(p, encoding="utf-8-sig").read()
    assert "NOT COVERED" in src
    assert "fluoroscopy" in src.lower()
    assert "bone age" in src.lower()


# ── 7. the radiography study types ───────────────────────────────────────────

#: Every category the owner asked for on 2026-08-09, and where it landed.
#: Two are regions, not subtypes: sinus radiography already had a region module
#: (strengthened with the named projections) and pelvic bone is the `pelvis` region.
REQUESTED = {
    "nasal bone": "xr_nasal_bone",
    "hysterosalpingography": "xr_hsg",
    "retrograde urethrography": "xr_rug",
    "intravenous pyelography": "xr_ivp",
    "barium swallow": "xr_barium_swallow",
    "barium meal": "xr_barium_meal",
    "small bowel follow-through": "xr_sbft",
    "barium enema": "xr_barium_enema",
    "fistulography": "xr_fistulography",
    "colon transit": "xr_colon_transit",
    "spine alignment": "xr_spine_alignment",
    "spine flexion-extension": "xr_spine_flexion_extension",
    "spine oblique": "xr_spine_oblique",
    "standing limb alignment": "xr_limb_alignment",
    "bone age": "xr_bone_age",
    "skeletal survey": "xr_skeletal_survey",
    "shoulder special views": "xr_shoulder_special",
    "mastoid views": "xr_mastoid",
}


@pytest.mark.parametrize("label,key", sorted(REQUESTED.items()))
def test_every_requested_study_type_exists(label, key):
    assert key in XR_SUBTYPE_PACKAGES, f"{label} has no study-type package"
    p = XR_SUBTYPE_PACKAGES[key]
    assert p["title"].strip() and p["must_report"] and p["pathology"], key


def test_the_two_requested_categories_that_are_regions_are_regions():
    """Sinus radiography and pelvic bone are places, not study types."""
    assert "paranasal_sinuses" in XR_MODULES and "pelvis" in XR_MODULES
    assert not any(k.startswith("xr_sinus") or k.startswith("xr_pelvi")
                   for k in XR_SUBTYPE_PACKAGES)


def test_the_sinus_projections_are_named():
    """A finding belongs to the view that showed it, and each sinus view profiles
    different sinuses."""
    blob = " ".join(XR_MODULES["paranasal_sinuses"]["projection"])
    for view in ("Water's", "Caldwell", "lateral", "submentovertex"):
        assert view.lower() in blob.lower(), f"{view} not named"
    assert "ERECT" in blob, "the erect requirement for an air-fluid level was lost"


def test_radiography_has_its_own_subtype_library_and_ultrasound_keeps_its_own():
    assert len(TM.known_subtypes("RADIOLOGY")) == 18
    assert len(TM.known_subtypes("SONOGRAPHY")) == 9
    assert TM.subtypes_for("RADIOLOGY", ["ob_nt"]) == []
    assert TM.subtypes_for("SONOGRAPHY", ["xr_bone_age"]) == []


@pytest.mark.parametrize("key,probe", [
    ("xr_colon_transit", "protocol"),
    ("xr_limb_alignment", "weight-bearing"),
    ("xr_bone_age", "chronological age"),
    ("xr_skeletal_survey", "indication"),
    ("xr_hsg", "spill"),
    ("xr_rug", "reflux"),
    ("xr_ivp", "nephrogram"),
    ("xr_barium_enema", "double-contrast"),
    ("xr_fistulography", "internal opening"),
    ("xr_nasal_bone", "clinical"),
    ("xr_spine_flexion_extension", "instability"),
    ("xr_mastoid", "pneumatisation"),
])
def test_each_study_type_carries_its_defining_content(key, probe):
    p = XR_SUBTYPE_PACKAGES[key]
    blob = " ".join(p["technique"] + p["must_report"] + p["pathology"]).lower()
    assert probe.lower() in blob, f"{key}: {probe!r} missing"


@pytest.mark.parametrize("key,caveat", [
    ("xr_colon_transit", "never be read against a different one"),
    ("xr_limb_alignment", "disagree between sources"),
    ("xr_bone_age", "not interchangeable"),
    ("xr_spine_flexion_extension", "vary"),
])
def test_a_protocol_dependent_value_is_never_read_against_another_protocol(key, caveat):
    """Colon transit has at least four protocols with different marker counts, film days
    and thresholds. Lower-limb alignment normals disagree between three sources. Bone age
    differs by method. None of those numbers transfer."""
    blob = " ".join(XR_SUBTYPE_PACKAGES[key]["technique"]
                    + XR_SUBTYPE_PACKAGES[key]["pathology"]).lower()
    assert caveat.lower() in blob, f"{key}: missing the caveat {caveat!r}"


@pytest.mark.parametrize("key", sorted(REQUESTED.values()))
def test_xr_subtype_pathology_is_in_preserve_register(key):
    produce = ("specify ", "calculate ", "measure ", "estimate ", "assign a", "compute ")
    keep = ("preserve", "never", "do not", "he gave", "he stated", "he used",
            "he made", "he measured", "he described", "he assigned", "he counted",
            "he calculated", "he selected", "he identified", "he could", "his ")
    for line in XR_SUBTYPE_PACKAGES[key]["pathology"]:
        low = line.lower()
        assert not any(low.startswith(v) for v in produce), f"{key}: produce: {line}"
        assert any(w in low for w in keep), f"{key}: no preservation clause: {line}"


def test_a_study_type_renders_after_the_region_and_only_when_selected(monkeypatch):
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "1")
    with_sub = tp.build_turbo_system_prompt(
        "RADIOLOGY", "", profile={"regions": ["abdomen"], "subtype": "xr_barium_enema"})
    assert with_sub.index("# REPORTING CONTEXT") < with_sub.index("# STUDY TYPE")
    assert "Barium enema" in with_sub
    without = tp.build_turbo_system_prompt("RADIOLOGY", "", profile={"regions": ["abdomen"]})
    assert "# STUDY TYPE" not in without


def test_the_subtype_libraries_do_not_leak_into_each_other():
    for key in XR_SUBTYPE_PACKAGES:
        assert key.startswith("xr_"), key
    from modules.EchoMind.viewer_chat.turbo_us_modules import US_SUBTYPE_PACKAGES
    assert not set(XR_SUBTYPE_PACKAGES) & set(US_SUBTYPE_PACKAGES)


def test_the_authored_subtype_file_declares_its_provenance():
    p = os.path.join(_ROOT, "tools", "dev", "turbo_xr_subtypes.py")
    src = io.open(p, encoding="utf-8-sig").read()
    assert "CLINICAL REVIEW REQUIRED" in src
    assert "SOURCES" in src
    assert "NOT subtypes" in src, "the region-vs-subtype decision must be recorded"
