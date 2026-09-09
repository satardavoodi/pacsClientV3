"""Synthetic report grouping: preserve compartments and incomplete coverage."""
import pytest


def _rows():
    from modules.ai_imaging.eagle_eye_brain.anatomical_groups import CORTICAL_GROUPS
    return ([{"structure": f"ctx-{side}-{name}", "volume_cm3": value}
             for _, names in CORTICAL_GROUPS for name in names
             for side, value in (("lh", 2.0), ("rh", 3.0))]
            + [{"structure": "total intracranial", "volume_cm3": 1000.0},
               {"structure": "left cerebral cortex", "volume_cm3": 900.0}])


def test_cortical_sums_exclude_parent_and_white_matter():
    from modules.ai_imaging.eagle_eye_brain.anatomical_groups import cortical_summaries
    summaries = cortical_summaries(_rows())
    assert len(summaries) == 6
    frontal = summaries[0]
    assert frontal["left_cm3"] == 22
    assert frontal["right_cm3"] == 33
    assert frontal["total_cm3"] == 55
    assert frontal["icv_percent"] == pytest.approx(5.5)
    assert sum(r["total_cm3"] for r in summaries) == 170
    assert summaries[4]["structure"] == "Cingulate cortex"


def test_missing_parcel_does_not_become_zero_or_complete_lobe():
    from modules.ai_imaging.eagle_eye_brain.anatomical_groups import cortical_summaries
    rows = [r for r in _rows() if r["structure"] != "ctx-lh-precentral"]
    frontal = cortical_summaries(rows)[0]
    assert frontal["left_cm3"] is None
    assert frontal["right_cm3"] == 33
    assert frontal["total_cm3"] is None
    assert frontal["icv_percent"] is None
    assert frontal["left_coverage"] == "10/11"


def test_report_distinguishes_cortex_white_matter_and_unmeasured_thickness():
    from modules.ai_imaging.eagle_eye_brain.organized_report import _lobar_summary
    html = _lobar_summary({"posterior_rows": _rows()})
    assert "Lobar and regional cortical summary" in html
    assert "Cingulate cortex" in html and "Insular cortex" in html
    assert "Hemisphere white matter</h2>" not in html
    assert "Lobar white matter: not separately measured" in html
    assert "Cortical thickness: not measured" in html
    assert "No matched age/sex reference" in html
    assert "55.000" in html
