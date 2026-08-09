"""Guard: the prompt template and its region modules (2026-08-09).

The prompt this replaces grew by accretion — measured on the CT branch: 23 emphasis
markers, the same rule stated 2–3×, 13% leading whitespace, and no statement anywhere
of what job the model was doing. The template fixes the SHAPE so a future failure adds
a line to a named slot instead of another paragraph wherever it seemed to fit.

It is OFF by default. It replaces the whole prompt rather than narrowing spans inside
one, so it is a behaviour change and must be evaluated before it is switched on.
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

from modules.EchoMind.session_metadata import REGION_KEYS                 # noqa: E402
from modules.EchoMind.viewer_chat import turbo_prompt as tp               # noqa: E402
from modules.EchoMind.viewer_chat import turbo_template as T              # noqa: E402
from modules.EchoMind.viewer_chat.turbo_region_modules import (           # noqa: E402
    REGION_MODULES, module_for, modules_for)

SLOTS = (T.ROLE, T.PRECEDENCE, T.TWO_HALVES, T.RULES_PATHOLOGICAL,
         T.RULES_NORMAL, T.OUTPUT)


# ── 1. it is off, and nothing changed ────────────────────────────────────────

def test_the_template_is_on_by_default(monkeypatch):
    """Owner decision 2026-08-09. It shipped off while the four libraries were built."""
    monkeypatch.delenv("AIPACS_TURBO_PROMPT_V2", raising=False)
    assert T.template_v2_enabled() is True


def test_by_default_a_ct_report_uses_the_template(monkeypatch):
    monkeypatch.delenv("AIPACS_TURBO_PROMPT_V2", raising=False)
    got = tp.build_turbo_system_prompt("CT", "", profile={"regions": ["chest"]})
    assert got.startswith("# ROLE")
    assert "## Chest" in got


@pytest.mark.parametrize("off", ["0", "false", "no", "off", "OFF"])
def test_the_kill_switch_reverts_to_the_narrowed_prompt(monkeypatch, off):
    """The switch is what makes running it live reversible: one variable, effective on
    the next report, no rebuild."""
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", off)
    assert T.template_v2_enabled() is False
    got = tp.build_turbo_system_prompt("CT", "", profile={"regions": ["chest"]})
    assert "SOURCE FIDELITY" in got, "this is not the existing prompt"
    assert "# ROLE" not in got, "the template rendered despite the kill switch"


def test_with_the_flag_on_the_template_renders(monkeypatch):
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "1")
    got = tp.build_turbo_system_prompt("CT", "", profile={"regions": ["chest"]})
    assert got.startswith("# ROLE")
    assert "# OUTPUT" in got


def test_a_region_with_no_module_falls_back_to_narrowing(monkeypatch):
    """Rendering a REPORTING CONTEXT with nothing in it would be worse than the
    narrowed prompt, so the template declines rather than degrades."""
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "1")
    got = tp.build_turbo_system_prompt("CT", "", profile={"regions": ["obstetric"]})
    assert "# ROLE" not in got


# ── 2. the shape the template exists to enforce ──────────────────────────────

def test_the_prompt_states_the_task_in_its_first_lines():
    """The prompt this replaces never said what job it was: 'radiology report',
    'You are' and 'TASK' were all absent, and the first line was a formatting rule."""
    head = T.ROLE.split("\n")[:6]
    joined = " ".join(head).lower()
    assert "radiologist" in joined
    assert "report" in joined


def test_the_slots_appear_in_the_fixed_order():
    p = T.render(modality="CT",
                 study_facts=[("Modality", "CT", "DICOM")],
                 modules=modules_for(["chest"]))
    order = ["# ROLE", "# PRECEDENCE", "# THE TWO HALVES", "# RULES — PATHOLOGICAL",
             "# RULES — NORMAL", "# MODALITY", "# STUDY CONTEXT",
             "# REPORTING CONTEXT", "# OUTPUT"]
    at = [p.find(s) for s in order]
    assert all(i >= 0 for i in at), [s for s, i in zip(order, at) if i < 0]
    assert at == sorted(at), "the slots are out of order"


def test_the_output_contract_is_last():
    p = T.render(modality="CT", study_facts=[("Modality", "CT", "DICOM")],
                 modules=modules_for(["chest"]))
    assert p.rstrip().endswith("Start with { and end with }.")


def test_no_emphasis_inflation_in_the_shared_slots():
    """23 markers in the prompt this replaces — one every 17 lines. When a third of
    the sections announce themselves as critical, the marker stops carrying
    information."""
    text = "\n".join(SLOTS)
    found = [m for m in ("MANDATORY", "CRITICAL", "NON-NEGOTIABLE", "HARD RULE",
                         "READ FIRST", "ABSOLUTE", "FORBIDDEN")
             if re.search(r"\b" + m + r"\b", text)]
    assert not found, f"emphasis markers crept back in: {found}"


def test_no_rule_is_stated_twice_in_the_shared_slots():
    text = "\n".join(SLOTS)
    for phrase in ("never report the same structure twice",
                   "The imaging modality is",
                   "Report features, not verdicts"):
        assert text.count(phrase) <= 1, f"{phrase!r} appears more than once"


def test_the_shared_slots_are_not_indented_prose():
    """13% of the old prompt was leading whitespace from a triple-quoted string."""
    text = "\n".join(SLOTS)
    ws = sum(len(l) - len(l.lstrip()) for l in text.split("\n"))
    assert ws / max(len(text), 1) < 0.06


# ── 3. every rule that exists because of a real failure survived ────────────

@pytest.mark.parametrize("probe", [
    "The liver is normal.",                 # the verdict-not-features failure
    "کد طبیعی",                             # the normal-template trigger
    "دگنش",                                 # the corrupted trigger, verbatim
    "No pathological findings are identified.",
    "may represent",                        # hedge preservation
    "Right occipital lobe",                 # laterality preservation
    "never invent one",                     # the measurement rule
    "Never infer the patient's sex",
    "no code fences",
])
def test_load_bearing_rules_survived_the_rewrite(probe):
    text = "\n".join(SLOTS)
    assert probe in text, f"{probe!r} was lost in the rewrite"


def test_the_json_keys_match_the_validator():
    from modules.EchoMind.viewer_chat import openai_reporter  # noqa: F401
    for key in ("Report Title", "Pathological Findings", "Normal Findings",
                "Impression", "Recommendations"):
        assert f'"{key}"' in T.OUTPUT


# ── 4. the region modules ────────────────────────────────────────────────────

def test_every_module_key_is_canonical():
    for k in REGION_MODULES:
        assert k in REGION_KEYS, f"{k!r} is not a canonical region key"


def test_every_module_has_all_five_sections():
    for key, m in REGION_MODULES.items():
        assert m["title"].strip(), f"{key}: no title"
        assert m["headings"].strip(), f"{key}: no headings"
        assert isinstance(m["pathology"], list)
        assert m["normal"], f"{key}: no normal-findings reference"
        assert isinstance(m["terms"], list)
        assert isinstance(m["notes"], list)


def test_no_module_lost_its_clinical_depth():
    for key, m in REGION_MODULES.items():
        assert len(m["normal"]) >= 5, f"{key} has only {len(m['normal'])} normal lines"
        for line in m["normal"]:
            assert line == line.strip(), f"{key}: un-stripped line"
            assert not line.startswith("•"), f"{key}: bullet marker left in"


def test_shared_titles_share_one_module():
    """`pelvis` and `prostate` must not both emit the pelvis package."""
    mods = modules_for(["pelvis", "prostate"])
    assert len(mods) == 1
    assert modules_for(["head_neck", "thyroid"]) == modules_for(["head_neck"])


def test_each_region_ships_one_self_contained_package():
    """The gate is the source of this slot: one block per region, in gate order, each
    carrying its own headings, normal reference, terms and notes."""
    ctx = T.render_region_context(modules_for(["chest", "abdomen"]))
    assert ctx.count("# REPORTING CONTEXT") == 1
    assert 0 < ctx.index("## Chest") < ctx.index("## Abdomen")
    for block in ("Headings, in this order", "Normal-findings reference"):
        assert ctx.count(block) == 2, f"{block!r} should appear once per region"


def test_the_region_list_is_not_restated_in_the_context_header():
    """'# REPORTING CONTEXT - chest, abdomen' repeated what the blocks below name.
    One statement of the region set, as a fact with provenance, in STUDY CONTEXT."""
    ctx = T.render_region_context(modules_for(["chest", "abdomen"]))
    assert ctx.splitlines()[0] == "# REPORTING CONTEXT"


def test_dictation_terms_are_not_repeated_across_regions():
    """The always-on terms reach the model once, not once per gated region."""
    ctx = T.render_region_context(modules_for(["chest", "abdomen", "pelvis"]))
    emitted = [t.strip()
               for line in ctx.splitlines() if "\u2192" in line
               for t in line.split("\u00b7")]
    assert emitted, "no dictation terms rendered at all"
    assert len(emitted) == len(set(emitted)), "a term was emitted under two regions"


def test_the_prompt_carries_exactly_one_region_content_layer():
    """The failure the slot exists to fix: the prompt it replaces spread chest and
    abdomen content across a grouping vocabulary, a measurement block and an RSNA
    block - three places that had to agree and did not."""
    p = T.render(modality="CT",
                 study_facts=[("Modality", "CT", "DICOM"),
                              ("Regions", "chest, abdomen", "auto-detected")],
                 modules=modules_for(["chest", "abdomen"]))
    assert p.count("# REPORTING CONTEXT") == 1
    assert p.count("Normal-findings reference") == 2, "once per region, nowhere else"
    assert re.search(r"Regions\s+chest, abdomen\s+\(auto-detected\)", p), \
        "the gate's conclusion should survive in STUDY CONTEXT as a fact"


def test_region_notes_stay_with_their_region_and_study_notes_do_not():
    ctx = T.render_region_context(modules_for(["chest"]),
                                  notes=["The booking names the urinary tract."])
    assert "## Notes for this study" in ctx
    assert ctx.index("## Chest") < ctx.index("## Notes for this study")


def test_the_always_on_dictation_terms_reach_every_region():
    for key in ("knee", "brain", "temporal_bone"):
        terms = " ".join(module_for(key)["terms"])
        assert "lymphadenopathy" in terms.lower()


def test_unknown_regions_render_nothing_rather_than_an_empty_block():
    assert T.render_region_context(modules_for(["not_a_region"])) == ""
    assert T.render_region_context([]) == ""


def test_study_context_only_shows_facts_it_actually_has():
    ctx = T.render_study_context([("Modality", "CT", "DICOM"),
                                  ("Contrast", "", "booking"),
                                  ("Service", None, "")])
    assert "Modality" in ctx
    assert "Contrast" not in ctx, "an empty fact was rendered as a blank row"
    assert "Service" not in ctx


def test_provenance_travels_with_each_fact():
    ctx = T.render_study_context([("Regions", "chest", "set by the physician")])
    assert "(set by the physician)" in ctx


def test_the_generator_still_exists():
    p = os.path.join(_ROOT, "tools", "dev", "gen_turbo_modules.py")
    assert os.path.exists(p), "the module generator was moved or deleted"
    assert "REGION_MODULES" in io.open(p, encoding="utf-8-sig").read()


def test_every_region_renders_a_complete_prompt():
    for key in REGION_MODULES:
        p = T.render(modality="CT",
                     study_facts=[("Modality", "CT", "DICOM"),
                                  ("Regions", key, "gate")],
                     modules=modules_for([key]))
        assert p.startswith("# ROLE") and "# OUTPUT" in p, key
        # Ceiling raised 12000 -> 13000 on 2026-08-09. The owner's decision to make
        # the regional context ADVISORY rather than a report skeleton added ~700
        # characters of standing rules to every prompt: the guidance-not-checklist
        # paragraph and the RSNA fallback. That is the fix for a hysterosalpingogram
        # being reported with a plain-abdominal-film normal template, and it is worth
        # ~175 tokens on every study. Still a sanity range, not a contract.
        assert 3000 < len(p) < 13000, f"{key}: {len(p)} chars is out of the sane range"


# ── 5. the pathological half is gated too ────────────────────────────────────

#: system -> the only regions allowed to mention it. A study gated to any other
#: region must never see the name.
SYSTEM_OWNERS = {
    "Fleischner": {"Chest"},
    "Lung-RADS": {"Chest"},
    "Bosniak": {"Abdomen"},
    "LI-RADS": {"Abdomen"},
    "ASPECTS": {"Brain"},
    "TI-RADS": {"Neck"},
    "O-RADS": {"Pelvis"},
    "PI-RADS": {"Pelvis"},
    "AO/Magerl": {"Spine", "Cervical spine", "Thoracic spine", "Lumbar spine"},
    "BI-RADS": set(),          # breast is not a CT region: no CT study may see it
    "Neer": {"Shoulder"},
    "Ideberg": {"Shoulder"},
    "Walch": {"Shoulder"},
    "Goutallier": {"Shoulder"},
    "Judet-Letournel": {"Hip"},
    "Pipkin": {"Hip"},
    "Schatzker": {"Knee"},
    "Dejour": {"Knee"},
    "Insall-Salvati": {"Knee"},
    "Sanders": {"Ankle and foot"},
    "Hawkins": {"Ankle and foot"},
    "Lauge-Hansen": {"Ankle and foot"},
    "Myerson": {"Ankle and foot"},
    "Weber level": {"Ankle and foot"},
    "Salter-Harris": {"Ankle and foot", "Extremity"},
    "Herbert": {"Wrist and hand"},
    "Frykman": {"Wrist and hand"},
    "Lund-Mackay": {"Paranasal sinuses"},
    "Keros": {"Paranasal sinuses"},
    "Le Fort": {"Maxillofacial"},
    "Zingg": {"Maxillofacial"},
    "Markowitz-Manson": {"Maxillofacial"},
}


@pytest.mark.parametrize("system,owners", sorted(SYSTEM_OWNERS.items()))
def test_a_region_never_sees_another_regions_classification_system(system, owners):
    """The point of gating the pathological half: a brain CT is not told about
    Fleischner, and an abdominal CT is not told about BI-RADS."""
    for key, m in REGION_MODULES.items():
        text = T.render_region_context([m])
        if system in text:
            assert m["title"] in owners, (
                f"{key} ({m['title']}) was shown {system}, which belongs to {owners or 'no CT region'}")


def test_the_shared_rules_no_longer_name_one_regions_system():
    """These moved into the region packages. Naming them in the shared slot would put
    them back in front of every study, which is the thing being fixed."""
    text = "\n".join(SLOTS)
    for system in ("BI-RADS", "Fleischner", "Bosniak", "Balthazar", "PI-RADS"):
        assert system not in text, f"{system} is back in the shared rules"
    assert "never invent one" in text, "the safety rule itself must survive"
    assert "REPORTING CONTEXT" in T.RULES_PATHOLOGICAL, "no pointer to the gated systems"


@pytest.mark.parametrize("key", sorted(k for k, m in REGION_MODULES.items()
                                       if m["pathology"]))
def test_pathology_rules_preserve_rather_than_produce(key):
    """The source bullets were imperatives to PRODUCE - "specify volume (ABC/2 method)".
    The physician dictates; he cannot dictate a volume he did not measure, and source
    fidelity forbids the model inventing one. Every line must read as preservation."""
    produce = ("specify ", "calculate ", "measure ", "estimate ", "assign a", "compute ")
    for line in REGION_MODULES[key]["pathology"]:
        low = line.lower()
        assert not any(low.startswith(v) for v in produce), f"{key}: produce-register: {line}"
        assert any(w in low for w in ("preserve", "he dictated", "he gave", "he named",
                                      "as dictated", "only when", "never assign",
                                      "standardise", "unless he")), \
            f"{key}: no preservation clause: {line}"


def test_the_region_block_carries_both_halves_in_report_order():
    ctx = T.render_region_context(modules_for(["chest"]))
    assert ctx.index("Pathological findings") < ctx.index("Normal-findings reference")


def test_a_region_with_no_authored_pathology_renders_no_empty_heading():
    """Every canonical region has rules today, but a new one is added empty and must
    not render a bare heading on its way in."""
    stub = {"title": "Stub", "headings": "A * B", "pathology": [],
            "normal": ["Structure is intact."], "terms": [], "notes": []}
    ctx = T.render_region_context([stub])
    assert "Pathological findings" not in ctx
    assert "Normal-findings reference" in ctx


def test_gating_the_pathological_half_shrinks_the_prompt_it_replaces():
    """The 15 bullets went to every CT study. No region now carries more than its own."""
    from modules.EchoMind.viewer_chat.openai_reporter import build_report_system_prompt
    shared = build_report_system_prompt("CT", "")
    assert "CT-SPECIFIC MEASUREMENT AND CLASSIFICATION RULES" in shared, \
        "the source block moved; re-check what the region packages were derived from"
    worst = max(len(m["pathology"]) for m in REGION_MODULES.values())
    assert worst <= 9, f"a single region carries {worst} rules; the source block had 15"


# ── 6. the researched region content ─────────────────────────────────────────

def test_every_region_now_has_pathology_rules():
    """Ten regions had none - the MSK group, sinuses, temporal bone, orbit,
    maxillofacial - because the prompt this grew from never wrote any for them."""
    empty = sorted(k for k, m in REGION_MODULES.items() if not m["pathology"])
    assert not empty, f"regions still without pathology rules: {empty}"


def test_no_region_is_left_with_a_thin_normal_reference():
    thin = {k: len(m["normal"]) for k, m in REGION_MODULES.items()
            if len(m["normal"]) < 8}
    assert not thin, f"normal-findings reference too thin: {thin}"


#: (region, measurement, the caveat that must travel with it).
#: Published normal ranges genuinely disagree for each of these. Encoding one side
#: silently would produce a confidently wrong report, so the line must name the
#: measurement and hand the interpretation back to the physician.
CONTESTED = [
    ("ankle_foot", "Gissane", "more than one published normal range"),
    ("knee", "Insall-Salvati", "differ between sources"),
    ("temporal_bone", "vestibular aqueduct", "plane"),
    ("hip", "version", "measurement method"),
    ("hip", "centre-edge", "more than one published normal range"),
    ("orbit", "enophthalmos", "reference plane"),
    ("shoulder", "bone loss", "never convert"),
]


@pytest.mark.parametrize("region,measurement,caveat", CONTESTED)
def test_a_contested_threshold_is_never_encoded_as_a_bare_number(region, measurement,
                                                                 caveat):
    lines = [l for l in REGION_MODULES[region]["pathology"]
             if measurement.lower() in l.lower()]
    assert lines, f"{region}: no pathology line mentions {measurement!r}"
    assert any(caveat.lower() in l.lower() for l in lines), (
        f"{region}: {measurement!r} is stated without the caveat {caveat!r}; "
        f"published normal ranges for it disagree")


def test_the_researched_content_declares_its_provenance():
    """It came from the literature, not from a radiologist on this project, and the
    file has to say so where the editing happens."""
    p = os.path.join(_ROOT, "tools", "dev", "turbo_region_authored.py")
    assert os.path.exists(p), "the researched content file was moved or deleted"
    src = io.open(p, encoding="utf-8-sig").read()
    assert "CLINICAL REVIEW REQUIRED" in src
    assert "has NOT been read by a radiologist" in src
    assert "SOURCES" in src


def test_researched_content_cannot_silently_overwrite_authored_content():
    """The generator raises rather than letting the literature win over a rule a
    radiologist wrote for this project."""
    src = io.open(os.path.join(_ROOT, "tools", "dev", "gen_turbo_modules.py"),
                  encoding="utf-8-sig").read()
    assert "researched content would overwrite authored" in src
