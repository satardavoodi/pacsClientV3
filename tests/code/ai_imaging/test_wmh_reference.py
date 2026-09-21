"""Synthetic normalization contracts; no invented normative model or patient data."""
import pytest

from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
from modules.ai_imaging.eagle_eye_brain.wmh_reference import (
    normalize_volume_ml, reference_status, reference_html,
)


def test_normalization_scales_with_head_size_and_preserves_zero():
    assert normalize_volume_ml(2, 1409) == 2
    assert normalize_volume_ml(2, 2818) == 1
    assert normalize_volume_ml(0, 1409) == 0


@pytest.mark.parametrize('volume,tiv', [(1, 0), (-1, 1409), (1500, 1409),
                                     (float('nan'), 1409), (1, float('inf')),
                                     (True, 1409), (1, '1409')])
def test_invalid_units_or_values_do_not_produce_output(volume, tiv):
    with pytest.raises(BrainError):
        normalize_volume_ml(volume, tiv)


@pytest.mark.parametrize('age,expected', [(66, 'within reference age range'),
    (40, 'within reference age range'), (95, 'within reference age range'),
    (17, 'outside reference age range'), (96, 'outside reference age range'),
    (None, 'not supplied'), (float('nan'), 'not supplied'), (True, 'not supplied')])
def test_eligibility_never_fabricates_percentile(age, expected):
    result = dict(age_years=age, sex='F', wmh_reference={'percentile': 99})
    status = reference_status(result)
    assert status['age_status'] == expected
    assert status['percentile'] is None and status['normalized_volume_ml'] is None
    assert status['status'] == 'not_calculated'
    assert 'SPM12' in reference_html(result)


def test_svd_pdf_explains_missing_model_instead_of_missing_age():
    from modules.ai_imaging.eagle_eye_brain.svd_assessment import svd_pages
    pages = svd_pages(dict(age_years=66, sex='F', clinical_context={'primary_disease': 'svd'}))
    assert 'within reference age range' in pages[0]
    assert 'GAMLSS model is not installed' in pages[0]
    assert '10.3390/diagnostics16152460' in pages[0]
    assert svd_pages({'clinical_context': {'primary_disease': 'ms'}}) == []
