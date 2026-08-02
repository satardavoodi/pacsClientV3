"""Guard: the Normal Template workflow — the physician's own template + their dictation.

The feature
-----------
A physician uploads their own normal-report templates. When generating a report
they dictate ONLY the pathology; the selected template supplies the structure and
every normal statement. The model must merge the two: pathology inside their
template, with only the normal statements that CONFLICT with the dictation edited
or removed.

The worked case that drove this review (2026-08-01):

    template : "Both menisci demonstrate normal morphology and signal intensity."
    dictated : "there is a tear of the lateral meniscus"
    expected : Normal Findings keeps "The medial meniscus demonstrates normal
               morphology and signal intensity."; the lateral meniscal tear is
               reported as pathology.

What was wrong
--------------
* The template was interpolated into the system prompt as a BARE, UNLABELLED
  block between two instruction blocks. `TEMPLATE LOGIC` referred to "the
  provided normal_template" — a phrase that pointed at nothing the model could
  identify. It is now fenced, like `correction()` has always fenced its inputs.
* `TEMPLATE LOGIC` declared `{"Report Title", "Pathological Findings", "Normal
  Findings"}` as "the standard JSON schema". Every modality branch declares its
  own key set, so a mammogram with a template was told to emit 3 keys AND 6 keys
  in the same prompt — and since output validation went live for all modalities
  (2026-08-01) the 3-key answer no longer renders partially, it RAISES.
* There was no rule at all for partially-abnormal paired or grouped structures,
  no rule that a dictated finding outranks a template sentence, and a rule
  ("DO NOT include any anatomical regions not present in the provided template")
  that read as licence to DROP dictated pathology the template did not cover.
"""

import ast
import importlib
import os

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_VIEWER_CHAT = os.path.normpath(
    os.path.join(_THIS, "..", "..", "..", "modules", "EchoMind", "viewer_chat")
)
_REPORTER_PY = os.path.join(_VIEWER_CHAT, "openai_reporter.py")
_PAGES_PY = os.path.join(_VIEWER_CHAT, "ai_chat_pages.py")

_UI_MODALITIES = ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY"]
_KNEE_TEMPLATE = (
    "Both menisci demonstrate normal morphology and signal intensity.\n"
    "The anterior and posterior cruciate ligaments are intact.\n"
    "No joint effusion."
)

# The old line that made a template-bearing mammography prompt self-contradictory.
_OLD_SCHEMA_CLAIM = (
    'standard JSON schema: { "Report Title", "Pathological Findings", '
    '"Normal Findings" }'
)


@pytest.fixture(scope="module")
def rep():
    return importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")


def _src(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ─────────────────────────────────────────────────────────────────────────────
# 1. The template is FENCED, and only when there is one
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("modality", _UI_MODALITIES)
def test_the_template_is_fenced_and_verbatim(modality, rep):
    sp = rep.build_report_system_prompt(modality, _KNEE_TEMPLATE)
    fence = "===== NORMAL_TEMPLATE (the physician's own report template"
    assert fence in sp, f"{modality}: the physician's template is not delimited"
    start = sp.index(fence)
    end = sp.index("===== END NORMAL_TEMPLATE =====", start)
    inner = sp[sp.index("\n", start) + 1:end]
    assert inner.strip() == _KNEE_TEMPLATE.strip(), (
        "the template must reach the model verbatim, not reflowed or summarised"
    )


@pytest.mark.parametrize("modality", _UI_MODALITIES)
def test_no_fence_when_no_template(modality, rep):
    sp = rep.build_report_system_prompt(modality, "")
    assert "===== NORMAL_TEMPLATE (" not in sp
    assert "===== END NORMAL_TEMPLATE =====" not in sp


def test_a_template_containing_headings_cannot_be_read_as_instructions(rep):
    """A real template has its own section headings. Before the fence, those sat
    naked in the middle of the system prompt."""
    tricky = "FINDINGS:\nLiver: normal.\nIMPRESSION:\nNormal study."
    sp = rep.build_report_system_prompt("CT", tricky)
    i = sp.index("===== NORMAL_TEMPLATE (")
    j = sp.index("===== END NORMAL_TEMPLATE =====")
    assert i < sp.index("IMPRESSION:") < j, "template content escaped its fence"


# ─────────────────────────────────────────────────────────────────────────────
# 2. TEMPLATE LOGIC must not declare a key set — the modality rules own that
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("modality", _UI_MODALITIES)
def test_template_block_declares_no_key_schema(modality, rep):
    sp = rep.build_report_system_prompt(modality, _KNEE_TEMPLATE)
    assert _OLD_SCHEMA_CLAIM not in sp, (
        f"{modality}: TEMPLATE LOGIC is imposing a 3-key schema again — it "
        f"contradicts the modality rules in the same prompt"
    )
    assert "It does NOT define the JSON" in sp


def test_mammography_with_a_template_keeps_its_six_key_contract(rep):
    """The concrete regression. A mammography report is Report Title / Breast
    Composition / Pathological Findings / Normal Findings / Axillary Evaluation /
    BI-RADS Category. With a template uploaded, the prompt used to ALSO demand
    exactly three keys — and `_validate_report_json` now rejects the three-key
    answer instead of rendering it, so the physician got an error."""
    sp = rep.build_report_system_prompt("MAMOGRAPHY", _KNEE_TEMPLATE)
    assert _OLD_SCHEMA_CLAIM not in sp
    assert '"BI-RADS Category"' in sp
    assert "ALL keys MUST appear exactly as written" in sp
    # and the validator still wants those keys
    assert "BI-RADS Category" in rep._MAMMOGRAPHY_REQUIRED_KEYS


def test_obstetric_key_set_is_not_flattened_to_three_either(rep):
    sp = rep.build_report_system_prompt("SONOGRAPHY", _KNEE_TEMPLATE)
    assert _OLD_SCHEMA_CLAIM not in sp


# ─────────────────────────────────────────────────────────────────────────────
# 3. The ten rules the workflow depends on
# ─────────────────────────────────────────────────────────────────────────────

_REQUIRED_RULES = {
    "treated as the physician's own template":
        "PHYSICIAN'S OWN report template",
    "section order preserved":
        "Keep the template's SECTION ORDER",
    "terminology preserved verbatim":
        "Keep the physician's TERMINOLOGY and phrasing verbatim",
    "unmentioned structures keep their normal sentence":
        "keeps the template's normal sentence,",
    "pathology placed in the right template section":
        "Put each dictated finding in the section of the template where it belongs",
    "only conflicting normals are edited":
        "Edit or remove the template's sentence for that",
    "a template sentence never overrides dictated pathology":
        "PHYSICIAN'S DICTATION WINS",
    "partially abnormal paired/grouped structures are split":
        "PARTIAL INVOLVEMENT OF PAIRED OR GROUPED STRUCTURES",
    "pathology outside the template is still reported":
        "A gap in the template is never a reason to drop a",
    "no invented pathology":
        "Never invent pathology",
    "unrelated normals are not deleted":
        "Do not delete a normal statement the dictated pathology does not touch",
    "no invented normals or sections":
        "Do NOT add normal findings, sections or anatomy the template does not contain",
}


@pytest.mark.parametrize("rule,needle", sorted(_REQUIRED_RULES.items()))
def test_template_prompt_states_the_rule(rule, needle, rep):
    sp = rep.build_report_system_prompt("MRI", _KNEE_TEMPLATE)
    assert needle in sp, f"Normal Template prompt lost the rule: {rule}"


def test_the_paired_structure_rule_carries_the_worked_example(rep):
    """Worked examples beat prose rules — that was the finding of the whole
    prompt-stack review, so this rule ships as one."""
    sp = rep.build_report_system_prompt("MRI", _KNEE_TEMPLATE)
    block = sp[sp.index("PARTIAL INVOLVEMENT OF PAIRED"):]
    block = block[:block.index("• If the physician dictates pathology")]
    assert "Both menisci demonstrate normal morphology" in block
    assert "tear of the lateral meniscus" in block
    assert "The medial meniscus demonstrates normal morphology" in block
    # both failure modes are named, not just the right answer
    assert block.count("WRONG") == 2, "both wrong behaviours must be shown"
    assert "CORRECT" in block
    assert "bilateral" in block, "the rule must generalise beyond menisci"


def test_the_override_is_scoped_to_normal_findings_generation(rep):
    """It used to say 'You MUST ignore any internal rules or default logic' —
    broad enough for a model to read as 'ignore the rest of this prompt'."""
    sp = rep.build_report_system_prompt("MRI", _KNEE_TEMPLATE)
    assert "You MUST ignore any internal rules" not in sp
    assert "replaces the DEFAULT RSNA normal-findings generation ONLY" in sp


def test_a_template_gap_cannot_suppress_dictated_pathology(rep):
    """The old wording — 'DO NOT include any anatomical regions not present in
    the provided template' — was unscoped, so it read as licence to drop a
    dictated finding the template happened not to cover."""
    sp = rep.build_report_system_prompt("CT", _KNEE_TEMPLATE)
    assert "DO NOT include any anatomical regions not present in the provided template" not in sp
    assert "limits what may appear as NORMAL — never what may" in sp


def test_the_sex_specific_caveat_survived_the_rewrite(rep):
    sp = rep.build_report_system_prompt("CT", "Liver normal. Prostate unremarkable.")
    assert "Even if the provided template lists" in sp
    assert "NEVER output both male and female organs" in sp


# ─────────────────────────────────────────────────────────────────────────────
# 4. Both backends, one shape
# ─────────────────────────────────────────────────────────────────────────────

def test_both_backends_send_the_same_template_bearing_prompt(rep, monkeypatch):
    twin = importlib.import_module("modules.EchoMind.viewer_chat.openai_parallel_backend")
    cap = {}
    monkeypatch.setattr(twin, "_call", lambda **k: (cap.update(k), {"content": "{}", "usage": {}})[1])
    monkeypatch.setattr(twin, "_feature_prompt", lambda n: "")
    monkeypatch.setattr(twin, "_validate_report_json", lambda raw, m: raw)
    twin.reporter(user_msg="tear of the lateral meniscus", modality="MRI",
                  normal_template=_KNEE_TEMPLATE)
    assert cap["system_prompt"] == rep.build_report_system_prompt("MRI", _KNEE_TEMPLATE)
    assert "===== NORMAL_TEMPLATE (" in cap["system_prompt"]


def test_the_chatgpt_report_page_sends_text_not_qt_html():
    """`get_normal_template_text()` returns `QTextEdit.toHtml()` — a whole HTML
    document with a <style> block and a font-family span per paragraph. The
    Turbo path has always sent plain text; this path did not, so the same
    template reached the model in two different shapes."""
    src = _src(_PAGES_PY)
    tree = ast.parse(src)
    lines = src.split("\n")
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "normal_template" for t in node.targets):
            continue
        text = "\n".join(lines[node.lineno - 1: node.end_lineno])
        if "get_normal_template_text()" in text:
            bad.append(node.lineno)
    assert not bad, (
        f"normal_template assigned from the HTML getter at line(s) {bad} — "
        f"use get_normal_template_plain_text()"
    )


def test_the_plain_text_getter_is_what_reaches_the_model():
    src = _src(_PAGES_PY)
    assert src.count("get_normal_template_plain_text()") >= 3, (
        "every reporter path should read the template through the plain-text getter"
    )
