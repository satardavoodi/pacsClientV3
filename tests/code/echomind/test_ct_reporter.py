"""
Tests for CT-scan reporter functionality in openai_reporter.py.

Covers:
  - _CT_REQUIRED_KEYS constant
  - _validate_report_json for CT (shares implementation with MRI)
  - payload temperature / max_tokens set for CT
  - validate call wired for CT in reporter()
  - source-pin: comprehensive per-body-part checklist phrases in the CT block
"""

import sys
import types
import importlib
import json
import pytest

# ─────────────────────────────────────────────────────────────────
# Qt stub injection (headless / offscreen)
# ─────────────────────────────────────────────────────────────────
def _inject_qt_stubs():
    stubs = [
        "PySide6", "PySide6.QtCore", "PySide6.QtWidgets", "PySide6.QtGui",
        "PySide6.QtNetwork", "PySide6.QtMultimedia",
    ]
    for name in stubs:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.Qt = types.SimpleNamespace(
                AlignLeft=1, AlignRight=2, AlignCenter=4,
                LeftButton=1, RightButton=2,
            )
            mod.Signal = lambda *a, **kw: None
            mod.Slot = lambda *a, **kw: (lambda f: f)
            mod.QObject = object
            mod.QThread = object
            sys.modules[name] = mod

_inject_qt_stubs()

from modules.EchoMind.viewer_chat.openai_reporter import (
    _CT_REQUIRED_KEYS,
    _clean_model_json_text,
    _validate_report_json,
)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────
def _src():
    """Return the full source text of openai_reporter.py."""
    import os
    here = os.path.dirname(__file__)
    path = os.path.join(
        here, "..", "..", "..",
        "modules", "EchoMind", "viewer_chat", "openai_reporter.py",
    )
    with open(os.path.normpath(path), encoding="utf-8") as f:
        return f.read()


def _get_ct_block(src):
    """Slice the CT-modality block between its opening `if` and the next `elif`."""
    start = src.index('if modality_lower == "ct":')
    end = src.index('elif modality_lower == "mri":', start)
    return src[start:end]


# ─────────────────────────────────────────────────────────────────
# 1. _CT_REQUIRED_KEYS constant
# ─────────────────────────────────────────────────────────────────
class TestCTRequiredKeys:
    def test_is_list(self):
        assert isinstance(_CT_REQUIRED_KEYS, list)

    def test_has_five_keys(self):
        assert len(_CT_REQUIRED_KEYS) == 5

    def test_contains_report_title(self):
        assert "Report Title" in _CT_REQUIRED_KEYS

    def test_contains_pathological_findings(self):
        assert "Pathological Findings" in _CT_REQUIRED_KEYS

    def test_contains_normal_findings(self):
        assert "Normal Findings" in _CT_REQUIRED_KEYS

    def test_contains_impression(self):
        assert "Impression" in _CT_REQUIRED_KEYS

    def test_contains_recommendations(self):
        assert "Recommendations" in _CT_REQUIRED_KEYS


# ─────────────────────────────────────────────────────────────────
# 2. _validate_report_json — CT modality
# ─────────────────────────────────────────────────────────────────
class TestValidateReportJsonCT:
    _GOOD_PAYLOAD = json.dumps({
        "Report Title": "CT Scan of the Brain Without Contrast",
        "Pathological Findings": "No acute intracranial findings.",
        "Normal Findings": "Normal brain parenchyma.",
        "Impression": "Normal study.",
        "Recommendations": "Clinical correlation recommended.",
    })

    def test_passthrough_for_non_ct(self):
        raw = "anything"
        assert _validate_report_json(raw, "sonography") == raw

    def test_ct_returns_json_string(self):
        result = _validate_report_json(self._GOOD_PAYLOAD, "ct")
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_ct_uppercase_passthrough(self):
        """Modality matching is case-insensitive."""
        result = _validate_report_json(self._GOOD_PAYLOAD, "CT")
        assert json.loads(result)["Report Title"] == "CT Scan of the Brain Without Contrast"

    def test_ct_strips_fence(self):
        fenced = "```json\n" + self._GOOD_PAYLOAD + "\n```"
        result = _validate_report_json(fenced, "ct")
        assert json.loads(result)["Report Title"] == "CT Scan of the Brain Without Contrast"

    def test_ct_strips_end_token(self):
        with_end = self._GOOD_PAYLOAD + "<|end|>"
        result = _validate_report_json(with_end, "ct")
        assert json.loads(result)["Report Title"] == "CT Scan of the Brain Without Contrast"

    def test_ct_raises_on_invalid_json(self):
        with pytest.raises(ValueError, match="non-parseable"):
            _validate_report_json("not json {{{", "ct")

    def test_ct_raises_on_non_dict_json(self):
        with pytest.raises(ValueError, match="dict"):
            _validate_report_json("[1, 2, 3]", "ct")

    def test_ct_raises_on_missing_required_key(self):
        bad = json.dumps({
            "Report Title": "CT Chest",
            "Pathological Findings": "None.",
            # "Normal Findings" missing
        })
        with pytest.raises(ValueError, match="Normal Findings"):
            _validate_report_json(bad, "ct")

    def test_ct_null_impression_coerced_from_empty_string(self):
        payload = json.dumps({
            "Report Title": "CT Chest",
            "Pathological Findings": "None.",
            "Normal Findings": "Normal.",
            "Impression": "",
            "Recommendations": "n/a",
        })
        result = _validate_report_json(payload, "ct")
        parsed = json.loads(result)
        assert parsed["Impression"] is None
        assert parsed["Recommendations"] is None

    def test_ct_missing_optional_keys_added_as_null(self):
        payload = json.dumps({
            "Report Title": "CT Chest",
            "Pathological Findings": "None.",
            "Normal Findings": "Normal.",
        })
        result = _validate_report_json(payload, "ct")
        parsed = json.loads(result)
        assert "Impression" in parsed
        assert "Recommendations" in parsed
        assert parsed["Impression"] is None
        assert parsed["Recommendations"] is None


# ─────────────────────────────────────────────────────────────────
# 3. reporter() payload settings for CT
# ─────────────────────────────────────────────────────────────────
class TestCTPayloadSettings:
    def test_temperature_set_for_ct(self):
        src = _src()
        # Must appear in the in ("mri", "ct") guard context
        assert 'modality.lower() in ("mri", "ct")' in src
        assert 'payload["temperature"] = 0.1' in src

    def test_max_tokens_set_for_ct(self):
        src = _src()
        assert 'payload["max_tokens"] = 2500' in src

    def test_validate_called_for_ct_in_reporter(self):
        src = _src()
        # The validate guard must cover CT
        assert 'modality.lower() in ("mri", "ct")' in src
        assert '_validate_report_json(raw_content, modality.lower())' in src


# ─────────────────────────────────────────────────────────────────
# 4. Source-pin: CT block checklist phrases
# ─────────────────────────────────────────────────────────────────
class TestCTBlockSourcePins:
    def setup_method(self):
        self.block = _get_ct_block(_src()).lower()

    # Body-part coverage
    def test_brain_ct_noncontrast_present(self):
        assert "brain ct (non-contrast)" in self.block

    def test_brain_ct_with_contrast_present(self):
        assert "brain ct with contrast" in self.block

    def test_chest_ct_present(self):
        assert "chest ct" in self.block

    def test_neck_ct_present(self):
        assert "neck ct" in self.block

    def test_paranasal_sinus_present(self):
        assert "paranasal sinus" in self.block

    def test_abdomen_ct_present(self):
        assert "abdomen ct" in self.block

    def test_pelvis_ct_present(self):
        assert "pelvis ct" in self.block

    def test_abdominopelvic_ct_present(self):
        assert "abdominopelvic ct" in self.block

    def test_cervical_spine_ct_present(self):
        assert "cervical spine ct" in self.block

    def test_thoracic_spine_ct_present(self):
        assert "thoracic spine ct" in self.block

    def test_lumbar_spine_ct_present(self):
        assert "lumbar spine ct" in self.block

    def test_msk_shoulder_present(self):
        assert "msk ct shoulder" in self.block

    def test_msk_hip_present(self):
        assert "msk ct hip" in self.block

    def test_msk_knee_present(self):
        assert "msk ct knee" in self.block

    def test_msk_ankle_foot_present(self):
        assert "msk ct ankle and foot" in self.block

    def test_msk_wrist_hand_present(self):
        assert "msk ct wrist and hand" in self.block

    def test_coronary_cta_present(self):
        assert "coronary cta" in self.block

    def test_ct_aorta_present(self):
        assert "ct angiography aorta" in self.block

    def test_ct_kub_present(self):
        assert "ct urography and ct kub" in self.block

    # Pathological findings rules
    def test_pathological_findings_rules_header(self):
        assert "pathological findings rules" in self.block

    def test_imaging_manifestation_instruction(self):
        assert "imaging manifestation" in self.block

    def test_ct_measurement_rules_present(self):
        assert "ct-specific measurement" in self.block

    # Key normal findings phrases (lowercase)
    def test_brain_no_intracranial_haemorrhage(self):
        assert "no intracranial haemorrhage" in self.block

    def test_brain_ventricular_system(self):
        assert "ventricular system" in self.block

    def test_brain_no_midline_shift(self):
        assert "no midline shift" in self.block

    def test_cerebellum_phrase(self):
        assert "the cerebellum and brainstem show no focal" in self.block

    def test_orbits_phrase(self):
        assert "the orbits are normal in appearance" in self.block

    def test_chest_ground_glass(self):
        assert "ground-glass opacity" in self.block

    def test_chest_no_pleural_effusion(self):
        assert "no pleural effusion" in self.block

    def test_abdomen_no_free_fluid(self):
        assert "no pneumoperitoneum or intraperitoneal free fluid" in self.block

    def test_abdomen_liver_no_focal_lesion(self):
        assert "no focal hepatic lesion" in self.block

    def test_lumbar_no_spondylolisthesis(self):
        assert "no spondylolisthesis" in self.block

    def test_coronary_lad_patent(self):
        assert "left anterior descending artery (lad)" in self.block

    def test_impression_lock_rule_present(self):
        assert "impression / recommendations presence-lock" in self.block

    def test_output_format_section_present(self):
        assert "output format (strict)" in self.block

    def test_report_title_examples_present(self):
        assert "ct scan of the brain without contrast" in self.block

    def test_coronary_report_title_example(self):
        assert "coronary ct angiography" in self.block
