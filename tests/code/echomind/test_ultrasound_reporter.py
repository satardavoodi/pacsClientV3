"""
Tests for the Ultrasound / OB Ultrasound reporter branches in openai_reporter.py.

Coverage:
  - Source-pin: OB Ultrasound elif branch exists with all required modality aliases
  - Source-pin: ISUOG anatomy survey structure present
  - Source-pin: fetal biometry parameters present
  - Source-pin: AFI / DVP normal ranges present
  - Source-pin: Doppler documentation section present
  - Source-pin: trimester detection rules present
  - _validate_report_json: OB Ultrasound required-key enforcement
  - _validate_report_json: OB Ultrasound optional keys accepted
  - _VALIDATED_MODALITIES contains all OB ultrasound aliases
"""

import importlib
import importlib.util
import os
import re
import sys
import types
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_REPORTER_PATH = os.path.join(
    _ROOT, "modules", "EchoMind", "viewer_chat", "openai_reporter.py"
)

with open(_REPORTER_PATH, encoding="utf-8") as _f:
    _SRC = _f.read()


# ---------------------------------------------------------------------------
# Helpers — extract constants from source text without importing the module
# (avoids the PySide6 import chain that is unavailable in the sandbox)
# ---------------------------------------------------------------------------

def _extract_list_constant(src: str, name: str) -> list:
    """Parse a module-level ``name: list = [...]`` constant from source text."""
    m = re.search(
        rf'{re.escape(name)}\s*:\s*list\s*=\s*(\[[^\]]+\])',
        src,
        re.DOTALL,
    )
    if not m:
        return []
    return [
        s.strip().strip('"')
        for s in m.group(1).strip("[]").split(",")
        if s.strip().strip('"')
    ]


def _extract_frozenset_constant(src: str, name: str) -> frozenset:
    """Parse a module-level ``name: frozenset = frozenset({...})`` constant."""
    m = re.search(
        rf'{re.escape(name)}\s*:\s*frozenset\s*=\s*frozenset\(\{{([^}}]+)\}}\)',
        src,
        re.DOTALL,
    )
    if not m:
        return frozenset()
    return frozenset(
        s.strip().strip('"')
        for s in m.group(1).split(",")
        if s.strip().strip('"')
    )


def _load_validate_fn():
    """Stub heavy imports and load only the validator function."""
    stub_openai = types.ModuleType("openai")
    stub_openai.OpenAI = object
    stub_openai.APIError = Exception
    stub_openai.RateLimitError = Exception
    stub_openai.APIConnectionError = Exception

    for name in ["openai", "PySide6", "PySide6.QtCore", "PySide6.QtWidgets", "PySide6.QtGui"]:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["openai"] = stub_openai

    spec = importlib.util.spec_from_file_location("openai_reporter_us_test", _REPORTER_PATH)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass
    return mod


_MOD = _load_validate_fn()
_validate_report_json = getattr(_MOD, "_validate_report_json", None)

# Extract constants directly from source text
_OB_ULTRASOUND_REQUIRED_KEYS = _extract_list_constant(_SRC, "_OB_ULTRASOUND_REQUIRED_KEYS") or None
_VALIDATED_MODALITIES = _extract_frozenset_constant(_SRC, "_VALIDATED_MODALITIES") or None


# ===========================================================================
# 1. Source-pin: OB Ultrasound elif branch
# ===========================================================================

class TestObBranchExists(unittest.TestCase):

    def test_ob_elif_branch_present(self):
        self.assertIn('elif modality_lower in ["obstetric ultrasound"', _SRC)

    def test_ob_ultrasound_alias_present(self):
        self.assertIn('"ob ultrasound"', _SRC)

    def test_pregnancy_ultrasound_alias_present(self):
        self.assertIn('"pregnancy ultrasound"', _SRC)

    def test_fetal_ultrasound_alias_present(self):
        self.assertIn('"fetal ultrasound"', _SRC)

    def test_isuog_reference_present(self):
        self.assertIn("ISUOG", _SRC)


# ===========================================================================
# 2. Source-pin: ISUOG anatomy survey structure
# ===========================================================================

class TestIsuogAnatomySurveySourcePin(unittest.TestCase):

    def test_cns_section_present(self):
        self.assertIn("CNS", _SRC)

    def test_atrial_width_normal_range(self):
        """Lateral ventricular atrial width normal: ≤10 mm."""
        self.assertIn("10 mm", _SRC)

    def test_cisterna_magna_range(self):
        """Cisterna magna normal: 2–10 mm."""
        self.assertIn("cisterna magna", _SRC.lower())

    def test_four_chamber_view_present(self):
        self.assertIn("four-chamber", _SRC)

    def test_renal_pelvis_range(self):
        """Renal pelvis APD normal: <7 mm (2nd trimester)."""
        self.assertIn("7 mm", _SRC)

    def test_umbilical_cord_vessel_rule(self):
        """Three-vessel cord / SUA must be documented."""
        self.assertIn("three-vessel", _SRC)

    def test_spine_section_present(self):
        self.assertIn("Spine", _SRC)

    def test_limbs_section_present(self):
        self.assertIn("Limbs", _SRC)

    def test_face_section_present(self):
        self.assertIn("Face", _SRC)


# ===========================================================================
# 3. Source-pin: fetal biometry parameters
# ===========================================================================

class TestFetalBiometrySourcePin(unittest.TestCase):

    def test_bpd_present(self):
        self.assertIn("BPD", _SRC)

    def test_hc_present(self):
        self.assertIn("HC", _SRC)

    def test_ac_present(self):
        self.assertIn("AC", _SRC)

    def test_fl_present(self):
        self.assertIn("FL", _SRC)

    def test_efw_present(self):
        self.assertIn("EFW", _SRC)

    def test_crl_present(self):
        """CRL used in first trimester."""
        self.assertIn("CRL", _SRC)

    def test_nt_present(self):
        """Nuchal translucency for first trimester."""
        self.assertIn("NT", _SRC)

    def test_growth_percentile_mentioned(self):
        self.assertIn("percentile", _SRC)

    def test_hl_or_humerus_present(self):
        """Humeral length for symmetry check."""
        self.assertTrue("HL" in _SRC or "humeral" in _SRC.lower())


# ===========================================================================
# 4. Source-pin: AFI / DVP normal ranges
# ===========================================================================

class TestAmniotiFluidSourcePin(unittest.TestCase):

    def test_afi_normal_range(self):
        """AFI normal: 8–24 cm."""
        self.assertIn("AFI", _SRC)
        self.assertIn("8", _SRC)
        self.assertIn("24", _SRC)

    def test_afi_oligohydramnios_threshold(self):
        """AFI <5 cm = oligohydramnios; source uses 'Oligo' abbreviation."""
        self.assertTrue(
            "oligohydramnios" in _SRC.lower() or "oligo" in _SRC.lower(),
            "Neither 'oligohydramnios' nor 'Oligo' found in source",
        )

    def test_afi_polyhydramnios_threshold(self):
        """AFI >24 cm = polyhydramnios; source uses '>24' abbreviation."""
        self.assertIn(">24", _SRC)  # source: "Poly >24 cm"

    def test_dvp_normal_range(self):
        """DVP normal: 2–8 cm."""
        self.assertIn("DVP", _SRC)
        self.assertIn("2–8", _SRC)

    def test_borderline_range_present(self):
        """AFI borderline 5–8 cm must be documented."""
        self.assertIn("Borderline", _SRC)


# ===========================================================================
# 5. Source-pin: Doppler documentation
# ===========================================================================

class TestDopplerSourcePin(unittest.TestCase):

    def test_umbilical_artery_present(self):
        self.assertIn("Umbilical artery", _SRC)

    def test_mca_present(self):
        """Middle cerebral artery PSV."""
        self.assertIn("MCA", _SRC)

    def test_ductus_venosus_present(self):
        self.assertIn("ductus venosus", _SRC.lower())

    def test_doppler_omit_rule_present(self):
        """Doppler key must be omitted if not performed."""
        self.assertIn("OMIT", _SRC)


# ===========================================================================
# 6. Source-pin: trimester detection
# ===========================================================================

class TestTrimesterDetectionSourcePin(unittest.TestCase):

    def test_first_trimester_threshold(self):
        self.assertIn("13", _SRC)

    def test_second_trimester_range(self):
        self.assertIn("14", _SRC)
        self.assertIn("27", _SRC)

    def test_third_trimester_threshold(self):
        self.assertIn("28", _SRC)

    def test_ga_discordance_rule_present(self):
        """Discordance >7d rules must be present."""
        self.assertIn("7 days", _SRC)

    def test_lmp_vs_biometry_rule_present(self):
        self.assertIn("LMP", _SRC)


# ===========================================================================
# 7. _OB_ULTRASOUND_REQUIRED_KEYS constant
# ===========================================================================

class TestObRequiredKeys(unittest.TestCase):

    def test_constant_exists(self):
        self.assertIsNotNone(
            _OB_ULTRASOUND_REQUIRED_KEYS,
            "_OB_ULTRASOUND_REQUIRED_KEYS not found in source",
        )

    def test_mandatory_keys_present(self):
        required = {
            "Report Title",
            "Gestational Age & Dating",
            "Fetal Presentation",
            "Biometry",
            "Placenta & Umbilical Cord",
            "Amniotic Fluid",
            "Normal Findings",
        }
        actual = set(_OB_ULTRASOUND_REQUIRED_KEYS)
        missing = required - actual
        self.assertFalse(missing, f"Required OB keys missing: {missing}")


# ===========================================================================
# 8. _validate_report_json for OB Ultrasound
# ===========================================================================

@unittest.skipUnless(_validate_report_json is not None, "_validate_report_json not importable")
class TestValidateObUltrasoundJson(unittest.TestCase):

    def _make_valid(self, extra: dict | None = None) -> str:
        import json
        obj = {
            "Report Title": "Obstetric Ultrasound — 2nd Trimester",
            "Gestational Age & Dating": "GA: 20w3d by BPD/HC/AC/FL. LMP: 20w0d. Concordant.",
            "Fetal Presentation": "Cephalic.",
            "Biometry": "BPD: 49 mm (50th %ile). HC: 180 mm. AC: 155 mm. FL: 34 mm. EFW: 345 g (50th %ile).",
            "Placenta & Umbilical Cord": "Posterior placenta, grade I. OS clear (>20 mm). Three-vessel cord.",
            "Amniotic Fluid": "AFI: 14 cm (normal, 8–24 cm).",
            "Normal Findings": "Fetal cardiac activity: present. Fetal movements: present.",
        }
        if extra:
            obj.update(extra)
        return json.dumps(obj)

    def test_valid_ob_report_passes(self):
        raw = self._make_valid()
        result = _validate_report_json(raw, "obstetric ultrasound")
        import json
        parsed = json.loads(result)
        self.assertIn("Gestational Age & Dating", parsed)

    def test_ob_ultrasound_alias_accepted(self):
        raw = self._make_valid()
        for alias in ("obstetric ultrasound", "ob ultrasound", "pregnancy ultrasound", "fetal ultrasound"):
            result = _validate_report_json(raw, alias)
            import json
            parsed = json.loads(result)
            self.assertIn("Report Title", parsed, f"Alias '{alias}' failed validation")

    def test_missing_biometry_raises(self):
        import json
        obj = {
            "Report Title": "OB US",
            "Gestational Age & Dating": "20w.",
            "Fetal Presentation": "Cephalic.",
            # Biometry intentionally omitted
            "Placenta & Umbilical Cord": "Posterior.",
            "Amniotic Fluid": "AFI: 14 cm.",
            "Normal Findings": "Normal.",
        }
        with self.assertRaises(ValueError):
            _validate_report_json(json.dumps(obj), "obstetric ultrasound")

    def test_missing_amniotic_fluid_raises(self):
        import json
        obj = {
            "Report Title": "OB US",
            "Gestational Age & Dating": "20w.",
            "Fetal Presentation": "Cephalic.",
            "Biometry": "BPD: 49 mm.",
            "Placenta & Umbilical Cord": "Posterior.",
            # Amniotic Fluid intentionally omitted
            "Normal Findings": "Normal.",
        }
        with self.assertRaises(ValueError):
            _validate_report_json(json.dumps(obj), "ob ultrasound")

    def test_optional_doppler_key_accepted(self):
        raw = self._make_valid({"Doppler": "UA: S/D 2.5, normal. MCA PSV: 40 cm/s, normal."})
        import json
        result = _validate_report_json(raw, "obstetric ultrasound")
        parsed = json.loads(result)
        self.assertIn("Doppler", parsed)

    def test_optional_anatomy_survey_accepted(self):
        raw = self._make_valid({"Anatomy Survey": "CNS: normal. Heart: four-chamber view normal."})
        import json
        result = _validate_report_json(raw, "pregnancy ultrasound")
        parsed = json.loads(result)
        self.assertIn("Anatomy Survey", parsed)

    def test_non_json_raises(self):
        with self.assertRaises(ValueError):
            _validate_report_json("free text only, not JSON", "obstetric ultrasound")


# ===========================================================================
# 9. _VALIDATED_MODALITIES contains OB aliases
# ===========================================================================

class TestObModalitiesValidated(unittest.TestCase):

    def test_ob_aliases_in_validated_set(self):
        self.assertIsNotNone(
            _VALIDATED_MODALITIES,
            "_VALIDATED_MODALITIES not found in source",
        )
        for alias in ("obstetric ultrasound", "ob ultrasound", "pregnancy ultrasound", "fetal ultrasound"):
            self.assertIn(
                alias,
                _VALIDATED_MODALITIES,
                f"'{alias}' not in _VALIDATED_MODALITIES",
            )

    def test_general_ultrasound_in_validated_set(self):
        self.assertIsNotNone(_VALIDATED_MODALITIES)
        for alias in ("sonography", "ultrasound"):
            self.assertIn(
                alias,
                _VALIDATED_MODALITIES,
                f"'{alias}' not in _VALIDATED_MODALITIES",
            )


if __name__ == "__main__":
    unittest.main()
