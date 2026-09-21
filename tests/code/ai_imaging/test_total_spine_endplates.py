"""Focused endplate workflow guards using synthetic coordinates only."""
import pytest
from modules.ai_imaging.eagle_eye_total_spine.geometry import measure_curve, suggest_apex


def test_curve_needs_only_two_selected_endplates():
    points = {'L1': {'superior_left': [10, 10], 'superior_right': [30, 20]},
              'S1': {'superior_left': [10, 100], 'superior_right': [30, 90]}}
    result = measure_curve(points, 'L1', 'S1', lower_endplate='superior')
    assert result['cobb_deg'] == pytest.approx(53.130102)
    assert suggest_apex(points, 'L1', 'S1') is None


def test_partial_endplate_rejects_reversed_handles():
    p = {'L1': {'superior_left': [30, 10], 'superior_right': [10, 20]},
         'L5': {'inferior_left': [10, 100], 'inferior_right': [30, 90]}}
    with pytest.raises(ValueError, match='left'):
        measure_curve(p, 'L1', 'L5')


from copy import deepcopy
import threading
import numpy as np
from modules.ai_imaging.eagle_eye_total_spine.review_workflow import curve_evidence, curve_is_reviewed, predict_region
from modules.ai_imaging.eagle_eye_total_spine.measurements import measure_view, validate_report_views


def snapshot():
    return dict(image=dict(pixels=np.zeros((200, 200), dtype=np.uint8), spacing=(1., 1.),
                           identity=dict(study_uid='1', series_uid='2', sop_uid='3'),
                           source_sha256='synthetic', projection='lateral', calibrated=False, calibration_method='Synthetic'),
                points={'L1': {'superior_left': [10, 10], 'superior_right': [30, 20]},
                        'S1': {'superior_left': [10, 100], 'superior_right': [30, 90]}},
                curves=[dict(name='Lumbar lordosis', upper='L1', lower='S1', lower_endplate='superior')],
                acquisition_confirmed=True, landmarks_reviewed=True, review_protocol='selected-endplates-v1')


def test_review_requires_selected_pair_and_changes_revoke_confirmation():
    v = snapshot(); spec = v['curves'][0]
    with pytest.raises(ValueError, match='Confirm the selected'):
        validate_report_views([v], '1', reviewed=True)
    spec['review_signature'] = curve_evidence(v, spec)
    assert validate_report_views([v], '1', reviewed=True)[0]['curves'][0]['endplates_reviewed']
    v['points']['L1']['superior_left'][1] += 2
    assert not curve_is_reviewed(v, spec)
    with pytest.raises(ValueError): validate_report_views([v], '1', reviewed=True)


def test_unused_points_do_not_block_or_revoke_curve_review():
    v = snapshot(); spec = v['curves'][0]; spec['review_signature'] = curve_evidence(v, spec)
    v['points']['T4'] = {'superior_left': [-100, -100]}
    assert curve_is_reviewed(v, spec)
    assert len(measure_view(v)['curves']) == 1


def test_region_mapping_preserves_identity_and_excludes_outside_candidates():
    v = snapshot(); seen = []
    def predictor(image, cancel):
        seen.append(image['pixels'].shape)
        return {'candidates': [dict(corners=[[1, 2], [20, 2], [1, 25], [20, 25]], confidence=.8),
                               dict(corners=[[-1, 2], [20, 2], [1, 25], [20, 25]], confidence=.9)]}
    result = predict_region(v['image'], [30, 40, 130, 170], threading.Event(), predictor)
    assert seen == [(130, 100)] and len(result['candidates']) == 1
    assert result['candidates'][0]['corners'][0] == [31, 42]
    assert result['binding']['source_sha256'] == 'synthetic'


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_editor_two_endplates_auto_advance_and_review(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    e = ProjectionEditor('lateral'); v = snapshot(); e.accept_image(v['image'])
    e.confirm.setChecked(True); e.kind.setCurrentText('Lumbar lordosis')
    e._edit_required(False)
    assert e.canvas.manual_target == ('L1', 'superior_left')
    assert 'L1' in e.placement.text() and 'superior' in e.placement.text()
    e._point_changed('L1', 'superior_left', 10, 10)
    assert e.canvas.manual_target == ('L1', 'superior_right')
    e._point_changed('L1', 'superior_right', 30, 20)
    assert e.canvas.manual_target is None
    e._edit_required(True)
    e._point_changed('S1', 'superior_left', 10, 100)
    e._point_changed('S1', 'superior_right', 30, 90)
    e._add_curve(); assert len(e.curves) == 1
    e.table.selectRow(0); e._confirm_curve()
    assert curve_is_reviewed(e.snapshot(), e.curves[0])
    e._point_changed('L1', 'superior_right', 30, 25)
    assert not curve_is_reviewed(e.snapshot(), e.curves[0])
    e.close()


def test_candidates_do_not_overwrite_manual_points_and_scene_resets(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    e = ProjectionEditor('coronal'); e.accept_image(snapshot()['image'])
    candidate = dict(corners=[[20, 20], [50, 20], [20, 40], [50, 40]])
    e.accept_candidates({'candidates': [candidate]})
    assert not e.points
    e.level.setCurrentText('L4'); e._assign_candidate()
    assert 'L4' in e.points and not e.candidates
    original = deepcopy(e.points)
    e.accept_candidates({'candidates': [candidate]}); e._assign_candidate()
    assert e.points == original and len(e.candidates) == 1
    e.clear_image(); assert not e.candidates and not e.points
    e.close()


def test_superior_blue_inferior_yellow_and_visible_level_labels(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import SpineCanvas
    c = SpineCanvas(); c.load(np.zeros((200, 200), dtype=np.uint8))
    c.set_points({'L5': dict(superior_left=[10, 10], superior_right=[30, 10], inferior_left=[10, 30], inferior_right=[30, 30])})
    assert c.items_by_key['L5', 'superior_left'].brush().color().name() == '#38bdf8'
    assert c.items_by_key['L5', 'inferior_left'].brush().color().name() == '#fbbf24'
    labels = [i.text() for i in c.lines if hasattr(i, 'text')]
    assert 'L5 superior' in labels and 'L5 inferior' in labels
    c.close()


def test_actual_mouse_region_and_partial_endplate_input(qapp):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    e = ProjectionEditor('coronal'); e.resize(1200, 900); e.show()
    e.accept_image(snapshot()['image']); qapp.processEvents(); e.canvas.fit()
    e._select_region()
    for x, y in ((20, 20), (180, 180)):
        QTest.mouseClick(e.canvas.viewport(), Qt.LeftButton, pos=e.canvas.mapFromScene(QPointF(x, y)))
    assert e.region == pytest.approx([20, 20, 180, 180], abs=1)
    e.level.setCurrentText('L5'); e.corner.setCurrentText('inferior_left')
    for x, y in ((50, 80), (100, 90)):
        QTest.mouseClick(e.canvas.viewport(), Qt.LeftButton, pos=e.canvas.mapFromScene(QPointF(x, y)))
    assert set(e.points['L5']) == {'inferior_left', 'inferior_right'}
    assert e.canvas.manual_target is None
    e.close()


def test_aspect_change_revokes_selected_curve_confirmation():
    v = snapshot(); spec = v['curves'][0]; spec['review_signature'] = curve_evidence(v, spec)
    v['image']['spacing'] = (.5, 1.)
    assert not curve_is_reviewed(v, spec)
    assert measure_view(v)['curves'][0]['cobb_deg'] == pytest.approx(28.072486)


def test_partial_reviewed_report_has_only_selected_endplate_requirement(tmp_path):
    from modules.ai_imaging.eagle_eye_total_spine.report import render_html
    v = snapshot(); spec = v['curves'][0]; spec['review_signature'] = curve_evidence(v, spec)
    measured = validate_report_views([v], '1', reviewed=True)
    html = render_html([v], measured, True, '')
    assert 'Lumbar lordosis' in html and '53.1' in html


def test_refine_lower_roi_discards_stale_proposals_preserves_manual_points(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    e = ProjectionEditor('coronal'); e.accept_image(snapshot()['image'])
    assert e._set_region([10, 10, 190, 190])
    e.points = {'L5': {'superior_left': [40, 100], 'superior_right': [80, 100]}}
    saved = deepcopy(e.points)
    e.accept_candidates({'candidates': [dict(corners=[[30, 130], [60, 130], [30, 160], [60, 160]])]})
    e._select_region_edge('bottom'); e._point_changed('region', 'bottom', 100, 120)
    assert e.region == [10, 10, 190, 120] and not e.candidates
    assert e.points == saved and e.canvas.manual_target is None
    assert not e._set_region([10, 10, 190, 20])
    assert e.region == [10, 10, 190, 120]
    e.close()


def test_lower_roi_excludes_pixels_below_cutoff_before_inference():
    v = snapshot(); v['image']['pixels'][120:] = 255
    def predictor(image, cancel):
        assert image['pixels'].shape == (100, 160)
        assert not image['pixels'].any()
        return {'candidates': []}
    result = predict_region(v['image'], [20, 20, 180, 120], threading.Event(), predictor)
    assert result['region'] == [20, 20, 180, 120]
