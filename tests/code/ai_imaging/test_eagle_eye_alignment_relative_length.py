"""Relative projected length is scale invariant, aspect aware and directional."""
import math
import pytest
from test_eagle_eye_alignment import points, image, qapp
from modules.ai_imaging.eagle_eye_alignment.geometry import measure_bilateral


def shortened():
    p = {'R': points(), 'L': points('L')}
    for key in ('ankle_lateral', 'ankle_medial'):
        p['R'][key][1] -= 80
    return p


def test_relative_length_uses_longer_denominator_and_common_scale_cancels():
    for spacing in ((1, 1), (.1, .1), (2, 2)):
        for calibrated in (False, True):
            m = measure_bilateral(shortened(), spacing, calibrated=calibrated)
            assert m['lld_percent'] == pytest.approx(10)
            assert m['shorter_side'] == 'R'
    m = measure_bilateral({'R': points(), 'L': points('L')})
    assert m['lld_percent'] == 0 and m['shorter_side'] == 'equal'


def test_relative_length_retains_aspect_without_patient_plane_calibration():
    p = shortened()
    for key in ('ankle_lateral', 'ankle_medial'):
        p['R'][key][0] += 100
    expected = 100 * (800 - math.hypot(720, 200)) / 800
    m = measure_bilateral(p, (1, 2), calibrated=False)
    assert m['lld_percent'] == pytest.approx(expected)
    assert m['lld_percent'] == pytest.approx(measure_bilateral(p, (.2, .4), calibrated=True)['lld_percent'])
    mirrored = {s: {key: [400-v[0], v[1]] for key, v in p[other].items()}
                for s, other in (('R', 'L'), ('L', 'R'))}
    swapped = measure_bilateral(mirrored, (1, 2))
    assert swapped['lld_percent'] == pytest.approx(expected)
    assert swapped['shorter_side'] == 'L'


def test_relative_length_recalculates_in_widget_and_pdf(qapp):
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    from modules.ai_imaging.eagle_eye_alignment.report import render_html
    w = AlignmentWidget(study_uid='1.2.3')
    w._apply_image(image()); w.points = shortened(); w._redraw_points()
    assert '10.00% (Right shorter)' in w.summary.text()
    assert '10.00% (Right shorter)' in render_html(w.image, w.points, {})
    w.points['R'] = points(); w._redraw_points()
    assert '0.00% (Equal projected lengths)' in w.summary.text()
    w.teardown(); w.deleteLater(); qapp.processEvents()
