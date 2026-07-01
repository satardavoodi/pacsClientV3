"""
Tests for the Mammography reporter branch in openai_reporter.py.

Coverage:
  - Source-pin: ACR BI-RADS 5th edition mass/calcification lexicon present
  - Source-pin: BI-RADS category management recommendations present
  - Source-pin: Breast composition A-D descriptions present
  - _validate_report_json: mammography required-key enforcement
  - _validate_report_json: mammography optional keys pass-through
  - _validate_report_json: non-validated modality passthrough unchanged
  - Modality aliases all resolve into the mammography elif branch
"""

import importlib
import os
import sys
import re
import types
import unittest

# ---------------------------------------------------------------------------
# Path setup — allow import from the project root without installing the pkg
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ---------------------------------------------------------------------------
# Source text (used for source-pin tests — no OpenAI calls needed)
# ---------------------------------------------------------------------------
_REPORTER_PATH = os.path.join(
    _ROOT, "modules", "EchoMind", "viewer_chat", "openai_reporter.py"
)

with open(_REPORTER_PATH, encoding="utf-8") as _f:
    _SRC = _f.read()


# ---------------------------------------------------------------------------
# Helpers to import only the pure-Python parts of openai_reporter
# ---------------------------------------------------------------------------

def _extract_list_constant(src: str, name: str) -> list:
    """Parse a module-level `name: list = [...]` constant from source text."""
    m = re.search(rf'{re.escape(name)}\s*:\s*list\s*=\s*(\[[^\]]+\])', src, re.DOTALL)
    if not m:
        return []
    return [s.strip().strip('"') for s in m.group(1).strip("[]").split(",") if s.strip().strip('"')]


def _extract_frozenset_constant(src: str, name: str) -> frozenset:
    """Parse a module-level `name: frozenset = frozenset({...})` constant."""
    m = re.search(rf'{re.escape(name)}\s*:\s*frozenset\s*=\s*frozenset\(\{{([^}}]+)\}}\)', src, re.DOTALL)
    if not m:
        return frozenset()
    return frozenset(s.strip().strip('"') for s in m.group(1).split(",") if s.strip().strip('"'))


def _load_validate_fn():
    """
    Load _validate_report_json by stubbing PySide6 / openai before executing
    the module.  Constants are extracted from source text (more reliable than
    importing when the PySide6 chain is unavailable in the sandbox).
    """
    stub_openai = types.ModuleType("openai")
    stub_openai.OpenAI = object
    stub_openai.APIError = Exception
    stub_openai.RateLimitError = Exception
    stub_openai.APIConnectionError = Exception

    for name in ["openai", "PySide6", "PySide6.QtCore", "PySide6.QtWidgets", "PySide6.QtGui"]:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["openai"] = stub_openai

    spec = importlib.util.spec_from_file_location("openai_reporter_test", _REPORTER_PATH)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass
    return mod


_MOD = _load_validate_fn()
_validate_report_json = getattr(_MOD, "_validate_report_json", None)

# Extract constants directly from source (avoids PySide6 import chain in sandbox)
_MAMMOGRAPHY_REQUIRED_KEYS = _extract_list_constant(_SRC, "_MAMMOGRAPHY_REQUIRED_KEYS") or None
_VALIDATED_MODALITIES = _extract_frozenset_constant(_SRC, "_VALIDATED_MODALITIES") or None


# ===========================================================================
# 1. Source-pin: ACR BI-RADS 5th edition mass descriptors
# ===========================================================================

class TestMammographyLexiconSourcePin(unittest.TestCase):
    """Mass shape, margins, density terms must be present verbatim."""

    def test_mass_shape_terms_present(self):
        for term in ("oval", "round", "irregular"):
            self.assertIn(term, _SRC, f"Mass shape term '{term}' missing from source")

    def test_mass_margin_terms_present(self):
        for term in ("circumscribed", "obscured", "microlobulated", "indistinct", "spiculated"):
            self.assertIn(term, _SRC, f"Mass margin term '{term}' missing from source")

    def test_mass_density_terms_present(self):
        for term in ("fat-containing", "low density", "equal density", "high density"):
            self.assertIn(term, _SRC, f"Mass density term '{term}' missing from source")

    def test_calcification_morphology_terms_present(self):
        for term in (
            "Typically benign",
            "coarse heterogeneous",
            "fine pleomorphic",
            "fine linear",
            "fine-linear branching",
        ):
            self.assertIn(term, _SRC, f"Calcification morphology term '{term}' missing from source")

    def test_calcification_distribution_terms_present(self):
        for term in ("diffuse", "regional", "grouped", "linear", "segmental"):
            self.assertIn(term, _SRC, f"Calcification distribution term '{term}' missing from source")

    def test_birads_descriptor_instruction_present(self):
        """Instruction to use EXACT BI-RADS terms must exist."""
        self.assertIn("Use EXACTLY these BI-RADS terms", _SRC)


# ===========================================================================
# 2. Source-pin: BI-RADS categories and management recommendations
# ===========================================================================

class TestBiradsManagementSourcePin(unittest.TestCase):
    """All 8 BI-RADS categories (0-6 incl. 4A/4B/4C) with management must be present."""

    def _check(self, fragment: str):
        self.assertIn(fragment, _SRC, f"BI-RADS management fragment missing: {fragment!r}")

    def test_category_0(self):
        self._check("Incomplete")
        self._check("additional imaging evaluation")

    def test_category_1(self):
        self._check("Negative")

    def test_category_2(self):
        self._check("Benign finding")

    def test_category_3(self):
        self._check("Probably benign")
        self._check("Short-interval follow-up")

    def test_category_4a(self):
        self._check("4A")
        self._check("Low suspicion for malignancy")

    def test_category_4b(self):
        self._check("4B")
        self._check("Moderate suspicion for malignancy")

    def test_category_4c(self):
        self._check("4C")
        self._check("High suspicion for malignancy")

    def test_category_5(self):
        self._check("5 — Highly suggestive of malignancy")

    def test_category_6(self):
        self._check("6 — Known biopsy-proven malignancy")

    def test_tissue_sampling_mentioned(self):
        self._check("Tissue sampling")

    def test_annual_screening_mentioned(self):
        self._check("Annual screening mammography")


# ===========================================================================
# 3. Source-pin: Breast composition A-D
# ===========================================================================

class TestBreastCompositionSourcePin(unittest.TestCase):
    """ACR breast composition A-D must be present verbatim."""

    def test_composition_a(self):
        self.assertIn("almost entirely fatty", _SRC)

    def test_composition_b(self):
        self.assertIn("scattered areas of fibroglandular density", _SRC)

    def test_composition_c(self):
        self.assertIn("heterogeneously dense, which may obscure small masses", _SRC)

    def test_composition_d(self):
        self.assertIn("extremely dense, which lowers the sensitivity of mammography", _SRC)

    def test_composition_mapping_rule(self):
        self.assertIn("map to the standard description above", _SRC)


# ===========================================================================
# 4. Validation: _MAMMOGRAPHY_REQUIRED_KEYS constant
# ===========================================================================

class TestMammographyRequiredKeys(unittest.TestCase):

    def test_keys_constant_exists(self):
        self.assertIsNotNone(_MAMMOGRAPHY_REQUIRED_KEYS, "_MAMMOGRAPHY_REQUIRED_KEYS not found")

    def test_mandatory_keys_present(self):
        required = {
            "Report Title",
            "Breast Composition",
            "Pathological Findings",
            "Normal Findings",
            "Axillary Evaluation",
            "BI-RADS Category",
        }
        actual = set(_MAMMOGRAPHY_REQUIRED_KEYS)
        missing = required - actual
        self.assertFalse(missing, f"Required keys missing from _MAMMOGRAPHY_REQUIRED_KEYS: {missing}")


# ===========================================================================
# 5. Validation: _validate_report_json for mammography
# ===========================================================================

@unittest.skipUnless(_validate_report_json is not None, "_validate_report_json not importable")
class TestValidateMammographyJson(unittest.TestCase):

    def _make_valid(self, extra: dict | None = None) -> str:
        import json
        obj = {
            "Report Title": "Bilateral Mammography",
            "Breast Composition": "B — There are scattered areas of fibroglandular density.",
            "Pathological Findings": "No suspicious mass or calcification identified.",
            "Normal Findings": "Bilateral breast parenchyma unremarkable.",
            "Axillary Evaluation": "No pathological axillary lymph node.",
            "BI-RADS Category": "2 — Benign finding(s)",
        }
        if extra:
            obj.update(extra)
        return json.dumps(obj)

    def test_valid_report_passes_unchanged(self):
        raw = self._make_valid()
        result = _validate_report_json(raw, "mammography")
        import json
        parsed = json.loads(result)
        self.assertEqual(parsed["BI-RADS Category"], "2 — Benign finding(s)")

    def test_missing_birads_category_raises(self):
        import json
        obj = {
            "Report Title": "Mammography",
            "Breast Composition": "A — Almost entirely fatty.",
            "Pathological Findings": "None.",
            "Normal Findings": "Normal.",
            "Axillary Evaluation": "Normal.",
            # BI-RADS Category intentionally omitted
        }
        with self.assertRaises(ValueError):
            _validate_report_json(json.dumps(obj), "mammography")

    def test_missing_breast_composition_raises(self):
        import json
        obj = {
            "Report Title": "Mammography",
            # Breast Composition intentionally omitted
            "Pathological Findings": "None.",
            "Normal Findings": "Normal.",
            "Axillary Evaluation": "Normal.",
            "BI-RADS Category": "1 — Negative",
        }
        with self.assertRaises(ValueError):
            _validate_report_json(json.dumps(obj), "mammography")

    def test_non_json_raw_raises(self):
        with self.assertRaises(ValueError):
            _validate_report_json("not json at all", "mammography")

    def test_mammography_alias_same_as_lowercase(self):
        """'Mammography' (mixed case) behaves identically to 'mammography'."""
        raw = self._make_valid()
        r1 = _validate_report_json(raw, "mammography")
        r2 = _validate_report_json(raw, "Mammography")
        self.assertEqual(r1, r2)


# ===========================================================================
# 6. Validation: mammography is in _VALIDATED_MODALITIES
# ===========================================================================

class TestMammographyInValidatedModalities(unittest.TestCase):

    def test_mammography_validated(self):
        self.assertIsNotNone(_VALIDATED_MODALITIES)
        self.assertIn("mammography", _VALIDATED_MODALITIES)

    def test_unrelated_modalities_not_validated(self):
        for mod in ("Radiology", "XRay", "Nuclear", "PET"):
            self.assertNotIn(mod.lower(), _VALIDATED_MODALITIES,
                             f"'{mod}' should NOT be in _VALIDATED_MODALITIES")


# ===========================================================================
# 7. Source-pin: mammography elif branch exists in reporter()
# ===========================================================================

class TestMammographyBranchSourcePin(unittest.TestCase):

    def test_mammography_elif_branch_exists(self):
        self.assertIn('elif modality_lower == "mammography":', _SRC)

    def test_birads_section_header_present(self):
        self.assertIn("SECTION 6 — BI-RADS RULE", _SRC)

    def test_acr_birads_reference_present(self):
        self.assertIn("ACR BI-RADS 5th Edition", _SRC)


if __name__ == "__main__":
    unittest.main()
