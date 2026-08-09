"""Guard: the user-approved safe reductions (2026-08-02).

A. The X-ray (RADIOLOGY) prompt no longer carries the two dated in-string
   developer-commentary blocks ("# ── 2026-08-01 ── # REMOVED … because …").
   Those were literal prompt text (compilation strips real comments, so text that
   survives into the built prompt is string content) describing already-removed
   instructions, and re-quoting the banned phrasing into the model's context. The
   REAL surrounding instructions and the live "# 3./4./5." section headers stay.

   NOTE: one real instruction — "…emulating a typist…" in the Objective line — is
   deliberately LEFT (removing it is a behaviour change, out of this scope). Only
   the commentary copy that *mentioned* it was removed. So the guard pins the
   dead-commentary markers gone, not the phrase itself.

B. The MRI Brain (Ex 1) and Spine (Ex 3) worked examples are compressed to
   skeletons: input + Pathological Findings + Impression kept (the edge-case
   lesson), the verbose "Normal Findings" enumeration shortened. Knee (Ex 2) and
   Breast (Ex 4) stay full-fidelity. All four titles remain; JSON/output rules and
   the other modalities are untouched.

Extraction harness matches the other prompt tests (the module is Qt-heavy).
"""

import os
import typing

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_REPORTER_PY = os.path.normpath(
    os.path.join(_THIS, "..", "..", "..", "modules", "EchoMind", "viewer_chat", "openai_reporter.py")
)


def _prompt_fn():
    import ast

    with open(_REPORTER_PY, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.split("\n")
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == "build_report_system_prompt")
    body = "\n".join(lines[node.lineno - 1:node.end_lineno])
    ns = {"_to_str": lambda x: "" if x is None else str(x),
          "Optional": typing.Optional, "Dict": dict, "Any": object}
    exec(compile(body, _REPORTER_PY, "exec"), ns)
    return ns["build_report_system_prompt"]


@pytest.fixture(scope="module")
def prompt():
    return _prompt_fn()


# ── A. X-ray dead-commentary removed, real instructions kept ──────────────────

def test_xray_dead_commentary_removed(prompt):
    rad = prompt("RADIOLOGY", "")
    for dead in [
        "REMOVED two instructions",
        "creative-writing scaffold",
        "highest-variance sampling",
        "the negative being asserted",
    ]:
        assert dead not in rad, f"X-ray dead commentary survived: {dead!r}"
    # the dated in-string divider is gone (a shallow real code comment may still
    # exist in the source, but must NOT be in the built prompt)
    assert "── 2026-08-01" not in rad


def test_xray_real_instructions_preserved(prompt):
    rad = prompt("RADIOLOGY", "")
    for keep in [
        "Remove any normal statement about the same anatomical",
        "If the dictation is focused",
        "ANSWER MUST STRICTLY IN ENGLISH",
        "Neutral, declarative, professional radiological register",
        "3. Language & Tone",
        "4. Absolutely",
    ]:
        assert keep in rad, f"X-ray lost a REAL instruction: {keep!r}"


def test_xray_typist_metaphor_is_now_fully_gone(prompt):
    """SUPERSEDED 2026-08-06. This originally pinned that ONLY the commentary
    copy of "emulating a typist" was removed and the real Objective instruction
    stayed (count == 1).

    The real instruction has since been removed too, deliberately: a typist
    transcribes, it does not reorganize findings into anatomical sections, so it
    contradicted the REPORT ORGANIZATION rule — and GPT-5.6 treats contradictory
    instructions as destabilising. The Objective's INTENT (transcribe, translate,
    formal professional register) is preserved in the replacement wording.
    """
    rad = prompt("RADIOLOGY", "")
    assert "typist" not in rad, "the metaphor must not come back"
    assert "Objective: Transcribe and translate" in rad, "the real intent must remain"
    assert "formal, professional radiological register" in rad


# ── B. MRI examples: Brain+Spine skeletonised, Knee+Breast full ───────────────

def test_all_four_mri_examples_still_present(prompt):
    mri = prompt("MRI", "")
    for title in [
        "MRI of the Brain With and Without Contrast, Including DWI and MR Spectroscopy",
        "MRI of the Right Knee Joint Without Contrast",
        "MRI of the Lumbar Spine Without Contrast",
        "MRI of Both Breasts With Contrast",
    ]:
        assert mri.count(title) == 1, f"example changed count: {title}"


def test_brain_and_spine_normal_findings_compressed(prompt):
    mri = prompt("MRI", "")
    # new skeleton phrasing present
    assert "Remaining structures (paranasal sinuses, mastoid air cells, skull base" in mri
    assert "Remaining structures (alignment, spinal canal, neural foramina" in mri
    # old verbose enumerations gone
    assert "Sinuses and Skull Base:\\n * Paranasal sinuses and mastoid air cells are clear" not in mri
    assert "Facet Joints:\\n * Normal alignment and no hypertrophic changes" not in mri


def test_knee_and_breast_examples_stay_full(prompt):
    """The two Essential examples keep their full Normal Findings."""
    mri = prompt("MRI", "")
    # Knee: the paired-structure teaching line
    assert "Meniscal segments other than those described above show no tear" in mri
    # Breast: the full normal enumeration
    assert "Pectoralis muscles are normal in appearance with no abnormal enhancement" in mri


# ── nothing essential was collateral damage ──────────────────────────────────

def test_json_and_additions_and_other_modalities_intact(prompt):
    for m in ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY"]:
        assert "OUTPUT FORMAT (STRICT)" in prompt(m, ""), f"{m}: OUTPUT FORMAT lost"
    assert "REGEX-LOCKED JSON SCHEMA" in prompt("MAMOGRAPHY", "")
    assert "BI-RADS" in prompt("MAMOGRAPHY", "")
    assert "ISUOG" in prompt("SONOGRAPHY", "")
    for m in ["CT", "MRI"]:
        sp = prompt(m, "")
        assert "Preserve the physician's degree of certainty exactly" in sp
        assert "STANDARDIZED SYSTEMS — use them" in sp
        assert "SOURCE FIDELITY — the medical content comes only from the physician." in sp


def test_both_backends_still_identical(monkeypatch):
    import importlib

    rep = importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")
    twin = importlib.import_module("modules.EchoMind.viewer_chat.openai_parallel_backend")
    cap = {}
    monkeypatch.setattr(twin, "_call", lambda **k: (cap.update(k), {"content": "{}", "usage": {}})[1])
    monkeypatch.setattr(twin, "_feature_prompt", lambda n: "")
    monkeypatch.setattr(twin, "_validate_report_json", lambda raw, m: raw)
    twin.reporter(user_msg="x", modality="RADIOLOGY")
    assert cap["system_prompt"] == rep.build_report_system_prompt("RADIOLOGY", "")
    assert "REMOVED two instructions" not in cap["system_prompt"]
