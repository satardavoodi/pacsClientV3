"""Guard: the generated Normal Findings are RSNA-shaped, organ by organ, and the
physician's "normal report" request is obeyed (2026-08-07).

THE REPORT THAT CAUSED THIS. Patient 53516, CT chest+abdomen, Turbo/gpt-5.6-terra.
The physician dictated «دیگه‌اش هم کد طبیعی بیاد» — bring the normal report for the
rest — and received:

    "No gross focal abnormality is identified in the liver, gallbladder and biliary
     tree, pancreas, spleen, adrenal glands, kidneys and ureters, bowel, peritoneum,
     vessels, or abdominal lymph nodes."

One hedged line standing in for eleven organs. Three prompt causes, fixed together:

  1. The definitive-normal escape was PERMISSIVE ("you MAY") competing with a
     DIRECTIVE default, and listed only English triggers. The Persian idiom — and its
     speech-to-text corruption «دگنش» — was never recognised as the request.
  2. No instruction anywhere asked for one statement per organ. The register's own
     example was the lumped form, and MODALITY LOGIC (CT) adds "concise, non-redundant".
  3. "RSNA-style normal structure" was named but never shown.

These tests pin all three, for every modality, on both the template and no-template
paths. They are text assertions on the built prompt because that is exactly what
regressed: prompt text, silently, with no code change and no exception.
"""

import ast
import os
import typing

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
_REPORTER = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "openai_reporter.py")
_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")

# Every modality the UI offers, plus the generic fallback.
MODALITIES = ["CT", "MRI", "SONOGRAPHY", "OBSTETRIC ULTRASOUND",
              "RADIOLOGY", "MAMOGRAPHY", ""]


def _build():
    """Exec the prompt builder out of the source — the module itself is Qt-heavy.
    Same harness as the other prompt guards."""
    with open(_REPORTER, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.split("\n")
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == "build_report_system_prompt")
    ns = {"_to_str": lambda x: "" if x is None else str(x),
          "Optional": typing.Optional, "Dict": dict, "Any": object}
    exec(compile("\n".join(lines[node.lineno - 1:node.end_lineno]), _REPORTER, "exec"), ns)
    return ns["build_report_system_prompt"]


@pytest.fixture(scope="module")
def prompt():
    return _build()


# ── 1. the request is obeyed, not merely permitted ───────────────────────────

@pytest.mark.parametrize("modality", MODALITIES)
def test_the_normal_report_request_is_directive(prompt, modality):
    """A permissive clause loses to a directive default every time. The physician
    asked for the normal report and got hedged text, which he then has to rewrite
    by hand — the opposite of the point."""
    p = prompt(modality, "")
    assert "THE NORMAL-REPORT REQUEST" in p
    i = p.index("THE NORMAL-REPORT REQUEST")
    assert "MUST switch to DEFINITIVE" in p[i:i + 500], (
        "the definitive-normal switch is not stated as a requirement"
    )


@pytest.mark.parametrize("modality", MODALITIES)
def test_the_old_permissive_wording_is_gone(prompt, modality):
    assert "you MAY state definitive" not in prompt(modality, ""), (
        "the permissive escape is back — it is the reason 53516 came out hedged"
    )


@pytest.mark.parametrize("phrase", [
    "کد طبیعی", "کد نرمال", "تمپلیت نرمال", "نرمال بیاد",
    "بقیه طبیعی", "مابقی طبیعی",
])
def test_the_persian_triggers_are_named(prompt, phrase):
    """The physician dictates in Persian. Triggers described only in English idiom
    ('says the rest is normal') are not matchable against what he actually says."""
    assert phrase in prompt("CT", ""), f"trigger {phrase!r} is not in the prompt"


def test_a_corrupted_trigger_is_taught_by_example(prompt):
    """The transcription is speech-to-text over medical Persian and mangles terms —
    in this one dictation it produced دگنش / ماده حاجه / این گوییناد. The rule has to
    survive that, so the real corrupted form is shown verbatim."""
    p = prompt("CT", "")
    assert "دگنش هم کد طبیعی بیاد" in p
    assert "INTENT" in p[p.index("THE NORMAL-REPORT REQUEST"):], (
        "nothing tells the model to match on intent rather than spelling"
    )


@pytest.mark.parametrize("modality", MODALITIES)
def test_definitive_normals_are_still_bound_by_source_fidelity(prompt, modality):
    """Switching register must not switch off the safety rule. A definitive normal
    for a structure the dictated pathology involves is the one failure this whole
    feature must never produce."""
    p = prompt(modality, "")
    seg = p[p.index("THE NORMAL-REPORT REQUEST"):]
    assert "SOURCE FIDELITY still governs" in seg


# ── 2. one statement per organ ───────────────────────────────────────────────

@pytest.mark.parametrize("modality", MODALITIES)
@pytest.mark.parametrize("template", ["", "Lungs: clear.\nHeart: normal in size."])
def test_granularity_rule_reaches_every_prompt(prompt, modality, template):
    """It lives in the shared REPORT ORGANIZATION block precisely so it governs both
    findings sections, every modality, and both the template and no-template paths."""
    assert "GRANULARITY — ONE STATEMENT PER ORGAN" in prompt(modality, template)


def test_the_granularity_rule_shows_the_actual_failure(prompt):
    """An abstract 'be granular' is ignorable. The rule quotes the exact sentence the
    model produced, so the model can recognise the shape it must not emit."""
    p = prompt("CT", "")
    i = p.index("GRANULARITY — ONE STATEMENT PER ORGAN")
    seg = p[i:i + 1200]
    assert "gallbladder and" in seg and "peritoneum" in seg, "the counter-example is gone"
    assert "NOT acceptable output" in seg


def test_granularity_does_not_license_padding(prompt):
    """The opposite failure: inventing organs to make more lines. A heading or a
    normal statement is a claim that the structure was examined."""
    p = prompt("CT", "")
    i = p.index("GRANULARITY — ONE STATEMENT PER ORGAN")
    assert "never invent an organ the study did not cover" in p[i:i + 1200]


# ── 3. the RSNA form is shown, not just named ────────────────────────────────

@pytest.mark.parametrize("modality", MODALITIES)
def test_rsna_structure_is_required_when_no_template(prompt, modality):
    p = prompt(modality, "")
    assert "RSNA STRUCTURE" in p
    i = p.index("RSNA STRUCTURE")
    assert "ONE LINE PER ORGAN OR STRUCTURE GROUP" in p[i:i + 500]


def test_the_worked_example_is_guarded_against_being_copied(prompt):
    """An example of a normal chest+abdomen is one careless copy away from becoming the
    report for a knee. It must read as FORM, never as content."""
    p = prompt("CT", "")
    i = p.index("WORKED EXAMPLE")
    seg = p[i:i + 2600]
    assert "FEATURE DEPTH AND PHRASING ONLY" in seg
    assert "Do NOT copy its organ list" in seg
    assert "drop any organ" in seg
    assert "drop every enhancement clause if no" in seg, (
        "the example is contrast-enhanced; nothing tells the model to strip the "
        "enhancement wording on a non-contrast study"
    )


def _example_bullets(p):
    """The example's bullets, with wrapped continuation lines rejoined."""
    i = p.index("WORKED EXAMPLE")
    seg = p[i:p.index("What this example is teaching", i)]
    out = []
    for line in seg.split("\n"):
        s = line.strip()
        if s.startswith("- "):
            out.append(s[2:])
        elif out and s and not s.endswith(":") and line.startswith("      "):
            out[-1] += " " + s
    return out


# the failure this whole change exists to prevent was eleven of these in one sentence
_ORGANS = ["liver", "gallbladder", "pancreas", "spleen", "adrenal", "kidney",
           "bowel", "bladder", "uterus", "prostate", "lung", "heart"]


def test_the_example_never_lumps_organs(prompt):
    """If the example itself lumped organs it would teach the failure it exists to
    prevent — the previous version really did ('Pancreas, spleen and adrenal glands
    are unremarkable': three organs, zero features)."""
    bullets = _example_bullets(prompt("CT", ""))
    assert len(bullets) >= 15, f"the example collapsed to {len(bullets)} bullets"
    for b in bullets:
        named = {o for o in _ORGANS if o in b.lower()}
        assert len(named) <= 2, f"one line covers {sorted(named)}: {b!r}"


@pytest.mark.parametrize("organ,features", [
    ("Liver", ["attenuation", "focal lesion", "biliary"]),
    ("Bowel", ["caliber", "obstruction", "mass"]),
    ("Kidneys", ["size", "hydronephrosis"]),
    ("Pancreas", ["ductal dilatation"]),
])
def test_the_example_shows_features_not_verdicts(prompt, organ, features):
    """The point of the example is DEPTH. A line reading 'Liver is normal.' would
    satisfy the granularity rule and still be useless to a referring clinician."""
    bullets = _example_bullets(prompt("CT", ""))
    line = next((b for b in bullets if b.lower().startswith(organ.lower())), None)
    assert line, f"the {organ} line is gone from the example"
    for f in features:
        assert f in line.lower(), f"{organ} line no longer reports {f!r}: {line!r}"


@pytest.mark.parametrize("modality", MODALITIES)
def test_no_template_guidance_never_leaks_into_the_template_path(prompt, modality):
    """When the physician supplies their own template, THEIR structure governs. The
    generation rules — and especially a worked example of someone else's normal
    report — must not appear and compete with it."""
    p = prompt(modality, "Lungs: clear.\nHeart: normal in size.")
    for leaked in ("THE NORMAL-REPORT REQUEST", "RSNA STRUCTURE", "WORKED EXAMPLE"):
        assert leaked not in p, f"{leaked} leaked into the with-template prompt"


# ── 3b. Normal Findings is a GENERATION task with a procedure ────────────────

@pytest.mark.parametrize("modality", MODALITIES)
def test_the_construction_procedure_is_ordered_and_complete(prompt, modality):
    """Pathological Findings is transcription; Normal Findings is generation. The
    generation half needs an actual procedure — establish the exam, build the full
    checklist, write features, subtract the pathology, group — or the model improvises
    and improvising trends short."""
    p = prompt(modality, "")
    assert "NORMAL FINDINGS CONSTRUCTION — a GENERATION task" in p
    seg = p[p.index("NORMAL FINDINGS CONSTRUCTION — a GENERATION task"):][:2200]
    for step in ("STUDY TYPE", "MODALITY", "CONTRAST",
                 "COMPLETE normal checklist", "IMAGING FEATURES", "SUBTRACT"):
        assert step in seg, f"the construction procedure is missing {step!r}"


@pytest.mark.parametrize("modality", MODALITIES)
def test_subtraction_is_an_explicit_step(prompt, modality):
    """The same structure appearing as both normal and abnormal is the one output a
    radiologist cannot sign. It was implied by SOURCE FIDELITY; now it is a numbered
    step in the procedure that builds the section."""
    p = prompt(modality, "")
    seg = p[p.index("NORMAL FINDINGS CONSTRUCTION — a GENERATION task"):][:2200]
    assert "NEVER appear as both normal and abnormal" in seg


@pytest.mark.parametrize("modality", MODALITIES)
def test_bare_verdicts_are_banned(prompt, modality):
    """'The liver is normal.' passes every earlier rule — it is one line, one organ,
    correctly grouped — and still tells the referring clinician nothing."""
    p = prompt(modality, "")
    assert "REPORT FEATURES, NOT VERDICTS" in p
    # collapse whitespace: the prompt is hard-wrapped, so phrases straddle line breaks
    seg = " ".join(p[p.index("REPORT FEATURES, NOT VERDICTS"):][:1400].split())
    assert "'The liver is normal.'" in seg and "'The bowel is normal.'" in seg, (
        "the counter-examples are gone — an abstract rule is ignorable"
    )
    assert "no intrahepatic biliary ductal dilatation" in seg, (
        "the worked liver features are gone, so 'relevant features' is undefined"
    )


@pytest.mark.parametrize("modality", MODALITIES)
def test_completeness_is_scaled_to_the_study_not_a_word_count(prompt, modality):
    """The guard against this change's own failure mode. A completeness rule stated as
    length would pad a single-digit radiograph — and RADIOLOGY separately, correctly,
    says a one-or-two-line Normal Findings is expected there."""
    p = prompt(modality, "")
    assert "COMPLETENESS IS MEASURED AGAINST THE ANATOMY THE STUDY COVERS" in p
    seg = p[p.index("COMPLETENESS IS MEASURED AGAINST THE ANATOMY THE STUDY COVERS"):][:700]
    assert "never pad a small study" in seg
    assert "never compress a large one" in seg


def test_the_radiograph_do_not_pad_rule_survived(prompt):
    """Pinned explicitly: this change must not have overridden it."""
    assert "do NOT pad it" in prompt("RADIOLOGY", "")


def test_the_obstetric_single_sentence_design_survived(prompt):
    """OB is the deliberate exception — its organ-by-organ work lives in the ISUOG
    'Anatomy Survey' key, so its Normal Findings really is one sentence. A blanket
    'be complete' sweep would have broken it."""
    p = prompt("OBSTETRIC ULTRASOUND", "")
    assert "Single sentence" in p or "single sentence" in p


@pytest.mark.parametrize("modality", MODALITIES)
def test_contrast_governs_enhancement_claims(prompt, modality):
    """Describing enhancement on a non-contrast study is a fabricated observation —
    the same class of error as inventing a finding."""
    p = prompt(modality, "")
    assert "CONTRAST governs what you may say" in p
    seg = p[p.index("CONTRAST governs what you may say"):][:800]
    assert "WITHOUT contrast, say nothing about" in seg
    assert "do\n  not guess" in seg or "do not guess" in seg


# ── 3c. the compression pressure is gone ─────────────────────────────────────

@pytest.mark.parametrize("modality", ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY"])
def test_no_bare_concise_instruction_steers_normal_findings(prompt, modality):
    """These four branches each carried a 'concise, non-redundant' instruction with
    nothing balancing it, so the whole cluster read as 'keep it short'. Anti-redundancy
    is correct and stays; the brevity pressure had to go."""
    p = prompt(modality, "")
    for banned in ("concise, non-redundant",
                   "grouped, concise, non-redundant",
                   "concise, grouped, non-redundant",
                   "Keep it concise but complete"):
        assert banned not in p, f"{modality}: compression cue is back: {banned!r}"


@pytest.mark.parametrize("modality", ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY"])
def test_non_redundancy_is_kept_and_defined(prompt, modality):
    """Dropping 'concise' must not drop the real rule underneath it."""
    p = prompt(modality, "")
    assert "non-redundant" in p
    assert "never report the same structure twice" in p or "same structure twice" in p


# ── 4. the run records which register it was in ──────────────────────────────

def test_turbo_logs_whether_a_template_was_attached():
    """Diagnosing 53516 meant inferring the template state from the output's wording,
    because the run never recorded it."""
    with open(_PAGES, encoding="utf-8") as fh:
        src = fh.read()
    i = src.index('"[Turbo] sending backend=')
    seg = src[i:i + 700]
    assert "normal_template=%s" in seg, "the Turbo log line does not record template state"
    assert "normal_template else" in seg, "no value is actually passed for it"
