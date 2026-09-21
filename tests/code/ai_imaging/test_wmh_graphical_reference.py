"""Synthetic contracts for approximate WMH references, without patient fixtures."""
import math
import pytest

from modules.ai_imaging.eagle_eye_brain.wmh_fraction import graphical_reference
from modules.ai_imaging.eagle_eye_brain.wmh_reference import reference_status, reference_html
from modules.ai_imaging.eagle_eye_brain.rotterdam_curve_data import LOG_QUANTILES


def test_published_curves_are_ordered_at_every_grid_point():
    for rows in LOG_QUANTILES.values():
        assert len(rows) == 8
        for row in rows:
            assert len(row) == 7
            assert all(a < b for a, b in zip(row, row[1:]))


@pytest.mark.parametrize('age', [17, 49.9, 85.1, None, True, float('nan')])
def test_no_age_extrapolation(age):
    assert graphical_reference(age, 'F', .1)['status'] == 'unavailable'


def test_zero_and_boundaries_have_bands_without_exact_scores():
    zero = graphical_reference(65, 'F', 0)
    assert zero['band'] == 'Below P5'
    assert not zero['boundary_sensitive']
    at = graphical_reference(65, 'F', zero['quantiles_percent'][50])
    assert at['boundary_sensitive']
    assert at['percentile_lower'] == 25 and at['percentile_upper'] == 75
    assert at['exact_percentile'] is None and at['z_score'] is None
    assert not at['clinical_qualification']


def test_log_interpolation_and_upper_endpoint():
    a = graphical_reference(60, 'M', .1)['quantiles_percent']
    b = graphical_reference(65, 'M', .1)['quantiles_percent']
    middle = graphical_reference(62.5, 'M', .1)['quantiles_percent']
    assert middle[50] == pytest.approx(math.sqrt(a[50] * b[50]))
    assert graphical_reference(85, 'M', .1)['status'] == 'approximate_graphical_band'


def test_report_recomputes_fraction_and_ignores_cached_scores():
    result = dict(age_years=65, sex='F', metrics={'total_volume_cm3': 1},
                  svd_spatial={'candidate_fractions': dict(candidate_volume_ml=1, icv_ml=1000,
                                                         icv_percent=99)},
                  wmh_reference={'percentile': 99})
    status = reference_status(result)
    assert status['icv_percent'] == .1 and status['percentile'] is None
    html = reference_html(result)
    assert '0.1000%' in html and '10.1161/STROKEAHA.124.046731' in html
    assert 'method bias is not quantified' in html
    result['metrics']['total_volume_cm3'] = 2
    assert reference_status(result)['status'] == 'not_calculated'
