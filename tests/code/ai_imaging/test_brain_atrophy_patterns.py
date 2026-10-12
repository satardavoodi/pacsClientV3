"""Synthetic regional reference plots never become disease classifiers."""
import base64
import copy
import pytest


def fixture():
    return dict(normative=dict(reference_id='volbrain', status='published_intervals',
        demographics=dict(age_years=74, sex='male'), rows=[
            dict(structure='left hippocampus', observed_cm3=2., lower_cm3=3., median_cm3=4., upper_cm3=5., mapping_status='cross_method'),
            dict(structure='ctx-lh-entorhinal', observed_cm3=1., lower_cm3=2., median_cm3=3., upper_cm3=4., mapping_status='anatomical_analogue')]),
        posterior_rows=[dict(structure='left hippocampus', volume_cm3=2.),
                        dict(structure='ctx-lh-entorhinal', volume_cm3=1.)])


def test_chart_preserves_physical_volumes_and_does_not_invent_centiles():
    from modules.ai_imaging.eagle_eye_brain.atrophy_patterns import chart_rows, pages
    result = fixture(); original = copy.deepcopy(result)
    rows = chart_rows(result)
    assert rows[0]['observed_relative'] == 50
    assert rows[0]['lower_relative'] == 75
    assert rows[1]['analogue']
    html = ''.join(pages(result))
    assert 'not a percentile' in html
    assert 'probability is not calculated' in html
    assert 'anatomical analogue' in html
    assert 'Hippocampus L: 2.000 cm3; below interval' in html
    assert 'patterns remain unclassified' in html
    assert result == original


@pytest.mark.parametrize('bad', [None, float('nan'), -1, True])
def test_invalid_reference_and_unmatched_volume_never_plotted(bad):
    from modules.ai_imaging.eagle_eye_brain.atrophy_patterns import chart_rows
    result = fixture()
    result['normative']['rows'][0]['median_cm3'] = bad
    assert len(chart_rows(result)) == 1
    result = fixture(); result['posterior_rows'][0]['volume_cm3'] = 99
    assert len(chart_rows(result)) == 1


def test_missing_reference_not_treated_as_normal_or_absent_disease():
    from modules.ai_imaging.eagle_eye_brain.atrophy_patterns import pages
    html = ''.join(pages(dict(posterior_rows=[])))
    assert 'reference unavailable' in html
    assert 'cannot establish or exclude' in html
    assert '10.1093/brain/awr179' in html
    assert 'github' not in html.lower()


def test_plot_png_is_real_and_labels_analogue_separately():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage
    from modules.ai_imaging.eagle_eye_brain.atrophy_patterns import chart_png, chart_rows
    app = QApplication.instance() or QApplication([])
    png = chart_png(chart_rows(fixture()))
    image = QImage.fromData(base64.b64decode(png))
    assert not image.isNull() and image.width() == 1200
