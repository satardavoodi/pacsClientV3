"""Guard: physician-provided Impression / Recommendation / Suggestion must be preserved
in EVERY EchoMind report prompt (per-modality, independent prompts).

Background
----------
Physician-dictated conclusions were being dropped from generated reports (confirmed in MRI).
The reporting prompts live in ``modules/EchoMind/viewer_chat/openai_reporter.py`` inside the
``reporter()`` function, which selects an INDEPENDENT prompt per modality (CT, MRI, Ultrasound,
Obstetric Ultrasound, Mammography, Radiology, and a generic fallback). Each prompt must, on its
own, tell the model:

  * NOT to independently generate NEW impressions / recommendations / suggestions, AND
  * to ALWAYS preserve any impression / recommendation / suggestion / clinical-laboratory-
    pathologic correlation the physician EXPLICITLY dictated.

This test assembles the real ``system_prompt`` per modality (network stubbed, exactly like the
prompt-export mechanism) and asserts the preservation rule is present in each one — so a future
edit that drops it from any single modality fails here rather than silently in production.

The whole ``openai_reporter.py`` module is heavy to import (Qt / app deps), so we extract just the
``reporter()`` source and exec it with lightweight stubs. This keeps the test hermetic and fast.
"""

import os
import types
import typing

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_REPORTER_PY = os.path.normpath(
    os.path.join(
        _THIS, "..", "..", "..", "modules", "EchoMind", "viewer_chat", "openai_reporter.py"
    )
)


def _extract_defs(path: str, names) -> str:
    """Return the source of the named TOP-LEVEL functions, in file order.

    2026-08-01: `reporter()` no longer assembles the prompt inline — it calls
    `build_report_system_prompt()`, the shared authority the OpenAI twin backend
    also uses. Extracting `reporter` alone would exec a `NameError`, and
    STUBBING the builder would make every assertion in this file vacuous, so we
    extract both and keep testing the real prompt text.
    """
    import ast as _ast

    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.split("\n")
    tree = _ast.parse(src)
    wanted = set(names)
    out = []
    for node in tree.body:
        if isinstance(node, _ast.FunctionDef) and node.name in wanted:
            out.append("\n".join(lines[node.lineno - 1 : node.end_lineno]))
            wanted.discard(node.name)
    assert not wanted, f"top-level def(s) not found in {path}: {sorted(wanted)}"
    return "\n\n".join(out)


def _extract_reporter_source() -> str:
    return _extract_defs(_REPORTER_PY, ("build_report_system_prompt", "reporter"))


def _build_reporter():
    """Exec the real reporter() with the network + app deps stubbed. Returns (reporter, capture)."""
    capture: dict = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"Report Title":"t","Pathological Findings":"p","Normal Findings":"n"}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    def _fake_post(url, headers=None, json=None, proxies=None, **kw):
        capture["system_prompt"] = json["messages"][0]["content"]
        capture["user"] = json["messages"][1]["content"]
        return _FakeResp()

    class _FakeMgr:
        @staticmethod
        def instance():
            return _FakeMgr()

        def get_center_and_gapgpt_key(self):
            return ("center", "key")

    g = {
        "__name__": "reporter_under_test",
        "Optional": typing.Optional,
        "Dict": dict,
        "Any": object,
        "requests": types.SimpleNamespace(post=_fake_post),
        "_to_str": lambda x: "" if x is None else str(x),
        "_get_requests_proxies": lambda: {},
        # OPT-33 (2026-07-13): reporter() now passes timeout=_request_timeout() to
        # requests.post — every outbound AI call must have one, or a half-open link
        # hangs the ApiWorker thread forever. This stub namespace is a WHITELIST of
        # the module globals reporter() really uses, so it has to track that.
        "_request_timeout": lambda: (10.0, 180.0),
        "_log_usage_safe": lambda *a, **k: None,
        "_validate_report_json": lambda raw, mod: raw,
        # 2026-08-01: post-response validation is no longer gated to ("mri","ct")
        # — reporter() now asks `_report_validation_enabled()` and hands every
        # modality to `_validate_report_json`, which no-ops for anything outside
        # `_VALIDATED_MODALITIES`. Both names therefore belong in this whitelist.
        "_report_validation_enabled": lambda: True,
        # Mirrors the real set, which had to grow to cover the values the UI
        # actually sends: "MAMOGRAPHY" (one "m") and "RADIOLOGY". Before that,
        # mammography silently lost its temperature clamp and its output check.
        "_VALIDATED_MODALITIES": {
            "mri", "ct",
            "mammography", "mamography", "mammogram", "mamogram",
            "sonography", "ultrasound",
            "obstetric ultrasound", "ob ultrasound",
            "pregnancy ultrasound", "fetal ultrasound",
            "radiology",
        },
        "Manage": _FakeMgr,
    }
    exec(compile(_extract_reporter_source(), _REPORTER_PY, "exec"), g)
    return g["reporter"], capture


# modality button value -> a dictation that contains physician-provided conclusions
_DICTATIONS = {
    "MRI": "MRI brain. right temporal mass. findings are suggestive of glioblastoma. "
    "biopsy is recommended. clinical correlation is recommended.",
    "CT": "CT chest. lung nodule. suggestive of malignancy. further evaluation is recommended. "
    "correlation with laboratory findings is recommended.",
    "SONOGRAPHY": "abdominal ultrasound. liver lesion suggestive of hemangioma. follow-up is recommended.",
    "RADIOLOGY": "chest x-ray. opacity suggestive of pneumonia. clinical correlation is recommended.",
    "MAMOGRAPHY": "mammography. spiculated mass right breast suggestive of malignancy. biopsy is recommended. BI-RADS 5.",
    "": "study. suggestive of something. biopsy is recommended.",
}


@pytest.mark.parametrize("modality", list(_DICTATIONS))
def test_each_prompt_preserves_physician_content(modality):
    reporter, capture = _build_reporter()
    capture.clear()
    reporter(_DICTATIONS[modality], modality=modality)
    sp = capture.get("system_prompt", "")
    low = sp.lower()
    assert sp, f"no system_prompt captured for modality={modality!r}"
    # Independent preservation rule must be present in THIS modality's prompt
    assert "preserve" in low and "physician" in low, (
        f"modality {modality!r}: missing physician-content preservation rule"
    )
    # The generate-vs-preserve distinction must be explicit
    assert ("did not dictate" in low) or ("not independently generate" in low) or (
        "did not provide" in low
    ), f"modality {modality!r}: missing 'do not independently generate' side of the rule"
    # Must explicitly protect dictated recommendations/correlations (the reported failure)
    assert "clinical correlation" in low, f"modality {modality!r}: correlation not named"
    assert "biopsy" in low, f"modality {modality!r}: biopsy recommendation not named"


def test_mammography_alias_routes_to_mammography_prompt():
    """The menu button value 'MAMOGRAPHY' (one 'm') must reach the regex-locked mammography prompt,
    not the generic fallback."""
    reporter, capture = _build_reporter()
    capture.clear()
    reporter(_DICTATIONS["MAMOGRAPHY"], modality="MAMOGRAPHY")
    sp = capture.get("system_prompt", "")
    assert "BI-RADS" in sp and "REGEX-LOCKED JSON SCHEMA" in sp, (
        "MAMOGRAPHY did not route to the mammography prompt (spelling alias regression)"
    )
    assert "SECTION 0b — PRESERVE PHYSICIAN-PROVIDED CONCLUSIONS (SCHEMA-SAFE)" in sp


@pytest.mark.parametrize("modality", ["CT", "MRI", "SONOGRAPHY"])
def test_sex_specific_anatomy_rule_present(modality):
    """Each pelvis-bearing modality prompt must instruct: do not infer sex, include a sex-specific
    organ only if the physician explicitly mentioned it, and never emit both sexes."""
    reporter, capture = _build_reporter()
    capture.clear()
    reporter("abdomen and pelvis. no acute finding.", modality=modality)
    low = capture.get("system_prompt", "").lower()
    assert "sex-specific anatomy" in low, f"{modality}: missing sex-specific anatomy rule"
    assert "do not infer or assume the patient's sex" in low, f"{modality}: missing 'do not infer sex'"
    assert "include only if" in low, f"{modality}: missing explicit-mention gate"
    # never both sexes
    assert "never include both" in low or "never output both" in low, (
        f"{modality}: missing 'never both sexes' rule"
    )


def test_no_unconditional_both_sex_normal_findings_in_source():
    """Static guard: the CT and MRI pelvis normal-findings must not list sex-specific organs with the
    weak '(if applicable)' form that previously produced both prostate AND uterus/ovaries."""
    with open(_REPORTER_PY, encoding="utf-8") as fh:
        src = fh.read()
    for bad in [
        "Prostate (if applicable)",
        "Uterus (if applicable)",
        "Ovaries (if applicable)",
        "Female pelvis (if applicable)",
        "Male pelvis (if applicable)",
    ]:
        assert bad not in src, f"weak conditional still present: {bad!r} (should be 'INCLUDE ONLY IF ... mentioned')"


def test_template_override_has_sex_caveat():
    """Even a user-provided normal_template must not auto-complete unmentioned sex-specific organs."""
    reporter, capture = _build_reporter()
    capture.clear()
    reporter(
        "abdomen and pelvis.",
        modality="CT",
        normal_template="Liver normal. Prostate unremarkable. Uterus unremarkable.",
    )
    low = capture.get("system_prompt", "").lower()
    assert "even if the provided template lists" in low, "template-override sex caveat missing"


def test_non_ob_ultrasound_has_exam_specific_normal_templates():
    """The non-obstetric ultrasound prompt must provide structured, exam-specific normal templates
    (not one thin generic list), with reference measurements, while leaving the OB section intact."""
    reporter, capture = _build_reporter()
    capture.clear()
    reporter("thyroid ultrasound. no nodule.", modality="SONOGRAPHY")
    sp = capture.get("system_prompt", "")
    required_templates = [
        "EXAM-SPECIFIC NORMAL TEMPLATES",
        "COMPLETE ABDOMINAL ULTRASOUND",
        "RENAL / URINARY-TRACT (KUB)",
        "THYROID / NECK ULTRASOUND",
        "BREAST ULTRASOUND",
        "SCROTAL / TESTICULAR",
        "CAROTID / VERTEBRAL DOPPLER",
        "EXTREMITY VENOUS DOPPLER (DVT",
        "APPENDIX / RIGHT-ILIAC-FOSSA",
        "SOFT-TISSUE / SUPERFICIAL / MUSCULOSKELETAL",
    ]
    for t in required_templates:
        assert t in sp, f"ultrasound prompt missing exam template: {t!r}"
    # reference measurements present
    assert "not dilated (≤6 mm)" in sp, "missing CBD normal measurement reference"
    assert "proliferative ≈4–8 mm" in sp, "missing endometrial thickness reference"
    # thin generic list removed
    assert "RSNA NORMAL FINDINGS — GENERAL ULTRASOUND" not in sp, "old thin generic list still present"
    # OB untouched, sex + preservation rules retained
    assert "ISUOG NORMAL FINDINGS — OBSTETRIC ULTRASOUND" in sp, "OB section must remain"
    assert "SEX-SPECIFIC ANATOMY RULE" in sp
    assert "PRESERVE PHYSICIAN-PROVIDED CONCLUSIONS" in sp


def _build_company_correction():
    """Exec the company-path correction() with the network stubbed; returns (fn, capture)."""
    import types

    src = _extract_defs(
        _REPORTER_PY,
        ("build_correction_system_prompt", "build_correction_user_content", "correction"),
    )
    cap = {}

    class _R:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    def _post(u, headers=None, json=None, proxies=None, timeout=None, **k):
        cap["payload"] = json
        return _R()

    class _M:
        @staticmethod
        def instance():
            return _M()

        def get_center_and_gapgpt_key(self):
            return ("c", "k")

    g = {
        "__name__": "corr_under_test",
        "requests": types.SimpleNamespace(post=_post),
        "_to_str": lambda x: "" if x is None else str(x),
        "_get_requests_proxies": lambda: {},
        "_log_usage_safe": lambda *a, **k: None,
        "_request_timeout": lambda: 30,
        "Manage": _M,
        "Optional": typing.Optional,
        "Dict": dict,
        "Any": object,
    }
    exec(compile(src, _REPORTER_PY, "exec"), g)
    return g["correction"], cap


def test_correction_is_deterministic_and_structured():
    """Correction (company path) must use a strong model, temperature 0, and a clearly-delimited
    payload separating the report from the instruction."""
    correction, cap = _build_company_correction()
    correction(user_report='{"Report Title":"MRI Lumbar"}', correction_note="change L4-L5 to L5-S1")
    p = cap["payload"]
    assert p["model"] == "gpt-5.4", f"correction should default to a strong model, got {p['model']!r}"
    assert p.get("temperature") == 0, "correction must pin temperature to 0 (surgical patch, not rewrite)"
    uc = p["messages"][1]["content"]
    assert "===== ORIGINAL_REPORT" in uc and "===== CORRECTION_NOTE" in uc, "payload blocks not delimited"
    sp = p["messages"][0]["content"]
    assert "PATCH, NOT REGENERATE" in sp, "correction system prompt lost its patch principle"


def test_correction_target_location_block_is_conditional():
    correction, cap = _build_company_correction()
    # absent when no target
    correction(user_report="{}", correction_note="fix it")
    assert "TARGET_LOCATION" not in cap["payload"]["messages"][1]["content"]
    # present, verbatim, when supplied
    correction(user_report="{}", correction_note="fix it", target_section="Disc bulging at L4-L5.")
    uc = cap["payload"]["messages"][1]["content"]
    assert "===== TARGET_LOCATION" in uc and "Disc bulging at L4-L5." in uc


def test_correction_backend_uses_correction_feature_and_temp0():
    """OpenAI-backend correction() must resolve the dedicated 'correction' model feature, pin
    temperature 0, and carry the full PATCH/preserve system prompt."""
    _backend_py = os.path.normpath(
        os.path.join(_THIS, "..", "..", "..", "modules", "EchoMind", "viewer_chat", "openai_parallel_backend.py")
    )
    src = _extract_defs(_backend_py, ("correction",))
    cap = {}

    def _fake_call(**kw):
        cap.update(kw)
        return {"content": "{}", "usage": {}}

    g = {"__name__": "corr_backend", "_call": _fake_call, "Any": object, "Optional": typing.Optional,
         "_to_str": lambda x: "" if x is None else str(x)}
    # 2026-08-01: the twin backend no longer carries its own correction prompt —
    # it calls the SAME builders as the company path. Exec the REAL builders in
    # so the assertions below still check real prompt text, not a stub.
    exec(
        compile(
            _extract_defs(
                _REPORTER_PY,
                ("build_correction_system_prompt", "build_correction_user_content"),
            ),
            _REPORTER_PY,
            "exec",
        ),
        g,
    )
    exec(compile(src, _backend_py, "exec"), g)
    g["correction"](user_report="{}", correction_note="n", target_section="S")
    assert cap["feature_name"] == "correction", "backend must use the 'correction' model feature"
    assert cap.get("temperature") == 0, "backend correction must pin temperature 0"
    assert "PATCH operation" in cap["system_prompt"], "backend correction lost the patch system prompt"
    assert "===== TARGET_LOCATION" in cap["user_content"]


def test_no_central_single_rule_all_branches_independent():
    """Regression guard for the architecture directive: the preservation rule must live INSIDE each
    modality branch, not as one shared block appended once to every prompt. We assert the MRI, CT,
    Ultrasound and Radiology prompts each carry their OWN modality-named preservation header."""
    reporter, capture = _build_reporter()
    expected = {
        "MRI": "MRI — PRESERVE PHYSICIAN-PROVIDED CONCLUSIONS",
        "CT": "CT — PRESERVE PHYSICIAN-PROVIDED CONCLUSIONS",
        "SONOGRAPHY": "ULTRASOUND — PRESERVE PHYSICIAN-PROVIDED CONCLUSIONS",
        "RADIOLOGY": "RADIOLOGY (X-RAY) — PRESERVE PHYSICIAN-PROVIDED CONCLUSIONS",
    }
    for mod, header in expected.items():
        capture.clear()
        reporter(_DICTATIONS[mod], modality=mod)
        assert header in capture.get("system_prompt", ""), (
            f"modality {mod!r} missing its own preservation header {header!r}"
        )
