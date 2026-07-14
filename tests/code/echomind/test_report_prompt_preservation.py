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


def _extract_reporter_source() -> str:
    with open(_REPORTER_PY, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith("def reporter("))
    end = next(i for i, l in enumerate(lines) if l.startswith("def ") and i > start)
    return "\n".join(lines[start:end])


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
        "_VALIDATED_MODALITIES": {"mri", "ct", "mammography"},
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
