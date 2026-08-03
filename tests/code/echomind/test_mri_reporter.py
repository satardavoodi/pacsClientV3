# -*- coding: utf-8 -*-
"""Unit tests for MRI-specific reporter helpers.

Tests _clean_model_json_text() and _validate_report_json() from
modules/EchoMind/viewer_chat/openai_reporter.py.

No live API calls -- all tests run fully offline/headless.
Guard: keeps the MRI null-schema, fence-stripping, and key-validation
behaviour locked so future edits to the prompt do not silently break parsing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# -- project root on sys.path --------------------------------------------------
_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# -- PySide6 / Qt stub injection -----------------------------------------------
# openai_reporter.py -> api_manager.py -> PySide6.QtCore (Signal/QObject).
# Inject lightweight stubs so the module imports headlessly without a display.
import types as _types


def _make_qt_stub(name: str) -> "_types.ModuleType":
    mod = _types.ModuleType(name)
    mod.QObject = type("QObject", (), {})

    class _FakeSignal:
        def __init__(self, *a, **kw):
            pass

        def connect(self, *a):
            pass

        def emit(self, *a):
            pass

    mod.Signal = _FakeSignal
    mod.QThread = type("QThread", (), {})
    mod.Qt = type("Qt", (), {})
    mod.QTimer = type("QTimer", (), {})
    return mod


_QT_STUBS = [
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtWidgets",
    "PySide6.QtGui",
    "PySide6.QtNetwork",
]
for _qt_name in _QT_STUBS:
    if _qt_name not in sys.modules:
        sys.modules[_qt_name] = _make_qt_stub(_qt_name)

from modules.EchoMind.viewer_chat.openai_reporter import (
    _MRI_REQUIRED_KEYS,
    _clean_model_json_text,
    _validate_report_json,
)

# -- test fixtures -------------------------------------------------------------

_VALID_MRI_ALL_KEYS = json.dumps(
    {
        "Report Title": "MRI of the Brain With and Without Contrast, Including DWI and MR Spectroscopy",
        "Pathological Findings": (
            "A 1.8 cm ring-enhancing lesion in the right temporal lobe demonstrates "
            "restricted diffusion on DWI with low ADC values. MR Spectroscopy shows "
            "elevated choline peak and reduced NAA, suggestive of a high-grade neoplasm."
        ),
        "Normal Findings": (
            "Ventricular system normal in size and configuration. No midline shift or "
            "mass effect beyond the described lesion. Brainstem, cerebellum, basal ganglia, "
            "and internal capsule are unremarkable. Paranasal sinuses are clear."
        ),
        "Impression": (
            "Ring-enhancing right temporal lobe lesion with spectroscopic features suggestive "
            "of a high-grade glioma. Differential includes primary CNS lymphoma."
        ),
        "Recommendations": (
            "Neurosurgical consultation recommended. Stereotactic biopsy or resection advised "
            "for histopathological confirmation."
        ),
    },
    ensure_ascii=False,
)

_VALID_MRI_NULL_REC = json.dumps(
    {
        "Report Title": "MRI of the Right Knee Joint Without Contrast",
        "Pathological Findings": (
            "Complete tear of the anterior cruciate ligament (ACL) with bone marrow edema "
            "at the lateral femoral condyle and lateral tibial plateau. Grade II signal "
            "change in the posterior horn of the medial meniscus."
        ),
        "Normal Findings": (
            "Posterior cruciate ligament, medial and lateral collateral ligaments intact. "
            "Articular cartilage preserved in thickness. No joint effusion. "
            "Muscles have normal bulk and signal intensity."
        ),
        "Impression": None,
        "Recommendations": None,
    },
    ensure_ascii=False,
)

_VALID_MRI_WITH_REC = json.dumps(
    {
        "Report Title": "MRI of the Lumbar Spine Without Contrast",
        "Pathological Findings": (
            "L4-L5 disc extrusion with moderate left-sided neural foraminal stenosis "
            "and compression of the exiting L4 nerve root. Mild cord signal change at L4."
        ),
        "Normal Findings": (
            "Vertebral bodies at L1-L3 and L5-S1 show normal height and marrow signal. "
            "Spinal canal dimensions preserved at those levels. Conus medullaris "
            "terminates at L1. Cauda equina shows no abnormal signal above L4."
        ),
        "Impression": None,
        "Recommendations": (
            "Clinical correlation with radiculopathy symptoms. "
            "Neurosurgical referral advised if conservative management fails."
        ),
    },
    ensure_ascii=False,
)


# =============================================================================
# 1. _MRI_REQUIRED_KEYS constant
# =============================================================================

def test_mri_required_keys_complete():
    """All five schema keys must be present in the constant."""
    expected = {
        "Report Title",
        "Pathological Findings",
        "Normal Findings",
        "Impression",
        "Recommendations",
    }
    assert set(_MRI_REQUIRED_KEYS) == expected


# =============================================================================
# 2. _clean_model_json_text
# =============================================================================

def test_clean_strips_json_fence():
    raw = '```json\n{"key": "value"}\n```'
    result = _clean_model_json_text(raw)
    assert result == '{"key": "value"}'


def test_clean_strips_plain_fence():
    raw = '```\n{"key": "value"}\n```'
    result = _clean_model_json_text(raw)
    assert result == '{"key": "value"}'


def test_clean_strips_end_token():
    raw = '{"key": "value"}<|end|>'
    result = _clean_model_json_text(raw)
    assert "<|end|>" not in result
    assert result.strip() == '{"key": "value"}'


def test_clean_strips_end_token_with_fence():
    raw = '```json\n{"key": "value"}\n```<|end|>'
    result = _clean_model_json_text(raw)
    assert "<|end|>" not in result
    assert "```" not in result


def test_clean_passthrough_plain_json():
    raw = '{"Report Title": "MRI Brain", "Impression": null}'
    result = _clean_model_json_text(raw)
    assert result == raw


def test_clean_non_string_passthrough():
    """Non-string input is returned as-is (defensive guard)."""
    assert _clean_model_json_text(None) is None
    assert _clean_model_json_text(42) == 42


# =============================================================================
# 3. _validate_report_json -- non-MRI passthrough
# =============================================================================

def test_validate_non_validated_modality_passthrough():
    """Modalities outside _VALIDATED_MODALITIES must be returned byte-for-byte unchanged."""
    raw = "anything at all -- not checked for this modality"
    # 2026-08-01 — "Radiology" removed: it is a live UI modality and is now
    # validated. See test_mammography_reporter for the same correction.
    for mod in ("XRay", "Nuclear", "PET", "Fluoroscopy"):
        result = _validate_report_json(raw, mod)
        assert result == raw, f"Modality {mod!r} was mutated"


# =============================================================================
# 4. _validate_report_json -- MRI happy-path
# =============================================================================

class TestValidateMriHappyPath:
    """Test Case 1 -- Brain MRI with contrast, DWI, MR Spectroscopy,
    explicit impression, and recommendation."""

    def test_all_five_keys_present(self):
        result = _validate_report_json(_VALID_MRI_ALL_KEYS, "mri")
        data = json.loads(result)
        for key in _MRI_REQUIRED_KEYS:
            assert key in data, f"Missing key: {key!r}"

    def test_impression_not_null(self):
        result = _validate_report_json(_VALID_MRI_ALL_KEYS, "mri")
        data = json.loads(result)
        assert data["Impression"] is not None
        assert isinstance(data["Impression"], str)
        assert len(data["Impression"]) > 0

    def test_recommendations_not_null(self):
        result = _validate_report_json(_VALID_MRI_ALL_KEYS, "mri")
        data = json.loads(result)
        assert data["Recommendations"] is not None
        assert isinstance(data["Recommendations"], str)
        assert len(data["Recommendations"]) > 0

    def test_no_markdown_in_output(self):
        result = _validate_report_json(_VALID_MRI_ALL_KEYS, "mri")
        assert "```" not in result

    def test_no_end_token_in_output(self):
        result = _validate_report_json(_VALID_MRI_ALL_KEYS, "mri")
        assert "<|end|>" not in result

    def test_output_is_valid_json(self):
        result = _validate_report_json(_VALID_MRI_ALL_KEYS, "mri")
        data = json.loads(result)  # must not raise
        assert isinstance(data, dict)


class TestValidateMriKneeNoRec:
    """Test Case 2 -- Knee MRI without contrast, no explicit recommendation."""

    def test_recommendations_is_null(self):
        result = _validate_report_json(_VALID_MRI_NULL_REC, "mri")
        data = json.loads(result)
        assert data["Recommendations"] is None

    def test_impression_is_null_when_absent(self):
        result = _validate_report_json(_VALID_MRI_NULL_REC, "mri")
        data = json.loads(result)
        assert data["Impression"] is None

    def test_all_five_keys_present(self):
        result = _validate_report_json(_VALID_MRI_NULL_REC, "mri")
        data = json.loads(result)
        for key in _MRI_REQUIRED_KEYS:
            assert key in data

    def test_normal_findings_exists(self):
        result = _validate_report_json(_VALID_MRI_NULL_REC, "mri")
        data = json.loads(result)
        assert isinstance(data["Normal Findings"], str)
        assert len(data["Normal Findings"]) > 0

    def test_output_is_valid_json(self):
        result = _validate_report_json(_VALID_MRI_NULL_REC, "mri")
        json.loads(result)  # must not raise


class TestValidateMriLumbarWithRec:
    """Test Case 3 -- Lumbar spine MRI with explicit recommendation."""

    def test_recommendations_not_null(self):
        result = _validate_report_json(_VALID_MRI_WITH_REC, "mri")
        data = json.loads(result)
        assert data["Recommendations"] is not None
        assert isinstance(data["Recommendations"], str)
        assert "neurosurgical" in data["Recommendations"].lower()

    def test_impression_null_when_not_dictated(self):
        """Impression should stay null when no diagnostic conclusion was dictated."""
        result = _validate_report_json(_VALID_MRI_WITH_REC, "mri")
        data = json.loads(result)
        assert data["Impression"] is None

    def test_all_five_keys_present(self):
        result = _validate_report_json(_VALID_MRI_WITH_REC, "mri")
        data = json.loads(result)
        for key in _MRI_REQUIRED_KEYS:
            assert key in data

    def test_output_is_valid_json(self):
        result = _validate_report_json(_VALID_MRI_WITH_REC, "mri")
        json.loads(result)  # must not raise


# =============================================================================
# 5. _validate_report_json -- MRI fence/token stripping
# =============================================================================

def test_validate_strips_fence_from_model_output():
    """Validator must transparently strip markdown fences added by the model."""
    wrapped = "```json\n" + _VALID_MRI_ALL_KEYS + "\n```"
    result = _validate_report_json(wrapped, "mri")
    data = json.loads(result)
    assert set(data.keys()) == set(_MRI_REQUIRED_KEYS)


def test_validate_strips_end_token_from_model_output():
    """Validator must strip <|end|> appended by the model."""
    with_token = _VALID_MRI_ALL_KEYS + "<|end|>"
    result = _validate_report_json(with_token, "mri")
    assert "<|end|>" not in result
    json.loads(result)  # must not raise


def test_validate_repairs_missing_impression():
    """If model omits Impression key, validator inserts null."""
    data = json.loads(_VALID_MRI_ALL_KEYS)
    del data["Impression"]
    result = _validate_report_json(json.dumps(data, ensure_ascii=False), "mri")
    repaired = json.loads(result)
    assert "Impression" in repaired
    assert repaired["Impression"] is None


def test_validate_repairs_missing_recommendations():
    """If model omits Recommendations key, validator inserts null."""
    data = json.loads(_VALID_MRI_ALL_KEYS)
    del data["Recommendations"]
    result = _validate_report_json(json.dumps(data, ensure_ascii=False), "mri")
    repaired = json.loads(result)
    assert "Recommendations" in repaired
    assert repaired["Recommendations"] is None


def test_validate_normalises_empty_string_impression():
    """Empty-string Impression should be coerced to null."""
    data = json.loads(_VALID_MRI_ALL_KEYS)
    data["Impression"] = ""
    result = _validate_report_json(json.dumps(data, ensure_ascii=False), "mri")
    assert json.loads(result)["Impression"] is None


def test_validate_normalises_na_recommendations():
    """N/A Recommendations should be coerced to null."""
    data = json.loads(_VALID_MRI_ALL_KEYS)
    data["Recommendations"] = "N/A"
    result = _validate_report_json(json.dumps(data, ensure_ascii=False), "mri")
    assert json.loads(result)["Recommendations"] is None


# =============================================================================
# 6. _validate_report_json -- MRI error cases
# =============================================================================

def test_validate_raises_on_invalid_json():
    with pytest.raises(ValueError, match="non-parseable JSON"):
        _validate_report_json("not json at all {{{", "mri")


def test_validate_raises_on_missing_required_key():
    """A missing non-optional key (Report Title) must raise ValueError."""
    data = json.loads(_VALID_MRI_ALL_KEYS)
    del data["Report Title"]
    with pytest.raises(ValueError, match="Required key missing"):
        _validate_report_json(json.dumps(data, ensure_ascii=False), "mri")


def test_validate_raises_on_missing_pathological_findings():
    data = json.loads(_VALID_MRI_ALL_KEYS)
    del data["Pathological Findings"]
    with pytest.raises(ValueError, match="Required key missing"):
        _validate_report_json(json.dumps(data, ensure_ascii=False), "mri")


def test_validate_raises_on_missing_normal_findings():
    data = json.loads(_VALID_MRI_ALL_KEYS)
    del data["Normal Findings"]
    with pytest.raises(ValueError, match="Required key missing"):
        _validate_report_json(json.dumps(data, ensure_ascii=False), "mri")


def test_validate_raises_on_non_object_json():
    with pytest.raises(ValueError, match="Expected a JSON object"):
        _validate_report_json('["list", "not", "object"]', "mri")


# =============================================================================
# 7. Source-pin guards (structural, no live calls)
# =============================================================================

def test_mri_block_contains_strict_output_instruction():
    """The live MRI specific_instructions must tell the model not to use markdown."""
    src_path = Path(__file__).resolve().parents[3] / (
        "modules/EchoMind/viewer_chat/openai_reporter.py"
    )
    src = src_path.read_text(encoding="utf-8")
    mri_start = src.find('elif modality_lower == "mri":')
    sono_start = src.find('elif modality_lower in ["sonography"', mri_start)
    assert mri_start != -1 and sono_start != -1
    mri_block = src[mri_start:sono_start]
    assert "Return only a valid JSON object" in mri_block
    assert "Do not include markdown" in mri_block
    assert "Do not include code fences" in mri_block


def test_mri_block_contains_null_schema_instruction():
    src_path = Path(__file__).resolve().parents[3] / (
        "modules/EchoMind/viewer_chat/openai_reporter.py"
    )
    src = src_path.read_text(encoding="utf-8")
    mri_start = src.find('elif modality_lower == "mri":')
    sono_start = src.find('elif modality_lower in ["sonography"', mri_start)
    mri_block = src[mri_start:sono_start]
    assert "string | null" in mri_block


def test_mri_payload_sets_temperature():
    """reporter() must set temperature=0.1 for MRI."""
    src_path = Path(__file__).resolve().parents[3] / (
        "modules/EchoMind/viewer_chat/openai_reporter.py"
    )
    src = src_path.read_text(encoding="utf-8")
    assert 'payload["temperature"] = 0.1' in src


def test_mri_payload_sets_max_tokens():
    """reporter() must set max_tokens=2500 for MRI."""
    src_path = Path(__file__).resolve().parents[3] / (
        "modules/EchoMind/viewer_chat/openai_reporter.py"
    )
    src = src_path.read_text(encoding="utf-8")
    assert 'payload["max_tokens"] = 2500' in src


def test_validate_report_json_called_in_reporter():
    """reporter() must call _validate_report_json for MRI/CT output."""
    src_path = Path(__file__).resolve().parents[3] / (
        "modules/EchoMind/viewer_chat/openai_reporter.py"
    )
    src = src_path.read_text(encoding="utf-8")
    assert '_validate_report_json(raw_content, modality.lower())' in src


def _get_mri_block(src: str) -> str:
    mri_start = src.find('elif modality_lower == "mri":')
    sono_start = src.find('elif modality_lower in ["sonography"', mri_start)
    assert mri_start != -1 and sono_start != -1, "MRI block not found in source"
    return src[mri_start:sono_start]


def test_mri_block_pathological_findings_manifestation_rule():
    """MRI prompt must instruct the model to describe the imaging manifestation."""
    from pathlib import Path
    src_path = Path(__file__).resolve().parents[3] / (
        "modules/EchoMind/viewer_chat/openai_reporter.py"
    )
    src = src_path.read_text(encoding="utf-8")
    block = _get_mri_block(src)
    assert "PATHOLOGICAL FINDINGS RULES" in block
    assert "manifested by" in block
    assert "imaging appearance" in block


def test_mri_block_brain_normal_findings_comprehensive():
    """Brain MRI normal-findings template must include the systematic checklist items."""
    from pathlib import Path
    src_path = Path(__file__).resolve().parents[3] / (
        "modules/EchoMind/viewer_chat/openai_reporter.py"
    )
    src = src_path.read_text(encoding="utf-8")
    block = _get_mri_block(src)
    required_items = [
        "No acute territorial infarction",
        "No intracranial hemorrhage",
        "No intra-axial or extra-axial mass lesion",
        "No midline shift or significant mass effect",
        "basal cisterns are patent",
        "No abnormal extra-axial fluid collection",
        "cerebellum and brainstem show no focal abnormal signal",
        "sellar and parasellar",
        "orbits are grossly unremarkable",
        "vascular flow voids are preserved",
    ]
    for item in required_items:
        assert item in block, f"Brain MRI checklist item missing: {item!r}"  # noqa: E501
